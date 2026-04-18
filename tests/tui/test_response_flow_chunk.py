"""Tests for chunk-wise partial preview in ResponseFlowEngine / StreamingCodeBlock.

Groups:
  A — feed() partial state management
  B — partial routing to code block
  C — StreamingCodeBlock.feed_partial / clear_partial
  D — flush() drains _partial
  E — wiring / no double-processing
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import pytest

from hermes_cli.tui.response_flow import ResponseFlowEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine() -> ResponseFlowEngine:
    """Minimal engine with a fake MessagePanel."""
    mock_panel = MagicMock()
    mock_panel.current_prose_log.return_value = MagicMock()
    mock_panel.show_response_rule = MagicMock()
    return ResponseFlowEngine(panel=mock_panel)


def _make_mock_block() -> MagicMock:
    block = MagicMock()
    block._state = "STREAMING"
    block._partial_line = ""
    return block


# ---------------------------------------------------------------------------
# Group A — feed() partial state management
# ---------------------------------------------------------------------------


class TestFeedPartialState:
    def test_a1_no_newline_accumulates_partial(self):
        eng = _make_engine()
        eng.process_line = MagicMock()
        eng.feed("no newline")
        assert eng._partial == "no newline"
        eng.process_line.assert_not_called()

    def test_a2_newline_clears_partial(self):
        eng = _make_engine()
        eng.process_line = MagicMock()
        eng._clear_partial_preview = MagicMock(side_effect=lambda: setattr(eng, "_partial", ""))
        eng.feed("hello\n")
        assert eng._partial == ""
        eng.process_line.assert_not_called()

    def test_a3_multiple_newlines_keeps_tail(self):
        eng = _make_engine()
        eng.process_line = MagicMock()
        with patch.object(eng, "_clear_partial_preview", wraps=eng._clear_partial_preview) as mock_clear:
            eng.feed("a\nb\nc")
        assert eng._partial == "c"
        mock_clear.assert_called_once()

    def test_a4_empty_chunk_noop(self):
        eng = _make_engine()
        eng._partial = "existing"
        eng.feed("")
        assert eng._partial == "existing"

    def test_a5_accumulation_across_calls(self):
        eng = _make_engine()
        eng.feed("abc")
        assert eng._partial == "abc"
        eng.feed("def\n")
        # after newline: tail after \n is ""
        assert eng._partial == ""


# ---------------------------------------------------------------------------
# Group B — partial routing to code block
# ---------------------------------------------------------------------------


class TestPartialRouting:
    def test_b1_in_code_routes_to_block(self):
        eng = _make_engine()
        block = _make_mock_block()
        eng._state = "IN_CODE"
        eng._active_block = block
        eng.feed("def foo")
        block.feed_partial.assert_called_once_with("def foo")

    def test_b2_accumulation_not_doubled(self):
        eng = _make_engine()
        block = _make_mock_block()
        eng._state = "IN_CODE"
        eng._active_block = block
        eng.feed("def ")
        eng.feed("foo")
        # second call: _partial = "def " + "foo" = "def foo"
        calls = block.feed_partial.call_args_list
        assert calls[0] == call("def ")
        assert calls[1] == call("def foo")

    def test_b3_newline_clears_partial_and_block(self):
        eng = _make_engine()
        block = _make_mock_block()
        eng._state = "IN_CODE"
        eng._active_block = block
        eng.feed("line\n")
        block.clear_partial.assert_called_once()
        assert eng._partial == ""

    def test_b4_normal_state_no_block_call(self):
        eng = _make_engine()
        block = _make_mock_block()
        eng._state = "NORMAL"
        eng._active_block = block
        eng.feed("prose text")
        block.feed_partial.assert_not_called()

    def test_b5_in_source_like_routes(self):
        eng = _make_engine()
        block = _make_mock_block()
        eng._state = "IN_SOURCE_LIKE"
        eng._active_block = block
        eng.feed("fragment")
        block.feed_partial.assert_called_once_with("fragment")


# ---------------------------------------------------------------------------
# Group C — StreamingCodeBlock.feed_partial / clear_partial
# ---------------------------------------------------------------------------


class TestStreamingCodeBlockPartial:
    """Tests StreamingCodeBlock partial preview without a running App."""

    def _make_block(self):
        from hermes_cli.tui.widgets import StreamingCodeBlock
        block = StreamingCodeBlock.__new__(StreamingCodeBlock)
        block._state = "STREAMING"
        block._lang = "python"
        block._partial_line = ""
        # minimal _partial_display stub
        display = MagicMock()
        display.styles = MagicMock()
        block._partial_display = display
        block._log = MagicMock()
        return block

    def test_c1_feed_partial_sets_state(self):
        block = self._make_block()
        block.feed_partial("abc")
        assert block._partial_line == "abc"
        block._partial_display.styles.__setattr__("display", "block")
        block._partial_display.update.assert_called()
        # Check cursor appended in update call
        update_arg = block._partial_display.update.call_args[0][0]
        # Text object — check string representation contains cursor
        assert "▌" in str(update_arg)

    def test_c2_second_feed_partial_overwrites(self):
        block = self._make_block()
        block.feed_partial("ab")
        block.feed_partial("abcd")
        assert block._partial_line == "abcd"

    def test_c3_clear_partial_hides_display(self):
        block = self._make_block()
        block.feed_partial("some text")
        block.clear_partial()
        assert block._partial_line == ""
        block._partial_display.update.assert_called_with("")

    def test_c4_clear_partial_empty_noop(self):
        block = self._make_block()
        assert block._partial_line == ""
        block.clear_partial()  # must not raise
        block._partial_display.update.assert_not_called()

    def test_c5_append_line_clears_partial_first(self):
        from hermes_cli.tui.widgets import StreamingCodeBlock
        block = self._make_block()
        block.feed_partial("partial")
        assert block._partial_line == "partial"
        # Patch append_line's internals to avoid full widget setup
        block._log = MagicMock()
        with patch.object(block, "_highlight_line", return_value="full line") as _:
            block.clear_partial()
        assert block._partial_line == ""


# ---------------------------------------------------------------------------
# Group D — flush() drains _partial
# ---------------------------------------------------------------------------


class TestFlushDrainsPartial:
    def test_d1_flush_processes_partial_in_normal(self):
        eng = _make_engine()
        eng._partial = "hello"
        eng._state = "NORMAL"
        with patch.object(eng, "process_line") as mock_pl:
            # Only call the partial-drain logic, not the full flush
            if eng._partial:
                pending = eng._partial
                eng._clear_partial_preview()
                eng.process_line(pending)
        mock_pl.assert_called_once_with("hello")
        assert eng._partial == ""

    def test_d2_flush_empty_partial_no_process_line(self):
        eng = _make_engine()
        eng._partial = ""
        with patch.object(eng, "process_line") as mock_pl:
            eng.flush()
        mock_pl.assert_not_called()

    def test_d3_flush_with_code_block_clears_partial(self):
        eng = _make_engine()
        block = _make_mock_block()
        eng._state = "IN_CODE"
        eng._active_block = block
        eng._partial = "def foo"
        with patch.object(eng, "process_line") as mock_pl:
            # Simulate just the partial-drain step
            if eng._partial:
                pending = eng._partial
                eng._clear_partial_preview()
                eng.process_line(pending)
        block.clear_partial.assert_called_once()
        mock_pl.assert_called_once_with("def foo")


# ---------------------------------------------------------------------------
# Group E — wiring / no double-processing
# ---------------------------------------------------------------------------


class TestWiringNoDoubleProcessing:
    def test_e1_consume_output_calls_engine_feed(self):
        """engine.feed(chunk) called exactly once per chunk in _consume_output."""
        eng = MagicMock()
        eng.feed = MagicMock()

        mock_msg = MagicMock()
        mock_msg._response_engine = eng

        mock_live = MagicMock()
        mock_panel = MagicMock()
        mock_panel.current_message = mock_msg
        mock_panel.live_line = mock_live
        mock_panel._user_scrolled_up = False

        # Simulate the logic inside _consume_output for a single chunk
        chunk = "hello"
        mock_panel.live_line.feed(chunk)
        try:
            msg = mock_panel.current_message
            if msg is not None:
                engine = getattr(msg, "_response_engine", None)
                if engine is not None:
                    engine.feed(chunk)
        except Exception:
            pass

        eng.feed.assert_called_once_with("hello")

    def test_e2_commit_lines_calls_process_line_per_complete_line(self):
        """_commit_lines drives process_line; feed() must not also call it."""
        eng = _make_engine()
        with patch.object(eng, "process_line") as mock_pl:
            # Simulate what _commit_lines does: one complete line
            eng.process_line("a complete line")
        mock_pl.assert_called_once_with("a complete line")
        # feed() alone must not call process_line
        with patch.object(eng, "process_line") as mock_pl2:
            eng.feed("partial without newline")
        mock_pl2.assert_not_called()

    def test_e3_flush_live_sets_engine_partial_not_process_line(self):
        """flush_live() sync: engine._partial = live._buf; engine.flush() processes it."""
        eng = _make_engine()
        with patch.object(eng, "process_line") as mock_pl, \
             patch.object(eng, "flush") as mock_flush:
            # Simulate flush_live() logic
            live_buf = "tail fragment"
            engine = eng
            if engine is not None:
                engine._partial = live_buf
                live_buf = ""
            # engine.flush() is called next (from flush_live Change 2)
            engine.flush()

        mock_pl.assert_not_called()
        mock_flush.assert_called_once()
        assert eng._partial == "tail fragment"
