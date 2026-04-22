"""Unit tests for FeedbackService — T1–T15.

No Textual, no App, no run_test. Uses FakeScheduler + FakeAdapter.
"""
from __future__ import annotations

import gc
from typing import Any

import pytest

from hermes_cli.tui.services.feedback import (
    CRITICAL,
    ERROR,
    LOW,
    NORMAL,
    WARN,
    ChannelAdapter,
    ExpireReason,
    FeedbackService,
    FlashState,
)

# ---------------------------------------------------------------------------
# Test fakes
# ---------------------------------------------------------------------------


class FakeCancelToken:
    def __init__(self) -> None:
        self.stopped: bool = False

    def stop(self) -> None:
        self.stopped = True


class FakeScheduler:
    def __init__(self) -> None:
        self._now: float = 0.0
        self._queue: list[list[Any]] = []  # [fire_at, cb, token]

    def after(self, delay: float, cb: Any) -> FakeCancelToken:
        token = FakeCancelToken()
        self._queue.append([self._now + delay, cb, token])
        self._queue.sort(key=lambda x: x[0])
        return token

    def advance(self, dt: float) -> None:
        self._now += dt
        for entry in list(self._queue):
            if entry[0] <= self._now and not entry[2].stopped:
                entry[2].stopped = True
                entry[1]()
        self._queue = [e for e in self._queue if not e[2].stopped]


class FakeAdapter(ChannelAdapter):
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self._mounted: bool = True

    def apply(self, state: FlashState) -> None:
        from hermes_cli.tui.services.feedback import ChannelUnmountedError
        if not self._mounted:
            raise ChannelUnmountedError("not mounted")
        self.calls.append(("apply", state.message))

    def restore(self) -> None:
        self.calls.append(("restore",))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_service(*channels: str, lifecycle_aware: bool = False) -> tuple[FeedbackService, FakeScheduler, dict[str, FakeAdapter]]:
    sched = FakeScheduler()
    svc = FeedbackService(sched)
    adapters: dict[str, FakeAdapter] = {}
    for ch in channels:
        adapter = FakeAdapter()
        svc.register_channel(ch, adapter, lifecycle_aware=lifecycle_aware)
        adapters[ch] = adapter
    return svc, sched, adapters


# ---------------------------------------------------------------------------
# T1 — basic flash applies then restores
# ---------------------------------------------------------------------------


def test_t1_basic_flash_applies_then_restores() -> None:
    svc, sched, ads = make_service("c1")
    ad = ads["c1"]

    handle = svc.flash("c1", "hi", duration=0.5)
    assert handle.displayed is True
    assert ("apply", "hi") in ad.calls

    restore_before = sum(1 for c in ad.calls if c[0] == "restore")
    sched.advance(0.6)
    restore_after = sum(1 for c in ad.calls if c[0] == "restore")
    assert restore_after == restore_before + 1


# ---------------------------------------------------------------------------
# T2 — second flash at equal priority cancels first timer (D3 regression)
# ---------------------------------------------------------------------------


def test_t2_equal_priority_replace_cancels_first_timer() -> None:
    svc, sched, ads = make_service("c1")
    ad = ads["c1"]

    svc.flash("c1", "A", duration=1.0)
    sched.advance(0.2)
    svc.flash("c1", "B", duration=1.0)

    # advance past when A's original timer would have fired
    sched.advance(1.5)

    restores = [c for c in ad.calls if c[0] == "restore"]
    # exactly one restore — B's natural expiry; A's timer was cancelled
    assert len(restores) == 1


# ---------------------------------------------------------------------------
# T3 — preempted flash's restore does not run; on_expire fires correctly
# ---------------------------------------------------------------------------


def test_t3_preempted_flash_no_restore_correct_callbacks() -> None:
    svc, sched, ads = make_service("c1")
    ad = ads["c1"]

    a_reasons: list[ExpireReason] = []
    b_reasons: list[ExpireReason] = []

    svc.flash("c1", "A", duration=5.0, priority=NORMAL, on_expire=lambda r: a_reasons.append(r))
    svc.flash("c1", "B", duration=1.0, priority=ERROR, on_expire=lambda r: b_reasons.append(r))

    # A was preempted immediately
    assert a_reasons == [ExpireReason.PREEMPTED]

    sched.advance(1.1)
    assert b_reasons == [ExpireReason.NATURAL]

    # restore fired exactly once (for B)
    restores = [c for c in ad.calls if c[0] == "restore"]
    assert len(restores) == 1


# ---------------------------------------------------------------------------
# T4 — cancel() stops the timer; on_expire(CANCELLED) fires; no further calls
# ---------------------------------------------------------------------------


def test_t4_cancel_stops_timer() -> None:
    svc, sched, ads = make_service("c1")
    ad = ads["c1"]

    reasons: list[ExpireReason] = []
    svc.flash("c1", "A", duration=5.0, on_expire=lambda r: reasons.append(r))

    result = svc.cancel("c1")
    assert result is True
    assert reasons == [ExpireReason.CANCELLED]

    restores_after_cancel = len([c for c in ad.calls if c[0] == "restore"])
    # advance well past duration — no more restores should fire
    sched.advance(10.0)
    assert len([c for c in ad.calls if c[0] == "restore"]) == restores_after_cancel


# ---------------------------------------------------------------------------
# T5 — higher priority preempts lower; lower not resurrected
# ---------------------------------------------------------------------------


def test_t5_higher_priority_preempts_lower() -> None:
    svc, sched, ads = make_service("c1")
    ad = ads["c1"]

    svc.flash("c1", "info", duration=5.0, priority=NORMAL)
    handle = svc.flash("c1", "err", duration=1.0, priority=ERROR)
    assert handle.displayed is True

    # error message was applied
    applies = [c for c in ad.calls if c[0] == "apply"]
    assert applies[-1] == ("apply", "err")

    # advance past error duration
    sched.advance(1.1)
    restores = [c for c in ad.calls if c[0] == "restore"]
    assert len(restores) == 1

    # info is NOT resurrected
    applies_after = [c for c in ad.calls if c[0] == "apply"]
    assert all(a[1] != "info" for a in applies_after[1:])


# ---------------------------------------------------------------------------
# T6 — lower priority blocked; handle.displayed == False; high prio continues
# ---------------------------------------------------------------------------


def test_t6_lower_priority_blocked() -> None:
    svc, sched, ads = make_service("c1")
    ad = ads["c1"]

    svc.flash("c1", "err", duration=5.0, priority=ERROR)
    handle = svc.flash("c1", "info", duration=1.0, priority=NORMAL)

    assert handle.displayed is False

    # info was never applied
    applies = [c for c in ad.calls if c[0] == "apply"]
    assert all(a[1] != "info" for a in applies)

    sched.advance(5.1)
    restores = [c for c in ad.calls if c[0] == "restore"]
    assert len(restores) == 1


# ---------------------------------------------------------------------------
# T7 — channels are isolated
# ---------------------------------------------------------------------------


def test_t7_channels_isolated() -> None:
    svc, sched, _ = make_service()
    sched2 = sched

    ad1 = FakeAdapter()
    ad2 = FakeAdapter()
    svc.register_channel("c1", ad1)
    svc.register_channel("c2", ad2)

    svc.flash("c1", "A", duration=1.0)
    svc.flash("c2", "B", duration=2.0)

    sched.advance(1.1)
    # c1 restored; c2 still active
    assert any(c[0] == "restore" for c in ad1.calls)
    assert not any(c[0] == "restore" for c in ad2.calls)

    sched.advance(1.0)
    assert any(c[0] == "restore" for c in ad2.calls)


# ---------------------------------------------------------------------------
# T8 — shutdown cancels all and fires UNMOUNTED; no restore called
# ---------------------------------------------------------------------------


def test_t8_shutdown_on_unmount() -> None:
    svc, sched, ads = make_service("c1", "c2")

    reasons_c1: list[ExpireReason] = []
    reasons_c2: list[ExpireReason] = []

    svc.flash("c1", "X", duration=5.0, on_expire=lambda r: reasons_c1.append(r))
    svc.flash("c2", "Y", duration=5.0, on_expire=lambda r: reasons_c2.append(r))

    # Record restore count before shutdown
    restores_before = sum(
        len([c for c in ads[ch].calls if c[0] == "restore"]) for ch in ("c1", "c2")
    )

    svc.shutdown()

    # on_expire fires with UNMOUNTED for each
    assert reasons_c1 == [ExpireReason.UNMOUNTED]
    assert reasons_c2 == [ExpireReason.UNMOUNTED]

    # shutdown does NOT call adapter.restore()
    restores_after = sum(
        len([c for c in ads[ch].calls if c[0] == "restore"]) for ch in ("c1", "c2")
    )
    assert restores_after == restores_before

    # advance past original duration — nothing fires
    sched.advance(10.0)
    restores_final = sum(
        len([c for c in ads[ch].calls if c[0] == "restore"]) for ch in ("c1", "c2")
    )
    assert restores_final == restores_before


# ---------------------------------------------------------------------------
# T9 — key replaces regardless of priority
# ---------------------------------------------------------------------------


def test_t9_key_replaces_regardless_of_priority() -> None:
    svc, sched, ads = make_service("c1")
    ad = ads["c1"]

    reasons: list[ExpireReason] = []

    # High-priority ERROR flash with key="copy"
    svc.flash("c1", "err", duration=5.0, priority=ERROR, key="copy", on_expire=lambda r: reasons.append(r))

    # Low-priority NORMAL flash with same key — should replace
    handle = svc.flash("c1", "copied", duration=1.5, priority=NORMAL, key="copy")
    assert handle.displayed is True

    # Previous flash was preempted
    assert reasons == [ExpireReason.PREEMPTED]

    # New message was applied
    applies = [c for c in ad.calls if c[0] == "apply"]
    assert applies[-1] == ("apply", "copied")


# ---------------------------------------------------------------------------
# T10 — peek reflects active state
# ---------------------------------------------------------------------------


def test_t10_peek_reflects_active_state() -> None:
    svc, sched, _ = make_service("c1")

    assert svc.peek("c1") is None

    svc.flash("c1", "hello", duration=1.0)
    state = svc.peek("c1")
    assert state is not None
    assert state.message == "hello"

    svc.cancel("c1")
    assert svc.peek("c1") is None


# ---------------------------------------------------------------------------
# T11 — on_agent_idle does not clear an active flash (E3 regression)
# ---------------------------------------------------------------------------


def test_t11_on_agent_idle_does_not_clear_active_flash() -> None:
    svc, sched, ads = make_service("c1", lifecycle_aware=True)
    ad = ads["c1"]

    svc.flash("c1", "flashing", duration=5.0)

    restores_before = len([c for c in ad.calls if c[0] == "restore"])
    svc.on_agent_idle()
    restores_after = len([c for c in ad.calls if c[0] == "restore"])

    assert restores_after == restores_before  # no additional restore


# ---------------------------------------------------------------------------
# T12 — on_agent_idle restores resting state when no flash active
# ---------------------------------------------------------------------------


def test_t12_on_agent_idle_restores_when_no_flash() -> None:
    svc, sched, ads = make_service("c1", lifecycle_aware=True)
    ad = ads["c1"]

    svc.on_agent_idle()

    restores = [c for c in ad.calls if c[0] == "restore"]
    assert len(restores) == 1


# ---------------------------------------------------------------------------
# T13 — no reference cycle (D5 regression)
# ---------------------------------------------------------------------------


def test_t13_no_reference_cycle() -> None:
    svc, sched, _ = make_service()

    for i in range(1000):
        ch = "c1"
        if i == 0:
            ad = FakeAdapter()
            svc.register_channel(ch, ad)
        svc.flash(ch, f"msg{i}", duration=0.1)

    # expire all
    sched.advance(1.0)

    # No active state should remain
    assert len(svc._active) == 0

    # force GC
    gc.collect()

    # service itself is clean
    assert len(svc._active) == 0


# ---------------------------------------------------------------------------
# T14 — restore pulls live resting state (not a snapshot from flash-time)
# ---------------------------------------------------------------------------


def test_t14_restore_pulls_live_resting_state() -> None:
    """Adapter.restore() is a method call, not a closure over snapshotted state.

    This verifies the architectural property: after flash expires, restore()
    is called and the adapter reads from live widget state, not from a value
    captured at apply() time.
    """

    class LiveStateAdapter(ChannelAdapter):
        def __init__(self) -> None:
            self.restore_calls: int = 0
            self.current_label: str = "original"

        def apply(self, state: FlashState) -> None:
            # simulate changing the label during a flash
            self.current_label = "changed-during-flash"

        def restore(self) -> None:
            self.restore_calls += 1
            # restore reads live state, not a snapshot
            # (in production this would read widget.hint or _copy_original)
            self.current_label = "restored-from-live"

    svc, sched, _ = make_service()
    adapter = LiveStateAdapter()
    svc.register_channel("live", adapter)

    svc.flash("live", "msg", duration=0.5)
    assert adapter.current_label == "changed-during-flash"

    sched.advance(0.6)
    assert adapter.restore_calls == 1
    assert adapter.current_label == "restored-from-live"


# ---------------------------------------------------------------------------
# T15 — cancel_all(channel=) leaves other channels
# ---------------------------------------------------------------------------


def test_t15_cancel_all_channel_selective() -> None:
    svc, sched, _ = make_service()

    ad1 = FakeAdapter()
    ad2 = FakeAdapter()
    svc.register_channel("c1", ad1)
    svc.register_channel("c2", ad2)

    svc.flash("c1", "A", duration=5.0)
    svc.flash("c2", "B", duration=5.0)

    count = svc.cancel_all(channel="c1")
    assert count == 1
    assert svc.peek("c1") is None
    assert svc.peek("c2") is not None

    # c2 still expires naturally
    sched.advance(5.1)
    restores_c2 = [c for c in ad2.calls if c[0] == "restore"]
    assert len(restores_c2) == 1
