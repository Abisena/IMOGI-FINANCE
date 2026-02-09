# -*- coding: utf-8 -*-
# Copyright (c) 2026, Imogi Finance and contributors
# For license information, please see license.txt

"""
Validation module for Tax Invoice line items and totals.

Implements per-row and invoice-level validation with auto-approval logic.
"""

import re
from typing import Dict, List, Optional, Tuple
import frappe
from frappe import _
from frappe.utils import flt

from .normalization import normalize_indonesian_number


def get_tolerance_settings(amount: float = None) -> float:
	"""
	Get validation tolerance percentage from Tax Invoice OCR Settings.
	
	ERPNext v15+ Best Practice: Single percentage-based tolerance
	scales fairly for all amount sizes and tax rates (including low-rate PPN like 1.1%).
	
	🔥 NEW: Tiered tolerance for large amounts
	- < 100 million: base tolerance (default 2%)
	- 100M - 500M: base × 1.25 (2.5% max)
	- 500M - 1B: base × 1.5 (3% max)
	- > 1B: base × 2 (4% max, capped at 5%)
	
	Rationale: Large invoices have more rounding errors accumulation
	but absolute IDR tolerance would be unfair to small invoices.
	
	Args:
		amount: Optional amount to scale tolerance (DPP or PPN)
	
	Returns:
		Tolerance as decimal (e.g., 0.02 for 2%)
		
	Example:
		>>> get_tolerance_settings(50_000_000)  # 50M
		0.02  # 2%
		>>> get_tolerance_settings(200_000_000)  # 200M
		0.025  # 2.5%
		>>> get_tolerance_settings(2_000_000_000)  # 2B
		0.05  # 5% (capped)
	"""
	try:
		settings = frappe.get_single("Tax Invoice OCR Settings")
		base_tolerance_pct = flt(settings.get("tolerance_percentage", 2.0))
		base_tolerance = base_tolerance_pct / 100  # Convert to decimal
		
		# If no amount provided, return base tolerance
		if amount is None or amount <= 0:
			return base_tolerance
		
		# Tiered multiplier based on amount
		amount_val = flt(amount)
		
		if amount_val < 100_000_000:  # < 100M
			multiplier = 1.0
		elif amount_val < 500_000_000:  # 100M - 500M
			multiplier = 1.25
		elif amount_val < 1_000_000_000:  # 500M - 1B
			multiplier = 1.5
		else:  # > 1B
			multiplier = 2.0
		
		# Apply multiplier and cap at 5%
		tiered_tolerance = min(base_tolerance * multiplier, 0.05)
		
		# Log if using tiered tolerance
		if multiplier > 1.0:
			frappe.logger().debug(
				f"[TOLERANCE] Amount: {amount_val:,.0f} → "
				f"Base: {base_tolerance_pct:.2f}% × {multiplier} = "
				f"{tiered_tolerance*100:.2f}%"
			)
		
		return tiered_tolerance
		
	except Exception as e:
		frappe.logger().warning(f"[TOLERANCE] Error getting settings: {e}")
		return 0.02  # 2% default (covers low-rate PPN)


def validate_line_item(
	item: Dict,
	tax_rate: float = 0.11,
	tolerance_percentage: float = None,
	vat_inclusivity_context: Optional[Dict] = None
) -> Dict:
	"""
	Validate a single line item and calculate confidence score.

	Checks:
		- VAT inclusivity detection and auto-correction (if applicable)
		- Item code validity
		- PPN ≈ DPP × tax_rate (within tolerance)
		- Harga Jual >= DPP (standard assumption)
		- All numeric values are present and valid

	Args:
		item: Line item dictionary with harga_jual, dpp, ppn
		tax_rate: PPN tax rate (default 0.11 = 11%)
		tolerance_percentage: Relative tolerance as decimal (0.02 = 2%)
		vat_inclusivity_context: Optional dict with VAT inclusivity detection results

	Returns:
		Updated item dict with row_confidence, notes, and validation flags
	"""
	harga_jual = flt(item.get("harga_jual"))
	dpp = flt(item.get("dpp"))
	ppn = flt(item.get("ppn"))
	item_code = item.get("item_code")

	# Get tiered tolerance based on DPP amount
	if tolerance_percentage is None:
		tolerance_percentage = get_tolerance_settings(amount=dpp)

	notes = []
	confidence = 1.0

	# Validate item code if present
	if item_code:
		code_validation = validate_item_code(item_code)
		if not code_validation.get("is_valid"):
			notes.append(f"Item code issue: {code_validation['message']}")
			confidence *= code_validation.get("confidence_penalty", 0.9)

	# Check if all values are present
	if not dpp or not ppn:
		notes.append("Missing DPP or PPN value")
		confidence = 0.3
		item["row_confidence"] = confidence
		item["notes"] = "; ".join(notes)
		item["vat_inclusivity_detected"] = False
		return item

	# Check for VAT inclusivity context (if provided by parser)
	if vat_inclusivity_context and vat_inclusivity_context.get("is_inclusive"):
		notes.append(
			f"VAT Detected as Inclusive: {vat_inclusivity_context.get('reason')}"
		)

	# Calculate expected PPN
	expected_ppn = dpp * tax_rate
	ppn_diff = abs(ppn - expected_ppn)

	# Calculate tolerance (percentage-based, scales with amount)
	max_tolerance = dpp * tolerance_percentage

	# Validate PPN
	if ppn_diff <= max_tolerance:
		# Perfect or within tolerance
		if ppn_diff == 0:
			confidence = 1.0
		else:
			# Scale confidence from 0.95 to 1.0 based on how close to tolerance
			confidence = 0.95 + (0.05 * (1 - ppn_diff / max_tolerance))
	else:
		# Outside tolerance
		notes.append(
			f"PPN mismatch: expected {frappe.utils.fmt_money(expected_ppn, currency='IDR')}, "
			f"got {frappe.utils.fmt_money(ppn, currency='IDR')} "
			f"(diff: {frappe.utils.fmt_money(ppn_diff, currency='IDR')})"
		)
		# Scale confidence from 0.5 to 0.95 based on how far outside tolerance
		excess = ppn_diff - max_tolerance
		if excess > max_tolerance * 2:
			confidence = 0.5  # Very far off
		else:
			confidence = 0.95 - (0.45 * (excess / (max_tolerance * 2)))

	# Validate Harga Jual >= DPP (standard business rule)
	if harga_jual and harga_jual < dpp:
		notes.append(
			f"Harga Jual ({frappe.utils.fmt_money(harga_jual, currency='IDR')}) < "
			f"DPP ({frappe.utils.fmt_money(dpp, currency='IDR')})"
		)
		confidence *= 0.9  # Reduce confidence by 10%

	# Check for suspicious values
	if dpp <= 0 or ppn < 0:
		notes.append("Invalid negative or zero values")
		confidence = 0.4

	# Very large numbers might be OCR errors (e.g., > 1 billion IDR per line)
	if dpp > 1_000_000_000 or ppn > 1_000_000_000:
		notes.append("Unusually large values detected")
		confidence *= 0.9

	# Update item
	item["row_confidence"] = round(confidence, 4)
	item["notes"] = "; ".join(notes) if notes else ""
	item["vat_inclusivity_detected"] = (
		vat_inclusivity_context and vat_inclusivity_context.get("is_inclusive", False)
	)

	return item


def validate_all_line_items(
	items: List[Dict],
	tax_rate: float = 0.11
) -> Tuple[List[Dict], List[Dict]]:
	"""
	Validate all line items in a list.

	Args:
		items: List of line item dictionaries
		tax_rate: PPN tax rate

	Returns:
		Tuple of (validated_items, invalid_items_list)
	"""
	# Note: Each item will get its own tiered tolerance based on its DPP
	# We don't calculate a single tolerance here anymore

	validated_items = []
	invalid_items = []

	for item in items:
		validated_item = validate_line_item(
			item,
			tax_rate=tax_rate,
			tolerance_percentage=None  # Let validate_line_item calculate tiered tolerance
		)
		validated_items.append(validated_item)

		# Track items with low confidence
		if validated_item.get("row_confidence", 0) < 0.85:
			invalid_items.append({
				"line_no": validated_item.get("line_no"),
				"reason": validated_item.get("notes"),
				"confidence": validated_item.get("row_confidence")
			})

	return validated_items, invalid_items


def validate_invoice_totals(
	items: List[Dict],
	header_totals: Dict,
	tolerance_percentage: float = None
) -> Dict:
	"""
	Validate sum of line items against header totals.

	Args:
		items: List of validated line items
		header_totals: Dict with harga_jual, dpp, ppn from invoice header
		tolerance_percentage: Relative tolerance as decimal

	Returns:
		Dictionary with validation results:
			- match: Boolean
			- differences: Dict of field -> delta
			- notes: List of validation messages
	"""
	if tolerance_percentage is None:
		# Use tiered tolerance based on header DPP amount
		header_dpp = flt(header_totals.get("dpp", 0))
		tolerance_percentage = get_tolerance_settings(amount=header_dpp)

	# Calculate sums
	sum_harga_jual = sum(flt(item.get("harga_jual", 0)) for item in items)
	sum_dpp = sum(flt(item.get("dpp", 0)) for item in items)
	sum_ppn = sum(flt(item.get("ppn", 0)) for item in items)

	# Get header values
	header_harga_jual = flt(header_totals.get("harga_jual", 0))
	header_dpp = flt(header_totals.get("dpp", 0))
	header_ppn = flt(header_totals.get("ppn", 0))

	# Calculate differences
	diff_harga_jual = abs(sum_harga_jual - header_harga_jual) if header_harga_jual else 0
	diff_dpp = abs(sum_dpp - header_dpp) if header_dpp else 0
	diff_ppn = abs(sum_ppn - header_ppn) if header_ppn else 0

	notes = []
	match = True

	# Validate each total
	for field, header_val, sum_val, diff in [
		("Harga Jual", header_harga_jual, sum_harga_jual, diff_harga_jual),
		("DPP", header_dpp, sum_dpp, diff_dpp),
		("PPN", header_ppn, sum_ppn, diff_ppn)
	]:
		if header_val == 0:
			continue  # Skip if header value not provided

		# Calculate tolerance (percentage-based)
		max_tolerance = header_val * tolerance_percentage

		if diff > max_tolerance:
			match = False
			notes.append(
				f"{field}: Header {frappe.utils.fmt_money(header_val, currency='IDR')} vs "
				f"Sum {frappe.utils.fmt_money(sum_val, currency='IDR')} "
				f"(diff: {frappe.utils.fmt_money(diff, currency='IDR')})"
			)

	return {
		"match": match,
		"differences": {
			"harga_jual": diff_harga_jual,
			"dpp": diff_dpp,
			"ppn": diff_ppn
		},
		"sums": {
			"harga_jual": sum_harga_jual,
			"dpp": sum_dpp,
			"ppn": sum_ppn
		},
		"notes": notes
	}


def determine_parse_status(
	items: List[Dict],
	invalid_items: List[Dict],
	totals_validation: Dict,
	header_complete: bool = True
) -> str:
	"""
	Determine parse_status based on validation results.

	Auto-approval logic:
		- ALL rows >= 0.95 confidence
		- Totals match within tolerance
		- Header fields complete (fp_no, npwp, date)
		=> "Approved"

	Otherwise: "Needs Review"

	Args:
		items: Validated line items
		invalid_items: List of items with confidence < 0.85
		totals_validation: Results from validate_invoice_totals
		header_complete: Whether header fields are complete

	Returns:
		Parse status string: "Approved" or "Needs Review"
	"""
	# Check if header is complete
	if not header_complete:
		return "Needs Review"

	# Check if any items have low confidence
	if invalid_items:
		return "Needs Review"

	# Check if all items have >= 0.95 confidence
	all_high_confidence = all(
		flt(item.get("row_confidence", 0)) >= 0.95
		for item in items
	)

	if not all_high_confidence:
		return "Needs Review"

	# Check if totals match
	if not totals_validation.get("match"):
		return "Needs Review"

	# All checks passed - auto-approve
	return "Approved"


def generate_validation_summary_html(
	items: List[Dict],
	invalid_items: List[Dict],
	totals_validation: Dict,
	parse_status: str
) -> str:
	"""
	Generate HTML summary for validation_summary field.

	Args:
		items: Validated line items
		invalid_items: Items with confidence < 0.85
		totals_validation: Totals validation results
		parse_status: Current parse status

	Returns:
		HTML string for display
	"""
	html_parts = []

	# Status indicator
	status_color = {
		"Approved": "green",
		"Needs Review": "orange",
		"Parsed": "blue",
		"Draft": "gray"
	}.get(parse_status, "gray")

	html_parts.append(
		f'<div style="padding: 10px; border-left: 4px solid {status_color}; background: #f9f9f9; margin-bottom: 10px;">'
		f'<strong style="color: {status_color}; font-size: 14px;">Status: {parse_status}</strong>'
		f'</div>'
	)

	# Line items summary
	total_items = len(items)
	invalid_count = len(invalid_items)
	valid_count = total_items - invalid_count

	html_parts.append(
		f'<div style="margin-bottom: 10px;">'
		f'<strong>Line Items:</strong> {total_items} total | '
		f'<span style="color: green;">{valid_count} valid</span> | '
		f'<span style="color: red;">{invalid_count} need review</span>'
		f'</div>'
	)

	# Invalid items details
	if invalid_items:
		html_parts.append('<div style="margin-bottom: 10px;"><strong>⚠️ Items Needing Review:</strong><ul>')
		for item in invalid_items[:10]:  # Limit to 10 items
			html_parts.append(
				f'<li>Line {item["line_no"]}: '
				f'Confidence {item["confidence"]:.1%} - {item["reason"]}</li>'
			)
		if len(invalid_items) > 10:
			html_parts.append(f'<li>...and {len(invalid_items) - 10} more items</li>')
		html_parts.append('</ul></div>')

	# Totals validation
	if totals_validation:
		match_icon = "✓" if totals_validation.get("match") else "✗"
		match_color = "green" if totals_validation.get("match") else "red"

		html_parts.append(
			f'<div style="margin-bottom: 10px;">'
			f'<strong>Totals Validation:</strong> '
			f'<span style="color: {match_color}; font-size: 16px;">{match_icon}</span>'
		)

		if not totals_validation.get("match") and totals_validation.get("notes"):
			html_parts.append('<ul style="margin-top: 5px; color: red;">')
			for note in totals_validation["notes"]:
				html_parts.append(f'<li>{note}</li>')
			html_parts.append('</ul>')

		html_parts.append('</div>')

	return "".join(html_parts)

# =============================================================================
# 🔥 ITEM CODE VALIDATION (PHASE 2 FIX)
# =============================================================================

def validate_item_code(code: Optional[str]) -> Dict:
	"""
	Validate item/product code format.

	Business Rules:
		- Default code "000000" is NOT acceptable (indicates missing item code)
		- Empty or None codes are flagged as missing
		- Valid codes: numeric 1-9999999, or alphanumeric patterns
		- Codes with only zeros are flagged as invalid

	Args:
		code: Item code from invoice line

	Returns:
		Dictionary with:
			- is_valid: Boolean
			- message: Explanation of validation result
			- severity: "error" or "warning"
			- confidence_penalty: Float (0.0-1.0) to multiply against row confidence

	Examples:
		>>> validate_item_code("123456")
		{'is_valid': True, 'message': 'Valid numeric code', 'severity': 'ok', ...}

		>>> validate_item_code("000000")
		{'is_valid': False, 'message': 'Default/invalid code', 'severity': 'error', ...}

		>>> validate_item_code(None)
		{'is_valid': False, 'message': 'Missing item code', 'severity': 'warning', ...}
	"""
	if not code or not isinstance(code, str):
		return {
			"is_valid": False,
			"message": "Missing item code",
			"severity": "warning",
			"confidence_penalty": 0.95  # Minor penalty
		}

	code = code.strip()

	# Check for empty after strip
	if not code:
		return {
			"is_valid": False,
			"message": "Empty item code",
			"severity": "warning",
			"confidence_penalty": 0.95
		}

	# Check for default code "000000" or similar (all zeros)
	if re.match(r'^0+$', code):
		return {
			"is_valid": False,
			"message": f"Invalid default code '{code}' (all zeros)",
			"severity": "error",
			"confidence_penalty": 0.5  # Major penalty
		}

	# Check for common invalid patterns
	invalid_patterns = [
		r'^x+$',           # All X's
		r'^[\-\s]+$',      # Only dashes or spaces
		r'^\.+$',          # Only dots
	]

	for pattern in invalid_patterns:
		if re.match(pattern, code, re.IGNORECASE):
			return {
				"is_valid": False,
				"message": f"Invalid code pattern: '{code}'",
				"severity": "error",
				"confidence_penalty": 0.5
			}

	# Valid patterns: numeric, alphanumeric, or codes with standard separators
	# Allow: 123456, ABC123, item-001, ITEM_001
	if re.match(r'^[A-Z0-9\-_]+$', code, re.IGNORECASE):
		return {
			"is_valid": True,
			"message": f"Valid code: '{code}'",
			"severity": "ok",
			"confidence_penalty": 1.0  # No penalty
		}

	# Unknown format - flag as warning but allow
	return {
		"is_valid": False,
		"message": f"Unusual code format: '{code}' (contains special characters)",
		"severity": "warning",
		"confidence_penalty": 0.90  # Mild penalty
	}


def validate_invoice_date(
	invoice_date: Optional[str],
	fiscal_period_start: Optional[str] = None,
	fiscal_period_end: Optional[str] = None
) -> Dict:
	"""
	Validate invoice date against fiscal period (if provided).

	Args:
		invoice_date: Invoice date as string (format: DD-MM-YYYY or YYYY-MM-DD)
		fiscal_period_start: Fiscal period start date (format: YYYY-MM-DD)
		fiscal_period_end: Fiscal period end date (format: YYYY-MM-DD)

	Returns:
		Dictionary with:
			- is_valid: Boolean
			- message: Explanation
			- severity: "ok", "warning", or "error"
			- in_period: Boolean (True if within fiscal period, None if no period provided)
	"""
	from datetime import datetime

	result = {
		"is_valid": True,
		"message": "Invoice date valid",
		"severity": "ok",
		"in_period": None
	}

	# Guard: missing date
	if not invoice_date:
		result["is_valid"] = False
		result["message"] = "Missing invoice date"
		result["severity"] = "error"
		return result

	# Try to parse invoice date
	invoice_dt = None
	for fmt in ["%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"]:
		try:
			invoice_dt = datetime.strptime(invoice_date, fmt)
			break
		except ValueError:
			continue

	if invoice_dt is None:
		result["is_valid"] = False
		result["message"] = f"Cannot parse invoice date: {invoice_date}"
		result["severity"] = "error"
		return result

	# If no fiscal period provided, just validate the date is reasonable
	if not fiscal_period_start or not fiscal_period_end:
		# Check if date is in the future or too old (> 5 years)
		from datetime import timedelta
		today = datetime.now()
		five_years_ago = today.replace(year=today.year - 5)
		future_date = today + timedelta(days=1)

		if invoice_dt > future_date:
			result["is_valid"] = False
			result["message"] = "Invoice date is in the future"
			result["severity"] = "error"
			result["in_period"] = False
		elif invoice_dt < five_years_ago:
			result["is_valid"] = True  # Allow old dates, but warn
			result["message"] = "Invoice date is more than 5 years old"
			result["severity"] = "warning"
			result["in_period"] = False

		return result

	# Parse fiscal period dates
	try:
		period_start_dt = datetime.strptime(fiscal_period_start, "%Y-%m-%d")
		period_end_dt = datetime.strptime(fiscal_period_end, "%Y-%m-%d")
	except ValueError as e:
		result["is_valid"] = False
		result["message"] = f"Cannot parse fiscal period dates: {str(e)}"
		result["severity"] = "warning"
		return result

	# Check if invoice date is within fiscal period
	if invoice_dt >= period_start_dt and invoice_dt <= period_end_dt:
		result["message"] = f"Invoice date {invoice_date} is within fiscal period"
		result["in_period"] = True
	else:
		result["is_valid"] = False
		result["message"] = (
			f"Invoice date {invoice_date} is outside fiscal period "
			f"({fiscal_period_start} to {fiscal_period_end})"
		)
		result["severity"] = "error" if invoice_dt > period_end_dt else "warning"
		result["in_period"] = False

	return result


def validate_line_summation(
	items: List[Dict],
	header_totals: Dict,
	tolerance_percentage: float = None
) -> Dict:
	"""
	Enhanced validation for line-item summation with detailed discrepancy reporting.

	Purpose:
		Validate that sum of line items matches invoice header totals.
		Detects rounding errors and provides detailed diagnostic info.

	Args:
		items: List of validated line items
		header_totals: Dict with harga_jual, dpp, ppn from invoice header
		tolerance_percentage: Relative tolerance (default 2%)

	Returns:
		Dictionary with:
			- is_valid: Boolean
			- match: Boolean (totals match within tolerance)
			- discrepancies: Dict with per-field analysis
			- summary: Human-readable summary
			- suggestions: List of recommended actions
	"""
	if tolerance_percentage is None:
		tolerance_percentage = get_tolerance_settings()

	# Calculate sums
	sum_harga_jual = sum(flt(item.get("harga_jual", 0)) for item in items)
	sum_dpp = sum(flt(item.get("dpp", 0)) for item in items)
	sum_ppn = sum(flt(item.get("ppn", 0)) for item in items)

	# Get header values
	header_harga_jual = flt(header_totals.get("harga_jual", 0))
	header_dpp = flt(header_totals.get("dpp", 0))
	header_ppn = flt(header_totals.get("ppn", 0))

	result = {
		"is_valid": True,
		"match": True,
		"discrepancies": {},
		"summary": "All totals match",
		"suggestions": []
	}

	# Analyze each field
	for field, header_val, sum_val in [
		("harga_jual", header_harga_jual, sum_harga_jual),
		("dpp", header_dpp, sum_dpp),
		("ppn", header_ppn, sum_ppn)
	]:
		if header_val == 0:
			continue

		diff = abs(sum_val - header_val)
		max_tolerance = header_val * tolerance_percentage

		discrepancy = {
			"header_value": header_val,
			"line_sum": sum_val,
			"difference": diff,
			"difference_percentage": (diff / header_val * 100) if header_val else 0,
			"tolerance": max_tolerance,
			"within_tolerance": diff <= max_tolerance
		}

		result["discrepancies"][field] = discrepancy

		if not discrepancy["within_tolerance"]:
			result["match"] = False
			result["is_valid"] = False
			result["suggestions"].append(
				f"{field}: Difference of Rp {diff:,.0f} exceeds tolerance Rp {max_tolerance:,.0f}"
			)

	if not result["match"]:
		result["summary"] = f"Found {len(result['suggestions'])} mismatch(es) in totals"

	return result
