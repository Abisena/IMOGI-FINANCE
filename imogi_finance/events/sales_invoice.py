from __future__ import annotations

from frappe.utils import flt

PPN_RATE = 11.0


def _round_amount(doc, fieldname: str, value: float) -> float:
    if hasattr(doc, "precision"):
        return flt(value, doc.precision(fieldname))
    return flt(value)


def _calculate_dpp_ppn(amount: float, rate: float = PPN_RATE) -> tuple[float, float]:
    if amount <= 0:
        return 0.0, 0.0
    divisor = 1 + (rate / 100)
    dpp = amount / divisor
    ppn = amount - dpp
    return dpp, ppn


def apply_dpp_ppn_to_sales_invoice(doc, method=None) -> None:
    """Compute DPP and PPN 11% from gross item amounts for Sales Invoice."""
    if not getattr(doc, "items", None):
        return

    total_dpp = 0.0
    total_ppn = 0.0

    for item in doc.items:
        amount = flt(getattr(item, "amount", 0)) or flt(getattr(item, "rate", 0)) * flt(
            getattr(item, "qty", 0)
        )
        dpp, ppn = _calculate_dpp_ppn(amount)
        dpp = _round_amount(item, "dpp_amount", dpp)
        ppn = _round_amount(item, "ppn_amount", ppn)

        if hasattr(item, "dpp_amount"):
            item.dpp_amount = dpp
        if hasattr(item, "ppn_amount"):
            item.ppn_amount = ppn

        total_dpp += dpp
        total_ppn += ppn

    if hasattr(doc, "out_fp_dpp"):
        doc.out_fp_dpp = _round_amount(doc, "out_fp_dpp", total_dpp)
    if hasattr(doc, "out_fp_ppn"):
        doc.out_fp_ppn = _round_amount(doc, "out_fp_ppn", total_ppn)
