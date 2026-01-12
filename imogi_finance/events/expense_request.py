"""Expense Request event handlers for doc_events hooks."""
from __future__ import annotations

import frappe
from frappe import _


def validate_workflow_action(doc, method=None):
    """Validate approver authorization when workflow action is being applied.
    
    This is triggered via doc_events validate hook when Frappe's apply_workflow
    saves the document. We detect if a workflow transition is happening and
    validate that the current user is the authorized approver.
    """
    # Skip if not in workflow transition
    if not _is_workflow_transition(doc):
        return
    
    # Skip if not transitioning to/from Pending Review
    if not _is_approval_action(doc):
        return
    
    # Get current approval level - default to 1 if not set
    current_level = getattr(doc, "current_approval_level", None) or 1
    
    # Get expected approver for this level
    expected_user = getattr(doc, f"level_{current_level}_user", None)
    
    if not expected_user:
        # No approver configured for this level
        frappe.throw(
            _("No approver configured for level {0}.").format(current_level),
            title=_("Not Allowed"),
        )
    
    session_user = frappe.session.user
    
    if session_user != expected_user:
        frappe.throw(
            _("You are not authorized to approve at level {0}. Required: {1}.").format(
                current_level, expected_user
            ),
            title=_("Not Allowed"),
        )


def sync_status_with_workflow(doc, method=None):
    """Sync status field with workflow_state after save.
    
    This ensures the 'status' field matches 'workflow_state' for display consistency.
    Also handles advancing approval level when approving with multi-level approval.
    """
    workflow_state = getattr(doc, "workflow_state", None)
    current_status = getattr(doc, "status", None)
    
    if not workflow_state:
        return
    
    # Sync status with workflow_state if different
    if current_status != workflow_state:
        # Use db_set to update without triggering hooks again
        doc.db_set("status", workflow_state, update_modified=False)
    
    # Handle approval level advancement for multi-level approval
    previous = getattr(doc, "_doc_before_save", None)
    if previous:
        prev_state = getattr(previous, "workflow_state", None)
        # If we just got approved at a level but staying in Pending Review (multi-level)
        if prev_state == "Pending Review" and workflow_state == "Pending Review":
            _advance_approval_level(doc)


def _is_workflow_transition(doc) -> bool:
    """Check if document is undergoing a workflow state transition."""
    # Check if there's a previous version to compare
    previous = getattr(doc, "_doc_before_save", None)
    if not previous:
        return False
    
    # Check if workflow_state is changing
    current_state = getattr(doc, "workflow_state", None)
    previous_state = getattr(previous, "workflow_state", None)
    
    return current_state != previous_state


def _is_approval_action(doc) -> bool:
    """Check if the transition involves approval (from or to Pending Review)."""
    previous = getattr(doc, "_doc_before_save", None)
    if not previous:
        return False
    
    current_state = getattr(doc, "workflow_state", None)
    previous_state = getattr(previous, "workflow_state", None)
    
    # Approval action: transitioning FROM Pending Review
    # This catches both Approve (to Pending Review or Approved) and Reject (to Rejected)
    if previous_state == "Pending Review":
        return True
    
    return False


def _advance_approval_level(doc):
    """Advance to next approval level for multi-level approval.
    
    Called when approval action keeps document in Pending Review (more levels to go).
    """
    current_level = getattr(doc, "current_approval_level", None) or 1
    
    # Find next level with an assigned user
    for level in range(current_level + 1, 4):
        user_field = f"level_{level}_user"
        if getattr(doc, user_field, None):
            doc.db_set("current_approval_level", level, update_modified=False)
            return
    
    # No more levels - shouldn't happen if workflow conditions are correct
