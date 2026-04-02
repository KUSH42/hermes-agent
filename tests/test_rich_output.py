"""Tests for agent/rich_output.py — syntax highlighting, diff rendering, code block detection."""

import re

import pytest
from unittest.mock import patch

from agent.rich_output import (
    DiffRenderer,
    FilePathFormatter,
    LanguageDetector,
    StreamingBlockBuffer,
    StreamingCodeBlockHighlighter,
    SyntaxHighlighter,
    _highlight_inline_code,
    _NUM_RE,
    _SETEXT_H1_RE,
    _SETEXT_H2_RE,
    _TABLE_ROW_RE,
    _intra_diff,
    _parse_diff_filename,
    _split_row,
    apply_block_line,
    apply_inline_markdown,
    clean_command_output,
    format_response,
    render_stateful_blocks,
)


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

def _seg_color(seg) -> str:
    """Return the colour name of a Text segment as a plain string."""
    return seg.style.color.name  # rich.color.Color.name is the canonical name string


def _renderables(diff: str) -> list:
    """Return the list of Text children from DiffRenderer._style().

    Uses ``group.renderables`` which is an internal Rich attribute.  If a
    future Rich upgrade removes it, switch to rendering the Group to a Console
    buffer and inspecting the output instead.
    """
    return list(DiffRenderer()._style(diff.splitlines()).renderables)


# ---------------------------------------------------------------------------
# LanguageDetector
# ---------------------------------------------------------------------------

class TestLanguageDetector:
    def setup_method(self):
        self.det = LanguageDetector()

    def test_detect_python_from_extension(self):
        assert self.det.detect_from_filename("foo.py") == "python"

    def test_detect_typescript_from_extension(self):
        assert self.det.detect_from_filename("app.ts") == "typescript"

    def test_detect_unknown_extension_returns_none(self):
        assert self.det.detect_from_filename("file.xyz") is None

    def test_detect_dockerfile(self):
        assert self.det.detect_from_filename("Dockerfile") == "dockerfile"

    def test_detect_makefile(self):
        assert self.det.detect_from_filename("Makefile") == "makefile"

    def test_detect_python_from_content(self):
        code = "def hello():\n    return 42\n"
        assert self.det.detect_from_content(code) == "python"

    def test_detect_javascript_from_content(self):
        code = "const x = require('fs');\nmodule.exports = x;\n"
        assert self.det.detect_from_content(code) == "javascript"

    def test_detect_bash_from_content(self):
        code = "#!/bin/bash\nif [ -f foo ]; then echo hi; fi\n"
        assert self.det.detect_from_content(code) == "bash"

    def test_detect_empty_content_returns_none(self):
        assert self.det.detect_from_content("") is None
        assert self.det.detect_from_content("   \n  ") is None

    def test_detect_prefers_filename_over_content(self):
        # .js extension should win even if content looks like Python
        assert self.det.detect("def foo(): pass", filename="script.js") == "javascript"


# ---------------------------------------------------------------------------
# FilePathFormatter
# ---------------------------------------------------------------------------

class TestFilePathFormatter:
    def test_python_icon(self):
        assert FilePathFormatter.get_file_icon("main.py") == "🐍"

    def test_rust_icon(self):
        assert FilePathFormatter.get_file_icon("lib.rs") == "🦀"

    def test_unknown_extension_fallback(self):
        assert FilePathFormatter.get_file_icon("weird.xyz") == "📄"

    def test_titled_includes_icon_and_path(self):
        result = FilePathFormatter.titled("main.py", compact=False)
        assert "🐍" in result
        assert "main.py" in result

    def test_format_path_compact_returns_relative(self, tmp_path):
        file_path = str(tmp_path / "sub" / "foo.py")
        result = FilePathFormatter.format_path(file_path, compact=True, cwd=str(tmp_path))
        assert result == "sub/foo.py"

    def test_format_path_verbose_returns_full(self, tmp_path):
        file_path = str(tmp_path / "foo.py")
        result = FilePathFormatter.format_path(file_path, compact=False)
        assert result == file_path


# ---------------------------------------------------------------------------
# SyntaxHighlighter
# ---------------------------------------------------------------------------

class TestSyntaxHighlighter:
    def setup_method(self):
        self.hl = SyntaxHighlighter()

    def test_to_ansi_returns_string(self):
        result = self.hl.to_ansi("x = 1", language="python")
        assert isinstance(result, str)
        assert "x" in result

    def test_to_ansi_contains_ansi_codes(self):
        result = self.hl.to_ansi("def foo(): pass", language="python")
        # Should contain at least one ANSI escape sequence
        assert "\033[" in result

    def test_to_markup_returns_string(self):
        result = self.hl.to_markup("x = 1", language="python")
        assert isinstance(result, str)

    def test_to_ansi_empty_string(self):
        result = self.hl.to_ansi("")
        assert isinstance(result, str)

    def test_to_ansi_fallback_on_unknown_language(self):
        # Unknown language should not crash
        result = self.hl.to_ansi("some text", language="nonexistentlang123")
        assert isinstance(result, str)
        assert "some text" in result

    def test_to_ansi_no_rogue_backslash_before_bracket(self):
        # Haskell type signatures like [Integer] must render as [Integer], not
        # [Integer\] — the old code escaped ] to \] which Rich renders literally.
        import re
        _strip = lambda s: re.sub(r"\x1b\[[0-9;]*m", "", s)
        result = _strip(self.hl.to_ansi("fib :: [Integer]", language="haskell"))
        assert "[Integer]" in result, f"Expected [Integer], got: {result!r}"
        assert r"\]" not in result, f"Rogue backslash-bracket: {result!r}"

    def test_to_ansi_lambda_backslash_no_leaking_close_tag(self):
        # Haskell lambda \ is tokenised by Pygments as Name.Function (bold
        # yellow). Without backslash-doubling the \ combined with the [/bold
        # yellow] close tag to form \[ (Rich's escape), leaking the tag text.
        import re
        _strip = lambda s: re.sub(r"\x1b\[[0-9;]*m", "", s)
        result = _strip(self.hl.to_ansi(r"fact = foldl (\a b -> a * b) 1", language="haskell"))
        assert "[/bold" not in result, f"Leaked close tag: {result!r}"

    def test_to_ansi_brackets_not_interpreted_as_rich_markup(self):
        # Rich markup tags inside code string literals must survive as literal
        # text — brackets like [bold green] and [/bold green] should appear
        # verbatim in output, not vanish because Rich consumed them as tags.
        import re
        _strip = lambda s: re.sub(r"\x1b\[[0-9;]*m", "", s)
        result = _strip(self.hl.to_ansi('printf "[bold green]hello[/bold green]\\n"', language="haskell"))
        assert "hello" in result
        assert "[bold green]" in result, f"Bracket text vanished: {result!r}"
        assert "[/bold green]" in result, f"Bracket text vanished: {result!r}"

    def test_to_markup_brackets_escaped(self):
        # to_markup output goes to Console.print() — [ must be \[-escaped so
        # Rich never interprets code content as formatting markup.
        result = self.hl.to_markup('x = "[bold]text[/bold]"', language="python")
        assert "[bold]" not in result or r"\[bold" in result


# ---------------------------------------------------------------------------
# DiffRenderer
# ---------------------------------------------------------------------------

class TestDiffRenderer:
    def setup_method(self):
        self.dr = DiffRenderer()

    def test_to_lines_returns_list(self):
        diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"
        lines = self.dr.to_lines(diff)
        assert isinstance(lines, list)
        assert len(lines) > 0

    def test_to_lines_contains_content(self):
        diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"
        lines = self.dr.to_lines(diff)
        combined = "\n".join(lines)
        assert "old" in combined
        assert "new" in combined

    def test_from_content_produces_renderable(self):
        from rich.console import Group
        result = self.dr.from_content("old line\n", "new line\n", file_path="test.py")
        assert isinstance(result, Group)

    def test_from_unified_empty_diff(self):
        # Empty diff should not crash
        result = self.dr.to_lines("")
        assert isinstance(result, list)

    def test_file_header_formatted(self):
        diff = "--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1 @@\n-x\n+y\n"
        lines = self.dr.to_lines(diff)
        combined = "\n".join(lines)
        assert "main.py" in combined

    def test_to_lines_does_not_crash_on_malformed_diff(self):
        result = self.dr.to_lines("not a real diff at all\njust some text\n")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# StreamingCodeBlockHighlighter
# ---------------------------------------------------------------------------

class TestStreamingCodeBlockHighlighter:
    def setup_method(self):
        self.hl = StreamingCodeBlockHighlighter()

    def test_plain_lines_pass_through(self):
        # Lines with no inline code are returned verbatim.
        assert self.hl.process_line("Hello world") == "Hello world"
        assert self.hl.process_line("Another line") == "Another line"

    def test_plain_line_with_inline_code_styled(self):
        import re
        result = self.hl.process_line("Use `foo()` here.")
        assert result is not None
        plain = re.sub(r"\x1b\[[0-9;]*m", "", result)
        assert "foo()" in plain
        assert "\033[" in result

    def test_opening_fence_suppressed(self):
        assert self.hl.process_line("```python") is None

    def test_code_lines_buffered(self):
        self.hl.process_line("```python")
        assert self.hl.process_line("x = 1") is None
        assert self.hl.process_line("y = 2") is None

    def test_closing_fence_flushes_highlighted(self):
        self.hl.process_line("```python")
        self.hl.process_line("x = 1")
        result = self.hl.process_line("```")
        assert result is not None
        assert "x" in result

    def test_full_code_block_sequence(self):
        lines = ["Here is code:", "```python", "def foo(): pass", "```", "Done."]
        outputs = []
        for line in lines:
            out = self.hl.process_line(line)
            if out is not None:
                outputs.append(out)
        tail = self.hl.flush()
        if tail:
            outputs.append(tail)

        combined = "\n".join(outputs)
        assert "Here is code:" in combined
        assert "foo" in combined
        assert "Done." in combined

    def test_flush_returns_none_when_no_open_block(self):
        assert self.hl.flush() is None

    def test_flush_returns_content_for_unclosed_block(self):
        self.hl.process_line("```python")
        self.hl.process_line("x = 1")
        result = self.hl.flush()
        assert result is not None
        assert "x" in result

    def test_reset_clears_state(self):
        self.hl.process_line("```python")
        self.hl.process_line("x = 1")
        self.hl.reset()
        assert self.hl.flush() is None
        # Should behave as fresh after reset
        assert self.hl.process_line("normal line") == "normal line"

    def test_multiple_blocks_in_sequence(self):
        lines = [
            "Block one:", "```python", "a = 1", "```",
            "Block two:", "```javascript", "var b = 2;", "```",
        ]
        outputs = [self.hl.process_line(l) for l in lines]
        non_none = [o for o in outputs if o is not None]
        assert len(non_none) == 4  # "Block one:", highlighted, "Block two:", highlighted

    def test_no_language_hint_still_works(self):
        self.hl.process_line("```")
        self.hl.process_line("SELECT * FROM users;")
        result = self.hl.process_line("```")
        assert result is not None
        assert "SELECT" in result

    def test_lang_hint_passed_to_highlighter(self):
        """Opening fence ```python should call to_ansi with language='python'."""
        with patch.object(self.hl._hl, "to_ansi", return_value="highlighted") as mock_ansi:
            self.hl.process_line("```python")
            self.hl.process_line("x = 1")
            self.hl.process_line("```")
        mock_ansi.assert_called_once()
        _, kwargs = mock_ansi.call_args
        assert kwargs.get("language") == "python"

    def test_no_lang_hint_calls_content_detection(self):
        """Opening fence with no hint should fall back to detect_from_content."""
        with patch.object(self.hl._det, "detect_from_content", return_value=None) as mock_det:
            self.hl.process_line("```")
            self.hl.process_line("x = 1")
            self.hl.process_line("```")
        mock_det.assert_called_once()

    def test_four_backtick_fence_opened_and_closed(self):
        """4-backtick opening fence is handled; 4-backtick closing fence closes it."""
        assert self.hl.process_line("````python") is None  # suppressed
        assert self.hl.process_line("x = 1") is None       # buffered
        result = self.hl.process_line("````")               # closes
        assert result is not None
        assert "x" in result

    def test_four_backtick_fence_three_backtick_close_ignored(self):
        """3-backtick closing fence inside a 4-backtick block is buffered, not a close."""
        assert self.hl.process_line("````python") is None
        assert self.hl.process_line("x = 1") is None
        # 3-backtick closer must NOT close a 4-backtick block
        assert self.hl.process_line("```") is None   # still buffering
        result = self.hl.flush()                      # force flush
        assert result is not None
        assert "x" in result

    def test_prose_after_four_backtick_block_rendered(self):
        """Lines after a properly-closed 4-backtick block are treated as prose."""
        self.hl.process_line("````python")
        self.hl.process_line("x = 1")
        self.hl.process_line("````")
        # Back in prose mode — next line should pass through unchanged
        out = self.hl.process_line("**bold**")
        assert out == "**bold**"


# ---------------------------------------------------------------------------
# format_response
# ---------------------------------------------------------------------------

class TestFormatResponse:
    def test_plain_text_unchanged(self):
        text = "No code here, just text."
        result = format_response(text)
        assert "No code here, just text." in result

    def test_code_block_highlighted(self):
        text = "Here:\n```python\ndef foo(): pass\n```\nDone."
        result = format_response(text)
        assert "foo" in result
        assert "Here:" in result
        assert "Done." in result

    def test_multiple_code_blocks(self):
        text = "First:\n```python\nx = 1\n```\nSecond:\n```javascript\nvar y = 2;\n```"
        result = format_response(text)
        assert "x" in result
        assert "y" in result

    def test_no_code_blocks_returns_original(self):
        text = "Just a response with no fences."
        assert format_response(text) == text

    def test_empty_string(self):
        assert format_response("") == ""

    def test_code_block_without_language(self):
        text = "```\nSELECT * FROM t;\n```"
        result = format_response(text)
        assert "SELECT" in result

    def test_no_lang_hint_calls_content_detection(self):
        """Fence with no lang tag should call LanguageDetector.detect_from_content."""
        from unittest.mock import patch, MagicMock
        with patch("agent.rich_output.LanguageDetector") as MockLD:
            mock_instance = MagicMock()
            mock_instance.detect_from_content.return_value = None
            MockLD.return_value = mock_instance
            format_response("```\nSELECT * FROM t;\n```")
        mock_instance.detect_from_content.assert_called_once()

    def test_code_block_content_not_markdown_rendered(self):
        """Code fence content must not have apply_block_line/apply_inline_markdown applied.

        Pygments plain-text lexer emits some lines without ANSI codes; those
        lines must still be skipped by pass 2 so markdown markers stay literal.
        """
        text = "```\n### raw heading\n**raw bold**\n- raw item\n```\nDone."
        result = format_response(text)
        plain = re.sub(r"\x1b\[[0-9;]*m", "", result)
        # Code block content must appear literally
        assert "### raw heading" in plain
        assert "**raw bold**" in plain
        assert "- raw item" in plain
        # Prose after the block still renders
        assert "Done." in plain

    def test_four_backtick_fence_consumed(self):
        """format_response consumes 4-backtick fences and highlights their content."""
        text = "Intro.\n````python\nx = 1\n````\nDone."
        result = format_response(text)
        assert "Intro." in result
        assert "Done." in result
        assert "x" in result
        # Fences should be consumed (no raw backtick-only lines)
        for line in result.splitlines():
            assert not line.strip().startswith("````"), f"fence leaked: {line!r}"

    def test_nested_three_in_four_backtick_fence(self):
        """3-backtick inner content inside a 4-backtick fence is highlighted as code."""
        text = "````markdown\n```python\ndef foo(): pass\n```\n````\nAfter."
        result = format_response(text)
        assert "After." in result
        # The outer 4-backtick block is consumed; inner ``` lines are code content
        for line in result.splitlines():
            assert not line.strip() == "````", f"4-backtick fence leaked: {line!r}"

    def test_inline_code_in_prose_styled(self):
        """Inline code spans in prose get ANSI styling."""
        text = "Use `foo()` to call it."
        result = format_response(text)
        assert "\033[" in result
        import re as _re
        plain = _re.sub(r"\x1b\[[0-9;]*m", "", result)
        assert "foo()" in plain

    def test_inline_code_not_applied_inside_fenced_block(self):
        """Backtick spans inside fenced code blocks are not double-styled."""
        text = "```python\nx = `foo`\n```"
        result = format_response(text)
        # The fenced block content should not contain the inline-code ANSI prefix
        # (48;5;237 is the inline code background index — only used by
        # _highlight_inline_code, never by apply_inline_markdown's _MD_CODE_RE)
        assert "48;5;237" not in result

    def test_inline_code_preserved_in_plain_text(self):
        """Inline code content survives styling."""
        import re as _re
        text = "The `fmap` function maps over a functor."
        result = format_response(text)
        plain = _re.sub(r"\x1b\[[0-9;]*m", "", result)
        assert "fmap" in plain

    def test_prose_without_backticks_unchanged(self):
        """Plain prose with no backticks is returned verbatim."""
        text = "Just a response with no fences."
        assert format_response(text) == text

    def test_code_fence_inside_blockquote_not_consumed(self):
        """Fences prefixed with > must not be treated as code block openers.

        Regression: the old un-anchored regex matched ``` mid-line, causing
        > ```python lines to be syntax-highlighted and the \x1b guard to then
        skip apply_block_line — so blockquote lines rendered with raw > instead
        of the ▌ gutter.
        """
        text = "> ```python\n> x = 1\n> ```\nAfter."
        result = format_response(text)
        plain = re.sub(r"\x1b\[[0-9;]*m", "", result)
        # Blockquote gutter must appear; raw > must not lead these lines
        assert "▌" in plain
        assert "After." in plain


# ---------------------------------------------------------------------------
# _highlight_inline_code unit tests
# ---------------------------------------------------------------------------

class TestHighlightInlineCode:
    def _strip(self, s: str) -> str:
        import re
        return re.sub(r"\x1b\[[0-9;]*m", "", s)

    def test_single_span_styled(self):
        result = _highlight_inline_code("Use `foo()` here.")
        assert "\033[" in result
        assert "foo()" in self._strip(result)

    def test_multiple_spans_styled(self):
        result = _highlight_inline_code("`a` and `b`")
        plain = self._strip(result)
        assert "a" in plain and "b" in plain
        assert result.count("\033[48;5;237m") == 2

    def test_no_backticks_unchanged(self):
        text = "No inline code here."
        assert _highlight_inline_code(text) == text

    def test_backtick_content_preserved(self):
        result = _highlight_inline_code("`m :: f (a -> Either e a)`")
        assert "m :: f (a -> Either e a)" in self._strip(result)

    def test_multiline_span_not_matched(self):
        """A backtick span crossing a newline must NOT be treated as inline code."""
        text = "`line one\nline two`"
        result = _highlight_inline_code(text)
        assert result == text  # no ANSI injected across a newline


# ---------------------------------------------------------------------------
# clean_command_output
# ---------------------------------------------------------------------------

class TestCleanCommandOutput:
    def test_strips_venv_paths(self):
        noisy = "/home/user/venv/lib/python3.11/site-packages/foo.py\nActual output"
        result = clean_command_output(noisy)
        assert "site-packages" not in result
        assert "Actual output" in result

    def test_keeps_meaningful_lines(self):
        output = "Build succeeded\n3 tests passed\nDone."
        result = clean_command_output(output)
        assert "Build succeeded" in result
        assert "3 tests passed" in result

    def test_empty_string(self):
        assert clean_command_output("") == ""

    def test_removes_excessive_blank_lines(self):
        output = "line1\n\n\n\n\nline2"
        result = clean_command_output(output)
        assert result.count("\n") < 3


# ---------------------------------------------------------------------------
# _intra_diff unit tests
# ---------------------------------------------------------------------------

class TestIntraDiff:
    def test_equal_spans_use_base_colour(self):
        del_segs, add_segs = _intra_diff("abc", "abc")
        for seg in del_segs + add_segs:
            assert not seg.style.bold
            assert _seg_color(seg) == "white"

    def test_changed_span_highlighted(self):
        del_segs, add_segs = _intra_diff("foo bar", "foo baz")
        # There must be at least one bright_red segment in del and bright_green in add
        del_highlighted = [s for s in del_segs if _seg_color(s) == "bright_red"]
        add_highlighted = [s for s in add_segs if _seg_color(s) == "bright_green"]
        assert del_highlighted, "expected at least one bright_red segment in del_segs"
        assert add_highlighted, "expected at least one bright_green segment in add_segs"
        # All highlighted segments must be bold
        assert all(s.style.bold for s in del_highlighted)
        assert all(s.style.bold for s in add_highlighted)
        # Equal spans must be white and not bold
        del_equal = [s for s in del_segs if _seg_color(s) == "white"]
        assert del_equal, "expected equal (white) segments in del_segs"
        assert all(not s.style.bold for s in del_equal)

    def test_delete_opcode_no_add_seg(self):
        del_segs, add_segs = _intra_diff("abcXYZ", "abc")
        del_plain = "".join(s.plain for s in del_segs)
        add_plain = "".join(s.plain for s in add_segs)
        assert "XYZ" in del_plain
        assert len(add_plain) == 3  # only "abc"

    def test_insert_opcode_no_del_seg(self):
        del_segs, add_segs = _intra_diff("abc", "abcXYZ")
        del_plain = "".join(s.plain for s in del_segs)
        add_plain = "".join(s.plain for s in add_segs)
        assert "XYZ" in add_plain
        assert len(del_plain) == 3  # only "abc"


# ---------------------------------------------------------------------------
# _parse_diff_filename unit tests
# ---------------------------------------------------------------------------

class TestParseDiffFilename:
    def test_strips_b_prefix(self):
        assert _parse_diff_filename("b/src/foo.py") == "foo.py"

    def test_strips_a_prefix(self):
        assert _parse_diff_filename("a/src/foo.py") == "foo.py"

    def test_bare_path(self):
        assert _parse_diff_filename("path/bar.py") == "bar.py"

    def test_devnull_falls_back_to_from(self):
        assert _parse_diff_filename("/dev/null", "a/old.py") == "old.py"

    def test_devnull_no_fallback_returns_question(self):
        assert _parse_diff_filename("/dev/null") == "?"


# ---------------------------------------------------------------------------
# DiffRenderer v2 rendering tests
# ---------------------------------------------------------------------------

_SIMPLE_DIFF = (
    "--- a/foo.py\n"
    "+++ b/foo.py\n"
    "@@ -1,2 +1,2 @@\n"
    "-foo bar\n"
    "+foo baz\n"
    " context\n"
)

_LOW_RATIO_DIFF = (
    "--- a/foo.py\n"
    "+++ b/foo.py\n"
    "@@ -1 +1 @@\n"
    "-aaaa\n"
    "+zzzz\n"
)


class TestDiffRendererV2:
    def test_intra_diff_skipped_below_ratio(self):
        import re
        from io import StringIO
        from rich.console import Console
        buf = StringIO()
        Console(file=buf, force_terminal=True, highlight=False, width=220).print(
            DiffRenderer()._style(_LOW_RATIO_DIFF.splitlines())
        )
        lines = buf.getvalue().splitlines()
        del_line = next(l for l in lines if "aaaa" in re.sub(r"\x1b\[[0-9;]*m", "", l))
        # bright_red bold is encoded as \x1b[1;91; — must not appear on a flat-colour line
        assert "\x1b[1;91;" not in del_line

    def test_pairing_per_run_not_per_hunk(self):
        # Use pairs with ratio > 0.5 so intra-diff triggers.
        # "return foo_value" vs "return bar_value": share "return " + "_value" = 13 chars,
        # total = 32, ratio = 26/32 ≈ 0.81.
        diff = (
            "--- a/f.py\n+++ b/f.py\n"
            "@@ -1,3 +1,3 @@\n"
            "-return foo_value\n"
            "+return bar_value\n"
            " context\n"
            "-return foo_result\n"
            "+return bar_result\n"
        )
        import re
        from io import StringIO
        from rich.console import Console
        buf = StringIO()
        Console(file=buf, force_terminal=True, highlight=False, width=220).print(
            DiffRenderer()._style(diff.splitlines())
        )
        output = buf.getvalue()
        # Both pairs should produce intra-highlighted changed chars
        assert output.count("\x1b[1;91;") >= 2  # bright_red bold in both del lines
        assert output.count("\x1b[1;92;") >= 2  # bright_green bold in both add lines

    def test_alternating_run_flush(self):
        # -A +B -C +D with no context between — should pair (-A,+B) and (-C,+D)
        diff = (
            "--- a/f.py\n+++ b/f.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-alpha\n"
            "+ALPHA\n"
            "-beta\n"
            "+BETA\n"
        )
        renderables = _renderables(diff)
        all_plain = " ".join(r.plain for r in renderables)
        assert "alpha" in all_plain
        assert "ALPHA" in all_plain
        assert "beta" in all_plain
        assert "BETA" in all_plain

    def test_unpaired_lines_flat_colour(self):
        diff = (
            "--- a/f.py\n+++ b/f.py\n"
            "@@ -1,2 +1,1 @@\n"
            "-first del\n"
            "-second del\n"
            "+one add\n"
        )
        import re
        from io import StringIO
        from rich.console import Console
        buf = StringIO()
        Console(file=buf, force_terminal=True, highlight=False, width=220).print(
            DiffRenderer()._style(diff.splitlines())
        )
        output = buf.getvalue()
        lines = output.splitlines()
        second_del = next(
            l for l in lines
            if "second del" in re.sub(r"\x1b\[[0-9;]*m", "", l)
        )
        assert "\x1b[91m" not in second_del  # no bright_red on unpaired line

    def test_summary_header_add_only(self):
        diff = "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n+new\n"
        renderables = _renderables(diff)
        plain = renderables[0].plain
        assert "Added" in plain
        assert "removed" not in plain

    def test_summary_header_remove_only(self):
        diff = "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-old\n"
        plain = _renderables(diff)[0].plain
        assert "Removed" in plain
        assert "Added" not in plain

    def test_summary_header_mixed(self):
        diff = "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-old\n+new\n"
        plain = _renderables(diff)[0].plain
        assert "Added" in plain
        assert "removed" in plain

    def test_summary_header_plural(self):
        diff = "--- a/f.py\n+++ b/f.py\n@@ -1 +2 @@\n+line1\n+line2\n"
        plain = _renderables(diff)[0].plain
        assert "Added 2 lines" in plain

    def test_summary_header_singular(self):
        diff = "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n+line1\n"
        plain = _renderables(diff)[0].plain
        assert "Added 1 line" in plain
        assert "lines" not in plain

    def test_summary_header_contains_filename(self):
        diff = "--- a/src/foo.py\n+++ b/src/foo.py\n@@ -1 +1 @@\n+x\n"
        plain = _renderables(diff)[0].plain
        assert "foo.py" in plain

    def test_summary_header_strips_b_prefix(self):
        diff = "--- a/path/bar.py\n+++ b/path/bar.py\n@@ -1 +1 @@\n+x\n"
        plain = _renderables(diff)[0].plain
        assert "bar.py" in plain
        assert "b/bar.py" not in plain

    def test_summary_header_bare_path(self):
        diff = "--- path/bar.py\n+++ path/bar.py\n@@ -1 +1 @@\n+x\n"
        plain = _renderables(diff)[0].plain
        assert "bar.py" in plain

    def test_summary_header_devnull_fallback(self):
        diff = "--- a/old.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n"
        plain = _renderables(diff)[0].plain
        assert "old.py" in plain

    def test_multi_file_diff_two_headers(self):
        diff = (
            "--- a/one.py\n+++ b/one.py\n@@ -1 +1 @@\n+x\n"
            "--- a/two.py\n+++ b/two.py\n@@ -1 +1 @@\n+y\n"
        )
        renderables = _renderables(diff)
        header_plains = [r.plain for r in renderables if "●" in r.plain]
        assert len(header_plains) == 2
        assert any("one.py" in p for p in header_plains)
        assert any("two.py" in p for p in header_plains)

    def test_separator_width_matches_header(self):
        diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n+x\n"
        renderables = _renderables(diff)
        header = renderables[0]
        separator = renderables[1]
        assert len(separator.plain) == len(header.plain)


# ---------------------------------------------------------------------------
# apply_inline_markdown
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip(s: str) -> str:
    """Strip all ANSI escape codes from s."""
    return _ANSI_RE.sub("", s)


class TestApplyInlineMarkdown:
    def test_bold_double_asterisk(self):
        result = apply_inline_markdown("**foo**")
        assert "\033[1m" in result
        assert "foo" in result
        assert "**" not in result

    def test_bold_double_underscore(self):
        result = apply_inline_markdown("__foo__")
        assert "\033[1m" in result
        assert "foo" in result
        assert "__" not in result

    def test_italic_single_asterisk(self):
        result = apply_inline_markdown("*foo*")
        assert "\033[3m" in result
        assert "foo" in result
        assert result.count("*") == 0

    def test_italic_single_underscore(self):
        result = apply_inline_markdown("_foo_")
        assert "\033[3m" in result
        assert "foo" in result
        assert "_" not in result

    def test_italic_underscore_multi_word(self):
        result = apply_inline_markdown("_underline - kinda works_")
        assert "\033[3m" in result
        assert "underline - kinda works" in result
        assert "_" not in result

    def test_italic_single_underscore_with_spaces(self):
        result = apply_inline_markdown("This is _super bold and italic_ text.")
        assert "\033[3m" in result
        assert "super bold and italic" in result
        assert "_" not in result

    def test_underscore_inside_word_ignored(self):
        result = apply_inline_markdown("snake_case_var")
        assert result == "snake_case_var"

    def test_trailing_underscore_ignored(self):
        assert apply_inline_markdown("value_") == "value_"

    def test_leading_underscore_ignored(self):
        assert apply_inline_markdown("_private") == "_private"

    def test_backtick_code_span(self):
        result = apply_inline_markdown("`foo`")
        assert "\033[97m" in result
        assert "foo" in result
        assert "`" not in result

    def test_strikethrough(self):
        result = apply_inline_markdown("~~foo~~")
        assert "\033[9m" in result
        assert "foo" in result
        assert "~~" not in result

    def test_mixed_bold_and_code(self):
        result = apply_inline_markdown("**Line 88**: `cdOffset`")
        assert "\033[1m" in result   # bold applied
        assert "\033[97m" in result  # code span applied
        assert "**" not in result
        assert "`" not in result

    def test_asterisks_inside_backtick_untouched(self):
        result = apply_inline_markdown("`**not bold**`")
        # Content inside code span must not be bold-rendered
        assert "\033[1m" not in result
        assert "**not bold**" in result

    def test_already_ansi_returned_unchanged(self):
        ansi_line = "\033[32mgreen\033[0m"
        assert apply_inline_markdown(ansi_line) is ansi_line

    def test_empty_string(self):
        assert apply_inline_markdown("") == ""

    def test_plain_text_unchanged(self):
        assert apply_inline_markdown("plain text") == "plain text"

    def test_reset_suffix_restored_between_spans(self):
        colour = "\033[32m"
        result = apply_inline_markdown("**a** and *b*", reset_suffix=colour)
        # Each closing reset should be followed by the colour suffix
        assert f"\033[0m{colour}" in result

    def test_no_markdown(self):
        assert apply_inline_markdown("no markdown here") == "no markdown here"

    def test_em_tag_italic(self):
        result = apply_inline_markdown("<em>foo</em>")
        assert "\033[3m" in result
        assert "foo" in result
        assert "<em>" not in result
        assert "</em>" not in result

    def test_strong_tag_bold(self):
        result = apply_inline_markdown("<strong>foo</strong>")
        assert "\033[1m" in result
        assert "foo" in result
        assert "<strong>" not in result

    def test_u_tag_underline(self):
        result = apply_inline_markdown("<u>foo</u>")
        assert "\033[4m" in result
        assert "foo" in result
        assert "<u>" not in result

    def test_mark_tag_highlight(self):
        result = apply_inline_markdown("<mark>foo</mark>")
        assert "\033[7m" in result
        assert "foo" in result
        assert "<mark>" not in result

    def test_u_tag_with_inner_bold_restores_underline(self):
        # Inner bold reset must restore underline, not drop it.
        result = apply_inline_markdown("<u>**bold** normal</u>")
        # Underline code appears before bold
        assert result.index("\033[4m") < result.index("\033[1m")
        # reset_suffix "\033[4m" appears after the bold reset, restoring underline
        ansi_codes = [result[i:i+4] for i in range(len(result)) if result[i:i+2] == "\033["]
        assert result.count("\033[4m") >= 2  # outer open + reset_suffix restore

    def test_bold_italic_triple_star(self):
        result = apply_inline_markdown("***foo***")
        assert "\033[1;3m" in result
        assert "foo" in result
        assert "*" not in _strip(result)

    def test_bold_italic_triple_underscore(self):
        result = apply_inline_markdown("___foo___")
        assert "\033[1;3m" in result
        assert "foo" in result

    def test_i_tag_italic(self):
        result = apply_inline_markdown("<i>foo</i>")
        assert "\033[3m" in result
        assert "<i>" not in result

    def test_b_tag_bold(self):
        result = apply_inline_markdown("<b>foo</b>")
        assert "\033[1m" in result
        assert "<b>" not in result

    def test_s_tag_strikethrough(self):
        result = apply_inline_markdown("<s>foo</s>")
        assert "\033[9m" in result
        assert "<s>" not in result

    def test_strike_tag_strikethrough(self):
        result = apply_inline_markdown("<strike>foo</strike>")
        assert "\033[9m" in result
        assert "<strike>" not in result

    def test_del_tag_strikethrough(self):
        result = apply_inline_markdown("<del>foo</del>")
        assert "\033[9m" in result
        assert "<del>" not in result

    def test_code_tag_inline(self):
        result = apply_inline_markdown("<code>foo</code>")
        assert "\033[97m" in result
        assert "<code>" not in result

    def test_kbd_tag_code_style(self):
        result = apply_inline_markdown("<kbd>Ctrl+C</kbd>")
        assert "\033[97m" in result
        assert "<kbd>" not in result

    def test_ins_tag_underline(self):
        result = apply_inline_markdown("<ins>foo</ins>")
        assert "\033[4m" in result
        assert "<ins>" not in result

    def test_sup_tag_stripped(self):
        result = apply_inline_markdown("x<sup>2</sup>")
        assert "<sup>" not in result
        assert "2" in result

    def test_sub_tag_stripped(self):
        result = apply_inline_markdown("H<sub>2</sub>O")
        assert "<sub>" not in result
        assert "2" in result
        assert "H" in result
        assert "O" in result

    def test_link_underlined(self):
        result = apply_inline_markdown("[click here](https://x.com)")
        assert "\033[4m" in result
        assert "click here" in result
        assert "https://x.com" not in _strip(result)
        assert "[click here]" not in _strip(result)

    def test_image_placeholder(self):
        result = apply_inline_markdown("![logo](img.png)")
        assert "[img: logo]" in result
        assert "\033[2m" in result
        assert "img.png" not in result

    def test_image_before_link(self):
        result = apply_inline_markdown("![a](u) [b](v)")
        assert "[img: a]" in result
        assert "\033[4m" in result
        assert "b" in result


class TestApplyBlockLine:
    def test_h1_stripped_and_bold(self):
        result = apply_block_line("# Foo")
        assert "\033[1;97m" in result
        assert "Foo" in result
        assert "#" not in result

    def test_h2_dimmer_than_h1(self):
        result = apply_block_line("## Foo")
        assert "\033[1;37m" in result
        assert "97m" not in result

    def test_h4_bold_dim(self):
        result = apply_block_line("#### Foo")
        assert "\033[1;2m" in result

    def test_h1_with_inline_span(self):
        result = apply_block_line("# **Foo**")
        assert "\033[1;97m" in result
        assert "\033[1m" in result
        assert "Foo" in result
        assert "**" not in result

    def test_hr_dashes_replaced(self):
        result = apply_block_line("---")
        assert "─" in result
        assert "-" not in _strip(result)

    def test_hr_stars_replaced(self):
        result = apply_block_line("***")
        assert "─" in result

    def test_hr_underscores_replaced(self):
        result = apply_block_line("___")
        assert "─" in result

    def test_non_hr_dashes_unchanged(self):
        result = apply_block_line("some --- text")
        assert result == "some --- text"

    def test_blockquote_gutter(self):
        result = apply_block_line("> hello")
        assert "▌" in result
        assert "hello" in result
        assert ">" not in result

    def test_blockquote_nested_collapsed(self):
        result = apply_block_line(">> deep")
        assert result.count("▌") == 1

    def test_blockquote_inline_span(self):
        result = apply_block_line("> **bold**")
        assert "▌" in result
        assert "\033[1m" in result
        assert "**" not in result

    def test_blockquote_inline_span_restores_dim(self):
        # Bold span inside a blockquote must restore the dim gutter style on close,
        # not reset to terminal default — fixes missing reset_suffix on blockquote branch.
        result = apply_block_line("> **bold** plain")
        # Dim style (\033[2m) must appear after the bold close (\033[0m)
        assert "\033[0m\033[2m" in result

    def test_list_bullet_dot(self):
        result = apply_block_line("- item")
        assert "•" in result
        assert "item" in result
        assert result.startswith("•")

    def test_list_bullet_circle_nested(self):
        result = apply_block_line("  - item")
        assert "◦" in result

    def test_list_bullet_triangle_double_nested(self):
        result = apply_block_line("    - item")
        assert "▸" in result

    def test_list_star_and_plus(self):
        assert "•" in apply_block_line("* item")
        assert "•" in apply_block_line("+ item")

    def test_ordered_list_unchanged(self):
        result = apply_block_line("1. item")
        assert result == "1. item"

    def test_reference_link_suppressed(self):
        result = apply_block_line("[ref]: https://x.com")
        assert result == ""

    def test_reference_link_with_quoted_title_suppressed(self):
        assert apply_block_line('[ref]: https://x.com "Page Title"') == ""

    def test_reference_link_with_paren_title_suppressed(self):
        assert apply_block_line("[ref]: https://x.com (Page Title)") == ""

    def test_ansi_lines_skipped(self):
        ansi_line = "\033[32mgreen\033[0m"
        assert apply_block_line(ansi_line) is ansi_line

    def test_multiline_skipped(self):
        multi = "line1\nline2"
        assert apply_block_line(multi) is multi

    def test_plain_line_unchanged(self):
        assert apply_block_line("just text") == "just text"


class TestFormatResponseInlineMarkdown:
    """Integration: format_response applies inline markdown to prose, not code."""

    def test_bold_in_prose_rendered(self):
        text = "This is **important** text."
        result = format_response(text)
        assert "\033[1m" in result
        assert "important" in result
        assert "**" not in result

    def test_heading_followed_by_paragraph_preserves_newline(self):
        # apply_block_line drops the trailing \n from matched lines; format_response
        # must compensate so the paragraph starts on its own line.
        text = "# Title\nParagraph text"
        result = format_response(text)
        plain = _strip(result)
        # Heading and paragraph must be on separate lines
        assert plain.index("Title") < plain.index("\n")
        assert "Paragraph text" in plain

    def test_list_followed_by_paragraph_preserves_newline(self):
        text = "- item one\nnext line"
        result = format_response(text)
        plain = _strip(result)
        assert "item one" in plain
        assert plain.index("item one") < plain.index("\n")
        assert "next line" in plain

    def test_code_block_not_double_escaped(self):
        text = "Note **this**:\n```python\nx = **1**\n```\nEnd **here**."
        result = format_response(text)
        # Prose bold rendered
        assert "\033[1m" in result
        # The Python code block was syntax-highlighted; the ** inside are code
        # content — they appear as plain chars inside the highlighted block,
        # not as ANSI bold markers.  Verify no double-escape by checking that
        # the result does not contain literal \033[1m immediately followed by
        # content that was already inside an ANSI span.
        # Simpler: strip all ANSI and confirm code content intact
        plain = _strip(result)
        assert "x = **1**" in plain

    def test_backslash_escape_stripped(self):
        r"""CommonMark backslash escapes like \] and \* are stripped from output."""
        result = apply_inline_markdown(r"- [ \] unchecked")
        assert r"\]" not in result
        assert "]" in result

    def test_backslash_escape_checkbox(self):
        r"""[x\] renders as [x] — backslash before ] removed."""
        result = apply_inline_markdown(r"- [x\] checked item")
        assert r"\]" not in result
        assert "[x]" in _strip(result)


# ---------------------------------------------------------------------------
# render_stateful_blocks — regex smoke tests
# ---------------------------------------------------------------------------

class TestStatefulBlockRegexes:
    def test_setext_h1_re_matches(self):
        assert _SETEXT_H1_RE.match("==")
        assert _SETEXT_H1_RE.match("===")
        assert _SETEXT_H1_RE.match("===  ")
        assert not _SETEXT_H1_RE.match("=")
        assert not _SETEXT_H1_RE.match("=== text")

    def test_setext_h2_re_matches(self):
        assert _SETEXT_H2_RE.match("--")
        assert _SETEXT_H2_RE.match("---")
        assert _SETEXT_H2_RE.match("---  ")
        assert not _SETEXT_H2_RE.match("-")
        assert not _SETEXT_H2_RE.match("--- text")

    def test_table_row_re(self):
        assert _TABLE_ROW_RE.match("| a | b |")
        assert _TABLE_ROW_RE.match("|---|---|")
        assert not _TABLE_ROW_RE.match("a | b")
        assert not _TABLE_ROW_RE.match("| no trailing")

    def test_num_re(self):
        assert _NUM_RE.match("42")
        assert _NUM_RE.match("1,000")
        assert _NUM_RE.match("3.14")
        assert _NUM_RE.match("-7")
        assert not _NUM_RE.match("abc")
        assert not _NUM_RE.match("1a")

    def test_split_row(self):
        assert _split_row("| a | b |") == [" a ", " b "]
        assert _split_row("|---|---|") == ["---", "---"]


# ---------------------------------------------------------------------------
# render_stateful_blocks — setext headings
# ---------------------------------------------------------------------------

class TestRenderStatefulBlocksSetext:
    def test_setext_h1(self):
        result = render_stateful_blocks("Foo\n===")
        assert "\033[1;97m" in result
        assert "Foo" in result
        assert "===" not in result

    def test_setext_h2(self):
        result = render_stateful_blocks("Bar\n---")
        assert "\033[1;37m" in result
        assert "Bar" in result
        assert "---" not in result

    def test_blank_line_dash_is_hr_not_h2(self):
        result = format_response("\n---")
        plain = _strip(result)
        assert "─" in plain
        assert "\033[1;37m" not in result

    def test_list_item_dash_is_hr(self):
        result = format_response("- x\n---")
        assert "\033[1;37m" not in result
        plain = _strip(result)
        assert "─" in plain

    def test_setext_with_inline_span(self):
        result = render_stateful_blocks("**Foo**\n===")
        assert "\033[1;97m" in result
        assert "\033[1m" in result
        assert "Foo" in result
        assert "**" not in result

    def test_setext_at_end_of_string_no_newline(self):
        result = render_stateful_blocks("Title\n===")
        assert "\033[1;97m" in result
        assert "===" not in result

    def test_ansi_pending_not_heading(self):
        result = render_stateful_blocks("\033[1mcode\033[0m\n===")
        assert "===" in result
        assert "\033[1;97m" not in result

    def test_trailing_whitespace_marker(self):
        result = render_stateful_blocks("Foo\n===  ")
        assert "\033[1;97m" in result
        assert "===" not in result

    def test_marker_at_document_start(self):
        # --- at document start renders as hr, not setext h2
        result = format_response("---\ntext")
        plain = _strip(result)
        assert "─" in plain
        assert "text" in plain
        assert "\033[1;37m" not in result


# ---------------------------------------------------------------------------
# render_stateful_blocks — multi-line blockquote continuation
# ---------------------------------------------------------------------------

class TestRenderStatefulBlocksBlockquote:
    def test_continuation_has_gutter(self):
        result = render_stateful_blocks("> q\ncontinuation")
        assert result.count("▌") == 2

    def test_blank_line_ends_continuation(self):
        result = render_stateful_blocks("> q\n\nnormal")
        lines = result.splitlines()
        normal_line = [l for l in lines if "normal" in l][0]
        assert "▌" not in normal_line

    def test_explicit_bq_resets(self):
        result = render_stateful_blocks("> q\n\n> new")
        assert result.count("▌") == 2


# ---------------------------------------------------------------------------
# render_stateful_blocks — tables
# ---------------------------------------------------------------------------

class TestRenderStatefulBlocksTables:
    _TABLE = "| Name | Age |\n|------|-----|\n| Alice | 28 |\n| Bob | 32 |"

    def test_basic_table_rendered(self):
        result = render_stateful_blocks(self._TABLE)
        plain = _strip(result)
        assert "─" in plain
        assert "Alice" in plain
        assert "Bob" in plain
        assert "|" not in plain

    def test_right_aligned_column(self):
        t = "| Name | Age |\n|------|----:|\n| Alice | 28 |"
        result = render_stateful_blocks(t)
        lines = _strip(result).splitlines()
        data = [l for l in lines if "Alice" in l][0]
        # "28" should appear right-justified (preceded by spaces)
        assert "28" in data
        idx_28 = data.index("28")
        assert data[idx_28 - 1] == " "

    def test_centre_aligned_column(self):
        t = "| Name |\n|:----:|\n| Hi |"
        result = render_stateful_blocks(t)
        plain = _strip(result)
        assert "Hi" in plain

    def test_number_auto_right(self):
        t = "| Item | Count |\n|------|-------|\n| foo | 42 |"
        result = render_stateful_blocks(t)
        plain = _strip(result)
        assert "42" in plain

    def test_ragged_row_padded(self):
        t = "| A | B | C |\n|---|---|---|\n| x |"
        result = render_stateful_blocks(t)
        assert "x" in _strip(result)

    def test_ragged_align_no_error(self):
        t = "| A | B | C |\n|---|---|\n| x | y | z |"
        result = render_stateful_blocks(t)
        assert "x" in _strip(result)

    def test_table_at_end_no_newline(self):
        t = "| A |\n|---|\n| x |"
        result = render_stateful_blocks(t)
        assert "x" in _strip(result)
        assert "|" not in _strip(result)

    def test_table_no_separator(self):
        t = "| A | B |\n| x | y |\n| z | w |"
        result = render_stateful_blocks(t)
        plain = _strip(result)
        assert "x" in plain
        assert "─" not in plain


    def test_inline_markdown_in_cells_does_not_misalign_columns(self):
        # Cells with **bold** markup: rendered visual width must match padding.
        md = "| A | B |\n|---|---|\n| **hi** | x |\n| bye | y |"
        out = format_response(md)
        lines = [l for l in out.splitlines() if l.strip() and "─" not in l]
        # All data lines must have the same visual length (consistent column widths).
        import re
        ansi = re.compile(r"\x1b\[[0-9;]*m")
        visual_lens = [len(ansi.sub("", l)) for l in lines]
        assert len(set(visual_lens)) == 1, f"Column widths diverged: {visual_lens}"


# ---------------------------------------------------------------------------
# StreamingBlockBuffer
# ---------------------------------------------------------------------------

class TestStreamingBlockBuffer:
    def setup_method(self):
        self.buf = StreamingBlockBuffer()

    def test_setext_h1_on_marker(self):
        assert self.buf.process_line("Foo") is None
        result = self.buf.process_line("===")
        assert result is not None
        assert "\033[1;97m" in result
        assert "Foo" in result

    def test_setext_non_marker_releases_pending(self):
        assert self.buf.process_line("Foo") is None
        result = self.buf.process_line("bar")
        assert result == "Foo"
        # "bar" is now pending
        flushed = self.buf.flush()
        assert flushed == "bar"

    def test_setext_flush_emits_pending(self):
        assert self.buf.process_line("Foo") is None
        result = self.buf.flush()
        assert result == "Foo"

    def test_setext_ansi_line_not_held(self):
        ansi = "\033[1mx\033[0m"
        result = self.buf.process_line(ansi)
        assert result is ansi  # returned immediately

    def test_table_rows_none_until_done(self):
        assert self.buf.process_line("| A | B |") is None
        assert self.buf.process_line("|---|---|") is None
        assert self.buf.process_line("| x | y |") is None
        non_table = "done"
        result = self.buf.process_line(non_table)
        assert result is not None
        assert "x" in _strip(result)
        # Next call returns the non-table line
        next_result = self.buf.process_line("anything")
        assert next_result == "done"

    def test_table_flush_emits_partial(self):
        self.buf.process_line("| A |")
        self.buf.process_line("|---|")
        self.buf.process_line("| x |")
        result = self.buf.flush()
        assert result is not None
        assert "x" in _strip(result)

    def test_table_non_table_line_identity(self):
        self.buf.process_line("| A |")
        self.buf.process_line("|---|")
        self.buf.process_line("| x |")
        non_table = "plain line"
        self.buf.process_line(non_table)  # returns rendered table
        # Next call should return the non-table line with same identity
        result = self.buf.process_line("next")
        assert result is non_table

    def test_blockquote_continuation_stateful(self):
        self.buf.process_line("some")  # goes to pending
        self.buf.flush()
        self.buf.reset()
        # Fresh: enter blockquote, then continuation
        r1 = self.buf.process_line("> quote")
        # r1 may be None (pending setext) or the bq line
        # Force through: no pending, so should return gutter immediately
        self.buf.reset()
        r1 = self.buf.process_line("> quote")
        assert r1 is not None
        assert "▌" in r1
        r2 = self.buf.process_line("continuation")
        assert r2 is not None
        assert "▌" in r2

    def test_blockquote_ansi_gets_gutter(self):
        # ANSI line inside blockquote keeps the gutter and stays in blockquote
        self.buf.process_line("> start")
        ansi = "\033[1mx\033[0m"
        result = self.buf.process_line(ansi)
        assert result is not None
        assert "▌" in result
        assert ansi in result
        assert self.buf._in_blockquote  # stays in blockquote

    def test_blockquote_fence_exits_state(self):
        # Code fence line exits blockquote so the code highlighter can handle it
        self.buf.process_line("> start")
        result = self.buf.process_line("```python")
        assert result == "```python"
        assert not self.buf._in_blockquote

    def test_mode_transition_pending_plus_blockquote(self):
        assert self.buf.process_line("pending_line") is None
        result = self.buf.process_line("> blockquote")
        assert result == "pending_line"
        # Next call should return rendered blockquote
        result2 = self.buf.process_line("next")
        assert result2 is not None
        assert "▌" in result2

    def test_mode_transition_pending_plus_table(self):
        assert self.buf.process_line("pending_line") is None
        result = self.buf.process_line("| A |")
        assert result == "pending_line"
        # Next call processes "| A |" (buffered), returns None
        result2 = self.buf.process_line("| B |")
        assert result2 is None

    def test_reset_clears_all_state(self):
        self.buf.process_line("pending")
        self.buf._in_blockquote = True
        self.buf._table_buf.append("| x |")
        self.buf._emit_next = "something"
        self.buf.reset()
        assert self.buf._pending is None
        assert self.buf._in_blockquote is False
        assert self.buf._table_buf == []
        assert self.buf._emit_next is None

    def test_setext_marker_as_emit_next_via_flush(self):
        """Deferred line stored in _emit_next is a setext marker: flush renders heading."""
        # Turn 1: "Title" → pending
        assert self.buf.process_line("Title") is None
        # Turn 2: ">" line arrives while pending → returns "Title", stores ">" in _emit_next
        result = self.buf.process_line("> quote")
        assert result == "Title"
        # flush: _emit_next = "> quote", _pending = None
        flushed = self.buf.flush()
        assert flushed is not None
        assert "▌" in flushed

    def test_pending_flushed_before_table(self):
        """Prose line pending before a table must be emitted before table rows."""
        result = render_stateful_blocks("prose\n| A | B |\n|---|---|\n| x | y |")
        lines = _strip(result).splitlines()
        prose_idx = next(i for i, l in enumerate(lines) if "prose" in l)
        table_idx = next(i for i, l in enumerate(lines) if "x" in l)
        assert prose_idx < table_idx

    def test_ansi_line_in_table_flushes_table(self):
        """An ANSI line mid-table must flush the accumulated rows before emitting the ANSI line."""
        ansi = "\033[32mcode\033[0m"
        text = "| A | B |\n|---|---|\n| x | y |\n" + ansi + "\nnormal"
        result = render_stateful_blocks(text)
        lines = result.splitlines()
        # Table content must appear before the ANSI line
        table_idx = next(i for i, l in enumerate(lines) if "x" in _strip(l))
        ansi_idx = next(i for i, l in enumerate(lines) if ansi in l)
        assert table_idx < ansi_idx
