# Tax Invoice OCR Upload - Flow & Rules

Dokumen ini merangkum flow handling upload Faktur Pajak berbasis OCR di modul IMOGI Finance.

## 1) Entry point & validasi awal (Tax Invoice OCR Upload)

Saat dokumen **Tax Invoice OCR Upload** divalidasi:
- `fp_no` wajib ada.
- `tax_invoice_pdf` wajib ada.
- Tipe faktur (`tax_invoice_type`) di-resolve otomatis dari 3 digit prefix nomor faktur.
- `parse_status` tidak boleh diubah manual (hanya oleh sistem / tombol approve parse).
- Jika sudah ada item, summary validasi di-refresh.

## 2) Auto-detect PDF scan vs text layer (after insert)

Setelah insert:
- Sistem cek setting OCR aktif.
- Sistem mencoba ekstraksi token cepat dari PDF.
- Jika token minim (indikasi PDF scan tanpa text layer), sistem auto-queue OCR (`ocr_status` jadi `Queued`) dan menampilkan info di `validation_summary`.

## 3) OCR run (job queue + anti-duplicate)

OCR hanya boleh dijalankan via doctype **Tax Invoice OCR Upload**.
Rules utama:
- Harus `enable_tax_invoice_ocr = 1`.
- Provider OCR harus siap (Google Vision/Tesseract sesuai setting).
- Jika status sudah `Queued`/`Processing`, request OCR baru akan di-skip (anti duplicate queue).

## 4) Parsing line items (manual/auto)

Method `parse_line_items` akan:
- Menunggu OCR selesai (`Done`) untuk auto-triggered parse.
- Pakai parser unified (PyMuPDF untuk text-layer, fallback Vision JSON jika scan).
- Normalisasi item + validasi item/totals.
- Auto-deteksi kasus VAT-inclusive dan recalculate DPP/PPN.
- Menentukan `parse_status` (`Approved`/`Needs Review` dll).
- Menyimpan `validation_summary` + debug json.
- Jika `parse_status == Approved`, sistem auto-trigger verifikasi bisnis (`verify_tax_invoice`).

Jika OCR sudah `Done`, `on_update` auto-enqueue parsing background job dengan `job_name` deterministik agar tidak dobel.

## 5) Verifikasi bisnis Faktur Pajak

`verify_tax_invoice` melakukan rule penting:
- Cek duplikasi nomor faktur lintas dokumen (PI/ER/Branch ER/SI/Tax Invoice OCR Upload) jika setting block duplicate aktif.
- Cek NPWP faktur vs master party (supplier/customer).
- Cek kewajaran PPN vs expected PPN (dengan tolerance setting).
- Rule PPnBM: jika ada PPnBM, rate PPN harus 11%.
- Hasil: set status ke `Verified` atau `Needs Review`, plus notes.

## 6) Link ke dokumen transaksi (PI/ER/Branch ER)

Saat dokumen transaksi memilih `ti_tax_invoice_upload`:
- Upload harus `Verified`.
- Upload yang sama tidak boleh dipakai ulang di dokumen lain (kecuali skenario ER -> PI turunan yang memang terkait).
- Kalau user isi field manual faktur tapi belum pilih upload verified, sistem block.
- Saat link valid, sistem `sync_tax_invoice_upload` akan copy field faktur dari upload ke dokumen target.

## 7) Gate submit

### Purchase Invoice
Sebelum submit:
- Sync dulu dari upload OCR.
- Validasi link upload + NPWP match supplier.
- Jika setting mewajibkan verifikasi dan ada upload tapi belum `Verified`, submit diblok.

### Expense Request / Branch Expense Request
Sebelum submit:
- Ada validasi OCR-specific (NPWP, DPP, PPN, tolerance, type PPN).
- Kalau mismatch melewati tolerance, submit diblok.

## 8) Context picker di UI

Query picker upload untuk field `ti_tax_invoice_upload` di PI/ER/Branch ER menampilkan:
- hanya upload dengan `verification_status = Verified`.
- mengecualikan upload yang sudah dipakai dokumen lain.

## 9) Catatan: Tax Invoice Upload (non-OCR, khusus Sales Invoice sync)

Selain OCR upload, ada doctype **Tax Invoice Upload** untuk flow sinkronisasi ke Sales Invoice output tax fields.
Rules:
- Nomor faktur wajib 16 digit.
- NPWP wajib valid.
- PDF wajib ada dan file harus eksis.
- Nomor faktur unik di doctype tersebut.
- Jika linked ke Sales Invoice, sistem sync ke `out_fp_*` dan set status `Synced` / `Error`.

