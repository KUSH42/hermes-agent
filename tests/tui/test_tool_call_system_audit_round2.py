"""Tests for the Round 2 system-audit follow-up spec.

Covers:
    TestTerminalCleanupHelper      — R2-HIGH-01: _terminalize_tool_view + cancel/remove/close routing
    TestAdoptionIdentityBackfill   — R2-HIGH-02: block + DOM panel id backfill on adoption
    TestNameplateRound2            — R2-MED-01: _on_error_set + _MORPH_TICKS

See spec: 2026-04-25-tool-call-system-audit-followup-round2-spec.md
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.services.tools import (
    ToolCallState,
    ToolCallViewState,
    ToolRenderingService,
)
from hermes_cli.tui.plan_types import PlannedCall, PlanState
from hermes_cli.tui.tool_panel.density import DensityTier


# ---------------------------------------------------------------------------
# Helpers
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
    svc._state_lock = threading.RLock()
    from hermes_cli.tui.services.plan_sync import PlanSyncBroker
    svc._plan_broker = PlanSyncBroker(svc)
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


def _seed_plan(svc, tool_call_id, state, tool_name="test"):
    pc = PlannedCall(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        label=tool_name,
        category="unknown",
        args_preview="",
        state=state,
        started_at=None,
        ended_at=None,
        parent_tool_call_id=None,
        depth=0,
    )
    svc.app.planned_calls = list(svc.app.planned_calls) + [pc]


# ---------------------------------------------------------------------------
# R2-HIGH-01 — terminal cleanup helper
# ---------------------------------------------------------------------------

class TestTerminalCleanupHelper:
    """Helper underwrites remove_streaming_tool_block, cancel_tool_call, close_streaming_tool_block."""

    def test_remove_streaming_tool_block_decrements_open_count_and_phase(self):
        from hermes_cli.tui.agent_phase import Phase

        svc = _make_service()
        view = _make_view(state=ToolCallState.STREAMING)
        svc._tool_views_by_id["tid-1"] = view
        svc.app._active_streaming_blocks["tid-1"] = view.block
        svc.app._streaming_tool_count = 1
        svc._open_tool_count = 1

        with patch.object(svc, "_panel_for_block", return_value=None):
            svc.remove_streaming_tool_block("tid-1")

        assert svc._open_tool_count == 0
        assert svc.app.status_phase == Phase.REASONING
        assert "tid-1" not in svc._tool_views_by_id

    def test_cancel_started_tool_marks_plan_cancelled_and_decrements(self):
        svc = _make_service()
        view = _make_view(state=ToolCallState.STARTED)
        svc._tool_views_by_id["tid-1"] = view
        svc._open_tool_count = 1
        _seed_plan(svc, "tid-1", PlanState.RUNNING)

        with patch.object(svc, "_panel_for_block", return_value=None):
            svc.cancel_tool_call(tool_call_id="tid-1")

        # Plan row CANCELLED
        rows = list(svc.app.planned_calls)
        assert rows[0].state == PlanState.CANCELLED
        # Counter decremented (locks the H2 regression)
        assert svc._open_tool_count == 0
        # View terminal state stamped via axis bus
        assert view.state == ToolCallState.CANCELLED

    def test_cancel_clears_active_maps_and_agent_stack(self):
        svc = _make_service()
        view = _make_view(state=ToolCallState.STREAMING)
        svc._tool_views_by_id["tid-1"] = view
        svc._agent_stack.append("tid-1")
        svc.app._active_streaming_blocks["tid-1"] = view.block

        with patch.object(svc, "_panel_for_block", return_value=None):
            svc.cancel_tool_call(tool_call_id="tid-1")

        assert "tid-1" not in svc._tool_views_by_id
        assert "tid-1" not in svc._agent_stack
        assert "tid-1" not in svc.app._active_streaming_blocks

    def test_close_with_other_tools_open_keeps_active_tool_name(self):
        """When closing Tool A but Tool B (`tool_name='read_file'`, label='Read') is still
        running and is the active tool, _active_tool_name must remain 'read_file'.
        Locks step 5(a): keys on view.tool_name (raw), not view.label.
        """
        svc = _make_service()
        # Tool A — being closed
        view_a = _make_view(tool_call_id="A", tool_name="execute_code", state=ToolCallState.STREAMING)
        # Tool B — still running, is active
        view_b = _make_view(tool_call_id="B", tool_name="read_file", label="Read",
                            state=ToolCallState.STREAMING)
        svc._tool_views_by_id["A"] = view_a
        svc._tool_views_by_id["B"] = view_b
        svc.app._active_streaming_blocks["A"] = view_a.block
        svc.app._active_streaming_blocks["B"] = view_b.block
        svc._open_tool_count = 2
        svc.app._active_tool_name = "read_file"  # Tool B is the active one

        # Drive the close path directly — block.complete is mocked
        view_a.block.complete = MagicMock()
        with patch.object(svc, "_get_output_panel", return_value=None):
            svc.close_streaming_tool_block("A", duration="120ms", is_error=False)

        assert svc.app._active_tool_name == "read_file"
        assert svc._open_tool_count == 1

    def test_close_idempotent_after_remove(self):
        """remove then close decrements _open_tool_count exactly once total."""
        svc = _make_service()
        view = _make_view(state=ToolCallState.STREAMING)
        svc._tool_views_by_id["tid-1"] = view
        svc.app._active_streaming_blocks["tid-1"] = view.block
        svc._open_tool_count = 1

        with patch.object(svc, "_panel_for_block", return_value=None):
            svc.remove_streaming_tool_block("tid-1")

        assert svc._open_tool_count == 0

        # close after remove — block already gone, no double-decrement
        with patch.object(svc, "_get_output_panel", return_value=None):
            svc.close_streaming_tool_block("tid-1", duration="0ms", is_error=False)

        assert svc._open_tool_count == 0

    def test_cancel_via_gen_index_only_pops_gen_map(self):
        svc = _make_service()
        view = _make_view(
            tool_call_id=None,
            gen_index=2,
            state=ToolCallState.GENERATED,
        )
        svc._tool_views_by_gen_index[2] = view
        svc._open_tool_count = 0  # GENERATED never incremented

        with patch.object(svc, "_panel_for_block", return_value=None):
            svc.cancel_tool_call(gen_index=2)

        # Counter unchanged (prev_state=GENERATED is not in _inflight)
        assert svc._open_tool_count == 0
        # Gen map popped
        assert 2 not in svc._tool_views_by_gen_index
        # Visual remove attempted
        view.block.remove.assert_called()

    def test_complete_unknown_id_mark_plan_still_fires(self):
        """complete_tool_call on an unknown id → close path early-returns at
        block-is-None guard; mark_plan_done still fires from complete_tool_call,
        helper not invoked, _open_tool_count unchanged.
        """
        svc = _make_service()
        svc._open_tool_count = 0
        # No view, no active streaming block

        with patch.object(svc, "_terminalize_tool_view") as helper, \
             patch.object(svc, "mark_plan_done") as plan_done:
            svc.complete_tool_call(
                "ghost",
                tool_name="nope",
                args={},
                raw_result="",
                is_error=False,
                summary=None,
            )

        # Helper not invoked for ghost id (close_streaming_tool_block returns
        # early at "if block is None: return")
        helper.assert_not_called()
        # Plan still marked done
        plan_done.assert_called_once()
        assert svc._open_tool_count == 0


# ---------------------------------------------------------------------------
# R2-HIGH-02 — backfill block + DOM panel id on adoption
# ---------------------------------------------------------------------------

class TestAdoptionIdentityBackfill:
    """start_tool_call() adopting a generated panel must backfill identity."""

    def _adopt(self, svc, *, query_returns_existing: bool):
        """Drive start_tool_call through the adoption branch with mocks."""
        # Pre-create a GENERATED view with a block + panel
        block = MagicMock(spec=["finalize_code", "set_final_path", "_tool_call_id", "remove", "parent"])
        block._tool_call_id = None
        panel = MagicMock(spec=["_plan_tool_call_id", "id", "refresh"])
        panel.id = "gen-7"
        panel._plan_tool_call_id = None

        view = ToolCallViewState(
            tool_call_id=None,
            gen_index=7,
            tool_name="web_search",
            label="Search",
            args={},
            state=ToolCallState.GENERATED,
            block=block,
            panel=panel,
            parent_tool_call_id=None,
            category="research_tools",
            depth=0,
            start_s=0.0,
        )
        svc._tool_views_by_gen_index[7] = view

        # app.query — empty unless query_returns_existing
        if query_returns_existing:
            svc.app.query.return_value = [MagicMock()]
        else:
            svc.app.query.return_value = []

        # Stub helpers used in adopted path
        with patch.object(svc, "_panel_for_block", return_value=panel), \
             patch.object(svc, "_pop_pending_gen_for", return_value=view), \
             patch.object(svc, "_compute_parent_depth", return_value=(None, 0)), \
             patch.object(svc, "_wire_args"), \
             patch.object(svc, "mark_plan_running"):
            svc.start_tool_call("tid-XYZ", "web_search", {"query": "hi"})

        return view, block, panel

    def test_adoption_sets_block_tool_call_id(self):
        svc = _make_service()
        view, block, panel = self._adopt(svc, query_returns_existing=False)
        assert block._tool_call_id == "tid-XYZ"

    def test_adoption_updates_panel_dom_id_when_no_collision(self):
        svc = _make_service()
        view, block, panel = self._adopt(svc, query_returns_existing=False)
        assert panel.id == "tool-tid-XYZ"
        panel.refresh.assert_called()

    def test_adoption_keeps_panel_id_on_collision(self):
        svc = _make_service()
        view, block, panel = self._adopt(svc, query_returns_existing=True)
        # panel.id remained gen-7 (collision detected)
        assert panel.id == "gen-7"


# ---------------------------------------------------------------------------
# R2-MED-01 — nameplate _on_error_set + _MORPH_TICKS
# ---------------------------------------------------------------------------

class TestNameplateRound2:
    """_on_error_set must call _stop_timer (not the missing _pulse_stop), and
    morph transitions must use _MORPH_TICKS (~250 ms) rather than _DECRYPT_TICKS (5 s).
    """

    def _make_np(self, **kwargs):
        from hermes_cli.tui.widgets import AssistantNameplate
        kw = dict(name="Hermes", effects_enabled=False)
        kw.update(kwargs)
        np = AssistantNameplate(**kw)
        np._effects_enabled = kw.get("effects_enabled", False)
        return np

    def test_on_error_set_calls_stop_timer_not_pulse_stop(self):
        from hermes_cli.tui.widgets import AssistantNameplate

        np = self._make_np()
        # Ensure _pulse_stop is not present (it never was — bug confirmed).
        assert not hasattr(AssistantNameplate, "_pulse_stop")

        with patch.object(np, "_stop_timer") as stop_timer, \
             patch.object(np, "refresh"):
            np._on_error_set()

        stop_timer.assert_called_once()
        assert np.has_class("--error")
        assert not np.has_class("--active")
        assert not np.has_class("--idle")

    def test_on_error_set_logs_on_unexpected_failure(self, monkeypatch):
        np = self._make_np()
        # Force add_class to raise
        monkeypatch.setattr(np, "add_class", MagicMock(side_effect=RuntimeError("boom")))

        mock_log = MagicMock()
        monkeypatch.setattr("hermes_cli.tui.widgets._LOG", mock_log)

        # Must not raise
        np._on_error_set()

        # Log called with exc_info=True
        assert mock_log.debug.called
        kwargs = mock_log.debug.call_args.kwargs
        assert kwargs.get("exc_info") is True

    def test_morph_ticks_constant_distinct_from_decrypt_ticks(self):
        from hermes_cli.tui.widgets import AssistantNameplate
        assert AssistantNameplate._MORPH_TICKS != AssistantNameplate._DECRYPT_TICKS
        assert AssistantNameplate._MORPH_TICKS < 30  # well under 1s @ 30fps

    def test_active_morph_tick_base_uses_morph_ticks(self):
        from hermes_cli.tui.widgets import AssistantNameplate

        np = self._make_np(morph_speed=1.0)
        np._target_name = "Hermes"
        np._active_label = "● thinking"
        # Drive _init_morph for the active-target morph
        np._init_morph(np._target_name, np._active_label)

        # Per-character tick targets reside in _morph_dissolve. Each has the
        # _random.randint(-2, 2) jitter applied; assert all within ±2 of MORPH_TICKS
        # AND strictly less than _DECRYPT_TICKS.
        morph_ticks = AssistantNameplate._MORPH_TICKS
        decrypt_ticks = AssistantNameplate._DECRYPT_TICKS
        for ticks in np._morph_dissolve:
            assert morph_ticks - 2 <= ticks <= morph_ticks + 2
            assert ticks < decrypt_ticks
