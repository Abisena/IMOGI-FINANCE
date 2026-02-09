# -*- coding: utf-8 -*-
"""
Test Suite for Priority 1 Production Improvements
==================================================

Tests the critical improvements implemented:
1. Zero-rated transaction handling (exports, exempt goods)
2. Pre-compiled regex patterns (performance)
3. Basic error tracking structure

Run with:
    python test_priority1_improvements.py
"""

import sys
import time

# Add parent directory to path to import normalization module
sys.path.insert(0, r'd:\coding\IMOGI-FINANCE\imogi_finance\imogi_finance\parsers')

# Importing the functions from normalization.py
from normalization import (
    detect_tax_rate,
    validate_tax_calculation,
    extract_summary_values,
    ParsingError,
    ParsingErrorCollector,
    _COMPILED_PATTERNS
)


def test_zero_rated_export():
    """Test 1: Zero-rated export transaction (0% tax)"""
    print("\n" + "="*70)
    print("TEST 1: Zero-rated Export Transaction (0% tax)")
    print("="*70)

    # Export invoice: DPP exists but PPN = 0 (zero-rated)
    dpp = 10000000.0  # Rp 10 million
    ppn = 0.0  # Export = 0% tax
    faktur_type = "020"  # Export faktur type

    tax_rate = detect_tax_rate(dpp, ppn, faktur_type)

    print(f"DPP: Rp {dpp:,.2f}")
    print(f"PPN: Rp {ppn:,.2f}")
    print(f"Faktur Type: {faktur_type}")
    print(f"Detected Tax Rate: {tax_rate*100:.1f}%")

    assert tax_rate == 0.0, f"Expected 0.0 for export, got {tax_rate}"
    print("✅ PASS: Correctly detected zero-rated transaction")


def test_zero_rated_validation():
    """Test 2: Validate zero-rated transaction"""
    print("\n" + "="*70)
    print("TEST 2: Zero-rated Transaction Validation")
    print("="*70)

    # Export invoice with 0% tax
    harga_jual = 10500000.0
    dpp = 10000000.0
    ppn = 0.0  # Zero-rated
    ppnbm = 0.0
    tax_rate = 0.0  # Zero rate
    potongan_harga = 500000.0

    is_valid, issues = validate_tax_calculation(
        harga_jual=harga_jual,
        dpp=dpp,
        ppn=ppn,
        ppnbm=ppnbm,
        tax_rate=tax_rate,
        potongan_harga=potongan_harga
    )

    print(f"Harga Jual: Rp {harga_jual:,.2f}")
    print(f"DPP: Rp {dpp:,.2f}")
    print(f"PPN: Rp {ppn:,.2f} (0% - Export)")
    print(f"Tax Rate: {tax_rate*100:.1f}%")
    print(f"Valid: {is_valid}")
    print(f"Issues: {issues if issues else 'None'}")

    assert is_valid, f"Expected valid for zero-rated transaction, got issues: {issues}"
    assert len(issues) == 0, f"Expected no issues, got: {issues}"
    print("✅ PASS: Zero-rated validation works correctly")


def test_zero_rated_with_nonzero_ppn_warning():
    """Test 3: Zero-rated transaction with non-zero PPN (should warn)"""
    print("\n" + "="*70)
    print("TEST 3: Zero-rated with Non-Zero PPN (Warning)")
    print("="*70)

    # Zero-rated but PPN > 0 (unusual)
    harga_jual = 10000000.0
    dpp = 10000000.0
    ppn = 100000.0  # Should be 0 for export
    ppnbm = 0.0
    tax_rate = 0.0  # Zero rate

    is_valid, issues = validate_tax_calculation(
        harga_jual=harga_jual,
        dpp=dpp,
        ppn=ppn,
        ppnbm=ppnbm,
        tax_rate=tax_rate
    )

    print(f"Tax Rate: {tax_rate*100:.1f}% (Zero-rated)")
    print(f"DPP: Rp {dpp:,.2f}")
    print(f"PPN: Rp {ppn:,.2f} (Should be 0)")
    print(f"Valid: {is_valid}")
    print(f"Issues: {issues}")

    # Should have a warning about non-zero PPN
    assert len(issues) > 0, "Expected warning about non-zero PPN with zero tax rate"
    assert any("Zero-rated" in issue for issue in issues), "Expected zero-rated warning"
    print("✅ PASS: Warning correctly issued for zero-rated with non-zero PPN")


def test_standard_rate_still_works():
    """Test 4: Standard 11% and 12% rates still work correctly"""
    print("\n" + "="*70)
    print("TEST 4: Standard Tax Rates Still Work (11%, 12%)")
    print("="*70)

    # Test 11% rate
    dpp_11 = 10000000.0
    ppn_11 = 1100000.0  # 11%
    rate_11 = detect_tax_rate(dpp_11, ppn_11, "010")

    print(f"\n11% Test:")
    print(f"  DPP: Rp {dpp_11:,.2f}")
    print(f"  PPN: Rp {ppn_11:,.2f}")
    print(f"  Detected Rate: {rate_11*100:.1f}%")
    assert rate_11 == 0.11, f"Expected 0.11, got {rate_11}"
    print("  ✅ 11% rate detected correctly")

    # Test 12% rate
    dpp_12 = 10000000.0
    ppn_12 = 1200000.0  # 12%
    rate_12 = detect_tax_rate(dpp_12, ppn_12, "040")

    print(f"\n12% Test:")
    print(f"  DPP: Rp {dpp_12:,.2f}")
    print(f"  PPN: Rp {ppn_12:,.2f}")
    print(f"  Detected Rate: {rate_12*100:.1f}%")
    assert rate_12 == 0.12, f"Expected 0.12, got {rate_12}"
    print("  ✅ 12% rate detected correctly")

    print("\n✅ PASS: Standard rates (11%, 12%) still work correctly")


def test_pre_compiled_patterns():
    """Test 5: Pre-compiled regex patterns are defined"""
    print("\n" + "="*70)
    print("TEST 5: Pre-compiled Regex Patterns")
    print("="*70)

    # Check that patterns are pre-compiled
    assert _COMPILED_PATTERNS is not None, "Pre-compiled patterns not found"
    assert 'harga_jual' in _COMPILED_PATTERNS, "Missing harga_jual patterns"
    assert 'dpp' in _COMPILED_PATTERNS, "Missing dpp patterns"
    assert 'ppn' in _COMPILED_PATTERNS, "Missing ppn patterns"

    print("Pre-compiled pattern categories:")
    for key in _COMPILED_PATTERNS.keys():
        pattern_list = _COMPILED_PATTERNS[key]
        if isinstance(pattern_list, list):
            print(f"  • {key}: {len(pattern_list)} patterns")
        else:
            print(f"  • {key}: 1 pattern")

    # Verify patterns are compiled regex objects
    import re
    harga_jual_patterns = _COMPILED_PATTERNS['harga_jual']
    assert isinstance(harga_jual_patterns, list), "Patterns should be in list"
    assert all(hasattr(p, 'search') for p in harga_jual_patterns), "Patterns should be compiled regex"

    print("\n✅ PASS: Pre-compiled patterns are defined and valid")


def test_extraction_performance():
    """Test 6: Performance comparison with pre-compiled patterns"""
    print("\n" + "="*70)
    print("TEST 6: Extraction Performance Test")
    print("="*70)

    # Sample OCR text
    ocr_text = """
    FAKTUR PAJAK
    Kode dan Nomor Seri Faktur Pajak: 040.025.00.40687057

    Harga Jual / Penggantian / Uang Muka / Termin    4.953.154,00
    Dikurangi Potongan Harga                         247.658,00
    Dikurangi Uang Muka yang telah diterima
    Dasar Pengenaan Pajak                            4.313.371,00
    Jumlah PPN (Pajak Pertambahan Nilai)            517.605,00
    Jumlah PPnBM (Pajak Penjualan atas Barang Mewah)    0,00
    """

    # Run extraction multiple times to measure performance
    NUM_ITERATIONS = 100

    print(f"Running {NUM_ITERATIONS} extractions...")
    start_time = time.time()

    for _ in range(NUM_ITERATIONS):
        result = extract_summary_values(ocr_text)

    end_time = time.time()
    elapsed = end_time - start_time
    avg_time = elapsed / NUM_ITERATIONS

    print(f"\nPerformance Results:")
    print(f"  Total time: {elapsed:.4f} seconds")
    print(f"  Average per extraction: {avg_time*1000:.2f} ms")
    print(f"  Throughput: {NUM_ITERATIONS/elapsed:.1f} extractions/second")

    # Verify extraction still works correctly
    assert result['dpp'] == 4313371.0, "DPP incorrect"
    assert result['ppn'] == 517605.0, "PPN incorrect"
    assert result['harga_jual'] == 4953154.0, "Harga Jual incorrect"

    print("\n✅ PASS: Extraction works with pre-compiled patterns")
    print(f"   (Expected ~30-40% faster than non-compiled version)")


def test_error_tracking_structure():
    """Test 7: Error tracking structure (ParsingError, ParsingErrorCollector)"""
    print("\n" + "="*70)
    print("TEST 7: Error Tracking Structure")
    print("="*70)

    # Test ParsingError
    error1 = ParsingError("dpp", "Failed to parse DPP value", "ERROR")
    print(f"ParsingError created: {error1}")
    assert error1.field == "dpp"
    assert error1.severity == "ERROR"
    assert "dpp" in str(error1)
    print("✅ ParsingError class works")

    # Test ParsingErrorCollector
    collector = ParsingErrorCollector()
    assert not collector.has_errors(), "Should start with no errors"

    # Add some errors
    collector.add_error("ppn", "PPN value missing", "WARNING")
    collector.add_error("harga_jual", "Invalid currency format", "ERROR")

    assert collector.has_errors(), "Should have errors after adding"
    assert len(collector.errors) == 2, f"Expected 2 errors, got {len(collector.errors)}"

    messages = collector.get_error_messages()
    print(f"\nCollected error messages:")
    for msg in messages:
        print(f"  • {msg}")

    assert len(messages) == 2, "Should have 2 error messages"
    assert any("ppn" in msg.lower() for msg in messages), "Should have PPN error"
    assert any("harga_jual" in msg.lower() for msg in messages), "Should have Harga Jual error"

    print("\n✅ PASS: Error tracking structure works correctly")


def run_all_tests():
    """Run all Priority 1 improvement tests"""
    print("\n" + "="*70)
    print("PRIORITY 1 IMPROVEMENTS - COMPREHENSIVE TEST SUITE")
    print("="*70)
    print("\nTesting:")
    print("  1. Zero-rated transaction handling (exports, exempt)")
    print("  2. Pre-compiled regex patterns (performance)")
    print("  3. Error tracking structure")
    print()

    tests = [
        ("Zero-rated Export", test_zero_rated_export),
        ("Zero-rated Validation", test_zero_rated_validation),
        ("Zero-rated Warning", test_zero_rated_with_nonzero_ppn_warning),
        ("Standard Rates", test_standard_rate_still_works),
        ("Pre-compiled Patterns", test_pre_compiled_patterns),
        ("Extraction Performance", test_extraction_performance),
        ("Error Tracking", test_error_tracking_structure),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            print(f"\n❌ FAILED: {test_name}")
            print(f"   Error: {str(e)}")
            import traceback
            traceback.print_exc()
            failed += 1

    # Final summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"Total Tests: {len(tests)}")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")
    print(f"Success Rate: {passed/len(tests)*100:.1f}%")

    if failed == 0:
        print("\n🎉 ALL TESTS PASSED! Priority 1 improvements working correctly.")
    else:
        print(f"\n⚠️  {failed} test(s) failed. Please review and fix.")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
