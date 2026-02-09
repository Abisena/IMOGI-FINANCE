#!/usr/bin/env python3
"""
Test script for detect_tax_rate() function.

Verifies smart tax rate detection across all three methods:
1. Calculation from DPP/PPN values
2. Faktur type prefix detection
3. Default fallback
"""

# Mock frappe for standalone testing
class MockLogger:
	def warning(self, msg):
		print(f"⚠️  {msg}")

	def info(self, msg):
		print(f"ℹ️  {msg}")

	def debug(self, msg):
		pass  # Suppress debug messages for cleaner output

	def error(self, msg):
		print(f"🚨 {msg}")

class MockFrappe:
	def logger(self):
		return MockLogger()

import sys
sys.modules['frappe'] = MockFrappe()

# Now import the function
from imogi_finance.imogi_finance.parsers.normalization import detect_tax_rate


def test_detect_tax_rate():
	"""Test detect_tax_rate with various scenarios."""

	print("Testing detect_tax_rate()")
	print("=" * 100)

	# Test Case 1: Calculate 12% rate from actual values
	print("\n🧪 Test Case 1: Calculate 12% rate from DPP and PPN")
	print("-" * 100)
	print("Scenario: DPP = 4,313,371.00, PPN = 517,605.00")
	print("Expected: 517,605 / 4,313,371 = 0.12 (12%)")

	rate_1 = detect_tax_rate(4313371.0, 517605.0, "040.000-26.12345678")

	print(f"\n📊 Detected rate: {rate_1*100:.0f}%")
	assert rate_1 == 0.12, f"❌ Expected 0.12, got {rate_1}"
	print("✅ Test Case 1: PASSED - Correctly detected 12% rate from calculation!")

	# Test Case 2: Calculate 11% rate from actual values
	print("\n\n🧪 Test Case 2: Calculate 11% rate from DPP and PPN")
	print("-" * 100)
	print("Scenario: DPP = 1,000,000.00, PPN = 110,000.00")
	print("Expected: 110,000 / 1,000,000 = 0.11 (11%)")

	rate_2 = detect_tax_rate(1000000.0, 110000.0, "010.000-16.12345678")

	print(f"\n📊 Detected rate: {rate_2*100:.0f}%")
	assert rate_2 == 0.11, f"❌ Expected 0.11, got {rate_2}"
	print("✅ Test Case 2: PASSED - Correctly detected 11% rate from calculation!")

	# Test Case 3: Fallback to faktur type 040 (11%)
	print("\n\n🧪 Test Case 3: Faktur type 040 → 11%")
	print("-" * 100)
	print("Scenario: No DPP/PPN values, faktur type = '040.000-26.12345678'")
	print("Expected: Faktur type 040 typically uses 11%")

	rate_3 = detect_tax_rate(0, 0, "040.000-26.12345678")

	print(f"\n📊 Detected rate: {rate_3*100:.0f}%")
	assert rate_3 == 0.11, f"❌ Expected 0.11, got {rate_3}"
	print("✅ Test Case 3: PASSED - Correctly used faktur type 040 → 11%!")

	# Test Case 4: Fallback to faktur type 010 (11%)
	print("\n\n🧪 Test Case 4: Faktur type 010 → 11%")
	print("-" * 100)
	print("Scenario: No DPP/PPN values, faktur type = '010.000-16.12345678'")
	print("Expected: Faktur type 010 typically uses 11%")

	rate_4 = detect_tax_rate(0, 0, "010.000-16.12345678")

	print(f"\n📊 Detected rate: {rate_4*100:.0f}%")
	assert rate_4 == 0.11, f"❌ Expected 0.11, got {rate_4}"
	print("✅ Test Case 4: PASSED - Correctly used faktur type 010 → 11%!")

	# Test Case 5: Default fallback (11%)
	print("\n\n🧪 Test Case 5: Default fallback → 11%")
	print("-" * 100)
	print("Scenario: No DPP/PPN values, unknown faktur type = '030.000-16.12345678'")
	print("Expected: Default to 11% (current standard PPN rate)")

	rate_5 = detect_tax_rate(0, 0, "030.000-16.12345678")

	print(f"\n📊 Detected rate: {rate_5*100:.0f}%")
	assert rate_5 == 0.11, f"❌ Expected 0.11, got {rate_5}"
	print("✅ Test Case 5: PASSED - Correctly used default 11%!")

	# Test Case 6: Empty/None faktur type
	print("\n\n🧪 Test Case 6: Empty faktur type → default 11%")
	print("-" * 100)
	print("Scenario: No DPP/PPN values, empty faktur type")
	print("Expected: Default to 11%")

	rate_6 = detect_tax_rate(0, 0, "")

	print(f"\n📊 Detected rate: {rate_6*100:.0f}%")
	assert rate_6 == 0.11, f"❌ Expected 0.11, got {rate_6}"
	print("✅ Test Case 6: PASSED - Correctly used default 11%!")

	# Test Case 7: Rate with rounding tolerance (11.8% should round to 12%)
	print("\n\n🧪 Test Case 7: Rate with rounding tolerance (±2%)")
	print("-" * 100)
	print("Scenario: DPP = 1,000,000.00, PPN = 118,000.00")
	print("Expected: 118,000 / 1,000,000 = 0.118 (11.8%) → Should round to 12%")

	rate_7 = detect_tax_rate(1000000.0, 118000.0, "")

	print(f"\n📊 Detected rate: {rate_7*100:.0f}%")
	assert rate_7 == 0.12, f"❌ Expected 0.12 (within ±2% tolerance), got {rate_7}"
	print("✅ Test Case 7: PASSED - Correctly rounded 11.8% to 12%!")

	# Test Case 8: Rate with rounding tolerance (10.2% should round to 11%)
	print("\n\n🧪 Test Case 8: Rate with rounding tolerance (±2%)")
	print("-" * 100)
	print("Scenario: DPP = 1,000,000.00, PPN = 102,000.00")
	print("Expected: 102,000 / 1,000,000 = 0.102 (10.2%) → Should round to 11%")

	rate_8 = detect_tax_rate(1000000.0, 102000.0, "")

	print(f"\n📊 Detected rate: {rate_8*100:.0f}%")
	assert rate_8 == 0.11, f"❌ Expected 0.11 (within ±2% tolerance), got {rate_8}"
	print("✅ Test Case 8: PASSED - Correctly rounded 10.2% to 11%!")

	# Test Case 9: Rate outside tolerance with faktur type fallback
	print("\n\n🧪 Test Case 9: Rate outside tolerance → fallback to faktur type")
	print("-" * 100)
	print("Scenario: DPP = 1,000,000.00, PPN = 80,000.00 (8%), faktur type = '040'")
	print("Expected: 8% is outside ±2% tolerance, should fallback to faktur type 040 → 11%")

	rate_9 = detect_tax_rate(1000000.0, 80000.0, "040.000-26.12345678")

	print(f"\n📊 Detected rate: {rate_9*100:.0f}%")
	assert rate_9 == 0.11, f"❌ Expected 0.11 (fallback to faktur type), got {rate_9}"
	print("✅ Test Case 9: PASSED - Correctly fell back to faktur type when rate outside tolerance!")

	# Test Case 10: Real-world example from bug report
	print("\n\n🧪 Test Case 10: Real-world example (Invoice #04002500406870573)")
	print("-" * 100)
	print("Scenario: DPP = 4,313,371.00, PPN = 517,605.00, faktur type = '040.002-26.50406870'")
	print("Expected: 517,605 / 4,313,371 = 0.12000... → 12%")

	rate_10 = detect_tax_rate(4313371.0, 517605.0, "040.002-26.50406870")

	print(f"\n📊 Detected rate: {rate_10*100:.0f}%")
	print(f"Verification: {4313371.0 * rate_10:,.2f} (expected PPN: 517,605.00)")
	assert rate_10 == 0.12, f"❌ Expected 0.12, got {rate_10}"

	# Verify the rate produces correct PPN
	calculated_ppn = 4313371.0 * rate_10
	ppn_difference = abs(calculated_ppn - 517605.0)
	print(f"PPN difference: {ppn_difference:.2f} (should be < 1.00)")
	assert ppn_difference < 1.0, f"❌ PPN mismatch: {calculated_ppn:,.2f} vs 517,605.00"

	print("✅ Test Case 10: PASSED - Real-world invoice correctly detected as 12%!")

	# Summary
	print("\n" + "=" * 100)
	print("\n🎉 ALL TESTS PASSED!")
	print("\n✅ Summary:")
	print("  - Method 1 (Calculation): Works for 11% and 12% rates")
	print("  - Method 2 (Faktur Type): Correctly handles 040 and 010 prefixes")
	print("  - Method 3 (Default): Falls back to 11% when needed")
	print("  - Tolerance: ±2% rounding works correctly")
	print("  - Fallback chain: Calculation → Faktur Type → Default")
	print("  - Real-world validation: Invoice #04002500406870573 → 12% ✅")

	return True


if __name__ == "__main__":
	try:
		success = test_detect_tax_rate()
		sys.exit(0 if success else 1)
	except AssertionError as e:
		print(f"\n❌ TEST FAILED: {e}")
		sys.exit(1)
	except Exception as e:
		print(f"\n❌ ERROR: {e}")
		import traceback
		traceback.print_exc()
		sys.exit(1)
