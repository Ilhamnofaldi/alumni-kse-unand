from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, g

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

SCHEMA_VERSION = 8


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_e=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def migrate(db: sqlite3.Connection) -> None:
    """Langkah bertahap untuk database yang sudah berisi data.

    Setiap langkah dijaga pemeriksaan sendiri agar aman dijalankan berulang.
    `PRAGMA user_version` dicatat sebagai penanda untuk langkah berikutnya.
    """
    columns = {row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()}
    if columns and "status" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
        # Akun lama belum pernah lewat persetujuan pengurus: fail-closed.
        db.execute("UPDATE users SET status = 'pending' WHERE role != 'admin'")
    if columns and "request_ip" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN request_ip TEXT")
    db.execute("CREATE INDEX IF NOT EXISTS idx_users_status ON users(status)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_users_alumni ON users(alumni_id)")

    alumni_cols = {row[1] for row in db.execute("PRAGMA table_info(alumni)").fetchall()}
    if alumni_cols and "self_updated_at" not in alumni_cols:
        db.execute("ALTER TABLE alumni ADD COLUMN self_updated_at TEXT")
    if alumni_cols and "hide_requested" not in alumni_cols:
        db.execute(
            "ALTER TABLE alumni ADD COLUMN hide_requested INTEGER NOT NULL DEFAULT 0"
        )
    db.execute("CREATE INDEX IF NOT EXISTS idx_alumni_phone ON alumni(phone_normalized)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_alumni_hide ON alumni(hide_requested)")

    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS invites (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          alumni_id INTEGER REFERENCES alumni(id) ON DELETE CASCADE,
          user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
          token_hash TEXT NOT NULL UNIQUE,
          purpose TEXT NOT NULL CHECK(purpose IN ('invite', 'password_reset')),
          payload TEXT,
          expires_at TEXT NOT NULL,
          used_at TEXT,
          created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_invites_hash ON invites(token_hash);
        CREATE INDEX IF NOT EXISTS idx_invites_alumni ON invites(alumni_id);

        CREATE TABLE IF NOT EXISTS change_requests (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          alumni_id INTEGER NOT NULL REFERENCES alumni(id) ON DELETE CASCADE,
          user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
          kind TEXT NOT NULL CHECK(kind IN ('email', 'identity', 'hide', 'reset')),
          payload TEXT NOT NULL DEFAULT '{}',
          status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected')),
          created_at TEXT NOT NULL,
          resolved_at TEXT,
          resolved_by INTEGER REFERENCES users(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_change_requests_status ON change_requests(status);

        CREATE TABLE IF NOT EXISTS recovery_codes (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          code_hash TEXT NOT NULL UNIQUE,
          used_at TEXT,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_recovery_user ON recovery_codes(user_id);

        CREATE TABLE IF NOT EXISTS alumni_kse_roles (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          alumni_id INTEGER NOT NULL REFERENCES alumni(id) ON DELETE CASCADE,
          office_code TEXT NOT NULL,
          period_start INTEGER,
          period_end INTEGER,
          period_raw TEXT,
          scope TEXT,
          title_raw TEXT,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_roles_alumni ON alumni_kse_roles(alumni_id);
        CREATE INDEX IF NOT EXISTS idx_roles_office ON alumni_kse_roles(office_code);
        CREATE INDEX IF NOT EXISTS idx_roles_period ON alumni_kse_roles(period_start);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_roles_uniq
          ON alumni_kse_roles(alumni_id, office_code, IFNULL(period_start, 0), IFNULL(scope, ''));
        """
    )
    from .offices import split_wide_role_rows
    from .org_layout import ensure_org_layout

    split_wide_role_rows(db)
    ensure_org_layout(db)
    db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def init_db() -> None:
    db = get_db()
    db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    migrate(db)
    db.commit()


def audit(action: str, detail: str | None = None) -> None:
    """Catat aksi sensitif (akses/ekspor PII, aksi pengurus)."""
    from flask import has_request_context, request

    user_id = None
    ip = None
    if has_request_context():
        user = g.get("user")
        if user is not None:
            user_id = user["id"]
        ip = request.remote_addr
    get_db().execute(
        """
        INSERT INTO audit_log (user_id, action, detail, ip, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, action, detail, ip, utcnow()),
    )


def init_app(app) -> None:
    app.teardown_appcontext(close_db)

    @app.cli.command("init-db")
    def init_db_command():
        init_db()
        print("Database siap.")
