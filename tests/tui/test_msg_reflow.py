"""Tests for SPEC-MSG-REFLOW: CopyableRichLog reflow buffer for viewport narrowing.

Covers:
  TestReflowCore    (8)  — REFLOW-H1: core buffer + reflow in CopyableRichLog
  TestInlineReflow  (5)  — REFLOW-H2: InlineProseLog inline op storage + replay
  TestStreamingWire (4)  — REFLOW-M1: set_streaming wiring
  TestSourceOpsCap  (3)  — REFLOW-M2: _source_ops cap enforcement
  TestReplayGuards  (2)  — REFLOW-L1: no double-append during replay

All tests use direct widget instantiation (no full Textual app).
call_after_refresh is substituted with direct _do_reflow() in synchronous tests.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from rich.text import Text

import pytest

from hermes_cli.tui.widgets.renderers import CopyableRichLog, CopyableBlock, _WriteOp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_log(render_width: int = 80) -> CopyableRichLog:
    """Create a CopyableRichLog with a fixed render width (no Textual app needed)."""
    log = CopyableRichLog(markup=False, highlight=False, wrap=True)
    log._render_width = render_width
    return log


def _fake_resize_event(width: int):
    """Build a minimal resize event mock."""
    from textual.geometry import Size
    ev = MagicMock()
    ev.size = Size(width, 24)
    return ev


# ---------------------------------------------------------------------------
# TestReflowCore — REFLOW-H1
# ---------------------------------------------------------------------------


class TestReflowCore:
    def test_reflow_triggers_on_narrow(self):
        """on_resize with width < rendered max → _do_reflow scheduled."""
        log = _make_log(80)
        log.write(Text("hello world " * 5))
        assert log._rendered_max_width == 80
        assert len(log._source_ops) == 1

        # Simulate narrowing resize; patch call_after_refresh to capture call
        reflow_called = []
        with patch.object(log, "call_after_refresh", side_effect=lambda fn: reflow_called.append(fn)):
            ev = _fake_resize_event(40)
            log.on_resize(ev)

        assert log._render_width == 40
        assert log._reflow_scheduled is True
        assert len(reflow_called) == 1

    def test_reflow_not_triggered_on_widen(self):
        """on_resize with width > rendered max → no reflow."""
        log = _make_log(60)
        log.write(Text("test content"))
        assert log._rendered_max_width == 60

        calls = []
        with patch.object(log, "call_after_refresh", side_effect=lambda fn: calls.append(fn)):
            ev = _fake_resize_event(80)
            log.on_resize(ev)

        assert log._reflow_scheduled is False
        assert calls == []

    def test_reflow_debounced(self):
        """Two narrow resizes in same frame produce a single _do_reflow schedule."""
        log = _make_log(80)
        log.write(Text("content"))

        calls = []
        with patch.object(log, "call_after_refresh", side_effect=lambda fn: calls.append(fn)):
            log.on_resize(_fake_resize_event(60))
            log.on_resize(_fake_resize_event(40))

        # second resize is a no-op because _reflow_scheduled is already True
        assert len(calls) == 1

    def test_reflow_preserves_plain_lines(self):
        """After _do_reflow, _plain_lines is rebuilt from the stored ops."""
        log = _make_log(80)
        log.write(Text("line alpha"))
        log.write(Text("line beta"))
        orig_plain = list(log._plain_lines)

        # Simulate narrowing
        log._render_width = 40
        # Suppress actual call_after_refresh
        log._reflow_scheduled = False
        log._do_reflow()

        assert log._plain_lines == orig_plain

    def test_reflow_preserves_line_links(self):
        """After _do_reflow, _line_links is rebuilt correctly."""
        log = _make_log(80)
        log.write_with_source(Text("styled line"), "styled line", link="https://example.com")
        orig_links = list(log._line_links)

        log._render_width = 40
        log._do_reflow()

        assert log._line_links == orig_links

    def test_reflow_deferred_during_streaming(self):
        """_do_reflow reschedules itself when _streaming_active is True."""
        log = _make_log(80)
        log.write(Text("content"))
        log._streaming_active = True
        log._reflow_scheduled = False  # will be set True inside _do_reflow

        calls = []
        with patch.object(log, "call_after_refresh", side_effect=lambda fn: calls.append(fn)):
            log._do_reflow()

        # should have rescheduled itself
        assert log._reflow_scheduled is True
        assert len(calls) == 1

    def test_set_streaming_false_triggers_pending_reflow(self):
        """set_streaming(False) dispatches a pending reflow immediately."""
        log = _make_log(80)
        log.write(Text("some text"))
        log._reflow_scheduled = True

        calls = []
        with patch.object(log, "call_after_refresh", side_effect=lambda fn: calls.append(fn)):
            log.set_streaming(False)

        assert len(calls) == 1

    def test_rendered_max_width_tracks_widest(self):
        """_rendered_max_width records the widest width seen across writes."""
        log = _make_log(60)
        log.write(Text("at 60"))
        log._render_width = 80
        log.write(Text("at 80"))
        log._render_width = 70
        log.write(Text("at 70"))

        assert log._rendered_max_width == 80


# ---------------------------------------------------------------------------
# TestInlineReflow — REFLOW-H2
# ---------------------------------------------------------------------------


class TestInlineReflow:
    def _make_inline_log(self, width: int = 80):
        from hermes_cli.tui.widgets.prose import InlineProseLog
        from textual.geometry import Region

        class _W(InlineProseLog):
            _test_width: int = width

            @property
            def scrollable_content_region(self):  # type: ignore[override]
                return Region(0, 0, self._test_width, 100)

        widget = _W(markup=False, highlight=False, wrap=True)
        widget._render_width = width
        return widget

    def _make_inline_line(self, text_str: str = "hello inline"):
        from hermes_cli.tui.inline_prose import TextSpan
        return [TextSpan(text=Text(text_str))]

    def test_inline_op_stored(self):
        """write_inline stores exactly one 'inline' op; no 'wws' ops."""
        widget = self._make_inline_log()
        line = self._make_inline_line("test")
        widget.write_inline(line)

        ops = widget._source_ops
        assert len(ops) == 1
        assert ops[0].kind == "inline"
        # No "wws" ops (suppressed by _inline_source_appending guard)
        assert all(op.kind != "wws" for op in ops)

    def test_inline_reflow_rebuilds_inline_lines(self):
        """After reflow, _inline_lines is non-empty (rebuilt from stored ops)."""
        widget = self._make_inline_log(80)
        line = self._make_inline_line("hello world")
        widget.write_inline(line)

        # Simulate narrowing + reflow
        widget._render_width = 20
        widget._do_reflow()

        assert len(widget._inline_lines) > 0

    def test_inline_reflow_no_duplicate_plain_lines(self):
        """After reflow, _plain_lines length matches number of write_inline calls."""
        widget = self._make_inline_log(80)
        widget.write_inline(self._make_inline_line("line one"))
        widget.write_inline(self._make_inline_line("line two"))

        widget._render_width = 20
        widget._do_reflow()

        # One plain line per write_inline call
        assert len(widget._plain_lines) == 2

    def test_inline_reflow_clears_stale_paint(self):
        """_inline_paint from pre-reflow is absent after reflow (rebuilt fresh)."""
        widget = self._make_inline_log(80)
        widget.write_inline(self._make_inline_line("paint me"))
        old_paint_keys = set(widget._inline_paint.keys())
        assert old_paint_keys  # should have exactly {0}

        widget._render_width = 20
        widget._do_reflow()

        # After reflow, _inline_paint keys are 0-based from fresh replay
        # (old keys ≥ 1 would be stale; since we only wrote 1 line, key is always 0)
        assert set(widget._inline_paint.keys()) == {0}

    def test_inline_logical_count_reset(self):
        """After reflow, _logical_count equals the number of write_inline ops replayed."""
        widget = self._make_inline_log(80)
        widget.write_inline(self._make_inline_line("a"))
        widget.write_inline(self._make_inline_line("b"))
        widget.write_inline(self._make_inline_line("c"))
        assert widget._logical_count == 3

        widget._render_width = 20
        widget._do_reflow()

        # All 3 inline ops replayed; logical_count == 3
        assert widget._logical_count == 3


# ---------------------------------------------------------------------------
# TestStreamingWire — REFLOW-M1
# ---------------------------------------------------------------------------


class TestStreamingWire:
    def test_set_streaming_true_blocks_reflow(self):
        """set_streaming(True) sets flag; reflow triggered during streaming is deferred."""
        log = _make_log(80)
        log.write(Text("some content"))
        log.set_streaming(True)
        assert log._streaming_active is True

        # Trigger reflow via narrow resize
        log._reflow_scheduled = False
        calls = []
        with patch.object(log, "call_after_refresh", side_effect=lambda fn: calls.append(fn)):
            log.on_resize(_fake_resize_event(40))
        # Scheduling happened
        assert log._reflow_scheduled is True

        # Calling _do_reflow while streaming → reschedules, does not replay
        rescheduled_calls = []
        with patch.object(log, "call_after_refresh", side_effect=lambda fn: rescheduled_calls.append(fn)):
            log._do_reflow()
        assert log._reflow_scheduled is True
        assert len(rescheduled_calls) == 1

    def test_set_streaming_false_called_at_finalize(self):
        """set_streaming(False) on prose block is called when streaming ends."""
        block = CopyableBlock()
        block._log._render_width = 80
        block._log.write(Text("content"))

        block.set_streaming(True)
        assert block._log._streaming_active is True

        calls = []
        with patch.object(block._log, "call_after_refresh", side_effect=lambda fn: calls.append(fn)):
            block.set_streaming(False)

        assert block._log._streaming_active is False

    def test_reasoning_log_set_streaming(self):
        """ReasoningPanel._reasoning_log.set_streaming called at reasoning start/end."""
        from hermes_cli.tui.widgets.message_panel import ReasoningPanel

        panel = ReasoningPanel()
        log = panel._reasoning_log
        log._render_width = 80

        # set_streaming(True) is called in open_box — we call it manually since
        # open_box requires app context for ThinkingWidget query.
        log.set_streaming(True)
        assert log._streaming_active is True

        # set_streaming(False) is called in close_box
        log.set_streaming(False)
        assert log._streaming_active is False

    def test_streaming_guard_integration(self):
        """End-to-end: write at wide, set streaming, resize narrow, set False → reflow fires."""
        log = _make_log(80)
        log.write(Text("broad content line"))
        log.set_streaming(True)

        # Narrow resize during streaming — should schedule but not execute
        ev = _fake_resize_event(40)
        reflow_calls = []
        with patch.object(log, "call_after_refresh", side_effect=lambda fn: reflow_calls.append(fn)):
            log.on_resize(ev)

        assert log._reflow_scheduled is True

        # End streaming → set_streaming(False) dispatches the pending reflow
        dispatch_calls = []
        with patch.object(log, "call_after_refresh", side_effect=lambda fn: dispatch_calls.append(fn)):
            log.set_streaming(False)

        assert log._streaming_active is False
        assert len(dispatch_calls) == 1


# ---------------------------------------------------------------------------
# TestSourceOpsCap — REFLOW-M2
# ---------------------------------------------------------------------------


class TestSourceOpsCap:
    def test_source_ops_capped_at_2000(self):
        """Writing 2001 ops results in exactly 2000 stored (cap enforced per write)."""
        log = _make_log(80)
        for i in range(2001):
            log.write(Text(f"line {i}"))

        assert len(log._source_ops) == 2000

    def test_cap_drops_oldest(self):
        """After cap, the oldest op is absent and the newest is present."""
        log = _make_log(80)
        for i in range(2001):
            log.write(Text(f"unique-{i}"))

        texts = [op.content.plain for op in log._source_ops if hasattr(op.content, "plain")]
        assert "unique-0" not in texts      # oldest dropped
        assert "unique-2000" in texts       # newest retained

    def test_rendered_max_width_conservative_after_eviction(self):
        """_rendered_max_width stays at historical max even after oldest ops are evicted."""
        log = _make_log(80)
        for i in range(2001):
            log.write(Text(f"w80-{i}"))

        # _rendered_max_width should still be 80 (conservative max; not reset after eviction)
        assert log._rendered_max_width == 80


# ---------------------------------------------------------------------------
# TestReplayGuards — REFLOW-L1
# ---------------------------------------------------------------------------


class TestReplayGuards:
    def test_no_double_append_during_replay(self):
        """_do_reflow does not double-append: source_ops post-reflow equals pre-reflow count.

        _source_ops is cleared before the replay loop; each replayed write re-populates
        it exactly once. The buffer size after reflow equals the buffer size before.
        """
        log = _make_log(80)
        log.write(Text("alpha"))
        log.write_with_source(Text("beta styled"), "beta")
        pre_reflow_count = len(log._source_ops)
        assert pre_reflow_count == 2

        log._render_width = 40
        log._do_reflow()

        # After replay, _source_ops has exactly the same number of ops (no doubling)
        assert len(log._source_ops) == pre_reflow_count

    def test_plain_lines_not_duplicated_during_replay(self):
        """After reflow, _plain_lines length equals number of wws ops replayed."""
        log = _make_log(80)
        # write_with_source is the reliable path for _plain_lines (write() guards on _size_known)
        log.write_with_source(Text("alpha styled"), "alpha")
        log.write_with_source(Text("beta styled"), "beta")
        pre_count = len(log._plain_lines)
        assert pre_count == 2

        log._render_width = 20
        log._do_reflow()

        # After reflow, _plain_lines is rebuilt from wws ops — exactly pre_count entries (no dup)
        assert len(log._plain_lines) == pre_count
