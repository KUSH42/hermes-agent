"""D1: compact mode keeps error footer visible without focus."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from hermes_cli.tui.tool_result_parse import ResultSummaryV4
from textual.widgets import Static
from hermes_cli.tui.tool_panel import ToolPanel, FooterPane


def _error_summary():
    return ResultSummaryV4(
        primary="fail",
        exit_code=1,
        chips=(),
        stderr_tail="something went wrong",
        actions=(),
        artifacts=(),
        is_error=True,
        error_kind="shell",
    )


def _ok_summary():
    return ResultSummaryV4(
        primary="ok",
        exit_code=0,
        chips=(),
        stderr_tail="",
        actions=(),
        artifacts=(),
        is_error=False,
    )


@pytest.mark.asyncio
async def test_error_panel_gets_error_class():
    class _App(App):
        def compose(self) -> ComposeResult:
            block = Static("body")
            yield ToolPanel(block=block, tool_name="Bash")

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        panel.set_result_summary(_error_summary())
        await pilot.pause()
        assert panel.has_class("tool-panel--error")


@pytest.mark.asyncio
async def test_ok_panel_no_error_class():
    class _App(App):
        def compose(self) -> ComposeResult:
            block = Static("body")
            yield ToolPanel(block=block, tool_name="Bash")

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        panel.set_result_summary(_ok_summary())
        await pilot.pause()
        assert not panel.has_class("tool-panel--error")
