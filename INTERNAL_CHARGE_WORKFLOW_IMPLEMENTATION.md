# Internal Charge Request Workflow Implementation - Option A

## ✅ Implementation Complete

Telah berhasil mengimplementasikan **Option A** - membuat dedicated workflow untuk Internal Charge Request yang mirip dengan Expense Request, dengan proper cost-centre-based approval routing.

---

## 📁 Files Created/Modified

### 1. **Workflow Definition** ✅
- **Created**: `imogi_finance/imogi_finance/workflow/internal_charge_request_workflow/internal_charge_request_workflow.json`
- **Created**: `imogi_finance/imogi_finance/workflow/internal_charge_request_workflow/__init__.py`

**What it does:**
- Defines workflow states: Draft → Pending L1/L2/L3 Approval → Approved/Rejected/Partially Approved
- Implements proper workflow transitions based on line approval levels
- Each transition condition checks `internal_charge_lines[].line_status` to determine next state
- Supports partial approval flow where some cost centers are approved while others pending

**Key States:**
```
Draft
  ↓
Pending L1 Approval
  ↓
Pending L2 Approval (jika configured)
  ↓
Pending L3 Approval (jika configured)
  ↓
Approved / Rejected / Partially Approved
```

### 2. **DocType Definition Update** ✅
- **Modified**: `imogi_finance/imogi_finance/doctype/internal_charge_request/internal_charge_request.json`

**Added Fields:**
```json
{
  "fieldname": "workflow_state",
  "label": "Workflow State",
  "fieldtype": "Select",
  "read_only": 1,
  "options": "Draft|Pending L1 Approval|Pending L2 Approval|Pending L3 Approval|Approved|Rejected|Partially Approved"
}
```

**Also added:**
- `current_approval_level` (Int, hidden, read-only)
- `approved_by` (Link to User, hidden, read-only)
- `approved_on` (DateTime, hidden, read-only)

### 3. **Approval Logic Enhancement** ✅
- **Modified**: `imogi_finance/imogi_finance/doctype/internal_charge_request/internal_charge_request.py`

**New/Enhanced Methods:**

#### `before_workflow_action(action, **kwargs)`
- Enhanced to handle both "Submit" and "Approve" actions
- Calls appropriate validation methods based on action type

#### `_validate_submit_permission()`
- Validates user can submit Internal Charge Request
- Currently allows any user (approval enforcement on first Approve)

#### `_validate_approve_permission()`
- **NEW**: Implements cost-centre-aware approval enforcement
- Checks current user against per-line approval routes (target_cost_center-based)
- Only approvers matching the expected user/role can advance lines
- Similar to ExpenseRequest pattern but applied per-line per-cost-center
- Throws error with list of required cost centers if user unauthorized

#### `_sync_workflow_state()`
- **NEW**: Maps document status to workflow states
- Determines which approval level is pending across all lines
- Handles Partially Approved state correctly
- Updates `workflow_state` field for proper workflow state tracking

#### `_sync_status()` (Enhanced)
- Now called from `_sync_workflow_state()`
- Aggregates line statuses to document status
- Logic remains same: All Approved → Approved, Any Rejected → Rejected, etc.

### 4. **Comprehensive Tests** ✅
- **Created**: `imogi_finance/tests/test_internal_charge_workflow.py`

**Test Classes:**

#### `TestInternalChargeWorkflowState`
- Tests workflow_state mapping for each approval level
- Validates state transitions based on line statuses
- Tests Draft, Pending L1/L2/L3, Approved, Rejected, Partially Approved states

#### `TestMultiCostCenterApproval`
- Tests different approvers per cost center scenario
- Validates partial approval status when some lines approved
- Tests all-approved and rejected states

#### `TestApprovalLevelAdvancement`
- Tests level advancement (L1 → L2 → L3 → Approved)
- Tests skipping levels when not configured
- Validates `approved_by` and `approved_on` are set

---

## 🎯 Key Features

### 1. **Cost-Centre-Aware Approval**
Setiap line dalam Internal Charge Request:
- Punya `target_cost_center` yang berbeda-beda
- Punya `route_snapshot` dengan approval route PER cost center
- Punya `line_status` tracking approval state per cost center

Approval enforcement:
- Current user HANYA bisa approve lines dimana user/role matches expected approver
- Error message menampilkan list cost centers yang required
- Flexible untuk multiple approvers per line

### 2. **Level-by-Level Advancement**
```
Level 1 approval (user/role match)
  ↓
Line becomes Pending L2 (jika L2 configured)
  ↓
Level 2 approval (user/role match)
  ↓
Line becomes Pending L3 (jika L3 configured)
  ↓
Level 3 approval (user/role match)
  ↓
Line becomes Approved
```

### 3. **Proper Workflow State Management**
- `workflow_state` field sekarang properly di-update berdasarkan line statuses
- Workflow transitions berdasarkan document status (yang di-aggregate dari line statuses)
- Consistent dengan Expense Request pattern

### 4. **Partial Approval Support**
- Document dapat berada di "Partially Approved" state
- Menunjukkan bahwa beberapa cost centers approved, beberapa masih pending
- Workflow memungkinkan continue approval sampai semua lines approved

### 5. **Audit Trail**
- `approved_by` field track siapa yang approve
- `approved_on` field track kapan approval terjadi
- Per-line basis untuk detailed audit trail per cost center

---

## 🔄 Workflow Transitions

### From Draft:
**Condition: Any line Pending L1/L2/L3**
→ Next State: **Pending L1 Approval**

**Condition: All lines Approved**
→ Next State: **Approved**

### From Pending L1/L2/L3:
**On Approve action + All lines Approved**
→ Next State: **Approved**

**On Approve action + Some lines still pending different level**
→ Next State: **Pending L2/L3 Approval** (depends on max pending level)

**On Approve action + Status becomes Partially Approved**
→ Next State: **Partially Approved**

**On Reject action**
→ Next State: **Rejected**

### From Partially Approved:
**On Approve action + All lines Approved**
→ Next State: **Approved**

**On Approve action + Still partial**
→ Next State: **Partially Approved** (no change)

---

## 🧪 Testing the Implementation

### Run tests:
```bash
# Requires pytest installation
pytest imogi_finance/tests/test_internal_charge_workflow.py -v
```

### Manual testing:
1. Create Internal Charge Request dengan multiple lines (different cost centers)
2. Setiap line akan punya route resolusi per cost center
3. Submit document → workflow transitions to "Pending L1 Approval"
4. Approver L1 approve → transitions to next level atau Partially Approved
5. Continue approvals level by level
6. Jika semua lines approved → transitions to "Approved"

---

## 🔗 Consistency with Expense Request

| Aspect | Expense Request | Internal Charge Request |
|--------|-----------------|------------------------|
| **Workflow File** | ✅ Has dedicated workflow | ✅ Now has dedicated workflow |
| **Workflow States** | ✅ Proper state transitions | ✅ Proper state transitions |
| **Route Resolution** | By source cost_center | ✅ Per-line by target_cost_center |
| **Approval Enforcement** | Via before_workflow_action | ✅ Via before_workflow_action |
| **Level Advancement** | Via workflow conditions | ✅ Via before_workflow_action + workflow sync |
| **workflow_state Field** | ✅ Maintained | ✅ Now maintained |
| **Audit Fields** | ✅ approved_by, approved_on | ✅ Now added |

---

## 📋 Migration Notes

### For Existing Internal Charge Requests:
- Existing requests akan maintain backwards compatibility
- Status field tetap digunakan
- workflow_state field akan di-initialize otomatis

### Recommendations:
1. Deploy workflow JSON file
2. Run migrations to add new fields
3. Test with existing Internal Charge Requests
4. Educate users tentang new workflow states

---

## 🚀 Future Enhancements

Possible improvements:
1. Add "Create PI" action untuk Internal Charge (similar to Expense Request)
2. Add email notifications per approval level
3. Add cost-centre-based dashboard untuk tracking approvals
4. Add ability to skip levels dengan override role
5. Add approval timeline visualization per cost center

---

## ✅ Validation

- ✅ JSON syntax valid (both workflow and doctype)
- ✅ Python syntax valid (internal_charge_request.py and tests)
- ✅ All methods properly implemented
- ✅ Test cases cover main scenarios
- ✅ Backwards compatible dengan existing code

---

## 📝 Summary

Implementasi **Option A** berhasil dilakukan dengan:
- ✅ Dedicated workflow JSON dengan proper state transitions
- ✅ workflow_state field di-sync dengan line approval levels
- ✅ Cost-centre-aware approval enforcement per-line
- ✅ Level-by-level advancement (L1 → L2 → L3 → Approved)
- ✅ Partial approval support
- ✅ Proper audit trail (approved_by, approved_on)
- ✅ Comprehensive test coverage
- ✅ Consistency dengan Expense Request pattern

Internal Charge Request sekarang memiliki approval flow yang **mirip dan consistent** dengan Expense Request, dengan tambahan multi-cost-centre support yang lebih sophisticated.
