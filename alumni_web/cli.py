from __future__ import annotations

import argparse
import os
import secrets
from datetime import date
from pathlib import Path

from .boot import find_csv, prepare, reset_admin_password
from .db import connect, get_db, init_db
from .import_csv import import_csv_path
from .quality import clean_junk, recompute_flags, refresh_duplicate_flags, resolve_duplicates


def _app():
    # CLI menyiapkan sendiri; jangan biarkan create_app ikut menyiapkan.
    os.environ["ALUMNI_PREPARE_ON_BOOT"] = "0"
    from . import create_app

    return create_app()


def cmd_setup(app, args) -> None:
    info = prepare(
        app,
        args.csv_path,
        auto_import=True,
        allow_generate=True,
        include_root=True,
    )
    print(f"Admin: {info['admin_email']}")
    if info["admin_password"]:
        print(f"Kata sandi awal: {info['admin_password']}")
        print("Catat sekarang. Sandi ini tidak disimpan ke berkas mana pun.")
    if info["import"]:
        r = info["import"]
        print(
            f"Impor {r['filename']}: +{r['inserted']} baru, "
            f"{r['updated']} update, {r['skipped']} skip"
        )


def cmd_import(app, args) -> None:
    with app.app_context():
        init_db()
        path = args.csv_path or find_csv(include_root=True)
        if not path:
            raise SystemExit("CSV tidak ada. Letakkan di data/source/ atau pakai --csv.")
        print(import_csv_path(Path(path)))


def cmd_reset_admin(app, args) -> None:
    password = args.password or secrets.token_urlsafe(12)
    with app.app_context():
        email = reset_admin_password(app, password, email=args.email)
    print(f"Sandi pengurus {email} diganti.")
    if not args.password:
        print(f"Kata sandi baru: {password}")


def cmd_quality(app, args) -> None:
    apply = bool(args.apply)
    with app.app_context():
        junk = clean_junk(apply=apply)
        flags = recompute_flags(apply=apply)
        dups = resolve_duplicates(apply=apply) if args.dedupe else {"decisions": []}
        if apply:
            db = get_db()
            refresh_duplicate_flags(db)
            db.commit()
    print("Isian sampah:", len(junk["changed"]), "nilai")
    for row_id, field, value in junk["changed"][:20]:
        print(f"  #{row_id} {field} = {value!r} -> kosong")
    print("Bendera mutu:")
    keys = sorted(set(flags["before"]) | set(flags["after"]))
    for key in keys:
        print(f"  {key:24} {flags['before'].get(key, 0):>4} -> {flags['after'].get(key, 0):>4}")
    print(f"  baris berubah: {flags['changed']}")
    if args.dedupe:
        print("Nama kembar:")
        for d in dups["decisions"]:
            print(
                f"  {d['name']}: simpan #{d['keep_id']} (isi {d['keep_score']}), "
                f"sembunyikan #{d['hide_id']} (isi {d['hide_score']})"
            )
        if not dups["decisions"]:
            print("  tidak ada yang perlu disembunyikan")
    print("MODE TERAPKAN" if apply else "Mode simulasi. Tambahkan --apply untuk menyimpan.")


def cmd_backup(app, args) -> None:
    target = Path(args.out or f"backup/alumni-{date.today().isoformat()}.db")
    target.parent.mkdir(parents=True, exist_ok=True)
    source = connect(app.config["DATABASE"])
    dest = connect(target)
    with dest:
        source.backup(dest)
    dest.close()
    source.close()
    print(f"Backup: {target} ({target.stat().st_size} byte)")


def main() -> None:
    parser = argparse.ArgumentParser(description="CLI database alumni KSE UNAND")
    sub = parser.add_subparsers(dest="command", required=True)

    p_setup = sub.add_parser("setup", help="Siapkan DB, akun pengurus, impor awal")
    p_setup.add_argument("--csv", dest="csv_path")

    p_import = sub.add_parser("import", help="Impor CSV")
    p_import.add_argument("--csv", dest="csv_path")

    p_reset = sub.add_parser("reset-admin", help="Ganti sandi pengurus")
    p_reset.add_argument("--password", dest="password")
    p_reset.add_argument(
        "--email",
        dest="email",
        help="Email pengurus. Default: ADMIN_EMAIL di .env",
    )

    p_backup = sub.add_parser("backup", help="Backup SQLite yang aman saat server jalan")
    p_backup.add_argument("--out", dest="out")

    p_quality = sub.add_parser(
        "quality", help="Bersihkan isian sampah, hitung ulang bendera mutu, resolusi nama kembar"
    )
    p_quality.add_argument("--apply", action="store_true", help="Simpan perubahan")
    p_quality.add_argument(
        "--dedupe", action="store_true", help="Sembunyikan baris kembar yang paling sedikit isinya"
    )

    args = parser.parse_args()
    app = _app()
    handlers = {
        "setup": cmd_setup,
        "import": cmd_import,
        "reset-admin": cmd_reset_admin,
        "backup": cmd_backup,
        "quality": cmd_quality,
    }
    handlers[args.command](app, args)


if __name__ == "__main__":
    main()
