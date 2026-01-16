# Budget Control Entry Debug Guide

## Masalah
Budget Control Entry tidak otomatis terbentuk ketika Expense Request disetujui (Approved).

## Solusi yang Diterapkan

### 1. Event Hook Ditambahkan
File: `imogi_finance/hooks.py`

Menambahkan event handler `handle_budget_workflow` pada:
- `on_update` 
- `on_update_after_submit`

Hook ini akan otomatis memanggil `reserve_budget_for_request()` ketika Expense Request statusnya berubah menjadi "Approved".

### 2. Handler Function Baru
File: `imogi_finance/events/expense_request.py`

Fungsi baru `handle_budget_workflow()` yang:
- Deteksi perubahan workflow state
- Panggil `reserve_budget_for_request()` saat Approved
- Panggil `release_budget_for_request()` saat Rejected
- Logging lengkap untuk troubleshooting

### 3. Enhanced Logging
File: `imogi_finance/budget_control/workflow.py`

Fungsi `reserve_budget_for_request()` diperbaiki dengan:
- Bisa menerima doc object atau string name
- Logging detail di setiap step
- Message ke user (msgprint) untuk feedback
- Return list of created entries

### 4. Browser Console Debug Tools
File: `imogi_finance/public/js/budget_control_debug.js`

JavaScript commands untuk debugging di browser console.

## Cara Testing

### A. Testing Otomatis (setelah bench restart)

1. **Restart bench**:
   ```bash
   bench --site [site-name] restart
   ```

2. **Approve Expense Request baru**:
   - Buat Expense Request baru
   - Submit dan Approve
   - Budget Control Entry harus otomatis terbuat

3. **Check di console log**:
   ```bash
   tail -f ~/frappe-bench/logs/[site-name].log
   ```
   
   Cari log message:
   - `handle_budget_workflow: Calling reserve_budget for ER-XXXX`
   - `reserve_budget_for_request: Created reservation BCE-XXXX`

### B. Testing Manual via Browser Console

1. **Load debug commands**:
   - Buka Expense Request di browser
   - Buka Console (F12 atau Cmd+Option+I)
   - Paste isi file `budget_control_debug.js` atau include via hooks

2. **Run full debug**:
   ```javascript
   debug_budget_control()
   ```
   
   Ini akan check:
   - Budget settings
   - Budget dimensions
   - Budget document existence
   - Existing Budget Control Entries

3. **Manual trigger reserve budget**:
   ```javascript
   // Untuk document yang sedang dibuka
   trigger_reserve_budget()
   
   // Atau untuk document tertentu
   trigger_reserve_budget("ER-2026-000027")
   ```

4. **Check hasil**:
   ```javascript
   check_bce_exists()
   ```

### C. Testing via Python Console

```python
# Login ke bench console
bench --site [site-name] console

# Import modules
import frappe
from imogi_finance.budget_control import workflow

# Load expense request
doc = frappe.get_doc("Expense Request", "ER-2026-000027")

# Manual trigger
entries = workflow.reserve_budget_for_request(doc)

# Check result
print(f"Created entries: {entries}")

# Verify entries exist
bce_list = frappe.get_all(
    "Budget Control Entry",
    filters={
        "ref_doctype": "Expense Request",
        "ref_name": doc.name
    },
    fields=["name", "entry_type", "amount", "docstatus"]
)
print(bce_list)
```

## Troubleshooting

### Budget Control Entry tetap tidak terbuat

1. **Check Budget Control Setting**:
   ```javascript
   check_budget_settings()
   ```
   
   Pastikan:
   - `enable_budget_lock` = checked
   - `lock_on_workflow_state` = "Approved"

2. **Check Budget Document exists**:
   ```javascript
   check_budget_exists()
   ```
   
   Jika tidak ada Budget document untuk Cost Center tersebut:
   - Buat Budget document baru
   - Atau budget check akan di-bypass (lihat log)

3. **Check Expense Request dimensions**:
   ```javascript
   check_budget_dimensions()
   ```
   
   Pastikan ada:
   - Cost Center
   - Items dengan expense account
   - Company
   - Status = "Approved"

4. **Check Error Log**:
   - Web UI: Setup > Error Log
   - Console: `tail -f ~/frappe-bench/logs/[site-name].log`
   - Browser Console: Lihat network tab untuk error response

5. **Check Fiscal Year**:
   - Pastikan Fiscal Year aktif exists
   - Check di System Settings atau User Defaults

### Error Messages

#### "Fiscal Year could not be determined"
- Set default Fiscal Year di System Settings
- Atau set di User Defaults

#### "No approver configured for level X"
- Check Expense Approval Setting
- Pastikan ada approver untuk level tersebut

#### "Insufficient budget"
- Check Budget allocated amount
- Atau gunakan role dengan `allow_budget_overrun_role`

#### "No account totals"
- Pastikan Expense Request ada items
- Pastikan items punya expense_account

## Available Debug Commands

Load di browser console:

```javascript
// 1. Check if Budget Control Entry exists
check_bce_exists()

// 2. Check Budget Control Settings
check_budget_settings()

// 3. Check budget dimensions (cost center, account, etc)
check_budget_dimensions()

// 4. Manual trigger reserve budget
trigger_reserve_budget()

// 5. Check if Budget document exists
check_budget_exists()

// 6. Full debug (runs all checks)
debug_budget_control()

// 7. Reload document
reload_doc()
```

## Expected Behavior Sekarang

1. **Submit Expense Request** → Status = "Pending Review"
   - Tidak ada Budget Control Entry

2. **Approve Expense Request** → Status = "Approved"
   - Hook `handle_budget_workflow` triggered
   - Fungsi `reserve_budget_for_request` called
   - Budget Control Entry created dengan:
     - entry_type = "RESERVATION"
     - direction = "OUT"
     - ref_doctype = "Expense Request"
     - ref_name = [ER-NAME]
   - User melihat success message

3. **Reject Expense Request** → Status = "Rejected"
   - Fungsi `release_budget_for_request` called
   - Budget Control Entry created dengan:
     - entry_type = "RELEASE"
     - direction = "IN"

## Files Changed

1. `imogi_finance/hooks.py` - Added budget workflow hooks
2. `imogi_finance/events/expense_request.py` - Added handle_budget_workflow function
3. `imogi_finance/budget_control/workflow.py` - Enhanced reserve_budget_for_request with logging
4. `imogi_finance/public/js/budget_control_debug.js` - NEW debug commands
5. `BUDGET_CONTROL_DEBUG_GUIDE.md` - This file

## Next Steps

1. **Restart bench** untuk apply changes:
   ```bash
   bench --site [site-name] restart
   ```

2. **Test dengan Expense Request baru**

3. **Monitor logs** untuk error atau warning

4. **Gunakan debug commands** jika ada masalah

5. **Report hasil** testing
