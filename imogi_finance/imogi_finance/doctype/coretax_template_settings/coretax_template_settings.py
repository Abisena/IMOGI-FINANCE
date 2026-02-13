# Copyright (c) 2026, PT. Inovasi Terbaik Bangsa and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now


class CoreTaxTemplateSettings(Document):
	def validate(self):
		"""Validate template settings."""
		if not self.template_file:
			frappe.throw(_("Template File is required"))
		
		if not self.active_template_version:
			frappe.throw(_("Active Template Version is required"))
	
	def before_save(self):
		"""Update metadata."""
		self.last_updated_by = frappe.session.user
		self.last_updated_on = now()
	
	@staticmethod
	def get_active_template():
		"""Get the active template file path.
		
		Returns:
			dict: Template data with version and file path
		"""
		if not frappe.db.exists("CoreTax Template Settings", "CoreTax Template Settings"):
			frappe.throw(_("CoreTax Template Settings not configured. Please configure in Settings."))
		
		settings = frappe.get_doc("CoreTax Template Settings", "CoreTax Template Settings")
		
		if not settings.template_file:
			frappe.throw(_("No active template file configured"))
		
		return {
			"version": settings.active_template_version,
			"file": settings.template_file,
			"notes": settings.version_notes
		}


@frappe.whitelist()
def upload_new_template(file_url: str, notes: str = None):
	"""Upload a new template version.
	
	Args:
		file_url: URL of uploaded Excel file
		notes: Optional version notes
	
	Returns:
		dict: New version info
	"""
	settings = frappe.get_single("CoreTax Template Settings")
	
	# Add current template to history
	if settings.template_file and settings.active_template_version:
		settings.append("template_history", {
			"version": settings.active_template_version,
			"template_file": settings.template_file,
			"updated_by": settings.last_updated_by,
			"updated_on": settings.last_updated_on,
			"notes": settings.version_notes
		})
	
	# Increment version
	current_version = settings.active_template_version or "1.0"
	try:
		major, minor = current_version.split(".")
		new_version = f"{major}.{int(minor) + 1}"
	except:
		new_version = "1.0"
	
	# Update active template
	settings.active_template_version = new_version
	settings.template_file = file_url
	settings.version_notes = notes or f"Template updated to version {new_version}"
	
	settings.save()
	
	return {
		"status": "success",
		"version": new_version,
		"message": _("Template updated successfully")
	}
