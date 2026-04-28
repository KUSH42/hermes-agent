"""C2: retry action always present in footer when is_error=True."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button

from hermes_cli.tui.tool_result_parse import Action, ResultSummaryV4, Chip, inject_recovery_actions


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


def _action_button_labels(fp) -> list[str]:
    """Collect all action-chip button labels as lowercase strings."""
    return [
        str(btn.label).lower()
        for btn in fp._action_row.query(".--action-chip")
    ]


@pytest.mark.asyncio
async def test_retry_injected_when_no_server_retry():
    """Error summary with no actions → inject_recovery_actions synthesises retry → footer shows it."""
    from hermes_cli.tui.tool_panel import FooterPane

    raw_summary = _make_error_summary(actions=[])
    summary = inject_recovery_actions(raw_summary)

    class _App(App):
        def compose(self) -> ComposeResult:
            yield FooterPane()

    async with _App().run_test() as pilot:
        fp = pilot.app.query_one(FooterPane)
        fp.update_summary_v4(summary, frozenset())
        await pilot.pause()
        labels = _action_button_labels(fp)
        assert any("retry" in lbl for lbl in labels), (
            f"Expected a retry button; got labels: {labels}"
        )


@pytest.mark.asyncio
async def test_retry_not_duplicated_when_already_present():
    """Error summary that already has a retry action → inject_recovery_actions doesn't duplicate it."""
    from hermes_cli.tui.tool_panel import FooterPane

    retry_action = Action(label="retry", hotkey="r", kind="retry", payload=None)
    raw_summary = _make_error_summary(actions=[retry_action])
    summary = inject_recovery_actions(raw_summary)

    class _App(App):
        def compose(self) -> ComposeResult:
            yield FooterPane()

    async with _App().run_test() as pilot:
        fp = pilot.app.query_one(FooterPane)
        fp.update_summary_v4(summary, frozenset())
        await pilot.pause()
        labels = _action_button_labels(fp)
        retry_count = sum(1 for lbl in labels if "retry" in lbl)
        assert retry_count == 1, f"Expected exactly 1 retry button; got: {labels}"


@pytest.mark.asyncio
async def test_retry_not_shown_on_success():
    """Success summary → no retry in footer buttons."""
    from hermes_cli.tui.tool_panel import FooterPane

    summary = _make_ok_summary()

    class _App(App):
        def compose(self) -> ComposeResult:
            yield FooterPane()

    async with _App().run_test() as pilot:
        fp = pilot.app.query_one(FooterPane)
        fp.update_summary_v4(summary, frozenset())
        await pilot.pause()
        labels = _action_button_labels(fp)
        assert not any("retry" in lbl for lbl in labels), (
            f"Expected no retry button on success; got labels: {labels}"
        )
