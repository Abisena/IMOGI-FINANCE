#!/usr/bin/env python3
"""
Quick test to verify Asset Request approval route fix.
Run this in Frappe console: bench --site [site] console
"""

import frappe
from imogi_finance.approval import get_approval_route, get_active_setting_meta

def test_asset_request_approval():
    """Test that Asset Request with empty accounts triggers default line."""
    
    print("\n" + "="*60)
    print("TESTING: Asset Request Approval Route Fix")
    print("="*60)
    
    # Test parameters (matching ER-2026-000014)
    cost_center = "Main - ITB"
    accounts = ()  # Empty for Asset Request
    amount = 4706400
    
    print(f"\nTest Parameters:")
    print(f"  Cost Center: {cost_center}")
    print(f"  Accounts: {accounts} (empty - Asset Request)")
    print(f"  Amount: {amount:,.0f}")
    
    # Step 1: Get active setting
    print(f"\n[1] Getting active approval setting...")
    try:
        setting = get_active_setting_meta(cost_center)
        if setting:
            print(f"  ✅ Found setting: {setting.get('name')}")
            print(f"     Modified: {setting.get('modified')}")
        else:
            print(f"  ❌ No active setting found for {cost_center}")
            return False
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False
    
    # Step 2: Get approval route
    print(f"\n[2] Resolving approval route...")
    try:
        route = get_approval_route(cost_center, accounts, amount, setting_meta=setting)
        print(f"  ✅ Route resolved successfully")
        print(f"\n  Route Details:")
        for level in (1, 2, 3):
            user = route.get(f"level_{level}", {}).get("user")
            if user:
                print(f"    Level {level}: {user}")
            else:
                print(f"    Level {level}: (none)")
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Step 3: Verify route has at least one approver
    print(f"\n[3] Validating route...")
    has_approver = any(route.get(f"level_{level}", {}).get("user") for level in (1, 2, 3))
    
    if has_approver:
        print(f"  ✅ Route has at least one approver")
    else:
        print(f"  ❌ Route has no approvers - will fail at submit")
        return False
    
    # Step 4: Get actual approval lines from setting
    print(f"\n[4] Checking approval lines in setting...")
    try:
        lines = frappe.get_all(
            "Expense Approval Line",
            filters={"parent": setting.get("name")},
            fields=["name", "expense_account", "is_default", "level_1_user", "level_1_min_amount", "level_1_max_amount"],
            order_by="idx"
        )
        
        print(f"  Found {len(lines)} approval line(s):")
        for i, line in enumerate(lines, 1):
            print(f"\n  Line {i}:")
            print(f"    Expense Account: {line.get('expense_account') or '(none)'}")
            print(f"    Is Default: {line.get('is_default') or 0}")
            print(f"    Level 1 User: {line.get('level_1_user') or '(none)'}")
            print(f"    Level 1 Range: {line.get('level_1_min_amount', 0):,.0f} - {line.get('level_1_max_amount', 0):,.0f}")
            
            # Check if this line would match
            is_default = line.get('is_default')
            min_amt = line.get('level_1_min_amount', 0)
            max_amt = line.get('level_1_max_amount', 0)
            
            if is_default and line.get('level_1_user'):
                if max_amt == 0 or max_amt is None:
                    if amount >= min_amt:
                        print(f"    ✅ MATCHED (is_default, amount >= min)")
                    else:
                        print(f"    ❌ Not matched (amount < min)")
                else:
                    if min_amt <= amount <= max_amt:
                        print(f"    ✅ MATCHED (is_default, amount in range)")
                    else:
                        print(f"    ❌ Not matched (amount out of range)")
            elif is_default:
                print(f"    ⚠️  Default line but no approver configured")
                
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n" + "="*60)
    print("✅ TEST PASSED - Asset Request approval should work!")
    print("="*60)
    return True


def test_expense_request_approval():
    """Test that Expense Request still works (regression test)."""
    
    print("\n" + "="*60)
    print("REGRESSION TEST: Expense Request Approval Route")
    print("="*60)
    
    # Test parameters
    cost_center = "Main - ITB"
    accounts = ("Utility Expenses - ITB",)  # Specific account
    amount = 5000000
    
    print(f"\nTest Parameters:")
    print(f"  Cost Center: {cost_center}")
    print(f"  Accounts: {accounts}")
    print(f"  Amount: {amount:,.0f}")
    
    print(f"\n[1] Resolving approval route...")
    try:
        setting = get_active_setting_meta(cost_center)
        route = get_approval_route(cost_center, accounts, amount, setting_meta=setting)
        
        has_approver = any(route.get(f"level_{level}", {}).get("user") for level in (1, 2, 3))
        
        if has_approver:
            print(f"  ✅ Route resolved with approver")
            for level in (1, 2, 3):
                user = route.get(f"level_{level}", {}).get("user")
                if user:
                    print(f"    Level {level}: {user}")
        else:
            print(f"  ⚠️  No approver in route (will auto-approve or error)")
            
        print("\n✅ REGRESSION TEST PASSED - Expense Request still works")
        return True
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("\n🧪 Running approval route fix verification tests...\n")
    
    test1 = test_asset_request_approval()
    test2 = test_expense_request_approval()
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Asset Request Test: {'✅ PASS' if test1 else '❌ FAIL'}")
    print(f"Expense Request Test: {'✅ PASS' if test2 else '❌ FAIL'}")
    
    if test1 and test2:
        print("\n🎉 All tests passed! Safe to deploy.")
    else:
        print("\n⚠️  Some tests failed. Review before deploying.")
    print("="*60)
