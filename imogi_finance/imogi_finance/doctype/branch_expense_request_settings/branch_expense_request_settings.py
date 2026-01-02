from __future__ import annotations

import frappe
from frappe.model.document import Document


DEFAULT_SETTINGS = {
	"enable_branch_expense_request": 1,
	"default_expense_account": None,
	"require_employee": 0,
	"enable_budget_check": 1,
	"budget_block_on_over": 1,
	"budget_warn_on_over": 0,
	"budget_check_basis": "Fiscal Year",
}


class BranchExpenseRequestSettings(Document):
	pass


def get_settings():
	try:
		return frappe.get_cached_doc("Branch Expense Request Settings")
	except Exception:
		try:
			return frappe.get_single("Branch Expense Request Settings")
		except Exception:
			return frappe._dict(DEFAULT_SETTINGS)
