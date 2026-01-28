# Deferred Amortization - Quick Reference & Data Mapping

**Created:** January 28, 2026
**Issue:** Total Amortized = 0 (masih gak ada mapping amortisasi)
**Solution:** Direct mapping menggunakan `amortization_processor.py`

---

## Current State (From Deferred Expense Tracker)

### Data Snapshot
```
8 Purchase Invoices dengan deferred items:
┌────┬─────────────────┬────────────┬─────────┬──────────────┬──────────────────┐
│ # │ PI / ER         │ Amount (M) │ Periods │ Start Date   │ Account          │
├────┼─────────────────┼────────────┼─────────┼──────────────┼──────────────────┤
│ 1 │ ER-2026-000025  │ 12         │ 12      │ 01-11-2025   │ Marketing - ITB  │
│ 2 │ ER-2026-000024  │ 24         │ 24      │ 28-01-2026   │ Marketing - ITB  │
│ 3 │ ER-2026-000023  │ 12         │ 12      │ 28-01-2026   │ Marketing - ITB  │
│ 4 │ ER-2026-000022  │ 12         │ 12      │ 28-01-2026   │ Marketing - ITB  │
│ 5 │ ER-2026-000021  │ 12         │ 12      │ 28-01-2026   │ Marketing - ITB  │
│ 6 │ ER-2026-000015  │ 12         │ 12      │ 27-01-2026   │ Marketing - ITB  │
│ 7 │ ER-2026-000014  │ 12         │ 12      │ 27-11-2025   │ Marketing - ITB  │
│ 8 │ ER-2026-000013  │ 12         │ 12      │ 27-01-2026   │ Marketing - ITB  │
├────┼─────────────────┼────────────┼─────────┼──────────────┼──────────────────┤
│    │ TOTAL           │ 108        │         │              │                  │
└────┴─────────────────┴────────────┴─────────┴──────────────┴──────────────────┘

Summary:
  Total Deferred:      Rp 108,000,000 ✓
  Total Amortized:     Rp 0 ✗ MISSING!
  Total Outstanding:   Rp 108,000,000 (should be 0 after amortization)
```

---

## Expected Mapping (After Implementation)

### ER-2026-000025 (Example: 12 juta ÷ 12 bulan)

```
Date          JE      Debit        Credit       Account
─────────────────────────────────────────────────────────
01-11-2025    JE-1    1,000,000                Prepaid Marketing
              JE-1                 1,000,000  Marketing Expense

01-12-2025    JE-2    1,000,000                Prepaid Marketing
              JE-2                 1,000,000  Marketing Expense

01-01-2026    JE-3    1,000,000                Prepaid Marketing
              JE-3                 1,000,000  Marketing Expense

01-02-2026    JE-4    1,000,000                Prepaid Marketing
              JE-4                 1,000,000  Marketing Expense

...

01-10-2026    JE-12   1,000,000                Prepaid Marketing
              JE-12                1,000,000  Marketing Expense

BALANCE: 0 ✓
```

---

## Implementation Mapping (Using amortization_processor.py)

### Function Calls Needed

```python
# For single ER-2026-000025 (needs corresponding PI)
from imogi_finance.services.amortization_processor import create_amortization_schedule_for_pi

# Get underlying PI name from ER
# Assuming PI: ACC-PINV-2026-00011 corresponds to ER-2026-000025

result = create_amortization_schedule_for_pi('ACC-PINV-2026-00011')

print(result)
# Output:
# {
#   "pi_name": "ACC-PINV-2026-00011",
#   "total_schedules": 12,
#   "total_amount": 12000000.0,
#   "journal_entries": [
#     "JE-ACC-0001",
#     "JE-ACC-0002",
#     ... (12 entries)
#   ]
# }
```

---

## Console Commands (Copy-Paste Ready)

### 1. Get Schedule Breakdown untuk 1 PI

```javascript
frappe.call({
    method: 'imogi_finance.services.amortization_processor.get_amortization_schedule',
    args: { pi_name: 'ACC-PINV-2026-00011' },
    callback: (r) => {
        console.log('Total Deferred:', r.message.total_deferred);
        console.log('Periods:', r.message.total_periods);
        console.table(r.message.schedule);
    }
});
```

**Expected Output:**
```
┌────────┬──────────────┬───────────────┬─────────────┬──────────────┐
│ period │ posting_date │ amount        │ item_code   │ bulan        │
├────────┼──────────────┼───────────────┼─────────────┼──────────────┤
│ 1      │ 2026-01-28   │ 1000000       │ MARKETING   │ January 2026 │
│ 2      │ 2026-02-28   │ 1000000       │ MARKETING   │ February 2026│
│ 3      │ 2026-03-31   │ 1000000       │ MARKETING   │ March 2026   │
│ ...    │ ...          │ 1000000       │ ...         │ ...          │
│ 12     │ 2026-12-31   │ 1000000       │ MARKETING   │ December 2026│
└────────┴──────────────┴───────────────┴─────────────┴──────────────┘

Total Deferred: 12000000
Periods: 12
```

---

### 2. Create Amortization untuk 1 PI

```javascript
frappe.call({
    method: 'imogi_finance.services.amortization_processor.create_amortization_schedule_for_pi',
    args: { pi_name: 'ACC-PINV-2026-00011' },
    callback: (r) => {
        let result = r.message;
        alert(`✓ Amortization Created!\n\nTotal Schedules: ${result.total_schedules}\nJournal Entries: ${result.journal_entries.length}`);
        console.log('Created JEs:', result.journal_entries);
    }
});
```

**Expected Output:**
```
✓ Amortization Created!

Total Schedules: 12
Journal Entries: 12

Created JEs:
  - JE-ACC-0001
  - JE-ACC-0002
  - JE-ACC-0003
  ... (12 entries total)
```

---

### 3. Create untuk ALL PI (Batch)

```javascript
frappe.call({
    method: 'imogi_finance.services.amortization_processor.create_all_missing_amortization',
    callback: (r) => {
        let result = r.message;
        console.log(`Processed ${result.total_pi} PIs`);
        console.log(`Success: ${result.success}, Failed: ${result.failed}`);
        console.log(`JEs Created: ${result.journal_entries_created}`);
        console.table(result.details);
    }
});
```

**Expected Output (for 8 PIs):**
```
Processed 8 PIs
Success: 8, Failed: 0
JEs Created: 96 (8 PIs × 12 months each)

┌────────────────────────┬───────────┬────────────┬───────────────────┐
│ pi_name                │ schedules │ amount     │ jes               │
├────────────────────────┼───────────┼────────────┼───────────────────┤
│ ACC-PINV-2026-00011    │ 12        │ 12000000   │ [JE-ACC-0001, ...] │
│ ACC-PINV-2026-00012    │ 24        │ 24000000   │ [JE-ACC-0013, ...] │
│ ...                    │ ...       │ ...        │ ...                │
│ ACC-PINV-2026-00018    │ 12        │ 12000000   │ [JE-ACC-0085, ...] │
└────────────────────────┴───────────┴────────────┴───────────────────┘
```

---

## Database Queries untuk Verification

### Check 1: Count Deferred PIs

```sql
SELECT
    COUNT(DISTINCT `pi`.`name`) as total_deferred_pis,
    COUNT(DISTINCT `item`.`parent`) as pis_with_deferred_items,
    SUM(`item`.`amount`) as total_deferred_amount
FROM `tabPurchase Invoice` pi
INNER JOIN `tabPurchase Invoice Item` item
    ON pi.name = item.parent
WHERE pi.docstatus = 1
AND item.enable_deferred_expense = 1;

-- Expected Output (from your data):
-- total_deferred_pis: 8
-- pis_with_deferred_items: 8
-- total_deferred_amount: 108000000
```

---

### Check 2: Count Generated Journal Entries

```sql
SELECT
    COUNT(*) as total_jes_created,
    COUNT(DISTINCT posting_date) as distinct_months,
    SUM(`accounts`.`debit`) as total_debit
FROM `tabJournal Entry` je
INNER JOIN `tabJournal Entry Account` accounts
    ON je.name = accounts.parent
WHERE je.reference_type = 'Purchase Invoice'
AND je.reference_name LIKE 'ACC-PI%'
AND je.docstatus = 1;

-- Expected Output (after amortization):
-- total_jes_created: 96 (8 PIs × 12 months avg)
-- distinct_months: ~12-13 (overlapping dates)
-- total_debit: 108000000
```

---

### Check 3: Verify Amortized Amount

```sql
SELECT
    DATE(je.posting_date) as posting_month,
    COUNT(je.name) as je_count,
    SUM(accounts.debit) as total_debited,
    SUM(accounts.credit) as total_credited
FROM `tabJournal Entry` je
INNER JOIN `tabJournal Entry Account` accounts
    ON je.name = accounts.parent
WHERE je.reference_type = 'Purchase Invoice'
AND je.docstatus = 1
AND accounts.account LIKE '%Prepaid%Marketing%'
GROUP BY DATE(je.posting_date)
ORDER BY posting_date;

-- Expected Output:
-- 2025-11-28:  1 JE,  1,000,000
-- 2025-12-28:  1 JE,  1,000,000
-- 2026-01-28:  8 JEs, 9,000,000 (combined from 8 PIs starting same date)
-- 2026-02-28:  8 JEs, 9,000,000
-- ... (12 months total)
-- 2026-10-31:  6 JEs, 7,000,000 (only 6 PIs that extend to month 10+)
-- TOTAL:       96 JEs, 108,000,000 ✓
```

---

### Check 4: Before vs After Deferred Expense Tracker

```sql
-- BEFORE (Current State)
SELECT
    'Total Deferred' as metric,
    SUM(item.amount) as amount
FROM `tabPurchase Invoice Item` item
WHERE item.enable_deferred_expense = 1

UNION ALL

SELECT
    'Total Amortized' as metric,
    SUM(accounts.debit) as amount
FROM `tabJournal Entry` je
INNER JOIN `tabJournal Entry Account` accounts
    ON je.name = accounts.parent
WHERE je.reference_type = 'Purchase Invoice'
AND accounts.account LIKE '%Prepaid%Marketing%'
AND je.docstatus = 1;

-- BEFORE Result:
-- Total Deferred:   108,000,000
-- Total Amortized:  0 ✗ PROBLEM!

-- AFTER (After Running Amortization):
-- Total Deferred:   108,000,000
-- Total Amortized:  108,000,000 ✓ FIXED!
-- Outstanding:      0 ✓ FIXED!
```

---

## Step-by-Step Execution Plan

### Phase 1: Setup (10 minutes)
```
1. Open amortization_processor.py from file manager
2. Copy entire content
3. Go to: https://itb-dev.frappe.cloud/app/home
4. Create new file in server OR use existing services folder
5. Paste code
6. Save
```

### Phase 2: Test Single PI (5 minutes)
```
1. Open Frappe Console (Ctrl+K → console)
2. Copy command from "Get Schedule Breakdown" above
3. Paste in console
4. Press Enter
5. Check output shows 12 periods with 1M each
```

### Phase 3: Create Amortization (5 minutes)
```
1. In same console
2. Copy command from "Create Amortization untuk 1 PI"
3. Paste & press Enter
4. Check output shows "12 Journal Entries created"
5. Refresh page
```

### Phase 4: Batch Process (10 minutes)
```
1. In console, run: create_all_missing_amortization()
2. Check output shows 8 PIs processed
3. Check "JEs Created: 96" (or similar)
4. Wait for completion
```

### Phase 5: Verify (5 minutes)
```
1. Menu → Accounting → Deferred Expense Tracker
2. Refresh (Ctrl+R)
3. Check Total Amortized = 108,000,000
4. Check Outstanding = 0
```

---

## Troubleshooting Quick Guide

| Problem | Cause | Fix |
|---------|-------|-----|
| "No deferred items" | PI items missing flags | Add enable_deferred_expense=1 to item |
| "JE already exists" | Amortization already created | Check JE list, skip duplicate |
| "PI must be submitted" | PI status is draft | Click Submit on PI |
| Total still 0 | Data not refreshed | Clear cache, refresh page |
| Error during creation | Python syntax error | Check amortization_processor.py format |

---

## Success Criteria

✅ **You'll know it worked when:**

1. Deferred Expense Tracker shows:
   - Total Deferred: 108,000,000
   - Total Amortized: 108,000,000
   - Outstanding: 0

2. General Ledger shows 12 monthly entries per PI

3. Journal Entries visible in GL Entry

4. Each month shows Rp 9,000,000 (combined from 8 PIs)

5. Database query returns all 96 JEs created

---

## Time Estimate

- **Setup:** 10 minutes
- **Testing:** 5 minutes
- **Batch Create:** 10 minutes
- **Verification:** 5 minutes
- **Total:** 30 minutes

**Start:** Now! 🚀
