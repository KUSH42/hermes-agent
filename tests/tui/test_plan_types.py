"""tests/tui/test_plan_types.py — PlanState + PlannedCall unit tests (Phase 1)."""
from __future__ import annotations

import time

import pytest

from hermes_cli.tui.plan_types import PlannedCall, PlanState


# ---------------------------------------------------------------------------
# T1: PlanState has all required members
# ---------------------------------------------------------------------------
def test_plan_state_members():
    assert PlanState.PENDING == "pending"
    assert PlanState.RUNNING == "running"
    assert PlanState.DONE == "done"
    assert PlanState.ERROR == "error"
    assert PlanState.CANCELLED == "cancelled"
    assert PlanState.SKIPPED == "skipped"


# ---------------------------------------------------------------------------
# T2: PlannedCall is frozen (immutable)
# ---------------------------------------------------------------------------
def test_planned_call_frozen():
    call = PlannedCall(
        tool_call_id="id1",
        tool_name="terminal",
        label="ls",
        category="shell",
        args_preview='{"command": "ls"}',
        state=PlanState.PENDING,
        started_at=None,
        ended_at=None,
        parent_tool_call_id=None,
        depth=0,
    )
    with pytest.raises((AttributeError, TypeError)):
        call.state = PlanState.RUNNING  # type: ignore[misc]


# ---------------------------------------------------------------------------
# T3: as_running returns RUNNING with started_at set
# ---------------------------------------------------------------------------
def test_as_running_sets_state_and_started_at():
    before = time.monotonic()
    call = PlannedCall(
        tool_call_id="id2",
        tool_name="read_file",
        label="README.md",
        category="file",
        args_preview='{"path": "README.md"}',
        state=PlanState.PENDING,
        started_at=None,
        ended_at=None,
        parent_tool_call_id=None,
        depth=0,
    )
    running = call.as_running()
    after = time.monotonic()
    assert running.state == PlanState.RUNNING
    assert running.started_at is not None
    assert before <= running.started_at <= after
    # Other fields unchanged
    assert running.tool_call_id == "id2"
    assert running.ended_at is None


# ---------------------------------------------------------------------------
# T4: as_done returns DONE with ended_at set
# ---------------------------------------------------------------------------
def test_as_done_sets_state_and_ended_at():
    call = PlannedCall(
        tool_call_id="id3",
        tool_name="terminal",
        label="git status",
        category="shell",
        args_preview="",
        state=PlanState.RUNNING,
        started_at=time.monotonic(),
        ended_at=None,
        parent_tool_call_id=None,
        depth=0,
    )
    done = call.as_done(is_error=False)
    assert done.state == PlanState.DONE
    assert done.ended_at is not None


# ---------------------------------------------------------------------------
# T5: as_done with is_error=True yields ERROR state
# ---------------------------------------------------------------------------
def test_as_done_error():
    call = PlannedCall(
        tool_call_id="id4",
        tool_name="terminal",
        label="failing_cmd",
        category="shell",
        args_preview="",
        state=PlanState.RUNNING,
        started_at=time.monotonic(),
        ended_at=None,
        parent_tool_call_id=None,
        depth=0,
    )
    error = call.as_done(is_error=True)
    assert error.state == PlanState.ERROR


# ---------------------------------------------------------------------------
# T6: PlannedCall preserves all fields through transitions
# ---------------------------------------------------------------------------
def test_fields_preserved_through_transitions():
    call = PlannedCall(
        tool_call_id="abc",
        tool_name="write_file",
        label="output.txt",
        category="file",
        args_preview='{"path": "output.txt"}',
        state=PlanState.PENDING,
        started_at=None,
        ended_at=None,
        parent_tool_call_id="parent-1",
        depth=1,
    )
    running = call.as_running()
    done = running.as_done()
    assert done.tool_call_id == "abc"
    assert done.tool_name == "write_file"
    assert done.label == "output.txt"
    assert done.category == "file"
    assert done.parent_tool_call_id == "parent-1"
    assert done.depth == 1
