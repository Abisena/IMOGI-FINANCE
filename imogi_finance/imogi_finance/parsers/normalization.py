# -*- coding: utf-8 -*-
# Copyright (c) 2026, Imogi Finance and contributors
# For license information, please see license.txt

"""
Normalization utilities for Indonesian tax invoice data.

Handles Indonesian number formats, description cleaning, and OCR corrections.
"""

import re
from typing import Optional

import frappe


def normalize_indonesian_number(text: str) -> Optional[float]:
	"""
	Convert Indonesian number format to float.

	Indonesian format:
		- Thousand separator: . (dot)
		- Decimal separator: , (comma)
		- Example: "1.234.567,89" -> 1234567.89

	Also handles:
		- Split tokens: "1 234 567,89"
		- OCR errors: O->0, I->1 in numeric context
		- Extra whitespace

	Args:
		text: String representation of number

	Returns:
		Float value or None if not parseable
	"""
	if not text or not isinstance(text, str):
		return None

	# Strip whitespace
	text = text.strip()

	# Remove thousand separators (dots) ONLY if followed by 3 digits or comma
	# This prevents removing decimal points in non-Indonesian formats
	text = re.sub(r'\.(?=\d{3}(?:\.|,|$))', '', text)

	# Remove spaces between digits (handle split tokens)
	text = re.sub(r'(\d)\s+(\d)', r'\1\2', text)

	# Fix common OCR errors in numeric context
	# O -> 0 when surrounded by digits
	text = re.sub(r'(?<=\d)O(?=\d)', '0', text)
	text = re.sub(r'(?<=\d)o(?=\d)', '0', text)
	# I -> 1 when surrounded by digits
	text = re.sub(r'(?<=\d)I(?=\d)', '1', text)
	text = re.sub(r'(?<=\d)l(?=\d)', '1', text)

	# Convert decimal comma to dot
	text = text.replace(',', '.')

	# Remove any remaining non-numeric characters except decimal point
	text = re.sub(r'[^\d\.]', '', text)

	# Try to convert to float
	try:
		value = float(text)

		# Sanity check: tax invoice amounts should be positive
		if value < 0:
			return None

		return value
	except (ValueError, TypeError):
		return None


def clean_description(text: str) -> str:
	"""
	Clean and normalize item description text.

	Operations:
		- Remove reference lines (Referensi:, Invoice:, INV-)
		- Merge multiple whitespaces
		- Strip leading/trailing whitespace
		- Preserve original casing (for part numbers, codes, etc.)

	Args:
		text: Raw description text

	Returns:
		Cleaned description string
	"""
	if not text or not isinstance(text, str):
		return ""

	# Remove reference patterns
	# Pattern: Referensi: <anything> or Invoice: <anything> or INV-<digits>
	reference_patterns = [
		r'Referensi\s*:\s*[^\n]*',
		r'Invoice\s*:\s*[^\n]*',
		r'INV-\d+[^\s]*',
		r'Ref\s*:\s*[^\n]*',
		r'No\.\s*Ref\s*:\s*[^\n]*'
	]

	for pattern in reference_patterns:
		text = re.sub(pattern, '', text, flags=re.IGNORECASE)

	# Merge multiple whitespaces/newlines into single space
	text = re.sub(r'\s+', ' ', text)

	# Strip leading/trailing whitespace
	text = text.strip()

	# DO NOT apply title case - preserves part numbers, model codes, etc.
	return text


def extract_npwp(text: str) -> Optional[str]:
	"""
	Extract and normalize NPWP (Indonesian Tax ID).

	NPWP format: XX.XXX.XXX.X-XXX.XXX (15 digits)

	Args:
		text: Text containing NPWP

	Returns:
		Normalized NPWP (digits only) or None
	"""
	if not text or not isinstance(text, str):
		return None

	# Remove dots, dashes, spaces
	npwp = re.sub(r'[.\-\s]', '', text)

	# Check if it's 15 digits
	if re.match(r'^\d{15}$', npwp):
		return npwp

	# Try to find 15-digit sequence in text
	match = re.search(r'\d{15}', text)
	if match:
		return match.group(0)

	return None


def normalize_line_item(item: dict) -> dict:
	"""
	Normalize all fields in a line item dictionary.

	Args:
		item: Dictionary with raw values (raw_harga_jual, raw_dpp, raw_ppn, description)

	Returns:
		Updated dictionary with normalized values
	"""
	# Normalize numeric fields
	if "raw_harga_jual" in item:
		item["harga_jual"] = normalize_indonesian_number(item["raw_harga_jual"])

	if "raw_dpp" in item:
		item["dpp"] = normalize_indonesian_number(item["raw_dpp"])

	if "raw_ppn" in item:
		item["ppn"] = normalize_indonesian_number(item["raw_ppn"])

	# Clean description
	if "description" in item:
		item["description"] = clean_description(item["description"])

	return item


def normalize_all_items(items: list) -> list:
	"""
	Normalize all items in a list.

	Args:
		items: List of item dictionaries

	Returns:
		List of normalized items
	"""
	return [normalize_line_item(item) for item in items]


# =============================================================================
# 🔥 INCLUSIVE VAT DETECTION & HANDLING (PHASE 1 FIX)
# =============================================================================
# Indonesian invoices often have amounts that INCLUDE VAT (Harga Jual includes 11% PPN).
# This module detects this pattern and auto-corrects DPP calculations.

def find_decimal_separator(text: str) -> tuple:
	"""
	Intelligently detect comma vs period as decimal separator in Indonesian format.

	Rules:
	- If text has both comma and period: rightmost is decimal, others are thousand separators
	- If text has only comma: likely decimal (no thousand separator used)
	- If text has only period: likely thousand separator OR decimal (needs context)
	- Returns tuple of (thousand_sep, decimal_sep)

	Examples:
		"1.234.567,89" -> (".", ",")
		"1234567,89" -> (None, ",")
		"1234567.89" -> (None, ".")  # Ambiguous, assume period is decimal
		"1,000.00" -> (",", ".")  # Already formatted (US style)

	Args:
		text: Number string possibly with separators

	Returns:
		Tuple of (thousand_separator, decimal_separator) or (None, None) if ambiguous
	"""
	text = text.strip()

	# Count occurrences
	comma_count = text.count(',')
	period_count = text.count('.')

	# No separators - ambiguous
	if comma_count == 0 and period_count == 0:
		return None, None

	# Both present - rightmost is decimal, rest are thousand seps
	if comma_count > 0 and period_count > 0:
		comma_idx = text.rfind(',')
		period_idx = text.rfind('.')

		if comma_idx > period_idx:
			return ".", ","	# Indonesian format
		else:
			return ",", "."	# US format

	# Only comma - likely decimal
	if comma_count == 1 and period_count == 0:
		# Check if comma is in rightmost 3 positions (like "1234,56")
		comma_idx = text.find(',')
		digits_after = len(text) - comma_idx - 1
		if digits_after <= 3:
			return None, ","
		# Otherwise it's a thousands separator (unusual but possible)
		return ",", None

	# Only period - ambiguous, but assume decimal if rightmost
	if period_count == 1 and comma_count == 0:
		# If period is in rightmost 3 positions, likely decimal
		period_idx = text.rfind('.')
		digits_after = len(text) - period_idx - 1
		if digits_after <= 3:
			return None, "."
		# Otherwise assume thousand separator (Indonesian style)
		return ".", None

	# Multiple commas or periods - assume Indonesian format
	if comma_count > 1 or period_count > 1:
		# Find rightmost comma/period
		comma_idx = text.rfind(',')
		period_idx = text.rfind('.')

		if comma_idx > period_idx:
			return ".", ","
		else:
			return ",", "."

	return None, None


def validate_number_format(original_text: str, parsed_value: Optional[float]) -> dict:
	"""
	Validate that parsed number makes sense in context.

	Checks:
	- If original has obvious structure (thousand separators), parsed value should be large
	- If parsing resulted in unusual magnitude change, flag as suspicious
	- Detect OCR artifacts (missing digits, wrong separators)

	Args:
		original_text: Raw text from OCR
		parsed_value: Result from normalize_indonesian_number()

	Returns:
		Dictionary with:
			- is_valid: Boolean (True if format seems reasonable)
			- confidence: Float (0.0-1.0)
			- message: String explaining the validation
			- suggestions: List of alternative interpretations if suspicious
	"""
	if not original_text or parsed_value is None:
		return {
			"is_valid": False,
			"confidence": 0.0,
			"message": "Missing input or parse failure",
			"suggestions": []
		}

	# Extract digit count from original to estimate magnitude
	digit_count = len(re.sub(r'\D', '', original_text))

	# Expected magnitude based on structure
	# If text has commas/periods, it's likely a multi-digit number
	if ',' in original_text or '.' in original_text:
		# Should have at least 4-5 digits (thousand+ IDR)
		if digit_count < 4:
			return {
				"is_valid": False,
				"confidence": 0.3,
				"message": f"Unusual: Text has separators but only {digit_count} digits",
				"suggestions": [
					"Check OCR output for missing digits",
					"Original text may be misread quantity, not amount"
				]
			}

		# Sanity check: if number of digits suggests million/billion, parsed value shouldn't be tiny
		if digit_count >= 7 and parsed_value < 100000:  # 7+ digits but < 100k
			return {
				"is_valid": False,
				"confidence": 0.2,
				"message": f"Parsing error: {digit_count} digits but only Rp {parsed_value:,.0f}",
				"suggestions": [
					"Decimal separator may be incorrect",
					"Try swapping comma/period interpretation"
				]
			}

	# Check for reasonable magnitude (tax invoice amounts are usually 10k - 10 billion IDR)
	if parsed_value < 1000:
		return {
			"is_valid": False,
			"confidence": 0.5,
			"message": f"Very small amount (Rp {parsed_value:,.0f})",
			"suggestions": ["May be OCR error or receipt, not invoice"]
		}

	if parsed_value > 100_000_000_000:  # 100 billion
		return {
			"is_valid": False,
			"confidence": 0.4,
			"message": f"Very large amount (Rp {parsed_value:,.0f}) - may be OCR error",
			"suggestions": ["Check digit count and separator placement"]
		}

	# All checks passed
	return {
		"is_valid": True,
		"confidence": 0.95,
		"message": f"Valid amount: Rp {parsed_value:,.0f}",
		"suggestions": []
	}


# =============================================================================
# 🔥 INCLUSIVE VAT DETECTION & HANDLING
# =============================================================================


def detect_vat_inclusivity(
	harga_jual: Optional[float],
	dpp: Optional[float],
	ppn: Optional[float],
	tax_rate: float = 0.11,
	tolerance_percentage: float = 0.02
) -> dict:
	"""
	Detect if invoice amounts suggest Harga Jual includes VAT (inclusive VAT).

	Common in Indonesian invoices: Harga_Jual = DPP × (1 + tax_rate)

	Detection Logic:
	1. If Harga_Jual ≈ DPP × (1 + tax_rate), amounts are INCLUSIVE
	2. If Harga_Jual ≈ DPP (or DPP+PPN), amounts are EXCLUSIVE

	Args:
		harga_jual: Selling price (may include VAT)
		dpp: Tax base amount
		ppn: Tax amount
		tax_rate: PPN tax rate (default 0.11 = 11%)
		tolerance_percentage: Percentage tolerance (default 0.02 = 2%)

	Returns:
		Dictionary with:
			- is_inclusive: bool, True if amounts appear to be inclusive VAT
			- reason: str, Explanation of detection logic
			- expected_dpp: float, What DPP should be if inclusive
			- expected_ppn: float, What PPN should be if inclusive
			- confidence: float, 0-1.0 confidence score
			- original_amounts: dict, Debug info with original values

	Example:
		>>> detect_vat_inclusivity(harga_jual=1232100, dpp=1111000, ppn=121100)
		{'is_inclusive': True, 'confidence': 0.95, ...}

		>>> detect_vat_inclusivity(harga_jual=1000000, dpp=1000000, ppn=110000)
		{'is_inclusive': False, 'confidence': 0.85, ...}
	"""
	if not all([harga_jual, dpp, ppn]):
		return {
			"is_inclusive": False,
			"reason": "Missing required amounts (harga_jual, dpp, ppn)",
			"confidence": 0.0,
			"expected_dpp": None,
			"expected_ppn": None,
			"original_amounts": {"harga_jual": harga_jual, "dpp": dpp, "ppn": ppn}
		}

	# Calculate what DPP/PPN would be if Harga Jual is INCLUSIVE
	expected_dpp_inclusive = harga_jual / (1 + tax_rate)
	expected_ppn_inclusive = expected_dpp_inclusive * tax_rate

	# Calculate what Harga Jual would be if DPP/PPN are EXCLUSIVE
	expected_harga_jual_exclusive = dpp + ppn

	# Check INCLUSIVE scenario: Harga_Jual ≈ DPP × (1 + tax_rate)
	# This is the most common case in Indonesian invoices
	inclusive_match_dpp = abs(dpp - expected_dpp_inclusive) <= (expected_dpp_inclusive * tolerance_percentage)
	inclusive_match_ppn = abs(ppn - expected_ppn_inclusive) <= (expected_ppn_inclusive * tolerance_percentage) if expected_ppn_inclusive > 0 else False

	# Check EXCLUSIVE scenario: Harga_Jual ≈ DPP + PPN
	exclusive_match = abs(harga_jual - expected_harga_jual_exclusive) <= (expected_harga_jual_exclusive * tolerance_percentage)

	# Decision logic
	is_inclusive = (inclusive_match_dpp and inclusive_match_ppn) and not exclusive_match

	if is_inclusive:
		confidence = 0.95 if (inclusive_match_dpp and inclusive_match_ppn) else 0.80
		reason = f"Harga Jual ({harga_jual:,.0f}) ≈ DPP ({dpp:,.0f}) × {1+tax_rate:.4f}, indicating inclusive VAT"
	else:
		confidence = 0.85 if exclusive_match else 0.50
		reason = "Amounts appear to be exclusive (Harga Jual ≈ DPP reported values are not indicative of inclusive VAT)"

	return {
		"is_inclusive": is_inclusive,
		"reason": reason,
		"expected_dpp": round(expected_dpp_inclusive, 2),
		"expected_ppn": round(expected_ppn_inclusive, 2),
		"confidence": confidence,
		"original_amounts": {
			"harga_jual": harga_jual,
			"dpp": dpp,
			"ppn": ppn,
			"expected_harga_jual_exclusive": round(expected_harga_jual_exclusive, 2)
		}
	}


def recalculate_dpp_from_inclusive(
	harga_jual: float,
	tax_rate: float = 0.11
) -> dict:
	"""
	Recalculate DPP and PPN from INCLUSIVE Harga Jual amount.

	Formula:
		DPP = Harga Jual / (1 + tax_rate)
		PPN = DPP × tax_rate

	Args:
		harga_jual: Total amount INCLUDING VAT
		tax_rate: PPN tax rate (default 0.11)

	Returns:
		Dictionary with:
			- dpp: Calculated tax base
			- ppn: Calculated tax amount
			- harga_jual_original: Input value
			- calculation_note: Explanation for logging

	Example:
		>>> recalculate_dpp_from_inclusive(1232100)
		{'dpp': 1111000.0, 'ppn': 122100.0, ...}
	"""
	dpp = harga_jual / (1 + tax_rate)
	ppn = dpp * tax_rate

	return {
		"dpp": round(dpp, 2),
		"ppn": round(ppn, 2),
		"harga_jual_original": harga_jual,
		"calculation_note": f"DPP recalculated from inclusive Harga Jual using formula: DPP = Total / (1 + {tax_rate:.2%})"
	}


# Compatibility with existing tax_invoice_ocr.py
def parse_idr_amount(amount_str: str) -> Optional[float]:
	"""
	Wrapper for backward compatibility with existing codebase.

	Delegates to normalize_indonesian_number.
	"""
	return normalize_indonesian_number(amount_str)
