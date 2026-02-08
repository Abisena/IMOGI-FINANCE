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


# Compatibility with existing tax_invoice_ocr.py
def parse_idr_amount(amount_str: str) -> Optional[float]:
	"""
	Wrapper for backward compatibility with existing codebase.
	
	Delegates to normalize_indonesian_number.
	"""
	return normalize_indonesian_number(amount_str)
