# Copyright (c) 2026, PT. Inovasi Terbaik Bangsa and contributors
# For license information, please see license.txt
from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class AdvancePaymentEntry(Document):
    def validate(self):
        # Prevent manual creation; entries should originate from Payment Entry workflow
        if not self.payment_entry and not getattr(self.flags, "allow_manual_creation", False):
            frappe.throw(_("Advance Payment Entry can only be created from a Payment Entry."))

        self._set_defaults()
        self._set_amounts()
        self._validate_allocations()
        self._validate_allocation_rules()
        self._update_status()

    def on_submit(self):
        self._update_status()

    def on_cancel(self):
        self.status = "Cancelled"

    def allocate_reference(
        self,
        invoice_doctype: str,
        invoice_name: str,
        allocated_amount: float,
        reference_currency: str | None = None,
        reference_exchange_rate: float | None = None,
    ) -> None:
        allocated_amount = flt(allocated_amount)
        if allocated_amount <= 0:
            frappe.throw(_("Allocated amount must be greater than zero."))

        if not invoice_doctype or not invoice_name:
            frappe.throw(_("Invoice reference is required to create an allocation."))

        # Get reference document details for tracking
        reference_doc = frappe.get_doc(invoice_doctype, invoice_name)
        reference_posting_date = getattr(reference_doc, "posting_date", None) or frappe.utils.today()
        reference_status = getattr(reference_doc, "status", None) or reference_doc.docstatus

        existing_row = next(
            (
                row
                for row in self.references
                if row.invoice_doctype == invoice_doctype and row.invoice_name == invoice_name
            ),
            None,
        )

        if existing_row:
            existing_row.allocated_amount = flt(existing_row.allocated_amount) + allocated_amount
            if reference_currency:
                existing_row.reference_currency = reference_currency
            if reference_exchange_rate:
                existing_row.reference_exchange_rate = reference_exchange_rate
            # Update tracking info on re-allocation
            existing_row.allocation_date = frappe.utils.today()
            existing_row.allocated_by = frappe.session.user
            existing_row.reference_posting_date = reference_posting_date
            existing_row.reference_status = reference_status
        else:
            self.append(
                "references",
                {
                    "invoice_doctype": invoice_doctype,
                    "invoice_name": invoice_name,
                    "allocated_amount": allocated_amount,
                    "reference_currency": reference_currency or self.currency,
                    "reference_exchange_rate": reference_exchange_rate or self.exchange_rate,
                    # Tracking fields
                    "allocation_date": frappe.utils.today(),
                    "allocated_by": frappe.session.user,
                    "reference_posting_date": reference_posting_date,
                    "reference_status": reference_status,
                },
            )

        self._set_amounts()
        self._validate_allocations()
        self._update_status()

    def clear_reference_allocations(self, invoice_doctype: str, invoice_name: str) -> None:
        self.set(
            "references",
            [
                row
                for row in self.references
                if not (row.invoice_doctype == invoice_doctype and row.invoice_name == invoice_name)
            ],
        )
        self._set_amounts()
        self._update_status()

    def _set_defaults(self) -> None:
        if not self.status:
            self.status = "Draft"

        if not self.exchange_rate:
            self.exchange_rate = 1.0

        if not self.currency:
            self.currency = self._get_default_currency()

        if self.party_type and self.party:
            self.party_name = self._get_party_name()

    def _set_amounts(self) -> None:
        self.base_advance_amount = flt(self.advance_amount) * flt(self.exchange_rate)
        total_allocated = sum(flt(row.allocated_amount) for row in self.references)
        self.allocated_amount = total_allocated
        self.unallocated_amount = flt(self.advance_amount) - total_allocated
        self.base_allocated_amount = flt(total_allocated) * flt(self.exchange_rate)
        self.base_unallocated_amount = flt(self.base_advance_amount) - self.base_allocated_amount

        remaining = max(self.unallocated_amount, 0)
        for row in self.references:
            row.remaining_amount = remaining
            if not row.reference_currency:
                row.reference_currency = self.currency
            if not row.reference_exchange_rate:
                row.reference_exchange_rate = self.exchange_rate

    def _validate_allocations(self) -> None:
        if not self.party_type:
            frappe.throw(_("Party Type is required."))

        if not self.party:
            frappe.throw(_("Party is required for {0}.").format(self.party_type))

        precision = self.precision("advance_amount") or 2
        if flt(self.unallocated_amount, precision) < -0.005:
            frappe.throw(
                _("Total allocated amount ({0}) cannot exceed the advance amount ({1}).").format(
                    frappe.bold(frappe.format_value(self.allocated_amount, {"fieldtype": "Currency", "currency": self.currency})),
                    frappe.bold(frappe.format_value(self.advance_amount, {"fieldtype": "Currency", "currency": self.currency})),
                )
            )

        for row in self.references:
            if flt(row.allocated_amount) <= 0:
                frappe.throw(_("Allocated Amount must be greater than zero in row {0}.").format(row.idx))
            if not row.invoice_doctype or not row.invoice_name:
                frappe.throw(_("Invoice reference is required in row {0}.").format(row.idx))
    
    def _validate_allocation_rules(self) -> None:
        """Validate allocation business rules (draft invoices, cross-company, cancelled docs)."""
        for row in self.references:
            if not row.invoice_doctype or not row.invoice_name:
                continue
            
            # Check if invoice exists
            if not frappe.db.exists(row.invoice_doctype, row.invoice_name):
                frappe.throw(
                    _("Reference {0} {1} in row {2} does not exist.").format(
                        row.invoice_doctype, row.invoice_name, row.idx
                    )
                )
            
            # Validate invoice status (draft warning, cancelled error)
            invoice_docstatus = frappe.db.get_value(row.invoice_doctype, row.invoice_name, "docstatus")
            if invoice_docstatus == 0:
                frappe.msgprint(
                    _("Warning: {0} {1} in row {2} is still in draft. Allocation will be tracked but reconciliation should be done after submission.").format(
                        row.invoice_doctype, row.invoice_name, row.idx
                    ),
                    indicator="orange",
                    alert=True
                )
            elif invoice_docstatus == 2:
                frappe.throw(
                    _("Cannot allocate to cancelled {0} {1} in row {2}.").format(
                        row.invoice_doctype, row.invoice_name, row.idx
                    )
                )
            
            # Validate cross-company allocation
            if self.company:
                invoice_company = frappe.db.get_value(row.invoice_doctype, row.invoice_name, "company")
                if invoice_company and invoice_company != self.company:
                    frappe.throw(
                        _("Cannot allocate advance from {0} to invoice from {1} in row {2}. Cross-company allocation is not allowed.").format(
                            self.company, invoice_company, row.idx
                        )
                    )
                frappe.throw(_("Invoice Reference and Doctype are mandatory in row {0}.").format(row.idx))

    def _update_status(self) -> None:
        if self.docstatus == 2:
            self.status = "Cancelled"
            return

        if self.docstatus == 0:
            self.status = "Draft"
            return

        if flt(self.unallocated_amount) <= 0:
            self.status = "Reconciled"
        elif self.payment_entry:
            self.status = "Paid"
        else:
            self.status = "Submitted"

    def _get_default_currency(self) -> str | None:
        if self.company:
            currency = frappe.db.get_value("Company", self.company, "default_currency")
            if currency:
                return currency
        return frappe.db.get_default("currency")

    def _get_party_name(self) -> str | None:
        fieldname = None
        if self.party_type == "Supplier":
            fieldname = "supplier_name"
        elif self.party_type == "Employee":
            fieldname = "employee_name"
        elif self.party_type == "Customer":
            fieldname = "customer_name"

        if fieldname:
            return frappe.db.get_value(self.party_type, self.party, fieldname) or self.party
        return self.party

    @property
    def available_unallocated(self) -> float:
        precision = self.precision("unallocated_amount") or 2
        return max(flt(self.unallocated_amount, precision), 0)
