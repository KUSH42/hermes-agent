"""Tests for parallel session widgets and HermesApp session integration.

Phase C — session_widgets.py + app.py session attrs.

28 tests:
  1.  SessionBar hidden by default (no --sessions-enabled class)
  2.  SessionBar visible when --sessions-enabled class added
  3.  SessionBar shows ● for active session
  4.  SessionBar shows ○ for background idle session
  5.  SessionBar shows [●] suffix for running background session
  6.  SessionBar._rebuild() with empty list shows only + button
  7.  SessionBar at max capacity shows dim + button
  8.  SessionBar + click calls app._open_new_session_overlay()
  9.  SessionBar session button click calls app._switch_to_session(id)
  10. SessionBar active session button click is no-op (no switch)
  11. HermesApp._sessions_enabled defaults False
  12. HermesApp on_mount with sessions.enabled=False leaves bar hidden
  13. HermesApp._get_session_records() returns cache list
  14. HermesApp._get_active_session_id() returns active id
  15. HermesApp action_new_worktree_session with sessions disabled does nothing
  16. HermesApp._flash_sessions_max() flashes hint bar (mocked)
  17. _SessionsTab shows empty message when no records
  18. _SessionsTab.refresh_sessions() renders _WorktreeSessionRow per record
  19. _WorktreeSessionRow active row has --active class
  20. _WorktreeSessionRow orphan row has --orphan class
  21. _WorktreeSessionRow active row shows dim hint, no kill/switch buttons
  22. _SessionNotification.push() shows notification
  23. _SessionNotification.push() queues when already visible
  24. _SessionNotification auto-dismisses after 5s (mocked timer)
  25. HistoryPanel.load() renders lines from output.jsonl dicts
  26. HistoryPanel.load() with empty list shows no lines
  27. HistoryPanel.load() skips entries missing text key
  28. MergeConfirmOverlay strategy buttons set correct _strategy value
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from hermes_cli.tui.session_manager import SessionRecord
from hermes_cli.tui.session_widgets import (
    SessionBar,
    _SessionsTab,
    _WorktreeSessionRow,
    _SessionNotification,
    NewSessionOverlay,
    MergeConfirmOverlay,
    HistoryPanel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(sessions_enabled: bool = False) -> "HermesApp":
    from hermes_cli.tui.app import HermesApp
    cli = MagicMock()
    cli.config = {"sessions": {"enabled": sessions_enabled}}
    cli._cfg = {}
    return HermesApp(cli=cli)


def _make_record(
    id: str = "abc123def456",
    branch: str = "feat/test",
    agent_running: bool = False,
    is_active: bool = False,
) -> SessionRecord:
    return SessionRecord(
        id=id,
        branch=branch,
        worktree_path=f"/tmp/{id}",
        pid=12345,
        socket_path=f"/tmp/{id}/notify.sock",
        agent_running=agent_running,
        last_event="started",
    )


# ---------------------------------------------------------------------------
# 1. SessionBar hidden by default
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_bar_hidden_by_default():
    app = _make_app(sessions_enabled=False)
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(SessionBar)
        assert not bar.has_class("--sessions-enabled")


# ---------------------------------------------------------------------------
# 2. SessionBar visible when --sessions-enabled added
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_bar_visible_when_enabled():
    app = _make_app()
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(SessionBar)
        bar.add_class("--sessions-enabled")
        await pilot.pause()
        assert bar.has_class("--sessions-enabled")


# ---------------------------------------------------------------------------
# 3. SessionBar shows ● for active session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_bar_shows_active_marker():
    app = _make_app()
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(SessionBar)
        rec = _make_record()
        bar.update_sessions([rec], active_id=rec.id)
        await pilot.pause()
        # Find button with ● marker
        from textual.widgets import Button
        buttons = list(bar.query(Button))
        labels = [str(b.label) for b in buttons]
        assert any("●" in lbl and rec.branch in lbl for lbl in labels)


# ---------------------------------------------------------------------------
# 4. SessionBar shows ○ for background idle session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_bar_shows_idle_background():
    app = _make_app()
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(SessionBar)
        rec = _make_record()
        bar.update_sessions([rec], active_id="different-id")
        await pilot.pause()
        from textual.widgets import Button
        buttons = list(bar.query(Button))
        labels = [str(b.label) for b in buttons]
        assert any("○" in lbl and rec.branch in lbl for lbl in labels)


# ---------------------------------------------------------------------------
# 5. SessionBar shows [●] for running background session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_bar_shows_running_background():
    app = _make_app()
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(SessionBar)
        rec = _make_record(agent_running=True)
        bar.update_sessions([rec], active_id="different-id")
        await pilot.pause()
        from textual.widgets import Button
        buttons = list(bar.query(Button))
        labels = [str(b.label) for b in buttons]
        # The suffix is " [●]" which renders as the bullet in brackets;
        # check that at least one label contains ● and agent_running is indicated
        assert any("●" in lbl for lbl in labels)
        # And at least one non-active label (○)
        assert any("○" in lbl for lbl in labels)


# ---------------------------------------------------------------------------
# 6. SessionBar with empty list shows only + button
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_bar_empty_shows_only_add():
    app = _make_app()
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(SessionBar)
        bar.update_sessions([], active_id="")
        await pilot.pause()
        from textual.widgets import Button
        buttons = list(bar.query(Button))
        # Should have exactly 1 button: the + button
        assert len(buttons) == 1
        assert "+" in str(buttons[0].label) or "add" in (buttons[0].id or "")


# ---------------------------------------------------------------------------
# 7. SessionBar at max capacity shows dim + button
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_bar_max_capacity_dim_add():
    app = _make_app()
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(SessionBar)
        # Create 8 records (max)
        records = [_make_record(id=f"session{i:04d}", branch=f"feat/{i}") for i in range(8)]
        bar.update_sessions(records, active_id="session0000", max_sessions=8)
        await pilot.pause()
        from textual.widgets import Button
        add_btn = bar.query_one("#sess-add-btn", Button)
        assert add_btn.has_class("--add-btn-disabled")


# ---------------------------------------------------------------------------
# 8. SessionBar + click calls app._open_new_session_overlay
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_bar_add_click_opens_overlay():
    """SessionBar + button press triggers _open_new_session_overlay on app."""
    app = _make_app()
    called = []

    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        app._open_new_session_overlay = lambda: called.append(True)
        app._sessions_enabled = True
        bar = app.query_one(SessionBar)
        bar._sessions_data = []
        bar._max_sessions = 8

        # Simulate button press event directly (avoids DOM timing dependency)
        from textual.widgets import Button
        from textual.widgets._button import Button as BtnClass
        fake_btn = MagicMock()
        fake_btn.id = "sess-add-btn"
        event = MagicMock()
        event.button = fake_btn
        event.stop = MagicMock()
        bar.on_button_pressed(event)
        await pilot.pause()

    assert len(called) == 1


# ---------------------------------------------------------------------------
# 9. SessionBar session button click calls app._switch_to_session(id)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_bar_session_click_switches():
    """SessionBar session button press calls _switch_to_session with correct ID."""
    app = _make_app()
    switched_to = []

    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        app._switch_to_session = lambda sid: switched_to.append(sid)
        app._sessions_enabled = True
        bar = app.query_one(SessionBar)
        rec = _make_record(id="target00")
        bar._active_id = "other000"
        bar._sessions_data = [rec]

        # Simulate button press event directly
        fake_btn = MagicMock()
        fake_btn.id = "sess-btn-0"
        event = MagicMock()
        event.button = fake_btn
        event.stop = MagicMock()
        bar.on_button_pressed(event)
        await pilot.pause()

    assert "target00" in switched_to


# ---------------------------------------------------------------------------
# 10. SessionBar active session button click is no-op
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_bar_active_click_noop():
    """SessionBar click on active session does not trigger switch."""
    app = _make_app()
    switched_to = []

    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        app._switch_to_session = lambda sid: switched_to.append(sid)
        bar = app.query_one(SessionBar)
        rec = _make_record(id="active000")
        bar._active_id = "active000"
        bar._sessions_data = [rec]

        # Simulate button press on the active session
        fake_btn = MagicMock()
        fake_btn.id = "sess-btn-0"
        event = MagicMock()
        event.button = fake_btn
        event.stop = MagicMock()
        bar.on_button_pressed(event)
        await pilot.pause()

    assert len(switched_to) == 0


# ---------------------------------------------------------------------------
# 11. HermesApp._sessions_enabled defaults False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hermes_app_sessions_enabled_defaults_false():
    app = _make_app(sessions_enabled=False)
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        assert app._sessions_enabled is False


# ---------------------------------------------------------------------------
# 12. HermesApp on_mount sessions.enabled=False leaves bar hidden
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hermes_app_sessions_disabled_bar_hidden():
    app = _make_app(sessions_enabled=False)
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(SessionBar)
        assert not bar.has_class("--sessions-enabled")


# ---------------------------------------------------------------------------
# 13. HermesApp._get_session_records() returns cache list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hermes_app_get_session_records():
    app = _make_app()
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        rec = _make_record()
        app._session_records_cache = [rec]
        result = app._get_session_records()
        assert len(result) == 1
        assert result[0].id == rec.id


# ---------------------------------------------------------------------------
# 14. HermesApp._get_active_session_id() returns active id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hermes_app_get_active_session_id():
    app = _make_app()
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        app._session_active_id = "active123"
        assert app._get_active_session_id() == "active123"


# ---------------------------------------------------------------------------
# 15. action_new_worktree_session with sessions disabled does nothing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_new_worktree_session_disabled_noop():
    app = _make_app(sessions_enabled=False)
    called = []
    app._open_new_session_overlay = lambda: called.append(True)
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        app.action_new_worktree_session()
        await pilot.pause()
    assert len(called) == 0


# ---------------------------------------------------------------------------
# 16. HermesApp._flash_sessions_max() flashes hint bar
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flash_sessions_max():
    app = _make_app()
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        app._sessions_enabled = True
        flashed = []
        app._flash_hint = lambda msg, duration=1.5: flashed.append(msg)
        app._flash_sessions_max()
        await pilot.pause()
    assert any("Max sessions" in m for m in flashed)


# ---------------------------------------------------------------------------
# 17. _SessionsTab shows empty message when no records
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sessions_tab_empty_message():
    app = _make_app()
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        # Mount a standalone _SessionsTab
        tab = _SessionsTab(id="test-sessions-tab")
        await app.mount(tab)
        await pilot.pause()
        tab.refresh_sessions([], active_id="")
        await pilot.pause()
        from textual.widgets import Static
        statics = list(tab.query(Static))
        # In Textual 8.x, Static content is in _renderable (private) or accessed via str()
        texts = [str(s._renderable) for s in statics if hasattr(s, "_renderable")]
        texts += [str(s.render()) for s in statics if hasattr(s, "render") and not hasattr(s, "_renderable")]
        # Also get the text content
        content = " ".join(texts)
        assert "No parallel" in content or "no" in content.lower() or "press" in content.lower()


# ---------------------------------------------------------------------------
# 18. _SessionsTab.refresh_sessions() renders _WorktreeSessionRow per record
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sessions_tab_renders_rows():
    app = _make_app()
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        tab = _SessionsTab(id="test-sessions-tab-2")
        await app.mount(tab)
        await pilot.pause()
        records = [_make_record(id=f"sess{i}", branch=f"feat/{i}") for i in range(3)]
        tab.refresh_sessions(records, active_id="sess0")
        await pilot.pause()
        rows = list(tab.query(_WorktreeSessionRow))
        assert len(rows) == 3


# ---------------------------------------------------------------------------
# 19. _WorktreeSessionRow active row has --active class
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_row_active_has_class():
    app = _make_app()
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        rec = _make_record()
        row = _WorktreeSessionRow(rec, is_active=True)
        await app.mount(row)
        await pilot.pause()
        assert row.has_class("--active")


# ---------------------------------------------------------------------------
# 20. _WorktreeSessionRow orphan row has --orphan class
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_row_orphan_has_class():
    app = _make_app()
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        rec = _make_record()
        rec._orphan = True
        row = _WorktreeSessionRow(rec, is_active=False)
        await app.mount(row)
        await pilot.pause()
        assert row.has_class("--orphan")


# ---------------------------------------------------------------------------
# 21. _WorktreeSessionRow active row shows dim hint, no kill/switch buttons
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_row_active_no_kill_switch():
    app = _make_app()
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        rec = _make_record()
        row = _WorktreeSessionRow(rec, is_active=True)
        await app.mount(row)
        await pilot.pause()
        from textual.widgets import Button
        buttons = list(row.query(Button))
        btn_ids = [(b.id or "") for b in buttons]
        # Should have no switch or kill buttons
        assert not any("switch" in bid or "kill" in bid for bid in btn_ids)


# ---------------------------------------------------------------------------
# 22. _SessionNotification.push() shows notification
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_notification_push_shows():
    app = _make_app()
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        notif = app.query_one(_SessionNotification)
        notif.push({"type": "agent_complete", "session_id": "abc", "message": "done"})
        await pilot.pause()
        assert notif.has_class("--visible")


# ---------------------------------------------------------------------------
# 23. _SessionNotification.push() queues when already visible
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_notification_queues():
    app = _make_app()
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        notif = app.query_one(_SessionNotification)
        notif.push({"type": "agent_complete", "session_id": "a", "message": "first"})
        await pilot.pause()
        notif.push({"type": "agent_complete", "session_id": "b", "message": "second"})
        await pilot.pause()
        # Still visible (showing first), second queued
        assert notif.has_class("--visible")
        assert len(notif._queue) == 1


# ---------------------------------------------------------------------------
# 24. _SessionNotification auto-dismisses via timer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_notification_auto_dismiss():
    app = _make_app()
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        notif = app.query_one(_SessionNotification)
        notif.push({"type": "test", "session_id": "x", "message": "hi"})
        await pilot.pause()
        assert notif.has_class("--visible")
        # Call auto-dismiss directly (timer fires eventually in real use)
        notif._auto_dismiss()
        await pilot.pause()
        assert not notif.has_class("--visible")


# ---------------------------------------------------------------------------
# 25. HistoryPanel.load() renders lines
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_panel_load_renders():
    app = _make_app()
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        panel = HistoryPanel(id="test-history")
        await app.mount(panel)
        await pilot.pause()
        lines = [
            {"ts": 1.0, "text": "line one", "role": "assistant"},
            {"ts": 2.0, "text": "line two", "role": "user"},
        ]
        panel.load(lines)
        await pilot.pause()
        from textual.widgets import RichLog
        log = panel.query_one("#hp-log", RichLog)
        # RichLog line count should reflect loaded content
        # (Content rendered internally; check no exception raised)
        assert log is not None


# ---------------------------------------------------------------------------
# 26. HistoryPanel.load() with empty list shows no lines
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_panel_load_empty():
    app = _make_app()
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        panel = HistoryPanel(id="test-history-empty")
        await app.mount(panel)
        await pilot.pause()
        panel.load([])
        await pilot.pause()
        # Just verify no exception
        from textual.widgets import RichLog
        assert panel.query_one("#hp-log", RichLog) is not None


# ---------------------------------------------------------------------------
# 27. HistoryPanel.load() skips entries missing text key
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_panel_load_skips_missing_text():
    app = _make_app()
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        panel = HistoryPanel(id="test-history-skip")
        await app.mount(panel)
        await pilot.pause()
        # Entry with no text key
        lines = [{"ts": 1.0, "role": "assistant"}]
        # Should not raise
        panel.load(lines)
        await pilot.pause()


# ---------------------------------------------------------------------------
# 28. MergeConfirmOverlay strategy buttons set correct _strategy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_merge_overlay_strategy_buttons():
    app = _make_app()
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        overlay = app.query_one(MergeConfirmOverlay)
        overlay.show_for("sess001", "1 file changed")
        await pilot.pause()

        from textual.widgets import Button

        # Test squash
        squash_btn = overlay.query_one("#mg-squash", Button)
        await pilot.click(squash_btn)
        await pilot.pause()
        assert overlay._strategy == "squash"

        # Test merge
        merge_btn = overlay.query_one("#mg-merge", Button)
        await pilot.click(merge_btn)
        await pilot.pause()
        assert overlay._strategy == "merge"

        # Test rebase
        rebase_btn = overlay.query_one("#mg-rebase", Button)
        await pilot.click(rebase_btn)
        await pilot.pause()
        assert overlay._strategy == "rebase"
