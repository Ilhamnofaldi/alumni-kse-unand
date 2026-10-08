from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

PLACEHOLDER_SECRETS = {
    "",
    "ganti-dengan-string-acak",
    "dev-kse-unand-ganti",
    "changeme",
}


def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or ""
    DATABASE = os.environ.get("DATABASE", str(ROOT / "instance" / "alumni.db"))
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@kse.local")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024
    SOURCE_DIR = ROOT / "data" / "source"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Aman secara default; matikan hanya untuk dev di http lokal.
    SESSION_COOKIE_SECURE = not _flag("SESSION_COOKIE_INSECURE")
    PERMANENT_SESSION_LIFETIME = timedelta(days=3)
    SESSION_REFRESH_EACH_REQUEST = False
    # Sembunyikan titik peta yang isinya terlalu sedikit agar tidak menunjuk individu.
    MAP_MIN_COUNT = max(int(os.environ.get("MAP_MIN_COUNT", "3") or 3), 3)
    # Mesin pencari tidak boleh mengindeks halaman orang secara default.
    ALLOW_INDEXING = _flag("ALLOW_INDEXING")
    PREPARE_ON_BOOT = _flag("ALUMNI_PREPARE_ON_BOOT")
    # Domain kanonis untuk tautan yang disalin keluar (undangan, pemulihan).
    # Kosong = pakai host dari permintaan yang sedang berjalan (hanya non-produksi).
    APP_BASE_URL = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
    ALUMNI_ENV = os.environ.get("ALUMNI_ENV", "").strip().lower()
    # Aset statis memakai ?v=mtime di url_for, jadi cache panjang aman.
    SEND_FILE_MAX_AGE_DEFAULT = 365 * 24 * 60 * 60


def validate_secret(secret: str) -> None:
    if secret.strip() in PLACEHOLDER_SECRETS:
        raise RuntimeError(
            "SECRET_KEY masih placeholder. Buat nilai acak: "
            "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
    if len(secret) < 32:
        raise RuntimeError("SECRET_KEY minimal 32 karakter.")


def validate_base_url(url: str) -> None:
    if not url:
        raise RuntimeError(
            "APP_BASE_URL wajib di produksi (contoh: https://database.kseunand.social)."
        )
    if not url.startswith("https://") or "://" in url[8:] or " " in url:
        raise RuntimeError(
            "APP_BASE_URL produksi harus https://host tanpa spasi atau path."
        )
