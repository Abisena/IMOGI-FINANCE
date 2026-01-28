# IMOGI Finance - Deferred Expense Amortization Issue & Solution

**Date:** January 28, 2026
**Issue:** Total Amortized = 0 (belum ada amortisasi yang tercipta)
**Status:** Need to manually generate amortization schedule

---

## Problem Analysis

Dari Deferred Expense Tracker:
```
Total Deferred:      108,000,000 ✓ (recorded)
Total Amortized:     0 ✗ (NO AMORTIZATION!)
Total Outstanding:   108,000,000 ✗ (should decrease as amortized)
```

**8 Expense Requests terdeteksi:**
| Row | ER Number | Amount | Periods | Start Date | PI Status |
|-----|-----------|--------|---------|-----------|-----------|
| 1 | ER-2026-000025 | 12 juta | 12 | 01-11-2025 | ACC-PI |
| 2 | ER-2026-000024 | 24 juta | 24 | 28-01-2026 | ACC-PI |
| 3 | ER-2026-000023 | 12 juta | 12 | 28-01-2026 | ACC-PI |
| 4 | ER-2026-000022 | 12 juta | 12 | 28-01-2026 | ACC-PI |
| 5 | ER-2026-000021 | 12 juta | 12 | 28-01-2026 | ACC-PI |
| 6 | ER-2026-000015 | 12 juta | 12 | 27-01-2026 | ACC-PI |
| 7 | ER-2026-000014 | 12 juta | 12 | 27-11-2025 | ACC-PI |
| 8 | ER-2026-000013 | 12 juta | 12 | 27-01-2026 | ACC-PI |

---

## Root Causes

### ❌ Cause 1: ERPNext Native Scheduler Belum Berjalan
```
The "Process Deferred Accounting" scheduler runs monthly.
If it hasn't run yet, no amortization entries are created.

Status: Background job belum dieksekusi
```

### ❌ Cause 2: PI Items Belum Punya Flag "enable_deferred_expense"
```
Purchase Invoice items perlu:
  □ enable_deferred_expense = 1
  □ deferred_expense_account = [Prepaid Account]
  □ service_start_date = [date]
  □ service_end_date = [date]

Status: Jika kosong = Frappe tidak buat schedule
```

### ❌ Cause 3: Purchase Invoice Belum Submitted
```
Deferred expense posting hanya terjadi saat PI submitted.

Status: Cek PI status di setiap ER
```

### ❌ Cause 4: Manual Amortization Belum Dijalankan
```
Sistem tidak generate Journal Entry manual.
Hanya rely pada Frappe scheduler.

Status: Perlu trigger manual proses
```

---

## Quick Fixes (Order of Execution)

### STEP 1: Check PI Status

```python
# SSH to server atau gunakan Frappe Console

import frappe

# Check semua PI yang linked ke deferred ER
pi_list = frappe.db.get_list(
    "Purchase Invoice",
    filters={
        "docstatus": 1,  # Submitted only
        "imogi_expense_request": ["!=", ""]
    },
    fields=["name", "docstatus", "imogi_expense_request"],
    limit_page_length=0
)

for pi in pi_list:
    print(f"PI: {pi.name}, Status: {pi.docstatus}, ER: {pi.imogi_expense_request}")
```

**Expected:** docstatus = 1 (submitted)

---

### STEP 2: Check PI Item Deferred Flags

```python
# Check individual items
pi_name = "ACC-PINV-2026-00011"  # salah satu dari ER
items = frappe.db.get_list(
    "Purchase Invoice Item",
    filters={
        "parent": pi_name
    },
    fields=[
        "item_code",
        "enable_deferred_expense",
        "deferred_expense_account",
        "service_start_date",
        "service_end_date"
    ]
)

for item in items:
    print(f"""
    Item: {item.item_code}
    Enable Deferred: {item.enable_deferred_expense}
    Prepaid Account: {item.deferred_expense_account}
    Start Date: {item.service_start_date}
    End Date: {item.service_end_date}
    """)
```

**Expected:** Semua fields terisi ✓

---

### STEP 3: Trigger ERPNext Deferred Accounting Process

```bash
# SSH to server
cd ~/frappe-bench

# Run the scheduler manually
bench --site itb-dev.frappe.cloud execute \
  frappe.utils.background_jobs.run_recurring_jobs

# Or specific scheduler
bench --site itb-dev.frappe.cloud execute \
  erpnext.accounts.deferred_revenue.process_deferred_accounting
```

**Or via UI:**
```
Menu → Tools → Scheduled Jobs
Search: "Process Deferred Accounting"
Click: Run Now
```

---

### STEP 4: Verify Amortization Created

```python
# After scheduler runs, check Journal Entries
je_list = frappe.db.get_list(
    "Journal Entry",
    filters={
        "reference_type": "Purchase Invoice",
        "reference_name": ["in", ["ACC-PINV-2026-00011", "ACC-PINV-2026-00012"]],
        "docstatus": 1
    },
    fields=["name", "posting_date", "reference_name"],
    order_by="posting_date asc",
    limit_page_length=0
)

print(f"Total Journal Entries found: {len(je_list)}")
for je in je_list:
    print(f"  {je.name} - {je.posting_date} for PI {je.reference_name}")
```

**Expected:** Multiple entries (one per month)

---

## Solution: Create Custom Amortization Schedule Doctype

Saya akan membuat **custom doctype** untuk menampilkan breakdown bulanan dengan cara:

### Option A: Create New Doctype "Deferred Expense Monthly Schedule"

```
Doctype: Deferred Expense Monthly Schedule
Parent Link: Purchase Invoice Item / Expense Request Item
Child Table: Amortization Detail (month, amount, posting_date, je_link)
```

### Option B: Enhance Existing Report

Add breakdown column ke "Deferred Expense Tracker"

---

## Custom Python Function untuk Manual Amortization

Create file: `imogi_finance/services/amortization_processor.py`

```python
"""Manual amortization processor untuk deferred expenses."""

import frappe
from datetime import date, timedelta
from calendar import monthrange
from frappe import _
from frappe.utils import add_months, flt, getdate


def create_amortization_schedule_for_pi(pi_name: str):
    """
    Generate dan create amortization schedule untuk Purchase Invoice.

    Akan create Journal Entry untuk setiap bulan.
    """

    # Get PI
    pi = frappe.get_doc("Purchase Invoice", pi_name)

    if pi.docstatus != 1:
        frappe.throw(_("PI must be submitted first"))

    # Get deferred items
    deferred_items = [
        item for item in pi.items
        if item.get("enable_deferred_expense")
    ]

    if not deferred_items:
        frappe.throw(_("No deferred items found in this PI"))

    # Generate schedule per item
    all_schedules = []

    for item in deferred_items:
        amount = flt(item.amount)
        periods = int(item.get("deferred_expense_periods") or 12)
        start_date = getdate(item.service_start_date)
        prepaid_account = item.deferred_expense_account
        expense_account = item.expense_head  # atau dari item

        # Generate schedule
        schedule = _generate_monthly_schedule(
            amount=amount,
            periods=periods,
            start_date=start_date,
            prepaid_account=prepaid_account,
            expense_account=expense_account,
            pi_name=pi_name,
            item_code=item.item_code
        )

        all_schedules.extend(schedule)

    # Sort by posting_date
    all_schedules.sort(key=lambda x: x["posting_date"])

    # Create Journal Entries
    je_names = []
    for schedule_entry in all_schedules:
        je_name = _create_deferred_expense_je(schedule_entry, pi_name)
        je_names.append(je_name)

    return {
        "pi_name": pi_name,
        "total_schedules": len(all_schedules),
        "journal_entries": je_names
    }


def _generate_monthly_schedule(
    amount: float,
    periods: int,
    start_date: date,
    prepaid_account: str,
    expense_account: str,
    pi_name: str,
    item_code: str
) -> list:
    """Generate monthly breakdown."""

    schedule = []
    monthly_amount = amount / periods
    remaining = amount

    for month_idx in range(periods):
        # Final month gets remainder (handle rounding)
        if month_idx == periods - 1:
            period_amount = remaining
        else:
            period_amount = flt(monthly_amount)

        posting_date = add_months(start_date, month_idx)

        schedule.append({
            "period": month_idx + 1,
            "posting_date": posting_date,
            "amount": period_amount,
            "prepaid_account": prepaid_account,
            "expense_account": expense_account,
            "pi_name": pi_name,
            "item_code": item_code,
            "description": f"Deferred Expense Amortization - {item_code} (Month {month_idx + 1})"
        })

        remaining -= period_amount

    return schedule


def _create_deferred_expense_je(schedule_entry: dict, pi_name: str) -> str:
    """Create individual Journal Entry untuk satu bulan."""

    # Check jika sudah ada JE untuk posting_date ini
    existing_je = frappe.db.get_value(
        "Journal Entry",
        {
            "reference_type": "Purchase Invoice",
            "reference_name": pi_name,
            "posting_date": schedule_entry["posting_date"],
            "docstatus": 1
        },
        "name"
    )

    if existing_je:
        return existing_je

    # Create new JE
    je_doc = frappe.new_doc("Journal Entry")
    je_doc.posting_date = schedule_entry["posting_date"]
    je_doc.reference_type = "Purchase Invoice"
    je_doc.reference_name = pi_name
    je_doc.description = schedule_entry["description"]
    je_doc.remark = f"Auto-generated amortization for {schedule_entry['item_code']}"

    # Account 1: Prepaid Account (Debit)
    je_doc.append("accounts", {
        "account": schedule_entry["prepaid_account"],
        "debit": schedule_entry["amount"],
        "debit_in_account_currency": schedule_entry["amount"],
        "project": frappe.db.get_value("Purchase Invoice", pi_name, "project")
    })

    # Account 2: Expense Account (Credit)
    je_doc.append("accounts", {
        "account": schedule_entry["expense_account"],
        "credit": schedule_entry["amount"],
        "credit_in_account_currency": schedule_entry["amount"],
        "project": frappe.db.get_value("Purchase Invoice", pi_name, "project")
    })

    je_doc.insert(ignore_permissions=True)
    je_doc.submit()

    return je_doc.name


@frappe.whitelist()
def get_amortization_schedule(pi_name: str) -> dict:
    """Get breakdown schedule untuk satu PI."""

    pi = frappe.get_doc("Purchase Invoice", pi_name)
    deferred_items = [i for i in pi.items if i.get("enable_deferred_expense")]

    schedule = []

    for item in deferred_items:
        amount = flt(item.amount)
        periods = int(item.get("deferred_expense_periods") or 12)
        start_date = getdate(item.service_start_date)

        monthly = amount / periods
        remaining = amount

        for month_idx in range(periods):
            if month_idx == periods - 1:
                period_amount = remaining
            else:
                period_amount = flt(monthly)

            posting_date = add_months(start_date, month_idx)

            schedule.append({
                "bulan": month_idx + 1,
                "posting_date": str(posting_date),
                "amount": period_amount,
                "item_code": item.item_code,
                "description": item.description
            })

            remaining -= period_amount

    # Sort by date
    schedule.sort(key=lambda x: x["posting_date"])

    return {
        "pi": pi_name,
        "total_deferred": sum(i.amount for i in deferred_items),
        "schedule": schedule
    }
```

---

## Manual Run (Frappe Console)

```javascript
// Buka: http://itb-dev.frappe.cloud/app/home
// Press Ctrl+K → Frappe Console

// Get schedule
frappe.call({
    method: 'imogi_finance.services.amortization_processor.get_amortization_schedule',
    args: {
        pi_name: 'ACC-PINV-2026-00011'
    },
    callback: (r) => {
        console.log(r.message);
        // Will show breakdown 12 bulan dengan amounts
    }
});

// Create amortization JE
frappe.call({
    method: 'imogi_finance.services.amortization_processor.create_amortization_schedule_for_pi',
    args: {
        pi_name: 'ACC-PINV-2026-00011'
    },
    callback: (r) => {
        console.log('Amortization created:', r.message);
        // Will show list of JE created
    }
});
```

---

## Expected Result After Running

**Before:**
```
General Ledger - Prepaid Marketing Expenses:
  No entries
```

**After:**
```
General Ledger - Prepaid Marketing Expenses:
  28-01-2026: Debit 1,000,000 (JE-ACC-1)
  28-02-2026: Debit 1,000,000 (JE-ACC-2)
  31-03-2026: Debit 1,000,000 (JE-ACC-3)
  30-04-2026: Debit 1,000,000 (JE-ACC-4)
  31-05-2026: Debit 1,000,000 (JE-ACC-5)
  30-06-2026: Debit 1,000,000 (JE-ACC-6)
  31-07-2026: Debit 1,000,000 (JE-ACC-7)
  31-08-2026: Debit 1,000,000 (JE-ACC-8)
  30-09-2026: Debit 1,000,000 (JE-ACC-9)
  31-10-2026: Debit 1,000,000 (JE-ACC-10)
  30-11-2026: Debit 1,000,000 (JE-ACC-11)
  31-12-2026: Debit 1,000,000 (JE-ACC-12)
  Balance: 0 ✓
```

**Deferred Expense Tracker Report:**
```
Total Deferred:      12,000,000
Total Amortized:     12,000,000 ✓ (ALL POSTED!)
Total Outstanding:   0
```

---

## Action Items

### 1️⃣ Check Current PI Status
```bash
Run SQL:
SELECT name, docstatus, imogi_expense_request
FROM `tabPurchase Invoice`
WHERE imogi_expense_request IS NOT NULL
LIMIT 10;

Expected: All docstatus = 1
```

### 2️⃣ Check PI Item Configuration
```bash
For each PI, verify:
  □ enable_deferred_expense = 1
  □ deferred_expense_account = [account]
  □ service_start_date = [date]
  □ service_end_date = [date]
  □ deferred_expense_periods = [number]
```

### 3️⃣ Run Manual Amortization (if needed)
```bash
# Create Python file & run
python -c "
import sys
sys.path.insert(0, '/home/frappe/frappe-bench/apps/imogi_finance')
from imogi_finance.services.amortization_processor import create_amortization_schedule_for_pi
result = create_amortization_schedule_for_pi('ACC-PINV-2026-00011')
print(result)
"
```

### 4️⃣ Verify via Report
```
Deferred Expense Tracker:
  Total Amortized should now be > 0
  Outstanding should decrease
```

---

## Summary

| Item | Status | Fix |
|------|--------|-----|
| Total Deferred: 108M | ✓ OK | No action |
| Total Amortized: 0 | ✗ PROBLEM | Run amortization processor |
| Outstanding: 108M | ✗ SHOULD BE 0 | After amortization done |

**Next Step:** Implement `amortization_processor.py` dan run untuk generate JE bulanan!
