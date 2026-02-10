# -*- coding: utf-8 -*-
"""
Tests for multi-row item grouping & summary parser fixes.

Covers all 3 critical fixes:
    Fix #1: Multi-row item grouping (group_multirow_items, parse_grouped_item)
    Fix #2: Smart filter (is_summary_row)
    Fix #3: Summary section parsing (parse_summary_section)
    Bonus: Cross-validation (validate_parsed_data)

Run standalone:
    python -m pytest tests/test_multirow_parser.py -v
    # or
    python tests/test_multirow_parser.py
"""

import re
import sys
import unittest
from typing import Any, Dict, List
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Portable stubs for running outside a Frappe bench environment
# ---------------------------------------------------------------------------

_frappe_stub = MagicMock()
_frappe_stub.logger.return_value = MagicMock()
_frappe_stub.utils.flt = lambda x, precision=None: float(x or 0)
_frappe_stub.utils.cint = lambda x: int(x or 0)
_frappe_stub._ = lambda x: x

if "frappe" not in sys.modules:
    sys.modules["frappe"] = _frappe_stub
    sys.modules["frappe.utils"] = _frappe_stub.utils
    sys.modules["frappe.utils.formatters"] = MagicMock()
    sys.modules["frappe.exceptions"] = MagicMock()

# ---------------------------------------------------------------------------
# Import production code
# ---------------------------------------------------------------------------
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from imogi_finance.imogi_finance.parsers.multirow_parser import (
    group_multirow_items,
    is_summary_row,
    parse_grouped_item,
    parse_indonesian_number,
    parse_summary_from_full_text,
    parse_summary_section,
    validate_parsed_data,
)


# =============================================================================
# Helper: Build 5-item test invoice text blocks
# =============================================================================

def build_5_item_invoice_blocks() -> List[Dict]:
    """
    Build text blocks simulating the 5-item test invoice (04002500436451666).

    Each item spans 6 rows:
        Row 1: "N 000000"              (item number + code)
        Row 2: "DESCRIPTION"           (item description)
        Row 3: "Rp X x N,NN Lainnya"   (unit price × qty)
        Row 4: "Potongan Harga = ..."  (discount)
        Row 5: "PPnBM (0,00%) = ..."   (luxury tax)
        Row 6: "VALUE"                 (harga_jual in right column)

    Returns:
        List of text blocks sorted by Y coordinate.
    """
    items = [
        (1, "HYDRO CARBON TREATMENT", "360.500,00", 1),
        (2, "JASA AC LIGHT ADVANCE-05S", "380.000,00", 1),
        (3, "NITROGEN - KURAS", "54.000,00", 1),
        (4, "SPOORING B (INV,RSH,YRS,VIOS,LIMO,HLX)", "228.000,00", 1),
        (5, "TIMAH BALANCE", "80.000,00", 1),
    ]

    blocks = []
    y = 100
    for line_no, desc, price, qty in items:
        blocks.append({'text': f'{line_no} 000000', 'x': 50, 'y': y})
        y += 12
        blocks.append({'text': desc, 'x': 50, 'y': y})
        y += 12
        blocks.append({'text': f'Rp {price} x {qty},00 Lainnya', 'x': 50, 'y': y})
        y += 12
        blocks.append({'text': 'Potongan Harga = Rp 0,00', 'x': 50, 'y': y})
        y += 12
        blocks.append({'text': 'PPnBM (0,00%) = Rp 0,00', 'x': 50, 'y': y})
        y += 12
        blocks.append({'text': price, 'x': 450, 'y': y})
        y += 20  # Larger gap between items

    return blocks


def build_summary_blocks(y_start: float = 600) -> List[Dict]:
    """Build text blocks for the invoice summary section."""
    y = y_start
    return [
        {'text': 'Harga Jual / Penggantian / Uang Muka / Termin', 'x': 50, 'y': y},
        {'text': '1.102.500,00', 'x': 450, 'y': y},
        {'text': 'Dikurangi Potongan Harga', 'x': 50, 'y': y + 25},
        {'text': '0,00', 'x': 450, 'y': y + 25},
        {'text': 'Dasar Pengenaan Pajak', 'x': 50, 'y': y + 50},
        {'text': '1.010.625,00', 'x': 450, 'y': y + 50},
        {'text': 'Jumlah PPN (Pajak Pertambahan Nilai)', 'x': 50, 'y': y + 75},
        {'text': '121.275,00', 'x': 450, 'y': y + 75},
        {'text': 'Jumlah PPnBM (Pajak Penjualan atas Barang Mewah)', 'x': 50, 'y': y + 100},
        {'text': '0,00', 'x': 450, 'y': y + 100},
    ]


# =============================================================================
# Test 1: Indonesian Number Parser
# =============================================================================

class TestParseIndonesianNumber(unittest.TestCase):
    """Test parse_indonesian_number for all Indonesian currency formats."""

    def test_standard_format_with_thousands_and_decimals(self):
        self.assertAlmostEqual(parse_indonesian_number("1.102.500,00"), 1102500.0)

    def test_small_amount(self):
        self.assertAlmostEqual(parse_indonesian_number("360.500,00"), 360500.0)

    def test_medium_amount(self):
        self.assertAlmostEqual(parse_indonesian_number("1.010.625,00"), 1010625.0)

    def test_zero(self):
        self.assertAlmostEqual(parse_indonesian_number("0,00"), 0.0)

    def test_with_rp_prefix(self):
        self.assertAlmostEqual(parse_indonesian_number("Rp 360.500,00"), 360500.0)

    def test_with_rp_no_space(self):
        self.assertAlmostEqual(parse_indonesian_number("Rp360.500,00"), 360500.0)

    def test_integer_only(self):
        self.assertAlmostEqual(parse_indonesian_number("121275"), 121275.0)

    def test_thousand_dots_no_decimal(self):
        self.assertAlmostEqual(parse_indonesian_number("360.500"), 360500.0)

    def test_empty_string(self):
        self.assertEqual(parse_indonesian_number(""), 0.0)

    def test_whitespace_only(self):
        self.assertEqual(parse_indonesian_number("   "), 0.0)

    def test_none(self):
        self.assertEqual(parse_indonesian_number(None), 0.0)

    def test_large_amount(self):
        self.assertAlmostEqual(parse_indonesian_number("15.000.000,00"), 15000000.0)

    def test_very_large_amount(self):
        self.assertAlmostEqual(parse_indonesian_number("1.500.000.000,00"), 1500000000.0)


# =============================================================================
# Test 2: Smart Filter (is_summary_row) — Fix #2
# =============================================================================

class TestIsSummaryRow(unittest.TestCase):
    """Verify is_summary_row correctly distinguishes items from summary rows."""

    # ---- Items that should be KEPT (return False) ----

    def test_item_number_pattern_always_kept(self):
        """Row starting with item pattern is ALWAYS a line item."""
        self.assertFalse(is_summary_row("1 000000"))

    def test_item_with_embedded_potongan_harga_kept(self):
        """Item row containing 'Potongan Harga' with '=' is item detail."""
        self.assertFalse(is_summary_row("1 000000 Potongan Harga = Rp 0,00"))

    def test_normal_description_kept(self):
        self.assertFalse(is_summary_row("HYDRO CARBON TREATMENT"))

    def test_jasa_description_kept(self):
        self.assertFalse(is_summary_row("JASA AC LIGHT ADVANCE-05S"))

    def test_price_qty_line_kept(self):
        """Price × quantity line is item detail."""
        self.assertFalse(is_summary_row("Rp 360.500,00 x 1,00 Lainnya"))

    def test_potongan_harga_with_equals_kept(self):
        """'Potongan Harga = Rp 0,00' is item detail, NOT summary."""
        self.assertFalse(is_summary_row("Potongan Harga = Rp 0,00"))

    def test_ppnbm_item_detail_kept(self):
        """PPnBM with percentage is item detail."""
        self.assertFalse(is_summary_row("PPnBM (0,00%) = Rp 0,00"))

    def test_pure_amount_kept(self):
        """Pure numeric value is a column value, not summary."""
        self.assertFalse(is_summary_row("360.500,00"))

    def test_item_10_pattern_kept(self):
        """Double-digit item numbers work too."""
        self.assertFalse(is_summary_row("10 000000 SOME ITEM"))

    # ---- Summary rows that should be FILTERED (return True) ----

    def test_harga_jual_penggantian_filtered(self):
        self.assertTrue(is_summary_row("Harga Jual / Penggantian / Uang Muka / Termin"))

    def test_harga_jual_slash_filtered(self):
        self.assertTrue(is_summary_row("Harga Jual / Penggantian"))

    def test_dikurangi_potongan_harga_filtered(self):
        """Standalone 'Dikurangi Potongan Harga' is a summary label."""
        self.assertTrue(is_summary_row("Dikurangi Potongan Harga"))

    def test_dasar_pengenaan_pajak_filtered(self):
        self.assertTrue(is_summary_row("Dasar Pengenaan Pajak"))

    def test_jumlah_ppn_filtered(self):
        self.assertTrue(is_summary_row("Jumlah PPN (Pajak Pertambahan Nilai)"))

    def test_jumlah_ppnbm_filtered(self):
        self.assertTrue(is_summary_row("Jumlah PPnBM (Pajak Penjualan atas Barang Mewah)"))

    def test_grand_total_filtered(self):
        self.assertTrue(is_summary_row("Grand Total"))

    def test_ditandatangani_filtered(self):
        self.assertTrue(is_summary_row("Ditandatangani secara elektronik"))

    def test_dikurangi_uang_muka_filtered(self):
        self.assertTrue(is_summary_row("Dikurangi Uang Muka yang telah diterima"))

    def test_header_row_filtered(self):
        self.assertTrue(is_summary_row("No. Barang / Nama Barang Kena Pajak"))

    # ---- Edge cases ----

    def test_empty_string_not_filtered(self):
        self.assertFalse(is_summary_row(""))

    def test_none_not_filtered(self):
        self.assertFalse(is_summary_row(None))

    def test_whitespace_not_filtered(self):
        self.assertFalse(is_summary_row("   "))


# =============================================================================
# Test 3: Multi-Row Item Grouping — Fix #1
# =============================================================================

class TestGroupMultirowItems(unittest.TestCase):
    """Test group_multirow_items groups 6-row items correctly."""

    def test_single_item_6_rows(self):
        """One complete item (6 rows) grouped as one."""
        blocks = [
            {'text': '1 000000', 'x': 50, 'y': 100},
            {'text': 'HYDRO CARBON TREATMENT', 'x': 50, 'y': 110},
            {'text': 'Rp 360.500,00 x 1,00 Lainnya', 'x': 50, 'y': 120},
            {'text': 'Potongan Harga = Rp 0,00', 'x': 50, 'y': 130},
            {'text': 'PPnBM (0,00%) = Rp 0,00', 'x': 50, 'y': 140},
            {'text': '360.500,00', 'x': 450, 'y': 150},
        ]
        result = group_multirow_items(blocks)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['line_no'], 1)
        self.assertEqual(len(result[0]['rows']), 6)
        self.assertEqual(result[0]['y_start'], 100)
        self.assertEqual(result[0]['y_end'], 150)

    def test_two_items_12_rows(self):
        """Two items (12 rows) grouped as two."""
        blocks = [
            {'text': '1 000000', 'x': 50, 'y': 100},
            {'text': 'HYDRO CARBON TREATMENT', 'x': 50, 'y': 110},
            {'text': 'Rp 360.500,00 x 1,00 Lainnya', 'x': 50, 'y': 120},
            {'text': 'Potongan Harga = Rp 0,00', 'x': 50, 'y': 130},
            {'text': 'PPnBM (0,00%) = Rp 0,00', 'x': 50, 'y': 140},
            {'text': '360.500,00', 'x': 450, 'y': 150},
            {'text': '2 000000', 'x': 50, 'y': 170},
            {'text': 'JASA AC LIGHT ADVANCE-05S', 'x': 50, 'y': 180},
            {'text': 'Rp 380.000,00 x 1,00 Lainnya', 'x': 50, 'y': 190},
            {'text': 'Potongan Harga = Rp 0,00', 'x': 50, 'y': 200},
            {'text': 'PPnBM (0,00%) = Rp 0,00', 'x': 50, 'y': 210},
            {'text': '380.000,00', 'x': 450, 'y': 220},
        ]
        result = group_multirow_items(blocks)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['line_no'], 1)
        self.assertEqual(result[1]['line_no'], 2)
        self.assertEqual(len(result[0]['rows']), 6)
        self.assertEqual(len(result[1]['rows']), 6)

    def test_five_item_invoice(self):
        """Full 5-item invoice grouped into exactly 5 groups."""
        blocks = build_5_item_invoice_blocks()
        result = group_multirow_items(blocks)

        self.assertEqual(len(result), 5, f"Expected 5 items, got {len(result)}")
        for i, group in enumerate(result, 1):
            self.assertEqual(group['line_no'], i, f"Item {i} has wrong line_no")
            self.assertEqual(
                len(group['rows']), 6,
                f"Item {i} should have 6 rows, got {len(group['rows'])}"
            )

    def test_stops_at_summary_section(self):
        """Grouping stops when summary section row is encountered."""
        blocks = [
            {'text': '1 000000', 'x': 50, 'y': 100},
            {'text': 'HYDRO CARBON TREATMENT', 'x': 50, 'y': 110},
            {'text': '360.500,00', 'x': 450, 'y': 120},
            # Summary section starts
            {'text': 'Harga Jual / Penggantian / Uang Muka / Termin', 'x': 50, 'y': 200},
            {'text': '1.102.500,00', 'x': 450, 'y': 200},
        ]
        result = group_multirow_items(blocks)

        self.assertEqual(len(result), 1)

    def test_empty_input(self):
        self.assertEqual(group_multirow_items([]), [])

    def test_no_items_only_summary(self):
        """Only summary rows — no items grouped."""
        blocks = [
            {'text': 'Harga Jual / Penggantian', 'x': 50, 'y': 100},
            {'text': '1.000.000,00', 'x': 450, 'y': 100},
        ]
        result = group_multirow_items(blocks)
        self.assertEqual(len(result), 0)


# =============================================================================
# Test 4: Parse Grouped Item
# =============================================================================

class TestParseGroupedItem(unittest.TestCase):
    """Test parse_grouped_item extracts structured data."""

    def _make_group(
        self,
        line_no: int,
        description: str,
        price: str,
        qty: int = 1,
    ) -> Dict:
        y = 100
        rows = [
            {'text': f'{line_no} 000000', 'x': 50, 'y': y},
            {'text': description, 'x': 50, 'y': y + 12},
            {'text': f'Rp {price} x {qty},00 Lainnya', 'x': 50, 'y': y + 24},
            {'text': 'Potongan Harga = Rp 0,00', 'x': 50, 'y': y + 36},
            {'text': 'PPnBM (0,00%) = Rp 0,00', 'x': 50, 'y': y + 48},
            {'text': price, 'x': 450, 'y': y + 60},
        ]
        return {
            'line_no': line_no,
            'rows': rows,
            'y_start': y,
            'y_end': y + 60,
        }

    def test_extract_description(self):
        group = self._make_group(1, "HYDRO CARBON TREATMENT", "360.500,00")
        result = parse_grouped_item(group)
        self.assertEqual(result['description'], "HYDRO CARBON TREATMENT")

    def test_extract_harga_jual(self):
        group = self._make_group(1, "HYDRO CARBON TREATMENT", "360.500,00")
        result = parse_grouped_item(group)
        self.assertAlmostEqual(result['harga_jual'], 360500.0)

    def test_extract_unit_price(self):
        group = self._make_group(1, "HYDRO CARBON TREATMENT", "360.500,00")
        result = parse_grouped_item(group)
        self.assertAlmostEqual(result['unit_price'], 360500.0)

    def test_extract_qty(self):
        group = self._make_group(1, "HYDRO CARBON TREATMENT", "360.500,00")
        result = parse_grouped_item(group)
        self.assertAlmostEqual(result['qty'], 1.0)

    def test_extract_line_no(self):
        group = self._make_group(3, "NITROGEN - KURAS", "54.000,00")
        result = parse_grouped_item(group)
        self.assertEqual(result['line_no'], 3)

    def test_discount_zero(self):
        group = self._make_group(1, "HYDRO CARBON TREATMENT", "360.500,00")
        result = parse_grouped_item(group)
        self.assertAlmostEqual(result['discount'], 0.0)

    def test_ppnbm_zero(self):
        group = self._make_group(1, "HYDRO CARBON TREATMENT", "360.500,00")
        result = parse_grouped_item(group)
        self.assertAlmostEqual(result['ppnbm_rate'], 0.0)
        self.assertAlmostEqual(result['ppnbm_amount'], 0.0)

    def test_full_5_item_invoice_parse(self):
        """Parse all 5 items and verify descriptions and values."""
        blocks = build_5_item_invoice_blocks()
        groups = group_multirow_items(blocks)
        items = [parse_grouped_item(g) for g in groups]

        self.assertEqual(len(items), 5)

        expected = [
            (1, "HYDRO CARBON TREATMENT", 360500.0),
            (2, "JASA AC LIGHT ADVANCE-05S", 380000.0),
            (3, "NITROGEN - KURAS", 54000.0),
            (4, "SPOORING B (INV,RSH,YRS,VIOS,LIMO,HLX)", 228000.0),
            (5, "TIMAH BALANCE", 80000.0),
        ]

        for item, (exp_no, exp_desc, exp_hj) in zip(items, expected):
            self.assertEqual(item['line_no'], exp_no)
            self.assertEqual(item['description'], exp_desc)
            self.assertAlmostEqual(item['harga_jual'], exp_hj,
                                   msg=f"Item {exp_no} harga_jual mismatch")

    def test_empty_rows(self):
        group = {'line_no': 1, 'rows': [], 'y_start': 0, 'y_end': 0}
        result = parse_grouped_item(group)
        self.assertEqual(result['harga_jual'], 0.0)
        self.assertEqual(result['description'], '')


# =============================================================================
# Test 5: Summary Section Parsing — Fix #3
# =============================================================================

class TestParseSummarySection(unittest.TestCase):
    """Test coordinate-based summary parsing."""

    def test_standard_5_item_summary(self):
        """Parse 5-item invoice summary with coordinate blocks."""
        blocks = build_summary_blocks(y_start=600)
        result = parse_summary_section(blocks, page_height=800)

        self.assertAlmostEqual(result['harga_jual'], 1102500.0,
                               msg=f"harga_jual={result['harga_jual']}")
        self.assertAlmostEqual(result['potongan'], 0.0)
        self.assertAlmostEqual(result['dpp'], 1010625.0,
                               msg=f"dpp={result['dpp']}")
        self.assertAlmostEqual(result['ppn'], 121275.0,
                               msg=f"ppn={result['ppn']}")
        self.assertAlmostEqual(result['ppnbm'], 0.0)

    def test_harga_jual_not_confused_with_ppn(self):
        """harga_jual should be 1,102,500 NOT 121,275 (PPN value)."""
        blocks = build_summary_blocks()
        result = parse_summary_section(blocks, page_height=800)
        self.assertNotAlmostEqual(result['harga_jual'], 121275.0,
                                  msg="harga_jual should NOT be the PPN value!")
        self.assertAlmostEqual(result['harga_jual'], 1102500.0)

    def test_dpp_not_confused_with_item_price(self):
        """DPP should be 1,010,625 NOT 80,000 (last item price)."""
        blocks = build_summary_blocks()
        result = parse_summary_section(blocks, page_height=800)
        self.assertNotAlmostEqual(result['dpp'], 80000.0,
                                  msg="DPP should NOT be last item's price!")
        self.assertAlmostEqual(result['dpp'], 1010625.0)

    def test_ppn_not_miscalculated(self):
        """PPN should be 121,275 NOT 9,600."""
        blocks = build_summary_blocks()
        result = parse_summary_section(blocks, page_height=800)
        self.assertNotAlmostEqual(result['ppn'], 9600.0,
                                  msg="PPN should NOT be miscalculated!")
        self.assertAlmostEqual(result['ppn'], 121275.0)

    def test_empty_blocks(self):
        result = parse_summary_section([], page_height=800)
        self.assertEqual(result['dpp'], 0.0)
        self.assertEqual(result['ppn'], 0.0)

    def test_dpp_ppn_swap_detection(self):
        """If PPN > DPP, they should be auto-swapped."""
        blocks = [
            {'text': 'Dasar Pengenaan Pajak', 'x': 50, 'y': 600},
            {'text': '121.275,00', 'x': 450, 'y': 600},  # PPN value in DPP spot
            {'text': 'Jumlah PPN (Pajak Pertambahan Nilai)', 'x': 50, 'y': 650},
            {'text': '1.010.625,00', 'x': 450, 'y': 650},  # DPP value in PPN spot
        ]
        result = parse_summary_section(blocks, page_height=800)
        # After swap correction: DPP should be the larger value
        self.assertGreater(result['dpp'], result['ppn'],
                           msg="DPP should be greater than PPN after swap correction")


class TestParseSummaryFromFullText(unittest.TestCase):
    """Test text-based summary parsing (no coordinates)."""

    def test_standard_summary_text(self):
        text = """
Harga Jual / Penggantian / Uang Muka / Termin    1.102.500,00
Dikurangi Potongan Harga                                 0,00
Dasar Pengenaan Pajak                            1.010.625,00
Jumlah PPN (Pajak Pertambahan Nilai)               121.275,00
Jumlah PPnBM (Pajak Penjualan atas Barang Mewah)        0,00
"""
        result = parse_summary_from_full_text(text)

        self.assertAlmostEqual(result['harga_jual'], 1102500.0)
        self.assertAlmostEqual(result['dpp'], 1010625.0)
        self.assertAlmostEqual(result['ppn'], 121275.0)
        self.assertAlmostEqual(result['ppnbm'], 0.0)

    def test_summary_with_different_format(self):
        text = """
Harga Jual / Penggantian 4.953.154,00
Dikurangi Potongan Harga 247.658,00
Dasar Pengenaan Pajak 4.313.371,00
Jumlah PPN 517.605,00
Jumlah PPnBM 0,00
"""
        result = parse_summary_from_full_text(text)

        self.assertAlmostEqual(result['harga_jual'], 4953154.0)
        self.assertAlmostEqual(result['potongan'], 247658.0)
        self.assertAlmostEqual(result['dpp'], 4313371.0)
        self.assertAlmostEqual(result['ppn'], 517605.0)

    def test_ppn_is_12_percent_of_dpp(self):
        """PPN should be approximately 12% of DPP for test invoice."""
        text = """
Dasar Pengenaan Pajak 1.010.625,00
Jumlah PPN (Pajak Pertambahan Nilai) 121.275,00
"""
        result = parse_summary_from_full_text(text)
        if result['dpp'] > 0 and result['ppn'] > 0:
            rate = result['ppn'] / result['dpp']
            self.assertAlmostEqual(rate, 0.12, places=2,
                                   msg=f"PPN rate is {rate*100:.1f}%, expected ~12%")


# =============================================================================
# Test 6: Cross-Validation — Bonus
# =============================================================================

class TestValidateParsedData(unittest.TestCase):
    """Test validate_parsed_data cross-checking logic."""

    def test_valid_5_item_invoice(self):
        """All 5 items sum to summary harga_jual, PPN = DPP × 12%."""
        items = [
            {'harga_jual': 360500},
            {'harga_jual': 380000},
            {'harga_jual': 54000},
            {'harga_jual': 228000},
            {'harga_jual': 80000},
        ]
        summary = {'harga_jual': 1102500, 'dpp': 1010625, 'ppn': 121275}

        result = validate_parsed_data(items, summary, tax_rate=0.12)

        self.assertTrue(result['is_valid'], f"Should be valid: {result['errors']}")
        self.assertTrue(result['checks']['items_count_ok'])
        self.assertTrue(result['checks']['no_zero_values'])
        self.assertTrue(result['checks']['items_sum_matches'])
        self.assertTrue(result['checks']['ppn_calculation_ok'])

    def test_no_items_is_invalid(self):
        result = validate_parsed_data([], {'harga_jual': 1000000})
        self.assertFalse(result['is_valid'])
        self.assertFalse(result['checks']['items_count_ok'])
        self.assertIn("No line items", result['errors'][0])

    def test_zero_harga_jual_item_is_warning(self):
        """Zero harga_jual items are warnings, not fatal errors."""
        items = [
            {'harga_jual': 360500},
            {'harga_jual': 0},  # Zero value!
        ]
        summary = {'harga_jual': 360500, 'dpp': 330000, 'ppn': 39600}

        result = validate_parsed_data(items, summary)
        # Zero items are now a WARNING — is_valid depends only on real errors
        self.assertFalse(result['checks']['no_zero_values'])
        self.assertTrue(
            any('zero' in w.lower() for w in result['warnings']),
            "Zero items should appear in warnings"
        )

    def test_sum_mismatch_is_invalid(self):
        items = [{'harga_jual': 100000}]
        summary = {'harga_jual': 500000, 'dpp': 0, 'ppn': 0}
        result = validate_parsed_data(items, summary)
        self.assertFalse(result['is_valid'])
        self.assertFalse(result['checks']['items_sum_matches'])

    def test_ppn_rate_mismatch_produces_warning(self):
        """PPN at 11% when expecting 12% should produce warning but still be valid."""
        items = [{'harga_jual': 1000000}]
        summary = {'harga_jual': 1000000, 'dpp': 1000000, 'ppn': 110000}

        result = validate_parsed_data(items, summary, tax_rate=0.12)
        self.assertTrue(result['is_valid'])
        # Should have warning about rate mismatch AND/OR match at 11%
        self.assertTrue(len(result['warnings']) > 0)

    def test_zero_rated_transaction(self):
        """PPN=0 is valid (zero-rated transaction)."""
        items = [{'harga_jual': 500000}]
        summary = {'harga_jual': 500000, 'dpp': 500000, 'ppn': 0}

        result = validate_parsed_data(items, summary)
        self.assertTrue(result['is_valid'])

    def test_empty_summary(self):
        items = [{'harga_jual': 100000}]
        result = validate_parsed_data(items, {})
        # Should be valid but with warnings
        self.assertTrue(result['is_valid'])


# =============================================================================
# Test 7: End-to-End Integration
# =============================================================================

class TestEndToEndIntegration(unittest.TestCase):
    """Full pipeline: blocks → group → parse items → parse summary → validate."""

    def test_5_item_invoice_pipeline(self):
        """Complete pipeline for Invoice 04002500436451666."""
        # Step 1: Build full invoice (items + summary)
        item_blocks = build_5_item_invoice_blocks()
        summary_blocks = build_summary_blocks(y_start=600)
        all_blocks = item_blocks + summary_blocks

        # Step 2: Group items
        groups = group_multirow_items(item_blocks)
        self.assertEqual(len(groups), 5, "Should group into 5 items")

        # Step 3: Parse each item
        items = [parse_grouped_item(g) for g in groups]
        self.assertEqual(len(items), 5, "Should parse 5 items")

        # Verify correct descriptions (not mangled)
        expected_descriptions = [
            "HYDRO CARBON TREATMENT",
            "JASA AC LIGHT ADVANCE-05S",
            "NITROGEN - KURAS",
            "SPOORING B (INV,RSH,YRS,VIOS,LIMO,HLX)",
            "TIMAH BALANCE",
        ]
        for item, exp_desc in zip(items, expected_descriptions):
            self.assertEqual(item['description'], exp_desc,
                             msg=f"Item {item['line_no']} description mangled")

        # Verify correct harga_jual values (not 0)
        expected_values = [360500, 380000, 54000, 228000, 80000]
        for item, exp_val in zip(items, expected_values):
            self.assertAlmostEqual(item['harga_jual'], exp_val,
                                   msg=f"Item {item['line_no']} harga_jual wrong")

        # Step 4: Parse summary
        summary = parse_summary_section(summary_blocks, page_height=800)
        self.assertAlmostEqual(summary['harga_jual'], 1102500.0,
                               msg="Summary harga_jual wrong (should not be PPN)")
        self.assertAlmostEqual(summary['dpp'], 1010625.0,
                               msg="Summary DPP wrong (should not be item price)")
        self.assertAlmostEqual(summary['ppn'], 121275.0,
                               msg="Summary PPN wrong (should not be miscalculated)")

        # Step 5: Validate
        result = validate_parsed_data(items, summary, tax_rate=0.12)
        self.assertTrue(result['is_valid'],
                        f"Validation failed: {result['errors']}")
        self.assertTrue(result['checks']['items_sum_matches'],
                        "Items sum should match summary")
        self.assertTrue(result['checks']['ppn_calculation_ok'],
                        "PPN should be ~12% of DPP")

    def test_before_after_comparison(self):
        """
        Demonstrate the BEFORE (broken) vs AFTER (fixed) output.

        BEFORE (broken):
            items: 6 mangled items with wrong descriptions and zero values
            summary: harga_jual=121275 (is PPN!), dpp=80000 (is item price!)

        AFTER (fixed):
            items: 5 clean items with correct descriptions and values
            summary: harga_jual=1102500, dpp=1010625, ppn=121275
        """
        item_blocks = build_5_item_invoice_blocks()
        summary_blocks = build_summary_blocks(y_start=600)

        # Parse with fixes
        groups = group_multirow_items(item_blocks)
        items = [parse_grouped_item(g) for g in groups]
        summary = parse_summary_section(summary_blocks, page_height=800)

        # Should have exactly 5 items (not 6 or more)
        self.assertEqual(len(items), 5, "Should have 5 items, not 6 mangled items")

        # harga_jual should be 1,102,500 not 121,275
        self.assertAlmostEqual(summary['harga_jual'], 1102500.0)
        self.assertNotAlmostEqual(summary['harga_jual'], 121275.0,
                                  msg="harga_jual must NOT be PPN value")

        # DPP should be 1,010,625 not 80,000
        self.assertAlmostEqual(summary['dpp'], 1010625.0)
        self.assertNotAlmostEqual(summary['dpp'], 80000.0,
                                  msg="DPP must NOT be last item's price")

        # PPN should be 121,275 not 9,600
        self.assertAlmostEqual(summary['ppn'], 121275.0)
        self.assertNotAlmostEqual(summary['ppn'], 9600.0,
                                  msg="PPN must NOT be miscalculated")

        # No items should have zero harga_jual
        for item in items:
            self.assertGreater(item['harga_jual'], 0,
                               msg=f"Item {item['line_no']} has zero harga_jual!")

        # Items should sum to summary
        items_sum = sum(i['harga_jual'] for i in items)
        self.assertAlmostEqual(items_sum, summary['harga_jual'])


# =============================================================================
# Test 8: Usage Example
# =============================================================================

class TestUsageExample(unittest.TestCase):
    """Demonstrates how to use the fixed parser — doubles as a usage example."""

    def test_usage_example(self):
        """
        Usage Example: Parse a 5-item invoice end-to-end.

        This shows the complete workflow for parsing a multi-item
        Indonesian tax invoice using the fixed parser.
        """
        # 1. Simulate OCR text blocks (from Google Vision API)
        text_blocks = [
            # Item 1
            {'text': '1 000000', 'x': 50, 'y': 100},
            {'text': 'HYDRO CARBON TREATMENT', 'x': 50, 'y': 112},
            {'text': 'Rp 360.500,00 x 1,00 Lainnya', 'x': 50, 'y': 124},
            {'text': 'Potongan Harga = Rp 0,00', 'x': 50, 'y': 136},
            {'text': 'PPnBM (0,00%) = Rp 0,00', 'x': 50, 'y': 148},
            {'text': '360.500,00', 'x': 450, 'y': 160},
            # Item 2
            {'text': '2 000000', 'x': 50, 'y': 180},
            {'text': 'JASA AC LIGHT ADVANCE-05S', 'x': 50, 'y': 192},
            {'text': 'Rp 380.000,00 x 1,00 Lainnya', 'x': 50, 'y': 204},
            {'text': 'Potongan Harga = Rp 0,00', 'x': 50, 'y': 216},
            {'text': 'PPnBM (0,00%) = Rp 0,00', 'x': 50, 'y': 228},
            {'text': '380.000,00', 'x': 450, 'y': 240},
            # Summary (at the bottom)
            {'text': 'Harga Jual / Penggantian / Uang Muka / Termin', 'x': 50, 'y': 600},
            {'text': '740.500,00', 'x': 450, 'y': 600},
            {'text': 'Dasar Pengenaan Pajak', 'x': 50, 'y': 650},
            {'text': '678.792,00', 'x': 450, 'y': 650},
            {'text': 'Jumlah PPN (Pajak Pertambahan Nilai)', 'x': 50, 'y': 675},
            {'text': '81.455,00', 'x': 450, 'y': 675},
        ]

        # 2. Separate item blocks from summary by Y position
        item_blocks = [b for b in text_blocks if b.get('y', 0) < 500]
        summary_only = [b for b in text_blocks if b.get('y', 0) >= 500]

        # 3. Group multi-row items
        groups = group_multirow_items(item_blocks)
        self.assertEqual(len(groups), 2)

        # 4. Parse each item
        items = [parse_grouped_item(g) for g in groups]
        self.assertEqual(items[0]['description'], 'HYDRO CARBON TREATMENT')
        self.assertAlmostEqual(items[0]['harga_jual'], 360500.0)
        self.assertEqual(items[1]['description'], 'JASA AC LIGHT ADVANCE-05S')
        self.assertAlmostEqual(items[1]['harga_jual'], 380000.0)

        # 5. Parse summary
        summary = parse_summary_section(summary_only, page_height=800)
        self.assertAlmostEqual(summary['harga_jual'], 740500.0)
        self.assertAlmostEqual(summary['dpp'], 678792.0)
        self.assertAlmostEqual(summary['ppn'], 81455.0)

        # 6. Validate
        validation = validate_parsed_data(items, summary, tax_rate=0.12)
        self.assertTrue(validation['is_valid'],
                        f"Validation errors: {validation['errors']}")


if __name__ == "__main__":
    unittest.main()
