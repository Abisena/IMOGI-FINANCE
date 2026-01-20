from __future__ import annotations

import frappe
from frappe import _
from imogi_finance import roles
from frappe.model.document import Document
from frappe.utils import cint, flt, money_in_words, now_datetime, today

from imogi_finance.transfer_application.payment_entries import (
    create_payment_entry_for_transfer_application,
)
from imogi_finance.transfer_application.settings import get_reference_doctype_options


class TransferApplication(Document):
    def validate(self):
        self.apply_defaults()
        self.validate_item_parties()
        self.calculate_totals()
        self.validate_reference_fields()
        self.update_amount_in_words()
        self.sync_payment_details()

    def apply_defaults(self):
        if not self.status:
            self.status = "Draft"
        if not self.posting_date:
            self.posting_date = today()
        if not self.requested_transfer_date:
            self.requested_transfer_date = self.posting_date

        if not self.currency:
            company_currency = None
            if self.company:
                company_currency = frappe.db.get_value("Company", self.company, "default_currency")
            self.currency = company_currency or frappe.db.get_default("currency")

        if not self.workflow_state:
            self.workflow_state = self.status or "Draft"

    def validate_item_parties(self):
        """Validate that each item has required party/beneficiary details"""
        if not self.items:
            frappe.throw(_("Please add at least one item to the Transfer Application."))
        
        for idx, item in enumerate(self.items, start=1):
            if not item.beneficiary_name:
                frappe.throw(_("Row {0}: Beneficiary Name is required").format(idx))
            if not item.bank_name:
                frappe.throw(_("Row {0}: Bank Name is required").format(idx))
            if not item.account_number:
                frappe.throw(_("Row {0}: Account Number is required").format(idx))
            
            # Sync party_type from party if set
            if item.party and not item.party_type:
                party_type = frappe.db.get_value("Party", item.party, "party_type")
                if party_type:
                    item.party_type = party_type

    def calculate_totals(self):
        """Calculate total amount and expected amount from items"""
        total_amount = 0.0
        total_expected = 0.0
        
        for item in self.items or []:
            total_amount += flt(item.amount)
            total_expected += flt(item.expected_amount or item.amount)
        
        self.amount = total_amount
        self.expected_amount = total_expected

    def validate_reference_fields(self):
        if self.reference_name and not self.reference_doctype:
            frappe.throw(_("Please choose a Reference Doctype when Reference Name is set."))
        if self.reference_doctype and not self.reference_name:
            # Allow empty name for Other/manual
            if self.reference_doctype != "Other":
                frappe.throw(_("Please select a Reference Name for the chosen Reference Doctype."))

        allowed = set(get_reference_doctype_options())
        if self.reference_doctype and self.reference_doctype not in allowed:
            frappe.throw(_("Reference Doctype {0} is not available in this site.").format(self.reference_doctype))

    def update_amount_in_words(self):
        if flt(self.amount) and self.currency:
            self.amount_in_words = money_in_words(self.amount, self.currency)
        else:
            self.amount_in_words = None

    def sync_payment_details(self):
        if not self.payment_entry:
            self.paid_date = None
            self.paid_amount = None
            if self.workflow_state and self.status != "Paid":
                self.status = self.workflow_state
            return

        payment_info = frappe.db.get_value(
            "Payment Entry",
            self.payment_entry,
            ["docstatus", "posting_date", "paid_amount"],
            as_dict=True,
        )
        if not payment_info:
            return

        if payment_info.docstatus == 1:
            self.paid_amount = payment_info.paid_amount
            self.paid_date = payment_info.posting_date
            self.status = "Paid"
            self.workflow_state = "Paid"
        elif payment_info.docstatus == 2:
            self.payment_entry = None
            self.paid_amount = None
            self.paid_date = None
            if self.workflow_state == "Paid":
                self.workflow_state = "Awaiting Bank Confirmation"
            self.status = self.workflow_state or self.status

    def on_cancel(self):
        self.status = "Cancelled"
        self.workflow_state = "Cancelled"

    @frappe.whitelist()
    def mark_as_printed(self):
        frappe.only_for((roles.ACCOUNTS_USER, roles.ACCOUNTS_MANAGER, roles.SYSTEM_MANAGER))
        now = now_datetime()
        self.db_set({"printed_by": frappe.session.user, "printed_at": now})
        return {"printed_at": now}

    @frappe.whitelist()
    def create_payment_entry(self, submit: int | str = 0):
        if self.docstatus == 2:
            frappe.throw(_("Cannot create a Payment Entry from a cancelled Transfer Application."))

        submit_flag = bool(cint(submit))
        payment_entry = create_payment_entry_for_transfer_application(
            self, submit=submit_flag
        )
        self.reload()
        return {"payment_entry": payment_entry.name}

    def get_grouped_items(self):
        """Group items by beneficiary for cleaner print format.
        Returns a list of dicts with beneficiary info and their items."""
        from collections import OrderedDict
        
        grouped = OrderedDict()
        
        for item in self.items or []:
            # Create unique key for each beneficiary
            key = (
                item.beneficiary_name or "",
                item.bank_name or "",
                item.account_number or "",
                item.account_holder_name or "",
                item.bank_branch or ""
            )
            
            if key not in grouped:
                grouped[key] = {
                    "beneficiary_name": item.beneficiary_name,
                    "bank_name": item.bank_name,
                    "bank_branch": item.bank_branch,
                    "account_number": item.account_number,
                    "account_holder_name": item.account_holder_name,
                    "party_type": item.party_type,
                    "party": item.party,
                    "items": [],
                    "total_amount": 0.0,
                    "total_expected": 0.0
                }
            
            grouped[key]["items"].append(item)
            grouped[key]["total_amount"] += flt(item.amount)
            grouped[key]["total_expected"] += flt(item.expected_amount or item.amount)
        
        return list(grouped.values())


@frappe.whitelist()
def fetch_reference_doctype_options():
    return get_reference_doctype_options()
