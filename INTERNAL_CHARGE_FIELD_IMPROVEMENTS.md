# Internal Charge Request - Keterkaitan & Field Improvements

**Tanggal:** 16 Januari 2026  
**Status:** ✅ IMPROVEMENTS IMPLEMENTED

---

## 📋 Keterkaitan Expense Request → Internal Charge Request

### 1. Flow Diagram

```
┌────────────────────────────────────────────────────────────────┐
│                   EXPENSE REQUEST (ER)                         │
│  - allocation_mode: "Allocated via Internal Charge"           │
│  - internal_charge_request: (link to IC)                      │
└────────────────────────────────────────────────────────────────┘
                              │
                              │ User clicks "Generate Internal Charge"
                              │ (Button in ER form)
                              ▼
                    ┌──────────────────────┐
                    │  Backend Function:   │
                    │  create_internal_    │
                    │  charge_from_        │
                    │  expense_request()   │
                    └──────────────────────┘
                              │
                              ├─ Validate: allocation_mode = "Allocated via IC"
                              ├─ Check: ER tidak sudah punya IC
                              ├─ Get: total_amount & expense_accounts dari ER items
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│              INTERNAL CHARGE REQUEST (IC) - CREATED            │
│  - expense_request: [link to ER]                              │
│  - company: [fetched from ER]                                 │
│  - source_cost_center: [from ER.cost_center]                  │
│  - total_amount: [from ER.total_amount]                       │
│  - posting_date: [from ER.request_date]                       │
│  - fiscal_year: [from ER or resolved]                         │
│  - allocation_mode: "Allocated via Internal Charge"           │
│  - internal_charge_lines: [1 starter line → source CC]        │
│    └─ target_cost_center: [ER.cost_center]                    │
│    └─ amount: [ER.total_amount]                               │
└────────────────────────────────────────────────────────────────┘
                              │
                              │ User edits IC lines
                              │ (Split to multiple cost centers)
                              ▼
                    ┌──────────────────────┐
                    │  IC Line Approval    │
                    │  (Per-Cost-Center)   │
                    └──────────────────────┘
                              │
                              │ All lines approved
                              ▼
                    ┌──────────────────────┐
                    │  IC Status:          │
                    │  "Approved"          │
                    └──────────────────────┘
                              │
                              │ Link back to ER
                              ▼
┌────────────────────────────────────────────────────────────────┐
│         EXPENSE REQUEST (ER) - UPDATED                         │
│  - internal_charge_request: [IC-2024-00001]                   │
└────────────────────────────────────────────────────────────────┘
                              │
                              │ ER Approval → Budget Lock
                              ▼
                    ┌──────────────────────┐
                    │  _require_internal_  │
                    │  charge_ready()      │
                    │  - Check IC Approved │
                    │  - Validate totals   │
                    └──────────────────────┘
                              │
                              ▼
                    ┌──────────────────────┐
                    │  _build_allocation_  │
                    │  slices()            │
                    │  - IC line ratios    │
                    │  - Per account       │
                    │  - Per cost center   │
                    └──────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│            BUDGET CONTROL ENTRIES (BCE)                        │
│  For each IC line × each account:                             │
│  - entry_type: RESERVATION                                     │
│  - cost_center: [IC line target CC]                           │
│  - account: [from ER items]                                    │
│  - amount: [IC line amount × account ratio]                   │
│  - ref_doctype: "Expense Request"                             │
│  - ref_name: [ER name]                                        │
└────────────────────────────────────────────────────────────────┘
                              │
                              │ PI Submit
                              ▼
┌────────────────────────────────────────────────────────────────┐
│              JOURNAL ENTRY (Optional)                          │
│  IF internal_charge_posting_mode = "Auto JE on PI Submit":    │
│  - Credit: source_cost_center (ER CC)                         │
│  - Debit: target_cost_centers (IC lines)                      │
│  Purpose: GL reclass (accounting only, not budget)            │
└────────────────────────────────────────────────────────────────┘
```

---

## 2. Field Mapping: ER → IC

### 2.1 Auto-Populated Fields

| IC Field | Source | Type | Notes |
|----------|--------|------|-------|
| **expense_request** | User input | Link | Required, read-only after submit |
| **company** | `ER.company` | Fetch | Auto via `fetch_from`, readonly |
| **source_cost_center** | `ER.cost_center` | Fetch | Auto via `fetch_from`, readonly |
| **total_amount** | `ER.total_amount` | Fetch | Auto via `fetch_from`, readonly |
| **fiscal_year** | `ER.fiscal_year` or resolved | Fetch | Auto via `fetch_from`, readonly |
| **posting_date** | `ER.request_date` or Today | Default | Editable in draft |
| **allocation_mode** | "Allocated via IC" | Default | Hidden, always IC mode |

### 2.2 Backend Logic (create_internal_charge_from_expense_request)

**Source:** [imogi_finance/budget_control/workflow.py](imogi_finance/budget_control/workflow.py#L687-L728)

```python
@frappe.whitelist()
def create_internal_charge_from_expense_request(er_name: str) -> str:
    """
    Creates IC Request from ER with pre-populated fields.
    
    Validations:
    1. enable_internal_charge = true
    2. ER.allocation_mode = "Allocated via Internal Charge"
    3. ER doesn't already have IC linked
    
    Process:
    1. Get total & expense_accounts from ER items
    2. Resolve company from ER.cost_center
    3. Resolve fiscal_year from ER.fiscal_year or current
    4. Create IC with starter line (100% to source CC)
    5. Link IC to ER (ER.internal_charge_request = IC.name)
    """
    settings = utils.get_settings()
    if not settings.get("enable_internal_charge"):
        frappe.throw(_("Internal Charge feature is disabled."))

    request = frappe.get_doc("Expense Request", er_name)
    if getattr(request, "allocation_mode") != "Allocated via Internal Charge":
        frappe.throw(_("Allocation mode must be 'Allocated via Internal Charge'."))

    if getattr(request, "internal_charge_request"):
        return request.internal_charge_request  # Already exists

    total, expense_accounts = accounting.summarize_request_items(
        getattr(request, "items", []) or []
    )
    company = utils.resolve_company_from_cost_center(
        getattr(request, "cost_center")
    )
    fiscal_year = utils.resolve_fiscal_year(
        getattr(request, "fiscal_year", None)
    )

    # Create IC
    ic = frappe.new_doc("Internal Charge Request")
    ic.expense_request = request.name
    ic.company = company
    ic.fiscal_year = fiscal_year
    ic.posting_date = getattr(request, "request_date", None) or frappe.utils.nowdate()
    ic.source_cost_center = getattr(request, "cost_center")
    ic.total_amount = total
    ic.allocation_mode = "Allocated via Internal Charge"

    # Auto-suggest single line to source CC as starting point
    ic.append("internal_charge_lines", {
        "target_cost_center": getattr(request, "cost_center"),
        "amount": total,
    })

    ic.insert(ignore_permissions=True)

    # Link back to ER
    request.db_set("internal_charge_request", ic.name)

    return ic.name
```

---

## 3. Field Attribute Improvements

### 3.1 Internal Charge Request JSON

**File:** [internal_charge_request.json](imogi_finance/imogi_finance/doctype/internal_charge_request/internal_charge_request.json)

#### ✅ Improvements Applied:

| Field | Before | After | Reason |
|-------|--------|-------|--------|
| **expense_request** | Basic Link | + `in_list_view`<br>+ `in_standard_filter`<br>+ `search_index`<br>+ `read_only_depends_on: docstatus==1` | Better searchability, prevent edit after submit |
| **company** | Basic Link | + `fetch_from: expense_request.company`<br>+ `read_only: 1` | Auto-populate from ER, prevent manual change |
| **posting_date** | Basic Date | + `default: Today`<br>+ `read_only_depends_on: docstatus==1` | Default value, lock after submit |
| **fiscal_year** | Basic Link | + `fetch_from: expense_request.fiscal_year`<br>+ `read_only: 1` | Auto-populate from ER |
| **source_cost_center** | Basic Link | + `fetch_from: expense_request.cost_center`<br>+ `read_only: 1`<br>+ `in_list_view: 1` | Auto-populate, show in list |
| **total_amount** | Basic Currency | + `fetch_from: expense_request.total_amount`<br>+ `read_only: 1`<br>+ `in_list_view: 1`<br>+ `bold: 1` | Auto-populate, highlight in UI |
| **allocation_mode** | Editable Select | + `read_only: 1`<br>+ `hidden: 1` | Always "Allocated via IC" for IC docs |
| **internal_charge_lines** | Basic Table | + `cannot_add_rows: false`<br>+ `cannot_delete_rows: false`<br>+ `read_only_depends_on: docstatus==1` | Editable in draft only |
| **status** | Basic Select | + `in_list_view: 1`<br>+ `in_standard_filter: 1`<br>+ `bold: 1` | Better visibility and searchability |
| **workflow_state** | Select type | Changed to `Link`<br>+ `options: Workflow State`<br>+ `allow_on_submit: 1` | Proper workflow integration |

### 3.2 Internal Charge Line JSON

**File:** [internal_charge_line.json](imogi_finance/imogi_finance/doctype/internal_charge_line/internal_charge_line.json)

#### ✅ Improvements Applied:

| Field | Before | After | Reason |
|-------|--------|-------|--------|
| **line_status** | Basic Select | + `read_only: 1`<br>+ `bold: 1` | System-controlled, highlight status |
| **current_approval_level** | Basic Int | + `read_only: 1`<br>+ `hidden: 1` | System field, hide from user |
| **route_snapshot** | Basic Long Text | + `read_only: 1`<br>+ `hidden: 1` | Internal snapshot, hide from UI |
| **level_1_role** | Basic Link | + `read_only: 1`<br>+ `hidden: 1` | Auto-populated, hide from UI |
| **level_1_approver** | Basic Link | + `read_only: 1`<br>+ `hidden: 1` | Auto-populated, hide from UI |
| **level_2_role** | Basic Link | + `read_only: 1`<br>+ `hidden: 1` | Auto-populated, hide from UI |
| **level_2_approver** | Basic Link | + `read_only: 1`<br>+ `hidden: 1` | Auto-populated, hide from UI |
| **level_3_role** | Basic Link | + `read_only: 1`<br>+ `hidden: 1` | Auto-populated, hide from UI |
| **level_3_approver** | Basic Link | + `read_only: 1`<br>+ `hidden: 1` | Auto-populated, hide from UI |
| **approved_by** | Basic Link | (unchanged) `read_only: 1` | Already correct |
| **approved_on** | Basic Datetime | (unchanged) `read_only: 1` | Already correct |

### 3.3 Expense Request JSON

**File:** [expense_request.json](imogi_finance/imogi_finance/doctype/expense_request/expense_request.json)

#### ✅ Improvements Applied:

| Field | Before | After | Reason |
|-------|--------|-------|--------|
| **internal_charge_request** | Basic Link | + `depends_on: allocation_mode=='Allocated via IC'`<br>+ `bold: 1`<br>+ `description` | Show only when relevant, highlight |

---

## 4. Client Script Enhancements

### 4.1 New File: internal_charge_request.js

**Features Implemented:**

#### A) Auto-Fetch from Expense Request
```javascript
// When expense_request is selected, auto-populate:
- company
- source_cost_center
- total_amount
- posting_date (from ER.request_date)
- fiscal_year (from ER or resolved from date)
```

#### B) Status Indicators
```javascript
// Dashboard indicators:
- Link to Expense Request (clickable)
- Status with color coding
- Approval progress (X/Y approved, Z pending)
- Line total validation (warning if mismatch)
```

#### C) Validation
```javascript
// Prevent target_cost_center = source_cost_center
if (row.target_cost_center === frm.doc.source_cost_center) {
  frappe.msgprint("Target CC cannot be same as Source CC");
  frappe.model.set_value(cdt, cdn, 'target_cost_center', '');
}
```

#### D) Custom Buttons
```javascript
// "View Expense Request" button → Navigate to ER
// "View Budget Entries" button → Show BCE list filtered by ER
```

#### E) Real-time Calculations
```javascript
// Calculate line totals on change
// Show warning if sum(line.amount) != total_amount
// Display line status counts
```

---

## 5. Data Flow Summary

### 5.1 Creation Flow

```
USER ACTION                    SYSTEM ACTION
────────────────              ────────────────
1. Create ER                  → Set allocation_mode options
   allocation_mode = "IC"       
                              
2. Submit ER                  → Validate ER ready
                              
3. Click "Generate IC"        → Call create_internal_charge_from_expense_request()
   (Button in ER form)        
                              
4. Backend creates IC         → Auto-populate fields via fetch_from
   - IC Draft created         → company (from ER)
   - Linked to ER             → source_cost_center (from ER.cost_center)
                              → total_amount (from ER.total_amount)
                              → fiscal_year (from ER)
                              → 1 starter line added
                              
5. User edits IC lines        → Client-side validation
   - Split to multiple CCs    → Prevent target = source
   - Adjust amounts           → Real-time total calculation
                              
6. Submit IC                  → Backend validation
                              → _validate_amounts()
                              → _populate_line_routes()
                              
7. Approve IC (per-line)      → Workflow actions
   - L1, L2, L3 approval      → _validate_approve_permission()
                              → _advance_line_status()
                              
8. All lines approved         → status = "Approved"
                              → Update ER link
                              
9. Approve ER                 → _require_internal_charge_ready()
   (Budget Lock)              → Check IC Approved
                              → _build_allocation_slices()
                              → Create Budget Control Entries
                              
10. Submit PI                 → consume_budget_for_purchase_invoice()
                              → Create CONSUMPTION entries
                              → maybe_post_internal_charge_je()
                              → Create Journal Entry (if enabled)
```

### 5.2 Data Dependencies

```
Expense Request
├─ Must have: allocation_mode = "Allocated via Internal Charge"
├─ Must have: items with expense_account
├─ Optional: internal_charge_request link
└─ Status: Submitted + Approved

Internal Charge Request
├─ Must link to: Expense Request
├─ Auto-fetch from ER:
│  ├─ company
│  ├─ source_cost_center
│  ├─ total_amount
│  └─ fiscal_year
├─ Must have: ≥1 internal_charge_line
├─ Validation: sum(line.amount) = total_amount
└─ Status: All lines Approved

Budget Control Entry
├─ Created when: ER Approval (RESERVATION)
├─ Uses: _build_allocation_slices(ER, IC)
├─ Reference: ref_doctype="Expense Request"
└─ Per entry: cost_center × account from IC allocation

Journal Entry (Optional)
├─ Created when: PI Submit (if Auto JE enabled)
├─ Purpose: GL reclass only
├─ Credit: source_cost_center
└─ Debit: target_cost_centers (from IC lines)
```

---

## 6. Testing Checklist

### 6.1 Field Auto-Population

- [ ] Create ER with allocation_mode = "Allocated via Internal Charge"
- [ ] Click "Generate Internal Charge" button
- [ ] Verify IC fields auto-populated:
  - [ ] company (from ER.company)
  - [ ] source_cost_center (from ER.cost_center)
  - [ ] total_amount (from ER.total_amount)
  - [ ] fiscal_year (from ER or resolved)
  - [ ] posting_date (from ER.request_date)
  - [ ] 1 starter line with source CC

### 6.2 Field Attributes

- [ ] Verify expense_request is:
  - [ ] Searchable in list view
  - [ ] Filterable
  - [ ] Read-only after submit
- [ ] Verify company, source_cost_center, total_amount are:
  - [ ] Auto-populated from ER
  - [ ] Read-only (cannot manual edit)
- [ ] Verify allocation_mode is hidden
- [ ] Verify status shows in list view
- [ ] Verify workflow_state integrates with workflow

### 6.3 Client Script Features

- [ ] Dashboard shows:
  - [ ] Link to ER
  - [ ] Status with color
  - [ ] Approval progress
  - [ ] Line total validation
- [ ] Custom buttons work:
  - [ ] "View Expense Request" navigates correctly
  - [ ] "View Budget Entries" filters correctly
- [ ] Line validation:
  - [ ] Prevents target_cost_center = source_cost_center
  - [ ] Shows warning if line total ≠ total_amount
- [ ] Real-time calculations update

### 6.4 Integration Testing

- [ ] Full flow: ER → IC → Approval → Budget Lock → PI
- [ ] Verify Budget Control Entries created correctly
- [ ] Verify allocation slices match IC lines
- [ ] Verify Journal Entry posts correctly (if enabled)
- [ ] Verify ref_doctype/ref_name in BCE

---

## 7. Before/After Comparison

### 7.1 User Experience

| Aspect | Before | After |
|--------|--------|-------|
| **Field Population** | Manual entry for all fields | Auto-populated from ER |
| **Validation** | Backend only | Real-time + backend |
| **Visibility** | Basic fields | Status indicators, progress bars |
| **Navigation** | Manual URL typing | Custom buttons |
| **Editing** | No restrictions | Smart read-only based on state |
| **Searchability** | Limited | Full-text search, filters |

### 7.2 Developer Experience

| Aspect | Before | After |
|--------|--------|-------|
| **Field Attributes** | Minimal | Comprehensive (readonly, fetch, depends_on) |
| **Client Script** | Missing | Full featured |
| **Data Integrity** | Rely on backend | Multi-layer validation |
| **Debugging** | Manual queries | Dashboard indicators |
| **Documentation** | Code comments only | Complete flow docs |

---

## 8. Migration Notes

### 8.1 JSON Changes Only

✅ **Safe:** All changes are field attribute additions/modifications in JSON files.

- No database schema changes
- No data migration needed
- Backward compatible
- Can be deployed directly

### 8.2 Client Script is New

✅ **Safe:** New file creation only.

- No existing JS file modified
- Won't break existing functionality
- Can be deployed directly

### 8.3 Deployment Steps

1. **Commit changes:**
   ```bash
   git add imogi_finance/imogi_finance/doctype/internal_charge_request/
   git add imogi_finance/imogi_finance/doctype/internal_charge_line/
   git add imogi_finance/imogi_finance/doctype/expense_request/expense_request.json
   git commit -m "feat: improve IC field attributes and add client script"
   ```

2. **Deploy to server:**
   ```bash
   bench --site [site-name] migrate
   bench --site [site-name] clear-cache
   ```

3. **Test in staging first:**
   - Create new IC from ER
   - Verify auto-population
   - Test approval flow
   - Check Budget Control Entries

4. **Deploy to production** (after staging success)

---

## 9. Future Enhancements

### 9.1 Potential Improvements

| Priority | Enhancement | Description |
|----------|-------------|-------------|
| 🟢 LOW | IC Templates | Pre-defined allocation templates for common scenarios |
| 🟡 MEDIUM | Bulk IC Creation | Create multiple ICs from list of ERs |
| 🟡 MEDIUM | IC Dashboard | Summary view of all IC requests with charts |
| 🔴 HIGH | Budget Validation on IC Approval | Check budget availability before IC approval |
| 🟢 LOW | IC History Report | Track IC changes and approval history |

### 9.2 Recommended Next Steps

1. ✅ **Current PR:** Field improvements + client script
2. 🔴 **Next PR:** Budget validation on IC approval (from analysis doc)
3. 🟡 **Future PR:** Flexible JE posting modes
4. 🟢 **Future PR:** IC allocation reports

---

## 10. Summary

### What Changed

✅ **Internal Charge Request JSON:**
- 10 field attributes improved
- Added fetch_from for auto-population
- Added depends_on, read_only conditions
- Better visibility (in_list_view, bold)

✅ **Internal Charge Line JSON:**
- 9 field attributes improved
- Hidden internal fields (route_snapshot, approver fields)
- Made system fields read-only

✅ **Expense Request JSON:**
- 1 field improved (internal_charge_request)
- Added conditional visibility

✅ **New Client Script:**
- Auto-fetch ER details
- Real-time validation
- Dashboard indicators
- Custom action buttons
- Line total calculations

### Impact

- **Better UX:** Auto-population reduces manual entry
- **Data Integrity:** Multi-layer validation prevents errors
- **Visibility:** Clear status indicators and progress tracking
- **Efficiency:** Custom buttons for quick navigation
- **Maintainability:** Well-documented field purposes

### Testing Required

1. Auto-population from ER
2. Field attribute behavior (readonly, fetch_from, depends_on)
3. Client script features (indicators, buttons, validation)
4. End-to-end flow (ER → IC → Approval → Budget → PI)

---

**Document Version:** 1.0  
**Created:** January 16, 2026  
**Status:** ✅ Improvements Implemented
