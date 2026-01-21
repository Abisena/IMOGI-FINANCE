# MIXED Mode - Explicit Item-Level apply_tds Fix

## Problem (User Test Result)

User tested MIXED Apply WHT with:
- Item 1: Utility Expenses, Rp 200,000 (Apply WHT ✓)
- Item 2: Administrative Expenses, Rp 200,000 (Apply WHT ✗)

**Expected:** Rp 4,000 PPh (only Item 1)
**Got:** Rp 8,000 PPh (BOTH items taxed!) ✗

## Root Cause

In item creation loop, the code only SET `apply_tds = 1` for items WITH Apply WHT, but did NOT explicitly SET `apply_tds = 0` for items WITHOUT Apply WHT.

```python
# BEFORE (INCOMPLETE):
if not has_item_level_pph or getattr(item, "is_pph_applicable", 0):
    pi_item_doc.apply_tds = 1
# ← Missing: else clause to set apply_tds = 0
```

**Why This Caused the Issue:**
When PI-level `apply_tds = 1`, Frappe's default behavior is to apply tax to ALL items. Item-level `apply_tds` flags should override this, but:
- If an item's `apply_tds` is **not set** (undefined), Frappe treats it as "inherit from PI level"
- Result: ALL items get taxed because PI-level is 1

**What Should Happen:**
- Items with Apply WHT: `apply_tds = 1` (explicitly set)
- Items WITHOUT Apply WHT: `apply_tds = 0` (MUST be explicitly set)

## Solution

Add explicit `else` clause to set `apply_tds = 0` for items without Apply WHT:

```python
# AFTER (COMPLETE):
if not has_item_level_pph or getattr(item, "is_pph_applicable", 0):
    pi_item_doc.apply_tds = 1
else:
    # EXPLICITLY set to 0 for items WITHOUT Apply WHT
    pi_item_doc.apply_tds = 0
```

## Implementation

### File: `imogi_finance/accounting.py` (Line 433-441)

```python
pi_item_doc = pi.append("items", pi_item)
if apply_pph and hasattr(pi_item_doc, "apply_tds"):
    # CRITICAL: Explicitly set apply_tds for EACH item
    # In MIXED mode: Only items with is_pph_applicable=1 get apply_tds=1
    # In CONSISTENT mode: All items follow the same rule
    if not has_item_level_pph or getattr(item, "is_pph_applicable", 0):
        pi_item_doc.apply_tds = 1
    else:
        # EXPLICITLY set to 0 for items WITHOUT Apply WHT
        pi_item_doc.apply_tds = 0
```

## Logic Breakdown

### Scenario: MIXED Apply WHT

**ER State:**
- Item 1: Utility Expenses, Rp 200,000, `is_pph_applicable = 1` ✓
- Item 2: Admin Expenses, Rp 200,000, `is_pph_applicable = 0` ✗
- `has_item_level_pph = True` (because there are items with PPh)

**Item 1 Processing:**
```python
item = Item 1 (is_pph_applicable = 1)
if not True or 1:  # not has_item_level_pph or is_pph_applicable
    # = if False or 1
    # = if True
    pi_item_doc.apply_tds = 1  ✓
```

**Item 2 Processing (BEFORE FIX):**
```python
item = Item 2 (is_pph_applicable = 0)
if not True or 0:  # not has_item_level_pph or is_pph_applicable
    # = if False or 0
    # = if False
    # ← Nothing happens, apply_tds stays undefined
    # ← Frappe interprets as "inherit from PI level = 1"
    # ❌ RESULT: Item 2 gets taxed even though it shouldn't
```

**Item 2 Processing (AFTER FIX):**
```python
item = Item 2 (is_pph_applicable = 0)
if not True or 0:  # not has_item_level_pph or is_pph_applicable
    # = if False
    pi_item_doc.apply_tds = 1
else:
    pi_item_doc.apply_tds = 0  ✓ EXPLICITLY SET TO 0
    # ✓ RESULT: Item 2 is NOT taxed
```

## Expected Behavior After Fix

### Test Case: MIXED Apply WHT

**ER:**
- Item 1: Rp 200,000 (Apply WHT ✓)
- Item 2: Rp 200,000 (Apply WHT ✗)
- Expected PPh: Rp 4,000

**PI After Fix:**
```
Items:
  Item 1:
    - Amount: Rp 200,000
    - apply_tds: 1 ✓ (explicitly set)
    - Result: Taxed
  
  Item 2:
    - Amount: Rp 200,000
    - apply_tds: 0 ✓ (explicitly set)
    - Result: NOT taxed

Purchase Taxes and Charges:
  Type: Actual
  Account: PPh - ITB
  Tax Rate: 2%
  Amount: Rp 4,000 (2% of Rp 200,000)
  Total: Rp 200,000 × 2% = Rp 4,000 ✓

Grand Total: Rp 396,000
  = Rp 400,000 (subtotal) - Rp 4,000 (PPh withheld)
```

## Comparison: Before vs After

| Aspect | Before Fix | After Fix |
|--------|-----------|-----------|
| Item 1 apply_tds | 1 ✓ | 1 ✓ |
| Item 2 apply_tds | undefined (inherits 1) ❌ | 0 (explicit) ✓ |
| PPh Calculated | Rp 8,000 (both items) ❌ | Rp 4,000 (item 1 only) ✓ |
| Grand Total | Rp 392,000 ❌ | Rp 396,000 ✓ |

## Key Lesson

**Frappe's Item-Level apply_tds Behavior:**
- `apply_tds = 1`: Item is taxed
- `apply_tds = 0`: Item is NOT taxed
- `apply_tds = undefined/null`: Item **inherits from PI level**

**Therefore:**
- In MIXED mode, we MUST explicitly set BOTH 1 and 0
- Cannot rely on "not setting" as equivalent to 0
- Explicit is better than implicit

## Complete MIXED Mode Flow (Corrected)

```
1. Create ER with MIXED Apply WHT
   ↓
2. accounting.py detects has_mixed_pph = True
   ↓
3. Set PI: apply_tds=1, tax_withholding_category=request.pph_type
   ↓
4. For each item:
   - Item WITH Apply WHT → apply_tds=1
   - Item WITHOUT Apply WHT → apply_tds=0 (EXPLICIT)
   ↓
5. Event hook clears supplier category
   ↓
6. PI saved
   ↓
7. Frappe TDS calculates:
   - Sees PI apply_tds=1 → Activate TDS
   - For Item 1: apply_tds=1 → Tax it
   - For Item 2: apply_tds=0 → Skip it
   ↓
8. Result: Only Item 1 taxed, Rp 4,000 PPh ✓
```

## Testing Checklist

- [x] Issue identified: Both items taxed (Rp 8,000)
- [x] Root cause found: apply_tds not explicitly set to 0
- [x] Fix implemented: Added else clause
- [x] Syntax verified: No errors
- [ ] User to test: Create new PI from ER with MIXED Apply WHT
- [ ] Expected: Only Item 1 taxed (Rp 4,000 PPh total)
- [ ] Verify: Item 2 NOT taxed (apply_tds=0 visible if checked)

---

**Related Files:**
- [MIXED_MODE_PPH_FINAL_FIX.md](MIXED_MODE_PPH_FINAL_FIX.md) - Previous fix (apply_tds=1 at PI level)
- This fix completes the MIXED mode implementation
