"""Tests for hermes_cli/tui/history_suggester.py — native Suggester ghost text."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.history_suggester import HistorySuggester
from hermes_cli.tui.input_widget import HermesInput


# ---------------------------------------------------------------------------
# Phase 5 tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prefix_match_from_history() -> None:
    """history=['git status'], value='git s' → suggestion='git status'."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = ["git status"]
        result = await inp.suggester.get_suggestion("git s")
        assert result == "git status"


@pytest.mark.asyncio
async def test_empty_value_returns_none() -> None:
    """get_suggestion('') returns None."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = ["git status"]
        result = await inp.suggester.get_suggestion("")
        assert result is None


@pytest.mark.asyncio
async def test_self_match_excluded() -> None:
    """Exact-match entry is never returned as its own suggestion."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = ["git status"]
        result = await inp.suggester.get_suggestion("git status")
        assert result is None


@pytest.mark.asyncio
async def test_newest_wins() -> None:
    """history=['git status', 'git show'], value='git s' → 'git show' (most recent)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = ["git status", "git show"]
        result = await inp.suggester.get_suggestion("git s")
        assert result == "git show"


@pytest.mark.asyncio
async def test_suggester_wired() -> None:
    """HermesInput.suggester is a HistorySuggester tracking _history."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert isinstance(inp.suggester, HistorySuggester)
        assert inp.suggester._input is inp


@pytest.mark.asyncio
async def test_no_history_returns_none() -> None:
    """Empty history always returns None."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = []
        result = await inp.suggester.get_suggestion("git")
        assert result is None


@pytest.mark.asyncio
async def test_suggestion_not_saved_on_submit() -> None:
    """Submitting 'git s' saves 'git s', not the suggested 'git status'."""
    cli = MagicMock()
    cli._pending_input = MagicMock()
    cli._pending_input.put = MagicMock()

    app = HermesApp(cli=cli)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = ["git status"]

        inp.value = "git s"
        inp.cursor_position = len(inp.value)
        inp.action_submit()
        await pilot.pause()

        # Last saved history entry should be "git s", not "git status"
        assert inp._history[-1] == "git s"
