"""Tests for input widget focus and chevron prompt rendering.

The chevron is now a separate Static('❯ ') sibling in the #input-row
Horizontal container, not rendered inside HermesInput (which extends
Textual's Input and does not use render()).
"""

from unittest.mock import MagicMock

import pytest
from textual.widgets import Static

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.input_widget import HermesInput


@pytest.mark.asyncio
async def test_input_focused_on_startup():
    """Input widget receives focus automatically when the app mounts."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert inp.has_focus, "Input should be focused on startup"


@pytest.mark.asyncio
async def test_chevron_exists_as_sibling():
    """The ❯ chevron is a Static sibling in the #input-row container."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        chevron = app.query_one("#input-chevron", Static)
        assert chevron is not None


@pytest.mark.asyncio
async def test_chevron_visible_when_empty():
    """The ❯ chevron Static is visible even when input is empty."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert inp.content == ""
        chevron = app.query_one("#input-chevron", Static)
        assert chevron.display


@pytest.mark.asyncio
async def test_chevron_visible_when_disabled():
    """The ❯ chevron remains visible when input is disabled."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        chevron = app.query_one("#input-chevron", Static)
        assert chevron.display


@pytest.mark.asyncio
async def test_spinner_overlay_exists():
    """Spinner overlay Static widget exists in #input-row."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        spinner = app.query_one("#spinner-overlay", Static)
        assert spinner is not None
        # Hidden by default
        assert not spinner.display


@pytest.mark.asyncio
async def test_no_placeholder_when_idle():
    """No placeholder text shown when idle."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert inp.placeholder == ""
