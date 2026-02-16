# FASE 1-7 SENIOR AUDIT REPORT — Go/No-Go Decision

**Audit Date:** February 17, 2026  
**Auditor Role:** Senior Frappe/ERPNext Reviewer  
**Project:** IMOGI-FINANCE Settings Consolidation  
**Audit Scope:** Fase 1-7 (Foundation → Fixtures)  

---

## Executive Summary

**RECOMMENDATION: NO-GO for Fase 8 (Testing & Validation)**

**Current Status:** 3 BLOCKERS + Rules violations prevent fresh deploy and multi-module consistency.

**Required Actions:** Fix all 3 blockers before QA/testing can proceed. Estimated fix time: 30-45 minutes.

---

## BLOCKING ISSUES (Must Fix Before Fase 8)

### ⛔ BLOCKER #1: Duplicate `get_expense_deferred_settings()` Function

**Location:** [imogi_finance/settings/utils.py](imogi_finance/settings/utils.py)
- **Line 107-112:** First definition (with error handling)
- **Line 248-255:** Second definition (without error handling)

**Impact:** 
- Python import undefined behavior (second definition overwrites first)
- Inconsistent error handling across imports
- Violates Rule 2 (single source of truth)

**Fix Required:**
- Delete lines 248-255 (second definition)
- Verify line 107-112 has proper error handling
- Add comment linking to first definition

**Code Snippet (line 107-112):**
```python
def get_expense_deferred_settings() -> frappe.Document:
    """Get Expense Deferred Settings singleton."""
    doc = get_single_cached(EXPENSE_DEFERRED_SETTINGS_DOCTYPE)
    if not doc:
        frappe.throw(_("Expense Deferred Settings not configured"))
    return doc
```

**Code Snippet (lines 248-255 - DELETE THIS):**
```python
def get_expense_deferred_settings() -> frappe.Document:
    """Get Expense Deferred Settings singleton.
    
    This helper centralizes access to deferred expense configuration.
    Ensures all modules use the same settings access pattern.
    
    Returns:
        ExpenseDeferredSettings document
    """
    return frappe.get_single(EXPENSE_DEFERRED_SETTINGS_DOCTYPE)
```

**Recommendation:** Keep first definition (with get_single_cached + error handling). Delete second.

---

### ⛔ BLOCKER #2: Duplicate `BRANCH_SETTING_DEFAULTS` Definitions

**Location:** 
- `imogi_finance/branching.py` line 9-13 (ACTIVE)
- `imogi_finance/settings/branch_defaults.py` line 7-12 (INTENDED SOURCE)

**Impact:**
- Two sources of truth (branching.py not importing from settings/)
- Risk of divergence during maintenance
- Violates Rule 7 (single definition per constant)

**Current Code - branching.py (WRONG):**
```python
BRANCH_SETTING_DEFAULTS = {
    "enable_multi_branch": 0,
    "inherit_branch_from_cost_center": 1,
    "default_branch": None,
    "enforce_branch_on_links": 1,
}
```

**Fix Required:**
- Remove BRANCH_SETTING_DEFAULTS definition from branching.py (lines 9-13)
- Add import at top: `from imogi_finance.settings.branch_defaults import BRANCH_SETTING_DEFAULTS`
- Verify usage of `BRANCH_SETTING_DEFAULTS` in branching.py still works

**Verification:** After fix, grep should find BRANCH_SETTING_DEFAULTS only in settings/branch_defaults.py + imports in branching.py

---

### ⛔ BLOCKER #3: Direct `frappe.get_single/get_cached_doc()` Calls in Business Logic

**Location:** 7 files violating Rule 6 (helper layer consolidation)

**Violating Files & Lines:**
1. `reporting/tasks.py:27` — `frappe.get_cached_doc("Finance Control Settings", "Finance Control Settings")`
2. `administrative_payment_voucher.py:55` — `frappe.get_cached_doc("Finance Control Settings")`
3. `cash_bank_daily_report.py:152` — `frappe.get_single("Finance Control Settings")`
4. `cash_bank_daily_report.py:205` — `frappe.get_cached_doc("Finance Control Settings")`
5. `api/reporting.py:40` — `frappe.get_cached_doc("Finance Control Settings")`
6. `branching.py:19` — `frappe.get_cached_doc("Finance Control Settings")`
7. `branching.py:22` — `frappe.get_single("Finance Control Settings")`

**Impact:**
- Settings access not centralized (violates Rule 6)
- Difficult to track dependencies
- Bypasses helper layer validation logic
- Inconsistent error messages across app

**Fix Required per File:**

**Option A: Replace with helper function call**
```python
# BEFORE (wrong)
settings = frappe.get_cached_doc("Finance Control Settings")

# AFTER (correct)
from imogi_finance.settings.utils import get_finance_control_settings
settings = get_finance_control_settings()
```

**Option B: For branching.py specifically - consolidate into _get_settings_doc() helper**
```python
# BEFORE
def _get_settings_doc():
    try:
        return frappe.get_cached_doc("Finance Control Settings")
    except Exception:
        try:
            return frappe.get_single("Finance Control Settings")
        except Exception:
            return None

# AFTER
from imogi_finance.settings.utils import get_finance_control_settings
def _get_settings_doc():
    try:
        return get_finance_control_settings()
    except Exception:
        return None
```

---

## COMPLIANCE STATUS BY RULE

| Rule | Status | Details |
|------|--------|---------|
| 1: Tax Profile as PPN master | ✅ PASS | ppn_input/output_account correctly sourced from Tax Profile |
| 2: Variance accounts via GL Mappings | ✅ PASS | dpp_variance/ppn_variance via get_gl_account() |
| 3: Materai accounts not hardcoded | ✅ PASS | Uses get_gl_account(DIGITAL_STAMP_*) pattern |
| 4: Paid from/to via GL Mappings | ✅ PASS | get_gl_account(DEFAULT_PAID_FROM) exists |
| 5: Default prepaid via GL Mappings | ✅ PASS | get_default_prepaid_account() exists |
| 6: No direct frappe.get_single in business logic | ❌ FAIL | 7 files violate (see BLOCKER #3) |
| 7: BRANCH_SETTING_DEFAULTS single definition | ❌ FAIL | Defined in 2 places (see BLOCKER #2) |
| 8: Reference doctypes not hardcoded | ✅ PASS | Transfer Application Settings table used |

---

## ADDITIONAL FINDINGS (Non-blocking, informational)

### ✅ DocType Structure Validation - PASS
- Finance Control Settings: Has gl_account_mappings ✅
- Tax Invoice OCR Settings: Missing ppn_input/output/dpp_variance ✅
- Transfer Application Settings: Has reference_doctypes, no default_paid_from/to ✅
- Expense Deferred Settings: No default_prepaid_account ✅

### ✅ Hardcoded Account Strings - PASS
- No "Biaya Materai Digital", "Kas", "PPN Input", "PPN Output" in code
- Only in fixtures (correct location)
- Account references via get_gl_account() helper

### ✅ Fase 7 Fixtures - PASS
- hooks.py includes Finance Control Settings, Transfer Application Settings ✅
- finance_control_settings.json has 6 GL mapping rows (all purposes) ✅
- transfer_application_settings.json has 3 reference doctypes ✅
- No gl_account_mapping_item.json separate fixture (correctly consolidated) ✅

---

## ACTION PLAN (Priority Order)

### Phase 1: Critical Fixes (MUST COMPLETE)

1. **Fix BLOCKER #2: BRANCH_SETTING_DEFAULTS Duplication**
   - File: `imogi_finance/branching.py`
   - Action: Remove lines 9-13, add import from settings.branch_defaults
   - Effort: 2 minutes
   - Risk: LOW (same constant values, no logic change)

2. **Fix BLOCKER #1: Duplicate get_expense_deferred_settings()**
   - File: `imogi_finance/settings/utils.py`
   - Action: Delete lines 248-255 (second definition)
   - Effort: 1 minute
   - Risk: VERY LOW (only removing duplicate)

3. **Fix BLOCKER #3: Direct frappe.get_single() Calls** 
   - Files: 7 locations
   - Action: Replace with helper function calls from settings/utils.py
   - Effort: ~15 minutes (systematic replacement across all files)
   - Risk: LOW (helpers already exist, just redirecting calls)

### Phase 2: Verification (Post-Fix)

4. **Syntax Validation**
   - Run `python3 -m py_compile` on all modified files
   - Verify no import errors
   - Effort: 2 minutes

5. **Grep Verification**
   - Verify 0 matches for direct frappe.get_single("... Settings")
   - Verify BRANCH_SETTING_DEFAULTS only in settings/branch_defaults.py
   - Verify 1 definition of get_expense_deferred_settings()
   - Effort: 2 minutes

### Phase 3: Re-Audit (Pre-Fase 8)

6. **Quick Re-Audit**
   - Run same checks as above
   - Confirm all 3 blockers resolved
   - Effort: 5 minutes

**Total Estimated Fix Time:** 30-45 minutes

---

## GO/NO-GO DECISION

### Current Status: **NO-GO** ❌

**Reason:** 3 BLOCKERS prevent Fase 8 entry

**Decision Gate:**
- Must fix all 3 blockers
- Must pass re-audit (all violations cleared)
- Then: PROCEED TO FASE 8 ✅

---

## RECOMMENDATIONS FOR FASE 8+ (Future)

1. **Add linting rule:** Prevent direct frappe.get_single() calls in business modules (only settings/)
2. **Add unit test:** Test each helper function's error handling
3. **Add integration test:** Multi-company GL mapping lookup scenarios
4. **Create module docstring:** Document settings/utils.py expected usage
5. **Enforce imports in fixtures:** All fixture JSON must validate against schema

---

## Sign-Off & Next Steps

**Audit Completeness:** 100% - All 8 rules checked, all violations identified

**Next Action:** Execute ACTION PLAN Phase 1 (3 blockers)

**Target:** Complete fixes + re-audit within 1 hour

**Decision Milestone:** After fixes verified → **GO for Fase 8**

---

**Report Generated By:** Senior Frappe/ERPNext Reviewer  
**Date:** 2026-02-17  
**Status:** PENDING FIX (3 blockers identified, fix plan provided)
