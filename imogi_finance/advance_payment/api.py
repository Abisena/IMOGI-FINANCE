from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from imogi_finance.imogi_finance.doctype.advance_payment_entry.advance_payment_entry import (
    AdvancePaymentEntry,
)

SUPPORTED_REFERENCE_DOCTYPES = {
    "Purchase Invoice",
    "Expense Claim",
    "Payroll Entry",
    "Purchase Order",  # Advance payment untuk PO
    "Sales Invoice",  # Refund/advance dari customer
    "Journal Entry",  # Manual settlement
    "Expense Request",  # Internal expense request
    "Branch Expense Request",  # Branch expense
}


@frappe.whitelist()
def get_available_advances(party_type: str, party: str, company: str | None = None, currency: str | None = None):
    validate_party_inputs(party_type, party)
    filters = {
        "party_type": party_type,
        "party": party,
        "docstatus": 1,
    }
    if company:
        filters["company"] = company
    if currency:
        filters["currency"] = currency

    entries = frappe.get_all(
        "Advance Payment Entry",
        filters=filters,
        fields=[
            "name",
            "posting_date",
            "company",
            "party_type",
            "party",
            "currency",
            "advance_amount",
            "allocated_amount",
            "unallocated_amount",
            "status",
        ],
        order_by="posting_date desc, name desc",
    )

    for entry in entries:
        entry.unallocated_amount = flt(entry.unallocated_amount or (entry.advance_amount or 0) - (entry.allocated_amount or 0))
    return [entry for entry in entries if flt(entry.unallocated_amount) > 0]


@frappe.whitelist()
def get_allocations_for_reference(reference_doctype: str, reference_name: str):
    if not reference_doctype or not reference_name:
        frappe.throw(_("Reference DocType and name are required."))

    rows = frappe.get_all(
        "Advance Payment Reference",
        filters={"invoice_doctype": reference_doctype, "invoice_name": reference_name},
        fields=[
            "parent",
            "invoice_doctype",
            "invoice_name",
            "allocated_amount",
            "remaining_amount",
            "reference_currency",
        ],
        order_by="modified desc",
    )

    parent_map = {}
    for row in rows:
        if row.parent in parent_map:
            continue
        parent_map[row.parent] = frappe.db.get_value(
            "Advance Payment Entry",
            row.parent,
            ["currency", "unallocated_amount", "party_type", "party"],
            as_dict=True,
        )

    for row in rows:
        parent_info = parent_map.get(row.parent) or {}
        row.update(
            {
                "advance_currency": parent_info.get("currency"),
                "advance_unallocated": parent_info.get("unallocated_amount"),
                "party_type": parent_info.get("party_type"),
                "party": parent_info.get("party"),
            }
        )

    return rows


@frappe.whitelist()
def allocate_advances(
    reference_doctype: str,
    reference_name: str,
    allocations: list | str,
    party_type: str | None = None,
    party: str | None = None,
):
    if reference_doctype not in SUPPORTED_REFERENCE_DOCTYPES:
        frappe.throw(_("Advance reconciliation is not enabled for {0}.").format(reference_doctype))

    if not allocations:
        frappe.throw(_("Please choose at least one Advance Payment Entry."))

    allocations = frappe.parse_json(allocations)
    if not isinstance(allocations, (list, tuple)) or not allocations:
        frappe.throw(_("Please choose at least one Advance Payment Entry."))

    reference_doc = frappe.get_doc(reference_doctype, reference_name)
    reference_currency = get_reference_currency(reference_doc)
    resolved_party_type, resolved_party = resolve_reference_party(reference_doc, party_type, party)
    validate_party_inputs(resolved_party_type, resolved_party)
    validate_reference_allocation_capacity(reference_doc, allocations, reference_currency)

    applied_allocations = []
    for allocation in allocations:
        advance_name = allocation.get("advance_payment_entry") or allocation.get("name")
        amount = flt(allocation.get("allocated_amount"))
        if not advance_name or amount <= 0:
            continue

        advance_doc: AdvancePaymentEntry = frappe.get_doc("Advance Payment Entry", advance_name)
        validate_advance_for_party(advance_doc, resolved_party_type, resolved_party)
        validate_allocation_currency(reference_currency, advance_doc)
        validate_allocation_amount(amount, advance_doc)

        if advance_doc.docstatus != 1:
            frappe.throw(_("Advance Payment Entry {0} must be submitted before it can be allocated.").format(advance_doc.name))

        advance_doc.flags.ignore_validate_update_after_submit = True
        advance_doc.allocate_reference(
            reference_doctype,
            reference_name,
            amount,
            reference_currency=reference_currency,
            reference_exchange_rate=allocation.get("reference_exchange_rate")
            or getattr(reference_doc, "conversion_rate", None)
            or advance_doc.exchange_rate,
        )
        advance_doc.save(ignore_permissions=True)

        applied_allocations.append(
            {
                "advance_payment_entry": advance_doc.name,
                "allocated_amount": amount,
                "unallocated_amount": advance_doc.available_unallocated,
            }
        )

    if not applied_allocations:
        frappe.throw(_("Please enter at least one allocation amount."))

    return {"allocations": applied_allocations}


def resolve_reference_party(document, party_type: str | None, party: str | None) -> tuple[str | None, str | None]:
    if party_type and party:
        return party_type, party

    mapping = {
        "Purchase Invoice": ("Supplier", "supplier"),
        "Purchase Order": ("Supplier", "supplier"),
        "Expense Claim": ("Employee", "employee"),
        "Payroll Entry": ("Employee", "employee"),
        "Expense Request": ("Employee", "employee"),
        "Branch Expense Request": ("Employee", "employee"),
        "Sales Invoice": ("Customer", "customer"),
        "Journal Entry": (None, None),  # Manual, ambil dari parameter
    }
    if document.doctype in mapping:
        resolved_type, fieldname = mapping[document.doctype]
        if fieldname:
            return resolved_type, getattr(document, fieldname, None)
        return resolved_type, party  # Untuk Journal Entry

    return party_type, party


def validate_party_inputs(party_type: str | None, party: str | None) -> None:
    if not party_type:
        frappe.throw(_("Party Type is required for advance allocation."))
    if not party:
        frappe.throw(_("Party is required for advance allocation."))


def validate_advance_for_party(advance: AdvancePaymentEntry, party_type: str, party: str) -> None:
    if advance.party_type != party_type:
        frappe.throw(
            _("Advance Payment Entry {0} is for {1}, not {2}.").format(
                advance.name, advance.party_type or "-", party_type
            )
        )
    if advance.party != party:
        frappe.throw(
            _("Advance Payment Entry {0} is assigned to {1}, not {2}.").format(
                advance.name,
                advance.party or _("Unknown"),
                party,
            )
        )


def validate_allocation_currency(reference_currency: str | None, advance: AdvancePaymentEntry) -> None:
    if reference_currency and advance.currency and reference_currency != advance.currency:
        frappe.throw(
            _("Advance Payment Entry {0} currency is {1}, which does not match the document currency {2}.").format(
                advance.name,
                frappe.bold(advance.currency),
                frappe.bold(reference_currency),
            )
        )


def validate_allocation_amount(amount: float, advance: AdvancePaymentEntry) -> None:
    precision = advance.precision("unallocated_amount") or 2
    if flt(amount, precision) - flt(advance.available_unallocated, precision) > 0.005:
        frappe.throw(
            _("Allocated amount of {0} exceeds unallocated balance {1} for Advance Payment Entry {2}.").format(
                frappe.format_value(amount, {"fieldtype": "Currency", "currency": advance.currency}),
                frappe.format_value(advance.available_unallocated, {"fieldtype": "Currency", "currency": advance.currency}),
                advance.name,
            )
        )


def release_allocations(reference_doctype: str, reference_name: str) -> None:
    links = frappe.get_all(
        "Advance Payment Reference",
        filters={"invoice_doctype": reference_doctype, "invoice_name": reference_name},
        fields=["parent"],
    )
    if not links:
        return

    for link in links:
        advance_doc: AdvancePaymentEntry = frappe.get_doc("Advance Payment Entry", link.parent)
        advance_doc.flags.ignore_validate_update_after_submit = True
        advance_doc.clear_reference_allocations(reference_doctype, reference_name)
        advance_doc.save(ignore_permissions=True)


def refresh_linked_advances(reference_doctype: str, reference_name: str) -> None:
    links = frappe.get_all(
        "Advance Payment Reference",
        filters={"invoice_doctype": reference_doctype, "invoice_name": reference_name},
        fields=["parent"],
    )
    for link in links:
        advance_doc: AdvancePaymentEntry = frappe.get_doc("Advance Payment Entry", link.parent)
        advance_doc.flags.ignore_validate_update_after_submit = True
        advance_doc._set_amounts()
        advance_doc._validate_allocations()
        advance_doc._update_status()
        advance_doc.save(ignore_permissions=True)


def on_reference_before_cancel(doc, method=None):
    """Auto-unlink payment reconciliation BEFORE document cancellation.
    
    This prevents cancellation from being blocked due to linked payments.
    Must run BEFORE cancel to avoid "Cannot cancel - linked to payments" errors.
    """
    frappe.logger().info(f"Auto-unlinking payments before cancel {doc.doctype} {doc.name}")
    auto_unlink_reconciled_payments(doc)


def on_reference_cancel(doc, method=None):
    """Release all advance allocations when reference document is cancelled.
    
    This ensures that when a PI/Invoice is cancelled, the advance becomes available again.
    Payments should already be unlinked by before_cancel hook.
    """
    frappe.logger().info(f"Releasing allocations for cancelled {doc.doctype} {doc.name}")
    release_allocations(doc.doctype, doc.name)


def on_reference_update(doc, method=None):
    """Refresh linked advance entries when reference document is updated.
    
    This keeps APE in sync with changes to the reference document.
    """
    refresh_linked_advances(doc.doctype, doc.name)


def validate_reference_allocation_capacity(document, allocations: list[dict], reference_currency: str | None = None) -> None:
    outstanding = get_reference_outstanding_amount(document)
    if outstanding is None:
        return

    existing_allocated = get_existing_allocated_amount(document.doctype, document.name)
    total = sum(flt(item.get("allocated_amount")) for item in allocations)
    precision = getattr(document, "precision", lambda *_: 2)("grand_total") or 2
    remaining_capacity = flt(outstanding, precision) - flt(existing_allocated, precision)
    if flt(total, precision) - max(remaining_capacity, 0) > 0.005:
        frappe.throw(
            _("{0} allocations of {1} exceed remaining outstanding {2} after {3} already allocated.").format(
                document.doctype,
                frappe.format_value(total, {"fieldtype": "Currency", "currency": reference_currency or getattr(document, "currency", None)}),
                frappe.format_value(remaining_capacity, {"fieldtype": "Currency", "currency": reference_currency or getattr(document, "currency", None)}),
                frappe.format_value(existing_allocated, {"fieldtype": "Currency", "currency": reference_currency or getattr(document, "currency", None)}),
            )
        )


def get_reference_outstanding_amount(document) -> float | None:
    if hasattr(document, "outstanding_amount"):
        return flt(getattr(document, "outstanding_amount") or 0)

    if document.doctype == "Expense Claim":
        total = flt(getattr(document, "grand_total", None) or getattr(document, "total_sanctioned_amount", None) or 0)
        reimbursed = flt(getattr(document, "total_amount_reimbursed", None) or 0)
        advances = flt(getattr(document, "total_advance_amount", None) or getattr(document, "total_advance", None) or 0)
        return total - reimbursed - advances

    if document.doctype == "Payroll Entry":
        return flt(getattr(document, "total_deduction", None) or getattr(document, "total_payment", None) or 0)

    return None


def get_existing_allocated_amount(reference_doctype: str, reference_name: str) -> float:
        total = frappe.db.sql(
            """
            SELECT COALESCE(SUM(apr.allocated_amount), 0)
            FROM `tabAdvance Payment Reference` apr
            JOIN `tabAdvance Payment Entry` ape ON apr.parent = ape.name
            WHERE apr.invoice_doctype = %s AND apr.invoice_name = %s AND ape.docstatus = 1
            """,
            (reference_doctype, reference_name),
        )
        return flt(total[0][0]) if total else 0.0


@frappe.whitelist()
def get_allocation_history(advance_payment_entry: str) -> list[dict]:
    """
    Get full allocation history with tracking details for an Advance Payment Entry.
    
    Returns list of allocations with:
    - Reference document details
    - Allocation tracking (date, user)
    - Reference document status
    - Timeline of allocations
    """
    if not frappe.db.exists("Advance Payment Entry", advance_payment_entry):
        frappe.throw(_("Advance Payment Entry {0} not found.").format(advance_payment_entry))
    
    history = frappe.db.sql(
        """
        SELECT 
            apr.name,
            apr.invoice_doctype,
            apr.invoice_name,
            apr.allocated_amount,
            apr.remaining_amount,
            apr.reference_currency,
            apr.reference_exchange_rate,
            apr.allocation_date,
            apr.allocated_by,
            apr.reference_posting_date,
            apr.reference_status,
            apr.remarks,
            apr.creation,
            apr.modified
        FROM `tabAdvance Payment Reference` apr
        WHERE apr.parent = %s
        ORDER BY apr.allocation_date DESC, apr.creation DESC
        """,
        (advance_payment_entry,),
        as_dict=True
    )
    
    # Enrich with user details
    for record in history:
        if record.allocated_by:
            user = frappe.get_cached_value("User", record.allocated_by, ["full_name", "email"], as_dict=True)
            record["allocated_by_name"] = user.get("full_name") if user else record.allocated_by
    
    return history


@frappe.whitelist()
def get_reference_allocations(reference_doctype: str, reference_name: str) -> list[dict]:
    """
    Get all advance allocations for a specific reference document.
    
    Useful untuk melihat dari mana saja advance yang dialokasikan ke dokumen tertentu.
    """
    if not frappe.db.exists(reference_doctype, reference_name):
        frappe.throw(_("{0} {1} not found.").format(reference_doctype, reference_name))
    
    allocations = frappe.db.sql(
        """
        SELECT 
            ape.name as advance_payment_entry,
            ape.posting_date as advance_posting_date,
            ape.party_type,
            ape.party,
            ape.party_name,
            ape.currency,
            ape.advance_amount,
            ape.status as advance_status,
            apr.allocated_amount,
            apr.allocation_date,
            apr.allocated_by,
            apr.remarks
        FROM `tabAdvance Payment Reference` apr
        JOIN `tabAdvance Payment Entry` ape ON apr.parent = ape.name
        WHERE apr.invoice_doctype = %s 
            AND apr.invoice_name = %s 
            AND ape.docstatus = 1
        ORDER BY apr.allocation_date DESC
        """,
        (reference_doctype, reference_name),
        as_dict=True
    )
    
    # Enrich with user details
    for record in allocations:
        if record.allocated_by:
            user = frappe.get_cached_value("User", record.allocated_by, ["full_name"], as_dict=True)
            record["allocated_by_name"] = user.get("full_name") if user else record.allocated_by
    
    return allocations


def get_reference_currency(document) -> str | None:
    return getattr(document, "currency", None) or getattr(document, "company_currency", None)


@frappe.whitelist()
def get_payment_reconciliation_data(
    party_type: str,
    party: str,
    payment_entry: str | None = None,
    invoice_names: list | str | None = None,
):
    """Get data needed to pre-fill Payment Reconciliation tool.
    
    This helps user quickly reconcile advances with allocated invoices.
    """
    if isinstance(invoice_names, str):
        invoice_names = frappe.parse_json(invoice_names)
    
    # Get default receivable/payable account for the party
    account = None
    if party_type == "Supplier":
        account = frappe.get_cached_value("Company", frappe.defaults.get_user_default("Company"), "default_payable_account")
    elif party_type == "Customer":
        account = frappe.get_cached_value("Company", frappe.defaults.get_user_default("Company"), "default_receivable_account")
    
    return {
        "party_type": party_type,
        "party": party,
        "account": account,
        "payment_entry": payment_entry,
        "invoice_names": invoice_names or [],
    }


@frappe.whitelist()
def check_allocation_coverage(references: list | str):
    """Check if allocated invoices are fully covered by advances.
    
    Returns list of invoices with partial allocations and over-allocations.
    """
    if isinstance(references, str):
        references = frappe.parse_json(references)
    
    partial_allocations = []
    over_allocations = []
    
    for ref in references:
        invoice_doctype = ref.get("invoice_doctype")
        invoice_name = ref.get("invoice_name")
        allocated_amount = flt(ref.get("allocated_amount"))
        
        if not invoice_doctype or not invoice_name:
            continue
        
        # Get total allocated from all advance payment entries
        total_allocated = get_existing_allocated_amount(invoice_doctype, invoice_name)
        
        # Get invoice outstanding/total
        try:
            invoice = frappe.get_doc(invoice_doctype, invoice_name)
            invoice_total = get_reference_outstanding_amount(invoice)
            
            if invoice_total is None:
                invoice_total = flt(getattr(invoice, "grand_total", 0))
            
            # Check for over-allocation (e.g., after credit note)
            if total_allocated > invoice_total + 0.01:
                over_allocations.append({
                    "invoice_doctype": invoice_doctype,
                    "invoice_name": invoice_name,
                    "allocated": total_allocated,
                    "total": invoice_total,
                    "excess": total_allocated - invoice_total,
                })
            # Check for partial allocation
            elif invoice_total > 0 and total_allocated < invoice_total - 0.01:
                partial_allocations.append({
                    "invoice_doctype": invoice_doctype,
                    "invoice_name": invoice_name,
                    "allocated": total_allocated,
                    "total": invoice_total,
                    "remaining": invoice_total - total_allocated,
                })
        except Exception:
            # Skip if invoice not found or error
            continue
    
    return {
        "partial_allocations": partial_allocations,
        "over_allocations": over_allocations,
        "has_partial": len(partial_allocations) > 0,
        "has_over": len(over_allocations) > 0,
    }


@frappe.whitelist()
def fix_over_allocation(invoice_doctype: str, invoice_name: str):
    """Fix over-allocation by proportionally reducing allocations.
    
    This can happen when credit note is issued after advance allocation.
    """
    # Get invoice current total
    invoice = frappe.get_doc(invoice_doctype, invoice_name)
    invoice_total = get_reference_outstanding_amount(invoice)
    
    if invoice_total is None:
        invoice_total = flt(getattr(invoice, "grand_total", 0))
    
    # Get all allocations for this invoice
    allocations = frappe.db.sql(
        """
        SELECT apr.parent, apr.allocated_amount, apr.name as ref_name
        FROM `tabAdvance Payment Reference` apr
        JOIN `tabAdvance Payment Entry` ape ON apr.parent = ape.name
        WHERE apr.invoice_doctype = %s 
        AND apr.invoice_name = %s 
        AND ape.docstatus = 1
        ORDER BY apr.creation
        """,
        (invoice_doctype, invoice_name),
        as_dict=True,
    )
    
    if not allocations:
        return {"success": False, "message": "No allocations found"}
    
    total_allocated = sum(flt(a.allocated_amount) for a in allocations)
    
    if total_allocated <= invoice_total + 0.01:
        return {"success": False, "message": "No over-allocation detected"}
    
    # Calculate proportional reduction
    reduction_ratio = invoice_total / total_allocated
    
    adjusted_count = 0
    for alloc in allocations:
        ape = frappe.get_doc("Advance Payment Entry", alloc.parent)
        ape.flags.ignore_validate_update_after_submit = True
        
        for row in ape.references:
            if row.invoice_doctype == invoice_doctype and row.invoice_name == invoice_name:
                old_amount = flt(row.allocated_amount)
                new_amount = flt(old_amount * reduction_ratio, 2)
                row.allocated_amount = new_amount
                adjusted_count += 1
                
                frappe.logger().info(
                    f"Adjusted allocation in {ape.name}: {old_amount} → {new_amount}"
                )
        
        ape._set_amounts()
        ape._validate_allocations()
        ape._update_status()
        ape.save(ignore_permissions=True)
    
    return {
        "success": True,
        "message": f"Adjusted {adjusted_count} allocations proportionally",
        "old_total": total_allocated,
        "new_total": invoice_total,
        "reduction_ratio": reduction_ratio,
    }


def auto_unlink_reconciled_payments(doc):
    """Automatically unlink all payment reconciliation entries before document cancellation.
    
    This prevents "Cannot cancel - linked to payments" errors.
    Runs in before_cancel hook to ensure smooth cancellation process.
    """
    # Get all linked Payment Ledger Entries
    reconciled_entries = frappe.db.sql(
        """
        SELECT DISTINCT
            ple.voucher_type,
            ple.voucher_no
        FROM `tabPayment Ledger Entry` ple
        WHERE ple.against_voucher_type = %s
        AND ple.against_voucher_no = %s
        AND ple.delinked = 0
        """,
        (doc.doctype, doc.name),
        as_dict=True
    )
    
    if not reconciled_entries:
        frappe.logger().info(f"No reconciled payments found for {doc.doctype} {doc.name}")
        return
    
    success_count = 0
    failed_payments = []
    
    for entry in reconciled_entries:
        result = unlink_single_payment(
            entry.voucher_type,
            entry.voucher_no,
            doc.doctype,
            doc.name
        )
        
        if result.get("success"):
            success_count += 1
            frappe.logger().info(
                f"Auto-unlinked {entry.voucher_type} {entry.voucher_no} from {doc.doctype} {doc.name}"
            )
        else:
            failed_payments.append(f"{entry.voucher_no}: {result.get('error', 'Unknown error')}")
            frappe.logger().error(
                f"Failed to auto-unlink {entry.voucher_type} {entry.voucher_no}: {result.get('error')}"
            )
    
    # Show summary message
    if success_count > 0:
        frappe.msgprint(
            _(
                "<b>Payment Reconciliation Auto-Unlinked:</b><br>"
                "Successfully unlinked {0} payment(s) before cancellation.<br>"
                "Advance allocations will be cleared after cancel completes."
            ).format(success_count),
            indicator="blue",
            alert=True,
            title=_("Auto-Unlink Successful")
        )
    
    # If some failed, show warning but allow cancellation to proceed
    # (Payment Entry might already be cancelled, which is OK)
    if failed_payments:
        frappe.msgprint(
            _(
                "<b>Note:</b> Some payments could not be auto-unlinked:<br>{0}<br>"
                "This is usually OK if those payments are already cancelled. "
                "Cancellation will proceed."
            ).format("<br>".join(failed_payments)),
            indicator="orange",
            alert=True
        )


@frappe.whitelist()
def get_reconciled_payments_for_cancelled_doc(doctype: str, docname: str):
    """Get list of reconciled payments for a cancelled document.
    
    Used to show user which payments need to be unlinked.
    """
    if not frappe.db.exists(doctype, docname):
        frappe.throw(_("{0} {1} not found.").format(doctype, docname))
    
    reconciled = frappe.db.sql(
        """
        SELECT 
            ple.voucher_type,
            ple.voucher_no,
            ple.account,
            ple.amount,
            ple.account_currency as currency,
            ple.posting_date,
            ple.creation
        FROM `tabPayment Ledger Entry` ple
        WHERE ple.against_voucher_type = %s
        AND ple.against_voucher_no = %s
        AND ple.delinked = 0
        ORDER BY ple.posting_date DESC, ple.creation DESC
        """,
        (doctype, docname),
        as_dict=True
    )
    
    return reconciled


@frappe.whitelist()
def unlink_single_payment(voucher_type: str, voucher_no: str, reference_doctype: str, reference_name: str):
    """Attempt to unlink a single payment from a cancelled reference document.
    
    This uses ERPNext's standard unlink mechanism.
    """
    try:
        # Import ERPNext's unlink function
        from erpnext.accounts.doctype.payment_entry.payment_entry import unlink_ref_doc_from_payment_entries
        
        # Attempt to unlink
        unlink_ref_doc_from_payment_entries(voucher_type, voucher_no, reference_doctype, reference_name)
        
        frappe.logger().info(
            f"Successfully unlinked {voucher_type} {voucher_no} from {reference_doctype} {reference_name}"
        )
        
        return {
            "success": True,
            "message": f"Unlinked {voucher_no} successfully"
        }
    
    except ImportError:
        # ERPNext function not available, try manual method
        return unlink_payment_manual(voucher_type, voucher_no, reference_doctype, reference_name)
    
    except Exception as e:
        frappe.logger().error(
            f"Failed to unlink {voucher_type} {voucher_no} from {reference_doctype} {reference_name}: {str(e)}"
        )
        return {
            "success": False,
            "error": str(e)
        }


def unlink_payment_manual(voucher_type: str, voucher_no: str, reference_doctype: str, reference_name: str):
    """Manual unlinking by removing reference from Payment Entry.
    
    Fallback method if ERPNext standard function not available.
    """
    try:
        if voucher_type != "Payment Entry":
            return {
                "success": False,
                "error": f"Manual unlink only supports Payment Entry, not {voucher_type}"
            }
        
        pe = frappe.get_doc(voucher_type, voucher_no)
        
        # Remove reference from references table
        original_count = len(pe.references or [])
        pe.references = [
            ref for ref in (pe.references or [])
            if not (ref.reference_doctype == reference_doctype and ref.reference_name == reference_name)
        ]
        
        if len(pe.references) == original_count:
            return {
                "success": False,
                "error": "Reference not found in Payment Entry"
            }
        
        # Recalculate amounts
        pe.flags.ignore_validate_update_after_submit = True
        pe.set_amounts()
        pe.save(ignore_permissions=True)
        
        frappe.logger().info(
            f"Manually unlinked {voucher_type} {voucher_no} from {reference_doctype} {reference_name}"
        )
        
        return {
            "success": True,
            "message": f"Manually unlinked {voucher_no} successfully"
        }
    
    except Exception as e:
        frappe.logger().error(f"Manual unlink failed: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

