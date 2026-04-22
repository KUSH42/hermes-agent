"""Shared constants, helpers, and the OmissionBar widget.

Kept in a separate module to break the circular dependency:
  _block.py  → needs OmissionBar (used by StreamingToolBlock.on_mount)
  _streaming.py → inherits ToolBlock from _block.py AND defines OmissionBar

Moving OmissionBar here lets _block.py and _streaming.py both import from _shared.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from rich.text import Text
from textual.css.query import NoMatches
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Static

from hermes_cli.tui.resize_utils import THRESHOLD_NARROW, crosses_threshold
from hermes_cli.tui.tooltip import TooltipMixin
from hermes_cli.tui.widgets import (
    CopyableRichLog,
    _boost_layout_caches,
    _skin_color,
    _strip_ansi,
)

# ---------------------------------------------------------------------------
# Public re-exports of imported names (so __init__.py can get them from here)
# ---------------------------------------------------------------------------
# (re-exported directly by __init__.py)

COLLAPSE_THRESHOLD = 3  # >N lines → collapsed by default

# ---------------------------------------------------------------------------
# Link detection helpers
# ---------------------------------------------------------------------------

_LINK_URL_RE = re.compile(r'https?://[^\s<>"\']+')
_LINK_PATH_RE = re.compile(
    r"(?<![=:\w/])(/[\w./\-_]+|\.{1,2}/[\w./\-_]+)(?![\w])"
)
_LINK_TRAIL_RE = re.compile(r'[.,;:!?)\]>]+$')


def _linkify_text(plain: str, rich_text: "Text") -> "Text":
    """Apply underline+bold + click meta to URL and file-path spans (E3)."""
    import os as _os
    from rich.style import Style as _Style

    url_ranges: list[tuple[int, int]] = []
    for m in _LINK_URL_RE.finditer(plain):
        url_ranges.append((m.start(), m.end()))

    def _in_url(start: int, end: int) -> bool:
        return any(us <= start and end <= ue for us, ue in url_ranges)

    for m in _LINK_URL_RE.finditer(plain):
        raw_target = m.group(0)
        target = _LINK_TRAIL_RE.sub("", raw_target)
        start, end = m.start(), m.start() + len(target)
        rich_text.stylize(_Style(underline=True, bold=True, meta={"_link_url": target}), start, end)

    for m in _LINK_PATH_RE.finditer(plain):
        raw_target = m.group(0)
        target = _LINK_TRAIL_RE.sub("", raw_target)
        start, end = m.start(), m.start() + len(target)
        if _in_url(start, end):
            continue
        abs_path = _os.path.abspath(target)
        url = f"file://{abs_path}"
        rich_text.stylize(_Style(underline=True, bold=True, meta={"_link_url": url}), start, end)

    return rich_text


def _first_link(plain: str) -> "str | None":
    """Return the first URL or file:// path found in *plain*, or None."""
    import os as _os
    m = _LINK_URL_RE.search(plain)
    if m:
        return _LINK_TRAIL_RE.sub("", m.group(0))
    m = _LINK_PATH_RE.search(plain)
    if m:
        target = _LINK_TRAIL_RE.sub("", m.group(0))
        return f"file://{_os.path.abspath(target)}"
    return None


def _build_args_row_text(spec: "object", tool_input: "dict | None") -> "str | None":
    """Format non-primary tool args as a dim 'key: value' row string."""
    if not tool_input:
        return None
    primary_key = getattr(spec, "primary_arg", None)
    parts: list[str] = []
    for k, v in tool_input.items():
        if k == primary_key:
            continue
        v_str = str(v)
        if len(v_str) > 60:
            v_str = v_str[:59] + "…"
        parts.append(f"{k}: {v_str}")
    return "  ".join(parts) if parts else None


# StreamingToolBlock constants
_VISIBLE_CAP = 200          # max lines shown in the RichLog
THRESHOLD_NARROW = 60       # D2: OmissionBar collapses to 2 buttons below this width
_LINE_BYTE_CAP = 2000       # truncate single lines beyond this many chars
_PAGE_SIZE = 50             # lines per [+]/[-] step in OmissionBar
_SPINNER_FRAMES: tuple[str, ...] = (
    "⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏",
)

# Gutter fallback color
_GUTTER_FALLBACK: str = "#FFD700"

_FILE_TOOL_NAMES: frozenset[str] = frozenset({
    "patch", "read_file", "write_file", "create_file",
    "edit_file", "str_replace_editor", "view",
})
_URL_SCHEMES: tuple[str, ...] = ("http://", "https://", "ftp://", "file://")
_DIFF_PATH_RE = re.compile(r"^(?:---|\+\+\+)\s+(?:[ab]/)?(.+)$")
_DIFF_OLD_RE = re.compile(r"^--- (a/(.+)|/dev/null)")
_DIFF_NEW_RE = re.compile(r"^\+\+\+ (b/(.+)|/dev/null)")
_DIFF_HEADER_RE = re.compile(r"^((?:---|\+\+\+)\s+)(?:[ab]/)?(.+)$")
_DIFF_ARROW_RE = re.compile(r"^(.+?)\s+→\s+(.+)$")

_IMAGE_EXTS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"})
_MEDIA_LINE_RE = re.compile(r"(?m)^MEDIA:\s*\S.*$")


class ImageMounted(Message):
    """Posted by StreamingToolBlock after an InlineImage is mounted."""
    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path


_MEDIA_EXTRACT_RE = re.compile(r"^MEDIA:\s*(.+)$", re.IGNORECASE)


def _extract_image_path(raw: str) -> "str | None":
    """Return path string if raw is a MEDIA: line or a bare image path."""
    from pathlib import Path as _Path
    m = _MEDIA_EXTRACT_RE.match(raw.strip())
    if m:
        path = m.group(1).strip()
        return path if _Path(path).suffix.lower() in _IMAGE_EXTS else None
    suffix = _Path(raw.strip()).suffix.lower()
    return raw.strip() if suffix in _IMAGE_EXTS else None


_CODE_EXT_MAP: dict[str, str] = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "tsx",
    ".rs": "rust", ".go": "go", ".java": "java", ".c": "c", ".cpp": "cpp",
    ".h": "c", ".rb": "ruby", ".sh": "bash", ".bash": "bash", ".zsh": "zsh",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
    ".sql": "sql", ".html": "html", ".css": "css", ".md": "markdown",
    ".kt": "kotlin", ".scala": "scala", ".php": "php", ".swift": "swift",
}


def _code_lang(path: str) -> str:
    """Return pygments language id for path, or '' if not a recognised code file."""
    import os
    return _CODE_EXT_MAP.get(os.path.splitext(path)[-1].lower(), "")


def _word_diff(removed: str, added: str) -> "tuple[Text, Text]":
    """Word-level diff between two lines. Returns (removed_text, added_text)."""
    import difflib
    rem_words = removed.split()
    add_words = added.split()
    sm = difflib.SequenceMatcher(None, rem_words, add_words, autojunk=False)
    rem_t = Text()
    add_t = Text()
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            rem_t.append(" ".join(rem_words[i1:i2]) + " ")
            add_t.append(" ".join(add_words[j1:j2]) + " ")
        elif tag == "replace":
            rem_t.append(" ".join(rem_words[i1:i2]) + " ", style="bold underline")
            add_t.append(" ".join(add_words[j1:j2]) + " ", style="bold underline")
        elif tag == "delete":
            rem_t.append(" ".join(rem_words[i1:i2]) + " ", style="bold underline")
        elif tag == "insert":
            add_t.append(" ".join(add_words[j1:j2]) + " ", style="bold underline")
    return rem_t, add_t


def _safe_cell_width(s: str) -> int:
    """Return cell width of s; fall back to len(s) if wcwidth unavailable."""
    try:
        from wcwidth import wcswidth
        w = wcswidth(s)
        return w if w >= 0 else len(s)
    except ImportError:
        return len(s)


def _secondary_args_text(category: "Any", tool_input: "dict | None") -> str:
    """Extract secondary display text from tool input args (B1)."""
    if not tool_input:
        return ""
    try:
        from hermes_cli.tui.tool_category import ToolCategory as _TC
        if category == _TC.FILE:
            content = tool_input.get("content") or tool_input.get("new_content") or ""
            if content:
                chars = len(content)
                lines = content.count("\n") + 1
                return f"content: {chars} chars · {lines} lines"
            offset = tool_input.get("offset")
            limit = tool_input.get("limit")
            parts = []
            if offset is not None:
                parts.append(f"offset: {offset}")
            if limit is not None:
                parts.append(f"limit: {limit}")
            return " · ".join(parts)

        if category == _TC.SHELL:
            parts = []
            env = tool_input.get("env") or {}
            if env and isinstance(env, dict):
                kv = next(iter(env.items()))
                parts.append(f"env: {kv[0]}={kv[1]}")
            cwd = tool_input.get("cwd") or tool_input.get("working_dir")
            if cwd:
                import os
                if cwd != os.getcwd():
                    parts.append(f"cwd: {cwd}")
            return " · ".join(parts)

        if category == _TC.SEARCH:
            glob_pat = tool_input.get("glob") or tool_input.get("include") or tool_input.get("file_pattern")
            if glob_pat:
                return f"glob: {glob_pat}"
            return ""

        if category == _TC.WEB:
            headers = tool_input.get("headers") or {}
            if headers and isinstance(headers, dict):
                return f"headers: {len(headers)}"
            return ""

        if category == _TC.AGENT:
            text = tool_input.get("task") or tool_input.get("thought") or ""
            if text:
                text = str(text)
                if len(text) > 80:
                    return text[:79] + "…"
                return text
            return ""

        if category == _TC.MCP:
            _META_KEYS = frozenset({"name", "server", "tool"})
            pairs = [(k, v) for k, v in tool_input.items() if k not in _META_KEYS][:2]
            if pairs:
                return "args: " + ", ".join(f"{k}: {v}" for k, v in pairs)
            return ""

    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# v4 §2.2 — unified duration rule
# ---------------------------------------------------------------------------

def _format_duration_v4(elapsed_ms: float) -> str:
    """E4: extended duration formatter covering ms → hours."""
    if elapsed_ms < 50:
        return ""
    if elapsed_ms < 5000:
        return f"{int(elapsed_ms)}ms"
    if elapsed_ms < 60_000:
        return f"{elapsed_ms / 1000:.1f}s"
    if elapsed_ms < 600_000:
        return f"{int(elapsed_ms / 1000)}s"
    if elapsed_ms < 3_600_000:
        mins = int(elapsed_ms / 60_000)
        secs = int((elapsed_ms % 60_000) / 1000)
        return f"{mins}m{secs}s"
    hours = int(elapsed_ms / 3_600_000)
    mins = int((elapsed_ms % 3_600_000) / 60_000)
    return f"{hours}h{mins}m"


# ---------------------------------------------------------------------------
# v4 §2.1 — primary-arg header label
# ---------------------------------------------------------------------------

_AGENT_PRIMARY_ARGS: frozenset[str] = frozenset({"thought", "description", "task"})
_AGENT_MAX_CELLS: int = 40
_TRUNCATION_MARGIN: int = 3

_DIFF_ADD_FALLBACK: str = "#5fd75f"
_DIFF_DEL_FALLBACK: str = "#ef5350"
_RUNNING_FALLBACK: str = "#c0c0c0"
_VISIBLE_DIFF_ROW_RE = re.compile(r"^\s*\d+\s+([+-])\s")


@dataclass(frozen=True, slots=True)
class ToolHeaderStats:
    additions: int = 0
    deletions: int = 0

    @property
    def has_diff_counts(self) -> bool:
        return self.additions > 0 or self.deletions > 0


def _count_visible_diff_rows(lines: list[str]) -> ToolHeaderStats | None:
    additions = 0
    deletions = 0
    for line in lines:
        match = _VISIBLE_DIFF_ROW_RE.match(line)
        if not match:
            continue
        if match.group(1) == "+":
            additions += 1
        else:
            deletions += 1
    if additions == 0 and deletions == 0:
        return None
    return ToolHeaderStats(additions=additions, deletions=deletions)


def header_label_v4(
    spec: "Any",
    args: dict,
    full_label: str,
    full_path: "str | None",
    available: int,
    accent_color: str = "",
) -> "Text":
    """Return header label Text using v4 primary-arg rules (spec §2.1)."""
    primary = getattr(spec, "primary_arg", None)

    try:
        from hermes_cli.tui.tool_category import ToolCategory as _TC
        cat = getattr(spec, "category", None)
        if cat == _TC.MCP:
            prov = getattr(spec, "provenance", None) or ""
            server = prov[4:] if prov.startswith("mcp:") else "?"
            name = getattr(spec, "name", "") or ""
            method = name.split("__", 2)[-1] if "__" in name else name
            label_str = f"{server}::{method}()"
            avail = available
            if _safe_cell_width(label_str) > avail:
                if avail < 8:
                    label_str = "[MCP]"
                else:
                    head_len = max(4, avail // 2 - 1)
                    tail_len = avail - head_len - 1
                    label_str = label_str[:head_len] + "…" + label_str[-tail_len:] if tail_len > 0 else label_str[:head_len] + "…"
            t = Text()
            t.append(f" {label_str}", style="bold")
            return t
        if cat == _TC.AGENT and primary not in ("path", "command", "query", "url"):
            text = str(args.get("task") or args.get("thought") or "") or full_label
            if len(text) > 60:
                text = text[:59] + "…"
            t = Text()
            t.append(f" {text}", style="italic dim")
            return t
        if cat == _TC.UNKNOWN and primary is None:
            t = Text()
            label_str = full_label
            if _safe_cell_width(label_str) > available:
                label_str = label_str[:max(1, available - 1)] + "…"
            t.append(f" {label_str}")
            return t
    except Exception:
        pass

    if primary == "path":
        path = full_path or full_label
        parts = path.rsplit("/", 1)
        if len(parts) == 2 and parts[0]:
            dir_part, fname = parts[0] + "/", parts[1]
        else:
            dir_part, fname = "", path
        fname_w = _safe_cell_width(fname)
        dir_budget = max(0, available - fname_w - 1)
        if _safe_cell_width(dir_part) > dir_budget:
            trimmed = dir_part
            while trimmed and _safe_cell_width("…/" + trimmed) > dir_budget:
                trimmed = trimmed.split("/", 1)[-1] if "/" in trimmed else ""
            dir_part = ("…/" + trimmed) if trimmed else "…/"
        t = Text()
        t.append(" " + dir_part if dir_part else " ", style="dim")
        t.append(fname, style="bold underline")
        start = args.get("start_line")
        end = args.get("end_line")
        lr = args.get("line_range")
        if isinstance(lr, (list, tuple)) and len(lr) == 2:
            t.append(f":{lr[0]}-{lr[1]}", style="dim")
        elif start is not None and end is not None:
            t.append(f":{start}-{end}", style="dim")
        return t

    if primary == "command":
        label_str = full_label
        trunc = available - _TRUNCATION_MARGIN
        if _safe_cell_width(label_str) > trunc:
            label_str = label_str[:max(1, trunc - 1)] + "…"
        t = Text()
        cat = getattr(spec, "category", None)
        try:
            from hermes_cli.tui.tool_category import ToolCategory as _TC
            _is_shell = cat == _TC.SHELL
        except Exception:
            _is_shell = False
        if accent_color and _is_shell:
            t.append(" $", style=f"bold {accent_color}")
        t.append(f" {label_str}", style="italic")
        return t

    if primary == "query":
        label_str = full_label
        trunc = available - 2 - _TRUNCATION_MARGIN
        if _safe_cell_width(label_str) > trunc:
            label_str = label_str[:max(1, trunc - 1)] + "…"
        t = Text()
        t.append(f" {label_str}", style="bold")
        return t

    if primary == "url":
        url = full_path or full_label
        for scheme in ("https://", "http://", "ftp://"):
            if url.startswith(scheme):
                rest = url[len(scheme):]
                host_end = rest.find("/")
                host = rest[:host_end] if host_end != -1 else rest
                path_part = rest[host_end:] if host_end != -1 else ""
                path_avail = available - len(scheme) - len(host) - 1
                if len(path_part) > path_avail:
                    path_part = path_part[:max(0, path_avail - 1)] + "…"
                t = Text()
                t.append(f" {scheme}", style="dim")
                t.append(host, style="bold")
                t.append(path_part, style="dim")
                return t
        t = Text()
        label_str = full_label
        if _safe_cell_width(label_str) > available:
            label_str = label_str[:max(1, available - 1)] + "…"
        t.append(f" {label_str}")
        return t

    if primary in _AGENT_PRIMARY_ARGS:
        label_str = full_label
        if _safe_cell_width(label_str) > _AGENT_MAX_CELLS:
            label_str = label_str[:_AGENT_MAX_CELLS - 1] + "…"
        t = Text()
        t.append(f" {label_str}", style="italic dim")
        return t

    # None or unknown primary → plain label
    label_str = full_label
    if _safe_cell_width(label_str) > available:
        label_str = label_str[:max(1, available - 1)] + "…"
    t = Text()
    t.append(f" {label_str}")
    return t


# ---------------------------------------------------------------------------
# OmissionBar — interactive expand/collapse controls for the line cap
# ---------------------------------------------------------------------------

class OmissionBar(TooltipMixin, Widget):
    """Dual-position omission bar for StreamingToolBlock.

    G1: Two visible buttons by default; advanced buttons behind [more ▸] toggle.

    position="top"    → default: [↑all]; advanced: [↑+50]
    position="bottom" → default: [show all] [hide]; advanced: [↑] [↓+N] [reset]
    """

    DEFAULT_CSS = """
    OmissionBar {
        layout: horizontal;
        height: 1;
        padding: 0 1;
    }
    """

    _tooltip_text = "Scroll output window"

    @staticmethod
    def _reset_label() -> str:
        """C4: icon-mode-aware label for reset button."""
        try:
            from agent.display import get_tool_icon_mode
            mode = get_tool_icon_mode()
        except Exception:
            mode = "ascii"
        if mode in ("nerdfont", "auto"):
            return "\U000f09a8 reset"
        if mode == "emoji":
            return "🔄 reset"
        return "[reset]"

    def __init__(
        self,
        parent_block: "Any",  # StreamingToolBlock — forward ref avoids circular
        position: str = "bottom",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._parent_block = parent_block
        self.position = position
        self._visible_start: int = 0
        self._visible_end: int = 0
        self._total: int = 0
        self._label: Static | None = None
        self._cap_label: Static | None = None
        self._last_resize_w: int = 0
        self._narrow: bool = False
        # G1: advanced buttons toggle state
        self._advanced_visible: bool = False

    def compose(self):
        from textual.app import ComposeResult
        label = Static("", classes="--ob-label")
        self._label = label
        cap_label = Static("", classes="--cap-label")
        self._cap_label = cap_label
        yield label
        yield cap_label
        if self.position == "top":
            # G1: default visible
            yield Button("[↑all]", classes="--ob-up-all")
            # G1: advanced (hidden by default)
            yield Button("[↑+50]", classes="--ob-up-page --ob-advanced", disabled=False)
            yield Button("[more ▸]", classes="--ob-more")
        else:
            # G1: default visible — show all / hide (Rich Text avoids markup bracket parsing)
            from rich.text import Text as _T
            yield Button(_T("[show all]"), classes="--ob-down-all")
            yield Button(_T("[hide]"),     classes="--ob-cap")
            # G1: advanced (hidden by default)
            yield Button("[↑]",          classes="--ob-up --ob-advanced")
            yield Button("[↓]",          classes="--ob-down --ob-advanced")
            yield Button(self._reset_label(), classes="--ob-cap-adv --ob-advanced")
            yield Button("[more ▸]", classes="--ob-more")

    def on_mount(self) -> None:
        """G1: hide advanced buttons initially."""
        self._set_advanced_visible(False)

    def _set_advanced_visible(self, visible: bool) -> None:
        """G1: show/hide advanced buttons and update [more ▸] label."""
        self._advanced_visible = visible
        try:
            for btn in self.query(".--ob-advanced"):
                btn.display = visible
            more_btn = self.query_one(".--ob-more", Button)
            more_btn.label = "[less ◂]" if visible else "[more ▸]"
        except NoMatches:
            pass

    def on_resize(self, event: Any) -> None:
        w = self.size.width
        now_narrow = w < THRESHOLD_NARROW
        if now_narrow != self._narrow:
            self._narrow = now_narrow
            self._sync_narrow_layout()
        if crosses_threshold(self._last_resize_w, w, THRESHOLD_NARROW):
            if self._label is not None:
                self._label.display = w >= THRESHOLD_NARROW
        self._last_resize_w = w

    def _sync_narrow_layout(self) -> None:
        if self.position != "bottom":
            return
        try:
            if self._narrow:
                # In narrow mode, hide advanced panel and [↓all] / [↑] buttons
                if self._advanced_visible:
                    self._set_advanced_visible(False)
                try:
                    self.query_one(".--ob-down-all", Button).display = False
                except NoMatches:
                    pass
            else:
                # Restore [↓all] visibility
                try:
                    self.query_one(".--ob-down-all", Button).display = True
                except NoMatches:
                    pass
                down_btn = self.query_one(".--ob-down", Button)
                vs, ve, tot = self._visible_start, self._visible_end, self._total
                step_below = min(_PAGE_SIZE, tot - ve)
                down_btn.label = f"[↓+{step_below}]" if step_below > 0 else "[↓+0]"
        except NoMatches:
            pass

    def set_counts(
        self,
        visible_start: int,
        visible_end: int,
        total: int,
        above: int | None = None,
        below: int | None = None,
        cap_msg: str | None = None,
        visible_cap: int = _VISIBLE_CAP,  # H1: honour per-block cap override
    ) -> None:
        """Cache counts and update label + disabled states (B1/B2/B3)."""
        self._visible_start = visible_start
        self._visible_end = visible_end
        self._total = total
        if self._label is None:
            return
        try:
            all_showing = (visible_end - visible_start) == total
            if all_showing:
                self._label.update("")
            else:
                self._label.update(f"  {visible_start + 1}–{visible_end} of {total}  ")

            if self.position == "top":
                step_above = min(_PAGE_SIZE, visible_start)
                at_top = visible_start == 0
                try:
                    up_all_btn = self.query_one(".--ob-up-all", Button)
                    up_all_btn.disabled = at_top
                    up_page_btn = self.query_one(".--ob-up-page", Button)
                    up_page_btn.label = f"[↑+{step_above}]" if step_above > 0 else "[↑+0]"
                    up_page_btn.disabled = step_above == 0
                except NoMatches:
                    pass
            else:
                step_below = min(_PAGE_SIZE, total - visible_end)
                at_default = (
                    visible_start == 0
                    and (visible_end - visible_start) <= visible_cap  # H1
                )
                at_end = visible_end >= total
                try:
                    # G1: [hide] = reset to default view
                    self.query_one(".--ob-cap", Button).disabled = at_default
                    # G1: advanced [↑] button
                    self.query_one(".--ob-up", Button).disabled = at_default
                    # G1: advanced [↓+N] button
                    down_btn = self.query_one(".--ob-down", Button)
                    down_btn.label = f"[↓+{step_below}]" if step_below > 0 else "[↓+0]"
                    down_btn.disabled = at_end
                    # G1: [show all]
                    self.query_one(".--ob-down-all", Button).disabled = at_end
                except NoMatches:
                    pass

            if self._cap_label is not None:
                if cap_msg:
                    self._cap_label.update(cap_msg)
                    self._cap_label.add_class("--visible")
                else:
                    self._cap_label.update("")
                    self._cap_label.remove_class("--visible")
        except NoMatches:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        pb = self._parent_block
        vs, ve, tot = self._visible_start, self._visible_end, self._total
        classes = event.button.classes
        # G1: [more ▸] / [less ◂] toggle
        if "--ob-more" in classes:
            self._set_advanced_visible(not self._advanced_visible)
            event.stop()
            return
        if "--ob-up-all" in classes:
            pb.rerender_window(0, ve)
        elif "--ob-up-page" in classes:
            pb.rerender_window(max(0, vs - _PAGE_SIZE), ve)
        elif "--ob-cap" in classes:
            # G1: [hide] = reset to default view
            pb.rerender_window(0, _VISIBLE_CAP)
        elif "--ob-cap-adv" in classes:
            # G1: advanced [reset] = full reset
            pb.rerender_window(0, _VISIBLE_CAP)
        elif "--ob-up" in classes:
            pb.rerender_window(
                max(0, vs - _PAGE_SIZE),
                max(_VISIBLE_CAP, ve - _PAGE_SIZE),
            )
        elif "--ob-down" in classes:
            pb.rerender_window(vs, min(tot, ve + _PAGE_SIZE))
        elif "--ob-down-all" in classes:
            pb.rerender_window(vs, tot)
        event.stop()

