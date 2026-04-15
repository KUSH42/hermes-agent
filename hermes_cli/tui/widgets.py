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

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import asyncio
import os
import re
import time

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import ComposeResult, RenderResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, VerticalScroll
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.selection import Selection
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Input, RichLog, Static

from hermes_cli.tui.animation import PulseMixin, lerp_color, shimmer_text

from hermes_cli.tui.state import (
    ChoiceOverlayState,
    OverlayState,
    SecretOverlayState,
    UndoOverlayState,
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


_ANSI_RE = re.compile(
    r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]"
)
_PRENUMBERED_LINE_RE = re.compile(r"^\s*(\d+)(?:\s*[│|:]\s?|\s{2,})(.*)$")
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


def _fps_hud_enabled() -> bool:
    """FPS/ms HUD overlay — off by default, toggleable at runtime (default: false)."""
    try:
        from hermes_cli.config import read_raw_config
        return bool(read_raw_config().get("display", {}).get("fps_hud", False))
    except Exception:
        return False


class CopyableRichLog(RichLog, can_focus=False):
    """RichLog that stores plain text for clipboard operations.

    ``can_focus=False`` prevents Textual's focus machinery from calling
    ``Screen.scroll_to_center`` → ``scroll_to_widget`` → ``OutputPanel.
    scroll_to_region`` when this widget is clicked, which would scroll the
    output to y=0 (scroll-to-top regression).

    Text selection still works: in Textual 8.x selection is gated on
    ``ALLOW_SELECT`` / ``allow_select()`` (default True), not on ``can_focus``.
    Mouse events (MouseDown/Move/Up) are delivered by cursor position, not
    focus, so drag-to-select is unaffected.

    Overrides ``overflow-y: scroll`` from RichLog.DEFAULT_CSS to ``hidden``
    so that mouse-scroll events are NOT stopped here and can bubble up to
    the parent OutputPanel (the intended scroll container).  Without this,
    Textual's ``_on_mouse_scroll_up`` sees ``allow_vertical_scroll=True``
    on CopyableRichLog, calls ``event.stop()``, and OutputPanel never scrolls.
    Note: the ``MessagePanel RichLog`` CSS rule doesn't help here because
    Textual matches on ``_css_type_name`` ("CopyableRichLog"), not on the
    base-class name "RichLog".
    """

    DEFAULT_CSS = """
    CopyableRichLog {
        height: auto;
        overflow-y: hidden;
        overflow-x: hidden;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._plain_lines: list[str] = []

    def write(  # type: ignore[override]
        self,
        content: Any,
        width: "int | None" = None,
        expand: bool = True,
        shrink: bool = True,
        scroll_end: "bool | None" = None,
        animate: bool = False,
    ) -> "CopyableRichLog":
        """Override to use the full widget width regardless of layout timing.

        RichLog.write(expand=True) computes: max(scrollable_content_region.width, 0).
        When the first streaming token arrives before layout completes,
        scrollable_content_region.width is 0, collapsing text to ~1-14 chars.
        Fix: resolve the target width here and pass it explicitly, falling back
        to app.size.width when the widget region is not yet populated.
        """
        if width is None:
            region_w = self.scrollable_content_region.width
            # app.size.width is the terminal column count — always available.
            # Take the max so pre-layout writes (region_w may be any small
            # number, not just 0) still use the full terminal width.
            try:
                app_w = self.app.size.width
            except Exception:
                app_w = 0
            width = max(region_w, app_w) or None
        return super().write(  # type: ignore[return-value]
            content,
            width=width,
            expand=False,  # width already resolved above
            shrink=False,  # don't shrink the explicit width
            scroll_end=scroll_end,
            animate=animate,
        )

    def write_with_source(self, styled: Text, plain: str, **kwargs: Any) -> "CopyableRichLog":
        """Write styled text to display, store plain text for copy."""
        self._plain_lines.append(plain)
        try:
            from hermes_cli.tui.osc8 import inject_osc8, _osc8_supported
            if _osc8_supported():
                import io as _io
                from rich.console import Console as _Console
                buf = _io.StringIO()
                _Console(file=buf, force_terminal=True, width=10000, highlight=False).print(styled, end="")
                ansi_str = buf.getvalue().rstrip("\n")
                return self.write(Text.from_ansi(inject_osc8(ansi_str, _enabled=True)), **kwargs)
        except Exception:
            pass
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


class CopyableBlock(Widget):
    """Wraps CopyableRichLog with a hover-reveal copy button."""

    DEFAULT_CSS = "CopyableBlock { height: auto; }"

    def __init__(self, _log_id: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        log_kwargs: dict[str, Any] = {"markup": False, "highlight": False, "wrap": True}
        if _log_id:
            log_kwargs["id"] = _log_id
        self._log = CopyableRichLog(**log_kwargs)

    def compose(self) -> ComposeResult:
        yield self._log
        # Copy button is lazy-mounted on first hover to avoid layout interference
        # with sibling RichLog deferred renders.  See on_click for implementation.

    @property
    def log(self) -> "CopyableRichLog":
        return self._log

    def on_click(self, event: Any) -> None:
        if getattr(event.widget, "id", None) == "copy-btn":
            text = self.log.copy_content()
            try:
                self.app._copy_text_with_hint(text)
            except Exception:
                pass
            event.prevent_default()

    def on_mouse_enter(self, _event: Any) -> None:
        """Lazily mount the copy button on first hover."""
        try:
            self.query_one("#copy-btn")
        except NoMatches:
            self.mount(Static("⎘", id="copy-btn"))


class CodeBlockFooter(Widget):
    """Dedicated footer row with distinct click targets for code actions."""

    DEFAULT_CSS = """
    CodeBlockFooter {
        height: 1;
        margin-top: 0;
        margin-left: 1;
        background: transparent;
        layout: horizontal;
    }
    CodeBlockFooter > Static {
        width: auto;
        color: $text-muted;
        background: transparent;
    }
    CodeBlockFooter > .sep {
        color: $text-muted;
    }
    CodeBlockFooter > .action:hover {
        color: $accent;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._copy = Static("", id="code-copy-action", classes="action")
        self._sep = Static("", classes="sep")
        self._toggle = Static("", id="code-toggle-action", classes="action")

    def compose(self) -> ComposeResult:
        yield self._copy
        yield self._sep
        yield self._toggle

    def set_actions(self, *, copy_label: str, toggle_label: str | None) -> None:
        self._copy.update(copy_label)
        if toggle_label:
            self._sep.update("  ·  ")
            self._toggle.update(toggle_label)
            self._sep.styles.display = "block"
            self._toggle.styles.display = "block"
        else:
            self._sep.update("")
            self._toggle.update("")
            self._sep.styles.display = "none"
            self._toggle.styles.display = "none"

    def on_click(self, event: Any) -> None:
        """Route clicks on footer actions to the parent StreamingCodeBlock."""
        if getattr(event, "button", 1) != 1:
            return
        parent = self.parent
        if parent is None:
            return
        target_id = getattr(getattr(event, "widget", None), "id", None)
        if target_id == "code-copy-action":
            try:
                self.app._copy_code_block(parent)  # type: ignore[attr-defined]
            except Exception:
                pass
            event.prevent_default()
            return
        if target_id == "code-toggle-action":
            try:
                if parent.can_toggle():
                    parent.toggle_collapsed()
                    event.prevent_default()
            except Exception:
                pass


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
            rl = msg.current_prose_log()
            msg.show_response_rule()
            for committed in lines[:-1]:
                engine = getattr(msg, "_response_engine", None)
                if engine is not None:
                    engine.process_line(committed)  # engine routes to prose log or code block
                else:
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
    """Owns all assistant-turn content blocks for one message."""

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

    def __init__(self, user_text: str = "", show_header: bool = True, **kwargs: Any) -> None:
        import datetime as _dt
        MessagePanel._msg_counter += 1
        self._msg_id = MessagePanel._msg_counter
        self._show_header = show_header
        self._created_at = _dt.datetime.now()
        self._response_rule = TitledRule(
            id=f"response-rule-{self._msg_id}",
            created_at=self._created_at,
        )
        self._response_block = CopyableBlock(
            id=f"response-block-{self._msg_id}",
            _log_id=f"response-{self._msg_id}",
        )
        self._prose_blocks: list[CopyableBlock] = [self._response_block]
        self._thinking_blocks: list[ReasoningPanel] = []
        self._active_thinking_block: ReasoningPanel | None = None
        self._active_prose_block: CopyableBlock = self._response_block
        self._user_text: str = user_text
        self._response_engine: "Any | None" = None   # ResponseFlowEngine, set in on_mount
        super().__init__(**kwargs)

    def _finish_fade(self) -> None:
        """Stub kept for API compatibility — fade handled by CSS transition on --entering class."""

    def compose(self) -> ComposeResult:
        yield self._response_rule
        yield self._response_block

    def show_response_rule(self) -> None:
        """Show the response title rule (called when first content arrives)."""
        if not self._show_header:
            return
        self._response_rule.add_class("visible")

    def set_response_metrics(
        self,
        *,
        tok_s: float | None = None,
        elapsed_s: float | None = None,
        streaming: bool = False,
    ) -> None:
        """Update right-side response metrics on this turn's header."""
        self._response_rule.set_response_metrics(
            tok_s=tok_s,
            elapsed_s=elapsed_s,
            streaming=streaming,
        )

    @property
    def reasoning(self) -> ReasoningPanel:
        if self._active_thinking_block is not None:
            return self._active_thinking_block
        if self._thinking_blocks:
            return self._thinking_blocks[-1]
        rp = ReasoningPanel(id=f"reasoning-{self._msg_id}-1")
        self._thinking_blocks.append(rp)
        self._mount_nonprose_block(rp)
        return rp

    def on_mount(self) -> None:
        """Lazy engine init — panel.app is guaranteed available at mount time."""
        for block in self._thinking_blocks:
            if block.parent is None:
                self._mount_nonprose_block(block)
        from hermes_cli.tui.response_flow import MARKDOWN_ENABLED, ResponseFlowEngine
        self._response_engine = (
            ResponseFlowEngine(panel=self) if MARKDOWN_ENABLED else None
        )

    @property
    def response_log(self) -> CopyableRichLog:
        return self._response_block.log

    def current_prose_log(self) -> CopyableRichLog:
        return self.ensure_prose_block().log

    def _has_any_prose_content(self) -> bool:
        return any(block.log._plain_lines for block in self._prose_blocks)

    def _mount_nonprose_block(self, block: Widget) -> None:
        """Mount a non-prose block in timeline order.

        Before the first prose line appears, keep the bootstrap response block
        at the end so reasoning/tool/code blocks can appear above it and prose
        can still flow into the existing response block later.
        """
        if not self.is_attached:
            return
        if (
            self._response_block.parent is self
            and self.children
            and self.children[-1] is self._response_block
            and not self._has_any_prose_content()
        ):
            self.mount(block, before=self._response_block)
        else:
            self.mount(block)

    def ensure_prose_block(self) -> CopyableBlock:
        """Return the current prose destination, creating a trailing block if needed."""
        active = self._active_prose_block
        if active is self._response_block and active.parent is None:
            return active
        if active.parent is self and self.children and self.children[-1] is active:
            return active

        new_prose = CopyableBlock(
            id=f"prose-{self._msg_id}-{len(self._prose_blocks)}",
            _log_id=f"prose-log-{self._msg_id}-{len(self._prose_blocks)}",
        )
        self.mount(new_prose)
        self._prose_blocks.append(new_prose)
        self._active_prose_block = new_prose
        return new_prose

    def open_thinking_block(self, title: str = "Reasoning") -> ReasoningPanel:
        """Open a new thinking block for this message."""
        if self._active_thinking_block is not None:
            self._active_thinking_block.close_box()
            self._active_thinking_block = None

        if (
            self._thinking_blocks
            and self._thinking_blocks[-1].parent is self
            and not self._thinking_blocks[-1].has_class("visible")
            and not self._thinking_blocks[-1]._plain_lines
            and not self._thinking_blocks[-1]._live_buf
        ):
            block = self._thinking_blocks[-1]
        else:
            block = ReasoningPanel(
                id=f"reasoning-{self._msg_id}-{len(self._thinking_blocks) + 1}"
            )
            self._thinking_blocks.append(block)
            self._mount_nonprose_block(block)
        self._active_thinking_block = block
        block.open_box(title)
        return block

    def append_thinking(self, delta: str) -> None:
        if not delta:
            return
        block = self._active_thinking_block or self.open_thinking_block("Reasoning")
        block.append_delta(delta)

    def close_thinking_block(self) -> None:
        block = self._active_thinking_block
        if block is None:
            return
        block.close_box()
        self._active_thinking_block = None

    def mount_tool_block(
        self,
        label: str,
        lines: list[str],
        plain_lines: list[str],
        tool_name: str | None = None,
        rerender_fn=None,
        header_stats=None,
    ) -> Widget | None:
        if not lines:
            return None
        from hermes_cli.tui.tool_blocks import ToolBlock as _ToolBlock
        block = _ToolBlock(
            label,
            lines,
            plain_lines,
            tool_name=tool_name,
            rerender_fn=rerender_fn,
            header_stats=header_stats,
        )
        self._mount_nonprose_block(block)
        return block

    def open_streaming_tool_block(self, label: str, tool_name: str | None = None) -> Widget:
        from hermes_cli.tui.tool_blocks import StreamingToolBlock as _STB
        block = _STB(label=label, tool_name=tool_name)
        self._mount_nonprose_block(block)
        return block

    def all_prose_text(self) -> str:
        """Plain text from all prose sections — for copy-all and history search."""
        parts = []
        for block in self._prose_blocks:
            text = block.log.copy_content()
            if text:
                parts.append(text)
        return "\n".join(parts)

    def first_response_line(self) -> str:
        """First non-empty display line from any prose section — for history search preview."""
        for block in self._prose_blocks:
            for line in block.log._plain_lines:
                if line.strip():
                    return line
        return ""


# ---------------------------------------------------------------------------
# StreamingCodeBlock — fenced code block widget (stream-then-finalize)
# ---------------------------------------------------------------------------

class StreamingCodeBlock(Widget):
    """Fenced code block widget: streams per-line Pygments highlight, then
    finalizes to full rich.Syntax on fence close.

    States
    ------
    STREAMING → COMPLETE (fence closed — call_after_refresh(_finalize_syntax))
    STREAMING → FLUSHED  (turn ended before fence closed — content preserved)
    """

    DEFAULT_CSS = """
    StreamingCodeBlock {
        height: auto;
        layout: vertical;
        margin-left: 2;
        margin-top: 1;
        margin-bottom: 1;
    }
    """

    def __init__(
        self,
        lang: str = "",
        pygments_theme: str = "monokai",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._lang = lang
        self._pygments_theme = pygments_theme
        self._state: "Literal['STREAMING', 'COMPLETE', 'FLUSHED']" = "STREAMING"
        self._code_lines: list[str] = []
        self._resolved_lang: str | None = None
        self._log = CopyableRichLog(markup=False)
        self._footer = CodeBlockFooter(classes="code-block-footer")
        self._footer.styles.display = "none"
        self._collapsed = False
        self._copy_flash = False
        self._controls_text_plain = ""

    def compose(self) -> ComposeResult:
        yield self._log
        yield self._footer

    # ------------------------------------------------------------------
    # Streaming phase
    # ------------------------------------------------------------------

    def append_line(self, line: str) -> None:
        """Called by ResponseFlowEngine for each code line during streaming."""
        plain_line = _strip_ansi(line)
        self._code_lines.append(plain_line)
        highlighted = self._highlight_line(plain_line, self._lang)
        self._log.write_with_source(Text.from_ansi(highlighted), plain_line)

    def _highlight_line(self, line: str, lang: str) -> str:
        """Per-line Pygments highlight — loses multi-line string context but
        gives correct token highlighting for 90%+ of code."""
        try:
            from pygments import highlight  # type: ignore[import-untyped]
            from pygments.lexers import TextLexer, get_lexer_by_name  # type: ignore[import-untyped]
            from pygments.formatters import TerminalTrueColorFormatter  # type: ignore[import-untyped]
            try:
                lexer = get_lexer_by_name(lang, stripall=False) if lang else TextLexer()
            except Exception:
                lexer = TextLexer()  # unknown language name → plain text
            return highlight(line, lexer, TerminalTrueColorFormatter(style=self._pygments_theme)).rstrip("\n")
        except Exception:
            return line  # safe fallback — plain text

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

    def complete(self, skin_vars: dict[str, str]) -> None:
        """Fence closed — replace per-line content with full rich.Syntax block."""
        if self._state != "STREAMING":
            return
        self._state = "COMPLETE"
        self._pygments_theme = skin_vars.get("preview-syntax-theme", self._pygments_theme)
        self.add_class("--complete")
        self.call_after_refresh(self._finalize_syntax, dict(skin_vars))

    def _finalize_syntax(self, skin_vars: dict[str, str]) -> None:
        from rich.syntax import Syntax
        from hermes_cli.tui.response_flow import _detect_lang
        code = "\n".join(self._display_code_lines())
        lang = self._resolved_lang or self._lang or _detect_lang(code)
        self._resolved_lang = lang
        self._pygments_theme = skin_vars.get("preview-syntax-theme", self._pygments_theme)
        syntax = Syntax(
            code,
            lexer=lang,
            theme=self._pygments_theme,
            line_numbers=True,
            word_wrap=False,
            indent_guides=False,
            background_color=skin_vars.get("app-bg", "#1e1e1e"),
        )
        self._log.clear()
        if not self._collapsed:
            self._log.write_with_source(syntax, code)  # type: ignore[arg-type]
        self._sync_footer()
        self.refresh(layout=True)

    # ------------------------------------------------------------------
    # Partial fence (turn ended before fence closed)
    # ------------------------------------------------------------------

    def flush(self) -> None:
        """Turn ended before fence closed. Commit as plain text; no re-render."""
        if self._state != "STREAMING":
            return
        self._state = "FLUSHED"
        self.add_class("--flushed")
        self._render_flushed_content()

    def copy_content(self) -> str:
        """Plain text of the code block for clipboard operations."""
        return "\n".join(self._display_code_lines())

    def refresh_skin(self, css_vars: dict[str, str]) -> None:
        """Refresh theme-dependent rendering without remounting the widget."""
        self._pygments_theme = css_vars.get("preview-syntax-theme", self._pygments_theme)
        if self._state == "COMPLETE":
            self._finalize_syntax(css_vars)
        elif self._state == "FLUSHED":
            self._sync_footer()

    def toggle_collapsed(self) -> None:
        """Collapse/expand code body after the block is complete/flushed."""
        if self._state == "STREAMING" or not self.can_toggle():
            return
        self._collapsed = not self._collapsed
        if self._state == "COMPLETE":
            self._finalize_syntax(self.app.get_css_variables())
        else:
            self._render_flushed_content()

    def can_toggle(self) -> bool:
        """Only completed multi-line code blocks get a collapse affordance."""
        return self._state != "STREAMING" and len(self._code_lines) > 1

    def flash_copy(self) -> None:
        """Flash copy confirmation in controls row."""
        self._copy_flash = True
        if self._state == "COMPLETE":
            self._finalize_syntax(self.app.get_css_variables())
        elif self._state == "FLUSHED":
            self._render_flushed_content()
        self.set_timer(1.5, self._end_copy_flash)

    def _end_copy_flash(self) -> None:
        self._copy_flash = False
        if self._state == "COMPLETE":
            self._finalize_syntax(self.app.get_css_variables())
        elif self._state == "FLUSHED":
            self._render_flushed_content()

    def _controls_text(self) -> Text:
        label = "✓ copied" if self._copy_flash else "⎘ copy"
        t = Text(" ")
        t.append(label, style="dim")
        if self.can_toggle():
            t.append("  ·  ", style="dim")
            t.append("expand" if self._collapsed else "collapse", style="dim")
        self._controls_text_plain = t.plain
        return t

    def _sync_footer(self) -> None:
        copy_label = "✓ copy" if self._copy_flash else "⎘ copy"
        toggle_label = "expand" if (self.can_toggle() and self._collapsed) else (
            "collapse" if self.can_toggle() else None
        )
        self._footer.set_actions(copy_label=copy_label, toggle_label=toggle_label)
        self._controls_text()
        self._footer.styles.display = "none" if self._state == "STREAMING" else "block"
        self._footer.refresh(layout=True)

    def _render_flushed_content(self) -> None:
        self._log.clear()
        if not self._collapsed:
            for line in self._display_code_lines():
                highlighted = self._highlight_line(line, self._lang)
                self._log.write_with_source(Text.from_ansi(highlighted), line)
        self._sync_footer()
        self.refresh(layout=True)

    def _display_code_lines(self) -> list[str]:
        """Normalize code lines for display/copy, stripping duplicate model-added gutters."""
        nonempty = [line for line in self._code_lines if line.strip()]
        if not nonempty:
            return list(self._code_lines)
        matches = [_PRENUMBERED_LINE_RE.match(line) for line in nonempty]
        threshold = 1 if len(nonempty) == 1 else max(2, (len(nonempty) * 3 + 4) // 5)
        if sum(1 for m in matches if m) < threshold:
            return list(self._code_lines)
        numbers = [int(m.group(1)) for m in matches if m]
        if len(numbers) >= threshold:
            expected = list(range(numbers[0], numbers[0] + len(numbers)))
            sequential_hits = sum(1 for a, b in zip(numbers, expected) if a == b)
            if sequential_hits < threshold:
                return list(self._code_lines)
        stripped_lines: list[str] = []
        for line in self._code_lines:
            m = _PRENUMBERED_LINE_RE.match(line)
            stripped_lines.append(m.group(2) if m else line)
        return stripped_lines




class ThinkingWidget(Widget):
    """Static placeholder shown while agent is thinking.

    Shown after prompt submission, before the first response token arrives.
    """

    DEFAULT_CSS = "ThinkingWidget { height: 1; display: none; }"

    _shimmer_timer: object | None = None

    def activate(self) -> None:
        """Show placeholder. Call from event loop only."""
        self.styles.display = "block"

    def deactivate(self) -> None:
        """Hide placeholder. Idempotent. Call from event loop only."""
        self.styles.display = "none"

    def render_line(self, y: int) -> Strip:
        if y != 0:
            return Strip.blank(self.size.width or 40)
        width = self.size.width or 40
        text = Text(" thinking…", style="dim", no_wrap=True, overflow="ellipsis")
        segments = [
            Segment(seg.text, seg.style or Style(), seg.control)
            for seg in text.render(self.app.console)
        ]
        strip = Strip(segments, text.cell_len).extend_cell_length(width)
        strip = Strip(
            [Segment(seg.text, seg.style or Style(), seg.control) for seg in strip],
            strip.cell_length,
        )
        return strip.crop(0, width)


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

    def watch_scroll_y(self, old_y: float, new_y: float) -> None:
        """Re-engage auto-scroll when the user scrolls back to the bottom.

        Must call ``_refresh_scroll()`` so the viewport repaints when the
        scroll position changes.  ``scroll_y`` is a reactive with
        ``repaint=False`` — without this, setting ``scroll_y`` only updates
        internal state; the display never repaints until some unrelated event
        (e.g. a keypress) happens to trigger a refresh.
        """
        if round(old_y) != round(new_y):
            self._refresh_scroll()
        # max_scroll_y can be 0 when the panel hasn't laid out yet; guard against that.
        if self.max_scroll_y > 0 and new_y >= self.max_scroll_y - 1:
            was_scrolled = self._user_scrolled_up
            self._user_scrolled_up = False
            if was_scrolled:
                # User returned to the live edge — dismiss all scroll-lock badges
                from hermes_cli.tui.tool_blocks import ToolTail as _TT
                for tail in self.query(_TT):
                    tail.dismiss()

    # Lines scrolled per mouse wheel tick.  1 is the OS default; 3 matches
    # most browser/editor defaults and reduces scroll fatigue on long outputs.
    _SCROLL_LINES: int = 3

    def is_user_scrolled_up(self) -> bool:
        """Whether the user has manually scrolled away from the live edge."""
        return self._user_scrolled_up

    def on_mouse_scroll_up(self, event: Any) -> None:
        """Scroll up 3 lines per wheel tick and suppress auto-scroll."""
        self._user_scrolled_up = True
        self.scroll_relative(y=-self._SCROLL_LINES, animate=False, immediate=True)
        event.prevent_default()

    def on_mouse_scroll_down(self, event: Any) -> None:
        """Scroll down 3 lines per wheel tick; re-engage auto-scroll at bottom."""
        self.scroll_relative(y=self._SCROLL_LINES, animate=False, immediate=True)
        event.prevent_default()
        # watch_scroll_y handles re-engaging auto-scroll when near the bottom.

    def on_scroll_up(self, _event: Any) -> None:
        """Mark that the user has scrolled up via keyboard — suppress auto-scroll."""
        self._user_scrolled_up = True

    def compose(self) -> ComposeResult:
        yield ThinkingWidget(id="thinking")
        yield LiveLineWidget(id="live-line")

    @property
    def live_line(self) -> LiveLineWidget:
        return self.query_one(LiveLineWidget)

    @property
    def current_message(self) -> MessagePanel | None:
        """Return the most recent MessagePanel, or None."""
        panels = self.query(MessagePanel)
        return panels.last() if panels else None

    def new_message(self, user_text: str = "", show_header: bool = True) -> MessagePanel:
        """Create and mount a new MessagePanel for a new turn.

        The panel gets the ``--entering`` CSS class before mounting so the
        opacity: 0 rule in hermes.tcss applies on first paint.  The class
        is removed after the first render cycle so the CSS transition
        animates opacity back to 1 (fade-in effect).
        """
        panel = MessagePanel(user_text=user_text, show_header=show_header)
        panel.add_class("--entering")
        self.mount(panel, before=self.query_one(ThinkingWidget))
        # Remove --entering after the first render so the CSS opacity transition
        # plays: opacity 0 → 1 (fade-in).  call_after_refresh fires in the next
        # event loop pass — fast enough to keep the initial "black flash" invisible
        # while not blocking layout passes for sibling widgets.
        self.call_after_refresh(lambda: panel.remove_class("--entering"))
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

        # Change 1: route partial final buffer through engine (or direct write)
        if live._buf:
            msg = self.current_message
            if msg is None:
                msg = self.new_message()
            msg.show_response_rule()
            rl = msg.current_prose_log()
            engine = getattr(msg, "_response_engine", None)
            if engine is not None:
                engine.process_line(live._buf)
            else:
                plain = _strip_ansi(live._buf)
                if isinstance(rl, CopyableRichLog):
                    rl.write_with_source(Text.from_ansi(live._buf), plain)
                else:
                    rl.write(Text.from_ansi(live._buf))
            if rl._deferred_renders:
                self.call_after_refresh(msg.refresh, layout=True)
            live._buf = ""

        # Change 2: close any open code block (re-acquire msg independently)
        msg2 = self.current_message
        if msg2 is not None:
            engine2 = getattr(msg2, "_response_engine", None)
            if engine2 is not None:
                engine2.flush()  # closes open StreamingCodeBlock if mid-fence; flushes StreamingBlockBuffer


# ---------------------------------------------------------------------------
# User echo panel
# ---------------------------------------------------------------------------

class UserMessagePanel(Widget):
    """Displays the user's submitted message framed by short fade rulers.

    Mounted into OutputPanel when the user sends a message, before the new
    MessagePanel.
    """

    DEFAULT_CSS = """
    UserMessagePanel {
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

    def _format_message(self) -> Text:
        try:
            v = self.app.get_css_variables()
            bullet_color = v.get("user-echo-bullet-color") or v.get("rule-accent-color", "#FFBF00")
        except Exception:
            bullet_color = "#FFBF00"
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
    line is rendered in dim italic text, with the gutter supplied by CSS.

    After ``close_box()`` is called, clicking anywhere on the panel toggles
    the body between expanded and collapsed states.
    """

    DEFAULT_CSS = """
    ReasoningPanel {
        display: none;
        height: auto;
        margin: 0 1;
    }
    ReasoningPanel.visible {
        display: block;
    }
    ReasoningPanel #reasoning-collapsed {
        height: 1;
        display: none;
    }
    ReasoningPanel.--closeable.--collapsed #reasoning-collapsed {
        display: block;
    }
    ReasoningPanel.--closeable:hover {
        background: $accent 5%;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        self._reasoning_log = CopyableRichLog(markup=False, highlight=False, wrap=True, id="reasoning-log")
        self._live_line = Static("", id="reasoning-live")
        self._collapsed_stub = Static("", id="reasoning-collapsed")
        super().__init__(**kwargs)
        self._live_buf = ""
        self._plain_lines: list[str] = []
        self._is_closed: bool = False
        self._body_collapsed: bool = False

    def compose(self) -> ComposeResult:
        yield self._collapsed_stub
        yield self._reasoning_log
        yield self._live_line

    def _gutter_line(self, content: str) -> Text:
        """Build a dim italic line for the reasoning log.

        The left gutter marker is rendered as a CSS ``border-left: vkey`` on
        the whole ``ReasoningPanel``, so it appears on every visual row of a
        wrapped line — not just the first row (which was the bug with the old
        text-prepended ``▌`` approach).
        """
        return Text(content, style="dim italic")

    def _update_collapsed_stub(self) -> None:
        """Rebuild the one-line collapsed summary."""
        n = len(self._plain_lines)
        try:
            k = self.app.get_css_variables().get("primary", "#5f87d7")
        except Exception:
            k = "#5f87d7"
        self._collapsed_stub.update(
            Text.from_markup(
                f"[dim]Reasoning collapsed  {n}L  [bold {k}]click to expand[/][/dim]"
            )
        )

    def _sync_collapsed_state(self) -> None:
        self._reasoning_log.styles.display = "none" if self._body_collapsed else "block"
        self.set_class(self._body_collapsed, "--collapsed")
        if self._body_collapsed:
            self._update_collapsed_stub()

    def on_click(self, event: Any | None = None) -> None:
        """Toggle body visibility after streaming completes."""
        if not self._is_closed:
            return
        if event is not None and getattr(event, "button", 1) != 1:
            return
        if event is not None:
            event.prevent_default()
        self._body_collapsed = not self._body_collapsed
        self._sync_collapsed_state()

    def open_box(self, title: str) -> None:
        """Show the reasoning panel."""
        self._live_buf = ""
        self._plain_lines.clear()
        self._is_closed = False
        self._body_collapsed = False
        self._live_line.styles.display = "none"
        self._live_line.update("")
        self.remove_class("--closeable")
        self.remove_class("--collapsed")
        self._sync_collapsed_state()
        self.add_class("visible")
        # Force a layout refresh so the RichLog receives a Resize event and
        # sets _size_known=True, enabling deferred writes to be committed.
        self.call_after_refresh(self.refresh, layout=True)

    def append_delta(self, text: str) -> None:
        """Append a reasoning text delta, streaming character-by-character.

        Buffers partial lines and commits on newlines so the RichLog
        shows complete lines while still updating in real-time.
        Each committed line gets a ``▌`` gutter prefix.
        """
        self._live_buf += text
        log = self._reasoning_log
        # Commit complete lines
        while "\n" in self._live_buf:
            line, self._live_buf = self._live_buf.split("\n", 1)
            log.write(self._gutter_line(line), expand=True)
            self._plain_lines.append(line)
        if log._deferred_renders:
            self.call_after_refresh(self.refresh, layout=True)
        if self._live_buf:
            self._live_line.update(self._gutter_line(self._live_buf))
            self._live_line.styles.display = "block"
        else:
            self._live_line.styles.display = "none"
            self._live_line.update("")
        self.refresh(layout=True)

    def close_box(self) -> None:
        """Flush remaining buffer and activate collapse affordance."""
        # Flush any partial line
        buf = self._live_buf
        if buf:
            self._reasoning_log.write(self._gutter_line(buf), expand=True)
            self._plain_lines.append(buf)
            self._live_buf = ""
        if self._reasoning_log._deferred_renders:
            self.call_after_refresh(self.refresh, layout=True)
        self._live_line.styles.display = "none"
        self._live_line.update("")
        self._is_closed = True
        # Defensive: finalization must never drop the panel from the transcript,
        # even if a concurrent class toggle/race stripped visibility earlier.
        self.add_class("visible")
        self.add_class("--closeable")
        self._sync_collapsed_state()
        # Don't remove "visible" — reasoning stays shown as part of the
        # message so it isn't lost when tool output or the next response
        # pushes new content into the same MessagePanel.


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


class TitledRule(PulseMixin, Widget):
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
    progress: reactive[float] = reactive(0.0, repaint=True)

    def __init__(
        self,
        title: str | None = None,
        fade_start: str | None = None,
        fade_end: str | None = None,
        accent: str | None = None,
        title_color: str | None = None,
        show_state: bool = False,
        created_at: "Any | None" = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.title_text = title or _skin_branding("response_label", "⚕ Hermes")
        self._fade_start = fade_start or _skin_color("rule_start", "#555555")
        self._fade_end = fade_end or _skin_color("rule_end", "#2A2A2A")
        self._accent = accent or _skin_color("banner_title", "#FFD700")
        self._title_color = title_color or _skin_color("banner_dim", "#B8860B")
        self._show_state = show_state
        self._created_at = created_at  # datetime | None — shown as HH:MM when set
        self._glyph_error: bool = False
        self._response_tok_s: float | None = None
        self._response_elapsed_s: float | None = None
        self._response_streaming: bool = False

    def on_mount(self) -> None:
        if self._show_state:
            self.watch(self.app, "agent_running", self._on_state_change)
            self.watch(self.app, "command_running", self._on_state_change)

    def _on_state_change(self, _value: object = None) -> None:
        running = (
            getattr(self.app, "agent_running", False)
            or getattr(self.app, "command_running", False)
        )
        if running and getattr(self.app, "_animations_enabled", True):
            self._pulse_start()
        else:
            self._pulse_stop()
        self.refresh()

    def set_error(self, is_error: bool) -> None:
        """Set error state — hard red glyph, no animation."""
        self._glyph_error = is_error
        if is_error:
            self._pulse_stop()
        self.refresh()

    def set_response_metrics(
        self,
        *,
        tok_s: float | None = None,
        elapsed_s: float | None = None,
        streaming: bool = False,
    ) -> None:
        """Update per-response header metrics shown left of timestamp."""
        self._response_tok_s = tok_s if tok_s and tok_s > 0 else None
        if elapsed_s is not None:
            self._response_elapsed_s = elapsed_s
        self._response_streaming = streaming
        self.refresh()

    def _response_metrics_text(self) -> str:
        if self._show_state:
            return ""
        parts: list[str] = []
        if self._response_tok_s is not None:
            parts.append(f"{self._response_tok_s:.0f} tok/s")
        elif self._response_streaming:
            parts.append("… tok/s")
        if self._response_elapsed_s is not None:
            parts.append(_format_elapsed_compact(self._response_elapsed_s))
        return " · ".join(parts)

    def _live_colors(self) -> tuple[str, str, str, str]:
        """Read rule colours from CSS variables for hot-reload support.

        Returns (fade_start, fade_end, accent, title_color). Falls back to
        the instance variables set at construction time so pre-mount renders
        (e.g. during test setup) are safe.
        """
        try:
            v = self.app.get_css_variables()
            # rule-bg-color is the foreground colour the gradient fades *to* —
            # it should match the app background so the rule "disappears" at the
            # right edge.  Fall through to app-bg if rule-bg-color is not
            # explicitly overridden in the skin.
            fade_end = v.get("rule-bg-color") or v.get("app-bg", self._fade_end)
            return (
                v.get("rule-dim-color",        self._fade_start),
                fade_end,
                v.get("rule-accent-color",     self._accent),
                v.get("rule-accent-dim-color", self._title_color),
            )
        except Exception:
            return self._fade_start, self._fade_end, self._accent, self._title_color

    def render(self) -> RenderResult:
        if self.progress >= 0.5:
            return self._render_progress_bar()
        return self._render_normal()

    def _render_normal(self) -> RenderResult:
        fade_start, fade_end, accent, title_color = self._live_colors()
        w = self.size.width
        title = self.title_text
        # Split title into accent char (first non-space) + rest
        # e.g. "⚕ Hermes" → accent="⚕", rest=" Hermes"
        parts = title.split(" ", 1)
        accent_char = parts[0] if parts else ""
        rest = (" " + parts[1]) if len(parts) > 1 else ""

        # Determine glyph color: error → hard red; running → pulse; idle → darken-3
        try:
            v = self.app.get_css_variables()
            glyph_idle = v.get("primary-darken-3", "#2d4a6e")
            glyph_active = v.get("primary", "#5f87d7")
            glyph_err = v.get("status-error-color", "#EF5350")
        except Exception:
            glyph_idle = "#2d4a6e"
            glyph_active = "#5f87d7"
            glyph_err = "#EF5350"

        if self._glyph_error:
            glyph_color = glyph_err
        elif self._pulse_t > 0:
            glyph_color = lerp_color(glyph_idle, glyph_active, self._pulse_t)
        else:
            glyph_color = glyph_idle

        # Right-side state glyph — only on instances with show_state=True,
        # only visible when the agent is running.
        state_suffix = Text()
        if self._show_state and not self._glyph_error:
            running = (
                getattr(self.app, "agent_running", False)
                or getattr(self.app, "command_running", False)
            )
            if running:
                warn_color = v.get("status-warn-color", "#FFA726")
                state_suffix = Text(" ⟳", style=warn_color)

        # Right-side timestamp — HH:MM when created_at is set (response rules only)
        ts_text = ""
        if self._created_at is not None and not self._show_state:
            try:
                ts_text = self._created_at.strftime("%H:%M")
            except Exception:
                ts_text = ""
        metrics_text = self._response_metrics_text()
        metrics_len = (len(metrics_text) + 1) if metrics_text else 0
        ts_len = (len(ts_text) + 1) if ts_text else 0  # +1 for leading space

        label_len = len(f"{title} ")
        right = max(0, w - label_len - state_suffix.cell_len - metrics_len - ts_len)
        t = Text()
        # Title: accent char with dynamic glyph color, rest in title_color
        t.append(accent_char, style=f"bold {glyph_color}")
        t.append(f"{rest} ", style=f"{title_color}")
        # Right fill: fade out (start → end), then optional timestamp + state glyph
        t.append_text(_fade_rule(right, fade_start, fade_end))
        if metrics_text:
            t.append(f" {metrics_text}", style="dim")
        if ts_text:
            t.append(f" {ts_text}", style="dim")
        t.append_text(state_suffix)
        return t

    def _render_progress_bar(self) -> RenderResult:
        fade_start, fade_end, accent, _title_color = self._live_colors()
        width = max(1, self.size.width)
        filled = int(width * self.progress)
        if self.progress >= 0.9:
            bar_color = _skin_color("error_color", "#E06C75")
        elif self.progress >= 0.75:
            bar_color = _skin_color("warning_color", "#FFA726")
        else:
            bar_color = _skin_color("caution_color", "#FFBF00")
        empty_color = fade_start  # use live-reloaded dim colour
        t = Text()
        t.append("━" * filled, style=bar_color)
        t.append("─" * (width - filled), style=empty_color)
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
        fade_start = self._fade_start
        fade_end = self._fade_end
        try:
            v = self.app.get_css_variables()
            fade_start = v.get("rule-dim-color", fade_start)
            # Same fallback chain as TitledRule: rule-bg-color → app-bg → default
            fade_end = v.get("rule-bg-color") or v.get("app-bg", fade_end)
        except Exception:
            pass
        return _fade_rule(w, fade_start, fade_end)


# ---------------------------------------------------------------------------
# Hint cache + helpers (Phase 1)
# ---------------------------------------------------------------------------

_hint_cache: dict[tuple[str, str], dict[str, str]] = {}

_SEP = "  [dim]·[/dim]  "


def _build_hints(phase: str, key_color: str) -> dict[str, str]:
    """Build {long, medium, short, minimal} hint variants for a phase+color."""
    k = key_color

    def _fmt(entries: list[tuple[str, str | None]], sep: str = _SEP) -> str:
        parts = []
        for key, desc in entries:
            if desc is not None:
                parts.append(f"[bold {k}]{key}[/] [dim]{desc}[/dim]")
            else:
                parts.append(f"[bold {k}]{key}[/]")
        return sep.join(parts)

    if phase == "idle":
        long_ = _fmt([("F1", "help"), ("^F", "search"), ("/", "cmd"), ("@", "path")])
        medium = long_
        short = _fmt([("F1", None), ("^F", None), ("/", None), ("@", None)])
        minimal = f"[bold {k}]F1[/]"
    elif phase == "typing":
        long_ = _fmt([("↵", "send"), ("Esc", "clear"), ("@", "path"), ("/", "cmd")])
        medium = long_
        short = _fmt([("↵", None), ("Esc", None), ("@", None), ("/", None)])
        minimal = f"[bold {k}]↵[/]"
    elif phase in ("stream", "file"):
        s = f"[bold {k}]^C[/] [dim]interrupt[/dim]{_SEP}[bold {k}]Esc[/] [dim]dismiss[/dim]"
        long_ = s
        medium = s
        short = f"[bold {k}]^C[/]{_SEP}[bold {k}]Esc[/]"
        minimal = f"[bold {k}]^C[/]"
    elif phase == "browse":
        long_ = _fmt([("⇥", "next"), ("c", "copy"), ("a", "expand"), ("A", "collapse"), ("Esc", "exit")])
        medium = long_
        short = _fmt([("⇥", None), ("c", None), ("a", None), ("A", None), ("Esc", None)])
        minimal = f"[bold {k}]⇥[/]"
    elif phase == "overlay":
        long_ = _fmt([("↑↓", "navigate"), ("↵", "confirm"), ("Esc", "close")])
        medium = long_
        short = _fmt([("↑↓", None), ("↵", None), ("Esc", None)])
        minimal = f"[bold {k}]↵[/]"
    elif phase == "voice":
        long_ = _fmt([("␣", "stop"), ("Esc", "cancel")])
        medium = long_
        short = _fmt([("␣", None), ("Esc", None)])
        minimal = f"[bold {k}]␣[/]"
    elif phase == "error":
        long_ = _fmt([("^Z", "undo"), ("^C", "new prompt"), ("F1", "help")])
        medium = long_
        short = _fmt([("^Z", None), ("^C", None), ("F1", None)])
        minimal = f"[bold {k}]^Z[/]"
    else:
        # Fallback: idle
        long_ = _fmt([("F1", "help"), ("^F", "search")])
        medium = long_
        short = f"[bold {k}]F1[/]"
        minimal = f"[bold {k}]F1[/]"

    return {"long": long_, "medium": medium, "short": short, "minimal": minimal}


def _hints_for(phase: str, key_color: str) -> dict[str, str]:
    """Return {long, medium, short, minimal} for this phase+color. Cached."""
    cache_key = (phase, key_color.lower())
    if cache_key not in _hint_cache:
        _hint_cache[cache_key] = _build_hints(phase, key_color)
    return _hint_cache[cache_key]


def _build_streaming_hint(key_color: str) -> "tuple[Text, list[tuple[int, int]]]":
    """
    Returns the streaming-phase hint Text and the character ranges of key
    badge names that must be excluded from shimmer.
    """
    text = Text()
    badges: list[tuple[int, int]] = []

    def badge(key: str, desc: str, sep: bool = False) -> None:
        if sep:
            text.append("  ·  ", style="dim")
        start = len(text)
        text.append(key, style=Style(color=key_color, bold=True))
        badges.append((start, len(text)))   # end is exclusive
        text.append(f" {desc}", style="dim")

    badge("^C", "interrupt")
    badge("Esc", "dismiss", sep=True)
    return text, badges


# ---------------------------------------------------------------------------
# Hint bar + spinner (Step 3)
# ---------------------------------------------------------------------------

class HintBar(Widget):
    """Single-line hint / countdown display below the overlay layer.

    ``HermesApp`` has NO ``hint_text`` reactive. ``HintBar.hint`` is the
    single source of truth. ``_tick_spinner`` writes to
    ``app.query_one(HintBar).hint`` directly.

    Always occupies exactly 1 line (no display:none toggling) to prevent
    layout reflow jitter when hints appear/disappear during streaming.

    Phase-aware: set_phase() transitions the hint bar between context-
    sensitive hint states. When hint is non-empty it always overrides phase
    display (overlay countdowns, flash messages).
    """

    DEFAULT_CSS = """
    HintBar {
        height: 1;
    }
    """

    hint: reactive[str] = reactive("")
    _shimmer_tick: reactive[int] = reactive(0, repaint=True)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._phase: str = "idle"
        self._shimmer_timer: object | None = None
        self._shimmer_base: "Text | None" = None
        self._shimmer_skip: list[tuple[int, int]] = []

    def watch_hint(self, value: str) -> None:
        # Trigger repaint — render() picks up hint directly
        self.refresh()

    def _get_key_color(self) -> str:
        """Read key badge color from CSS variables."""
        try:
            v = self.app.get_css_variables()
            return v.get("primary", "#5f87d7")
        except Exception:
            return "#5f87d7"

    def set_phase(self, phase: str) -> None:
        """Transition to a new hint phase. Manages shimmer lifecycle."""
        if phase == self._phase and self._shimmer_timer is not None:
            return  # already in this phase and shimmer is running
        # Stop any existing shimmer first
        self._shimmer_stop()
        self._phase = phase
        if phase in ("stream", "file") and getattr(self.app, "_animations_enabled", True):
            self._shimmer_start()
        else:
            self.refresh()

    def _shimmer_start(self) -> None:
        """Start the streaming/file shimmer."""
        if not getattr(self.app, "_animations_enabled", True):
            self.refresh()
            return
        key_color = self._get_key_color()
        base_text, skip = _build_streaming_hint(key_color)
        self._shimmer_base = base_text
        self._shimmer_skip = skip
        self._shimmer_tick = 0
        if self._shimmer_timer is None:
            self._shimmer_timer = self.set_interval(1 / 8, self._shimmer_step)

    def _shimmer_stop(self) -> None:
        """Stop the shimmer. Idempotent."""
        if self._shimmer_timer is not None:
            self._shimmer_timer.stop()
            self._shimmer_timer = None
        self._shimmer_base = None
        self._shimmer_skip = []
        self._shimmer_tick = 0

    def _shimmer_step(self) -> None:
        """8Hz shimmer timer callback — plain def."""
        self._shimmer_tick += 1

    def render(self) -> "RenderResult":
        # Override: flash/overlay hints take priority
        if self.hint:
            return Text.from_markup(self.hint)
        # Shimmer active: render shimmer
        if self._shimmer_base is not None and self._shimmer_timer is not None:
            return shimmer_text(
                self._shimmer_base,
                self._shimmer_tick,
                dim="#6e6e6e",
                peak="#909090",
                period=32,
                skip_ranges=self._shimmer_skip,
            )
        # Phase-based static hint
        key_color = self._get_key_color()
        hints = _hints_for(self._phase, key_color)
        w = self.content_size.width
        if w >= 118:
            variant = hints.get("long", hints["medium"])
        elif w >= 78:
            variant = hints["medium"]
        elif w >= 48:
            variant = hints["short"]
        else:
            variant = hints["minimal"]
        return Text.from_markup(variant)


# ---------------------------------------------------------------------------
# Status bar (Step 3)
# ---------------------------------------------------------------------------

_BAR_FILLED = "▰"
_BAR_EMPTY = "▱"
_BAR_WIDTH = 20


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


class StatusBar(PulseMixin, Widget):
    """Bottom status bar showing model, compaction bar, ctx usage, and state.

    Inherits PulseMixin for the running-indicator pulse animation.
    Reads directly from the App's reactives — no duplicated state.
    """

    DEFAULT_CSS = "StatusBar { height: 1; dock: bottom; }"

    # Animated tok/s backing reactive — drives smooth counter easing
    _tok_s_displayed: reactive[float] = reactive(0.0, repaint=True)

    # Built lazily in _get_idle_tips() — skin not loaded at class definition time
    _idle_tips_cache: "list[str] | None" = None

    def compose(self) -> "ComposeResult":
        yield Static("⚠ no clipboard", id="status-clipboard-warning")

    def _get_idle_tips(self) -> list[str]:
        """Build idle tips lazily with key-badge format."""
        if self._idle_tips_cache is not None:
            return self._idle_tips_cache
        try:
            k = self.app.get_css_variables().get("primary", "#5f87d7")
        except Exception:
            k = "#5f87d7"
        sep = "  ·  "
        mouse_enabled = getattr(self.app, "_mouse_enabled", True)
        tip5 = (
            f"[bold {k}]right-click[/] [dim]for options[/dim]"
            if mouse_enabled else
            f"[bold {k}]^D[/] [dim]attach image[/dim]{sep}[bold {k}]^V[/] [dim]paste[/dim]"
        )
        tips = [
            f"[bold {k}]F1[/] [dim]help[/dim]{sep}[bold {k}]^F[/] [dim]history search[/dim]",
            f"[bold {k}]^Z[/] [dim]undo last turn[/dim]{sep}[bold {k}]^G[/] [dim]retry[/dim]",
            f"[bold {k}]@[/][dim]file[/dim]{sep}[bold {k}]/[/][dim]command[/dim]{sep}[bold {k}]⇥[/] [dim]accept[/dim]",
            f"[bold {k}]^L[/] [dim]clear[/dim]{sep}[bold {k}]^K[/] [dim]new session[/dim]",
            tip5,
        ]
        self._idle_tips_cache = tips
        return tips

    def on_mount(self) -> None:
        app = self.app
        # Register all standard attributes to the generic refresh callback.
        # IMPORTANT: "agent_running" and "status_tok_s" are registered to
        # dedicated callbacks below — omit them here to avoid double-registration.
        for attr in (
            "status_model", "status_context_tokens", "status_context_max",
            "status_compaction_progress", "status_compaction_enabled",
            "command_running",
            "browse_mode", "browse_index", "_browse_total",
            "status_output_dropped",
            "status_active_file",
        ):
            self.watch(app, attr, self._on_status_change)
        # agent_running: dedicated callback to start/stop pulse + refresh
        self.watch(app, "agent_running", self._on_agent_running_change)
        # status_tok_s: dedicated callback to animate _tok_s_displayed
        self.watch(app, "status_tok_s", self._on_tok_s_change)
        # _browse_uses is a plain int (not reactive) — watch browse_mode instead,
        # which always fires before we need to re-render.
        # status_error: triggers repaint when a persistent error is set/cleared
        self.watch(app, "status_error", self._on_status_change)
        self._hint_idx: int = 0
        self._hint_phase: str = "idle"
        self.set_interval(5.0, self._rotate_hint)

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

    def _rotate_hint(self) -> None:
        """Advance idle hint text to the next entry — idle phase only."""
        # Only rotate when in idle phase (no agent/browse/error active)
        app = self.app
        is_idle = (
            not getattr(app, "agent_running", False)
            and not getattr(app, "command_running", False)
            and not getattr(app, "browse_mode", False)
            and not bool(getattr(app, "status_error", ""))
        )
        if not is_idle:
            return
        tips = self._get_idle_tips()
        self._hint_idx = (self._hint_idx + 1) % len(tips)
        self.refresh()

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
            ctx_tokens = getattr(app, "status_context_tokens", 0)
            ctx_max = getattr(app, "status_context_max", 0)
            ctx_label = (
                f"{_format_compact_tokens(ctx_tokens)}/{_format_compact_tokens(ctx_max)}"
                if ctx_max > 0 else _format_compact_tokens(ctx_tokens)
            )
            right = Text()
            right.append(ctx_label, style="dim")
            pad = max(0, width - left.cell_len - right.cell_len)
            left.append(" " * pad)
            left.append_text(right)
            return left

        _vars    = getattr(app, "get_css_variables", lambda: {})()
        model    = str(getattr(app, "status_model", ""))
        ctx_tokens = getattr(app, "status_context_tokens", 0)
        ctx_max    = getattr(app, "status_context_max", 0)
        progress = getattr(app, "status_compaction_progress", 0.0)
        enabled  = getattr(app, "status_compaction_enabled", True)
        running  = (
            getattr(app, "agent_running", False)
            or getattr(app, "command_running", False)
        )
        ctx_label = (
            f"{_format_compact_tokens(ctx_tokens)}/{_format_compact_tokens(ctx_max)}"
            if ctx_max > 0 else _format_compact_tokens(ctx_tokens)
        )

        t = Text()
        # Startup state: show "connecting…" when model is not yet loaded
        if not model:
            t.append("connecting…", style=f"dim")
        else:
            t.append(model, style="dim")

        if width < 40:
            # Minimal: model · ctx
            if ctx_label:
                t.append(" · ", style="dim")
                t.append(ctx_label, style="dim")
        elif width < 60:
            # Compact: % · ctx (no bar)
            if enabled:
                pct_int = min(int(progress * 100), 100)
                t.append(" · ", style="dim")
                t.append(f"{pct_int}%", style=StatusBar._compaction_color(progress, _vars))
            if ctx_label:
                t.append(" · ", style="dim")
                t.append(ctx_label, style="dim")
        else:
            # Full: bar % · ctx
            if enabled:
                pct_int = min(int(progress * 100), 100)
                filled  = min(int(progress * _BAR_WIDTH), _BAR_WIDTH)
                bar_str = _BAR_FILLED * filled + _BAR_EMPTY * (_BAR_WIDTH - filled)
                bar_color = StatusBar._compaction_color(progress, _vars)
                t.append("  ")
                t.append(bar_str, style=bar_color)
                t.append(" ")
                t.append(f"{pct_int}%", style=bar_color)
            if ctx_label:
                t.append(" · ", style="dim")
                t.append(ctx_label, style="dim")

        # Active-file breadcrumb — shown when agent is using a file-touching tool
        active_file = str(getattr(app, "status_active_file", ""))
        if active_file and width >= 60:
            t.append("  📄 ", style="dim")
            max_path = max(10, width // 4)
            display_path = (
                active_file if len(active_file) <= max_path
                else "…" + active_file[-(max_path - 1):]
            )
            t.append(display_path, style="dim")

        # Right-anchored state label (with optional dropped-output warning).
        # When agent is running, the ● indicator pulses between two accent shades.
        dropped = getattr(app, "status_output_dropped", False)
        _err_color = _vars.get("status-error-color", "#EF5350")
        _status_err = getattr(app, "status_error", "")

        if running:
            _run_lo = _vars.get("status-running-color", "#FFBF00")
            _run_hi = _vars.get("running-indicator-hi-color", "#FFA726")
            # Use hardcoded dim — text-muted CSS var returns non-hex like "auto 60%"
            _shimmer_dim = "#6e6e6e"
            if self._pulse_t > 0:
                pulse_color = lerp_color(_run_hi, _run_lo, self._pulse_t)
            else:
                pulse_color = _run_hi
            state_t = Text()
            state_t.append(" ● ", style=f"bold {pulse_color}")
            # Shimmer the "running" word using the existing _pulse_tick as tick source
            if getattr(app, "_animations_enabled", True):
                running_shimmer = shimmer_text(
                    "running",
                    self._pulse_tick,
                    dim=_shimmer_dim,
                    peak=_run_lo,
                    period=32,
                )
                state_t.append_text(running_shimmer)
            else:
                state_t.append("running", style=f"bold {pulse_color}")
        elif _status_err:
            state_t = Text(f" ⚠ {_status_err}", style=f"bold {_err_color}")
        else:
            tips = self._get_idle_tips()
            hint_idx = getattr(self, "_hint_idx", 0)
            hint = tips[hint_idx % len(tips)]
            state_t = Text()
            state_t.append(" ")
            state_t.append_text(Text.from_markup(hint))

        if dropped:
            state_t = Text(f" ⚠ output truncated", style=_err_color) + state_t
        pad = max(0, width - t.cell_len - state_t.cell_len)
        t.append(" " * pad)
        t.append_text(state_t)

        return t

    @staticmethod
    def _compaction_color(progress: float, css_vars: dict) -> str:
        """Lerp context-bar colour from CSS variables (no legacy skin_engine read).

        Fallbacks use lowercase hex to match lerp_color()'s output format,
        so direct returns (< 0.50, >= 0.95) and lerp returns are consistently
        cased when using the defaults.
        """
        color_normal = css_vars.get("status-context-color", "#5f87d7")
        color_warn   = css_vars.get("status-warn-color",    "#FFA726")
        color_crit   = css_vars.get("status-error-color",   "#ef5350")
        if progress >= 0.95:
            return color_crit
        if progress >= 0.80:
            t = (progress - 0.80) / 0.15
            return lerp_color(color_warn, color_crit, t)
        if progress >= 0.50:
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

class ImageBar(Widget):
    """Displays attached image filenames; hidden when empty.

    Converted from Static to Widget to support render() override and
    one-pass shimmer animation on image attach (Phase 4).
    """

    DEFAULT_CSS = """
    ImageBar {
        display: none;
        height: auto;
    }
    """

    _shimmer_tick: reactive[int] = reactive(0, repaint=True)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._shimmer_timer: object | None = None
        self._shimmer_base: "Text | None" = None
        self._shimmer_skip: list[tuple[int, int]] = []
        self._static_content: "Text" = Text()

    def _shimmer_stop(self) -> None:
        """Stop shimmer. Idempotent."""
        if self._shimmer_timer is not None:
            self._shimmer_timer.stop()
            self._shimmer_timer = None
        self._shimmer_base = None
        self._shimmer_skip = []
        self._shimmer_tick = 0

    def _shimmer_once(self, base_text: "Text", fps: int = 15, period: int = 15) -> None:
        """Run one shimmer pass then settle to static. Used on image attach."""
        if not getattr(self.app, "_animations_enabled", True):
            self._static_content = base_text
            self.refresh()
            return

        self._shimmer_base = base_text
        self._shimmer_skip = []
        self._shimmer_tick = 0
        _ticks_remaining = [period]  # mutable cell for closure

        def _step() -> None:
            if not self.is_mounted:
                return
            self._shimmer_tick += 1
            _ticks_remaining[0] -= 1
            if _ticks_remaining[0] <= 0:
                self._shimmer_stop()
                self._static_content = base_text
                self.refresh()

        if self._shimmer_timer is not None:
            self._shimmer_timer.stop()
        self._shimmer_timer = self.set_interval(1 / fps, _step)

    def render(self) -> "RenderResult":
        if self._shimmer_base is not None and self._shimmer_timer is not None:
            return shimmer_text(
                self._shimmer_base,
                self._shimmer_tick,
                dim="#6e6e6e",
                peak="#cccccc",
                period=15,
                skip_ranges=self._shimmer_skip,
            )
        return self._static_content

    def update_images(self, images: list) -> None:
        """Update the displayed image list and toggle visibility."""
        if images:
            self.display = True
            names = ", ".join(getattr(img, "name", str(img)) for img in images)
            base_text = Text(f"📎 {names}", style="dim")
            self._static_content = base_text
            self._shimmer_once(base_text)
        else:
            self.display = False
            self._shimmer_stop()
            self._static_content = Text()
            self.refresh()


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
    # Stored handle so we can stop/restart the timer for pause/resume.
    _countdown_timer: "object | None" = None
    # Pause/resume tracking (P0-B: multi-overlay stacking).
    _was_paused: bool = False
    _pause_start: float = 0.0
    # Initial total seconds — set from state.remaining in each widget's update().
    # Used to compute the ▓▒░ fill ratio.
    _countdown_total: int = 30

    def _start_countdown(self) -> None:
        """Call from on_mount(). Starts the 1-second tick timer."""
        if self._countdown_timer is not None:
            return  # already running
        self._countdown_timer = self.set_interval(1.0, self._tick_countdown)

    def pause_countdown(self) -> None:
        """Pause the countdown timer (P0-B: multi-overlay stacking).

        Stops the tick without auto-resolving; call ``resume_countdown()`` to
        restart and compensate the deadline for time spent paused.
        """
        if self._countdown_timer is not None:
            self._countdown_timer.stop()
            self._countdown_timer = None
        self._was_paused = True
        self._pause_start = time.monotonic()

    def resume_countdown(self) -> None:
        """Resume a previously paused countdown.

        Extends the deadline by the time spent paused so the user is not
        penalised for an interruption they did not initiate.
        """
        if not self._was_paused:
            return
        state: "OverlayState | None" = getattr(
            getattr(self, "app", None), self._state_attr, None
        )
        if state is not None:
            elapsed_paused = time.monotonic() - self._pause_start
            state.deadline += elapsed_paused
        self._was_paused = False
        self._start_countdown()

    def _build_countdown_strip(self, remaining: int, total: int, width: int) -> "Text":
        """Build a ▓▒░ progress strip for the countdown display.

        Spec §2.3: ▓ = remaining time (left, colored); ░ = elapsed (right, dim).
        Color phases: >5s → $primary; 1-5s → lerp($primary→$warning); ≤1s → $error.
        """
        # Bar color phase
        if remaining > 5:
            bar_color = "#5f87d7"  # $primary calm
        elif remaining > 1:
            t = (5.0 - remaining) / 4.0
            bar_color = lerp_color("#5f87d7", "#FFA726", t)
        else:
            bar_color = "#ef5350"  # $error critical

        label = f"{remaining:>2}s"
        label_width = len(label) + 1   # leading space + label
        bar_width = max(8, width - label_width)

        result = Text()
        ratio = min(1.0, remaining / max(1, total))
        filled_cells = int(bar_width * ratio)

        meniscus = min(3, filled_cells)
        heavy = max(0, filled_cells - meniscus)
        empty = max(0, bar_width - filled_cells)

        if heavy > 0:
            result.append("▓" * heavy, Style(color=bar_color))
        if meniscus > 0:
            result.append("▒" * meniscus, Style(color=bar_color))
        if empty > 0:
            result.append("░" * empty, Style(color="#6e6e6e"))
        result.append(f" {label}", Style(color="#6e6e6e"))
        return result

    def _tick_countdown(self) -> None:
        """Tick handler — update countdown display and auto-resolve on expiry.

        Runs ON the event loop (set_interval callback), so direct mutation is
        correct; call_from_thread would be wrong here.
        """
        state: "OverlayState | None" = getattr(self.app, self._state_attr)
        if state is None:
            return
        remaining = state.remaining
        countdown_id = f"#{self._countdown_prefix}-countdown"
        try:
            countdown_w = self.query_one(countdown_id, Static)
            # content_size.width may be 0 if not yet laid out; use 40 as fallback.
            bar_width = max(10, self.content_size.width)
            strip = self._build_countdown_strip(remaining, self._countdown_total, bar_width)
            countdown_w.update(strip)
        except (NoMatches, AttributeError):
            pass
        if state.expired:
            self._resolve_timeout(state)

    def _resolve_timeout(self, state: "OverlayState") -> None:
        """Put timeout response on queue and clear state. Runs on event loop."""
        state.response_queue.put(self._timeout_response)
        setattr(self.app, self._state_attr, None)


# ---------------------------------------------------------------------------
# Clarify widget (Step 4)
# ---------------------------------------------------------------------------

class ClarifyWidget(CountdownMixin, Widget, can_focus=True):
    """Choice overlay with countdown for clarification questions."""

    _state_attr = "clarify_state"
    _timeout_response = None
    _countdown_prefix = "clarify"

    DEFAULT_CSS = """
    ClarifyWidget {
        display: none;
        height: auto;
        border-top: hkey $primary 25%;
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
        self._countdown_total = max(1, state.remaining)
        try:
            self.query_one("#clarify-question", Static).update(
                f"[dim]?[/dim]  {state.question}"
            )
            choices_markup = "  ".join(
                f"[bold #FFD700]\\[ {c} ←\\][/bold #FFD700]" if i == state.selected
                else f"[dim]\\[ {c} \\][/dim]"
                for i, c in enumerate(state.choices)
            )
            self.query_one("#clarify-choices", Static).update("     " + choices_markup)
        except NoMatches:
            pass

    def hide(self) -> None:
        self.display = False


# ---------------------------------------------------------------------------
# Approval widget (Step 4)
# ---------------------------------------------------------------------------

class ApprovalWidget(CountdownMixin, Widget, can_focus=True):
    """Choice overlay for dangerous-command approval with 'deny' timeout."""

    _state_attr = "approval_state"
    _timeout_response = "deny"
    _countdown_prefix = "approval"

    DEFAULT_CSS = """
    ApprovalWidget {
        display: none;
        height: auto;
        border-top: hkey $warning 35%;
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
        self._countdown_total = max(1, state.remaining)
        try:
            self.query_one("#approval-question", Static).update(
                f"[dim]![/dim]  {state.question}"
            )
            choices_markup = "  ".join(
                f"[bold #FFD700]\\[ {c} ←\\][/bold #FFD700]" if i == state.selected
                else f"[dim]\\[ {c} \\][/dim]"
                for i, c in enumerate(state.choices)
            )
            self.query_one("#approval-choices", Static).update("     " + choices_markup)
        except NoMatches:
            pass

    def hide(self) -> None:
        self.display = False


# ---------------------------------------------------------------------------
# Sudo widget (Step 4)
# ---------------------------------------------------------------------------

class SudoWidget(CountdownMixin, Widget):
    """Password input overlay for sudo commands with countdown.

    Alt+P toggles masked/unmasked peek (P1-A). The `--unmasked` CSS class is
    applied when peek is active; re-masked on next keypress, click, or blur.
    """

    _state_attr = "sudo_state"
    _timeout_response = None
    _countdown_prefix = "sudo"

    DEFAULT_CSS = """
    SudoWidget {
        display: none;
        height: auto;
        border-top: hkey $warning 35%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="sudo-prompt")
        yield Input(password=True, placeholder="enter passphrase…", id="sudo-input")
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

    def on_key(self, event: Any) -> None:
        """Alt+P toggles peek (unmask) for the password input (P1-A)."""
        if event.key == "alt+p":
            try:
                inp = self.query_one("#sudo-input", Input)
                if self.has_class("--unmasked"):
                    inp.password = True
                    self.remove_class("--unmasked")
                else:
                    inp.password = False
                    self.add_class("--unmasked")
            except NoMatches:
                pass
            event.prevent_default()

    def on_blur(self, event: Any) -> None:  # type: ignore[override]
        """Re-mask on focus loss."""
        try:
            self.query_one("#sudo-input", Input).password = True
        except NoMatches:
            pass
        self.remove_class("--unmasked")

    def update(self, state: SecretOverlayState) -> None:
        """Populate and show the sudo prompt."""
        self.display = True
        self._countdown_total = max(1, state.remaining)
        try:
            self.query_one("#sudo-prompt", Static).update(
                f"[dim]#[/dim]  {state.prompt}"
            )
            inp = self.query_one("#sudo-input", Input)
            inp.password = True
            self.remove_class("--unmasked")
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
    """Captures a secret value (API key, token, etc.) with masked input.

    Alt+P toggles masked/unmasked peek (P1-A). Re-masked on blur.
    """

    _state_attr = "secret_state"
    _timeout_response = None
    _countdown_prefix = "secret"

    DEFAULT_CSS = """
    SecretWidget {
        display: none;
        height: auto;
        border-top: hkey $primary 25%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="secret-prompt")
        yield Input(password=True, placeholder="enter secret value…", id="secret-input")
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

    def on_key(self, event: Any) -> None:
        """Alt+P toggles peek (unmask) for the secret input (P1-A)."""
        if event.key == "alt+p":
            try:
                inp = self.query_one("#secret-input", Input)
                if self.has_class("--unmasked"):
                    inp.password = True
                    self.remove_class("--unmasked")
                else:
                    inp.password = False
                    self.add_class("--unmasked")
            except NoMatches:
                pass
            event.prevent_default()

    def on_blur(self, event: Any) -> None:  # type: ignore[override]
        """Re-mask on focus loss."""
        try:
            self.query_one("#secret-input", Input).password = True
        except NoMatches:
            pass
        self.remove_class("--unmasked")

    def update(self, state: SecretOverlayState) -> None:
        """Populate and show the secret prompt."""
        self.display = True
        self._countdown_total = max(1, state.remaining)
        try:
            self.query_one("#secret-prompt", Static).update(
                f"[dim]*[/dim]  {state.prompt}"
            )
            inp = self.query_one("#secret-input", Input)
            inp.password = True
            self.remove_class("--unmasked")
            inp.clear()
            inp.focus()
        except NoMatches:
            pass

    def hide(self) -> None:
        self.display = False


# ---------------------------------------------------------------------------
# UndoConfirmOverlay (SPEC-C)
# ---------------------------------------------------------------------------

class UndoConfirmOverlay(CountdownMixin, Widget):
    """Undo confirmation overlay with 10-second auto-cancel.

    Shows the user text that will be removed and waits for Y/Enter (confirm)
    or N/Escape (cancel).  CountdownMixin drives the timer tick.

    Border: all-sides ``$warning 35%`` — destructive action demands stronger
    containment signal than top-only tray modals (spec §2.4).
    """

    _state_attr = "undo_state"
    _timeout_response = "cancel"
    _countdown_prefix = "undo"

    DEFAULT_CSS = """
    UndoConfirmOverlay {
        display: none;
        height: auto;
        border: tall $warning 35%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="undo-header")
        yield Static("", id="undo-user-text")
        yield Static("", id="undo-has-checkpoint")
        yield Static("", id="undo-choices")
        yield Static("", id="undo-countdown")

    def on_mount(self) -> None:
        self._start_countdown()

    def update(self, state: UndoOverlayState) -> None:
        """Populate content from typed state and make visible."""
        self.display = True
        self._countdown_total = max(1, state.remaining)
        try:
            self.query_one("#undo-header", Static).update(
                "[dim]<[/dim]  Undo last turn?"
            )
            echo_raw = state.user_text
            echo_text = echo_raw[:80] + "…" if len(echo_raw) > 80 else echo_raw
            self.query_one("#undo-user-text", Static).update(
                "     This will remove the assistant's last response and re-queue:\n"
                f'     [dim italic]"{echo_text}"[/dim italic]'
            )
            checkpoint_text = (
                "     [dim]+ filesystem checkpoint revert[/dim]"
                if state.has_checkpoint else ""
            )
            self.query_one("#undo-has-checkpoint", Static).update(checkpoint_text)
            self.query_one("#undo-choices", Static).update(
                "     [bold]\\[y][/bold] Undo and retry    "
                "[bold]\\[n][/bold] Cancel"
            )
        except NoMatches:
            pass

    def hide(self) -> None:
        self.display = False


# ---------------------------------------------------------------------------
# History Search (SPEC-B)
# ---------------------------------------------------------------------------

@dataclass
class _TurnEntry:
    """Metadata for one indexed turn (frozen snapshot; never mutated)."""
    panel: "MessagePanel"
    index: int          # 1-based (turn 1 = first ever)
    user_text: str      # paired text from preceding UserMessagePanel
    assistant_text: str # full plain assistant prose from the panel
    search_text: str    # combined contiguous-search haystack
    display: str        # user-facing row label


@dataclass(frozen=True, slots=True)
class TurnCandidate:
    """Candidate for fuzzy_rank() carrying a _TurnEntry reference.

    Re-implements Candidate fields inline (rather than subclassing) to avoid
    the Python slots-inheritance restriction when both base and child are
    frozen+slotted dataclasses across different module scopes.
    fuzzy_rank() only reads .display and calls dataclasses.replace(), which
    works fine on this standalone frozen dataclass.
    """
    display: str
    score: int = 0
    match_spans: tuple[tuple[int, int], ...] = ()
    entry: "_TurnEntry | None" = field(default=None)


def _turn_result_label(entry: "_TurnEntry | None") -> str:
    """Build the Rich-markup label for a TurnResultItem row."""
    if not entry:
        return ""
    max_width = 76
    first = entry.display or "(no content)"
    truncated = first[:max_width] + "…" if len(first) > max_width else first
    return f"[dim]\\[turn {entry.index:>3}][/dim]  {truncated}"


class TurnResultItem(Static):
    """Single row in the history search result list."""

    DEFAULT_CSS = """
    TurnResultItem { height: 1; padding: 0 1; }
    TurnResultItem.--selected { background: $accent 20%; }
    TurnResultItem:hover { background: $accent 10%; }
    """

    def __init__(self, entry: "_TurnEntry | None", **kwargs: Any) -> None:
        self._entry = entry
        super().__init__(_turn_result_label(entry), **kwargs)

    def on_click(self, event: Any) -> None:
        """Clicking a result row jumps to the turn."""
        if event.button == 1:
            try:
                overlay = self.app.query_one(HistorySearchOverlay)
                overlay.action_jump_to(self._entry)
            except NoMatches:
                pass


class KeymapOverlay(Widget):
    """Keyboard-shortcut reference card.  Toggle with F1; dismiss with Escape, F1, or q."""

    DEFAULT_CSS = """
    KeymapOverlay {
        layer: overlay;
        display: none;
        dock: top;
        height: auto;
        max-height: 24;
        width: 1fr;
        margin: 0 1;
        padding: 1 2;
        background: $surface;
        border: tall $primary 15%;
    }
    KeymapOverlay.--visible { display: block; }
    KeymapOverlay > Static { height: auto; }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=False, priority=True),
        Binding("f1", "dismiss", "Close", show=False, priority=True),
        Binding("q", "dismiss", "Close", show=False, priority=True),
    ]

    # Full-width layout (≥80 cols).  Width-breakpoint rendering is handled in
    # render() on the inner Static; this constant is the ≥80 version.
    _CONTENT_WIDE = (
        "[bold]Hermes  Keyboard Reference[/bold]"
        "                          [dim]\\[F1][/dim] close\n"
        "─────────────────────────────────────────────────────────────\n"
        "\n"
        "[bold $text]Navigation[/bold $text]\n"
        "  Previous / next turn            [dim]\\[Alt+↑][/dim]   [dim]\\[Alt+↓][/dim]\n"
        "  Scroll to live edge             [dim]\\[End][/dim]\n"
        "  Open history search             [dim]\\[Ctrl+F][/dim]  [dim]\\[Ctrl+G][/dim]\n"
        "\n"
        "[bold $text]Input[/bold $text]\n"
        "  Submit message                  [dim]\\[Enter][/dim]\n"
        "  Accept autocomplete             [dim]\\[Tab][/dim]\n"
        "  Insert newline                  [dim]\\[Shift+Enter][/dim]\n"
        "  Previous / next history         [dim]\\[↑][/dim]  [dim]\\[↓][/dim]\n"
        "\n"
        "[bold $text]Tools[/bold $text]\n"
        "  Expand / collapse tool block    [dim]\\[click header][/dim]\n"
        "  Expand all / collapse all       [dim]\\[a][/dim]  [dim]\\[A][/dim]  (browse mode)\n"
        "  Interrupt agent                 [dim]\\[Ctrl+C][/dim]  [dim]\\[Escape][/dim]\n"
        "\n"
        "[bold $text]Panels[/bold $text]\n"
        "  Click reasoning                 Collapse / expand\n"
        "  Undo last turn                  [dim]\\[Alt+Z][/dim]\n"
        "  Toggle FPS HUD                  [dim]\\[F8][/dim]\n"
        "\n"
        "[bold $text]System[/bold $text]\n"
        "  This help                       [dim]\\[F1][/dim]\n"
        "  Quit                            [dim]\\[Ctrl+Q][/dim]\n"
    )

    _CONTENT_NARROW = (
        "[bold]Keyboard Reference[/bold]  [dim]\\[F1][/dim] close\n"
        "\n"
        "[bold $text]Navigation[/bold $text]\n"
        "  Prev/next turn\n    [dim]\\[Alt+↑][/dim]  [dim]\\[Alt+↓][/dim]\n"
        "  History search\n    [dim]\\[Ctrl+F][/dim]\n"
        "\n"
        "[bold $text]Input[/bold $text]\n"
        "  Submit\n    [dim]\\[Enter][/dim]\n"
        "  Autocomplete\n    [dim]\\[Tab][/dim]\n"
        "\n"
        "[bold $text]Tools[/bold $text]\n"
        "  Expand/collapse\n    [dim]\\[click header][/dim]\n"
        "  Interrupt\n    [dim]\\[Ctrl+C][/dim]\n"
        "\n"
        "[bold $text]System[/bold $text]\n"
        "  Help  [dim]\\[F1][/dim]    Quit  [dim]\\[Ctrl+Q][/dim]\n"
    )

    def compose(self) -> ComposeResult:
        yield Static("", id="keymap-content", markup=True)

    def on_mount(self) -> None:
        self._update_content()

    def on_resize(self) -> None:
        self._update_content()

    def _update_content(self) -> None:
        """Choose wide/narrow layout based on terminal width (P1-D)."""
        try:
            w = self.app.size.width
        except Exception:
            w = 80
        content = self._CONTENT_WIDE if w >= 80 else self._CONTENT_NARROW
        try:
            self.query_one("#keymap-content", Static).update(content)
        except NoMatches:
            pass

    def action_dismiss(self) -> None:
        self.remove_class("--visible")
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.app.query_one(HermesInput).focus()
        except (NoMatches, ImportError):
            pass


class HistorySearchOverlay(Widget):
    """Ctrl+F history search overlay.

    Shows a fuzzy-searchable list of past conversation turns. Ctrl+F opens
    it; Escape/Ctrl+F/Enter dismiss it (Enter also jumps to the selected turn).
    """

    DEFAULT_CSS = """
    HistorySearchOverlay {
        layer: overlay;
        dock: top;
        margin-top: 2;
        margin-left: 4;
        width: 90%;
        max-width: 90;
        min-width: 40;
        height: auto;
        max-height: 16;
        display: none;
        background: $surface;
        border: tall $primary 15%;
        padding: 0 1;
    }
    HistorySearchOverlay.--visible {
        display: block;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", priority=True),
        Binding("ctrl+f", "dismiss", priority=True),
        Binding("ctrl+g", "dismiss", priority=True),
        Binding("ctrl+c", "dismiss", priority=True),
        Binding("up", "move_up", priority=True),
        Binding("down", "move_down", priority=True),
        Binding("ctrl+p", "move_up", priority=True),
        Binding("ctrl+n", "move_down", priority=True),
        Binding("enter", "jump", priority=True),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._index: list[_TurnEntry] = []
        self._selected_idx: int = 0
        self._saved_hint: str = ""
        self._debounce_handle: Any = None  # Timer | None; cancelled on each new keystroke

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Search history  ↑↓ navigate · Enter jump · Esc close", id="history-search-input")
        yield VerticalScroll(id="history-result-list")
        yield Static("", id="history-status")

    def open_search(self) -> None:
        """Build frozen snapshot index, show overlay, focus search input."""
        self._build_index()
        self._selected_idx = 0
        # Save and update HintBar hint
        try:
            hint_bar = self.app.query_one(HintBar)
            self._saved_hint = hint_bar.hint
            hint_bar.hint = "↑↓ navigate  Enter jump  Esc close"
        except NoMatches:
            self._saved_hint = ""
        self._render_results("")
        self.add_class("--visible")
        try:
            self.query_one("#history-search-input", Input).focus()
        except NoMatches:
            pass

    def action_dismiss(self) -> None:
        """Hide overlay, restore hint, return focus to HermesInput."""
        # Cancel any pending debounce so _render_results() doesn't run
        # against a hidden overlay, removing and re-mounting DOM children.
        if self._debounce_handle is not None:
            self._debounce_handle.stop()
            self._debounce_handle = None
        self.remove_class("--visible")
        try:
            self.app.query_one(HintBar).hint = self._saved_hint
        except NoMatches:
            pass
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.app.query_one(HermesInput).focus()
        except (NoMatches, ImportError):
            pass

    def _build_index(self) -> None:
        """Build a frozen snapshot of current turns. DOM access — event loop only."""
        try:
            output_panel = self.app.query_one(OutputPanel)
            panels = [
                child for child in output_panel.children if isinstance(child, MessagePanel)
            ]
        except NoMatches:
            self._index = []
            return

        entries: list[_TurnEntry] = []
        chronological_panels = list(reversed(panels))
        for message_count, panel in enumerate(chronological_panels[1:], start=2):
            user_text = panel._user_text or "(no user message)"
            assistant_text = panel.all_prose_text()
            entries.append(
                _TurnEntry(
                    panel=panel,
                    index=message_count,
                    user_text=user_text,
                    assistant_text=assistant_text,
                    search_text=f"{user_text}\n\n{assistant_text}",
                    display=user_text,
                )
            )
        self._index = entries

    def on_input_changed(self, event: Input.Changed) -> None:
        """Debounce keystrokes (150ms) before re-ranking results."""
        if event.input.id != "history-search-input":
            return
        if self._debounce_handle is not None:
            self._debounce_handle.stop()
            self._debounce_handle = None
        query = event.value
        self._debounce_handle = self.set_timer(0.15, lambda: self._render_results(query))

    def _render_results(self, query: str) -> None:
        """Apply contiguous substring filtering and update the result list.

        Reuses existing TurnResultItem widgets when the result count is
        unchanged (update-in-place via Static.update()).  Only adds or removes
        widgets when the count changes, cutting DOM churn on stable queries.
        """
        self._debounce_handle = None
        # Cap at 15: overlay max-height 18 minus input + status rows = ~16 visible.
        # Rendering more than fits is wasted DOM work.
        entries = list(self._index)
        if query:
            needle = query.casefold()
            entries = [entry for entry in entries if needle in entry.search_text.casefold()]
        results = entries[:15]
        try:
            result_list = self.query_one("#history-result-list", VerticalScroll)
        except NoMatches:
            return

        existing = list(result_list.query(TurnResultItem))
        new_count = len(results)
        old_count = len(existing)

        if new_count == old_count:
            # Common case: same number of results — update in place, zero DOM add/remove.
            for widget, entry in zip(existing, results):
                widget._entry = entry
                widget.update(_turn_result_label(entry))
        elif new_count < old_count:
            # Fewer results: update kept widgets, remove the tail.
            for widget, entry in zip(existing[:new_count], results):
                widget._entry = entry
                widget.update(_turn_result_label(entry))
            for widget in existing[new_count:]:
                widget.remove()
        else:
            # More results: update existing, mount only the new additions.
            for widget, entry in zip(existing, results[:old_count]):
                widget._entry = entry
                widget.update(_turn_result_label(entry))
            new_items = [TurnResultItem(entry) for entry in results[old_count:]]
            result_list.mount(*new_items)

        self._selected_idx = max(0, min(self._selected_idx, new_count - 1))
        self.call_after_refresh(self._update_selection)

        # Status line
        total = len(self._index)
        try:
            if results or total == 0:
                status_text = (
                    f"[dim]{len(results)} of {total} turn{'s' if total != 1 else ''}[/dim]"
                )
            else:
                status_text = (
                    "[dim]no matches — try fewer words or a partial phrase[/dim]"
                )
            self.query_one("#history-status", Static).update(status_text)
        except NoMatches:
            pass

    def _update_selection(self) -> None:
        """Apply --selected CSS class to the currently highlighted row."""
        try:
            items = list(self.query(TurnResultItem))
        except Exception:
            return
        for i, item in enumerate(items):
            item.set_class(i == self._selected_idx, "--selected")

    def action_move_up(self) -> None:
        self._selected_idx = max(0, self._selected_idx - 1)
        self._update_selection()

    def action_move_down(self) -> None:
        count = len(list(self.query(TurnResultItem)))
        self._selected_idx = min(max(count - 1, 0), self._selected_idx + 1)
        self._update_selection()

    def action_jump(self) -> None:
        """Jump to the selected turn and dismiss the overlay."""
        items = list(self.query(TurnResultItem))
        if not items:
            self.action_dismiss()
            return
        idx = max(0, min(self._selected_idx, len(items) - 1))
        entry = items[idx]._entry
        self.action_dismiss()
        if entry is None:
            return
        panel = entry.panel
        panel.scroll_visible(animate=True)
        panel.add_class("--highlighted")
        panel.set_timer(0.5, lambda: panel.remove_class("--highlighted"))

    def action_jump_to(self, entry: "_TurnEntry | None") -> None:
        """Jump directly to a specific entry (used by TurnResultItem click)."""
        self.action_dismiss()
        if entry is None:
            return
        panel = entry.panel
        panel.scroll_visible(animate=True)
        panel.add_class("--highlighted")
        panel.set_timer(0.5, lambda: panel.remove_class("--highlighted"))

    def on_resize(self) -> None:
        """Re-render results to update truncation width after terminal resize."""
        if self.has_class("--visible"):
            try:
                query = self.query_one("#history-search-input", Input).value
            except NoMatches:
                query = ""
            self._render_results(query)


# ---------------------------------------------------------------------------
# FPSCounter — floating HUD for event-loop FPS + avg-ms
# ---------------------------------------------------------------------------

class FPSCounter(Widget):
    """Floating FPS / avg-ms HUD.

    Displays the event-loop timer delivery rate (target: 10 fps) and average
    milliseconds per tick.  Values come from :class:`~hermes_cli.tui.perf.FrameRateProbe`
    via two reactives that ``HermesApp._tick_fps`` sets every 0.1 s.

    Toggle with **F8** or set ``display.fps_hud: true`` in your Hermes config to start visible.

    Visual layout::

        ┌──────────────────┐  ← docked top, overlay layer (no layout reflow)
        │  10.0fps  9.8ms  │
        └──────────────────┘

    Structural CSS is in ``DEFAULT_CSS``; visual CSS is in ``hermes.tcss``.
    The widget stays ``display: none`` until the ``--visible`` class is added.
    """

    DEFAULT_CSS = """
    FPSCounter {
        layer: overlay;
        dock: top;
        width: 18;
        height: 1;
        display: none;
    }
    FPSCounter.--visible {
        display: block;
    }
    """

    fps: reactive[float] = reactive(0.0, repaint=True)
    avg_ms: reactive[float] = reactive(0.0, repaint=True)

    def render(self) -> RenderResult:
        # fps here is the event-loop timer delivery rate (target: 10 Hz).
        # Display as Hz so it's not confused with screen render FPS.
        # avg_ms is the mean interval between probe ticks (~100ms = healthy).
        t = Text()
        t.append(f"{self.fps:.1f}", style="bold")
        t.append("Hz ", style="dim")
        t.append(f"{self.avg_ms:.0f}ms", style="dim")
        return t


# ---------------------------------------------------------------------------
# TTEWidget — non-blocking Terminal Text Effects inside Textual
# ---------------------------------------------------------------------------

class TTEWidget(Widget):
    """Renders a Terminal Text Effects animation inside Textual."""

    DEFAULT_CSS = """
    TTEWidget {
        height: auto;
        min-height: 5;
        display: none;
    }
    TTEWidget.active {
        display: block;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._done_event: "threading.Event | None" = None

    def compose(self) -> ComposeResult:
        yield Static("", id="tte-frame")

    def play(
        self,
        effect_name: str,
        text: str,
        params: dict[str, object] | None = None,
        done_event: "threading.Event | None" = None,
    ) -> None:
        """Start a TTE animation. Non-blocking."""
        self.stop()
        self._done_event = done_event
        self.add_class("active")
        self._run_animation(effect_name, text, params)

    def stop(self) -> None:
        """Stop current animation and hide widget."""
        self.remove_class("active")
        try:
            frame = self.query_one("#tte-frame", Static)
            frame.update("")
        except NoMatches:
            pass
        if self._done_event is not None:
            self._done_event.set()
            self._done_event = None

    @work(thread=True, exclusive=True)
    def _run_animation(
        self,
        effect_name: str,
        text: str,
        params: dict[str, object] | None = None,
    ) -> None:
        """Background worker — generates TTE frames and pushes to UI."""
        try:
            from hermes_cli.tui.tte_runner import iter_frames

            for frame in iter_frames(effect_name, text, params=params):
                if not self.is_mounted:
                    return
                rich_text = Text.from_ansi(frame)
                self.app.call_from_thread(self._update_frame, rich_text)
                time.sleep(0.02)
        except Exception:
            pass
        finally:
            if self.is_mounted:
                self.app.call_from_thread(self.remove_class, "active")
            if self._done_event is not None:
                self._done_event.set()
                self._done_event = None

    def _update_frame(self, rich_text: Text) -> None:
        """Update frame widget on event loop."""
        try:
            frame = self.query_one("#tte-frame", Static)
            frame.update(rich_text)
        except NoMatches:
            pass
