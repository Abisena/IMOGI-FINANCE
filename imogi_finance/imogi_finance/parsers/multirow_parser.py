# -*- coding: utf-8 -*-
# Copyright (c) 2026, Imogi Finance and contributors
# For license information, please see license.txt

"""
Multi-Row Item Grouping & Summary Parser for Indonesian Tax Invoices.

Fixes 3 critical bugs in Faktur Pajak OCR parsing:
  1. Multi-row items not grouped (6 rows per item treated as separate items)
  2. Aggressive filter removes valid items containing "Potongan Harga"
  3. Summary section values read from wrong positions

This module provides standalone functions that can be integrated into the
existing faktur_pajak_parser.py pipeline.

Usage::

    from imogi_finance.imogi_finance.parsers.multirow_parser import (
        group_multirow_items,
        parse_grouped_item,
        parse_summary_section,
        is_summary_row,
        validate_parsed_data,
        parse_indonesian_number,
    )
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# Try to use Frappe logger if available
try:
    import frappe
    logger = frappe.logger()
except ImportError:
    pass


# =============================================================================
# CONSTANTS
# =============================================================================

# Pattern for item number + code at beginning of a line
# e.g., "1 000000", "2 000000", "10 000000"
ITEM_NUMBER_PATTERN = re.compile(r'^(\d+)\s+(\d{4,6})')

# Pattern for price × quantity line
# e.g., "Rp 360.500,00 x 1,00 Lainnya"
PRICE_QTY_PATTERN = re.compile(
    r'Rp\s*([\d.,]+)\s*x\s*([\d.,]+)\s*(.*)',
    re.IGNORECASE,
)

# Pattern for Indonesian currency amounts
AMOUNT_PATTERN = re.compile(r'(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?)')

# Pattern for discount line
# e.g., "Potongan Harga = Rp 0,00"
DISCOUNT_PATTERN = re.compile(
    r'Potongan\s+Harga\s*=\s*Rp\s*([\d.,]+)',
    re.IGNORECASE,
)

# Pattern for luxury tax line
# e.g., "PPnBM (0,00%) = Rp 0,00"
PPNBM_ITEM_PATTERN = re.compile(
    r'PPnBM\s*\(([\d.,]+)%\)\s*=\s*Rp\s*([\d.,]+)',
    re.IGNORECASE,
)

# Harga jual column X-range (for coordinate-based parsing)
HARGA_JUAL_X_MIN = 350
HARGA_JUAL_X_MAX = 700

# Summary section labels (used for both summary parsing and filtering)
SUMMARY_LABELS = {
    'harga_jual': [
        re.compile(r'Harga\s+Jual\s*/\s*Penggantian\s*/\s*Uang\s+Muka\s*/\s*Termin', re.I),
        re.compile(r'Harga\s+Jual\s*/\s*Penggantian\s*/\s*Uang\s+Muka', re.I),
        re.compile(r'Harga\s+Jual\s*/\s*Penggantian', re.I),
    ],
    'potongan': [
        re.compile(r'Dikurangi\s+Potongan\s+Harga', re.I),
    ],
    'uang_muka': [
        re.compile(r'Dikurangi\s+Uang\s+Muka\s+yang\s+telah\s+diterima', re.I),
        re.compile(r'Dikurangi\s+Uang\s+Muka', re.I),
    ],
    'dpp': [
        re.compile(r'Dasar\s+Pengenaan\s+Pajak', re.I),
    ],
    'ppn': [
        re.compile(r'Jumlah\s+PPN\s*\([^)]*\)', re.I),
        re.compile(r'Jumlah\s+PPN', re.I),
    ],
    'ppnbm': [
        re.compile(r'Jumlah\s+PPnBM\s*\([^)]*\)', re.I),
        re.compile(r'Jumlah\s+PPnBM', re.I),
    ],
}

# Keywords that START a summary row (never a line item)
SUMMARY_START_KEYWORDS = [
    "harga jual /",
    "harga jual/",
    "dikurangi potongan harga",
    "dikurangi uang muka",
    "dasar pengenaan pajak",
    "jumlah ppn",
    "jumlah ppnbm",
]

# Broad substring keywords for summary detection
SUMMARY_SUBSTRING_KEYWORDS = {
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
    "uang muka yang telah diterima",
    "nilai lain",
    "total harga",
    "sub total",
    "subtotal",
    "ditandatangani secara elektronik",
    "sesuai dengan ketentuan",
    "direktorat jenderal pajak",
    "tidak diperlukan tanda tangan basah",
}

# Header row keywords (never line items)
HEADER_ROW_KEYWORDS = {
    "no. barang",
    "nama barang",
    "no. barang / nama barang",
    "kode barang",
    "harga satuan",
    "jumlah barang",
    "jasa kena pajak",
    "barang kena pajak",
}


# =============================================================================
# VISION JSON → TEXT BLOCKS CONVERSION
# =============================================================================

def vision_json_to_text_blocks(
    vision_json: Dict[str, Any],
    y_tolerance: float = 8.0,
    x_gap_threshold: float = 50.0,
) -> Tuple[List[Dict], float]:
    """
    Convert Google Vision OCR JSON into text blocks for multirow parsing.

    Groups word-level OCR tokens into line/phrase-level text blocks
    suitable for :func:`group_multirow_items` and :func:`parse_summary_section`.

    The Google Vision API returns word-level bounding boxes. This function:

    1. Extracts all words with pixel coordinates from ``fullTextAnnotation``.
    2. Groups words into visual rows by Y-coordinate proximity.
    3. Within each row, groups nearby words into phrases by X-gap.
    4. Returns phrase-level text blocks with ``text``, ``x``, ``y`` keys.

    Handles multiple Vision JSON nesting variants:
      - ``{"responses": [{"responses": [{"fullTextAnnotation": ...}]}]}``
      - ``{"responses": [{"fullTextAnnotation": ...}]}``
      - ``{"fullTextAnnotation": ...}``

    Args:
        vision_json: Google Vision API response dictionary.
        y_tolerance: Maximum Y pixel distance to consider words on same row.
        x_gap_threshold: Minimum X pixel gap to split words into separate
                         text blocks. Words closer than this are joined.

    Returns:
        Tuple of ``(text_blocks, page_height)``:
          - ``text_blocks``: List of ``{'text': str, 'x': float, 'y': float}``
          - ``page_height``: Height of first page in pixels.

    Example::

        >>> vj = {"fullTextAnnotation": {"pages": [{"height": 842, ...}]}}
        >>> blocks, ph = vision_json_to_text_blocks(vj)
        >>> blocks[0]
        {'text': '1 000000', 'x': 50.0, 'y': 100.0}
    """
    # --- Unwrap nested responses to reach fullTextAnnotation ---
    fta = _resolve_full_text_annotation(vision_json)
    if fta is None:
        logger.warning("No fullTextAnnotation found in Vision JSON")
        return [], 800.0

    pages = fta.get('pages', [])
    if not pages:
        logger.warning("No pages in fullTextAnnotation")
        return [], 800.0

    page = pages[0]
    page_height = float(page.get('height', 800))
    page_width = float(page.get('width', 600))

    # --- Extract all word tokens with pixel coordinates ---
    word_tokens: List[Dict] = []

    for block in page.get('blocks', []):
        for para in block.get('paragraphs', []):
            for word in para.get('words', []):
                symbols = word.get('symbols', [])
                if not symbols:
                    continue

                text = ''.join(s.get('text', '') for s in symbols)
                if not text.strip():
                    continue

                bbox = word.get('boundingBox', {})
                # Prefer raw vertices; fall back to normalizedVertices × page size
                vertices = bbox.get('vertices', [])
                use_normalized = False
                if not vertices or not any('x' in v for v in vertices):
                    vertices = bbox.get('normalizedVertices', [])
                    use_normalized = True

                if len(vertices) < 4:
                    continue

                xs = [v.get('x', 0) for v in vertices]
                ys = [v.get('y', 0) for v in vertices]

                if use_normalized:
                    xs = [x * page_width for x in xs]
                    ys = [y * page_height for y in ys]

                x0, x1 = min(xs), max(xs)
                y0, y1 = min(ys), max(ys)

                word_tokens.append({
                    'text': text.strip(),
                    'x0': x0, 'y0': y0,
                    'x1': x1, 'y1': y1,
                })

    if not word_tokens:
        logger.warning("No word tokens extracted from Vision JSON")
        return [], page_height

    # --- Group into visual rows by Y proximity ---
    sorted_tokens = sorted(word_tokens, key=lambda t: (t['y0'], t['x0']))
    rows: List[List[Dict]] = []
    current_row: List[Dict] = [sorted_tokens[0]]
    current_y = sorted_tokens[0]['y0']

    for tok in sorted_tokens[1:]:
        if abs(tok['y0'] - current_y) <= y_tolerance:
            current_row.append(tok)
        else:
            rows.append(current_row)
            current_row = [tok]
            current_y = tok['y0']
    if current_row:
        rows.append(current_row)

    # --- Within each row, group words into phrases by X gap ---
    text_blocks: List[Dict] = []

    for row in rows:
        sorted_row = sorted(row, key=lambda t: t['x0'])

        phrases: List[List[Dict]] = [[sorted_row[0]]]
        for tok in sorted_row[1:]:
            gap = tok['x0'] - phrases[-1][-1]['x1']
            if gap > x_gap_threshold:
                phrases.append([tok])
            else:
                phrases[-1].append(tok)

        for phrase in phrases:
            text = ' '.join(t['text'] for t in phrase)
            x = phrase[0]['x0']
            avg_y = sum(t['y0'] for t in phrase) / len(phrase)
            text_blocks.append({'text': text, 'x': x, 'y': avg_y})

    logger.debug(
        f"Converted Vision JSON to {len(text_blocks)} text blocks "
        f"(from {len(word_tokens)} words, page_height={page_height:.0f})"
    )
    return text_blocks, page_height


def _resolve_full_text_annotation(vision_json: Dict[str, Any]) -> Optional[Dict]:
    """
    Unwrap nested Google Vision JSON to reach ``fullTextAnnotation``.

    Handles variants:
      - ``{"responses": [{"responses": [{"fullTextAnnotation": ...}]}]}``
      - ``{"responses": [{"fullTextAnnotation": ...}]}``
      - ``{"fullTextAnnotation": ...}``

    Returns:
        The ``fullTextAnnotation`` dict, or None if not found.
    """
    if not vision_json or not isinstance(vision_json, dict):
        return None

    # Direct
    if 'fullTextAnnotation' in vision_json:
        return vision_json['fullTextAnnotation']

    # Single-nested responses
    responses = vision_json.get('responses', [])
    if not responses or not isinstance(responses, list):
        return None

    first = responses[0]
    if isinstance(first, dict):
        if 'fullTextAnnotation' in first:
            return first['fullTextAnnotation']

        # Double-nested responses
        inner = first.get('responses', [])
        if inner and isinstance(inner, list) and isinstance(inner[0], dict):
            return inner[0].get('fullTextAnnotation')

    return None


def tokens_to_text_blocks(
    tokens: List[Any],
    y_tolerance: float = 5.0,
    x_gap_threshold: float = 50.0,
) -> Tuple[List[Dict], float]:
    """
    Convert word-level Token objects to text blocks for multirow parsing.

    Accepts Token objects from ``faktur_pajak_parser.vision_to_tokens()``
    or ``extract_text_with_bbox()``. Each Token must have attributes:
    ``text``, ``x0``, ``y0``, ``x1``, ``y1``.

    Args:
        tokens: List of Token objects (with x0, y0, x1, y1, text).
        y_tolerance: Y distance for same-row grouping.
        x_gap_threshold: X gap for phrase splitting.

    Returns:
        Tuple of ``(text_blocks, page_height)``.
    """
    if not tokens:
        return [], 800.0

    # Estimate page height from max y1
    page_height = max(getattr(t, 'y1', 0) or 0 for t in tokens) * 1.1
    page_height = max(page_height, 800.0)

    # Convert to dicts
    word_dicts = []
    for t in tokens:
        word_dicts.append({
            'text': str(getattr(t, 'text', '')).strip(),
            'x0': float(getattr(t, 'x0', 0)),
            'y0': float(getattr(t, 'y0', 0)),
            'x1': float(getattr(t, 'x1', 0)),
            'y1': float(getattr(t, 'y1', 0)),
        })

    # Group into rows
    sorted_tokens = sorted(word_dicts, key=lambda t: (t['y0'], t['x0']))
    rows: List[List[Dict]] = []
    current_row: List[Dict] = [sorted_tokens[0]]
    current_y = sorted_tokens[0]['y0']

    for tok in sorted_tokens[1:]:
        if abs(tok['y0'] - current_y) <= y_tolerance:
            current_row.append(tok)
        else:
            rows.append(current_row)
            current_row = [tok]
            current_y = tok['y0']
    if current_row:
        rows.append(current_row)

    # Group into phrases
    text_blocks: List[Dict] = []
    for row in rows:
        sorted_row = sorted(row, key=lambda t: t['x0'])
        phrases: List[List[Dict]] = [[sorted_row[0]]]
        for tok in sorted_row[1:]:
            gap = tok['x0'] - phrases[-1][-1]['x1']
            if gap > x_gap_threshold:
                phrases.append([tok])
            else:
                phrases[-1].append(tok)

        for phrase in phrases:
            text = ' '.join(t['text'] for t in phrase if t['text'])
            if text.strip():
                x = phrase[0]['x0']
                avg_y = sum(t['y0'] for t in phrase) / len(phrase)
                text_blocks.append({'text': text, 'x': x, 'y': avg_y})

    return text_blocks, page_height


# =============================================================================
# NUMBER PARSING
# =============================================================================

def parse_indonesian_number(value_str: str) -> float:
    """
    Convert Indonesian number format to float.

    Indonesian format uses period (.) as thousand separator and
    comma (,) as decimal separator.

    Args:
        value_str: Number string in Indonesian format.

    Returns:
        Float value. Returns 0.0 for invalid/empty inputs.

    Examples:
        >>> parse_indonesian_number("1.102.500,00")
        1102500.0
        >>> parse_indonesian_number("360.500")
        360500.0
        >>> parse_indonesian_number("121.275,00")
        121275.0
        >>> parse_indonesian_number("0,00")
        0.0
        >>> parse_indonesian_number("Rp 360.500,00")
        360500.0
        >>> parse_indonesian_number("")
        0.0
    """
    if not value_str or not isinstance(value_str, str):
        return 0.0

    text = str(value_str).strip()
    if not text:
        return 0.0

    # Remove "Rp" prefix (case-insensitive)
    text = re.sub(r'^[Rr][Pp]\s*', '', text).strip()
    if not text:
        return 0.0

    comma_count = text.count(',')

    if comma_count > 1:
        # Invalid format
        logger.warning(f"Invalid Indonesian number format (multiple commas): {value_str}")
        return 0.0

    if comma_count == 1:
        # Standard: "4.953.154,00" → integer_part="4953154", decimal_part="00"
        parts = text.split(',')
        integer_part = parts[0].replace('.', '')
        decimal_part = parts[1] if len(parts) > 1 else '0'

        # Remove non-digit characters
        integer_part = re.sub(r'[^\d]', '', integer_part)
        decimal_part = re.sub(r'[^\d]', '', decimal_part)

        text = f"{integer_part}.{decimal_part}" if decimal_part else integer_part
    else:
        # No comma — integer-only or "4.953.154" format
        text = text.replace('.', '')
        text = re.sub(r'[^\d]', '', text)

    if not text:
        return 0.0

    try:
        value = float(text)
        if value < 0:
            logger.warning(f"Negative value parsed: {value_str} → {value}")
            return 0.0
        return value
    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to parse Indonesian number '{value_str}': {e}")
        return 0.0


# =============================================================================
# FIX #1: MULTI-ROW ITEM GROUPING
# =============================================================================

def group_multirow_items(text_blocks: List[Dict]) -> List[Dict]:
    """
    Group consecutive rows that belong to the same invoice line item.

    Each line item in an Indonesian Tax Invoice (Faktur Pajak) spans
    approximately 6 rows in the OCR output:

    ::

        Row 1: "1 000000"                           ← Item number & code
        Row 2: "HYDRO CARBON TREATMENT"             ← Item description
        Row 3: "Rp 360.500,00 x 1,00 Lainnya"       ← Unit price × quantity
        Row 4: "Potongan Harga = Rp 0,00"           ← Discount line
        Row 5: "PPnBM (0,00%) = Rp 0,00"            ← Luxury tax line
        Row 6: "360.500,00" (in harga_jual column)  ← Final value

    Detection Logic:
        1. Item starts when text matches pattern: ``r'^\\d+\\s+\\d{4,6}'``
           Example: "1 000000", "2 000000", "10 000000"
        2. Following rows are part of the same item until the next item starts
           or we reach a summary section row.
        3. Row with a numeric value at x-position ~400-600 is the final
           harga_jual value.

    Args:
        text_blocks: List of OCR text blocks with 'text', 'x', 'y' keys.
                     Must be sorted by Y position (top to bottom).

    Returns:
        List of grouped items, each containing:
            - ``line_no``: int - Sequential item number (from OCR)
            - ``rows``: List[Dict] - All text blocks for this item
            - ``y_start``: float - Y of first row
            - ``y_end``: float - Y of last row

    Example::

        >>> blocks = [
        ...     {'text': '1 000000', 'x': 50, 'y': 100},
        ...     {'text': 'HYDRO CARBON TREATMENT', 'x': 50, 'y': 110},
        ...     {'text': 'Rp 360.500,00 x 1,00 Lainnya', 'x': 50, 'y': 120},
        ...     {'text': 'Potongan Harga = Rp 0,00', 'x': 50, 'y': 130},
        ...     {'text': 'PPnBM (0,00%) = Rp 0,00', 'x': 50, 'y': 140},
        ...     {'text': '360.500,00', 'x': 450, 'y': 150},
        ... ]
        >>> result = group_multirow_items(blocks)
        >>> len(result)
        1
        >>> result[0]['line_no']
        1
    """
    if not text_blocks:
        return []

    # Sort by Y position (top to bottom)
    sorted_blocks = sorted(text_blocks, key=lambda b: (b.get('y', 0), b.get('x', 0)))

    groups: List[Dict] = []
    current_group: Optional[Dict] = None

    for block in sorted_blocks:
        text = str(block.get('text', '')).strip()
        if not text:
            continue

        # Check if this row starts a new item
        item_match = ITEM_NUMBER_PATTERN.match(text)

        # Check if this is a summary section row
        if is_summary_row(text):
            # Close current group and stop — we've hit the summary section
            if current_group:
                current_group['y_end'] = block.get('y', 0)
                groups.append(current_group)
                current_group = None
            break

        if item_match:
            # Start of a new item
            # First, save the previous group
            if current_group:
                current_group['y_end'] = block.get('y', 0)
                groups.append(current_group)

            line_no = int(item_match.group(1))
            current_group = {
                'line_no': line_no,
                'rows': [block],
                'y_start': block.get('y', 0),
                'y_end': block.get('y', 0),
            }
        elif current_group is not None:
            # Continuation of current item
            current_group['rows'].append(block)
            current_group['y_end'] = block.get('y', 0)
        else:
            # Row before any item starts (e.g., header) — skip
            logger.debug(f"Skipping pre-item row: '{text[:50]}'")

    # Don't forget the last group
    if current_group:
        groups.append(current_group)

    logger.debug(f"Grouped {len(sorted_blocks)} text blocks into {len(groups)} items")
    return groups


def parse_grouped_item(item_group: Dict) -> Dict:
    """
    Extract structured data from a grouped multi-row item.

    Extraction Rules:
        - ``line_no``: From the group metadata (extracted during grouping).
        - ``description``: Longest text row that is NOT a number, price,
          discount, or tax detail. Usually Row 2 (the item name).
        - ``qty``: From row matching ``Rp ... x N,NN`` pattern.
        - ``unit_price``: From same row as qty.
        - ``harga_jual``: Final value from the rightmost column —
          the row that is purely a numeric amount (no label text).
        - ``discount``: From "Potongan Harga = Rp X" row.
        - ``ppnbm_rate``: From "PPnBM (X%) = Rp Y" row.

    Args:
        item_group: Dictionary from :func:`group_multirow_items` with keys
                    ``line_no``, ``rows``, ``y_start``, ``y_end``.

    Returns:
        Dictionary with extracted item data::

            {
                'line_no': int,
                'description': str,
                'qty': float,
                'unit_price': float,
                'harga_jual': float,
                'discount': float,
                'ppnbm_rate': float,
                'ppnbm_amount': float,
                'dpp': float,
                'ppn': float,
            }

    Example::

        >>> group = {
        ...     'line_no': 1,
        ...     'rows': [
        ...         {'text': '1 000000', 'x': 50, 'y': 100},
        ...         {'text': 'HYDRO CARBON TREATMENT', 'x': 50, 'y': 110},
        ...         {'text': 'Rp 360.500,00 x 1,00 Lainnya', 'x': 50, 'y': 120},
        ...         {'text': 'Potongan Harga = Rp 0,00', 'x': 50, 'y': 130},
        ...         {'text': 'PPnBM (0,00%) = Rp 0,00', 'x': 50, 'y': 140},
        ...         {'text': '360.500,00', 'x': 450, 'y': 150},
        ...     ],
        ...     'y_start': 100,
        ...     'y_end': 150,
        ... }
        >>> result = parse_grouped_item(group)
        >>> result['description']
        'HYDRO CARBON TREATMENT'
        >>> result['harga_jual']
        360500.0
        >>> result['unit_price']
        360500.0
        >>> result['qty']
        1.0
    """
    rows = item_group.get('rows', [])

    result = {
        'line_no': item_group.get('line_no', 0),
        'description': '',
        'qty': 0.0,
        'unit_price': 0.0,
        'harga_jual': 0.0,
        'discount': 0.0,
        'ppnbm_rate': 0.0,
        'ppnbm_amount': 0.0,
        'dpp': 0.0,
        'ppn': 0.0,
    }

    if not rows:
        return result

    # Classify each row by its content
    description_candidates: List[Tuple[str, float]] = []  # (text, score)
    harga_jual_value: Optional[float] = None

    for row in rows:
        text = str(row.get('text', '')).strip()
        x_pos = row.get('x', 0)

        if not text:
            continue

        # --- Item number row (Row 1) ---
        if ITEM_NUMBER_PATTERN.match(text):
            # Skip — line_no already extracted during grouping
            continue

        # --- Price × Quantity row (Row 3) ---
        price_qty_match = PRICE_QTY_PATTERN.search(text)
        if price_qty_match:
            result['unit_price'] = parse_indonesian_number(price_qty_match.group(1))
            result['qty'] = parse_indonesian_number(price_qty_match.group(2))
            continue

        # --- Discount row (Row 4) ---
        discount_match = DISCOUNT_PATTERN.search(text)
        if discount_match:
            result['discount'] = parse_indonesian_number(discount_match.group(1))
            continue

        # --- PPnBM row (Row 5) ---
        ppnbm_match = PPNBM_ITEM_PATTERN.search(text)
        if ppnbm_match:
            result['ppnbm_rate'] = parse_indonesian_number(ppnbm_match.group(1))
            result['ppnbm_amount'] = parse_indonesian_number(ppnbm_match.group(2))
            continue

        # --- Harga Jual value row (Row 6) ---
        # Pure numeric value, typically at x > HARGA_JUAL_X_MIN
        amount_match = AMOUNT_PATTERN.fullmatch(text)
        if amount_match and x_pos >= HARGA_JUAL_X_MIN:
            parsed = parse_indonesian_number(text)
            if parsed > 0:
                harga_jual_value = parsed
                continue

        # If it's a pure numeric row but at lower x, still try as harga_jual
        if amount_match and harga_jual_value is None:
            parsed = parse_indonesian_number(text)
            if parsed >= 1000:  # Minimum reasonable item price
                harga_jual_value = parsed
                continue

        # --- Description candidate (Row 2) ---
        # Score: longer text with letters is better description
        letter_count = sum(1 for c in text if c.isalpha())
        if letter_count > 2:
            # Penalize rows with mostly numbers or Rp prefix
            score = letter_count / max(len(text), 1)
            description_candidates.append((text, score))

    # Pick the best description: highest score (most alphabetic content)
    if description_candidates:
        description_candidates.sort(key=lambda x: x[1], reverse=True)
        result['description'] = description_candidates[0][0]

    # Set harga_jual
    if harga_jual_value is not None:
        result['harga_jual'] = harga_jual_value
    elif result['unit_price'] > 0 and result['qty'] > 0:
        # Fallback: calculate from unit_price × qty − discount
        result['harga_jual'] = (result['unit_price'] * result['qty']) - result['discount']

    logger.debug(
        f"Parsed item #{result['line_no']}: "
        f"desc='{result['description'][:40]}', "
        f"harga_jual={result['harga_jual']:,.0f}, "
        f"qty={result['qty']}, "
        f"unit_price={result['unit_price']:,.0f}"
    )

    return result


# =============================================================================
# FIX #2: SMART FILTER FUNCTION
# =============================================================================

def is_summary_row(text: str, context: Optional[Dict] = None) -> bool:
    """
    Determine if a text row is a summary row that should be excluded from items.

    This function fixes the aggressive filter that incorrectly removed valid
    line items containing "Potongan Harga". The key insight is that
    "Potongan Harga = Rp 0,00" appears inside EVERY item detail (as Row 4),
    while "Dikurangi Potongan Harga" is the standalone summary label.

    Rules:
        1. **NEVER** filter if text starts with item pattern ``r'^\\d+\\s+\\d{4,6}'``
           Examples: "1 000000", "2 000000", "10 000000"

        2. **NEVER** filter if text is clearly part of item detail (price
           line, discount with "=", PPnBM percentage, pure description).

        3. **DO** filter if text starts with summary keywords:
           - "Harga Jual /"
           - "Dikurangi Potongan"
           - "Dikurangi Uang Muka"
           - "Dasar Pengenaan Pajak"
           - "Jumlah PPN"
           - "Jumlah PPnBM"

        4. **DO** filter if text contains broad summary-only keywords:
           - "grand total", "sub total"
           - "ditandatangani secara elektronik"

    Args:
        text: Text content of the row.
        context: Optional context dict with keys like ``y_position``,
                 ``page_height``, ``previous_rows``.

    Returns:
        True if row should be filtered out (is summary), False if
        it should be kept (is a line item).

    Examples:
        >>> is_summary_row("1 000000 Potongan Harga = Rp 0,00")
        False
        >>> is_summary_row("Harga Jual / Penggantian / Uang Muka")
        True
        >>> is_summary_row("Dasar Pengenaan Pajak")
        True
        >>> is_summary_row("HYDRO CARBON TREATMENT")
        False
        >>> is_summary_row("Potongan Harga = Rp 0,00")
        False
        >>> is_summary_row("Dikurangi Potongan Harga")
        True
        >>> is_summary_row("PPnBM (0,00%) = Rp 0,00")
        False
        >>> is_summary_row("Rp 360.500,00 x 1,00 Lainnya")
        False
    """
    if not text or not isinstance(text, str):
        return False

    # Normalize whitespace
    text_clean = re.sub(r'\s+', ' ', text.strip())
    text_lower = text_clean.lower()

    if not text_lower:
        return False

    # ----- RULE 1: Item number pattern → ALWAYS keep -----
    if ITEM_NUMBER_PATTERN.match(text_clean):
        return False

    # ----- RULE 2: Item detail patterns → ALWAYS keep -----
    # Price × quantity line: "Rp 360.500,00 x 1,00 Lainnya"
    if PRICE_QTY_PATTERN.search(text_clean):
        return False

    # Discount detail line: "Potongan Harga = Rp 0,00"
    # Key distinction: "=" sign means it's an item detail, not summary
    if DISCOUNT_PATTERN.search(text_clean):
        return False

    # PPnBM detail line: "PPnBM (0,00%) = Rp 0,00"
    if PPNBM_ITEM_PATTERN.search(text_clean):
        return False

    # Pure amount value (no label text): "360.500,00"
    if AMOUNT_PATTERN.fullmatch(text_clean):
        return False

    # ----- RULE 3: Summary START keywords → filter -----
    for keyword in SUMMARY_START_KEYWORDS:
        if text_lower.startswith(keyword):
            return True

    # ----- RULE 4: Broad summary substring keywords → filter -----
    for keyword in SUMMARY_SUBSTRING_KEYWORDS:
        if keyword in text_lower:
            return True

    # ----- RULE 5: Header keywords → filter -----
    for keyword in HEADER_ROW_KEYWORDS:
        if keyword in text_lower:
            return True

    # ----- Default: keep the row -----
    return False


# =============================================================================
# FIX #3: SUMMARY SECTION PARSER
# =============================================================================

def parse_summary_section(
    text_blocks: List[Dict],
    page_height: float = 800.0,
) -> Dict[str, float]:
    """
    Parse the summary section of an Indonesian tax invoice using text blocks
    with spatial coordinates.

    The summary section is located in the bottom portion of the invoice
    (typically y >= 60% of page height) and contains label-value pairs:

    ::

        Harga Jual / Penggantian / Uang Muka / Termin    1.102.500,00
        Dikurangi Potongan Harga                                 0,00
        Dasar Pengenaan Pajak                            1.010.625,00
        Jumlah PPN (Pajak Pertambahan Nilai)               121.275,00
        Jumlah PPnBM (...)                                       0,00

    Strategy:
        1. Filter text blocks to bottom 60-80% of page (summary area).
        2. Group blocks into rows by Y-coordinate proximity.
        3. For each summary label, find matching text on the left side.
        4. Extract the corresponding value from the right side of the
           same row (or nearby row).
        5. Parse values using Indonesian number format.

    Args:
        text_blocks: List of OCR text blocks with keys:
            - ``text``: str — The text content
            - ``x``: float — X coordinate (left edge)
            - ``y``: float — Y coordinate (top edge)
        page_height: Total page height in pixels.

    Returns:
        Dictionary with parsed summary values::

            {
                'harga_jual': float,
                'potongan': float,
                'uang_muka': float,
                'dpp': float,
                'ppn': float,
                'ppnbm': float,
            }

        All values default to 0.0 if not found.

    Example::

        >>> blocks = [
        ...     {'text': 'Harga Jual / Penggantian / Uang Muka / Termin', 'x': 50, 'y': 600},
        ...     {'text': '1.102.500,00', 'x': 450, 'y': 600},
        ...     {'text': 'Dasar Pengenaan Pajak', 'x': 50, 'y': 650},
        ...     {'text': '1.010.625,00', 'x': 450, 'y': 650},
        ... ]
        >>> result = parse_summary_section(blocks, page_height=800)
        >>> result['harga_jual']
        1102500.0
        >>> result['dpp']
        1010625.0
    """
    result: Dict[str, float] = {
        'harga_jual': 0.0,
        'potongan': 0.0,
        'uang_muka': 0.0,
        'dpp': 0.0,
        'ppn': 0.0,
        'ppnbm': 0.0,
    }

    if not text_blocks:
        logger.warning("No text blocks provided for summary parsing")
        return result

    # ---- Step 1: Filter to summary area (bottom 60%+ of page) ----
    summary_y_threshold = page_height * 0.40  # Start looking from 40% down
    summary_blocks = [
        b for b in text_blocks if b.get('y', 0) >= summary_y_threshold
    ]

    if not summary_blocks:
        logger.warning(
            f"No text blocks in summary area (y >= {summary_y_threshold:.0f}). "
            f"Falling back to full page."
        )
        summary_blocks = text_blocks

    # ---- Step 2: Group blocks into rows by Y proximity ----
    rows = _group_blocks_by_row(summary_blocks, y_tolerance=12)

    # ---- Step 3: Try coordinate-based extraction first ----
    for field_name, patterns in SUMMARY_LABELS.items():
        value = _find_label_value_in_rows(rows, patterns, field_name)
        if value is not None and value > 0:
            result_key = field_name
            result[result_key] = value

    # ---- Step 4: Fallback — reconstruct text and use regex ----
    if result['dpp'] == 0.0 and result['ppn'] == 0.0:
        logger.debug("Coordinate-based extraction found no DPP/PPN, trying text fallback")
        full_text = _reconstruct_text_from_blocks(summary_blocks)
        fallback = _parse_summary_from_text(full_text)
        for key, value in fallback.items():
            if result.get(key, 0.0) == 0.0 and value > 0:
                result[key] = value

    # ---- Step 5: Validate and fix DPP/PPN swap ----
    if result['dpp'] > 0 and result['ppn'] > 0 and result['ppn'] > result['dpp']:
        logger.warning(
            f"DPP/PPN swap detected: PPN ({result['ppn']:,.0f}) > DPP ({result['dpp']:,.0f}). Swapping."
        )
        result['dpp'], result['ppn'] = result['ppn'], result['dpp']

    logger.info(
        f"Summary parsed: " +
        ", ".join(f"{k}={v:,.2f}" for k, v in result.items())
    )
    return result


def parse_summary_from_full_text(ocr_text: str) -> Dict[str, float]:
    """
    Parse summary section from plain OCR text (no coordinates).

    Convenience wrapper for when only text is available (no bounding boxes).
    Uses line-by-line regex matching to find label-value pairs.

    Args:
        ocr_text: Raw OCR text containing the summary section.

    Returns:
        Summary dictionary with float values.

    Example::

        >>> text = '''
        ... Harga Jual / Penggantian / Uang Muka / Termin    1.102.500,00
        ... Dasar Pengenaan Pajak                            1.010.625,00
        ... Jumlah PPN (Pajak Pertambahan Nilai)               121.275,00
        ... '''
        >>> result = parse_summary_from_full_text(text)
        >>> result['dpp']
        1010625.0
    """
    return _parse_summary_from_text(ocr_text)


# =============================================================================
# BONUS: VALIDATION FUNCTION
# =============================================================================

def validate_parsed_data(
    items: List[Dict],
    summary: Dict,
    tax_rate: float = 0.12,
    tolerance_pct: float = 0.01,
) -> Dict[str, Any]:
    """
    Cross-check parsed item data against summary totals for consistency.

    Validates that:
        1. At least 1 item was parsed.
        2. No items have zero ``harga_jual``.
        3. Sum of item ``harga_jual`` equals summary ``harga_jual`` (within tolerance).
        4. PPN ≈ DPP × tax_rate (within tolerance).

    Args:
        items: List of parsed line items (each with ``harga_jual`` key).
        summary: Parsed summary dictionary with ``harga_jual``, ``dpp``, ``ppn``.
        tax_rate: Expected PPN tax rate (default 0.12 = 12% for 2025+).
        tolerance_pct: Allowed deviation as fraction (default 0.01 = 1%).

    Returns:
        Validation result::

            {
                'is_valid': bool,
                'errors': List[str],
                'warnings': List[str],
                'checks': {
                    'items_count_ok': bool,
                    'no_zero_values': bool,
                    'items_sum_matches': bool,
                    'ppn_calculation_ok': bool,
                },
            }

    Example::

        >>> items = [
        ...     {'harga_jual': 360500},
        ...     {'harga_jual': 380000},
        ...     {'harga_jual': 54000},
        ...     {'harga_jual': 228000},
        ...     {'harga_jual': 80000},
        ... ]
        >>> summary = {'harga_jual': 1102500, 'dpp': 1010625, 'ppn': 121275}
        >>> result = validate_parsed_data(items, summary)
        >>> result['is_valid']
        True
    """
    items = items or []
    summary = summary or {}

    errors: List[str] = []
    warnings: List[str] = []
    checks = {
        'items_count_ok': False,
        'no_zero_values': False,
        'items_sum_matches': False,
        'ppn_calculation_ok': False,
    }

    # ---- Check 1: At least 1 item ----
    if len(items) == 0:
        errors.append("No line items parsed from invoice")
    else:
        checks['items_count_ok'] = True

    # ---- Check 2: No zero harga_jual ----
    zero_items = [
        i for i, item in enumerate(items, 1)
        if float(item.get('harga_jual', 0) or 0) == 0
    ]
    if zero_items:
        # Zero harga_jual is a warning (possible qty=0), not a fatal error
        warnings.append(
            f"{len(zero_items)} item(s) with zero harga_jual: line(s) {zero_items}"
        )
    else:
        checks['no_zero_values'] = True

    # ---- Check 3: Items sum matches summary harga_jual ----
    summary_hj = float(summary.get('harga_jual', 0) or 0)
    items_sum = sum(float(item.get('harga_jual', 0) or 0) for item in items)

    if summary_hj > 0:
        hj_diff = abs(items_sum - summary_hj)
        hj_tolerance = summary_hj * tolerance_pct

        if hj_diff <= hj_tolerance:
            checks['items_sum_matches'] = True
        else:
            errors.append(
                f"Harga Jual sum mismatch: items total {items_sum:,.0f} vs "
                f"summary {summary_hj:,.0f} (diff={hj_diff:,.0f}, "
                f"tolerance={hj_tolerance:,.0f})"
            )
    elif items_sum > 0:
        warnings.append(
            f"Summary harga_jual is 0 but items total {items_sum:,.0f}"
        )
        checks['items_sum_matches'] = True  # Can't validate without summary

    # ---- Check 4: PPN ≈ DPP × tax_rate ----
    summary_dpp = float(summary.get('dpp', 0) or 0)
    summary_ppn = float(summary.get('ppn', 0) or 0)

    if summary_dpp > 0 and summary_ppn > 0:
        expected_ppn = summary_dpp * tax_rate
        ppn_diff = abs(summary_ppn - expected_ppn)
        ppn_tolerance = expected_ppn * tolerance_pct

        if ppn_diff <= ppn_tolerance:
            checks['ppn_calculation_ok'] = True
        else:
            actual_rate = summary_ppn / summary_dpp
            warnings.append(
                f"PPN rate mismatch: expected {expected_ppn:,.0f} "
                f"({tax_rate*100:.0f}% of DPP), got {summary_ppn:,.0f} "
                f"(actual rate: {actual_rate*100:.1f}%)"
            )
            # Try common alternative rates
            for alt_rate in [0.11, 0.12, 0.10]:
                alt_expected = summary_dpp * alt_rate
                if abs(summary_ppn - alt_expected) <= alt_expected * tolerance_pct:
                    checks['ppn_calculation_ok'] = True
                    warnings.append(
                        f"PPN matches {alt_rate*100:.0f}% rate instead of "
                        f"{tax_rate*100:.0f}%"
                    )
                    break
    elif summary_dpp > 0 and summary_ppn == 0:
        warnings.append("PPN is zero — possibly a zero-rated transaction")
        checks['ppn_calculation_ok'] = True  # Acceptable edge case
    elif summary_dpp == 0 and summary_ppn == 0:
        warnings.append("Both DPP and PPN are zero — cannot validate tax calculation")

    # ---- Final result ----
    is_valid = len(errors) == 0

    result = {
        'is_valid': is_valid,
        'errors': errors,
        'warnings': warnings,
        'checks': checks,
    }

    logger.info(
        f"Validation: valid={is_valid}, errors={len(errors)}, warnings={len(warnings)}, "
        f"checks={checks}"
    )

    return result


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _group_blocks_by_row(
    blocks: List[Dict],
    y_tolerance: float = 12,
) -> List[Tuple[float, List[Dict]]]:
    """
    Group text blocks into rows by Y-coordinate proximity.

    Blocks with Y coordinates within ``y_tolerance`` pixels of each other
    are grouped into the same row.

    Args:
        blocks: Text blocks sorted by Y position.
        y_tolerance: Maximum Y difference for same-row grouping.

    Returns:
        List of (y_center, blocks_in_row) tuples, sorted top to bottom.
    """
    if not blocks:
        return []

    sorted_blocks = sorted(blocks, key=lambda b: (b.get('y', 0), b.get('x', 0)))
    rows: List[Tuple[float, List[Dict]]] = []
    current_y = sorted_blocks[0].get('y', 0)
    current_row: List[Dict] = [sorted_blocks[0]]

    for block in sorted_blocks[1:]:
        block_y = block.get('y', 0)
        if abs(block_y - current_y) <= y_tolerance:
            current_row.append(block)
        else:
            avg_y = sum(b.get('y', 0) for b in current_row) / len(current_row)
            rows.append((avg_y, current_row))
            current_y = block_y
            current_row = [block]

    if current_row:
        avg_y = sum(b.get('y', 0) for b in current_row) / len(current_row)
        rows.append((avg_y, current_row))

    return rows


def _find_label_value_in_rows(
    rows: List[Tuple[float, List[Dict]]],
    patterns: List[re.Pattern],
    field_name: str,
) -> Optional[float]:
    """
    Find a summary label in rows and extract its corresponding value.

    For each row, concatenates left-side text and checks against label
    patterns. When matched, looks for a numeric value on the right side
    of the same row, or in the row directly below.

    Args:
        rows: Grouped rows from ``_group_blocks_by_row``.
        patterns: List of compiled regex patterns for the label.
        field_name: Field name for logging.

    Returns:
        Parsed float or None if not found.
    """
    for row_idx, (row_y, row_blocks) in enumerate(rows):
        # Sort blocks in row by X (left to right)
        sorted_by_x = sorted(row_blocks, key=lambda b: b.get('x', 0))

        # Reconstruct full row text
        row_text = ' '.join(str(b.get('text', '')) for b in sorted_by_x)

        # Check if any label pattern matches
        matched = False
        for pattern in patterns:
            if pattern.search(row_text):
                matched = True
                break

        if not matched:
            continue

        # Found label — now find the value
        # Strategy A: rightmost numeric block in same row
        for block in reversed(sorted_by_x):
            block_text = str(block.get('text', '')).strip()
            if AMOUNT_PATTERN.fullmatch(block_text):
                value = parse_indonesian_number(block_text)
                if value >= 0:
                    logger.debug(
                        f"Found {field_name} in same row: {value:,.2f} "
                        f"(text='{block_text}', y={row_y:.1f})"
                    )
                    return value

        # Strategy A2: extract amount from the row text itself
        amounts = AMOUNT_PATTERN.findall(row_text)
        if amounts:
            # Take the last amount in the row text
            value = parse_indonesian_number(amounts[-1])
            if value >= 0:
                logger.debug(
                    f"Found {field_name} from row text: {value:,.2f} "
                    f"(row_text='{row_text[:60]}', y={row_y:.1f})"
                )
                return value

        # Strategy B: value in row below
        if row_idx + 1 < len(rows):
            next_y, next_blocks = rows[row_idx + 1]
            # Only check if next row is close (within ~40px)
            if abs(next_y - row_y) <= 40:
                sorted_next = sorted(next_blocks, key=lambda b: b.get('x', 0))
                for block in reversed(sorted_next):
                    block_text = str(block.get('text', '')).strip()
                    if AMOUNT_PATTERN.fullmatch(block_text):
                        value = parse_indonesian_number(block_text)
                        if value >= 0:
                            logger.debug(
                                f"Found {field_name} in next row: {value:,.2f} "
                                f"(text='{block_text}', y={next_y:.1f})"
                            )
                            return value

        logger.debug(f"Label found for {field_name} at y={row_y:.1f} but no value extracted")
        return 0.0  # Label found but value is 0 or missing

    return None  # Label not found at all


def _reconstruct_text_from_blocks(blocks: List[Dict]) -> str:
    """
    Reconstruct text from blocks, grouping by Y position into lines.

    Args:
        blocks: Text blocks with 'text', 'x', 'y'.

    Returns:
        Multi-line string with blocks on the same Y grouped into one line.
    """
    if not blocks:
        return ""

    rows = _group_blocks_by_row(blocks, y_tolerance=12)
    lines = []
    for _, row_blocks in rows:
        sorted_by_x = sorted(row_blocks, key=lambda b: b.get('x', 0))
        line = ' '.join(str(b.get('text', '')).strip() for b in sorted_by_x)
        lines.append(line)

    return '\n'.join(lines)


def _parse_summary_from_text(ocr_text: str) -> Dict[str, float]:
    """
    Parse summary values from plain OCR text using line-by-line regex.

    This is the fallback when coordinate-based parsing doesn't find values.
    It matches label patterns line-by-line and extracts the amount from
    the same line or the next line.

    Args:
        ocr_text: The full OCR text.

    Returns:
        Summary dictionary with float values.
    """
    result: Dict[str, float] = {
        'harga_jual': 0.0,
        'potongan': 0.0,
        'uang_muka': 0.0,
        'dpp': 0.0,
        'ppn': 0.0,
        'ppnbm': 0.0,
    }

    if not ocr_text:
        return result

    lines = ocr_text.split('\n')

    for field_name, patterns in SUMMARY_LABELS.items():
        for pattern in patterns:
            found = False
            for idx, line in enumerate(lines):
                match = pattern.search(line)
                if not match:
                    continue

                # Strategy 1: amount on same line (after label)
                text_after = line[match.end():].strip()
                if text_after:
                    amount_match = AMOUNT_PATTERN.search(text_after)
                    if amount_match:
                        value = parse_indonesian_number(amount_match.group(0))
                        if value >= 0:
                            result[field_name] = value
                            found = True
                            break

                # Also try the full line for amounts
                all_amounts = AMOUNT_PATTERN.findall(line)
                if all_amounts:
                    value = parse_indonesian_number(all_amounts[-1])
                    if value >= 0:
                        result[field_name] = value
                        found = True
                        break

                # Strategy 2: amount on next non-empty line
                for next_idx in range(idx + 1, min(idx + 3, len(lines))):
                    next_line = lines[next_idx].strip()
                    if not next_line:
                        continue
                    amount_match = AMOUNT_PATTERN.search(next_line)
                    if amount_match:
                        value = parse_indonesian_number(amount_match.group(0))
                        if value >= 0:
                            result[field_name] = value
                            found = True
                            break
                    break  # Only check first non-empty line

                if found:
                    break
            if found:
                break

    return result


# =============================================================================
# INTEGRATED PIPELINE: FULL MULTIROW PARSING
# =============================================================================

def parse_tax_invoice_multirow(
    vision_json: Optional[Dict] = None,
    text_blocks: Optional[List[Dict]] = None,
    page_height: float = 800.0,
    tax_rate: float = 0.12,
) -> Dict[str, Any]:
    """
    Full multirow parsing pipeline for Indonesian tax invoices (Faktur Pajak).

    Chains the 3 critical fixes into a complete pipeline:

    1. Convert Vision JSON to text blocks (if not provided directly).
    2. Group multi-row OCR lines into single items (**Fix #2**).
    3. Parse summary section with regex (**Fix #1**).
    4. Cross-validate items vs summary (**Fix #3**).

    This function can be used as:
      - A **standalone parser** for Vision JSON OCR data.
      - A **fallback pipeline** when the primary token-based parser
        (``faktur_pajak_parser.parse_invoice()``) produces invalid results.
      - A **cross-validation tool** to verify primary parser output.

    Args:
        vision_json: Google Vision API response dict. Either this or
                     ``text_blocks`` must be provided.
        text_blocks: Pre-built text blocks with ``text``, ``x``, ``y`` keys.
                     If provided, ``vision_json`` is ignored.
        page_height: Page height in pixels (used for summary area detection).
                     Auto-detected from Vision JSON if not provided.
        tax_rate: Expected PPN tax rate (default 0.12 = 12% for 2025+).

    Returns:
        Dictionary with::

            {
                'items': List[Dict],          # Parsed line items
                'summary': Dict[str, float],  # Summary values (harga_jual, dpp, ppn, ...)
                'validation': Dict,           # Validation result
                'success': bool,              # True if pipeline completed
                'errors': List[str],          # Any errors encountered
            }

    Example::

        >>> result = parse_tax_invoice_multirow(vision_json=vj)
        >>> result['summary']['harga_jual']
        1102500.0
        >>> result['validation']['is_valid']
        True
        >>> len(result['items'])
        5
    """
    result: Dict[str, Any] = {
        'items': [],
        'summary': {},
        'validation': {},
        'success': False,
        'errors': [],
    }

    try:
        # Step 1: Get text blocks
        if text_blocks is None and vision_json is not None:
            text_blocks, page_height = vision_json_to_text_blocks(vision_json)
        elif text_blocks is None:
            result['errors'].append('No input data: provide vision_json or text_blocks')
            return result

        if not text_blocks:
            result['errors'].append('No text blocks extracted from input')
            return result

        logger.info(
            f"Multirow pipeline: {len(text_blocks)} text blocks, "
            f"page_height={page_height:.0f}"
        )

        # Step 2: Group multi-row items and parse them (Fix #2)
        grouped_items = group_multirow_items(text_blocks)
        items = [parse_grouped_item(group) for group in grouped_items]

        # Filter items with no description and no value (noise)
        items = [
            item for item in items
            if item.get('description') or item.get('harga_jual', 0) > 0
        ]

        logger.info(
            f"Multirow pipeline: {len(grouped_items)} groups → "
            f"{len(items)} valid items"
        )

        # Step 3: Parse summary section with regex (Fix #1)
        summary = parse_summary_section(text_blocks, page_height)

        logger.info(
            f"Multirow pipeline: summary harga_jual={summary.get('harga_jual', 0):,.0f}, "
            f"dpp={summary.get('dpp', 0):,.0f}, ppn={summary.get('ppn', 0):,.0f}"
        )

        # Step 4: Cross-validate (Fix #3)
        validation = validate_parsed_data(items, summary, tax_rate=tax_rate)

        result['items'] = items
        result['summary'] = summary
        result['validation'] = validation
        result['success'] = True

        if not validation['is_valid']:
            for error in validation['errors']:
                logger.warning(f"Multirow validation issue: {error}")
        else:
            logger.info(
                f"Multirow pipeline: VALIDATED OK — "
                f"{len(items)} items, sum={sum(i.get('harga_jual', 0) for i in items):,.0f}"
            )

    except Exception as e:
        error_msg = f'Multirow parsing failed: {str(e)}'
        result['errors'].append(error_msg)
        logger.error(error_msg)

    return result
