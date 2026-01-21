"""
Test script to verify that double WHT is prevented when Apply WHT is set in Expense Request.

This script tests whether:
1. When Apply WHT is checked in Expense Request with PPh template
2. And the supplier has a Tax Withholding Category set in master
3. The Purchase Invoice should NOT double-calculate WHT

Run with: bench --site [your-site] execute imogi_finance.test_double_wht_prevention.test_double_wht_prevention
"""

import frappe
from frappe.utils import flt


def test_double_wht_prevention():
    """Test that double WHT is prevented when Apply WHT is set from ER."""
    
    print(f"\n{'='*80}")
    print(f"TEST: Double WHT Prevention")
    print(f"{'='*80}")
    
    # Find an Expense Request with Apply WHT (is_pph_applicable = 1)
    # and linked to a supplier that has Tax Withholding Category
    er_list = frappe.get_all(
        "Expense Request",
        filters={
            "docstatus": 1,
            "workflow_state": "Approved",
            "is_pph_applicable": 1,  # Apply WHT is checked
            "pph_type": ["is", "set"],  # PPh Type is set
        },
        fields=["name", "supplier", "pph_type", "pph_base_amount"],
        order_by="modified desc",
        limit=1
    )
    
    if not er_list:
        print("\n❌ No approved Expense Request with Apply WHT found")
        return
    
    er_name = er_list[0].name
    er = frappe.get_doc("Expense Request", er_name)
    supplier_name = er.supplier
    
    print(f"\n📋 Found Expense Request: {er_name}")
    print(f"   Supplier: {supplier_name}")
    print(f"   Apply WHT (is_pph_applicable): {bool(er.is_pph_applicable)}")
    print(f"   PPh Type from ER: {er.pph_type}")
    print(f"   PPh Base Amount: {flt(er.pph_base_amount or 0):,.2f}")
    
    # Check supplier's Tax Withholding Category
    supplier_tax_category = frappe.db.get_value("Supplier", supplier_name, "tax_withholding_category")
    print(f"\n   Supplier's Tax Withholding Category: {supplier_tax_category or 'Not set'}")
    
    if supplier_tax_category:
        print(f"   ⚠️  WARNING: Supplier HAS Tax Withholding Category set!")
        print(f"   This could cause DOUBLE WHT calculation if not prevented!")
    else:
        print(f"   ✅ OK: Supplier has NO Tax Withholding Category")
    
    # Check if PI already exists
    existing_pi = frappe.db.get_value(
        "Purchase Invoice",
        {"imogi_expense_request": er_name, "docstatus": ["!=", 2]},
        "name"
    )
    
    if existing_pi:
        print(f"\n⚠️  Purchase Invoice already exists: {existing_pi}")
        pi = frappe.get_doc("Purchase Invoice", existing_pi)
    else:
        print(f"\n🔨 Creating new Purchase Invoice from ER...")
        from imogi_finance.accounting import create_purchase_invoice_from_request
        
        try:
            pi_name = create_purchase_invoice_from_request(er_name)
            pi = frappe.get_doc("Purchase Invoice", pi_name)
            print(f"✅ Purchase Invoice created: {pi_name}")
        except Exception as e:
            print(f"❌ Error creating Purchase Invoice: {str(e)}")
            import traceback
            traceback.print_exc()
            return
    
    print(f"\n💰 Purchase Invoice WHT Configuration Check:")
    print(f"   Apply TDS (apply_tds): {pi.apply_tds}")
    print(f"   PPh Type from ER (imogi_pph_type): {pi.imogi_pph_type}")
    print(f"   Tax Withholding Category (from PI): {pi.tax_withholding_category or 'Not set'}")
    print(f"   Withholding Tax Base Amount: {flt(pi.withholding_tax_base_amount or 0):,.2f}")
    
    # Check taxes table for PPh entries
    print(f"\n📊 Taxes in Purchase Invoice:")
    pph_rows = []
    if pi.taxes:
        for tax_row in pi.taxes:
            tax_account = getattr(tax_row, "account_head", "")
            tax_desc = getattr(tax_row, "description", "")
            tax_amount = flt(getattr(tax_row, "tax_amount", 0))
            
            # Identify PPh rows (usually contain "PPh" or "Withholding" in description)
            if "PPh" in tax_desc or "Withholding" in tax_desc or "23" in tax_desc:
                pph_rows.append({
                    "account": tax_account,
                    "description": tax_desc,
                    "amount": tax_amount
                })
                print(f"   - {tax_desc}: {tax_amount:,.2f} IDR")
                print(f"     Account: {tax_account}")
    
    if not pph_rows:
        print(f"   ℹ️  No PPh rows found in taxes table")
    
    # Validation checks
    print(f"\n{'='*80}")
    print(f"VALIDATION CHECKS:")
    print(f"{'='*80}")
    
    issues = []
    
    # Check 1: tax_withholding_category should be EMPTY when Apply WHT from ER is used
    if supplier_tax_category and pi.tax_withholding_category:
        issues.append(
            f"❌ ISSUE: Both supplier's category ({supplier_tax_category}) and PI's category ({pi.tax_withholding_category}) are set!\n"
            f"   This will cause DOUBLE WHT calculation!"
        )
    elif pi.tax_withholding_category and not supplier_tax_category:
        issues.append(
            f"❌ ISSUE: PI has tax_withholding_category '{pi.tax_withholding_category}' but it's from ER (should be clear for Apply WHT)"
        )
    elif not pi.tax_withholding_category and pi.apply_tds:
        print(f"✅ PASS: tax_withholding_category is cleared (good for Apply WHT)")
    
    # Check 2: apply_tds should be 1 when Apply WHT from ER
    if pi.apply_tds != 1:
        issues.append(f"❌ ISSUE: apply_tds is {pi.apply_tds} (should be 1)")
    else:
        print(f"✅ PASS: apply_tds is set correctly")
    
    # Check 3: imogi_pph_type should match ER's pph_type
    if pi.imogi_pph_type != er.pph_type:
        issues.append(f"❌ ISSUE: imogi_pph_type mismatch: PI='{pi.imogi_pph_type}' vs ER='{er.pph_type}'")
    else:
        print(f"✅ PASS: imogi_pph_type matches ER")
    
    # Check 4: Only ONE PPh entry should exist (not double)
    if len(pph_rows) > 1:
        issues.append(f"❌ ISSUE: Found {len(pph_rows)} PPh entries! This indicates DOUBLE WHT!")
    elif len(pph_rows) == 1:
        print(f"✅ PASS: Only one PPh entry found (no double WHT)")
    elif len(pph_rows) == 0 and pi.apply_tds:
        issues.append(f"❌ ISSUE: No PPh entries found but apply_tds is set! PPh may not be calculated")
    
    # Print results
    if issues:
        print(f"\n{'='*80}")
        print(f"❌ ISSUES FOUND:")
        print(f"{'='*80}")
        for issue in issues:
            print(issue)
    else:
        print(f"\n{'='*80}")
        print(f"✅ ALL CHECKS PASSED - NO DOUBLE WHT DETECTED!")
        print(f"{'='*80}")
    
    # Detailed breakdown
    print(f"\n{'='*80}")
    print(f"DETAILED SUMMARY:")
    print(f"{'='*80}")
    print(f"Expense Request: {er_name}")
    print(f"Purchase Invoice: {pi.name}")
    print(f"Supplier: {supplier_name}")
    print(f"\nWHT Configuration:")
    print(f"  - Apply WHT from ER: ✅ {bool(er.is_pph_applicable)}")
    print(f"  - PPh Type from ER: {er.pph_type}")
    print(f"  - Supplier Tax Category: {supplier_tax_category or 'Not set'}")
    print(f"  - PI tax_withholding_category: {pi.tax_withholding_category or 'Cleared (CORRECT!)'}")
    print(f"  - PI apply_tds: {pi.apply_tds}")
    print(f"  - PPh entries in taxes: {len(pph_rows)}")
    if pph_rows:
        total_pph = sum(row["amount"] for row in pph_rows)
        print(f"  - Total PPh amount: {total_pph:,.2f}")
    
    return {
        "er_name": er_name,
        "pi_name": pi.name,
        "issues": issues,
        "pph_count": len(pph_rows),
        "is_success": len(issues) == 0
    }


if __name__ == "__main__":
    test_double_wht_prevention()
