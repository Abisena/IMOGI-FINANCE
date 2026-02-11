"""
COMPLETE OCR FLOW FOR INDONESIAN TAX INVOICE (FAKTUR PAJAK)
Updated: February 2026

Flow diagram:
═══════════════════════════════════════════════════════════════════════════════

1. OCR INPUT (Google Vision API)
   └─ JSON with Vision API response (bounding boxes + text)

2. TEXT EXTRACTION
   ├─ Filter to SUMMARY SECTION ONLY
   │  └─ Use markers: "Dikurangi Potongan Harga" or "Dasar Pengenaan Pajak"
   │     (these ONLY appear in summary, not in item details)
   │
   └─ Extract from summary section ONLY:
      ├─ Harga Jual (Total selling price)
      ├─ Potongan Harga (Discount)
      ├─ Uang Muka (Down payment)
      ├─ DPP (Tax base = Dasar Pengenaan Pajak)
      ├─ PPN (VAT = Jumlah PPN)
      └─ PPnBM (Luxury goods tax = Jumlah PPnBM)

3. PATTERN MATCHING (Text-based extraction)
   ├─ DPP pattern: "Dasar Pengenaan Pajak" → Extract value after label
   ├─ PPN pattern: "Jumlah PPN (...)" → Extract value after label
   ├─ Harga Jual pattern: "Harga Jual / Penggantian" → Extract value after
   ├─ Potongan pattern: "Dikurangi Potongan Harga" → Extract value after
   └─ Uang Muka pattern: "Dikurangi Uang Muka" → Extract value after
       (Note: Changed from "Uang Muka" only, to avoid false matches)

4. VALIDATE NO FIELD SWAP
   └─ Check: PPN should ALWAYS be < DPP
      └─ If PPN > DPP → CRITICAL ERROR (field swap detected)

5. CALCULATE TAX RATE
   ├─ IF DPP > 0 AND PPN > 0:
   │  └─ tax_rate = PPN / DPP
   │
   ├─ MATCH to standard rates (with ±2% tolerance):
   │  ├─ 0.12 (12%) → Closest match
   │  ├─ 0.11 (11%) → Closest match
   │  └─ Other calculated rates → Return as-is
   │
   └─ ELSE:
      └─ Return 0.0 (cannot calculate)

6. VERIFY TAX RATE AGAINST INDONESIAN REGULATIONS
   ├─ Valid rates in Indonesia:
   │  ├─ 0.0% → Zero-Rated (export, exempt)
   │  ├─ 1.1% → Digital (e-commerce)
   │  ├─ 3.0% → Special goods/services
   │  ├─ 5.0% → Reduced (food, medicines, books)
   │  ├─ 11.0% → Standard (pre-2025)
   │  └─ 12.0% → Standard (current, since Jan 2025)
   │
   ├─ Match calculated rate to valid rates
   │  ├─ IF match found: ✅ Valid
   │  └─ IF no match: ❌ Invalid (log error but continue)
   │
   └─ Return rate type & validation status

7. COMPREHENSIVE VALIDATION
   ├─ CHECK: Negative values? → ❌ Invalid
   ├─ CHECK: DPP ≤ Harga Jual? → ❌ Invalid if not
   ├─ CHECK: PPN = DPP × tax_rate? → ❌ If diff > 2%
   ├─ CHECK: Discount calculation correct? → ⚠️ Warning if wrong
   └─ CHECK: Values suspiciously low? → ⚠️ Warning

8. LAYOUT-AWARE PARSER (Fallback if text extraction failed)
   ├─ Use coordinate-based extraction (bounding boxes)
   ├─ Extract DPP/PPN using spatial position
   └─ Compare with text extraction results
      └─ If text extraction found larger values → Use text version
         (Summary totals are always larger than line-item values)

9. OUTPUT & STORAGE
   ├─ Store extracted values:
   │  ├─ harga_jual
   │  ├─ dpp
   │  ├─ ppn
   │  ├─ ppnbm
   │  └─ tax_rate
   │
   ├─ Store validation status:
   │  ├─ is_valid (boolean)
   │  ├─ validation_issues (list)
   │  ├─ rate_type (string)
   │  └─ rate_verification (dict)
   │
   └─ Log all issues for audit trail

═══════════════════════════════════════════════════════════════════════════════

KEY IMPROVEMENTS (vs old flow):
✅ 1. Filter to SUMMARY SECTION ONLY
     - Prevents mixing item detail amounts with summary totals
     - Uses structural markers ("Dikurangi Potongan Harga") not hardcoded amounts

✅ 2. CALCULATE tax rate from DPP & PPN ONLY
     - No hardcoded default rates
     - No fallback to invoice type prefix
     - Always computed from actual data

✅ 3. VERIFY against Indonesian regulations
     - Check all valid PPN rates (0%, 1.1%, 3%, 5%, 11%, 12%)
     - Log if rate is invalid (but don't block - allow for edge cases)

✅ 4. NO FIELD SWAP BUG
     - Check PPN > DPP immediately → Critical error
     - Prevents major parsing mistakes

✅ 5. Pattern specificity
     - "Dikurangi Uang Muka" instead of "Uang Muka" only
     - Avoids matching on label headers like "Harga Jual / Penggantian / Uang Muka / Termin"

═══════════════════════════════════════════════════════════════════════════════

EXAMPLE TRACE (Invoice from Lampiran):

Input: Vision API JSON + OCR text
│
├─ Extract summary section (lines with "Dasar Pengenaan Pajak")
│  └─ Lines 9-15 of OCR (not item details lines 3-8)
│
├─ Pattern match in summary section:
│  ├─ "Harga Jual ... Termin 1.102.900,00" → harga_jual = 1,102,900
│  ├─ "Dikurangi Potongan Harga 0,00" → potongan_harga = 0
│  ├─ "Dikurangi Uang Muka ... -" → uang_muka = 0
│  ├─ "Dasar Pengenaan Pajak 1.010.625,00" → dpp = 1,010,625
│  └─ "Jumlah PPN (...) 121.275,00" → ppn = 121,275
│
├─ Validate no field swap:
│  └─ PPN (121,275) < DPP (1,010,625) ✅ OK
│
├─ Calculate tax rate:
│  └─ rate = 121,275 / 1,010,625 = 0.12 (12%)
│
├─ Match to standard rates:
│  └─ 0.12 ≈ 0.12 (within tolerance) → Matched to 12%
│
├─ Verify against Indonesian regulations:
│  └─ 12% is valid (Standard Current rate since Jan 2025) ✅
│
├─ Comprehensive validation:
│  ├─ No negative values ✅
│  ├─ DPP ≤ Harga Jual ✅
│  ├─ PPN ≈ DPP × 12% (121,612.5 ≈ 121,275) ✅ (within tolerance)
│  └─ All checks pass ✅
│
└─ Output:
   {
     "harga_jual": 1102900.0,
     "dpp": 1010625.0,
     "ppn": 121275.0,
     "ppnbm": 0.0,
     "tax_rate": 0.12,
     "is_valid": True,
     "rate_type": "Standard (Current)",
     "validation_issues": []
   }

═══════════════════════════════════════════════════════════════════════════════
"""
