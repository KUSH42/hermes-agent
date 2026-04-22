"""A2: chips serve only from FooterPane; header._header_chips always empty."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from textual.app import App, ComposeResult
from textual.widgets import Static

from hermes_cli.tui.tool_result_parse import ResultSummaryV4, Chip
from hermes_cli.tui.tool_panel import ToolPanel


def _summary_with_chips():
    return ResultSummaryV4(
        primary="ok",
        exit_code=0,
        chips=(Chip(text="myChip", kind="exit", tone="ok"),),
        stderr_tail="",
        actions=(),
        artifacts=(),
        is_error=False,
    )


@pytest.mark.asyncio
async def test_chips_not_in_header():
    """After set_result_summary, header._header_chips is always []."""
    fake_header = MagicMock()
    fake_header._header_chips = [("old chip", "dim")]  # pre-existing

    class FakeBlock(Static):
        _header = fake_header

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanel(block=FakeBlock("body"), tool_name="Bash")

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        panel.set_result_summary(_summary_with_chips())
        await pilot.pause()
        # A2: header chips always cleared, never populated from summary
        assert fake_header._header_chips == []
