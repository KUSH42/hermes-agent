"""Tests for AgentLifecycleHooks service (RX4 spec §9)."""
from __future__ import annotations
import gc
import logging
from unittest.mock import MagicMock, patch
import pytest

from hermes_cli.tui.services.lifecycle_hooks import AgentLifecycleHooks, RegistrationHandle


# ── Core behavior ─────────────────────────────────────────────────────────────

def test_register_then_fire_invokes_once():
    h = AgentLifecycleHooks()
    calls = []
    h.register("on_turn_start", lambda: calls.append(1))
    h.fire("on_turn_start")
    assert calls == [1]


def test_multiple_registrations_fire_priority_order():
    h = AgentLifecycleHooks()
    order = []
    h.register("on_turn_end_any", lambda: order.append("hi"), priority=500)
    h.register("on_turn_end_any", lambda: order.append("lo"), priority=10)
    h.register("on_turn_end_any", lambda: order.append("mid"), priority=100)
    h.fire("on_turn_end_any")
    assert order == ["lo", "mid", "hi"]


def test_same_priority_registration_order_stable():
    h = AgentLifecycleHooks()
    order = []
    h.register("evt", lambda: order.append("a"), priority=50)
    h.register("evt", lambda: order.append("b"), priority=50)
    h.register("evt", lambda: order.append("c"), priority=50)
    h.fire("evt")
    assert order == ["a", "b", "c"]


def test_fire_unknown_transition_noop():
    h = AgentLifecycleHooks()
    h.fire("does_not_exist")  # no error


def test_ctx_kwargs_forwarded():
    h = AgentLifecycleHooks()
    received = {}
    h.register("on_interrupt", lambda source=None: received.update({"source": source}))
    h.fire("on_interrupt", source="esc")
    assert received == {"source": "esc"}


def test_unregister_removes_callback():
    h = AgentLifecycleHooks()
    calls = []
    handle = h.register("evt", lambda: calls.append(1))
    h.unregister(handle)
    h.fire("evt")
    assert calls == []


def test_unregister_owner_removes_all_for_owner():
    class Owner:
        pass
    owner = Owner()
    h = AgentLifecycleHooks()
    calls = []
    h.register("on_turn_start", lambda: calls.append("a"), owner=owner)
    h.register("on_turn_end_any", lambda: calls.append("b"), owner=owner)
    h.register("on_turn_start", lambda: calls.append("c"))  # no owner
    h.unregister_owner(owner)
    h.fire("on_turn_start")
    h.fire("on_turn_end_any")
    assert calls == ["c"]


# ── Owner lifecycle ───────────────────────────────────────────────────────────

def test_gc_owner_drops_registration():
    """After owner is GC'd, its callbacks are pruned during fire."""
    class Owner:
        def cb(self):
            pass
    owner = Owner()
    h = AgentLifecycleHooks()
    h.register("evt", owner.cb, owner=owner)
    del owner
    gc.collect()
    # Should not raise; dead registration is pruned silently
    h.fire("evt")


def test_multiple_transitions_cleared_by_unregister_owner():
    class Owner:
        pass
    owner = Owner()
    h = AgentLifecycleHooks()
    for t in ("on_turn_start", "on_turn_end_any", "on_compact_complete"):
        h.register(t, lambda: None, owner=owner)
    h.unregister_owner(owner)
    assert all(len(h._registrations.get(t, [])) == 0 for t in ("on_turn_start", "on_turn_end_any", "on_compact_complete"))


# ── Error isolation ───────────────────────────────────────────────────────────

def test_callback_exception_does_not_block_later_callbacks():
    h = AgentLifecycleHooks()
    calls = []

    def bad():
        raise RuntimeError("boom")

    h.register("evt", bad, priority=10)
    h.register("evt", lambda: calls.append("ok"), priority=100)
    h.fire("evt")  # should not raise
    assert calls == ["ok"]


def test_callback_exception_is_logged(caplog):
    h = AgentLifecycleHooks()

    def bad():
        raise ValueError("test-error")

    h.register("evt", bad, name="my_callback")
    with caplog.at_level(logging.ERROR):
        h.fire("evt")
    assert any("my_callback" in r.message and "test-error" in r.message for r in caplog.records)


def test_system_exit_propagates():
    h = AgentLifecycleHooks()
    h.register("evt", lambda: (_ for _ in ()).throw(SystemExit(1)))
    with pytest.raises(SystemExit):
        h.fire("evt")


# ── Pre-mount guard ───────────────────────────────────────────────────────────

def test_fire_before_is_running_defers():
    mock_app = MagicMock()
    mock_app.is_running = False
    h = AgentLifecycleHooks(app=mock_app)
    calls = []
    h.register("on_turn_start", lambda: calls.append(1))
    h.fire("on_turn_start")
    assert calls == []  # deferred
    assert len(h._deferred) == 1


def test_deferred_ctx_preserved():
    mock_app = MagicMock()
    mock_app.is_running = False
    h = AgentLifecycleHooks(app=mock_app)
    received = {}
    h.register("on_interrupt", lambda source=None: received.update({"source": source}))
    h.fire("on_interrupt", source="esc")
    # drain manually
    mock_app.is_running = True
    h.drain_deferred()
    assert received == {"source": "esc"}


def test_deferred_fires_in_order():
    mock_app = MagicMock()
    mock_app.is_running = False
    h = AgentLifecycleHooks(app=mock_app)
    order = []
    h.register("a", lambda: order.append("a"))
    h.register("b", lambda: order.append("b"))
    h.fire("a")
    h.fire("b")
    mock_app.is_running = True
    h.drain_deferred()
    assert order == ["a", "b"]


# ── Integration (mutation during fire) ───────────────────────────────────────

def test_registering_during_fire_does_not_call_new_callback_this_turn():
    h = AgentLifecycleHooks()
    calls = []

    def first():
        calls.append("first")
        h.register("evt", lambda: calls.append("new"))

    h.register("evt", first)
    h.fire("evt")
    assert calls == ["first"]  # "new" not called this turn
    h.fire("evt")
    assert "new" in calls  # called next turn


def test_unregistering_during_fire_does_not_skip_queued():
    h = AgentLifecycleHooks()
    calls = []
    handle_b = None

    def first():
        calls.append("first")
        if handle_b is not None:
            h.unregister(handle_b)

    h.register("evt", first, priority=10)
    handle_b = h.register("evt", lambda: calls.append("second"), priority=100)
    h.fire("evt")
    assert calls == ["first", "second"]  # second already in snapshot, still fires


def test_nested_fire_terminates():
    """Callback fires another transition — should not infinite-loop."""
    h = AgentLifecycleHooks()
    calls = []

    def outer():
        calls.append("outer")
        h.fire("inner")

    h.register("outer", outer)
    h.register("inner", lambda: calls.append("inner"))
    h.fire("outer")
    assert calls == ["outer", "inner"]


# ── Snapshot ─────────────────────────────────────────────────────────────────

def test_snapshot_returns_registration_names():
    h = AgentLifecycleHooks()
    h.register("on_turn_start", lambda: None, name="reset_turn")
    h.register("on_turn_start", lambda: None, name="osc_start")
    snap = h.snapshot()
    assert "on_turn_start" in snap
    assert snap["on_turn_start"] == ["reset_turn", "osc_start"]
