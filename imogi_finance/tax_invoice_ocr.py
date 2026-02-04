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

ALLOWED_OCR_FIELDS = {"fp_no", "fp_date", "npwp", "harga_jual", "dpp", "ppn", "ppnbm", "ppn_type", "notes"}


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


def _get_fieldname(doctype: str, key: str) -> str:
    mapping = tax_invoice_fields.get_field_map(doctype)
    return mapping.get(key, key)


def _get_canonical_key(fieldname: str) -> str:
    if fieldname.startswith("ti_fp_"):
        return fieldname.replace("ti_fp_", "")
    if fieldname.startswith("out_fp_"):
        return fieldname.replace("out_fp_", "")
    if fieldname == "out_buyer_tax_id":
        return "npwp"
    return fieldname


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
    cleaned = (value or "").strip()
    last_dot = cleaned.rfind(".")
    last_comma = cleaned.rfind(",")
    if last_dot == -1 and last_comma == -1:
        return flt(cleaned)

    decimal_index = max(last_dot, last_comma)
    integer_part = re.sub(r"[.,]", "", cleaned[:decimal_index])
    decimal_part = cleaned[decimal_index + 1 :]
    normalized = f"{integer_part}.{decimal_part}"
    return flt(normalized)


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

        # First, check if amount is in the same line after the label
        inline_value = match.group("value") or ""
        inline_amount = _extract_amount(inline_value)
        if inline_amount is not None:
            logger.info(f"🔍 _find_amount_after_label: Found inline amount: {inline_amount}")
            return inline_amount

        # For table format: Check if there's an amount at the END of the same line
        all_amounts_in_line = []
        for amt_match in AMOUNT_REGEX.finditer(line):
            amt = _sanitize_amount(_parse_idr_amount(amt_match.group("amount")))
            if amt is not None and amt >= 10000:
                all_amounts_in_line.append(amt)

        if all_amounts_in_line:
            rightmost_amount = all_amounts_in_line[-1]
            logger.info(f"🔍 _find_amount_after_label: Found {len(all_amounts_in_line)} amounts in line, using rightmost: {rightmost_amount}")
            return rightmost_amount

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
    🔧 FIXED VERSION: Extract Harga Jual from the signature section of Faktur Pajak.

    Improvements:
    1. Better regex pattern that handles reference lines
    2. Enhanced skip keywords for reference/invoice numbers
    3. Multi-strategy approach with proper fallback
    4. Minimum amount validation (must be >= 10,000 IDR)
    """
    logger = frappe.logger("tax_invoice_ocr")
    logger.info("🔍 _extract_harga_jual_from_signature_section: Starting extraction")

    if not text:
        logger.info("🔍 _extract_harga_jual_from_signature_section: No text provided, returning None")
        return None

    # 🔧 FIX 2: Improved regex pattern that allows for reference lines
    # Pattern now uses non-greedy matching and allows multiple lines between name and amount
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

        # Reference patterns - THIS IS THE KEY FIX
        r'referensi\s*:', r'reference\s*:', r'invoice\s*:',
        r'\(referensi', r'nomor\s+referensi', r'no\.\s*ref',
        r'faktur\s+\d+', r'inv[-/]', r'/mtla/', r'/gmm/',

        # Warnings/notices
        r'pemberitahuan\s*:', r'peringatan\s*:',
        r'sesuai\s+dengan', r'ketentuan',

        # Mixed content lines (text + numbers like "Invoice: 12345")
        r'[a-zA-Z]{3,}.*\d{4,}',  # At least 3 letters followed by 4+ digits
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
            # NO letters allowed (this filters out "Referensi: 12345")
            pure_amount_pattern = r'^\s*[\d\s\.,]+\s*$'

            if not re.match(pure_amount_pattern, line_stripped):
                logger.info(f"🔍 Line {idx}: ⚠️ SKIPPED - not pure amount (contains text): '{line_stripped[:50]}'")
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
    🔧 FIXED VERSION: Parse Faktur Pajak text with improved Harga Jual extraction.

    Key improvements:
    1. Prioritize signature section amounts over table amounts
    2. Better filtering of signature amounts with DPP validation
    3. Enhanced fallback logic when signature extraction fails
    4. More robust logging for debugging
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

    # 🔧 FIX 4: Improved signature-based extraction with validation
    logger.info("🔍 parse_faktur_pajak_text: ===== STARTING SIGNATURE EXTRACTION =====")
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

            # ALWAYS set DPP and PPN first (these are reliable)
            matches["dpp"] = dpp
            matches["ppn"] = ppn
            logger.info(f"🔍 parse_faktur_pajak_text: ✅ Set DPP={dpp}, PPN={ppn} from signature")

            # Now determine Harga Jual with validation
            harga_jual_0 = signature_amounts[0]
            harga_jual_1 = signature_amounts[1]

            # 🔧 Validation: Harga Jual should be >= DPP
            if harga_jual_0 >= dpp:
                matches["harga_jual"] = harga_jual_0
                logger.info(f"🔍 parse_faktur_pajak_text: ✅ Harga Jual from [0]: {harga_jual_0}")
                confidence += 0.35
            elif harga_jual_1 >= dpp:
                # Try index [1] as alternative
                matches["harga_jual"] = harga_jual_1
                logger.info(f"🔍 parse_faktur_pajak_text: ✅ Harga Jual from [1]: {harga_jual_1}")
                confidence += 0.35
            else:
                # Both failed validation - will use fallback later
                logger.info(f"🔍 parse_faktur_pajak_text: ⚠️ Both [0]={harga_jual_0} and [1]={harga_jual_1} < DPP={dpp}")
                logger.info(f"🔍 parse_faktur_pajak_text: Will try fallback for Harga Jual")

        elif len(signature_amounts) == 5:
            # 5-amount format (no duplicate or no ppnbm)
            # Could be: [Harga Jual, Harga Jual dup, DPP, PPN, PPnBM] OR [Harga Jual, Potongan, DPP, PPN, PPnBM]
            dpp = signature_amounts[2]
            ppn = signature_amounts[3]

            # ALWAYS set DPP and PPN
            matches["dpp"] = dpp
            matches["ppn"] = ppn
            logger.info(f"🔍 parse_faktur_pajak_text: ✅ Set DPP={dpp}, PPN={ppn} from signature (5-amt)")

            harga_jual = signature_amounts[0]
            if harga_jual >= dpp:
                matches["harga_jual"] = harga_jual
                logger.info(f"🔍 parse_faktur_pajak_text: ✅ Harga Jual: {harga_jual}")
                confidence += 0.3
            else:
                logger.info(f"🔍 parse_faktur_pajak_text: ⚠️ Harga Jual {harga_jual} < DPP {dpp}, will try fallback")

        elif len(signature_amounts) == 4:
            # Minimal 4-amount format: [Harga Jual, Harga Jual dup, DPP, PPN]
            dpp = signature_amounts[2]
            ppn = signature_amounts[3]

            # ALWAYS set DPP and PPN
            matches["dpp"] = dpp
            matches["ppn"] = ppn
            logger.info(f"🔍 parse_faktur_pajak_text: ✅ Set DPP={dpp}, PPN={ppn} from signature (4-amt)")

            harga_jual = signature_amounts[0]
            if harga_jual >= dpp:
                matches["harga_jual"] = harga_jual
                logger.info(f"🔍 parse_faktur_pajak_text: ✅ Harga Jual: {harga_jual}")
                confidence += 0.25
            else:
                logger.info(f"🔍 parse_faktur_pajak_text: ⚠️ Harga Jual {harga_jual} < DPP {dpp}, will try fallback")

    else:
        logger.info(f"🔍 parse_faktur_pajak_text: ⚠️ FALLBACK MODE - Signature extraction insufficient (got {len(signature_amounts) if signature_amounts else 0} amounts)")

    # 🔧 FIX 5: Enhanced fallback with better Harga Jual detection
    if "harga_jual" not in matches:
        logger.info("🔍 parse_faktur_pajak_text: ===== FALLBACK: Trying individual Harga Jual extraction =====")

        # Try focused extraction from signature section
        labeled_harga_jual = _extract_harga_jual_from_signature_section(text or "")
        logger.info(f"🔍 parse_faktur_pajak_text: Labeled extraction result: {labeled_harga_jual}")

        if labeled_harga_jual is not None and labeled_harga_jual >= 10000:
            matches["harga_jual"] = labeled_harga_jual
            logger.info(f"🔍 parse_faktur_pajak_text: ✓ Set Harga Jual from labeled extraction: {labeled_harga_jual}")
            confidence += 0.2

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
            sorted_amounts = sorted(amounts)
            if "dpp" not in matches:
                matches["dpp"] = sorted_amounts[-1]
            if "ppn" not in matches:
                matches["ppn"] = sorted_amounts[-2]
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

def _validate_pdf_size(file_url: str, max_mb: int) -> None:
    if not file_url:
        frappe.throw(_("Please attach a Tax Invoice PDF before running OCR."))

    local_path = get_site_path(file_url.strip("/"))
    try:
        size_mb = os.path.getsize(local_path) / (1024 * 1024)
    except OSError:
        return
    if size_mb and size_mb > max_mb:
        frappe.throw(_("File exceeds maximum size of {0} MB.").format(max_mb))


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


def _load_pdf_content_base64(file_url: str) -> tuple[str, str]:
    if not file_url:
        raise ValidationError(_("Tax Invoice PDF is missing. Please attach the file before running OCR."))

    local_path = get_site_path(file_url.strip("/"))
    try:
        with open(local_path, "rb") as handle:
            content = base64.b64encode(handle.read()).decode("utf-8")
    except FileNotFoundError:
        raise ValidationError(_("Could not read Tax Invoice PDF from {0}.").format(file_url))
    return local_path, content


def _build_google_vision_url(settings: dict[str, Any]) -> str:
    endpoint = settings.get("google_vision_endpoint") or DEFAULT_SETTINGS["google_vision_endpoint"]
    parsed = urlparse(endpoint)

    if not parsed.scheme or not parsed.netloc:
        raise_validation_error(("Google Vision endpoint is invalid."))

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
    file_url = settings.get("google_vision_service_account_file")

    if file_url:
        local_path = get_site_path(file_url.strip("/"))
        try:
            with open(local_path, "r", encoding="utf-8") as handle:
                content = handle.read()
        except FileNotFoundError:
            raise ValidationError(_("Google Vision Service Account file not found: {0}").format(file_url))
        except OSError as exc:
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
        raise ValidationError(_("Google Vision OCR did not return any responses for file {0}.").format(local_path))

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
    local_path, _ = _load_pdf_content_base64(file_url)
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
    except FileNotFoundError:
        raise ValidationError(_("Tesseract command not found: {0}").format(command))
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise ValidationError(_("Tesseract OCR failed: {0}").format(stderr or exc)) from exc
    except subprocess.TimeoutExpired:
        raise ValidationError(_("Tesseract OCR timed out for file {0}.").format(local_path))

    text = (result.stdout or "").strip()
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
    allowed_keys = set(tax_invoice_fields.get_field_map(doctype).keys()) & ALLOWED_OCR_FIELDS
    extra_notes: list[str] = []
    updates: dict[str, Any] = {
        _get_fieldname(doctype, "status"): "Needs Review",
        _get_fieldname(doctype, "ocr_status"): "Done",
        _get_fieldname(doctype, "ocr_confidence"): confidence,
    }
    for key, value in parsed.items():
        if key not in allowed_keys:
            continue

        if key in {"dpp", "ppn"}:
            sanitized = _sanitize_amount(value)
            if sanitized is None:
                extra_notes.append(_("OCR ignored invalid {0} value").format(key.upper()))
                continue
            value = sanitized

        updates[_get_fieldname(doctype, key)] = value

    if extra_notes:
        notes_field = _get_fieldname(doctype, "notes")
        existing_notes = getattr(doc, notes_field, None) or ""
        combined = f"{existing_notes}\n" if existing_notes else ""
        combined += "\n".join(extra_notes)
        updates[notes_field] = combined

    if raw_json is not None:
        updates[_get_fieldname(doctype, "ocr_raw_json")] = json.dumps(raw_json, indent=2)

    db_set = getattr(doc, "db_set", None)
    if callable(db_set):
        db_set(updates)
    else:
        for field, value in updates.items():
            setattr(doc, field, value)


def _run_ocr_job(name: str, target_doctype: str, provider: str):
    target_doc = frappe.get_doc(target_doctype, name)
    settings = get_settings()
    pdf_field = _get_fieldname(target_doctype, "tax_invoice_pdf")
    try:
        target_doc.db_set(_get_fieldname(target_doctype, "ocr_status"), "Processing")
        file_url = getattr(target_doc, pdf_field)
        text, raw_json, confidence = ocr_extract_text_from_pdf(file_url, provider)
        if not (text or "").strip():
            update_payload = {
                _get_fieldname(target_doctype, "ocr_status"): "Failed",
                _get_fieldname(target_doctype, "notes"): _(
                    "OCR returned empty text for file {0}."
                ).format(file_url),
            }
            if raw_json is not None:
                update_payload[_get_fieldname(target_doctype, "ocr_raw_json")] = json.dumps(raw_json, indent=2)
            target_doc.db_set(update_payload)
            return
        parsed, estimated_confidence = parse_faktur_pajak_text(text or "")
        if not parsed.get("fp_no"):
            raw_fp_no = _extract_faktur_number_from_json(raw_json)
            if raw_fp_no:
                parsed["fp_no"] = raw_fp_no
        _update_doc_after_ocr(
            target_doc,
            target_doctype,
            parsed,
            confidence or estimated_confidence,
            raw_json if cint(settings.get("store_raw_ocr_json", 1)) else None,
        )
    except Exception as exc:
        target_doc.db_set(
            {
                _get_fieldname(target_doctype, "ocr_status"): "Failed",
                _get_fieldname(target_doctype, "notes"): getattr(exc, "message", None) or str(exc),
            }
        )
        frappe.log_error(frappe.get_traceback(), "Tax Invoice OCR failed")


def _enqueue_ocr(doc: Any, doctype: str):
    settings = get_settings()
    pdf_field = _get_fieldname(doctype, "tax_invoice_pdf")
    _validate_pdf_size(getattr(doc, pdf_field, None), cint(settings.get("ocr_file_max_mb", 10)))

    doc.db_set(
        {
            _get_fieldname(doctype, "ocr_status"): "Queued",
            _get_fieldname(doctype, "notes"): None,
        }
    )
    provider = settings.get("ocr_provider", "Manual Only")

    method_path = f"{__name__}._run_ocr_job"
    frappe.enqueue(
        method_path,
        queue="long",
        job_name=f"tax-invoice-ocr-{doctype}-{doc.name}",
        timeout=300,
        now=getattr(frappe.flags, "in_test", False),
        is_async=not getattr(frappe.flags, "in_test", False),
        **{"name": doc.name, "target_doctype": doctype, "provider": provider},
    )


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
    settings = get_settings()
    if not cint(settings.get("enable_tax_invoice_ocr", 0)):
        _raise_validation_error(_("Tax Invoice OCR is disabled. Enable it in Tax Invoice OCR Settings."))

    provider_ready, provider_error = _get_provider_status(settings)
    if not provider_ready:
        _raise_validation_error(provider_error)

    doc = frappe.get_doc(doctype, docname)
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
    job_name = f"tax-invoice-ocr-{source_doctype}-{source_doc.name}"
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
