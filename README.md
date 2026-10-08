# Website Alumni KSE UNAND

Direktori web untuk paguyuban penerima beasiswa **Karya Salemba Empat** Universitas Andalas. Stack disengaja ringan: Flask + SQLite + Jinja, tanpa Node.

## Jalan di Windows (dev)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy .env.example .env
# isi SECRET_KEY di .env, lalu untuk dev http lokal tambahkan SESSION_COOKIE_INSECURE=1
python -m alumni_web.cli setup
python run.py
```

Buka http://127.0.0.1:5000

`python run.py` menyiapkan database dan mengimpor CSV Google Form dari folder ini atau `data/source/` jika database masih kosong. Debug hanya aktif bila `FLASK_DEBUG=1` dan `ALUMNI_ENV` bukan `production`.

## Akun pengurus

Atur `ADMIN_EMAIL` dan `ADMIN_PASSWORD` di `.env`. Jika `ADMIN_PASSWORD` kosong, hanya `python -m alumni_web.cli setup` yang boleh membuat akun — sandi acak dicetak sekali ke terminal dan tidak disimpan ke berkas mana pun.

Alumni **baru** daftar di `/daftar` (nama belum tampil sampai disetujui). Yang sudah tercatat **klaim** di `/klaim` (`/aktivasi` mengalihkan ke sana). Pengurus meninjau di `/admin/tinjau`. Setelah akun aktif, alumni lain melihat WhatsApp dan email; alamat dan tanggal lahir hanya untuk pemilik dan pengurus. Pekerjaan/kota diisi ulang di `/profil/saya`.

Lupa sandi alumni: `/lupa-sandi` → pengurus membuat tautan di tinjau. Lupa sandi pengurus:

```powershell
python -m alumni_web.cli reset-admin              # cetak sandi acak baru
python -m alumni_web.cli reset-admin --email "..." --password "..."
```

Atau kode pemulih dari `/admin/akun` lalu `/pulih-pengurus`. `ADMIN_PASSWORD` di `.env` **tidak** mengubah sandi yang sudah ada. Sediakan minimal dua pengurus.

## Isi

- Direktori + saringan, profil, statistik, peta sebaran tingkat kota
- Alumni: daftar, klaim, profil sendiri, lupa sandi lewat pengurus
- Admin: tinjau keanggotaan, tempel daftar, undangan, pengurus cadangan, CRUD, impor/ekspor CSV, antrean mutu data
- `/healthz` untuk monitor, `/robots.txt` menutup halaman orang dari mesin pencari
- Buku saku PDF: `alumni_web/static/docs/pedoman-pengguna.pdf` (alumni, tautan di kaki situs) dan `pedoman-pengurus.pdf` (pengurus, tautan di panel). Bangun ulang: `python tools/handbook/build.py`

## Mutu data

Panel pengurus punya antrean kerja berbentuk chip: **Perlu dilengkapi**, **Nama kembar**, **Tanpa angkatan**, **Tanpa kota**, **Kota tidak terpetakan**, **Tersembunyi**. Setiap chip adalah saringan (`/admin?mutu=…`).

```powershell
python -m alumni_web.cli quality --dedupe            # simulasi, tidak menyimpan
python -m alumni_web.cli quality --dedupe --apply    # terapkan
```

Perintah itu mengosongkan isian sampah (`-`, `_`, `n/a`), menghitung ulang bendera mutu, dan untuk nama kembar **menyembunyikan** baris yang paling sedikit isinya (`is_listed = 0`) — tidak menghapus apa pun, dan bisa dibatalkan dari form ubah. Jalankan setelah setiap impor besar.

Kota yang gagal dipetakan sengaja tidak ditebak dari nama perumahan atau jalan; isi manual lewat chip **Kota tidak terpetakan**.

## Tes

```powershell
pytest
```

## Produksi

### 1. Siapkan environment

`.env` di server, minimal:

```
SECRET_KEY=<48+ karakter acak>
ADMIN_EMAIL=pengurus@domain.anda
ADMIN_PASSWORD=<sandi kuat, ganti setelah login pertama>
MAP_MIN_COUNT=3
ALUMNI_ENV=production
```

Jangan set `SESSION_COOKIE_INSECURE` di server: cookie sesi wajib `Secure`. Aplikasi menolak boot jika `SECRET_KEY` kosong, masih placeholder, atau kurang dari 32 karakter.

### 2. Siapkan database (sekali, bukan saat boot)

```bash
pip install -r requirements-prod.txt
python -m alumni_web.cli setup
python -m alumni_web.cli import --csv /path/ke/form.csv   # bila perlu
```

Boot aplikasi sengaja tidak menyentuh skema maupun mengimpor CSV. Itu mencegah dua worker menyiapkan database bersamaan dan mencegah CSV yang tergeletak di direktori aplikasi terimpor diam-diam. Setelah merilis pembaruan bagan kepengurusan, jalankan `setup` sekali lagi di server agar tabel template (`org_blueprints`) terbuat; data alumni yang sudah ada tidak diimpor ulang.

### 3. Jalankan lewat WSGI

Linux:

```bash
gunicorn -c gunicorn.conf.py wsgi:app
```

Windows:

```powershell
waitress-serve --listen=127.0.0.1:8000 --threads=4 wsgi:app
```

`wsgi.py` memasang `ProxyFix` untuk satu reverse proxy. Tanpa itu `remote_addr` selalu IP proxy dan pembatas laju login jadi satu bucket global. SQLite hanya menerima satu penulis, jadi pakai **satu proses dengan beberapa thread** (`workers = 1`, `threads = 4`), bukan banyak worker.

### 4. Reverse proxy + HTTPS

HTTPS wajib: cookie sesi adalah kunci ke seluruh PII. Contoh Nginx:

```nginx
server {
  listen 80;
  server_name alumni.domain.anda;
  return 301 https://$host$request_uri;
}

server {
  listen 443 ssl http2;
  server_name alumni.domain.anda;

  ssl_certificate     /etc/letsencrypt/live/alumni.domain.anda/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/alumni.domain.anda/privkey.pem;

  client_max_body_size 8m;

  location /healthz { proxy_pass http://127.0.0.1:8000; allow 127.0.0.1; deny all; }

  location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }
}
```

Aplikasi mengirim HSTS hanya saat request sudah https, jadi pasang sertifikat lebih dulu.

### 5. systemd

```ini
[Unit]
Description=Alumni KSE UNAND
After=network.target

[Service]
User=alumni
WorkingDirectory=/srv/alumni
EnvironmentFile=/srv/alumni/.env
UMask=0077
ExecStart=/srv/alumni/.venv/bin/gunicorn -c gunicorn.conf.py wsgi:app
Restart=always

[Install]
WantedBy=multi-user.target
```

`UMask=0077` menjaga `instance/alumni.db` tidak terbaca akun lain di server.

### 6. Backup dan restore

Database adalah satu-satunya salinan data pribadi anggota. Mode WAL aktif, jadi jangan `cp` file yang sedang dipakai — pakai perintah backup yang konsisten saat server jalan:

```bash
python -m alumni_web.cli backup --out /var/backups/alumni/alumni-$(date +%F).db
chmod 600 /var/backups/alumni/*.db
find /var/backups/alumni -name '*.db' -mtime +30 -delete
```

Restore: hentikan layanan, ganti `instance/alumni.db` dengan berkas backup (hapus `-wal`/`-shm` yang tertinggal), jalankan layanan. **Uji restore sekali sebelum go-live.**

### 7. Setelah go-live

- Login pertama, lalu ganti sandi pengurus di `/akun/sandi`.
- `instance/logs/app.log` memuat login, ekspor PII, impor, dan aksi akun (rotasi 5 × 1 MB).
- Tabel `audit_log` menyimpan jejak yang sama di database, termasuk siapa mengekspor berapa baris.
- Kerjakan antrean data di `/admin`: chip **Perlu dilengkapi**, **Nama kembar**, **Kota tidak terpetakan**.

## Privasi

Publik hanya melihat nama, fakultas, jurusan, angkatan, pekerjaan, kota, status, dan testimonial. WA, email, alamat, dan tanggal lahir butuh akun aktif. Peta memakai centroid kota dengan ambang `MAP_MIN_COUNT` agar satu titik tidak menunjuk satu orang. Halaman orang dikirim dengan `noindex` dan diblokir di `robots.txt` kecuali `ALLOW_INDEXING=1`.

Jangan pernah commit CSV asli, `instance/alumni.db`, atau `.env`.
