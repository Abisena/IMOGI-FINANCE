"""
Debug tool to check PI PPh configuration in detail
"""

import frappe
from frappe import _
from frappe.utils import flt
import json


@frappe.whitelist()
def debug_pi_pph(pi_name):
    """
    Deep debugging of PI PPh configuration

    Usage:
    frappe.call({
        method: 'imogi_finance.scripts.debug_pi_pph.debug_pi_pph',
        args: {pi_name: 'ACC-PINV-2026-00025'},
        callback: function(r) { console.log(JSON.stringify(r.message, null, 2)); }
    });
    """
    try:
        pi = frappe.get_doc("Purchase Invoice", pi_name)

        result = {
            "pi_name": pi_name,
            "pi_header": {
                "docstatus": pi.docstatus,
                "apply_tds": getattr(pi, "apply_tds", None),
                "tax_withholding_category": getattr(pi, "tax_withholding_category", None),
                "taxes_and_charges_deducted": getattr(pi, "taxes_and_charges_deducted", 0),
                "total": pi.total,
                "grand_total": pi.grand_total,
            },
            "items": [],
            "taxes": [],
            "er_name": getattr(pi, "imogi_expense_request", None)
        }

        # Check items
        for item in (pi.items or []):
            result["items"].append({
                "idx": item.idx,
                "expense_account": item.expense_account,
                "amount": item.amount,
                "apply_tds": getattr(item, "apply_tds", None)
            })

        # Check taxes in detail
        for tax in (pi.taxes or []):
            result["taxes"].append({
                "idx": tax.idx,
                "charge_type": tax.charge_type,
                "account_head": tax.account_head,
                "description": getattr(tax, "description", ""),
                "tax_amount": getattr(tax, "tax_amount", 0),
                "base_tax_amount": getattr(tax, "base_tax_amount", 0),
                "add_deduct_tax": getattr(tax, "add_deduct_tax", ""),
                "is_pph": "PPh" in (tax.account_head or "")
            })

        # Count PPh rows
        pph_rows = [t for t in result["taxes"] if t["is_pph"]]
        result["pph_row_count"] = len(pph_rows)

        # Check database directly
        db_taxes = frappe.db.sql("""
            SELECT idx, charge_type, account_head, description,
                   tax_amount, base_tax_amount, add_deduct_tax
            FROM `tabPurchase Taxes and Charges`
            WHERE parent = %s
            ORDER BY idx
        """, pi_name, as_dict=True)

        result["db_taxes"] = db_taxes
        result["db_pph_count"] = len([t for t in db_taxes if "PPh" in (t.get("account_head") or "")])

        # Check if ER has PPh
        if result["er_name"]:
            er = frappe.get_doc("Expense Request", result["er_name"])
            result["er_pph"] = {
                "is_pph_applicable": getattr(er, "is_pph_applicable", 0),
                "pph_type": getattr(er, "pph_type", None),
                "total_pph": getattr(er, "total_pph", 0)
            }

        return result

    except Exception as e:
        frappe.log_error(
            title=f"Debug PI PPh Error - {pi_name}",
            message=frappe.get_traceback()
        )
        return {
            "status": "error",
            "message": str(e),
            "traceback": frappe.get_traceback()
        }


@frappe.whitelist()
def force_add_pph_row(pi_name):
    """
    Force add PPh row by directly inserting into database

    Usage:
    frappe.call({
        method: 'imogi_finance.scripts.debug_pi_pph.force_add_pph_row',
        args: {pi_name: 'ACC-PINV-2026-00025'},
        callback: function(r) {
            console.log(r.message);
            if (r.message.status === 'success') location.reload();
        }
    });
    """
    try:
        pi = frappe.get_doc("Purchase Invoice", pi_name)

        # Check if already has PPh
        existing_pph = frappe.db.sql("""
            SELECT name FROM `tabPurchase Taxes and Charges`
            WHERE parent = %s AND account_head LIKE '%%PPh%%'
        """, pi_name)

        if existing_pph:
            return {
                "status": "skip",
                "message": "PPh row already exists in database"
            }

        # Get ER
        er_name = getattr(pi, "imogi_expense_request", None)
        if not er_name:
            return {"status": "error", "message": "No ER linked"}

        er = frappe.get_doc("Expense Request", er_name)
        pph_type = getattr(er, "pph_type", None)
        total_pph_er = flt(getattr(er, "total_pph", 0))

        if not pph_type or total_pph_er == 0:
            return {"status": "error", "message": "ER has no PPh config"}

        # Get account
        category = frappe.get_doc("Tax Withholding Category", pph_type)
        account = None
        for acc in (category.accounts or []):
            if acc.company == pi.company:
                account = acc.account
                break

        if not account:
            return {"status": "error", "message": "No account found"}

        # Get cost center
        cost_center = pi.get("cost_center") or frappe.get_cached_value("Company", pi.company, "cost_center")

        # Get next idx
        max_idx = frappe.db.sql("""
            SELECT IFNULL(MAX(idx), 0) FROM `tabPurchase Taxes and Charges`
            WHERE parent = %s
        """, pi_name)[0][0]

        next_idx = max_idx + 1

        # Use ER's calculated PPh amount
        pph_amount = total_pph_er

        # Create new tax row child doc
        tax_row = frappe.new_doc("Purchase Taxes and Charges")
        tax_row.parent = pi_name
        tax_row.parenttype = "Purchase Invoice"
        tax_row.parentfield = "taxes"
        tax_row.idx = next_idx
        tax_row.charge_type = "Actual"
        tax_row.account_head = account
        tax_row.description = f"Tax Withheld - {pph_type}"
        tax_row.tax_amount = -pph_amount
        tax_row.base_tax_amount = -pph_amount
        tax_row.add_deduct_tax = "Deduct"
        tax_row.category = "Total"
        tax_row.cost_center = cost_center
        tax_row.insert(ignore_permissions=True)

        # Update PI header
        pi.apply_tds = 1
        pi.tax_withholding_category = pph_type

        # Recalculate
        pi.reload()
        pi.run_method("calculate_taxes_and_totals")
        pi.save(ignore_permissions=True)

        frappe.db.commit()

        # Verify
        pi.reload()
        final_pph = flt(getattr(pi, "taxes_and_charges_deducted", 0))

        return {
            "status": "success",
            "message": "PPh row inserted directly",
            "pph_amount": pph_amount,
            "pph_final": final_pph,
            "grand_total": pi.grand_total
        }

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(
            title=f"Force Add PPh Error - {pi_name}",
            message=frappe.get_traceback()
        )
        return {
            "status": "error",
            "message": str(e)
        }
