"""Tests for MSG-DEDUP Sub-fix C: prefix-extension dedup (SPEC-MSG-DEDUP-PFX).

Covers:
  TestSubfixCBasic      (4) — trailing emoji collapse + state
  TestSubfixCBoundaries (4) — leading emoji, long delta, exact repeat, replay
  TestSubfixCGraphemes  (2) — ZWJ + skin-tone counted as 1
  TestSubfixCEdges      (2) — index 0, image span

Total: 12 tests.
"""
from __future__ import annotations

import logging

import pytest
from rich.text import Text
from textual.geometry import Region


# ---------------------------------------------------------------------------
# Helpers (copied from test_msg_dedup.py — intentionally decoupled)
# ---------------------------------------------------------------------------


def _make_inline_log(width: int = 80):
    """Create an InlineProseLog with fixed render width — no Textual app required."""
    from hermes_cli.tui.widgets.prose import InlineProseLog

    class _StubLog(InlineProseLog):
        _test_width: int = width

        @property
        def scrollable_content_region(self):  # type: ignore[override]
            return Region(0, 0, self._test_width, 100)

    widget = _StubLog(markup=False, highlight=False, wrap=True)
    widget._render_width = width
    return widget


def _make_line(text_str: str = "hello"):
    """Build a minimal InlineLine (single TextSpan)."""
    from hermes_cli.tui.inline_prose import TextSpan
    return [TextSpan(text=Text(text_str))]


def _make_image_line(text_str: str = "caption"):
    """Build an InlineLine that contains an ImageSpan."""
    from pathlib import Path
    from hermes_cli.tui.inline_prose import ImageSpan, TextSpan
    img = ImageSpan(image_path=Path("/tmp/fake.png"), cell_width=10, alt_text=text_str)
    text = TextSpan(text=Text(text_str))
    return [img, text]


# ---------------------------------------------------------------------------
# TestSubfixCBasic — 4 tests
# ---------------------------------------------------------------------------


class TestSubfixCBasic:
    def test_trailing_emoji_dedup_collapses_pair(self):
        """Emit base line then prefix-extended line; only 1 slot in _inline_lines."""
        log = _make_inline_log()
        log.write_inline(_make_line("1. Hantavirus on a Cruise Ship"))
        log.write_inline(_make_line("1. Hantavirus on a Cruise Ship \U0001f6f3️"))
        assert len(log._inline_lines) == 1
        plain = log._line_to_plain(log._inline_lines[0])
        assert plain.endswith("\U0001f6f3️")

    def test_trailing_emoji_dedup_paint_plan_replaced(self):
        """After Sub-fix C fires, the paint plan at slot 0 reflects the new line."""
        from hermes_cli.tui.widgets.prose import _PREFIX_EXTEND_MAX_GRAPHEMES  # noqa: F401
        log = _make_inline_log()
        log.write_inline(_make_line("1. Hantavirus on a Cruise Ship"))
        first_plan = log._inline_paint.get(0)
        log.write_inline(_make_line("1. Hantavirus on a Cruise Ship \U0001f6f3️"))
        second_plan = log._inline_paint.get(0)
        # The paint plan must have been updated (rewrite_inline refreshes it).
        assert second_plan is not None
        assert second_plan != first_plan

    def test_trailing_emoji_dedup_logical_count_unchanged(self):
        """Sub-fix C rewrites in place; _logical_count stays at 1 after both emits."""
        log = _make_inline_log()
        log.write_inline(_make_line("1. Hantavirus on a Cruise Ship"))
        assert log._logical_count == 1
        log.write_inline(_make_line("1. Hantavirus on a Cruise Ship \U0001f6f3️"))
        assert log._logical_count == 1

    def test_emit_seen_old_plain_evicted(self):
        """After Sub-fix C fires, the original plain is removed from _inline_emit_seen."""
        log = _make_inline_log()
        base_plain = "1. Hantavirus on a Cruise Ship"
        extended_plain = base_plain + " \U0001f6f3️"
        log.write_inline(_make_line(base_plain))
        log.write_inline(_make_line(extended_plain))
        # Old plain evicted by _rewrite_inline; new plain registered.
        assert base_plain not in log._inline_emit_seen
        assert extended_plain in log._inline_emit_seen


# ---------------------------------------------------------------------------
# TestSubfixCBoundaries — 4 tests
# ---------------------------------------------------------------------------


class TestSubfixCBoundaries:
    def test_continuation_paragraph_not_collapsed(self):
        """Long suffix (>6 graphemes of regular prose) → two distinct rows."""
        log = _make_inline_log()
        log.write_inline(_make_line("foo"))
        log.write_inline(_make_line("foo bar baz qux quux corge grault"))
        assert len(log._inline_lines) == 2

    def test_leading_emoji_change_not_collapsed(self):
        """New line prepends emoji — not a startswith match — both rows kept."""
        log = _make_inline_log()
        log.write_inline(_make_line("THE NEWS…"))
        log.write_inline(_make_line("\U0001f4fa THE NEWS…"))
        assert len(log._inline_lines) == 2

    def test_exact_repeat_still_handled_by_subfix_b(self, caplog):
        """Exact duplicate fires Sub-fix B (warning logged), not Sub-fix C."""
        log = _make_inline_log()
        log.write_inline(_make_line("same plain text"))
        with caplog.at_level(logging.WARNING, logger="hermes_cli.tui.widgets.prose"):
            log.write_inline(_make_line("same plain text"))
        assert any("duplicate plain text emit" in r.message for r in caplog.records)
        # Only 1 slot (Sub-fix B returned early, Sub-fix C never ran).
        assert len(log._inline_lines) == 1

    def test_replay_skips_subfix_c(self):
        """When _replaying is True, Sub-fix C guard fires False → both emits stored."""
        log = _make_inline_log()
        log.write_inline(_make_line("base text"))
        # Force replaying flag for the second emit.
        log._replaying = True
        try:
            log.write_inline(_make_line("base text \U0001f6f3️"))
        finally:
            log._replaying = False
        # Sub-fix C is skipped; second emit is appended normally.
        assert len(log._inline_lines) == 2


# ---------------------------------------------------------------------------
# TestSubfixCGraphemes — 2 tests
# ---------------------------------------------------------------------------


class TestSubfixCGraphemes:
    def test_zwj_emoji_sequence_counts_as_one_grapheme(self):
        """ZWJ family '👨‍👩‍👧' is a single grapheme cluster; space + family = 2 graphemes → rewrite."""
        from hermes_cli.tui.widgets._grapheme import suffix_grapheme_count
        family = "\U0001f468‍\U0001f469‍\U0001f467"
        assert suffix_grapheme_count(family) == 1
        # Integration: " 👨‍👩‍👧" suffix → 2 graphemes ≤ 6, triggers rewrite.
        log = _make_inline_log()
        log.write_inline(_make_line("look at this"))
        log.write_inline(_make_line("look at this " + family))
        assert len(log._inline_lines) == 1

    def test_skin_tone_modifier_counts_as_one(self):
        """'👋🏽' (wave + medium skin-tone) is one grapheme cluster; " 👋🏽" = 2 → rewrite."""
        from hermes_cli.tui.widgets._grapheme import suffix_grapheme_count
        wave_skin = "\U0001f44b\U0001f3fd"
        assert suffix_grapheme_count(wave_skin) == 1
        log = _make_inline_log()
        log.write_inline(_make_line("bruh ok"))
        log.write_inline(_make_line("bruh ok " + wave_skin))
        assert len(log._inline_lines) == 1


# ---------------------------------------------------------------------------
# TestSubfixCEdges — 2 tests
# ---------------------------------------------------------------------------


class TestSubfixCEdges:
    def test_index_zero_no_predecessor(self):
        """First emit at line_index 0: Sub-fix C guard (line_index > 0) is False — no-op."""
        log = _make_inline_log()
        log.write_inline(_make_line("first line only"))
        assert len(log._inline_lines) == 1

    def test_subfix_c_does_not_fire_during_streaming_image_span(self):
        """ImageSpan in previous line blocks Sub-fix C; both rows kept."""
        log = _make_inline_log()
        log.write_inline(_make_image_line("caption text"))
        log.write_inline(_make_line("caption text \U0001f6f3️"))
        assert len(log._inline_lines) == 2
