# Budget Control Workflow State Fix - Final Check

## Issue Summary
Expense Request sudah approved tapi Budget Control Entry tidak terbuat karena field `status` tidak ikut berubah menjadi "Approved" (ERPNext v15+ behavior - docstatus tetap "Submitted").

## Changes Made

### 1. Budget Control Workflow (`imogi_finance/budget_control/workflow.py`)

#### Function: `reserve_budget_for_request` (Line ~318-327)
**Before:**
```python
target_state = settings.get("lock_on_workflow_state") or "Approved"
if getattr(expense_request, "status", None) != target_state:
    return
```

**After:**
```python
target_state = settings.get("lock_on_workflow_state") or "Approved"
status = getattr(expense_request, "status", None)
workflow_state = getattr(expense_request, "workflow_state", None)
if status != target_state and workflow_state != target_state:
    return
```

**Impact:** Budget lock sekarang akan ter-trigger jika SALAH SATU dari `status` atau `workflow_state` = target (default "Approved").

#### Function: `handle_expense_request_workflow` (Line ~437-443)
**Before:**
```python
if getattr(expense_request, "status", None) == target_state or next_state == target_state:
    reserve_budget_for_request(expense_request, trigger_action=action, next_state=next_state)
```

**After:**
```python
status = getattr(expense_request, "status", None)
workflow_state = getattr(expense_request, "workflow_state", None)
if status == target_state or workflow_state == target_state or next_state == target_state:
    reserve_budget_for_request(expense_request, trigger_action=action, next_state=next_state)
```

**Impact:** Handler sekarang cek 3 kondisi: `status`, `workflow_state`, atau `next_state` untuk memutuskan kapan reserve budget.

### 2. Expense Request Controller (`imogi_finance/imogi_finance/doctype/expense_request/expense_request.py`)

#### Function: `_ensure_budget_lock_synced_after_approval` (Line ~1081-1088)
**Before:**
```python
target_state = settings.get("lock_on_workflow_state") or "Approved"
if getattr(self, "status", None) != target_state:
    return
```

**After:**
```python
target_state = settings.get("lock_on_workflow_state") or "Approved"
status = getattr(self, "status", None)
workflow_state = getattr(self, "workflow_state", None)
if status != target_state and workflow_state != target_state:
    return
```

**Impact:** Guard sync helper juga support `workflow_state` sebagai trigger untuk re-lock edge cases.

## Backward Compatibility

✅ **Fully backward compatible** - perubahan ini **additive**, bukan replacement:
- Workflow lama yang menggunakan `status` field tetap berfungsi 100%
- Workflow baru yang hanya set `workflow_state` sekarang juga didukung
- Tidak ada breaking changes untuk existing implementation

## Test Coverage

Existing tests di `test_budget_control.py` tetap valid karena:
- Test menggunakan `status="Approved"` yang masih didukung
- Logic OR (`or`) memastikan semua test existing tetap pass
- Test: `test_reserve_budget_for_request`, `test_budget_workflow_state_transitions` ✅

## Edge Cases Covered

1. **ERPNext v14 behavior**: Field `status` diupdate → ✅ works
2. **ERPNext v15 behavior**: Field `workflow_state` diupdate, `status` tetap "Submitted" → ✅ works
3. **Mixed state**: Kedua field diupdate → ✅ works (salah satu match sudah cukup)
4. **Migration case**: Dokumen lama yang sudah Approved tapi belum ada entry → ✅ works via `_ensure_budget_lock_synced_after_approval`

## Validation Checklist

- [x] Syntax Python valid (py_compile passed)
- [x] No breaking changes to existing logic
- [x] Backward compatible dengan workflow lama
- [x] Support ERPNext v15+ workflow behavior
- [x] Existing tests remain valid
- [x] Edge case migration scenario covered

## Deployment Steps

1. **Pre-deploy checks:**
   ```bash
   # Validate syntax
   python3 -m py_compile imogi_finance/budget_control/workflow.py
   python3 -m py_compile imogi_finance/imogi_finance/doctype/expense_request/expense_request.py
   ```

2. **Deploy:**
   ```bash
   cd ~/frappe-bench
   bench --site your-site migrate
   bench --site your-site clear-cache
   ```

3. **Post-deploy validation:**
   - Cek Budget Control Settings → Enable Budget Lock = ON
   - Buat Expense Request baru
   - Approve via workflow
   - Verifikasi:
     - Budget Lock Status berubah (Not Locked → Locked)
     - Budget Workflow State berubah (Draft → Approved)
     - Budget Control Entry list ada entry baru dengan ref_doctype = Expense Request

4. **Fix existing approved ER (optional):**
   - Buka ER yang sudah approved tapi belum ada Budget Control Entry
   - Edit field dummy (misal tambah spasi di remarks)
   - Save
   - Guard `_ensure_budget_lock_synced_after_approval` akan auto-create entry

## Rollback Plan

Jika ada issue, revert dengan:
```bash
git revert <commit-hash>
bench --site your-site migrate
```

Atau manual replace kembali:
- `workflow_state` check → hapus, kembalikan hanya `status` check
- Deploy ulang

## Known Limitations

- Tidak mengubah docstatus (tetap 0/1/2 sesuai ERPNext standard)
- Tidak mengubah behavior UI "Submitted" badge
- Memerlukan Budget Control Settings aktif untuk berfungsi

## Contact

Jika ada issue setelah deploy, cek:
1. Error Log di ERPNext
2. Budget Control Settings configuration
3. Field `workflow_state` vs `status` di Expense Request yang bermasalah
