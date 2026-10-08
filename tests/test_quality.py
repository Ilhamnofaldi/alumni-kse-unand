"""Pembersihan mutu data: bendera, isian sampah, resolusi nama kembar."""

from __future__ import annotations

import json

from alumni_web.db import get_db, utcnow
from alumni_web.normalize import blank_if_junk, quality_flags, quality_notes
from alumni_web.quality import (
    clean_junk,
    completeness,
    recompute_flags,
    refresh_duplicate_flags,
    resolve_duplicates,
)
from tests.conftest import csrf_token, login_admin


def _tambah(app, **kolom):
    now = utcnow()
    dasar = {
        "full_name": "Tanpa Nama",
        "name_normalized": "tanpa nama",
        "is_listed": 1,
        "data_quality_flags": "[]",
        "created_at": now,
        "updated_at": now,
    }
    dasar.update(kolom)
    cols = list(dasar.keys())
    with app.app_context():
        cur = get_db().execute(
            f"INSERT INTO alumni ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [dasar[c] for c in cols],
        )
        get_db().commit()
        return cur.lastrowid


def test_skeleton_hanya_untuk_baris_tanpa_isi_apa_pun():
    kosong = quality_flags({"full_name": "A"})
    assert "skeleton" in kosong
    assert "perlu_dilengkapi" not in kosong

    # Baris dari daftar kedua: nama + fakultas + jurusan + WA. Bukan skeleton.
    sebagian = quality_flags(
        {
            "full_name": "B",
            "faculty_code": "pertanian",
            "major_normalized": "Agroteknologi",
            "phone_normalized": "6281234567890",
        }
    )
    assert "skeleton" not in sebagian
    assert "perlu_dilengkapi" in sebagian


def test_lengkap_tidak_diberi_bendera():
    assert quality_flags(
        {
            "full_name": "C",
            "faculty_code": "pertanian",
            "cohort_year": 2013,
            "city": "Padang",
            "status_code": "belum_bekerja",
        }
    ) == []


def test_tanpa_tempat_kerja_bukan_perlu_dilengkapi():
    flags = quality_flags(
        {
            "full_name": "D",
            "faculty_code": "teknik",
            "cohort_year": 2018,
            "city": "Padang",
            "status_code": "mahasiswa",
        }
    )
    assert flags == []
    assert "perlu_dilengkapi" not in flags


def test_tanpa_kota_tetap_perlu_dilengkapi():
    flags = quality_flags(
        {
            "full_name": "E",
            "cohort_year": 2018,
            "workplace": "PT Contoh",
            "status_code": "bekerja",
        }
    )
    assert "perlu_dilengkapi" in flags
    assert "skeleton" not in flags


def test_tanpa_angkatan_tetap_perlu_dilengkapi():
    flags = quality_flags(
        {
            "full_name": "F",
            "city": "Padang",
            "workplace": "PT Contoh",
        }
    )
    assert "perlu_dilengkapi" in flags
    assert "skeleton" not in flags


def test_catatan_mutu_menyebut_isian_yang_kurang():
    notes = quality_notes(
        {
            "full_name": "G",
            "faculty_code": "teknik",
            "major_normalized": "Teknik Sipil",
            "phone_normalized": "6281234567890",
        }
    )
    assert notes == ["belum ada kota", "belum ada angkatan"]
    assert "perlu dilengkapi" not in " ".join(notes), "jangan pakai nama bendera internal"


def test_catatan_mutu_membedakan_kota_yang_tidak_terbaca():
    notes = quality_notes(
        {
            "full_name": "H",
            "cohort_year": 2015,
            "faculty_code": "teknik",
            "major_normalized": "Teknik Sipil",
            "domicile": "Perumahan Tanpa Nama Kota",
        }
    )
    assert notes == ["kota belum terbaca dari alamat"]


def test_catatan_mutu_diam_soal_tempat_kerja_dan_jabatan():
    notes = quality_notes(
        {
            "full_name": "I",
            "cohort_year": 2019,
            "city": "Padang",
            "faculty_code": "teknik",
            "major_normalized": "Teknik Sipil",
            "status_code": "belum_bekerja",
        }
    )
    assert notes == []


def test_catatan_mutu_baris_hanya_nama():
    assert quality_notes({"full_name": "J"}) == ["baru berisi nama"]


def test_catatan_mutu_menerima_baris_sqlite(app):
    rid = _tambah(
        app,
        full_name="Baris Row",
        name_normalized="baris row",
        faculty_code="teknik",
        major_normalized="Teknik Sipil",
        cohort_year=2018,
    )
    with app.app_context():
        row = get_db().execute("SELECT * FROM alumni WHERE id = ?", (rid,)).fetchone()
        assert quality_notes(row) == ["belum ada kota"]


def test_isian_sampah_dianggap_kosong():
    for nilai in ("-", "--", "_", ".", "n/a", "N/A", "tidak ada", "  "):
        assert blank_if_junk(nilai) is None
    assert blank_if_junk("PT Semen Padang") == "PT Semen Padang"


def test_clean_junk_mengosongkan_dan_butuh_apply(app):
    rid = _tambah(app, full_name="Sampah Uji", name_normalized="sampah uji", workplace="-", phone="_")
    with app.app_context():
        assert len(clean_junk()["changed"]) == 2
        baris = get_db().execute("SELECT workplace FROM alumni WHERE id = ?", (rid,)).fetchone()
        assert baris["workplace"] == "-", "mode simulasi tidak boleh mengubah data"
        clean_junk(apply=True)
        baris = get_db().execute(
            "SELECT workplace, phone, phone_normalized FROM alumni WHERE id = ?", (rid,)
        ).fetchone()
    assert baris["workplace"] is None
    assert baris["phone"] is None
    assert baris["phone_normalized"] is None


def test_recompute_flags_memperbarui_baris_lama(app):
    rid = _tambah(
        app,
        full_name="Bendera Lama",
        name_normalized="bendera lama",
        faculty_code="pertanian",
        phone_normalized="6281234567890",
        data_quality_flags='["skeleton"]',
    )
    with app.app_context():
        laporan = recompute_flags(apply=True)
        flags = json.loads(
            get_db().execute(
                "SELECT data_quality_flags FROM alumni WHERE id = ?", (rid,)
            ).fetchone()[0]
        )
    assert flags == ["perlu_dilengkapi"]
    assert laporan["before"].get("skeleton", 0) >= 1
    assert laporan["after"].get("skeleton", 0) == 0


def test_recompute_flags_tidak_menggeser_waktu_ubah(app):
    """Bendera mutu adalah nilai turunan.

    Kalau `updated_at` ikut diperbarui, seluruh baris yang benderanya berubah
    melompat ke puncak daftar `/admin` yang terurut waktu ubah — panel jadi
    tampak seperti baru disunting semua padahal tidak ada yang menyentuhnya.
    """
    rid = _tambah(
        app,
        full_name="Waktu Ubah",
        name_normalized="waktu ubah",
        faculty_code="teknik",
        cohort_year=2020,
        city="Padang",
        created_at="2020-01-01T00:00:00+00:00",
        updated_at="2020-01-01T00:00:00+00:00",
        data_quality_flags='["perlu_dilengkapi"]',
    )
    with app.app_context():
        laporan = recompute_flags(apply=True)
        row = get_db().execute(
            "SELECT data_quality_flags, updated_at FROM alumni WHERE id = ?", (rid,)
        ).fetchone()
    assert laporan["changed"] >= 1
    assert row["data_quality_flags"] == "[]", "bendera tetap harus ikut diperbarui"
    assert row["updated_at"] == "2020-01-01T00:00:00+00:00"


def test_recompute_flags_tidak_menandai_tanpa_tempat_kerja(app):
    rid = _tambah(
        app,
        full_name="Mahasiswa Uji",
        name_normalized="mahasiswa uji",
        faculty_code="teknik",
        cohort_year=2020,
        city="Padang",
        status_code="mahasiswa",
        data_quality_flags='["perlu_dilengkapi"]',
    )
    with app.app_context():
        laporan = recompute_flags(apply=True)
        flags = json.loads(
            get_db().execute(
                "SELECT data_quality_flags FROM alumni WHERE id = ?", (rid,)
            ).fetchone()[0]
        )
    assert flags == []
    assert laporan["changed"] >= 1


def test_resolve_duplicates_menyembunyikan_yang_paling_miskin(app):
    kaya = _tambah(
        app,
        full_name="Kembar Uji",
        name_normalized="kembar uji",
        cohort_year=2013,
        workplace="PT Contoh",
        city="Padang",
        email_normalized="kaya@example.com",
        phone_normalized="6281111111111",
    )
    miskin = _tambah(app, full_name="Kembar Uji", name_normalized="kembar uji")
    with app.app_context():
        keputusan = resolve_duplicates()["decisions"]
        assert [d["hide_id"] for d in keputusan] == [miskin]
        assert [d["keep_id"] for d in keputusan] == [kaya]
        listed = get_db().execute("SELECT is_listed FROM alumni WHERE id = ?", (miskin,)).fetchone()[0]
        assert listed == 1, "mode simulasi tidak boleh mengubah data"
        resolve_duplicates(apply=True)
        db = get_db()
        assert db.execute("SELECT is_listed FROM alumni WHERE id = ?", (miskin,)).fetchone()[0] == 0
        assert db.execute("SELECT is_listed FROM alumni WHERE id = ?", (kaya,)).fetchone()[0] == 1
        # Tidak ada yang dihapus.
        assert db.execute("SELECT COUNT(*) FROM alumni WHERE name_normalized = 'kembar uji'").fetchone()[0] == 2
        assert db.execute(
            "SELECT is_duplicate_suspect FROM alumni WHERE id = ?", (kaya,)
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT is_duplicate_suspect FROM alumni WHERE id = ?", (miskin,)
        ).fetchone()[0] == 0


def test_completeness_menghitung_isian(app):
    rid = _tambah(app, full_name="Skor Uji", name_normalized="skor uji", cohort_year=2010, city="Padang")
    with app.app_context():
        db = get_db()
        row = db.execute("SELECT * FROM alumni WHERE id = ?", (rid,)).fetchone()
        assert completeness(row, db) == 3


def test_completeness_jabatan_lebih_berat_dari_tempat_kerja(app):
    dari_kantor = _tambah(
        app,
        full_name="Skor Kembar",
        name_normalized="skor kembar",
        city="Padang",
        workplace="PT Contoh",
    )
    dari_jabatan = _tambah(
        app,
        full_name="Skor Kembar",
        name_normalized="skor kembar",
        city="Padang",
    )
    with app.app_context():
        from alumni_web.offices import add_roles

        db = get_db()
        add_roles(
            db,
            dari_jabatan,
            {"office_code": "ketua", "period_start": 2023, "period_end": 2024},
        )
        db.commit()
        kerja = db.execute("SELECT * FROM alumni WHERE id = ?", (dari_kantor,)).fetchone()
        jabatan = db.execute("SELECT * FROM alumni WHERE id = ?", (dari_jabatan,)).fetchone()
        assert completeness(kerja, db) == 3
        assert completeness(jabatan, db) == 4


def test_panel_pengurus_urut_waktu_ubah(client, app):
    _tambah(
        app,
        full_name="Lama Ada Catatan",
        name_normalized="lama ada catatan",
        updated_at="2010-01-01T00:00:00+00:00",
        data_quality_flags='["perlu_dilengkapi"]',
    )
    _tambah(
        app,
        full_name="Baru Tanpa Catatan",
        name_normalized="baru tanpa catatan",
        faculty_code="teknik",
        cohort_year=2020,
        city="Padang",
        updated_at="2026-09-14T12:00:00+00:00",
        data_quality_flags="[]",
    )
    login_admin(client)
    body = client.get("/admin").get_data(as_text=True)
    assert "Urutan: yang terakhir diubah." in body
    assert "catatan mutu dulu" not in body
    assert body.index("Baru Tanpa Catatan") < body.index("Lama Ada Catatan")


def test_filter_mutu_di_panel_pengurus(client, app):
    _tambah(
        app,
        full_name="Perlu Lengkap",
        name_normalized="perlu lengkap",
        faculty_code="pertanian",
        data_quality_flags='["perlu_dilengkapi"]',
    )
    login_admin(client)
    res = client.get("/admin?mutu=perlu_dilengkapi")
    body = res.get_data(as_text=True)
    assert res.status_code == 200
    assert "Perlu Lengkap" in body
    assert "Aisyah Uji" not in body, "baris lengkap tidak boleh masuk antrean"
    # Nilai mutu ngawur tidak boleh menjatuhkan halaman atau menyaring apa pun.
    assert client.get("/admin?mutu=x' OR 1=1--").status_code == 200


def test_catatan_mutu_admin_tidak_menandai_tanpa_tempat_kerja(client, app):
    _tambah(
        app,
        full_name="Belum Kerja Uji",
        name_normalized="belum kerja uji",
        faculty_code="teknik",
        major_normalized="Teknik Sipil",
        cohort_year=2019,
        city="Padang",
        status_code="belum_bekerja",
        data_quality_flags="[]",
    )
    login_admin(client)
    body = client.get("/admin?q=Belum+Kerja+Uji").get_data(as_text=True)
    assert "Belum Kerja Uji" in body
    assert '<span class="muted">tidak ada catatan</span>' in body
    assert "<li>belum ada" not in body


def test_kolom_catatan_mutu_menyebut_isian_yang_kurang(client, app):
    _tambah(
        app,
        full_name="Kurang Kota",
        name_normalized="kurang kota",
        faculty_code="teknik",
        major_normalized="Teknik Sipil",
        data_quality_flags='["perlu_dilengkapi"]',
    )
    login_admin(client)
    body = client.get("/admin?q=Kurang+Kota").get_data(as_text=True)
    assert "<li>belum ada kota</li>" in body
    assert "<li>belum ada angkatan</li>" in body
    # Nama bendera internal tidak boleh jadi teks kolom.
    assert "<li>perlu_dilengkapi</li>" not in body


def test_filter_tanpa_jabatan_hanya_yang_tampil_tanpa_peran(client, app):
    _tambah(app, full_name="Tanpa Jabatan Uji", name_normalized="tanpa jabatan uji")
    berjabatan = _tambah(app, full_name="Ada Jabatan Uji", name_normalized="ada jabatan uji")
    _tambah(
        app,
        full_name="Sembunyi Tanpa Jabatan",
        name_normalized="sembunyi tanpa jabatan",
        is_listed=0,
    )
    with app.app_context():
        from alumni_web.offices import add_roles

        db = get_db()
        add_roles(
            db,
            berjabatan,
            {"office_code": "ketua", "period_start": 2023, "period_end": 2024},
        )
        db.commit()
    login_admin(client)
    body = client.get("/admin?mutu=tanpa_jabatan").get_data(as_text=True)
    assert "Tanpa Jabatan Uji" in body
    assert "Ada Jabatan Uji" not in body
    assert "Sembunyi Tanpa Jabatan" not in body
    assert "Tanpa jabatan KSE" in body


def test_filter_mutu_tidak_bocor_ke_direktori_publik(client, app):
    _tambah(
        app,
        full_name="Sembunyi Uji",
        name_normalized="sembunyi uji",
        is_listed=0,
        data_quality_flags='["perlu_dilengkapi"]',
    )
    body = client.get("/direktori?mutu=tersembunyi").get_data(as_text=True)
    assert "Sembunyi Uji" not in body


def _kembar(app, listed=1, **kolom):
    data = {
        "full_name": "Kembar Bendera",
        "name_normalized": "kembar bendera",
        "is_listed": listed,
        "is_duplicate_suspect": 1,
    }
    data.update(kolom)
    return _tambah(app, **data)


def test_hapus_satu_kembar_melepas_bendera_saudara(client, app):
    pertama = _kembar(app)
    sisa = _kembar(app)
    login_admin(client)
    token = csrf_token(client, "/admin")
    res = client.post(
        f"/admin/alumni/{pertama}/hapus",
        data={"csrf": token},
        follow_redirects=True,
    )
    assert res.status_code == 200
    with app.app_context():
        db = get_db()
        assert db.execute("SELECT id FROM alumni WHERE id = ?", (pertama,)).fetchone() is None
        row = db.execute(
            "SELECT is_duplicate_suspect, is_listed FROM alumni WHERE id = ?",
            (sisa,),
        ).fetchone()
    assert row["is_listed"] == 1
    assert row["is_duplicate_suspect"] == 0


def test_tiga_kembar_hapus_satu_dua_tetap_suspect(client, app):
    satu = _kembar(app)
    dua = _kembar(app)
    tiga = _kembar(app)
    login_admin(client)
    token = csrf_token(client, "/admin")
    client.post(f"/admin/alumni/{satu}/hapus", data={"csrf": token}, follow_redirects=True)
    with app.app_context():
        db = get_db()
        assert db.execute("SELECT id FROM alumni WHERE id = ?", (satu,)).fetchone() is None
        flags = [
            db.execute(
                "SELECT is_duplicate_suspect FROM alumni WHERE id = ?", (rid,)
            ).fetchone()[0]
            for rid in (dua, tiga)
        ]
    assert flags == [1, 1]


def test_sembunyikan_satu_kembar_melepas_bendera_listed(client, app):
    tampil = _kembar(app)
    disembunyikan = _kembar(app)
    login_admin(client)
    token = csrf_token(client, f"/admin/alumni/{disembunyikan}/ubah")
    res = client.post(
        f"/admin/alumni/{disembunyikan}/ubah",
        data={"csrf": token, "full_name": "Kembar Bendera"},
        follow_redirects=True,
    )
    assert res.status_code == 200
    with app.app_context():
        db = get_db()
        hidden = db.execute(
            "SELECT is_listed, is_duplicate_suspect FROM alumni WHERE id = ?",
            (disembunyikan,),
        ).fetchone()
        visible = db.execute(
            "SELECT is_listed, is_duplicate_suspect FROM alumni WHERE id = ?",
            (tampil,),
        ).fetchone()
    assert hidden["is_listed"] == 0
    assert hidden["is_duplicate_suspect"] == 0
    assert visible["is_listed"] == 1
    assert visible["is_duplicate_suspect"] == 0


def test_kembar_tersembunyi_tidak_menahan_bendera_listed(app):
    tampil = _kembar(app, listed=1)
    _kembar(app, listed=0)
    with app.app_context():
        db = get_db()
        refresh_duplicate_flags(db)
        db.commit()
        assert db.execute(
            "SELECT is_duplicate_suspect FROM alumni WHERE id = ?", (tampil,)
        ).fetchone()[0] == 0
        hidden_flags = db.execute(
            """
            SELECT is_duplicate_suspect FROM alumni
            WHERE name_normalized = 'kembar bendera' AND is_listed = 0
            """
        ).fetchone()[0]
    assert hidden_flags == 0


def test_refresh_menyalakan_pasangan_listed(app):
    satu = _tambah(
        app,
        full_name="Pasang Bendera",
        name_normalized="pasang bendera",
        is_listed=1,
        is_duplicate_suspect=0,
    )
    dua = _tambah(
        app,
        full_name="Pasang Bendera",
        name_normalized="pasang bendera",
        is_listed=1,
        is_duplicate_suspect=0,
    )
    with app.app_context():
        db = get_db()
        refresh_duplicate_flags(db, ["pasang bendera"])
        db.commit()
        flags = [
            db.execute(
                "SELECT is_duplicate_suspect FROM alumni WHERE id = ?", (rid,)
            ).fetchone()[0]
            for rid in (satu, dua)
        ]
    assert flags == [1, 1]


def test_tambah_alumni_nama_kembar_menyalakan_bendera(client, app):
    login_admin(client)
    for _ in range(2):
        token = csrf_token(client, "/admin/alumni/baru")
        res = client.post(
            "/admin/alumni/baru",
            data={"csrf": token, "full_name": "Nama Kembar Baru", "is_listed": "1"},
            follow_redirects=True,
        )
        assert res.status_code == 200
    with app.app_context():
        rows = get_db().execute(
            """
            SELECT is_listed, is_duplicate_suspect FROM alumni
            WHERE name_normalized = 'nama kembar baru'
            """
        ).fetchall()
    assert len(rows) == 2
    assert all(row["is_listed"] == 1 and row["is_duplicate_suspect"] == 1 for row in rows)
