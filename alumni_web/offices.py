"""Jabatan paguyuban KSE UNAND.

Katalog kode jabatan stabil. Bagan per periode bisa menyesuaikan template
tanpa membuat ulang: divisi biasa, sayap (misalnya Comdev terpisah), plus
jabatan tambahan seperti sekbend. Kode lama `anggota_divisi` tetap sah.

Satu baris = satu periode kepengurusan. Status jabatan menempel ke periode
itu, bukan ke orang secara permanen.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Optional

from .catalog import FACULTIES, FACULTY_ALIASES
from .db import utcnow
from .normalize import fold, parse_year

# Divisi resmi. Anggota punya kode sendiri; `anggota_divisi` lama tetap sah.
KSE_DIVISIONS: tuple[dict[str, Any], ...] = (
    {
        "code": "community_development",
        "title": "Community Development",
        "lead": "community_development",
        "member": "anggota_community_development",
        "lead_role": "Ketua",
        "tone": "1",
        "extra_officers": ("mnb_community_development",),
        "member_aliases": (
            "anggota community development",
            "anggota divisi community development",
            "anggota divisi cd",
            "anggota kadiv cd",
            "anggota cd",
            "staf cd",
            "staff cd",
        ),
    },
    {
        "code": "humas",
        "title": "Hubungan Masyarakat",
        "lead": "humas",
        "member": "anggota_humas",
        "lead_role": "Koordinator",
        "tone": "2",
        "member_aliases": (
            "anggota hubungan masyarakat",
            "anggota divisi hubungan masyarakat",
            "anggota divisi humas",
            "anggota kadiv humas",
            "anggota humas",
            "staf humas",
            "staff humas",
        ),
    },
    {
        "code": "humaniora",
        "title": "Humaniora",
        "lead": "humaniora",
        "member": "anggota_humaniora",
        "lead_role": "Koordinator",
        "tone": "3",
        "member_aliases": (
            "anggota humaniora",
            "anggota divisi humaniora",
            "anggota kadiv humaniora",
            "staf humaniora",
            "staff humaniora",
        ),
    },
    {
        "code": "pengabdian",
        "title": "Pengabdian Masyarakat",
        "lead": "pengabdian",
        "member": "anggota_pengabdian",
        "lead_role": "Koordinator",
        "tone": "4",
        "member_aliases": (
            "anggota pengabdian masyarakat",
            "anggota divisi pengabdian",
            "anggota divisi pengmas",
            "anggota pengmas",
            "anggota pengabdian",
            "staf pengabdian",
            "staff pengabdian",
        ),
    },
    {
        "code": "rumah_anak_cerdas",
        "title": "Rumah Anak Cerdas",
        "lead": "rumah_anak_cerdas",
        "member": "anggota_rumah_anak_cerdas",
        "lead_role": "Koordinator",
        "tone": "5",
        "member_aliases": (
            "anggota rumah anak cerdas",
            "anggota divisi rac",
            "anggota rac",
            "staf rac",
            "staff rac",
        ),
    },
    {
        "code": "pendidikan",
        "title": "Pendidikan",
        "lead": "pendidikan",
        "member": "anggota_pendidikan",
        "lead_role": "Koordinator",
        "tone": "6",
        "member_aliases": (
            "anggota pendidikan",
            "anggota divisi pendidikan",
            "anggota kadiv pendidikan",
            "staf pendidikan",
            "staff pendidikan",
        ),
    },
    {
        "code": "kestari",
        "title": "Kestari",
        "lead": "kestari",
        "member": "anggota_kestari",
        "lead_role": "Koordinator",
        "tone": "7",
        "member_aliases": (
            "anggota kestari",
            "anggota kesekretariatan",
            "anggota divisi kestari",
            "staf kestari",
            "staff kestari",
        ),
    },
    {
        "code": "kewirausahaan",
        "title": "Kewirausahaan",
        "lead": "kewirausahaan",
        "member": "anggota_kewirausahaan",
        "lead_role": "Koordinator",
        "tone": "8",
        "member_aliases": (
            "anggota kewirausahaan",
            "anggota divisi kewirausahaan",
            "anggota divisi kwu",
            "anggota kwu",
            "staf kewirausahaan",
            "staff kewirausahaan",
        ),
    },
)

# urutan = tampilan bagan. rank lebih kecil = lebih tinggi.
KSE_OFFICES: dict[str, dict[str, Any]] = {
    "ketua": {
        "label": "Ketua Paguyuban",
        "short": "Ketua",
        "branch": "inti",
        "rank": 10,
        "kind": "core",
    },
    "wakil_ketua": {
        "label": "Wakil Ketua",
        "short": "Wakil Ketua",
        "branch": "inti",
        "rank": 20,
        "kind": "core",
    },
    "sekretaris": {
        "label": "Sekretaris",
        "short": "Sekretaris",
        "branch": "inti",
        "rank": 30,
        "kind": "core",
    },
    "bendahara": {
        "label": "Bendahara",
        "short": "Bendahara",
        "branch": "inti",
        "rank": 40,
        "kind": "core",
    },
    "community_development": {
        "label": "Ketua Community Development",
        "short": "Community Development",
        "branch": "divisi",
        "rank": 50,
        "kind": "lead",
        "unit": "community_development",
        "tone": "1",
    },
    "mnb_community_development": {
        "label": "MnB Community Development",
        "short": "MnB",
        "branch": "divisi",
        "rank": 52,
        "kind": "officer",
        "unit": "community_development",
        "tone": "1",
    },
    "humas": {
        "label": "Koordinator Hubungan Masyarakat",
        "short": "Humas",
        "branch": "divisi",
        "rank": 60,
        "kind": "lead",
        "unit": "humas",
        "tone": "2",
    },
    "humaniora": {
        "label": "Koordinator Humaniora",
        "short": "Humaniora",
        "branch": "divisi",
        "rank": 70,
        "kind": "lead",
        "unit": "humaniora",
        "tone": "3",
    },
    "pengabdian": {
        "label": "Koordinator Pengabdian Masyarakat",
        "short": "Pengabdian Masyarakat",
        "branch": "divisi",
        "rank": 80,
        "kind": "lead",
        "unit": "pengabdian",
        "tone": "4",
    },
    "rumah_anak_cerdas": {
        "label": "Koordinator Rumah Anak Cerdas",
        "short": "Rumah Anak Cerdas",
        "branch": "divisi",
        "rank": 90,
        "kind": "lead",
        "unit": "rumah_anak_cerdas",
        "tone": "5",
    },
    "pendidikan": {
        "label": "Koordinator Pendidikan",
        "short": "Pendidikan",
        "branch": "divisi",
        "rank": 100,
        "kind": "lead",
        "unit": "pendidikan",
        "tone": "6",
    },
    "kestari": {
        "label": "Koordinator Kestari",
        "short": "Kestari",
        "branch": "divisi",
        "rank": 110,
        "kind": "lead",
        "unit": "kestari",
        "tone": "7",
    },
    "kewirausahaan": {
        "label": "Koordinator Kewirausahaan",
        "short": "Kewirausahaan",
        "branch": "divisi",
        "rank": 120,
        "kind": "lead",
        "unit": "kewirausahaan",
        "tone": "8",
    },
    "anggota_divisi": {
        "label": "Anggota Divisi (belum spesifik)",
        "short": "Anggota Divisi",
        "branch": "divisi",
        "rank": 199,
        "kind": "member",
        "unit": None,
        "unspecified": True,
    },
    "pj_universitas": {
        "label": "Penanggung Jawab Universitas",
        "short": "PJ Universitas",
        "branch": "pj",
        "rank": 200,
        "kind": "pj",
    },
    "pj_fakultas": {
        "label": "Penanggung Jawab Fakultas",
        "short": "PJ Fakultas",
        "branch": "pj",
        "rank": 210,
        "kind": "pj",
        "needs_scope": True,
    },
}

KSE_BRANCHES = (
    ("inti", "Pengurus inti"),
    ("divisi", "Divisi"),
    ("pj", "Penanggung jawab"),
)

KSE_OFFICE_GROUPS = (
    ("core", "Pengurus inti"),
    ("lead", "Koordinator divisi"),
    ("member", "Anggota divisi"),
    ("pj", "Penanggung jawab"),
)

KSE_FORM_GROUPS = (
    ("core", "Pengurus inti"),
    ("lead", "Koordinator / ketua unit"),
    ("officer", "Sekbend dan pengurus unit"),
    ("member", "Anggota divisi"),
    ("pj", "Penanggung jawab"),
)

# Frasa panjang dulu supaya "wakil ketua" tidak jadi "ketua".
KSE_OFFICE_ALIASES: dict[str, str] = {
    "ketua paguyuban": "ketua",
    "ketua umum": "ketua",
    "ketua kse": "ketua",
    "chairman": "ketua",
    "ketua": "ketua",
    "wakil ketua paguyuban": "wakil_ketua",
    "wakil ketua": "wakil_ketua",
    "wkt": "wakil_ketua",
    "wakil": "wakil_ketua",
    "sekretaris jenderal": "sekretaris",
    "sekretaris": "sekretaris",
    "sekjen": "sekretaris",
    "bendahara": "bendahara",
    "ketua humas": "humas",
    "wakil humas": "humas",
    "wakil ketua humas": "humas",
    "ketua community development": "community_development",
    "ketua comdev": "community_development",
    "ketua komdev": "community_development",
    "ketua cd": "community_development",
    "wakil comdev": "community_development",
    "wakil community development": "community_development",
    "koordinator community development": "community_development",
    "community development": "community_development",
    "kadiv cd": "community_development",
    "komdev": "community_development",
    "mnb community development": "mnb_community_development",
    "mnb comdev": "mnb_community_development",
    "mnb cd": "mnb_community_development",
    "mnb": "mnb_community_development",
    "koordinator hubungan masyarakat": "humas",
    "ketua hubungan masyarakat": "humas",
    "kadiv humas": "humas",
    "koordinator humas": "humas",
    "hubungan masyarakat": "humas",
    "humas": "humas",
    "koordinator humaniora": "humaniora",
    "kadiv humaniora": "humaniora",
    "humaniora": "humaniora",
    "koordinator pengabdian masyarakat": "pengabdian",
    "pengabdian masyarakat": "pengabdian",
    "pengmas": "pengabdian",
    "pengabdian": "pengabdian",
    "koordinator rumah anak cerdas": "rumah_anak_cerdas",
    "rumah anak cerdas": "rumah_anak_cerdas",
    "rac": "rumah_anak_cerdas",
    "koordinator pendidikan": "pendidikan",
    "kadiv pendidikan": "pendidikan",
    "pendidikan": "pendidikan",
    "koordinator kestari": "kestari",
    "kesekretariatan": "kestari",
    "kestari": "kestari",
    "koordinator kewirausahaan": "kewirausahaan",
    "kewirausahaan": "kewirausahaan",
    "kwu": "kewirausahaan",
    "anggota divisi": "anggota_divisi",
    "staff divisi": "anggota_divisi",
    "staf divisi": "anggota_divisi",
    "anggota": "anggota_divisi",
    "penanggung jawab universitas": "pj_universitas",
    "pj universitas": "pj_universitas",
    "pj univ": "pj_universitas",
    "penanggung jawab fakultas": "pj_fakultas",
    "pj fakultas": "pj_fakultas",
}


def _register_division_offices() -> None:
    """Sekbend dan anggota per divisi. `anggota_divisi` generik tidak dihapus."""
    for unit in KSE_DIVISIONS:
        lead = KSE_OFFICES[unit["lead"]]
        sekbend_code = f"sekbend_{unit['code']}"
        unit["sekbend"] = sekbend_code
        extra_n = len(unit.get("extra_officers") or ())
        KSE_OFFICES[sekbend_code] = {
            "label": f"Sekbend {unit['title']}",
            "short": "Sekbend",
            "branch": "divisi",
            "rank": int(lead["rank"]) + 1,
            "kind": "officer",
            "unit": unit["code"],
            "tone": unit["tone"],
        }
        for alias in (
            f"sekbend {unit['title'].lower()}",
            f"sekbend divisi {unit['title'].lower()}",
            f"sekbend {lead['short'].lower()}",
            f"sekretaris bendahara {unit['title'].lower()}",
            f"sekretaris/bendahara {unit['title'].lower()}",
            f"sekretaris-bendahara {unit['title'].lower()}",
            f"sekretaris bendahara divisi {unit['title'].lower()}",
            f"sekretaris/bendahara divisi {unit['title'].lower()}",
            f"sekretaris/bendahara divisi {lead['short'].lower()}",
            f"sekretaris/bendahara {lead['short'].lower()}",
        ):
            KSE_OFFICE_ALIASES.setdefault(alias, sekbend_code)
        KSE_OFFICES[unit["member"]] = {
            "label": f"Anggota Divisi {unit['title']}",
            "short": f"Anggota {unit['title']}",
            "branch": "divisi",
            "rank": int(lead["rank"]) + 2 + extra_n,
            "kind": "member",
            "unit": unit["code"],
            "tone": unit["tone"],
        }
        extras = (
            f"staff divisi {unit['title'].lower()}",
            f"staf divisi {unit['title'].lower()}",
            f"staff divisi {lead['short'].lower()}",
            f"staf divisi {lead['short'].lower()}",
            f"anggota divisi {lead['short'].lower()}",
        )
        for alias in (*unit["member_aliases"], *extras):
            KSE_OFFICE_ALIASES.setdefault(alias, unit["member"])


_register_division_offices()

_PERIOD_RE = re.compile(
    r"(19|20)\d{2}(?:\s*[/\-–]\s*(?:(?:19|20)?\d{2}))?"
)
_ALIAS_KEYS = sorted(KSE_OFFICE_ALIASES, key=len, reverse=True)
_FACULTY_KEYS = sorted(
    list(FACULTY_ALIASES.keys()) + [label.lower() for label in FACULTIES.values()],
    key=len,
    reverse=True,
)
_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,47}$")


def _branch_for_kind(kind: str) -> str:
    if kind == "core":
        return "inti"
    if kind == "pj":
        return "pj"
    return "divisi"


def invalidate_office_catalog() -> None:
    try:
        from flask import g, has_app_context

        if has_app_context():
            g.pop("office_catalog", None)
            g.pop("office_aliases", None)
    except Exception:
        pass


def _custom_offices(db) -> dict[str, dict[str, Any]]:
    try:
        rows = db.execute(
            """
            SELECT code, label, short, kind, unit_code, needs_scope,
                   unspecified, aliases
            FROM kse_office_defs
            ORDER BY code
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    extras: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if row["code"] in KSE_OFFICES:
            continue
        try:
            aliases = json.loads(row["aliases"] or "[]")
        except json.JSONDecodeError:
            aliases = []
        if not isinstance(aliases, list):
            aliases = []
        extras[row["code"]] = {
            "label": row["label"],
            "short": row["short"],
            "branch": _branch_for_kind(row["kind"]),
            "rank": 180 + index * 3,
            "kind": row["kind"],
            "unit": row["unit_code"],
            "needs_scope": bool(row["needs_scope"]),
            "unspecified": bool(row["unspecified"]),
            "aliases": tuple(str(item) for item in aliases if item),
            "custom": True,
        }
    return extras


def get_offices(db=None) -> dict[str, dict[str, Any]]:
    catalog = {code: dict(meta) for code, meta in KSE_OFFICES.items()}
    if db is None:
        try:
            from flask import g, has_app_context

            from .db import get_db

            if has_app_context():
                cached = g.get("office_catalog")
                if cached is not None:
                    return cached
                db = get_db()
            else:
                return catalog
        except Exception:
            return catalog
    catalog.update(_custom_offices(db))
    try:
        from flask import g, has_app_context

        if has_app_context():
            g.office_catalog = catalog
    except Exception:
        pass
    return catalog


def known_office(code: Optional[str], db=None) -> bool:
    return bool(code) and code in get_offices(db)


def office_meta(code: Optional[str], db=None) -> dict[str, Any]:
    return get_offices(db).get(code or "") or {}


def stats_kind(code: Optional[str], db=None) -> str:
    kind = office_meta(code, db).get("kind")
    if kind == "officer":
        return "lead"
    if kind in {"core", "lead", "member", "pj"}:
        return kind
    return "member"


def alias_map(db=None) -> dict[str, str]:
    try:
        from flask import g, has_app_context

        if db is None and has_app_context():
            cached = g.get("office_aliases")
            if cached is not None:
                return cached
    except Exception:
        pass
    aliases = dict(KSE_OFFICE_ALIASES)
    for code, meta in get_offices(db).items():
        if not meta.get("custom"):
            continue
        label = fold(meta.get("label")).lower()
        if label:
            aliases.setdefault(label, code)
        for extra in meta.get("aliases") or ():
            key = fold(extra).lower()
            if key:
                aliases.setdefault(key, code)
    try:
        from flask import g, has_app_context

        if has_app_context():
            g.office_aliases = aliases
    except Exception:
        pass
    return aliases


def suggest_office_code(label: str, unit_code: Optional[str] = None) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", fold(label).lower()).strip("_")[:32] or "jabatan"
    if unit_code and not base.endswith(unit_code):
        trimmed = base[: max(8, 47 - len(unit_code) - 1)]
        return f"{trimmed}_{unit_code}"[:48]
    return base[:48]


def valid_office_code(code: str) -> bool:
    return bool(_CODE_RE.match(code or ""))


def office_label(code: Optional[str], scope: Optional[str] = None, db=None) -> str:
    meta = office_meta(code, db)
    if not meta:
        return code or "—"
    if code == "pj_fakultas" and scope:
        faculty = FACULTIES.get(scope, scope)
        return f"{meta['label']} {faculty}"
    return meta["label"]


def office_short(code: Optional[str], db=None) -> str:
    meta = office_meta(code, db)
    return meta["short"] if meta else (code or "—")


def format_period(start: Optional[int], end: Optional[int]) -> str:
    if start and end and end != start:
        return f"{start}/{end}"
    if start:
        return f"{start}/{start + 1}"
    return ""


def term_years(
    start: Optional[int], end: Optional[int]
) -> list[tuple[Optional[int], Optional[int]]]:
    """Pecah rentang jadi tahun kepengurusan. 2022–2025 → 2022/23, 2023/24, 2024/25."""
    if not start:
        return [(None, end)]
    last = end if end and end > start else start + 1
    return [(year, year + 1) for year in range(start, last)]


def expand_role_entry(entry: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for start, end in term_years(entry.get("period_start"), entry.get("period_end")):
        row = dict(entry)
        row["period_start"] = start
        row["period_end"] = end
        if start:
            row["period_raw"] = format_period(start, end)
        rows.append(row)
    return rows


def parse_period(text: Optional[str]) -> tuple[Optional[int], Optional[int], Optional[str]]:
    raw = fold(text)
    if not raw:
        return None, None, None
    match = _PERIOD_RE.search(raw)
    if not match:
        year, leftover = parse_year(raw)
        return year, (year + 1 if year else None), leftover
    token = re.sub(r"\s+", "", match.group(0))
    years = re.findall(r"(?:19|20)\d{2}", token)
    if len(years) == 1 and "/" in token:
        first = int(years[0])
        tail = token.split("/")[-1]
        if len(tail) == 2 and tail.isdigit():
            century = first // 100 * 100
            second = century + int(tail)
            if second < first:
                second += 100
            return first, second, raw
        if len(tail) == 4 and tail.isdigit():
            return first, int(tail), raw
        return first, first + 1, raw
    if len(years) >= 2:
        a, b = int(years[0]), int(years[1])
        if b < a:
            a, b = b, a
        return a, b, raw
    if years:
        start = int(years[0])
        return start, start + 1, raw
    return None, None, raw


def _faculty_in(text: str) -> Optional[str]:
    low = text.lower()
    for key in _FACULTY_KEYS:
        if key in low:
            if key in FACULTY_ALIASES:
                return FACULTY_ALIASES[key]
            for code, label in FACULTIES.items():
                if label.lower() == key:
                    return code
    return None


def parse_office_text(
    text: Optional[str], db=None
) -> tuple[Optional[str], Optional[str]]:
    low = fold(text).lower()
    if not low:
        return None, None
    aliases = alias_map(db)
    for alias in sorted(aliases, key=len, reverse=True):
        if alias in low:
            code = aliases[alias]
            needs_scope = office_meta(code, db).get("needs_scope") or code == "pj_fakultas"
            scope = _faculty_in(low) if needs_scope else None
            return code, scope
    if "pj" in low and _faculty_in(low):
        return "pj_fakultas", _faculty_in(low)
    return None, None


def parse_role_entries(text: Optional[str], db=None) -> list[dict[str, Any]]:
    """Urai isian bebas: 'Ketua 2023/2024; Humas 2022/2023'."""
    blob = fold(text)
    if not blob:
        return []
    chunks = re.split(r"[;|]+", blob)
    if len(chunks) == 1 and "," in blob and _PERIOD_RE.search(blob):
        chunks = re.split(
            r",(?=\s*(?:ketua|wakil|sekretaris|bendahara|koordinator|sekbend|mnb|pj|humas|kadiv|anggota))",
            blob,
            flags=re.I,
        )
    entries = []
    seen = set()
    for chunk in chunks:
        piece = fold(chunk)
        if not piece:
            continue
        code, scope = parse_office_text(piece, db)
        if not code:
            continue
        start, end, period_raw = parse_period(piece)
        if end is None and start:
            end = start + 1
        key = (code, start or 0, end or 0, scope or "")
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            {
                "office_code": code,
                "period_start": start,
                "period_end": end,
                "period_raw": period_raw,
                "scope": scope,
                "title_raw": piece,
            }
        )
    return entries


def insert_role(db, alumni_id: int, entry: dict[str, Any]) -> bool:
    code = entry.get("office_code")
    if not known_office(code, db):
        return False
    start = entry.get("period_start")
    scope = entry.get("scope") or None
    existing = db.execute(
        """
        SELECT id FROM alumni_kse_roles
        WHERE alumni_id = ? AND office_code = ?
          AND IFNULL(period_start, 0) = IFNULL(?, 0)
          AND IFNULL(scope, '') = IFNULL(?, '')
        """,
        (alumni_id, code, start, scope),
    ).fetchone()
    if existing:
        return False
    db.execute(
        """
        INSERT INTO alumni_kse_roles (
          alumni_id, office_code, period_start, period_end, period_raw,
          scope, title_raw, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            alumni_id,
            code,
            start,
            entry.get("period_end"),
            entry.get("period_raw"),
            scope,
            fold(entry.get("title_raw")) or None,
            utcnow(),
        ),
    )
    return True


def add_roles(db, alumni_id: int, entry: dict[str, Any]) -> int:
    """Tambah jabatan; rentang lebih dari satu tahun dipecah per periode.

    Tahun yang baru punya riwayat dibekukan ke salinan template saat itu, supaya
    menyunting template kemudian tidak mengubah bagan yang baru saja muncul.
    """
    from .org_layout import capture_appeared_year

    added = 0
    for term in expand_role_entry(entry):
        if insert_role(db, alumni_id, term):
            added += 1
            capture_appeared_year(db, term.get("period_start"))
    return added


def apply_roles_text(db, alumni_id: int, text: Optional[str]) -> int:
    added = 0
    for entry in parse_role_entries(text, db=db):
        added += add_roles(db, alumni_id, entry)
    return added


def split_wide_role_rows(db) -> int:
    """Pecah baris lama yang menyimpan rentang >1 periode jadi satu baris per tahun."""
    rows = db.execute(
        """
        SELECT * FROM alumni_kse_roles
        WHERE period_start IS NOT NULL
          AND period_end IS NOT NULL
          AND period_end > period_start + 1
        """
    ).fetchall()
    split = 0
    for row in rows:
        payload = {
            "office_code": row["office_code"],
            "period_start": row["period_start"],
            "period_end": row["period_end"],
            "period_raw": row["period_raw"],
            "scope": row["scope"],
            "title_raw": row["title_raw"],
        }
        db.execute("DELETE FROM alumni_kse_roles WHERE id = ?", (row["id"],))
        split += add_roles(db, row["alumni_id"], payload)
    return split


def delete_role(db, role_id: int, alumni_id: int) -> bool:
    cur = db.execute(
        "DELETE FROM alumni_kse_roles WHERE id = ? AND alumni_id = ?",
        (role_id, alumni_id),
    )
    return cur.rowcount > 0


def list_roles(db, alumni_id: int) -> list:
    rows = [
        dict(row)
        for row in db.execute(
            "SELECT * FROM alumni_kse_roles WHERE alumni_id = ?",
            (alumni_id,),
        ).fetchall()
    ]
    offices = get_offices(db)
    rows.sort(
        key=lambda row: (
            -(row["period_start"] or 0),
            (offices.get(row["office_code"]) or {}).get("rank", 999),
            -(row["id"] or 0),
        )
    )
    return rows


def group_roles_by_term(roles) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for role in roles:
        item = dict(role)
        key = (item.get("period_start"), item.get("period_end"))
        if groups and (groups[-1]["period_start"], groups[-1]["period_end"]) == key:
            groups[-1]["roles"].append(item)
            continue
        groups.append(
            {
                "period_start": item.get("period_start"),
                "period_end": item.get("period_end"),
                "period_label": format_period(
                    item.get("period_start"), item.get("period_end")
                )
                or "Periode belum terdata",
                "roles": [item],
            }
        )
    return groups


def decorate_alumni_rows(db, rows) -> list[dict[str, Any]]:
    """Lampirkan jabatan periode terbaru ke kartu direktori/beranda."""
    items = [dict(row) for row in rows]
    tops = top_offices_for(db, [item["id"] for item in items if item.get("id")])
    for item in items:
        top = tops.get(item["id"])
        if not top:
            item["office_label"] = None
            item["office_period"] = None
            continue
        item["office_label"] = office_label(top["office_code"], top["scope"], db)
        item["office_period"] = format_period(top["period_start"], top["period_end"])
    return items


def top_offices_for(db, alumni_ids: list[int]) -> dict[int, dict]:
    if not alumni_ids:
        return {}
    placeholders = ",".join("?" for _ in alumni_ids)
    rows = db.execute(
        f"""
        SELECT alumni_id, office_code, period_start, period_end, scope
        FROM alumni_kse_roles
        WHERE alumni_id IN ({placeholders})
        """,
        alumni_ids,
    ).fetchall()
    offices = get_offices(db)
    best: dict[int, dict] = {}
    for row in rows:
        meta = offices.get(row["office_code"]) or {"rank": 999}
        current = best.get(row["alumni_id"])
        # Periode terbaru dulu; jika satu tahun dua kursi, ambil yang lebih tinggi.
        score = (-(row["period_start"] or 0), meta["rank"])
        if current is None or score < current["_score"]:
            best[row["alumni_id"]] = {
                "office_code": row["office_code"],
                "period_start": row["period_start"],
                "period_end": row["period_end"],
                "scope": row["scope"],
                "_score": score,
            }
    for item in best.values():
        item.pop("_score", None)
    return best


def role_periods(db) -> list[int]:
    years: set[int] = set()
    rows = db.execute(
        """
        SELECT period_start, period_end FROM alumni_kse_roles
        WHERE period_start IS NOT NULL
        """
    ).fetchall()
    for row in rows:
        for start, _end in term_years(row["period_start"], row["period_end"]):
            if start:
                years.add(start)
    return sorted(years, reverse=True)


def office_groups(db=None) -> list[dict[str, Any]]:
    """Kelompok opsi formulir: inti, koordinator, sekbend, anggota, PJ."""
    offices = get_offices(db)
    groups = []
    for key, title in KSE_FORM_GROUPS:
        items = [
            {"code": code, **meta}
            for code, meta in offices.items()
            if meta.get("kind") == key
        ]
        items.sort(
            key=lambda item: (
                1 if item.get("unspecified") else 0,
                item.get("rank", 999),
                item["code"],
            )
        )
        groups.append({"key": key, "title": title, "offices": items})
    return groups


def org_seats(period_start: Optional[int] = None, db=None) -> list[dict]:
    seats = []
    for code, meta in get_offices(db).items():
        seats.append({"code": code, **meta, "people": []})
    return seats


def _faculty_scope_label(scope: Optional[str]) -> str:
    if not scope:
        return "Fakultas belum tercatat"
    return FACULTIES.get(scope, scope)


def build_org_tree(seats: dict[str, dict], layout: Optional[dict] = None) -> dict[str, Any]:
    if layout and layout.get("units"):
        from .org_layout import tree_from_layout

        return tree_from_layout(seats, layout)
    divisions = []
    for unit in KSE_DIVISIONS:
        member_seat = seats[unit["member"]]
        officers = []
        sekbend = seats.get(unit.get("sekbend") or "")
        if sekbend:
            officers.append(sekbend)
        divisions.append(
            {
                "code": unit["code"],
                "title": unit["title"],
                "lead_role": unit["lead_role"],
                "tone": unit["tone"],
                "unit_kind": "division",
                "lead": seats[unit["lead"]],
                "officers": officers,
                "teams": [],
                "members": member_seat["people"],
                "member_seat": member_seat,
            }
        )
    unspecified = seats.get("anggota_divisi")
    pj_faculty = seats["pj_fakultas"]
    by_scope: dict[str, list] = {}
    for person in pj_faculty["people"]:
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
    return {
        "heads": [seats["ketua"], seats["wakil_ketua"]],
        "officers": [seats["sekretaris"], seats["bendahara"]],
        "core_extra": [],
        "divisions": divisions,
        "wings": [],
        "unspecified": unspecified if unspecified and unspecified["people"] else None,
        "outside": [],
        "pj_universitas": seats["pj_universitas"],
        "pj_fakultas": pj_faculty,
        "pj_faculty_groups": pj_faculty_groups,
    }


def build_org_chart(db, period_start: Optional[int] = None) -> dict:
    from .org_layout import resolve_layout

    layout = resolve_layout(db, period_start)
    seats = {s["code"]: s for s in org_seats(period_start, db=db)}
    params: list = []
    where = ["a.is_listed = 1"]
    if period_start:
        where.append(
            "r.period_start IS NOT NULL AND r.period_start <= ? "
            "AND IFNULL(r.period_end, r.period_start + 1) > ?"
        )
        params.extend([period_start, period_start])
    rows = db.execute(
        f"""
        SELECT r.office_code, r.scope, r.period_start, r.period_end,
               a.id, a.full_name, a.faculty_code, a.cohort_year, a.major_normalized
        FROM alumni_kse_roles r
        JOIN alumni a ON a.id = r.alumni_id
        WHERE {' AND '.join(where)}
        ORDER BY r.period_start IS NULL, r.period_start,
                 r.period_end IS NULL, r.period_end,
                 a.full_name COLLATE NOCASE
        """,
        params,
    ).fetchall()
    for row in rows:
        seat = seats.get(row["office_code"])
        if not seat:
            seats[row["office_code"]] = {
                "code": row["office_code"],
                "label": office_label(row["office_code"], db=db),
                "short": office_short(row["office_code"], db=db),
                "branch": "divisi",
                "rank": 400,
                "kind": "member",
                "people": [],
            }
            seat = seats[row["office_code"]]
        seat["people"].append(dict(row))
    branches = []
    for key, title in KSE_BRANCHES:
        items = [s for s in seats.values() if s.get("branch") == key]
        items.sort(
            key=lambda s: (
                s.get("rank", 999),
                1 if s.get("unspecified") else 0,
                s["code"],
            )
        )
        branches.append({"key": key, "title": title, "seats": items})
    tree = build_org_tree(seats, layout)
    visible_codes = set()
    for unit in layout.get("units") or []:
        if not unit.get("is_visible", 1):
            continue
        for spec in unit.get("seats") or []:
            visible_codes.add(spec["office_code"])
    filled = sum(1 for code in visible_codes if seats.get(code, {}).get("people"))
    shown_codes = set(visible_codes)
    if tree.get("unspecified"):
        filled += 1
        shown_codes.add(tree["unspecified"]["code"])
    filled += len(tree.get("outside") or [])
    shown_codes.update(seat["code"] for seat in tree.get("outside") or [])
    # Satu orang bisa memegang dua kursi dalam satu periode (misalnya PJ dua
    # fakultas). Yang dihitung orangnya, bukan penugasannya.
    people = {
        person["id"]
        for code in shown_codes
        for person in (seats.get(code) or {}).get("people") or []
        if person.get("id")
    }
    return {
        "period": period_start,
        "period_label": format_period(period_start, period_start + 1 if period_start else None),
        "branches": branches,
        "tree": tree,
        "layout": layout,
        "filled": filled,
        "people": len(people),
    }
