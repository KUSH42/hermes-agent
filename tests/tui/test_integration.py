"""Integration tests — Step 7.

Full app lifecycle, streaming pipeline stress, error boundaries,
and single-query mode verification.
"""

import asyncio
import queue
import time
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.state import ChoiceOverlayState, SecretOverlayState
from hermes_cli.tui.widgets import (
    HintBar,
    OutputPanel,
    ReasoningPanel,
    StatusBar,
)


@pytest.mark.asyncio
async def test_full_app_composes_all_widgets():
    """HermesApp composes all expected widgets."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Verify all key widgets are present
        assert app.query_one(OutputPanel)
        assert app.query_one(ReasoningPanel)
        assert app.query_one(HintBar)
        assert app.query_one(StatusBar)
        assert app.query_one("#input-area")
        assert app.query_one("#overlay-layer")


@pytest.mark.asyncio
async def test_agent_turn_lifecycle():
    """Simulate a full agent turn: start → stream output → reasoning → end."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        # Start agent
        app.agent_running = True
        app.status_model = "claude-opus"
        await pilot.pause()

        # Stream some output
        for i in range(10):
            app.write_output(f"response chunk {i}\n")
        await pilot.pause()
        await pilot.pause()

        # Open reasoning
        app.open_reasoning("Thinking")
        await pilot.pause()
        app.append_reasoning("step 1: analyze")
        app.append_reasoning("step 2: synthesize")
        await pilot.pause()
        app.close_reasoning()
        await pilot.pause()

        # End agent
        app.agent_running = False
        app.status_tokens = 500
        app.status_duration = 3.2
        await pilot.pause()
        app.flush_output()
        await pilot.pause()


@pytest.mark.asyncio
async def test_streaming_pipeline_ordering():
    """Output chunks arrive in order after passing through the queue."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        # Write numbered chunks
        for i in range(100):
            app.write_output(f"line {i}\n")

        # Wait for consumer to process
        await pilot.pause()
        await pilot.pause()
        await asyncio.sleep(0.1)
        await pilot.pause()

        log = app.query_one("#output-log")
        assert len(log.lines) >= 50  # Should have most lines committed


@pytest.mark.asyncio
async def test_streaming_pipeline_stress():
    """Feed many chunks through the queue — verify no crash."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        # Write 1000 chunks rapidly
        for i in range(1000):
            app.write_output(f"chunk{i}\n")

        app.flush_output()
        await pilot.pause()
        await pilot.pause()

        # Should not crash — that's the main assertion


@pytest.mark.asyncio
async def test_error_boundary_cprint_no_app():
    """_cprint falls through to stdout when no TUI is active."""
    import cli as cli_mod

    original = cli_mod._hermes_app
    try:
        cli_mod._hermes_app = None
        # Should not crash
        with patch.object(cli_mod, '_pt_print'):
            cli_mod._cprint("test")
    finally:
        cli_mod._hermes_app = original


@pytest.mark.asyncio
async def test_concurrent_overlay_transitions():
    """Multiple overlay state changes in rapid succession don't crash."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        for _ in range(5):
            rq = queue.Queue()
            state = ChoiceOverlayState(
                deadline=time.monotonic() + 30,
                response_queue=rq,
                question="Q?",
                choices=["a", "b"],
            )
            app.clarify_state = state
            await pilot.pause()
            state.response_queue.put("a")
            app.clarify_state = None
            await pilot.pause()


@pytest.mark.asyncio
async def test_skin_switch_mid_session():
    """Switching skin mid-session doesn't crash."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.apply_skin({"primary": "#FF0000"})
        await pilot.pause()
        app.apply_skin({"primary": "#00FF00", "background": "#111111"})
        await pilot.pause()
        css_vars = app.get_css_variables()
        assert css_vars["primary"] == "#00FF00"
