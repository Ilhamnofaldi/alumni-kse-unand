from io import BytesIO

from alumni_web.db import get_db
from alumni_web.security import safe_next
from tests.conftest import csrf_token, login_admin


def test_activate_creates_pending_and_blocks_login(client, app):
    token = csrf_token(client, "/klaim")
    res = client.post(
        "/klaim",
        data={
            "email": "aisyah.uji@example.com",
            "password": "password123",
            "csrf": token,
        },
        follow_redirects=True,
    )
    body = res.get_data(as_text=True)
    assert "pengurus" in body.lower()
    with app.app_context():
        row = get_db().execute(
            "SELECT status FROM users WHERE email = ?",
            ("aisyah.uji@example.com",),
        ).fetchone()
        assert row["status"] == "pending"
    token = csrf_token(client, "/login")
    denied = client.post(
        "/login",
        data={
            "email": "aisyah.uji@example.com",
            "password": "password123",
            "csrf": token,
        },
    )
    assert "Email atau kata sandi salah." in denied.get_data(as_text=True)
    profile = client.get("/alumni/1")
    assert "aisyah.uji@example.com" not in profile.get_data(as_text=True)


def test_activate_unknown_email_same_message(client, app):
    token = csrf_token(client, "/klaim")
    res = client.post(
        "/klaim",
        data={"email": "tidakada@example.com", "password": "password123", "csrf": token},
        follow_redirects=True,
    )
    assert "pengurus" in res.get_data(as_text=True).lower()
    with app.app_context():
        n = get_db().execute(
            "SELECT COUNT(*) FROM users WHERE email = ?",
            ("tidakada@example.com",),
        ).fetchone()[0]
        assert n == 0


def test_admin_approves_pending_user(client, app):
    token = csrf_token(client, "/klaim")
    client.post(
        "/klaim",
        data={
            "email": "aisyah.uji@example.com",
            "password": "password123",
            "csrf": token,
        },
    )
    with app.app_context():
        uid = get_db().execute(
            "SELECT id FROM users WHERE email = ?",
            ("aisyah.uji@example.com",),
        ).fetchone()["id"]
    login_admin(client)
    token = csrf_token(client, "/admin/akun")
    client.post(
        f"/admin/akun/{uid}/setujui",
        data={"csrf": token},
        follow_redirects=True,
    )
    client.post("/logout", data={"csrf": csrf_token(client, "/direktori")})
    token = csrf_token(client, "/login")
    client.post(
        "/login",
        data={
            "email": "aisyah.uji@example.com",
            "password": "password123",
            "csrf": token,
        },
        follow_redirects=True,
    )
    text = client.get("/alumni/1").get_data(as_text=True)
    assert "aisyah.uji@example.com" in text


def test_open_redirect_rejected(client):
    token = csrf_token(client, "/login")
    res = client.post(
        "/login?next=//evil.example",
        data={"email": "admin@test.local", "password": "password123", "csrf": token},
        follow_redirects=False,
    )
    assert res.status_code in (302, 303)
    loc = res.headers.get("Location", "")
    assert "evil" not in loc
    assert loc.startswith("/")


def test_safe_next_helper():
    assert safe_next("//evil.com", "/direktori") == "/direktori"
    assert safe_next("/alumni/1", "/direktori") == "/alumni/1"
    assert safe_next("https://evil.com", "/direktori") == "/direktori"
    assert safe_next("/%2f%2fevil.example", "/direktori") == "/direktori"
    assert safe_next("%2f%2fevil.example", "/direktori") == "/direktori"


def test_bad_page_param(client):
    res = client.get("/direktori?page=abc")
    assert res.status_code == 200


def test_export_formula_injection(client, app):
    with app.app_context():
        get_db().execute("UPDATE alumni SET full_name = ? WHERE id = 1", ("=cmd|calc",))
        get_db().commit()
    login_admin(client)
    token = csrf_token(client, "/admin/export.csv")
    res = client.post("/admin/export.csv", data={"csrf": token})
    assert res.status_code == 200
    text = res.get_data(as_text=True)
    assert "'=cmd|calc" in text


def test_import_rejects_non_csv(client):
    login_admin(client)
    token = csrf_token(client, "/admin/import")
    res = client.post(
        "/admin/import",
        data={"csrf": token, "file": (BytesIO(b"not csv"), "data.txt")},
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert "csv" in res.get_data(as_text=True).lower()


def test_edit_keeps_belum_bekerja(client, app):
    login_admin(client)
    token = csrf_token(client, "/admin/alumni/1/ubah")
    res = client.post(
        "/admin/alumni/1/ubah",
        data={
            "csrf": token,
            "full_name": "Aisyah Uji",
            "status": "belum_bekerja",
            "faculty": "pertanian",
            "major": "Agroteknologi",
            "is_listed": "1",
        },
        follow_redirects=True,
    )
    assert res.status_code == 200
    with app.app_context():
        row = get_db().execute("SELECT status_code FROM alumni WHERE id = 1").fetchone()
        assert row["status_code"] == "belum_bekerja"


def test_login_without_csrf_is_400(client):
    client.get("/login")
    res = client.post(
        "/login",
        data={"email": "admin@test.local", "password": "password123"},
    )
    assert res.status_code == 400


def test_aktivasi_mengalihkan_ke_klaim(client):
    res = client.get("/aktivasi")
    assert res.status_code in (301, 302, 303)
    assert "/klaim" in res.headers.get("Location", "")


def test_login_tamu_no_store(client):
    res = client.get("/login")
    assert "no-store" in res.headers.get("Cache-Control", "")
