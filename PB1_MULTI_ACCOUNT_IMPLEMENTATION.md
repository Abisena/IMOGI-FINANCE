# PB1 Multi-Account Implementation Guide

## 📋 Overview

Implementation untuk mendukung **multiple PB1 payable accounts per branch** dalam satu company. Memungkinkan perusahaan dengan multi-branch untuk menggunakan akun PB1 yang berbeda per cabang/provinsi.

## ✅ What Has Been Implemented

### 1. **Tax Profile PB1 Account** (New Child DocType)
- **Location**: `imogi_finance/doctype/tax_profile_pb1_account/`
- **Purpose**: Child table untuk mapping branch ke PB1 account
- **Fields**:
  - `branch` (Link to Branch) - Required
  - `pb1_payable_account` (Link to Account) - Required

### 2. **Tax Profile Updates**
- **File**: `tax_profile.py`, `tax_profile.json`
- **New Fields**:
  - `enable_pb1_multi_branch` (Check) - Toggle untuk enable multi-branch
  - `pb1_account_mappings` (Table) - Child table untuk mappings
  
- **New Methods**:
  ```python
  def get_pb1_account(self, branch: str = None) -> str:
      """Get PB1 account based on branch or fallback to default."""
  ```

- **New Validations**:
  - `_validate_pb1_mappings()` - Cek duplicate branch
  - Backward compatible dengan existing single account

### 3. **Tax Payment Batch Updates**
- **File**: `tax_payment_batch.py`, `tax_payment_batch.json`
- **New Field**: `branch` (Link to Branch)
- **Updated Logic**: `_ensure_payable_account()` sekarang:
  ```python
  if self.tax_type == "PB1":
      branch = getattr(self, "branch", None)
      if branch and hasattr(profile, "get_pb1_account"):
          self.payable_account = profile.get_pb1_account(branch)
      else:
          # Fallback to default
  ```

### 4. **Tax Operations Updates**
- **File**: `tax_operations.py`
- **Function**: `build_register_snapshot()` updated
- **New Features**:
  - Menghitung `pb1_total` sebagai aggregate dari semua branch
  - Menambahkan `pb1_breakdown` dict per branch jika multi-branch enabled
  - Backward compatible dengan single account

### 5. **PB1 Register Report Updates**
- **File**: `pb1_register.py`, `pb1_register.json`
- **New Features**:
  - Filter `branch` untuk select branch-specific account
  - Column `branch` (conditional) jika multi-branch enabled
  - Auto-resolve PB1 account dari branch mapping

### 6. **Tests**
- **File**: `tests/test_pb1_multi_account.py`
- **Coverage**:
  - Single account (backward compatibility)
  - Multi-branch mapping
  - Fallback behavior
  - Duplicate validation

---

## 🚀 How to Use

### Setup (One-Time per Company)

1. **Enable Multi-Branch PB1**:
   ```
   Go to: Tax Profile > [Your Company]
   Check: ☑ Enable PB1 Multi-Branch Accounts
   ```

2. **Configure Branch Mappings**:
   ```
   In "PB1 Account Mappings" table:
   Row 1: Branch = Jakarta,    PB1 Account = PB1 Jakarta - Company
   Row 2: Branch = Surabaya,   PB1 Account = PB1 Surabaya - Company
   Row 3: Branch = Bandung,    PB1 Account = PB1 Bandung - Company
   ```

3. **Set Default Fallback** (Optional but recommended):
   ```
   "PB1 Payable Account" field = PB1 Default - Company
   (Used for unmapped branches or when branch not specified)
   ```

### Operational Usage

#### Creating Tax Payment Batch

```python
# Manual creation
batch = frappe.new_doc("Tax Payment Batch")
batch.company = "My Company"
batch.tax_type = "PB1"
batch.branch = "Jakarta"  # ← NEW: Specify branch
batch.period_month = 1
batch.period_year = 2026
batch.save()

# System auto-populates payable_account with Jakarta-specific account
```

#### Running PB1 Register

```
Imogi Finance > Reports > PB1 Register
Filters:
  - Company: My Company
  - Branch: Jakarta        ← NEW: Filter by specific branch
  - From Date: 2026-01-01
  - To Date: 2026-01-31

Result: Shows GL entries for Jakarta's PB1 account only
```

#### Tax Period Closing

```python
closing = frappe.get_doc("Tax Period Closing", "CLOSE-2026-01")
closing.generate_snapshot()

# Snapshot now includes:
snapshot = {
    "pb1_total": 150000,  # Total across all branches
    "pb1_breakdown": {
        "Jakarta": 100000,
        "Surabaya": 50000
    }
}
```

---

## 🔄 Backward Compatibility

### Existing Systems (Before Implementation)
✅ **Fully backward compatible!**

- If `enable_pb1_multi_branch = 0` (default):
  - Behavior sama persis seperti sebelumnya
  - Single `pb1_payable_account` digunakan
  - Field `branch` di Tax Payment Batch optional (ignored)

- Existing Tax Profiles **tidak perlu diubah**
- Existing Tax Payment Batch **tetap berfungsi**

### Migration Path

**Option A: Manual (Recommended)**
```
1. Edit Tax Profile
2. Check "Enable PB1 Multi-Branch Accounts"
3. Add mappings manually
4. Going forward, specify branch in new Tax Payment Batches
```

**Option B: Programmatic**
```python
# One-time script to migrate existing setup
def migrate_pb1_to_multi_branch(company, default_branch="Head Office"):
    profile = frappe.get_doc("Tax Profile", company)
    
    if not profile.enable_pb1_multi_branch:
        profile.enable_pb1_multi_branch = 1
        
        # Create mapping for all branches using default account
        branches = frappe.get_all("Branch", filters={"company": company}, pluck="name")
        for branch in branches:
            profile.append("pb1_account_mappings", {
                "branch": branch,
                "pb1_payable_account": profile.pb1_payable_account
            })
        
        profile.save()
        print(f"✅ Migrated {company} to multi-branch PB1")
```

---

## 🎯 Use Cases

### Scenario 1: Multiple Provinces with Different PB1 Rules
```
Jakarta branch   → DKI Jakarta provincial account
Surabaya branch  → East Java provincial account
Medan branch     → North Sumatra provincial account
```

### Scenario 2: Centralized vs Decentralized
```
Head Office branches    → Centralized PB1 account (for settlement)
Regional branches       → Regional PB1 accounts (for local filing)
```

### Scenario 3: Gradual Rollout
```
Phase 1: Enable multi-branch, map only new branches
Phase 2: All branches use mapped accounts
Phase 3: Retire default account
```

---

## ⚠️ Important Notes

### Validations
- ✅ Duplicate branch in mappings → **Blocked** (validation error)
- ✅ Missing PB1 account for branch → **Fallback** to default (no error)
- ✅ Multi-branch disabled → **Ignored** (uses default account)

### Permissions
- Same as Tax Profile permissions (System Manager, Accounts Manager)
- Tax Reviewer can view but not modify

### Performance
- `get_pb1_account()` is O(n) where n = number of mappings (typically < 50)
- Cached via `frappe.get_cached_doc("Tax Profile")`
- No performance impact for single-account mode

### Reports
- PB1 Register: Filter by branch to see branch-specific transactions
- Tax Period Closing: Shows aggregate + breakdown
- VAT registers: Unaffected (PPN logic separate)

---

## 🧪 Testing Checklist

- [ ] Create Tax Profile with multi-branch enabled
- [ ] Add 3+ branch mappings
- [ ] Try duplicate branch (should fail validation)
- [ ] Create Tax Payment Batch with branch specified
- [ ] Verify correct PB1 account is auto-populated
- [ ] Create Tax Payment Batch without branch (should use default)
- [ ] Run PB1 Register with branch filter
- [ ] Generate Tax Period Closing snapshot
- [ ] Verify `pb1_breakdown` in snapshot JSON
- [ ] Test backward compatibility (disable multi-branch)

---

## 📚 Related Files

### Core Implementation
- `imogi_finance/doctype/tax_profile/tax_profile.py` - Main logic
- `imogi_finance/doctype/tax_profile_pb1_account/` - Child table
- `imogi_finance/doctype/tax_payment_batch/tax_payment_batch.py` - Usage
- `imogi_finance/tax_operations.py` - Register snapshot

### Reports
- `imogi_finance/report/pb1_register/pb1_register.py` - Report logic

### Tests
- `imogi_finance/tests/test_pb1_multi_account.py` - Unit tests

---

## 🔮 Future Enhancements (Optional)

### Low Priority
- [ ] Auto-populate branch from Cost Center in Tax Payment Batch
- [ ] Validation warning if branch not covered in mapping
- [ ] Bulk migration utility for existing Tax Profiles
- [ ] Dashboard widget showing PB1 breakdown by branch

### Medium Priority
- [ ] Support Province-level mapping (in addition to Branch)
- [ ] Tax template per-branch override
- [ ] Branch filter in Tax Period Closing list view

### High Priority (if needed)
- [ ] Permissions per branch (user can only see their branch's PB1)
- [ ] Automated branch detection from Journal Entry/Payment Entry
- [ ] Multi-company consolidation with branch grouping

---

## 💡 Tips & Best Practices

1. **Always set a default PB1 account** even with multi-branch enabled
   - Acts as safety net for unmapped branches
   - Useful during transition period

2. **Use descriptive account names**
   ```
   Good: "PB1 Payable - Jakarta (DKI Jakarta)"
   Bad:  "PB1-001"
   ```

3. **Document your mapping strategy**
   - Which branches share accounts?
   - Which are branch-specific?
   - What's the fallback logic?

4. **Test with dummy data first**
   - Create test Tax Payment Batch entries
   - Verify GL entries use correct accounts
   - Run reports before going live

5. **Monitor during transition**
   - Check if old batches still work
   - Verify new batches use correct accounts
   - Watch for validation errors

---

## 🆘 Troubleshooting

### Issue: Tax Payment Batch uses wrong PB1 account
**Solution**:
1. Check if `enable_pb1_multi_branch = 1` in Tax Profile
2. Verify branch mapping exists for specified branch
3. Clear cache: `frappe.clear_cache()`

### Issue: Validation error "Branch appears multiple times"
**Solution**:
- Remove duplicate branch rows from `pb1_account_mappings`
- Each branch should appear only once

### Issue: PB1 Register shows no data
**Solution**:
- Verify branch filter matches actual GL entries
- Check if PB1 account for that branch has transactions
- Try without branch filter to see all PB1 accounts

### Issue: Tax Period Closing snapshot missing pb1_breakdown
**Solution**:
- Ensure `enable_pb1_multi_branch = 1`
- Ensure at least one branch mapping exists
- Regenerate snapshot

---

## ✅ Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| Tax Profile PB1 Account DocType | ✅ Complete | New child table |
| Tax Profile UI | ✅ Complete | New section with toggle |
| Tax Profile Logic | ✅ Complete | get_pb1_account() method |
| Tax Profile Validation | ✅ Complete | Duplicate check |
| Tax Payment Batch Field | ✅ Complete | Branch field added |
| Tax Payment Batch Logic | ✅ Complete | Auto-populate account |
| Tax Operations Snapshot | ✅ Complete | PB1 breakdown |
| PB1 Register Filter | ✅ Complete | Branch filter added |
| PB1 Register Column | ✅ Complete | Conditional branch column |
| Unit Tests | ✅ Complete | Basic coverage |
| Integration Tests | ⏳ Pending | Needs full DB setup |
| User Documentation | ✅ Complete | This file |
| Migration Script | ⏳ Optional | Manual setup sufficient |

---

## 📞 Support

For issues or questions:
1. Check this documentation first
2. Review test file for examples
3. Check ERPNext forums for multi-branch patterns
4. Consult with your Frappe developer

---

**Last Updated**: January 16, 2026  
**Version**: 1.0  
**Author**: Imogi Finance Team
