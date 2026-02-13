# Copyright (c) 2026, PT. Inovasi Terbaik Bangsa and contributors
# For license information, please see license.txt

from __future__ import annotations

from pathlib import Path

import frappe


def ensure_coretax_export_doctypes() -> None:
	"""Ensure CoreTax export doctypes exist for linked fields."""
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


def ensure_advances_allow_on_submit() -> None:
	"""
	Create Property Setters to allow updating 'advances' child table after submit.
	This is required when Payment Entry references submitted invoices/expense claims.
	"""
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
