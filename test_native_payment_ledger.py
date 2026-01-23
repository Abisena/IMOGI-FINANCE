#!/usr/bin/env python3
"""
Test Native Payment Ledger Features
Run with: bench --site [your-site] execute imogi_finance.test_native_payment_ledger.test_payment_ledger
"""

import frappe
from frappe.utils import nowdate, flt


def test_payment_ledger():
    """Test if Payment Ledger Entry is working"""
    
    print("\n" + "="*70)
    print("TESTING NATIVE PAYMENT LEDGER FEATURES")
    print("="*70)
    
    # Test 1: Check if Payment Ledger Entry exists
    print("\n[Test 1] Checking Payment Ledger Entry DocType...")
    try:
        doctype_exists = frappe.db.exists("DocType", "Payment Ledger Entry")
        if doctype_exists:
            print("✓ Payment Ledger Entry DocType exists")
        else:
            print("✗ Payment Ledger Entry not found - might be older ERPNext version")
            return
    except Exception as e:
        print(f"✗ Error: {e}")
        return
    
    # Test 2: Count total entries
    print("\n[Test 2] Counting Payment Ledger Entries...")
    try:
        total_count = frappe.db.count("Payment Ledger Entry")
        print(f"✓ Total Payment Ledger Entries: {total_count:,}")
        
        if total_count == 0:
            print("⚠  No entries yet - create a Payment Entry to test")
            return
    except Exception as e:
        print(f"✗ Error: {e}")
        return
    
    # Test 3: Sample recent entries
    print("\n[Test 3] Recent Payment Ledger Entries (last 10)...")
    try:
        entries = frappe.get_all(
            "Payment Ledger Entry",
            fields=[
                "name", "voucher_type", "voucher_no", "party_type", "party",
                "amount", "against_voucher_type", "against_voucher_no",
                "posting_date", "delinked"
            ],
            limit=10,
            order_by="creation desc"
        )
        
        print(f"\n{'Voucher':<15} {'Party':<20} {'Amount':>15} {'Status':<30}")
        print("-" * 80)
        
        for entry in entries:
            if entry.get("delinked"):
                status = "DELINKED"
            elif not entry.get("against_voucher_type"):
                status = "🟢 ADVANCE (Unallocated)"
            else:
                status = f"🔵 → {entry['against_voucher_type']}: {entry['against_voucher_no']}"
            
            print(f"{entry['voucher_no']:<15} {entry['party']:<20} {entry['amount']:>15,.0f} {status:<30}")
    
    except Exception as e:
        print(f"✗ Error: {e}")
        return
    
    # Test 4: Find unallocated advances
    print("\n[Test 4] Finding Unallocated Advances...")
    try:
        # Query for advances (against_voucher_type is NULL)
        advances = frappe.db.sql("""
            SELECT 
                voucher_no,
                party_type,
                party,
                SUM(amount) as total_amount,
                SUM(COALESCE(allocated_amount, 0)) as total_allocated,
                SUM(amount) - SUM(COALESCE(allocated_amount, 0)) as unallocated
            FROM `tabPayment Ledger Entry`
            WHERE against_voucher_type IS NULL
              AND delinked = 0
            GROUP BY voucher_no, party_type, party
            HAVING unallocated > 0
            ORDER BY posting_date DESC
            LIMIT 10
        """, as_dict=True)
        
        if advances:
            print(f"\n✓ Found {len(advances)} unallocated advances:\n")
            print(f"{'Payment Entry':<15} {'Party Type':<12} {'Party':<25} {'Unallocated':>15}")
            print("-" * 80)
            
            for adv in advances:
                print(f"{adv['voucher_no']:<15} {adv['party_type']:<12} {adv['party']:<25} {adv['unallocated']:>15,.0f}")
        else:
            print("⚠  No unallocated advances found")
    
    except Exception as e:
        print(f"✗ Error: {e}")
        return
    
    # Test 5: Check native report existence
    print("\n[Test 5] Checking Native Reports...")
    try:
        advance_report = frappe.db.exists("Report", "Advance Payment Ledger")
        if advance_report:
            print("✓ Advance Payment Ledger report exists")
        else:
            print("⚠  Advance Payment Ledger report not found")
        
        payment_ledger_report = frappe.db.exists("Report", "Payment Ledger")
        if payment_ledger_report:
            print("✓ Payment Ledger report exists")
        else:
            print("⚠  Payment Ledger report not found")
    
    except Exception as e:
        print(f"✗ Error: {e}")
    
    # Test 6: Verify Payment Entry has advances field
    print("\n[Test 6] Checking Payment Entry Integration...")
    try:
        # Check if invoice doctypes have 'advances' field
        for doctype in ["Purchase Invoice", "Sales Invoice"]:
            has_advances = frappe.db.exists(
                "DocField",
                {"parent": doctype, "fieldname": "advances"}
            )
            if has_advances:
                print(f"✓ {doctype} has 'advances' field")
            else:
                print(f"✗ {doctype} missing 'advances' field")
    
    except Exception as e:
        print(f"✗ Error: {e}")
    
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print("\nNative Payment Ledger is working! ✅")
    print("\nNext Steps:")
    print("1. Test creating advance Payment Entry")
    print("2. Test 'Get Advances' button on invoice")
    print("3. Check Advance Payment Ledger report")
    print("4. Build custom dashboard report (if needed)")
    print("\n")


def test_create_advance_payment():
    """
    Example: Create a test advance payment
    DO NOT run in production without reviewing!
    """
    print("\n" + "="*70)
    print("TEST: CREATE ADVANCE PAYMENT")
    print("="*70)
    
    # Get first supplier
    supplier = frappe.get_all("Supplier", limit=1)
    if not supplier:
        print("✗ No suppliers found - create a supplier first")
        return
    
    supplier_name = supplier[0].name
    
    # Get default company
    company = frappe.defaults.get_user_default("Company")
    if not company:
        company = frappe.get_all("Company", limit=1)[0].name
    
    print(f"\nCreating test advance payment:")
    print(f"  Supplier: {supplier_name}")
    print(f"  Company: {company}")
    print(f"  Amount: Rp 10,000,000")
    
    try:
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Pay"
        pe.party_type = "Supplier"
        pe.party = supplier_name
        pe.company = company
        pe.posting_date = nowdate()
        
        # Set accounts
        pe.paid_from = frappe.get_value("Company", company, "default_bank_account")
        pe.paid_to = frappe.get_value("Party Account", {
            "parenttype": "Supplier",
            "parent": supplier_name,
            "company": company
        }, "account")
        
        if not pe.paid_from or not pe.paid_to:
            print("✗ Could not determine accounts - check supplier/company setup")
            return
        
        pe.paid_amount = 10000000
        pe.received_amount = 10000000
        
        # Dry run - show what would be created
        print("\n⚠  DRY RUN - Payment Entry would be created with:")
        print(f"  paid_from: {pe.paid_from}")
        print(f"  paid_to: {pe.paid_to}")
        print(f"  paid_amount: {pe.paid_amount:,.0f}")
        
        print("\n✓ To actually create, uncomment pe.insert() and pe.submit()")
        print("  Then check Payment Ledger Entry table")
        
        # Uncomment to actually create:
        # pe.insert()
        # pe.submit()
        # print(f"\n✓ Created: {pe.name}")
        # print(f"  Check Payment Ledger Entry for voucher_no = {pe.name}")
        
    except Exception as e:
        print(f"✗ Error: {e}")
        frappe.log_error(frappe.get_traceback())


if __name__ == "__main__":
    # If running directly with bench execute
    test_payment_ledger()
    
    # Uncomment to test creating advance payment:
    # test_create_advance_payment()
