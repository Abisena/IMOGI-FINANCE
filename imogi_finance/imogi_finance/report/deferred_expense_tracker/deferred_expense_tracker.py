from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters: dict | None = None):
    filters = filters or {}
    columns = get_columns()
    data = get_data(filters)
    summary = get_summary(data)
    return columns, data, None, None, summary


def get_columns() -> list[dict]:
    return [
        {
            "label": _("ER Number"),
            "fieldname": "expense_request",
            "fieldtype": "Link",
            "options": "Expense Request",
            "width": 160,
        },
        {"label": _("ER Date"), "fieldname": "er_date", "fieldtype": "Date", "width": 110},
        {"label": _("Item Description"), "fieldname": "description", "fieldtype": "Data", "width": 200},
        {
            "label": _("Prepaid Account"),
            "fieldname": "prepaid_account",
            "fieldtype": "Link",
            "options": "Account",
            "width": 180,
        },
        {
            "label": _("Expense Account"),
            "fieldname": "expense_account",
            "fieldtype": "Link",
            "options": "Account",
            "width": 180,
        },
        {
            "label": _("Total Amount"),
            "fieldname": "total_amount",
            "fieldtype": "Currency",
            "width": 130,
        },
        {"label": _("Periods"), "fieldname": "periods", "fieldtype": "Int", "width": 80},
        {"label": _("Start Date"), "fieldname": "start_date", "fieldtype": "Date", "width": 110},
        {
            "label": _("PI Number"),
            "fieldname": "purchase_invoice",
            "fieldtype": "Link",
            "options": "Purchase Invoice",
            "width": 160,
        },
        {"label": _("PI Date"), "fieldname": "pi_date", "fieldtype": "Date", "width": 110},
        {"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 110},
        {
            "label": _("Outstanding Balance"),
            "fieldname": "outstanding_balance",
            "fieldtype": "Currency",
            "width": 160,
        },
    ]


def get_conditions(filters: dict) -> tuple[str, dict]:
    conditions = ["er.docstatus = 1", "eri.is_deferred_expense = 1"]
    params: dict[str, str] = {}

    if filters.get("from_date"):
        conditions.append("er.request_date >= %(from_date)s")
        params["from_date"] = filters["from_date"]

    if filters.get("to_date"):
        conditions.append("er.request_date <= %(to_date)s")
        params["to_date"] = filters["to_date"]

    if filters.get("prepaid_account"):
        conditions.append("eri.prepaid_account = %(prepaid_account)s")
        params["prepaid_account"] = filters["prepaid_account"]

    if filters.get("expense_account"):
        conditions.append("eri.expense_account = %(expense_account)s")
        params["expense_account"] = filters["expense_account"]

    return " AND ".join(conditions), params


def get_data(filters: dict) -> list[dict]:
    where_clause, params = get_conditions(filters)
    query = f"""
        SELECT
            er.name AS expense_request,
            er.request_date AS er_date,
            eri.description,
            eri.prepaid_account,
            eri.expense_account,
            eri.amount AS total_amount,
            eri.deferred_periods AS periods,
            eri.deferred_start_date AS start_date,
            pi.name AS purchase_invoice,
            pi.posting_date AS pi_date,
            pi.status AS status,
            COALESCE(SUM(gle.credit - gle.debit), 0) AS amortized_amount
        FROM `tabExpense Request Item` eri
        JOIN `tabExpense Request` er ON er.name = eri.parent
        LEFT JOIN `tabPurchase Invoice` pi ON pi.imogi_expense_request = er.name
        LEFT JOIN `tabPurchase Invoice Item` pii
            ON pii.parent = pi.name
            AND pii.expense_account = eri.prepaid_account
            AND pii.amount = eri.amount
            AND (pii.description = eri.description OR pii.item_name = eri.description)
        LEFT JOIN `tabGL Entry` gle
            ON gle.against_voucher_type = 'Purchase Invoice'
            AND gle.against_voucher = pi.name
            AND gle.account = eri.prepaid_account
            AND gle.is_cancelled = 0
        WHERE {where_clause}
        GROUP BY
            eri.name,
            er.name,
            er.request_date,
            eri.description,
            eri.prepaid_account,
            eri.expense_account,
            eri.amount,
            eri.deferred_periods,
            eri.deferred_start_date,
            pi.name,
            pi.posting_date,
            pi.status
        ORDER BY er.request_date DESC, er.name DESC
    """

    rows = frappe.db.sql(query, params, as_dict=True)
    for row in rows:
        amortized = flt(row.get("amortized_amount"))
        total_amount = flt(row.get("total_amount"))
        row["outstanding_balance"] = total_amount - amortized
    return rows


def get_summary(data: list[dict]) -> list[dict]:
    total_deferred = sum(flt(row.get("total_amount")) for row in data)
    total_amortized = sum(flt(row.get("amortized_amount")) for row in data)
    total_outstanding = total_deferred - total_amortized

    return [
        {
            "label": _("Total Deferred"),
            "value": total_deferred,
            "indicator": "Blue",
        },
        {
            "label": _("Total Amortized"),
            "value": total_amortized,
            "indicator": "Green",
        },
        {
            "label": _("Total Outstanding"),
            "value": total_outstanding,
            "indicator": "Orange",
        },
    ]
