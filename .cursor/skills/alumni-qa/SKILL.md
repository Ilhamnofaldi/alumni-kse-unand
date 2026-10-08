---
name: alumni-qa
description: QA checklist for the KSE UNAND alumni website covering privacy, import quality, auth, map, deployment, and responsive checks. Use before finishing a change, when testing, or when verifying CSV import.
---

# QA Alumni KSE

## Otomatis

```bash
pytest
```

Wajib lulus: privasi, normalisasi, impor fixture, konfigurasi, hardening, keanggotaan (`pytest`).

## Manual (setelah ubah UI/route)

1. Beranda menampilkan angka dan kartu tanpa WA/email.
2. `/direktori` saring fakultas + angkatan + q.
3. Profil tanpa login: ada ajakan masuk; tidak ada `@`, `62`, alamat jalan.
4. Login admin → profil menampilkan kontak, respons ber-`Cache-Control: no-store`.
5. `/peta` titik kota; popup dan panel menampilkan nama publik jika `count >= MAP_MIN_COUNT`; titik di bawah ambang tidak muncul; JSON tanpa WA/email/alamat/DOB.
6. `/statistik` chart berwarna per kategori; `/struktur` menampilkan pohon per periode (ketua dan wakil setara, sekretaris dan bendahara setara, sekbend di tiap divisi, PJ). Mode **Semua periode** mengurut nama di tiap jabatan dari yang menjabat lebih dulu sampai yang terkini, bukan abjad. Di divisi/sayap, koordinator tampil **di bawah pengurus sebagai kartu berjajar** (bukan tumpuk vertikal di dalam satu kotak sayap), tiap koordinator punya ember anggota sendiri, dan lead kedua tidak boleh hilang. Data lama `anggota_divisi` muncul di ember “belum spesifik”, bukan error. Periode yang disesuaikan di `/admin/struktur` boleh punya sayap (misalnya Comdev terpisah) tanpa mengubah template bawaan.
7. `/admin` CRUD + impor + export (GET konfirmasi, POST + CSRF mengunduh; export berisi PII, jangan diunggah publik). Daftar diurutkan dari yang terakhir diubah. Catatan mutu menyebut isian yang kurang; antrean chip (`?mutu=`) tetap ada untuk menyaring.
8. `/admin/struktur` hanya menyunting satu tahun kepengurusan. `/admin/template` (alias `/admin/acuan`) menyunting pola dasar: edit, tambah, jadikan bawaan. Menyunting template tidak boleh mengubah bagan tahun yang sudah tampil. Tahun baru mengikuti template bawaan. "Keluar" di navigasi berwarna merah. Tab Tahun/Template ada di kepala halaman, bukan menu kedua di crumb. Tombol geser tidak muncul pada pengurus inti/PJ sebagai unit, dan tidak menjanjikan ketua bisa jatuh ke bawah bendahara. Tempat di bagan = satu pilihan hierarki, bukan dua field samar. Setelah ubah, halaman kembali ke unit/jabatan yang disunting (bukan ke puncak). Jangan hanya satu `lead` — koordinator kedua+ harus tetap tampil. Di tiap unit, anggota unit selalu paling bawah; anggota tim menempel di bawah koordinatornya. Jangan sampai MnB atau jabatan baru menyelip di bawah anggota unit.
9. `/daftar` membuat baris tersembunyi + akun pending; `/klaim` menempel ke data lama; login ditolak sampai pengurus setujui di `/admin/tinjau`.
10. `/profil/saya` mengubah pekerjaan tanpa mengubah nama; profil publik tetap tanpa WA/email.
11. `/akun/sandi` mengganti sandi lalu memaksa login ulang. Pintunya dari Profil saya atau Panel pengurus, bukan dari navbar.
12. Lebar 360px: nav tidak pecah, kartu tetap kebaca. Empat destinasi publik tetap tautan langsung; jangan mengelompokkan ke label samar.

## Keamanan (jangan dilewat)

1. Form tanpa token CSRF → 400 dengan halaman error situs, bukan halaman Werkzeug.
2. `next=//evil.example` tidak redirect keluar.
3. `?page=99999999999999999999` dan `?angkatan=999…` → 200, bukan 500.
4. `?_external=1` dengan header `Host: evil.example` tidak memasukkan domain itu ke tautan halaman.
5. 12 login gagal dengan `X-Forwarded-For` yang diputar-putar tetap kena 429.
6. Durasi respons `/login` untuk email terdaftar dan email asing selisihnya kecil (< ~20%).
7. `/robots.txt` menutup `/admin`, `/api/`, `/alumni/`, `/direktori`.
8. CSP tidak memuat domain CDN; Leaflet/Chart.js dari `static/vendor/`.
9. Ekspor CSV: GET menampilkan konfirmasi; unduhan hanya POST + CSRF, lalu tercatat di tabel `audit_log`.

## Produksi

- `SECRET_KEY` ≥32 karakter, bukan placeholder; aplikasi harus menolak boot kalau tidak.
- `SESSION_COOKIE_INSECURE` tidak diset di server → cookie `Secure`.
- Jalan lewat `wsgi:app` (ProxyFix), bukan `run.py`; `workers = 1`.
- `python -m alumni_web.cli setup` dijalankan sebagai langkah deploy, bukan saat boot.
- `python -m alumni_web.cli backup` berhasil dan hasil restore pernah diuji.
- `/healthz` mengembalikan `{"status":"ok"}`.

## Mutu data (setelah impor CSV asli)

- ~327 baris, bukan 0
- Fakultas tidak meledak jadi 35 nilai mentah (harus terpetakan ke kode)
- Ada `is_duplicate_suspect` untuk nama kembar (2 pasang di data awal). Bendera hanya di antara `is_listed = 1`. Hapus atau sembunyikan salah satu harus melepas bendera saudara yang tersisa jika namanya sudah unik.
- Baris belum lengkap tetap ada. `perlu_dilengkapi` = belum ada angkatan atau kota, **bukan** karena tempat kerja kosong. Alumni `belum_bekerja` / `mahasiswa` tanpa kantor tidak boleh berpill “perlu dilengkapi” jika kota dan angkatannya sudah ada.
- Kolom "Catatan mutu" di `/admin` menyebut isian yang kurang (`quality_notes()`), bukan nama bendera internal. Baris bersih berbunyi "tidak ada catatan", bukan strip kosong dan bukan klaim "lengkap".
- `recompute_flags` tidak boleh menyentuh `updated_at`. Kalau tersentuh, semua baris yang benderanya berubah melompat ke puncak `/admin` dan panel tampak seperti baru disunting seluruhnya.
- Kota "Padang Panjang" ≠ "Padang"
- Setelah impor, `cli quality --dedupe` dijalankan agar bendera mutu ikut diperbarui

## Yang sering pecah

- Jinja `map(attribute=…)` pada `sqlite3.Row` (pakai dict/index)
- `NULLS LAST` di SQLite lama
- Header form "Nama … Uda/uni" tertukar jadi kolom gender
- `int()` mentah dari query string (SQLite menolak >64-bit → 500)
- `request.args.to_dict()` diteruskan ke `url_for(**query)`
- Di Windows, proses server lama bisa tetap memegang port 5000 dan menyajikan kode basi: pastikan tidak ada `python` lain sebelum menguji ulang
