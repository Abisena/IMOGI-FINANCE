# Budget Control Entry - Fix Summary

## 🔍 Root Cause
Budget Control Entry tidak otomatis terbentuk karena **tidak ada event hook** yang memanggil fungsi `reserve_budget_for_request()` ketika Expense Request disetujui.

## ✅ Solusi Implemented

### 1. Event Hook Baru (`hooks.py`)
```python
"Expense Request": {
    "on_update": [
        "imogi_finance.events.expense_request.handle_budget_workflow",
    ],
    "on_update_after_submit": [
        "imogi_finance.events.expense_request.handle_budget_workflow",
    ],
}
```

### 2. Handler Function Baru (`expense_request.py`)
Fungsi `handle_budget_workflow()` yang otomatis:
- Deteksi perubahan workflow state
- Call `reserve_budget_for_request()` saat status → "Approved"
- Call `release_budget_for_request()` saat status → "Rejected"
- Logging lengkap untuk troubleshooting

### 3. Enhanced Logging (`workflow.py`)
Function `reserve_budget_for_request()` diperbaiki:
- Accept doc object atau string name
- Logging detail di setiap step
- User feedback via msgprint
- Return list of created Budget Control Entries

### 4. Browser Console Debug Tools
File JavaScript baru: `public/js/budget_control_debug.js`

7 debug commands:
- `check_bce_exists()` - Check Budget Control Entry
- `check_budget_settings()` - Check settings
- `check_budget_dimensions()` - Check dimensions
- `trigger_reserve_budget()` - Manual trigger
- `check_budget_exists()` - Check Budget doc
- `debug_budget_control()` - Run all checks
- `reload_doc()` - Reload document

### 5. Python Test Script
File: `test_budget_control.py`

4 test functions:
- `test_budget_control_entry_creation(er_name)` - Test specific ER
- `quick_test()` - Test latest approved ER
- `check_all_approved_ers()` - Find ERs missing BCE
- `fix_missing_budget_entries()` - Auto-fix all missing

## 📋 Files Changed

1. ✅ `imogi_finance/hooks.py` - Added budget workflow hooks
2. ✅ `imogi_finance/events/expense_request.py` - Added handler function
3. ✅ `imogi_finance/budget_control/workflow.py` - Enhanced with logging
4. ✅ `imogi_finance/public/js/budget_control_debug.js` - NEW debug commands
5. ✅ `test_budget_control.py` - NEW test script
6. ✅ `BUDGET_CONTROL_DEBUG_GUIDE.md` - Documentation

## 🚀 Next Steps

### 1. Restart Bench
```bash
bench --site itb-dev.j.frappe.cloud restart
```

### 2. Test dengan ER Baru
- Buat Expense Request baru
- Submit → Approve
- Budget Control Entry harus otomatis terbuat

### 3. Test ER Existing (ER-2026-000027)

#### Option A: Via Browser Console
1. Buka ER-2026-000027 di browser
2. Open Console (F12)
3. Load debug script:
   ```javascript
   // Copy paste isi file budget_control_debug.js
   // atau include via hooks
   ```
4. Run:
   ```javascript
   debug_budget_control()
   trigger_reserve_budget()
   ```

#### Option B: Via Python Console
```bash
bench --site itb-dev.j.frappe.cloud console
```

```python
# Load test script
exec(open('test_budget_control.py').read())

# Test specific ER
test_budget_control_entry_creation("ER-2026-000027")

# Or quick test
quick_test()

# Or fix all missing
fix_missing_budget_entries()
```

### 4. Check Logs
```bash
# Terminal 1 - Watch logs
tail -f ~/frappe-bench/logs/itb-dev.j.frappe.cloud.log | grep -i budget

# Terminal 2 - Approve ER
# (via browser)
```

Cari log messages:
- ✅ `handle_budget_workflow: Calling reserve_budget`
- ✅ `reserve_budget_for_request: Created reservation BCE-XXXX`
- ❌ Error messages (jika ada)

## 🐛 Troubleshooting

### Jika Budget Control Entry tetap tidak terbuat:

1. **Check Settings** (via console):
   ```javascript
   check_budget_settings()
   ```
   Pastikan `enable_budget_lock` = true

2. **Check Dimensions**:
   ```javascript
   check_budget_dimensions()
   ```
   Pastikan ada Cost Center, Items, Account

3. **Check Budget Document**:
   ```javascript
   check_budget_exists()
   ```
   Jika tidak ada → akan di-bypass (not an error)

4. **Check Error Log**:
   - Web: Setup > Error Log
   - Console: `tail -f logs/*.log`

5. **Manual Trigger**:
   ```python
   # Via Python console
   import frappe
   from imogi_finance.budget_control import workflow
   
   doc = frappe.get_doc("Expense Request", "ER-2026-000027")
   entries = workflow.reserve_budget_for_request(doc)
   print(entries)
   ```

## 📊 Expected Behavior

### Before Fix
1. Submit ER → Status = "Pending Review" ✅
2. Approve ER → Status = "Approved" ✅
3. Budget Control Entry → ❌ **NOT CREATED**
4. No error message shown

### After Fix
1. Submit ER → Status = "Pending Review" ✅
2. Approve ER → Status = "Approved" ✅
3. Hook triggered → `handle_budget_workflow()` called ✅
4. `reserve_budget_for_request()` called ✅
5. Budget Control Entry created → ✅ **BCE-XXXX**
6. Success message shown to user ✅

## 📝 Log Messages to Watch

Success flow:
```
handle_budget_workflow: ER-2026-000027 - Pending Review -> Approved
handle_budget_workflow: Calling reserve_budget for ER-2026-000027
reserve_budget_for_request: ER-2026-000027 - status=Approved, workflow=Approved, target=Approved
reserve_budget_for_request: Processing 1 slices for ER-2026-000027
reserve_budget_for_request: Budget check for Main/5110-00-000: amount=5000000, available=10000000, ok=True
reserve_budget_for_request: ✅ Created reservation BCE-2026-00002
reserve_budget_for_request: ✅ Completed for ER-2026-000027 with status Locked. Created 1 entries: BCE-2026-00002
handle_budget_workflow: Completed reserve_budget for ER-2026-000027
```

## 🎯 Testing Checklist

- [ ] Bench restarted
- [ ] Test new ER → Budget Control Entry created
- [ ] Test existing ER via browser console
- [ ] Test existing ER via Python console
- [ ] Check logs for success messages
- [ ] Verify Budget Control Entry list shows new entries
- [ ] Test rejection flow (should create RELEASE entry)
- [ ] Document any issues found

## 💡 Quick Commands Reference

### Browser Console
```javascript
// Full debug
debug_budget_control()

// Manual trigger for current document
trigger_reserve_budget()

// Check if entries exist
check_bce_exists()
```

### Python Console
```python
# Load test functions
exec(open('test_budget_control.py').read())

# Quick test
quick_test()

# Test specific ER
test_budget_control_entry_creation("ER-2026-000027")

# Check all and fix
check_all_approved_ers()
fix_missing_budget_entries()
```

### Bash
```bash
# Restart
bench --site itb-dev.j.frappe.cloud restart

# Watch logs
tail -f logs/itb-dev.j.frappe.cloud.log | grep budget

# Python console
bench --site itb-dev.j.frappe.cloud console
```

## 📞 Support

Jika masih ada masalah:
1. Check Error Log (Setup > Error Log)
2. Share log output dari `debug_budget_control()`
3. Share screenshot dari console errors
4. Share hasil `test_budget_control_entry_creation()`

---

**Status**: ✅ Ready for testing
**Last Updated**: 2026-01-16
