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
    from pathlib import Path

    doctype_map = {
        "CoreTax Export Settings": "coretax_export_settings",
        "CoreTax Column Mapping": "coretax_column_mapping",
        "Tax Profile PPh Account": "tax_profile_pph_account",
    }

    doctype_root = Path(frappe.get_app_path("imogi_finance", "imogi_finance", "doctype"))
    for doctype, module_name in doctype_map.items():
        doctype_definition = doctype_root / module_name / f"{module_name}.json"
        if doctype_definition.exists():
            frappe.reload_doc("imogi_finance", "doctype", module_name)
        else:
            frappe.log_error(
                message=f"Skipped reload for missing CoreTax DocType definition: {doctype_definition}",
                title="CoreTax DocType definition not found",
            )


def ensure_advances_allow_on_submit():
    """
    Create Property Setters to allow updating 'advances' child table after submit.
    This is required when Payment Entry references submitted invoices/expense claims.
    """
    import frappe

    property_setters = [
        {
            "doctype_or_field": "DocField",
            "doc_type": "Purchase Invoice",
            "field_name": "advances",
            "property": "allow_on_submit",
            "property_type": "Check",
            "value": "1",
        },
        {
            "doctype_or_field": "DocField",
            "doc_type": "Sales Invoice",
            "field_name": "advances",
            "property": "allow_on_submit",
            "property_type": "Check",
            "value": "1",
        },
        {
            "doctype_or_field": "DocField",
            "doc_type": "Expense Claim",
            "field_name": "advances",
            "property": "allow_on_submit",
            "property_type": "Check",
            "value": "1",
        },
    ]

    for ps_data in property_setters:
        ps_name = f"{ps_data['doc_type']}-{ps_data['field_name']}-{ps_data['property']}"
        if not frappe.db.exists("Property Setter", ps_name):
            ps = frappe.new_doc("Property Setter")
            ps.name = ps_name
            ps.doctype_or_field = ps_data["doctype_or_field"]
            ps.doc_type = ps_data["doc_type"]
            ps.field_name = ps_data["field_name"]
            ps.property = ps_data["property"]
            ps.property_type = ps_data["property_type"]
            ps.value = ps_data["value"]
            ps.module = "Imogi Finance"
            ps.flags.ignore_permissions = True
            ps.insert()
            frappe.db.commit()


__all__ = [
    "get_tax_amount_from_gl",
    "get_tax_amounts_batch",
    "validate_tax_register_configuration",
    "validate_vat_input_configuration",
    "validate_vat_output_configuration",
    "validate_withholding_configuration",
    "ensure_coretax_export_doctypes",
    "ensure_advances_allow_on_submit",
]
