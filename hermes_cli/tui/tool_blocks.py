"""ToolBlock widgets for displaying collapsible tool output in the TUI.

ToolBlock groups a ToolHeader (single-line label with toggle/copy affordances)
and a ToolBodyContainer (collapsible content area). Blocks with ≤3 lines are
auto-expanded with no toggle or copy affordance.

StreamingToolBlock extends ToolBlock with IDLE→STREAMING→COMPLETED lifecycle,
60fps render throttle, 200-line visible cap, and 2 kB per-line byte cap.
"""

from __future__ import annotations

import collections
from typing import Any

from rich.text import Text
from textual.app import ComposeResult, RenderResult
from textual.css.query import NoMatches
from textual.events import Click
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from hermes_cli.tui.widgets import CopyableRichLog, _skin_color, _strip_ansi

COLLAPSE_THRESHOLD = 3  # >N lines → collapsed by default

# StreamingToolBlock constants
_VISIBLE_CAP = 200          # max lines shown in the RichLog
_LINE_BYTE_CAP = 2000       # truncate single lines beyond this many chars
_SPINNER_FRAMES: tuple[str, ...] = (
    "⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏",
)

# Gutter fallback color — avoid duplicating the literal across three call sites
_GUTTER_FALLBACK: str = "#FFD700"


class ToolHeader(Widget):
    """Single-line header: '  ╌╌ {label}  {N}L  [▸/▾  ⎘]'.

    During streaming ``_spinner_char`` replaces the toggle chevron.
    After completion ``_duration`` is appended to the label.
    """

    DEFAULT_CSS = "ToolHeader { height: 1; }"

    collapsed: reactive[bool] = reactive(True, repaint=True)

    def __init__(self, label: str, line_count: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._label = label
        self._line_count = line_count
        # ≤ threshold: always open, no affordances shown
        self._has_affordances = line_count > COLLAPSE_THRESHOLD
        self._copy_flash = False
        # Streaming state — set by StreamingToolBlock
        self._spinner_char: str | None = None   # non-None while streaming
        self._duration: str = ""                # set on completion

    def on_mount(self) -> None:
        self._refresh_gutter_color()

    def _refresh_gutter_color(self) -> None:
        """Cache focused-gutter colour from CSS variables (supports hot-reload)."""
        try:
            self._focused_gutter_color: str = self.app.get_css_variables().get(
                "rule-accent-color", _GUTTER_FALLBACK
            )
        except Exception:
            self._focused_gutter_color = _GUTTER_FALLBACK

    def render(self) -> RenderResult:
        focused = self.has_class("focused")
        if focused:
            color = getattr(self, "_focused_gutter_color", _GUTTER_FALLBACK)
            gutter = Text("  ┃", style=f"bold {color}")
        else:
            gutter = Text("  ┊", style="dim")
        t = Text()
        t.append_text(gutter)
        label_str = self._label
        if self._duration:
            label_str += f"  {self._duration}"
        t.append(f"   ╌╌ {label_str}", style="dim")
        if self._spinner_char is not None:
            # Streaming in progress — show spinner, no line count or toggle yet
            t.append(f"  {self._spinner_char}", style="dim")
        else:
            if self._line_count:
                t.append(f"  {self._line_count}L", style="dim")
            if self._has_affordances:
                toggle = "  ▾" if not self.collapsed else "  ▸"
                icon = "  ✓" if self._copy_flash else "  ⎘"
                t.append(toggle, style="dim")
                t.append(icon, style="dim")
        return t

    def flash_copy(self) -> None:
        """Flash ⎘ → ✓ for 1.5 s, then revert."""
        self._copy_flash = True
        self.refresh()
        self.set_timer(1.5, self._end_flash)

    def _end_flash(self) -> None:
        self._copy_flash = False
        self.refresh()

    def flash_complete(self) -> None:
        """Brief success-colour flash when a streaming block completes."""
        self.add_class("--flash-complete")
        self.set_timer(0.45, self._end_complete_flash)

    def _end_complete_flash(self) -> None:
        self.remove_class("--flash-complete")

    def on_click(self, event: Click) -> None:
        """Left-click toggles the parent ToolBlock.

        Right-clicks (button=3) are not intercepted here — they bubble up to
        HermesApp.on_click() which builds the context menu.
        """
        if event.button != 1:
            return                          # right/middle click: let bubble to HermesApp
        if self._spinner_char is not None:
            return                          # streaming: ignore click
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
    """

    DEFAULT_CSS = "ToolBlock { height: auto; }"

    def __init__(
        self,
        label: str,
        lines: list[str],       # ANSI display lines
        plain_lines: list[str], # plain text for copy (no ANSI, no gutter)
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._label = label
        self._lines = list(lines)
        self._plain_lines = list(plain_lines)
        auto_expand = len(lines) <= COLLAPSE_THRESHOLD
        self._header = ToolHeader(label, len(lines))
        self._body = ToolBodyContainer()
        if auto_expand:
            self._header.collapsed = False
            # _has_affordances is already False when line_count ≤ threshold

    def compose(self) -> ComposeResult:
        yield self._header
        yield self._body

    def on_mount(self) -> None:
        try:
            log = self._body.query_one(CopyableRichLog)
            for styled, plain in zip(self._lines, self._plain_lines):
                log.write_with_source(Text.from_ansi(styled), plain)
        except NoMatches:
            pass  # body not yet in DOM — safe to skip
        if not self._header.collapsed:
            self._body.add_class("expanded")

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
    """

    DEFAULT_CSS = "StreamingToolBlock { height: auto; }"

    def __init__(self, label: str, **kwargs: Any) -> None:
        # Initialise parent with empty lines — content arrives via append_line()
        super().__init__(label=label, lines=[], plain_lines=[], **kwargs)
        self._stream_label = label
        # Lines buffered between 60fps flush ticks
        self._pending: list[tuple[str, str]] = []  # (raw_ansi, plain)
        # All plain-text lines for clipboard (no display cap)
        self._all_plain: list[str] = []
        self._visible_count: int = 0
        self._total_received: int = 0
        self._cap_marker_written: bool = False
        self._spinner_frame: int = 0
        self._completed: bool = False
        self._tail_new_count: int = 0  # lines added while user scrolled away

    def on_mount(self) -> None:
        """Start expanded (user wants to see streaming output) + start timers."""
        self._body.add_class("expanded")
        self._header.collapsed = False
        self._header._has_affordances = False  # no toggle while streaming
        self._header._spinner_char = _SPINNER_FRAMES[0]
        self._render_timer = self.set_interval(1 / 60, self._flush_pending)
        self._spinner_timer = self.set_interval(0.25, self._tick_spinner)

    # ------------------------------------------------------------------
    # Streaming API (called from event loop via call_from_thread)
    # ------------------------------------------------------------------

    def append_line(self, raw: str) -> None:
        """Buffer a raw ANSI line for rendering on the next 60fps tick."""
        if self._completed:
            return
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

    def complete(self, duration: str) -> None:
        """Transition to COMPLETED state: flush remaining lines, update header."""
        if self._completed:
            return
        self._completed = True
        # Stop timers — no more streaming ticks needed
        try:
            self._render_timer.stop()
            self._spinner_timer.stop()
        except Exception:
            pass
        # Final synchronous flush
        self._flush_pending()
        # Hide tail badge unconditionally
        try:
            self.query_one(ToolTail).dismiss()
        except NoMatches:
            pass
        # Update header: remove spinner, add duration + line count
        self._header._spinner_char = None
        self._header._duration = duration
        self._header._line_count = self._total_received
        # Apply same collapse logic as static ToolBlock
        if self._total_received > COLLAPSE_THRESHOLD:
            self._header._has_affordances = True
            self._header.collapsed = True
            self._body.remove_class("expanded")
        else:
            self._header.collapsed = False
        self._header.refresh()
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

        for raw, plain in batch:
            if self._visible_count < _VISIBLE_CAP:
                log.write_with_source(Text.from_ansi(raw), plain)
                self._visible_count += 1
            elif not self._cap_marker_written:
                log.write(Text.from_markup(
                    f"[dim]  … (showing first {_VISIBLE_CAP} of "
                    f"{self._total_received} lines)[/dim]"
                ))
                self._cap_marker_written = True
            # Lines beyond cap are still in _all_plain (appended in append_line)

    # ------------------------------------------------------------------
    # Override copy_content to return all plain lines, not just visible
    # ------------------------------------------------------------------

    def copy_content(self) -> str:
        return "\n".join(self._all_plain)
