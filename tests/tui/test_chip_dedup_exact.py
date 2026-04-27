"""A3: chip dedup uses exact match — substrings not dropped."""
from __future__ import annotations

# A2 removed chip promotion to header, so A3 (exact dedup) is now moot for
# header promotion. Verify the old substring-match guard is gone by confirming
# chips flow to FooterPane regardless of substring relationship with primary.

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from hermes_cli.tui.tool_result_parse import ResultSummaryV4, Chip, Action
from hermes_cli.tui.tool_panel import FooterPane


def _summary(primary: str, chip_text: str) -> ResultSummaryV4:
    return ResultSummaryV4(
        primary=primary,
        exit_code=0,
        chips=(Chip(text=chip_text, kind="exit", tone="success"),),
        stderr_tail="",
        actions=(),
        artifacts=(),
        is_error=False,
    )


@pytest.mark.asyncio
async def test_substring_chip_not_dropped():
    """primary='exit 0', chip='0' — chip is substring but must still appear in footer."""
    class _App(App):
        def compose(self) -> ComposeResult:
            yield FooterPane()

    async with _App().run_test() as pilot:
        fp = pilot.app.query_one(FooterPane)
        summary = _summary(primary="exit 0", chip_text="0")
        fp.update_summary_v4(summary, frozenset())
        await pilot.pause()
        content = str(fp._content._Static__content)
        assert "0" in content


@pytest.mark.asyncio
async def test_exact_match_chip_present_in_footer():
    """primary='ok', chip='ok' — still appears in footer (no dedup at footer level)."""
    class _App(App):
        def compose(self) -> ComposeResult:
            yield FooterPane()

    async with _App().run_test() as pilot:
        fp = pilot.app.query_one(FooterPane)
        summary = _summary(primary="ok", chip_text="ok")
        fp.update_summary_v4(summary, frozenset())
        await pilot.pause()
        content = str(fp._content._Static__content)
        assert "ok" in content
