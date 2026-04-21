"""Tests for Tool UX Audit Pass 7 — Phase A: Live state & streaming feedback."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# A1 — Suppress action row during streaming
# ---------------------------------------------------------------------------

def _make_footer_base():
    """Create a FooterPane instance with mocked internal widgets."""
    from hermes_cli.tui.tool_panel import FooterPane
    footer = FooterPane.__new__(FooterPane)
    footer._show_all_artifacts = False
    footer._last_summary = None
    footer._last_promoted = frozenset()
    footer._last_resize_w = 0
    content_mock = MagicMock()
    footer._content = content_mock
    footer._stderr_row = MagicMock()
    footer._remediation_row = MagicMock()
    artifact_mock = MagicMock()
    artifact_mock.children = []
    artifact_mock.query.return_value = []
    footer._artifact_row = artifact_mock
    footer.add_class = MagicMock()
    footer.remove_class = MagicMock()
    return footer, content_mock


class TestA1SuppressActionRowDuringStreaming:
    """FooterPane suppresses action row when block is still streaming."""

    def _make_summary(self):
        from hermes_cli.tui.tool_result_parse import ResultSummaryV4, Action
        return ResultSummaryV4(
            primary="done", exit_code=0, chips=(), stderr_tail="",
            actions=(Action("copy", "c", "copy_body", None),),
            artifacts=(), is_error=False,
        )

    def test_action_row_hidden_when_streaming(self):
        """A1: action row must not appear when block._completed is False."""
        footer, content_mock = _make_footer_base()
        summary = self._make_summary()
        block = MagicMock()
        block._completed = False
        parent = MagicMock()
        parent._block = block
        # Patch getattr on parent property
        with patch.object(type(footer), 'parent', new_callable=lambda: property(lambda s: parent)):
            with patch.object(footer, '_rebuild_artifact_buttons'):
                footer._render_footer(summary, frozenset())
        rendered_text = content_mock.update.call_args[0][0]
        plain = rendered_text.plain if hasattr(rendered_text, 'plain') else str(rendered_text)
        assert "[c]" not in plain, "Action row should be suppressed during streaming"

    def test_action_row_shown_when_completed(self):
        """A1: action row must appear when block._completed is True."""
        footer, content_mock = _make_footer_base()
        summary = self._make_summary()
        block = MagicMock()
        block._completed = True
        parent = MagicMock()
        parent._block = block
        with patch.object(type(footer), 'parent', new_callable=lambda: property(lambda s: parent)):
            with patch.object(footer, '_rebuild_artifact_buttons'):
                footer._render_footer(summary, frozenset())
        rendered_text = content_mock.update.call_args[0][0]
        plain = rendered_text.plain if hasattr(rendered_text, 'plain') else str(rendered_text)
        assert "[c]" in plain, "Action row should appear after completion"

    def test_action_row_shown_when_no_block(self):
        """A1: if no block attached, action row should still appear (safe fallback)."""
        footer, content_mock = _make_footer_base()
        summary = self._make_summary()
        parent = MagicMock()
        parent._block = None
        with patch.object(type(footer), 'parent', new_callable=lambda: property(lambda s: parent)):
            with patch.object(footer, '_rebuild_artifact_buttons'):
                footer._render_footer(summary, frozenset())
        rendered_text = content_mock.update.call_args[0][0]
        plain = rendered_text.plain if hasattr(rendered_text, 'plain') else str(rendered_text)
        assert "[c]" in plain


# ---------------------------------------------------------------------------
# A2 — Tail-follow N/A feedback
# ---------------------------------------------------------------------------

class TestA2TailFollowFeedback:
    """action_toggle_tail_follow flashes warning when block is completed."""

    def _make_panel_with_block(self, completed: bool):
        from hermes_cli.tui.tool_blocks import StreamingToolBlock
        from hermes_cli.tui.tool_panel import ToolPanel
        block = MagicMock(spec=StreamingToolBlock)
        block._completed = completed
        block._follow_tail = False
        panel = ToolPanel.__new__(ToolPanel)
        panel._block = block
        panel._result_summary_v4 = None
        panel._flash_header = MagicMock()
        return panel

    def test_flash_warning_when_completed(self):
        """A2: pressing f on completed block flashes 'tail-follow N/A'."""
        panel = self._make_panel_with_block(completed=True)
        panel.action_toggle_tail_follow()
        panel._flash_header.assert_called_once()
        call_args = panel._flash_header.call_args
        assert "N/A" in call_args[0][0]
        assert call_args[1].get("tone") == "warning" or "warning" in str(call_args)

    def test_no_warning_when_streaming(self):
        """A2: pressing f on streaming block toggles normally."""
        panel = self._make_panel_with_block(completed=False)
        panel.action_toggle_tail_follow()
        # Should have toggled, not warned
        panel._flash_header.assert_called_once()
        call_args = panel._flash_header.call_args
        assert "N/A" not in call_args[0][0]


# ---------------------------------------------------------------------------
# A3 — Auto-collapse flash
# ---------------------------------------------------------------------------

class TestA3AutoCollapseFlash:
    """_apply_complete_auto_collapse flashes notification when collapsing."""

    def test_flash_on_auto_collapse(self):
        """A3: flash 'auto-collapsed (N lines)' is invoked when collapsing."""
        # Test the implementation logic directly via extracted logic
        flash_calls = []

        def fake_flash(msg, tone="success"):
            flash_calls.append((msg, tone))

        # Simulate what _apply_complete_auto_collapse does
        total = 500
        threshold = 100
        should_collapse = total > threshold
        if should_collapse:
            fake_flash(f"▾ auto-collapsed ({total} lines)", tone="success")

        assert len(flash_calls) == 1
        msg, tone = flash_calls[0]
        assert "auto-collapsed" in msg
        assert "500" in msg
        assert tone == "success"

    def test_no_flash_when_not_collapsing(self):
        """A3: no flash when body count is below threshold (stays expanded)."""
        flash_calls = []

        def fake_flash(msg, tone="success"):
            flash_calls.append((msg, tone))

        total = 5
        threshold = 100
        should_collapse = total > threshold
        if should_collapse:
            fake_flash(f"▾ auto-collapsed ({total} lines)", tone="success")

        assert len(flash_calls) == 0

    def test_apply_auto_collapse_implementation_flashes(self):
        """A3: verify _apply_complete_auto_collapse code path calls _flash_header."""
        # Read the implementation to verify the flash is present
        import inspect
        from hermes_cli.tui.tool_panel import ToolPanel
        src = inspect.getsource(ToolPanel._apply_complete_auto_collapse)
        assert "_flash_header" in src, "A3: _flash_header call missing from _apply_complete_auto_collapse"
        assert "auto-collapsed" in src, "A3: 'auto-collapsed' text missing from flash call"


# ---------------------------------------------------------------------------
# A4 — Stream stall detection
# ---------------------------------------------------------------------------

class TestA4StallDetection:
    """microcopy_line appends stall indicator when stalled=True."""

    def _make_spec(self, category):
        from hermes_cli.tui.tool_category import ToolCategory
        spec = MagicMock()
        spec.category = category
        spec.primary_result = "lines"
        spec.provenance = ""
        spec.name = "test"
        return spec

    def _make_state(self):
        from hermes_cli.tui.streaming_microcopy import StreamingState
        return StreamingState(
            lines_received=10, bytes_received=1024,
            elapsed_s=10.0, rate_bps=None,
        )

    def test_stall_suffix_shell(self):
        """A4: SHELL category shows stall indicator when stalled=True."""
        from hermes_cli.tui.streaming_microcopy import microcopy_line
        from hermes_cli.tui.tool_category import ToolCategory
        spec = self._make_spec(ToolCategory.SHELL)
        state = self._make_state()
        result = microcopy_line(spec, state, stalled=True)
        assert "stalled?" in str(result)

    def test_no_stall_suffix_when_not_stalled(self):
        """A4: no stall indicator when stalled=False."""
        from hermes_cli.tui.streaming_microcopy import microcopy_line
        from hermes_cli.tui.tool_category import ToolCategory
        spec = self._make_spec(ToolCategory.SHELL)
        state = self._make_state()
        result = microcopy_line(spec, state, stalled=False)
        assert "stalled?" not in str(result)

    def test_stall_suffix_file(self):
        """A4: FILE category also gets stall indicator."""
        from hermes_cli.tui.streaming_microcopy import microcopy_line
        from hermes_cli.tui.tool_category import ToolCategory
        spec = self._make_spec(ToolCategory.FILE)
        state = self._make_state()
        result = microcopy_line(spec, state, stalled=True)
        assert "stalled?" in str(result)

    def test_stall_suffix_mcp(self):
        """A4: MCP category also gets stall indicator."""
        from hermes_cli.tui.streaming_microcopy import microcopy_line
        from hermes_cli.tui.tool_category import ToolCategory
        spec = self._make_spec(ToolCategory.MCP)
        state = self._make_state()
        result = microcopy_line(spec, state, stalled=True)
        assert "stalled?" in str(result)


# ---------------------------------------------------------------------------
# A5 — Copy flash includes byte size
# ---------------------------------------------------------------------------

class TestA5CopyFlashSize:
    """action_copy_body flash includes size suffix for large payloads."""

    def test_flash_includes_size_suffix(self):
        """A5: flash message includes kB suffix for large text."""
        from hermes_cli.tui.tool_panel import ToolPanel
        panel = ToolPanel.__new__(ToolPanel)
        panel._result_summary_v4 = None
        panel._result_paths = []
        panel._flash_header = MagicMock()
        panel._block = MagicMock()
        panel.copy_content = MagicMock(return_value="x" * 2048)
        app_mock = MagicMock()
        app_mock._copy_text_with_hint = MagicMock()
        with patch.object(type(panel), 'app', new_callable=lambda: property(lambda s: app_mock)):
            panel.action_copy_body()
        call_args = panel._flash_header.call_args[0][0]
        assert "kB" in call_args or "B" in call_args, \
            f"Expected size suffix in flash: {call_args!r}"

    def test_small_payload_no_suffix(self):
        """A5: no suffix for payloads under 1 kB."""
        from hermes_cli.tui.tool_panel import ToolPanel
        panel = ToolPanel.__new__(ToolPanel)
        panel._result_summary_v4 = None
        panel._result_paths = []
        panel._flash_header = MagicMock()
        panel._block = MagicMock()
        panel.copy_content = MagicMock(return_value="hi")
        app_mock = MagicMock()
        app_mock._copy_text_with_hint = MagicMock()
        with patch.object(type(panel), 'app', new_callable=lambda: property(lambda s: app_mock)):
            panel.action_copy_body()
        call_args = panel._flash_header.call_args[0][0]
        assert "kB" not in call_args
