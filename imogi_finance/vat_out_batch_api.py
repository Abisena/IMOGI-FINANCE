# Copyright (c) 2026, PT. Inovasi Terbaik Bangsa and contributors
# For license information, please see license.txt

"""API endpoints for VAT OUT Batch operations."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now

from imogi_finance.tax_operations import generate_vat_out_batch_excel


@frappe.whitelist()
def generate_coretax_upload_file(batch_name: str):
	"""Generate Excel file for CoreTax upload.
	
	Args:
		batch_name: VAT OUT Batch name
		
	Returns:
		dict: File URL and status
	"""
	batch = frappe.get_doc("VAT OUT Batch", batch_name)
	batch.check_permission("write")
	
	# Check if already exported
	if batch.exported_on:
		frappe.throw(_("Batch already exported on {0}. Use regenerate if needed.").format(
			frappe.format(batch.exported_on, {"fieldtype": "Datetime"})
		))
	
	# Get template version
	from imogi_finance.imogi_finance.doctype.coretax_template_settings.coretax_template_settings import (
		CoreTaxTemplateSettings
	)
	template_info = CoreTaxTemplateSettings.get_active_template()
	
	# Generate file
	file_url = generate_vat_out_batch_excel(
		batch_name,
		include_fp_numbers=False,
		for_upload=True
	)
	
	# Update batch
	batch.coretax_export_file = file_url
	batch.template_version = template_info["version"]
	batch.exported_on = now()
	batch.flags.ignore_export_lock = True
	batch.save(ignore_permissions=True)
	
	return {
		"status": "success",
		"file_url": file_url,
		"message": _("Export file generated successfully")
	}


@frappe.whitelist()
def generate_reconciliation_file(batch_name: str):
	"""Generate reconciliation Excel file with FP numbers.
	
	Args:
		batch_name: VAT OUT Batch name
		
	Returns:
		dict: File URL and status
	"""
	batch = frappe.get_doc("VAT OUT Batch", batch_name)
	batch.check_permission("read")
	
	# Generate file with FP numbers
	file_url = generate_vat_out_batch_excel(
		batch_name,
		include_fp_numbers=True,
		for_upload=False
	)
	
	# Update batch
	batch.reconciliation_file = file_url
	batch.save(ignore_permissions=True)
	
	return {
		"status": "success",
		"file_url": file_url,
		"message": _("Reconciliation file generated successfully")
	}


@frappe.whitelist()
def import_fp_numbers_from_file(batch_name: str, file_data: str):
	"""Import FP numbers from uploaded CSV/Excel file.
	
	Args:
		batch_name: VAT OUT Batch name
		file_data: JSON string with import data
			Format: [{"group_id": 1, "fp_no": "...", "fp_date": "..."}]
			
	Returns:
		dict: Import summary with success/failed counts
	"""
	import json
	
	batch = frappe.get_doc("VAT OUT Batch", batch_name)
	batch.check_permission("write")
	
	# Parse file data
	try:
		import_rows = json.loads(file_data)
	except:
		frappe.throw(_("Invalid file data format"))
	
	# Build group map
	group_map = {g.group_id: g for g in batch.groups}
	
	success_count = 0
	failed_count = 0
	warnings = []
	
	for row in import_rows:
		try:
			# Primary match by group_id
			group_id = row.get("group_id")
			fp_no = row.get("fp_no")
			fp_date = row.get("fp_date")
			
			if not group_id or not fp_no or not fp_date:
				failed_count += 1
				warnings.append(f"Row missing required fields: {row}")
				continue
			
			# Validate FP number format
			if not _validate_fp_number(fp_no):
				failed_count += 1
				warnings.append(f"Invalid FP Number format: {fp_no}")
				continue
			
			# Check if group exists
			if group_id not in group_map:
				# Fallback: match by customer + totals
				fallback_group = _find_group_by_fallback(batch, row)
				if fallback_group:
					group_id = fallback_group.group_id
					warnings.append(f"Matched Group {group_id} by customer/totals fallback")
				else:
					failed_count += 1
					warnings.append(f"No matching group for: {row}")
					continue
			
			# Update group
			group = group_map[group_id]
			group.fp_no = fp_no
			group.fp_date = fp_date
			success_count += 1
			
		except Exception as e:
			failed_count += 1
			warnings.append(f"Error processing row {row}: {str(e)}")
	
	# Save batch
	if success_count > 0:
		batch.save(ignore_permissions=True)
		batch.add_comment("Info", _("Imported {0} FP numbers").format(success_count))
	
	return {
		"status": "success" if failed_count == 0 else "partial",
		"success_count": success_count,
		"failed_count": failed_count,
		"warnings": warnings,
		"message": _("Imported {0} of {1} records").format(success_count, len(import_rows))
	}


def _validate_fp_number(fp_no: str) -> bool:
	"""Validate FP number is 16 digits."""
	if not fp_no:
		return False
	
	# Remove any formatting
	fp_clean = fp_no.replace("-", "").replace(".", "").replace(" ", "")
	
	# Check if 16 digits
	return len(fp_clean) == 16 and fp_clean.isdigit()


def _find_group_by_fallback(batch, row):
	"""Find group by customer NPWP and totals (fallback matching).
	
	Args:
		batch: VAT OUT Batch document
		row: Import row with customer_npwp, total_dpp, total_ppn
		
	Returns:
		Group document or None
	"""
	customer_npwp = row.get("customer_npwp")
	total_dpp = row.get("total_dpp")
	total_ppn = row.get("total_ppn")
	
	if not customer_npwp:
		return None
	
	# Find matching group
	for group in batch.groups:
		if group.customer_npwp != customer_npwp:
			continue
		
		# Check totals with tolerance
		if total_dpp is not None:
			if abs((group.total_dpp or 0) - float(total_dpp)) > 0.01:
				continue
		
		if total_ppn is not None:
			if abs((group.total_ppn or 0) - float(total_ppn)) > 0.01:
				continue
		
		return group
	
	return None


@frappe.whitelist()
def bulk_upload_pdfs(batch_name: str, pdf_files: str):
	"""Upload multiple PDF files and match to groups.
	
	Args:
		batch_name: VAT OUT Batch name
		pdf_files: JSON string with list of file URLs
			
	Returns:
		dict: Upload summary
	"""
	import json
	import re
	
	batch = frappe.get_doc("VAT OUT Batch", batch_name)
	batch.check_permission("write")
	
	# Parse file list
	try:
		file_urls = json.loads(pdf_files)
	except:
		frappe.throw(_("Invalid file data format"))
	
	# Build group map by FP number
	fp_group_map = {}
	for group in batch.groups:
		if group.fp_no:
			fp_group_map[group.fp_no] = group
	
	success_count = 0
	failed_count = 0
	warnings = []
	
	for file_url in file_urls:
		try:
			# Extract FP number from filename
			# Pattern: FP-{16digits}.pdf or Group-{id}.pdf
			filename = file_url.split("/")[-1]
			
			# Try FP number pattern
			fp_match = re.search(r'(\d{16})', filename)
			if fp_match:
				fp_no = fp_match.group(1)
				if fp_no in fp_group_map:
					group = fp_group_map[fp_no]
					group.tax_invoice_pdf = file_url
					success_count += 1
					continue
			
			# Try Group ID pattern
			group_match = re.search(r'Group-(\d+)', filename, re.IGNORECASE)
			if group_match:
				group_id = int(group_match.group(1))
				for group in batch.groups:
					if group.group_id == group_id:
						group.tax_invoice_pdf = file_url
						success_count += 1
						break
				else:
					failed_count += 1
					warnings.append(f"No group found for: {filename}")
			else:
				failed_count += 1
				warnings.append(f"Could not match filename pattern: {filename}")
				
		except Exception as e:
			failed_count += 1
			warnings.append(f"Error processing {file_url}: {str(e)}")
	
	# Save batch
	if success_count > 0:
		batch.save(ignore_permissions=True)
	
	return {
		"status": "success" if failed_count == 0 else "partial",
		"success_count": success_count,
		"failed_count": failed_count,
		"warnings": warnings,
		"message": _("Uploaded {0} of {1} PDFs").format(success_count, len(file_urls))
	}
