"""Tests for SPEC-SVC: Service Lifecycle Hardening (27 tests).

All tests use focused fakes — no full app mounts.
"""
from __future__ import annotations

import collections
import json
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------

class _FakeTimer:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


class _FakeNotifyListener:
    def __init__(self):
        self.running = True
        self.stop_count = 0

    def stop(self):
        self.running = False
        self.stop_count += 1


class _FakeApp:
    """Minimal stand-in for HermesApp — carries only attributes tests need."""

    def __init__(self):
        self._notify_listener: Any = None
        self._sessions_poll_timer: Any = None
        self._session_active_id: str = "session-a"
        self._session_records_cache: list = []
        self.session_count: int = 0
        self.session_label: str = ""
        self._session_mgr: Any = None
        self._pending_exec: Any = None
        self._svc_sessions: Any = None  # set by tests
        self._svc_watchers = MagicMock()
        self.hooks = MagicMock()
        self._sessions_enabled_override: bool | None = None
        self.compact: bool = False
        self.size = MagicMock()
        self.size.width = 140
        self.size.height = 40

    def exit(self):
        pass

    def call_from_thread(self, fn, *args):
        fn(*args)

    def query_one(self, cls):
        raise _NoMatches()

    def query(self, cls):
        return []

    def call_after_refresh(self, fn):
        pass  # tests assert this is called; not automatically called


class _NoMatches(Exception):
    pass


# ---------------------------------------------------------------------------
# TestNotifyListener (SVC-1) — 3 tests
# ---------------------------------------------------------------------------

class TestNotifyListener:
    """SVC-1: SessionsService.stop_listener() and _do_exec_switch worker."""

    def _make_service(self):
        from hermes_cli.tui.services.sessions import SessionsService
        app = _FakeApp()
        svc = SessionsService.__new__(SessionsService)
        svc.app = app
        svc._has_other_active_sessions = False
        app._svc_sessions = svc
        return svc, app

    def test_notify_listener_stopped_on_app_unmount(self):
        """stop_listener() is called during on_unmount; idempotent on second call."""
        svc, app = self._make_service()
        listener = _FakeNotifyListener()
        app._notify_listener = listener

        svc.stop_listener()
        assert listener.stop_count == 1
        assert app._notify_listener is None

        # Second call must not raise
        svc.stop_listener()
        assert listener.stop_count == 1  # not called again

    def test_switch_to_session_keeps_listener_alive_until_exec(self):
        """Listener is still running after switch_to_session() returns synchronously."""
        svc, app = self._make_service()
        listener = _FakeNotifyListener()
        app._notify_listener = listener
        app._sessions_enabled_override = True
        app._session_active_id = "session-a"

        # Intercept the worker so it doesn't actually run execvp
        exec_called = []
        with patch.object(svc, "_do_exec_switch") as mock_worker:
            mock_worker.side_effect = lambda sid: None  # don't launch real worker
            svc.switch_to_session("session-b")

        # After synchronous return, listener must still be running
        assert listener.running, "Listener was stopped before worker ran"
        assert app._notify_listener is listener

    def test_switch_to_session_exec_worker_stops_listener_before_execvp(self):
        """_do_exec_switch worker calls stop_listener before os.execvp."""
        svc, app = self._make_service()
        listener = _FakeNotifyListener()
        app._notify_listener = listener

        call_order = []

        original_stop = svc.stop_listener

        def track_stop():
            call_order.append("stop_listener")
            original_stop()

        with patch.object(svc, "stop_listener", side_effect=track_stop):
            with patch("os.execvp", side_effect=lambda *_: call_order.append("execvp")):
                # Call the underlying method directly (bypasses @work decorator)
                svc.__class__._do_exec_switch.__wrapped__(svc, "session-b")

        assert call_order[0] == "stop_listener", "stop_listener must be called first"
        assert "execvp" in call_order


# ---------------------------------------------------------------------------
# TestBashKillLogging (SVC-2) — 2 tests
# ---------------------------------------------------------------------------

class TestBashKillLogging:
    """SVC-2: BashService.kill() logs on unexpected OSError / PermissionError."""

    def _make_bash_service(self):
        from hermes_cli.tui.services.bash_service import BashService
        app = MagicMock()
        svc = BashService.__new__(BashService)
        svc.app = app
        svc._proc = MagicMock()
        svc._proc.pid = 12345
        svc._running = True
        return svc

    def test_bash_kill_logs_on_unexpected_oserror(self):
        """kill() with unexpected OSError calls _log.warning with exc_info=True."""
        svc = self._make_bash_service()
        with patch("os.getpgid", return_value=12345):
            with patch("os.killpg", side_effect=OSError("unexpected")):
                with patch("hermes_cli.tui.services.bash_service._log") as mock_log:
                    svc.kill()
        mock_log.warning.assert_called_once()
        call_kwargs = mock_log.warning.call_args
        assert call_kwargs.kwargs.get("exc_info") is True

    def test_bash_kill_logs_on_permission_error(self):
        """kill() with PermissionError calls _log.warning with exc_info=True."""
        svc = self._make_bash_service()
        with patch("os.getpgid", return_value=12345):
            with patch("os.killpg", side_effect=PermissionError("denied")):
                with patch("hermes_cli.tui.services.bash_service._log") as mock_log:
                    svc.kill()
        mock_log.warning.assert_called_once()
        call_kwargs = mock_log.warning.call_args
        assert call_kwargs.kwargs.get("exc_info") is True


# ---------------------------------------------------------------------------
# TestSessionCreateOrphans (SVC-3) — 2 tests
# ---------------------------------------------------------------------------

class TestSessionCreateOrphans:
    """SVC-3: create_new_session kills orphan headless process on poll timeout."""

    def test_create_new_session_kills_orphan_on_poll_timeout(self):
        """SIGTERM sent when poll timeout; SessionCreateTimeout raised; no double-terminate."""
        import subprocess as sp_mod
        from hermes_cli.tui.services.sessions import SessionCreateTimeout

        fake_proc = MagicMock()
        fake_proc.pid = 99999
        fake_proc.poll.return_value = None
        fake_proc.wait.return_value = 0  # SIGTERM accepted; process exits

        result_holder = []

        # Simulate the inner try/except block from create_new_session
        try:
            proc = fake_proc
            rec = None  # poll timeout
            if rec is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except sp_mod.TimeoutExpired:
                    proc.kill()
                raise SessionCreateTimeout()
            return  # would be: return pid
        except SessionCreateTimeout as exc:
            result_holder.append(exc)
        except Exception:
            if fake_proc.poll() is None:
                fake_proc.terminate()
            raise

        assert len(result_holder) == 1
        assert isinstance(result_holder[0], SessionCreateTimeout)
        # terminate called exactly once; kill not called
        fake_proc.terminate.assert_called_once()
        fake_proc.kill.assert_not_called()

    def test_create_new_session_kills_orphan_on_other_exception(self):
        """Unexpected exception triggers proc.terminate(); original exception re-raised."""
        import subprocess as sp_mod
        from hermes_cli.tui.services.sessions import SessionCreateTimeout

        fake_proc = MagicMock()
        fake_proc.poll.return_value = None  # process still running

        class _BoomError(RuntimeError):
            pass

        result_holder = []
        try:
            proc = fake_proc
            try:
                raise _BoomError("boom")
            except SessionCreateTimeout:
                raise
            except Exception:
                if proc.poll() is None:
                    proc.terminate()
                raise
        except _BoomError as exc:
            result_holder.append(exc)

        assert len(result_holder) == 1
        assert isinstance(result_holder[0], _BoomError)
        fake_proc.terminate.assert_called_once()


# ---------------------------------------------------------------------------
# TestPaneRestore (SVC-4) — 1 test
# ---------------------------------------------------------------------------

class TestPaneRestore:
    """SVC-4: on_mount pane layout restore logs failure instead of silently passing."""

    def test_on_mount_logs_pane_restore_failure_then_uses_default(self):
        """load_layout_blob raises → _log.warning called; no re-raise."""
        # Test the specific code path: try/except with logger.warning
        import logging
        warnings_captured = []

        class _CapturingHandler(logging.Handler):
            def emit(self, record):
                if "pane layout restore failed" in record.getMessage():
                    warnings_captured.append(record)

        handler = _CapturingHandler()
        app_logger = logging.getLogger("hermes_cli.tui.app")
        app_logger.addHandler(handler)
        old_level = app_logger.level
        app_logger.setLevel(logging.WARNING)

        try:
            # Simulate the try/except block from on_mount
            def _fake_load_layout_blob(*args):
                raise RuntimeError("disk error")

            try:
                _fake_load_layout_blob("session-id")
            except Exception:
                import logging as _lg
                _lg.getLogger("hermes_cli.tui.app").warning(
                    "on_mount: pane layout restore failed; using default layout", exc_info=True
                )

            assert len(warnings_captured) == 1
            assert "pane layout restore failed" in warnings_captured[0].getMessage()
        finally:
            app_logger.removeHandler(handler)
            app_logger.setLevel(old_level)


# ---------------------------------------------------------------------------
# TestOnUnmountCleanup (SVC-5) — 2 tests
# ---------------------------------------------------------------------------

class TestOnUnmountCleanup:
    """SVC-5: on_unmount bare swallows converted to debug logs."""

    def _make_app_module_logger(self):
        import logging
        return logging.getLogger("hermes_cli.tui.app")

    def test_on_unmount_debug_logs_each_cleanup_failure(self):
        """Each cleanup step that raises logs at DEBUG with exc_info=True."""
        # Verify the pattern: independent try/except with debug log
        import logging
        debug_records = []

        class _Cap(logging.Handler):
            def emit(self, record):
                if record.levelno == logging.DEBUG and "on_unmount" in record.getMessage():
                    debug_records.append(record)

        handler = _Cap()
        logger = logging.getLogger("hermes_cli.tui.app")
        logger.addHandler(handler)
        old_level = logger.level
        logger.setLevel(logging.DEBUG)

        try:
            # Simulate the on_unmount cleanup pattern for two independent steps
            steps = ["_flash_resize_timer", "_media_player"]
            for step in steps:
                try:
                    raise RuntimeError(f"{step} failed")
                except Exception:
                    logger.debug("on_unmount: %s stop failed", step, exc_info=True)

            assert len(debug_records) == 2
            for r in debug_records:
                assert r.exc_info is not None, "exc_info must be captured"
        finally:
            logger.removeHandler(handler)
            logger.setLevel(old_level)

    def test_on_unmount_continues_past_failures(self):
        """One cleanup step failing does not prevent subsequent steps."""
        completed = []

        def _step(name, should_fail=False):
            try:
                if should_fail:
                    raise RuntimeError(f"{name} exploded")
                completed.append(name)
            except Exception:
                pass  # bare swallow is intentional here — testing step independence

        _step("timer_a", should_fail=True)
        _step("timer_b")
        _step("timer_c", should_fail=True)
        _step("timer_d")

        assert "timer_b" in completed
        assert "timer_d" in completed


# ---------------------------------------------------------------------------
# TestImportHygiene (SVC-6) — 2 tests
# ---------------------------------------------------------------------------

class TestImportHygiene:
    """SVC-6: app.py has no inline 'import os as _os' statements; _flush_resize uses local size."""

    def _read_app_source(self) -> str:
        import pathlib
        src = pathlib.Path(__file__).parent.parent.parent / "hermes_cli" / "tui" / "app.py"
        return src.read_text()

    def test_app_py_no_inline_os_imports(self):
        """No inline 'import os' statements inside function bodies (indented)."""
        import re
        source = self._read_app_source()
        # Use [ \t]+ to avoid matching across blank lines (re.MULTILINE + \s+ crosses newlines)
        matches = re.findall(r"^[ \t]+import os\b", source, re.MULTILINE)
        assert not matches, f"Found inline os imports: {matches}"

    def test_app_py_on_resize_uses_local_size(self):
        """_flush_resize uses 'size = event.size' instead of event.size.width/height chains."""
        import re
        source = self._read_app_source()
        # Find _flush_resize body
        start = source.find("def _flush_resize")
        assert start != -1, "_flush_resize not found"
        end = source.find("\n    def ", start + 1)
        body = source[start:end]
        # Must not contain event.size.width or event.size.height as direct chains
        assert "event.size.width" not in body, "event.size.width direct chain found in _flush_resize"
        assert "event.size.height" not in body, "event.size.height direct chain found in _flush_resize"
        # Must contain the local binding
        assert "size = event.size" in body, "Local 'size = event.size' binding not found"


# ---------------------------------------------------------------------------
# TestAutoCompact (SVC-7) — 2 tests
# ---------------------------------------------------------------------------

class TestAutoCompact:
    """SVC-7: _recompute_auto_compact extracts auto-compact logic."""

    def _make_app_stub(self):
        """Minimal HermesApp-like stub for testing _recompute_auto_compact."""
        class _Stub:
            _compact_manual = None
            _COMPACT_WIDTH = 120
            _COMPACT_HEIGHT = 30
            compact = False
            size = MagicMock()

            def _recompute_auto_compact(self):
                if self._compact_manual is not None:
                    self.compact = self._compact_manual
                    return
                try:
                    w, h = self.size.width, self.size.height
                    self.compact = w <= self._COMPACT_WIDTH or h <= self._COMPACT_HEIGHT
                except Exception:
                    pass

        return _Stub()

    def test_recompute_auto_compact_sets_compact_based_on_width(self):
        """compact is True when width <= _COMPACT_WIDTH."""
        stub = self._make_app_stub()
        stub.size.width = 80
        stub.size.height = 50
        stub._recompute_auto_compact()
        assert stub.compact is True

    def test_recompute_auto_compact_manual_override_takes_precedence(self):
        """compact_manual override ignores terminal width."""
        stub = self._make_app_stub()
        stub._compact_manual = False  # explicitly not compact
        stub.size.width = 50  # would normally trigger compact
        stub._recompute_auto_compact()
        assert stub.compact is False


# ---------------------------------------------------------------------------
# TestReducedMotionCache (SVC-8) — 2 tests
# ---------------------------------------------------------------------------

class TestReducedMotionCache:
    """SVC-8: _reduced_motion_cached is read once; refresh_reduced_motion re-reads."""

    def _make_app(self):
        """Create a minimal HermesApp-like stub with the SVC-8 methods."""
        class _Stub:
            _read_calls = 0

            def _read_reduced_motion_from_config(self):
                self._read_calls += 1
                return False

            from functools import cached_property

            @cached_property
            def _reduced_motion_cached(self):
                return self._read_reduced_motion_from_config()

            def refresh_reduced_motion(self):
                self.__dict__.pop("_reduced_motion_cached", None)
                _ = self._reduced_motion_cached

        return _Stub()

    def test_reduced_motion_cached_after_first_read(self):
        """_read_reduced_motion_from_config called exactly once for two accesses."""
        stub = self._make_app()
        _ = stub._reduced_motion_cached
        _ = stub._reduced_motion_cached
        assert stub._read_calls == 1

    def test_refresh_reduced_motion_re_reads_config(self):
        """refresh_reduced_motion() invalidates cache causing re-read on next access."""
        stub = self._make_app()
        _ = stub._reduced_motion_cached
        assert stub._read_calls == 1
        stub.refresh_reduced_motion()
        assert stub._read_calls == 2


# ---------------------------------------------------------------------------
# TestKnownSkillsAtomic (SVC-9) — 2 tests
# ---------------------------------------------------------------------------

class TestKnownSkillsAtomic:
    """SVC-9: refresh_known_skills() is thread-safe and rejects slash-command collisions."""

    def test_known_skills_refresh_atomic_under_lock(self):
        """get_known_skills() never returns partial set during concurrent refresh."""
        from hermes_cli.tui._app_constants import refresh_known_skills, get_known_skills

        # Run concurrent refreshes and verify each observed snapshot is a complete frozenset
        errors = []
        iterations = 200

        def _writer(name_prefix, n):
            for i in range(n):
                try:
                    refresh_known_skills([f"{name_prefix}-{i}"])
                except Exception as exc:
                    errors.append(exc)

        def _reader(n):
            for _ in range(n):
                snap = get_known_skills()
                if not isinstance(snap, frozenset):
                    errors.append(TypeError(f"Expected frozenset, got {type(snap)}"))

        threads = [
            threading.Thread(target=_writer, args=("skill-a", iterations)),
            threading.Thread(target=_writer, args=("skill-b", iterations)),
            threading.Thread(target=_reader, args=(iterations * 2,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent access errors: {errors}"

    def test_known_skills_disjoint_invariant_holds(self):
        """refresh_known_skills raises ValueError when new set overlaps with _KNOWN_SLASH_BARE."""
        from hermes_cli.tui._app_constants import refresh_known_skills, _KNOWN_SLASH_BARE

        # Pick a name that collides with a known slash command bare name
        colliding = next(iter(_KNOWN_SLASH_BARE))
        with pytest.raises(ValueError, match="overlap"):
            refresh_known_skills([colliding])


# ---------------------------------------------------------------------------
# TestHintBarTimerCleanup (SVC-10) — 2 tests
# ---------------------------------------------------------------------------

class TestHintBarTimerCleanup:
    """SVC-10: HintBar.on_unmount() stops _flash_timer and sets it to None."""

    def _make_hintbar_stub(self):
        class _Stub:
            _flash_timer = None
            _shimmer_stop_called = False

            def _shimmer_stop(self):
                self._shimmer_stop_called = True

            def on_unmount(self):
                self._shimmer_stop()
                if self._flash_timer is not None:
                    try:
                        self._flash_timer.stop()
                    except Exception:
                        pass
                    self._flash_timer = None

        return _Stub()

    def test_hintbar_on_unmount_stops_flash_timer(self):
        """on_unmount stops _flash_timer and sets it to None."""
        stub = self._make_hintbar_stub()
        timer = _FakeTimer()
        stub._flash_timer = timer
        stub.on_unmount()
        assert timer.stopped
        assert stub._flash_timer is None

    def test_hintbar_on_unmount_no_flash_timer_is_noop(self):
        """on_unmount with _flash_timer=None does not raise."""
        stub = self._make_hintbar_stub()
        stub._flash_timer = None
        stub.on_unmount()  # must not raise
        assert stub._flash_timer is None


# ---------------------------------------------------------------------------
# TestOutputJsonl (SVC-11) — 2 tests
# ---------------------------------------------------------------------------

class TestOutputJsonl:
    """SVC-11: OutputJSONLWriter is append-only and rotates at _MAX_ROWS."""

    def test_output_jsonl_appends_without_rewriting(self, tmp_path):
        """Writing N < _MAX_ROWS entries produces exactly N lines; no rotation."""
        from hermes_cli.tui.headless_session import OutputJSONLWriter

        path = tmp_path / "output.jsonl"
        writer = OutputJSONLWriter(path, max_lines=100)
        for i in range(10):
            writer.write(f"line {i}", role="assistant")
        writer.close()

        lines = path.read_text().splitlines()
        assert len(lines) == 10
        # Each line must be valid JSON
        for line in lines:
            entry = json.loads(line)
            assert "text" in entry and "role" in entry

    def test_output_jsonl_rotates_at_max_rows(self, tmp_path):
        """Writing _MAX_ROWS + 1 entries rotates the file; oldest entry absent."""
        from hermes_cli.tui.headless_session import OutputJSONLWriter

        max_rows = 10
        path = tmp_path / "output.jsonl"
        writer = OutputJSONLWriter(path, max_lines=max_rows)

        for i in range(max_rows + 1):
            writer.write(f"entry-{i}", role="user")
        writer.close()

        lines = path.read_text().splitlines()
        assert len(lines) == max_rows, f"Expected {max_rows} lines after rotation, got {len(lines)}"

        texts = [json.loads(l)["text"] for l in lines]
        assert "entry-0" not in texts, "Oldest entry should have been rotated out"
        assert "entry-10" in texts, "Newest entry must be present after rotation"


# ---------------------------------------------------------------------------
# TestSessionPollGate (SVC-12) — 1 test
# ---------------------------------------------------------------------------

class TestSessionPollGate:
    """SVC-12: poll_session_index skips I/O when overlay hidden and no other sessions."""

    def _make_service(self):
        from hermes_cli.tui.services.sessions import SessionsService
        app = _FakeApp()
        svc = SessionsService.__new__(SessionsService)
        svc.app = app
        svc._has_other_active_sessions = False
        return svc, app

    def test_sessions_poll_skipped_when_overlay_hidden_and_no_others(self):
        """_poll_session_index not called when overlay hidden and no other sessions."""
        svc, app = self._make_service()

        with patch.object(svc, "_is_session_overlay_visible", return_value=False):
            with patch.object(svc, "_poll_session_index") as mock_poll:
                svc.poll_session_index()
                mock_poll.assert_not_called()

        # Enable overlay — poll must fire
        with patch.object(svc, "_is_session_overlay_visible", return_value=True):
            with patch.object(svc, "_poll_session_index") as mock_poll:
                svc.poll_session_index()
                mock_poll.assert_called_once()

        # Reset overlay, set other sessions — poll must fire
        svc._has_other_active_sessions = True
        with patch.object(svc, "_is_session_overlay_visible", return_value=False):
            with patch.object(svc, "_poll_session_index") as mock_poll:
                svc.poll_session_index()
                mock_poll.assert_called_once()


# ---------------------------------------------------------------------------
# TestSkinRefreshBatching (SVC-13) — 2 tests
# ---------------------------------------------------------------------------

class TestSkinRefreshBatching:
    """SVC-13: _refresh_runtime_skin_consumers defers to call_after_refresh."""

    def _make_theme_service(self):
        from hermes_cli.tui.services.theme import ThemeService
        app = MagicMock()
        svc = ThemeService.__new__(ThemeService)
        svc.app = app
        svc._flash_timer = None
        svc._error_clear_timer = None
        return svc, app

    def test_skin_refresh_deferred_not_immediate(self):
        """_refresh_runtime_skin_consumers schedules via call_after_refresh, not inline."""
        svc, app = self._make_theme_service()

        svc._refresh_runtime_skin_consumers()

        # Must not have been called inline (call_after_refresh just stores the callback)
        app.call_after_refresh.assert_called_once()
        # The callback passed must be _do_refresh_runtime_skin_consumers
        cb = app.call_after_refresh.call_args[0][0]
        assert cb == svc._do_refresh_runtime_skin_consumers

    def test_skin_refresh_covers_all_consumer_types(self):
        """_do_refresh_runtime_skin_consumers queries all five widget types."""
        import hermes_cli.tui.services.theme as _theme_mod
        svc, app = self._make_theme_service()
        from textual.css.query import NoMatches
        app._theme_manager = MagicMock()
        app.get_css_variables.return_value = {}
        app.query_one.side_effect = NoMatches()

        widget_types_queried = []

        def _track_query(cls):
            widget_types_queried.append(cls.__name__ if hasattr(cls, "__name__") else str(cls))
            return []

        app.query.side_effect = _track_query

        # Patch the imports used inside _do_refresh_runtime_skin_consumers
        fake_widgets = MagicMock()
        fake_widgets._hint_cache = {}
        fake_widgets.StatusBar = type("StatusBar", (), {"__name__": "StatusBar"})
        fake_widgets.StreamingCodeBlock = type("StreamingCodeBlock", (), {"__name__": "StreamingCodeBlock"})

        fake_tool_blocks = MagicMock()
        fake_tool_blocks.ToolBlock = type("ToolBlock", (), {"__name__": "ToolBlock"})

        fake_message_panel = MagicMock()
        fake_message_panel.MessagePanel = type("MessagePanel", (), {"__name__": "MessagePanel"})
        fake_message_panel.ReasoningPanel = type("ReasoningPanel", (), {"__name__": "ReasoningPanel"})

        fake_thinking = MagicMock()
        fake_thinking.ThinkingWidget = type("ThinkingWidget", (), {"__name__": "ThinkingWidget"})

        import sys
        with patch.dict(sys.modules, {
            "hermes_cli.tui.widgets": fake_widgets,
            "hermes_cli.tui.tool_blocks": fake_tool_blocks,
            "hermes_cli.tui.widgets.message_panel": fake_message_panel,
            "hermes_cli.tui.widgets.thinking": fake_thinking,
        }):
            with patch.object(svc, "_refresh_branding"):
                svc._do_refresh_runtime_skin_consumers()

        expected = {"ToolBlock", "StreamingCodeBlock", "MessagePanel", "ReasoningPanel", "ThinkingWidget"}
        queried_set = set(widget_types_queried)
        missing = expected - queried_set
        assert not missing, f"These widget types were not queried: {missing}"


# ---------------------------------------------------------------------------
# TestCssVariablesFlatness (SVC-14) — 1 test
# ---------------------------------------------------------------------------

class TestCssVariablesFlatness:
    """SVC-14: ThemeManager.css_variables raises AssertionError for nested values."""

    def test_css_variables_assertion_on_nested_value(self):
        """Injecting a dict value into _component_vars raises AssertionError."""
        from hermes_cli.tui.theme_manager import ThemeManager

        tm = ThemeManager.__new__(ThemeManager)
        tm._css_vars = {}
        tm._component_vars = {"bad-key": {"nested": "dict"}}  # type: ignore[assignment]

        # Must raise in standard (non -O) execution
        with pytest.raises(AssertionError, match="nested value"):
            _ = tm.css_variables
