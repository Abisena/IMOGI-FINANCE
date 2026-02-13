from __future__ import annotations

from typing import Dict, List, Tuple

import frappe
from frappe import _


def execute(filters: Dict | None = None) -> Tuple[List[Dict], List[Dict]]:
    filters = filters or {}
    columns = _get_columns()
    data = _get_data(filters)
    # Enrich data with reference outstanding
    data = _enrich_with_reference_outstanding(data)
    return columns, data


def _get_columns() -> List[Dict]:
    return [
        {"fieldname": "receipt_no", "label": _("Receipt No"), "fieldtype": "Link", "options": "Customer Receipt", "width": 160},
        {"fieldname": "posting_date", "label": _("Posting Date"), "fieldtype": "Date", "width": 110},
        {"fieldname": "customer", "label": _("Customer"), "fieldtype": "Link", "options": "Customer", "width": 200},
        {"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 110},
        {"fieldname": "payment_type", "label": _("Payment Type"), "fieldtype": "Data", "width": 120},
        {"fieldname": "receipt_purpose", "label": _("Purpose"), "fieldtype": "Data", "width": 130},
        {"fieldname": "customer_reference_no", "label": _("Customer Ref"), "fieldtype": "Data", "width": 160},
        {"fieldname": "sales_order_no", "label": _("Sales Order"), "fieldtype": "Data", "width": 200},
        {"fieldname": "sales_invoice_no", "label": _("Sales Invoice"), "fieldtype": "Data", "width": 200},
        {"fieldname": "total_amount", "label": _("CR Amount"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "paid_amount", "label": _("CR Paid"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "outstanding_amount", "label": _("CR Outstanding"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "ref_outstanding", "label": _("Ref Outstanding"), "fieldtype": "Currency", "width": 140},
        {"fieldname": "stamp_mode", "label": _("Stamp Mode"), "fieldtype": "Data", "width": 110},
        {"fieldname": "digital_stamp_status", "label": _("Digital Stamp Status"), "fieldtype": "Data", "width": 160},
        {"fieldname": "payment_entries", "label": _("Payment Entry"), "fieldtype": "Data", "width": 220},
    ]


def _enrich_with_reference_outstanding(data: List[Dict]) -> List[Dict]:
    """
    Enrich report data with reference document outstanding.
    This shows the ACTUAL outstanding in Sales Order/Invoice, not just Customer Receipt.
    """
    for row in data:
        ref_outstanding = 0
        payment_type = ""

        # Get Sales Order outstanding
        if row.get("sales_order_no"):
            so_names = [s.strip() for s in row["sales_order_no"].split(",") if s.strip()]
            for so_name in so_names:
                so_data = frappe.db.get_value(
                    "Sales Order", so_name,
                    ["grand_total", "advance_paid", "rounded_total"],
                    as_dict=True
                )
                if so_data:
                    grand = so_data.get("rounded_total") or so_data.get("grand_total") or 0
                    paid = so_data.get("advance_paid") or 0
                    ref_outstanding += (grand - paid)

        # Get Sales Invoice outstanding
        if row.get("sales_invoice_no"):
            si_names = [s.strip() for s in row["sales_invoice_no"].split(",") if s.strip()]
            for si_name in si_names:
                si_outstanding = frappe.db.get_value("Sales Invoice", si_name, "outstanding_amount") or 0
                ref_outstanding += si_outstanding

        row["ref_outstanding"] = ref_outstanding

        # Determine payment type indicator
        if row.get("status") == "Paid" and ref_outstanding > 0:
            payment_type = "DP/Partial"
        elif row.get("status") == "Paid" and ref_outstanding == 0:
            payment_type = "Full Payment"
        elif row.get("status") == "Partially Paid":
            payment_type = "In Progress"
        elif row.get("status") == "Issued":
            payment_type = "Pending"
        else:
            payment_type = row.get("status", "")

        row["payment_type"] = payment_type

    return data


def _get_conditions(filters: Dict) -> Tuple[str, Dict]:
    conditions = []
    params: Dict[str, str] = {}

    mapping = {
        "date_from": ("cr.posting_date", ">="),
        "date_to": ("cr.posting_date", "<="),
        "receipt_no": ("cr.name", "="),
        "status": ("cr.status", "="),
        "customer": ("cr.customer", "="),
        "customer_reference_no": ("cr.customer_reference_no", "="),
        "sales_order_no": ("cri.sales_order", "="),
        "billing_no": ("cri.sales_invoice", "="),
        "receipt_purpose": ("cr.receipt_purpose", "="),
        "stamp_mode": ("cr.stamp_mode", "="),
        "digital_stamp_status": ("cr.digital_stamp_status", "="),
    }

    for key, (field, operator) in mapping.items():
        if filters.get(key):
            conditions.append(f"{field} {operator} %({key})s")
            params[key] = filters[key]

    if filters.get("sales_invoice_no"):
        conditions.append("cri.sales_invoice = %(sales_invoice_no)s")
        params["sales_invoice_no"] = filters["sales_invoice_no"]

    where = " and ".join(conditions) if conditions else "1=1"
    return where, params


def _get_data(filters: Dict) -> List[Dict]:
    where, params = _get_conditions(filters)
    query = f"""
        select
            cr.name as receipt_no,
            cr.posting_date,
            cr.customer,
            cr.status,
            cr.receipt_purpose,
            cr.customer_reference_no,
            group_concat(distinct cri.sales_order separator ', ') as sales_order_no,
            group_concat(distinct cri.sales_invoice separator ', ') as sales_invoice_no,
            cr.total_amount,
            cr.paid_amount,
            cr.outstanding_amount,
            cr.stamp_mode,
            cr.digital_stamp_status,
            group_concat(distinct crp.payment_entry separator ', ') as payment_entries
        from `tabCustomer Receipt` cr
        left join `tabCustomer Receipt Item` cri on cri.parent = cr.name
        left join `tabCustomer Receipt Payment` crp on crp.parent = cr.name
        where {where}
        group by cr.name
        order by cr.posting_date desc, cr.name desc
    """
    return frappe.db.sql(query, params, as_dict=True)
