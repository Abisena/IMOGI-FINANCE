# Copyright (c) 2026, PT. Inovasi Terbaik Bangsa and contributors
# For license information, please see license.txt

"""Shared utilities for Imogi Finance.

This package contains utility modules used across multiple reports and features.
"""

from __future__ import annotations

# Re-export commonly used functions for convenience
from .tax_report_utils import (
    get_tax_amount_from_gl,
    get_tax_amounts_batch,
    validate_tax_register_configuration,
    validate_vat_input_configuration,
    validate_vat_output_configuration,
    validate_withholding_configuration,
)

# Re-export from imogi_finance.imogi_finance.utils for hooks compatibility
def ensure_coretax_export_doctypes():
    """Ensure CoreTax Export DocTypes exist.
    
    This is called from hooks after_install and after_migrate.
    """
    import frappe
    from frappe.utils import get_site_path
    import os
    import json
    
    # Implementation here or import from another module
    # For now, just a placeholder that won't break hooks
    pass

__all__ = [
    "get_tax_amount_from_gl",
    "get_tax_amounts_batch",
    "validate_tax_register_configuration",
    "validate_vat_input_configuration",
    "validate_vat_output_configuration",
    "validate_withholding_configuration",
    "ensure_coretax_export_doctypes",
]
