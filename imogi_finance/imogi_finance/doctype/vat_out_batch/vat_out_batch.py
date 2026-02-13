# Copyright (c) 2026, PT. Inovasi Terbaik Bangsa and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now, nowdate


class VATOUTBatch(Document):
	def validate(self):
		"""Validate batch data and auto-assign group IDs."""
		if self.flags.get("ignore_validate"):
			return
		
		# Auto-assign group_id sequentially per batch
		self._assign_group_ids()
		
		# Validate grouping rules
		self._validate_grouping()
		
		# Calculate group totals
		self._calculate_group_totals()
		
		# Validate Sales Invoices not in other batches
		self._validate_invoice_exclusivity()
		
		# Update computed status
		self._update_status()
	
	def _assign_group_ids(self):
		"""Auto-assign sequential group IDs per batch (1, 2, 3...)."""
		if not self.get("groups"):
			return
		
		# Get existing group_ids
		existing_ids = [g.group_id for g in self.groups if g.group_id]
		next_id = max(existing_ids) + 1 if existing_ids else 1
		
		# Assign to groups without ID
		for group in self.groups:
			if not group.group_id:
				group.group_id = next_id
				next_id += 1
	
	def _validate_grouping(self):
		"""Validate that all invoices in a group have same customer and NPWP."""
		if not self.get("invoices"):
			return
		
		# Prevent grouping changes after export
		if self.exported_on and not self.flags.get("ignore_export_lock"):
			frappe.throw(
				_("Cannot modify groups after export. Exported on {0}").format(
					frappe.format(self.exported_on, {"fieldtype": "Datetime"})
				)
			)
		
		# Group invoices by group_id
		groups_map = {}
		for group in self.get("groups", []):
			groups_map[group.group_id] = {
				"customer": group.customer,
				"customer_npwp": group.customer_npwp
			}
		
		# Validate invoice consistency per group
		for invoice in self.get("invoices", []):
			if not invoice.group_id:
				continue
			
			group_data = groups_map.get(invoice.group_id)
			if not group_data:
				continue
			
			# Get Sales Invoice customer
			si_customer = frappe.db.get_value(
				"Sales Invoice",
				invoice.sales_invoice,
				"customer"
			)
			
			if si_customer != group_data["customer"]:
				frappe.throw(
					_("Sales Invoice {0} customer does not match Group {1} customer").format(
						invoice.sales_invoice,
						invoice.group_id
					)
				)
	
	def _calculate_group_totals(self):
		"""Calculate total DPP and PPN for each group."""
		if not self.get("invoices"):
			return
		
		# Sum by group_id
		totals = {}
		for invoice in self.get("invoices", []):
			if not invoice.group_id:
				continue
			
			if invoice.group_id not in totals:
				totals[invoice.group_id] = {"dpp": 0, "ppn": 0}
			
			totals[invoice.group_id]["dpp"] += invoice.dpp or 0
			totals[invoice.group_id]["ppn"] += invoice.ppn or 0
		
		# Update group rows
		for group in self.get("groups", []):
			if group.group_id in totals:
				group.total_dpp = totals[group.group_id]["dpp"]
				group.total_ppn = totals[group.group_id]["ppn"]
	
	def _validate_invoice_exclusivity(self):
		"""Ensure Sales Invoices are not in other active batches."""
		if not self.get("invoices"):
			return
		
		invoice_list = [inv.sales_invoice for inv in self.get("invoices", [])]
		if not invoice_list:
			return
		
		# Check for invoices in other batches
		other_batches = frappe.db.sql(
			"""
			SELECT DISTINCT vbi.sales_invoice, vob.name
			FROM `tabVAT OUT Batch Invoice` vbi
			INNER JOIN `tabVAT OUT Batch` vob ON vob.name = vbi.parent
			WHERE vbi.sales_invoice IN %(invoices)s
				AND vob.name != %(current_batch)s
				AND vob.docstatus != 2
			""",
			{"invoices": invoice_list, "current_batch": self.name},
			as_dict=True
		)
		
		if other_batches:
			duplicates = ", ".join([
				f"{row.sales_invoice} (in {row.name})"
				for row in other_batches
			])
			frappe.throw(
				_("Sales Invoices already in other batches: {0}").format(duplicates)
			)
	
	def _update_status(self):
		"""Update computed status field."""
		if self.docstatus == 0:
			if self.exported_on:
				if self._all_groups_have_fp():
					self.status = "Ready to Submit"
				else:
					self.status = "Importing"
			else:
				self.status = "Draft" if not self.coretax_export_file else "Exported"
		elif self.docstatus == 1:
			self.status = "Submitted"
	
	def _all_groups_have_fp(self):
		"""Check if all groups have FP number and date."""
		if not self.get("groups"):
			return False
		
		for group in self.groups:
			if not group.fp_no or not group.fp_date:
				return False
		
		return True
	
	def before_submit(self):
		"""Validate before submission."""
		# Validate all groups have FP number and date
		if not self._all_groups_have_fp():
			frappe.throw(_("All groups must have FP Number and FP Date before submission"))
		
		# Validate upload status is completed
		if self.coretax_upload_status != "Completed":
			frappe.throw(
				_("CoreTax Upload Status must be 'Completed' before submission. Current status: {0}").format(
					self.coretax_upload_status
				)
			)
		
		# Validate no duplicate FP numbers globally
		self._validate_fp_numbers_unique()
		
		# Validate tax period lock
		self._validate_tax_period_lock()
	
	def _validate_fp_numbers_unique(self):
		"""Validate FP numbers are globally unique."""
		for group in self.get("groups", []):
			if not group.fp_no:
				continue
			
			# Check in other batches
			existing = frappe.db.sql(
				"""
				SELECT vobg.parent
				FROM `tabVAT OUT Batch Group` vobg
				INNER JOIN `tabVAT OUT Batch` vob ON vob.name = vobg.parent
				WHERE vobg.fp_no = %(fp_no)s
					AND vob.name != %(current_batch)s
					AND vob.docstatus != 2
				LIMIT 1
				""",
				{"fp_no": group.fp_no, "current_batch": self.name},
				as_dict=True
			)
			
			if existing:
				frappe.throw(
					_("FP Number {0} already exists in batch {1}").format(
						group.fp_no,
						existing[0].parent
					)
				)
			
			# Check in Sales Invoices
			existing_si = frappe.db.get_value(
				"Sales Invoice",
				{
					"out_fp_no": group.fp_no,
					"out_fp_batch": ["!=", self.name],
					"docstatus": ["!=", 2]
				},
				"name"
			)
			
			if existing_si:
				frappe.throw(
					_("FP Number {0} already exists in Sales Invoice {1}").format(
						group.fp_no,
						existing_si
					)
				)
	
	def _validate_tax_period_lock(self):
		"""Validate batch period is not locked."""
		# Check if tax period closing exists for this period
		from imogi_finance.imogi_finance.doctype.tax_period_closing.tax_period_closing import (
			is_period_locked
		)
		
		# Get latest FP date from groups
		fp_dates = [g.fp_date for g in self.get("groups", []) if g.fp_date]
		if not fp_dates:
			# Use date_to if no FP dates yet
			check_date = self.date_to
		else:
			check_date = max(fp_dates)
		
		# Check if period is locked
		if is_period_locked(self.company, check_date):
			frappe.throw(
				_("Tax period for {0} is locked. Please unlock via Tax Period Closing or use a valid period.").format(
					frappe.format(check_date, {"fieldtype": "Date"})
				)
			)
	
	def on_submit(self):
		"""Update Sales Invoices with batch and FP data."""
		self._update_sales_invoices()
		self._add_submit_metadata()
	
	def _update_sales_invoices(self):
		"""Update all Sales Invoices with batch link and FP data."""
		# Build mapping of group_id to FP data
		group_fp_map = {}
		for group in self.get("groups", []):
			group_fp_map[group.group_id] = {
				"fp_no": group.fp_no,
				"fp_date": group.fp_date
			}
		
		# Update each Sales Invoice
		for invoice in self.get("invoices", []):
			if invoice.group_id not in group_fp_map:
				continue
			
			fp_data = group_fp_map[invoice.group_id]
			
			frappe.db.set_value(
				"Sales Invoice",
				invoice.sales_invoice,
				{
					"out_fp_batch": self.name,
					"out_fp_group_id": invoice.group_id,
					"out_fp_no": fp_data["fp_no"],
					"out_fp_date": fp_data["fp_date"]
				},
				update_modified=True
			)
			
			# Add comment
			frappe.get_doc("Sales Invoice", invoice.sales_invoice).add_comment(
				"Info",
				_("Submitted in VAT OUT Batch {0} Group {1}").format(
					self.name,
					invoice.group_id
				)
			)
	
	def _add_submit_metadata(self):
		"""Add submission metadata."""
		self.db_set("submit_on", now(), update_modified=False)
	
	def on_cancel(self):
		"""Unlink Sales Invoices but retain FP data for audit."""
		self._unlink_sales_invoices()
	
	def _unlink_sales_invoices(self):
		"""Unlink batch from Sales Invoices, keep FP data for audit."""
		for invoice in self.get("invoices", []):
			frappe.db.set_value(
				"Sales Invoice",
				invoice.sales_invoice,
				{
					"out_fp_batch": None,
					"out_fp_group_id": None
				},
				update_modified=True
			)
			
			# Add comment
			frappe.get_doc("Sales Invoice", invoice.sales_invoice).add_comment(
				"Info",
				_("Batch {0} cancelled. FP data retained for audit trail.").format(self.name)
			)


@frappe.whitelist()
def mark_upload_status(batch_name: str, status: str, notes: str = None):
	"""Update CoreTax upload status.
	
	Args:
		batch_name: VAT OUT Batch name
		status: New status (In Progress, Completed, Failed)
		notes: Optional notes
	"""
	batch = frappe.get_doc("VAT OUT Batch", batch_name)
	batch.check_permission("write")
	
	if status not in ["In Progress", "Completed", "Failed"]:
		frappe.throw(_("Invalid status"))
	
	batch.coretax_upload_status = status
	if notes:
		batch.upload_notes = notes
	if status == "Completed":
		batch.uploaded_on = now()
	
	batch.save(ignore_permissions=True)
	
	return {"status": "success", "batch": batch.name}


@frappe.whitelist()
def clone_batch(source_batch_name: str):
	"""Clone a cancelled batch for resubmission.
	
	Args:
		source_batch_name: Name of cancelled batch to clone
	
	Returns:
		dict: New batch name and status
	"""
	source = frappe.get_doc("VAT OUT Batch", source_batch_name)
	source.check_permission("read")
	
	if source.docstatus != 2:
		frappe.throw(_("Can only clone cancelled batches"))
	
	# Create new batch
	new_batch = frappe.new_doc("VAT OUT Batch")
	new_batch.company = source.company
	new_batch.date_from = source.date_from
	new_batch.date_to = source.date_to
	
	# Copy groups (without FP data)
	for group in source.groups:
		new_batch.append("groups", {
			"group_id": group.group_id,
			"customer": group.customer,
			"customer_npwp": group.customer_npwp
		})
	
	# Copy invoices
	for invoice in source.invoices:
		new_batch.append("invoices", {
			"group_id": invoice.group_id,
			"sales_invoice": invoice.sales_invoice,
			"dpp": invoice.dpp,
			"ppn": invoice.ppn,
			"remarks": invoice.remarks
		})
	
	new_batch.save()
	
	# Add comment
	new_batch.add_comment(
		"Info",
		_("Cloned from cancelled batch {0}").format(source_batch_name)
	)
	
	return {
		"status": "success",
		"new_batch": new_batch.name,
		"message": _("Batch cloned successfully")
	}
