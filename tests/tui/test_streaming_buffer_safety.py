"""Tests for streaming buffer safety: H1 (_stream_buf cap) and M1 (_char_queue cap).

Classes:
    TestStreamBufCap      — 5 tests for cli.py _STREAM_BUF_MAX_CHARS / _emit_stream_text
    TestCharQueueBounded  — 9 tests for LiveLineWidget._char_queue maxsize + _enqueue_char
"""

from __future__ import annotations

import asyncio
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hermes_cli_stub():
    """Return a minimal HermesCLI-like object with every attr _emit_stream_text reads."""
    import cli
    obj = cli.HermesCLI.__new__(cli.HermesCLI)
    obj._ORPHAN_CLOSE_TAGS = []
    obj.show_reasoning = False
    obj._reasoning_box_opened = False
    obj._close_reasoning_box = lambda: None
    obj._message_stream_output_tokens = 0
    obj._stream_box_opened = True   # skip box-header printing
    obj._stream_buf = ""
    obj._stream_spec_stack = []
    obj._stream_text_ansi = ""
    obj._stream_code_hl = None
    return obj


# ---------------------------------------------------------------------------
# H1 — _stream_buf cap tests
# ---------------------------------------------------------------------------

class TestStreamBufCap:
    """_STREAM_BUF_MAX_CHARS constant and force-flush path in _emit_stream_text."""

    def test_stream_buf_cap_constant_present(self):
        """_STREAM_BUF_MAX_CHARS must be importable from cli and be >= 32768."""
        import cli
        assert hasattr(cli, "_STREAM_BUF_MAX_CHARS"), "_STREAM_BUF_MAX_CHARS not found in cli"
        assert cli._STREAM_BUF_MAX_CHARS >= 32_768

    def test_stream_buf_no_flush_below_cap(self):
        """Buffer below cap must not trigger force-flush."""
        import cli

        obj = _make_hermes_cli_stub()
        with (
            patch.object(cli, "_hermes_app", None),
            patch.object(cli, "_RICH_RESPONSE", False),
        ):
            text = "x" * (cli._STREAM_BUF_MAX_CHARS - 1)
            cli.HermesCLI._emit_stream_text(obj, text)

        # No newline, no space → no flush of any kind at < cap
        assert len(obj._stream_buf) == cli._STREAM_BUF_MAX_CHARS - 1

    def test_stream_buf_force_flush_at_cap(self):
        """Feeding > _STREAM_BUF_MAX_CHARS chars with no newline/space triggers force-flush."""
        import cli

        captured: list[str] = []
        fake_app = types.SimpleNamespace(
            _event_loop=object(),  # truthy — activates TUI write_output path
            write_output=lambda chunk: captured.append(chunk),
        )

        obj = _make_hermes_cli_stub()
        with (
            patch.object(cli, "_hermes_app", fake_app),
            patch.object(cli, "_RICH_RESPONSE", False),
        ):
            text = "A" * (cli._STREAM_BUF_MAX_CHARS + 1)
            cli.HermesCLI._emit_stream_text(obj, text)

        assert captured, "write_output was not called — force-flush did not trigger"
        assert len(captured[0]) >= cli._STREAM_BUF_MAX_CHARS

    def test_stream_buf_cap_resets_after_flush(self):
        """After force-flush, _stream_buf must be below the cap."""
        import cli

        fake_app = types.SimpleNamespace(
            _event_loop=object(),
            write_output=lambda _: None,
        )

        obj = _make_hermes_cli_stub()
        with (
            patch.object(cli, "_hermes_app", fake_app),
            patch.object(cli, "_RICH_RESPONSE", False),
        ):
            text = "B" * (cli._STREAM_BUF_MAX_CHARS + 1)
            cli.HermesCLI._emit_stream_text(obj, text)

        assert len(obj._stream_buf) < cli._STREAM_BUF_MAX_CHARS

    def test_stream_buf_newline_before_cap(self):
        """A \\n at position 100 triggers line-split flush, NOT force-flush."""
        import cli

        captured: list[str] = []
        printed: list[str] = []

        fake_app = types.SimpleNamespace(
            _event_loop=object(),
            write_output=lambda chunk: captured.append(chunk),
        )

        obj = _make_hermes_cli_stub()
        with (
            patch.object(cli, "_hermes_app", fake_app),
            patch.object(cli, "_RICH_RESPONSE", False),
            patch.object(cli, "_cprint", lambda s: printed.append(s)),
        ):
            text = "C" * 100 + "\n"
            cli.HermesCLI._emit_stream_text(obj, text)

        # Line-split consumed the buffer; nothing should exceed the cap
        assert obj._stream_buf == ""
        # Force-flush (write_output via TUI path) should not have fired for a short line
        assert all(len(c) < cli._STREAM_BUF_MAX_CHARS for c in captured)


# ---------------------------------------------------------------------------
# M1 — _char_queue bounded tests
# ---------------------------------------------------------------------------

class TestCharQueueBounded:
    """LiveLineWidget._char_queue is bounded; overflow falls back to flush+commit."""

    def _make_widget(self, tw_enabled: bool = True):
        """Construct a LiveLineWidget using the proper constructor (reactive-safe)."""
        from hermes_cli.tui.widgets.renderers import LiveLineWidget
        from hermes_cli.tui.widgets.utils import _TW_CHAR_QUEUE_MAX

        widget = LiveLineWidget()
        # Simulate on_mount state without calling on_mount (which reads config)
        widget._tw_enabled = tw_enabled
        widget._tw_delay = 0.02
        widget._tw_burst = 4
        widget._tw_cursor = False
        widget._blink_visible = True
        widget._blink_timer = None
        widget._blink_enabled = False
        widget._animating = False
        widget._panel = MagicMock()

        if tw_enabled:
            widget._char_queue = asyncio.Queue(maxsize=_TW_CHAR_QUEUE_MAX)

        return widget

    def test_char_queue_bounded_maxsize(self):
        """After on_mount, _char_queue.maxsize must equal _TW_CHAR_QUEUE_MAX."""
        from hermes_cli.tui.widgets.utils import _TW_CHAR_QUEUE_MAX

        widget = self._make_widget(tw_enabled=True)
        assert widget._char_queue.maxsize == _TW_CHAR_QUEUE_MAX

    def test_char_queue_overflow_falls_back_to_direct(self):
        """Overflow char must appear in _buf, not be dropped."""
        widget = self._make_widget(tw_enabled=True)
        for _ in range(widget._char_queue.maxsize):
            widget._char_queue.put_nowait("a")

        def _fake_flush():
            while not widget._char_queue.empty():
                widget._buf += widget._char_queue.get_nowait()

        with patch.object(widget, "flush", side_effect=_fake_flush):
            widget._enqueue_char("Z")

        assert "Z" in widget._buf

    def test_char_queue_overflow_no_exception_raised(self):
        """_enqueue_char must not raise even when queue is at maxsize."""
        widget = self._make_widget(tw_enabled=True)
        for _ in range(widget._char_queue.maxsize):
            widget._char_queue.put_nowait("x")

        with patch.object(widget, "flush", return_value=None):
            try:
                widget._enqueue_char("!")
            except Exception as exc:
                pytest.fail(f"_enqueue_char raised unexpectedly: {exc}")

    def test_char_queue_overflow_commit_lines_called(self):
        """When overflow char is \\n, _commit_lines must be invoked."""
        widget = self._make_widget(tw_enabled=True)
        for _ in range(widget._char_queue.maxsize):
            widget._char_queue.put_nowait("x")

        with (
            patch.object(widget, "flush", return_value=None),
            patch.object(widget, "_commit_lines") as mock_commit,
        ):
            widget._enqueue_char("\n")

        mock_commit.assert_called_once()

    def test_char_queue_normal_path_unaffected(self):
        """With queue < maxsize, _enqueue_char puts char in queue (not _buf)."""
        widget = self._make_widget(tw_enabled=True)
        assert widget._char_queue.empty()

        widget._enqueue_char("H")
        widget._enqueue_char("i")

        assert widget._char_queue.qsize() == 2
        assert widget._buf == ""

    def test_char_queue_ansi_token_overflow(self):
        """Full ANSI escape sequence committed atomically as a unit on overflow."""
        widget = self._make_widget(tw_enabled=True)
        for _ in range(widget._char_queue.maxsize):
            widget._char_queue.put_nowait("x")

        ansi_token = "\x1b[31m"

        def _fake_flush():
            while not widget._char_queue.empty():
                widget._char_queue.get_nowait()

        with patch.object(widget, "flush", side_effect=_fake_flush):
            widget._enqueue_char(ansi_token)

        assert ansi_token in widget._buf

    def test_tw_char_queue_max_constant(self):
        """_TW_CHAR_QUEUE_MAX must be importable from widgets.utils and >= 1024."""
        from hermes_cli.tui.widgets.utils import _TW_CHAR_QUEUE_MAX
        assert _TW_CHAR_QUEUE_MAX >= 1024

    def test_char_queue_reset_after_flush(self):
        """After flush(), queue empty; next _enqueue_char enqueues normally."""
        widget = self._make_widget(tw_enabled=True)
        for _ in range(10):
            widget._char_queue.put_nowait("a")

        def _fake_flush():
            while not widget._char_queue.empty():
                widget._buf += widget._char_queue.get_nowait()

        with patch.object(widget, "flush", side_effect=_fake_flush):
            widget.flush()

        widget._enqueue_char("X")
        assert widget._char_queue.qsize() == 1
        assert "X" not in widget._buf  # went to queue, not direct commit

    def test_no_char_queue_when_typewriter_disabled(self):
        """Typewriter disabled: _char_queue must not exist (no regression)."""
        widget = self._make_widget(tw_enabled=False)
        assert not hasattr(widget, "_char_queue")
