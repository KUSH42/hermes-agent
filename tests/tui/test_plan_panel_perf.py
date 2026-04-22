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
    from unittest.mock import MagicMock
    from hermes_cli.tui.services.tools import ToolRenderingService

    mock_app = MagicMock()
    mock_app.planned_calls = []
    mock_app._turn_tool_calls = {}
    mock_app._active_streaming_blocks = {}
    mock_app._streaming_tool_count = 0
    mock_app._agent_stack = []
    mock_app._turn_start_monotonic = None
    mock_app._browse_total = 0
    mock_app._current_turn_tool_count = 0
    mock_app._cached_output_panel = None
    mock_app.query_one = MagicMock(side_effect=Exception)
    mock_app.call_after_refresh = MagicMock()

    svc = ToolRenderingService.__new__(ToolRenderingService)
    svc.app = mock_app
    svc._streaming_map = {}
    svc._turn_tool_calls = {}
    svc._agent_stack = []
    svc._subagent_panels = {}

    class _Proxy:
        @property
        def planned_calls(self):
            return mock_app.planned_calls

        @planned_calls.setter
        def planned_calls(self, v):
            mock_app.planned_calls = v

        def set_plan_batch(self, batch):
            return svc.set_plan_batch(batch)

        def mark_plan_running(self, tid):
            return svc.mark_plan_running(tid)

        def mark_plan_done(self, tid, is_error, dur_ms):
            return svc.mark_plan_done(tid, is_error, dur_ms)

    return _Proxy()


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
