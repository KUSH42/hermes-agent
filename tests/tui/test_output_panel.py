"""Tests for OutputPanel and LiveLineWidget — Step 1 output pipeline."""

import asyncio
import sys
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import LiveLineWidget, OutputPanel


@pytest.mark.asyncio
async def test_output_panel_composes_children():
    """OutputPanel yields a RichLog and a LiveLineWidget."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        assert panel is not None
        live = panel.live_line
        assert isinstance(live, LiveLineWidget)


@pytest.mark.asyncio
async def test_cprint_routes_to_queue():
    """Text written via write_output reaches the output panel."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.write_output("Hello world\n")
        # Give consumer time to process
        await pilot.pause()
        await pilot.pause()
        log = app.query_one("#output-log")
        # RichLog should have at least one line
        assert len(log.lines) >= 1


@pytest.mark.asyncio
async def test_queue_sentinel_flushes_live_line():
    """None sentinel flushes the live line buffer and consumer stays alive."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Write partial line (no newline) then flush
        app.write_output("partial")
        await pilot.pause()
        app.flush_output()
        await pilot.pause()
        await pilot.pause()
        # After flush, the live line buffer should be empty
        live = app.query_one(LiveLineWidget)
        assert live._buf == ""


@pytest.mark.asyncio
async def test_live_line_commits_complete_lines():
    """LiveLineWidget commits complete lines to RichLog."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.write_output("line1\nline2\npartial")
        await pilot.pause()
        await pilot.pause()
        log = app.query_one("#output-log")
        assert len(log.lines) >= 2
        live = app.query_one(LiveLineWidget)
        assert live._buf == "partial"


@pytest.mark.asyncio
async def test_queue_backpressure_does_not_crash():
    """QueueFull is caught gracefully when queue is saturated."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Fill the queue to capacity
        for i in range(4096):
            app.write_output(f"chunk{i}\n")
        # One more should be silently dropped (not raise)
        app.write_output("overflow\n")
        await pilot.pause()


def test_cprint_falls_through_when_no_app():
    """_cprint falls through to stdout when _hermes_app is None."""
    # Import the module-level function
    import cli
    original_app = cli._hermes_app
    try:
        cli._hermes_app = None
        # Should not raise — falls through to prompt_toolkit renderer
        # We just verify it doesn't crash
        with patch.object(cli, '_pt_print') as mock_print:
            cli._cprint("test output")
            mock_print.assert_called_once()
    finally:
        cli._hermes_app = original_app
