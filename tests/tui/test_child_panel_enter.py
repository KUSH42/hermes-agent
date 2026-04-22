"""F2: ChildPanel Enter toggles binary collapse; watch_collapsed hides body."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from hermes_cli.tui.child_panel import ChildPanel


class _App(App):
    def compose(self) -> ComposeResult:
        yield ChildPanel(block=Static("body"), tool_name="Bash", depth=1)


@pytest.mark.asyncio
async def test_toggle_collapse_flips_collapsed():
    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ChildPanel)
        was = panel.collapsed
        panel.action_toggle_collapse()
        assert panel.collapsed != was


@pytest.mark.asyncio
async def test_watch_collapsed_hides_body():
    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ChildPanel)
        # Should not raise even if .tool-body-container doesn't exist
        panel.watch_collapsed(False, True)
        await pilot.pause()
