"""Branch Expense Request event handlers for doc_events hooks."""
from __future__ import annotations


def sync_status_with_workflow(doc, method=None):
    """Sync status field with workflow_state after save.
    
    This ensures the 'status' field matches 'workflow_state' for display consistency
    when workflow actions are performed.
    Records timestamp for each approval level.
    """
    workflow_state = getattr(doc, "workflow_state", None)
    current_status = getattr(doc, "status", None)
    
    if not workflow_state:
        return
    
    # Sync status with workflow_state if different
    if current_status != workflow_state:
        # Use db_set to update without triggering hooks again
        doc.db_set("status", workflow_state, update_modified=False)
    
    # Handle approval level timestamp recording
    previous = getattr(doc, "_doc_before_save", None)
    if previous:
        prev_state = getattr(previous, "workflow_state", None)
        
        # Record timestamp when transitioning FROM Pending Review
        if prev_state == "Pending Review":
            current_level = getattr(previous, "current_approval_level", None) or 1
            
            if workflow_state == "Approved":
                # Final approval - record timestamp
                _record_approval_timestamp(doc, current_level)
            elif workflow_state == "Pending Review":
                # Multi-level approval - record timestamp and advance level
                _record_approval_timestamp(doc, current_level)
            elif workflow_state == "Rejected":
                # Rejection - record timestamp
                _record_rejection_timestamp(doc, current_level)


def _record_approval_timestamp(doc, level: int):
    """Record approval timestamp for a specific level."""
    timestamp_field = f"level_{level}_approved_on"
    if hasattr(doc, timestamp_field):
        from frappe.utils import now_datetime
        doc.db_set(timestamp_field, now_datetime(), update_modified=False)


def _record_rejection_timestamp(doc, level: int):
    """Record rejection timestamp for a specific level."""
    timestamp_field = f"level_{level}_rejected_on"
    if hasattr(doc, timestamp_field):
        from frappe.utils import now_datetime
        doc.db_set(timestamp_field, now_datetime(), update_modified=False)
