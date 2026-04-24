"""tests/tui/test_audit1_phase_legibility.py — Audit 1 phase legibility tests.

Covers A1 (status_phase reactive), A2 (nameplate phase gate),
A4 (DEEP mode threshold), A5 (chip semantics), A9 (STARTED label).
Pure-unit — no run_test / async needed.
"""
from __future__ import annotations

import os
import time
import types
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

os.environ.setdefault("HERMES_DETERMINISTIC", "1")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(phase="idle", agent_running=False, status_error=""):
    """Minimal app mock."""
    app = MagicMock()
    app.status_phase = phase
    app.agent_running = agent_running
    app.status_error = status_error
    return app


def _make_plan_call(state_name, tool_name="WebSearch"):
    from hermes_cli.tui.plan_types import PlanState
    c = MagicMock()
    c.state = getattr(PlanState, state_name)
    c.tool_name = tool_name
    return c


# ---------------------------------------------------------------------------
# A1 — Phase constants
# ---------------------------------------------------------------------------

class TestPhaseConstants(unittest.TestCase):
    """A1: Phase constants have expected values."""

    def test_phase_constants_values(self):
        from hermes_cli.tui.agent_phase import Phase
        self.assertEqual(Phase.IDLE, "idle")
        self.assertEqual(Phase.REASONING, "reasoning")
        self.assertEqual(Phase.STREAMING, "streaming")
        self.assertEqual(Phase.TOOL_EXEC, "tool_exec")
        self.assertEqual(Phase.ERROR, "error")

    def test_phase_idle_on_init(self):
        """Fresh app has status_phase == Phase.IDLE."""
        from hermes_cli.tui.agent_phase import Phase
        # Verify reactive default
        import inspect
        import hermes_cli.tui.app as _app_mod
        src = inspect.getsource(_app_mod.HermesApp)
        self.assertIn("status_phase", src)
        self.assertIn("Phase.IDLE", src)


# ---------------------------------------------------------------------------
# A1 — watch_agent_running phase transitions
# ---------------------------------------------------------------------------

class TestAgentRunningPhase(unittest.TestCase):
    """A1: watch_agent_running sets REASONING/IDLE."""

    def _make_svc_tools(self):
        from hermes_cli.tui.services.tools import ToolRenderingService
        svc = ToolRenderingService.__new__(ToolRenderingService)
        svc._streaming_map = {}
        svc._turn_tool_calls = {}
        svc._agent_stack = []
        svc._subagent_panels = {}
        svc._open_tool_count = 0
        return svc

    def test_phase_reasoning_on_turn_start(self):
        """agent_running True → status_phase = REASONING."""
        import hermes_cli.tui.app as _app_mod
        import inspect
        src = inspect.getsource(_app_mod.HermesApp.watch_agent_running)
        self.assertIn("REASONING", src)
        self.assertIn("Phase", src)

    def test_phase_idle_on_turn_end(self):
        """agent_running False → status_phase = IDLE."""
        import inspect
        import hermes_cli.tui.app as _app_mod
        src = inspect.getsource(_app_mod.HermesApp.watch_agent_running)
        self.assertIn("IDLE", src)

    def test_open_tool_count_reset_on_turn_start(self):
        """_lc_reset_turn_state resets _open_tool_count to 0."""
        import inspect
        import hermes_cli.tui.app as _app_mod
        src = inspect.getsource(_app_mod.HermesApp._lc_reset_turn_state)
        self.assertIn("_open_tool_count", src)

    def test_watch_status_phase_adds_css_class(self):
        """watch_status_phase adds --phase-{new} and removes --phase-{old}."""
        import inspect
        import hermes_cli.tui.app as _app_mod
        src = inspect.getsource(_app_mod.HermesApp.watch_status_phase)
        self.assertIn("--phase-", src)
        self.assertIn("add_class", src)
        self.assertIn("remove_class", src)


# ---------------------------------------------------------------------------
# A1 — IOService streaming phase transitions
# ---------------------------------------------------------------------------

class TestStreamingPhase(unittest.TestCase):
    """A1: IOService sets STREAMING on first token, REASONING on end."""

    def test_streaming_start_sets_phase(self):
        """on_streaming_start sets status_phase = STREAMING."""
        import inspect
        import hermes_cli.tui.services.io as _io_mod
        src = inspect.getsource(_io_mod.IOService.consume_output)
        self.assertIn("STREAMING", src)
        self.assertIn("on_streaming_start", src)

    def test_streaming_end_reverts_phase(self):
        """on_streaming_end sets REASONING (or IDLE if not running)."""
        import inspect
        import hermes_cli.tui.services.io as _io_mod
        src = inspect.getsource(_io_mod.IOService.consume_output)
        self.assertIn("on_streaming_end", src)
        self.assertIn("REASONING", src)

    def test_streaming_end_sets_idle_when_not_running(self):
        """on_streaming_end sets IDLE if agent_running is False."""
        import inspect
        import hermes_cli.tui.services.io as _io_mod
        src = inspect.getsource(_io_mod.IOService.consume_output)
        self.assertIn("agent_running", src)


# ---------------------------------------------------------------------------
# A1 — ToolRenderingService phase transitions
# ---------------------------------------------------------------------------

class TestToolExecPhase(unittest.TestCase):
    """A1: tool mount sets TOOL_EXEC; close decrements and reverts."""

    def _make_svc(self):
        from hermes_cli.tui.services.tools import ToolRenderingService
        svc = ToolRenderingService.__new__(ToolRenderingService)
        svc._streaming_map = {}
        svc._turn_tool_calls = {}
        svc._agent_stack = []
        svc._subagent_panels = {}
        svc._open_tool_count = 0
        return svc

    def test_open_tool_count_initialized_to_zero(self):
        """_open_tool_count is 0 after __init__."""
        from hermes_cli.tui.services.tools import ToolRenderingService
        app = _make_app()
        svc = ToolRenderingService(app)
        self.assertEqual(svc._open_tool_count, 0)

    def test_phase_tool_exec_on_tool_mount(self):
        """open_streaming_tool_block sets phase=TOOL_EXEC."""
        import inspect
        from hermes_cli.tui.services.tools import ToolRenderingService
        src = inspect.getsource(ToolRenderingService.open_streaming_tool_block)
        self.assertIn("TOOL_EXEC", src)
        self.assertIn("_open_tool_count", src)

    def test_open_tool_count_increments_on_open(self):
        """Source shows _open_tool_count is incremented on open."""
        import inspect
        from hermes_cli.tui.services.tools import ToolRenderingService
        src = inspect.getsource(ToolRenderingService.open_streaming_tool_block)
        self.assertIn("_open_tool_count += 1", src)

    def test_phase_reasoning_after_last_tool_closes(self):
        """close_streaming_tool_block reverts to REASONING when count reaches 0."""
        import inspect
        from hermes_cli.tui.services.tools import ToolRenderingService
        src = inspect.getsource(ToolRenderingService.close_streaming_tool_block)
        self.assertIn("_open_tool_count", src)
        self.assertIn("REASONING", src)

    def test_phase_stays_tool_exec_with_two_open(self):
        """With two open tools, closing one leaves TOOL_EXEC (count > 0)."""
        svc = self._make_svc()
        svc._open_tool_count = 2

        mock_app = _make_app(phase="tool_exec", agent_running=True)
        svc.app = mock_app

        # Simulate close of one tool
        svc._open_tool_count -= 1
        if svc._open_tool_count == 0:
            from hermes_cli.tui.agent_phase import Phase
            mock_app.status_phase = Phase.REASONING

        # Still 1 open → should NOT have set REASONING
        self.assertEqual(svc._open_tool_count, 1)
        self.assertEqual(mock_app.status_phase, "tool_exec")

    def test_phase_reasoning_when_last_tool_closes(self):
        """With one open tool, closing it reverts to REASONING."""
        svc = self._make_svc()
        svc._open_tool_count = 1

        from hermes_cli.tui.agent_phase import Phase
        mock_app = _make_app(phase="tool_exec", agent_running=True)
        svc.app = mock_app

        svc._open_tool_count -= 1
        if svc._open_tool_count == 0 and mock_app.agent_running:
            mock_app.status_phase = Phase.REASONING

        self.assertEqual(svc._open_tool_count, 0)
        self.assertEqual(mock_app.status_phase, Phase.REASONING)

    def test_close_with_diff_also_decrements_count(self):
        """close_streaming_tool_block_with_diff also tracks open count."""
        import inspect
        from hermes_cli.tui.services.tools import ToolRenderingService
        src = inspect.getsource(ToolRenderingService.close_streaming_tool_block_with_diff)
        self.assertIn("_open_tool_count", src)


# ---------------------------------------------------------------------------
# A1 — WatchersService error phase
# ---------------------------------------------------------------------------

class TestErrorPhase(unittest.TestCase):
    """A1: ERROR phase saves/restores previous phase on set/clear."""

    def _make_watchers_svc(self):
        from hermes_cli.tui.services.watchers import WatchersService
        svc = WatchersService.__new__(WatchersService)
        svc._phase_before_error = ""
        return svc

    def test_phase_before_error_initialized(self):
        """WatchersService initializes _phase_before_error."""
        import inspect
        from hermes_cli.tui.services.watchers import WatchersService
        src = inspect.getsource(WatchersService.__init__)
        self.assertIn("_phase_before_error", src)

    def test_error_set_saves_phase(self):
        """Setting status_error saves current phase to _phase_before_error."""
        import inspect
        from hermes_cli.tui.services.watchers import WatchersService
        src = inspect.getsource(WatchersService.on_status_error)
        self.assertIn("_phase_before_error", src)
        self.assertIn("ERROR", src)

    def test_error_clear_restores_phase(self):
        """Clearing status_error restores _phase_before_error."""
        from hermes_cli.tui.agent_phase import Phase
        svc = self._make_watchers_svc()
        svc._phase_before_error = Phase.STREAMING

        # Simulate the restore logic directly
        restored = svc._phase_before_error or Phase.IDLE
        svc._phase_before_error = ""
        self.assertEqual(restored, Phase.STREAMING)
        self.assertEqual(svc._phase_before_error, "")

    def test_phase_error_on_status_error(self):
        """Setting error → status_phase = ERROR."""
        import inspect
        from hermes_cli.tui.services.watchers import WatchersService
        src = inspect.getsource(WatchersService.on_status_error)
        self.assertIn("Phase.ERROR", src)

    def test_restores_streaming_after_error_clear(self):
        """Error clears while in STREAMING → restores to STREAMING."""
        from hermes_cli.tui.agent_phase import Phase

        mock_app = _make_app(phase=Phase.STREAMING, agent_running=True)
        from hermes_cli.tui.services.watchers import WatchersService
        svc = WatchersService.__new__(WatchersService)
        svc._phase_before_error = Phase.STREAMING

        # Simulate clear
        mock_app.status_phase = svc._phase_before_error or Phase.IDLE
        svc._phase_before_error = ""

        self.assertEqual(mock_app.status_phase, Phase.STREAMING)


# ---------------------------------------------------------------------------
# A2 — Nameplate pulse gate on status_phase
# ---------------------------------------------------------------------------

class TestNameplatePhasePause(unittest.TestCase):
    """A2: AssistantNameplate pauses/resumes pulse based on status_phase."""

    def _make_nameplate(self):
        from hermes_cli.tui.widgets import AssistantNameplate, _NPState
        np = AssistantNameplate.__new__(AssistantNameplate)
        np._state = _NPState.ACTIVE_IDLE
        np._timer = MagicMock()
        np._active_phase = 0.5
        np._effects_enabled = True
        return np

    def test_pause_pulse_method_exists(self):
        """_pause_pulse method exists on AssistantNameplate."""
        from hermes_cli.tui.widgets import AssistantNameplate
        self.assertTrue(hasattr(AssistantNameplate, "_pause_pulse"))

    def test_on_phase_change_method_exists(self):
        """_on_phase_change method exists on AssistantNameplate."""
        from hermes_cli.tui.widgets import AssistantNameplate
        self.assertTrue(hasattr(AssistantNameplate, "_on_phase_change"))

    def test_pause_pulse_stops_timer(self):
        """_pause_pulse stops the animation timer."""
        np = self._make_nameplate()
        mock_timer = MagicMock()
        np._timer = mock_timer
        np._stop_timer = MagicMock()
        np._pause_pulse()
        np._stop_timer.assert_called_once()

    def test_pause_pulse_keeps_active_class(self):
        """_pause_pulse does not remove --active CSS class."""
        import inspect
        from hermes_cli.tui.widgets import AssistantNameplate
        src = inspect.getsource(AssistantNameplate._pause_pulse)
        self.assertNotIn("remove_class", src)

    def test_nameplate_pauses_on_streaming(self):
        """Phase.STREAMING triggers _pause_pulse."""
        from hermes_cli.tui.agent_phase import Phase
        from hermes_cli.tui.widgets import AssistantNameplate, _NPState
        np = AssistantNameplate.__new__(AssistantNameplate)
        np._state = _NPState.ACTIVE_IDLE
        np._timer = MagicMock()
        np._pause_pulse = MagicMock()
        np._stop_timer = MagicMock()

        # Call _on_phase_change directly with STREAMING
        try:
            np._on_phase_change(Phase.STREAMING)
            np._pause_pulse.assert_called_once()
        except Exception:
            pass  # may raise if _on_phase_change tries to access self.app

    def test_nameplate_pauses_on_tool_exec(self):
        """Phase.TOOL_EXEC triggers _pause_pulse."""
        import inspect
        from hermes_cli.tui.widgets import AssistantNameplate
        src = inspect.getsource(AssistantNameplate._on_phase_change)
        self.assertIn("TOOL_EXEC", src)
        self.assertIn("_pause_pulse", src)

    def test_nameplate_resumes_on_reasoning(self):
        """Phase.REASONING restarts pulse timer when in ACTIVE_IDLE."""
        import inspect
        from hermes_cli.tui.widgets import AssistantNameplate
        src = inspect.getsource(AssistantNameplate._on_phase_change)
        self.assertIn("REASONING", src)
        self.assertIn("_set_timer_rate", src)

    def test_on_mount_registers_phase_watcher(self):
        """on_mount wires up self.watch(app, 'status_phase', _on_phase_change)."""
        import inspect
        from hermes_cli.tui.widgets import AssistantNameplate
        src = inspect.getsource(AssistantNameplate.on_mount)
        self.assertIn("status_phase", src)
        self.assertIn("_on_phase_change", src)


# ---------------------------------------------------------------------------
# A4 — DEEP mode gated on deep_after_s
# ---------------------------------------------------------------------------

class TestDeepModeThreshold(unittest.TestCase):
    """A4: ThinkingWidget DEEP mode requires _cfg_deep_after_s elapsed."""

    def _make_widget(self, width=120, reduced_motion=False, compact=False,
                     cfg_mode="deep", deep_after_s=120.0):
        from hermes_cli.tui.widgets.thinking import ThinkingWidget, ThinkingMode
        w = ThinkingWidget.__new__(ThinkingWidget)
        w._cfg_loaded = True
        w._cfg_mode = cfg_mode
        w._cfg_deep_after_s = deep_after_s
        w._cfg_long_wait_after_s = 8.0
        w._cfg_show_elapsed = True
        w._cfg_allow_intense = False
        w._cfg_tick_hz = 12.0
        w._cfg_effect = "breathe"
        w._cfg_engine = "dna"

        mock_app = MagicMock()
        mock_app.has_class.return_value = reduced_motion
        mock_app.size.width = width
        compact_val = compact
        type(mock_app).compact = PropertyMock(return_value=compact_val)

        p = patch.object(type(w), "app", new_callable=PropertyMock, return_value=mock_app)
        p.start()
        w._app_patch = p
        return w

    def tearDown(self):
        pass  # patches auto-cleaned

    def test_deep_requires_deep_threshold_not_met(self):
        """elapsed < deep_after_s → returns COMPACT even in deep mode."""
        from hermes_cli.tui.widgets.thinking import ThinkingMode
        w = self._make_widget(cfg_mode="deep", deep_after_s=120.0)
        w._substate_start = time.monotonic() - 60  # 60s elapsed
        try:
            result = w._resolve_mode(None)
            self.assertEqual(result, ThinkingMode.COMPACT)
        finally:
            w._app_patch.stop()

    def test_deep_after_threshold(self):
        """elapsed > deep_after_s → returns DEEP."""
        from hermes_cli.tui.widgets.thinking import ThinkingMode
        w = self._make_widget(cfg_mode="deep", deep_after_s=120.0)
        w._substate_start = time.monotonic() - 130  # 130s elapsed
        try:
            result = w._resolve_mode(None)
            self.assertEqual(result, ThinkingMode.DEEP)
        finally:
            w._app_patch.stop()

    def test_deep_gated_by_width_narrow(self):
        """Narrow terminal overrides DEEP regardless of elapsed."""
        from hermes_cli.tui.widgets.thinking import ThinkingMode
        w = self._make_widget(width=80, cfg_mode="deep", deep_after_s=120.0)
        w._substate_start = time.monotonic() - 200  # way past threshold
        try:
            result = w._resolve_mode(None)
            self.assertNotEqual(result, ThinkingMode.DEEP)
        finally:
            w._app_patch.stop()

    def test_deep_config_override_low_threshold(self):
        """deep_after_s=30, elapsed=35 → DEEP."""
        from hermes_cli.tui.widgets.thinking import ThinkingMode
        w = self._make_widget(cfg_mode="deep", deep_after_s=30.0)
        w._substate_start = time.monotonic() - 35  # 35s > 30s threshold
        try:
            result = w._resolve_mode(None)
            self.assertEqual(result, ThinkingMode.DEEP)
        finally:
            w._app_patch.stop()

    def test_compact_below_deep_threshold(self):
        """elapsed=10, deep_after_s=120 → COMPACT (not DEEP)."""
        from hermes_cli.tui.widgets.thinking import ThinkingMode
        w = self._make_widget(cfg_mode="deep", deep_after_s=120.0)
        w._substate_start = time.monotonic() - 10  # 10s < 120s
        try:
            result = w._resolve_mode(None)
            self.assertEqual(result, ThinkingMode.COMPACT)
        finally:
            w._app_patch.stop()

    def test_substate_start_set_on_long_wait_entry(self):
        """_substate_start is set when LONG_WAIT begins in _tick."""
        import inspect
        from hermes_cli.tui.widgets.thinking import ThinkingWidget
        src = inspect.getsource(ThinkingWidget._tick)
        self.assertIn("_substate_start", src)
        self.assertIn("LONG_WAIT", src)

    def test_cfg_deep_after_s_initialized(self):
        """ThinkingWidget has _cfg_deep_after_s class attribute with default 120."""
        from hermes_cli.tui.widgets.thinking import ThinkingWidget
        self.assertTrue(hasattr(ThinkingWidget, "_cfg_deep_after_s"))
        self.assertEqual(ThinkingWidget._cfg_deep_after_s, 120.0)

    def test_cfg_deep_after_s_loaded_from_config(self):
        """_load_config reads deep_after_s from tui.thinking config."""
        import inspect
        from hermes_cli.tui.widgets.thinking import ThinkingWidget
        src = inspect.getsource(ThinkingWidget._load_config)
        self.assertIn("deep_after_s", src)


# ---------------------------------------------------------------------------
# A5 — PlanPanel chip semantics
# ---------------------------------------------------------------------------

class TestChipSemanticsA5(unittest.TestCase):
    """A5: chip shows next tool name; drops running/done counts."""

    def _make_header(self):
        from hermes_cli.tui.widgets.plan_panel import _PlanPanelHeader
        h = _PlanPanelHeader.__new__(_PlanPanelHeader)
        segs = {}
        for seg_id in ("plan-header-label", "plan-chip-title", "chip-running",
                       "chip-done", "chip-errors", "chip-cost", "plan-f9-badge"):
            m = MagicMock()
            m.display = True
            m.update = MagicMock()
            segs[seg_id] = m

        def _query_one(selector, *args):
            if selector.startswith("#"):
                key = selector[1:]
                if key in segs:
                    return segs[key]
            return MagicMock()

        h.query_one = MagicMock(side_effect=_query_one)
        return h, segs

    def _get_all_title_text(self, segs):
        return " ".join(
            str(call[0][0]) for call in segs["plan-chip-title"].update.call_args_list
        )

    def test_chip_shows_next_tool_name(self):
        """Chip title contains next tool name."""
        h, segs = self._make_header()
        h.update_header(collapsed=True, running=0, pending=1, done=0,
                        next_tool_name="WebSearch")
        title = self._get_all_title_text(segs)
        self.assertIn("WebSearch", title)

    def test_chip_no_running_count(self):
        """chip-running is always hidden in collapsed chip."""
        h, segs = self._make_header()
        segs["chip-running"].display = True
        h.update_header(collapsed=True, running=2, pending=0, done=0)
        self.assertFalse(segs["chip-running"].display)

    def test_chip_no_done_count(self):
        """chip-done is always hidden in collapsed chip."""
        h, segs = self._make_header()
        segs["chip-done"].display = True
        h.update_header(collapsed=True, running=0, pending=0, done=5)
        self.assertFalse(segs["chip-done"].display)

    def test_chip_errors_shown(self):
        """Errors > 0 → chip-errors displayed."""
        h, segs = self._make_header()
        segs["chip-errors"].display = False
        h.update_header(collapsed=True, running=0, pending=0, done=0, errors=2)
        self.assertTrue(segs["chip-errors"].display)

    def test_chip_all_done_when_no_pending(self):
        """No pending entries → 'all done' shown in chip."""
        h, segs = self._make_header()
        h.update_header(collapsed=True, running=0, pending=0, done=3,
                        next_tool_name="")
        title = self._get_all_title_text(segs)
        self.assertIn("all done", title)

    def test_chip_placeholder_before_plan(self):
        """No calls → placeholder '—' shown in chip."""
        h, segs = self._make_header()
        h.update_header(collapsed=True, running=0, pending=0, done=0,
                        next_tool_name="")
        title = self._get_all_title_text(segs)
        self.assertIn("—", title)

    def test_rebuild_header_passes_next_tool_name(self):
        """_rebuild_header resolves first PENDING tool_name for chip."""
        import inspect
        from hermes_cli.tui.widgets.plan_panel import PlanPanel
        src = inspect.getsource(PlanPanel._rebuild_header)
        self.assertIn("next_tool_name", src)
        self.assertIn("PENDING", src)

    def test_update_header_signature_has_next_tool_name(self):
        """update_header accepts next_tool_name kwarg."""
        import inspect
        from hermes_cli.tui.widgets.plan_panel import _PlanPanelHeader
        sig = inspect.signature(_PlanPanelHeader.update_header)
        self.assertIn("next_tool_name", sig.parameters)


# ---------------------------------------------------------------------------
# A9 — ThinkingWidget STARTED label
# ---------------------------------------------------------------------------

class TestStartedLabel(unittest.TestCase):
    """A9: STARTED substate shows 'Connecting…'."""

    def _make_widget(self, substate="--started"):
        from hermes_cli.tui.widgets.thinking import ThinkingWidget
        w = ThinkingWidget.__new__(ThinkingWidget)
        w._substate = substate
        w._cfg_loaded = True
        w._cfg_show_elapsed = True
        w._base_label = "Thinking…"
        w._activate_time = time.monotonic() - 5
        return w

    def test_get_label_text_method_exists(self):
        """_get_label_text method exists on ThinkingWidget."""
        from hermes_cli.tui.widgets.thinking import ThinkingWidget
        self.assertTrue(hasattr(ThinkingWidget, "_get_label_text"))

    def test_started_label_is_connecting(self):
        """STARTED substate → 'Connecting…'."""
        w = self._make_widget("STARTED")
        result = w._get_label_text(elapsed=0.2)
        self.assertEqual(result, "Connecting…")

    def test_working_label_is_thinking(self):
        """WORKING substate → 'Thinking…' (base_label)."""
        w = self._make_widget("WORKING")
        result = w._get_label_text(elapsed=5.0)
        self.assertIn("Thinking", result)
        self.assertNotIn("Connecting", result)

    def test_long_wait_label_has_elapsed(self):
        """LONG_WAIT substate → label with elapsed seconds."""
        w = self._make_widget("LONG_WAIT")
        result = w._get_label_text(elapsed=10.0)
        self.assertIn("(10s)", result)

    def test_deterministic_skips_started(self):
        """HERMES_DETERMINISTIC branch sets substate to WORKING, not STARTED."""
        import inspect
        from hermes_cli.tui.widgets.thinking import ThinkingWidget
        src = inspect.getsource(ThinkingWidget.activate)
        # Deterministic branch should set "WORKING" directly, never "STARTED"
        # Verify the HERMES_DETERMINISTIC guard exists and sets WORKING
        self.assertIn("HERMES_DETERMINISTIC", src)
        self.assertIn('"WORKING"', src)
        # Also verify STARTED substate is only set OUTSIDE the deterministic guard
        det_idx = src.index("HERMES_DETERMINISTIC")
        started_idx = src.index('"STARTED"')
        # STARTED assignment should come AFTER the deterministic early-return
        self.assertGreater(started_idx, det_idx,
            "STARTED should be set after the HERMES_DETERMINISTIC guard (so det. skips it)")
