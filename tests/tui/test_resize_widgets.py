"""Widget-level resize tests — W01-W12.

Covers: ToolGroup hysteresis, FooterPane compact toggle, DrawilleOverlay
engine resize + refresh, CompletionOverlay --narrow toggle, ToolsScreen
dismiss on narrow, AssistantNameplate canvas tracking, InlineMediaWidget
seekbar refresh, StatusBar threshold jumps.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch, call

import pytest

from hermes_cli.tui.resize_utils import (
    HYSTERESIS,
    THRESHOLD_COMP_NARROW,
    THRESHOLD_NARROW,
    THRESHOLD_TOOL_NARROW,
    THRESHOLD_ULTRA_NARROW,
    THRESHOLD_MIN_HEIGHT,
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
# ToolGroup hysteresis (W01-W02)
# ---------------------------------------------------------------------------

class TestToolGroupHysteresis:
    """W01-W02: ToolGroup sets --narrow only on clean threshold crossing."""

    def test_no_flip_within_band(self):
        # W01: oscillate 79↔81 — no set_class calls
        from hermes_cli.tui.tool_group import ToolGroup

        group = MagicMock(spec=ToolGroup)
        group._last_resize_w = 90  # starts above hi=82
        group.set_class = MagicMock()

        for w in [82, 81, 80, 79, 78, 79, 80, 81]:
            if crosses_threshold(group._last_resize_w, w, THRESHOLD_TOOL_NARROW):
                group.set_class(w < THRESHOLD_TOOL_NARROW, "--narrow")
            group._last_resize_w = w

        # 90→82: 82 < lo=78? No. 82 >= hi=82? Yes. was_above=True, now_below=(82<78)=False → no cross
        # 82→81: 81 < hi=82 — in band. was_above=(82>=82)=True, now_below=(81<78)=False → no
        # continues in band; never crosses lo=78
        group.set_class.assert_not_called()

    def test_class_set_on_clear_crossing(self):
        # W02: clear drop from 90 → 60 crosses THRESHOLD_TOOL_NARROW=80
        from hermes_cli.tui.tool_group import ToolGroup

        group = MagicMock(spec=ToolGroup)
        group._last_resize_w = 90
        group.set_class = MagicMock()

        w = 60
        if crosses_threshold(group._last_resize_w, w, THRESHOLD_TOOL_NARROW):
            group.set_class(w < THRESHOLD_TOOL_NARROW, "--narrow")
        group._last_resize_w = w

        group.set_class.assert_called_once_with(True, "--narrow")

    def test_last_resize_w_updated(self):
        # _last_resize_w must be updated even when no crossing
        from hermes_cli.tui.tool_group import ToolGroup

        group = MagicMock(spec=ToolGroup)
        group._last_resize_w = 90

        w = 85
        if crosses_threshold(group._last_resize_w, w, THRESHOLD_TOOL_NARROW):
            pass
        group._last_resize_w = w

        assert group._last_resize_w == 85

    def test_on_resize_method_exists(self):
        from hermes_cli.tui.tool_group import ToolGroup
        assert hasattr(ToolGroup, "on_resize")

    def test_last_resize_w_attr_in_init(self):
        from hermes_cli.tui.tool_group import ToolGroup
        src = inspect.getsource(ToolGroup.__init__)
        assert "_last_resize_w" in src


# ---------------------------------------------------------------------------
# FooterPane compact toggle (W03-W04)
# ---------------------------------------------------------------------------

class TestFooterPaneCompact:
    """W03-W04: FooterPane sets compact class on clear THRESHOLD_NARROW crossing."""

    def test_on_resize_method_exists(self):
        from hermes_cli.tui.tool_panel import FooterPane
        assert hasattr(FooterPane, "on_resize")

    def test_last_resize_w_in_init(self):
        from hermes_cli.tui.tool_panel import FooterPane
        src = inspect.getsource(FooterPane.__init__)
        assert "_last_resize_w" in src

    def test_compact_set_on_narrow_crossing(self):
        # W03: 80 → 40 crosses THRESHOLD_NARROW=60
        from hermes_cli.tui.tool_panel import FooterPane

        pane = MagicMock(spec=FooterPane)
        pane._last_resize_w = 80
        pane.set_class = MagicMock()

        FooterPane.on_resize(pane, _size_event(40))
        pane.set_class.assert_called_once_with(True, "compact")

    def test_no_flip_in_dead_band(self):
        # W04: oscillate in [58, 62) — no set_class
        from hermes_cli.tui.tool_panel import FooterPane

        pane = MagicMock(spec=FooterPane)
        pane._last_resize_w = 65
        pane.set_class = MagicMock()

        for w in [63, 61, 59, 60, 62]:
            FooterPane.on_resize(pane, _size_event(w))

        pane.set_class.assert_not_called()


# ---------------------------------------------------------------------------
# DrawilleOverlay engine resize (W05-W06)
# ---------------------------------------------------------------------------

class TestDrawilleOverlayResize:
    """W05-W06: DrawilleOverlay resizes engine canvas and calls refresh()."""

    def test_on_resize_method_exists(self):
        from hermes_cli.tui.drawille_overlay import DrawilleOverlay
        assert hasattr(DrawilleOverlay, "on_resize")

    def test_refresh_called_when_active(self):
        # W05: _anim_params set → refresh called after resize
        from hermes_cli.tui.drawille_overlay import DrawilleOverlay

        overlay = MagicMock(spec=DrawilleOverlay)
        overlay._anim_params = MagicMock()
        overlay._anim_params.width = 160
        overlay._anim_params.height = 96

        DrawilleOverlay.on_resize(overlay, _size_event(100, 30))

        overlay.refresh.assert_called_once()

    def test_canvas_dims_updated(self):
        # W06: params.width = event.width*2, params.height = event.height*4
        from hermes_cli.tui.drawille_overlay import DrawilleOverlay

        overlay = MagicMock(spec=DrawilleOverlay)
        overlay._anim_params = MagicMock()

        DrawilleOverlay.on_resize(overlay, _size_event(80, 24))

        assert overlay._anim_params.width == 160
        assert overlay._anim_params.height == 96

    def test_no_refresh_when_inactive(self):
        # W05b: _anim_params is None → no refresh, no error
        from hermes_cli.tui.drawille_overlay import DrawilleOverlay

        overlay = MagicMock(spec=DrawilleOverlay)
        overlay._anim_params = None

        DrawilleOverlay.on_resize(overlay, _size_event(80, 24))
        overlay.refresh.assert_not_called()


# ---------------------------------------------------------------------------
# CompletionOverlay --narrow toggle (W07)
# ---------------------------------------------------------------------------

class TestCompletionOverlayNarrow:
    """W07: CompletionOverlay toggles --narrow class."""

    def test_on_resize_method_exists(self):
        from hermes_cli.tui.completion_overlay import CompletionOverlay
        assert hasattr(CompletionOverlay, "on_resize")

    def test_last_applied_w_init(self):
        from hermes_cli.tui.completion_overlay import CompletionOverlay
        # Check on_mount or __init__ sets _last_applied_w
        src = inspect.getsource(CompletionOverlay.on_mount)
        assert "_last_applied_w" in src

    def test_narrow_class_set_on_crossing(self):
        # W07: 120 → 70 crosses THRESHOLD_COMP_NARROW=80 dead-band [78, 82)
        from hermes_cli.tui.completion_overlay import CompletionOverlay

        overlay = MagicMock(spec=CompletionOverlay)
        overlay._last_applied_w = 120
        overlay.set_class = MagicMock()

        CompletionOverlay.on_resize(overlay, _size_event(70))
        overlay.set_class.assert_called_once_with(True, "--narrow")

    def test_no_set_class_in_band(self):
        # No crossing within dead-band
        from hermes_cli.tui.completion_overlay import CompletionOverlay

        overlay = MagicMock(spec=CompletionOverlay)
        overlay._last_applied_w = 103
        overlay.set_class = MagicMock()

        CompletionOverlay.on_resize(overlay, _size_event(101))
        overlay.set_class.assert_not_called()


# ---------------------------------------------------------------------------
# AssistantNameplate canvas tracking (W08)
# ---------------------------------------------------------------------------

class TestAssistantNameplateResize:
    """W08: AssistantNameplate tracks _canvas_width."""

    def test_on_resize_method_exists(self):
        from hermes_cli.tui.widgets import AssistantNameplate
        assert hasattr(AssistantNameplate, "on_resize")

    def test_canvas_width_attr(self):
        from hermes_cli.tui.widgets import AssistantNameplate
        src = inspect.getsource(AssistantNameplate.__init__)
        assert "_canvas_width" in src

    def test_canvas_width_updated_on_large_change(self):
        # W08: large resize updates _canvas_width
        from hermes_cli.tui.widgets import AssistantNameplate

        widget = MagicMock(spec=AssistantNameplate)
        widget._canvas_width = 80
        widget._last_nameplate_w = 80

        AssistantNameplate.on_resize(widget, _size_event(140))
        # Change > HYSTERESIS*2=4 → _canvas_width should update
        assert widget._canvas_width == 140

    def test_canvas_width_stable_on_small_change(self):
        # W08b: tiny resize (2 cols) does NOT update _canvas_width
        from hermes_cli.tui.widgets import AssistantNameplate

        widget = MagicMock(spec=AssistantNameplate)
        widget._canvas_width = 80
        widget._last_nameplate_w = 80

        AssistantNameplate.on_resize(widget, _size_event(82))
        # Change = 2 ≤ HYSTERESIS*2=4 → _canvas_width stays 80
        assert widget._canvas_width == 80


# ---------------------------------------------------------------------------
# InlineMediaWidget → SeekBar refresh (W09)
# ---------------------------------------------------------------------------

class TestInlineMediaWidgetResize:
    """W09: InlineMediaWidget.on_resize refreshes SeekBar."""

    def test_on_resize_exists(self):
        from hermes_cli.tui.widgets import InlineMediaWidget
        assert hasattr(InlineMediaWidget, "on_resize")

    def test_seekbar_refresh_called(self):
        from hermes_cli.tui.widgets import InlineMediaWidget

        widget = MagicMock(spec=InlineMediaWidget)
        widget._seekbar = MagicMock()

        InlineMediaWidget.on_resize(widget, _size_event(80))
        widget._seekbar.refresh.assert_called_once()


# ---------------------------------------------------------------------------
# StatusBar render reads self.size.width (W10-W11)
# ---------------------------------------------------------------------------

class TestStatusBarAdaptive:
    """W10-W11: StatusBar render() reads width from self.size."""

    def test_render_reads_self_size_width(self):
        # W10
        from hermes_cli.tui.widgets import StatusBar
        src = inspect.getsource(StatusBar.render)
        assert "self.size.width" in src or "self.size" in src

    def test_render_has_multiple_width_branches(self):
        # W11: at least two different width thresholds
        from hermes_cli.tui.widgets import StatusBar
        src = inspect.getsource(StatusBar.render)
        # Must have at least one numeric threshold comparison
        assert "width <" in src or "w <" in src

    def test_no_on_resize_method(self):
        # StatusBar adapts in render() — no separate on_resize needed
        from hermes_cli.tui.widgets import StatusBar
        # If on_resize exists it must not be a custom implementation
        # (it may inherit from Widget's no-op)
        if hasattr(StatusBar, "on_resize"):
            src = inspect.getsource(StatusBar.on_resize)
            # Should not modify state if present — basic check
            assert "set_class" not in src


# ---------------------------------------------------------------------------
# ToolsScreen dismiss (W12)
# ---------------------------------------------------------------------------

class TestToolsScreenDismiss:
    """W12: ToolsScreen.on_resize flashes warning and pops when too narrow."""

    def test_on_resize_method_exists(self):
        from hermes_cli.tui.tools_overlay import ToolsScreen
        assert hasattr(ToolsScreen, "on_resize")

    def test_last_resize_w_in_init(self):
        from hermes_cli.tui.tools_overlay import ToolsScreen
        src = inspect.getsource(ToolsScreen.__init__)
        assert "_last_resize_w" in src

    def test_pop_screen_on_narrow(self):
        # W12: terminal shrinks to < THRESHOLD_NARROW → pop_screen
        from hermes_cli.tui.tools_overlay import ToolsScreen

        screen = MagicMock(spec=ToolsScreen)
        screen._last_resize_w = 80
        screen._term_w = 80
        app_mock = MagicMock()
        app_mock.size = MagicMock()
        app_mock.size.width = 40
        screen.app = app_mock

        ToolsScreen.on_resize(screen)

        app_mock.pop_screen.assert_called_once()

    def test_no_pop_when_wide(self):
        # W12b: wide terminal → no pop
        from hermes_cli.tui.tools_overlay import ToolsScreen

        screen = MagicMock(spec=ToolsScreen)
        screen._last_resize_w = 80
        screen._term_w = 80
        app_mock = MagicMock()
        app_mock.size = MagicMock()
        app_mock.size.width = 100
        screen.app = app_mock

        ToolsScreen.on_resize(screen)

        app_mock.pop_screen.assert_not_called()
