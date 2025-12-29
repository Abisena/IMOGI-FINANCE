"""Accounting helpers for IMOGI Finance."""

from __future__ import annotations

import frappe
from frappe import _

PURCHASE_INVOICE_REQUEST_TYPES = {"Expense"}
JOURNAL_ENTRY_REQUEST_TYPES: set[str] = {"Asset"}


def _get_pph_base_amount(request: frappe.model.document.Document) -> float:
    if request.is_pph_applicable and request.pph_base_amount:
        return request.pph_base_amount
    return request.amount


def _validate_request_ready_for_link(request: frappe.model.document.Document) -> None:
    if request.docstatus != 1 or request.status != "Approved":
        frappe.throw(
            _("Expense Request must be submitted and Approved before creating accounting entries.")
        )


def _validate_request_type(
    request: frappe.model.document.Document, allowed_types: set[str], action: str
) -> None:
    if request.request_type not in allowed_types:
        frappe.throw(
            _("{0} can only be created for request type(s): {1}").format(
                action, ", ".join(sorted(allowed_types))
            )
        )


@frappe.whitelist()
def create_purchase_invoice_from_request(expense_request_name: str) -> str:
    """Create a Purchase Invoice from an Expense Request and return its name."""
    request = frappe.get_doc("Expense Request", expense_request_name)
    _validate_request_ready_for_link(request)
    _validate_request_type(request, PURCHASE_INVOICE_REQUEST_TYPES, _("Purchase Invoice"))
    if request.linked_purchase_invoice:
        frappe.throw(
            _("Expense Request is already linked to Purchase Invoice {0}.").format(
                request.linked_purchase_invoice
            )
        )

    company = frappe.db.get_value("Cost Center", request.cost_center, "company")
    if not company:
        frappe.throw(_("Unable to resolve company from the selected Cost Center."))

    pi = frappe.new_doc("Purchase Invoice")
    pi.company = company
    pi.supplier = request.supplier
    pi.posting_date = request.request_date
    pi.bill_date = request.supplier_invoice_date
    pi.bill_no = request.supplier_invoice_no
    pi.currency = request.currency
    pi.imogi_expense_request = request.name
    pi.imogi_request_type = request.request_type
    pi.tax_withholding_category = request.pph_type if request.is_pph_applicable else None
    pi.imogi_pph_type = request.pph_type
    pi.apply_tds = 1 if request.is_pph_applicable else 0
    pi.withholding_tax_base_amount = _get_pph_base_amount(request) if request.is_pph_applicable else None

    pi.append(
        "items",
        {
            "item_name": request.asset_name or request.description or request.expense_account,
            "description": request.description,
            "expense_account": request.expense_account,
            "cost_center": request.cost_center,
            "project": request.project,
            "qty": 1,
            "rate": request.amount,
            "amount": request.amount,
        },
    )

    if request.is_ppn_applicable and request.ppn_template:
        pi.taxes_and_charges = request.ppn_template
        pi.set_taxes()

    pi.insert(ignore_permissions=True)

    request.db_set({"linked_purchase_invoice": pi.name, "status": "Linked"})
    return pi.name


@frappe.whitelist()
def create_journal_entry_from_request(expense_request_name: str) -> str:
    """Create a Journal Entry from an Expense Request and return its name."""
    request = frappe.get_doc("Expense Request", expense_request_name)
    _validate_request_ready_for_link(request)
    _validate_request_type(request, JOURNAL_ENTRY_REQUEST_TYPES, _("Journal Entry"))

    if request.linked_journal_entry:
        frappe.throw(
            _("Expense Request is already linked to Journal Entry {0}.").format(
                request.linked_journal_entry
            )
        )

    if request.is_pph_applicable and not request.pph_type:
        frappe.throw(_("Please set PPh Type before creating a Journal Entry."))

    company = frappe.db.get_value("Cost Center", request.cost_center, "company")
    if not company:
        frappe.throw(_("Unable to resolve company from the selected Cost Center."))

    payable_account = frappe.get_cached_value(
        "Supplier", request.supplier, "default_payable_account"
    ) or frappe.get_cached_value("Company", company, "default_payable_account")
    if not payable_account:
        frappe.throw(_("Please set a Default Payable Account for the Supplier or Company."))

    withholding_amount = 0.0
    withholding_account = None
    if request.is_pph_applicable and request.pph_type:
        twc_info = frappe.get_cached_value(
            "Tax Withholding Category",
            request.pph_type,
            ["account", "rate"],
            as_dict=True,
        )
        withholding_account = twc_info.account if twc_info else None
        withholding_rate = twc_info.rate if twc_info else 0
        withholding_amount = _get_pph_base_amount(request) * (withholding_rate or 0) / 100

    payable_amount = request.amount - withholding_amount
    if payable_amount < 0:
        frappe.throw(_("Withholding amount cannot exceed the request amount."))

    je = frappe.new_doc("Journal Entry")
    je.company = company
    je.posting_date = request.request_date
    je.user_remark = request.description
    je.imogi_expense_request = request.name
    je.imogi_request_type = request.request_type

    je.append(
        "accounts",
        {
            "account": request.expense_account,
            "debit_in_account_currency": request.amount,
            "cost_center": request.cost_center,
            "project": request.project,
        },
    )

    if withholding_amount and withholding_account:
        je.append(
            "accounts",
            {
                "account": withholding_account,
                "credit_in_account_currency": withholding_amount,
                "cost_center": request.cost_center,
            },
        )

    je.append(
        "accounts",
        {
            "account": payable_account,
            "party_type": "Supplier",
            "party": request.supplier,
            "credit_in_account_currency": payable_amount,
            "cost_center": request.cost_center,
        },
    )

    je.insert(ignore_permissions=True)

    request.db_set({"linked_journal_entry": je.name, "status": "Linked"})
    return je.name
