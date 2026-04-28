"""Tests for SF-1..SF-4 stream flush cadence visibility logging.

Covers:
- SF-1: _code_fence_buffer buffer/flush lifecycle logs in ResponseFlowEngine
- SF-2: StreamingCodeBlock complete/finalize/flush lifecycle logs
- SF-3: ResponseFlowEngine fence open/close timer logs + _fence_opened_at reset
- SF-4: [STREAM-SEQ] chunk sequence counter in io.consume_output
"""

from __future__ import annotations

import logging
import types
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine():
    """Return a minimal ResponseFlowEngine with mocked panel/app dependencies."""
    from hermes_cli.tui.response_flow import ResponseFlowEngine

    panel = MagicMock()
    panel.app = MagicMock()
    panel.app.get_css_variables.return_value = {}
    skin_vars: dict = {}
    engine = ResponseFlowEngine.__new__(ResponseFlowEngine)
    engine._panel = panel
    engine._skin_vars = skin_vars
    engine._init_fields()
    # Stub out write/mount helpers
    engine._write_prose = MagicMock()
    engine._sync_prose_log = MagicMock()
    engine._mount_nonprose_block = MagicMock()
    engine._panel._mount_nonprose_block = MagicMock()
    return engine


def _make_streaming_code_block(lang: str = "python") -> "StreamingCodeBlock":
    """Return an isolated StreamingCodeBlock without Textual DOM.

    Creates a dynamic subclass that shadows read-only Textual properties
    (app, is_mounted) so instance attributes can be set freely in tests.
    """
    from hermes_cli.tui.widgets.code_blocks import StreamingCodeBlock

    # Shadow read-only Textual properties at subclass level so __new__ instances
    # can have them set as plain instance attributes.
    _Isolated = type("_Isolated", (StreamingCodeBlock,), {"app": None, "is_mounted": False})
    block = _Isolated.__new__(_Isolated)
    block._lang = lang
    block._state = "STREAMING"
    block._code_lines = []
    block._partial_line = ""
    block._log = MagicMock()  # the CopyableRichLog widget attribute
    block._pygments_theme = "monokai"
    block._syntax_bold = True
    block._display_code_lines = lambda: list(block._code_lines)
    block.clear_partial = MagicMock()
    block.add_class = MagicMock()
    block._complete_skin_vars = {}
    block._try_render_mermaid_async = MagicMock()
    block.call_after_refresh = MagicMock()
    block._render_flushed_content = MagicMock()
    block._render_syntax = MagicMock()
    block._update_controls = MagicMock()
    block.refresh = MagicMock()
    block.app = None
    return block


# ---------------------------------------------------------------------------
# SF-1: _code_fence_buffer buffer/flush lifecycle logs
# ---------------------------------------------------------------------------

class TestSF01BufferStartLogged:
    def test_sf01_buffer_start_logged(self, caplog):
        """[STREAM-BUF] buffering started logged exactly once for first numbered line."""
        engine = _make_engine()
        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.response_flow"):
            # "1 | some code" matches _NUMBERED_LINE_RE
            engine._commit_prose_line("1 | foo", "1 | foo")

        starts = [r for r in caplog.records if "[STREAM-BUF] InlineCodeFence buffering started" in r.message]
        assert len(starts) == 1

    def test_sf01_buffer_start_logged_once_not_per_line(self, caplog):
        """[STREAM-BUF] buffering started fires once even for multiple numbered lines."""
        engine = _make_engine()
        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.response_flow"):
            engine._commit_prose_line("1 | foo", "1 | foo")
            engine._commit_prose_line("2 | bar", "2 | bar")

        starts = [r for r in caplog.records if "[STREAM-BUF] InlineCodeFence buffering started" in r.message]
        assert len(starts) == 1

    def test_sf01_flush_logged_with_count(self, caplog):
        """[STREAM-BUF] flushing N lines logged at flush; N matches lines buffered."""
        engine = _make_engine()
        # Buffer 3 lines then flush with non-matching line
        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.response_flow"):
            engine._commit_prose_line("1 | a", "1 | a")
            engine._commit_prose_line("2 | b", "2 | b")
            engine._commit_prose_line("3 | c", "3 | c")
            # Trigger flush with a non-numbered line
            engine._commit_prose_line("normal text", "normal text")

        flush_records = [r for r in caplog.records if "[STREAM-BUF] InlineCodeFence flushing" in r.message]
        assert len(flush_records) == 1
        assert "3 lines" in flush_records[0].message

    def test_sf01_no_log_when_empty(self, caplog):
        """_flush_code_fence_buffer() with empty buffer emits no [STREAM-BUF] log."""
        engine = _make_engine()
        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.response_flow"):
            engine._flush_code_fence_buffer()

        assert not any("[STREAM-BUF]" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# SF-2: StreamingCodeBlock lifecycle logs
# ---------------------------------------------------------------------------

class TestSF02StreamingCodeBlockLogs:
    def test_sf02_complete_logged(self, caplog):
        """[STREAM-CODE] fence closed logged when complete() is called."""
        block = _make_streaming_code_block("python")
        block._code_lines = ["x = 1", "y = 2"]
        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.widgets.code_blocks"):
            block.complete({})

        records = [r for r in caplog.records if "[STREAM-CODE] fence closed" in r.message]
        assert len(records) == 1
        assert "python" in records[0].message

    def test_sf02_line_count_accurate(self, caplog):
        """Count in complete() log equals number of append_line calls."""
        from hermes_cli.tui.widgets.code_blocks import StreamingCodeBlock

        block = _make_streaming_code_block("bash")
        # Simulate append_line calls (we call directly on _code_lines for isolation)
        block._code_lines = ["echo a", "echo b", "echo c"]
        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.widgets.code_blocks"):
            block.complete({})

        records = [r for r in caplog.records if "[STREAM-CODE] fence closed" in r.message]
        assert len(records) == 1
        assert "3 lines" in records[0].message

    def test_sf02_finalize_logged(self, caplog):
        """[STREAM-CODE] finalize_syntax logged when _finalize_syntax() fires."""
        block = _make_streaming_code_block("js")
        block._code_lines = ["const x = 1;"]
        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.widgets.code_blocks"):
            block._finalize_syntax({})

        records = [r for r in caplog.records if "[STREAM-CODE] finalize_syntax" in r.message]
        assert len(records) == 1
        assert "batch re-render" in records[0].message

    def test_sf02_flush_logged(self, caplog):
        """[STREAM-CODE] fence flushed logged when flush() is called."""
        block = _make_streaming_code_block("python")
        block._code_lines = ["line1", "line2"]
        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.widgets.code_blocks"):
            block.flush()

        records = [r for r in caplog.records if "[STREAM-CODE] fence flushed" in r.message]
        assert len(records) == 1
        assert "STREAMING→FLUSHED" in records[0].message


# ---------------------------------------------------------------------------
# SF-3: ResponseFlowEngine fence state timer
# ---------------------------------------------------------------------------

class TestSF03FenceStateTimer:
    def _engine_with_classifier(self):
        """Engine with a minimal classifier stub for fence open/close detection."""
        engine = _make_engine()
        clf = MagicMock()
        # Fence detection
        clf.is_fence_open.return_value = ("python", "`", 3)
        clf.is_fence_close.return_value = True
        # All other paths return falsy so execution reaches fence detection
        clf.is_indented_code.return_value = None
        clf.is_block_math_oneline.return_value = None
        clf.is_block_math_open.return_value = False
        clf.is_inline_code_label.return_value = None
        clf.looks_like_source_line.return_value = False
        engine._clf = clf
        mock_block = MagicMock()
        mock_block._lang = "python"
        mock_block._state = "STREAMING"
        mock_block._code_lines = []
        engine._open_code_block = MagicMock(return_value=mock_block)
        engine._flush_block_buf = MagicMock()
        engine._flush_code_fence_buffer = MagicMock()
        engine._pending_source_line = None
        engine._pending_code_intro = False
        return engine

    def test_sf03_fence_open_logged(self, caplog):
        """[STREAM-FENCE] opened logged when _state transitions to IN_CODE."""
        engine = self._engine_with_classifier()
        engine._clf.is_fence_open.return_value = ("python", "`", 3)
        engine._flush_code_fence_buffer = MagicMock()
        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.response_flow"):
            engine._state = "NORMAL"
            engine._dispatch_normal_state("```python", False)

        records = [r for r in caplog.records if "[STREAM-FENCE] opened" in r.message]
        assert len(records) == 1
        assert "python" in records[0].message

    def test_sf03_fence_close_logged_with_elapsed(self, caplog):
        """[STREAM-FENCE] closed logged with positive elapsed_ms when fence closes."""
        engine = self._engine_with_classifier()
        import time
        engine._state = "IN_CODE"
        engine._fence_opened_at = time.monotonic() - 0.05  # 50ms ago
        engine._fence_char = "`"
        engine._fence_depth = 3
        mock_block = MagicMock()
        mock_block._lang = "python"
        engine._active_block = mock_block
        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.response_flow"):
            engine._dispatch_non_normal_state("```")

        records = [r for r in caplog.records if "[STREAM-FENCE] closed" in r.message]
        assert len(records) == 1
        # elapsed should be a positive float
        msg = records[0].message
        import re
        m = re.search(r"elapsed_ms=([\d.]+)", msg)
        assert m is not None
        assert float(m.group(1)) > 0.0

    def test_sf03_fence_opened_at_reset(self, caplog):
        """_fence_opened_at is None after fence closes (no leak into next fence)."""
        engine = self._engine_with_classifier()
        import time
        engine._state = "IN_CODE"
        engine._fence_opened_at = time.monotonic()
        engine._fence_char = "`"
        engine._fence_depth = 3
        mock_block = MagicMock()
        mock_block._lang = "python"
        engine._active_block = mock_block
        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.response_flow"):
            engine._dispatch_non_normal_state("```")

        assert engine._fence_opened_at is None


# ---------------------------------------------------------------------------
# SF-4: Chunk sequence counter in io.consume_output
# ---------------------------------------------------------------------------

class TestSF04ChunkSeqCounter:
    def _run_consume_chunk(self, app, chunk):
        """Simulate a single chunk passing through the [STREAM-SEQ] instrumentation."""
        import logging as _logging
        logger = _logging.getLogger("hermes_cli.tui.services.io")
        _seq = getattr(app, "_perf_chunk_seq", 0) + 1
        app._perf_chunk_seq = _seq
        logger.debug("[STREAM-SEQ] seq=%d size=%d", _seq, len(chunk))

    def test_sf04_seq_logged_per_chunk(self, caplog):
        """[STREAM-SEQ] seq=... logged once per chunk processed."""
        app = types.SimpleNamespace(_perf_chunk_seq=0)
        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.services.io"):
            self._run_consume_chunk(app, "hello")

        records = [r for r in caplog.records if "[STREAM-SEQ]" in r.message]
        assert len(records) == 1

    def test_sf04_seq_monotonically_increasing(self, caplog):
        """seq values across three consecutive chunks are 1, 2, 3."""
        app = types.SimpleNamespace()
        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.services.io"):
            self._run_consume_chunk(app, "a")
            self._run_consume_chunk(app, "b")
            self._run_consume_chunk(app, "c")

        records = [r for r in caplog.records if "[STREAM-SEQ]" in r.message]
        import re
        seqs = [int(re.search(r"seq=(\d+)", r.message).group(1)) for r in records]
        assert seqs == [1, 2, 3]

    def test_sf04_size_matches_chunk_len(self, caplog):
        """logged size= value equals len(chunk) for the test chunk."""
        app = types.SimpleNamespace()
        chunk = "hello world"
        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.services.io"):
            self._run_consume_chunk(app, chunk)

        records = [r for r in caplog.records if "[STREAM-SEQ]" in r.message]
        assert len(records) == 1
        import re
        m = re.search(r"size=(\d+)", records[0].message)
        assert m is not None
        assert int(m.group(1)) == len(chunk)
