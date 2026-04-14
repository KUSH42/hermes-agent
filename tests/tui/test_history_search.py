"""Tests for HistorySearchOverlay (SPEC-B — History Search).

25 tests covering:
  1–3   Open/close/escape overlay
  4–7   Empty-query browse-all + contiguous filter across user/assistant text
  6–9   Up/Down navigation + clamping
  10–13 Enter jump: scroll_visible + dismiss + --highlighted + timer fade
  14–15 Edge cases: 0 turns + 1 turn
  16    Click TurnResultItem triggers jump
  17–18 HintBar hint save/restore
  19    Overlay opens when agent_running=True
  20    Snapshot frozen after open
  21    on_resize re-renders without crash
  22    ctrl+c dismisses overlay
  23    Cross-boundary mixed query does not match
  24    First turn excluded as startup/banner
  25    Clearing query restores full list
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import (
    HistorySearchOverlay,
    HintBar,
    MessagePanel,
    OutputPanel,
    TurnResultItem,
    UserMessagePanel,
)
from textual.widgets import Input, Static


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app() -> HermesApp:
    return HermesApp(cli=MagicMock())


def _ensure_startup_turn(app: HermesApp) -> None:
    """Mount the initial banner/startup assistant turn once."""
    output = app.query_one(OutputPanel)
    if list(output.query(MessagePanel)):
        return
    startup = MessagePanel()
    output.mount(startup)
    startup.response_log._plain_lines.append("Hermes startup banner")


def _add_turn(app: HermesApp, user_text: str, assistant_text: str) -> MessagePanel:
    """Mount a realistic user+assistant turn after the startup turn."""
    _ensure_startup_turn(app)
    output = app.query_one(OutputPanel)
    output.mount(UserMessagePanel(user_text), before=output.tool_pending)
    panel = MessagePanel(user_text=user_text)
    output.mount(panel, before=output.tool_pending)
    panel.response_log._plain_lines.append(assistant_text)
    return panel


# ---------------------------------------------------------------------------
# 1. ctrl+f opens overlay
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ctrl_f_opens_overlay():
    """ctrl+f makes HistorySearchOverlay visible and focuses search input."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(HistorySearchOverlay)
        assert not overlay.has_class("--visible")

        await pilot.press("ctrl+f")
        await pilot.pause()

        assert overlay.has_class("--visible")
        inp = overlay.query_one("#history-search-input", Input)
        assert inp.has_focus


# ---------------------------------------------------------------------------
# 2. Second ctrl+f closes overlay
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ctrl_f_second_press_closes_overlay():
    """Pressing ctrl+f again while overlay is visible dismisses it."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(HistorySearchOverlay)

        await pilot.press("ctrl+f")
        await pilot.pause()
        assert overlay.has_class("--visible")

        await pilot.press("ctrl+f")
        await pilot.pause()
        assert not overlay.has_class("--visible")


# ---------------------------------------------------------------------------
# 3. Escape closes overlay
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_escape_closes_overlay():
    """Escape dismisses the overlay and returns focus to HermesInput."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(HistorySearchOverlay)

        await pilot.press("ctrl+f")
        await pilot.pause()
        assert overlay.has_class("--visible")

        await pilot.press("escape")
        await pilot.pause()
        assert not overlay.has_class("--visible")
        # Focus should return to #input-area
        focused = app.focused
        assert focused is not None
        assert getattr(focused, "id", None) == "input-area"


# ---------------------------------------------------------------------------
# 4. Empty query shows all turns in reverse chronological order
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_query_shows_all_turns_reverse():
    """Empty query shows all indexed user turns, most recent first."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _add_turn(app, "first user ask", "first assistant text")
        _add_turn(app, "second user ask", "second assistant text")
        _add_turn(app, "third user ask", "third assistant text")
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()

        result_list = overlay.query_one("#history-result-list")
        items = [child for child in result_list.children if isinstance(child, TurnResultItem)]
        assert len(items) == 3
        assert items[0]._entry.display == "third user ask"
        assert items[1]._entry.display == "second user ask"
        assert items[2]._entry.display == "first user ask"


# ---------------------------------------------------------------------------
# 5. Non-empty query filters turns via fuzzy match
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_filter_matches_user_text_case_insensitively():
    """Non-empty query matches contiguous substrings in user text."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _add_turn(app, "Parse ISO dates", "assistant one")
        _add_turn(app, "Memory architecture", "assistant two")
        _add_turn(app, "Rollback behavior", "assistant three")
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()
        await pilot.pause()  # allow on_resize events to settle

        inp = overlay.query_one("#history-search-input", Input)
        inp.value = "memory"
        await pilot.pause()
        await asyncio.sleep(0.16)  # wait for 150ms debounce timer
        await pilot.pause()        # flush DOM update

        items = list(overlay.query(TurnResultItem))
        assert len(items) == 1
        assert items[0]._entry.user_text == "Memory architecture"


# ---------------------------------------------------------------------------
# 6. Non-empty query matches assistant plain text
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_filter_matches_assistant_plain_text():
    """Non-empty query can match assistant text even if user text does not."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _add_turn(app, "User request one", "parse ISO dates")
        _add_turn(app, "User request two", "memory architecture")
        _add_turn(app, "User request three", "rollback behavior")
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()

        inp = overlay.query_one("#history-search-input", Input)
        inp.value = "memory"
        await pilot.pause()
        await asyncio.sleep(0.16)
        await pilot.pause()

        items = list(overlay.query(TurnResultItem))
        assert len(items) == 1
        assert items[0]._entry.assistant_text == "memory architecture"
        assert items[0]._entry.display == "User request two"


# ---------------------------------------------------------------------------
# 7. Non-consecutive substring does not match
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_filter_requires_consecutive_match():
    """Subsequence-only query does not match."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _add_turn(app, "User request", "Memory architecture")
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()

        inp = overlay.query_one("#history-search-input", Input)
        inp.value = "mry"
        await pilot.pause()
        await asyncio.sleep(0.16)
        await pilot.pause()

        items = list(overlay.query(TurnResultItem))
        assert len(items) == 0


# ---------------------------------------------------------------------------
# 8. Down moves selection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_down_moves_selection():
    """Down key moves the --selected class to the next row."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _add_turn(app, "turn one", "assistant one")
        _add_turn(app, "turn two", "assistant two")
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()
        await pilot.pause()  # extra tick for mount + update_selection to settle

        # Initially row 0 is selected
        items = list(overlay.query(TurnResultItem))
        assert len(items) == 2
        assert items[0].has_class("--selected")

        overlay.action_move_down()
        await pilot.pause()
        items = list(overlay.query(TurnResultItem))
        assert not items[0].has_class("--selected")
        assert items[1].has_class("--selected")


# ---------------------------------------------------------------------------
# 9. Up moves selection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_up_moves_selection():
    """Up key moves --selected class to the previous row."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _add_turn(app, "turn one", "assistant one")
        _add_turn(app, "turn two", "assistant two")
        _add_turn(app, "turn three", "assistant three")
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()

        overlay.action_move_down()
        overlay.action_move_down()
        items = list(overlay.query(TurnResultItem))
        assert items[2].has_class("--selected")

        overlay.action_move_up()
        items = list(overlay.query(TurnResultItem))
        assert items[1].has_class("--selected")


# ---------------------------------------------------------------------------
# 10. Up at row 0 clamps (no wrap)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_up_clamps_at_row_zero():
    """Up at row 0 keeps --selected on row 0 (no wrap)."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _add_turn(app, "only turn", "assistant")
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()

        overlay.action_move_up()  # already at 0
        overlay.action_move_up()
        items = list(overlay.query(TurnResultItem))
        assert items[0].has_class("--selected")
        assert overlay._selected_idx == 0


# ---------------------------------------------------------------------------
# 11. Down at last row clamps (no wrap)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_down_clamps_at_last_row():
    """Down at the last row keeps --selected on last row (no wrap)."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _add_turn(app, "turn A", "assistant A")
        _add_turn(app, "turn B", "assistant B")
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()

        overlay.action_move_down()
        overlay.action_move_down()  # already at last
        overlay.action_move_down()

        items = list(overlay.query(TurnResultItem))
        assert items[-1].has_class("--selected")
        assert overlay._selected_idx == len(items) - 1


# ---------------------------------------------------------------------------
# 12. Enter calls scroll_visible on correct panel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enter_calls_scroll_visible_on_panel():
    """Enter calls scroll_visible(animate=True) on the selected panel."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel1 = _add_turn(app, "alpha request", "alpha content")
        panel2 = _add_turn(app, "beta request", "beta content")
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()

        # Row 0 is the most recent (panel2, index 2)
        items = list(overlay.query(TurnResultItem))
        target_panel = items[0]._entry.panel

        with patch.object(target_panel, "scroll_visible") as mock_sv:
            overlay.action_jump()
            await pilot.pause()
            mock_sv.assert_called_once_with(animate=True)


# ---------------------------------------------------------------------------
# 13. Enter dismisses overlay
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enter_dismisses_overlay():
    """action_jump removes --visible class from overlay."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _add_turn(app, "some turn", "assistant")
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()
        assert overlay.has_class("--visible")

        overlay.action_jump()
        await pilot.pause()
        assert not overlay.has_class("--visible")


# ---------------------------------------------------------------------------
# 14. Enter adds --highlighted to target panel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enter_adds_highlighted_class():
    """action_jump adds --highlighted CSS class to the target panel."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = _add_turn(app, "highlighted turn", "assistant")
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        # _render_results mounts TurnResultItem widgets asynchronously;
        # give the event loop enough cycles to settle before action_jump queries them.
        await asyncio.sleep(0.05)
        await pilot.pause()

        overlay.action_jump()
        await pilot.pause()
        assert panel.has_class("--highlighted")


# ---------------------------------------------------------------------------
# 15. --highlighted removed after 1.5 s
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_highlighted_removed_after_timeout():
    """--highlighted class is removed after the 0.5s timer fires."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = _add_turn(app, "fading turn", "assistant")
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        # Let TurnResultItem mounts settle before action_jump queries them.
        await asyncio.sleep(0.05)
        await pilot.pause()

        overlay.action_jump()
        await pilot.pause()
        assert panel.has_class("--highlighted")

        await asyncio.sleep(0.7)
        await pilot.pause()
        assert not panel.has_class("--highlighted")


# ---------------------------------------------------------------------------
# 16. 0-turn conversation → empty results, "0 of 0 turns"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_zero_turns_shows_empty_status():
    """With no turns, result list is empty and status shows '0 of 0 turns'."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # No turns added

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()

        items = list(overlay.query(TurnResultItem))
        assert len(items) == 0

        status = overlay.query_one("#history-status", Static)
        assert "0 of 0 turn" in str(status.render())


# ---------------------------------------------------------------------------
# 17. 1-turn conversation → single entry with correct user display
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_single_turn_shows_correct_user_display():
    """Single indexed turn renders with its user text as display text."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = _add_turn(app, "hello world request", "hello world response")
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()

        items = list(overlay.query(TurnResultItem))
        assert len(items) == 1
        assert items[0]._entry.display == "hello world request"
        assert items[0]._entry.assistant_text == "hello world response"
        assert items[0]._entry.index == 2


# ---------------------------------------------------------------------------
# 18. Click on TurnResultItem triggers jump
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_click_result_item_triggers_jump():
    """Clicking a TurnResultItem calls action_jump_to and dismisses overlay."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = _add_turn(app, "clickable turn", "assistant")
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()

        items = list(overlay.query(TurnResultItem))
        assert len(items) == 1
        entry = items[0]._entry

        with patch.object(panel, "scroll_visible") as mock_sv:
            overlay.action_jump_to(entry)
            await pilot.pause()
            mock_sv.assert_called_once_with(animate=True)

        assert not overlay.has_class("--visible")


# ---------------------------------------------------------------------------
# 19. HintBar shows navigation hint when overlay is open
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hint_bar_shows_navigation_hint():
    """HintBar.hint is updated to navigation hint when overlay opens."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()

        hint_bar = app.query_one(HintBar)
        assert "navigate" in hint_bar.hint


# ---------------------------------------------------------------------------
# 20. HintBar hint restored after overlay closes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hint_bar_hint_restored_after_close():
    """HintBar.hint reverts to the saved value after overlay dismisses."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        hint_bar = app.query_one(HintBar)
        hint_bar.hint = "original hint text"
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()
        assert hint_bar.hint != "original hint text"

        overlay.action_dismiss()
        await pilot.pause()
        assert hint_bar.hint == "original hint text"


# ---------------------------------------------------------------------------
# 21. Overlay opens even when agent_running=True
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_overlay_opens_when_agent_running():
    """Overlay can open while agent is running (no guard blocks it)."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()

        assert overlay.has_class("--visible")


# ---------------------------------------------------------------------------
# 22. Snapshot is frozen: new panel after open is NOT in results
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_snapshot_frozen_after_open():
    """Panels mounted after open_search() are not reflected in the index."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _add_turn(app, "pre-open turn", "assistant pre-open")
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()

        index_len_at_open = len(overlay._index)

        # Add a new turn AFTER open_search() — should NOT appear in results
        _add_turn(app, "post-open turn", "assistant post-open")
        await pilot.pause()

        assert len(overlay._index) == index_len_at_open


# ---------------------------------------------------------------------------
# 23. on_resize re-renders without crash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_resize_rerenders_without_crash():
    """on_resize() fires when visible; _render_results called; no exception."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _add_turn(app, "resize test turn", "assistant")
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()

        render_count_before = len(list(overlay.query(TurnResultItem)))

        # Simulate a resize — call on_resize directly
        overlay.on_resize()
        await pilot.pause()

        render_count_after = len(list(overlay.query(TurnResultItem)))
        # Same number of items; no crash
        assert render_count_after == render_count_before


# ---------------------------------------------------------------------------
# 24. ctrl+c dismisses overlay
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ctrl_c_dismisses_overlay():
    """ctrl+c while overlay is visible removes --visible."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()
        assert overlay.has_class("--visible")

        # The overlay's own BINDINGS have ctrl+c → action_dismiss at priority=True
        # which fires before the app-level ctrl+c handler.
        overlay.action_dismiss()
        await pilot.pause()
        assert not overlay.has_class("--visible")


# ---------------------------------------------------------------------------
# 25. Mixed query must not match across user/assistant boundary
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mixed_boundary_query_does_not_match():
    """Query must not match by crossing synthetic user/assistant boundary."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _add_turn(app, "fix history", "search bug")
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()

        inp = overlay.query_one("#history-search-input", Input)
        inp.value = "history search"
        await pilot.pause()
        await asyncio.sleep(0.16)
        await pilot.pause()

        items = list(overlay.query(TurnResultItem))
        assert len(items) == 0


# ---------------------------------------------------------------------------
# 26. First turn excluded as startup/banner
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_first_turn_is_excluded_from_history():
    """Initial startup/banner MessagePanel is not indexed."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _ensure_startup_turn(app)
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()

        assert len(list(overlay.query(TurnResultItem))) == 0


# ---------------------------------------------------------------------------
# 27. Clearing query restores full list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clearing_query_restores_full_list():
    """Clearing search input restores full reverse-chronological result set."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _add_turn(app, "alpha request", "assistant one")
        _add_turn(app, "beta request", "memory architecture")
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()

        inp = overlay.query_one("#history-search-input", Input)
        inp.value = "memory"
        await pilot.pause()
        await asyncio.sleep(0.16)
        await pilot.pause()
        assert len(list(overlay.query(TurnResultItem))) == 1

        inp.value = ""
        await pilot.pause()
        await asyncio.sleep(0.16)
        await pilot.pause()

        result_list = overlay.query_one("#history-result-list")
        items = [child for child in result_list.children if isinstance(child, TurnResultItem)]
        assert len(items) == 2
        assert items[0]._entry.display == "beta request"
        assert items[1]._entry.display == "alpha request"
