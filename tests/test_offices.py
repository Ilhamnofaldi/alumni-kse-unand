from __future__ import annotations

from alumni_web.db import get_db, utcnow
from alumni_web.import_csv import TEMPLATE_HEADERS, _header_map, import_csv_path
from alumni_web.offices import (
    add_roles,
    build_org_chart,
    build_org_tree,
    decorate_alumni_rows,
    org_seats,
    parse_office_text,
    parse_period,
    parse_role_entries,
    split_wide_role_rows,
    term_years,
    top_offices_for,
)
from tests.conftest import csrf_token, login_admin


def _insert_city(app, *, name, email, listed=1, lat=-0.95, lng=100.35, city="Padang"):
    now = utcnow()
    with app.app_context():
        db = get_db()
        db.execute(
            """
            INSERT INTO alumni (
              full_name, name_normalized, email, email_normalized, city, province,
              lat, lng, faculty_code, cohort_year, major_normalized, is_listed,
              data_quality_flags, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'Sumatera Barat', ?, ?, 'teknik', 2014, 'Teknik Mesin', ?, '[]', ?, ?)
            """,
            (name, name.lower(), email, email, city, lat, lng, listed, now, now),
        )
        db.commit()
        return db.execute(
            "SELECT id FROM alumni WHERE email_normalized = ?", (email,)
        ).fetchone()["id"]


def test_parser_jabatan_dan_periode():
    assert parse_office_text("Wakil Ketua 2023/2024") == ("wakil_ketua", None)
    assert parse_office_text("Ketua Community Development") == ("community_development", None)
    assert parse_office_text("PJ Fakultas Pertanian") == ("pj_fakultas", "pertanian")
    assert parse_office_text("Anggota Humas 2023/2024") == ("anggota_humas", None)
    assert parse_office_text("Anggota Divisi Humas") == ("anggota_humas", None)
    assert parse_office_text("Anggota Divisi 2023/2024") == ("anggota_divisi", None)
    assert parse_office_text("Sekbend Humas 2023/2024") == ("sekbend_humas", None)
    assert parse_office_text("Sekretaris/Bendahara Divisi Pendidikan") == (
        "sekbend_pendidikan",
        None,
    )
    assert parse_office_text("MnB Comdev") == ("mnb_community_development", None)
    assert parse_office_text("Ketua Humas") == ("humas", None)
    assert parse_office_text("Ketua Comdev") == ("community_development", None)
    assert parse_office_text("Wakil Humas") == ("humas", None)
    start, end, _ = parse_period("2023/2024")
    assert (start, end) == (2023, 2024)
    start, end, _ = parse_period("2023/24")
    assert (start, end) == (2023, 2024)
    entries = parse_role_entries("Ketua 2023/2024; Humas 2022/2023; PJ Fakultas Hukum 2021/2022")
    codes = [e["office_code"] for e in entries]
    assert codes == ["ketua", "humas", "pj_fakultas"]
    assert entries[2]["scope"] == "hukum"
    assert term_years(2022, 2025) == [(2022, 2023), (2023, 2024), (2024, 2025)]
    assert term_years(2023, 2024) == [(2023, 2024)]


def test_riwayat_jabatan_per_periode(app):
    alumni_id = _insert_city(app, name="Dina Masa", email="dina.masa@example.com")
    with app.app_context():
        db = get_db()
        assert add_roles(
            db,
            alumni_id,
            {
                "office_code": "anggota_divisi",
                "period_start": 2022,
                "period_end": 2023,
            },
        )
        assert add_roles(
            db,
            alumni_id,
            {"office_code": "humas", "period_start": 2023, "period_end": 2024},
        )
        assert add_roles(
            db,
            alumni_id,
            {
                "office_code": "wakil_ketua",
                "period_start": 2024,
                "period_end": 2025,
            },
        )
        assert add_roles(
            db,
            alumni_id,
            {"office_code": "ketua", "period_start": 2020, "period_end": 2022},
        ) == 2
        db.commit()
        rows = db.execute(
            """
            SELECT office_code, period_start FROM alumni_kse_roles
            WHERE alumni_id = ? ORDER BY period_start, office_code
            """,
            (alumni_id,),
        ).fetchall()
        pairs = [(r["office_code"], r["period_start"]) for r in rows]
        assert ("ketua", 2020) in pairs
        assert ("ketua", 2021) in pairs
        assert ("anggota_divisi", 2022) in pairs
        assert ("humas", 2023) in pairs
        assert ("wakil_ketua", 2024) in pairs
        assert add_roles(
            db,
            alumni_id,
            {"office_code": "humas", "period_start": 2023, "period_end": 2024},
        ) == 0
        chart_2023 = build_org_chart(db, 2023)
        humas = next(s for b in chart_2023["branches"] for s in b["seats"] if s["code"] == "humas")
        ketua = next(s for b in chart_2023["branches"] for s in b["seats"] if s["code"] == "ketua")
        wakil = next(
            s for b in chart_2023["branches"] for s in b["seats"] if s["code"] == "wakil_ketua"
        )
        assert any(p["full_name"] == "Dina Masa" for p in humas["people"])
        assert not any(p["full_name"] == "Dina Masa" for p in ketua["people"])
        assert not any(p["full_name"] == "Dina Masa" for p in wakil["people"])
        top = top_offices_for(db, [alumni_id])[alumni_id]
        assert top["office_code"] == "wakil_ketua"
        assert top["period_start"] == 2024
        decorated = decorate_alumni_rows(
            db, db.execute("SELECT * FROM alumni WHERE id = ?", (alumni_id,)).fetchall()
        )
        assert decorated[0]["office_label"] == "Wakil Ketua"
        assert decorated[0]["office_period"] == "2024/2025"


def test_semua_periode_urut_masa_menjabat_bukan_abjad(app, client):
    lama = _insert_city(app, name="Zahra Lama", email="zahra.lama@example.com")
    kini = _insert_city(app, name="Ahmad Kini", email="ahmad.kini@example.com")
    with app.app_context():
        db = get_db()
        add_roles(db, lama, {"office_code": "ketua", "period_start": 2020, "period_end": 2021})
        add_roles(db, kini, {"office_code": "ketua", "period_start": 2024, "period_end": 2025})
        db.commit()
        people = build_org_chart(db, None)["tree"]["heads"][0]["people"]
        names = [person["full_name"] for person in people]
        assert names == ["Zahra Lama", "Ahmad Kini"]
        assert [person["period_start"] for person in people] == [2020, 2024]
    body = client.get("/struktur?periode=semua").get_data(as_text=True)
    assert body.index("Zahra Lama") < body.index("Ahmad Kini")


def test_anggota_divisi_spesifik_dan_generik(app):
    generic_id = _insert_city(app, name="Fajar Generik", email="fajar.generik@example.com")
    member_id = _insert_city(app, name="Gita Humas", email="gita.humas@example.com")
    with app.app_context():
        db = get_db()
        assert add_roles(
            db,
            generic_id,
            {
                "office_code": "anggota_divisi",
                "period_start": 2023,
                "period_end": 2024,
            },
        )
        assert add_roles(
            db,
            member_id,
            {
                "office_code": "anggota_humas",
                "period_start": 2023,
                "period_end": 2024,
            },
        )
        assert (
            add_roles(
                db,
                member_id,
                {"office_code": "bukan_jabatan", "period_start": 2023, "period_end": 2024},
            )
            == 0
        )
        db.commit()
        entries = parse_role_entries(
            "Anggota Humas 2023/2024; Anggota Divisi 2022/2023"
        )
        assert [e["office_code"] for e in entries] == ["anggota_humas", "anggota_divisi"]
        chart = build_org_chart(db, 2023)
        assert [s["code"] for s in chart["tree"]["heads"]] == ["ketua", "wakil_ketua"]
        assert [s["code"] for s in chart["tree"]["officers"]] == ["sekretaris", "bendahara"]
        humas = next(s for b in chart["branches"] for s in b["seats"] if s["code"] == "humas")
        assert humas["code"] == "humas"
        unspecified = chart["tree"]["unspecified"]
        assert unspecified is not None
        assert any(p["full_name"] == "Fajar Generik" for p in unspecified["people"])
        unit = next(u for u in chart["tree"]["divisions"] if u["code"] == "humas")
        assert any(p["full_name"] == "Gita Humas" for p in unit["members"])
        assert not any(p["full_name"] == "Fajar Generik" for p in unit["members"])
        assert [s["code"] for s in unit["officers"]] == ["sekbend_humas"]
        assert chart["tree"]["wings"] == []
        comdev = next(
            u for u in chart["tree"]["divisions"] if u["code"] == "community_development"
        )
        assert [s["code"] for s in comdev["officers"]] == ["sekbend_community_development"]
        db.execute(
            """
            INSERT INTO alumni_kse_roles (
              alumni_id, office_code, period_start, period_end, period_raw,
              scope, title_raw, created_at
            ) VALUES (?, 'jabatan_lama_tidak_dikenal', 2023, 2024, '2023/2024', NULL, 'Lama', ?)
            """,
            (generic_id, utcnow()),
        )
        db.commit()
        chart_ok = build_org_chart(db, 2023)
        assert chart_ok["tree"]["unspecified"] is not None


def test_halaman_struktur_anggota_lama(client, app):
    alumni_id = _insert_city(app, name="Hasan Lama", email="hasan.lama@example.com")
    with app.app_context():
        db = get_db()
        add_roles(
            db,
            alumni_id,
            {
                "office_code": "anggota_divisi",
                "period_start": 2023,
                "period_end": 2024,
            },
        )
        db.commit()
    page = client.get("/struktur?periode=2023")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "Hasan Lama" in body
    assert "Anggota Divisi (belum spesifik)" in body
    assert "0812" not in body
    login_admin(client)
    form = client.get("/admin/alumni/1/ubah").get_data(as_text=True)
    assert "Anggota Divisi Hubungan Masyarakat" in form
    assert "Sekbend Hubungan Masyarakat" in form
    assert "Sekbend dan pengurus unit" in form
    assert "<optgroup" in form


def test_pecah_rentang_lama(app):
    alumni_id = _insert_city(app, name="Eka Rentang", email="eka.rentang@example.com")
    with app.app_context():
        db = get_db()
        db.execute(
            """
            INSERT INTO alumni_kse_roles (
              alumni_id, office_code, period_start, period_end, period_raw,
              scope, title_raw, created_at
            ) VALUES (?, 'sekretaris', 2021, 2024, '2021-2024', NULL, 'Sekretaris', ?)
            """,
            (alumni_id, utcnow()),
        )
        db.commit()
        assert split_wide_role_rows(db) == 3
        db.commit()
        years = [
            r["period_start"]
            for r in db.execute(
                "SELECT period_start FROM alumni_kse_roles WHERE alumni_id = ? ORDER BY period_start",
                (alumni_id,),
            )
        ]
        assert years == [2021, 2022, 2023]


def test_template_memuat_kolom_jabatan():
    mapping = _header_map(list(TEMPLATE_HEADERS))
    assert mapping["kse_roles"] == "jabatan_kse"


def test_impor_jabatan_kse(app, tmp_path):
    path = tmp_path / "roles.csv"
    path.write_text(
        "nama,email,jabatan_kse\n"
        "Rina Role,rina.role@example.com,Ketua 2023/2024; Humas 2022/2023\n",
        encoding="utf-8",
    )
    with app.app_context():
        import_csv_path(path, source="test")
        alumni_id = get_db().execute(
            "SELECT id FROM alumni WHERE email_normalized = ?",
            ("rina.role@example.com",),
        ).fetchone()["id"]
        rows = get_db().execute(
            "SELECT office_code, period_start FROM alumni_kse_roles WHERE alumni_id = ? ORDER BY office_code",
            (alumni_id,),
        ).fetchall()
        assert [r["office_code"] for r in rows] == ["humas", "ketua"]
        chart = build_org_chart(get_db(), 2023)
        ketua = next(s for b in chart["branches"] for s in b["seats"] if s["code"] == "ketua")
        assert ketua["people"][0]["full_name"] == "Rina Role"


def test_admin_tambah_jabatan_dan_filter_direktori(client, app):
    login_admin(client)
    token = csrf_token(client, "/admin/alumni/1/ubah")
    res = client.post(
        "/admin/alumni/1/jabatan",
        data={"csrf": token, "office_code": "sekretaris", "period": "2023/2024"},
        follow_redirects=True,
    )
    body = res.get_data(as_text=True)
    assert "Jabatan ditambahkan." in body
    assert "Sekretaris" in body
    guest = app.test_client()
    public = guest.get("/alumni/1").get_data(as_text=True)
    assert "Sekretaris" in public
    assert "081234567890" not in public
    directory = client.get("/direktori?jabatan=sekretaris").get_data(as_text=True)
    assert "Aisyah Uji" in directory
    empty = client.get("/direktori?jabatan=ketua").get_data(as_text=True)
    assert "Aisyah Uji" not in empty
    struktur = client.get("/struktur?periode=2023").get_data(as_text=True)
    assert "Aisyah Uji" in struktur
    assert "Ketua Paguyuban" in struktur
    assert 'class="org-tree"' in struktur
    stats = client.get("/statistik").get_data(as_text=True)
    assert "Pernah jadi pengurus" in stats
    assert "Sekretaris" in stats


def test_pj_fakultas_wajib_memilih_fakultas(client):
    login_admin(client)
    token = csrf_token(client, "/admin/alumni/1/ubah")
    res = client.post(
        "/admin/alumni/1/jabatan",
        data={"csrf": token, "office_code": "pj_fakultas", "period": "2022/2023"},
        follow_redirects=True,
    )
    assert "wajib memilih fakultas" in res.get_data(as_text=True)
    token = csrf_token(client, "/admin/alumni/1/ubah")
    res = client.post(
        "/admin/alumni/1/jabatan",
        data={
            "csrf": token,
            "office_code": "pj_fakultas",
            "period": "2022/2023",
            "scope": "pertanian",
        },
        follow_redirects=True,
    )
    assert "Penanggung Jawab Fakultas Pertanian" in res.get_data(as_text=True)


def test_form_periode_wajib_dan_jabatan_sama_beda_tahun(client):
    login_admin(client)
    token = csrf_token(client, "/admin/alumni/1/ubah")
    res = client.post(
        "/admin/alumni/1/jabatan",
        data={"csrf": token, "office_code": "ketua"},
        follow_redirects=True,
    )
    assert "Periode wajib" in res.get_data(as_text=True)
    token = csrf_token(client, "/admin/alumni/1/ubah")
    first = client.post(
        "/admin/alumni/1/jabatan",
        data={"csrf": token, "office_code": "ketua", "period": "2022/2023"},
        follow_redirects=True,
    )
    assert "Jabatan ditambahkan." in first.get_data(as_text=True)
    token = csrf_token(client, "/admin/alumni/1/ubah")
    second = client.post(
        "/admin/alumni/1/jabatan",
        data={"csrf": token, "office_code": "ketua", "period": "2024/2025"},
        follow_redirects=True,
    )
    body = second.get_data(as_text=True)
    assert "Jabatan ditambahkan." in body
    assert "2022/2023" in body
    assert "2024/2025" in body
    only_2022 = client.get("/struktur?periode=2022").get_data(as_text=True)
    assert "Aisyah Uji" in only_2022
    only_2023 = client.get("/struktur?periode=2023").get_data(as_text=True)
    assert "Aisyah Uji" not in only_2023
    only_2024 = client.get("/struktur?periode=2024").get_data(as_text=True)
    assert "Aisyah Uji" in only_2024


def test_peta_menampilkan_nama_tanpa_pii(client, app):
    with app.app_context():
        get_db().execute(
            "UPDATE alumni SET lat = -0.95, lng = 100.35, city = 'Padang' WHERE id = 1"
        )
        get_db().commit()
    _insert_city(app, name="Budi Peta", email="budi.peta@example.com")
    _insert_city(app, name="Citra Peta", email="citra.peta@example.com")
    _insert_city(app, name="Rahasia Peta", email="rahasia.peta@example.com", listed=0)
    payload = client.get("/api/map-points").get_json()
    assert len(payload["points"]) == 1
    names = [person["full_name"] for person in payload["points"][0]["alumni"]]
    assert "Aisyah Uji" in names
    assert "Budi Peta" in names
    assert "Citra Peta" in names
    assert "Rahasia Peta" not in names
    blob = str(payload)
    assert "0812" not in blob
    assert "aisyah.uji@" not in blob
    assert "Jl. Rahasia" not in blob
    assert "date_of_birth" not in blob
    assert "phone" not in blob
    for person in payload["points"][0]["alumni"]:
        assert set(person) <= {"id", "full_name", "faculty_code", "cohort_year", "major_normalized"}
    page = client.get("/peta").get_data(as_text=True)
    assert "Aisyah Uji" in page
    assert "Budi Peta" in page
    assert "Rahasia Peta" not in page
    assert "081234567890" not in page


def test_peta_satu_orang_tetap_disembunyikan(client, app):
    with app.app_context():
        get_db().execute("UPDATE alumni SET lat = -0.95, lng = 100.35 WHERE id = 1")
        get_db().commit()
    payload = client.get("/api/map-points").get_json()
    assert payload["points"] == []
    assert "Aisyah" not in str(payload)


def test_acuan_umum_memakai_sekbend_tanpa_sayap_comdev(app):
    with app.app_context():
        chart = build_org_chart(get_db(), 2024)
        assert chart["tree"]["wings"] == []
        assert [s["code"] for s in chart["tree"]["heads"]] == ["ketua", "wakil_ketua"]
        assert [s["code"] for s in chart["tree"]["officers"]] == ["sekretaris", "bendahara"]
        humas = next(u for u in chart["tree"]["divisions"] if u["code"] == "humas")
        assert [s["code"] for s in humas["officers"]] == ["sekbend_humas"]
        comdev = next(
            u for u in chart["tree"]["divisions"] if u["code"] == "community_development"
        )
        assert [s["code"] for s in comdev["officers"]] == ["sekbend_community_development"]


def test_periode_bisa_disalin_dari_comdev_terpisah(app):
    from alumni_web.org_layout import customize_period, reset_period

    alumni_id = _insert_city(app, name="Vicky Comdev", email="vicky.comdev@example.com")
    with app.app_context():
        db = get_db()
        assert add_roles(
            db,
            alumni_id,
            {
                "office_code": "mnb_community_development",
                "period_start": 2023,
                "period_end": 2024,
            },
        )
        db.commit()
        before = build_org_chart(db, 2023)
        assert before["tree"]["wings"] == []
        leftovers = [s["code"] for s in before["tree"]["outside"]]
        assert "mnb_community_development" in leftovers
        customize_period(db, 2023, "comdev_terpisah", replace=True)
        db.commit()
        chart = build_org_chart(db, 2023)
        assert chart["layout"]["is_custom"]
        assert not any(u["code"] == "community_development" for u in chart["tree"]["divisions"])
        wing = next(u for u in chart["tree"]["wings"] if u["code"] == "community_development")
        assert [s["code"] for s in wing["officers"]] == [
            "sekbend_community_development",
            "mnb_community_development",
        ]
        assert any(p["full_name"] == "Vicky Comdev" for p in wing["officers"][1]["people"])
        reset_period(db, 2023)
        db.commit()
        after = build_org_chart(db, 2023)
        assert after["tree"]["wings"] == []


def test_pengurus_menyesuaikan_bagan_periode(client, app):
    assert client.get("/admin/struktur").status_code == 403
    login_admin(client)
    page = client.get("/admin/struktur")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "Tahun kepengurusan" in body
    assert "Template bagan" in body
    assert 'class="org-tabs"' in body
    admin_home = client.get("/admin").get_data(as_text=True)
    assert 'href="/admin/struktur"' in admin_home
    assert "Kelola akun" in admin_home
    assert "Template bagan" not in admin_home
    acuan = client.get("/admin/acuan").get_data(as_text=True)
    assert "Template umum" in acuan
    assert "Comdev terpisah" in acuan
    assert "Sekbend" in acuan
    token = csrf_token(client, "/admin/struktur?periode=2024")
    copied = client.post(
        "/admin/struktur/salin",
        data={"csrf": token, "periode": "2024", "sumber": "comdev_terpisah"},
        follow_redirects=True,
    )
    assert "Bagan 2024/2025 disiapkan" in copied.get_data(as_text=True)
    public = client.get("/struktur?periode=2024").get_data(as_text=True)
    assert "MnB" in public
    assert "Sesuaikan bagan" in public
    token = csrf_token(client, "/admin/struktur?periode=2024")
    added = client.post(
        "/admin/struktur/unit",
        data={
            "csrf": token,
            "periode": "2024",
            "title": "Riset",
            "unit_kind": "division",
            "lead_role": "Koordinator",
        },
        follow_redirects=True,
    )
    assert "Unit Riset ditambahkan" in added.get_data(as_text=True)
    form = client.get("/admin/alumni/1/ubah").get_data(as_text=True)
    assert "Sekbend Riset" in form
    token = csrf_token(client, "/admin/alumni/1/ubah")
    assigned = client.post(
        "/admin/alumni/1/jabatan",
        data={"csrf": token, "office_code": "sekbend_riset", "period": "2024/2025"},
        follow_redirects=True,
    )
    assert "Jabatan ditambahkan." in assigned.get_data(as_text=True)
    struktur = client.get("/struktur?periode=2024").get_data(as_text=True)
    assert "Riset" in struktur
    assert "Aisyah Uji" in struktur


def test_halaman_bagan_memisahkan_template_dan_periode(client, app):
    """Template dan periode adalah dua halaman berbeda."""
    alumni_id = _insert_city(app, name="Nadia Bagan", email="nadia.bagan@example.com")
    with app.app_context():
        db = get_db()
        add_roles(db, alumni_id, {"office_code": "ketua", "period_start": 2023, "period_end": 2024})
        db.commit()

    login_admin(client)
    body = client.get("/admin/struktur").get_data(as_text=True)
    assert "Pilih tahun" in body
    assert "Buka tahun lain" in body
    assert "2023/2024" in body
    assert "Sunting acuan bagan" not in body
    assert "Pilih acuan" not in body
    assert "Pilih template" not in body
    assert "pola untuk bagan baru" not in body

    acuan = client.get("/admin/acuan").get_data(as_text=True)
    assert "Pilih template" in acuan
    assert "Template umum" in acuan
    assert "Bawaan" in acuan
    assert "Tambah template" in acuan
    kotak = acuan.split('class="scope-bar"', 1)[1].split("</section>", 1)[0]
    assert "Nama template" in kotak
    assert "Simpan nama" in kotak
    assert 'name="title"' in kotak
    assert "Buat template" not in kotak
    assert "Jadikan bawaan" not in kotak
    assert "Pilih tahun" not in acuan
    assert "Buka tahun lain" not in acuan
    assert "Sunting bagan kepengurusan" not in acuan
    alias = client.get("/admin/template")
    assert alias.status_code == 200
    assert "Template bagan" in alias.get_data(as_text=True)

    # Tahun yang sudah punya riwayat langsung punya salinan sendiri.
    tahun = client.get("/admin/struktur?periode=2023").get_data(as_text=True)
    assert "Bagan sendiri" in tahun
    assert "Perubahan hanya untuk tahun ini" in tahun
    assert "Ganti dari template" in tahun
    assert 'value="umum" selected' in tahun
    assert 'value="comdev_terpisah"' in tahun
    assert "Ganti dengan acuan umum sekarang" not in tahun
    assert "Sunting acuan bagan" not in tahun

    # Tahun tanpa riwayat masih mengikuti template, sampai disiapkan.
    kosong = client.get("/admin/struktur?periode=2026").get_data(as_text=True)
    assert "Mengikuti template" in kosong
    assert "Siapkan bagan 2026/2027" in kosong
    assert 'value="umum" selected' in kosong
    assert 'value="comdev_terpisah"' in kosong


def test_dua_cara_menambah_jabatan_terpisah(client, app):
    """Satu formulir dengan dua kolom yang saling menggantikan membingungkan.

    Sekarang keduanya form terpisah: pilih dari daftar, atau buat baru.
    """
    from alumni_web.org_layout import template_by_slug, unused_offices_for_unit

    login_admin(client)
    body = client.get("/admin/acuan").get_data(as_text=True)
    assert "Cara 1 — pakai jabatan yang sudah dikenal" in body
    assert "Cara 2 — buat jabatan yang belum ada" in body
    assert "Buat jabatan baru di sebelah" not in body, "pilihan lama yang ambigu"

    with app.app_context():
        db = get_db()
        umum = template_by_slug(db, "umum")
        humas = next(unit for unit in umum["units"] if unit["code"] == "humas")

    # Cara 2: hanya nama, singkatan, dan posisi — tanpa memilih kode jabatan.
    token = csrf_token(client, "/admin/acuan")
    dibuat = client.post(
        "/admin/struktur/jabatan",
        data={
            "csrf": token,
            "acuan": "umum",
            "unit_id": str(humas["id"]),
            "label": "Manager and Business",
            "short": "MnB",
            "seat_kind": "officer",
        },
        follow_redirects=True,
    )
    assert "Jabatan ditambahkan ke bagan." in dibuat.get_data(as_text=True)

    with app.app_context():
        db = get_db()
        umum = template_by_slug(db, "umum")
        humas = next(unit for unit in umum["units"] if unit["code"] == "humas")
        labels = [seat["label"] for seat in humas["seats"]]
    assert "Manager and Business" in labels

    # Cara 1: jabatan yang baru dibuat kini bisa dipilih di unit lain.
    with app.app_context():
        db = get_db()
        umum = template_by_slug(db, "umum")
        dana = next(unit for unit in umum["units"] if unit["code"] != "humas" and unit["unit_kind"] == "division")
        tersedia = [item["code"] for item in unused_offices_for_unit(db, dana["id"])]
        unit_id = dana["id"]
    assert any(code.startswith("mnb") for code in tersedia)
    token = csrf_token(client, "/admin/acuan")
    dipakai = client.post(
        "/admin/struktur/jabatan",
        data={
            "csrf": token,
            "acuan": "umum",
            "unit_id": str(unit_id),
            "office_code": next(c for c in tersedia if c.startswith("mnb")),
        },
        follow_redirects=True,
    )
    assert "Jabatan ditambahkan ke bagan." in dipakai.get_data(as_text=True)


def test_urutan_hanya_dalam_satu_tingkat(client, app):
    """Naik/turun di pengaturan tidak boleh menjanjikan pohon bebas."""
    from alumni_web.org_layout import template_by_slug

    login_admin(client)
    page = client.get("/admin/acuan").get_data(as_text=True)
    assert "Puncak bagan" in page
    assert "Dasar bagan" in page
    assert "Geser kiri" in page
    assert "Geser kanan" in page
    assert ">Naik<" not in page
    assert ">Turun<" not in page
    assert "tombol geser hanya muncul jika posisinya di bagan itu benar-benar berubah" in page.lower()

    with app.app_context():
        db = get_db()
        umum = template_by_slug(db, "umum")
        inti = next(unit for unit in umum["units"] if unit["unit_kind"] == "core")
        pertama = next(unit for unit in umum["units"] if unit["unit_kind"] == "division")
        kedua = next(
            unit
            for unit in umum["units"]
            if unit["unit_kind"] == "division" and unit["id"] != pertama["id"]
        )
        ketua = next(seat for seat in inti["seats"] if seat["office_code"] == "ketua")
        assert not inti["can_shift_prev"]
        assert not inti["can_shift_next"]
        assert ketua["can_shift_next"]
        assert not ketua["can_shift_prev"]

    token = csrf_token(client, "/admin/acuan")
    ditolak = client.post(
        f"/admin/struktur/unit/{inti['id']}/urut",
        data={"csrf": token, "acuan": "umum", "arah": "down"},
        follow_redirects=True,
    )
    assert "tidak bisa dipindah" in ditolak.get_data(as_text=True)

    token = csrf_token(client, "/admin/acuan")
    ditukar = client.post(
        f"/admin/struktur/jabatan/{ketua['id']}/urut",
        data={"csrf": token, "acuan": "umum", "arah": "down"},
        follow_redirects=True,
    )
    assert "Urutan jabatan diperbarui." in ditukar.get_data(as_text=True)

    token = csrf_token(client, "/admin/acuan")
    menyeberang = client.post(
        f"/admin/struktur/jabatan/{ketua['id']}/urut",
        data={"csrf": token, "acuan": "umum", "arah": "down"},
        follow_redirects=True,
    )
    assert "Urutan tidak berubah" in menyeberang.get_data(as_text=True)
    assert "sejenis" in menyeberang.get_data(as_text=True)

    token = csrf_token(client, "/admin/acuan")
    divisi = client.post(
        f"/admin/struktur/unit/{kedua['id']}/urut",
        data={"csrf": token, "acuan": "umum", "arah": "up"},
        follow_redirects=True,
    )
    assert "Urutan divisi diperbarui." in divisi.get_data(as_text=True)


def test_pengurus_sayap_geser_kiri_kanan(client, app):
    """Dua pengurus di sayap (Comdev) berjajar di bagan, jadi gesernya kiri-kanan.

    Anggota yang terselip di daftar pengaturan tidak boleh memblokir tukar itu.
    """
    from alumni_web.org_layout import template_by_slug

    login_admin(client)
    page = client.get("/admin/acuan?acuan=comdev_terpisah").get_data(as_text=True)
    assert "Geser kiri" in page
    assert "Geser kanan" in page

    with app.app_context():
        db = get_db()
        bagan = template_by_slug(db, "comdev_terpisah")
        comdev = next(unit for unit in bagan["units"] if unit["code"] == "community_development")
        assert comdev["unit_kind"] == "wing"
        officers = [seat for seat in comdev["seats"] if seat["display_band"] == "officer"]
        lead = next(seat for seat in comdev["seats"] if seat["display_band"] == "lead")
        member = next(seat for seat in comdev["seats"] if seat["display_band"] == "member")
        assert len(officers) == 2
        assert officers[0]["shift_axis"] == "horizontal"
        assert officers[0]["shift_next_label"] == "Geser kanan"
        assert officers[1]["shift_prev_label"] == "Geser kiri"
        db.execute("UPDATE org_seats SET sort_order = 0 WHERE id = ?", (lead["id"],))
        db.execute("UPDATE org_seats SET sort_order = 1 WHERE id = ?", (officers[0]["id"],))
        db.execute("UPDATE org_seats SET sort_order = 2 WHERE id = ?", (member["id"],))
        db.execute("UPDATE org_seats SET sort_order = 3 WHERE id = ?", (officers[1]["id"],))
        db.commit()
        kiri_id = officers[0]["id"]
        kanan_id = officers[1]["id"]
        comdev_id = comdev["id"]

    token = csrf_token(client, "/admin/acuan?acuan=comdev_terpisah")
    geser = client.post(
        f"/admin/struktur/jabatan/{kiri_id}/urut",
        data={"csrf": token, "acuan": "comdev_terpisah", "arah": "down"},
        follow_redirects=True,
    )
    body = geser.get_data(as_text=True)
    assert "Urutan jabatan diperbarui." in body
    assert "Jabatan ini tidak bisa ditukar dengan yang di sebelahnya" not in body

    with app.app_context():
        db = get_db()
        rows = db.execute(
            "SELECT id FROM org_seats WHERE id IN (?, ?) ORDER BY sort_order, id",
            (kiri_id, kanan_id),
        ).fetchall()
        assert [row["id"] for row in rows] == [kanan_id, kiri_id]
        ordered = db.execute(
            "SELECT seat_kind FROM org_seats WHERE unit_id = ? ORDER BY sort_order, id",
            (comdev_id,),
        ).fetchall()
        assert [row["seat_kind"] for row in ordered][-1] == "member"
        assert [row["seat_kind"] for row in ordered].count("member") == 1


def test_anggota_selalu_di_bawah_pengurus(client, app):
    """Anggota tidak boleh terselip di antara pengurus, di data maupun di editor."""
    from alumni_web.org_layout import add_existing_seat, template_by_slug

    login_admin(client)
    with app.app_context():
        db = get_db()
        umum = template_by_slug(db, "umum")
        comdev = next(unit for unit in umum["units"] if unit["code"] == "community_development")
        assert add_existing_seat(db, comdev["id"], "mnb_community_development") == (
            "Jabatan ditambahkan ke bagan."
        )
        db.commit()
        kinds = [
            row["seat_kind"]
            for row in db.execute(
                "SELECT seat_kind FROM org_seats WHERE unit_id = ? ORDER BY sort_order, id",
                (comdev["id"],),
            )
        ]
        assert kinds[-1] == "member"
        assert kinds.index("officer") < kinds.index("member")
        page_units = template_by_slug(db, "umum")
        visible = next(unit for unit in page_units["units"] if unit["id"] == comdev["id"])
        assert visible["seats"][-1]["seat_kind"] == "member"
        assert [seat["office_code"] for seat in visible["seats"] if seat["seat_kind"] == "officer"] == [
            "sekbend_community_development",
            "mnb_community_development",
        ]

    body = client.get("/admin/acuan").get_data(as_text=True)
    comdev_html = body.split("Community Development", 1)[1].split("layout-unit", 1)[0]
    assert comdev_html.find("Sekbend") < comdev_html.find("MnB")
    assert comdev_html.find("MnB") < comdev_html.find("Anggota")


def test_periode_bisa_diganti_dari_template_lain(client, app):
    """Bagan tahun yang sudah ada boleh dimulai ulang dari template mana pun."""
    alumni_id = _insert_city(app, name="Doni Ganti", email="doni.ganti@example.com")
    with app.app_context():
        db = get_db()
        add_roles(db, alumni_id, {"office_code": "ketua", "period_start": 2024, "period_end": 2025})
        db.commit()

    login_admin(client)
    before = client.get("/struktur?periode=2024").get_data(as_text=True)
    assert "MnB" not in before
    token = csrf_token(client, "/admin/struktur?periode=2024")
    ganti = client.post(
        "/admin/struktur/salin",
        data={"csrf": token, "periode": "2024", "sumber": "comdev_terpisah"},
        follow_redirects=True,
    )
    body = ganti.get_data(as_text=True)
    assert "diganti dengan template yang dipilih" in body
    public = client.get("/struktur?periode=2024").get_data(as_text=True)
    assert "MnB" in public


def test_ubah_template_tidak_mengubah_bagan_yang_sudah_tampil(app):
    """Menyunting template hanya berlaku untuk periode yang baru muncul."""
    from alumni_web.org_layout import add_standard_unit, period_blueprint, template_by_slug

    alumni_id = _insert_city(app, name="Rina Lama", email="rina.lama@example.com")
    with app.app_context():
        db = get_db()
        add_roles(
            db,
            alumni_id,
            {"office_code": "ketua", "period_start": 2023, "period_end": 2024},
        )
        db.commit()
        before = period_blueprint(db, 2023)
        assert before is not None
        assert not any(unit["title"] == "Riset" for unit in before["units"])

        umum = template_by_slug(db, "umum")
        add_standard_unit(db, umum["id"], title="Riset", unit_kind="division", lead_role="Koordinator")
        db.commit()

        after = period_blueprint(db, 2023)
        assert not any(unit["title"] == "Riset" for unit in after["units"])
        chart_lama = build_org_chart(db, 2023)
        assert not any(unit["title"] == "Riset" for unit in chart_lama["tree"]["divisions"])

    baru = _insert_city(app, name="Sari Baru", email="sari.baru@example.com")
    with app.app_context():
        db = get_db()
        add_roles(
            db,
            baru,
            {"office_code": "ketua", "period_start": 2026, "period_end": 2027},
        )
        db.commit()
        chart_baru = build_org_chart(db, 2026)
        assert any(unit["title"] == "Riset" for unit in chart_baru["tree"]["divisions"])


def test_migrasi_skema_lama_menyiapkan_acuan(app):
    from alumni_web.db import migrate

    with app.app_context():
        db = get_db()
        db.execute("PRAGMA foreign_keys = OFF")
        db.executescript(
            """
            DROP TABLE IF EXISTS org_seats;
            DROP TABLE IF EXISTS org_units;
            DROP TABLE IF EXISTS org_blueprints;
            DROP TABLE IF EXISTS kse_office_defs;
            """
        )
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA user_version = 5")
        db.commit()
        migrate(db)
        db.commit()
        umum = db.execute(
            "SELECT slug, title, is_default FROM org_blueprints WHERE slug = 'umum'"
        ).fetchone()
        assert umum
        assert umum["title"] == "Template umum"
        assert umum["is_default"] == 1
        chart = build_org_chart(db, 2024)
        assert [s["code"] for s in chart["tree"]["heads"]] == ["ketua", "wakil_ketua"]
        humas = next(u for u in chart["tree"]["divisions"] if u["code"] == "humas")
        assert [s["code"] for s in humas["officers"]] == ["sekbend_humas"]


def test_bagan_tanpa_acuan_tetap_memakai_pola_umum(app):
    with app.app_context():
        seats = {item["code"]: item for item in org_seats(db=get_db())}
        tree = build_org_tree(seats, {"units": []})
        assert [s["code"] for s in tree["heads"]] == ["ketua", "wakil_ketua"]
        comdev = next(u for u in tree["divisions"] if u["code"] == "community_development")
        assert [s["code"] for s in comdev["officers"]] == ["sekbend_community_development"]


def test_jabatan_inti_tidak_boleh_dilepas(app):
    from alumni_web.org_layout import delete_seat, template_by_slug

    with app.app_context():
        db = get_db()
        umum = template_by_slug(db, "umum")
        inti = next(unit for unit in umum["units"] if unit["code"] == "inti")
        ketua = next(seat for seat in inti["seats"] if seat["office_code"] == "ketua")
        assert "tidak boleh dilepas" in delete_seat(db, ketua["id"])


def test_salin_bagan_wajib_csrf(client):
    login_admin(client)
    res = client.post(
        "/admin/struktur/salin",
        data={"periode": "2024", "sumber": "umum"},
    )
    assert res.status_code == 400
    assert "Kesalahan 400" in res.get_data(as_text=True)
    for path in (
        "/admin/acuan/baru",
        "/admin/acuan/bawaan",
        "/admin/acuan/ubah",
        "/admin/acuan/hapus",
        "/admin/template/baru",
    ):
        blocked = client.post(path, data={"title": "X", "sumber": "umum", "acuan": "umum"})
        assert blocked.status_code == 400, path


def test_bisa_membuat_template_dan_menjadikannya_bawaan(client, app):
    login_admin(client)
    token = csrf_token(client, "/admin/acuan")
    dibuat = client.post(
        "/admin/acuan/baru",
        data={"csrf": token, "title": "Bagan 2027", "sumber": "umum"},
        follow_redirects=True,
    )
    html = dibuat.get_data(as_text=True)
    assert "Template Bagan 2027 sudah dibuat" in html
    assert "Bagan 2027" in html

    token = csrf_token(client, "/admin/acuan?acuan=bagan_2027")
    bawaan = client.post(
        "/admin/acuan/bawaan",
        data={"csrf": token, "acuan": "bagan_2027"},
        follow_redirects=True,
    )
    assert "sekarang dipakai sebagai template bawaan" in bawaan.get_data(as_text=True)

    with app.app_context():
        from alumni_web.org_layout import default_template_slug

        db = get_db()
        assert default_template_slug(db) == "bagan_2027"
        assert db.execute(
            "SELECT is_default FROM org_blueprints WHERE slug = 'umum'"
        ).fetchone()["is_default"] == 0

    kosong = client.get("/admin/struktur?periode=2028").get_data(as_text=True)
    assert 'value="bagan_2027" selected' in kosong
    assert "Bagan 2027 (bawaan)" in kosong


def test_tahun_baru_mengikuti_template_bawaan(app):
    from alumni_web.org_layout import (
        add_standard_unit,
        default_template_slug,
        period_blueprint,
        set_default_template,
        template_by_slug,
    )

    with app.app_context():
        db = get_db()
        comdev = template_by_slug(db, "comdev_terpisah")
        add_standard_unit(db, comdev["id"], title="Riset", unit_kind="division", lead_role="Koordinator")
        ok, _ = set_default_template(db, "comdev_terpisah")
        assert ok
        db.commit()
        assert default_template_slug(db) == "comdev_terpisah"

    alumni_id = _insert_city(app, name="Tono Baru", email="tono.baru@example.com")
    with app.app_context():
        db = get_db()
        add_roles(
            db,
            alumni_id,
            {"office_code": "ketua", "period_start": 2028, "period_end": 2029},
        )
        db.commit()
        bagan = period_blueprint(db, 2028)
        assert bagan is not None
        assert any(unit["title"] == "Riset" for unit in bagan["units"])
        assert any(
            unit["code"] == "community_development" and unit["unit_kind"] == "wing"
            for unit in bagan["units"]
        )


def test_tidak_bisa_hapus_template_bawaan_atau_satu_satunya(client, app):
    from alumni_web.org_layout import delete_template, list_templates

    login_admin(client)
    token = csrf_token(client, "/admin/acuan")
    ditolak = client.post(
        "/admin/acuan/hapus",
        data={"csrf": token, "acuan": "umum"},
        follow_redirects=True,
    )
    assert "Jadikan template lain sebagai bawaan dulu" in ditolak.get_data(as_text=True)

    with app.app_context():
        db = get_db()
        for item in list_templates(db):
            if item["slug"] != "umum":
                db.execute("DELETE FROM org_blueprints WHERE id = ?", (item["id"],))
        db.commit()
        ok, message = delete_template(db, "umum")
        assert not ok
        assert "satu-satunya template" in message


def test_ganti_nama_kosong_ditolak(client):
    login_admin(client)
    token = csrf_token(client, "/admin/acuan")
    res = client.post(
        "/admin/acuan/ubah",
        data={"csrf": token, "acuan": "umum", "title": "   ", "notes": ""},
        follow_redirects=True,
    )
    assert "Nama template tidak boleh kosong" in res.get_data(as_text=True)


def test_buat_template_tanpa_nama_ditolak(client):
    login_admin(client)
    token = csrf_token(client, "/admin/acuan")
    res = client.post(
        "/admin/acuan/baru",
        data={"csrf": token, "title": "", "sumber": "umum"},
        follow_redirects=True,
    )
    assert "Nama template tidak boleh kosong" in res.get_data(as_text=True)


def test_slug_template_asing_dialihkan_ke_bawaan(client):
    login_admin(client)
    res = client.get("/admin/acuan?acuan=tidak-ada")
    assert res.status_code == 302
    assert "acuan=umum" in res.headers["Location"]


def test_ganti_nama_template(client):
    login_admin(client)
    token = csrf_token(client, "/admin/acuan")
    ubah = client.post(
        "/admin/acuan/ubah",
        data={"csrf": token, "acuan": "umum", "title": "Pola inti", "notes": "Untuk tahun baru"},
        follow_redirects=True,
    )
    html = ubah.get_data(as_text=True)
    assert "Nama template sudah disimpan" in html
    assert "Pola inti" in html


def test_bisa_hapus_template_cadangan(client):
    login_admin(client)
    token = csrf_token(client, "/admin/acuan")
    client.post(
        "/admin/acuan/baru",
        data={"csrf": token, "title": "Cadangan uji", "sumber": "umum"},
        follow_redirects=True,
    )
    token = csrf_token(client, "/admin/acuan?acuan=cadangan_uji")
    hapus = client.post(
        "/admin/acuan/hapus",
        data={"csrf": token, "acuan": "cadangan_uji"},
        follow_redirects=True,
    )
    html = hapus.get_data(as_text=True)
    assert "Template Cadangan uji sudah dihapus" in html
    assert 'href="/admin/template?acuan=cadangan_uji"' not in html
    assert 'href="/admin/acuan?acuan=cadangan_uji"' not in html


def test_schema_sql_aman_untuk_tabel_lama_tanpa_is_default(app):
    from alumni_web.db import SCHEMA_PATH, migrate

    with app.app_context():
        db = get_db()
        db.execute("PRAGMA foreign_keys = OFF")
        db.executescript(
            """
            DROP TABLE IF EXISTS org_seats;
            DROP TABLE IF EXISTS org_units;
            DROP TABLE IF EXISTS org_blueprints;
            CREATE TABLE org_blueprints (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              kind TEXT NOT NULL,
              slug TEXT,
              period_start INTEGER,
              title TEXT NOT NULL,
              notes TEXT,
              copied_from_id INTEGER,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            INSERT INTO org_blueprints (kind, slug, title, notes, created_at, updated_at)
            VALUES ('template', 'umum', 'Acuan umum', 'lama', '2024-01-01', '2024-01-01');
            """
        )
        db.execute("PRAGMA foreign_keys = ON")
        db.commit()
        db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        migrate(db)
        db.commit()
        cols = {row[1] for row in db.execute("PRAGMA table_info(org_blueprints)")}
        assert "is_default" in cols
        row = db.execute(
            "SELECT title, is_default FROM org_blueprints WHERE slug = 'umum'"
        ).fetchone()
        assert row["title"] == "Template umum"
        assert row["is_default"] == 1


def test_migrasi_skema_lama_menambah_kolom_bawaan(app):
    from alumni_web.db import migrate
    from alumni_web.org_layout import default_template_slug

    with app.app_context():
        db = get_db()
        db.execute("PRAGMA foreign_keys = OFF")
        db.executescript(
            """
            DROP TABLE IF EXISTS org_seats;
            DROP TABLE IF EXISTS org_units;
            DROP TABLE IF EXISTS org_blueprints;
            """
        )
        db.executescript(
            """
            CREATE TABLE org_blueprints (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              kind TEXT NOT NULL,
              slug TEXT,
              period_start INTEGER,
              title TEXT NOT NULL,
              notes TEXT,
              copied_from_id INTEGER,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            INSERT INTO org_blueprints (kind, slug, title, notes, created_at, updated_at)
            VALUES ('template', 'umum', 'Acuan umum', 'lama', '2024-01-01', '2024-01-01');
            """
        )
        db.execute("PRAGMA foreign_keys = ON")
        db.commit()
        migrate(db)
        db.commit()
        cols = {row[1] for row in db.execute("PRAGMA table_info(org_blueprints)")}
        assert "is_default" in cols
        row = db.execute(
            "SELECT title, is_default FROM org_blueprints WHERE slug = 'umum'"
        ).fetchone()
        assert row["title"] == "Template umum"
        assert row["is_default"] == 1
        assert default_template_slug(db) == "umum"


def test_editor_posisi_menjelaskan_cabang_pohon(client):
    login_admin(client)
    html = client.get("/admin/acuan").get_data(as_text=True)
    assert "Tempat di bagan" in html
    assert "Koordinator baru — kartu sendiri di bawah pengurus" in html
    assert "Anggota unit — tidak terikat koordinator" in html
    assert "Susunan di bagan, dari atas ke bawah" in html
    assert "Posisinya di unit ini" not in html
    assert ">Di bawah koordinator<" not in html
    assert "org-editor.js" in html


def test_ubah_bagan_kembali_ke_tempat_yang_disunting(client, app):
    """Sesudah ubah, pengurus kembali ke unit yang baru disunting, bukan ke puncak halaman."""
    from alumni_web.org_layout import template_by_slug

    login_admin(client)
    with app.app_context():
        umum = template_by_slug(get_db(), "umum")
        comdev = next(unit for unit in umum["units"] if unit["code"] == "community_development")
        unit_id = comdev["id"]
        sekbend = next(seat for seat in comdev["seats"] if seat["seat_kind"] == "officer")
        seat_id = sekbend["id"]

    token = csrf_token(client, "/admin/acuan")
    tambah = client.post(
        "/admin/struktur/jabatan",
        data={
            "csrf": token,
            "acuan": "umum",
            "unit_id": str(unit_id),
            "office_code": "mnb_community_development",
        },
        follow_redirects=False,
    )
    assert tambah.status_code == 302
    assert f"#unit-{unit_id}" in tambah.headers["Location"]

    token = csrf_token(client, "/admin/acuan")
    geser = client.post(
        f"/admin/struktur/jabatan/{seat_id}/urut",
        data={"csrf": token, "acuan": "umum", "arah": "down"},
        follow_redirects=False,
    )
    assert geser.status_code == 302
    assert f"#seat-{seat_id}" in geser.headers["Location"]


def test_sayap_comdev_koordinator_berjajar_seperti_divisi(client, app):
    """Sayap Comdev bukan satu kotak penuh: koordinator berjajar seperti kartu divisi."""
    from alumni_web.org_layout import add_custom_seat, period_blueprint, template_by_slug

    alumni_id = _insert_city(app, name="Eka Sayap", email="eka.sayap@example.com")
    with app.app_context():
        db = get_db()
        wing = template_by_slug(db, "comdev_terpisah")
        comdev = next(unit for unit in wing["units"] if unit["code"] == "community_development")
        add_custom_seat(
            db,
            comdev["id"],
            label="Koordinator Media",
            short="Media",
            kind="coordinator",
        )
        add_custom_seat(
            db,
            comdev["id"],
            label="Koordinator Usaha",
            short="Usaha",
            kind="coordinator",
        )
        add_roles(db, alumni_id, {"office_code": "ketua", "period_start": 2024, "period_end": 2025})
        db.commit()

    login_admin(client)
    token = csrf_token(client, "/admin/struktur?periode=2024")
    client.post(
        "/admin/struktur/salin",
        data={"csrf": token, "periode": "2024", "sumber": "comdev_terpisah"},
        follow_redirects=True,
    )
    html = client.get("/struktur?periode=2024").get_data(as_text=True)
    assert 'class="org-wing' not in html
    wing = html.split('id="org-wing-community_development"', 1)[1].split('id="org-pj"', 1)[0]
    assert wing.count('org-unit-kicker">Koordinator') == 2
    assert "Media" in wing
    assert "Usaha" in wing
    assert wing.find("MnB") < wing.find("Media")
    assert 'class="org-units"' in wing
    with app.app_context():
        period = period_blueprint(get_db(), 2024)
        comdev = next(unit for unit in period["units"] if unit["code"] == "community_development")
        assert comdev["unit_kind"] == "wing"
        assert len([seat for seat in comdev["seats"] if seat["seat_kind"] == "coordinator"]) == 2


def test_lead_kedua_tampil_sebagai_koordinator(client, app):
    """Lead tambahan yang dulu dibuang sekarang tampil sebagai koordinator."""
    from alumni_web.org_layout import create_office_def, period_blueprint, template_by_slug

    alumni_id = _insert_city(app, name="Budi Korwil", email="budi.korwil@example.com")
    with app.app_context():
        db = get_db()
        umum = template_by_slug(db, "umum")
        comdev = next(unit for unit in umum["units"] if unit["code"] == "community_development")
        create_office_def(
            db,
            code="korwil_comdev",
            label="Koordinator Wilayah",
            short="Korwil",
            kind="lead",
            unit_code="community_development",
        )
        db.execute(
            """
            INSERT INTO org_seats (
              unit_id, office_code, label, short, seat_kind, pair_group, sort_order, parent_seat_id
            ) VALUES (?, 'korwil_comdev', 'Koordinator Wilayah', 'Korwil', 'lead', NULL, 99, NULL)
            """,
            (comdev["id"],),
        )
        add_roles(
            db,
            alumni_id,
            {"office_code": "korwil_comdev", "period_start": 2024, "period_end": 2025},
        )
        db.commit()

    html = client.get("/struktur?periode=2024").get_data(as_text=True)
    assert "Korwil" in html
    assert "Budi Korwil" in html

    with app.app_context():
        db = get_db()
        period = period_blueprint(db, 2024)
        comdev = next(unit for unit in period["units"] if unit["code"] == "community_development")
        kinds = [seat["seat_kind"] for seat in comdev["seats"] if seat["office_code"] == "korwil_comdev"]
        assert kinds == ["coordinator"]
        chart = build_org_chart(db, 2024)
        unit = next(item for item in chart["tree"]["divisions"] if item["code"] == "community_development")
        assert unit["lead"]["code"] != "korwil_comdev"
        assert any(team["coordinator"]["code"] == "korwil_comdev" for team in unit["teams"])
        names = [person["full_name"] for team in unit["teams"] for person in team["members"]]
        lead_names = [person["full_name"] for person in (unit["lead"] or {}).get("people") or []]
        assert "Budi Korwil" not in lead_names
        assert any(
            person["full_name"] == "Budi Korwil"
            for team in unit["teams"]
            for person in team["coordinator"]["people"]
        )


def test_koordinator_baru_punya_slot_anggota_di_bawah_pengurus(client, app):
    from alumni_web.org_layout import add_custom_seat, add_existing_seat, template_by_slug

    alumni_id = _insert_city(app, name="Sari Media", email="sari.media@example.com")
    with app.app_context():
        db = get_db()
        umum = template_by_slug(db, "umum")
        comdev = next(unit for unit in umum["units"] if unit["code"] == "community_development")
        assert add_existing_seat(db, comdev["id"], "mnb_community_development") == (
            "Jabatan ditambahkan ke bagan."
        )
        assert add_custom_seat(
            db,
            comdev["id"],
            label="Koordinator Media",
            short="Media",
            kind="coordinator",
        ) == "Jabatan ditambahkan ke bagan."
        media = db.execute(
            """
            SELECT id, office_code FROM org_seats
            WHERE unit_id = ? AND seat_kind = 'coordinator'
            """,
            (comdev["id"],),
        ).fetchone()
        assert media
        child = db.execute(
            "SELECT label, parent_seat_id FROM org_seats WHERE parent_seat_id = ?",
            (media["id"],),
        ).fetchone()
        assert child
        assert child["label"].startswith("Anggota")
        add_roles(
            db,
            alumni_id,
            {"office_code": media["office_code"], "period_start": 2025, "period_end": 2026},
        )
        db.commit()

    html = client.get("/struktur?periode=2025").get_data(as_text=True)
    sekbend_at = html.find("Sekbend")
    mnb_at = html.find("MnB")
    media_at = html.find("Media")
    # Ember anggota koordinator berlabel "Anggota" saja — nama koordinatornya
    # sudah jadi judul kartu, jadi yang dicek posisinya, bukan labelnya.
    anggota_at = html.find("<h4>Anggota</h4>", media_at)
    assert sekbend_at != -1
    assert mnb_at != -1
    assert media_at != -1
    assert anggota_at != -1
    assert sekbend_at < media_at
    assert mnb_at < media_at
    assert media_at < anggota_at
    assert "Sari Media" in html


def test_anggota_tim_tidak_masuk_ember_lain(app):
    from alumni_web.org_layout import add_custom_seat, template_by_slug

    orang_a = _insert_city(app, name="Ana Tim A", email="ana.tima@example.com")
    orang_b = _insert_city(app, name="Beni Tim B", email="beni.timb@example.com")
    orang_u = _insert_city(app, name="Cici Unit", email="cici.unit@example.com")
    with app.app_context():
        db = get_db()
        umum = template_by_slug(db, "umum")
        comdev = next(unit for unit in umum["units"] if unit["code"] == "community_development")
        add_custom_seat(db, comdev["id"], label="Koordinator A", short="Kor A", kind="coordinator")
        add_custom_seat(db, comdev["id"], label="Koordinator B", short="Kor B", kind="coordinator")
        coords = list(
            db.execute(
                """
                SELECT id, office_code FROM org_seats
                WHERE unit_id = ? AND seat_kind = 'coordinator'
                ORDER BY sort_order, id
                """,
                (comdev["id"],),
            )
        )
        add_custom_seat(
            db,
            comdev["id"],
            label="Staf A",
            short="Staf A",
            kind="member",
            parent_seat_id=coords[0]["id"],
        )
        add_custom_seat(
            db,
            comdev["id"],
            label="Staf B",
            short="Staf B",
            kind="member",
            parent_seat_id=coords[1]["id"],
        )
        staf_a = db.execute(
            "SELECT office_code FROM org_seats WHERE unit_id = ? AND label = 'Staf A'",
            (comdev["id"],),
        ).fetchone()["office_code"]
        staf_b = db.execute(
            "SELECT office_code FROM org_seats WHERE unit_id = ? AND label = 'Staf B'",
            (comdev["id"],),
        ).fetchone()["office_code"]
        add_roles(db, orang_a, {"office_code": staf_a, "period_start": 2026, "period_end": 2027})
        add_roles(db, orang_b, {"office_code": staf_b, "period_start": 2026, "period_end": 2027})
        add_roles(
            db,
            orang_u,
            {"office_code": "anggota_community_development", "period_start": 2026, "period_end": 2027},
        )
        db.commit()
        chart = build_org_chart(db, 2026)
        unit = next(item for item in chart["tree"]["divisions"] if item["code"] == "community_development")
        by_coord = {team["coordinator"]["short"]: [p["full_name"] for p in team["members"]] for team in unit["teams"]}
        assert by_coord["Kor A"] == ["Ana Tim A"]
        assert by_coord["Kor B"] == ["Beni Tim B"]
        unit_names = [person["full_name"] for person in unit["members"]]
        assert unit_names == ["Cici Unit"]
        assert "Ana Tim A" not in unit_names
        assert "Beni Tim B" not in unit_names


def test_pack_anggota_tim_menempel_di_bawah_koordinator(app):
    from alumni_web.org_layout import add_custom_seat, pack_unit_seats, template_by_slug

    with app.app_context():
        db = get_db()
        umum = template_by_slug(db, "umum")
        comdev = next(unit for unit in umum["units"] if unit["code"] == "community_development")
        add_custom_seat(db, comdev["id"], label="Koordinator Usaha", short="Usaha", kind="coordinator")
        coord = db.execute(
            "SELECT id FROM org_seats WHERE unit_id = ? AND seat_kind = 'coordinator'",
            (comdev["id"],),
        ).fetchone()
        child = db.execute(
            "SELECT id FROM org_seats WHERE parent_seat_id = ?",
            (coord["id"],),
        ).fetchone()
        unit_member = db.execute(
            """
            SELECT id FROM org_seats
            WHERE unit_id = ? AND seat_kind = 'member' AND parent_seat_id IS NULL
            """,
            (comdev["id"],),
        ).fetchone()
        db.execute("UPDATE org_seats SET sort_order = 0 WHERE id = ?", (unit_member["id"],))
        db.execute("UPDATE org_seats SET sort_order = 1 WHERE id = ?", (child["id"],))
        db.execute("UPDATE org_seats SET sort_order = 9 WHERE id = ?", (coord["id"],))
        db.commit()
        pack_unit_seats(db, comdev["id"])
        db.commit()
        ordered = [
            dict(row)
            for row in db.execute(
                "SELECT id, seat_kind, parent_seat_id FROM org_seats WHERE unit_id = ? ORDER BY sort_order, id",
                (comdev["id"],),
            )
        ]
        kinds = [row["seat_kind"] for row in ordered]
        assert kinds[0] == "lead"
        assert "officer" in kinds
        assert kinds.index("coordinator") < kinds.index("member")
        coord_index = next(i for i, row in enumerate(ordered) if row["id"] == coord["id"])
        child_index = next(i for i, row in enumerate(ordered) if row["id"] == child["id"])
        unit_index = next(i for i, row in enumerate(ordered) if row["id"] == unit_member["id"])
        assert child_index == coord_index + 1
        assert unit_index == len(ordered) - 1


def test_salin_template_menyimpan_induk_koordinator(app):
    from alumni_web.org_layout import add_custom_seat, copy_blueprint, template_by_slug

    with app.app_context():
        db = get_db()
        umum = template_by_slug(db, "umum")
        comdev = next(unit for unit in umum["units"] if unit["code"] == "community_development")
        add_custom_seat(db, comdev["id"], label="Koordinator Relasi", short="Relasi", kind="coordinator")
        db.commit()
        new_id = copy_blueprint(
            db,
            umum["id"],
            kind="period",
            title="Tahun 2029",
            period_start=2029,
        )
        db.commit()
        source_coord = db.execute(
            """
            SELECT s.id FROM org_seats s
            JOIN org_units u ON u.id = s.unit_id
            WHERE u.blueprint_id = ? AND s.seat_kind = 'coordinator' AND s.short = 'Relasi'
            """,
            (umum["id"],),
        ).fetchone()
        source_child = db.execute(
            "SELECT id, parent_seat_id FROM org_seats WHERE parent_seat_id = ?",
            (source_coord["id"],),
        ).fetchone()
        copied_coord = db.execute(
            """
            SELECT s.id FROM org_seats s
            JOIN org_units u ON u.id = s.unit_id
            WHERE u.blueprint_id = ? AND s.seat_kind = 'coordinator' AND s.short = 'Relasi'
            """,
            (new_id,),
        ).fetchone()
        copied_child = db.execute(
            """
            SELECT s.id, s.parent_seat_id FROM org_seats s
            JOIN org_units u ON u.id = s.unit_id
            WHERE u.blueprint_id = ? AND s.label LIKE 'Anggota%' AND s.parent_seat_id IS NOT NULL
            """,
            (new_id,),
        ).fetchone()
        assert copied_coord["id"] != source_coord["id"]
        assert copied_child["id"] != source_child["id"]
        assert copied_child["parent_seat_id"] == copied_coord["id"]
        assert copied_child["parent_seat_id"] != source_coord["id"]


def test_hapus_koordinator_anggotanya_jadi_anggota_unit(app):
    from alumni_web.org_layout import add_custom_seat, delete_seat, template_by_slug

    with app.app_context():
        db = get_db()
        umum = template_by_slug(db, "umum")
        comdev = next(unit for unit in umum["units"] if unit["code"] == "community_development")
        add_custom_seat(db, comdev["id"], label="Koordinator Lepas", short="Lepas", kind="coordinator")
        coord = db.execute(
            "SELECT id FROM org_seats WHERE unit_id = ? AND seat_kind = 'coordinator'",
            (comdev["id"],),
        ).fetchone()
        child = db.execute(
            "SELECT id FROM org_seats WHERE parent_seat_id = ?",
            (coord["id"],),
        ).fetchone()
        message = delete_seat(db, coord["id"])
        db.commit()
        assert "Anggotanya jadi anggota unit" in message
        leftover = db.execute("SELECT parent_seat_id FROM org_seats WHERE id = ?", (child["id"],)).fetchone()
        assert leftover is not None
        assert leftover["parent_seat_id"] is None


def test_migrasi_org_seats_lama_ke_pohon_koordinator(app):
    from alumni_web.db import migrate
    from alumni_web.org_layout import ensure_org_layout

    with app.app_context():
        db = get_db()
        rows = list(db.execute("SELECT * FROM org_seats"))
        db.execute("PRAGMA foreign_keys = OFF")
        db.execute("DROP TABLE org_seats")
        db.execute(
            """
            CREATE TABLE org_seats (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              unit_id INTEGER NOT NULL,
              office_code TEXT NOT NULL,
              label TEXT NOT NULL,
              short TEXT NOT NULL,
              seat_kind TEXT NOT NULL CHECK(seat_kind IN ('head', 'officer', 'lead', 'member', 'pj')),
              pair_group INTEGER,
              sort_order INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        for row in rows:
            db.execute(
                """
                INSERT INTO org_seats (
                  id, unit_id, office_code, label, short, seat_kind, pair_group, sort_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["unit_id"],
                    row["office_code"],
                    row["label"],
                    row["short"],
                    row["seat_kind"],
                    row["pair_group"],
                    row["sort_order"],
                ),
            )
        comdev = db.execute(
            "SELECT id FROM org_units WHERE code = 'community_development' ORDER BY id LIMIT 1"
        ).fetchone()
        db.execute(
            """
            INSERT INTO org_seats (
              unit_id, office_code, label, short, seat_kind, pair_group, sort_order
            ) VALUES (?, 'korwil_lama', 'Koordinator Lama', 'Korlama', 'lead', NULL, 80)
            """,
            (comdev["id"],),
        )
        db.execute("PRAGMA foreign_keys = ON")
        db.commit()
        migrate(db)
        db.commit()
        cols = {row[1] for row in db.execute("PRAGMA table_info(org_seats)")}
        assert "parent_seat_id" in cols
        sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'org_seats'"
        ).fetchone()[0]
        assert "coordinator" in sql
        extra = db.execute(
            "SELECT seat_kind FROM org_seats WHERE office_code = 'korwil_lama'"
        ).fetchone()
        assert extra["seat_kind"] == "coordinator"
        ensure_org_layout(db)
