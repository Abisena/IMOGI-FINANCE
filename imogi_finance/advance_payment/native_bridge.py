"""
Native Bridge Module
Bridges Advance Payment Entry (custom tracking) with ERPNext Native advances system.

Architecture:
- APE = Tracking & Dashboard layer (non-invasive)
- ERPNext advances table = Actual accounting (native GL logic)
- This module = Bridge between them (sync only)

Principles:
1. Native First: ERPNext handles all accounting
2. Scalable: APE can be removed without breaking accounting
3. Modular: Each component independent
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, today


def sync_allocation_to_native_advances(
    payment_entry: str,
    invoice_doctype: str,
    invoice_name: str,
    allocated_amount: float,
    reference_exchange_rate: float = 1.0
) -> dict:
    """
    Sync APE allocation to ERPNext native advances table.
    
    This bridges our custom tracking with ERPNext standard accounting.
    
    Args:
        payment_entry: Payment Entry name (source of advance)
        invoice_doctype: Purchase Invoice, Sales Invoice, etc.
        invoice_name: Invoice document name
        allocated_amount: Amount to allocate
        reference_exchange_rate: Exchange rate for multi-currency
    
    Returns:
        dict: {success: bool, message: str, advance_row: dict}
    """
    # Validate inputs
    if not frappe.db.exists("Payment Entry", payment_entry):
        return {"success": False, "message": f"Payment Entry {payment_entry} not found"}
    
    if not frappe.db.exists(invoice_doctype, invoice_name):
        return {"success": False, "message": f"{invoice_doctype} {invoice_name} not found"}
    
    # Get invoice
    invoice = frappe.get_doc(invoice_doctype, invoice_name)
    
    # Check if advance already exists in invoice
    existing_advance = None
    for adv in (invoice.advances or []):
        if adv.reference_type == "Payment Entry" and adv.reference_name == payment_entry:
            existing_advance = adv
            break
    
    if existing_advance:
        # Update existing advance
        old_amount = flt(existing_advance.allocated_amount)
        existing_advance.allocated_amount = flt(allocated_amount)
        existing_advance.advance_amount = flt(allocated_amount)
        
        frappe.logger().info(
            f"Updated advance in {invoice_doctype} {invoice_name}: "
            f"{old_amount} → {allocated_amount}"
        )
    else:
        # Add new advance to invoice
        invoice.append("advances", {
            "reference_type": "Payment Entry",
            "reference_name": payment_entry,
            "advance_amount": flt(allocated_amount),
            "allocated_amount": flt(allocated_amount),
            "ref_exchange_rate": flt(reference_exchange_rate),
            "remarks": f"Auto-allocated from Advance Payment Entry on {today()}"
        })
        
        frappe.logger().info(
            f"Added advance to {invoice_doctype} {invoice_name}: "
            f"PE {payment_entry} = {allocated_amount}"
        )
    
    # Save invoice (allow update after submit)
    invoice.flags.ignore_validate_update_after_submit = True
    invoice.flags.ignore_permissions = True
    
    try:
        invoice.save()
        
        return {
            "success": True,
            "message": f"Successfully synced {allocated_amount} to {invoice_doctype} advances",
            "advance_row": existing_advance or invoice.advances[-1]
        }
    
    except Exception as e:
        frappe.logger().error(f"Failed to sync advance to native: {str(e)}")
        return {
            "success": False,
            "message": f"Failed to sync: {str(e)}"
        }


def remove_allocation_from_native_advances(
    payment_entry: str,
    invoice_doctype: str,
    invoice_name: str
) -> dict:
    """
    Remove allocation from ERPNext native advances table.
    
    Called when APE allocation is cleared (e.g., invoice cancelled).
    
    Args:
        payment_entry: Payment Entry name
        invoice_doctype: Purchase Invoice, Sales Invoice, etc.
        invoice_name: Invoice document name
    
    Returns:
        dict: {success: bool, message: str}
    """
    if not frappe.db.exists(invoice_doctype, invoice_name):
        # Invoice deleted/doesn't exist - OK, nothing to remove
        return {"success": True, "message": "Invoice not found (already removed)"}
    
    # Get invoice
    invoice = frappe.get_doc(invoice_doctype, invoice_name)
    
    # Find and remove matching advance
    original_count = len(invoice.advances or [])
    invoice.advances = [
        adv for adv in (invoice.advances or [])
        if not (adv.reference_type == "Payment Entry" and adv.reference_name == payment_entry)
    ]
    
    removed_count = original_count - len(invoice.advances)
    
    if removed_count > 0:
        # Save invoice
        invoice.flags.ignore_validate_update_after_submit = True
        invoice.flags.ignore_permissions = True
        
        try:
            invoice.save()
            
            frappe.logger().info(
                f"Removed {removed_count} advance(s) from {invoice_doctype} {invoice_name}"
            )
            
            return {
                "success": True,
                "message": f"Removed {removed_count} advance allocation(s)"
            }
        
        except Exception as e:
            frappe.logger().error(f"Failed to remove advance from native: {str(e)}")
            return {
                "success": False,
                "message": f"Failed to remove: {str(e)}"
            }
    
    return {
        "success": True,
        "message": "No matching advance found (already removed)"
    }


def sync_all_allocations_for_ape(advance_payment_entry_name: str) -> dict:
    """
    Sync all allocations from one APE to native advances tables.
    
    Useful for bulk sync or re-sync operations.
    
    Args:
        advance_payment_entry_name: APE document name
    
    Returns:
        dict: {success: bool, synced_count: int, failed: list}
    """
    from imogi_finance.imogi_finance.doctype.advance_payment_entry.advance_payment_entry import (
        AdvancePaymentEntry,
    )
    
    ape: AdvancePaymentEntry = frappe.get_doc("Advance Payment Entry", advance_payment_entry_name)
    
    synced_count = 0
    failed = []
    
    for ref in (ape.references or []):
        if not ref.invoice_doctype or not ref.invoice_name:
            continue
        
        result = sync_allocation_to_native_advances(
            payment_entry=ape.payment_entry,
            invoice_doctype=ref.invoice_doctype,
            invoice_name=ref.invoice_name,
            allocated_amount=flt(ref.allocated_amount),
            reference_exchange_rate=flt(ref.reference_exchange_rate or 1.0)
        )
        
        if result.get("success"):
            synced_count += 1
        else:
            failed.append({
                "invoice": f"{ref.invoice_doctype} {ref.invoice_name}",
                "error": result.get("message")
            })
    
    return {
        "success": len(failed) == 0,
        "synced_count": synced_count,
        "failed": failed,
        "total": len(ape.references or [])
    }


@frappe.whitelist()
def verify_native_sync(advance_payment_entry_name: str) -> dict:
    """
    Verify that APE allocations are in sync with native advances.
    
    Returns comparison report for debugging/validation.
    
    Args:
        advance_payment_entry_name: APE document name
    
    Returns:
        dict: Comparison report
    """
    from imogi_finance.imogi_finance.doctype.advance_payment_entry.advance_payment_entry import (
        AdvancePaymentEntry,
    )
    
    ape: AdvancePaymentEntry = frappe.get_doc("Advance Payment Entry", advance_payment_entry_name)
    
    comparison = []
    
    for ref in (ape.references or []):
        if not ref.invoice_doctype or not ref.invoice_name:
            continue
        
        # Check native advances table
        invoice = frappe.get_doc(ref.invoice_doctype, ref.invoice_name)
        
        native_advance = None
        for adv in (invoice.advances or []):
            if adv.reference_type == "Payment Entry" and adv.reference_name == ape.payment_entry:
                native_advance = adv
                break
        
        ape_amount = flt(ref.allocated_amount)
        native_amount = flt(native_advance.allocated_amount) if native_advance else 0.0
        
        in_sync = abs(ape_amount - native_amount) < 0.01
        
        comparison.append({
            "invoice": f"{ref.invoice_doctype} {ref.invoice_name}",
            "ape_amount": ape_amount,
            "native_amount": native_amount,
            "in_sync": in_sync,
            "difference": ape_amount - native_amount,
            "status": "✅ Synced" if in_sync else "⚠️ Out of Sync"
        })
    
    return {
        "ape": advance_payment_entry_name,
        "payment_entry": ape.payment_entry,
        "total_references": len(ape.references or []),
        "in_sync_count": sum(1 for c in comparison if c["in_sync"]),
        "out_of_sync_count": sum(1 for c in comparison if not c["in_sync"]),
        "comparison": comparison
    }
