"""
Pipeline OCR : extraction de données tabulaires depuis un PDF scanné.

Responsabilités :
- Corrections automatiques d'erreurs OCR courantes
- Extraction et normalisation de tokens numériques
- Prétraitement d'image (deskew, binarisation, débruitage)
- Orchestration page par page avec support d'annulation

Ce module ne contient **aucune** logique d'interface.
"""

from __future__ import annotations

import os
import re
import threading
from typing import Callable

import numpy as np
import pandas as pd
import pytesseract
from pdf2image import convert_from_path
from PIL import Image

from config import CFG, COLONNES, POPPLER_PATH, TESSERACT_PATH

pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

# Optionnel : OpenCV pour le prétraitement avancé
try:
    import cv2
    _CV2_OK = True
except ImportError:
    _CV2_OK = False

# ──────────────────────────────────────────────────────────────────────────────
#  Expressions régulières
# ──────────────────────────────────────────────────────────────────────────────

TOKEN_RE = re.compile(r'NaN|[-+]?\d+\.\d+|[-+]?\d+')
ML_MAX   = 50.0

JUNK_PATTERNS = re.compile(
    r'(METTLER|TOLEDO|Version|serie|titreur|Utilisateur|'
    r'Page\s+\d|Date\s*/|heure|MARION|Excell?|ID du)',
    re.IGNORECASE,
)

LogCallback = Callable[[str], None]


# ──────────────────────────────────────────────────────────────────────────────
#  Corrections OCR textuelles
# ──────────────────────────────────────────────────────────────────────────────

def fix_ocr_line(line: str) -> str:
    """Corrige les artefacts OCR courants dans une ligne de texte brut."""
    line = re.sub(r'\.\.+', '.', line)

    def _fix_slash(m: re.Match) -> str:
        a, b = m.group(1), m.group(2)
        candidate = a + '.' + b
        if len(a) >= 2 and a[0] == a[1]:
            dedup = a[0] + '.' + a[1:] + b
            try:
                if float(dedup) <= 14.0:
                    return dedup
            except ValueError:
                pass
        return candidate

    line = re.sub(r'(\d+)/(\d+)', _fix_slash, line)
    line = re.sub(r'(\d):( ?(\d))', lambda m: m.group(1) + '.' + m.group(2).strip(), line)
    line = re.sub(r'(\d)°', r'\1', line)
    line = re.sub(r'~(-?)', r'\1', line)
    line = re.sub(r'__+', ' ', line)
    return line


def _try_insert_dot(s: str, lo: float, hi: float) -> str | None:
    """Tente d'insérer un point décimal manquant dans un token."""
    if '.' in s:
        return None
    sign   = s[0] if s and s[0] in '+-' else ''
    digits = s.lstrip('+-')
    if len(digits) < 2:
        return None
    candidates: list[str] = []
    for pos in range(1, len(digits)):
        candidate = sign + digits[:pos] + '.' + digits[pos:]
        try:
            if lo <= float(candidate) <= hi:
                candidates.append(candidate)
        except ValueError:
            pass
    return candidates[0] if len(candidates) == 1 else None


def fix_ml_decimal(tokens: list[str]) -> list[str]:
    """Corrige la décimale manquante du premier token (mL)."""
    if not tokens:
        return tokens
    try:
        v = float(tokens[0])
    except ValueError:
        return tokens
    if '.' in tokens[0] or v <= ML_MAX:
        return tokens
    s = tokens[0].lstrip('+-')
    if len(s) >= 2:
        corrected = s[0] + '.' + s[1:]
        try:
            if float(corrected) <= ML_MAX:
                tokens = [corrected] + tokens[1:]
        except ValueError:
            pass
    return tokens


def _fix_seconds(s: str) -> str | None:
    """Corrige un token de secondes qui semble être tronqué (manque un 0)."""
    if '.' in s or s == 'NaN':
        return None
    try:
        v = int(s)
    except ValueError:
        return None
    if v == 0 or v % 10 == 0:
        return None
    corrected = v * 10
    return str(corrected) if 0 <= corrected <= 99999 else None


def fix_missing_decimals(tokens: list[str]) -> list[str]:
    """Insère les décimales manquantes en se basant sur les plages attendues."""
    result = list(tokens)
    for i, (s, (lo, hi)) in enumerate(zip(result, CFG.col_ranges)):
        if s == 'NaN':
            continue
        if i == 4:  # Colonne S (secondes)
            fixed = _fix_seconds(s)
            if fixed is not None:
                result[i] = fixed
            continue
        fixed = _try_insert_dot(s, lo, hi)
        if fixed is not None:
            result[i] = fixed
    return result


def extract_tokens(line: str) -> list[str]:
    """Extrait et corrige les tokens numériques d'une ligne OCR."""
    line = re.sub(r'\ba(\d)', r'3\1', line)
    tokens = TOKEN_RE.findall(line)
    tokens = fix_ml_decimal(tokens)
    if len(tokens) == 6:
        tokens = fix_missing_decimals(tokens)
    return tokens


def clean_line(line: str) -> str:
    """Nettoyage final d'une ligne avant extraction."""
    line = fix_ocr_line(line)
    line = re.sub(r'^\.\s*', '0.0000 ', line)
    line = re.sub(r'^4\.(\d)', r'1.\1', line)
    return line


def _is_junk(line: str) -> bool:
    """Détecte les en-têtes / pieds de page du titrateur."""
    if JUNK_PATTERNS.search(line):
        return True
    letters = sum(1 for c in line if c.isalpha())
    digits  = sum(1 for c in line if c.isdigit())
    return letters > 6 and digits > 0 and letters > digits * 2


# ──────────────────────────────────────────────────────────────────────────────
#  Prétraitement image (OpenCV)
# ──────────────────────────────────────────────────────────────────────────────

def _deskew(gray: np.ndarray) -> tuple[np.ndarray, float]:
    """
    Corrige l'inclinaison (deskew) basé sur la variance de la projection horizontale.
    Idéal pour des données tabulaires sans lignes de séparation (alignement parfait des lignes de texte).
    """
    h_full, w_full = gray.shape
    
    # Downscale pour accélérer grandement le calcul
    scale = 1.0
    if w_full > 1000:
        scale = 1000.0 / w_full
        small = cv2.resize(gray, (int(w_full * scale), int(h_full * scale)), interpolation=cv2.INTER_AREA)
    else:
        small = gray
        
    _, thresh = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    
    best_angle = 0.0
    best_var = 0.0
    h_s, w_s = thresh.shape
    center = (w_s // 2, h_s // 2)
    
    def _calc_variance(angle: float) -> float:
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(thresh, M, (w_s, h_s), flags=cv2.INTER_NEAREST)
        row_sums = np.sum(rotated, axis=1)
        return float(np.var(row_sums))

    # 1. Recherche grossière (-5.0° à +5.0° avec un pas de 0.5°)
    for angle in np.arange(-5.0, 5.5, 0.5):
        v = _calc_variance(angle)
        if v > best_var:
            best_var = v
            best_angle = angle
            
    # 2. Recherche fine autour du meilleur angle (pas de 0.1°)
    fine_best_angle = best_angle
    for angle in np.arange(best_angle - 0.4, best_angle + 0.5, 0.1):
        v = _calc_variance(angle)
        if v > best_var:
            best_var = v
            fine_best_angle = angle
            
    best_angle = float(fine_best_angle)

    # Si l'image est déjà quasiment droite
    if abs(best_angle) < 0.1:
        return gray, 0.0
        
    # Appliquer la rotation correctrice finale sur l'image pleine résolution
    M_full = cv2.getRotationMatrix2D((w_full // 2, h_full // 2), best_angle, 1.0)
    rotated_full = cv2.warpAffine(
        gray, M_full, (w_full, h_full),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return rotated_full, best_angle


def _binarize(gray: np.ndarray) -> np.ndarray:
    """Binarise l'image en choisissant entre Otsu et adaptatif."""
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    black_ratio = np.sum(otsu == 0) / otsu.size
    if black_ratio > 0.40:
        return cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 31, 10,
        )
    return otsu


def _denoise(gray: np.ndarray) -> np.ndarray:
    """Applique un débruitage non-local means."""
    return cv2.fastNlMeansDenoising(gray, h=12, templateWindowSize=7, searchWindowSize=21)


def preprocess_page(pil_image: Image.Image, log_fn: LogCallback | None = None) -> Image.Image:
    """
    Prétraitement complet d'une page scannée.

    Pipeline : débruitage → deskew → binarisation → érosion légère.
    """
    if not _CV2_OK:
        return pil_image
    gray         = np.array(pil_image.convert('L'))
    gray         = _denoise(gray)
    gray, angle  = _deskew(gray)
    if log_fn and abs(angle) >= 0.3:
        log_fn(f"    ↻ Deskew : {angle:+.2f}°")
    binary = _binarize(gray)
    kernel = np.ones((2, 2), np.uint8)
    binary = cv2.erode(binary, kernel, iterations=1)
    return Image.fromarray(binary)


# ──────────────────────────────────────────────────────────────────────────────
#  Pipeline principal d'extraction
# ──────────────────────────────────────────────────────────────────────────────

DiagEntry = tuple[str, str, list[str], list[str], list[str]]

def process_pdf(
    pdf_path: str,
    log_callback: LogCallback,
    diag_path: str | None = None,
    stop_event: threading.Event | None = None,
) -> tuple[pd.DataFrame, int, list[tuple[str, str]]]:
    """
    Extrait un DataFrame à partir d'un PDF scanné.

    Args:
        pdf_path: Chemin du fichier PDF.
        log_callback: Fonction de log (appelée depuis le thread worker).
        diag_path: Si fourni, écrit un rapport diagnostic à ce chemin.
        stop_event: Permet l'annulation entre les pages.

    Returns:
        ``(df, n_lignes, skipped)`` — le DataFrame, le nombre de lignes,
        et la liste des lignes ignorées/ajustées.

    Raises:
        StopIteration: Si l'extraction est annulée via *stop_event*.
        RuntimeError: Si Poppler est introuvable.
    """
    if POPPLER_PATH:
        log_callback(f"  Poppler : {POPPLER_PATH}")
    else:
        log_callback("  Poppler : détection via PATH système")
    log_callback("  Conversion en images...")

    try:
        pages = convert_from_path(pdf_path, dpi=CFG.scan_dpi, poppler_path=POPPLER_PATH)
    except Exception as e:
        msg = str(e)
        if "poppler" in msg.lower() or "page count" in msg.lower():
            raise RuntimeError(
                "Poppler introuvable.\n\n"
                "Solutions :\n"
                "1. Téléchargez Poppler : https://github.com/oschwartz10612/poppler-windows/releases\n"
                "2. Décompressez-le (ex: C:\\poppler\\)\n"
                "3. Relancez l'application — elle le détectera automatiquement.\n\n"
                f"Détail : {e}"
            ) from e
        raise

    log_callback(f"  {len(pages)} page(s) détectée(s).")
    if _CV2_OK:
        log_callback("  Prétraitement : deskew + débruitage + binarisation (OpenCV)")
    else:
        log_callback("  ⚠ OpenCV non disponible — prétraitement ignoré (pip install opencv-python)")

    ocr_raw = ""
    TESS_CONFIG = (
        '--psm 6 '
        '--oem 1 '
        '-c tessedit_char_whitelist=0123456789.-+NaN '
    )
    # word_boxes[i] = liste de (text, left, top, width, height) pour la page i
    word_boxes: list[list[tuple[str, int, int, int, int]]] = []
    ready_pages = []

    for i, page in enumerate(pages):
        if stop_event is not None and stop_event.is_set():
            log_callback("  ⛔ Extraction annulée par l'utilisateur.")
            raise StopIteration("Extraction annulée")
        page_ready  = preprocess_page(page, log_fn=log_callback)
        ready_pages.append(page_ready)
        ocr_raw    += pytesseract.image_to_string(page_ready, lang='eng', config=TESS_CONFIG) + "\n"

        # Récupérer les boxes de coordonnées pour le zoom-source
        try:
            import pytesseract as _pt
            data = _pt.image_to_data(page_ready, lang='eng', config=TESS_CONFIG,
                                     output_type=_pt.Output.DICT)
            boxes: list[tuple[str, int, int, int, int]] = []
            for j, txt in enumerate(data['text']):
                txt = str(txt).strip()
                if txt and int(data['conf'][j]) > 0:
                    boxes.append((txt,
                                  int(data['left'][j]),
                                  int(data['top'][j]),
                                  int(data['width'][j]),
                                  int(data['height'][j])))
            word_boxes.append(boxes)
        except Exception:
            word_boxes.append([])

        log_callback(f"  Page {i+1}/{len(pages)} traitée.")


    # ── Nettoyage global ──
    ocr_clean = ocr_raw.replace(",", ".")
    ocr_clean = re.sub(r'[""\"»\'`!|]', ' ', ocr_clean)
    ocr_clean = re.sub(r'(\d)\.$',     r'\1', ocr_clean)
    ocr_clean = re.sub(r'(\d)\.\s',   r'\1 ', ocr_clean)
    raw_lines = ocr_clean.split("\n")

    # ── Fusion de lignes fragmentées ──
    merged_lines: list[str] = []
    buffer = ""
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        tokens = TOKEN_RE.findall(line)
        if len(tokens) <= 1:
            buffer += " " + line
        else:
            if buffer:
                merged_lines.append((buffer + " " + line).strip())
                buffer = ""
            else:
                merged_lines.append(line)
    if buffer:
        merged_lines.append(buffer.strip())

    # ── Filtrage des lignes parasites ──
    junk_lines = [(l, "en-tête/pied de page") for l in merged_lines if _is_junk(l)]
    merged_lines = [clean_line(l) for l in merged_lines if not _is_junk(l)]
    merged_lines = [l for l in merged_lines if TOKEN_RE.search(l)]

    # ── Extraction des données ──
    data:    list[list[str]]         = []
    skipped: list[tuple[str, str]]   = []
    diag:    list[DiagEntry]         = []

    for raw, reason in junk_lines:
        diag.append(("SKIP", raw, [], [], []))
        skipped.append(("SKIP", raw))

    for line in merged_lines:
        tokens_raw = TOKEN_RE.findall(line)
        tokens     = extract_tokens(line)

        if len(tokens) == 6:
            data.append(tokens)
            diag.append(("OK", line, tokens_raw, tokens, tokens))
        elif len(tokens) == 7:
            found = False
            for drop_idx in [0, 1, 2]:
                candidate = tokens[:drop_idx] + tokens[drop_idx + 1:]
                try:
                    if float(candidate[4]) % 10 == 0:
                        data.append(candidate)
                        found = True
                        diag.append(("7→6", line, tokens_raw, tokens, candidate))
                        break
                except Exception:
                    continue
            if not found:
                data.append(tokens[:6])
                skipped.append(("7→6", line))
                diag.append(("7→6!", line, tokens_raw, tokens, tokens[:6]))
        elif len(tokens) == 5:
            fixed = list(tokens)
            fixed.insert(3, "NaN")
            data.append(fixed)
            skipped.append(("5→6", line))
            diag.append(("5→6", line, tokens_raw, tokens, fixed))
        else:
            if tokens:
                skipped.append((f"{len(tokens)} val.", line))
                diag.append(("SKIP", line, tokens_raw, tokens, []))

    df = pd.DataFrame(data, columns=COLONNES)
    for col in COLONNES:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    if diag_path:
        _write_diag(diag_path, pdf_path, diag, df)
        log_callback(f"  📋 Diagnostic OCR → {os.path.basename(diag_path)}")

    return df, len(data), skipped, word_boxes, ready_pages


# ──────────────────────────────────────────────────────────────────────────────
#  Rapport diagnostic OCR
# ──────────────────────────────────────────────────────────────────────────────

def _write_diag(
    diag_path: str,
    pdf_path: str,
    diag: list[DiagEntry],
    df: pd.DataFrame,
) -> None:
    """Écrit un rapport texte détaillé du diagnostic OCR."""
    header = (
        f"DIAGNOSTIC OCR — {os.path.basename(pdf_path)}\n"
        f"{'=' * 80}\n"
        f"Colonnes attendues : {COLONNES}\n"
        f"Lignes extraites   : {len(df)}\n"
        f"{'=' * 80}\n\n"
        f"LÉGENDE:\n"
        f"  OK    = ligne extraite correctement (6 tokens)\n"
        f"  7→6   = 7 tokens → 1 supprimé automatiquement\n"
        f"  7→6!  = 7 tokens → troncature forcée (à vérifier !)\n"
        f"  5→6   = 5 tokens → NaN inséré en col. delta\n"
        f"  SKIP  = ligne ignorée\n"
        f"{'=' * 80}\n\n"
    )
    col_header = (
        f"  {'Statut':<6}  {'mL':>10} {'mL2':>10} {'pH':>8} "
        f"{'delta':>10} {'S':>10} {'C':>8}    Ligne brute OCR\n"
    )
    sep       = "  " + "-" * 120 + "\n"
    issues:    list[str] = []
    lines_out: list[str] = []

    for status, raw_line, tokens_raw, tokens_corr, final in diag:
        vals = "  ".join(f"{v:>10}" for v in (final + [""] * (6 - len(final)))[:6])
        corr_note = ""
        if tokens_raw != tokens_corr:
            diffs = [f"{a}→{b}" for a, b in zip(tokens_raw, tokens_corr) if a != b]
            if diffs:
                corr_note = f"  [corrigé: {', '.join(diffs)}]"
        line_out = f"  {status:<6}  {vals}    {raw_line[:80]}{corr_note}\n"
        lines_out.append(line_out)
        if status != "OK":
            issues.append(line_out)

    summary = (
        f"RÉSUMÉ DES LIGNES PROBLÉMATIQUES ({len(issues)} / {len(diag)})\n"
        f"{'=' * 80}\n"
        + col_header + sep + "".join(issues) + sep + "\n"
        + f"TOUTES LES LIGNES\n"
        f"{'=' * 80}\n"
        + col_header + sep
    )

    with open(diag_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write(summary)
        f.write("".join(lines_out))
        f.write(sep)
        f.write("\nFIN DU RAPPORT\n")
