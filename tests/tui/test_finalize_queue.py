"""Tests for hermes_cli/tui/finalize_queue.py — deferred finalize queue."""
from __future__ import annotations

import pytest

import hermes_cli.tui.finalize_queue as fq


def _reset():
    """Clear the module-level queue between tests."""
    fq._queue.clear()


# ---------------------------------------------------------------------------
# enqueue_finalize()
# ---------------------------------------------------------------------------

def test_enqueue_adds_to_queue():
    _reset()
    fq.enqueue_finalize(lambda: None)
    assert fq.queue_depth() == 1


def test_enqueue_multiple_items_preserves_order():
    _reset()
    order = []
    fq.enqueue_finalize(lambda: order.append(1))
    fq.enqueue_finalize(lambda: order.append(2))
    fq.enqueue_finalize(lambda: order.append(3))
    assert fq.queue_depth() == 3
    fq.drain_all()
    assert order == [1, 2, 3]


def test_enqueue_runs_inline_when_queue_full():
    """When queue depth >= MAX_DEPTH, enqueue runs the closure inline."""
    _reset()
    # Fill the queue to MAX_DEPTH with no-ops
    for _ in range(fq.MAX_DEPTH):
        fq.enqueue_finalize(lambda: None)
    assert fq.queue_depth() == fq.MAX_DEPTH

    called = []
    fq.enqueue_finalize(lambda: called.append(True))
    # The closure should have been called immediately (inline)
    assert called == [True]
    # Queue depth must not exceed MAX_DEPTH
    assert fq.queue_depth() == fq.MAX_DEPTH


def test_enqueue_inline_exception_does_not_propagate():
    """Inline execution (backpressure path) swallows exceptions."""
    _reset()
    for _ in range(fq.MAX_DEPTH):
        fq.enqueue_finalize(lambda: None)

    def _bad():
        raise ValueError("boom")

    # Should not raise
    fq.enqueue_finalize(_bad)


# ---------------------------------------------------------------------------
# drain_one()
# ---------------------------------------------------------------------------

def test_drain_one_returns_false_when_empty():
    _reset()
    assert fq.drain_one() is False


def test_drain_one_returns_true_when_item_present():
    _reset()
    fq.enqueue_finalize(lambda: None)
    assert fq.drain_one() is True


def test_drain_one_runs_oldest_closure_first():
    _reset()
    order = []
    fq.enqueue_finalize(lambda: order.append("first"))
    fq.enqueue_finalize(lambda: order.append("second"))
    fq.drain_one()
    assert order == ["first"]
    assert fq.queue_depth() == 1


def test_drain_one_decrements_depth():
    _reset()
    fq.enqueue_finalize(lambda: None)
    fq.enqueue_finalize(lambda: None)
    fq.drain_one()
    assert fq.queue_depth() == 1


def test_drain_one_swallows_exception():
    _reset()
    fq.enqueue_finalize(lambda: (_ for _ in ()).throw(RuntimeError("oops")))
    # Should not raise
    result = fq.drain_one()
    assert result is True
    assert fq.queue_depth() == 0


# ---------------------------------------------------------------------------
# drain_all()
# ---------------------------------------------------------------------------

def test_drain_all_returns_zero_when_empty():
    _reset()
    assert fq.drain_all() == 0


def test_drain_all_drains_everything():
    _reset()
    for _ in range(5):
        fq.enqueue_finalize(lambda: None)
    count = fq.drain_all()
    assert count == 5
    assert fq.queue_depth() == 0


def test_drain_all_runs_all_closures():
    _reset()
    results = []
    for i in range(4):
        val = i
        fq.enqueue_finalize(lambda v=val: results.append(v))
    fq.drain_all()
    assert sorted(results) == [0, 1, 2, 3]


def test_drain_all_swallows_exceptions():
    _reset()
    fq.enqueue_finalize(lambda: (_ for _ in ()).throw(RuntimeError("a")))
    fq.enqueue_finalize(lambda: (_ for _ in ()).throw(RuntimeError("b")))
    count = fq.drain_all()
    assert count == 2
    assert fq.queue_depth() == 0


# ---------------------------------------------------------------------------
# queue_depth()
# ---------------------------------------------------------------------------

def test_queue_depth_zero_initially():
    _reset()
    assert fq.queue_depth() == 0


def test_queue_depth_increments_on_enqueue():
    _reset()
    fq.enqueue_finalize(lambda: None)
    fq.enqueue_finalize(lambda: None)
    assert fq.queue_depth() == 2


def test_queue_depth_decrements_on_drain():
    _reset()
    fq.enqueue_finalize(lambda: None)
    fq.enqueue_finalize(lambda: None)
    fq.drain_one()
    assert fq.queue_depth() == 1


# ---------------------------------------------------------------------------
# MAX_DEPTH boundary
# ---------------------------------------------------------------------------

def test_max_depth_constant_is_64():
    assert fq.MAX_DEPTH == 64


def test_item_at_max_depth_minus_one_is_enqueued_not_inline():
    """Item at exactly MAX_DEPTH - 1 queue length is enqueued, not run inline."""
    _reset()
    for _ in range(fq.MAX_DEPTH - 1):
        fq.enqueue_finalize(lambda: None)
    called = []
    fq.enqueue_finalize(lambda: called.append(True))
    # Should be queued, not called inline
    assert called == []
    assert fq.queue_depth() == fq.MAX_DEPTH
