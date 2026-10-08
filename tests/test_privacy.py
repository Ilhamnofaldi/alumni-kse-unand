from alumni_web.db import get_db, utcnow
from tests.conftest import csrf_token, login_admin


def test_halaman_daftar_tidak_membawa_pii_orang_lain(client):
    body = client.get("/daftar").get_data(as_text=True)
    assert "aisyah.uji@example.com" not in body
    assert "081234567890" not in body
    assert "Jl. Rahasia" not in body


def test_public_directory_ok(client):
    res = client.get("/direktori")
    assert res.status_code == 200
    assert b"Aisyah Uji" in res.data


def test_beranda_dan_statistik_tanpa_pii(client):
    for path in ("/", "/statistik"):
        body = client.get(path).get_data(as_text=True)
        assert "081234567890" not in body
        assert "aisyah.uji@example.com" not in body
        assert "Jl. Rahasia" not in body
        assert "1994-08-11" not in body


def test_daftar_tanpa_csrf_400(client):
    res = client.post(
        "/daftar",
        data={"full_name": "X", "email": "x@y.z", "password": "password123"},
    )
    assert res.status_code == 400
    assert "Paguyuban" in res.get_data(as_text=True)


def test_public_profile_hides_pii(client):
    res = client.get("/alumni/1")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "Aisyah Uji" in body
    assert "Agroteknologi" in body
    assert "081234567890" not in body
    assert "6281234567890" not in body
    assert "aisyah.uji@example.com" not in body
    assert "Jl. Rahasia No. 9" not in body
    assert "1994-08-11" not in body


def test_map_points_have_no_names(client):
    res = client.get("/api/map-points")
    assert res.status_code == 200
    payload = res.get_json()
    blob = str(payload)
    assert "Aisyah" not in blob
    assert "0812" not in blob
    for point in payload["points"]:
        for person in point.get("alumni") or []:
            assert "phone" not in person
            assert "email" not in person
            assert "domicile" not in person


def test_export_requires_admin(client):
    res = client.get("/admin/export.csv")
    assert res.status_code == 403


def test_admin_login_sees_pii(client):
    login_admin(client)
    profile = client.get("/alumni/1")
    text = profile.get_data(as_text=True)
    assert "aisyah.uji@example.com" in text
    assert "081234567890" in text
    assert "Jl. Rahasia No. 9" in text
    assert "1994-08-11" in text


def test_alumni_melihat_kontak_bukan_alamat_orang_lain(client, app):
    token = csrf_token(client, "/klaim")
    client.post(
        "/klaim",
        data={
            "csrf": token,
            "full_name": "Aisyah Uji",
            "email": "aisyah.uji@example.com",
            "password": "password123",
        },
    )
    login_admin(client)
    with app.app_context():
        uid = get_db().execute(
            "SELECT id FROM users WHERE email = ?", ("aisyah.uji@example.com",)
        ).fetchone()["id"]
    token = csrf_token(client, "/admin/tinjau")
    client.post(
        f"/admin/tinjau/akun/{uid}/setujui-tampil",
        data={"csrf": token},
    )
    client.post("/logout", data={"csrf": csrf_token(client, "/direktori")})
    token = csrf_token(client, "/login")
    client.post(
        "/login",
        data={"email": "aisyah.uji@example.com", "password": "password123", "csrf": token},
    )
    own = client.get("/alumni/1").get_data(as_text=True)
    assert "aisyah.uji@example.com" in own
    assert "Jl. Rahasia No. 9" in own
    with app.app_context():
        now = utcnow()
        get_db().execute(
            """
            INSERT INTO alumni (
              full_name, name_normalized, domicile, city, phone, email, email_normalized,
              faculty_code, cohort_year, is_listed, data_quality_flags, created_at, updated_at
            ) VALUES (
              'Budi Lain', 'budi lain', 'Jl. Orang Lain 1', 'Solok', '081200011122',
              'budi.lain@example.com', 'budi.lain@example.com', 'teknik', 2010, 1, '[]', ?, ?
            )
            """,
            (now, now),
        )
        get_db().commit()
        oid = get_db().execute(
            "SELECT id FROM alumni WHERE email_normalized = ?", ("budi.lain@example.com",)
        ).fetchone()["id"]
    other = client.get(f"/alumni/{oid}").get_data(as_text=True)
    assert "081200011122" in other
    assert "budi.lain@example.com" in other
    assert "Jl. Orang Lain 1" not in other


def test_unlisted_hidden_from_public_visible_to_admin(client, app):
    from alumni_web.db import get_db

    login_admin(client)
    with app.app_context():
        get_db().execute("UPDATE alumni SET is_listed = 0 WHERE id = 1")
        get_db().commit()
    res = client.get("/alumni/1")
    assert res.status_code == 200
    assert "Aisyah Uji" in res.get_data(as_text=True)
    public = app.test_client()
    assert public.get("/alumni/1").status_code == 404


def test_disabled_session_cannot_see_pii(client, app):
    from alumni_web.db import get_db

    login_admin(client)
    with app.app_context():
        get_db().execute(
            "UPDATE users SET status = 'disabled' WHERE email = ?",
            ("admin@test.local",),
        )
        get_db().commit()
    assert "aisyah.uji@example.com" not in client.get("/alumni/1").get_data(as_text=True)
    assert client.get("/admin").status_code == 403
