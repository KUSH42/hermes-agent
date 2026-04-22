"""Widgets for parallel worktree sessions UI."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, RichLog, Static


class SessionBar(Widget):
    """Bottom chrome strip showing parallel worktree sessions.

    Shows active session (●) and background sessions (○). Pulsing [●]
    = agent running in background session.
    """

    DEFAULT_CSS = """
    SessionBar {
        dock: bottom;
        height: 1;
        width: 1fr;
        padding: 0 1;
        background: $surface;
        color: $text-muted;
        display: none;
    }
    SessionBar.--sessions-enabled { display: block; }
    SessionBar .--active-session { color: $accent; }
    SessionBar .--bg-running { color: $warning; }
    SessionBar .--add-btn { color: $text-muted; }
    SessionBar .--add-btn-disabled { color: $text-disabled; }
    """

    _sessions_data: reactive[list] = reactive([], layout=True)

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._active_id: str = ""
        self._max_sessions: int = 8

    def compose(self) -> ComposeResult:
        yield Horizontal(id="session-bar-inner")

    def on_mount(self) -> None:
        self._rebuild()

    def update_sessions(
        self,
        records: list,
        active_id: str,
        max_sessions: int = 8,
    ) -> None:
        self._active_id = active_id
        self._max_sessions = max_sessions
        self._sessions_data = list(records)
        self._rebuild()

    def _rebuild(self) -> None:
        try:
            inner = self.query_one("#session-bar-inner", Horizontal)
        except Exception:
            return
        records = self._sessions_data
        widgets = []
        for i, rec in enumerate(records):
            is_active = (getattr(rec, "id", None) == self._active_id)
            running = getattr(rec, "agent_running", False)
            branch = getattr(rec, "branch", "") or getattr(rec, "id", "?")
            if is_active:
                marker = "●"
                suffix = ""
                css = "--active-session"
            else:
                marker = "○"
                suffix = " [●]" if running else ""
                css = "--bg-running" if running else ""
            label = f" {marker} {branch}{suffix} "
            btn = Button(label, id=f"sess-btn-{i}", classes=css)
            widgets.append(btn)
        # Add "+" button
        at_max = len(records) >= self._max_sessions
        add_label = " [dim]+[/dim] " if at_max else " + "
        add_css = "--add-btn-disabled" if at_max else "--add-btn"
        widgets.append(Button(add_label, id="sess-add-btn", classes=add_css))
        # Remove existing children individually to avoid async-removal vs sync-mount race.
        for child in list(inner.children):
            child.remove()
        if widgets:
            _w = widgets
            inner.call_after_refresh(lambda: inner.mount(*_w))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id == "sess-add-btn":
            event.stop()
            if len(self._sessions_data) < self._max_sessions:
                try:
                    self.app._open_new_session_overlay()
                except Exception:
                    pass
            else:
                try:
                    self.app._flash_sessions_max()
                except Exception:
                    pass
            return
        if btn_id.startswith("sess-btn-"):
            idx = int(btn_id.split("-")[-1])
            if 0 <= idx < len(self._sessions_data):
                rec = self._sessions_data[idx]
                target_id = getattr(rec, "id", None)
                if target_id and target_id != self._active_id:
                    try:
                        self.app._switch_to_session(target_id)
                    except Exception:
                        pass
            event.stop()


class _WorktreeSessionRow(Horizontal):
    """Single row in the _SessionsTab: shows session info + action buttons."""

    DEFAULT_CSS = """
    _WorktreeSessionRow {
        height: 3;
        padding: 0 1;
        margin-bottom: 1;
    }
    _WorktreeSessionRow.--active { background: $accent 10%; }
    _WorktreeSessionRow.--orphan { background: $error 10%; }
    _WorktreeSessionRow > Static { width: 1fr; }
    _WorktreeSessionRow > Button { width: auto; margin: 0 1; }
    """

    def __init__(self, record: object, is_active: bool, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._record = record
        self._is_active = is_active
        if is_active:
            self.add_class("--active")

    def compose(self) -> ComposeResult:
        rec = self._record
        branch = getattr(rec, "branch", "")
        status = "idle"
        if getattr(rec, "agent_running", False):
            status = "running"
        is_orphan = getattr(rec, "_orphan", False)
        if is_orphan:
            self.add_class("--orphan")
            status = "orphan"
        icon = "●" if self._is_active else ("⚠" if is_orphan else "○")
        yield Static(f"{icon}  {branch}  [{status}]")
        if is_orphan:
            yield Button("[reopen]", id=f"reopen-{getattr(rec, 'id', '')}", variant="warning")
            yield Button("[delete]", id=f"delete-{getattr(rec, 'id', '')}", variant="error")
        elif not self._is_active:
            yield Button("[switch]", id=f"switch-{getattr(rec, 'id', '')}")
            yield Button("[merge]", id=f"merge-{getattr(rec, 'id', '')}")
            yield Button("[kill]", id=f"kill-{getattr(rec, 'id', '')}", variant="error")
        else:
            yield Static("[dim](switch away to kill)[/dim]")


class _SessionsTab(Widget):
    """Content pane for the Sessions tab inside WorkspaceOverlay."""

    DEFAULT_CSS = """
    _SessionsTab {
        height: auto;
        max-height: 20;
        overflow-y: auto;
    }
    _SessionsTab #sess-tab-list { height: auto; }
    _SessionsTab #sess-tab-footer { height: 1; color: $text-muted; }
    """

    def compose(self) -> ComposeResult:
        yield Vertical(id="sess-tab-list")
        yield Button("[ + New Session ]", id="sess-tab-new")
        yield Static("[dim]Alt+1–9 switch · Ctrl+W N new session[/dim]", id="sess-tab-footer")

    def refresh_sessions(self, records: list, active_id: str) -> None:
        try:
            lst = self.query_one("#sess-tab-list", Vertical)
        except Exception:
            return
        lst.remove_children()
        rows = []
        for rec in records:
            is_active = (getattr(rec, "id", None) == active_id)
            rows.append(_WorktreeSessionRow(rec, is_active))
        if rows:
            lst.mount(*rows)
        else:
            lst.mount(Static("[dim]No parallel sessions — press + to create one.[/dim]"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        app = self.app
        if btn_id == "sess-tab-new":
            event.stop()
            try:
                app._open_new_session_overlay()
            except Exception:
                pass
        elif btn_id.startswith("switch-"):
            sid = btn_id[len("switch-"):]
            event.stop()
            try:
                app._switch_to_session(sid)
            except Exception:
                pass
        elif btn_id.startswith("kill-"):
            sid = btn_id[len("kill-"):]
            event.stop()
            try:
                app._kill_session_prompt(sid)
            except Exception:
                pass
        elif btn_id.startswith("merge-"):
            sid = btn_id[len("merge-"):]
            event.stop()
            try:
                app._open_merge_overlay(sid)
            except Exception:
                pass
        elif btn_id.startswith("reopen-"):
            sid = btn_id[len("reopen-"):]
            event.stop()
            try:
                app._reopen_orphan_session(sid)
            except Exception:
                pass
        elif btn_id.startswith("delete-"):
            sid = btn_id[len("delete-"):]
            event.stop()
            try:
                app._delete_orphan_session(sid)
            except Exception:
                pass


# R3 Phase B: NewSessionOverlay / MergeConfirmOverlay class bodies deleted;
# names re-export as alias proxies from overlays._aliases.
from hermes_cli.tui.overlays._aliases import (  # noqa: F401,E402
    MergeConfirmOverlay,
    NewSessionOverlay,
)


class _SessionNotification(Horizontal):
    """Transient notification widget for cross-session events.

    Mounts into the same dock slot as HintBar. Holds 5s then auto-dismisses.
    Multiple events queue in _queue; shows next on dismiss.
    Does NOT use _flash_hint_expires — independent timer.
    """

    DEFAULT_CSS = """
    _SessionNotification {
        layer: overlay;
        dock: bottom;
        height: 1;
        width: 1fr;
        padding: 0 1;
        background: $accent 20%;
        color: $text;
        display: none;
    }
    _SessionNotification.--visible { display: block; }
    _SessionNotification > Static { width: 1fr; }
    _SessionNotification > Button { width: auto; }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._queue: list[dict] = []
        self._timer = None

    def compose(self) -> ComposeResult:
        yield Static("", id="sn-message")
        yield Button("[switch]", id="sn-switch")

    def push(self, event: dict) -> None:
        self._queue.append(event)
        if not self.has_class("--visible"):
            self._show_next()

    def _show_next(self) -> None:
        if not self._queue:
            self.remove_class("--visible")
            return
        event = self._queue.pop(0)
        msg = event.get("message", "")
        self._current_session_id = event.get("session_id", "")
        try:
            self.query_one("#sn-message", Static).update(f"{self._current_session_id}: {msg}")
        except Exception:
            pass
        self.add_class("--visible")
        if self._timer:
            try:
                self._timer.stop()
            except Exception:
                pass
        self._timer = self.set_timer(5.0, self._auto_dismiss)

    def _auto_dismiss(self) -> None:
        self._timer = None
        self.remove_class("--visible")
        self._show_next()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "sn-switch":
            event.stop()
            sid = getattr(self, "_current_session_id", "")
            if sid:
                self.remove_class("--visible")
                self._timer = None
                try:
                    self.app._switch_to_session(sid)
                except Exception:
                    pass


class HistoryPanel(Widget):
    """Read-only replay of output.jsonl from a background session.

    Plain text only — Rich markup stripped by HeadlessSession writer.
    """

    DEFAULT_CSS = """
    HistoryPanel {
        height: auto;
        max-height: 30;
        overflow-y: auto;
    }
    HistoryPanel #hp-header { color: $text-muted; height: 1; }
    HistoryPanel #hp-log { height: auto; }
    """

    def compose(self) -> ComposeResult:
        yield Static("── session history (plain text) ──", id="hp-header")
        yield RichLog(id="hp-log", markup=False, highlight=False)

    def load(self, lines: list[dict]) -> None:
        try:
            log = self.query_one("#hp-log", RichLog)
        except Exception:
            return
        log.clear()
        for entry in lines:
            text = entry.get("text", "")
            if text:
                log.write(text)
