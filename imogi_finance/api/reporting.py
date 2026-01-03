from __future__ import annotations

from datetime import date
from importlib import util as importlib_util
import sys
import types

from imogi_finance.reporting import (
    ReportScheduler,
    build_dashboard_snapshot,
    build_daily_report,
    resolve_signers,
)
from imogi_finance.reporting.data import load_daily_inputs


existing = sys.modules.get("frappe")
if existing:
    frappe = existing
elif importlib_util.find_spec("frappe"):
    import frappe  # type: ignore
else:
    frappe = sys.modules.setdefault(
        "frappe",
        types.SimpleNamespace(
            whitelist=lambda *args, **kwargs: (lambda fn: fn),
            _=lambda msg, *args, **kwargs: msg,
            _dict=lambda value=None, **kwargs: {**(value or {}), **kwargs},
            utils=types.SimpleNamespace(nowdate=lambda: date.today().isoformat()),
            session=types.SimpleNamespace(user="system"),
        ),
    )

_ = frappe._


def _get_settings():
    try:
        if hasattr(frappe, "get_cached_doc"):
            return frappe.get_cached_doc("Finance Control Settings")
    except Exception:
        return {}
    return {}


def _extract_signers_from_settings(doc) -> dict:
    if not doc:
        return {}
    return {
        "prepared_by": getattr(doc, "daily_report_preparer", None),
        "approved_by": getattr(doc, "daily_report_approver", None),
        "acknowledged_by": getattr(doc, "daily_report_acknowledger", None),
    }


@frappe.whitelist()
def preview_daily_report(branches=None, report_date=None):
    signers = resolve_signers(_extract_signers_from_settings(_get_settings()))
    report_date_obj = date.fromisoformat(report_date) if report_date else None
    branch_filter = branches or None
    transactions, opening_balances = load_daily_inputs(report_date_obj, branch_filter)
    bundle = build_daily_report(
        transactions,
        opening_balances=opening_balances,
        report_date=report_date_obj,
        signers=signers,
        allowed_branches=branch_filter,
        status="preview",
    )
    return bundle.to_dict()


@frappe.whitelist()
def get_dashboard_snapshot(branches=None, report_date=None):
    signers = resolve_signers(_extract_signers_from_settings(_get_settings()))
    report_date_obj = date.fromisoformat(report_date) if report_date else None
    branch_filter = branches or None
    transactions, opening_balances = load_daily_inputs(report_date_obj, branch_filter)
    snapshot = build_dashboard_snapshot(
        transactions=transactions,
        opening_balances=opening_balances,
        report_date=report_date_obj,
        allowed_branches=branch_filter,
        reconciliation=None,
        signers=signers,
    )
    return snapshot


@frappe.whitelist()
def plan_reporting_jobs(branches=None):
    scheduler = ReportScheduler(activate=False)

    def _daily_job(**kwargs):
        return {"status": "planned", "branches": kwargs.get("branches")}

    def _monthly_job():
        return {"status": "planned"}

    scheduler.schedule_daily_report(_daily_job, branches=branches or None)
    scheduler.schedule_monthly_reconciliation(_monthly_job)

    return frappe._dict(
        {
            "backend": scheduler.backend,
            "jobs": [job.to_dict() for job in scheduler.jobs],
        }
    )
