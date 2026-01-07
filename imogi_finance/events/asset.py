import frappe
from frappe import _

from imogi_finance.events.utils import (
    get_approved_expense_request,
    get_cancel_updates,
)


def on_submit(doc, method=None):
    request = doc.get("imogi_expense_request")
    if not request:
        return

    request = get_approved_expense_request(request, _("Asset"))

    if request.linked_asset:
        frappe.throw(_("Expense Request is already linked to an Asset."))

    if request.request_type != "Asset":
        frappe.throw(_("Expense Request must have request type Asset to link Asset."))

    frappe.db.set_value(
        "Expense Request",
        request.name,
        {"linked_asset": doc.name, "status": "PI Created"},
    )


def on_cancel(doc, method=None):
    request = doc.get("imogi_expense_request")
    if not request:
        return

    updates = get_cancel_updates(request, "linked_asset")

    frappe.db.set_value("Expense Request", request, updates)
