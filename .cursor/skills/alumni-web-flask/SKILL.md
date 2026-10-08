---
name: alumni-web-flask
description: Flask + SQLite conventions for the KSE UNAND alumni website. Use when adding pages, admin CRUD, auth, CSS, deployment, or running the local server.
---

# Website Flask Alumni

Stack sengaja tipis: Flask, sqlite3, Jinja, CSS sendiri. Tanpa Node, tanpa ORM, tanpa CDN pihak ketiga.

Semua aset di-host sendiri sehingga CSP terkunci: `default-src 'self'` dengan `script-src`, `style-src`, dan `font-src` semuanya `'self'`, tanpa `'unsafe-inline'`. Satu-satunya host luar adalah tile OpenStreetMap di `img-src`. Konsekuensinya: jangan menambah `<style>` atau atribut `style=` di template dan jangan menautkan CDN — CSS lewat `app.css`, warna dinamis lewat `element.style` di JavaScript (CSSOM tidak terkena CSP). Berkas woff2 didaftarkan `mimetypes.add_type` karena Python 3.10 belum mengenalnya.

## Jalan (dev)

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy .env.example .env
# dev http lokal butuh SESSION_COOKIE_INSECURE=1 di .env
python -m alumni_web.cli setup
python run.py
```

Buka `http://127.0.0.1:5000`. `SECRET_KEY` wajib ≥32 karakter dan bukan placeholder, kalau tidak aplikasi menolak boot. Sandi pengurus hasil generate hanya dicetak sekali oleh CLI. Lupa sandi: `python -m alumni_web.cli reset-admin`.

## Produksi

`run.py` hanya untuk dev. Produksi lewat `wsgi.py` (memasang `ProxyFix`) dengan `gunicorn -c gunicorn.conf.py wsgi:app` atau `waitress-serve ... wsgi:app`. SQLite satu penulis → `workers = 1`, `threads = 4`.

Boot aplikasi **tidak** menyiapkan skema dan tidak mengimpor CSV. Itu tugas `python -m alumni_web.cli setup` sebagai langkah deploy. `find_csv()` hanya memindai `data/source/`; root proyek hanya dipindai oleh CLI eksplisit.

Backup: `python -m alumni_web.cli backup --out ...` (memakai API backup SQLite, aman saat server jalan). Jangan `cp` file `.db` bermode WAL.

## Letak kode

| Urusan | File |
|---|---|
| Route | `alumni_web/__init__.py`, keanggotaan di `alumni_web/portal.py` + `membership.py` |
| Schema + migrasi | `alumni_web/schema.sql`, `migrate()` di `db.py` |
| Rate limit / redirect / CSV cell / clamp | `alumni_web/security.py` |
| Konfigurasi + validasi secret | `alumni_web/config.py` |
| Boot/seed/backup | `alumni_web/boot.py`, `alumni_web/cli.py` |
| Entrypoint produksi | `wsgi.py`, `gunicorn.conf.py` |
| UI | `alumni_web/templates/`, `static/css/app.css` |
| Peta | `static/js/map.js` + `/api/map-points` |
| Statistik | `static/js/stats.js` + `static/vendor/chart.umd.min.js` |
| Jabatan KSE | `alumni_web/offices.py` (katalog kode), `alumni_web/org_layout.py` (template bagan), tabel `alumni_kse_roles` + `org_blueprints` / `org_units` / `org_seats`. Halaman `/struktur` mengikuti template periode; pengurus menyesuaikan di `/admin/struktur` tanpa membuat ulang dari nol. Pola dasar disunting di `/admin/template` (alias `/admin/acuan`). Anggota per divisi memakai `anggota_*`; sekbend memakai `sekbend_*`; `anggota_divisi` generik tidak dihapus. Kursi unit boleh `coordinator` dengan `parent_seat_id` pada anggota; `SCHEMA_VERSION` 8 membangun ulang CHECK SQLite. |
| Leaflet/Chart.js | `static/vendor/` (self-host, CSP `script-src 'self'`) |
| Font Fraunces/Figtree | `static/vendor/fonts/*.woff2` + `@font-face` di `app.css` |
| Lambang KSE/Unand | `static/img/` (web) dan `brand/` (asli) |

## Pola

- Form mutasi: CSRF `session['_csrf']` + field `csrf`, dibandingkan `compare_digest`, dirotasi saat login
- Auth: `session['user_id']`, role `admin` \| `alumni`, status `pending` \| `active` \| `disabled`
- Pendaftaran baru: `/daftar` membuat baris `is_listed = 0` + akun `pending`. Klaim data lama: `/klaim`. `/aktivasi` mengalihkan ke `/klaim` (POST lama email-only masih diterima).
- Pengurus meninjau di `/admin/tinjau` (setujui+tampilkan, permintaan email/sembunyi/reset/identitas, kerangka batch). Tolak pada `self_register` tersembunyi menghapus baris supaya email tidak terkunci.
- Profil sendiri: `/profil/saya` field lunak plus isian identitas yang masih kosong. Identitas yang sudah terisi dikunci. Ganti email dan sembunyi lewat antrean pengurus.
- Undangan: `/undang/<token>` (14 hari, hash SHA-256 di DB) tidak menampilkan WA/email/alamat; akun hasil undangan `pending`. Pemulihan alumni: `/pulih/<token>` setelah pengurus buat tautan; tidak menghidupkan akun `disabled`.
- Pengurus cadangan di `/admin/akun`. Lupa sandi pengurus: kode pemulih, `/pulih-pengurus`, atau `python -m alumni_web.cli reset-admin [--email ...]`.
- Ganti sandi: `/akun/sandi`, minimal 10 karakter (sama untuk daftar/klaim/undang), maksimal 128, sesi di-clear setelah ganti
- Query filter: `alumni_filters()` — jangan duplikasi SQL saring
- Parameter angka dari URL: `clamp_int` / `parse_cohort`, jangan `int()` mentah (SQLite tolak >64-bit → 500)
- Link paginasi: `filter_query()` saja. Jangan `request.args.to_dict()` ke `url_for(**query)` — kunci `_external`/`endpoint` bisa dibajak
- Konfirmasi hapus: atribut `data-confirm` + `static/js/confirm.js`. Jangan `onsubmit="return confirm(...)"` (CSP mematikannya).
- Tampilan fakultas/status: filter Jinja `faculty_name`, `status_name`

## UI

Arah visual: arsip cetak universitas. Kertas hangat, tinta gelap, hijau dan emas dari lambang. Fraunces untuk judul, Figtree untuk teks. Bukan dashboard SaaS, dan bukan halaman marketing.

Warna diambil langsung dari lambang: hijau Unand `#009048` (token `--green-mid`), emas `#c09030` (`--gold`). Turunan gelapnya `--green` `#0a6b3d` untuk tautan dan angka, `--green-deep` `#07472a` untuk judul, tombol, dan garis atas kartu. Emas hanya untuk garis dan label kecil, jangan untuk bidang besar.

Aset lambang di `alumni_web/static/img/`: `kse-sm.png` / `unand-sm.png` (128px, masthead, kaki, formulir), `kse-md.png` / `unand-md.png` (256px, lambang beranda), plus `kse.png` / `unand.png` (640px, cadangan). Jangan tautkan PNG 640px di template web. Macro di `templates/_brand.html`. Berkas asli di `brand/`. Semua PNG transparan, jadi aman di atas kertas. Jangan taruh lambang di atas bidang hijau tua — keduanya memuat hijau. Aset `/static` memakai `?v=mtime` dan `Cache-Control: immutable`.

Semua nilai visual ada sebagai token di `:root` (`app.css`): warna, spasi (`--s1`…`--s8`, kelipatan 4px), radius (`--r1` 3px, `--r2` 6px kontrol, `--r3` 10px panel). Jangan tulis hex atau px acak di aturan baru.

Aturan yang menahan tampilan tetap tenang:

- Beranda berurut: hero (judul, ajakan singkat, **kotak pencarian**) → ringkasan angka → indeks fakultas → contoh isi direktori → cara lain menelusuri → kesan pesan → ajakan daftar/klaim. Ajakan ditaruh paling akhir, sesudah orang melihat isinya, dan hanya tampil untuk tamu. Jarak antarbagian dipegang `.home-section`, bukan margin yang ditempel di tiap daftar.
- Beranda menyorot **Angkatan terbaru** (`MAX(cohort_year)`), tautan ke `/direktori?angkatan=…`. Jangan diganti jadi cuplikan acak atau judul “Sekilas isi direktori” — itu keputusan produk yang sudah dibatalkan.
- Ringkasan beranda tepat empat kotak (nama, fakultas, kota, rentang angkatan) supaya penuh di kisi 4 kolom. Jangan menambah kotak kelima.
- Angka bernilai 0 jangan dipajang di beranda. Kekosongan data tempatnya di `/statistik` pada bagian "Yang belum terdata".
- Satu aksen halaman (hijau-emas lambang). Grafik statistik memakai palet kategorikal `--chart-1`…`--chart-12` di `stats.js` (`colorFor()`) supaya fakultas/status/jabatan mudah dibedakan, dengan warna **stabil per kode** (Pertanian selalu warna yang sama), bukan pelangi Chart.js. Warna tidak pernah ditentukan dari nama orang. Swatch dinamis lewat `element.style`.
- Kartu orang dirender lewat macro `person_card` di `templates/_cards.html` — beranda dan direktori memakai macro yang sama, jangan menyalin markup kartu.
- Urutan isi kartu: nama, fakultas · jurusan, tempat kerja, lalu baris angkatan · kota yang didorong ke dasar kartu dengan `margin-top: auto`, supaya tepi bawah seluruh kisi sejajar. Teks panjang dipangkas `-webkit-line-clamp`.
- Nama yang terisi HURUF BESAR di formulir dirapikan saat tampil publik lewat filter `display_name`; tabel pengurus sengaja tetap memakai nilai asli agar bisa diperbaiki.
- Pemisah selalu hairline 1px. Untuk kisi (`.metrics`, `.facts`) pakai `gap: 1px` di atas latar `var(--line)` supaya tidak ada garis ganda di tepi.
- Tombol wajib berkelas: `.btn` (utama), `.btn-ghost` (sekunder), `.linkish` (aksi dalam tabel/nav). Selektor `button[type="submit"]:not([class])` hanya jaring aman.
- Label field kecil, huruf besar, `--ink-3`; kecuali `.check` yang tetap ukuran teks biasa.
- Hover mengubah garis atau latar, bukan menggeser posisi. Fokus keyboard memakai `:focus-visible` global.
- Grafik dibungkus `.chart-box` (tinggi tetap) dan legenda Chart.js dimatikan — daftar `.rank` di bawahnya yang jadi legenda lewat `.swatch`. Fakultas memakai batang mendatar; angkatan satu warna `--green`; donat jabatan memakai 4 ember `KSE_OFFICE_GROUPS`. Kota di statistik memakai ambang `MAP_MIN_COUNT` yang sama dengan peta.
- Antrean pengurus `/admin/tinjau` memakai `.nav-queue` (emas/`--warn-ink`), bukan `.btn` hijau, supaya tidak dikira halaman terpilih. `aria-current` Pengurus tidak menandai Tinjau. Tinjau tetap tautan langsung di navbar, jangan disembunyikan. Empat destinasi publik datar dan namanya sama dengan beranda: Direktori, Struktur, Statistik, Sebaran. Sesudah pemisah `.nav-gap`: Pengurus + Tinjau + Keluar, atau Profil saya + Keluar, atau Daftar + Masuk. Jangan mengelompokkan ke label samar (“Gambaran”, “Akun”). Kata sandi tinggal di profil/panel, bukan di navbar.
- Bagan pengurus satu pintu: tombol **Bagan** di `/admin` menuju `/admin/struktur`. Dua pekerjaan dipisah tab di dalam `.page-head` (`_org_switch.html`): Tahun kepengurusan (`/admin/struktur`) dan Template (`/admin/template`, alias `/admin/acuan`). Jangan menambah tautan silang di crumb, jangan menggabungkan chip tahun dan template di satu deret, dan jangan taruh tombol "sunting template" di halaman tahun. Identitas template (nama, catatan, jadikan bawaan, hapus) tinggal di dalam `.scope-bar` yang sedang dibuka. Tambah template tinggal di kotak pemilih. Tahun baru mengikuti template bawaan, bukan selalu slug `umum`. Banner tahun menawarkan *menerapkan* template yang sudah ada, bukan mengajak menyunting polanya. Menyunting template hanya berlaku untuk bagan yang *baru muncul*; tahun yang sudah punya riwayat jabatan dibekukan ke salinan (`capture_appeared_year`). Tombol Keluar memakai `.linkish.danger` (merah). Chip aktif wajib teks krim di atas hijau tua — jangan timpa `.chip-on` dengan warna tinta emas. Jarak antarbagian bagan dipegang `.org-stack`, bukan margin yang ditumpuk di `.org-nav-group` dan `.scope-bar`. Toolbar `/admin` dua deret: data (tambah/tempel/impor/ekspor) lalu Bagan, Kelola akun, Buku saku. Label akun **Kelola akun**, bukan “Akun”, supaya tidak bentrok dengan sesi pribadi.
- Editor bagan dikelompokkan mengikuti pohon publik (`unit_bands`): puncak (inti), divisi, sayap, dasar (PJ). Pengurus inti dan PJ tidak punya tombol geser unit. Jabatan ditukar dengan **sesama tingkat tampil** (`seat_display_band` + `parent_seat_id`), bukan dengan baris tetangga di daftar: ketua↔wakil, sekretaris↔bendahara, sesama pengurus, sesama koordinator, atau anggota di dalam tim yang sama. Setelah geser atau tambah jabatan, `pack_unit_seats` merapikan urutan: pimpinan, pengurus, **koordinator + anggotanya**, **anggota unit paling bawah**. Jangan menaruh jabatan baru di `MAX(sort_order)` mentah — itu yang membuat MnB jatuh di bawah anggota. Dua pengurus di sayap (Comdev) berjajar seperti `org_pair`, jadi labelnya “Geser kiri/kanan”. Jangan menampilkan tombol pada item yang di bagan publik tidak akan pindah.
- Satu pilihan **Tempat di bagan** (`place`): pimpinan, pengurus, koordinator baru, anggota unit, atau anggota di bawah koordinator tertentu. Jangan dua dropdown terpisah. Field form `place` (`member:<id>` untuk anggota tim). Setelah mutasi, redirect ke `#unit-` / `#seat-` dan `static/js/org-editor.js` mengembalikan gulir + `<details>` yang terbuka.
- Sayap (Comdev terpisah) memakai pola pohon yang sama dengan paguyuban: pimpinan dan pengurus sebagai simpul, lalu kartu koordinator berjajar di `.org-units` seperti kartu divisi. Jangan membungkus seluruh sayap dalam satu kotak `.org-wing`.
- Kartu bagan (divisi, koordinator, PJ) simetris: `flex` + `justify-content: center`, lebar tetap. Jangan `auto-fill`/`1fr` yang menaruh sisa baris di kiri.
- Formulir panjang di panel pengurus dilipat memakai `<details class="disclose">` (tanpa JS, aman CSP) supaya kartu unit dibaca dulu. Pilihan yang saling menggantikan dipisah jadi dua form dalam `.choice-pair` ("Cara 1 — pakai yang sudah ada" / "Cara 2 — buat baru"), bukan satu form dengan field yang harus dikosongkan sebagian.
- Peta: basemap diredam dengan filter CSS pada `.leaflet-tile-pane`, `fitBounds` dipanggil sebelum titik digambar, radius titik memakai akar kuadrat jumlah orang.

Pemeriksaan visual cepat tanpa Node: jalankan `run.py`, lalu `tools\shot.ps1 -Path /direktori -Out shots\x.png [-Width 500]` (lebar minimum jendela headless 500px, jadi cek mobile pakai 500). Skrip itu memakai Edge/Chrome headless dengan `--user-data-dir` sekali pakai; **tanpa itu** peramban menyajikan HTML dan CSS dari cache profil sebelumnya dan perubahan tampak seolah tidak jalan.

`run.py` menyalakan `jinja_env.auto_reload` sendiri. Kalau server dijalankan lewat cara lain tanpa debug, Jinja meng-cache template selama proses hidup: berkas sudah diubah tapi halaman tidak berubah. Restart dulu sebelum menyimpulkan perubahan tidak jalan.

## Tambah field alumni

1. Kolom di `schema.sql` **dan** langkah baru di `migrate()` (`db.py`), naikkan `SCHEMA_VERSION`
2. `record_from_form` / form admin
3. Klasifikasikan di `catalog.py`: `PUBLIC_FIELDS`, `CONTACT_FIELDS` (WA/email), `SENSITIVE_FIELDS` (alamat/DOB), atau `INTERNAL_FIELDS` — `tests/test_hardening.py` gagal kalau ada kolom tak terklasifikasi (`PII_FIELDS` = kontak+sensitif)
4. Jika kontak atau sensitif → tambah asersi di `tests/test_privacy.py`
5. Jika publik → kartu direktori / profil

Setiap langkah migrasi dijaga pemeriksaan `PRAGMA table_info` sendiri supaya aman dijalankan berulang. Jangan pernah menyarankan hapus `instance/alumni.db` di server.
