"""C2: retry action always present in footer when is_error=True."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from textual.app import App, ComposeResult

from hermes_cli.tui.tool_result_parse import Action, ResultSummaryV4, Chip


def _make_error_summary(actions=()):
    return ResultSummaryV4(
        primary="fail",
        exit_code=1,
        chips=(),
        stderr_tail="",
        actions=tuple(actions),
        artifacts=(),
        is_error=True,
        error_kind="shell",
    )


def _make_ok_summary():
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
async def test_retry_injected_when_no_server_retry():
    """Error summary with no actions → retry is synthesized."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_panel import FooterPane

    summary = _make_error_summary(actions=[])

    class _App(App):
        def compose(self) -> ComposeResult:
            fp = FooterPane()
            yield fp

    async with _App().run_test() as pilot:
        fp = pilot.app.query_one(FooterPane)
        fp.update_summary_v4(summary, frozenset())
        await pilot.pause()
        # Access stored rich.Text via Static's private __content attr
        content_obj = fp._content._Static__content
        assert "retry" in str(content_obj).lower()


@pytest.mark.asyncio
async def test_retry_not_duplicated_when_already_present():
    """Error summary that already has a retry action → no duplicate."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_panel import FooterPane

    retry_action = Action(label="retry", hotkey="r", kind="retry", payload=None)
    summary = _make_error_summary(actions=[retry_action])

    class _App(App):
        def compose(self) -> ComposeResult:
            yield FooterPane()

    async with _App().run_test() as pilot:
        fp = pilot.app.query_one(FooterPane)
        fp.update_summary_v4(summary, frozenset())
        await pilot.pause()
        content_obj = fp._content._Static__content
        assert str(content_obj).lower().count("retry") == 1


@pytest.mark.asyncio
async def test_retry_not_shown_on_success():
    """Success summary → no retry in footer."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_panel import FooterPane

    summary = _make_ok_summary()

    class _App(App):
        def compose(self) -> ComposeResult:
            yield FooterPane()

    async with _App().run_test() as pilot:
        fp = pilot.app.query_one(FooterPane)
        fp.update_summary_v4(summary, frozenset())
        await pilot.pause()
        content_obj = fp._content._Static__content
        assert "retry" not in str(content_obj).lower()
