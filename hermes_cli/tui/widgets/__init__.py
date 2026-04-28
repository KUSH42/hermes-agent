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
  - overlays.py       — TurnCandidate, TurnResultItem, KeymapOverlay,
                        HistorySearchOverlay (+ search helpers)

Remaining classes defined here: OutputPanel, FPSCounter, TTEWidget,
StartupBannerWidget.
"""

from __future__ import annotations

import enum
from enum import StrEnum
import logging
import math
import random as _random
import threading as _threading
import time
from dataclasses import dataclass
from dataclasses import field as _dc_field
from typing import TYPE_CHECKING, Any

from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import ComposeResult, RenderResult
from textual.binding import Binding
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
    CopyableBlock,
    CopyableRichLog,
    LiveLineWidget,
    PlainRule,
    TitledRule,
    _CopyBtn,
    _fade_rule,
)

from .code_blocks import (  # noqa: F401
    CodeBlockFooter,
    StreamingCodeBlock,
)

from .inline_media import (  # noqa: F401
    InlineImage,
    InlineImageBar,
    InlineThumbnail,
)

from .prose import (  # noqa: F401
    InlineProseLog,
    MathBlockWidget,
)

from .message_panel import (  # noqa: F401
    MessagePanel,
    ReasoningPanel,
    UserMessagePanel,
    _EchoBullet,
)

from .thinking import ThinkingWidget  # noqa: F401


def _clear_thinking_reserve(tw: "ThinkingWidget") -> None:
    """D-4 helper: safely call clear_reserve() on a ThinkingWidget."""
    try:
        tw.clear_reserve()
    except Exception:
        # best-effort UI update; widget may not be mounted
        pass


from .status_bar import (  # noqa: F401
    AnimatedCounter,
    FlashMessage,
    HintBar,
    ImageBar,
    KindOverrideChanged,
    KindOverrideChip,
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
    HistorySearchOverlay,
    KeymapOverlay,
    TurnCandidate,
    TurnResultItem,
    _CrossSessionResult,
    _ModeBar,
    _SearchResult,
    _TurnEntry,
    _build_cross_session_label,
    _build_result_label,
    _escape_markup,
    _extract_snippet,
    _highlight_spans,
    _substring_search,
    _turn_result_label,
)

from .media import (  # noqa: F401
    InlineMediaWidget,
    SeekBar,
)

# R3 Phase B: interrupt widget classes are aliases routing to InterruptOverlay.
from hermes_cli.tui.perf import measure  # noqa: E402
from hermes_cli.tui.overlays._aliases import (  # noqa: F401,E402
    ApprovalWidget,
    ClarifyWidget,
    MergeConfirmOverlay,
    NewSessionOverlay,
    SecretWidget,
    SudoWidget,
    UndoConfirmOverlay,
)

from .status_bar import SourcesBar, _extract_domain, _truncate  # noqa: F401

from hermes_cli.stream_effects import make_stream_effect  # noqa: F401


def _stream_effect_cfg() -> dict:
    """Read stream-effect config from hermes config.yaml + active skin."""
    try:
        from hermes_cli.config import read_raw_config
        raw = read_raw_config()
    except Exception:
        # config dict read failed; use empty defaults
        raw = {}
    terminal_cfg = raw.get("terminal", {}) if isinstance(raw, dict) else {}
    se_cfg = terminal_cfg.get("stream_effect", {}) if isinstance(terminal_cfg, dict) else {}
    if isinstance(se_cfg, str):
        effect_name = se_cfg
        se_cfg = {}
    else:
        effect_name = se_cfg.get("enabled", "none") if isinstance(se_cfg, dict) else "none"
    # Skin overrides — read from display.skin path in config, then theme_manager
    skin_path = None
    try:
        display_cfg = raw.get("display", {}) if isinstance(raw, dict) else {}
        skin_path = display_cfg.get("skin") if isinstance(display_cfg, dict) else None
    except Exception:
        # widget refresh failed pre-mount; skip silently
        pass
    if not skin_path:
        try:
            from hermes_cli.tui.theme_manager import _active_skin_path
            skin_path = _active_skin_path()
        except Exception:
            # CSS variable lookup unavailable; use default value
            pass
    skin_se_cfg: dict = {}
    if skin_path:
        try:
            import yaml
            skin = yaml.safe_load(open(skin_path)) or {}  # allow-sync-io: skin init, one-shot at startup
            se_skin = skin.get("stream_effect")
            if isinstance(se_skin, str):
                effect_name = se_skin
            elif isinstance(se_skin, dict):
                effect_name = se_skin.get("enabled", effect_name)
                skin_se_cfg = {k: v for k, v in se_skin.items() if k != "enabled"}
        except Exception:
            # reactive set failed before mount; skip gracefully
            pass
    merged_se_cfg = {**se_cfg, **skin_se_cfg} if isinstance(se_cfg, dict) else skin_se_cfg
    result: dict = {
        "stream_effect": effect_name,
        "stream_effect_length": int(merged_se_cfg.get("length", 16)),
        "stream_effect_settle_frames": int(merged_se_cfg.get("settle_frames", 6)),
        "stream_effect_scramble_frames": int(merged_se_cfg.get("scramble_frames", 14)),
    }
    if "cascade_ticks" in merged_se_cfg:
        result["stream_effect_cascade_ticks"] = int(merged_se_cfg["cascade_ticks"])
    return result


if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OutputPanel — scrollable output container
# ---------------------------------------------------------------------------


class ScrollState(StrEnum):
    """W-11: three-state scroll position enum for OutputPanel."""
    PINNED = "pinned"      # at live edge; auto-scroll active
    ANCHORED = "anchored"  # user scrolled up; pending-count badge shown
    JUMPED = "jumped"      # programmatic browse jump; jump-hint badge shown


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

    # D6: panel must be focusable so its Space/Esc bindings reach it
    # when no descendant has focus.
    can_focus = True

    # W-11: tri-state scroll position reactive
    scroll_state: reactive[ScrollState] = reactive(ScrollState.PINNED)

    BINDINGS = [
        # D6: streaming-only — non-priority so a focused child (e.g.
        # CopyableRichLog) handles Space normally; Esc bubbles to the
        # panel only when no overlay/child claims it first.
        Binding("space", "pause_scroll", "pause-scroll", show=False),
        Binding("escape", "cancel_streaming", "cancel", show=False),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        _boost_layout_caches(self, box_model_maxsize=256, arrangement_maxsize=32)
        # W-11: _user_scrolled_up is now a property backed by scroll_state;
        # keep these two extra fields for anchored-badge tracking.
        self._last_scroll_origin: str | None = None
        self._anchored_pending_count: int = 0
        self._turn_raw_output: str = ""

    @property
    def _user_scrolled_up(self) -> bool:
        """W-11: True when not PINNED (ANCHORED or JUMPED)."""
        return self.scroll_state != ScrollState.PINNED

    @_user_scrolled_up.setter
    def _user_scrolled_up(self, v: bool) -> None:
        """W-11: writing True → ANCHORED; writing False → PINNED."""
        self.scroll_state = ScrollState.ANCHORED if v else ScrollState.PINNED

    # D6 actions ----------------------------------------------------
    def action_pause_scroll(self) -> None:
        """D6: toggle _user_scrolled_up while streaming.

        Idle: no-op (Space behaviour for the panel itself is undefined;
        focused children handle their own Space).
        """
        if not getattr(self.app, "status_streaming", False):
            return
        self._user_scrolled_up = not self._user_scrolled_up

    def action_cancel_streaming(self) -> None:
        """D6: route Esc to cli.agent.interrupt() during streaming."""
        if not getattr(self.app, "status_streaming", False):
            return
        try:
            cli = getattr(self.app, "cli", None)
            agent = getattr(cli, "agent", None) if cli is not None else None
            if agent is not None and hasattr(agent, "interrupt"):
                agent.interrupt()
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "OutputPanel cancel_streaming: agent.interrupt() failed"
            )

    def reset_turn_capture(self) -> None:
        """Clear the raw assistant text capture for the next turn."""
        self._turn_raw_output = ""

    def record_raw_output(self, text: str) -> None:
        """Append raw streamed assistant text for the current turn."""
        if text:
            self._turn_raw_output += text

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
                # B1: trigger any deferred auto-collapses
                from hermes_cli.tui.tool_panel import ToolPanel as _TP
                for panel in self.query(_TP):
                    if getattr(panel, "_should_auto_collapse", False):
                        panel._apply_complete_auto_collapse()
        self._update_active_file_offscreen()  # S1-B

    def _update_active_file_offscreen(self) -> None:
        """S1-B: update status_active_file_offscreen based on scroll position."""
        try:
            app = self.app
        except Exception:
            # widget absent or unmounted; return early is correct
            return
        active_file = getattr(app, "status_active_file", "")
        if not active_file:
            app.status_active_file_offscreen = False
            return
        # Conservative: if scrolled at all and a file is active, show breadcrumb
        app.status_active_file_offscreen = self.scroll_y > 0

    # Lines scrolled per mouse wheel tick.  1 is the OS default; 3 matches
    # most browser/editor defaults and reduces scroll fatigue on long outputs.
    _SCROLL_LINES: int = 3

    def is_user_scrolled_up(self) -> bool:
        """Whether the user has manually scrolled away from the live edge."""
        return self._user_scrolled_up

    def _get_scroll_lines(self) -> int:
        return getattr(getattr(self, "app", None), "_scroll_lines", self._SCROLL_LINES)

    def on_mouse_scroll_up(self, event: Any) -> None:
        """Scroll up N lines per wheel tick and suppress auto-scroll."""
        self._user_scrolled_up = True
        self.scroll_relative(y=-self._get_scroll_lines(), animate=False, immediate=True)
        event.prevent_default()

    def on_mouse_scroll_down(self, event: Any) -> None:
        """Scroll down N lines per wheel tick; re-engage auto-scroll at bottom."""
        self.scroll_relative(y=self._get_scroll_lines(), animate=False, immediate=True)
        event.prevent_default()
        # watch_scroll_y handles re-engaging auto-scroll when near the bottom.

    def on_scroll_up(self, _event: Any) -> None:
        """W-11: keyboard scroll up → ANCHORED state."""
        self._last_scroll_origin = None
        self.scroll_state = ScrollState.ANCHORED

    def on_scroll_down(self, _event: Any) -> None:
        """W-11: keyboard scroll down; JUMPED → ANCHORED (PINNED via watch_scroll_y)."""
        self._last_scroll_origin = None
        if self.scroll_state == ScrollState.JUMPED:
            self.scroll_state = ScrollState.ANCHORED

    def on_mount(self) -> None:
        # Cache width for the startup banner daemon thread.
        # Written once from the event loop; read as a Python int from the daemon thread
        # (GIL-safe on CPython for integer attribute reads).
        try:
            self.app._startup_output_panel_width = self.size.width
        except Exception:
            # best-effort UI update; widget may not be mounted
            pass
        # W-11: mount the scroll-state badge before the live-output duo so the
        # [ThinkingWidget, LiveLineWidget] suffix invariant is preserved.
        badge = OutputPanelScrollBadge()
        anchor = self._live_anchor()
        if anchor is not None:
            self.mount(badge, before=anchor)
        else:
            self.mount(badge)

    # W-9/W-11: gated scroll_end -----------------------------------------------

    def scroll_end_if_pinned(self, *, animate: bool = False) -> None:
        """W-9/W-11: call scroll_end only when pinned; increment pending count when not."""
        if not self._user_scrolled_up:
            self.app.call_after_refresh(self.scroll_end, animate=animate)
        else:
            self._anchored_pending_count += 1
            self._update_scroll_badge()

    # W-11: badge helpers -------------------------------------------------------

    def _update_scroll_badge(self) -> None:
        """Sync badge visibility and pending count display."""
        try:
            badge = self.query_one(OutputPanelScrollBadge)
        except NoMatches:
            return  # not yet mounted; expected during startup
        if self.scroll_state == ScrollState.PINNED:
            self._anchored_pending_count = 0
            badge.remove_class("--visible")
        else:
            badge.add_class("--visible")
        badge.refresh()

    def watch_scroll_state(self, new: ScrollState) -> None:
        """W-11: keep badge in sync when scroll_state changes."""
        self._update_scroll_badge()

    def compose(self) -> ComposeResult:
        # StartupBannerWidget must be first so startup TTE frames render above
        # all message content. Empty on init; startup thread fills it via
        # call_from_thread → set_frame without any runtime mount.
        yield StartupBannerWidget(id="startup-banner")
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

    def _live_anchor(self) -> "Widget | None":
        """Return the first-present live-output member, or None if neither composed.

        Order: ThinkingWidget then LiveLineWidget. Returning the *first present*
        member means new mounts land before both, preserving the suffix invariant
        [ThinkingWidget, LiveLineWidget].
        """
        for cls in (ThinkingWidget, LiveLineWidget):
            try:
                return self.query_one(cls)
            except NoMatches:
                continue
        return None

    def new_message(self, user_text: str = "", show_header: bool = True) -> MessagePanel:
        """Create and mount a new MessagePanel for a new turn.

        The panel gets the ``--entering`` CSS class before mounting so the
        opacity: 0 rule in hermes.tcss applies on first paint.  The class
        is removed after the first render cycle so the CSS transition
        animates opacity back to 1 (fade-in effect).
        """
        panel = MessagePanel(user_text=user_text, show_header=show_header)
        panel.add_class("--entering")
        # Bug-2 fix: mount AFTER the most recent UserMessagePanel so the user
        # echo always precedes the assistant response regardless of call_from_thread
        # scheduling order between echo_user_message and watch_agent_running(True).
        with measure("output_panel.mount_message", budget_ms=16.0):
            try:
                last_ump = self.query(UserMessagePanel).last()
                _LOG.debug(
                    "new_message: mounting MP after UMP (id=%s children_count=%d)",
                    getattr(last_ump, "id", None),
                    len(self.children),
                )
                self.mount(panel, after=last_ump)
            except NoMatches:
                # No UMP yet — fall back to before ThinkingWidget/LiveLineWidget.
                anchor = self._live_anchor()
                _LOG.debug(
                    "new_message: no UMP found, mounting MP before anchor=%s children_count=%d",
                    type(anchor).__name__ if anchor else "None",
                    len(self.children),
                )
                if anchor is not None:
                    self.mount(panel, before=anchor)
                elif self.children:
                    self.mount(panel, before=self.children[-1])
                else:
                    self.mount(panel)
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
            tw = self.query_one(ThinkingWidget)
            tw.deactivate()
            # D-4: clear the layout reserve row after the 150ms fade-out timer fires
            self.set_timer(0.20, lambda: _clear_thinking_reserve(tw))
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

    def on_resize(self, event: Any) -> None:
        """Anchor scroll position on resize; Textual cascades resize to children automatically."""
        # R08/R09: scroll anchoring — preserve position after layout recalc
        if not getattr(self, "_user_scrolled_up", False):
            self.call_after_refresh(self.scroll_end, animate=False)
        else:
            vh = getattr(getattr(self, "virtual_size", None), "height", 0)
            sy = getattr(self, "scroll_y", 0)
            frac = (sy / vh) if vh > 0 else 0.0
            def _restore_frac(panel: "OutputPanel" = self, f: float = frac) -> None:
                new_vh = getattr(getattr(panel, "virtual_size", None), "height", 0)
                panel.scroll_y = int(f * new_vh)
            self.call_after_refresh(_restore_frac)


# ---------------------------------------------------------------------------
# OutputPanelScrollBadge — W-11 anchored/jumped badge
# ---------------------------------------------------------------------------


class OutputPanelScrollBadge(Static):
    """W-11: shows pending-event count or jump hint when output is not pinned."""

    def render(self) -> str:
        try:
            panel = self.app.query_one(OutputPanel)
        except NoMatches:
            return ""
        if panel.scroll_state == ScrollState.ANCHORED:
            return f"↓ {panel._anchored_pending_count} new"
        if panel.scroll_state == ScrollState.JUMPED:
            return "↑ jump · End to latest"
        return ""


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

            _frame_interval = 1.0 / 60  # match tc.frame_rate set in iter_frames
            _next_t = time.monotonic()
            for frame in iter_frames(effect_name, text, params=params):
                if not self.is_mounted:
                    return
                rich_text = Text.from_ansi(frame)
                self.app.call_from_thread(self._update_frame, rich_text)
                _next_t += _frame_interval
                _sleep = _next_t - time.monotonic()
                if _sleep > 0:
                    time.sleep(_sleep)
        except Exception:
            _LOG.debug("TTEWidget animation error", exc_info=True)
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

# Set when StartupBannerWidget enters on_mount. Producer threads (the CLI TTE
# worker) wait on this before assuming query_one() will succeed.
STARTUP_BANNER_READY = _threading.Event()


class StartupBannerWidget(Static):
    """Lightweight inline startup banner host inside OutputPanel.

    Used for startup TTE frames so animation doesn't go through
    ``CopyableRichLog.clear()+write()`` on every frame.
    """

    DEFAULT_CSS = """
    StartupBannerWidget {
        height: auto;
        width: auto;
        min-width: 100%;
        overflow-x: hidden;
        margin: 1 0 0 0;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(Text(""), **kwargs)

    def on_mount(self) -> None:
        STARTUP_BANNER_READY.set()

    def on_unmount(self) -> None:
        # Clear so a hot-reload or second App instance waits correctly.
        STARTUP_BANNER_READY.clear()

    def set_frame(self, rich_text: Text) -> None:
        self.update(rich_text)


# ---------------------------------------------------------------------------
# AssistantNameplate
# ---------------------------------------------------------------------------

_NP_POOL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*"
_NP_DECRYPT_COLOR = Style.parse("bold #00ff41")
_NP_IDLE_COLOR = Style.parse("#888888")
_NP_ACTIVE_COLOR = Style.parse("bold #7b68ee")
_NP_ERROR_COLOR = Style.parse("bold red")
_NP_DIM_COLOR = Style.parse("dim #888888")


def _lerp_hex(a: str, b: str, t: float) -> str:
    """Interpolate between two #rrggbb hex colors."""
    a, b = a.lstrip("#"), b.lstrip("#")
    ra, ga, ba_ = int(a[0:2], 16), int(a[2:4], 16), int(a[4:6], 16)
    rb, gb, bb = int(b[0:2], 16), int(b[2:4], 16), int(b[4:6], 16)
    return "#{:02x}{:02x}{:02x}".format(
        int(ra + (rb - ra) * t),
        int(ga + (gb - ga) * t),
        int(ba_ + (bb - ba_) * t),
    )


@dataclass
class _NPChar:
    target: str
    current: str
    locked: bool
    lock_at: int
    style: Style


class _NPState(enum.Enum):
    STARTUP = "startup"
    IDLE = "idle"
    MORPH_TO_ACTIVE = "morph_to_active"
    ACTIVE_IDLE = "active_idle"
    GLITCH = "glitch"
    MORPH_TO_IDLE = "morph_to_idle"
    ERROR_FLASH = "error_flash"


class _NPIdleBeat(enum.Enum):
    NONE    = "none"
    PULSE   = "pulse"
    SHIMMER = "shimmer"
    DECRYPT = "decrypt"


class AssistantNameplate(Widget):
    """Animated assistant name above the input bar."""

    _MORPH_TICKS: int = 8  # ≈267 ms at 30 fps; controls active/idle morph speed only

    DEFAULT_CSS = """
    AssistantNameplate {
        height: 1;
        width: 1fr;
        padding: 0 1;
        background: transparent;
    }
    """

    def __init__(
        self,
        name: str = "Hermes",
        effects_enabled: bool = True,
        idle_effect: str = "auto",
        idle_beat_min_s: float = 30.0,
        idle_beat_max_s: float = 60.0,
        morph_speed: float = 1.0,
        glitch_enabled: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._target_name = name
        self._active_label = "● thinking"
        self._state = _NPState.STARTUP
        self._frame: list[_NPChar] = []
        self._tick = 0
        self._timer = None
        self._effects_enabled = effects_enabled
        if idle_effect == "breathe":
            idle_effect = "pulse"
        self._idle_effect_name = idle_effect
        self._cfg_idle_effect = idle_effect  # A6: alias for tests/config inspection
        self._idle_beat_min_s: float = idle_beat_min_s
        self._idle_beat_max_s: float = max(idle_beat_max_s, idle_beat_min_s + 1.0)
        self._idle_beat_timer = None
        self._idle_beat_tick: int = 0
        self._idle_beat_type: _NPIdleBeat = _NPIdleBeat.NONE
        self._beat_decrypt_frame: list[_NPChar] = []
        self._morph_speed = morph_speed
        self._glitch_enabled = glitch_enabled
        self._glitch_frame = 0
        self._error_frame = 0
        self._last_was_error = False
        self._error_color_hex: str = "#ef5350"
        self._accent_hex = "#7b68ee"
        self._linked_rule: "Any | None" = None
        self._active_dim_hex = "#3d3480"
        self._text_hex = "#cccccc"
        # C-5/C-2: derived in on_mount; fallbacks point to module constants until then
        self._active_style: Style = _NP_ACTIVE_COLOR
        self._idle_color_hex: str = "#888888"
        self._active_phase: float = 0.0
        # C-2/C-5: theme-derived colors (updated in on_mount; fallbacks match constants)
        self._active_style: Style = _NP_ACTIVE_COLOR
        self._idle_color_hex: str = "#888888"
        # morph state
        self._morph_src = ""
        self._morph_dst = ""
        self._morph_dissolve: list[int] = []  # ticks remaining per position
        self._canvas_width: int = 80
        self._last_nameplate_w: int = 0
        # minimum animation duration gate (toolcall must animate >= 5s)
        self._MIN_ANIM_S: float = 5.0
        self._anim_min_end: float = 0.0  # monotonic deadline; 0 = no gate
        self._pending_idle: bool = False

    def on_mount(self) -> None:
        try:
            css_vars = self.app.get_css_variables()
            self._accent_hex = css_vars.get("nameplate-active-color", "#7b68ee")
            self._text_hex = css_vars.get("foreground", "#cccccc")
            # dim end of pulse wave: 30% of the accent blended toward black
            self._active_dim_hex = _lerp_hex("#000000", self._accent_hex, 0.30)
            # C-5: derive active style from live accent rather than module constant
            self._active_style = Style.parse(f"bold {self._accent_hex}")
            # C-2: idle color = 25% accent tint blended toward base text color
            self._idle_color_hex: str = _lerp_hex(
                self._text_hex, self._accent_hex, 0.25
            )
            self._error_color_hex = css_vars.get("status-error-color", "#ef5350")
        except Exception:
            pass
        # C-5: active style from live accent color (not hardcoded constant)
        self._active_style = Style.parse(f"bold {self._accent_hex}")
        # C-2: idle color as 25% accent tint toward text color
        self._idle_color_hex: str = _lerp_hex(self._text_hex, self._accent_hex, 0.25)
        if not self._effects_enabled:
            return  # effects disabled — skip animation/timer setup
        if self.styles.display == "none":
            return  # hidden — skip animation setup; widget is paint-ready if display is later restored
        self._init_decrypt()
        self._timer = self.set_interval(1 / 30, self._advance)
        # A2: watch status_phase to pause/resume pulse
        try:
            self.watch(self.app, "status_phase", self._on_phase_change)
        except Exception:
            pass
        # A3-1: register error hooks (independent of _effects_enabled)
        try:
            self.app.hooks.register("on_error_set",   self._on_error_set,   owner=self, priority=100, name="nameplate_error_set")
            self.app.hooks.register("on_error_clear", self._on_error_clear, owner=self, priority=100, name="nameplate_error_clear")
        except Exception:
            # best-effort UI update; widget may not be mounted
            pass

    def on_unmount(self) -> None:
        self._stop_all_idle_timers()
        try:
            self.app.hooks.unregister_owner(self)
        except Exception:
            # best-effort UI update; widget may not be mounted
            pass

    def on_resize(self, event: Any) -> None:
        new_w = getattr(getattr(event, "size", None), "width", self._canvas_width)
        from hermes_cli.tui.resize_utils import HYSTERESIS
        if abs(new_w - self._canvas_width) > HYSTERESIS * 2:
            self._canvas_width = new_w
            self.refresh()  # C-6: repaint after canvas-width change
        self._last_nameplate_w = new_w

    # --- public API ---

    def link_to_rule(self, rule: "Any") -> None:
        """Drive *rule*.refresh() from this nameplate's animation timer."""
        self._linked_rule = rule

    def transition_to_active(self, label: str = "● thinking") -> None:
        self._active_label = label
        if self._state == _NPState.MORPH_TO_IDLE:
            self._snap_to_idle()
        self._state = _NPState.MORPH_TO_ACTIVE
        self._init_morph(self._target_name, self._active_label)
        self._set_timer_rate(30)
        self._anim_min_end = time.monotonic() + self._MIN_ANIM_S

    def transition_to_idle(self) -> None:
        if self._last_was_error:
            self._last_was_error = False
            self._state = _NPState.ERROR_FLASH
            self._error_frame = 0
            self._set_timer_rate(30)
            return
        # gate: don't end animation before minimum duration elapsed
        remaining = self._anim_min_end - time.monotonic()
        if remaining > 0:
            self._pending_idle = True
            self._set_timer_rate(30)
            return
        self._pending_idle = False
        if self._state == _NPState.MORPH_TO_ACTIVE:
            self._snap_to_active()
        self._state = _NPState.MORPH_TO_IDLE
        self._init_morph(self._active_label, self._target_name)
        self._set_timer_rate(30)

    def glitch(self) -> None:
        if self._state != _NPState.ACTIVE_IDLE or not self._glitch_enabled:
            return
        self._state = _NPState.GLITCH
        self._glitch_frame = 0
        self._set_timer_rate(30)
        self._anim_min_end = time.monotonic() + self._MIN_ANIM_S

    def set_active_label(self, label: str) -> None:
        self._active_label = label
        if self._state == _NPState.ACTIVE_IDLE:
            self._init_frame_for(label, active_style=True)

    def mark_error(self) -> None:
        self._last_was_error = True

    # --- render ---

    def render(self) -> Text:
        if not self._effects_enabled:
            return Text(self._target_name)
        if self._state == _NPState.IDLE:
            if self._idle_beat_type != _NPIdleBeat.NONE:
                return self._render_idle_beat(self._idle_beat_type, self._idle_beat_tick)
            return Text(self._target_name, style=Style.parse(self._idle_color_hex))
        if self._state == _NPState.ACTIVE_IDLE:
            return self._render_active_pulse()
        if self._state == _NPState.ERROR_FLASH:
            return Text(self._target_name, style=_NP_ERROR_COLOR)
        t = Text()
        for ch in self._frame:
            t.append(ch.current, style=ch.style)
        return t

    def _render_active_pulse(self) -> Text:
        """Traveling sine-wave shimmer in active color while agent is thinking."""
        t = Text()
        n = max(3, len(self._frame))
        offset = math.pi / n  # spans exactly π across name regardless of length
        for i, ch in enumerate(self._frame):
            wave = (math.sin(self._active_phase - i * offset) + 1.0) / 2.0
            color = _lerp_hex(self._active_dim_hex, self._accent_hex, wave)
            t.append(ch.target, style=Style.parse(f"bold {color}"))
        return t

    # --- advance ---

    def _advance(self) -> None:
        self._tick += 1
        # fire pending idle if minimum anim duration has elapsed
        if self._pending_idle and time.monotonic() >= self._anim_min_end:
            self._pending_idle = False
            if self._state == _NPState.MORPH_TO_ACTIVE:
                self._snap_to_active()
            self._state = _NPState.MORPH_TO_IDLE
            self._init_morph(self._active_label, self._target_name)
            # stay at 30fps
        if self._state == _NPState.STARTUP:
            self._tick_startup()
        elif self._state == _NPState.IDLE:
            self._tick_idle()
        elif self._state in (_NPState.MORPH_TO_ACTIVE, _NPState.MORPH_TO_IDLE):
            self._tick_morph()
        elif self._state == _NPState.ACTIVE_IDLE:
            self._tick_active_idle()
        elif self._state == _NPState.GLITCH:
            self._tick_glitch()
        elif self._state == _NPState.ERROR_FLASH:
            self._tick_error_flash()
        self.refresh()
        if self._linked_rule is not None:
            try:
                self._linked_rule.refresh()
            except Exception:
                # best-effort turn-boundary cleanup; widget may be absent
                pass

    def _tick_startup(self) -> None:
        all_locked = True
        for ch in self._frame:
            if ch.locked:
                continue
            if self._tick >= ch.lock_at:
                ch.current = ch.target
                ch.locked = True
                ch.style = Style.parse(self._idle_color_hex)
            else:
                ch.current = _random.choice(_NP_POOL)
                ch.style = _NP_DECRYPT_COLOR
                all_locked = False
        if all_locked and self._frame:
            self._state = _NPState.IDLE
            self._enter_idle_timer()

    def _tick_idle(self) -> None:
        if self._idle_beat_type == _NPIdleBeat.NONE:
            return
        self._idle_beat_tick += 1
        done = self._tick_idle_beat(self._idle_beat_type, self._idle_beat_tick)
        if done:
            self._idle_beat_type = _NPIdleBeat.NONE
            self._stop_timer()
            self._schedule_next_beat()

    def _tick_active_idle(self) -> None:
        try:
            if self.app.has_class("reduced-motion"):
                return  # static nameplate in reduced-motion mode
        except Exception:
            pass
        self._active_phase += 0.11  # ~1.9 s full cycle @ 30 fps

    def _tick_morph(self) -> None:
        dst_style = self._active_style if self._state == _NPState.MORPH_TO_ACTIVE else Style.parse(self._idle_color_hex)
        done = True
        for i, ch in enumerate(self._frame):
            if ch.locked:
                continue
            self._morph_dissolve[i] -= 1
            if self._morph_dissolve[i] <= 0:
                ch.current = ch.target
                ch.locked = True
                ch.style = dst_style
            else:
                ch.current = _random.choice(_NP_POOL)
                ch.style = _NP_DIM_COLOR
                done = False
        if done:
            if self._state == _NPState.MORPH_TO_ACTIVE:
                self._state = _NPState.ACTIVE_IDLE
                self._active_phase = 0.0
                self._set_timer_rate(30)
            else:
                self._state = _NPState.IDLE
                self._enter_idle_timer()

    def _tick_glitch(self) -> None:
        self._glitch_frame += 1
        if self._glitch_frame <= 2:
            # corrupt 1-3 random positions
            for _ in range(_random.randint(1, min(3, len(self._frame)))):
                idx = _random.randrange(len(self._frame))
                self._frame[idx].current = _random.choice(_NP_POOL)
                self._frame[idx].style = _NP_DECRYPT_COLOR
        elif self._glitch_frame == 3:
            # partial restore
            for ch in self._frame:
                ch.current = ch.target
                ch.style = self._active_style
        else:
            # fully clean; resume pulse
            for ch in self._frame:
                ch.current = ch.target
                ch.style = self._active_style
            self._active_phase = 0.0  # C-4: reset so wave restarts cleanly from glitch
            self._state = _NPState.ACTIVE_IDLE
            self._set_timer_rate(30)

    def _tick_error_flash(self) -> None:
        self._error_frame += 1
        if self._error_frame >= 3:
            # transition directly to MORPH_TO_IDLE without re-entering transition_to_idle
            self._state = _NPState.MORPH_TO_IDLE
            self._init_morph(self._active_label, self._target_name)
            # timer stays at 30fps

    # --- helpers ---

    _DECRYPT_TICKS = 150  # 5s @ 30fps — startup splash only
    _MORPH_TICKS = 8      # ~267ms @ 30fps — active/idle transitions
    _BEAT_PULSE_TICKS    = 30
    _BEAT_SHIMMER_TICKS  = 30
    _BEAT_DECRYPT_TICKS  = 30   # defined for symmetry; not used as completion gate — see NA-2c
    _BEAT_CATALOGUE      = [_NPIdleBeat.PULSE, _NPIdleBeat.SHIMMER, _NPIdleBeat.DECRYPT]

    def _init_decrypt(self) -> None:
        self._frame = []
        n = max(1, len(self._target_name))
        step = self._DECRYPT_TICKS / max(1, n - 1)
        for i, ch in enumerate(self._target_name):
            lock_at = int(round(i * step)) + _random.randint(-1, 1)
            self._frame.append(_NPChar(
                target=ch,
                current=_random.choice(_NP_POOL),
                locked=False,
                lock_at=max(1, lock_at),
                style=_NP_DECRYPT_COLOR,
            ))
        self._tick = 0

    def _init_morph(self, src: str, dst: str) -> None:
        self._morph_src = src
        self._morph_dst = dst
        length = max(len(src), len(dst))
        ticks_base = max(1, int(round(self._MORPH_TICKS * self._morph_speed)))
        self._frame = []
        self._morph_dissolve = []
        for i in range(length):
            s_ch = src[i] if i < len(src) else " "
            d_ch = dst[i] if i < len(dst) else " "
            ticks = ticks_base + _random.randint(-2, 2)
            ticks = max(1, ticks)
            self._frame.append(_NPChar(
                target=d_ch,
                current=s_ch,
                locked=(s_ch == d_ch),
                lock_at=ticks,
                style=self._active_style if self._state == _NPState.MORPH_TO_ACTIVE else Style.parse(self._idle_color_hex),
            ))
            self._morph_dissolve.append(ticks)

    def _snap_to_idle(self) -> None:
        self._init_frame_for(self._target_name, active_style=False)

    def _snap_to_active(self) -> None:
        self._init_frame_for(self._active_label, active_style=True)

    def _init_frame_for(self, text: str, *, active_style: bool = False) -> None:
        style = self._active_style if active_style else Style.parse(self._idle_color_hex)
        self._frame = [
            _NPChar(target=ch, current=ch, locked=True, lock_at=0, style=style)
            for ch in text
        ]
        self._morph_dissolve = [0] * len(self._frame)

    def _set_timer_rate(self, fps: int) -> None:
        if self._timer:
            self._timer.stop()
        self._timer = self.set_interval(1 / fps, self._advance)

    def _stop_timer(self) -> None:
        if self._timer:
            self._timer.stop()
            self._timer = None

    def _enter_idle_timer(self) -> None:
        """Enter static wait; schedule first beat one-shot."""
        self._stop_timer()
        self._idle_beat_type = _NPIdleBeat.NONE
        if not self._effects_enabled:
            return
        if self._idle_effect_name == "none":
            return
        self._schedule_next_beat()

    def _schedule_next_beat(self) -> None:
        delay = _random.uniform(self._idle_beat_min_s, self._idle_beat_max_s)
        if self._idle_beat_timer is not None:
            self._idle_beat_timer.stop()
        self._idle_beat_timer = self.set_timer(delay, self._start_idle_beat)

    def _start_idle_beat(self) -> None:
        self._idle_beat_timer = None
        self._idle_beat_tick = 0
        self._idle_beat_type = self._pick_beat_type()
        self._init_beat(self._idle_beat_type)
        self._set_timer_rate(30)

    def _stop_all_idle_timers(self) -> None:
        """Call before leaving IDLE or on unmount."""
        self._stop_timer()
        if self._idle_beat_timer is not None:
            self._idle_beat_timer.stop()
            self._idle_beat_timer = None
        self._idle_beat_type = _NPIdleBeat.NONE

    # --- idle beat catalogue ---

    def _pick_beat_type(self) -> _NPIdleBeat:
        name = self._idle_effect_name
        if name == "auto":
            return _random.choice(self._BEAT_CATALOGUE)
        mapping = {
            "pulse":   _NPIdleBeat.PULSE,
            "shimmer": _NPIdleBeat.SHIMMER,
            "decrypt": _NPIdleBeat.DECRYPT,
        }
        result = mapping.get(name)
        if result is None:
            _LOG.warning("unknown idle_effect %r; falling back to pulse", name)
            result = _NPIdleBeat.PULSE
        return result

    def _init_beat(self, beat: _NPIdleBeat) -> None:
        if beat == _NPIdleBeat.DECRYPT:
            self._beat_decrypt_frame = [
                _NPChar(target=ch, current=_random.choice(_NP_POOL),
                        locked=False, lock_at=0, style=_NP_DECRYPT_COLOR)
                for ch in self._target_name
            ]

    def _tick_idle_beat(self, beat: _NPIdleBeat, tick: int) -> bool:
        """Return True when the beat is complete."""
        if beat == _NPIdleBeat.PULSE:
            return tick >= self._BEAT_PULSE_TICKS
        if beat == _NPIdleBeat.SHIMMER:
            return tick >= self._BEAT_SHIMMER_TICKS
        if beat == _NPIdleBeat.DECRYPT:
            return self._tick_beat_decrypt(tick)
        return True

    def _tick_beat_decrypt(self, tick: int) -> bool:
        n = len(self._target_name)
        if tick < 10:
            for ch in self._beat_decrypt_frame:
                ch.current = _random.choice(_NP_POOL)
            return False
        t_rel = tick - 10
        all_locked = True
        for i, ch in enumerate(self._beat_decrypt_frame):
            if ch.locked:
                continue
            if i <= (n - 1) * t_rel / 19:
                ch.current = ch.target
                ch.style = Style.parse(self._idle_color_hex)
                ch.locked = True
            else:
                ch.current = _random.choice(_NP_POOL)
                all_locked = False
        return all_locked

    def _render_idle_beat(self, beat: _NPIdleBeat, tick: int) -> Text:
        if beat == _NPIdleBeat.PULSE:
            return self._render_beat_pulse(tick)
        if beat == _NPIdleBeat.SHIMMER:
            return self._render_beat_shimmer(tick)
        if beat == _NPIdleBeat.DECRYPT:
            t = Text()
            for ch in self._beat_decrypt_frame:
                t.append(ch.current, style=ch.style)
            return t
        return Text(self._target_name, style=Style.parse(self._idle_color_hex))

    def _render_beat_pulse(self, tick: int) -> Text:
        t = Text()
        n = max(3, len(self._target_name))
        phase = 2 * math.pi * tick / self._BEAT_PULSE_TICKS
        offset = math.pi / n
        for i, ch in enumerate(self._target_name):
            w = (math.sin(phase - i * offset) + 1.0) / 2.0
            color = _lerp_hex(self._idle_color_hex, self._accent_hex, w)
            t.append(ch, style=Style.parse(color))
        return t

    def _render_beat_shimmer(self, tick: int) -> Text:
        t = Text()
        n = max(3, len(self._target_name))
        pos = (n + 4) * tick / self._BEAT_SHIMMER_TICKS - 2
        for i, ch in enumerate(self._target_name):
            dist = abs(i - pos)
            w = max(0.0, 1.0 - dist / 1.5)
            color = _lerp_hex(self._idle_color_hex, self._accent_hex, w)
            t.append(ch, style=Style.parse(color))
        return t

    def _pause_pulse(self) -> None:
        """Stop animation timer; --active stays so the turn-in-progress color persists."""
        self._stop_timer()

    def _on_phase_change(self, phase: str) -> None:
        """A2: gate nameplate pulse on status_phase."""
        from hermes_cli.tui.agent_phase import Phase
        try:
            if phase == Phase.REASONING:
                # (re)start pulse if currently active state
                if self._state == _NPState.ACTIVE_IDLE and self._timer is None:
                    self._active_phase = 0.0
                    self._set_timer_rate(30)
            elif phase in (Phase.STREAMING, Phase.TOOL_EXEC):
                if self._state != _NPState.STARTUP:  # don't interrupt decrypt
                    self._pause_pulse()
            elif phase == Phase.IDLE:
                pass  # transition_to_idle() drives IDLE transitions
            # Phase.ERROR handled by A3 (error-prominence spec)
        except Exception:
            # best-effort status update; widget may be absent
            pass

    def _activate_idle_phase(self) -> None:
        """Resume idle animation after error cleared."""
        self._state = _NPState.IDLE
        self._enter_idle_timer()

    def _on_error_set(self, **_) -> None:
        """A3-1: switch nameplate into error state."""
        try:
            if self._state == _NPState.STARTUP:
                # Abort decrypt early so garbled chars don't freeze on screen.
                self._state = _NPState.IDLE
                self._init_frame_for(self._target_name, active_style=False)
            self._stop_timer()
            self.remove_class("--active", "--idle")
            self.add_class("--error")
            self.refresh()
        except Exception:
            _LOG.debug("nameplate _on_error_set failed", exc_info=True)

    def _on_error_clear(self, **_) -> None:
        """A3-1: restore nameplate after error is cleared."""
        try:
            self.remove_class("--error")
            self._activate_idle_phase()
        except Exception:
            _LOG.debug("nameplate _on_error_clear failed", exc_info=True)
