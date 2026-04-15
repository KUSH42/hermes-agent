"""Streaming tool output integration tests.

Covers the full open/append/close API, concurrent blocks, interrupt cleanup,
collapse/expand behavior, and mount order invariants.

Run with:
    pytest -o "addopts=" tests/tui/test_tool_output_integration.py -v
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.tool_blocks import StreamingToolBlock, ToolHeader
from hermes_cli.tui.widgets import (
    CopyableRichLog,
    HintBar,
    LiveLineWidget,
    OutputPanel,
    ThinkingWidget,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app() -> HermesApp:
    return HermesApp(cli=MagicMock(), clipboard_available=True, xclip_cmd=None)


async def _open_block(app: HermesApp, pilot, tool_id: str, label: str) -> StreamingToolBlock:
    """Open a streaming block and return it."""
    app.open_streaming_tool_block(tool_id, label)
    await pilot.pause()
    output = app.query_one(OutputPanel)
    blocks = list(output.query(StreamingToolBlock))
    return blocks[-1]


# ---------------------------------------------------------------------------
# Open creates block in OutputPanel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_open_creates_block_in_output_panel():
    """open_streaming_tool_block mounts a StreamingToolBlock into OutputPanel."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()

        app.open_streaming_tool_block("id1", "ls -la")
        await pilot.pause()

        output = app.query_one(OutputPanel)
        blocks = list(output.query(StreamingToolBlock))
        assert len(blocks) >= 1, "Expected at least one StreamingToolBlock in OutputPanel"

        block = blocks[-1]
        # Label is stored on the block
        assert block._label == "ls -la", (
            f"Expected block label 'ls -la', got: {block._label!r}"
        )

        app.agent_running = False
        await pilot.pause()


# ---------------------------------------------------------------------------
# Active dict tracking
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_open_stores_in_active_dict():
    """After open, the block is tracked in _active_streaming_blocks."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()

        app.open_streaming_tool_block("id1", "bash")
        await pilot.pause()

        assert "id1" in app._active_streaming_blocks, (
            "Block must be tracked in _active_streaming_blocks after open"
        )

        app.agent_running = False
        await pilot.pause()


# ---------------------------------------------------------------------------
# Append lines
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_append_line_increments_richlog():
    """append_streaming_line routes to block and populates CopyableRichLog lines."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()

        block = await _open_block(app, pilot, "id1", "cat file")

        app.append_streaming_line("id1", "line one\n")
        app.append_streaming_line("id1", "line two\n")
        app.append_streaming_line("id1", "line three\n")

        # Wait for the 60fps flush tick to fire
        await asyncio.sleep(0.1)
        await pilot.pause()

        # Plain text lines are accumulated on the block
        assert len(block._all_plain) >= 3, (
            f"Expected >= 3 plain lines on block, got: {len(block._all_plain)}"
        )

        app.agent_running = False
        await pilot.pause()


# ---------------------------------------------------------------------------
# Close removes from active dict
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_close_removes_from_active_dict():
    """close_streaming_tool_block pops the block from _active_streaming_blocks."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()

        app.open_streaming_tool_block("id1", "ls")
        await pilot.pause()
        app.append_streaming_line("id1", "total 4\n")
        await asyncio.sleep(0.05)
        await pilot.pause()

        app.close_streaming_tool_block("id1", "0.2s")
        await pilot.pause()

        assert "id1" not in app._active_streaming_blocks, (
            "Block must be removed from _active_streaming_blocks after close"
        )

        app.agent_running = False
        await pilot.pause()


# ---------------------------------------------------------------------------
# Close shows duration in header
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_close_shows_duration_in_header():
    """close_streaming_tool_block records the duration string in the ToolHeader."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()

        block = await _open_block(app, pilot, "id1", "grep -r foo")

        app.close_streaming_tool_block("id1", "1.23s")
        await pilot.pause()

        assert block._header._duration == "1.23s", (
            f"Expected _duration='1.23s', got: {block._header._duration!r}"
        )

        app.agent_running = False
        await pilot.pause()


# ---------------------------------------------------------------------------
# Close stops spinner
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_close_stops_spinner():
    """Spinner char is non-None while streaming, None after complete()."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()

        block = await _open_block(app, pilot, "id1", "find .")

        assert block._header._spinner_char is not None, (
            "Spinner must be active while streaming"
        )

        app.close_streaming_tool_block("id1", "0.5s")
        await pilot.pause()

        assert block._header._spinner_char is None, (
            "Spinner must stop after complete()"
        )

        app.agent_running = False
        await pilot.pause()


# ---------------------------------------------------------------------------
# Auto-collapse on many lines
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_collapse_hides_body_after_many_lines():
    """Blocks with > COLLAPSE_THRESHOLD lines auto-collapse after complete()."""
    from hermes_cli.tui.tool_blocks import COLLAPSE_THRESHOLD

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()

        block = await _open_block(app, pilot, "id1", "ls -la")

        for i in range(COLLAPSE_THRESHOLD + 2):
            app.append_streaming_line("id1", f"line {i}\n")

        await asyncio.sleep(0.1)
        await pilot.pause()

        app.close_streaming_tool_block("id1", "0.3s")
        await pilot.pause()

        assert not block._body.has_class("expanded"), (
            "Block body should be collapsed after complete() with many lines"
        )

        app.agent_running = False
        await pilot.pause()


@pytest.mark.asyncio
async def test_expand_shows_body():
    """After auto-collapse, toggle() expands the body."""
    from hermes_cli.tui.tool_blocks import COLLAPSE_THRESHOLD

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()

        block = await _open_block(app, pilot, "id1", "ls -la")

        for i in range(COLLAPSE_THRESHOLD + 2):
            app.append_streaming_line("id1", f"line {i}\n")

        await asyncio.sleep(0.1)
        await pilot.pause()

        app.close_streaming_tool_block("id1", "0.3s")
        await pilot.pause()

        # Collapsed — now expand
        block.toggle()
        await pilot.pause()

        assert block._body.has_class("expanded"), (
            "Block body should be expanded after toggle()"
        )

        app.agent_running = False
        await pilot.pause()


# ---------------------------------------------------------------------------
# Two concurrent blocks tracked independently
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_two_concurrent_blocks_tracked_independently():
    """Lines appended to id1 do not appear in id2."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()

        app.open_streaming_tool_block("id1", "cmd-one")
        await pilot.pause()
        app.open_streaming_tool_block("id2", "cmd-two")
        await pilot.pause()

        block1 = app._active_streaming_blocks["id1"]
        block2 = app._active_streaming_blocks["id2"]

        app.append_streaming_line("id1", "only for id1\n")

        await asyncio.sleep(0.1)
        await pilot.pause()

        assert len(block1._all_plain) >= 1, "Block1 should have received a line"
        assert len(block2._all_plain) == 0, (
            "Block2 must not receive lines sent to id1"
        )

        app.agent_running = False
        await pilot.pause()


# ---------------------------------------------------------------------------
# Interrupt mid-stream: documented leak in _active_streaming_blocks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_interrupt_mid_stream_clears_active_dict():
    """watch_agent_running(False) clears _active_streaming_blocks for interrupted blocks."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()

        app.open_streaming_tool_block("tool-1", "bash")
        await pilot.pause()

        # Interrupt: set agent_running=False WITHOUT calling close
        app.agent_running = False
        await pilot.pause()

        assert "tool-1" not in app._active_streaming_blocks, (
            "_active_streaming_blocks must be cleared on interrupt to prevent GC leaks"
        )


@pytest.mark.asyncio
async def test_interrupt_mid_stream_block_stays_in_dom():
    """After interrupt (no close), the StreamingToolBlock stays in OutputPanel DOM."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()

        app.open_streaming_tool_block("tool-1", "bash")
        await pilot.pause()

        app.agent_running = False
        await pilot.pause()

        output = app.query_one(OutputPanel)
        blocks = list(output.query(StreamingToolBlock))
        assert len(blocks) >= 1, (
            "StreamingToolBlock must remain in DOM after interrupt (not removed)"
        )


# ---------------------------------------------------------------------------
# Overwrite on second open with same id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_overwrite_on_second_open_same_id():
    """Opening the same tool_call_id twice overwrites the active dict entry — no crash."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()

        app.open_streaming_tool_block("id1", "cmd")
        await pilot.pause()
        first_block = app._active_streaming_blocks["id1"]

        # Open again with the same id (simulates turn reuse)
        app.open_streaming_tool_block("id1", "cmd again")
        await pilot.pause()
        second_block = app._active_streaming_blocks["id1"]

        assert second_block is not first_block, (
            "Second open with same id must create a new block, not reuse the stale one"
        )

        app.agent_running = False
        await pilot.pause()


# ---------------------------------------------------------------------------
# Mount order: last 3 children are always the fixed trio
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_block_mount_order_before_duo():
    """StreamingToolBlock is mounted before the ThinkingWidget/LiveLineWidget duo."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()

        app.open_streaming_tool_block("id1", "ls")
        await pilot.pause()

        output = app.query_one(OutputPanel)
        children = list(output.children)

        assert len(children) >= 2, "OutputPanel must have at least 2 children"
        last2 = children[-2:]

        assert isinstance(last2[0], ThinkingWidget), (
            f"2nd-from-last must be ThinkingWidget, got {type(last2[0]).__name__}"
        )
        assert isinstance(last2[1], LiveLineWidget), (
            f"Last child must be LiveLineWidget, got {type(last2[1]).__name__}"
        )

        # The StreamingToolBlock must NOT be in the last 2
        assert not isinstance(last2[0], StreamingToolBlock)
        assert not isinstance(last2[1], StreamingToolBlock)

        app.agent_running = False
        await pilot.pause()


# ---------------------------------------------------------------------------
# Completed block context menu copy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_completed_block_copy_via_context_menu():
    """After block completes, 'Copy tool output' context menu action flashes HintBar."""
    from unittest.mock import patch

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()

        block = await _open_block(app, pilot, "id1", "cat")
        app.append_streaming_line("id1", "output line\n")
        await asyncio.sleep(0.05)
        await pilot.pause()

        app.close_streaming_tool_block("id1", "0.1s")
        await pilot.pause()

        # Point the context event at the ToolHeader (child of the block)
        header = block.query_one(ToolHeader)
        mock_event = MagicMock()
        mock_event.widget = header

        items = app._build_context_items(mock_event)
        copy_item = next(
            (i for i in items if "Copy tool output" in i.label), None
        )
        assert copy_item is not None, "Expected 'Copy tool output' in context items"

        bar = app.query_one(HintBar)
        with patch.object(app, "copy_to_clipboard"):
            copy_item.action()
            await pilot.pause()

        assert "⎘" in bar.hint, (
            f"Expected copy icon in HintBar after copy action, got: {bar.hint!r}"
        )

        app.agent_running = False
        await pilot.pause()
