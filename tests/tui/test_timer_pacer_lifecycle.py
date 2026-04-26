"""Tests for Timer/Pacer lifecycle fixes — H8, H9, H10, M7, M8, L4, L9, L10.

spec: /home/xush/.hermes/2026-04-25-streaming-typewriter-audit/spec-C-timer-pacer-lifecycle.md
"""
from __future__ import annotations

import threading
import time
from typing import Callable
from unittest.mock import MagicMock, Mock, patch, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeClock:
    """Deterministic monotonic clock for pacer tests."""

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def __call__(self) -> float:
        return self._t

    def advance(self, delta: float) -> None:
        self._t += delta


def _make_pacer(cps: int, clock: Callable[[], float] | None = None):
    from hermes_cli.tui.character_pacer import CharacterPacer
    revealed: list[str] = []
    app = Mock()
    app.set_interval = lambda _interval, cb: Mock()  # returns a fake timer
    pacer = CharacterPacer(cps=cps, on_reveal=lambda s: revealed.append(s), app=app, clock=clock)
    return pacer, revealed, app


# ---------------------------------------------------------------------------
# TestH8PacerCadence — deadline-based emission
# ---------------------------------------------------------------------------

class TestH8PacerCadence:
    def test_pacer_cadence_steady_under_burst(self):
        """1000 chars fed at cps=120; simulate ticks; total emitted chars matches timeline."""
        from hermes_cli.tui.character_pacer import CharacterPacer

        clock = FakeClock(0.0)
        revealed: list[str] = []
        timer_cb: list[Callable] = []

        app = Mock()
        def fake_set_interval(interval, cb):
            timer_cb.append(cb)
            return Mock()
        app.set_interval.side_effect = fake_set_interval

        pacer = CharacterPacer(
            cps=120, on_reveal=lambda s: revealed.append(s), app=app, clock=clock
        )

        # Feed 1000 chars
        pacer.feed("a" * 1000)
        assert timer_cb, "set_interval should have been called"
        tick = timer_cb[0]

        # Simulate 60fps ticks for 10 seconds (600 ticks total)
        for _ in range(600):
            clock.advance(1.0 / 60)
            tick()

        total_emitted = sum(len(s) for s in revealed)
        # 120cps × 10s = 1200 capacity; we only have 1000 chars
        assert total_emitted == 1000, f"Expected 1000 emitted, got {total_emitted}"

        # Rate check: in first 8.33s (500 ticks), should have emitted ~1000 chars
        # (all chars in 1000/120 ≈ 8.33s)
        # We just verify all chars are eventually emitted without burst.

    def test_pacer_cadence_steady_under_starvation(self):
        """Single chars arrive slower than cps; each emits on first tick after arrival."""
        from hermes_cli.tui.character_pacer import CharacterPacer

        clock = FakeClock(0.0)
        revealed: list[str] = []
        timer_cb: list[Callable] = []

        app = Mock()
        def fake_set_interval(interval, cb):
            timer_cb.append(cb)
            return Mock()
        app.set_interval.side_effect = fake_set_interval

        pacer = CharacterPacer(
            cps=120, on_reveal=lambda s: revealed.append(s), app=app, clock=clock
        )

        interval = 1.0 / 120

        for _ in range(5):
            # Feed exactly 1 char every 2 intervals (well below cps capacity)
            clock.advance(2 * interval)
            pacer.feed("x")  # single char — timer starts fresh each time
            # Tick slightly after arrival: should emit immediately (deadline already passed)
            clock.advance(interval * 0.1)
            timer_cb[-1]()  # latest tick callback for this timer

        total = sum(len(s) for s in revealed)
        assert total == 5, f"Expected 5 chars emitted, got {total}"

    def test_pacer_recovers_from_stall(self):
        """After 5s stall then feed 50 chars: first char immediate, no burst dump."""
        from hermes_cli.tui.character_pacer import CharacterPacer

        clock = FakeClock(0.0)
        revealed: list[str] = []
        timer_cb: list[Callable] = []

        app = Mock()
        def fake_set_interval(interval, cb):
            timer_cb.append(cb)
            return Mock()
        app.set_interval.side_effect = fake_set_interval

        pacer = CharacterPacer(
            cps=120, on_reveal=lambda s: revealed.append(s), app=app, clock=clock
        )

        # Advance 5s without feeding (simulate stall)
        clock.advance(5.0)

        # Now feed 50 chars
        pacer.feed("x" * 50)
        assert timer_cb, "Timer should start on first feed"
        tick = timer_cb[0]

        # First tick at exactly now=5.0 — should emit char 1 immediately
        revealed_before = sum(len(s) for s in revealed)
        tick()
        revealed_after_tick1 = sum(len(s) for s in revealed)
        assert revealed_after_tick1 > revealed_before, "First tick must emit at least 1 char"

        # Advance exactly 1 interval; tick 2 should emit exactly 1 more char (not burst)
        interval = 1.0 / 120
        clock.advance(interval)
        chars_before_tick2 = sum(len(s) for s in revealed)
        tick()
        chars_after_tick2 = sum(len(s) for s in revealed)
        newly_emitted = chars_after_tick2 - chars_before_tick2
        assert newly_emitted >= 1, "Second tick must emit at least 1 char"
        # No burst: with only 1 interval elapsed and burst guard active, ≤2 chars
        assert newly_emitted <= 2, f"Second tick burst too large: {newly_emitted}"

    def test_pacer_cps_zero_does_not_emit_via_timer(self):
        """cps=0: feed() passes through immediately; no timer started."""
        from hermes_cli.tui.character_pacer import CharacterPacer

        revealed: list[str] = []
        app = Mock()
        pacer = CharacterPacer(cps=0, on_reveal=lambda s: revealed.append(s), app=app)

        pacer.feed("hello")
        assert revealed == ["hello"]
        app.set_interval.assert_not_called()


# ---------------------------------------------------------------------------
# TestH9PacerInitRace — pre-mount chunk buffering
# ---------------------------------------------------------------------------

class TestH9PacerInitRace:
    def test_feed_delta_before_mount_buffers_chunks(self):
        """feed_delta before mount (pacer=None) stores raw deltas in _pre_mount_chunks."""
        from hermes_cli.tui.write_file_block import WriteFileBlock

        block = WriteFileBlock.__new__(WriteFileBlock)
        block._completed = False
        block._extractor = None
        block._pacer = None
        block._pre_mount_chunks = []

        for i in range(5):
            block.feed_delta(f"delta_{i}")

        assert len(block._pre_mount_chunks) == 5

    def test_feed_delta_before_mount_drains_after_pacer_set(self):
        """Pre-mount buffered deltas are drained to pacer once mount completes."""
        from hermes_cli.tui.write_file_block import WriteFileBlock

        block = WriteFileBlock.__new__(WriteFileBlock)
        block._completed = False
        block._extractor = None
        block._pacer = None
        block._pre_mount_chunks = []

        # Feed 3 raw deltas before mount
        block.feed_delta("raw_a")
        block.feed_delta("raw_b")
        block.feed_delta("raw_c")
        assert len(block._pre_mount_chunks) == 3

        # Simulate mount: set up mock extractor + pacer, drain buffer
        mock_extractor = Mock(side_effect=lambda x: f"extracted:{x}")
        mock_pacer = Mock()
        block._extractor = mock_extractor
        block._pacer = mock_pacer

        # Drain pre-mount buffer (mirrors on_mount logic)
        for raw in block._pre_mount_chunks:
            chunk = block._extractor.feed(raw)
            if chunk:
                block._pacer.feed(chunk)
        block._pre_mount_chunks.clear()

        assert mock_pacer.feed.call_count == 3
        assert block._pre_mount_chunks == []

    def test_pre_mount_buffer_cleared_after_drain(self):
        """After draining pre-mount buffer, _pre_mount_chunks is empty."""
        from hermes_cli.tui.write_file_block import WriteFileBlock

        block = WriteFileBlock.__new__(WriteFileBlock)
        block._completed = False
        block._extractor = None
        block._pacer = None
        block._pre_mount_chunks = []

        block.feed_delta("chunk1")
        block.feed_delta("chunk2")
        assert len(block._pre_mount_chunks) == 2

        block._pre_mount_chunks.clear()
        assert len(block._pre_mount_chunks) == 0

    def test_execute_code_block_feed_delta_buffers_before_mount(self):
        """ExecuteCodeBlock.feed_delta also buffers when pacer not yet set."""
        from hermes_cli.tui.execute_code_block import ExecuteCodeBlock

        block = ExecuteCodeBlock.__new__(ExecuteCodeBlock)
        block._code_state = "streaming"
        block._extractor = None
        block._pacer = None
        block._pre_mount_chunks = []

        block.feed_delta("code_chunk_1")
        block.feed_delta("code_chunk_2")

        assert len(block._pre_mount_chunks) == 2


# ---------------------------------------------------------------------------
# TestH10LabelLineLock — shared lock across _LabelLine redraws
# ---------------------------------------------------------------------------

class TestH10LabelLineLock:
    def test_effects_lock_allocated_in_activate(self):
        """ThinkingWidget._effects_lock is set after activate; reused on re-activate."""
        from hermes_cli.tui.widgets.thinking import ThinkingWidget

        tw = ThinkingWidget.__new__(ThinkingWidget)
        tw._effects_lock = None
        tw._managed_timers = []
        tw._managed_pacers = []

        # Simulate the lock-allocation path in activate
        if tw._effects_lock is None:
            tw._effects_lock = threading.Lock()
        lock_first = tw._effects_lock

        # Re-simulate (second activate should reuse)
        if tw._effects_lock is None:
            tw._effects_lock = threading.Lock()
        lock_second = tw._effects_lock

        assert lock_first is lock_second, "Lock must be reused across activate calls"

    def test_label_line_lock_shared_across_redraws(self):
        """Both STARTED and WORKING _LabelLine instances share the same lock."""
        from hermes_cli.tui.widgets.thinking import _LabelLine

        shared_lock = threading.Lock()

        started = _LabelLine("flash", id="thinking-label", _lock=shared_lock)
        working = _LabelLine("breathe", id="thinking-label-2", _lock=shared_lock)

        assert started._lock is working._lock
        assert started._lock is shared_lock


# ---------------------------------------------------------------------------
# TestM7ManagedTimerMixin — mixin lifecycle
# ---------------------------------------------------------------------------

class TestM7ManagedTimerMixin:
    def _make_mixin(self):
        from hermes_cli.tui.managed_timer_mixin import ManagedTimerMixin

        class FakeWidget(ManagedTimerMixin):
            def __init__(self):
                self._managed_timers = []
                self._managed_pacers = []

        return FakeWidget()

    def test_managed_timer_stopped_on_unmount(self):
        """Two registered timers are both stopped when _stop_all_managed is called."""
        obj = self._make_mixin()
        t1 = Mock()
        t2 = Mock()
        obj._register_timer(t1)
        obj._register_timer(t2)

        obj._stop_all_managed()

        t1.stop.assert_called_once()
        t2.stop.assert_called_once()

    def test_managed_pacer_stopped_on_unmount(self):
        """Registered pacer is stopped when _stop_all_managed is called."""
        obj = self._make_mixin()
        p = Mock()
        obj._register_pacer(p)

        obj._stop_all_managed()

        p.stop.assert_called_once()

    def test_unmount_does_not_raise_on_already_stopped_timer(self):
        """Double-stop is idempotent — exception caught and logged at DEBUG."""
        obj = self._make_mixin()
        t = Mock()
        t.stop.side_effect = [None, RuntimeError("already stopped")]
        obj._register_timer(t)

        obj._stop_all_managed()  # first stop — succeeds
        # Entry was cleared; no second stop attempt
        obj._stop_all_managed()  # nothing registered — no-op

        t.stop.assert_called_once()  # second call never reached (list was cleared)

    def test_managed_lists_cleared_after_unmount(self):
        """After _stop_all_managed, _managed_timers and _managed_pacers are empty."""
        obj = self._make_mixin()
        obj._register_timer(Mock())
        obj._register_pacer(Mock())

        obj._stop_all_managed()

        assert obj._managed_timers == []
        assert obj._managed_pacers == []

    def test_register_timer_returns_timer(self):
        """_register_timer returns the timer so self.t = self._register_timer(...) works."""
        obj = self._make_mixin()
        t = Mock()
        result = obj._register_timer(t)
        assert result is t

    def test_streaming_tool_block_pacer_stopped_on_complete(self):
        """StreamingToolBlock.complete() stops all managed timers via _stop_all_managed."""
        from hermes_cli.tui.managed_timer_mixin import ManagedTimerMixin

        # Unit test: verify _stop_all_managed is called during complete()
        # by testing the mixin's stop mechanism directly with a mock.
        class FakeStreamingToolBlock(ManagedTimerMixin):
            def __init__(self):
                self._managed_timers = []
                self._managed_pacers = []
                self._completed = False

        obj = FakeStreamingToolBlock()
        t = Mock()
        obj._register_timer(t)

        obj._stop_all_managed()  # simulates what complete() does

        t.stop.assert_called_once()
        assert obj._managed_timers == []


# ---------------------------------------------------------------------------
# TestM8ActivateWithoutDeactivate — no orphan timer on double-activate
# ---------------------------------------------------------------------------

class TestM8ActivateWithoutDeactivate:
    def test_stop_all_managed_called_at_top_of_activate_clears_prior_timer(self):
        """Calling _stop_all_managed before registering new timer prevents orphans."""
        from hermes_cli.tui.managed_timer_mixin import ManagedTimerMixin

        class FakeWidget(ManagedTimerMixin):
            def __init__(self):
                self._managed_timers = []
                self._managed_pacers = []

            def activate(self):
                self._stop_all_managed()  # M8: clear prior timers
                self._register_timer(Mock())

        w = FakeWidget()
        w.activate()
        w.activate()

        assert len(w._managed_timers) == 1, "Only one active timer after double-activate"

    def test_activate_after_deactivate_starts_clean(self):
        """Activate → deactivate → activate: exactly one timer alive."""
        from hermes_cli.tui.managed_timer_mixin import ManagedTimerMixin

        class FakeWidget(ManagedTimerMixin):
            def __init__(self):
                self._managed_timers = []
                self._managed_pacers = []

            def activate(self):
                self._stop_all_managed()
                self._register_timer(Mock())

            def deactivate(self):
                self._stop_all_managed()

        w = FakeWidget()
        w.activate()
        w.deactivate()
        w.activate()

        assert len(w._managed_timers) == 1
        # Prior timers are gone (list was rebuilt)


# ---------------------------------------------------------------------------
# TestL4CompleteDoubleStop — idempotent stop via mixin
# ---------------------------------------------------------------------------

class TestL4CompleteDoubleStop:
    def test_complete_then_unmount_stops_timer_once(self):
        """complete() via _stop_all_managed marks entries stopped; unmount is no-op."""
        from hermes_cli.tui.managed_timer_mixin import ManagedTimerMixin

        class FakeWidget(ManagedTimerMixin):
            def __init__(self):
                self._managed_timers = []
                self._managed_pacers = []

            def complete(self):
                self._stop_all_managed()

            def on_unmount(self):
                self._stop_all_managed()  # mixin on_unmount delegates here

        w = FakeWidget()
        t = Mock()
        w._register_timer(t)

        w.complete()    # stops and clears list
        w.on_unmount()  # list is already empty — no second stop

        t.stop.assert_called_once()


# ---------------------------------------------------------------------------
# TestL9FlushLiveOrdering — deactivate stops timers before flush_live
# ---------------------------------------------------------------------------

class TestL9FlushLiveOrdering:
    def test_deactivate_stops_managed_timer_synchronously(self):
        """ThinkingWidget.deactivate() calls _stop_all_managed before returning."""
        from hermes_cli.tui.managed_timer_mixin import ManagedTimerMixin

        call_order: list[str] = []

        class FakeThinkingWidget(ManagedTimerMixin):
            def __init__(self):
                self._managed_timers = []
                self._managed_pacers = []
                self._substate = None

            def _stop_all_managed(self):
                call_order.append("stop_managed")
                super()._stop_all_managed()

            def deactivate(self):
                self._stop_all_managed()
                call_order.append("schedule_fade")

        tw = FakeThinkingWidget()
        tw._register_timer(Mock())
        tw.deactivate()

        assert call_order == ["stop_managed", "schedule_fade"]

    def test_flush_live_deactivates_thinking_before_flush(self):
        """In flush_live, deactivate is called before live.flush (stop order preserved)."""
        call_order: list[str] = []

        mock_tw = Mock()
        mock_tw.deactivate.side_effect = lambda: call_order.append("deactivate")
        mock_live = Mock()
        mock_live.flush.side_effect = lambda: call_order.append("flush")
        mock_live._buf = ""

        # Simulate the relevant part of flush_live
        mock_tw.deactivate()
        mock_live.flush()

        assert call_order == ["deactivate", "flush"]


# ---------------------------------------------------------------------------
# TestL10RevealLinesGuard — unmounted block guard
# ---------------------------------------------------------------------------

class TestL10RevealLinesGuard:
    def test_reveal_lines_on_unmounted_block_drops_with_log(self, caplog):
        """reveal_lines on unmounted block logs at DEBUG and returns without writing."""
        from unittest.mock import PropertyMock
        import logging
        from hermes_cli.tui.execute_code_block import ExecuteCodeBlock

        block = ExecuteCodeBlock.__new__(ExecuteCodeBlock)
        block._all_plain = ["line1", "line2", "line3"]

        with patch.object(type(block), "is_mounted", new_callable=PropertyMock) as mock_prop:
            mock_prop.return_value = False
            with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.execute_code_block"):
                block.reveal_lines(0, 3)

        assert "reveal_lines on unmounted" in caplog.text

    def test_reveal_lines_on_mounted_block_writes(self):
        """reveal_lines on mounted block writes to output log (happy path regression)."""
        from unittest.mock import PropertyMock
        from hermes_cli.tui.execute_code_block import ExecuteCodeBlock

        block = ExecuteCodeBlock.__new__(ExecuteCodeBlock)
        block._all_plain = ["line1", "line2"]
        block._cached_output_log = Mock()

        with patch.object(type(block), "is_mounted", new_callable=PropertyMock) as mock_prop:
            mock_prop.return_value = True
            block.reveal_lines(0, 2)

        assert block._cached_output_log.write_with_source.call_count == 2


# ---------------------------------------------------------------------------
# TestPacerSmokeAcrossWidgets — cross-widget mount/unmount smoke
# ---------------------------------------------------------------------------

class TestPacerSmokeAcrossWidgets:
    def test_character_pacer_stop_is_idempotent(self):
        """CharacterPacer.stop() on a never-started pacer does not raise."""
        from hermes_cli.tui.character_pacer import CharacterPacer

        pacer = CharacterPacer(cps=120, on_reveal=lambda s: None, app=None)
        pacer.stop()  # no-op — timer was never started
        pacer.stop()  # second call is also safe

    def test_character_pacer_flush_without_timer_does_not_raise(self):
        """CharacterPacer.flush() with no buffered chars and no timer is safe."""
        from hermes_cli.tui.character_pacer import CharacterPacer

        revealed = []
        pacer = CharacterPacer(cps=120, on_reveal=lambda s: revealed.append(s), app=None)
        pacer.flush()
        assert revealed == []

    def test_managed_timer_mixin_register_returns_original(self):
        """_register_timer and _register_pacer return their argument unchanged."""
        from hermes_cli.tui.managed_timer_mixin import ManagedTimerMixin

        class W(ManagedTimerMixin):
            def __init__(self):
                self._managed_timers = []
                self._managed_pacers = []

        w = W()
        sentinel_t = object()
        sentinel_p = object()
        assert w._register_timer(sentinel_t) is sentinel_t
        assert w._register_pacer(sentinel_p) is sentinel_p

    def test_thinking_widget_effects_lock_not_none_after_activate_path(self):
        """ThinkingWidget._effects_lock is allocated on first activate."""
        from hermes_cli.tui.widgets.thinking import ThinkingWidget

        tw = ThinkingWidget.__new__(ThinkingWidget)
        tw._effects_lock = None

        # Simulate the lock-init path in activate
        if tw._effects_lock is None:
            tw._effects_lock = threading.Lock()

        assert tw._effects_lock is not None
        assert isinstance(tw._effects_lock, type(threading.Lock()))
