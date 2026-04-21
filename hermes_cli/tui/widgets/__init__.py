"""Textual widgets for the Hermes TUI.

All widgets follow these conventions (from the migration spec):
- Widget.render() returns Text objects, never plain str (plain str = literal, no markup)
- RichLog.write() has no markup kwarg — set markup= at construction
- query_one() raises NoMatches — use _safe_widget_call during teardown
- self.size.width is 0 during compose() — don't use for layout math
- set_interval callbacks must be def, not async def (unless they contain await)
- Reactive mutable defaults use factory form: reactive(list) not reactive([])

This module is now a re-export shim: the actual implementations live in:
  - widget_utils.py   — pure utility functions
  - renderers.py      — CopyableRichLog, CopyableBlock, CodeBlockFooter,
                        LiveLineWidget, StreamingCodeBlock, _fade_rule,
                        TitledRule, PlainRule
  - message_panel.py  — MessagePanel, ThinkingWidget, _EchoBullet,
                        UserMessagePanel, ReasoningPanel
  - status_bar.py     — HintBar, StatusBar, AnimatedCounter,
                        VoiceStatusBar, ImageBar (+ hint helpers)
  - overlays.py       — CountdownMixin, ClarifyWidget, ApprovalWidget,
                        SudoWidget, SecretWidget, UndoConfirmOverlay,
                        TurnCandidate, TurnResultItem, KeymapOverlay,
                        HistorySearchOverlay (+ search helpers)

Remaining classes defined here: OutputPanel, FPSCounter, TTEWidget,
StartupBannerWidget.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual import work
from textual.app import ComposeResult, RenderResult
from textual.containers import ScrollableContainer
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

# ---------------------------------------------------------------------------
# Re-exports from sub-modules (backward-compat shim)
# ---------------------------------------------------------------------------

from .utils import (  # noqa: F401
    _ANSI_RE,
    _ANSI_SEQ_RE,
    _PRENUMBERED_LINE_RE,
    _animate_counters_enabled,
    _apply_span_style,
    _boost_layout_caches,
    _cursor_blink_enabled,
    _format_compact_tokens,
    _format_elapsed_compact,
    _fps_hud_enabled,
    _prewrap_code_line,
    _pulse_enabled,
    _safe_widget_call,
    _skin_branding,
    _skin_color,
    _strip_ansi,
    _typewriter_burst_threshold,
    _typewriter_cursor_enabled,
    _typewriter_delay_s,
    _typewriter_enabled,
)

from .renderers import (  # noqa: F401
    CodeBlockFooter,
    CopyableBlock,
    CopyableRichLog,
    LiveLineWidget,
    PlainRule,
    StreamingCodeBlock,
    TitledRule,
    _fade_rule,
)

from .message_panel import (  # noqa: F401
    MessagePanel,
    ReasoningPanel,
    ThinkingWidget,
    UserMessagePanel,
    _EchoBullet,
)

from .status_bar import (  # noqa: F401
    AnimatedCounter,
    HintBar,
    ImageBar,
    StatusBar,
    VoiceStatusBar,
    _BAR_EMPTY,
    _BAR_FILLED,
    _BAR_WIDTH,
    _SEP,
    _build_hints,
    _build_streaming_hint,
    _hint_cache,
    _hints_for,
)

from .overlays import (  # noqa: F401
    ApprovalWidget,
    ClarifyWidget,
    CountdownMixin,
    HistorySearchOverlay,
    KeymapOverlay,
    SecretWidget,
    SudoWidget,
    TurnCandidate,
    TurnResultItem,
    UndoConfirmOverlay,
    _SearchResult,
    _TurnEntry,
    _build_result_label,
    _escape_markup,
    _extract_snippet,
    _highlight_spans,
    _substring_search,
    _turn_result_label,
)

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp


# ---------------------------------------------------------------------------
# OutputPanel — scrollable output container
# ---------------------------------------------------------------------------

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
        _boost_layout_caches(self, box_model_maxsize=256, arrangement_maxsize=32)
        self._user_scrolled_up: bool = False

    def watch_scroll_y(self, old_y: float, new_y: float) -> None:
        """Re-engage auto-scroll when the user scrolls back to the bottom.

        Calls ``super()`` to let the base ``Widget.watch_scroll_y`` update
        ``vertical_scrollbar.position`` (so the thumb tracks the viewport)
        *and* trigger ``_refresh_scroll()`` for the viewport repaint.
        ``scroll_y`` is a reactive with ``repaint=False`` — without
        ``_refresh_scroll()`` the display stays frozen until an unrelated
        event triggers a refresh.
        """
        super().watch_scroll_y(old_y, new_y)
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

    # Max turns to keep in OutputPanel.  When exceeded, oldest turns are evicted
    # at turn-end to prevent Textual compositor cache thrash (LRU maxsize=16
    # cannot cope with 300+ children → KeyError on reflow).
    _MAX_TURNS: int = 20
    _EVICTION_THRESHOLD: int = 25

    def evict_old_turns(self) -> None:
        """Remove MessagePanel+UserMessagePanel pairs beyond ``_EVICTION_THRESHOLD``.

        Safe to call at turn-end (idle) when no mounts are in flight.
        Uses per-child ``remove()`` — NOT ``remove_children()`` — to avoid the
        deferred-removal race with subsequent ``mount()`` calls.
        """
        # Collect removable turn-boundary children (MessagePanel / UserMessagePanel).
        # StreamingToolBlock, ReasoningPanel, etc. are *inside* MessagePanel —
        # removing the panel removes them transitively.
        turn_children: list[Widget] = []
        for child in self.children:
            if isinstance(child, (MessagePanel, UserMessagePanel)):
                turn_children.append(child)
        # Each turn produces ~2 panels (UserMessagePanel + MessagePanel).
        # Keep last _MAX_TURNS * 2 panels, evict everything older.
        max_keep = self._MAX_TURNS * 2
        if len(turn_children) <= max_keep:
            return
        to_remove = turn_children[: len(turn_children) - max_keep]
        for child in to_remove:
            try:
                child.remove()
            except Exception:
                pass  # widget may already be mid-removal from a previous call

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
        min-height: 0;
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


# ---------------------------------------------------------------------------
# StartupBannerWidget
# ---------------------------------------------------------------------------

class StartupBannerWidget(Static):
    """Lightweight inline startup banner host inside OutputPanel.

    Used for startup TTE frames so animation doesn't go through
    ``CopyableRichLog.clear()+write()`` on every frame.
    """

    DEFAULT_CSS = """
    StartupBannerWidget {
        height: auto;
        margin: 1 0 0 0;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(Text(""), **kwargs)

    def set_frame(self, rich_text: Text) -> None:
        self.update(rich_text)
