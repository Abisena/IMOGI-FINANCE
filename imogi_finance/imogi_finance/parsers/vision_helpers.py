# -*- coding: utf-8 -*-
# Copyright (c) 2026, Imogi Finance and contributors
# For license information, please see license.txt

"""
Helper utilities for Google Vision API response processing.
"""

from typing import Dict, Any, Optional


def _resolve_full_text_annotation(vision_json: Dict[str, Any]) -> Optional[str]:
	"""
	Extract full text from Vision API JSON response.
	
	Handles both direct responses and nested 'responses' array format.
	
	Args:
		vision_json: Raw Vision API JSON response
		
	Returns:
		Full extracted text or None if not found
	"""
	if not vision_json:
		return None
	
	# Handle nested responses array format
	if "responses" in vision_json and isinstance(vision_json["responses"], list):
		if len(vision_json["responses"]) > 0:
			response = vision_json["responses"][0]
			full_text_annotation = response.get("fullTextAnnotation")
			if full_text_annotation:
				return full_text_annotation.get("text")
	
	# Handle direct response format
	full_text_annotation = vision_json.get("fullTextAnnotation")
	if full_text_annotation:
		return full_text_annotation.get("text")
	
	return None
