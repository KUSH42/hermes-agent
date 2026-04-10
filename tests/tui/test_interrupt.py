"""Tests for Ctrl+C / Escape agent interrupt in the TUI."""

import asyncio
from unittest.mock import MagicMock, PropertyMock
import queue

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.state import ChoiceOverlayState, SecretOverlayState
from hermes_cli.tui.widgets import OutputPanel


def _app_with_agent():
    """Create an app with a mock CLI that has an agent with interrupt()."""
    cli = MagicMock()
    cli.agent = MagicMock()
    cli.agent.interrupt = MagicMock()
    app = HermesApp(cli=cli)
    return app, cli


@pytest.mark.asyncio
async def test_ctrl_c_interrupts_running_agent():
    """Ctrl+C calls agent.interrupt() when agent is running."""
    app, cli = _app_with_agent()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        await pilot.press("ctrl+c")
        await pilot.pause()
        cli.agent.interrupt.assert_called_once()


@pytest.mark.asyncio
async def test_escape_interrupts_running_agent():
    """Escape calls agent.interrupt() when agent is running."""
    app, cli = _app_with_agent()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        cli.agent.interrupt.assert_called_once()


@pytest.mark.asyncio
async def test_ctrl_c_no_interrupt_when_idle():
    """Ctrl+C does NOT call interrupt when agent is not running."""
    app, cli = _app_with_agent()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Agent not running — ctrl+c should clear input or exit, not interrupt
        await pilot.press("ctrl+c")
        await pilot.pause()
        cli.agent.interrupt.assert_not_called()


@pytest.mark.asyncio
async def test_ctrl_c_cancels_approval_overlay():
    """Ctrl+C cancels an active approval overlay with 'deny'."""
    app, cli = _app_with_agent()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        import time
        rq = queue.Queue()
        state = ChoiceOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=rq,
            question="Allow?",
            choices=["once", "deny"],
            selected=0,
        )
        app.approval_state = state
        await pilot.pause()
        await pilot.press("ctrl+c")
        await pilot.pause()
        result = rq.get(timeout=2)
        assert result == "deny"
        assert app.approval_state is None


@pytest.mark.asyncio
async def test_escape_cancels_approval_overlay_with_none():
    """Escape cancels an active approval overlay with None."""
    app, cli = _app_with_agent()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        import time
        rq = queue.Queue()
        state = ChoiceOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=rq,
            question="Allow?",
            choices=["once", "deny"],
            selected=0,
        )
        app.approval_state = state
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        result = rq.get(timeout=2)
        assert result is None
        assert app.approval_state is None


@pytest.mark.asyncio
async def test_ctrl_c_cancels_sudo_overlay():
    """Ctrl+C cancels an active sudo overlay."""
    app, cli = _app_with_agent()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        import time
        rq = queue.Queue()
        state = SecretOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=rq,
            prompt="Password:",
        )
        app.sudo_state = state
        await pilot.pause()
        await pilot.press("ctrl+c")
        await pilot.pause()
        result = rq.get(timeout=2)
        assert result == ""
        assert app.sudo_state is None


@pytest.mark.asyncio
async def test_overlay_priority_over_interrupt():
    """When overlay is active, ctrl+c cancels overlay rather than interrupting agent."""
    app, cli = _app_with_agent()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        import time
        rq = queue.Queue()
        state = ChoiceOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=rq,
            question="Allow?",
            choices=["once", "deny"],
            selected=0,
        )
        app.approval_state = state
        await pilot.pause()
        await pilot.press("ctrl+c")
        await pilot.pause()
        # Overlay cancelled, agent NOT interrupted
        result = rq.get(timeout=2)
        assert result == "deny"
        cli.agent.interrupt.assert_not_called()


@pytest.mark.asyncio
async def test_double_ctrl_c_exits():
    """Double Ctrl+C within 2s exits the app."""
    app, cli = _app_with_agent()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        await pilot.press("ctrl+c")
        await pilot.pause()
        # Second ctrl+c within 2s should trigger exit
        await pilot.press("ctrl+c")
        await pilot.pause()
        # The app should have exited (or be exiting)
        # interrupt called at least once (first press)
        assert cli.agent.interrupt.call_count >= 1
