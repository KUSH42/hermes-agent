"""Tests for LOG-1 (sessions.py) and LOG-2 (watchers.py) logging sweep."""
from __future__ import annotations

import types
import unittest.mock as mock
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(**kwargs):
    """Minimal SimpleNamespace fake app for unit tests."""
    from textual.css.query import NoMatches
    defaults: dict = dict(
        _session_mgr=None,
        _notify_listener=None,
        _sessions_poll_timer=None,
        _own_session_id=None,
        _sessions_enabled_override=None,
        _session_records_cache=[],
        _session_active_id=None,
        session_count=0,
        _sessions_cfg={},
        agent_running=False,
        command_running=False,
        compact=False,
        config={},
        _compaction_warn_99=False,
        hooks=MagicMock(),
        feedback=MagicMock(),
    )
    defaults.update(kwargs)
    app = types.SimpleNamespace(**defaults)
    # query helpers default to raising NoMatches
    app.query_one = MagicMock(side_effect=NoMatches())
    app.query = MagicMock(return_value=[])
    app.call_from_thread = MagicMock()
    app.call_after_refresh = MagicMock()
    app.set_interval = MagicMock(return_value=MagicMock())
    app._flash_hint = MagicMock()
    app._svc_watchers = MagicMock()
    app._svc_spinner = MagicMock()
    app.screen = MagicMock()
    app.add_class = MagicMock()
    app.remove_class = MagicMock()
    return app


def _make_sessions_svc(app=None):
    from hermes_cli.tui.services.sessions import SessionsService
    if app is None:
        app = _make_app()
    svc = SessionsService.__new__(SessionsService)
    svc.app = app
    return svc


def _make_watchers_svc(app=None):
    from hermes_cli.tui.services.watchers import WatchersService
    if app is None:
        app = _make_app()
    svc = WatchersService.__new__(WatchersService)
    svc.app = app
    svc._phase_before_error = ""
    svc._compact_warn_flashed = False
    return svc


def _make_index(sessions=None, active_id=None):
    idx = MagicMock()
    idx.get_sessions.return_value = sessions or []
    idx.get_active_id.return_value = active_id
    return idx


def _make_session_mgr(sessions=None, active_id=None):
    mgr = MagicMock()
    mgr.index = _make_index(sessions, active_id)
    mgr._max_sessions = 8
    return mgr


# ===========================================================================
# LOG-1: SessionsService logging
# ===========================================================================

class TestSessionsLogging:

    def test_log_init_sessions_notify_listener_failure(self):
        """_NotifyListener.start() raises → _log.warning; poll timer still started."""
        app = _make_app(_own_session_id="sess-1", _sessions_cfg={"enabled": True, "session_dir": "/tmp/hs"})
        app._sessions_enabled_override = None

        svc = _make_sessions_svc(app)

        mgr_instance = _make_session_mgr()
        nl_instance = MagicMock()
        nl_instance.start.side_effect = RuntimeError("socket error")

        with (
            patch("hermes_cli.tui.services.sessions._log") as mock_log,
            patch("hermes_cli.tui.session_manager.SessionManager", return_value=mgr_instance),
            patch("hermes_cli.tui.session_manager._NotifyListener", return_value=nl_instance),
            patch("os.path.expanduser", return_value="/tmp/hs"),
        ):
            svc.init_sessions()

        mock_log.warning.assert_called_once()
        assert "notify listener" in mock_log.warning.call_args[0][0]
        app.set_interval.assert_called_once()

    def test_log_poll_session_index_failure(self):
        """index.get_sessions() raises → _log.warning with exc_info; no propagation."""
        app = _make_app()
        app._session_mgr = _make_session_mgr()
        app._session_mgr.index.get_sessions.side_effect = IOError("disk error")
        svc = _make_sessions_svc(app)

        with patch("hermes_cli.tui.services.sessions._log") as mock_log:
            svc.poll_session_index()  # must not raise

        mock_log.warning.assert_called_once()
        assert "poll_session_index" in mock_log.warning.call_args[0][0]
        assert mock_log.warning.call_args[1].get("exc_info") is True

    def test_log_switch_to_session_update_active_failure(self):
        """update_active raises → _log.warning; listener/timer teardown still attempted."""
        app = _make_app()
        app._sessions_enabled_override = True
        mgr = _make_session_mgr()
        mgr.index.update_active.side_effect = RuntimeError("write error")
        app._session_mgr = mgr

        listener = MagicMock()
        app._notify_listener = listener
        timer = MagicMock()
        app._sessions_poll_timer = timer
        app._session_active_id = "other-id"
        app.exit = MagicMock(side_effect=SystemExit)

        svc = _make_sessions_svc(app)

        with patch("hermes_cli.tui.services.sessions._log") as mock_log:
            with pytest.raises(SystemExit):
                svc.switch_to_session("target-id")

        mock_log.warning.assert_called_once()
        assert "update_active" in mock_log.warning.call_args[0][0]
        # teardown still ran
        listener.stop.assert_called_once()
        timer.stop.assert_called_once()

    def test_log_switch_to_session_listener_stop_failure(self):
        """listener.stop() raises → _log.debug; timer stop still attempted."""
        app = _make_app()
        app._sessions_enabled_override = True
        mgr = _make_session_mgr()
        app._session_mgr = mgr

        listener = MagicMock()
        listener.stop.side_effect = RuntimeError("stop error")
        app._notify_listener = listener
        timer = MagicMock()
        app._sessions_poll_timer = timer
        app._session_active_id = "other"
        app.exit = MagicMock(side_effect=SystemExit)

        svc = _make_sessions_svc(app)

        with patch("hermes_cli.tui.services.sessions._log") as mock_log:
            with pytest.raises(SystemExit):
                svc.switch_to_session("new-id")

        mock_log.debug.assert_any_call(
            mock.ANY, mock.ANY  # message + exc
        )
        assert any("listener stop" in str(c) for c in mock_log.debug.call_args_list)
        timer.stop.assert_called_once()

    def test_log_switch_to_session_timer_stop_failure(self):
        """timer.stop() raises → _log.debug; no exception propagates."""
        app = _make_app()
        app._sessions_enabled_override = True
        mgr = _make_session_mgr()
        app._session_mgr = mgr

        app._notify_listener = None
        timer = MagicMock()
        timer.stop.side_effect = RuntimeError("timer err")
        app._sessions_poll_timer = timer
        app._session_active_id = "other"
        app.exit = MagicMock(side_effect=SystemExit)

        svc = _make_sessions_svc(app)

        with patch("hermes_cli.tui.services.sessions._log") as mock_log:
            with pytest.raises(SystemExit):
                svc.switch_to_session("new-id")

        assert any("timer stop" in str(c) for c in mock_log.debug.call_args_list)

    def test_log_create_new_session_worktree_cleanup_failure(self):
        """Worktree cleanup _sp.run raises after spawn fails → _log.warning."""
        app = _make_app()
        app._session_mgr = _make_session_mgr()
        app._session_mgr.new_id.return_value = "new-sess"
        app._session_mgr.validate_socket_path.return_value = None
        app._session_mgr.create_session_dir.return_value = "/tmp/wt/new-sess"
        app._session_mgr.poll_state_until_pid.return_value = None

        svc = _make_sessions_svc(app)
        overlay = MagicMock()

        import subprocess as _sp
        # git worktree add succeeds; cleanup run raises
        call_count = [0]
        def run_side_effect(cmd, **kw):
            call_count[0] += 1
            if "add" in cmd:
                return MagicMock(returncode=0)
            raise OSError("cleanup error")

        with (
            patch("hermes_cli.tui.services.sessions._log") as mock_log,
            patch("subprocess.run", side_effect=run_side_effect),
            patch("subprocess.Popen", return_value=MagicMock()),
        ):
            svc.create_new_session.__wrapped__(svc, "branch", "current", overlay)

        mock_log.warning.assert_called()
        assert any("worktree cleanup" in str(c) for c in mock_log.warning.call_args_list)

    def test_log_create_new_session_index_add_failure(self):
        """index.add_session raises after spawn succeeds → _log.error."""
        app = _make_app()
        mgr = _make_session_mgr()
        mgr.new_id.return_value = "new-sess"
        mgr.validate_socket_path.return_value = None
        mgr.create_session_dir.return_value = "/tmp/wt/new-sess"
        mgr.poll_state_until_pid.return_value = MagicMock()  # rec found
        mgr.index.add_session.side_effect = RuntimeError("index write error")
        app._session_mgr = mgr

        svc = _make_sessions_svc(app)
        overlay = MagicMock()

        with (
            patch("hermes_cli.tui.services.sessions._log") as mock_log,
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
            patch("subprocess.Popen", return_value=MagicMock()),
        ):
            svc.create_new_session.__wrapped__(svc, "branch", "current", overlay)

        mock_log.error.assert_called_once()
        assert "index.add_session" in mock_log.error.call_args[0][0]
        assert mock_log.error.call_args[1].get("exc_info") is True

    def test_log_kill_session_prompt_failure(self):
        """kill_session raises → _log.warning."""
        app = _make_app()
        rec = MagicMock()
        rec.id = "sess-1"
        mgr = _make_session_mgr(sessions=[rec])
        mgr.kill_session.side_effect = RuntimeError("kill error")
        app._session_mgr = mgr

        svc = _make_sessions_svc(app)

        with patch("hermes_cli.tui.services.sessions._log") as mock_log:
            svc.kill_session_prompt.__wrapped__(svc, "sess-1")

        mock_log.warning.assert_called_once()
        assert "kill_session_prompt" in mock_log.warning.call_args[0][0]

    def test_log_run_merge_cleanup_failure(self):
        """Post-merge cleanup raises → _log.warning."""
        app = _make_app()
        rec = MagicMock()
        rec.id = "sess-1"
        rec.branch = "feat/x"
        rec.worktree_path = "/tmp/wt/sess-1"
        mgr = _make_session_mgr(sessions=[rec])
        mgr.kill_session.side_effect = RuntimeError("kill err")
        app._session_mgr = mgr

        svc = _make_sessions_svc(app)
        overlay = MagicMock()

        with (
            patch("hermes_cli.tui.services.sessions._log") as mock_log,
            patch("subprocess.run", return_value=MagicMock(returncode=0, stderr="", stdout="")),
        ):
            svc.run_merge.__wrapped__(svc, "sess-1", "merge", True, overlay)

        mock_log.warning.assert_called()
        assert any("post-merge cleanup" in str(c) for c in mock_log.warning.call_args_list)

    def test_log_reopen_orphan_popen_failure(self):
        """Popen raises → _log.error; function returns without crash."""
        app = _make_app()
        rec = MagicMock()
        rec.id = "sess-1"
        rec.worktree_path = "/tmp/wt/sess-1"
        mgr = _make_session_mgr(sessions=[rec])
        app._session_mgr = mgr

        svc = _make_sessions_svc(app)

        with (
            patch("hermes_cli.tui.services.sessions._log") as mock_log,
            patch("subprocess.Popen", side_effect=OSError("no such file")),
        ):
            svc.reopen_orphan_session.__wrapped__(svc, "sess-1")  # must not raise

        mock_log.error.assert_called_once()
        assert "Popen failed" in mock_log.error.call_args[0][0]

    def test_log_reopen_orphan_index_add_failure(self):
        """index.add_session raises in reopen path → _log.warning."""
        app = _make_app()
        rec = MagicMock()
        rec.id = "sess-1"
        rec.worktree_path = "/tmp/wt/sess-1"
        mgr = _make_session_mgr(sessions=[rec])
        mgr.poll_state_until_pid.return_value = MagicMock()
        mgr.index.add_session.side_effect = RuntimeError("add error")
        app._session_mgr = mgr

        svc = _make_sessions_svc(app)

        with (
            patch("hermes_cli.tui.services.sessions._log") as mock_log,
            patch("subprocess.Popen", return_value=MagicMock()),
        ):
            svc.reopen_orphan_session.__wrapped__(svc, "sess-1")

        mock_log.warning.assert_called()
        assert any("index.add_session" in str(c) for c in mock_log.warning.call_args_list)

    def test_log_delete_orphan_worktree_failure(self):
        """git worktree remove raises → _log.warning includes worktree_path."""
        app = _make_app()
        rec = MagicMock()
        rec.id = "sess-1"
        rec.worktree_path = "/tmp/wt/sess-1"
        mgr = _make_session_mgr(sessions=[rec])
        app._session_mgr = mgr

        svc = _make_sessions_svc(app)

        with (
            patch("hermes_cli.tui.services.sessions._log") as mock_log,
            patch("subprocess.run", side_effect=OSError("rm error")),
        ):
            svc.delete_orphan_session.__wrapped__(svc, "sess-1")

        mock_log.warning.assert_called()
        call_args = mock_log.warning.call_args_list[0]
        # worktree_path appears in the formatted message
        assert "/tmp/wt/sess-1" in str(call_args)

    def test_log_delete_orphan_index_failure(self):
        """index.remove_session raises → _log.warning."""
        app = _make_app()
        rec = MagicMock()
        rec.id = "sess-1"
        rec.worktree_path = ""
        mgr = _make_session_mgr(sessions=[rec])
        mgr.index.remove_session.side_effect = RuntimeError("remove err")
        app._session_mgr = mgr

        svc = _make_sessions_svc(app)

        with (
            patch("hermes_cli.tui.services.sessions._log") as mock_log,
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
        ):
            svc.delete_orphan_session.__wrapped__(svc, "sess-1")

        mock_log.warning.assert_called()
        assert any("index.remove_session" in str(c) for c in mock_log.warning.call_args_list)

    def test_log_resume_session_failure(self):
        """_handle_resume_command raises → _log.exception called."""
        app = _make_app()
        cli = MagicMock()
        cli._handle_resume_command.side_effect = RuntimeError("resume error")
        app.cli = cli

        svc = _make_sessions_svc(app)

        with patch("hermes_cli.tui.services.sessions._log") as mock_log:
            svc.resume_session.__wrapped__(svc, "sess-1")  # must not propagate

        mock_log.exception.assert_called_once()
        assert "resume_session" in mock_log.exception.call_args[0][0]


# ===========================================================================
# LOG-2: WatchersService logging
# ===========================================================================

class TestWatchersLogging:

    def test_handle_file_drop_logs_exception(self):
        """handle_file_drop_inner raises → _log.exception called; flash hint called."""
        app = _make_app()
        svc = _make_watchers_svc(app)
        svc.handle_file_drop_inner = MagicMock(side_effect=RuntimeError("drop fail"))

        with patch("hermes_cli.tui.services.watchers._log") as mock_log:
            svc.handle_file_drop([])

        mock_log.exception.assert_called_once()
        assert "handle_file_drop" in mock_log.exception.call_args[0][0]
        app._flash_hint.assert_called_once()
        assert "see log" in app._flash_hint.call_args[0][0]

    def test_handle_file_drop_inner_ok_no_log(self):
        """No exception → _log.exception never called."""
        app = _make_app()
        svc = _make_watchers_svc(app)
        svc.handle_file_drop_inner = MagicMock()

        with patch("hermes_cli.tui.services.watchers._log") as mock_log:
            svc.handle_file_drop([])

        mock_log.exception.assert_not_called()

    def test_compaction_flash_warn_logs_on_failure(self):
        """feedback.flash raises on warn threshold → _log.warning called."""
        app = _make_app(config={"display": {"compact_warn_threshold": 0.85, "compact_badge_threshold": 0.95}})
        app.feedback.flash.side_effect = RuntimeError("flash error")
        svc = _make_watchers_svc(app)
        svc._compact_warn_flashed = False

        with patch("hermes_cli.tui.services.watchers._log") as mock_log:
            svc.on_status_compaction_progress(0.86)

        mock_log.warning.assert_called()
        assert "feedback.flash" in mock_log.warning.call_args[0][0]
        assert mock_log.warning.call_args[1].get("exc_info") is True

    def test_compaction_crit_flash_logs_on_failure(self):
        """feedback.flash raises on crit threshold → _log.warning called."""
        app = _make_app(config={"display": {"compact_warn_threshold": 0.85, "compact_badge_threshold": 0.95}})
        app.feedback.flash.side_effect = RuntimeError("flash error")
        svc = _make_watchers_svc(app)
        svc._compact_warn_flashed = True  # skip warn branch
        app._compaction_warn_99 = False

        with patch("hermes_cli.tui.services.watchers._log") as mock_log:
            svc.on_status_compaction_progress(0.96)

        mock_log.warning.assert_called()
        assert "feedback.flash" in mock_log.warning.call_args[0][0]

    def test_on_compact_chevron_nomatch_no_log(self):
        """query_one raises NoMatches → narrowed except, no log call, no exception."""
        from textual.css.query import NoMatches
        app = _make_app()
        app.query_one = MagicMock(side_effect=NoMatches())
        app._classes = set()
        svc = _make_watchers_svc(app)

        with patch("hermes_cli.tui.services.watchers._log") as mock_log:
            svc.on_compact(True)  # must not raise

        mock_log.error.assert_not_called()
        mock_log.warning.assert_not_called()
        mock_log.exception.assert_not_called()

    def test_on_compact_toolpanel_no_wrapping_try(self):
        """query(ToolPanel) returns empty → loop body never entered; no exception."""
        app = _make_app()
        app._classes = set()
        app.query_one = MagicMock(return_value=MagicMock())
        app.query = MagicMock(return_value=[])

        svc = _make_watchers_svc(app)

        with patch("hermes_cli.tui.services.watchers._log") as mock_log:
            svc.on_compact(True)  # must not raise

        # No ToolPanel → set_class never called → no error logged
        mock_log.error.assert_not_called()

    def test_on_compact_sync_logs_on_failure(self):
        """sync_compact_visibility raises → _log.debug called."""
        app = _make_app()
        app._classes = set()
        app.query_one = MagicMock(return_value=MagicMock())
        app.query = MagicMock(return_value=[])
        svc = _make_watchers_svc(app)
        svc.sync_compact_visibility = MagicMock(side_effect=RuntimeError("sync fail"))

        with patch("hermes_cli.tui.services.watchers._log") as mock_log:
            svc.on_compact(True)

        mock_log.debug.assert_called()
        assert "sync_compact_visibility" in mock_log.debug.call_args[0][0]

    def test_on_status_error_inp_nomatch_no_log(self):
        """query_one raises NoMatches for input-area → no log; feedback.flash still runs."""
        from textual.css.query import NoMatches
        app = _make_app()
        app.query_one = MagicMock(side_effect=NoMatches())
        app.status_phase = "IDLE"
        svc = _make_watchers_svc(app)

        with patch("hermes_cli.tui.services.watchers._log") as mock_log:
            svc.on_status_error("some error")

        mock_log.error.assert_not_called()
        mock_log.exception.assert_not_called()
        app.feedback.flash.assert_called()

    def test_on_status_error_feedback_logs_on_failure(self):
        """feedback.flash raises → _log.warning with exc_info."""
        from textual.css.query import NoMatches
        app = _make_app()
        app.query_one = MagicMock(side_effect=NoMatches())
        app.feedback.flash.side_effect = RuntimeError("flash err")
        app.status_phase = "IDLE"
        svc = _make_watchers_svc(app)

        with patch("hermes_cli.tui.services.watchers._log") as mock_log:
            svc.on_status_error("some error")

        mock_log.warning.assert_called()
        assert "feedback flash/cancel" in mock_log.warning.call_args[0][0]
        assert mock_log.warning.call_args[1].get("exc_info") is True

    def test_on_approval_state_drawbraille_nomatch_no_log(self):
        """DrawbrailleOverlay query raises NoMatches → narrowed, no log, no exception."""
        from textual.css.query import NoMatches
        app = _make_app()
        app.query_one = MagicMock(side_effect=NoMatches())
        svc = _make_watchers_svc(app)
        svc._get_interrupt_overlay = MagicMock(return_value=None)

        with patch("hermes_cli.tui.services.watchers._log") as mock_log:
            svc.on_approval_state(None)

        mock_log.error.assert_not_called()
        mock_log.warning.assert_not_called()

    def test_post_interrupt_focus_nomatch_no_log(self):
        """query_one raises NoMatches → narrowed to NoMatches; no log call."""
        from textual.css.query import NoMatches
        app = _make_app()
        app.query_one = MagicMock(side_effect=NoMatches())
        svc = _make_watchers_svc(app)

        with patch("hermes_cli.tui.services.watchers._log") as mock_log:
            svc._post_interrupt_focus()

        mock_log.debug.assert_not_called()

    def test_post_interrupt_focus_unexpected_logs_debug(self):
        """Non-NoMatches error from call_after_refresh → _log.debug called."""
        app = _make_app()
        input_widget = MagicMock()
        app.query_one = MagicMock(return_value=input_widget)
        app.call_after_refresh = MagicMock(side_effect=RuntimeError("refresh error"))
        svc = _make_watchers_svc(app)

        with patch("hermes_cli.tui.services.watchers._log") as mock_log:
            svc._post_interrupt_focus()

        mock_log.debug.assert_called()
        assert "_post_interrupt_focus" in mock_log.debug.call_args[0][0]

    def test_on_undo_state_lock_failure_logs_debug(self):
        """_set_input_locked(True) raises → _log.debug; no exception propagates."""
        from textual.css.query import NoMatches
        app = _make_app()
        inp = MagicMock()
        inp._set_input_locked.side_effect = AttributeError("no method")
        app.query_one = MagicMock(return_value=inp)
        svc = _make_watchers_svc(app)
        svc._get_interrupt_overlay = MagicMock(return_value=None)

        undo_state = MagicMock()  # non-None value triggers lock path

        with patch("hermes_cli.tui.services.watchers._log") as mock_log:
            svc.on_undo_state(undo_state)

        mock_log.debug.assert_called()
        assert "_set_input_locked(True)" in mock_log.debug.call_args[0][0]

    def test_on_undo_state_unlock_failure_logs_debug(self):
        """_set_input_locked(False) raises → _log.debug; no exception propagates."""
        app = _make_app()
        inp = MagicMock()
        inp._set_input_locked.side_effect = AttributeError("no method")
        app.query_one = MagicMock(return_value=inp)
        app.agent_running = False
        app.command_running = False
        svc = _make_watchers_svc(app)
        svc._get_interrupt_overlay = MagicMock(return_value=None)

        with patch("hermes_cli.tui.services.watchers._log") as mock_log:
            svc.on_undo_state(None)  # None → unlock path

        mock_log.debug.assert_called()
        assert "_set_input_locked(False)" in mock_log.debug.call_args[0][0]
