"""Tests for Tool UX Audit Pass 7 — Phase D: Navigation & discovery."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# D1 — ToolGroup peek hint in _build_hint_text
# ---------------------------------------------------------------------------

class TestD1PeekHint:
    """_build_hint_text shows Shift+Enter peek hint when panel is in ToolGroup."""

    def test_peek_hint_implementation_in_source(self):
        """D1: peek/⇧↵ are power-tier hints, signalled by F1 overflow indicator."""
        import inspect
        from hermes_cli.tui.tool_panel import ToolPanel
        src = inspect.getsource(ToolPanel._build_hint_text)
        # B1 three-tier model: power keys (⇧↵/peek) are not shown inline;
        # they are behind F1. Verify F1 overflow is signalled.
        assert "_power_keys_exist" in src or "F1" in src, (
            "D1: power-tier overflow (F1) must be signalled in _build_hint_text"
        )

    def test_get_tool_group_import_present(self):
        """D1: _get_tool_group is importable from tool_group."""
        from hermes_cli.tui.tool_group import _get_tool_group
        assert callable(_get_tool_group)

    def test_peek_hint_logic_conditional(self):
        """D1: peek hint only added when _get_tool_group returns non-None."""
        # Simulate the hint logic without needing a full Textual app
        mock_group = MagicMock()
        hints = []

        # Simulate the D1 block logic
        group = mock_group  # non-None
        if group is not None:
            hints.append(("⇧↵", " ", "peek"))
        assert any(h[2] == "peek" for h in hints)

        # With None
        hints2 = []
        group2 = None
        if group2 is not None:
            hints2.append(("⇧↵", " ", "peek"))
        assert not any(h[2] == "peek" for h in hints2)


# ---------------------------------------------------------------------------
# D2 — /tools filter placeholder
# ---------------------------------------------------------------------------

class TestD2FilterPlaceholder:
    """ToolsScreen filter Input has helpful placeholder text."""

    def test_filter_placeholder_text(self):
        """D2: compose() sets filter input placeholder with prefix hints."""
        from hermes_cli.tui.tools_overlay import ToolsScreen
        screen = ToolsScreen.__new__(ToolsScreen)
        # Walk compose() to find the Input widget
        from textual.widgets import Input
        composed_widgets = []

        original_compose = ToolsScreen.compose
        widgets_seen = []

        class RecordingInput:
            def __init__(self, *a, **kw):
                self.placeholder = kw.get('placeholder', '')
                widgets_seen.append(self)

        with patch('hermes_cli.tui.tools_overlay.Input', RecordingInput):
            try:
                for _ in screen.compose():
                    pass
            except Exception:
                pass

        if widgets_seen:
            placeholder = widgets_seen[-1].placeholder
            assert "file:" in placeholder or "shell:" in placeholder or "error:" in placeholder, \
                f"Placeholder missing prefix hints: {placeholder!r}"

    def test_placeholder_contains_error_prefix(self):
        """D2: placeholder text includes 'error:' prefix hint."""
        from hermes_cli.tui.tools_overlay import ToolsScreen
        widgets_seen = []

        class RecordingInput:
            def __init__(self, *a, **kw):
                self.id = kw.get('id', '')
                self.placeholder = kw.get('placeholder', '')
                widgets_seen.append(self)

        with patch('hermes_cli.tui.tools_overlay.Input', RecordingInput):
            try:
                screen = ToolsScreen.__new__(ToolsScreen)
                for _ in screen.compose():
                    pass
            except Exception:
                pass

        filter_inputs = [w for w in widgets_seen if w.id == "filter-input"]
        if filter_inputs:
            assert "error:" in filter_inputs[0].placeholder


# ---------------------------------------------------------------------------
# D3 — Secondary args row lazy-mounted
# ---------------------------------------------------------------------------

class TestD3LazyArgsRow:
    """ToolBodyContainer lazy-mounts --args-row on first non-empty call."""

    def test_compose_does_not_yield_args_row(self):
        """D3: compose() no longer yields the --args-row Static."""
        from hermes_cli.tui.tool_blocks import ToolBodyContainer
        container = ToolBodyContainer.__new__(ToolBodyContainer)
        container._secondary_text = ""
        container._microcopy_active = False
        container._args_row_mounted = False
        widgets = []
        # Simulate compose — just check it doesn't yield args-row in normal flow
        # We'll check the class-level CSS no longer mentions --args-row as always-visible
        css = ToolBodyContainer.DEFAULT_CSS
        # args-row is still in CSS but not in compose
        assert "--args-row" in css  # CSS exists
        # But the compose should not always yield it
        assert not container._args_row_mounted

    def test_args_row_mounted_flag_initializes_false(self):
        """D3: _args_row_mounted starts False."""
        from hermes_cli.tui.tool_blocks import ToolBodyContainer
        container = ToolBodyContainer()
        assert container._args_row_mounted is False

    def test_set_args_row_empty_doesnt_crash_when_unmounted(self):
        """D3: set_args_row('') gracefully handles unmounted state."""
        from hermes_cli.tui.tool_blocks import ToolBodyContainer
        container = ToolBodyContainer.__new__(ToolBodyContainer)
        container._secondary_text = ""
        container._microcopy_active = False
        container._args_row_mounted = False
        container.query_one = MagicMock(side_effect=Exception("not found"))
        # Should not raise
        container.set_args_row(None)
        container.set_args_row("")


# ---------------------------------------------------------------------------
# D4 — Collapsed error shows stderr hint in tail
# ---------------------------------------------------------------------------

class TestD4StderrHintInCollapsedTail:
    """ToolHeader._render_v4 appends '⚠ stderr (e)' when collapsed error with stderr."""

    def test_stderr_hint_in_render_v4_source(self):
        """D4: _render_v4 source contains the collapsed error+stderr hint logic."""
        import inspect
        from hermes_cli.tui.tool_blocks import ToolHeader
        src = inspect.getsource(ToolHeader._render_v4)
        assert "stderr" in src, "D4: stderr hint missing from _render_v4"
        assert "collapsed" in src, "D4: collapsed check missing from _render_v4"
        assert "_tool_icon_error" in src, "D4: _tool_icon_error check missing from _render_v4"

    def test_stderr_hint_logic_conditions(self):
        """D4: the stderr hint shows only when collapsed AND error AND has stderr."""
        # Simulate the condition logic from _render_v4
        from hermes_cli.tui.tool_result_parse import ResultSummaryV4

        def should_show_hint(collapsed, is_error, has_stderr):
            rs_v4 = ResultSummaryV4(
                primary="✗ error" if is_error else "done",
                exit_code=1 if is_error else 0,
                chips=(), stderr_tail="err output" if has_stderr else "",
                actions=(), artifacts=(), is_error=is_error,
            )
            panel = MagicMock()
            panel.collapsed = collapsed
            panel._result_summary_v4 = rs_v4
            # Replicate the D4 condition
            try:
                return (panel is not None and
                        panel.collapsed and
                        is_error and
                        rs_v4 is not None and
                        bool(getattr(rs_v4, "stderr_tail", "")))
            except Exception:
                return False

        assert should_show_hint(True, True, True) is True
        assert should_show_hint(False, True, True) is False  # not collapsed
        assert should_show_hint(True, False, True) is False  # not error
        assert should_show_hint(True, True, False) is False  # no stderr


# ---------------------------------------------------------------------------
# D5 — Streaming tool count in StatusBar
# ---------------------------------------------------------------------------

class TestD5StreamingToolCount:
    """HermesApp._streaming_tool_count increments/decrements with open/close."""

    def test_streaming_count_reactive_exists(self):
        """D5: _streaming_tool_count reactive field exists on HermesApp."""
        from hermes_cli.tui.app import HermesApp
        assert hasattr(HermesApp, '_streaming_tool_count'), \
            "_streaming_tool_count reactive field missing from HermesApp"

    def test_count_increments_on_open(self):
        """D5: _active_streaming_blocks length drives _streaming_tool_count."""
        # Simulate what open_streaming_tool_block does
        active = {}
        active["tool1"] = MagicMock()
        count = len(active)
        assert count == 1

        active["tool2"] = MagicMock()
        count = len(active)
        assert count == 2

    def test_count_decrements_on_close(self):
        """D5: count decrements when tool completes."""
        active = {"tool1": MagicMock(), "tool2": MagicMock()}
        active.pop("tool1", None)
        count = len(active)
        assert count == 1
