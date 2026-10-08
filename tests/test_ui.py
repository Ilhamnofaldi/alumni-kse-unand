from __future__ import annotations

from alumni_web.db import get_db, utcnow


def _insert(app, **kolom):
    now = utcnow()
    data = {
        "full_name": "Tanpa Nama",
        "name_normalized": "tanpa nama",
        "faculty_code": "teknik",
        "is_listed": 1,
        "data_quality_flags": "[]",
    }
    data.update(kolom)
    with app.app_context():
        db = get_db()
        kunci = ", ".join(data)
        tanya = ", ".join("?" for _ in data)
        db.execute(
            f"INSERT INTO alumni ({kunci}, created_at, updated_at) VALUES ({tanya}, ?, ?)",
            list(data.values()) + [now, now],
        )
        db.commit()


def test_nama_huruf_besar_dirapikan_saat_tampil(app, client):
    _insert(app, full_name="BUDI SANTOSO HARAHAP", name_normalized="budi santoso harahap")
    body = client.get("/direktori").get_data(as_text=True)
    assert "Budi Santoso Harahap" in body
    assert "BUDI SANTOSO HARAHAP" not in body


def test_nama_campuran_tidak_diubah(app, client):
    _insert(app, full_name="Fachrum de Nisa", name_normalized="fachrum de nisa")
    body = client.get("/direktori").get_data(as_text=True)
    assert "Fachrum de Nisa" in body


def test_kartu_tanpa_angkatan_dan_kota_memakai_teks_netral(app, client):
    _insert(app, full_name="Sunyi Data", name_normalized="sunyi data")
    body = client.get("/direktori").get_data(as_text=True)
    assert "Belum terdata" in body


def test_lambang_paguyuban_dan_unand_tersaji(client):
    for berkas in (
        "img/kse.png",
        "img/kse-md.png",
        "img/kse-sm.png",
        "img/unand.png",
        "img/unand-md.png",
        "img/unand-sm.png",
        "img/favicon.png",
    ):
        res = client.get(f"/static/{berkas}")
        assert res.status_code == 200, berkas
        assert res.headers["Content-Type"].startswith("image/")


def test_font_di_host_sendiri(client):
    for berkas in (
        "vendor/fonts/figtree-latin.woff2",
        "vendor/fonts/figtree-latin-ext.woff2",
        "vendor/fonts/fraunces-latin.woff2",
        "vendor/fonts/fraunces-latin-ext.woff2",
    ):
        res = client.get(f"/static/{berkas}")
        assert res.status_code == 200, berkas
        assert res.headers["Content-Type"] == "font/woff2", berkas

    css = client.get("/static/css/app.css").get_data(as_text=True)
    assert css.count("@font-face") == 4
    assert "fonts.gstatic.com" not in css


def test_halaman_pengurus_keanggotaan(client):
    from tests.conftest import login_admin

    login_admin(client)
    assert client.get("/admin/tinjau").status_code == 200
    assert client.get("/admin/tempel").status_code == 200
    assert client.get("/admin/akun").status_code == 200
    body = client.get("/admin").get_data(as_text=True)
    assert "Tinjau" in body
    assert "Tempel daftar" in body
    assert "js/confirm.js" in body
    assert "onsubmit=" not in body
    assert "Terapkan" in body
    assert ">Saring<" not in body


def test_halaman_masuk_memuat_tautan_keanggotaan(client):
    res = client.get("/login")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "Kesalahan 500" not in body
    assert 'href="/daftar"' in body
    assert 'href="/klaim"' in body
    assert 'href="/lupa-sandi"' in body


def test_nav_tamu_memuat_daftar(client):
    body = client.get("/").get_data(as_text=True)
    assert 'class="mark-kicker">Direktori Alumni</span>' in body
    assert 'href="/daftar"' in body
    assert 'href="/login"' in body
    assert 'href="/struktur"' in body
    assert client.get("/daftar").status_code == 200
    assert client.get("/struktur").status_code == 200
    assert client.get("/peta").status_code == 200
    assert client.get("/klaim").status_code == 200
    assert client.get("/lupa-sandi").status_code == 200
    assert client.get("/undang/bukan-token").status_code == 404


def test_statistik_palet_dan_halaman_struktur(client):
    css = client.get("/static/css/app.css").get_data(as_text=True)
    assert "--chart-1:" in css
    assert "--chart-12:" in css
    js = client.get("/static/js/stats.js").get_data(as_text=True)
    assert "function colorFor" in js
    assert "function ramp" not in js
    # Sebaran angkatan ikut berwarna-warni, tidak lagi satu hijau seragam.
    assert 'kind === "cohort"' not in js
    stats = client.get("/statistik").get_data(as_text=True)
    assert 'id="chart-office"' in stats
    struktur = client.get("/struktur").get_data(as_text=True)
    assert "Pengurus inti" in struktur
    assert "Ketua Paguyuban" in struktur
    assert "Wakil Ketua" in struktur
    assert "Sekbend" in struktur
    assert "Belum ada nama." in struktur
    assert "Sesuaikan bagan" not in struktur
    assert 'class="org-tree"' in struktur
    assert "org-pair" in struktur
    assert "org-node-head" in struktur
    assert "Anggota Divisi (belum spesifik)" not in struktur
    # Nama unit tidak boleh tertulis dua kali di satu kartu: judul kartu
    # menyebut unitnya, sub-bloknya menyebut jabatan.
    assert "<h4>Koordinator</h4>" in struktur
    assert "<h4>Humas</h4>" not in struktur
    assert "PJ Universitas" in struktur
    # Bagannya sudah menjelaskan sendiri, jadi narasi susunannya dibuang.
    assert "sejajar di pimpinan" not in struktur
    peta = client.get("/peta").get_data(as_text=True)
    assert "data-map-cities" in peta
    assert "081234567890" not in peta


def test_beranda_memuat_kedua_lambang(client):
    body = client.get("/").get_data(as_text=True)
    assert "img/kse-md.png" in body
    assert "img/unand-md.png" in body
    assert "img/kse-sm.png" in body
    assert "loading=\"lazy\"" in body
    assert "Lambang Universitas Andalas" in body
    assert "Direktori Alumni Penerima Beasiswa Karya Salemba Empat" in body
    assert "Telusuri menurut fakultas" in body
    assert "Rentang angkatan" in body
    assert 'class="explore"' in body
    assert 'class="hero-search"' in body


def test_beranda_menyorot_angkatan_terbaru(app, client):
    """Sorotan beranda dikunci ke angkatan termuda, bukan nama acak."""
    _insert(app, full_name="Yunior Baru", name_normalized="yunior baru", cohort_year=2022)
    _insert(app, full_name="Senior Lama", name_normalized="senior lama", cohort_year=2001)
    body = client.get("/").get_data(as_text=True)
    assert "Angkatan terbaru" in body
    assert "Sekilas isi direktori" not in body
    assert "Sudah bisa dikenalkan" not in body
    assert 'href="/direktori?angkatan=2022"' in body
    assert "Yunior Baru" in body
    assert "Senior Lama" not in body


def test_beranda_mengajak_tamu_mendaftar(client):
    """Ajakan mendaftar harus ada untuk tamu, karena itu satu-satunya jalan
    masuk bagi alumni yang namanya belum tercatat."""
    body = client.get("/").get_data(as_text=True)
    assert "Nama Anda belum ada di sini?" in body
    assert 'href="/daftar"' in body
    assert 'href="/klaim"' in body


def test_beranda_menyembunyikan_ajakan_daftar_setelah_masuk(client):
    """Yang sudah masuk tidak perlu lagi diajak mendaftar atau mengklaim."""
    from tests.conftest import login_admin

    login_admin(client)
    body = client.get("/").get_data(as_text=True)
    assert 'class="invite"' not in body
    assert "Nama Anda belum ada di sini?" not in body
    assert 'href="/klaim"' not in body
    assert 'href="/daftar"' not in body
    # Isi direktori tetap tersaji, jadi yang hilang hanya ajakannya.
    assert "Angkatan terbaru" in body
    assert "Keluar" in body
    assert 'class="linkish danger"' in body


def test_kesan_pesan_jadi_carousel(app, client):
    """Kutipan tampil satu per satu, dan tanpa JavaScript masih bisa digeser."""
    pesan = (
        "Beasiswa KSE membuat saya bisa menyelesaikan kuliah dan berani "
        "mencoba banyak hal baru bersama teman-teman paguyuban."
    )
    for i in range(2):
        _insert(
            app,
            full_name=f"Penulis Pesan {i}",
            name_normalized=f"penulis pesan {i}",
            testimonial=pesan,
        )
    body = client.get("/").get_data(as_text=True)
    assert "data-carousel" in body
    assert body.count('class="carousel-slide"') == 2
    assert 'class="quotes"' not in body
    assert "js/carousel.js" in body

    js = client.get("/static/js/carousel.js").get_data(as_text=True)
    assert js.count("prefers-reduced-motion") == 1
    # Gerakan pelan terus-menerus memakai requestAnimationFrame, dan isi
    # petak digandakan supaya putarannya tanpa ujung.
    assert "requestAnimationFrame" in js
    assert "cloneNode" in js
    # Regresi: posisi geser tidak boleh dibaca dari offsetLeft — di dalam
    # petak grid yang bisa digulir, Chromium menggeser nilainya mengikuti
    # scrollLeft sehingga scrollTo selalu kembali ke slide pertama.
    assert ".offsetLeft" not in js
    assert "getBoundingClientRect" in js
    css = client.get("/static/css/app.css").get_data(as_text=True)
    assert "scroll-snap-type" in css


def test_statistik_lembar_agregat(client):
    import json

    body = client.get("/statistik").get_data(as_text=True)
    assert 'id="chart-office"' in body
    assert "Pernah jadi pengurus" in body
    assert "Tanpa fakultas" in body
    assert "Kota tempat alumni tinggal" in body
    assert "chart-box-tall" in body
    assert "kota=Padang" not in body
    assert "belum mencapai jumlah itu" in body
    payload = json.loads(body.split('id="stats-data">', 1)[1].split("</script>", 1)[0])
    assert "Aisyah" not in str(payload)
    assert "081234567890" not in str(payload)
    assert "aisyah.uji@" not in str(payload)
    assert set(payload["office"]["keys"]) <= {"core", "lead", "member", "pj"}
    assert len(payload["office"]["keys"]) <= 4
    js = client.get("/static/js/stats.js").get_data(as_text=True)
    assert "function colorFor" in js
    assert "Sekretaris" in js
    assert "indexAxis" in js


def test_statistik_jabatan_orang_unik_per_kelompok(app, client):
    import json

    from alumni_web.offices import add_roles

    with app.app_context():
        db = get_db()
        add_roles(db, 1, {"office_code": "ketua", "period_start": 2023, "period_end": 2024})
        add_roles(db, 1, {"office_code": "sekretaris", "period_start": 2022, "period_end": 2023})
        db.commit()
    payload = json.loads(
        client.get("/statistik").get_data(as_text=True).split('id="stats-data">', 1)[1].split("</script>", 1)[0]
    )
    core_index = payload["office"]["keys"].index("core")
    assert payload["office"]["data"][core_index] == 1


def test_navbar_nama_pekerjaan_langsung(client):
    from tests.conftest import login_admin

    guest = client.get("/").get_data(as_text=True)
    nav = guest.split('<nav class="nav"', 1)[1].split("</nav>", 1)[0]
    assert "Direktori" in nav
    assert "Struktur" in nav
    assert "Statistik" in nav
    assert "Sebaran" in nav
    assert "Gambaran" not in nav
    assert "Akun" not in nav
    assert "Daftar" in nav
    assert "Masuk" in nav
    assert 'class="nav-fold"' not in nav
    assert 'class="nav-gap"' in nav
    assert 'href="/statistik"' in nav
    assert 'href="/peta"' in nav

    login_admin(client)
    body = client.get("/").get_data(as_text=True)
    nav = body.split('<nav class="nav"', 1)[1].split("</nav>", 1)[0]
    assert "Gambaran" not in nav
    assert "Akun" not in nav
    assert "Kata sandi" not in nav
    assert "Pengurus" in nav
    assert "Keluar" in nav
    assert "Profil saya" not in nav
    assert 'class="nav-fold"' not in nav
    assert 'class="nav-queue"' in nav
    assert 'class="nav-queue" href="/admin/tinjau"' in nav


def test_tombol_tinjau_bukan_hijau_terpilih(client):
    from tests.conftest import login_admin

    guest = client.get("/").get_data(as_text=True)
    assert "/admin/tinjau" not in guest
    assert "nav-queue" not in guest
    login_admin(client)
    admin = client.get("/admin").get_data(as_text=True)
    assert 'class="nav-queue"' in admin
    assert 'href="/admin/tinjau"' in admin
    assert 'class="btn" href="/admin/tinjau"' not in admin
    assert 'class="nav-cta"' not in admin
    direktori = client.get("/direktori").get_data(as_text=True)
    assert 'class="nav-queue"' in direktori
    assert 'href="/admin/tinjau"' in direktori
    assert 'href="/admin/tinjau" aria-current="page"' not in direktori
    tinjau = client.get("/admin/tinjau").get_data(as_text=True)
    assert 'class="nav-queue"' in tinjau
    assert 'aria-current="page"' in tinjau
    css = client.get("/static/css/app.css").get_data(as_text=True)
    assert ".nav a.nav-queue" in css
    assert "--warn-ink" in css


def test_buku_saku_alumni_di_kaki_situs(client):
    body = client.get("/").get_data(as_text=True)
    assert "Buku saku alumni" in body
    assert "/static/docs/pedoman-pengguna.pdf" in body
    assert "pedoman-pengurus.pdf" not in body
    pdf = client.get("/static/docs/pedoman-pengguna.pdf")
    assert pdf.status_code == 200
    assert pdf.mimetype == "application/pdf"
    blob = pdf.data
    assert b"aisyah.uji@example.com" not in blob
    assert b"081234567890" not in blob
    assert b"Jl. Rahasia" not in blob


def test_buku_saku_pengurus_di_panel(client):
    from tests.conftest import login_admin

    login_admin(client)
    body = client.get("/admin").get_data(as_text=True)
    assert "Buku saku pengurus" in body
    assert "/static/docs/pedoman-pengurus.pdf" in body
    pdf = client.get("/static/docs/pedoman-pengurus.pdf")
    assert pdf.status_code == 200
    assert pdf.mimetype == "application/pdf"
    assert b"aisyah.uji@example.com" not in pdf.data
    assert b"081234567890" not in pdf.data
