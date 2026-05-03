"""Parallel sessions orchestration service extracted from _app_sessions.py."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any


class SessionCreateTimeout(Exception):
    """Raised when poll_state_until_pid times out and the orphan is killed."""

_log = logging.getLogger(__name__)

from textual import work
from textual.css.query import NoMatches

from .base import AppService

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp


class SessionsService(AppService):
    """Parallel sessions orchestration."""

    def __init__(self, app: "HermesApp") -> None:
        super().__init__(app)
        # All session state lives on app for backward compat; service holds no extra state.
        self._has_other_active_sessions: bool = False  # SVC-12: set by NotifyListener

    # ------------------------------------------------------------------
    # SVC-1: listener teardown helpers
    # ------------------------------------------------------------------

    def stop_listener(self) -> None:
        """Idempotent: stop the notify listener and release the socket."""
        listener = self.app._notify_listener
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                _log.debug("stop_listener: stop failed", exc_info=True)
            self.app._notify_listener = None

    # ------------------------------------------------------------------
    # SVC-12: poll gate helpers
    # ------------------------------------------------------------------

    def _is_session_overlay_visible(self) -> bool:
        """Return True if the session-switcher overlay is mounted and visible."""
        from hermes_cli.tui.overlays import SessionOverlay
        try:
            return self.app.query_one(SessionOverlay).display
        except NoMatches:
            # NoMatches is expected when the overlay is not mounted — not an error
            return False
        except Exception:
            _log.debug("_is_session_overlay_visible: query failed", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def _sessions_enabled(self) -> bool:
        """True when sessions.enabled is set in CLI config."""
        if self.app._sessions_enabled_override is not None:
            return self.app._sessions_enabled_override
        try:
            from hermes_cli.config import CLI_CONFIG
            return bool(CLI_CONFIG.get("sessions", {}).get("enabled", False))
        except Exception:
            _log.debug("_sessions_enabled: config read failed", exc_info=True)
            return False

    @_sessions_enabled.setter
    def _sessions_enabled(self, value: bool) -> None:
        self.app._sessions_enabled_override = value

    def init_sessions(self) -> None:
        """Initialize parallel session infrastructure (event-loop only)."""
        from hermes_cli.tui.session_manager import SessionManager, _NotifyListener
        from hermes_cli.tui.session_widgets import SessionBar
        cfg = getattr(self.app, "_sessions_cfg", {})
        if not cfg:
            cli_cfg = getattr(getattr(self.app, "cli", None), "config", None) or {}
            cfg = cli_cfg.get("sessions", {}) if isinstance(cli_cfg, dict) else {}
        if not cfg.get("enabled", False):
            return
        self._sessions_enabled = True
        import os as _os
        session_dir = _os.path.expanduser(cfg.get("session_dir", "/tmp/hermes-sessions"))
        from pathlib import Path as _Path
        self.app._session_mgr = SessionManager(
            _Path(session_dir),
            max_sessions=int(cfg.get("max_sessions", 8)),
        )
        self.app._session_records_cache = self.app._session_mgr.index.get_sessions()
        self.app._session_active_id = self.app._session_mgr.index.get_active_id()
        self.app.session_count = len(self.app._session_records_cache)  # S1-D
        self._update_session_label()
        self.app._svc_watchers.sync_compact_visibility()
        try:
            bar = self.app.query_one(SessionBar)
            bar.add_class("--sessions-enabled")
            bar.update_sessions(
                self.app._session_records_cache,
                self.app._session_active_id,
                self.app._session_mgr._max_sessions,
            )
        except NoMatches:
            pass
        if self.app._own_session_id:
            try:
                sock_path = str(
                    _Path(session_dir) / self.app._own_session_id / "notify.sock"
                )
                self.app._notify_listener = _NotifyListener(
                    sock_path, self._on_session_notify_event
                )
                self.app._notify_listener.start()
            except Exception as exc:
                _log.warning("init_sessions: notify listener failed to start", exc_info=True)
        self.app._sessions_poll_timer = self.app.set_interval(2.0, self.poll_session_index)

    def _update_session_label(self) -> None:
        """Sync app.session_label with current cache state. Event-loop only."""
        records = self.app._session_records_cache
        active_id = self.app._session_active_id
        session_count = len(records)
        if session_count > 1:
            try:
                active_idx = next(
                    i + 1 for i, r in enumerate(records) if getattr(r, "id", None) == active_id
                )
            except StopIteration:
                active_idx = 1
            self.app.session_label = f"[{active_idx}/{session_count}]"
        else:
            self.app.session_label = ""

    def get_session_records(self) -> list:
        """Return cached session records. Event-loop safe."""
        return list(self.app._session_records_cache)

    def get_active_session_id(self) -> str:
        """Return active session ID. Event-loop safe."""
        return self.app._session_active_id

    def refresh_session_bar(self) -> None:
        """Rebuild SessionBar from current cache. Event-loop only."""
        from hermes_cli.tui.session_widgets import SessionBar
        if not self._sessions_enabled:
            return
        self._update_session_label()
        try:
            bar = self.app.query_one(SessionBar)
            max_s = self.app._session_mgr._max_sessions if self.app._session_mgr else 8
            bar.update_sessions(
                self.app._session_records_cache,
                self.app._session_active_id,
                max_s,
            )
        except NoMatches:
            pass

    def poll_session_index(self) -> None:
        """Event-loop: re-read sessions.json every 2s and refresh bar on change (SVC-12 gated)."""
        if not (self._is_session_overlay_visible() or self._has_other_active_sessions):
            return  # skip I/O — nobody observes the session list right now
        self._poll_session_index()

    def _poll_session_index(self) -> None:
        """Unconditional poll — called internally and by tests."""
        if not self.app._session_mgr:
            return
        try:
            records = self.app._session_mgr.index.get_sessions()
            active_id = self.app._session_mgr.index.get_active_id()
            # Reset _has_other_active_sessions if only one session remains (SVC-12)
            if len(records) <= 1:
                self._has_other_active_sessions = False
            if records != self.app._session_records_cache or active_id != self.app._session_active_id:
                self.app._session_records_cache = records
                self.app._session_active_id = active_id
                self.app.session_count = len(records)  # S1-D
                self._update_session_label()
                self.refresh_session_bar()
                self.app._svc_watchers.sync_compact_visibility()
        except Exception as exc:
            _log.warning("_poll_session_index: index read failed", exc_info=True)

    def refresh_session_records_from_index(self) -> None:
        """Re-read sessions.json and update bar. Event-loop only."""
        self.poll_session_index()

    def open_new_session_overlay(self) -> None:
        """Show NewSession interrupt overlay. Event-loop only."""
        from hermes_cli.tui.overlays import InterruptOverlay
        from hermes_cli.tui.overlays._adapters import make_new_session_payload
        if not self._sessions_enabled:
            return
        self.app._svc_context.dismiss_all_info_overlays()
        try:
            ov = self.app.query_one(InterruptOverlay)
            ov.present(make_new_session_payload(), replace=True)
        except NoMatches:
            pass

    def flash_sessions_max(self) -> None:
        """Flash HintBar with max sessions message. Event-loop only."""
        self.app._flash_hint("Max sessions reached", duration=2.0)

    def new_worktree_session(self) -> None:
        """Ctrl+W N — open new session overlay."""
        if not self._sessions_enabled:
            return
        if len(self.app._session_records_cache) >= (
            self.app._session_mgr._max_sessions if self.app._session_mgr else 8
        ):
            self.flash_sessions_max()
            return
        self.open_new_session_overlay()

    def switch_to_session_by_index(self, n: int) -> None:
        """Switch to session by 0-based index in session bar. Event-loop only."""
        if not self._sessions_enabled or not self.app._session_records_cache:
            return
        if 0 <= n < len(self.app._session_records_cache):
            rec = self.app._session_records_cache[n]
            target_id = getattr(rec, "id", None)
            if target_id and target_id != self.app._session_active_id:
                self.switch_to_session(target_id)

    def switch_to_session(self, session_id: str) -> None:
        """Switch to a background session via os.execvp. Event-loop only."""
        if session_id == self.app._session_active_id or not self._sessions_enabled:
            return
        try:
            if self.app._session_mgr:
                self.app._session_mgr.index.update_active(session_id)
        except Exception as exc:
            _log.warning("switch_to_session: update_active failed", exc_info=True)
        # SVC-1: do NOT stop listener here — _do_exec_switch worker stops it
        # just before execvp so the listener remains live for any arriving notifications.
        if self.app._sessions_poll_timer:
            try:
                self.app._sessions_poll_timer.stop()
            except Exception as exc:
                _log.debug("switch_to_session: timer stop failed: %s", exc, exc_info=True)
        # RX4: fire session_switch hooks so callers can release blocking queues
        # before execvp replaces the process.
        self.app.hooks.fire("on_session_switch", target_id=session_id)
        # Kick off the exec worker; it stops the listener then calls execvp.
        self._do_exec_switch(session_id)
        # Exit the app for clean UI teardown. execvp in the worker will replace
        # the process; if the worker runs first the exit is a no-op.
        self.app.exit()

    @work(thread=True)
    def _do_exec_switch(self, session_id: str) -> None:
        """Worker: stop listener then execvp into the target session."""
        import os as _os
        import sys as _sys
        try:
            self.stop_listener()  # safe: no more notifications expected at this point
            _os.execvp(_sys.argv[0], [_sys.argv[0], "--worktree-session-id", session_id])
        except Exception:
            _log.exception("SessionsService._do_exec_switch: execvp failed")

    def _on_session_notify_event(self, event: dict) -> None:
        """Called from _NotifyListener daemon thread — must use call_from_thread."""
        self._has_other_active_sessions = True  # SVC-12: another session is active
        self.app.call_from_thread(self.handle_session_event, event)

    def handle_session_event(self, event: dict) -> None:
        """Event-loop: route IPC notification to _SessionNotification widget."""
        from hermes_cli.tui.session_widgets import _SessionNotification
        try:
            notif = self.app.query_one(_SessionNotification)
            notif.push(event)
        except NoMatches:
            pass
        self.refresh_session_records_from_index()

    @work(thread=True)
    def create_new_session(self, branch: str, base: str, overlay: object) -> None:
        """Worker: git worktree add + spawn headless process + register in index."""
        try:
            import subprocess as _sp
            import sys as _sys
            if not self.app._session_mgr:
                self.app.call_from_thread(
                    getattr(overlay, "_set_error", lambda m: None), "Sessions not initialized."
                )
                return
            new_id = self.app._session_mgr.new_id()
            try:
                self.app._session_mgr.validate_socket_path(new_id)
            except ValueError as exc:
                self.app.call_from_thread(
                    getattr(overlay, "_set_error", lambda m: None), str(exc)
                )
                return
            worktree_path = self.app._session_mgr.create_session_dir(new_id)
            base_ref = "HEAD" if base == "current" else "main"
            try:
                _sp.run(
                    ["git", "worktree", "add", str(worktree_path), "-b", branch, base_ref],
                    capture_output=True, text=True, check=True,
                )
            except _sp.CalledProcessError as exc:
                err = (exc.stderr or "").strip() or "git worktree add failed"
                self.app.call_from_thread(
                    getattr(overlay, "_set_error", lambda m: None), err
                )
                return
            try:
                proc = _sp.Popen(
                    [_sys.argv[0], "--headless", "--worktree-session-id", new_id],
                    cwd=str(worktree_path),
                    start_new_session=True,
                )
            except OSError as exc:
                self.app.call_from_thread(
                    getattr(overlay, "_set_error", lambda m: None), f"Spawn failed: {exc}"
                )
                return
            # SVC-3: kill orphan process on poll timeout before raising
            try:
                rec = self.app._session_mgr.poll_state_until_pid(new_id, timeout=3.0)
                if rec is None:
                    _log.warning(
                        "create_new_session: poll timeout; killing orphan headless pid=%d",
                        proc.pid,
                    )
                    proc.terminate()
                    try:
                        proc.wait(timeout=2.0)
                    except _sp.TimeoutExpired:
                        _log.warning(
                            "create_new_session: SIGTERM ignored; sending SIGKILL to pid=%d",
                            proc.pid,
                        )
                        proc.kill()
                    self.app.call_from_thread(
                        getattr(overlay, "_set_error", lambda m: None), "Session failed to start."
                    )
                    try:
                        _sp.run(
                            ["git", "worktree", "remove", "--force", str(worktree_path)],
                            capture_output=True, timeout=5,
                        )
                    except Exception:
                        _log.warning("create_new_session: worktree cleanup failed", exc_info=True)
                    raise SessionCreateTimeout()
            except SessionCreateTimeout:
                raise  # already cleaned up above; don't re-enter cleanup
            except Exception:
                if proc.poll() is None:
                    proc.terminate()
                raise
            try:
                self.app._session_mgr.index.add_session(rec)
            except Exception as exc:
                _log.error("create_new_session: index.add_session failed", exc_info=True)
            self.app.call_from_thread(self.on_session_created, new_id, overlay)
        except SessionCreateTimeout:
            pass  # already logged and cleaned up by the inner raise path
        except Exception:
            _log.exception("sessions.create_new_session: failed")

    def on_session_created(self, new_id: str, overlay: object) -> None:
        """Event-loop: dismiss overlay and refresh session bar after create."""
        dismiss = getattr(overlay, "action_dismiss", None)
        if dismiss:
            dismiss()
        self.refresh_session_records_from_index()

    @work(thread=True)
    def kill_session_prompt(self, session_id: str) -> None:
        """Worker: find record and kill the session process."""
        try:
            records = self.app._session_mgr.index.get_sessions() if self.app._session_mgr else []
            rec = next((r for r in records if getattr(r, "id", None) == session_id), None)
            if rec is None:
                self.app.call_from_thread(
                    self.app._flash_hint, "Session not found.", 2.0
                )
                return
            try:
                if self.app._session_mgr:
                    self.app._session_mgr.kill_session(rec)
                self.app._session_mgr.index.remove_session(session_id)
            except Exception as exc:
                _log.warning("kill_session_prompt: kill or index remove failed", exc_info=True)
            self.app.call_from_thread(self.refresh_session_records_from_index)
        except Exception:
            _log.exception("sessions.kill_session_prompt: failed")

    @work(thread=True)
    def do_kill_session(self, session_id: str) -> None:
        """Worker: kill session process and remove from index."""
        try:
            from pathlib import Path
            from hermes_cli.config import CLI_CONFIG
            from hermes_cli.tui.session_manager import SessionManager
            sessions_cfg = CLI_CONFIG.get("sessions", {})
            session_dir = Path(sessions_cfg.get("session_dir", "/tmp/hermes-sessions"))
            mgr = SessionManager(session_dir)
            for rec in mgr.index.get_sessions():
                if rec.id == session_id:
                    mgr.kill_session(rec)
                    mgr.index.remove_session(session_id)
                    break
            self.app.call_from_thread(
                self.app._flash_hint, f"Session {session_id[:8]} killed", 1.5
            )
        except Exception:
            _log.exception("sessions.do_kill_session: failed")

    @work(thread=True)
    def open_merge_overlay(self, session_id: str) -> None:
        """Worker: fetch diff stat then show MergeConfirmOverlay."""
        try:
            import subprocess as _sp
            records = self.app._session_mgr.index.get_sessions() if self.app._session_mgr else []
            rec = next((r for r in records if getattr(r, "id", None) == session_id), None)
            if rec is None:
                return
            branch = getattr(rec, "branch", "")
            try:
                result = _sp.run(
                    ["git", "diff", "HEAD..." + branch, "--stat"],
                    capture_output=True, text=True, timeout=10,
                )
                diff_stat = result.stdout.strip() or "(no diff)"
            except Exception:
                _log.debug("open_merge_overlay: git diff failed", exc_info=True)
                diff_stat = "(error fetching diff)"
            self.app.call_from_thread(self.show_merge_overlay, session_id, diff_stat)
        except Exception:
            _log.exception("sessions.open_merge_overlay: failed")

    def show_merge_overlay(self, session_id: str, diff_stat: str) -> None:
        """Event-loop: open MergeConfirm interrupt overlay for the given session."""
        from hermes_cli.tui.overlays import InterruptOverlay
        from hermes_cli.tui.overlays._adapters import make_merge_confirm_payload
        try:
            overlay = self.app.query_one(InterruptOverlay)
            overlay.present(
                make_merge_confirm_payload(session_id, diff_stat), replace=True
            )
        except NoMatches:
            pass

    @work(thread=True)
    def run_merge(
        self,
        session_id: str,
        strategy: str,
        close_on_success: bool,
        overlay: object,
    ) -> None:
        """Worker: run git merge/squash/rebase for the session branch."""
        try:
            import subprocess as _sp
            records = self.app._session_mgr.index.get_sessions() if self.app._session_mgr else []
            rec = next((r for r in records if getattr(r, "id", None) == session_id), None)
            if rec is None:
                self.app.call_from_thread(
                    getattr(overlay, "_set_error", lambda m: None), "Session not found."
                )
                return
            branch = getattr(rec, "branch", "")
            if strategy == "squash":
                cmd = ["git", "merge", "--squash", branch]
            elif strategy == "rebase":
                cmd = ["git", "rebase", branch]
            else:
                cmd = ["git", "merge", branch]
            try:
                result = _sp.run(cmd, capture_output=True, text=True, timeout=60)
                if result.returncode != 0:
                    err = (result.stderr or result.stdout or "merge failed").strip()
                    self.app.call_from_thread(
                        getattr(overlay, "_set_error", lambda m: None), err
                    )
                    return
            except Exception as exc:
                _log.warning("run_merge: subprocess failed: %s", exc, exc_info=True)
                self.app.call_from_thread(getattr(overlay, "_set_error", lambda m: None), str(exc))
                return
            if close_on_success:
                try:
                    if self.app._session_mgr:
                        self.app._session_mgr.kill_session(rec)
                        _sp.run(
                            ["git", "worktree", "remove", "--force", getattr(rec, "worktree_path", "")],
                            capture_output=True, timeout=10,
                        )
                        self.app._session_mgr.index.remove_session(session_id)
                except Exception as exc:
                    _log.warning("run_merge: post-merge cleanup failed", exc_info=True)
            self.app.call_from_thread(self.refresh_session_records_from_index)
            self.app.call_from_thread(getattr(overlay, "action_dismiss", lambda: None))
        except Exception:
            _log.exception("sessions.run_merge: failed")

    @work(thread=True)
    def reopen_orphan_session(self, session_id: str) -> None:
        """Worker: spawn new headless process in an orphan worktree."""
        try:
            import subprocess as _sp
            import sys as _sys
            records = self.app._session_mgr.index.get_sessions() if self.app._session_mgr else []
            rec = next((r for r in records if getattr(r, "id", None) == session_id), None)
            if rec is None:
                return
            worktree_path = getattr(rec, "worktree_path", "")
            try:
                _sp.Popen(
                    [_sys.argv[0], "--headless", "--worktree-session-id", session_id],
                    cwd=worktree_path,
                    start_new_session=True,
                )
            except Exception as exc:
                _log.error("reopen_orphan_session: Popen failed", exc_info=True)
                return
            new_rec = self.app._session_mgr.poll_state_until_pid(session_id, timeout=3.0) if self.app._session_mgr else None
            if new_rec:
                try:
                    self.app._session_mgr.index.add_session(new_rec)
                except Exception as exc:
                    _log.warning("reopen_orphan_session: index.add_session failed", exc_info=True)
            self.app.call_from_thread(self.refresh_session_records_from_index)
        except Exception:
            _log.exception("sessions.reopen_orphan_session: failed")

    @work(thread=True)
    def delete_orphan_session(self, session_id: str) -> None:
        """Worker: remove worktree dir and session index entry."""
        try:
            import subprocess as _sp
            records = self.app._session_mgr.index.get_sessions() if self.app._session_mgr else []
            rec = next((r for r in records if getattr(r, "id", None) == session_id), None)
            worktree_path = getattr(rec, "worktree_path", "") if rec else ""
            if worktree_path:
                try:
                    _sp.run(
                        ["git", "worktree", "remove", "--force", worktree_path],
                        capture_output=True, timeout=10,
                    )
                except Exception as exc:
                    _log.warning("delete_orphan_session: worktree remove failed %r", worktree_path, exc_info=True)
            try:
                if self.app._session_mgr:
                    self.app._session_mgr.index.remove_session(session_id)
            except Exception as exc:
                _log.warning("delete_orphan_session: index.remove_session failed", exc_info=True)
            self.app.call_from_thread(self.refresh_session_records_from_index)
        except Exception:
            _log.exception("sessions.delete_orphan_session: failed")

    @work(thread=True)
    def resume_session(self, session_id: str) -> None:
        """Resume a session by ID (runs in worker thread)."""
        try:
            cli = self.app.cli
            if hasattr(cli, "_handle_resume_command"):
                cli._handle_resume_command(f"/resume {session_id}")
                db = getattr(cli, "_session_db", None)
                session_meta: dict = {}
                if db is not None:
                    try:
                        session_meta = db.get_session(session_id) or {}
                    except Exception:
                        # DB read for session metadata is best-effort; empty dict means no title shown
                        pass
                title = session_meta.get("title") or ""
                msgs = getattr(cli, "conversation_history", []) or []
                turn_count = len([m for m in msgs if m.get("role") in ("user", "assistant")])
                self.app.call_from_thread(
                    self.app.handle_session_resume, session_id, title, turn_count
                )
        except Exception:
            _log.exception("resume_session: failed")

    def open_sessions(self) -> None:
        """Open the session browser overlay."""
        from hermes_cli.tui.overlays import SessionOverlay
        self.app._svc_context.dismiss_all_info_overlays()
        try:
            self.app.query_one(SessionOverlay).open_sessions()
        except NoMatches:
            pass
