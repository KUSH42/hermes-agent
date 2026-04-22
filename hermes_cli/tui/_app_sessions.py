"""_SessionsMixin — parallel worktree session management for HermesApp."""
from __future__ import annotations

from typing import Any

from textual import work
from textual.css.query import NoMatches

from hermes_cli.tui.overlays import SessionOverlay


class _SessionsMixin:
    """Parallel worktree session management methods.

    Extracted from HermesApp to reduce file size.  Self is always a HermesApp
    instance at runtime — all attribute access on self is valid.
    """

    @property
    def _sessions_enabled(self) -> bool:
        """True when sessions.enabled is set in CLI config."""
        if self._sessions_enabled_override is not None:  # type: ignore[attr-defined]
            return self._sessions_enabled_override  # type: ignore[attr-defined]
        try:
            from hermes_cli.config import CLI_CONFIG
            return bool(CLI_CONFIG.get("sessions", {}).get("enabled", False))
        except Exception:
            return False

    @_sessions_enabled.setter
    def _sessions_enabled(self, value: bool) -> None:
        self._sessions_enabled_override = value  # type: ignore[attr-defined]

    def _init_sessions(self) -> None:
        """Initialize parallel session infrastructure (event-loop only)."""
        from hermes_cli.tui.session_manager import SessionManager, _NotifyListener
        from hermes_cli.tui.session_widgets import SessionBar
        cfg = getattr(self, "_sessions_cfg", {})
        if not cfg:
            cli_cfg = getattr(getattr(self, "cli", None), "config", None) or {}
            cfg = cli_cfg.get("sessions", {}) if isinstance(cli_cfg, dict) else {}
        if not cfg.get("enabled", False):
            return
        self._sessions_enabled = True
        import os as _os
        session_dir = _os.path.expanduser(cfg.get("session_dir", "/tmp/hermes-sessions"))
        from pathlib import Path as _Path
        self._session_mgr = SessionManager(  # type: ignore[attr-defined]
            _Path(session_dir),
            max_sessions=int(cfg.get("max_sessions", 8)),
        )
        self._session_records_cache = self._session_mgr.index.get_sessions()  # type: ignore[attr-defined]
        self._session_active_id = self._session_mgr.index.get_active_id()  # type: ignore[attr-defined]
        self._sync_compact_visibility()  # type: ignore[attr-defined]
        try:
            bar = self.query_one(SessionBar)  # type: ignore[attr-defined]
            bar.add_class("--sessions-enabled")
            bar.update_sessions(
                self._session_records_cache,  # type: ignore[attr-defined]
                self._session_active_id,  # type: ignore[attr-defined]
                self._session_mgr._max_sessions,  # type: ignore[attr-defined]
            )
        except NoMatches:
            pass
        if self._own_session_id:  # type: ignore[attr-defined]
            try:
                sock_path = str(
                    _Path(session_dir) / self._own_session_id / "notify.sock"  # type: ignore[attr-defined]
                )
                self._notify_listener = _NotifyListener(  # type: ignore[attr-defined]
                    sock_path, self._on_session_notify_event
                )
                self._notify_listener.start()  # type: ignore[attr-defined]
            except Exception:
                pass
        self._sessions_poll_timer = self.set_interval(2.0, self._poll_session_index)  # type: ignore[attr-defined]

    def _get_session_records(self) -> list:
        """Return cached session records. Event-loop safe."""
        return list(self._session_records_cache)  # type: ignore[attr-defined]

    def _get_active_session_id(self) -> str:
        """Return active session ID. Event-loop safe."""
        return self._session_active_id  # type: ignore[attr-defined]

    def _refresh_session_bar(self) -> None:
        """Rebuild SessionBar from current cache. Event-loop only."""
        from hermes_cli.tui.session_widgets import SessionBar
        if not self._sessions_enabled:
            return
        try:
            bar = self.query_one(SessionBar)  # type: ignore[attr-defined]
            max_s = self._session_mgr._max_sessions if self._session_mgr else 8  # type: ignore[attr-defined]
            bar.update_sessions(
                self._session_records_cache,  # type: ignore[attr-defined]
                self._session_active_id,  # type: ignore[attr-defined]
                max_s,
            )
        except NoMatches:
            pass

    def _poll_session_index(self) -> None:
        """Event-loop: re-read sessions.json every 2s and refresh bar on change."""
        if not self._session_mgr:  # type: ignore[attr-defined]
            return
        try:
            records = self._session_mgr.index.get_sessions()  # type: ignore[attr-defined]
            active_id = self._session_mgr.index.get_active_id()  # type: ignore[attr-defined]
            if records != self._session_records_cache or active_id != self._session_active_id:  # type: ignore[attr-defined]
                self._session_records_cache = records  # type: ignore[attr-defined]
                self._session_active_id = active_id  # type: ignore[attr-defined]
                self._refresh_session_bar()
                self._sync_compact_visibility()  # type: ignore[attr-defined]
        except Exception:
            pass

    def _refresh_session_records_from_index(self) -> None:
        """Re-read sessions.json and update bar. Event-loop only."""
        self._poll_session_index()

    def _open_new_session_overlay(self) -> None:
        """Show NewSession interrupt overlay. Event-loop only."""
        from hermes_cli.tui.overlays import InterruptOverlay
        from hermes_cli.tui.overlays._adapters import make_new_session_payload
        if not self._sessions_enabled:
            return
        self._dismiss_all_info_overlays()  # type: ignore[attr-defined]
        try:
            ov = self.query_one(InterruptOverlay)  # type: ignore[attr-defined]
            ov.present(make_new_session_payload(), replace=True)
        except NoMatches:
            pass

    def _flash_sessions_max(self) -> None:
        """Flash HintBar with max sessions message. Event-loop only."""
        self._flash_hint("Max sessions reached", duration=2.0)  # type: ignore[attr-defined]

    def action_new_worktree_session(self) -> None:
        """Ctrl+W N — open new session overlay."""
        if not self._sessions_enabled:
            return
        if len(self._session_records_cache) >= (  # type: ignore[attr-defined]
            self._session_mgr._max_sessions if self._session_mgr else 8  # type: ignore[attr-defined]
        ):
            self._flash_sessions_max()
            return
        self._open_new_session_overlay()

    def _switch_to_session_by_index(self, n: int) -> None:
        """Switch to session by 0-based index in session bar. Event-loop only."""
        if not self._sessions_enabled or not self._session_records_cache:  # type: ignore[attr-defined]
            return
        if 0 <= n < len(self._session_records_cache):  # type: ignore[attr-defined]
            rec = self._session_records_cache[n]  # type: ignore[attr-defined]
            target_id = getattr(rec, "id", None)
            if target_id and target_id != self._session_active_id:  # type: ignore[attr-defined]
                self._switch_to_session(target_id)

    def _switch_to_session(self, session_id: str) -> None:
        """Switch to a background session via os.execvp. Event-loop only."""
        import sys as _sys
        if session_id == self._session_active_id or not self._sessions_enabled:  # type: ignore[attr-defined]
            return
        try:
            if self._session_mgr:  # type: ignore[attr-defined]
                self._session_mgr.index.update_active(session_id)  # type: ignore[attr-defined]
        except Exception:
            pass
        if self._notify_listener:  # type: ignore[attr-defined]
            try:
                self._notify_listener.stop()  # type: ignore[attr-defined]
            except Exception:
                pass
        if self._sessions_poll_timer:  # type: ignore[attr-defined]
            try:
                self._sessions_poll_timer.stop()  # type: ignore[attr-defined]
            except Exception:
                pass

        def _do_exec() -> None:
            import os as _os
            _os.execvp(_sys.argv[0], [_sys.argv[0], "--worktree-session-id", session_id])

        self.exit(callback=_do_exec)  # type: ignore[attr-defined]

    def _on_session_notify_event(self, event: dict) -> None:
        """Called from _NotifyListener daemon thread — must use call_from_thread."""
        self.call_from_thread(self._handle_session_event, event)  # type: ignore[attr-defined]

    def _handle_session_event(self, event: dict) -> None:
        """Event-loop: route IPC notification to _SessionNotification widget."""
        from hermes_cli.tui.session_widgets import _SessionNotification
        try:
            notif = self.query_one(_SessionNotification)  # type: ignore[attr-defined]
            notif.push(event)
        except NoMatches:
            pass
        self._refresh_session_records_from_index()

    @work(thread=True)
    def _create_new_session(self, branch: str, base: str, overlay: object) -> None:
        """Worker: git worktree add + spawn headless process + register in index."""
        import subprocess as _sp
        import sys as _sys
        if not self._session_mgr:  # type: ignore[attr-defined]
            self.call_from_thread(  # type: ignore[attr-defined]
                getattr(overlay, "_set_error", lambda m: None), "Sessions not initialized."
            )
            return
        new_id = self._session_mgr.new_id()  # type: ignore[attr-defined]
        try:
            self._session_mgr.validate_socket_path(new_id)  # type: ignore[attr-defined]
        except ValueError as exc:
            self.call_from_thread(  # type: ignore[attr-defined]
                getattr(overlay, "_set_error", lambda m: None), str(exc)
            )
            return
        worktree_path = self._session_mgr.create_session_dir(new_id)  # type: ignore[attr-defined]
        base_ref = "HEAD" if base == "current" else "main"
        try:
            _sp.run(
                ["git", "worktree", "add", str(worktree_path), "-b", branch, base_ref],
                capture_output=True, text=True, check=True,
            )
        except _sp.CalledProcessError as exc:
            err = (exc.stderr or "").strip() or "git worktree add failed"
            self.call_from_thread(  # type: ignore[attr-defined]
                getattr(overlay, "_set_error", lambda m: None), err
            )
            return
        try:
            _sp.Popen(
                [_sys.argv[0], "--headless", "--worktree-session-id", new_id],
                cwd=str(worktree_path),
                start_new_session=True,
            )
        except OSError as exc:
            self.call_from_thread(  # type: ignore[attr-defined]
                getattr(overlay, "_set_error", lambda m: None), f"Spawn failed: {exc}"
            )
            return
        rec = self._session_mgr.poll_state_until_pid(new_id, timeout=3.0)  # type: ignore[attr-defined]
        if rec is None:
            self.call_from_thread(  # type: ignore[attr-defined]
                getattr(overlay, "_set_error", lambda m: None), "Session failed to start."
            )
            try:
                _sp.run(
                    ["git", "worktree", "remove", "--force", str(worktree_path)],
                    capture_output=True, timeout=5,
                )
            except Exception:
                pass
            return
        try:
            self._session_mgr.index.add_session(rec)  # type: ignore[attr-defined]
        except Exception:
            pass
        self.call_from_thread(self._on_session_created, new_id, overlay)  # type: ignore[attr-defined]

    def _on_session_created(self, new_id: str, overlay: object) -> None:
        """Event-loop: dismiss overlay and refresh session bar after create."""
        dismiss = getattr(overlay, "action_dismiss", None)
        if dismiss:
            dismiss()
        self._refresh_session_records_from_index()

    @work(thread=True)
    def _kill_session_prompt(self, session_id: str) -> None:
        """Worker: find record and kill the session process."""
        records = self._session_mgr.index.get_sessions() if self._session_mgr else []  # type: ignore[attr-defined]
        rec = next((r for r in records if getattr(r, "id", None) == session_id), None)
        if rec is None:
            self.call_from_thread(self._flash_hint, "Session not found.", 2.0)  # type: ignore[attr-defined]
            return
        try:
            if self._session_mgr:  # type: ignore[attr-defined]
                self._session_mgr.kill_session(rec)  # type: ignore[attr-defined]
            self._session_mgr.index.remove_session(session_id)  # type: ignore[attr-defined]
        except Exception:
            pass
        self.call_from_thread(self._refresh_session_records_from_index)  # type: ignore[attr-defined]

    @work(thread=True)
    def _do_kill_session(self, session_id: str) -> None:
        """Worker: kill session process and remove from index."""
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
        self.call_from_thread(self._flash_hint, f"Session {session_id[:8]} killed", 1.5)  # type: ignore[attr-defined]

    @work(thread=True)
    def _open_merge_overlay(self, session_id: str) -> None:
        """Worker: fetch diff stat then show MergeConfirmOverlay."""
        import subprocess as _sp
        records = self._session_mgr.index.get_sessions() if self._session_mgr else []  # type: ignore[attr-defined]
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
            diff_stat = "(error fetching diff)"
        self.call_from_thread(self._show_merge_overlay, session_id, diff_stat)  # type: ignore[attr-defined]

    def _show_merge_overlay(self, session_id: str, diff_stat: str) -> None:
        """Event-loop: open MergeConfirm interrupt overlay for the given session."""
        from hermes_cli.tui.overlays import InterruptOverlay
        from hermes_cli.tui.overlays._adapters import make_merge_confirm_payload
        try:
            overlay = self.query_one(InterruptOverlay)  # type: ignore[attr-defined]
            overlay.present(
                make_merge_confirm_payload(session_id, diff_stat), replace=True
            )
        except NoMatches:
            pass

    @work(thread=True)
    def _run_merge(
        self,
        session_id: str,
        strategy: str,
        close_on_success: bool,
        overlay: object,
    ) -> None:
        """Worker: run git merge/squash/rebase for the session branch."""
        import subprocess as _sp
        records = self._session_mgr.index.get_sessions() if self._session_mgr else []  # type: ignore[attr-defined]
        rec = next((r for r in records if getattr(r, "id", None) == session_id), None)
        if rec is None:
            self.call_from_thread(  # type: ignore[attr-defined]
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
                self.call_from_thread(  # type: ignore[attr-defined]
                    getattr(overlay, "_set_error", lambda m: None), err
                )
                return
        except Exception as exc:
            self.call_from_thread(  # type: ignore[attr-defined]
                getattr(overlay, "_set_error", lambda m: None), str(exc)
            )
            return
        if close_on_success:
            try:
                if self._session_mgr:  # type: ignore[attr-defined]
                    self._session_mgr.kill_session(rec)  # type: ignore[attr-defined]
                    _sp.run(
                        ["git", "worktree", "remove", "--force", getattr(rec, "worktree_path", "")],
                        capture_output=True, timeout=10,
                    )
                    self._session_mgr.index.remove_session(session_id)  # type: ignore[attr-defined]
            except Exception:
                pass
        self.call_from_thread(self._refresh_session_records_from_index)  # type: ignore[attr-defined]
        self.call_from_thread(getattr(overlay, "action_dismiss", lambda: None))  # type: ignore[attr-defined]

    @work(thread=True)
    def _reopen_orphan_session(self, session_id: str) -> None:
        """Worker: spawn new headless process in an orphan worktree."""
        import subprocess as _sp
        import sys as _sys
        records = self._session_mgr.index.get_sessions() if self._session_mgr else []  # type: ignore[attr-defined]
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
        except Exception:
            return
        new_rec = self._session_mgr.poll_state_until_pid(session_id, timeout=3.0) if self._session_mgr else None  # type: ignore[attr-defined]
        if new_rec:
            try:
                self._session_mgr.index.add_session(new_rec)  # type: ignore[attr-defined]
            except Exception:
                pass
        self.call_from_thread(self._refresh_session_records_from_index)  # type: ignore[attr-defined]

    @work(thread=True)
    def _delete_orphan_session(self, session_id: str) -> None:
        """Worker: remove worktree dir and session index entry."""
        import subprocess as _sp
        records = self._session_mgr.index.get_sessions() if self._session_mgr else []  # type: ignore[attr-defined]
        rec = next((r for r in records if getattr(r, "id", None) == session_id), None)
        worktree_path = getattr(rec, "worktree_path", "") if rec else ""
        if worktree_path:
            try:
                _sp.run(
                    ["git", "worktree", "remove", "--force", worktree_path],
                    capture_output=True, timeout=10,
                )
            except Exception:
                pass
        try:
            if self._session_mgr:  # type: ignore[attr-defined]
                self._session_mgr.index.remove_session(session_id)  # type: ignore[attr-defined]
        except Exception:
            pass
        self.call_from_thread(self._refresh_session_records_from_index)  # type: ignore[attr-defined]

    @work(thread=True)
    def action_resume_session(self, session_id: str) -> None:
        """Resume a session by ID (runs in worker thread)."""
        cli = self.cli  # type: ignore[attr-defined]
        try:
            if hasattr(cli, "_handle_resume_command"):
                cli._handle_resume_command(f"/resume {session_id}")
                db = getattr(cli, "_session_db", None)
                session_meta: dict = {}
                if db is not None:
                    try:
                        session_meta = db.get_session(session_id) or {}
                    except Exception:
                        pass
                title = session_meta.get("title") or ""
                msgs = getattr(cli, "conversation_history", []) or []
                turn_count = len([m for m in msgs if m.get("role") in ("user", "assistant")])
                self.call_from_thread(  # type: ignore[attr-defined]
                    self.handle_session_resume, session_id, title, turn_count
                )
        except Exception:
            pass

    def action_open_sessions(self) -> None:
        """Open the session browser overlay."""
        self._dismiss_all_info_overlays()  # type: ignore[attr-defined]
        try:
            self.query_one(SessionOverlay).open_sessions()  # type: ignore[attr-defined]
        except NoMatches:
            pass
