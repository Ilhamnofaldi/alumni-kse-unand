"""Template bagan kepengurusan: pola yang bisa disalin dan disesuaikan per periode."""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Optional

from .catalog import FACULTIES
from .db import utcnow
from .normalize import fold
from .offices import (
    KSE_DIVISIONS,
    KSE_OFFICES,
    get_offices,
    invalidate_office_catalog,
    role_periods,
    suggest_office_code,
    valid_office_code,
)

PROTECTED_UNITS = frozenset({"inti", "pj"})
PROTECTED_OFFICES = frozenset(
    {
        "ketua",
        "wakil_ketua",
        "sekretaris",
        "bendahara",
        "pj_universitas",
        "pj_fakultas",
    }
)
UNIT_KIND_LABELS = {
    "core": "Pengurus inti",
    "division": "Divisi",
    "wing": "Sayap",
    "pj": "Penanggung jawab",
}
SEAT_KIND_LABELS = {
    "head": "Ketua atau wakil",
    "officer": "Pengurus unit",
    "lead": "Pimpinan unit",
    "coordinator": "Koordinator",
    "member": "Anggota",
    "pj": "Penanggung jawab",
}
SEAT_KINDS = frozenset(SEAT_KIND_LABELS)
BRANCH_UNIT_KINDS = frozenset({"division", "wing"})
# Tempat tetap di bagan publik. Urutan hanya bisa diubah di dalam satu tingkat.
FIXED_UNIT_KINDS = frozenset({"core", "pj"})
UNIT_BANDS = (
    {
        "kind": "core",
        "title": "Puncak bagan",
        "note": "Pengurus inti selalu di sini. Yang bisa diubah: sisi kiri atau kanan pada satu baris — ketua dengan wakil, sekretaris dengan bendahara.",
    },
    {
        "kind": "division",
        "title": "Divisi",
        "note": "Kartu berjajar di bawah pengurus inti. Geser kiri atau kanan mengubah urutan kartu, bukan menaikkan divisi ke atas ketua.",
    },
    {
        "kind": "wing",
        "title": "Sayap",
        "note": "Tampil sendiri di bawah deret divisi. Dua pengurus di sayap ini berjajar, jadi gesernya kiri atau kanan. Naik atau turun hanya untuk menukar urutan antar-sayap.",
    },
    {
        "kind": "pj",
        "title": "Dasar bagan",
        "note": "Penanggung jawab selalu di sini. Posisinya tidak bisa ditukar dengan unit lain.",
    },
)
_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS kse_office_defs (
  code TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  short TEXT NOT NULL,
  kind TEXT NOT NULL,
  unit_code TEXT,
  needs_scope INTEGER NOT NULL DEFAULT 0,
  unspecified INTEGER NOT NULL DEFAULT 0,
  aliases TEXT NOT NULL DEFAULT '[]',
  is_builtin INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS org_blueprints (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL CHECK(kind IN ('template', 'period')),
  slug TEXT,
  period_start INTEGER,
  title TEXT NOT NULL,
  notes TEXT,
  copied_from_id INTEGER REFERENCES org_blueprints(id) ON DELETE SET NULL,
  is_default INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_org_blueprint_slug
  ON org_blueprints(slug) WHERE kind = 'template' AND slug IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_org_blueprint_period
  ON org_blueprints(period_start) WHERE kind = 'period';

CREATE TABLE IF NOT EXISTS org_units (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  blueprint_id INTEGER NOT NULL REFERENCES org_blueprints(id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  unit_kind TEXT NOT NULL CHECK(unit_kind IN ('core', 'division', 'wing', 'pj')),
  title TEXT NOT NULL,
  lead_role TEXT,
  tone TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  is_visible INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_org_units_code
  ON org_units(blueprint_id, code);

CREATE TABLE IF NOT EXISTS org_seats (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  unit_id INTEGER NOT NULL REFERENCES org_units(id) ON DELETE CASCADE,
  office_code TEXT NOT NULL,
  label TEXT NOT NULL,
  short TEXT NOT NULL,
  seat_kind TEXT NOT NULL CHECK(seat_kind IN ('head', 'officer', 'lead', 'coordinator', 'member', 'pj')),
  pair_group INTEGER,
  sort_order INTEGER NOT NULL DEFAULT 0,
  parent_seat_id INTEGER REFERENCES org_seats(id) ON DELETE SET NULL
);
"""
_ORG_SEATS_DDL = """
CREATE TABLE org_seats (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  unit_id INTEGER NOT NULL REFERENCES org_units(id) ON DELETE CASCADE,
  office_code TEXT NOT NULL,
  label TEXT NOT NULL,
  short TEXT NOT NULL,
  seat_kind TEXT NOT NULL CHECK(seat_kind IN ('head', 'officer', 'lead', 'coordinator', 'member', 'pj')),
  pair_group INTEGER,
  sort_order INTEGER NOT NULL DEFAULT 0,
  parent_seat_id INTEGER REFERENCES org_seats(id) ON DELETE SET NULL
);
"""


def _ensure_default_column(db) -> bool:
    info = db.execute("PRAGMA table_info(org_blueprints)").fetchall()
    if not info:
        return False
    cols = {row[1] for row in info}
    changed = False
    if "is_default" not in cols:
        db.execute(
            "ALTER TABLE org_blueprints ADD COLUMN is_default INTEGER NOT NULL DEFAULT 0"
        )
        changed = True
    has_index = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'idx_org_blueprint_one_default'"
    ).fetchone()
    if not has_index:
        db.execute(
            """
            CREATE UNIQUE INDEX idx_org_blueprint_one_default
            ON org_blueprints(is_default) WHERE kind = 'template' AND is_default = 1
            """
        )
        changed = True
    return changed


def _org_seats_needs_rebuild(db) -> bool:
    info = db.execute("PRAGMA table_info(org_seats)").fetchall()
    if not info:
        return False
    cols = {row[1] for row in info}
    if "parent_seat_id" not in cols:
        return True
    sql = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'org_seats'"
    ).fetchone()
    return not sql or "coordinator" not in (sql[0] or "")


def _rebuild_org_seats(db) -> None:
    """SQLite tidak bisa ALTER CHECK: salin tabel, lalu ganti."""
    info = db.execute("PRAGMA table_info(org_seats)").fetchall()
    cols = {row[1] for row in info}
    has_parent = "parent_seat_id" in cols
    db.execute("PRAGMA foreign_keys = OFF")
    db.execute("DROP TABLE IF EXISTS org_seats_migrate")
    db.execute(
        """
        CREATE TABLE org_seats_migrate (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          unit_id INTEGER NOT NULL,
          office_code TEXT NOT NULL,
          label TEXT NOT NULL,
          short TEXT NOT NULL,
          seat_kind TEXT NOT NULL,
          pair_group INTEGER,
          sort_order INTEGER NOT NULL DEFAULT 0,
          parent_seat_id INTEGER
        )
        """
    )
    if has_parent:
        db.execute(
            """
            INSERT INTO org_seats_migrate (
              id, unit_id, office_code, label, short, seat_kind, pair_group, sort_order, parent_seat_id
            )
            SELECT id, unit_id, office_code, label, short, seat_kind, pair_group, sort_order, parent_seat_id
            FROM org_seats
            """
        )
    else:
        db.execute(
            """
            INSERT INTO org_seats_migrate (
              id, unit_id, office_code, label, short, seat_kind, pair_group, sort_order, parent_seat_id
            )
            SELECT id, unit_id, office_code, label, short, seat_kind, pair_group, sort_order, NULL
            FROM org_seats
            """
        )
    db.execute("DROP TABLE org_seats")
    db.executescript(_ORG_SEATS_DDL)
    db.execute(
        """
        INSERT INTO org_seats (
          id, unit_id, office_code, label, short, seat_kind, pair_group, sort_order, parent_seat_id
        )
        SELECT id, unit_id, office_code, label, short, seat_kind, pair_group, sort_order, parent_seat_id
        FROM org_seats_migrate
        """
    )
    db.execute("DROP TABLE org_seats_migrate")
    max_id = db.execute("SELECT MAX(id) FROM org_seats").fetchone()[0]
    if max_id:
        db.execute(
            "UPDATE sqlite_sequence SET seq = ? WHERE name = 'org_seats'",
            (max_id,),
        )
        if not db.execute(
            "SELECT 1 FROM sqlite_sequence WHERE name = 'org_seats'"
        ).fetchone():
            db.execute(
                "INSERT INTO sqlite_sequence (name, seq) VALUES ('org_seats', ?)",
                (max_id,),
            )
    db.execute("PRAGMA foreign_keys = ON")


def _promote_extra_leads(db) -> bool:
    """Lead pertama per unit tetap pimpinan; lead tambahan jadi koordinator."""
    changed = False
    touched: set[int] = set()
    units = db.execute("SELECT DISTINCT unit_id FROM org_seats WHERE seat_kind = 'lead'").fetchall()
    for unit in units:
        leads = db.execute(
            """
            SELECT id FROM org_seats
            WHERE unit_id = ? AND seat_kind = 'lead'
            ORDER BY sort_order, id
            """,
            (unit["unit_id"],),
        ).fetchall()
        for extra in leads[1:]:
            db.execute(
                "UPDATE org_seats SET seat_kind = 'coordinator' WHERE id = ?",
                (extra["id"],),
            )
            touched.add(unit["unit_id"])
            changed = True
    for unit_id in touched:
        pack_unit_seats(db, unit_id)
    return changed


def _ensure_seat_tree(db) -> bool:
    info = db.execute("PRAGMA table_info(org_seats)").fetchall()
    if not info:
        return False
    changed = False
    if _org_seats_needs_rebuild(db):
        _rebuild_org_seats(db)
        changed = True
    if _promote_extra_leads(db):
        changed = True
    return changed


def _rename_legacy_titles(db) -> bool:
    if not db.execute(
        "SELECT 1 FROM org_blueprints WHERE slug = 'umum' AND title = 'Acuan umum'"
    ).fetchone():
        return False
    db.execute(
        "UPDATE org_blueprints SET title = 'Template umum' WHERE slug = 'umum' AND title = 'Acuan umum'"
    )
    return True


def _ensure_one_default(db) -> bool:
    if db.execute(
        "SELECT 1 FROM org_blueprints WHERE kind = 'template' AND is_default = 1"
    ).fetchone():
        return False
    if db.execute(
        "SELECT 1 FROM org_blueprints WHERE kind = 'template' AND slug = 'umum'"
    ).fetchone():
        db.execute(
            "UPDATE org_blueprints SET is_default = 1 WHERE kind = 'template' AND slug = 'umum'"
        )
        return True
    first = db.execute(
        "SELECT id FROM org_blueprints WHERE kind = 'template' ORDER BY id LIMIT 1"
    ).fetchone()
    if not first:
        return False
    db.execute(
        "UPDATE org_blueprints SET is_default = 1 WHERE id = ?",
        (first["id"],),
    )
    return True


def _default_slug(db) -> str:
    row = db.execute(
        "SELECT slug FROM org_blueprints WHERE kind = 'template' AND is_default = 1"
    ).fetchone()
    if row and row["slug"]:
        return row["slug"]
    umum = db.execute(
        "SELECT slug FROM org_blueprints WHERE kind = 'template' AND slug = 'umum'"
    ).fetchone()
    if umum:
        return "umum"
    first = db.execute(
        "SELECT slug FROM org_blueprints WHERE kind = 'template' ORDER BY id"
    ).fetchone()
    return first["slug"] if first else "umum"


def _ensure_tables(db) -> None:
    """Siapkan tabel dan template bawaan. Tidak membekukan periode."""
    db.executescript(_TABLES_SQL)
    mutated = _ensure_default_column(db)
    if _ensure_seat_tree(db):
        mutated = True
    has_template = db.execute(
        "SELECT 1 FROM org_blueprints WHERE kind = 'template'"
    ).fetchone()
    if not has_template:
        try:
            seed_builtin_templates(db)
            mutated = True
        except sqlite3.IntegrityError:
            db.rollback()
            db.executescript(_TABLES_SQL)
            mutated = _ensure_default_column(db)
            if not db.execute(
                "SELECT 1 FROM org_blueprints WHERE kind = 'template'"
            ).fetchone():
                raise
    if _rename_legacy_titles(db):
        mutated = True
    if _ensure_one_default(db):
        mutated = True
    if mutated:
        db.commit()


def ensure_org_layout(db) -> None:
    _ensure_tables(db)
    # Tahun yang sudah punya riwayat jabatan harus punya salinan sendiri.
    # Kalau tidak, menyunting template akan mengubah bagan lama.
    if capture_appeared_periods(db):
        db.commit()


def seed_builtin_templates(db) -> None:
    umum_id = _insert_blueprint(
        db,
        kind="template",
        slug="umum",
        title="Template umum",
        notes="Inti, divisi dengan sekbend, dan penanggung jawab. Hanya dipakai bagan yang baru muncul.",
        is_default=1,
    )
    _fill_standard_units(db, umum_id, wing_comdev=False, include_mnb=False)
    wing_id = _insert_blueprint(
        db,
        kind="template",
        slug="comdev_terpisah",
        title="Comdev terpisah",
        notes="Community Development jadi sayap sendiri: ketua, sekbend, MnB, lalu anggota.",
    )
    _fill_standard_units(db, wing_id, wing_comdev=True, include_mnb=True)


def _insert_blueprint(
    db,
    *,
    kind: str,
    title: str,
    slug: Optional[str] = None,
    period_start=None,
    notes=None,
    copied_from_id=None,
    is_default: int = 0,
) -> int:
    now = utcnow()
    cur = db.execute(
        """
        INSERT INTO org_blueprints (
          kind, slug, period_start, title, notes, copied_from_id, is_default, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (kind, slug, period_start, title, notes, copied_from_id, is_default, now, now),
    )
    return int(cur.lastrowid)


def _office(code: str) -> dict[str, Any]:
    return KSE_OFFICES[code]


def _add_unit(db, blueprint_id: int, *, code: str, unit_kind: str, title: str, lead_role=None, tone=None, sort_order=0) -> int:
    cur = db.execute(
        """
        INSERT INTO org_units (
          blueprint_id, code, unit_kind, title, lead_role, tone, sort_order, is_visible
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (blueprint_id, code, unit_kind, title, lead_role, tone, sort_order),
    )
    return int(cur.lastrowid)


def _add_seat(
    db,
    unit_id: int,
    office_code: str,
    *,
    seat_kind: str,
    pair_group: Optional[int] = None,
    sort_order: int = 0,
    label: Optional[str] = None,
    short: Optional[str] = None,
    parent_seat_id: Optional[int] = None,
) -> int:
    meta = get_offices(db).get(office_code) or _office(office_code)
    cur = db.execute(
        """
        INSERT INTO org_seats (
          unit_id, office_code, label, short, seat_kind, pair_group, sort_order, parent_seat_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            unit_id,
            office_code,
            label or meta["label"],
            short or meta["short"],
            seat_kind,
            pair_group,
            sort_order,
            parent_seat_id,
        ),
    )
    return int(cur.lastrowid)


def _fill_standard_units(db, blueprint_id: int, *, wing_comdev: bool, include_mnb: bool) -> None:
    inti = _add_unit(
        db, blueprint_id, code="inti", unit_kind="core", title="Pengurus inti", sort_order=0
    )
    _add_seat(db, inti, "ketua", seat_kind="head", pair_group=1, sort_order=0)
    _add_seat(db, inti, "wakil_ketua", seat_kind="head", pair_group=1, sort_order=1)
    _add_seat(db, inti, "sekretaris", seat_kind="officer", pair_group=2, sort_order=2)
    _add_seat(db, inti, "bendahara", seat_kind="officer", pair_group=2, sort_order=3)

    for index, unit in enumerate(KSE_DIVISIONS, start=1):
        is_wing = wing_comdev and unit["code"] == "community_development"
        unit_id = _add_unit(
            db,
            blueprint_id,
            code=unit["code"],
            unit_kind="wing" if is_wing else "division",
            title=unit["title"],
            lead_role=unit["lead_role"],
            tone=unit["tone"],
            sort_order=index,
        )
        order = 0
        _add_seat(db, unit_id, unit["lead"], seat_kind="lead", sort_order=order)
        order += 1
        sekbend = unit.get("sekbend") or f"sekbend_{unit['code']}"
        _add_seat(db, unit_id, sekbend, seat_kind="officer", sort_order=order)
        order += 1
        if include_mnb and unit["code"] == "community_development":
            _add_seat(db, unit_id, "mnb_community_development", seat_kind="officer", sort_order=order)
            order += 1
        _add_seat(db, unit_id, unit["member"], seat_kind="member", sort_order=order)

    pj = _add_unit(
        db,
        blueprint_id,
        code="pj",
        unit_kind="pj",
        title="Penanggung jawab",
        sort_order=90,
    )
    _add_seat(db, pj, "pj_universitas", seat_kind="pj", sort_order=0)
    _add_seat(db, pj, "pj_fakultas", seat_kind="pj", sort_order=1)


def list_templates(db) -> list[dict[str, Any]]:
    _ensure_tables(db)
    return [
        dict(row)
        for row in db.execute(
            """
            SELECT * FROM org_blueprints
            WHERE kind = 'template'
            ORDER BY is_default DESC, title COLLATE NOCASE, id
            """
        )
    ]


def list_period_layouts(db) -> list[int]:
    _ensure_tables(db)
    return [
        row["period_start"]
        for row in db.execute(
            """
            SELECT period_start FROM org_blueprints
            WHERE kind = 'period' AND period_start IS NOT NULL
            ORDER BY period_start DESC
            """
        )
    ]


def template_by_slug(db, slug: str) -> Optional[dict[str, Any]]:
    _ensure_tables(db)
    row = db.execute(
        "SELECT * FROM org_blueprints WHERE kind = 'template' AND slug = ?",
        (slug,),
    ).fetchone()
    return load_blueprint(db, row["id"]) if row else None


def period_blueprint(db, period_start: int) -> Optional[dict[str, Any]]:
    _ensure_tables(db)
    row = db.execute(
        "SELECT id FROM org_blueprints WHERE kind = 'period' AND period_start = ?",
        (period_start,),
    ).fetchone()
    return load_blueprint(db, row["id"]) if row else None


def load_blueprint(db, blueprint_id: int) -> dict[str, Any]:
    row = db.execute("SELECT * FROM org_blueprints WHERE id = ?", (blueprint_id,)).fetchone()
    if row is None:
        raise ValueError("Bagan tidak ditemukan.")
    units = []
    for unit in db.execute(
        "SELECT * FROM org_units WHERE blueprint_id = ? ORDER BY sort_order, id",
        (blueprint_id,),
    ):
        item = dict(unit)
        item["seats"] = sort_seats_for_display(
            [
                dict(seat)
                for seat in db.execute(
                    "SELECT * FROM org_seats WHERE unit_id = ?",
                    (unit["id"],),
                )
            ]
        )
        units.append(item)
    source = None
    if row["copied_from_id"]:
        parent = db.execute(
            "SELECT title, slug, kind, period_start FROM org_blueprints WHERE id = ?",
            (row["copied_from_id"],),
        ).fetchone()
        if parent:
            source = dict(parent)
    data = dict(row)
    data["units"] = units
    data["is_custom"] = row["kind"] == "period"
    data["is_default"] = bool(row["is_default"]) if "is_default" in row.keys() else False
    data["source"] = source
    return annotate_reorder(data)


def default_template_slug(db) -> str:
    _ensure_tables(db)
    return _default_slug(db)


def default_template(db) -> Optional[dict[str, Any]]:
    return template_by_slug(db, default_template_slug(db))


def set_default_template(db, slug: str) -> tuple[bool, str]:
    _ensure_tables(db)
    slug = (slug or "").strip()
    row = db.execute(
        "SELECT id, title FROM org_blueprints WHERE kind = 'template' AND slug = ?",
        (slug,),
    ).fetchone()
    if not row:
        return False, "Template itu tidak ada."
    db.execute("UPDATE org_blueprints SET is_default = 0 WHERE kind = 'template'")
    db.execute(
        "UPDATE org_blueprints SET is_default = 1, updated_at = ? WHERE kind = 'template' AND slug = ?",
        (utcnow(), slug),
    )
    return True, f"{row['title']} sekarang dipakai sebagai template bawaan."


def create_template(db, title: str, source_token: str) -> tuple[Optional[dict[str, Any]], str]:
    _ensure_tables(db)
    clean = fold(title)
    if not clean:
        return None, "Nama template tidak boleh kosong."
    taken = {
        row["slug"]
        for row in db.execute(
            "SELECT slug FROM org_blueprints WHERE kind = 'template' AND slug IS NOT NULL"
        )
    }
    slug = make_unit_code(clean, taken)
    source_id = source_blueprint_id(db, source_token)
    new_id = copy_blueprint(db, source_id, kind="template", title=clean, slug=slug)
    return load_blueprint(db, new_id), f"Template {clean} sudah dibuat."


def rename_template(db, slug: str, title: str, notes: Optional[str] = None) -> tuple[bool, str]:
    _ensure_tables(db)
    clean = fold(title)
    if not clean:
        return False, "Nama template tidak boleh kosong."
    row = db.execute(
        "SELECT id FROM org_blueprints WHERE kind = 'template' AND slug = ?",
        (slug,),
    ).fetchone()
    if not row:
        return False, "Template itu tidak ada."
    db.execute(
        "UPDATE org_blueprints SET title = ?, notes = ?, updated_at = ? WHERE id = ?",
        (clean, (notes or "").strip() or None, utcnow(), row["id"]),
    )
    return True, "Nama template sudah disimpan."


def delete_template(db, slug: str) -> tuple[bool, str]:
    _ensure_tables(db)
    row = db.execute(
        """
        SELECT id, title, is_default FROM org_blueprints
        WHERE kind = 'template' AND slug = ?
        """,
        (slug,),
    ).fetchone()
    if not row:
        return False, "Template itu tidak ada."
    count = db.execute(
        "SELECT COUNT(*) AS n FROM org_blueprints WHERE kind = 'template'"
    ).fetchone()["n"]
    if count <= 1:
        return False, "Tidak bisa menghapus satu-satunya template."
    if row["is_default"]:
        return False, "Jadikan template lain sebagai bawaan dulu, baru hapus yang ini."
    db.execute("DELETE FROM org_blueprints WHERE id = ?", (row["id"],))
    return True, f"Template {row['title']} sudah dihapus."


def capture_appeared_year(db, year: Optional[int], source: Optional[str] = None) -> bool:
    """Bekukan bagan tahun ini ke salinan template, sekali saja.

    Dipanggil saat periode baru tampil: alumni mengisi riwayat jabatan, atau
    pengurus menyiapkan tahun itu. Tahun yang sudah punya salinan tidak disentuh,
    jadi menyunting template tidak mengubah riwayat yang sudah ada.
    """
    if not year:
        return False
    _ensure_tables(db)
    exists = db.execute(
        "SELECT id FROM org_blueprints WHERE kind = 'period' AND period_start = ?",
        (year,),
    ).fetchone()
    if exists:
        return False
    customize_period(db, year, source or default_template_slug(db))
    return True


def capture_appeared_periods(db) -> int:
    """Bekukan semua tahun yang sudah punya riwayat jabatan tetapi belum tersalin."""
    _ensure_tables(db)
    frozen = 0
    for year in role_periods(db):
        if capture_appeared_year(db, year):
            frozen += 1
    return frozen


def resolve_layout(db, period_start: Optional[int] = None) -> dict[str, Any]:
    ensure_org_layout(db)
    if period_start:
        custom = period_blueprint(db, period_start)
        if custom:
            return custom
    fallback = default_template(db) or template_by_slug(db, "umum")
    if fallback:
        return fallback
    return {
        "id": None,
        "kind": "template",
        "slug": "umum",
        "title": "Template umum",
        "units": [],
        "unit_bands": [],
        "is_custom": False,
        "is_default": True,
        "source": None,
    }


def copy_blueprint(
    db,
    source_id: int,
    *,
    kind: str,
    title: str,
    slug: Optional[str] = None,
    period_start: Optional[int] = None,
) -> int:
    new_id = _insert_blueprint(
        db,
        kind=kind,
        title=title,
        slug=slug,
        period_start=period_start,
        copied_from_id=source_id,
    )
    for unit in db.execute(
        "SELECT * FROM org_units WHERE blueprint_id = ? ORDER BY sort_order, id",
        (source_id,),
    ):
        cur = db.execute(
            """
            INSERT INTO org_units (
              blueprint_id, code, unit_kind, title, lead_role, tone, sort_order, is_visible
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id,
                unit["code"],
                unit["unit_kind"],
                unit["title"],
                unit["lead_role"],
                unit["tone"],
                unit["sort_order"],
                unit["is_visible"],
            ),
        )
        new_unit = int(cur.lastrowid)
        id_map: dict[int, int] = {}
        pending_parents: list[tuple[int, int]] = []
        for seat in db.execute(
            "SELECT * FROM org_seats WHERE unit_id = ? ORDER BY sort_order, id",
            (unit["id"],),
        ):
            parent = None
            if "parent_seat_id" in seat.keys():
                parent = seat["parent_seat_id"]
            inserted = db.execute(
                """
                INSERT INTO org_seats (
                  unit_id, office_code, label, short, seat_kind, pair_group, sort_order, parent_seat_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    new_unit,
                    seat["office_code"],
                    seat["label"],
                    seat["short"],
                    seat["seat_kind"],
                    seat["pair_group"],
                    seat["sort_order"],
                ),
            )
            new_seat_id = int(inserted.lastrowid)
            id_map[seat["id"]] = new_seat_id
            if parent:
                pending_parents.append((new_seat_id, int(parent)))
        for new_seat_id, old_parent in pending_parents:
            mapped = id_map.get(old_parent)
            if mapped:
                db.execute(
                    "UPDATE org_seats SET parent_seat_id = ? WHERE id = ?",
                    (mapped, new_seat_id),
                )
    _touch(db, new_id)
    return new_id


def source_blueprint_id(db, token: Optional[str] = None) -> int:
    _ensure_tables(db)
    fallback = _default_slug(db)
    token = (token or "").strip() or fallback
    if token.startswith("period:"):
        try:
            year = int(token.split(":", 1)[1])
        except ValueError:
            year = 0
        row = db.execute(
            "SELECT id FROM org_blueprints WHERE kind = 'period' AND period_start = ?",
            (year,),
        ).fetchone()
        if row:
            return row["id"]
        token = fallback
    row = db.execute(
        "SELECT id FROM org_blueprints WHERE kind = 'template' AND slug = ?",
        (token,),
    ).fetchone()
    if row:
        return row["id"]
    fallback_row = db.execute(
        "SELECT id FROM org_blueprints WHERE kind = 'template' AND slug = ?",
        (fallback,),
    ).fetchone()
    if fallback_row:
        return fallback_row["id"]
    umum = db.execute(
        "SELECT id FROM org_blueprints WHERE kind = 'template' AND slug = 'umum'"
    ).fetchone()
    if umum:
        return umum["id"]
    raise ValueError("Belum ada template bagan.")


def customize_period(
    db, period_start: int, source_token: Optional[str] = None, *, replace: bool = False
) -> dict[str, Any]:
    existing = period_blueprint(db, period_start)
    if existing and not replace:
        return existing
    if existing:
        db.execute(
            "DELETE FROM org_blueprints WHERE kind = 'period' AND period_start = ?",
            (period_start,),
        )
    source_id = source_blueprint_id(db, source_token)
    try:
        new_id = copy_blueprint(
            db,
            source_id,
            kind="period",
            title=f"Periode {period_start}/{period_start + 1}",
            period_start=period_start,
        )
        return load_blueprint(db, new_id)
    except sqlite3.IntegrityError:
        db.rollback()
        existing = period_blueprint(db, period_start)
        if existing:
            return existing
        raise


def reset_period(db, period_start: int) -> bool:
    """Ganti bagan tahun ini dengan salinan template bawaan yang berlaku sekarang.

    Bukan live-follow: setelah ini, menyunting template lagi tidak mengubah tahun ini.
    """
    if period_blueprint(db, period_start) is None:
        return False
    customize_period(db, period_start, default_template_slug(db), replace=True)
    return True


def _touch(db, blueprint_id: int) -> None:
    db.execute(
        "UPDATE org_blueprints SET updated_at = ? WHERE id = ?",
        (utcnow(), blueprint_id),
    )


def _unit_row(db, unit_id: int):
    return db.execute("SELECT * FROM org_units WHERE id = ?", (unit_id,)).fetchone()


def _seat_row(db, seat_id: int):
    return db.execute(
        """
        SELECT s.*, u.blueprint_id, u.code AS unit_code, u.unit_kind
        FROM org_seats s
        JOIN org_units u ON u.id = s.unit_id
        WHERE s.id = ?
        """,
        (seat_id,),
    ).fetchone()


def update_unit(
    db,
    unit_id: int,
    *,
    title: Optional[str] = None,
    lead_role: Optional[str] = None,
    unit_kind: Optional[str] = None,
    is_visible: Optional[bool] = None,
) -> str:
    unit = _unit_row(db, unit_id)
    if unit is None:
        return "Unit itu tidak ditemukan."
    fields = []
    params: list[Any] = []
    if title is not None:
        clean = fold(title)
        if not clean:
            return "Nama unit wajib diisi."
        fields.append("title = ?")
        params.append(clean)
    if lead_role is not None and unit["unit_kind"] in {"division", "wing"}:
        fields.append("lead_role = ?")
        params.append(fold(lead_role) or None)
    if unit_kind in {"division", "wing"} and unit["unit_kind"] in {"division", "wing"}:
        fields.append("unit_kind = ?")
        params.append(unit_kind)
    if is_visible is not None and unit["code"] not in PROTECTED_UNITS:
        fields.append("is_visible = ?")
        params.append(1 if is_visible else 0)
    if not fields:
        return "Tidak ada yang diubah."
    params.append(unit_id)
    db.execute(f"UPDATE org_units SET {', '.join(fields)} WHERE id = ?", params)
    _touch(db, unit["blueprint_id"])
    return "Unit diperbarui."


def delete_unit(db, unit_id: int) -> str:
    unit = _unit_row(db, unit_id)
    if unit is None:
        return "Unit itu tidak ditemukan."
    if unit["code"] in PROTECTED_UNITS or unit["unit_kind"] in {"core", "pj"}:
        return "Pengurus inti dan penanggung jawab tidak boleh dihapus."
    db.execute("DELETE FROM org_units WHERE id = ?", (unit_id,))
    _touch(db, unit["blueprint_id"])
    return "Unit dihapus dari bagan ini. Catatan jabatan orang tidak ikut terhapus."


SEAT_BAND_ORDER = ("head", "lead", "officer_pair", "officer", "coordinator", "member", "pj")


def _row_parent_id(row) -> Optional[int]:
    if row is None:
        return None
    if isinstance(row, dict):
        value = row.get("parent_seat_id")
    elif "parent_seat_id" in row.keys():
        value = row["parent_seat_id"]
    else:
        return None
    return int(value) if value is not None else None


def seat_display_band(seat: dict[str, Any]) -> str:
    """Kelompok tampil di bagan publik, bukan urutan daftar pengaturan."""
    pair = seat.get("pair_group")
    kind = seat.get("seat_kind") or ""
    if pair == 1 or kind == "head":
        return "head"
    if pair == 2:
        return "officer_pair"
    if kind in {"lead", "officer", "coordinator", "member", "pj"}:
        return kind
    return kind or "other"


def seat_peer_key(seat: dict[str, Any]) -> tuple[Any, ...]:
    """Geser hanya sesama tingkat, dan anggota hanya di dalam tim yang sama."""
    return (seat_display_band(seat), _row_parent_id(seat))


def seat_band_rank(band: str) -> int:
    try:
        return SEAT_BAND_ORDER.index(band)
    except ValueError:
        return SEAT_BAND_ORDER.index("officer")


def sort_seats_for_display(seats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    children: dict[int, list[dict[str, Any]]] = {}
    roots: list[dict[str, Any]] = []
    for seat in seats:
        parent = _row_parent_id(seat)
        if parent:
            children.setdefault(parent, []).append(seat)
        else:
            roots.append(seat)
    roots.sort(
        key=lambda seat: (
            seat_band_rank(seat_display_band(seat)),
            seat.get("sort_order") or 0,
            seat.get("id") or 0,
        )
    )
    packed: list[dict[str, Any]] = []
    for seat in roots:
        packed.append(seat)
        kids = children.pop(seat.get("id"), [])
        kids.sort(key=lambda item: (item.get("sort_order") or 0, item.get("id") or 0))
        packed.extend(kids)
    for leftovers in children.values():
        leftovers.sort(key=lambda item: (item.get("sort_order") or 0, item.get("id") or 0))
        packed.extend(leftovers)
    return packed


def pack_unit_seats(db, unit_id: int) -> bool:
    """Tulis ulang sort_order: pimpinan, pengurus, koordinator + tim, anggota unit."""
    rows = [dict(row) for row in db.execute("SELECT * FROM org_seats WHERE unit_id = ?", (unit_id,))]
    packed = sort_seats_for_display(rows)
    changed = False
    for index, row in enumerate(packed):
        if row["sort_order"] != index:
            db.execute("UPDATE org_seats SET sort_order = ? WHERE id = ?", (index, row["id"]))
            changed = True
    return changed


def repair_blueprint_seats(db, blueprint_id: int) -> bool:
    changed = False
    for row in db.execute("SELECT id FROM org_units WHERE blueprint_id = ?", (blueprint_id,)):
        if pack_unit_seats(db, row["id"]):
            changed = True
    return changed


def _shift_labels(axis: str) -> tuple[str, str]:
    if axis == "horizontal":
        return "Geser kiri", "Geser kanan"
    return "Naik", "Turun"


def _seat_shift_axis(unit_kind: str, band: str, peer_count: int) -> str:
    # Dua jabatan sejenis yang di bagan publik berjajar (org_pair).
    paired = band in {"head", "officer_pair"} or (
        band == "officer" and unit_kind == "wing"
    ) or (
        band == "coordinator" and peer_count == 2
    )
    if paired and peer_count == 2:
        return "horizontal"
    return "vertical"


def annotate_reorder(blueprint: dict[str, Any]) -> dict[str, Any]:
    units = blueprint.get("units") or []
    groups: dict[str, list[dict[str, Any]]] = {}
    for unit in units:
        groups.setdefault(unit["unit_kind"], []).append(unit)
    for kind, group in groups.items():
        movable = kind not in FIXED_UNIT_KINDS
        axis = "horizontal" if kind == "division" else "vertical"
        prev_label, next_label = _shift_labels(axis)
        visible = [unit for unit in group if unit.get("is_visible", 1)]
        for unit in group:
            unit["shift_axis"] = axis
            unit["shift_prev_label"] = prev_label
            unit["shift_next_label"] = next_label
            if movable and unit in visible:
                index = visible.index(unit)
                unit["can_shift_prev"] = index > 0
                unit["can_shift_next"] = index < len(visible) - 1
            else:
                unit["can_shift_prev"] = False
                unit["can_shift_next"] = False
            _annotate_seat_shifts(unit, kind)
            unit["seat_tree"] = _seat_tree(unit.get("seats") or [])
            unit["coordinator_options"] = [
                seat for seat in unit.get("seats") or [] if seat.get("seat_kind") == "coordinator"
            ]
    blueprint["unit_bands"] = [
        {**band, "units": groups[band["kind"]]}
        for band in UNIT_BANDS
        if band["kind"] in groups
    ]
    return blueprint


def _annotate_seat_shifts(unit: dict[str, Any], unit_kind: str) -> None:
    seats = unit.get("seats") or []
    peers: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for seat in seats:
        band = seat_display_band(seat)
        seat["display_band"] = band
        peers.setdefault(seat_peer_key(seat), []).append(seat)
    for seat in seats:
        band = seat["display_band"]
        group = peers[seat_peer_key(seat)]
        axis = _seat_shift_axis(unit_kind, band, len(group))
        prev_label, next_label = _shift_labels(axis)
        index = group.index(seat)
        seat["shift_axis"] = axis
        seat["shift_prev_label"] = prev_label
        seat["shift_next_label"] = next_label
        movable = band != "pj" and len(group) > 1
        seat["can_shift_prev"] = movable and index > 0
        seat["can_shift_next"] = movable and index < len(group) - 1


def _seat_tree(seats: list[dict[str, Any]]) -> dict[str, Any]:
    """Kelompokkan kursi editor mengikuti cabang bagan."""
    by_parent: dict[int, list[dict[str, Any]]] = {}
    for seat in seats:
        parent = _row_parent_id(seat)
        if parent:
            by_parent.setdefault(parent, []).append(seat)
    teams = []
    for seat in seats:
        if seat.get("seat_kind") != "coordinator":
            continue
        teams.append(
            {
                "coordinator": seat,
                "members": by_parent.get(seat.get("id"), []),
            }
        )
    return {
        "leads": [seat for seat in seats if seat.get("seat_kind") == "lead"],
        "heads": [seat for seat in seats if seat.get("seat_kind") == "head"],
        "officers": [seat for seat in seats if seat.get("seat_kind") == "officer"],
        "teams": teams,
        "unit_members": [
            seat
            for seat in seats
            if seat.get("seat_kind") == "member" and not _row_parent_id(seat)
        ],
        "pjs": [seat for seat in seats if seat.get("seat_kind") == "pj"],
    }


def move_unit(db, unit_id: int, direction: str) -> str:
    unit = _unit_row(db, unit_id)
    if unit is None:
        return "Unit itu tidak ditemukan."
    if unit["unit_kind"] in FIXED_UNIT_KINDS:
        return "Pengurus inti dan penanggung jawab tidak bisa dipindah. Di bagan mereka tetap di puncak dan di dasar."
    siblings = db.execute(
        """
        SELECT id, sort_order FROM org_units
        WHERE blueprint_id = ? AND unit_kind = ?
        ORDER BY sort_order, id
        """,
        (unit["blueprint_id"], unit["unit_kind"]),
    ).fetchall()
    if not _swap_order(db, "org_units", siblings, unit_id, direction):
        return "Urutan tidak berubah. Unit hanya bisa ditukar dengan unit sejenis."
    _touch(db, unit["blueprint_id"])
    if unit["unit_kind"] == "division":
        return "Urutan divisi diperbarui."
    return "Urutan sayap diperbarui."


def move_seat(db, seat_id: int, direction: str) -> str:
    seat = _seat_row(db, seat_id)
    if seat is None:
        return "Jabatan itu tidak ditemukan."
    current = dict(seat)
    band = seat_display_band(current)
    if band == "pj":
        return "Penanggung jawab tidak bisa ditukar posisinya."
    key = seat_peer_key(current)
    siblings = [
        row
        for row in db.execute(
            "SELECT * FROM org_seats WHERE unit_id = ? ORDER BY sort_order, id",
            (seat["unit_id"],),
        )
        if seat_peer_key(dict(row)) == key
    ]
    if not _swap_order(db, "org_seats", siblings, seat_id, direction):
        return "Urutan tidak berubah. Geser hanya menukar jabatan yang sejenis di unit yang sama."
    pack_unit_seats(db, seat["unit_id"])
    _touch(db, seat["blueprint_id"])
    return "Urutan jabatan diperbarui."


def _swap_order(db, table: str, rows, item_id: int, direction: str) -> bool:
    ids = [row["id"] for row in rows]
    try:
        index = ids.index(item_id)
    except ValueError:
        return False
    target = index - 1 if direction == "up" else index + 1
    if target < 0 or target >= len(ids):
        return False
    left, right = rows[index], rows[target]
    db.execute(f"UPDATE {table} SET sort_order = ? WHERE id = ?", (right["sort_order"], left["id"]))
    db.execute(f"UPDATE {table} SET sort_order = ? WHERE id = ?", (left["sort_order"], right["id"]))
    return True


def next_tone(db, blueprint_id: int) -> str:
    used = {
        row["tone"]
        for row in db.execute(
            "SELECT tone FROM org_units WHERE blueprint_id = ? AND tone IS NOT NULL",
            (blueprint_id,),
        )
    }
    for index in range(1, 13):
        token = str(index)
        if token not in used:
            return token
    return "1"


def make_unit_code(title: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", fold(title).lower()).strip("_")[:40] or "unit"
    code = base
    serial = 2
    while code in taken:
        code = f"{base}_{serial}"
        serial += 1
    return code


def add_standard_unit(
    db,
    blueprint_id: int,
    *,
    title: str,
    unit_kind: str,
    lead_role: str,
) -> str:
    if unit_kind not in {"division", "wing"}:
        return "Jenis unit hanya divisi atau sayap."
    clean = fold(title)
    if not clean:
        return "Nama unit wajib diisi."
    taken = {row["code"] for row in db.execute("SELECT code FROM org_units WHERE blueprint_id = ?", (blueprint_id,))}
    taken.update(get_offices(db))
    code = make_unit_code(clean, taken)
    role = fold(lead_role) or ("Ketua" if unit_kind == "wing" else "Koordinator")
    max_order = db.execute(
        "SELECT IFNULL(MAX(sort_order), 0) FROM org_units WHERE blueprint_id = ? AND code != 'pj'",
        (blueprint_id,),
    ).fetchone()[0]
    unit_id = _add_unit(
        db,
        blueprint_id,
        code=code,
        unit_kind=unit_kind,
        title=clean,
        lead_role=role,
        tone=next_tone(db, blueprint_id),
        sort_order=int(max_order) + 1,
    )
    lead_code = create_office_def(
        db,
        code=code,
        label=f"{role} {clean}",
        short=clean,
        kind="lead",
        unit_code=code,
        aliases=[clean.lower(), f"{role.lower()} {clean.lower()}"],
    )
    sekbend_code = create_office_def(
        db,
        code=f"sekbend_{code}",
        label=f"Sekbend {clean}",
        short="Sekbend",
        kind="officer",
        unit_code=code,
        aliases=[f"sekbend {clean.lower()}", f"sekretaris bendahara {clean.lower()}"],
    )
    member_code = create_office_def(
        db,
        code=f"anggota_{code}",
        label=f"Anggota Divisi {clean}",
        short=f"Anggota {clean}",
        kind="member",
        unit_code=code,
        aliases=[f"anggota {clean.lower()}", f"anggota divisi {clean.lower()}"],
    )
    _add_seat(db, unit_id, lead_code, seat_kind="lead", sort_order=0)
    _add_seat(db, unit_id, sekbend_code, seat_kind="officer", sort_order=1)
    _add_seat(db, unit_id, member_code, seat_kind="member", sort_order=2)
    _touch(db, blueprint_id)
    return f"Unit {clean} ditambahkan, lengkap dengan sekbend dan anggota."


def create_office_def(
    db,
    *,
    code: str,
    label: str,
    short: str,
    kind: str,
    unit_code: Optional[str] = None,
    aliases: Optional[list[str]] = None,
) -> str:
    offices = get_offices(db)
    if code in offices:
        return code
    if not valid_office_code(code):
        raise ValueError("Kode jabatan tidak sah.")
    if kind not in {"core", "lead", "officer", "member", "pj"}:
        raise ValueError("Jenis jabatan tidak sah.")
    db.execute(
        """
        INSERT INTO kse_office_defs (
          code, label, short, kind, unit_code, needs_scope, unspecified,
          aliases, is_builtin, created_at
        ) VALUES (?, ?, ?, ?, ?, 0, 0, ?, 0, ?)
        """,
        (
            code,
            fold(label) or code,
            fold(short) or fold(label) or code,
            kind,
            unit_code,
            json.dumps([fold(item).lower() for item in (aliases or []) if fold(item)]),
            utcnow(),
        ),
    )
    invalidate_office_catalog()
    return code


def _resolve_parent_seat_id(db, unit_id: int, parent_seat_id: Optional[int], seat_kind: str) -> Optional[int]:
    if seat_kind != "member" or not parent_seat_id:
        return None
    parent = db.execute(
        "SELECT id, seat_kind FROM org_seats WHERE id = ? AND unit_id = ?",
        (parent_seat_id, unit_id),
    ).fetchone()
    if parent and parent["seat_kind"] == "coordinator":
        return int(parent["id"])
    return None


def _unit_has_lead(db, unit_id: int) -> bool:
    return bool(
        db.execute(
            "SELECT 1 FROM org_seats WHERE unit_id = ? AND seat_kind = 'lead'",
            (unit_id,),
        ).fetchone()
    )


def _add_team_member_seat(db, unit, coordinator_id: int, coordinator_label: str) -> None:
    taken = set(get_offices(db))
    taken.update(
        row["office_code"]
        for row in db.execute("SELECT office_code FROM org_seats WHERE unit_id = ?", (unit["id"],))
    )
    label = f"Anggota {coordinator_label}"
    code = suggest_office_code(
        label, unit["code"] if unit["code"] not in PROTECTED_UNITS else None
    )
    if not valid_office_code(code) or code in taken:
        serial = 2
        base = code if valid_office_code(code) else "anggota"
        while f"{base}_{serial}" in taken:
            serial += 1
        code = f"{base}_{serial}"
    create_office_def(
        db,
        code=code,
        label=label,
        short=label,
        kind="member",
        unit_code=None if unit["code"] in PROTECTED_UNITS else unit["code"],
        aliases=[label.lower()],
    )
    max_order = db.execute(
        "SELECT IFNULL(MAX(sort_order), 0) FROM org_seats WHERE unit_id = ?",
        (unit["id"],),
    ).fetchone()[0]
    _add_seat(
        db,
        unit["id"],
        code,
        seat_kind="member",
        sort_order=int(max_order) + 1,
        parent_seat_id=coordinator_id,
        label=label,
        short=label,
    )


def add_existing_seat(
    db,
    unit_id: int,
    office_code: str,
    seat_kind: Optional[str] = None,
    parent_seat_id: Optional[int] = None,
) -> str:
    unit = _unit_row(db, unit_id)
    if unit is None:
        return "Unit itu tidak ditemukan."
    meta = get_offices(db).get(office_code)
    if not meta:
        return "Jabatan itu tidak ada di katalog."
    exists = db.execute(
        "SELECT id FROM org_seats WHERE unit_id = ? AND office_code = ?",
        (unit_id, office_code),
    ).fetchone()
    if exists:
        return "Jabatan itu sudah ada di unit ini."
    kind = (seat_kind or "").strip() or _seat_kind_for(unit["unit_kind"], meta.get("kind") or "officer")
    if kind not in SEAT_KINDS:
        return "Jenis jabatan tidak sah."
    if unit["unit_kind"] not in BRANCH_UNIT_KINDS and kind == "coordinator":
        return "Koordinator hanya untuk divisi atau sayap."
    if kind == "lead" and unit["unit_kind"] in BRANCH_UNIT_KINDS and _unit_has_lead(db, unit_id):
        kind = "coordinator"
    parent = _resolve_parent_seat_id(db, unit_id, parent_seat_id, kind)
    max_order = db.execute(
        "SELECT IFNULL(MAX(sort_order), 0) FROM org_seats WHERE unit_id = ?",
        (unit_id,),
    ).fetchone()[0]
    pair_group = 1 if kind == "head" else 2 if kind == "officer" and unit["unit_kind"] == "core" else None
    seat_id = _add_seat(
        db,
        unit_id,
        office_code,
        seat_kind=kind,
        pair_group=pair_group,
        sort_order=int(max_order) + 1,
        parent_seat_id=parent,
    )
    if kind == "coordinator":
        _add_team_member_seat(db, unit, seat_id, meta.get("label") or office_code)
    pack_unit_seats(db, unit_id)
    _touch(db, unit["blueprint_id"])
    return "Jabatan ditambahkan ke bagan."


def add_custom_seat(
    db,
    unit_id: int,
    *,
    label: str,
    short: str,
    kind: str,
    parent_seat_id: Optional[int] = None,
) -> str:
    unit = _unit_row(db, unit_id)
    if unit is None:
        return "Unit itu tidak ditemukan."
    clean = fold(label)
    if not clean:
        return "Nama jabatan wajib diisi."
    if kind not in SEAT_KINDS:
        return "Jenis jabatan tidak sah."
    if unit["unit_kind"] not in BRANCH_UNIT_KINDS and kind == "coordinator":
        return "Koordinator hanya untuk divisi atau sayap."
    catalog_kind = "core" if kind == "head" else "lead" if kind == "coordinator" else kind
    taken = set(get_offices(db))
    code = suggest_office_code(short or clean, unit["code"] if unit["code"] not in PROTECTED_UNITS else None)
    if not valid_office_code(code) or code in taken:
        serial = 2
        base = code if valid_office_code(code) else "jabatan"
        while f"{base}_{serial}" in taken:
            serial += 1
        code = f"{base}_{serial}"
    create_office_def(
        db,
        code=code,
        label=clean,
        short=fold(short) or clean,
        kind=catalog_kind,
        unit_code=None if unit["code"] in PROTECTED_UNITS else unit["code"],
        aliases=[clean.lower(), fold(short).lower()] if short else [clean.lower()],
    )
    return add_existing_seat(db, unit_id, code, seat_kind=kind, parent_seat_id=parent_seat_id)


def _seat_kind_for(unit_kind: str, office_kind: str) -> str:
    if unit_kind == "core":
        return "head" if office_kind in {"core", "head"} else "officer"
    if unit_kind == "pj":
        return "pj"
    if office_kind == "member":
        return "member"
    if office_kind == "coordinator":
        return "coordinator"
    if office_kind == "lead":
        return "lead"
    return "officer"


def update_seat(db, seat_id: int, *, label: Optional[str] = None, short: Optional[str] = None) -> str:
    seat = _seat_row(db, seat_id)
    if seat is None:
        return "Jabatan itu tidak ditemukan."
    fields = []
    params: list[Any] = []
    if label is not None:
        clean = fold(label)
        if not clean:
            return "Nama jabatan wajib diisi."
        fields.append("label = ?")
        params.append(clean)
    if short is not None:
        clean_short = fold(short)
        if not clean_short:
            return "Nama singkat wajib diisi."
        fields.append("short = ?")
        params.append(clean_short)
    if not fields:
        return "Tidak ada yang diubah."
    params.append(seat_id)
    db.execute(f"UPDATE org_seats SET {', '.join(fields)} WHERE id = ?", params)
    _touch(db, seat["blueprint_id"])
    return "Label jabatan diperbarui."


def delete_seat(db, seat_id: int) -> str:
    seat = _seat_row(db, seat_id)
    if seat is None:
        return "Jabatan itu tidak ditemukan."
    if seat["office_code"] in PROTECTED_OFFICES:
        return "Jabatan inti dan penanggung jawab tidak boleh dilepas dari bagan."
    remaining = db.execute(
        "SELECT COUNT(*) FROM org_seats WHERE unit_id = ?",
        (seat["unit_id"],),
    ).fetchone()[0]
    if remaining <= 1:
        return "Unit tidak boleh kosong. Hapus unitnya jika memang tidak dipakai."
    was_coordinator = seat["seat_kind"] == "coordinator"
    child_count = db.execute(
        "SELECT COUNT(*) FROM org_seats WHERE parent_seat_id = ?",
        (seat_id,),
    ).fetchone()[0]
    db.execute("UPDATE org_seats SET parent_seat_id = NULL WHERE parent_seat_id = ?", (seat_id,))
    db.execute("DELETE FROM org_seats WHERE id = ?", (seat_id,))
    pack_unit_seats(db, seat["unit_id"])
    _touch(db, seat["blueprint_id"])
    if was_coordinator:
        if child_count:
            return (
                "Koordinator dilepas dari bagan. Anggotanya jadi anggota unit, "
                "tidak ikut terhapus. Catatan orang tidak ikut terhapus."
            )
        return "Koordinator dilepas dari bagan. Catatan orang tidak ikut terhapus."
    return "Jabatan dilepas dari bagan. Catatan orang tidak ikut terhapus."


def unused_offices_for_unit(db, unit_id: int) -> list[dict[str, Any]]:
    unit = _unit_row(db, unit_id)
    if unit is None:
        return []
    used = {
        row["office_code"]
        for row in db.execute("SELECT office_code FROM org_seats WHERE unit_id = ?", (unit_id,))
    }
    items = []
    for code, meta in get_offices(db).items():
        if code in used or meta.get("unspecified"):
            continue
        items.append({"code": code, **meta})
    items.sort(key=lambda item: (item.get("rank", 999), item["code"]))
    return items


def _faculty_scope_label(scope: Optional[str]) -> str:
    if not scope:
        return "Fakultas belum tercatat"
    return FACULTIES.get(scope, scope)


def _filled_seat(seats: dict[str, dict], spec: dict[str, Any]) -> dict[str, Any]:
    code = spec["office_code"]
    base = seats.get(code) or {
        "code": code,
        "people": [],
        "label": spec.get("label") or code,
        "short": spec.get("short") or code,
        "rank": 999,
        "kind": spec.get("seat_kind"),
    }
    return {
        **base,
        "id": spec.get("id"),
        "parent_seat_id": spec.get("parent_seat_id"),
        "code": code,
        "label": spec.get("label") or base.get("label"),
        "short": spec.get("short") or base.get("short"),
        "seat_kind": spec.get("seat_kind"),
        "pair_group": spec.get("pair_group"),
        "people": list(base.get("people") or []),
    }


def tree_from_layout(seats: dict[str, dict], layout: dict[str, Any]) -> dict[str, Any]:
    used: set[str] = set()
    heads: list[dict] = []
    officers: list[dict] = []
    core_extra: list[dict] = []
    divisions: list[dict] = []
    wings: list[dict] = []
    pj_universitas = seats.get("pj_universitas") or {
        "code": "pj_universitas",
        "label": "Penanggung Jawab Universitas",
        "short": "PJ Universitas",
        "people": [],
    }
    pj_faculty = seats.get("pj_fakultas") or {
        "code": "pj_fakultas",
        "label": "Penanggung Jawab Fakultas",
        "short": "PJ Fakultas",
        "people": [],
    }

    for unit in layout.get("units") or []:
        specs = unit.get("seats") or []
        if not unit.get("is_visible", 1):
            continue
        filled = [_filled_seat(seats, spec) for spec in specs]
        for spec in specs:
            used.add(spec["office_code"])
        kind = unit.get("unit_kind")
        if kind == "core":
            for seat in filled:
                if seat.get("pair_group") == 1 or seat.get("seat_kind") == "head":
                    heads.append(seat)
                elif seat.get("pair_group") == 2:
                    officers.append(seat)
                else:
                    core_extra.append(seat)
            continue
        if kind == "pj":
            for seat in filled:
                if seat["code"] == "pj_universitas":
                    pj_universitas = seat
                elif seat["code"] == "pj_fakultas":
                    pj_faculty = seat
            continue
        leads = [seat for seat in filled if seat.get("seat_kind") == "lead"]
        lead = leads[0] if leads else None
        extra_leads = leads[1:]
        coordinators = extra_leads + [seat for seat in filled if seat.get("seat_kind") == "coordinator"]
        unit_officers = [seat for seat in filled if seat.get("seat_kind") == "officer"]
        member_seats = [seat for seat in filled if seat.get("seat_kind") == "member"]
        coord_ids = {seat.get("id") for seat in coordinators if seat.get("id") is not None}
        teams = []
        for coord in coordinators:
            kids = [item for item in member_seats if item.get("parent_seat_id") == coord.get("id")]
            people: list[dict] = []
            for kid in kids:
                people.extend(kid.get("people") or [])
            teams.append(
                {
                    "coordinator": coord,
                    "members": people,
                    "member_label": (
                        kids[0].get("label")
                        if kids
                        else f"Anggota {coord.get('short') or coord.get('label')}"
                    ),
                }
            )
        members: list[dict] = []
        ungrouped_seats = []
        for member_seat in member_seats:
            if member_seat.get("parent_seat_id") in coord_ids:
                continue
            ungrouped_seats.append(member_seat)
            members.extend(member_seat.get("people") or [])
        block = {
            "code": unit["code"],
            "title": unit["title"],
            "lead_role": unit.get("lead_role") or "Koordinator",
            "tone": unit.get("tone") or "1",
            "unit_kind": kind,
            "lead": lead,
            "officers": unit_officers,
            "teams": teams,
            "members": members,
            "member_seat": ungrouped_seats[0] if ungrouped_seats else {"people": [], "label": "Anggota"},
        }
        if kind == "wing":
            wings.append(block)
        else:
            divisions.append(block)

    unspecified = seats.get("anggota_divisi")
    by_scope: dict[str, list] = {}
    for person in pj_faculty.get("people") or []:
        by_scope.setdefault(person.get("scope") or "", []).append(person)
    pj_faculty_groups = [
        {
            "scope": scope or None,
            "label": _faculty_scope_label(scope or None),
            "people": people,
        }
        for scope, people in sorted(
            by_scope.items(),
            key=lambda item: (_faculty_scope_label(item[0] or None), item[0]),
        )
    ]
    outside = []
    for code, seat in seats.items():
        if not seat.get("people"):
            continue
        if code in used or code == "anggota_divisi":
            continue
        outside.append(seat)
    outside.sort(key=lambda item: (item.get("rank", 999), item["code"]))
    return {
        "heads": heads,
        "officers": officers,
        "core_extra": core_extra,
        "divisions": divisions,
        "wings": wings,
        "unspecified": unspecified if unspecified and unspecified.get("people") else None,
        "outside": outside,
        "pj_universitas": pj_universitas,
        "pj_fakultas": pj_faculty,
        "pj_faculty_groups": pj_faculty_groups,
    }
