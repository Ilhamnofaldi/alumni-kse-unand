"""Pembatas laju, validasi redirect, dan sanitasi ekspor."""

from __future__ import annotations

import time
from collections import defaultdict
from urllib.parse import unquote

_hits: dict[str, list[float]] = defaultdict(list)
_MAX_KEYS = 5000


def reset_rate_limits() -> None:
    _hits.clear()


def _prune(now: float, window: int) -> None:
    stale = [k for k, v in _hits.items() if not v or now - v[-1] > window]
    for key in stale:
        _hits.pop(key, None)
    if len(_hits) > _MAX_KEYS:
        oldest = sorted(_hits.items(), key=lambda kv: kv[1][-1])[: len(_hits) - _MAX_KEYS]
        for key, _ in oldest:
            _hits.pop(key, None)


def rate_limited(key: str, limit: int = 8, window: int = 300) -> bool:
    now = time.time()
    _prune(now, window)
    recent = [t for t in _hits[key] if now - t < window]
    if len(recent) >= limit:
        _hits[key] = recent
        return True
    recent.append(now)
    _hits[key] = recent
    return False


def client_key(request) -> str:
    """Alamat peer saja.

    `X-Forwarded-For` sengaja tidak dibaca di sini: header itu dapat dipalsukan
    penyerang. Di belakang reverse proxy, pasang ProxyFix (lihat wsgi.py) agar
    `remote_addr` berisi IP asli.
    """
    return request.remote_addr or "unknown"


def safe_next(value, fallback: str) -> str:
    raw = str(value or "")
    if "%" in raw.lower() and ("%2f" in raw.lower() or "%5c" in raw.lower() or "%00" in raw.lower()):
        return fallback
    nxt = unquote(raw)
    if not nxt.startswith("/") or nxt.startswith("//") or "\\" in nxt or "://" in nxt:
        return fallback
    if "\\" in raw or nxt != raw and unquote(nxt) != nxt:
        return fallback
    return nxt


def csv_cell(val) -> str:
    if val is None:
        return ""
    text = str(val)
    if text[:1] in ("=", "+", "-", "@", "\t"):
        return "'" + text
    return text


def clamp_int(value, low: int, high: int, default: int) -> int:
    raw = str(value or "").strip()
    if not raw.isdigit():
        return default
    if len(raw) > len(str(high)) + 1:
        return default
    try:
        return min(max(int(raw), low), high)
    except ValueError:
        return default


def parse_cohort(value) -> int | None:
    raw = str(value or "").strip()
    if not raw.isdigit() or len(raw) > 4:
        return None
    year = int(raw)
    return year if 1950 <= year <= 2100 else None
