# Analisis Approval Flow: Internal Charge Request vs Expense Request

## Ringkasan Masalah
**Internal Charge Request** seharusnya memiliki approval flow yang mirip dengan **Expense Request** karena keduanya dikelompokkan berdasarkan **Cost Centre**. Namun saat ini implementasinya tidak konsisten.

---

## 1. Expense Request Approval Flow ✅

### Characteristics:
- **Single document** dengan **single cost_center**
- **Workflow-based** dengan state transitions
- **Route resolution**: Based on source cost_center

### Flow:
```
Cost Centre → get_active_setting_meta() → get_approval_route()
   ↓
expense_accounts + amount
   ↓
Expense Approval Line matching
   ↓
level_1_user, level_2_user, level_3_user
   ↓
Workflow transitions: Draft → Pending Review → Pending Review (L2) → Approved
```

### Code:
- **Route resolution**: `imogi_finance/approval.py` → `get_approval_route(cost_center, accounts, amount)`
- **Workflow enforcement**: `imogi_finance/imogi_finance/doctype/expense_request/expense_request.py` → `before_workflow_action()`
- **Workflow config**: `imogi_finance/imogi_finance/workflow/expense_request_workflow/expense_request_workflow.json`

### Key Features:
1. ✅ Cost centre-aware approval route resolution
2. ✅ Level advancement based on configuration
3. ✅ Proper workflow state management
4. ✅ Enforcement in `before_workflow_action()` with permission check

---

## 2. Internal Charge Request Approval Flow ❌ (Problematic)

### Current Structure:
- **Single document** dengan **multiple lines**
- Setiap line punya **target_cost_center** yang BERBEDA
- **Line-based approval** (per-line status tracking)
- **TIDAK ada workflow yang proper** - hanya `before_workflow_action()` hook

### Current Flow:
```
Internal Charge Request
   └── Line 1 (target_cost_center: CC-A) → route resolution
   └── Line 2 (target_cost_center: CC-B) → route resolution
   └── Line 3 (target_cost_center: CC-C) → route resolution
       ↓
   All lines aggregated to document status
       ↓
   before_workflow_action("Approve") → advance_line_status()
```

### Problems:

#### Problem 1: No Proper Workflow States
- **Expense Request** punya workflow states: Draft → Pending Review → Approved
- **Internal Charge Request** hanya punya status field: Draft, Pending Approval, Partially Approved, Approved, Rejected
- **Status berubah langsung** ketika approve tanpa workflow transitions

#### Problem 2: Line-Level Approval Without Workflow Transitions
- Setiap line punya `line_status` (Pending L1, Pending L2, Pending L3, Approved, Rejected)
- Tapi **tidak ada workflow transitions per-line**
- Approval advance hanya di `before_workflow_action()` tanpa workflow state management

#### Problem 3: Per-Line Routes Not Properly Integrated
```python
# Di internal_charge_request.py _populate_line_routes()
for line in getattr(self, "internal_charge_lines", []) or []:
    route = get_approval_route(
        line.target_cost_center,  # ← Cost centre per-line
        expense_accounts,
        float(getattr(line, "amount", 0) or 0),
        setting_meta=setting_meta,
    )
    # Routes disimpan di line: level_1_role, level_1_approver, etc
    # TAPI tidak ada workflow enforcement yang comparable ke Expense Request
```

#### Problem 4: Workflow Action Handler Tidak Sesuai Pattern
```python
# internal_charge_request.py before_workflow_action()
def before_workflow_action(self, action, **kwargs):
    if action != "Approve":
        return
    
    # Finds approvable lines based on current user
    for line in approvable_lines:
        _advance_line_status(line, session_user=session_user)
    
    self._sync_status()  # ← Aggregate status dari semua lines
```

**Issue**: Ini TIDAK following Expense Request pattern dimana:
- Expense Request check `level_1_user`, `level_2_user`, `level_3_user`
- Approval advance level by level dengan workflow transitions
- Line-based approval di Internal Charge tidak ada equivalent workflow transition

---

## 3. Key Differences Summary

| Aspect | Expense Request | Internal Charge Request |
|--------|-----------------|------------------------|
| **Document Structure** | Single doc, single cost_center | Single doc, multiple lines per cost_center |
| **Route Resolution** | By source cost_center | Per-line by target_cost_center ✓ |
| **Route Storage** | Document level (level_1_user, level_2_user, level_3_user) | Line level (line.level_1_approver, line.level_2_approver) ✓ |
| **Workflow States** | Proper workflow states (Draft, Pending Review, Approved) ✓ | Only status field, no workflow states ❌ |
| **Approval Enforcement** | Workflow transitions dengan permission check | Before-action hook tanpa workflow transitions ❌ |
| **Level Advancement** | Via workflow conditions dan before_workflow_action | Via before_workflow_action only ❌ |
| **Multi-Cost-Center** | N/A - single cost center | Per-line ✓ (but approval logic doesn't leverage this) |

---

## 4. Rekomendasi Perbaikan

### Option A: Create Dedicated Workflow for Internal Charge (Recommended)
Buat `internal_charge_request_workflow.json` dengan:

1. **States**: Draft, Pending L1 Approval, Pending L2 Approval, Pending L3 Approval, Approved, Rejected
2. **Actions**: Submit, Approve, Reject
3. **Transitions**: Level by level sesuai approval route
4. **Approval Enforcement**: `before_workflow_action()` check per-line routes

#### Advantages:
- Konsisten dengan Expense Request pattern
- Proper state management untuk audit trail
- Better UI/UX dengan workflow state indication

#### Implementation Steps:

**Step 1**: Create workflow JSON
```json
// internal_charge_request_workflow.json
{
  "doctype": "Workflow",
  "document_type": "Internal Charge Request",
  "states": [
    {"state": "Draft", "doc_status": 0, "allow_edit": "All"},
    {"state": "Pending L1 Approval", "doc_status": 1, "allow_edit": ""},
    {"state": "Pending L2 Approval", "doc_status": 1, "allow_edit": ""},
    {"state": "Pending L3 Approval", "doc_status": 1, "allow_edit": ""},
    {"state": "Approved", "doc_status": 1, "allow_edit": ""},
    {"state": "Rejected", "doc_status": 1, "allow_edit": ""}
  ],
  "transitions": [
    // Submit transition based on approval route
    // Approve transitions level by level
  ]
}
```

**Step 2**: Update `before_workflow_action()` 
```python
def before_workflow_action(self, action, **kwargs):
    # Similar to ExpenseRequest pattern:
    # 1. Validate approver based on current_approval_level
    # 2. Check approvable_lines
    # 3. Return early if not authorized
    # 4. Advance level on Approve action
```

**Step 3**: Update `_sync_status()` logic
```python
def _sync_status(self):
    # Map workflow_state to status for compatibility
    # or use workflow_state directly if migrating completely
```

---

### Option B: Keep Line-Based Approval But Improve Consistency
Enhance current line-based approach to be more like Expense Request:

1. **Add workflow_state field** to Internal Charge Request (same as Expense Request)
2. **Map line-level approval** to document-level workflow transitions
3. **Update approval logic** to follow Expense Request pattern more closely

#### Implementation:
```python
def before_workflow_action(self, action, **kwargs):
    if action == "Submit":
        # Set initial approval level based on routes
        self._set_initial_approval_level()
        return
    
    if action == "Approve":
        # Similar to ExpenseRequest.before_workflow_action()
        self._validate_approver_authorization()
        self._advance_approval_level()
```

---

## 5. Checklist for Implementation

### For Option A (Recommended):
- [ ] Create `imogi_finance/imogi_finance/workflow/internal_charge_request_workflow/internal_charge_request_workflow.json`
- [ ] Register workflow in fixtures/workspace.json if needed
- [ ] Update `InternalChargeRequest.before_workflow_action()` to:
  - [ ] Validate Submit action (set initial level)
  - [ ] Validate Approve action (check authorization per-line, similar to ExpenseRequest)
  - [ ] Map to workflow_state transitions
- [ ] Update `_sync_status()` to align workflow_state and status
- [ ] Add workflow_state field to internal_charge_request.json DocType definition
- [ ] Update tests to validate workflow transitions
- [ ] Test multi-cost-center approval scenarios

### For Option B:
- [ ] Add workflow_state field to internal_charge_request.json
- [ ] Update before_workflow_action() to use workflow_state
- [ ] Document mapping between line_status and workflow_state
- [ ] Create utility function to determine next workflow state based on line statuses

---

## 6. Testing Scenarios

For both options:
```python
# Test 1: Multi-cost-center with different approvers
def test_internal_charge_with_different_approvers_per_cc():
    ic = InternalChargeRequest()
    ic.append("internal_charge_lines", {"target_cost_center": "CC-A", "amount": 100})
    ic.append("internal_charge_lines", {"target_cost_center": "CC-B", "amount": 100})
    # CC-A approver: User1 (L1)
    # CC-B approver: User2 (L1)
    # → User1 should only be able to approve CC-A line
    # → User2 should only be able to approve CC-B line

# Test 2: Partial approval workflow
def test_internal_charge_partial_approval():
    ic = InternalChargeRequest(3 lines with different cost centers)
    ic.submit()
    # User1 approves Line 1 & 2
    # Status should be "Partially Approved"
    # User2 approves Line 3
    # Status should be "Approved"

# Test 3: Rejection handling
def test_internal_charge_rejection():
    ic = InternalChargeRequest()
    ic.submit()
    # User1 rejects Line 1
    # Status should be "Rejected"
```

---

## 7. Cost-Centre Awareness

Both Expense Request dan Internal Charge Request harus fully cost-centre aware:

**Expense Request**:
- ✅ Source cost_center determines approver route
- ✅ All items dalam request must share same approval route

**Internal Charge Request** (Needs Fix):
- ✅ Each line targets different cost_center
- ✓ Routes resolved per-line (already implemented)
- ❌ Approval workflow not per-cost-center (needs workflow structure)

Dengan workflow proper, bisa lebih mudah:
- Visualize approval status per cost-center
- Track which cost-center approval pending
- Better audit trail per cost-center
