# -*- coding: utf-8 -*-
# Copyright (c) 2026, Imogi Finance and contributors
# For license information, please see license.txt

"""
Parsers module for Tax Invoice OCR processing.
"""

from .layout_aware_parser import (  # noqa: F401
    BoundingBox,
    OCRToken,
    LayoutAwareParser,
    validate_summary_amounts,
    process_with_layout_parser,
)

from .multirow_parser import (  # noqa: F401
    group_multirow_items,
    parse_grouped_item,
    parse_summary_section as parse_summary_section_blocks,
    parse_summary_from_full_text,
    is_summary_row,
    validate_parsed_data,
    parse_indonesian_number,
    parse_tax_invoice_multirow,
    vision_json_to_text_blocks,
    tokens_to_text_blocks,
    _resolve_full_text_annotation,  # 🔥 FIX: Export for Vision JSON unwrapping
)
