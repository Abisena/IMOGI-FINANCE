import frappe
from frappe import _

from imogi_finance.events.utils import (
    get_approved_expense_request,
    get_cancel_updates,
)


def on_submit(doc, method=None):
    """Link Asset to Expense Request when submitted."""
    request = doc.get("imogi_expense_request")
    if not request:
        return

    request_doc = frappe.get_doc("Expense Request", request)
    
    # Validate
    if request_doc.docstatus != 1:
        frappe.throw(_("Expense Request must be submitted."))
    
    if request_doc.request_type != "Asset":
        frappe.throw(_("Expense Request must have request type Asset to link Asset."))

    # Add to asset_links child table
    request_doc.append("asset_links", {
        "asset": doc.name,
        "asset_name": doc.asset_name,
        "asset_category": doc.asset_category,
        "asset_location": doc.location,
        "status": doc.status
    })
    
    # Also update legacy linked_asset field for backward compatibility (first asset only)
    if not request_doc.linked_asset:
        request_doc.linked_asset = doc.name
        request_doc.status = "PI Created"
    
    request_doc.flags.ignore_validate_update_after_submit = True
    request_doc.save(ignore_permissions=True)


def on_cancel(doc, method=None):
    """Remove Asset link from Expense Request when cancelled."""
    request = doc.get("imogi_expense_request")
    if not request:
        return

    # Remove from asset_links child table
    request_doc = frappe.get_doc("Expense Request", request)
    
    # Find and remove this asset from the child table
    asset_links_to_remove = []
    for idx, asset_link in enumerate(request_doc.asset_links):
        if asset_link.asset == doc.name:
            asset_links_to_remove.append(idx)
    
    # Remove in reverse order to avoid index issues
    for idx in reversed(asset_links_to_remove):
        request_doc.remove(request_doc.asset_links[idx])
    
    # Update legacy linked_asset field if it matches
    if request_doc.linked_asset == doc.name:
        # Set to next asset if available, otherwise null
        if request_doc.asset_links:
            request_doc.linked_asset = request_doc.asset_links[0].asset
        else:
            request_doc.linked_asset = None
            # Reset status only if no more assets linked
            request_doc.status = "Approved"
    
    request_doc.flags.ignore_validate_update_after_submit = True
    request_doc.save(ignore_permissions=True)
