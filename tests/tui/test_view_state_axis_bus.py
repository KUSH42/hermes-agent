"""Tests for AXIS-1/2/3/4/5: DensityTier enum, ToolCallViewState axis fields,
set_axis observer hook, kind stamp at COMPLETING, density mirror from collapse.

Spec: /home/xush/.hermes/2026-04-25-axis-bus-view-state-spec.md
"""
from __future__ import annotations

import threading
import types
import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# AXIS-1: DensityTier enum
# ---------------------------------------------------------------------------

class TestDensityTier:
    def test_density_tier_str_value(self):
        from hermes_cli.tui.tool_panel.density import DensityTier
        assert DensityTier.HERO.value == "hero"
        assert DensityTier.DEFAULT.value == "default"
        assert DensityTier.COMPACT.value == "compact"
        assert DensityTier.TRACE.value == "trace"

    def test_density_tier_rank_ordering(self):
        from hermes_cli.tui.tool_panel.density import DensityTier
        assert DensityTier.HERO.rank < DensityTier.DEFAULT.rank
        assert DensityTier.DEFAULT.rank < DensityTier.COMPACT.rank
        assert DensityTier.COMPACT.rank < DensityTier.TRACE.rank

    def test_density_tier_is_str_enum(self):
        from hermes_cli.tui.tool_panel.density import DensityTier
        assert DensityTier.DEFAULT == "default"
        assert isinstance(DensityTier.COMPACT, str)


# ---------------------------------------------------------------------------
# AXIS-2: ToolCallViewState kind / density / _watchers fields
# ---------------------------------------------------------------------------

class TestViewStateFields:
    def _make_view(self):
        from hermes_cli.tui.services.tools import ToolCallViewState, ToolCallState
        return ToolCallViewState(
            tool_call_id="tc1",
            gen_index=None,
            tool_name="read_file",
            label="Read File",
            args={},
            state=ToolCallState.STARTED,
            block=None,
            panel=None,
            parent_tool_call_id=None,
            category="file_tools",
            depth=0,
            start_s=0.0,
        )

    def test_view_state_kind_default_none(self):
        view = self._make_view()
        assert view.kind is None

    def test_view_state_density_default_default(self):
        from hermes_cli.tui.tool_panel.density import DensityTier
        view = self._make_view()
        assert view.density == DensityTier.DEFAULT

    def test_view_state_existing_callsites_compile(self):
        from hermes_cli.tui.services.tools import ToolCallViewState, ToolCallState
        # Construct without new fields — must succeed with defaults
        view = ToolCallViewState(
            tool_call_id="tc2",
            gen_index=1,
            tool_name="terminal",
            label="Terminal",
            args={"command": "ls"},
            state=ToolCallState.GENERATED,
            block=None,
            panel=None,
            parent_tool_call_id=None,
            category="shell",
            depth=0,
            start_s=0.1,
        )
        assert view.kind is None
        from hermes_cli.tui.tool_panel.density import DensityTier
        assert view.density == DensityTier.DEFAULT
        assert view._watchers == []


# ---------------------------------------------------------------------------
# AXIS-3: set_axis observer hook
# ---------------------------------------------------------------------------

class TestSetAxisWatcher:
    def _make_view(self):
        from hermes_cli.tui.services.tools import ToolCallViewState, ToolCallState
        return ToolCallViewState(
            tool_call_id="tc3",
            gen_index=None,
            tool_name="web_search",
            label="Web Search",
            args={},
            state=ToolCallState.STARTED,
            block=None,
            panel=None,
            parent_tool_call_id=None,
            category="search",
            depth=0,
            start_s=0.0,
        )

    def test_set_axis_fires_watcher_with_old_and_new(self):
        from hermes_cli.tui.services.tools import set_axis, add_axis_watcher
        from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind
        view = self._make_view()
        calls = []

        def watcher(v, axis, old, new):
            calls.append((axis, old, new))

        add_axis_watcher(view, watcher)
        new_kind = ClassificationResult(kind=ResultKind.TEXT, confidence=1.0)
        set_axis(view, "kind", new_kind)

        assert len(calls) == 1
        axis, old, new = calls[0]
        assert axis == "kind"
        assert old is None
        assert new is new_kind

    def test_set_axis_no_op_when_unchanged(self):
        from hermes_cli.tui.services.tools import set_axis, add_axis_watcher
        view = self._make_view()
        calls = []

        add_axis_watcher(view, lambda v, a, o, n: calls.append(a))
        # density is already DEFAULT — setting to DEFAULT again is a no-op
        from hermes_cli.tui.tool_panel.density import DensityTier
        set_axis(view, "density", DensityTier.DEFAULT)

        assert calls == []

    def test_set_axis_watcher_exception_isolated(self):
        from hermes_cli.tui.services.tools import set_axis, add_axis_watcher
        from hermes_cli.tui.tool_panel.density import DensityTier
        view = self._make_view()
        second_calls = []

        def bad_watcher(v, a, o, n):
            raise RuntimeError("watcher boom")

        def good_watcher(v, a, o, n):
            second_calls.append(n)

        add_axis_watcher(view, bad_watcher)
        add_axis_watcher(view, good_watcher)

        with patch("hermes_cli.tui.services.tools.logger") as mock_log:
            set_axis(view, "density", DensityTier.COMPACT)
            mock_log.exception.assert_called_once()

        # field still updated
        assert view.density == DensityTier.COMPACT
        # second watcher still ran
        assert second_calls == [DensityTier.COMPACT]

    def test_remove_axis_watcher_idempotent(self):
        from hermes_cli.tui.services.tools import add_axis_watcher, remove_axis_watcher
        view = self._make_view()
        watcher = MagicMock()
        add_axis_watcher(view, watcher)
        remove_axis_watcher(view, watcher)
        # second remove must not raise
        remove_axis_watcher(view, watcher)


# ---------------------------------------------------------------------------
# AXIS-4: kind stamp at COMPLETING
# ---------------------------------------------------------------------------

class TestKindStampOnCompleting:
    def _make_service(self):
        from hermes_cli.tui.services.tools import ToolRenderingService
        app = MagicMock()
        app._turn_start_monotonic = None
        app._active_streaming_blocks = {}
        app._streaming_tool_count = 0
        app.planned_calls = []
        app._browse_total = 0
        app._user_scrolled_up = False
        svc = ToolRenderingService.__new__(ToolRenderingService)
        svc.app = app
        svc._streaming_map = {}
        svc._subagent_panels = {}
        svc._tool_views_by_id = {}
        svc._tool_views_by_gen_index = {}
        svc._pending_gen_arg_deltas = {}
        svc._turn_tool_calls = {}
        svc._agent_stack = []
        svc._open_tool_count = 0
        svc._state_lock = threading.RLock()
        from hermes_cli.tui.services.plan_sync import PlanSyncBroker
        svc._plan_broker = PlanSyncBroker(svc)
        return svc

    def _make_view(self):
        from hermes_cli.tui.services.tools import ToolCallViewState, ToolCallState
        return ToolCallViewState(
            tool_call_id="tc4",
            gen_index=None,
            tool_name="web_search",
            label="Web Search",
            args={"query": "python"},
            state=ToolCallState.STREAMING,
            block=None,
            panel=None,
            parent_tool_call_id=None,
            category="search",
            depth=0,
            start_s=0.0,
        )

    def test_complete_tool_call_stamps_kind(self):
        from hermes_cli.tui.services.tools import set_axis
        from hermes_cli.tui.content_classifier import classify_content
        from hermes_cli.tui.tool_payload import ToolPayload

        svc = self._make_service()
        view = self._make_view()
        svc._tool_views_by_id["tc4"] = view
        svc.app._active_streaming_blocks["tc4"] = MagicMock()

        with patch.object(svc, "close_streaming_tool_block"), \
             patch.object(svc, "mark_plan_done"), \
             patch("hermes_cli.tui.services.tools.set_axis", wraps=set_axis) as mock_sa, \
             patch("hermes_cli.tui.perf._tool_probe") as mock_probe:
            mock_probe.record = MagicMock()
            svc.complete_tool_call(
                "tc4", "web_search", {"query": "python"}, "",
                is_error=False, summary=None, result_lines=["result line"]
            )

        # kind should be stamped
        assert view.kind is not None

    def test_complete_tool_call_kind_watcher_fires(self):
        from hermes_cli.tui.services.tools import add_axis_watcher, set_axis

        svc = self._make_service()
        view = self._make_view()
        svc._tool_views_by_id["tc4"] = view
        svc.app._active_streaming_blocks["tc4"] = MagicMock()

        watcher_calls = []
        add_axis_watcher(view, lambda v, a, o, n: watcher_calls.append((a, o, n)))

        with patch.object(svc, "close_streaming_tool_block"), \
             patch.object(svc, "mark_plan_done"), \
             patch("hermes_cli.tui.perf._tool_probe") as mock_probe:
            mock_probe.record = MagicMock()
            svc.complete_tool_call(
                "tc4", "web_search", {"query": "python"}, "",
                is_error=False, summary=None, result_lines=["foo"]
            )

        # at least one watcher call for axis="kind" with old=None
        kind_calls = [c for c in watcher_calls if c[0] == "kind"]
        assert len(kind_calls) == 1
        assert kind_calls[0][1] is None   # old
        assert kind_calls[0][2] is not None  # new

    def test_complete_tool_call_classifier_error_safe(self):
        from hermes_cli.tui.services.tools import ToolCallState

        svc = self._make_service()
        view = self._make_view()
        svc._tool_views_by_id["tc4"] = view
        svc.app._active_streaming_blocks["tc4"] = MagicMock()

        # R3-AXIS-03: terminal state reached via real close path → helper.
        with patch.object(svc, "_get_output_panel", return_value=None), \
             patch.object(svc, "mark_plan_done"), \
             patch("hermes_cli.tui.perf._tool_probe") as mock_probe, \
             patch("hermes_cli.tui.content_classifier.classify_content",
                   side_effect=RuntimeError("boom")), \
             patch("hermes_cli.tui.services.tools.logger") as mock_log:
            mock_probe.record = MagicMock()
            svc.complete_tool_call(
                "tc4", "web_search", {"query": "python"}, "",
                is_error=False, summary=None, result_lines=["x"]
            )

        # completion still reached terminal state
        assert view.state in (ToolCallState.DONE, ToolCallState.ERROR)
        # kind remains None
        assert view.kind is None
        # exception was logged
        mock_log.exception.assert_called()


# ---------------------------------------------------------------------------
# AXIS-5: density mirror from collapse toggle
# ---------------------------------------------------------------------------

class TestDensityMirrorFromCollapse:
    @pytest.mark.asyncio
    async def test_collapse_toggle_mirrors_density(self):
        from hermes_cli.tui.app import HermesApp
        from hermes_cli.tui.widgets import OutputPanel
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.services.tools import (
            ToolCallViewState, ToolCallState, add_axis_watcher,
        )
        from hermes_cli.tui.tool_panel.density import DensityTier

        app = HermesApp(cli=MagicMock())
        async with app.run_test(size=(80, 30)) as pilot:
            for _ in range(5):
                await pilot.pause()

            app.agent_running = True
            for _ in range(3):
                await pilot.pause()

            # Open a gen block and start a tool call to get a view state
            app._svc_tools.open_gen_block("terminal")
            for _ in range(3):
                await pilot.pause()

            output = app.query_one(OutputPanel)
            panel = output.query_one(ToolPanel)

            # Manually wire the panel to a view state via _plan_tool_call_id
            tool_call_id = "density-test-tc"
            # Move 1: resolver blocks toggle during STARTED/STREAMING.
            # Use DONE state so the user override path is exercised.
            view = ToolCallViewState(
                tool_call_id=tool_call_id,
                gen_index=None,
                tool_name="terminal",
                label="Terminal",
                args={},
                state=ToolCallState.DONE,
                block=panel._block,
                panel=panel,
                parent_tool_call_id=None,
                category="shell",
                depth=0,
                start_s=0.0,
            )
            app._svc_tools._tool_views_by_id[tool_call_id] = view
            panel._plan_tool_call_id = tool_call_id

            watcher_calls = []
            add_axis_watcher(view, lambda v, a, o, n: watcher_calls.append((a, o, n)))

            # Focus panel so Enter binding fires
            panel.focus()
            for _ in range(3):
                await pilot.pause()

            # First toggle: DEFAULT → COMPACT (user override, body < threshold → would stay DEFAULT
            # but user_override=True forces COMPACT)
            await pilot.press("enter")
            for _ in range(3):
                await pilot.pause()

            density_calls = [c for c in watcher_calls if c[0] == "density"]
            assert len(density_calls) >= 1, f"Expected density watcher call; got {watcher_calls}"
            assert density_calls[0][1] == DensityTier.DEFAULT  # old
            assert density_calls[0][2] == DensityTier.COMPACT  # new

            # Second toggle: COMPACT → DEFAULT
            watcher_calls.clear()
            await pilot.press("enter")
            for _ in range(3):
                await pilot.pause()

            density_calls = [c for c in watcher_calls if c[0] == "density"]
            assert len(density_calls) >= 1, f"Expected density watcher call on 2nd toggle; got {watcher_calls}"
            assert density_calls[0][1] == DensityTier.COMPACT  # old
            assert density_calls[0][2] == DensityTier.DEFAULT  # new
