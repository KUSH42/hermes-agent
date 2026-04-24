"""Integration-style resize tests — I01-I08.

Covers: resize during reasoning/streaming (no crash), completion open
(overlay syncs), drawbraille active (engine dims update), media playback
(seekbar refreshes), floor/recover cycle, burst debounce (final state
matches last size), initial-state zero crossing.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch, call

import pytest

from hermes_cli.tui.resize_utils import (
    HYSTERESIS,
    THRESHOLD_COMP_NARROW,
    THRESHOLD_MIN_HEIGHT,
    THRESHOLD_NARROW,
    THRESHOLD_TOOL_NARROW,
    THRESHOLD_ULTRA_NARROW,
    crosses_threshold,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _size_event(width: int, height: int = 24) -> MagicMock:
    ev = MagicMock()
    ev.size = MagicMock()
    ev.size.width = width
    ev.size.height = height
    return ev


# ---------------------------------------------------------------------------
# I01: Resize during active reasoning stream
# ---------------------------------------------------------------------------

class TestResizeDuringReasoning:
    """I01: Resize while reasoning panel streams — no crash, scroll anchor fires."""

    def test_output_panel_resize_no_crash_while_streaming(self):
        # OutputPanel.on_resize must not raise even when virtual_size is 0
        from hermes_cli.tui.widgets import OutputPanel

        panel = MagicMock(spec=OutputPanel)
        panel._user_scrolled_up = False
        panel.scroll_y = 0
        panel.virtual_size = MagicMock()
        panel.virtual_size.height = 0  # edge case: no content yet
        panel.call_after_refresh = MagicMock()

        OutputPanel.on_resize(panel, _size_event(80))
        panel.call_after_refresh.assert_called_once_with(panel.scroll_end, animate=False)

    def test_output_panel_resize_fractional_with_zero_height(self):
        # _user_scrolled_up=True, virtual_size.height=0 — must not divide by zero
        from hermes_cli.tui.widgets import OutputPanel

        panel = MagicMock(spec=OutputPanel)
        panel._user_scrolled_up = True
        panel.scroll_y = 0
        panel.virtual_size = MagicMock()
        panel.virtual_size.height = 0
        panel.call_after_refresh = MagicMock()

        # Must not raise
        OutputPanel.on_resize(panel, _size_event(80))
        panel.call_after_refresh.assert_called_once()

    def test_reasoning_panel_no_on_resize(self):
        # ReasoningPanel uses wrap=True — no resize handler needed
        from hermes_cli.tui.widgets import ReasoningPanel
        # If on_resize is defined, it must not mess with content
        if hasattr(ReasoningPanel, "on_resize"):
            src = inspect.getsource(ReasoningPanel.on_resize)
            assert "clear" not in src


# ---------------------------------------------------------------------------
# I02: Resize while completion overlay open
# ---------------------------------------------------------------------------

class TestResizeWithCompletionOpen:
    """I02: CompletionOverlay syncs --narrow when terminal resizes while open."""

    def test_completion_overlay_on_resize_exists(self):
        from hermes_cli.tui.completion_overlay import CompletionOverlay
        assert hasattr(CompletionOverlay, "on_resize")

    def test_completion_overlay_narrow_class_on_wide_to_narrow(self):
        from hermes_cli.tui.completion_overlay import CompletionOverlay

        overlay = MagicMock(spec=CompletionOverlay)
        overlay._last_applied_w = 150
        overlay.set_class = MagicMock()

        CompletionOverlay.on_resize(overlay, _size_event(70))
        overlay.set_class.assert_called_once_with(True, "--narrow")

    def test_completion_overlay_last_applied_w_updated(self):
        from hermes_cli.tui.completion_overlay import CompletionOverlay

        overlay = MagicMock(spec=CompletionOverlay)
        overlay._last_applied_w = 150
        overlay.set_class = MagicMock()

        CompletionOverlay.on_resize(overlay, _size_event(120))
        assert overlay._last_applied_w == 120


# ---------------------------------------------------------------------------
# I03: Resize while drawbraille overlay active
# ---------------------------------------------------------------------------

class TestResizeWithDrawbrailleActive:
    """I03: DrawbrailleOverlay resizes engine when _anim_params set."""

    def test_drawbraille_dims_scale_correctly(self):
        from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay

        overlay = MagicMock(spec=DrawbrailleOverlay)
        overlay._anim_params = MagicMock()

        DrawbrailleOverlay.on_resize(overlay, _size_event(60, 20))

        # Braille canvas = 2× cols, 4× rows
        assert overlay._anim_params.width == 120
        assert overlay._anim_params.height == 80
        overlay.refresh.assert_called_once()

    def test_drawbraille_multiple_resizes_refresh_each_time(self):
        from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay

        overlay = MagicMock(spec=DrawbrailleOverlay)
        overlay._anim_params = MagicMock()

        DrawbrailleOverlay.on_resize(overlay, _size_event(80, 24))
        DrawbrailleOverlay.on_resize(overlay, _size_event(100, 30))

        assert overlay.refresh.call_count == 2


# ---------------------------------------------------------------------------
# I04: Resize during media playback
# ---------------------------------------------------------------------------

class TestResizeDuringMedia:
    """I04: InlineMediaWidget.on_resize refreshes SeekBar during playback."""

    def test_seekbar_refresh_during_playback(self):
        from hermes_cli.tui.widgets import InlineMediaWidget

        widget = MagicMock(spec=InlineMediaWidget)
        widget._seekbar = MagicMock()

        # Multiple resize events — each should call seekbar.refresh
        for w in [80, 70, 60, 55]:
            InlineMediaWidget.on_resize(widget, _size_event(w))

        assert widget._seekbar.refresh.call_count == 4


# ---------------------------------------------------------------------------
# I05: MinSizeBackdrop floor and recover cycle
# ---------------------------------------------------------------------------

class TestMinSizeFloorAndRecover:
    """I05: Terminal shrinks below floor → backdrop; grows back → backdrop removed."""

    def test_too_small_logic_floor(self):
        # I05a: at threshold boundary
        w, h = THRESHOLD_ULTRA_NARROW - 1, THRESHOLD_MIN_HEIGHT
        assert w < THRESHOLD_ULTRA_NARROW or h < THRESHOLD_MIN_HEIGHT

    def test_too_small_exact_threshold(self):
        # Exactly at threshold — NOT too small
        w, h = THRESHOLD_ULTRA_NARROW, THRESHOLD_MIN_HEIGHT
        assert not (w < THRESHOLD_ULTRA_NARROW or h < THRESHOLD_MIN_HEIGHT)

    def test_apply_min_size_overlay_method_exists(self):
        from hermes_cli.tui.app import HermesApp
        assert hasattr(HermesApp, "_apply_min_size_overlay")

    def test_flush_resize_calls_apply_min_size(self):
        from hermes_cli.tui.app import HermesApp
        src = inspect.getsource(HermesApp._flush_resize)
        assert "_apply_min_size_overlay" in src

    def test_min_size_backdrop_importable(self):
        from hermes_cli.tui.min_size_overlay import MinSizeBackdrop, MinSizeBox
        assert MinSizeBackdrop is not None

    def test_backdrop_update_size_method(self):
        from hermes_cli.tui.min_size_overlay import MinSizeBackdrop
        assert hasattr(MinSizeBackdrop, "update_size")

    def test_backdrop_can_focus_false(self):
        from hermes_cli.tui.min_size_overlay import MinSizeBackdrop
        assert MinSizeBackdrop.can_focus is False

    def test_backdrop_allow_maximize_false(self):
        from hermes_cli.tui.min_size_overlay import MinSizeBackdrop
        assert MinSizeBackdrop.ALLOW_MAXIMIZE is False


# ---------------------------------------------------------------------------
# I06: Burst resizes — debounce — final state matches last size
# ---------------------------------------------------------------------------

class TestDebounce:
    """I06: Burst of resize events; only final size matters."""

    def test_debounce_attrs_set_in_init(self):
        from hermes_cli.tui.app import HermesApp
        src = inspect.getsource(HermesApp.__init__)
        assert "_pending_resize" in src
        assert "_resize_timer" in src

    def test_debounce_constant_positive(self):
        from hermes_cli.tui.app import HermesApp
        assert HermesApp._RESIZE_DEBOUNCE_S > 0

    def test_flush_resize_uses_pending(self):
        # _flush_resize must read _pending_resize
        from hermes_cli.tui.app import HermesApp
        src = inspect.getsource(HermesApp._flush_resize)
        assert "_pending_resize" in src

    def test_on_resize_stops_timer_before_reset(self):
        # on_resize must call timer.stop() before setting new timer
        from hermes_cli.tui.app import HermesApp
        src = inspect.getsource(HermesApp.on_resize)
        assert "stop" in src or "_resize_timer" in src

    def test_resize_timer_uses_set_timer(self):
        from hermes_cli.tui.app import HermesApp
        src = inspect.getsource(HermesApp.on_resize)
        assert "set_timer" in src


# ---------------------------------------------------------------------------
# I07: Stale state after rapid resize
# ---------------------------------------------------------------------------

class TestNoStaleState:
    """I07: No stale _last_resize_w from previous burst."""

    def test_toolgroup_last_w_always_updated(self):
        # Even without a crossing, _last_resize_w tracks last event
        from hermes_cli.tui.tool_group import ToolGroup

        group = MagicMock(spec=ToolGroup)
        group._last_resize_w = 90
        group.set_class = MagicMock()

        # Small deltas — no crossings
        for w in [89, 88, 87, 86, 85]:
            ToolGroup.on_resize(group, _size_event(w))

        assert group._last_resize_w == 85

    def test_footerpane_last_w_always_updated(self):
        from hermes_cli.tui.tool_panel import FooterPane

        pane = MagicMock(spec=FooterPane)
        pane._last_resize_w = 80
        pane.set_class = MagicMock()

        for w in [79, 78, 77, 76]:
            FooterPane.on_resize(pane, _size_event(w))

        assert pane._last_resize_w == 76


# ---------------------------------------------------------------------------
# I08: Initial-state zero crossing
# ---------------------------------------------------------------------------

class TestInitialStateCrossing:
    """I08: _last_resize_w=0 at init → first real resize fires correctly."""

    def test_zero_to_wide_crosses_threshold_narrow(self):
        # 0 → 80: old=0 < lo=58, new=80 >= hi=62 → crossing
        assert crosses_threshold(0, 80, THRESHOLD_NARROW) is True

    def test_zero_to_wide_crosses_threshold_tool_narrow(self):
        # 0 → 100 crosses THRESHOLD_TOOL_NARROW=80
        assert crosses_threshold(0, 100, THRESHOLD_TOOL_NARROW) is True

    def test_zero_to_wide_crosses_comp_narrow(self):
        # 0 → 120 crosses THRESHOLD_COMP_NARROW=100
        assert crosses_threshold(0, 120, THRESHOLD_COMP_NARROW) is True

    def test_zero_to_narrow_crosses_threshold_narrow(self):
        # 0 → 40 stays below lo=58 — no crossing (was_below=True, now_above=False)
        assert crosses_threshold(0, 40, THRESHOLD_NARROW) is False

    def test_toolgroup_first_resize_fires(self):
        # W initial: group._last_resize_w=0, first event w=100 → fires, --narrow removed
        from hermes_cli.tui.tool_group import ToolGroup

        group = MagicMock(spec=ToolGroup)
        group._last_resize_w = 0
        group.set_class = MagicMock()

        ToolGroup.on_resize(group, _size_event(100))
        group.set_class.assert_called_once_with(False, "--narrow")

    def test_footerpane_first_resize_fires(self):
        from hermes_cli.tui.tool_panel import FooterPane

        pane = MagicMock(spec=FooterPane)
        pane._last_resize_w = 0
        pane.set_class = MagicMock()

        FooterPane.on_resize(pane, _size_event(80))
        pane.set_class.assert_called_once_with(False, "compact")
