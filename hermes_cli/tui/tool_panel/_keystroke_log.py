"""Opt-in keypress recorder for convergence-plan Step 6a.

Enabled by:
  - env var  HERMES_KEYSTROKE_LOG=1, OR
  - ~/.hermes/config.toml  [debug] keystroke_log = true

Never active when the env var HERMES_CI=1 is set (CI guard).
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # no runtime deps needed at import time

_log = logging.getLogger(__name__)

# Keys logged verbatim; all other printable chars become "<other>".
# Includes every key in BINDINGS plus navigation keys; "c" excluded (not bound).
_ALLOWLIST: frozenset[str] = frozenset({
    "t", "T", "y", "Y", "C", "H", "I", "u", "o", "e", "p", "P",
    "r", "a", "E", "O", "f", "j", "k", "J", "K", "D", "x",
    "plus", "minus", "asterisk", "less_than_sign", "greater_than_sign",
    "question_mark",
    "escape", "enter", "tab", "space", "f1",
    "up", "down", "left", "right",
    "page_up", "page_down",
    "shift+d",
})

_ROTATE_BYTES: int = 5 * 1024 * 1024  # 5 MB
_LOG_PATH: Path = Path.home() / ".hermes" / "keystroke.jsonl"


def _is_enabled() -> bool:
    """Return True iff recording is enabled and not suppressed by CI guard."""
    if os.environ.get("HERMES_CI") == "1":
        return False
    if os.environ.get("HERMES_KEYSTROKE_LOG") == "1":
        return True
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            return False
    cfg_path = Path.home() / ".hermes" / "config.toml"
    if not cfg_path.exists():
        return False
    try:
        with cfg_path.open("rb") as fh:
            data = tomllib.load(fh)
        return bool(data.get("debug", {}).get("keystroke_log", False))
    except Exception:
        _log.warning("keystroke_log: failed to parse config.toml", exc_info=True)
        return False


# Evaluated once at module import so overhead per keypress is a single bool read.
ENABLED: bool = _is_enabled()


def _redact(key: str) -> str:
    """Return key verbatim if in allowlist, else '<other>'."""
    return key if key in _ALLOWLIST else "<other>"


def _rotate_if_needed(path: Path) -> None:
    """Rotate path → path.1 when path exceeds _ROTATE_BYTES; keep one backup."""
    try:
        if path.stat().st_size >= _ROTATE_BYTES:
            rotated = path.with_suffix(".jsonl.1")
            path.rename(rotated)
    except FileNotFoundError:
        pass  # file doesn't exist yet — nothing to rotate
    except Exception:
        _log.warning("keystroke_log: rotation failed", exc_info=True)


def _base_row(
    event_type: str,
    block_id: str,
    phase: str,
    kind: "str | None",
    density: str,
    focused: bool,
) -> dict:
    return {
        "ts": round(time.time(), 3),
        "event_type": event_type,
        "block_id": block_id,
        "phase": phase,
        "kind": kind,
        "density": density,
        "focused": focused,
    }


def _append(row: dict) -> None:
    path = _LOG_PATH
    try:
        _rotate_if_needed(path)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except Exception:
        _log.warning("keystroke_log: write failed", exc_info=True)


def record(
    key: str,
    block_id: str,
    phase: str,
    kind: "str | None",
    density: str,
    focused: bool,
) -> None:
    """Append one key-event JSONL record.

    Called from ToolPanel.on_key (main thread) — must be fast (<50 µs).
    """
    if not ENABLED:
        return
    row = _base_row("key", block_id, phase, kind, density, focused)
    row["key"] = _redact(key)
    _append(row)


def record_mouse(
    button: str,
    x: int,
    y: int,
    widget: str,
    block_id: str,
    phase: str,
    kind: "str | None",
    density: str,
    focused: bool,
) -> None:
    """Append one mouse-event JSONL record.

    `button` must be one of: "left", "right", "middle", "scroll_up", "scroll_down".
    Called from ToolPanel.on_mouse_* handlers (main thread).
    """
    if not ENABLED:
        return
    row = _base_row("mouse", block_id, phase, kind, density, focused)
    row["button"] = button
    row["x"] = x
    row["y"] = y
    row["widget"] = widget
    _append(row)


def record_component(
    action: str,
    widget: str,
    block_id: str,
    phase: str,
    kind: "str | None",
    density: str,
    focused: bool,
    extra: "dict | None" = None,
) -> None:
    """Append one component-interaction JSONL record.

    `action` is a symbolic name from the catalogue in KL-7.
    Called from discrete interaction sites inside ToolPanel and its children.
    """
    if not ENABLED:
        return
    row = _base_row("component", block_id, phase, kind, density, focused)
    row["action"] = action
    row["widget"] = widget
    row["extra"] = extra
    _append(row)
