"""ATX heading + rule grouping — 8 tests (R-A1 spec).

Verifies that an ATX heading immediately followed by `---` is emitted as a
single write_with_source call so Textual cannot interleave the two writes.

Run with:
    pytest -o "addopts=" tests/tui/test_response_flow_heading_wrap.py -v
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from rich.text import Text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine():
    """ResponseFlowEngine with mock panel + real CopyableRichLog."""
    from hermes_cli.tui.response_flow import ResponseFlowEngine
    from hermes_cli.tui.widgets import CopyableRichLog

    log = CopyableRichLog(markup=False)
    panel = MagicMock()
    panel._msg_id = 1
    panel._prose_blocks = []
    panel.response_log = log
    panel.app.get_css_variables.return_value = {
        "preview-syntax-theme": "monokai",
        "app-bg": "#1e1e1e",
    }
    engine = ResponseFlowEngine(panel=panel)
    engine._prose_log = log
    return engine, log


def _make_reasoning_engine():
    """ReasoningFlowEngine with mock panel (copied from test_streaming_engine_safety)."""
    from hermes_cli.tui.response_flow import ReasoningFlowEngine

    panel = MagicMock()
    panel.is_mounted = True
    panel.app.get_css_variables.return_value = {"preview-syntax-theme": "monokai"}
    panel.app._reasoning_rich_prose = True
    panel.app._citations_enabled = True
    panel.app._emoji_reasoning = False
    panel.app._emoji_images_enabled = False
    panel.app._emoji_registry = None
    # _DimRichLogProxy.__getattr__ delegates to panel._reasoning_log (MagicMock).
    # _resolve_log_width calls .scrollable_content_region.width — configure as int
    # so that the `> 0` comparison doesn't raise TypeError.
    panel._reasoning_log.scrollable_content_region.width = 0
    panel._reasoning_log.size.width = 0
    panel._reasoning_log.app.size.width = 80
    panel._plain_lines = []
    engine = ReasoningFlowEngine(panel=panel)
    return engine, panel


# ---------------------------------------------------------------------------
# TestHeadingRuleGrouping — 7 tests
# ---------------------------------------------------------------------------

class TestHeadingRuleGrouping:

    def test_h2_short_emits_single_grouped_write(self):
        engine, log = _make_engine()
        mock_write = MagicMock()
        engine._prose_log.write_with_source = mock_write

        # "---" is delayed by one StreamingBlockBuffer tick; need a third line
        engine.process_line("## Short")
        engine.process_line("---")
        engine.process_line("x")  # triggers _emit_rule for buffered "---"

        # "x" is buffered — only the heading+rule write has fired
        assert mock_write.call_count == 1, (
            f"expected 1 write_with_source call, got {mock_write.call_count}"
        )
        payload: Text = mock_write.call_args_list[0][0][0]
        assert "Short" in payload.plain, f"heading text not in payload: {payload.plain!r}"
        assert "─" in payload.plain, f"rule chars not in payload: {payload.plain!r}"
        # rule must come after heading text
        assert payload.plain.index("Short") < payload.plain.index("─"), (
            "rule chars appeared before heading text"
        )

    def test_h2_wrapping_emits_single_grouped_write(self):
        engine, log = _make_engine()
        mock_write = MagicMock()
        engine._prose_log.write_with_source = mock_write

        long_heading = "## " + "x " * 40  # 320 chars — wider than any test viewport
        engine.process_line(long_heading)
        engine.process_line("---")
        engine.process_line("x")

        assert mock_write.call_count == 1, (
            f"expected 1 write_with_source call, got {mock_write.call_count}"
        )
        payload: Text = mock_write.call_args_list[0][0][0]
        assert "x " in payload.plain, "heading text not in payload"
        assert "─" in payload.plain, "rule chars not in payload"

    def test_h2_grouped_write_text_contains_rule_below_text(self):
        engine, log = _make_engine()
        mock_write = MagicMock()
        engine._prose_log.write_with_source = mock_write

        engine.process_line("## Short")
        engine.process_line("---")
        engine.process_line("x")

        assert mock_write.call_count == 1
        payload: Text = mock_write.call_args_list[0][0][0]
        assert "\n" in payload.plain, "newline must separate heading from rule"
        newline_pos = payload.plain.index("\n")
        rule_pos = payload.plain.index("─")  # U+2500 produced by _make_rule
        assert newline_pos < rule_pos, "rule chars must be after the newline"
        assert "─" not in payload.plain[:newline_pos], "no rule chars before the newline"

    def test_hr_alone_unchanged(self):
        engine, log = _make_engine()
        mock_write = MagicMock()
        engine._prose_log.write_with_source = mock_write

        # "---" alone — no preceding heading
        engine.process_line("---")
        engine.process_line("x")  # triggers _emit_rule for buffered "---"

        assert mock_write.call_count == 1, (
            f"expected 1 write_with_source call, got {mock_write.call_count}"
        )
        payload: Text = mock_write.call_args_list[0][0][0]
        assert all(c == "─" for c in payload.plain), (
            f"standalone rule payload must be only rule chars, got: {payload.plain!r}"
        )
        assert "\n" not in payload.plain, "standalone rule must not contain newline"
        assert engine._pending_heading is None

    def test_setext_in_base_engine_promotes_to_single_write_no_stash(self):
        # Do NOT mock write_with_source — use live log._plain_lines
        engine, log = _make_engine()

        engine.process_line("Heading")  # buffered for setext lookahead
        engine.process_line("=====")   # setext H1 — promoted to one styled write
        engine.flush()

        # Setext-promoted string from StreamingBlockBuffer begins with ESC, not '#',
        # so _MD_HEADING_RE does not match → _pending_heading never set.
        assert engine._pending_heading is None
        assert any("Heading" in line for line in log._plain_lines), (
            f"promoted setext heading not in _plain_lines: {log._plain_lines}"
        )
        assert not any("=====" in line for line in log._plain_lines), (
            "setext underline must not appear in _plain_lines"
        )
        assert len([l for l in log._plain_lines if "Heading" in l]) == 1, (
            "setext heading should appear exactly once"
        )

    def test_h2_rule_triggered_by_flush_emits_single_grouped_write(self):
        engine, log = _make_engine()
        mock_write = MagicMock()
        engine._prose_log.write_with_source = mock_write

        engine.process_line("## End heading")   # buffered
        engine.process_line("---")              # heading returned → stashed; "---" buffered
        engine.flush()  # first _flush_block_buf returns "---" → _emit_rule merges stash

        assert mock_write.call_count == 1, (
            f"expected 1 write_with_source call, got {mock_write.call_count}"
        )
        payload: Text = mock_write.call_args_list[0][0][0]
        assert "End heading" in payload.plain, f"heading not in payload: {payload.plain!r}"
        assert "─" in payload.plain, "rule chars not in payload"
        end_idx = payload.plain.index("End heading")
        rule_idx = payload.plain.index("─")
        assert end_idx < rule_idx, "rule must come after heading text"

    def test_heading_at_turn_end_no_rule_is_emitted(self):
        engine, log = _make_engine()
        mock_write = MagicMock()
        engine._prose_log.write_with_source = mock_write

        engine.process_line("## Final heading")  # buffered
        engine.flush()  # _flush_block_buf stashes heading; flush() drains it

        assert mock_write.call_count == 1, (
            f"expected 1 write_with_source call, got {mock_write.call_count}"
        )
        payload: Text = mock_write.call_args_list[0][0][0]
        assert "Final heading" in payload.plain, f"heading not in payload: {payload.plain!r}"
        assert "─" not in payload.plain, (
            f"rule chars must not appear when heading ends turn without '---': {payload.plain!r}"
        )


# ---------------------------------------------------------------------------
# TestReasoningEngineParity — 1 test
# ---------------------------------------------------------------------------

class TestReasoningEngineParity:

    def test_reasoning_engine_h2_uses_same_grouped_write(self):
        engine, panel = _make_reasoning_engine()
        mock_write = MagicMock()
        engine._prose_log.write_with_source = mock_write

        # ReasoningFlowEngine flushes _block_buf on every process_line,
        # so only two calls are needed (no third trigger line required).
        engine.process_line("## Reason heading")   # flushed immediately → stashed
        engine.process_line("---")                 # "---" flushed → _emit_rule merges

        assert mock_write.call_count == 1, (
            f"expected 1 write_with_source call, got {mock_write.call_count}"
        )
        payload: Text = mock_write.call_args_list[0][0][0]
        assert "Reason heading" in payload.plain, (
            f"heading not in payload: {payload.plain!r}"
        )
        assert "─" in payload.plain, "rule chars not in payload"
        heading_idx = payload.plain.index("Reason heading")
        rule_idx = payload.plain.index("─")
        assert heading_idx < rule_idx, "rule must come after heading text"
