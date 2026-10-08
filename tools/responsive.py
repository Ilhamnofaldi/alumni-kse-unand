"""Periksa halaman pada lebar layar sungguhan, mis. 360px.

`tools/shot.ps1` tidak bisa dipakai untuk ini: Edge headless di Windows menahan
lebar jendela di sekitar 500px, jadi `-Width 360` sebenarnya merender 500px
lalu memotongnya jadi 360. Hasilnya tampak meluap padahal tidak, dan luapan
yang sungguhan justru tidak kelihatan.

Skrip ini memakai DevTools protocol (Emulation.setDeviceMetricsOverride) supaya
lebar tata letaknya betul, lalu membandingkan `scrollWidth` dengan lebar layar.
Keluar dengan kode 1 kalau ada halaman yang meluap, jadi bisa dipakai di QA.

    python tools/responsive.py
    python tools/responsive.py --width 360 --width 768 --shots
    python tools/responsive.py --base http://127.0.0.1:5001 / /statistik
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOT_DIR = ROOT / "tmp" / "responsive"

DEFAULT_PAGES = ("/", "/direktori", "/statistik", "/struktur", "/peta")
DEFAULT_BASE = "http://127.0.0.1:5000"

BROWSER_CANDIDATES = (
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
)

# Hanya dipanggil kalau halaman memang meluap, supaya kotak peta yang isinya
# sengaja dipotong (ubin Leaflet) tidak ikut dilaporkan sebagai tersangka.
PROBE = """
(() => {
  const doc = document.documentElement;
  const wide = doc.scrollWidth - doc.clientWidth;
  const suspects = [];
  if (wide > 0) {
    for (const el of document.querySelectorAll('body *')) {
      const box = el.getBoundingClientRect();
      if (box.width === 0 && box.height === 0) continue;
      if (box.right <= doc.clientWidth + 1) continue;
      let clipped = false;
      for (let p = el.parentElement; p; p = p.parentElement) {
        if (getComputedStyle(p).overflowX !== 'visible') { clipped = true; break; }
      }
      if (clipped) continue;
      suspects.push({
        tag: el.tagName.toLowerCase(),
        cls: (el.className || '').toString().trim().slice(0, 48),
        right: Math.round(box.right),
        width: Math.round(box.width),
      });
    }
    suspects.sort((a, b) => b.right - a.right);
  }
  return JSON.stringify({
    viewport: doc.clientWidth,
    scrollWidth: doc.scrollWidth,
    overflow: wide,
    suspects: suspects.slice(0, 8),
  });
})()
"""


def find_browser() -> Path:
    for path in BROWSER_CANDIDATES:
        if path.is_file():
            return path
    for name in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return Path(found)
    raise SystemExit("Chrome atau Edge tidak ditemukan. Pasang salah satu, lalu jalankan lagi.")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class DevTools:
    """Klien WebSocket seadanya: cukup untuk kirim perintah dan tunggu balasan."""

    def __init__(self, url: str):
        hostport, path = url.split("://", 1)[1].split("/", 1)
        host, port = hostport.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=30)
        key = base64.b64encode(uuid.uuid4().bytes).decode()
        self.sock.sendall(
            f"GET /{path} HTTP/1.1\r\n"
            f"Host: {hostport}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode()
        )
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.sock.recv(4096)
        self.buf = buf.split(b"\r\n\r\n", 1)[1]
        self.last_id = 0

    def close(self) -> None:
        self.sock.close()

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise SystemExit("DevTools menutup sambungan lebih awal.")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def call(self, method: str, params: dict | None = None) -> dict:
        self.last_id += 1
        payload = json.dumps({"id": self.last_id, "method": method, "params": params or {}}).encode()
        size = len(payload)
        if size < 126:
            header = struct.pack("!BB", 0x81, 0x80 | size)
        elif size < 1 << 16:
            header = struct.pack("!BBH", 0x81, 0x80 | 126, size)
        else:
            header = struct.pack("!BBQ", 0x81, 0x80 | 127, size)
        mask = os.urandom(4)
        self.sock.sendall(
            header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        )
        while True:
            first, second = self._read(2)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read(8))[0]
            body = self._read(length)
            if first & 0x0F != 1:
                continue
            message = json.loads(body)
            if message.get("id") != self.last_id:
                continue
            if "error" in message:
                raise SystemExit(f"{method} gagal: {message['error']}")
            return message.get("result", {})


def attach(port: int) -> DevTools:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            listing = json.loads(
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2).read()
            )
            page = next((t for t in listing if t["type"] == "page"), None)
            if page:
                return DevTools(page["webSocketDebuggerUrl"])
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(0.4)
    raise SystemExit("Peramban tidak membuka DevTools tepat waktu.")


def check(dev: DevTools, base: str, path: str, width: int, settle: float, shots: bool) -> bool:
    dev.call(
        "Emulation.setDeviceMetricsOverride",
        {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": width <= 480},
    )
    dev.call("Page.navigate", {"url": base + path})
    time.sleep(settle)
    report = json.loads(
        dev.call("Runtime.evaluate", {"expression": PROBE, "returnByValue": True})["result"]["value"]
    )
    ok = report["overflow"] <= 0
    mark = "pas   " if ok else "LUAPAN"
    print(f"[{mark}] {width}px {path:<12} layar={report['viewport']} isi={report['scrollWidth']}")
    for item in report["suspects"]:
        print(f"           tepi kanan {item['right']}px, lebar {item['width']}px"
              f"  <{item['tag']} class=\"{item['cls']}\">")
    if shots:
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        name = (path.strip("/") or "home").replace("/", "-")
        data = dev.call(
            "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True}
        )["data"]
        (SHOT_DIR / f"{width}-{name}.png").write_bytes(base64.b64decode(data))
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Cek luapan mendatar pada lebar layar tertentu")
    parser.add_argument("pages", nargs="*", default=list(DEFAULT_PAGES),
                        help="Jalur halaman, mis. / /statistik")
    parser.add_argument("--base", default=DEFAULT_BASE, help=f"Alamat server (bawaan {DEFAULT_BASE})")
    parser.add_argument("--width", type=int, action="append", dest="widths",
                        help="Lebar layar, boleh diulang (bawaan 360)")
    parser.add_argument("--settle", type=float, default=2.5,
                        help="Detik menunggu Chart.js dan Leaflet selesai (bawaan 2.5)")
    parser.add_argument("--shots", action="store_true",
                        help="Simpan PNG ke tmp/responsive/")
    args = parser.parse_args()
    widths = args.widths or [360]
    base = args.base.rstrip("/")

    try:
        urllib.request.urlopen(f"{base}/healthz", timeout=5)
    except (urllib.error.URLError, OSError) as exc:
        raise SystemExit(f"Server di {base} tidak menjawab ({exc}). Jalankan `python run.py` dulu.")

    browser = find_browser()
    port = free_port()
    profile = Path(tempfile.mkdtemp(prefix="responsive-"))
    proc = subprocess.Popen(
        [str(browser), "--headless=new", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", f"--remote-debugging-port={port}",
         f"--user-data-dir={profile}", "--window-size=1200,900", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    failures = 0
    try:
        dev = attach(port)
        dev.call("Page.enable")
        dev.call("Runtime.enable")
        for width in widths:
            for path in args.pages:
                if not check(dev, base, path, width, args.settle, args.shots):
                    failures += 1
        dev.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        shutil.rmtree(profile, ignore_errors=True)

    if failures:
        print(f"\n{failures} halaman meluap mendatar.")
        return 1
    print(f"\nSemua halaman pas pada {', '.join(f'{w}px' for w in widths)}.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
