"""P1 — v2 pane layout PlanPanel wiring tests.

Covers:
- PlanPanel in left pane (not stub)
- No bottom-docked duplicate
- planned_calls reactive reaches the left-pane PlanPanel
- ContextPanelStub still in right pane
- Exception in wiring block logs via logger.exception
- Non-v2 layout still bottom-docks PlanPanel
- plan_panel_stub module deleted
- CSS override present
"""
from __future__ import annotations

import os
import pathlib
import re

import pytest

os.environ.setdefault("HERMES_DETERMINISTIC", "1")
from unittest.mock import MagicMock, patch
from textual.css.query import NoMatches

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.plan_types import PlanState
from hermes_cli.tui.widgets.plan_panel import PlanPanel
from hermes_cli.tui.widgets.context_panel_stub import ContextPanelStub


def _make_app(layout: str = "v1") -> HermesApp:
    """Mirror of test_pane_layout_compose._make_app."""
    cli = MagicMock()
    cli._cfg = {"display": {"layout": layout}}
    cli.agent = MagicMock()
    cli.agent.model = "claude-sonnet-4-6"
    app = HermesApp(cli=cli)
    return app


class TestV2LayoutPlanPanel:
    pytestmark = pytest.mark.asyncio

    async def test_v2_left_pane_has_plan_panel(self):
        app = _make_app("v2")
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            assert len(app.query_one("#pane-left").query(PlanPanel)) == 1

    async def test_v2_left_pane_not_stub(self):
        app = _make_app("v2")
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            pane_left = app.query_one("#pane-left")
            assert not any(
                type(w).__name__ == "PlanPanelStub"
                for w in pane_left.walk_children()
            )

    async def test_v2_no_bottom_docked_plan_panel(self):
        app = _make_app("v2")
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            assert len(app.query("#plan-panel")) == 1

    async def test_v2_no_bottom_docked_plan_panel_location(self):
        app = _make_app("v2")
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            # Should not raise — the one #plan-panel is inside #pane-left
            app.query_one("#pane-left").query_one("#plan-panel")

    async def test_v2_compose_no_free_plan_panel(self):
        app = _make_app("v2")
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            # PlanPanel's parent is a PaneContainer, not the Screen
            assert app.query_one("#plan-panel").parent is not app.screen

    async def test_v2_plan_panel_id_is_plan_panel(self):
        app = _make_app("v2")
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            assert app.query_one("#pane-left").query_one(PlanPanel).id == "plan-panel"

    async def test_v2_planned_calls_reactive_reaches_panel(self):
        # Use PENDING state to avoid _NowSection.show_call which starts a
        # set_interval timer that prevents pilot.pause() from completing.
        app = _make_app("v2")
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            mock_call = MagicMock()
            mock_call.state = PlanState.PENDING
            mock_call.depth = 0
            mock_call.label = "test_tool"
            mock_call.tool_call_id = "tc-1"
            app.planned_calls = [mock_call]
            await pilot.pause()
            await pilot.pause()
            assert app.query_one("#plan-panel", PlanPanel).has_class("--active")

    async def test_v2_right_pane_has_context_stub(self):
        app = _make_app("v2")
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            assert len(app.query_one("#pane-right").query(ContextPanelStub)) == 1

    async def test_v2_wiring_exception_logs(self):
        app = _make_app("v2")
        _real_qo = app.query_one

        def _raise_on_pane_left(selector, *a, **kw):
            if "#pane-left" in str(selector):
                raise NoMatches(selector)
            return _real_qo(selector, *a, **kw)

        with patch.object(app, "query_one", side_effect=_raise_on_pane_left), \
             patch("hermes_cli.tui.app.logger") as mock_logger:
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                # completes without raising = app did not crash
        mock_logger.exception.assert_called_once_with("v2 pane wiring failed")


class TestNonV2Layout:
    pytestmark = pytest.mark.asyncio

    async def test_non_v2_bottom_docked_plan_panel(self):
        app = _make_app("v1")
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            assert isinstance(app.query_one("#plan-panel"), PlanPanel)
            assert app.query_one("#plan-panel").parent is app.screen

    async def test_non_v2_compose_yields_plan_panel(self):
        app = _make_app("v1")
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            assert len(app.query("#plan-panel")) == 1
            assert app.query_one("#plan-panel").parent is app.screen


class TestDeletedStub:
    def test_plan_panel_stub_module_absent(self):
        import importlib
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("hermes_cli.tui.widgets.plan_panel_stub")

    def test_context_panel_stub_still_present(self):
        import importlib
        mod = importlib.import_module("hermes_cli.tui.widgets.context_panel_stub")
        assert mod is not None


class TestCSSOverride:
    def test_v2_pane_left_plan_panel_no_dock(self):
        css_path = (
            pathlib.Path(__file__).parent.parent.parent
            / "hermes_cli" / "tui" / "hermes.tcss"
        )
        css = css_path.read_text()
        assert re.search(
            r"layout-v2 #pane-left PlanPanel\s*\{[^}]*dock:\s*none",
            css, re.DOTALL
        ) is not None
        assert re.search(
            r"layout-v2 #pane-left PlanPanel\s*\{[^}]*height:\s*1fr",
            css, re.DOTALL
        ) is not None
        assert re.search(
            r"layout-v2 #pane-left PlanPanel\s*\{[^}]*max-height:\s*100%",
            css, re.DOTALL
        ) is not None
