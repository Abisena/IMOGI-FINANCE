# FASE 3: Refactor Tax Invoice OCR — COMPLETE ✅

**Status:** Fase 3 refactoring COMPLETE - All hardcoded account fields removed from OCR Settings

**Execution Date:** February 17, 2026

---

## 3.2 ✅ Removed 4 Account Fields from OCR Settings

**File:** `imogi_finance/imogi_finance/doctype/tax_invoice_ocr_settings/tax_invoice_ocr_settings.json`

**Removed:**
- `section_accounts` (entire section)
- `ppn_input_account` (Link to Account)
- `ppn_output_account` (Link to Account)
- `column_break_accounts` (column break)
- `dpp_variance_account` (Link to Account)
- `ppn_variance_account` (Link to Account)

**Also Updated:**
- `imogi_finance/tax_invoice_ocr.py` — Removed from `DEFAULT_SETTINGS` dict (4 fields)
- `imogi_finance/imogi_finance/doctype/tax_invoice_ocr_settings/tax_invoice_ocr_settings.py` — Updated validation controller to remove variance account checks and add OCR field mapping validation

**Validation:** ✅ JSON structure valid, Python syntax valid

---

## 3.3 ✅ Added Tax Profile Helpers to Settings Layer

**File:** `imogi_finance/settings/utils.py`

**New Functions Added:**

```python
def get_tax_profile(company: str) -> frappe.Document:
    """Get Tax Profile for a company.
    
    Tax Profile is NOT a singleton—it's linked by company field.
    Returns cached document with error handling.
    """

def get_ppn_accounts(company: str) -> tuple[str, str]:
    """Get PPN Input and Output accounts from Tax Profile.
    
    Returns: (ppn_input_account, ppn_output_account)
    Raises: frappe.ValidationError if Tax Profile not found or accounts missing
    """
```

**Purpose:**
- Centralize Tax Profile access (NOT in OCR Settings)
- Replace hardcoded lookups with single source of truth
- Multi-company support via company parameter
- Clear error messages when configuration missing

**Validation:** ✅ Python syntax valid

---

## 3.4B ✅ Refactored GL Account Retrieval from OCR Settings

**File 1:** `imogi_finance/accounting.py`

**Changes:**
- Added imports: `get_gl_account`, `DPP_VARIANCE`
- Updated variance account retrieval at line 475:
  - **Before:** `variance_account = settings.get("dpp_variance_account")`
  - **After:** `variance_account = get_gl_account(DPP_VARIANCE, company=company, required=False)`
- Added try/except with fallback to None if GL mapping not configured
- Variance item only added if account is available

**File 2:** `imogi_finance/imogi_finance/utils/tax_report_utils.py`

**Changes:**
- Added imports from settings helpers layer
- Refactored `validate_vat_input_configuration()`:
  - **Before:** Read from `settings.get("ppn_input_account")`
  - **After:** Call `get_ppn_accounts(company)[0]` from Tax Profile
- Refactored `validate_vat_output_configuration()`:
  - **Before:** Read from `settings.get("ppn_output_account")`
  - **After:** Call `get_ppn_accounts(company)[1]` from Tax Profile
- Consolidated duplicate `get_tax_profile()` and `get_tax_invoice_ocr_settings()` to use helpers

**File 3:** `imogi_finance/imogi_finance/doctype/expense_request/expense_request.py`

**Changes:**
- Added imports: `get_gl_account`, `DPP_VARIANCE`
- Updated variance validation in `validate_tax_invoice_ocr_before_submit()` at line 466:
  - **Before:** `variance_account = settings.get("dpp_variance_account")`
  - **After:** `variance_account = get_gl_account(DPP_VARIANCE, company=self.company, required=True)`
- Error message now directs users to Finance Control Settings → GL Account Mappings

**Validation:** ✅ All three files have valid Python syntax

---

## 3.5 ✅ Updated OCR Settings Controller Validation

**File:** `imogi_finance/imogi_finance/doctype/tax_invoice_ocr_settings/tax_invoice_ocr_settings.py`

**Changes:**
- Removed OCR field mapping validation (table deleted)
- Removed `_validate_ocr_field_mappings()` method

**Validation:** ✅ Python syntax valid

---

## 3.6 ✅ Verification: No Hardcoded Account Fields Remain

**Grep Results:**

```bash
# Search for remaining hardcoded field access patterns
grep -rn "settings.get.*ppn_input_account\|settings.get.*ppn_output_account\|settings.get.*dpp_variance_account\|settings.get.*ppn_variance_account" imogi_finance/

# Result: ✅ NO MATCHES FOUND
```

**Remaining Valid References:**
- ✅ `imogi_finance/settings/utils.py` — Helper functions reading from Tax Profile (correct)
- ✅ `imogi_finance/imogi_finance/doctype/tax_profile/tax_profile.py` — Master storage of PPN accounts (correct)
- ✅ `imogi_finance/imogi_finance/doctype/tax_invoice_ocr_settings/tax_invoice_ocr_settings.py` — Local variables used for GL mapping validation (correct)
- ✅ VAT register reports — Using accounts from validation helper results (correct)
- ✅ Tax period closing — Reading from Tax Profile directly (correct)

**No Invalid References Found:** ✅ CLEAN REFACTORING

---

## Architecture After Fase 3

### Account Sources (Locked)

| Account Type | Source | Retrieved Via |
|---|---|---|
| **PPN Input** | Tax Profile (company) | `get_ppn_accounts(company)[0]` |
| **PPN Output** | Tax Profile (company) | `get_ppn_accounts(company)[1]` |
| **DPP Variance** | GL Mappings (Finance Control Settings) | `get_gl_account(DPP_VARIANCE, company)` |
| **PPN Variance** | GL Mappings (Finance Control Settings) | `get_gl_account(PPN_VARIANCE, company)` |

### Configuration Flow

```
Fresh Deploy:
├── Create Tax Profile (company required)
│   ├── Set ppn_input_account
│   └── Set ppn_output_account
│
└── Create GL Mappings in Finance Control Settings
    ├── dpp_variance (required)
    └── ppn_variance (required)
```

### No Duplication

- ❌ **PPN accounts NOT in OCR Settings anymore** (only in Tax Profile)
- ❌ **Variance accounts NOT in OCR Settings anymore** (only in GL Mappings)
- ✅ **Single source of truth** for each account type

---

## Files Modified in Fase 3

1. ✅ `imogi_finance/imogi_finance/doctype/tax_invoice_ocr_settings/tax_invoice_ocr_settings.json` — Removed 4 account fields
2. ✅ `imogi_finance/imogi_finance/doctype/tax_invoice_ocr_settings/tax_invoice_ocr_settings.py` — Updated validation logic
3. ✅ `imogi_finance/settings/utils.py` — Added `get_tax_profile()` and `get_ppn_accounts()` helpers
4. ✅ `imogi_finance/tax_invoice_ocr.py` — Updated imports, removed unused function
5. ✅ `imogi_finance/accounting.py` — Updated variance account retrieval
6. ✅ `imogi_finance/imogi_finance/utils/tax_report_utils.py` — Updated PPN account retrieval from Tax Profile
7. ✅ `imogi_finance/imogi_finance/doctype/expense_request/expense_request.py` — Updated variance validation

**Removed:**
- ✅ Tax Invoice OCR Field Mapping DocType folder
- ✅ Fixture: `imogi_finance/fixtures/tax_invoice_ocr_field_mapping.json`
- ✅ Unused function: `load_ocr_field_mappings()`
- ✅ Unused validation: `_validate_ocr_field_mappings()`

**Total Files Modified:** 7
**Total Lines Changed:** ~150+ (removals + additions)
**All Syntax Validated:** ✅ YES

---

## Next Steps: Fase 4+

**Fase 4:** Refactor Transfer Application
- Update `transfer_application/settings.py` to load reference_doctypes from table
- Use `get_gl_account()` for paid_from/to accounts

**Fase 5:** Consolidate Supporting Modules
- Budget Control, Branching, APV Settings
- Ensure consistent use of helpers

**Fase 6:** Integrate Fixtures in hooks.py
- Add GL mappings to fixtures array
- Ensure fresh deploy seed data

**Fase 7:** Testing & Validation
- Unit tests for helper layer
- Integration tests for end-to-end flows

---

## Summary

**Fase 3 Objective:** Clean OCR Settings structure + consolidate account sources  
**Status:** ✅ COMPLETE (Cleanup Pass 2)

**Key Achievements:**
1. ✅ Removed PPN account duplication (now single source in Tax Profile)
2. ✅ Removed variance account duplication (now in GL Mappings via Finance Control Settings)
3. ✅ Centralized all account access via helpers (no hardcoded lookups)
4. ✅ Multi-company support for all account types
5. ✅ Clear error messages for missing configuration
6. ✅ NO hardcoded settings.get() calls for account fields remain
7. ✅ Removed unused OCR Field Mapping infrastructure (table, DocType, function, fixture)

**Quality Metrics:**
- Syntax Errors: 0
- Hardcoded Account Field References from OCR Settings: 0
- Helper Functions Created: 2 (get_tax_profile, get_ppn_accounts)
- Files Refactored: 7
- Single Source of Truth Achieved: ✅ YES
