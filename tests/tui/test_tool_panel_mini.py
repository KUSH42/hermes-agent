"""Tests for ToolPanelMini and auto-select criteria (v3 Phase B, §5.10).

Covers:
- meets_mini_criteria: SHELL+exit0+≤3L+no-stderr → True
- meets_mini_criteria: fails when category != SHELL
- meets_mini_criteria: fails when exit_code != 0
- meets_mini_criteria: fails when line_count > 3
- meets_mini_criteria: fails when stderr_raw present
- ToolPanelMini composes ToolAccent + content Static
- ToolPanelMini has height:1 in DEFAULT_CSS
- can_focus = True on ToolPanelMini
- Integration: ToolPanel activates mini after qualifying set_result_summary
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from hermes_cli.tui.tool_panel_mini import meets_mini_criteria, ToolPanelMini


# ---------------------------------------------------------------------------
# Unit — meets_mini_criteria
# ---------------------------------------------------------------------------


def _shell_category():
    from hermes_cli.tui.tool_category import ToolCategory
    return ToolCategory.SHELL


def _non_shell_category():
    from hermes_cli.tui.tool_category import ToolCategory
    return ToolCategory.FILE


def test_meets_criteria_all_conditions():
    assert meets_mini_criteria(_shell_category(), 0, 2, None) is True


def test_meets_criteria_zero_lines():
    assert meets_mini_criteria(_shell_category(), 0, 0, None) is True


def test_fails_non_shell():
    assert meets_mini_criteria(_non_shell_category(), 0, 2, None) is False


def test_fails_nonzero_exit():
    assert meets_mini_criteria(_shell_category(), 1, 2, None) is False


def test_fails_exit_code_none():
    """exit_code=None means not finished — does not meet criteria."""
    assert meets_mini_criteria(_shell_category(), None, 2, None) is False


def test_fails_too_many_lines():
    assert meets_mini_criteria(_shell_category(), 0, 4, None) is False


def test_fails_stderr_present():
    assert meets_mini_criteria(_shell_category(), 0, 2, "some error") is False


def test_fails_empty_stderr_counts_as_ok():
    """Empty string stderr is treated same as None."""
    assert meets_mini_criteria(_shell_category(), 0, 2, "") is True


# ---------------------------------------------------------------------------
# Unit — ToolPanelMini
# ---------------------------------------------------------------------------


def test_tool_panel_mini_has_height_1():
    assert "height: 1" in ToolPanelMini.DEFAULT_CSS


def test_tool_panel_mini_can_focus():
    assert ToolPanelMini.can_focus is True


def test_tool_panel_mini_stores_command():
    source = MagicMock()
    mini = ToolPanelMini(source_panel=source, command="ls -la", duration_s=0.5)
    assert mini._command == "ls -la"
    assert mini._duration_s == 0.5


# ---------------------------------------------------------------------------
# Integration — ToolPanel activates mini on qualifying set_result_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_panel_mini_mounts_after_qualifying_complete():
    """ToolPanel hides itself and mounts ToolPanelMini sibling on qualifying SHELL complete."""
    from hermes_cli.tui.app import HermesApp
    from hermes_cli.tui.widgets import OutputPanel
    from hermes_cli.tui.tool_panel import ToolPanel

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(5):
            await pilot.pause()
        app.agent_running = True
        for _ in range(5):
            await pilot.pause()

        # Open a shell tool block (terminal = SHELL category)
        app._open_gen_block("terminal")
        for _ in range(5):
            await pilot.pause()

        panel = app.query_one(OutputPanel).query_one(ToolPanel)

        # Simulate a qualifying completion: exit0, 2 lines, no stderr
        from hermes_cli.tui.tool_result_parse import ResultSummary
        summary = ResultSummary(
            is_error=False,
            exit_code=0,
            stat_badges=[],
            stderr_tail=None,
            retry_hint=None,
        )
        # Add 2 lines to block so line_count = 2
        from hermes_cli.tui.tool_blocks import StreamingToolBlock
        stb = panel.query_one(StreamingToolBlock)
        stb.append_line("line 1")
        stb.append_line("line 2")
        for _ in range(5):
            await pilot.pause()

        panel.set_result_summary(summary)
        for _ in range(8):
            await pilot.pause()

        # ToolPanel should be hidden, ToolPanelMini should be in DOM
        assert not panel.display
        minis = list(app.query_one(OutputPanel).query(ToolPanelMini))
        assert len(minis) == 1
