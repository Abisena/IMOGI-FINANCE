# Amortization Setup & Implementation Guide

## Overview

Solusi untuk fix missing amortization di IMOGI-Finance. Total Amortized = 0 akan fixed menjadi menampilkan breakdown bulanan.

---

## 3-Step Implementation

### STEP 1: Add Python Module
**Location:** `imogi_finance/services/amortization_processor.py`
**Status:** Already created ✓

```bash
# File sudah ada, jangan perlu create baru
```

---

### STEP 2: Add Custom Script ke Purchase Invoice Doctype

**Path:** ERPNext Menu → Customization → Customize Form → Purchase Invoice

1. **Go to:** https://itb-dev.frappe.cloud/app/customize-form/Purchase%20Invoice
2. **Click:** "Custom Script" tab
3. **Replace entire content** dengan script dari `AMORTIZATION_UI_INTEGRATION.js` (bagian "Purchase Invoice - Custom Script")

**Result:**
- Akan ada button "Generate Amortization" untuk PI dengan deferred items
- Akan ada button "View Schedule" untuk lihat breakdown bulanan

---

### STEP 3: (Optional) Update Deferred Expense Tracker Report

**Path:** ERPNext Menu → Reporting Tools → Query Report → Deferred Expense Tracker

1. **Go to:** https://itb-dev.frappe.cloud/app/query-report/Deferred%20Expense%20Tracker
2. **Click:** Menu (3 dots) → Customize → Custom Script
3. **Add filter** untuk show amortization schedule details

**Result:**
- Report akan show per-bulan breakdown
- Status: Posted vs Pending

---

## Quick Start (Jalankan Langsung)

### Option A: Via Console (Fastest)

```javascript
// Open Frappe Console: Ctrl+K → Search "Console"

// 1. Get schedule breakdown
frappe.call({
    method: 'imogi_finance.services.amortization_processor.get_amortization_schedule',
    args: {
        pi_name: 'ACC-PINV-2026-00011'  // Sesuaikan dengan PI name
    },
    callback: (r) => {
        console.table(r.message.schedule);
        console.log('Total Deferred:', r.message.total_deferred);
    }
});

// 2. Generate Journal Entries
frappe.call({
    method: 'imogi_finance.services.amortization_processor.create_amortization_schedule_for_pi',
    args: {
        pi_name: 'ACC-PINV-2026-00011'
    },
    callback: (r) => {
        console.log('Created JEs:', r.message.journal_entries);
        frappe.msgprint('Amortization created!');
        location.reload();
    }
});
```

---

### Option B: Via Terminal (Batch Processing)

```bash
# SSH ke server
cd ~/frappe-bench

# Run untuk ALL PI dengan deferred items
bench --site itb-dev.frappe.cloud execute \
  'from imogi_finance.services.amortization_processor import create_all_missing_amortization; print(create_all_missing_amortization())'
```

---

### Option C: Via Web Form (GUI)

1. **Open Purchase Invoice** dengan deferred items
   - Contoh: ACC-PINV-2026-00011

2. **Click button** "Generate Amortization"

3. **System akan create** Journal Entries otomatis

4. **Refresh page** → Check General Ledger

---

## Verification

### ✅ Check if Working

**1. View Generated Schedule**
```javascript
frappe.call({
    method: 'imogi_finance.services.amortization_processor.get_amortization_schedule',
    args: { pi_name: 'ACC-PINV-2026-00011' },
    callback: (r) => {
        // Expected output:
        // {
        //   "pi": "ACC-PINV-2026-00011",
        //   "total_deferred": 12000000,
        //   "total_periods": 12,
        //   "schedule": [
        //     {period: 1, posting_date: "2026-01-28", amount: 1000000, ...},
        //     {period: 2, posting_date: "2026-02-28", amount: 1000000, ...},
        //     ...
        //   ]
        // }
    }
});
```

**2. Check Journal Entries Created**
```sql
-- Run di Database
SELECT name, posting_date, reference_name, docstatus
FROM `tabJournal Entry`
WHERE reference_type = 'Purchase Invoice'
AND reference_name = 'ACC-PINV-2026-00011'
AND docstatus = 1
ORDER BY posting_date;

-- Expected: 12 entries, 1 per bulan, semua docstatus = 1 (submitted)
```

**3. Verify GL Entries**
```
Menu → Accounting → General Ledger
Filter → Account = "Prepaid Marketing Expenses - ITB"
Filter → Reference = "ACC-PINV-2026-00011"

Expected: 12 entries
  28-01-2026: Debit 1,000,000
  28-02-2026: Debit 1,000,000
  ... (12 times)
  Balance: 0 ✓
```

**4. Check Deferred Expense Tracker**
```
Menu → Reporting Tools → Query Report → Deferred Expense Tracker

Expected (After Fix):
  | PI | Total Deferred | Total Amortized | Outstanding |
  | ACC-PINV-2026-00011 | 12,000,000 | 12,000,000 | 0 |
  | ACC-PINV-2026-00012 | 24,000,000 | 24,000,000 | 0 |
  | ... | 108,000,000 | 108,000,000 | 0 |
```

---

## Troubleshooting

### ❌ Error: "No deferred items found"
**Cause:** PI items tidak punya flag `enable_deferred_expense`

**Fix:**
```
Open PI → Edit items → Check setiap item punya:
  □ enable_deferred_expense = 1
  □ deferred_expense_account = [Prepaid Account]
  □ service_start_date = [date]
  □ service_end_date = [date]

Save & Submit PI
```

---

### ❌ Error: "JE already exists"
**Cause:** JE sudah dibuat sebelumnya untuk tanggal yang sama

**Fix:**
```sql
-- Check existing JE
SELECT name, posting_date FROM `tabJournal Entry`
WHERE reference_name = 'ACC-PINV-2026-00011'
AND docstatus = 1;

-- Jika sudah ada, skip atau update existing
```

---

### ❌ Error: "PI must be submitted"
**Cause:** PI masih dalam status draft

**Fix:**
```
Open PI → Click Submit button → Retry amortization
```

---

### ❌ Total Amortized Still = 0
**Cause:** Journal Entries belum di-count di Deferred Expense Tracker

**Fix:**
```
1. Clear browser cache: Ctrl+Shift+Delete
2. Refresh page: Ctrl+R
3. Or run SQL refresh:

UPDATE `tabDeferred Expense`
SET total_amortized = (
    SELECT SUM(credit) FROM `tabJournal Entry Account`
    WHERE journal_entry IN (...)
)
```

---

## Database Structure

### New Data Created by System

**Purchase Invoice**
```
No changes to existing data
```

**Journal Entry** (NEW - Created by Amortization)
```
Fields:
  posting_date: 2026-01-28, 2026-02-28, etc (one per month)
  reference_type: "Purchase Invoice"
  reference_name: "ACC-PINV-2026-00011"
  description: "Deferred Expense Amortization - Marketing Expense (Month 1 of 12)"
  docstatus: 1 (submitted)
```

**Journal Entry Account** (NEW - Created for each JE)
```
Account 1 (Debit):
  account: "Prepaid Marketing Expenses - ITB"
  debit: 1,000,000

Account 2 (Credit):
  account: "Marketing Expenses - ITB"
  credit: 1,000,000
```

---

## Expected Results

### Before Implementation
```
Deferred Expense Tracker Report:
═══════════════════════════════════════════════════════════
  Total Deferred:     108,000,000
  Total Amortized:    0 ✗ PROBLEM
  Outstanding:        108,000,000
═══════════════════════════════════════════════════════════

General Ledger - Prepaid Marketing:
═══════════════════════════════════════════════════════════
  (NO ENTRIES) ✗
═══════════════════════════════════════════════════════════
```

### After Implementation
```
Deferred Expense Tracker Report:
═══════════════════════════════════════════════════════════
  Total Deferred:     108,000,000 ✓
  Total Amortized:    108,000,000 ✓ FIXED!
  Outstanding:        0 ✓
═══════════════════════════════════════════════════════════

General Ledger - Prepaid Marketing:
═══════════════════════════════════════════════════════════
  28-01-2026: Debit 9,000,000 (combined from 8 ERs) ✓
  28-02-2026: Debit 9,000,000 ✓
  ... (12 months total) ✓
  Balance: 0 ✓
═══════════════════════════════════════════════════════════

PI: ACC-PINV-2026-00011 (Monthly Breakdown):
═══════════════════════════════════════════════════════════
  Period 1:  01-28-2026: 1,000,000 (JE-ACC-0001) ✓
  Period 2:  02-28-2026: 1,000,000 (JE-ACC-0002) ✓
  Period 3:  03-31-2026: 1,000,000 (JE-ACC-0003) ✓
  ... (12 periods)
  Total:     12,000,000 ✓
═══════════════════════════════════════════════════════════
```

---

## Summary

| Step | Action | Status |
|------|--------|--------|
| 1 | Add `amortization_processor.py` | ✓ Created |
| 2 | Add Custom Script to PI doctype | ⏳ Manual add |
| 3 | Test via Console | ⏳ Manual run |
| 4 | Verify JE created | ⏳ Check DB |
| 5 | Refresh Deferred Expense Tracker | ⏳ Manual refresh |

---

## Files Created

1. **`DEFERRED_AMORTIZATION_ISSUE_AND_SOLUTION.md`**
   - Root cause analysis
   - Quick fixes guide

2. **`amortization_processor.py`**
   - Main Python module
   - Functions: `create_amortization_schedule_for_pi()`, `get_amortization_schedule()`, etc

3. **`AMORTIZATION_UI_INTEGRATION.js`**
   - Custom script untuk PI doctype
   - Browser console snippets

4. **`AMORTIZATION_SETUP_AND_IMPLEMENTATION.md`** (ini file)
   - Step-by-step guide
   - Verification checklist

---

## Next Actions

### Immediate (Today)
- [ ] Review `amortization_processor.py` logic
- [ ] Copy Custom Script ke PI doctype
- [ ] Test via Console dengan 1 PI

### Short-term (This Week)
- [ ] Run batch processing untuk ALL PI
- [ ] Verify total amortized = total deferred
- [ ] Update Deferred Expense Tracker report

### Long-term (Integrate)
- [ ] Add to Frappe hooks untuk auto-run monthly
- [ ] Create scheduled job untuk background processing
- [ ] Add audit trail untuk setiap amortization

---

## Support

**If something breaks:**

1. Check error di browser console (F12)
2. Check server logs: `~/frappe-bench/logs/bench.log`
3. Run test manually: `frappe execute ...`
4. Rollback JE: Delete manually created JEs via UI

**If confused:**

1. Review `DEFERRED_AMORTIZATION_ISSUE_AND_SOLUTION.md` untuk root cause
2. Check database directly untuk understand current state
3. Run verification queries untuk check progress
