---
name: alumni-csv-import
description: Import and clean the KSE UNAND Google Form CSV into SQLite. Use when importing alumni CSV/Excel, mapping form columns, deduping names, or changing normalize rules.
---

# Impor CSV Alumni

## Perintah

```bash
python -m alumni_web.cli setup
python -m alumni_web.cli import --csv "data/source/nama.csv"
python -m alumni_web.cli quality --dedupe          # simulasi
python -m alumni_web.cli quality --dedupe --apply  # terapkan
```

Pengurus juga bisa unggah di `/admin/import` (default: hanya tambah baris baru) atau unduh template kolom tetap di `/admin/import/template.csv`. Tempel daftar resmi di `/admin/tempel`. Google Form bukan alur tahunan.

Boot aplikasi **tidak** mengimpor apa pun. Impor otomatis hanya terjadi lewat `run.py` (dev) atau `cli setup`, dan `find_csv()` hanya memindai `data/source/` kecuali dipanggil dari CLI.

Setelah setiap impor besar, jalankan `cli quality` supaya bendera mutu ikut diperbarui.

## Mapping kolom

Jangan andalkan nama kolom persis (ada emoji di header WA). Gunakan `FIELD_NEEDLES` di `alumni_web/import_csv.py`.

Khusus:

- `gender` = kolom yang mengandung `hehe`, **bukan** "Nama Lengkap Uda/uni"
- `status` = header tepat `Status`
- timestamp form sering bernama `Column 1`
- `kse_roles` = kolom yang mengandung `jabatan`, `kepengurusan`, atau `struktur` (template: `jabatan_kse`). Isian bebas diurai ke `alumni_kse_roles` (satu baris per periode). Rentang `2022-2025` dipecah per tahun kepengurusan. `Anggota Humas` → `anggota_humas`; `Anggota Divisi` tanpa nama unit → `anggota_divisi` (tetap sah).

## Upsert

1. Cocokkan `email_normalized`
2. Kalau tidak ada, `phone_normalized` + `name_normalized`
3. Kalau tidak ada, insert
4. Nama sama tanpa email/WA → insert. Bendera `is_duplicate_suspect` hanya untuk nama yang sama di antara baris `is_listed = 1`. Setelah hapus/sembunyi, `refresh_duplicate_flags()` menghitung ulang.

Impor ulang tidak boleh menghidupkan kembali baris yang disembunyikan pengurus: `is_listed`, `source`, `created_at`, `is_duplicate_suspect`, `self_updated_at`, dan `hide_requested` ada di `SKIP_ON_UPDATE`. Baris dengan `self_updated_at` (alumni sudah mengisi sendiri) dilewati seluruhnya. Mode `insert_only=True` (default di form web) tidak memperbarui baris lama.

Jangan wipe tabel saat impor.

## Normalisasi

Semua pembersih ada di `alumni_web/normalize.py` + `catalog.py`.

- Telepon: `8…` / `08…` → `62…`
- Tahun: ambil tahun 19xx/20xx terakhir di string (`2011/2012` → 2012). "Belum lulus" / "Lupa" → NULL
- Angkatan `020` tidak jadi tahun valid; biarkan flag
- Isian "kosong" yang diketik responden (`-`, `_`, `.`, `n/a`, `tidak ada`) → NULL lewat `blank_if_junk()`

## Bendera mutu

- `skeleton` hanya untuk baris yang **benar-benar** cuma berisi nama
- `perlu_dilengkapi` untuk baris yang layak tampil tetapi belum punya angkatan atau kota. Tempat kerja **tidak** masuk syarat ini (banyak yang belum bekerja atau masih kuliah). Antrean pengurus: `/admin?mutu=perlu_dilengkapi`. Prioritas isi: kota dulu, lalu jabatan KSE (`/admin?mutu=tanpa_jabatan` dan `/admin?mutu=tanpa_kota`), baru sisanya.
- `kota_tidak_terpetakan` berarti domisili berisi alamat tanpa nama kota. **Jangan menebak kotanya** dari nama perumahan atau jalan; biarkan pengurus mengisi manual
- Nama kembar tidak pernah dihapus. `cli quality --dedupe` hanya menyembunyikan baris yang paling sedikit isinya (`is_listed = 0`), dan bisa dibatalkan dari form ubah

Setelah mengubah alias atau aturan bendera, jalankan `pytest tests/test_normalize.py tests/test_import.py tests/test_quality.py`.

## Privasi berkas

CSV sumber **jangan di-commit**. `*.csv` di gitignore kecuali `tests/fixtures/*.csv` (data palsu).
