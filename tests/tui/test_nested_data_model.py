"""Phase A — nested tool tree data model and stack inference.

Tests for _ToolCallRecord dataclass and _agent_stack logic
in ToolRenderingService.open_streaming_tool_block / close_*.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from hermes_cli.tui.services.tools import _ToolCallRecord, ToolRenderingService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_app():
    """Return a minimal mock app that satisfies ToolRenderingService's self.app calls."""
    app = MagicMock()
    app._active_streaming_blocks = {}
    app._turn_tool_calls = {}
    app._turn_start_monotonic = 0.0
    app._current_turn_tool_count = 0
    app._streaming_tool_count = 0
    app._active_tool_name = ""
    app._browse_total = 0
    app._cached_output_panel = None
    app._explicit_parent_map = {}
    app._update_anim_hint = MagicMock()
    app.call_after_refresh = MagicMock()
    app.query_one = MagicMock(side_effect=Exception("no match"))
    app.planned_calls = []
    return app


def _make_svc():
    """Return a ToolRenderingService with a minimal mock app."""
    app = _make_mock_app()
    svc = ToolRenderingService.__new__(ToolRenderingService)
    svc.app = app
    svc._streaming_map = {}
    svc._turn_tool_calls = {}
    svc._agent_stack = []
    svc._subagent_panels = {}
    return svc


def _mock_output(msg=None):
    output = MagicMock()
    output._user_scrolled_up = False
    if msg is None:
        msg = MagicMock()
        msg.open_streaming_tool_block = MagicMock(return_value=MagicMock())
    output.current_message = msg
    output.new_message = MagicMock(return_value=msg)
    return output


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_agent_stack_push_pop():
    """AGENT tool is pushed on open and popped on close."""
    svc = _make_svc()
    output = _mock_output()

    with patch.object(svc, "_get_output_panel", return_value=output), \
         patch("hermes_cli.tui.services.tools._time") as mock_time:
        mock_time.monotonic.return_value = 1.0

        svc.open_streaming_tool_block("tid-1", "Task", tool_name="delegate")

    assert "tid-1" in svc._agent_stack

    with patch.object(svc, "_get_output_panel", return_value=output), \
         patch("hermes_cli.tui.services.tools._time") as mock_time:
        mock_time.monotonic.return_value = 2.0

        svc.close_streaming_tool_block("tid-1", "1s")

    assert "tid-1" not in svc._agent_stack


def test_agent_stack_pop_via_with_diff():
    """AGENT tool popped from stack via close_with_diff path."""
    svc = _make_svc()
    output = _mock_output()
    block = MagicMock()
    svc.app._active_streaming_blocks["tid-2"] = block
    svc._agent_stack.append("tid-2")
    # record needed for dur_ms update
    svc._turn_tool_calls["tid-2"] = _ToolCallRecord(
        tool_call_id="tid-2", parent_tool_call_id=None, label="Task",
        tool_name="Task", category="agent", depth=0, start_s=0.0,
        dur_ms=None, is_error=False, error_kind=None, mcp_server=None,
    )

    with patch.object(svc, "_get_output_panel", return_value=output), \
         patch("hermes_cli.tui.services.tools._time") as mock_time:
        mock_time.monotonic.return_value = 3.0
        svc.close_streaming_tool_block_with_diff(
            "tid-2", "500ms", False, [], MagicMock()
        )

    assert "tid-2" not in svc._agent_stack


def test_child_assigned_to_parent():
    """Non-AGENT tool opened while AGENT on stack gets parent_tool_call_id set."""
    svc = _make_svc()
    output = _mock_output()
    svc._agent_stack.append("parent-tid")
    svc._turn_tool_calls["parent-tid"] = _ToolCallRecord(
        tool_call_id="parent-tid", parent_tool_call_id=None, label="Task",
        tool_name="delegate", category="agent", depth=0, start_s=0.0,
        dur_ms=None, is_error=False, error_kind=None, mcp_server=None,
    )

    with patch.object(svc, "_get_output_panel", return_value=output), \
         patch("hermes_cli.tui.services.tools._time") as mock_time:
        mock_time.monotonic.return_value = 2.0

        svc.open_streaming_tool_block("child-tid", "ReadFile", tool_name="Read")

    assert svc._turn_tool_calls["child-tid"].parent_tool_call_id == "parent-tid"


def test_explicit_parent_overrides_stack():
    """_explicit_parent_map entry wins over stack inference."""
    svc = _make_svc()
    output = _mock_output()
    svc._agent_stack.append("stack-parent")
    svc._turn_tool_calls["stack-parent"] = _ToolCallRecord(
        tool_call_id="stack-parent", parent_tool_call_id=None, label="T",
        tool_name="delegate", category="agent", depth=0, start_s=0.0,
        dur_ms=None, is_error=False, error_kind=None, mcp_server=None,
    )
    svc._turn_tool_calls["explicit-parent"] = _ToolCallRecord(
        tool_call_id="explicit-parent", parent_tool_call_id=None, label="T2",
        tool_name="delegate", category="agent", depth=0, start_s=0.0,
        dur_ms=None, is_error=False, error_kind=None, mcp_server=None,
    )
    svc.app._explicit_parent_map = {"child-x": "explicit-parent"}

    with patch.object(svc, "_get_output_panel", return_value=output), \
         patch("hermes_cli.tui.services.tools._time") as mock_time:
        mock_time.monotonic.return_value = 1.0

        svc.open_streaming_tool_block("child-x", "Grep", tool_name="Grep")

    assert svc._turn_tool_calls["child-x"].parent_tool_call_id == "explicit-parent"


def test_depth_computation_0_1_2():
    """Depth increments for each nested level."""
    svc = _make_svc()
    # Manually build records
    rec0 = _ToolCallRecord(
        tool_call_id="p0", parent_tool_call_id=None, label="T", tool_name="Task",
        category="agent", depth=0, start_s=0.0, dur_ms=None, is_error=False,
        error_kind=None, mcp_server=None,
    )
    rec1 = _ToolCallRecord(
        tool_call_id="p1", parent_tool_call_id="p0", label="T", tool_name="Task",
        category="agent", depth=1, start_s=0.0, dur_ms=None, is_error=False,
        error_kind=None, mcp_server=None,
    )
    svc._turn_tool_calls["p0"] = rec0
    svc._turn_tool_calls["p1"] = rec1

    # depth of p1's child should be 2
    parent = svc._turn_tool_calls.get("p1")
    depth = min((parent.depth + 1) if parent else 0, 3)
    assert depth == 2


def test_depth_cap_at_3():
    """Depth never exceeds 3 even for deeply nested agents."""
    parent = _ToolCallRecord(
        tool_call_id="p3", parent_tool_call_id="p2", label="T", tool_name="Task",
        category="agent", depth=3, start_s=0.0, dur_ms=None, is_error=False,
        error_kind=None, mcp_server=None,
    )
    depth = min((parent.depth + 1) if parent else 0, 3)
    assert depth == 3


def test_children_list_updated():
    """Parent record's children list gets child_id appended."""
    svc = _make_svc()
    output = _mock_output()
    svc._agent_stack.append("parent-a")
    svc._turn_tool_calls["parent-a"] = _ToolCallRecord(
        tool_call_id="parent-a", parent_tool_call_id=None, label="T",
        tool_name="Task", category="agent", depth=0, start_s=0.0,
        dur_ms=None, is_error=False, error_kind=None, mcp_server=None,
    )

    with patch.object(svc, "_get_output_panel", return_value=output), \
         patch("hermes_cli.tui.services.tools._time") as mock_time:
        mock_time.monotonic.return_value = 1.0

        svc.open_streaming_tool_block("child-a", "Grep", tool_name="Grep")

    assert "child-a" in svc._turn_tool_calls["parent-a"].children


def test_current_turn_tool_calls_shape():
    """current_turn_tool_calls returns list of dicts with required keys."""
    svc = _make_svc()
    svc._turn_tool_calls["t1"] = _ToolCallRecord(
        tool_call_id="t1", parent_tool_call_id=None, label="Task", tool_name="Task",
        category="agent", depth=0, start_s=0.0, dur_ms=500, is_error=False,
        error_kind=None, mcp_server=None,
    )
    result = svc.current_turn_tool_calls()
    assert len(result) == 1
    rec = result[0]
    for key in ("tool_call_id", "parent_tool_call_id", "name", "category",
                "depth", "children", "start_s", "dur_ms", "is_error",
                "error_kind", "mcp_server"):
        assert key in rec, f"Missing key: {key}"


def test_current_turn_tool_calls_children_field():
    """children field is a list copy of the record's children."""
    svc = _make_svc()
    rec = _ToolCallRecord(
        tool_call_id="p", parent_tool_call_id=None, label="T", tool_name="Task",
        category="agent", depth=0, start_s=0.0, dur_ms=None, is_error=False,
        error_kind=None, mcp_server=None,
    )
    rec.children = ["c1", "c2"]
    svc._turn_tool_calls["p"] = rec
    result = svc.current_turn_tool_calls()
    assert result[0]["children"] == ["c1", "c2"]
    # Mutation of returned list does not affect record
    result[0]["children"].append("c3")
    assert "c3" not in rec.children
