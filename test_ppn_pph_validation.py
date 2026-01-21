#!/usr/bin/env python3
"""
Test PPN and PPh Validation Logic
==================================
This script tests the improved validation that handles PPN and PPh configuration
without conflicts.

Test Cases:
1. Only PPN without PPh - should pass if PPN template set
2. Only PPh without PPN - should pass if PPh type set
3. Both PPN and PPh - should pass if both configured
4. PPN set but no template - should fail with clear message
5. PPh set but no type - should fail with clear message
6. Both set but missing configs - should show both errors
"""

import frappe
from frappe.utils import flt


def test_validation_scenarios():
    """Test various PPN and PPh configuration scenarios."""
    
    print("\n" + "="*80)
    print("Testing PPN & PPh Validation Logic")
    print("="*80)
    
    test_cases = [
        {
            "name": "✅ Only PPN - Correct Config",
            "data": {
                "is_ppn_applicable": 1,
                "ppn_template": "ID - PPN 11% Input",
                "is_pph_applicable": 0,
                "pph_type": None,
            },
            "should_pass": True
        },
        {
            "name": "✅ Only PPh - Correct Config",
            "data": {
                "is_ppn_applicable": 0,
                "ppn_template": None,
                "is_pph_applicable": 1,
                "pph_type": "PPh 23 - 2%",
                "pph_base_amount": 1000000,
            },
            "should_pass": True
        },
        {
            "name": "✅ Both PPN & PPh - Correct Config",
            "data": {
                "is_ppn_applicable": 1,
                "ppn_template": "ID - PPN 11% Input",
                "is_pph_applicable": 1,
                "pph_type": "PPh 23 - 2%",
                "pph_base_amount": 1000000,
            },
            "should_pass": True
        },
        {
            "name": "❌ PPN Applicable but No Template",
            "data": {
                "is_ppn_applicable": 1,
                "ppn_template": None,
                "is_pph_applicable": 0,
                "pph_type": None,
            },
            "should_pass": False,
            "expected_error": "PPN Template"
        },
        {
            "name": "❌ PPh Applicable but No Type",
            "data": {
                "is_ppn_applicable": 0,
                "ppn_template": None,
                "is_pph_applicable": 1,
                "pph_type": None,
                "pph_base_amount": 1000000,
            },
            "should_pass": False,
            "expected_error": "PPh Type"
        },
        {
            "name": "❌ Both Applicable but Missing Configs",
            "data": {
                "is_ppn_applicable": 1,
                "ppn_template": None,
                "is_pph_applicable": 1,
                "pph_type": None,
            },
            "should_pass": False,
            "expected_error": "PPN"  # Should show both PPN and PPh errors
        },
        {
            "name": "❌ Item-level PPh but No Header Type",
            "data": {
                "is_ppn_applicable": 0,
                "ppn_template": None,
                "is_pph_applicable": 0,
                "pph_type": None,
                "items": [
                    {"is_pph_applicable": 1, "pph_base_amount": 500000, "amount": 500000}
                ]
            },
            "should_pass": False,
            "expected_error": "PPh Type"
        },
    ]
    
    passed = 0
    failed = 0
    
    for test_case in test_cases:
        print(f"\n📋 Test: {test_case['name']}")
        print(f"   Data: {test_case['data']}")
        
        try:
            # Create mock document
            doc = frappe._dict(test_case['data'])
            if 'items' not in doc:
                doc.items = []
            else:
                doc.items = [frappe._dict(item) for item in doc.items]
            
            # Run validation
            from imogi_finance.validators.finance_validator import FinanceValidator
            FinanceValidator.validate_tax_fields(doc)
            
            # If we reach here, validation passed
            if test_case['should_pass']:
                print(f"   ✅ PASS - Validation succeeded as expected")
                passed += 1
            else:
                print(f"   ❌ FAIL - Should have thrown error but didn't")
                failed += 1
                
        except Exception as e:
            error_msg = str(e)
            if not test_case['should_pass']:
                # Check if expected error is in message
                if test_case.get('expected_error', '') in error_msg:
                    print(f"   ✅ PASS - Got expected error")
                    print(f"   Error: {error_msg[:100]}...")
                    passed += 1
                else:
                    print(f"   ❌ FAIL - Got unexpected error")
                    print(f"   Expected: {test_case.get('expected_error')}")
                    print(f"   Got: {error_msg}")
                    failed += 1
            else:
                print(f"   ❌ FAIL - Should have passed but got error:")
                print(f"   Error: {error_msg}")
                failed += 1
    
    print(f"\n{'='*80}")
    print(f"Test Results: {passed} passed, {failed} failed")
    print(f"{'='*80}\n")
    
    return passed, failed


if __name__ == "__main__":
    test_validation_scenarios()
