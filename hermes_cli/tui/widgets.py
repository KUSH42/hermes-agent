"""Textual widgets for the Hermes TUI.

All widgets follow these conventions (from the migration spec):
- Widget.render() returns Text objects, never plain str (plain str = literal, no markup)
- RichLog.write() has no markup kwarg — set markup= at construction
- query_one() raises NoMatches — use _safe_widget_call during teardown
- self.size.width is 0 during compose() — don't use for layout math
- set_interval callbacks must be def, not async def (unless they contain await)
- Reactive mutable defaults use factory form: reactive(list) not reactive([])
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import asyncio
import os
import re

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import ComposeResult, RenderResult
from textual.containers import ScrollableContainer
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.selection import Selection
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Input, RichLog, Static

from hermes_cli.tui.animation import PulseMixin, lerp_color

from hermes_cli.tui.state import (
    ChoiceOverlayState,
    OverlayState,
    SecretOverlayState,
)

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp


# ---------------------------------------------------------------------------
# Helper
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


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
    """Strip ANSI CSI escape sequences from text."""
    return _ANSI_RE.sub("", text)


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


class CopyableRichLog(RichLog):
    """RichLog that stores plain text for clipboard operations."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._plain_lines: list[str] = []

    def write_with_source(self, styled: Text, plain: str, **kwargs: Any) -> "CopyableRichLog":
        """Write styled text to display, store plain text for copy."""
        self._plain_lines.append(plain)
        return self.write(styled, **kwargs)

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        """Return plain text for the selected region.

        Overrides RichLog.get_selection() to return clean markdown without ANSI
        codes. Uses _plain_lines joined with newlines, then delegates extraction
        to Selection.extract() which handles line/column offsets correctly.

        Note: _plain_lines has one entry per write_with_source() call. RichLog
        wraps long lines internally, so a single write may produce multiple
        visual lines. Selection offsets reference the wrapped layout — for short
        lines this is fine, but wrapped lines may extract partial plain text.
        """
        if not self._plain_lines:
            return None
        text = "\n".join(self._plain_lines)
        return selection.extract(text), "\n"

    def copy_content(self) -> str:
        """Plain text for clipboard — no ANSI, no markup."""
        return "\n".join(self._plain_lines)

    def clear(self) -> "CopyableRichLog":
        self._plain_lines.clear()
        return super().clear()


def _safe_widget_call(app: HermesApp, widget_type: type, method: str, *args: Any) -> None:
    """Query a widget and call a method on it, swallowing NoMatches during teardown.

    Both the query and the method call execute on the event loop (the DOM is
    owned by the event loop thread). Callers from other threads must wrap this
    in ``app.call_from_thread(_safe_widget_call, app, ...)``.
    """
    try:
        getattr(app.query_one(widget_type), method)(*args)
    except NoMatches:
        pass  # widget removed during teardown — safe to ignore


# ---------------------------------------------------------------------------
# Output pipeline (Step 1)
# ---------------------------------------------------------------------------

class ToolPendingLine(Widget):
    """Shows in-progress tool calls as a stacked list while they are executing.

    Each pending entry is keyed by *tool_id* (typically the tool name).
    Lines are added via :meth:`set_line` when argument generation begins and
    removed via :meth:`remove_line` once the tool completes and the final
    cute-message is committed to the RichLog.  The widget auto-hides when the
    pending dict is empty.
    """

    DEFAULT_CSS = """
    ToolPendingLine {
        height: auto;
        display: none;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._lines: dict[str, Text] = {}
        self._order: list[str] = []

    def set_line(self, tool_id: str, styled: Text) -> None:
        """Add or update the in-progress line for *tool_id*."""
        if tool_id not in self._lines:
            self._order.append(tool_id)
        self._lines[tool_id] = styled
        self.display = True
        self.refresh()

    def remove_line(self, tool_id: str) -> None:
        """Remove the pending line for *tool_id*.  Auto-hides when empty."""
        if tool_id in self._lines:
            del self._lines[tool_id]
            self._order = [k for k in self._order if k in self._lines]
        if not self._lines:
            self.display = False
        self.refresh()

    def get_content_height(self, container, viewport, width: int) -> int:  # type: ignore[override]
        return max(1, len(self._lines))

    def render(self) -> RenderResult:
        if not self._lines:
            return Text("")
        t = Text()
        for i, key in enumerate(self._order):
            if key not in self._lines:
                continue
            if i > 0:
                t.append("\n")
            t.append_text(self._lines[key])
        return t


class LiveLineWidget(Widget):
    """Renders the current in-progress streaming chunk before it is committed.

    Accumulates text via :meth:`append` (direct) or :meth:`feed` (typewriter).
    When a newline arrives, all complete lines are committed to the parent
    OutputPanel's RichLog and only the trailing partial line remains in the buffer.

    Typewriter animation is opt-in via config (``terminal.typewriter.enabled``).
    When disabled, :meth:`feed` falls through to :meth:`append` with zero overhead.
    """

    DEFAULT_CSS = "LiveLineWidget { height: auto; }"

    _buf: reactive[str] = reactive("", repaint=True)
    _animating: reactive[bool] = reactive(False, repaint=True)

    def on_mount(self) -> None:
        self._tw_enabled: bool = _typewriter_enabled()
        self._tw_delay: float = _typewriter_delay_s()
        self._tw_burst: int = _typewriter_burst_threshold()
        self._tw_cursor: bool = _typewriter_cursor_enabled()
        if self._tw_enabled:
            self._char_queue: asyncio.Queue[str] = asyncio.Queue()
            self._drain_chars()
        # Non-typewriter blink state — initialized here (not __init__) to avoid
        # event-loop resource issues on Python ≤ 3.9.
        self._blink_visible: bool = True
        self._blink_timer: object | None = None
        self._blink_enabled: bool = _cursor_blink_enabled()

    def on_unmount(self) -> None:
        self._animating = False
        # Cancel blink timer if active
        if getattr(self, "_blink_timer", None) is not None:
            self._blink_timer.stop()
            self._blink_timer = None

    def render(self) -> RenderResult:
        if not self._buf and not self._animating:
            return Text("")
        t = Text.from_ansi(self._buf) if self._buf else Text("")
        # Typewriter cursor (existing path — typewriter on):
        if self._animating and getattr(self, "_tw_cursor", True):
            t.append("▌", style="blink")
        # Non-typewriter blink (only when typewriter is off and blink timer active):
        elif (
            not getattr(self, "_tw_enabled", False)
            and getattr(self, "_blink_timer", None) is not None
            and getattr(self, "_blink_visible", True)
        ):
            t.append("▌", style="dim")
        return t

    def _commit_lines(self) -> None:
        """Commit all complete lines in _buf to the current MessagePanel's RichLog."""
        if "\n" not in self._buf:
            return
        lines = self._buf.split("\n")
        try:
            panel = self.app.query_one(OutputPanel)
            msg = panel.current_message
            if msg is None:
                msg = panel.new_message()
            rl = msg.response_log
            msg.show_response_rule()
            for committed in lines[:-1]:
                plain = _strip_ansi(committed)
                if isinstance(rl, CopyableRichLog):
                    rl.write_with_source(Text.from_ansi(committed), plain)
                else:
                    rl.write(Text.from_ansi(committed))
            if rl._deferred_renders:
                self.call_after_refresh(msg.refresh, layout=True)
        except NoMatches:
            pass
        self._buf = lines[-1]

    def append(self, chunk: str) -> None:
        """Append *chunk* directly; commit complete lines to the MessagePanel's RichLog."""
        self._buf += chunk
        if "\n" in self._buf:
            self._commit_lines()

    def _toggle_blink(self) -> None:
        """Blink timer callback — plain def required (no await)."""
        self._blink_visible = not self._blink_visible
        self.refresh()

    def feed(self, chunk: str) -> None:
        """Enqueue *chunk* for typewriter animation (falls through to append when disabled).

        ANSI escape sequences are enqueued as atomic items so _buf never contains
        a partial escape code between render frames.  Must be called from the event loop.
        """
        if not getattr(self, "_tw_enabled", False):
            # Non-typewriter path: start blink timer on first chunk (if enabled)
            if (
                getattr(self, "_blink_timer", None) is None
                and getattr(self, "_blink_enabled", True)
            ):
                self._blink_timer = self.set_interval(0.5, self._toggle_blink)
            self.append(chunk)
            return
        pos = 0
        for m in _ANSI_SEQ_RE.finditer(chunk):
            for ch in chunk[pos:m.start()]:
                self._char_queue.put_nowait(ch)
            self._char_queue.put_nowait(m.group(0))
            pos = m.end()
        for ch in chunk[pos:]:
            self._char_queue.put_nowait(ch)

    @work(exclusive=False)
    async def _drain_chars(self) -> None:
        """Long-running drainer — started once in on_mount(), exits on unmount.

        Burst compensation batch-drains when the queue is deep, avoiding O(N)
        asyncio.sleep calls for fast model output.
        """
        delay = self._tw_delay
        burst = self._tw_burst
        try:
            while self.is_mounted:
                try:
                    char = await asyncio.wait_for(
                        self._char_queue.get(), timeout=0.5
                    )
                except asyncio.TimeoutError:
                    continue

                self._animating = True
                self._buf += char
                if "\n" in self._buf:
                    self._commit_lines()

                qsize = self._char_queue.qsize()
                if qsize >= burst:
                    for _ in range(min(qsize, burst * 2)):
                        try:
                            c = self._char_queue.get_nowait()
                            self._buf += c
                            if "\n" in self._buf:
                                self._commit_lines()
                        except asyncio.QueueEmpty:
                            break
                    await asyncio.sleep(0)
                else:
                    await asyncio.sleep(delay)

                if self._char_queue.empty():
                    self._animating = False
        finally:
            self._animating = False

    def flush(self) -> None:
        """Synchronously drain all pending chars from _char_queue.

        Called from OutputPanel.flush_live() on the event loop when the None
        sentinel arrives.  Safe because asyncio is single-threaded.
        Also stops the non-typewriter blink timer.
        """
        # Stop non-typewriter blink timer
        if getattr(self, "_blink_timer", None) is not None:
            self._blink_timer.stop()
            self._blink_timer = None
        self._blink_visible = True  # reset to visible for next turn

        if not getattr(self, "_tw_enabled", False) or not hasattr(self, "_char_queue"):
            return
        while True:
            try:
                char = self._char_queue.get_nowait()
                self._buf += char
                if "\n" in self._buf:
                    self._commit_lines()
            except asyncio.QueueEmpty:
                break
        self._animating = False


class MessagePanel(Widget):
    """Groups a response TitledRule + ReasoningPanel + response RichLog for one assistant turn."""

    DEFAULT_CSS = """
    MessagePanel {
        height: auto;
    }
    MessagePanel RichLog {
        height: auto;
        overflow-y: hidden;
        overflow-x: hidden;
    }
    MessagePanel TitledRule {
        display: none;
    }
    MessagePanel TitledRule.visible {
        display: block;
    }
    """

    _msg_counter: int = 0

    def __init__(self, **kwargs: Any) -> None:
        MessagePanel._msg_counter += 1
        self._msg_id = MessagePanel._msg_counter
        self._response_rule = TitledRule(id=f"response-rule-{self._msg_id}")
        self._reasoning_panel = ReasoningPanel(id=f"reasoning-{self._msg_id}")
        self._response_log = CopyableRichLog(
            markup=False, highlight=False, wrap=True,
            id=f"response-{self._msg_id}",
        )
        super().__init__(**kwargs)

    def on_mount(self) -> None:
        # Skip animation under pytest: styles.animate 60fps callbacks compete
        # with RichLog._deferred_renders commit ticks and cause flaky failures.
        # Tests only assert final opacity==1.0, which holds without animation.
        import os
        if "PYTEST_CURRENT_TEST" not in os.environ:
            self.call_after_refresh(self._start_fade)

    def _start_fade(self) -> None:
        """Fade-in after first render (plain def — no await).

        Fires after the first layout pass so child RichLog widgets have already
        been sized. Sets opacity to 0 then immediately animates to 1.
        """
        self.styles.opacity = 0.0
        self.styles.animate("opacity", 1.0, duration=0.25, easing="out_cubic")

    def compose(self) -> ComposeResult:
        yield self._response_rule
        yield self._reasoning_panel
        yield self._response_log

    def show_response_rule(self) -> None:
        """Show the response title rule (called when first content arrives)."""
        self._response_rule.add_class("visible")

    @property
    def reasoning(self) -> ReasoningPanel:
        return self._reasoning_panel

    @property
    def response_log(self) -> CopyableRichLog:
        return self._response_log


# ---------------------------------------------------------------------------
# Shimmer character table: ascending density from space to ▓ and back
# ---------------------------------------------------------------------------

_SHIMMER_CHARS = " ░▒▓▒░"
_SHIMMER_LEN   = len(_SHIMMER_CHARS)


class ThinkingWidget(Widget):
    """Animated skeleton placeholder shown while the agent is thinking.

    Shown after prompt submission, before the first response token arrives.
    Uses ``render_line()`` for per-cell shimmer animation at 8fps.
    """

    DEFAULT_CSS = "ThinkingWidget { height: 1; display: none; }"

    _phase: reactive[int] = reactive(0, repaint=True)
    _shimmer_timer: object | None = None

    def activate(self) -> None:
        """Show shimmer and start animation. Call from event loop only."""
        self.styles.display = "block"
        if self._shimmer_timer is None:
            self._shimmer_timer = self.set_interval(1 / 8, self._advance_phase)

    def deactivate(self) -> None:
        """Hide shimmer and stop animation. Idempotent. Call from event loop only."""
        if self._shimmer_timer is not None:
            self._shimmer_timer.stop()
            self._shimmer_timer = None
        self.styles.display = "none"
        self._phase = 0

    def _advance_phase(self) -> None:
        """Timer callback — plain def required (no await)."""
        self._phase = (self._phase + 1) % (_SHIMMER_LEN * 4)

    def render_line(self, y: int) -> Strip:
        # height: 1 → Textual only calls render_line(0), but guard defensively.
        if y != 0:
            return Strip.blank(self.size.width or 40)
        width = self.size.width or 40
        phase = self._phase
        segments: list[Segment] = []
        for x in range(width):
            idx = (x + phase) % _SHIMMER_LEN
            char = _SHIMMER_CHARS[idx]
            brightness = idx / max(_SHIMMER_LEN - 1, 1)
            color = lerp_color("#1a1a1a", "#4a4a4a", brightness)
            segments.append(Segment(char, Style(color=color)))
        return Strip(segments).crop(0, width)


class OutputPanel(ScrollableContainer):
    """Scrollable output area containing MessagePanels + live in-progress line.

    ``_user_scrolled_up`` is ``True`` when the user has manually scrolled away
    from the bottom.  When this flag is set, automatic ``scroll_end()`` calls
    from streaming output are suppressed so the user can read previous content
    without losing their position.  The flag is cleared when the scroll
    position returns to (near) the bottom.
    """

    DEFAULT_CSS = """
    OutputPanel {
        height: 1fr;
        overflow-y: auto;
        overflow-x: hidden;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._user_scrolled_up: bool = False

    def watch_scroll_y(self, new_y: float) -> None:
        """Re-engage auto-scroll when the user scrolls back to the bottom."""
        # max_scroll_y can be 0 when the panel hasn't laid out yet; guard against that.
        if self.max_scroll_y > 0 and new_y >= self.max_scroll_y - 3:
            self._user_scrolled_up = False

    def on_mouse_scroll_up(self, _event: Any) -> None:
        """Mark that the user has scrolled up — suppress auto-scroll."""
        self._user_scrolled_up = True

    def on_scroll_up(self, _event: Any) -> None:
        """Mark that the user has scrolled up via keyboard — suppress auto-scroll."""
        self._user_scrolled_up = True

    def compose(self) -> ComposeResult:
        yield ToolPendingLine(id="tool-pending")
        yield ThinkingWidget(id="thinking")
        yield LiveLineWidget(id="live-line")

    @property
    def live_line(self) -> LiveLineWidget:
        return self.query_one(LiveLineWidget)

    @property
    def tool_pending(self) -> ToolPendingLine:
        return self.query_one(ToolPendingLine)

    @property
    def current_message(self) -> MessagePanel | None:
        """Return the most recent MessagePanel, or None."""
        panels = self.query(MessagePanel)
        return panels.last() if panels else None

    def new_message(self) -> MessagePanel:
        """Create and mount a new MessagePanel for a new turn."""
        panel = MessagePanel()
        self.mount(panel, before=self.live_line)
        return panel

    def flush_live(self) -> None:
        """Commit any in-progress buffered line to current message's RichLog."""
        # Deactivate shimmer — covers the empty-response case where no chunk ever arrives
        try:
            self.query_one(ThinkingWidget).deactivate()
        except NoMatches:
            pass
        live = self.live_line
        live.flush()  # drain _char_queue before reading _buf (no-op when typewriter disabled)
        if live._buf:
            msg = self.current_message
            if msg is None:
                msg = self.new_message()
            msg.show_response_rule()
            rl = msg.response_log
            plain = _strip_ansi(live._buf)
            if isinstance(rl, CopyableRichLog):
                rl.write_with_source(Text.from_ansi(live._buf), plain)
            else:
                rl.write(Text.from_ansi(live._buf))
            if rl._deferred_renders:
                self.call_after_refresh(msg.refresh, layout=True)
            live._buf = ""


# ---------------------------------------------------------------------------
# User echo panel
# ---------------------------------------------------------------------------

class UserEchoPanel(Widget):
    """Displays the user's submitted message framed by short fade rulers.

    Mounted into OutputPanel when the user sends a message, before the new
    MessagePanel is created for the response.
    """

    DEFAULT_CSS = """
    UserEchoPanel {
        height: auto;
        margin: 1 0 0 0;
        padding: 0 1;
    }
    """

    _ECHO_RULE_WIDTH = 30

    def __init__(self, message: str, images: int = 0, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._message = message
        self._images = images

    def compose(self) -> ComposeResult:
        yield PlainRule(max_width=self._ECHO_RULE_WIDTH, id="echo-rule-top")
        yield Static(self._format_message(), id="echo-text")
        if self._images:
            yield Static(self._format_images(), id="echo-images")
        yield PlainRule(max_width=self._ECHO_RULE_WIDTH, id="echo-rule-bottom")

    def _format_message(self) -> Text:
        bullet_color = _skin_color("ui_accent", "#FFBF00")
        t = Text()
        t.append("● ", style=f"bold {bullet_color}")
        msg = self._message
        if "\n" in msg:
            first_line = msg.split("\n")[0]
            line_count = msg.count("\n") + 1
            t.append(first_line, style="bold")
            t.append(f" (+{line_count - 1} lines)", style="dim")
        else:
            t.append(msg, style="bold")
        return t

    def _format_images(self) -> Text:
        n = self._images
        return Text(f"  📎 {n} image{'s' if n > 1 else ''} attached", style="dim")


# ---------------------------------------------------------------------------
# Reasoning panel (Step 2)
# ---------------------------------------------------------------------------

class ReasoningPanel(Widget):
    """Collapsible reasoning display with left gutter marker.

    Hidden by default via CSS ``display: none``. Toggled visible via the
    ``visible`` CSS class when reasoning output arrives. Each committed
    line is prefixed with a ``▌`` gutter marker in dim style.
    """

    GUTTER = "▌ "

    DEFAULT_CSS = """
    ReasoningPanel {
        display: none;
        height: auto;
        margin: 0 1;
    }
    ReasoningPanel.visible {
        display: block;
    }
    ReasoningPanel RichLog {
        height: auto;
        overflow-y: hidden;
        overflow-x: hidden;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        self._reasoning_log = RichLog(markup=False, highlight=False, wrap=True, id="reasoning-log")
        super().__init__(**kwargs)
        self._live_buf = ""
        self._plain_lines: list[str] = []

    def compose(self) -> ComposeResult:
        yield self._reasoning_log

    def _gutter_line(self, content: str) -> Text:
        """Build a dim gutter-prefixed line for the reasoning log."""
        t = Text()
        t.append(self.GUTTER, style="dim")
        t.append(content, style="dim italic")
        return t

    def open_box(self, title: str) -> None:
        """Show the reasoning panel."""
        self._live_buf = ""
        self._plain_lines.clear()
        self.add_class("visible")
        # Trigger layout refresh so parent recalculates height after
        # deferred renders are processed on the next resize event.
        self.call_after_refresh(self.refresh, layout=True)

    def append_delta(self, text: str) -> None:
        """Append a reasoning text delta, streaming character-by-character.

        Buffers partial lines and commits on newlines so the RichLog
        shows complete lines while still updating in real-time.
        Each committed line gets a ``▌`` gutter prefix.
        """
        self._live_buf += text
        log = self._reasoning_log
        wrote = False
        # Commit complete lines
        while "\n" in self._live_buf:
            line, self._live_buf = self._live_buf.split("\n", 1)
            log.write(self._gutter_line(line))
            self._plain_lines.append(line)
            wrote = True
        if wrote and log._deferred_renders:
            self.call_after_refresh(self.refresh, layout=True)

    def close_box(self) -> None:
        """Flush remaining buffer. The panel stays visible as message history."""
        # Flush any partial line
        buf = self._live_buf
        if buf:
            self._reasoning_log.write(self._gutter_line(buf))
            self._plain_lines.append(buf)
            self._live_buf = ""
        # Don't remove "visible" — reasoning stays shown as part of the
        # message so it isn't lost when tool output or the next response
        # pushes new content into the same MessagePanel.
        self.call_after_refresh(self.refresh, layout=True)


# ---------------------------------------------------------------------------
# Titled rule (separator with embedded title)
# ---------------------------------------------------------------------------

def _fade_rule(count: int, start_hex: str, end_hex: str) -> Text:
    """Build a run of ``─`` chars that fade from *start_hex* to *end_hex*.

    Uses Rich's ``blend_rgb`` for interpolation — no extra dependencies.
    """
    from rich.color import Color, blend_rgb

    if count <= 0:
        return Text()
    c_start = Color.parse(start_hex).get_truecolor()
    c_end = Color.parse(end_hex).get_truecolor()
    t = Text()
    for i in range(count):
        factor = i / max(count - 1, 1)
        c = blend_rgb(c_start, c_end, factor)
        t.append("─", style=f"rgb({c.red},{c.green},{c.blue})")
    return t


class TitledRule(Widget):
    """Horizontal rule with an embedded title and fading rule chars.

    Pass ``show_state=True`` on the input-rule instance to get a right-side
    state glyph (``⟳`` amber when agent/command is running, hidden when idle).
    """

    DEFAULT_CSS = """
    TitledRule {
        height: 1;
    }
    """

    title_text: reactive[str] = reactive("Hermes")

    def __init__(
        self,
        title: str | None = None,
        fade_start: str | None = None,
        fade_end: str | None = None,
        accent: str | None = None,
        title_color: str | None = None,
        show_state: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.title_text = title or _skin_branding("response_label", "⚕ Hermes")
        self._fade_start = fade_start or _skin_color("rule_start", "#555555")
        self._fade_end = fade_end or _skin_color("rule_end", "#2A2A2A")
        self._accent = accent or _skin_color("banner_title", "#FFD700")
        self._title_color = title_color or _skin_color("banner_dim", "#B8860B")
        self._show_state = show_state

    def on_mount(self) -> None:
        if self._show_state:
            self.watch(self.app, "agent_running", self._on_state_change)
            self.watch(self.app, "command_running", self._on_state_change)

    def _on_state_change(self, _value: object = None) -> None:
        self.refresh()

    def render(self) -> RenderResult:
        w = self.size.width
        title = self.title_text
        # Split title into accent char (first non-space) + rest
        # e.g. "⚕ Hermes" → accent="⚕", rest=" Hermes"
        parts = title.split(" ", 1)
        accent_char = parts[0] if parts else ""
        rest = (" " + parts[1]) if len(parts) > 1 else ""

        # Right-side state glyph — only on instances with show_state=True,
        # only visible when the agent is running.
        state_suffix = Text()
        if self._show_state:
            running = (
                getattr(self.app, "agent_running", False)
                or getattr(self.app, "command_running", False)
            )
            if running:
                state_suffix = Text(" ⟳", style="#ffa726")

        label_len = len(f"{title} ")
        right = max(0, w - label_len - state_suffix.cell_len)
        t = Text()
        # Title: accent char in bright accent, rest in title_color
        t.append(accent_char, style=f"bold {self._accent}")
        t.append(f"{rest} ", style=f"{self._title_color}")
        # Right fill: fade out (start → end), then optional state glyph
        t.append_text(_fade_rule(right, self._fade_start, self._fade_end))
        t.append_text(state_suffix)
        return t


class PlainRule(Widget):
    """Plain horizontal rule that fades out."""

    DEFAULT_CSS = """
    PlainRule {
        height: 1;
    }
    """

    def __init__(
        self,
        fade_start: str | None = None,
        fade_end: str | None = None,
        max_width: int = 0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._fade_start = fade_start or _skin_color("rule_start", "#555555")
        self._fade_end = fade_end or _skin_color("rule_end", "#2A2A2A")
        self._max_width = max_width

    def render(self) -> RenderResult:
        w = self.size.width
        if self._max_width:
            w = min(w, self._max_width)
        return _fade_rule(w, self._fade_start, self._fade_end)


# ---------------------------------------------------------------------------
# Hint bar + spinner (Step 3)
# ---------------------------------------------------------------------------

class HintBar(Static):
    """Single-line hint / countdown display below the overlay layer.

    ``HermesApp`` has NO ``hint_text`` reactive. ``HintBar.hint`` is the
    single source of truth. ``_tick_spinner`` writes to
    ``app.query_one(HintBar).hint`` directly.
    """

    DEFAULT_CSS = """
    HintBar {
        height: 1;
        display: none;
    }
    HintBar.visible {
        display: block;
    }
    """

    hint: reactive[str] = reactive("")

    def watch_hint(self, value: str) -> None:
        self.update(value)
        if value:
            self.add_class("visible")
        else:
            self.remove_class("visible")


# ---------------------------------------------------------------------------
# Status bar (Step 3)
# ---------------------------------------------------------------------------

_BAR_FILLED = "▰"
_BAR_EMPTY = "▱"
_BAR_WIDTH = 20


class StatusBar(PulseMixin, Widget):
    """Bottom status bar showing model, compaction bar, tok/s, tokens, and duration.

    Inherits PulseMixin for the running-indicator pulse animation.
    Reads directly from the App's reactives — no duplicated state.
    """

    DEFAULT_CSS = "StatusBar { height: 1; dock: bottom; }"

    # Animated tok/s backing reactive — drives smooth counter easing
    _tok_s_displayed: reactive[float] = reactive(0.0, repaint=True)

    def on_mount(self) -> None:
        app = self.app
        # Register all standard attributes to the generic refresh callback.
        # IMPORTANT: "agent_running" and "status_tok_s" are registered to
        # dedicated callbacks below — omit them here to avoid double-registration.
        for attr in (
            "status_tokens", "status_model", "status_duration",
            "status_compaction_progress", "status_compaction_enabled",
            "command_running",
            "browse_mode", "browse_index", "_browse_total",
            "status_output_dropped",
        ):
            self.watch(app, attr, self._on_status_change)
        # agent_running: dedicated callback to start/stop pulse + refresh
        self.watch(app, "agent_running", self._on_agent_running_change)
        # status_tok_s: dedicated callback to animate _tok_s_displayed
        self.watch(app, "status_tok_s", self._on_tok_s_change)
        # _browse_uses is a plain int (not reactive) — watch browse_mode instead,
        # which always fires before we need to re-render.

    def _on_status_change(self, _value: object = None) -> None:
        self.refresh()

    def _on_agent_running_change(self, running: bool = False) -> None:
        """Start or stop the pulse animation when agent_running changes."""
        if running and _pulse_enabled():
            self._pulse_start()
        else:
            self._pulse_stop()
        self.refresh()

    def _on_tok_s_change(self, tok_s: float = 0.0) -> None:
        """Animate _tok_s_displayed to new tok/s value over 200ms."""
        if _animate_counters_enabled():
            self.animate("_tok_s_displayed", float(tok_s), duration=0.2, easing="out_cubic")
        else:
            self._tok_s_displayed = float(tok_s)

    def render(self) -> RenderResult:
        app = self.app
        width = self.size.width

        browse = getattr(app, "browse_mode", False)
        browse_idx = getattr(app, "browse_index", 0)

        if browse:
            # Use memoized counter — avoids O(n) DOM query per keystroke
            browse_total = getattr(app, "_browse_total", 0)

            browse_uses = getattr(app, "_browse_uses", 0)
            left = Text(f"BROWSE ▸{browse_idx + 1}/{browse_total}", style="bold")
            if width >= 60:
                if browse_uses <= 3:
                    left.append("  Tab · Enter · c copy · a expand-all · Esc exit", style="dim")
                else:
                    left.append("  Tab · c · a/A · Esc", style="dim")
            elif width >= 40:
                left.append("  Tab · c · Esc", style="dim")
            # Right side: tokens · duration
            tokens = getattr(app, "status_tokens", 0)
            duration = str(getattr(app, "status_duration", "0s"))
            right = Text()
            if width >= 60:
                right.append(f"{tokens} tok", style="dim")
                right.append("  ", style="dim")
                right.append(duration, style="dim")
            elif width >= 40:
                right.append(f"{tokens} tok", style="dim")
            else:
                right.append(duration, style="dim")
            pad = max(0, width - left.cell_len - right.cell_len)
            left.append(" " * pad)
            left.append_text(right)
            return left

        model    = str(getattr(app, "status_model", ""))
        duration = str(getattr(app, "status_duration", "0s"))
        tokens   = getattr(app, "status_tokens", 0)
        progress = getattr(app, "status_compaction_progress", 0.0)
        enabled  = getattr(app, "status_compaction_enabled", True)
        # Use the animated _tok_s_displayed reactive for smooth counter easing
        tok_s    = self._tok_s_displayed
        running  = (
            getattr(app, "agent_running", False)
            or getattr(app, "command_running", False)
        )

        t = Text()
        t.append(model, style="dim")

        if width < 40:
            # Minimal: model · duration
            t.append(" · ", style="dim")
            t.append(duration, style="dim")
        elif width < 60:
            # Compact: % · tokens · duration (no bar)
            if enabled and progress > 0:
                pct_int = min(int(progress * 100), 100)
                t.append(" · ", style="dim")
                t.append(f"{pct_int}%", style=self._compaction_color(progress))
            t.append(" · ", style="dim")
            t.append(f"{tokens} tok", style="dim")
            t.append(" · ", style="dim")
            t.append(duration, style="dim")
        else:
            # Full: bar % · tok/s · tokens · duration
            if enabled and progress > 0:
                pct_int = min(int(progress * 100), 100)
                filled  = min(int(progress * _BAR_WIDTH), _BAR_WIDTH)
                bar_str = _BAR_FILLED * filled + _BAR_EMPTY * (_BAR_WIDTH - filled)
                bar_color = self._compaction_color(progress)
                t.append("  ")
                t.append(bar_str, style=bar_color)
                t.append(" ")
                t.append(f"{pct_int}%", style=bar_color)
            if tok_s > 0:
                t.append(" · ", style="dim")
                t.append(f"{tok_s:.0f} tok/s", style="dim")
            t.append(" · ", style="dim")
            t.append(f"{tokens} tok", style="dim")
            t.append(" · ", style="dim")
            t.append(duration, style="dim")

        # Right-anchored state label (with optional dropped-output warning).
        # When agent is running, the ● indicator pulses between two accent shades.
        dropped = getattr(app, "status_output_dropped", False)
        if running:
            if self._pulse_t > 0:
                pulse_color = lerp_color("#ffa726", "#ffbf00", self._pulse_t)
            else:
                pulse_color = "#ffa726"
            state_t = Text(" ● running", style=f"bold {pulse_color}")
        else:
            state_t = Text(" idle", style="dim")
        if dropped:
            state_t = Text(" ⚠ output truncated", style="#ef5350") + state_t
        pad = max(0, width - t.cell_len - state_t.cell_len)
        t.append(" " * pad)
        t.append_text(state_t)

        return t

    @staticmethod
    def _compaction_color(progress: float) -> str:
        """Return Rich style hex color for compaction bar, smoothly lerped between bands."""
        try:
            from hermes_cli.skin_engine import get_active_skin
            skin = get_active_skin()
        except Exception:
            skin = None

        color_normal = skin.get_ui_ext("context_bar_normal", "#5f87d7") if skin else "#5f87d7"
        color_warn   = skin.get_ui_ext("context_bar_warn",   "#ffa726") if skin else "#ffa726"
        color_crit   = skin.get_ui_ext("context_bar_crit",   "#ef5350") if skin else "#ef5350"

        if progress >= 0.95:
            return color_crit
        if progress >= 0.80:
            # Lerp from warn → crit across the 0.80–0.95 band
            t = (progress - 0.80) / 0.15
            return lerp_color(color_warn, color_crit, t)
        if progress >= 0.50:
            # Lerp from normal → warn across the 0.50–0.80 band
            t = (progress - 0.50) / 0.30
            return lerp_color(color_normal, color_warn, t)
        return color_normal


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# AnimatedCounter — reusable numeric counter widget with smooth easing
# ---------------------------------------------------------------------------

class AnimatedCounter(Widget):
    """
    Reusable leaf widget: smoothly eases a numeric value when updated.

    Use ``set_target()`` from the event loop or via ``call_from_thread``.
    The value is rounded to the nearest integer for display; an optional
    unit suffix is shown dim after the number.
    """

    DEFAULT_CSS = "AnimatedCounter { height: 1; width: auto; }"

    _displayed: reactive[float] = reactive(0.0, repaint=True)
    _unit: str = ""

    def set_target(self, value: float, unit: str = "") -> None:
        """Animate to value over 200ms. Safe to call from the event loop."""
        self._unit = unit
        self.animate("_displayed", float(value), duration=0.2, easing="out_cubic")

    def render(self) -> RenderResult:
        t = Text(str(round(self._displayed)))
        if self._unit:
            t.append(f" {self._unit}", style="dim")
        return t


# ---------------------------------------------------------------------------
# Voice status bar (Step 3)
# ---------------------------------------------------------------------------

class VoiceStatusBar(Widget):
    """Persistent voice recording status indicator.

    Hidden by default; toggled via the ``active`` CSS class driven by
    ``HermesApp.watch_voice_mode``.
    """

    DEFAULT_CSS = """
    VoiceStatusBar {
        display: none;
        height: 1;
        color: $error;
    }
    VoiceStatusBar.active {
        display: block;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="voice-status-text")

    def update_status(self, text: str) -> None:
        try:
            self.query_one("#voice-status-text", Static).update(text)
        except NoMatches:
            pass


# ---------------------------------------------------------------------------
# Image bar (Step 3)
# ---------------------------------------------------------------------------

class ImageBar(Static):
    """Displays attached image filenames; hidden when empty."""

    DEFAULT_CSS = """
    ImageBar {
        display: none;
        height: auto;
    }
    """

    def update_images(self, images: list) -> None:
        """Update the displayed image list and toggle visibility."""
        if images:
            self.display = True
            names = ", ".join(getattr(img, "name", str(img)) for img in images)
            self.update(f"[dim]📎 {names}[/dim]")
        else:
            self.display = False
            self.update("")


# ---------------------------------------------------------------------------
# CountdownMixin (Step 4)
# ---------------------------------------------------------------------------

class CountdownMixin:
    """Shared countdown logic for timed overlays.

    Subclasses must define:
      - ``_state_attr``: str — the HermesApp reactive attribute name
      - ``_timeout_response``: value to put on response_queue on expiry
      - ``_countdown_prefix``: str — used for countdown widget ID
      - A ``Static`` with ``id="{prefix}-countdown"`` in compose()
    """

    _state_attr: str
    _timeout_response: object = None
    _countdown_prefix: str = ""

    def _start_countdown(self) -> None:
        """Call from on_mount(). Starts the 1-second tick timer."""
        self.set_interval(1.0, self._tick_countdown)

    def _tick_countdown(self) -> None:
        """Tick handler — update countdown display and auto-resolve on expiry.

        Runs ON the event loop (set_interval callback), so direct mutation is
        correct; call_from_thread would be wrong here.
        """
        state: OverlayState | None = getattr(self.app, self._state_attr)
        if state is None:
            return
        countdown_id = f"#{self._countdown_prefix}-countdown"
        try:
            self.query_one(countdown_id, Static).update(
                f"[dim]({state.remaining}s)[/dim]"
            )
        except NoMatches:
            pass
        if state.expired:
            self._resolve_timeout(state)

    def _resolve_timeout(self, state: OverlayState) -> None:
        """Put timeout response on queue and clear state. Runs on event loop."""
        state.response_queue.put(self._timeout_response)
        setattr(self.app, self._state_attr, None)


# ---------------------------------------------------------------------------
# Clarify widget (Step 4)
# ---------------------------------------------------------------------------

class ClarifyWidget(CountdownMixin, Widget):
    """Choice overlay with countdown for clarification questions."""

    _state_attr = "clarify_state"
    _timeout_response = None
    _countdown_prefix = "clarify"

    DEFAULT_CSS = """
    ClarifyWidget {
        display: none;
        height: auto;
        border: tall $warning;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="clarify-question")
        yield Static("", id="clarify-choices")
        yield Static("", id="clarify-countdown")

    def on_mount(self) -> None:
        self._start_countdown()

    def update(self, state: ChoiceOverlayState) -> None:
        """Populate content from typed state and make visible."""
        self.display = True
        try:
            self.query_one("#clarify-question", Static).update(state.question)
            choices_markup = "\n".join(
                f"[bold]→[/bold] {c}" if i == state.selected else f"  {c}"
                for i, c in enumerate(state.choices)
            )
            self.query_one("#clarify-choices", Static).update(choices_markup)
        except NoMatches:
            pass

    def hide(self) -> None:
        self.display = False


# ---------------------------------------------------------------------------
# Approval widget (Step 4)
# ---------------------------------------------------------------------------

class ApprovalWidget(CountdownMixin, Widget):
    """Choice overlay for dangerous-command approval with 'deny' timeout."""

    _state_attr = "approval_state"
    _timeout_response = "deny"
    _countdown_prefix = "approval"

    DEFAULT_CSS = """
    ApprovalWidget {
        display: none;
        height: auto;
        border: tall $error;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="approval-question")
        yield Static("", id="approval-choices")
        yield Static("", id="approval-countdown")

    def on_mount(self) -> None:
        self._start_countdown()

    def update(self, state: ChoiceOverlayState) -> None:
        """Populate content from typed state."""
        self.display = True
        try:
            self.query_one("#approval-question", Static).update(state.question)
            choices_markup = "\n".join(
                f"[bold]→[/bold] {c}" if i == state.selected else f"  {c}"
                for i, c in enumerate(state.choices)
            )
            self.query_one("#approval-choices", Static).update(choices_markup)
        except NoMatches:
            pass

    def hide(self) -> None:
        self.display = False


# ---------------------------------------------------------------------------
# Sudo widget (Step 4)
# ---------------------------------------------------------------------------

class SudoWidget(CountdownMixin, Widget):
    """Password input overlay for sudo commands with countdown."""

    _state_attr = "sudo_state"
    _timeout_response = None
    _countdown_prefix = "sudo"

    DEFAULT_CSS = """
    SudoWidget {
        display: none;
        height: auto;
        border: tall $warning;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="sudo-prompt")
        yield Input(password=True, placeholder="sudo password", id="sudo-input")
        yield Static("", id="sudo-countdown")

    def on_mount(self) -> None:
        self._start_countdown()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """User pressed Enter in the password field."""
        state = getattr(self.app, "sudo_state", None)
        if state is None:
            return
        state.response_queue.put(event.value)
        self.app.sudo_state = None

    def update(self, state: SecretOverlayState) -> None:
        """Populate and show the sudo prompt."""
        self.display = True
        try:
            self.query_one("#sudo-prompt", Static).update(state.prompt)
            inp = self.query_one("#sudo-input", Input)
            inp.clear()
            inp.focus()
        except NoMatches:
            pass

    def hide(self) -> None:
        self.display = False


# ---------------------------------------------------------------------------
# Secret widget (Step 4)
# ---------------------------------------------------------------------------

class SecretWidget(CountdownMixin, Widget):
    """Captures a secret value (API key, token, etc.) with masked input."""

    _state_attr = "secret_state"
    _timeout_response = None
    _countdown_prefix = "secret"

    DEFAULT_CSS = """
    SecretWidget {
        display: none;
        height: auto;
        border: tall $warning;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="secret-prompt")
        yield Input(password=True, placeholder="enter secret value", id="secret-input")
        yield Static("", id="secret-countdown")

    def on_mount(self) -> None:
        self._start_countdown()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """User pressed Enter in the secret field."""
        state = getattr(self.app, "secret_state", None)
        if state is None:
            return
        state.response_queue.put(event.value)
        self.app.secret_state = None

    def update(self, state: SecretOverlayState) -> None:
        """Populate and show the secret prompt."""
        self.display = True
        try:
            self.query_one("#secret-prompt", Static).update(state.prompt)
            inp = self.query_one("#secret-input", Input)
            inp.clear()
            inp.focus()
        except NoMatches:
            pass

    def hide(self) -> None:
        self.display = False
