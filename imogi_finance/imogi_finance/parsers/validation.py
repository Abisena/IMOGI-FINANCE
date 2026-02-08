# -*- coding: utf-8 -*-
# Copyright (c) 2026, Imogi Finance and contributors
# For license information, please see license.txt

"""
Validation module for Tax Invoice line items and totals.

Implements per-row and invoice-level validation with auto-approval logic.
"""

from typing import Dict, List, Optional, Tuple
import frappe
from frappe import _
from frappe.utils import flt

from .normalization import normalize_indonesian_number


def get_tolerance_settings() -> Tuple[float, float]:
	"""
	Get validation tolerance settings from Tax Invoice OCR Settings.
	
	Returns:
		Tuple of (tolerance_idr, tolerance_percentage)
	"""
	try:
		settings = frappe.get_single("Tax Invoice OCR Settings")
		tolerance_idr = flt(settings.get("tolerance_idr", 10000))
		tolerance_percentage = flt(settings.get("tolerance_percentage", 1)) / 100  # Convert to decimal
		return tolerance_idr, tolerance_percentage
	except Exception:
		# Default values if settings not found
		return 10000.0, 0.01  # 10,000 IDR and 1%


def validate_line_item(
	item: Dict,
	tax_rate: float = 0.11,
	tolerance_idr: float = None,
	tolerance_percentage: float = None
) -> Dict:
	"""
	Validate a single line item and calculate confidence score.
	
	Checks:
		- PPN ≈ DPP × tax_rate (within tolerance)
		- Harga Jual >= DPP (standard assumption)
		- All numeric values are present and valid
	
	Args:
		item: Line item dictionary with harga_jual, dpp, ppn
		tax_rate: PPN tax rate (default 0.11 = 11%)
		tolerance_idr: Absolute tolerance in IDR
		tolerance_percentage: Relative tolerance as decimal (0.01 = 1%)
	
	Returns:
		Updated item dict with row_confidence, notes, and validation flags
	"""
	if tolerance_idr is None or tolerance_percentage is None:
		tolerance_idr, tolerance_percentage = get_tolerance_settings()
	
	harga_jual = flt(item.get("harga_jual"))
	dpp = flt(item.get("dpp"))
	ppn = flt(item.get("ppn"))
	
	notes = []
	confidence = 1.0
	
	# Check if all values are present
	if not dpp or not ppn:
		notes.append("Missing DPP or PPN value")
		confidence = 0.3
		item["row_confidence"] = confidence
		item["notes"] = "; ".join(notes)
		return item
	
	# Calculate expected PPN
	expected_ppn = dpp * tax_rate
	ppn_diff = abs(ppn - expected_ppn)
	
	# Calculate tolerance (use maximum of absolute or relative)
	absolute_tolerance = tolerance_idr
	relative_tolerance = dpp * tolerance_percentage
	max_tolerance = max(absolute_tolerance, relative_tolerance)
	
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
	tolerance_idr, tolerance_percentage = get_tolerance_settings()
	
	validated_items = []
	invalid_items = []
	
	for item in items:
		validated_item = validate_line_item(
			item,
			tax_rate=tax_rate,
			tolerance_idr=tolerance_idr,
			tolerance_percentage=tolerance_percentage
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
	tolerance_idr: float = None,
	tolerance_percentage: float = None
) -> Dict:
	"""
	Validate sum of line items against header totals.
	
	Args:
		items: List of validated line items
		header_totals: Dict with harga_jual, dpp, ppn from invoice header
		tolerance_idr: Absolute tolerance
		tolerance_percentage: Relative tolerance
	
	Returns:
		Dictionary with validation results:
			- match: Boolean
			- differences: Dict of field -> delta
			- notes: List of validation messages
	"""
	if tolerance_idr is None or tolerance_percentage is None:
		tolerance_idr, tolerance_percentage = get_tolerance_settings()
	
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
		
		# Calculate tolerance
		absolute_tolerance = tolerance_idr
		relative_tolerance = header_val * tolerance_percentage
		max_tolerance = max(absolute_tolerance, relative_tolerance)
		
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
