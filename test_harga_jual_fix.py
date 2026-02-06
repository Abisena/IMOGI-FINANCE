#!/usr/bin/env python3
"""
Test script untuk verifikasi ekstraksi Harga Jual dengan data real
"""
import sys
import os
import logging
from types import ModuleType

sys.path.insert(0, '.')
os.environ['FRAPPE_SITE'] = 'test_site'

# Mock frappe module
frappe_mock = ModuleType('frappe')

def logger_func(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(handler)
    return logger

def translate_func(text):
    return text

frappe_mock.logger = logger_func
frappe_mock._ = translate_func

sys.modules['frappe'] = frappe_mock

from imogi_finance.tax_invoice_ocr import parse_faktur_pajak_text

# Data dari screenshot user
text_from_user = """
No. | Kode Barang/Jasa | Nama Barang Kena Pajak / Jasa Kena Pajak | Harga Jual / Penggantian / Uang Muka / Termin (Rp)

1   | 120101           | Utility 01#01 / 2.IU.03 / DIRNOSAURUS di Grand Metropolitan Bekasi
                         Rp 1.049.485,00 x 1.00 Lainnya
                         Potongan Harga = Rp 0,00
                         PPnBM (0,00%) = Rp 0,00                           | 1.049.485,00

Harga Jual / Penggantian / Uang Muka / Termin                               1.049.485,00

Dikurangi Potongan Harga                                                     0,00

Dikurangi Uang Muka yang telah diterima

Dasar Pengenaan Pajak                                                        962.028,00

Jumlah PPN (Pajak Pertambahan Nilai)                                        115.443,00

Jumlah PPnBM (Pajak Penjualan atas Barang Mewah)                            0,00
"""

print("=" * 80)
print("TEST: Ekstraksi Harga Jual dari Data Real User")
print("=" * 80)
print()

result, confidence = parse_faktur_pajak_text(text_from_user)

print("\n" + "=" * 80)
print("HASIL EKSTRAKSI")
print("=" * 80)
print(f"Harga Jual: {result.get('harga_jual')}")
print(f"DPP       : {result.get('dpp')}")
print(f"PPN       : {result.get('ppn')}")
print(f"Confidence: {confidence:.2f}")
print("=" * 80)

# Verifikasi
print("\nVERIFIKASI:")
expected_hj = 1049485.0
expected_dpp = 962028.0
expected_ppn = 115443.0

errors = []

if result.get('harga_jual') == expected_hj:
    print(f"✅ Harga Jual BENAR: {result.get('harga_jual')} = {expected_hj}")
else:
    print(f"❌ Harga Jual SALAH: {result.get('harga_jual')} ≠ {expected_hj}")
    errors.append("Harga Jual")

if result.get('dpp') == expected_dpp:
    print(f"✅ DPP BENAR: {result.get('dpp')} = {expected_dpp}")
else:
    print(f"❌ DPP SALAH: {result.get('dpp')} ≠ {expected_dpp}")
    errors.append("DPP")

if result.get('ppn') == expected_ppn:
    print(f"✅ PPN BENAR: {result.get('ppn')} = {expected_ppn}")
else:
    print(f"❌ PPN SALAH: {result.get('ppn')} ≠ {expected_ppn}")
    errors.append("PPN")

print("\n" + "=" * 80)
if errors:
    print(f"❌ TEST GAGAL - Field yang salah: {', '.join(errors)}")
else:
    print("✅ TEST BERHASIL - Semua nilai benar!")
print("=" * 80)
