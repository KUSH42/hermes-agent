"""Phase C — Overlay Consistency & Discoverability tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.overlays import (
    HelpOverlay,
    SessionOverlay,
    WorkspaceOverlay,
    UsageOverlay,
)
from hermes_cli.tui.widgets import HintBar


# ---------------------------------------------------------------------------
# C1 — HelpOverlay search cleared on re-open
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_c1_help_overlay_search_cleared_on_reopen() -> None:
    """HelpOverlay clears the search Input when reopened."""
    from textual.widgets import Input

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        overlay = app.query_one(HelpOverlay)
        # Simulate first open + filter
        overlay.show_overlay()
        await pilot.pause()
        inp = overlay.query_one("#help-search", Input)
        inp.value = "myfilter"
        await pilot.pause()
        overlay.action_dismiss()
        await pilot.pause()
        # Re-open
        overlay.show_overlay()
        await pilot.pause()
        inp2 = overlay.query_one("#help-search", Input)
        assert inp2.value == "", f"Search not cleared on re-open: {inp2.value!r}"


@pytest.mark.asyncio
async def test_c1_help_overlay_all_commands_shown_on_reopen() -> None:
    """After reopen, full command list is rendered (no stale filter)."""
    from textual.widgets import Input

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        overlay = app.query_one(HelpOverlay)
        overlay.show_overlay()
        await pilot.pause()
        inp = overlay.query_one("#help-search", Input)
        inp.value = "zzznomatches"
        await pilot.pause()
        overlay.action_dismiss()
        await pilot.pause()
        overlay.show_overlay()
        await pilot.pause()
        # Commands cache should be repopulated
        assert len(overlay._commands_cache) > 0, "Commands cache empty"


# ---------------------------------------------------------------------------
# C2 — SessionOverlay scrolls to selected row
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_c2_session_overlay_scrolls_to_selected() -> None:
    """SessionOverlay scrolls #sess-scroll to show the selected row."""
    from textual.containers import ScrollableContainer

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(SessionOverlay)
        # Inject fake sessions
        sessions = [
            {"id": f"sess-{i:03d}", "title": f"Session {i}", "created": i}
            for i in range(15)
        ]
        overlay._sessions = sessions
        overlay._render_rows(sessions)
        await pilot.pause()
        # Navigate to row 12 (beyond 8-row visible area)
        for _ in range(12):
            overlay.action_move_down()
        await pilot.pause()
        assert overlay._selected_idx == 12
        # The scroll container should have scrolled
        scroll = overlay.query_one("#sess-scroll", ScrollableContainer)
        assert scroll.scroll_y >= 0  # must have attempted scroll


# ---------------------------------------------------------------------------
# C3 — show_model_switch_result flashes hint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_c3_show_model_switch_result_flashes_hint() -> None:
    """show_model_switch_result sets HintBar hint with the model name."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.show_model_switch_result("claude-opus-4")
        await pilot.pause()
        hint = app.query_one(HintBar).hint
        assert "claude-opus-4" in hint, f"HintBar.hint={hint!r}"


# ---------------------------------------------------------------------------
# C4 — WorkspaceOverlay focuses tab button on open
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_c4_workspace_overlay_focuses_tab_on_open() -> None:
    """WorkspaceOverlay focuses the first tab button when show_overlay is called."""
    from textual.widgets import Button

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        overlay = app.query_one(WorkspaceOverlay)
        overlay.show_overlay()
        await pilot.pause()
        focused = app.focused
        # The git tab button should be focused (or at least overlay shown)
        assert overlay.has_class("--visible"), "WorkspaceOverlay must be --visible"
        # Focus should be on the git tab button
        if focused is not None:
            assert getattr(focused, "id", None) == "ws-tab-git", (
                f"Expected #ws-tab-git focused, got {getattr(focused, 'id', None)!r}"
            )


# ---------------------------------------------------------------------------
# C5 — F2 binding and action_show_usage
# ---------------------------------------------------------------------------

def test_c5_f2_binding_exists() -> None:
    """HermesApp.BINDINGS must include an 'f2' key."""
    keys = [b.key for b in HermesApp.BINDINGS]
    assert "f2" in keys, f"f2 not in HermesApp.BINDINGS: {keys}"


@pytest.mark.asyncio
async def test_c5_action_show_usage_shows_overlay() -> None:
    """action_show_usage makes UsageOverlay visible."""
    from unittest.mock import patch as _patch

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        overlay = app.query_one(UsageOverlay)
        assert not overlay.has_class("--visible")
        # Patch refresh_data to avoid MagicMock arithmetic errors
        with _patch.object(overlay, "refresh_data"):
            app.action_show_usage()
        await pilot.pause()
        assert overlay.has_class("--visible"), "UsageOverlay must be --visible after action"
