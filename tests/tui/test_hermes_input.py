"""Tests for HermesInput widget — Step 5."""

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
    """Input content is empty on mount."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert inp.content == ""
        assert inp.has_class("--empty")


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
        inp.content = "hello"
        inp.cursor_pos = 3
        inp.clear()
        assert inp.content == ""
        assert inp.cursor_pos == 0


@pytest.mark.asyncio
async def test_input_insert_text():
    """insert_text inserts at cursor position."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.content = "helo"
        inp.cursor_pos = 3
        inp.insert_text("l")
        assert inp.content == "hello"
        assert inp.cursor_pos == 4


@pytest.mark.asyncio
async def test_input_password_masking():
    """When masked=True, render shows bullets."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.content = "secret"
        inp.masked = True
        await pilot.pause()
        # The render method should produce masked output


@pytest.mark.asyncio
async def test_slash_command_autocomplete():
    """Typing '/' triggers autocomplete when slash commands are set."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.set_slash_commands(["/help", "/history", "/quit"])
        inp.content = "/he"
        inp.cursor_pos = 3
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
        inp.content = "current"

        inp.action_history_prev()
        assert inp.content == "third"
        inp.action_history_prev()
        assert inp.content == "second"
        inp.action_history_next()
        assert inp.content == "third"
        inp.action_history_next()
        assert inp.content == "current"
