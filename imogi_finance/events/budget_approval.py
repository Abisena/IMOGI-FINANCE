"""Event handlers for Budget Approval workflow (Budget Reclass Request & Additional Budget Request)."""

from __future__ import annotations

import frappe


def sync_workflow_state_after_approval(doc, method=None):
    """
    Sync workflow state after approval action completes.
    
    This hook runs AFTER workflow save, ensuring state changes from advance_approval_level()
    are properly persisted and not overridden by workflow framework.
    
    Called via on_update_after_submit hook.
    """
    # Only process if doc is submitted (docstatus == 1)
    if doc.docstatus != 1:
        return
    
    # Get current approval level from DB (most reliable source)
    current_level = frappe.db.get_value(doc.doctype, doc.name, "current_approval_level")
    
    # If current_level is None, it means document is not in approval flow
    if current_level is None:
        return
    
    # Determine expected state based on current approval level
    # If level > 0, we're in multi-level approval - should be "Pending Approval"
    # If level == 0, final approval complete - should be "Approved"
    expected_state = "Pending Approval" if current_level > 0 else "Approved"
    
    # Get current workflow state from document
    current_state = getattr(doc, "workflow_state", None)
    
    # Only correct if state is wrong
    if current_state != expected_state:
        frappe.logger().info(
            f"sync_workflow_state_after_approval: Correcting {doc.doctype} {doc.name} from '{current_state}' to '{expected_state}' (current_approval_level={current_level})"
        )
        
        # Update in memory
        doc.workflow_state = expected_state
        doc.status = expected_state
        
        # Persist to DB - this will override any workflow framework changes
        frappe.db.set_value(
            doc.doctype,
            doc.name,
            {
                "workflow_state": expected_state,
                "status": expected_state,
            },
            update_modified=False
        )
        
        # Commit immediately to ensure persistence
        frappe.db.commit()
