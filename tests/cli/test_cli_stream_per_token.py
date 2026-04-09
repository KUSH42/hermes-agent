"""Tests for per-token streaming output in _emit_stream_text and _stream_reasoning_delta.

Covers:
- _emit_stream_text: partial line printed immediately via _pt_print(end="") on each token
- _emit_stream_text: partial line cleared (\\r+spaces+\\r) before a complete line is printed
- _emit_stream_text: no partial call when token ends with newline (buffer empty after loop)
- _emit_stream_text: _flush_stream clears partial before final render when _stream_vis_len > 0
- _stream_reasoning_delta: same per-token guarantees as above
- _stream_reasoning_delta: 80-char force-flush replaced by true per-token display
- _close_reasoning_box: clears partial before final dim render
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

# Patch _PT_ANSI as identity so _pt_print receives the raw string and tests
# can inspect its content via c.args[0].
_ANSI_IDENTITY = patch("cli._PT_ANSI", side_effect=lambda x: x)


def _make_emit_cli(stream_buf="", stream_vis_len=0, stream_text_ansi=""):
    """Minimal HermesCLI stub for exercising _emit_stream_text."""
    from cli import HermesCLI

    cli = HermesCLI.__new__(HermesCLI)
    cli._stream_buf = stream_buf
    cli._stream_vis_len = stream_vis_len
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
# _emit_stream_text: per-token partial display
# ---------------------------------------------------------------------------

class TestEmitStreamTextPerToken:
    """Partial lines must be written immediately via _pt_print(end='')."""

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_partial_line_written_immediately(self, mock_cprint, mock_pt_print, mock_ansi):
        """A token with no newline must call _pt_print with end='' immediately."""
        cli = _make_emit_cli()
        cli._emit_stream_text("hello")

        partial_calls = [
            c for c in mock_pt_print.call_args_list
            if c.kwargs.get("end", "\n") == ""
        ]
        assert partial_calls, (
            "_pt_print was not called with end='' for partial token output"
        )

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_partial_contains_token_text(self, mock_cprint, mock_pt_print, mock_ansi):
        """The partial _pt_print call must include the buffered token text."""
        cli = _make_emit_cli()
        cli._emit_stream_text("hello")

        rendered = " ".join(
            str(c.args[0]) for c in mock_pt_print.call_args_list
            if c.kwargs.get("end", "\n") == ""
        )
        assert "hello" in rendered, (
            f"Token text 'hello' not found in partial render: {rendered!r}"
        )

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_no_partial_when_token_ends_with_newline(self, mock_cprint, mock_pt_print, mock_ansi):
        """When the token ends with \\n the buffer is empty — no partial call."""
        cli = _make_emit_cli()
        cli._emit_stream_text("hello\n")

        partial_calls = [
            c for c in mock_pt_print.call_args_list
            if c.kwargs.get("end", "\n") == ""
        ]
        assert not partial_calls, (
            f"Unexpected partial _pt_print calls when buffer is empty: {partial_calls}"
        )

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_complete_line_goes_to_cprint(self, mock_cprint, mock_pt_print, mock_ansi):
        """Complete lines (ending with \\n) must be emitted via _cprint."""
        cli = _make_emit_cli()
        cli._emit_stream_text("hello\n")

        assert mock_cprint.called, "_cprint was not called for a complete line"
        rendered = " ".join(str(c.args[0]) for c in mock_cprint.call_args_list)
        assert "hello" in rendered


# ---------------------------------------------------------------------------
# _emit_stream_text: partial clearing before complete line
# ---------------------------------------------------------------------------

class TestEmitStreamTextPartialClear:
    """When a newline arrives after partial tokens, the partial must be erased."""

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_clear_sequence_emitted_before_complete_line(self, mock_cprint, mock_pt_print, mock_ansi):
        """A \\r+spaces+\\r clear must appear in _pt_print calls when a partial was shown."""
        # Prime the CLI with a partial line already shown (vis_len = 5)
        cli = _make_emit_cli(stream_buf="hello", stream_vis_len=5)
        cli._emit_stream_text("\n")

        clear_calls = [
            c for c in mock_pt_print.call_args_list
            if c.kwargs.get("end", "\n") == ""
            and "\r" in str(c.args[0])
            and "     " in str(c.args[0])
        ]
        assert clear_calls, (
            "No \\r+spaces+\\r clear sequence found in _pt_print calls before complete line"
        )

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_clear_happens_before_cprint(self, mock_cprint, mock_pt_print, mock_ansi):
        """The partial-clear _pt_print call must precede the _cprint call."""
        cli = _make_emit_cli(stream_buf="hello", stream_vis_len=5)

        all_calls = []

        def track_pt(*args, **kwargs):
            if kwargs.get("end", "\n") == "" and "\r" in str(args[0]):
                all_calls.append("clear")

        def track_cp(*args, **kwargs):
            all_calls.append("cprint")

        mock_pt_print.side_effect = track_pt
        mock_cprint.side_effect = track_cp

        cli._emit_stream_text("\n")

        assert "clear" in all_calls, "No clear call found"
        assert "cprint" in all_calls, "No cprint call found"
        assert all_calls.index("clear") < all_calls.index("cprint"), (
            f"Clear must precede cprint, got order: {all_calls}"
        )

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_no_clear_when_no_prior_partial(self, mock_cprint, mock_pt_print, mock_ansi):
        """When vis_len == 0 (no prior partial shown), no clear sequence is emitted."""
        cli = _make_emit_cli(stream_buf="", stream_vis_len=0)
        cli._emit_stream_text("hello\n")

        clear_calls = [
            c for c in mock_pt_print.call_args_list
            if c.kwargs.get("end", "\n") == ""
            and "\r" in str(c.args[0])
        ]
        assert not clear_calls, (
            f"Unexpected clear sequence with no prior partial: {clear_calls}"
        )


# ---------------------------------------------------------------------------
# _flush_stream: clears partial before final render
# ---------------------------------------------------------------------------

class TestFlushStreamClearsPartial:
    """_flush_stream must clear any shown partial line before the final render."""

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_clear_emitted_when_vis_len_nonzero(self, mock_cprint, mock_pt_print, mock_ansi):
        """When _stream_vis_len > 0, _flush_stream must emit a \\r+spaces+\\r clear."""
        from cli import HermesCLI

        cli = HermesCLI.__new__(HermesCLI)
        cli._stream_buf = "partial"
        cli._stream_vis_len = 7
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
        assert clear_calls, (
            "_flush_stream did not emit a clear sequence despite _stream_vis_len > 0"
        )

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_no_clear_when_vis_len_zero(self, mock_cprint, mock_pt_print, mock_ansi):
        """When _stream_vis_len == 0, no clear sequence should be emitted."""
        from cli import HermesCLI

        cli = HermesCLI.__new__(HermesCLI)
        cli._stream_buf = ""
        cli._stream_vis_len = 0
        cli._stream_box_opened = False
        cli._stream_text_ansi = ""
        cli._reasoning_box_opened = False
        cli._reasoning_buf = ""
        cli._deferred_content = ""
        cli._stream_block_buf = MagicMock()
        cli._stream_block_buf.flush.return_value = None
        cli._stream_code_hl = MagicMock()
        cli._stream_code_hl.flush.return_value = None

        with patch.object(cli, "_close_reasoning_box"):
            cli._flush_stream()

        clear_calls = [
            c for c in mock_pt_print.call_args_list
            if c.kwargs.get("end", "\n") == ""
            and "\r" in str(c.args[0])
        ]
        assert not clear_calls, (
            f"Unexpected clear call when vis_len == 0: {clear_calls}"
        )


# ---------------------------------------------------------------------------
# _stream_reasoning_delta: per-token partial display
# ---------------------------------------------------------------------------

class TestReasoningDeltaPerToken:
    """Reasoning tokens must appear immediately, not wait for 80 chars or newlines."""

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    @patch("cli._DIM", _DIM_SENTINEL)
    def test_short_partial_written_immediately(self, mock_cprint, mock_pt_print, mock_ansi):
        """A short reasoning token (<80 chars, no newline) must emit a partial via _pt_print."""
        cli = _make_reasoning_cli()
        cli._stream_reasoning_delta("thinking...")

        partial_calls = [
            c for c in mock_pt_print.call_args_list
            if c.kwargs.get("end", "\n") == ""
        ]
        assert partial_calls, (
            "Short reasoning token did not produce an immediate _pt_print(end='') call"
        )

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    @patch("cli._DIM", _DIM_SENTINEL)
    def test_partial_text_present_in_output(self, mock_cprint, mock_pt_print, mock_ansi):
        """The reasoning partial output must contain the token text."""
        cli = _make_reasoning_cli()
        cli._stream_reasoning_delta("pondering")

        rendered = " ".join(
            str(c.args[0]) for c in mock_pt_print.call_args_list
            if c.kwargs.get("end", "\n") == ""
        )
        assert "pondering" in rendered, (
            f"Token text 'pondering' not in partial output: {rendered!r}"
        )

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    @patch("cli._DIM", _DIM_SENTINEL)
    def test_no_partial_when_token_ends_with_newline(self, mock_cprint, mock_pt_print, mock_ansi):
        """When the reasoning token ends with \\n the buffer is empty — no partial call."""
        cli = _make_reasoning_cli()
        cli._stream_reasoning_delta("step one\n")

        partial_calls = [
            c for c in mock_pt_print.call_args_list
            if c.kwargs.get("end", "\n") == ""
        ]
        assert not partial_calls, (
            f"Unexpected partial call when reasoning buffer is empty: {partial_calls}"
        )

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    @patch("cli._DIM", _DIM_SENTINEL)
    def test_no_80_char_forced_flush(self, mock_cprint, mock_pt_print, mock_ansi):
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


# ---------------------------------------------------------------------------
# _stream_reasoning_delta: partial clearing before complete line
# ---------------------------------------------------------------------------

class TestReasoningDeltaPartialClear:
    """When a newline arrives after partial reasoning tokens, the partial must be erased."""

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    @patch("cli._DIM", _DIM_SENTINEL)
    def test_prior_partial_cleared_on_newline(self, mock_cprint, mock_pt_print, mock_ansi):
        """After partial tokens, a newline token must emit a \\r+spaces+\\r clear."""
        cli = _make_reasoning_cli(reasoning_buf="prior")  # 5 chars already buffered

        cli._stream_reasoning_delta("\n")

        clear_calls = [
            c for c in mock_pt_print.call_args_list
            if c.kwargs.get("end", "\n") == ""
            and "\r" in str(c.args[0])
            and " " * 5 in str(c.args[0])
        ]
        assert clear_calls, (
            "No \\r+spaces+\\r clear sequence found when newline follows a partial"
        )

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    @patch("cli._DIM", _DIM_SENTINEL)
    def test_no_clear_when_no_prior_partial(self, mock_cprint, mock_pt_print, mock_ansi):
        """No clear when the reasoning buffer was empty before the newline token."""
        cli = _make_reasoning_cli(reasoning_buf="")
        cli._stream_reasoning_delta("hello\n")

        clear_calls = [
            c for c in mock_pt_print.call_args_list
            if c.kwargs.get("end", "\n") == ""
            and "\r" in str(c.args[0])
            and " " * 3 in str(c.args[0])
        ]
        assert not clear_calls, (
            f"Unexpected clear sequence with no prior partial: {clear_calls}"
        )


# ---------------------------------------------------------------------------
# _close_reasoning_box: clears partial before final render
# ---------------------------------------------------------------------------

class TestCloseReasoningBoxClearsPartial:
    """_close_reasoning_box must clear any shown partial before final dim render."""

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    @patch("cli._DIM", _DIM_SENTINEL)
    def test_clear_emitted_before_dim_render(self, mock_cprint, mock_pt_print, mock_ansi):
        """When _reasoning_buf has content, _close_reasoning_box clears it first."""
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
        assert clear_calls, (
            "_close_reasoning_box did not emit a clear sequence before final dim render"
        )

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    @patch("cli._DIM", _DIM_SENTINEL)
    def test_final_render_uses_cprint(self, mock_cprint, mock_pt_print, mock_ansi):
        """After the clear, the final reasoning content goes through _cprint."""
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
# _emit_stream_text: rich response path still emits partial
# ---------------------------------------------------------------------------

class TestEmitStreamTextRichPartial:
    """Per-token partial output fires regardless of _RICH_RESPONSE mode."""

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST_SENTINEL)
    def test_partial_written_in_rich_mode(self, mock_cprint, mock_pt_print, mock_ansi):
        """With _RICH_RESPONSE=True a no-newline token still produces _pt_print(end='')."""
        cli = _make_emit_cli()
        cli._emit_stream_text("hello")

        partial_calls = [
            c for c in mock_pt_print.call_args_list
            if c.kwargs.get("end", "\n") == ""
        ]
        assert partial_calls, (
            "No partial _pt_print(end='') call in rich-response mode"
        )

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST_SENTINEL)
    def test_complete_line_goes_through_block_buf_in_rich_mode(
        self, mock_cprint, mock_pt_print, mock_ansi
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

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST_SENTINEL)
    def test_partial_not_sent_through_block_buf(self, mock_cprint, mock_pt_print, mock_ansi):
        """Partial tokens must bypass _stream_block_buf (needs complete lines)."""
        cli = _make_emit_cli()
        cli._emit_stream_text("hello")

        cli._stream_block_buf.process_line.assert_not_called()


# ---------------------------------------------------------------------------
# _emit_stream_text: multi-token accumulation
# ---------------------------------------------------------------------------

class TestEmitStreamTextMultiToken:
    """vis_len and partial content must track across successive token calls."""

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_accumulated_partial_shown_after_second_token(
        self, mock_cprint, mock_pt_print, mock_ansi
    ):
        """After 'hello' then ' world', the partial output contains 'hello world'."""
        cli = _make_emit_cli()
        cli._emit_stream_text("hello")
        cli._emit_stream_text(" world")

        # Last partial call should contain the full accumulation.
        # Note: partial calls start with \r (overwrite previous partial) so we
        # identify them by whether they contain the actual token text.
        partial_calls = [
            c for c in mock_pt_print.call_args_list
            if c.kwargs.get("end", "\n") == ""
            and "hello" in str(c.args[0])
        ]
        assert partial_calls, "No partial output calls found"
        last_partial = str(partial_calls[-1].args[0])
        assert "hello world" in last_partial, (
            f"Accumulated partial 'hello world' not in last partial call: {last_partial!r}"
        )

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_clear_uses_accumulated_vis_len(self, mock_cprint, mock_pt_print, mock_ansi):
        """When '\\n' arrives after two partial tokens, clear covers both lengths combined."""
        cli = _make_emit_cli()
        cli._emit_stream_text("hello")   # vis_len becomes 5
        cli._emit_stream_text(" world")  # vis_len becomes 11
        cli._emit_stream_text("\n")      # clear must be >= 11 spaces

        clear_calls = [
            c for c in mock_pt_print.call_args_list
            if c.kwargs.get("end", "\n") == ""
            and "\r" in str(c.args[0])
            and " " * 11 in str(c.args[0])
        ]
        assert clear_calls, (
            "Clear sequence does not cover the full accumulated partial length (11 chars)"
        )

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    @patch("cli._RST", _RST_SENTINEL)
    def test_vis_len_reset_after_newline(self, mock_cprint, mock_pt_print, mock_ansi):
        """After a complete line is flushed, vis_len resets so no spurious clear next call."""
        cli = _make_emit_cli()
        cli._emit_stream_text("hello\n")   # complete line — buf empty, vis_len = 0
        mock_pt_print.reset_mock()

        cli._emit_stream_text("next")      # fresh partial, no prior partial to clear

        clear_calls = [
            c for c in mock_pt_print.call_args_list
            if c.kwargs.get("end", "\n") == ""
            and "\r" in str(c.args[0])
            and " " * 3 in str(c.args[0])
        ]
        assert not clear_calls, (
            f"Spurious clear sequence after newline reset: {clear_calls}"
        )


# ---------------------------------------------------------------------------
# _flush_stream: clears partial in rich-response mode
# ---------------------------------------------------------------------------

class TestFlushStreamClearsPartialRichMode:
    """_flush_stream partial-clear fires in _RICH_RESPONSE=True too."""

    @_ANSI_IDENTITY
    @patch("cli._pt_print")
    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST_SENTINEL)
    def test_clear_emitted_in_rich_mode(self, mock_cprint, mock_pt_print, mock_ansi):
        """_flush_stream emits \\r+spaces+\\r clear when _RICH_RESPONSE=True and vis_len > 0."""
        from cli import HermesCLI

        cli = HermesCLI.__new__(HermesCLI)
        cli._stream_buf = "partial"
        cli._stream_vis_len = 7
        cli._stream_box_opened = False
        cli._stream_text_ansi = ""
        cli._reasoning_box_opened = False
        cli._reasoning_buf = ""
        cli._deferred_content = ""
        cli._stream_block_buf = MagicMock()
        cli._stream_block_buf.process_line.return_value = "partial"
        cli._stream_block_buf.flush.return_value = None
        cli._stream_code_hl = MagicMock()
        cli._stream_code_hl.process_line.return_value = "partial"
        cli._stream_code_hl.flush.return_value = None

        with (
            patch.object(cli, "_close_reasoning_box"),
            patch("cli._apply_block_line", side_effect=lambda l, **_: l),
            patch("cli._apply_inline_md", side_effect=lambda l, **_: l),
        ):
            cli._flush_stream()

        clear_calls = [
            c for c in mock_pt_print.call_args_list
            if c.kwargs.get("end", "\n") == ""
            and "\r" in str(c.args[0])
        ]
        assert clear_calls, (
            "_flush_stream did not clear partial in _RICH_RESPONSE=True mode"
        )
