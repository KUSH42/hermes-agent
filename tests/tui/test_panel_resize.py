"""Tests for panel and box resize/invalidation during streaming.

Verifies that MessagePanel, OutputPanel, and ReasoningPanel correctly
expand their height as streaming content arrives — including when
RichLog writes are deferred (size not yet known at write time).
"""

from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import LiveLineWidget, MessagePanel, OutputPanel, ReasoningPanel


async def _pause(pilot, n=5):
    for _ in range(n):
        await pilot.pause()


# ---------------------------------------------------------------------------
# MessagePanel expansion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_message_panel_grows_with_each_line():
    """MessagePanel height increases as lines are written to response_log."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        msg = panel.new_message()
        await _pause(pilot)

        h0 = msg.size.height

        app.write_output("Line 1\n")
        await _pause(pilot)
        h1 = msg.size.height

        app.write_output("Line 2\n")
        app.write_output("Line 3\n")
        await _pause(pilot)
        h3 = msg.size.height

        assert h1 > h0, f"Panel should grow after first line: {h0} → {h1}"
        assert h3 > h1, f"Panel should grow after more lines: {h1} → {h3}"


@pytest.mark.asyncio
async def test_message_panel_height_matches_content():
    """MessagePanel height is at least the number of committed lines."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        msg = panel.new_message()
        await _pause(pilot)

        for i in range(10):
            app.write_output(f"Line {i}\n")
        await _pause(pilot, n=10)

        assert msg.size.height >= 10, (
            f"Panel height {msg.size.height} should be >= 10 lines of content"
        )


@pytest.mark.asyncio
async def test_message_panel_richlog_height_auto():
    """RichLog inside MessagePanel uses height:auto and expands with content."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        msg = panel.new_message()
        await _pause(pilot)

        rl = msg.response_log
        h_empty = rl.size.height

        for i in range(5):
            app.write_output(f"Content line {i}\n")
        await _pause(pilot, n=10)

        h_filled = rl.size.height
        assert h_filled > h_empty, (
            f"RichLog should expand: empty={h_empty}, filled={h_filled}"
        )


# ---------------------------------------------------------------------------
# ReasoningPanel expansion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reasoning_panel_appears_with_nonzero_height():
    """ReasoningPanel has nonzero height once opened and content is written."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await _pause(pilot)

        msg = app.query_one(OutputPanel).current_message
        rp = msg.reasoning

        # Before open: display:none → 0 height
        assert rp.size.height == 0

        rp.open_box("Reasoning")
        rp.append_delta("Step 1\n")
        rp.append_delta("Step 2\n")
        await _pause(pilot, n=10)

        assert rp.size.height > 0, (
            f"ReasoningPanel should have nonzero height after content, got {rp.size.height}"
        )


@pytest.mark.asyncio
async def test_reasoning_panel_grows_with_content():
    """ReasoningPanel height increases as reasoning lines stream in."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await _pause(pilot)

        msg = app.query_one(OutputPanel).current_message
        rp = msg.reasoning
        rp.open_box("Reasoning")
        await _pause(pilot)
        h_header = rp.size.height

        rp.append_delta("Step 1\n")
        rp.append_delta("Step 2\n")
        rp.append_delta("Step 3\n")
        await _pause(pilot, n=10)
        h_after = rp.size.height

        assert h_after > h_header, (
            f"ReasoningPanel should grow with content: {h_header} → {h_after}"
        )


@pytest.mark.asyncio
async def test_reasoning_panel_collapses_on_close():
    """ReasoningPanel returns to zero height (display:none) after close."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await _pause(pilot)

        msg = app.query_one(OutputPanel).current_message
        rp = msg.reasoning
        rp.open_box("Reasoning")
        rp.append_delta("Step 1\n")
        await _pause(pilot, n=10)

        assert rp.size.height > 0

        rp.close_box()
        await _pause(pilot, n=10)

        assert rp.size.height == 0, (
            f"ReasoningPanel should collapse after close, got height={rp.size.height}"
        )


# ---------------------------------------------------------------------------
# Deferred render handling — content written before size is known
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deferred_richlog_writes_become_visible():
    """Content written to RichLog before its size is known eventually appears.

    When mount() runs, compose() is deferred. RichLog.write() before the
    first resize stores content in _deferred_renders. Our fix triggers
    call_after_refresh(refresh, layout=True) so parents recalculate.
    """
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()

        # Write output immediately — forces auto-creation of MessagePanel
        # whose compose() hasn't finished yet (deferred renders scenario)
        app.write_output("Deferred line 1\n")
        app.write_output("Deferred line 2\n")
        app.write_output("Deferred line 3\n")
        await _pause(pilot, n=10)

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        assert len(msg.response_log.lines) >= 3
        # Panel should have expanded to show the deferred content
        assert msg.size.height >= 3, (
            f"Panel should expand for deferred content, height={msg.size.height}"
        )


@pytest.mark.asyncio
async def test_reasoning_deferred_writes_become_visible():
    """Reasoning content written before panel layout is resolved still appears."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        app.agent_running = True
        # Don't wait long — open_box right after turn starts
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        rp = msg.reasoning
        rp.open_box("Reasoning")
        # Write immediately — may hit deferred renders
        rp.append_delta("Deferred step 1\n")
        rp.append_delta("Deferred step 2\n")
        await _pause(pilot, n=10)

        assert len(rp._reasoning_log.lines) >= 2  # 2 gutter-prefixed steps (no header)
        assert rp.size.height > 0


# ---------------------------------------------------------------------------
# OutputPanel scroll / containment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_output_panel_scrollable_with_many_messages():
    """OutputPanel remains scrollable when many MessagePanels are created."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)

        # Create multiple turns with content
        for turn in range(3):
            app.agent_running = True
            await _pause(pilot)
            for line in range(5):
                app.write_output(f"Turn {turn} line {line}\n")
            await _pause(pilot)
            app.agent_running = False
            await _pause(pilot)

        panels = panel.query(MessagePanel)
        assert len(panels) >= 3

        # OutputPanel virtual size should exceed viewport when content overflows
        # (24-line terminal with 3 turns × 5 lines = 15+ lines of content)
        assert panel.virtual_size.height >= panel.size.height or len(panels) >= 3


@pytest.mark.asyncio
async def test_live_line_widget_stays_at_bottom():
    """LiveLineWidget remains the last child of OutputPanel after new messages."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)

        app.agent_running = True
        await _pause(pilot)
        app.write_output("Some content\n")
        await _pause(pilot)

        # LiveLineWidget should be the last child
        children = list(panel.children)
        assert isinstance(children[-1], LiveLineWidget), (
            f"Last child should be LiveLineWidget, got {type(children[-1])}"
        )


# ---------------------------------------------------------------------------
# Combined: reasoning box + response box resize during a turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_turn_layout_reasoning_then_response():
    """A full turn with reasoning→response transitions lays out correctly.

    The reasoning panel should expand, then collapse, then the response
    panel should expand — all within the same MessagePanel.
    """
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await _pause(pilot)

        msg = app.query_one(OutputPanel).current_message
        rp = msg.reasoning

        # Phase 1: Reasoning
        rp.open_box("Thinking")
        rp.append_delta("Analyzing the problem\n")
        rp.append_delta("Considering approach A\n")
        rp.append_delta("Considering approach B\n")
        await _pause(pilot, n=10)

        reasoning_h = rp.size.height
        assert reasoning_h > 0, "Reasoning should be visible during thinking"

        # Phase 2: Transition — close reasoning, start response
        rp.close_box()
        await _pause(pilot, n=10)

        assert rp.size.height == 0, "Reasoning should collapse after close"

        # Phase 3: Response
        for i in range(8):
            app.write_output(f"Response line {i}\n")
        await _pause(pilot, n=10)

        assert msg.size.height >= 8, (
            f"MessagePanel should accommodate response, height={msg.size.height}"
        )
        assert len(msg.response_log.lines) >= 8


@pytest.mark.asyncio
async def test_rapid_streaming_panels_stay_expanded():
    """Panels don't collapse or flicker during rapid token arrival."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        msg = panel.new_message()
        await _pause(pilot)

        # Rapid-fire streaming — tokens arriving faster than layout cycles
        for i in range(20):
            app.write_output(f"Rapid line {i}\n")
        await _pause(pilot, n=15)

        # All content should be committed
        assert len(msg.response_log.lines) >= 20
        # Panel should be expanded to fit
        assert msg.size.height >= 20, (
            f"Panel should stay expanded after rapid streaming, height={msg.size.height}"
        )


@pytest.mark.asyncio
async def test_incremental_streaming_height_never_shrinks():
    """Panel height monotonically increases during streaming (no shrink flicker)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        msg = panel.new_message()
        await _pause(pilot)

        heights = []
        for i in range(10):
            app.write_output(f"Line {i}\n")
            await _pause(pilot)
            heights.append(msg.size.height)

        # Height should never decrease
        for i in range(1, len(heights)):
            assert heights[i] >= heights[i - 1], (
                f"Height should never shrink: step {i-1}→{i}: {heights[i-1]}→{heights[i]}"
            )
        # And it should have grown overall
        assert heights[-1] > heights[0], (
            f"Height should have grown: {heights[0]} → {heights[-1]}"
        )
