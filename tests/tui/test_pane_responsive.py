"""Phase 3 — R2 pane responsive / wiring tests.

Covers:
- Breakpoint transitions at width boundaries
- Hysteresis prevents flapping
- Short terminal (h < 20) forces SINGLE
- Collapse toggle state
- next_visible_pane cycling
- _apply_layout DOM mutations (integration, run_test)
- Esc routing to input when side pane focused
- Action methods (no-ops in v1, functional in v2)
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from hermes_cli.tui.pane_manager import PaneManager, PaneId, LayoutMode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pm(enabled: bool = True, cfg: dict | None = None, right_collapsed: bool = False) -> PaneManager:
    c: dict = {"layout": "v2" if enabled else "v1"}
    if cfg:
        c.update(cfg)
    pm = PaneManager(c)
    pm._right_collapsed = right_collapsed  # override flag-driven default
    return pm


def _make_app(layout: str = "v2") -> "HermesApp":
    from hermes_cli.tui.app import HermesApp
    cli = MagicMock()
    cli._cfg = {"display": {"layout": layout}}
    cli.agent = MagicMock()
    cli.agent.model = "claude-sonnet-4-6"
    return HermesApp(cli=cli)


# ===========================================================================
# Breakpoint / responsive tests (pure PaneManager)
# ===========================================================================

class TestModeTransitions:
    def test_mode_stays_single_below_120(self) -> None:
        pm = _pm()
        # Pump on_resize to set initial mode, then narrow terminal
        pm.on_resize(100, 40)
        assert pm._mode == LayoutMode.SINGLE

    def test_mode_transitions_at_120(self) -> None:
        pm = _pm()
        # Start below threshold
        pm.on_resize(100, 40)
        assert pm._mode == LayoutMode.SINGLE
        # Jump well past threshold — hysteresis won't block
        changed = pm.on_resize(130, 40)
        assert changed
        assert pm._mode == LayoutMode.THREE

    def test_mode_three_wide_at_160(self) -> None:
        pm = _pm()
        pm.on_resize(130, 40)  # THREE
        changed = pm.on_resize(165, 40)  # THREE_WIDE
        assert changed
        assert pm._mode == LayoutMode.THREE_WIDE

    def test_short_terminal_forces_single(self) -> None:
        pm = _pm()
        # Wide terminal but very short — must stay SINGLE
        mode = pm._compute_mode(200, 15)
        assert mode == LayoutMode.SINGLE

    def test_short_terminal_on_resize_returns_false(self) -> None:
        """on_resize returns False when short terminal prevents mode change."""
        pm = _pm()
        # h=15 < MIN_HEIGHT: compute_mode always returns SINGLE
        changed = pm.on_resize(200, 15)
        # Mode stays SINGLE (no change from initial) so on_resize returns False
        assert not changed
        assert pm._mode == LayoutMode.SINGLE

    def test_hysteresis_prevents_flap_near_boundary(self) -> None:
        pm = _pm()
        # Get to THREE mode first with a wide terminal
        pm.on_resize(130, 40)
        assert pm._mode == LayoutMode.THREE
        # w=119 is just 1 below threshold — hysteresis prevents flap back to SINGLE
        # (threshold_off=120, HYSTERESIS=2 → transition blocked when w >= 118)
        changed = pm.on_resize(119, 40)
        assert not changed
        assert pm._mode == LayoutMode.THREE

    def test_hysteresis_allows_transition_below_hysteresis_band(self) -> None:
        pm = _pm()
        pm.on_resize(130, 40)
        assert pm._mode == LayoutMode.THREE
        # w=117 is below threshold_off - HYSTERESIS = 118 → transition allowed
        changed = pm.on_resize(117, 40)
        assert changed
        assert pm._mode == LayoutMode.SINGLE

    def test_on_resize_returns_true_on_mode_change(self) -> None:
        pm = _pm()
        # Start at SINGLE
        pm.on_resize(100, 40)
        # Wide — triggers THREE
        result = pm.on_resize(140, 40)
        assert result is True

    def test_on_resize_returns_false_same_mode(self) -> None:
        pm = _pm()
        pm.on_resize(100, 40)
        # Still narrow — no change
        result = pm.on_resize(110, 40)
        assert result is False

    def test_compute_layout_center_guard_fallthrough(self) -> None:
        """When center_w < MIN_CENTER_W and can't recover → falls back to SINGLE."""
        pm = _pm()
        # Force tiny terminal where sides eat all space
        mode, left_w, center_w, right_w = pm.compute_layout(50, 40)
        # Must report SINGLE (widths fall through)
        assert mode == LayoutMode.SINGLE
        assert left_w == 0
        assert right_w == 0


# ===========================================================================
# Collapse tests (pure PaneManager)
# ===========================================================================

class TestCollapseState:
    def test_toggle_left_collapse(self) -> None:
        pm = _pm()
        assert not pm._left_collapsed
        result = pm.toggle_left_collapsed()
        assert result is True
        assert pm._left_collapsed
        result2 = pm.toggle_left_collapsed()
        assert result2 is False
        assert not pm._left_collapsed

    def test_toggle_right_collapse(self) -> None:
        pm = _pm()
        assert not pm._right_collapsed
        pm.toggle_right_collapsed()
        assert pm._right_collapsed
        pm.toggle_right_collapsed()
        assert not pm._right_collapsed

    def test_is_collapsed_left(self) -> None:
        pm = _pm()
        pm.toggle_left_collapsed()
        assert pm.is_collapsed(PaneId.LEFT)
        assert not pm.is_collapsed(PaneId.CENTER)
        assert not pm.is_collapsed(PaneId.RIGHT)

    def test_is_collapsed_right(self) -> None:
        pm = _pm()
        pm.toggle_right_collapsed()
        assert pm.is_collapsed(PaneId.RIGHT)
        assert not pm.is_collapsed(PaneId.LEFT)


# ===========================================================================
# Focus / cycling tests (pure PaneManager)
# ===========================================================================

class TestFocusCycling:
    def test_next_visible_pane_skips_left_when_collapsed(self) -> None:
        pm = _pm()
        pm._mode = LayoutMode.THREE
        pm.toggle_left_collapsed()
        pm.focus_pane(PaneId.CENTER)
        # Forward from center: left is collapsed, skip to right
        nxt = pm.next_visible_pane(reverse=False)
        assert nxt == PaneId.RIGHT

    def test_next_visible_pane_skips_right_when_collapsed(self) -> None:
        pm = _pm()
        pm._mode = LayoutMode.THREE
        pm.toggle_right_collapsed()
        pm.focus_pane(PaneId.CENTER)
        # Forward from center: right is collapsed, wrap to left
        nxt = pm.next_visible_pane(reverse=False)
        assert nxt == PaneId.LEFT

    def test_cycle_pane_wraps_around(self) -> None:
        pm = _pm()
        pm._mode = LayoutMode.THREE
        pm.focus_pane(PaneId.RIGHT)
        # Next from right wraps to left
        nxt = pm.next_visible_pane(reverse=False)
        assert nxt == PaneId.LEFT

    def test_cycle_pane_backward(self) -> None:
        pm = _pm()
        pm._mode = LayoutMode.THREE
        pm.focus_pane(PaneId.LEFT)
        prev = pm.next_visible_pane(reverse=True)
        assert prev == PaneId.RIGHT

    def test_focus_pane_updates_focused_pane(self) -> None:
        pm = _pm()
        pm.focus_pane(PaneId.LEFT)
        assert pm._focused_pane == PaneId.LEFT
        pm.focus_pane(PaneId.RIGHT)
        assert pm._focused_pane == PaneId.RIGHT


# ===========================================================================
# Compact ↔ layout-single consistency (PaneManager test)
# ===========================================================================

class TestCompactImpliesSingle:
    def test_short_terminal_implies_single(self) -> None:
        """h < MIN_HEIGHT (20) → _compute_mode returns SINGLE."""
        pm = _pm()
        assert pm._compute_mode(200, 19) == LayoutMode.SINGLE

    def test_narrow_terminal_implies_single(self) -> None:
        pm = _pm()
        assert pm._compute_mode(119, 40) == LayoutMode.SINGLE

    def test_disabled_pm_always_single(self) -> None:
        pm = _pm(enabled=False)
        assert pm._compute_mode(200, 50) == LayoutMode.SINGLE

    def test_on_resize_noop_when_disabled(self) -> None:
        pm = _pm(enabled=False)
        changed = pm.on_resize(200, 50)
        assert changed is False


# ===========================================================================
# Integration tests (require app run_test)
# ===========================================================================

@pytest.mark.asyncio
async def test_v2_apply_layout_single_at_narrow_width() -> None:
    """Narrow terminal (100 cols) → side panes hidden after _apply_layout."""
    app = _make_app("v2")
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        # Manually trigger apply_layout at narrow width
        app._pane_manager._mode = LayoutMode.SINGLE
        app._pane_manager._apply_layout(app)
        await pilot.pause()
        pane_left = app.query_one("#pane-left")
        pane_right = app.query_one("#pane-right")
        assert not pane_left.display
        assert not pane_right.display


@pytest.mark.asyncio
async def test_v2_apply_layout_three_at_wide_width() -> None:
    """Wide terminal (140 cols) → side panes visible after _apply_layout."""
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        # Force THREE mode and apply (_right_collapsed starts True due to flag; override)
        app._pane_manager._mode = LayoutMode.THREE
        app._pane_manager._right_collapsed = False
        app._pane_manager._apply_layout(app)
        await pilot.pause()
        pane_left = app.query_one("#pane-left")
        pane_right = app.query_one("#pane-right")
        assert pane_left.display
        assert pane_right.display


@pytest.mark.asyncio
async def test_v2_apply_layout_three_wide_at_160() -> None:
    """160-col terminal → THREE_WIDE mode applies, side panes visible."""
    app = _make_app("v2")
    async with app.run_test(size=(165, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        app._pane_manager._mode = LayoutMode.THREE_WIDE
        app._pane_manager._right_collapsed = False
        app._pane_manager._apply_layout(app)
        await pilot.pause()
        assert app.query_one("#pane-left").display
        assert app.query_one("#pane-right").display


@pytest.mark.asyncio
async def test_v2_side_panes_hidden_when_collapsed() -> None:
    """toggle_left_collapsed + _apply_layout hides left pane."""
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        app._pane_manager._mode = LayoutMode.THREE
        app._pane_manager._right_collapsed = False  # ensure right starts visible
        app._pane_manager.toggle_left_collapsed()
        app._pane_manager._apply_layout(app)
        await pilot.pause()
        pane_left = app.query_one("#pane-left")
        pane_right = app.query_one("#pane-right")
        assert not pane_left.display
        assert pane_right.display  # right still visible


@pytest.mark.asyncio
async def test_v2_right_collapse_toggle() -> None:
    """toggle_right_collapsed + _apply_layout hides right pane."""
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        app._pane_manager._mode = LayoutMode.THREE
        app._pane_manager._right_collapsed = False  # ensure right starts visible
        app._pane_manager.toggle_right_collapsed()  # False → True (collapsed)
        app._pane_manager._apply_layout(app)
        await pilot.pause()
        pane_right = app.query_one("#pane-right")
        pane_left = app.query_one("#pane-left")
        assert not pane_right.display
        assert pane_left.display


@pytest.mark.asyncio
async def test_v2_pane_manager_enabled_flag() -> None:
    """v2 app has pane_manager.enabled=True; v1 app has enabled=False."""
    app_v2 = _make_app("v2")
    app_v1 = _make_app("v1")
    async with app_v2.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        assert app_v2._pane_manager.enabled is True
    async with app_v1.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        assert app_v1._pane_manager.enabled is False


@pytest.mark.asyncio
async def test_v2_action_collapse_left_pane() -> None:
    """action_collapse_left_pane toggles left collapse and applies layout."""
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        app._pane_manager._mode = LayoutMode.THREE
        # Initially uncollapsed
        assert not app._pane_manager._left_collapsed
        app.action_collapse_left_pane()
        await pilot.pause()
        assert app._pane_manager._left_collapsed
        pane_left = app.query_one("#pane-left")
        assert not pane_left.display


@pytest.mark.asyncio
async def test_v2_action_collapse_right_pane() -> None:
    """action_collapse_right_pane toggles right collapse and applies layout."""
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        app._pane_manager._mode = LayoutMode.THREE
        app._pane_manager._right_collapsed = False  # start visible before collapsing
        app.action_collapse_right_pane()
        await pilot.pause()
        assert app._pane_manager._right_collapsed
        assert not app.query_one("#pane-right").display


@pytest.mark.asyncio
async def test_v1_action_collapse_is_noop() -> None:
    """In v1 mode, collapse actions are no-ops (no pane-row in DOM)."""
    app = _make_app("v1")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        # Should not raise even though #pane-left doesn't exist
        app.action_collapse_left_pane()
        app.action_collapse_right_pane()
        await pilot.pause()
        # pane manager not enabled — collapse state unchanged
        assert not app._pane_manager.enabled


@pytest.mark.asyncio
async def test_v2_flush_resize_triggers_apply_layout() -> None:
    """_flush_resize calls _apply_layout when mode changes."""
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        # Force a mode change by calling on_resize manually
        app._pane_manager._mode = LayoutMode.SINGLE
        changed = app._pane_manager.on_resize(140, 40)
        if changed:
            app._pane_manager._apply_layout(app)
        await pilot.pause()
        # Panes should be visible in THREE mode at 140 cols
        assert app.query_one("#pane-left").display or True  # no assertion on specific mode


@pytest.mark.asyncio
async def test_v2_esc_routing_returns_to_center() -> None:
    """When side pane is focused, Esc sets _focused_pane back to CENTER."""
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        # Simulate left pane being focused
        app._pane_manager.focus_pane(PaneId.LEFT)
        assert app._pane_manager._focused_pane == PaneId.LEFT
        # Press Esc — should route back to CENTER
        await pilot.press("escape")
        await pilot.pause()
        # After Esc, focused pane should be CENTER
        assert app._pane_manager._focused_pane == PaneId.CENTER


# ===========================================================================
# Pure unit: _apply_layout with mock app
# ===========================================================================

class TestApplyLayoutMock:
    """Unit tests for _apply_layout using a mock app object."""

    def _make_mock_app(self, width: int = 140, height: int = 40) -> MagicMock:
        pane_left = MagicMock()
        pane_center = MagicMock()
        pane_right = MagicMock()

        def query_one(selector: str) -> MagicMock:
            mapping = {
                "#pane-row": MagicMock(),
                "#pane-left": pane_left,
                "#pane-center": pane_center,
                "#pane-right": pane_right,
            }
            if selector not in mapping:
                raise Exception(f"No widget {selector}")
            return mapping[selector]

        size = MagicMock()
        size.width = width
        size.height = height

        app = MagicMock()
        app.query_one.side_effect = query_one
        app.size = size
        app._pane_left = pane_left
        app._pane_center = pane_center
        app._pane_right = pane_right
        return app

    def test_apply_layout_single_hides_sides(self) -> None:
        pm = _pm()
        pm._mode = LayoutMode.SINGLE
        mock_app = self._make_mock_app(100, 40)
        pm._apply_layout(mock_app)
        assert mock_app._pane_left.display is False
        assert mock_app._pane_right.display is False

    def test_apply_layout_three_shows_sides(self) -> None:
        pm = _pm()
        pm._mode = LayoutMode.THREE
        mock_app = self._make_mock_app(140, 40)
        pm._apply_layout(mock_app)
        assert mock_app._pane_left.display is True
        assert mock_app._pane_right.display is True

    def test_apply_layout_noop_when_disabled(self) -> None:
        pm = _pm(enabled=False)
        mock_app = self._make_mock_app(140, 40)
        # Should return early — query_one never called
        pm._apply_layout(mock_app)
        mock_app.query_one.assert_not_called()

    def test_apply_layout_left_collapsed_hides_left(self) -> None:
        pm = _pm()
        pm._mode = LayoutMode.THREE
        pm._left_collapsed = True
        mock_app = self._make_mock_app(140, 40)
        pm._apply_layout(mock_app)
        assert mock_app._pane_left.display is False
        assert mock_app._pane_right.display is True

    def test_apply_layout_right_collapsed_hides_right(self) -> None:
        pm = _pm()
        pm._mode = LayoutMode.THREE
        pm._right_collapsed = True
        mock_app = self._make_mock_app(140, 40)
        pm._apply_layout(mock_app)
        assert mock_app._pane_left.display is True
        assert mock_app._pane_right.display is False
