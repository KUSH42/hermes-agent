"""Disk cache for slow banner data inputs: unavailable_toolsets, mcp_status, skills_by_category.

Cache key: SHA-1[:12] of (format_ver, sys.executable, install_path).
Stored as JSON with a unix-epoch timestamp; TTL = 24 h.
Atomic write via .tmp + rename.  GC deletes orphaned .tmp files older than TTL.

Usage:
    _cached = load_banner_data()
    if _cached is not None:
        # use _cached["unavailable_toolsets"], ["mcp_status"], ["skills_by_category"]
    else:
        # run live calls
    schedule_refresh()  # kicks daemon thread off critical path
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

_log = logging.getLogger(__name__)

_FORMAT_VER = 1
_DEFAULT_TTL = 24 * 60 * 60  # seconds

_refresh_started = threading.Event()


def is_cache_disabled() -> bool:
    return os.environ.get("HERMES_NO_CACHE", "") not in ("", "0")


def banner_data_cache_dir() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME", "")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    d = base / "hermes" / "banner_data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def banner_data_cache_key() -> str:
    install_path = str(Path(__file__).resolve().parent)
    blob = "\x00".join([str(_FORMAT_VER), sys.executable, install_path])
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


def load_banner_data() -> dict | None:
    if is_cache_disabled():
        return None
    try:
        p = banner_data_cache_dir() / f"{banner_data_cache_key()}.json"
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("_v") != _FORMAT_VER:
            return None
        ts = data.get("_ts", 0)
        if time.time() - ts > _DEFAULT_TTL:
            return None
        return data
    except Exception:
        _log.debug("banner data cache load failed", exc_info=True)
        return None


def save_banner_data(
    unavailable_toolsets: list,
    mcp_status: list,
    skills_by_category: dict,
) -> None:
    if is_cache_disabled():
        return
    try:
        cache_dir = banner_data_cache_dir()
        key = banner_data_cache_key()
        tmp = cache_dir / f"{key}.tmp"
        final = cache_dir / f"{key}.json"
        payload = {
            "_v": _FORMAT_VER,
            "_ts": time.time(),
            "unavailable_toolsets": unavailable_toolsets,
            "mcp_status": mcp_status,
            "skills_by_category": skills_by_category,
        }
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(final)
    except Exception:
        _log.debug("banner data cache save failed", exc_info=True)


def gc_banner_data_cache() -> None:
    """Delete .tmp files older than TTL (orphaned by killed process)."""
    try:
        cutoff = time.time() - _DEFAULT_TTL
        for p in banner_data_cache_dir().glob("*.tmp"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
            except Exception:
                _log.debug("gc_banner_data_cache: failed to remove %s", p, exc_info=True)
    except Exception:
        _log.debug("gc_banner_data_cache failed", exc_info=True)


def _do_refresh() -> None:
    try:
        from model_tools import check_tool_availability
        _, unavailable_toolsets = check_tool_availability(quiet=True)
    except Exception:
        _log.exception("_do_refresh: check_tool_availability failed")
        unavailable_toolsets = []
    try:
        from tools.mcp_tool import get_mcp_status
        mcp_status = get_mcp_status()
    except Exception:
        # EH-OK: MCP status is cosmetic; cache write continues with empty list
        _log.debug("_do_refresh: get_mcp_status failed", exc_info=True)
        mcp_status = []
    try:
        from hermes_cli.banner import get_available_skills
        skills_by_category = get_available_skills()
    except Exception:
        _log.exception("_do_refresh: get_available_skills failed")
        skills_by_category = {}
    save_banner_data(unavailable_toolsets, mcp_status, skills_by_category)
    gc_banner_data_cache()


def schedule_refresh() -> None:
    """Start a daemon thread to refresh the banner data cache.

    Idempotent within a process: second call is a no-op.
    """
    if is_cache_disabled() or _refresh_started.is_set():
        return
    _refresh_started.set()
    t = threading.Thread(
        target=_do_refresh,
        daemon=True,
        name="hermes-banner-data-refresh",
    )
    t.start()
