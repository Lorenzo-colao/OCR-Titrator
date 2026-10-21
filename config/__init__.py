"""Paquet de configuration — exporte les symboles principaux."""

from config.settings import (
    CFG,
    COLONNES,
    COL_LABELS,
    DEFAULT_SETTINGS,
    POPPLER_PATH,
    SETTINGS_PATH,
    TESSERACT_PATH,
    Settings,
    load_settings,
    save_settings,
)

__all__ = [
    "CFG",
    "COLONNES",
    "COL_LABELS",
    "DEFAULT_SETTINGS",
    "POPPLER_PATH",
    "SETTINGS_PATH",
    "TESSERACT_PATH",
    "Settings",
    "load_settings",
    "save_settings",
]
