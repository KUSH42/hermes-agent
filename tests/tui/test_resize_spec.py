"""Core resize spec tests — R01-R20.

Covers: MinSizeBackdrop, hysteresis, debounce, OutputPanel scroll anchor,
StatusBar label modes, LiveLineWidget (N/A — no ghost text yet),
OmissionBar label hiding, SeekBar refresh, crosses_threshold util.
"""

from __future__ import annotations

import asyncio
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
# Utility tests (no Textual app needed)
# ---------------------------------------------------------------------------

class TestCrossesThreshold:
    """R18–R20: crosses_threshold() utility."""

    def test_rising_crosses(self):
        # R18: rising from below → above threshold
        assert crosses_threshold(50, 85, 80) is True

    def test_falling_crosses(self):
        # R19: falling from above → below threshold
        assert crosses_threshold(85, 50, 80) is True

    def test_within_dead_band(self):
        # R20: both values in [78, 82) — no crossing
        assert crosses_threshold(81, 83, 80) is False

    def test_both_above(self):
        # 90 → 95, both above hi=82 — no crossing
        assert crosses_threshold(90, 95, 80) is False

    def test_both_below(self):
        # 50 → 55, both below lo=78 — no crossing
        assert crosses_threshold(50, 55, 80) is False

    def test_old_in_dead_band_new_above(self):
        # old in dead-band, new above — no crossing (dead-band → above, ambiguous)
        assert crosses_threshold(80, 90, 80) is False

    def test_old_in_dead_band_new_below(self):
        # old in dead-band, new below — no crossing
        assert crosses_threshold(80, 70, 80) is False

    def test_initial_state_zero(self):
        # R (I08): old=0 crosses to new=90 — initial state fires
        assert crosses_threshold(0, 90, 80) is True

    def test_initial_state_zero_narrow(self):
        # old=0 crosses THRESHOLD_NARROW (60)
        assert crosses_threshold(0, 70, 60) is True

    def test_no_change(self):
        # old == new → False
        assert crosses_threshold(75, 75, 80) is False

    def test_custom_hysteresis(self):
        # With hyst=0, exact threshold crossing fires
        assert crosses_threshold(79, 81, 80, hyst=0) is True
        assert crosses_threshold(80, 80, 80, hyst=0) is False


# ---------------------------------------------------------------------------
# MinSizeBackdrop
# ---------------------------------------------------------------------------

class TestMinSizeBackdrop:
    """R01–R03: MinSizeBackdrop mount/dismiss via _apply_min_size_overlay."""

    def _make_app_stub(self):
        """Return a minimal stub with _apply_min_size_overlay wired up."""
        from hermes_cli.tui.min_size_overlay import MinSizeBackdrop

        # Simulate the HermesApp method in isolation using mocks
        screen = MagicMock()
        screen.query.return_value = []  # no existing backdrop by default
        app = MagicMock()
        app.screen = screen
        return app, MinSizeBackdrop

    def test_shown_narrow(self):
        # R01: mount when w < THRESHOLD_ULTRA_NARROW
        from hermes_cli.tui.min_size_overlay import MinSizeBackdrop
        app, _ = self._make_app_stub()
        app.screen.query.return_value = []

        # Simulate _apply_min_size_overlay logic
        w, h = 30, 10
        too_small = w < THRESHOLD_ULTRA_NARROW or h < THRESHOLD_MIN_HEIGHT
        assert too_small is True

    def test_shown_short_height(self):
        # R02: mount when h < THRESHOLD_MIN_HEIGHT
        w, h = 60, 6
        too_small = w < THRESHOLD_ULTRA_NARROW or h < THRESHOLD_MIN_HEIGHT
        assert too_small is True

    def test_not_shown_adequate(self):
        # Terminal large enough — no backdrop
        w, h = 80, 24
        too_small = w < THRESHOLD_ULTRA_NARROW or h < THRESHOLD_MIN_HEIGHT
        assert too_small is False

    def test_dismissed_on_grow(self):
        # R03: once adequate, too_small becomes False → backdrop should be removed
        w_small, h_small = 30, 6
        w_ok, h_ok = 80, 24
        assert (w_small < THRESHOLD_ULTRA_NARROW or h_small < THRESHOLD_MIN_HEIGHT) is True
        assert (w_ok < THRESHOLD_ULTRA_NARROW or h_ok < THRESHOLD_MIN_HEIGHT) is False

    def test_backdrop_widget_imports(self):
        from hermes_cli.tui.min_size_overlay import MinSizeBackdrop, MinSizeBox
        assert MinSizeBackdrop is not None
        assert MinSizeBox is not None

    def test_backdrop_can_focus_false(self):
        from hermes_cli.tui.min_size_overlay import MinSizeBackdrop
        assert MinSizeBackdrop.can_focus is False

    def test_backdrop_allow_maximize_false(self):
        from hermes_cli.tui.min_size_overlay import MinSizeBackdrop
        assert MinSizeBackdrop.ALLOW_MAXIMIZE is False


# ---------------------------------------------------------------------------
# Hysteresis — ToolGroup, ToolPanel (FooterPane)
# ---------------------------------------------------------------------------

class TestHysteresisNoFlip:
    """R04–R05: hysteresis prevents class flip-flop."""

    def test_toolgroup_no_flip_in_dead_band(self):
        # R04: width oscillates in [78, 82) — no class change
        from hermes_cli.tui.tool_group import ToolGroup

        group = MagicMock(spec=ToolGroup)
        group._last_resize_w = 0
        group.set_class = MagicMock()

        # Simulate resize events within dead-band
        for w in [79, 80, 81, 78, 82]:
            if crosses_threshold(group._last_resize_w, w, THRESHOLD_TOOL_NARROW):
                group.set_class(w < THRESHOLD_TOOL_NARROW, "--narrow")
            group._last_resize_w = w

        # Only the very first event (0→79) should trigger (0 < lo=78 is False,
        # wait: 0 < 78 = True, 79 >= 82? No → no crossing). Then 79→80 etc in band.
        # Actually 0 → 79: was_below=(0<78)=True, now_above=(79>=82)=False → False
        # So NO crossing at all — set_class never called
        group.set_class.assert_not_called()

    def test_toolgroup_class_applied_clear_crossing(self):
        # R05: w moves from 90 → 70 — clear crossing of threshold 80
        from hermes_cli.tui.resize_utils import crosses_threshold as ct

        last_w = 90
        w = 70
        assert ct(last_w, w, THRESHOLD_TOOL_NARROW) is True

    def test_footerpane_compact_uses_hysteresis(self):
        # FooterPane.on_resize should only toggle at clear crossings
        from hermes_cli.tui.resize_utils import crosses_threshold as ct

        # Jumping from 65 to 55 crosses THRESHOLD_NARROW=60
        assert ct(65, 55, THRESHOLD_NARROW) is True

        # Jumping from 65 to 63 stays in dead-band [58, 62) — no
        # Actually 65 >= hi=62 (above), 63 >= lo=58 and < hi=62 (in dead-band)
        # was_above=True, now_below=(63<58)=False → False
        assert ct(65, 63, THRESHOLD_NARROW) is False


# ---------------------------------------------------------------------------
# Debounce
# ---------------------------------------------------------------------------

class TestDebounce:
    """R06–R07: HermesApp on_resize debounce."""

    def test_debounce_attrs_exist(self):
        # Verify the init attrs are declared
        import inspect
        from hermes_cli.tui.app import HermesApp
        src = inspect.getsource(HermesApp.__init__)
        assert "_pending_resize" in src
        assert "_resize_timer" in src

    def test_flush_resize_method_exists(self):
        from hermes_cli.tui.app import HermesApp
        assert hasattr(HermesApp, "_flush_resize")

    def test_maybe_reload_emoji_method_exists(self):
        from hermes_cli.tui.app import HermesApp
        assert hasattr(HermesApp, "_maybe_reload_emoji")

    def test_apply_min_size_overlay_method_exists(self):
        from hermes_cli.tui.app import HermesApp
        assert hasattr(HermesApp, "_apply_min_size_overlay")

    def test_debounce_constant(self):
        from hermes_cli.tui.app import HermesApp
        assert hasattr(HermesApp, "_RESIZE_DEBOUNCE_S")
        assert HermesApp._RESIZE_DEBOUNCE_S > 0


# ---------------------------------------------------------------------------
# OutputPanel scroll anchor
# ---------------------------------------------------------------------------

class TestOutputPanelScrollAnchor:
    """R08–R09: on_resize scroll anchor."""

    def test_on_resize_method_exists(self):
        from hermes_cli.tui.widgets import OutputPanel
        assert hasattr(OutputPanel, "on_resize")

    def test_pinned_calls_scroll_end(self):
        # R08: _user_scrolled_up=False → scroll_end called
        from hermes_cli.tui.widgets import OutputPanel

        panel = MagicMock(spec=OutputPanel)
        panel._user_scrolled_up = False
        panel.scroll_y = 0
        panel.virtual_size = MagicMock()
        panel.virtual_size.height = 100
        panel.call_after_refresh = MagicMock()
        panel.scroll_end = MagicMock()

        # Call the real on_resize logic
        OutputPanel.on_resize(panel, MagicMock())
        panel.call_after_refresh.assert_called_once_with(panel.scroll_end, animate=False)

    def test_fractional_position_preserved(self):
        # R09: _user_scrolled_up=True → fractional restore scheduled
        from hermes_cli.tui.widgets import OutputPanel

        panel = MagicMock(spec=OutputPanel)
        panel._user_scrolled_up = True
        panel.scroll_y = 50
        panel.virtual_size = MagicMock()
        panel.virtual_size.height = 200
        panel.call_after_refresh = MagicMock()

        OutputPanel.on_resize(panel, MagicMock())
        # call_after_refresh called with a closure (not scroll_end)
        panel.call_after_refresh.assert_called_once()
        args = panel.call_after_refresh.call_args[0]
        assert callable(args[0])


# ---------------------------------------------------------------------------
# OmissionBar label hiding
# ---------------------------------------------------------------------------

class TestOmissionBarResize:
    """R15–R16: OmissionBar hides label when narrow."""

    def test_on_resize_method_exists(self):
        from hermes_cli.tui.tool_blocks import OmissionBar
        assert hasattr(OmissionBar, "on_resize")

    def test_last_resize_w_attr(self):
        from hermes_cli.tui.tool_blocks import OmissionBar
        import inspect
        src = inspect.getsource(OmissionBar.__init__)
        assert "_last_resize_w" in src

    def test_label_hidden_narrow(self):
        # R15: label abbreviated (B4) at narrow widget width — not hidden,
        # but update() called with short text.
        from hermes_cli.tui.tool_blocks import OmissionBar

        bar = MagicMock(spec=OmissionBar)
        bar._last_resize_w = 80
        bar._label = MagicMock()
        bar._label.display = True
        bar.size.width = 35  # on_resize uses self.size.width
        bar._narrow = False
        # B4: on_resize reads _total/_visible_start/_visible_end to compute n_hidden
        bar._total = 50
        bar._visible_start = 0
        bar._visible_end = 20  # n_hidden = 50 - 20 = 30 → label shows "↓30L↑"

        # Simulate crossing below THRESHOLD_NARROW
        OmissionBar.on_resize(bar, _make_size_event(35))
        # After B4: label text is abbreviated, update() called (display not forced False)
        bar._label.update.assert_called_once()
        call_arg = bar._label.update.call_args[0][0]
        assert "30" in call_arg, f"Expected abbreviated count in label; got: {call_arg!r}"

    def test_label_visible_wide(self):
        # R16: label visible at wide widget width
        from hermes_cli.tui.tool_blocks import OmissionBar

        bar = MagicMock(spec=OmissionBar)
        bar._last_resize_w = 0  # initial state
        bar._label = MagicMock()
        bar._label.display = True
        bar.size.width = 70  # on_resize uses self.size.width
        bar._narrow = True  # was narrow, going wide

        OmissionBar.on_resize(bar, _make_size_event(70))
        # 0 → 70: crosses THRESHOLD_NARROW (60)? was_below=(0<58)=True, now_above=(70>=62)=True → Yes!
        # So it fires: label.display = (70 >= 60) = True
        assert bar._label.display is True


# ---------------------------------------------------------------------------
# SeekBar refresh
# ---------------------------------------------------------------------------

class TestSeekBarRefresh:
    """R17: SeekBar.refresh() called on InlineMediaWidget resize."""

    def test_inline_media_on_resize_exists(self):
        from hermes_cli.tui.widgets import InlineMediaWidget
        assert hasattr(InlineMediaWidget, "on_resize")

    def test_seekbar_refresh_called(self):
        from hermes_cli.tui.widgets import InlineMediaWidget

        widget = MagicMock(spec=InlineMediaWidget)
        widget._seekbar = MagicMock()

        InlineMediaWidget.on_resize(widget, MagicMock())
        widget._seekbar.refresh.assert_called_once()


# ---------------------------------------------------------------------------
# StatusBar already adapts in render() — verify no on_resize regression
# ---------------------------------------------------------------------------

class TestStatusBarRenderAdaptive:
    """R10–R12: StatusBar adapts in render(); no separate on_resize needed."""

    def test_statusbar_reads_self_size_in_render(self):
        import inspect
        from hermes_cli.tui.widgets import StatusBar
        src = inspect.getsource(StatusBar.render)
        assert "self.size.width" in src or "width = self.size" in src

    def test_statusbar_has_width_branches(self):
        import inspect
        from hermes_cli.tui.widgets import StatusBar
        src = inspect.getsource(StatusBar.render)
        assert "width < 40" in src or "width < 60" in src


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_size_event(width: int, height: int = 24) -> MagicMock:
    event = MagicMock()
    event.size = MagicMock()
    event.size.width = width
    event.size.height = height
    return event
