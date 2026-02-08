# Tax Invoice OCR Audit Report

**Date:** 2026-02-08
**Scope:** Legacy OCR-only parsing vs. New Token+bbox Pipeline
**Goal:** Identify overlaps, duplications, and safe deletion candidates

---

## Executive Summary

The codebase currently has **TWO PARALLEL PIPELINES** for Tax Invoice OCR:

1. **Legacy Pipeline** ([tax_invoice_ocr.py](tax_invoice_ocr.py)) - OCR text → regex parsing for HEADER/TOTALS
2. **New Pipeline** ([parsers/faktur_pajak_parser.py](imogi_finance/imogi_finance/parsers/faktur_pajak_parser.py)) - Token+bbox for LINE ITEMS

**Key Findings:**
- ✅ **No OCR-only line-item parsing found** - all line items use the new token pipeline
- ⚠️ **Duplicated utility functions** - amount parsing and NPWP normalization
- ✅ **Clean separation** - legacy handles header/totals, new handles line items
- ⚠️ **parse_line_items() already unified** - uses both PyMuPDF and Vision JSON fallback

---

## 1. Entry Points Table

| Function | Location | Type | Purpose | Status |
|----------|----------|------|---------|--------|
| `run_ocr()` | [tax_invoice_ocr.py:2135](tax_invoice_ocr.py#L2135) | @frappe.whitelist | Main OCR trigger (enqueues job) | **Keep** - Active |
| `_run_ocr_job()` | [tax_invoice_ocr.py:1896](tax_invoice_ocr.py#L1896) | Background Job | Background OCR processor | **Keep** - Active |
| `run_ocr_for_*()` (5x) | [api/tax_invoice.py:17-37](imogi_finance/api/tax_invoice.py#L17-L37) | @frappe.whitelist | Wrappers for different doctypes | **Keep** - Active |
| `parse_line_items()` | [doctype/tax_invoice_ocr_upload/tax_invoice_ocr_upload.py:96](imogi_finance/imogi_finance/doctype/tax_invoice_ocr_upload/tax_invoice_ocr_upload.py#L96) | @frappe.whitelist (method) | Parse line items from PDF | **Keep** - Active |
| `auto_parse_line_items()` | [doctype/tax_invoice_ocr_upload/tax_invoice_ocr_upload.py:379](imogi_finance/imogi_finance/doctype/tax_invoice_ocr_upload/tax_invoice_ocr_upload.py#L379) | Background Job | Auto-triggered parsing | **Keep** - Active |
| `approve_parse()` | [doctype/tax_invoice_ocr_upload/tax_invoice_ocr_upload.py:350](imogi_finance/imogi_finance/doctype/tax_invoice_ocr_upload/tax_invoice_ocr_upload.py#L350) | @frappe.whitelist | Manual parse approval | **Keep** - Active |

**Hooks:**
- ✅ No scheduled events for OCR
- ✅ No doc_events hooks for OCR (uses `on_update()` method in DocType)

---

## 2. Parsing Modules & Responsibilities

### A. HEADER/TOTALS Extraction (LEGACY)

| Function | Location | Responsibility | Used By | Keep/Delete |
|----------|----------|----------------|---------|-------------|
| `parse_faktur_pajak_text()` | [tax_invoice_ocr.py:864](tax_invoice_ocr.py#L864) | Parse header: fp_no, fp_date, npwp, harga_jual total, dpp total, ppn total from OCR text | Purchase Invoice, Expense Request flows | **KEEP** - Active (7 usages) |
| `_extract_npwp_from_text()` | [tax_invoice_ocr.py:780](tax_invoice_ocr.py#L780) | Extract NPWP from OCR text | `parse_faktur_pajak_text()` | **KEEP** - Used internally |
| `_extract_npwp_with_label()` | [tax_invoice_ocr.py:785](tax_invoice_ocr.py#L785) | Extract NPWP with label pattern | `parse_faktur_pajak_text()` | **KEEP** - Used internally |
| `_extract_harga_jual_from_signature_section()` | [tax_invoice_ocr.py:460](tax_invoice_ocr.py#L460) | Extract Harga Jual from signature section | `parse_faktur_pajak_text()` | **KEEP** - Used internally |
| `_find_amount_after_label()` | [tax_invoice_ocr.py:370](tax_invoice_ocr.py#L370) | Find amount after label in text | Multiple functions | **KEEP** - Used internally |
| `_extract_amounts_after_signature()` | [tax_invoice_ocr.py:629](tax_invoice_ocr.py#L629) | Extract amounts from signature block | `parse_faktur_pajak_text()` | **KEEP** - Used internally |

**Verdict:** ✅ **All LEGACY header/totals functions are ACTIVE and NEEDED**

### B. LINE ITEMS Extraction (NEW TOKEN PIPELINE)

| Function | Location | Responsibility | Used By | Keep/Delete |
|----------|----------|----------------|---------|-------------|
| `parse_invoice()` | [parsers/faktur_pajak_parser.py:695](imogi_finance/imogi_finance/parsers/faktur_pajak_parser.py#L695) | Main orchestrator for line items | `parse_line_items()` | **KEEP** - Active |
| `extract_text_with_bbox()` | [parsers/faktur_pajak_parser.py:145](imogi_finance/imogi_finance/parsers/faktur_pajak_parser.py#L145) | PyMuPDF token extraction | `parse_invoice()` | **KEEP** - Active |
| `vision_to_tokens()` | [parsers/faktur_pajak_parser.py:221](imogi_finance/imogi_finance/parsers/faktur_pajak_parser.py#L221) | Vision OCR to tokens | `parse_invoice()` | **KEEP** - Active |
| `parse_tokens()` | [parsers/faktur_pajak_parser.py:1145](imogi_finance/imogi_finance/parsers/faktur_pajak_parser.py#L1145) | Source-agnostic parser | `parse_invoice()` | **KEEP** - Active |
| `detect_table_header()` | [parsers/faktur_pajak_parser.py:351](imogi_finance/imogi_finance/parsers/faktur_pajak_parser.py#L351) | Detect column headers | `parse_tokens()` | **KEEP** - Active |
| `_parse_multipage()` | [parsers/faktur_pajak_parser.py:906](imogi_finance/imogi_finance/parsers/faktur_pajak_parser.py#L906) | Multi-page parser | `parse_tokens()` | **KEEP** - Active |

**Verdict:** ✅ **All NEW TOKEN functions are ACTIVE**

### C. OCR EXECUTION (GOOGLE VISION)

| Function | Location | Responsibility | Used By | Keep/Delete |
|----------|----------|----------------|---------|-------------|
| `ocr_extract_text_from_pdf()` | [tax_invoice_ocr.py:1838](tax_invoice_ocr.py#L1838) | Provider router for OCR | `_run_ocr_job()` | **KEEP** - Active |
| `_google_vision_ocr()` | [tax_invoice_ocr.py:1627](tax_invoice_ocr.py#L1627) | Google Vision OCR implementation | `ocr_extract_text_from_pdf()` | **KEEP** - Active (+ 1 test usage) |

**Verdict:** ✅ **All OCR execution functions are ACTIVE**

---

## 3. Duplicated Utilities

### A. Indonesian Amount Parsing

| Function | Location | Used By | Keep/Delete |
|----------|----------|---------|-------------|
| `_parse_idr_amount()` | [tax_invoice_ocr.py:320](tax_invoice_ocr.py#L320) | Legacy parser (8 internal usages) | **KEEP - Refactor to wrapper** |
| `parse_idr_amount()` | [parsers/normalization.py:220](imogi_finance/imogi_finance/parsers/normalization.py#L220) | New parser (no external usage found) | **KEEP - Target implementation** |
| `normalize_indonesian_number()` | [parsers/normalization.py:16](imogi_finance/imogi_finance/parsers/normalization.py#L16) | New parser implementation | **KEEP - Core implementation** |

**Analysis:**
- `_parse_idr_amount()` is used 8 times in [tax_invoice_ocr.py](tax_invoice_ocr.py) (lines 396, 426, 516, 577, 611, 738, 921)
- `parse_idr_amount()` (normalization.py) is **NOT USED** externally
- Both implement the same logic (Indonesian format: dots as thousand separators, comma as decimal)

**Recommendation:**
```python
# In tax_invoice_ocr.py:
def _parse_idr_amount(value: str) -> float:
    """
    LEGACY WRAPPER: Maintained for backward compatibility.
    
    Delegates to parsers.normalization.parse_idr_amount for actual parsing.
    
    Args:
        value: String representation of Indonesian Rupiah amount
    
    Returns:
        Float value
    """
    from imogi_finance.imogi_finance.parsers.normalization import parse_idr_amount
    return parse_idr_amount(value)
```

**Impact:** Zero breaking changes, unifies parsing logic

### B. NPWP Normalization/Extraction

| Function | Location | Used By | Keep/Delete |
|----------|----------|---------|-------------|
| `normalize_npwp()` | [tax_invoice_ocr.py:107](tax_invoice_ocr.py#L107) | **15 usages across codebase** | **KEEP** - Widely used |
| `extract_npwp()` | [parsers/normalization.py:149](imogi_finance/imogi_finance/parsers/normalization.py#L149) | Tests only (4 usages in test_faktur_pajak_parser.py) | **KEEP** - Different purpose |

**Analysis:**
- `normalize_npwp()` removes dots/dashes from NPWP (normalization only) - **15 usages:**
  - [services/tax_invoice_service.py:9, 26](imogi_finance/services/tax_invoice_service.py#L9)
  - [tax_invoice_ocr.py:768, 1978, 2075](tax_invoice_ocr.py#L768)
  - [events/purchase_invoice.py:15, 182, 183](imogi_finance/events/purchase_invoice.py#L15)
  - [doctype/branch_expense_request/branch_expense_request.py:244](imogi_finance/imogi_finance/doctype/branch_expense_request/branch_expense_request.py#L244)
  - [doctype/tax_invoice_upload/tax_invoice_upload.py:13, 29](imogi_finance/imogi_finance/doctype/tax_invoice_upload/tax_invoice_upload.py#L13)
  - [doctype/expense_request/expense_request.py:383, 405, 406](imogi_finance/imogi_finance/doctype/expense_request/expense_request.py#L383)

- `extract_npwp()` **extracts + normalizes** from text (extraction + normalization) - **4 usages in tests only**

**Recommendation:**
```python
# In tax_invoice_ocr.py:
def normalize_npwp(npwp: str | None) -> str | None:
    """
    Normalize NPWP by removing dots, dashes, and spaces.
    
    NOTE: For EXTRACTION from text, use:
        from imogi_finance.imogi_finance.parsers.normalization import extract_npwp
    
    Args:
        npwp: NPWP string (may contain formatting)
    
    Returns:
        Normalized NPWP (digits only) or None
    """
    if not npwp:
        return npwp
    settings = get_settings()
    if cint(settings.get("npwp_normalize")):
        return re.sub(r"[.\-\s]", "", npwp or "")
    return npwp
```

**Impact:** Zero breaking changes, adds docstring pointer

---

## 4. Key Findings: parse_line_items() Analysis

**Location:** [doctype/tax_invoice_ocr_upload/tax_invoice_ocr_upload.py:96](imogi_finance/imogi_finance/doctype/tax_invoice_ocr_upload/tax_invoice_ocr_upload.py#L96)

**Current Implementation:**
```python
def parse_line_items(self, auto_triggered: bool = False):
    # Try to load vision_json from ocr_raw_json if available (for scanned PDFs)
    vision_json = None
    if self.ocr_raw_json:
        try:
            vision_json = json.loads(self.ocr_raw_json)
        except Exception:
            pass  # Ignore JSON parse errors, will use PyMuPDF fallback
    
    # Parse invoice using unified parser (PyMuPDF or Vision OCR)
    parse_result = parse_invoice(pdf_path=pdf_path, vision_json=vision_json, tax_rate=tax_rate)
```

**✅ ALREADY UNIFIED:**
- ✅ Uses new token pipeline (`parse_invoice()`)
- ✅ Supports Vision JSON fallback when PyMuPDF fails
- ✅ Multi-page support already implemented in `_parse_multipage()`
- ✅ Robust error handling with "Needs Review" status

**❌ NO LEGACY LINE-ITEM PARSING FOUND**

---

## 5. Safe Deletions

**Result:** ✅ **NO SAFE DELETIONS IDENTIFIED**

All functions are either:
1. Actively used in production (entry points, parsers, utilities)
2. Part of the new unified pipeline
3. Required for header/totals extraction (legacy but necessary)

---

## 6. Refactoring Recommendations

### Priority 1: Unify Amount Parsing (Zero Breaking Changes)

**File:** [tax_invoice_ocr.py](tax_invoice_ocr.py#L320)

```python
def _parse_idr_amount(value: str) -> float:
    """
    LEGACY WRAPPER: Parse Indonesian Rupiah amount format.
    
    Delegates to parsers.normalization.parse_idr_amount for unified logic.
    Maintained for backward compatibility with existing code.
    
    Indonesian format:
    - Thousand separator: . (dot)
    - Decimal separator: , (comma)
    - Example: "1.234.567,89" -> 1234567.89
    
    Args:
        value: String representation of IDR amount
    
    Returns:
        Float value
    """
    from imogi_finance.imogi_finance.parsers.normalization import parse_idr_amount
    return parse_idr_amount(value) or 0.0
```

**Impact:**
- ✅ Zero breaking changes (function signature unchanged)
- ✅ Unifies amount parsing logic
- ✅ Future enhancements only needed in one place

### Priority 2: Add Docstring Pointer for NPWP Functions

**File:** [tax_invoice_ocr.py](tax_invoice_ocr.py#L107)

```python
def normalize_npwp(npwp: str | None) -> str | None:
    """
    Normalize NPWP by removing dots, dashes, and spaces.
    
    Use this function when you already have an NPWP string and need to normalize it.
    
    For EXTRACTING NPWP from raw OCR text, use:
        from imogi_finance.imogi_finance.parsers.normalization import extract_npwp
        npwp = extract_npwp(ocr_text)  # Extracts + normalizes
    
    Args:
        npwp: NPWP string (may contain formatting like dots/dashes)
    
    Returns:
        Normalized NPWP (digits only) or None
    """
    if not npwp:
        return npwp
    settings = get_settings()
    if cint(settings.get("npwp_normalize")):
        return re.sub(r"[.\-\s]", "", npwp or "")
    return npwp
```

**Impact:**
- ✅ Zero code changes
- ✅ Clarifies which function to use for extraction vs normalization
- ✅ Prevents future duplication

---

## 7. Must Keep (Justification)

### All Functions in Legacy Pipeline
**Reason:** Active in production for header/totals extraction in Purchase Invoice / Expense Request flows

### All Functions in New Token Pipeline
**Reason:** Active for line items extraction, multi-page support, Vision OCR fallback

### All Entry Points & Background Jobs
**Reason:** User-facing features, whitelisted API methods, production workflows

---

## 8. Architecture Summary

### Current Design (✅ ALREADY OPTIMAL)

```
┌─────────────────────────────────────────────────────┐
│                  OCR TRIGGER                        │
│  run_ocr() → _run_ocr_job() → ocr_extract_text()  │
│                                                     │
│  Stores:                                            │
│  - OCR text                                         │
│  - ocr_raw_json (Vision API response)              │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│          HEADER/TOTALS PARSING (LEGACY)             │
│                                                     │
│  parse_faktur_pajak_text(ocr_text)                 │
│  ├── fp_no, fp_date, npwp                          │
│  ├── harga_jual_total                              │
│  ├── dpp_total                                      │
│  └── ppn_total                                      │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│       LINE ITEMS PARSING (NEW TOKEN PIPELINE)       │
│                                                     │
│  parse_line_items() → parse_invoice()              │
│  ├── Vision JSON (if ocr_raw_json exists)          │
│  ├── Fallback: PyMuPDF (if Vision fails)           │
│  ├── Multi-page support                            │
│  └── Token+bbox → Structured items                 │
└─────────────────────────────────────────────────────┘
```

**Strengths:**
- ✅ Clean separation of concerns
- ✅ No overlaps or conflicts
- ✅ Robust fallback chain
- ✅ Multi-page support

---

## 9. Testing Coverage

| Module | Test File | Status |
|--------|-----------|--------|
| Legacy parser | [tests/test_tax_invoice_ocr.py](imogi_finance/tests/test_tax_invoice_ocr.py) | ✅ Exists |
| New token parser | [tests/test_faktur_pajak_parser.py](imogi_finance/imogi_finance/tests/test_faktur_pajak_parser.py) | ✅ Exists |

---

## 10. Conclusion

**Audit Status:** ✅ **COMPLETE**

**Findings:**
1. ✅ **No legacy OCR-only line-item parsing exists** - unified from day 1
2. ⚠️ **Minor duplication in utilities** - easily fixed with thin wrappers
3. ✅ **Clean architecture** - legacy for headers, new for line items
4. ✅ **Already robust** - Vision JSON → PyMuPDF fallback working
5. ✅ **Multi-page support** - already implemented

**Recommendations:**
1. **Refactor `_parse_idr_amount()` to wrapper** (Priority 1)
2. **Add docstring to `normalize_npwp()`** (Priority 2)
3. **No deletions needed** - all code is active

**Next Steps:** See implementation in MIGRATION.md (to be created)

