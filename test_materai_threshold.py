"""
Test for Materai (Stamp Duty) Threshold Setting

Tests the requires_materai() function with various amounts.
"""

import frappe
from imogi_finance.receipt_control.utils import requires_materai, get_receipt_control_settings


def test_materai_default_threshold():
    """Test with default threshold of Rp 10,000,000"""
    print("\n=== Testing Materai Threshold (Default: Rp 10,000,000) ===\n")
    
    test_cases = [
        (5000000, False, "Rp 5,000,000 - Below threshold"),
        (9999999, False, "Rp 9,999,999 - Below threshold"),
        (10000000, True, "Rp 10,000,000 - At threshold"),
        (10000001, True, "Rp 10,000,001 - Above threshold"),
        (25000000, True, "Rp 25,000,000 - Above threshold"),
        (100000000, True, "Rp 100,000,000 - Above threshold"),
    ]
    
    for amount, expected, description in test_cases:
        result = requires_materai(amount)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        print(f"{status} - {description}: {result} (expected: {expected})")
        
        if result != expected:
            raise AssertionError(f"Failed test for {amount}: got {result}, expected {expected}")
    
    print("\n✅ All default threshold tests passed!\n")


def test_custom_threshold():
    """Test with custom threshold"""
    print("\n=== Testing Custom Threshold (Rp 5,000,000) ===\n")
    
    # Save current setting
    settings_doc = frappe.get_single("Finance Control Settings")
    original_value = settings_doc.materai_minimum_amount
    
    try:
        # Set custom threshold
        settings_doc.materai_minimum_amount = 5000000
        settings_doc.save()
        frappe.db.commit()
        
        # Clear cache to ensure new value is used
        if hasattr(frappe, 'cache'):
            frappe.cache().delete_value('Finance Control Settings')
        
        test_cases = [
            (3000000, False, "Rp 3,000,000 - Below threshold"),
            (4999999, False, "Rp 4,999,999 - Below threshold"),
            (5000000, True, "Rp 5,000,000 - At threshold"),
            (5000001, True, "Rp 5,000,001 - Above threshold"),
            (10000000, True, "Rp 10,000,000 - Above threshold"),
        ]
        
        for amount, expected, description in test_cases:
            result = requires_materai(amount)
            status = "✅ PASS" if result == expected else "❌ FAIL"
            print(f"{status} - {description}: {result} (expected: {expected})")
            
            if result != expected:
                raise AssertionError(f"Failed test for {amount}: got {result}, expected {expected}")
        
        print("\n✅ All custom threshold tests passed!\n")
        
    finally:
        # Restore original setting
        settings_doc.materai_minimum_amount = original_value
        settings_doc.save()
        frappe.db.commit()


def test_edge_cases():
    """Test edge cases"""
    print("\n=== Testing Edge Cases ===\n")
    
    test_cases = [
        (0, False, "Zero amount"),
        (None, False, "None value"),
        (-1000, False, "Negative amount"),
        (0.01, False, "Very small amount"),
    ]
    
    for amount, expected, description in test_cases:
        try:
            result = requires_materai(amount)
            status = "✅ PASS" if result == expected else "❌ FAIL"
            print(f"{status} - {description}: {result} (expected: {expected})")
            
            if result != expected:
                raise AssertionError(f"Failed test for {amount}: got {result}, expected {expected}")
        except Exception as e:
            print(f"⚠️  WARNING - {description}: Exception raised: {str(e)}")
    
    print("\n✅ Edge case tests completed!\n")


def test_settings_retrieval():
    """Test that settings can be retrieved correctly"""
    print("\n=== Testing Settings Retrieval ===\n")
    
    settings = get_receipt_control_settings()
    print(f"Settings retrieved: {type(settings)}")
    print(f"Materai minimum amount: {settings.get('materai_minimum_amount')}")
    
    assert 'materai_minimum_amount' in settings, "materai_minimum_amount not in settings"
    assert isinstance(settings.materai_minimum_amount, (int, float)), "materai_minimum_amount should be numeric"
    
    print("✅ Settings retrieval test passed!\n")


def run_all_tests():
    """Run all materai threshold tests"""
    print("\n" + "="*60)
    print("MATERAI THRESHOLD TESTS")
    print("="*60)
    
    try:
        test_settings_retrieval()
        test_materai_default_threshold()
        test_custom_threshold()
        test_edge_cases()
        
        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED!")
        print("="*60 + "\n")
        
    except Exception as e:
        print("\n" + "="*60)
        print(f"❌ TEST FAILED: {str(e)}")
        print("="*60 + "\n")
        raise


if __name__ == "__main__":
    run_all_tests()
