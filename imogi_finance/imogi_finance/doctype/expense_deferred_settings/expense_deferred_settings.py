from __future__ import annotations

import frappe


def get_settings():
    return frappe.get_single("Expense Deferred Settings")


def get_deferrable_account_map():
    settings = get_settings()
    accounts = {}
    for row in getattr(settings, "deferrable_accounts", []) or []:
        if not getattr(row, "is_active", 0):
            continue
        prepaid = getattr(row, "prepaid_account", None)
        if prepaid:
            accounts[prepaid] = row
    return settings, accounts
