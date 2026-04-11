"""Tests for HermesInput widget (Input-based)."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.completion_list import VirtualCompletionList
from hermes_cli.tui.completion_overlay import CompletionOverlay
from hermes_cli.tui.history_suggester import HistorySuggester
from hermes_cli.tui.input_widget import HermesInput
from hermes_cli.tui.path_search import PathCandidate, SlashCandidate


@pytest.mark.asyncio
async def test_input_widget_exists():
    """HermesInput is present in the composed layout."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one("#input-area")
        assert isinstance(inp, HermesInput)


@pytest.mark.asyncio
async def test_input_starts_empty():
    """Input value is empty on mount."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert inp.value == ""
        assert inp.content == ""  # bridge property


@pytest.mark.asyncio
async def test_content_property_bridge():
    """content property reads/writes value; cursor_pos bridges cursor_position."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.content = "hello"
        assert inp.value == "hello"
        assert inp.content == "hello"
        inp.cursor_pos = 3
        assert inp.cursor_position == 3
        assert inp.cursor_pos == 3


@pytest.mark.asyncio
async def test_input_disabled_when_agent_running():
    """Input is disabled when agent_running is True."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert not inp.disabled
        app.agent_running = True
        await pilot.pause()
        assert inp.disabled


@pytest.mark.asyncio
async def test_input_clear():
    """clear() resets content and cursor position."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "hello"
        inp.cursor_position = 3
        inp.clear()
        assert inp.value == ""
        assert inp.cursor_position == 0


@pytest.mark.asyncio
async def test_input_insert_text():
    """insert_text inserts at cursor position."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "helo"
        inp.cursor_position = 3
        inp.insert_text("l")
        assert inp.value == "hello"
        assert inp.cursor_position == 4


@pytest.mark.asyncio
async def test_slash_still_works():
    """Typing '/' triggers the completion overlay with slash candidates."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.set_slash_commands(["/help", "/history", "/quit"])
        inp.value = "/he"
        inp.cursor_position = 3
        await pilot.pause()
        # New API: overlay visible, list has candidates
        overlay = app.query_one(CompletionOverlay)
        assert overlay.has_class("--visible")
        clist = app.query_one(VirtualCompletionList)
        displays = [c.display for c in clist.items]
        assert any("help" in d for d in displays)


@pytest.mark.asyncio
async def test_history_navigation():
    """Up/Down keys cycle through history when overlay is hidden."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = ["first", "second", "third"]
        inp.value = "current"

        inp.action_history_prev()
        assert inp.value == "third"
        inp.action_history_prev()
        assert inp.value == "second"
        inp.action_history_next()
        assert inp.value == "third"
        inp.action_history_next()
        assert inp.value == "current"


@pytest.mark.asyncio
async def test_history_navigation_empty_history():
    """Up/down with no history entries is a no-op."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = []
        inp.value = "current"
        inp.action_history_prev()
        assert inp.value == "current"
        inp.action_history_next()
        assert inp.value == "current"


@pytest.mark.asyncio
async def test_history_save_on_submit():
    """action_submit() saves to history before posting Submitted."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = []
        inp.value = "test command"
        inp.action_submit()
        assert "test command" in inp._history
        assert inp.value == ""


@pytest.mark.asyncio
async def test_disabled_input_rejects_keystrokes():
    """Typing into disabled HermesInput has no effect."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.focus()
        app.agent_running = True
        await pilot.pause()
        assert inp.disabled
        await pilot.press("a", "b", "c")
        await pilot.pause()
        assert inp.value == ""


@pytest.mark.asyncio
async def test_input_changed_triggers_autocomplete():
    """watch_value updates completion overlay on slash input."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.set_slash_commands(["/help", "/history"])
        inp.value = "/he"
        inp.cursor_position = 3
        await pilot.pause()
        overlay = app.query_one(CompletionOverlay)
        assert overlay.has_class("--visible")


@pytest.mark.asyncio
async def test_ctrl_a_selects_all():
    """ctrl+a selects entire input value."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "hello world"
        inp.focus()
        await pilot.pause()
        inp.action_select_all()
        await pilot.pause()
        assert inp.selection.start != inp.selection.end


@pytest.mark.asyncio
async def test_shift_arrow_selection():
    """Shift+right selects text; selection range is non-empty."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "hello"
        inp.cursor_position = 0
        inp.focus()
        await pilot.pause()
        await pilot.press("shift+right")
        await pilot.pause()
        assert inp.selection.start != inp.selection.end


@pytest.mark.asyncio
async def test_ctrl_x_cuts_selected_input():
    """ctrl+x removes selected text."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "hello"
        inp.focus()
        await pilot.pause()
        inp.action_select_all()
        await pilot.pause()
        await pilot.press("ctrl+x")
        await pilot.pause()
        assert inp.value == ""


@pytest.mark.asyncio
async def test_ctrl_v_pastes():
    """ctrl+v inserts clipboard content at cursor."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.focus()
        await pilot.pause()
        app.copy_to_clipboard("pasted")
        await pilot.pause()
        await pilot.press("ctrl+v")
        await pilot.pause()
        assert "pasted" in inp.value


# ---------------------------------------------------------------------------
# Phase 4 new tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_path_completion_triggers_walker() -> None:
    """Typing '@' causes PathSearchProvider.search to be called."""
    from unittest.mock import patch
    from hermes_cli.tui.path_search import PathSearchProvider

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        provider = app.query_one(PathSearchProvider)
        search_calls: list = []
        original_search = provider.search

        def capture_search(query, root):
            search_calls.append((query, root))
            # Don't actually run the walk in tests
        provider.search = capture_search  # type: ignore[method-assign]

        inp = app.query_one(HermesInput)
        inp.value = "@src"
        inp.cursor_position = 4
        # Path completions are now debounced (120ms) — wait enough cycles for timer to fire
        for _ in range(5):
            await pilot.pause()

        assert len(search_calls) > 0, "PathSearchProvider.search was not called"
        assert search_calls[0][0] == "src"


@pytest.mark.asyncio
async def test_path_completion_populates_list() -> None:
    """Batch handler updates VirtualCompletionList.items."""
    from hermes_cli.tui.path_search import PathSearchProvider

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "@src"
        inp.cursor_position = 4
        await pilot.pause()

        # Simulate a batch arriving
        from hermes_cli.tui.completion_context import CompletionContext, CompletionTrigger
        inp._current_trigger = CompletionTrigger(
            CompletionContext.PATH_REF, "src", 1
        )
        batch_msg = PathSearchProvider.Batch(
            query="src",
            batch=[
                PathCandidate(display="src/main.py", abs_path="/tmp/src/main.py"),
                PathCandidate(display="src/utils.py", abs_path="/tmp/src/utils.py"),
            ],
            final=True,
        )
        inp.on_path_search_provider_batch(batch_msg)
        await pilot.pause()

        clist = app.query_one(VirtualCompletionList)
        assert len(clist.items) == 2


@pytest.mark.asyncio
async def test_stale_batch_dropped() -> None:
    """Batch with mismatched query is ignored."""
    from hermes_cli.tui.completion_context import CompletionContext, CompletionTrigger
    from hermes_cli.tui.path_search import PathSearchProvider

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)

        # Current trigger is "src" but batch has query "old"
        inp._current_trigger = CompletionTrigger(
            CompletionContext.PATH_REF, "src", 1
        )
        stale_batch = PathSearchProvider.Batch(
            query="old",
            batch=[PathCandidate(display="old.py", abs_path="/tmp/old.py")],
            final=True,
        )
        inp.on_path_search_provider_batch(stale_batch)
        await pilot.pause()

        clist = app.query_one(VirtualCompletionList)
        # Items should remain empty (stale batch discarded)
        assert len(clist.items) == 0


@pytest.mark.asyncio
async def test_tab_accepts_highlighted_slash() -> None:
    """Tab on a SlashCandidate replaces value with '<cmd> '."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.set_slash_commands(["/help", "/history"])
        inp.value = "/he"
        inp.cursor_position = 3
        await pilot.pause()

        # Simulate Tab press
        inp.action_accept_autocomplete()
        await pilot.pause()

        assert inp.value == "/help "
        assert inp.cursor_position == len("/help ")


@pytest.mark.asyncio
async def test_tab_accepts_highlighted_path() -> None:
    """Tab on a PathCandidate inserts @path preserving surrounding text."""
    from hermes_cli.tui.completion_context import CompletionContext, CompletionTrigger

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "@src"
        inp.cursor_position = 4

        # Manually set trigger and list state
        inp._current_trigger = CompletionTrigger(
            CompletionContext.PATH_REF, "src", 1
        )
        clist = app.query_one(VirtualCompletionList)
        clist.items = (PathCandidate(display="src/main.py", abs_path="/tmp/src/main.py"),)
        clist.highlighted = 0
        await pilot.pause()

        inp.action_accept_autocomplete()
        await pilot.pause()

        assert "@src/main.py" in inp.value
        assert not app.query_one(CompletionOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_up_down_delegates_to_list_when_overlay_visible() -> None:
    """Up/Down navigates the completion list when the overlay is visible."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.set_slash_commands(["/help", "/history", "/clear"])
        inp.value = "/"
        inp.cursor_position = 1
        await pilot.pause()

        clist = app.query_one(VirtualCompletionList)
        initial_highlight = clist.highlighted

        inp.action_history_next()  # bound to down
        await pilot.pause()
        assert clist.highlighted != initial_highlight or len(clist.items) == 1


@pytest.mark.asyncio
async def test_enter_submits_as_typed_with_overlay_visible() -> None:
    """/he + overlay visible + Enter → submits '/he', NOT '/help'."""
    submitted_values: list[str] = []

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.set_slash_commands(["/help"])
        inp.value = "/he"
        inp.cursor_position = 3
        await pilot.pause()

        # Confirm overlay is visible
        assert app.query_one(CompletionOverlay).has_class("--visible")

        # Hook the submitted message
        def on_submitted(event):
            submitted_values.append(event.value)
        app.on_hermes_input_submitted = on_submitted

        # Submit
        inp.action_submit()
        await pilot.pause()

        # The value submitted should be the raw typed value, not the suggestion
        assert inp._history[-1] == "/he"
        assert inp.value == ""


@pytest.mark.asyncio
async def test_suggester_wired() -> None:
    """HermesInput.suggester is a HistorySuggester tracking _history."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert isinstance(inp.suggester, HistorySuggester)
        assert inp.suggester._input is inp
