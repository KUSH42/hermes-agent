"""Tests for streaming pipeline fixes in cli.py.

Covers:
- Orphan </think> tag stripping in _emit_stream_text
- Word-boundary flush skipping unclosed markdown delimiters
- Reasoning _cprint isolation in TUI mode (no leak to response RichLog)
"""

import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers — minimal CLI stubs
# ---------------------------------------------------------------------------


def _make_emit_cli(stream_buf="", show_reasoning=False):
    """Minimal HermesCLI stub for _emit_stream_text."""
    from cli import HermesCLI

    cli = HermesCLI.__new__(HermesCLI)
    cli._stream_buf = stream_buf
    cli._stream_text_ansi = ""
    cli._stream_box_opened = True
    cli._stream_started = True
    cli.show_reasoning = show_reasoning
    cli._reasoning_box_opened = False
    cli._deferred_content = ""
    cli._stream_block_buf = MagicMock()
    cli._stream_block_buf.process_line = MagicMock(side_effect=lambda x: x)
    cli._stream_code_hl = MagicMock()
    cli._stream_code_hl.process_line = MagicMock(side_effect=lambda x: x)
    return cli


def _make_reasoning_cli(reasoning_buf=""):
    """Minimal HermesCLI stub for _stream_reasoning_delta."""
    from cli import HermesCLI

    cli = HermesCLI.__new__(HermesCLI)
    cli._reasoning_buf = reasoning_buf
    cli._reasoning_box_opened = True
    cli._reasoning_stream_started = False
    cli._reasoning_shown_this_turn = False
    cli._stream_box_opened = False
    cli._rich_reasoning = False
    cli.show_reasoning = True
    return cli


def _make_stream_delta_cli(show_reasoning=True):
    """Minimal HermesCLI stub for _stream_delta."""
    from cli import HermesCLI

    cli = HermesCLI.__new__(HermesCLI)
    cli._stream_buf = ""
    cli._stream_text_ansi = ""
    cli._stream_box_opened = False
    cli._stream_started = False
    cli._stream_prefilt = ""
    cli._in_reasoning_block = False
    cli._reasoning_box_opened = False
    cli._reasoning_buf = ""
    cli._reasoning_stream_started = False
    cli._reasoning_shown_this_turn = False
    cli._reasoning_preview_buf = ""
    cli.show_reasoning = show_reasoning
    cli.streaming_enabled = True
    cli._deferred_content = ""
    cli._rich_reasoning = False
    cli._stream_block_buf = MagicMock()
    cli._stream_block_buf.process_line = MagicMock(side_effect=lambda x: x)
    cli._stream_block_buf.flush = MagicMock(return_value=None)
    cli._stream_code_hl = MagicMock()
    cli._stream_code_hl.process_line = MagicMock(side_effect=lambda x: x)
    cli._stream_code_hl.flush = MagicMock(return_value=None)
    return cli


# ---------------------------------------------------------------------------
# Orphan </think> tag stripping
# ---------------------------------------------------------------------------


class TestOrphanCloseTagStripping(unittest.TestCase):
    """_emit_stream_text strips orphan reasoning close tags that leak through
    when the API uses structured thinking blocks."""

    @patch("cli._cprint")
    def test_bare_think_tag_stripped(self, mock_cprint):
        """Literal '</think>' is stripped from emitted text."""
        cli = _make_emit_cli()
        cli._emit_stream_text("</think>\nHello world\n")
        # </think> should be removed; "Hello world" should be emitted
        calls = [c.args[0] for c in mock_cprint.call_args_list]
        for call in calls:
            assert "</think>" not in call, f"</think> leaked: {call}"
        # At least "Hello world" should have been emitted
        assert any("Hello world" in c for c in calls)

    @patch("cli._cprint")
    def test_think_tag_at_end_of_line(self, mock_cprint):
        """'</think>' at end of text is stripped cleanly."""
        cli = _make_emit_cli()
        cli._emit_stream_text("some text</think>\n")
        calls = [c.args[0] for c in mock_cprint.call_args_list]
        for call in calls:
            assert "</think>" not in call

    @patch("cli._cprint")
    def test_thinking_tag_stripped(self, mock_cprint):
        """'</thinking>' is also stripped."""
        cli = _make_emit_cli()
        cli._emit_stream_text("text</thinking>\nmore\n")
        calls = [c.args[0] for c in mock_cprint.call_args_list]
        for call in calls:
            assert "</thinking>" not in call

    @patch("cli._cprint")
    def test_reasoning_scratchpad_tag_stripped(self, mock_cprint):
        """'</REASONING_SCRATCHPAD>' is stripped."""
        cli = _make_emit_cli()
        cli._emit_stream_text("</REASONING_SCRATCHPAD>Response\n")
        calls = [c.args[0] for c in mock_cprint.call_args_list]
        for call in calls:
            assert "</REASONING_SCRATCHPAD>" not in call

    @patch("cli._cprint")
    def test_only_tag_produces_no_output(self, mock_cprint):
        """Text that is ONLY a close tag produces no visible output."""
        cli = _make_emit_cli()
        cli._emit_stream_text("</think>")
        # The tag is stripped → empty text → early return, no _cprint
        mock_cprint.assert_not_called()

    @patch("cli._cprint")
    def test_text_around_tag_preserved(self, mock_cprint):
        """Text before and after the tag is preserved."""
        cli = _make_emit_cli()
        cli._emit_stream_text("before</think>after\n")
        calls = [c.args[0] for c in mock_cprint.call_args_list]
        joined = "".join(calls)
        assert "before" in joined
        assert "after" in joined
        assert "</think>" not in joined

    @patch("cli._cprint")
    def test_multiple_tags_stripped(self, mock_cprint):
        """Multiple close tags in the same text are all stripped."""
        cli = _make_emit_cli()
        cli._emit_stream_text("</think></thinking>clean\n")
        calls = [c.args[0] for c in mock_cprint.call_args_list]
        for call in calls:
            assert "</think>" not in call
            assert "</thinking>" not in call


# ---------------------------------------------------------------------------
# Word-boundary flush with unclosed markdown
# ---------------------------------------------------------------------------


class TestWordBoundaryFlushMarkdown(unittest.TestCase):
    """Word-boundary flush skips when buffer contains unclosed markdown
    delimiters, preventing raw asterisks from showing."""

    @patch("cli._cprint")
    def test_unclosed_bold_prevents_flush(self, mock_cprint):
        """Buffer with unclosed ** is NOT flushed at word boundary."""
        cli = _make_emit_cli()
        # Pre-load buffer with unclosed bold then send a space to trigger flush check
        cli._stream_buf = "This is a **memorable text that"
        cli._emit_stream_text(" keeps going")
        # Unclosed ** → flush should be suppressed, all content stays in buf
        assert "**memorable" in cli._stream_buf

    @patch("cli._cprint")
    def test_unclosed_italic_prevents_flush(self, mock_cprint):
        """Buffer with unclosed * is NOT flushed at word boundary."""
        cli = _make_emit_cli()
        cli._stream_buf = "We are in a *judgment-free zone"
        cli._emit_stream_text(" right now")
        assert "*judgment-free" in cli._stream_buf

    @patch("cli._cprint")
    def test_closed_bold_allows_flush(self, mock_cprint):
        """Buffer with closed ** (even count) IS flushed normally."""
        cli = _make_emit_cli()
        # Even number of ** = all spans closed. Pre-load and trigger.
        cli._stream_buf = "This has **bold** text and"
        cli._emit_stream_text(" keeps going on")
        # Flush should have occurred — buffer was > 12, no structural prefix,
        # even delimiter counts
        assert mock_cprint.called or len(cli._stream_buf) < len("This has **bold** text and keeps going on")

    @patch("cli._cprint")
    def test_complete_line_still_processes_markdown(self, mock_cprint):
        """A complete line (with \\n) still gets _apply_inline_md, regardless."""
        cli = _make_emit_cli()
        with (
            patch("cli._apply_block_line", side_effect=lambda l, **_: l),
            patch("cli._apply_inline_md", side_effect=lambda l, **_: l) as mock_md,
        ):
            cli._emit_stream_text("This has **bold** text\n")
        mock_md.assert_called()


# ---------------------------------------------------------------------------
# Reasoning _cprint isolation in TUI mode
# ---------------------------------------------------------------------------


class TestReasoningCprintIsolation(unittest.TestCase):
    """In TUI mode, _stream_reasoning_delta and _close_reasoning_box must
    NOT call _cprint, as that would leak reasoning content into the response
    RichLog via the output queue."""

    @patch("cli._cprint")
    @patch("cli._hermes_app")
    def test_reasoning_delta_skips_cprint_in_tui_mode(self, mock_app, mock_cprint):
        """_stream_reasoning_delta does NOT call _cprint when TUI is active."""
        mock_app.__bool__ = lambda self: True
        mock_app.call_from_thread = MagicMock()

        cli = _make_reasoning_cli()
        cli._stream_reasoning_delta("Step 1\nStep 2\n")

        # _cprint should NOT have been called
        mock_cprint.assert_not_called()
        # But TUI bridge should have been called
        mock_app.call_from_thread.assert_called()

    @patch("cli._cprint")
    @patch("cli._hermes_app", new=None)
    def test_reasoning_delta_uses_cprint_in_pt_mode(self, mock_cprint):
        """_stream_reasoning_delta DOES call _cprint when no TUI is active."""
        cli = _make_reasoning_cli()
        with (
            patch("cli._apply_block_line", side_effect=lambda l, **_: l),
            patch("cli._apply_inline_md", side_effect=lambda l, **_: l),
            patch("cli._dim_lines", side_effect=lambda l: [l]),
        ):
            cli._stream_reasoning_delta("Step 1\n")

        mock_cprint.assert_called()

    @patch("cli._cprint")
    @patch("cli._hermes_app")
    def test_close_reasoning_skips_cprint_in_tui_mode(self, mock_app, mock_cprint):
        """_close_reasoning_box does NOT call _cprint when TUI is active."""
        mock_app.__bool__ = lambda self: True
        mock_app.call_from_thread = MagicMock()

        cli = _make_reasoning_cli()
        cli._reasoning_buf = "partial"
        cli._close_reasoning_box()

        mock_cprint.assert_not_called()
        mock_app.call_from_thread.assert_called()

    @patch("cli._cprint")
    @patch("cli._hermes_app", new=None)
    def test_close_reasoning_uses_cprint_in_pt_mode(self, mock_cprint):
        """_close_reasoning_box DOES call _cprint when no TUI is active."""
        import os
        cli = _make_reasoning_cli()
        cli._reasoning_buf = "remaining text"
        with (
            patch("cli._apply_block_line", side_effect=lambda l, **_: l),
            patch("cli._apply_inline_md", side_effect=lambda l, **_: l),
            patch("cli._dim_lines", side_effect=lambda l: [l]),
            patch("cli.shutil.get_terminal_size", return_value=os.terminal_size((80, 24))),
        ):
            cli._close_reasoning_box()

        # Should have called _cprint for the buffer flush and box bottom
        assert mock_cprint.call_count >= 2

    @patch("cli._cprint")
    @patch("cli._hermes_app")
    def test_reasoning_box_open_skips_cprint_in_tui(self, mock_app, mock_cprint):
        """Opening the reasoning box skips the PT border _cprint in TUI mode."""
        mock_app.__bool__ = lambda self: True
        mock_app.call_from_thread = MagicMock()

        cli = _make_reasoning_cli()
        cli._reasoning_box_opened = False  # force re-open
        cli._stream_reasoning_delta("first token")

        # No _cprint for the ┌─ Reasoning ─┐ border
        mock_cprint.assert_not_called()


# ---------------------------------------------------------------------------
# _stream_delta tag filter with structured thinking
# ---------------------------------------------------------------------------


class TestStreamDeltaTagFilter(unittest.TestCase):
    """_stream_delta tag filter handles <think> tags in text content."""

    @patch("cli._cprint")
    @patch("cli._hermes_app", new=None)
    def test_think_tags_suppressed_in_stream(self, mock_cprint):
        """Content inside <think>...</think> does not reach _emit_stream_text."""
        cli = _make_stream_delta_cli(show_reasoning=False)
        cli._stream_delta("<think>secret reasoning</think>visible text\n")
        calls = [c.args[0] for c in mock_cprint.call_args_list]
        joined = "".join(calls)
        assert "secret reasoning" not in joined
        assert "<think>" not in joined
        assert "</think>" not in joined

    @patch("cli._cprint")
    @patch("cli._hermes_app", new=None)
    def test_text_after_close_tag_emitted(self, mock_cprint):
        """Text after </think> is emitted normally."""
        cli = _make_stream_delta_cli(show_reasoning=False)
        cli._stream_delta("<think>hidden</think>Hello\n")
        calls = [c.args[0] for c in mock_cprint.call_args_list]
        joined = "".join(calls)
        assert "Hello" in joined

    @patch("cli._cprint")
    @patch("cli._hermes_app", new=None)
    def test_split_close_tag_across_chunks(self, mock_cprint):
        """Close tag split across two chunks is still detected."""
        cli = _make_stream_delta_cli(show_reasoning=False)
        cli._stream_delta("<think>reasoning</thi")
        cli._stream_delta("nk>visible\n")
        calls = [c.args[0] for c in mock_cprint.call_args_list]
        joined = "".join(calls)
        assert "reasoning" not in joined
        assert "</think>" not in joined
        # visible text should come through
        assert "visible" in joined
