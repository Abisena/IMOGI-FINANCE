#!/usr/bin/env python3
"""
Debug script to test Harga Jual extraction with extensive logging
"""
import sys
import os
import logging
sys.path.insert(0, '.')
os.environ['FRAPPE_SITE'] = 'test_site'

# Mock frappe untuk testing
class MockFrappe:
    @staticmethod
    def logger(name):
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter('%(message)s'))
            logger.addHandler(handler)
        return logger

sys.modules['frappe'] = MockFrappe()

from imogi_finance.tax_invoice_ocr import parse_faktur_pajak_text

# Sample text from user's PDF transcript
text = """KOTA BEKASI, 30 Januari 2026
Ditandatangani secara elektronik
ANHAR SUDRADJAT
1.049.485,00
1.049.485,00
0,00
962.028,00
115.443,00
0,00"""

print("=" * 80)
print("TESTING HARGA JUAL EXTRACTION")
print("=" * 80)
print("\nInput text (signature section):")
print(text)
print("\n" + "=" * 80)
print("STARTING EXTRACTION...")
print("=" * 80)
print()

result = parse_faktur_pajak_text(text)

print("\n" + "=" * 80)
print("=== FINAL RESULT ===")
print("=" * 80)
print(f"Harga Jual: {result.get('harga_jual')}")
print(f"DPP: {result.get('dpp')}")
print(f"PPN: {result.get('ppn')}")
print("=" * 80)

# Verification
expected_harga_jual = 1049485.0
expected_dpp = 962028.0
expected_ppn = 115443.0

print("\n=== VERIFICATION ===")
if result.get('harga_jual') == expected_harga_jual:
    print(f"✓ Harga Jual CORRECT: {result.get('harga_jual')}")
else:
    print(f"✗ Harga Jual WRONG: {result.get('harga_jual')} (expected {expected_harga_jual})")

if result.get('dpp') == expected_dpp:
    print(f"✓ DPP CORRECT: {result.get('dpp')}")
else:
    print(f"✗ DPP WRONG: {result.get('dpp')} (expected {expected_dpp})")

if result.get('ppn') == expected_ppn:
    print(f"✓ PPN CORRECT: {result.get('ppn')}")
else:
    print(f"✗ PPN WRONG: {result.get('ppn')} (expected {expected_ppn})")
