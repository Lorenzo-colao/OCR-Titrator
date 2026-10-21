"""
Validation et flagging des données extraites.

Responsabilités :
- ``flag_row`` : détecte les valeurs hors-plage / aberrantes par ligne
- ``compute_iqr_bounds`` : calcule les bornes IQR pour la détection statistique
- ``check_and_fix_cumulative`` : vérifie et corrige mL2/delta vs valeurs cumulatives
- ``check_physical_consistency`` : applique les règles R1–R6 de cohérence physique

Ce module ne dépend que de ``config`` et de bibliothèques de calcul (pandas, numpy).
Aucune référence à l'UI.
"""

from __future__ import annotations

import pandas as pd

from config import CFG, COLONNES


# ──────────────────────────────────────────────────────────────────────────────
#  Statistiques / flags
# ──────────────────────────────────────────────────────────────────────────────

def flag_row(
    row: pd.Series,
    col_stats: dict[str, tuple[float, float]] | None = None,
) -> str:
    """
    Évalue les anomalies d'une ligne de données.

    Retourne une chaîne vide si tout est OK, sinon une description
    des problèmes séparés par ``|``.
    """
    issues: list[str] = []
    for col, rules in CFG.validation_rules.items():
        val = row.get(col)
        if pd.isna(val):
            issues.append(f"{rules['label']} manquant (NaN)")
        else:
            if val < rules["min"] or val > rules["max"]:
                issues.append(
                    f"{rules['label']}={val:.4g} hors plage "
                    f"[{rules['min']},{rules['max']}]"
                )
            elif col_stats and col in col_stats and CFG.iqr_factor > 0:
                lo, hi = col_stats[col]
                if val < lo or val > hi:
                    issues.append(f"{rules['label']}={val:.4g} valeur aberrante (stat.)")
    return " | ".join(issues) if issues else ""


def compute_iqr_bounds(df: pd.DataFrame) -> dict[str, tuple[float, float]]:
    """
    Calcule les bornes *IQR* pour chaque colonne numérique.

    Retourne un dict ``{colonne: (borne_basse, borne_haute)}``.
    """
    bounds: dict[str, tuple[float, float]] = {}
    for col in COLONNES:
        series = df[col].dropna()
        if len(series) < 4:
            continue
        q1, q3 = series.quantile(0.25), series.quantile(0.75)
        iqr = q3 - q1
        factor = CFG.iqr_factor
        bounds[col] = (q1 - factor * iqr, q3 + factor * iqr)
    return bounds


# ──────────────────────────────────────────────────────────────────────────────
#  Correction cumulative
# ──────────────────────────────────────────────────────────────────────────────

def check_and_fix_cumulative(df: pd.DataFrame) -> pd.DataFrame:
    """
    Vérifie que ``mL2 = mL[i] − mL[i-1]`` et ``delta = pH[i] − pH[i-1]``.

    Améliorations :
    - La recherche de la ligne de référence ignore les NaN **et** les valeurs
      hors-plage.
    - Ne corrige pas si les valeurs cumulatives sont elles-mêmes hors-plage.
    - Arrondi à 8 décimales pour éviter les artefacts float64.
    """
    tol = CFG.cumul_tolerance
    df = df.copy().reset_index(drop=True)
    df["Fix_mL2"]   = ""
    df["Fix_delta"] = ""

    pairs = [
        ("mL",  "mL2",  "Fix_mL2",   CFG.validation_rules["mL"],  CFG.validation_rules["mL2"]),
        ("pH",  "delta", "Fix_delta", CFG.validation_rules["pH"],  CFG.validation_rules["delta"]),
    ]

    for col_cum, col_delta, col_fix, rules_cum, rules_delta in pairs:
        # Trouver la première ligne de référence valide
        ref_idx: int | None = None
        for i in range(len(df)):
            v_cum   = df.at[i, col_cum]
            v_delta = df.at[i, col_delta]
            if pd.isna(v_cum) or pd.isna(v_delta):
                continue
            if not (rules_cum["min"] <= v_cum <= rules_cum["max"]):
                continue
            if not (rules_delta["min"] <= v_delta <= rules_delta["max"]):
                continue
            ref_idx = i
            break

        if ref_idx is None:
            continue

        for i in range(ref_idx + 1, len(df)):
            a_curr = df.at[i,     col_cum]
            a_prev = df.at[i - 1, col_cum]
            b_curr = df.at[i,     col_delta]

            if pd.isna(a_curr) or pd.isna(a_prev) or pd.isna(b_curr):
                continue
            if not (rules_cum["min"] <= float(a_curr) <= rules_cum["max"]):
                continue
            if not (rules_cum["min"] <= float(a_prev) <= rules_cum["max"]):
                continue

            # Ignorer autour du point d'équivalence pour delta pH
            if col_delta == "delta" and "S" in df.columns:
                s_curr = df.at[i, "S"]
                s_prev = df.at[i - 1, "S"]
                if not pd.isna(s_curr) and not pd.isna(s_prev):
                    if float(s_curr) - float(s_prev) > 10:
                        continue

            b_expected = round(float(a_curr) - float(a_prev), 8)
            b_actual   = round(float(b_curr), 8)

            if abs(b_expected - b_actual) > tol:
                df.at[i, col_fix] = (
                    f"{col_delta} corrigé ligne {i + 2} : "
                    f"{b_actual:+.6f} → {b_expected:+.6f} "
                    f"(= {col_cum}[{i+2}] − {col_cum}[{i+1}] "
                    f"= {float(a_curr):.6f} − {float(a_prev):.6f})"
                )
                df.at[i, col_delta] = b_expected

    return df


# ──────────────────────────────────────────────────────────────────────────────
#  Cohérence physique (R1–R6)
# ──────────────────────────────────────────────────────────────────────────────

def check_physical_consistency(df: pd.DataFrame) -> pd.DataFrame:
    """
    Vérifie la cohérence physique entre colonnes consécutives.

    Règles :
        R1 — mL  strictement croissant (tolérance 0.001)
        R2 — mL2 strictement croissant (tolérance 0.001)
        R3 — S   non décroissant (tolérance configurable)
        R4 — C   varie lentement (|ΔC| ≤ seuil)
        R5 — signe de delta cohérent avec ΔpH
        R6 — mL2 ≤ mL
    """
    df = df.copy().reset_index(drop=True)
    df["Phys_Flag"] = ""

    s_tol  = CFG.s_monotone_tolerance
    c_step = CFG.c_max_step

    def _add(i: int, msg: str) -> None:
        sep = " | " if df.at[i, "Phys_Flag"] else ""
        df.at[i, "Phys_Flag"] = df.at[i, "Phys_Flag"] + sep + msg

    for i in range(len(df)):
        ml    = df.at[i, "mL"]
        ml2   = df.at[i, "mL2"]
        ph    = df.at[i, "pH"]
        delta = df.at[i, "delta"]
        s     = df.at[i, "S"]
        c     = df.at[i, "C"]

        # R6 : mL2 ≤ mL
        if not pd.isna(ml) and not pd.isna(ml2) and ml2 > ml + 0.001:
            _add(i, f"R6: mL2={ml2:.4f} > mL={ml:.4f}")

        if i == 0:
            continue

        ml_p    = df.at[i - 1, "mL"]
        ml2_p   = df.at[i - 1, "mL2"]
        ph_p    = df.at[i - 1, "pH"]
        delta_p = df.at[i - 1, "delta"]
        s_p     = df.at[i - 1, "S"]
        c_p     = df.at[i - 1, "C"]

        # R1 : mL strictement croissant
        if not pd.isna(ml) and not pd.isna(ml_p) and ml < ml_p - 0.001:
            _add(i, f"R1: mL={ml:.4f} < mL[{i}]={ml_p:.4f} (non monotone)")

        # R2 : mL2 strictement croissant
        if not pd.isna(ml2) and not pd.isna(ml2_p) and ml2 < ml2_p - 0.001:
            _add(i, f"R2: mL2={ml2:.4f} < mL2[{i}]={ml2_p:.4f} (non monotone)")

        # R3 : S non décroissant
        if not pd.isna(s) and not pd.isna(s_p):
            if float(s) < float(s_p) - s_tol:
                _add(i, f"R3: S={s:.0f} < S[{i}]={s_p:.0f} (non monotone, tol={s_tol})")

        # R4 : C varie lentement
        if not pd.isna(c) and not pd.isna(c_p):
            step_c = abs(float(c) - float(c_p))
            if step_c > c_step:
                _add(i, f"R4: ΔC={step_c:.1f}°C (seuil={c_step}°C)")

        # R5 : signe de delta cohérent avec ΔpH
        if not pd.isna(delta) and not pd.isna(ph) and not pd.isna(ph_p):
            if abs(float(delta)) >= 0.01:
                ph_diff = float(ph) - float(ph_p)
                near_equiv = (
                    abs(ph_diff) > 1.5
                    or (not pd.isna(delta_p) and abs(float(delta_p)) > 1.5)
                )
                if not near_equiv and abs(ph_diff) >= 0.01:
                    sign_ok = (
                        (float(delta) > 0 and ph_diff > 0)
                        or (float(delta) < 0 and ph_diff < 0)
                    )
                    if not sign_ok:
                        _add(
                            i,
                            f"R5: delta={float(delta):+.3f} incohérent "
                            f"avec ΔpH={ph_diff:+.3f}",
                        )

    return df
