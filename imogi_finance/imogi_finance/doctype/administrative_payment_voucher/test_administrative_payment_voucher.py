import sys
import types

import pytest


frappe = sys.modules.setdefault("frappe", types.ModuleType("frappe"))
if not hasattr(frappe, "_"):
    frappe._ = lambda msg: msg
if not hasattr(frappe, "_dict"):
    frappe._dict = lambda *args, **kwargs: types.SimpleNamespace(**kwargs)
if not hasattr(frappe, "msgprint"):
    frappe.msgprint = lambda *args, **kwargs: None
if not hasattr(frappe, "bold"):
    frappe.bold = lambda msg: msg
if not hasattr(frappe, "whitelist"):
    frappe.whitelist = lambda *args, **kwargs: (lambda fn: fn)

frappe_db = getattr(frappe, "db", types.SimpleNamespace())
if not hasattr(frappe_db, "has_column"):
    frappe_db.has_column = lambda *args, **kwargs: False
if not hasattr(frappe_db, "get_value"):
    frappe_db.get_value = lambda *args, **kwargs: None
frappe.db = frappe_db

if not hasattr(frappe, "get_all"):
    frappe.get_all = lambda *args, **kwargs: []

if not hasattr(frappe, "throw"):
    class ThrowMarker(Exception):
        pass

    def _throw(msg=None, title=None):
        raise ThrowMarker(msg or title)

    frappe.ThrowMarker = ThrowMarker
    frappe.throw = _throw

model = sys.modules.setdefault("frappe.model", types.ModuleType("frappe.model"))
document = types.ModuleType("frappe.model.document")


class DummyDocument:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def append(self, fieldname, values):
        rows = getattr(self, fieldname, [])
        rows.append(values)
        setattr(self, fieldname, rows)

    def get(self, key, default=None):
        return getattr(self, key, default)

    def db_set(self, *args, **kwargs):
        pass


document.Document = DummyDocument
model.document = document
sys.modules["frappe.model.document"] = document

utils = sys.modules.setdefault("frappe.utils", types.ModuleType("frappe.utils"))
if not hasattr(utils, "now_datetime"):
    import datetime

    utils.now_datetime = lambda: datetime.datetime.now()
if not hasattr(utils, "flt"):
    utils.flt = lambda value, *args, **kwargs: float(value or 0)
if not hasattr(utils, "get_first_day"):
    utils.get_first_day = lambda date_str=None: None
if not hasattr(utils, "get_last_day"):
    utils.get_last_day = lambda date_obj=None: None
if not hasattr(utils, "nowdate"):
    utils.nowdate = lambda: ""

sys.modules["frappe.utils"] = utils

xlsxutils = types.ModuleType("frappe.utils.xlsxutils")
xlsxutils.make_xlsx = lambda *args, **kwargs: types.SimpleNamespace(getvalue=lambda: b"")
sys.modules["frappe.utils.xlsxutils"] = xlsxutils

from imogi_finance.imogi_finance.doctype.administrative_payment_voucher import (  # noqa: E402
    administrative_payment_voucher as apv,
)


def test_payment_entry_mapping_receive_direction():
    mapping = apv.map_payment_entry_accounts("Receive", 1500, "ACC-BANK", "ACC-INCOME")
    assert mapping.payment_type == "Receive"
    assert mapping.paid_to == "ACC-BANK"
    assert mapping.paid_from == "ACC-INCOME"
    assert mapping.paid_amount == 1500
    assert mapping.received_amount == 1500


def test_target_account_rejects_bank_or_cash():
    details = apv.AccountDetails("ACC-BANK", "Bank", "Asset", 0, "Company A")
    with pytest.raises(Exception):
        apv.validate_target_account(details, "Company A")


def test_party_required_for_receivable_accounts(monkeypatch):
    details = apv.AccountDetails("ACC-REC", "Receivable", "Asset", 0, "Company A")

    class Marker(Exception):
        pass

    monkeypatch.setattr(frappe, "throw", lambda *args, **kwargs: (_ for _ in ()).throw(Marker()))
    with pytest.raises(Marker):
        apv.validate_party(details, None, None)


def test_apply_optional_dimension_respects_missing_column(monkeypatch):
    doc = DummyDocument(doctype="Dummy")
    monkeypatch.setattr(frappe.db, "has_column", lambda doctype, field: False)
    apv.apply_optional_dimension(doc, "branch", "BR-01")
    assert not hasattr(doc, "branch")


def test_apply_optional_dimension_sets_when_present(monkeypatch):
    doc = DummyDocument(doctype="Dummy")
    monkeypatch.setattr(frappe.db, "has_column", lambda doctype, field: True)
    apv.apply_optional_dimension(doc, "branch", "BR-02")
    assert doc.branch == "BR-02"
