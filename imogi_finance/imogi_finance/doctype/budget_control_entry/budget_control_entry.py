# Copyright (c) 2026, PT. Inovasi Terbaik Bangsa and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _

try:
    from frappe.model.document import Document
except Exception:  # pragma: no cover - fallback for test stubs
    class Document:  # type: ignore
        def __init__(self, *args, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)


class BudgetControlEntry(Document):
    """Ledger record for budget reservations and allocation deltas."""

    VALID_ENTRY_TYPES = {"RESERVATION", "CONSUMPTION", "RELEASE", "RECLASS", "SUPPLEMENT", "REVERSAL"}
    VALID_DIRECTIONS = {"IN", "OUT"}
    
    # Valid entry_type and direction combinations
    VALID_COMBINATIONS = {
        "RESERVATION": ["OUT"],
        "CONSUMPTION": ["IN"],
        "RELEASE": ["IN"],
        "REVERSAL": ["OUT"],
        "RECLASS": ["IN", "OUT"],
        "SUPPLEMENT": ["IN"]
    }

    def before_insert(self):
        """Prevent manual creation of Budget Control Entries."""
        # Check if this is being created programmatically (via ledger.post_entry)
        # by checking if ignore_permissions flag is set
        if not self.flags.get("ignore_permissions"):
            frappe.throw(
                _("""Budget Control Entries cannot be created manually.
                
This is an audit/logging DocType that is automatically created by:
- Expense Request approval (creates RESERVATION entries)
- Purchase Invoice submit (creates CONSUMPTION entries)
- Document cancellation (creates RELEASE/REVERSAL entries)
- Budget reclass/supplement operations (creates RECLASS/SUPPLEMENT entries)

Manual entry creation would corrupt budget tracking."""),
                title=_("Manual Creation Not Allowed")
            )

    def validate(self):
        if getattr(self, "amount", 0) is None or float(self.amount) <= 0:
            frappe.throw(_("Amount must be greater than zero."))

        if getattr(self, "entry_type", None) not in self.VALID_ENTRY_TYPES:
            frappe.throw(_("Entry Type must be one of: {0}").format(", ".join(sorted(self.VALID_ENTRY_TYPES))))

        if getattr(self, "direction", None) not in self.VALID_DIRECTIONS:
            frappe.throw(_("Direction must be IN or OUT."))
        
        # Validate ref_doctype and ref_name consistency
        if getattr(self, "ref_doctype", None) and not getattr(self, "ref_name", None):
            frappe.throw(_("Reference Name is required when Reference DocType is set"))
        
        if getattr(self, "ref_name", None) and not getattr(self, "ref_doctype", None):
            frappe.throw(_("Reference DocType is required when Reference Name is set"))
        
        # Validate entry_type and direction combinations
        entry_type = getattr(self, "entry_type", None)
        direction = getattr(self, "direction", None)
        if entry_type in self.VALID_COMBINATIONS:
            if direction not in self.VALID_COMBINATIONS[entry_type]:
                frappe.throw(
                    _("Invalid combination: {0} must have direction {1}").format(
                        entry_type,
                        " or ".join(self.VALID_COMBINATIONS[entry_type])
                    )
                )
    
    def before_cancel(self):
        """Prevent manual cancellation of Budget Control Entries."""
        frappe.throw(
            _("""Budget Control Entries cannot be cancelled directly.
            
To reverse a budget entry:
- For Expense Request: Cancel the Expense Request (will auto-create RELEASE entries)
- For Purchase Invoice: Cancel the Purchase Invoice (will auto-create REVERSAL entries)

Manual cancellation would corrupt budget tracking."""),
            title=_("Manual Cancel Not Allowed")
        )
    
    def on_cancel(self):
        """This should never be called due to before_cancel block."""
        frappe.log_error(
            title="Illegal Budget Control Entry Cancellation",
            message=f"Budget Control Entry {self.name} was cancelled directly! This should never happen."
        )
