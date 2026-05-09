"""DEDUP-1: Emoji-suffix re-emission dedup.

Spec: 2026-05-09-stream-dedup-emoji-suffix-spec.md

Regression tests for the _last_prose_idx route introduced to prevent
_write_prose_inline_emojis from emitting a new commit entry when the
incoming plain text is just the most-recently committed prose line with
a trailing emoji appended.

All tests use _make_engine_with_stubs() / ProseLogStub from
test_response_flow_no_duplication.py — no full Textual app.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch, call

import pytest
from rich.text import Text

from hermes_cli.tui.response_flow import ResponseFlowEngine
from tests.tui.test_response_flow_no_duplication import (
    ProseLogStub,
    _make_engine_with_stubs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_emoji_engine():
    """Return engine wired with a registry stub that recognises 'snake' and 'sparkles'."""
    eng, prose_log, scheduler = _make_engine_with_stubs()

    registry = MagicMock()

    def _get(name):
        if name in ("snake", "sparkles"):
            entry = MagicMock()
            entry.path = f"/fake/{name}.png"
            entry.cell_width = 2
            entry.cell_height = 1
            return entry
        return None

    registry.get.side_effect = _get
    eng._emoji_registry = registry
    eng._emoji_images_enabled = True

    # Patch image-support check so the emoji path is always taken.
    eng._has_image_support = lambda: True

    # Patch write_inline onto the prose log stub so the inline path works.
    prose_log.write_inline = MagicMock()

    # Patch inline_prose import inside _write_prose_inline_emojis.
    return eng, prose_log, scheduler


# ---------------------------------------------------------------------------
# TestEmojiSuffixDedup — 8 tests
# ---------------------------------------------------------------------------

class TestEmojiSuffixDedup:

    def test_emoji_suffix_routes_through_apply_write(self) -> None:
        """'foo' then 'foo :snake:' → 1 log entry, _apply_write_to_log called."""
        eng, prose_log, _ = _make_emoji_engine()

        with patch("hermes_cli.tui.inline_prose.ImageSpan", MagicMock()), \
             patch("hermes_cli.tui.inline_prose.TextSpan", MagicMock()):
            # First write: plain prose, no emoji.
            eng._write_prose(Text("foo"), "foo")
            assert len(eng._log_texts) == 1
            assert eng._last_prose_idx == 0

            # Second write: emoji-suffix version of the same line.
            with patch.object(eng, "_apply_write_to_log") as mock_apply:
                eng._write_prose_inline_emojis(Text("foo :snake:"), "foo :snake:")

        # apply_write called with the original index; log still has 1 entry.
        mock_apply.assert_called_once_with(0, Text("foo :snake:"))
        assert len(eng._log_texts) == 1

    def test_separator_resets_last_prose_idx(self) -> None:
        """'foo' → separator commit → 'bar :snake:' becomes a fresh commit."""
        eng, prose_log, _ = _make_emoji_engine()

        with patch("hermes_cli.tui.inline_prose.ImageSpan", MagicMock()), \
             patch("hermes_cli.tui.inline_prose.TextSpan", MagicMock()):
            eng._write_prose(Text("foo"), "foo")
            assert eng._last_prose_idx == 0

            # A separator commit via _commit_to_log must clear _last_prose_idx.
            eng._commit_to_log(Text("─" * 40), "─" * 40)
            assert eng._last_prose_idx is None

            # Now an emoji-suffix write for an unrelated line should NOT route
            # through _apply_write_to_log — it becomes a new commit.
            prose_log.write_inline = MagicMock()
            eng._write_prose_inline_emojis(Text("bar :snake:"), "bar :snake:")

        # Log now has 3 entries: foo, separator, bar :snake:
        assert len(eng._log_texts) == 3

    def test_genuinely_new_line_still_commits(self) -> None:
        """'foo' then unrelated 'bar :snake:' → 2 commits, no routing."""
        eng, prose_log, _ = _make_emoji_engine()

        with patch("hermes_cli.tui.inline_prose.ImageSpan", MagicMock()), \
             patch("hermes_cli.tui.inline_prose.TextSpan", MagicMock()):
            eng._write_prose(Text("foo"), "foo")
            prose_log.write_inline = MagicMock()
            eng._write_prose_inline_emojis(Text("bar :snake:"), "bar :snake:")

        assert len(eng._log_texts) == 2
        prose_log.write_inline.assert_called_once()

    def test_dup_trace_records_one_site_per_decoration(self, caplog) -> None:
        """With trace enabled: prose_main fires once; emoji suffix fires _apply_write (no new trace)."""
        eng, prose_log, _ = _make_emoji_engine()
        eng._DUP_TRACE_ENABLED = True

        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.response_flow"), \
             patch("hermes_cli.tui.inline_prose.ImageSpan", MagicMock()), \
             patch("hermes_cli.tui.inline_prose.TextSpan", MagicMock()), \
             patch.object(eng, "_apply_write_to_log") as mock_apply:
            eng._write_prose(Text("foo"), "foo")
            eng._write_prose_inline_emojis(Text("foo :snake:"), "foo :snake:")

        trace_records = [r for r in caplog.records if "dup_trace" in r.getMessage()]
        # Only one dup_trace record (from prose_main) — emoji suffix goes through apply_write.
        assert len(trace_records) == 1
        assert "site=prose_main" in trace_records[0].getMessage()
        mock_apply.assert_called_once()

    def test_screenshot_fixture_replay(self) -> None:
        """Minimum synthetic stream: same line emitted twice (plain + emoji) → 1 log entry."""
        eng, prose_log, _ = _make_emoji_engine()

        with patch("hermes_cli.tui.inline_prose.ImageSpan", MagicMock()), \
             patch("hermes_cli.tui.inline_prose.TextSpan", MagicMock()):
            eng._write_prose(Text("ah that cnn"), "ah that cnn")
            assert len(eng._log_texts) == 1

            with patch.object(eng, "_apply_write_to_log") as mock_apply:
                eng._write_prose_inline_emojis(Text("ah that cnn :snake:"), "ah that cnn :snake:")

        assert len(eng._log_texts) == 1
        mock_apply.assert_called_once_with(0, Text("ah that cnn :snake:"))

    def test_apply_write_preserves_rich_styling(self) -> None:
        """After emoji-suffix update, log entry is replaced with new rich_text."""
        eng, prose_log, _ = _make_emoji_engine()

        bold_text = Text("foo")
        bold_text.stylize("bold")

        with patch("hermes_cli.tui.inline_prose.ImageSpan", MagicMock()), \
             patch("hermes_cli.tui.inline_prose.TextSpan", MagicMock()):
            eng._commit_to_log(bold_text, "foo")
            eng._last_prose_idx = 0

            updated = Text("foo :snake:")
            eng._apply_write_to_log = MagicMock()
            eng._write_prose_inline_emojis(updated, "foo :snake:")

        eng._apply_write_to_log.assert_called_once_with(0, updated)

    def test_reset_log_state_clears_last_idx(self) -> None:
        """_reset_log_state sets _last_prose_idx to None."""
        eng, _, _ = _make_engine_with_stubs()
        eng._last_prose_idx = 3
        eng._reset_log_state()
        assert eng._last_prose_idx is None

    def test_two_decorations_in_a_row(self) -> None:
        """'foo' → 'foo :snake:' → 'foo :snake: :sparkles:' → 1 commit + 2 updates."""
        eng, prose_log, _ = _make_emoji_engine()

        with patch("hermes_cli.tui.inline_prose.ImageSpan", MagicMock()), \
             patch("hermes_cli.tui.inline_prose.TextSpan", MagicMock()):
            eng._write_prose(Text("foo"), "foo")
            assert len(eng._log_texts) == 1

            apply_calls: list = []
            original_apply = eng._apply_write_to_log

            def _tracking_apply(idx, text):
                apply_calls.append((idx, text))
                original_apply(idx, text)

            eng._apply_write_to_log = _tracking_apply

            prose_log.write_inline = MagicMock()
            eng._write_prose_inline_emojis(Text("foo :snake:"), "foo :snake:")
            # After first decoration, _last_prose_idx must still be 0
            # (apply_write doesn't create a new entry).
            assert eng._last_prose_idx == 0
            eng._write_prose_inline_emojis(Text("foo :snake: :sparkles:"), "foo :snake: :sparkles:")

        # Only 1 log entry; apply_write called twice.
        assert len(eng._log_texts) == 1
        assert len(apply_calls) == 2
        assert apply_calls[0][0] == 0
        assert apply_calls[1][0] == 0
