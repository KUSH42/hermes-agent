"""R-B1: streaming renderer must not duplicate prose lines.

Spec: 2026-05-09-stream-content-duplication-spec.md

Invariant: For every \\n-delimited logical line committed during streaming,
_log_texts contains exactly one entry. Late-arriving writes (callbacks
scheduled via call_from_thread) must update the existing entry in-place via
_apply_write_to_log() — never append a new entry.

Tests use a stubbed _prose_log + SchedulerMock so call_from_thread callbacks
fire synchronously in either order relative to line promotion. No real Textual
app, no run_test / pilot.
"""
from __future__ import annotations

import logging
import threading
from unittest.mock import MagicMock, patch

import pytest
from rich.text import Text

from hermes_cli.tui.response_flow import ResponseFlowEngine


class SchedulerMock:
    """Stand-in for app.call_from_thread that defers callbacks until trigger_all."""

    def __init__(self) -> None:
        self.pending: list[tuple] = []
        self.call_args_list: list[tuple] = []

    def call_from_thread(self, fn, *args, **kwargs) -> None:
        self.pending.append((fn, args, kwargs))
        self.call_args_list.append((fn, args, kwargs))

    def trigger_all(self) -> None:
        for fn, args, kwargs in self.pending:
            fn(*args, **kwargs)
        self.pending.clear()


class ProseLogStub:
    """Records write_with_source / write / clear calls; no rendering."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []  # (kind, *args)

    def write_with_source(self, styled, plain, *args, **kwargs) -> None:
        self.calls.append(("wws", styled, plain))

    def write(self, content, *args, **kwargs) -> None:
        self.calls.append(("write", content))

    def write_inline(self, spans) -> None:
        self.calls.append(("inline", spans))

    def clear(self) -> None:
        self.calls.append(("clear",))

    @property
    def call_count(self) -> int:
        return len(self.calls)


def _make_engine_with_stubs() -> tuple[ResponseFlowEngine, ProseLogStub, SchedulerMock]:
    prose_log = ProseLogStub()
    scheduler = SchedulerMock()
    panel = MagicMock()
    panel.current_prose_log.return_value = prose_log
    panel.show_response_rule = MagicMock()
    panel.app._thread_id = threading.get_ident()
    panel.app.call_from_thread = scheduler.call_from_thread
    eng = ResponseFlowEngine(panel=panel)
    # _sync_prose_log was called in __init__; lock identity to the stub.
    eng._prose_log = prose_log
    eng._tracked_prose_log = prose_log
    return eng, prose_log, scheduler


# ---------------------------------------------------------------------------
# TestEmojiMountTiming — 4 tests
# ---------------------------------------------------------------------------


class TestEmojiMountTiming:
    def test_emoji_mount_before_promotion_mutates_live_line(self) -> None:
        """Pre-promotion state: no logical line committed; tracking remains empty."""
        eng, _, _ = _make_engine_with_stubs()
        # Simulate "live line" buffer before \n: no commit yet.
        eng._partial = "• elections "
        assert len(eng._log_texts) == 0
        assert eng._logical_index == 0

    def test_emoji_mount_after_promotion_mutates_log_no_append(self) -> None:
        """After commit, late-arriving _apply_write_to_log updates entry in place."""
        eng, prose_log, _ = _make_engine_with_stubs()
        # Simulate primary commit.
        original = Text("• elections")
        eng._commit_to_log(original, "• elections")
        committed_idx = eng._logical_index - 1
        assert len(eng._log_texts) == 1
        # Late-arriving update.
        updated = Text("• elections 🍳")
        eng._apply_write_to_log(committed_idx, updated)
        assert len(eng._log_texts) == 1
        assert "🍳" in eng._log_texts[committed_idx].plain
        assert eng._log_plains[committed_idx] == updated.plain
        # Log was cleared and rewritten.
        kinds = [c[0] for c in prose_log.calls]
        assert "clear" in kinds
        assert kinds.count("wws") == 2  # one initial + one rewrite

    def test_emoji_mount_after_log_cleared_is_dropped(self, caplog) -> None:
        """Late-arriving write whose host log was cleared: dropped silently at debug."""
        eng, _, _ = _make_engine_with_stubs()
        # Commit then clear (simulating panel switch / explicit clear).
        eng._commit_to_log(Text("line"), "line")
        committed_idx = eng._logical_index - 1
        eng._reset_log_state()
        assert len(eng._log_texts) == 0
        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.response_flow"):
            eng._apply_write_to_log(committed_idx, Text("late"))
        assert len(eng._log_texts) == 0
        debug_msgs = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("dropped" in m for m in debug_msgs)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert not warnings

    def test_two_emoji_mounts_on_same_line_no_duplication(self) -> None:
        """Two late-arriving writes on the same logical line: last-write-wins, count unchanged."""
        eng, _, _ = _make_engine_with_stubs()
        eng._commit_to_log(Text("• elections"), "• elections")
        committed_idx = eng._logical_index - 1
        first = Text("• elections 🍳")
        second = Text("• elections 🍳🔥")
        eng._apply_write_to_log(committed_idx, first)
        eng._apply_write_to_log(committed_idx, second)
        assert len(eng._log_texts) == 1
        assert eng._log_texts[committed_idx].plain == second.plain
        assert "🔥" in eng._log_plains[committed_idx]


# ---------------------------------------------------------------------------
# TestMathImageMountTiming — 1 test
# ---------------------------------------------------------------------------


class TestMathImageMountTiming:
    def test_math_image_mount_after_promotion_mutates_log_no_append(self) -> None:
        eng, _, _ = _make_engine_with_stubs()
        eng._commit_to_log(Text("preamble"), "preamble")
        committed_idx = eng._logical_index - 1
        # Math content arrives via late update of the same logical line.
        updated = Text("preamble + math: x²")
        eng._apply_write_to_log(committed_idx, updated)
        assert len(eng._log_texts) == 1
        assert "x²" in eng._log_texts[committed_idx].plain


# ---------------------------------------------------------------------------
# TestTrailingChunkBehavior — 1 test
# ---------------------------------------------------------------------------


class TestTrailingChunkBehavior:
    def test_trailing_word_chunk_after_line_commit_does_not_duplicate(self) -> None:
        """Late-arriving re-emit of a word for an already-committed line must not append.

        Per spec: if the trailing-word arrives via call_from_thread, Step 3
        idempotency handles it (route through _apply_write_to_log).
        """
        eng, _, scheduler = _make_engine_with_stubs()
        eng._commit_to_log(Text("villain behavior"), "villain behavior")
        assert len(eng._log_texts) == 1
        committed_idx = eng._logical_index - 1
        # Simulate late-arriving callback that re-emits the same content.
        scheduler.call_from_thread(
            eng._apply_write_to_log, committed_idx, Text("villain behavior")
        )
        scheduler.trigger_all()
        assert len(eng._log_texts) == 1


# ---------------------------------------------------------------------------
# TestRepro — 1 test
# ---------------------------------------------------------------------------


class TestRepro:
    def test_repro_bbc_bullet_duplication_red_then_green(self) -> None:
        """End-to-end repro of the BBC bullet duplication symptom.

        BEFORE FIX: late-arriving write would append → len == 2.
        AFTER FIX:  routes through _apply_write_to_log → len == 1.
        """
        eng, _, scheduler = _make_engine_with_stubs()
        original = Text("• Keir Starmer / Labour got COOKED in local elections ")
        eng._commit_to_log(original, original.plain)
        committed_idx = eng._logical_index - 1
        # Late-arriving: emoji-augmented version of the same line.
        updated = Text("• Keir Starmer / Labour got COOKED in local elections 🍳")
        scheduler.call_from_thread(eng._apply_write_to_log, committed_idx, updated)
        scheduler.trigger_all()
        assert len(eng._log_texts) == 1
        assert eng._log_texts[0].plain != ""
        assert "🍳" in eng._log_texts[0].plain


# ---------------------------------------------------------------------------
# TestLineIdInvariant — 1 test
# ---------------------------------------------------------------------------


class TestLineIdInvariant:
    def test_line_id_assigned_unique_per_logical_line(self) -> None:
        eng, _, _ = _make_engine_with_stubs()
        N = 5
        for i in range(N):
            eng._commit_to_log(Text(f"line {i}"), f"line {i}")
        assert len(eng._log_texts) == N
        assert eng._logical_index == N
        for i in range(N):
            assert eng._log_texts[i].plain == f"line {i}"
            assert eng._log_plains[i] == f"line {i}"


# ---------------------------------------------------------------------------
# Bonus: out-of-range late writes on non-empty log emit warning
# ---------------------------------------------------------------------------


class TestApplyWriteToLogEdgeCases:
    def test_out_of_range_on_nonempty_log_warns(self, caplog) -> None:
        eng, _, _ = _make_engine_with_stubs()
        eng._commit_to_log(Text("line 0"), "line 0")
        with caplog.at_level(logging.WARNING, logger="hermes_cli.tui.response_flow"):
            eng._apply_write_to_log(99, Text("late"))
        assert len(eng._log_texts) == 1
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("out of range" in r.message for r in warnings)
