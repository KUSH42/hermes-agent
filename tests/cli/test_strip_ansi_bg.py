"""Regression tests for cli._strip_ansi_bg.

The function strips background color SGR parameters while preserving
foreground codes. A 2026-05-09 regression: it was treating 2-digit
RGB channel values 40-49 (and 3-digit 100-107) as 8-color bg codes,
truncating 24-bit fg sequences when the blue channel landed in those
ranges. That produced malformed `\\x1b[38;2;R;Gm` codes that terminals
fall back to default foreground for — visible as white braille glyphs
in the ares startup banner whose stops have B=46/32/23.
"""

from __future__ import annotations

from cli import _strip_ansi_bg


class TestForegroundPreservation:
    def test_fg_24bit_with_blue_in_bg_range_46(self):
        # Blue = 46 → must NOT be eaten as 8-color bg
        s = "\x1b[38;2;184;85;46m⣤\x1b[0m"
        assert _strip_ansi_bg(s) == s

    def test_fg_24bit_with_blue_in_bg_range_40(self):
        s = "\x1b[38;2;100;100;40mX\x1b[0m"
        assert _strip_ansi_bg(s) == s

    def test_fg_24bit_with_green_in_bg_range(self):
        # Green = 49 → must NOT be eaten
        s = "\x1b[38;2;200;49;10mX\x1b[0m"
        assert _strip_ansi_bg(s) == s

    def test_fg_24bit_with_red_in_bright_bg_range(self):
        # Red = 105 (would match bright bg 100-107 rule)
        s = "\x1b[38;2;105;50;25mX\x1b[0m"
        assert _strip_ansi_bg(s) == s

    def test_fg_256color_with_n_in_bg_range(self):
        # 38;5;42 — the 42 must not be mistaken for a bg code
        s = "\x1b[38;5;42mX\x1b[0m"
        assert _strip_ansi_bg(s) == s


class TestBackgroundStripping:
    def test_strips_24bit_bg(self):
        assert _strip_ansi_bg("\x1b[48;2;30;30;30mX\x1b[0m") == "X\x1b[0m"

    def test_strips_256color_bg(self):
        assert _strip_ansi_bg("\x1b[48;5;42mX\x1b[0m") == "X\x1b[0m"

    def test_strips_simple_8color_bg(self):
        assert _strip_ansi_bg("\x1b[41mX\x1b[0m") == "X\x1b[0m"

    def test_strips_bright_8color_bg(self):
        assert _strip_ansi_bg("\x1b[101mX\x1b[0m") == "X\x1b[0m"


class TestCombinedFgBg:
    def test_keeps_fg_strips_bg(self):
        # Combined sequence with fg blue=46 + bg
        out = _strip_ansi_bg("\x1b[38;2;180;81;46;48;2;30;30;30mX\x1b[0m")
        assert out == "\x1b[38;2;180;81;46mX\x1b[0m"

    def test_keeps_fg_strips_bg_when_fg_first(self):
        out = _strip_ansi_bg("\x1b[38;2;100;200;42;48;2;0;0;0mX\x1b[0m")
        assert out == "\x1b[38;2;100;200;42mX\x1b[0m"

    def test_keeps_fg_strips_bg_when_bg_first(self):
        out = _strip_ansi_bg("\x1b[48;2;0;0;0;38;2;100;200;42mX\x1b[0m")
        assert out == "\x1b[38;2;100;200;42mX\x1b[0m"
