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
        
        # 🆕 PPN Type is now REQUIRED - user must select before saving
        if not self.ppn_type:
            frappe.throw(_(
                "PPN Type is required. Please select the appropriate PPN type "
                "(Standard 11%, Standard 12%, Zero Rated, etc.) based on your tax invoice."
            ))

        tax_invoice_type, type_description = _resolve_tax_invoice_type(self.fp_no)
        self.tax_invoice_type = tax_invoice_type
        self.tax_invoice_type_description = type_description
        
        # 🆕 Cross-check Tax Invoice Type vs PPN Type
        ppn_type_match = False
        if self.tax_invoice_type and self.ppn_type:
            try:
                invoice_type_doc = frappe.get_doc("Tax Invoice Type", self.tax_invoice_type)
                is_valid, warning_message = invoice_type_doc.matches_ppn_type(self.ppn_type)
                
                if is_valid:
                    # ✅ PPN Type matches - good for auto-verify
                    ppn_type_match = True
                elif warning_message:
                    # ⚠️ Show warning but don't block save
                    frappe.msgprint(
                        msg=warning_message,
                        title=_("PPN Type Verification Warning"),
                        indicator="orange"
                    )
            except frappe.DoesNotExistError:
                # Tax Invoice Type not found in master - skip validation
                pass
        
        # 🆕 Cross-check FP Number: Compare doctype fp_no (autoname) vs OCR extracted fp_no
        # ⚠️ CRITICAL: fp_no is autoname (document name), cannot be changed after save
        fp_no_match = False
        ocr_fp_no = None
        
        # Only validate if OCR has run (ocr_text exists)
        if self.ocr_text:
            # Extract FP number from OCR text
            import re
            
            # Try to find FP number pattern in OCR text
            # Pattern: 010.000-24.12345678 or variations
            fp_patterns = [
                r'\b(\d{3}[.\s-]?\d{3}[.\s-]?\d{2}[.\s-]?\d{8})\b',  # Full pattern
                r'(?:Nomor|No\.?|NSFP)[:\s]*(\d{3}[.\s-]?\d{3}[.\s-]?\d{2}[.\s-]?\d{8})',  # With label
            ]
            
            for pattern in fp_patterns:
                matches = re.findall(pattern, self.ocr_text, re.IGNORECASE)
                if matches:
                    # Normalize extracted fp_no (remove spaces, keep dots and dashes)
                    ocr_fp_no = re.sub(r'\s+', '', matches[0])
                    break
            
            # Normalize both for comparison (remove dots, spaces, dashes)
            if ocr_fp_no:
                fp_normalized = re.sub(r'[.\s-]', '', self.fp_no.upper())
                ocr_normalized = re.sub(r'[.\s-]', '', ocr_fp_no.upper())
                
                if fp_normalized == ocr_normalized:
                    fp_no_match = True
            else:
                # Fallback: simple substring check
                fp_normalized = re.sub(r'[.\s-]', '', self.fp_no.upper())
                ocr_text_normalized = re.sub(r'[.\s-]', '', self.ocr_text.upper())
                
                if fp_normalized in ocr_text_normalized:
                    fp_no_match = True
                    ocr_fp_no = self.fp_no  # Assumed match
        
        # 🆕 Auto-set verification status based on multiple checks
        verification_notes_parts = []
        
        if ppn_type_match:
            verification_notes_parts.append("✅ PPN Type matches Tax Invoice Type")
        
        if fp_no_match:
            verification_notes_parts.append(f"✅ FP Number verified in OCR: {self.fp_no}")
        elif ocr_fp_no and ocr_fp_no != self.fp_no:
            # ⚠️ CRITICAL: Mismatch between document name (autoname) and OCR result
            verification_notes_parts.append(
                f"🚨 FP Number MISMATCH (autoname cannot be changed!):\n"
                f"   Document Name: {self.fp_no}\n"
                f"   OCR Detected: {ocr_fp_no}\n"
                f"   ⚠️ Please verify the correct invoice was uploaded or recreate document with correct FP number."
            )
            # Show prominent warning to user
            frappe.msgprint(
                msg=_(
                    "FP Number mismatch detected!<br><br>"
                    "<b>Document Name (autoname):</b> {0}<br>"
                    "<b>OCR Detected:</b> {1}<br><br>"
                    "⚠️ The document name cannot be changed. "
                    "Please verify you uploaded the correct PDF or delete this document and create a new one."
                ).format(self.fp_no, ocr_fp_no),
                title=_("FP Number Verification Failed"),
                indicator="red"
            )
        
        if self.dpp and self.ppn:
            verification_notes_parts.append("✅ DPP and PPN amounts present")
        
        # 🆕 Validate PPN amount matches selected PPN Type
        ppn_amount_match = False
        if self.ppn_type and self.dpp and self.ppn is not None:
            dpp_value = float(self.dpp)
            ppn_value = float(self.ppn)
            
            if dpp_value > 0:
                actual_rate = ppn_value / dpp_value if ppn_value > 0 else 0
                
                # Check rate based on PPN Type
                if "Standard 11%" in self.ppn_type:
                    expected_rate = 0.11
                    if abs(actual_rate - expected_rate) <= 0.02:  # 2% tolerance
                        ppn_amount_match = True
                        verification_notes_parts.append(f"✅ PPN amount matches rate: {actual_rate:.2%} ≈ 11%")
                    else:
                        verification_notes_parts.append(
                            f"⚠️ PPN rate mismatch: Expected 11%, actual {actual_rate:.2%}"
                        )
                
                elif "Standard 12%" in self.ppn_type:
                    expected_rate = 0.12
                    if abs(actual_rate - expected_rate) <= 0.02:  # 2% tolerance
                        ppn_amount_match = True
                        verification_notes_parts.append(f"✅ PPN amount matches rate: {actual_rate:.2%} ≈ 12%")
                    else:
                        verification_notes_parts.append(
                            f"⚠️ PPN rate mismatch: Expected 12%, actual {actual_rate:.2%}"
                        )
                
                elif "Zero Rated" in self.ppn_type or "Ekspor" in self.ppn_type:
                    if ppn_value == 0:
                        ppn_amount_match = True
                        verification_notes_parts.append("✅ PPN amount is 0 (Zero Rated)")
                    else:
                        verification_notes_parts.append(
                            f"⚠️ Zero Rated should have PPN=0, but got Rp {ppn_value:,.0f}"
                        )
                
                elif "Tidak Dipungut" in self.ppn_type or "Dibebaskan" in self.ppn_type:
                    if ppn_value == 0:
                        ppn_amount_match = True
                        verification_notes_parts.append(f"✅ PPN amount is 0 ({self.ppn_type})")
                    else:
                        verification_notes_parts.append(
                            f"⚠️ {self.ppn_type} should have PPN=0, but got Rp {ppn_value:,.0f}"
                        )
                
                elif "Bukan Objek PPN" in self.ppn_type:
                    if ppn_value == 0:
                        ppn_amount_match = True
                        verification_notes_parts.append("✅ PPN amount is 0 (Bukan Objek PPN)")
                    else:
                        verification_notes_parts.append(
                            f"⚠️ Bukan Objek PPN should have PPN=0, but got Rp {ppn_value:,.0f}"
                        )
                
                elif "Digital 1.1%" in self.ppn_type or "PMSE" in self.ppn_type:
                    expected_rate = 0.011
                    if abs(actual_rate - expected_rate) <= 0.005:  # 0.5% tolerance
                        ppn_amount_match = True
                        verification_notes_parts.append(f"✅ PPN amount matches rate: {actual_rate:.2%} ≈ 1.1%")
                    else:
                        verification_notes_parts.append(
                            f"⚠️ PPN rate mismatch: Expected 1.1%, actual {actual_rate:.2%}"
                        )
                
                elif "Custom" in self.ppn_type or "Other" in self.ppn_type:
                    # Custom tariff - always pass but show rate
                    ppn_amount_match = True
                    verification_notes_parts.append(
                        f"ℹ️ Custom PPN Type: Actual rate is {actual_rate:.2%}"
                    )
        
        # Auto-verify if ALL conditions met
        if ppn_type_match and fp_no_match and ppn_amount_match and self.dpp and self.ppn is not None:
            self.verification_status = "Verified"
            self.verification_notes = "\n".join(verification_notes_parts)
        elif self.verification_status != "Rejected":
            # Keep as "Needs Review" if not explicitly rejected
            self.verification_status = "Needs Review"
            if verification_notes_parts:
                self.verification_notes = "\n".join(verification_notes_parts)

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
