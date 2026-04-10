"""Tests for modal overlay widgets — Step 4.

Tests: ClarifyWidget, ApprovalWidget, SudoWidget, SecretWidget
with CountdownMixin, typed state, and response queues.
"""

import queue
import time
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.state import ChoiceOverlayState, SecretOverlayState
from hermes_cli.tui.widgets import (
    ApprovalWidget,
    ClarifyWidget,
    SecretWidget,
    SudoWidget,
)


# ---------------------------------------------------------------------------
# ClarifyWidget
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clarify_hidden_by_default():
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        w = app.query_one(ClarifyWidget)
        assert not w.display


@pytest.mark.asyncio
async def test_clarify_visible_when_state_set():
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        state = ChoiceOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=queue.Queue(),
            question="Which tool?",
            choices=["a", "b"],
        )
        app.clarify_state = state
        await pilot.pause()
        w = app.query_one(ClarifyWidget)
        assert w.display


@pytest.mark.asyncio
async def test_clarify_hides_when_state_cleared():
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        state = ChoiceOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=queue.Queue(),
            question="Q?",
            choices=["x"],
        )
        app.clarify_state = state
        await pilot.pause()
        app.clarify_state = None
        await pilot.pause()
        w = app.query_one(ClarifyWidget)
        assert not w.display


@pytest.mark.asyncio
async def test_clarify_response_queue():
    """Selecting a choice puts it on the response_queue."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        rq = queue.Queue()
        state = ChoiceOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=rq,
            question="Pick",
            choices=["yes", "no"],
            selected=0,
        )
        app.clarify_state = state
        await pilot.pause()
        # Simulate Enter key — should put selected choice on queue
        await pilot.press("enter")
        await pilot.pause()
        result = rq.get(timeout=2)
        assert result == "yes"


@pytest.mark.asyncio
async def test_clarify_escape_dismisses():
    """Escape puts None on the response_queue."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        rq = queue.Queue()
        state = ChoiceOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=rq,
            question="Q?",
            choices=["a"],
        )
        app.clarify_state = state
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        result = rq.get(timeout=2)
        assert result is None


@pytest.mark.asyncio
async def test_clarify_timeout_auto_resolves():
    """Expired deadline auto-resolves with None."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        rq = queue.Queue()
        state = ChoiceOverlayState(
            deadline=time.monotonic() - 1,  # already expired
            response_queue=rq,
            question="Q?",
            choices=["a"],
        )
        app.clarify_state = state
        await pilot.pause()
        # Wait for countdown tick (1s interval)
        import asyncio
        await asyncio.sleep(1.2)
        await pilot.pause()
        result = rq.get(timeout=2)
        assert result is None


# ---------------------------------------------------------------------------
# ApprovalWidget
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approval_hidden_by_default():
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        w = app.query_one(ApprovalWidget)
        assert not w.display


@pytest.mark.asyncio
async def test_approval_visible_when_state_set():
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        state = ChoiceOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=queue.Queue(),
            question="Allow rm -rf?",
            choices=["once", "deny"],
        )
        app.approval_state = state
        await pilot.pause()
        w = app.query_one(ApprovalWidget)
        assert w.display


@pytest.mark.asyncio
async def test_approval_timeout_auto_denies():
    """ApprovalWidget timeout response is 'deny'."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        rq = queue.Queue()
        state = ChoiceOverlayState(
            deadline=time.monotonic() - 1,  # already expired
            response_queue=rq,
            question="Allow?",
            choices=["once", "deny"],
        )
        app.approval_state = state
        await pilot.pause()
        import asyncio
        await asyncio.sleep(1.2)
        await pilot.pause()
        result = rq.get(timeout=2)
        assert result == "deny"


@pytest.mark.asyncio
async def test_approval_up_down_navigation():
    """Up/Down keys change selected choice."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        rq = queue.Queue()
        state = ChoiceOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=rq,
            question="Allow?",
            choices=["once", "session", "deny"],
            selected=0,
        )
        app.approval_state = state
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        assert state.selected == 1
        await pilot.press("down")
        await pilot.pause()
        assert state.selected == 2
        await pilot.press("up")
        await pilot.pause()
        assert state.selected == 1


@pytest.mark.asyncio
async def test_approval_enter_submits_selected():
    """Enter submits the selected choice."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        rq = queue.Queue()
        state = ChoiceOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=rq,
            question="Allow?",
            choices=["once", "deny"],
            selected=1,
        )
        app.approval_state = state
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        result = rq.get(timeout=2)
        assert result == "deny"


# ---------------------------------------------------------------------------
# SudoWidget
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sudo_hidden_by_default():
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        w = app.query_one(SudoWidget)
        assert not w.display


@pytest.mark.asyncio
async def test_sudo_visible_when_state_set():
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        state = SecretOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=queue.Queue(),
            prompt="Enter sudo password:",
        )
        app.sudo_state = state
        await pilot.pause()
        w = app.query_one(SudoWidget)
        assert w.display


@pytest.mark.asyncio
async def test_sudo_timeout_resolves_none():
    """SudoWidget timeout puts None on queue."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        rq = queue.Queue()
        state = SecretOverlayState(
            deadline=time.monotonic() - 1,
            response_queue=rq,
            prompt="Password:",
        )
        app.sudo_state = state
        await pilot.pause()
        import asyncio
        await asyncio.sleep(1.2)
        await pilot.pause()
        result = rq.get(timeout=2)
        assert result is None


# ---------------------------------------------------------------------------
# SecretWidget
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_secret_hidden_by_default():
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        w = app.query_one(SecretWidget)
        assert not w.display


@pytest.mark.asyncio
async def test_secret_visible_when_state_set():
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        state = SecretOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=queue.Queue(),
            prompt="Enter API key:",
        )
        app.secret_state = state
        await pilot.pause()
        w = app.query_one(SecretWidget)
        assert w.display


@pytest.mark.asyncio
async def test_secret_timeout_resolves_none():
    """SecretWidget timeout puts None on queue."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        rq = queue.Queue()
        state = SecretOverlayState(
            deadline=time.monotonic() - 1,
            response_queue=rq,
            prompt="API Key:",
        )
        app.secret_state = state
        await pilot.pause()
        import asyncio
        await asyncio.sleep(1.2)
        await pilot.pause()
        result = rq.get(timeout=2)
        assert result is None
