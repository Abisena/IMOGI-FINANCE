# -*- coding: utf-8 -*-
"""
Comprehensive tests for the multirow parser integration pipeline.

Tests 3 critical bug fixes + integration:
    Fix #1: Summary section regex parser (parse_summary_section)
    Fix #2: Multi-row item grouping (group_multirow_items, parse_grouped_item)
    Fix #3: Validation (validate_parsed_data)
    Integration: Vision JSON → text blocks → full pipeline

Test Invoice: 04002500436451666
    5 items (HYDRO CARBON, AC LIGHT, NITROGEN, SPOORING, TIMAH)
    Harga Jual: 1,102,500
    DPP: 1,010,625
    PPN: 121,275

Run standalone::

    python -m pytest tests/test_multirow_integration.py -v
    # or
    python tests/test_multirow_integration.py

"""

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
    parse_tax_invoice_multirow,
    validate_parsed_data,
    vision_json_to_text_blocks,
    tokens_to_text_blocks,
    _resolve_full_text_annotation,
)


# =============================================================================
# Test Data Builders
# =============================================================================

def build_5_item_invoice_blocks() -> List[Dict]:
    """
    Build text blocks for the 5-item test invoice (04002500436451666).

    Each item spans 6 rows in OCR output.
    """
    items_data = [
        (1, "HYDRO CARBON TREATMENT", "360.500,00", 1),
        (2, "JASA AC LIGHT ADVANCE-05S", "380.000,00", 1),
        (3, "NITROGEN - KURAS", "54.000,00", 1),
        (4, "SPOORING B (INV,RSH,YRS,VIOS,LIMO,HLX)", "228.000,00", 1),
        (5, "TIMAH BALANCE", "80.000,00", 1),
    ]

    blocks = []
    y = 100
    for line_no, desc, price, qty in items_data:
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


def build_full_invoice_blocks() -> List[Dict]:
    """
    Build complete invoice blocks: items + summary section.
    """
    blocks = build_5_item_invoice_blocks()
    y_after_items = max(b['y'] for b in blocks) + 30

    # Summary section (bottom of page)
    summary_blocks = [
        {'text': 'Harga Jual / Penggantian / Uang Muka / Termin', 'x': 50, 'y': y_after_items},
        {'text': '1.102.500,00', 'x': 450, 'y': y_after_items},
        {'text': 'Dikurangi Potongan Harga', 'x': 50, 'y': y_after_items + 20},
        {'text': '0,00', 'x': 450, 'y': y_after_items + 20},
        {'text': 'Dikurangi Uang Muka yang telah diterima', 'x': 50, 'y': y_after_items + 40},
        {'text': '0,00', 'x': 450, 'y': y_after_items + 40},
        {'text': 'Dasar Pengenaan Pajak', 'x': 50, 'y': y_after_items + 60},
        {'text': '1.010.625,00', 'x': 450, 'y': y_after_items + 60},
        {'text': 'Jumlah PPN (Pajak Pertambahan Nilai)', 'x': 50, 'y': y_after_items + 80},
        {'text': '121.275,00', 'x': 450, 'y': y_after_items + 80},
        {'text': 'Jumlah PPnBM (Pajak Penjualan atas Barang Mewah)', 'x': 50, 'y': y_after_items + 100},
        {'text': '0,00', 'x': 450, 'y': y_after_items + 100},
    ]
    blocks.extend(summary_blocks)
    return blocks


def build_mock_vision_json() -> Dict:
    """
    Build a mock Google Vision API JSON response that represents the
    5-item test invoice with summary section.

    This simulates word-level Vision OCR output.
    """
    def make_word(text: str, x: float, y: float, w: float = None, h: float = 15):
        if w is None:
            w = len(text) * 8  # rough char width
        return {
            'symbols': [{'text': c} for c in text],
            'boundingBox': {
                'vertices': [
                    {'x': int(x), 'y': int(y)},
                    {'x': int(x + w), 'y': int(y)},
                    {'x': int(x + w), 'y': int(y + h)},
                    {'x': int(x), 'y': int(y + h)},
                ]
            },
            'confidence': 0.98,
        }

    paragraphs = []
    y = 100

    # 5 items, each spanning 6 rows
    items = [
        (1, "HYDRO CARBON TREATMENT", "360.500,00", "1,00"),
        (2, "JASA AC LIGHT ADVANCE-05S", "380.000,00", "1,00"),
        (3, "NITROGEN - KURAS", "54.000,00", "1,00"),
        (4, "SPOORING B (INV,RSH,YRS,VIOS,LIMO,HLX)", "228.000,00", "1,00"),
        (5, "TIMAH BALANCE", "80.000,00", "1,00"),
    ]

    for line_no, desc, price, qty in items:
        # Row 1: "N 000000"
        words = [
            make_word(str(line_no), 50, y),
            make_word("000000", 70, y),
        ]
        paragraphs.append({'words': words})
        y += 18

        # Row 2: description (split into words)
        desc_words = desc.split()
        x = 50
        row_words = []
        for dw in desc_words:
            row_words.append(make_word(dw, x, y))
            x += len(dw) * 8 + 5
        paragraphs.append({'words': row_words})
        y += 18

        # Row 3: "Rp X x N,NN Lainnya"
        words = [
            make_word("Rp", 50, y),
            make_word(price, 75, y),
            make_word("x", 175, y),
            make_word(qty, 190, y),
            make_word("Lainnya", 230, y),
        ]
        paragraphs.append({'words': words})
        y += 18

        # Row 4: "Potongan Harga = Rp 0,00"
        words = [
            make_word("Potongan", 50, y),
            make_word("Harga", 120, y),
            make_word("=", 165, y),
            make_word("Rp", 180, y),
            make_word("0,00", 200, y),
        ]
        paragraphs.append({'words': words})
        y += 18

        # Row 5: "PPnBM (0,00%) = Rp 0,00"
        words = [
            make_word("PPnBM", 50, y),
            make_word("(0,00%)", 105, y),
            make_word("=", 175, y),
            make_word("Rp", 190, y),
            make_word("0,00", 210, y),
        ]
        paragraphs.append({'words': words})
        y += 18

        # Row 6: value in harga_jual column (right side)
        words = [make_word(price, 450, y, w=80)]
        paragraphs.append({'words': words})
        y += 25  # gap between items

    # Summary section
    y += 30  # gap before summary

    # Harga Jual label + value
    words = [
        make_word("Harga", 50, y),
        make_word("Jual", 95, y),
        make_word("/", 130, y),
        make_word("Penggantian", 140, y),
        make_word("/", 230, y),
        make_word("Uang", 240, y),
        make_word("Muka", 280, y),
        make_word("/", 315, y),
        make_word("Termin", 325, y),
    ]
    paragraphs.append({'words': words})
    words = [make_word("1.102.500,00", 450, y, w=90)]
    paragraphs.append({'words': words})
    y += 25

    # Dikurangi Potongan Harga
    words = [
        make_word("Dikurangi", 50, y),
        make_word("Potongan", 125, y),
        make_word("Harga", 200, y),
    ]
    paragraphs.append({'words': words})
    words = [make_word("0,00", 450, y, w=40)]
    paragraphs.append({'words': words})
    y += 25

    # Dasar Pengenaan Pajak
    words = [
        make_word("Dasar", 50, y),
        make_word("Pengenaan", 100, y),
        make_word("Pajak", 185, y),
    ]
    paragraphs.append({'words': words})
    words = [make_word("1.010.625,00", 450, y, w=90)]
    paragraphs.append({'words': words})
    y += 25

    # Jumlah PPN
    words = [
        make_word("Jumlah", 50, y),
        make_word("PPN", 110, y),
        make_word("(Pajak", 145, y),
        make_word("Pertambahan", 190, y),
        make_word("Nilai)", 275, y),
    ]
    paragraphs.append({'words': words})
    words = [make_word("121.275,00", 450, y, w=80)]
    paragraphs.append({'words': words})
    y += 25

    # Jumlah PPnBM
    words = [
        make_word("Jumlah", 50, y),
        make_word("PPnBM", 110, y),
        make_word("(Pajak", 170, y),
        make_word("Penjualan", 215, y),
        make_word("atas", 290, y),
        make_word("Barang", 315, y),
        make_word("Mewah)", 365, y),
    ]
    paragraphs.append({'words': words})
    words = [make_word("0,00", 450, y, w=40)]
    paragraphs.append({'words': words})

    return {
        'fullTextAnnotation': {
            'pages': [{
                'width': 595,
                'height': max(y + 50, 842),
                'blocks': [{
                    'paragraphs': paragraphs,
                }],
            }],
            'text': '',  # not needed for this test
        }
    }


# =============================================================================
# Fix #1: Indonesian Number Parser
# =============================================================================

class TestParseIndonesianNumber(unittest.TestCase):
    """Test Indonesian number format parsing."""

    def test_standard_format(self):
        self.assertEqual(parse_indonesian_number("1.102.500,00"), 1102500.0)

    def test_no_decimal(self):
        self.assertEqual(parse_indonesian_number("360.500"), 360500.0)

    def test_with_decimal(self):
        self.assertEqual(parse_indonesian_number("121.275,00"), 121275.0)

    def test_zero(self):
        self.assertEqual(parse_indonesian_number("0,00"), 0.0)

    def test_with_rp_prefix(self):
        self.assertEqual(parse_indonesian_number("Rp 360.500,00"), 360500.0)

    def test_empty(self):
        self.assertEqual(parse_indonesian_number(""), 0.0)

    def test_none(self):
        self.assertEqual(parse_indonesian_number(None), 0.0)

    def test_large_number(self):
        self.assertEqual(parse_indonesian_number("4.953.154,00"), 4953154.0)

    def test_small_number(self):
        self.assertEqual(parse_indonesian_number("500,00"), 500.0)


# =============================================================================
# Fix #1: Summary Section Parser
# =============================================================================

class TestParseSummarySection(unittest.TestCase):
    """Test summary section parsing with coordinate-based + regex fallback."""

    def test_separate_label_value_blocks(self):
        """Summary with label and value as separate text blocks."""
        blocks = [
            {'text': 'Harga Jual / Penggantian / Uang Muka / Termin', 'x': 50, 'y': 600},
            {'text': '1.102.500,00', 'x': 450, 'y': 600},
            {'text': 'Dasar Pengenaan Pajak', 'x': 50, 'y': 650},
            {'text': '1.010.625,00', 'x': 450, 'y': 650},
            {'text': 'Jumlah PPN (Pajak Pertambahan Nilai)', 'x': 50, 'y': 670},
            {'text': '121.275,00', 'x': 450, 'y': 670},
        ]
        result = parse_summary_section(blocks, page_height=800)

        self.assertEqual(result['harga_jual'], 1102500.0)
        self.assertEqual(result['dpp'], 1010625.0)
        self.assertEqual(result['ppn'], 121275.0)

    def test_inline_label_value(self):
        """Summary with label and value on the same text block."""
        blocks = [
            {'text': 'Harga Jual / Penggantian / Uang Muka / Termin 1.102.500,00', 'x': 50, 'y': 600},
            {'text': 'Dasar Pengenaan Pajak 1.010.625,00', 'x': 50, 'y': 650},
            {'text': 'Jumlah PPN (Pajak Pertambahan Nilai) 121.275,00', 'x': 50, 'y': 670},
        ]
        result = parse_summary_section(blocks, page_height=800)

        self.assertEqual(result['harga_jual'], 1102500.0)
        self.assertEqual(result['dpp'], 1010625.0)
        self.assertEqual(result['ppn'], 121275.0)

    def test_not_confused_with_item_values(self):
        """
        CRITICAL: Summary parser must NOT read item values as summary.

        Previous bug: parser read PPN value (121,275) as harga_jual,
        and last item price (80,000) as DPP.
        """
        result = parse_summary_section(build_full_invoice_blocks(), page_height=800)

        # These are the CORRECT values
        self.assertEqual(result['harga_jual'], 1102500.0, "harga_jual must be 1,102,500 NOT 121,275")
        self.assertEqual(result['dpp'], 1010625.0, "DPP must be 1,010,625 NOT 80,000")
        self.assertEqual(result['ppn'], 121275.0, "PPN must be 121,275 NOT 9,600")

    def test_full_summary_with_all_fields(self):
        """Parse all 6 summary fields."""
        blocks = [
            {'text': 'Harga Jual / Penggantian / Uang Muka / Termin', 'x': 50, 'y': 600},
            {'text': '1.102.500,00', 'x': 450, 'y': 600},
            {'text': 'Dikurangi Potongan Harga', 'x': 50, 'y': 620},
            {'text': '0,00', 'x': 450, 'y': 620},
            {'text': 'Dikurangi Uang Muka yang telah diterima', 'x': 50, 'y': 640},
            {'text': '0,00', 'x': 450, 'y': 640},
            {'text': 'Dasar Pengenaan Pajak', 'x': 50, 'y': 660},
            {'text': '1.010.625,00', 'x': 450, 'y': 660},
            {'text': 'Jumlah PPN (Pajak Pertambahan Nilai)', 'x': 50, 'y': 680},
            {'text': '121.275,00', 'x': 450, 'y': 680},
            {'text': 'Jumlah PPnBM (Pajak Penjualan atas Barang Mewah)', 'x': 50, 'y': 700},
            {'text': '0,00', 'x': 450, 'y': 700},
        ]
        result = parse_summary_section(blocks, page_height=800)

        self.assertEqual(result['harga_jual'], 1102500.0)
        self.assertEqual(result['potongan'], 0.0)
        self.assertEqual(result['uang_muka'], 0.0)
        self.assertEqual(result['dpp'], 1010625.0)
        self.assertEqual(result['ppn'], 121275.0)
        self.assertEqual(result['ppnbm'], 0.0)

    def test_empty_blocks(self):
        """Gracefully handle empty input."""
        result = parse_summary_section([], page_height=800)
        self.assertEqual(result['harga_jual'], 0.0)
        self.assertEqual(result['dpp'], 0.0)
        self.assertEqual(result['ppn'], 0.0)


class TestParseSummaryFromFullText(unittest.TestCase):
    """Test summary parsing from plain text (no coordinates)."""

    def test_full_text_extraction(self):
        text = """
Harga Jual / Penggantian / Uang Muka / Termin    1.102.500,00
Dikurangi Potongan Harga                                 0,00
Dikurangi Uang Muka yang telah diterima                  0,00
Dasar Pengenaan Pajak                            1.010.625,00
Jumlah PPN (Pajak Pertambahan Nilai)               121.275,00
Jumlah PPnBM (Pajak Penjualan atas Barang Mewah)        0,00
"""
        result = parse_summary_from_full_text(text)

        self.assertEqual(result['harga_jual'], 1102500.0)
        self.assertEqual(result['dpp'], 1010625.0)
        self.assertEqual(result['ppn'], 121275.0)


# =============================================================================
# Fix #2: Multi-Row Item Grouping
# =============================================================================

class TestGroupMultirowItems(unittest.TestCase):
    """Test multi-row text block grouping."""

    def test_5_items_grouped_correctly(self):
        """CRITICAL: Must produce 5 groups, not 6."""
        blocks = build_5_item_invoice_blocks()
        groups = group_multirow_items(blocks)

        self.assertEqual(len(groups), 5, "Must be 5 items, not 6!")

    def test_line_numbers_sequential(self):
        blocks = build_5_item_invoice_blocks()
        groups = group_multirow_items(blocks)

        for i, group in enumerate(groups, 1):
            self.assertEqual(group['line_no'], i)

    def test_each_group_has_rows(self):
        blocks = build_5_item_invoice_blocks()
        groups = group_multirow_items(blocks)

        for group in groups:
            self.assertGreater(len(group['rows']), 0)
            self.assertIn('y_start', group)
            self.assertIn('y_end', group)

    def test_stops_at_summary_section(self):
        """Groups should not include summary rows."""
        blocks = build_full_invoice_blocks()
        groups = group_multirow_items(blocks)

        self.assertEqual(len(groups), 5, "Must stop at summary section")

    def test_empty_input(self):
        self.assertEqual(group_multirow_items([]), [])

    def test_two_items_partial(self):
        """Test with 2 items to verify grouping boundaries."""
        blocks = [
            {'text': '1 000000', 'x': 50, 'y': 100},
            {'text': 'HYDRO CARBON TREATMENT', 'x': 50, 'y': 112},
            {'text': 'Rp 360.500,00 x 1,00 Lainnya', 'x': 50, 'y': 124},
            {'text': 'Potongan Harga = Rp 0,00', 'x': 50, 'y': 136},
            {'text': 'PPnBM (0,00%) = Rp 0,00', 'x': 50, 'y': 148},
            {'text': '360.500,00', 'x': 450, 'y': 160},
            {'text': '2 000000', 'x': 50, 'y': 180},
            {'text': 'JASA AC LIGHT ADVANCE-05S', 'x': 50, 'y': 192},
            {'text': 'Rp 380.000,00 x 1,00 Lainnya', 'x': 50, 'y': 204},
            {'text': 'Potongan Harga = Rp 0,00', 'x': 50, 'y': 216},
            {'text': 'PPnBM (0,00%) = Rp 0,00', 'x': 50, 'y': 228},
            {'text': '380.000,00', 'x': 450, 'y': 240},
        ]
        groups = group_multirow_items(blocks)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]['line_no'], 1)
        self.assertEqual(groups[1]['line_no'], 2)


class TestParseGroupedItem(unittest.TestCase):
    """Test extracting structured data from grouped item rows."""

    def _make_group(self, line_no, desc, price_str, qty=1):
        """Helper to build a single item group."""
        return {
            'line_no': line_no,
            'rows': [
                {'text': f'{line_no} 000000', 'x': 50, 'y': 100},
                {'text': desc, 'x': 50, 'y': 112},
                {'text': f'Rp {price_str} x {qty},00 Lainnya', 'x': 50, 'y': 124},
                {'text': 'Potongan Harga = Rp 0,00', 'x': 50, 'y': 136},
                {'text': 'PPnBM (0,00%) = Rp 0,00', 'x': 50, 'y': 148},
                {'text': price_str, 'x': 450, 'y': 160},
            ],
            'y_start': 100,
            'y_end': 160,
        }

    def test_item1_hydro_carbon(self):
        """CRITICAL: Description must be clean, not mangled."""
        group = self._make_group(1, 'HYDRO CARBON TREATMENT', '360.500,00')
        item = parse_grouped_item(group)

        self.assertEqual(item['line_no'], 1)
        self.assertEqual(item['description'], 'HYDRO CARBON TREATMENT')
        self.assertEqual(item['harga_jual'], 360500.0)
        self.assertEqual(item['unit_price'], 360500.0)
        self.assertEqual(item['qty'], 1.0)

    def test_item2_ac_light(self):
        group = self._make_group(2, 'JASA AC LIGHT ADVANCE-05S', '380.000,00')
        item = parse_grouped_item(group)

        self.assertEqual(item['line_no'], 2)
        self.assertEqual(item['description'], 'JASA AC LIGHT ADVANCE-05S')
        self.assertEqual(item['harga_jual'], 380000.0)

    def test_item3_nitrogen(self):
        group = self._make_group(3, 'NITROGEN - KURAS', '54.000,00')
        item = parse_grouped_item(group)

        self.assertEqual(item['description'], 'NITROGEN - KURAS')
        self.assertEqual(item['harga_jual'], 54000.0)

    def test_item4_spooring(self):
        group = self._make_group(
            4, 'SPOORING B (INV,RSH,YRS,VIOS,LIMO,HLX)', '228.000,00'
        )
        item = parse_grouped_item(group)

        self.assertEqual(item['description'], 'SPOORING B (INV,RSH,YRS,VIOS,LIMO,HLX)')
        self.assertEqual(item['harga_jual'], 228000.0)

    def test_item5_timah(self):
        group = self._make_group(5, 'TIMAH BALANCE', '80.000,00')
        item = parse_grouped_item(group)

        self.assertEqual(item['description'], 'TIMAH BALANCE')
        self.assertEqual(item['harga_jual'], 80000.0)

    def test_description_not_mangled(self):
        """CRITICAL: Description must NOT contain item numbers or discount text."""
        group = self._make_group(1, 'HYDRO CARBON TREATMENT', '360.500,00')
        item = parse_grouped_item(group)

        self.assertNotIn('000000', item['description'])
        self.assertNotIn('Potongan', item['description'])
        self.assertNotIn('PPnBM', item['description'])

    def test_empty_group(self):
        result = parse_grouped_item({'line_no': 1, 'rows': []})
        self.assertEqual(result['description'], '')
        self.assertEqual(result['harga_jual'], 0.0)

    def test_all_5_items_parsed_correctly(self):
        """End-to-end: group + parse all 5 items."""
        blocks = build_5_item_invoice_blocks()
        groups = group_multirow_items(blocks)
        items = [parse_grouped_item(g) for g in groups]

        self.assertEqual(len(items), 5)

        expected = [
            (1, 'HYDRO CARBON TREATMENT', 360500.0),
            (2, 'JASA AC LIGHT ADVANCE-05S', 380000.0),
            (3, 'NITROGEN - KURAS', 54000.0),
            (4, 'SPOORING B (INV,RSH,YRS,VIOS,LIMO,HLX)', 228000.0),
            (5, 'TIMAH BALANCE', 80000.0),
        ]

        for item, (exp_no, exp_desc, exp_hj) in zip(items, expected):
            self.assertEqual(item['line_no'], exp_no)
            self.assertEqual(item['description'], exp_desc)
            self.assertEqual(item['harga_jual'], exp_hj)

    def test_items_sum_correct(self):
        """Sum of all item harga_jual must equal 1,102,500."""
        blocks = build_5_item_invoice_blocks()
        groups = group_multirow_items(blocks)
        items = [parse_grouped_item(g) for g in groups]

        total = sum(item['harga_jual'] for item in items)
        self.assertEqual(total, 1102500.0)


# =============================================================================
# Fix #2: Smart Filter (is_summary_row)
# =============================================================================

class TestIsSummaryRow(unittest.TestCase):
    """Test the smart filter that distinguishes items from summary rows."""

    def test_summary_labels_filtered(self):
        self.assertTrue(is_summary_row("Harga Jual / Penggantian / Uang Muka / Termin"))
        self.assertTrue(is_summary_row("Dasar Pengenaan Pajak"))
        self.assertTrue(is_summary_row("Jumlah PPN (Pajak Pertambahan Nilai)"))
        self.assertTrue(is_summary_row("Dikurangi Potongan Harga"))

    def test_item_number_never_filtered(self):
        self.assertFalse(is_summary_row("1 000000"))
        self.assertFalse(is_summary_row("2 000000"))
        self.assertFalse(is_summary_row("10 000000"))

    def test_item_detail_rows_not_filtered(self):
        self.assertFalse(is_summary_row("Rp 360.500,00 x 1,00 Lainnya"))
        self.assertFalse(is_summary_row("Potongan Harga = Rp 0,00"))
        self.assertFalse(is_summary_row("PPnBM (0,00%) = Rp 0,00"))
        self.assertFalse(is_summary_row("360.500,00"))

    def test_descriptions_not_filtered(self):
        self.assertFalse(is_summary_row("HYDRO CARBON TREATMENT"))
        self.assertFalse(is_summary_row("JASA AC LIGHT ADVANCE-05S"))
        self.assertFalse(is_summary_row("TIMAH BALANCE"))


# =============================================================================
# Fix #3: Validation
# =============================================================================

class TestValidateParsedData(unittest.TestCase):
    """Test cross-validation of parsed items against summary."""

    def test_correct_data_validates(self):
        """Valid data should pass all checks."""
        items = [
            {'harga_jual': 360500},
            {'harga_jual': 380000},
            {'harga_jual': 54000},
            {'harga_jual': 228000},
            {'harga_jual': 80000},
        ]
        summary = {
            'harga_jual': 1102500,
            'dpp': 1010625,
            'ppn': 121275,
        }

        result = validate_parsed_data(items, summary, tax_rate=0.12)

        self.assertTrue(result['is_valid'])
        self.assertTrue(result['checks']['items_sum_matches'])
        self.assertTrue(result['checks']['ppn_calculation_ok'])
        self.assertTrue(result['checks']['items_count_ok'])
        self.assertTrue(result['checks']['no_zero_values'])
        self.assertEqual(len(result['errors']), 0)

    def test_broken_summary_detected(self):
        """Current broken parsing should fail validation."""
        items = [
            {'harga_jual': 360500},
            {'harga_jual': 380000},
            {'harga_jual': 54000},
            {'harga_jual': 228000},
            {'harga_jual': 80000},
        ]
        summary_broken = {
            'harga_jual': 121275,  # WRONG (this is PPN)
            'dpp': 80000,          # WRONG (this is last item price)
            'ppn': 9600,           # WRONG (calculated from wrong DPP)
        }

        result = validate_parsed_data(items, summary_broken, tax_rate=0.12)

        self.assertFalse(result['is_valid'])
        self.assertFalse(result['checks']['items_sum_matches'])
        self.assertGreater(len(result['errors']), 0)

    def test_zero_items_are_warning_not_error(self):
        """Zero harga_jual items should be warnings, not fatal errors."""
        items = [
            {'harga_jual': 0},
            {'harga_jual': 360500},
        ]
        summary = {
            'harga_jual': 360500,
            'dpp': 330825,
            'ppn': 39699,
        }

        result = validate_parsed_data(items, summary, tax_rate=0.12)

        # Zero items should NOT make is_valid=False by themselves
        # (only if there are actual errors like sum mismatch)
        self.assertFalse(result['checks']['no_zero_values'])
        # Check that zero items appear in warnings
        has_zero_warning = any('zero' in w.lower() for w in result['warnings'])
        self.assertTrue(has_zero_warning, "Zero items should be in warnings")

    def test_no_items_is_error(self):
        result = validate_parsed_data([], {'harga_jual': 100})
        self.assertFalse(result['is_valid'])
        self.assertFalse(result['checks']['items_count_ok'])

    def test_ppn_rate_mismatch_detected(self):
        """PPN that doesn't match DPP × rate should trigger warning."""
        items = [{'harga_jual': 100000}]
        summary = {
            'harga_jual': 100000,
            'dpp': 91667,
            'ppn': 5000,   # Should be ~11,000 at 12%
        }

        result = validate_parsed_data(items, summary, tax_rate=0.12)
        # PPN mismatch should produce a warning
        self.assertFalse(result['checks']['ppn_calculation_ok'])

    def test_tolerance_allows_rounding(self):
        """Small rounding differences should still pass."""
        items = [{'harga_jual': 1102500}]
        summary = {
            'harga_jual': 1102500,
            'dpp': 1010625,
            'ppn': 121275,  # 1010625 × 0.12 = 121275 exactly
        }

        result = validate_parsed_data(items, summary, tax_rate=0.12)
        self.assertTrue(result['is_valid'])


# =============================================================================
# Vision JSON Conversion
# =============================================================================

class TestVisionJsonToTextBlocks(unittest.TestCase):
    """Test Vision JSON → text blocks conversion."""

    def test_basic_conversion(self):
        """Mock Vision JSON should produce text blocks."""
        vj = build_mock_vision_json()
        blocks, page_height = vision_json_to_text_blocks(vj)

        self.assertGreater(len(blocks), 0)
        self.assertGreater(page_height, 0)

    def test_blocks_have_required_keys(self):
        vj = build_mock_vision_json()
        blocks, _ = vision_json_to_text_blocks(vj)

        for block in blocks:
            self.assertIn('text', block)
            self.assertIn('x', block)
            self.assertIn('y', block)

    def test_item_number_reconstructed(self):
        """Vision words '1' + '000000' should merge into '1 000000'."""
        vj = build_mock_vision_json()
        blocks, _ = vision_json_to_text_blocks(vj)

        # Find blocks that contain item number patterns
        import re
        item_pattern = re.compile(r'^\d+\s+\d{6}')
        item_blocks = [b for b in blocks if item_pattern.match(b['text'])]

        self.assertGreaterEqual(
            len(item_blocks), 1,
            "Should have at least one '1 000000'-style block"
        )

    def test_empty_vision_json(self):
        blocks, height = vision_json_to_text_blocks({})
        self.assertEqual(blocks, [])

    def test_nested_responses(self):
        """Handle double-nested responses format."""
        inner = build_mock_vision_json()
        nested = {'responses': [{'responses': [inner]}]}
        blocks, _ = vision_json_to_text_blocks(nested)
        self.assertGreater(len(blocks), 0)

    def test_single_nested_responses(self):
        """Handle single-nested responses format."""
        inner = build_mock_vision_json()
        fta = inner['fullTextAnnotation']
        nested = {'responses': [{'fullTextAnnotation': fta}]}
        blocks, _ = vision_json_to_text_blocks(nested)
        self.assertGreater(len(blocks), 0)


class TestResolveFullTextAnnotation(unittest.TestCase):
    """Test Vision JSON unwrapping logic."""

    def test_direct(self):
        fta = {'pages': []}
        result = _resolve_full_text_annotation({'fullTextAnnotation': fta})
        self.assertEqual(result, fta)

    def test_single_nested(self):
        fta = {'pages': []}
        result = _resolve_full_text_annotation(
            {'responses': [{'fullTextAnnotation': fta}]}
        )
        self.assertEqual(result, fta)

    def test_double_nested(self):
        fta = {'pages': []}
        result = _resolve_full_text_annotation(
            {'responses': [{'responses': [{'fullTextAnnotation': fta}]}]}
        )
        self.assertEqual(result, fta)

    def test_none_input(self):
        self.assertIsNone(_resolve_full_text_annotation(None))

    def test_empty_dict(self):
        self.assertIsNone(_resolve_full_text_annotation({}))


# =============================================================================
# Full Integration Pipeline
# =============================================================================

class TestParseTaxInvoiceMultirow(unittest.TestCase):
    """Test the complete multirow parsing pipeline."""

    def test_full_pipeline_from_text_blocks(self):
        """End-to-end: text blocks → items + summary + validation."""
        blocks = build_full_invoice_blocks()
        page_height = max(b['y'] for b in blocks) + 50

        result = parse_tax_invoice_multirow(
            text_blocks=blocks,
            page_height=page_height,
            tax_rate=0.12,
        )

        self.assertTrue(result['success'])

        # Check items
        items = result['items']
        self.assertEqual(len(items), 5, "Must be exactly 5 items")

        expected_items = [
            ('HYDRO CARBON TREATMENT', 360500.0),
            ('JASA AC LIGHT ADVANCE-05S', 380000.0),
            ('NITROGEN - KURAS', 54000.0),
            ('SPOORING B (INV,RSH,YRS,VIOS,LIMO,HLX)', 228000.0),
            ('TIMAH BALANCE', 80000.0),
        ]

        for item, (exp_desc, exp_hj) in zip(items, expected_items):
            self.assertEqual(item['description'], exp_desc)
            self.assertEqual(item['harga_jual'], exp_hj)

        # Check summary
        summary = result['summary']
        self.assertEqual(summary['harga_jual'], 1102500.0)
        self.assertEqual(summary['dpp'], 1010625.0)
        self.assertEqual(summary['ppn'], 121275.0)

        # Check validation
        validation = result['validation']
        self.assertTrue(validation['is_valid'])
        self.assertTrue(validation['checks']['items_sum_matches'])
        self.assertTrue(validation['checks']['ppn_calculation_ok'])

    def test_full_pipeline_from_vision_json(self):
        """End-to-end: Vision JSON → text blocks → items + summary."""
        vj = build_mock_vision_json()

        result = parse_tax_invoice_multirow(
            vision_json=vj,
            tax_rate=0.12,
        )

        self.assertTrue(result['success'])

        # Items should be parsed (exact count may vary based on OCR grouping)
        items = result['items']
        self.assertGreaterEqual(len(items), 1, "Should parse at least 1 item")

        # Summary should extract DPP/PPN
        summary = result['summary']
        self.assertGreater(summary.get('dpp', 0), 0, "DPP should be extracted")
        self.assertGreater(summary.get('ppn', 0), 0, "PPN should be extracted")

    def test_no_input_returns_error(self):
        result = parse_tax_invoice_multirow()
        self.assertFalse(result['success'])
        self.assertGreater(len(result['errors']), 0)

    def test_empty_blocks_returns_error(self):
        result = parse_tax_invoice_multirow(text_blocks=[])
        self.assertFalse(result['success'])


# =============================================================================
# Regression Tests: Bug-Specific
# =============================================================================

class TestBugRegression(unittest.TestCase):
    """
    Regression tests for the 3 confirmed bugs.

    These tests verify that the specific error patterns described in the
    bug report no longer occur.
    """

    def test_bug1_summary_not_reading_ppn_as_harga_jual(self):
        """
        Bug #1: System reads PPN value (121,275) as Harga Jual.

        BEFORE: harga_jual=121275 (wrong), dpp=80000 (wrong), ppn=9600 (wrong)
        AFTER:  harga_jual=1102500, dpp=1010625, ppn=121275
        """
        blocks = build_full_invoice_blocks()
        page_height = max(b['y'] for b in blocks) + 50

        result = parse_tax_invoice_multirow(
            text_blocks=blocks,
            page_height=page_height,
        )

        summary = result['summary']
        self.assertNotEqual(summary['harga_jual'], 121275.0,
                            "harga_jual must NOT be 121,275 (that's PPN!)")
        self.assertEqual(summary['harga_jual'], 1102500.0)
        self.assertNotEqual(summary['dpp'], 80000.0,
                            "DPP must NOT be 80,000 (that's last item price!)")
        self.assertEqual(summary['dpp'], 1010625.0)
        self.assertEqual(summary['ppn'], 121275.0)

    def test_bug2_items_not_mangled(self):
        """
        Bug #2: Multi-row items produce mangled descriptions.

        BEFORE: 6 items with descriptions like "1 000000 Potongan Harga..."
        AFTER:  5 items with clean descriptions like "HYDRO CARBON TREATMENT"
        """
        blocks = build_5_item_invoice_blocks()
        groups = group_multirow_items(blocks)
        items = [parse_grouped_item(g) for g in groups]

        self.assertEqual(len(items), 5, "Must be 5 items, NOT 6")

        for item in items:
            self.assertNotIn('000000', item['description'],
                             f"Description contaminated: {item['description']}")
            self.assertNotIn('Potongan', item['description'],
                             f"Description contaminated: {item['description']}")

        self.assertEqual(items[0]['description'], 'HYDRO CARBON TREATMENT')
        self.assertEqual(items[0]['harga_jual'], 360500.0)

    def test_bug3_validation_catches_broken_data(self):
        """
        Bug #3: No validation exists to catch the mismatched values.

        BEFORE: Broken data (89% error) passes silently.
        AFTER:  Validation catches the mismatch.
        """
        items = [
            {'harga_jual': 0},        # Bug: extra item with zero
            {'harga_jual': 360500},
            {'harga_jual': 380000},
            {'harga_jual': 54000},
            {'harga_jual': 228000},
            {'harga_jual': 80000},
        ]
        summary_broken = {
            'harga_jual': 121275,
            'dpp': 80000,
            'ppn': 9600,
        }

        result = validate_parsed_data(items, summary_broken, tax_rate=0.12)

        self.assertFalse(result['is_valid'],
                         "Broken data MUST fail validation!")
        self.assertGreater(len(result['errors']), 0,
                           "Must report errors for 89% mismatch")

    def test_correct_data_passes_all_checks(self):
        """
        After all 3 fixes are applied, the full pipeline should produce
        valid, consistent results that pass all validation checks.
        """
        blocks = build_full_invoice_blocks()
        page_height = max(b['y'] for b in blocks) + 50

        result = parse_tax_invoice_multirow(
            text_blocks=blocks,
            page_height=page_height,
            tax_rate=0.12,
        )

        self.assertTrue(result['success'])
        self.assertTrue(result['validation']['is_valid'],
                        f"Should validate OK, errors: {result['validation'].get('errors')}")

        # Final success criteria
        items = result['items']
        summary = result['summary']
        validation = result['validation']

        self.assertEqual(len(items), 5)
        self.assertEqual(summary['harga_jual'], 1102500.0)
        self.assertEqual(summary['dpp'], 1010625.0)
        self.assertEqual(summary['ppn'], 121275.0)
        self.assertTrue(validation['checks']['items_sum_matches'])
        self.assertTrue(validation['checks']['ppn_calculation_ok'])
        self.assertTrue(validation['checks']['items_count_ok'])
        self.assertTrue(validation['checks']['no_zero_values'])


# =============================================================================
# Run
# =============================================================================

if __name__ == '__main__':
    unittest.main(verbosity=2)
