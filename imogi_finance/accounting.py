"""Accounting helpers for IMOGI Finance."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_months, cint, flt

from imogi_finance.branching import apply_branch, resolve_branch
from imogi_finance.tax_invoice_ocr import get_settings, sync_tax_invoice_upload

PURCHASE_INVOICE_REQUEST_TYPES = {"Expense"}
PURCHASE_INVOICE_ALLOWED_STATUSES = frozenset({"Approved"})


def _raise_verification_error(message: str):
    marker = getattr(frappe, "ThrowMarker", None)
    throw_fn = getattr(frappe, "throw", None)

    if callable(throw_fn):
        try:
            throw_fn(message, title=_("Verification Required"))
            return
        except Exception as exc:
            if marker and not isinstance(exc, marker) and exc.__class__.__name__ != "ThrowCalled":
                raise marker(message)
            raise

    if marker:
        raise marker(message)
    raise Exception(message)


def _get_item_value(item: object, field: str):
    if isinstance(item, dict):
        return item.get(field)
    return getattr(item, field, None)


def summarize_request_items(
    items: list[frappe.model.document.Document] | None,
    *,
    skip_invalid_items: bool = False,
) -> tuple[float, tuple[str, ...]]:
    if not items:
        if skip_invalid_items:
            return 0.0, ()
        frappe.throw(_("Please add at least one item."))

    total = 0.0
    accounts = set()

    for item in items:
        amount = _get_item_value(item, "amount")
        if amount is None or amount <= 0:
            if skip_invalid_items:
                continue
            frappe.throw(_("Each item must have an Amount greater than zero."))

        account = _get_item_value(item, "expense_account")
        if not account:
            if skip_invalid_items:
                continue
            frappe.throw(_("Each item must have an Expense Account."))

        accounts.add(account)
        total += float(amount)

    return total, tuple(sorted(accounts))


def _sync_request_amounts(
    request: frappe.model.document.Document, total: float, expense_accounts: tuple[str, ...]
) -> None:
    updates = {}
    primary_account = expense_accounts[0] if len(expense_accounts) == 1 else None

    if getattr(request, "amount", None) != total:
        updates["amount"] = total

    if getattr(request, "expense_account", None) != primary_account:
        updates["expense_account"] = primary_account

    if updates and hasattr(request, "db_set"):
        request.db_set(updates)

    for field, value in updates.items():
        setattr(request, field, value)
    setattr(request, "expense_accounts", expense_accounts)


def _get_pph_base_amount(request: frappe.model.document.Document) -> float:
    items = getattr(request, "items", []) or []
    item_bases = [
        getattr(item, "pph_base_amount", None)
        for item in items
        if getattr(item, "is_pph_applicable", 0) and getattr(item, "pph_base_amount", None)
    ]

    if item_bases:
        return float(sum(item_bases))

    if getattr(request, "is_pph_applicable", 0) and getattr(request, "pph_base_amount", None):
        return request.pph_base_amount
    return request.amount


def _validate_request_ready_for_link(request: frappe.model.document.Document) -> None:
    status = None
    if hasattr(request, "get"):
        status = request.get("status") or request.get("workflow_state")
    if request.docstatus != 1 or status not in PURCHASE_INVOICE_ALLOWED_STATUSES:
        frappe.throw(
            _("Expense Request must be submitted and have status {0} before creating accounting entries.").format(
                ", ".join(sorted(PURCHASE_INVOICE_ALLOWED_STATUSES))
            )
        )


def _validate_request_type(
    request: frappe.model.document.Document, allowed_types: set[str], action: str
) -> None:
    if request.request_type not in allowed_types:
        frappe.throw(
            _("{0} can only be created for request type(s): {1}").format(
                action, ", ".join(sorted(allowed_types))
            )
        )


def _validate_no_existing_purchase_invoice(request: frappe.model.document.Document) -> None:
    # Query untuk cek apakah sudah ada PI yang submitted untuk ER ini
    existing_pi = frappe.db.get_value(
        "Purchase Invoice",
        {
            "imogi_expense_request": request.name,
            "docstatus": ["!=", 2]  # Not cancelled
        },
        "name"
    )
    
    if existing_pi:
        frappe.throw(
            _("Expense Request is already linked to Purchase Invoice {0}.").format(
                existing_pi
            )
        )


def _update_request_purchase_invoice_links(
    request: frappe.model.document.Document,
    purchase_invoice: frappe.model.document.Document,
    mark_pending: bool = True,
) -> None:
    """Legacy function - kept for backward compatibility.
    
    With native connections, PI link is established via imogi_expense_request field
    on Purchase Invoice. Status is determined by querying submitted documents.
    
    This function now only clears pending_purchase_invoice field.
    """
    # Clear pending field only - actual link is via PI.imogi_expense_request
    if hasattr(request, "db_set"):
        request.db_set("pending_purchase_invoice", None)
    else:
        setattr(request, "pending_purchase_invoice", None)


@frappe.whitelist()
def create_purchase_invoice_from_request(expense_request_name: str) -> str:
    """Create a Purchase Invoice from an Expense Request and return its name."""
    request = frappe.get_doc("Expense Request", expense_request_name)
    _validate_request_ready_for_link(request)
    _validate_request_type(request, PURCHASE_INVOICE_REQUEST_TYPES, _("Purchase Invoice"))
    _validate_no_existing_purchase_invoice(request)

    company = frappe.db.get_value("Cost Center", request.cost_center, "company")
    if not company:
        frappe.throw(_("Unable to resolve company from the selected Cost Center."))

    branch = resolve_branch(
        company=company, cost_center=request.cost_center, explicit_branch=getattr(request, "branch", None)
    )

    request_items = getattr(request, "items", []) or []
    
    if not request_items:
        frappe.throw(_("Expense Request must have at least one item to create a Purchase Invoice."))

    total_amount, expense_accounts = summarize_request_items(request_items, skip_invalid_items=True)
    _sync_request_amounts(request, total_amount, expense_accounts)

    settings = get_settings()
    sync_tax_invoice_upload(request, "Expense Request", save=False)
    enforce_mode = (settings.get("enforce_mode") or "").lower()
    if settings.get("enable_budget_lock") and enforce_mode in {"approval only", "both"}:
        lock_status = getattr(request, "budget_lock_status", None)
        if lock_status not in {"Locked", "Overrun Allowed"}:
            frappe.throw(
                _("Expense Request must be budget locked before creating a Purchase Invoice. Current status: {0}").format(
                    lock_status or _("Not Locked")
                )
            )

        if getattr(request, "allocation_mode", "Direct") == "Allocated via Internal Charge":
            ic_name = getattr(request, "internal_charge_request", None)
            if not ic_name:
                frappe.throw(_("Internal Charge Request is required before creating a Purchase Invoice."))

            ic_status = frappe.db.get_value("Internal Charge Request", ic_name, "status")
            if ic_status != "Approved":
                frappe.throw(_("Internal Charge Request {0} must be Approved.").format(ic_name))

    require_verified = (
        cint(settings.get("enable_tax_invoice_ocr"))
        and cint(settings.get("require_verification_before_create_pi_from_expense_request"))
        and bool(getattr(request, "is_ppn_applicable", 0))
    )

    if require_verified:
        upload_name = getattr(request, "ti_tax_invoice_upload", None)

        # Source of truth: if upload linked, check upload; else check ER field
        if upload_name:
            upload_status = frappe.db.get_value(
                "Tax Invoice OCR Upload", upload_name, "verification_status"
            )
            if upload_status != "Verified":
                status_msg = f". Current upload status: {upload_status}" if upload_status else ""
                _raise_verification_error(
                    _(
                        "Tax Invoice OCR Upload {0} must be Verified before creating a Purchase Invoice from this request{1}"
                    ).format(upload_name, status_msg)
                )
        else:
            # No upload linked, check ER field
            er_status = getattr(request, "ti_verification_status", "") or ""
            if er_status != "Verified":
                _raise_verification_error(
                    _("Tax Invoice must be verified before creating a Purchase Invoice from this request.")
                )

    pph_items = [item for item in request_items if getattr(item, "is_pph_applicable", 0)]
    has_item_level_pph = bool(pph_items)
    
    # Count items with Apply WHT to detect MIXED scenario
    items_with_pph = len(pph_items)
    total_items = len(request_items)
    has_mixed_pph = 0 < items_with_pph < total_items  # Some but not all items have Apply WHT
    
    is_ppn_applicable = bool(getattr(request, "is_ppn_applicable", 0))
    # CRITICAL: apply_pph is determined by item-level flags (whether any item has Apply WHT)
    # Header Apply WHT checkbox is only for determining which category to use
    apply_ppn = is_ppn_applicable
    apply_pph = items_with_pph > 0  # Apply PPh if ANY item has Apply WHT checked
    
    # Header checkbox indicates whether to use ER's category or supplier's category
    header_apply_wht = bool(getattr(request, "is_pph_applicable", 0))
    
    # ============================================================================
    # VALIDATION: If items have Apply WHT, Header must provide PPh category
    # ============================================================================
    # RULE: If any item has Apply WHT checked, Header must have PPh Type specified
    if apply_pph:  # apply_pph = True if any item has Apply WHT
        pph_type = getattr(request, "pph_type", None)
        if not pph_type:
            frappe.throw(
                _("Found {0} item(s) with 'Apply WHT' checked but PPh Type is NOT specified in Tab Tax. "
                  "Please select PPh Type in Tab Tax.").format(items_with_pph)
            )
    
    # CRITICAL: If mixed Apply WHT (some items have, some don't)
    # Then don't use supplier's category at all (it would apply to all items)
    # No need to log this - it's a valid configuration
    has_mixed_pph = has_mixed_pph  # Keep variable for later use

    # Validate PPN template exists when PPN applicable
    if apply_ppn:
        ppn_template = getattr(request, "ppn_template", None)
        if not ppn_template:
            frappe.throw(
                _("PPN Template is required in Expense Request {0} before creating Purchase Invoice").format(request.name)
            )
        
        # Validate template exists in system
        template_exists = frappe.db.exists("Sales Taxes and Charges Template", ppn_template)
        if not template_exists:
            frappe.throw(
                _("PPN Template '{0}' does not exist in system").format(ppn_template)
            )

    # Validate PPh category exists in system when PPh applicable
    if apply_pph:
        pph_type = getattr(request, "pph_type", None)
        # Validate category exists in system
        category_exists = frappe.db.exists("Tax Withholding Category", pph_type)
        if not category_exists:
            frappe.throw(
                _("Tax Withholding Category '{0}' does not exist in system").format(pph_type)
            )

    pi = frappe.new_doc("Purchase Invoice")
    pi.company = company
    
    # IMPORTANT: Set apply_tds = 0 BEFORE assigning supplier
    # This prevents Frappe's TDS controller from auto-calculating supplier's WHT
    # We will set it to 1 later if ER's Apply WHT is checked
    pi.apply_tds = 0
    
    pi.supplier = request.supplier
    # NOTE: After setting supplier, Frappe auto-populates tax_withholding_category
    # BUT since apply_tds=0, Frappe's TDS won't calculate it yet
    # We will override this with ON/OFF logic below
    pi.posting_date = request.request_date
    pi.bill_date = request.supplier_invoice_date
    pi.bill_no = request.supplier_invoice_no
    pi.currency = request.currency
    if hasattr(pi, "tax_category"):
        pi.tax_category = getattr(request, "tax_category", None)
    pi.imogi_expense_request = request.name
    pi.internal_charge_request = getattr(request, "internal_charge_request", None)
    pi.imogi_request_type = request.request_type
    
    # ============================================================================
    # ON/OFF LOGIC FOR PPh (Withholding Tax)
    # CRITICAL: Control which PPh source to use (ER vs Supplier)
    # ============================================================================
    # RULE:
    # - Jika SEMUA items Apply WHT ✅ CENTANG → AKTIFKAN ER's pph_type
    # - Jika ADA items dengan Apply WHT PARTIAL (mixed) → NO supplier category (items control)
    # - Jika TIDAK ADA items Apply WHT ❌ → GUNAKAN supplier's category (jika enabled)
    # - TIDAK BOLEH supplier category dipakai saat ada item-level Apply WHT
    # ============================================================================
    
    if apply_pph:
        # ✅ Some items have Apply WHT checked → Enable PPh calculation
        # Use ER's pph_type from Tab Tax
        # CRITICAL: Check if supplier has conflicting category
        supplier_category = pi.tax_withholding_category  # Auto-populated by Frappe after setting supplier
        
        if supplier_category and supplier_category != request.pph_type:
            # ⚠️ CONFLICT: Supplier's category berbeda dengan ER's PPh Type
            frappe.msgprint(
                msg=_(
                    "<b>Supplier WHT Category Conflict Detected</b><br><br>"
                    "Supplier <b>{0}</b> has Tax Withholding Category: <b>{1}</b><br>"
                    "But Expense Request specifies PPh Type: <b>{2}</b><br><br>"
                    "The system will use <b>{2}</b> (from Expense Request) and override supplier's category.<br>"
                    "If you want to use supplier's category instead, please update PPh Type in Expense Request Tab Tax."
                ).format(request.supplier, supplier_category, request.pph_type),
                title=_("WHT Category Conflict"),
                indicator="orange"
            )
        
        # Override supplier's category with ER's pph_type
        pi.tax_withholding_category = request.pph_type
        pi.imogi_pph_type = request.pph_type
        pi.apply_tds = 1  # Enable TDS for items with Apply WHT
    else:
        # ❌ ER does NOT have Apply WHT set (no items with Apply WHT)
        # Action: MATIKAN ER's pph_type, GUNAKAN supplier's category (jika ada & enabled)
        
        settings = get_settings() if callable(get_settings) else {}
        use_supplier_wht = cint(settings.get("use_supplier_wht_if_no_er_pph", 0))
        
        if use_supplier_wht:
            # Setting enabled: Auto-copy supplier's tax withholding category
            supplier_wht = frappe.db.get_value("Supplier", request.supplier, "tax_withholding_category")
            if supplier_wht:
                pi.tax_withholding_category = supplier_wht
                pi.imogi_pph_type = supplier_wht
                pi.apply_tds = 1
            else:
                pi.tax_withholding_category = None
                pi.imogi_pph_type = None
                pi.apply_tds = 0
        else:
            # Setting disabled: Don't use supplier's category
            pi.tax_withholding_category = None
            pi.imogi_pph_type = None
            pi.apply_tds = 0
    # withholding_tax_base_amount will be set after all items are added

    # Collect per-item PPh details during item creation
    temp_pph_items = []

    for idx, item in enumerate(request_items, start=1):
        expense_account = getattr(item, "expense_account", None)
        is_deferred = bool(getattr(item, "is_deferred_expense", 0))
        prepaid_account = getattr(item, "prepaid_account", None)
        deferred_start_date = getattr(item, "deferred_start_date", None)
        deferred_periods = getattr(item, "deferred_periods", None)
        
        qty = getattr(item, "qty", 1) or 1
        item_amount = flt(getattr(item, "amount", 0))
        
        pi_item = {
            "item_name": getattr(item, "asset_name", None)
            or getattr(item, "description", None)
            or getattr(item, "expense_account", None),
            "description": getattr(item, "asset_description", None)
            or getattr(item, "description", None),
            "expense_account": prepaid_account if is_deferred else expense_account,
            "cost_center": request.cost_center,
            "project": request.project,
            "qty": qty,
            "rate": item_amount / qty if qty > 0 else item_amount,
            "amount": item_amount,
        }

        if is_deferred:
            pi_item["enable_deferred_expense"] = 1
            pi_item["service_start_date"] = deferred_start_date
            pi_item["service_end_date"] = add_months(deferred_start_date, deferred_periods or 0)
            pi_item["deferred_expense_account"] = expense_account
        
        pi_item_doc = pi.append("items", pi_item)
        # Set item-level apply_tds flag if PPh applies
        if apply_pph and hasattr(pi_item_doc, "apply_tds"):
            # CRITICAL: Only items with is_pph_applicable = 1 get taxed
            if getattr(item, "is_pph_applicable", 0):
                pi_item_doc.apply_tds = 1

        # Track which items have PPh for later index mapping
        if apply_pph and getattr(item, "is_pph_applicable", 0):
            base_amount = getattr(item, "pph_base_amount", None)
            if base_amount is not None:
                temp_pph_items.append({
                    "er_index": idx,
                    "base_amount": float(base_amount)
                })

    # Add DPP variance as additional line item at the end (NOT subject to withholding tax)
    dpp_variance = flt(getattr(request, "ti_dpp_variance", 0) or 0)
    if dpp_variance != 0:
        variance_account = settings.get("dpp_variance_account")
        
        if variance_account:
            variance_item = {
                "item_name": "DPP Variance Adjustment" if dpp_variance > 0 else "DPP Variance Reduction",
                "description": f"Tax invoice variance adjustment (OCR vs Expected): {flt(dpp_variance):,.2f}",
                "expense_account": variance_account,
                "cost_center": request.cost_center,
                "project": request.project,
                "qty": 1,
                "rate": dpp_variance,  # Can be positive or negative
                "amount": dpp_variance,
            }
            pi.append("items", variance_item)

    # Build item_wise_tax_detail with correct indices AFTER all items are added
    # This ensures index mapping is accurate regardless of variance items
    item_wise_pph_detail = {}
    if temp_pph_items:
        for pph_item in temp_pph_items:
            # Use ER index directly since items are added in order
            pi_idx = pph_item["er_index"]
            item_wise_pph_detail[str(pi_idx)] = pph_item["base_amount"]

    # Calculate withholding tax base amount
    # IMPORTANT: Exclude variance item from PPh calculation
    if apply_pph:
        if item_wise_pph_detail:
            # If per-item PPh, sum from item_wise_pph_detail
            pi.withholding_tax_base_amount = sum(float(v) for v in item_wise_pph_detail.values())
        else:
            # If header-level PPh, use total of expense items only (exclude variance)
            # Variance item is always last if it exists
            items_count = len(request_items)  # Original items without variance
            pi.withholding_tax_base_amount = sum(
                flt(pi.items[i].get("amount", 0)) for i in range(items_count)
            )

    # Set PPh details after all items are added
    if item_wise_pph_detail:
        pi.item_wise_tax_detail = item_wise_pph_detail

    # map tax invoice metadata
    pi.ti_tax_invoice_pdf = getattr(request, "ti_tax_invoice_pdf", None)
    pi.ti_tax_invoice_upload = getattr(request, "ti_tax_invoice_upload", None)
    pi.ti_fp_no = getattr(request, "ti_fp_no", None)
    pi.ti_fp_date = getattr(request, "ti_fp_date", None)
    pi.ti_fp_npwp = getattr(request, "ti_fp_npwp", None)
    pi.ti_fp_dpp = getattr(request, "ti_fp_dpp", None)
    pi.ti_fp_ppn = getattr(request, "ti_fp_ppn", None)
    pi.ti_fp_ppn_type = getattr(request, "ti_fp_ppn_type", None)
    pi.ti_verification_status = getattr(request, "ti_verification_status", None)
    pi.ti_verification_notes = getattr(request, "ti_verification_notes", None)
    pi.ti_duplicate_flag = getattr(request, "ti_duplicate_flag", None)
    pi.ti_npwp_match = getattr(request, "ti_npwp_match", None)
    # Copy variance fields for reference and audit trail
    pi.ti_dpp_variance = getattr(request, "ti_dpp_variance", None)
    pi.ti_ppn_variance = getattr(request, "ti_ppn_variance", None)
    apply_branch(pi, branch)

    pi.insert(ignore_permissions=True)
    
    # Set PPN template AFTER insert so ERPNext can properly populate the taxes table
    if apply_ppn and request.ppn_template:
        pi.taxes_and_charges = request.ppn_template
        pi.set_taxes()
        pi.save(ignore_permissions=True)

    # Ensure withholding tax (PPh) rows are generated for net total calculation
    if apply_pph:
        set_tax_withholding = getattr(pi, "set_tax_withholding", None)
        if callable(set_tax_withholding):
            set_tax_withholding()
            pi.save(ignore_permissions=True)
    
    # Recalculate taxes and totals after insert to ensure PPN and PPh are properly calculated
    # This is critical because:
    # 1. Withholding tax (PPh) is calculated by Frappe's TDS controller after save
    # 2. PPN needs to be recalculated from the final item total (including variance)
    # 3. ERPNext's tax calculation requires the document to exist in DB first
    pi.reload()  # Refresh from DB to get any auto-calculated fields
    
    # Now recalculate with all items and settings in place
    if hasattr(pi, "calculate_taxes_and_totals"):
        try:
            pi.calculate_taxes_and_totals()
            for fieldname in (
                "taxes_and_charges_added",
                "taxes_and_charges_deducted",
                "total_taxes_and_charges",
            ):
                if getattr(pi, fieldname, None) is None:
                    setattr(pi, fieldname, 0)
            pi.save(ignore_permissions=True)
        except Exception as e:
            frappe.logger().error(f"Tax calculation failed for PI {pi.name}: {str(e)}")
            frappe.msgprint(
                _("Tax calculation encountered an error. Please review the Purchase Invoice {0} manually.").format(pi.name),
                indicator="red",
                alert=True
            )
    
    # Reload again to get final calculated values
    pi.reload()

    # Validate taxes were actually calculated
    # NOTE: Skip validation for MIXED mode since taxes are calculated per-item, not at PI level
    if apply_ppn and flt(pi.taxes_and_charges_added) == 0:
        frappe.msgprint(
            _("Warning: PPN was not calculated. Please check PPN Template '{0}' configuration.").format(
                getattr(request, "ppn_template", "")
            ),
            indicator="orange",
            alert=True
        )

    # CRITICAL: Don't warn if MIXED Apply WHT mode (taxes calculated per-item)
    if apply_pph and not has_mixed_pph and flt(pi.taxes_and_charges_deducted) == 0:
        frappe.msgprint(
            _("Warning: PPH was not calculated. Please check Tax Withholding Category '{0}' configuration.").format(
                getattr(request, "pph_type", "")
            ),
            indicator="orange", 
            alert=True
        )

    _update_request_purchase_invoice_links(request, pi)

    if getattr(pi, "docstatus", 0) == 0:
        notifier = getattr(frappe, "msgprint", None)
        if notifier:
            notifier(
                _(
                    "Purchase Invoice {0} was created in Draft. Please submit it before continuing to Payment Entry."
                ).format(pi.name),
                alert=True,
            )

    return pi.name