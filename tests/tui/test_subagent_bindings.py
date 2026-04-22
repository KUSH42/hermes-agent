"""F1: Space toggles EXPANDED↔COLLAPSED; c toggles EXPANDED↔COMPACT."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from hermes_cli.tui.sub_agent_panel import SubAgentPanel, CollapseState


class _App(App):
    def compose(self) -> ComposeResult:
        yield SubAgentPanel(depth=0)


@pytest.mark.asyncio
async def test_space_expands_collapsed():
    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(SubAgentPanel)
        panel.collapse_state = CollapseState.COLLAPSED
        panel.action_toggle_collapse()
        assert panel.collapse_state == CollapseState.EXPANDED


@pytest.mark.asyncio
async def test_space_collapses_expanded():
    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(SubAgentPanel)
        panel.collapse_state = CollapseState.EXPANDED
        panel.action_toggle_collapse()
        assert panel.collapse_state == CollapseState.COLLAPSED


@pytest.mark.asyncio
async def test_space_collapses_from_compact():
    """Space on COMPACT → COLLAPSED (not EXPANDED)."""
    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(SubAgentPanel)
        panel.collapse_state = CollapseState.COMPACT
        panel.action_toggle_collapse()
        assert panel.collapse_state == CollapseState.COLLAPSED


@pytest.mark.asyncio
async def test_c_toggles_compact():
    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(SubAgentPanel)
        panel.collapse_state = CollapseState.EXPANDED
        panel.action_toggle_compact()
        assert panel.collapse_state == CollapseState.COMPACT
        panel.action_toggle_compact()
        assert panel.collapse_state == CollapseState.EXPANDED
