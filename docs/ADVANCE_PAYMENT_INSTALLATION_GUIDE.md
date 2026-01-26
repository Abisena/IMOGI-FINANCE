# Migration Instructions for Advance Payment Module

## Overview
Modul Advance Payment dan Expense Claim sudah berhasil didaftarkan dan file-file berikut telah dibuat:

## Files Created/Updated

### 1. Report Files
- `/imogi_finance/advance_payment_native/report/advance_payment_dashboard/advance_payment_dashboard.py`
- `/imogi_finance/advance_payment_native/report/advance_payment_dashboard/advance_payment_dashboard.json`
- `/imogi_finance/advance_payment_native/report/advance_payment_dashboard/__init__.py`

### 2. JavaScript Files
- `/imogi_finance/public/js/expense_claim.js` (NEW)

### 3. Documentation
- `/imogi_finance/advance_payment_native/README.md`

### 4. Updated Files
- `/imogi_finance/fixtures/workspace.json` - Added Expense Claim and Advance Payment Dashboard shortcuts
- `/imogi_finance/hooks.py` - Added Expense Claim JS hook and Report fixtures
- `/imogi_finance/advance_payment_native/expense_claim_advances.py` - Added get_allocated_advances function

## Manual Installation Steps

Karena kita tidak bisa langsung menjalankan bench migrate, lakukan langkah-langkah berikut:

### Step 1: Pindah ke Bench Directory
```bash
# Cari bench directory Anda
cd /path/to/your/frappe-bench
# Contoh: cd ~/frappe-bench atau cd /home/frappe/frappe-bench
```

### Step 2: Import Report
```bash
# Import report JSON ke database
bench --site [site-name] console

# Dalam console:
import frappe
from frappe.modules.import_file import import_file_by_path

# Import report
import_file_by_path("/path/to/imogi_finance/advance_payment_native/report/advance_payment_dashboard/advance_payment_dashboard.json")
frappe.db.commit()
```

### Step 3: Import Workspace
```bash
# Import updated workspace
bench --site [site-name] import-doc fixtures/workspace.json
```

### Step 4: Migrate
```bash
# Run migrate to apply all changes
bench --site [site-name] migrate
```

### Step 5: Clear Cache
```bash
# Clear cache untuk memastikan perubahan terimplementasi
bench --site [site-name] clear-cache
bench restart
```

## Alternative: Manual Database Import

Jika bench console tidak tersedia, Anda bisa:

### Option A: Via ERPNext UI
1. Login ke ERPNext
2. Go to: **Developer > Report > New**
3. Buat Report baru dengan data dari `advance_payment_dashboard.json`:
   - Report Name: `Advance Payment Dashboard`
   - Module: `Imogi Finance`
   - Reference DocType: `Payment Ledger Entry`
   - Report Type: `Script Report`
   - Is Standard: ✓
   
4. Save

5. Go to: **Setup > Workspace > FINANCE IMOGI**
6. Edit workspace dan tambahkan shortcuts:
   - Expense Claim (DocType)
   - Advance Payment Dashboard (Report)

### Option B: Via SQL (Advanced)
```sql
-- Insert report
INSERT INTO `tabReport` (
    name, report_name, ref_doctype, report_type, 
    is_standard, module, disabled
) VALUES (
    'Advance Payment Dashboard',
    'Advance Payment Dashboard',
    'Payment Ledger Entry',
    'Script Report',
    1,
    'Imogi Finance',
    0
);
```

## Verification

Setelah instalasi, verify dengan:

### 1. Check Report
- Navigate to: **FINANCE IMOGI Workspace**
- Look for: **Advance Payment** section
- Click: **Advance Payment Dashboard**
- Report harus terbuka tanpa error

### 2. Check Expense Claim
- Go to: **HR > Expense Claim**
- Open atau buat Expense Claim baru
- Verify button "View Employee Advances" muncul
- Setelah submit, verify "Link Employee Advances" muncul

### 3. Test Functionality
```bash
# Test via console
bench --site [site-name] console

# Test get_employee_advances
import frappe
advances = frappe.call(
    'imogi_finance.advance_payment_native.expense_claim_advances.get_employee_advances',
    employee='EMP-00001',
    company='Your Company'
)
print(advances)
```

## Troubleshooting

### Report tidak muncul
1. Check file permissions:
```bash
chmod -R 755 imogi_finance/advance_payment_native/report/
```

2. Verify module name di JSON file matches dengan hooks.py

3. Clear cache dan restart:
```bash
bench --site [site-name] clear-cache
bench restart
```

### JavaScript tidak loaded
1. Check file ada di `/imogi_finance/public/js/expense_claim.js`
2. Clear cache browser (Ctrl+Shift+R atau Cmd+Shift+R)
3. Check browser console untuk errors

### Workspace tidak update
1. Export workspace fixture:
```bash
bench --site [site-name] export-fixtures
```

2. Re-import workspace:
```bash
bench --site [site-name] import-doc imogi_finance/fixtures/workspace.json
```

## Files Summary

### New Files (5)
1. `imogi_finance/advance_payment_native/report/__init__.py`
2. `imogi_finance/advance_payment_native/report/advance_payment_dashboard/__init__.py`
3. `imogi_finance/advance_payment_native/report/advance_payment_dashboard/advance_payment_dashboard.json`
4. `imogi_finance/advance_payment_native/report/advance_payment_dashboard/advance_payment_dashboard.py`
5. `imogi_finance/public/js/expense_claim.js`
6. `imogi_finance/advance_payment_native/README.md`

### Modified Files (3)
1. `imogi_finance/fixtures/workspace.json` - Added shortcuts
2. `imogi_finance/hooks.py` - Added hooks and fixtures
3. `imogi_finance/advance_payment_native/expense_claim_advances.py` - Added functions

### Deleted Files (1)
1. `imogi_finance/advance_payment_native/advance_payment_dashboard.json` (old location)

## Next Steps

1. Commit changes to git:
```bash
git add .
git commit -m "feat: Add Advance Payment module with Expense Claim integration

- Add Advance Payment Dashboard report
- Add Expense Claim JS customization
- Update workspace with new shortcuts
- Add auto-allocation for employee advances"
```

2. Push to repository:
```bash
git push origin main
```

3. Deploy to server (if applicable)

## Support

Jika ada masalah saat instalasi, silakan:
1. Check error log: `tail -f ~/frappe-bench/logs/[site-name].log`
2. Check browser console untuk JavaScript errors
3. Verify all files exist dan memiliki permissions yang benar

---

**Status**: ✅ Module ready for installation
**Version**: 1.0.0
**Date**: 2026-01-24
