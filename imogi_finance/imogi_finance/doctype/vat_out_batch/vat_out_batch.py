# Copyright (c) 2026, PT. Inovasi Terbaik Bangsa and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now, nowdate, getdate


class VATOUTBatch(Document):
	def validate(self):
		"""Validate batch data."""
		if self.flags.get("ignore_validate"):
			return
		
		# Validate date range
		if getdate(self.date_from) > getdate(self.date_to):
			frappe.throw(_("Date From cannot be greater than Date To"))
		
		# Update computed status
		self._update_status()
	
	def on_submit(self):
		"""Lock and finalize batch data."""
		# Prevent submit without FP numbers
		invoices = self.get_batch_invoices()
		if not invoices:
			frappe.throw(_("Cannot submit empty batch. Please add invoices first."))
		
		missing_fp = [inv.name for inv in invoices if not inv.out_fp_no]
		if missing_fp:
			frappe.throw(
				_("Cannot submit batch. {0} invoices missing FP numbers: {1}").format(
					len(missing_fp), ", ".join(missing_fp[:5])
				)
			)
		
		# Update submission metadata
		self.db_set("submit_on", now(), update_modified=False)
		self._update_status()
	
	def on_cancel(self):
		"""Unlink all Sales Invoices from this batch but preserve FP numbers."""
		invoices = self.get_batch_invoices()
		
		for inv in invoices:
			frappe.db.set_value(
				"Sales Invoice",
				inv.name,
				{
					"out_fp_batch": None,
					"out_fp_group_id": None
				},
				update_modified=False
			)
		
		self._update_status()
		frappe.msgprint(
			_("All {0} invoices unlinked from batch. FP numbers preserved.").format(len(invoices))
		)
	
	def _update_status(self):
		"""Update batch status based on state."""
		if self.docstatus == 0:
			if self.exported_on:
				self.status = "Exported"
			else:
				self.status = "Draft"
		elif self.docstatus == 1:
			self.status = "Submitted"
		elif self.docstatus == 2:
			self.status = "Cancelled"
	
	@frappe.whitelist()
	def get_available_invoices(self):
		"""Get Sales Invoices available for this batch and auto-group them."""
		# Query Sales Invoices
		invoices = frappe.db.get_all(
			"Sales Invoice",
			filters={
				"docstatus": 1,
				"company": self.company,
				"posting_date": ["between", [self.date_from, self.date_to]],
				"out_fp_status": "Verified",
				"out_fp_batch": ["is", "not set"]
			},
			fields=[
				"name",
				"posting_date",
				"customer",
				"customer_name",
				"grand_total",
				"out_fp_no_faktur",
				"out_fp_ppn",
				"out_fp_dpp",
				"out_fp_combine",
				"out_fp_customer_npwp"
			],
			order_by="posting_date, customer"
		)
		
		if not invoices:
			frappe.msgprint(_("No available invoices found for selected date range."))
			return []
		
		# Auto-group by customer and out_fp_combine flag
		groups = self._auto_group_invoices(invoices)
		
		# Assign group IDs and link to batch
		self._assign_and_link_groups(groups)
		
		return {
			"total_invoices": len(invoices),
			"total_groups": len(groups),
			"groups": groups
		}
	
	def _auto_group_invoices(self, invoices):
		"""
		Auto-group invoices based on out_fp_combine flag and customer.
		
		Logic:
		- out_fp_combine = 1: Group with other combine=1 invoices from same customer
		- out_fp_combine = 0: Each invoice gets its own group (no combining)
		"""
		groups = []
		combine_groups = {}  # {customer: [invoices]}
		
		for inv in invoices:
			if inv.out_fp_combine:
				# Combine with other invoices from same customer
				key = f"{inv.customer}|{inv.out_fp_customer_npwp or ''}"
				if key not in combine_groups:
					combine_groups[key] = []
				combine_groups[key].append(inv)
			else:
				# Single invoice group
				groups.append({
					"customer": inv.customer,
					"customer_name": inv.customer_name,
					"customer_npwp": inv.out_fp_customer_npwp,
					"invoice_count": 1,
					"total_dpp": inv.out_fp_dpp or 0,
					"total_ppn": inv.out_fp_ppn or 0,
					"invoices": [inv]
				})
		
		# Process combine groups
		for key, inv_list in combine_groups.items():
			customer = inv_list[0].customer
			customer_name = inv_list[0].customer_name
			customer_npwp = inv_list[0].out_fp_customer_npwp
			
			groups.append({
				"customer": customer,
				"customer_name": customer_name,
				"customer_npwp": customer_npwp,
				"invoice_count": len(inv_list),
				"total_dpp": sum(inv.out_fp_dpp or 0 for inv in inv_list),
				"total_ppn": sum(inv.out_fp_ppn or 0 for inv in inv_list),
				"invoices": inv_list
			})
		
		return groups
	
	def _assign_and_link_groups(self, groups):
		"""Assign sequential group IDs and link Sales Invoices to this batch."""
		for idx, group in enumerate(groups, start=1):
			group_id = idx
			
			# Update all invoices in group
			for inv in group["invoices"]:
				frappe.db.set_value(
					"Sales Invoice",
					inv.name,
					{
						"out_fp_batch": self.name,
						"out_fp_group_id": group_id
					},
					update_modified=False
				)
			
			# Store group_id in return data
			group["group_id"] = group_id
	
	def get_batch_invoices(self):
		"""Get all Sales Invoices linked to this batch."""
		return frappe.db.get_all(
			"Sales Invoice",
			filters={"out_fp_batch": self.name, "docstatus": 1},
			fields=[
				"name",
				"posting_date",
				"customer",
				"customer_name",
				"grand_total",
				"out_fp_no",
				"out_fp_no_seri",
				"out_fp_no_faktur",
				"out_fp_date",
				"out_fp_dpp",
				"out_fp_ppn",
				"out_fp_group_id",
				"out_fp_customer_npwp",
				"out_fp_combine"
			],
			order_by="out_fp_group_id, posting_date"
		)
	
	def get_groups_summary(self):
		"""Get summary of groups in this batch."""
		invoices = self.get_batch_invoices()
		
		groups_map = {}
		for inv in invoices:
			gid = inv.out_fp_group_id or 0
			if gid not in groups_map:
				groups_map[gid] = {
					"group_id": gid,
					"customer": inv.customer,
					"customer_name": inv.customer_name,
					"customer_npwp": inv.out_fp_customer_npwp,
					"invoice_count": 0,
					"total_dpp": 0,
					"total_ppn": 0,
					"fp_number": inv.out_fp_no or ""
				}
			
			groups_map[gid]["invoice_count"] += 1
			groups_map[gid]["total_dpp"] += inv.out_fp_dpp or 0
			groups_map[gid]["total_ppn"] += inv.out_fp_ppn or 0
		
		return list(groups_map.values())
