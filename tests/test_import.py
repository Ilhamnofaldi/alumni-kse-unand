from pathlib import Path

from alumni_web.db import get_db, init_db
from alumni_web.import_csv import import_csv_path

FIXTURE = Path(__file__).parent / "fixtures" / "sample.csv"


def test_import_sample(app):
    with app.app_context():
        init_db()
        result = import_csv_path(FIXTURE)
        assert result["inserted"] >= 1
        row = get_db().execute(
            "SELECT * FROM alumni WHERE email_normalized = ?",
            ("budi.uji@example.com",),
        ).fetchone()
        assert row["faculty_code"] == "teknik"
        assert row["phone_normalized"].startswith("62")
        assert row["city"] == "Jakarta"


def test_template_headers_terpetakan():
    from alumni_web.import_csv import TEMPLATE_HEADERS, _header_map

    mapping = _header_map(list(TEMPLATE_HEADERS))
    assert mapping["full_name"] == "nama"
    assert mapping["email"] == "email"
    assert mapping["phone"] == "whatsapp"
    assert mapping["gender"] == "jenis_kelamin"
    assert mapping["faculty"] == "fakultas"
    assert mapping["kse_roles"] == "jabatan_kse"


def test_reimport_keeps_unlisted(app):
    with app.app_context():
        db = get_db()
        db.execute(
            "UPDATE alumni SET is_listed = 0 WHERE email_normalized = ?",
            ("aisyah.uji@example.com",),
        )
        db.commit()
        import_csv_path(FIXTURE)
        row = db.execute(
            "SELECT is_listed FROM alumni WHERE email_normalized = ?",
            ("aisyah.uji@example.com",),
        ).fetchone()
        assert row["is_listed"] == 0
