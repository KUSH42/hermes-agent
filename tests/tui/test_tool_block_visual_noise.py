"""Tool block — Visual Noise Cleanup spec.

Two unrelated polish fixes verified together:

* VN-1 — action chip row is hidden unless ``ToolPanel`` (or any descendant) has
  focus. Driven by a ``:focus-within`` rule in ``hermes.tcss``; the per-widget
  ``has-actions`` class still toggles to gate the rule.
* VN-2 — header label→stats gap is capped to a configurable cell count
  (``tool-header-max-gap`` skin var, fallback 8) so on wide terminals stats no
  longer fly to the far right.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from rich.text import Text

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.tool_blocks._header import (
    MAX_HEADER_GAP_CELLS_FALLBACK,
    ToolHeader,
)


# ---------------------------------------------------------------------------
# VN-2: header gap cap
# ---------------------------------------------------------------------------


def _make_header(label: str = "tt") -> ToolHeader:
    """Build an unmounted ToolHeader with safe defaults for ``_render_v4``."""
    h = ToolHeader(label=label, line_count=0, tool_name=None)
    h._label_rich = Text(label)
    h._stats = None
    h._is_complete = False
    h._spinner_char = None
    h._tool_icon = ""
    h._has_affordances = False
    return h


def _make_app_mock(css_vars: dict | None = None) -> SimpleNamespace:
    """Mock for ``Widget.app`` exposing ``get_css_variables`` and ``console``."""
    cv = dict(css_vars or {})
    return SimpleNamespace(
        get_css_variables=lambda: cv,
        console=SimpleNamespace(color_system="truecolor"),
    )


def _pad_cells(t: Text, label_cells: int, tail_cells: int) -> int:
    """Padding cells between label and tail in ``_render_v4`` output.

    Plain layout: 4-cell gutter + label + N spaces + tail.
    """
    GUTTER_W = 4
    return len(t.plain) - GUTTER_W - label_cells - tail_cells


class TestVN2HeaderGapCap:
    @patch.object(ToolHeader, "size", new_callable=PropertyMock)
    @patch.object(ToolHeader, "app", new_callable=PropertyMock)
    def test_header_gap_capped_on_wide_term(self, mock_app, mock_size):
        mock_app.return_value = _make_app_mock()
        mock_size.return_value = SimpleNamespace(width=200)
        h = _make_header(label="tt")
        t = h._render_v4()
        assert t is not None
        # tail = "·" (1 cell), label = 2 cells; uncapped pad would be ~190.
        assert _pad_cells(t, label_cells=2, tail_cells=1) == 8

    @patch.object(ToolHeader, "size", new_callable=PropertyMock)
    @patch.object(ToolHeader, "app", new_callable=PropertyMock)
    def test_header_gap_uncapped_when_already_smaller(self, mock_app, mock_size):
        mock_app.return_value = _make_app_mock()
        mock_size.return_value = SimpleNamespace(width=80)
        # Pick label_cells s.t. (available - label_cells) < 8.
        # available = max(12, 80 - 5 - 1 - 2) = 72; choose 70 → uncapped pad = 2.
        label = "x" * 70
        h = _make_header(label=label)
        t = h._render_v4()
        assert t is not None
        pad = _pad_cells(t, label_cells=70, tail_cells=1)
        assert 0 < pad < 8

    @patch.object(ToolHeader, "size", new_callable=PropertyMock)
    @patch.object(ToolHeader, "app", new_callable=PropertyMock)
    def test_header_gap_zero_when_label_fills(self, mock_app, mock_size):
        mock_app.return_value = _make_app_mock()
        mock_size.return_value = SimpleNamespace(width=80)
        # available = 72; label > available triggers truncate→divide+ellipsis →
        # label_text.cell_len ≥ available, so pad = 0.
        h = _make_header(label="x" * 200)
        t = h._render_v4()
        assert t is not None
        # Label is truncated to fit, then ellipsis appended; recover real label
        # cell_len from t.plain by subtracting gutter and tail.
        plain = t.plain
        assert plain.endswith("·")
        gutter = "    "
        assert plain.startswith(gutter)
        body = plain[len(gutter):-1]  # strip gutter + tail "·"
        # Body is label + pad spaces. Label uses ellipsis "…" at end.
        assert "…" in body
        # Pad must be 0: body has no trailing run of spaces.
        assert not body.endswith(" ")

    @patch.object(ToolHeader, "size", new_callable=PropertyMock)
    @patch.object(ToolHeader, "app", new_callable=PropertyMock)
    def test_header_gap_skin_var_override(self, mock_app, mock_size):
        mock_app.return_value = _make_app_mock({"tool-header-max-gap": "4"})
        mock_size.return_value = SimpleNamespace(width=200)
        h = _make_header(label="tt")
        t = h._render_v4()
        assert t is not None
        assert _pad_cells(t, label_cells=2, tail_cells=1) == 4

    @patch.object(ToolHeader, "size", new_callable=PropertyMock)
    @patch.object(ToolHeader, "app", new_callable=PropertyMock)
    def test_header_gap_skin_var_invalid_fallback(self, mock_app, mock_size):
        mock_app.return_value = _make_app_mock({"tool-header-max-gap": "garbage"})
        mock_size.return_value = SimpleNamespace(width=200)
        h = _make_header(label="tt")
        t = h._render_v4()
        assert t is not None
        # int("garbage") raises ValueError → caught → fallback (8).
        assert _pad_cells(t, label_cells=2, tail_cells=1) == MAX_HEADER_GAP_CELLS_FALLBACK

    @patch.object(ToolHeader, "size", new_callable=PropertyMock)
    @patch.object(ToolHeader, "app", new_callable=PropertyMock)
    def test_header_gap_skin_var_missing_fallback(self, mock_app, mock_size):
        mock_app.return_value = _make_app_mock({})  # key absent → v is None
        mock_size.return_value = SimpleNamespace(width=200)
        h = _make_header(label="tt")
        t = h._render_v4()
        assert t is not None
        assert _pad_cells(t, label_cells=2, tail_cells=1) == MAX_HEADER_GAP_CELLS_FALLBACK


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
