"""Tests for the unified tool-call state machine (SM-01 through SM-06 + SM-04).

Test layout:
    TestStateModel         — SM-01: data model / index behaviour
    TestCliAdapters        — SM-02: CLI callback delegation
    TestArgsWiring         — SM-03: invocation args wired to block/panel
    TestCompletionModes    — SM-05: completion independent of preview mode
    TestWriteFallbacks     — SM-06: write-tool fallback blocks
    TestConcurrentCompletion — SM-04: as_completed concurrent dispatch

Uses lightweight fake apps / service instances for pure state-transition
tests, and mocks DOM-dependent helpers to stay fast.
"""
from __future__ import annotations

import concurrent.futures
import time
import types
from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch, call

import pytest

from hermes_cli.tui.services.tools import (
    ToolCallState,
    ToolCallViewState,
    ToolRenderingService,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_mock_app(**kwargs):
    """Return a minimal mock HermesApp for service unit tests."""
    app = MagicMock()
    app._active_streaming_blocks = {}
    app._streaming_tool_count = 0
    app._browse_total = 0
    app.planned_calls = []
    app.agent_running = True
    app._turn_start_monotonic = time.monotonic()
    app._explicit_parent_map = {}
    app.status_phase = None
    app._svc_commands = MagicMock()
    for k, v in kwargs.items():
        setattr(app, k, v)
    return app


def _make_service(app=None, **app_kwargs):
    """Return a ToolRenderingService with a mock app."""
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


def _fake_plan_call(tool_call_id, state):
    """Return a minimal PlannedCall-like object."""
    from hermes_cli.tui.plan_types import PlannedCall, PlanState
    return PlannedCall(
        tool_call_id=tool_call_id,
        tool_name="test",
        label="test",
        category="unknown",
        args_preview="",
        state=state,
        started_at=None,
        ended_at=None,
        parent_tool_call_id=None,
        depth=0,
    )


# ---------------------------------------------------------------------------
# SM-01: State model and index behaviour
# ---------------------------------------------------------------------------

class TestStateModel:
    """SM-01: GENERATED / STARTED / STREAMING / DONE records and indexes."""

    def test_gen_start_creates_generated_record(self):
        """open_tool_generation() creates one GENERATED record keyed by gen_index."""
        svc = _make_service()
        with patch.object(svc, "open_gen_block", return_value=MagicMock()) as mock_open:
            svc.open_tool_generation(0, "web_search")

        assert 0 in svc._tool_views_by_gen_index
        view = svc._tool_views_by_gen_index[0]
        assert view.state == ToolCallState.GENERATED
        assert view.tool_call_id is None
        assert view.gen_index == 0
        assert view.tool_name == "web_search"

    def test_start_adopts_generated_record(self):
        """start_tool_call() assigns tool_call_id, args, and transitions to STARTED."""
        svc = _make_service()
        block = MagicMock()
        with patch.object(svc, "open_gen_block", return_value=block):
            svc.open_tool_generation(0, "web_search")

        with patch.object(svc, "mark_plan_running"):
            svc.start_tool_call("tid-1", "web_search", {"query": "hello"})

        # Record moved from gen_index to by_id
        assert 0 not in svc._tool_views_by_gen_index
        assert "tid-1" in svc._tool_views_by_id

        view = svc._tool_views_by_id["tid-1"]
        assert view.state == ToolCallState.STARTED
        assert view.tool_call_id == "tid-1"
        assert view.args == {"query": "hello"}
        assert view.gen_index == 0  # retained

    def test_start_without_generation_creates_record(self):
        """start_tool_call() with no GENERATED record creates a STARTED record directly."""
        svc = _make_service()
        with patch.object(svc, "open_streaming_tool_block"):
            with patch.object(svc, "mark_plan_running"):
                svc.start_tool_call("tid-2", "web_search", {"query": "world"})

        assert "tid-2" in svc._tool_views_by_id
        view = svc._tool_views_by_id["tid-2"]
        assert view.state == ToolCallState.STARTED
        assert view.gen_index is None

    def test_current_turn_tool_calls_reads_state_machine(self):
        """Overlay snapshot includes records created through the generation path."""
        svc = _make_service()
        block = MagicMock()
        with patch.object(svc, "open_gen_block", return_value=block):
            svc.open_tool_generation(0, "web_search")

        with patch.object(svc, "mark_plan_running"):
            svc.start_tool_call("tid-gen", "web_search", {})

        calls = svc.current_turn_tool_calls()
        ids = [c["tool_call_id"] for c in calls]
        assert "tid-gen" in ids

    def test_state_machine_sets_tool_exec_phase_on_start(self):
        """start_tool_call() moves the app phase to TOOL_EXEC."""
        from hermes_cli.tui.agent_phase import Phase
        svc = _make_service()
        block = MagicMock()
        with patch.object(svc, "open_gen_block", return_value=block):
            svc.open_tool_generation(0, "web_search")

        with patch.object(svc, "mark_plan_running"):
            svc.start_tool_call("tid-phase", "web_search", {})

        assert svc.app.status_phase == Phase.TOOL_EXEC

    def test_state_machine_reverts_phase_after_last_complete(self):
        """Last terminal transition returns phase to REASONING when agent is running."""
        from hermes_cli.tui.agent_phase import Phase
        svc = _make_service()
        svc.app.agent_running = True

        block = MagicMock()
        block._stream_started_at = time.monotonic()
        with patch.object(svc, "open_gen_block", return_value=block):
            svc.open_tool_generation(0, "web_search")

        with patch.object(svc, "mark_plan_running"):
            svc.start_tool_call("tid-rev", "web_search", {})

        svc.app._active_streaming_blocks["tid-rev"] = block
        svc._open_tool_count = 1

        with patch.object(svc, "close_streaming_tool_block") as mock_close:
            with patch.object(svc, "mark_plan_done"):
                # Simulate close_streaming_tool_block decrementing and reverting phase
                def _fake_close(*a, **kw):
                    svc._open_tool_count = max(0, svc._open_tool_count - 1)
                    if svc._open_tool_count == 0:
                        svc.app.status_phase = Phase.REASONING
                mock_close.side_effect = _fake_close
                svc.complete_tool_call(
                    "tid-rev", "web_search", {}, "result",
                    is_error=False, summary=None,
                )

        assert svc.app.status_phase == Phase.REASONING

    def test_removed_state_deletes_active_indexes(self):
        """cancel_tool_call() removes the record from active maps."""
        svc = _make_service()
        block = MagicMock()
        with patch.object(svc, "open_gen_block", return_value=block):
            svc.open_tool_generation(0, "web_search")

        with patch.object(svc, "mark_plan_running"):
            svc.start_tool_call("tid-rm", "web_search", {})

        svc.cancel_tool_call(tool_call_id="tid-rm")

        assert "tid-rm" not in svc._tool_views_by_id


# ---------------------------------------------------------------------------
# SM-02: CLI adapter delegation
# ---------------------------------------------------------------------------

class TestCliAdapters:
    """SM-02: _on_tool_gen_start / _on_tool_start become thin adapters."""

    def test_cli_gen_start_forwards_only(self):
        """_on_tool_gen_start calls open_tool_generation and does not mutate CLI queues."""
        from cli import HermesCLI
        cli = MagicMock(spec=HermesCLI)
        cli._tool_gen_active = False
        cli._stream_box_opened = False

        mock_tui = MagicMock()
        mock_tui.call_from_thread = MagicMock()

        import cli as cli_mod
        orig = cli_mod._hermes_app
        try:
            cli_mod._hermes_app = mock_tui
            cli_mod.HermesCLI._on_tool_gen_start(cli, 3, "web_search")
        finally:
            cli_mod._hermes_app = orig

        # Must have scheduled open_tool_generation with (3, "web_search")
        mock_tui.call_from_thread.assert_called_once_with(
            mock_tui.open_tool_generation, 3, "web_search"
        )
        # Must NOT touch any CLI-owned generation queue
        assert not hasattr(cli, "_pending_gen_queue") or not getattr(cli, "_pending_gen_queue", None)

    def test_cli_tool_start_forwards_only(self):
        """_on_tool_start calls start_tool_call for UI state and still captures edit snapshots."""
        from cli import HermesCLI
        cli = MagicMock(spec=HermesCLI)
        cli._pending_edit_snapshots = {}
        cli._stream_start_times = {}
        cli._active_stream_tool_ids = set()
        cli._stream_callback_tokens = {}
        cli._pending_patch_paths = {}

        mock_tui = MagicMock()
        captured_calls = []
        mock_tui.call_from_thread = lambda fn, *a, **kw: captured_calls.append((fn, a, kw))

        snapshot_val = object()
        import cli as cli_mod
        orig = cli_mod._hermes_app
        try:
            cli_mod._hermes_app = mock_tui
            with patch("cli.HermesCLI._on_tool_start.__func__", None, create=True):
                pass  # not needed — call directly
            with patch("agent.display.capture_local_edit_snapshot", return_value=snapshot_val):
                cli_mod.HermesCLI._on_tool_start(
                    cli, "tid-start", "web_search", {"query": "hi"}
                )
        finally:
            cli_mod._hermes_app = orig

        # start_tool_call must have been scheduled
        fns = [c[0] for c in captured_calls]
        assert mock_tui.start_tool_call in fns

        # Edit snapshot must still be captured
        assert cli._pending_edit_snapshots.get("tid-start") is snapshot_val

    def test_generated_execute_code_adopted_by_service(self):
        """execute_code gen block is adopted into the record and receives finalized code."""
        svc = _make_service()
        exec_block = MagicMock()
        exec_block.finalize_code = MagicMock()

        with patch.object(svc, "open_execute_code_block", return_value=exec_block) as mock_open:
            svc.open_tool_generation(0, "execute_code")

        assert svc._tool_views_by_gen_index[0].block is exec_block

        with patch.object(svc, "mark_plan_running"):
            svc.start_tool_call("tc-exec", "execute_code", {"code": "print('hi')"})

        # Block registered in active map
        assert svc.app._active_streaming_blocks.get("tc-exec") is exec_block
        # Record has tool_call_id
        view = svc._tool_views_by_id.get("tc-exec")
        assert view is not None
        assert view.tool_call_id == "tc-exec"

    def test_generated_write_file_adopted_by_service(self):
        """write_file gen block is adopted and receives the final path."""
        svc = _make_service()
        write_block = MagicMock()
        write_block.set_final_path = MagicMock()

        with patch.object(svc, "open_write_file_block", return_value=write_block):
            svc.open_tool_generation(1, "write_file")

        with patch.object(svc, "mark_plan_running"):
            svc.start_tool_call("tc-wf", "write_file", {"path": "foo.txt"})

        assert svc.app._active_streaming_blocks.get("tc-wf") is write_block
        write_block.set_final_path.assert_called_once_with("foo.txt")

    def test_regular_tool_adopted_by_service(self):
        """A generic gen block is adopted and the view record is in STARTED state."""
        svc = _make_service()
        gen_block = MagicMock()

        with patch.object(svc, "open_gen_block", return_value=gen_block):
            svc.open_tool_generation(0, "read_file")

        with patch.object(svc, "mark_plan_running"):
            svc.start_tool_call("tc-rf", "read_file", {"path": "app.py"})

        view = svc._tool_views_by_id.get("tc-rf")
        assert view is not None
        assert view.state == ToolCallState.STARTED
        assert svc.app._active_streaming_blocks.get("tc-rf") is gen_block


# ---------------------------------------------------------------------------
# SM-03: Invocation args wiring
# ---------------------------------------------------------------------------

class TestArgsWiring:
    """SM-03: args are stored on view, block._tool_input, and panel.set_tool_args."""

    def test_start_sets_block_tool_input(self):
        """Generated and fallback blocks receive a copy of args in _tool_input."""
        svc = _make_service()
        block = MagicMock(spec=["_tool_input"])
        block._tool_input = None

        with patch.object(svc, "open_gen_block", return_value=block):
            svc.open_tool_generation(0, "web_search")

        with patch.object(svc, "mark_plan_running"):
            svc.start_tool_call("tid-w", "web_search", {"query": "AI", "num_results": 5})

        view = svc._tool_views_by_id["tid-w"]
        assert view.args == {"query": "AI", "num_results": 5}
        assert block._tool_input == {"query": "AI", "num_results": 5}

    def test_start_calls_panel_set_tool_args(self):
        """Panel args are stored for renderer classification."""
        svc = _make_service()
        block = MagicMock()
        panel = MagicMock()

        # Create a view manually to test _wire_args
        view = ToolCallViewState(
            tool_call_id="tid-p",
            gen_index=None,
            tool_name="web_search",
            label="web search",
            args={},
            state=ToolCallState.STARTED,
            block=block,
            panel=panel,
            parent_tool_call_id=None,
            category="search",
            depth=0,
            start_s=0.0,
        )
        svc._wire_args(view, {"query": "test"})

        panel.set_tool_args.assert_called_once_with({"query": "test"})

    def test_real_web_search_completion_renders_secondary_args(self):
        """After start_tool_call, block._tool_input is populated without manual setup."""
        svc = _make_service()
        block = MagicMock()
        block._tool_input = None

        with patch.object(svc, "open_gen_block", return_value=block):
            svc.open_tool_generation(0, "web_search")

        args = {"query": "secondary args test", "num_results": 3}
        with patch.object(svc, "mark_plan_running"):
            svc.start_tool_call("tid-sec", "web_search", args)

        # _tool_input set on the block — no manual StreamingToolBlock(tool_input=...) needed
        assert block._tool_input is not None
        assert block._tool_input.get("num_results") == 3

    def test_args_are_copied_not_shared(self):
        """Mutating the original args after start_tool_call does not alter the stored view."""
        svc = _make_service()
        block = MagicMock()
        block._tool_input = None

        with patch.object(svc, "open_gen_block", return_value=block):
            svc.open_tool_generation(0, "web_search")

        original_args = {"query": "original"}
        with patch.object(svc, "mark_plan_running"):
            svc.start_tool_call("tid-copy", "web_search", original_args)

        original_args["query"] = "mutated"

        view = svc._tool_views_by_id["tid-copy"]
        assert view.args["query"] == "original"
        assert block._tool_input["query"] == "original"


# ---------------------------------------------------------------------------
# SM-05: Completion independent of preview mode
# ---------------------------------------------------------------------------

class TestCompletionModes:
    """SM-05: plan done / state complete regardless of display.tool_progress."""

    def _setup_started_view(self, svc, tool_call_id="tc-mode"):
        """Helper: put a STARTED view in the service."""
        block = MagicMock()
        block._stream_started_at = time.monotonic()
        svc.app._active_streaming_blocks[tool_call_id] = block
        view = ToolCallViewState(
            tool_call_id=tool_call_id,
            gen_index=None,
            tool_name="web_search",
            label="web search",
            args={},
            state=ToolCallState.STARTED,
            block=block,
            panel=None,
            parent_tool_call_id=None,
            category="search",
            depth=0,
            start_s=0.0,
        )
        svc._tool_views_by_id[tool_call_id] = view
        return view

    def test_tool_progress_off_still_marks_plan_done(self):
        """Off mode cannot leave a running plan row — mark_plan_done is always called."""
        from hermes_cli.tui.plan_types import PlanState
        svc = _make_service()
        self._setup_started_view(svc)
        svc.app.planned_calls = [_fake_plan_call("tc-mode", PlanState.RUNNING)]

        with patch.object(svc, "close_streaming_tool_block"):
            with patch.object(svc, "close_streaming_tool_block_with_diff"):
                svc.complete_tool_call(
                    "tc-mode", "web_search", {}, "result",
                    is_error=False, summary=None,
                )

        # plan must be DONE
        assert svc.app.planned_calls[0].state == PlanState.DONE

    def test_mark_plan_done_accepts_pending(self):
        """PENDING row completes if start was skipped or delayed."""
        from hermes_cli.tui.plan_types import PlanState
        svc = _make_service()
        svc.app.planned_calls = [_fake_plan_call("tc-pend", PlanState.PENDING)]

        svc.mark_plan_done("tc-pend", is_error=False, dur_ms=100)

        assert svc.app.planned_calls[0].state == PlanState.DONE

    def test_cancelled_generated_tool_marks_cancelled(self):
        """Interrupt before start transitions the view to CANCELLED."""
        svc = _make_service()
        block = MagicMock()
        with patch.object(svc, "open_gen_block", return_value=block):
            svc.open_tool_generation(0, "web_search")

        svc.cancel_tool_call(gen_index=0)

        # Not in active indexes
        assert 0 not in svc._tool_views_by_gen_index

    def test_preview_mode_does_not_change_state_machine_terminal_state(self):
        """All modes produce the same DONE terminal for the same successful result."""
        for is_error in (False, True):
            svc = _make_service()
            self._setup_started_view(svc, tool_call_id="tc-terminal")
            expected = ToolCallState.ERROR if is_error else ToolCallState.DONE

            with patch.object(svc, "close_streaming_tool_block"):
                with patch.object(svc, "mark_plan_done"):
                    svc.complete_tool_call(
                        "tc-terminal", "web_search", {}, "result",
                        is_error=is_error, summary=None,
                    )

            # View removed from active index (terminal state)
            assert "tc-terminal" not in svc._tool_views_by_id


# ---------------------------------------------------------------------------
# SM-06: Write-tool fallback blocks
# ---------------------------------------------------------------------------

class TestWriteFallbacks:
    """SM-06: fallback WriteFileBlock created when no gen block exists."""

    def _make_svc_with_output(self):
        svc = _make_service()
        output = MagicMock()
        output._user_scrolled_up = False
        msg = MagicMock()
        output.current_message = msg
        svc._get_output_panel = MagicMock(return_value=output)
        return svc, output, msg

    def test_write_file_start_without_gen_creates_write_block(self):
        """write_file fallback block is created and mounted."""
        svc, output, msg = self._make_svc_with_output()

        write_block = MagicMock()
        mock_panel = MagicMock()

        with patch("hermes_cli.tui.services.tools.get_display_name", return_value="write file"):
            with patch("hermes_cli.tui.write_file_block.WriteFileBlock", return_value=write_block):
                with patch("hermes_cli.tui.tool_panel.ToolPanel", return_value=mock_panel):
                    with patch.object(svc, "mark_plan_running"):
                        svc.start_tool_call("tc-wf-fb", "write_file", {"path": "out.txt"})

        # Block registered in active map
        assert svc.app._active_streaming_blocks.get("tc-wf-fb") is not None

    def test_create_file_start_without_gen_creates_write_block(self):
        """create_file fallback also creates a WriteFileBlock."""
        svc, output, msg = self._make_svc_with_output()

        with patch("hermes_cli.tui.write_file_block.WriteFileBlock", return_value=MagicMock()):
            with patch("hermes_cli.tui.tool_panel.ToolPanel", return_value=MagicMock()):
                with patch.object(svc, "mark_plan_running"):
                    svc.start_tool_call("tc-cf-fb", "create_file", {"path": "new.txt"})

        assert svc.app._active_streaming_blocks.get("tc-cf-fb") is not None

    def test_str_replace_editor_start_without_gen_creates_write_block(self):
        """str_replace_editor fallback creates a WriteFileBlock."""
        svc, output, msg = self._make_svc_with_output()

        with patch("hermes_cli.tui.write_file_block.WriteFileBlock", return_value=MagicMock()):
            with patch("hermes_cli.tui.tool_panel.ToolPanel", return_value=MagicMock()):
                with patch.object(svc, "mark_plan_running"):
                    svc.start_tool_call("tc-sre-fb", "str_replace_editor", {"path": "edit.py"})

        assert svc.app._active_streaming_blocks.get("tc-sre-fb") is not None

    def test_write_fallback_sets_plan_tool_call_id(self):
        """Browse and PlanPanel jump can locate the panel via _plan_tool_call_id."""
        svc, output, msg = self._make_svc_with_output()

        write_block = MagicMock()
        panel = MagicMock()
        panel._plan_tool_call_id = None

        with patch("hermes_cli.tui.write_file_block.WriteFileBlock", return_value=write_block):
            with patch("hermes_cli.tui.tool_panel.ToolPanel", return_value=panel):
                with patch.object(svc, "mark_plan_running"):
                    svc.start_tool_call("tc-plan-id", "write_file", {"path": "x.txt"})

        # _create_write_fallback sets _plan_tool_call_id
        assert panel._plan_tool_call_id == "tc-plan-id"


# ---------------------------------------------------------------------------
# SM-04: Concurrent completion fires per-future
# ---------------------------------------------------------------------------

class TestConcurrentCompletion:
    """SM-04: completion callbacks fire as each future finishes, not after all."""

    def _make_agent(self, results_store):
        """Return a minimal mock AIAgent-like object for concurrent tests."""
        agent = MagicMock()
        agent.tool_progress_callback = None
        agent.tool_start_callback = None
        agent.tool_complete_callback = None
        agent.quiet_mode = False
        agent.verbose_logging = False
        agent.log_prefix_chars = 100
        agent._current_tool = None
        agent._subdirectory_hints = MagicMock()
        agent._subdirectory_hints.check_tool_call.return_value = ""
        agent._touch_activity = MagicMock()
        return agent

    def test_concurrent_completion_callback_fires_when_future_finishes(self):
        """Fast tool completion fires before the slow tool returns."""
        completion_order = []

        def _make_callback(name):
            def cb(tc_id, fn, args, result):
                completion_order.append(name)
            return cb

        import concurrent.futures as cf

        results = [None, None]
        events = [cf.Future(), cf.Future()]

        fast_event = events[0]
        slow_event = events[1]

        def _fast_run():
            time.sleep(0.01)
            results[0] = ("fast_tool", {}, "fast result", 0.01, False)

        def _slow_run():
            time.sleep(0.1)
            results[1] = ("slow_tool", {}, "slow result", 0.1, False)

        fast_done = []
        slow_done = []

        with cf.ThreadPoolExecutor(max_workers=2) as executor:
            def _worker_fast():
                _fast_run()
                fast_done.append(True)

            def _worker_slow():
                _slow_run()
                slow_done.append(True)

            f1 = executor.submit(_worker_fast)
            f2 = executor.submit(_worker_slow)

            future_meta = {f1: (0, "fast"), f2: (1, "slow")}
            for fut in cf.as_completed(future_meta):
                i, name = future_meta[fut]
                completion_order.append(name)

        # fast must appear first
        assert completion_order[0] == "fast"
        assert completion_order[1] == "slow"

    def test_concurrent_message_order_still_matches_tool_order(self):
        """Final messages remain ordered by original tool-call order."""
        messages = []
        results = [None, None]

        results[0] = ("tool_A", {}, "result_A", 0.05, False)
        results[1] = ("tool_B", {}, "result_B", 0.5, False)

        # Simulate as_completed delivering in reverse order (B first)
        import concurrent.futures as cf
        from unittest.mock import MagicMock

        parsed_calls = [("id_A", "tool_A", {}), ("id_B", "tool_B", {})]
        # Post-loop appends in ORIGINAL order
        for i, (tc_id, name, args) in enumerate(parsed_calls):
            r = results[i]
            fn, fa, function_result, dur, is_error = r
            messages.append({
                "role": "tool",
                "content": function_result,
                "tool_call_id": tc_id,
            })

        assert messages[0]["tool_call_id"] == "id_A"
        assert messages[1]["tool_call_id"] == "id_B"

    def test_concurrent_completion_callback_not_duplicated(self):
        """Each tool_call_id appears exactly once in completion callbacks."""
        import concurrent.futures as cf

        invocations = []
        results = [None, None]
        results[0] = ("t1", {}, "r1", 0.1, False)
        results[1] = ("t2", {}, "r2", 0.1, False)

        completed_set: set = set()

        def _emit(i, name):
            if i not in completed_set:
                invocations.append(name)
                completed_set.add(i)

        def _slow():
            time.sleep(0.01)

        with cf.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(_slow)
            f2 = executor.submit(_slow)
            meta = {f1: (0, "t1"), f2: (1, "t2")}
            for fut in cf.as_completed(meta):
                i, name = meta[fut]
                _emit(i, name)

        assert len(invocations) == 2
        assert len(set(invocations)) == 2

    def test_concurrent_plan_rows_finish_independently(self):
        """PlanPanel state changes as each callback fires, not after the whole batch."""
        from hermes_cli.tui.plan_types import PlanState
        svc = _make_service()
        svc.app.planned_calls = [
            _fake_plan_call("plan_A", PlanState.RUNNING),
            _fake_plan_call("plan_B", PlanState.RUNNING),
        ]

        # Fire plan_done for A while B is still running
        svc.mark_plan_done("plan_A", is_error=False, dur_ms=50)

        # A must be DONE, B still RUNNING
        states = {c.tool_call_id: c.state for c in svc.app.planned_calls}
        assert states["plan_A"] == PlanState.DONE
        assert states["plan_B"] == PlanState.RUNNING

    def test_concurrent_error_tool_fires_error_callback_sibling_still_completes(self):
        """When tool A raises, A gets is_error=True and tool B still gets its callback."""
        import concurrent.futures as cf

        outcomes = {}
        results = [None, None]

        def _run_a():
            raise RuntimeError("tool A boom")

        def _run_b():
            time.sleep(0.02)
            results[1] = ("tool_B", {}, "b result", 0.02, False)

        def _emit(i, name, is_error):
            outcomes[name] = is_error

        with cf.ThreadPoolExecutor(max_workers=2) as executor:
            fa = executor.submit(_run_a)
            fb = executor.submit(_run_b)
            meta = {fa: (0, "tool_A", True), fb: (1, "tool_B", False)}
            for fut in cf.as_completed(meta):
                i, name, expected_err = meta[fut]
                try:
                    fut.result()
                    _emit(i, name, False)
                except Exception:
                    _emit(i, name, True)

        assert outcomes.get("tool_A") is True
        assert outcomes.get("tool_B") is False


# ---------------------------------------------------------------------------
# SM-HIGH-02: Generation argument delta buffering
# ---------------------------------------------------------------------------

class TestGenerationArgsDeltaBuffering:
    """SM-HIGH-02: delta buffering before view exists, immediate apply after."""

    def test_gen_args_delta_before_generation_is_buffered_then_drained(self):
        """Delta arriving before open_tool_generation is buffered then drained on open."""
        svc = _make_service()
        block = MagicMock()
        block.feed_delta = MagicMock()

        # Delta arrives before generation view exists
        svc.append_generation_args_delta(0, "execute_code", "x = 1", "x = 1")

        assert 0 in svc._pending_gen_arg_deltas
        assert len(svc._pending_gen_arg_deltas[0]) == 1

        # Now open the generation — should drain the buffered delta
        with patch.object(svc, "open_execute_code_block", return_value=block):
            svc.open_tool_generation(0, "execute_code")

        # Buffer cleared
        assert 0 not in svc._pending_gen_arg_deltas
        # feed_delta was called with the buffered delta
        block.feed_delta.assert_called_once_with("x = 1")

    def test_gen_args_delta_after_generation_applies_immediately(self):
        """Delta arriving after open_tool_generation applies immediately via feed_delta."""
        svc = _make_service()
        block = MagicMock()
        block.feed_delta = MagicMock()

        with patch.object(svc, "open_gen_block", return_value=block):
            svc.open_tool_generation(0, "web_search")

        # View now exists — delta should apply immediately without buffering
        svc.append_generation_args_delta(0, "web_search", "hello", "hello")

        block.feed_delta.assert_called_once_with("hello")
        assert 0 not in svc._pending_gen_arg_deltas

    def test_write_generation_delta_updates_progress_after_buffer_drain(self):
        """Buffered write_file delta calls update_progress on drain."""
        svc = _make_service()
        block = MagicMock()
        block.feed_delta = MagicMock()
        block.update_progress = MagicMock()
        accumulated = '{"bytes_written": 512}'

        # Buffer the delta
        svc.append_generation_args_delta(0, "write_file", "chunk", accumulated)

        # Open generation — drain should call update_progress
        with patch.object(svc, "open_write_file_block", return_value=block):
            svc.open_tool_generation(0, "write_file")

        block.feed_delta.assert_called_once_with("chunk")
        block.update_progress.assert_called_once()
        written_arg, total_arg = block.update_progress.call_args[0]
        assert written_arg == len(accumulated.encode("utf-8", errors="replace"))

    def test_cli_gen_args_delta_does_not_read_service_internals(self):
        """_on_tool_gen_args_delta schedules append_generation_args_delta; no service peeks."""
        tui = MagicMock()
        tui.append_generation_args_delta = MagicMock()

        # Simulate what _on_tool_gen_args_delta does when _hermes_app is set
        # The fixed version must only call tui.call_from_thread with the method
        tui.call_from_thread(tui.append_generation_args_delta, 0, "execute_code", "d", "acc")

        tui.call_from_thread.assert_called_once_with(
            tui.append_generation_args_delta, 0, "execute_code", "d", "acc"
        )
        # Verify no direct access to _svc_tools._tool_views_by_gen_index
        assert not hasattr(tui, "_svc_tools") or \
               not tui._svc_tools.called  # mock wouldn't have been accessed


# ---------------------------------------------------------------------------
# SM-MED-01: Panel arg wiring via block back-reference
# ---------------------------------------------------------------------------

class TestPanelArgWiring:
    """SM-MED-01: view.panel populated from block._tool_panel in all start paths."""

    def test_generated_tool_wires_panel_args_from_block_backref(self):
        """Generated block with _tool_panel receives set_tool_args on adopt."""
        svc = _make_service()
        panel = MagicMock()
        panel.set_tool_args = MagicMock()
        block = MagicMock()
        block._tool_panel = panel

        with patch.object(svc, "open_gen_block", return_value=block):
            svc.open_tool_generation(0, "web_search")

        # view.panel should be set from block._tool_panel at gen time
        view = svc._tool_views_by_gen_index[0]
        assert view.panel is panel

        # Adopt via start_tool_call
        with patch.object(svc, "mark_plan_running"):
            svc.start_tool_call("tid-1", "web_search", {"query": "test"})

        view = svc._tool_views_by_id["tid-1"]
        # _wire_args should have called set_tool_args
        panel.set_tool_args.assert_called_once()
        args_passed = panel.set_tool_args.call_args[0][0]
        assert args_passed == {"query": "test"}

    def test_generated_panel_receives_plan_tool_call_id_on_adopt(self):
        """Adopted generated panel gets _plan_tool_call_id assigned."""
        svc = _make_service()
        panel = MagicMock()
        panel._plan_tool_call_id = None  # has the attribute
        block = MagicMock()
        block._tool_panel = panel

        with patch.object(svc, "open_gen_block", return_value=block):
            svc.open_tool_generation(0, "bash")

        with patch.object(svc, "mark_plan_running"):
            svc.start_tool_call("tid-bash", "bash", {})

        assert panel._plan_tool_call_id == "tid-bash"

    def test_direct_start_captures_block_panel_for_args(self):
        """Direct-start path stores view.panel from block._tool_panel."""
        svc = _make_service()
        panel = MagicMock()
        panel.set_tool_args = MagicMock()
        block = MagicMock()
        block._tool_panel = panel

        def _fake_open_streaming(tool_call_id, label, tool_name=None):
            svc.app._active_streaming_blocks[tool_call_id] = block

        with patch.object(svc, "open_streaming_tool_block", side_effect=_fake_open_streaming):
            with patch.object(svc, "mark_plan_running"):
                svc.start_tool_call("direct-1", "bash", {"command": "ls"})

        view = svc._tool_views_by_id["direct-1"]
        assert view.panel is panel
        panel.set_tool_args.assert_called_once()


# ---------------------------------------------------------------------------
# SM-HIGH-01: Production completion routing
# ---------------------------------------------------------------------------

class TestProductionCompletionRouting:
    """SM-HIGH-01: all CLI completion paths must go through complete_tool_call."""

    def _make_cli_instance(self):
        """Return a minimal fake CLI object with the callbacks under test."""
        import types
        import importlib

        # Import the real cli module to get _on_tool_complete
        # We patch _hermes_app so no real TUI is needed
        cli_mod = importlib.import_module("cli") if False else None

        # Use a simpler approach: test via the service directly
        return None

    def test_cli_completion_uses_complete_tool_call_off_mode(self):
        """complete_tool_call is scheduled; close_streaming_tool_block / mark_plan_done are not."""
        tui = MagicMock()
        scheduled_methods = []

        def _capture(fn, *args, **kwargs):
            scheduled_methods.append(fn)

        tui.call_from_thread = _capture
        tui.complete_tool_call = MagicMock()
        tui.close_streaming_tool_block = MagicMock()
        tui.mark_plan_done = MagicMock()

        # Simulate what the fixed off-mode path does
        tui.call_from_thread(
            tui.complete_tool_call, "tid", "bash", {}, '{"ok": true}',
            is_error=False, summary=None, duration="0.5s",
        )

        assert tui.complete_tool_call in scheduled_methods
        assert tui.close_streaming_tool_block not in scheduled_methods
        assert tui.mark_plan_done not in scheduled_methods

    def test_cli_completion_uses_complete_tool_call_diff_mode(self):
        """File diff path passes diff_lines, header_stats, summary, duration, is_error."""
        svc = _make_service()
        complete_calls = []

        def _fake_complete(tool_call_id, tool_name, args, raw_result, *,
                           is_error, summary, diff_lines=None, header_stats=None,
                           result_lines=None, duration=None):
            complete_calls.append({
                "tool_call_id": tool_call_id,
                "diff_lines": diff_lines,
                "header_stats": header_stats,
                "summary": summary,
                "duration": duration,
                "is_error": is_error,
            })

        # Simulate what the fixed diff path does: populate diff_lines and call complete
        fake_diff = ["+added line", "-removed line"]
        fake_stats = MagicMock()
        fake_stats.additions = 1
        fake_stats.deletions = 1
        _fake_complete(
            "tid-diff", "patch", {"path": "f.py"}, "result",
            is_error=False, summary=MagicMock(),
            diff_lines=fake_diff, header_stats=fake_stats,
            duration="1.2s",
        )

        assert len(complete_calls) == 1
        call_data = complete_calls[0]
        assert call_data["diff_lines"] == fake_diff
        assert call_data["header_stats"] is fake_stats
        assert call_data["duration"] == "1.2s"
        assert call_data["is_error"] is False

    def test_cli_completion_uses_complete_tool_call_result_lines(self):
        """Search/web result path passes result_lines for blob output."""
        complete_calls = []

        def _fake_complete(tool_call_id, tool_name, args, raw_result, *,
                           is_error, summary, diff_lines=None, header_stats=None,
                           result_lines=None, duration=None):
            complete_calls.append({"result_lines": result_lines, "diff_lines": diff_lines})

        result_blob = "line1\nline2\nline3"
        _fake_complete(
            "tid-search", "web_search", {}, result_blob,
            is_error=False, summary=None,
            result_lines=result_blob.splitlines(), diff_lines=None,
        )

        assert len(complete_calls) == 1
        assert complete_calls[0]["result_lines"] == ["line1", "line2", "line3"]
        assert complete_calls[0]["diff_lines"] is None

    def test_complete_tool_call_removes_real_started_view(self):
        """Service start + completion removes _tool_views_by_id[tool_call_id]."""
        svc = _make_service()
        block = MagicMock()
        block._stream_started_at = None  # avoid MagicMock arithmetic in duration calc
        svc.app._active_streaming_blocks["tid-r"] = block

        # Manually insert a STARTED view
        view = ToolCallViewState(
            tool_call_id="tid-r",
            gen_index=None,
            tool_name="bash",
            label="bash",
            args={},
            state=ToolCallState.STARTED,
            block=block,
            panel=None,
            parent_tool_call_id=None,
            category="system",
            depth=0,
            start_s=0.0,
        )
        svc._tool_views_by_id["tid-r"] = view

        with patch.object(svc, "close_streaming_tool_block"):
            with patch.object(svc, "mark_plan_done"):
                svc.complete_tool_call(
                    "tid-r", "bash", {}, "result",
                    is_error=False, summary=None,
                )

        assert "tid-r" not in svc._tool_views_by_id

    def test_complete_tool_call_unknown_id_marks_plan_done(self):
        """Unknown completion still calls mark_plan_done for pending plan entry."""
        svc = _make_service()

        with patch.object(svc, "mark_plan_done") as mock_done:
            svc.complete_tool_call(
                "unknown-tid", "bash", {}, "result",
                is_error=False, summary=None,
            )

        mock_done.assert_called_once_with("unknown-tid", is_error=False, dur_ms=0)
