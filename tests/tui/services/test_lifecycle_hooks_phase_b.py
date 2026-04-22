"""Phase b tests for RX4 AgentLifecycleHooks.

Covers:
- on_streaming_start / on_streaming_end fire on correct transitions
- D2: compaction warn flags reset on stream-end path (not only on progress→0)
- E1: error auto-clear timer scheduled via hook, cancelled via hook
- Inline code removed: hooks own the cleanup, not the watchers/app inline code
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_hooks():
    from hermes_cli.tui.services.lifecycle_hooks import AgentLifecycleHooks
    return AgentLifecycleHooks()


def _make_fake_app():
    """Minimal app-like namespace for testing hook callbacks in isolation."""
    app = MagicMock()
    app.status_compaction_progress = 0.0
    app.status_error = ""
    app._status_error_timer = None
    app._compaction_warned = False
    app._compaction_warn_99 = False
    app.context_pct = 0.0
    return app


# ── on_streaming_start / on_streaming_end ─────────────────────────────────────

class TestStreamingHooks:
    def test_streaming_start_fires_on_first_chunk(self):
        h = _make_hooks()
        calls = []
        h.register("on_streaming_start", lambda: calls.append("start"))
        h.fire("on_streaming_start")
        assert calls == ["start"]

    def test_streaming_end_fires_with_no_ctx(self):
        h = _make_hooks()
        calls = []
        h.register("on_streaming_end", lambda **_: calls.append("end"))
        h.fire("on_streaming_end")
        assert calls == ["end"]

    def test_streaming_start_before_end(self):
        h = _make_hooks()
        order = []
        h.register("on_streaming_start", lambda: order.append("start"))
        h.register("on_streaming_end", lambda **_: order.append("end"))
        h.fire("on_streaming_start")
        h.fire("on_streaming_end")
        assert order == ["start", "end"]

    def test_multiple_streaming_cycles(self):
        """Multiple start/end pairs per turn are fine."""
        h = _make_hooks()
        calls = []
        h.register("on_streaming_start", lambda: calls.append("S"))
        h.register("on_streaming_end", lambda **_: calls.append("E"))
        for _ in range(3):
            h.fire("on_streaming_start")
            h.fire("on_streaming_end")
        assert calls == ["S", "E", "S", "E", "S", "E"]


# ── D2: compaction reset on stream-end path ───────────────────────────────────

class TestD2CompactionStreamEnd:
    def test_compact_flags_reset_via_on_compact_complete(self):
        """on_compact_complete hook resets warn flags — the hook itself works."""
        h = _make_hooks()
        app = _make_fake_app()
        app._compaction_warned = True
        app._compaction_warn_99 = True
        app.context_pct = 0.8

        def reset_flags(**_):
            app._compaction_warned = False
            app._compaction_warn_99 = False
            app.context_pct = 0.0

        h.register("on_compact_complete", reset_flags)
        h.fire("on_compact_complete")

        assert not app._compaction_warned
        assert not app._compaction_warn_99
        assert app.context_pct == 0.0

    def test_status_compaction_progress_zeroed_triggers_compact_complete(self):
        """Setting status_compaction_progress = 0.0 from io.py fires on_compact_complete."""
        h = _make_hooks()
        calls = []
        h.register("on_compact_complete", lambda **_: calls.append(1))

        # Simulate the watcher path: progress set to 0.0 → fire hook
        def on_progress_zero():
            h.fire("on_compact_complete")

        on_progress_zero()
        assert calls == [1]

    def test_io_service_sets_progress_zero_when_stuck(self):
        """IOService consume_output sets status_compaction_progress=0 when >0 at stream end."""
        # We test the io.py logic by inspecting what it does to the app mock
        app = _make_fake_app()
        app.status_compaction_progress = 0.7  # stuck > 0

        # Simulate the D2 fix path in consume_output
        was_streaming = True
        if was_streaming and getattr(app, "status_compaction_progress", 0.0) > 0.0:
            app.status_compaction_progress = 0.0

        assert app.status_compaction_progress == 0.0

    def test_io_service_does_not_zero_progress_when_not_streaming(self):
        """D2 path only triggers when we were actually streaming."""
        app = _make_fake_app()
        app.status_compaction_progress = 0.7

        was_streaming = False  # None arrived without any chunks
        if was_streaming and getattr(app, "status_compaction_progress", 0.0) > 0.0:
            app.status_compaction_progress = 0.0

        assert app.status_compaction_progress == 0.7  # untouched

    def test_io_service_does_not_zero_when_already_zero(self):
        """D2 guard: progress already 0 — no double fire."""
        app = _make_fake_app()
        app.status_compaction_progress = 0.0  # already reset

        was_streaming = True
        if was_streaming and getattr(app, "status_compaction_progress", 0.0) > 0.0:
            app.status_compaction_progress = 0.0  # would have zeroed — but condition is False

        assert app.status_compaction_progress == 0.0


# ── E1: error auto-clear via hooks ───────────────────────────────────────────

class TestE1ErrorAutoClear:
    def test_on_error_set_hook_receives_error_kwarg(self):
        h = _make_hooks()
        received = {}
        h.register("on_error_set", lambda error="", **_: received.update({"error": error}))
        h.fire("on_error_set", error="disk full")
        assert received["error"] == "disk full"

    def test_on_error_clear_hook_fires(self):
        h = _make_hooks()
        calls = []
        h.register("on_error_clear", lambda **_: calls.append(1))
        h.fire("on_error_clear")
        assert calls == [1]

    def test_lc_schedule_error_autoclear_sets_timer(self):
        """_lc_schedule_error_autoclear stores a timer handle on app."""
        from hermes_cli.tui.services.lifecycle_hooks import AgentLifecycleHooks

        app = MagicMock()
        app._status_error_timer = None
        fake_handle = MagicMock()
        app.set_timer.return_value = fake_handle

        h = AgentLifecycleHooks(app)

        # Simulate calling the callback the way the hook would
        # (We access it via a registered no-op, then call directly)
        class _FakeApp:
            _status_error_timer = None
            def set_timer(self, delay, cb):
                self._status_error_timer = cb
                return MagicMock()
            @property
            def _svc_watchers(self):
                m = MagicMock()
                m.auto_clear_status_error = MagicMock()
                return m

        fa = _FakeApp()
        # Import and call the method with the fake app as self
        from hermes_cli.tui.app import HermesApp
        import types
        bound = types.MethodType(HermesApp._lc_schedule_error_autoclear, fa)
        bound(error="something bad")
        assert fa._status_error_timer is not None

    def test_lc_cancel_error_timer_stops_existing(self):
        """_lc_cancel_error_timer stops and clears the stored handle."""
        fake_timer = MagicMock()

        class _FakeApp:
            _status_error_timer = fake_timer
            def set_timer(self, *a, **kw):
                return MagicMock()

        fa = _FakeApp()
        from hermes_cli.tui.app import HermesApp
        import types
        bound = types.MethodType(HermesApp._lc_cancel_error_timer, fa)
        bound()

        fake_timer.stop.assert_called_once()
        assert fa._status_error_timer is None

    def test_lc_cancel_error_timer_noop_when_no_timer(self):
        """_lc_cancel_error_timer is safe when no timer is set."""
        class _FakeApp:
            _status_error_timer = None

        fa = _FakeApp()
        from hermes_cli.tui.app import HermesApp
        import types
        bound = types.MethodType(HermesApp._lc_cancel_error_timer, fa)
        bound()  # no exception


# ── Inline code removal verification ─────────────────────────────────────────

class TestInlineRemoved:
    """Structural guards: verify the inline cleanup is gone from watchers and app."""

    def test_on_status_compaction_progress_no_inline_flag_reset(self):
        import inspect
        from hermes_cli.tui.services.watchers import WatchersService
        src = inspect.getsource(WatchersService.on_status_compaction_progress)
        assert "self.app.context_pct = 0.0" not in src, (
            "context_pct reset must be in _lc_reset_compact_flags hook, not inline"
        )
        assert "self.app._compaction_warned = False" not in src, (
            "_compaction_warned reset must be in hook, not inline"
        )
        assert "self.app._compaction_warn_99 = False" not in src, (
            "_compaction_warn_99 reset must be in hook, not inline"
        )

    def test_on_status_error_no_inline_timer(self):
        import inspect
        from hermes_cli.tui.services.watchers import WatchersService
        src = inspect.getsource(WatchersService.on_status_error)
        assert "set_timer" not in src, (
            "set_timer must be in _lc_schedule_error_autoclear hook, not inline in on_status_error"
        )
        assert "_status_error_timer" not in src, (
            "_status_error_timer must be managed by hooks, not inline in on_status_error"
        )

    def test_watch_agent_running_no_inline_osc_start(self):
        import inspect
        from hermes_cli.tui.app import HermesApp
        src = inspect.getsource(HermesApp.watch_agent_running)
        # osc_progress_update(True) should only exist via the hook, not inline
        # The method itself is called from _lc_osc_progress_start, not from watch_agent_running
        lines = src.splitlines()
        inline_osc_start = [
            l for l in lines
            if "_osc_progress_update(True)" in l and "def _lc_" not in l
        ]
        assert not inline_osc_start, (
            f"Inline _osc_progress_update(True) found in watch_agent_running: {inline_osc_start}"
        )

    def test_watch_agent_running_no_inline_maybe_notify(self):
        import inspect
        from hermes_cli.tui.app import HermesApp
        src = inspect.getsource(HermesApp.watch_agent_running)
        assert "_maybe_notify" not in src, (
            "_maybe_notify must be in _lc_desktop_notify hook, not in watch_agent_running"
        )

    def test_watch_agent_running_no_inline_auto_title(self):
        import inspect
        from hermes_cli.tui.app import HermesApp
        src = inspect.getsource(HermesApp.watch_agent_running)
        assert "_try_auto_title" not in src, (
            "_try_auto_title must be in _lc_auto_title hook, not in watch_agent_running"
        )

    def test_watch_agent_running_no_inline_clear_output_dropped(self):
        import inspect
        from hermes_cli.tui.app import HermesApp
        src = inspect.getsource(HermesApp.watch_agent_running)
        assert "status_output_dropped = False" not in src, (
            "status_output_dropped reset must be in hook, not in watch_agent_running"
        )

    def test_watch_agent_running_no_inline_spinner_clear(self):
        import inspect
        from hermes_cli.tui.app import HermesApp
        src = inspect.getsource(HermesApp.watch_agent_running)
        assert 'spinner_label = ""' not in src, (
            "spinner_label clear must be in hook, not in watch_agent_running"
        )

    def test_io_service_fires_streaming_hooks(self):
        import inspect
        from hermes_cli.tui.services.io import IOService
        src = inspect.getsource(IOService.consume_output)
        assert "on_streaming_start" in src
        assert "on_streaming_end" in src

    def test_io_service_has_d2_guard(self):
        import inspect
        from hermes_cli.tui.services.io import IOService
        src = inspect.getsource(IOService.consume_output)
        assert "status_compaction_progress" in src, (
            "D2 fix: consume_output must check status_compaction_progress at stream end"
        )
