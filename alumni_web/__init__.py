from __future__ import annotations

import csv
import io
import logging
import mimetypes
import os
import secrets
import time
from functools import wraps
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import (
    Flask,
    Response,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from .catalog import (
    CONTACT_FIELDS,
    FACULTIES,
    INTERNAL_FIELDS,
    PII_FIELDS,
    PUBLIC_FIELDS,
    SENSITIVE_FIELDS,
    STATUS_LABELS,
)
from .config import ROOT, Config, validate_base_url, validate_secret
from .db import audit, get_db, init_app as init_db_app, utcnow
from .import_csv import import_csv_path
from .membership import password_error, review_counts
from .offices import (
    KSE_OFFICE_GROUPS,
    build_org_chart,
    decorate_alumni_rows,
    format_period,
    get_offices,
    group_roles_by_term,
    list_roles,
    office_groups,
    office_label,
    role_periods,
    stats_kind,
)
from .quality import refresh_duplicate_flags
from . import org_admin, portal
from .security import (
    clamp_int,
    client_key,
    csv_cell,
    parse_cohort,
    rate_limited,
    safe_next,
)

# Python 3.10 belum mengenal woff2, tanpa ini font dikirim application/octet-stream.
mimetypes.add_type("font/woff2", ".woff2")

ACTIVATE_MSG = (
    "Jika email tercatat, permintaan aktivasi diteruskan ke pengurus. "
    "Tunggu persetujuan sebelum masuk."
)
# Dibandingkan saat email tidak ditemukan agar waktu respons /login tidak
# membocorkan email mana yang terdaftar.
DUMMY_HASH = generate_password_hash("timing-equalizer-bukan-sandi-nyata")
FILTER_KEYS = ("q", "fakultas", "angkatan", "status", "jurusan", "kota", "mutu", "jabatan")
MAP_ALUMNI_CAP = 40


def _share_rows(rows, total: int) -> list[dict]:
    items = []
    for row in rows:
        item = dict(row)
        item["share"] = round(100 * item["n"] / total) if total else 0
        items.append(item)
    return items


# Cek hidup, robots, dan berkas statis tidak boleh menulis cookie sesi.
BARE_ENDPOINTS = frozenset({"static", "healthz", "robots"})
NOINDEX_ENDPOINTS = {
    "directory",
    "profile",
    "map_points",
    "org_chart",
    "register_alumni",
    "claim_profile",
    "forgot_password",
    "invite_accept",
    "recover_password",
    "recover_admin",
    "own_profile",
    "login",
    "activate",
    "change_password",
}
AUTH_NOSTORE_ENDPOINTS = frozenset({
    "login",
    "register_alumni",
    "claim_profile",
    "forgot_password",
    "invite_accept",
    "recover_password",
    "recover_admin",
    "activate",
    "change_password",
})
# Antrean kerja pengurus di /admin?mutu=…
QUALITY_FILTERS = {
    "perlu_dilengkapi": ("Perlu dilengkapi", "data_quality_flags LIKE '%perlu_dilengkapi%'"),
    "tanpa_kota": ("Tanpa kota", "city IS NULL OR TRIM(city) = ''"),
    "tanpa_jabatan": (
        "Tanpa jabatan KSE",
        "is_listed = 1 AND NOT EXISTS ("
        "SELECT 1 FROM alumni_kse_roles r WHERE r.alumni_id = alumni.id"
        ")",
    ),
    "tanpa_angkatan": ("Tanpa angkatan", "cohort_year IS NULL"),
    "tanpa_fakultas": ("Tanpa fakultas", "faculty_code IS NULL"),
    "skeleton": ("Hanya nama", "data_quality_flags LIKE '%skeleton%'"),
    "kembar": ("Nama kembar", "is_duplicate_suspect = 1 AND is_listed = 1"),
    "kota_tidak_terpetakan": ("Kota tidak terpetakan", "data_quality_flags LIKE '%kota_tidak_terpetakan%'"),
    "telepon_tidak_valid": ("Telepon tidak valid", "data_quality_flags LIKE '%telepon_tidak_valid%'"),
    "tersembunyi": ("Tersembunyi", "is_listed = 0"),
    "minta_sembunyi": ("Minta disembunyikan", "hide_requested = 1 AND is_listed = 1"),
}


def _setup_logging(app: Flask, instance: Path) -> None:
    log_dir = instance / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "app.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    handler.setLevel(logging.INFO)
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)


def create_app() -> Flask:
    app = Flask(
        __name__,
        instance_path=str(ROOT / "instance"),
        instance_relative_config=True,
    )
    app.config.from_object(Config)
    for key in ("SECRET_KEY", "DATABASE", "ADMIN_EMAIL", "ADMIN_PASSWORD"):
        if os.environ.get(key):
            app.config[key] = os.environ[key]
    instance = Path(app.instance_path)
    instance.mkdir(parents=True, exist_ok=True)
    try:
        instance.chmod(0o700)
    except (OSError, NotImplementedError):
        pass
    init_db_app(app)
    app.config["TESTING"] = app.config.get("TESTING") or os.environ.get("FLASK_TESTING") == "1"
    if not app.config["TESTING"]:
        validate_secret(app.config.get("SECRET_KEY") or "")
        if (app.config.get("ALUMNI_ENV") or "") == "production":
            validate_base_url(app.config.get("APP_BASE_URL") or "")
        _setup_logging(app, instance)
    app.jinja_env.finalize = lambda value: "" if value is None else value
    if not app.config["TESTING"] and app.config["PREPARE_ON_BOOT"]:
        from .boot import prepare

        prepare(app)

    @app.url_defaults
    def _static_cache_bust(endpoint, values):
        if endpoint != "static" or "v" in values:
            return
        filename = values.get("filename")
        if not filename or app.static_folder is None:
            return
        path = Path(app.static_folder) / filename
        try:
            values["v"] = int(path.stat().st_mtime)
        except OSError:
            pass

    @app.context_processor
    def inject_globals():
        extras = {}
        user = g.get("user")
        if user is not None and user["role"] == "admin":
            extras["review"] = review_counts(get_db())
        return {
            "current_user": user,
            "faculties": FACULTIES,
            "status_labels": STATUS_LABELS,
            "kse_offices": get_offices(),
            "kse_office_groups": office_groups(),
            "format_period": format_period,
            "role_terms": group_roles_by_term,
            "office_label": office_label,
            "csrf_token": session.get("_csrf", ""),
            "allow_indexing": app.config["ALLOW_INDEXING"],
            "review": extras.get("review"),
        }

    @app.before_request
    def load_user():
        if request.endpoint in BARE_ENDPOINTS:
            return
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_hex(16)
        g.user = None
        uid = session.get("user_id")
        if not uid:
            return
        row = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if row is None or row["status"] != "active":
            session.pop("user_id", None)
            return
        g.user = row

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Frame-Options"] = "SAMEORIGIN"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "font-src 'self'; "
            "img-src 'self' data: https://*.tile.openstreetmap.org https://tile.openstreetmap.org; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'self'"
        )
        if request.is_secure:
            resp.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        endpoint = request.endpoint or ""
        if endpoint == "static":
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif g.get("user") is not None:
            resp.headers["Cache-Control"] = "no-store, private"
            resp.headers["Pragma"] = "no-cache"
        elif endpoint in AUTH_NOSTORE_ENDPOINTS:
            resp.headers["Cache-Control"] = "no-store, private"
            resp.headers["Pragma"] = "no-cache"
        if not app.config["ALLOW_INDEXING"] and (
            endpoint in NOINDEX_ENDPOINTS
            or endpoint.startswith("admin")
            or endpoint.startswith("own_")
        ):
            resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        return resp

    @app.template_filter("faculty_name")
    def faculty_name(code):
        return FACULTIES.get(code or "", code or "—")

    @app.template_filter("status_name")
    def status_name(code):
        return STATUS_LABELS.get(code or "", code or "—")

    @app.template_filter("office_name")
    def office_name(code, scope=None):
        return office_label(code, scope)

    @app.template_filter("display_name")
    def display_name(name: str) -> str:
        """Nama yang terisi HURUF BESAR semua di formulir dirapikan saat tampil.

        Hanya presentasi: nilai di basis data tidak diubah.
        """
        text = (name or "").strip()
        letters = [ch for ch in text if ch.isalpha()]
        if letters and all(ch.isupper() for ch in letters):
            return text.title()
        return text

    @app.template_filter("initials")
    def initials(name: str) -> str:
        parts = [p for p in (name or "").split() if p]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()

    @app.template_filter("quality_notes")
    def quality_notes_filter(row):
        from .normalize import quality_notes

        return quality_notes(row)

    def csrf_ok() -> bool:
        sent = request.form.get("csrf") or request.headers.get("X-CSRF-Token") or ""
        expected = session.get("_csrf") or ""
        return bool(sent) and bool(expected) and secrets.compare_digest(sent, expected)

    def admin_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None or g.user["role"] != "admin":
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    portal.register(app, csrf_ok=csrf_ok, admin_required=admin_required)
    org_admin.register(app, csrf_ok=csrf_ok, admin_required=admin_required)
    missing = [
        name
        for name in ("register_alumni", "claim_profile", "forgot_password", "own_profile")
        if name not in app.view_functions
    ]
    if missing:
        raise RuntimeError(f"Rute keanggotaan tidak terpasang: {', '.join(missing)}")

    def can_see_contact() -> bool:
        return (
            g.user is not None
            and g.user["status"] == "active"
            and g.user["role"] in ("admin", "alumni")
        )

    def can_see_sensitive(alumni_id) -> bool:
        if g.user is None or g.user["status"] != "active":
            return False
        if g.user["role"] == "admin":
            return True
        return g.user["role"] == "alumni" and g.user["alumni_id"] == alumni_id

    def strip_pii(row) -> dict:
        """Daftar-izin: kolom baru tertutup sampai dinyatakan publik."""
        source = dict(row)
        allowed = set(PUBLIC_FIELDS)
        if can_see_contact():
            allowed |= set(CONTACT_FIELDS)
        if can_see_sensitive(source.get("id")):
            allowed |= set(SENSITIVE_FIELDS)
        if g.user is not None and g.user["role"] == "admin":
            allowed |= set(INTERNAL_FIELDS)
        data = {key: source.get(key) for key in allowed if key in source}
        for field in PII_FIELDS:
            data.setdefault(field, None)
        return data

    def map_min_count() -> int:
        n = int(app.config.get("MAP_MIN_COUNT") or 3)
        return n if n > 0 else 3

    def parse_page() -> int:
        return clamp_int(request.args.get("page"), 1, 100_000, 1)

    def filter_query() -> dict:
        """Hanya kunci filter yang dikenal boleh masuk url_for(**query)."""
        return {
            key: request.args[key]
            for key in FILTER_KEYS
            if (request.args.get(key) or "").strip()
        }

    def alumni_filters(listed_only: bool = True, allow_quality: bool = False):
        clauses = []
        params: list = []
        if listed_only:
            clauses.append("is_listed = 1")
        if allow_quality:
            mutu = QUALITY_FILTERS.get(request.args.get("mutu") or "")
            if mutu:
                clauses.append(mutu[1])
        q = (request.args.get("q") or "").strip()
        if q:
            like = f"%{q}%"
            clauses.append(
                "(full_name LIKE ? OR workplace LIKE ? OR city LIKE ? OR major_normalized LIKE ? OR major_raw LIKE ?)"
            )
            params.extend([like, like, like, like, like])
        faculty = request.args.get("fakultas") or ""
        if faculty:
            clauses.append("faculty_code = ?")
            params.append(faculty)
        angkatan = parse_cohort(request.args.get("angkatan"))
        if angkatan is not None:
            clauses.append("cohort_year = ?")
            params.append(angkatan)
        status = request.args.get("status") or ""
        if status:
            clauses.append("status_code = ?")
            params.append(status)
        jurusan = (request.args.get("jurusan") or "").strip()
        if jurusan:
            clauses.append("(major_normalized LIKE ? OR major_raw LIKE ?)")
            params.extend([f"%{jurusan}%", f"%{jurusan}%"])
        kota = (request.args.get("kota") or "").strip()
        if kota:
            clauses.append("city LIKE ?")
            params.append(f"%{kota}%")
        jabatan = (request.args.get("jabatan") or "").strip()
        if jabatan and jabatan in get_offices():
            clauses.append(
                "id IN (SELECT alumni_id FROM alumni_kse_roles WHERE office_code = ?)"
            )
            params.append(jabatan)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    def listed_city_points():
        db = get_db()
        min_count = map_min_count()
        groups = db.execute(
            """
            SELECT city, province, lat, lng, COUNT(*) AS n
            FROM alumni
            WHERE is_listed = 1 AND lat IS NOT NULL AND lng IS NOT NULL AND city IS NOT NULL
            GROUP BY city, province, lat, lng
            HAVING n >= ?
            ORDER BY n DESC, city COLLATE NOCASE
            """,
            (min_count,),
        ).fetchall()

        def city_key(row):
            return (row["city"], row["province"] or "", row["lat"], row["lng"])

        buckets = {city_key(group): [] for group in groups}
        if buckets:
            people = db.execute(
                """
                SELECT id, full_name, faculty_code, cohort_year, major_normalized,
                       city, province, lat, lng
                FROM alumni
                WHERE is_listed = 1
                  AND lat IS NOT NULL AND lng IS NOT NULL AND city IS NOT NULL
                ORDER BY full_name COLLATE NOCASE
                """
            ).fetchall()
            for person in people:
                bucket = buckets.get(city_key(person))
                if bucket is not None and len(bucket) < MAP_ALUMNI_CAP:
                    bucket.append(person)
        points = []
        for group in groups:
            points.append(
                {
                    "city": group["city"],
                    "province": group["province"],
                    "lat": group["lat"],
                    "lng": group["lng"],
                    "count": group["n"],
                    "alumni": [
                        {
                            "id": person["id"],
                            "full_name": person["full_name"],
                            "faculty_code": person["faculty_code"],
                            "cohort_year": person["cohort_year"],
                            "major_normalized": person["major_normalized"],
                        }
                        for person in buckets[city_key(group)]
                    ],
                }
            )
        return points, min_count

    @app.route("/")
    def home():
        db = get_db()
        stats = db.execute(
            """
            SELECT
              COUNT(*) AS total,
              COUNT(DISTINCT faculty_code) AS faculties,
              COUNT(DISTINCT cohort_year) AS cohorts,
              COUNT(DISTINCT city) AS cities,
              MIN(cohort_year) AS cohort_min,
              MAX(cohort_year) AS cohort_max
            FROM alumni WHERE is_listed = 1
            """
        ).fetchone()
        officers = db.execute(
            """
            SELECT COUNT(DISTINCT r.alumni_id) AS n
            FROM alumni_kse_roles r
            JOIN alumni a ON a.id = r.alumni_id
            WHERE a.is_listed = 1
            """
        ).fetchone()["n"]
        by_faculty = db.execute(
            """
            SELECT faculty_code, COUNT(*) AS n FROM alumni
            WHERE is_listed = 1 AND faculty_code IS NOT NULL
            GROUP BY faculty_code ORDER BY n DESC, faculty_code
            """
        ).fetchall()
        latest_cohort = stats["cohort_max"]
        spotlight = []
        latest_cohort_total = 0
        if latest_cohort:
            latest_cohort_total = db.execute(
                "SELECT COUNT(*) AS n FROM alumni WHERE is_listed = 1 AND cohort_year = ?",
                (latest_cohort,),
            ).fetchone()["n"]
            spotlight = db.execute(
                """
                SELECT id, full_name, faculty_code, major_normalized, cohort_year,
                       workplace, city, status_code
                FROM alumni
                WHERE is_listed = 1 AND cohort_year = ?
                ORDER BY
                  (COALESCE(TRIM(workplace), '') != '' OR COALESCE(TRIM(city), '') != '') DESC,
                  full_name
                LIMIT 8
                """,
                (latest_cohort,),
            ).fetchall()
        quotes = db.execute(
            """
            SELECT id, full_name, faculty_code, cohort_year, testimonial
            FROM alumni
            WHERE is_listed = 1 AND LENGTH(TRIM(testimonial)) BETWEEN 70 AND 260
            ORDER BY RANDOM()
            LIMIT 8
            """
        ).fetchall()
        from .normalize import testimonial_has_contact

        quotes = [row for row in quotes if not testimonial_has_contact(row["testimonial"])][:6]
        return render_template(
            "home.html",
            stats=stats,
            officers=officers or 0,
            by_faculty=by_faculty,
            latest_cohort=latest_cohort,
            latest_cohort_total=latest_cohort_total,
            spotlight=decorate_alumni_rows(db, spotlight),
            quotes=quotes,
        )

    @app.route("/direktori")
    def directory():
        db = get_db()
        where, params = alumni_filters()
        page = parse_page()
        per_page = 24
        total = db.execute(f"SELECT COUNT(*) FROM alumni{where}", params).fetchone()[0]
        pages = max((total + per_page - 1) // per_page, 1)
        page = min(page, pages)
        rows = db.execute(
            f"""
            SELECT id, full_name, faculty_code, major_normalized, cohort_year, workplace, city, status_code, gender
            FROM alumni{where}
            ORDER BY full_name COLLATE NOCASE
            LIMIT ? OFFSET ?
            """,
            params + [per_page, (page - 1) * per_page],
        ).fetchall()
        cohorts = [
            r[0]
            for r in db.execute(
                """
                SELECT DISTINCT cohort_year FROM alumni
                WHERE cohort_year IS NOT NULL AND is_listed = 1
                ORDER BY cohort_year
                """
            )
        ]
        query = filter_query()
        return render_template(
            "directory.html",
            rows=decorate_alumni_rows(db, rows),
            total=total,
            page=page,
            pages=pages,
            cohorts=cohorts,
            query=query,
        )

    @app.route("/alumni/<int:alumni_id>")
    def profile(alumni_id: int):
        db = get_db()
        if g.user is not None and g.user["role"] == "admin":
            row = db.execute("SELECT * FROM alumni WHERE id = ?", (alumni_id,)).fetchone()
        else:
            row = db.execute(
                "SELECT * FROM alumni WHERE id = ? AND is_listed = 1", (alumni_id,)
            ).fetchone()
        if row is None:
            abort(404)
        return render_template(
            "profile.html",
            alumni=strip_pii(row),
            see_contact=can_see_contact(),
            see_sensitive=can_see_sensitive(row["id"]),
            roles=list_roles(db, alumni_id),
        )

    @app.route("/statistik")
    def stats_page():
        db = get_db()
        summary = dict(
            db.execute(
                """
                SELECT
                  COUNT(*) AS total,
                  MIN(cohort_year) AS cohort_min,
                  MAX(cohort_year) AS cohort_max,
                  SUM(CASE WHEN city IS NOT NULL THEN 1 ELSE 0 END) AS with_city,
                  SUM(CASE WHEN status_code IS NOT NULL THEN 1 ELSE 0 END) AS with_status,
                  SUM(CASE WHEN faculty_code IS NULL THEN 1 ELSE 0 END) AS missing_faculty,
                  SUM(CASE WHEN cohort_year IS NULL THEN 1 ELSE 0 END) AS missing_cohort,
                  SUM(CASE WHEN status_code IS NULL THEN 1 ELSE 0 END) AS missing_status,
                  SUM(CASE WHEN city IS NULL THEN 1 ELSE 0 END) AS missing_city,
                  SUM(CASE WHEN workplace IS NULL THEN 1 ELSE 0 END) AS missing_workplace
                FROM alumni WHERE is_listed = 1
                """
            ).fetchone()
        )
        summary["officers"] = db.execute(
            """
            SELECT COUNT(DISTINCT r.alumni_id) AS n
            FROM alumni_kse_roles r
            JOIN alumni a ON a.id = r.alumni_id
            WHERE a.is_listed = 1
            """
        ).fetchone()["n"] or 0
        faculty_rows = db.execute(
            """
            SELECT faculty_code, COUNT(*) AS n FROM alumni
            WHERE is_listed = 1 AND faculty_code IS NOT NULL
            GROUP BY faculty_code ORDER BY n DESC
            """
        ).fetchall()
        faculty_n = sum(r["n"] for r in faculty_rows)
        by_faculty = _share_rows(faculty_rows, faculty_n)
        cohort_rows = db.execute(
            """
            SELECT cohort_year AS label, COUNT(*) AS n FROM alumni
            WHERE is_listed = 1 AND cohort_year IS NOT NULL
            GROUP BY cohort_year ORDER BY cohort_year
            """
        ).fetchall()
        by_cohort = _share_rows(cohort_rows, sum(r["n"] for r in cohort_rows))
        status_rows = db.execute(
            """
            SELECT status_code, COUNT(*) AS n FROM alumni
            WHERE is_listed = 1 AND status_code IS NOT NULL
            GROUP BY status_code ORDER BY n DESC
            """
        ).fetchall()
        by_status = _share_rows(status_rows, summary["with_status"] or 0)
        min_count = map_min_count()
        all_cities = db.execute(
            """
            SELECT city, COUNT(*) AS n FROM alumni
            WHERE is_listed = 1 AND city IS NOT NULL
            GROUP BY city ORDER BY n DESC
            """
        ).fetchall()
        visible_cities = [dict(row) for row in all_cities if row["n"] >= min_count]
        by_city = _share_rows(visible_cities[:12], summary["with_city"] or 0)
        city_more = visible_cities[12:]
        city_below = [dict(row) for row in all_cities if row["n"] < min_count]
        by_office = _share_rows(
            db.execute(
                """
                SELECT r.office_code, COUNT(DISTINCT r.alumni_id) AS n
                FROM alumni_kse_roles r
                JOIN alumni a ON a.id = r.alumni_id
                WHERE a.is_listed = 1
                GROUP BY r.office_code
                ORDER BY n DESC
                """
            ).fetchall(),
            summary["officers"] or 1,
        )
        holders = {key: set() for key, _title in KSE_OFFICE_GROUPS}
        for row in db.execute(
            """
            SELECT r.alumni_id, r.office_code
            FROM alumni_kse_roles r
            JOIN alumni a ON a.id = r.alumni_id
            WHERE a.is_listed = 1
            """
        ):
            kind = stats_kind(row["office_code"])
            if kind not in holders:
                kind = "member"
            holders[kind].add(row["alumni_id"])
        by_office_kind = _share_rows(
            [
                {"kind": key, "label": title, "n": len(holders[key])}
                for key, title in KSE_OFFICE_GROUPS
            ],
            summary["officers"] or 1,
        )
        peak_cohort = max(by_cohort, key=lambda row: row["n"]) if by_cohort else None
        top_faculty = by_faculty[0] if by_faculty else None
        working = sum(
            r["n"] for r in by_status if r["status_code"] in ("bekerja", "wirausaha")
        )
        chart = {
            "faculty": {
                "keys": [r["faculty_code"] for r in by_faculty],
                "labels": [FACULTIES.get(r["faculty_code"], r["faculty_code"]) for r in by_faculty],
                "data": [r["n"] for r in by_faculty],
            },
            "cohort": {
                "labels": [r["label"] for r in by_cohort],
                "data": [r["n"] for r in by_cohort],
            },
            "status": {
                "keys": [r["status_code"] for r in by_status],
                "labels": [STATUS_LABELS.get(r["status_code"], r["status_code"]) for r in by_status],
                "data": [r["n"] for r in by_status],
            },
            "office": {
                "keys": [r["kind"] for r in by_office_kind if r["n"]],
                "labels": [r["label"] for r in by_office_kind if r["n"]],
                "data": [r["n"] for r in by_office_kind if r["n"]],
            },
        }
        return render_template(
            "stats.html",
            summary=summary,
            by_faculty=by_faculty,
            by_cohort=by_cohort,
            by_status=by_status,
            by_city=by_city,
            city_more_n=sum(r["n"] for r in city_more),
            city_more_k=len(city_more),
            city_below_n=sum(r["n"] for r in city_below),
            city_below_k=len(city_below),
            min_count=min_count,
            by_office=by_office,
            by_office_kind=by_office_kind,
            faculty_n=faculty_n,
            peak_cohort=peak_cohort,
            top_faculty=top_faculty,
            working=working,
            chart=chart,
        )

    @app.route("/struktur")
    def org_chart():
        db = get_db()
        years = role_periods(db)
        raw = (request.args.get("periode") or "").strip()
        if raw == "semua" or (raw == "" and not years):
            year_i = None
        elif raw.isdigit():
            year_i = clamp_int(raw, 1990, 2100, 0) or None
            if year_i == 0:
                year_i = None
        elif years:
            year_i = years[0]
        else:
            year_i = None
        return render_template(
            "struktur.html",
            chart=build_org_chart(db, year_i),
            year=year_i,
            years=years,
        )

    @app.route("/peta")
    def map_page():
        points, min_count = listed_city_points()
        return render_template("map.html", points=points, min_count=min_count)

    @app.route("/api/map-points")
    def map_points():
        points, min_count = listed_city_points()
        return {"points": points, "min_count": min_count}

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            if not csrf_ok():
                abort(400)
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""
            # Batas per IP menahan penyerang tunggal, batas per email menahan
            # percobaan tersebar ke satu akun.
            if rate_limited(f"login:{client_key(request)}") or rate_limited(
                f"login-email:{email}", limit=20, window=900
            ):
                app.logger.warning("login rate limited ip=%s", client_key(request))
                flash("Terlalu banyak percobaan. Coba lagi nanti.", "err")
                return render_template("login.html"), 429
            db = get_db()
            user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            # Selalu verifikasi satu hash, termasuk saat email tidak ada, agar
            # durasi respons tidak menjadi oracle keberadaan email.
            stored = user["password_hash"] if user else DUMMY_HASH
            ok = check_password_hash(stored, password) and user is not None
            if ok and user["status"] == "active":
                nxt = safe_next(request.args.get("next"), url_for("directory"))
                session.clear()
                session["user_id"] = user["id"]
                session["_csrf"] = secrets.token_hex(16)
                session.permanent = True
                g.user = user
                audit("login_ok", email)
                db.commit()
                app.logger.info("login ok user=%s", user["id"])
                flash("Berhasil masuk.", "ok")
                return redirect(nxt)
            if ok:
                audit("login_blocked", f"{email} status={user['status']}")
            else:
                audit("login_fail", email)
            db.commit()
            app.logger.info("login gagal ip=%s", client_key(request))
            flash("Email atau kata sandi salah.", "err")
        return render_template("login.html")

    @app.route("/logout", methods=["POST"])
    def logout():
        if not csrf_ok():
            abort(400)
        if g.user is not None:
            audit("logout", g.user["email"])
            get_db().commit()
        session.clear()
        flash("Anda sudah keluar.", "ok")
        return redirect(url_for("home"))

    @app.route("/aktivasi", methods=["GET", "POST"])
    def activate():
        if request.method == "GET":
            return redirect(url_for("claim_profile"))
        if not csrf_ok():
            abort(400)
        if rate_limited(f"activate:{client_key(request)}"):
            flash("Terlalu banyak percobaan. Coba lagi nanti.", "err")
            return redirect(url_for("claim_profile")), 429
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        err = password_error(password)
        if err:
            flash(err, "err")
            return redirect(url_for("claim_profile"))
        password_hash = generate_password_hash(password)
        db = get_db()
        alumni = db.execute(
            "SELECT id FROM alumni WHERE email_normalized = ? AND is_listed = 1",
            (email,),
        ).fetchone()
        existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if alumni is not None and existing is None:
            db.execute(
                """
                INSERT INTO users
                  (email, password_hash, role, status, alumni_id, request_ip, created_at)
                VALUES (?, ?, 'alumni', 'pending', ?, ?, ?)
                """,
                (email, password_hash, alumni["id"], client_key(request), utcnow()),
            )
            audit("activation_request", f"{email} ip={client_key(request)}")
            db.commit()
            app.logger.info("permintaan aktivasi ip=%s", client_key(request))
        flash(ACTIVATE_MSG, "ok")
        return redirect(url_for("login"))

    @app.route("/akun/sandi", methods=["GET", "POST"])
    def change_password():
        if g.user is None:
            return redirect(url_for("login", next=url_for("change_password")))
        if request.method == "POST":
            if not csrf_ok():
                abort(400)
            if rate_limited(f"pwd:{g.user['id']}", limit=10, window=900):
                flash("Terlalu banyak percobaan. Coba lagi nanti.", "err")
                return render_template("password.html"), 429
            current = request.form.get("current") or ""
            baru = request.form.get("baru") or ""
            ulang = request.form.get("ulang") or ""
            if not check_password_hash(g.user["password_hash"], current):
                audit("password_change_fail", g.user["email"])
                get_db().commit()
                flash("Kata sandi saat ini salah.", "err")
                return render_template("password.html")
            err = password_error(baru)
            if err:
                flash(err, "err")
                return render_template("password.html")
            if baru != ulang:
                flash("Ulangi kata sandi belum sama.", "err")
                return render_template("password.html")
            db = get_db()
            db.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (generate_password_hash(baru), g.user["id"]),
            )
            audit("password_change", g.user["email"])
            db.commit()
            session.clear()
            flash("Kata sandi diganti. Masuk kembali.", "ok")
            return redirect(url_for("login"))
        return render_template("password.html")

    @app.route("/admin")
    @admin_required
    def admin_home():
        db = get_db()
        where, params = alumni_filters(listed_only=False, allow_quality=True)
        page = parse_page()
        per_page = 50
        total_rows = db.execute(f"SELECT COUNT(*) FROM alumni{where}", params).fetchone()[0]
        pages = max((total_rows + per_page - 1) // per_page, 1)
        page = min(page, pages)
        # `id DESC` memecah hasil impor yang berbagi satu `updated_at`,
        # supaya urutan halaman tidak berubah-ubah sendiri.
        rows = db.execute(
            f"SELECT * FROM alumni{where}"
            " ORDER BY updated_at DESC, id DESC"
            " LIMIT ? OFFSET ?",
            params + [per_page, (page - 1) * per_page],
        ).fetchall()
        counts = db.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN is_duplicate_suspect = 1 AND is_listed = 1 THEN 1 ELSE 0 END) AS dups,
                   SUM(CASE WHEN data_quality_flags LIKE '%skeleton%' THEN 1 ELSE 0 END) AS skeleton,
                   SUM(CASE WHEN data_quality_flags LIKE '%perlu_dilengkapi%' THEN 1 ELSE 0 END) AS perlu,
                   SUM(CASE WHEN is_listed = 0 THEN 1 ELSE 0 END) AS tersembunyi
            FROM alumni
            """
        ).fetchone()
        queue = {
            key: db.execute(f"SELECT COUNT(*) FROM alumni WHERE {clause}").fetchone()[0]
            for key, (_, clause) in QUALITY_FILTERS.items()
        }
        pending = db.execute(
            "SELECT COUNT(*) FROM users WHERE status = 'pending'"
        ).fetchone()[0]
        review = review_counts(db)
        pages = max((total_rows + per_page - 1) // per_page, 1)
        query = filter_query()
        return render_template(
            "admin/index.html",
            rows=rows,
            counts=counts,
            pending=pending,
            review=review,
            page=page,
            pages=pages,
            total_rows=total_rows,
            query=query,
            queue=queue,
            quality_filters=QUALITY_FILTERS,
            mutu=request.args.get("mutu") or "",
        )

    def _form_record() -> dict:
        from .normalize import record_from_form

        return record_from_form(
            {
                "full_name": request.form.get("full_name", ""),
                "gender": request.form.get("gender", ""),
                "date_of_birth": request.form.get("date_of_birth", ""),
                "domicile": request.form.get("domicile", ""),
                "workplace": request.form.get("workplace", ""),
                "phone": request.form.get("phone", ""),
                "status": request.form.get("status", ""),
                "email": request.form.get("email", ""),
                "cohort_year": request.form.get("cohort_year", ""),
                "graduation_year": request.form.get("graduation_year", ""),
                "kse_last_year": request.form.get("kse_last_year", ""),
                "faculty": request.form.get("faculty", ""),
                "major": request.form.get("major", ""),
                "testimonial": request.form.get("testimonial", ""),
            },
            source="admin",
        )

    @app.route("/admin/alumni/baru", methods=["GET", "POST"])
    @admin_required
    def admin_new():
        if request.method == "POST":
            if not csrf_ok():
                abort(400)
            rec = _form_record()
            rec["is_listed"] = 1 if request.form.get("is_listed") else 0
            if not rec["full_name"]:
                flash("Nama wajib diisi.", "err")
                return render_template("admin/form.html", alumni=rec, mode="new", roles=[])
            rec["created_at"] = rec["updated_at"] = utcnow()
            db = get_db()
            cols = list(rec.keys())
            db.execute(
                f"INSERT INTO alumni ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                [rec[c] for c in cols],
            )
            refresh_duplicate_flags(db, [rec.get("name_normalized")])
            db.commit()
            flash("Alumni ditambahkan.", "ok")
            return redirect(url_for("admin_home"))
        return render_template("admin/form.html", alumni=None, mode="new", roles=[])

    @app.route("/admin/alumni/<int:alumni_id>/ubah", methods=["GET", "POST"])
    @admin_required
    def admin_edit(alumni_id: int):
        db = get_db()
        row = db.execute("SELECT * FROM alumni WHERE id = ?", (alumni_id,)).fetchone()
        if row is None:
            abort(404)
        if request.method == "POST":
            if not csrf_ok():
                abort(400)
            rec = _form_record()
            rec["is_listed"] = 1 if request.form.get("is_listed") else 0
            if not rec["full_name"]:
                flash("Nama wajib diisi.", "err")
                rec["id"] = alumni_id
                return render_template(
                    "admin/form.html",
                    alumni=rec,
                    mode="edit",
                    roles=list_roles(db, alumni_id),
                )
            rec["updated_at"] = utcnow()
            rec["source"] = row["source"]
            rec["submitted_at"] = row["submitted_at"]
            rec["created_at"] = row["created_at"]
            rec["self_updated_at"] = row["self_updated_at"] if "self_updated_at" in row.keys() else None
            rec["hide_requested"] = row["hide_requested"] if "hide_requested" in row.keys() else 0
            cols = [c for c in rec.keys()]
            db.execute(
                f"UPDATE alumni SET {', '.join(c + ' = ?' for c in cols)} WHERE id = ?",
                [rec[c] for c in cols] + [alumni_id],
            )
            refresh_duplicate_flags(
                db, [row["name_normalized"], rec.get("name_normalized")]
            )
            db.commit()
            flash("Perubahan disimpan.", "ok")
            return redirect(url_for("admin_home"))
        return render_template(
            "admin/form.html",
            alumni=row,
            mode="edit",
            roles=list_roles(db, alumni_id),
        )

    @app.route("/admin/alumni/<int:alumni_id>/hapus", methods=["POST"])
    @admin_required
    def admin_delete(alumni_id: int):
        if not csrf_ok():
            abort(400)
        db = get_db()
        row = db.execute(
            "SELECT name_normalized FROM alumni WHERE id = ?", (alumni_id,)
        ).fetchone()
        db.execute("DELETE FROM alumni WHERE id = ?", (alumni_id,))
        if row:
            refresh_duplicate_flags(db, [row["name_normalized"]])
        audit("alumni_delete", f"id={alumni_id}")
        db.commit()
        flash("Data dihapus.", "ok")
        return redirect(url_for("admin_home"))

    @app.route("/admin/import", methods=["GET", "POST"])
    @admin_required
    def admin_import():
        result = None
        if request.method == "POST":
            if not csrf_ok():
                abort(400)
            upload = request.files.get("file")
            if not upload or not upload.filename:
                flash("Pilih berkas CSV.", "err")
                return render_template("admin/import.html", result=None)
            filename = upload.filename.lower()
            if not filename.endswith(".csv"):
                flash("Berkas harus berekstensi .csv.", "err")
                return render_template("admin/import.html", result=None)
            dest = Path(app.instance_path) / "uploads"
            dest.mkdir(exist_ok=True)
            # Sisa unggahan dari proses yang mati di tengah impor tidak boleh
            # menginap di disk: isinya WA, email, dan alamat.
            for stale in dest.glob("*.csv"):
                if time.time() - stale.stat().st_mtime > 600:
                    stale.unlink(missing_ok=True)
            path = dest / f"{secrets.token_hex(8)}.csv"
            insert_only = bool(request.form.get("insert_only"))
            try:
                upload.save(path)
                result = import_csv_path(path, insert_only=insert_only)
                audit("import_csv", f"{upload.filename} rows={result['row_count']}")
                get_db().commit()
                extra = ""
                if result.get("protected"):
                    extra = f" {result['protected']} baris dilindungi karena sudah diubah alumni."
                flash(
                    f"Impor selesai: {result['inserted']} baru, {result['updated']} diperbarui, {result['skipped']} dilewati.{extra}",
                    "ok",
                )
            except (ValueError, UnicodeDecodeError, csv.Error) as exc:
                flash(str(exc) or "Impor gagal. Periksa berkas CSV.", "err")
                result = None
            finally:
                if path.exists():
                    path.unlink()
        return render_template("admin/import.html", result=result)

    @app.route("/admin/export.csv", methods=["GET", "POST"])
    @admin_required
    def admin_export():
        db = get_db()
        total = db.execute("SELECT COUNT(*) FROM alumni").fetchone()[0]
        if request.method == "GET":
            return render_template("admin/export.html", total=total)
        if not csrf_ok():
            abort(400)
        rows = db.execute("SELECT * FROM alumni ORDER BY full_name COLLATE NOCASE").fetchall()
        output = io.StringIO()
        if rows:
            writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            for row in rows:
                writer.writerow({key: csv_cell(row[key]) for key in row.keys()})
        data = output.getvalue().encode("utf-8-sig")
        audit("export_csv", f"rows={len(rows)}")
        db.commit()
        app.logger.info("ekspor PII oleh user=%s rows=%s", g.user["id"], len(rows))
        return Response(
            data,
            mimetype="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=alumni-kse-unand.csv",
                "Cache-Control": "no-store, private",
            },
        )

    @app.route("/admin/akun")
    @admin_required
    def admin_accounts():
        db = get_db()
        rows = db.execute(
            """
            SELECT u.id, u.email, u.role, u.status, u.created_at, u.request_ip, a.full_name
            FROM users u
            LEFT JOIN alumni a ON a.id = u.alumni_id
            ORDER BY CASE u.status WHEN 'pending' THEN 0 WHEN 'active' THEN 1 ELSE 2 END, u.created_at DESC
            """
        ).fetchall()
        return render_template("admin/accounts.html", rows=rows)

    @app.route("/admin/akun/<int:user_id>/<action>", methods=["POST"])
    @admin_required
    def admin_account_action(user_id: int, action: str):
        if not csrf_ok():
            abort(400)
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if user is None or user["role"] == "admin":
            abort(404)
        if action == "setujui":
            db.execute("UPDATE users SET status = 'active' WHERE id = ?", (user_id,))
            flash("Akun disetujui.", "ok")
        elif action == "tolak":
            db.execute("DELETE FROM users WHERE id = ? AND status = 'pending'", (user_id,))
            flash("Permintaan ditolak.", "ok")
        elif action == "nonaktif":
            db.execute("UPDATE users SET status = 'disabled' WHERE id = ?", (user_id,))
            flash("Akun dinonaktifkan.", "ok")
        else:
            abort(404)
        audit(f"account_{action}", f"user={user_id} email={user['email']}")
        db.commit()
        app.logger.info("akun %s oleh admin=%s target=%s", action, g.user["id"], user_id)
        return redirect(url_for("admin_accounts"))

    @app.route("/robots.txt")
    def robots():
        lines = [
            "User-agent: *",
            "Disallow: /admin",
            "Disallow: /api/",
            "Disallow: /akun/",
            "Disallow: /daftar",
            "Disallow: /klaim",
            "Disallow: /undang",
            "Disallow: /pulih",
            "Disallow: /profil",
            "Disallow: /lupa-sandi",
        ]
        if not app.config["ALLOW_INDEXING"]:
            lines += ["Disallow: /direktori", "Disallow: /alumni/", "Disallow: /struktur"]
        return Response("\n".join(lines) + "\n", mimetype="text/plain")

    @app.route("/healthz")
    def healthz():
        get_db().execute("SELECT 1").fetchone()
        return Response(
            '{"status":"ok"}',
            mimetype="application/json",
            headers={"Cache-Control": "no-store"},
        )

    @app.errorhandler(400)
    def bad_request(_e):
        return (
            render_template(
                "error.html",
                code=400,
                message="Permintaan tidak valid atau sesi kedaluwarsa. Muat ulang halaman lalu coba lagi.",
            ),
            400,
        )

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", code=403, message="Akses pengurus saja."), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404, message="Halaman tidak ditemukan."), 404

    @app.errorhandler(413)
    def too_large(_e):
        return (
            render_template("error.html", code=413, message="Berkas terlalu besar. Maksimal 8 MB."),
            413,
        )

    @app.errorhandler(429)
    def too_many(_e):
        return (
            render_template(
                "error.html", code=429, message="Terlalu banyak percobaan. Coba lagi nanti."
            ),
            429,
        )

    @app.errorhandler(500)
    def server_error(e):
        app.logger.exception("kesalahan server: %s", e)
        return render_template("error.html", code=500, message="Terjadi kesalahan. Coba lagi."), 500

    return app
