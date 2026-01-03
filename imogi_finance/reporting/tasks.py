from __future__ import annotations

from datetime import date

from imogi_finance.reporting import build_dashboard_snapshot, resolve_signers
from imogi_finance.reporting.data import load_daily_inputs
from imogi_finance.reporting.service import build_monthly_reconciliation

try:
    import frappe  # type: ignore
except Exception:  # pragma: no cover - fallback for tests
    frappe = None


def _get_signers():
    if not frappe:
        return resolve_signers()

    try:
        settings = frappe.get_cached_doc("Finance Control Settings")
    except Exception:
        return resolve_signers()

    return resolve_signers(
        {
            "prepared_by": getattr(settings, "daily_report_preparer", None),
            "approved_by": getattr(settings, "daily_report_approver", None),
            "acknowledged_by": getattr(settings, "daily_report_acknowledger", None),
        }
    )


def run_daily_reporting(branches=None, report_date=None):
    report_date_obj = report_date or date.today()
    transactions, opening_balances = load_daily_inputs(report_date_obj, branches)
    signers = _get_signers()

    snapshot = build_dashboard_snapshot(
        transactions=transactions,
        opening_balances=opening_balances,
        report_date=report_date_obj,
        allowed_branches=branches,
        reconciliation=None,
        signers=signers,
    )

    if frappe:
        try:
            frappe.cache().hset(
                "imogi_finance_reporting_snapshots", report_date_obj.isoformat(), snapshot
            )
        except Exception:
            frappe.log_error("Failed to cache daily report snapshot", "IMOGI Finance Reporting")
    return snapshot


def run_monthly_reconciliation(month=None, ledger_transactions=None, bank_statements=None):
    month_value = month or date.today().strftime("%Y-%m")
    reconciliation = build_monthly_reconciliation(
        ledger_transactions=ledger_transactions or [],
        bank_statements=bank_statements or [],
        month=month_value,
        tolerance=0.0,
        auto_close=True,
    )
    if frappe:
        try:
            frappe.cache().hset(
                "imogi_finance_monthly_reconciliation", month_value, reconciliation.to_dict()
            )
        except Exception:
            frappe.log_error("Failed to cache monthly reconciliation", "IMOGI Finance Reporting")
    return reconciliation.to_dict()
