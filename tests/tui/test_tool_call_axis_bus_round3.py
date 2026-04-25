"""R3-AXIS-01 / R3-AXIS-02 / R3-AXIS-03 — Audit Round 3 Spec A: Axis-Bus Holes.

Routes three remaining direct-write sites in services/tools.py through the
axis bus so view-state watchers see every transition.

See spec: 2026-04-25-tool-call-system-audit-round3-axis-spec.md
"""
from __future__ import annotations

import logging
import time
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.services.tools import (
    ToolCallState,
    ToolCallViewState,
    ToolRenderingService,
    add_axis_watcher,
)


# ---------------------------------------------------------------------------
# Helpers (mirrors test_tool_call_system_audit_round2.py)
# ---------------------------------------------------------------------------

def _make_mock_app(**kwargs):
    app = MagicMock()
    app._active_streaming_blocks = {}
    app._streaming_tool_count = 0
    app._browse_total = 0
    app.planned_calls = []
    app.agent_running = True
    app._turn_start_monotonic = time.monotonic()
    app._explicit_parent_map = {}
    app.status_phase = None
    app._active_tool_name = ""
    app._svc_commands = MagicMock()
    for k, v in kwargs.items():
        setattr(app, k, v)
    return app


def _make_service(app=None, **app_kwargs):
    if app is None:
        app = _make_mock_app(**app_kwargs)
    svc = ToolRenderingService.__new__(ToolRenderingService)
    svc.app = app
    svc._streaming_map = {}
    svc._turn_tool_calls = {}
    svc._agent_stack = []
    svc._subagent_panels = {}
    svc._open_tool_count = 0
    svc._tool_views_by_id = {}
    svc._tool_views_by_gen_index = {}
    svc._pending_gen_arg_deltas = {}
    return svc


def _make_view(
    *,
    tool_call_id="tid-1",
    gen_index=None,
    tool_name="read_file",
    label="Read",
    state=ToolCallState.STREAMING,
    block=None,
):
    if block is None:
        block = MagicMock()
        block.parent = None
    return ToolCallViewState(
        tool_call_id=tool_call_id,
        gen_index=gen_index,
        tool_name=tool_name,
        label=label,
        args={},
        state=state,
        block=block,
        panel=None,
        parent_tool_call_id=None,
        category="file_tools",
        depth=0,
        start_s=0.0,
    )


def _watcher_recorder():
    calls = []

    def watcher(view, axis, old, new):
        calls.append((view, axis, old, new))

    return watcher, calls


# ---------------------------------------------------------------------------
# R3-AXIS-01 — append_tool_output STARTED→STREAMING bypass
# ---------------------------------------------------------------------------

class TestR3Axis01AppendToolOutput:
    """append_tool_output must route the STARTED→STREAMING write through set_axis."""

    def test_append_tool_output_started_to_streaming_fires_axis_watcher(self):
        svc = _make_service()
        view = _make_view(state=ToolCallState.STARTED)
        svc._tool_views_by_id["tid-1"] = view
        # Wire an active streaming block so append_streaming_line sees it.
        svc.app._active_streaming_blocks["tid-1"] = view.block

        watcher, calls = _watcher_recorder()
        add_axis_watcher(view, watcher)

        with patch.object(svc, "_get_output_panel", return_value=None):
            svc.append_tool_output("tid-1", "first line\n")

        state_calls = [c for c in calls if c[1] == "state"]
        assert len(state_calls) == 1
        v, axis, old, new = state_calls[0]
        assert v is view
        assert axis == "state"
        assert old == ToolCallState.STARTED
        assert new == ToolCallState.STREAMING
        assert view.state == ToolCallState.STREAMING

    def test_append_tool_output_already_streaming_no_watcher(self):
        svc = _make_service()
        view = _make_view(state=ToolCallState.STREAMING)
        svc._tool_views_by_id["tid-1"] = view
        svc.app._active_streaming_blocks["tid-1"] = view.block

        watcher, calls = _watcher_recorder()
        add_axis_watcher(view, watcher)

        with patch.object(svc, "_get_output_panel", return_value=None):
            svc.append_tool_output("tid-1", "more output\n")

        # Same-value short-circuit: set_axis is a no-op, watcher silent.
        assert calls == []
        assert view.state == ToolCallState.STREAMING

    def test_append_tool_output_terminal_no_state_change(self):
        svc = _make_service()
        view = _make_view(state=ToolCallState.DONE)
        svc._tool_views_by_id["tid-1"] = view

        watcher, calls = _watcher_recorder()
        add_axis_watcher(view, watcher)

        svc.append_tool_output("tid-1", "stale line\n")

        assert calls == []
        assert view.state == ToolCallState.DONE


# ---------------------------------------------------------------------------
# R3-AXIS-02 — _cancel_first_pending_gen direct CANCELLED + bare-except
# ---------------------------------------------------------------------------

class TestR3Axis02CancelFirstPendingGen:
    """_cancel_first_pending_gen must delegate to _terminalize_tool_view."""

    def test_cancel_first_pending_gen_routes_through_helper(self):
        svc = _make_service()
        view = _make_view(
            tool_call_id=None,
            gen_index=3,
            tool_name="terminal",
            state=ToolCallState.GENERATED,
        )
        svc._tool_views_by_gen_index[3] = view

        with patch.object(svc, "_terminalize_tool_view") as helper:
            svc._cancel_first_pending_gen("terminal")

        helper.assert_called_once()
        kwargs = helper.call_args.kwargs
        assert kwargs["terminal_state"] == ToolCallState.CANCELLED
        assert kwargs["is_error"] is False
        assert kwargs["mark_plan"] is False
        assert kwargs["remove_visual"] is True
        assert kwargs["delete_view"] is False
        assert kwargs["view"] is view
        assert kwargs["gen_index"] == 3

    def test_cancel_first_pending_gen_fires_axis_watcher(self):
        svc = _make_service()
        view = _make_view(
            tool_call_id=None,
            gen_index=4,
            tool_name="terminal",
            state=ToolCallState.GENERATED,
        )
        svc._tool_views_by_gen_index[4] = view

        watcher, calls = _watcher_recorder()
        add_axis_watcher(view, watcher)

        with patch.object(svc, "_panel_for_block", return_value=None):
            svc._cancel_first_pending_gen("terminal")

        state_calls = [c for c in calls if c[1] == "state"]
        assert len(state_calls) == 1
        v, axis, old, new = state_calls[0]
        assert v is view
        assert old == ToolCallState.GENERATED
        assert new == ToolCallState.CANCELLED
        assert view.state == ToolCallState.CANCELLED
        assert 4 not in svc._tool_views_by_gen_index

    def test_cancel_first_pending_gen_no_match_no_helper_call(self):
        svc = _make_service()
        view = _make_view(
            tool_call_id=None,
            gen_index=5,
            tool_name="read_file",  # different tool
            state=ToolCallState.GENERATED,
        )
        svc._tool_views_by_gen_index[5] = view

        with patch.object(svc, "_terminalize_tool_view") as helper:
            svc._cancel_first_pending_gen("terminal")

        helper.assert_not_called()
        # Original entry untouched
        assert svc._tool_views_by_gen_index.get(5) is view
        assert view.state == ToolCallState.GENERATED

    def test_cancel_first_pending_gen_block_remove_failure_logged(self, caplog):
        svc = _make_service()
        block = MagicMock()
        block.remove = MagicMock(side_effect=RuntimeError("boom"))
        block.parent = None
        view = _make_view(
            tool_call_id=None,
            gen_index=6,
            tool_name="terminal",
            state=ToolCallState.GENERATED,
            block=block,
        )
        svc._tool_views_by_gen_index[6] = view

        # caplog defaults to WARNING; helper logs at DEBUG so we must opt in.
        caplog.set_level(logging.DEBUG, logger="hermes_cli.tui.services.tools")

        with patch.object(svc, "_panel_for_block", return_value=None):
            # No exception should propagate
            svc._cancel_first_pending_gen("terminal")

        debug_records = [
            r for r in caplog.records
            if r.levelname == "DEBUG"
            and "terminalize visual remove failed" in r.message
        ]
        assert len(debug_records) == 1
        assert debug_records[0].exc_info is not None
        # View popped from gen-index map by helper Step 11
        assert 6 not in svc._tool_views_by_gen_index


# ---------------------------------------------------------------------------
# R3-AXIS-03 — complete_tool_call redundant terminal write
# ---------------------------------------------------------------------------

class TestR3Axis03CompleteToolCall:
    """_terminalize_tool_view must own the view.is_error mirror; complete_tool_call no longer writes it."""

    def test_terminalize_helper_writes_view_is_error(self):
        svc = _make_service()
        view = _make_view(state=ToolCallState.STREAMING)
        svc._tool_views_by_id["tid-1"] = view
        svc.app._active_streaming_blocks["tid-1"] = view.block
        svc._open_tool_count = 1

        watcher, calls = _watcher_recorder()
        add_axis_watcher(view, watcher)

        with patch.object(svc, "_panel_for_block", return_value=None):
            svc._terminalize_tool_view(
                tool_call_id="tid-1",
                terminal_state=ToolCallState.ERROR,
                is_error=True,
                mark_plan=False,
                remove_visual=False,
                delete_view=False,
                view=view,
            )

        assert view.is_error is True
        assert view.state == ToolCallState.ERROR
        state_calls = [c for c in calls if c[1] == "state"]
        assert len(state_calls) == 1
        assert state_calls[0][3] == ToolCallState.ERROR

    def test_complete_tool_call_no_redundant_writes(self):
        from hermes_cli.tui.services import tools as tools_mod

        svc = _make_service()
        view = _make_view(state=ToolCallState.STARTED)
        # Force classifier-skip path: pre-stamp view.kind so
        # _stamp_kind_on_completing short-circuits at the kind-already-set guard,
        # yielding exactly two state-axis writes.
        sentinel_kind = MagicMock()
        view.kind = sentinel_kind
        svc._tool_views_by_id["tid-1"] = view
        svc.app._active_streaming_blocks["tid-1"] = view.block
        svc._open_tool_count = 1

        recorded: list[tuple] = []
        real_set_axis = tools_mod.set_axis

        def recording_set_axis(v, axis, value):
            recorded.append((v, axis, getattr(v, axis), value))
            real_set_axis(v, axis, value)

        view.block.complete = MagicMock()

        with patch.object(tools_mod, "set_axis", side_effect=recording_set_axis), \
             patch.object(svc, "_get_output_panel", return_value=None), \
             patch.object(svc, "mark_plan_done"):
            svc.complete_tool_call(
                tool_call_id="tid-1",
                tool_name="read_file",
                args={},
                raw_result="ok",
                is_error=False,
                summary=None,
                result_lines=["x"],
            )

        state_calls = [c for c in recorded if c[1] == "state"]
        # Exactly two state-axis writes: COMPLETING then DONE.
        # The deleted redundant block in complete_tool_call would have made a third
        # (same-value, would have short-circuited but still routed through set_axis
        # had the spec used set_axis there) — instead the prior code did a direct
        # attribute write, which never appeared on the bus at all. The assertion
        # locks the post-fix invariant: no fourth bus write, exactly two states.
        assert len(state_calls) == 2
        assert state_calls[0][3] == ToolCallState.COMPLETING
        assert state_calls[1][3] == ToolCallState.DONE
        assert view.state == ToolCallState.DONE
        assert view.is_error is False
        # Helper Step 11 popped the active-id index.
        assert "tid-1" not in svc._tool_views_by_id
