"""OutputPanel, OutputPanelScrollBadge, and ScrollState."""
from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.binding import Binding
from textual.containers import ScrollableContainer
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from ._events import OUTPUT_PANEL_WIDTH_READY

_log = logging.getLogger(__name__)

# LP-COL-1: canonical body indent constant — mirrors $body-indent in hermes.tcss.
# Every top-level OutputPanel surface (UserMessagePanel, ToolPanel BodyPane,
# ReasoningPanel, CopyableBlock) must land its first text column at this offset.
BODY_INDENT_COLUMNS: int = 2

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# ScrollState — W-11 tri-state scroll position enum
# ---------------------------------------------------------------------------


class ScrollState(StrEnum):
    """W-11: three-state scroll position enum for OutputPanel."""
    PINNED = "pinned"      # at live edge; auto-scroll active
    ANCHORED = "anchored"  # user scrolled up; pending-count badge shown
    JUMPED = "jumped"      # programmatic browse jump; jump-hint badge shown


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
        from .utils import _boost_layout_caches
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
        """W-11: writing True → ANCHORED; writing False → PINNED.

        JUMPED → PINNED is not allowed via a bool write; that transition
        must only happen via watch_scroll_y confirming the live edge.
        """
        if not v and self.scroll_state == ScrollState.JUMPED:
            return  # JUMPED→PINNED only via watch_scroll_y reaching live edge
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
            _log.exception("OutputPanel cancel_streaming: agent.interrupt() failed")

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
            self.scroll_state = ScrollState.PINNED  # live edge confirmed; direct write
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
        try:
            w = self.size.width
            if w > 0:
                # Subtract 1 for the vertical scrollbar (scrollbar-size-vertical: 1 in TCSS).
                self.app._startup_output_panel_width = max(1, w - 1)
                OUTPUT_PANEL_WIDTH_READY.set()
            # else: on_resize will set it once Textual completes initial layout
        except Exception:
            # best-effort UI update; widget may not be mounted
            pass
        # W-11: mount the scroll-state badge before the live-output duo so the
        # [LiveLineWidget, ThinkingWidget] suffix invariant is preserved.
        badge = OutputPanelScrollBadge()
        anchor = self._live_anchor()
        if anchor is not None:
            self.mount(badge, before=anchor)
        else:
            self.mount(badge)

    def on_unmount(self) -> None:
        OUTPUT_PANEL_WIDTH_READY.clear()

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

    def compose(self):
        from .startup_banner import StartupBannerWidget
        from .renderers import LiveLineWidget
        from .thinking import ThinkingWidget
        yield StartupBannerWidget(id="startup-banner")
        yield LiveLineWidget(id="live-line")
        yield ThinkingWidget(id="thinking")

    @property
    def live_line(self):
        from .renderers import LiveLineWidget
        return self.query_one(LiveLineWidget)

    @property
    def current_message(self):
        """Return the most recent MessagePanel, or None."""
        from .message_panel import MessagePanel
        panels = self.query(MessagePanel)
        return panels.last() if panels else None

    def _live_anchor(self) -> "Widget | None":
        """Return the first-present live-output member, or None if neither composed.

        Order: LiveLineWidget then ThinkingWidget. Returning the *first present*
        member means new mounts land before both, preserving the suffix invariant
        [LiveLineWidget, ThinkingWidget].
        """
        from .renderers import LiveLineWidget
        from .thinking import ThinkingWidget
        for cls in (LiveLineWidget, ThinkingWidget):
            try:
                return self.query_one(cls)
            except NoMatches:
                continue
        return None

    def new_message(self, user_text: str = "", show_header: bool = True):
        """Create and mount a new MessagePanel for a new turn.

        The panel gets the ``--entering`` CSS class before mounting so the
        opacity: 0 rule in hermes.tcss applies on first paint.  The class
        is removed after the first render cycle so the CSS transition
        animates opacity back to 1 (fade-in effect).
        """
        from hermes_cli.tui.perf import measure
        from .message_panel import MessagePanel, UserMessagePanel
        panel = MessagePanel(user_text=user_text, show_header=show_header)
        panel.add_class("--entering")
        # Bug-2 fix: mount AFTER the most recent UserMessagePanel so the user
        # echo always precedes the assistant response regardless of call_from_thread
        # scheduling order between echo_user_message and watch_agent_running(True).
        with measure("output_panel.mount_message", budget_ms=16.0):
            try:
                last_ump = self.query(UserMessagePanel).last()
                _log.debug(
                    "new_message: mounting MP after UMP (id=%s children_count=%d)",
                    getattr(last_ump, "id", None),
                    len(self.children),
                )
                self.mount(panel, after=last_ump)
            except NoMatches:
                # No UMP yet — fall back to before LiveLineWidget/ThinkingWidget.
                anchor = self._live_anchor()
                _log.debug(
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
        # plays: opacity 0 → 1 (fade-in).
        self.call_after_refresh(lambda: panel.remove_class("--entering"))
        return panel

    # Max turns to keep in OutputPanel.
    _MAX_TURNS: int = 20
    _EVICTION_THRESHOLD: int = 25

    def evict_old_turns(self) -> None:
        """Remove MessagePanel+UserMessagePanel pairs beyond ``_EVICTION_THRESHOLD``."""
        from .message_panel import MessagePanel, UserMessagePanel
        turn_children: list[Widget] = []
        for child in self.children:
            if isinstance(child, (MessagePanel, UserMessagePanel)):
                turn_children.append(child)
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
        from .thinking import ThinkingWidget
        from .renderers import CopyableRichLog
        from .utils import _strip_ansi
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
                engine._partial = ""  # prevent engine.flush() below from re-processing same partial
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

    def _iter_visible_blocks(self):
        """Yield mounted ToolPanel widgets that are currently visible (display != none)."""
        from hermes_cli.tui.tool_panel import ToolPanel
        for child in self.walk_children(ToolPanel, with_self=False):
            if getattr(child.styles, "display", "block") != "none":
                yield child

    def _compute_viewport_pressure(self) -> "tuple[float, int]":
        """Return (pressure, viewport_rows) per concept §Per-tier behavior contract.

        pressure = sum(visible_block.height) / max(1, screen.size.height)
        """
        try:
            viewport_rows = max(1, self.app.screen.size.height)
        except AttributeError:
            # screen is None before the app mounts (common in unit tests); 999
            # acts as "infinite viewport" so no pressure-induced tier change fires.
            _log.debug("_compute_viewport_pressure: screen not yet mounted, using sentinel")
            viewport_rows = 999
        rows_consumed = 0
        for block in self._iter_visible_blocks():
            rows_consumed += block.size.height if block.size else 0
        return rows_consumed / viewport_rows, viewport_rows

    def _resolve_pass(self, pressure: float, viewport_rows: int) -> None:
        """Resolve tier for every visible block given the supplied pressure snapshot.

        Constructs LayoutInputs per block (adding pressure, viewport_rows,
        is_offscreen), calls self._resolver.resolve(inputs), and applies the
        returned DensityTier to each ToolCallBlock widget.
        """
        from hermes_cli.tui.tool_panel.layout_resolver import LayoutInputs
        from hermes_cli.tui.services.tools import ToolCallState

        scroll_top = getattr(self, "scroll_y", 0)
        viewport_bottom = scroll_top + viewport_rows

        for block in self._iter_visible_blocks():
            resolver = getattr(block, "_resolver", None)
            if resolver is None:
                continue
            _vs = getattr(block, "_view_state", None) or (
                getattr(block, "_lookup_view_state", lambda: None)()
            )
            if _vs is None:
                continue
            phase = _vs.state
            _vs_kind = getattr(_vs, "kind", None)
            kind = _vs_kind.kind if _vs_kind is not None else None
            block_y = getattr(getattr(block, "region", None), "y", 0)
            block_h = block.size.height if block.size else 0
            is_offscreen = (block_y + block_h) < scroll_top or block_y > viewport_bottom
            _size = getattr(block, "size", None)
            width = _size.width if _size is not None else 0
            try:
                from hermes_cli.tui.tool_category import _CATEGORY_DEFAULTS
                threshold = _CATEGORY_DEFAULTS[block._category].default_collapsed_lines
            except Exception:  # category unavailable pre-mount; use safe default
                threshold = 20
            inputs = LayoutInputs(
                phase=phase,
                is_error=bool(getattr(_vs, "is_error_for_ui", False)),
                has_focus=block.has_focus,
                user_scrolled_up=bool(getattr(self, "_user_scrolled_up", False)),
                user_override=bool(getattr(block, "_user_collapse_override", False)),
                user_override_tier=getattr(block, "_user_override_tier", None),
                body_line_count=block._body_line_count() if hasattr(block, "_body_line_count") else 0,
                threshold=threshold,
                kind=kind,
                parent_clamp=getattr(block, "_parent_clamp_tier", None),
                width=width,
                user_collapsed=bool(getattr(block, "_user_collapse_override", False)),
                has_footer_content=bool(
                    getattr(block, "_result_summary_v4", None) is not None
                ),
                is_streaming=(phase in (ToolCallState.STARTED, ToolCallState.STREAMING)),
                pressure=pressure,
                viewport_rows=viewport_rows,
                is_offscreen=is_offscreen,
            )
            resolver.resolve(inputs)

        # TB-MED-2: resolve group tier via same pressure axis
        from hermes_cli.tui.tool_group import ToolGroup as _TG
        for group in self.query(_TG):
            if not group.display:
                continue
            grp_y = getattr(getattr(group, "region", None), "y", 0)
            grp_h = group.size.height if group.size else 0
            grp_offscreen = (grp_y + grp_h) < scroll_top or grp_y > viewport_bottom
            group._resolve_group_tier(
                pressure=pressure,
                viewport_rows=viewport_rows,
                is_offscreen=grp_offscreen,
            )

    def _resolve_layout(self) -> None:
        """Two-pass fixed-point per concept lines 375–381.

        Pass 1: compute pressure, resolve each block, observe any band crossings.
        Pass 2: recompute pressure with pass-1 tiers; re-resolve only if any
        block crossed a band boundary in pass 1. Bounded at 2 passes — concept
        rule, not a heuristic.
        """
        from hermes_cli.tui.tool_panel.layout_resolver import _pressure_band
        pressure, viewport_rows = self._compute_viewport_pressure()
        bands_pre = _pressure_band(pressure)
        self._resolve_pass(pressure, viewport_rows)
        pressure2, viewport_rows2 = self._compute_viewport_pressure()
        if _pressure_band(pressure2) == bands_pre:
            return
        self._resolve_pass(pressure2, viewport_rows2)

    def on_resize(self, event: Any) -> None:
        """Anchor scroll position on resize; Textual cascades resize to children automatically."""
        self._resolve_layout()
        # Set startup banner width on first resize (size.width is 0 at on_mount in Textual 8.x).
        if not OUTPUT_PANEL_WIDTH_READY.is_set():
            try:
                w = self.size.width
                if w > 0:
                    self.app._startup_output_panel_width = max(1, w - 1)
                    OUTPUT_PANEL_WIDTH_READY.set()
            except Exception:
                pass
        # R08/R09: scroll anchoring — preserve position after layout recalc.
        # During startup (before any messages), skip scroll_end: it would race
        # with the async banner-set and show the wrong position before the final
        # static frame is painted. scroll_end is called explicitly after the
        # banner is fully painted (TTE or static path).
        if not getattr(self, "_user_scrolled_up", False):
            from hermes_cli.tui.widgets.message_panel import MessagePanel
            if list(self.query(MessagePanel)):
                self.call_after_refresh(self.scroll_end, animate=False)
        else:
            vh = getattr(getattr(self, "virtual_size", None), "height", 0)
            sy = getattr(self, "scroll_y", 0)
            frac = (sy / vh) if vh > 0 else 0.0
            def _restore_frac(panel: "OutputPanel" = self, f: float = frac) -> None:
                new_vh = getattr(getattr(panel, "virtual_size", None), "height", 0)
                panel.scroll_y = int(f * new_vh)
            self.call_after_refresh(_restore_frac)


def _clear_thinking_reserve(tw) -> None:
    """D-4 helper: safely call clear_reserve() on a ThinkingWidget."""
    try:
        tw.clear_reserve()
    except Exception:
        # best-effort UI update; widget may not be mounted
        pass


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
            n = panel._anchored_pending_count
            return f"↓ {n} new" if n > 0 else "↓ scrolled"
        if panel.scroll_state == ScrollState.JUMPED:
            return "↑ jump · End to latest"
        return ""
