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
                    {
                        "ocr_status": "Queued",
                        "validation_summary": """
                        <div style="padding: 10px; background: #d1ecf1; border-left: 4px solid #0c5460;">
                            <strong>🔄 Scanned PDF Detected</strong><br><br>
                            This PDF appears to be a scanned image.<br>
                            OCR has been queued automatically.<br><br>
                            <small>Refresh this page in a few seconds to see progress.</small>
                        </div>
                        """
                    },
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

    @frappe.whitelist()
    def parse_line_items(self, auto_triggered: bool = False):
        """
        Parse line items from PDF using unified layout-aware parser.

        Supports both text-layer PDFs (PyMuPDF) and scanned PDFs (Google Vision OCR).
        Automatically uses vision_json from ocr_raw_json if PyMuPDF extraction fails.

        🔥 PHASE 1 FIX: Automatic Inclusive VAT Detection & Correction
        - Detects when Harga Jual includes 11% VAT (common in Indonesian invoices)
        - Auto-recalculates DPP from inclusive amounts using formula: DPP = Harga Jual / 1.11
        - Tracks which items were recalculated for visibility in validation
        - Uses context-aware tolerance for DPP/PPN validation

        Enhanced Validation:
        - Item code validation: flags invalid/default codes ("000000")
        - Invoice date checking: validates against fiscal period
        - Number format validation: detects OCR parsing errors
        - Enhanced summation validation: detailed discrepancy reporting
        - Improved error messages: explain VAT detection and suggest actions

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
        from imogi_finance.imogi_finance.parsers.normalization import (
            normalize_all_items,
            detect_vat_inclusivity,
            recalculate_dpp_from_inclusive,
            validate_number_format
        )
        from imogi_finance.imogi_finance.parsers.validation import (
            validate_all_line_items,
            validate_invoice_totals,
            validate_line_summation,
            determine_parse_status,
            generate_validation_summary_html,
            validate_item_code,
            validate_invoice_date
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
                self.flags.allow_parse_status_update = True  # Allow system to update parse_status
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

            # 🔥 PHASE 1 FIX: Detect and apply inclusive VAT correction
            # This handles invoices where Harga Jual includes 11% VAT
            vat_inclusivity_results = []
            for item in items:
                # Check if this item's amounts suggest inclusive VAT
                vat_context = detect_vat_inclusivity(
                    harga_jual=item.get("harga_jual"),
                    dpp=item.get("dpp"),
                    ppn=item.get("ppn"),
                    tax_rate=tax_rate,
                    tolerance_percentage=0.02  # 2% tolerance
                )

                # If amounts are inclusive, auto-correct DPP
                if vat_context.get("is_inclusive"):
                    corrected = recalculate_dpp_from_inclusive(
                        harga_jual=item.get("harga_jual"),
                        tax_rate=tax_rate
                    )

                    # Update item with corrected values
                    original_dpp = item.get("dpp")
                    original_ppn = item.get("ppn")
                    item["dpp"] = corrected["dpp"]
                    item["ppn"] = corrected["ppn"]
                    item["dpp_was_recalculated"] = True
                    item["original_dpp"] = original_dpp
                    item["original_ppn"] = original_ppn

                    frappe.logger().info(
                        f"VAT Inclusive detected for line {item.get('line_no')}: "
                        f"Recalculated DPP from {original_dpp} to {corrected['dpp']}"
                    )

                vat_inclusivity_results.append(vat_context)

            # Guard: If no items extracted, treat as parsing issue
            if not items:
                # Get token count to distinguish error types
                debug_info = parse_result.get("debug_info", {})
                token_count = debug_info.get("token_count", 0)

                # 🔥 AUTO-OCR FALLBACK: If no tokens and OCR not run, auto-trigger OCR
                if token_count == 0 and not vision_json_present and self.ocr_status != "Done":
                    # Check if OCR is enabled and provider ready
                    try:
                        from imogi_finance.api.tax_invoice import run_ocr_for_upload

                        frappe.logger().info(
                            f"[AUTO-OCR] {self.name}: No text extracted, auto-triggering OCR"
                        )

                        # Set status to indicate OCR is being queued
                        self.flags.allow_parse_status_update = True  # Allow system to update parse_status
                        self.parse_status = "Needs Review"
                        self.validation_summary = """
                        <div style="padding: 10px; background: #d1ecf1; border-left: 4px solid #0c5460;">
                            <strong>🔄 Auto-OCR Triggered</strong><br><br>
                            PDF appears to be a scanned image without text layer.<br>
                            OCR is being queued automatically.<br><br>
                            <strong>Next steps:</strong><br>
                            1. Wait for OCR to complete (ocr_status → Done)<br>
                            2. Line items will be parsed automatically after OCR<br><br>
                            <small>Refresh this page in a few seconds to see progress.</small>
                        </div>
                        """
                        self.save()

                        # Queue OCR
                        run_ocr_for_upload(self.name)

                        frappe.db.commit()

                        return {
                            "success": False,
                            "auto_ocr_triggered": True,
                            "message": "OCR queued automatically for scanned PDF"
                        }

                    except Exception as ocr_err:
                        frappe.logger().warning(
                            f"[AUTO-OCR FAILED] {self.name}: {str(ocr_err)}"
                        )
                        # Continue with normal error handling below

                self.flags.allow_parse_status_update = True  # Allow system to update parse_status
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
                        <small><strong>Solution:</strong> If this is a scanned PDF, run OCR first to populate ocor_raw_json, then re-parse.</small>
                    </div>
                    """
                    debug_info["warning"] = "No tokens extracted - both PyMuPDF and Vision OCR failed"
                else:
                    # Tokens extracted but no table detected - layout issue
                    # Check if OCR was run
                    ocr_available = bool(vision_json_present)
                    ocr_hint = ""
                    if not ocr_available:
                        ocr_hint = """<br><br>
                        <strong>🔥 Tip:</strong> If this is a scanned PDF, you may need to:<br>
                        1. Click <strong>"Run OCR"</strong> button first<br>
                        2. Wait for OCR to complete<br>
                        3. Then click <strong>"🔄 Re-Parse Line Items"</strong>
                        """

                    self.validation_summary = f"""
                    <div style="padding: 10px; background: #fff3cd; border-left: 4px solid #ffc107;">
                        <strong>⚠️ Table Header Not Found</strong><br>
                        Token count: {token_count} (text extracted)<br>
                        OCR data available: {'Yes' if ocr_available else 'No'}<br><br>
                        Could not detect table header row with Harga Jual/DPP/PPN columns.<br><br>
                        Possible causes:<br>
                        • <strong>Non-standard Faktur Pajak template</strong><br>
                        • Table header keywords not found<br>
                        • PDF is scanned image without OCR{ocr_hint}<br><br>
                        <small>Check parsing_debug_json field for extracted tokens.</small>
                    </div>
                    """
                    debug_info["warning"] = f"Table header not found - {token_count} tokens extracted"
                    debug_info["ocr_available"] = ocr_available

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

            # =================================================================
            # 🔥 LAYOUT-AWARE SUMMARY RE-EXTRACTION
            # Re-extract header-level DPP/PPN/Harga Jual from Vision JSON
            # coordinates to fix the field-swap bug where the regex parser
            # wrote PPN into the DPP field.
            # =================================================================
            if vision_json:
                try:
                    from imogi_finance.imogi_finance.parsers.layout_aware_parser import (
                        process_with_layout_parser,
                    )
                    layout_result = process_with_layout_parser(
                        vision_json=vision_json,
                        faktur_no=self.fp_no or "",
                        faktur_type=(self.fp_no or "")[:3],
                        ocr_text="",  # text will be auto-resolved from Vision JSON
                    )
                    layout_dpp = layout_result.get("dpp", 0)
                    layout_ppn = layout_result.get("ppn", 0)

                    # Guard: skip override if existing (text-parsed) values
                    # are much larger — summary totals shouldn't shrink.
                    existing_dpp = flt(self.dpp)
                    skip_layout = (
                        existing_dpp > 0
                        and layout_dpp > 0
                        and existing_dpp > layout_dpp * 2
                    )
                    if skip_layout:
                        frappe.logger().warning(
                            f"[PARSE] Layout DPP ({layout_dpp:,.0f}) << existing "
                            f"DPP ({existing_dpp:,.0f}); skipping layout override"
                        )

                    if (
                        layout_dpp > 0
                        and layout_ppn > 0
                        and layout_result.get("is_valid")
                        and not skip_layout
                    ):
                        if layout_dpp != flt(self.dpp) or layout_ppn != flt(self.ppn):
                            frappe.logger().info(
                                f"[PARSE] Layout-aware summary override: "
                                f"DPP {self.dpp} → {layout_dpp}, "
                                f"PPN {self.ppn} → {layout_ppn}"
                            )
                            self.dpp = layout_dpp
                            self.ppn = layout_ppn
                            if layout_result.get("harga_jual", 0) > 0:
                                self.harga_jual = layout_result["harga_jual"]
                            if layout_result.get("detected_tax_rate"):
                                self.tax_rate = layout_result["detected_tax_rate"]
                except Exception as layout_err:
                    frappe.logger().warning(
                        f"[PARSE] Layout-aware summary extraction failed: {layout_err}"
                    )

            # =================================================================
            # 🔥 MULTIROW PIPELINE: Cross-Validation & Fallback
            # Uses regex-based summary extraction and multi-row item grouping
            # to validate / correct the primary parser output (Fixes #1–#3).
            # =================================================================
            if vision_json:
                try:
                    from imogi_finance.imogi_finance.parsers.multirow_parser import (
                        parse_tax_invoice_multirow,
                        validate_parsed_data as multirow_validate,
                    )

                    multirow_result = parse_tax_invoice_multirow(
                        vision_json=vision_json,
                        tax_rate=flt(self.tax_rate or 0.12),
                    )

                    if multirow_result.get('success'):
                        mr_summary = multirow_result['summary']
                        mr_items = multirow_result['items']
                        mr_validation = multirow_result['validation']

                        # -- Summary cross-validation --
                        # If multirow summary has DPP/PPN and passes validation,
                        # check if current values are suspiciously different.
                        mr_dpp = flt(mr_summary.get('dpp', 0))
                        mr_ppn = flt(mr_summary.get('ppn', 0))
                        mr_hj = flt(mr_summary.get('harga_jual', 0))
                        current_dpp = flt(self.dpp)
                        current_ppn = flt(self.ppn)
                        current_hj = flt(self.harga_jual)

                        # For summary override, only require PPN/DPP ratio
                        # to be consistent.  Full item validation (is_valid)
                        # is only needed for the line-items fallback.
                        mr_ppn_ratio_ok = any(
                            abs(mr_ppn - mr_dpp * rate) <= mr_dpp * rate * 0.20
                            for rate in (0.12, 0.11, 0.10)
                        ) if mr_dpp > 0 else False

                        if mr_dpp > 0 and mr_ppn > 0 and (
                            mr_validation.get('is_valid') or mr_ppn_ratio_ok
                        ):
                            # Override if multirow values are significantly larger
                            # (primary parser may have picked up item-level values
                            # instead of summary totals)
                            should_override = False

                            if current_dpp > 0 and mr_dpp > current_dpp * 2:
                                should_override = True
                                frappe.logger().warning(
                                    f"[MULTIROW] DPP cross-validation: multirow "
                                    f"{mr_dpp:,.0f} >> current {current_dpp:,.0f}"
                                )
                            elif current_dpp == 0 and mr_dpp > 0:
                                should_override = True
                            # Also override when PPN ratio is clearly wrong
                            elif (
                                current_dpp > 0
                                and current_ppn > 0
                                and mr_dpp > current_dpp * 1.5
                            ):
                                should_override = True
                                frappe.logger().warning(
                                    f"[MULTIROW] DPP cross-validation (1.5x): multirow "
                                    f"{mr_dpp:,.0f} > current {current_dpp:,.0f}"
                                )

                            if should_override:
                                frappe.logger().info(
                                    f"[MULTIROW] Summary override: "
                                    f"DPP {current_dpp:,.0f} → {mr_dpp:,.0f}, "
                                    f"PPN {current_ppn:,.0f} → {mr_ppn:,.0f}, "
                                    f"HJ {current_hj:,.0f} → {mr_hj:,.0f}"
                                )
                                self.dpp = mr_dpp
                                self.ppn = mr_ppn
                                if mr_hj > 0:
                                    self.harga_jual = mr_hj

                                # Also update notes JSON with corrected values
                                try:
                                    if self.notes:
                                        notes_obj = json.loads(self.notes)
                                        notes_obj["ringkasan_pajak"] = {
                                            "harga_jual": float(self.harga_jual or 0),
                                            "dasar_pengenaan_pajak": float(self.dpp or 0),
                                            "jumlah_ppn": float(self.ppn or 0),
                                        }
                                        notes_obj.setdefault("validation_notes", []).append(
                                            f"Multirow parser corrected summary: "
                                            f"DPP {current_dpp:,.0f} → {mr_dpp:,.0f}, "
                                            f"PPN {current_ppn:,.0f} → {mr_ppn:,.0f}"
                                        )
                                        self.notes = json.dumps(notes_obj, ensure_ascii=False, indent=2)
                                except (json.JSONDecodeError, TypeError, ValueError):
                                    pass

                        # -- Line items cross-validation --
                        # If primary items fail validation against summary
                        # OR show signs of mangled parsing, use multirow items.
                        primary_sum = sum(
                            flt(i.get('harga_jual') or i.get('raw_harga_jual'))
                            for i in validated_items
                        )
                        summary_hj = flt(self.harga_jual)

                        primary_sum_ok = (
                            summary_hj > 0
                            and abs(primary_sum - summary_hj) <= summary_hj * 0.05
                        )

                        # Detect signs of mangled items even if sum matches:
                        # - Zero-value items (parsing error)
                        # - Descriptions with "000000" (item code leaked into desc)
                        # - More items than multirow found (rows not grouped)
                        has_zero_items = any(
                            flt(i.get('harga_jual') or i.get('raw_harga_jual')) == 0
                            for i in validated_items
                        )
                        has_mangled_desc = any(
                            '000000' in str(i.get('description', ''))
                            for i in validated_items
                        )
                        item_count_mismatch = (
                            len(mr_items) > 0
                            and len(validated_items) > len(mr_items)
                        )
                        primary_items_suspect = (
                            has_zero_items or has_mangled_desc or item_count_mismatch
                        )

                        use_multirow_items = (
                            mr_validation.get('is_valid')
                            and len(mr_items) > 0
                            and (not primary_sum_ok or primary_items_suspect)
                        )

                        if use_multirow_items:
                            frappe.logger().info(
                                f"[MULTIROW] Line items fallback: "
                                f"primary_sum_ok={primary_sum_ok}, "
                                f"zero_items={has_zero_items}, "
                                f"mangled={has_mangled_desc}, "
                                f"count_mismatch={item_count_mismatch} "
                                f"({len(validated_items)} vs {len(mr_items)}). "
                                f"Using {len(mr_items)} multirow items."
                            )

                            # Convert multirow items to the expected format
                            validated_items = []
                            for mr_item in mr_items:
                                validated_items.append({
                                    'line_no': mr_item.get('line_no', 0),
                                    'description': mr_item.get('description', ''),
                                    'harga_jual': str(mr_item.get('harga_jual', 0)),
                                    'dpp': str(mr_item.get('dpp', 0)),
                                    'ppn': str(mr_item.get('ppn', 0)),
                                    'qty': mr_item.get('qty', 0),
                                    'unit_price': mr_item.get('unit_price', 0),
                                    'page_no': 1,
                                    'source': 'multirow_fallback',
                                })

                            # Re-normalize the replacement items
                            validated_items = normalize_all_items(validated_items)
                            validated_items, invalid_items = validate_all_line_items(
                                validated_items, tax_rate
                            )

                        # Store multirow debug info
                        debug_info = parse_result.get("debug_info", {})
                        debug_info["multirow_validation"] = {
                            "is_valid": mr_validation.get('is_valid'),
                            "items_count": len(mr_items),
                            "summary": mr_summary,
                            "checks": mr_validation.get('checks', {}),
                            "errors": mr_validation.get('errors', []),
                            "warnings": mr_validation.get('warnings', []),
                        }

                except Exception as mr_err:
                    frappe.logger().warning(
                        f"[MULTIROW] Cross-validation failed: {mr_err}"
                    )

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
            debug_info["vat_inclusivity_results"] = vat_inclusivity_results
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
def revalidate_items(docname: str):
    """
    Re-validate all line items using current tax_rate.

    This is useful after tax_rate is changed via set_value (which doesn't trigger validate).
    It recalculates expected PPN for each item and updates validation_summary + parse_status.

    Args:
        docname: Name of Tax Invoice OCR Upload document

    Returns:
        dict: {"ok": True, "parse_status": str, "items_count": int} or error
    """
    try:
        doc = frappe.get_doc("Tax Invoice OCR Upload", docname)

        if not doc.items or len(doc.items) == 0:
            return {
                "ok": False,
                "message": _("No line items to validate. Run Parse Line Items first.")
            }

        from imogi_finance.imogi_finance.parsers.validation import (
            validate_all_line_items,
            validate_invoice_totals,
            generate_validation_summary_html,
            determine_parse_status
        )

        # Get current tax_rate from doc
        tax_rate = flt(doc.tax_rate or 0.11)

        # Convert child table to dict list
        items = [item.as_dict() for item in doc.items]

        # Re-validate all items with current tax_rate
        validated_items, invalid_items = validate_all_line_items(items, tax_rate)

        # Validate totals
        header_totals = {
            "harga_jual": doc.harga_jual,
            "dpp": doc.dpp,
            "ppn": doc.ppn
        }
        totals_validation = validate_invoice_totals(validated_items, header_totals)

        # Determine new parse status
        header_complete = bool(doc.fp_no and doc.npwp and doc.fp_date)
        new_parse_status = determine_parse_status(
            validated_items,
            invalid_items,
            totals_validation,
            header_complete
        )

        # Generate validation summary HTML
        validation_html = generate_validation_summary_html(
            validated_items,
            invalid_items,
            totals_validation,
            new_parse_status
        )

        # Update doc
        doc.flags.allow_parse_status_update = True
        doc.parse_status = new_parse_status
        doc.validation_summary = validation_html
        doc.save()

        frappe.logger().info(
            f"[REVALIDATE] {docname}: tax_rate={tax_rate}, "
            f"parse_status={new_parse_status}, valid={len(validated_items)}, invalid={len(invalid_items)}"
        )

        return {
            "ok": True,
            "parse_status": new_parse_status,
            "items_count": len(validated_items),
            "invalid_count": len(invalid_items),
            "tax_rate": tax_rate
        }

    except Exception as e:
        frappe.log_error(
            title="Re-Validate Items Failed",
            message=f"Failed to re-validate {docname}: {str(e)}\n{frappe.get_traceback()}"
        )
        return {
            "ok": False,
            "message": str(e)
        }


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

        # 🔥 NEW: Reload document to ensure we have latest version (race condition mitigation)
        doc.reload()

        # Re-check items after reload (another job might have parsed while we were loading)
        if doc.items and len(doc.items) > 0:
            frappe.logger().info(f"[AUTO-PARSE SKIP] {doc_name} has items after reload (race condition detected)")
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
