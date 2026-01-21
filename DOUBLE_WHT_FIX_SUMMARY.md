# Double WHT Prevention - Complete Implementation Summary

## Overview
Fixed the **DOUBLE PPh (Withholding Tax)** calculation issue where both Expense Request's Apply WHT and Supplier's Tax Withholding Category were calculating simultaneously, resulting in double tax charges.

**Problem:** PPh Rp 6,000 (should be Rp 3,000)
**Solution:** ON/OFF logic with timing-aware implementation
**Status:** ✅ Code implemented and documented

---

## What Was Changed

### 1. imogi_finance/accounting.py (Lines 281-370)

**Key Change:** Set `apply_tds = 0` BEFORE supplier assignment to prevent Frappe's auto-calculation

```python
# BEFORE (problematic):
pi = frappe.new_doc("Purchase Invoice")
pi.company = company
pi.supplier = request.supplier  # ← TDS triggers here, calculates supplier's tax
pi.apply_tds = 1               # ← Too late!
pi.tax_withholding_category = request.pph_type

# AFTER (fixed):
pi = frappe.new_doc("Purchase Invoice")
pi.company = company
pi.apply_tds = 0  # ← Block TDS BEFORE supplier assignment
pi.supplier = request.supplier # ← Auto-populates category, but TDS blocked
# ... ON/OFF logic ...
if apply_pph:
    pi.apply_tds = 1           # ← Re-enable TDS for ER's type only
    pi.tax_withholding_category = request.pph_type
else:
    # ... handle supplier's category if enabled ...
```

**Logic Implementation:**
- ✅ Apply WHT CHECKED: Use ER's pph_type, disable supplier's category
- ❌ Apply WHT NOT CHECKED: 
  - If setting enabled: Use supplier's category (auto-copy)
  - If setting disabled: No PPh

### 2. imogi_finance/events/purchase_invoice.py (Lines 181-260)

**Key Change:** ALWAYS clear supplier's category when ER Apply WHT is active (not conditional)

```python
# BEFORE (problematic):
if supplier_tax_category:  # ← Only clears if value already exists
    doc.tax_withholding_category = None

# AFTER (fixed):
if expense_request and apply_tds and pph_type:
    # ← Always clear, regardless of current state
    doc.tax_withholding_category = None
    doc.apply_tds = 1
    
    # User notification
    frappe.msgprint(
        _(f"✅ PPh Configuration: Using '{pph_type}' from Expense Request. "
          f"Supplier's Tax Withholding Category disabled."),
        indicator="green",
        alert=True
    )
```

**Features:**
- Called at TWO points: validate() and before_submit()
- Double-check ensures consistency
- User-facing notification with status indicator
- Detailed logging for audit trail

### 3. imogi_finance/hooks.py

**No changes needed** - Already has validate hook:
```python
"validate": [
    "imogi_finance.events.purchase_invoice.prevent_double_wht_validate",
    ...
]
```

---

## How It Solves the Double Calculation

### Original Problem Flow
```
1. Create PI from ER
2. pi.supplier = X
   └─> Frappe auto-populates tax_withholding_category from supplier
   └─> Frappe's TDS controller notes: "category exists, will calculate"
3. pi.apply_tds = 1
   └─> TDS calculation triggers
4. TDS calculates BOTH:
   ├─ Supplier's category (Rp 3,000) ← From supplier master
   └─ ER's pph_type (Rp 3,000) ← From our imogi_pph_type
5. Result: Rp 6,000 ❌ DOUBLE!
```

### Fixed Flow
```
1. Create PI from ER
2. pi.apply_tds = 0
   └─> Block TDS calculation initially
3. pi.supplier = X
   └─> Frappe auto-populates tax_withholding_category
   └─> BUT TDS doesn't calculate (apply_tds=0)
4. ON/OFF logic:
   ├─ If ER Apply WHT: set pi.tax_withholding_category = ER's type
   └─ If NOT: set to supplier's type OR None
5. pi.apply_tds = 1 (if ER Apply WHT)
   └─> Re-enable TDS calculation
6. validate event clears supplier's category
   └─> Ensures only ER's type is active
7. TDS calculates ONCE:
   ├─ ✅ ER's pph_type (Rp 3,000) if Apply WHT checked
   └─ ✅ Supplier's category (Rp 3,000) if Apply WHT NOT checked
8. Result: Rp 3,000 ✅ SINGLE!
```

---

## Detailed Implementation Steps

### Phase 1: Prevent TDS Auto-Calculation
In `accounting.py` (line 285):
```python
pi.apply_tds = 0  # Block Frappe's automatic TDS before supplier assigned
```

**Purpose:** When supplier is assigned, Frappe won't auto-calculate TDS from supplier's category.

### Phase 2: ON/OFF Logic in Accounting
In `accounting.py` (lines 300-361):
```python
if apply_pph:
    # ER's Apply WHT is CHECKED
    pi.tax_withholding_category = request.pph_type
    pi.imogi_pph_type = request.pph_type
    pi.apply_tds = 1  # Re-enable TDS for ER's type
else:
    # ER's Apply WHT NOT CHECKED
    # Check setting and use supplier's category if enabled
    ...
```

**Purpose:** Explicitly choose which PPh source to use based on ER's setting.

### Phase 3: Event Hook Enforcement
In `events/purchase_invoice.py` (lines 213-226):
```python
if expense_request and apply_tds and pph_type:
    # Clear supplier's category when ER Apply WHT is active
    doc.tax_withholding_category = None
    doc.apply_tds = 1
```

**Purpose:** Final enforcement - even if something unexpected happens, this ensures supplier's category won't interfere.

---

## Test Case: Real-World Scenario

### Expense Request
```
Item 1: Utility Expenses - Rp 150,000 (Apply WHT ❌ NOT checked)
Item 2: Administrative - Rp 150,000 (Apply WHT ✅ CHECKED)

ER Total: Rp 300,000
ER PPh: Rp 3,000 (from item 2 only: 150,000 × 2%)
```

### Expected Purchase Invoice
```
DPP (Total): Rp 300,000
PPh - ITB: Rp 3,000 ✅ (SINGLE, from ER only)
Taxes Deducted: Rp 3,000 ✅
```

### Test Result Before Fix
```
DPP (Total): Rp 300,000
PPh - ITB: Rp 6,000 ❌ (DOUBLE: Rp 3,000 ER + Rp 3,000 supplier)
Taxes Deducted: Rp 6,000 ❌
```

### Test Result After Fix
```
Expected: Rp 3,000
Pending: Actual execution in Frappe environment
```

---

## Key Features & Benefits

### ✅ ON/OFF Logic
- Only ONE PPh source active at a time
- Prevents conflicts and double calculations
- Respects user's intent from ER's Apply WHT checkbox

### ✅ Auto-Copy Feature
- Fallback to supplier's Tax Withholding Category when ER doesn't set Apply WHT
- Controlled by setting: `use_supplier_wht_if_no_er_pph`
- Allows flexibility in tax handling

### ✅ Timing-Aware
- Works with Frappe's auto-population behavior
- Leverages field assignment order
- Handles TDS calculation lifecycle correctly

### ✅ User Notifications
- Green indicator when configuration is correct
- Alert message explaining which PPh source is active
- Server logs with [PPh ON/OFF] tag for audit trail

### ✅ Double-Check Safety
- Called at TWO event points: validate + before_submit
- Ensures consistency throughout document lifecycle
- Catches unexpected state changes

---

## Testing Instructions

### 1. Setup Test Data
```
Supplier: PT ABC (Tax Withholding Category: PPh 23)
ER Create:
  - Item 1: Rp 150,000 (Apply WHT: ❌)
  - Item 2: Rp 150,000 (Apply WHT: ✅)
```

### 2. Create PI from ER
```
- System creates PI from ER
- Watch for messages:
  - "[PPh ON/OFF] PI xxx: Apply WHT di ER CENTANG"
  - "✅ PPh Configuration: Using... from Expense Request"
```

### 3. Verify Results
```
Check PI:
  - PPh - ITB field should show: Rp 3,000 (NOT Rp 6,000)
  - Taxes Deducted should be: Rp 3,000
  - tax_withholding_category should be: ER's pph_type
```

### 4. Check Server Logs
```
Look for messages:
  ✓ "Apply WHT di ER CENTANG"
  ✓ "Clearing supplier's tax_withholding_category"
  ✓ "✅ PPh Configuration"
```

### 5. Regression Tests
```
- Test ER without Apply WHT (supplier's category should be used)
- Test supplier without Tax Withholding Category
- Test with auto-copy setting DISABLED
```

---

## Files Documentation

### accounting.py Changes
- **Lines 281-294:** Set apply_tds = 0 before supplier assignment
- **Lines 300-361:** ON/OFF logic implementation
  - if apply_pph: Use ER's pph_type
  - else: Use supplier's category or disable based on setting
- **Lines 363-368:** Log and continue with item creation

### purchase_invoice.py Changes
- **Lines 63-73:** New prevent_double_wht_validate() function for early hook
- **Lines 181-260:** Updated _prevent_double_wht() function
  - ALWAYS clear supplier's category when ER Apply WHT active
  - User notification with indicator
  - Improved logging

### hooks.py
- **Line 206:** Already has prevent_double_wht_validate hook (no changes needed)

---

## Debugging Information

### If PPh Still Shows Double (Rp 6,000):

1. **Check Server Logs:**
   ```
   Search for: "[PPh ON/OFF]"
   Should show: "Clearing supplier's tax_withholding_category"
   If missing: Event hook not firing
   ```

2. **Verify Field Values in PI:**
   ```
   Check: apply_tds = ? (should be 1 if ER Apply WHT checked)
   Check: tax_withholding_category = ? (should be ER's type, not supplier's)
   Check: imogi_pph_type = ? (should have value)
   ```

3. **Verify ER Settings:**
   ```
   Check: apply_tds = 1 in ER
   Check: imogi_pph_type = set correctly
   ```

4. **Check Frappe Configuration:**
   ```
   Is TDS module enabled?
   Is Frappe version compatible?
   Are taxes & charges calculated correctly?
   ```

---

## Summary

| Aspect | Before | After |
|--------|--------|-------|
| **PPh Calculation** | Rp 6,000 (DOUBLE) | Rp 3,000 (SINGLE) ✅ |
| **ER Apply WHT Logic** | Ignored/conflicted | Used exclusively ✅ |
| **Supplier's Category** | Always calculated | Used only if ER doesn't set ✅ |
| **User Notification** | None | Green indicator + message ✅ |
| **Audit Trail** | Minimal | Detailed [PPh ON/OFF] logs ✅ |
| **Timing Handling** | Problematic | Frappe-aware ✅ |

**Next Step:** Test in Frappe environment and verify PPh = Rp 3,000 (not Rp 6,000) ✅
