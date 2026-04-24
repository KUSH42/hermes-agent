"""Pure utility functions for the Hermes TUI widget layer.

No widget classes live here.  This module is the leaf of the tui import
graph — it must NOT import from any other tui widget file.
"""

from __future__ import annotations

import os
import re
import shutil

from rich.style import Style
from rich.text import Text
from textual.cache import FIFOCache, LRUCache
from textual.strip import Strip
from textual.widget import Widget


# ---------------------------------------------------------------------------
# Module-level compiled regexes (shared across modules)
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(
    r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]"
)
_PRENUMBERED_LINE_RE = re.compile(r"^\s*(\d+)(?:\s*[│|:]\s?|\s{2,})(.*)$")

# Matches complete ANSI/VT escape sequences as atomic units for typewriter animation.
# Covers CSI (colour/attr), OSC (hyperlinks), and Fe (reverse-index etc.).
_ANSI_SEQ_RE = re.compile(
    r"\x1b(?:"
    r"\[[0-9;]*[A-Za-z]"               # CSI sequences
    r"|\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC sequences
    r"|[A-Za-z]"                        # Fe sequences
    r")"
)


# ---------------------------------------------------------------------------
# Nerd Font helper
# ---------------------------------------------------------------------------

def _nf_or_text(glyph: str, fallback: str, app: "object | None" = None) -> str:
    """Return NF glyph if terminal supports it, else fallback text."""
    if os.environ.get("HERMES_ACCESSIBLE") or os.environ.get("HERMES_NO_UNICODE"):
        return fallback
    if app is not None:
        try:
            cs = app.console.color_system  # type: ignore[attr-defined]
            if cs is None or cs == "standard":
                return fallback
        except Exception:
            pass
    return glyph


# ---------------------------------------------------------------------------
# Skin helpers
# ---------------------------------------------------------------------------

def _skin_color(key: str, fallback: str) -> str:
    """Read a color from the active skin, falling back to *fallback*."""
    try:
        from hermes_cli.skin_engine import get_active_skin
        return get_active_skin().get_color(key, fallback)
    except Exception:
        return fallback


def _skin_branding(key: str, fallback: str) -> str:
    """Read a branding string from the active skin."""
    try:
        from hermes_cli.skin_engine import get_active_skin
        return get_active_skin().get_branding(key, fallback)
    except Exception:
        return fallback


# ---------------------------------------------------------------------------
# Layout cache boost
# ---------------------------------------------------------------------------

def _boost_layout_caches(
    widget: Widget,
    *,
    box_model_maxsize: int = 128,
    arrangement_maxsize: int = 16,
) -> None:
    """Raise Textual's tiny default layout caches on heavy auto-height widgets."""
    widget._box_model_cache = LRUCache(box_model_maxsize)
    widget._arrangement_cache = FIFOCache(arrangement_maxsize)


# ---------------------------------------------------------------------------
# Strip/span helpers
# ---------------------------------------------------------------------------

def _apply_span_style(strip: Strip, start_x: int, end_x: int, style: Style) -> Strip:
    """Apply *style* to character range [start_x, end_x) in *strip*.

    Used to paint selection highlights on RichLog strips.  *end_x* == -1
    means apply to end of strip.  Positions are in characters (code points),
    matching the coordinate system used by ``apply_offsets`` and
    ``Selection.get_span``.
    """
    from rich.segment import Segment as _Seg
    segs = list(strip)
    new_segs: list[_Seg] = []
    char_pos = 0
    real_end = sum(len(s.text) for s in segs) if end_x == -1 else end_x

    for seg in segs:
        text, seg_style, ctrl = seg.text, seg.style, seg.control
        seg_len = len(text)
        seg_end = char_pos + seg_len

        if seg_end <= start_x or char_pos >= real_end:
            new_segs.append(seg)
        elif char_pos >= start_x and seg_end <= real_end:
            new_segs.append(_Seg(text, (seg_style + style) if seg_style else style, ctrl))
        else:
            a = max(0, start_x - char_pos)
            b = min(seg_len, real_end - char_pos)
            if a > 0:
                new_segs.append(_Seg(text[:a], seg_style, ctrl))
            new_segs.append(_Seg(text[a:b], (seg_style + style) if seg_style else style, ctrl))
            if b < seg_len:
                new_segs.append(_Seg(text[b:], seg_style, ctrl))

        char_pos += seg_len

    return Strip(new_segs, strip.cell_length)


def _strip_ansi(text: str) -> str:
    """Strip ANSI CSI escape sequences from text."""
    return _ANSI_RE.sub("", text)


def _prewrap_code_line(highlighted: str, source_line: str = "", width: int | None = None) -> list[str]:
    """Pre-wrap an ANSI-highlighted code line, indenting continuation chunks.

    Continuation rows carry the same leading whitespace as *source_line*
    (the original un-highlighted code).  If *source_line* is empty or has
    no leading whitespace, a 4-space indent is used as fallback.

    Returns a list of strings — one per visual line.  Short lines return
    ``[highlighted]`` unchanged.  Long lines are split at the last space
    before *width*; ANSI colour state is re-emitted at each chunk start.
    """
    if width is None:
        try:
            width = shutil.get_terminal_size((80, 24)).columns - 6  # account for margins + scrollbar
        except Exception:
            width = 74
    plain = _strip_ansi(highlighted)
    if len(plain) <= width:
        return [highlighted]

    # Detect original line's leading whitespace for continuation indent
    stripped_src = source_line.lstrip(" \t")
    src_indent_len = len(source_line) - len(stripped_src)
    if src_indent_len > 0:
        indent = source_line[:src_indent_len]
    else:
        indent = "    "

    # Tokenise into (type, value) pairs: 'ansi' or 'text'
    tokens: list[tuple[str, str]] = []
    pos = 0
    for m in _ANSI_RE.finditer(highlighted):
        if m.start() > pos:
            tokens.append(("text", highlighted[pos:m.start()]))
        tokens.append(("ansi", m.group()))
        pos = m.end()
    if pos < len(highlighted):
        tokens.append(("text", highlighted[pos:]))

    active_ansi: list[str] = []
    chunks: list[str] = []
    cur = ""
    cur_vis = 0

    def _flush() -> None:
        nonlocal cur, cur_vis
        if cur:
            chunks.append(cur)
        cur = indent + "".join(active_ansi)
        cur_vis = len(indent)

    for ttype, tval in tokens:
        if ttype == "ansi":
            cur += tval
            active_ansi.append(tval)
            continue
        remaining = tval
        while remaining:
            space_left = width - cur_vis
            if space_left <= 0:
                _flush()
                space_left = width - len(indent)
            if len(remaining) <= space_left:
                cur += remaining
                cur_vis += len(remaining)
                break
            seg = remaining[:space_left]
            last_sp = seg.rfind(" ")
            if last_sp > 0:
                cur += remaining[:last_sp + 1]
                remaining = remaining[last_sp + 1:]
            else:
                cur += remaining[:space_left]
                remaining = remaining[space_left:]
            _flush()

    if cur:
        if cur_vis > len(indent) or not chunks:
            chunks.append(cur)
        elif chunks:
            chunks[-1] += cur

    return chunks if chunks else [highlighted]


# ---------------------------------------------------------------------------
# Typewriter config accessors (called once at mount, never from render)
# ---------------------------------------------------------------------------

def _typewriter_enabled() -> bool:
    env = os.environ.get("HERMES_TYPEWRITER")
    if env == "1":
        return True
    if env == "0":
        return False
    try:
        from hermes_cli.config import read_raw_config
        return bool(
            read_raw_config().get("terminal", {}).get("typewriter", {}).get("enabled", False)
        )
    except Exception:
        return False


def _typewriter_delay_s() -> float:
    speed = 60
    try:
        from hermes_cli.config import read_raw_config
        speed = read_raw_config().get("terminal", {}).get("typewriter", {}).get("speed", 60)
    except Exception:
        pass
    if speed <= 0:
        return 0.0
    return 1.0 / speed


def _typewriter_burst_threshold() -> int:
    try:
        from hermes_cli.config import read_raw_config
        raw = read_raw_config().get("terminal", {}).get("typewriter", {}).get("burst_threshold", 128)
        return max(1, int(raw))
    except Exception:
        return 128


def _typewriter_cursor_enabled() -> bool:
    try:
        from hermes_cli.config import read_raw_config
        return bool(
            read_raw_config().get("terminal", {}).get("typewriter", {}).get("cursor", True)
        )
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Display animation config accessors (analogous to _typewriter_enabled)
# ---------------------------------------------------------------------------

def _cursor_blink_enabled() -> bool:
    """Non-typewriter cursor blink (default: true)."""
    try:
        from hermes_cli.config import read_raw_config
        return bool(read_raw_config().get("display", {}).get("cursor_blink", True))
    except Exception:
        return True


def _pulse_enabled() -> bool:
    """PulseMixin on StatusBar running indicator (default: true)."""
    try:
        from hermes_cli.config import read_raw_config
        return bool(read_raw_config().get("display", {}).get("running_indicator_pulse", True))
    except Exception:
        return True


def _animate_counters_enabled() -> bool:
    """AnimatedCounter smooth easing on numeric values (default: true)."""
    try:
        from hermes_cli.config import read_raw_config
        return bool(read_raw_config().get("display", {}).get("animate_counters", True))
    except Exception:
        return True


def _fps_hud_enabled() -> bool:
    """FPS/ms HUD overlay — off by default, toggleable at runtime (default: false)."""
    try:
        from hermes_cli.config import read_raw_config
        return bool(read_raw_config().get("display", {}).get("fps_hud", False))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Safe widget call helper
# ---------------------------------------------------------------------------

def _safe_widget_call(app: "Any", widget_type: type, method: str, *args: "Any") -> None:
    """Query a widget and call a method on it, swallowing NoMatches during teardown.

    Both the query and the method call execute on the event loop (the DOM is
    owned by the event loop thread). Callers from other threads must wrap this
    in ``app.call_from_thread(_safe_widget_call, app, ...)``.
    """
    from textual.css.query import NoMatches
    try:
        getattr(app.query_one(widget_type), method)(*args)
    except NoMatches:
        pass  # widget removed during teardown — safe to ignore


# ---------------------------------------------------------------------------
# Compact format helpers (pure — no widget deps)
# ---------------------------------------------------------------------------

def _format_compact_tokens(value: int) -> str:
    """Format token counts as short lowercase units, e.g. 96000 -> 96k."""
    value = max(0, int(value))
    if value >= 1_000_000:
        scaled = value / 1_000_000
        return f"{scaled:.1f}".rstrip("0").rstrip(".") + "m"
    if value >= 1_000:
        scaled = value / 1_000
        rounded = round(scaled)
        if abs(scaled - rounded) < 0.05:
            return f"{rounded}k"
        return f"{scaled:.1f}".rstrip("0").rstrip(".") + "k"
    return str(value)


def _format_elapsed_compact(seconds: float) -> str:
    """Format response elapsed time compactly for message headers."""
    seconds = max(0.0, float(seconds))
    if seconds < 10:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, sec = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


# Avoid NameError at annotation evaluation time
from typing import Any  # noqa: E402
