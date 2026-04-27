"""Tool block — Visual Noise Cleanup spec.

* VN-1 — action chip row is hidden unless ``ToolPanel`` (or any descendant) has
  focus. Driven by a ``:focus-within`` rule in ``hermes.tcss``; the per-widget
  ``has-actions`` class still toggles to gate the rule.

Note: VN-2 (header gap cap) tests removed — ``_resolve_max_header_gap`` and
``MAX_HEADER_GAP_CELLS_FALLBACK`` were deleted by HW-1..HW-6.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp



# ---------------------------------------------------------------------------
# VN-1: action chip row visibility tied to ToolPanel:focus-within
# ---------------------------------------------------------------------------


async def _pause(pilot, n: int = 5) -> None:
    for _ in range(n):
        await pilot.pause()


def _make_app() -> HermesApp:
    return HermesApp(cli=MagicMock())


def _summary_with_actions(actions_kinds=("copy_body",), is_error=False):
    from hermes_cli.tui.tool_result_parse import Action, ResultSummaryV4

    actions = tuple(
        Action(label=k, hotkey=k[0], kind=k, payload=None)
        for k in actions_kinds
    )
    return ResultSummaryV4(
        primary=None,
        exit_code=0 if not is_error else 1,
        chips=(),
        stderr_tail="",
        actions=actions,
        artifacts=(),
        is_error=is_error,
    )


async def _mounted_panel_with_actions(app, pilot):
    """Mount a ToolPanel and complete it with an action so action-row populates."""
    from hermes_cli.tui.widgets import OutputPanel
    from hermes_cli.tui.tool_panel import ToolPanel

    app.agent_running = True
    await _pause(pilot)
    app._svc_tools.open_gen_block("terminal")
    await _pause(pilot)
    panel = app.query_one(OutputPanel).query_one(ToolPanel)
    # Mark streaming block as completed so FooterPane._render_footer doesn't
    # zero-out actions_to_render under the streaming guard.
    panel._block._completed = True
    panel.set_result_summary(_summary_with_actions(("copy_body",)))
    await _pause(pilot)
    return panel


class TestVN1ActionRowFocus:
    @pytest.mark.asyncio
    async def test_action_row_hidden_when_unfocused(self):
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await _pause(pilot)
            panel = await _mounted_panel_with_actions(app, pilot)
            # Move focus elsewhere — input usually steals focus by default but
            # be explicit.
            from hermes_cli.tui.input.widget import HermesInput
            try:
                inp = app.query_one(HermesInput)
                inp.focus()
            except Exception:  # input not mounted in some configs; safe to skip
                pass
            await _pause(pilot)
            row = panel.query_one(".action-row")
            assert row.has_class("--action-chip") is False  # sanity
            assert row.display is False

    @pytest.mark.asyncio
    async def test_action_row_visible_when_panel_focused(self):
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await _pause(pilot)
            panel = await _mounted_panel_with_actions(app, pilot)
            panel.focus()
            await _pause(pilot)
            row = panel.query_one(".action-row")
            assert row.display is True

    @pytest.mark.asyncio
    async def test_action_row_visible_when_button_focused(self):
        from textual.widgets import Button

        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await _pause(pilot)
            panel = await _mounted_panel_with_actions(app, pilot)
            buttons = list(panel.query(".--action-chip"))
            assert buttons, "expected at least one action chip Button"
            btn = buttons[0]
            assert isinstance(btn, Button)
            btn.focus()
            await _pause(pilot)
            row = panel.query_one(".action-row")
            assert row.display is True

    @pytest.mark.asyncio
    async def test_action_row_hidden_after_focus_leaves(self):
        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await _pause(pilot)
            panel = await _mounted_panel_with_actions(app, pilot)
            panel.focus()
            await _pause(pilot)
            row = panel.query_one(".action-row")
            assert row.display is True
            # Move focus to the input.
            from hermes_cli.tui.input.widget import HermesInput
            inp = app.query_one(HermesInput)
            inp.focus()
            await _pause(pilot)
            assert row.display is False

    @pytest.mark.asyncio
    async def test_action_row_no_actions_no_show_even_focused(self):
        from hermes_cli.tui.tool_result_parse import ResultSummaryV4
        from hermes_cli.tui.widgets import OutputPanel
        from hermes_cli.tui.tool_panel import ToolPanel, FooterPane

        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await _pause(pilot)
            app.agent_running = True
            await _pause(pilot)
            app._svc_tools.open_gen_block("terminal")
            await _pause(pilot)
            panel = app.query_one(OutputPanel).query_one(ToolPanel)
            # Empty actions tuple → no chips, no has-actions.
            panel.set_result_summary(
                ResultSummaryV4(
                    primary=None,
                    exit_code=0,
                    chips=(),
                    stderr_tail="",
                    actions=(),
                    artifacts=(),
                    is_error=False,
                )
            )
            await _pause(pilot)
            panel.focus()
            await _pause(pilot)
            footer = panel.query_one(FooterPane)
            assert footer.has_class("has-actions") is False
            row = panel.query_one(".action-row")
            assert row.display is False

    @pytest.mark.asyncio
    async def test_button_click_keeps_row_visible(self):
        from hermes_cli.tui.tool_panel import ToolPanel

        app = _make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await _pause(pilot)
            panel = await _mounted_panel_with_actions(app, pilot)
            buttons = list(panel.query(".--action-chip"))
            assert buttons
            # Replace the action method so we don't depend on full panel state.
            with patch.object(ToolPanel, "action_copy_body", autospec=True) as fn:
                panel.focus()
                await _pause(pilot)
                await pilot.click(buttons[0])
                await _pause(pilot)
                row = panel.query_one(".action-row")
                assert fn.called, "click did not deliver"
                assert row.display is True
