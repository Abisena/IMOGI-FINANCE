from __future__ import annotations

import base64
import json
import math
import os
import re
import subprocess
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import frappe
from frappe import _
from frappe.exceptions import ValidationError
from frappe.utils import cint, flt, get_site_path
from frappe.utils.formatters import format_value

from imogi_finance import tax_invoice_fields

background_jobs = getattr(frappe.utils, "background_jobs", None)

SETTINGS_DOCTYPE = "Tax Invoice OCR Settings"
DEFAULT_SETTINGS = {
    "enable_tax_invoice_ocr": 0,
    "ocr_provider": "Manual Only",
    "ocr_language": "id",
    "ocr_max_pages": 2,
    "ocr_min_confidence": 0.85,
    "ocr_max_retry": 1,
    "ocr_file_max_mb": 10,
    "store_raw_ocr_json": 1,
    "require_verification_before_submit_pi": 1,
    "require_verification_before_create_pi_from_expense_request": 1,
    "npwp_normalize": 1,
    "tolerance_idr": 10000,
    "tolerance_percentage": 1.0,
    "block_duplicate_fp_no": 1,
    "ppn_input_account": None,
    "ppn_output_account": None,
    "dpp_variance_account": None,
    "ppn_variance_account": None,
    "default_ppn_type": "Standard",
    "use_tax_rule_effective_date": 1,
    "google_vision_service_account_file": None,
    "google_vision_endpoint": "https://vision.googleapis.com/v1/files:annotate",
    "tesseract_cmd": None,
}

ALLOWED_OCR_FIELDS = {"fp_no", "fp_date", "npwp", "harga_jual", "dpp", "ppn", "ppnbm", "ppn_type", "tax_rate", "notes"}


def _raise_validation_error(message: str):
    try:
        frappe.throw(message, exc=ValidationError)
    except ValidationError:
        raise
    except Exception:
        raise ValidationError(message)


def get_settings() -> dict[str, Any]:
    if not frappe.db:
        return DEFAULT_SETTINGS.copy()

    settings_map = DEFAULT_SETTINGS.copy()
    getter = getattr(getattr(frappe, "db", None), "get_singles_dict", None)
    record = getter(SETTINGS_DOCTYPE) if callable(getter) else {}
    record = record or {}
    settings_map.update(record)
    settings_obj = frappe._dict(settings_map)
    if not hasattr(settings_obj, "get"):
        settings_obj.get = lambda key, default=None: getattr(settings_obj, key, default)
    return settings_obj


def _normalize_google_vision_path(path: str | None, *, is_pdf: bool = True) -> str:
    """
    Normalize Google Vision endpoint path.
    For PDF OCR, ONLY files:annotate is supported.
    """

    if not path:
        endpoint = "files:annotate"
    else:
        endpoint = path.strip()

        # jika user isi full URL atau /v1/xxx
        if endpoint.startswith("http"):
            endpoint = endpoint.split("/v1/")[-1]

        endpoint = endpoint.lstrip("/")

    if is_pdf and endpoint != "files:annotate":
        _raise_validation_error(
            _("PDF OCR must use Google Vision 'files:annotate' endpoint.")
        )

    if endpoint not in {"files:annotate", "images:annotate"}:
        _raise_validation_error(
            _("Unsupported Google Vision endpoint: {0}").format(endpoint)
        )

    return endpoint


def normalize_npwp(npwp: str | None) -> str | None:
    """
    Normalize NPWP by removing dots, dashes, and spaces.
    
    Use this function when you already have an NPWP string and need to normalize it.
    
    For EXTRACTING NPWP from raw OCR text, use:
        from imogi_finance.imogi_finance.parsers.normalization import extract_npwp
        npwp = extract_npwp(ocr_text)  # Extracts + normalizes
    
    Args:
        npwp: NPWP string (may contain formatting like dots/dashes)
    
    Returns:
        Normalized NPWP (digits only) or None
    """
    if not npwp:
        return npwp
    settings = get_settings()
    if cint(settings.get("npwp_normalize")):
        return re.sub(r"[.\-\s]", "", npwp or "")
    return npwp


NPWP_REGEX = re.compile(r"(?P<npwp>\d{2}\.\d{3}\.\d{3}\.\d-\d{3}\.\d{3}|\d{15,20})")
NPWP_LABEL_REGEX = re.compile(r"NPWP\s*[:\-]?\s*(?P<npwp>[\d.\-\s]{10,})", re.IGNORECASE)
PPN_RATE_REGEX = re.compile(r"(?:Tarif\s*)?PPN[^\d%]{0,10}(?P<rate>\d{1,2}(?:[.,]\d+)?)\s*%", re.IGNORECASE)
TAX_INVOICE_REGEX = re.compile(r"(?P<fp>\d{2,3}[.\-\s]?\d{2,3}[.\-\s]?\d{1,2}[.\-\s]?\d{8})")
DATE_REGEX = re.compile(r"(?P<date>\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4})")
NUMBER_REGEX = re.compile(r"(?P<number>\d+[.,\d]*)")
AMOUNT_REGEX = re.compile(r"(?P<amount>\d{1,3}(?:[.,]\d{3})*[.,]\d{2})")
FAKTUR_NO_LABEL_REGEX = re.compile(
    r"Kode\s+dan\s+Nomor\s+Seri\s+Faktur\s+Pajak\s*[:\-]?\s*(?P<fp>[\d.\-\s]{10,})",
    re.IGNORECASE,
)
INDO_DATE_REGEX = re.compile(r"(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})")
INDO_MONTHS = {
    "januari": 1,
    "februari": 2,
    "maret": 3,
    "april": 4,
    "mei": 5,
    "juni": 6,
    "juli": 7,
    "agustus": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "desember": 12,
}


def infer_tax_rate(dpp: float = None, ppn: float = None, fp_date: str = None) -> float:
    """
    Infer effective PPN tax rate based on actual values or document date.
    
    Priority:
        1. Infer from actual ppn/dpp ratio (if both valid and ratio in 8-13% range)
        2. Based on fp_date: >= 2025-01-01 → 12%, else 11%
        3. Default: 0.11 (backward compatible)
    
    Args:
        dpp: Dasar Pengenaan Pajak (tax base)
        ppn: Pajak Pertambahan Nilai (VAT amount)
        fp_date: Faktur Pajak date (ISO format: YYYY-MM-DD)
    
    Returns:
        Tax rate as float (0.11 or 0.12)
    
    Example:
        >>> infer_tax_rate(dpp=1010625, ppn=121275, fp_date="2025-12-20")
        0.12
        >>> infer_tax_rate(dpp=1000000, ppn=110000, fp_date="2024-06-15")
        0.11
    """
    # Priority 1: Infer from actual values
    if dpp and ppn and dpp > 0:
        ratio = ppn / dpp
        # Round to 2 decimal places for comparison
        if 0.10 <= ratio <= 0.13:
            # Return closest standard rate
            if abs(ratio - 0.11) < abs(ratio - 0.12):
                return 0.11
            else:
                return 0.12
    
    # Priority 2: Based on document date (PPN 12% effective 1 Jan 2025)
    if fp_date:
        try:
            from datetime import datetime
            if isinstance(fp_date, str):
                # Handle ISO format and common date formats
                for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
                    try:
                        date_obj = datetime.strptime(fp_date, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    date_obj = None
            else:
                date_obj = fp_date
            
            if date_obj and date_obj.year >= 2025:
                return 0.12
        except Exception:
            pass
    
    # Priority 3: Default (backward compatible)
    return 0.11


def _get_fieldname(doctype: str, key: str) -> str:
    mapping = tax_invoice_fields.get_field_map(doctype)
    return mapping.get(key, key)


def _get_value(doc: Any, doctype: str, key: str, default: Any = None) -> Any:
    fieldname = _get_fieldname(doctype, key)
    return getattr(doc, fieldname, default)


def _get_upload_link_field(doctype: str) -> str | None:
    return tax_invoice_fields.get_upload_link_field(doctype)


def get_linked_tax_invoice_uploads(
    *, exclude_doctype: str | None = None, exclude_name: str | None = None
) -> set[str]:
    targets = ("Purchase Invoice", "Expense Request", "Branch Expense Request")
    uploads: set[str] = set()

    for target in targets:
        fieldname = _get_upload_link_field(target)
        if not fieldname:
            continue

        filters: dict[str, Any] = {fieldname: ("!=", None)}
        filters["docstatus"] = ("<", 2)
        if exclude_name and target == exclude_doctype:
            filters["name"] = ("!=", exclude_name)

        try:
            linked = frappe.get_all(target, filters=filters, pluck=fieldname) or []
        except Exception:
            continue

        uploads.update(linked)

    return {name for name in uploads if name}


def _find_existing_upload_link(
    upload_name: str, current_doctype: str, current_name: str | None = None
) -> tuple[str | None, str | None]:
    targets = ("Purchase Invoice", "Expense Request", "Branch Expense Request")

    for target in targets:
        fieldname = _get_upload_link_field(target)
        if not fieldname:
            continue

        filters: dict[str, Any] = {fieldname: upload_name, "docstatus": ("<", 2)}
        if current_name and target == current_doctype:
            filters["name"] = ("!=", current_name)

        try:
            matches = frappe.get_all(target, filters=filters, pluck="name", limit=1) or []
        except Exception:
            continue

        if matches:
            return target, matches[0]
    return None, None


def validate_tax_invoice_upload_link(doc: Any, doctype: str):
    link_field = _get_upload_link_field(doctype)
    if not link_field:
        return

    fp_no = _get_value(doc, doctype, "fp_no")
    upload = getattr(doc, link_field, None)
    has_manual_fields = any(
        _get_value(doc, doctype, key)
        for key in ("fp_no", "fp_date", "npwp", "harga_jual", "dpp", "ppn", "ppnbm")
    )

    if not upload:
        if has_manual_fields:
            raise ValidationError(_("Please select a verified Tax Invoice OCR Upload for the Faktur Pajak."))
        return

    status = frappe.db.get_value("Tax Invoice OCR Upload", upload, "verification_status")
    if status != "Verified":
        raise ValidationError(_("Tax Invoice OCR Upload {0} must be Verified.").format(upload))

    existing_doctype, existing_name = _find_existing_upload_link(upload, doctype, getattr(doc, "name", None))
    if existing_doctype and existing_name:
        if existing_doctype == "Expense Request" and doctype == "Purchase Invoice":
            request_name = doc.get("imogi_expense_request") or doc.get("expense_request")
            expense_request = frappe.db.get_value(
                "Expense Request",
                existing_name,
                ["name", "linked_purchase_invoice", "pending_purchase_invoice"],
                as_dict=True,
            )
            if expense_request:
                linked_pi = expense_request.get("linked_purchase_invoice")
                pending_pi = expense_request.get("pending_purchase_invoice")
                if existing_name == request_name or doc.name in {linked_pi, pending_pi}:
                    return

        raise ValidationError(
            _("Tax Invoice OCR Upload {0} is already used in {1} {2}. Please select another Faktur Pajak.")
            .format(upload, existing_doctype, existing_name)
        )


def get_tax_invoice_upload_context(target_doctype: str | None = None, target_name: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    provider_ready, provider_error = _get_provider_status(settings)
    used_uploads = sorted(
        get_linked_tax_invoice_uploads(exclude_doctype=target_doctype, exclude_name=target_name)
    )
    verified_uploads = []
    try:
        verified_uploads = frappe.get_all(
            "Tax Invoice OCR Upload",
            filters={
                "verification_status": "Verified",
                **({"name": ("not in", used_uploads)} if used_uploads else {}),
            },
            fields=["name", "fp_no", "fp_date", "npwp", "harga_jual", "dpp", "ppn", "ppnbm", "ppn_type"],
        )
    except Exception:
        verified_uploads = []
    return {
        "enable_tax_invoice_ocr": cint(settings.get("enable_tax_invoice_ocr", 0)),
        "ocr_provider": settings.get("ocr_provider") or "Manual Only",
        "provider_ready": provider_ready,
        "provider_error": provider_error,
        "used_uploads": used_uploads,
        "verified_uploads": verified_uploads,
    }


def _set_value(doc: Any, doctype: str, key: str, value: Any) -> None:
    fieldname = _get_fieldname(doctype, key)
    setattr(doc, fieldname, value)


def _copy_tax_invoice_fields(source_doc: Any, source_doctype: str, target_doc: Any, target_doctype: str):
    source_map = tax_invoice_fields.get_field_map(source_doctype)
    target_map = tax_invoice_fields.get_field_map(target_doctype)
    for key in tax_invoice_fields.iter_copy_keys():
        if key not in source_map or key not in target_map:
            continue
        value = _get_value(source_doc, source_doctype, key)
        _set_value(target_doc, target_doctype, key, value)
        if target_doctype == "Sales Invoice" and key == "npwp":
            setattr(target_doc, "out_buyer_tax_id", value)


def _extract_section(text: str, start_label: str, end_label: str | None = None) -> str:
    if not text:
        return ""
    lower_text = text.lower()
    start_index = lower_text.find(start_label.lower())
    if start_index < 0:
        return text
    if end_label:
        end_index = lower_text.find(end_label.lower(), start_index)
        if end_index > start_index:
            return text[start_index:end_index]
    return text[start_index:]


def _parse_idr_amount(value: str) -> float:
    """
    LEGACY WRAPPER: Parse Indonesian Rupiah amount format.
    
    Delegates to parsers.normalization.parse_idr_amount for unified logic.
    Maintained for backward compatibility with existing code.
    
    Indonesian format:
    - Thousand separator: . (dot)
    - Decimal separator: , (comma)
    - Example: "1.234.567,89" -> 1234567.89
    
    Args:
        value: String representation of IDR amount
    
    Returns:
        Float value (defaults to 0.0 if parsing fails)
    """
    from imogi_finance.imogi_finance.parsers.normalization import parse_idr_amount
    result = parse_idr_amount(value)
    return result if result is not None else 0.0


def _sanitize_amount(value: Any, *, max_abs: float = 9_999_999_999_999.99) -> float | None:
    try:
        number = flt(value)
    except Exception:
        return None

    if not math.isfinite(number):
        return None
    if abs(number) > max_abs:
        return None
    return number


def _extract_section_lines(text: str, start_label: str, stop_labels: tuple[str, ...]) -> list[str]:
    lines = text.splitlines()
    start_idx = next((idx for idx, line in enumerate(lines) if start_label.lower() in line.lower()), None)
    if start_idx is None:
        return []

    collected: list[str] = []
    for line in lines[start_idx:]:
        normalized = line.lower().strip()
        if any(normalized.startswith(stop.lower()) for stop in stop_labels):
            break
        collected.append(line.strip())
    return collected


def _extract_first_after_label(section_lines: list[str], label: str) -> str | None:
    pattern = re.compile(rf"{re.escape(label)}\s*[:\-]?\s*(?P<value>.+)", re.IGNORECASE)
    for line in section_lines:
        match = pattern.search(line)
        if match:
            return match.group("value").strip()
    return None


def _find_amount_after_label(text: str, label: str, max_lines_to_check: int = 5) -> float | None:
    """
    Find amount after a label in text.

    Args:
        text: Text to search in
        label: Label to search for
        max_lines_to_check: Maximum number of non-empty lines to check after label (default: 5)

    Returns:
        Float amount if found, None otherwise
    """
    def _extract_amount(line: str) -> float | None:
        # 🔧 FIX 1: Enhanced skip keywords to include reference patterns
        skip_keywords = [
            "Referensi:", "Reference:", "Invoice:", "INV-", "/MTLA/", "/GMM/",
            "Pemberitahuan:", "PERINGATAN:", "(Referensi", "Nomor Referensi",
            "No. Ref", "Faktur", "No. Invoice"
        ]
        if any(keyword in line for keyword in skip_keywords):
            logger.info(f"🔍 _extract_amount: Skipping line with reference keyword: '{line[:80]}'")
            return None

        # ONLY match amounts with proper currency format (has decimal separator)
        amount_match = AMOUNT_REGEX.search(line or "")
        if amount_match:
            amount = _sanitize_amount(_parse_idr_amount(amount_match.group("amount")))
            # For Harga Jual, typically should be at least 10,000 IDR
            if amount is not None and amount >= 10000:
                return amount
            elif amount is not None:
                logger.info(f"🔍 _extract_amount: Amount {amount} too small (< 10000), ignoring")
        return None

    logger = frappe.logger("tax_invoice_ocr")

    # Normalize label: handle multiple spaces and slash variations
    normalized_label = re.sub(r'\s+', r'\\s+', label.strip())
    normalized_label = normalized_label.replace('/', r'\s*/\s*')

    logger.info(f"🔍 _find_amount_after_label: Searching for label '{label}' with pattern: {normalized_label}")

    pattern = re.compile(rf"{normalized_label}\s*[:\-]?\s*(?P<value>.*)", re.IGNORECASE)
    lines = (text or "").splitlines()

    for idx, line in enumerate(lines):
        match = pattern.search(line)
        if not match:
            continue

        logger.info(f"🔍 _find_amount_after_label: Found label '{label}' at line {idx}: '{line[:100]}'")

        # 🔧 PRIORITY 1: For table format, check the END of the same line first (rightmost value)
        # This handles format: "Harga Jual / Penggantian / Uang Muka / Termin     1.049.485,00"
        all_amounts_in_line = []
        for amt_match in AMOUNT_REGEX.finditer(line):
            amt = _sanitize_amount(_parse_idr_amount(amt_match.group("amount")))
            if amt is not None and amt >= 10000:
                all_amounts_in_line.append((amt, amt_match.end()))  # Store amount and position

        if all_amounts_in_line:
            # Get the rightmost amount (last in the line, which is typically the value in table format)
            all_amounts_in_line.sort(key=lambda x: x[1])  # Sort by position
            rightmost_amount = all_amounts_in_line[-1][0]
            logger.info(f"🔍 _find_amount_after_label: Found {len(all_amounts_in_line)} amounts in line, using RIGHTMOST (table format): {rightmost_amount}")
            return rightmost_amount

        # PRIORITY 2: Check if amount is after the label in the same line
        inline_value = match.group("value") or ""
        inline_amount = _extract_amount(inline_value)
        if inline_amount is not None:
            logger.info(f"🔍 _find_amount_after_label: Found inline amount after label: {inline_amount}")
            return inline_amount

        # If not found in same line, check next few non-empty lines
        logger.info(f"🔍 _find_amount_after_label: No inline amount, checking next {max_lines_to_check} lines")
        lines_checked = 0
        for offset, next_line in enumerate(lines[idx + 1 :], start=1):
            if not next_line.strip():
                continue

            logger.info(f"🔍 _find_amount_after_label: Checking line {idx + offset}: '{next_line[:80]}'")

            next_amount = _extract_amount(next_line)
            if next_amount is not None:
                logger.info(f"🔍 _find_amount_after_label: Found amount in next line: {next_amount}")
                return next_amount

            lines_checked += 1
            if lines_checked >= max_lines_to_check:
                logger.info(f"🔍 _find_amount_after_label: Reached max {max_lines_to_check} lines, stopping")
                break

    logger.info(f"🔍 _find_amount_after_label: Label '{label}' not found or no amount extracted")
    return None


def _extract_harga_jual_from_signature_section(text: str) -> float | None:
    """
    🔧 FIXED VERSION V3: Extract Harga Jual with robust multi-strategy approach.

    Improvements:
    1. Try label-based extraction FIRST (most reliable)
    2. Improved signature regex with better amount capture
    3. Line-by-line parsing with enhanced filtering
    4. Aggressive fallback for edge cases
    """
    logger = frappe.logger("tax_invoice_ocr")
    logger.info("🔍 _extract_harga_jual_from_signature_section: Starting V3 extraction")

    if not text:
        logger.info("🔍 _extract_harga_jual_from_signature_section: No text provided, returning None")
        return None

    # 🔧 STRATEGY 0: Try label-based extraction FIRST (most reliable)
    logger.info("🔍 Strategy 0: Trying label-based extraction")
    label_patterns = [
        "Harga Jual/Penggantian/Uang Muka/Termin",
        "Harga Jual / Penggantian / Uang Muka / Termin",
        "Harga Jual",
    ]

    for pattern in label_patterns:
        labeled_value = _find_amount_after_label(text, pattern, max_lines_to_check=3)
        if labeled_value and labeled_value >= 10000:
            logger.info(f"🔍 Strategy 0: SUCCESS with pattern '{pattern}': {labeled_value}")
            return labeled_value

    logger.info("🔍 Strategy 0: Label-based extraction failed, trying signature patterns")

    # 🔧 STRATEGY 1: Improved regex pattern
    signature_pattern = re.compile(
        r'Ditandatangani\s+secara\s+elektronik\s*\n'  # Marker
        r'\s*([A-Z][A-Za-z\s\.]+?)\s*\n'              # Nama (must start with uppercase)
        r'(?:.*?\n){0,5}?'                             # Skip 0-5 lines non-greedy (for references/notes)
        r'\s*(\d[\d\s\.,]+?)(?=\s*\n)',               # Amount (positive lookahead to stop at newline)
        re.IGNORECASE | re.MULTILINE
    )

    logger.info("🔍 Strategy 1: Trying improved regex pattern matching")
    match = signature_pattern.search(text)
    if match:
        name_captured = match.group(1).strip()
        amount_str = match.group(2).strip()
        logger.info(f"🔍 Strategy 1: Regex matched! Name: '{name_captured}', Amount string: '{amount_str}'")

        parsed = _parse_idr_amount(amount_str)
        logger.info(f"🔍 Strategy 1: _parse_idr_amount returned: {parsed}")

        sanitized = _sanitize_amount(parsed)
        logger.info(f"🔍 Strategy 1: _sanitize_amount returned: {sanitized}")

        if sanitized and sanitized >= 10000:
            logger.info(f"🔍 Strategy 1: SUCCESS! Returning {sanitized}")
            return sanitized
        else:
            logger.info(f"🔍 Strategy 1: Amount {sanitized} too small or None, trying next strategy")
    else:
        logger.info("🔍 Strategy 1: Regex did not match, trying next strategy")

    # 🔧 FIX 3: Enhanced line-by-line parsing with better skip keywords
    logger.info("🔍 Strategy 2: Trying line-by-line parsing with enhanced filters")
    signature_marker_idx = text.find("Ditandatangani secara elektronik")
    if signature_marker_idx == -1:
        signature_marker_idx = text.lower().find("ditandatangani secara elektronik")

    if signature_marker_idx != -1:
        logger.info(f"🔍 Strategy 2: Found signature marker at index {signature_marker_idx}")
        after_signature = text[signature_marker_idx:]
        lines = after_signature.split('\n')
        logger.info(f"🔍 Strategy 2: Split into {len(lines)} lines after signature")

        found_name = False
        # 🔧 Enhanced skip keywords list
        skip_keywords = [
            "Harga", "Jual", "Penggantian", "Uang", "Muka", "Termin", "(Rp)",
            "Dikurangi", "Potongan", "Dasar", "Pengenaan", "Pajak", "Jumlah", "PPN", "PPnBM",
            # Reference/invoice patterns
            "Referensi:", "Reference:", "Invoice:", "INV-", "/MTLA/", "/GMM/",
            "Pemberitahuan:", "PERINGATAN:", "(Referensi", "Nomor Referensi",
            "No. Ref", "Faktur"
        ]

        for idx, line in enumerate(lines[1:], start=1):
            line = line.strip()

            if not line:
                continue

            # Check if this is likely a signer name
            if not found_name and len(line) > 3:
                clean_line = line.replace(' ', '').replace('.', '').replace(',', '')
                if clean_line.isalpha():
                    found_name = True
                    logger.info(f"🔍 Strategy 2: Found name at line {idx}: '{line}'")
                    continue

            # After finding the name, look for the first amount
            if found_name and line:
                # Skip lines containing label/reference keywords
                if any(keyword.lower() in line.lower() for keyword in skip_keywords):
                    logger.info(f"🔍 Strategy 2: Skipping line with keyword at {idx}: '{line[:50]}'")
                    continue

                # Check if this line contains only a number pattern
                if re.match(r'^\s*\d[\d\s\.,]+\s*$', line):
                    logger.info(f"🔍 Strategy 2: Found amount pattern at line {idx}: '{line}'")
                    parsed = _parse_idr_amount(line)
                    logger.info(f"🔍 Strategy 2: _parse_idr_amount returned: {parsed}")

                    sanitized = _sanitize_amount(parsed)
                    logger.info(f"🔍 Strategy 2: _sanitize_amount returned: {sanitized}")

                    if sanitized and sanitized >= 10000:
                        logger.info(f"🔍 Strategy 2: SUCCESS! Returning {sanitized}")
                        return sanitized
                    else:
                        logger.info(f"🔍 Strategy 2: Amount {sanitized} too small, continuing search")
    else:
        logger.info("🔍 Strategy 2: Signature marker not found")

    # Strategy 3: Aggressive fallback with better filtering
    logger.info("🔍 Strategy 3: Trying aggressive fallback")
    signature_marker_idx = text.find("Ditandatangani secara elektronik")
    if signature_marker_idx == -1:
        signature_marker_idx = text.lower().find("ditandatangani secara elektronik")

    if signature_marker_idx != -1:
        logger.info(f"🔍 Strategy 3: Found signature marker at index {signature_marker_idx}")
        after_signature = text[signature_marker_idx:]

        # Match standalone amounts - use positive lookahead to stop at newline
        amount_pattern = re.compile(r'(?:^|\n)\s*(\d[\d\s\.,]+?)(?=\s*\n)')

        matches_found = list(amount_pattern.finditer(after_signature))
        logger.info(f"🔍 Strategy 3: Found {len(matches_found)} amount patterns")

        for idx, match in enumerate(matches_found):
            amount_str = match.group(1).strip()
            logger.info(f"🔍 Strategy 3: Pattern {idx+1}: '{amount_str}'")

            parsed = _parse_idr_amount(amount_str)
            logger.info(f"🔍 Strategy 3: _parse_idr_amount returned: {parsed}")

            sanitized = _sanitize_amount(parsed)
            logger.info(f"🔍 Strategy 3: _sanitize_amount returned: {sanitized}")

            if sanitized and sanitized >= 10000:
                logger.info(f"🔍 Strategy 3: SUCCESS! Returning {sanitized}")
                return sanitized
            else:
                logger.info(f"🔍 Strategy 3: Amount {sanitized} too small, continuing...")
    else:
        logger.info("🔍 Strategy 3: Signature marker not found")

    logger.info("🔍 _extract_harga_jual_from_signature_section: All strategies failed, returning None")
    return None


def _extract_amounts_after_signature(text: str) -> list[float] | None:
    """
    🔧 FIXED VERSION V2: Extract all amounts from signature section.

    Key improvements:
    1. More aggressive reference line detection
    2. Better handling of parenthetical notes like "(Referensi: ...)"
    3. Stricter pure-amount line detection
    4. Debug logging untuk troubleshooting
    """
    logger = frappe.logger("tax_invoice_ocr")
    logger.info("🔍 _extract_amounts_after_signature: Starting extraction V2")

    if not text:
        return None

    # Find signature marker (case-insensitive)
    signature_marker_idx = text.lower().find("ditandatangani secara elektronik")
    if signature_marker_idx == -1:
        logger.info("🔍 _extract_amounts_after_signature: Signature marker not found")
        return None

    after_signature = text[signature_marker_idx:]
    logger.info(f"🔍 _extract_amounts_after_signature: Found signature at index {signature_marker_idx}")

    lines = after_signature.split('\n')
    found_name = False
    amounts = []

    # 🔧 ENHANCED: More comprehensive skip patterns
    skip_patterns = [
        # Labels
        r'harga\s+jual', r'penggantian', r'uang\s+muka', r'termin',
        r'dikurangi', r'potongan', r'dasar\s+pengenaan', r'pajak',
        r'jumlah\s+ppn', r'ppnbm', r'barang\s+mewah',
        r'nilai\s+pertambahan', r'\(rp\)',

        # Reference patterns - CRITICAL FIX for reference lines
        r'referensi\s*:', r'reference\s*:', r'invoice\s*:',
        r'\(referensi', r'nomor\s+referensi', r'no\.?\s*ref',
        r'faktur\s+\d+', r'inv[-/]\d', r'/mtla/', r'/gmm/',
        r'no\.?\s*inv', r'\binv-', r'\binv/',

        # Warnings/notices
        r'pemberitahuan\s*:', r'peringatan\s*:',
        r'sesuai\s+dengan', r'ketentuan',

        # 🔧 CRITICAL: Lines containing BOTH text and numbers (like "Referensi: INV/2024/001")
        # This catches mixed content that should not be treated as pure amounts
        r'[a-zA-Z]{2,}.*[:/].*\d',  # Text with : or / and digits
        r'\d.*[a-zA-Z]{2,}',          # Digits followed by text
    ]

    # Compile all patterns into one regex
    skip_regex = re.compile('|'.join(skip_patterns), re.IGNORECASE)

    for idx, line in enumerate(lines[1:], start=1):  # Skip first line (marker itself)
        line_stripped = line.strip()

        logger.info(f"🔍 Line {idx}: '{line_stripped[:80]}'")

        if not line_stripped:
            logger.info(f"🔍 Line {idx}: Empty, skipping")
            continue

        # Step 1: Find the signer name
        if not found_name:
            # Name detection: must be mostly alphabetic (allow spaces, dots, commas)
            clean_line = line_stripped.replace(' ', '').replace('.', '').replace(',', '')

            # Name must:
            # 1. Be at least 4 chars
            # 2. Be mostly letters (>80% alphabetic)
            # 3. Not contain numbers
            if len(clean_line) >= 4 and clean_line.isalpha():
                found_name = True
                logger.info(f"🔍 Line {idx}: ✓ Found name: '{line_stripped}'")
                continue
            else:
                logger.info(f"🔍 Line {idx}: Not a name (has numbers or too short)")
                continue

        # Step 2: After finding name, extract amounts
        if found_name:
            # 🔧 CRITICAL FIX: Skip lines matching any skip pattern
            if skip_regex.search(line_stripped):
                logger.info(f"🔍 Line {idx}: ⚠️ SKIPPED - matches skip pattern: '{line_stripped[:50]}'")
                continue

            # 🔧 CRITICAL FIX: Only accept lines that are PURELY amounts
            # Pattern: optional whitespace + digits/commas/dots/spaces + optional whitespace
            # NO letters, colons, slashes, or special chars allowed
            pure_amount_pattern = r'^\s*[\d\s\.,]+\s*$'

            if not re.match(pure_amount_pattern, line_stripped):
                logger.info(f"🔍 Line {idx}: ⚠️ SKIPPED - not pure amount (contains text): '{line_stripped[:50]}'")
                continue

            # 🔧 ADDITIONAL CHECK: Ensure it's not a date-like pattern (DD-MM-YYYY or similar)
            # Dates like "30-01-2024" could pass as amounts
            if re.match(r'^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$', line_stripped.replace(' ', '')):
                logger.info(f"🔍 Line {idx}: ⚠️ SKIPPED - looks like a date: '{line_stripped}'")
                continue

            # If we reach here, line is purely numeric
            logger.info(f"🔍 Line {idx}: ✓ Pure amount line detected: '{line_stripped}'")

            # Parse the amount
            try:
                parsed = _parse_idr_amount(line_stripped)
                logger.info(f"🔍 Line {idx}: Parsed value: {parsed}")

                sanitized = _sanitize_amount(parsed)
                logger.info(f"🔍 Line {idx}: Sanitized value: {sanitized}")

                if sanitized is not None:
                    amounts.append(sanitized)
                    logger.info(f"🔍 Line {idx}: ✅ Amount #{len(amounts)} added: {sanitized}")

                    # Standard Faktur Pajak has exactly 6 amounts in signature section
                    if len(amounts) >= 6:
                        logger.info(f"🔍 Line {idx}: Reached 6 amounts, stopping extraction")
                        break
                else:
                    logger.info(f"🔍 Line {idx}: ⚠️ Amount sanitized to None")

            except Exception as e:
                logger.error(f"🔍 Line {idx}: ❌ Error parsing amount: {e}")
                continue

    logger.info(f"🔍 _extract_amounts_after_signature: ===== FINAL RESULT =====")
    logger.info(f"🔍 _extract_amounts_after_signature: Total amounts: {len(amounts)}")
    logger.info(f"🔍 _extract_amounts_after_signature: Values: {amounts}")

    return amounts if amounts else None


def _pick_best_npwp(candidates: list[str]) -> str | None:
    valid = [normalize_npwp((val or "").strip()) for val in candidates if val]
    valid = [val for val in valid if val]
    if not valid:
        return None

    def _score(value: str) -> tuple[int, int, str]:
        preferred_len = 0 if len(value) in {15, 16} else 1
        return (preferred_len, len(value), value)

    return sorted(valid, key=_score)[0]


def _extract_npwp_from_text(text: str) -> str | None:
    candidates = [match.group("npwp") for match in NPWP_REGEX.finditer(text or "")]
    return _pick_best_npwp(candidates)


def _extract_npwp_with_label(text: str) -> str | None:
    candidates = [match.group("npwp") for match in NPWP_LABEL_REGEX.finditer(text or "")]
    return _pick_best_npwp(candidates)


def _extract_address(section_lines: list[str], label: str) -> str | None:
    address: list[str] = []
    capture = False
    for line in section_lines:
        if label.lower() in line.lower() and ":" in line:
            capture = True
            address.append(line.split(":", 1)[1].strip())
            continue
        if capture:
            if not line or any(stop in line.lower() for stop in ("npwp", "nik", "email", "pembeli", "kode")):
                break
            address.append(line.strip())
    if not address:
        return None
    return " ".join(part for part in address if part)


def _parse_date_from_text(text: str) -> str | None:
    date_match = DATE_REGEX.search(text or "")
    if date_match:
        raw_date = date_match.group("date")
        for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y"):
            try:
                return datetime.strptime(raw_date, fmt).date().isoformat()
            except Exception:
                continue

    indo_match = INDO_DATE_REGEX.search(text or "")
    if indo_match:
        try:
            day = int(indo_match.group("day"))
            month_name = indo_match.group("month").strip().lower()
            year = int(indo_match.group("year"))
            month = INDO_MONTHS.get(month_name)
            if month:
                return datetime(year, month, day).date().isoformat()
        except Exception:
            return None
    return None


def _normalize_faktur_number(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) < 10:
        return None
    return digits


def _extract_faktur_number_from_json(raw_json: dict[str, Any] | str | None) -> str | None:
    if not raw_json:
        return None

    payload: dict[str, Any] | None = None
    if isinstance(raw_json, dict):
        payload = raw_json
    elif isinstance(raw_json, str):
        try:
            payload = json.loads(raw_json)
        except Exception:
            payload = None

    if not isinstance(payload, dict):
        return None

    faktur_pajak = payload.get("faktur_pajak")
    if isinstance(faktur_pajak, dict):
        nomor_seri = faktur_pajak.get("nomor_seri")
        if nomor_seri:
            return _normalize_faktur_number(str(nomor_seri))

    return None


def parse_faktur_pajak_text(text: str) -> tuple[dict[str, Any], float]:
    """
    ⚠️ LEGACY HEADER/TOTALS EXTRACTOR - OCR Text-Based Parsing
    
    Scope:
        Extracts HEADER FIELDS and DOCUMENT TOTALS from OCR text using regex patterns.
        Does NOT extract line items (use parse_invoice() for that).
    
    Extracted Fields:
        - fp_no (Faktur Pajak number)
        - fp_date (Invoice date)
        - npwp (Seller NPWP)
        - harga_jual (TOTAL from signature section)
        - dpp (TOTAL Dasar Pengenaan Pajak)
        - ppn (TOTAL Pajak Pertambahan Nilai)
        - ppnbm (TOTAL PPnBM if applicable)
    
    Used By:
        - _run_ocr_job() → Sets header fields on:
          * Purchase Invoice
          * Expense Request
          * Branch Expense Request
          * Sales Invoice
          * Tax Invoice OCR Upload
    
    Parsing Strategy:
        1. Regex-based extraction from plain OCR text
        2. Label-based amount extraction (prioritized)
        3. Signature section fallback (6-amount format)
        4. Validation: Harga Jual >= DPP
    
    Why Legacy?
        - Proven stable in production for header extraction
        - Regex works well for unstructured header text
        - Different use case than token-based line item parsing
    
    ⚠️ DO NOT USE FOR LINE ITEMS
        For line item extraction, use:
        from imogi_finance.imogi_finance.parsers.faktur_pajak_parser import parse_invoice
    
    Args:
        text: Raw OCR text from Google Vision or other OCR provider
    
    Returns:
        Tuple of (matches_dict, confidence_score)
        - matches_dict: Extracted field values
        - confidence_score: Float 0.0-1.0 based on extraction success
    
    Example:
        >>> ocr_text = frappe.get_value("Tax Invoice OCR Upload", upload_name, "ocr_text")
        >>> matches, conf = parse_faktur_pajak_text(ocr_text)
        >>> print(matches["fp_no"])  # "010.000-24.12345678"
        >>> print(matches["harga_jual"])  # 10000000.00 (TOTAL)
    """
    matches: dict[str, Any] = {}
    confidence = 0.0

    seller_section = _extract_section_lines(
        text or "", "Pengusaha Kena Pajak", ("Pembeli Barang Kena Pajak", "Pembeli Barang Kena Pajak/Penerima Jasa Kena Pajak")
    )
    buyer_section = _extract_section_lines(
        text or "", "Pembeli Barang Kena Pajak", ("No.", "Kode Barang", "Nama Barang", "Harga Jual")
    )

    faktur_match = FAKTUR_NO_LABEL_REGEX.search(text or "")
    if faktur_match:
        normalized_fp = _normalize_faktur_number(faktur_match.group("fp"))
        if normalized_fp:
            matches["fp_no"] = normalized_fp
            confidence += 0.3
    else:
        fp_match = TAX_INVOICE_REGEX.search(text or "")
        if fp_match:
            normalized_fp = _normalize_faktur_number(fp_match.group("fp"))
            if normalized_fp:
                matches["fp_no"] = normalized_fp
                confidence += 0.25

    pkp_section = _extract_section(text or "", "Pengusaha Kena Pajak", "Pembeli")
    seller_npwp = _extract_npwp_with_label(pkp_section) or _extract_npwp_from_text(pkp_section)
    if seller_npwp:
        matches["npwp"] = seller_npwp
        confidence += 0.25
    else:
        seller_npwp = _extract_npwp_with_label(text) or _extract_npwp_from_text(text)
        if seller_npwp:
            matches["npwp"] = seller_npwp
            confidence += 0.2

    parsed_date = _parse_date_from_text(text or "")
    if parsed_date:
        matches["fp_date"] = parsed_date
        confidence += 0.15

    seller_name = _extract_first_after_label(seller_section, "Nama")
    seller_address = _extract_address(seller_section, "Alamat")
    buyer_name = _extract_first_after_label(buyer_section, "Nama")
    buyer_address = _extract_address(buyer_section, "Alamat")
    buyer_section_text = "\n".join(buyer_section)
    buyer_npwp = _extract_npwp_with_label(buyer_section_text) or _extract_npwp_from_text(buyer_section_text)

    amounts = [_sanitize_amount(_parse_idr_amount(m.group("amount"))) for m in AMOUNT_REGEX.finditer(text or "")]
    amounts = [amt for amt in amounts if amt is not None]

    logger = frappe.logger("tax_invoice_ocr")
    logger.info(f"🔍 parse_faktur_pajak_text: Found {len(amounts)} amounts in text")
    if amounts:
        logger.info(f"🔍 parse_faktur_pajak_text: All amounts: {amounts}")
        # Show first 10 and last 10 for debugging
        if len(amounts) > 20:
            logger.info(f"🔍 parse_faktur_pajak_text: First 10: {amounts[:10]}")
            logger.info(f"🔍 parse_faktur_pajak_text: Last 10: {amounts[-10:]}")
    else:
        logger.warning("🔍 parse_faktur_pajak_text: ⚠️ NO AMOUNTS FOUND IN TEXT!")

    # 🔧 FIX PRIORITY 1: Try label-based extraction FIRST (most reliable)
    logger.info("🔍 parse_faktur_pajak_text: ===== PRIORITY 1: LABEL-BASED EXTRACTION =====")

    # Extract DPP (Dasar Pengenaan Pajak) from label - try multiple variants
    dpp_labeled = None
    for dpp_label in ["Dasar Pengenaan Pajak", "DPP"]:
        dpp_labeled = _find_amount_after_label(text or "", dpp_label, max_lines_to_check=3)
        if dpp_labeled:
            matches["dpp"] = dpp_labeled
            logger.info(f"🔍 parse_faktur_pajak_text: ✅ DPP from label '{dpp_label}': {dpp_labeled}")
            confidence += 0.3
            break

    # Extract PPN (Pajak Pertambahan Nilai) from label - try multiple variants
    # 🔧 CRITICAL FIX: Validate PPN is not same as DPP
    ppn_labeled = None
    dpp_for_validation = matches.get("dpp")
    for ppn_label in ["Jumlah PPN", "PPN", "Pajak Pertambahan Nilai"]:
        ppn_candidate = _find_amount_after_label(text or "", ppn_label, max_lines_to_check=3)
        if ppn_candidate:
            # 🔧 BUG FIX: Validate PPN is NOT the same as DPP (this was causing PPN=DPP bug!)
            if dpp_for_validation and ppn_candidate == dpp_for_validation:
                logger.warning(f"🔍 parse_faktur_pajak_text: ⚠️ Rejecting PPN {ppn_candidate} from '{ppn_label}' - same as DPP!")
                continue  # Try next label
            
            # Also validate PPN is roughly 8-13% of DPP (reasonable tax range)
            if dpp_for_validation and ppn_candidate > dpp_for_validation * 0.15:
                logger.warning(f"🔍 parse_faktur_pajak_text: ⚠️ Rejecting PPN {ppn_candidate} from '{ppn_label}' - too high (>15% of DPP)")
                continue  # Try next label
            
            ppn_labeled = ppn_candidate
            matches["ppn"] = ppn_labeled
            logger.info(f"🔍 parse_faktur_pajak_text: ✅ PPN from label '{ppn_label}': {ppn_labeled}")
            confidence += 0.3
            break

    # Extract Harga Jual from label - try multiple variants including long format
    # 🔧 PRIORITY FIX: Try the most specific pattern FIRST
    harga_jual_labeled = None
    hj_labels_priority = [
        "Harga Jual / Penggantian / Uang Muka / Termin",  # Most specific, with spaces
        "Harga Jual/Penggantian/Uang Muka/Termin",         # Without spaces
        "Harga Jual / Penggantian / Uang Muka",            # Partial match
        "Harga Jual/Penggantian",
        "Harga Jual / Penggantian",
        "Harga Jual",  # Last resort, most generic
    ]

    for hj_label in hj_labels_priority:
        harga_jual_labeled = _find_amount_after_label(text or "", hj_label, max_lines_to_check=2)
        if harga_jual_labeled:
            # Validate: Harga Jual must be >= DPP (if DPP already extracted)
            dpp_check = matches.get("dpp")
            if not dpp_check or harga_jual_labeled >= dpp_check:
                matches["harga_jual"] = harga_jual_labeled
                logger.info(f"🔍 parse_faktur_pajak_text: ✅ Harga Jual from label '{hj_label}': {harga_jual_labeled}")
                confidence += 0.4  # Higher confidence for label-based extraction
                break
            else:
                logger.info(f"🔍 parse_faktur_pajak_text: ⚠️ Rejected Harga Jual {harga_jual_labeled} < DPP {dpp_check} from label '{hj_label}'")
    signature_amounts = _extract_amounts_after_signature(text or "")
    logger.info(f"🔍 parse_faktur_pajak_text: Signature amounts: {signature_amounts}")

    if signature_amounts and len(signature_amounts) >= 4:
        logger.info(f"🔍 parse_faktur_pajak_text: ✅ USING SIGNATURE AMOUNTS (length={len(signature_amounts)})")

        # Standard format validation:
        # [0] = Harga Jual
        # [1] = Harga Jual duplicate (or sometimes potongan)
        # [2] = Potongan (usually 0) OR DPP if no potongan
        # [3] = DPP
        # [4] = PPN
        # [5] = PPnBM (optional)

        if len(signature_amounts) >= 6:
            # Full 6-amount format
            # [0] = Harga Jual, [1] = Harga Jual dup, [2] = Potongan, [3] = DPP, [4] = PPN, [5] = PPnBM
            dpp = signature_amounts[3]
            ppn = signature_amounts[4]

            # Only set DPP and PPN if not already set by label extraction
            if "dpp" not in matches:
                matches["dpp"] = dpp
                logger.info(f"🔍 parse_faktur_pajak_text: ✅ Set DPP={dpp} from signature")
                confidence += 0.25
            else:
                logger.info(f"🔍 parse_faktur_pajak_text: ℹ️ DPP already set by label, skipping signature value")

            if "ppn" not in matches:
                matches["ppn"] = ppn
                logger.info(f"🔍 parse_faktur_pajak_text: ✅ Set PPN={ppn} from signature")
                confidence += 0.25
            else:
                logger.info(f"🔍 parse_faktur_pajak_text: ℹ️ PPN already set by label, skipping signature value")

            # Now determine Harga Jual with validation (only if not already set by label)
            if "harga_jual" not in matches:
                harga_jual_0 = signature_amounts[0]
                harga_jual_1 = signature_amounts[1]
                current_dpp = matches.get("dpp", dpp)

                # 🔧 Validation: Harga Jual should be >= DPP
                if harga_jual_0 >= current_dpp:
                    matches["harga_jual"] = harga_jual_0
                    logger.info(f"🔍 parse_faktur_pajak_text: ✅ Harga Jual from [0]: {harga_jual_0}")
                    confidence += 0.35
                elif harga_jual_1 >= current_dpp:
                    # Try index [1] as alternative
                    matches["harga_jual"] = harga_jual_1
                    logger.info(f"🔍 parse_faktur_pajak_text: ✅ Harga Jual from [1]: {harga_jual_1}")
                    confidence += 0.35
                else:
                    # Both failed validation - will use fallback later
                    logger.info(f"🔍 parse_faktur_pajak_text: ⚠️ Both [0]={harga_jual_0} and [1]={harga_jual_1} < DPP={current_dpp}")
                    logger.info(f"🔍 parse_faktur_pajak_text: Will try fallback for Harga Jual")
            else:
                logger.info(f"🔍 parse_faktur_pajak_text: ℹ️ Harga Jual ALREADY SET by label ({matches['harga_jual']}), SKIPPING signature value")

        elif len(signature_amounts) == 5:
            # 5-amount format (no duplicate or no ppnbm)
            # Could be: [Harga Jual, Harga Jual dup, DPP, PPN, PPnBM] OR [Harga Jual, Potongan, DPP, PPN, PPnBM]
            dpp = signature_amounts[2]
            ppn = signature_amounts[3]

            # Only set if not already set by label extraction
            if "dpp" not in matches:
                matches["dpp"] = dpp
                logger.info(f"🔍 parse_faktur_pajak_text: ✅ Set DPP={dpp} from signature (5-amt)")
                confidence += 0.2

            if "ppn" not in matches:
                matches["ppn"] = ppn
                logger.info(f"🔍 parse_faktur_pajak_text: ✅ Set PPN={ppn} from signature (5-amt)")
                confidence += 0.2

            if "harga_jual" not in matches:
                harga_jual = signature_amounts[0]
                current_dpp = matches.get("dpp", dpp)
                if harga_jual >= current_dpp:
                    matches["harga_jual"] = harga_jual
                    logger.info(f"🔍 parse_faktur_pajak_text: ✅ Harga Jual: {harga_jual}")
                    confidence += 0.3
                else:
                    logger.info(f"🔍 parse_faktur_pajak_text: ⚠️ Harga Jual {harga_jual} < DPP {current_dpp}, will try fallback")

        elif len(signature_amounts) == 4:
            # Minimal 4-amount format: [Harga Jual, Harga Jual dup, DPP, PPN]
            dpp = signature_amounts[2]
            ppn = signature_amounts[3]

            # Only set if not already set by label extraction
            if "dpp" not in matches:
                matches["dpp"] = dpp
                logger.info(f"🔍 parse_faktur_pajak_text: ✅ Set DPP={dpp} from signature (4-amt)")
                confidence += 0.2

            if "ppn" not in matches:
                matches["ppn"] = ppn
                logger.info(f"🔍 parse_faktur_pajak_text: ✅ Set PPN={ppn} from signature (4-amt)")
                confidence += 0.2

            if "harga_jual" not in matches:
                harga_jual = signature_amounts[0]
                current_dpp = matches.get("dpp", dpp)
                if harga_jual >= current_dpp:
                    matches["harga_jual"] = harga_jual
                    logger.info(f"🔍 parse_faktur_pajak_text: ✅ Harga Jual: {harga_jual}")
                    confidence += 0.25
                else:
                    logger.info(f"🔍 parse_faktur_pajak_text: ⚠️ Harga Jual {harga_jual} < DPP {current_dpp}, will try fallback")

    else:
        logger.info(f"🔍 parse_faktur_pajak_text: ⚠️ Signature extraction insufficient (got {len(signature_amounts) if signature_amounts else 0} amounts)")

        # 🔧 NEW: Try to get DPP and PPN from labels if signature failed completely
        if "dpp" not in matches:
            dpp_from_label = _find_amount_after_label(text or "", "Dasar Pengenaan Pajak")
            if dpp_from_label is None:
                dpp_from_label = _find_amount_after_label(text or "", "DPP")
            if dpp_from_label:
                matches["dpp"] = dpp_from_label
                logger.info(f"🔍 parse_faktur_pajak_text: ✓ Found DPP from label: {dpp_from_label}")

        if "ppn" not in matches:
            ppn_from_label = _find_amount_after_label(text or "", "Jumlah PPN")
            if ppn_from_label is None:
                ppn_from_label = _find_amount_after_label(text or "", "PPN")
            if ppn_from_label:
                matches["ppn"] = ppn_from_label
                logger.info(f"🔍 parse_faktur_pajak_text: ✓ Found PPN from label: {ppn_from_label}")

    # 🔧 FIX 5: Enhanced fallback with better Harga Jual detection
    if "harga_jual" not in matches:
        logger.info("🔍 parse_faktur_pajak_text: ===== FALLBACK: Trying individual Harga Jual extraction =====")

        # Strategy 0: Look for pattern "Nilai Harga Jual dari Faktur Pajak" (from UI field description)
        logger.info("🔍 parse_faktur_pajak_text: Strategy 0: Looking for 'Nilai Harga Jual dari Faktur Pajak'")
        nilai_hj_from_desc = _find_amount_after_label(text or "", "Nilai Harga Jual dari Faktur Pajak", max_lines_to_check=2)
        if nilai_hj_from_desc and nilai_hj_from_desc >= 10000:
            dpp_check = matches.get("dpp")
            if not dpp_check or nilai_hj_from_desc >= dpp_check:
                matches["harga_jual"] = nilai_hj_from_desc
                logger.info(f"🔍 parse_faktur_pajak_text: ✅ Strategy 0: Harga Jual from description: {nilai_hj_from_desc}")
                confidence += 0.3
            else:
                logger.info(f"🔍 parse_faktur_pajak_text: ⚠️ Strategy 0: Rejected {nilai_hj_from_desc} < DPP {dpp_check}")

        # Strategy 1: Calculate from DPP + PPN (most reliable if both are correct)
        if "harga_jual" not in matches:
            dpp_value = matches.get("dpp")
            ppn_value = matches.get("ppn")

            if dpp_value and ppn_value:
                logger.info(f"🔍 parse_faktur_pajak_text: Strategy 1: Looking for Harga Jual > DPP ({dpp_value})")

                # Show diagnostic info
                amounts_gt_dpp = [amt for amt in amounts if amt > dpp_value]
                amounts_eq_dpp = [amt for amt in amounts if amt == dpp_value]

                logger.info(f"🔍 parse_faktur_pajak_text: Total amounts in text: {len(amounts)}")
                logger.info(f"🔍 parse_faktur_pajak_text: Amounts > DPP ({dpp_value}): {amounts_gt_dpp}")
                logger.info(f"🔍 parse_faktur_pajak_text: Amounts = DPP: {len(amounts_eq_dpp)} occurrences")

                # Look for amount that matches DPP + something (likely original Harga Jual)
                found = False

                if amounts_gt_dpp:
                    # 🔧 CRITICAL FIX: Don't just take any amount > DPP
                    # Look for amounts that are close to DPP + PPN (within reasonable range)
                    expected_hj = dpp_value + ppn_value

                    # Find amounts within 20% tolerance of expected Harga Jual
                    tolerance = expected_hj * 0.2
                    candidates = [amt for amt in amounts_gt_dpp if abs(amt - expected_hj) <= tolerance]

                    if candidates:
                        # Use the one closest to expected value
                        best_candidate = min(candidates, key=lambda x: abs(x - expected_hj))
                        matches["harga_jual"] = best_candidate
                        logger.info(f"🔍 parse_faktur_pajak_text: ✅ Strategy 1: Harga Jual (closest to DPP+PPN={expected_hj}): {best_candidate}")
                        confidence += 0.25
                        found = True
                    else:
                        # Fallback: Use the smallest amount > DPP (most conservative)
                        best_candidate = min(amounts_gt_dpp)
                        matches["harga_jual"] = best_candidate
                        logger.info(f"🔍 parse_faktur_pajak_text: ⚠️ Strategy 1: Using smallest amount > DPP: {best_candidate}")
                        confidence += 0.15
                        found = True

                if not found:
                    logger.info(f"🔍 parse_faktur_pajak_text: ⚠️ Strategy 1 failed - no amount > DPP found")
                    logger.warning(f"🔍 parse_faktur_pajak_text: ❌ Strategy 1 completely failed - NO amount > DPP!")

        # Strategy 2: Try focused extraction from signature section
        if "harga_jual" not in matches:
            labeled_harga_jual = _extract_harga_jual_from_signature_section(text or "")
            logger.info(f"🔍 parse_faktur_pajak_text: Strategy 2 (signature with labels): {labeled_harga_jual}")
            logger.info(f"🔍 parse_faktur_pajak_text: ✓ Set Harga Jual from signature: {labeled_harga_jual}")
            confidence += 0.2
        else:
                logger.info(f"🔍 parse_faktur_pajak_text: ⚠️ Rejected: {labeled_harga_jual} < DPP {dpp_check}")

        # Strategy 3: Direct label extraction with multiple variants
        if "harga_jual" not in matches:
            logger.info("🔍 parse_faktur_pajak_text: Strategy 3: Direct label extraction")
            harga_from_label = _find_amount_after_label(text or "", "Harga Jual")
            if harga_from_label is None:
                harga_from_label = _find_amount_after_label(text or "", "Harga Jual/Penggantian")
            if harga_from_label is None:
                harga_from_label = _find_amount_after_label(text or "", "Penggantian")

            logger.info(f"🔍 parse_faktur_pajak_text: Strategy 3 (label): {harga_from_label}")

            if harga_from_label is not None and harga_from_label >= 10000:
                # 🔧 CRITICAL: Validate against DPP if available
                dpp_value = matches.get("dpp")
                if dpp_value and harga_from_label >= dpp_value:
                    matches["harga_jual"] = harga_from_label
                    logger.info(f"🔍 parse_faktur_pajak_text: ✓ Set Harga Jual from label: {harga_from_label}")
                    confidence += 0.15
                elif not dpp_value:
                    # No DPP to validate against, accept it anyway
                    matches["harga_jual"] = harga_from_label
                    logger.info(f"🔍 parse_faktur_pajak_text: ✓ Set Harga Jual from label (no DPP check): {harga_from_label}")
                    confidence += 0.1
                else:
                    logger.info(f"🔍 parse_faktur_pajak_text: ✗ Harga Jual {harga_from_label} < DPP {dpp_value}, rejected")

    # Extract DPP and PPN if not already set
    if "dpp" not in matches or "ppn" not in matches:
        logger.info("🔍 parse_faktur_pajak_text: ===== FALLBACK: Extracting DPP/PPN =====")

        if len(amounts) >= 6:
            tail_amounts = amounts[-6:]
            logger.info(f"🔍 parse_faktur_pajak_text: Using tail amounts: {tail_amounts}")

            if "dpp" not in matches:
                matches["dpp"] = tail_amounts[3]
                logger.info(f"🔍 parse_faktur_pajak_text: Set DPP: {tail_amounts[3]}")
            if "ppn" not in matches:
                matches["ppn"] = tail_amounts[4]
                logger.info(f"🔍 parse_faktur_pajak_text: Set PPN: {tail_amounts[4]}")
            confidence += 0.2

        elif len(amounts) >= 2:
            # 🔧 CRITICAL FIX: Don't blindly assign largest amounts
            # This was causing DPP to be assigned to both DPP and PPN
            sorted_amounts = sorted(amounts, reverse=True)

            # Find distinct amounts (avoid duplicates)
            distinct_amounts = []
            for amt in sorted_amounts:
                if not distinct_amounts or amt != distinct_amounts[-1]:
                    distinct_amounts.append(amt)

            logger.info(f"🔍 parse_faktur_pajak_text: Distinct amounts for fallback: {distinct_amounts[:5]}")

            if "dpp" not in matches and len(distinct_amounts) >= 1:
                # DPP is typically one of the larger amounts (but not always the largest)
                # Could be at index 0 or 1
                matches["dpp"] = distinct_amounts[0]
                logger.info(f"🔍 parse_faktur_pajak_text: Fallback DPP: {distinct_amounts[0]}")

            if "ppn" not in matches and len(distinct_amounts) >= 2:
                # PPN is typically smaller than DPP (around 11-12% of DPP)
                # Look for an amount that's roughly 10-13% of DPP
                dpp_val = matches.get("dpp", distinct_amounts[0])
                fp_date = matches.get("fp_date")

                # 🔥 FIX: Use dynamic tax rate based on document date
                effective_rate = infer_tax_rate(dpp=dpp_val, ppn=None, fp_date=fp_date)
                expected_ppn = dpp_val * effective_rate
                best_ppn_candidate = None
                best_ppn_diff = float('inf')

                for amt in distinct_amounts[1:]:  # Skip first (likely DPP)
                    if amt < dpp_val:  # PPN must be less than DPP
                        diff = abs(amt - expected_ppn)
                        if diff < best_ppn_diff:
                            best_ppn_diff = diff
                            best_ppn_candidate = amt

                if best_ppn_candidate:
                    matches["ppn"] = best_ppn_candidate
                    logger.info(f"🔍 parse_faktur_pajak_text: Fallback PPN (matched ~{effective_rate*100:.0f}% rule): {best_ppn_candidate}")
                elif len(distinct_amounts) >= 2:
                    # Fallback to second distinct amount
                    matches["ppn"] = distinct_amounts[1]
                    logger.info(f"🔍 parse_faktur_pajak_text: Fallback PPN (second distinct): {distinct_amounts[1]}")

            confidence += 0.15

    # 🔧 CRITICAL FIX: Final validation and correction for Harga Jual
    logger.info("=" * 80)
    logger.info("🔍 parse_faktur_pajak_text: FINAL VALIDATION")
    logger.info("=" * 80)

    dpp_value = matches.get("dpp")
    ppn_value = matches.get("ppn")
    harga_jual_value = matches.get("harga_jual")

    logger.info(f"🔍 Current values: Harga Jual={harga_jual_value}, DPP={dpp_value}, PPN={ppn_value}")

    if harga_jual_value and dpp_value and harga_jual_value < dpp_value:
        logger.info(f"🔍 ⚠️ VALIDATION ERROR: Harga Jual ({harga_jual_value}) < DPP ({dpp_value})")
        logger.info(f"🔍 Searching for correct Harga Jual from all extracted amounts...")

        # Strategy 1: Find amounts > DPP in the tail section (most recent amounts in document)
        # These are likely from signature section
        if len(amounts) >= 6:
            tail_amounts = amounts[-6:]
            logger.info(f"🔍 Checking tail amounts: {tail_amounts}")

            # Find amounts > DPP within reasonable range (< DPP * 1.5)
            candidates_tail = [amt for amt in tail_amounts if amt > dpp_value and amt < dpp_value * 1.5]

            if candidates_tail:
                # Use the first one found (likely Harga Jual position)
                matches["harga_jual"] = candidates_tail[0]
                logger.info(f"🔍 ✅ Corrected Harga Jual from tail: {matches['harga_jual']}")
            else:
                logger.info(f"🔍 No valid candidates in tail amounts")

                # Strategy 2: Search all amounts
                candidates_all = [amt for amt in reversed(amounts) if amt > dpp_value and amt < dpp_value * 1.5]

                if candidates_all:
                    matches["harga_jual"] = candidates_all[0]
                    logger.info(f"🔍 ✅ Corrected Harga Jual from all amounts: {matches['harga_jual']}")
                else:
                    logger.info(f"🔍 ❌ Could not find valid Harga Jual > DPP")
        else:
            # Search all amounts if not enough for tail
            candidates_all = [amt for amt in reversed(amounts) if amt > dpp_value and amt < dpp_value * 1.5]

            if candidates_all:
                matches["harga_jual"] = candidates_all[0]
                logger.info(f"🔍 ✅ Corrected Harga Jual: {matches['harga_jual']}")
    elif harga_jual_value and dpp_value:
        logger.info(f"🔍 ✅ Validation passed: Harga Jual ({harga_jual_value}) >= DPP ({dpp_value})")
    else:
        logger.info(f"🔍 ⚠️ Missing values - Harga Jual: {harga_jual_value}, DPP: {dpp_value}")

    logger.info(f"🔍 parse_faktur_pajak_text: ===== FINAL RESULTS =====")
    logger.info(f"🔍 parse_faktur_pajak_text: Harga Jual: {matches.get('harga_jual')}")
    logger.info(f"🔍 parse_faktur_pajak_text: DPP: {matches.get('dpp')}")
    logger.info(f"🔍 parse_faktur_pajak_text: PPN: {matches.get('ppn')}")
    logger.info(f"🔍 parse_faktur_pajak_text: Confidence: {confidence}")

    # 🔧 LAST RESORT: If Harga Jual still not found, try to find ANY amount > DPP
    if not matches.get("harga_jual") and matches.get("dpp"):
        logger.warning("⚠️ LAST RESORT: Harga Jual not found, searching for any amount > DPP...")
        dpp_val = matches.get("dpp")

        # Find all amounts greater than DPP
        candidates = [amt for amt in amounts if amt > dpp_val]

        if candidates:
            # Use the one closest to DPP (most likely to be correct)
            # Sort by distance from DPP
            candidates_sorted = sorted(candidates, key=lambda x: x - dpp_val)
            best = candidates_sorted[0]
            matches["harga_jual"] = best
            logger.info(f"🔍 ✅ LAST RESORT: Set Harga Jual to {best} (closest amount > DPP)")
            confidence += 0.1
        else:
            # ABSOLUTE LAST RESORT: Calculate Harga Jual = DPP / 0.92 (assuming 8% discount)
            # This is a reasonable assumption for Indonesian tax invoices
            estimated_hj = round(dpp_val / 0.92, 2)
            matches["harga_jual"] = estimated_hj
            logger.warning(f"🔍 ⚠️ ABSOLUTE LAST RESORT: Estimated Harga Jual = {estimated_hj} (DPP / 0.92)")
            confidence = min(confidence, 0.4)  # Very low confidence

    # 🔧 CRITICAL: Validation for duplicate values (bug detection)
    harga_jual_final = matches.get("harga_jual")
    dpp_final = matches.get("dpp")
    ppn_final = matches.get("ppn")

    # Check for suspicious duplications
    duplicate_detected = False

    if harga_jual_final and dpp_final and harga_jual_final == dpp_final:
        logger.warning(f"⚠️ WARNING: Harga Jual ({harga_jual_final}) sama dengan DPP ({dpp_final})")
        duplicate_detected = True

    if ppn_final and dpp_final and ppn_final == dpp_final:
        # 🔧 ENHANCED FIX: More aggressive PPN correction with dynamic rate
        ppn_corrected = False
        if dpp_final:
            fp_date = matches.get("fp_date")
            effective_rate = infer_tax_rate(dpp=dpp_final, ppn=None, fp_date=fp_date)
            expected_ppn = dpp_final * effective_rate
            best_ppn_candidate = None
            best_ppn_diff = float('inf')
            
            # Search for amount close to expected PPN (8-13% of DPP range)
            for amt in amounts:
                if amt != dpp_final and 0.08 * dpp_final <= amt <= 0.13 * dpp_final:
                    diff = abs(amt - expected_ppn)
                    if diff < best_ppn_diff:
                        best_ppn_diff = diff
                        best_ppn_candidate = amt
            
            if best_ppn_candidate:
                matches["ppn"] = best_ppn_candidate
                ppn_final = best_ppn_candidate
                logger.info(f"🔍 ✅ CORRECTED PPN from {dpp_final} to: {best_ppn_candidate} (found amount matching ~{effective_rate*100:.0f}% of DPP)")
                ppn_corrected = True
            else:
                # Last resort: Calculate PPN using effective rate
                calculated_ppn = round(dpp_final * effective_rate, 2)
                # Verify calculated PPN exists in amounts (within 1000 IDR tolerance)
                for amt in amounts:
                    if amt != dpp_final and abs(amt - calculated_ppn) <= 1000:
                        matches["ppn"] = amt
                        ppn_final = amt
                        logger.info(f"🔍 ✅ CORRECTED PPN from {dpp_final} to: {amt} (close to calculated {effective_rate*100:.0f}%: {calculated_ppn})")
                        ppn_corrected = True
                        break
                else:
                    # If no matching amount found, use calculated value
                    matches["ppn"] = calculated_ppn
                    ppn_final = calculated_ppn
                    logger.info(f"🔍 ✅ ESTIMATED PPN: {calculated_ppn} ({effective_rate*100:.0f}% of DPP, no exact match found)")
                    ppn_corrected = True
                    confidence = min(confidence, 0.5)  # Lower confidence for estimated value
        
        # Only log error and set duplicate flag if correction failed
        if not ppn_corrected:
            logger.error(f"❌ CRITICAL ERROR: PPN ({ppn_final}) sama dengan DPP ({dpp_final}) - CORRECTION FAILED!")
            duplicate_detected = True

    if harga_jual_final and ppn_final and harga_jual_final == ppn_final:
        logger.error(f"❌ CRITICAL ERROR: Harga Jual ({harga_jual_final}) sama dengan PPN ({ppn_final}) - INI BUG!")
        duplicate_detected = True
    # Validate Harga Jual vs DPP relationship - BEFORE checking duplicate_detected
    # This allows recovery to happen first
    if harga_jual_final and dpp_final and harga_jual_final < dpp_final:
        logger.warning(f"⚠️ WARNING: Harga Jual ({harga_jual_final}) LEBIH KECIL dari DPP ({dpp_final}) - attempting recovery...")
        
        # 🔥 RECOVERY: Try to find correct Harga Jual from amounts
        # Harga Jual should be >= DPP (typically DPP + PPN or with small discount)
        hj_recovered = False
        candidates = [amt for amt in amounts if amt >= dpp_final]
        if candidates:
            # Use the smallest value >= DPP (most likely correct Harga Jual)
            candidates.sort()
            recovered_hj = candidates[0]
            matches["harga_jual"] = recovered_hj
            harga_jual_final = recovered_hj
            logger.info(f"🔍 ✅ RECOVERED Harga Jual: {recovered_hj} (smallest amount >= DPP)")
            hj_recovered = True
            confidence = min(confidence, 0.6)  # Still lower confidence
        else:
            # 🔥 LAST RESORT: Calculate Harga Jual = DPP + PPN
            ppn_val = matches.get("ppn", 0)
            if ppn_val and ppn_val > 0 and ppn_val != dpp_final:
                calculated_hj = dpp_final + ppn_val
                matches["harga_jual"] = calculated_hj
                harga_jual_final = calculated_hj
                logger.info(f"🔍 ✅ CALCULATED Harga Jual: {calculated_hj} (DPP + PPN)")
                hj_recovered = True
                confidence = min(confidence, 0.5)
        
        if not hj_recovered:
            # Give up - set confidence very low for manual review
            logger.error(f"❌ Cannot recover Harga Jual - manual review required")
            confidence = min(confidence, 0.3)

    # Only log duplicate error if still have issues after all recovery attempts
    if duplicate_detected:
        logger.warning("⚠️ DUPLICATE VALUES DETECTED - some extraction issues occurred but may have been corrected")
        confidence = min(confidence, 0.4)  # Mark as lower confidence

    ppn_rate = None
    ppn_rate_match = PPN_RATE_REGEX.search(text or "")
    if ppn_rate_match:
        raw_rate = ppn_rate_match.group("rate").replace(",", ".")
        try:
            ppn_rate = flt(raw_rate)
        except Exception:
            ppn_rate = None

    if ppn_rate is None:
        ppn_type = DEFAULT_SETTINGS.get("default_ppn_type", "Standard")
    else:
        ppn_type = "Standard" if ppn_rate > 0 else "Zero Rated"

    matches["ppn_type"] = ppn_type

    # � FIX: Set tax_rate from infer_tax_rate() for validation
    # This ensures doctype validation uses the correct rate (11% or 12%)
    dpp_final_for_rate = matches.get("dpp")
    ppn_final_for_rate = matches.get("ppn")
    fp_date_for_rate = matches.get("fp_date")
    inferred_rate = infer_tax_rate(dpp=dpp_final_for_rate, ppn=ppn_final_for_rate, fp_date=fp_date_for_rate)
    matches["tax_rate"] = inferred_rate
    logger.info(f"🔍 parse_faktur_pajak_text: Inferred tax_rate = {inferred_rate} (based on DPP={dpp_final_for_rate}, PPN={ppn_final_for_rate}, date={fp_date_for_rate})")

    # �🔧 VALIDATION: Check for suspicious Harga Jual = DPP (possible bug)
    harga_jual_final = matches.get("harga_jual")
    dpp_final = matches.get("dpp")

    if harga_jual_final and dpp_final and abs(harga_jual_final - dpp_final) < 1:
        logger.warning(f"⚠️ SUSPICIOUS: Harga Jual ({harga_jual_final}) equals DPP ({dpp_final})")
        logger.warning(f"⚠️ This may indicate extraction error. Please verify manually.")
        # Set confidence lower to flag for manual review
        confidence = min(confidence, 0.70)

    summary = {
        "faktur_pajak": {
            "nomor_seri": matches.get("fp_no"),
            "pengusaha_kena_pajak": {
                "nama": seller_name,
                "npwp": matches.get("npwp"),
                "alamat": seller_address,
            },
            "pembeli": {
                "nama": buyer_name,
                "npwp": buyer_npwp,
                "alamat": buyer_address,
            },
        },
        "ringkasan_pajak": {
            "harga_jual": matches.get("harga_jual"),
            "dasar_pengenaan_pajak": matches.get("dpp"),
            "jumlah_ppn": matches.get("ppn"),
        },
    }

    matches["notes"] = json.dumps(summary, ensure_ascii=False, indent=2)

    filtered_matches = {key: value for key, value in matches.items() if key in ALLOWED_OCR_FIELDS}
    return filtered_matches, round(min(confidence, 0.95), 2)


# ============================================================================
# REST OF THE CODE REMAINS THE SAME (Google Vision, Tesseract, etc.)
# ============================================================================


# =============================================================================
# 🔥 FRAPPE CLOUD SAFE FILE HANDLING
# =============================================================================

def _get_file_doc_by_url(file_url: str):
    """
    Get File doctype by file_url.
    
    🔥 FRAPPE CLOUD SAFE: Works with local and remote storage.
    
    Args:
        file_url: File URL like /private/files/xxx.pdf or /files/xxx.pdf
    
    Returns:
        File document
    
    Raises:
        ValidationError: If file not found
    """
    if not file_url:
        raise ValidationError(_("File URL is empty"))
    
    # Strategy 1: Direct file_url match
    name = frappe.db.get_value("File", {"file_url": file_url}, "name")
    
    # Strategy 2: Try with/without leading slash
    if not name:
        alt_url = file_url.lstrip("/") if file_url.startswith("/") else f"/{file_url}"
        name = frappe.db.get_value("File", {"file_url": alt_url}, "name")
    
    # Strategy 3: Fallback by basename (file_name)
    if not name:
        basename = (file_url or "").split("/")[-1]
        if basename:
            name = frappe.db.get_value("File", {"file_name": basename}, "name")
    
    # Strategy 4: Try LIKE match for partial URL
    if not name and file_url:
        normalized = file_url.strip("/")
        name = frappe.db.get_value("File", {"file_url": ["like", f"%{normalized}"]}, "name")
    
    if not name:
        raise ValidationError(
            _("File not found in DocType File for URL: {0}. "
              "File may have been deleted or is not properly attached.").format(file_url)
        )
    
    return frappe.get_doc("File", name)


def _validate_pdf_size(file_url: str, max_mb: int) -> None:
    """
    Validate PDF file size.
    
    🔥 FRAPPE CLOUD SAFE: Uses File.file_size or File.get_content() length.
    Does NOT rely on local filesystem.
    
    Args:
        file_url: File URL
        max_mb: Maximum allowed size in MB
    
    Raises:
        ValidationError: If file missing or exceeds size limit
    """
    if not file_url:
        frappe.throw(_("Please attach a Tax Invoice PDF before running OCR."))
    
    try:
        file_doc = _get_file_doc_by_url(file_url)
    except ValidationError:
        # File not found in DB - let the actual read fail with clear error
        frappe.throw(_("PDF file not found. Please re-attach the file."))
        return
    
    # Try file_size field first (faster)
    size_bytes = getattr(file_doc, "file_size", None)
    
    if not size_bytes:
        # Fallback: get actual content length
        try:
            content = file_doc.get_content() or b""
            size_bytes = len(content)
        except Exception as e:
            frappe.logger().warning(f"[OCR] Could not get file size for {file_url}: {e}")
            size_bytes = 0
    
    if size_bytes == 0:
        frappe.throw(_("PDF file is empty (0 bytes). Please re-upload a valid PDF."))
    
    size_mb = size_bytes / (1024 * 1024)
    frappe.logger().info(f"[OCR] File size: {size_mb:.2f} MB")
    
    if size_mb > max_mb:
        frappe.throw(_("File exceeds maximum size of {0} MB (current: {1:.1f} MB).").format(max_mb, size_mb))


def _validate_provider_settings(provider: str, settings: dict[str, Any]) -> None:
    if provider == "Manual Only":
        raise ValidationError(_("OCR provider not configured. Please select an OCR provider."))

    if provider == "Google Vision":
        service_account_file = settings.get("google_vision_service_account_file")
        if not service_account_file:
            try:
                import google.auth  # type: ignore
            except Exception:
                raise ValidationError(
                    _(
                        "Google Vision credentials are not configured. "
                        "Upload a Service Account JSON file or configure Application Default Credentials (service account). "
                        "API Key is not supported for the selected OCR flow. "
                        "See Google Cloud authentication guidance (e.g. gcloud auth application-default login or GOOGLE_APPLICATION_CREDENTIALS)."
                )
            )
        endpoint = settings.get("google_vision_endpoint") or DEFAULT_SETTINGS["google_vision_endpoint"]
        parsed = urlparse(endpoint or DEFAULT_SETTINGS["google_vision_endpoint"])
        if not parsed.scheme or not parsed.netloc:
            raise ValidationError(_("Google Vision endpoint is invalid. Please update Tax Invoice OCR Settings."))

        allowed_hosts = {"vision.googleapis.com", "eu-vision.googleapis.com", "us-vision.googleapis.com"}
        if parsed.netloc not in allowed_hosts:
            raise ValidationError(_("Google Vision endpoint host is not supported. Please use vision.googleapis.com or a supported regional host."))

        normalized_path = _normalize_google_vision_path(parsed.path)

        if "asyncBatchAnnotate" in (normalized_path or ""):
            raise ValidationError(
                _(
                    "Google Vision asyncBatchAnnotate is not supported with the current OCR flow. "
                    "Use files:annotate (synchronous) or implement a GCS-based async flow with service-account auth."
                )
            )

        if "/locations/" in (normalized_path or ""):
            parts = normalized_path.split("/locations/", 1)
            if len(parts) > 1:
                loc_part = (parts[1] or "").split("/")[0]
                if loc_part and loc_part not in {"us", "eu"}:
                    raise ValidationError(_("Google Vision location must be 'us' or 'eu' when specifying locations in endpoint path."))

        is_regional = parsed.netloc.startswith(("eu-vision.googleapis.com", "us-vision.googleapis.com"))
        if is_regional:
            if not settings.get("google_vision_project_id"):
                raise ValidationError(
                    _("Google Vision project ID is required when using a regional endpoint. Please update Tax Invoice OCR Settings.")
                )
            location = settings.get("google_vision_location")
            if not location:
                raise ValidationError(
                    _("Google Vision location is required when using a regional endpoint. Please update Tax Invoice OCR Settings.")
                )
            if location not in {"us", "eu"}:
                raise ValidationError(_("Google Vision location must be 'us' or 'eu' for regional endpoints."))
        return

    if provider == "Tesseract":
        if not settings.get("tesseract_cmd"):
            raise ValidationError(_("Tesseract command/path is not configured. Please update Tax Invoice OCR Settings."))
        return

    raise ValidationError(_("OCR provider {0} is not supported.").format(provider))


def _get_provider_status(settings: dict[str, Any]) -> tuple[bool, str | None]:
    provider = settings.get("ocr_provider") or "Manual Only"
    try:
        _validate_provider_settings(provider, settings)
        return True, None
    except ValidationError as exc:
        return False, str(exc)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Tax Invoice OCR provider check failed")
        return False, _("OCR provider not configured. Please update Tax Invoice OCR Settings.")


def _resolve_file_path(file_url: str) -> str:
    """
    Resolve file URL to actual local file path.
    Handles both local files and Frappe Cloud S3/remote files.
    
    Args:
        file_url: File URL from File doctype (can be /private/files/xxx or /files/xxx)
    
    Returns:
        Absolute local file path that exists and is readable
    
    Raises:
        ValidationError: If file cannot be found or accessed
    """
    if not file_url:
        raise ValidationError(_("File URL is empty"))
    
    frappe.logger().info(f"[OCR] Resolving file: {file_url}")
    
    # Try 1: Direct local path (most common in on-premise)
    try:
        local_path = get_site_path(file_url.strip("/"))
        if os.path.exists(local_path) and os.path.isfile(local_path):
            frappe.logger().info(f"[OCR] File found at local path: {local_path}")
            return local_path
    except Exception as e:
        frappe.logger().warning(f"[OCR] Could not resolve as local path: {e}")
    
    # Try 2: Get File doc and use file_url or file_path
    try:
        # Find File doc by file_url
        file_filters = [
            ["file_url", "=", file_url],
            ["file_name", "like", f"%{os.path.basename(file_url)}%"]
        ]
        
        for filter_cond in file_filters:
            files = frappe.get_all("File", filters=[filter_cond], fields=["name", "file_url", "file_name"], limit=1)
            if files:
                file_doc = frappe.get_doc("File", files[0].name)
                frappe.logger().info(f"[OCR] Found File doc: {file_doc.name}")
                
                # Try file_name (actual path on disk)
                if file_doc.file_name:
                    file_path = get_site_path(file_doc.file_name.strip("/"))
                    if os.path.exists(file_path) and os.path.isfile(file_path):
                        frappe.logger().info(f"[OCR] File found via File.file_name: {file_path}")
                        return file_path
                
                # Try file_url
                if file_doc.file_url and file_doc.file_url != file_url:
                    file_path = get_site_path(file_doc.file_url.strip("/"))
                    if os.path.exists(file_path) and os.path.isfile(file_path):
                        frappe.logger().info(f"[OCR] File found via File.file_url: {file_path}")
                        return file_path
                
                break
    except Exception as e:
        frappe.logger().warning(f"[OCR] Could not find File doc: {e}")
    
    # Try 3: Check if it's already an absolute path
    if os.path.isabs(file_url) and os.path.exists(file_url) and os.path.isfile(file_url):
        frappe.logger().info(f"[OCR] File is already absolute path: {file_url}")
        return file_url
    
    # All attempts failed
    error_msg = _(
        "Could not find or access PDF file. "
        "URL: {0}. "
        "File may be in remote storage (S3) or deleted. "
        "Please re-upload the file."
    ).format(file_url)
    frappe.logger().error(f"[OCR] {error_msg}")
    raise ValidationError(error_msg)


def _load_pdf_content_base64(file_url: str) -> tuple[str | None, str]:
    """
    Load PDF content as base64 string.
    
    🔥 FRAPPE CLOUD SAFE: Uses File.get_content() instead of local file read.
    Works with local files, S3, and remote storage.
    
    Args:
        file_url: File URL like /private/files/xxx.pdf
    
    Returns:
        Tuple of (None, base64_content) - local_path is None since we use bytes
    
    Raises:
        ValidationError: If file missing, empty, or not a valid PDF
    """
    if not file_url:
        raise ValidationError(_("Tax Invoice PDF is missing. Please attach the file before running OCR."))
    
    frappe.logger().info(f"[OCR] Loading PDF content for: {file_url}")
    
    # Get file via Frappe File API (Cloud-safe)
    file_doc = _get_file_doc_by_url(file_url)
    
    try:
        pdf_bytes = file_doc.get_content()
    except Exception as e:
        raise ValidationError(
            _("Could not read PDF file: {0}. Error: {1}").format(file_url, str(e))
        )
    
    if not pdf_bytes:
        raise ValidationError(_("PDF content is empty for file: {0}").format(file_url))
    
    # Validate PDF header
    header = pdf_bytes[:20].lstrip() if pdf_bytes else b""
    if not header.startswith(b"%PDF"):
        if pdf_bytes[:2] == b"\x1f\x8b":
            raise ValidationError(
                _("Attached file appears to be gzipped, not a PDF: {0}").format(file_url)
            )
        raise ValidationError(
            _("Attached file is not a valid PDF (missing %PDF header): {0}").format(file_url)
        )
    
    content_b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    frappe.logger().info(f"[OCR] PDF loaded successfully: {len(pdf_bytes)} bytes")
    
    # Return None for local_path since we're using bytes-based approach
    return None, content_b64


def _materialize_pdf_to_tempfile(file_url: str) -> str:
    """
    Write PDF bytes to a temporary file for tools that require file paths (e.g., Tesseract).
    
    🔥 FRAPPE CLOUD SAFE: Gets bytes via File.get_content(), writes to temp file.
    
    Args:
        file_url: File URL like /private/files/xxx.pdf
    
    Returns:
        Path to temporary PDF file
    
    Raises:
        ValidationError: If file missing or empty
    
    Note:
        Caller is responsible for cleaning up the temp file after use.
    """
    import tempfile
    
    frappe.logger().info(f"[OCR] Materializing PDF to temp file: {file_url}")
    
    file_doc = _get_file_doc_by_url(file_url)
    
    try:
        pdf_bytes = file_doc.get_content()
    except Exception as e:
        raise ValidationError(
            _("Could not read PDF file: {0}. Error: {1}").format(file_url, str(e))
        )
    
    if not pdf_bytes:
        raise ValidationError(_("PDF content is empty for file: {0}").format(file_url))
    
    # Write to temp file
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", prefix="ocr_")
    try:
        tmp.write(pdf_bytes)
        tmp.flush()
        tmp.close()
        frappe.logger().info(f"[OCR] Temp file created: {tmp.name} ({len(pdf_bytes)} bytes)")
        return tmp.name
    except Exception as e:
        # Clean up on error
        try:
            import os
            os.unlink(tmp.name)
        except Exception:
            pass
        raise ValidationError(_("Could not write temp file: {0}").format(str(e)))


def _build_google_vision_url(settings: dict[str, Any]) -> str:
    endpoint = settings.get("google_vision_endpoint") or DEFAULT_SETTINGS["google_vision_endpoint"]
    parsed = urlparse(endpoint)

    if not parsed.scheme or not parsed.netloc:
        _raise_validation_error(_("Google Vision endpoint is invalid."))

    normalized = _normalize_google_vision_path(parsed.path, is_pdf=True)
    return f"{parsed.scheme}://{parsed.netloc}/v1/{normalized}"


def _parse_service_account_json(raw_value: str) -> dict[str, Any]:
    try:
        return json.loads(raw_value)
    except Exception:
        try:
            decoded = base64.b64decode(raw_value).decode("utf-8")
            return json.loads(decoded)
        except Exception:
            raise ValidationError(_("Google Vision Service Account JSON is invalid. Please check Tax Invoice OCR Settings."))


def _load_service_account_info(settings: dict[str, Any]) -> dict[str, Any] | None:
    """
    Load Google Vision Service Account JSON from file.
    
    🔥 FRAPPE CLOUD SAFE: Uses File.get_content() instead of local filesystem.
    Works with local files, S3, and remote storage.
    """
    file_url = settings.get("google_vision_service_account_file")

    if file_url:
        try:
            # Cloud-safe: use Frappe File API
            file_doc = _get_file_doc_by_url(file_url)
            if not file_doc:
                raise ValidationError(_("Google Vision Service Account file not found: {0}").format(file_url))
            
            content_bytes = file_doc.get_content()
            if isinstance(content_bytes, bytes):
                content = content_bytes.decode("utf-8")
            else:
                content = content_bytes
                
        except ValidationError:
            raise
        except Exception as exc:
            raise ValidationError(_("Could not read Google Vision Service Account file: {0}").format(exc))
        
        return _parse_service_account_json(content)

    return None


def _get_google_vision_headers(settings: dict[str, Any]) -> dict[str, str]:
    service_account_info = _load_service_account_info(settings)
    try:
        import google.auth  # type: ignore
        from google.auth.transport.requests import Request  # type: ignore
        if service_account_info:
            from google.oauth2 import service_account  # type: ignore
    except Exception:
        raise ValidationError(
            _(
                "Google Vision credentials are not configured. "
                "Install google-auth and provide Service Account JSON, or configure Application Default Credentials (service account). "
                "API Key is not supported for the selected OCR flow."
            )
        )

    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    credentials = None
    if service_account_info:
        credentials = service_account.Credentials.from_service_account_info(service_account_info, scopes=scopes)
    else:
        credentials, _ = google.auth.default(scopes=scopes)

    if credentials.expired or not credentials.valid:
        credentials.refresh(Request())

    if not credentials.token:
        raise ValidationError(_("Failed to obtain Google Vision access token from credentials."))

    return {"Authorization": f"Bearer {credentials.token}"}


def _google_vision_ocr(file_url: str, settings: dict[str, Any]) -> tuple[str, dict[str, Any], float]:
    def _iter_block_text(entry: dict[str, Any]) -> list[tuple[str, float, float, float]]:
        """Yield (text, y_min, y_max, confidence) for each block with normalized coordinates."""
        pages = (entry.get("fullTextAnnotation") or {}).get("pages") or []
        blocks: list[tuple[str, float, float, float]] = []

        for page in pages:
            for block in page.get("blocks") or []:
                vertices = (block.get("boundingBox") or {}).get("normalizedVertices") or []
                ys = [v.get("y", 0) for v in vertices if isinstance(v, dict) and "y" in v]
                if not ys:
                    continue
                y_min, y_max = min(ys), max(ys)
                block_conf = flt(block.get("confidence", 0))

                texts: list[str] = []
                for para in block.get("paragraphs") or []:
                    for word in para.get("words") or []:
                        symbols = [sym.get("text", "") for sym in (word.get("symbols") or []) if isinstance(sym, dict)]
                        word_text = "".join(symbols).strip()
                        if word_text:
                            texts.append(word_text)
                if texts:
                    blocks.append((" ".join(texts), y_min, y_max, block_conf))
        return blocks

    def _strip_border_artifacts(text: str) -> str:
        # Remove lines that are mostly border characters
        border_chars = set("─│—|+═╔╗╚╝•·-_=#[]")
        cleaned_lines: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if len([ch for ch in stripped if ch in border_chars]) >= max(3, int(0.6 * len(stripped))):
                continue
            cleaned_lines.append(re.sub(r"[│─—|+_=]+", " ", stripped))
        return "\n".join(cleaned_lines)

    def _needs_full_text_fallback(text: str) -> bool:
        if not text or not text.strip():
            return True
        lower = text.lower()
        key_markers = ("pembeli", "penerima jasa", "dasar pengenaan pajak", "jumlah ppn")
        if any(marker in lower for marker in key_markers):
            return False
        if len(AMOUNT_REGEX.findall(text)) >= 2:
            return False
        return True

    try:
        import requests
    except Exception as exc:
        raise ValidationError(_("Google Vision OCR requires the requests package: {0}").format(exc))

    local_path, content = _load_pdf_content_base64(file_url)
    endpoint = _build_google_vision_url(settings)
    language = settings.get("ocr_language") or "id"
    max_pages = max(cint(settings.get("ocr_max_pages", 2)), 1)
    headers = _get_google_vision_headers(settings)

    request_body: dict[str, Any] = {
        "requests": [
            {
                "inputConfig": {"mimeType": "application/pdf", "content": content},
                "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
            }
        ]
    }

    image_context = {}
    if language:
        image_context["languageHints"] = [language]
    if image_context:
        request_body["requests"][0]["imageContext"] = image_context

    if max_pages and "files:annotate" in endpoint:
        request_body["requests"][0]["pages"] = list(range(1, max_pages + 1))

    try:
        response = requests.post(endpoint, json=request_body, headers=headers, timeout=45)
    except Exception as exc:
        raise ValidationError(_("Failed to call Google Vision OCR: {0}").format(exc))

    if response.status_code != 200:
        raise ValidationError(
            _("Google Vision OCR request failed with status {0}: {1}").format(
                response.status_code, response.text
            )
        )

    data = response.json() if hasattr(response, "json") else {}
    responses = data.get("responses") or []
    if not responses:
        raise ValidationError(_("Google Vision OCR did not return any responses for file {0}.").format(file_url))

    def _iter_entries(resp: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for entry in resp:
            yield entry
            nested_responses = entry.get("responses")
            if isinstance(nested_responses, list):
                for nested in nested_responses:
                    if isinstance(nested, dict):
                        yield nested

    texts: list[str] = []
    confidence_values: list[float] = []
    min_block_conf = flt(settings.get("ocr_min_confidence", 0.0)) or 0.0
    full_text_candidates: list[str] = []

    for entry in _iter_entries(responses):
        block_texts = _iter_block_text(entry)
        filtered_blocks = [
            (text, conf)
            for text, y_min, y_max, conf in block_texts
            if conf >= min_block_conf and (y_max <= 0.35 or y_min >= 0.65)
        ]
        if filtered_blocks:
            texts.extend([text for text, _ in filtered_blocks])
            confidence_values.extend([conf for _, conf in filtered_blocks])
            full_text = (entry.get("fullTextAnnotation") or {}).get("text")
            if full_text:
                processed_full = _strip_border_artifacts((full_text or "").strip())
                if processed_full:
                    full_text_candidates.append(processed_full)
            continue

        full_text = (entry.get("fullTextAnnotation") or {}).get("text")
        if not full_text:
            text_annotations = entry.get("textAnnotations") or []
            if text_annotations:
                full_text = text_annotations[0].get("description")
        if full_text:
            processed_full = _strip_border_artifacts((full_text or "").strip())
            if processed_full:
                full_text_candidates.append(processed_full)
                texts.append(processed_full)
            pages = (entry.get("fullTextAnnotation") or {}).get("pages") or []
            for page in pages:
                if "confidence" in page:
                    try:
                        confidence_values.append(flt(page.get("confidence")))
                    except Exception:
                        continue

    text = _strip_border_artifacts("\n".join(texts).strip())

    if _needs_full_text_fallback(text) and full_text_candidates:
        fallback_text = "\n".join(full_text_candidates).strip()
        if fallback_text and fallback_text not in text:
            text = "\n".join([text, fallback_text]).strip()

    if not text:
        for entry in _iter_entries(responses):
            full_text = (entry.get("fullTextAnnotation") or {}).get("text")
            if full_text:
                pages = (entry.get("fullTextAnnotation") or {}).get("pages") or []
                for page in pages:
                    if "confidence" in page:
                        try:
                            confidence_values.append(flt(page.get("confidence")))
                        except Exception:
                            continue
                text = _strip_border_artifacts(full_text.strip())
                if text:
                    break
            text_annotations = entry.get("textAnnotations") or []
            if text_annotations:
                description = text_annotations[0].get("description")
                if description:
                    text = _strip_border_artifacts((description or "").strip())
                    if text:
                        break
    if not text:
        return "", data, 0.0

    confidence = max(confidence_values) if confidence_values else 0.0
    return text, data, confidence


def _tesseract_ocr(file_url: str, settings: dict[str, Any]) -> tuple[str, dict[str, Any] | None, float]:
    """
    Extract text using Tesseract OCR.
    
    🔥 FRAPPE CLOUD SAFE: Uses temp file from File.get_content() bytes.
    """
    import os
    
    # Materialize PDF to temp file (Cloud-safe)
    local_path = _materialize_pdf_to_tempfile(file_url)
    
    language = settings.get("ocr_language") or "eng"
    command = settings.get("tesseract_cmd")

    if not command:
        raise ValidationError(_("Tesseract command/path is not configured. Please update Tax Invoice OCR Settings."))

    try:
        result = subprocess.run(
            [command, local_path, "stdout", "-l", language],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        text = (result.stdout or "").strip()
        
    except FileNotFoundError:
        raise ValidationError(_("Tesseract command not found: {0}").format(command))
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise ValidationError(_("Tesseract OCR failed: {0}").format(stderr or exc)) from exc
    except subprocess.TimeoutExpired:
        raise ValidationError(_("Tesseract OCR timed out for file {0}.").format(file_url))
    finally:
        # Clean up temp file
        try:
            if local_path and os.path.exists(local_path):
                os.unlink(local_path)
                frappe.logger().info(f"[OCR] Temp file cleaned up: {local_path}")
        except Exception as cleanup_err:
            frappe.logger().warning(f"[OCR] Failed to clean up temp file: {cleanup_err}")

    if not text:
        return "", None, 0.0

    return text, None, 0.0


def ocr_extract_text_from_pdf(file_url: str, provider: str) -> tuple[str, dict[str, Any] | None, float]:
    settings = get_settings()
    _validate_provider_settings(provider, settings)

    if provider == "Google Vision":
        return _google_vision_ocr(file_url, settings)

    if provider == "Tesseract":
        return _tesseract_ocr(file_url, settings)

    raise ValidationError(_("OCR provider {0} is not supported.").format(provider))


def _update_doc_after_ocr(
    doc: Any,
    doctype: str,
    parsed: dict[str, Any],
    confidence: float,
    raw_json: dict[str, Any] | None = None,
):
    """
    Update document with OCR results.
    Uses save() to properly trigger hooks and update modified timestamp.
    """
    allowed_keys = set(tax_invoice_fields.get_field_map(doctype).keys()) & ALLOWED_OCR_FIELDS
    extra_notes: list[str] = []
    
    # Set OCR status and confidence
    ocr_status_field = _get_fieldname(doctype, "ocr_status")
    status_field = _get_fieldname(doctype, "status")
    confidence_field = _get_fieldname(doctype, "ocr_confidence")
    
    setattr(doc, ocr_status_field, "Done")
    setattr(doc, status_field, "Needs Review")
    setattr(doc, confidence_field, confidence)
    
    # Update parsed fields
    for key, value in parsed.items():
        if key not in allowed_keys:
            continue

        if key in {"dpp", "ppn"}:
            sanitized = _sanitize_amount(value)
            if sanitized is None:
                extra_notes.append(_("OCR ignored invalid {0} value").format(key.upper()))
                continue
            value = sanitized

        setattr(doc, _get_fieldname(doctype, key), value)

    # Update notes if any
    if extra_notes:
        notes_field = _get_fieldname(doctype, "notes")
        existing_notes = getattr(doc, notes_field, None) or ""
        combined = f"{existing_notes}\n" if existing_notes else ""
        combined += "\n".join(extra_notes)
        setattr(doc, notes_field, combined)

    # Update raw JSON
    if raw_json is not None:
        setattr(doc, _get_fieldname(doctype, "ocr_raw_json"), json.dumps(raw_json, indent=2))
    
    # 🔥 CRITICAL: Use save() to trigger hooks properly
    # This ensures on_update() is called automatically with correct state
    doc.flags.ignore_validate = True  # Skip validation in background job
    doc.flags.ignore_permissions = True
    doc.save()
    
    frappe.logger().info(f"[OCR] Doc saved with ocr_status=Done, modified={doc.modified}")


def _run_ocr_job(name: str, target_doctype: str, provider: str):
    # 🔥 EARLY LOG: Kalau ini tidak muncul → worker crash sebelum function executed
    frappe.logger().info(f"[OCR JOB START] {target_doctype} {name} | Provider: {provider}")
    
    try:
        target_doc = frappe.get_doc(target_doctype, name)
        frappe.logger().info(f"[OCR] Doc loaded: {name}")
        
        settings = get_settings()
        pdf_field = _get_fieldname(target_doctype, "tax_invoice_pdf")
        file_url = getattr(target_doc, pdf_field)
        
        frappe.logger().info(f"[OCR] File URL: {file_url}")
        
        # 🔧 CRASH-GAP FIX: Set status to Processing WITH timestamp for recovery detection
        # If worker dies after this point but before completion, we can detect stale jobs
        processing_update = {
            _get_fieldname(target_doctype, "ocr_status"): "Processing",
        }
        # Add timestamp if field exists (for crash recovery)
        ocr_started_field = _get_fieldname(target_doctype, "ocr_started_at")
        if hasattr(target_doc, ocr_started_field) or frappe.db.has_column(target_doctype, ocr_started_field):
            processing_update[ocr_started_field] = frappe.utils.now_datetime()
        
        target_doc.db_set(processing_update)
        frappe.logger().info(f"[OCR] Status set to Processing (with timestamp)")
        
        # Extract text from PDF
        frappe.logger().info(f"[OCR] Calling ocr_extract_text_from_pdf...")
        text, raw_json, confidence = ocr_extract_text_from_pdf(file_url, provider)
        frappe.logger().info(f"[OCR] Extraction complete | Confidence: {confidence} | Text length: {len(text or '')}")
        
        if not (text or "").strip():
            error_msg = _("OCR returned empty text for file {0}.").format(file_url)
            frappe.logger().warning(f"[OCR] Empty text returned: {error_msg}")
            update_payload = {
                _get_fieldname(target_doctype, "ocr_status"): "Failed",
                _get_fieldname(target_doctype, "notes"): error_msg,
            }
            if raw_json is not None:
                update_payload[_get_fieldname(target_doctype, "ocr_raw_json")] = json.dumps(raw_json, indent=2)
            target_doc.db_set(update_payload)
            return
        
        # Parse the extracted text
        frappe.logger().info(f"[OCR] Parsing faktur pajak text...")
        parsed, estimated_confidence = parse_faktur_pajak_text(text or "")
        frappe.logger().info(f"[OCR] Parse complete | Found fp_no: {parsed.get('fp_no')}")
        
        if not parsed.get("fp_no"):
            raw_fp_no = _extract_faktur_number_from_json(raw_json)
            if raw_fp_no:
                parsed["fp_no"] = raw_fp_no
                frappe.logger().info(f"[OCR] Extracted fp_no from JSON: {raw_fp_no}")
        
        # Update doc with OCR results
        frappe.logger().info(f"[OCR] Updating doc with OCR results...")
        _update_doc_after_ocr(
            target_doc,
            target_doctype,
            parsed,
            confidence or estimated_confidence,
            raw_json if cint(settings.get("store_raw_ocr_json", 1)) else None,
        )
        
        # ✅ save() already called in _update_doc_after_ocr()
        # This automatically triggers on_update() hook which enqueues auto-parse
        # No need for manual commit/reload/on_update() call
        
        frappe.logger().info(f"[OCR JOB SUCCESS] {target_doctype} {name}")
        
    except Exception as exc:
        frappe.logger().error(
            f"[OCR JOB CRASHED] {target_doctype} {name} | Error: {str(exc)[:200]}",
            exc_info=True
        )
        
        error_message = getattr(exc, "message", None) or str(exc)
        error_message_short = error_message[:500] if len(error_message) > 500 else error_message
        
        try:
            # Try to update status to Failed
            target_doc = frappe.get_doc(target_doctype, name)
            target_doc.db_set(
                {
                    _get_fieldname(target_doctype, "ocr_status"): "Failed",
                    _get_fieldname(target_doctype, "notes"): error_message_short,
                }
            )
            frappe.logger().info(f"[OCR] Status set to Failed for {name}")
        except Exception as db_exc:
            # Even db_set failed - log it
            frappe.logger().error(f"[OCR] Could not set Failed status: {str(db_exc)}")
        
        frappe.log_error(
            title=f"OCR FAILED: {target_doctype} {name}",
            message=frappe.get_traceback()
        )
        
        # 🔥 CRITICAL: Re-raise exception agar worker tahu job gagal
        raise


def _enqueue_ocr(doc: Any, doctype: str):
    """Enqueue OCR background job with race condition protection.
    
    Uses try-finally to ensure status is set to Failed if enqueue fails,
    preventing stuck "Queued" status.
    
    Job name pattern: "ocr:Tax Invoice OCR Upload:{docname}" for deterministic deduplication.
    """
    settings = get_settings()
    pdf_field = _get_fieldname(doctype, "tax_invoice_pdf")
    _validate_pdf_size(getattr(doc, pdf_field, None), cint(settings.get("ocr_file_max_mb", 10)))

    status_field = _get_fieldname(doctype, "ocr_status")
    notes_field = _get_fieldname(doctype, "notes")
    
    # Set status to Queued first
    doc.db_set({status_field: "Queued", notes_field: None})
    
    provider = settings.get("ocr_provider", "Manual Only")
    method_path = f"{__name__}._run_ocr_job"
    
    # Deterministic job_name: "ocr:Tax Invoice OCR Upload:{docname}"
    job_name = f"ocr:{doctype}:{doc.name}"
    
    try:
        frappe.enqueue(
            method_path,
            queue="long",
            job_name=job_name,
            timeout=300,
            now=getattr(frappe.flags, "in_test", False),
            is_async=not getattr(frappe.flags, "in_test", False),
            enqueue_after_commit=True,  # Ensure Queued status is committed first
            **{"name": doc.name, "target_doctype": doctype, "provider": provider},
        )
        frappe.logger().info(f"[OCR ENQUEUE] Job queued: {job_name}")
    except Exception as enqueue_err:
        # Rollback: if enqueue fails, set status to Failed to avoid stuck Queued
        frappe.logger().error(f"[OCR ENQUEUE FAILED] {job_name}: {enqueue_err}")
        doc.db_set({
            status_field: "Failed",
            notes_field: f"Enqueue failed: {str(enqueue_err)[:200]}"
        })
        raise


def _get_party_npwp(doc: Any, doctype: str) -> str | None:
    if doctype == "Sales Invoice":
        party = getattr(doc, "customer", None) or getattr(doc, "party", None)
        party_type = "Customer"
    else:
        party = getattr(doc, "supplier", None) or getattr(doc, "party", None)
        party_type = "Supplier"

    if not party:
        return None

    for field in ("tax_id", "npwp"):
        if not frappe.db.has_column(party_type, field):
            continue
        value = frappe.db.get_value(party_type, party, field)
        if value:
            return normalize_npwp(value)
    return None


def _build_filters(target_doctype: str, fp_no: str, company: str | None) -> dict[str, Any]:
    filters: dict[str, Any] = {
        "name": ("!=", None),
        _get_fieldname(target_doctype, "fp_no"): fp_no,
    }
    if company and target_doctype not in ("Expense Request", "Tax Invoice OCR Upload"):
        filters["company"] = company
    if target_doctype not in ("Expense Request", "Tax Invoice OCR Upload"):
        filters["docstatus"] = ("<", 2)
    return filters


def _check_duplicate_fp_no(current_name: str, fp_no: str, company: str | None, doctype: str) -> bool:
    if not fp_no:
        return False

    targets = [
        "Purchase Invoice",
        "Expense Request",
        "Branch Expense Request",
        "Sales Invoice",
        "Tax Invoice OCR Upload",
    ]
    filters_cache: dict[str, dict[str, Any]] = {}

    for target in targets:
        fieldname = _get_fieldname(target, "fp_no")
        if not fieldname:
            continue

        filters = filters_cache.setdefault(
            target,
            _build_filters(target, fp_no, company),
        )
        filters["name"] = ("!=", current_name if target == doctype else "")

        try:
            matches = frappe.get_all(target, filters=filters, pluck="name")
        except Exception:
            continue

        if matches:
            return True

    return False


def sync_tax_invoice_upload(doc: Any, doctype: str, upload_name: str | None = None, *, save: bool = True):
    link_field = _get_upload_link_field(doctype)
    if not link_field:
        return None

    target_doc = doc if not isinstance(doc, str) else frappe.get_doc(doctype, doc)
    upload_docname = upload_name or getattr(target_doc, link_field, None)
    if not upload_docname:
        return None

    upload_doc = frappe.get_doc("Tax Invoice OCR Upload", upload_docname)
    if getattr(upload_doc, "verification_status", None) != "Verified":
        raise ValidationError(_("Tax Invoice OCR Upload {0} must be Verified before syncing.").format(upload_docname))
    _copy_tax_invoice_fields(upload_doc, "Tax Invoice OCR Upload", target_doc, doctype)

    if save:
        target_doc.save(ignore_permissions=True)

    return {
        "upload": upload_doc.name,
        "status": _get_value(upload_doc, "Tax Invoice OCR Upload", "status"),
    }


def verify_tax_invoice(doc: Any, *, doctype: str, force: bool = False) -> dict[str, Any]:
    settings = get_settings()
    notes: list[str] = []

    fp_no = _get_value(doc, doctype, "fp_no")
    if fp_no:
        fp_digits = re.sub(r"\D", "", str(fp_no))
        if len(fp_digits) != 17:
            notes.append(_("Tax invoice number must be exactly 16 digits."))
    company = getattr(doc, "company", None)
    if not company:
        cost_center = getattr(doc, "cost_center", None)
        if cost_center:
            company = frappe.db.get_value("Cost Center", cost_center, "company")

    if cint(settings.get("block_duplicate_fp_no", 1)) and fp_no and company:
        duplicate = _check_duplicate_fp_no(doc.name, fp_no, company, doctype)
        _set_value(doc, doctype, "duplicate_flag", 1 if duplicate else 0)
        if duplicate:
            notes.append(_("Duplicate tax invoice number detected."))

    party_npwp = _get_party_npwp(doc, doctype)
    doc_npwp = normalize_npwp(_get_value(doc, doctype, "npwp"))
    if doc_npwp and party_npwp:
        npwp_match = 1 if doc_npwp == party_npwp else 0
        _set_value(doc, doctype, "npwp_match", npwp_match)
        if npwp_match == 0:
            label = _("supplier") if doctype != "Sales Invoice" else _("customer")
            notes.append(_("NPWP on tax invoice does not match {0}.").format(label))

    expected_ppn = None
    if _get_value(doc, doctype, "ppn_type") == "Standard":
        dpp = flt(_get_value(doc, doctype, "dpp", 0))
        template_rate = None
        taxes = getattr(doc, "taxes", []) or []
        for row in taxes:
            try:
                rate = getattr(row, "rate", None)
                if rate is not None:
                    template_rate = rate
                    break
            except Exception:
                continue
        rate = template_rate if template_rate is not None else 11
        expected_ppn = dpp * rate / 100
    else:
        expected_ppn = 0

    tolerance = flt(settings.get("tolerance_idr", 10))
    if expected_ppn is not None:
        actual_ppn = flt(_get_value(doc, doctype, "ppn", 0))
        diff = abs(actual_ppn - expected_ppn)
        if diff > tolerance:
            message = _(
                "PPN amount differs from expected by more than {0}. Difference: {1}"
            ).format(
                format_value(tolerance, "Currency"), format_value(diff, "Currency")
            )
            if not force:
                _raise_validation_error(message)
            notes.append(message)

    dpp_value = flt(_get_value(doc, doctype, "dpp", 0))
    ppn_value = flt(_get_value(doc, doctype, "ppn", 0))
    ppnbm_value = flt(_get_value(doc, doctype, "ppnbm", 0))
    if ppnbm_value > 0 and dpp_value > 0:
        ppn_rate = (ppn_value / dpp_value) * 100
        if abs(ppn_rate - 11) > 0.01:
            notes.append(_("PPN rate must be 11% when PPNBM is present."))

    if notes and not force:
        _set_value(doc, doctype, "status", "Needs Review")
    else:
        _set_value(doc, doctype, "status", "Verified")

    if notes:
        _set_value(doc, doctype, "notes", "\n".join(notes))

    doc.save(ignore_permissions=True)
    return {"status": _get_value(doc, doctype, "status"), "notes": notes}


def run_ocr(docname: str, doctype: str):
    """Run OCR for Tax Invoice OCR Upload document.
    
    Race condition guards:
    - Only allows doctype "Tax Invoice OCR Upload" (hard guard)
    - Returns early if ocr_status is already "Queued" or "Processing"
    - Uses deterministic job_name for RQ deduplication
    """
    if doctype != "Tax Invoice OCR Upload":
        frappe.throw(_("OCR only allowed via Tax Invoice OCR Upload"))
    
    settings = get_settings()
    if not cint(settings.get("enable_tax_invoice_ocr", 0)):
        _raise_validation_error(_("Tax Invoice OCR is disabled. Enable it in Tax Invoice OCR Settings."))

    provider_ready, provider_error = _get_provider_status(settings)
    if not provider_ready:
        _raise_validation_error(provider_error)

    doc = frappe.get_doc(doctype, docname)
    
    # 🔥 Race condition guard: Prevent duplicate OCR jobs
    current_status = getattr(doc, _get_fieldname(doctype, "ocr_status"), None)
    if current_status in ("Queued", "Processing"):
        frappe.logger().info(f"[OCR SKIP] {doctype} {docname} already {current_status}")
        return {
            "queued": False,
            "message": _("OCR is already {0}. Please wait for completion.").format(current_status),
            "status": current_status
        }
    
    _enqueue_ocr(doc, doctype)
    return {"queued": True}


def _get_job_info(job_name: str) -> dict[str, Any] | list[dict[str, Any]] | None:
    get_info = getattr(background_jobs, "get_info", None)
    if callable(get_info):
        return get_info(job_name=job_name)

    get_job_info = getattr(background_jobs, "get_job_info", None)
    if callable(get_job_info):
        return get_job_info(job_name)

    return None


def _pick_job_info(job_name: str) -> dict[str, Any] | None:
    try:
        jobs = _get_job_info(job_name)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Tax Invoice OCR monitor get_info failed")
        return None

    if isinstance(jobs, dict):
        return jobs
    if not isinstance(jobs, (list, tuple)):
        return None

    for job in jobs:
        if not isinstance(job, dict):
            continue
        if job.get("job_name") == job_name or job.get("name") == job_name:
            return job

    return jobs[0] if jobs else None


def _format_job_info(job_info: dict[str, Any] | None, job_name: str) -> dict[str, Any] | None:
    if not job_info:
        return None

    def pick(*keys):
        for key in keys:
            if key in job_info:
                return job_info.get(key)
        return None

    return {
        "name": pick("job_name", "name") or job_name,
        "queue": pick("queue"),
        "status": pick("status", "state"),
        "exc_info": pick("exc_info", "error"),
        "kwargs": pick("kwargs"),
        "enqueued_at": pick("enqueued_at"),
        "started_at": pick("started_at"),
        "ended_at": pick("ended_at", "finished_at"),
    }


def get_tax_invoice_ocr_monitoring(docname: str, doctype: str) -> dict[str, Any]:
    if doctype not in tax_invoice_fields.get_supported_doctypes():
        raise ValidationError(_("Doctype {0} is not supported for Tax Invoice OCR.").format(doctype))

    settings = get_settings()
    doc = frappe.get_doc(doctype, docname)

    source_doc = doc
    source_doctype = doctype
    link_field = _get_upload_link_field(doctype)
    upload_name = None
    if link_field:
        upload_name = getattr(doc, link_field, None)
        if upload_name:
            source_doctype = "Tax Invoice OCR Upload"
            source_doc = frappe.get_doc(source_doctype, upload_name)

    pdf_field = _get_fieldname(source_doctype, "tax_invoice_pdf")
    # 🔥 FIX: Match job_name pattern from _enqueue_ocr: "ocr:{doctype}:{name}"
    job_name = f"ocr:{source_doctype}:{source_doc.name}"
    job_info = _format_job_info(_pick_job_info(job_name), job_name)
    doc_info = {
        "name": docname,
        "doctype": doctype,
        "upload_name": upload_name,
        "ocr_status": _get_value(source_doc, source_doctype, "ocr_status"),
        "verification_status": _get_value(source_doc, source_doctype, "status"),
        "verification_notes": _get_value(source_doc, source_doctype, "notes"),
        "ocr_confidence": _get_value(source_doc, source_doctype, "ocr_confidence"),
        "fp_no": _get_value(source_doc, source_doctype, "fp_no"),
        "fp_date": _get_value(source_doc, source_doctype, "fp_date"),
        "npwp": _get_value(source_doc, source_doctype, "npwp"),
        "dpp": _get_value(source_doc, source_doctype, "dpp"),
        "ppn": _get_value(source_doc, source_doctype, "ppn"),
        "ppnbm": _get_value(source_doc, source_doctype, "ppnbm"),
        "ppn_type": _get_value(source_doc, source_doctype, "ppn_type"),
        "duplicate_flag": _get_value(source_doc, source_doctype, "duplicate_flag"),
        "npwp_match": _get_value(source_doc, source_doctype, "npwp_match"),
        "tax_invoice_pdf": getattr(source_doc, pdf_field, None),
        "ocr_raw_json": _get_value(source_doc, source_doctype, "ocr_raw_json"),
        "ocr_raw_json_present": bool(_get_value(source_doc, source_doctype, "ocr_raw_json")),
    }

    status_fieldname = _get_fieldname(source_doctype, "ocr_status")
    verification_status = doc_info.get("verification_status")
    current_ocr_status = doc_info.get("ocr_status")
    active_job = job_info.get("status") if job_info else None
    if (
        verification_status == "Verified"
        and current_ocr_status in {None, "", "Queued", "Processing", "Not Started"}
        and active_job not in {"queued", "started"}
    ):
        new_status = "Done"
        if current_ocr_status != new_status:
            setter = getattr(source_doc, "db_set", None)
            if callable(setter):
                setter(status_fieldname, new_status)
            else:
                setattr(source_doc, status_fieldname, new_status)
            doc_info["ocr_status"] = new_status

    return {
        "doc": doc_info,
        "job": job_info,
        "job_name": job_name,
        "provider": settings.get("ocr_provider"),
        "max_retry": settings.get("ocr_max_retry"),
    }


# ============================================================================
# DIAGNOSTIC FUNCTIONS (FOR DEBUGGING)
# ============================================================================

def check_ocr_dependencies() -> dict[str, Any]:
    """
    Check if all OCR dependencies are available.
    Call this from console to diagnose dependency issues.
    
    Usage:
        from imogi_finance.tax_invoice_ocr import check_ocr_dependencies
        check_ocr_dependencies()
    """
    result = {
        "all_ok": True,
        "dependencies": {},
        "errors": []
    }
    
    # Check google-auth
    try:
        import google.auth
        result["dependencies"]["google-auth"] = {
            "installed": True,
            "version": getattr(google.auth, "__version__", "unknown")
        }
    except ImportError as e:
        result["all_ok"] = False
        result["dependencies"]["google-auth"] = {"installed": False, "error": str(e)}
        result["errors"].append("google-auth not installed")
    
    # Check requests
    try:
        import requests
        result["dependencies"]["requests"] = {
            "installed": True,
            "version": requests.__version__
        }
    except ImportError as e:
        result["all_ok"] = False
        result["dependencies"]["requests"] = {"installed": False, "error": str(e)}
        result["errors"].append("requests not installed")
    
    # Check PyMuPDF (fitz)
    try:
        import fitz
        result["dependencies"]["PyMuPDF"] = {
            "installed": True,
            "version": fitz.version
        }
    except ImportError as e:
        result["all_ok"] = False
        result["dependencies"]["PyMuPDF"] = {"installed": False, "error": str(e)}
        result["errors"].append("PyMuPDF (fitz) not installed")
    
    return result


def test_ocr_environment(upload_name: str | None = None) -> dict[str, Any]:
    """
    Test OCR environment and configuration.
    
    Usage:
        from imogi_finance.tax_invoice_ocr import test_ocr_environment
        test_ocr_environment("04002600021035998")
    """
    result = {
        "dependencies": check_ocr_dependencies(),
        "settings": {},
        "upload_doc": None,
        "file_check": None
    }
    
    # Check settings
    try:
        settings = get_settings()
        result["settings"] = {
            "enable_tax_invoice_ocr": settings.get("enable_tax_invoice_ocr"),
            "ocr_provider": settings.get("ocr_provider"),
            "google_vision_service_account_file": settings.get("google_vision_service_account_file"),
            "google_vision_endpoint": settings.get("google_vision_endpoint"),
        }
        
        provider_ready, provider_error = _get_provider_status(settings)
        result["settings"]["provider_ready"] = provider_ready
        result["settings"]["provider_error"] = provider_error
    except Exception as e:
        result["settings"]["error"] = str(e)
    
    # Check upload doc if provided
    if upload_name:
        try:
            doc = frappe.get_doc("Tax Invoice OCR Upload", upload_name)
            result["upload_doc"] = {
                "name": doc.name,
                "ocr_status": doc.ocr_status,
                "file_faktur_pajak": doc.file_faktur_pajak,
            }
            
            # Check file exists - both local and Cloud-safe methods
            if doc.file_faktur_pajak:
                try:
                    # Try direct path first (will fail on Frappe Cloud)
                    local_path = get_site_path(doc.file_faktur_pajak.strip("/"))
                    file_exists = os.path.exists(local_path)
                    file_size = os.path.getsize(local_path) if file_exists else 0
                    
                    result["file_check"] = {
                        "file_url": doc.file_faktur_pajak,
                        "direct_path": local_path,
                        "direct_path_exists": file_exists,
                        "size_bytes": file_size,
                        "size_mb": round(file_size / (1024 * 1024), 2) if file_exists else 0
                    }
                    
                    # Try Cloud-safe access via File.get_content()
                    try:
                        file_doc = _get_file_doc_by_url(doc.file_faktur_pajak)
                        if file_doc:
                            result["file_check"]["cloud_safe_file_doc"] = file_doc.name
                            result["file_check"]["cloud_safe_file_size"] = file_doc.file_size
                            # Try to get actual content
                            content = file_doc.get_content()
                            result["file_check"]["cloud_safe_content_size"] = len(content) if content else 0
                            result["file_check"]["cloud_safe_access"] = True
                        else:
                            result["file_check"]["cloud_safe_access"] = False
                            result["file_check"]["cloud_safe_error"] = "File doc not found"
                    except Exception as cloud_err:
                        result["file_check"]["cloud_safe_access"] = False
                        result["file_check"]["cloud_safe_error"] = str(cloud_err)
                    
                    # Legacy resolver (for backward compatibility check)
                    if not file_exists:
                        try:
                            resolved_path = _resolve_file_path(doc.file_faktur_pajak)
                            result["file_check"]["resolved_path"] = resolved_path
                            result["file_check"]["resolved_exists"] = os.path.exists(resolved_path)
                            if os.path.exists(resolved_path):
                                result["file_check"]["resolved_size_mb"] = round(
                                    os.path.getsize(resolved_path) / (1024 * 1024), 2
                                )
                        except Exception as resolve_err:
                            result["file_check"]["resolve_error"] = str(resolve_err)
                    
                except Exception as e:
                    result["file_check"] = {"error": str(e)}
        except Exception as e:
            result["upload_doc"] = {"error": str(e)}
    
    return result


@frappe.whitelist()
def recover_stale_ocr_jobs(timeout_minutes: int = 10) -> dict[str, Any]:
    """
    🔧 CRASH-GAP RECOVERY: Detect and recover OCR jobs stuck in Processing state.
    
    This handles the edge case where a worker dies/restarts after setting
    ocr_status="Processing" but before completing OCR or setting to Done/Failed.
    
    Detection criteria:
    - ocr_status = "Processing"
    - ocr_started_at < NOW() - timeout_minutes (if field exists)
    - OR ocr_status = "Processing" for > timeout_minutes based on modified timestamp
    
    Recovery action:
    - Set ocr_status = "Failed"
    - Set notes = "Worker terminated unexpectedly. Please retry OCR."
    
    Args:
        timeout_minutes: How long to wait before considering a job stale (default: 10)
    
    Returns:
        Dict with recovered_count, recovered_docs, and any errors
    
    Usage:
        - Manual: Call from console or API when needed
        - Scheduled: Add to hooks.py scheduler_events for automatic recovery
    
    Example (manual):
        >>> from imogi_finance.tax_invoice_ocr import recover_stale_ocr_jobs
        >>> result = recover_stale_ocr_jobs(timeout_minutes=15)
        >>> print(f"Recovered {result['recovered_count']} stale jobs")
    
    Example (scheduled - add to hooks.py):
        scheduler_events = {
            "cron": {
                "*/15 * * * *": [  # Every 15 minutes
                    "imogi_finance.tax_invoice_ocr.recover_stale_ocr_jobs"
                ]
            }
        }
    """
    from frappe.utils import now_datetime, add_to_date
    
    result = {
        "recovered_count": 0,
        "recovered_docs": [],
        "errors": [],
        "checked_at": str(now_datetime()),
        "timeout_minutes": timeout_minutes
    }
    
    try:
        cutoff_time = add_to_date(now_datetime(), minutes=-timeout_minutes)
        
        # Find stale Processing jobs
        # Strategy: Use modified timestamp as fallback if ocr_started_at doesn't exist
        stale_docs = frappe.get_all(
            "Tax Invoice OCR Upload",
            filters={
                "ocr_status": "Processing",
                "modified": ("<", cutoff_time)
            },
            fields=["name", "modified", "ocr_status"],
            limit=100  # Process in batches to avoid timeout
        )
        
        frappe.logger().info(
            f"[OCR RECOVERY] Found {len(stale_docs)} potentially stale jobs "
            f"(modified before {cutoff_time})"
        )
        
        for doc_info in stale_docs:
            try:
                # Double-check the document is still Processing
                current_status = frappe.db.get_value(
                    "Tax Invoice OCR Upload", 
                    doc_info.name, 
                    "ocr_status"
                )
                
                if current_status != "Processing":
                    # Status changed, skip
                    frappe.logger().info(
                        f"[OCR RECOVERY] Skipping {doc_info.name} - status changed to {current_status}"
                    )
                    continue
                
                # Check if there's an active RQ job for this doc
                job_name = f"ocr:Tax Invoice OCR Upload:{doc_info.name}"
                existing_job = frappe.get_all(
                    "RQ Job",
                    filters={
                        "job_name": job_name,
                        "status": ("in", ["queued", "started"])
                    },
                    limit=1
                )
                
                if existing_job:
                    # Job still exists, don't recover
                    frappe.logger().info(
                        f"[OCR RECOVERY] Skipping {doc_info.name} - active RQ job found"
                    )
                    continue
                
                # Recover the stale job
                frappe.db.set_value(
                    "Tax Invoice OCR Upload",
                    doc_info.name,
                    {
                        "ocr_status": "Failed",
                        "notes": f"Worker terminated unexpectedly after {timeout_minutes} minutes. Please retry OCR."
                    },
                    update_modified=True
                )
                
                result["recovered_count"] += 1
                result["recovered_docs"].append({
                    "name": doc_info.name,
                    "modified": str(doc_info.modified),
                    "recovered_at": str(now_datetime())
                })
                
                frappe.logger().info(
                    f"[OCR RECOVERY] Recovered stale job: {doc_info.name}"
                )
                
            except Exception as doc_err:
                error_msg = f"Failed to recover {doc_info.name}: {str(doc_err)}"
                result["errors"].append(error_msg)
                frappe.logger().error(f"[OCR RECOVERY] {error_msg}")
        
        if result["recovered_count"] > 0:
            frappe.db.commit()
            frappe.logger().info(
                f"[OCR RECOVERY] Successfully recovered {result['recovered_count']} stale jobs"
            )
        
    except Exception as e:
        error_msg = f"Recovery process failed: {str(e)}"
        result["errors"].append(error_msg)
        frappe.logger().error(f"[OCR RECOVERY] {error_msg}", exc_info=True)
    
    return result
