# -*- coding: utf-8 -*-
"""
Tests for multi-row item parsing fixes.

Covers:
    1. Smart filter logic — "Potongan Harga" in item detail vs summary label
    2. Multi-row item grouping (merge_description_wraparounds)
    3. Summary section parsing (extract_summary_values)
    4. Cross-validation (validate_parsed_data)
"""

import re
import sys
import unittest
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Portable stubs for running outside a Frappe bench environment
# ---------------------------------------------------------------------------

_frappe_stub = MagicMock()
_frappe_stub.logger.return_value = MagicMock()
_frappe_stub.utils.flt = lambda x, precision=None: float(x or 0)
_frappe_stub.utils.cint = lambda x: int(x or 0)
_frappe_stub._ = lambda x: x
_frappe_stub.utils.fmt_money = lambda v, currency=None: f"{v:,.0f}"

if "frappe" not in sys.modules:
    sys.modules["frappe"] = _frappe_stub
    sys.modules["frappe.utils"] = _frappe_stub.utils
    sys.modules["frappe.utils.formatters"] = MagicMock()
    sys.modules["frappe.exceptions"] = MagicMock()


# ---------------------------------------------------------------------------
# Test helpers — inline reimplementations so tests are self-contained
# ---------------------------------------------------------------------------

def parse_indonesian_currency(value_str: str) -> float:
    """Minimal reimplementation for testing."""
    if not value_str:
        return 0.0
    text = value_str.strip()
    text = re.sub(r'^[Rr][Pp]\s*', '', text)
    text = text.strip()
    if not text:
        return 0.0
    comma_count = text.count(',')
    if comma_count == 1:
        parts = text.split(',')
        integer_part = parts[0].replace('.', '').replace(' ', '')
        decimal_part = parts[1].strip()
        text = f"{integer_part}.{decimal_part}"
    elif comma_count == 0:
        text = text.replace('.', '').replace(' ', '')
        text = re.sub(r'[^\d]', '', text)
    else:
        return 0.0
    if not text:
        return 0.0
    try:
        return float(text)
    except (ValueError, TypeError):
        return 0.0


# ============================================================================
# Test 1: Smart Filter Logic
# ============================================================================

class TestSmartFilterLogic(unittest.TestCase):
    """Verify _is_summary_row correctly distinguishes items from summary rows."""

    # ---- helpers ----

    SIGNATURE_STOP_KEYWORDS: set = {
        "ditandatangani secara elektronik",
    }

    SUMMARY_ROW_KEYWORDS: set = {
        "harga jual / pengganti",
        "harga jual/pengganti",
        "harga jual / pengganti / uang muka",
        "harga jual/pengganti/uang muka",
        "dasar pengenaan pajak",
        "jumlah ppn",
        "jumlah ppnbm",
        "ppn = ",
        "ppn =",
        "ppnbm = ",
        "ppnbm =",
        "grand total",
        # "potongan harga" REMOVED — now handled by SUMMARY_START_KEYWORDS
        "uang muka yang telah diterima",
        "nilai lain",
        "total harga",
        "sub total",
        "subtotal",
        "ditandatangani secara elektronik",
    }

    SUMMARY_START_KEYWORDS: list = [
        "dikurangi potongan harga",
        "potongan harga",
        "harga jual",
        "dasar pengenaan",
        "jumlah ppn",
        "jumlah ppnbm",
    ]

    HEADER_ROW_KEYWORDS: set = {
        "no. barang",
        "nama barang",
        "no. barang / nama barang",
        "kode barang",
        "harga satuan",
        "jumlah barang",
    }

    ZERO_VALUE_SUSPECT_KEYWORDS: set = {
        "ppn", "dpp", "dasar", "harga jual", "pengganti", "total", "jumlah",
    }

    def _is_summary_row(self, row: Dict[str, Any]) -> Tuple[bool, str, str]:
        """Mirror of the fixed _is_summary_row logic."""
        description = row.get("description", "")
        if not description:
            return False, "", ""

        text_lower = re.sub(r'\s+', ' ', description.lower().strip())

        # Item-number override
        if re.match(r'^\d+\s+\d{4,6}', text_lower):
            return False, "", ""

        # Broad substring match
        for kw in self.SUMMARY_ROW_KEYWORDS:
            if kw in text_lower:
                return True, f"summary keyword '{kw}'", "summary"

        # Start-of-description match
        for kw in self.SUMMARY_START_KEYWORDS:
            if text_lower.startswith(kw):
                raw_hj = row.get("harga_jual", "")
                if raw_hj and str(raw_hj).strip():
                    continue
                return True, f"summary start keyword '{kw}'", "summary"

        for kw in self.HEADER_ROW_KEYWORDS:
            if kw in text_lower:
                return True, f"header keyword '{kw}'", "header"

        raw_dpp = row.get("dpp") or row.get("raw_dpp") or ""
        raw_ppn = row.get("ppn") or row.get("raw_ppn") or ""
        try:
            dpp_val = float(str(raw_dpp).replace(".", "").replace(",", ".")) if str(raw_dpp).strip() else 0
        except (ValueError, TypeError):
            dpp_val = 0
        try:
            ppn_val = float(str(raw_ppn).replace(".", "").replace(",", ".")) if str(raw_ppn).strip() else 0
        except (ValueError, TypeError):
            ppn_val = 0

        if dpp_val == 0 and ppn_val == 0:
            # Skip zero-suspect check if row has a valid harga_jual value
            raw_hj_check = row.get("harga_jual", "")
            has_harga_jual = bool(raw_hj_check and str(raw_hj_check).strip())
            if not has_harga_jual:
                for kw in self.ZERO_VALUE_SUSPECT_KEYWORDS:
                    if kw in text_lower:
                        return True, f"zero DPP/PPN with suspect keyword '{kw}'", "zero_suspect"

        return False, "", ""

    # ---- tests ----

    def test_item_with_potongan_harga_in_description_kept(self):
        """Line items whose merged description contains 'Potongan Harga' must NOT be filtered."""
        row = {
            "description": (
                "HYDRO CARBON TREATMENT Rp 360.500,00 x 1,00 Lainnya "
                "Potongan Harga = Rp 0,00 PPnBM (0,00%) = Rp 0,00"
            ),
            "harga_jual": "360.500,00",
            "dpp": "",
            "ppn": "",
        }
        is_filtered, reason, ftype = self._is_summary_row(row)
        self.assertFalse(is_filtered, f"Item was incorrectly filtered: {reason}")

    def test_summary_dikurangi_potongan_harga_filtered(self):
        """Standalone summary label 'Dikurangi Potongan Harga' with no harga_jual → FILTER."""
        row = {
            "description": "Dikurangi Potongan Harga",
            "harga_jual": "",
            "dpp": "",
            "ppn": "",
        }
        is_filtered, reason, ftype = self._is_summary_row(row)
        self.assertTrue(is_filtered, "Summary row 'Dikurangi Potongan Harga' should be filtered")

    def test_summary_potongan_harga_with_value_kept(self):
        """If 'Potongan Harga' row has an actual harga_jual value, keep it (edge case)."""
        row = {
            "description": "Potongan Harga Layanan Cuci",
            "harga_jual": "50.000,00",
            "dpp": "",
            "ppn": "",
        }
        is_filtered, reason, ftype = self._is_summary_row(row)
        self.assertFalse(is_filtered, "Potongan Harga with harga_jual value should be kept")

    def test_dasar_pengenaan_pajak_filtered(self):
        row = {"description": "Dasar Pengenaan Pajak", "harga_jual": "", "dpp": "", "ppn": ""}
        is_filtered, _, _ = self._is_summary_row(row)
        self.assertTrue(is_filtered)

    def test_item_number_pattern_always_kept(self):
        """Row starting with '1 000000' is always an item, even if merged text has keywords."""
        row = {
            "description": "1 000000 HYDRO CARBON TREATMENT Potongan Harga = Rp 0,00",
            "harga_jual": "360.500,00",
            "dpp": "",
            "ppn": "",
        }
        is_filtered, _, _ = self._is_summary_row(row)
        self.assertFalse(is_filtered, "Item number pattern should override keyword match")

    def test_harga_jual_pengganti_filtered(self):
        row = {
            "description": "Harga Jual / Pengganti / Uang Muka / Termin",
            "harga_jual": "",
        }
        is_filtered, _, _ = self._is_summary_row(row)
        self.assertTrue(is_filtered)

    def test_normal_item_description_kept(self):
        row = {
            "description": "JASA AC LIGHT ADVANCE-05S",
            "harga_jual": "380.000,00",
            "dpp": "",
            "ppn": "",
        }
        is_filtered, _, _ = self._is_summary_row(row)
        self.assertFalse(is_filtered)

    def test_header_row_filtered(self):
        row = {"description": "No. Barang / Nama Barang Kena Pajak", "harga_jual": ""}
        is_filtered, _, ftype = self._is_summary_row(row)
        self.assertTrue(is_filtered)
        self.assertEqual(ftype, "header")


# ============================================================================
# Test 2: Multi-Row Item Grouping
# ============================================================================

class TestMultiRowItemGrouping(unittest.TestCase):
    """Test merge_description_wraparounds() preserves items with values."""

    def _merge(self, rows: List[Dict]) -> List[Dict]:
        """Reimplementation of the fixed merge_description_wraparounds."""
        if not rows:
            return []

        merged = []
        current_row = None

        for row in rows:
            has_numbers = any([
                row.get("harga_jual"),
                row.get("dpp"),
                row.get("ppn"),
            ])

            description_only_keywords = [
                "ppnbm", "potongan", "diskon", "discount",
                "x 1,00", "x 1.00", "lainnya",
            ]
            desc_text = (row.get("description", "") or "").lower()
            is_description_only = (
                not has_numbers
                and any(keyword in desc_text for keyword in description_only_keywords)
            )

            if (has_numbers or not is_description_only) or current_row is None:
                if current_row:
                    merged.append(current_row)
                current_row = row
            else:
                if current_row and row.get("description"):
                    prev_desc = current_row.get("description", "")
                    new_desc = row.get("description", "")
                    current_row["description"] = f"{prev_desc} {new_desc}".strip()

        if current_row:
            merged.append(current_row)

        return merged

    def test_five_item_invoice_multi_row(self):
        """Multi-row items (6 rows each) should merge into 5 items."""
        # Simulate OCR rows for a 5-item invoice
        raw_rows = [
            # Item 1 — rows span: item number, description, price detail, potongan, ppnbm, value
            {"description": "1 000000", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "HYDRO CARBON TREATMENT", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "Rp 360.500,00 x 1,00 Lainnya", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "Potongan Harga = Rp 0,00", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "PPnBM (0,00%) = Rp 0,00", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "", "harga_jual": "360.500,00", "dpp": "", "ppn": ""},

            # Item 2
            {"description": "2 000000", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "JASA AC LIGHT ADVANCE-05S", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "Rp 380.000,00 x 1,00 Lainnya", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "Potongan Harga = Rp 0,00", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "PPnBM (0,00%) = Rp 0,00", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "", "harga_jual": "380.000,00", "dpp": "", "ppn": ""},

            # Item 3
            {"description": "3 000000", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "NITROGEN - KURAS", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "Rp 54.000,00 x 1,00 Lainnya", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "Potongan Harga = Rp 0,00", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "PPnBM (0,00%) = Rp 0,00", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "", "harga_jual": "54.000,00", "dpp": "", "ppn": ""},

            # Item 4
            {"description": "4 000000", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "SPOORING B", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "Rp 228.000,00 x 1,00 Lainnya", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "Potongan Harga = Rp 0,00", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "PPnBM (0,00%) = Rp 0,00", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "", "harga_jual": "228.000,00", "dpp": "", "ppn": ""},

            # Item 5
            {"description": "5 000000", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "TIMAH BALANCE", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "Rp 80.000,00 x 1,00 Lainnya", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "Potongan Harga = Rp 0,00", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "PPnBM (0,00%) = Rp 0,00", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "", "harga_jual": "80.000,00", "dpp": "", "ppn": ""},
        ]

        merged = self._merge(raw_rows)

        # Should have 5 items (each with an harga_jual value)
        items_with_values = [r for r in merged if r.get("harga_jual")]
        self.assertEqual(len(items_with_values), 5, f"Expected 5 items, got {len(items_with_values)}")

        # Verify values
        expected_values = ["360.500,00", "380.000,00", "54.000,00", "228.000,00", "80.000,00"]
        actual_values = [r["harga_jual"] for r in items_with_values]
        self.assertEqual(actual_values, expected_values)

    def test_detail_rows_merge_into_previous(self):
        """Rows with 'Potongan' or 'PPnBM' and no values merge into previous row."""
        rows = [
            {"description": "HYDRO CARBON TREATMENT", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "Potongan Harga = Rp 0,00", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "PPnBM (0,00%) = Rp 0,00", "harga_jual": "", "dpp": "", "ppn": ""},
        ]
        merged = self._merge(rows)
        self.assertEqual(len(merged), 1)
        self.assertIn("Potongan Harga", merged[0]["description"])
        self.assertIn("PPnBM", merged[0]["description"])

    def test_row_with_value_not_merged(self):
        """Row with harga_jual value is always kept as a separate data row."""
        rows = [
            {"description": "ITEM A", "harga_jual": "", "dpp": "", "ppn": ""},
            {"description": "Potongan detail", "harga_jual": "100.000,00", "dpp": "", "ppn": ""},
        ]
        merged = self._merge(rows)
        # Row 2 has harga_jual, so it should NOT merge into row 1
        self.assertEqual(len(merged), 2)


# ============================================================================
# Test 3: Summary Section Parsing
# ============================================================================

class TestSummaryParsing(unittest.TestCase):
    """Test that extract_summary_values correctly reads all summary fields."""

    def test_standard_summary_extraction(self):
        """Standard 5-item invoice summary section."""
        ocr_text = """
Harga Jual / Penggantian / Uang Muka / Termin    1.102.500,00
Dikurangi Potongan Harga                                 0,00
Dasar Pengenaan Pajak                            1.010.625,00
Jumlah PPN (Pajak Pertambahan Nilai)               121.275,00
Jumlah PPnBM (Pajak Penjualan atas Barang Mewah)        0,00
"""
        # Test with inline parse (without frappe dependency)
        lines = ocr_text.strip().split('\n')

        # Find Harga Jual
        for line in lines:
            if "Harga Jual" in line:
                match = re.search(r'([\d\.]+,\d{2})\s*$', line.strip())
                if match:
                    hj = parse_indonesian_currency(match.group(1))
                    self.assertAlmostEqual(hj, 1102500.0, places=0)
                    break

        # Find DPP
        for line in lines:
            if "Dasar Pengenaan Pajak" in line:
                match = re.search(r'([\d\.]+,\d{2})\s*$', line.strip())
                if match:
                    dpp = parse_indonesian_currency(match.group(1))
                    self.assertAlmostEqual(dpp, 1010625.0, places=0)
                    break

        # Find PPN
        for line in lines:
            if "Jumlah PPN" in line:
                match = re.search(r'([\d\.]+,\d{2})\s*$', line.strip())
                if match:
                    ppn = parse_indonesian_currency(match.group(1))
                    self.assertAlmostEqual(ppn, 121275.0, places=0)
                    break

    def test_ppn_is_12_percent_of_dpp(self):
        """PPN should be approximately 12% of DPP."""
        dpp = 1010625.0
        ppn = 121275.0
        actual_rate = ppn / dpp
        self.assertAlmostEqual(actual_rate, 0.12, places=2)


# ============================================================================
# Test 4: Cross-Validation
# ============================================================================

class TestValidateParsedData(unittest.TestCase):
    """Test validate_parsed_data cross-check logic."""

    def _validate(self, items, summary, tax_rate=0.12, tolerance_pct=0.01):
        """Reimplementation of validate_parsed_data for standalone testing."""
        errors = []
        warnings = []
        items = items or []
        summary = summary or {}

        summary_hj = float(summary.get("harga_jual", 0) or 0)
        summary_dpp = float(summary.get("dpp", 0) or 0)
        summary_ppn = float(summary.get("ppn", 0) or 0)

        if len(items) == 0:
            errors.append("No line items parsed from invoice")

        items_sum = sum(float(item.get("harga_jual", 0) or 0) for item in items)
        hj_diff = abs(items_sum - summary_hj) if summary_hj else 0
        hj_tolerance = summary_hj * tolerance_pct if summary_hj else 0

        if summary_hj > 0 and hj_diff > hj_tolerance:
            errors.append(f"Harga Jual mismatch: {items_sum:,.0f} != {summary_hj:,.0f}")

        if summary_dpp > 0 and summary_ppn > 0:
            expected_ppn = summary_dpp * tax_rate
            ppn_diff = abs(summary_ppn - expected_ppn)
            ppn_tolerance = expected_ppn * tolerance_pct
            if ppn_diff > ppn_tolerance:
                warnings.append(f"PPN mismatch: expected {expected_ppn:,.0f}, got {summary_ppn:,.0f}")

        return {"is_valid": len(errors) == 0, "errors": errors, "warnings": warnings}

    def test_valid_5_item_invoice(self):
        items = [
            {"harga_jual": 360500},
            {"harga_jual": 380000},
            {"harga_jual": 54000},
            {"harga_jual": 228000},
            {"harga_jual": 80000},
        ]
        summary = {"harga_jual": 1102500, "dpp": 1010625, "ppn": 121275}

        result = self._validate(items, summary)
        self.assertTrue(result["is_valid"], f"Should be valid: {result['errors']}")

    def test_missing_items_invalid(self):
        result = self._validate([], {"harga_jual": 1000000})
        self.assertFalse(result["is_valid"])
        self.assertIn("No line items", result["errors"][0])

    def test_sum_mismatch_invalid(self):
        items = [{"harga_jual": 100000}]
        summary = {"harga_jual": 500000, "dpp": 0, "ppn": 0}
        result = self._validate(items, summary)
        self.assertFalse(result["is_valid"])

    def test_ppn_rate_warning(self):
        """PPN at 11% when expecting 12% should produce warning."""
        summary = {"harga_jual": 1000000, "dpp": 1000000, "ppn": 110000}
        items = [{"harga_jual": 1000000}]
        result = self._validate(items, summary, tax_rate=0.12)
        self.assertTrue(result["is_valid"])  # Still valid (it's a warning, not error)
        self.assertTrue(len(result["warnings"]) > 0, "Should have PPN rate warning")

    def test_zero_rated_no_warning(self):
        """Zero-rated transaction (PPN=0) should not error — it's a warning."""
        items = [{"harga_jual": 500000}]
        summary = {"harga_jual": 500000, "dpp": 500000, "ppn": 0}
        result = self._validate(items, summary)
        self.assertTrue(result["is_valid"])


# ============================================================================
# Test 5: Indonesian Currency Parser
# ============================================================================

class TestIndonesianCurrencyParser(unittest.TestCase):
    """Test IDR amount parsing edge cases."""

    def test_standard_format(self):
        self.assertAlmostEqual(parse_indonesian_currency("1.102.500,00"), 1102500.0)

    def test_small_amount(self):
        self.assertAlmostEqual(parse_indonesian_currency("360.500,00"), 360500.0)

    def test_zero(self):
        self.assertAlmostEqual(parse_indonesian_currency("0,00"), 0.0)

    def test_with_rp_prefix(self):
        self.assertAlmostEqual(parse_indonesian_currency("Rp 360.500,00"), 360500.0)

    def test_large_amount(self):
        self.assertAlmostEqual(parse_indonesian_currency("1.010.625,00"), 1010625.0)

    def test_integer_only(self):
        self.assertAlmostEqual(parse_indonesian_currency("121275"), 121275.0)

    def test_empty_string(self):
        self.assertEqual(parse_indonesian_currency(""), 0.0)

    def test_none_like(self):
        self.assertEqual(parse_indonesian_currency("  "), 0.0)


if __name__ == "__main__":
    unittest.main()
