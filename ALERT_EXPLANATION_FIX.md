# Alert Explanation & Fix

## 🎯 The Alerts You Saw

When creating PI from ER with MIXED Apply WHT, user saw 3 notifications:

### 1. ⚠️ Orange Warning (EXPECTED)
```
"Mixed Apply WHT Detected: 1 of 2 items have Apply WHT. 
PPh will be calculated per-item, not at PI level. 
Supplier's Tax Withholding Category is disabled."
```

**Status:** ✅ **NORMAL - This is INTENTIONAL**
- This is from our NEW code to inform user
- It's telling user why PPh is calculated differently (per-item instead of PI-level)
- This is helpful information, NOT an error
- User should UNDERSTAND this message

---

### 2. ⚠️ Orange Warning (PROBLEMATIC)
```
"Warning: PPh was not calculated. 
Please check Tax Withholding Category 'PPh 23' configuration."
```

**Status:** ❌ **This is UNWANTED - Now FIXED!**
- This was from old validation code in accounting.py line 588
- It was checking: `if apply_pph and taxes_and_charges_deducted == 0`
- But in mixed mode, `taxes_and_charges_deducted = 0` because:
  - We set `apply_tds = 0` (disable PI-level PPh)
  - Taxes are calculated per-item, not at PI level
  - So PI-level deducted = 0, but items have PPh
- This validation didn't know about mixed mode, so it warned

**Fix Applied:** Modified line 588 to:
```python
# Old:
if apply_pph and flt(pi.taxes_and_charges_deducted) == 0:

# New:
if apply_pph and not has_mixed_pph and flt(pi.taxes_and_charges_deducted) == 0:
```

Now it says: **"Only warn if NOT in mixed mode"** ✅

---

### 3. 🔵 Blue Info (EXPECTED)
```
"Purchase Invoice ACC-PINV-2026-00011 was created in Draft. 
Please submit it before continuing to Payment Entry."
```

**Status:** ✅ **NORMAL - Just informational**
- This is Frappe's standard message
- Tells user PI was created successfully
- Reminds user to submit before next step

---

### 4. 🟢 Green Success (EXPECTED)
```
"Purchase Invoice ACC-PINV-2026-00011 created successfully!"
```

**Status:** ✅ **NORMAL - Success notification**
- PI was created and saved
- Everything is working

---

## 🔧 What Was Fixed

### File: imogi_finance/accounting.py (Lines 575-600)

**Before:**
```python
if apply_pph and flt(pi.taxes_and_charges_deducted) == 0:
    frappe.msgprint("Warning: PPh was not calculated...")
```

**After:**
```python
# CRITICAL: Don't warn if MIXED Apply WHT mode (taxes calculated per-item)
if apply_pph and not has_mixed_pph and flt(pi.taxes_and_charges_deducted) == 0:
    frappe.msgprint("Warning: PPh was not calculated...")
```

**Logic:**
- `has_mixed_pph = TRUE` → Skip validation (taxes are per-item)
- `has_mixed_pph = FALSE` → Show warning if no taxes calculated (something might be wrong)

---

## 📊 Expected Alerts After Fix

### Scenario: MIXED Apply WHT (Your Case)

**Before Fix:**
```
⚠️ Mixed Apply WHT Detected... (orange)
⚠️ PPh was not calculated... (orange) ← UNWANTED
🔵 PI was created in Draft... (blue)
🟢 PI created successfully! (green)
```

**After Fix:**
```
⚠️ Mixed Apply WHT Detected... (orange) ← GOOD, informational
🔵 PI was created in Draft... (blue)
🟢 PI created successfully! (green)
```

The unwanted warning is GONE! ✅

---

### Scenario: Consistent Apply WHT (ALL items or NONE)

**Expected:**
```
🟢 PI created successfully! (green)
(No warnings, normal flow)
```

Or if taxes didn't calculate for some reason:
```
⚠️ Warning: PPh was not calculated... (orange) ← Legitimate warning
(Tells user to check configuration)
```

---

## ✨ Summary

| Alert | Type | Cause | Status |
|-------|------|-------|--------|
| Mixed Apply WHT Detected | Orange | Code (intentional) | ✅ Good |
| PPh was not calculated | Orange | Old validation | ❌ Fixed! |
| PI in Draft | Blue | Frappe | ✅ Normal |
| PI created successfully | Green | Frappe | ✅ Normal |

**What Changed:**
- Added `and not has_mixed_pph` condition to validation
- Now it won't warn in mixed mode (taxes are per-item)
- Still warns in other cases if taxes really aren't calculated

**File Modified:** `imogi_finance/accounting.py` Line 588

---

## 🧪 Test Again

Now when you create PI from MIXED Apply WHT ER:

1. ✅ You should see: "⚠️ Mixed Apply WHT Detected..." (orange)
2. ✅ You should see: "🟢 PI created successfully!" (green)
3. ❌ You should NOT see: "⚠️ PPh was not calculated..." (gone!)

Try it now! The warning is fixed! 🎉
