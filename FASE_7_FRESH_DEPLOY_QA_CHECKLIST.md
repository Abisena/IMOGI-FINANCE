# FASE 7 — Quality Gate: Fresh Deploy Verification

## Objective
Verify that after a fresh app installation, all Settings DocTypes are properly seeded with their fixtures and child table rows, so modules from phases 2–6 work immediately without manual configuration.

---

## Prerequisites
- Fresh Frappe/ERPNext site (or clean test site)
- imogi_finance app not yet installed
- Access to Frappe console/bench commands

---

## Test Steps

### Step 1: Install App
```bash
cd /path/to/frappe-bench
bench --site <site_name> install-app imogi_finance
```

Expected: App installs without errors. Fixtures auto-load during migration.

---

### Step 2: Verify Settings DocTypes Created

After installation completes, check that all Settings singleton documents exist:

#### 2.1 Finance Control Settings
```bash
bench --site <site_name> console
frappe.get_single('Finance Control Settings')
```

**Expected Output:**
- Document exists (no "not found" error)
- `name` = "Finance Control Settings"
- `issingle` = 1

**Via UI:**
- Navigate to: Setup → Customize → Finance Control Settings
- Document should be pre-created

#### 2.2 Transfer Application Settings
```bash
bench --site <site_name> console
frappe.get_single('Transfer Application Settings')
```

**Expected Output:**
- Document exists
- `name` = "Transfer Application Settings"

#### 2.3 Expense Deferred Settings
```bash
bench --site <site_name> console
frappe.get_single('Expense Deferred Settings')
```

**Expected Output:**
- Document exists (created by doctype fixture)
- `deferrable_accounts` table may be empty (user configures rule-based mappings)

---

### Step 3: Verify Child Table Rows Seeded

#### 3.1 GL Account Mappings (Finance Control Settings)

**Via Console:**
```python
settings = frappe.get_single('Finance Control Settings')
print(len(settings.gl_account_mappings))  # Should be 6
for row in settings.gl_account_mappings:
    print(f"{row.purpose}: required={row.is_required}, account={row.account}")
```

**Expected Output:**
```
6
digital_stamp_expense: required=1, account=
digital_stamp_payment: required=1, account=
default_paid_from: required=1, account=
default_prepaid: required=1, account=
dpp_variance: required=0, account=
ppn_variance: required=0, account=
```

**Via UI:**
- Navigate to Finance Control Settings form
- Scroll to "GL Account Mappings" section
- Verify table has 6 rows with purposes listed above
- All `account` fields empty (users will fill these)
- `is_required` field shows 1 for stamp + paid_from + prepaid, 0 for variance

#### 3.2 Reference DocTypes (Transfer Application Settings)

**Via Console:**
```python
settings = frappe.get_single('Transfer Application Settings')
print(len(settings.reference_doctypes))  # Should be 3
for row in settings.reference_doctypes:
    print(f"{row.reference_doctype}: enabled={row.enabled}")
```

**Expected Output:**
```
3
Expense Request: enabled=1
Purchase Invoice: enabled=1
Branch Expense Request: enabled=1
```

**Via UI:**
- Navigate to Transfer Application Settings form
- Scroll to "Reference DocTypes" section
- Verify table has 3 rows (Expense Request, Purchase Invoice, Branch Expense Request)
- All `enabled` = checked (1)

---

### Step 4: Verify Helper Functions Work

Test that the helper layer can access settings without throwing "doc not found" errors:

**Via Console:**
```python
from imogi_finance.settings.utils import get_finance_control_settings
from imogi_finance.settings.utils import get_gl_account

# Should return settings doc without error
settings = get_finance_control_settings()
print(f"Settings doc found: {settings.name}")

# Should throw meaningful error about missing account (not "doc not found")
try:
    account = get_gl_account('digital_stamp_expense', 'Default Company', required=True)
    print(f"Account: {account}")
except frappe.ValidationError as e:
    # Expected: "Account not configured for purpose X in Finance Control Settings"
    print(f"Expected error (OK): {str(e)}")
```

**Expected Output:**
```
Settings doc found: Finance Control Settings
Expected error (OK): Account not configured for purpose digital_stamp_expense in Finance Control Settings. Please configure GL Account Mappings.
```

(Error message may vary slightly depending on implementation, but should clearly point to Finance Control Settings, not "doc not found")

---

### Step 5: Verify One Core Flow Works

Test that a core module can run without throwing "missing doc" errors:

#### Option A: Test Digital Stamp Module
```python
from imogi_finance.receipt_control.utils import requires_materai

# Should not throw "settings doc not found" error
result = requires_materai(
    doctype='Purchase Invoice',
    doc_name='PI-001',
    company='Default Company'
)
print(f"Materai check result: {result}")
```

**Expected Output:**
- Function runs without "settings doc not found" error
- Returns True or False (or throws account-not-configured error, which is OK at this stage)

#### Option B: Test Transfer Application Settings Access
```python
from imogi_finance.transfer_application.utils import get_reference_doctypes

# Should not throw "settings doc not found" error
reference_doctypes = get_reference_doctypes(enabled_only=True)
print(f"Available reference doctypes: {reference_doctypes}")
```

**Expected Output:**
```
Available reference doctypes: ['Expense Request', 'Purchase Invoice', 'Branch Expense Request']
```

---

## Success Criteria

✅ **All checks pass:**
1. App installs without errors
2. All 3 Settings singleton docs exist (no "not found" errors)
3. GL Account Mappings table has exactly 6 rows (all purposes present)
4. Reference DocTypes table has exactly 3 rows (Expense Request, Purchase Invoice, Branch Expense Request)
5. Helper functions can access settings and throw meaningful errors (not "doc not found")
6. Core flows run without throwing "missing doc" errors

✅ **Fresh deploy ready:** New users can install app, fill in GL account mappings via UI, and features work immediately.

---

## Troubleshooting

### Issue: "Finance Control Settings" doc not found
**Solution:** Check that fixture file exists at `fixtures/finance_control_settings.json` and hooks.py includes it in fixtures list.

### Issue: GL Account Mappings table empty (0 rows)
**Solution:** Verify fixture JSON has `gl_account_mappings` array with 6 rows. Run `bench --site <site> migrate --force` to reload fixtures.

### Issue: Settings doc exists but account field is filled with invalid reference
**Solution:** Fixture was exported with actual account links. Clear those and re-seed by removing and re-installing fixture.

### Issue: Helper function still throws "settings doc not found"
**Solution:** Verify helper function is using `frappe.get_single()` or similar, not direct DB query. Check imports in settings/utils.py.

---

## Next Steps (Post QA)

Once fresh deploy verification passes:
1. Document user setup guide (how to fill GL account mappings via UI)
2. Create optional "Setup Wizard" to guide initial account configuration
3. Proceed to Fase 8: Testing & Validation (unit tests, integration tests)

---

## Fixture File Locations

- `imogi_finance/fixtures/finance_control_settings.json` — 6 GL mappings rows
- `imogi_finance/fixtures/transfer_application_settings.json` — 3 reference doctypes rows
- Both files are auto-loaded on `bench migrate` if app is installed

## Related Documentation

- **Fase 7 Spec**: [USER_REQUEST_PHASE_7_FIXTURES]
- **Fase 5 (Deferred Expense)**: Removed `default_prepaid_account` field; now uses GL Mappings default
- **Fase 4 (Transfer Application)**: Removed `paid_to` Settings resolution; uses party account per beneficiary
- **Fase 3 (OCR)**: Removed unused OCR Field Mapping DocType
- **Helper Layer Architecture**: `imogi_finance/settings/utils.py`

---

## Sign-Off

- [ ] Step 1: Fresh app install succeeds
- [ ] Step 2: All Settings docs exist
- [ ] Step 3: Child tables properly seeded (6 GL mappings, 3 reference doctypes)
- [ ] Step 4: Helper functions work (return settings, throw meaningful errors)
- [ ] Step 5: Core flows run without "doc not found" errors

**QA Date:** _____________  
**QA By:** _____________  
**Status:** ✅ PASS / ❌ FAIL  
