"""Tests for HermesInput widget (Input-based)."""

from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.input_widget import HermesInput


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
async def test_slash_command_autocomplete():
    """Typing '/' triggers autocomplete when slash commands are set."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.set_slash_commands(["/help", "/history", "/quit"])
        inp.value = "/he"
        inp.cursor_position = 3
        await pilot.pause()
        assert inp.has_class("--autocomplete-visible")
        assert "/help" in inp._autocomplete_items


@pytest.mark.asyncio
async def test_history_navigation():
    """Up/Down keys cycle through history."""
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
        inp._history = []  # ensure empty
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
        # Try typing — value should remain empty
        await pilot.press("a", "b", "c")
        await pilot.pause()
        assert inp.value == ""


@pytest.mark.asyncio
async def test_input_changed_triggers_autocomplete():
    """watch_value updates autocomplete popup."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.set_slash_commands(["/help", "/history"])
        # Setting value should trigger watch_value → _update_autocomplete
        inp.value = "/he"
        await pilot.pause()
        assert inp._autocomplete_items == ["/help"]


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
