"""Tests for ReasoningPanel widget — Step 2."""

from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import ReasoningPanel, _safe_widget_call


@pytest.mark.asyncio
async def test_reasoning_panel_hidden_by_default():
    """ReasoningPanel is hidden (display: none) on mount."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(ReasoningPanel)
        assert not panel.has_class("visible")


@pytest.mark.asyncio
async def test_open_box_makes_visible():
    """open_box adds the 'visible' CSS class."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(ReasoningPanel)
        panel.open_box("Reasoning")
        await pilot.pause()
        assert panel.has_class("visible")


@pytest.mark.asyncio
async def test_append_delta_writes_to_log():
    """append_delta writes text to the reasoning RichLog."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(ReasoningPanel)
        panel.open_box("Thinking")
        panel.append_delta("step 1")
        panel.append_delta("step 2")
        await pilot.pause()
        log = app.query_one("#reasoning-log")
        # Header + 2 deltas = at least 3 lines
        assert len(log.lines) >= 3


@pytest.mark.asyncio
async def test_close_box_hides_and_clears():
    """close_box removes visible class and clears the log."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(ReasoningPanel)
        panel.open_box("Reasoning")
        panel.append_delta("some content")
        await pilot.pause()
        panel.close_box()
        await pilot.pause()
        assert not panel.has_class("visible")
        log = app.query_one("#reasoning-log")
        assert len(log.lines) == 0


@pytest.mark.asyncio
async def test_safe_widget_call_swallows_no_matches():
    """_safe_widget_call does not raise when widget is not found."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Call with a type that doesn't exist — should not raise
        class FakeWidget:
            pass
        _safe_widget_call(app, FakeWidget, "some_method")


@pytest.mark.asyncio
async def test_app_reasoning_helpers():
    """HermesApp convenience methods for reasoning panel work correctly."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.open_reasoning("Test")
        await pilot.pause()
        panel = app.query_one(ReasoningPanel)
        assert panel.has_class("visible")
        app.append_reasoning("thinking...")
        await pilot.pause()
        app.close_reasoning()
        await pilot.pause()
        assert not panel.has_class("visible")
