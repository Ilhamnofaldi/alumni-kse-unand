from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Optional

from .db import get_db, utcnow
from .normalize import record_from_form
from .offices import apply_roles_text

MAX_IMPORT_ROWS = 4000
csv.field_size_limit(256 * 1024)

FIELD_NEEDLES = {
    "submitted_at": (("column 1",), ("timestamp",), ("waktu",)),
    "full_name": (("nama",),),
    "date_of_birth": (("tanggal lahir",),),
    "domicile": (("domisili",),),
    "workplace": (("tempat kerja",), ("kantor",)),
    "phone": (("nomor",), ("whatsapp",), ("wa",)),
    "gender": (("hehe",), ("jenis kelamin",), ("jenis_kelamin",), ("gender",)),
    "status": (("status",),),
    "email": (("email",),),
    "cohort_year": (("angkatan",),),
    "graduation_year": (("tahun lulus",),),
    "testimonial": (("kesan",),),
    "kse_last_year": (("tahun terakhir",),),
    "faculty": (("fakultas",),),
    "major": (("jurusan",),),
    "kse_roles": (("jabatan",), ("kepengurusan",), ("struktur",)),
}


def _header_map(headers: list[str]) -> dict[str, str]:
    mapping = {}
    lowered = [(h, h.lower()) for h in headers]
    used = set()
    for field, groups in FIELD_NEEDLES.items():
        for needles in groups:
            for original, low in lowered:
                if original in used:
                    continue
                if field == "status" and low.strip() != "status":
                    continue
                if field == "gender" and "nama" in low:
                    continue
                if all(n in low for n in needles):
                    mapping[field] = original
                    used.add(original)
                    break
            if field in mapping:
                break
    return mapping


def _row_values(raw: dict[str, str], mapping: dict[str, str]) -> dict[str, str]:
    return {field: (raw.get(col) or "") for field, col in mapping.items()}


def _find_existing(db, rec: dict) -> Optional[int]:
    if rec.get("email_normalized"):
        row = db.execute(
            "SELECT id FROM alumni WHERE email_normalized = ?",
            (rec["email_normalized"],),
        ).fetchone()
        if row:
            return row["id"]
    if rec.get("phone_normalized"):
        row = db.execute(
            "SELECT id FROM alumni WHERE phone_normalized = ? AND name_normalized = ?",
            (rec["phone_normalized"], rec["name_normalized"]),
        ).fetchone()
        if row:
            return row["id"]
    return None


def _mark_duplicates(db) -> None:
    from .quality import refresh_duplicate_flags

    refresh_duplicate_flags(db)


SKIP_ON_UPDATE = {
    "is_listed",
    "source",
    "created_at",
    "is_duplicate_suspect",
    "self_updated_at",
    "hide_requested",
}

# Header tetap untuk unduhan template. Impor Google Form lama tetap jalan
# lewat FIELD_NEEDLES.
TEMPLATE_HEADERS = (
    "nama",
    "jenis_kelamin",
    "tanggal_lahir",
    "fakultas",
    "jurusan",
    "angkatan",
    "tahun_lulus",
    "tahun_terakhir_kse",
    "status",
    "tempat_kerja",
    "whatsapp",
    "email",
    "domisili",
    "kesan_pesan",
    "jabatan_kse",
)


def template_csv_bytes() -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(TEMPLATE_HEADERS)
    return output.getvalue().encode("utf-8-sig")


def import_csv_path(
    path: str | Path,
    source: str = "google_form",
    insert_only: bool = False,
) -> dict:
    path = Path(path)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        mapping = _header_map(headers)
        if "full_name" not in mapping:
            raise ValueError("Kolom nama tidak ditemukan di CSV.")
        db = get_db()
        inserted = updated = skipped = protected = 0
        now = utcnow()
        row_n = 0
        for raw in reader:
            row_n += 1
            if row_n > MAX_IMPORT_ROWS:
                raise ValueError(f"CSV melebihi {MAX_IMPORT_ROWS} baris. Pecah berkasnya.")
            values = _row_values(raw, mapping)
            rec = record_from_form(values, source=source)
            if not rec["full_name"]:
                skipped += 1
                continue
            existing_id = _find_existing(db, rec)
            rec["updated_at"] = now
            alumni_id = existing_id
            if existing_id:
                if insert_only:
                    skipped += 1
                    if values.get("kse_roles"):
                        apply_roles_text(db, existing_id, values.get("kse_roles"))
                    continue
                existing = db.execute(
                    "SELECT self_updated_at FROM alumni WHERE id = ?",
                    (existing_id,),
                ).fetchone()
                if existing and existing["self_updated_at"]:
                    protected += 1
                    skipped += 1
                    continue
                cols = [k for k in rec.keys() if k not in SKIP_ON_UPDATE]
                assignments = ", ".join(f"{c} = ?" for c in cols)
                db.execute(
                    f"UPDATE alumni SET {assignments} WHERE id = ?",
                    [rec[c] for c in cols] + [existing_id],
                )
                updated += 1
            else:
                rec["created_at"] = now
                cols = list(rec.keys())
                placeholders = ", ".join("?" for _ in cols)
                cur = db.execute(
                    f"INSERT INTO alumni ({', '.join(cols)}) VALUES ({placeholders})",
                    [rec[c] for c in cols],
                )
                alumni_id = int(cur.lastrowid)
                inserted += 1
            if alumni_id and values.get("kse_roles"):
                apply_roles_text(db, alumni_id, values.get("kse_roles"))
        _mark_duplicates(db)
        total = inserted + updated + skipped
        db.execute(
            """
            INSERT INTO import_log (filename, row_count, inserted, updated, skipped, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (path.name, total, inserted, updated, skipped, now),
        )
        db.commit()
        return {
            "filename": path.name,
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "protected": protected,
            "row_count": total,
            "mapping": mapping,
        }
