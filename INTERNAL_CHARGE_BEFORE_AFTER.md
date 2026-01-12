# Before vs After Comparison

## Internal Charge Request Approval Flow

### ❌ BEFORE (Without Workflow)

```
Internal Charge Request (Draft)
  │
  ├─ Line 1 (CC-A): route resolved, but no workflow enforcement
  ├─ Line 2 (CC-B): route resolved, but no workflow enforcement
  └─ Line 3 (CC-C): route resolved, but no workflow enforcement
       │
       └─ Submit
            │
            ├─ _populate_line_routes() → sets line_status = Pending L1/L2/L3
            ├─ _sync_status() → aggregates to document status = Pending Approval
            └─ MISSING: workflow_state field
                 │
                 └─ before_workflow_action("Approve")
                      │
                      ├─ Find approvable lines (current user matches route)
                      ├─ _advance_line_status() → L1→L2 or L2→L3 or L3→Approved
                      ├─ _sync_status() → updates status
                      └─ MISSING: No workflow transitions!
                           │
                           └─ Status remains "Pending Approval"
                                (or changes to Approved/Partially Approved)
                                BUT: No workflow state history, no proper state machine
```

**Problems:**
- ❌ No workflow state transitions logged
- ❌ Status changes without proper workflow states
- ❌ No clear visual indication of approval level in workflow
- ❌ Inconsistent with Expense Request pattern
- ❌ No workflow audit trail

---

### ✅ AFTER (With Dedicated Workflow)

```
Internal Charge Request (Draft)
  │
  ├─ Line 1 (CC-A): route resolved per cost center
  ├─ Line 2 (CC-B): route resolved per cost center
  └─ Line 3 (CC-C): route resolved per cost center
       │
       └─ Submit (Workflow Action)
            │
            ├─ before_workflow_action("Submit")
            │   ├─ _validate_submit_permission()
            │   └─ flags workflow_action_allowed = True
            │
            ├─ _populate_line_routes() → sets line_status per CC
            ├─ _sync_status() → aggregates status
            ├─ _sync_workflow_state() → sets workflow_state = "Pending L1 Approval"
            │
            └─ Workflow Transition
                 Draft → Pending L1 Approval ✅
                 (Logged in workflow state history)
                 │
                 └─ Approve (Workflow Action) - User1 (CC-A Approver)
                      │
                      ├─ before_workflow_action("Approve")
                      │   └─ _validate_approve_permission()
                      │       ├─ Check: Is User1 in approvable_lines?
                      │       │   ├─ Line 1 (CC-A): ✅ User1 matches L1 approver
                      │       │   ├─ Line 2 (CC-B): ❌ User1 NOT approver for CC-B
                      │       │   └─ Line 3 (CC-C): ❌ User1 NOT approver for CC-C
                      │       ├─ Advance Line 1: L1→L2 (if L2 configured)
                      │       ├─ _sync_status() → Partially Approved
                      │       └─ _sync_workflow_state() → Pending L2 Approval
                      │
                      └─ Workflow Transition
                           Pending L1 Approval → Pending L2 Approval ✅
                           (Logged in workflow state history)
                           │
                           └─ Approve (Workflow Action) - User2 (CC-B Approver)
                                │
                                ├─ before_workflow_action("Approve")
                                │   └─ _validate_approve_permission()
                                │       ├─ Line 1: ❌ Pending L2, not L1 (User2 is L1, skip)
                                │       ├─ Line 2: ✅ User2 matches L1 approver for CC-B
                                │       └─ Line 3: ❌ User2 NOT approver for CC-C
                                │
                                ├─ Advance Line 2: L1→Approved (if no L2)
                                ├─ _sync_status() → Partially Approved
                                └─ _sync_workflow_state() → Pending L2 Approval
                                     (Line 1 still waiting for L2)
                                     │
                                     └─ Continue until all lines Approved
                                          │
                                          └─ Workflow Transition
                                               Pending L2 Approval → Approved ✅
                                               (All lines approved)
```

---

## Key Improvements

### 1. **Workflow State Tracking** ✅
**Before:** No workflow_state field
```
Document status: "Pending Approval"
(Unclear which approval level)
```

**After:** Proper workflow_state field
```
workflow_state: "Pending L1 Approval"  → Level 1 pending
workflow_state: "Pending L2 Approval"  → Level 2 pending
workflow_state: "Pending L3 Approval"  → Level 3 pending
workflow_state: "Partially Approved"   → Some lines approved
workflow_state: "Approved"             → All lines approved
```

### 2. **Cost-Centre-Aware Enforcement** ✅
**Before:** 
```python
# Just checks if line_status is pending
if getattr(line, "line_status", None) not in {"Pending L1", "Pending L2", "Pending L3"}:
    continue
# But ANY user who matches ANY line can approve
```

**After:**
```python
# Checks cost-centre-specific route for EACH line
for line in approvable_lines:
    snapshot = _parse_route_snapshot(getattr(line, "route_snapshot", None))
    # Route is per-line per-cost_center
    expected_user = level_meta.get("user")  # Cost-centre specific!
    
    # Only approves if matches
    if user_allowed and role_allowed:
        approvable_lines.append(line)
```

### 3. **Multi-Cost-Centre Support** ✅
**Before:** 
- Lines resolved routes per cost center ✅
- But approval was not cost-centre-isolated ❌

**After:**
- Lines resolved routes per cost center ✅
- Approval enforcement per cost center ✅
- Error message shows required cost centers ✅

Example:
```
User1 is approver for CC-A only
→ Can approve CC-A lines
→ Cannot approve CC-B, CC-C lines
→ Clear error: "Required cost centers: CC-B, CC-C"
```

### 4. **Workflow Audit Trail** ✅
**Before:**
```
history_table: no workflow state changes logged
```

**After:**
```
history_table entries:
├─ Draft → Pending L1 Approval (Submit)
├─ Pending L1 Approval → Pending L2 Approval (Approve by User1)
├─ Pending L2 Approval → Partially Approved (Approve by User2)
├─ Partially Approved → Pending L2 Approval (Approve by User3)
└─ Pending L2 Approval → Approved (Approve by User4)
```

### 5. **Approval Audit Fields** ✅
**Before:**
```
approved_by: (field not in DocType)
approved_on: (field not in DocType)
```

**After:**
```
approved_by: "user@test.com"
approved_on: "2026-01-12 10:30:45"
(Fields now tracked in DocType)
```

### 6. **Consistency with Expense Request** ✅
**Before:**
| Feature | Expense Request | Internal Charge |
|---------|-----------------|-----------------|
| Workflow | ✅ Has | ❌ No |
| workflow_state | ✅ Tracked | ❌ No field |
| Level advancement | ✅ Via workflow | ❌ Manual method |

**After:**
| Feature | Expense Request | Internal Charge |
|---------|-----------------|-----------------|
| Workflow | ✅ Has | ✅ Has |
| workflow_state | ✅ Tracked | ✅ Tracked |
| Level advancement | ✅ Via workflow | ✅ Via workflow |
| Cost-centre awareness | ✅ Yes (single) | ✅ Yes (per-line) |

---

## Code Changes Summary

### New Methods in InternalChargeRequest:
```python
# 2 new validation methods
_validate_submit_permission()     # Submit validation
_validate_approve_permission()    # Cost-centre-aware approve validation

# 1 new sync method
_sync_workflow_state()            # Maps status → workflow_state
```

### Enhanced Methods:
```python
before_workflow_action()          # Now handles Submit & Approve properly
before_submit()                   # Now calls _sync_workflow_state()
_sync_status()                    # Same logic, called from new methods
```

### New Files:
```
imogi_finance/workflow/internal_charge_request_workflow/
├─ __init__.py
└─ internal_charge_request_workflow.json
```

### New Tests:
```
imogi_finance/tests/test_internal_charge_workflow.py
├─ TestInternalChargeWorkflowState (5 tests)
├─ TestMultiCostCenterApproval (4 tests)
└─ TestApprovalLevelAdvancement (4 tests)
```

---

## Impact Summary

### ✅ Benefits:
1. **Proper State Machine** - Workflow states properly tracked and transitioned
2. **Better UX** - Users see clear approval level status
3. **Enhanced Audit Trail** - Workflow history shows all state changes
4. **Cost-Centre Isolation** - Each cost center has independent approval flow
5. **Consistency** - Now follows same pattern as Expense Request
6. **Clarity** - Clear error messages when user not authorized for cost center

### ✅ No Breaking Changes:
1. Existing Internal Charge Requests remain compatible
2. Status field still works (backwards compatible)
3. Line-based approval still works
4. No changes to existing workflows required

### ✅ Future Ready:
1. Easy to add new approval levels
2. Easy to add additional actions (like "Create PI")
3. Easy to add notifications per state
4. Scalable for more complex scenarios

---

## Deployment Checklist

- ✅ Workflow JSON created and validated
- ✅ DocType updated with new fields
- ✅ Python code updated with new methods
- ✅ Tests created and validated
- ✅ Backwards compatibility maintained
- ✅ Documentation provided

**Ready for deployment!**
