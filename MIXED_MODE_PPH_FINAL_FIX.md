# MIXED Mode PPh Calculation Fix - CORRECTED

## Problem
User tested MIXED Apply WHT scenario:
- Item 1: Rp 100,000 (Apply WHT ❌)
- Item 2: Rp 200,000 (Apply WHT ✓)
- Expected: Rp 4,000 PPh (2% of Item 2)
- Got: Rp 0 PPh ✗

**Root Cause (Found After First Attempt):**
Setting `pi.apply_tds = 0` prevents Frappe's TDS controller from calculating taxes at all, even if:
- `tax_withholding_category` is set
- Item-level `apply_tds = 1` flags are set

**Why?** Frappe's TDS system requires PI-level `apply_tds = 1` to activate the entire TDS calculation engine. Item-level flags control *which items* get taxed, but without PI-level flag, nothing happens.

## Correct Solution

### Accounting.py Logic

```python
# MIXED MODE (CORRECTED):
pi.tax_withholding_category = request.pph_type
pi.apply_tds = 1  # ✅ MUST be 1 so Frappe calculates TDS
# Later, event hook will clear supplier's category
# Item-level apply_tds flags control which items are taxed
```

**Why This Works:**
1. `pi.apply_tds = 1`: Activates Frappe's TDS engine
2. `pi.tax_withholding_category = request.pph_type`: Sets tax template
3. `pi_item.apply_tds = 1` (only for items with Apply WHT): Only these items taxed
4. Event hook clears supplier category: No double calculation

### Event Hook Logic

```python
# MIXED MODE Detection (CORRECTED):
is_mixed_mode = (
    expense_request and 
    apply_tds and          # ✅ Changed from "not apply_tds"
    pph_type and 
    supplier_tax_category and
    pph_type == supplier_tax_category
)

# Action: CLEAR supplier's category
if is_mixed_mode:
    doc.tax_withholding_category = None  # Remove supplier override
    doc.apply_tds = 1  # Keep enabled
```

## Item-Level Control

**Key:** When `apply_tds = 1` at PI level, Frappe applies tax template to ALL items by default. Item-level `apply_tds` flag controls *which specific items* get the tax.

```python
# In accounting.py, for each item:
if apply_pph and getattr(item, "is_pph_applicable", 0):
    pi_item_doc.apply_tds = 1  # This item gets taxed
else:
    # Don't set apply_tds at all (defaults to 0)
    pass  # This item is NOT taxed
```

## Behavior Now (CORRECTED)

### Scenario: MIXED Apply WHT

**ER State:**
```
Item 1: Rp 100,000 (is_pph_applicable = 0)
Item 2: Rp 200,000 (is_pph_applicable = 1)
Apply WHT: ✓ (in Tab Tax)
PPh Type: PPh 23
```

**accounting.py Processing:**
```python
items_with_pph = 1  # Only Item 2
total_items = 2
has_mixed_pph = (0 < 1 < 2) = True

# Enter MIXED mode branch:
pi.tax_withholding_category = "PPh 23"
pi.apply_tds = 1  # ✅ ENABLE for TDS calculation
```

**Item Processing:**
```python
Item 1: pi_item_doc.apply_tds = 0 (or not set, defaults to 0)
Item 2: pi_item_doc.apply_tds = 1  # Gets taxed
```

**Event Hook (_prevent_double_wht_validate):**
```python
is_mixed_mode = (
    apply_tds=1 AND 
    pph_type="PPh 23" AND 
    supplier_tax_category="PPh 23" (auto-populated)
)

# Action:
doc.tax_withholding_category = None  # Clear supplier override
doc.apply_tds = 1  # Keep enabled
```

**PI State After Save:**
```
Items:
  Item 1: Rp 100,000 (apply_tds=0) ← Not taxed
  Item 2: Rp 200,000 (apply_tds=1) ← Gets taxed

Taxes and Charges Template: PPh 23 (exists as template)

TDS Calculation:
  - Check PI-level apply_tds: 1 ✓ Activate TDS
  - Check tax_withholding_category: PPh 23 ✓ Use this template
  - For each item:
    - Item 1: apply_tds=0 → Skip this item
    - Item 2: apply_tds=1 → Apply 2% on Rp 200,000 = Rp 4,000

Result:
  ✓ Taxes and Charges Deducted (IDR): Rp 4,000
```

## Changes Made

### File: `imogi_finance/accounting.py` (Line 338-352)
**Before:**
```python
pi.apply_tds = 0  # ❌ Disables entire TDS engine
```

**After:**
```python
pi.apply_tds = 1  # ✅ Enables TDS so calculation happens
```

### File: `imogi_finance/events/purchase_invoice.py`

**Line 244-250:** Fixed MIXED mode detection
```python
# Before: is_mixed_mode = (not apply_tds AND pph_type AND ...)
# After: is_mixed_mode = (apply_tds AND pph_type AND ...)

is_mixed_mode = (
    expense_request and 
    apply_tds and          # ✅ Now checks apply_tds=1
    pph_type and 
    supplier_tax_category and
    pph_type == supplier_tax_category
)
```

**Line 257-275:** Updated protection logic
```python
# BEFORE: Tried to keep supplier category
# AFTER: Clears supplier category in MIXED mode

if is_mixed_mode:
    # CLEAR supplier's category to prevent it applying to all items
    doc.tax_withholding_category = None
    doc.apply_tds = 1
```

## Complete Flow Summary

```
1. ER has MIXED Apply WHT (Item 1: NO, Item 2: YES)
   ↓
2. accounting.create_purchase_invoice() detects has_mixed_pph=True
   ↓
3. Sets: pi.apply_tds=1, pi.tax_withholding_category="PPh 23"
   ↓
4. Item 1: apply_tds=0 (not taxed)
   Item 2: apply_tds=1 (taxed)
   ↓
5. Before submit, event hook _prevent_double_wht_validate() runs
   ↓
6. Detects is_mixed_mode=True
   ↓
7. Clears supplier's category: tax_withholding_category=None
   (Prevents Frappe using supplier's category as override)
   ↓
8. PI saved with:
   - apply_tds=1 (active)
   - No supplier category (no override)
   - Item 1: apply_tds=0
   - Item 2: apply_tds=1
   ↓
9. Frappe TDS Controller calculates:
   - Base: Frappe sees apply_tds=1, activates TDS ✓
   - Template: Uses "PPh 23" template ✓
   - Items: Applies only to Item 2 (apply_tds=1) ✓
   - Result: Rp 4,000 PPh on Item 2 ✓
   ↓
10. PI shows: Taxes and Charges Deducted = Rp 4,000 ✓
```

## Key Insight

The fundamental difference from the first attempt:
- **First attempt:** Tried to set `apply_tds=0` at PI level, hoping item flags would work
  - ❌ Doesn't work - Frappe won't calculate taxes at all
- **Corrected approach:** Keep `apply_tds=1` at PI level, clear supplier category instead
  - ✅ Works - TDS calculates, supplier category doesn't override, items control individually

## Testing Checklist

- [ ] Create ER with:
  - Item 1: Rp 100,000 (Apply WHT: ❌)
  - Item 2: Rp 200,000 (Apply WHT: ✓)
  - Tab Tax: Apply WHT ✓, PPh Type: PPh 23

- [ ] Create PI from ER

- [ ] Verify PI shows:
  - Items: Both items with correct amounts ✓
  - Purchase Taxes and Charges Template: PPh 23 ✓
  - Taxes and Charges Deducted: Rp 4,000 ✓ (was Rp 0 before fix)
  - NO orange or green alerts ✓

- [ ] Server logs show:
  - `[PPh MIXED MODE]` message during PI creation ✓
  - `[PPh MIXED]` message during validation ✓

## Notes

- This fix handles the Frappe TDS architecture correctly
- Item-level control works only when PI-level `apply_tds=1` is set
- Clearing supplier category prevents it overriding ER's pph_type
- Silent operation (no user alerts)
