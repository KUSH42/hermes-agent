"""tests/tui/test_plan_state_transitions.py — _ToolRenderingMixin plan mutation tests (Phase 1).

Tests use a lightweight mock app object to call the mixin methods directly
on the event loop (via run_test pilot approach).
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app_stub():
    """Return a minimal stub that satisfies _ToolRenderingMixin self calls."""
    from hermes_cli.tui._app_tool_rendering import _ToolRenderingMixin
    from hermes_cli.tui.plan_types import PlanState

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
            raise Exception("NoMatches")

        def call_after_refresh(self, *a, **kw):
            pass

    return _StubApp()


# ---------------------------------------------------------------------------
# T1: set_plan_batch seeds PENDING entries
# ---------------------------------------------------------------------------
def test_set_plan_batch_seeds_pending():
    app = _make_app_stub()
    batch = [
        ("id1", "terminal", "ls", {"command": "ls"}),
        ("id2", "read_file", "README.md", {"path": "README.md"}),
    ]
    app.set_plan_batch(batch)
    assert len(app.planned_calls) == 2
    from hermes_cli.tui.plan_types import PlanState
    for call in app.planned_calls:
        assert call.state == PlanState.PENDING


# ---------------------------------------------------------------------------
# T2: set_plan_batch preserves DONE/ERROR entries from prior round
# ---------------------------------------------------------------------------
def test_set_plan_batch_preserves_done_entries():
    from hermes_cli.tui.plan_types import PlannedCall, PlanState
    import time

    app = _make_app_stub()
    done_call = PlannedCall(
        tool_call_id="old-1",
        tool_name="terminal",
        label="old cmd",
        category="shell",
        args_preview="",
        state=PlanState.DONE,
        started_at=time.monotonic() - 1,
        ended_at=time.monotonic(),
        parent_tool_call_id=None,
        depth=0,
    )
    app.planned_calls = [done_call]
    batch = [("new-1", "write_file", "out.txt", {"path": "out.txt"})]
    app.set_plan_batch(batch)
    ids = [c.tool_call_id for c in app.planned_calls]
    assert "old-1" in ids
    assert "new-1" in ids


# ---------------------------------------------------------------------------
# T3: set_plan_batch drops stale PENDING entries from prior round
# ---------------------------------------------------------------------------
def test_set_plan_batch_drops_stale_pending():
    from hermes_cli.tui.plan_types import PlannedCall, PlanState

    app = _make_app_stub()
    stale = PlannedCall(
        tool_call_id="stale-1",
        tool_name="terminal",
        label="stale",
        category="shell",
        args_preview="",
        state=PlanState.PENDING,
        started_at=None,
        ended_at=None,
        parent_tool_call_id=None,
        depth=0,
    )
    app.planned_calls = [stale]
    batch = [("fresh-1", "read_file", "a.py", {"path": "a.py"})]
    app.set_plan_batch(batch)
    ids = [c.tool_call_id for c in app.planned_calls]
    assert "stale-1" not in ids
    assert "fresh-1" in ids


# ---------------------------------------------------------------------------
# T4: mark_plan_running transitions PENDING → RUNNING
# ---------------------------------------------------------------------------
def test_mark_plan_running():
    from hermes_cli.tui.plan_types import PlanState

    app = _make_app_stub()
    batch = [("id1", "terminal", "ls", {"command": "ls"})]
    app.set_plan_batch(batch)
    app.mark_plan_running("id1")
    call = next(c for c in app.planned_calls if c.tool_call_id == "id1")
    assert call.state == PlanState.RUNNING
    assert call.started_at is not None


# ---------------------------------------------------------------------------
# T5: mark_plan_running is a no-op for unknown id
# ---------------------------------------------------------------------------
def test_mark_plan_running_unknown_id():
    app = _make_app_stub()
    batch = [("id1", "terminal", "ls", {"command": "ls"})]
    app.set_plan_batch(batch)
    original = list(app.planned_calls)
    app.mark_plan_running("nonexistent")
    # List replaced but content unchanged
    assert len(app.planned_calls) == len(original)
    assert app.planned_calls[0].tool_call_id == "id1"


# ---------------------------------------------------------------------------
# T6: mark_plan_done transitions RUNNING → DONE
# ---------------------------------------------------------------------------
def test_mark_plan_done():
    from hermes_cli.tui.plan_types import PlanState

    app = _make_app_stub()
    batch = [("id1", "terminal", "ls", {"command": "ls"})]
    app.set_plan_batch(batch)
    app.mark_plan_running("id1")
    app.mark_plan_done("id1", is_error=False, dur_ms=123)
    call = next(c for c in app.planned_calls if c.tool_call_id == "id1")
    assert call.state == PlanState.DONE
    assert call.ended_at is not None


# ---------------------------------------------------------------------------
# T7: mark_plan_done with is_error=True → ERROR
# ---------------------------------------------------------------------------
def test_mark_plan_done_error():
    from hermes_cli.tui.plan_types import PlanState

    app = _make_app_stub()
    batch = [("id1", "terminal", "bad_cmd", {"command": "bad_cmd"})]
    app.set_plan_batch(batch)
    app.mark_plan_running("id1")
    app.mark_plan_done("id1", is_error=True, dur_ms=50)
    call = next(c for c in app.planned_calls if c.tool_call_id == "id1")
    assert call.state == PlanState.ERROR


# ---------------------------------------------------------------------------
# T8: mutations produce new list objects (reactive watcher contract)
# ---------------------------------------------------------------------------
def test_mutations_produce_new_list_objects():
    app = _make_app_stub()
    original = app.planned_calls
    batch = [("id1", "terminal", "ls", {"command": "ls"})]
    app.set_plan_batch(batch)
    assert app.planned_calls is not original

    after_set = app.planned_calls
    app.mark_plan_running("id1")
    assert app.planned_calls is not after_set


# ---------------------------------------------------------------------------
# T9: multiple calls in batch — each transitions independently
# ---------------------------------------------------------------------------
def test_multiple_calls_independent_transitions():
    from hermes_cli.tui.plan_types import PlanState

    app = _make_app_stub()
    batch = [
        ("id1", "terminal", "cmd1", {"command": "cmd1"}),
        ("id2", "read_file", "file.py", {"path": "file.py"}),
    ]
    app.set_plan_batch(batch)
    app.mark_plan_running("id1")
    # id2 still PENDING
    call2 = next(c for c in app.planned_calls if c.tool_call_id == "id2")
    assert call2.state == PlanState.PENDING

    app.mark_plan_done("id1", is_error=False, dur_ms=0)
    call1 = next(c for c in app.planned_calls if c.tool_call_id == "id1")
    assert call1.state == PlanState.DONE


# ---------------------------------------------------------------------------
# T10: args_preview truncated to 60 chars
# ---------------------------------------------------------------------------
def test_args_preview_truncated():
    app = _make_app_stub()
    long_arg = "x" * 200
    batch = [("id1", "terminal", "cmd", {"command": long_arg})]
    app.set_plan_batch(batch)
    call = app.planned_calls[-1]  # the newly added one
    # preview should not exceed ~65 chars (60 + ellipsis + json overhead)
    assert len(call.args_preview) <= 65
