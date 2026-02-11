# Copyright (c) 2026, PT. Inovasi Terbaik Bangsa and contributors
# For license information, please see license.txt

from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.model.document import Document


def _resolve_tax_invoice_type(fp_no: str | None) -> tuple[str | None, str | None]:
    if not fp_no:
        return None, None

    digits = re.sub(r"\D", "", str(fp_no))
    if len(digits) < 3:
        return None, None

    prefix = digits[:3]
    type_row = frappe.db.get_value(
        "Tax Invoice Type",
        prefix,
        ["name", "transaction_description", "status_description"],
        as_dict=True,
    )
    if not type_row:
        return None, None

    description_parts = [type_row.transaction_description, type_row.status_description]
    description = " - ".join([part for part in description_parts if part])
    return type_row.name, description or type_row.transaction_description


class TaxInvoiceOCRUpload(Document):
    def validate(self):
        if not self.fp_no:
            frappe.throw(_("Tax Invoice Number is required."))
        if not self.tax_invoice_pdf:
            frappe.throw(_("Faktur Pajak PDF is required."))

        tax_invoice_type, type_description = _resolve_tax_invoice_type(self.fp_no)
        self.tax_invoice_type = tax_invoice_type
        self.tax_invoice_type_description = type_description

    def on_trash(self):
        """Clean up all links pointing to this OCR Upload before deletion.

        Clears link fields in Expense Request, Branch Expense Request,
        Purchase Invoice, and Sales Invoice that reference this document.
        Also deletes any Tax Invoice OCR Monitoring records.
        """
        from imogi_finance.tax_invoice_fields import UPLOAD_LINK_FIELDS

        # Clear links from all doctypes that may reference this OCR Upload
        for doctype, link_field in UPLOAD_LINK_FIELDS.items():
            if frappe.db.table_exists(doctype.replace(" ", "")):
                linked_docs = frappe.get_all(
                    doctype,
                    filters={link_field: self.name},
                    pluck="name",
                )
                for doc_name in linked_docs:
                    frappe.db.set_value(doctype, doc_name, link_field, None)

        # Delete any OCR Monitoring records for this upload
        if frappe.db.table_exists("Tax Invoice OCR Monitoring"):
            monitoring_records = frappe.get_all(
                "Tax Invoice OCR Monitoring",
                filters={"upload_name": self.name},
                pluck="name",
            )
            for record in monitoring_records:
                frappe.delete_doc("Tax Invoice OCR Monitoring", record, ignore_permissions=True, force=True)

    def after_insert(self):
        """
        Auto-detect scanned PDFs and trigger OCR on new document creation.

        Flow:
        1. Try PyMuPDF to check if PDF has text layer
        2. If no text (scanned PDF) → Auto-queue OCR
        3. OCR completes → on_update triggers auto-parse
        """
        if not self.tax_invoice_pdf:
            return

        # Check if OCR is enabled
        try:
            from imogi_finance.tax_invoice_ocr import get_settings
            settings = get_settings()
            if not settings.get("enable_tax_invoice_ocr"):
                frappe.logger().debug(f"[AFTER_INSERT] OCR disabled, skipping auto-detect")
                return
        except Exception:
            return

        # Try quick text extraction to detect scanned PDF
        try:
            from imogi_finance.imogi_finance.parsers.faktur_pajak_parser import extract_tokens

            # Quick extraction (PyMuPDF only, no vision_json)
            tokens = extract_tokens(file_url_or_path=self.tax_invoice_pdf, vision_json=None)

            has_text_layer = bool(tokens and len(tokens) > 10)  # At least 10 tokens = has text

            frappe.logger().info(
                f"[AFTER_INSERT] {self.name}: PDF text detection - "
                f"tokens={len(tokens) if tokens else 0}, has_text_layer={has_text_layer}"
            )

            if not has_text_layer:
                # Scanned PDF detected - auto-queue OCR
                frappe.logger().info(f"[AFTER_INSERT] {self.name}: Scanned PDF detected, auto-queueing OCR")

                from imogi_finance.api.tax_invoice import run_ocr_for_upload
                run_ocr_for_upload(self.name)

                # Update status to show OCR is queued
                frappe.db.set_value(
                    "Tax Invoice OCR Upload",
                    self.name,
                    {"ocr_status": "Queued"},
                    update_modified=False
                )

        except Exception as e:
            # Don't fail document creation if detection fails
            frappe.logger().warning(
                f"[AFTER_INSERT] {self.name}: Auto-detect failed: {str(e)}"
            )

    @frappe.whitelist()
    def refresh_status(self):
        from imogi_finance.api.tax_invoice import monitor_tax_invoice_ocr

        return monitor_tax_invoice_ocr(self.name, "Tax Invoice OCR Upload")

    def on_update(self):
        """Hook removed - line items auto-parsing no longer needed."""
        pass


# Removed functions: _update_validation_summary, revalidate_items, approve_parse, auto_parse_line_items
