# Copyright (c) 2026, PT. Inovasi Terbaik Bangsa and contributors
# For license information, please see license.txt

from __future__ import annotations

import json
import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_site_path


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
        
        # Prevent manual changes to parse_status (must be set via parse_line_items only)
        if self.has_value_changed("parse_status") and not self.flags.allow_parse_status_update:
            old_status = self.get_doc_before_save().parse_status if self.get_doc_before_save() else None
            if old_status:
                frappe.throw(_("Parse Status tidak boleh diubah manual. Gunakan tombol 'Parse Line Items'."))
        
        # Update validation summary if items exist
        if self.items:
            self._update_validation_summary()

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

    @frappe.whitelist()
    def refresh_status(self):
        from imogi_finance.api.tax_invoice import monitor_tax_invoice_ocr

        return monitor_tax_invoice_ocr(self.name, "Tax Invoice OCR Upload")
    
    @frappe.whitelist()
    def parse_line_items(self, auto_triggered: bool = False):
        """
        Parse line items from PDF using layout-aware parser.
        
        This method is called after OCR completes to extract individual
        line items from the tax invoice with proper column mapping.
        
        Args:
            auto_triggered: If True, triggered automatically after OCR (no user message)
        """
        from imogi_finance.parsers.faktur_pajak_parser import parse_invoice
        from imogi_finance.parsers.normalization import normalize_all_items
        from imogi_finance.parsers.validation import (
            validate_all_line_items,
            validate_invoice_totals,
            determine_parse_status,
            generate_validation_summary_html
        )
        
        if not self.tax_invoice_pdf:
            frappe.throw(_("No PDF attached"))
        
        # Get absolute path to PDF
        pdf_path = get_site_path(self.tax_invoice_pdf.strip("/"))
        
        try:
            # Parse invoice using PyMuPDF-based parser
            tax_rate = flt(self.tax_rate or 0.11)
            parse_result = parse_invoice(pdf_path, tax_rate)
            
            if not parse_result.get("success"):
                errors = "; ".join(parse_result.get("errors", []))
                
                # Set status to Needs Review with clear error message
                self.parse_status = "Needs Review"
                self.validation_summary = f"""
                <div style="padding: 10px; background: #fff3cd; border-left: 4px solid #ffc107;">
                    <strong>⚠️ Parsing Failed</strong><br>
                    {errors}<br><br>
                    <small>Check Error Log for details. For Frappe Cloud: verify build logs show PyMuPDF installation.</small>
                </div>
                """
                self.save()
                
                if auto_triggered:
                    frappe.log_error(
                        title="Auto-Parse Line Items Failed",
                        message=f"Error parsing {self.name}: {errors}"
                    )
                    return {"success": False, "errors": errors}
                else:
                    frappe.throw(_("Parsing failed: {0}").format(errors))
            
            # Normalize extracted items
            items = normalize_all_items(parse_result.get("items", []))
            
            # Guard: If no items extracted, treat as parsing issue
            if not items:
                # Get token count to distinguish error types
                debug_info = parse_result.get("debug_info", {})
                token_count = debug_info.get("token_count", 0)
                
                self.parse_status = "Needs Review"
                
                # Differentiate: no tokens (PyMuPDF/dependency) vs layout issue
                if token_count == 0:
                    # No text extracted - likely PyMuPDF missing or scanned PDF
                    self.validation_summary = """
                    <div style="padding: 10px; background: #fff3cd; border-left: 4px solid #ffc107;">
                        <strong>⚠️ No Text Extracted from PDF</strong><br>
                        Token count: 0<br><br>
                        Possible causes:<br>
                        • <strong>PyMuPDF not installed on server</strong> (most likely)<br>
                        • PDF is scanned image without text layer<br>
                        • PDF file corrupted or empty<br><br>
                        <small><strong>For Frappe Cloud:</strong> Verify build logs show PyMuPDF installation. 
                        If console import works but worker fails, try <strong>Clear Cache & Deploy</strong>.</small>
                    </div>
                    """
                    debug_info["warning"] = "No tokens extracted - PyMuPDF missing or scanned PDF"
                else:
                    # Tokens extracted but no table detected - layout issue
                    self.validation_summary = f"""
                    <div style="padding: 10px; background: #fff3cd; border-left: 4px solid #ffc107;">
                        <strong>⚠️ Layout Not Detected</strong><br>
                        Token count: {token_count} (text extracted successfully)<br><br>
                        Possible causes:<br>
                        • <strong>Non-standard Faktur Pajak template</strong><br>
                        • Table header keywords not found ("Harga Jual", "DPP", "PPN")<br>
                        • Unusual PDF layout or formatting<br><br>
                        <small>Check parsing_debug_json field for extracted tokens. 
                        Header keywords may be spelled differently or missing.</small>
                    </div>
                    """
                    debug_info["warning"] = f"Layout not detected - {token_count} tokens extracted but no table found"
                
                # Store debug info to help troubleshooting
                debug_info["auto_triggered"] = auto_triggered
                self.parsing_debug_json = json.dumps(debug_info, indent=2, ensure_ascii=False)
                
                self.save()
                
                if auto_triggered:
                    frappe.log_error(
                        title="No Line Items Extracted",
                        message=f"No items extracted from {self.name}. Token count: {debug_info.get('token_count', 0)}"
                    )
                    return {"success": False, "errors": "No items extracted"}
                else:
                    frappe.msgprint(
                        _("No line items extracted. Check validation_summary for details."),
                        indicator="orange"
                    )
                    return {"success": False, "items_count": 0}
            
            # Validate all items
            validated_items, invalid_items = validate_all_line_items(items, tax_rate)
            
            # Validate totals if header values exist
            header_totals = {
                "harga_jual": self.harga_jual,
                "dpp": self.dpp,
                "ppn": self.ppn
            }
            totals_validation = validate_invoice_totals(validated_items, header_totals)
            
            # Determine parse status
            header_complete = bool(self.fp_no and self.npwp and self.fp_date)
            parse_status = determine_parse_status(
                validated_items,
                invalid_items,
                totals_validation,
                header_complete
            )
            
            # Clear existing items and add new ones
            self.items = []
            for item in validated_items:
                self.append("items", item)
            
            # Store debug info (with size guard applied in parser)
            debug_info = parse_result.get("debug_info", {})
            debug_info["invalid_items"] = invalid_items
            debug_info["auto_triggered"] = auto_triggered
            self.parsing_debug_json = json.dumps(debug_info, indent=2, ensure_ascii=False)
            
            # Set parse status (set flag to allow update during parsing)
            self.flags.allow_parse_status_update = True
            self.parse_status = parse_status
            
            # Generate validation summary HTML
            validation_html = generate_validation_summary_html(
                validated_items,
                invalid_items,
                totals_validation,
                parse_status
            )
            self.validation_summary = validation_html
            
            # Save document
            self.save()
            
            if not auto_triggered:
                frappe.msgprint(
                    _("Successfully parsed {0} line items. Status: {1}").format(
                        len(validated_items),
                        parse_status
                    ),
                    indicator="green" if parse_status == "Approved" else "orange"
                )
            
            return {
                "success": True,
                "items_count": len(validated_items),
                "invalid_count": len(invalid_items),
                "parse_status": parse_status
            }
            
        except Exception as e:
            frappe.log_error(
                title="Tax Invoice Line Item Parsing Error",
                message=f"Error parsing {self.name}: {str(e)}\n{frappe.get_traceback()}"
            )
            if not auto_triggered:
                frappe.throw(_("Parsing error: {0}").format(str(e)))
            return {"success": False, "error": str(e)}
    
    def on_update(self):
        """Hook to auto-trigger line item parsing after OCR completes."""
        # Guard: Only enqueue if ALL conditions met (prevent duplicate jobs)
        should_enqueue = (
            self.ocr_status == "Done" and  # OCR completed
            self.tax_invoice_pdf and       # PDF exists
            not self.items and              # No items yet
            self.parse_status in ["Draft", None, ""]  # Not yet parsed/processing
        )
        
        if should_enqueue:
            # Additional guard: Check if already enqueued (prevent double-click spam)
            # This prevents multiple jobs if user saves multiple times quickly
            if not frappe.flags.in_test:
                # In production: check for existing queued jobs
                from frappe.utils.background_jobs import get_jobs
                existing_jobs = get_jobs(
                    site=frappe.local.site,
                    queue="default",
                    key="job_name"
                )
                
                job_signature = f"tax-invoice-auto-parse:{self.name}"
                if any(job_signature in str(job) for job in existing_jobs):
                    frappe.logger().debug(f"Parse job already queued for {self.name}, skipping")
                    return
            
            # Enqueue background job with unique job_name per document
            frappe.enqueue(
                method="imogi_finance.imogi_finance.doctype.tax_invoice_ocr_upload.tax_invoice_ocr_upload.auto_parse_line_items",
                queue="default",
                timeout=60,
                doc_name=self.name,
                job_name=f"tax-invoice-auto-parse:{self.name}",  # Unique per document for deduplication
                now=frappe.flags.in_test
            )
    
    def _update_validation_summary(self):
        """Update validation summary HTML based on current items."""
        if not self.items:
            self.validation_summary = ""
            return
        
        from imogi_finance.parsers.validation import (
            validate_all_line_items,
            validate_invoice_totals,
            generate_validation_summary_html
        )
        
        # Convert child table to dict list
        items = [item.as_dict() for item in self.items]
        
        # Validate
        tax_rate = flt(self.tax_rate or 0.11)
        validated_items, invalid_items = validate_all_line_items(items, tax_rate)
        
        header_totals = {
            "harga_jual": self.harga_jual,
            "dpp": self.dpp,
            "ppn": self.ppn
        }
        totals_validation = validate_invoice_totals(validated_items, header_totals)
        
        # Generate HTML
        validation_html = generate_validation_summary_html(
            validated_items,
            invalid_items,
            totals_validation,
            self.parse_status or "Draft"
        )
        self.validation_summary = validation_html


def auto_parse_line_items(doc_name: str):
    """
    Background job to auto-parse line items after OCR completes.
    
    Args:
        doc_name: Name of Tax Invoice OCR Upload document
    """
    try:
        doc = frappe.get_doc("Tax Invoice OCR Upload", doc_name)
        doc.parse_line_items(auto_triggered=True)
        frappe.db.commit()
        
        frappe.logger().info(
            f"Auto-parsed line items for {doc_name}: "
            f"Status={doc.parse_status}, Items={len(doc.items)}"
        )
    except Exception as e:
        frappe.log_error(
            title="Auto-Parse Line Items Failed",
            message=f"Failed to auto-parse {doc_name}: {str(e)}\n{frappe.get_traceback()}"
        )
