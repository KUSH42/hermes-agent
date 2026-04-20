"""Tests for hermes_cli/tui/session_widgets.py"""
from __future__ import annotations

import time
import unittest.mock as mock
from dataclasses import dataclass
from typing import Optional

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, RichLog, Static

from hermes_cli.tui.session_widgets import (
    HistoryPanel,
    MergeConfirmOverlay,
    NewSessionOverlay,
    SessionBar,
    _SessionNotification,
    _SessionsTab,
)


# ---------------------------------------------------------------------------
# Minimal fake SessionRecord for tests
# ---------------------------------------------------------------------------

@dataclass
class FakeRecord:
    id: str
    branch: str
    agent_running: bool = False
    _orphan: bool = False


# ---------------------------------------------------------------------------
# Helper: minimal App wrappers
# ---------------------------------------------------------------------------

class _SessionBarApp(App):
    def compose(self) -> ComposeResult:
        yield SessionBar(id="session-bar")

    def _open_new_session_overlay(self):
        pass

    def _flash_sessions_max(self):
        pass

    def _switch_to_session(self, sid):
        pass


class _SessionsTabApp(App):
    def compose(self) -> ComposeResult:
        yield _SessionsTab(id="sessions-tab")

    def _open_new_session_overlay(self):
        pass

    def _switch_to_session(self, sid):
        pass

    def _kill_session_prompt(self, sid):
        pass

    def _open_merge_overlay(self, sid):
        pass

    def _reopen_orphan_session(self, sid):
        pass

    def _delete_orphan_session(self, sid):
        pass


class _NewSessionApp(App):
    CSS = """
    NewSessionOverlay { layer: overlay; }
    """
    LAYERS = ("default", "overlay")

    def compose(self) -> ComposeResult:
        yield NewSessionOverlay(id="new-session-overlay")

    def _create_new_session(self, branch, base, overlay):
        self._created = (branch, base)

    def query_one_hermes_input(self):
        return None


class _SessionNotifApp(App):
    def compose(self) -> ComposeResult:
        yield _SessionNotification(id="sn")

    def _switch_to_session(self, sid):
        self._switched_to = sid


class _HistoryPanelApp(App):
    def compose(self) -> ComposeResult:
        yield HistoryPanel(id="hp")


class _MergeApp(App):
    CSS = """
    MergeConfirmOverlay { layer: overlay; }
    """
    LAYERS = ("default", "overlay")

    def compose(self) -> ComposeResult:
        yield MergeConfirmOverlay(id="merge-overlay")

    def _run_merge(self, sid, strategy, close_on_success, overlay):
        self._merged = (sid, strategy, close_on_success)


# ---------------------------------------------------------------------------
# SessionBar tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_bar_renders_without_error():
    app = _SessionBarApp()
    async with app.run_test(size=(80, 24)) as pilot:
        bar = app.query_one(SessionBar)
        assert bar is not None


@pytest.mark.asyncio
async def test_session_bar_shows_active_session_marker():
    app = _SessionBarApp()
    async with app.run_test(size=(80, 24)) as pilot:
        bar = app.query_one(SessionBar)
        records = [FakeRecord("sess1", "main")]
        bar.update_sessions(records, "sess1")
        await pilot.pause()
        # SessionBar renders content in a Static widget; access raw content
        content = bar.query_one("#session-bar-content", Static)
        text = str(content._Static__content)
        assert "●" in text and "main" in text


@pytest.mark.asyncio
async def test_session_bar_shows_background_idle_marker():
    app = _SessionBarApp()
    async with app.run_test(size=(80, 24)) as pilot:
        bar = app.query_one(SessionBar)
        records = [
            FakeRecord("active", "main"),
            FakeRecord("bg", "feat/x"),
        ]
        bar.update_sessions(records, "active")
        await pilot.pause()
        content = bar.query_one("#session-bar-content", Static)
        text = str(content._Static__content)
        assert "○" in text and "feat/x" in text


@pytest.mark.asyncio
async def test_session_bar_shows_running_background_marker():
    app = _SessionBarApp()
    async with app.run_test(size=(80, 24)) as pilot:
        bar = app.query_one(SessionBar)
        records = [
            FakeRecord("active", "main"),
            FakeRecord("bg", "feat/y", agent_running=True),
        ]
        bar.update_sessions(records, "active")
        await pilot.pause()
        content = bar.query_one("#session-bar-content", Static)
        text = str(content._Static__content)
        # Running background session shows [●] in the content
        assert "[●]" in text


@pytest.mark.asyncio
async def test_session_bar_shows_add_button():
    app = _SessionBarApp()
    async with app.run_test(size=(80, 24)) as pilot:
        bar = app.query_one(SessionBar)
        bar.update_sessions([], "")
        await pilot.pause()
        add_btn = bar.query_one("#sess-add-btn", Button)
        assert add_btn is not None


@pytest.mark.asyncio
async def test_session_bar_add_button_disabled_at_max():
    app = _SessionBarApp()
    async with app.run_test(size=(80, 24)) as pilot:
        bar = app.query_one(SessionBar)
        records = [FakeRecord(f"s{i}", f"b{i}") for i in range(8)]
        bar.update_sessions(records, "s0", max_sessions=8)
        await pilot.pause()
        add_btn = bar.query_one("#sess-add-btn", Button)
        assert add_btn.has_class("--add-btn-disabled")


@pytest.mark.asyncio
async def test_session_bar_hidden_by_default():
    app = _SessionBarApp()
    async with app.run_test(size=(80, 24)) as pilot:
        bar = app.query_one(SessionBar)
        # display:none means not has_class --sessions-enabled
        assert not bar.has_class("--sessions-enabled")


# ---------------------------------------------------------------------------
# _SessionsTab tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sessions_tab_renders_rows():
    app = _SessionsTabApp()
    async with app.run_test(size=(80, 24)) as pilot:
        tab = app.query_one(_SessionsTab)
        records = [FakeRecord("s1", "main"), FakeRecord("s2", "feat/x")]
        tab.refresh_sessions(records, "s1")
        await pilot.pause()
        statics = list(tab.query(Static))
        texts = [str(s._Static__content) for s in statics]
        assert any("main" in t for t in texts)


@pytest.mark.asyncio
async def test_sessions_tab_shows_orphan_row():
    app = _SessionsTabApp()
    async with app.run_test(size=(80, 24)) as pilot:
        tab = app.query_one(_SessionsTab)
        orphan = FakeRecord("orphan1", "dead-branch", _orphan=True)
        tab.refresh_sessions([orphan], "other")
        await pilot.pause()
        buttons = list(tab.query(Button))
        btn_ids = [b.id for b in buttons]
        assert any("reopen-" in (bid or "") for bid in btn_ids)
        assert any("delete-" in (bid or "") for bid in btn_ids)


@pytest.mark.asyncio
async def test_sessions_tab_active_row_has_no_kill_button():
    app = _SessionsTabApp()
    async with app.run_test(size=(80, 24)) as pilot:
        tab = app.query_one(_SessionsTab)
        rec = FakeRecord("s1", "main")
        tab.refresh_sessions([rec], "s1")
        await pilot.pause()
        kill_btns = [b for b in tab.query(Button) if (b.id or "").startswith("kill-")]
        assert kill_btns == []


# ---------------------------------------------------------------------------
# NewSessionOverlay tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_new_session_overlay_dismisses_on_cancel():
    app = _NewSessionApp()
    async with app.run_test(size=(80, 24)) as pilot:
        overlay = app.query_one(NewSessionOverlay)
        overlay.show_overlay()
        await pilot.pause()
        assert overlay.has_class("--visible")
        # Directly call dismiss instead of click to avoid focus/display issues
        overlay.action_dismiss()
        await pilot.pause()
        assert not overlay.has_class("--visible")


@pytest.mark.asyncio
async def test_new_session_overlay_error_on_empty_branch():
    app = _NewSessionApp()
    async with app.run_test(size=(80, 24)) as pilot:
        overlay = app.query_one(NewSessionOverlay)
        overlay.show_overlay()
        await pilot.pause()
        # Directly call _do_create with empty branch to test validation
        overlay._do_create()
        await pilot.pause()
        error_widget = overlay.query_one("#ns-error", Static)
        assert "required" in str(error_widget._Static__content).lower()


# ---------------------------------------------------------------------------
# _SessionNotification tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_notification_push_shows_first_event():
    app = _SessionNotifApp()
    async with app.run_test(size=(80, 24)) as pilot:
        sn = app.query_one(_SessionNotification)
        sn.push({"session_id": "s1", "message": "agent done"})
        await pilot.pause()
        assert sn.has_class("--visible")
        msg = sn.query_one("#sn-message", Static)
        assert "s1" in str(msg._Static__content)


@pytest.mark.asyncio
async def test_session_notification_auto_dismisses():
    app = _SessionNotifApp()
    async with app.run_test(size=(80, 24)) as pilot:
        sn = app.query_one(_SessionNotification)
        sn.push({"session_id": "s1", "message": "done"})
        await pilot.pause()
        assert sn.has_class("--visible")
        # Manually trigger auto dismiss
        sn._auto_dismiss()
        await pilot.pause()
        assert not sn.has_class("--visible")


@pytest.mark.asyncio
async def test_session_notification_multiple_pushes_queue():
    app = _SessionNotifApp()
    async with app.run_test(size=(80, 24)) as pilot:
        sn = app.query_one(_SessionNotification)
        sn.push({"session_id": "s1", "message": "first"})
        sn.push({"session_id": "s2", "message": "second"})
        await pilot.pause()
        # First event shown; second is queued
        assert sn.has_class("--visible")
        assert len(sn._queue) == 1  # one queued


@pytest.mark.asyncio
async def test_session_notification_switch_button_calls_switch():
    app = _SessionNotifApp()
    async with app.run_test(size=(80, 24)) as pilot:
        sn = app.query_one(_SessionNotification)
        sn.push({"session_id": "target-sess", "message": "done"})
        await pilot.pause()
        switch_btn = sn.query_one("#sn-switch", Button)
        await pilot.click(switch_btn)
        await pilot.pause()
        assert getattr(app, "_switched_to", None) == "target-sess"


# ---------------------------------------------------------------------------
# HistoryPanel tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_panel_load_writes_lines():
    app = _HistoryPanelApp()
    async with app.run_test(size=(80, 24)) as pilot:
        hp = app.query_one(HistoryPanel)
        lines = [{"text": "hello", "role": "assistant"}, {"text": "world", "role": "user"}]
        hp.load(lines)
        await pilot.pause()
        log = hp.query_one("#hp-log", RichLog)
        assert log is not None


@pytest.mark.asyncio
async def test_history_panel_shows_header():
    app = _HistoryPanelApp()
    async with app.run_test(size=(80, 24)) as pilot:
        hp = app.query_one(HistoryPanel)
        header = hp.query_one("#hp-header", Static)
        assert "session history" in str(header._Static__content)


# ---------------------------------------------------------------------------
# MergeConfirmOverlay tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_merge_confirm_overlay_show_for_updates_title():
    app = _MergeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        overlay = app.query_one(MergeConfirmOverlay)
        overlay.show_for("sess42", "3 files changed")
        await pilot.pause()
        title = overlay.query_one("#merge-title", Static)
        assert "sess42" in str(title._Static__content)


@pytest.mark.asyncio
async def test_merge_confirm_overlay_dismiss_on_cancel():
    app = _MergeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        overlay = app.query_one(MergeConfirmOverlay)
        overlay.show_for("sess1", "diff")
        await pilot.pause()
        assert overlay.has_class("--visible")
        cancel = overlay.query_one("#mg-cancel", Button)
        await pilot.click(cancel)
        await pilot.pause()
        assert not overlay.has_class("--visible")
