"""Persistent disk cache for TTE startup animation frames.

Stores raw ANSI frame strings as gzip+pickle so subsequent startups skip
the CPU-bound iter_frames() call entirely.

Cache key: SHA-1[:14] of effect_name, plain_hero, render_width, skin_colors,
params, installed TTE library version, and internal format version.

Set HERMES_TTE_NO_CACHE=1 (or true/yes/on) to disable both loading and saving.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import pickle
import threading
import time
from pathlib import Path

_log = logging.getLogger(__name__)

# bump to nuke all caches at next release
_TTE_CACHE_FORMAT_VER: int = 1
_GC_MAX_AGE_S: int = 7 * 86400  # 7 days
_GC_MAX_FILES: int = 10
_NO_CACHE_VALUES: frozenset = frozenset(("1", "true", "yes", "on"))

# Set when a corrupt cache file cannot be unlinked; disables cache for the remainder of this run
_CACHE_DISABLED_FOR_RUN: threading.Event = threading.Event()


def _no_cache() -> bool:
    # _NO_CACHE_VALUES declared at module level (see above)
    return os.environ.get("HERMES_TTE_NO_CACHE", "").strip().lower() in _NO_CACHE_VALUES


def _tte_version() -> str:
    try:
        import terminaltexteffects as _m
        # "unknown" is a stable sentinel: a package without __version__ produces
        # the same key on every restart, so caches remain valid across sessions
        # as long as the package is not upgraded (which would change __version__).
        return str(getattr(_m, "__version__", "unknown"))
    except ImportError:  # il-ex-1-exempt: swallow
        return "missing"


def tte_cache_dir() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME", "")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    d = base / "hermes" / "tte"
    d.mkdir(parents=True, exist_ok=True)
    return d


def tte_cache_key(
    effect_name: str,
    plain_hero: str,   # sanitized by _sanitize_startup_hero_text before calling;
                       # hashed verbatim — different byte strings → different keys
    render_width: int,
    skin_colors: tuple[str, str, str],   # (banner_title, banner_accent, banner_dim)
    params: dict[str, object],
) -> str:
    try:
        params_str = json.dumps(params, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"tte_cache_key: params not JSON-serializable: {exc}") from exc
    tte_ver = _tte_version()
    normed_colors = (
        skin_colors[0].upper(),
        skin_colors[1].upper(),
        skin_colors[2].upper(),
    )
    blob = "\x00".join([
        str(_TTE_CACHE_FORMAT_VER),
        effect_name.strip().lower(),
        plain_hero,
        str(render_width),
        f"{normed_colors[0]},{normed_colors[1]},{normed_colors[2]}",
        params_str,
        tte_ver,
    ])
    # 14 hex chars = 56-bit prefix; collision resistance reduced to 56 bits.
    # Collision risk is explicitly accepted: birthday-paradox probability ≈ N²/2⁵⁷
    # where N is live file count. GC caps N at 10 after each miss write-back, but N
    # may temporarily exceed that before GC runs. Even at N=50: 50²/2⁵⁷ ≈ 1.73×10⁻¹⁴
    # — still negligible.
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:14]


def load_tte_frames(key: str) -> list[str] | None:
    if _no_cache():
        return None
    if _CACHE_DISABLED_FOR_RUN.is_set():
        return None
    try:
        path = tte_cache_dir() / f"{key}.pkl.gz"
    except Exception:
        _log.debug("tte_cache: load failed (cannot access cache dir)", exc_info=True)
        return None
    try:
        if not path.exists():
            return None
        with gzip.open(path, "rb") as fh:
            data = pickle.load(fh)
        if not isinstance(data, dict) or data.get("v") != _TTE_CACHE_FORMAT_VER:
            try:
                path.unlink(missing_ok=True)
            except OSError:  # il-ex-1-exempt: swallow
                pass  # file may have been deleted between check and unlink — ignore
            return None
        frames = data.get("frames")
        if not isinstance(frames, list) or not frames:
            try:
                path.unlink(missing_ok=True)
            except OSError:  # il-ex-1-exempt: swallow
                pass  # file may have been deleted between check and unlink — ignore
            return None
        # str(f) coercion is intentionally lenient: frames are always written as
        # str by save_tte_frames, so str(f)==f for any valid cache file. The
        # _TTE_CACHE_FORMAT_VER version check above rejects files from future
        # format changes that might use non-string items.
        return [str(f) for f in frames]
    except Exception:
        _log.debug("tte_cache: load failed for key=%s", key, exc_info=True)
        try:
            path.unlink(missing_ok=True)
        except FileNotFoundError:  # il-ex-1-exempt: swallow
            pass  # raced with another process — fine
        except OSError:
            _log.warning(
                "tte_cache: cannot unlink corrupt cache file %s; disabling cache for this run",
                path, exc_info=True,
            )
            _CACHE_DISABLED_FOR_RUN.set()
        return None


def save_tte_frames(key: str, frames: list[str]) -> None:
    if not frames or _no_cache():
        return
    if _CACHE_DISABLED_FOR_RUN.is_set():
        return
    try:
        cache_dir = tte_cache_dir()
    except Exception:
        _log.debug("tte_cache: save failed (cannot create cache dir)", exc_info=True)
        return
    path = cache_dir / f"{key}.pkl.gz"
    tmp = cache_dir / f"{key}.pkl.gz.tmp"
    try:
        data = {"v": _TTE_CACHE_FORMAT_VER, "frames": frames}
        with gzip.open(tmp, "wb", compresslevel=6) as fh:
            pickle.dump(data, fh, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(path)            # atomic rename
    except Exception:
        _log.debug("tte_cache: save failed for key=%s", key, exc_info=True)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:  # il-ex-1-exempt: swallow
            pass  # tmp file may have been deleted already — ignore


def gc_tte_cache() -> None:
    try:
        cache_dir = tte_cache_dir()
        now = time.time()  # wall-clock; correct for mtime comparisons

        # Delete orphaned .tmp files (left by interrupted saves).
        for tmp in cache_dir.glob("*.pkl.gz.tmp"):
            try:
                _st = tmp.stat()
                if (now - _st.st_mtime) > _GC_MAX_AGE_S:
                    tmp.unlink(missing_ok=True)
            except OSError:  # il-ex-1-exempt: swallow
                pass  # file deleted by concurrent process — ignore

        files = list(cache_dir.glob("*.pkl.gz"))
        survivors = []
        for f in files:
            try:
                _st = f.stat()
                if (now - _st.st_mtime) > _GC_MAX_AGE_S:
                    f.unlink(missing_ok=True)
                else:
                    survivors.append((_st.st_mtime, f))
            except OSError:  # il-ex-1-exempt: swallow
                pass  # file deleted by concurrent process — ignore
        # enforce max file count: keep _GC_MAX_FILES newest
        if len(survivors) > _GC_MAX_FILES:
            survivors.sort()   # ascending mtime; oldest first
            for _mtime, f in survivors[:-_GC_MAX_FILES]:
                try:
                    f.unlink(missing_ok=True)
                except OSError:  # il-ex-1-exempt: swallow
                    pass  # file deleted by concurrent process — ignore
    except Exception:
        _log.debug("tte_cache: gc failed", exc_info=True)
