"""Tests for hermes_cli/tui/pane_manager.py — Phase 1 scaffolding."""
from __future__ import annotations

import pytest

from hermes_cli.tui.pane_manager import (
    LayoutMode,
    PaneId,
    PaneManager,
    _clamp,
    _int_or_none,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pm(cfg: dict | None = None) -> PaneManager:
    """Create a PaneManager with layout=v2 enabled by default."""
    base = {"layout": "v2"}
    if cfg:
        base.update(cfg)
    return PaneManager(cfg=base)


def _make_pm_disabled() -> PaneManager:
    return PaneManager(cfg={"layout": "v1"})


# ---------------------------------------------------------------------------
# _compute_mode
# ---------------------------------------------------------------------------

class TestComputeMode:
    def test_compute_mode_single_below_threshold(self) -> None:
        pm = _make_pm()
        mode = pm._compute_mode(100, 40)
        assert mode == LayoutMode.SINGLE

    def test_compute_mode_three(self) -> None:
        pm = _make_pm()
        mode = pm._compute_mode(130, 40)
        assert mode == LayoutMode.THREE

    def test_compute_mode_three_wide(self) -> None:
        pm = _make_pm()
        mode = pm._compute_mode(170, 40)
        assert mode == LayoutMode.THREE_WIDE

    def test_compute_mode_disabled(self) -> None:
        pm = _make_pm_disabled()
        # Even with large terminal, disabled → always SINGLE
        assert pm._compute_mode(200, 50) == LayoutMode.SINGLE
        assert pm._compute_mode(130, 40) == LayoutMode.SINGLE

    def test_compute_mode_short_terminal(self) -> None:
        pm = _make_pm()
        # h=15 < MIN_HEIGHT=20 → SINGLE regardless of width
        mode = pm._compute_mode(200, 15)
        assert mode == LayoutMode.SINGLE

    def test_compute_mode_exactly_at_off_threshold(self) -> None:
        pm = _make_pm()
        # At threshold → THREE (not SINGLE)
        assert pm._compute_mode(120, 40) == LayoutMode.THREE

    def test_compute_mode_exactly_at_wide_threshold(self) -> None:
        pm = _make_pm()
        assert pm._compute_mode(160, 40) == LayoutMode.THREE_WIDE


# ---------------------------------------------------------------------------
# _compute_widths
# ---------------------------------------------------------------------------

class TestComputeWidths:
    def test_widths_single(self) -> None:
        pm = _make_pm()
        left, center, right = pm._compute_widths(200, LayoutMode.SINGLE)
        assert left == 0
        assert right == 0
        assert center == 200

    def test_widths_three(self) -> None:
        pm = _make_pm()
        term_w = 150
        left, center, right = pm._compute_widths(term_w, LayoutMode.THREE)
        assert left == 22
        assert right == 24
        assert center == term_w - 22 - 24

    def test_widths_three_wide(self) -> None:
        pm = _make_pm()
        term_w = 200
        left, center, right = pm._compute_widths(term_w, LayoutMode.THREE_WIDE)
        assert left == 28
        assert right == 32
        assert center == term_w - 28 - 32

    def test_widths_center_guard_proportional_shrink(self) -> None:
        """Custom side widths that leave center < 80: sides shrink proportionally."""
        pm = _make_pm({"layout_v2": {"default_left_w": 40, "default_right_w": 40}})
        # term_w=130; sides=80, center=50 < MIN_CENTER_W=80; need to shrink
        left, center, right = pm._compute_widths(130, LayoutMode.THREE)
        # Center must be >= MIN_CENTER_W (or fallback to single)
        if left == 0:
            # fallthrough path: center == term_w
            assert center == 130
        else:
            assert center >= pm.MIN_CENTER_W

    def test_widths_center_guard_fallthrough(self) -> None:
        """Sides already at MIN_SIDE_W and center still < MIN_CENTER_W → (0, term_w, 0)."""
        pm = _make_pm()
        # Very narrow: 16+16=32, center=50-32=18 < 80; can't shrink below MIN_SIDE_W
        left, center, right = pm._compute_widths(50, LayoutMode.THREE)
        assert left == 0
        assert right == 0
        assert center == 50


# ---------------------------------------------------------------------------
# compute_layout
# ---------------------------------------------------------------------------

class TestComputeLayout:
    def test_compute_layout_forces_single_when_widths_fallthrough(self) -> None:
        pm = _make_pm()
        # Narrow enough that widths can't satisfy MIN_CENTER_W
        mode, left, center, right = pm.compute_layout(50, 40)
        assert mode == LayoutMode.SINGLE
        assert left == 0
        assert right == 0

    def test_compute_layout_normal(self) -> None:
        pm = _make_pm()
        mode, left, center, right = pm.compute_layout(180, 40)
        assert mode == LayoutMode.THREE_WIDE
        assert left > 0
        assert right > 0
        assert center >= pm.MIN_CENTER_W


# ---------------------------------------------------------------------------
# on_resize / hysteresis
# ---------------------------------------------------------------------------

class TestOnResize:
    def test_on_resize_returns_false_when_no_change(self) -> None:
        pm = _make_pm()
        # Start in SINGLE (mode defaults to SINGLE), resize to still-SINGLE
        result = pm.on_resize(100, 40)
        assert result is False

    def test_on_resize_returns_true_when_mode_changes(self) -> None:
        pm = _make_pm()
        # Start in SINGLE; resize to width clearly in THREE range
        result = pm.on_resize(140, 40)
        assert result is True
        assert pm._mode == LayoutMode.THREE

    def test_hysteresis_prevents_upward_flap(self) -> None:
        """Resize to just below threshold+HYSTERESIS from THREE: no mode change."""
        pm = _make_pm()
        # Get into THREE mode first (cleanly)
        pm.on_resize(140, 40)
        assert pm._mode == LayoutMode.THREE

        # Now resize to threshold_off - HYSTERESIS + 1 = 120 - 2 + 1 = 119
        # That's below threshold_off but within hysteresis band
        result = pm.on_resize(119, 40)
        # Should NOT flip back to SINGLE (within hysteresis band)
        assert result is False
        assert pm._mode == LayoutMode.THREE

    def test_hysteresis_allows_clear_transition(self) -> None:
        """Resize well below threshold → mode changes."""
        pm = _make_pm()
        pm.on_resize(140, 40)
        assert pm._mode == LayoutMode.THREE

        # Resize well below off threshold (100 < 120 - 2 = 118)
        result = pm.on_resize(100, 40)
        assert result is True
        assert pm._mode == LayoutMode.SINGLE

    def test_on_resize_disabled_always_false(self) -> None:
        pm = _make_pm_disabled()
        assert pm.on_resize(200, 40) is False


# ---------------------------------------------------------------------------
# Collapse
# ---------------------------------------------------------------------------

class TestCollapse:
    def test_toggle_collapse_left(self) -> None:
        pm = _make_pm()
        assert pm.is_collapsed(PaneId.LEFT) is False
        result = pm.toggle_left_collapsed()
        assert result is True
        assert pm.is_collapsed(PaneId.LEFT) is True
        result = pm.toggle_left_collapsed()
        assert result is False

    def test_toggle_collapse_right(self) -> None:
        pm = _make_pm()
        assert pm.is_collapsed(PaneId.RIGHT) is False
        result = pm.toggle_right_collapsed()
        assert result is True
        assert pm.is_collapsed(PaneId.RIGHT) is True

    def test_center_never_collapsed(self) -> None:
        pm = _make_pm()
        assert pm.is_collapsed(PaneId.CENTER) is False


# ---------------------------------------------------------------------------
# Focus / next_visible_pane
# ---------------------------------------------------------------------------

class TestFocus:
    def test_next_visible_pane_skips_collapsed_correctly(self) -> None:
        pm = _make_pm()
        pm.focus_pane(PaneId.CENTER)
        pm.toggle_right_collapsed()  # RIGHT collapsed
        nxt = pm.next_visible_pane()
        # order=[LEFT,CENTER,RIGHT], idx=1 (CENTER)
        # i=1 → order[2]=RIGHT → collapsed → skip
        # i=2 → order[0]=LEFT → not collapsed → return LEFT
        assert nxt == PaneId.LEFT

    def test_next_visible_pane_wraps(self) -> None:
        pm = _make_pm()
        pm.focus_pane(PaneId.RIGHT)
        # No collapses; from RIGHT → wraps to LEFT
        nxt = pm.next_visible_pane()
        assert nxt == PaneId.LEFT

    def test_next_visible_pane_reverse(self) -> None:
        pm = _make_pm()
        pm.focus_pane(PaneId.CENTER)
        nxt = pm.next_visible_pane(reverse=True)
        # reverse order=[RIGHT,CENTER,LEFT], idx=1 (CENTER)
        # i=1 → LEFT → return LEFT
        assert nxt == PaneId.LEFT


# ---------------------------------------------------------------------------
# Host registry
# ---------------------------------------------------------------------------

class TestHostRegistry:
    def test_set_host_and_get_host(self) -> None:
        pm = _make_pm()

        class FakeHost:
            pane_id = PaneId.CENTER
            widget = None
            preferred_width_cells = None
            collapsible = False
            focus_binding = None
            def on_pane_show(self) -> None: pass
            def on_pane_hide(self) -> None: pass
            def on_pane_width_change(self, w: int) -> None: pass

        host = FakeHost()
        pm.set_host(PaneId.CENTER, host)
        assert pm.get_host(PaneId.CENTER) is host

    def test_get_host_missing_returns_none(self) -> None:
        pm = _make_pm()
        assert pm.get_host(PaneId.LEFT) is None


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

class TestStatePersistence:
    def test_dump_and_load_state_roundtrip(self) -> None:
        pm = _make_pm()
        pm.toggle_left_collapsed()
        pm.set_left_w(30)
        pm.set_right_w(35)

        state = pm.dump_state()
        assert state["left_collapsed"] is True
        assert state["left_w"] == 30
        assert state["right_w"] == 35

        pm2 = _make_pm()
        pm2.load_state(state)
        assert pm2._left_collapsed is True
        assert pm2._left_w_override == 30
        assert pm2._right_w_override == 35

    def test_load_state_advisory_mode(self) -> None:
        """Loaded mode is advisory — actual mode comes from compute_layout."""
        pm = _make_pm()
        # Even if we load a state that claims THREE_WIDE, _mode stays SINGLE
        # until on_resize is called
        pm.load_state({"mode": "three_wide", "left_collapsed": False, "right_collapsed": False})
        # _mode is NOT updated by load_state (only collapse/width state is restored)
        # compute_layout is still based on terminal dimensions
        mode, *_ = pm.compute_layout(100, 40)
        assert mode == LayoutMode.SINGLE  # 100 < threshold_off → SINGLE


# ---------------------------------------------------------------------------
# Config threshold clamping
# ---------------------------------------------------------------------------

class TestConfigThresholds:
    def test_config_thresholds_clamped(self) -> None:
        """Out-of-range panes_off_cols and panes_wide_cols are clamped."""
        pm = PaneManager(cfg={
            "layout": "v2",
            "layout_v2": {
                "panes_off_cols": 10,   # below min=60 → clamped to 60
                "panes_wide_cols": 999,  # above max=240 → clamped to 240
            }
        })
        assert pm._threshold_off == 60
        assert pm._threshold_wide == 240

    def test_config_threshold_wide_min_gap(self) -> None:
        """threshold_wide is always >= threshold_off + 20."""
        pm = PaneManager(cfg={
            "layout": "v2",
            "layout_v2": {
                "panes_off_cols": 100,
                "panes_wide_cols": 110,  # too close to off; should be clamped up
            }
        })
        assert pm._threshold_wide >= pm._threshold_off + 20


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_clamp_within_range(self) -> None:
        assert _clamp(50, 0, 100) == 50

    def test_clamp_below_lo(self) -> None:
        assert _clamp(-5, 0, 100) == 0

    def test_clamp_above_hi(self) -> None:
        assert _clamp(200, 0, 100) == 100

    def test_int_or_none_with_value(self) -> None:
        assert _int_or_none("42") == 42
        assert _int_or_none(10) == 10

    def test_int_or_none_with_none(self) -> None:
        assert _int_or_none(None) is None
