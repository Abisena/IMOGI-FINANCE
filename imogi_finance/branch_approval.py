"""Branch Expense approval helpers for IMOGI Finance."""

from __future__ import annotations

from collections.abc import Iterable

import frappe
from frappe import _
from frappe.utils import flt


def _normalize_accounts(accounts: str | Iterable[str]) -> tuple[str, ...]:
    """Normalize accounts to tuple."""
    if isinstance(accounts, str):
        return (accounts,)

    if isinstance(accounts, Iterable):
        normalized = tuple(sorted({account for account in accounts if account}))
        if normalized:
            return normalized

    return ()


def get_active_setting_meta_for_branch(branch: str) -> dict | None:
    """Return active branch approval setting metadata, or None if not found."""
    if not branch:
        return None
        
    setting = frappe.db.get_value(
        "Branch Expense Approval Setting",
        {"branch": branch, "is_active": 1},
        ["name", "modified"],
        as_dict=True,
    )
    
    if not setting:
        return None

    if isinstance(setting, str):
        return {"name": setting, "modified": None}

    return setting


def _empty_route() -> dict:
    """Return empty route for auto-approve scenarios."""
    return {
        "level_1": {"user": None, "role": None},
        "level_2": {"user": None, "role": None},
        "level_3": {"user": None, "role": None},
    }


def _get_route_for_account(setting_name: str, account: str, amount: float) -> dict | None:
    """Get approval route for a specific account.
    
    Matches by expense_account first, falls back to is_default.
    Then filters levels by amount range.
    """
    # Try to find specific account line
    approval_line = frappe.get_all(
        "Branch Expense Approval Line",
        filters={
            "parent": setting_name,
            "expense_account": account,
        },
        fields=[
            "level_1_user", "level_1_role", "level_1_min_amount", "level_1_max_amount",
            "level_2_user", "level_2_role", "level_2_min_amount", "level_2_max_amount",
            "level_3_user", "level_3_role", "level_3_min_amount", "level_3_max_amount",
        ],
        limit=1,
    )

    # Fall back to default line
    if not approval_line:
        approval_line = frappe.get_all(
            "Branch Expense Approval Line",
            filters={
                "parent": setting_name,
                "is_default": 1,
            },
            fields=[
                "level_1_user", "level_1_role", "level_1_min_amount", "level_1_max_amount",
                "level_2_user", "level_2_role", "level_2_min_amount", "level_2_max_amount",
                "level_3_user", "level_3_role", "level_3_min_amount", "level_3_max_amount",
            ],
            limit=1,
        )

    if not approval_line:
        return None

    data = approval_line[0]
    route = {
        "level_1": {"user": None, "role": None},
        "level_2": {"user": None, "role": None},
        "level_3": {"user": None, "role": None},
    }

    # Filter each level by amount range
    for level in (1, 2, 3):
        user = data.get(f"level_{level}_user")
        role = data.get(f"level_{level}_role")
        min_amount = data.get(f"level_{level}_min_amount")
        max_amount = data.get(f"level_{level}_max_amount")

        # Skip if no approver configured for this level
        if not user:
            continue

        # Skip if amount range not configured
        if min_amount is None or max_amount is None:
            continue

        min_amount = flt(min_amount)
        max_amount = flt(max_amount)

        # Check if amount falls within this level's range
        if min_amount <= amount <= max_amount:
            route[f"level_{level}"] = {"user": user, "role": role}

    return route


def get_branch_approval_route(
    branch: str, accounts: str | Iterable[str], amount: float, *, setting_meta: dict | None = None
) -> dict:
    """Return approval route based on branch, account(s) and amount.
    
    Returns empty route (for auto-approve) if no setting exists or no matching rules.
    """
    amount = flt(amount or 0)
    
    # Normalize accounts
    try:
        normalized_accounts = _normalize_accounts(accounts)
    except Exception:
        normalized_accounts = ()
    
    if not normalized_accounts:
        return _empty_route()
    
    # Get setting
    try:
        route_setting = setting_meta if setting_meta is not None else get_active_setting_meta_for_branch(branch)
    except Exception:
        route_setting = None
        
    if not route_setting:
        return _empty_route()
    
    setting_name = route_setting.get("name") if isinstance(route_setting, dict) else None
    if not setting_name:
        return _empty_route()
    
    resolved_route = None

    for account in normalized_accounts:
        route = _get_route_for_account(setting_name, account, amount)
        
        if route is None:
            continue

        if resolved_route is None:
            resolved_route = route
            continue

        # Check route consistency across accounts
        if resolved_route != route:
            raise frappe.ValidationError(
                _("All expense accounts on the request must share the same approval route.")
            )

    if not resolved_route:
        return _empty_route()

    return resolved_route


def branch_approval_setting_required_message(branch: str | None = None) -> str:
    """Return user-friendly message when approval setting is missing."""
    if branch:
        return _(
            "Approval route could not be determined. Please configure a Branch Expense Approval Setting for Branch {0}."
        ).format(branch)

    return _("Approval route could not be determined. Please configure a Branch Expense Approval Setting.")


def log_branch_route_resolution_error(exc: Exception, *, branch: str | None = None, accounts=None, amount=None):
    """Log approval route resolution errors."""
    logger = getattr(frappe, "log_error", None)
    if logger:
        try:
            logger(
                title=_("Branch Expense Request Approval Route Resolution Failed"),
                message={
                    "branch": branch,
                    "accounts": accounts,
                    "amount": amount,
                    "error": str(exc),
                },
            )
        except Exception:
            pass


def validate_route_users(route: dict) -> dict:
    """Validate users in approval route exist and are enabled."""
    invalid_users = []
    disabled_users = []

    for level in (1, 2, 3):
        level_data = route.get(f"level_{level}", {})
        user = level_data.get("user")

        if not user:
            continue

        user_doc = frappe.db.get_value("User", user, ["enabled"], as_dict=True)

        if not user_doc:
            invalid_users.append({"level": level, "user": user})
            continue

        if not user_doc.get("enabled"):
            disabled_users.append({"level": level, "user": user})

    return {
        "valid": not (invalid_users or disabled_users),
        "invalid_users": invalid_users,
        "disabled_users": disabled_users,
    }


def has_approver_in_route(route: dict | None) -> bool:
    """Check if route has at least one approver.
    
    Shared helper to avoid duplication across doctypes and services.
    """
    if not route:
        return False
    return any(route.get(f"level_{level}", {}).get("user") for level in (1, 2, 3))


def parse_route_snapshot(snapshot: str | dict | None) -> dict:
    """Parse approval route snapshot from string or dict.
    
    Shared helper to avoid duplication across doctypes and services.
    Returns dict with level_1/2/3 structure.
    """
    if isinstance(snapshot, dict):
        return snapshot
    
    if isinstance(snapshot, str):
        try:
            import json
            parsed = json.loads(snapshot)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    
    return {}


@frappe.whitelist()
def check_branch_expense_request_route(
    branch: str,
    items=None,
    expense_accounts=None,
    amount: float | None = None,
    docstatus: int | None = None,
):
    """API to check approval route for branch expense request."""
    import json as json_lib

    # Parse items if string
    if items and isinstance(items, str):
        try:
            items = json_lib.loads(items)
        except Exception:
            items = None

    # Parse accounts
    if expense_accounts and isinstance(expense_accounts, str):
        try:
            parsed_accounts = json_lib.loads(expense_accounts)
        except Exception:
            parsed_accounts = [expense_accounts]
    elif isinstance(expense_accounts, list):
        parsed_accounts = expense_accounts
    else:
        parsed_accounts = []

    # Calculate amount from items if not provided
    if amount is None and items:
        target_amount = sum(flt(item.get("amount", 0)) for item in items)
    else:
        target_amount = flt(amount or 0)

    route = get_branch_approval_route(branch, parsed_accounts or [], target_amount or 0)
    
    # Validate users in route
    user_validation = validate_route_users(route)
    if not user_validation["valid"]:
        error_parts = []

        if user_validation["invalid_users"]:
            user_list = ", ".join(
                _("Level {level}: {user}").format(level=u["level"], user=u["user"])
                for u in user_validation["invalid_users"]
            )
            error_parts.append(_("Users not found: {0}").format(user_list))

        if user_validation["disabled_users"]:
            user_list = ", ".join(
                _("Level {level}: {user}").format(level=u["level"], user=u["user"])
                for u in user_validation["disabled_users"]
            )
            error_parts.append(_("Users disabled: {0}").format(user_list))

        return {
            "ok": False,
            "route": route,
            "message": _("{errors}. Please update the Branch Expense Approval Setting.").format(
                errors=_("; ").join(error_parts)
            ),
            "user_validation": user_validation,
        }

    # Check if route has any approvers
    if not has_approver_in_route(route):
        return {
            "ok": True,
            "route": route,
            "message": _("No approval required. Request will be auto-approved."),
            "auto_approve": True,
        }

    return {"ok": True, "route": route, "auto_approve": False}
