# -*- coding: utf-8 -*-
"""
Tests for LayoutAwareParser — coordinate-based OCR extraction.

Run with:
    python -m pytest test_layout_aware_parser.py -v
    # or inside a Frappe bench:
    bench run-tests --module imogi_finance.parsers.layout_aware_parser
"""

import sys
import os
import json
import unittest
from unittest.mock import MagicMock, patch
from typing import Dict, Any, List

# ---------------------------------------------------------------------------
# Mock frappe before importing the parser (allows running outside bench)
# ---------------------------------------------------------------------------
_frappe_mock = MagicMock()
_frappe_mock.logger.return_value = MagicMock()
_frappe_mock._ = lambda s: s
sys.modules.setdefault("frappe", _frappe_mock)
sys.modules.setdefault("frappe.utils", MagicMock())

# Add project root so imports work
_project_root = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "imogi_finance")
)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from imogi_finance.parsers.layout_aware_parser import (
    BoundingBox,
    OCRToken,
    LayoutAwareParser,
    validate_summary_amounts,
    process_with_layout_parser,
    SUMMARY_LABEL_PATTERNS,
)


# =============================================================================
# HELPERS — build synthetic Google Vision JSON
# =============================================================================

def _make_word(text: str, x_min: float, y_min: float, x_max: float, y_max: float, conf: float = 0.98) -> Dict:
    """Create a Vision API-format word with normalizedVertices."""
    return {
        "symbols": [{"text": ch} for ch in text],
        "boundingBox": {
            "normalizedVertices": [
                {"x": x_min, "y": y_min},
                {"x": x_max, "y": y_min},
                {"x": x_max, "y": y_max},
                {"x": x_min, "y": y_max},
            ]
        },
        "confidence": conf,
    }


def _build_vision_json(words: List[Dict]) -> Dict[str, Any]:
    """
    Wrap a list of Vision-format words into a full API response structure.

    Uses the double-nested format:
        {"responses": [{"responses": [{"fullTextAnnotation": ...}]}]}
    """
    full_text = " ".join(
        "".join(s["text"] for s in w["symbols"]) for w in words
    )
    return {
        "responses": [{
            "responses": [{
                "fullTextAnnotation": {
                    "text": full_text,
                    "pages": [{
                        "width": 1,
                        "height": 1,
                        "blocks": [{
                            "paragraphs": [{
                                "words": words,
                            }]
                        }],
                    }],
                }
            }]
        }]
    }


def build_standard_invoice_vision_json() -> Dict[str, Any]:
    """
    Build a realistic Google Vision JSON for the standard test invoice:

        Harga Jual / Penggantian / Uang Muka / Termin   4.953.154,00
        Dikurangi Potongan Harga                           247.658,00
        Dikurangi Uang Muka yang telah diterima                     -
        Dasar Pengenaan Pajak                            4.313.371,00
        Jumlah PPN (Pajak Pertambahan Nilai)               517.605,00
        Jumlah PPnBM (Pajak Penjualan atas Barang Mewah)        0,00
    """
    # Label column spans x ≈ 0.05–0.55
    # Value column spans x ≈ 0.60–0.90
    words = [
        # --- Row 1: Harga Jual (y ≈ 0.58) ---
        _make_word("Harga",       0.05, 0.575, 0.10, 0.590),
        _make_word("Jual",        0.11, 0.575, 0.15, 0.590),
        _make_word("/",           0.16, 0.575, 0.17, 0.590),
        _make_word("Penggantian", 0.18, 0.575, 0.30, 0.590),
        _make_word("/",           0.31, 0.575, 0.32, 0.590),
        _make_word("Uang",        0.33, 0.575, 0.38, 0.590),
        _make_word("Muka",        0.39, 0.575, 0.43, 0.590),
        _make_word("/",           0.44, 0.575, 0.45, 0.590),
        _make_word("Termin",      0.46, 0.575, 0.52, 0.590),
        _make_word("4.953.154,00", 0.65, 0.575, 0.88, 0.590),

        # --- Row 2: Dikurangi Potongan Harga (y ≈ 0.60) ---
        _make_word("Dikurangi",   0.05, 0.595, 0.16, 0.610),
        _make_word("Potongan",    0.17, 0.595, 0.27, 0.610),
        _make_word("Harga",       0.28, 0.595, 0.34, 0.610),
        _make_word("247.658,00",  0.67, 0.595, 0.88, 0.610),

        # --- Row 3: Dikurangi Uang Muka yang telah diterima (y ≈ 0.62) ---
        _make_word("Dikurangi",   0.05, 0.615, 0.16, 0.630),
        _make_word("Uang",        0.17, 0.615, 0.22, 0.630),
        _make_word("Muka",        0.23, 0.615, 0.28, 0.630),
        _make_word("yang",        0.29, 0.615, 0.33, 0.630),
        _make_word("telah",       0.34, 0.615, 0.39, 0.630),
        _make_word("diterima",    0.40, 0.615, 0.50, 0.630),
        # No value in this row (empty / dash)

        # --- Row 4: Dasar Pengenaan Pajak (y ≈ 0.64) ---
        _make_word("Dasar",       0.05, 0.635, 0.11, 0.650),
        _make_word("Pengenaan",   0.12, 0.635, 0.22, 0.650),
        _make_word("Pajak",       0.23, 0.635, 0.30, 0.650),
        _make_word("4.313.371,00", 0.65, 0.635, 0.88, 0.650),

        # --- Row 5: Jumlah PPN (y ≈ 0.66) ---
        _make_word("Jumlah",      0.05, 0.655, 0.12, 0.670),
        _make_word("PPN",         0.13, 0.655, 0.17, 0.670),
        _make_word("(Pajak",      0.18, 0.655, 0.24, 0.670),
        _make_word("Pertambahan", 0.25, 0.655, 0.38, 0.670),
        _make_word("Nilai)",      0.39, 0.655, 0.45, 0.670),
        _make_word("517.605,00",  0.67, 0.655, 0.88, 0.670),

        # --- Row 6: Jumlah PPnBM (y ≈ 0.68) ---
        _make_word("Jumlah",      0.05, 0.675, 0.12, 0.690),
        _make_word("PPnBM",       0.13, 0.675, 0.20, 0.690),
        _make_word("(Pajak",      0.21, 0.675, 0.27, 0.690),
        _make_word("Penjualan",   0.28, 0.675, 0.38, 0.690),
        _make_word("atas",        0.39, 0.675, 0.42, 0.690),
        _make_word("Barang",      0.43, 0.675, 0.49, 0.690),
        _make_word("Mewah)",      0.50, 0.675, 0.56, 0.690),
        _make_word("0,00",        0.82, 0.675, 0.88, 0.690),
    ]
    return _build_vision_json(words)


# =============================================================================
# TEST: BoundingBox
# =============================================================================

class TestBoundingBox(unittest.TestCase):

    def test_center(self):
        bb = BoundingBox(0.1, 0.2, 0.3, 0.4)
        self.assertAlmostEqual(bb.center_x, 0.2)
        self.assertAlmostEqual(bb.center_y, 0.3)

    def test_same_row_true(self):
        a = BoundingBox(0.1, 0.60, 0.3, 0.62)
        b = BoundingBox(0.7, 0.60, 0.9, 0.62)
        self.assertTrue(a.is_same_row(b))

    def test_same_row_false(self):
        a = BoundingBox(0.1, 0.60, 0.3, 0.62)
        b = BoundingBox(0.1, 0.65, 0.3, 0.67)
        self.assertFalse(a.is_same_row(b, tolerance=0.012))

    def test_is_right_of(self):
        left = BoundingBox(0.1, 0.5, 0.3, 0.52)
        right = BoundingBox(0.5, 0.5, 0.9, 0.52)
        self.assertTrue(right.is_right_of(left))
        self.assertFalse(left.is_right_of(right))

    def test_is_below(self):
        top = BoundingBox(0.1, 0.50, 0.3, 0.52)
        bot = BoundingBox(0.1, 0.53, 0.3, 0.55)
        self.assertTrue(bot.is_below(top, max_distance=0.04))
        self.assertFalse(top.is_below(bot))


# =============================================================================
# TEST: OCRToken
# =============================================================================

class TestOCRToken(unittest.TestCase):

    def test_is_numeric(self):
        tok = OCRToken("4.313.371,00", BoundingBox(0.6, 0.6, 0.9, 0.62))
        self.assertTrue(tok.is_numeric)

    def test_is_not_numeric(self):
        tok = OCRToken("Pajak", BoundingBox(0.1, 0.6, 0.3, 0.62))
        self.assertFalse(tok.is_numeric)

    def test_is_currency_value(self):
        tok = OCRToken("517.605,00", BoundingBox(0.7, 0.66, 0.9, 0.68))
        self.assertTrue(tok.is_currency_value)


# =============================================================================
# TEST: LayoutAwareParser — token extraction
# =============================================================================

class TestTokenExtraction(unittest.TestCase):

    def test_extract_from_normalized_vertices(self):
        """Tokens should be extracted from normalizedVertices."""
        vision = build_standard_invoice_vision_json()
        parser = LayoutAwareParser(vision_json=vision)
        self.assertGreater(len(parser.tokens), 20)

    def test_extract_from_flat_structure(self):
        """Also handles the flat {fullTextAnnotation: ...} structure."""
        inner = build_standard_invoice_json_flat()
        parser = LayoutAwareParser(vision_json=inner)
        self.assertGreater(len(parser.tokens), 0)

    def test_empty_json(self):
        parser = LayoutAwareParser(vision_json={})
        self.assertEqual(len(parser.tokens), 0)

    def test_token_from_vertices_fallback(self):
        """When normalizedVertices absent, fall back to vertices + page dims."""
        word = {
            "symbols": [{"text": "T"}, {"text": "e"}, {"text": "s"}, {"text": "t"}],
            "boundingBox": {
                "vertices": [
                    {"x": 100, "y": 200},
                    {"x": 200, "y": 200},
                    {"x": 200, "y": 220},
                    {"x": 100, "y": 220},
                ]
            },
            "confidence": 0.95,
        }
        vision = {
            "fullTextAnnotation": {
                "text": "Test",
                "pages": [{
                    "width": 1000,
                    "height": 1000,
                    "blocks": [{"paragraphs": [{"words": [word]}]}],
                }],
            }
        }
        parser = LayoutAwareParser(vision_json=vision)
        self.assertEqual(len(parser.tokens), 1)
        tok = parser.tokens[0]
        self.assertAlmostEqual(tok.bbox.x_min, 0.1)
        self.assertAlmostEqual(tok.bbox.y_min, 0.2)


def build_standard_invoice_json_flat() -> Dict:
    """Flat structure — no outer 'responses' wrapper."""
    nested = build_standard_invoice_vision_json()
    return nested["responses"][0]["responses"][0]


# =============================================================================
# TEST: Row grouping
# =============================================================================

class TestRowGrouping(unittest.TestCase):

    def test_rows_are_grouped(self):
        vision = build_standard_invoice_vision_json()
        parser = LayoutAwareParser(vision_json=vision)
        # We defined 6 distinct Y bands ⇒ should see ~6 rows
        self.assertGreaterEqual(len(parser._rows), 5)
        self.assertLessEqual(len(parser._rows), 8)

    def test_rows_sorted_by_y(self):
        vision = build_standard_invoice_vision_json()
        parser = LayoutAwareParser(vision_json=vision)
        ys = [y for y, _ in parser._rows]
        self.assertEqual(ys, sorted(ys))


# =============================================================================
# TEST: Value column detection
# =============================================================================

class TestValueColumnDetection(unittest.TestCase):

    def test_auto_detected_column_in_right_half(self):
        vision = build_standard_invoice_vision_json()
        parser = LayoutAwareParser(vision_json=vision)
        x_min, x_max = parser._value_col_range
        self.assertGreater(x_min, 0.35)
        self.assertLessEqual(x_max, 1.0)


# =============================================================================
# TEST: CORE — parse_summary_section (the main test!)
# =============================================================================

class TestParseSummarySection(unittest.TestCase):
    """Verify that the parser correctly maps DPP and PPN values."""

    def test_standard_invoice(self):
        """
        THE key test: DPP = 4,313,371 and PPN = 517,605.
        The old regex parser would swap these. Layout parser must not.
        """
        vision = build_standard_invoice_vision_json()
        parser = LayoutAwareParser(vision_json=vision)
        result = parser.parse_summary_section()

        self.assertAlmostEqual(result["harga_jual"],     4953154.0, delta=1)
        self.assertAlmostEqual(result["potongan_harga"],  247658.0, delta=1)
        self.assertAlmostEqual(result["dpp"],            4313371.0, delta=1)  # ⭐ NOT 517605
        self.assertAlmostEqual(result["ppn"],             517605.0, delta=1)  # ⭐ NOT 62112.6
        self.assertAlmostEqual(result["ppnbm"],                0.0, delta=1)

    def test_dpp_is_not_ppn(self):
        """Explicit check: DPP must be larger than PPN."""
        vision = build_standard_invoice_vision_json()
        parser = LayoutAwareParser(vision_json=vision)
        result = parser.parse_summary_section()
        self.assertGreater(result["dpp"], result["ppn"])

    def test_uang_muka_is_zero_when_missing(self):
        vision = build_standard_invoice_vision_json()
        parser = LayoutAwareParser(vision_json=vision)
        result = parser.parse_summary_section()
        self.assertEqual(result["uang_muka"], 0.0)


# =============================================================================
# TEST: Value extraction — same-row and below-label
# =============================================================================

class TestValueExtraction(unittest.TestCase):

    def test_value_below_label(self):
        """
        Invoice layout where value is on the line below the label.

        Dasar Pengenaan Pajak        (label row, no value)
        4.313.371,00                 (value row, in value column)
        """
        words = [
            _make_word("Dasar",        0.05, 0.640, 0.11, 0.655),
            _make_word("Pengenaan",    0.12, 0.640, 0.22, 0.655),
            _make_word("Pajak",        0.23, 0.640, 0.30, 0.655),
            # Value on next row
            _make_word("4.313.371,00", 0.65, 0.660, 0.88, 0.675),
        ]
        vision = _build_vision_json(words)
        parser = LayoutAwareParser(vision_json=vision)

        dpp_patterns = SUMMARY_LABEL_PATTERNS[3][1]  # 'dpp' patterns
        value = parser.extract_currency_value(dpp_patterns, "dpp")
        self.assertIsNotNone(value)
        self.assertAlmostEqual(value, 4313371.0, delta=1)


# =============================================================================
# TEST: Split numeric tokens merge
# =============================================================================

class TestSplitTokenMerge(unittest.TestCase):

    def test_merge_split_amount(self):
        """
        OCR splits '4.313.371,00' into two adjacent tokens:
        '4.313.371' and ',00'
        """
        words = [
            _make_word("Dasar",      0.05, 0.640, 0.11, 0.655),
            _make_word("Pengenaan",  0.12, 0.640, 0.22, 0.655),
            _make_word("Pajak",      0.23, 0.640, 0.30, 0.655),
            # Split value tokens — close together horizontally
            _make_word("4.313.371",  0.65, 0.640, 0.82, 0.655),
            _make_word(",00",        0.82, 0.640, 0.88, 0.655),
        ]
        vision = _build_vision_json(words)
        parser = LayoutAwareParser(vision_json=vision)

        dpp_patterns = SUMMARY_LABEL_PATTERNS[3][1]
        value = parser.extract_currency_value(dpp_patterns, "dpp")
        self.assertIsNotNone(value)
        self.assertAlmostEqual(value, 4313371.0, delta=1)


# =============================================================================
# TEST: Validation
# =============================================================================

class TestValidation(unittest.TestCase):

    def test_valid_summary(self):
        summary = {
            "harga_jual": 4953154.0,
            "potongan_harga": 247658.0,
            "uang_muka": 0.0,
            "dpp": 4313371.0,
            "ppn": 517605.0,
            "ppnbm": 0.0,
        }
        result = validate_summary_amounts(summary, tax_rate=0.12)
        self.assertTrue(result["is_valid"])
        self.assertEqual(len(result["errors"]), 0)
        self.assertGreater(result["confidence"], 80)

    def test_swapped_fields_detected(self):
        """PPN > DPP should trigger FIELD SWAP error."""
        summary = {
            "harga_jual": 4953154.0,
            "potongan_harga": 0.0,
            "uang_muka": 0.0,
            "dpp": 517605.0,     # WRONG — this is PPN
            "ppn": 4313371.0,    # WRONG — this is DPP
            "ppnbm": 0.0,
        }
        result = validate_summary_amounts(summary)
        self.assertFalse(result["is_valid"])
        self.assertTrue(any("SWAP" in e.upper() for e in result["errors"]))
        self.assertEqual(result["confidence"], 0.0)

    def test_missing_dpp(self):
        summary = {"harga_jual": 1000.0, "dpp": 0.0, "ppn": 0.0, "ppnbm": 0.0}
        result = validate_summary_amounts(summary)
        self.assertFalse(result["is_valid"])

    def test_bug_pattern_harga_equals_dpp_plus_ppn(self):
        """
        Bug pattern: Harga Jual = alleged-DPP + alleged-PPN,
        but PPN > DPP ⇒ fields are reversed.
        """
        summary = {
            "harga_jual": 5000.0,
            "potongan_harga": 0.0,
            "uang_muka": 0.0,
            "dpp": 1000.0,
            "ppn": 4000.0,
            "ppnbm": 0.0,
        }
        result = validate_summary_amounts(summary)
        self.assertFalse(result["is_valid"])
        self.assertTrue(any("BUG PATTERN" in e for e in result["errors"]))


# =============================================================================
# TEST: process_with_layout_parser (integration)
# =============================================================================

class TestProcessWithLayoutParser(unittest.TestCase):

    @patch("imogi_finance.parsers.normalization.detect_tax_rate", return_value=0.12)
    def test_full_pipeline(self, mock_rate):
        vision = build_standard_invoice_vision_json()
        result = process_with_layout_parser(
            vision_json=vision,
            faktur_no="040.002-26.50406870",
            faktur_type="040",
        )
        self.assertAlmostEqual(result["dpp"], 4313371.0, delta=1)
        self.assertAlmostEqual(result["ppn"], 517605.0, delta=1)
        self.assertEqual(result["extraction_method"], "layout_aware")
        self.assertIn(result["parse_status"], ("Approved", "Needs Review"))

    @patch("imogi_finance.parsers.normalization.detect_tax_rate", return_value=0.11)
    def test_fallback_to_text(self, mock_rate):
        """If Vision JSON is empty, fallback to text extraction."""
        with patch.object(
            LayoutAwareParser,
            "parse_summary_from_text",
            return_value={
                "harga_jual": 1000000.0,
                "potongan_harga": 0.0,
                "uang_muka": 0.0,
                "dpp": 900000.0,
                "ppn": 99000.0,
                "ppnbm": 0.0,
            },
        ):
            result = process_with_layout_parser(
                vision_json={},
                ocr_text="Dasar Pengenaan Pajak 900.000,00\nJumlah PPN 99.000,00",
            )
            self.assertEqual(result["extraction_method"], "text_fallback")
            self.assertAlmostEqual(result["dpp"], 900000.0, delta=1)


# =============================================================================
# TEST: Pre-built OCRToken list (skip Vision JSON parsing)
# =============================================================================

class TestPreBuiltTokens(unittest.TestCase):

    def test_parser_from_tokens(self):
        """Parser can accept a pre-built token list directly."""
        tokens = [
            OCRToken("Dasar",        BoundingBox(0.05, 0.64, 0.11, 0.65)),
            OCRToken("Pengenaan",    BoundingBox(0.12, 0.64, 0.22, 0.65)),
            OCRToken("Pajak",        BoundingBox(0.23, 0.64, 0.30, 0.65)),
            OCRToken("4.313.371,00", BoundingBox(0.65, 0.64, 0.88, 0.65)),
            OCRToken("Jumlah",       BoundingBox(0.05, 0.66, 0.12, 0.67)),
            OCRToken("PPN",          BoundingBox(0.13, 0.66, 0.17, 0.67)),
            OCRToken("517.605,00",   BoundingBox(0.67, 0.66, 0.88, 0.67)),
        ]
        parser = LayoutAwareParser(tokens=tokens)
        result = parser.parse_summary_section()
        self.assertAlmostEqual(result["dpp"], 4313371.0, delta=1)
        self.assertAlmostEqual(result["ppn"], 517605.0, delta=1)


# =============================================================================
# TEST: Plausibility Check — DPP vs Harga Jual relationship
# =============================================================================

class TestPlausibilityCheck(unittest.TestCase):
    """
    Tests for the post-extraction plausibility check added in
    parse_summary_section(). When extracted values are internally
    consistent but don't satisfy DPP ≈ f(Harga_Jual), they should be
    invalidated (set to 0.0) so that the text-based fallback triggers.
    """

    def test_wrong_values_rejected(self):
        """
        Invoice 04002500436451666 bug: parser extracted hj=121,275,
        dpp=80,000, ppn=9,600. These are internally consistent
        (80,000 × 12% = 9,600) but DPP doesn't match Harga Jual under
        any tax rule.  Plausibility check should zero them out.
        """
        tokens = [
            # Harga Jual label + WRONG value (121,275 = actual PPN)
            OCRToken("Harga",         BoundingBox(0.05, 0.575, 0.10, 0.590)),
            OCRToken("Jual",          BoundingBox(0.11, 0.575, 0.15, 0.590)),
            OCRToken("/",             BoundingBox(0.16, 0.575, 0.17, 0.590)),
            OCRToken("Penggantian",   BoundingBox(0.18, 0.575, 0.30, 0.590)),
            OCRToken("121.275,00",    BoundingBox(0.65, 0.575, 0.88, 0.590)),

            # Potongan Harga
            OCRToken("Dikurangi",     BoundingBox(0.05, 0.595, 0.16, 0.610)),
            OCRToken("Potongan",      BoundingBox(0.17, 0.595, 0.27, 0.610)),
            OCRToken("Harga",         BoundingBox(0.28, 0.595, 0.34, 0.610)),
            OCRToken("0,00",          BoundingBox(0.82, 0.595, 0.88, 0.610)),

            # DPP label + WRONG value (80,000 = last item price)
            OCRToken("Dasar",         BoundingBox(0.05, 0.635, 0.11, 0.650)),
            OCRToken("Pengenaan",     BoundingBox(0.12, 0.635, 0.22, 0.650)),
            OCRToken("Pajak",         BoundingBox(0.23, 0.635, 0.30, 0.650)),
            OCRToken("80.000,00",     BoundingBox(0.65, 0.635, 0.88, 0.650)),

            # PPN label + WRONG value (9,600 = 80,000 × 12%)
            OCRToken("Jumlah",        BoundingBox(0.05, 0.655, 0.12, 0.670)),
            OCRToken("PPN",           BoundingBox(0.13, 0.655, 0.17, 0.670)),
            OCRToken("(Pajak",        BoundingBox(0.18, 0.655, 0.24, 0.670)),
            OCRToken("Pertambahan",   BoundingBox(0.25, 0.655, 0.38, 0.670)),
            OCRToken("Nilai)",        BoundingBox(0.39, 0.655, 0.45, 0.670)),
            OCRToken("9.600,00",      BoundingBox(0.67, 0.655, 0.88, 0.670)),

            # PPnBM
            OCRToken("Jumlah",        BoundingBox(0.05, 0.675, 0.12, 0.690)),
            OCRToken("PPnBM",         BoundingBox(0.13, 0.675, 0.20, 0.690)),
            OCRToken("(Pajak",        BoundingBox(0.21, 0.675, 0.27, 0.690)),
            OCRToken("Penjualan",     BoundingBox(0.28, 0.675, 0.38, 0.690)),
            OCRToken("atas",          BoundingBox(0.39, 0.675, 0.42, 0.690)),
            OCRToken("Barang",        BoundingBox(0.43, 0.675, 0.49, 0.690)),
            OCRToken("Mewah)",        BoundingBox(0.50, 0.675, 0.56, 0.690)),
            OCRToken("0,00",          BoundingBox(0.82, 0.675, 0.88, 0.690)),
        ]
        parser = LayoutAwareParser(tokens=tokens)
        result = parser.parse_summary_section()

        # All values should be zeroed out because DPP doesn't match HJ
        self.assertEqual(result["harga_jual"], 0.0,
                         "Plausibility check should zero harga_jual")
        self.assertEqual(result["dpp"], 0.0,
                         "Plausibility check should zero dpp")
        self.assertEqual(result["ppn"], 0.0,
                         "Plausibility check should zero ppn")

    def test_correct_040_values_accepted(self):
        """
        Correct 040-type invoice: Harga Jual=1,102,500,
        DPP=1,010,625 (= HJ × 11/12), PPN=121,275 (= DPP × 12%).
        These should pass the plausibility check.
        """
        tokens = [
            OCRToken("Harga",         BoundingBox(0.05, 0.575, 0.10, 0.590)),
            OCRToken("Jual",          BoundingBox(0.11, 0.575, 0.15, 0.590)),
            OCRToken("/",             BoundingBox(0.16, 0.575, 0.17, 0.590)),
            OCRToken("Penggantian",   BoundingBox(0.18, 0.575, 0.30, 0.590)),
            OCRToken("1.102.500,00",  BoundingBox(0.65, 0.575, 0.88, 0.590)),

            OCRToken("Dikurangi",     BoundingBox(0.05, 0.595, 0.16, 0.610)),
            OCRToken("Potongan",      BoundingBox(0.17, 0.595, 0.27, 0.610)),
            OCRToken("Harga",         BoundingBox(0.28, 0.595, 0.34, 0.610)),
            OCRToken("0,00",          BoundingBox(0.82, 0.595, 0.88, 0.610)),

            OCRToken("Dasar",         BoundingBox(0.05, 0.635, 0.11, 0.650)),
            OCRToken("Pengenaan",     BoundingBox(0.12, 0.635, 0.22, 0.650)),
            OCRToken("Pajak",         BoundingBox(0.23, 0.635, 0.30, 0.650)),
            OCRToken("1.010.625,00",  BoundingBox(0.65, 0.635, 0.88, 0.650)),

            OCRToken("Jumlah",        BoundingBox(0.05, 0.655, 0.12, 0.670)),
            OCRToken("PPN",           BoundingBox(0.13, 0.655, 0.17, 0.670)),
            OCRToken("(Pajak",        BoundingBox(0.18, 0.655, 0.24, 0.670)),
            OCRToken("Pertambahan",   BoundingBox(0.25, 0.655, 0.38, 0.670)),
            OCRToken("Nilai)",        BoundingBox(0.39, 0.655, 0.45, 0.670)),
            OCRToken("121.275,00",    BoundingBox(0.67, 0.655, 0.88, 0.670)),

            OCRToken("Jumlah",        BoundingBox(0.05, 0.675, 0.12, 0.690)),
            OCRToken("PPnBM",         BoundingBox(0.13, 0.675, 0.20, 0.690)),
            OCRToken("(Pajak",        BoundingBox(0.21, 0.675, 0.27, 0.690)),
            OCRToken("Penjualan",     BoundingBox(0.28, 0.675, 0.38, 0.690)),
            OCRToken("atas",          BoundingBox(0.39, 0.675, 0.42, 0.690)),
            OCRToken("Barang",        BoundingBox(0.43, 0.675, 0.49, 0.690)),
            OCRToken("Mewah)",        BoundingBox(0.50, 0.675, 0.56, 0.690)),
            OCRToken("0,00",          BoundingBox(0.82, 0.675, 0.88, 0.690)),
        ]
        parser = LayoutAwareParser(tokens=tokens)
        result = parser.parse_summary_section()

        self.assertAlmostEqual(result["harga_jual"], 1102500.0, delta=1)
        self.assertAlmostEqual(result["dpp"], 1010625.0, delta=1)
        self.assertAlmostEqual(result["ppn"], 121275.0, delta=1)

    def test_classic_010_values_accepted(self):
        """
        Classic 010-type invoice: DPP = Harga Jual − Potongan.
        Should pass plausibility under the classic rule.
        """
        tokens = [
            OCRToken("Harga",         BoundingBox(0.05, 0.575, 0.10, 0.590)),
            OCRToken("Jual",          BoundingBox(0.11, 0.575, 0.15, 0.590)),
            OCRToken("1.000.000,00",  BoundingBox(0.65, 0.575, 0.88, 0.590)),

            OCRToken("Dikurangi",     BoundingBox(0.05, 0.595, 0.16, 0.610)),
            OCRToken("Potongan",      BoundingBox(0.17, 0.595, 0.27, 0.610)),
            OCRToken("Harga",         BoundingBox(0.28, 0.595, 0.34, 0.610)),
            OCRToken("50.000,00",     BoundingBox(0.67, 0.595, 0.88, 0.610)),

            OCRToken("Dasar",         BoundingBox(0.05, 0.635, 0.11, 0.650)),
            OCRToken("Pengenaan",     BoundingBox(0.12, 0.635, 0.22, 0.650)),
            OCRToken("Pajak",         BoundingBox(0.23, 0.635, 0.30, 0.650)),
            OCRToken("950.000,00",    BoundingBox(0.65, 0.635, 0.88, 0.650)),

            OCRToken("Jumlah",        BoundingBox(0.05, 0.655, 0.12, 0.670)),
            OCRToken("PPN",           BoundingBox(0.13, 0.655, 0.17, 0.670)),
            OCRToken("(Pajak",        BoundingBox(0.18, 0.655, 0.24, 0.670)),
            OCRToken("Pertambahan",   BoundingBox(0.25, 0.655, 0.38, 0.670)),
            OCRToken("Nilai)",        BoundingBox(0.39, 0.655, 0.45, 0.670)),
            OCRToken("104.500,00",    BoundingBox(0.67, 0.655, 0.88, 0.670)),

            OCRToken("Jumlah",        BoundingBox(0.05, 0.675, 0.12, 0.690)),
            OCRToken("PPnBM",         BoundingBox(0.13, 0.675, 0.20, 0.690)),
            OCRToken("(Pajak",        BoundingBox(0.21, 0.675, 0.27, 0.690)),
            OCRToken("Penjualan",     BoundingBox(0.28, 0.675, 0.38, 0.690)),
            OCRToken("atas",          BoundingBox(0.39, 0.675, 0.42, 0.690)),
            OCRToken("Barang",        BoundingBox(0.43, 0.675, 0.49, 0.690)),
            OCRToken("Mewah)",        BoundingBox(0.50, 0.675, 0.56, 0.690)),
            OCRToken("0,00",          BoundingBox(0.82, 0.675, 0.88, 0.690)),
        ]
        parser = LayoutAwareParser(tokens=tokens)
        result = parser.parse_summary_section()

        # DPP = 950,000 = Harga Jual (1,000,000) − Potongan (50,000) → classic rule
        self.assertAlmostEqual(result["harga_jual"], 1000000.0, delta=1)
        self.assertAlmostEqual(result["dpp"], 950000.0, delta=1)
        self.assertAlmostEqual(result["ppn"], 104500.0, delta=1)


# =============================================================================
# TEST: Cross-validation (text vs coordinate extraction)
# =============================================================================

class TestCrossValidation(unittest.TestCase):
    """
    Tests for the cross-validation logic in process_with_layout_parser()
    that compares coordinate-based and text-based extraction results.
    """

    def test_text_override_when_layout_wrong(self):
        """
        When layout extraction returns small wrong values but text
        extraction returns much larger correct values, the cross-
        validation should prefer the text values.
        """
        # Build a Vision JSON that would produce wrong small values
        wrong_tokens = [
            _make_word("Harga",       0.05, 0.575, 0.10, 0.590),
            _make_word("Jual",        0.11, 0.575, 0.15, 0.590),
            _make_word("/",           0.16, 0.575, 0.17, 0.590),
            _make_word("Penggantian", 0.18, 0.575, 0.30, 0.590),
            _make_word("121.275,00",  0.65, 0.575, 0.88, 0.590),

            _make_word("Dikurangi",   0.05, 0.595, 0.16, 0.610),
            _make_word("Potongan",    0.17, 0.595, 0.27, 0.610),
            _make_word("Harga",       0.28, 0.595, 0.34, 0.610),
            _make_word("0,00",        0.82, 0.595, 0.88, 0.610),

            _make_word("Dasar",       0.05, 0.635, 0.11, 0.650),
            _make_word("Pengenaan",   0.12, 0.635, 0.22, 0.650),
            _make_word("Pajak",       0.23, 0.635, 0.30, 0.650),
            _make_word("80.000,00",   0.65, 0.635, 0.88, 0.650),

            _make_word("Jumlah",      0.05, 0.655, 0.12, 0.670),
            _make_word("PPN",         0.13, 0.655, 0.17, 0.670),
            _make_word("(Pajak",      0.18, 0.655, 0.24, 0.670),
            _make_word("Pertambahan", 0.25, 0.655, 0.38, 0.670),
            _make_word("Nilai)",      0.39, 0.655, 0.45, 0.670),
            _make_word("9.600,00",    0.67, 0.655, 0.88, 0.670),

            _make_word("Jumlah",      0.05, 0.675, 0.12, 0.690),
            _make_word("PPnBM",       0.13, 0.675, 0.20, 0.690),
            _make_word("(Pajak",      0.21, 0.675, 0.27, 0.690),
            _make_word("Penjualan",   0.28, 0.675, 0.38, 0.690),
            _make_word("atas",        0.39, 0.675, 0.42, 0.690),
            _make_word("Barang",      0.43, 0.675, 0.49, 0.690),
            _make_word("Mewah)",      0.50, 0.675, 0.56, 0.690),
            _make_word("0,00",        0.82, 0.675, 0.88, 0.690),
        ]
        vision_json = _build_vision_json(wrong_tokens)

        # The plausibility check should zero out the wrong layout values,
        # then the text fallback should provide correct values.
        correct_text = (
            "Harga Jual / Penggantian / Uang Muka / Termin 1.102.500,00\n"
            "Dikurangi Potongan Harga 0,00\n"
            "Dasar Pengenaan Pajak 1.010.625,00\n"
            "Jumlah PPN (Pajak Pertambahan Nilai) 121.275,00\n"
            "Jumlah PPnBM 0,00\n"
        )

        result = process_with_layout_parser(
            vision_json=vision_json,
            faktur_no="040.002-25.04364516",
            faktur_type="040",
            ocr_text=correct_text,
        )

        # Should use text fallback because plausibility check zeroed layout
        self.assertIn(result["extraction_method"], ("text_fallback", "text_cross_validated"))
        self.assertAlmostEqual(result["dpp"], 1010625.0, delta=1)
        self.assertAlmostEqual(result["ppn"], 121275.0, delta=1)
        self.assertAlmostEqual(result["harga_jual"], 1102500.0, delta=1)


# =============================================================================
# RUN
# =============================================================================

if __name__ == "__main__":
    unittest.main()
