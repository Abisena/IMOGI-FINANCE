#!/usr/bin/env python3
"""
Test script untuk Budget Control Entry creation
Run via: bench --site [site-name] console < test_budget_control.py
Atau copy-paste ke bench console
"""

import frappe
from frappe import _


def test_budget_control_entry_creation(expense_request_name):
    """Test creating Budget Control Entry for an Expense Request."""
    
    print("\n" + "="*70)
    print("TESTING BUDGET CONTROL ENTRY CREATION")
    print("="*70)
    
    # 1. Load Expense Request
    print(f"\n1. Loading Expense Request: {expense_request_name}")
    try:
        doc = frappe.get_doc("Expense Request", expense_request_name)
        print(f"   ✅ Loaded: {doc.name}")
        print(f"   Status: {doc.status}")
        print(f"   Workflow State: {doc.workflow_state}")
        print(f"   Cost Center: {doc.cost_center}")
        print(f"   Company: {doc.company}")
    except Exception as e:
        print(f"   ❌ Failed to load: {str(e)}")
        return
    
    # 2. Check Budget Control Settings
    print("\n2. Checking Budget Control Settings")
    try:
        settings = frappe.get_doc("Budget Control Setting", "Budget Control Setting")
        print(f"   Enable Budget Lock: {settings.enable_budget_lock}")
        print(f"   Lock on Workflow State: {settings.lock_on_workflow_state}")
        print(f"   Budget Controller Role: {settings.budget_controller_role}")
        
        if not settings.enable_budget_lock:
            print("   ⚠️  WARNING: Budget lock is disabled!")
            return
    except Exception as e:
        print(f"   ❌ Failed to load settings: {str(e)}")
        return
    
    # 3. Check if Budget exists
    print("\n3. Checking Budget Document")
    try:
        budgets = frappe.get_all(
            "Budget",
            filters={
                "company": doc.company,
                "cost_center": doc.cost_center,
                "docstatus": 1
            },
            fields=["name", "fiscal_year"]
        )
        if budgets:
            print(f"   ✅ Found {len(budgets)} budget(s):")
            for b in budgets:
                print(f"      - {b.name} (FY: {b.fiscal_year})")
        else:
            print("   ⚠️  No Budget found (will be bypassed)")
    except Exception as e:
        print(f"   ❌ Error checking budgets: {str(e)}")
    
    # 4. Check items
    print("\n4. Checking Expense Request Items")
    if not doc.items:
        print("   ❌ No items found!")
        return
    
    print(f"   Found {len(doc.items)} item(s):")
    total = 0
    for item in doc.items:
        amt = item.amount or 0
        total += amt
        print(f"      - {item.item_code}: {item.expense_account} = {amt}")
    print(f"   Total Amount: {total}")
    
    # 5. Check existing Budget Control Entries
    print("\n5. Checking Existing Budget Control Entries")
    try:
        existing = frappe.get_all(
            "Budget Control Entry",
            filters={
                "ref_doctype": "Expense Request",
                "ref_name": doc.name
            },
            fields=["name", "entry_type", "direction", "amount", "docstatus"]
        )
        if existing:
            print(f"   Found {len(existing)} existing entries:")
            for e in existing:
                print(f"      - {e.name}: {e.entry_type} {e.direction} {e.amount} (docstatus={e.docstatus})")
        else:
            print("   No existing entries found")
    except Exception as e:
        print(f"   ❌ Error checking entries: {str(e)}")
    
    # 6. Trigger reserve_budget_for_request
    print("\n6. Triggering reserve_budget_for_request()")
    try:
        from imogi_finance.budget_control import workflow
        
        entries = workflow.reserve_budget_for_request(doc)
        
        if entries:
            print(f"   ✅ SUCCESS! Created {len(entries)} entries:")
            for entry_name in entries:
                print(f"      - {entry_name}")
        else:
            print("   ⚠️  No entries created (check logs)")
            
    except Exception as e:
        print(f"   ❌ FAILED: {str(e)}")
        import traceback
        print("\n   Traceback:")
        print("   " + "\n   ".join(traceback.format_exc().split("\n")))
    
    # 7. Verify entries were created
    print("\n7. Verifying Budget Control Entries")
    try:
        created = frappe.get_all(
            "Budget Control Entry",
            filters={
                "ref_doctype": "Expense Request",
                "ref_name": doc.name
            },
            fields=["name", "entry_type", "direction", "amount", "posting_date", "docstatus"],
            order_by="creation desc"
        )
        if created:
            print(f"   ✅ Found {len(created)} entries:")
            for e in created:
                status = "Submitted" if e.docstatus == 1 else "Draft" if e.docstatus == 0 else "Cancelled"
                print(f"      - {e.name}: {e.entry_type} {e.direction} {e.amount} ({status})")
        else:
            print("   ❌ No entries found!")
    except Exception as e:
        print(f"   ❌ Error verifying: {str(e)}")
    
    print("\n" + "="*70)
    print("TEST COMPLETED")
    print("="*70 + "\n")


def quick_test():
    """Quick test dengan ER terbaru."""
    print("Searching for latest Expense Request...")
    
    ers = frappe.get_all(
        "Expense Request",
        filters={"docstatus": 1, "status": "Approved"},
        fields=["name", "status", "workflow_state"],
        order_by="creation desc",
        limit=1
    )
    
    if not ers:
        print("❌ No approved Expense Request found!")
        print("\nTrying to find any submitted ER...")
        ers = frappe.get_all(
            "Expense Request",
            filters={"docstatus": 1},
            fields=["name", "status", "workflow_state"],
            order_by="creation desc",
            limit=1
        )
    
    if ers:
        er_name = ers[0].name
        print(f"Found: {er_name} (Status: {ers[0].status})")
        test_budget_control_entry_creation(er_name)
    else:
        print("❌ No submitted Expense Request found!")


def check_all_approved_ers():
    """Check all approved ERs yang belum punya Budget Control Entry."""
    print("\n" + "="*70)
    print("CHECKING ALL APPROVED EXPENSE REQUESTS")
    print("="*70)
    
    # Get all approved ERs
    ers = frappe.get_all(
        "Expense Request",
        filters={"docstatus": 1, "status": "Approved"},
        fields=["name", "status", "posting_date"],
        order_by="posting_date desc"
    )
    
    print(f"\nFound {len(ers)} approved Expense Requests")
    
    missing = []
    for er in ers:
        # Check if has BCE
        bce = frappe.get_all(
            "Budget Control Entry",
            filters={
                "ref_doctype": "Expense Request",
                "ref_name": er.name,
                "entry_type": "RESERVATION"
            }
        )
        
        if not bce:
            missing.append(er.name)
            print(f"   ❌ {er.name} - No Budget Control Entry")
        else:
            print(f"   ✅ {er.name} - Has {len(bce)} entry(ies)")
    
    if missing:
        print(f"\n⚠️  {len(missing)} Expense Requests missing Budget Control Entries:")
        for er_name in missing:
            print(f"   - {er_name}")
        
        print("\nTo fix them, run:")
        print("fix_missing_budget_entries()")
    else:
        print("\n✅ All approved ERs have Budget Control Entries!")
    
    print("="*70 + "\n")


def fix_missing_budget_entries():
    """Create missing Budget Control Entries for all approved ERs."""
    print("\n" + "="*70)
    print("FIXING MISSING BUDGET CONTROL ENTRIES")
    print("="*70)
    
    from imogi_finance.budget_control import workflow
    
    # Get all approved ERs without BCE
    ers = frappe.get_all(
        "Expense Request",
        filters={"docstatus": 1, "status": "Approved"},
        fields=["name"]
    )
    
    fixed = []
    failed = []
    
    for er in ers:
        # Check if has BCE
        bce = frappe.get_all(
            "Budget Control Entry",
            filters={
                "ref_doctype": "Expense Request",
                "ref_name": er.name,
                "entry_type": "RESERVATION"
            }
        )
        
        if not bce:
            print(f"\nProcessing {er.name}...")
            try:
                doc = frappe.get_doc("Expense Request", er.name)
                entries = workflow.reserve_budget_for_request(doc)
                if entries:
                    print(f"   ✅ Created {len(entries)} entries")
                    fixed.append(er.name)
                else:
                    print(f"   ⚠️  No entries created")
                    failed.append((er.name, "No entries created"))
            except Exception as e:
                print(f"   ❌ Failed: {str(e)}")
                failed.append((er.name, str(e)))
    
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(f"✅ Fixed: {len(fixed)}")
    print(f"❌ Failed: {len(failed)}")
    
    if failed:
        print("\nFailed items:")
        for er_name, error in failed:
            print(f"   - {er_name}: {error}")
    
    print("="*70 + "\n")


# Print instructions
print("""
Budget Control Entry Test Script Loaded!

Available functions:
1. test_budget_control_entry_creation("ER-2026-000027")
   - Test specific Expense Request
   
2. quick_test()
   - Test with latest approved ER
   
3. check_all_approved_ers()
   - Check which ERs are missing Budget Control Entries
   
4. fix_missing_budget_entries()
   - Automatically create missing entries for all approved ERs

Example:
>>> quick_test()
>>> check_all_approved_ers()
>>> fix_missing_budget_entries()
""")
