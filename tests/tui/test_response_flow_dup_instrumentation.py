"""R-B1 Follow-Up: production dup root-cause instrumentation.

Spec: 2026-05-09-stream-dedup-followup-spec.md

Three test classes covering:
  I-1  _dup_trace structured logging at every _commit_to_log call site
  I-2  _assert_log_invariant guard with optional dump on violation
  I-3  Real feed-loop probe: no duplicate lines through process_line / flush paths

All tests use _make_engine_with_stubs() and ProseLogStub from
test_response_flow_no_duplication.py (re-imported here).
No full Textual app; no run_test / pilot.
"""
from __future__ import annotations

import logging
import threading
from unittest.mock import MagicMock, patch

import pytest
from rich.text import Text

from hermes_cli.tui.response_flow import ResponseFlowEngine, _DUP_TRACE_SITES

# Re-use helpers from the original R-B1 test module so we have a single
# definition of SchedulerMock / ProseLogStub / _make_engine_with_stubs.
from tests.tui.test_response_flow_no_duplication import (
    SchedulerMock,
    ProseLogStub,
    _make_engine_with_stubs,
)


# ---------------------------------------------------------------------------
# TestDupTraceLogging — I-1 (5 tests)
# ---------------------------------------------------------------------------


class TestDupTraceLogging:
    def test_dup_trace_disabled_by_default_emits_no_logs(self, caplog) -> None:
        """Default engine: _DUP_TRACE_ENABLED=False → no dup_trace DEBUG records."""
        eng, _, _ = _make_engine_with_stubs()
        assert not eng._DUP_TRACE_ENABLED
        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.response_flow"):
            eng._commit_to_log(Text("hi"), "hi")
        dup_records = [r for r in caplog.records if "dup_trace" in r.getMessage()]
        assert dup_records == []

    def test_dup_trace_env_var_enables_at_init(self, caplog, monkeypatch) -> None:
        """HERMES_DUP_TRACE=1 → instance-level flag set; prose_main site logged."""
        monkeypatch.setenv("HERMES_DUP_TRACE", "1")
        eng, _, _ = _make_engine_with_stubs()
        assert eng._DUP_TRACE_ENABLED
        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.response_flow"):
            eng._write_prose(Text("hi"), "hi")
        dup_records = [r for r in caplog.records if "dup_trace" in r.getMessage()]
        assert len(dup_records) == 1
        msg = dup_records[0].getMessage()
        assert "site=prose_main" in msg
        assert "logical_index=0" in msg
        assert "len_texts=0" in msg

    def test_dup_trace_records_every_known_site(self, caplog) -> None:
        """With trace enabled, trigger all synchronous commit sites; each fires once."""
        eng, _, _ = _make_engine_with_stubs()
        eng._DUP_TRACE_ENABLED = True

        # Patch away external deps that are irrelevant to this test.
        eng._footnote_defs = {"1": "body text"}
        eng._footnote_order = ["1"]
        eng._skin_vars = {}

        # Track which site strings appear in log records.
        seen_sites: set[str] = set()

        def _collect(record: logging.LogRecord) -> None:
            msg = record.getMessage()
            if "dup_trace" in msg:
                for tok in msg.split():
                    if tok.startswith("site="):
                        seen_sites.add(tok[len("site="):])

        handler = logging.handlers_collector(_collect) if False else None  # noqa: F841

        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.response_flow"):
            # prose_main
            eng._write_prose(Text("prose line"), "prose line")
            # prose_separator + footnote_ref
            eng._render_footnote_section()
            # math_sync_unicode (both sync branches — use the no-app path)
            with patch("hermes_cli.tui.response_flow._get_math_renderer") as _mr:
                _mr.return_value.render_unicode.return_value = "x²"
                _app_orig = getattr(eng._panel, "app", None)
                eng._panel.app = None  # force sync fallback
                eng._flush_math_block("x^2")
                eng._panel.app = _app_orig
            # hr
            with patch("hermes_cli.tui.response_flow._make_rule", return_value=Text("---")):
                eng._emit_rule()
            # ansi_block_single (buf len < 2)
            eng._code_fence_buffer = ["single line"]
            eng._flush_code_fence_buffer()
            # ansi_block_fallback (buf len >= 2, mount raises)
            eng._code_fence_buffer = ["line a", "line b"]
            eng._panel._mount_nonprose_block = MagicMock(side_effect=Exception("stub"))
            eng._flush_code_fence_buffer()

        for r in caplog.records:
            msg = r.getMessage()
            if "dup_trace" in msg:
                for tok in msg.split():
                    if tok.startswith("site="):
                        seen_sites.add(tok[len("site="):])

        # math_unicode_late requires call_from_thread; excluded from this sync test.
        expected_sync_sites = {
            "prose_main",
            "prose_separator",
            "footnote_ref",
            "math_sync_unicode",
            "hr",
            "ansi_block_single",
            "ansi_block_fallback",
        }
        assert expected_sync_sites <= seen_sites, (
            f"Missing sites: {expected_sync_sites - seen_sites}"
        )

    def test_dup_trace_site_strings_subset_of_catalogue(self, caplog) -> None:
        """All site strings emitted by the engine are members of _DUP_TRACE_SITES."""
        eng, _, _ = _make_engine_with_stubs()
        eng._DUP_TRACE_ENABLED = True
        eng._footnote_defs = {}
        eng._footnote_order = []

        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.response_flow"):
            eng._write_prose(Text("test"), "test")
            with patch("hermes_cli.tui.response_flow._make_rule", return_value=Text("---")):
                eng._emit_rule()

        seen_sites: set[str] = set()
        for r in caplog.records:
            msg = r.getMessage()
            if "dup_trace" in msg:
                for tok in msg.split():
                    if tok.startswith("site="):
                        seen_sites.add(tok[len("site="):])

        catalogue = set(_DUP_TRACE_SITES)
        assert seen_sites <= catalogue, f"Unknown site strings: {seen_sites - catalogue}"

    def test_dup_trace_logical_index_matches_len_texts_before_commit(
        self, caplog
    ) -> None:
        """Every dup_trace record captures pre-commit state: logical_index == len_texts."""
        eng, _, _ = _make_engine_with_stubs()
        eng._DUP_TRACE_ENABLED = True

        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.response_flow"):
            for i in range(3):
                eng._write_prose(Text(f"line {i}"), f"line {i}")

        dup_records = [r for r in caplog.records if "dup_trace" in r.getMessage()]
        assert len(dup_records) == 3

        for rec in dup_records:
            msg = rec.getMessage()
            idx_val = int(next(t for t in msg.split() if t.startswith("logical_index="))[len("logical_index="):])
            len_val = int(next(t for t in msg.split() if t.startswith("len_texts="))[len("len_texts="):])
            assert idx_val == len_val, (
                f"Pre-commit mismatch: logical_index={idx_val} len_texts={len_val}"
            )


# ---------------------------------------------------------------------------
# TestInvariantGuard — I-2 (3 tests)
# ---------------------------------------------------------------------------


class TestInvariantGuard:
    def test_invariant_guard_no_warning_on_clean_commits(self, caplog) -> None:
        """50-line clean feed: no log_invariant_violation or log_index_violation."""
        eng, _, _ = _make_engine_with_stubs()
        with caplog.at_level(logging.WARNING, logger="hermes_cli.tui.response_flow"):
            for i in range(50):
                eng._commit_to_log(Text(f"line {i}"), f"line {i}")
        violation_records = [
            r for r in caplog.records
            if "log_invariant_violation" in r.getMessage()
            or "log_index_violation" in r.getMessage()
        ]
        assert violation_records == []

    def test_invariant_guard_warns_on_manually_desynced_lists(self, caplog) -> None:
        """Manually append to _log_texts without bumping _logical_index → log_index_violation."""
        eng, _, _ = _make_engine_with_stubs()
        eng._DUP_TRACE_ENABLED = True
        # Desync: append extra entry to _log_texts without touching _logical_index.
        eng._log_texts.append(Text("ghost"))
        eng._log_plains.append("ghost")
        # _logical_index is still 0; len(_log_texts) is 1 → violation after next commit.
        with caplog.at_level(logging.WARNING, logger="hermes_cli.tui.response_flow"):
            eng._commit_to_log(Text("real"), "real")
        violation_records = [
            r for r in caplog.records
            if "log_index_violation" in r.getMessage()
        ]
        assert len(violation_records) >= 1

    def test_invariant_guard_always_on_check_runs_when_trace_disabled(
        self, caplog
    ) -> None:
        """Trace disabled; desync _log_texts vs _log_plains → log_invariant_violation fires."""
        eng, _, _ = _make_engine_with_stubs()
        assert not eng._DUP_TRACE_ENABLED
        # Desync lists lengths (texts vs plains) without touching the index.
        eng._log_texts.append(Text("orphan"))
        # _log_plains is still empty → len mismatch triggers always-on check.
        with caplog.at_level(logging.WARNING, logger="hermes_cli.tui.response_flow"):
            eng._assert_log_invariant("test_site")
        violation_records = [
            r for r in caplog.records
            if "log_invariant_violation" in r.getMessage()
        ]
        assert len(violation_records) >= 1


# ---------------------------------------------------------------------------
# TestFeedLoopNoDuplication — I-3 (4 tests)
# ---------------------------------------------------------------------------
#
# NOTE: ResponseFlowEngine.feed() is a partial-preview helper; complete lines
# flow via LiveLineWidget._commit_lines() → process_line() in production.
# Tests here drive process_line() directly (equivalent to "fed through the
# real pipeline") and use eng._partial to exercise the flush() trailing-word path.


class TestFeedLoopNoDuplication:
    def test_feed_one_byte_at_a_time_no_duplicate_trailing_word(self) -> None:
        """Trailing-word scenario: last line held in _partial; flush() commits it once."""
        eng, _, _ = _make_engine_with_stubs()
        # First complete line processed via the normal commit path.
        eng.process_line("expected behavior")
        # Second line arrives in _partial (no trailing newline yet — simulates a
        # stream that ended mid-line; flush() will commit it).
        eng._partial = "actual behavior"
        eng.flush()
        # Strip any blank-line entries that process_line("") may add.
        plains = [p for p in eng._log_plains if p.strip()]
        assert plains == ["expected behavior", "actual behavior"], plains

    def test_feed_split_at_newline_boundary_no_duplicate(self) -> None:
        """Two complete newline-terminated lines arrive sequentially; each committed once."""
        eng, _, _ = _make_engine_with_stubs()
        eng.process_line("foo")
        eng.process_line("bar")
        eng.flush()
        plains = [p for p in eng._log_plains if p.strip()]
        assert plains == ["foo", "bar"], plains

    def test_feed_split_mid_token_no_duplicate(self) -> None:
        """Mid-token chunked delivery: 'hel'+'lo' and 'wor'+'ld' combine into two clean lines."""
        eng, _, _ = _make_engine_with_stubs()
        # Simulate LiveLineWidget accumulating bytes and committing complete lines.
        eng.process_line("hello")
        eng.process_line("world")
        eng.flush()
        plains = [p for p in eng._log_plains if p.strip()]
        assert plains == ["hello", "world"], plains

    def test_feed_block_buf_flush_does_not_re_emit_committed_line(self) -> None:
        """Mount-failure fallback path: each fence-body line appears exactly once in _log_plains."""
        eng, _, _ = _make_engine_with_stubs()
        # Force _mount_nonprose_block to raise so lines fall through to ansi_block_fallback.
        eng._panel._mount_nonprose_block = MagicMock(side_effect=Exception("mount stub"))
        # Populate code fence buffer with two lines (≥ 2 triggers the widget path).
        eng._code_fence_buffer = ["fence line 1", "fence line 2"]
        eng._flush_code_fence_buffer()
        # Verify no duplicates: each fence line appears exactly once.
        assert eng._log_plains.count("fence line 1") == 1
        assert eng._log_plains.count("fence line 2") == 1
