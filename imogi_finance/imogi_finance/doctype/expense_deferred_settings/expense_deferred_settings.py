from __future__ import annotations

import frappe
from frappe.model.document import Document


class ExpenseDeferredSettings(Document):
    """Controller for Expense Deferred Settings"""
    
    def validate(self):
        """Validate settings before saving"""
        self.validate_default_prepaid_account()
        self.validate_deferrable_accounts()
    
    def validate_default_prepaid_account(self):
        """Validate that default prepaid account is an asset account"""
        if self.default_prepaid_account:
            account = frappe.db.get_value(
                "Account", 
                self.default_prepaid_account, 
                ["root_type", "is_group"], 
                as_dict=1
            )
            if account:
                if account.is_group:
                    frappe.throw(
                        f"Default Prepaid Account {self.default_prepaid_account} cannot be a group account"
                    )
                if account.root_type != "Asset":
                    frappe.throw(
                        f"Default Prepaid Account {self.default_prepaid_account} must be an Asset account"
                    )
    
    def validate_deferrable_accounts(self):
        """Validate deferrable accounts configuration"""
        if not self.deferrable_accounts:
            return
        
        seen_accounts = set()
        for idx, row in enumerate(self.deferrable_accounts, start=1):
            if not row.prepaid_account:
                frappe.throw(f"Row {idx}: Prepaid Account is required")
            
            # Check for duplicate prepaid accounts
            if row.prepaid_account in seen_accounts:
                frappe.throw(
                    f"Row {idx}: Duplicate Prepaid Account {row.prepaid_account}"
                )
            seen_accounts.add(row.prepaid_account)
            
            # Validate prepaid account is an asset
            account = frappe.db.get_value(
                "Account", 
                row.prepaid_account, 
                ["root_type", "is_group"], 
                as_dict=1
            )
            if account:
                if account.is_group:
                    frappe.throw(
                        f"Row {idx}: Prepaid Account {row.prepaid_account} cannot be a group account"
                    )
                if account.root_type != "Asset":
                    frappe.throw(
                        f"Row {idx}: Prepaid Account {row.prepaid_account} must be an Asset account"
                    )


def get_settings():
    """Get Expense Deferred Settings singleton"""
    return frappe.get_single("Expense Deferred Settings")


def get_deferrable_account_map():
    """Get mapping of prepaid accounts to their configuration"""
    settings = get_settings()
    accounts = {}
    for row in getattr(settings, "deferrable_accounts", []) or []:
        if not getattr(row, "is_active", 0):
            continue
        prepaid = getattr(row, "prepaid_account", None)
        if prepaid:
            accounts[prepaid] = row
    return settings, accounts
