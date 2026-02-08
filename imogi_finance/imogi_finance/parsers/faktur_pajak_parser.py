# -*- coding: utf-8 -*-
# Copyright (c) 2026, Imogi Finance and contributors
# For license information, please see license.txt

"""
PyMuPDF-based layout-aware parser for Indonesian Tax Invoices (Faktur Pajak).

This module extracts line items from PDF tax invoices using token positions
to accurately map Harga Jual, DPP, and PPN columns, solving multi-line item
extraction bugs.

🔥 FRAPPE CLOUD SAFE: Uses bytes-based PDF reading via Frappe File API.
   Works with local files, S3, and remote storage.
"""

import json
import re
from typing import Dict, List, Tuple, Optional, Any, Union
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
	"""
	Unified token model for text with bounding box coordinates.
	
	Supports both PyMuPDF text-layer extraction and Google Vision OCR results.
	Tracks page number for multi-page documents and OCR confidence for quality monitoring.
	"""
	
	def __init__(
		self, 
		text: str, 
		x0: float, 
		y0: float, 
		x1: float, 
		y1: float, 
		page_no: int = 1,
		confidence: Optional[float] = None,
		source: str = "pymupdf"
	):
		self.text = text.strip()
		self.x0 = x0
		self.y0 = y0
		self.x1 = x1
		self.y1 = y1
		self.x_mid = (x0 + x1) / 2
		self.y_mid = (y0 + y1) / 2
		self.width = x1 - x0
		self.height = y1 - y0
		self.page_no = page_no  # Track page number for multi-page PDFs
		self.confidence = confidence  # OCR confidence (0.0-1.0), None for text-layer PDFs
		self.source = source  # "pymupdf" or "vision_ocr"
	
	def __repr__(self):
		conf_str = f", conf={self.confidence:.2f}" if self.confidence is not None else ""
		return f"Token('{self.text}', x={self.x0:.1f}, y={self.y0:.1f}, page={self.page_no}{conf_str})"
	
	def to_dict(self) -> Dict:
		"""Convert to dictionary for JSON serialization."""
		result = {
			"text": self.text,
			"bbox": [self.x0, self.y0, self.x1, self.y1],
			"x_mid": self.x_mid,
			"y_mid": self.y_mid,
			"page_no": self.page_no,
			"source": self.source
		}
		if self.confidence is not None:
			result["confidence"] = self.confidence
		return result


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


# =============================================================================
# 🔥 FRAPPE CLOUD SAFE PDF HANDLING
# =============================================================================

def _get_pdf_bytes(file_url_or_name: str) -> bytes:
	"""
	Get PDF file content as bytes via Frappe File API.
	
	🔥 FRAPPE CLOUD SAFE: Works with local files, S3, and remote storage.
	This is the recommended way to read files in Frappe Cloud environments
	where get_local_path() may return non-existent paths.
	
	Args:
		file_url_or_name: Can be:
			- File URL: /private/files/xxx.pdf or /files/xxx.pdf
			- File doctype name
			- Absolute path (fallback for backward compatibility)
	
	Returns:
		PDF content as bytes
	
	Raises:
		ValueError: If file not found, empty, or not a valid PDF
	"""
	import os
	
	if not file_url_or_name:
		raise ValueError("File URL/name is empty or None")
	
	frappe.logger().info(f"[PDF] Getting bytes for: {file_url_or_name}")
	
	file_doc = None
	content = None
	
	# Strategy 1: Try as File doctype name
	try:
		if frappe.db.exists("File", file_url_or_name):
			file_doc = frappe.get_doc("File", file_url_or_name)
			frappe.logger().info(f"[PDF] Found File doc by name: {file_doc.name}")
	except Exception as e:
		frappe.logger().debug(f"[PDF] Not a File doc name: {e}")
	
	# Strategy 2: Try as file_url
	if not file_doc:
		try:
			file_doc_name = frappe.db.get_value("File", {"file_url": file_url_or_name}, "name")
			if file_doc_name:
				file_doc = frappe.get_doc("File", file_doc_name)
				frappe.logger().info(f"[PDF] Found File doc by file_url: {file_doc.name}")
		except Exception as e:
			frappe.logger().debug(f"[PDF] Could not find by file_url: {e}")
	
	# Strategy 3: Try with normalized URL (strip leading /)
	if not file_doc and file_url_or_name.startswith("/"):
		try:
			normalized_url = file_url_or_name.lstrip("/")
			file_doc_name = frappe.db.get_value(
				"File", 
				{"file_url": ["like", f"%{normalized_url}"]}, 
				"name"
			)
			if file_doc_name:
				file_doc = frappe.get_doc("File", file_doc_name)
				frappe.logger().info(f"[PDF] Found File doc by normalized URL: {file_doc.name}")
		except Exception as e:
			frappe.logger().debug(f"[PDF] Could not find by normalized URL: {e}")
	
	# Get content from File doc
	if file_doc:
		try:
			content = file_doc.get_content()
			frappe.logger().info(
				f"[PDF] Got content via File API: {len(content) if content else 0} bytes"
			)
		except Exception as e:
			frappe.logger().warning(f"[PDF] File.get_content() failed: {e}")
			content = None
	
	# Strategy 4: Fallback to direct file read (for absolute paths)
	if not content and os.path.isabs(file_url_or_name) and os.path.exists(file_url_or_name):
		try:
			with open(file_url_or_name, "rb") as f:
				content = f.read()
			frappe.logger().info(f"[PDF] Read from absolute path: {len(content)} bytes")
		except Exception as e:
			frappe.logger().warning(f"[PDF] Direct file read failed: {e}")
	
	# Strategy 5: Fallback to site_path resolution
	if not content:
		try:
			from frappe.utils import get_site_path
			site_path = get_site_path(file_url_or_name.strip("/"))
			if os.path.exists(site_path):
				with open(site_path, "rb") as f:
					content = f.read()
				frappe.logger().info(f"[PDF] Read from site_path: {len(content)} bytes")
		except Exception as e:
			frappe.logger().warning(f"[PDF] Site path resolution failed: {e}")
	
	# Validate content
	if not content:
		raise ValueError(
			f"Could not read PDF file: {file_url_or_name}. "
			"File may not exist or is in remote storage that is not accessible."
		)
	
	if len(content) == 0:
		raise ValueError(f"PDF file is empty (0 bytes): {file_url_or_name}")
	
	# Validate PDF header (allow some whitespace before %PDF)
	header_check = content[:20].lstrip()
	if not header_check.startswith(b"%PDF"):
		# Check if it might be gzipped or otherwise compressed
		if content[:2] == b"\x1f\x8b":
			raise ValueError(
				f"File appears to be gzipped, not a PDF: {file_url_or_name}"
			)
		raise ValueError(
			f"File is not a valid PDF (missing %PDF header): {file_url_or_name}. "
			f"First bytes: {content[:20]!r}"
		)
	
	frappe.logger().info(
		f"[PDF] Successfully loaded {len(content)} bytes from {file_url_or_name}"
	)
	return content


def extract_text_with_bbox_from_bytes(pdf_bytes: bytes, source_name: str = "bytes") -> List[Token]:
	"""
	Extract text with bounding boxes from PDF bytes using PyMuPDF.
	
	🔥 FRAPPE CLOUD SAFE: Opens PDF from bytes, not file path.
	This avoids issues with S3/remote storage where local paths don't exist.
	
	Args:
		pdf_bytes: PDF content as bytes
		source_name: Name for logging (e.g., file URL)
	
	Returns:
		List of Token objects with text, coordinates, and page_no
	
	Raises:
		ValueError: If PyMuPDF not available, PDF encrypted, or corrupted
	"""
	if not PYMUPDF_AVAILABLE:
		frappe.log_error(
			title="PyMuPDF Not Installed",
			message=(
				"PyMuPDF is required for Tax Invoice OCR line item parsing. "
				"Add 'PyMuPDF>=1.23.0' to imogi_finance/requirements.txt and redeploy."
			)
		)
		return []
	
	if not pdf_bytes:
		raise ValueError("PDF bytes is empty or None")
	
	if len(pdf_bytes) < 100:
		frappe.logger().warning(
			f"[PyMuPDF] PDF suspiciously small ({len(pdf_bytes)} bytes): {source_name}"
		)
	
	tokens = []
	doc = None
	
	try:
		# 🔥 Open from bytes, not path - this is the key fix!
		doc = fitz.open(stream=pdf_bytes, filetype="pdf")
		
		# Defensive check: verify document is actually open
		if doc.is_closed:
			raise ValueError(f"PDF document closed immediately after open (corrupted): {source_name}")
		
		# Check for encrypted PDFs
		if doc.is_encrypted:
			if not doc.authenticate(""):  # Try empty password
				raise ValueError(f"PDF is encrypted and requires password: {source_name}")
			frappe.logger().info(f"[PyMuPDF] PDF encrypted but opened with empty password: {source_name}")
		
		if len(doc) == 0:
			raise ValueError(f"PDF has no pages: {source_name}")
		
		page_count = len(doc)
		
		# Process ALL pages
		for page_index in range(page_count):
			page_no = page_index + 1  # 1-based page numbering
			page = doc[page_index]
			
			# Extract text as dictionary with position info
			text_dict = page.get_text("dict")
			
			# Parse blocks -> lines -> spans
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
							token = Token(
								text=text,
								x0=bbox[0],
								y0=bbox[1],
								x1=bbox[2],
								y1=bbox[3],
								page_no=page_no,
								source="pymupdf"
							)
							tokens.append(token)
		
		frappe.logger().info(
			f"[PyMuPDF] Extracted {len(tokens)} tokens from {page_count} page(s): {source_name}"
		)
		
		if len(tokens) == 0:
			frappe.logger().warning(
				f"[PyMuPDF] No text tokens extracted: {source_name}. PDF may be scanned image."
			)
		
		return tokens
	
	except fitz.FileDataError as e:
		raise ValueError(f"PDF file is corrupted or invalid: {source_name}. Error: {e}")
	except Exception as e:
		error_str = str(e).lower()
		if "encrypted" in error_str:
			raise ValueError(f"PDF is encrypted: {source_name}")
		if "closed" in error_str or "invalid" in error_str:
			raise ValueError(f"PDF corrupted or closed unexpectedly: {source_name}. Error: {e}")
		frappe.log_error(
			title="PyMuPDF Text Extraction Failed",
			message=f"Error extracting text from {source_name}: {e}\n{frappe.get_traceback()}"
		)
		raise
	
	finally:
		# Always close the document to prevent resource leaks
		if doc is not None and not doc.is_closed:
			try:
				doc.close()
			except Exception:
				pass


def extract_text_with_bbox(file_url_or_path: str) -> List[Token]:
	"""
	Extract text with bounding boxes from PDF using PyMuPDF.
	
	🔥 FRAPPE CLOUD SAFE: Now uses bytes-based extraction internally.
	Accepts file URLs, File doc names, or absolute paths.
	
	Args:
		file_url_or_path: File URL (/private/files/xxx.pdf), File name, or path
	
	Returns:
		List of Token objects with text, coordinates, and page_no
		Empty list if PyMuPDF not available
	
	Raises:
		ValueError: If file not found, empty, encrypted, or corrupted
	"""
	if not PYMUPDF_AVAILABLE:
		frappe.log_error(
			title="PyMuPDF Not Installed",
			message="PyMuPDF is required for Tax Invoice OCR line item parsing."
		)
		return []
	
	# Get PDF bytes via Cloud-safe method
	pdf_bytes = _get_pdf_bytes(file_url_or_path)
	
	# Extract using bytes-based method
	return extract_text_with_bbox_from_bytes(pdf_bytes, source_name=file_url_or_path)


def vision_to_tokens(vision_json: Dict[str, Any]) -> List[Token]:
	"""
	Convert Google Vision OCR JSON result to unified Token list.
	
	Reads fullTextAnnotation.pages[].blocks[].paragraphs[].words[]
	and creates Token objects with page_no, confidence, and bounding boxes.
	
	Vision API coordinate system:
	- Origin (0,0) is top-left
	- boundingBox.vertices = [{x, y}, {x, y}, {x, y}, {x, y}]
	  (4 corners: top-left, top-right, bottom-right, bottom-left)
	
	Args:
		vision_json: Parsed JSON from Google Vision API response
	
	Returns:
		List of Token objects with page_no and confidence
	"""
	tokens = []
	
	# Navigate to pages array
	full_text = vision_json.get("fullTextAnnotation", {})
	pages = full_text.get("pages", [])
	
	if not pages:
		frappe.logger().warning("No pages found in Vision OCR result")
		return tokens
	
	for page_index, page in enumerate(pages):
		page_no = page_index + 1  # 1-based page numbering
		
		blocks = page.get("blocks", [])
		for block in blocks:
			paragraphs = block.get("paragraphs", [])
			for paragraph in paragraphs:
				words = paragraph.get("words", [])
				for word in words:
					# Construct word text from symbols
					symbols = word.get("symbols", [])
					if not symbols:
						continue
					
					word_text = "".join([sym.get("text", "") for sym in symbols])
					if not word_text.strip():
						continue
					
					# Extract bounding box (4 vertices -> x0,y0,x1,y1)
					bbox = word.get("boundingBox", {})
					vertices = bbox.get("vertices", [])
					
					if len(vertices) < 4:
						continue
					
					# Convert vertices to (x_min, y_min, x_max, y_max)
					x_coords = [v.get("x", 0) for v in vertices if "x" in v]
					y_coords = [v.get("y", 0) for v in vertices if "y" in v]
					
					if not x_coords or not y_coords:
						continue
					
					x0 = min(x_coords)
					y0 = min(y_coords)
					x1 = max(x_coords)
					y1 = max(y_coords)
					
					# Extract confidence (optional, word-level or paragraph-level)
					confidence = word.get("confidence")
					if confidence is None:
						confidence = paragraph.get("confidence")
					if confidence is None:
						confidence = block.get("confidence")
					
					# Create Token
					token = Token(
						text=word_text,
						x0=float(x0),
						y0=float(y0),
						x1=float(x1),
						y1=float(y1),
						page_no=page_no,
						confidence=float(confidence) if confidence is not None else None,
						source="vision_ocr"
					)
					tokens.append(token)
	
	frappe.logger().info(
		f"Converted {len(tokens)} tokens from Vision OCR ({len(pages)} page(s))"
	)
	
	return tokens


def extract_tokens(
	file_url_or_path: Optional[str] = None, 
	vision_json: Optional[Dict] = None,
	pdf_bytes: Optional[bytes] = None
) -> List[Token]:
	"""
	Unified token extraction with automatic fallback.
	
	🔥 FRAPPE CLOUD SAFE: Now accepts file URLs for bytes-based extraction.
	
	Pure extraction layer - does not perform any parsing logic.
	Returns unified Token list regardless of source.
	
	Extraction Priority (automatic fallback):
		1. Vision JSON (if provided) - Best for scanned PDFs
		2. PDF bytes (if provided) - Direct bytes extraction
		3. PyMuPDF via file URL (if file_url_or_path provided) - Best for text-layer PDFs
		4. Raise ValueError if all fail or none provided
	
	Args:
		file_url_or_path: File URL (/private/files/xxx.pdf), File name, or path
		vision_json: Google Vision OCR JSON result (for scanned PDFs)
		pdf_bytes: Direct PDF bytes (optional, for pre-loaded content)
	
	Returns:
		List of Token objects
	
	Raises:
		ValueError if no input provided or all extraction methods fail
	"""
	if not file_url_or_path and not vision_json and not pdf_bytes:
		raise ValueError("At least one of file_url_or_path, vision_json, or pdf_bytes must be provided")
	
	# Track errors for final error message
	vision_error = None
	pymupdf_error = None
	
	# STEP 1: Try vision_json first (preferred for scanned PDFs)
	if vision_json:
		try:
			tokens = vision_to_tokens(vision_json)
			if tokens:
				frappe.logger().info(f"Extracted {len(tokens)} tokens from Vision OCR JSON")
				return tokens
			else:
				vision_error = "returned 0 tokens (empty or invalid JSON structure)"
				frappe.logger().warning(f"Vision JSON provided but {vision_error} - falling back to PyMuPDF")
		except Exception as e:
			vision_error = str(e)
			frappe.logger().warning(f"Vision OCR extraction failed: {vision_error} - falling back to PyMuPDF")
	
	# STEP 2: Try direct bytes if provided
	if pdf_bytes:
		try:
			tokens = extract_text_with_bbox_from_bytes(pdf_bytes, source_name="direct_bytes")
			if tokens:
				frappe.logger().info(f"Extracted {len(tokens)} tokens from PDF bytes")
				return tokens
			else:
				pymupdf_error = "returned 0 tokens (PDF may be scanned image without text layer)"
		except ValueError as e:
			pymupdf_error = str(e)
		except Exception as e:
			pymupdf_error = f"unexpected error - {str(e)}"
	
	# STEP 3: Try file URL/path via Cloud-safe method
	# NOTE: Always try if file_url_or_path is provided, even if Step 2 failed
	# (Step 2 might fail with direct bytes, but Step 3 could work with file lookup)
	if file_url_or_path:
		try:
			# Get bytes first, then extract - Cloud safe!
			file_bytes = _get_pdf_bytes(file_url_or_path)
			tokens = extract_text_with_bbox_from_bytes(file_bytes, source_name=file_url_or_path)
			if tokens:
				frappe.logger().info(f"Extracted {len(tokens)} tokens from PyMuPDF (text layer)")
				return tokens
			else:
				# Use 'or' to preserve error from Step 2 if it had more context
				pymupdf_error = pymupdf_error or "returned 0 tokens (PDF may be scanned image without text layer)"
		except ValueError as e:
			pymupdf_error = pymupdf_error or str(e)
		except Exception as e:
			error_str = str(e).lower()
			if "closed" in error_str or "invalid" in error_str or "corrupt" in error_str:
				pymupdf_error = pymupdf_error or f"document corrupted - {str(e)}"
			elif "not found" in error_str or "could not read" in error_str:
				pymupdf_error = pymupdf_error or f"file access error - {str(e)}"
			else:
				pymupdf_error = pymupdf_error or str(e)
	
	# Build clear error message
	vision_status = "not provided" if not vision_json else f"failed ({vision_error})" if vision_error else "failed"
	pymupdf_status = "not attempted" if not file_url_or_path and not pdf_bytes else pymupdf_error or "unknown error"
	
	raise ValueError(
		f"Both extraction methods failed. "
		f"Vision OCR: {vision_status}. "
		f"PyMuPDF: {pymupdf_status}"
	)


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


def parse_invoice(
	file_url_or_path: Optional[str] = None,
	vision_json: Optional[Dict] = None,
	tax_rate: float = 0.11,
	pdf_path: Optional[str] = None  # Backward compatibility alias
) -> Dict[str, Any]:
	"""
	🆕 LINE ITEM PARSER - Token+Bounding Box Based
	
	🔥 FRAPPE CLOUD SAFE: Now uses bytes-based PDF reading.
	
	Scope:
		Extracts LINE ITEMS (individual rows) from Faktur Pajak using spatial coordinates.
		Does NOT extract header/totals (use parse_faktur_pajak_text() for that).
	
	Extracted Per Line Item:
		- line_no (sequential)
		- description (item description, multi-line merged)
		- harga_jual (price per item)
		- dpp (taxable base per item)
		- ppn (tax amount per item)
		- page_no (for multi-page PDFs)
		- row_confidence (OCR quality score)
	
	Used By:
		- Tax Invoice OCR Upload.parse_line_items()
		- auto_parse_line_items() background job
	
	Extraction Strategy (Automatic Fallback):
		1. Try Vision JSON (if ocr_raw_json exists) → Best for scanned PDFs
		2. Fallback: PyMuPDF text layer → Best for digital PDFs
		3. If both fail: Set status "Needs Review"
	
	Token Sources:
		- PyMuPDF: extract_text_with_bbox() → Native text layer
		- Vision OCR: vision_to_tokens() → Google Vision API response
	
	Parsing Architecture:
		1. extract_tokens() → Unified Token list (source-agnostic)
		2. detect_table_header() → Find "Harga Jual", "DPP", "PPN" columns
		3. _parse_multipage() → Handle multi-page PDFs with sticky columns
		4. assign_tokens_to_columns() → Map tokens to columns by X-coordinate
		5. merge_description_wraparounds() → Combine multi-line descriptions
		6. normalize_all_items() → Parse Indonesian amounts
		7. validate_all_line_items() → Business rule validation
	
	Multi-Page Support:
		✅ Handles 1-N page PDFs
		✅ Sticky column detection (reuse header from page 1)
		✅ Strong totals detection on last page only
		✅ Global line numbering across pages
	
	Why Token-Based?
		- Accurate column mapping (X/Y coordinates)
		- Handles multi-line item descriptions
		- Solves regex parsing limitations for tabular data
		- Multi-page support out of the box
	
	⚠️ DO NOT USE FOR HEADERS
		For header/totals extraction, use:
		from imogi_finance.tax_invoice_ocr import parse_faktur_pajak_text
	
	Args:
		file_url_or_path: File URL (/private/files/xxx.pdf), File name, or path (🔥 Cloud-safe)
		vision_json: Google Vision OCR JSON result (for scanned PDFs)
		tax_rate: PPN tax rate for validation (default 11%)
		pdf_path: DEPRECATED - use file_url_or_path instead (backward compatibility)
	
	Returns:
		Dictionary with:
			- items: List of line item dictionaries (empty if parsing failed)
			- debug_info: Debug metadata (source, token_count, page_count, tokens)
			- success: Boolean (True if parsing succeeded)
			- errors: List of error messages (empty if success)
	
	Example:
		>>> from imogi_finance.imogi_finance.parsers.faktur_pajak_parser import parse_invoice
		>>> result = parse_invoice(file_url_or_path="/private/files/faktur.pdf", tax_rate=0.11)
		>>> if result["success"]:
		...     for item in result["items"]:
		...         print(f"Line {item['line_no']}: {item['description']} - Rp {item['harga_jual']}")
		>>> else:
		...     print(f"Parsing failed: {result['errors']}")
	"""
	# Backward compatibility: pdf_path -> file_url_or_path
	if pdf_path and not file_url_or_path:
		file_url_or_path = pdf_path
	
	result = {
		"items": [],
		"debug_info": {},
		"success": False,
		"errors": []
	}
	
	try:
		# Step 1: Extract tokens (source-specific, Cloud-safe)
		tokens = extract_tokens(file_url_or_path=file_url_or_path, vision_json=vision_json)
		
		if not tokens:
			result["errors"].append("No text extracted from source")
			return result
		
		# Step 2: Parse tokens (source-agnostic)
		result = parse_tokens(tokens, tax_rate)
		
	except ValueError as e:
		# Handle invalid inputs
		result["errors"].append(str(e))
		frappe.logger().error(f"Invalid input: {str(e)}")
	except Exception as e:
		error_msg = f"Parsing failed: {str(e)}"
		result["errors"].append(error_msg)
		frappe.log_error(
			title="Tax Invoice Parsing Error",
			message=f"Error: {str(e)}\n{frappe.get_traceback()}"
		)
	
	return result


def _parse_multipage(tokens: List[Token], tax_rate: float) -> Dict[str, Any]:
	"""
	Parse multi-page invoice with per-page column detection and sticky columns.
	
	Works with BOTH PyMuPDF and Vision OCR tokens.
	Used for ALL invoices regardless of page count (including page_count=1).
	
	Key features:
	- Per-page header detection with sticky columns
	- Header keyword skipping on subsequent pages
	- Strong totals detection (last page only)
	- Global line numbering across all pages
	- Per-page debug summary
	
	Args:
		tokens: All tokens from all pages (any source)
		tax_rate: PPN tax rate
	
	Returns:
		Dictionary with items and debug_info
	"""
	# Determine page count
	page_count = max(t.page_no for t in tokens) if tokens else 1
	
	result = {
		"items": [],
		"debug_info": {
			"page_count": page_count,
			"pages": []
		}
	}
	
	# State carried across pages
	previous_column_ranges = None
	previous_format_type = None
	global_line_no = 1
	
	# Header keywords to skip on continuation pages
	HEADER_SKIP_KEYWORDS = [
		"harga jual", "dasar pengenaan", "dpp", "ppn",
		"nama barang", "kode barang", "no.", "no"
	]
	
	# Strong totals keywords (need 2+ to trigger table end)
	TOTALS_KEYWORDS = [
		"jumlah", "total", "grand total", "subtotal",
		"dasar pengenaan pajak", "dikurangi potongan"
	]
	
	# 🔥 Summary row keywords - rows containing these are NEVER valid line items
	# This is the LAST LINE OF DEFENSE against summary rows leaking into items
	SUMMARY_ROW_KEYWORDS = {
		"harga jual / pengganti",
		"harga jual/pengganti",
		"dasar pengenaan pajak",
		"jumlah ppn",
		"jumlah ppnbm",
		"ppn = ",
		"ppnbm = ",
		"grand total",
		"potongan harga",
		"uang muka",
		"nilai lain",
	}
	
	for page_no in range(1, page_count + 1):
		frappe.logger().debug(f"Processing page {page_no}/{page_count}")
		
		page_result = _parse_page(
			tokens=tokens,
			page_no=page_no,
			tax_rate=tax_rate,
			previous_column_ranges=previous_column_ranges,
			previous_format_type=previous_format_type,
			global_line_no=global_line_no,
			header_skip_keywords=HEADER_SKIP_KEYWORDS,
			totals_keywords=TOTALS_KEYWORDS,
			is_last_page=(page_no == page_count)
		)
		
		# Accumulate items
		result["items"].extend(page_result["items"])
		
		# Update state for next page
		previous_column_ranges = page_result.get("column_ranges")
		previous_format_type = page_result.get("format_type")
		global_line_no += len(page_result["items"])
		
		# Store per-page debug info
		page_debug = {
			"page_no": page_no,
			"items_count": len(page_result["items"]),
			"format_type": page_result.get("format_type"),
			"used_sticky_columns": page_result.get("used_sticky_columns", False),
			"table_end_y": page_result.get("table_end_y")
		}
		
		# Add column ranges to debug (only if detected)
		if page_result.get("column_ranges"):
			page_debug["column_ranges"] = {
				k: v.to_dict() for k, v in page_result.get("column_ranges", {}).items()
			}
		
		result["debug_info"]["pages"].append(page_debug)
	
	# Set format_type at document level (use first page's type)
	if result["debug_info"]["pages"]:
		result["debug_info"]["format_type"] = result["debug_info"]["pages"][0]["format_type"]
	
	return result


def _parse_page(
	tokens: List[Token],
	page_no: int,
	tax_rate: float,
	previous_column_ranges: Optional[Dict[str, ColumnRange]],
	previous_format_type: Optional[str],
	global_line_no: int,
	header_skip_keywords: List[str],
	totals_keywords: List[str],
	is_last_page: bool
) -> Dict[str, Any]:
	"""Parse a single page from multi-page document."""
	page_result = {
		"items": [],
		"column_ranges": None,
		"format_type": None,
		"table_end_y": None,
		"used_sticky_columns": False
	}
	
	# Filter tokens for this page
	page_tokens = [t for t in tokens if t.page_no == page_no]
	
	if not page_tokens:
		frappe.logger().warning(f"No tokens on page {page_no}")
		return page_result
	
	# Try detect header
	header_y, column_ranges, format_type = detect_table_header(page_tokens)
	
	# Sticky columns: reuse from previous page if not found
	if (not column_ranges or not header_y) and previous_column_ranges and page_no > 1:
		frappe.logger().info(f"Page {page_no}: Using sticky columns from previous page")
		column_ranges = previous_column_ranges
		format_type = previous_format_type
		header_y = _find_first_non_header_row(page_tokens, header_skip_keywords)
		page_result["used_sticky_columns"] = True
	
	if not column_ranges:
		frappe.logger().warning(f"Page {page_no}: No columns detected, skipping page")
		return page_result
	
	page_result["column_ranges"] = column_ranges
	page_result["format_type"] = format_type
	
	# Find table end (strong detection on last page only)
	if is_last_page:
		table_end_y = _find_table_end_strong(page_tokens, header_y, totals_keywords, min_keywords=2)
	else:
		# On continuation pages, parse until end of page (no early stop)
		table_end_y = None
	
	page_result["table_end_y"] = table_end_y
	
	# Filter table tokens
	table_tokens = [t for t in page_tokens if t.y0 > header_y]
	if table_end_y:
		table_tokens = [t for t in table_tokens if t.y0 < table_end_y]
	
	# Cluster into rows
	rows = cluster_tokens_by_row(table_tokens, y_tolerance=3)
	
	# Parse each row
	parsed_rows = []
	for y_pos, row_tokens in rows:
		column_assignments = assign_tokens_to_columns(row_tokens, column_ranges)
		
		if format_type == "multi_column":
			row_data = {
				"row_y": y_pos,
				"page_no": page_no,
				"harga_jual": get_rightmost_value(column_assignments.get("harga_jual", [])),
				"dpp": get_rightmost_value(column_assignments.get("dpp", [])),
				"ppn": get_rightmost_value(column_assignments.get("ppn", [])),
			}
		else:
			row_data = {
				"row_y": y_pos,
				"page_no": page_no,
				"harga_jual": get_rightmost_value(column_assignments.get("harga_jual", [])),
				"dpp": None,
				"ppn": None,
			}
		
		# Get description
		desc_tokens = [t for t in row_tokens 
		               if not any(t in col_list for col_list in column_assignments.values())]
		row_data["description"] = " ".join([t.text for t in desc_tokens]) if desc_tokens else ""
		
		parsed_rows.append(row_data)
	
	# Merge wraparounds
	merged_rows = merge_description_wraparounds(parsed_rows)
	
	# 🔥 CRITICAL FIX: Filter out summary rows that leaked past table_end detection
	# Summary section rows (e.g., "Harga Jual / Pengganti", "Dasar Pengenaan Pajak")
	# are NEVER valid line items - they belong to the totals footer
	SUMMARY_ROW_KEYWORDS = {
		"harga jual / pengganti",
		"harga jual/pengganti", 
		"dasar pengenaan pajak",
		"jumlah ppn",
		"jumlah ppnbm",
		"ppn = ",
		"ppnbm = ",
		"grand total",
		"potongan harga",
		"uang muka",
		"nilai lain",
	}
	
	def _is_summary_row(description: str) -> bool:
		"""Check if row description matches summary/totals section keywords."""
		if not description:
			return False
		text_lower = description.lower().strip()
		return any(kw in text_lower for kw in SUMMARY_ROW_KEYWORDS)
	
	filtered_rows = []
	for row in merged_rows:
		desc = row.get("description", "")
		if _is_summary_row(desc):
			frappe.logger().info(
				f"[PARSE] Skipping summary row: '{desc[:50]}...' (page {row.get('page_no')})"
			)
			continue
		filtered_rows.append(row)
	
	# Log if any rows were filtered
	filtered_count = len(merged_rows) - len(filtered_rows)
	if filtered_count > 0:
		frappe.logger().info(f"[PARSE] Filtered {filtered_count} summary row(s) from page {page_no}")
	
	# Assign global line numbers
	for row in filtered_rows:
		row["line_no"] = global_line_no
		row["raw_harga_jual"] = row.get("harga_jual", "") or ""
		row["raw_dpp"] = row.get("dpp", "") or ""
		row["raw_ppn"] = row.get("ppn", "") or ""
		global_line_no += 1
	
	page_result["items"] = filtered_rows
	return page_result


def _find_first_non_header_row(tokens: List[Token], skip_keywords: List[str]) -> float:
	"""Find first row without header keywords (for continuation pages)."""
	rows = cluster_tokens_by_row(tokens, y_tolerance=5)
	
	for y_pos, row_tokens in rows:
		row_text = " ".join([t.text.lower() for t in row_tokens])
		has_header = any(kw.lower() in row_text for kw in skip_keywords)
		
		if not has_header:
			return y_pos
	
	return rows[0][0] if rows else 0.0


def _find_table_end_strong(
	tokens: List[Token],
	header_y: float,
	totals_keywords: List[str],
	min_keywords: int = 2
) -> Optional[float]:
	"""
	Find table end with strong detection (requires 2+ keywords).
	
	Prevents early termination on ambiguous single keywords like "Total" in descriptions.
	"""
	below_header = [t for t in tokens if t.y0 > header_y]
	rows = cluster_tokens_by_row(below_header, y_tolerance=5)
	
	for y_pos, row_tokens in rows:
		row_text = " ".join([t.text.lower() for t in row_tokens])
		
		keyword_count = sum(1 for kw in totals_keywords if kw in row_text)
		
		if keyword_count >= min_keywords:
			frappe.logger().info(f"Strong totals block at Y={y_pos:.1f} ({keyword_count} keywords)")
			return y_pos
		
		# Special case: "Dasar Pengenaan Pajak" alone is strong signal
		if "dasar pengenaan pajak" in row_text:
			return y_pos
	
	return None


def parse_tokens(tokens: List[Token], tax_rate: float = 0.11) -> Dict[str, Any]:
	"""
	Pure parsing function: convert tokens to structured line items.
	
	Parser layer - only accepts Token list, agnostic to source (PyMuPDF or Vision OCR).
	Always uses multi-page parser for consistency (works for page_count=1 too).
	
	Args:
		tokens: List of Token objects from any source
		tax_rate: PPN tax rate for validation (default 11%)
	
	Returns:
		Dictionary with:
			- items: List of line item dictionaries
			- debug_info: Debug metadata
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
		if not tokens:
			result["errors"].append("No tokens provided")
			return result
		
		# Determine source and page count
		page_count = max(t.page_no for t in tokens) if tokens else 1
		source = tokens[0].source if tokens else "unknown"
		
		result["debug_info"]["source"] = source
		result["debug_info"]["token_count"] = len(tokens)
		result["debug_info"]["page_count"] = page_count
		
		# Store tokens in debug info (truncate if too large)
		MAX_DEBUG_TOKENS = 500
		if len(tokens) <= MAX_DEBUG_TOKENS:
			result["debug_info"]["tokens"] = [t.to_dict() for t in tokens]
		else:
			result["debug_info"]["tokens"] = (
				[t.to_dict() for t in tokens[:100]] +
				[{"text": f"... {len(tokens) - 200} tokens truncated ...", "bbox": [0, 0, 0, 0], "page_no": 0}] +
				[t.to_dict() for t in tokens[-100:]]
			)
			result["debug_info"]["tokens_truncated"] = True
		
		# ALWAYS use multi-page parser (works for page_count=1 too)
		# No separate single-page legacy path
		multi_result = _parse_multipage(tokens, tax_rate)
		result.update(multi_result)
		
		result["success"] = True
		frappe.logger().info(
			f"Successfully parsed {len(result['items'])} line items from {page_count} page(s) ({source})"
		)
		
	except Exception as e:
		error_msg = f"Parsing failed: {str(e)}"
		result["errors"].append(error_msg)
		frappe.log_error(
			title="Tax Invoice Parsing Error",
			message=f"Error: {str(e)}\n{frappe.get_traceback()}"
		)
	
	return result
