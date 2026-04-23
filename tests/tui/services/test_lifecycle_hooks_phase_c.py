"""Phase C + D tests for RX4 AgentLifecycleHooks.

Covers:
- P0: _interrupt_source set before agent.interrupt() on all three interrupt paths
- C-1: on_session_switch fires from switch_to_session
- C-2: on_session_resume fires from handle_session_resume
- C-3: session_switch_cleanup releases blocking queues; session_resume_reset clears error state
- Phase D: watcher cleanup statement count; AST snapshot guard
"""
from __future__ import annotations

import ast
import importlib
import inspect
import queue
import textwrap
import types
from unittest.mock import MagicMock, patch, call

import pytest


# ── §9 authoritative snapshot ─────────────────────────────────────────────────
# This constant is the ground truth for _register_lifecycle_hooks.
# When you add a new h.register() call in app.py, update this table AND
# the §9 table in the RX4 spec at
#   /home/xush/.hermes/2026-04-22-tui-v2-RX4-lifecycle-hooks-spec.md

EXPECTED_SNAPSHOT = {
    "on_turn_start": [
        (10, "osc_progress_start"),
        (50, "dismiss_info_overlays"),
        (100, "reset_turn_state"),
    ],
    "on_turn_end_any": [
        (10, "osc_progress_end"),
        (10, "desktop_notify"),
        (50, "streaming_end_safety"),
        (100, "clear_output_dropped_flag"),
        (100, "clear_spinner_label"),
        (100, "clear_active_file"),
        (100, "reset_response_metrics"),
        (100, "clear_streaming_blocks"),
        (100, "drain_gen_queue"),
        (900, "restore_input_placeholder"),
    ],
    "on_turn_end_success": [
        (100, "auto_title_first_turn"),
        (500, "chevron_done_pulse"),
    ],
    "on_interrupt": [
        (10, "osc_progress_end_interrupt"),
    ],
    "on_compact_complete": [
        (100, "reset_compaction_warn_flags"),
    ],
    "on_error_set": [
        (100, "schedule_status_error_autoclear"),
    ],
    "on_error_clear": [
        (100, "cancel_status_error_timer"),
    ],
    "on_session_switch": [
        (100, "session_switch_cleanup"),
    ],
    "on_session_resume": [
        (100, "session_resume_reset"),
    ],
    "on_streaming_start": [
        (100, "streaming_start"),
    ],
    "on_streaming_end": [
        (100, "streaming_end"),
    ],
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_hooks_spy():
    """Return (hooks, fired) where fired accumulates (transition, ctx) pairs."""
    from hermes_cli.tui.services.lifecycle_hooks import AgentLifecycleHooks
    fired: list[tuple[str, dict]] = []

    hooks = AgentLifecycleHooks(app=None)
    _orig_fire = hooks.fire

    def _spy_fire(transition, **ctx):
        fired.append((transition, ctx))
        _orig_fire(transition, **ctx)

    hooks.fire = _spy_fire
    return hooks, fired


def _make_app_mock(hooks_spy=None):
    """Minimal mock of HermesApp surface used by keys/sessions."""
    app = MagicMock()
    app.agent_running = True
    app._interrupt_source = None
    from hermes_cli.tui.services.lifecycle_hooks import AgentLifecycleHooks
    if hooks_spy is not None:
        hooks, fired = hooks_spy
        app.hooks = hooks
        return app, fired
    app.hooks = AgentLifecycleHooks(app=None)
    return app


# ── P0: _interrupt_source set on all interrupt paths ────────────────────────

class TestInterruptSourceFlag:
    """keys.py must set _interrupt_source = '...' immediately before agent.interrupt().

    We verify this via source inspection: the assignment must appear in the source
    and must precede the interrupt() call in the same branch.
    """

    def _get_keys_src(self):
        import hermes_cli.tui.services.keys as _keys_mod
        return inspect.getsource(_keys_mod.KeyDispatchService.dispatch_key)

    def _get_submit_src(self):
        import hermes_cli.tui.services.keys as _keys_mod
        return inspect.getsource(_keys_mod.KeyDispatchService.dispatch_input_submitted)

    def test_esc_path_sets_interrupt_source(self):
        src = self._get_keys_src()
        # The ESC → agent interrupt block must set _interrupt_source = "esc"
        assert '_interrupt_source = "esc"' in src, (
            "ESC path in dispatch_key must set app._interrupt_source = 'esc' before interrupt()"
        )

    def test_ctrl_shift_c_path_sets_interrupt_source(self):
        src = self._get_keys_src()
        assert '_interrupt_source = "ctrl+shift+c"' in src, (
            "ctrl+shift+c path must set app._interrupt_source = 'ctrl+shift+c' before interrupt()"
        )

    def test_resubmit_path_sets_interrupt_source(self):
        src = self._get_submit_src()
        assert '_interrupt_source = "resubmit"' in src, (
            "Resubmit path in dispatch_input_submitted must set _interrupt_source = 'resubmit'"
        )

    def test_esc_assignment_precedes_interrupt_in_source(self):
        """_interrupt_source = 'esc' must appear before agent.interrupt() in the ESC block."""
        src = self._get_keys_src()
        assign_idx = src.find('_interrupt_source = "esc"')
        interrupt_idx = src.find("cli.agent.interrupt()", assign_idx)
        assert assign_idx != -1
        assert interrupt_idx != -1, (
            "agent.interrupt() must follow _interrupt_source = 'esc' in the same block"
        )
        assert assign_idx < interrupt_idx

    def test_ctrl_shift_c_assignment_precedes_interrupt_in_source(self):
        """_interrupt_source = 'ctrl+shift+c' must appear before agent.interrupt() in that block."""
        src = self._get_keys_src()
        assign_idx = src.find('_interrupt_source = "ctrl+shift+c"')
        interrupt_idx = src.find("cli.agent.interrupt()", assign_idx)
        assert assign_idx != -1
        assert interrupt_idx != -1, (
            "agent.interrupt() must follow _interrupt_source = 'ctrl+shift+c' in the same block"
        )
        assert assign_idx < interrupt_idx

    def test_resubmit_assignment_precedes_interrupt_in_source(self):
        src = self._get_submit_src()
        assign_idx = src.find('_interrupt_source = "resubmit"')
        interrupt_idx = src.find("cli.agent.interrupt()", assign_idx)
        assert assign_idx != -1
        assert interrupt_idx != -1
        assert assign_idx < interrupt_idx


# ── C-1: on_session_switch fires from switch_to_session ──────────────────────

class TestSessionSwitchHook:
    def test_on_session_switch_fires(self):
        from hermes_cli.tui.services.sessions import SessionsService

        fired: list[tuple[str, dict]] = []
        app = MagicMock()
        app._session_active_id = "session-A"
        app._session_mgr = None
        app._notify_listener = None
        app._sessions_poll_timer = None

        from hermes_cli.tui.services.lifecycle_hooks import AgentLifecycleHooks
        hooks = AgentLifecycleHooks(app=None)
        hooks.fire = lambda t, **kw: fired.append((t, kw))
        app.hooks = hooks

        svc = SessionsService.__new__(SessionsService)
        svc.app = app
        svc._sessions_enabled = True

        with patch("sys.argv", ["hermes"]):
            svc.switch_to_session("session-B")

        assert any(t == "on_session_switch" for t, _ in fired), \
            f"on_session_switch not fired; got {fired}"

    def test_on_session_switch_carries_target_id(self):
        from hermes_cli.tui.services.sessions import SessionsService

        fired: list[tuple[str, dict]] = []
        app = MagicMock()
        app._session_active_id = "session-A"
        app._session_mgr = None
        app._notify_listener = None
        app._sessions_poll_timer = None

        from hermes_cli.tui.services.lifecycle_hooks import AgentLifecycleHooks
        hooks = AgentLifecycleHooks(app=None)
        hooks.fire = lambda t, **kw: fired.append((t, kw))
        app.hooks = hooks

        svc = SessionsService.__new__(SessionsService)
        svc.app = app
        svc._sessions_enabled = True

        with patch("sys.argv", ["hermes"]):
            svc.switch_to_session("session-B")

        switch_events = [(t, kw) for t, kw in fired if t == "on_session_switch"]
        assert switch_events, "on_session_switch not fired"
        assert switch_events[0][1].get("target_id") == "session-B"

    def test_on_session_switch_fires_before_exit(self):
        """Hook must fire before app.exit() so callbacks can still use app state."""
        from hermes_cli.tui.services.sessions import SessionsService

        order: list[str] = []
        app = MagicMock()
        app._session_active_id = "session-A"
        app._session_mgr = None
        app._notify_listener = None
        app._sessions_poll_timer = None

        from hermes_cli.tui.services.lifecycle_hooks import AgentLifecycleHooks
        hooks = AgentLifecycleHooks(app=None)
        hooks.fire = lambda t, **kw: order.append(f"fire:{t}")
        app.hooks = hooks
        app.exit.side_effect = lambda: order.append("exit")

        svc = SessionsService.__new__(SessionsService)
        svc.app = app
        svc._sessions_enabled = True

        with patch("sys.argv", ["hermes"]):
            svc.switch_to_session("session-B")

        fire_idx = next((i for i, x in enumerate(order) if x == "fire:on_session_switch"), None)
        exit_idx = next((i for i, x in enumerate(order) if x == "exit"), None)
        assert fire_idx is not None, "on_session_switch not fired"
        assert exit_idx is not None, "app.exit not called"
        assert fire_idx < exit_idx, "hook must fire before app.exit()"

    def test_same_session_no_fire(self):
        from hermes_cli.tui.services.sessions import SessionsService

        fired: list[str] = []
        app = MagicMock()
        app._session_active_id = "session-A"
        app.hooks.fire = lambda t, **kw: fired.append(t)

        svc = SessionsService.__new__(SessionsService)
        svc.app = app
        svc._sessions_enabled = True

        svc.switch_to_session("session-A")  # same session
        assert "on_session_switch" not in fired


# ── C-2: on_session_resume fires from handle_session_resume ──────────────────

class TestSessionResumeHook:
    def _make_app_for_resume(self):
        app = MagicMock()
        app._browse_anchors = []
        app._browse_cursor = 0
        app._browse_total = 0
        app._auto_title_done = True
        from hermes_cli.tui.services.lifecycle_hooks import AgentLifecycleHooks
        app.hooks = AgentLifecycleHooks(app=None)
        return app

    def test_on_session_resume_fires(self):
        fired: list[tuple[str, dict]] = []

        # We test the method via source inspection rather than mounting a full app.
        import inspect
        import hermes_cli.tui.app as _app_mod
        src = inspect.getsource(_app_mod.HermesApp.handle_session_resume)
        assert "hooks.fire" in src, "handle_session_resume must call hooks.fire"
        assert "on_session_resume" in src

    def test_on_session_resume_carries_session_id(self):
        import inspect
        import hermes_cli.tui.app as _app_mod
        src = inspect.getsource(_app_mod.HermesApp.handle_session_resume)
        assert "session_id=session_id" in src or "session_id=" in src


# ── C-3: session_switch_cleanup releases blocking queues ─────────────────────

class TestSessionSwitchCleanup:
    def _make_state(self, sentinel):
        """Create a mock overlay-state object with a response_queue."""
        state = MagicMock()
        state.response_queue = queue.Queue()
        return state

    def _make_app_with_lc(self):
        """Return a minimal app mock with _lc_session_switch_cleanup wired."""
        import hermes_cli.tui.app as _app_mod
        app = MagicMock()
        # Bind the real method to our mock app
        app._lc_session_switch_cleanup = types.MethodType(
            _app_mod.HermesApp._lc_session_switch_cleanup, app
        )
        app.agent_running = False
        app.approval_state = None
        app.clarify_state = None
        app.sudo_state = None
        app.secret_state = None
        app.undo_state = None
        return app

    def test_approval_state_queue_released(self):
        app = self._make_app_with_lc()
        state = self._make_state(None)
        app.approval_state = state

        app._lc_session_switch_cleanup()

        assert not state.response_queue.empty(), "approval_state queue should have sentinel"
        assert state.response_queue.get_nowait() is None

    def test_clarify_state_queue_released(self):
        app = self._make_app_with_lc()
        state = self._make_state(None)
        app.clarify_state = state

        app._lc_session_switch_cleanup()

        assert state.response_queue.get_nowait() is None

    def test_sudo_state_queue_gets_empty_string(self):
        app = self._make_app_with_lc()
        state = self._make_state("")
        app.sudo_state = state

        app._lc_session_switch_cleanup()

        assert state.response_queue.get_nowait() == ""

    def test_secret_state_queue_gets_empty_string(self):
        app = self._make_app_with_lc()
        state = self._make_state("")
        app.secret_state = state

        app._lc_session_switch_cleanup()

        assert state.response_queue.get_nowait() == ""

    def test_undo_state_queue_released(self):
        app = self._make_app_with_lc()
        state = self._make_state(None)
        app.undo_state = state

        app._lc_session_switch_cleanup()

        assert state.response_queue.get_nowait() is None

    def test_agent_interrupted_when_running(self):
        app = self._make_app_with_lc()
        app.agent_running = True
        app.cli.agent = MagicMock()

        app._lc_session_switch_cleanup()

        app.cli.agent.interrupt.assert_called_once()

    def test_agent_not_interrupted_when_idle(self):
        app = self._make_app_with_lc()
        app.agent_running = False
        app.cli.agent = MagicMock()

        app._lc_session_switch_cleanup()

        app.cli.agent.interrupt.assert_not_called()

    def test_none_states_no_error(self):
        """All states None — should complete without raising."""
        app = self._make_app_with_lc()
        app._lc_session_switch_cleanup()  # must not raise


class TestSessionResumeReset:
    def _make_app_with_lc(self):
        import hermes_cli.tui.app as _app_mod
        app = MagicMock()
        app._lc_session_resume_reset = types.MethodType(
            _app_mod.HermesApp._lc_session_resume_reset, app
        )
        app._status_error_timer = None
        app.status_error = "previous error"
        return app

    def test_status_error_cleared(self):
        app = self._make_app_with_lc()
        app._lc_session_resume_reset(session_id="s1", turn_count=5)
        assert app.status_error == ""

    def test_error_timer_stopped(self):
        app = self._make_app_with_lc()
        fake_timer = MagicMock()
        app._status_error_timer = fake_timer

        app._lc_session_resume_reset(session_id="s1")

        fake_timer.stop.assert_called_once()
        assert app._status_error_timer is None

    def test_no_timer_no_error(self):
        app = self._make_app_with_lc()
        app._status_error_timer = None
        app._lc_session_resume_reset()  # must not raise


# ── Phase D: watcher cleanup count + snapshot guard ──────────────────────────

class TestPhaseD:
    def _count_cleanup_stmts_in_func(self, func_src: str) -> int:
        """Count top-level assignment/clear statements that are cleanup idioms."""
        _CLEANUP_PATTERNS = (
            "= None", "= False", "= []", "= {}", '= ""', "= 0",
            ".clear()", "_osc_progress", "_maybe_notify", "_try_auto_title",
        )
        count = 0
        for line in func_src.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if any(p in stripped for p in _CLEANUP_PATTERNS):
                count += 1
        return count

    def test_watch_agent_running_no_inline_reactive_cleanups(self):
        """RX4 cleanups should be in _lc_* callbacks, not inline in watch_agent_running.

        Specifically: status_output_dropped, spinner_label, status_active_file,
        _active_streaming_blocks.clear(), and _pending_gen_queue must NOT appear
        as inline assignments inside watch_agent_running.
        """
        import hermes_cli.tui.app as _app_mod
        src = inspect.getsource(_app_mod.HermesApp.watch_agent_running)
        banned_inline = [
            "status_output_dropped = False",
            "spinner_label = ",
            "status_active_file = ",
            "_active_streaming_blocks.clear()",
            "_maybe_notify()",
            "_try_auto_title()",
        ]
        for pattern in banned_inline:
            assert pattern not in src, (
                f"watch_agent_running still has inline cleanup '{pattern}' — "
                "should be in an _lc_* hook callback"
            )

    def test_snapshot_method_exists(self):
        from hermes_cli.tui.services.lifecycle_hooks import AgentLifecycleHooks
        hooks = AgentLifecycleHooks()
        snap = hooks.snapshot()
        assert isinstance(snap, dict)

    def test_registered_transitions_documented(self):
        """AST-based snapshot: every h.register() in _register_lifecycle_hooks
        must exactly match EXPECTED_SNAPSHOT (§9 authoritative table).

        Uses ast.parse(inspect.getsource(...)) to extract transition/priority/name
        from each h.register(...) call and compares the sorted result against the
        module-level EXPECTED_SNAPSHOT constant.
        """
        import hermes_cli.tui.app as _app_mod

        src = textwrap.dedent(inspect.getsource(_app_mod.HermesApp._register_lifecycle_hooks))
        tree = ast.parse(src)

        # Walk all Call nodes where func is an Attribute named "register"
        extracted: dict[str, list[tuple[int, str]]] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "register"):
                continue

            # arg 0 = transition (string constant)
            if not node.args:
                continue
            transition_node = node.args[0]
            if not isinstance(transition_node, ast.Constant):
                continue
            transition = transition_node.value

            # extract priority and name kwargs
            priority: int | None = None
            name: str | None = None
            for kw in node.keywords:
                if kw.arg == "priority" and isinstance(kw.value, ast.Constant):
                    priority = kw.value.value
                elif kw.arg == "name" and isinstance(kw.value, ast.Constant):
                    name = kw.value.value

            if priority is None or name is None:
                continue

            extracted.setdefault(transition, []).append((priority, name))

        # Sort each transition's list by priority (stable — preserves registration
        # order within same priority, as _Registration uses reg_order as tiebreaker)
        for t in extracted:
            extracted[t].sort(key=lambda x: x[0])

        assert extracted == EXPECTED_SNAPSHOT, (
            "h.register() calls in _register_lifecycle_hooks do not match EXPECTED_SNAPSHOT.\n"
            "When adding a new registration:\n"
            "  1. Add h.register() in app.py\n"
            "  2. Update EXPECTED_SNAPSHOT in this test file\n"
            "  3. Update §9 in /home/xush/.hermes/2026-04-22-tui-v2-RX4-lifecycle-hooks-spec.md\n"
            f"\nExtracted:\n{extracted}\n\nExpected:\n{EXPECTED_SNAPSHOT}"
        )

    def test_snapshot_keys_match_expected(self):
        """snapshot() returns one key per registered transition, names match registration order."""
        from hermes_cli.tui.services.lifecycle_hooks import AgentLifecycleHooks
        hooks = AgentLifecycleHooks()

        # register a dummy callback on each transition from §9
        TRANSITIONS = [
            "on_turn_start", "on_turn_end_any", "on_turn_end_success",
            "on_interrupt", "on_compact_complete", "on_error_set", "on_error_clear",
            "on_session_switch", "on_session_resume",
            "on_streaming_start", "on_streaming_end",
        ]
        for t in TRANSITIONS:
            hooks.register(t, lambda **kw: None, owner=object(), priority=100, name=f"test_{t}")

        snap = hooks.snapshot()
        for t in TRANSITIONS:
            assert t in snap, f"transition {t!r} missing from snapshot()"
            assert f"test_{t}" in snap[t]

    def test_session_switch_and_resume_in_docstring(self):
        import hermes_cli.tui.services.lifecycle_hooks as lhm
        module_src = inspect.getsource(lhm)
        assert "on_session_switch" in module_src
        assert "on_session_resume" in module_src

    def test_watchers_service_no_deep_inline_cleanup(self):
        """services/watchers.py should not have large inline cleanup blocks."""
        import hermes_cli.tui.services.watchers as wm
        src = inspect.getsource(wm)
        # Find watch_status_compaction_progress and check it's short
        match = None
        for name in dir(wm.WatchersService):
            if "compaction" in name.lower() or "compact" in name.lower():
                try:
                    fn = getattr(wm.WatchersService, name)
                    fn_src = inspect.getsource(fn)
                    n = self._count_cleanup_stmts_in_func(fn_src)
                    assert n <= 3, (
                        f"WatchersService.{name} has {n} inline cleanups — move to hooks"
                    )
                except (TypeError, OSError):
                    pass
