"""_SessionsMixin — parallel worktree session management for HermesApp.

Phase 2: all logic lives in SessionsService; methods here are 1-line adapters.
"""
from __future__ import annotations

from typing import Any

from textual import work
from textual.css.query import NoMatches

from hermes_cli.tui.overlays import SessionOverlay


class _SessionsMixin:
    """Parallel worktree session management methods.

    Extracted from HermesApp to reduce file size.  Self is always a HermesApp
    instance at runtime — all attribute access on self is valid.

    Phase 2: all logic delegated to self._svc_sessions (SessionsService).
    """

    @property
    def _sessions_enabled(self) -> bool:
        return self._svc_sessions._sessions_enabled  # type: ignore[attr-defined]

    @_sessions_enabled.setter
    def _sessions_enabled(self, value: bool) -> None:
        self._svc_sessions._sessions_enabled = value  # type: ignore[attr-defined]

    def _init_sessions(self) -> None:
        return self._svc_sessions.init_sessions()  # type: ignore[attr-defined]  # DEPRECATED

    def _get_session_records(self) -> list:
        return self._svc_sessions.get_session_records()  # type: ignore[attr-defined]  # DEPRECATED

    def _get_active_session_id(self) -> str:
        return self._svc_sessions.get_active_session_id()  # type: ignore[attr-defined]  # DEPRECATED

    def _refresh_session_bar(self) -> None:
        return self._svc_sessions.refresh_session_bar()  # type: ignore[attr-defined]  # DEPRECATED

    def _poll_session_index(self) -> None:
        return self._svc_sessions.poll_session_index()  # type: ignore[attr-defined]  # DEPRECATED

    def _refresh_session_records_from_index(self) -> None:
        return self._svc_sessions.refresh_session_records_from_index()  # type: ignore[attr-defined]  # DEPRECATED

    def _open_new_session_overlay(self) -> None:
        return self._svc_sessions.open_new_session_overlay()  # type: ignore[attr-defined]  # DEPRECATED

    def _flash_sessions_max(self) -> None:
        return self._svc_sessions.flash_sessions_max()  # type: ignore[attr-defined]  # DEPRECATED

    def action_new_worktree_session(self) -> None:
        """Ctrl+W N — open new session overlay."""
        return self._svc_sessions.new_worktree_session()  # type: ignore[attr-defined]

    def _switch_to_session_by_index(self, n: int) -> None:
        return self._svc_sessions.switch_to_session_by_index(n)  # type: ignore[attr-defined]  # DEPRECATED

    def _switch_to_session(self, session_id: str) -> None:
        return self._svc_sessions.switch_to_session(session_id)  # type: ignore[attr-defined]  # DEPRECATED

    def _on_session_notify_event(self, event: dict) -> None:
        return self._svc_sessions._on_session_notify_event(event)  # type: ignore[attr-defined]  # DEPRECATED

    def _handle_session_event(self, event: dict) -> None:
        return self._svc_sessions.handle_session_event(event)  # type: ignore[attr-defined]  # DEPRECATED

    def _create_new_session(self, branch: str, base: str, overlay: object) -> None:
        return self._svc_sessions.create_new_session(branch, base, overlay)  # type: ignore[attr-defined]  # DEPRECATED

    def _on_session_created(self, new_id: str, overlay: object) -> None:
        return self._svc_sessions.on_session_created(new_id, overlay)  # type: ignore[attr-defined]  # DEPRECATED

    def _kill_session_prompt(self, session_id: str) -> None:
        return self._svc_sessions.kill_session_prompt(session_id)  # type: ignore[attr-defined]  # DEPRECATED

    def _do_kill_session(self, session_id: str) -> None:
        return self._svc_sessions.do_kill_session(session_id)  # type: ignore[attr-defined]  # DEPRECATED

    def _open_merge_overlay(self, session_id: str) -> None:
        return self._svc_sessions.open_merge_overlay(session_id)  # type: ignore[attr-defined]  # DEPRECATED

    def _show_merge_overlay(self, session_id: str, diff_stat: str) -> None:
        return self._svc_sessions.show_merge_overlay(session_id, diff_stat)  # type: ignore[attr-defined]  # DEPRECATED

    def _run_merge(self, session_id: str, strategy: str, close_on_success: bool, overlay: object) -> None:
        return self._svc_sessions.run_merge(session_id, strategy, close_on_success, overlay)  # type: ignore[attr-defined]  # DEPRECATED

    def _reopen_orphan_session(self, session_id: str) -> None:
        return self._svc_sessions.reopen_orphan_session(session_id)  # type: ignore[attr-defined]  # DEPRECATED

    def _delete_orphan_session(self, session_id: str) -> None:
        return self._svc_sessions.delete_orphan_session(session_id)  # type: ignore[attr-defined]  # DEPRECATED

    def action_resume_session(self, session_id: str) -> None:
        """Resume a session by ID."""
        return self._svc_sessions.resume_session(session_id)  # type: ignore[attr-defined]

    def action_open_sessions(self) -> None:
        """Open the session browser overlay."""
        return self._svc_sessions.open_sessions()  # type: ignore[attr-defined]
