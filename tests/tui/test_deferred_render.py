"""Tests for deferred render handling in the TUI output pipeline.

Verifies that content written to RichLog widgets before their size is known
(deferred renders) is correctly displayed after layout, and that panels
expand to show the content.
"""

from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import MessagePanel, OutputPanel, ReasoningPanel


@pytest.mark.asyncio
async def test_response_log_available_before_compose():
    """MessagePanel.response_log is accessible immediately after construction."""
    panel = MessagePanel()
    # Should not raise — the RichLog is created in __init__
    rl = panel.response_log
    assert rl is not None
    assert rl.id.startswith("response-")


@pytest.mark.asyncio
async def test_reasoning_panel_available_before_compose():
    """MessagePanel.reasoning is accessible immediately after construction."""
    panel = MessagePanel()
    rp = panel.reasoning
    assert rp is not None
    assert isinstance(rp, ReasoningPanel)


@pytest.mark.asyncio
async def test_write_output_reaches_richlog_without_pre_existing_panel():
    """Content written via write_output creates a MessagePanel and populates it.

    Regression test: previously, new_message() mounted a panel whose compose()
    hadn't run yet, so query_one(RichLog) raised NoMatches and content was lost.
    """
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        # No MessagePanel exists yet — write_output should create one
        output = app.query_one(OutputPanel)
        assert output.current_message is None

        app.write_output("Hello\n")
        app.write_output("World\n")
        for _ in range(5):
            await pilot.pause()

        msg = output.current_message
        assert msg is not None
        assert len(msg.response_log.lines) == 2


@pytest.mark.asyncio
async def test_message_panel_expands_after_deferred_writes():
    """MessagePanel height grows when deferred RichLog content is rendered."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.write_output("Line 1\n")
        app.write_output("Line 2\n")
        app.write_output("Line 3\n")
        for _ in range(5):
            await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        assert msg.size.height >= 3, (
            f"MessagePanel should expand to fit content, got height={msg.size.height}"
        )


@pytest.mark.asyncio
async def test_reasoning_panel_content_visible_after_open():
    """ReasoningPanel content is visible after open_box, not just the border."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        # Create a turn
        app.agent_running = True
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None

        # Open reasoning and write content
        msg.reasoning.open_box("Reasoning")
        msg.reasoning.append_delta("Step 1\n")
        msg.reasoning.append_delta("Step 2\n")
        for _ in range(5):
            await pilot.pause()

        # Reasoning log should have 3 lines: header + 2 steps
        assert len(msg.reasoning._reasoning_log.lines) == 3
        # The reasoning panel should have non-zero height
        assert msg.reasoning.size.height > 0, (
            "ReasoningPanel should expand to show content"
        )


@pytest.mark.asyncio
async def test_new_turn_output_not_lost():
    """Content sent immediately after agent_running=True is not lost.

    Regression test: agent_running watcher creates a new MessagePanel, and
    output arriving right after must land in the new panel's RichLog.
    """
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        # Start a turn (creates new MessagePanel)
        app.agent_running = True
        await pilot.pause()

        # Immediately write output (simulates agent producing output)
        app.write_output("Initializing...\n")
        app.write_output("Response line\n")
        for _ in range(5):
            await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        assert len(msg.response_log.lines) >= 2, (
            f"Expected at least 2 lines, got {len(msg.response_log.lines)}"
        )


@pytest.mark.asyncio
async def test_flush_live_with_deferred_renders():
    """flush_live works correctly even when RichLog has deferred renders."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        # Write a partial line (no newline) then flush
        app.write_output("partial content")
        await pilot.pause()
        app.flush_output()
        for _ in range(5):
            await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        live = app.query_one(OutputPanel).live_line
        assert live._buf == ""
        assert len(msg.response_log.lines) >= 1
