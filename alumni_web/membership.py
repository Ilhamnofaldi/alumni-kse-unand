"""Pendaftaran, klaim, undangan, dan pembaruan profil alumni."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .db import audit, utcnow
from .import_csv import _mark_duplicates
from .normalize import (
    name_key,
    normalize_email,
    normalize_phone,
    parse_year,
    quality_flags,
    record_from_form,
    testimonial_has_contact,
)

GENERIC_PENDING = (
    "Jika data cocok, permintaan diteruskan ke pengurus. "
    "Tunggu persetujuan sebelum masuk."
)
GENERIC_RESET = (
    "Jika akun ada, permintaan pemulihan diteruskan ke pengurus. "
    "Pengurus akan menghubungi Anda lewat jalur yang sudah dikenal."
)
GENERIC_TOKEN = "Tautan tidak valid atau kedaluwarsa."

MIN_PASSWORD = 10
MAX_PASSWORD = 128
MIN_NEW_PASSWORD = MIN_PASSWORD
MIN_CHANGE_PASSWORD = MIN_PASSWORD
INVITE_DAYS = 14
RECOVERY_CODE_COUNT = 8

REQUEST_KIND_LABELS = {
    "email": "Ganti email",
    "hide": "Sembunyikan nama",
    "reset": "Pulihkan kata sandi",
    "identity": "Koreksi identitas",
}

SOURCE_LABELS = {
    "self_register": "Pendaftaran sendiri",
    "batch": "Tempel daftar",
    "google_form": "Formulir",
    "admin": "Pengurus",
}

LOCKED_ALUMNI_FIELDS = (
    "full_name",
    "name_normalized",
    "gender",
    "faculty_code",
    "faculty_raw",
    "major_normalized",
    "major_raw",
    "cohort_year",
    "email",
    "email_normalized",
    "is_listed",
    "source",
    "submitted_at",
    "created_at",
    "is_duplicate_suspect",
    "hide_requested",
)

FILLABLE_IF_EMPTY = (
    "gender",
    "faculty_code",
    "faculty_raw",
    "major_normalized",
    "major_raw",
    "cohort_year",
)

SOFT_FORM_KEYS = (
    "workplace",
    "status",
    "domicile",
    "phone",
    "testimonial",
    "date_of_birth",
    "graduation_year",
    "kse_last_year",
)


def password_error(password: str, minimum: int = MIN_PASSWORD) -> str | None:
    text = password or ""
    if len(text) < minimum:
        return f"Kata sandi minimal {minimum} karakter."
    if len(text) > MAX_PASSWORD:
        return f"Kata sandi maksimal {MAX_PASSWORD} karakter."
    return None


def _blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def token_digest(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_raw_token() -> str:
    return secrets.token_urlsafe(32)


def expires_after(days: int = INVITE_DAYS) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(
        microsecond=0
    ).isoformat()


def insert_alumni(db, rec: dict[str, Any], is_listed: int = 0) -> int:
    payload = dict(rec)
    payload["is_listed"] = is_listed
    now = utcnow()
    payload.setdefault("created_at", now)
    payload["updated_at"] = now
    cols = list(payload.keys())
    cur = db.execute(
        f"INSERT INTO alumni ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        [payload[c] for c in cols],
    )
    return int(cur.lastrowid)


def create_user(
    db,
    *,
    email: str,
    password_hash: str,
    alumni_id: int | None,
    ip: str | None,
    role: str = "alumni",
    status: str = "pending",
) -> int | None:
    existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        return None
    cur = db.execute(
        """
        INSERT INTO users
          (email, password_hash, role, status, alumni_id, request_ip, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (email, password_hash, role, status, alumni_id, ip, utcnow()),
    )
    return int(cur.lastrowid)


def user_for_alumni(db, alumni_id: int):
    return db.execute(
        "SELECT * FROM users WHERE alumni_id = ? ORDER BY id DESC LIMIT 1",
        (alumni_id,),
    ).fetchone()


def issue_token(
    db,
    *,
    purpose: str,
    alumni_id: int | None = None,
    user_id: int | None = None,
    created_by: int | None = None,
    days: int = INVITE_DAYS,
    payload: dict | None = None,
) -> str:
    raw = new_raw_token()
    db.execute(
        """
        INSERT INTO invites
          (alumni_id, user_id, token_hash, purpose, payload, expires_at, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            alumni_id,
            user_id,
            token_digest(raw),
            purpose,
            json.dumps(payload, ensure_ascii=False) if payload else None,
            expires_after(days),
            created_by,
            utcnow(),
        ),
    )
    return raw


def lookup_token(db, raw: str, purpose: str):
    if not raw or len(raw) > 80:
        return None
    row = db.execute(
        """
        SELECT * FROM invites
        WHERE token_hash = ? AND purpose = ?
        """,
        (token_digest(raw), purpose),
    ).fetchone()
    if row is None or row["used_at"] or row["expires_at"] < utcnow():
        return None
    return row


def mark_token_used(db, token_id: int) -> None:
    db.execute(
        "UPDATE invites SET used_at = ? WHERE id = ?",
        (utcnow(), token_id),
    )


def listed_by_email(db, email: str):
    if not email:
        return None
    return db.execute(
        "SELECT * FROM alumni WHERE email_normalized = ? AND is_listed = 1",
        (email,),
    ).fetchone()


def unlisted_by_email(db, email: str):
    if not email:
        return None
    return db.execute(
        "SELECT id FROM alumni WHERE email_normalized = ? AND is_listed = 0",
        (email,),
    ).fetchone()


def find_claim_row(
    db,
    *,
    name: str,
    cohort: Optional[int],
    email: str,
    phone_norm: Optional[str],
):
    """Cari satu baris tercatat yang cocok. Nol atau lebih dari satu = None."""
    key = name_key(name)
    if not key:
        return None
    clauses = ["is_listed = 1", "name_normalized = ?"]
    params: list = [key]
    where = " AND ".join(clauses)
    rows = db.execute(f"SELECT * FROM alumni WHERE {where}", params).fetchall()
    matched = []
    for row in rows:
        if (
            cohort is not None
            and row["cohort_year"] is not None
            and int(row["cohort_year"]) != int(cohort)
        ):
            continue
        email_ok = bool(email) and row["email_normalized"] == email
        phone_ok = bool(phone_norm) and row["phone_normalized"] == phone_norm
        record_email = row["email_normalized"]
        if email_ok:
            matched.append(row)
        elif phone_ok and (not record_email or record_email == email):
            matched.append(row)
    if len(matched) != 1:
        return None
    return matched[0]


def register_or_claim(
    db,
    *,
    values: dict[str, str],
    password_hash: str,
    ip: str | None,
    allow_new: bool,
) -> None:
    """Selalu biaya hash sudah dibayar pemanggil. Tidak membedakan hasil ke klien."""
    email = normalize_email(values.get("email"))
    phone_n, _ = normalize_phone(values.get("phone"))
    if not email:
        return
    existing_user = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    hidden = unlisted_by_email(db, email)
    listed = listed_by_email(db, email)
    cohort, _ = parse_year(values.get("cohort_year"))

    if existing_user or hidden:
        return

    if listed is not None:
        if user_for_alumni(db, listed["id"]):
            return
        create_user(
            db,
            email=email,
            password_hash=password_hash,
            alumni_id=listed["id"],
            ip=ip,
        )
        audit("activation_request", f"alumni={listed['id']}")
        return

    claimed = find_claim_row(
        db,
        name=values.get("full_name") or "",
        cohort=cohort,
        email=email,
        phone_norm=phone_n,
    )
    if claimed is not None:
        if user_for_alumni(db, claimed["id"]):
            return
        if not claimed["email_normalized"]:
            db.execute(
                """
                UPDATE alumni
                SET email = ?, email_normalized = ?, updated_at = ?
                WHERE id = ?
                """,
                (email, email, utcnow(), claimed["id"]),
            )
        create_user(
            db,
            email=email,
            password_hash=password_hash,
            alumni_id=claimed["id"],
            ip=ip,
        )
        audit("claim_request", f"alumni={claimed['id']}")
        return

    if not allow_new:
        return

    rec = record_from_form(values, source="self_register")
    if not rec["full_name"]:
        return
    alumni_id = insert_alumni(db, rec, is_listed=0)
    _mark_duplicates(db)
    create_user(
        db,
        email=email,
        password_hash=password_hash,
        alumni_id=alumni_id,
        ip=ip,
    )
    audit("register_request", f"alumni={alumni_id}")


def apply_soft_profile(db, alumni_id: int, form: dict[str, str]) -> str | None:
    row = db.execute("SELECT * FROM alumni WHERE id = ?", (alumni_id,)).fetchone()
    if row is None:
        return None
    if testimonial_has_contact(form.get("testimonial")):
        return "Kesan dan pesan tidak boleh berisi nomor, email, atau tautan."
    faculty_locked = not _blank(row["faculty_code"])
    major_locked = not _blank(row["major_normalized"]) or not _blank(row["major_raw"])
    merged = {
        "full_name": row["full_name"] or "",
        "gender": (row["gender"] or "") if not _blank(row["gender"]) else form.get("gender", ""),
        "faculty": (row["faculty_code"] or row["faculty_raw"] or "")
        if faculty_locked
        else form.get("faculty", ""),
        "major": (row["major_normalized"] or row["major_raw"] or "")
        if major_locked
        else form.get("major", ""),
        "cohort_year": str(row["cohort_year"] or "")
        if not _blank(row["cohort_year"])
        else form.get("cohort_year", ""),
        "email": row["email"] or "",
        "submitted_at": row["submitted_at"] or "",
        "workplace": form.get("workplace", row["workplace"] or ""),
        "status": form.get("status", row["status_code"] or ""),
        "domicile": form.get("domicile", row["domicile"] or ""),
        "phone": form.get("phone", row["phone"] or ""),
        "testimonial": form.get("testimonial", row["testimonial"] or ""),
        "date_of_birth": form.get("date_of_birth", row["date_of_birth"] or ""),
        "graduation_year": form.get("graduation_year", str(row["graduation_year"] or "")),
        "kse_last_year": form.get("kse_last_year", str(row["kse_last_year"] or "")),
    }
    rec = record_from_form(merged, source=row["source"] or "self_register")
    for field in LOCKED_ALUMNI_FIELDS:
        if field in FILLABLE_IF_EMPTY and _blank(row[field]):
            continue
        rec[field] = row[field]
    rec["self_updated_at"] = utcnow()
    rec["updated_at"] = utcnow()
    rec["data_quality_flags"] = json.dumps(quality_flags(rec), ensure_ascii=False)
    cols = [c for c in rec.keys()]
    db.execute(
        f"UPDATE alumni SET {', '.join(c + ' = ?' for c in cols)} WHERE id = ?",
        [rec[c] for c in cols] + [alumni_id],
    )
    return None


def add_change_request(
    db,
    *,
    alumni_id: int,
    user_id: int | None,
    kind: str,
    payload: dict,
) -> bool:
    open_row = db.execute(
        """
        SELECT id FROM change_requests
        WHERE alumni_id = ? AND kind = ? AND status = 'pending'
        """,
        (alumni_id, kind),
    ).fetchone()
    if open_row:
        db.execute(
            "UPDATE change_requests SET payload = ?, created_at = ? WHERE id = ?",
            (json.dumps(payload, ensure_ascii=False), utcnow(), open_row["id"]),
        )
        return False
    db.execute(
        """
        INSERT INTO change_requests
          (alumni_id, user_id, kind, payload, status, created_at)
        VALUES (?, ?, ?, ?, 'pending', ?)
        """,
        (alumni_id, user_id, kind, json.dumps(payload, ensure_ascii=False), utcnow()),
    )
    return True


def resolve_request(db, request_id: int, status: str, admin_id: int):
    row = db.execute(
        "SELECT * FROM change_requests WHERE id = ?", (request_id,)
    ).fetchone()
    if row is None or row["status"] != "pending":
        return None
    db.execute(
        """
        UPDATE change_requests
        SET status = ?, resolved_at = ?, resolved_by = ?
        WHERE id = ?
        """,
        (status, utcnow(), admin_id, request_id),
    )
    return row


def apply_email_change(db, alumni_id: int, new_email: str) -> str | None:
    email = normalize_email(new_email)
    if not email:
        return "Email tidak valid."
    taken = db.execute(
        """
        SELECT id FROM users WHERE email = ?
        UNION
        SELECT id FROM alumni WHERE email_normalized = ? AND id != ?
        """,
        (email, email, alumni_id),
    ).fetchone()
    if taken:
        return "Email sudah dipakai."
    db.execute(
        """
        UPDATE alumni
        SET email = ?, email_normalized = ?, updated_at = ?
        WHERE id = ?
        """,
        (email, email, utcnow(), alumni_id),
    )
    db.execute(
        "UPDATE users SET email = ? WHERE alumni_id = ? AND role = 'alumni'",
        (email, alumni_id),
    )
    return None


def parse_batch_lines(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in (text or "").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        if "\t" in raw:
            parts = [p.strip() for p in raw.split("\t")]
        else:
            parts = [p.strip() for p in raw.split(";")]
        while len(parts) < 5:
            parts.append("")
        name, faculty, cohort, email, phone = parts[:5]
        if not name:
            continue
        rows.append(
            {
                "full_name": name,
                "faculty": faculty,
                "cohort_year": cohort,
                "email": email,
                "phone": phone,
            }
        )
    return rows


def insert_batch(db, rows: list[dict[str, str]]) -> list[int]:
    ids = []
    for values in rows:
        rec = record_from_form(values, source="batch")
        if not rec["full_name"]:
            continue
        ids.append(insert_alumni(db, rec, is_listed=0))
    if ids:
        _mark_duplicates(db)
    return ids


def generate_recovery_codes(db, user_id: int) -> list[str]:
    db.execute(
        "DELETE FROM recovery_codes WHERE user_id = ? AND used_at IS NULL",
        (user_id,),
    )
    codes = []
    now = utcnow()
    for _ in range(RECOVERY_CODE_COUNT):
        raw = secrets.token_hex(8)
        code = f"{raw[0:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:16]}"
        db.execute(
            """
            INSERT INTO recovery_codes (user_id, code_hash, created_at)
            VALUES (?, ?, ?)
            """,
            (user_id, token_digest(code.lower()), now),
        )
        codes.append(code)
    return codes


def consume_recovery_code(db, email: str, code: str):
    """Kembalikan baris pengurus jika kode sah, selain itu None."""
    normalized = (code or "").strip().lower()
    hashed = token_digest(normalized)
    user = db.execute(
        "SELECT * FROM users WHERE email = ? AND role = 'admin' AND status = 'active'",
        ((email or "").strip().lower(),),
    ).fetchone()
    dummy = token_digest("bukan-kode-pemulih")
    if user is None:
        secrets.compare_digest(dummy, hashed)
        return None
    row = db.execute(
        """
        SELECT * FROM recovery_codes
        WHERE user_id = ? AND code_hash = ? AND used_at IS NULL
        """,
        (user["id"], hashed),
    ).fetchone()
    if row is None:
        secrets.compare_digest(dummy, hashed)
        return None
    db.execute(
        "UPDATE recovery_codes SET used_at = ? WHERE id = ?",
        (utcnow(), row["id"]),
    )
    return user


def active_admin_count(db) -> int:
    return db.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND status = 'active'"
    ).fetchone()[0]


def review_counts(db) -> dict[str, int]:
    pending_users = db.execute(
        "SELECT COUNT(*) FROM users WHERE status = 'pending'"
    ).fetchone()[0]
    pending_requests = db.execute(
        "SELECT COUNT(*) FROM change_requests WHERE status = 'pending'"
    ).fetchone()[0]
    unlisted_new = db.execute(
        """
        SELECT COUNT(*) FROM alumni
        WHERE is_listed = 0 AND source IN ('self_register', 'batch')
        """
    ).fetchone()[0]
    return {
        "pending_users": pending_users,
        "pending_requests": pending_requests,
        "unlisted_new": unlisted_new,
        "total": pending_users + pending_requests,
    }
