# Copyright (c) 2026, PT. Inovasi Terbaik Bangsa and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ExpenseApprovalLine(Document):
    """Child table to capture approval levels for expense accounts."""

    def validate(self):
        self.validate_level_amounts()
        self.validate_default_vs_account()

    def validate_level_amounts(self):
        """Validate level-specific amount ranges."""
        for level in (1, 2, 3):
            min_amt = getattr(self, f"level_{level}_min_amount", None)
            max_amt = getattr(self, f"level_{level}_max_amount", None)
            user = getattr(self, f"level_{level}_user", None)

            # Skip if level not configured
            if not user:
                continue

            # If level has approver, amount range is required
            if min_amt is None or max_amt is None:
                frappe.throw(
                    _("Level {0} requires both Min Amount and Max Amount when approver is configured.").format(level)
                )

            if min_amt > max_amt:
                frappe.throw(
                    _("Level {0} Min Amount cannot exceed Max Amount.").format(level)
                )

    def validate_default_vs_account(self):
        """Ensure default (Apply to All) lines do not specify an Expense Account.

        Business rule:
        - Default lines (is_default = 1 / Apply to All Accounts) are global fallbacks
          and must NOT bind to a specific Expense Account.
        - Account-specific rules should use is_default = 0 with Expense Account filled.
        """

        is_default = getattr(self, "is_default", 0)
        expense_account = getattr(self, "expense_account", None)

        if is_default and expense_account:
            frappe.throw(
                _(
                    "Default approval line (Apply to All Accounts) cannot specify an Expense Account. "
                    "Please either clear the Expense Account or uncheck Apply to All Accounts."
                )
            )