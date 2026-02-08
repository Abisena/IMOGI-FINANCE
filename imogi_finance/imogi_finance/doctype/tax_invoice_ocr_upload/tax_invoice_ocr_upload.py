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
        
        # Prevent manual changes to parse_status (set automatically by parser or via approve_parse method)
        if self.has_value_changed("parse_status") and not self.flags.allow_parse_status_update:
            old_status = self.get_doc_before_save().parse_status if self.get_doc_before_save() else None
            if old_status:
                frappe.throw(_("Parse Status tidak boleh diubah manual. Status ini di-set otomatis oleh sistem atau via tombol 'Review & Approve'."))
        
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
        Parse line items from PDF using unified layout-aware parser.
        
        Supports both text-layer PDFs (PyMuPDF) and scanned PDFs (Google Vision OCR).
        Automatically uses vision_json from ocr_raw_json if PyMuPDF extraction fails.
        
        This method is called after OCR completes to extract individual
        line items from the tax invoice with proper column mapping.
        
        Race condition guards:
        - If auto_triggered and ocr_status is Queued/Processing, skip (OCR not done)
        - Manual trigger always allowed (user responsibility)
        
        Args:
            auto_triggered: If True, triggered automatically after OCR (no user message)
        """
        # 🔥 Race condition guard: Prevent parsing while OCR is still running
        if self.ocr_status in ("Queued", "Processing") and auto_triggered:
            frappe.logger().warning(
                f"[PARSE SKIP] {self.name}: OCR status is {self.ocr_status}, cannot auto-parse"
            )
            return {"success": False, "error": f"OCR is {self.ocr_status}"}
        
        # Additional guard: For auto-triggered, ensure we have parseable data
        if auto_triggered and self.ocr_status != "Done" and not self.ocr_raw_json:
            frappe.logger().warning(
                f"[PARSE SKIP] {self.name}: No parseable data (ocr_status={self.ocr_status}, no ocr_raw_json)"
            )
            return {"success": False, "error": "No OCR data to parse"}
        
        from imogi_finance.imogi_finance.parsers.faktur_pajak_parser import parse_invoice
        from imogi_finance.imogi_finance.parsers.normalization import normalize_all_items
        from imogi_finance.imogi_finance.parsers.validation import (
            validate_all_line_items,
            validate_invoice_totals,
            determine_parse_status,
            generate_validation_summary_html
        )
        
        if not self.tax_invoice_pdf:
            frappe.throw(_("No PDF attached"))
        
        # 🔥 FRAPPE CLOUD SAFE: Pass file_url directly to parser
        # The parser now uses bytes-based extraction via Frappe File API
        # This works with local files, S3, and remote storage
        file_url = self.tax_invoice_pdf
        frappe.logger().info(f"[PARSE] Using file URL for Cloud-safe extraction: {file_url}")

        
        # Try to load vision_json from ocr_raw_json if available (for scanned PDFs)
        vision_json = None
        vision_json_present = False
        if self.ocr_raw_json:
            try:
                vision_json = json.loads(self.ocr_raw_json)
                vision_json_present = bool(vision_json)  # Track if valid JSON loaded
            except Exception as json_err:
                frappe.logger().warning(
                    f"Failed to parse ocr_raw_json for {self.name}: {str(json_err)}. "
                    "Will fallback to PyMuPDF extraction."
                )
                vision_json_present = False
        
        try:
            # 🔥 Parse invoice using Cloud-safe unified parser
            # Uses bytes-based extraction via Frappe File API
            tax_rate = flt(self.tax_rate or 0.11)
            parse_result = parse_invoice(
                file_url_or_path=file_url,  # Cloud-safe: passes URL, not path
                vision_json=vision_json, 
                tax_rate=tax_rate
            )
            
            # Inject vision_json_present into debug_info for troubleshooting
            if "debug_info" not in parse_result:
                parse_result["debug_info"] = {}
            parse_result["debug_info"]["vision_json_present"] = vision_json_present
            
            if not parse_result.get("success"):
                errors = "; ".join(parse_result.get("errors", []))
                
                # Set status to Needs Review with clear error message
                self.parse_status = "Needs Review"
                self.validation_summary = f"""
                <div style="padding: 10px; background: #fff3cd; border-left: 4px solid #ffc107;">
                    <strong>⚠️ Parsing Failed</strong><br>
                    {errors}<br><br>
                    <small>Check Error Log for details. Unified parser supports both PyMuPDF (text-layer) and Google Vision OCR (scanned PDFs).</small>
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
                
                # Differentiate: no tokens (extraction failed) vs layout issue
                if token_count == 0:
                    # No text extracted - both PyMuPDF and Vision OCR failed
                    self.validation_summary = """
                    <div style="padding: 10px; background: #fff3cd; border-left: 4px solid #ffc107;">
                        <strong>⚠️ No Text Extracted from PDF</strong><br>
                        Token count: 0<br><br>
                        The unified parser tried both extraction methods:<br>
                        • <strong>PyMuPDF</strong> (for text-layer PDFs)<br>
                        • <strong>Google Vision OCR</strong> (from ocr_raw_json, if available)<br><br>
                        Possible causes:<br>
                        • PDF file corrupted or empty<br>
                        • OCR was not run (ocr_raw_json empty)<br>
                        • PyMuPDF not installed AND no OCR data available<br><br>
                        <small><strong>Solution:</strong> If this is a scanned PDF, run OCR first to populate ocr_raw_json, then re-parse.</small>
                    </div>
                    """
                    debug_info["warning"] = "No tokens extracted - both PyMuPDF and Vision OCR failed"
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
            
            # Auto-trigger verification after successful parsing
            # This validates business rules (NPWP match, duplicate, PPN calculation)
            if parse_status == "Approved" and self.fp_no:
                try:
                    from imogi_finance.tax_invoice_ocr import verify_tax_invoice
                    verify_tax_invoice(self, doctype="Tax Invoice OCR Upload", force=False)
                except Exception as e:
                    frappe.log_error(
                        title="Auto-Verify Failed After Parse",
                        message=f"Failed to verify {self.name} after parsing: {str(e)}"
                    )
            
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
        frappe.logger().info(
            f"[ON_UPDATE] {self.name}: ocr_status={self.ocr_status}, "
            f"parse_status={self.parse_status}, items_count={len(self.items)}"
        )
        
        # Guard: Only enqueue if ALL conditions met (prevent duplicate jobs)
        should_enqueue = (
            self.ocr_status == "Done" and  # OCR completed
            self.tax_invoice_pdf and       # PDF exists
            not self.items and              # No items yet
            self.parse_status in ["Draft", None, ""] and  # Not yet parsed/processing
            self.ocr_raw_json  # Ensure we have OCR data to parse (extra safety)
        )
        
        frappe.logger().info(f"[ON_UPDATE] Should enqueue auto-parse: {should_enqueue}")
        
        if should_enqueue:
            # 🔥 CRITICAL: Use flag to prevent duplicate enqueues in same transaction
            if getattr(self, '_auto_parse_enqueued', False):
                frappe.logger().debug(f"[ON_UPDATE] Auto-parse already enqueued in this transaction, skipping")
                return
            
            # Additional guard: Check if already enqueued (prevent double-click spam)
            # This prevents multiple jobs if user saves multiple times quickly
            if not frappe.flags.in_test:
                # In production: check for existing queued jobs
                try:
                    from frappe.utils.background_jobs import get_jobs
                    existing_jobs = get_jobs(
                        site=frappe.local.site,
                        queue="default",
                        key="job_name"
                    )
                    
                    # Deterministic job_name pattern: "parse:Tax Invoice OCR Upload:{docname}"
                    job_signature = f"parse:Tax Invoice OCR Upload:{self.name}"
                    if any(job_signature in str(job) for job in existing_jobs):
                        frappe.logger().debug(f"[ON_UPDATE] Parse job already queued for {self.name}, skipping")
                        return
                except Exception as e:
                    # If get_jobs fails, continue (better to enqueue duplicate than miss)
                    frappe.logger().warning(f"[ON_UPDATE] Could not check existing jobs: {e}")
            
            frappe.logger().info(f"[ON_UPDATE] Enqueueing auto-parse for {self.name}")
            
            # Mark as enqueued to prevent duplicate in same transaction
            self._auto_parse_enqueued = True
            
            # Deterministic job_name: "parse:Tax Invoice OCR Upload:{docname}"
            job_name = f"parse:Tax Invoice OCR Upload:{self.name}"
            
            # Enqueue background job with unique job_name per document
            frappe.enqueue(
                method="imogi_finance.imogi_finance.doctype.tax_invoice_ocr_upload.tax_invoice_ocr_upload.auto_parse_line_items",
                queue="default",
                timeout=60,
                doc_name=self.name,
                job_name=job_name,
                now=frappe.flags.in_test,
                enqueue_after_commit=True  # Ensure doc.save() is committed before job runs
            )
            frappe.logger().info(f"[ON_UPDATE] Enqueued parse job: {job_name}")

    
    def _update_validation_summary(self):
        """Update validation summary HTML based on current items."""
        if not self.items:
            self.validation_summary = ""
            return
        
        from imogi_finance.imogi_finance.parsers.validation import (
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


@frappe.whitelist()
def approve_parse(docname: str):
    """
    Manually approve parse status after user has reviewed and fixed data.
    
    This method bypasses the read_only restriction on parse_status field.
    Should only be called when user has verified all line items.
    
    Args:
        docname: Name of Tax Invoice OCR Upload document
    
    Returns:
        dict: {"ok": True} if successful, {"ok": False, "message": error} if failed
    """
    try:
        doc = frappe.get_doc("Tax Invoice OCR Upload", docname)
        
        # Validation: Check if document has items
        if not doc.items or len(doc.items) == 0:
            return {
                "ok": False,
                "message": _("Cannot approve: No line items found. Line items are parsed automatically after OCR completes.")
            }
        
        # Optional: Check if any items have very low confidence (user decision to override)
        # low_confidence_items = [item for item in doc.items if flt(item.row_confidence) < 0.85]
        # if low_confidence_items:
        #     return {
        #         "ok": False,
        #         "message": _("Cannot approve: {0} items have confidence below 0.85").format(len(low_confidence_items))
        #     }
        
        # Set flag to allow parse_status update
        doc.flags.allow_parse_status_update = True
        doc.parse_status = "Approved"
        doc.save(ignore_permissions=True)
        
        frappe.logger().info(f"Parse status manually approved for {docname} by {frappe.session.user}")
        
        return {"ok": True}
        
    except Exception as e:
        frappe.log_error(
            title="Manual Parse Approval Failed",
            message=f"Failed to approve parse for {docname}: {str(e)}\n{frappe.get_traceback()}"
        )
        return {
            "ok": False,
            "message": _("Error: {0}").format(str(e))
        }


def auto_parse_line_items(doc_name: str):
    """
    Background job to auto-parse line items after OCR completes.
    
    Race condition guards:
    - Skip if doc already has items (another job parsed first)
    - Skip if ocr_status != "Done" (OCR not complete or failed)
    - Skip if no ocr_raw_json and no PDF (no data to parse)
    
    Args:
        doc_name: Name of Tax Invoice OCR Upload document
    """
    frappe.logger().info(f"[AUTO-PARSE START] {doc_name}")
    
    try:
        doc = frappe.get_doc("Tax Invoice OCR Upload", doc_name)
        frappe.logger().info(
            f"[AUTO-PARSE] Doc loaded: ocr_status={doc.ocr_status}, "
            f"parse_status={doc.parse_status}, items_count={len(doc.items)}"
        )
        
        # 🔥 Guard: Skip if already parsed (race condition protection)
        if doc.items and len(doc.items) > 0:
            frappe.logger().info(f"[AUTO-PARSE SKIP] {doc_name} already has {len(doc.items)} items")
            return
        
        # Guard: Skip if OCR not done
        if doc.ocr_status != "Done":
            frappe.logger().warning(f"[AUTO-PARSE SKIP] {doc_name} OCR status is {doc.ocr_status}, not Done")
            return
        
        # 🔥 Additional guard: Ensure we have parseable data
        if not doc.ocr_raw_json and not doc.tax_invoice_pdf:
            frappe.logger().warning(f"[AUTO-PARSE SKIP] {doc_name}: No ocr_raw_json and no PDF")
            return
        
        frappe.logger().info(f"[AUTO-PARSE] Starting parse for {doc_name}")
        doc.parse_line_items(auto_triggered=True)
        frappe.db.commit()
        
        frappe.logger().info(
            f"[AUTO-PARSE SUCCESS] {doc_name}: "
            f"Status={doc.parse_status}, Items={len(doc.items)}"
        )
    except Exception as e:
        frappe.logger().error(
            f"[AUTO-PARSE FAILED] {doc_name}: {str(e)}",
            exc_info=True
        )
        frappe.log_error(
            title="Auto-Parse Line Items Failed",
            message=f"Failed to auto-parse {doc_name}: {str(e)}\n{frappe.get_traceback()}"
        )
