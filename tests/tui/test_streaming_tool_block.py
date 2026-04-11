"""Tests for StreamingToolBlock — step 22/23/24 of streaming tool output (§8).

Run with:
    pytest -o "addopts=" tests/tui/test_streaming_tool_block.py -v
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.tool_blocks import (
    COLLAPSE_THRESHOLD,
    StreamingToolBlock,
    ToolHeader,
    ToolTail,
    _VISIBLE_CAP,
    _LINE_BYTE_CAP,
)
from hermes_cli.tui.widgets import CopyableRichLog, OutputPanel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _new_app_with_block(pilot, label="test cmd"):
    """Mount a StreamingToolBlock into the app's current message panel."""
    app = pilot.app
    output = app.query_one(OutputPanel)
    panel = output.current_message
    if panel is None:
        panel = output.new_message()
    block = StreamingToolBlock(label=label)
    await panel.mount(block, before=output.live_line)
    await pilot.pause()
    return block


# ---------------------------------------------------------------------------
# Lifecycle: mount, stream, complete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_block_starts_expanded():
    """StreamingToolBlock is expanded and shows spinner on mount."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_app_with_block(pilot)
        # Body should be expanded
        assert block._body.has_class("expanded")
        # Header should show a spinner char
        assert block._header._spinner_char is not None


@pytest.mark.asyncio
async def test_append_10_lines_then_complete():
    """Stream 10 lines, complete, verify auto-collapse and duration in header."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_app_with_block(pilot, label="echo test")

        for i in range(10):
            block.append_line(f"line {i}")
        await pilot.pause()

        # Let at least one 60fps flush tick fire
        await asyncio.sleep(0.05)
        await pilot.pause()

        block.complete("2.3s")
        await pilot.pause()

        # 10 > COLLAPSE_THRESHOLD → auto-collapsed
        assert block._header.collapsed is True
        assert not block._body.has_class("expanded")
        # Duration is set in header
        assert block._header._duration == "2.3s"
        # No spinner
        assert block._header._spinner_char is None
        # Total received count
        assert block._total_received == 10


@pytest.mark.asyncio
async def test_complete_with_few_lines_stays_expanded():
    """Blocks with ≤ COLLAPSE_THRESHOLD lines stay expanded after complete()."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_app_with_block(pilot)

        for i in range(COLLAPSE_THRESHOLD):
            block.append_line(f"short line {i}")
        await asyncio.sleep(0.05)
        await pilot.pause()

        block.complete("0.1s")
        await pilot.pause()

        assert block._header.collapsed is False
        assert block._body.has_class("expanded")


@pytest.mark.asyncio
async def test_lines_visible_in_richlog():
    """Appended lines appear in the body CopyableRichLog after a flush tick."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_app_with_block(pilot)

        block.append_line("hello streaming")
        await asyncio.sleep(0.05)
        await pilot.pause()

        log = block._body.query_one(CopyableRichLog)
        assert len(log.lines) >= 1
        assert block._all_plain == ["hello streaming"]


# ---------------------------------------------------------------------------
# Backpressure: byte cap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_line_byte_cap():
    """Lines exceeding _LINE_BYTE_CAP are truncated in both rendered and plain form."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_app_with_block(pilot)

        long_line = "x" * (_LINE_BYTE_CAP + 500)
        block.append_line(long_line)
        await asyncio.sleep(0.05)
        await pilot.pause()

        assert len(block._all_plain[0]) < _LINE_BYTE_CAP
        assert "…" in block._all_plain[0]


# ---------------------------------------------------------------------------
# Backpressure: 200-line visible cap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_visible_cap():
    """More than _VISIBLE_CAP lines: only _VISIBLE_CAP are written to RichLog."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_app_with_block(pilot)

        total = _VISIBLE_CAP + 50
        for i in range(total):
            block.append_line(f"line {i:04d}")

        # Wait for multiple flush ticks
        await asyncio.sleep(0.1)
        await pilot.pause()

        # All lines are in plain text
        assert len(block._all_plain) == total
        # Visible count capped + cap marker written
        assert block._visible_count == _VISIBLE_CAP
        assert block._cap_marker_written is True

        log = block._body.query_one(CopyableRichLog)
        # +1 for the cap marker line
        assert len(log.lines) == _VISIBLE_CAP + 1


# ---------------------------------------------------------------------------
# copy_content: returns all plain lines, including beyond visible cap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_copy_content_returns_all_plain_lines():
    """copy_content() returns ALL plain lines, not just the visible 200."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_app_with_block(pilot)

        total = _VISIBLE_CAP + 30
        for i in range(total):
            block.append_line(f"line {i}")
        await asyncio.sleep(0.1)
        await pilot.pause()

        content = block.copy_content()
        lines = content.splitlines()
        assert len(lines) == total


# ---------------------------------------------------------------------------
# App-level open/append/close API
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_app_open_append_close():
    """App methods open/append/close route correctly and produce a completed block."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        output.new_message()
        await pilot.pause()

        tid = "tool-001"
        app.open_streaming_tool_block(tid, "ls -la")
        await pilot.pause()

        assert tid in app._active_streaming_blocks
        block = app._active_streaming_blocks[tid]

        for line in ["total 4", "drwxr-xr-x 2 user", "-rw-r--r-- 1 user  README.md"]:
            app.append_streaming_line(tid, line)
        await asyncio.sleep(0.05)
        await pilot.pause()

        app.close_streaming_tool_block(tid, "0.2s")
        await pilot.pause()

        # Block removed from active dict
        assert tid not in app._active_streaming_blocks
        # Block is in completed state
        assert block._completed is True
        assert block._header._duration == "0.2s"


@pytest.mark.asyncio
async def test_app_append_unknown_id_is_noop():
    """append_streaming_line with an unknown ID silently ignores the call."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Should not raise
        app.append_streaming_line("nonexistent", "some line")
        await pilot.pause()


# ---------------------------------------------------------------------------
# ToolTail widget
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_tail_update_and_dismiss():
    """ToolTail shows/hides correctly via update_count / dismiss."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        panel = output.current_message or output.new_message()
        tail = ToolTail()
        await panel.mount(tail)
        await pilot.pause()

        tail.update_count(5)
        await pilot.pause()
        assert tail.display is True

        tail.update_count(0)
        await pilot.pause()
        assert tail.display is False

        tail.update_count(12)
        tail.dismiss()
        await pilot.pause()
        assert tail.display is False


# ---------------------------------------------------------------------------
# OutputPanel scroll flag
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_output_panel_scroll_flag_initial_state():
    """OutputPanel starts with _user_scrolled_up = False."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        assert panel._user_scrolled_up is False
