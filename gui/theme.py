"""
Système de design — Apple Dark Mode
────────────────────────────────────
Palette identique à macOS Heavy Dark : niveaux de gris élaborés,
accent bleu discret, typographie Segoe UI (proxy de SF Pro sous Windows).
"""

from __future__ import annotations


class Colors:
    """Palette Moderne — Style Tailwind / Dashboard Professionnel."""
    # ── Fonds ──────────────────────────────────────────────────────────────────
    BG_DARK     = "#09090B"   # zinc-950 (fond global très profond)
    BG_PANEL    = "#18181B"   # zinc-900 (panneau latéral, header)
    BG_CARD     = "#27272A"   # zinc-800 (cartes, formulaires)
    BG_CARD_ALT = "#3F3F46"   # zinc-700 (boutons ou inputs à l'intérieur)
    BG_HOVER    = "#52525B"   # zinc-600 (effet de survol)
    BORDER      = "#3F3F46"   # zinc-700 (lignes séparatrices)

    # ── Accents ────────────────────────────────────────────────────────────────
    ACCENT      = "#6366F1"   # indigo-500 (boutons principaux)
    ACCENT_HOVER= "#4F46E5"   # indigo-600 (survol indigo)
    GREEN       = "#10B981"   # emerald-500 (succès, logs)
    GREEN_DARK  = "#059669"   # emerald-600
    BLUE        = "#3B82F6"   # blue-500 (secondaire)
    PURPLE      = "#A855F7"   # purple-500
    PURPLE_DARK = "#9333EA"   # purple-600
    DANGER      = "#EF4444"   # red-500 (erreur)
    DANGER_ALT  = "#450A0A"   # red-950 (fond erreur)
    ORANGE      = "#F59E0B"   # amber-500

    # ── Texte ──────────────────────────────────────────────────────────────────
    TEXT_ON     = "#FAFAFA"   # zinc-50 (titres, actif)
    TEXT_OFF    = "#A1A1AA"   # zinc-400 (texte normal)
    TEXT_MUTED  = "#71717A"   # zinc-500 (descriptions discrètes)
    TEXT_DIM    = "#52525B"   # zinc-600
    TEXT_SUBTLE = "#3F3F46"   # zinc-700
    LOG_GREEN   = "#10B981"   # emerald-500
    DROP_LINE   = "#6366F1"   # indigo-500


class Fonts:
    """Typographie moderne (style Tailwind avec polices systèmes fluides)."""
    # Polices systèmes propres sous Windows
    _SYS_SANS = "Segoe UI"
    _SYS_MONO = "Consolas"

    MONO        = (_SYS_MONO,  10)
    MONO_BOLD   = (_SYS_MONO,  10, "bold")
    MONO_SM     = (_SYS_MONO,   9)
    MONO_SM_B   = (_SYS_MONO,   9, "bold")
    MONO_LG     = (_SYS_MONO,  11)
    MONO_LG_B   = (_SYS_MONO,  11, "bold")
    MONO_XL     = (_SYS_MONO,  12)
    MONO_XL_B   = (_SYS_MONO,  12, "bold")

    SANS        = (_SYS_SANS,  11)
    SANS_BOLD   = (_SYS_SANS,  11, "bold")
    SANS_SM     = (_SYS_SANS,  10)
    SANS_LG     = (_SYS_SANS,  12)
    SANS_LG_B   = (_SYS_SANS,  12, "bold")
    SANS_XL     = (_SYS_SANS,  13)
    SANS_XL_B   = (_SYS_SANS,  13, "bold")
    SANS_XXL_B  = (_SYS_SANS,  15, "bold")
    SANS_TITLE  = (_SYS_SANS,  22, "bold")


# ── Helpers scroll ─────────────────────────────────────────────────────────────

def handle_scroll_y(canvas, event) -> None:
    """Scroll vertical unifié (Windows/macOS/Linux)."""
    delta = getattr(event, "delta", 0)
    if delta:
        canvas.yview_scroll(int(-delta / 120), "units")
    elif getattr(event, "num", 0) == 4:
        canvas.yview_scroll(-1, "units")
    elif getattr(event, "num", 0) == 5:
        canvas.yview_scroll(1, "units")


def handle_scroll_x(canvas, event) -> None:
    """Scroll horizontal unifié."""
    delta = getattr(event, "delta", 0)
    if delta:
        canvas.xview_scroll(int(-delta / 120), "units")
