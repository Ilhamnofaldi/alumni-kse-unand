from __future__ import annotations

import pytest

from alumni_web import create_app
from alumni_web.boot import seed_admin
from alumni_web.db import get_db, init_db, utcnow
from alumni_web.security import reset_rate_limits


@pytest.fixture()
def app(tmp_path, monkeypatch):
    db_path = tmp_path / "alumni.db"
    monkeypatch.setenv("FLASK_TESTING", "1")
    monkeypatch.setenv("DATABASE", str(db_path))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@test.local")
    monkeypatch.setenv("ADMIN_PASSWORD", "password123")
    reset_rate_limits()
    application = create_app()
    application.config["TESTING"] = True
    with application.app_context():
        init_db()
        seed_admin(application)
        now = utcnow()
        get_db().execute(
            """
            INSERT INTO alumni (
              full_name, name_normalized, gender, date_of_birth, domicile, city, province,
              workplace, phone, phone_normalized, email, email_normalized, status_code,
              faculty_code, major_normalized, cohort_year, is_listed, data_quality_flags,
              created_at, updated_at
            ) VALUES (
              'Aisyah Uji', 'aisyah uji', 'P', '1994-08-11', 'Jl. Rahasia No. 9', 'Padang', 'Sumatera Barat',
              'PT Contoh', '081234567890', '6281234567890', 'aisyah.uji@example.com', 'aisyah.uji@example.com', 'bekerja',
              'pertanian', 'Agroteknologi', 2013, 1, '[]', ?, ?
            )
            """,
            (now, now),
        )
        get_db().commit()
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


def csrf_token(client, path="/login"):
    page = client.get(path)
    return page.get_data(as_text=True).split('name="csrf" value="')[1].split('"')[0]


def login_admin(client):
    token = csrf_token(client, "/login")
    return client.post(
        "/login",
        data={"email": "admin@test.local", "password": "password123", "csrf": token},
        follow_redirects=True,
    )
