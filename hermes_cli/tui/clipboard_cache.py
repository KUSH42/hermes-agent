"""Clipboard HTML cache — persists copies to ~/.cache/hermes/clipboard/ with rotation."""
from __future__ import annotations

import logging
import time
from pathlib import Path

_log = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".cache" / "hermes" / "clipboard"
RETENTION_SECONDS = 24 * 60 * 60


def cache_dir() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def write_html(html: str) -> Path:
    d = cache_dir()
    path = d / f"copy_{int(time.time())}.html"
    path.write_text(html, encoding="utf-8")
    return path


def prune_expired(now: float | None = None) -> int:
    """Delete entries older than RETENTION_SECONDS. Returns count deleted."""
    if not CACHE_DIR.exists():
        return 0
    cutoff = (now if now is not None else time.time()) - RETENTION_SECONDS
    deleted = 0
    for entry in CACHE_DIR.iterdir():
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
                deleted += 1
        except OSError:
            _log.debug("prune skipped %s", entry, exc_info=True)
    return deleted
