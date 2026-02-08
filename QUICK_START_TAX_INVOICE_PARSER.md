# Quick Start Guide - Tax Invoice Multi-Line Parser

## Installation Steps

### 1. Install PyMuPDF Dependency
```bash
cd /Users/dannyaudian/github/IMOGI-FINANCE
bench --site <your-site-name> pip install PyMuPDF>=1.23.0
```

### 2. Run Database Migration
```bash
bench --site <your-site-name> migrate
```

This will create:
- New child table: `Tax Invoice OCR Upload Item`
- New fields in `Tax Invoice OCR Upload`

### 3. Clear Cache & Rebuild
```bash
bench --site <your-site-name> clear-cache
bench --site <your-site-name> build
```

### 4. Restart Bench
```bash
bench restart
```

---

## Testing the Implementation

### Test with Sample Invoice

1. **Navigate to Tax Invoice OCR Upload**
   ```
   Desk → Imogi Finance → Tax Invoice OCR Upload → New
   ```

2. **Upload a Multi-Line Faktur Pajak PDF**
   - Click "Attach" and select PDF
   - Fill in FP No, Date, NPWP

3. **Run OCR (Existing Workflow)**
   - Click "Tax Invoice OCR" → "Run OCR"
   - Wait for OCR to complete (`ocr_status` = "Done")

4. **Parse Line Items (NEW)**
   - Click "Tax Invoice OCR" → **"Parse Line Items"**
   - System will:
     - Extract tokens with coordinates
     - Detect table boundaries
     - Map columns (Harga Jual, DPP, PPN)
     - Validate each row
     - Auto-set status to "Approved" or "Needs Review"

5. **Review Results**
   - Check **"Line Items"** section (child table)
   - Each row shows: description, amounts, confidence
   - Rows color-coded:
     - 🟢 Green = confidence ≥ 95%
     - 🟡 Yellow = confidence 85-94%
     - 🔴 Red = confidence < 85%
   - Review **"Validation Summary"** section

6. **Handle Needs Review**
   - If status = "Needs Review":
     - Edit incorrect values in child table
     - Click "Tax Invoice OCR" → **"Review & Approve"**
   - Status changes to "Approved"

---

## Verification Checklist

### ✅ Installation Verified
```bash
# Check PyMuPDF installed
bench --site <site> console
>>> import fitz
>>> print(fitz.__version__)  # Should show 1.23.x or higher

# Check DocType exists
>>> frappe.db.table_exists("Tax Invoice OCR Upload Item")
True

# Check new fields exist
>>> doc = frappe.get_doc("Tax Invoice OCR Upload", "<existing-doc-name>")
>>> hasattr(doc, 'items')
True
>>> hasattr(doc, 'parse_status')
True
```

### ✅ UI Buttons Visible
- Log in to ERPNext
- Open any Tax Invoice OCR Upload (after OCR Done)
- Should see button: **"Parse Line Items"** in Tax Invoice OCR menu
- After parsing, should see: **"Review & Approve"** or **"Generate Purchase Invoice"**

### ✅ Debug Fields Hidden
- Open form → expand Line Items grid
- Columns `raw_harga_jual`, `col_x_harga_jual`, etc. should NOT be visible
- Only visible: Line No, Description, Harga Jual, DPP, PPN, Confidence, Notes

---

## Running Unit Tests

```bash
cd /Users/dannyaudian/github/IMOGI-FINANCE

# Run all parser tests
bench --site <site> run-tests --module imogi_finance.tests.test_faktur_pajak_parser

# Run specific test class
bench --site <site> run-tests --module imogi_finance.tests.test_faktur_pajak_parser --test TestIndonesianNumberNormalization
```

Expected output:
```
Running Test imogi_finance.tests.test_faktur_pajak_parser
...........................................................................
----------------------------------------------------------------------
Ran 75 tests in 2.345s

OK
```

---

## Troubleshooting

### Problem: "PyMuPDF is not installed"
**Solution:**
```bash
bench --site <site> pip install PyMuPDF
bench restart
```

### Problem: "Tax Invoice OCR Upload Item not found"
**Solution:**
```bash
bench --site <site> migrate --force
bench --site <site> clear-cache
```

### Problem: "Parse Line Items button not showing"
**Solution:**
- Check `ocr_status` field = "Done"
- Clear browser cache (Ctrl+Shift+R)
- Check JS console for errors

### Problem: "All rows have low confidence"
**Solution:**
- Check PDF has text layer (not scanned image)
- Review `parsing_debug_json` field
- Check if table header keywords found
- Adjust `tax_rate` field (default 0.11)

### Problem: "Wrong column mapping"
**Solution:**
- Open `parsing_debug_json` field
- Check `column_ranges` → X-coordinates should match PDF layout
- Check `header_y` → Should be Y-position of "Harga Jual/DPP/PPN" row
- May need to adjust column expansion in code

---

## Debug Mode

Enable detailed logging:

```bash
bench --site <site> console
```

```python
import frappe
frappe.logger().set_log_level("DEBUG")

# Test parser directly
from imogi_finance.parsers.faktur_pajak_parser import parse_invoice

pdf_path = frappe.get_site_path("public/files/faktur_pajak.pdf")
result = parse_invoice(pdf_path, tax_rate=0.11)

# Check results
print(f"Success: {result['success']}")
print(f"Items: {len(result['items'])}")
print(f"Errors: {result['errors']}")

# Inspect debug info
debug = result['debug_info']
print(f"Tokens extracted: {debug['token_count']}")
print(f"Header Y: {debug.get('header_y')}")
print(f"Table end Y: {debug.get('table_end_y')}")
print(f"Rows before merge: {debug.get('row_count_before_merge')}")
print(f"Rows after merge: {debug.get('row_count_after_merge')}")
```

---

## Next Steps After Testing

1. **Test with Various PDF Formats**
   - Different FP types (01, 02, 03, etc.)
   - Different layouts
   - Various line item counts (1-50+)

2. **Adjust Settings if Needed**
   - Tax Invoice OCR Settings → Tolerance IDR/Percentage
   - Adjust column expansion in `faktur_pajak_parser.py` if needed

3. **Implement Purchase Invoice Generation**
   - Map approved line items to PI items
   - Handle tax accounts and templates
   - Link back to Tax Invoice Upload

4. **User Training**
   - Show workflow: Upload → OCR → Parse → Review → Generate PI
   - Explain confidence scores and validation
   - Demonstrate editing incorrect values

---

## Performance Notes

### Expected Performance:
- **PDF Text Extraction**: < 1 second
- **Parsing + Validation**: < 2 seconds for 20 line items
- **UI Render**: < 1 second for 50 line items in grid

### Optimization Tips:
- Child table grid lazy-loads by default
- Debug fields hidden to reduce DOM size
- Validation runs once on parse, not on every save
- Use `frappe.enqueue()` for batch processing if needed

---

## Support

For issues or questions:
1. Check [TAX_INVOICE_MULTI_LINE_IMPLEMENTATION.md](TAX_INVOICE_MULTI_LINE_IMPLEMENTATION.md) for detailed documentation
2. Review unit tests in `test_faktur_pajak_parser.py` for examples
3. Check Frappe Error Log for detailed error messages
4. Examine `parsing_debug_json` field for coordinate data

---

**Ready to use!** 🚀
