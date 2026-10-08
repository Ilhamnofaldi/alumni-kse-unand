"""Rute keanggotaan: daftar, klaim, profil, tinjau, undangan, pemulihan."""

from __future__ import annotations

import json
from functools import wraps

from flask import (
    Response,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import generate_password_hash

from .db import audit, get_db, utcnow
from .import_csv import template_csv_bytes
from .membership import (
    GENERIC_PENDING,
    GENERIC_RESET,
    REQUEST_KIND_LABELS,
    SOURCE_LABELS,
    active_admin_count,
    add_change_request,
    apply_email_change,
    apply_soft_profile,
    consume_recovery_code,
    create_user,
    generate_recovery_codes,
    insert_batch,
    issue_token,
    lookup_token,
    mark_token_used,
    parse_batch_lines,
    password_error,
    register_or_claim,
    resolve_request,
    review_counts,
    user_for_alumni,
)
from .normalize import normalize_email
from .quality import refresh_duplicate_flags
from .offices import (
    add_roles,
    apply_roles_text,
    delete_role,
    get_offices,
    list_roles,
    office_meta,
    parse_period,
)
from .security import client_key, rate_limited


def register(app, *, csrf_ok, admin_required):
    def alumni_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("login", next=request.path))
            if g.user["role"] != "alumni" or not g.user["alumni_id"]:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    def _values_from_form() -> dict[str, str]:
        return {
            "full_name": request.form.get("full_name", ""),
            "faculty": request.form.get("faculty", ""),
            "major": request.form.get("major", ""),
            "cohort_year": request.form.get("cohort_year", ""),
            "email": request.form.get("email", ""),
            "phone": request.form.get("phone", ""),
            "status": request.form.get("status", ""),
            "workplace": request.form.get("workplace", ""),
            "domicile": request.form.get("domicile", ""),
            "testimonial": request.form.get("testimonial", ""),
            "date_of_birth": request.form.get("date_of_birth", ""),
            "graduation_year": request.form.get("graduation_year", ""),
            "kse_last_year": request.form.get("kse_last_year", ""),
            "gender": request.form.get("gender", ""),
        }

    def _save_role(db, alumni_id: int) -> str:
        text = (request.form.get("roles_text") or "").strip()
        if text:
            added = apply_roles_text(db, alumni_id, text)
            if added:
                return f"{added} jabatan ditambahkan."
            return "Tidak ada jabatan yang dikenali dari isian itu."
        office = (request.form.get("office_code") or "").strip()
        offices = get_offices(db)
        if office not in offices:
            return "Pilih jabatan yang ada di struktur paguyuban."
        raw_period = (request.form.get("period") or "").strip()
        start, end, period_raw = parse_period(raw_period)
        if not start:
            return "Periode wajib. Contoh: 2023/2024. Jabatan menempel ke tahun kepengurusan itu."
        scope = (request.form.get("scope") or "").strip() or None
        if office_meta(office, db).get("needs_scope") and not scope:
            return "Penanggung jawab fakultas wajib memilih fakultas."
        if office != "pj_fakultas":
            scope = None
        added = add_roles(
            db,
            alumni_id,
            {
                "office_code": office,
                "period_start": start,
                "period_end": end,
                "period_raw": period_raw or raw_period or None,
                "scope": scope,
                "title_raw": offices[office]["label"],
            },
        )
        if added == 1:
            return "Jabatan ditambahkan."
        if added > 1:
            return f"{added} jabatan ditambahkan."
        return "Jabatan itu sudah tercatat untuk periode yang sama."

    def _reveal(kind: str, items: list[str], note: str):
        session["reveal"] = {"kind": kind, "entries": items, "note": note}
        return redirect(url_for("admin_reveal"))

    def _public_url(endpoint: str, **values) -> str:
        """Tautan absolut untuk disalin keluar (WA/email). Memakai APP_BASE_URL
        bila disetel; kalau tidak, host dari permintaan yang sedang berjalan."""
        base = current_app.config["APP_BASE_URL"]
        if base:
            return base + url_for(endpoint, **values)
        return url_for(endpoint, _external=True, **values)

    def _own_gaps(alumni) -> dict[str, bool]:
        city = (alumni["city"] or "").strip() if alumni["city"] else ""
        return {
            "faculty": not alumni["faculty_code"],
            "major": not (alumni["major_normalized"] or alumni["major_raw"]),
            "cohort": not alumni["cohort_year"],
            "gender": not alumni["gender"],
            "city": not city,
        }

    def _render_own(alumni, pending=None, status=200):
        html = render_template(
            "own_profile.html",
            alumni=alumni,
            pending=pending or [],
            roles=list_roles(get_db(), alumni["id"]),
            gaps=_own_gaps(alumni),
            kind_labels=REQUEST_KIND_LABELS,
        )
        return (html, status) if status != 200 else html

    @app.route("/daftar", methods=["GET", "POST"])
    def register_alumni():
        if g.user is not None:
            return redirect(url_for("home"))
        if request.method == "POST":
            if not csrf_ok():
                abort(400)
            if rate_limited(f"register:{client_key(request)}"):
                flash("Terlalu banyak percobaan. Coba lagi nanti.", "err")
                return render_template("register.html"), 429
            password = request.form.get("password") or ""
            err = password_error(password)
            if err:
                flash(err, "err")
                return render_template("register.html")
            if not (request.form.get("full_name") or "").strip():
                flash("Nama wajib diisi.", "err")
                return render_template("register.html")
            if not normalize_email(request.form.get("email")):
                flash("Email wajib diisi.", "err")
                return render_template("register.html")
            password_hash = generate_password_hash(password)
            db = get_db()
            register_or_claim(
                db,
                values=_values_from_form(),
                password_hash=password_hash,
                ip=client_key(request),
                allow_new=True,
            )
            db.commit()
            app.logger.info("permintaan daftar ip=%s", client_key(request))
            flash(GENERIC_PENDING, "ok")
            return redirect(url_for("login"))
        return render_template("register.html")

    @app.route("/klaim", methods=["GET", "POST"])
    def claim_profile():
        if g.user is not None:
            return redirect(url_for("home"))
        if request.method == "POST":
            if not csrf_ok():
                abort(400)
            if rate_limited(f"claim:{client_key(request)}"):
                flash("Terlalu banyak percobaan. Coba lagi nanti.", "err")
                return render_template("claim.html"), 429
            password = request.form.get("password") or ""
            err = password_error(password)
            if err:
                flash(err, "err")
                return render_template("claim.html")
            password_hash = generate_password_hash(password)
            db = get_db()
            register_or_claim(
                db,
                values=_values_from_form(),
                password_hash=password_hash,
                ip=client_key(request),
                allow_new=False,
            )
            db.commit()
            app.logger.info("permintaan klaim ip=%s", client_key(request))
            flash(GENERIC_PENDING, "ok")
            return redirect(url_for("login"))
        return render_template("claim.html")

    @app.route("/lupa-sandi", methods=["GET", "POST"])
    def forgot_password():
        if request.method == "POST":
            if not csrf_ok():
                abort(400)
            if rate_limited(f"forgot:{client_key(request)}"):
                flash("Terlalu banyak percobaan. Coba lagi nanti.", "err")
                return render_template("forgot.html"), 429
            email = normalize_email(request.form.get("email"))
            db = get_db()
            user = (
                db.execute(
                    "SELECT * FROM users WHERE email = ? AND role = 'alumni' AND status = 'active'",
                    (email,),
                ).fetchone()
                if email
                else None
            )
            if user and user["alumni_id"]:
                add_change_request(
                    db,
                    alumni_id=user["alumni_id"],
                    user_id=user["id"],
                    kind="reset",
                    payload={},
                )
                audit("password_reset_request", f"user={user['id']}")
                db.commit()
            app.logger.info("permintaan lupa sandi ip=%s", client_key(request))
            flash(GENERIC_RESET, "ok")
            return redirect(url_for("login"))
        return render_template("forgot.html")

    @app.route("/undang/<token>", methods=["GET", "POST"])
    def invite_accept(token: str):
        db = get_db()
        row = lookup_token(db, token, "invite")
        if row is None or not row["alumni_id"]:
            abort(404)
        alumni = db.execute(
            "SELECT * FROM alumni WHERE id = ?", (row["alumni_id"],)
        ).fetchone()
        if alumni is None:
            abort(404)
        if request.method == "POST":
            if not csrf_ok():
                abort(400)
            if rate_limited(f"invite:{client_key(request)}"):
                flash("Terlalu banyak percobaan. Coba lagi nanti.", "err")
                return render_template("invite.html", alumni=alumni, token=token), 429
            password = request.form.get("password") or ""
            stored_email = alumni["email_normalized"]
            typed_email = normalize_email(request.form.get("email") or "")
            email = stored_email or typed_email
            if not email:
                flash("Email wajib diisi.", "err")
                return render_template("invite.html", alumni=alumni, token=token)
            err = password_error(password)
            if err:
                flash(err, "err")
                return render_template("invite.html", alumni=alumni, token=token)
            taken = db.execute(
                "SELECT id, alumni_id FROM users WHERE email = ?", (email,)
            ).fetchone()
            if taken and taken["alumni_id"] != alumni["id"]:
                flash("Email sudah dipakai akun lain.", "err")
                return render_template("invite.html", alumni=alumni, token=token)
            if not stored_email:
                err = apply_email_change(db, alumni["id"], email)
                if err:
                    flash(err, "err")
                    return render_template("invite.html", alumni=alumni, token=token)
            existing = user_for_alumni(db, alumni["id"])
            if existing is None and taken is None:
                create_user(
                    db,
                    email=email,
                    password_hash=generate_password_hash(password),
                    alumni_id=alumni["id"],
                    ip=client_key(request),
                    status="pending",
                )
            elif existing is not None:
                if existing["status"] == "disabled":
                    flash("Akun ini dinonaktifkan. Hubungi pengurus.", "err")
                    return render_template("invite.html", alumni=alumni, token=token)
                db.execute(
                    "UPDATE users SET password_hash = ?, email = ? WHERE id = ? AND status != 'disabled'",
                    (generate_password_hash(password), email, existing["id"]),
                )
            mark_token_used(db, row["id"])
            audit("invite_accepted", f"alumni={alumni['id']}")
            db.commit()
            flash("Profil disimpan. Pengurus akan memeriksa sebelum Anda bisa masuk.", "ok")
            return redirect(url_for("login"))
        return render_template("invite.html", alumni=alumni, token=token)

    @app.route("/pulih/<token>", methods=["GET", "POST"])
    def recover_password(token: str):
        db = get_db()
        row = lookup_token(db, token, "password_reset")
        if row is None or not row["user_id"]:
            abort(404)
        user = db.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
        if user is None or user["status"] != "active":
            abort(404)
        if request.method == "POST":
            if not csrf_ok():
                abort(400)
            if rate_limited(f"recover:{client_key(request)}"):
                flash("Terlalu banyak percobaan. Coba lagi nanti.", "err")
                return render_template("recover.html", token=token), 429
            baru = request.form.get("baru") or ""
            ulang = request.form.get("ulang") or ""
            err = password_error(baru)
            if err:
                flash(err, "err")
                return render_template("recover.html", token=token)
            if baru != ulang:
                flash("Ulangi kata sandi belum sama.", "err")
                return render_template("recover.html", token=token)
            db.execute(
                "UPDATE users SET password_hash = ? WHERE id = ? AND status = 'active'",
                (generate_password_hash(baru), user["id"]),
            )
            mark_token_used(db, row["id"])
            audit("password_reset_ok", f"user={user['id']}")
            db.commit()
            session.clear()
            flash("Kata sandi diganti. Masuk kembali.", "ok")
            return redirect(url_for("login"))
        return render_template("recover.html", token=token)

    @app.route("/pulih-pengurus", methods=["GET", "POST"])
    def recover_admin():
        if request.method == "POST":
            if not csrf_ok():
                abort(400)
            if rate_limited(f"admin-recover:{client_key(request)}"):
                flash("Terlalu banyak percobaan. Coba lagi nanti.", "err")
                return render_template("recover_admin.html"), 429
            email = (request.form.get("email") or "").strip().lower()
            code = request.form.get("code") or ""
            baru = request.form.get("baru") or ""
            ulang = request.form.get("ulang") or ""
            password_hash = generate_password_hash(baru or "placeholder-timing")
            db = get_db()
            err = password_error(baru)
            if err or baru != ulang:
                consume_recovery_code(db, "bukan@akun.invalid", "bukan-kode")
                db.commit()
                flash("Email, kode pemulih, atau kata sandi baru tidak cocok.", "err")
                return render_template("recover_admin.html")
            user = consume_recovery_code(db, email, code)
            if user is not None:
                db.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ? AND status = 'active'",
                    (password_hash, user["id"]),
                )
                audit("admin_recovery_ok", f"user={user['id']}")
                db.commit()
                session.clear()
                flash("Kata sandi pengurus diganti. Masuk kembali.", "ok")
                return redirect(url_for("login"))
            db.commit()
            flash("Email, kode pemulih, atau kata sandi baru tidak cocok.", "err")
        return render_template("recover_admin.html")

    @app.route("/profil/saya", methods=["GET", "POST"])
    @alumni_required
    def own_profile():
        db = get_db()
        alumni = db.execute(
            "SELECT * FROM alumni WHERE id = ?", (g.user["alumni_id"],)
        ).fetchone()
        if alumni is None:
            abort(404)
        if request.method == "POST":
            if not csrf_ok():
                abort(400)
            if rate_limited(f"profile:{g.user['id']}", limit=20, window=900):
                flash("Terlalu banyak percobaan. Coba lagi nanti.", "err")
                return _render_own(alumni, [], 429)
            err = apply_soft_profile(db, alumni["id"], _values_from_form())
            if err:
                flash(err, "err")
                return _render_own(alumni, [])
            audit("profile_self_update", f"alumni={alumni['id']}")
            db.commit()
            flash("Profil disimpan.", "ok")
            return redirect(url_for("own_profile"))
        pending = db.execute(
            """
            SELECT kind, payload, created_at FROM change_requests
            WHERE alumni_id = ? AND status = 'pending'
            ORDER BY created_at DESC
            """,
            (alumni["id"],),
        ).fetchall()
        return _render_own(alumni, pending)

    @app.route("/profil/saya/jabatan", methods=["POST"])
    @alumni_required
    def own_add_role():
        if not csrf_ok():
            abort(400)
        if rate_limited(f"profile:{g.user['id']}", limit=20, window=900):
            flash("Terlalu banyak percobaan. Coba lagi nanti.", "err")
            return redirect(url_for("own_profile"))
        db = get_db()
        message = _save_role(db, g.user["alumni_id"])
        kind = "ok" if message.endswith("ditambahkan.") else "err"
        if kind == "ok":
            audit("role_self_add", f"alumni={g.user['alumni_id']}")
        db.commit()
        flash(message, kind)
        return redirect(url_for("own_profile"))

    @app.route("/profil/saya/jabatan/<int:role_id>/hapus", methods=["POST"])
    @alumni_required
    def own_delete_role(role_id: int):
        if not csrf_ok():
            abort(400)
        db = get_db()
        if delete_role(db, role_id, g.user["alumni_id"]):
            audit("role_self_delete", f"alumni={g.user['alumni_id']} role={role_id}")
            flash("Jabatan dihapus.", "ok")
        else:
            flash("Jabatan tidak ditemukan.", "err")
        db.commit()
        return redirect(url_for("own_profile"))

    @app.route("/admin/alumni/<int:alumni_id>/jabatan", methods=["POST"])
    @admin_required
    def admin_add_role(alumni_id: int):
        if not csrf_ok():
            abort(400)
        db = get_db()
        row = db.execute("SELECT id FROM alumni WHERE id = ?", (alumni_id,)).fetchone()
        if row is None:
            abort(404)
        message = _save_role(db, alumni_id)
        kind = "ok" if "ditambahkan" in message else "err"
        if kind == "ok":
            audit("role_add", f"alumni={alumni_id}")
        db.commit()
        flash(message, kind)
        return redirect(url_for("admin_edit", alumni_id=alumni_id))

    @app.route("/admin/alumni/<int:alumni_id>/jabatan/<int:role_id>/hapus", methods=["POST"])
    @admin_required
    def admin_delete_role(alumni_id: int, role_id: int):
        if not csrf_ok():
            abort(400)
        db = get_db()
        if delete_role(db, role_id, alumni_id):
            audit("role_delete", f"alumni={alumni_id} role={role_id}")
            flash("Jabatan dihapus.", "ok")
        else:
            flash("Jabatan tidak ditemukan.", "err")
        db.commit()
        return redirect(url_for("admin_edit", alumni_id=alumni_id))

    @app.route("/profil/saya/email", methods=["POST"])
    @alumni_required
    def own_email_change():
        if not csrf_ok():
            abort(400)
        email = normalize_email(request.form.get("email"))
        if not email:
            flash("Email baru tidak valid.", "err")
            return redirect(url_for("own_profile"))
        db = get_db()
        add_change_request(
            db,
            alumni_id=g.user["alumni_id"],
            user_id=g.user["id"],
            kind="email",
            payload={"email": email},
        )
        audit("email_change_request", f"alumni={g.user['alumni_id']}")
        db.commit()
        flash("Permintaan ganti email diteruskan ke pengurus.", "ok")
        return redirect(url_for("own_profile"))

    @app.route("/profil/saya/sembunyikan", methods=["POST"])
    @alumni_required
    def own_hide():
        if not csrf_ok():
            abort(400)
        db = get_db()
        db.execute(
            "UPDATE alumni SET hide_requested = 1, updated_at = ? WHERE id = ?",
            (utcnow(), g.user["alumni_id"]),
        )
        add_change_request(
            db,
            alumni_id=g.user["alumni_id"],
            user_id=g.user["id"],
            kind="hide",
            payload={},
        )
        audit("hide_request", f"alumni={g.user['alumni_id']}")
        db.commit()
        flash("Permintaan supaya nama tidak tampil di direktori dikirim ke pengurus.", "ok")
        return redirect(url_for("own_profile"))

    @app.route("/profil/saya/koreksi", methods=["POST"])
    @alumni_required
    def own_identity_fix():
        if not csrf_ok():
            abort(400)
        note = (request.form.get("note") or "").strip()
        if len(note) < 8:
            flash("Jelaskan koreksi yang dibutuhkan, minimal beberapa kata.", "err")
            return redirect(url_for("own_profile"))
        db = get_db()
        add_change_request(
            db,
            alumni_id=g.user["alumni_id"],
            user_id=g.user["id"],
            kind="identity",
            payload={"note": note[:2000]},
        )
        audit("identity_fix_request", f"alumni={g.user['alumni_id']}")
        db.commit()
        flash("Permintaan koreksi identitas diteruskan ke pengurus.", "ok")
        return redirect(url_for("own_profile"))

    @app.route("/admin/tinjau")
    @admin_required
    def admin_review():
        db = get_db()
        pending_users = db.execute(
            """
            SELECT u.id, u.email, u.role, u.status, u.created_at, u.request_ip,
                   u.alumni_id, a.full_name, a.faculty_code, a.cohort_year,
                   a.is_listed, a.source, a.phone, a.city
            FROM users u
            LEFT JOIN alumni a ON a.id = u.alumni_id
            WHERE u.status = 'pending'
            ORDER BY u.created_at DESC
            """
        ).fetchall()
        requests_ = db.execute(
            """
            SELECT r.id, r.kind, r.payload, r.created_at, r.alumni_id, r.user_id,
                   a.full_name, a.email AS alumni_email, u.email AS user_email
            FROM change_requests r
            JOIN alumni a ON a.id = r.alumni_id
            LEFT JOIN users u ON u.id = r.user_id
            WHERE r.status = 'pending'
            ORDER BY r.created_at DESC
            """
        ).fetchall()
        waiting = db.execute(
            """
            SELECT a.id, a.full_name, a.faculty_code, a.cohort_year, a.source,
                   a.email, a.phone, a.created_at
            FROM alumni a
            WHERE a.is_listed = 0 AND a.source IN ('self_register', 'batch')
              AND NOT EXISTS (
                SELECT 1 FROM users u WHERE u.alumni_id = a.id AND u.status = 'pending'
              )
            ORDER BY a.created_at DESC
            LIMIT 200
            """
        ).fetchall()
        waiting_total = db.execute(
            """
            SELECT COUNT(*) FROM alumni a
            WHERE a.is_listed = 0 AND a.source IN ('self_register', 'batch')
              AND NOT EXISTS (
                SELECT 1 FROM users u WHERE u.alumni_id = a.id AND u.status = 'pending'
              )
            """
        ).fetchone()[0]
        return render_template(
            "admin/review.html",
            pending_users=pending_users,
            requests=requests_,
            waiting=waiting,
            waiting_total=waiting_total,
            counts=review_counts(db),
            kind_labels=REQUEST_KIND_LABELS,
            source_labels=SOURCE_LABELS,
        )

    @app.route("/admin/tinjau/akun/<int:user_id>/<action>", methods=["POST"])
    @admin_required
    def admin_review_user(user_id: int, action: str):
        if not csrf_ok():
            abort(400)
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if user is None or user["role"] == "admin":
            abort(404)
        if action == "setujui-tampil":
            db.execute("UPDATE users SET status = 'active' WHERE id = ?", (user_id,))
            if user["alumni_id"]:
                db.execute(
                    """
                    UPDATE alumni
                    SET is_listed = 1, hide_requested = 0, updated_at = ?
                    WHERE id = ?
                    """,
                    (utcnow(), user["alumni_id"]),
                )
                named = db.execute(
                    "SELECT name_normalized FROM alumni WHERE id = ?",
                    (user["alumni_id"],),
                ).fetchone()
                if named:
                    refresh_duplicate_flags(db, [named["name_normalized"]])
            flash("Akun disetujui dan nama ditampilkan di direktori.", "ok")
        elif action == "setujui":
            db.execute("UPDATE users SET status = 'active' WHERE id = ?", (user_id,))
            flash("Akun disetujui. Nama belum ditampilkan di direktori.", "ok")
        elif action in ("tolak", "tolak-hapus"):
            alumni_id = user["alumni_id"]
            db.execute(
                "DELETE FROM users WHERE id = ? AND status = 'pending'", (user_id,)
            )
            deleted_row = False
            if alumni_id:
                row = db.execute(
                    "SELECT source, is_listed FROM alumni WHERE id = ?",
                    (alumni_id,),
                ).fetchone()
                if row and row["is_listed"] == 0 and row["source"] == "self_register":
                    named = db.execute(
                        "SELECT name_normalized FROM alumni WHERE id = ?",
                        (alumni_id,),
                    ).fetchone()
                    db.execute("DELETE FROM alumni WHERE id = ?", (alumni_id,))
                    if named:
                        refresh_duplicate_flags(db, [named["name_normalized"]])
                    deleted_row = True
            flash(
                "Permintaan ditolak dan data pendaftaran dihapus."
                if deleted_row
                else "Permintaan akun ditolak.",
                "ok",
            )
        else:
            abort(404)
        audit(f"review_user_{action}", f"user={user_id}")
        db.commit()
        app.logger.info("tinjau akun %s oleh admin=%s target=%s", action, g.user["id"], user_id)
        return redirect(url_for("admin_review"))

    @app.route("/admin/tinjau/permintaan/<int:req_id>/<action>", methods=["POST"])
    @admin_required
    def admin_review_request(req_id: int, action: str):
        if not csrf_ok():
            abort(400)
        db = get_db()
        if action == "setujui":
            row = resolve_request(db, req_id, "approved", g.user["id"])
            if row is None:
                abort(404)
            payload = {}
            try:
                payload = json.loads(row["payload"] or "{}")
            except json.JSONDecodeError:
                payload = {}
            if row["kind"] == "email":
                err = apply_email_change(db, row["alumni_id"], payload.get("email") or "")
                if err:
                    flash(err, "err")
                    db.commit()
                    return redirect(url_for("admin_review"))
            elif row["kind"] == "hide":
                named = db.execute(
                    "SELECT name_normalized FROM alumni WHERE id = ?",
                    (row["alumni_id"],),
                ).fetchone()
                db.execute(
                    """
                    UPDATE alumni
                    SET is_listed = 0, hide_requested = 1, updated_at = ?
                    WHERE id = ?
                    """,
                    (utcnow(), row["alumni_id"]),
                )
                if named:
                    refresh_duplicate_flags(db, [named["name_normalized"]])
            elif row["kind"] == "reset":
                user_id = row["user_id"]
                if user_id:
                    raw = issue_token(
                        db,
                        purpose="password_reset",
                        alumni_id=row["alumni_id"],
                        user_id=user_id,
                        created_by=g.user["id"],
                    )
                    link = _public_url("recover_password", token=raw)
                    audit("review_request_approved", f"id={req_id} kind={row['kind']}")
                    db.commit()
                    return _reveal(
                        "Tautan pemulihan kata sandi",
                        [link],
                        "Sampaikan tautan ini lewat WhatsApp paguyuban. Berlaku 14 hari, sekali pakai.",
                    )
            elif row["kind"] == "identity":
                note = (payload.get("note") or "").strip()
                audit("review_request_approved", f"id={req_id} kind=identity")
                db.commit()
                flash(
                    "Permintaan koreksi disetujui. Terapkan perubahannya di form ubah."
                    + (f" Catatan: {note[:400]}" if note else ""),
                    "ok",
                )
                return redirect(url_for("admin_edit", alumni_id=row["alumni_id"]))
            flash("Permintaan disetujui.", "ok")
        elif action == "tolak":
            row = resolve_request(db, req_id, "rejected", g.user["id"])
            if row is None:
                abort(404)
            flash("Permintaan ditolak.", "ok")
        elif action == "tautkan-pulih":
            row = db.execute(
                "SELECT * FROM change_requests WHERE id = ?", (req_id,)
            ).fetchone()
            if row is None or row["kind"] != "reset":
                abort(404)
            if not row["user_id"]:
                abort(404)
            raw = issue_token(
                db,
                purpose="password_reset",
                alumni_id=row["alumni_id"],
                user_id=row["user_id"],
                created_by=g.user["id"],
            )
            link = _public_url("recover_password", token=raw)
            resolve_request(db, req_id, "approved", g.user["id"])
            audit("review_request_tautkan_pulih", f"id={req_id}")
            db.commit()
            return _reveal(
                "Tautan pemulihan kata sandi",
                [link],
                "Sampaikan tautan ini lewat WhatsApp paguyuban. Berlaku 14 hari, sekali pakai.",
            )
        else:
            abort(404)
        audit(f"review_request_{action}", f"id={req_id}")
        db.commit()
        return redirect(url_for("admin_review"))

    @app.route("/admin/tinjau/alumni/<int:alumni_id>/tampilkan", methods=["POST"])
    @admin_required
    def admin_list_alumni(alumni_id: int):
        if not csrf_ok():
            abort(400)
        db = get_db()
        named = db.execute(
            "SELECT name_normalized FROM alumni WHERE id = ?", (alumni_id,)
        ).fetchone()
        db.execute(
            """
            UPDATE alumni
            SET is_listed = 1, hide_requested = 0, updated_at = ?
            WHERE id = ?
            """,
            (utcnow(), alumni_id),
        )
        if named:
            refresh_duplicate_flags(db, [named["name_normalized"]])
        audit("alumni_list", f"id={alumni_id}")
        db.commit()
        flash("Nama ditampilkan di direktori.", "ok")
        return redirect(url_for("admin_review"))

    @app.route("/admin/reveal")
    @admin_required
    def admin_reveal():
        payload = session.pop("reveal", None)
        if not payload:
            flash("Tidak ada tautan untuk ditampilkan. Buat ulang dari panel tinjau.", "warn")
            return redirect(url_for("admin_review"))
        return render_template("admin/reveal.html", reveal=payload)

    @app.route("/admin/akun/pengurus", methods=["POST"])
    @admin_required
    def admin_create_pengurus():
        if not csrf_ok():
            abort(400)
        email = normalize_email(request.form.get("email"))
        password = request.form.get("password") or ""
        err = password_error(password)
        if not email:
            flash("Email pengurus tidak valid.", "err")
            return redirect(url_for("admin_accounts"))
        if err:
            flash(err, "err")
            return redirect(url_for("admin_accounts"))
        db = get_db()
        created = create_user(
            db,
            email=email,
            password_hash=generate_password_hash(password),
            alumni_id=None,
            ip=client_key(request),
            role="admin",
            status="active",
        )
        if created is None:
            flash("Email itu sudah terpakai.", "err")
            db.commit()
            return redirect(url_for("admin_accounts"))
        audit("admin_create", f"user={created} email={email}")
        db.commit()
        flash("Pengurus baru dibuat. Sampaikan sandi lewat jalur yang aman, bukan lewat chat publik.", "ok")
        return redirect(url_for("admin_accounts"))

    @app.route("/admin/akun/<int:user_id>/sandi", methods=["POST"])
    @admin_required
    def admin_set_password(user_id: int):
        if not csrf_ok():
            abort(400)
        password = request.form.get("password") or ""
        err = password_error(password)
        if err:
            flash(err, "err")
            return redirect(url_for("admin_accounts"))
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if user is None:
            abort(404)
        if user["role"] == "admin" and user["id"] != g.user["id"]:
            flash("Sandi pengurus lain hanya bisa diganti oleh orangnya, CLI, atau kode pemulih.", "err")
            return redirect(url_for("admin_accounts"))
        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(password), user_id),
        )
        audit("admin_set_password", f"user={user_id}")
        db.commit()
        flash("Kata sandi sementara disetel. Sampaikan langsung kepada yang bersangkutan.", "ok")
        return redirect(url_for("admin_accounts"))

    @app.route("/admin/akun/<int:user_id>/nonaktif-pengurus", methods=["POST"])
    @admin_required
    def admin_disable_pengurus(user_id: int):
        if not csrf_ok():
            abort(400)
        if user_id == g.user["id"]:
            flash("Tidak bisa menonaktifkan akun Anda sendiri.", "err")
            return redirect(url_for("admin_accounts"))
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if user is None or user["role"] != "admin":
            abort(404)
        if active_admin_count(db) <= 1:
            flash("Tidak bisa menonaktifkan pengurus terakhir.", "err")
            return redirect(url_for("admin_accounts"))
        db.execute("UPDATE users SET status = 'disabled' WHERE id = ?", (user_id,))
        audit("admin_disable", f"user={user_id}")
        db.commit()
        flash("Pengurus dinonaktifkan.", "ok")
        return redirect(url_for("admin_accounts"))

    @app.route("/admin/akun/kode-pemulih", methods=["POST"])
    @admin_required
    def admin_recovery_codes():
        if not csrf_ok():
            abort(400)
        db = get_db()
        codes = generate_recovery_codes(db, g.user["id"])
        audit("recovery_codes_generated", f"user={g.user['id']}")
        db.commit()
        return _reveal(
            "Kode pemulih pengurus",
            codes,
            "Simpan di tempat aman, terpisah dari sandi. Setiap kode sekali pakai. Kode lama yang belum terpakai sudah dibatalkan.",
        )

    @app.route("/admin/alumni/<int:alumni_id>/undang", methods=["POST"])
    @admin_required
    def admin_invite(alumni_id: int):
        if not csrf_ok():
            abort(400)
        db = get_db()
        row = db.execute("SELECT id FROM alumni WHERE id = ?", (alumni_id,)).fetchone()
        if row is None:
            abort(404)
        raw = issue_token(
            db,
            purpose="invite",
            alumni_id=alumni_id,
            created_by=g.user["id"],
        )
        audit("invite_created", f"alumni={alumni_id}")
        db.commit()
        link = _public_url("invite_accept", token=raw)
        return _reveal(
            "Tautan undangan",
            [link],
            "Sampaikan ke alumni yang bersangkutan. Berlaku 14 hari, sekali pakai.",
        )

    @app.route("/admin/tempel", methods=["GET", "POST"])
    @admin_required
    def admin_batch():
        preview = None
        if request.method == "POST":
            if not csrf_ok():
                abort(400)
            rows = parse_batch_lines(request.form.get("daftar") or "")
            if not rows:
                flash("Tidak ada baris yang bisa dibaca. Satu orang per baris, dipisah titik koma.", "err")
                return render_template("admin/batch.html", preview=None)
            if len(rows) > 200:
                flash("Maksimal 200 baris sekali tempel.", "err")
                return render_template("admin/batch.html", preview=None)
            db = get_db()
            ids = insert_batch(db, rows)
            links = []
            if request.form.get("undang"):
                for alumni_id in ids:
                    raw = issue_token(
                        db,
                        purpose="invite",
                        alumni_id=alumni_id,
                        created_by=g.user["id"],
                    )
                    links.append(_public_url("invite_accept", token=raw))
            audit("batch_insert", f"n={len(ids)}")
            db.commit()
            if links:
                return _reveal(
                    f"{len(ids)} tautan undangan",
                    links,
                    "Nama belum tampil di direktori. Sampaikan tautan masing-masing. Berlaku 14 hari.",
                )
            flash(
                f"{len(ids)} nama ditambahkan sebagai kerangka, belum tampil di direktori.",
                "ok",
            )
            return redirect(url_for("admin_review"))
        return render_template("admin/batch.html", preview=preview)

    @app.route("/admin/import/template.csv")
    @admin_required
    def admin_import_template():
        audit("import_template", None)
        get_db().commit()
        return Response(
            template_csv_bytes(),
            mimetype="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=template-alumni-kse.csv",
                "Cache-Control": "no-store, private",
            },
        )

