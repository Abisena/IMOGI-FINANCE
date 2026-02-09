#!/usr/bin/env python3
"""
Test script for extract_summary_values() function.

Verifies that DPP and PPN are extracted correctly without swapping.
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
from imogi_finance.imogi_finance.parsers.normalization import extract_summary_values


def test_extract_summary_values():
    """Test extract_summary_values with various OCR text formats."""

    print("Testing extract_summary_values()\n")
    print("=" * 100)

    # Test Case 1: Standard format (from the bug report)
    print("\n🧪 Test Case 1: Standard format with all fields")
    print("-" * 100)

    ocr_text_1 = """
Harga Jual / Penggantian / Uang Muka / Termin 4.953.154,00
Dikurangi Potongan Harga 247.658,00
Dikurangi Uang Muka yang telah diterima
Dasar Pengenaan Pajak 4.313.371,00
Jumlah PPN (Pajak Pertambahan Nilai) 517.605,00
Jumlah PPnBM (Pajak Penjualan atas Barang Mewah) 0,00
"""

    result_1 = extract_summary_values(ocr_text_1)

    print("\n📊 Extracted values:")
    print(f"  Harga Jual:     Rp {result_1['harga_jual']:>15,.2f}")
    print(f"  Potongan Harga: Rp {result_1['potongan_harga']:>15,.2f}")
    print(f"  Uang Muka:      Rp {result_1['uang_muka']:>15,.2f}")
    print(f"  DPP:            Rp {result_1['dpp']:>15,.2f}")
    print(f"  PPN:            Rp {result_1['ppn']:>15,.2f}")
    print(f"  PPnBM:          Rp {result_1['ppnbm']:>15,.2f}")

    # Validation
    assert result_1['harga_jual'] == 4953154.0, f"Harga Jual mismatch: expected 4953154.0, got {result_1['harga_jual']}"
    assert result_1['potongan_harga'] == 247658.0, f"Potongan Harga mismatch"
    assert result_1['dpp'] == 4313371.0, f"❌ DPP mismatch: expected 4313371.0, got {result_1['dpp']}"
    assert result_1['ppn'] == 517605.0, f"❌ PPN mismatch: expected 517605.0, got {result_1['ppn']}"
    assert result_1['ppnbm'] == 0.0, f"PPnBM mismatch"

    # Critical validation: DPP should be greater than PPN
    assert result_1['dpp'] > result_1['ppn'], f"❌ CRITICAL: DPP ({result_1['dpp']}) should be > PPN ({result_1['ppn']})"

    print("\n✅ Test Case 1: PASSED - All values extracted correctly!")

    # Test Case 2: Values on next line
    print("\n\n🧪 Test Case 2: Values on next line (edge case)")
    print("-" * 100)

    ocr_text_2 = """
Dasar Pengenaan Pajak
4.313.371,00
Jumlah PPN (Pajak Pertambahan Nilai)
517.605,00
"""

    result_2 = extract_summary_values(ocr_text_2)

    print("\n📊 Extracted values:")
    print(f"  DPP: Rp {result_2['dpp']:>15,.2f}")
    print(f"  PPN: Rp {result_2['ppn']:>15,.2f}")

    assert result_2['dpp'] == 4313371.0, f"❌ DPP mismatch in Test 2"
    assert result_2['ppn'] == 517605.0, f"❌ PPN mismatch in Test 2"
    assert result_2['dpp'] > result_2['ppn'], f"❌ DPP should be > PPN in Test 2"

    print("\n✅ Test Case 2: PASSED - Multi-line format handled!")

    # Test Case 3: DPP and PPN on same line (the problematic case)
    print("\n\n🧪 Test Case 3: DPP and PPN on same line (bug scenario)")
    print("-" * 100)

    ocr_text_3 = """
Dasar Pengenaan Pajak 4.313.371,00  Jumlah PPN (Pajak Pertambahan Nilai) 517.605,00
"""

    result_3 = extract_summary_values(ocr_text_3)

    print("\n📊 Extracted values:")
    print(f"  DPP: Rp {result_3['dpp']:>15,.2f}")
    print(f"  PPN: Rp {result_3['ppn']:>15,.2f}")

    assert result_3['dpp'] == 4313371.0, f"❌ DPP mismatch in Test 3: expected 4313371.0, got {result_3['dpp']}"
    assert result_3['ppn'] == 517605.0, f"❌ PPN mismatch in Test 3: expected 517605.0, got {result_3['ppn']}"
    assert result_3['dpp'] > result_3['ppn'], f"❌ CRITICAL: DPP should be > PPN in Test 3"

    print("\n✅ Test Case 3: PASSED - Same-line format handled correctly!")

    # Test Case 4: Simulated swap scenario (what the auto-fix should catch)
    print("\n\n🧪 Test Case 4: Testing auto-correction if values somehow get swapped")
    print("-" * 100)

    # This would only happen if the extraction logic somehow extracted them backwards
    # The function should detect PPN > DPP and auto-swap
    ocr_text_4 = """
Jumlah PPN 4.313.371,00
Dasar Pengenaan Pajak 517.605,00
"""

    # Note: This simulates if someone mislabeled the fields in the document
    # The function should detect the values are wrong and swap them
    result_4 = extract_summary_values(ocr_text_4)

    print("\n📊 Extracted values (should be auto-corrected):")
    print(f"  DPP: Rp {result_4['dpp']:>15,.2f}")
    print(f"  PPN: Rp {result_4['ppn']:>15,.2f}")

    # The function should have detected ppn > dpp and swapped them
    assert result_4['dpp'] > result_4['ppn'], f"✅ Auto-correction worked: DPP ({result_4['dpp']}) > PPN ({result_4['ppn']})"

    print("\n✅ Test Case 4: PASSED - Auto-correction working!")

    # Test Case 5: Missing fields
    print("\n\n🧪 Test Case 5: Missing fields (should return 0.0)")
    print("-" * 100)

    ocr_text_5 = """
Some random text without any labels
"""

    result_5 = extract_summary_values(ocr_text_5)

    print("\n📊 Extracted values (should all be 0.0):")
    print(f"  Harga Jual: {result_5['harga_jual']}")
    print(f"  DPP:        {result_5['dpp']}")
    print(f"  PPN:        {result_5['ppn']}")

    assert result_5['harga_jual'] == 0.0, "Missing fields should return 0.0"
    assert result_5['dpp'] == 0.0, "Missing fields should return 0.0"
    assert result_5['ppn'] == 0.0, "Missing fields should return 0.0"

    print("\n✅ Test Case 5: PASSED - Missing fields handled gracefully!")

    # Summary
    print("\n" + "=" * 100)
    print("\n🎉 ALL TESTS PASSED!")
    print("\n✅ Summary:")
    print("  - DPP and PPN are extracted correctly (not swapped)")
    print("  - Same-line and multi-line formats both work")
    print("  - Auto-correction detects and fixes swapped values")
    print("  - Missing fields return 0.0 safely")
    print("  - All currency parsing works with Indonesian format")

    return True


if __name__ == "__main__":
    try:
        success = test_extract_summary_values()
        sys.exit(0 if success else 1)
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
