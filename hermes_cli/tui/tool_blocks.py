"""ToolBlock widgets for displaying collapsible tool output in the TUI.

ToolBlock groups a ToolHeader (single-line label with toggle/copy affordances)
and a ToolBodyContainer (collapsible content area). Blocks with ≤3 lines are
auto-expanded with no toggle or copy affordance.

StreamingToolBlock extends ToolBlock with IDLE→STREAMING→COMPLETED lifecycle,
60fps render throttle, 200-line visible cap, and 2 kB per-line byte cap.
"""

from __future__ import annotations

import collections
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from rich.text import Text
from textual.app import ComposeResult, RenderResult
from textual.css.query import NoMatches
from textual.events import Click
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from hermes_cli.tui.animation import PulseMixin, lerp_color
from hermes_cli.tui.widgets import (
    CopyableRichLog,
    _boost_layout_caches,
    _skin_color,
    _strip_ansi,
)

COLLAPSE_THRESHOLD = 3  # >N lines → collapsed by default

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
_DIFF_HEADER_RE = re.compile(r"^((?:---|\+\+\+)\s+)(?:[ab]/)?(.+)$")
# Rendered diff file-header line: "a/src/foo.py → b/src/foo.py" (after ANSI strip)
_DIFF_ARROW_RE = re.compile(r"^(.+?)\s+→\s+(.+)$")


def _safe_cell_width(s: str) -> int:
    """Return cell width of s; fall back to len(s) if wcwidth unavailable."""
    try:
        from wcwidth import wcswidth
        w = wcswidth(s)
        return w if w >= 0 else len(s)
    except ImportError:
        return len(s)


def _tool_gutter_enabled() -> bool:
    """Show ┊/┃ gutter symbols on tool call blocks (default: true)."""
    try:
        from hermes_cli.config import read_raw_config
        return bool(read_raw_config().get("display", {}).get("tool_gutter", True))
    except Exception:
        return True


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


class ToolHeader(PulseMixin, Widget):
    """Single-line header: '  ╌╌ {label}  {stats}  [▸/▾]'.

    During streaming ``_spinner_char`` replaces the toggle chevron.
    After completion ``_duration`` is appended to the label.

    Inherits PulseMixin — tool icon pulses green during streaming,
    settles to green (success) or red (error) on completion.
    """

    DEFAULT_CSS = "ToolHeader { height: 1; }"

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
        # Streaming state — set by StreamingToolBlock
        self._spinner_char: str | None = None   # non-None while streaming
        self._duration: str = ""                # set on completion
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
            self._tool_icon = ""

    def render(self) -> RenderResult:
        focused = self.has_class("focused")
        t = Text()

        # --- Gutter ---
        # ┊/┃ replaced by ToolAccent widget in ToolPanel (v3 D4 fix).
        # ╰─ kept for diff-child blocks until DiffAffordance is fully wired.
        if _tool_gutter_enabled() and self._is_child_diff:
            gutter_text = Text("  ╰─", style="dim")
            gutter_w = 4
            t.append_text(gutter_text)
        else:
            gutter_w = 0

        dashes_w = 0

        # --- Icon ---
        icon_str = self._tool_icon or ""
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
            elif self._duration:
                ok_color = getattr(self, "_diff_add_color", _DIFF_ADD_FALLBACK)
                icon_style = f"bold {ok_color}"
            else:
                icon_style = "dim"
            t.append(f" {icon_str}", style=icon_style)
        space_after_icon = 1  # the space before label

        # --- Label style (not dim for streaming or completed) ---
        if self._tool_icon_error:
            label_style = "#ef5350"
        else:
            label_style = ""   # terminal default — not dim

        # Duration style: dim for normal blocks, normal for compact-tail (execute_code)
        compact = getattr(self, "_compact_tail", False)
        dur_style = "" if compact else "dim"

        # --- Tail ---
        tail = Text()
        if self._spinner_char is not None:
            tail.append(f"  {self._spinner_char}", style="dim")
            if self._duration:
                tail.append(f"  {self._duration}", style=dur_style)
        else:
            if self._stats and self._stats.has_diff_counts:
                add_color = getattr(self, "_diff_add_color", _DIFF_ADD_FALLBACK)
                del_color = getattr(self, "_diff_del_color", _DIFF_DEL_FALLBACK)
                if self._stats.additions:
                    tail.append(f"  +{self._stats.additions}", style=f"bold {add_color}")
                if self._stats.deletions:
                    tail.append(f"  -{self._stats.deletions}", style=f"bold {del_color}")
            elif self._line_count:
                tail.append(f"  {self._line_count}L", style="dim")
            if self._has_affordances:
                toggle = "  ▾" if not self.collapsed else "  ▸"
                tail.append(toggle, style="dim")
            if self._duration:
                tail.append(f"  {self._duration}", style=dur_style)

        # --- Label with padding ---
        term_w = self.size.width

        # Compact-tail mode (execute_code): no right-align padding, natural flow
        if compact:
            if self._label_rich is not None:
                t.append(" ")
                t.append_text(self._label_rich)
            else:
                t.append(f" {self._label}", style=label_style)
            t.append_text(tail)
            return t

        # Normal mode: right-align tail
        tail_w = tail.cell_len
        FIXED_PREFIX_W = gutter_w + dashes_w + icon_cell_w + space_after_icon
        MIN_LABEL_W = 8

        if term_w <= 0:
            # Pre-mount: best-effort, no padding
            if self._path_clickable:
                t.append_text(self._render_path_label(50))
            elif self._label_rich is not None:
                label_str = self._label
                display_rich = self._label_rich if _safe_cell_width(label_str) <= 50 else Text(label_str[:49] + "…")
                t.append(" ")
                t.append_text(display_rich)
            else:
                t.append(f" {self._label}", style=label_style)
            t.append_text(tail)
            return t

        available = max(MIN_LABEL_W, term_w - FIXED_PREFIX_W - tail_w - 2)
        if self._path_clickable:
            path_text = self._render_path_label(available)
            t.append_text(path_text)
            pad = max(0, available - path_text.cell_len)
            t.append(" " * pad)
        elif self._label_rich is not None:
            label_str = self._label
            if _safe_cell_width(label_str) > available:
                label_str = label_str[:available - 1] + "…"
                display_rich = Text(label_str)
            else:
                display_rich = self._label_rich
            pad = max(0, available - _safe_cell_width(label_str))
            t.append(" ")
            t.append_text(display_rich)
            t.append(" " * pad)
        else:
            label_str = self._label
            if len(label_str) > available:
                label_str = label_str[:available - 1] + "…"
            pad = max(0, available - _safe_cell_width(label_str))
            t.append(f" {label_str}{' ' * pad}", style=label_style)
        t.append_text(tail)
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
        t.append(fname, style="bold underline")
        return t

    def on_click(self, event: Click) -> None:
        """Left-click: open file if path-clickable, otherwise toggle block.

        Right-clicks (button=3) are not intercepted here — they bubble up to
        HermesApp.on_click() which builds the context menu.
        """
        if event.button != 1:
            return                          # right/middle click: let bubble to HermesApp
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
        if not self._has_affordances:
            return                          # always-expanded block: nothing to toggle
        event.prevent_default()
        parent = self.parent
        if parent is not None:
            parent.toggle()


class ToolBodyContainer(Widget):
    """Collapsible container for tool output lines."""

    DEFAULT_CSS = """
    ToolBodyContainer { height: auto; display: none; }
    ToolBodyContainer.expanded { display: block; }
    """

    def compose(self) -> ComposeResult:
        # No explicit ID — query by type inside ToolBodyContainer to avoid
        # duplicate IDs when multiple ToolBlocks exist per MessagePanel.
        yield CopyableRichLog(markup=False, highlight=False, wrap=False)


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
        self._rerender_fn = rerender_fn
        self._header_stats = header_stats
        if self._header_stats is None and label == "diff":
            self._header_stats = _count_visible_diff_rows(self._plain_lines)
        auto_expand = len(lines) <= COLLAPSE_THRESHOLD
        self._header = ToolHeader(label, len(lines), tool_name=tool_name, stats=self._header_stats)
        self._body = ToolBodyContainer()
        if auto_expand:
            self._header.collapsed = False
            # _has_affordances is already False when line_count ≤ threshold

        # Path-aware header for file tools — not for "diff"/"code"/"output" labels
        if tool_name in _FILE_TOOL_NAMES and label not in ("diff", "code", "output"):
            self._header.set_path(label)

        # Diff body path parsing for context menu
        self._diff_file_path: str | None = None
        if label == "diff":
            _fallback: str | None = None
            for line in self._plain_lines:
                stripped = line.strip()
                # Raw ---/+++ format
                m = _DIFF_PATH_RE.match(stripped)
                if m:
                    candidate = m.group(1).strip()
                    if "/dev/null" in candidate:
                        continue
                    if stripped.startswith("+++"):
                        self._diff_file_path = candidate
                        break
                    if _fallback is None:
                        _fallback = candidate
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

    def _render_body(self) -> None:
        try:
            log = self._body.query_one(CopyableRichLog)
            log.clear()
            for styled, plain in zip(self._lines, self._plain_lines):
                if self._label == "diff":
                    rich_line = self._render_diff_line(plain)
                    if rich_line is not None:
                        log.write(rich_line)
                        continue
                log.write_with_source(Text.from_ansi(styled), plain)
            if self._header_stats and self._header_stats.has_diff_counts and self._lines:
                log.write(Text(""))
        except NoMatches:
            pass  # body not yet in DOM — safe to skip

    def toggle(self) -> None:
        """Toggle collapsed ↔ expanded. No-op for ≤3-line blocks."""
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
        if self._label == "diff" and self._header_stats is None:
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

class OmissionBar(Widget):
    """Interactive bar that replaces the static cap marker in StreamingToolBlock.

    Shows ``… N lines omitted  [--] [-] [+] [++]`` and lets the user reveal
    or hide lines beyond the _VISIBLE_CAP threshold.
    """

    DEFAULT_CSS = """
    OmissionBar {
        layout: horizontal;
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, parent_block: "StreamingToolBlock", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._parent_block = parent_block
        self._visible_end: int = _VISIBLE_CAP
        self._total: int = 0

    def compose(self) -> ComposeResult:
        yield Static("", id="omission-label", classes="omission-label")
        yield Static("[--]", id="btn-collapse-all", classes="omission-btn -disabled")
        yield Static("[-]",  id="btn-collapse-one", classes="omission-btn -disabled")
        yield Static("[+]",  id="btn-expand-one",   classes="omission-btn")
        yield Static("[++]", id="btn-expand-all",   classes="omission-btn")

    def on_click(self, event: Click) -> None:
        clicked = event.widget
        if clicked is self:
            return
        clicked_id = getattr(clicked, "id", None)
        if clicked_id is None:
            return
        if clicked.has_class("-disabled"):
            return
        event.stop()
        if clicked_id == "btn-collapse-all":
            self._do_collapse_all()
        elif clicked_id == "btn-collapse-one":
            self._do_collapse_one()
        elif clicked_id == "btn-expand-one":
            self._do_expand_one()
        elif clicked_id == "btn-expand-all":
            self._do_expand_all()

    def update(self, total: int, visible_end: int) -> None:
        """Refresh label text and button disabled states."""
        self._total = total
        self._visible_end = visible_end
        omitted = max(0, total - visible_end)
        try:
            self.query_one("#omission-label", Static).update(
                f"  … {omitted} lines omitted  "
            )
        except NoMatches:
            pass
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        at_cap = self._visible_end <= _VISIBLE_CAP
        at_end = self._visible_end >= self._total
        try:
            self.query_one("#btn-collapse-all", Static).set_class(at_cap, "-disabled")
            self.query_one("#btn-collapse-one", Static).set_class(at_cap, "-disabled")
            self.query_one("#btn-expand-one",   Static).set_class(at_end, "-disabled")
            self.query_one("#btn-expand-all",   Static).set_class(at_end, "-disabled")
        except NoMatches:
            pass

    def _do_expand_one(self) -> None:
        new_end = min(self._total, self._visible_end + _PAGE_SIZE)
        self._parent_block.reveal_lines(self._visible_end, new_end)
        self._visible_end = new_end
        self.update(self._total, self._visible_end)

    def _do_expand_all(self) -> None:
        new_end = self._total
        self._parent_block.reveal_lines(self._visible_end, new_end)
        self._visible_end = new_end
        self.update(self._total, self._visible_end)

    def _do_collapse_one(self) -> None:
        new_end = max(_VISIBLE_CAP, self._visible_end - _PAGE_SIZE)
        if new_end == self._visible_end:
            return
        self._parent_block.collapse_to(new_end)
        self._visible_end = new_end
        self.update(self._total, self._visible_end)

    def _do_collapse_all(self) -> None:
        if self._visible_end == _VISIBLE_CAP:
            return
        self._parent_block.collapse_to(_VISIBLE_CAP)
        self._visible_end = _VISIBLE_CAP
        self.update(self._total, self._visible_end)


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

    def __init__(self, label: str, tool_name: str | None = None, **kwargs: Any) -> None:
        # Initialise parent with empty lines — content arrives via append_line()
        super().__init__(label=label, lines=[], plain_lines=[], tool_name=tool_name, **kwargs)
        self._stream_label = label
        # Lines buffered between 60fps flush ticks
        self._pending: list[tuple[str, str]] = []  # (raw_ansi, plain)
        # All plain-text lines for clipboard (no display cap)
        self._all_plain: list[str] = []
        self._visible_count: int = 0
        self._total_received: int = 0
        self._omission_bar: OmissionBar | None = None
        self._omission_bar_mounted: bool = False
        self._spinner_frame: int = 0
        self._completed: bool = False
        self._tail = ToolTail()
        # CWD stripping — set True by ToolPanel for SHELL category blocks
        self._should_strip_cwd: bool = False
        self._detected_cwd: str | None = None

    def compose(self) -> ComposeResult:
        yield self._header
        yield self._body
        yield self._tail

    def on_mount(self) -> None:
        """Start expanded (user wants to see streaming output) + start timers."""
        self._body.add_class("expanded")
        self._header.collapsed = False
        self._header._has_affordances = False  # no toggle while streaming
        self._header._spinner_char = _SPINNER_FRAMES[0]
        self._stream_started_at = time.monotonic()
        self._header._duration = "0.0s"
        self._render_timer = self.set_interval(1 / 60, self._flush_pending)
        self._spinner_timer = self.set_interval(0.25, self._tick_spinner)
        self._duration_timer = self.set_interval(0.1, self._tick_duration)
        # Start icon pulse
        self._header._pulse_start()

    # ------------------------------------------------------------------
    # Streaming API (called from event loop via call_from_thread)
    # ------------------------------------------------------------------

    def append_line(self, raw: str) -> None:
        """Buffer a raw ANSI line for rendering on the next 60fps tick."""
        if self._completed:
            return
        # CWD token stripping for SHELL category blocks
        if self._should_strip_cwd:
            from hermes_cli.tui.cwd_strip import strip_cwd
            cleaned, cwd = strip_cwd(raw)
            if cwd is not None:
                self._detected_cwd = cwd
            if not cleaned.strip():
                return  # skip empty CWD-only lines
            raw = cleaned
        # Byte cap
        if len(raw) > _LINE_BYTE_CAP:
            over = len(raw) - _LINE_BYTE_CAP
            raw = raw[:_LINE_BYTE_CAP] + f"… (+{over} chars)"
        plain = _strip_ansi(raw)
        self._total_received += 1
        self._pending.append((raw, plain))
        self._all_plain.append(plain)

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
        # Update header: remove spinner, add duration + line count
        self._header._spinner_char = None
        self._header._duration = duration
        self._header._line_count = self._total_received
        # Apply same collapse logic as static ToolBlock
        if self._total_received > COLLAPSE_THRESHOLD:
            self._header._has_affordances = True
            self._header.collapsed = True
            self._body.remove_class("expanded")
        elif self._total_received == 0:
            # Hide empty body entirely (non-streaming tools with no output)
            self._body.styles.display = "none"
            self._header.collapsed = False
        else:
            self._header.collapsed = False
        self._header.refresh()
        # CWD footer dim line
        if self._detected_cwd:
            from rich.text import Text as _RichText
            try:
                from hermes_cli.tui.widgets import CopyableRichLog as _CRL
                log = self._body.query_one(_CRL)
                log.write(_RichText(f"  cwd: {self._detected_cwd}", style="dim"))
            except Exception:
                pass
        # Brief success flash to signal completion
        self._header.flash_complete()

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
        self._header._duration = f"{time.monotonic() - started:.1f}s"
        self._header.refresh()

    def _flush_pending(self) -> None:
        """Drain pending lines into the RichLog (called at 60fps)."""
        if not self._pending:
            return
        batch = self._pending
        self._pending = []

        try:
            log = self._body.query_one(CopyableRichLog)
        except NoMatches:
            return

        lines_written = 0
        for raw, plain in batch:
            if self._visible_count < _VISIBLE_CAP:
                log.write_with_source(Text.from_ansi(raw), plain)
                self._visible_count += 1
                lines_written += 1
            elif not self._omission_bar_mounted:
                bar = OmissionBar(parent_block=self)
                self._omission_bar = bar
                self._omission_bar_mounted = True
                self._body.mount(bar)
            # Lines beyond cap are still in _all_plain (appended in append_line)

        if self._omission_bar is not None:
            self._omission_bar.update(self._total_received,
                                      self._omission_bar._visible_end)

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

    # ------------------------------------------------------------------
    # OmissionBar callbacks — expand/collapse the visible line window
    # ------------------------------------------------------------------

    def reveal_lines(self, start: int, end: int) -> None:
        """Append _all_plain[start:end] to the RichLog (expand path)."""
        try:
            log = self._body.query_one(CopyableRichLog)
        except NoMatches:
            return
        for plain in self._all_plain[start:end]:
            log.write_with_source(Text(plain), plain)

    def collapse_to(self, new_end: int) -> None:
        """Clear the RichLog and rewrite _all_plain[:new_end] (collapse path)."""
        try:
            log = self._body.query_one(CopyableRichLog)
        except NoMatches:
            return
        log.clear()
        for plain in self._all_plain[:new_end]:
            log.write_with_source(Text(plain), plain)

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
