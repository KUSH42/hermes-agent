"""F1: Space toggles collapsed bool on SubAgentPanel (binary model, D3)."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from hermes_cli.tui.sub_agent_panel import SubAgentPanel


class _App(App):
    def compose(self) -> ComposeResult:
        yield SubAgentPanel(depth=0)


@pytest.mark.asyncio
async def test_space_expands_collapsed():
    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(SubAgentPanel)
        panel.collapsed = True
        panel.action_toggle_collapse()
        assert panel.collapsed is False


@pytest.mark.asyncio
async def test_space_collapses_expanded():
    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(SubAgentPanel)
        panel.collapsed = False
        panel.action_toggle_collapse()
        assert panel.collapsed is True


@pytest.mark.asyncio
async def test_collapse_subtree_sets_collapsed():
    """action_collapse_subtree forces collapsed=True."""
    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(SubAgentPanel)
        panel.collapsed = False
        panel.action_collapse_subtree()
        assert panel.collapsed is True
