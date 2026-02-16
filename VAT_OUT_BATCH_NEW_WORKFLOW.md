# VAT OUT Batch & Tax Invoice Upload - New Workflow Guide

**Last Updated:** February 16, 2026  
**Version:** 2.0 (Fresh Deploy - Post-Refactoring)

---

## Overview

This guide documents the **NEW workflow** for VAT OUT Batch and Tax Invoice Upload after architectural refactoring.

### Key Changes

**BEFORE (Legacy):**
- VAT OUT Batch had "Upload PDFs" button that directly updated Sales Invoice fields
- No audit trail for PDF uploads
- Single workflow mixed batch processing with PDF management

**AFTER (Current):**
- VAT OUT Batch = **Export-only** for CoreTax Excel generation
- Tax Invoice Upload = **Single source** for FP PDF uploads and sync to Sales Invoice
- Clear separation of concerns with full audit trail
- Deterministic naming for idempotency

---

## Architecture

### VAT OUT Batch
**Purpose:** Group Sales Invoices and export to CoreTax DJP format  
**Responsibilities:**
- Auto-group invoices by customer NPWP + combine flag
- Manual grouping controls (split/merge groups)
- Generate CoreTax upload Excel file
- Import FP numbers from CoreTax results
- **Export CSV template** for downstream Tax Invoice Upload

**Does NOT:**
- ❌ Upload PDFs
- ❌ Attach files to Sales Invoices
- ❌ Directly modify Sales Invoice PDF fields

### Tax Invoice Upload
**Purpose:** Store FP data + PDF and sync to Sales Invoice  
**Responsibilities:**
- Store official Faktur Pajak PDF
- Validate FP number (16 digits normalized)
- Validate NPWP matching
- Sync FP data to Sales Invoice output fields
- Track sync status (Draft/Synced/Error)
- **Bulk creation** from CSV + ZIP

**Deterministic Naming:**
- Format: `TAXUP-{fp16}-{sales_invoice}`
- Enables idempotent creation
- Example: `TAXUP-0109876543210001-SINV-2026-00123`

---

## Complete Workflow

### Step 1-6: Standard VAT OUT Batch Process

1. **Create VAT OUT Batch**
   - Set date range, company
   - Save draft

2. **Get Available Invoices**
   - Auto-groups by customer NPWP
   - Respects `out_fp_combine` flag

3. **Manual Grouping** (if needed)
   - Click "Manage Groups"
   - Split same-customer invoices into multiple FP groups
   - Move invoices between groups

4. **Generate CoreTax Upload File**
   - Creates Excel file for DJP portal
   - Stores in `coretax_upload_file` field

5. **Manual Upload to CoreTax DJP**
   - Download Excel from batch
   - Upload to https://coretax.pajak.go.id
   - Generate FP numbers in CoreTax

6. **Import FP Numbers**
   - Download FP numbers Excel from CoreTax
   - Click "Import FP Numbers" in batch
   - Updates `out_fp_no_faktur` on Sales Invoices

### Step 7-8: NEW Tax Invoice Upload Process

#### Step 7: Export CSV Template

**Action:** Click "Export CSV Template" button in VAT OUT Batch

**What it does:**
- Generates CSV file with columns:
  - `fp_number` (normalized 16 digits from `out_fp_no_faktur`)
  - `sales_invoice` (Sales Invoice name)
  - `dpp` (from `out_fp_dpp` or `base_net_total`)
  - `ppn` (from `out_fp_ppn` or `base_tax_total`)
  - `fp_date` (from `out_fp_date` or `posting_date`)
  - `customer_npwp` (from `out_fp_customer_npwp` or `tax_id`)

**Warning Handling:**
- If invoices missing `out_fp_no_faktur`, shows warning:
  - "N invoice(s) missing FP numbers. Run Import FP Numbers first."
- CSV still generated with blank `fp_number` column

**File naming:** `VAT_OUT_{batch_name}_template.csv`

#### Step 8: Bulk Upload PDFs via Tax Invoice Upload

**Action:** Go to Tax Invoice Upload list → Click "Bulk Create"

**Requirements:**
1. **CSV file** (from Step 7)
2. **ZIP file** with FP PDFs downloaded from CoreTax
   - **PDF naming:** `{16-digit-fp-number}.pdf`
   - Example: `0109876543210001.pdf`
   - Normalized (digits only, no punctuation)

**Options:**
- ☐ Require all batch invoices in CSV (strict mode)
- ☐ Require all CSV rows have PDFs (strict mode)
- ☐ Overwrite existing records (update mode)

**Processing:**
- **Synchronous:** If ≤30 rows, processes immediately
- **Background Job:** If >30 rows, shows progress dialog with polling

**Validation (Two-Phase):**

**Phase 1: CSV Validation (fail fast)**
- Check required headers present
- Validate fp_number format (16 digits after normalization)
- Validate sales_invoice is not empty
- Parse dpp/ppn as numbers
- Parse fp_date as date
- Detect CSV duplicate fp_number+sales_invoice

**Phase 2: ZIP Inspection**
- Extract ZIP, map PDFs by fp16
- Compute `csv_missing_pdf` (CSV rows without PDF)
- Compute `pdf_unmatched` (PDFs not in CSV)

**Phase 3: Record Creation**
- For each CSV row with PDF:
  - Create File record with PDF content
  - Set `invoice_pdf` field **before insert** (required validation)
  - Insert Tax Invoice Upload with:
    - `tax_invoice_no` = fp16 (normalized)
    - `tax_invoice_no_raw` = original format from CSV
    - `vat_out_batch` = batch_name (for filtering)
    - Deterministic name = `TAXUP-{fp16}-{sales_invoice}`
  - Call `sync_tax_invoice_with_sales()` to update Sales Invoice

**Idempotency:**
- If record exists with same name:
  - **Default:** Skip if PDF already attached
  - **Overwrite mode:** Update PDF and re-sync

**Results Display:**
- Summary counts (created/updated/skipped)
- Row-level error table
- Unmatched PDFs list
- Missing PDFs list
- Links to created records
- Quick filter link to batch

---

## FP Number Normalization

**Critical for PDF matching:**

FP numbers can appear in different formats:
- **Original:** `010.001-26.12345678` (from CoreTax)
- **Normalized:** `0100012612345678` (16 digits only)

**Normalization Rules:**
1. Extract only digits: `re.sub(r'\D', '', fp_number)`
2. Take last 16 digits if longer: `digits[-16:]`
3. Validate exactly 16 digits

**Why normalize?**
- PDF filenames use normalized format
- Deterministic naming uses normalized format
- Prevents duplicate records due to formatting differences

**Storage:**
- `tax_invoice_no` = normalized 16 digits (used for matching)
- `tax_invoice_no_raw` = original format (for display)

---

## Retry Sync Mechanism

### When to Use
- Tax Invoice Upload status = "Error"
- Sync failed due to temporary issue (permissions, network, etc.)
- Need to re-sync after fixing Sales Invoice data

### Single Record Retry
**Action:** Open Tax Invoice Upload form → Click "Retry Sync" button

### Bulk Retry
**Action:** Tax Invoice Upload list → Select error records → "Retry Sync" bulk action

**What it does:**
- Calls `sync_tax_invoice_with_sales()` again
- Updates `status` and `sync_error` fields
- Returns summary: `{synced: N, failed: N, errors: [...]}`

---

## Delete Behavior (Safe)

### Default Delete Behavior
- **Does NOT cascade** to Sales Invoice
- Sales Invoice fields remain unchanged (audit trail)
- Tax Invoice Upload record deleted

### Synced Records
**Protection:** Requires System Manager role to delete synced records

**Why?**
- Prevents accidental deletion of production data
- Audit trail preservation

**Alternative:** Use "Unlink from Sales Invoice" method instead of deleting

### Unlink from Sales Invoice
**Action:** Tax Invoice Upload form → "Unlink from Sales Invoice" button

**What it does:**
- Clears Sales Invoice fields **only if they match** this upload:
  - `out_fp_tax_invoice_pdf`
  - `out_fp_no`, `out_fp_no_seri`, `out_fp_no_faktur`
  - `out_fp_date`, `out_fp_customer_npwp`
  - `out_fp_dpp`, `out_fp_ppn`
- Sets Tax Invoice Upload status back to "Draft"
- Adds comment to Sales Invoice for audit trail
- **Keeps Tax Invoice Upload record** (not deleted)

**Use Case:** Undo sync without deleting upload record

---

## Troubleshooting

### CSV Validation Errors

**Error:** "Missing required headers"
**Fix:** CSV must have exact headers: `fp_number,sales_invoice,dpp,ppn,fp_date,customer_npwp`

**Error:** "FP number must be 16 digits, got N"
**Fix:** Ensure fp_number contains valid FP number, system will normalize automatically

**Error:** "Sales invoice is required"
**Fix:** Each CSV row must have valid Sales Invoice name

**Error:** "Invalid amount"
**Fix:** dpp and ppn must be numeric values (no currency symbols)

### PDF Matching Errors

**Error:** "PDF not found in ZIP"
**Fix:** 
- Check PDF filename matches fp_number (16 digits)
- Example: fp_number `0109876543210001` → PDF `0109876543210001.pdf`
- Remove any punctuation from PDF filename

**Warning:** "N PDFs in ZIP were not in CSV"
**Impact:** Non-blocking, PDFs ignored
**Fix:** Check if PDFs are for correct batch, or update CSV to include missing invoices

**Warning:** "N CSV rows had no PDF in ZIP"
**Impact:** Those rows skipped
**Fix:** Download missing PDFs from CoreTax, add to ZIP, re-run bulk create (idempotent)

### Sync Errors

**Error:** "NPWP mismatch"
**Fix:** Check customer NPWP in Sales Invoice matches Tax Invoice Upload `customer_npwp`

**Error:** "Sales Invoice not found"
**Fix:** Verify Sales Invoice name in CSV is correct and exists

**Error:** "Permission denied"
**Fix:** Ensure user has write permission on Sales Invoice

### Background Job Issues

**Symptom:** Progress dialog stuck at 50%
**Fix:** Check RQ worker is running: `bench worker --queue long`

**Symptom:** Job status "not_found"
**Fix:** Job may have expired (>1 hour), re-run bulk creation

---

## Migration from Legacy

### For Fresh Deploys
- ✅ No migration needed
- Start using new workflow immediately

### For Existing Batches with PDFs
**Legacy data preservation:**
- Sales Invoices with `out_fp_tax_invoice_pdf` already set remain unchanged
- No audit trail for legacy uploads

**Optional:** Create retroactive Tax Invoice Upload records
```python
# Run this script to create audit trail for existing PDFs
# (Not required for functionality)
for si in frappe.get_all("Sales Invoice", 
    filters={"out_fp_tax_invoice_pdf": ["!=", ""]},
    fields=["name", "out_fp_no_faktur", "out_fp_tax_invoice_pdf"]):
    
    if not si.out_fp_no_faktur:
        continue
    
    fp16 = normalize_fp_number(si.out_fp_no_faktur)
    doc_name = f"TAXUP-{fp16}-{si.name}"
    
    if frappe.db.exists("Tax Invoice Upload", doc_name):
        continue
    
    # Create retroactive record (status already synced)
    # ... implementation details ...
```

---

## Best Practices

### CSV Template Management
1. Export CSV immediately after Import FP Numbers
2. Verify all fp_number fields populated before exporting
3. Keep CSV backup for audit trail

### PDF Organization
1. Download all FP PDFs from CoreTax to single folder
2. Rename PDFs to 16-digit format using script:
   ```bash
   # Example rename script
   for f in *.pdf; do
     # Extract FP number, normalize
     fp=$(echo "$f" | sed 's/[^0-9]//g' | tail -c 17)
     mv "$f" "${fp}.pdf"
   done
   ```
3. Create ZIP in same folder
4. Verify ZIP contents before upload

### Batch Processing
1. Process batches of <50 invoices synchronously
2. Use background job for 50+ invoices
3. Monitor RQ worker status for large batches

### Error Recovery
1. Download bulk creation result errors to CSV
2. Fix errors in source data
3. Re-run bulk creation (idempotent, skips existing)
4. Use "Retry Sync" for resolved errors

### Audit Trail
1. Never delete synced Tax Invoice Upload records
2. Use "Unlink" if need to undo sync
3. Check batch field to trace upload source
4. Review comments on Sales Invoice for sync history

---

## API Reference

### Bulk Creation API

**Method:** `imogi_finance.imogi_finance.doctype.tax_invoice_upload.tax_invoice_upload_api.bulk_create_from_csv`

**Parameters:**
- `batch_name` (str, required): VAT OUT Batch name
- `zip_url` (str, required): URL of uploaded ZIP file
- `csv_url` (str, required): URL of uploaded CSV file
- `require_all_batch_invoices` (int, optional): Strict mode flag (0/1)
- `require_all_csv_have_pdf` (int, optional): Strict mode flag (0/1)
- `overwrite_existing` (int, optional): Update mode flag (0/1)

**Returns:**
```python
{
    "status": "success" | "partial" | "error",
    "created": int,
    "updated": int,
    "skipped": int,
    "row_errors": [
        {"row": int, "fp_number": str, "reason": str}
    ],
    "pdf_unmatched": [str],  # fp16 list
    "csv_missing_pdf": [str],  # fp16 list
    "created_docs": [
        {"fp_number": str, "name": str, "sales_invoice": str, "vat_out_batch": str}
    ]
}

# OR for background job:
{
    "queued": 1,
    "job_id": str
}
```

### Job Status API

**Method:** `imogi_finance.imogi_finance.doctype.tax_invoice_upload.tax_invoice_upload_api.get_bulk_job_status`

**Parameters:**
- `job_id` (str, required): Job ID from bulk_create_from_csv

**Returns:**
```python
{
    "status": "finished" | "processing" | "failed" | "not_found" | "error",
    "progress_pct": int,  # 0-100
    "message": str,
    "result": dict  # Same as bulk_create_from_csv return (if finished)
}
```

### Retry Sync API

**Method:** `imogi_finance.imogi_finance.doctype.tax_invoice_upload.tax_invoice_upload_api.retry_sync`

**Parameters:**
- `names` (str | list, required): Tax Invoice Upload names (JSON string or list)

**Returns:**
```python
{
    "synced": int,
    "failed": int,
    "errors": [
        {"name": str, "reason": str}
    ],
    "message": str
}
```

---

## FAQ

### Q: Can I still upload PDFs manually one-by-one?
**A:** Yes! Bulk creation is optional. You can still create Tax Invoice Upload records manually via form.

### Q: What happens if I run bulk creation twice?
**A:** Idempotent by design. Existing records with PDFs are skipped unless overwrite mode enabled.

### Q: Can I upload PDFs before importing FP numbers?
**A:** No. CSV template requires `out_fp_no_faktur` to be populated. Run Import FP Numbers first.

### Q: What if CoreTax PDFs have different naming format?
**A:** Rename PDFs to normalized 16-digit format before creating ZIP. System only matches digits.

### Q: Can I partial-upload if only some PDFs ready?
**A:** Yes! Default mode is permissive. Missing PDFs = skipped rows. Re-run bulk creation later with additional PDFs.

### Q: How to bulk-delete error records and re-create?
**A:** Select error records → Delete (safe, doesn't affect SI) → Re-run bulk creation with corrected data.

### Q: Can I use Tax Invoice Upload for input tax (Purchase Invoice)?
**A:** No. Tax Invoice Upload is for OUTPUT tax (Sales Invoice) only. Use Tax Invoice OCR Upload for input tax.

---

## Summary

**New Workflow Benefits:**
- ✅ Clear separation: VAT OUT Batch = grouping/export, Tax Invoice Upload = PDF management
- ✅ Full audit trail with deterministic naming
- ✅ Idempotent bulk operations (safe to re-run)
- ✅ No cascade delete (data safety)
- ✅ Background job support for large batches
- ✅ Detailed error reporting with row-level diagnostics
- ✅ Flexible partial uploads (permissive defaults)

**Key Points:**
1. VAT OUT Batch no longer touches PDFs
2. Tax Invoice Upload is single source for FP PDF sync
3. CSV template bridges the two systems
4. Normalize FP numbers for PDF matching
5. Use retry sync for error recovery
6. Safe delete behavior preserves audit trail
