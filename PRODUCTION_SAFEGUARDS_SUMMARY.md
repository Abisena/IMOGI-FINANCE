# Tax Invoice OCR - Production Safeguards Summary

## 🛡️ No Silent Failure Guarantee

All 5 critical safeguards implemented to prevent silent failures in production.

---

## 1️⃣ PyMuPDF Missing Guard

**Problem**: PyMuPDF not installed → parsing fails silently

**Solution**:
```python
# faktur_pajak_parser.py - extract_text_with_bbox()
if not PYMUPDF_AVAILABLE:
    frappe.log_error(
        title="PyMuPDF Not Installed",
        message="Add 'PyMuPDF>=1.23.0' to requirements.txt and redeploy"
    )
    return []  # Empty list, not throw
```

**User Experience**:
- ✅ `parse_status` = "Needs Review"
- ✅ Yellow warning in `validation_summary`
- ✅ Clear message: "Check Frappe Cloud build logs"
- ✅ Error Log entry with actionable steps

---

## 2️⃣ Empty Items Guard

**Problem**: Parse succeeds but no items extracted → looks like success but isn't

**Solution**:
```python
# tax_invoice_ocr_upload.py - parse_line_items()
if not items:
    self.parse_status = "Needs Review"
    self.validation_summary = """
    ⚠️ No Line Items Extracted
    Possible causes:
    • PDF is scanned image (no text layer)
    • PyMuPDF not installed on server
    • Non-standard invoice layout
    """
    # Store debug info with token_count
    self.save()
```

**User Experience**:
- ✅ Document saved (not lost)
- ✅ Clear warning message distinguishes:
  - `token_count = 0` → "PyMuPDF missing or scanned PDF"
  - `token_count > 0` → "Non-standard template layout"
- ✅ `parsing_debug_json` has `token_count` for diagnosis
- ✅ Actionable troubleshooting steps in warning

---

## 3️⃣ Duplicate Enqueue Prevention

**Problem**: User saves multiple times → spam background jobs

**Solution**:
```python
# tax_invoice_ocr_upload.py - on_update()
should_enqueue = (
    self.ocr_status == "Done" and
    self.tax_invoice_pdf and
    not self.items and
    self.parse_status in ["Draft", None, ""]  # Strict check
)

# Additional: Check existing queue for duplicate job_name
if not frappe.flags.in_test:
    existing_jobs = get_jobs(queue="default")
    job_signature = f"tax-invoice-auto-parse:{self.name}"  # Unique per doc
    if any(job_signature in str(job) for job in existing_jobs):
        return  # Skip enqueue
```

**Protection**:
- ✅ Only enqueue if ALL conditions met
- ✅ Unique `job_name=f"tax-invoice-auto-parse:{doc.name}"` for deduplication
- ✅ Check existing queue (production only)
- ✅ No spam even with rapid saves

---

## 4️⃣ Worker Environment Verification

**Problem**: Works in console, fails in worker → different environments!

**Documentation Emphasis**:
```markdown
⚠️ CRITICAL for Frappe Cloud:
- Deploy MUST rebuild WORKERS (not just web)
- Console import success ≠ worker import success
- ALWAYS test with: frappe.enqueue(..., now=True)
```

**Testing Protocol**:
```python
# Step 1: Test console (web environment)
import fitz
print(f"Web has PyMuPDF: {fitz.version}")

# Step 2: Test worker (background environment)
frappe.enqueue(
    "imogi_finance...auto_parse_line_items",
    doc_name="TIO-00001",
    now=True  # Force sync execution
)
# Check if parse succeeds without PyMuPDF error
```

**Troubleshooting**:
- ✅ Clear distinction: web ≠ worker
- ✅ Build logs must show dependency installation
- ✅ **If console works but worker fails:**
  - Go to Frappe Cloud → Site → Settings
  - Click **"Clear Cache & Deploy"** button
  - Forces full rebuild of web + workers
  - Wait 5-10 minutes, test again
- ✅ Verify full deploy (not just restart)

---

## 5️⃣ Graceful Error Messages

**Problem**: Technical errors confuse users

**Solution - All Errors User-Friendly**:

**Scenario A - PyMuPDF Missing**:
```
⚠️ Parsing Failed
PyMuPDF not installed on server.
Add to imogi_finance/requirements.txt and redeploy.
See Frappe Cloud build logs.
```

**Scenario B - Empty Items**:
```
⚠️ No Line Items Extracted
Possible causes:
• PDF is scanned image (no text layer)
• PyMuPDF not installed on server
• Non-standard invoice layout

Check parsing_debug_json field for token count.
If token_count=0, verify PyMuPDF installation.
```

**Scenario C - Parse Exception**:
```
⚠️ Parsing Failed
Error: [technical error message]

Check Error Log for details.
For Frappe Cloud: verify build logs show PyMuPDF installation.
```

**Characteristics**:
- ✅ Yellow warning box (not red crash)
- ✅ Actionable steps (not vague)
- ✅ Frappe Cloud specific guidance
- ✅ Error Log has full traceback for devs
- ✅ User sees friendly message

---

## Testing Matrix

### Local Development
| Scenario | Expected Result |
|----------|----------------|
| PyMuPDF installed | ✅ Parse succeeds |
| PyMuPDF missing | ⚠️ "Needs Review" + warning |
| Empty PDF | ⚠️ "Needs Review" + no items warning |
| Rapid saves | ✅ Only 1 job enqueued |
| Parse error | ⚠️ "Needs Review" + error in log |

### Frappe Cloud
| Scenario | Expected Result |
|----------|----------------|
| Fresh deploy | ✅ PyMuPDF auto-installed (web + workers) |
| Console import | ✅ `import fitz` succeeds |
| Worker import | ✅ `enqueue(..., now=True)` succeeds |
| Build cache issue | ⚠️ Clear warning, not silent fail |
| Worker not rebuilt | ⚠️ Parse fails with clear message |

---

## Deployment Verification Script

```python
# Run in Frappe Cloud Console after deployment

def verify_deployment():
    """Verify Tax Invoice OCR deployment on Frappe Cloud."""
    results = []
    
    # 1. Check PyMuPDF in web environment
    try:
        import fitz
        results.append(f"✅ Web: PyMuPDF {fitz.version}")
    except ImportError:
        results.append("❌ Web: PyMuPDF NOT FOUND")
    
    # 2. Check DocType exists
    if frappe.db.table_exists("Tax Invoice OCR Upload Item"):
        results.append("✅ DocType: Tax Invoice OCR Upload Item")
    else:
        results.append("❌ DocType: NOT MIGRATED")
    
    # 3. Check worker environment
    try:
        def worker_test():
            import fitz
            return f"Worker: PyMuPDF {fitz.version}"
        
        result = frappe.enqueue(
            method="__main__.worker_test",
            now=True
        )
        results.append(f"✅ {result}")
    except Exception as e:
        results.append(f"❌ Worker: {str(e)}")
    
    # 4. Summary
    print("\n".join(results))
    print("\n" + "="*50)
    if all("✅" in r for r in results):
        print("✅ DEPLOYMENT SUCCESSFUL - All checks passed!")
    else:
        print("❌ DEPLOYMENT INCOMPLETE - Check failed items above")
    
    return results

# Run verification
verify_deployment()
```

---

## Success Metrics

### Zero Silent Failures ✅
- All errors → `parse_status = "Needs Review"`
- All errors → Error Log entry
- All errors → User-facing warning message
- No document lost (always saved)

### Clear Troubleshooting ✅
- Error messages actionable (not vague)
- Frappe Cloud specific guidance
- Distinguish: PyMuPDF missing vs layout issue vs empty PDF
- Debug JSON stored for analysis

### Production Hardened ✅
- Worker environment verified
- Duplicate jobs prevented
- Build cache issues documented
- Full deploy (not restart) enforced

---

**Last Updated**: February 8, 2026  
**Status**: ✅ All 5 Safeguards Implemented and Tested
