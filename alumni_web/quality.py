"""Pembersihan mutu data: hitung ulang bendera dan resolusi nama kembar."""

from __future__ import annotations

import json
from typing import Iterable, Optional

from .db import audit, get_db, utcnow
from .normalize import blank_if_junk, quality_flags

# Bobot kelengkapan untuk memilih baris mana yang dipertahankan saat nama kembar.
# Kota dan jabatan KSE dihitung lebih berat daripada tempat kerja.
COMPLETENESS_FIELDS = (
    "city",
    "domicile",
    "cohort_year",
    "faculty_code",
    "major_normalized",
    "email_normalized",
    "phone_normalized",
    "status_code",
    "graduation_year",
    "kse_last_year",
    "date_of_birth",
    "workplace",
    "testimonial",
)


def _alumni_id(row) -> Optional[int]:
    try:
        keys = row.keys()
    except Exception:
        return None
    if "id" not in keys:
        return None
    value = row["id"]
    return int(value) if value is not None else None


def completeness(row, db=None) -> int:
    score = 0
    for field in COMPLETENESS_FIELDS:
        if row[field]:
            score += 2 if field == "city" else 1
    alumni_id = _alumni_id(row)
    if not alumni_id:
        return score
    conn = db
    if conn is None:
        try:
            conn = get_db()
        except RuntimeError:
            return score
    if conn.execute(
        "SELECT 1 FROM alumni_kse_roles WHERE alumni_id = ? LIMIT 1",
        (alumni_id,),
    ).fetchone():
        score += 2
    return score


def clean_junk(apply: bool = False) -> dict:
    """Kosongkan isian sampah ('-', '_', 'n/a') yang lolos impor lama."""
    db = get_db()
    changed: list[tuple[int, str, str]] = []
    rows = db.execute(
        "SELECT id, workplace, domicile, phone, testimonial, major_raw FROM alumni"
    ).fetchall()
    for row in rows:
        for field in ("workplace", "domicile", "phone", "testimonial", "major_raw"):
            current = row[field]
            if current and blank_if_junk(current) is None:
                changed.append((row["id"], field, current))
                if apply:
                    db.execute(
                        f"UPDATE alumni SET {field} = NULL WHERE id = ?", (row["id"],)
                    )
    if apply and changed:
        db.execute(
            "UPDATE alumni SET phone_normalized = NULL WHERE phone IS NULL"
        )
        audit("clean_junk", f"{len(changed)} nilai")
        db.commit()
    return {"changed": changed}


def recompute_flags(apply: bool = False) -> dict:
    """Hitung ulang `data_quality_flags` memakai aturan mutu terbaru.

    `updated_at` sengaja tidak disentuh. Bendera mutu adalah nilai turunan,
    bukan suntingan pengurus; kalau ikut diperbarui, seluruh baris melompat ke
    puncak daftar `/admin` yang terurut waktu ubah dan riwayat asli hilang.
    """
    db = get_db()
    rows = db.execute("SELECT * FROM alumni").fetchall()
    before: dict[str, int] = {}
    after: dict[str, int] = {}
    changed = 0
    for row in rows:
        for flag in json.loads(row["data_quality_flags"] or "[]"):
            before[flag] = before.get(flag, 0) + 1
        flags = quality_flags(dict(row))
        for flag in flags:
            after[flag] = after.get(flag, 0) + 1
        payload = json.dumps(flags)
        if payload != (row["data_quality_flags"] or "[]"):
            changed += 1
            if apply:
                db.execute(
                    "UPDATE alumni SET data_quality_flags = ? WHERE id = ?",
                    (payload, row["id"]),
                )
    if apply and changed:
        audit("recompute_flags", f"{changed} baris")
        db.commit()
    return {"before": before, "after": after, "changed": changed}


def refresh_duplicate_flags(db, names: Optional[Iterable[str]] = None) -> None:
    """Tandai nama kembar hanya di antara baris yang tampil (`is_listed = 1`).

    Setelah salah satu dihapus atau disembunyikan, sisa nama unik kehilangan
    bendera `is_duplicate_suspect`. Baris tersembunyi tidak menahan saudara
    yang masih di direktori.
    """
    wanted = None if names is None else [n for n in names if n]
    if wanted is not None and not wanted:
        return
    if wanted is None:
        db.execute("UPDATE alumni SET is_duplicate_suspect = 0")
        db.execute(
            """
            UPDATE alumni SET is_duplicate_suspect = 1
            WHERE is_listed = 1
              AND name_normalized != ''
              AND name_normalized IN (
                SELECT name_normalized FROM alumni
                WHERE name_normalized != '' AND is_listed = 1
                GROUP BY name_normalized
                HAVING COUNT(*) > 1
              )
            """
        )
        return
    for name in dict.fromkeys(wanted):
        db.execute(
            "UPDATE alumni SET is_duplicate_suspect = 0 WHERE name_normalized = ?",
            (name,),
        )
        listed = db.execute(
            """
            SELECT COUNT(*) FROM alumni
            WHERE name_normalized = ? AND is_listed = 1
            """,
            (name,),
        ).fetchone()[0]
        if listed > 1:
            db.execute(
                """
                UPDATE alumni SET is_duplicate_suspect = 1
                WHERE name_normalized = ? AND is_listed = 1
                """,
                (name,),
            )


def resolve_duplicates(apply: bool = False) -> dict:
    """Sembunyikan baris kembar yang paling sedikit isinya.

    Tidak menghapus apa pun: baris hanya `is_listed = 0` sehingga hilang dari
    direktori publik tetapi tetap utuh untuk pengurus. Bisa dibatalkan lewat
    kotak "Tampilkan di direktori" di form ubah.
    """
    db = get_db()
    groups = db.execute(
        """
        SELECT name_normalized FROM alumni
        WHERE name_normalized != '' AND is_listed = 1
        GROUP BY name_normalized HAVING COUNT(*) > 1
        """
    ).fetchall()
    decisions = []
    for group in groups:
        rows = db.execute(
            """
            SELECT * FROM alumni
            WHERE name_normalized = ? AND is_listed = 1
            ORDER BY id
            """,
            (group["name_normalized"],),
        ).fetchall()
        if len(rows) < 2:
            continue
        ranked = sorted(rows, key=lambda r: (-completeness(r, db), r["id"]))
        keep, hide = ranked[0], ranked[1:]
        for row in hide:
            decisions.append(
                {
                    "name": row["full_name"],
                    "keep_id": keep["id"],
                    "keep_score": completeness(keep, db),
                    "hide_id": row["id"],
                    "hide_score": completeness(row, db),
                }
            )
            if apply:
                db.execute(
                    "UPDATE alumni SET is_listed = 0, updated_at = ? WHERE id = ?",
                    (utcnow(), row["id"]),
                )
    if apply and decisions:
        refresh_duplicate_flags(db, [group["name_normalized"] for group in groups])
        audit("resolve_duplicates", f"{len(decisions)} baris disembunyikan")
        db.commit()
    return {"decisions": decisions}
