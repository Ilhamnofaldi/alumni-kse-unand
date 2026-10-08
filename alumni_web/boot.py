from __future__ import annotations

import secrets
from pathlib import Path

from werkzeug.security import generate_password_hash

from .db import audit, get_db, init_db, utcnow
from .import_csv import import_csv_path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "data" / "source"


def find_csv(include_root: bool = False) -> Path | None:
    """CSV kandidat untuk impor.

    Default hanya `data/source/`. Root proyek sengaja tidak dipindai otomatis
    supaya proses boot tidak pernah menelan CSV yang kebetulan tergeletak di
    direktori aplikasi.
    """
    found: list[Path] = []
    if SOURCE_DIR.exists():
        found.extend(sorted(SOURCE_DIR.glob("*.csv")))
    if include_root and not found:
        found.extend(sorted(ROOT.glob("*.csv")))
    return found[0] if found else None


def seed_admin(app, allow_generate: bool = False) -> tuple[str, str | None]:
    email = (app.config["ADMIN_EMAIL"] or "admin@kse.local").strip().lower()
    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        return email, None
    password = app.config["ADMIN_PASSWORD"]
    generated = False
    if not password:
        if not allow_generate:
            raise RuntimeError(
                "ADMIN_PASSWORD kosong. Isi di .env, atau buat akun lewat "
                "`python -m alumni_web.cli setup` yang mencetak sandi sekali."
            )
        password = secrets.token_urlsafe(12)
        generated = True
    if len(password) < 8:
        raise RuntimeError("ADMIN_PASSWORD minimal 8 karakter.")
    db.execute(
        """
        INSERT INTO users (email, password_hash, role, status, alumni_id, created_at)
        VALUES (?, ?, 'admin', 'active', NULL, ?)
        """,
        (email, generate_password_hash(password), utcnow()),
    )
    audit("admin_seed", email)
    db.commit()
    # Hanya sandi hasil generate yang perlu dicetak; yang dari .env sudah diketahui.
    return email, (password if generated else None)


def reset_admin_password(app, password: str, email: str | None = None) -> str:
    target = (email or app.config["ADMIN_EMAIL"] or "admin@kse.local").strip().lower()
    if len(password) < 8:
        raise RuntimeError("Sandi minimal 8 karakter.")
    db = get_db()
    cur = db.execute(
        "UPDATE users SET password_hash = ?, status = 'active' WHERE email = ? AND role = 'admin'",
        (generate_password_hash(password), target),
    )
    if cur.rowcount == 0:
        raise RuntimeError(f"Akun pengurus {target} tidak ada. Jalankan setup dulu.")
    audit("admin_password_reset", target)
    db.commit()
    return target


def prepare(
    app,
    csv_path: str | Path | None = None,
    auto_import: bool = True,
    allow_generate: bool = False,
    include_root: bool = False,
) -> dict:
    with app.app_context():
        init_db()
        email, password = seed_admin(app, allow_generate=allow_generate)
        imported = None
        count = get_db().execute("SELECT COUNT(*) FROM alumni").fetchone()[0]
        path = Path(csv_path) if csv_path else find_csv(include_root=include_root)
        force = bool(csv_path)
        if path and path.exists() and (force or (auto_import and count == 0)):
            imported = import_csv_path(path)
        return {
            "admin_email": email,
            "admin_password": password,
            "import": imported,
            "count": count,
        }
