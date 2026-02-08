# -*- coding: utf-8 -*-
# Copyright (c) 2026, Imogi Finance and contributors
# For license information, please see license.txt

"""
PyMuPDF-based layout-aware parser for Indonesian Tax Invoices (Faktur Pajak).

This module extracts line items from PDF tax invoices using token positions
to accurately map Harga Jual, DPP, and PPN columns, solving multi-line item
extraction bugs.
"""

import json
import re
from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict

import frappe
from frappe import _

# Try importing PyMuPDF (fitz)
try:
	import fitz  # PyMuPDF
	PYMUPDF_AVAILABLE = True
except ImportError:
	PYMUPDF_AVAILABLE = False
	frappe.log_error(
		title="PyMuPDF Not Available",
		message="PyMuPDF (fitz) is not installed. PDF text extraction will fall back to OCR. "
		        "Install with: pip install PyMuPDF>=1.23.0"
	)


class Token:
	"""Represents a text token with bounding box coordinates."""
	
	def __init__(self, text: str, x0: float, y0: float, x1: float, y1: float):
		self.text = text.strip()
		self.x0 = x0
		self.y0 = y0
		self.x1 = x1
		self.y1 = y1
		self.x_mid = (x0 + x1) / 2
		self.y_mid = (y0 + y1) / 2
		self.width = x1 - x0
		self.height = y1 - y0
	
	def __repr__(self):
		return f"Token('{self.text}', x={self.x0:.1f}, y={self.y0:.1f})"
	
	def to_dict(self) -> Dict:
		"""Convert to dictionary for JSON serialization."""
		return {
			"text": self.text,
			"bbox": [self.x0, self.y0, self.x1, self.y1],
			"x_mid": self.x_mid,
			"y_mid": self.y_mid
		}


class ColumnRange:
	"""Represents X-coordinate range for a table column."""
	
	def __init__(self, name: str, x_min: float, x_max: float):
		self.name = name
		self.x_min = x_min
		self.x_max = x_max
		self.width = x_max - x_min
	
	def expand(self, pixels: float = None, percentage: float = None):
		"""Expand range to handle column shifts."""
		if pixels is None and percentage is None:
			# Default: max(10px, 5% of width)
			expansion = max(10, self.width * 0.05)
		elif pixels is not None:
			expansion = pixels
		else:
			expansion = self.width * percentage
		
		self.x_min -= expansion
		self.x_max += expansion
		self.width = self.x_max - self.x_min
	
	def contains(self, token: Token, min_overlap: float = 0.1) -> bool:
		"""Check if token overlaps with column range."""
		overlap_start = max(self.x_min, token.x0)
		overlap_end = min(self.x_max, token.x1)
		overlap = max(0, overlap_end - overlap_start)
		
		if overlap <= 0:
			return False
		
		# Check if overlap ratio is sufficient
		overlap_ratio = overlap / token.width if token.width > 0 else 0
		return overlap_ratio >= min_overlap
	
	def to_dict(self) -> Dict:
		"""Convert to dictionary for JSON serialization."""
		return {
			"name": self.name,
			"x_min": self.x_min,
			"x_max": self.x_max,
			"width": self.width
		}


def extract_text_with_bbox(pdf_path: str) -> List[Token]:
	"""
	Extract text with bounding boxes from PDF using PyMuPDF.
	
	Args:
		pdf_path: Absolute path to PDF file
	
	Returns:
		List of Token objects with text and coordinates
		Empty list if PyMuPDF not available
	
	Raises:
		Exception for file access or PDF parsing errors
	"""
	if not PYMUPDF_AVAILABLE:
		# Don't throw - return empty to allow graceful error handling
		frappe.log_error(
			title="PyMuPDF Not Installed",
			message=(
				"PyMuPDF is required for Tax Invoice OCR line item parsing. "
				"Add 'PyMuPDF>=1.23.0' to imogi_finance/requirements.txt and redeploy. "
				"Check Frappe Cloud build logs for dependency installation errors."
			)
		)
		return []  # Empty list allows error to be handled upstream
	
	tokens = []
	
	try:
		doc = fitz.open(pdf_path)
		
		# Process first page (tax invoices are typically 1 page)
		if len(doc) == 0:
			frappe.throw(_("PDF has no pages"))
		
		page = doc[0]
		
		# Extract text as dictionary with position info
		text_dict = page.get_text("dict")
		
		# Parse blocks -> lines -> spans -> chars
		for block in text_dict.get("blocks", []):
			if block.get("type") != 0:  # 0 = text block
				continue
			
			for line in block.get("lines", []):
				for span in line.get("spans", []):
					text = span.get("text", "").strip()
					if not text:
						continue
					
					bbox = span.get("bbox")  # (x0, y0, x1, y1)
					if bbox and len(bbox) == 4:
						token = Token(text, bbox[0], bbox[1], bbox[2], bbox[3])
						tokens.append(token)
		
		doc.close()
		
		frappe.logger().info(f"Extracted {len(tokens)} tokens from PDF: {pdf_path}")
		
		if len(tokens) == 0:
			frappe.log_error(
				title="Empty PDF Text Layer",
				message=f"No text tokens extracted from {pdf_path}. PDF may be scanned image."
			)
		
		return tokens
	
	except Exception as e:
		frappe.log_error(
			title="PyMuPDF Text Extraction Failed",
			message=f"Error extracting text from {pdf_path}: {str(e)}"
		)
		raise


def detect_table_header(tokens: List[Token]) -> Tuple[Optional[float], Dict[str, ColumnRange], str]:
	"""
	Detect table header row and extract column ranges.
	
	Supports two Faktur Pajak formats:
	1. Multi-column: Separate Harga Jual, DPP, PPN columns per line item
	2. Single-column: Only Harga Jual per line, DPP/PPN in summary section
	
	Args:
		tokens: List of Token objects
	
	Returns:
		Tuple of (header_y_position, column_ranges_dict, format_type)
		format_type is either "multi_column" or "single_column"
	"""
	# Group tokens by Y coordinate (rows)
	rows = cluster_tokens_by_row(tokens, y_tolerance=5)
	
	# Keywords to identify header row - Multi-column format
	multi_col_keywords = {
		"harga_jual": ["harga jual", "harga", "jual"],
		"dpp": ["dpp", "dasar pengenaan", "dasar"],
		"ppn": ["ppn", "pajak pertambahan"]
	}
	
	# Keywords for single-column format header
	# Standard DJP format: "Harga Jual / Penggantian / Uang Muka / Termin"
	single_col_keywords = [
		"harga jual / penggantian",
		"harga jual/penggantian", 
		"uang muka / termin",
		"uang muka/termin",
		"harga jual"
	]
	
	column_ranges = {}
	header_y = None
	format_type = None
	
	for y_pos, row_tokens in rows:
		# Combine tokens in row for keyword matching
		row_text = " ".join([t.text.lower() for t in row_tokens])
		
		# First, check for multi-column format (all 3 separate columns)
		found_columns = {}
		for col_name, keywords in multi_col_keywords.items():
			for keyword in keywords:
				if keyword in row_text:
					matching_tokens = [t for t in row_tokens if keyword in t.text.lower()]
					if matching_tokens:
						x_min = min(t.x0 for t in matching_tokens)
						x_max = max(t.x1 for t in matching_tokens)
						found_columns[col_name] = (x_min, x_max)
						break
		
		# If we found all 3 columns, this is multi-column format
		if len(found_columns) >= 3:
			header_y = y_pos
			format_type = "multi_column"
			
			for col_name, (x_min, x_max) in found_columns.items():
				col_range = ColumnRange(col_name, x_min, x_max)
				col_range.expand()
				column_ranges[col_name] = col_range
			
			frappe.logger().info(
				f"Found MULTI-COLUMN header at Y={header_y:.1f} with columns: "
				f"{list(column_ranges.keys())}"
			)
			break
		
		# Check for single-column format (Harga Jual only)
		for keyword in single_col_keywords:
			if keyword in row_text:
				# Find the Harga Jual column header token
				matching_tokens = [t for t in row_tokens if any(kw in t.text.lower() for kw in ["harga", "jual", "termin", "(rp)"])]
				if matching_tokens:
					# Use rightmost token as the value column
					rightmost = max(matching_tokens, key=lambda t: t.x1)
					x_min = rightmost.x0
					x_max = rightmost.x1
					
					header_y = y_pos
					format_type = "single_column"
					
					# Only create harga_jual column - DPP/PPN will be calculated from summary
					col_range = ColumnRange("harga_jual", x_min, x_max)
					col_range.expand(pixels=30)  # Wider expansion for single column
					column_ranges["harga_jual"] = col_range
					
					frappe.logger().info(
						f"Found SINGLE-COLUMN header at Y={header_y:.1f}. "
						f"DPP/PPN will be extracted from summary section."
					)
					break
		
		if format_type:
			break
	
	if not column_ranges:
		frappe.log_error(
			title="Table Header Not Found",
			message="Could not detect table header row with Harga Jual/DPP/PPN columns"
		)
		# Try fallback: look for rightmost numeric columns
		header_y, column_ranges = _fallback_column_detection(rows)
		if column_ranges:
			format_type = "multi_column"  # Fallback assumes multi-column
			frappe.logger().info("Used fallback column detection")
	
	return header_y, column_ranges, format_type


def _fallback_column_detection(rows: List[Tuple[float, List[Token]]]) -> Tuple[Optional[float], Dict[str, ColumnRange]]:
	"""
	Fallback column detection when header keywords not found.
	
	Heuristic: Find rows with 3+ numeric tokens on the right side,
	assume rightmost 3 are Harga Jual, DPP, PPN in order.
	
	Args:
		rows: List of (y_position, tokens) tuples
	
	Returns:
		Tuple of (header_y, column_ranges) or (None, {})
	"""
	numeric_pattern = re.compile(r'[\d\.\,]+')
	
	for y_pos, row_tokens in rows:
		# Find tokens that look numeric
		numeric_tokens = [t for t in row_tokens if numeric_pattern.search(t.text)]
		
		if len(numeric_tokens) >= 3:
			# Sort by X position, take rightmost 3
			numeric_tokens.sort(key=lambda t: t.x0)
			rightmost_3 = numeric_tokens[-3:]
			
			# Assume order: Harga Jual, DPP, PPN
			column_ranges = {
				"harga_jual": ColumnRange("harga_jual", rightmost_3[0].x0, rightmost_3[0].x1),
				"dpp": ColumnRange("dpp", rightmost_3[1].x0, rightmost_3[1].x1),
				"ppn": ColumnRange("ppn", rightmost_3[2].x0, rightmost_3[2].x1)
			}
			
			# Expand ranges
			for col in column_ranges.values():
				col.expand()
			
			frappe.logger().warning(
				f"Fallback column detection at Y={y_pos:.1f}. "
				"This may be less accurate than keyword-based detection."
			)
			
			return y_pos, column_ranges
	
	return None, {}


def find_table_end(tokens: List[Token], header_y: float) -> Optional[float]:
	"""
	Find Y-position where table ends (totals/summary section).
	
	Looks for keywords: "Jumlah", "Total", "Grand Total", "Dasar Pengenaan Pajak"
	
	Args:
		tokens: List of Token objects
		header_y: Y-position of header row (to search below it)
	
	Returns:
		Y-position of table end, or None if not found
	"""
	# Keywords that indicate end of line items table
	stop_keywords = [
		"jumlah", "total", "grand total", "subtotal",
		"dasar pengenaan pajak", "harga jual / penggantian"
	]
	
	# Filter tokens below header
	below_header = [t for t in tokens if t.y0 > header_y]
	
	# Group by Y coordinate
	rows = cluster_tokens_by_row(below_header, y_tolerance=5)
	
	for y_pos, row_tokens in rows:
		row_text = " ".join([t.text.lower() for t in row_tokens])
		
		for keyword in stop_keywords:
			if keyword in row_text:
				frappe.logger().info(
					f"Found table end keyword '{keyword}' at Y={y_pos:.1f}"
				)
				return y_pos
	
	# If not found, return None (will use all tokens below header)
	return None


def cluster_tokens_by_row(tokens: List[Token], y_tolerance: float = 3) -> List[Tuple[float, List[Token]]]:
	"""
	Group tokens into rows based on Y-coordinate clustering.
	
	Args:
		tokens: List of Token objects
		y_tolerance: Maximum Y-distance to consider same row
	
	Returns:
		List of (y_position, tokens_in_row) tuples, sorted by Y
	"""
	if not tokens:
		return []
	
	# Sort tokens by Y position
	sorted_tokens = sorted(tokens, key=lambda t: t.y_mid)
	
	rows = []
	current_row = [sorted_tokens[0]]
	current_y = sorted_tokens[0].y_mid
	
	for token in sorted_tokens[1:]:
		if abs(token.y_mid - current_y) <= y_tolerance:
			# Same row
			current_row.append(token)
			current_y = sum(t.y_mid for t in current_row) / len(current_row)
		else:
			# New row
			rows.append((current_y, current_row))
			current_row = [token]
			current_y = token.y_mid
	
	# Add last row
	if current_row:
		rows.append((current_y, current_row))
	
	return rows


def assign_tokens_to_columns(
	row_tokens: List[Token],
	column_ranges: Dict[str, ColumnRange]
) -> Dict[str, List[Token]]:
	"""
	Assign tokens in a row to appropriate columns based on X-overlap.
	
	IMPORTANT: Only assigns tokens that overlap with defined column ranges.
	Tokens outside all column ranges (e.g., in description area) are excluded.
	
	Args:
		row_tokens: Tokens in this row
		column_ranges: Dictionary of column name -> ColumnRange
	
	Returns:
		Dictionary of column name -> tokens in that column
	"""
	assignments = {col_name: [] for col_name in column_ranges.keys()}
	
	# Sort column ranges by X position to determine leftmost boundary
	sorted_cols = sorted(column_ranges.values(), key=lambda c: c.x_min)
	leftmost_numeric_col = sorted_cols[0].x_min if sorted_cols else float('inf')
	
	for token in row_tokens:
		# Critical guard: Skip tokens that are clearly in description area
		# (left of the leftmost numeric column)
		if token.x1 < leftmost_numeric_col * 0.9:  # 10% tolerance
			continue
		
		assigned = False
		for col_name, col_range in column_ranges.items():
			if col_range.contains(token):
				assignments[col_name].append(token)
				assigned = True
				break  # Assign to first matching column only
		
		# Log warning if numeric token wasn't assigned (potential data loss)
		if not assigned and re.search(r'[\d\.,]+', token.text):
			frappe.logger().debug(
				f"Numeric token '{token.text}' at X={token.x0:.1f} not assigned to any column. "
				f"This is expected for amounts in description."
			)
	
	return assignments


def get_rightmost_value(tokens: List[Token]) -> Optional[str]:
	"""
	Get the rightmost token's text from a list (for numeric columns).
	
	Args:
		tokens: List of tokens in a column
	
	Returns:
		Text of rightmost token, or None if empty
	"""
	if not tokens:
		return None
	
	rightmost = max(tokens, key=lambda t: t.x1)
	return rightmost.text


def merge_description_wraparounds(rows: List[Dict]) -> List[Dict]:
	"""
	Merge rows without numeric values into previous row's description.
	
	Handles wrapped description lines in multi-line items.
	
	Special handling:
		- Rows with "PPnBM", "Potongan", "x 1,00" etc. in description
		  but no values in Harga Jual/DPP/PPN columns are merged
		- Preserves data rows with valid numeric columns
	
	Args:
		rows: List of parsed row dictionaries
	
	Returns:
		List of merged row dictionaries
	"""
	if not rows:
		return []
	
	merged = []
	current_row = None
	
	for row in rows:
		# Check if row has numeric values in the CORRECT columns
		# (not just any numeric text in description)
		has_numbers = any([
			row.get("harga_jual"),
			row.get("dpp"),
			row.get("ppn")
		])
		
		# Additional check: description-only keywords that should merge
		description_only_keywords = [
			"ppnbm", "potongan", "diskon", "discount",
			"x 1,00", "x 1.00", "lainnya"
		]
		desc_text = (row.get("description", "") or "").lower()
		is_description_only = any(keyword in desc_text for keyword in description_only_keywords)
		
		if (has_numbers and not is_description_only) or current_row is None:
			# This is a data row or first row
			if current_row:
				merged.append(current_row)
			current_row = row
		else:
			# This is a continuation row (description wraparound)
			if current_row and row.get("description"):
				# Append to previous description with space
				prev_desc = current_row.get("description", "")
				new_desc = row.get("description", "")
				current_row["description"] = f"{prev_desc} {new_desc}".strip()
				
				frappe.logger().debug(
					f"Merged wraparound: '{new_desc[:50]}...' into previous row"
				)
	
	# Add last row
	if current_row:
		merged.append(current_row)
	
	return merged


def parse_invoice(pdf_path: str, tax_rate: float = 0.11) -> Dict[str, Any]:
	"""
	Main parsing function: extract line items from Tax Invoice PDF.
	
	Supports two formats:
	1. Multi-column: Separate Harga Jual, DPP, PPN columns per line item
	2. Single-column: Only Harga Jual per line, DPP/PPN extracted from summary
	
	Args:
		pdf_path: Absolute path to PDF file
		tax_rate: PPN tax rate for validation (default 11%)
	
	Returns:
		Dictionary with:
			- items: List of line item dictionaries
			- debug_info: Debug metadata for troubleshooting
			- success: Boolean
			- errors: List of error messages
	"""
	result = {
		"items": [],
		"debug_info": {},
		"success": False,
		"errors": []
	}
	
	try:
		# Step 1: Extract tokens with bounding boxes
		tokens = extract_text_with_bbox(pdf_path)
		
		if not tokens:
			if not PYMUPDF_AVAILABLE:
				result["errors"].append(
					"PyMuPDF not installed on server. "
					"Add to imogi_finance/requirements.txt and redeploy. "
					"See Frappe Cloud build logs."
				)
			else:
				result["errors"].append("No text extracted from PDF (may be scanned image)")
			return result
		
		# Store token count in debug
		result["debug_info"]["token_count"] = len(tokens)
		
		# Store tokens in debug info (truncate if too large)
		MAX_DEBUG_TOKENS = 500
		if len(tokens) <= MAX_DEBUG_TOKENS:
			result["debug_info"]["tokens"] = [t.to_dict() for t in tokens]
		else:
			result["debug_info"]["tokens"] = (
				[t.to_dict() for t in tokens[:100]] +
				[{"text": f"... {len(tokens) - 200} tokens truncated ...", "bbox": [0, 0, 0, 0]}] +
				[t.to_dict() for t in tokens[-100:]]
			)
			result["debug_info"]["tokens_truncated"] = True
		
		# Step 2: Detect table header, column ranges, and format type
		header_y, column_ranges, format_type = detect_table_header(tokens)
		
		if not header_y or not column_ranges:
			result["errors"].append("Could not detect table header")
			return result
		
		result["debug_info"]["header_y"] = header_y
		result["debug_info"]["format_type"] = format_type
		result["debug_info"]["column_ranges"] = {
			k: v.to_dict() for k, v in column_ranges.items()
		}
		
		# Step 3: Find table end position
		table_end_y = find_table_end(tokens, header_y)
		result["debug_info"]["table_end_y"] = table_end_y
		
		# Step 4: For single-column format, extract summary totals (DPP, PPN)
		summary_totals = {}
		if format_type == "single_column":
			summary_totals = _extract_summary_totals(tokens, header_y)
			result["debug_info"]["summary_totals"] = summary_totals
		
		# Step 5: Filter tokens in table region
		table_tokens = [t for t in tokens if t.y0 > header_y]
		if table_end_y:
			table_tokens = [t for t in table_tokens if t.y0 < table_end_y]
		
		result["debug_info"]["table_token_count"] = len(table_tokens)
		
		# Step 6: Cluster into rows
		rows = cluster_tokens_by_row(table_tokens, y_tolerance=3)
		result["debug_info"]["row_count_before_merge"] = len(rows)
		
		# Step 7: Parse each row based on format type
		parsed_rows = []
		for y_pos, row_tokens in rows:
			# Assign tokens to columns
			column_assignments = assign_tokens_to_columns(row_tokens, column_ranges)
			
			# Extract values based on format
			if format_type == "multi_column":
				row_data = {
					"row_y": y_pos,
					"harga_jual": get_rightmost_value(column_assignments.get("harga_jual", [])),
					"dpp": get_rightmost_value(column_assignments.get("dpp", [])),
					"ppn": get_rightmost_value(column_assignments.get("ppn", [])),
				}
			else:  # single_column
				# Only Harga Jual from table, DPP/PPN will be calculated later
				harga_jual_value = get_rightmost_value(column_assignments.get("harga_jual", []))
				row_data = {
					"row_y": y_pos,
					"harga_jual": harga_jual_value,
					"dpp": None,  # Will be calculated from summary
					"ppn": None,  # Will be calculated from summary
				}
			
			# Get description (tokens not in numeric columns)
			desc_tokens = [t for t in row_tokens 
			               if not any(t in col_list for col_list in column_assignments.values())]
			row_data["description"] = " ".join([t.text for t in desc_tokens]) if desc_tokens else ""
			
			# Store column X positions for debug (only for columns that exist)
			if "harga_jual" in column_ranges:
				row_data["col_x_harga_jual"] = f"{column_ranges['harga_jual'].x_min:.1f}-{column_ranges['harga_jual'].x_max:.1f}"
			if "dpp" in column_ranges:
				row_data["col_x_dpp"] = f"{column_ranges['dpp'].x_min:.1f}-{column_ranges['dpp'].x_max:.1f}"
			if "ppn" in column_ranges:
				row_data["col_x_ppn"] = f"{column_ranges['ppn'].x_min:.1f}-{column_ranges['ppn'].x_max:.1f}"
			
			parsed_rows.append(row_data)
		
		# Step 8: Merge description wraparounds
		merged_rows = merge_description_wraparounds(parsed_rows)
		result["debug_info"]["row_count_after_merge"] = len(merged_rows)
		
		# Step 9: For single-column format, calculate DPP/PPN from summary
		if format_type == "single_column" and merged_rows:
			merged_rows = _apply_summary_totals_to_items(merged_rows, summary_totals, tax_rate)
		
		# Step 10: Assign line numbers and store raw values
		for idx, row in enumerate(merged_rows, start=1):
			row["line_no"] = idx
			row["raw_harga_jual"] = row.get("harga_jual", "") or ""
			row["raw_dpp"] = row.get("dpp", "") or ""
			row["raw_ppn"] = row.get("ppn", "") or ""
		
		result["items"] = merged_rows
		result["success"] = True
		
		frappe.logger().info(
			f"Successfully parsed {len(merged_rows)} line items from {pdf_path} (format: {format_type})"
		)
		
	except Exception as e:
		error_msg = f"Parsing failed: {str(e)}"
		result["errors"].append(error_msg)
		frappe.log_error(
			title="Tax Invoice Parsing Error",
			message=f"Error parsing {pdf_path}: {str(e)}\n{frappe.get_traceback()}"
		)
	
	return result


def _extract_summary_totals(tokens: List[Token], header_y: float) -> Dict[str, str]:
	"""
	Extract DPP and PPN totals from summary section (for single-column format).
	
	Looks for keywords like:
	- "Dasar Pengenaan Pajak" or "DPP" followed by amount
	- "Jumlah PPN" or "PPN (Pajak Pertambahan Nilai)" followed by amount
	
	Args:
		tokens: All tokens from PDF
		header_y: Y-position of table header
	
	Returns:
		Dictionary with 'dpp' and 'ppn' values (as strings)
	"""
	summary = {"dpp": None, "ppn": None, "harga_jual_total": None}
	
	# Group tokens by row
	rows = cluster_tokens_by_row(tokens, y_tolerance=5)
	
	# Keywords to find summary rows
	dpp_keywords = ["dasar pengenaan pajak", "dpp"]
	ppn_keywords = ["jumlah ppn", "ppn (pajak pertambahan", "pajak pertambahan nilai"]
	harga_jual_keywords = ["harga jual / penggantian / uang muka", "harga jual/penggantian"]
	
	numeric_pattern = re.compile(r'[\d\.\,]+')
	
	for y_pos, row_tokens in rows:
		# Only check rows below header (summary is after line items)
		if y_pos <= header_y:
			continue
		
		row_text = " ".join([t.text.lower() for t in row_tokens])
		
		# Find numeric tokens in this row
		numeric_tokens = [t for t in row_tokens if numeric_pattern.search(t.text)]
		if not numeric_tokens:
			continue
		
		# Get rightmost numeric value
		rightmost_num = max(numeric_tokens, key=lambda t: t.x1)
		
		# Check for DPP
		if any(kw in row_text for kw in dpp_keywords) and summary["dpp"] is None:
			summary["dpp"] = rightmost_num.text
			frappe.logger().debug(f"Found summary DPP: {rightmost_num.text} at Y={y_pos:.1f}")
		
		# Check for PPN
		elif any(kw in row_text for kw in ppn_keywords) and summary["ppn"] is None:
			summary["ppn"] = rightmost_num.text
			frappe.logger().debug(f"Found summary PPN: {rightmost_num.text} at Y={y_pos:.1f}")
		
		# Check for Harga Jual total (for validation)
		elif any(kw in row_text for kw in harga_jual_keywords) and summary["harga_jual_total"] is None:
			summary["harga_jual_total"] = rightmost_num.text
			frappe.logger().debug(f"Found summary Harga Jual: {rightmost_num.text} at Y={y_pos:.1f}")
	
	return summary


def _apply_summary_totals_to_items(
	items: List[Dict],
	summary_totals: Dict[str, str],
	tax_rate: float
) -> List[Dict]:
	"""
	Apply DPP/PPN from summary to line items (for single-column format).
	
	For single-item invoices: Use summary DPP/PPN directly
	For multi-item invoices: Distribute proportionally based on Harga Jual
	
	Args:
		items: Parsed line items (with harga_jual only)
		summary_totals: DPP and PPN from summary section
		tax_rate: PPN rate for calculations
	
	Returns:
		Updated items with DPP and PPN values
	"""
	from imogi_finance.imogi_finance.parsers.normalization import normalize_indonesian_number
	
	# Parse summary values
	summary_dpp = normalize_indonesian_number(summary_totals.get("dpp") or "")
	summary_ppn = normalize_indonesian_number(summary_totals.get("ppn") or "")
	
	if not summary_dpp and not summary_ppn:
		frappe.logger().warning("No summary DPP/PPN found - items will have empty DPP/PPN")
		return items
	
	# Calculate total Harga Jual from items
	total_harga_jual = 0
	for item in items:
		hj = normalize_indonesian_number(item.get("harga_jual") or "")
		if hj:
			total_harga_jual += hj
	
	if total_harga_jual == 0:
		frappe.logger().warning("Total Harga Jual is 0 - cannot distribute DPP/PPN")
		return items
	
	# Distribute DPP/PPN proportionally
	for item in items:
		hj = normalize_indonesian_number(item.get("harga_jual") or "")
		if hj and total_harga_jual > 0:
			ratio = hj / total_harga_jual
			
			if summary_dpp:
				item_dpp = round(summary_dpp * ratio, 2)
				item["dpp"] = f"{item_dpp:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
			
			if summary_ppn:
				item_ppn = round(summary_ppn * ratio, 2)
				item["ppn"] = f"{item_ppn:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
	
	frappe.logger().info(
		f"Applied summary totals to {len(items)} items: "
		f"DPP={summary_dpp}, PPN={summary_ppn}"
	)
	
	return items
