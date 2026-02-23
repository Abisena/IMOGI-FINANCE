"""
Add PPh tax row to existing Purchase Invoice
Can be called from browser console
"""

import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist()
def add_pph_row_to_pi(pi_name):
    """
    Add PPh tax row to an existing Purchase Invoice that's missing it.

    Usage in browser console:
    frappe.call({
        method: 'imogi_finance.scripts.add_pph_to_pi.add_pph_row_to_pi',
        args: {pi_name: 'ACC-PINV-2026-00025'},
        callback: function(r) {
            console.log(r.message);
            if (r.message.status === 'success') {
                frappe.show_alert({message: 'PPh added successfully!', indicator: 'green'});
                setTimeout(() => location.reload(), 1000);
            } else {
                frappe.show_alert({message: r.message.message, indicator: 'red'});
            }
        }
    });
    """
    try:
        # Get PI
        pi = frappe.get_doc("Purchase Invoice", pi_name)

        # Check if already has PPh row
        existing_pph = [tax for tax in (pi.taxes or []) if 'PPh' in (tax.account_head or '')]
        if existing_pph:
            return {
                "status": "skip",
                "message": f"PI already has PPh tax row",
                "pi_name": pi_name
            }

        # Check if PI is from ER
        er_name = getattr(pi, "imogi_expense_request", None)
        if not er_name:
            return {
                "status": "error",
                "message": "PI was not created from Expense Request",
                "pi_name": pi_name
            }

        # Get ER to check PPh config
        er = frappe.get_doc("Expense Request", er_name)
        total_pph_er = flt(getattr(er, "total_pph", 0))
        pph_type = getattr(er, "pph_type", None)

        if not pph_type or total_pph_er == 0:
            return {
                "status": "error",
                "message": f"ER {er_name} does not have PPh configured or PPh amount is 0",
                "pi_name": pi_name,
                "er_name": er_name
            }

        # Get WHT category
        if not frappe.db.exists("Tax Withholding Category", pph_type):
            return {
                "status": "error",
                "message": f"Tax Withholding Category '{pph_type}' not found",
                "pi_name": pi_name
            }

        category = frappe.get_doc("Tax Withholding Category", pph_type)

        # Find account for company
        account = None
        for acc in (category.accounts or []):
            if acc.company == pi.company:
                account = acc.account
                break

        if not account:
            return {
                "status": "error",
                "message": f"No account configured for company '{pi.company}' in category '{pph_type}'",
                "pi_name": pi_name
            }

        # Calculate PPh
        pph_base = flt(pi.total)
        rate = flt(category.rate)
        pph_amount = pph_base * rate / 100

        # Get cost center
        cost_center = pi.get("cost_center") or frappe.get_cached_value("Company", pi.company, "cost_center")

        # Add PPh row
        pi.append("taxes", {
            "charge_type": "Actual",
            "account_head": account,
            "description": f"Tax Withheld - {pph_type}",
            "tax_amount": -pph_amount,
            "base_tax_amount": -pph_amount,
            "add_deduct_tax": "Deduct",
            "category": "Total",
            "cost_center": cost_center
        })

        # Set PPh fields on header
        pi.apply_tds = 1
        pi.tax_withholding_category = pph_type
        if hasattr(pi, "imogi_pph_type"):
            pi.imogi_pph_type = pph_type

        # Calculate totals
        pi.run_method("calculate_taxes_and_totals")

        # Save
        pi.save(ignore_permissions=True)
        frappe.db.commit()

        # Reload to get final values
        pi.reload()
        final_pph = flt(getattr(pi, "taxes_and_charges_deducted", 0))

        return {
            "status": "success",
            "message": f"PPh successfully added to Purchase Invoice",
            "pi_name": pi_name,
            "er_name": er_name,
            "pph_type": pph_type,
            "pph_base": pph_base,
            "pph_rate": rate,
            "pph_amount_calculated": pph_amount,
            "pph_amount_final": final_pph,
            "account_used": account,
            "grand_total": pi.grand_total
        }

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(
            title=f"Add PPh Row Error - {pi_name}",
            message=frappe.get_traceback()
        )
        return {
            "status": "error",
            "message": str(e),
            "pi_name": pi_name
        }
