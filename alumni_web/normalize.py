"""Pembersih nilai CSV Google Form alumni KSE UNAND."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from typing import Any, Optional

from .catalog import (
    FACULTIES,
    FACULTY_ALIASES,
    GENDER_ALIASES,
    MAJOR_ALIASES,
    STATUS_ALIASES,
)

_FACULTY_BY_LABEL = {label.lower(): code for code, label in FACULTIES.items()}
from .geocode import geocode_domicile

_YEAR_RE = re.compile(r"(19|20)\d{2}")


def fold(text: Optional[str]) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text)).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def name_key(text: Optional[str]) -> str:
    return fold(text).lower()


# Isian "kosong" yang diketik responden di Google Form.
JUNK_VALUES = {"", "-", "--", "---", ".", "..", "–", "—", "_", "__", "n/a", "na", "tidak ada", "belum ada"}


def blank_if_junk(value: Optional[str]) -> Optional[str]:
    text = fold(value)
    if text.lower() in JUNK_VALUES:
        return None
    return text or None


def parse_year(value: Optional[str]) -> tuple[Optional[int], Optional[str]]:
    raw = fold(value)
    if not raw:
        return None, None
    low = raw.lower()
    if "belum" in low or "lupa" in low:
        return None, raw
    years = [int(m.group(0)) for m in _YEAR_RE.finditer(raw)]
    if years:
        return max(years), raw
    return None, raw


def parse_date(value: Optional[str]) -> Optional[str]:
    raw = fold(value)
    if not raw:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_timestamp(value: Optional[str]) -> Optional[str]:
    raw = fold(value)
    if not raw:
        return None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).isoformat(sep=" ")
        except ValueError:
            continue
    return raw


def normalize_phone(value: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    raw = blank_if_junk(value)
    if not raw:
        return None, None
    digits = re.sub(r"\D", "", raw)
    if not digits or digits in {"0", "00"}:
        return None, raw
    if digits.startswith("62"):
        norm = digits
    elif digits.startswith("0"):
        norm = "62" + digits[1:]
    elif digits.startswith("8"):
        norm = "62" + digits
    else:
        norm = digits
    if len(norm) < 10 or len(norm) > 15:
        return None, raw
    return norm, raw


def normalize_email(value: Optional[str]) -> Optional[str]:
    raw = fold(value).lower()
    if not raw or "@" not in raw:
        return None
    return raw


def faculty_code(value: Optional[str]) -> tuple[Optional[str], str]:
    raw = fold(value)
    if not raw:
        return None, ""
    key = raw.lower()
    code = FACULTY_ALIASES.get(key) or _FACULTY_BY_LABEL.get(key)
    if not code and key.startswith("fakultas "):
        inner = key[9:].strip()
        code = FACULTY_ALIASES.get(inner) or _FACULTY_BY_LABEL.get(inner)
    return code or "lain", raw


def major_name(value: Optional[str]) -> tuple[str, str]:
    raw = fold(value)
    if not raw:
        return "", ""
    mapped = MAJOR_ALIASES.get(raw.lower())
    if mapped:
        return mapped, raw
    return raw.title() if raw.isupper() or raw.islower() else raw, raw


def status_code(value: Optional[str]) -> tuple[Optional[str], str]:
    raw = fold(value)
    if not raw:
        return None, ""
    return STATUS_ALIASES.get(raw.lower()), raw


def gender_code(value: Optional[str]) -> Optional[str]:
    raw = fold(value)
    if not raw:
        return None
    return GENDER_ALIASES.get(raw.lower())


_CONTACT_IN_TEXT = re.compile(
    r"(?i)(?:[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}|https?://|(?:\+?62|08)\d{7,})"
)


def testimonial_has_contact(value: Optional[str]) -> bool:
    """Kesan pesan publik tidak boleh membawa nomor, email, atau tautan."""
    text = fold(value)
    return bool(text and _CONTACT_IN_TEXT.search(text.replace(" ", "")))


def quality_flags(row: dict[str, Any]) -> list[str]:
    """Bendera mutu data.

    `skeleton` khusus baris yang benar-benar hanya berisi nama.
    `perlu_dilengkapi` untuk baris yang layak tampil tetapi belum punya
    angkatan atau kota. Tempat kerja tidak masuk syarat ini: banyak alumni
    belum bekerja atau masih kuliah, jadi kolom itu boleh kosong.
    """
    flags = []
    isian = [
        row.get("date_of_birth"),
        row.get("domicile"),
        row.get("workplace"),
        row.get("email"),
        row.get("cohort_year"),
        row.get("faculty_code") or row.get("faculty_raw"),
        row.get("major_normalized") or row.get("major_raw"),
        row.get("phone_normalized"),
        row.get("status_code"),
        row.get("graduation_year"),
        row.get("kse_last_year"),
        row.get("city"),
    ]
    city = row.get("city")
    if isinstance(city, str):
        city = city.strip() or None
    if not any(isian):
        flags.append("skeleton")
    elif not row.get("cohort_year") or not city:
        flags.append("perlu_dilengkapi")
    if row.get("kse_last_raw") and not row.get("kse_last_year"):
        flags.append("tahun_kse_tidak_jelas")
    if row.get("graduation_raw") and not row.get("graduation_year"):
        if "belum" not in (row.get("graduation_raw") or "").lower():
            flags.append("tahun_lulus_tidak_jelas")
    phone_raw = row.get("phone")
    if phone_raw and not row.get("phone_normalized"):
        flags.append("telepon_tidak_valid")
    if row.get("cohort_year") and not (1980 <= row["cohort_year"] <= 2035):
        flags.append("angkatan_di luar_rentang")
    if not row.get("city") and row.get("domicile"):
        flags.append("kota_tidak_terpetakan")
    return flags


def quality_notes(row: dict[str, Any]) -> list[str]:
    """Apa yang perlu dilengkapi pada satu baris, dalam bahasa manusia.

    Kolom "Catatan mutu" di panel pengurus memakai ini, bukan nama bendera
    internal: pengurus perlu tahu *apa* yang kurang, bukan sekadar bahwa ada
    yang kurang. Urutannya mengikuti prioritas kerja — kota dulu, lalu identitas
    dasar, terakhir isian yang terbaca tetapi maknanya tidak jelas. Tempat kerja
    dan jabatan KSE tidak pernah masuk sini karena kosongnya wajar.
    """
    data = dict(row)
    flags = quality_flags(data)
    if "skeleton" in flags:
        return ["baru berisi nama"]
    notes: list[str] = []
    city = data.get("city")
    if isinstance(city, str):
        city = city.strip() or None
    if not city:
        notes.append(
            "kota belum terbaca dari alamat" if data.get("domicile") else "belum ada kota"
        )
    if not data.get("cohort_year"):
        notes.append("belum ada angkatan")
    faculty = data.get("faculty_code") or data.get("faculty_raw")
    major = data.get("major_normalized") or data.get("major_raw")
    if not faculty and not major:
        notes.append("belum ada fakultas dan jurusan")
    elif not faculty:
        notes.append("belum ada fakultas")
    elif not major:
        notes.append("belum ada jurusan")
    if "angkatan_di luar_rentang" in flags:
        notes.append("angkatan di luar rentang wajar")
    if "telepon_tidak_valid" in flags:
        notes.append("nomor WhatsApp tidak terbaca")
    if "tahun_lulus_tidak_jelas" in flags:
        notes.append("tahun lulus tidak jelas")
    if "tahun_kse_tidak_jelas" in flags:
        notes.append("tahun terakhir KSE tidak jelas")
    return notes


def record_from_form(values: dict[str, str], source: str = "google_form") -> dict[str, Any]:
    full_name = fold(values.get("full_name"))
    faculty_c, faculty_raw = faculty_code(values.get("faculty"))
    major_n, major_raw = major_name(values.get("major"))
    st_code, st_raw = status_code(values.get("status"))
    phone_n, phone_raw = normalize_phone(values.get("phone"))
    cohort, _ = parse_year(values.get("cohort_year"))
    grad, grad_raw = parse_year(values.get("graduation_year"))
    kse, kse_raw = parse_year(values.get("kse_last_year"))
    workplace = blank_if_junk(values.get("workplace"))
    domicile = blank_if_junk(values.get("domicile"))
    geo = geocode_domicile(domicile)
    row = {
        "full_name": full_name,
        "name_normalized": name_key(full_name),
        "gender": gender_code(values.get("gender")),
        "date_of_birth": parse_date(values.get("date_of_birth")),
        "domicile": domicile,
        "city": geo["city"] if geo else None,
        "province": geo["province"] if geo else None,
        "lat": geo["lat"] if geo else None,
        "lng": geo["lng"] if geo else None,
        "workplace": workplace,
        "phone": phone_raw,
        "phone_normalized": phone_n,
        "email": fold(values.get("email")) or None,
        "email_normalized": normalize_email(values.get("email")),
        "status_code": st_code,
        "status_raw": st_raw or None,
        "cohort_year": cohort,
        "graduation_year": grad,
        "graduation_raw": grad_raw,
        "kse_last_year": kse,
        "kse_last_raw": kse_raw,
        "faculty_code": faculty_c,
        "faculty_raw": faculty_raw or None,
        "major_normalized": major_n or None,
        "major_raw": major_raw or None,
        "testimonial": None
        if testimonial_has_contact(values.get("testimonial"))
        else (fold(values.get("testimonial")) or None),
        "source": source,
        "submitted_at": parse_timestamp(values.get("submitted_at")),
        "is_listed": 1,
    }
    flags = quality_flags(row)
    row["data_quality_flags"] = json.dumps(flags, ensure_ascii=False)
    return row
