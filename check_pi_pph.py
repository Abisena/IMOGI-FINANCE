"""
Quick script to check PPh status for Purchase Invoice
"""
import frappe
import json

def check_pi_pph(pi_name):
    """Check PPh configuration for PI and related ER"""

    # Get PI
    pi = frappe.get_doc("Purchase Invoice", pi_name)

    print("\n" + "="*70)
    print(f"PURCHASE INVOICE: {pi_name}")
    print("="*70)

    print(f"\nPI Status:")
    print(f"  Supplier: {pi.supplier}")
    print(f"  Total: Rp {pi.total:,.2f}")
    print(f"  Grand Total: Rp {pi.grand_total:,.2f}")
    print(f"  Apply TDS (PPh): {getattr(pi, 'apply_tds', 0)}")
    print(f"  Tax Withholding Category: {getattr(pi, 'tax_withholding_category', '-')}")
    print(f"  IMOGI PPh Type: {getattr(pi, 'imogi_pph_type', '-')}")
    print(f"  Taxes and Charges Deducted: Rp {getattr(pi, 'taxes_and_charges_deducted', 0):,.2f}")

    # Check if from ER
    er_name = getattr(pi, "imogi_expense_request", None)

    if not er_name:
        print(f"\n⚠️  PI is NOT created from Expense Request")
        return

    print(f"\n  Created from ER: {er_name}")

    # Get ER
    er = frappe.get_doc("Expense Request", er_name)

    print(f"\n" + "="*70)
    print(f"EXPENSE REQUEST: {er_name}")
    print("="*70)

    print(f"\nER Header:")
    print(f"  Total: Rp {er.total:,.2f}")
    print(f"  Apply WHT (is_pph_applicable): {getattr(er, 'is_pph_applicable', 0)}")
    print(f"  PPh Type: {getattr(er, 'pph_type', '-')}")
    print(f"  Total PPh: Rp {getattr(er, 'total_pph', 0):,.2f}")

    print(f"\nER Items:")
    for idx, item in enumerate(er.items or [], 1):
        pph_applicable = getattr(item, "is_pph_applicable", 0)
        print(f"  {idx}. {item.expense_account}")
        print(f"     Amount: Rp {item.amount:,.2f}")
        print(f"     Apply WHT: {pph_applicable}")
        if pph_applicable:
            print(f"     PPh Base: Rp {getattr(item, 'pph_base_amount', 0):,.2f}")
            print(f"     PPh Amount: Rp {getattr(item, 'pph_amount', 0):,.2f}")

    print(f"\n" + "="*70)
    print(f"PI ITEMS:")
    print("="*70)
    for idx, item in enumerate(pi.items or [], 1):
        print(f"  {idx}. {item.expense_account}")
        print(f"     Amount: Rp {item.amount:,.2f}")
        print(f"     Apply TDS: {getattr(item, 'apply_tds', 0)}")

    print(f"\n" + "="*70)
    print(f"DIAGNOSIS:")
    print("="*70)

    # Diagnosis
    issues = []

    if not getattr(er, 'is_pph_applicable', 0):
        issues.append("❌ ER Header 'Apply WHT' is NOT checked")
    else:
        print("✓ ER Header 'Apply WHT' is checked")

    if not getattr(er, 'pph_type', None):
        issues.append("❌ ER 'PPh Type' is NOT set")
    else:
        print(f"✓ ER PPh Type is set: {er.pph_type}")

    er_items_with_pph = [
        item for item in (er.items or [])
        if getattr(item, "is_pph_applicable", 0)
    ]

    if not er_items_with_pph:
        issues.append("❌ NO items in ER have 'Apply WHT' checked")
    else:
        print(f"✓ {len(er_items_with_pph)} items in ER have 'Apply WHT' checked")

    if not getattr(pi, 'apply_tds', 0):
        issues.append("❌ PI 'Apply TDS' is NOT set")
    else:
        print(f"✓ PI 'Apply TDS' is set")

    if not getattr(pi, 'tax_withholding_category', None):
        issues.append("❌ PI 'Tax Withholding Category' is NOT set")
    else:
        print(f"✓ PI Tax Withholding Category: {pi.tax_withholding_category}")

    pi_items_with_tds = [
        item for item in (pi.items or [])
        if getattr(item, "apply_tds", 0)
    ]

    if not pi_items_with_tds:
        issues.append("❌ NO items in PI have 'Apply TDS' set")
    else:
        print(f"✓ {len(pi_items_with_tds)} items in PI have 'Apply TDS' set")

    if issues:
        print(f"\n" + "="*70)
        print("ISSUES FOUND:")
        print("="*70)
        for issue in issues:
            print(f"  {issue}")

        print(f"\n" + "="*70)
        print("RECOMMENDED ACTION:")
        print("="*70)

        if not getattr(er, 'is_pph_applicable', 0) or not getattr(er, 'pph_type', None) or not er_items_with_pph:
            print("\n1. FIX EXPENSE REQUEST FIRST:")
            print(f"   - Open ER: {er_name}")
            print(f"   - Tab 'Tax' → Check 'Apply WHT'")
            print(f"   - Select 'PPh Type' (e.g., PPh 23)")
            print(f"   - Tab 'Items' → Check 'Apply WHT' on relevant items")
            print(f"   - Save ER")
            print(f"\n2. RECREATE PURCHASE INVOICE:")
            print(f"   - Delete current PI: {pi_name}")
            print(f"   - From ER {er_name}, click 'Create Purchase Invoice' again")
            print(f"   - New PI will have correct PPh calculation")
        else:
            print(f"\n1. RUN FIX SCRIPT:")
            print(f"   bench --site [site-name] execute imogi_finance.scripts.fix_pph_missing.fix_pph_for_pi --args \"['{pi_name}']\"")
    else:
        print("\n✅ All configurations look correct!")
        print("   But PPh still not calculated. Possible causes:")
        print("   - Tax Withholding Category configuration issue")
        print("   - Supplier not properly configured for WHT")
        print("   - set_tax_withholding() not called during creation")

# Run check
if __name__ == "__main__":
    import sys
    pi_name = sys.argv[1] if len(sys.argv) > 1 else "ACC-PINV-2026-00025"
    check_pi_pph(pi_name)
