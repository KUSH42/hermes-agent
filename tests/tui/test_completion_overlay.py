"""Tests for completion overlay visibility, slash-only mode, and coexistence."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.completion_list import VirtualCompletionList
from hermes_cli.tui.completion_overlay import CompletionOverlay
from hermes_cli.tui.input_widget import HermesInput
from hermes_cli.tui.preview_panel import PreviewPanel
from hermes_cli.tui.state import ChoiceOverlayState


# ---------------------------------------------------------------------------
# Phase 4 tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_overlay_hidden_by_default() -> None:
    """CompletionOverlay starts hidden (no --visible class)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(CompletionOverlay)
        assert not overlay.has_class("--visible")
        assert not overlay.display


@pytest.mark.asyncio
async def test_overlay_shows_on_slash() -> None:
    """Typing '/' shows the completion overlay with slash-only mode."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.set_slash_commands(["/help", "/history", "/clear"])
        inp.value = "/h"
        inp.cursor_position = 2
        await pilot.pause()
        overlay = app.query_one(CompletionOverlay)
        assert overlay.has_class("--visible")
        assert overlay.has_class("--slash-only")


@pytest.mark.asyncio
async def test_overlay_slash_only_mode() -> None:
    """SLASH_COMMAND context applies --slash-only (preview hidden, list full width)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.set_slash_commands(["/help"])
        inp.value = "/"
        inp.cursor_position = 1
        await pilot.pause()
        overlay = app.query_one(CompletionOverlay)
        assert overlay.has_class("--slash-only")
        # Preview panel should be display:none via CSS
        preview = app.query_one(PreviewPanel)
        assert not preview.display


@pytest.mark.asyncio
async def test_overlay_hidden_during_choice_overlay() -> None:
    """choice_overlay_active=True hides completion overlay; /h typing does NOT show it."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.set_slash_commands(["/help"])

        # First show completion overlay normally
        inp.value = "/"
        inp.cursor_position = 1
        await pilot.pause()
        overlay = app.query_one(CompletionOverlay)
        assert overlay.has_class("--visible")

        # Now activate a choice overlay
        import queue
        state = ChoiceOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=queue.Queue(),
            question="Allow?",
            choices=["yes", "no"],
            selected=0,
        )
        app.approval_state = state
        await pilot.pause()

        # Completion overlay should be hidden
        assert not overlay.has_class("--visible")

        # Typing /h should NOT re-show it while choice overlay is active
        inp.value = "/h"
        inp.cursor_position = 2
        await pilot.pause()
        assert not overlay.has_class("--visible")

        # Cleanup
        state.response_queue.put("no")
        app.approval_state = None


@pytest.mark.asyncio
async def test_overlay_hides_on_empty_input() -> None:
    """Clearing input hides the overlay."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.set_slash_commands(["/help"])
        inp.value = "/"
        inp.cursor_position = 1
        await pilot.pause()
        assert app.query_one(CompletionOverlay).has_class("--visible")

        inp.value = ""
        inp.cursor_position = 0
        await pilot.pause()
        assert not app.query_one(CompletionOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_escape_dismisses_completion_only() -> None:
    """Escape with overlay visible dismisses popup, doesn't interrupt agent."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.set_slash_commands(["/help"])
        inp.value = "/"
        inp.cursor_position = 1
        await pilot.pause()
        assert app.query_one(CompletionOverlay).has_class("--visible")

        await pilot.press("escape")
        await pilot.pause()
        assert not app.query_one(CompletionOverlay).has_class("--visible")
        # Agent interrupt flag should not have been set
        assert not app.agent_running
