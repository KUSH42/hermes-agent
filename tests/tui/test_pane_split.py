"""Phase 5 — R2 panes center-split tests.

Covers:
- PaneManager.toggle_center_split / apply_center_split (unit)
- dump_state / load_state for center_split (unit)
- SplitTargetStub DOM presence and initial hidden state (integration)
- action_toggle_center_split toggles stub visibility and CSS class (integration)
- v1 mode: action is a no-op, stub not in DOM (integration)
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from hermes_cli.tui.pane_manager import PaneManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pm(center_split: bool = False) -> PaneManager:
    cfg: dict = {"layout": "v2"}
    if center_split:
        cfg["layout_v2"] = {"center_split_enabled": True}
    return PaneManager(cfg=cfg)


def _make_app(layout: str = "v2") -> "HermesApp":
    from hermes_cli.tui.app import HermesApp
    cli = MagicMock()
    cli._cfg = {"display": {"layout": layout}}
    cli.agent = MagicMock()
    cli.agent.model = "claude-sonnet-4-6"
    return HermesApp(cli=cli)


# ---------------------------------------------------------------------------
# Unit tests — PaneManager (no Textual app needed)
# ---------------------------------------------------------------------------

class TestToggleCenterSplit:
    def test_toggle_center_split_false_to_true(self) -> None:
        pm = _make_pm()
        assert pm._center_split is False
        result = pm.toggle_center_split()
        assert result is True
        assert pm._center_split is True

    def test_toggle_center_split_true_to_false(self) -> None:
        pm = _make_pm()
        pm.toggle_center_split()
        result = pm.toggle_center_split()
        assert result is False
        assert pm._center_split is False

    def test_toggle_returns_new_state(self) -> None:
        pm = _make_pm()
        for _ in range(4):
            before = pm._center_split
            returned = pm.toggle_center_split()
            assert returned == (not before)


class TestDumpLoadCenterSplit:
    def test_dump_state_includes_center_split_false(self) -> None:
        pm = _make_pm()
        state = pm.dump_state()
        assert "center_split" in state
        assert state["center_split"] is False

    def test_dump_state_includes_center_split_true(self) -> None:
        pm = _make_pm()
        pm.toggle_center_split()
        state = pm.dump_state()
        assert state["center_split"] is True

    def test_load_state_restores_center_split_true(self) -> None:
        pm = _make_pm()
        pm.load_state({"center_split": True})
        assert pm._center_split is True

    def test_load_state_restores_center_split_false(self) -> None:
        pm = _make_pm(center_split=True)
        pm.load_state({"center_split": False})
        assert pm._center_split is False

    def test_roundtrip_center_split_true(self) -> None:
        pm = _make_pm()
        pm.toggle_center_split()
        state = pm.dump_state()
        pm2 = _make_pm()
        pm2.load_state(state)
        assert pm2._center_split is True

    def test_roundtrip_center_split_false(self) -> None:
        pm = _make_pm(center_split=True)
        pm.toggle_center_split()  # → False
        state = pm.dump_state()
        pm2 = _make_pm(center_split=True)
        pm2.load_state(state)
        assert pm2._center_split is False

    def test_split_state_load_state_preserves_on_second_call(self) -> None:
        pm = _make_pm()
        pm.toggle_center_split()
        pm.load_state(pm.dump_state())
        assert pm._center_split is True


# ---------------------------------------------------------------------------
# Integration tests — Textual app
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_split_stub_initially_hidden() -> None:
    """SplitTargetStub is in DOM but display=False in v2 mode."""
    app = _make_app("v2")
    async with app.run_test(size=(180, 40)) as pilot:
        await pilot.pause()
        stub = app.query_one("#split-target-stub")
        assert stub is not None
        assert stub.display is False


@pytest.mark.asyncio
async def test_action_toggle_center_split_shows_stub() -> None:
    """action_toggle_center_split makes the stub visible."""
    app = _make_app("v2")
    async with app.run_test(size=(180, 40)) as pilot:
        await pilot.pause()
        app.action_toggle_center_split()
        await pilot.pause()
        stub = app.query_one("#split-target-stub")
        assert stub.display is True


@pytest.mark.asyncio
async def test_action_toggle_twice_hides_stub() -> None:
    """Toggling twice returns stub to hidden state."""
    app = _make_app("v2")
    async with app.run_test(size=(180, 40)) as pilot:
        await pilot.pause()
        app.action_toggle_center_split()
        await pilot.pause()
        app.action_toggle_center_split()
        await pilot.pause()
        stub = app.query_one("#split-target-stub")
        assert stub.display is False


@pytest.mark.asyncio
async def test_pane_center_gets_split_class() -> None:
    """After toggle, #pane-center gains CSS class '--split'."""
    app = _make_app("v2")
    async with app.run_test(size=(180, 40)) as pilot:
        await pilot.pause()
        app.action_toggle_center_split()
        await pilot.pause()
        pane_center = app.query_one("#pane-center")
        assert pane_center.has_class("--split")


@pytest.mark.asyncio
async def test_pane_center_loses_split_class_on_second_toggle() -> None:
    """After two toggles, #pane-center loses '--split' class."""
    app = _make_app("v2")
    async with app.run_test(size=(180, 40)) as pilot:
        await pilot.pause()
        app.action_toggle_center_split()
        await pilot.pause()
        app.action_toggle_center_split()
        await pilot.pause()
        pane_center = app.query_one("#pane-center")
        assert not pane_center.has_class("--split")


@pytest.mark.asyncio
async def test_split_persists_to_dump_state() -> None:
    """After toggle, dump_state reflects center_split=True."""
    app = _make_app("v2")
    async with app.run_test(size=(180, 40)) as pilot:
        await pilot.pause()
        app.action_toggle_center_split()
        await pilot.pause()
        state = app._pane_manager.dump_state()
        assert state["center_split"] is True


@pytest.mark.asyncio
async def test_split_not_available_in_v1() -> None:
    """v1 mode: action_toggle_center_split is a no-op; stub not in DOM."""
    app = _make_app("v1")
    async with app.run_test(size=(180, 40)) as pilot:
        await pilot.pause()
        # Should not raise
        app.action_toggle_center_split()
        await pilot.pause()
        # No stub in v1 DOM
        from textual.css.query import NoMatches
        with pytest.raises(NoMatches):
            app.query_one("#split-target-stub")
        # pane manager disabled, center_split unchanged
        assert app._pane_manager._center_split is False
