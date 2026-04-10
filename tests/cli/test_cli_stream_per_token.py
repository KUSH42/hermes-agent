"""Tests for line-buffered streaming output in _emit_stream_text and _stream_reasoning_delta.

Per-token partial display (end="" _pt_print with \\r overwrite) was removed because
prompt_toolkit's run_in_terminal erases and redraws the app between each call, making
the \\r-based overwrite pattern produce garbage output in TUI mode.  Streaming is now
line-buffered: tokens accumulate in a buffer and complete lines appear via _cprint when
a \\n boundary is found.

Covers:
- _emit_stream_text: no _pt_print(end="") call for partial tokens (line-buffered only)
- _emit_stream_text: buffer accumulates across tokens, no premature _cprint
- _emit_stream_text: complete line (\\n-terminated) goes to _cprint
- _emit_stream_text: no \\r+spaces+\\r clear since there is no partial to clear
- _emit_stream_text: _flush_stream emits remaining buffer via _cprint (no prior clear)
- _stream_reasoning_delta: same line-buffered guarantees
- _stream_reasoning_delta: no 80-char force-flush hack
- _close_reasoning_box: final render via _cprint, no partial clear needed
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Stub optional packages absent in the test environment.
_MISSING_STUBS = {
    mod: MagicMock()
    for mod in [
        "prompt_toolkit", "prompt_toolkit.history", "prompt_toolkit.styles",
        "prompt_toolkit.patch_stdout", "prompt_toolkit.application",
        "prompt_toolkit.layout", "prompt_toolkit.layout.processors",
        "prompt_toolkit.filters", "prompt_toolkit.layout.dimension",
        "prompt_toolkit.layout.menus", "prompt_toolkit.widgets",
        "prompt_toolkit.key_binding", "prompt_toolkit.completion",
        "prompt_toolkit.formatted_text", "prompt_toolkit.auto_suggest",
        "fire",
    ]
    if mod not in sys.modules
}
sys.modules.update(_MISSING_STUBS)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RST_SENTINEL = "\033[0m"
_DIM_SENTINEL = "\033[2m"


def _make_emit_cli(stream_buf="", stream_text_ansi=""):
    """Minimal HermesCLI stub for exercising _emit_stream_text."""
    from cli import HermesCLI

    cli = HermesCLI.__new__(HermesCLI)
    cli._stream_buf = stream_buf
    cli._stream_spec_stack = []
    cli._stream_text_ansi = stream_text_ansi
    cli._stream_box_opened = True   # skip box-open branch (needs skin_engine)
    cli._stream_started = True
    cli.show_reasoning = False
    cli._reasoning_box_opened = False
    cli._deferred_content = ""
    cli._stream_block_buf = MagicMock()
    cli._stream_code_hl = MagicMock()
    return cli


def _make_reasoning_cli(reasoning_buf=""):
    """Minimal HermesCLI stub for exercising _stream_reasoning_delta."""
    from cli import HermesCLI

    cli = HermesCLI.__new__(HermesCLI)
    cli._reasoning_buf = reasoning_buf
    cli._reasoning_box_opened = True   # skip box-open branch
    cli._reasoning_stream_started = False
    cli._reasoning_shown_this_turn = False
    cli._stream_box_opened = False
    cli._rich_reasoning = False
    return cli


# ---------------------------------------------------------------------------
# _emit_stream_text: line-buffered (no per-token partial)
# ---------------------------------------------------------------------------

class TestEmitStreamTextLineBuf:
    """Tokens without \\n accumulate in _stream_buf; no _pt_print(end='') is emitted."""

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_no_partial_pt_print_for_partial_token(self, mock_cprint, mock_pt_print):
        """A token with no newline must NOT call _pt_print(end='')."""
        cli = _make_emit_cli()
        cli._emit_stream_text("hello")

        partial_calls = [
            c for c in mock_pt_print.call_args_list
            if c.kwargs.get("end", "\n") == ""
        ]
        assert not partial_calls, (
            f"Unexpected _pt_print(end='') for partial token: {partial_calls}"
        )

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_token_accumulates_in_buf(self, mock_cprint, mock_pt_print):
        """Token without newline must stay in _stream_buf, not trigger _cprint."""
        cli = _make_emit_cli()
        cli._emit_stream_text("hello")

        assert cli._stream_buf == "hello", (
            f"Buffer should be 'hello', got: {cli._stream_buf!r}"
        )
        assert not mock_cprint.called, "_cprint must not fire for a partial token"

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_multi_token_accumulation(self, mock_cprint, mock_pt_print):
        """Multiple partial tokens accumulate without triggering _cprint."""
        cli = _make_emit_cli()
        cli._emit_stream_text("hello")
        cli._emit_stream_text(" world")

        assert cli._stream_buf == "hello world"
        assert not mock_cprint.called

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_complete_line_goes_to_cprint(self, mock_cprint, mock_pt_print):
        """Complete lines (ending with \\n) must be emitted via _cprint."""
        cli = _make_emit_cli()
        cli._emit_stream_text("hello\n")

        assert mock_cprint.called, "_cprint was not called for a complete line"
        rendered = " ".join(str(c.args[0]) for c in mock_cprint.call_args_list)
        assert "hello" in rendered

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_complete_line_clears_buf(self, mock_cprint, mock_pt_print):
        """After a \\n, _stream_buf must be empty (no carry-over)."""
        cli = _make_emit_cli()
        cli._emit_stream_text("hello\n")

        assert cli._stream_buf == "", (
            f"Buffer not cleared after complete line; got: {cli._stream_buf!r}"
        )

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_no_cr_clear_sequence_for_partial(self, mock_cprint, mock_pt_print):
        """No \\r+spaces+\\r clear sequence is emitted (nothing to clear)."""
        cli = _make_emit_cli(stream_buf="hello")
        cli._emit_stream_text("\n")

        clear_calls = [
            c for c in mock_pt_print.call_args_list
            if c.kwargs.get("end", "\n") == ""
            and "\r" in str(c.args[0])
            and "     " in str(c.args[0])
        ]
        assert not clear_calls, (
            f"Unexpected \\r+spaces+\\r clear sequence: {clear_calls}"
        )


# ---------------------------------------------------------------------------
# _flush_stream: emits remaining buffer without prior clear
# ---------------------------------------------------------------------------

class TestFlushStreamNoClear:
    """_flush_stream renders remaining buffer via _cprint without a clear sequence."""

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_no_cr_clear_in_flush_stream(self, mock_cprint, mock_pt_print):
        """_flush_stream must not emit \\r+spaces+\\r (nothing was shown as partial)."""
        from cli import HermesCLI

        cli = HermesCLI.__new__(HermesCLI)
        cli._stream_buf = "partial"
        cli._stream_box_opened = False
        cli._stream_text_ansi = ""
        cli._reasoning_box_opened = False
        cli._reasoning_buf = ""
        cli._deferred_content = ""
        cli._stream_block_buf = MagicMock()
        cli._stream_code_hl = MagicMock()

        with patch.object(cli, "_close_reasoning_box"):
            cli._flush_stream()

        clear_calls = [
            c for c in mock_pt_print.call_args_list
            if c.kwargs.get("end", "\n") == ""
            and "\r" in str(c.args[0])
        ]
        assert not clear_calls, (
            f"Unexpected clear sequence in _flush_stream: {clear_calls}"
        )

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_remaining_buf_rendered_via_cprint(self, mock_cprint, mock_pt_print):
        """_flush_stream must emit remaining buffer content via _cprint."""
        from cli import HermesCLI

        cli = HermesCLI.__new__(HermesCLI)
        cli._stream_buf = "tail"
        cli._stream_box_opened = False
        cli._stream_text_ansi = ""
        cli._reasoning_box_opened = False
        cli._reasoning_buf = ""
        cli._deferred_content = ""
        cli._stream_block_buf = MagicMock()
        cli._stream_code_hl = MagicMock()

        with patch.object(cli, "_close_reasoning_box"):
            cli._flush_stream()

        assert mock_cprint.called, "_cprint not called for remaining buffer"
        rendered = " ".join(str(c.args[0]) for c in mock_cprint.call_args_list)
        assert "tail" in rendered


# ---------------------------------------------------------------------------
# _stream_reasoning_delta: line-buffered (no per-token partial)
# ---------------------------------------------------------------------------

class TestReasoningDeltaLineBuf:
    """Reasoning tokens accumulate line-by-line; no _pt_print(end='') partial."""

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    @patch("cli._DIM", _DIM_SENTINEL)
    def test_no_partial_pt_print_for_short_token(self, mock_cprint, mock_pt_print):
        """A short reasoning token must NOT call _pt_print(end='')."""
        cli = _make_reasoning_cli()
        cli._stream_reasoning_delta("thinking...")

        partial_calls = [
            c for c in mock_pt_print.call_args_list
            if c.kwargs.get("end", "\n") == ""
        ]
        assert not partial_calls, (
            f"Unexpected partial _pt_print(end='') for reasoning token: {partial_calls}"
        )

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    @patch("cli._DIM", _DIM_SENTINEL)
    def test_token_stays_in_buf(self, mock_cprint, mock_pt_print):
        """Reasoning token without newline stays in _reasoning_buf."""
        cli = _make_reasoning_cli()
        cli._stream_reasoning_delta("pondering")

        assert cli._reasoning_buf == "pondering"
        assert not mock_cprint.called

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    @patch("cli._DIM", _DIM_SENTINEL)
    def test_complete_reasoning_line_goes_to_cprint(self, mock_cprint, mock_pt_print):
        """A reasoning token ending with \\n emits a complete line via _cprint."""
        cli = _make_reasoning_cli()
        cli._stream_reasoning_delta("step one\n")

        assert mock_cprint.called, "_cprint not called for complete reasoning line"

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    @patch("cli._DIM", _DIM_SENTINEL)
    def test_no_80_char_forced_flush(self, mock_cprint, mock_pt_print):
        """An 81-char token without newline must NOT flush via _cprint (old 80-char hack)."""
        cli = _make_reasoning_cli()
        long_token = "x" * 81
        cli._stream_reasoning_delta(long_token)

        assert not mock_cprint.called, (
            "_cprint was called for a long partial reasoning token — 80-char hack is back"
        )
        assert cli._reasoning_buf == long_token, (
            "_reasoning_buf was cleared; old force-flush behaviour is present"
        )

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    @patch("cli._DIM", _DIM_SENTINEL)
    def test_no_cr_clear_on_newline(self, mock_cprint, mock_pt_print):
        """No \\r+spaces+\\r clear when a newline arrives (nothing shown as partial)."""
        cli = _make_reasoning_cli(reasoning_buf="prior")
        cli._stream_reasoning_delta("\n")

        clear_calls = [
            c for c in mock_pt_print.call_args_list
            if c.kwargs.get("end", "\n") == ""
            and "\r" in str(c.args[0])
        ]
        assert not clear_calls, (
            f"Unexpected \\r+spaces+\\r clear in reasoning delta: {clear_calls}"
        )


# ---------------------------------------------------------------------------
# _close_reasoning_box: final render via _cprint, no clear
# ---------------------------------------------------------------------------

class TestCloseReasoningBoxFinalRender:
    """_close_reasoning_box renders remaining buffer via _cprint without a clear."""

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    @patch("cli._DIM", _DIM_SENTINEL)
    def test_no_clear_sequence_emitted(self, mock_cprint, mock_pt_print):
        """_close_reasoning_box must not emit \\r+spaces+\\r (nothing to erase)."""
        from cli import HermesCLI

        cli = HermesCLI.__new__(HermesCLI)
        cli._reasoning_box_opened = True
        cli._reasoning_buf = "partial thought"
        cli._rich_reasoning = False
        cli._deferred_content = ""

        with (
            patch("cli.shutil") as mock_shutil,
            patch("cli._apply_block_line", side_effect=lambda l, **_: l),
            patch("cli._apply_inline_md", side_effect=lambda l, **_: l),
            patch("cli._dim_lines", side_effect=lambda t: [t]),
            patch("cli._resp_border_ansi", return_value=""),
        ):
            mock_shutil.get_terminal_size.return_value = SimpleNamespace(columns=40)
            cli._close_reasoning_box()

        clear_calls = [
            c for c in mock_pt_print.call_args_list
            if c.kwargs.get("end", "\n") == ""
            and "\r" in str(c.args[0])
        ]
        assert not clear_calls, (
            f"Unexpected clear sequence in _close_reasoning_box: {clear_calls}"
        )

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    @patch("cli._DIM", _DIM_SENTINEL)
    def test_final_render_uses_cprint(self, mock_cprint, mock_pt_print):
        """After the buffer, the final reasoning content goes through _cprint."""
        from cli import HermesCLI

        cli = HermesCLI.__new__(HermesCLI)
        cli._reasoning_box_opened = True
        cli._reasoning_buf = "partial thought"
        cli._rich_reasoning = False
        cli._deferred_content = ""

        with (
            patch("cli.shutil") as mock_shutil,
            patch("cli._apply_block_line", side_effect=lambda l, **_: l),
            patch("cli._apply_inline_md", side_effect=lambda l, **_: l),
            patch("cli._dim_lines", side_effect=lambda t: [t]),
            patch("cli._resp_border_ansi", return_value=""),
        ):
            mock_shutil.get_terminal_size.return_value = SimpleNamespace(columns=40)
            cli._close_reasoning_box()

        assert mock_cprint.called, (
            "_cprint was not called for final reasoning content in _close_reasoning_box"
        )


# ---------------------------------------------------------------------------
# _emit_stream_text: rich-response path still line-buffers correctly
# ---------------------------------------------------------------------------

class TestEmitStreamTextRichBuf:
    """Line-buffering in rich mode: no partial, block_buf gets complete lines."""

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST_SENTINEL)
    def test_no_partial_in_rich_mode(self, mock_cprint, mock_pt_print):
        """With _RICH_RESPONSE=True a no-newline token does NOT produce _pt_print(end='')."""
        cli = _make_emit_cli()
        cli._emit_stream_text("hello")

        partial_calls = [
            c for c in mock_pt_print.call_args_list
            if c.kwargs.get("end", "\n") == ""
        ]
        assert not partial_calls, (
            f"Unexpected partial _pt_print(end='') in rich-response mode: {partial_calls}"
        )

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST_SENTINEL)
    def test_complete_line_goes_through_block_buf_in_rich_mode(
        self, mock_cprint, mock_pt_print
    ):
        """In rich mode, complete lines pass through _stream_block_buf.process_line."""
        cli = _make_emit_cli()
        cli._stream_block_buf.process_line.return_value = "processed"
        cli._stream_code_hl.process_line.return_value = "processed"  # identity → inline md path

        with (
            patch("cli._apply_block_line", side_effect=lambda l, **_: l),
            patch("cli._apply_inline_md", side_effect=lambda l, **_: l),
        ):
            cli._emit_stream_text("hello\n")

        cli._stream_block_buf.process_line.assert_called_once_with("hello")

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST_SENTINEL)
    def test_partial_not_sent_through_block_buf(self, mock_cprint, mock_pt_print):
        """Partial tokens must bypass _stream_block_buf (needs complete lines)."""
        cli = _make_emit_cli()
        cli._emit_stream_text("hello")

        cli._stream_block_buf.process_line.assert_not_called()


# ---------------------------------------------------------------------------
# Word-boundary flushing: progress on long lines without waiting for \\n
# ---------------------------------------------------------------------------

class TestWordBoundaryFlush:
    """_emit_stream_text and _stream_reasoning_delta flush at word boundaries
    when the buffer exceeds _PARTIAL_FLUSH_CHARS, rather than waiting for \\n."""

    # --- _emit_stream_text -------------------------------------------------

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_no_flush_below_threshold(self, mock_cprint, mock_pt_print):
        """Buffer shorter than _PARTIAL_FLUSH_CHARS must not trigger a word-boundary flush."""
        import cli as cli_mod
        short = "hi "  # well under 12 chars
        assert len(short) < cli_mod._PARTIAL_FLUSH_CHARS
        c = _make_emit_cli()
        c._emit_stream_text(short)
        assert not mock_cprint.called

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_flush_at_word_boundary(self, mock_cprint, mock_pt_print):
        """Buffer >= _PARTIAL_FLUSH_CHARS with a space beyond position 5 triggers a flush."""
        text = "The quick brown fox"
        assert len(text) >= 12
        c = _make_emit_cli()
        c._emit_stream_text(text)
        assert mock_cprint.called, "_cprint not called for long buffer with word boundary"

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_remaining_stays_in_buf_after_flush(self, mock_cprint, mock_pt_print):
        """Text after the last-space cut point must remain in _stream_buf."""
        text = "The quick brown fox"
        c = _make_emit_cli()
        c._emit_stream_text(text)
        # The remaining buffer is the word(s) after the last flush cut
        assert c._stream_buf != text, "buffer unchanged after flush"
        assert "fox" in c._stream_buf or c._stream_buf == ""

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_no_flush_for_no_space_token(self, mock_cprint, mock_pt_print):
        """A token >= 12 chars with no spaces must not flush (rfind returns -1)."""
        text = "x" * 20  # no spaces, rfind(' ') == -1
        c = _make_emit_cli()
        c._emit_stream_text(text)
        assert not mock_cprint.called, "_cprint must not fire with no word boundary"
        assert c._stream_buf == text

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_no_flush_for_structural_prefix(self, mock_cprint, mock_pt_print):
        """Lines starting with structural prefixes must not word-boundary-flush.

        For ``-`` and ``*``, only the list-marker forms (``- text`` and
        ``* text``, with a trailing space) are structural.  ``*bold`` and
        ``-text`` are inline and may flush normally.
        """
        for prefix in ("#", ">", "|", "`", " ", "\t", "- ", "* ", "+"):
            c = _make_emit_cli()
            # Pad to exceed 12-char threshold after prefix
            text = prefix + "word " * 5
            c._emit_stream_text(text)
            assert not mock_cprint.called, (
                f"_cprint fired for structural prefix {prefix!r}: {mock_cprint.call_args_list}"
            )
            mock_cprint.reset_mock()

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_text_color_applied_to_flushed_chunk(self, mock_cprint, mock_pt_print):
        """Flushed word chunk must carry the stream text color and _RST suffix."""
        text = "The quick brown fox"
        ansi = "\033[38;2;255;248;220m"
        c = _make_emit_cli(stream_text_ansi=ansi)
        with patch("cli._RST", _RST_SENTINEL):
            c._emit_stream_text(text)
        assert mock_cprint.called
        rendered = mock_cprint.call_args_list[0].args[0]
        assert ansi in rendered, "text color ANSI not present in flushed chunk"
        assert _RST_SENTINEL in rendered, "_RST not present in flushed chunk"

    # --- _stream_reasoning_delta ------------------------------------------

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    @patch("cli._DIM", _DIM_SENTINEL)
    def test_reasoning_no_flush_below_threshold(self, mock_cprint, mock_pt_print):
        """Reasoning buffer shorter than _PARTIAL_FLUSH_CHARS must not flush."""
        import cli as cli_mod
        text = "think "
        assert len(text) < cli_mod._PARTIAL_FLUSH_CHARS
        c = _make_reasoning_cli()
        c._stream_reasoning_delta(text)
        assert not mock_cprint.called

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    @patch("cli._DIM", _DIM_SENTINEL)
    def test_reasoning_flush_at_word_boundary(self, mock_cprint, mock_pt_print):
        """Long reasoning buffer with a word boundary flushes via _cprint."""
        text = "The reasoning model evaluates"
        assert len(text) >= 12
        c = _make_reasoning_cli()
        with patch("cli._dim_lines", side_effect=lambda t: [t]):
            c._stream_reasoning_delta(text)
        assert mock_cprint.called, "_cprint not called for long reasoning buffer"

    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    @patch("cli._DIM", _DIM_SENTINEL)
    def test_reasoning_remaining_stays_in_buf(self, mock_cprint, mock_pt_print):
        """Words after the flush cut remain in _reasoning_buf."""
        text = "The reasoning model evaluates"
        c = _make_reasoning_cli()
        with patch("cli._dim_lines", side_effect=lambda t: [t]):
            c._stream_reasoning_delta(text)
        assert c._reasoning_buf != text, "reasoning_buf unchanged after flush"
