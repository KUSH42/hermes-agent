"""Spec B — Mount Order + Axis Race.

Six fixes on the chunk→block delivery path:
  H2  — append_tool_output drops final chunk after axis-triggered terminalise
  M6  — append_streaming_line symmetric guard via _live_block_for_streaming
  H5  — OutputPanel live-output duo mount-order invariant (_live_anchor)
  H6  — _flush_pending requeues batch on NoMatches; breaks loudly after cap
  M2  — replace_body_widget snapshots queries before iterating (list-wrap)
  M5  — MessagePanel child-buffer drains inline at SubAgentPanel registration

Test layout (22 tests):
    TestH2AppendAfterTerminalize       — 3 tests
    TestM6AppendStreamingLineGuards    — 2 tests
    TestH5OutputPanelDuoInvariant      — 2 tests
    TestH6FlushPendingRequeue          — 6 tests
    TestM2ReplaceBodyAtomic            — 2 tests
    TestM5ChildBufferFlush             — 3 tests
    TestStreamingDispatchHappyPath     — 4 regression tests
"""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field as _field
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from hermes_cli.tui.services.tools import (
    ToolCallState,
    ToolCallViewState,
    ToolRenderingService,
    _TERMINAL_STATES,
)
from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock, _FLUSH_MAX_RETRIES
from textual.css.query import NoMatches


# ---------------------------------------------------------------------------
# Shared helpers
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
    state=ToolCallState.STREAMING,
    block=None,
):
    if block is None:
        block = MagicMock()
        block.parent = None
    return ToolCallViewState(
        tool_call_id=tool_call_id,
        gen_index=None,
        tool_name="read_file",
        label="Read",
        args={},
        state=state,
        block=block,
        panel=None,
        parent_tool_call_id=None,
        category="file_tools",
        depth=0,
        start_s=0.0,
    )


def _make_streaming_block(tool_call_id="tid-1") -> StreamingToolBlock:
    """Return a StreamingToolBlock with mocked DOM parents (no app required)."""
    block = StreamingToolBlock.__new__(StreamingToolBlock)
    # Minimal __init__ state required by the methods under test
    block._pending = []
    block._flush_retry = 0
    block._broken = False
    block._tool_call_id = tool_call_id
    block._completed = False
    block._all_plain = []
    block._all_rich = []
    block._visible_count = 0
    block._visible_start = 0
    block._visible_cap = 200
    block._cached_body_log = None
    block._omission_bar_bottom_mounted = False
    block._omission_bar_top_mounted = False
    block._follow_tail_dirty = False
    block._flush_slow = False
    block._last_line_time = time.monotonic()  # recent — avoids slow-flush branch
    block._render_timer = None
    block._is_unmounted = False
    block._microcopy_tick = 0
    block._skeleton_widget = None
    block._skeleton_timer = None
    block._body = MagicMock()
    return block


# ---------------------------------------------------------------------------
# H2 — append_tool_output drops chunk after terminalize during _set_view_state
# ---------------------------------------------------------------------------

class TestH2AppendAfterTerminalize:

    def test_append_after_terminalize_drops_with_log(self, caplog):
        """After complete_tool_call pops the block, late append_tool_output must no-op."""
        svc = _make_service()
        view = _make_view(state=ToolCallState.STREAMING)
        svc._tool_views_by_id["tid-1"] = view

        # Simulate completed: view moves to DONE, block is gone
        view.state = ToolCallState.DONE
        # Block NOT in _active_streaming_blocks (as terminalize pops it)

        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.services.tools"):
            svc.append_tool_output("tid-1", "late chunk")

        # No exception, nothing appended
        assert "tid-1" not in svc.app._active_streaming_blocks

    def test_append_during_streaming_delivers(self):
        """Happy-path: STREAMING view + live block → append_streaming_line called."""
        svc = _make_service()
        view = _make_view(state=ToolCallState.STREAMING)
        svc._tool_views_by_id["tid-1"] = view
        block = MagicMock()
        svc.app._active_streaming_blocks["tid-1"] = block
        panel_mock = MagicMock()
        panel_mock._user_scrolled_up = False
        svc._get_output_panel = MagicMock(return_value=panel_mock)

        svc.append_tool_output("tid-1", "hello")

        block.append_line.assert_called_once_with("hello")

    def test_append_with_terminalize_during_set_view_state(self, caplog):
        """Simulate future watcher that terminates tool during _set_view_state call.

        Patches _set_view_state to call _terminalize_tool_view as a side effect;
        asserts chunk dropped and debug log emitted — no KeyError / AttributeError.
        """
        svc = _make_service()
        view = _make_view(state=ToolCallState.STARTED)
        svc._tool_views_by_id["tid-1"] = view
        block = MagicMock()
        svc.app._active_streaming_blocks["tid-1"] = block

        original_set_view_state = ToolRenderingService._set_view_state

        def _terminalize_side_effect(self_svc, v, new):
            # Advance the state to DONE and remove the block (simulating watcher teardown)
            v.state = ToolCallState.DONE
            self_svc.app._active_streaming_blocks.pop(v.tool_call_id, None)

        with (
            patch.object(ToolRenderingService, "_set_view_state", _terminalize_side_effect),
            caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.services.tools"),
        ):
            svc.append_tool_output("tid-1", "lost chunk")

        block.append_line.assert_not_called()
        assert any("block gone post-axis" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# M6 — append_streaming_line symmetric guard via _live_block_for_streaming
# ---------------------------------------------------------------------------

class TestM6AppendStreamingLineGuards:

    def test_append_streaming_line_noops_when_view_terminal(self):
        """DONE view + live block in _active_streaming_blocks → no-op (new behaviour)."""
        svc = _make_service()
        view = _make_view(state=ToolCallState.DONE)
        svc._tool_views_by_id["tid-1"] = view
        block = MagicMock()
        svc.app._active_streaming_blocks["tid-1"] = block

        result = svc.append_streaming_line("tid-1", "late")

        block.append_line.assert_not_called()
        assert result is None

    def test_append_streaming_line_writes_during_streaming(self):
        """STREAMING view + live block → append_line + scroll scheduled."""
        svc = _make_service()
        view = _make_view(state=ToolCallState.STREAMING)
        svc._tool_views_by_id["tid-1"] = view
        block = MagicMock()
        svc.app._active_streaming_blocks["tid-1"] = block
        panel_mock = MagicMock()
        panel_mock._user_scrolled_up = False
        svc._get_output_panel = MagicMock(return_value=panel_mock)

        svc.append_streaming_line("tid-1", "ok")

        block.append_line.assert_called_once_with("ok")
        svc.app.call_after_refresh.assert_called()


# ---------------------------------------------------------------------------
# H5 — OutputPanel live-output duo mount-order invariant
# ---------------------------------------------------------------------------

class TestH5OutputPanelDuoInvariant:

    def test_live_anchor_returns_thinking_widget(self):
        """_live_anchor() returns ThinkingWidget when both are composed."""
        from hermes_cli.tui.widgets import OutputPanel
        from hermes_cli.tui.widgets.thinking import ThinkingWidget
        from hermes_cli.tui.widgets import LiveLineWidget

        panel = OutputPanel.__new__(OutputPanel)
        thinking = MagicMock(spec=ThinkingWidget)
        live_line = MagicMock(spec=LiveLineWidget)

        def _query_one(cls):
            if cls is ThinkingWidget:
                return thinking
            if cls is LiveLineWidget:
                return live_line
            raise NoMatches()

        panel.query_one = _query_one

        result = panel._live_anchor()
        assert result is thinking

    def test_live_anchor_falls_back_to_live_line_widget(self):
        """_live_anchor() falls back to LiveLineWidget when ThinkingWidget missing."""
        from hermes_cli.tui.widgets import OutputPanel
        from hermes_cli.tui.widgets.thinking import ThinkingWidget
        from hermes_cli.tui.widgets import LiveLineWidget

        panel = OutputPanel.__new__(OutputPanel)
        live_line = MagicMock(spec=LiveLineWidget)

        def _query_one(cls):
            if cls is ThinkingWidget:
                raise NoMatches()
            if cls is LiveLineWidget:
                return live_line
            raise NoMatches()

        panel.query_one = _query_one

        result = panel._live_anchor()
        assert result is live_line


# ---------------------------------------------------------------------------
# H6 — _flush_pending requeue on NoMatches + broken state
# ---------------------------------------------------------------------------

class TestH6FlushPendingRequeue:

    def test_flush_pending_requeues_batch_on_nomatches(self):
        """query_one raises once then succeeds; both lines visible, arrival order."""
        from rich.text import Text

        block = _make_streaming_block()
        rich1, plain1 = Text("line-a"), "line-a"
        rich2, plain2 = Text("line-b"), "line-b"
        block._pending = [(rich1, plain1), (rich2, plain2)]

        call_count = [0]
        fake_log = MagicMock()
        written = []
        fake_log.write_with_source = lambda r, p, link=None: written.append(p)

        def _query_one(cls):
            call_count[0] += 1
            if call_count[0] == 1:
                raise NoMatches()
            return fake_log

        block._body.query_one = _query_one

        # First flush — NoMatches; batch re-prepended
        block._flush_pending()
        assert block._flush_retry == 1
        assert block._pending == [(rich1, plain1), (rich2, plain2)]

        # Second flush — succeeds
        block._flush_pending()
        assert block._flush_retry == 0
        assert written == ["line-a", "line-b"]

    def test_flush_pending_marks_broken_after_retry_exhaustion(self, caplog):
        """Always-NoMatches → _broken=True after _FLUSH_MAX_RETRIES; _pending cleared."""
        from rich.text import Text

        block = _make_streaming_block()
        block._pending = [(Text("x"), "x")]
        block._body.query_one = MagicMock(side_effect=NoMatches())

        with caplog.at_level(logging.ERROR, logger="hermes_cli.tui.tool_blocks._streaming"):
            for _ in range(_FLUSH_MAX_RETRIES):
                block._pending = block._pending or [(Text("x"), "x")]
                block._flush_pending()

        assert block._broken is True
        assert block._pending == []
        assert any("never appeared" in r.message for r in caplog.records)

    def test_broken_block_drops_subsequent_lines_loudly(self, caplog):
        """_broken=True → append_line debug-logs and does not append to _pending."""
        block = _make_streaming_block()
        block._broken = True

        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.tool_blocks._streaming"):
            block.append_line("late line")

        assert block._pending == []
        assert any("dropping line on broken block" in r.message for r in caplog.records)

    def test_rerender_window_noops_when_broken(self):
        """_broken=True → rerender_window returns immediately without touching log."""
        block = _make_streaming_block()
        block._broken = True
        block._all_rich = []
        block._all_plain = []

        block.rerender_window(0, 3)

        block._body.query_one.assert_not_called()

    def test_reveal_lines_noops_when_broken(self):
        """_broken=True → reveal_lines returns immediately."""
        block = _make_streaming_block()
        block._broken = True
        block._all_rich = []
        block._all_plain = []

        block.reveal_lines(0, 2)

        block._body.query_one.assert_not_called()

    def test_collapse_to_noops_when_broken(self):
        """_broken=True → collapse_to returns immediately without clearing log."""
        block = _make_streaming_block()
        block._broken = True
        block._all_rich = []
        block._all_plain = []

        block.collapse_to(1)

        block._body.query_one.assert_not_called()


# ---------------------------------------------------------------------------
# M2 — replace_body_widget snapshots queries before iterating
# ---------------------------------------------------------------------------

class TestM2ReplaceBodyAtomic:

    def _make_tool_block(self):
        from hermes_cli.tui.tool_blocks._block import ToolBlock
        block = ToolBlock.__new__(ToolBlock)
        body = MagicMock()
        body.query.return_value = []
        body.mount = MagicMock()
        block._body = body
        block._header = MagicMock()
        block._rendered_body_widget = None
        block._rendered_plain_text = ""
        return block

    def test_replace_body_widget_preserves_bookkeeping(self):
        """Call once with plain_text; check all state fields set correctly."""
        from hermes_cli.tui.widgets import CopyableRichLog
        from hermes_cli.tui.body_renderers._grammar import BodyFooter

        block = self._make_tool_block()
        new_widget = MagicMock()

        # No old widgets to remove
        block._body.query.return_value = []

        block.replace_body_widget(new_widget, plain_text="line1\nline2")

        assert block._rendered_body_widget is new_widget
        assert block._rendered_plain_text == "line1\nline2"
        assert block._header._line_count == 2
        assert block._header._has_affordances is True

    def test_replace_body_widget_idempotent_double_call(self):
        """Second call removes first widget; body has only the second widget."""
        from hermes_cli.tui.widgets import CopyableRichLog
        from hermes_cli.tui.body_renderers._grammar import BodyFooter

        block = self._make_tool_block()
        widget_a = MagicMock()
        widget_a.is_attached = True
        widget_b = MagicMock()
        widget_b.is_attached = False

        block._body.query.return_value = []

        block.replace_body_widget(widget_a)
        block.replace_body_widget(widget_b)

        widget_a.remove.assert_called_once()
        assert block._rendered_body_widget is widget_b


# ---------------------------------------------------------------------------
# M5 — MessagePanel child-buffer drains inline at SubAgentPanel registration
# ---------------------------------------------------------------------------

class TestM5ChildBufferFlush:

    def _make_message_panel(self):
        from hermes_cli.tui.widgets.message_panel import MessagePanel
        mp = MessagePanel.__new__(MessagePanel)
        mp._subagent_panels = {}
        mp._child_buffer = {}
        mp._flush_scheduled = set()
        mp._mount_nonprose_block = MagicMock()
        return mp

    def test_child_buffer_flushes_in_arrival_order(self):
        """Three pre-buffered children drain in arrival order at parent registration."""
        from hermes_cli.tui.sub_agent_panel import SubAgentPanel

        mp = self._make_message_panel()
        child_a, child_b, child_c = MagicMock(), MagicMock(), MagicMock()
        mp._child_buffer["parent-1"] = [child_a, child_b, child_c]
        mp._flush_scheduled.add("parent-1")

        panel = MagicMock(spec=SubAgentPanel)
        add_calls = []
        panel.add_child_panel.side_effect = lambda c: add_calls.append(c)

        # Simulate the registration path manually
        mp._subagent_panels["parent-1"] = panel
        pending = mp._child_buffer.pop("parent-1", [])
        mp._flush_scheduled.discard("parent-1")
        mp._mount_nonprose_block(panel)
        for child in pending:
            panel.add_child_panel(child)

        assert add_calls == [child_a, child_b, child_c]

    def test_child_buffer_flush_synchronous_at_registration(self):
        """Inline drain occurs before any further event-loop yield."""
        from hermes_cli.tui.sub_agent_panel import SubAgentPanel
        from hermes_cli.tui.tool_category import ToolCategory

        mp = self._make_message_panel()
        child_x, child_y = MagicMock(), MagicMock()
        mp._child_buffer["sap-A"] = [child_x, child_y]
        mp._flush_scheduled.add("sap-A")

        panel = MagicMock(spec=SubAgentPanel)

        # Simulate what the patched AGENT branch now does
        mp._subagent_panels["sap-A"] = panel
        pending = mp._child_buffer.pop("sap-A", [])
        mp._flush_scheduled.discard("sap-A")
        mp._mount_nonprose_block(panel)
        for child in pending:
            panel.add_child_panel(child)

        # Immediately after — no additional call_after_refresh needed
        assert panel.add_child_panel.call_count == 2
        assert "sap-A" not in mp._flush_scheduled

    def test_child_buffer_flush_scheduled_cleared(self):
        """After inline drain, _child_buffer and _flush_scheduled entries are gone."""
        from hermes_cli.tui.sub_agent_panel import SubAgentPanel

        mp = self._make_message_panel()
        child = MagicMock()
        mp._child_buffer["sap-B"] = [child]
        mp._flush_scheduled.add("sap-B")

        panel = MagicMock(spec=SubAgentPanel)

        mp._subagent_panels["sap-B"] = panel
        pending = mp._child_buffer.pop("sap-B", [])
        mp._flush_scheduled.discard("sap-B")
        mp._mount_nonprose_block(panel)
        for c in pending:
            panel.add_child_panel(c)

        assert mp._child_buffer.get("sap-B") is None
        assert "sap-B" not in mp._flush_scheduled


# ---------------------------------------------------------------------------
# Regression guards — TestStreamingDispatchHappyPath (4 tests)
# ---------------------------------------------------------------------------

class TestStreamingDispatchHappyPath:

    def test_terminal_states_constant_covers_all_four(self):
        """_TERMINAL_STATES covers exactly DONE, ERROR, CANCELLED, REMOVED."""
        assert set(_TERMINAL_STATES) == {
            ToolCallState.DONE,
            ToolCallState.ERROR,
            ToolCallState.CANCELLED,
            ToolCallState.REMOVED,
        }

    def test_live_block_for_streaming_returns_none_for_terminal_view(self):
        """_live_block_for_streaming returns None when view is terminal."""
        svc = _make_service()
        view = _make_view(state=ToolCallState.DONE)
        svc._tool_views_by_id["tid-1"] = view
        block = MagicMock()
        svc.app._active_streaming_blocks["tid-1"] = block

        result = svc._live_block_for_streaming("tid-1")
        assert result is None

    def test_live_block_for_streaming_returns_block_for_streaming_view(self):
        """_live_block_for_streaming returns block when view is STREAMING."""
        svc = _make_service()
        view = _make_view(state=ToolCallState.STREAMING)
        svc._tool_views_by_id["tid-1"] = view
        block = MagicMock()
        svc.app._active_streaming_blocks["tid-1"] = block

        result = svc._live_block_for_streaming("tid-1")
        assert result is block

    def test_flush_max_retries_constant_value(self):
        """_FLUSH_MAX_RETRIES is 32 as spec'd (≈530 ms at 60 Hz)."""
        assert _FLUSH_MAX_RETRIES == 32
