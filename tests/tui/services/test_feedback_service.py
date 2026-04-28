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


class _FakeSettledWidget:
    """Minimal SettledAware-conforming widget for FB-M2/M3/M4 tests."""

    def __init__(self, settled: bool = False) -> None:
        self._settled_flag = settled

    def is_settled(self) -> bool:
        return self._settled_flag


class FakeAdapter(ChannelAdapter):
    def __init__(
        self,
        *,
        fail_after_n_applies: int | None = None,
        apply_exception: type[BaseException] | None = None,
        settled: bool = False,
    ) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self._mounted: bool = True
        self._apply_count: int = 0
        self._fail_after_n_applies = fail_after_n_applies
        from hermes_cli.tui.services.feedback import ChannelUnmountedError
        self._apply_exception: type[BaseException] = apply_exception or ChannelUnmountedError
        self._widget: Any | None = _FakeSettledWidget(settled=True) if settled else None

    @property
    def widget(self) -> "Any | None":
        return self._widget

    def apply(self, state: FlashState) -> None:
        from hermes_cli.tui.services.feedback import ChannelUnmountedError
        if not self._mounted:
            raise ChannelUnmountedError("not mounted")
        if self._fail_after_n_applies is not None:
            if self._apply_count >= self._fail_after_n_applies:
                self._apply_count += 1
                raise self._apply_exception("FakeAdapter scheduled failure")
        self._apply_count += 1
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


# ---------------------------------------------------------------------------
# FB-H1 — equal-priority replace fires PREEMPTED on_expire
# ---------------------------------------------------------------------------


class TestEqualPriorityReplace:
    def test_equal_priority_replace_fires_preempted(self) -> None:
        svc, sched, ads = make_service("c1")
        a_reasons: list[ExpireReason] = []
        b_reasons: list[ExpireReason] = []
        svc.flash("c1", "A", duration=5.0, on_expire=lambda r: a_reasons.append(r))
        svc.flash("c1", "B", duration=5.0, on_expire=lambda r: b_reasons.append(r))
        assert a_reasons == [ExpireReason.PREEMPTED]
        assert b_reasons == []

    def test_equal_priority_new_flash_displayed(self) -> None:
        svc, sched, ads = make_service("c1")
        svc.flash("c1", "A", duration=5.0)
        h = svc.flash("c1", "B", duration=5.0)
        assert h.displayed is True
        peeked = svc.peek("c1")
        assert peeked is not None
        assert peeked.message == "B"

    def test_lower_priority_blocked_does_not_fire_existing_callback(self) -> None:
        svc, _, _ = make_service("c1")
        a_reasons: list[ExpireReason] = []
        svc.flash("c1", "A", duration=5.0, priority=WARN, on_expire=lambda r: a_reasons.append(r))
        h = svc.flash("c1", "B", duration=5.0, priority=NORMAL)
        assert h.displayed is False
        assert a_reasons == []  # existing callback NOT fired


# ---------------------------------------------------------------------------
# FB-H2 — apply() ChannelUnmountedError after preempt restores channel
# ---------------------------------------------------------------------------


class TestApplyFailureAfterPreempt:
    def test_apply_unmounted_after_preempt_restores_channel(self) -> None:
        from hermes_cli.tui.services.feedback import (
            ChannelUnmountedError,
            FeedbackService,
        )
        sched = FakeScheduler()
        svc = FeedbackService(sched)
        ad = FakeAdapter(fail_after_n_applies=1, apply_exception=ChannelUnmountedError)
        svc.register_channel("c1", ad)
        a_reasons: list[ExpireReason] = []
        b_reasons: list[ExpireReason] = []
        ha = svc.flash("c1", "A", duration=5.0, on_expire=lambda r: a_reasons.append(r))
        assert ha.displayed is True
        restore_count_before = sum(1 for c in ad.calls if c[0] == "restore")
        hb = svc.flash("c1", "B", duration=5.0, on_expire=lambda r: b_reasons.append(r))
        assert hb.displayed is False
        # A's PREEMPTED fired from the H1 path
        assert a_reasons == [ExpireReason.PREEMPTED]
        # B's UNMOUNTED fired on apply failure
        assert b_reasons == [ExpireReason.UNMOUNTED]
        # restore() was called once on the failure path
        restore_count_after = sum(1 for c in ad.calls if c[0] == "restore")
        assert restore_count_after == restore_count_before + 1

    def test_apply_unmounted_no_preempt_still_restores(self) -> None:
        from hermes_cli.tui.services.feedback import (
            ChannelUnmountedError,
            FeedbackService,
        )
        sched = FakeScheduler()
        svc = FeedbackService(sched)
        ad = FakeAdapter(fail_after_n_applies=0, apply_exception=ChannelUnmountedError)
        svc.register_channel("c1", ad)
        reasons: list[ExpireReason] = []
        h = svc.flash("c1", "A", duration=5.0, on_expire=lambda r: reasons.append(r))
        assert h.displayed is False
        assert reasons == [ExpireReason.UNMOUNTED]
        restores = [c for c in ad.calls if c[0] == "restore"]
        assert len(restores) == 1


# ---------------------------------------------------------------------------
# FB-M1 — generic apply() exceptions logged + UNMOUNTED + restore
# ---------------------------------------------------------------------------


class TestApplyGenericException:
    def test_apply_generic_exception_does_not_crash_flash(self, caplog: Any) -> None:
        import logging
        sched = FakeScheduler()
        svc = FeedbackService(sched)
        ad = FakeAdapter(fail_after_n_applies=0, apply_exception=RuntimeError)
        svc.register_channel("c1", ad)
        reasons: list[ExpireReason] = []
        with caplog.at_level(logging.ERROR, logger="hermes_cli.tui.services.feedback"):
            h = svc.flash("c1", "boom", on_expire=lambda r: reasons.append(r))
        assert h.displayed is False
        assert reasons == [ExpireReason.UNMOUNTED]
        # ERROR log with exception traceback
        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert any("adapter.apply() failed" in r.getMessage() for r in error_records)
        assert any(r.exc_info is not None for r in error_records)

    def test_apply_generic_exception_calls_restore(self) -> None:
        sched = FakeScheduler()
        svc = FeedbackService(sched)
        ad = FakeAdapter(fail_after_n_applies=0, apply_exception=RuntimeError)
        svc.register_channel("c1", ad)
        svc.flash("c1", "boom")
        restores = [c for c in ad.calls if c[0] == "restore"]
        assert len(restores) == 1

    def test_hint_bar_get_bar_propagates_render_error(self) -> None:
        from unittest.mock import MagicMock
        from hermes_cli.tui.services.feedback import HintBarAdapter

        app = MagicMock()
        app.query_one.side_effect = RuntimeError("render boom")
        ad = HintBarAdapter(app)
        with pytest.raises(RuntimeError, match="render boom"):
            ad._get_bar()


# ---------------------------------------------------------------------------
# FB-M2 — settled-suppression fires SUPPRESSED reason
# ---------------------------------------------------------------------------


class TestSettledSuppressionReason:
    def test_settled_suppression_fires_suppressed_reason(self) -> None:
        sched = FakeScheduler()
        svc = FeedbackService(sched)
        ad = FakeAdapter(settled=True)
        svc.register_channel("c1", ad)
        reasons: list[ExpireReason] = []
        h = svc.flash("c1", "hi", on_expire=lambda r: reasons.append(r))
        assert h.displayed is False
        assert reasons == [ExpireReason.SUPPRESSED]

    def test_settled_exempt_tones_unaffected(self) -> None:
        sched = FakeScheduler()
        svc = FeedbackService(sched)
        ad = FakeAdapter(settled=True)
        svc.register_channel("c1", ad)
        for tone in ("focus", "err-enter"):
            reasons: list[ExpireReason] = []
            h = svc.flash("c1", "hi", tone=tone, on_expire=lambda r, _r=reasons: _r.append(r))
            assert h.displayed is True, f"{tone} should bypass settled-suppression"
            assert reasons == []
            svc.cancel("c1")


# ---------------------------------------------------------------------------
# FB-M3 — SettledAware protocol (structural) gates suppression
# ---------------------------------------------------------------------------


class TestSettledProtocol:
    def test_settled_protocol_required_for_suppression(self) -> None:
        # Widget has _settled=True but no is_settled() — must NOT suppress.
        class _BareWidget:
            _settled = True

        sched = FakeScheduler()
        svc = FeedbackService(sched)
        ad = FakeAdapter()
        ad._widget = _BareWidget()
        svc.register_channel("c1", ad)
        h = svc.flash("c1", "hi")
        assert h.displayed is True

    def test_settled_protocol_true_suppresses(self) -> None:
        sched = FakeScheduler()
        svc = FeedbackService(sched)
        ad = FakeAdapter(settled=True)
        svc.register_channel("c1", ad)
        h = svc.flash("c1", "hi")
        assert h.displayed is False

    def test_settled_protocol_false_applies(self) -> None:
        sched = FakeScheduler()
        svc = FeedbackService(sched)
        ad = FakeAdapter()
        ad._widget = _FakeSettledWidget(settled=False)
        svc.register_channel("c1", ad)
        h = svc.flash("c1", "hi")
        assert h.displayed is True


# ---------------------------------------------------------------------------
# FB-M4 — Adapter widget contract (HintBar=None, CodeFooter resolves ancestor)
# ---------------------------------------------------------------------------


class TestAdapterWidgetContract:
    def test_hint_bar_adapter_widget_is_none(self) -> None:
        from unittest.mock import MagicMock
        from hermes_cli.tui.services.feedback import HintBarAdapter

        ad = HintBarAdapter(MagicMock())
        assert ad.widget is None

    def test_code_footer_adapter_resolves_settled_ancestor(self) -> None:
        from hermes_cli.tui.services.feedback import CodeFooterAdapter

        block = _FakeSettledWidget(settled=False)

        class _FakeFooter:
            def __init__(self, ancestors: list[Any]) -> None:
                self.ancestors_with_self = ancestors

        # Footer with SettledAware ancestor — resolves and caches.
        footer = _FakeFooter([object(), block])
        ad = CodeFooterAdapter(footer)
        first = ad.widget
        assert first is block
        # second access: cached
        assert ad.widget is block

        # Footer with no SettledAware ancestor — None and not cached.
        footer2 = _FakeFooter([object(), object()])
        ad2 = CodeFooterAdapter(footer2)
        assert ad2.widget is None
        # Add an ancestor and confirm next call walks again.
        footer2.ancestors_with_self = [object(), block]
        assert ad2.widget is block

    def test_code_footer_adapter_cache_survives_clear_settled(self) -> None:
        from hermes_cli.tui.services.feedback import CodeFooterAdapter, FeedbackService

        block = _FakeSettledWidget(settled=False)

        class _FakeFooter:
            ancestors_with_self = [block]

        # Subclass to no-op apply/restore — _FakeFooter doesn't implement the
        # widget interface, but we're testing the cache + protocol read path,
        # not the apply path.
        class _CachingAdapter(CodeFooterAdapter):
            def apply(self, state: FlashState) -> None:
                pass

            def restore(self) -> None:
                pass

        sched = FakeScheduler()
        svc = FeedbackService(sched)
        ad = _CachingAdapter(_FakeFooter())
        svc.register_channel("c1", ad)

        # Prime cache.
        first = ad.widget
        assert first is block

        # Toggle block._settled directly (testing adapter cache + protocol read,
        # not block lifecycle). is_settled() reads _settled_flag.
        block._settled_flag = False
        # Cached ancestor identity stable
        assert ad.widget is block
        # Flash succeeds while not settled
        h1 = svc.flash("c1", "hi")
        assert h1.displayed is True
        svc.cancel("c1")

        # Toggle back to settled — same cached ancestor, suppression engages
        block._settled_flag = True
        assert ad.widget is block
        reasons: list[ExpireReason] = []
        h2 = svc.flash("c1", "hi", on_expire=lambda r: reasons.append(r))
        assert h2.displayed is False
        assert reasons == [ExpireReason.SUPPRESSED]


# ---------------------------------------------------------------------------
# FB-L1 — register_channel double-registration warning + cancel + reentry guard
# ---------------------------------------------------------------------------


class TestRegisterOverwriteWarning:
    def test_register_channel_warns_on_overwrite(self, caplog: Any) -> None:
        import logging
        sched = FakeScheduler()
        svc = FeedbackService(sched)
        ad1 = FakeAdapter()
        ad2 = FakeAdapter()
        with caplog.at_level(logging.WARNING, logger="hermes_cli.tui.services.feedback"):
            svc.register_channel("c1", ad1)
            assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
            svc.register_channel("c1", ad2)
        warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("'c1' re-registered" in r.getMessage() for r in warns)
        assert any("FakeAdapter" in r.getMessage() for r in warns)

    def test_register_channel_cancels_active_flash_on_overwrite(self) -> None:
        sched = FakeScheduler()
        svc = FeedbackService(sched)
        ad_a = FakeAdapter()
        ad_b = FakeAdapter()
        svc.register_channel("c1", ad_a)
        a_reasons: list[ExpireReason] = []
        svc.flash("c1", "A", duration=5.0, on_expire=lambda r: a_reasons.append(r))

        svc.register_channel("c1", ad_b)
        # A's on_expire fired with UNMOUNTED
        assert a_reasons == [ExpireReason.UNMOUNTED]
        # _active dropped X
        assert svc.peek("c1") is None
        # B never received restore() as a side effect of the overwrite
        b_restores = [c for c in ad_b.calls if c[0] == "restore"]
        assert b_restores == []
        # advancing time does not fire any stray restore on B
        sched.advance(10.0)
        assert [c for c in ad_b.calls if c[0] == "restore"] == []

    def test_register_channel_reentrant_flash_blocked(self, caplog: Any) -> None:
        import logging
        sched = FakeScheduler()
        svc = FeedbackService(sched)
        ad_a = FakeAdapter()
        ad_b = FakeAdapter()
        svc.register_channel("c1", ad_a)

        captured: dict[str, Any] = {}

        def _on_expire_a(reason: ExpireReason) -> None:
            captured["reason"] = reason
            captured["reentry"] = svc.flash("c1", "reentry", duration=1.0)

        svc.flash("c1", "A", duration=5.0, on_expire=_on_expire_a)
        with caplog.at_level(logging.WARNING, logger="hermes_cli.tui.services.feedback"):
            svc.register_channel("c1", ad_b)
        # callback fired
        assert captured["reason"] == ExpireReason.UNMOUNTED
        # re-entrant flash blocked
        assert captured["reentry"].displayed is False
        # WARNING emitted for the reentry attempt
        warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("re-entry" in r.getMessage() for r in warns)
        # B installed
        assert svc._channels["c1"].adapter is ad_b
        # B never had restore() called from a stale timer
        sched.advance(10.0)
        assert [c for c in ad_b.calls if c[0] == "restore"] == []


# ---------------------------------------------------------------------------
# FB-L2 — state-change tones constant gates suppression for unlisted tones
# ---------------------------------------------------------------------------


class TestStateChangeTonesConstant:
    def test_unlisted_tone_is_suppressed_on_settled_widget(self) -> None:
        sched = FakeScheduler()
        svc = FeedbackService(sched)
        ad = FakeAdapter(settled=True)
        svc.register_channel("c1", ad)
        reasons: list[ExpireReason] = []
        # "adopt" is not in _STATE_CHANGE_TONES → must suppress.
        h = svc.flash("c1", "hi", tone="adopt", on_expire=lambda r: reasons.append(r))
        assert h.displayed is False
        assert reasons == [ExpireReason.SUPPRESSED]
