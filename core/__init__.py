"""Paquet core — exporte les fonctions métier principales."""

from core.validation    import (flag_row, compute_iqr_bounds,
                                 check_and_fix_cumulative,
                                 check_physical_consistency)
from core.ocr_pipeline  import process_pdf
from core.excel_export  import export_excel_with_flags

__all__ = [
    "flag_row", "compute_iqr_bounds",
    "check_and_fix_cumulative", "check_physical_consistency",
    "process_pdf", "export_excel_with_flags",
]
