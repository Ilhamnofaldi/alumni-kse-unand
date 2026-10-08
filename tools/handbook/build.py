"""Cetak buku saku alumni dan pengurus ke PDF A4."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT_DIR = ROOT / "alumni_web" / "static" / "docs"
PREVIEW_DIR = ROOT / "tmp" / "handbook-preview"

BOOKS = (
    ("pengguna.html", "pedoman-pengguna.pdf"),
    ("pengurus.html", "pedoman-pengurus.pdf"),
)

CHROME_CANDIDATES = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
)


def find_browser() -> Path:
    for path in CHROME_CANDIDATES:
        if path.is_file():
            return path
    for name in ("chrome", "msedge", "google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return Path(found)
    raise SystemExit(
        "Chrome atau Edge tidak ditemukan. Pasang salah satu, lalu jalankan lagi."
    )


def print_pdf(browser: Path, html: Path, pdf: Path) -> None:
    pdf.parent.mkdir(parents=True, exist_ok=True)
    if pdf.exists():
        pdf.unlink()
    # Profil sekali pakai: tanpa ini peramban bisa memakai print.css dari cache.
    profile = Path(tempfile.mkdtemp(prefix="handbook-"))
    cmd = [
        str(browser),
        "--headless=new",
        "--disable-gpu",
        "--allow-file-access-from-files",
        "--no-pdf-header-footer",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={profile}",
        "--disable-application-cache",
        "--virtual-time-budget=15000",
        "--run-all-compositor-stages-before-draw",
        f"--print-to-pdf={pdf}",
        html.resolve().as_uri(),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    if result.returncode != 0 or not pdf.is_file() or pdf.stat().st_size < 1000:
        detail = (result.stderr or result.stdout or "").strip()
        raise SystemExit(
            f"Gagal mencetak {html.name} (kode {result.returncode}). {detail}"
        )


def page_count(pdf: Path) -> int:
    try:
        import pypdfium2
    except ImportError:
        return -1
    doc = pypdfium2.PdfDocument(str(pdf))
    try:
        return len(doc)
    finally:
        doc.close()


def render_preview(pdf: Path, dest: Path) -> int:
    import pypdfium2

    dest.mkdir(parents=True, exist_ok=True)
    for lama in dest.glob("*.png"):
        lama.unlink()
    doc = pypdfium2.PdfDocument(str(pdf))
    try:
        n = len(doc)
        for i in range(n):
            page = doc[i]
            bitmap = page.render(scale=1.5)
            pil = bitmap.to_pil()
            pil.save(dest / f"page-{i + 1:02d}.png")
            page.close()
        return n
    finally:
        doc.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Cetak buku saku KSE UNAND")
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Render PNG halaman ke tmp/handbook-preview/ (butuh pypdfium2)",
    )
    args = parser.parse_args()
    browser = find_browser()
    print(f"Peramban: {browser}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    for html_name, pdf_name in BOOKS:
        html = HERE / html_name
        pdf = OUT_DIR / pdf_name
        if not html.is_file():
            raise SystemExit(f"Sumber hilang: {html}")
        print_pdf(browser, html, pdf)
        pages = page_count(pdf)
        size_kb = pdf.stat().st_size // 1024
        extra = f", {pages} halaman" if pages >= 0 else ""
        print(f"  {pdf.relative_to(ROOT)} ({size_kb} KB{extra})")
        made.append(pdf)
    if args.preview:
        try:
            import PIL  # noqa: F401
        except ImportError as exc:
            raise SystemExit("Pratinjau butuh Pillow: pip install pillow") from exc
        for pdf in made:
            folder = PREVIEW_DIR / pdf.stem
            n = render_preview(pdf, folder)
            print(f"  pratinjau {n} PNG di {folder.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
