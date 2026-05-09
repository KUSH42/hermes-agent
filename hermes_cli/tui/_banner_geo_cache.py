"""Disk cache for banner hero-slot geometry (hero_row/col/width/height).

Cache key: SHA-1[:12] of (format_ver, panel_width, skin_name,
           wide_layout flag, tall_layout flag).
Stored as a compact 4-integer JSON file; no gzip (tiny payload).
"""
from __future__ import annotations
import hashlib, json, logging, os
from pathlib import Path

_log = logging.getLogger(__name__)
_GEO_CACHE_FORMAT_VER = 4  # bumped: logo_tte_active included in cache key


def is_cache_disabled() -> bool:
    """Return True when HERMES_NO_CACHE env var is set to a truthy value."""
    return os.environ.get("HERMES_NO_CACHE", "") not in ("", "0")


def geo_cache_dir() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME", "")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    d = base / "hermes" / "banner_geo"
    d.mkdir(parents=True, exist_ok=True)
    return d


def geo_cache_key(
    panel_width: int,
    skin_name: str,
    wide_layout: bool,
    tall_layout: bool,
    logo_tte_active: bool = False,
) -> str:
    """Compute a 12-hex-char cache key from layout inputs.

    wide_layout: term_width >= 95 (logo/wordmark prints)
    tall_layout: term_rows >= 32  (full block-letter logo, not wordmark)
    logo_tte_active: whether logo TTE placeholder is embedded in the template
    These must mirror the gate in hermes_cli/banner.py build_welcome_banner.
    """
    blob = "\x00".join([
        str(_GEO_CACHE_FORMAT_VER),
        str(panel_width),
        skin_name.strip().lower(),
        "1" if wide_layout else "0",
        "1" if tall_layout else "0",
        "1" if logo_tte_active else "0",
    ])
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


def load_geo(key: str) -> dict[str, int] | None:
    if is_cache_disabled():
        return None
    try:
        p = geo_cache_dir() / f"{key}.json"
        if not p.exists():
            return None
        data = json.loads(p.read_text())
        if data.get("_v") != _GEO_CACHE_FORMAT_VER:
            return None
        return {k: int(data[k]) for k in ("hero_row", "hero_col")}
    except Exception:
        _log.debug("banner geo cache load failed", exc_info=True)
        return None


def save_geo(key: str, geo: dict[str, int]) -> None:
    if is_cache_disabled():
        return
    try:
        p = geo_cache_dir() / f"{key}.json"
        p.write_text(json.dumps({**geo, "_v": _GEO_CACHE_FORMAT_VER}))
    except Exception:
        _log.debug("banner geo cache save failed", exc_info=True)


def gc_geo_cache(cap: int = 20) -> None:
    """Delete oldest geo cache files beyond cap."""
    if cap <= 0:
        return
    try:
        files = sorted(geo_cache_dir().glob("*.json"), key=lambda p: p.stat().st_mtime)
        for old in files[:-cap]:
            old.unlink(missing_ok=True)
    except Exception:
        _log.debug("banner geo gc failed", exc_info=True)
