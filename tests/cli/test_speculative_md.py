"""Tests for speculative inline markdown in the streaming pipeline.

Covers:
- _find_unclosed_md_openers: detecting unmatched *, **, ***, ~~, ` after
  removing balanced pairs.
- apply_speculative_inline_md: speculative styling for partial flushes,
  closing of previously opened speculative delimiters, nesting support.
- Integration with _emit_stream_text: partial-flush now flushes even when
  unclosed delimiters are present, and \n processing closes spec state.
"""

import sys
import re
import unittest
from unittest.mock import MagicMock, patch

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

_RST = "\033[0m"
_BOLD = "\033[1m"
_ITALIC = "\033[3m"
_BOLD_ITALIC = "\033[1;3m"


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences for plain-text assertions."""
    return re.sub(r"\033\[[0-9;]*m", "", text)


def _make_emit_cli(stream_buf=""):
    """Minimal HermesCLI stub for _emit_stream_text."""
    from cli import HermesCLI

    cli = HermesCLI.__new__(HermesCLI)
    cli._stream_buf = stream_buf
    cli._stream_spec_stack = []
    cli._stream_text_ansi = ""
    cli._stream_box_opened = True
    cli._stream_started = True
    cli.show_reasoning = False
    cli._reasoning_box_opened = False
    cli._deferred_content = ""
    cli._stream_block_buf = MagicMock()
    cli._stream_block_buf.process_line = MagicMock(side_effect=lambda x: x)
    cli._stream_code_hl = MagicMock()
    cli._stream_code_hl.process_line = MagicMock(side_effect=lambda x: x)
    return cli


# ---------------------------------------------------------------------------
# Tests: _find_unclosed_md_openers
# ---------------------------------------------------------------------------

class TestFindUnclosedMdOpeners(unittest.TestCase):
    """Unit tests for _find_unclosed_md_openers in rich_output.py."""

    def _find(self, text):
        from agent.rich_output import _find_unclosed_md_openers
        return _find_unclosed_md_openers(text)

    def test_no_delimiters(self):
        assert self._find("plain text here") == []

    def test_balanced_bold(self):
        assert self._find("text **bold** more") == []

    def test_balanced_italic(self):
        assert self._find("text *italic* more") == []

    def test_balanced_code(self):
        assert self._find("text `code` more") == []

    def test_balanced_strike(self):
        assert self._find("text ~~strike~~ more") == []

    def test_balanced_bold_italic(self):
        assert self._find("text ***both*** more") == []

    def test_unclosed_bold(self):
        result = self._find("text **bold continues")
        assert len(result) == 1
        pos, delim, _ansi = result[0]
        assert delim == "**"
        assert pos == 5

    def test_unclosed_italic(self):
        result = self._find("text *italic continues")
        assert len(result) == 1
        assert result[0][1] == "*"

    def test_unclosed_code(self):
        result = self._find("text `code continues")
        assert len(result) == 1
        assert result[0][1] == "`"

    def test_unclosed_strike(self):
        result = self._find("text ~~strike continues")
        assert len(result) == 1
        assert result[0][1] == "~~"

    def test_unclosed_bold_italic(self):
        result = self._find("text ***both continues")
        assert len(result) == 1
        assert result[0][1] == "***"

    def test_balanced_then_unclosed(self):
        """A balanced pair followed by an unclosed opener."""
        result = self._find("**done** then *still open")
        assert len(result) == 1
        assert result[0][1] == "*"

    def test_multiple_unclosed(self):
        """Nested unclosed openers: ** then * inside."""
        result = self._find("**bold *italic continues")
        assert len(result) == 2
        assert result[0][1] == "**"
        assert result[1][1] == "*"

    def test_empty_string(self):
        assert self._find("") == []

    def test_star_run_decomposition_4stars(self):
        """4 stars → *** + *."""
        result = self._find("text ****more")
        assert len(result) == 2
        assert result[0][1] == "***"
        assert result[1][1] == "*"

    def test_star_run_decomposition_5stars(self):
        """5 stars → *** + **."""
        result = self._find("text *****more")
        assert len(result) == 2
        assert result[0][1] == "***"
        assert result[1][1] == "**"

    def test_star_inside_code_not_detected(self):
        """Stars inside a balanced code span are not unclosed openers."""
        result = self._find("text `x * y` more")
        assert result == []


# ---------------------------------------------------------------------------
# Tests: apply_speculative_inline_md
# ---------------------------------------------------------------------------

class TestApplySpeculativeInlineMd(unittest.TestCase):
    """Unit tests for apply_speculative_inline_md."""

    def _apply(self, text, stack=None, reset_suffix=""):
        from agent.rich_output import apply_speculative_inline_md
        return apply_speculative_inline_md(text, stack or [], reset_suffix)

    # --- No speculative state, balanced text ---

    def test_no_delimiters_passthrough(self):
        styled, stack = self._apply("plain text")
        assert stack == []
        assert _strip_ansi(styled) == "plain text"

    def test_balanced_bold_processed(self):
        styled, stack = self._apply("text **bold** more")
        assert stack == []
        assert "bold" in _strip_ansi(styled)
        # Bold ANSI should be present
        assert _BOLD in styled

    # --- Opening speculative styles ---

    def test_unclosed_bold_opens_spec(self):
        styled, stack = self._apply("text **bold continues")
        assert len(stack) == 1
        assert stack[0][0] == "**"
        # The ** should be stripped from visible text
        plain = _strip_ansi(styled)
        assert "**" not in plain
        assert "bold continues" in plain
        # Bold ANSI should be applied
        assert _BOLD in styled

    def test_unclosed_italic_opens_spec(self):
        styled, stack = self._apply("text *italic continues")
        assert len(stack) == 1
        assert stack[0][0] == "*"
        assert _ITALIC in styled
        plain = _strip_ansi(styled)
        assert "*" not in plain

    def test_unclosed_bold_italic_opens_spec(self):
        styled, stack = self._apply("text ***both continues")
        assert len(stack) == 1
        assert stack[0][0] == "***"
        assert _BOLD_ITALIC in styled

    def test_unclosed_strike_opens_spec(self):
        styled, stack = self._apply("text ~~strike continues")
        assert len(stack) == 1
        assert stack[0][0] == "~~"
        plain = _strip_ansi(styled)
        assert "~~" not in plain

    def test_unclosed_code_opens_spec(self):
        styled, stack = self._apply("text `code continues")
        assert len(stack) == 1
        assert stack[0][0] == "`"
        plain = _strip_ansi(styled)
        assert "`" not in plain

    def test_balanced_then_unclosed(self):
        """A balanced pair, then an unclosed opener in the same chunk."""
        styled, stack = self._apply("**done** then *still open")
        assert len(stack) == 1
        assert stack[0][0] == "*"
        plain = _strip_ansi(styled)
        assert "done" in plain
        assert "still open" in plain

    # --- Closing speculative styles ---

    def test_close_bold(self):
        """When open_stack has **, closing ** appears in text."""
        open_stack = [("**", _BOLD)]
        styled, stack = self._apply("more bold** normal text", open_stack)
        assert stack == []
        plain = _strip_ansi(styled)
        assert "more bold" in plain
        assert "normal text" in plain
        assert "**" not in plain

    def test_close_italic(self):
        open_stack = [("*", _ITALIC)]
        styled, stack = self._apply("italic end* normal", open_stack)
        assert stack == []
        plain = _strip_ansi(styled)
        assert "italic end" in plain
        assert "normal" in plain

    def test_close_nested_inner_first(self):
        """Close innermost delimiter first when both are present."""
        open_stack = [("**", _BOLD), ("*", _ITALIC)]
        styled, stack = self._apply("italic* bold** normal", open_stack)
        assert stack == []
        plain = _strip_ansi(styled)
        assert "italic" in plain
        assert "bold" in plain
        assert "normal" in plain

    def test_no_closing_in_chunk(self):
        """When the closing delimiter isn't in the chunk, keep spec open."""
        open_stack = [("**", _BOLD)]
        styled, stack = self._apply("still bold text", open_stack)
        assert len(stack) == 1
        assert stack[0][0] == "**"
        # Bold should be applied to the whole chunk
        assert _BOLD in styled

    # --- Nesting ---

    def test_nested_openers(self):
        """Two unclosed openers create a two-level stack."""
        styled, stack = self._apply("**bold *italic continues")
        assert len(stack) == 2
        assert stack[0][0] == "**"
        assert stack[1][0] == "*"

    # --- Edge cases ---

    def test_empty_text(self):
        styled, stack = self._apply("")
        assert styled == ""
        assert stack == []

    def test_empty_text_with_open_stack(self):
        styled, stack = self._apply("", [("**", _BOLD)])
        assert styled == ""
        assert stack == [("**", _BOLD)]

    def test_delimiter_at_end(self):
        """Delimiter right at the end with nothing after."""
        styled, stack = self._apply("text **")
        assert len(stack) == 1
        assert stack[0][0] == "**"

    def test_close_then_reopen(self):
        """Close one speculative, then encounter a new unclosed opener."""
        open_stack = [("**", _BOLD)]
        styled, stack = self._apply("end bold** then *italic", open_stack)
        assert len(stack) == 1
        assert stack[0][0] == "*"
        plain = _strip_ansi(styled)
        assert "**" not in plain
        assert "*" not in plain


# ---------------------------------------------------------------------------
# Tests: streaming pipeline integration
# ---------------------------------------------------------------------------

class TestStreamPartialFlushSpeculative(unittest.TestCase):
    """Partial flush now fires even with unclosed markdown delimiters."""

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST)
    def test_unclosed_bold_flushes(self, mock_cprint):
        """Buffer with unclosed ** now flushes instead of stalling."""
        cli = _make_emit_cli()
        # Seed buffer long enough to trigger partial flush (>= 12 chars)
        cli._stream_buf = "This is a **memorable text that"
        cli._emit_stream_text(" keeps going on")
        # Should have flushed — buffer should be smaller
        total_text = "This is a **memorable text that keeps going on"
        assert len(cli._stream_buf) < len(total_text), (
            f"Buffer should have been partially flushed but is: {cli._stream_buf!r}"
        )

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST)
    def test_unclosed_italic_flushes(self, mock_cprint):
        """Buffer with unclosed * now flushes instead of stalling."""
        cli = _make_emit_cli()
        cli._stream_buf = "We are in a *judgment-free zone"
        cli._emit_stream_text(" that extends")
        total_text = "We are in a *judgment-free zone that extends"
        assert len(cli._stream_buf) < len(total_text)

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST)
    def test_flushed_chunk_has_no_raw_delimiters(self, mock_cprint):
        """The flushed output should not contain raw ** characters."""
        cli = _make_emit_cli()
        cli._stream_buf = "This is **bold text that"
        cli._emit_stream_text(" continues further along")
        if mock_cprint.called:
            printed = "".join(str(c.args[0]) for c in mock_cprint.call_args_list)
            plain = _strip_ansi(printed)
            assert "**" not in plain, (
                f"Raw ** visible in flushed output: {plain!r}"
            )

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST)
    def test_spec_stack_set_after_unclosed_flush(self, mock_cprint):
        """_stream_spec_stack should be non-empty after flushing unclosed delimiter."""
        cli = _make_emit_cli()
        cli._stream_buf = "This is **bold text that"
        cli._emit_stream_text(" continues further along")
        if mock_cprint.called:
            assert len(cli._stream_spec_stack) >= 1, (
                "Speculative stack should track the open delimiter"
            )

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST)
    def test_balanced_flush_still_works(self, mock_cprint):
        """Balanced delimiters still flush normally (regression check)."""
        cli = _make_emit_cli()
        cli._stream_buf = "This has **bold** text and"
        cli._emit_stream_text(" keeps going on for a while")
        total = "This has **bold** text and keeps going on for a while"
        assert len(cli._stream_buf) < len(total)

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST)
    def test_star_at_pos0_with_space_still_blocked(self, mock_cprint):
        """'* list item text' is structural — should NOT partial-flush."""
        cli = _make_emit_cli()
        cli._stream_buf = "* this is a list item that goes on"
        cli._emit_stream_text(" and on further")
        # Should NOT have flushed (structural prefix)
        assert not mock_cprint.called

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST)
    def test_starstar_at_pos0_without_space_flushes(self, mock_cprint):
        """'**bold text' is NOT structural — should flush."""
        cli = _make_emit_cli()
        cli._stream_buf = "**this is bold text that goes on and"
        cli._emit_stream_text(" on for a while")
        # Should have flushed since ** at pos0 without space is not structural
        total = "**this is bold text that goes on and on for a while"
        assert len(cli._stream_buf) < len(total)


class TestStreamNewlineClosesSpec(unittest.TestCase):
    """Newline processing closes speculative state from partial flushes."""

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST)
    def test_newline_closes_spec_and_strips_closer(self, mock_cprint):
        """When \\n arrives with open spec stack, closer is stripped."""
        cli = _make_emit_cli()
        cli._stream_spec_stack = [("**", _BOLD)]
        cli._emit_stream_text("bold text** normal\n")
        # Spec stack should be cleared
        assert cli._stream_spec_stack == []
        # Check that ** was stripped
        printed = "".join(str(c.args[0]) for c in mock_cprint.call_args_list)
        plain = _strip_ansi(printed)
        assert "**" not in plain

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST)
    def test_newline_without_closer_still_resets_stack(self, mock_cprint):
        """If \\n arrives without a closing delimiter, stack resets anyway."""
        cli = _make_emit_cli()
        cli._stream_spec_stack = [("**", _BOLD)]
        cli._emit_stream_text("no closer here\n")
        assert cli._stream_spec_stack == []

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST)
    def test_text_after_closer_processed_normally(self, mock_cprint):
        """Text after the closing delimiter goes through normal pipeline."""
        cli = _make_emit_cli()
        cli._stream_spec_stack = [("**", _BOLD)]
        with (
            patch("cli._apply_block_line", side_effect=lambda l, **_: l),
            patch("cli._apply_inline_md", side_effect=lambda l, **_: l) as mock_md,
        ):
            cli._emit_stream_text("bold** normal text here\n")
        # _apply_inline_md should have been called on the remainder
        if mock_md.called:
            # Get the first positional arg
            arg = mock_md.call_args_list[-1].args[0]
            assert "**" not in arg, (
                f"Closer should be stripped before passing to inline md: {arg!r}"
            )


class TestStreamFlushClosesSpec(unittest.TestCase):
    """_flush_stream closes speculative state."""

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST)
    def test_flush_closes_open_spec(self, mock_cprint):
        """_flush_stream emits remaining spec-styled text and clears stack."""
        cli = _make_emit_cli()
        cli._stream_spec_stack = [("**", _BOLD)]
        cli._stream_buf = "trailing bold text** end"
        cli._stream_block_buf.process_line = MagicMock(side_effect=lambda x: x)
        cli._stream_code_hl.process_line = MagicMock(side_effect=lambda x: x)
        cli._stream_block_buf.flush = MagicMock(return_value=None)
        cli._stream_code_hl.flush = MagicMock(return_value=None)
        with patch.object(cli, "_close_reasoning_box"):
            cli._flush_stream()
        assert cli._stream_spec_stack == []
        printed = "".join(str(c.args[0]) for c in mock_cprint.call_args_list)
        plain = _strip_ansi(printed)
        assert "**" not in plain

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST)
    def test_flush_no_spec_works_normally(self, mock_cprint):
        """_flush_stream still works when no spec state is open."""
        cli = _make_emit_cli()
        cli._stream_buf = "simple text"
        cli._stream_block_buf.process_line = MagicMock(side_effect=lambda x: x)
        cli._stream_code_hl.process_line = MagicMock(side_effect=lambda x: x)
        cli._stream_block_buf.flush = MagicMock(return_value=None)
        cli._stream_code_hl.flush = MagicMock(return_value=None)
        with (
            patch.object(cli, "_close_reasoning_box"),
            patch("cli._apply_block_line", side_effect=lambda l, **_: l),
            patch("cli._apply_inline_md", side_effect=lambda l, **_: l),
        ):
            cli._flush_stream()
        assert cli._stream_buf == ""
        assert mock_cprint.called


# ---------------------------------------------------------------------------
# Tests: end-to-end streaming scenarios
# ---------------------------------------------------------------------------

class TestEndToEndStreaming(unittest.TestCase):
    """Simulate realistic multi-token streaming scenarios."""

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST)
    def test_bold_span_across_flushes(self, mock_cprint):
        """A bold span that starts in one partial flush and closes in the next."""
        cli = _make_emit_cli()
        with (
            patch("cli._apply_block_line", side_effect=lambda l, **_: l),
            patch("cli._apply_inline_md", side_effect=lambda l, **_: l),
        ):
            # Token 1: long text with unclosed **
            cli._emit_stream_text("The quick brown fox **jumps over the lazy dog and ")
            # Token 2: closing ** then newline
            cli._emit_stream_text("lands safely** on the other side\n")
        # Verify no raw ** in output
        printed = "".join(str(c.args[0]) for c in mock_cprint.call_args_list)
        plain = _strip_ansi(printed)
        assert "**" not in plain, f"Raw ** found in: {plain!r}"
        # Spec stack should be clear after newline
        assert cli._stream_spec_stack == []

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST)
    def test_multiple_lines_each_with_bold(self, mock_cprint):
        """Each line has its own ** pair — spec state resets between lines."""
        cli = _make_emit_cli()
        with (
            patch("cli._apply_block_line", side_effect=lambda l, **_: l),
            patch("cli._apply_inline_md", side_effect=lambda l, **_: l),
        ):
            cli._emit_stream_text("First line **with bold** content\n")
            cli._emit_stream_text("Second line **also bold** content\n")
        assert cli._stream_spec_stack == []
