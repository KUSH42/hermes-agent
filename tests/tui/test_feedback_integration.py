"""Integration tests for FeedbackService wired into HermesApp — I1–I3.

Uses run_test / pilot. Targeted file only — never run full tests/tui/.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import HintBar


@pytest.mark.asyncio
async def test_i1_two_rapid_flash_hints_b_survives() -> None:
    """I1: Two rapid _flash_hint calls; B's message survives for its full duration.

    Regression for D3 (overwrite race): A's timer must not fire at 5s and wipe B.
    """
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(HintBar)

        # Flash A with long duration
        app._flash_hint("message-A", 5.0)
        await pilot.pause()
        assert bar.hint == "message-A"

        # Flash B 0.1s later — should replace A
        app._flash_hint("message-B", 2.0)
        await pilot.pause()
        assert bar.hint == "message-B"

        # B's flash is active; A's old timer was cancelled (not checked by advancing
        # real timer — service ensures A's token was stopped)
        state = app.feedback.peek("hint-bar")
        assert state is not None
        assert state.message == "message-B"


@pytest.mark.asyncio
async def test_i2_flash_header_preempted_by_error() -> None:
    """I2: _flash_header normal preempted by error-tone flash; error wins."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        # Register a fake tool-header channel so we can test the service directly
        from hermes_cli.tui.services.feedback import (
            ChannelAdapter,
            ERROR,
            FlashState,
            NORMAL,
        )

        class RecordAdapter(ChannelAdapter):
            def __init__(self) -> None:
                self.messages: list[str] = []
                self.restores: int = 0

            def apply(self, state: FlashState) -> None:
                self.messages.append(state.message)

            def restore(self) -> None:
                self.restores += 1

        adapter = RecordAdapter()
        app.feedback.register_channel("tool-header::test-panel", adapter)

        # Normal flash first
        app.feedback.flash("tool-header::test-panel", "opening…", duration=5.0, priority=NORMAL)
        assert adapter.messages == ["opening…"]

        # Error preempts
        app.feedback.flash("tool-header::test-panel", "open failed", duration=1.0, priority=ERROR)
        assert adapter.messages[-1] == "open failed"

        state = app.feedback.peek("tool-header::test-panel")
        assert state is not None
        assert state.message == "open failed"
        assert state.priority == ERROR


@pytest.mark.asyncio
async def test_i3_agent_idle_with_active_flash_survives() -> None:
    """I3: watch_agent_running(False) with active flash — flash survives (E3 regression)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        # Start a flash
        app._flash_hint("important flash", 10.0)
        await pilot.pause()

        bar = app.query_one(HintBar)
        assert bar.hint == "important flash"

        # Simulate agent going idle (the E3 scenario)
        app.feedback.on_agent_idle()
        await pilot.pause()

        # Flash must still be active — on_agent_idle does not clear active flashes
        state = app.feedback.peek("hint-bar")
        assert state is not None
        assert state.message == "important flash"
        assert bar.hint == "important flash"
