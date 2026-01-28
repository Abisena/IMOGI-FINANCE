# Deferred Expense Amortization - Lookup Guide

**Date:** January 28, 2026
**Sistem:** IMOGI Finance + ERPNext v15
**Purpose:** Cara melihat breakdown amortisasi bulanan (12 bulan)

---

## Skenario Anda

```
Purchase Invoice: ACC-PINV-2026-00011
- Total Amount: 12,000,000 (Rp 12 juta)
- Deferred Expense Account: Marketing Expenses - ITB
- Service Start Date: 28-01-2026
- Service End Date: 28-01-2027
- Period: 12 bulan
- Enable Deferred Expense: ✓ (checked)

Target Breakdown:
  Bulan 1 (Jan 2026): 1,000,000
  Bulan 2 (Feb 2026): 1,000,000
  ...
  Bulan 12 (Dec 2026): 1,000,000
  Total: 12,000,000 ✓
```

---

# Cara 1: Lihat di Deferred Expense Tracker Report

## Step 1: Navigate ke Report

**Option A: Direct URL**
```
http://itb-dev.frappe.cloud/app/query-report/Deferred%20Expense%20Tracker
```

**Option B: Dari Menu**
```
Menu → IMOGI Finance → Reports → Deferred Expense Tracker
```

## Step 2: Filter Report

**Filter Fields:**
```
┌────────────────────────────────────────┐
│ Deferred Expense Tracker               │
├────────────────────────────────────────┤
│                                        │
│ Filters:                               │
│  Prepaid Account:  [________________]  │
│  From Date:        [28-01-2026]        │
│  To Date:          [28-01-2027]        │
│  ER Status:        [All]               │
│                                        │
│  [Apply Filters]                       │
│                                        │
└────────────────────────────────────────┘
```

### Filters to Set:
```
Prepaid Account:  Marketing Expenses - ITB
From Date:        28-01-2026
To Date:          28-01-2027
ER Status:        (leave blank or select)

Click: [Apply Filters]
```

## Step 3: Result - Table View

**Expected Output:**
```
┌──────────────────┬─────────────┬──────────┬─────────────────┬──────────┐
│ ER Name          │ Item Code   │ Amount   │ PI Link         │ Balance  │
├──────────────────┼─────────────┼──────────┼─────────────────┼──────────┤
│ BER-2026-00001   │ SERV-001    │ 12 juta  │ ACC-PINV-2026...│ 12 juta  │
│                  │             │          │ (Submitted)     │          │
└──────────────────┴─────────────┴──────────┴─────────────────┴──────────┘

Columns yang Terlihat:
  ✓ Expense Request name
  ✓ Item details
  ✓ Amount deferred
  ✓ Linked PI status
  ✓ Outstanding balance
```

**Kelemahan:** Report ini hanya menunjukkan level Expense Request + Item, **BUKAN breakdown bulanan**.

---

# Cara 2: Lihat di Journal Entry (GL Entry)

## Step 1: Understand Deferred Expense Posting

Ketika Deferred Expense posting terjadi:
```
Tanggal: 28-01-2026

Journal Entry (otomatis dibuat oleh Frappe):
┌─────────────────────────────────────────────┐
│ Journal Entry: ACC-JV-2026-00001            │
├─────────────────────────────────────────────┤
│ Posting Date: 28-01-2026                    │
│ Against Doctype: Purchase Invoice           │
│ Against Name: ACC-PINV-2026-00011           │
│                                             │
│ Account Entry:                              │
│ ┌──────────────────┬──┬──────────────────┐ │
│ │ Account          │Dr│ Cr               │ │
│ ├──────────────────┼──┼──────────────────┤ │
│ │ Prepaid Exp.     │  │ 12,000,000 (Cr) │ │
│ │ (Asset)          │  │                  │ │
│ │                  │  │                  │ │
│ │ Marketing Exp    │  │                  │ │
│ │ (Expense)        │  │ 0                │ │
│ │ (Wait for sched) │  │                  │ │
│ └──────────────────┴──┴──────────────────┘ │
└─────────────────────────────────────────────┘

Status: Posted (tidak ada entry untuk amortisasi bulanan YET)
```

## Step 2: Cek General Ledger untuk Prepaid Account

**Navigate to:**
```
Menu → Accounting → General Ledger
OR
Report → General Ledger
```

### Filters:
```
Account:        [Prepaid Marketing Expenses or similar]
From Date:      28-01-2026
To Date:        28-01-2027
Company:        Your Company
```

### Result - Expected Pattern:

```
GENERAL LEDGER: Prepaid Marketing Expenses - ITB
═════════════════════════════════════════════════

Posting Date│ Ref Type        │ Ref Name           │ Dr       │ Cr          │ Balance
────────────┼─────────────────┼────────────────────┼──────────┼─────────────┼──────────
28-01-2026  │ Journal Entry   │ ACC-JV-2026-00001  │          │ 12,000,000  │ 12 juta
28-02-2026  │ Journal Entry   │ ACC-JV-2026-00002  │ 1,000,000│             │ 11 juta
31-03-2026  │ Journal Entry   │ ACC-JV-2026-00003  │ 1,000,000│             │ 10 juta
30-04-2026  │ Journal Entry   │ ACC-JV-2026-00004  │ 1,000,000│             │ 9 juta
31-05-2026  │ Journal Entry   │ ACC-JV-2026-00005  │ 1,000,000│             │ 8 juta
30-06-2026  │ Journal Entry   │ ACC-JV-2026-00006  │ 1,000,000│             │ 7 juta
31-07-2026  │ Journal Entry   │ ACC-JV-2026-00007  │ 1,000,000│             │ 6 juta
31-08-2026  │ Journal Entry   │ ACC-JV-2026-00008  │ 1,000,000│             │ 5 juta
30-09-2026  │ Journal Entry   │ ACC-JV-2026-00009  │ 1,000,000│             │ 4 juta
31-10-2026  │ Journal Entry   │ ACC-JV-2026-00010  │ 1,000,000│             │ 3 juta
30-11-2026  │ Journal Entry   │ ACC-JV-2026-00011  │ 1,000,000│             │ 2 juta
31-12-2026  │ Journal Entry   │ ACC-JV-2026-00012  │ 1,000,000│             │ 1 juta
28-01-2027  │ Journal Entry   │ ACC-JV-2026-00013  │ 1,000,000│             │ 0
```

**Interpretasi:**
- Setiap bulan ada Journal Entry baru
- Debit ke Prepaid Account (mengurangi aset) = 1,000,000
- Credit ke Expense Account (mencatat biaya) = 1,000,000
- Balance Prepaid menurun dari 12M → 0

---

# Cara 3: Lihat Detail JE untuk Setiap Bulan

## Step 1: Click Journal Entry Bulanan

Dari General Ledger, klik salah satu JV reference:
```
Contoh: Click "ACC-JV-2026-00002" (Februari)
```

## Step 2: Lihat Journal Entry Detail

**Form akan tampilkan:**
```
┌────────────────────────────────────────────────────┐
│ Journal Entry: ACC-JV-2026-00002                   │
│ Status: Posted                                     │
├────────────────────────────────────────────────────┤
│                                                    │
│ Posting Date: 28-02-2026                          │
│ Reference Type: Purchase Invoice                  │
│ Reference: ACC-PINV-2026-00011                    │
│ Description: Deferred Expense Amortization       │
│             (or similar)                          │
│                                                    │
│ Accounts Table:                                    │
│ ┌────────────────────────┬──────┬──────┐         │
│ │ Account                │ Dr   │ Cr   │         │
│ ├────────────────────────┼──────┼──────┤         │
│ │ Prepaid Marketing      │1 juta│      │         │
│ │ Expenses - ITB         │      │      │         │
│ │                        │      │      │         │
│ │ Marketing Expenses     │      │1 juta│         │
│ │ - ITB (Expense)        │      │      │         │
│ └────────────────────────┴──────┴──────┘         │
│                                                    │
│ Status: Posted (Read-only)                        │
│                                                    │
└────────────────────────────────────────────────────┘
```

**Detail Breakdown:**
- **Account 1:** Prepaid Marketing Expenses - ITB (Asset)
  - Debit: 1,000,000
  - (Mengurangi aset yang ditangguhkan)

- **Account 2:** Marketing Expenses - ITB (Expense)
  - Credit: 1,000,000
  - (Mencatat sebagai biaya bulan ini)

---

# Cara 4: Direct SQL Query (Advanced)

Jika ingin lihat breakdown di database langsung:

## Query: Cek Semua Journal Entry untuk PI

```sql
SELECT
    je.name as "Journal Entry",
    je.posting_date as "Posting Date",
    jed.account as "Account",
    jed.debit as "Debit (Rp)",
    jed.credit as "Credit (Rp)",
    jed.account_currency as "Currency"
FROM
    `tabJournal Entry` je
    INNER JOIN `tabJournal Entry Account` jea ON je.name = jea.parent
WHERE
    je.reference_type = "Purchase Invoice"
    AND je.reference_name = "ACC-PINV-2026-00011"
    AND je.docstatus = 1
    AND je.posting_date >= "2026-01-01"
    AND je.posting_date <= "2027-01-31"
ORDER BY
    je.posting_date, je.name;
```

## Expected Result (12 entries):

```
Journal Entry       │ Posting Date │ Account                    │ Debit     │ Credit
────────────────────┼──────────────┼────────────────────────────┼───────────┼───────────
ACC-JV-2026-00001  │ 2026-01-28   │ Prepaid Marketing Exp      │ 1,000,000 │
                   │              │ Marketing Expenses         │           │ 1,000,000
────────────────────┼──────────────┼────────────────────────────┼───────────┼───────────
ACC-JV-2026-00002  │ 2026-02-28   │ Prepaid Marketing Exp      │ 1,000,000 │
                   │              │ Marketing Expenses         │           │ 1,000,000
────────────────────┼──────────────┼────────────────────────────┼───────────┼───────────
ACC-JV-2026-00003  │ 2026-03-31   │ Prepaid Marketing Exp      │ 1,000,000 │
                   │              │ Marketing Expenses         │           │ 1,000,000
────────────────────┼──────────────┼────────────────────────────┼───────────┼───────────
... (repeat 9 more times) ...
────────────────────┼──────────────┼────────────────────────────┼───────────┼───────────
Total              │              │                            │ 12,000,000│ 12,000,000
```

---

# Cara 5: Lihat di Purchase Invoice Form (Embedded View)

## Step 1: Open Purchase Invoice

```
URL: http://itb-dev.frappe.cloud/app/purchase-invoice/ACC-PINV-2026-00011
```

## Step 2: Scroll ke Section "Deferred Expense Schedule"

**Form Section:**
```
┌─────────────────────────────────────────────────────┐
│ Deferred Expense Schedule                           │
├─────────────────────────────────────────────────────┤
│                                                     │
│ This section shows expected amortization schedule  │
│ calculated at time of posting:                     │
│                                                     │
│ Posting Date│ Amount    │ Account         │ Status │
│ ────────────┼───────────┼─────────────────┼────────│
│ 28-01-2026  │ 1,000,000 │ Marketing Exp   │ Posted │
│ 28-02-2026  │ 1,000,000 │ Marketing Exp   │ Pending│
│ 31-03-2026  │ 1,000,000 │ Marketing Exp   │ Pending│
│ 30-04-2026  │ 1,000,000 │ Marketing Exp   │ Pending│
│ 31-05-2026  │ 1,000,000 │ Marketing Exp   │ Pending│
│ 30-06-2026  │ 1,000,000 │ Marketing Exp   │ Pending│
│ 31-07-2026  │ 1,000,000 │ Marketing Exp   │ Pending│
│ 31-08-2026  │ 1,000,000 │ Marketing Exp   │ Pending│
│ 30-09-2026  │ 1,000,000 │ Marketing Exp   │ Pending│
│ 31-10-2026  │ 1,000,000 │ Marketing Exp   │ Pending│
│ 30-11-2026  │ 1,000,000 │ Marketing Exp   │ Pending│
│ 31-12-2026  │ 1,000,000 │ Marketing Exp   │ Pending│
│                                                     │
│ Total Scheduled: Rp 12,000,000                     │
│ Total Posted: Rp 1,000,000 (Januari)              │
│ Remaining: Rp 11,000,000                           │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**Status Breakdown:**
- `Posted`: Already created Journal Entry
- `Pending`: Akan diproses oleh scheduler

---

# Cara 6: Monitor via "Deferred Expense" DocType (if exists)

## Step 1: Check if Deferred Expense DocType Exists

```
Try to navigate:
Menu → IMOGI Finance → (look for Deferred Expense)
OR
Search: Deferred Expense
```

## If DocType Exists:

```
┌──────────────────────────────────────────┐
│ Deferred Expense List                    │
├──────────────────────────────────────────┤
│                                          │
│ Filter:                                  │
│  Purchase Invoice: ACC-PINV-2026-00011  │
│  [Apply]                                 │
│                                          │
│ Results:                                 │
│ ┌────────────────┬────────┬──────────┐  │
│ │ Name           │ Amount │ Period   │  │
│ ├────────────────┼────────┼──────────┤  │
│ │ DExp-001-Jan26 │ 1 juta │ 01-2026  │  │
│ │ DExp-001-Feb26 │ 1 juta │ 02-2026  │  │
│ │ ... (12 rows)  │        │          │  │
│ └────────────────┴────────┴──────────┘  │
│                                          │
└──────────────────────────────────────────┘
```

---

# Amortisasi Calculation Logic

## Formula yang Digunakan:

```
Total Amount:           12,000,000
Start Date:             28-01-2026
End Date:               28-01-2027
Number of Periods:      12

Monthly Amortization:
  = Total Amount ÷ Number of Periods
  = 12,000,000 ÷ 12
  = 1,000,000 per bulan

Schedule:
  Bulan 1:  28-01-2026 → 1,000,000
  Bulan 2:  28-02-2026 → 1,000,000
  Bulan 3:  31-03-2026 → 1,000,000
  ...
  Bulan 12: 31-12-2026 → 1,000,000 (atau 28-01-2027)

  Total: 12,000,000 ✓
```

---

# Verification Checklist

```
□ Deferred Expense Tracker Report menunjukkan PI linked
□ General Ledger Prepaid Account menunjukkan posting 12 kali
□ Setiap Journal Entry ada debit 1,000,000 untuk Prepaid
□ Setiap Journal Entry ada credit 1,000,000 untuk Expense
□ Total Debit = Total Credit = 12,000,000
□ Posting date berspasi setiap akhir bulan (atau tanggal yang sama)
□ PI form menunjukkan Deferred Expense Schedule dengan 12 baris
□ Status: "Posted" untuk bulan-bulan yang sudah diproses
□ Status: "Pending" untuk bulan-bulan yang belum diproses
```

---

# Troubleshooting: Amortisasi Tidak Muncul

## Kemungkinan 1: Scheduler Belum Berjalan

**Solusi:**
```
1. Go to Menu → Tools → Background Jobs
2. Check: Process Deferred Accounting (Frappe Native)
3. If not exist, run manually:
   Menu → Accounting → Tools →
   Process Deferred Accounting
```

## Kemungkinan 2: Deferred Settings Belum Diset

**Cek:**
```
Menu → IMOGI Finance → Settings →
Expense Deferred Settings

Pastikan:
  ✓ Enable Deferred Expense: checked
  ✓ Prepaid Account (Marketing Expenses) di-whitelist
  ✓ Mapping sudah ada:
    Prepaid Account → Expense Account
    Default Periods: 12
    Is Active: ✓
```

## Kemungkinan 3: PI Item Belum Ada Flag "Enable Deferred"

**Cek di PI:**
```
Open: ACC-PINV-2026-00011
Scroll ke Item Details

Untuk setiap item:
  □ enable_deferred_expense: checked
  □ deferred_expense_account: set
  □ deferred_start_date: set
  □ deferred_periods: 12
```

---

# Summary: Where to Look for Amortization

| Lokasi | Breakdown Level | Update Frequency |
|--------|-----------------|------------------|
| **Deferred Expense Tracker Report** | Item-level | Real-time |
| **General Ledger (Prepaid Account)** | Monthly entries | Real-time |
| **Journal Entry Detail** | Per entry | Real-time |
| **Purchase Invoice Form** | Schedule table | Real-time |
| **Database Query** | Raw data | Real-time |

---

**Kesimpulan:**

Mapping amortisasi 12 bulan × 1 juta dapat dilihat di:
1. ✅ **General Ledger** (paling mudah) - lihat 12 JE entry
2. ✅ **Purchase Invoice Form** - lihat Deferred Schedule section
3. ✅ **Individual Journal Entry** - lihat detail bulanan
4. ✅ **Deferred Expense Tracker** - lihat summary level

Semua tempat menunjukkan **breakdown yang sama**: 12,000,000 dibagi 12 = 1 juta/bulan ✓
