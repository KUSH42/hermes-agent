"""Tests for TWEMO spec: emoji-prefixed line wrap geometry fix.

TWEMO-1: cell_len() replaces len() in _apply_cont_indent / _apply_cont_indent_ansi.
TWEMO-2: _detect_list_cont_indent recognises wide-cell emoji bullets.
"""
from __future__ import annotations

import pathlib
import pytest

from hermes_cli.tui.response_flow import (
    _apply_cont_indent,
    _apply_cont_indent_ansi,
    _detect_list_cont_indent,
)

_FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures" / "response_flow_emoji_wrap"


# ---------------------------------------------------------------------------
# TestCellLenPrewrap — TWEMO-1 (4 tests)
# ---------------------------------------------------------------------------

class TestCellLenPrewrap:
    @pytest.mark.parametrize("emoji", ["🤓", "🥲", "🌎", "🐍"])
    def test_wide_emoji_word_counted_as_two_cells(self, emoji: str) -> None:
        # 🤓 (2 cells) + space + 58 x's = 61 visual cells at width 60.
        # cell_len() = 61 > 60 → pre-wrap fires; result has two lines.
        line = f"{emoji} " + "x" * 58
        indent = "   "
        result = _apply_cont_indent_ansi(line, indent, width=60)
        lines = result.split("\n")
        assert len(lines) == 2, f"Expected 2 lines, got {len(lines)}: {lines!r}"
        assert lines[1].startswith(indent), f"Continuation must start with indent: {lines[1]!r}"

    def test_ansi_emoji_word_width_correct(self) -> None:
        # ANSI escape around the emoji must not confuse cell_len after _strip_ansi.
        ansi_emoji = "\x1b[1m🤓\x1b[0m"
        line = f"{ansi_emoji} " + "x" * 58
        indent = "   "
        result = _apply_cont_indent_ansi(line, indent, width=60)
        lines = result.split("\n")
        assert len(lines) == 2
        assert lines[1].startswith(indent)

    def test_plain_wrap_unchanged_for_ascii(self) -> None:
        # ASCII-only line shorter than width — must pass through unchanged.
        line = "- hello world"
        indent = "  "
        result = _apply_cont_indent_ansi(line, indent, width=60)
        assert result == line

    def test_list_item_emoji_bullet_indent_cell_aligned(self) -> None:
        # "- 🤓 " + 56 x's: cell_len = 2(bullet+spc) + 2(🤓) + 1(spc) + 56 = 61 > 60.
        # _MD_UL_RE matches, so indent="  " (2 spaces from bullet).
        # cell_len triggers wrap; continuation uses 2-space indent.
        line = "- 🤓 " + "x" * 56
        indent = "  "
        result = _apply_cont_indent_ansi(line, indent, width=60)
        lines = result.split("\n")
        assert len(lines) >= 2, f"Expected wrap, got: {result!r}"
        assert lines[1].startswith(indent)


# ---------------------------------------------------------------------------
# TestEmojiListDetection — TWEMO-2 (2 tests)
# ---------------------------------------------------------------------------

class TestEmojiListDetection:
    def test_detect_emoji_bullet_returns_indent(self) -> None:
        # cell_len("🤓")=2 > len("🤓")=1 → detected as emoji bullet.
        # indent = " " * (2 + 1) = "   " (3 spaces).
        result = _detect_list_cont_indent("🤓 content here")
        assert result == "   ", f"Expected 3-space indent, got {result!r}"

    def test_detect_non_emoji_short_prefix_no_indent(self) -> None:
        # "hi" is ASCII: cell_len("hi")==len("hi")==2 → NOT an emoji bullet.
        result = _detect_list_cont_indent("hi content here")
        assert result == "", f"Expected empty indent for ASCII prefix, got {result!r}"


# ---------------------------------------------------------------------------
# TestAuditFixture — golden file (1 test)
# ---------------------------------------------------------------------------

class TestAuditFixture:
    def test_audit_2026_05_09_screenshot_fixture(self) -> None:
        # Screenshot S1 line: emoji bullet causes wrong wrap geometry pre-fix.
        # Width=30 produces the same break point visible in the screenshot.
        line = "🤓 aight bet let me peek at the current state of our collective dumpster fire"
        indent = _detect_list_cont_indent(line)
        assert indent == "   ", f"Indent detection failed: {indent!r}"
        result = _apply_cont_indent_ansi(line, indent, width=30)
        expected = (_FIXTURE_DIR / "audit_2026_05_09.txt").read_text().rstrip("\n")
        assert result == expected, f"\nGot:\n{result}\n\nExpected:\n{expected}"
