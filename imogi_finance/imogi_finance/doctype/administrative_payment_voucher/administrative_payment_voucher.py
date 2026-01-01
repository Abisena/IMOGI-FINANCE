from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from imogi_finance.branching import apply_branch, doc_supports_branch, resolve_branch
from imogi_finance.tax_operations import validate_tax_period_lock


@dataclass
class AccountDetails:
    name: str
    account_type: Optional[str]
    root_type: Optional[str]
    is_group: int
    company: Optional[str]


def get_account_details(account: str) -> AccountDetails:
    account_type, root_type, is_group, company = frappe.db.get_value(
        "Account", account, ["account_type", "root_type", "is_group", "company"]
    )
    return AccountDetails(
        name=account,
        account_type=account_type,
        root_type=root_type,
        is_group=is_group or 0,
        company=company,
    )


def validate_bank_cash(details: AccountDetails, company: str) -> None:
    if details.is_group:
        frappe.throw(_("Bank/Cash account {0} cannot be a group.").format(details.name))

    if details.company and details.company != company:
        frappe.throw(
            _("Bank/Cash account {0} must belong to company {1}.").format(details.name, company)
        )

    bank_like = (details.account_type or "").lower() in {"bank", "cash"}
    asset_like = (details.root_type or "").lower() in {"asset"}
    if not bank_like and not asset_like:
        frappe.throw(
            _("Bank/Cash account {0} must have Account Type Bank/Cash or an Asset root type.").format(
                details.name
            )
        )


def validate_target_account(details: AccountDetails, company: str) -> None:
    if details.is_group:
        frappe.throw(_("Target account {0} cannot be a group.").format(details.name))

    if (details.account_type or "").lower() in {"bank", "cash"}:
        frappe.throw(_("Target GL Account cannot be a Bank or Cash account."))

    if details.company and details.company != company:
        frappe.throw(
            _("Target account {0} must belong to company {1}.").format(details.name, company)
        )


def party_required(details: AccountDetails) -> bool:
    return (details.account_type or "").lower() in {"receivable", "payable"}


def validate_party(details: AccountDetails, party_type: Optional[str], party: Optional[str]) -> None:
    if not party_required(details):
        return

    if not party_type or not party:
        frappe.throw(_("Party Type and Party are required when the target account is Receivable/Payable."))


def map_payment_entry_accounts(direction: str, amount: float, bank_account: str, target_account: str) -> frappe._dict:
    direction_normalized = (direction or "").strip().lower()
    if direction_normalized not in {"receive", "pay"}:
        frappe.throw(_("Direction must be Receive or Pay."))

    if amount <= 0:
        frappe.throw(_("Amount must be greater than zero."))

    if direction_normalized == "receive":
        return frappe._dict(
            payment_type="Receive",
            paid_from=target_account,
            paid_to=bank_account,
            paid_amount=amount,
            received_amount=amount,
        )

    return frappe._dict(
        payment_type="Pay",
        paid_from=bank_account,
        paid_to=target_account,
        paid_amount=amount,
        received_amount=amount,
    )


def apply_optional_dimension(doc: Document, fieldname: str, value: Optional[str]) -> None:
    if not value or not frappe.db.has_column(doc.doctype, fieldname):
        return

    setattr(doc, fieldname, value)


class AdministrativePaymentVoucher(Document):
    def validate(self):
        self._ensure_status_defaults()
        self._apply_branch_defaults()
        validate_tax_period_lock(self)
        self._validate_amount()
        self._validate_accounts()
        self._validate_party_rules()
        self._validate_reference_fields()
        self._validate_attachments()

    def before_submit(self):
        if self.status not in {"Approved", "Posted"}:
            self.status = "Approved"
            self.approved_by = self.approved_by or frappe.session.user
            self.approved_on = now_datetime()

    def on_submit(self):
        payment_entry = self.create_payment_entry()
        if payment_entry:
            self.payment_entry = payment_entry.name
            self.db_set("payment_entry", payment_entry.name)

        self.posted_by = frappe.session.user
        self.posted_on = now_datetime()
        self.status = "Posted"
        self.db_set(
            {
                "status": self.status,
                "posted_by": self.posted_by,
                "posted_on": self.posted_on,
            }
        )

    def on_cancel(self):
        if self.payment_entry and frappe.db.exists("Payment Entry", self.payment_entry):
            payment_entry = frappe.get_doc("Payment Entry", self.payment_entry)
            if payment_entry.docstatus == 1:
                payment_entry.cancel()
            elif payment_entry.docstatus == 0:
                payment_entry.delete()

        self.status = "Cancelled"
        self.db_set("status", "Cancelled")

    @frappe.whitelist()
    def create_payment_entry_from_client(self):
        if self.docstatus != 1:
            frappe.throw(_("Please submit the Administrative Payment Voucher before posting a Payment Entry."))

        payment_entry = self.create_payment_entry()
        return {"payment_entry": getattr(payment_entry, "name", None)}

    def create_payment_entry(self):
        if self.payment_entry:
            existing_status = frappe.db.get_value("Payment Entry", self.payment_entry, "docstatus")
            if existing_status is not None and existing_status != 2:
                frappe.msgprint(
                    _("Payment Entry {0} already exists for this voucher.").format(self.payment_entry)
                )
                return frappe.get_doc("Payment Entry", self.payment_entry)

        bank_details = self._get_account(self.bank_cash_account)
        target_details = self._get_account(self.target_gl_account)
        account_map = map_payment_entry_accounts(
            self.direction, self.amount, bank_details.name, target_details.name
        )

        payment_entry = frappe.new_doc("Payment Entry")
        payment_entry.payment_type = account_map.payment_type
        payment_entry.company = self.company
        payment_entry.posting_date = self.posting_date
        payment_entry.paid_from = account_map.paid_from
        payment_entry.paid_to = account_map.paid_to
        payment_entry.paid_amount = account_map.paid_amount
        payment_entry.received_amount = account_map.received_amount
        payment_entry.mode_of_payment = self.mode_of_payment
        payment_entry.reference_no = self.name
        payment_entry.reference_date = self.posting_date
        payment_entry.remarks = self._build_remarks()

        if party_required(target_details):
            payment_entry.party_type = self.party_type
            payment_entry.party = self.party
            if hasattr(payment_entry, "party_account"):
                payment_entry.party_account = target_details.name

        apply_optional_dimension(payment_entry, "cost_center", self.cost_center)

        branch = getattr(self, "branch", None)
        if doc_supports_branch(payment_entry.doctype):
            apply_branch(payment_entry, branch)
        elif branch and frappe.db.has_column(payment_entry.doctype, "branch"):
            apply_optional_dimension(payment_entry, "branch", branch)

        if self.reference_doctype and self.reference_name:
            payment_entry.append(
                "references",
                {
                    "reference_doctype": self.reference_doctype,
                    "reference_name": self.reference_name,
                    "allocated_amount": self.amount,
                    "cost_center": self.cost_center,
                },
            )

        if hasattr(payment_entry, "imogi_administrative_payment_voucher"):
            payment_entry.imogi_administrative_payment_voucher = self.name

        if hasattr(payment_entry, "set_missing_values"):
            payment_entry.set_missing_values()

        payment_entry.insert(ignore_permissions=True)
        payment_entry.submit()
        return payment_entry

    def _build_remarks(self) -> str:
        parts = [(_("Administrative Payment Voucher {0}").format(self.name))]
        if self.justification:
            parts.append(self.justification)
        if self.reference_doctype and self.reference_name:
            parts.append(_("Reference: {0} {1}").format(self.reference_doctype, self.reference_name))
        return " | ".join(parts)

    def _validate_amount(self):
        if not self.amount or self.amount <= 0:
            frappe.throw(_("Amount must be greater than zero."))

    def _validate_accounts(self):
        bank_details = self._get_account(self.bank_cash_account)
        target_details = self._get_account(self.target_gl_account)

        validate_bank_cash(bank_details, self.company)
        validate_target_account(target_details, self.company)

    def _validate_party_rules(self):
        target_details = self._get_account(self.target_gl_account)
        validate_party(target_details, self.party_type, self.party)

    def _validate_reference_fields(self):
        if self.reference_name and not self.reference_doctype:
            frappe.throw(_("Please choose a Reference Doctype when Reference Name is set."))
        if self.reference_doctype and not self.reference_name:
            frappe.throw(_("Please choose a Reference Name when Reference Doctype is set."))

    def _validate_attachments(self):
        if not getattr(self, "require_attachment", 0):
            return

        attachments = self.get("_attachments") or []
        if not attachments and self.name:
            attachments = frappe.get_all(
                "File",
                filters={"attached_to_doctype": self.doctype, "attached_to_name": self.name},
                limit=1,
            )
        if attachments:
            return
        frappe.throw(_("An attachment is required for this Administrative Payment Voucher."))

    def _ensure_status_defaults(self):
        if self.docstatus == 0 and not self.status:
            self.status = "Draft"
        if self.docstatus == 2:
            self.status = "Cancelled"

    def _apply_branch_defaults(self):
        branch = resolve_branch(
            company=getattr(self, "company", None),
            cost_center=getattr(self, "cost_center", None),
            explicit_branch=getattr(self, "branch", None),
        )
        if branch:
            apply_branch(self, branch)

    def _get_account(self, account: str) -> AccountDetails:
        if not account:
            frappe.throw(_("Please set an account."))

        if not hasattr(self, "_account_cache"):
            self._account_cache = {}

        if account not in self._account_cache:
            self._account_cache[account] = get_account_details(account)

        return self._account_cache[account]
