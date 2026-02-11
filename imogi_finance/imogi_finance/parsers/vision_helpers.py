# -*- coding: utf-8 -*-
# Copyright (c) 2026, Imogi Finance and contributors
# For license information, please see license.txt

"""
Helper utilities for Google Vision API response processing.
"""

from typing import Dict, Any, Optional, List


def _resolve_full_text_annotation(vision_json: Dict[str, Any]) -> Optional[Dict[str, Any]]:
	"""
	Extract fullTextAnnotation from Vision API JSON response.
	
	🔥 FIX: For multi-page PDFs, MERGE all pages from all responses.
	Google Vision returns separate response entries for each page.
	
	Handles:
	  1. Direct: {"fullTextAnnotation": {...}}
	  2. Single response: {"responses": [{"fullTextAnnotation": {...}}]}
	  3. Multi-page: {"responses": [{"fullTextAnnotation": page1}, {"fullTextAnnotation": page2}]}
	  4. Nested: {"responses": [{"responses": [{"fullTextAnnotation": ...}]}]}
	
	Args:
		vision_json: Raw Vision API JSON response
		
	Returns:
		Merged fullTextAnnotation dict with combined pages, or None if not found
	"""
	if not vision_json:
		return None
	
	all_pages: List[Dict[str, Any]] = []
	all_text_parts: List[str] = []
	
	def _extract_from_entry(entry: Dict[str, Any]) -> None:
		"""Extract pages from a single response entry."""
		fta = entry.get("fullTextAnnotation")
		if fta:
			text = fta.get("text", "")
			pages = fta.get("pages", [])
			if text:
				all_text_parts.append(text)
			if pages:
				all_pages.extend(pages)
	
	def _process_responses(responses: List[Dict[str, Any]]) -> None:
		"""Process a list of response entries."""
		for response in responses:
			if not isinstance(response, dict):
				continue
			
			# Check for nested responses
			nested = response.get("responses")
			if isinstance(nested, list) and len(nested) > 0:
				_process_responses(nested)
			else:
				_extract_from_entry(response)
	
	# Handle nested responses array format
	if "responses" in vision_json and isinstance(vision_json["responses"], list):
		_process_responses(vision_json["responses"])
	else:
		# Handle direct response format
		_extract_from_entry(vision_json)
	
	# If we found any pages, return merged result
	if all_pages or all_text_parts:
		return {
			"text": "\n".join(all_text_parts),
			"pages": all_pages,
		}
	
	return None
