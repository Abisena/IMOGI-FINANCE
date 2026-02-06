#!/usr/bin/env python3
"""
Script untuk mengekstrak nilai Harga Jual dari tabel Faktur Pajak
Mengambil nilai dari baris "Harga Jual / Penggantian / Uang Muka / Termin"
"""
import re


def parse_idr_amount(value: str) -> float:
    """
    Parse string IDR menjadi float.
    Contoh: "1.049.485,00" -> 1049485.0
    """
    if not value:
        return 0.0

    # Hapus whitespace
    value = value.strip()

    # Bersihkan format IDR: titik sebagai separator ribuan, koma sebagai desimal
    # 1.049.485,00 -> 1049485.00
    value = value.replace('.', '')  # Hapus separator ribuan
    value = value.replace(',', '.')  # Ubah koma desimal jadi titik

    try:
        return float(value)
    except ValueError:
        return 0.0


def extract_harga_jual_from_table(text: str) -> dict:
    """
    Ekstrak nilai Harga Jual dari tabel Faktur Pajak.

    Returns:
        dict dengan keys:
            - harga_jual: nilai float
            - harga_jual_formatted: string format Indonesia (Rp)
            - harga_jual_juta: nilai dalam jutaan rupiah
    """
    # Pattern untuk mencari label dan nilainya
    # Mencari "Harga Jual / Penggantian / Uang Muka / Termin" diikuti nilai
    patterns = [
        # Pattern 1: Langsung setelah label (untuk format tabel ringkasan)
        r'Harga\s+Jual\s*/\s*Penggantian\s*/\s*Uang\s+Muka\s*/\s*Termin\s+([\d\.\,]+)',
        # Pattern 2: Dengan spasi lebih banyak
        r'Harga\s+Jual\s+/\s+Penggantian\s+/\s+Uang\s+Muka\s+/\s+Termin\s+([\d\.\,]+)',
        # Pattern 3: Dengan newline atau whitespace di antara
        r'Harga\s+Jual\s*/\s*Penggantian\s*/\s*Uang\s+Muka\s*/\s*Termin\s*\n?\s*([\d\.\,]+)',
        # Pattern 4: Dengan (Rp) di header kolom - cari nilai setelah label
        r'Harga\s+Jual\s*/\s*Penggantian\s*/\s*Uang\s+Muka\s*/\s*Termin.*?\n.*?([\d\.\,]+)',
    ]

    harga_jual_value = None

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            amount_str = match.group(1).strip()
            harga_jual_value = parse_idr_amount(amount_str)
            if harga_jual_value > 10000:  # Minimal 10rb untuk filter out false positive
                break

    if harga_jual_value is None or harga_jual_value == 0:
        return {
            'harga_jual': 0.0,
            'harga_jual_formatted': 'Rp 0',
            'harga_jual_juta': 0.0,
            'error': 'Nilai Harga Jual tidak ditemukan'
        }

    # Format hasil
    return {
        'harga_jual': harga_jual_value,
        'harga_jual_formatted': f'Rp {harga_jual_value:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.'),
        'harga_jual_juta': round(harga_jual_value / 1_000_000, 3),  # Dalam juta
    }


# ============================================================================
# CONTOH PENGGUNAAN
# ============================================================================

if __name__ == '__main__':
    # Contoh 1: Dari gambar yang Anda berikan
    sample_text_1 = """
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
    print("CONTOH 1: Ekstraksi dari Tabel Faktur Pajak")
    print("=" * 80)
    result = extract_harga_jual_from_table(sample_text_1)

    print(f"\n✅ Hasil Ekstraksi:")
    print(f"   Harga Jual (float)    : {result['harga_jual']}")
    print(f"   Harga Jual (formatted): {result['harga_jual_formatted']}")
    print(f"   Harga Jual (jutaan)   : {result['harga_jual_juta']} juta")

    # Verifikasi
    print(f"\n✅ Verifikasi:")
    expected = 1049485.0
    if result['harga_jual'] == expected:
        print(f"   ✓ BENAR! Nilai yang diambil: {result['harga_jual']}")
        print(f"   ✓ Dalam jutaan: {result['harga_jual_juta']:.3f} juta rupiah")
    else:
        print(f"   ✗ SALAH! Nilai: {result['harga_jual']}, Expected: {expected}")

    # Contoh 2: Format lebih sederhana
    print("\n" + "=" * 80)
    print("CONTOH 2: Format Lebih Sederhana")
    print("=" * 80)

    sample_text_2 = """
    Harga Jual / Penggantian / Uang Muka / Termin    2.500.000,00
    Dikurangi Potongan Harga                         0,00
    Dasar Pengenaan Pajak                            2.272.727,00
    """

    result2 = extract_harga_jual_from_table(sample_text_2)
    print(f"\n✅ Hasil Ekstraksi:")
    print(f"   Harga Jual (float)    : {result2['harga_jual']}")
    print(f"   Harga Jual (formatted): {result2['harga_jual_formatted']}")
    print(f"   Harga Jual (jutaan)   : {result2['harga_jual_juta']} juta")

    # Contoh 3: Penggunaan direct parsing
    print("\n" + "=" * 80)
    print("CONTOH 3: Direct Parsing String Nilai")
    print("=" * 80)

    nilai_string = "1.049.485,00"
    nilai_float = parse_idr_amount(nilai_string)
    nilai_juta = nilai_float / 1_000_000

    print(f"\n✅ String input: '{nilai_string}'")
    print(f"   Parsed float : {nilai_float}")
    print(f"   Dalam juta   : {nilai_juta:.3f} juta")

    # Contoh 4: Integrasi dengan existing code
    print("\n" + "=" * 80)
    print("CONTOH 4: Cara Menggunakan di Code Anda")
    print("=" * 80)
    print("""
    # Di code Anda, setelah mendapat text dari OCR atau parsing PDF:

    text_from_pdf = "... text dari PDF ..."
    result = extract_harga_jual_from_table(text_from_pdf)

    if 'error' not in result:
        harga_jual = result['harga_jual']  # 1049485.0
        harga_juta = result['harga_jual_juta']  # 1.049

        print(f"Harga Jual: Rp {harga_jual:,.0f}")
        print(f"Atau: {harga_juta:.3f} juta rupiah")
    else:
        print(f"Error: {result['error']}")
    """)

    print("\n" + "=" * 80)
    print("✅ Script selesai!")
    print("=" * 80)
