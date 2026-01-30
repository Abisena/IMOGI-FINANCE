# Copyright (c) 2026, PT. Inovasi Terbaik Bangsa and contributors
# For license information, please see license.txt

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.model.document import Document

from imogi_finance.tax_invoice_ocr import get_tax_invoice_ocr_monitoring


class TaxInvoiceOCRMonitoring(Document):
    def validate(self):
        """Auto-populate data if Target is Tax Invoice OCR Upload"""
        if self.target_doctype == "Tax Invoice OCR Upload" and self.target_name:
            self._populate_from_ocr_upload()

    def _populate_from_ocr_upload(self):
        """Fetch and populate data directly from Tax Invoice OCR Upload"""
        if not frappe.db.exists("Tax Invoice OCR Upload", self.target_name):
            return

        ocr_upload = frappe.get_doc("Tax Invoice OCR Upload", self.target_name)

        # Populate basic info
        self.upload_name = ocr_upload.name
        self.tax_invoice_pdf = ocr_upload.get("file_faktur_pajak")

        # Populate extracted data
        self.ocr_confidence = ocr_upload.get("confidence_level") or 0
        self.fp_date = ocr_upload.get("tanggal_faktur_pajak")
        self.npwp = ocr_upload.get("npwp_supplier")
        self.dpp = ocr_upload.get("dpp")
        self.ppn = ocr_upload.get("jumlah_ppn")
        self.ppnbm = ocr_upload.get("jumlah_ppnbm") or 0
        self.ppn_type = ocr_upload.get("tipe_ppn")

        # Populate validation flags
        self.duplicate_flag = 1 if ocr_upload.get("faktur_duplikat") else 0
        self.npwp_match = 1 if ocr_upload.get("npwp_sesuai") else 0

        # Populate status
        self.ocr_status = ocr_upload.get("status_ocr")
        self.verification_status = ocr_upload.get("status_verifikasi")
        self.verification_notes = ocr_upload.get("catatan_verifikasi")

        # Check if raw JSON exists
        ocr_json = ocr_upload.get("data_ocr_lengkap_json")
        if ocr_json:
            self.ocr_raw_json_present = 1
            self.ocr_raw_json = ocr_json

    @frappe.whitelist()
    def refresh_status(self):
        if not self.target_doctype or not self.target_name:
            frappe.throw(_("Target DocType and Target Name are required to refresh status."))

        # If target is OCR Upload directly, populate from it
        if self.target_doctype == "Tax Invoice OCR Upload":
            self._populate_from_ocr_upload()
            return {"success": True, "message": "Data refreshed from OCR Upload"}

        # Otherwise use the original logic for Purchase Invoice etc
        result = get_tax_invoice_ocr_monitoring(self.target_name, self.target_doctype)
        doc_info = result.get("doc") or {}
        job_info = result.get("job") or {}

        self.job_name = result.get("job_name")
        self.provider = result.get("provider")
        self.max_retry = result.get("max_retry")

        self.ocr_status = doc_info.get("ocr_status")
        self.verification_status = doc_info.get("verification_status")
        self.verification_notes = doc_info.get("verification_notes")
        self.upload_name = doc_info.get("upload_name")
        self.ocr_confidence = doc_info.get("ocr_confidence")
        self.fp_no = doc_info.get("fp_no")
        self.fp_date = doc_info.get("fp_date")
        self.npwp = doc_info.get("npwp")
        self.dpp = doc_info.get("dpp")
        self.ppn = doc_info.get("ppn")
        self.ppnbm = doc_info.get("ppnbm")
        self.ppn_type = doc_info.get("ppn_type")
        self.duplicate_flag = doc_info.get("duplicate_flag")
        self.npwp_match = doc_info.get("npwp_match")
        self.tax_invoice_pdf = doc_info.get("tax_invoice_pdf")
        self.ocr_raw_json_present = 1 if doc_info.get("ocr_raw_json_present") else 0
        self.ocr_raw_json = doc_info.get("ocr_raw_json")

        self.job_queue = job_info.get("queue")
        self.job_status = job_info.get("status")
        self.job_exc_info = job_info.get("exc_info")

        job_kwargs = job_info.get("kwargs")
        if isinstance(job_kwargs, str):
            self.job_kwargs = job_kwargs
        elif job_kwargs is not None:
            self.job_kwargs = json.dumps(job_kwargs, indent=2, ensure_ascii=False, default=str)
        else:
            self.job_kwargs = None

        self.enqueued_at = job_info.get("enqueued_at")
        self.started_at = job_info.get("started_at")
        self.ended_at = job_info.get("ended_at")

        return result
