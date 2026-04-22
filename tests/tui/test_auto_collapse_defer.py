"""B1: _apply_complete_auto_collapse defers when user is scrolled up."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from hermes_cli.tui.tool_panel import ToolPanel


@pytest.mark.asyncio
async def test_should_auto_collapse_flag_initialized():
    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanel(block=Static("body"), tool_name="Bash")

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        assert hasattr(panel, "_should_auto_collapse")
        assert panel._should_auto_collapse is False


@pytest.mark.asyncio
async def test_defer_when_user_override():
    """If _user_collapse_override is True, collapse is skipped immediately."""
    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanel(block=Static("body"), tool_name="Bash")

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        panel._user_collapse_override = True
        original_collapsed = panel.collapsed
        panel._apply_complete_auto_collapse()
        await pilot.pause()
        # collapsed unchanged, no _should_auto_collapse set
        assert panel.collapsed == original_collapsed
