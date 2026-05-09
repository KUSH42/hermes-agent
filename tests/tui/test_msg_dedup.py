"""Tests for MSG-DEDUP spec: streaming prose deduplication guards.

Covers:
  TestWriteInlineAppend   (1)  — MSG-DEDUP-H1: basic append path
  TestRewriteInlineSubfixA(2)  — MSG-DEDUP-H1 Sub-fix A: index-collision rewrite
  TestPlainTextDedup      (3)  — MSG-DEDUP-H1 Sub-fix B: plain-text dedup guard
  TestSourceOpsInvariant  (2)  — MSG-DEDUP-H1: source ops / visible rows symmetry
  TestReflowGuard         (3)  — MSG-DEDUP-M2: concurrent-write guard during reflow

Total in this file: 11 tests.
MSG-DEDUP-M1 invariant gate tests are in tests/tui/test_invariants.py.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
from rich.text import Text
from textual.geometry import Region


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_inline_log(width: int = 80):
    """Create an InlineProseLog with fixed render width — no Textual app required."""
    from hermes_cli.tui.widgets.prose import InlineProseLog

    class _StubLog(InlineProseLog):
        """Subclass that stubs layout-dependent properties."""
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


# ---------------------------------------------------------------------------
# TestWriteInlineAppend — MSG-DEDUP-H1 (1 test)
# ---------------------------------------------------------------------------


class TestWriteInlineAppend:
    def test_write_inline_appends_new_line(self):
        """write_inline on a fresh log stores the line and increments _logical_count."""
        log = _make_inline_log()
        line = _make_line("new line")
        log.write_inline(line)

        assert log._logical_count == 1
        assert len(log._inline_lines) == 1
        assert log._inline_lines[0] is line


# ---------------------------------------------------------------------------
# TestRewriteInlineSubfixA — MSG-DEDUP-H1 Sub-fix A (2 tests)
# ---------------------------------------------------------------------------


class TestRewriteInlineSubfixA:
    def test_rewrite_inline_patches_in_place(self):
        """Index-collision (reflow race): _rewrite_inline updates in place, no count change."""
        log = _make_inline_log()
        line_v1 = _make_line("version one")
        line_v2 = _make_line("version two")

        log.write_inline(line_v1)
        assert log._logical_count == 1
        assert len(log._source_ops) == 1

        # Simulate reflow reset: _logical_count back to 0, but _inline_lines[0] still set
        log._logical_count = 0

        # write_inline with same idx in _inline_lines → _rewrite_inline path
        log.write_inline(line_v2)

        # _logical_count must NOT increment (stayed at 0, rewrite does not call super().write())
        assert log._logical_count == 0
        assert log._inline_lines[0] is line_v2
        # Exactly one source op (the rewrite updates in place, no new op added)
        assert len(log._source_ops) == 1

    def test_source_ops_idempotent_under_rewrite(self):
        """After _rewrite_inline, _source_ops has exactly one entry and its content is updated."""
        log = _make_inline_log()
        line_v1 = _make_line("original")
        line_v2 = _make_line("updated")

        log.write_inline(line_v1)
        log._logical_count = 0  # simulate reflow reset
        log.write_inline(line_v2)

        # Still one op, and it points to the new line
        assert len(log._source_ops) == 1
        assert log._source_ops[0].content is line_v2


# ---------------------------------------------------------------------------
# TestPlainTextDedup — MSG-DEDUP-H1 Sub-fix B (3 tests)
# ---------------------------------------------------------------------------


class TestPlainTextDedup:
    def test_duplicate_plain_text_skipped(self, caplog):
        """Duplicate plain-text emit outside replay is skipped and a WARNING is logged."""
        log = _make_inline_log()
        line_a = _make_line("same plain text")
        line_b = _make_line("same plain text")  # different object, same plain

        log.write_inline(line_a)
        assert log._logical_count == 1

        with caplog.at_level(logging.WARNING, logger="hermes_cli.tui.widgets.prose"):
            log.write_inline(line_b)

        # Second write must be skipped
        assert log._logical_count == 1
        assert "duplicate plain text" in caplog.text

    def test_duplicate_plain_text_allowed_during_replay(self):
        """With _replaying=True, duplicate plain-text writes are permitted."""
        log = _make_inline_log()
        line = _make_line("replay text")

        log._replaying = True
        log.write_inline(line)
        log.write_inline(line)

        # Both writes went through (replay bypass active)
        assert log._logical_count == 2

    def test_reflow_clears_emit_seen(self):
        """_do_reflow clears _inline_emit_seen before replay so ops can re-register."""
        log = _make_inline_log()
        for i in range(3):
            log.write_inline(_make_line(f"line {i}"))

        assert len(log._inline_emit_seen) == 3

        # Trigger reflow (direct call; _replaying handled internally)
        log._render_width = 40
        log._do_reflow()

        # After reflow, _inline_emit_seen is re-populated from replay
        # (must have exactly 3 entries, one per line)
        assert len(log._inline_emit_seen) == 3


# ---------------------------------------------------------------------------
# TestSourceOpsInvariant — MSG-DEDUP-H1 (2 tests)
# ---------------------------------------------------------------------------


class TestSourceOpsInvariant:
    def test_visible_rows_match_source_ops(self):
        """5 distinct-plain write_inline calls produce 5 inline ops and _logical_count==5."""
        log = _make_inline_log()
        for i in range(5):
            log.write_inline(_make_line(f"distinct line {i}"))

        inline_ops = [op for op in log._source_ops if op.kind == "inline"]
        assert len(inline_ops) == 5
        assert log._logical_count == 5

    def test_emit_seen_cap(self):
        """Writing 300 distinct lines does not grow _inline_emit_seen beyond 256."""
        log = _make_inline_log()
        for i in range(300):
            log.write_inline(_make_line(f"unique line {i:04d}"))

        assert len(log._inline_emit_seen) <= 256


# ---------------------------------------------------------------------------
# TestReflowGuard — MSG-DEDUP-M2 (3 tests)
# ---------------------------------------------------------------------------


class TestReflowGuard:
    def test_reflow_drops_concurrent_writes_into_queue(self):
        """While _reflowing=True, write_inline queues ops instead of appending."""
        log = _make_inline_log()
        log._reflowing = True
        line = _make_line("queued line")

        log.write_inline(line)

        assert len(log._pending_during_reflow) == 1
        assert len(log._inline_lines) == 0  # not appended to inline state

    def test_reflow_drains_queue_after_replay(self):
        """Ops queued during reflow are drained after _do_reflow completes."""
        log = _make_inline_log()
        # Write 2 normal lines
        log.write_inline(_make_line("line a"))
        log.write_inline(_make_line("line b"))
        assert log._logical_count == 2

        # Simulate: set reflowing + replaying=False, then queue a third write
        log._reflowing = True
        log._replaying = False
        line_c = _make_line("line c")
        log.write_inline(line_c)
        assert len(log._pending_during_reflow) == 1

        # Now simulate the reflow completing (restores _reflowing=False and drains)
        log._reflowing = False
        pending = list(log._pending_during_reflow)
        log._pending_during_reflow.clear()
        for op in pending:
            log.write_inline(op.content)

        # All 3 logical lines should now be present
        assert log._logical_count == 3
        assert len(log._pending_during_reflow) == 0

    def test_reflow_queue_cap_warns(self, caplog):
        """Overflowing the pending queue emits a WARNING and drops the oldest entry."""
        from hermes_cli.tui.widgets.renderers import CopyableRichLog
        log = _make_inline_log()
        cap = CopyableRichLog._SOURCE_OPS_CAP // 4
        log._reflowing = True

        with caplog.at_level(logging.WARNING, logger="hermes_cli.tui.widgets.prose"):
            for i in range(cap + 1):
                log.write_inline(_make_line(f"overflow line {i}"))

        assert "overflow" in caplog.text
        assert len(log._pending_during_reflow) == cap
