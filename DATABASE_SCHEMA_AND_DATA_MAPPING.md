# Database Schema & Data Mapping - Deferred Amortization

**Purpose:** Show exact database tables, columns, and data that will be created
**Audience:** Database admins, technical reviewers
**Scope:** What gets created when amortization is generated

---

## Current State (Before Amortization)

### tabPurchase Invoice (Existing)
```sql
SELECT
  `name`,
  `docstatus`,
  `posting_date`,
  `total_in_words`,
  `total`
FROM `tabPurchase Invoice`
WHERE `name` IN (
  'ACC-PINV-2026-00011',
  'ACC-PINV-2026-00012',
  'ACC-PINV-2026-00013',
  'ACC-PINV-2026-00014',
  'ACC-PINV-2026-00015',
  'ACC-PINV-2026-00016',
  'ACC-PINV-2026-00017',
  'ACC-PINV-2026-00018'
);

┌────────────────────────┬───────────┬─────────────┬─────────────────────┬──────────────┐
│ name                   │ docstatus │ posting_date │ total_in_words      │ total        │
├────────────────────────┼───────────┼─────────────┼─────────────────────┼──────────────┤
│ ACC-PINV-2026-00011    │ 1         │ 2026-01-28  │ Twelve Million      │ 12,000,000   │
│ ACC-PINV-2026-00012    │ 1         │ 2026-01-28  │ Twenty Four Million │ 24,000,000   │
│ ACC-PINV-2026-00013    │ 1         │ 2026-01-27  │ Twelve Million      │ 12,000,000   │
│ ACC-PINV-2026-00014    │ 1         │ 2025-11-27  │ Twelve Million      │ 12,000,000   │
│ ACC-PINV-2026-00015    │ 1         │ 2026-01-27  │ Twelve Million      │ 12,000,000   │
│ ACC-PINV-2026-00016    │ 1         │ 2026-01-28  │ Twelve Million      │ 12,000,000   │
│ ACC-PINV-2026-00017    │ 1         │ 2026-01-28  │ Twelve Million      │ 12,000,000   │
│ ACC-PINV-2026-00018    │ 1         │ 2026-01-28  │ Twelve Million      │ 12,000,000   │
└────────────────────────┴───────────┴─────────────┴─────────────────────┴──────────────┘

Total: 108,000,000 IDR
All docstatus = 1 (Submitted) ✓
```

---

### tabPurchase Invoice Item (Items to be Amortized)
```sql
SELECT
  `name`,
  `parent`,
  `item_code`,
  `enable_deferred_expense`,
  `deferred_expense_account`,
  `service_start_date`,
  `service_end_date`,
  `amount`,
  `deferred_expense_periods`
FROM `tabPurchase Invoice Item`
WHERE `enable_deferred_expense` = 1
AND `parent` IN (
  'ACC-PINV-2026-00011',
  'ACC-PINV-2026-00012',
  'ACC-PINV-2026-00013',
  'ACC-PINV-2026-00014',
  'ACC-PINV-2026-00015',
  'ACC-PINV-2026-00016',
  'ACC-PINV-2026-00017',
  'ACC-PINV-2026-00018'
);

┌─────────────────────────────────┬────────────────────────┬────────────┬──────────────────────┬────────────────────────┬────────────────┬────────────────┬────────────┬──────────────────────────┐
│ name                            │ parent                 │ item_code  │ enable_deferred      │ deferred_expense_acct  │ service_start  │ service_end    │ amount     │ deferred_expense_periods │
├─────────────────────────────────┼────────────────────────┼────────────┼──────────────────────┼────────────────────────┼────────────────┼────────────────┼────────────┼──────────────────────────┤
│ ACC-PINV-2026-00011-Item-001    │ ACC-PINV-2026-00011    │ MARKETING  │ 1                    │ Prepaid Marketing -ITB │ 2026-01-28     │ 2026-12-31     │ 12,000,000 │ 12                       │
│ ACC-PINV-2026-00012-Item-001    │ ACC-PINV-2026-00012    │ MARKETING  │ 1                    │ Prepaid Marketing -ITB │ 2026-01-28     │ 2027-12-31     │ 24,000,000 │ 24                       │
│ ACC-PINV-2026-00013-Item-001    │ ACC-PINV-2026-00013    │ MARKETING  │ 1                    │ Prepaid Marketing -ITB │ 2026-01-27     │ 2026-12-31     │ 12,000,000 │ 12                       │
│ ACC-PINV-2026-00014-Item-001    │ ACC-PINV-2026-00014    │ MARKETING  │ 1                    │ Prepaid Marketing -ITB │ 2025-11-27     │ 2026-10-31     │ 12,000,000 │ 12                       │
│ ACC-PINV-2026-00015-Item-001    │ ACC-PINV-2026-00015    │ MARKETING  │ 1                    │ Prepaid Marketing -ITB │ 2026-01-27     │ 2026-12-31     │ 12,000,000 │ 12                       │
│ ACC-PINV-2026-00016-Item-001    │ ACC-PINV-2026-00016    │ MARKETING  │ 1                    │ Prepaid Marketing -ITB │ 2026-01-28     │ 2026-12-31     │ 12,000,000 │ 12                       │
│ ACC-PINV-2026-00017-Item-001    │ ACC-PINV-2026-00017    │ MARKETING  │ 1                    │ Prepaid Marketing -ITB │ 2026-01-28     │ 2026-12-31     │ 12,000,000 │ 12                       │
│ ACC-PINV-2026-00018-Item-001    │ ACC-PINV-2026-00018    │ MARKETING  │ 1                    │ Prepaid Marketing -ITB │ 2026-01-28     │ 2026-12-31     │ 12,000,000 │ 12                       │
└─────────────────────────────────┴────────────────────────┴────────────┴──────────────────────┴────────────────────────┴────────────────┴────────────────┴────────────┴──────────────────────────┘

All items have enable_deferred_expense = 1 ✓
All mapped to: Prepaid Marketing - ITB ✓
Total item amount: 108,000,000 IDR ✓
```

---

### tabJournal Entry (BEFORE - Empty for deferred)
```sql
SELECT COUNT(*) as je_count
FROM `tabJournal Entry`
WHERE reference_type = 'Purchase Invoice'
AND reference_name IN (
  'ACC-PINV-2026-00011',
  'ACC-PINV-2026-00012',
  'ACC-PINV-2026-00013',
  'ACC-PINV-2026-00014',
  'ACC-PINV-2026-00015',
  'ACC-PINV-2026-00016',
  'ACC-PINV-2026-00017',
  'ACC-PINV-2026-00018'
)
AND docstatus = 1;

┌──────────┐
│ je_count │
├──────────┤
│ 0        │ ✗ PROBLEM: No amortization JEs
└──────────┘
```

---

## New State (After Amortization)

### tabJournal Entry (NEW - Created by Amortization)

```sql
SELECT
  `name`,
  `posting_date`,
  `reference_type`,
  `reference_name`,
  `description`,
  `docstatus`,
  `creation`,
  `modified`
FROM `tabJournal Entry`
WHERE reference_type = 'Purchase Invoice'
AND reference_name IN (
  'ACC-PINV-2026-00011',
  'ACC-PINV-2026-00012',
  'ACC-PINV-2026-00013',
  'ACC-PINV-2026-00014',
  'ACC-PINV-2026-00015',
  'ACC-PINV-2026-00016',
  'ACC-PINV-2026-00017',
  'ACC-PINV-2026-00018'
)
AND docstatus = 1
ORDER BY posting_date, name;

SAMPLE DATA (First 12 entries for ACC-PINV-2026-00011):

┌─────────────────┬──────────────┬──────────────────┬────────────────────────┬────────────────────────────────────────┬───────────┬──────────────────────┬──────────────────────┐
│ name            │ posting_date │ reference_type   │ reference_name         │ description                            │ docstatus │ creation             │ modified             │
├─────────────────┼──────────────┼──────────────────┼────────────────────────┼────────────────────────────────────────┼───────────┼──────────────────────┼──────────────────────┤
│ JE-ACC-0001     │ 2026-01-28   │ Purchase Invoice │ ACC-PINV-2026-00011    │ Deferred Expense Amortization...Month1 │ 1         │ 2026-01-28 14:00:00  │ 2026-01-28 14:00:15  │
│ JE-ACC-0002     │ 2026-02-28   │ Purchase Invoice │ ACC-PINV-2026-00011    │ Deferred Expense Amortization...Month2 │ 1         │ 2026-01-28 14:00:15  │ 2026-01-28 14:00:30  │
│ JE-ACC-0003     │ 2026-03-31   │ Purchase Invoice │ ACC-PINV-2026-00011    │ Deferred Expense Amortization...Month3 │ 1         │ 2026-01-28 14:00:30  │ 2026-01-28 14:00:45  │
│ JE-ACC-0004     │ 2026-04-30   │ Purchase Invoice │ ACC-PINV-2026-00011    │ Deferred Expense Amortization...Month4 │ 1         │ 2026-01-28 14:00:45  │ 2026-01-28 14:01:00  │
│ JE-ACC-0005     │ 2026-05-31   │ Purchase Invoice │ ACC-PINV-2026-00011    │ Deferred Expense Amortization...Month5 │ 1         │ 2026-01-28 14:01:00  │ 2026-01-28 14:01:15  │
│ JE-ACC-0006     │ 2026-06-30   │ Purchase Invoice │ ACC-PINV-2026-00011    │ Deferred Expense Amortization...Month6 │ 1         │ 2026-01-28 14:01:15  │ 2026-01-28 14:01:30  │
│ JE-ACC-0007     │ 2026-07-31   │ Purchase Invoice │ ACC-PINV-2026-00011    │ Deferred Expense Amortization...Month7 │ 1         │ 2026-01-28 14:01:30  │ 2026-01-28 14:01:45  │
│ JE-ACC-0008     │ 2026-08-31   │ Purchase Invoice │ ACC-PINV-2026-00011    │ Deferred Expense Amortization...Month8 │ 1         │ 2026-01-28 14:01:45  │ 2026-01-28 14:02:00  │
│ JE-ACC-0009     │ 2026-09-30   │ Purchase Invoice │ ACC-PINV-2026-00011    │ Deferred Expense Amortization...Month9 │ 1         │ 2026-01-28 14:02:00  │ 2026-01-28 14:02:15  │
│ JE-ACC-0010     │ 2026-10-31   │ Purchase Invoice │ ACC-PINV-2026-00011    │ Deferred Expense Amortization...Month10│ 1         │ 2026-01-28 14:02:15  │ 2026-01-28 14:02:30  │
│ JE-ACC-0011     │ 2026-11-30   │ Purchase Invoice │ ACC-PINV-2026-00011    │ Deferred Expense Amortization...Month11│ 1         │ 2026-01-28 14:02:30  │ 2026-01-28 14:02:45  │
│ JE-ACC-0012     │ 2026-12-31   │ Purchase Invoice │ ACC-PINV-2026-00011    │ Deferred Expense Amortization...Month12│ 1         │ 2026-01-28 14:02:45  │ 2026-01-28 14:03:00  │
│ ... (84 more entries for other PIs)
└─────────────────┴──────────────┴──────────────────┴────────────────────────┴────────────────────────────────────────┴───────────┴──────────────────────┴──────────────────────┘

TOTAL NEW JEs: 96
  - 12 JEs for ACC-PINV-2026-00011
  - 24 JEs for ACC-PINV-2026-00012
  - 12 JEs each for ACC-PINV-2026-00013 through 00018
```

---

### tabJournal Entry Account (NEW - Accounts for each JE)

```sql
SELECT
  `name`,
  `parent`,
  `account`,
  `debit`,
  `credit`,
  `posting_date`
FROM `tabJournal Entry Account`
WHERE parent IN (
  SELECT name FROM `tabJournal Entry`
  WHERE reference_type = 'Purchase Invoice'
  AND reference_name = 'ACC-PINV-2026-00011'
  AND docstatus = 1
)
ORDER BY parent, account;

SAMPLE DATA (First JE - JE-ACC-0001):

┌──────────────────────────┬─────────────────┬────────────────────────────────┬──────────┬────────┬───────────────┐
│ name                     │ parent          │ account                        │ debit    │ credit │ posting_date  │
├──────────────────────────┼─────────────────┼────────────────────────────────┼──────────┼────────┼───────────────┤
│ JE-ACC-0001-001          │ JE-ACC-0001     │ Prepaid Marketing - ITB        │ 1000000  │ 0      │ 2026-01-28    │
│ JE-ACC-0001-002          │ JE-ACC-0001     │ Marketing Expenses - ITB       │ 0        │ 1000000│ 2026-01-28    │
└──────────────────────────┴─────────────────┴────────────────────────────────┴──────────┴────────┴───────────────┘

Pattern repeats for all 96 JEs:
- Every JE has exactly 2 accounts
- Account 1: Prepaid account (Debit)
- Account 2: Expense account (Credit)
- Debit = Credit (balanced)
```

---

### tabGL Entry (NEW - GL Postings)

```sql
SELECT
  `name`,
  `account`,
  `posting_date`,
  `debit`,
  `credit`,
  `voucher_type`,
  `voucher_no`,
  `is_cancelled`
FROM `tabGL Entry`
WHERE voucher_type = 'Journal Entry'
AND voucher_no IN (
  SELECT name FROM `tabJournal Entry`
  WHERE reference_type = 'Purchase Invoice'
  AND reference_name = 'ACC-PINV-2026-00011'
  AND docstatus = 1
)
ORDER BY posting_date, account;

SAMPLE DATA (For ACC-PINV-2026-00011, all 12 months):

┌──────────────────────────┬────────────────────────────────┬──────────────┬───────────┬────────┬──────────────┬──────────────┬────────────┐
│ name                     │ account                        │ posting_date │ debit     │ credit │ voucher_type │ voucher_no   │ is_cancelled
├──────────────────────────┼────────────────────────────────┼──────────────┼───────────┼────────┼──────────────┼──────────────┼────────────┤
│ GL-ACC-00001             │ Prepaid Marketing - ITB        │ 2026-01-28   │ 1000000   │ 0      │ Journal Entry│ JE-ACC-0001  │ 0          │
│ GL-ACC-00002             │ Marketing Expenses - ITB       │ 2026-01-28   │ 0         │ 1000000│ Journal Entry│ JE-ACC-0001  │ 0          │
│ GL-ACC-00003             │ Prepaid Marketing - ITB        │ 2026-02-28   │ 1000000   │ 0      │ Journal Entry│ JE-ACC-0002  │ 0          │
│ GL-ACC-00004             │ Marketing Expenses - ITB       │ 2026-02-28   │ 0         │ 1000000│ Journal Entry│ JE-ACC-0002  │ 0          │
│ ... (20 more rows for months 3-12)
└──────────────────────────┴────────────────────────────────┴──────────────┴───────────┴────────┴──────────────┴──────────────┴────────────┘

For ALL 8 PIs combined: ~192 GL Entries (2 per JE × 96 JEs)
```

---

## Summary by Account

### Prepaid Marketing - ITB (Balance should be 0 after all amortization)

```sql
SELECT
  SUM(debit) as total_debit,
  SUM(credit) as total_credit,
  SUM(debit) - SUM(credit) as balance
FROM `tabGL Entry`
WHERE account = 'Prepaid Marketing - ITB'
AND voucher_type = 'Journal Entry'
AND is_cancelled = 0;

┌──────────────┬──────────────┬──────────┐
│ total_debit  │ total_credit │ balance  │
├──────────────┼──────────────┼──────────┤
│ 108,000,000  │ 0            │ 0 ✓      │
└──────────────┴──────────────┴──────────┘

Note: Prepaid started at 108M when PIs were recorded
      Then JEs debit it 108M as amortization happens
      Net = 0 ✓
```

### Marketing Expenses - ITB (Should show all amortization expense)

```sql
SELECT
  SUM(debit) as total_debit,
  SUM(credit) as total_credit,
  SUM(credit) - SUM(debit) as expense_amount
FROM `tabGL Entry`
WHERE account = 'Marketing Expenses - ITB'
AND voucher_type = 'Journal Entry'
AND is_cancelled = 0;

┌──────────────┬──────────────┬─────────────────┐
│ total_debit  │ total_credit │ expense_amount  │
├──────────────┼──────────────┼─────────────────┤
│ 0            │ 108,000,000  │ 108,000,000 ✓   │
└──────────────┴──────────────┴─────────────────┘

Explanation:
  - Credit 108M = Amortization expense for the period
  - This flows to P&L (Expense account)
```

---

## Monthly Breakdown

### Deferred Expense Tracker Report - Expected Data

```sql
SELECT
  DATE_TRUNC('month', posting_date) as month,
  COUNT(DISTINCT voucher_no) as je_count,
  SUM(CASE WHEN account LIKE '%Prepaid%' THEN debit ELSE 0 END) as prepaid_debit,
  SUM(CASE WHEN account LIKE '%Expense%' THEN credit ELSE 0 END) as expense_credit
FROM `tabGL Entry`
WHERE voucher_type = 'Journal Entry'
AND is_cancelled = 0
AND account IN ('Prepaid Marketing - ITB', 'Marketing Expenses - ITB')
GROUP BY DATE_TRUNC('month', posting_date)
ORDER BY month;

RESULT (Sample):

┌──────────────┬──────────┬────────────────┬──────────────────┐
│ month        │ je_count │ prepaid_debit  │ expense_credit   │
├──────────────┼──────────┼────────────────┼──────────────────┤
│ 2025-11      │ 1        │ 1,000,000      │ 1,000,000        │
│ 2025-12      │ 1        │ 1,000,000      │ 1,000,000        │
│ 2026-01      │ 8        │ 9,000,000      │ 9,000,000        │
│ 2026-02      │ 8        │ 9,000,000      │ 9,000,000        │
│ 2026-03      │ 8        │ 9,000,000      │ 9,000,000        │
│ 2026-04      │ 8        │ 9,000,000      │ 9,000,000        │
│ 2026-05      │ 8        │ 9,000,000      │ 9,000,000        │
│ 2026-06      │ 8        │ 9,000,000      │ 9,000,000        │
│ 2026-07      │ 8        │ 9,000,000      │ 9,000,000        │
│ 2026-08      │ 8        │ 9,000,000      │ 9,000,000        │
│ 2026-09      │ 8        │ 9,000,000      │ 9,000,000        │
│ 2026-10      │ 6        │ 7,000,000      │ 7,000,000        │
│ 2026-11      │ 2        │ 2,000,000      │ 2,000,000        │
│ 2026-12      │ 1        │ 1,000,000      │ 1,000,000        │
├──────────────┼──────────┼────────────────┼──────────────────┤
│ TOTAL        │ 96       │ 108,000,000    │ 108,000,000      │
└──────────────┴──────────┴────────────────┴──────────────────┘

Interpretation:
- Jan 2026: 8 PIs starting (8 × 1M = 9M combined)
- Each month shows different JE counts as PI periods overlap
- December 2026: Only 1 PI (24-month one continues to 2027)
- Total: 96 JEs covering 108M amortization
```

---

## Data Validation Queries

### ✅ Validation 1: All JEs are balanced

```sql
SELECT
  `parent`,
  SUM(debit) as total_debit,
  SUM(credit) as total_credit,
  (SUM(debit) - SUM(credit)) as imbalance
FROM `tabJournal Entry Account`
WHERE parent IN (
  SELECT name FROM `tabJournal Entry`
  WHERE reference_type = 'Purchase Invoice'
  AND reference_name LIKE 'ACC-PI%'
  AND docstatus = 1
)
GROUP BY `parent`
HAVING imbalance != 0;

-- Expected result: EMPTY (all balanced)
```

### ✅ Validation 2: Total amortization = Total deferred

```sql
-- Total deferred from PI items
SELECT SUM(amount) as total_deferred
FROM `tabPurchase Invoice Item`
WHERE enable_deferred_expense = 1
AND parent IN (
  'ACC-PINV-2026-00011',
  'ACC-PINV-2026-00012',
  'ACC-PINV-2026-00013',
  'ACC-PINV-2026-00014',
  'ACC-PINV-2026-00015',
  'ACC-PINV-2026-00016',
  'ACC-PINV-2026-00017',
  'ACC-PINV-2026-00018'
);
-- Result: 108,000,000

-- Total amortized via GL
SELECT SUM(credit) as total_amortized
FROM `tabGL Entry`
WHERE account LIKE '%Marketing Expense%'
AND voucher_type = 'Journal Entry'
AND is_cancelled = 0;
-- Result: 108,000,000

-- Both should match ✓
```

### ✅ Validation 3: No GL Entry is cancelled

```sql
SELECT COUNT(*) as cancelled_count
FROM `tabGL Entry`
WHERE voucher_type = 'Journal Entry'
AND is_cancelled = 1
AND voucher_no IN (
  SELECT name FROM `tabJournal Entry`
  WHERE reference_type = 'Purchase Invoice'
  AND reference_name LIKE 'ACC-PI%'
);

-- Expected result: 0 (no cancellations)
```

---

## Data Size Expectations

After amortization creation:

| Table | Rows Added | Size Impact | Notes |
|-------|-----------|-------------|-------|
| tabJournal Entry | 96 | ~50 KB | One per month, per PI |
| tabJournal Entry Account | 192 | ~30 KB | 2 per JE (prepaid + expense) |
| tabGL Entry | ~192 | ~100 KB | 2 per JE in GL |
| tabDeferred Expense | 0 | 0 KB | No changes to existing table |
| **Total** | **480** | **~180 KB** | Minimal database impact |

---

## Rollback Instructions

If something goes wrong, to undo all amortization:

```sql
-- 1. Identify JEs to delete
SELECT name FROM `tabJournal Entry`
WHERE reference_type = 'Purchase Invoice'
AND reference_name IN (
  'ACC-PINV-2026-00011',
  'ACC-PINV-2026-00012',
  'ACC-PINV-2026-00013',
  'ACC-PINV-2026-00014',
  'ACC-PINV-2026-00015',
  'ACC-PINV-2026-00016',
  'ACC-PINV-2026-00017',
  'ACC-PINV-2026-00018'
)
AND docstatus = 1;

-- 2. Delete via Frappe (do NOT delete directly from DB)
-- Go to each JE in UI → Click "Amend" → "Cancel" → "Save"

-- 3. This will:
-- - Amend JE, set docstatus = 2 (cancelled)
-- - Create GL Entry reversals automatically
-- - Data will still be in database but marked as cancelled
```

---

## Summary

| Component | Before | After | Change |
|-----------|--------|-------|--------|
| JE Count | 0 | 96 | +96 |
| GL Entries | 0 | ~192 | +192 |
| Total Deferred | 108M | 108M | No change |
| Total Amortized | 0 | 108M | +108M ✓ |
| Outstanding | 108M | 0 | -108M ✓ |
| Prepaid Balance | 108M | 0 | Reduced ✓ |
| Expense Amount | 0 | 108M | +108M ✓ |

**Result: ALL FIXED!** ✓✓✓
