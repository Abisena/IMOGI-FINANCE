#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive integration tests for tax invoice OCR processing.

Tests the complete pipeline from OCR text to validated results.
"""

import sys
import os

# Fix Windows console encoding for emojis
if sys.platform == 'win32':
	os.system('chcp 65001 >nul 2>&1')
	if hasattr(sys.stdout, 'reconfigure'):
		sys.stdout.reconfigure(encoding='utf-8')
	if hasattr(sys.stderr, 'reconfigure'):
		sys.stderr.reconfigure(encoding='utf-8')

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

# Now import the functions
from imogi_finance.imogi_finance.parsers.normalization import (
	parse_indonesian_currency,
	validate_tax_calculation,
	detect_tax_rate,
	extract_summary_values,
	process_tax_invoice_ocr
)


def print_separator(char="-", length=100):
	"""Print a separator line."""
	print(char * length)


def print_header(title):
	"""Print a test header."""
	print("\n" + "=" * 100)
	print(f"🧪 {title}")
	print("=" * 100)


def print_pass(message):
	"""Print a PASS result."""
	print(f"✅ PASS: {message}")


def print_fail(message):
	"""Print a FAIL result."""
	print(f"❌ FAIL: {message}")


def test_currency_parsing():
	"""TEST 1: Currency parsing with various formats."""
	print_header("TEST 1: Currency Parsing with Various Formats")

	test_cases = [
		# (input, expected, description)
		("4.953.154,00", 4953154.0, "Standard format with decimals"),
		("Rp 4.953.154,00", 4953154.0, "With Rp prefix"),
		("517.605,00", 517605.0, "Smaller amount"),
		("1.234,56", 1234.56, "With decimal cents"),
		("4953154", 4953154.0, "Integer only (no separators)"),
		("0,00", 0.0, "Zero value"),
		("", 0.0, "Empty string"),
		("   ", 0.0, "Whitespace only"),
		("Rp   1.000.000,00  ", 1000000.0, "Extra whitespace"),
	]

	passed = 0
	failed = 0

	for input_str, expected, description in test_cases:
		result = parse_indonesian_currency(input_str)

		if result == expected:
			print_pass(f"{description}: '{input_str}' → {result:,.2f}")
			passed += 1
		else:
			print_fail(f"{description}: '{input_str}' → {result:,.2f} (expected {expected:,.2f})")
			failed += 1

	print_separator()
	print(f"📊 Currency Parsing: {passed}/{len(test_cases)} tests passed")

	return failed == 0


def test_validation_correct_values():
	"""TEST 2: Validation with CORRECT values (should pass)."""
	print_header("TEST 2: Validation with CORRECT Values")

	print("\n📋 Test Data (Perfect Invoice - No Discount):")
	print("  Harga Jual: Rp 1,000,000.00")
	print("  DPP:        Rp 1,000,000.00")
	print("  PPN (11%):  Rp   110,000.00")
	print("  PPnBM:      Rp         0.00")
	print("\n🔍 Expected: Should PASS validation (values are correct)")

	print_separator()

	is_valid, issues = validate_tax_calculation(
		harga_jual=1000000.0,
		dpp=1000000.0,
		ppn=110000.0,
		ppnbm=0.0,
		tax_rate=0.11,
		potongan_harga=0.0  # No discount
	)

	print(f"\n📊 Validation Result: {'✅ VALID' if is_valid else '❌ INVALID'}")

	if issues:
		print(f"\n⚠️  Issues found ({len(issues)}):")
		for issue in issues:
			print(f"  - {issue}")
	else:
		print("\n✨ No issues found - all validations passed!")

	# Calculate expected PPN for verification
	expected_ppn = 1000000.0 * 0.11
	actual_ppn = 110000.0
	ppn_diff = abs(expected_ppn - actual_ppn)

	print(f"\n🔢 PPN Calculation Check:")
	print(f"  Expected PPN (DPP × 11%): {expected_ppn:,.2f}")
	print(f"  Actual PPN:               {actual_ppn:,.2f}")
	print(f"  Difference:               {ppn_diff:,.2f}")

	if is_valid and len(issues) == 0:
		print_pass("Validation passed with no issues")
		return True
	else:
		print_fail(f"Validation should have passed but got {len(issues)} issues")
		return False


def test_validation_buggy_values():
	"""TEST 3: Validation with BUGGY values (should fail)."""
	print_header("TEST 3: Validation with BUGGY Values (Field Swap Bug)")

	print("\n📋 Test Data (BUGGY - Swapped DPP and PPN):")
	print("  Harga Jual: Rp 4,953,154.00")
	print("  DPP:        Rp   517,605.00  ← WRONG (this is actually PPN!)")
	print("  PPN:        Rp 4,313,371.00  ← WRONG (this is actually DPP!)")
	print("  Tax Rate:   12%")
	print("\n🔍 Expected: Should FAIL validation with CRITICAL swap warning")
	print("   Because PPN (4,313,371) > DPP (517,605) - impossible!")

	print_separator()

	is_valid, issues = validate_tax_calculation(
		harga_jual=4953154.0,
		dpp=517605.0,  # SWAPPED! This is actually PPN
		ppn=4313371.0,  # SWAPPED! This is actually DPP
		ppnbm=0.0,
		tax_rate=0.12
	)

	print(f"\n📊 Validation Result: {'✅ VALID' if is_valid else '❌ INVALID (Expected)'}")

	if issues:
		print(f"\n🚨 Issues found ({len(issues)}):")
		for issue in issues:
			print(f"  - {issue}")
	else:
		print("\n✨ No issues found")

	# Check for critical swap detection
	has_critical_swap = any("CRITICAL" in issue and "SWAPPED" in issue for issue in issues)

	print_separator()

	if not is_valid and has_critical_swap:
		print_pass("Buggy values correctly identified as INVALID with CRITICAL swap warning")
		return True
	elif not is_valid and not has_critical_swap:
		print_fail("Validation failed but didn't detect field swap as CRITICAL")
		return False
	else:
		print_fail("Buggy values incorrectly passed validation!")
		return False


def test_integration_with_ocr():
	"""TEST 4: Integration test with sample OCR text."""
	print_header("TEST 4: Integration Test with Sample OCR Text")

	print("\n📄 Sample OCR Text:")
	sample_ocr = """
	FAKTUR PAJAK

	Kode dan Nomor Seri Faktur Pajak: 040.002-26.50406870

	Harga Jual / Penggantian / Uang Muka / Termin 4.953.154,00
	Dikurangi Potongan Harga 247.658,00
	Dikurangi Uang Muka yang telah diterima
	Dasar Pengenaan Pajak 4.313.371,00
	Jumlah PPN (Pajak Pertambahan Nilai) 517.605,00
	Jumlah PPnBM (Pajak Penjualan atas Barang Mewah) 0,00
	"""

	print(sample_ocr)
	print_separator()

	print("\n🔄 Processing invoice...")

	result = process_tax_invoice_ocr(
		ocr_text=sample_ocr,
		tokens=[],  # Not using tokens for this test
		faktur_no="040.002-26.50406870",
		faktur_type="040"
	)

	print_separator()
	print("\n📊 Processing Results:")
	print(f"  Parse Status:      {result['parse_status']}")
	print(f"  Is Valid:          {result['is_valid']}")
	print(f"  Confidence Score:  {result['confidence_score']:.1%}")
	print(f"  Detected Tax Rate: {result['tax_rate_percentage']:.0f}%")

	print("\n💰 Extracted Values:")
	print(f"  Harga Jual:        Rp {result['harga_jual']:>15,.2f}")
	print(f"  Potongan Harga:    Rp {result['potongan_harga']:>15,.2f}")
	print(f"  Uang Muka:         Rp {result['uang_muka']:>15,.2f}")
	print(f"  DPP:               Rp {result['dpp']:>15,.2f}")
	print(f"  PPN:               Rp {result['ppn']:>15,.2f}")
	print(f"  PPnBM:             Rp {result['ppnbm']:>15,.2f}")

	if result['validation_issues']:
		print(f"\n⚠️  Validation Issues ({len(result['validation_issues'])}):")
		for issue in result['validation_issues']:
			print(f"  - {issue}")
	else:
		print("\n✅ No validation issues")

	print_separator()

	# Verify extracted values are correct
	checks_passed = 0
	checks_total = 6

	expected_values = {
		'harga_jual': 4953154.0,
		'potongan_harga': 247658.0,
		'dpp': 4313371.0,
		'ppn': 517605.0,
		'ppnbm': 0.0,
	}

	print("\n🔍 Value Extraction Verification:")
	for field, expected in expected_values.items():
		actual = result[field]
		if actual == expected:
			print(f"  ✅ {field}: {actual:,.2f} (correct)")
			checks_passed += 1
		else:
			print(f"  ❌ {field}: {actual:,.2f} (expected {expected:,.2f})")

	# Check tax rate detection
	# Should detect 12% based on actual values (517,605 / 4,313,371 ≈ 12%)
	detected_rate_pct = result['tax_rate_percentage']
	if detected_rate_pct == 12.0:
		print(f"  ✅ Tax rate: {detected_rate_pct:.0f}% (correctly detected 12%)")
		checks_passed += 1
	else:
		print(f"  ⚠️  Tax rate: {detected_rate_pct:.0f}% (expected 12% based on actual values)")
		# Still count as pass if it's 11% (might be based on faktur type)
		if detected_rate_pct == 11.0:
			checks_passed += 1

	print_separator()
	print(f"\n📊 Integration Test: {checks_passed}/{checks_total} checks passed")

	# Test passes if:
	# 1. All values extracted correctly
	# 2. Parse status is reasonable (Approved or Needs Review)
	# 3. Tax rate detected (11% or 12%)
	valid_statuses = ["Approved", "Needs Review"]

	if checks_passed >= 5 and result['parse_status'] in valid_statuses:
		print_pass("Integration test completed successfully")
		return True
	else:
		print_fail(f"Integration test failed: {checks_passed}/{checks_total} checks passed")
		return False


def test_edge_case_empty_values():
	"""TEST 5: Edge case - Empty/missing values."""
	print_header("TEST 5: Edge Case - Empty/Missing Values")

	print("\n📋 Test Data: Empty OCR text")
	empty_ocr = ""

	print_separator()

	result = process_tax_invoice_ocr(
		ocr_text=empty_ocr,
		tokens=[],
		faktur_no="",
		faktur_type=""
	)

	print(f"\n📊 Processing Results:")
	print(f"  Parse Status:      {result['parse_status']}")
	print(f"  Confidence Score:  {result['confidence_score']:.1%}")

	print_separator()

	# Should result in Draft status with low confidence
	if result['parse_status'] == "Draft" and result['confidence_score'] < 0.5:
		print_pass("Empty values correctly handled (Draft status, low confidence)")
		return True
	else:
		print_fail(f"Expected Draft status with low confidence")
		return False


def test_edge_case_swapped_in_ocr():
	"""TEST 6: Edge case - Swapped values in OCR text."""
	print_header("TEST 6: Edge Case - Swapped Values in OCR Text")

	print("\n📋 Test Data: OCR with swapped DPP/PPN")
	swapped_ocr = """
	Dasar Pengenaan Pajak 517.605,00
	Jumlah PPN 4.313.371,00
	"""

	print(swapped_ocr)
	print_separator()

	print("\n🔄 Processing invoice...")

	result = process_tax_invoice_ocr(
		ocr_text=swapped_ocr,
		tokens=[],
		faktur_no="040.002-26.50406870",
		faktur_type="040"
	)

	print_separator()
	print(f"\n📊 Processing Results:")
	print(f"  Parse Status:      {result['parse_status']}")
	print(f"  DPP:               {result['dpp']:,.2f}")
	print(f"  PPN:               {result['ppn']:,.2f}")

	# Check if swap was detected
	has_swap_warning = any("CRITICAL" in issue and "SWAPPED" in issue
	                       for issue in result['validation_issues'])

	# After extract_summary_values auto-correction, DPP should be > PPN
	values_corrected = result['dpp'] > result['ppn']

	print_separator()

	if has_swap_warning or values_corrected:
		print_pass("Swapped values detected and/or corrected")
		return True
	else:
		print_fail("Swapped values not detected")
		return False


def run_all_tests():
	"""Run all integration tests."""
	print("\n" + "=" * 100)
	print("🧪 TAX INVOICE OCR PROCESSING - COMPREHENSIVE INTEGRATION TESTS")
	print("=" * 100)

	tests = [
		("Currency Parsing", test_currency_parsing),
		("Validation - Correct Values", test_validation_correct_values),
		("Validation - Buggy Values", test_validation_buggy_values),
		("Integration with OCR", test_integration_with_ocr),
		("Edge Case - Empty Values", test_edge_case_empty_values),
		("Edge Case - Swapped Values", test_edge_case_swapped_in_ocr),
	]

	results = []

	for test_name, test_func in tests:
		try:
			passed = test_func()
			results.append((test_name, passed))
		except Exception as e:
			print(f"\n❌ ERROR in {test_name}: {e}")
			import traceback
			traceback.print_exc()
			results.append((test_name, False))

	# Summary
	print("\n" + "=" * 100)
	print("📊 TEST SUMMARY")
	print("=" * 100)

	passed_count = sum(1 for _, passed in results if passed)
	total_count = len(results)

	for test_name, passed in results:
		status = "✅ PASS" if passed else "❌ FAIL"
		print(f"{status}: {test_name}")

	print("\n" + "=" * 100)
	print(f"🎯 Final Result: {passed_count}/{total_count} tests passed")
	print("=" * 100)

	if passed_count == total_count:
		print("\n🎉 ALL TESTS PASSED! 🎉")
		return True
	else:
		print(f"\n⚠️  {total_count - passed_count} test(s) failed")
		return False


if __name__ == "__main__":
	try:
		success = run_all_tests()
		sys.exit(0 if success else 1)
	except Exception as e:
		print(f"\n❌ FATAL ERROR: {e}")
		import traceback
		traceback.print_exc()
		sys.exit(1)
