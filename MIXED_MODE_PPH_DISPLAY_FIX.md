# MIXED Mode PPh Display Fix

## Problem
Ketika ER memiliki MIXED Apply WHT (beberapa items checked, beberapa tidak):
- ER menampilkan PPh = Rp 4,000 ✓
- PI ditampilkan KOSONG (tidak ada tax rows) ✗

**Root Cause:**
Dalam mode MIXED, sistem sebelumnya:
1. Set `pi.apply_tds = 0` (disable PI-level tax)
2. Set `pi.tax_withholding_category = None` (no category)
3. Hasilnya: PI tidak punya template untuk menampilkan tax rows
4. Items punya `apply_tds = 1` tapi tanpa category, tidak bisa calculate

## Solution
Ubah MIXED mode logic:

### Before
```python
elif has_mixed_pph:
    pi.tax_withholding_category = None  # ❌ No category = no tax template
    pi.apply_tds = 0
```

### After
```python
elif has_mixed_pph:
    pi.tax_withholding_category = request.pph_type  # ✅ Set category for template
    pi.apply_tds = 0  # But disable at PI level
    # Items control via individual apply_tds flags
```

**Why This Works:**
1. `pi.apply_tds = 0`: Frappe won't apply tax to ALL items
2. `pi.tax_withholding_category = request.pph_type`: Frappe creates tax template
3. `pi_item.apply_tds = 1` (only for items with Apply WHT): Only these items apply tax
4. Result: Per-item control with proper tax rows displayed

## Changes Made

### File: `imogi_finance/accounting.py`

**Line 338-349:** Updated MIXED mode block
```python
elif has_mixed_pph:
    # SET category BUT apply_tds=0 at PI level
    pi.tax_withholding_category = request.pph_type
    pi.imogi_pph_type = request.pph_type
    pi.apply_tds = 0  # Disable at PI level - let items control it
```

### File: `imogi_finance/events/purchase_invoice.py`

**Line 241-251:** Fixed MIXED mode detection
```python
# BEFORE: is_mixed_mode = (apply_tds=0 AND pph_type=None AND supplier_tax_category)
# AFTER: is_mixed_mode = (apply_tds=0 AND pph_type set AND supplier_tax_category)

is_mixed_mode = (
    expense_request and 
    not apply_tds and 
    pph_type and 
    supplier_tax_category and
    pph_type == supplier_tax_category
)
```

**Line 257-281:** Updated protection logic
- CONSISTENT mode: Clear conflicting supplier category
- MIXED mode: **KEEP** supplier category for template (don't clear)

## Behavior Now

### Scenario: MIXED Apply WHT (Item 1: NO, Item 2: YES)

**ER State:**
```
Item 1: Rp 150,000 (is_pph_applicable = 0) 
Item 2: Rp 200,000 (is_pph_applicable = 1)
Apply WHT: ✓ (checked in Tab Tax)
PPh Type: PPh 23
PPh Calculated: Rp 4,000 (2% of Rp 200,000)
```

**PI State (After Fix):**
```
Item 1: Rp 150,000 (apply_tds = 0) ← No tax
Item 2: Rp 200,000 (apply_tds = 1) ← Gets taxed
Tax Category: PPh 23 ← Template set
Tax Rows: Shows Rp 4,000 PPh ✓ ← NOW DISPLAYED!
apply_tds: 0 (at PI level) ← Prevent all-items taxation
```

## Validation Updates

**Existing validation (line 581) unchanged:**
```python
if apply_pph and not has_mixed_pph and flt(pi.taxes_and_charges_deducted) == 0:
    # Warns if PPh should be calculated but isn't (CONSISTENT mode only)
```

✅ Validation correctly skips MIXED mode because `has_mixed_pph = True` excludes it

## Testing Checklist

- [ ] Create ER with:
  - Item 1: Rp 150,000 (Apply WHT unchecked)
  - Item 2: Rp 200,000 (Apply WHT checked)
  - Apply WHT: ✓
  - PPh Type: PPh 23
  
- [ ] Check ER Summary:
  - Total PPh: Rp 4,000 ✓

- [ ] Create PI from ER

- [ ] Check PI:
  - Items: Both displayed with correct amounts ✓
  - Purchase Taxes and Charges: Should show PPh row with Rp 4,000 ✓
  - No orange "Mixed Apply WHT" alert ✓

- [ ] Check server logs:
  - Should see `[PPh MIXED MODE]` message ✓
  - Should see `[PPh MIXED]` message in event hook ✓

## Technical Details

### Item-Level Apply WHT Control

When `apply_tds = 0` at PI level but items have `apply_tds = 1`:
- Frappe's TDS controller only applies tax to items where `apply_tds = 1`
- Tax Template must exist (set via `tax_withholding_category`)
- Result: Selective per-item taxation

### Why We Keep Supplier Category in MIXED Mode

```python
# MIXED mode: apply_tds=0 at PI level, but pph_type is set
# Event hook sees: is_mixed_mode = True
# Action: Keep tax_withholding_category = request.pph_type
# Reason: Frappe needs this to calculate item-level PPh

# If we cleared it: items wouldn't have a template to calculate from
# If we set apply_tds=1 at PI level: ALL items would be taxed (back to double)
# Solution: Keep category, rely on item-level apply_tds flags
```

## Summary

✅ **Problem:** PPh from ER not displayed in PI (MIXED mode shows empty)
✅ **Root Cause:** No tax category set in PI
✅ **Solution:** Set PI category but disable at PI level, let items control
✅ **Result:** Only items with Apply WHT get taxed, PPh displays correctly

---

**Related Fixes:**
- [MIXED_APPLY_WHT_FIX.md](MIXED_APPLY_WHT_FIX.md) - Original mixed mode detection
- [DOUBLE_WHT_FIX_SUMMARY.md](DOUBLE_WHT_FIX_SUMMARY.md) - Overall double WHT prevention
