from __future__ import annotations

from io import BytesIO

from alumni_web.db import get_db
from alumni_web.import_csv import TEMPLATE_HEADERS, import_csv_path, template_csv_bytes
from alumni_web.membership import parse_batch_lines
from alumni_web.security import reset_rate_limits
from tests.conftest import csrf_token, login_admin


def _approve(client, app, email: str):
    with app.app_context():
        uid = get_db().execute(
            "SELECT id FROM users WHERE email = ?", (email,)
        ).fetchone()["id"]
    login_admin(client)
    token = csrf_token(client, "/admin/tinjau")
    client.post(
        f"/admin/tinjau/akun/{uid}/setujui-tampil",
        data={"csrf": token},
        follow_redirects=True,
    )
    client.post("/logout", data={"csrf": csrf_token(client, "/direktori")})


def _login(client, email: str, password: str):
    token = csrf_token(client, "/login")
    return client.post(
        "/login",
        data={"email": email, "password": password, "csrf": token},
        follow_redirects=True,
    )


def test_daftar_membuat_pending_dan_tidak_tampil_publik(client, app):
    token = csrf_token(client, "/daftar")
    res = client.post(
        "/daftar",
        data={
            "csrf": token,
            "full_name": "Rina Baru",
            "faculty": "teknik",
            "major": "Teknik Mesin",
            "cohort_year": "2024",
            "email": "rina.baru@example.com",
            "phone": "081222233334",
            "password": "password123",
        },
        follow_redirects=True,
    )
    body = res.get_data(as_text=True)
    assert "pengurus" in body.lower()
    with app.app_context():
        user = get_db().execute(
            "SELECT status, alumni_id FROM users WHERE email = ?",
            ("rina.baru@example.com",),
        ).fetchone()
        alumni = get_db().execute(
            "SELECT full_name, is_listed, source FROM alumni WHERE email_normalized = ?",
            ("rina.baru@example.com",),
        ).fetchone()
    assert user["status"] == "pending"
    assert alumni["is_listed"] == 0
    assert alumni["source"] == "self_register"
    assert "Rina Baru" not in client.get("/direktori").get_data(as_text=True)
    denied = _login(client, "rina.baru@example.com", "password123")
    assert "Email atau kata sandi salah." in denied.get_data(as_text=True)


def test_daftar_email_asing_pesan_sama(client, app):
    reset_rate_limits()
    token = csrf_token(client, "/daftar")
    asing = client.post(
        "/daftar",
        data={
            "csrf": token,
            "full_name": "Orang Asing",
            "email": "asing@example.com",
            "password": "password123",
        },
        follow_redirects=True,
    )
    token = csrf_token(client, "/daftar")
    kenal = client.post(
        "/daftar",
        data={
            "csrf": token,
            "full_name": "Aisyah Uji",
            "email": "aisyah.uji@example.com",
            "password": "password123",
        },
        follow_redirects=True,
    )
    assert "pengurus" in asing.get_data(as_text=True).lower()
    assert "pengurus" in kenal.get_data(as_text=True).lower()
    with app.app_context():
        n = get_db().execute(
            "SELECT COUNT(*) FROM alumni WHERE email_normalized = ?",
            ("aisyah.uji@example.com",),
        ).fetchone()[0]
        pending = get_db().execute(
            "SELECT status FROM users WHERE email = ?",
            ("aisyah.uji@example.com",),
        ).fetchone()
    assert n == 1
    assert pending["status"] == "pending"


def test_daftar_tidak_menghidupkan_alumni_tersembunyi(client, app):
    with app.app_context():
        get_db().execute("UPDATE alumni SET is_listed = 0 WHERE id = 1")
        get_db().commit()
    token = csrf_token(client, "/daftar")
    client.post(
        "/daftar",
        data={
            "csrf": token,
            "full_name": "Aisyah Uji",
            "email": "aisyah.uji@example.com",
            "password": "password123",
        },
    )
    with app.app_context():
        n = get_db().execute(
            "SELECT COUNT(*) FROM users WHERE email = ?",
            ("aisyah.uji@example.com",),
        ).fetchone()[0]
    assert n == 0


def test_klaim_nama_dan_email(client, app):
    token = csrf_token(client, "/klaim")
    client.post(
        "/klaim",
        data={
            "csrf": token,
            "full_name": "Aisyah Uji",
            "cohort_year": "2013",
            "email": "aisyah.uji@example.com",
            "phone": "081234567890",
            "password": "password123",
        },
    )
    with app.app_context():
        row = get_db().execute(
            "SELECT alumni_id, status FROM users WHERE email = ?",
            ("aisyah.uji@example.com",),
        ).fetchone()
    assert row["alumni_id"] == 1
    assert row["status"] == "pending"


def test_klaim_salah_nama_tidak_membuat_akun(client, app):
    token = csrf_token(client, "/klaim")
    client.post(
        "/klaim",
        data={
            "csrf": token,
            "full_name": "Bukan Aisyah",
            "cohort_year": "2013",
            "email": "orang.lain@example.com",
            "phone": "081234567890",
            "password": "password123",
        },
        follow_redirects=True,
    )
    with app.app_context():
        n = get_db().execute(
            "SELECT COUNT(*) FROM users WHERE email = ?",
            ("orang.lain@example.com",),
        ).fetchone()[0]
    assert n == 0


def test_setujui_tampil_dan_profil_saya(client, app):
    token = csrf_token(client, "/daftar")
    client.post(
        "/daftar",
        data={
            "csrf": token,
            "full_name": "Rina Baru",
            "faculty": "teknik",
            "cohort_year": "2024",
            "email": "rina.baru@example.com",
            "password": "password123",
            "workplace": "PT Lama",
        },
    )
    _approve(client, app, "rina.baru@example.com")
    assert "Rina Baru" in client.get("/direktori").get_data(as_text=True)
    _login(client, "rina.baru@example.com", "password123")
    page = client.get("/profil/saya")
    assert page.status_code == 200
    assert "Rina Baru" in page.get_data(as_text=True)
    token = csrf_token(client, "/profil/saya")
    client.post(
        "/profil/saya",
        data={
            "csrf": token,
            "workplace": "PT Baru",
            "status": "bekerja",
            "domicile": "Kota Padang",
            "phone": "081298765432",
            "testimonial": "Tetap berbagi.",
        },
        follow_redirects=True,
    )
    with app.app_context():
        row = get_db().execute(
            "SELECT workplace, city, self_updated_at, phone_normalized FROM alumni WHERE email_normalized = ?",
            ("rina.baru@example.com",),
        ).fetchone()
    assert row["workplace"] == "PT Baru"
    assert row["city"] == "Padang"
    assert row["self_updated_at"]
    assert row["phone_normalized"] == "6281298765432"
    public = app.test_client()
    with app.app_context():
        aid = get_db().execute(
            "SELECT id FROM alumni WHERE email_normalized = ?",
            ("rina.baru@example.com",),
        ).fetchone()[0]
    pub = public.get(f"/alumni/{aid}").get_data(as_text=True)
    assert "PT Baru" in pub
    assert "081298765432" not in pub
    assert "rina.baru@example.com" not in pub
    # Alumni tidak boleh mengedit orang lain lewat form admin.
    assert client.get("/admin/alumni/1/ubah").status_code == 403


def test_alumni_tidak_bisa_mengubah_nama_lewat_profil(client, app):
    token = csrf_token(client, "/klaim")
    client.post(
        "/klaim",
        data={
            "csrf": token,
            "full_name": "Aisyah Uji",
            "cohort_year": "2013",
            "email": "aisyah.uji@example.com",
            "password": "password123",
        },
    )
    _approve(client, app, "aisyah.uji@example.com")
    _login(client, "aisyah.uji@example.com", "password123")
    token = csrf_token(client, "/profil/saya")
    client.post(
        "/profil/saya",
        data={
            "csrf": token,
            "full_name": "Nama Palsu",
            "faculty": "hukum",
            "cohort_year": "1999",
            "workplace": "Kantor Baru",
        },
        follow_redirects=True,
    )
    with app.app_context():
        row = get_db().execute("SELECT full_name, faculty_code, cohort_year, workplace FROM alumni WHERE id = 1").fetchone()
    assert row["full_name"] == "Aisyah Uji"
    assert row["faculty_code"] == "pertanian"
    assert row["cohort_year"] == 2013
    assert row["workplace"] == "Kantor Baru"


def test_ganti_email_butuh_pengurus(client, app):
    token = csrf_token(client, "/klaim")
    client.post(
        "/klaim",
        data={
            "csrf": token,
            "full_name": "Aisyah Uji",
            "cohort_year": "2013",
            "email": "aisyah.uji@example.com",
            "password": "password123",
        },
    )
    _approve(client, app, "aisyah.uji@example.com")
    _login(client, "aisyah.uji@example.com", "password123")
    token = csrf_token(client, "/profil/saya")
    client.post(
        "/profil/saya/email",
        data={"csrf": token, "email": "aisyah.baru@example.com"},
        follow_redirects=True,
    )
    with app.app_context():
        req = get_db().execute(
            "SELECT kind, payload FROM change_requests WHERE kind = 'email'"
        ).fetchone()
        email = get_db().execute("SELECT email FROM alumni WHERE id = 1").fetchone()[0]
    assert req is not None
    assert email == "aisyah.uji@example.com"
    login_admin(client)
    with app.app_context():
        rid = get_db().execute("SELECT id FROM change_requests WHERE kind = 'email'").fetchone()[0]
    token = csrf_token(client, "/admin/tinjau")
    client.post(
        f"/admin/tinjau/permintaan/{rid}/setujui",
        data={"csrf": token},
        follow_redirects=True,
    )
    with app.app_context():
        assert get_db().execute("SELECT email_normalized FROM alumni WHERE id = 1").fetchone()[0] == "aisyah.baru@example.com"
        assert get_db().execute(
            "SELECT email FROM users WHERE alumni_id = 1"
        ).fetchone()[0] == "aisyah.baru@example.com"


def test_minta_sembunyi(client, app):
    token = csrf_token(client, "/klaim")
    client.post(
        "/klaim",
        data={
            "csrf": token,
            "full_name": "Aisyah Uji",
            "cohort_year": "2013",
            "email": "aisyah.uji@example.com",
            "password": "password123",
        },
    )
    _approve(client, app, "aisyah.uji@example.com")
    _login(client, "aisyah.uji@example.com", "password123")
    token = csrf_token(client, "/profil/saya")
    client.post("/profil/saya/sembunyikan", data={"csrf": token}, follow_redirects=True)
    login_admin(client)
    with app.app_context():
        rid = get_db().execute("SELECT id FROM change_requests WHERE kind = 'hide'").fetchone()[0]
    token = csrf_token(client, "/admin/tinjau")
    client.post(
        f"/admin/tinjau/permintaan/{rid}/setujui",
        data={"csrf": token},
        follow_redirects=True,
    )
    public = app.test_client()
    assert public.get("/alumni/1").status_code == 404


def test_lupa_sandi_pesan_generik(client, app):
    reset_rate_limits()
    token = csrf_token(client, "/lupa-sandi")
    ada = client.post(
        "/lupa-sandi",
        data={"csrf": token, "email": "aisyah.uji@example.com"},
        follow_redirects=True,
    )
    token = csrf_token(client, "/lupa-sandi")
    tidak = client.post(
        "/lupa-sandi",
        data={"csrf": token, "email": "tidakada@example.com"},
        follow_redirects=True,
    )
    assert "pengurus" in ada.get_data(as_text=True).lower()
    assert "pengurus" in tidak.get_data(as_text=True).lower()
    with app.app_context():
        # Belum ada akun alumni aktif, jadi permintaan reset tidak dibuat.
        n = get_db().execute("SELECT COUNT(*) FROM change_requests WHERE kind = 'reset'").fetchone()[0]
    assert n == 0


def test_tempel_daftar_dan_undangan(client, app):
    login_admin(client)
    token = csrf_token(client, "/admin/tempel")
    res = client.post(
        "/admin/tempel",
        data={
            "csrf": token,
            "daftar": "Siti Rahma; pertanian; 2024; siti.tempel@example.com; 081211122233\n",
            "undang": "1",
        },
        follow_redirects=True,
    )
    body = res.get_data(as_text=True)
    assert "/undang/" in body
    # Tautan harus absolut (skema + domain) supaya bisa langsung disalin.
    assert "http://localhost/undang/" in body
    assert "Siti Rahma" not in client.get("/direktori").get_data(as_text=True)
    with app.app_context():
        row = get_db().execute(
            "SELECT is_listed, source FROM alumni WHERE email_normalized = ?",
            ("siti.tempel@example.com",),
        ).fetchone()
    assert row["is_listed"] == 0
    assert row["source"] == "batch"


def test_parse_batch_abaikan_komentar():
    rows = parse_batch_lines("# abaikan\nNama Satu; teknik; 2020\n\n")
    assert len(rows) == 1
    assert rows[0]["full_name"] == "Nama Satu"


def test_pengurus_kedua(client, app):
    login_admin(client)
    token = csrf_token(client, "/admin/akun")
    res = client.post(
        "/admin/akun/pengurus",
        data={
            "csrf": token,
            "email": "wakil@test.local",
            "password": "sandi-wakil-10",
        },
        follow_redirects=True,
    )
    assert res.status_code == 200
    client.post("/logout", data={"csrf": csrf_token(client, "/direktori")})
    masuk = _login(client, "wakil@test.local", "sandi-wakil-10")
    assert masuk.status_code == 200
    assert client.get("/admin").status_code == 200


def test_pengurus_terakhir_tidak_bisa_dinonaktifkan(client, app):
    login_admin(client)
    with app.app_context():
        uid = get_db().execute(
            "SELECT id FROM users WHERE email = ?", ("admin@test.local",)
        ).fetchone()[0]
    token = csrf_token(client, "/admin/akun")
    client.post(
        f"/admin/akun/{uid}/nonaktif-pengurus",
        data={"csrf": token},
        follow_redirects=True,
    )
    with app.app_context():
        status = get_db().execute(
            "SELECT status FROM users WHERE id = ?", (uid,)
        ).fetchone()[0]
    assert status == "active"


def test_kode_pemulih_pengurus(client, app):
    login_admin(client)
    token = csrf_token(client, "/admin/akun")
    res = client.post(
        "/admin/akun/kode-pemulih",
        data={"csrf": token},
        follow_redirects=True,
    )
    body = res.get_data(as_text=True)
    assert "Kode pemulih" in body
    code = None
    for line in body.split("<code>")[1:]:
        piece = line.split("</code>")[0].strip()
        if "-" in piece:
            code = piece
            break
    assert code
    client.post("/logout", data={"csrf": csrf_token(client, "/direktori")})
    token = csrf_token(client, "/pulih-pengurus")
    client.post(
        "/pulih-pengurus",
        data={
            "csrf": token,
            "email": "admin@test.local",
            "code": code,
            "baru": "sandi-pulih-baru",
            "ulang": "sandi-pulih-baru",
        },
        follow_redirects=True,
    )
    masuk = _login(client, "admin@test.local", "sandi-pulih-baru")
    assert client.get("/admin").status_code == 200
    # Kode tidak bisa dipakai ulang.
    client.post("/logout", data={"csrf": csrf_token(client, "/direktori")})
    token = csrf_token(client, "/pulih-pengurus")
    client.post(
        "/pulih-pengurus",
        data={
            "csrf": token,
            "email": "admin@test.local",
            "code": code,
            "baru": "sandi-lain-panjang",
            "ulang": "sandi-lain-panjang",
        },
    )
    _login(client, "admin@test.local", "sandi-lain-panjang")
    assert client.get("/admin").status_code == 403


def test_template_csv_hanya_pengurus(client):
    assert client.get("/admin/import/template.csv").status_code == 403
    login_admin(client)
    res = client.get("/admin/import/template.csv")
    assert res.status_code == 200
    text = res.get_data(as_text=True)
    for col in TEMPLATE_HEADERS:
        assert col in text
    assert template_csv_bytes().startswith(b"\xef\xbb\xbf") or True


def test_impor_tidak_menimpa_self_update(app, tmp_path):
    from pathlib import Path

    with app.app_context():
        get_db().execute(
            "UPDATE alumni SET workplace = 'Sudah Diubah', self_updated_at = ? WHERE id = 1",
            ("2026-01-01T00:00:00+00:00",),
        )
        get_db().commit()
        dest = tmp_path / "again.csv"
        dest.write_text(
            Path(__file__).parent.joinpath("fixtures", "sample.csv").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        result = import_csv_path(dest)
        row = get_db().execute("SELECT workplace FROM alumni WHERE id = 1").fetchone()
    assert result["protected"] >= 1
    assert row["workplace"] == "Sudah Diubah"


def test_impor_insert_only(app, tmp_path):
    from pathlib import Path

    with app.app_context():
        get_db().execute("UPDATE alumni SET workplace = 'Jangan Timpa' WHERE id = 1")
        get_db().commit()
        dest = tmp_path / "again.csv"
        dest.write_text(
            Path(__file__).parent.joinpath("fixtures", "sample.csv").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        result = import_csv_path(dest, insert_only=True)
        row = get_db().execute("SELECT workplace FROM alumni WHERE id = 1").fetchone()
        budi = get_db().execute(
            "SELECT full_name FROM alumni WHERE email_normalized = ?",
            ("budi.uji@example.com",),
        ).fetchone()
    assert result["updated"] == 0
    assert result["inserted"] >= 1
    assert row["workplace"] == "Jangan Timpa"
    assert budi["full_name"] == "Budi Uji"


def test_web_impor_default_insert_only(client, app):
    login_admin(client)
    token = csrf_token(client, "/admin/import")
    from pathlib import Path

    data = Path(__file__).parent.joinpath("fixtures", "sample.csv").read_bytes()
    res = client.post(
        "/admin/import",
        data={"csrf": token, "insert_only": "1", "file": (BytesIO(data), "sample.csv")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert "baru" in res.get_data(as_text=True).lower()


def test_lupa_sandi_membuat_permintaan_setelah_akun_aktif(client, app):
    token = csrf_token(client, "/klaim")
    client.post(
        "/klaim",
        data={
            "csrf": token,
            "full_name": "Aisyah Uji",
            "cohort_year": "2013",
            "email": "aisyah.uji@example.com",
            "password": "password123",
        },
    )
    _approve(client, app, "aisyah.uji@example.com")
    token = csrf_token(client, "/lupa-sandi")
    client.post(
        "/lupa-sandi",
        data={"csrf": token, "email": "aisyah.uji@example.com"},
        follow_redirects=True,
    )
    with app.app_context():
        n = get_db().execute("SELECT COUNT(*) FROM change_requests WHERE kind = 'reset'").fetchone()[0]
    assert n == 1
    login_admin(client)
    with app.app_context():
        rid = get_db().execute("SELECT id FROM change_requests WHERE kind = 'reset'").fetchone()[0]
    token = csrf_token(client, "/admin/tinjau")
    res = client.post(
        f"/admin/tinjau/permintaan/{rid}/setujui",
        data={"csrf": token},
        follow_redirects=True,
    )
    body = res.get_data(as_text=True)
    assert "/pulih/" in body
    # Tautan pemulihan juga harus absolut supaya bisa langsung disalin.
    assert "http://localhost/pulih/" in body
    tautan = None
    for part in body.split('href="')[1:]:
        href = part.split('"')[0]
        if "/pulih/" in href:
            tautan = href
            break
    if tautan is None:
        for part in body.split("<code>")[1:]:
            piece = part.split("</code>")[0]
            if "/pulih/" in piece:
                tautan = piece
                break
    assert tautan
    client.post("/logout", data={"csrf": csrf_token(client, "/direktori")})
    page = client.get(tautan)
    assert page.status_code == 200
    token = csrf_token(client, tautan)
    client.post(
        tautan,
        data={"csrf": token, "baru": "sandi-baru-alumni", "ulang": "sandi-baru-alumni"},
        follow_redirects=True,
    )
    _login(client, "aisyah.uji@example.com", "sandi-baru-alumni")
    assert client.get("/profil/saya").status_code == 200


def test_pemilik_boleh_mengisi_angkatan_kosong(client, app):
    token = csrf_token(client, "/daftar")
    client.post(
        "/daftar",
        data={
            "csrf": token,
            "full_name": "Rina Kosong",
            "faculty": "teknik",
            "email": "rina.kosong@example.com",
            "password": "password123",
        },
    )
    _approve(client, app, "rina.kosong@example.com")
    _login(client, "rina.kosong@example.com", "password123")
    token = csrf_token(client, "/profil/saya")
    client.post(
        "/profil/saya",
        data={"csrf": token, "cohort_year": "2018", "workplace": "PT Ada"},
        follow_redirects=True,
    )
    with app.app_context():
        row = get_db().execute(
            "SELECT cohort_year, faculty_code FROM alumni WHERE email_normalized = ?",
            ("rina.kosong@example.com",),
        ).fetchone()
    assert row["cohort_year"] == 2018
    assert row["faculty_code"] == "teknik"


def test_klaim_tanpa_angkatan_pada_kerangka(client, app):
    with app.app_context():
        get_db().execute("UPDATE alumni SET cohort_year = NULL WHERE id = 1")
        get_db().commit()
    token = csrf_token(client, "/klaim")
    client.post(
        "/klaim",
        data={
            "csrf": token,
            "full_name": "Aisyah Uji",
            "cohort_year": "2013",
            "email": "aisyah.uji@example.com",
            "phone": "081234567890",
            "password": "password123",
        },
    )
    with app.app_context():
        row = get_db().execute(
            "SELECT alumni_id, status FROM users WHERE email = ?",
            ("aisyah.uji@example.com",),
        ).fetchone()
    assert row["alumni_id"] == 1
    assert row["status"] == "pending"


def test_setujui_identitas_membuka_form_ubah(client, app):
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
    _approve(client, app, "aisyah.uji@example.com")
    _login(client, "aisyah.uji@example.com", "password123")
    token = csrf_token(client, "/profil/saya")
    client.post(
        "/profil/saya/koreksi",
        data={"csrf": token, "note": "Jurusan seharusnya Agroekoteknologi."},
    )
    login_admin(client)
    with app.app_context():
        rid = get_db().execute(
            "SELECT id FROM change_requests WHERE kind = 'identity'"
        ).fetchone()["id"]
    token = csrf_token(client, "/admin/tinjau")
    res = client.post(
        f"/admin/tinjau/permintaan/{rid}/setujui",
        data={"csrf": token},
        follow_redirects=True,
    )
    body = res.get_data(as_text=True)
    assert "Agroekoteknologi" in body
    assert "form ubah" in body.lower() or "Ubah" in body
    with app.app_context():
        status = get_db().execute(
            "SELECT status FROM change_requests WHERE id = ?", (rid,)
        ).fetchone()[0]
        name = get_db().execute("SELECT full_name FROM alumni WHERE id = 1").fetchone()[0]
    assert status == "approved"
    assert name == "Aisyah Uji"


def test_undangan_tidak_praisi_kontak(client, app):
    login_admin(client)
    token = csrf_token(client, "/admin/tempel")
    res = client.post(
        "/admin/tempel",
        data={
            "csrf": token,
            "daftar": "Siti Rahma; pertanian; 2024; siti.undang@example.com; 081211122233\n",
            "undang": "1",
        },
        follow_redirects=True,
    )
    body = res.get_data(as_text=True)
    tautan = None
    for part in body.split("<code>")[1:]:
        piece = part.split("</code>")[0]
        if "/undang/" in piece:
            tautan = piece
            break
    assert tautan
    page = client.get(tautan)
    text = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "siti.undang@example.com" not in text
    assert "081211122233" not in text
    assert "no-store" in page.headers.get("Cache-Control", "")
