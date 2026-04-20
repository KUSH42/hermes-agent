"""ToolBlock widgets for displaying collapsible tool output in the TUI.

ToolBlock groups a ToolHeader (single-line label with toggle/copy affordances)
and a ToolBodyContainer (collapsible content area). Blocks with ≤3 lines are
auto-expanded with no toggle or copy affordance.

StreamingToolBlock extends ToolBlock with IDLE→STREAMING→COMPLETED lifecycle,
60fps render throttle, 200-line visible cap, and 2 kB per-line byte cap.
"""

from __future__ import annotations

import collections
from collections import deque
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from rich.text import Text
from textual.app import ComposeResult, RenderResult
from textual.css.query import NoMatches
from textual.events import Click
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Static

from hermes_cli.tui.animation import PulseMixin, lerp_color
from hermes_cli.tui.resize_utils import THRESHOLD_NARROW, crosses_threshold
from hermes_cli.tui.tooltip import TooltipMixin
from hermes_cli.tui.widgets import (
    CopyableRichLog,
    _boost_layout_caches,
    _skin_color,
    _strip_ansi,
)

COLLAPSE_THRESHOLD = 3  # >N lines → collapsed by default

# ---------------------------------------------------------------------------
# Link detection helpers (used by _linkify_text / _first_link)
# ---------------------------------------------------------------------------

_LINK_URL_RE = re.compile(r'https?://[^\s<>"\']+')
_LINK_PATH_RE = re.compile(
    r"(?<![=:\w/])(/[\w./\-_]+|\.{1,2}/[\w./\-_]+)(?![\w])"
)
_LINK_TRAIL_RE = re.compile(r'[.,;:!?)\]>]+$')


def _linkify_text(plain: str, rich_text: "Text") -> "Text":
    """Apply underline + click meta to URL and file-path spans.

    Operates on *plain* for regex matching so ANSI codes don't shift offsets,
    then stylizes the corresponding span on *rich_text* (which was built from
    the same content).  Underline only — no color override so existing ANSI
    colors are preserved.
    """
    import os as _os
    from rich.style import Style as _Style

    # Collect URL spans first so path matches inside URLs are skipped
    url_ranges: list[tuple[int, int]] = []
    for m in _LINK_URL_RE.finditer(plain):
        url_ranges.append((m.start(), m.end()))

    def _in_url(start: int, end: int) -> bool:
        return any(us <= start and end <= ue for us, ue in url_ranges)

    for m in _LINK_URL_RE.finditer(plain):
        raw_target = m.group(0)
        target = _LINK_TRAIL_RE.sub("", raw_target)
        start, end = m.start(), m.start() + len(target)
        rich_text.stylize(_Style(underline=True, meta={"_link_url": target}), start, end)

    for m in _LINK_PATH_RE.finditer(plain):
        raw_target = m.group(0)
        target = _LINK_TRAIL_RE.sub("", raw_target)
        start, end = m.start(), m.start() + len(target)
        if _in_url(start, end):
            continue
        abs_path = _os.path.abspath(target)
        url = f"file://{abs_path}"
        rich_text.stylize(_Style(underline=True, meta={"_link_url": url}), start, end)

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
    """Format non-primary tool args as a dim 'key: value' row string.

    Returns None when there is nothing to show (no secondary args).
    """
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
_LINE_BYTE_CAP = 2000       # truncate single lines beyond this many chars
_PAGE_SIZE = 50             # lines per [+]/[-] step in OmissionBar
_SPINNER_FRAMES: tuple[str, ...] = (
    "⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏",
)

# Gutter fallback color — avoid duplicating the literal across three call sites
_GUTTER_FALLBACK: str = "#FFD700"

_FILE_TOOL_NAMES: frozenset[str] = frozenset({
    "patch", "read_file", "write_file", "create_file",
    "edit_file", "str_replace_editor", "view",
})
_URL_SCHEMES: tuple[str, ...] = ("http://", "https://", "ftp://", "file://")
_DIFF_PATH_RE = re.compile(r"^(?:---|\+\+\+)\s+(?:[ab]/)?(.+)$")
# Stricter git-format matchers: require a/ b/ prefix to avoid matching bare "---"
_DIFF_OLD_RE = re.compile(r"^--- (a/(.+)|/dev/null)")
_DIFF_NEW_RE = re.compile(r"^\+\+\+ (b/(.+)|/dev/null)")
_DIFF_HEADER_RE = re.compile(r"^((?:---|\+\+\+)\s+)(?:[ab]/)?(.+)$")
# Rendered diff file-header line: "a/src/foo.py → b/src/foo.py" (after ANSI strip)
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
    """Extract secondary display text from tool input args (B1).

    Returns '' if nothing to show.
    """
    if not tool_input:
        return ""
    try:
        from hermes_cli.tui.tool_category import ToolCategory as _TC
        if category == _TC.FILE:
            # Write: content size
            content = tool_input.get("content") or tool_input.get("new_content") or ""
            if content:
                chars = len(content)
                lines = content.count("\n") + 1
                return f"content: {chars} chars · {lines} lines"
            # Read: offset/limit
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
    """<50 ms → omit; 50 ms–5 s → NNNms; >5 s → N.Ns."""
    if elapsed_ms < 50:
        return ""
    if elapsed_ms < 5000:
        return f"{int(elapsed_ms)}ms"
    return f"{elapsed_ms / 1000:.1f}s"


# ---------------------------------------------------------------------------
# v4 §2.1 — primary-arg header label
# ---------------------------------------------------------------------------

_AGENT_PRIMARY_ARGS: frozenset[str] = frozenset({"thought", "description", "task"})
_AGENT_MAX_CELLS: int = 40
_TRUNCATION_MARGIN: int = 3


def header_label_v4(
    spec: "Any",          # ToolSpec (avoid circular import at module level)
    args: dict,
    full_label: str,
    full_path: "str | None",
    available: int,
    accent_color: str = "",
) -> "Text":
    """Return header label Text using v4 primary-arg rules (spec §2.1)."""
    primary = getattr(spec, "primary_arg", None)

    # E3: category-based identity overrides for MCP and AGENT
    try:
        from hermes_cli.tui.tool_category import ToolCategory as _TC
        cat = getattr(spec, "category", None)
        if cat == _TC.MCP:
            # Format as server::method()
            prov = getattr(spec, "provenance", None) or ""
            server = prov[4:] if prov.startswith("mcp:") else "?"
            name = getattr(spec, "name", "") or ""
            method = name.split("__", 2)[-1] if "__" in name else name
            label_str = f"{server}::{method}()"
            if _safe_cell_width(label_str) > available:
                label_str = label_str[:max(1, available - 1)] + "…"
            t = Text()
            t.append(f" {label_str}", style="bold")
            return t
        if cat == _TC.AGENT and primary not in ("path", "command", "query", "url"):
            # First 60 chars of task or thought arg; fall back to full_label with italic dim
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
        # :{start}-{end} range suffix from args
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
        # $ prefix only for SHELL category (accent_color non-empty signals SHELL context)
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


class ToolHeader(TooltipMixin, PulseMixin, Widget):
    """Single-line header: '  ╌╌ {label}  {stats}  [▸/▾]'.

    During streaming ``_spinner_char`` replaces the toggle chevron.
    After completion ``_duration`` is appended to the label.

    Inherits PulseMixin — tool icon pulses green during streaming,
    settles to green (success) or red (error) on completion.
    """

    DEFAULT_CSS = "ToolHeader { height: 1; }"

    _tooltip_text = "Left-click: open/collapse  Right-click: menu"
    collapsed: reactive[bool] = reactive(True, repaint=True)

    def __init__(
        self,
        label: str,
        line_count: int,
        tool_name: str | None = None,
        stats: ToolHeaderStats | None = None,
        panel: "Any | None" = None,  # ToolPanel back-ref; None = legacy path (Phase 1)
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._label = label
        self._tool_name = tool_name
        self._line_count = line_count
        self._stats = stats
        self._panel = panel
        # ≤ threshold: always open, no affordances shown
        self._has_affordances = line_count > COLLAPSE_THRESHOLD
        self._copy_flash = False
        self._flash_msg: str | None = None
        self._flash_expires: float = 0.0
        # Streaming state — set by StreamingToolBlock
        self._spinner_char: str | None = None   # non-None while streaming
        self._duration: str = ""                # set on completion
        self._is_complete: bool = False         # True after _on_stream_complete
        self._tool_icon: str = ""
        # Icon color state
        self._tool_icon_error: bool = False
        # Rich-highlighted label (used by ExecuteCodeBlock to show syntax in header)
        self._label_rich: "Text | None" = None
        # Compact tail: no right-align padding, duration in normal color (execute_code)
        self._compact_tail: bool = False
        # Path-aware rendering
        self._is_child_diff: bool = False       # ╰─ gutter glyph for diff children
        self._full_path: str | None = None      # raw untruncated path or URL
        self._path_clickable: bool = False      # True for file-tool and URL headers
        self._is_url: bool = False              # True when path starts with http/https/etc.
        # Display overrides (v2 flags — kept for parity when tool_panel_v4=False)
        self._no_underline: bool = False         # suppress underline on clickable paths
        self._hide_duration: bool = False        # suppress timer display
        self._bold_label: bool = False           # bold label text (non-path)
        self._hidden: bool = False               # suppress header entirely
        self._shell_prompt: bool = False         # prepend "$ " in accent color before label
        # v4 fields
        self._elapsed_ms: float | None = None    # raw elapsed time for v4 duration rule
        self._header_args: dict = {}             # live tool args for primary-arg rendering
        self._primary_hero: str | None = None    # result summary primary shown in tail
        self._header_chips: list[tuple[str, str]] = []  # [(text, style)] promoted chips
        # v4 A1 — error kind for distinct icon/color
        self._error_kind: str | None = None
        # Browse mode badge (e.g. "± diff") — plain attr, render() reads it
        self._browse_badge: str = ""

    def on_mount(self) -> None:
        self._refresh_gutter_color()
        self._refresh_tool_icon()

    def _refresh_gutter_color(self) -> None:
        """Cache focused-gutter colour from CSS variables (supports hot-reload)."""
        try:
            css = self.app.get_css_variables()
            self._focused_gutter_color = css.get("rule-accent-color", _GUTTER_FALLBACK)
            self._diff_add_color = css.get("addition-marker-fg", _DIFF_ADD_FALLBACK)
            self._diff_del_color = css.get("deletion-marker-fg", _DIFF_DEL_FALLBACK)
            self._running_icon_color = css.get("status-running-color", _RUNNING_FALLBACK)
        except Exception:
            self._focused_gutter_color = _GUTTER_FALLBACK
            self._diff_add_color = _DIFF_ADD_FALLBACK
            self._diff_del_color = _DIFF_DEL_FALLBACK
            self._running_icon_color = _RUNNING_FALLBACK

    def _refresh_tool_icon(self) -> None:
        """Resolve current tool icon, so skin reloads can update header glyphs."""
        if not self._tool_name:
            self._tool_icon = ""
            return
        try:
            from agent.display import get_tool_icon
            self._tool_icon = get_tool_icon(self._tool_name)
        except Exception:
            try:
                from hermes_cli.tui.tool_category import spec_for, _CATEGORY_DEFAULTS
                spec = spec_for(self._tool_name)
                self._tool_icon = _CATEGORY_DEFAULTS[spec.category].ascii_fallback or "?"
            except Exception:
                self._tool_icon = "?"

    def _accessible_mode(self) -> bool:
        """Return True when low-color or HERMES_ACCESSIBLE=1 env var set (F1)."""
        import os
        if os.environ.get("HERMES_ACCESSIBLE"):
            return True
        try:
            cs = self.app.console.color_system
            return cs is None or cs == "standard"
        except Exception:
            return False

    def _render_v4(self) -> "Text | None":
        """v4 header render path. Returns Text or None to fall back to v2."""
        try:
            from hermes_cli.tui.tool_category import spec_for, ToolCategory
        except Exception:
            return None
        spec = spec_for(self._tool_name or "", args=self._header_args or None)
        # render_header=False → zero-height (replaces _hidden)
        if not spec.render_header:
            self.styles.height = 0
            return Text()

        focused = self.has_class("focused")
        t = Text()

        # F1: accessible mode state prefix
        if self._accessible_mode():
            if self._spinner_char is not None:
                t.append("[>] ", style="bold")
            elif self._tool_icon_error:
                t.append("[!] ", style="bold red")
            elif self._is_complete:
                t.append("[+] ", style="bold green")

        # Gutter
        if self._is_child_diff:
            gutter_text = Text("  ╰─", style="dim")
            gutter_w = 4
        elif focused:
            color = getattr(self, "_focused_gutter_color", _GUTTER_FALLBACK)
            gutter_text = Text("  ┃", style=f"bold {color}")
            gutter_w = 3
        else:
            gutter_text = Text("  ┊", style="dim")
            gutter_w = 3
        t.append_text(gutter_text)

        # Icon (shared with v2)
        icon_str = self._tool_icon or ""
        # B1: use error-kind icon in icon slot on failure
        if self._tool_icon_error and self._error_kind:
            try:
                from hermes_cli.tui.tool_result_parse import _error_kind_display
                from agent.display import get_tool_icon_mode
                _ek_icon, _, _ = _error_kind_display(self._error_kind, "", get_tool_icon_mode())
                if _ek_icon:
                    icon_str = _ek_icon
            except Exception:
                pass
        icon_cell_w = _safe_cell_width(icon_str) if icon_str else 0
        if icon_str:
            if self._spinner_char is not None:
                icon_dim = "#6e6e6e"
                icon_peak = getattr(self, "_running_icon_color", _RUNNING_FALLBACK)
                icon_color = lerp_color(icon_dim, icon_peak, self._pulse_t)
                icon_style = f"bold {icon_color}"
            elif self._tool_icon_error:
                err_color = getattr(self, "_diff_del_color", _DIFF_DEL_FALLBACK)
                icon_style = f"bold {err_color}"
            elif self._is_complete or self._duration:
                ok_color = getattr(self, "_diff_add_color", _DIFF_ADD_FALLBACK)
                icon_style = f"bold {ok_color}"
            else:
                icon_style = "dim"
            t.append(f" {icon_str}", style=icon_style)
        space_after_icon = 1

        # Shell prefix only for SHELL-category command tools
        shell_prompt_w = 0
        if spec.primary_arg == "command" and spec.category == ToolCategory.SHELL:
            accent = getattr(self, "_focused_gutter_color", _GUTTER_FALLBACK)
            t.append(" $", style=f"bold {accent}")
            shell_prompt_w = 2

        # Tail: duration uses v4 rule
        tail = Text()
        if self._spinner_char is not None:
            tail.append(f"  {self._spinner_char}", style="dim")
            if self._duration:
                tail.append(f"  {self._duration}", style="dim")
        else:
            if self._stats and self._stats.has_diff_counts:
                add_color = getattr(self, "_diff_add_color", _DIFF_ADD_FALLBACK)
                del_color = getattr(self, "_diff_del_color", _DIFF_DEL_FALLBACK)
                if self._stats.additions:
                    tail.append(f"  +{self._stats.additions}", style=f"bold {add_color}")
                if self._stats.deletions:
                    tail.append(f"  -{self._stats.deletions}", style=f"bold {del_color}")
            elif self._line_count and not self._primary_hero:
                tail.append(f"  {self._line_count}L", style="dim")
            # Hero chip: primary result summary (v4 §4.1)
            if self._primary_hero:
                if self._tool_icon_error and self._error_kind:
                    try:
                        from hermes_cli.tui.tool_result_parse import _error_kind_display
                        from agent.display import get_tool_icon_mode
                        _ek_icon, _, _ek_var = _error_kind_display(
                            self._error_kind, "", get_tool_icon_mode()
                        )
                        _ek_hex = self.app.get_css_variables().get(_ek_var, "#ef4444")
                        tail.append(f"  {_ek_icon} {self._primary_hero}", style=f"bold {_ek_hex}")
                    except Exception:
                        tail.append(f"  {self._primary_hero}", style="bold red")
                elif self._tool_icon_error:
                    tail.append(f"  {self._primary_hero}", style="bold red")
                else:
                    tail.append(f"  {self._primary_hero}", style="dim green")
            # Promoted chips (MCP source, exit code not already in hero, etc.)
            for chip_text, chip_style in (self._header_chips or []):
                tail.append(f"  {chip_text}", style=chip_style)
            if self._has_affordances:
                is_collapsed = self._panel.collapsed if self._panel is not None else self.collapsed
                tail.append("  ▸" if is_collapsed else "  ▾", style="dim")
            # Flash confirmation message (copy/open actions)
            now = time.monotonic()
            if self._flash_msg and now < self._flash_expires:
                tail.append(f"  ✓ {self._flash_msg}", style="dim green")
            if self._duration:   # already v4-formatted by _tick_duration / complete()
                tail.append(f"  {self._duration}", style="dim")

        # Label via primary-arg rules
        term_w = self.size.width
        tail_w = tail.cell_len
        FIXED_PREFIX_W = gutter_w + icon_cell_w + space_after_icon + shell_prompt_w
        available = max(8, term_w - FIXED_PREFIX_W - tail_w - 2) if term_w > 0 else 50
        if self._label_rich is not None:
            label_text = self._label_rich
            if label_text.cell_len > available:
                label_text = label_text.divide([available])[0]
                label_text.append("…", style="dim")
        else:
            label_text = header_label_v4(
                spec, self._header_args or {}, self._label,
                self._full_path, available,
                accent_color=getattr(self, "_focused_gutter_color", ""),
            )
        t.append_text(label_text)
        if term_w > 0:
            label_used = label_text.cell_len
            pad = max(0, available - label_used)
            t.append(" " * pad)
        t.append_text(tail)
        return t

    def render(self) -> RenderResult:
        result = self._render_v4()
        if result is not None:
            if self._browse_badge:
                result.append(f"  {self._browse_badge}", style="dim")
            return result
        # A3: degraded fallback — imports or render failed
        self.add_class("--header-degraded")
        t = Text()
        t.append(f"[tool] {self._label}")
        if self._browse_badge:
            t.append(f"  {self._browse_badge}", style="dim")
        return t

    def set_error(self, is_error: bool) -> None:
        """Mark tool result as error — icon turns red on completion."""
        self._tool_icon_error = is_error

    def flash_copy(self) -> None:
        """Flash ⎘ → ✓ for 1.5 s, then revert."""
        self._copy_flash = True
        self.refresh()
        self.set_timer(1.5, self._end_flash)

    def _end_flash(self) -> None:
        self._copy_flash = False
        self.refresh()

    def flash_success(self) -> None:
        """Green flash on successful completion."""
        self.add_class("--flash-success")
        self.set_timer(0.45, lambda: self.remove_class("--flash-success"))

    def flash_error(self) -> None:
        """Red flash on error completion."""
        self.add_class("--flash-error")
        self.set_timer(0.45, lambda: self.remove_class("--flash-error"))

    def flash_complete(self) -> None:
        """Deprecated: delegates to flash_success."""
        self.flash_success()

    def set_path(self, path: str) -> None:
        """Store full path/URL for path-aware rendering and context menu actions."""
        self._full_path = path
        self._path_clickable = True
        self._is_url = any(path.startswith(s) for s in _URL_SCHEMES)

    def set_args(self, args: dict) -> None:
        """Store live tool args for v4 primary-arg label rendering."""
        self._header_args = args
        self.refresh()

    def _render_path_label(self, max_cells: int) -> "Text":
        """Render dir (dim) + filename (bold), truncating dir prefix if needed."""
        path = self._full_path or self._label
        parts = path.rsplit("/", 1)
        if len(parts) == 2 and parts[0]:
            dir_part, fname = parts[0] + "/", parts[1]
        else:
            dir_part, fname = "", path

        fname_w = _safe_cell_width(fname)
        dir_budget = max(0, max_cells - fname_w - 1)  # -1 for leading space

        if _safe_cell_width(dir_part) > dir_budget:
            trimmed = dir_part
            while trimmed and _safe_cell_width("…/" + trimmed) > dir_budget:
                trimmed = trimmed.split("/", 1)[-1] if "/" in trimmed else ""
            dir_part = ("…/" + trimmed) if trimmed else "…/"

        t = Text()
        if dir_part:
            t.append(" " + dir_part, style="dim")
        else:
            t.append(" ", style="dim")
        fname_style = "bold" if self._no_underline else "bold underline"
        t.append(fname, style=fname_style)
        return t

    def on_click(self, event: Click) -> None:
        """Left-click: open file if path-clickable, otherwise toggle block.
        Double-click (finalized, no path): copy result summary to clipboard.
        Right-click (button=3): show context menu (C3).
        """
        if event.button == 3:
            self._show_context_menu(event)
            event.stop()
            return
        if event.button != 1:
            return                          # middle click: let bubble
        if self._spinner_char is not None:
            return                          # streaming: ignore click
        # Path-clickable header: open the file directly
        if self._path_clickable and self._full_path:
            event.prevent_default()
            import sys
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            try:
                self.app._open_path_action(self, self._full_path, opener, False)  # type: ignore[attr-defined]
            except Exception:
                pass
            return
        # Double-click on a finalized header with no path: copy result summary
        if event.chain == 2 and self._spinner_char is None and not self._path_clickable:
            try:
                parent = self.parent
                summary = getattr(parent, "_result_summary", None) or self._label
                self.app._copy_text_with_hint(str(summary))  # type: ignore[attr-defined]
            except Exception:
                pass
            event.prevent_default()
            return
        # Always allow toggle when wrapped in a ToolPanel — bypasses _has_affordances
        # guard so small-result blocks (≤3 lines) are still collapsible.
        panel = getattr(self, "_panel", None)
        if panel is not None:
            event.prevent_default()
            panel.action_toggle_collapse()
            return
        if not self._has_affordances:
            return                          # always-expanded legacy block: nothing to toggle
        event.prevent_default()
        parent = self.parent
        if parent is not None:
            parent.toggle()

    def _show_context_menu(self, event: Click) -> None:
        """C3: mount context menu on right-click."""
        import sys
        from pathlib import Path
        from hermes_cli.tui.context_menu import ContextMenu, MenuItem

        items: list[MenuItem] = []
        opener = "open" if sys.platform == "darwin" else "xdg-open"

        # Determine category for SHELL-specific option
        is_shell = False
        try:
            from hermes_cli.tui.tool_category import spec_for, ToolCategory
            _spec = spec_for(self._tool_name or "")
            is_shell = _spec.category == ToolCategory.SHELL
        except Exception:
            pass

        if self._path_clickable and self._full_path:
            _path = self._full_path  # closure capture
            items.append(MenuItem(
                label="Open file",
                shortcut="",
                action=lambda p=_path: self.app._open_path_action(self, p, opener, False),  # type: ignore[attr-defined]
            ))

        has_path = self._path_clickable or getattr(self, "_diff_file_path", None) is not None
        if has_path:
            _copy_path = self._full_path or getattr(self, "_diff_file_path", None)
            if _copy_path:
                items.append(MenuItem(
                    label="Copy path",
                    shortcut="",
                    action=lambda cp=_copy_path: self.app._copy_text_with_hint(cp),  # type: ignore[attr-defined]
                ))

        if is_shell:
            _cmd = str(self._header_args.get("command") or self._header_args.get("cmd") or self._label)
            items.append(MenuItem(
                label="Copy full command",
                shortcut="",
                action=lambda c=_cmd: self.app._copy_text_with_hint(c),  # type: ignore[attr-defined]
            ))

        if self._path_clickable and self._full_path:
            _parent = str(Path(self._full_path).parent)
            items.append(MenuItem(
                label="Reveal in file manager",
                shortcut="",
                action=lambda p=_parent: self.app._open_path_action(self, p, opener, False),  # type: ignore[attr-defined]
            ))

        if not items:
            return

        try:
            menu = self.app.query_one(ContextMenu)
            import asyncio
            asyncio.get_event_loop().create_task(
                menu.show(items, event.screen_x, event.screen_y)
            )
        except Exception:
            pass


class ToolBodyContainer(Widget):
    """Collapsible container for tool output lines."""

    DEFAULT_CSS = """
    ToolBodyContainer { height: auto; display: none; }
    ToolBodyContainer.expanded { display: block; }
    ToolBodyContainer .--microcopy { height: 1; display: none; color: $text-muted; padding: 0 2; }
    ToolBodyContainer .--microcopy.--active { display: block; }
    ToolBodyContainer .--args-row { height: auto; max-height: 2; padding: 0 2; display: none; color: $text-muted; }
    ToolBodyContainer .--args-row.--active { display: block; }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._secondary_text: str = ""
        self._microcopy_active: bool = False

    def compose(self) -> ComposeResult:
        # Args row — populated at completion with non-primary tool args
        yield Static("", classes="--args-row")
        # Microcopy row (v4 §3.3) — always present, shown when v4 active + elapsed≥0.5s
        yield Static("", classes="--microcopy")
        # No explicit ID — query by type inside ToolBodyContainer to avoid
        # duplicate IDs when multiple ToolBlocks exist per MessagePanel.
        yield CopyableRichLog(markup=False, highlight=False, wrap=False)

    def set_args_row(self, text: "str | None") -> None:
        """Show or hide the secondary-args row above body output."""
        try:
            w = self.query_one(".--args-row", Static)
        except Exception:
            return
        if text:
            w.update(text)
            w.add_class("--active")
        else:
            w.remove_class("--active")
            w.update("")

    def _mc_widget(self) -> "Static | None":
        try:
            return self.query_one(".--microcopy", Static)
        except Exception:
            return None

    def update_secondary_args(self, text: str) -> None:
        """Store secondary args text in the dedicated --args-row slot (P1-6).

        Uses the --args-row widget (above microcopy) so secondary args persist
        independently of microcopy state — set_microcopy() no longer overwrites them.
        """
        self._secondary_text = text
        self.set_args_row(text if text else None)

    def set_microcopy(self, text: "str | object") -> None:
        """Show streaming microcopy — takes precedence over secondary args (B1)."""
        self._microcopy_active = True
        mc = self._mc_widget()
        if mc is None:
            return
        mc.update(text)
        mc.remove_class("--secondary-args")
        mc.add_class("--active")

    def clear_microcopy(self) -> None:
        """Clear streaming microcopy. Does NOT restore secondary args (G2: completion
        result header is authoritative — secondary args are no longer shown)."""
        self._microcopy_active = False
        mc = self._mc_widget()
        if mc is None:
            return
        mc.remove_class("--active")
        mc.remove_class("--secondary-args")
        mc.update("")


class ToolBlock(Widget):
    """Collapsible widget pairing a ToolHeader with expandable body content.

    Lines with ≤ COLLAPSE_THRESHOLD are auto-expanded and show no toggle or
    copy affordance. Lines with > COLLAPSE_THRESHOLD start collapsed.

    Used for post-completion tool output summaries (diff previews, code/file
    previews, terminal output).  Content arrives all-at-once via ``lines`` /
    ``plain_lines`` and can be re-rendered on skin change via ``rerender_fn``.

    For real-time streaming output during tool execution, see
    ``StreamingToolBlock``.
    """

    DEFAULT_CSS = "ToolBlock { height: auto; }"
    _content_type: str = "tool"

    def __init__(
        self,
        label: str,
        lines: list[str],       # ANSI display lines
        plain_lines: list[str], # plain text for copy (no ANSI, no gutter)
        tool_name: str | None = None,
        rerender_fn: Callable[[], tuple[list[str], list[str]]] | None = None,
        header_stats: ToolHeaderStats | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        _boost_layout_caches(self)
        self._label = label
        self._tool_name = tool_name
        self._lines = list(lines)
        self._plain_lines = list(plain_lines)
        self._rerender_fn = rerender_fn if callable(rerender_fn) else None
        self._header_stats = header_stats if isinstance(header_stats, ToolHeaderStats) else None
        if self._header_stats is None and label == "diff":
            self._header_stats = _count_visible_diff_rows(self._plain_lines)
        auto_expand = len(lines) <= COLLAPSE_THRESHOLD
        self._header = ToolHeader(label, len(lines), tool_name=tool_name, stats=self._header_stats)
        self._body = ToolBodyContainer()
        if auto_expand:
            self._header.collapsed = False
            # _has_affordances is already False when line_count ≤ threshold

        # Per-tool display overrides
        if tool_name in ("read_file", "patch"):
            self._header._no_underline = True
        if tool_name in ("read_file", "search_files"):
            self._header._hide_duration = True
        if tool_name in ("search_files", "clarify"):
            self._header._bold_label = True
        if tool_name == "terminal":
            self._header._hidden = True

        # Path-aware header for file tools — not for "diff"/"code"/"output" labels
        if tool_name in _FILE_TOOL_NAMES and label not in ("diff", "code", "output"):
            self._header.set_path(label)

        # Diff body path parsing for context menu
        self._diff_file_path: str | None = None
        if label == "diff":
            _fallback: str | None = None
            for line in self._plain_lines:
                stripped = line.strip()
                # Strict git diff format: require "--- a/" or "+++ b/" prefix
                m_new = _DIFF_NEW_RE.match(stripped)
                if m_new:
                    new_path = m_new.group(2) or None  # None when /dev/null
                    if new_path:
                        self._diff_file_path = new_path
                        break
                    continue
                m_old = _DIFF_OLD_RE.match(stripped)
                if m_old:
                    old_path = m_old.group(2) or None  # None when /dev/null
                    if old_path and _fallback is None:
                        _fallback = old_path
                    continue
                # Rendered "old_path → new_path" format (from render_captured_diff_preview)
                m2 = _DIFF_ARROW_RE.match(stripped)
                if m2:
                    new_path = m2.group(2).strip()
                    if new_path.startswith("b/"):
                        new_path = new_path[2:]
                    if "/dev/null" not in new_path and new_path:
                        self._diff_file_path = new_path
                        break
            if self._diff_file_path is None:
                self._diff_file_path = _fallback
            # Make header path-clickable so left-click opens the file
            if self._diff_file_path:
                self._header.set_path(self._diff_file_path)

    def compose(self) -> ComposeResult:
        yield self._header
        yield self._body

    def on_mount(self) -> None:
        self._render_body()
        if not self._header.collapsed:
            self._body.add_class("expanded")

    def _render_diff_line(self, plain: str) -> "Text | None":
        """Return styled Rich Text for diff path lines. Delegates to FileRenderer."""
        try:
            from hermes_cli.tui.body_renderer import BodyRenderer
            from hermes_cli.tui.tool_category import ToolCategory
            return BodyRenderer.for_category(ToolCategory.FILE).render_diff_line(plain)
        except Exception:
            return None

    def _diff_bg_colors(self) -> tuple[str, str]:
        """Return (add_bg, del_bg) from skin component vars, falling back to defaults."""
        try:
            tm = getattr(self.app, "_theme_manager", None)
            if tm is not None:
                cvars: dict[str, str] = getattr(tm, "_component_vars", {})
                return cvars.get("diff-add-bg", "#1a3a1a"), cvars.get("diff-del-bg", "#3a1a1a")
        except Exception:
            pass
        return "#1a3a1a", "#3a1a1a"

    def _render_body(self) -> None:
        try:
            rl = self._body.query_one(CopyableRichLog)
            rl.clear()

            # Syntax highlighting for code files read by file tools
            if (
                self._tool_name in _FILE_TOOL_NAMES
                and self._label not in ("diff", "code", "output")
                and self._plain_lines
            ):
                lang = _code_lang(self._label)
                if lang:
                    try:
                        from rich.syntax import Syntax
                        rl.write(Syntax(
                            "\n".join(self._plain_lines),
                            lang,
                            line_numbers=True,
                            theme="monokai",
                        ))
                        return
                    except Exception:
                        pass  # fall through to plain render

            # Diff rendering with word-diff on adjacent -/+ lines
            if self._label == "diff":
                add_bg, del_bg = self._diff_bg_colors()
                pending_removed: str | None = None
                for styled, plain in zip(self._lines, self._plain_lines):
                    rich_line = self._render_diff_line(plain)
                    if rich_line is not None:
                        if pending_removed is not None:
                            t = Text("-", style="red")
                            t.append(pending_removed, style=f"on {del_bg}")
                            rl.write(t)
                            pending_removed = None
                        rl.write(rich_line)
                        continue
                    stripped = plain.rstrip("\n")
                    if stripped.startswith("-") and not stripped.startswith("---"):
                        if pending_removed is not None:
                            t = Text("-", style="red")
                            t.append(pending_removed, style=f"on {del_bg}")
                            rl.write(t)
                        pending_removed = stripped[1:]
                    elif stripped.startswith("+") and not stripped.startswith("+++"):
                        content = stripped[1:]
                        if pending_removed is not None:
                            rem_t, add_t = _word_diff(pending_removed, content)
                            rt = Text("-", style="red")
                            rt.append_text(rem_t)
                            rl.write(rt)
                            at = Text("+", style="green")
                            at.append_text(add_t)
                            rl.write(at)
                            pending_removed = None
                        else:
                            t = Text("+", style="green")
                            t.append(content, style=f"on {add_bg}")
                            rl.write(t)
                    else:
                        if pending_removed is not None:
                            t = Text("-", style="red")
                            t.append(pending_removed, style=f"on {del_bg}")
                            rl.write(t)
                            pending_removed = None
                        rl.write_with_source(Text.from_ansi(styled), plain)
                if pending_removed is not None:
                    t = Text("-", style="red")
                    t.append(pending_removed, style=f"on {del_bg}")
                    rl.write(t)
                if self._header_stats and self._header_stats.has_diff_counts and self._lines:
                    rl.write(Text(""))
                return

            # Plain render
            for styled, plain in zip(self._lines, self._plain_lines):
                rl.write_with_source(Text.from_ansi(styled), plain)
            if self._header_stats and self._header_stats.has_diff_counts and self._lines:
                rl.write(Text(""))
        except NoMatches:
            pass  # body not yet in DOM — safe to skip

    def toggle(self) -> None:
        """Toggle collapsed ↔ expanded. No-op for ≤3-line blocks."""
        panel = getattr(self._header, "_panel", None)
        if panel is not None:
            panel.action_toggle_collapse()
            return
        if not self._header._has_affordances:
            return
        self._header.collapsed = not self._header.collapsed
        if self._header.collapsed:
            self._body.remove_class("expanded")
        else:
            self._body.add_class("expanded")
        self._header.refresh()

    def copy_content(self) -> str:
        """Plain-text content for clipboard — no ANSI, no gutter, no line numbers."""
        return "\n".join(self._plain_lines)

    def refresh_skin(self) -> None:
        """Rebuild styled lines from canonical source when this block supports it."""
        if self._rerender_fn is not None:
            lines, plain_lines = self._rerender_fn()
            self._lines = list(lines)
            self._plain_lines = list(plain_lines)
        if self._label == "diff" and not isinstance(self._header_stats, ToolHeaderStats):
            self._header_stats = _count_visible_diff_rows(self._plain_lines)
        self._header._stats = self._header_stats
        self._header._line_count = len(self._lines)
        self._header._has_affordances = len(self._lines) > COLLAPSE_THRESHOLD
        self._header._refresh_gutter_color()
        self._header._refresh_tool_icon()
        if not self._header._has_affordances:
            self._header.collapsed = False
            self._body.add_class("expanded")
        self._render_body()
        self._header.refresh()
        self.refresh(layout=True)


# ---------------------------------------------------------------------------
# ToolTail — scroll-lock badge shown when auto-scroll is disengaged
# ---------------------------------------------------------------------------

class ToolTail(Static):
    """Single-line badge: '  ↓ N new lines' — right-aligned, dim.

    Hidden (``display: none``) when auto-scroll is active or the tool has
    completed.  Clicking it re-engages auto-scroll.
    """

    DEFAULT_CSS = """
    ToolTail {
        height: 1;
        display: none;
        text-align: right;
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self._new_line_count = 0

    def update_count(self, n: int) -> None:
        self._new_line_count = n
        if n > 0:
            self.update(f"  ↓ {n} new lines  ")
            self.display = True
        else:
            self.display = False

    def dismiss(self) -> None:
        self._new_line_count = 0
        self.display = False


# ---------------------------------------------------------------------------
# OmissionBar — interactive expand/collapse controls for the line cap
# ---------------------------------------------------------------------------

class OmissionBar(TooltipMixin, Widget):
    """Dual-position omission bar for StreamingToolBlock.

    position="top"    → shows lines above visible window; [↑all] [↑+50]
    position="bottom" → shows lines below visible window; [↑cap] [↑] [↓] [↓all]

    Both bars are always in the DOM from STB.on_mount(); display toggled by
    _refresh_omission_bars() as visible_start / visible_end change.
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
            return "\U000f09a8 reset"   # nf-md-restore U+F09A8
        if mode == "emoji":
            return "🔄 reset"
        return "[reset]"

    def __init__(
        self,
        parent_block: "StreamingToolBlock",
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
        self._last_resize_w: int = 0

    def compose(self) -> ComposeResult:
        label = Static("", classes="--ob-label")
        self._label = label
        yield label
        if self.position == "top":
            yield Button("[↑all]", classes="--ob-up-all")
            yield Button("[↑+50]", classes="--ob-up-page")
        else:
            yield Button(self._reset_label(), classes="--ob-cap")
            yield Button("[↑]",    classes="--ob-up")
            yield Button("[↓]",    classes="--ob-down")
            yield Button("[↓all]", classes="--ob-down-all")

    def set_counts(
        self,
        visible_start: int,
        visible_end: int,
        total: int,
        above: int | None = None,
        below: int | None = None,
    ) -> None:
        """Cache counts and update label + disabled states."""
        self._visible_start = visible_start
        self._visible_end = visible_end
        self._total = total
        if self._label is None:
            return
        try:
            if self.position == "top":
                self._label.update(f"  ▲ {above} lines above  ")
                at_top = visible_start == 0
                self.query_one(".--ob-up-all", Button).disabled = at_top
                self.query_one(".--ob-up-page", Button).disabled = at_top
            else:
                self._label.update(f"  ▼ {below} lines below  ")
                at_default = (
                    visible_start == 0
                    and (visible_end - visible_start) <= _VISIBLE_CAP
                )
                at_end = visible_end >= total
                self.query_one(".--ob-cap",      Button).disabled = at_default
                self.query_one(".--ob-up",       Button).disabled = at_default
                self.query_one(".--ob-down",     Button).disabled = at_end
                self.query_one(".--ob-down-all", Button).disabled = at_end
        except NoMatches:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        pb = self._parent_block
        vs, ve, tot = self._visible_start, self._visible_end, self._total
        classes = event.button.classes
        if "--ob-up-all" in classes:
            pb.rerender_window(0, ve)
        elif "--ob-up-page" in classes:
            pb.rerender_window(max(0, vs - _PAGE_SIZE), ve)
        elif "--ob-cap" in classes:
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

    def on_resize(self, event: object) -> None:
        """Hide the count label at narrow widths to make room for buttons."""
        w = getattr(getattr(event, "size", None), "width", 80)
        if crosses_threshold(self._last_resize_w, w, THRESHOLD_NARROW):
            if self._label is not None:
                self._label.display = w >= THRESHOLD_NARROW
        self._last_resize_w = w


# ---------------------------------------------------------------------------
# StreamingToolBlock — live output during tool execution
# ---------------------------------------------------------------------------

class StreamingToolBlock(ToolBlock):
    """ToolBlock with IDLE → STREAMING → COMPLETED lifecycle.

    Lines arrive via ``append_line()`` (called from the event loop via
    ``call_from_thread``).  A 60 fps flush timer drains the pending-line
    buffer into the RichLog.  Back-pressure is handled by:

    * **Render throttle** — the flush timer batches all lines that arrived
      between ticks into a single render pass.
    * **Visible cap** — at most ``_VISIBLE_CAP`` (200) lines are written to
      the RichLog.  Additional lines are tracked only in plain-text storage.
    * **Byte cap** — lines longer than ``_LINE_BYTE_CAP`` (2000 chars) are
      truncated before rendering and before plain-text storage.

    Used for real-time output during tool execution (terminal, execute_code).
    Content is written directly to the RichLog via ``_flush_pending()`` — the
    inherited ``self._lines`` / ``self._plain_lines`` are always empty.

    For post-completion summaries with full skin-refresh support, see
    ``ToolBlock`` (static).
    """

    DEFAULT_CSS = "StreamingToolBlock { height: auto; }"

    def __init__(self, label: str, tool_name: str | None = None, tool_input: "dict | None" = None, **kwargs: Any) -> None:
        # Initialise parent with empty lines — content arrives via append_line()
        super().__init__(label=label, lines=[], plain_lines=[], tool_name=tool_name, **kwargs)
        self._stream_label = label
        self._tool_input = tool_input
        # Lines buffered between 60fps flush ticks — stores linkified (Text, plain)
        self._pending: list[tuple[Text, str]] = []
        # All plain-text lines for clipboard (no display cap)
        self._all_plain: list[str] = []
        # Parallel ANSI-rich lines for windowed rerender (preserves color)
        self._all_rich: list[Text] = []
        self._visible_start: int = 0
        self._visible_count: int = 0
        self._total_received: int = 0
        self._omission_bar_top: OmissionBar | None = None
        self._omission_bar_bottom: OmissionBar | None = None
        self._omission_bar_top_mounted: bool = False
        self._omission_bar_bottom_mounted: bool = False
        self._spinner_frame: int = 0
        self._completed: bool = False
        self._tail = ToolTail()
        # v4 §3 — microcopy + adaptive flush
        self._bytes_received: int = 0
        self._last_line_time: float = 0.0
        self._flush_slow: bool = False       # True when idle≥2s, running at 10Hz
        self._microcopy_widget: "Static | None" = None
        # B2: rate tracking — (monotonic_time, byte_count) samples
        self._rate_samples: deque[tuple[float, int]] = deque(maxlen=60)
        # B2: last HTTP status line seen in WEB streams
        self._last_http_status: str | None = None
        # C2: tail-follow mode — when True, re-render window to latest lines every 5 appends
        self._follow_tail: bool = False
        # P1-4: tick-based shimmer phase for AGENT category (prevents teleport on busy loop)
        self._shimmer_phase: float = 0.0

    def compose(self) -> ComposeResult:
        yield self._header
        yield self._body
        yield self._tail

    def on_mount(self) -> None:
        """Start streaming timers. ToolPanel controls body visibility."""
        self._header._has_affordances = False  # no toggle while streaming
        self._header._spinner_char = _SPINNER_FRAMES[0]
        self._stream_started_at = time.monotonic()
        self._last_line_time = self._stream_started_at
        self._header._duration = "0.0s"
        self._render_timer = self.set_interval(1 / 60, self._flush_pending)
        self._spinner_timer = self.set_interval(0.25, self._tick_spinner)
        self._duration_timer = self.set_interval(0.1, self._tick_duration)
        # B4: read configurable limits from app config
        try:
            display_cfg = self.app.cfg.get("display", {})  # type: ignore[attr-defined]
            self._visible_cap: int = int(display_cfg.get("tool_visible_cap", _VISIBLE_CAP))
            self._line_byte_cap: int = int(display_cfg.get("tool_line_byte_cap", _LINE_BYTE_CAP))
        except Exception:
            self._visible_cap = _VISIBLE_CAP
            self._line_byte_cap = _LINE_BYTE_CAP
        # Cache microcopy widget ref (v4 §3.3)
        try:
            self._microcopy_widget = self._body.query_one(".--microcopy", Static)
        except Exception:
            self._microcopy_widget = None
        # Mount dual omission bars — always in DOM; display toggled dynamically.
        # Guard: ExecuteCodeBlock.compose() yields ExecuteCodeBody (not ToolBodyContainer),
        # so self._body may not be mounted here. Skip bar mount for those subclasses.
        if self._body.is_mounted:
            self._omission_bar_top = OmissionBar(
                parent_block=self, position="top", classes="--omission-bar-top"
            )
            self._omission_bar_bottom = OmissionBar(
                parent_block=self, position="bottom", classes="--omission-bar-bottom"
            )
            if self._microcopy_widget is not None:
                self._body.mount(self._omission_bar_top, before=self._microcopy_widget)
            else:
                self._body.mount(self._omission_bar_top)
            self._body.mount(self._omission_bar_bottom)
            self._omission_bar_top.display = False
            self._omission_bar_bottom.display = False
            self._omission_bar_top_mounted = True
            self._omission_bar_bottom_mounted = True
        # Start icon pulse
        self._header._pulse_start()
        # B1: extract and show secondary args before streaming starts
        try:
            from hermes_cli.tui.tool_category import spec_for as _spec_for
            _spec = _spec_for(self._tool_name or "")
            _sec = _secondary_args_text(_spec.category, self._tool_input)
            if _sec:
                self._body.update_secondary_args(_sec)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Streaming API (called from event loop via call_from_thread)
    # ------------------------------------------------------------------

    # B2: HTTP status line pattern for WEB streams
    _HTTP_STATUS_LINE_RE = re.compile(r'^HTTP/\S+\s+(\d+\s+.+)$')

    def append_line(self, raw: str) -> None:
        """Buffer a raw ANSI line for rendering on the next 60fps tick."""
        if self._completed:
            return
        # Byte cap — use instance override (B4) if set, else module constant
        line_byte_cap = getattr(self, "_line_byte_cap", _LINE_BYTE_CAP)
        if len(raw) > line_byte_cap:
            over = len(raw) - line_byte_cap
            raw = raw[:line_byte_cap] + f"… (+{over} chars)"
        plain = _strip_ansi(raw)
        self._total_received += 1
        self._bytes_received += len(raw)
        now = time.monotonic()
        self._last_line_time = now
        rich = _linkify_text(plain, Text.from_ansi(raw))
        self._pending.append((rich, plain))
        self._all_plain.append(plain)
        self._all_rich.append(rich)
        # C2: tail-follow — re-render to latest window every 5 lines
        total = len(self._all_plain)
        if self._follow_tail and total % 5 == 0:
            visible_cap = getattr(self, "_visible_cap", _VISIBLE_CAP)
            self.rerender_window(max(0, total - visible_cap), total)
        # B2: rate sample
        self._rate_samples.append((now, len(raw)))
        # B2: HTTP status detection for WEB category
        m = self._HTTP_STATUS_LINE_RE.match(plain.strip())
        if m:
            self._last_http_status = m.group(1).strip()
        # Restore 60Hz if we had dropped to slow rate (v4 §3.4)
        if self._flush_slow:
            self._flush_slow = False
            self._render_timer.stop()
            self._render_timer = self.set_interval(1 / 60, self._flush_pending)

    def inject_diff(self, diff_lines: list[str], header_stats: "ToolHeaderStats | None") -> None:
        """Inject diff content into body before complete(); set +/- chips in header."""
        for raw in diff_lines:
            self.append_line(raw)
        if header_stats is not None:
            self._header._stats = header_stats
        self._header.add_class("--diff-header")

    def on_unmount(self) -> None:
        """Stop timers so they don't fire against a detached widget."""
        try:
            self._render_timer.stop()
        except Exception:
            pass
        try:
            self._spinner_timer.stop()
        except Exception:
            pass
        try:
            self._duration_timer.stop()
        except Exception:
            pass

    def complete(self, duration: str, is_error: bool = False) -> None:
        """Transition to COMPLETED state: flush remaining lines, update header."""
        if self._completed:
            return
        self._completed = True
        # C2: reset tail follow on completion
        self._follow_tail = False
        # Stop timers — no more streaming ticks needed
        try:
            self._render_timer.stop()
            self._spinner_timer.stop()
            self._duration_timer.stop()
        except Exception:
            pass
        # Stop icon pulse, set error state
        self._header._pulse_stop()
        self._header.set_error(is_error)
        # Final synchronous flush
        self._flush_pending()
        # Hide tail badge unconditionally
        self._tail.dismiss()
        # Update header: remove spinner, mark complete, add duration + line count
        self._header._spinner_char = None
        self._header._is_complete = True
        started = getattr(self, "_stream_started_at", None)
        if started is not None:
            elapsed_ms = (time.monotonic() - started) * 1000.0
            self._header._elapsed_ms = elapsed_ms
            self._header._duration = _format_duration_v4(elapsed_ms)
        else:
            self._header._duration = duration
        self._header._line_count = self._total_received
        # Enable toggle affordance for static ToolBlocks (unwrapped; STBs in panels
        # skip the ▾/▸ via _render_v4 guard, but _has_affordances still gates copy)
        if self._total_received > COLLAPSE_THRESHOLD:
            self._header._has_affordances = True
        self._header.refresh()
        # v4 §3.3: clear microcopy on completion (keep MCP provenance line)
        self._clear_microcopy_on_complete()
        # Brief success flash to signal completion
        self._header.flash_complete()
        # If output contains a MEDIA: path, replace body with an inline image
        self._try_mount_media()
        # Populate secondary args row above body output
        try:
            from hermes_cli.tui.tool_category import spec_for as _spec_for
            _spec = _spec_for(self._tool_name or "")
            _args_text = _build_args_row_text(_spec, self._tool_input)
            if _args_text:
                self._body.set_args_row(_args_text)
        except Exception:
            pass

    def _clear_microcopy_on_complete(self) -> None:
        """Clear microcopy on completion; restore secondary args if set (B1)."""
        self._body.clear_microcopy()

    def _try_mount_media(self) -> bool:
        """Mount inline media if output contains a MEDIA: image line or audio/video URLs.

        Image: uses the last MEDIA: match (most recent matplotlib figure).
        Audio/video: mounts InlineMediaWidget below the tool body.
        Returns True if anything was mounted.
        """
        text = "\n".join(self._all_plain)
        mounted = False

        # Existing image detection (unchanged)
        matches = _MEDIA_LINE_RE.findall(text)
        if matches:
            path = _extract_image_path(matches[-1])
            if path is not None:
                try:
                    from hermes_cli.tui.widgets import InlineImage
                    self._body.mount(InlineImage(image=path, max_rows=24))
                    self.post_message(ImageMounted(path))
                    mounted = True
                except Exception:
                    pass

        # Audio/video/YouTube URL detection
        try:
            from hermes_cli.tui.media_player import (
                _AUDIO_EXT_RE, _VIDEO_EXT_RE, _YOUTUBE_RE, _inline_media_config,
            )
            from hermes_cli.tui.widgets import InlineMediaWidget
            cfg = _inline_media_config()
            if cfg.enabled:
                seen: set[str] = set()
                for url in _AUDIO_EXT_RE.findall(text):
                    if url not in seen:
                        seen.add(url)
                        self.mount(InlineMediaWidget(url=url, kind="audio"))
                        mounted = True
                for url in _VIDEO_EXT_RE.findall(text):
                    if url not in seen:
                        seen.add(url)
                        self.mount(InlineMediaWidget(url=url, kind="video"))
                        mounted = True
                for url in _YOUTUBE_RE.findall(text):
                    if url not in seen:
                        seen.add(url)
                        self.mount(InlineMediaWidget(url=url, kind="youtube"))
                        mounted = True
        except Exception:
            pass

        return mounted


    # ------------------------------------------------------------------
    # Internal timers
    # ------------------------------------------------------------------

    def _tick_spinner(self) -> None:
        if self._completed:
            return
        self._spinner_frame = (self._spinner_frame + 1) % len(_SPINNER_FRAMES)
        self._header._spinner_char = _SPINNER_FRAMES[self._spinner_frame]
        self._header.refresh()

    def _tick_duration(self) -> None:
        if self._completed:
            return
        started = getattr(self, "_stream_started_at", None)
        if started is None:
            return
        elapsed_ms = (time.monotonic() - started) * 1000.0
        self._header._elapsed_ms = elapsed_ms
        self._header._duration = _format_duration_v4(elapsed_ms)
        self._header.refresh()

    def _bytes_per_second(self) -> float | None:
        """B2: compute transfer rate from last 2s of samples."""
        now = time.monotonic()
        cutoff = now - 2.0
        recent = [(t, b) for t, b in self._rate_samples if t >= cutoff]
        if len(recent) < 2:
            return None
        return sum(b for _, b in recent) / 2.0

    def _update_microcopy(self) -> None:
        """Update microcopy Static with current streaming state (v4 §3.3)."""
        started = getattr(self, "_stream_started_at", None)
        if started is None:
            return
        elapsed_s = time.monotonic() - started
        if elapsed_s < 0.5:
            return  # avoid flash for fast tools
        try:
            from hermes_cli.tui.tool_category import spec_for
            from hermes_cli.tui.streaming_microcopy import StreamingState, microcopy_line
        except Exception:
            return
        spec = spec_for(self._tool_name or "")
        state = StreamingState(
            lines_received=self._total_received,
            bytes_received=self._bytes_received,
            elapsed_s=elapsed_s,
            last_status=self._last_http_status,  # B2: WEB HTTP status
            rate_bps=self._bytes_per_second(),    # B2: transfer rate
        )
        reduced_motion = getattr(getattr(self, "app", None), "_reduced_motion", False)  # D2
        # Advance shimmer phase by constant delta (avoids wall-clock jump on busy loop)
        try:
            from hermes_cli.tui.tool_category import ToolCategory as _TC
            if spec.category == _TC.AGENT:
                self._shimmer_phase = (self._shimmer_phase + 0.05) % 2.0
        except Exception:
            pass
        text = microcopy_line(spec, state, reduced_motion=reduced_motion, shimmer_phase=self._shimmer_phase)
        if text:
            self._body.set_microcopy(text)

    def _flush_pending(self) -> None:
        """Drain pending lines into the RichLog (called at 60fps)."""
        # Adaptive flush: drop to 10Hz after 2s idle (v4 §3.4)
        if not self._flush_slow and not self._completed:
            now = time.monotonic()
            if now - self._last_line_time > 2.0:
                self._flush_slow = True
                self._render_timer.stop()
                self._render_timer = self.set_interval(1 / 10, self._flush_pending)

        if not self._pending:
            self._update_microcopy()
            return
        batch = self._pending
        self._pending = []

        try:
            log = self._body.query_one(CopyableRichLog)
        except NoMatches:
            return

        lines_written = 0
        visible_cap = getattr(self, "_visible_cap", _VISIBLE_CAP)  # B4
        for rich, plain in batch:
            if self._visible_count < visible_cap:
                log.write_with_source(rich, plain, link=_first_link(plain))
                self._visible_count += 1
                lines_written += 1
            # Lines beyond cap are still in _all_plain (appended in append_line)

        if self._omission_bar_bottom_mounted or self._omission_bar_top_mounted:
            self._refresh_omission_bars()

        if lines_written:
            try:
                scrolled_up = getattr(self.app.query_one("#output-panel"), "_user_scrolled_up", False)
            except Exception:
                scrolled_up = False
            if scrolled_up:
                # _new_line_count is the source of truth; it is reset to 0 by
                # ToolTail.dismiss() (called by watch_scroll_y) so resuming a
                # second scroll session always starts from 0.
                new_total = self._tail._new_line_count + lines_written
                try:
                    self._tail.update_count(new_total)
                except Exception:
                    pass

        self._update_microcopy()

    # ------------------------------------------------------------------
    # OmissionBar callbacks — expand/collapse the visible line window
    # ------------------------------------------------------------------

    def rerender_window(self, start: int, end: int) -> None:
        """Clear log and re-render _all_rich[start:end] (canonical scroll primitive)."""
        try:
            log = self._body.query_one(CopyableRichLog)
        except NoMatches:
            return
        log.clear()
        for rich_line, plain in zip(self._all_rich[start:end], self._all_plain[start:end]):
            log.write_with_source(rich_line, plain, link=_first_link(plain))
        self._visible_start = start
        self._visible_count = end - start
        self._refresh_omission_bars()

    def reveal_lines(self, start: int, end: int) -> None:
        """Append _all_rich[start:end] to the RichLog (expand path)."""
        try:
            log = self._body.query_one(CopyableRichLog)
        except NoMatches:
            return
        for rich_line, plain in zip(self._all_rich[start:end], self._all_plain[start:end]):
            log.write_with_source(rich_line, plain, link=_first_link(plain))
        self._visible_count += end - start
        self._refresh_omission_bars()

    def collapse_to(self, new_end: int) -> None:
        """Clear the RichLog and rewrite _all_rich[:new_end] (collapse path)."""
        try:
            log = self._body.query_one(CopyableRichLog)
        except NoMatches:
            return
        log.clear()
        for rich_line, plain in zip(self._all_rich[:new_end], self._all_plain[:new_end]):
            log.write_with_source(rich_line, plain, link=_first_link(plain))
        self._visible_start = 0
        self._visible_count = new_end
        self._refresh_omission_bars()

    def _refresh_omission_bars(self) -> None:
        """Update both omission bars' visibility and counts."""
        total = len(self._all_plain)
        visible_start = self._visible_start
        visible_end = visible_start + self._visible_count

        if self._omission_bar_top_mounted and self._omission_bar_top is not None:
            show_top = visible_start > 0
            if self._omission_bar_top.display != show_top:
                self._omission_bar_top.display = show_top
            # Always update counts (not just when visible) so labels are current
            # when bar becomes visible again after being hidden.
            self._omission_bar_top.set_counts(
                visible_start=visible_start,
                visible_end=visible_end,
                total=total,
                above=visible_start,
            )

        if self._omission_bar_bottom_mounted and self._omission_bar_bottom is not None:
            show_bottom = visible_end < total
            if self._omission_bar_bottom.display != show_bottom:
                self._omission_bar_bottom.display = show_bottom
            self._omission_bar_bottom.set_counts(
                visible_start=visible_start,
                visible_end=visible_end,
                total=total,
                below=total - visible_end,
            )

    # ------------------------------------------------------------------
    # Override copy_content to return all plain lines, not just visible
    # ------------------------------------------------------------------

    def copy_content(self) -> str:
        return "\n".join(self._all_plain)

    def refresh_skin(self) -> None:
        """Refresh header cosmetics only — skip body re-render.

        StreamingToolBlock writes content directly to the RichLog via
        ``_flush_pending()``; ``self._lines`` / ``self._plain_lines`` are
        always empty.  The inherited ``_render_body()`` would be a no-op
        (returns early on empty lines), so we skip it entirely.

        Body content cannot be re-styled: per-line Pygments highlighting
        loses multi-line string/decorator context that ``complete()``
        never reconstructed.  Only header visuals (gutter color, tool
        icon) are refreshed.
        """
        self._header._refresh_gutter_color()
        self._header._refresh_tool_icon()
        self._header.refresh()

    def set_age_microcopy(self, text: str) -> None:
        """F1: update the microcopy slot with age text (only when complete)."""
        if not self._completed:
            return
        from rich.text import Text as _T
        mc = self._microcopy_widget
        if mc is None:
            try:
                mc = self._body.query_one(".--microcopy", Static)
                self._microcopy_widget = mc
            except Exception:
                return
        styled = _T(text, style="dim")
        mc.update(styled)
        mc.add_class("--active")
        mc.remove_class("--secondary-args")
