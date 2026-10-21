"""
Configuration et constantes globales de l'application.

Ce module centralise :
- Les constantes métier (colonnes, labels)
- Les chemins vers les outils externes (Tesseract, Poppler)
- Les paramètres par défaut
- La classe Settings (conteneur thread-safe)
- Les fonctions de persistance (load/save)

Principe : toutes les parties du code accèdent aux paramètres via
l'instance unique ``CFG``, jamais via des variables globales mutables.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import threading
from typing import Any

# ──────────────────────────────────────────────────────────────────────────────
#  Constantes métier
# ──────────────────────────────────────────────────────────────────────────────

COLONNES: list[str] = ["mL", "mL2", "pH", "delta", "S", "C"]
"""Noms ordonnés des colonnes de données."""

COL_LABELS: dict[str, str] = {
    "mL": "mL", "mL2": "mL2", "pH": "pH",
    "delta": "delta", "S": "S", "C": "°C",
}
"""Labels affichés pour chaque colonne."""


# ──────────────────────────────────────────────────────────────────────────────
#  Chemins externes et Portabilité
# ──────────────────────────────────────────────────────────────────────────────

def get_app_dir() -> str:
    """Retourne le dossier contenant l'exécutable ou le script."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


SETTINGS_PATH: str = os.path.join(get_app_dir(), "settings.json")

# Chemin du cache de détection des outils externes
_TOOLS_CACHE_PATH: str = os.path.join(get_app_dir(), "tools_cache.json")


def _load_tools_cache() -> dict:
    """Lit le cache {tesseract, poppler_bin} s'il existe et est valide."""
    try:
        with open(_TOOLS_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_tools_cache(data: dict) -> None:
    try:
        with open(_TOOLS_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def _disk_roots() -> list[str]:
    """Retourne toutes les racines de disque disponibles sur ce PC."""
    import string
    return [f"{l}:\\" for l in string.ascii_uppercase if os.path.isdir(f"{l}:\\")] or ["C:\\"]


# Dossiers système à ignorer lors du scan récursif
_SKIP_DIRS = {
    "Windows", "WinSxS", "$Recycle.Bin", "System Volume Information",
    "MSOCache", "Recovery", "ProgramData", "$WinREAgent",
    "Intel", "AMD", "NVIDIA", "Boot", "Recovery",
}


def _search_file_fast(filename: str,
                      priority_paths: list[str],
                      timeout_sec: float = 6.0) -> str | None:
    """
    Cherche *filename* rapidement :
    1. Vérifie *priority_paths* directement.
    2. Vérifie le PATH système.
    3. Scan os.walk sur tous les disques avec timeout.
    """
    import shutil, time

    # 1. Priorité directe
    for p in priority_paths:
        if os.path.isfile(p):
            return p
        candidate = os.path.join(p, filename)
        if os.path.isfile(candidate):
            return candidate

    # 2. PATH système
    exe_name = filename.rsplit(".", 1)[0]
    found_in_path = shutil.which(exe_name) or shutil.which(filename)
    if found_in_path:
        return found_in_path

    # 3. Scan récursif avec timeout
    deadline = time.monotonic() + timeout_sec
    for root_drive in _disk_roots():
        try:
            for dirpath, dirnames, filenames in os.walk(root_drive, topdown=True):
                if time.monotonic() > deadline:
                    return None
                dirnames[:] = [
                    d for d in dirnames
                    if d not in _SKIP_DIRS and not d.startswith(".")
                ]
                if filename in filenames:
                    return os.path.join(dirpath, filename)
        except PermissionError:
            continue

    return None


# ──────────────────────────────────────────────────────────────────────────────
#  Détection Tesseract
# ──────────────────────────────────────────────────────────────────────────────

def _find_tesseract() -> str:
    """
    Cherche tesseract.exe :
      1. Cache (retour instantané si valide)
      2. À côté de l'exe / dossiers parents et frères du projet
      3. Bureau/Desktop de tous les utilisateurs Windows
      4. Program Files classiques
      5. PATH système
      6. Scan disque complet (timeout 6 s, résultat mis en cache)
    """
    import glob, shutil

    cache = _load_tools_cache()
    cached = cache.get("tesseract", "")
    if cached and os.path.isfile(cached):
        return cached

    app_dir  = get_app_dir()
    parent   = os.path.dirname(app_dir)   # dossier parent du projet
    gparent  = os.path.dirname(parent)    # grand-parent

    # Dossiers Tesseract-OCR connus à côté / autour du projet
    near_dirs = []
    for base in (app_dir, parent, gparent):
        near_dirs.append(os.path.join(base, "Tesseract-OCR", "tesseract.exe"))
        near_dirs.append(os.path.join(base, "tesseract.exe"))
        for sibling in glob.glob(os.path.join(base, "*", "Tesseract-OCR", "tesseract.exe")):
            near_dirs.append(sibling)

    # Bureau / Desktop de tous les utilisateurs
    users_root = r"C:\Users"
    if os.path.isdir(users_root):
        for user in os.listdir(users_root):
            for desk_name in ("Desktop", "Bureau"):
                desk = os.path.join(users_root, user, desk_name)
                for pat in ("Tesseract-OCR/tesseract.exe",
                            "*/Tesseract-OCR/tesseract.exe",
                            "*/*/Tesseract-OCR/tesseract.exe",
                            "Tesseract*/tesseract.exe",
                            "*/Tesseract*/tesseract.exe",
                            "*/*/Tesseract*/tesseract.exe"):
                    for found in glob.glob(os.path.join(desk, pat)):
                        near_dirs.append(found)

    priority = near_dirs + [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]

    # Vérification directe des chemins prioritaires
    for p in priority:
        if os.path.isfile(p):
            cache["tesseract"] = p
            _save_tools_cache(cache)
            return p

    # PATH système
    in_path = shutil.which("tesseract")
    if in_path:
        cache["tesseract"] = in_path
        _save_tools_cache(cache)
        return in_path

    # Scan complet
    found = _search_file_fast("tesseract.exe", priority, timeout_sec=6.0)
    result = found if found else "tesseract"  # fallback PATH ultime

    cache["tesseract"] = result
    _save_tools_cache(cache)
    return result


# ──────────────────────────────────────────────────────────────────────────────
#  Détection Poppler
# ──────────────────────────────────────────────────────────────────────────────


def _test_pdftoppm(exe_path: str) -> bool:
    """Vérifie que l'exécutable pdftoppm (chemin absolu ou dans le PATH) fonctionne correctement."""
    import shutil, subprocess
    if not os.path.isabs(exe_path) and not shutil.which(exe_path):
        return False
    try:
        # Ne pas afficher de fenêtre console sous Windows
        kwargs = {}
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            kwargs["startupinfo"] = startupinfo
            
        r = subprocess.run([exe_path, "-v"],
                           capture_output=True, timeout=3, **kwargs)
        return r.returncode == 0 or b"oppler" in (r.stdout + r.stderr)
    except Exception:
        return False


def _find_poppler() -> str | None:
    """
    Cherche le dossier bin Poppler (contenant pdftoppm.exe) :
      1. Cache (retour instantané si valide et pdftoppm.exe présent et fonctionnel)
      2. Emplacements prioritaires connus (y compris Bureau de tous les users)
      3. PATH système (avec vérification réelle)
      4. Scan disque complet (timeout 6 s, résultat mis en cache)
    """
    cache = _load_tools_cache()
    cached = cache.get("poppler_bin", "__UNSET__")
    if cached != "__UNSET__":
        # None = dans PATH (validé), str = chemin avec pdftoppm.exe
        if cached is None:
            if _test_pdftoppm("pdftoppm"):
                return None
            # Le PATH ne fonctionne plus → on relance la détection complète
        elif isinstance(cached, str):
            exe = os.path.join(cached, "pdftoppm.exe")
            if os.path.isfile(exe) and _test_pdftoppm(exe):
                return cached

    app_dir = get_app_dir()

    # Dossiers Bureau de tous les utilisateurs Windows
    bureau_dirs: list[str] = []
    users_root = r"C:\Users"
    if os.path.isdir(users_root):
        for user in os.listdir(users_root):
            for desk_name in ("Desktop", "Bureau"):
                desk = os.path.join(users_root, user, desk_name)
                if os.path.isdir(desk):
                    # Cherche poppler*/Library/bin et poppler*/bin dans le Bureau, même dans un sous-dossier
                    import glob
                    for pat in ("poppler*/Library/bin", "poppler*/bin", "poppler*",
                                "*/poppler*/Library/bin", "*/poppler*/bin", "*/poppler*",
                                "*/*/poppler*/Library/bin", "*/*/poppler*/bin", "*/*/poppler*"):
                        for folder in glob.glob(os.path.join(desk, pat)):
                            bureau_dirs.append(folder)

    priority_dirs = [
        # À côté de l'exe (mode portable)
        os.path.join(app_dir, "poppler", "Library", "bin"),
        os.path.join(app_dir, "poppler", "bin"),
        os.path.join(app_dir, "poppler"),
        # Emplacements classiques
        r"C:\poppler\Library\bin",
        r"C:\poppler\bin",
        r"C:\Program Files\poppler\Library\bin",
        r"C:\Program Files\poppler\bin",
    ] + bureau_dirs

    # Vérification directe prioritaire
    for folder in priority_dirs:
        exe = os.path.join(folder, "pdftoppm.exe")
        if os.path.isfile(exe) and _test_pdftoppm(exe):
            cache["poppler_bin"] = folder
            _save_tools_cache(cache)
            return folder

    # PATH système (avec test réel)
    if _test_pdftoppm("pdftoppm"):
        cache["poppler_bin"] = None
        _save_tools_cache(cache)
        return None

    # Scan complet du disque
    found_exe = _search_file_fast("pdftoppm.exe", priority_dirs, timeout_sec=6.0)
    if found_exe and _test_pdftoppm(found_exe):
        result = os.path.dirname(found_exe)
    else:
        result = None

    cache["poppler_bin"] = result
    _save_tools_cache(cache)
    return result


TESSERACT_PATH: str      = _find_tesseract()
POPPLER_PATH:   str|None = _find_poppler()


# ──────────────────────────────────────────────────────────────────────────────
#  Paramètres par défaut
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_SETTINGS: dict[str, Any] = {
    "validation_rules": {
        "mL":    {"min": 0.0,   "max": 100.0},
        "mL2":   {"min": 0.0,   "max": 50.0},
        "pH":    {"min": 0.0,   "max": 14.0},
        "delta": {"min": -50.0, "max": 50.0},
        "S":     {"min": 0.0,   "max": 99999.0},
        "C":     {"min": 15.0,  "max": 60.0},
    },
    "iqr_factor":           3.0,
    "scan_dpi":             300,
    "cumul_tolerance":      0.0001,
    "c_max_step":           2.0,
    "s_monotone_tolerance": 0.0,
    "output_dir":           "",
    "recent_files":         [],
}


# ──────────────────────────────────────────────────────────────────────────────
#  Classe Settings — conteneur thread-safe
# ──────────────────────────────────────────────────────────────────────────────

class Settings:
    """
    Conteneur thread-safe pour tous les paramètres de l'application.

    Toutes les parties du code accèdent aux valeurs via l'instance unique
    ``CFG``, jamais via des variables globales mutables.
    """

    def __init__(self, data: dict[str, Any]) -> None:
        self._lock = threading.RLock()
        self._apply(data)

    def _apply(self, data: dict[str, Any]) -> None:
        """Applique un dictionnaire de paramètres brut."""
        vr = data["validation_rules"]
        self.validation_rules: dict[str, dict[str, Any]] = {
            col: {
                "min":   vr[col]["min"],
                "max":   vr[col]["max"],
                "label": COL_LABELS[col],
            }
            for col in COLONNES
        }
        self.iqr_factor:           float = float(data["iqr_factor"])
        self.scan_dpi:             int   = int(data["scan_dpi"])
        self.cumul_tolerance:      float = float(data["cumul_tolerance"])
        self.c_max_step:           float = float(data["c_max_step"])
        self.s_monotone_tolerance: float = float(data.get("s_monotone_tolerance", 0.0))
        self.output_dir:           str   = str(data.get("output_dir", ""))
        self.col_ranges: list[tuple[float, float]] = [
            (vr[col]["min"], vr[col]["max"]) for col in COLONNES
        ]
        self.recent_files: list[str] = list(data.get("recent_files", []))

    def add_recent_file(self, filepath: str) -> None:
        """Ajoute un fichier à l'historique récent et sauvegarde la configuration."""
        with self._lock:
            # Enlever le fichier s'il est déjà dans la liste
            if filepath in self.recent_files:
                self.recent_files.remove(filepath)
            # Insérer en premier
            self.recent_files.insert(0, filepath)
            # Garder au maximum 10 fichiers
            self.recent_files = self.recent_files[:10]
            # Sauvegarder automatiquement
            snap = self.snapshot()
        save_settings(snap)

    def update(self, data: dict[str, Any]) -> None:
        """Met à jour atomiquement tous les paramètres."""
        with self._lock:
            self._apply(data)

    def snapshot(self) -> dict[str, Any]:
        """Retourne un instantané thread-safe des paramètres."""
        with self._lock:
            return {
                "validation_rules": copy.deepcopy(self.validation_rules),
                "iqr_factor":           self.iqr_factor,
                "scan_dpi":             self.scan_dpi,
                "cumul_tolerance":      self.cumul_tolerance,
                "c_max_step":           self.c_max_step,
                "s_monotone_tolerance": self.s_monotone_tolerance,
                "output_dir":           self.output_dir,
                "col_ranges":           list(self.col_ranges),
                "recent_files":         list(self.recent_files),
            }


# ──────────────────────────────────────────────────────────────────────────────
#  Persistance JSON
# ──────────────────────────────────────────────────────────────────────────────

def load_settings() -> dict[str, Any]:
    """Charge les paramètres depuis ``settings.json`` avec merge sur les défauts."""
    resolved = os.path.normpath(SETTINGS_PATH)
    if os.path.isfile(resolved):
        try:
            with open(resolved, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = copy.deepcopy(DEFAULT_SETTINGS)
            for k, v in data.items():
                if k == "validation_rules" and isinstance(v, dict):
                    for col, bounds in v.items():
                        if col in merged["validation_rules"]:
                            merged["validation_rules"][col].update(bounds)
                else:
                    merged[k] = v
            return merged
        except Exception:
            pass
    save_settings(DEFAULT_SETTINGS)
    return copy.deepcopy(DEFAULT_SETTINGS)


def save_settings(settings: dict[str, Any]) -> None:
    """Persiste les paramètres dans ``settings.json``."""
    to_save = {k: v for k, v in settings.items() if k != "col_ranges"}
    resolved = os.path.normpath(SETTINGS_PATH)
    try:
        with open(resolved, "w", encoding="utf-8") as f:
            json.dump(to_save, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[settings] Impossible de sauvegarder : {e}")


# ──────────────────────────────────────────────────────────────────────────────
#  Instance globale
# ──────────────────────────────────────────────────────────────────────────────

CFG: Settings = Settings(load_settings())
"""Instance unique des paramètres — toute la base de code utilise ``CFG.<attribut>``."""
