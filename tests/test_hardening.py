"""Regresi untuk celah yang pernah terbukti bisa dieksploitasi."""

from __future__ import annotations

from alumni_web.catalog import INTERNAL_FIELDS, PII_FIELDS, PUBLIC_FIELDS
from alumni_web.db import get_db
from alumni_web.security import clamp_int, parse_cohort, reset_rate_limits
from tests.conftest import csrf_token, login_admin


def test_param_besar_tidak_membuat_500(client):
    besar = "9" * 20
    assert client.get(f"/direktori?page={besar}").status_code == 200
    assert client.get(f"/direktori?angkatan={besar}").status_code == 200
    login_admin(client)
    assert client.get(f"/admin?page={besar}").status_code == 200


def test_clamp_dan_cohort_menolak_nilai_liar():
    assert clamp_int("9" * 20, 1, 100_000, 1) == 1
    assert clamp_int("abc", 1, 100_000, 1) == 1
    assert clamp_int("7", 1, 100_000, 1) == 7
    assert clamp_int("100001", 1, 100_000, 1) == 100_000
    assert clamp_int("999999999", 1, 100_000, 1) == 1
    assert parse_cohort("9" * 20) is None
    assert parse_cohort("1899") is None
    assert parse_cohort("2013") == 2013


def test_query_string_tidak_bisa_membajak_url_for(client):
    assert client.get("/direktori?page=1&endpoint=zzz").status_code == 200
    res = client.get(
        "/direktori?page=1&_external=1&_scheme=https",
        headers={"Host": "evil.example"},
    )
    assert res.status_code == 200
    assert "evil.example" not in res.get_data(as_text=True)


def test_rate_limit_tidak_bisa_dilewati_lewat_forwarded_for(client):
    reset_rate_limits()
    codes = []
    for i in range(12):
        token = csrf_token(client, "/login")
        res = client.post(
            "/login",
            data={"email": f"x{i}@y.z", "password": "salah-sekali", "csrf": token},
            headers={"X-Forwarded-For": f"10.0.0.{i}"},
        )
        codes.append(res.status_code)
    assert 429 in codes


def test_aktivasi_tidak_membocorkan_alumni_tersembunyi(client, app):
    with app.app_context():
        get_db().execute("UPDATE alumni SET is_listed = 0 WHERE id = 1")
        get_db().commit()
    token = csrf_token(client, "/klaim")
    client.post(
        "/klaim",
        data={
            "email": "aisyah.uji@example.com",
            "password": "sandi-panjang-1",
            "csrf": token,
        },
    )
    with app.app_context():
        row = get_db().execute(
            "SELECT COUNT(*) FROM users WHERE email = ?", ("aisyah.uji@example.com",)
        ).fetchone()[0]
    assert row == 0


def test_login_pesan_sama_untuk_email_terdaftar_dan_asing(client):
    reset_rate_limits()
    token = csrf_token(client, "/login")
    kenal = client.post(
        "/login",
        data={"email": "admin@test.local", "password": "salah", "csrf": token},
    )
    token = csrf_token(client, "/login")
    asing = client.post(
        "/login",
        data={"email": "tidak@ada.tld", "password": "salah", "csrf": token},
    )
    assert kenal.status_code == asing.status_code == 200
    assert "Email atau kata sandi salah." in kenal.get_data(as_text=True)
    assert "Email atau kata sandi salah." in asing.get_data(as_text=True)


def test_semua_kolom_alumni_terklasifikasi(app):
    with app.app_context():
        cols = {row[1] for row in get_db().execute("PRAGMA table_info(alumni)").fetchall()}
    known = set(PUBLIC_FIELDS) | set(PII_FIELDS) | set(INTERNAL_FIELDS)
    assert cols - known == set(), "kolom baru wajib masuk PUBLIC/PII/INTERNAL_FIELDS"
    assert known - cols == set()


def test_profil_publik_tidak_membawa_kolom_internal(client):
    body = client.get("/alumni/1").get_data(as_text=True)
    assert "aisyah uji" not in body  # name_normalized
    assert "[]" not in body  # data_quality_flags


def test_peta_menyembunyikan_kota_berisi_sedikit_orang(client, app):
    with app.app_context():
        get_db().execute("UPDATE alumni SET lat = -0.95, lng = 100.35 WHERE id = 1")
        get_db().commit()
    app.config["MAP_MIN_COUNT"] = 3
    assert client.get("/api/map-points").get_json()["points"] == []
    app.config["MAP_MIN_COUNT"] = 1
    assert len(client.get("/api/map-points").get_json()["points"]) == 1
    app.config["MAP_MIN_COUNT"] = 0
    assert client.get("/api/map-points").get_json()["points"] == []


def test_robots_menutup_halaman_orang(client):
    body = client.get("/robots.txt").get_data(as_text=True)
    assert "Disallow: /admin" in body
    assert "Disallow: /alumni/" in body
    assert "Disallow: /daftar" in body
    assert "Disallow: /profil" in body


def test_healthz(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.get_json()["status"] == "ok"
    assert "Set-Cookie" not in res.headers


def test_aset_statis_boleh_di_cache(client):
    res = client.get("/static/css/app.css")
    assert res.status_code == 200
    cache = res.headers.get("Cache-Control", "")
    assert "max-age=" in cache
    assert "immutable" in cache
    assert "no-store" not in cache
    home = client.get("/")
    assert "v=" in home.get_data(as_text=True)
    assert "Set-Cookie" not in client.get("/robots.txt").headers


def test_csrf_gagal_memakai_halaman_error_situs(client):
    res = client.post("/login", data={"email": "a@b.c", "password": "x"})
    assert res.status_code == 400
    assert "Paguyuban" in res.get_data(as_text=True)


def test_ganti_sandi_dan_paksa_login_ulang(client):
    login_admin(client)
    token = csrf_token(client, "/akun/sandi")
    res = client.post(
        "/akun/sandi",
        data={
            "current": "password123",
            "baru": "sandi-baru-yang-panjang",
            "ulang": "sandi-baru-yang-panjang",
            "csrf": token,
        },
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert client.get("/admin").status_code == 403
    token = csrf_token(client, "/login")
    ulang = client.post(
        "/login",
        data={
            "email": "admin@test.local",
            "password": "sandi-baru-yang-panjang",
            "csrf": token,
        },
        follow_redirects=True,
    )
    assert ulang.status_code == 200
    assert client.get("/admin").status_code == 200


def test_ganti_sandi_menolak_sandi_lama_salah(client):
    login_admin(client)
    token = csrf_token(client, "/akun/sandi")
    res = client.post(
        "/akun/sandi",
        data={"current": "salah", "baru": "sandi-baru-panjang", "ulang": "sandi-baru-panjang", "csrf": token},
    )
    assert "Kata sandi saat ini salah." in res.get_data(as_text=True)


def test_ekspor_pii_tercatat_di_audit(client, app):
    login_admin(client)
    token = csrf_token(client, "/admin/export.csv")
    assert client.post("/admin/export.csv", data={"csrf": token}).status_code == 200
    with app.app_context():
        actions = [
            r[0] for r in get_db().execute("SELECT action FROM audit_log ORDER BY id").fetchall()
        ]
    assert "login_ok" in actions
    assert "export_csv" in actions


def test_header_no_store_untuk_sesi_login(client):
    login_admin(client)
    res = client.get("/alumni/1")
    assert "no-store" in res.headers.get("Cache-Control", "")
    assert res.headers.get("X-Robots-Tag") == "noindex, nofollow"


def test_csp_tanpa_cdn_pihak_ketiga(client):
    res = client.get("/")
    csp = res.headers["Content-Security-Policy"]
    assert "script-src 'self';" in csp
    assert "style-src 'self';" in csp
    assert "font-src 'self';" in csp
    assert "cdn.jsdelivr.net" not in csp
    assert "unpkg.com" not in csp
    assert "fonts.googleapis.com" not in csp
    assert "fonts.gstatic.com" not in csp
    assert "'unsafe-inline'" not in csp
    assert "frame-ancestors 'self'" in csp
    # Halaman juga tidak boleh lagi memanggil Google Fonts.
    body = res.get_data(as_text=True)
    assert "fonts.googleapis.com" not in body
    assert "fonts.gstatic.com" not in body
