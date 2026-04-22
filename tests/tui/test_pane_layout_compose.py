"""Phase 2 — R2 pane layout compose tests.

Covers:
- v1 mode: no #pane-row, OutputPanel direct child of screen
- v2 mode: #pane-row Horizontal with 3 PaneContainers
- OutputPanel mounted into center pane
- Stubs in left/right panes
- layout-v2 CSS class applied
- PaneManager.enabled flag
- All existing overlays/widgets still present
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets.pane_container import PaneContainer
from hermes_cli.tui.widgets.plan_panel_stub import PlanPanelStub
from hermes_cli.tui.widgets.context_panel_stub import ContextPanelStub
from hermes_cli.tui.pane_manager import PaneId, PaneManager
from hermes_cli.tui.widgets import OutputPanel, StatusBar


def _make_app(layout: str = "v1") -> HermesApp:
    """Create a HermesApp with the given layout mode."""
    cli = MagicMock()
    cli._cfg = {"display": {"layout": layout}}
    cli.agent = MagicMock()
    cli.agent.model = "claude-sonnet-4-6"
    app = HermesApp(cli=cli)
    return app


# ---------------------------------------------------------------------------
# v1 mode — no pane-row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v1_compose_has_no_pane_row():
    app = _make_app("v1")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        from textual.css.query import NoMatches
        try:
            pane_row = app.query_one("#pane-row")
            # If it exists at all it must be display:none (hidden)
            assert not pane_row.display
        except NoMatches:
            pass  # Not in DOM at all — also fine


@pytest.mark.asyncio
async def test_v1_output_panel_is_present():
    app = _make_app("v1")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        # OutputPanel must be queryable
        op = app.query_one(OutputPanel)
        assert op is not None


@pytest.mark.asyncio
async def test_v1_no_layout_class():
    app = _make_app("v1")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        assert not app.has_class("layout-v2")


@pytest.mark.asyncio
async def test_v1_pane_manager_disabled():
    app = _make_app("v1")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        assert app._pane_manager.enabled is False


@pytest.mark.asyncio
async def test_v1_no_pane_containers():
    app = _make_app("v1")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        containers = app.query(PaneContainer)
        assert len(containers) == 0


# ---------------------------------------------------------------------------
# v2 mode — pane-row with 3 containers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v2_compose_has_pane_row():
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        pane_row = app.query_one("#pane-row")
        assert pane_row is not None


@pytest.mark.asyncio
async def test_v2_three_pane_containers():
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        containers = app.query(PaneContainer)
        assert len(containers) == 3


@pytest.mark.asyncio
async def test_pane_container_ids():
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        ids = {c.id for c in app.query(PaneContainer)}
        assert ids == {"pane-left", "pane-center", "pane-right"}


@pytest.mark.asyncio
async def test_v2_pane_left_exists():
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        pane = app.query_one("#pane-left")
        assert isinstance(pane, PaneContainer)


@pytest.mark.asyncio
async def test_v2_pane_center_exists():
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        pane = app.query_one("#pane-center")
        assert isinstance(pane, PaneContainer)


@pytest.mark.asyncio
async def test_v2_pane_right_exists():
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        pane = app.query_one("#pane-right")
        assert isinstance(pane, PaneContainer)


@pytest.mark.asyncio
async def test_v2_output_panel_in_center_pane():
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        pane_center = app.query_one("#pane-center")
        op = app.query_one(OutputPanel)
        assert op.parent is pane_center


@pytest.mark.asyncio
async def test_v2_output_panel_queryable():
    """Same OutputPanel instance must be queryable after v2 reparenting."""
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        op = app.query_one(OutputPanel)
        assert op is app._output_panel


@pytest.mark.asyncio
async def test_v2_plan_stub_in_left_pane():
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        pane_left = app.query_one("#pane-left")
        stubs = pane_left.query(PlanPanelStub)
        assert len(stubs) == 1


@pytest.mark.asyncio
async def test_v2_context_stub_in_right_pane():
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        pane_right = app.query_one("#pane-right")
        stubs = pane_right.query(ContextPanelStub)
        assert len(stubs) == 1


@pytest.mark.asyncio
async def test_v2_layout_class_added():
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        assert app.has_class("layout-v2")


@pytest.mark.asyncio
async def test_v2_pane_manager_enabled():
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        assert app._pane_manager.enabled is True


# ---------------------------------------------------------------------------
# v2 — all core overlays/widgets still present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v2_input_row_exists():
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        input_row = app.query_one("#input-row")
        assert input_row is not None


@pytest.mark.asyncio
async def test_v2_status_bar_exists():
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        sb = app.query_one(StatusBar)
        assert sb is not None


@pytest.mark.asyncio
async def test_v2_hint_bar_exists():
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        from hermes_cli.tui.widgets import HintBar
        hb = app.query_one(HintBar)
        assert hb is not None


@pytest.mark.asyncio
async def test_v2_voice_status_bar_exists():
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        from hermes_cli.tui.widgets import VoiceStatusBar
        vsb = app.query_one(VoiceStatusBar)
        assert vsb is not None


@pytest.mark.asyncio
async def test_v2_all_overlays_present():
    """All 16 named overlays must still be in the DOM in v2 mode."""
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        overlay_ids = [
            "clarify", "approval", "sudo", "secret", "undo-confirm",
            "history-search", "keymap-help", "help-overlay", "usage-overlay",
            "commands-overlay", "workspace-overlay", "session-overlay",
            "new-session-overlay", "merge-confirm-overlay",
            "model-picker-overlay", "reasoning-picker-overlay",
        ]
        for oid in overlay_ids:
            widget = app.query_one(f"#{oid}")
            assert widget is not None, f"#{oid} missing in v2 compose"


@pytest.mark.asyncio
async def test_v2_tte_widget_exists():
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        from hermes_cli.tui.widgets import TTEWidget
        tte = app.query_one(TTEWidget)
        assert tte is not None


@pytest.mark.asyncio
async def test_v2_input_area_exists():
    app = _make_app("v2")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        inp = app.query_one("#input-area")
        assert inp is not None


# ---------------------------------------------------------------------------
# v2 at smaller terminal size — layout still activates (responsive in Phase 3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v2_small_terminal_still_has_pane_row():
    """Phase 2: v2 layout flag always activates pane-row regardless of width."""
    app = _make_app("v2")
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        pane_row = app.query_one("#pane-row")
        assert pane_row is not None


@pytest.mark.asyncio
async def test_v2_small_terminal_layout_class_present():
    app = _make_app("v2")
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        assert app.has_class("layout-v2")


@pytest.mark.asyncio
async def test_v2_small_terminal_three_containers():
    app = _make_app("v2")
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        containers = app.query(PaneContainer)
        assert len(containers) == 3


# ---------------------------------------------------------------------------
# PaneManager construction correctness
# ---------------------------------------------------------------------------


def test_pane_manager_v2_enabled_via_display_cfg():
    pm = PaneManager(cfg={"layout": "v2"})
    assert pm.enabled is True


def test_pane_manager_v1_disabled_via_display_cfg():
    pm = PaneManager(cfg={"layout": "v1"})
    assert pm.enabled is False


def test_pane_manager_default_disabled():
    pm = PaneManager(cfg={})
    assert pm.enabled is False


# ---------------------------------------------------------------------------
# PaneContainer set_content smoke test (no app needed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pane_container_set_content_mounts_widget():
    """set_content() mounts the widget as a child."""
    from textual.app import App, ComposeResult
    from textual.widgets import Static

    class _TestApp(App):
        def compose(self) -> ComposeResult:
            yield PaneContainer(pane_id=PaneId.CENTER, id="pc")

    async with _TestApp().run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        pc = pilot.app.query_one("#pc", PaneContainer)
        label = Static("hello", id="test-label")
        pc.set_content(label)
        await pilot.pause()
        found = pc.query_one("#test-label")
        assert found is label
