"""F3: depth class clamped to 3 for both SubAgentPanel and ChildPanel."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from hermes_cli.tui.sub_agent_panel import SubAgentPanel
from hermes_cli.tui.child_panel import ChildPanel


@pytest.mark.parametrize("depth,expected", [
    (1, "--depth-1"),
    (2, "--depth-2"),
    (3, "--depth-3"),
    (4, "--depth-3"),  # clamped
    (10, "--depth-3"),  # clamped
])
@pytest.mark.asyncio
async def test_subagent_panel_depth_clamp(depth: int, expected: str):
    class _App(App):
        def compose(self) -> ComposeResult:
            yield SubAgentPanel(depth=depth)

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(SubAgentPanel)
        assert panel.has_class(expected)
        # Ensure no unclamped class exists when depth > 3
        if depth > 3:
            assert not panel.has_class(f"--depth-{depth}")


@pytest.mark.parametrize("depth,expected", [
    (1, "--depth-1"),
    (3, "--depth-3"),
    (5, "--depth-3"),  # clamped
])
@pytest.mark.asyncio
async def test_child_panel_depth_clamp(depth: int, expected: str):
    class _App(App):
        def compose(self) -> ComposeResult:
            yield ChildPanel(block=Static("body"), tool_name="Bash", depth=depth)

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ChildPanel)
        assert panel.has_class(expected)
        if depth > 3:
            assert not panel.has_class(f"--depth-{depth}")
