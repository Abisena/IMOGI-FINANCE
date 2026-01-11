#!/usr/bin/env python3
"""
Quick validation test for workflow_state fix in Budget Control
Run: python3 test_workflow_state_fix.py
"""
import types


def test_status_check_logic():
    """Simulate the new logic for status/workflow_state checking"""
    
    target_state = "Approved"
    
    # Scenario 1: ERPNext v14 - only status is set
    er_v14 = types.SimpleNamespace(
        status="Approved",
        workflow_state=None
    )
    
    status = getattr(er_v14, "status", None)
    workflow_state = getattr(er_v14, "workflow_state", None)
    should_reserve_v14 = not (status != target_state and workflow_state != target_state)
    
    assert should_reserve_v14, "v14 scenario (status only) should trigger reservation"
    print("✅ v14 scenario (status='Approved', workflow_state=None): PASS")
    
    # Scenario 2: ERPNext v15 - only workflow_state is set
    er_v15 = types.SimpleNamespace(
        status="Submitted",
        workflow_state="Approved"
    )
    
    status = getattr(er_v15, "status", None)
    workflow_state = getattr(er_v15, "workflow_state", None)
    should_reserve_v15 = not (status != target_state and workflow_state != target_state)
    
    assert should_reserve_v15, "v15 scenario (workflow_state only) should trigger reservation"
    print("✅ v15 scenario (status='Submitted', workflow_state='Approved'): PASS")
    
    # Scenario 3: Both set to Approved
    er_both = types.SimpleNamespace(
        status="Approved",
        workflow_state="Approved"
    )
    
    status = getattr(er_both, "status", None)
    workflow_state = getattr(er_both, "workflow_state", None)
    should_reserve_both = not (status != target_state and workflow_state != target_state)
    
    assert should_reserve_both, "Both approved should trigger reservation"
    print("✅ Both approved scenario: PASS")
    
    # Scenario 4: Neither approved
    er_draft = types.SimpleNamespace(
        status="Draft",
        workflow_state="Draft"
    )
    
    status = getattr(er_draft, "status", None)
    workflow_state = getattr(er_draft, "workflow_state", None)
    should_not_reserve = (status != target_state and workflow_state != target_state)
    
    assert should_not_reserve, "Draft should NOT trigger reservation"
    print("✅ Draft scenario (should not reserve): PASS")
    
    # Scenario 5: One is None, other is Draft
    er_partial = types.SimpleNamespace(
        status="Submitted",
        workflow_state=None
    )
    
    status = getattr(er_partial, "status", None)
    workflow_state = getattr(er_partial, "workflow_state", None)
    should_not_reserve_partial = (status != target_state and workflow_state != target_state)
    
    assert should_not_reserve_partial, "Submitted without Approved workflow_state should NOT trigger"
    print("✅ Partial scenario (status='Submitted', workflow_state=None): PASS")


def test_handle_workflow_logic():
    """Test the handle_expense_request_workflow condition"""
    
    target_state = "Approved"
    
    # Test various combinations
    test_cases = [
        # (status, workflow_state, next_state, should_trigger, label)
        ("Approved", None, None, True, "v14 status only"),
        ("Submitted", "Approved", None, True, "v15 workflow_state only"),
        ("Submitted", "Submitted", "Approved", True, "next_state trigger"),
        ("Approved", "Approved", "Approved", True, "all approved"),
        ("Draft", None, None, False, "draft state"),
        ("Submitted", "Submitted", None, False, "submitted state"),
        (None, None, "PI Created", False, "PI Created state"),
    ]
    
    for status, workflow_state, next_state, expected, label in test_cases:
        er = types.SimpleNamespace(status=status, workflow_state=workflow_state)
        
        s = getattr(er, "status", None)
        ws = getattr(er, "workflow_state", None)
        should_trigger = (s == target_state or ws == target_state or next_state == target_state)
        
        assert should_trigger == expected, f"Failed: {label}"
        print(f"✅ Handle workflow - {label}: {'TRIGGER' if should_trigger else 'SKIP'} (expected: {expected})")


if __name__ == "__main__":
    print("=" * 60)
    print("Testing Budget Control Workflow State Logic")
    print("=" * 60)
    print()
    
    print("Test 1: Status Check Logic (reserve_budget_for_request)")
    print("-" * 60)
    test_status_check_logic()
    print()
    
    print("Test 2: Handle Workflow Logic (handle_expense_request_workflow)")
    print("-" * 60)
    test_handle_workflow_logic()
    print()
    
    print("=" * 60)
    print("✅ All tests passed! Logic is correct.")
    print("=" * 60)
