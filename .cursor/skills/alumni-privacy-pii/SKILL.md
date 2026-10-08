---
name: alumni-privacy-pii
description: Privacy rules for KSE UNAND alumni PII (phone, email, address, date of birth). Use when adding routes, templates, APIs, exports, maps, logs, or tests that could leak personal data.
---

# Privasi PII Alumni

Kontak alumni adalah data pribadi. Asumsi kerja: **direktori publik terbatas**.

## Publik (tanpa login)

Boleh: nama, fakultas, jurusan, angkatan, pekerjaan, kota (bukan alamat), status, testimonial, jabatan paguyuban KSE.

## Setelah login

Pengurus (`admin`) dan pemilik profil: WhatsApp, email, alamat lengkap, tanggal lahir.

Alumni aktif lain: WhatsApp dan email saja. Alamat dan tanggal lahir tidak ikut.

`/daftar` membuat baris alumni **tidak publik** (`is_listed = 0`) plus akun `pending`. `/klaim` menempel ke baris `is_listed = 1`. `/aktivasi` mengalihkan ke `/klaim`. Email tersembunyi tidak boleh dikonfirmasi. Pengurus menyetujui di `/admin/tinjau`; IP dan waktu permintaan tampil di sana. Jangan aktifkan otomatis. Undangan membuat akun `pending`, bukan `active`.

`/lupa-sandi`, `/daftar`, `/klaim`, `/login`, dan `/aktivasi` harus balas sama (isi, status, atau durasi) antara data yang ada dan data asing.

## Jangan pernah

- Render PII di template lalu `display:none`
- Kirim PII di JSON publik (`/api/map-points` hanya kota + jumlah + nama publik setelah ambang `MAP_MIN_COUNT` ≥ 3, supaya satu titik tidak menunjuk satu orang)
- Log request body yang berisi WA/email (`app.logger` hanya menerima id user dan jumlah baris)
- Commit CSV asli, `instance/*.db`, `.env`
- Geocode sampai tingkat rumah; cukup centroid kota
- Balas berbeda (isi, status, **atau durasi**) antara email terdaftar dan email asing di `/login`, `/aktivasi`, `/daftar`, `/klaim`, dan `/lupa-sandi`

## Model gerbang

`strip_pii()` memakai **daftar-izin**, bukan daftar-larang: hasilnya hanya `PUBLIC_FIELDS`, ditambah `CONTACT_FIELDS` (WA/email) bila alumni/pengurus aktif, ditambah `SENSITIVE_FIELDS` (alamat/DOB) bila pengurus atau pemilik, ditambah `INTERNAL_FIELDS` bila role admin. Kolom baru otomatis tertutup sampai diklasifikasikan di `alumni_web/catalog.py`. `PII_FIELDS` adalah gabungan kontak+sensitif untuk tes klasifikasi.

Halaman untuk sesi login dikirim `Cache-Control: no-store, private`. Halaman orang dikirim `X-Robots-Tag: noindex` dan diblokir di `/robots.txt` kecuali `ALLOW_INDEXING=1`.

Export CSV penuh hanya POST `/admin/export.csv` + `@admin_required` + CSRF, dan setiap ekspor tercatat di tabel `audit_log` beserta jumlah baris. GET menampilkan halaman konfirmasi.

## Tes wajib

`tests/test_privacy.py` dan `tests/test_hardening.py` harus tetap hijau jika mengubah profil, API, atau export.

```bash
pytest tests/test_privacy.py tests/test_hardening.py
```

Profil publik gagal tes jika body mengandung nomor, email, alamat, DOB, atau kolom internal fixture. Kolom alumni yang tidak masuk `PUBLIC_FIELDS`/`PII_FIELDS`/`INTERNAL_FIELDS` juga menggagalkan tes.
