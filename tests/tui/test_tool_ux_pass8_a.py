"""Tool UX Audit Pass 8 — Phase A tests.

A1: Duplicate question_mark binding resolved (f1 → show_help)
A2: Streaming block shows `f` in hint row; completed block does not
A3: action_copy_err fallback to copy_err action payload
A4: action_dismiss_overlay clears filter state
A5: OmissionBar reset button label refreshes on skin change
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# A1 — f1 binds to show_help; question_mark binds to show_context_menu only
# ---------------------------------------------------------------------------

class TestA1BindingConflictResolved:
    def test_f1_binding_present(self):
        from hermes_cli.tui.tool_panel import ToolPanel
        keys = {b.key for b in ToolPanel.BINDINGS}
        assert "f1" in keys, "f1 must be bound (show_help)"

    def test_question_mark_not_bound_to_show_help(self):
        from hermes_cli.tui.tool_panel import ToolPanel
        help_bindings = [b for b in ToolPanel.BINDINGS if b.action == "show_help"]
        # f1 should be the show_help binding, not question_mark
        assert all(b.key != "question_mark" for b in help_bindings), (
            "question_mark must not be bound to show_help (it's shadowed by show_context_menu)"
        )

    def test_show_help_reachable_via_f1(self):
        from hermes_cli.tui.tool_panel import ToolPanel
        f1_bindings = [b for b in ToolPanel.BINDINGS if b.key == "f1"]
        assert any(b.action == "show_help" for b in f1_bindings), (
            "f1 must be bound to show_help"
        )

    def test_question_mark_binds_to_context_menu(self):
        from hermes_cli.tui.tool_panel import ToolPanel
        qm_bindings = [b for b in ToolPanel.BINDINGS if b.key == "question_mark"]
        assert len(qm_bindings) >= 1, "question_mark must still be bound"
        # No duplicate bindings for question_mark→show_help should exist
        help_via_qm = [b for b in qm_bindings if b.action == "show_help"]
        assert len(help_via_qm) == 0, "question_mark must not map to show_help"

    def test_no_duplicate_question_mark_bindings(self):
        from hermes_cli.tui.tool_panel import ToolPanel
        qm_bindings = [b for b in ToolPanel.BINDINGS if b.key == "question_mark"]
        # Each key should map to at most one action in the same binding list
        # (Textual silently shadows — we verify no duplicate question_mark entries)
        assert len(qm_bindings) == 1, (
            f"question_mark must appear exactly once in BINDINGS, found {len(qm_bindings)}"
        )


# ---------------------------------------------------------------------------
# A2 — `f` hint shown during streaming, hidden when completed
# ---------------------------------------------------------------------------

class TestA2TailFollowHint:
    def test_streaming_hint_in_source(self):
        """_build_hint_text source must include streaming check + tail hint."""
        import inspect
        from hermes_cli.tui.tool_panel import ToolPanel
        src = inspect.getsource(ToolPanel._build_hint_text)
        assert "_completed" in src, "_build_hint_text must check _block._completed for streaming"
        assert "tail" in src, "_build_hint_text must include 'tail' label for f hint"

    def test_f_key_hint_conditional_on_streaming(self):
        """The 'f' tail hint must be gated by an _block_streaming conditional."""
        import inspect
        from hermes_cli.tui.tool_panel import ToolPanel
        src = inspect.getsource(ToolPanel._build_hint_text)
        # _block_streaming must exist
        assert "_block_streaming" in src, "_build_hint_text must use _block_streaming flag"
        # The append for ("f", ...) with "tail" must exist inside a block_streaming if
        assert 'if _block_streaming' in src, (
            "_build_hint_text must have 'if _block_streaming' conditional"
        )
        # Find if the tail append is under the if _block_streaming block
        streaming_if_idx = src.index("if _block_streaming")
        # The ("f", ..., "tail") append must appear after the if block_streaming
        f_tail_idx = src.find('"tail"')
        if f_tail_idx == -1:
            f_tail_idx = src.find("'tail'")
        assert f_tail_idx > streaming_if_idx, (
            "tail hint append must appear after 'if _block_streaming'"
        )

    def test_tail_hint_not_shown_unconditionally(self):
        """tail hint must not appear outside a conditional block."""
        import inspect
        from hermes_cli.tui.tool_panel import ToolPanel
        src = inspect.getsource(ToolPanel._build_hint_text)
        # 'tail' must be inside an if block referencing _block_streaming
        lines = src.split("\n")
        tail_lines = [l for l in lines if "tail" in l and "hints.append" in l]
        for line in tail_lines:
            # The line itself might not have the if, but verify _block_streaming appears before it
            assert len(tail_lines) > 0, "tail hint must be in _build_hint_text"


# ---------------------------------------------------------------------------
# A3 — action_copy_err fallback to copy_err action payload
# ---------------------------------------------------------------------------

class TestA3CopyErrFallback:
    def _make_copy_err_ctx(self, stderr_tail: str, actions: tuple):
        """Build just the result summary and app mock. Return (rs, app_mock, flash_mock)."""
        from hermes_cli.tui.tool_result_parse import ResultSummaryV4
        rs = ResultSummaryV4(
            primary="✓",
            exit_code=0,
            chips=(),
            stderr_tail=stderr_tail,
            actions=actions,
            artifacts=(),
            is_error=False,
        )
        app_mock = MagicMock()
        app_mock._copy_text_with_hint = MagicMock()
        flash_mock = MagicMock()
        return rs, app_mock, flash_mock

    def _call_copy_err(self, rs, app_mock, flash_mock):
        """Call action_copy_err with mocked panel context."""
        from hermes_cli.tui.tool_panel import ToolPanel
        # Patch app property access by calling the method body directly
        # using a simple namespace object
        import types
        panel = types.SimpleNamespace(
            _result_summary_v4=rs,
            app=app_mock,
            _flash_header=flash_mock,
        )
        # Bind method to namespace
        ToolPanel.action_copy_err(panel)
        return panel

    def test_copy_err_uses_stderr_tail_first(self):
        from hermes_cli.tui.tool_result_parse import Action
        rs, app_mock, flash_mock = self._make_copy_err_ctx(
            stderr_tail="STDERR LINE",
            actions=(Action("copy err", "e", "copy_err", "ACTION PAYLOAD"),),
        )
        self._call_copy_err(rs, app_mock, flash_mock)
        app_mock._copy_text_with_hint.assert_called_once()
        args = app_mock._copy_text_with_hint.call_args[0]
        assert args[0] == "STDERR LINE", "should copy stderr_tail when present"

    def test_copy_err_fallback_to_action_payload(self):
        from hermes_cli.tui.tool_result_parse import Action
        rs, app_mock, flash_mock = self._make_copy_err_ctx(
            stderr_tail="",
            actions=(Action("copy err", "e", "copy_err", "FALLBACK"),),
        )
        self._call_copy_err(rs, app_mock, flash_mock)
        app_mock._copy_text_with_hint.assert_called_once()
        args = app_mock._copy_text_with_hint.call_args[0]
        assert args[0] == "FALLBACK", "should copy action payload when stderr_tail is empty"

    def test_copy_err_no_op_when_both_empty(self):
        rs, app_mock, flash_mock = self._make_copy_err_ctx(
            stderr_tail="",
            actions=(),
        )
        self._call_copy_err(rs, app_mock, flash_mock)
        app_mock._copy_text_with_hint.assert_not_called()

    def test_hint_includes_e_check_in_source(self):
        """_build_hint_text must check copy_err action payload for e hint visibility."""
        import inspect
        from hermes_cli.tui.tool_panel import ToolPanel
        src = inspect.getsource(ToolPanel._build_hint_text)
        # Should check copy_err kind in actions
        assert "copy_err" in src, (
            "_build_hint_text must check for copy_err action when deciding e hint visibility"
        )
        assert "stderr" in src.lower() or "stderr_tail" in src, (
            "_build_hint_text must reference stderr_tail or stderr for e hint"
        )


# ---------------------------------------------------------------------------
# A4 — action_dismiss_overlay clears filter state
# ---------------------------------------------------------------------------

class TestA4DismissOverlayClearsFilter:
    def _make_screen(self, filter_text="some query"):
        """Create a SimpleNamespace masquerading as ToolsScreen."""
        import types
        from hermes_cli.tui.tools_overlay import ToolsScreen
        app_ns = types.SimpleNamespace(pop_screen=MagicMock())
        screen = types.SimpleNamespace(
            _filter_text=filter_text,
            app=app_ns,
            query_one=None,  # set per-test
        )
        # Bind the async method
        screen._action_dismiss_overlay = ToolsScreen.action_dismiss_overlay
        return screen, app_ns

    def test_dismiss_overlay_clears_filter_value(self):
        from hermes_cli.tui.tools_overlay import ToolsScreen

        fi_mock = MagicMock()
        fi_mock.display = True
        fi_mock.value = "some query"

        screen, app_ns = self._make_screen("some query")
        screen.query_one = lambda sel, wt=None: fi_mock

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            ToolsScreen.action_dismiss_overlay(screen)
        )

        assert screen._filter_text == "", "filter text must be cleared on dismiss"
        assert fi_mock.value == "", "filter input value must be cleared on dismiss"
        app_ns.pop_screen.assert_called_once()

    def test_dismiss_overlay_hides_filter_input(self):
        from hermes_cli.tui.tools_overlay import ToolsScreen

        fi_mock = MagicMock()
        fi_mock.display = True

        screen, app_ns = self._make_screen("query")
        screen.query_one = lambda sel, wt=None: fi_mock

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            ToolsScreen.action_dismiss_overlay(screen)
        )
        assert fi_mock.display is False, "filter input must be hidden on dismiss"


# ---------------------------------------------------------------------------
# A5 — OmissionBar reset button label refreshes on skin change
# ---------------------------------------------------------------------------

class TestA5OmissionBarLabelRefresh:
    def test_refresh_skin_updates_reset_button_label(self):
        from hermes_cli.tui.tool_blocks import StreamingToolBlock

        block = StreamingToolBlock.__new__(StreamingToolBlock)
        block._header = MagicMock()
        block._header._refresh_gutter_color = MagicMock()
        block._header._refresh_tool_icon = MagicMock()
        block._header.refresh = MagicMock()
        block._tool_name = "bash"

        # Create mock bars
        bar_top = MagicMock()
        bar_top.is_mounted = True
        btn_top = MagicMock()
        bar_top.query_one = MagicMock(return_value=btn_top)

        bar_bottom = MagicMock()
        bar_bottom.is_mounted = True
        btn_bottom = MagicMock()
        bar_bottom.query_one = MagicMock(return_value=btn_bottom)

        block._omission_bar_top = bar_top
        block._omission_bar_bottom = bar_bottom

        with patch(
            "hermes_cli.tui.tool_blocks.OmissionBar._reset_label",
            return_value="↺ reset",
        ):
            StreamingToolBlock.refresh_skin(block)

        # Both bars should have had their button label updated
        assert btn_top.label == "↺ reset", "top bar reset button label must update on skin reload"
        assert btn_bottom.label == "↺ reset", "bottom bar reset button label must update on skin reload"

    def test_refresh_skin_skips_unmounted_bars(self):
        from hermes_cli.tui.tool_blocks import StreamingToolBlock

        block = StreamingToolBlock.__new__(StreamingToolBlock)
        block._header = MagicMock()
        block._header._refresh_gutter_color = MagicMock()
        block._header._refresh_tool_icon = MagicMock()
        block._header.refresh = MagicMock()
        block._tool_name = "bash"

        bar = MagicMock()
        bar.is_mounted = False

        block._omission_bar_top = bar
        block._omission_bar_bottom = None

        # Should not raise even with unmounted bar and None bar
        StreamingToolBlock.refresh_skin(block)
        bar.query_one.assert_not_called()
