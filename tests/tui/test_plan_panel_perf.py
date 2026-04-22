"""tests/tui/test_plan_panel_perf.py — PlanPanel performance tests (Phase 5, 3 tests)."""
from __future__ import annotations

import time

import pytest

from hermes_cli.tui.plan_types import PlannedCall, PlanState


def _make_batch(n: int) -> "list[tuple[str, str, str, dict]]":
    """Build a batch of n tool calls."""
    return [
        (f"id{i}", "terminal", f"cmd_{i}", {"command": f"cmd_{i}"})
        for i in range(n)
    ]


def _make_app_stub():
    from hermes_cli.tui._app_tool_rendering import _ToolRenderingMixin

    class _StubApp(_ToolRenderingMixin):
        planned_calls = []
        _turn_tool_calls = {}
        _active_streaming_blocks = {}
        _streaming_tool_count = 0
        _agent_stack = []
        _turn_start_monotonic = None
        _browse_total = 0
        _current_turn_tool_count = 0
        _cached_output_panel = None

        def query_one(self, *a, **kw):
            raise Exception

        def call_after_refresh(self, *a, **kw):
            pass

    return _StubApp()


# T1: set_plan_batch on 20 items completes in < 50ms
def test_set_plan_batch_20_items_perf():
    app = _make_app_stub()
    batch = _make_batch(20)
    start = time.monotonic()
    app.set_plan_batch(batch)
    elapsed_ms = (time.monotonic() - start) * 1000
    assert elapsed_ms < 50, f"set_plan_batch took {elapsed_ms:.1f}ms (expected < 50ms)"


# T2: 20 mark_plan_running calls complete in < 100ms
def test_mark_plan_running_20_items_perf():
    app = _make_app_stub()
    batch = _make_batch(20)
    app.set_plan_batch(batch)
    start = time.monotonic()
    for i in range(20):
        app.mark_plan_running(f"id{i}")
    elapsed_ms = (time.monotonic() - start) * 1000
    assert elapsed_ms < 100, f"20x mark_plan_running took {elapsed_ms:.1f}ms (expected < 100ms)"


# T3: 20 mark_plan_done calls complete in < 100ms
def test_mark_plan_done_20_items_perf():
    app = _make_app_stub()
    batch = _make_batch(20)
    app.set_plan_batch(batch)
    for i in range(20):
        app.mark_plan_running(f"id{i}")
    start = time.monotonic()
    for i in range(20):
        app.mark_plan_done(f"id{i}", is_error=False, dur_ms=10)
    elapsed_ms = (time.monotonic() - start) * 1000
    assert elapsed_ms < 100, f"20x mark_plan_done took {elapsed_ms:.1f}ms (expected < 100ms)"
