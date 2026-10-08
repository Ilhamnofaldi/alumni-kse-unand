import sqlite3

import pytest

from alumni_web import create_app
from alumni_web.config import ROOT, Config, _flag
from alumni_web.db import init_db


def _boot_with_secret(tmp_path, monkeypatch, secret: str):
    monkeypatch.setenv("FLASK_TESTING", "0")
    monkeypatch.setenv("SECRET_KEY", secret)
    monkeypatch.setenv("DATABASE", str(tmp_path / "x.db"))
    monkeypatch.setenv("ALUMNI_PREPARE_ON_BOOT", "0")
    monkeypatch.setattr(Config, "SECRET_KEY", secret)
    monkeypatch.setattr(Config, "PREPARE_ON_BOOT", False)
    return create_app()


def test_missing_secret_key_raises(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _boot_with_secret(tmp_path, monkeypatch, "")


def test_placeholder_secret_key_raises(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="placeholder"):
        _boot_with_secret(tmp_path, monkeypatch, "ganti-dengan-string-acak")


def test_short_secret_key_raises(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="32 karakter"):
        _boot_with_secret(tmp_path, monkeypatch, "terlalu-pendek")


def test_secret_key_kuat_diterima(tmp_path, monkeypatch):
    app = _boot_with_secret(tmp_path, monkeypatch, "x" * 48)
    assert app.config["SECRET_KEY"] == "x" * 48


def test_produksi_wajib_app_base_url(tmp_path, monkeypatch):
    monkeypatch.setenv("ALUMNI_ENV", "production")
    monkeypatch.setattr(Config, "ALUMNI_ENV", "production")
    monkeypatch.setattr(Config, "APP_BASE_URL", "")
    with pytest.raises(RuntimeError, match="APP_BASE_URL"):
        _boot_with_secret(tmp_path, monkeypatch, "x" * 48)


def test_cookie_secure_aman_secara_default(monkeypatch):
    monkeypatch.delenv("SESSION_COOKIE_INSECURE", raising=False)
    assert _flag("SESSION_COOKIE_INSECURE") is False
    monkeypatch.setenv("SESSION_COOKIE_INSECURE", "1")
    assert _flag("SESSION_COOKIE_INSECURE") is True


def test_env_example_tidak_mengaktifkan_cookie_tidak_aman():
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    aktif = [ln for ln in lines if ln.strip() and not ln.strip().startswith("#")]
    assert not any("SESSION_COOKIE_INSECURE" in ln for ln in aktif)
    assert not any("FLASK_DEBUG" in ln for ln in aktif)
    assert any(ln.startswith("MAP_MIN_COUNT=3") for ln in aktif)


def test_migrasi_akun_lama_jadi_pending(app):
    with app.app_context():
        db = sqlite3.connect(app.config["DATABASE"])
        db.execute("DROP TABLE IF EXISTS users")
        db.execute(
            """
            CREATE TABLE users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              email TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              role TEXT NOT NULL,
              alumni_id INTEGER,
              created_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            "INSERT INTO users (email, password_hash, role, created_at)"
            " VALUES ('lama@b.c', 'x', 'alumni', 'now')"
        )
        db.commit()
        db.close()
        init_db()
        db = sqlite3.connect(app.config["DATABASE"])
        status = db.execute(
            "SELECT status FROM users WHERE email = 'lama@b.c'"
        ).fetchone()[0]
        db.close()
        assert status == "pending"


def test_migrate_adds_status_to_legacy_users(app):
    with app.app_context():
        db = sqlite3.connect(app.config["DATABASE"])
        db.execute("DROP TABLE IF EXISTS users")
        db.execute(
            """
            CREATE TABLE users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              email TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              role TEXT NOT NULL,
              alumni_id INTEGER,
              created_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            "INSERT INTO users (email, password_hash, role, created_at) VALUES ('a@b.c', 'x', 'admin', 'now')"
        )
        db.commit()
        db.close()
        init_db()
        db = sqlite3.connect(app.config["DATABASE"])
        cols = {row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()}
        db.close()
        assert "status" in cols
