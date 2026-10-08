"""Rute pengurus untuk menyesuaikan bagan kepengurusan."""

from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, url_for

from .db import audit, get_db
from .offices import format_period, get_offices, role_periods
from .org_layout import (
    PROTECTED_OFFICES,
    SEAT_KIND_LABELS,
    UNIT_KIND_LABELS,
    add_custom_seat,
    add_existing_seat,
    add_standard_unit,
    create_template,
    customize_period,
    default_template_slug,
    delete_seat,
    delete_template,
    delete_unit,
    ensure_org_layout,
    list_period_layouts,
    list_templates,
    move_seat,
    move_unit,
    period_blueprint,
    rename_template,
    repair_blueprint_seats,
    reset_period,
    set_default_template,
    template_by_slug,
    unused_offices_for_unit,
    update_seat,
    update_unit,
)
from .security import clamp_int


def register(app, *, csrf_ok, admin_required):
    def _year():
        raw = request.values.get("periode") or ""
        if raw.isdigit():
            return clamp_int(raw, 1990, 2100, 0) or None
        return None

    def _slug():
        return (request.values.get("acuan") or "").strip()

    def _focus_fragment(*, unit_id=None, seat_id=None) -> str:
        raw = (request.form.get("fokus") or "").strip()
        if seat_id:
            return f"seat-{int(seat_id)}"
        if unit_id:
            return f"unit-{int(unit_id)}"
        if raw.startswith(("unit-", "seat-")) and raw.replace("-", "").isalnum():
            return raw
        return ""

    def _back(*, unit_id=None, seat_id=None):
        year = _year()
        if year:
            url = url_for("admin_org", periode=year)
        else:
            slug = _slug()
            url = url_for("admin_acuan", acuan=slug) if slug else url_for("admin_org")
        fragment = _focus_fragment(unit_id=unit_id, seat_id=seat_id)
        return f"{url}#{fragment}" if fragment else url

    def _place_from_form():
        """Satu pilihan 'Tempat di bagan' → seat_kind + parent_seat_id."""
        place = (request.form.get("place") or request.form.get("seat_kind") or "").strip()
        parent_raw = request.form.get("parent_seat_id")
        if place.startswith("member:"):
            return "member", clamp_int(place.split(":", 1)[1], 1, 1_000_000, 0) or None
        if place == "member":
            return "member", clamp_int(parent_raw, 1, 1_000_000, 0) or None
        if place:
            return place, None
        return None, clamp_int(parent_raw, 1, 1_000_000, 0) or None

    def _period_view(db, year):
        custom = period_blueprint(db, year)
        preview = custom or template_by_slug(db, default_template_slug(db))
        return {
            "mode": "period",
            "year": year,
            "editable": custom is not None,
            "blueprint": preview,
            "uses_template": custom is None,
        }

    def _template_view(db, slug: str):
        fallback = default_template_slug(db)
        blueprint = template_by_slug(db, slug) or template_by_slug(db, fallback)
        return {
            "mode": "template",
            "year": None,
            "editable": True,
            "blueprint": blueprint,
            "uses_template": False,
        }

    def _ready_blueprint(db, view):
        blueprint = view.get("blueprint")
        if blueprint and blueprint.get("id") and repair_blueprint_seats(db, blueprint["id"]):
            db.commit()
            if view.get("mode") == "template" and blueprint.get("slug"):
                view["blueprint"] = template_by_slug(db, blueprint["slug"])
            elif view.get("year"):
                view["blueprint"] = _period_view(db, view["year"])["blueprint"]
        return view

    def _view(db):
        year = _year()
        if year:
            return _period_view(db, year)
        slug = _slug()
        if slug:
            return _template_view(db, slug)
        return {
            "mode": "period",
            "year": None,
            "editable": False,
            "blueprint": None,
            "uses_template": False,
        }

    def _guard_edit(db, blueprint_id: int):
        view = _view(db)
        current = view["blueprint"]
        if not view["editable"] or not current or current.get("id") != blueprint_id:
            abort(400)
        return view

    def _scope(db, view, years, custom_years):
        """Siapa yang ikut berubah. Dipakai banner supaya cakupan tidak ditebak.

        Pengurus sering keliru mengira mengubah satu tahun padahal sedang
        mengubah pola dasar, jadi cakupannya disebut dengan nama periode.
        """
        if view["mode"] == "period":
            return {
                "kind": "period_custom" if view["editable"] else "period_template",
                "following": [],
                "copies": [],
            }
        blueprint = view["blueprint"] or {}
        if blueprint.get("is_default"):
            return {
                "kind": "template_default",
                "following": [],
                "copies": [],
            }
        copies = []
        if blueprint.get("id"):
            copies = [
                format_period(row["period_start"], row["period_start"] + 1)
                for row in db.execute(
                    """
                    SELECT period_start FROM org_blueprints
                    WHERE kind = 'period' AND copied_from_id = ?
                      AND period_start IS NOT NULL
                    ORDER BY period_start DESC
                    """,
                    (blueprint["id"],),
                )
            ]
        return {"kind": "template_spare", "following": [], "copies": copies}

    def _editor_unused(db, view):
        blueprint = view["blueprint"]
        if not (blueprint and view["editable"]):
            return {}
        return {
            unit["id"]: unused_offices_for_unit(db, unit["id"])
            for unit in blueprint.get("units") or []
        }

    def _period_nav(db, current_year=None):
        custom_years = set(list_period_layouts(db))
        years = sorted(set(role_periods(db)) | custom_years, reverse=True)
        periods = [
            {
                "year": year,
                "label": format_period(year, year + 1),
                "is_custom": year in custom_years,
            }
            for year in years
        ]
        return years, custom_years, periods

    @app.route("/admin/struktur")
    @admin_required
    def admin_org():
        if request.args.get("acuan"):
            return redirect(url_for("admin_acuan", acuan=request.args.get("acuan")))
        db = get_db()
        ensure_org_layout(db)
        years, custom_years, periods = _period_nav(db, _year())
        year = _year() or (years[0] if years else None)
        view = _period_view(db, year) if year else {
            "mode": "period",
            "year": None,
            "editable": False,
            "blueprint": None,
            "uses_template": False,
        }
        view = _ready_blueprint(db, view)
        return render_template(
            "admin/struktur.html",
            view=view,
            blueprint=view["blueprint"],
            periods=periods,
            templates=list_templates(db),
            default_slug=default_template_slug(db),
            scope=_scope(db, view, years, custom_years),
            unused=_editor_unused(db, view),
            unit_kinds=UNIT_KIND_LABELS,
            seat_kinds=SEAT_KIND_LABELS,
            protected_offices=PROTECTED_OFFICES,
            offices=get_offices(db),
        )

    @app.route("/admin/template")
    @app.route("/admin/acuan")
    @admin_required
    def admin_acuan():
        if request.args.get("periode"):
            return redirect(url_for("admin_org", periode=request.args.get("periode")))
        db = get_db()
        ensure_org_layout(db)
        requested = (request.args.get("acuan") or "").strip()
        slug = requested or default_template_slug(db)
        view = _ready_blueprint(db, _template_view(db, slug))
        current = (view["blueprint"] or {}).get("slug")
        if requested and current and requested != current:
            return redirect(url_for("admin_acuan", acuan=current))
        years, custom_years, _periods = _period_nav(db)
        return render_template(
            "admin/acuan.html",
            view=view,
            blueprint=view["blueprint"],
            templates=list_templates(db),
            default_slug=default_template_slug(db),
            scope=_scope(db, view, years, custom_years),
            unused=_editor_unused(db, view),
            unit_kinds=UNIT_KIND_LABELS,
            seat_kinds=SEAT_KIND_LABELS,
            protected_offices=PROTECTED_OFFICES,
            offices=get_offices(db),
        )

    @app.route("/admin/template/baru", methods=["POST"])
    @app.route("/admin/acuan/baru", methods=["POST"])
    @admin_required
    def admin_template_new():
        if not csrf_ok():
            abort(400)
        db = get_db()
        blueprint, message = create_template(
            db,
            request.form.get("title") or "",
            request.form.get("sumber") or "",
        )
        if blueprint is None:
            flash(message, "err")
            return redirect(url_for("admin_acuan"))
        audit("org_template_create", blueprint["slug"])
        db.commit()
        flash(message, "ok")
        return redirect(url_for("admin_acuan", acuan=blueprint["slug"]))

    @app.route("/admin/template/bawaan", methods=["POST"])
    @app.route("/admin/acuan/bawaan", methods=["POST"])
    @admin_required
    def admin_template_default():
        if not csrf_ok():
            abort(400)
        db = get_db()
        slug = _slug()
        ok, message = set_default_template(db, slug)
        if ok:
            audit("org_template_default", slug)
            db.commit()
            flash(message, "ok")
        else:
            flash(message, "err")
        return redirect(url_for("admin_acuan", acuan=slug) if slug else url_for("admin_acuan"))

    @app.route("/admin/template/ubah", methods=["POST"])
    @app.route("/admin/acuan/ubah", methods=["POST"])
    @admin_required
    def admin_template_rename():
        if not csrf_ok():
            abort(400)
        db = get_db()
        slug = _slug()
        ok, message = rename_template(
            db,
            slug,
            request.form.get("title") or "",
            request.form.get("notes") or "",
        )
        if ok:
            audit("org_template_rename", slug)
            db.commit()
            flash(message, "ok")
        else:
            flash(message, "err")
        return redirect(url_for("admin_acuan", acuan=slug) if slug else url_for("admin_acuan"))

    @app.route("/admin/template/hapus", methods=["POST"])
    @app.route("/admin/acuan/hapus", methods=["POST"])
    @admin_required
    def admin_template_delete():
        if not csrf_ok():
            abort(400)
        db = get_db()
        slug = _slug()
        ok, message = delete_template(db, slug)
        if ok:
            audit("org_template_delete", slug)
            db.commit()
            flash(message, "ok")
            return redirect(url_for("admin_acuan"))
        flash(message, "err")
        return redirect(url_for("admin_acuan", acuan=slug) if slug else url_for("admin_acuan"))

    @app.route("/admin/struktur/salin", methods=["POST"])
    @admin_required
    def admin_org_copy():
        if not csrf_ok():
            abort(400)
        year = _year()
        if not year:
            flash("Pilih tahun yang mau disesuaikan.", "err")
            return redirect(url_for("admin_org"))
        db = get_db()
        source = (request.form.get("sumber") or default_template_slug(db)).strip()
        replacing = bool(period_blueprint(db, year))
        customize_period(db, year, source, replace=replacing)
        audit("org_layout_copy" if not replacing else "org_layout_replace", f"{year}:{source}")
        db.commit()
        if replacing:
            flash(
                f"Bagan {year}/{year + 1} diganti dengan template yang dipilih. "
                "Penyesuaian sebelumnya untuk tahun ini tidak dipakai lagi.",
                "ok",
            )
        else:
            flash(
                f"Bagan {year}/{year + 1} disiapkan. Perubahan berikutnya hanya berlaku untuk periode ini.",
                "ok",
            )
        return redirect(url_for("admin_org", periode=year))

    @app.route("/admin/struktur/reset", methods=["POST"])
    @admin_required
    def admin_org_reset():
        if not csrf_ok():
            abort(400)
        year = _year()
        if not year:
            flash("Periode tidak dikenali.", "err")
            return redirect(url_for("admin_org"))
        db = get_db()
        if reset_period(db, year):
            audit("org_layout_reset", str(year))
            db.commit()
            flash(
                f"Periode {year}/{year + 1} diganti dengan salinan template bawaan yang berlaku sekarang.",
                "ok",
            )
        else:
            flash("Periode itu memang belum punya bagan sendiri.", "err")
        return redirect(url_for("admin_org", periode=year))

    @app.route("/admin/struktur/unit", methods=["POST"])
    @admin_required
    def admin_org_add_unit():
        if not csrf_ok():
            abort(400)
        db = get_db()
        view = _view(db)
        if not view["editable"] or not view["blueprint"]:
            flash("Sesuaikan dulu periode ini sebelum menambah unit.", "err")
            return redirect(_back())
        message = add_standard_unit(
            db,
            view["blueprint"]["id"],
            title=request.form.get("title") or "",
            unit_kind=request.form.get("unit_kind") or "division",
            lead_role=request.form.get("lead_role") or "",
        )
        audit("org_unit_add", message)
        db.commit()
        flash(message, "ok" if "ditambahkan" in message else "err")
        return redirect(_back())

    @app.route("/admin/struktur/unit/<int:unit_id>", methods=["POST"])
    @admin_required
    def admin_org_update_unit(unit_id: int):
        if not csrf_ok():
            abort(400)
        db = get_db()
        unit = db.execute("SELECT blueprint_id FROM org_units WHERE id = ?", (unit_id,)).fetchone()
        if unit is None:
            abort(404)
        _guard_edit(db, unit["blueprint_id"])
        visible = request.form.get("is_visible")
        message = update_unit(
            db,
            unit_id,
            title=request.form.get("title"),
            lead_role=request.form.get("lead_role"),
            unit_kind=request.form.get("unit_kind") or None,
            is_visible=None if visible is None else visible == "1",
        )
        db.commit()
        flash(message, "ok" if "diperbarui" in message else "err")
        return redirect(_back(unit_id=unit_id))

    @app.route("/admin/struktur/unit/<int:unit_id>/hapus", methods=["POST"])
    @admin_required
    def admin_org_delete_unit(unit_id: int):
        if not csrf_ok():
            abort(400)
        db = get_db()
        unit = db.execute("SELECT blueprint_id FROM org_units WHERE id = ?", (unit_id,)).fetchone()
        if unit is None:
            abort(404)
        _guard_edit(db, unit["blueprint_id"])
        message = delete_unit(db, unit_id)
        db.commit()
        flash(message, "ok" if "dihapus" in message else "err")
        return redirect(_back())

    @app.route("/admin/struktur/unit/<int:unit_id>/urut", methods=["POST"])
    @admin_required
    def admin_org_move_unit(unit_id: int):
        if not csrf_ok():
            abort(400)
        db = get_db()
        unit = db.execute("SELECT blueprint_id FROM org_units WHERE id = ?", (unit_id,)).fetchone()
        if unit is None:
            abort(404)
        _guard_edit(db, unit["blueprint_id"])
        message = move_unit(db, unit_id, request.form.get("arah") or "up")
        db.commit()
        flash(message, "ok" if "diperbarui" in message else "err")
        return redirect(_back(unit_id=unit_id))

    @app.route("/admin/struktur/jabatan", methods=["POST"])
    @admin_required
    def admin_org_add_seat():
        if not csrf_ok():
            abort(400)
        db = get_db()
        unit_id = clamp_int(request.form.get("unit_id"), 1, 1_000_000, 0)
        unit = db.execute("SELECT blueprint_id FROM org_units WHERE id = ?", (unit_id,)).fetchone()
        if unit is None:
            abort(404)
        _guard_edit(db, unit["blueprint_id"])
        existing = (request.form.get("office_code") or "").strip()
        seat_kind, parent_id = _place_from_form()
        if existing:
            message = add_existing_seat(
                db,
                unit_id,
                existing,
                seat_kind=seat_kind,
                parent_seat_id=parent_id,
            )
        else:
            message = add_custom_seat(
                db,
                unit_id,
                label=request.form.get("label") or "",
                short=request.form.get("short") or "",
                kind=seat_kind or "officer",
                parent_seat_id=parent_id,
            )
        db.commit()
        flash(message, "ok" if "ditambahkan" in message else "err")
        return redirect(_back(unit_id=unit_id))

    @app.route("/admin/struktur/jabatan/<int:seat_id>", methods=["POST"])
    @admin_required
    def admin_org_update_seat(seat_id: int):
        if not csrf_ok():
            abort(400)
        db = get_db()
        seat = db.execute(
            """
            SELECT u.blueprint_id FROM org_seats s
            JOIN org_units u ON u.id = s.unit_id
            WHERE s.id = ?
            """,
            (seat_id,),
        ).fetchone()
        if seat is None:
            abort(404)
        _guard_edit(db, seat["blueprint_id"])
        message = update_seat(
            db,
            seat_id,
            label=request.form.get("label"),
            short=request.form.get("short"),
        )
        db.commit()
        flash(message, "ok" if "diperbarui" in message else "err")
        return redirect(_back(seat_id=seat_id))

    @app.route("/admin/struktur/jabatan/<int:seat_id>/hapus", methods=["POST"])
    @admin_required
    def admin_org_delete_seat(seat_id: int):
        if not csrf_ok():
            abort(400)
        db = get_db()
        seat = db.execute(
            """
            SELECT s.unit_id, u.blueprint_id FROM org_seats s
            JOIN org_units u ON u.id = s.unit_id
            WHERE s.id = ?
            """,
            (seat_id,),
        ).fetchone()
        if seat is None:
            abort(404)
        _guard_edit(db, seat["blueprint_id"])
        unit_id = seat["unit_id"]
        message = delete_seat(db, seat_id)
        db.commit()
        flash(message, "ok" if "dilepas" in message else "err")
        return redirect(_back(unit_id=unit_id))

    @app.route("/admin/struktur/jabatan/<int:seat_id>/urut", methods=["POST"])
    @admin_required
    def admin_org_move_seat(seat_id: int):
        if not csrf_ok():
            abort(400)
        db = get_db()
        seat = db.execute(
            """
            SELECT u.blueprint_id FROM org_seats s
            JOIN org_units u ON u.id = s.unit_id
            WHERE s.id = ?
            """,
            (seat_id,),
        ).fetchone()
        if seat is None:
            abort(404)
        _guard_edit(db, seat["blueprint_id"])
        message = move_seat(db, seat_id, request.form.get("arah") or "up")
        db.commit()
        flash(message, "ok" if "diperbarui" in message else "err")
        return redirect(_back(seat_id=seat_id))
