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
    ToolBlock,
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
    """Mount a StreamingToolBlock into current MessagePanel timeline."""
    app = pilot.app
    output = app.query_one(OutputPanel)
    panel = output.current_message
    if panel is None:
        panel = output.new_message()
    block = StreamingToolBlock(label=label)
    await panel.mount(block)
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
        # Timer starts immediately
        assert block._header._duration.endswith("s")


@pytest.mark.asyncio
async def test_live_timer_updates_while_streaming():
    """Header duration updates while the tool is still active."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_app_with_block(pilot)

        first = block._header._duration
        await asyncio.sleep(0.22)
        await pilot.pause()
        second = block._header._duration

        assert first.endswith("s")
        assert second.endswith("s")
        assert second != first


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
async def test_complete_freezes_timer_to_final_duration():
    """Final duration overrides live timer and stays fixed after complete()."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_app_with_block(pilot, label="echo test")

        await asyncio.sleep(0.18)
        await pilot.pause()
        live_value = block._header._duration
        assert live_value.endswith("s")

        block.complete("1.7s")
        await pilot.pause()
        frozen = block._header._duration
        await asyncio.sleep(0.18)
        await pilot.pause()

        assert frozen == "1.7s"
        assert block._header._duration == "1.7s"


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

        truncated = block._all_plain[0]
        # Truncated at _LINE_BYTE_CAP chars of content + "… (+N chars)" trailer
        assert truncated.startswith("x" * _LINE_BYTE_CAP), "First _LINE_BYTE_CAP chars must be preserved"
        assert "…" in truncated, "Truncation marker must be present"
        assert "+500 chars" in truncated, "Overrun count must be reported"
        # Total length is _LINE_BYTE_CAP + len of the trailer, NOT the old hardcoded 200
        assert len(truncated) < _LINE_BYTE_CAP + 30, "Total should not greatly exceed _LINE_BYTE_CAP"


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


# ---------------------------------------------------------------------------
# ToolTail mounted in StreamingToolBlock
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_streaming_tool_block_mounts_tool_tail():
    """StreamingToolBlock now composes a ToolTail — it must be present in DOM."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)

        app.open_streaming_tool_block("t1", "bash")
        await pilot.pause()

        block = output.query_one(StreamingToolBlock)
        # ToolTail must be mounted as a direct child
        tail = block.query_one(ToolTail)
        assert tail is not None
        # Initially hidden
        assert tail.display is False


@pytest.mark.asyncio
async def test_tool_tail_dismissed_on_complete():
    """complete() dismisses ToolTail unconditionally.

    The count lives in tail._new_line_count (single source of truth);
    complete() calls tail.dismiss() which resets it to 0.
    """
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)

        app.open_streaming_tool_block("t1", "bash")
        await pilot.pause()

        block = output.query_one(StreamingToolBlock)
        tail = block.query_one(ToolTail)

        # Arm the tail (simulating scroll-away state)
        tail.update_count(5)
        await pilot.pause()
        assert tail.display is True
        assert tail._new_line_count == 5

        app.close_streaming_tool_block("t1", "1.2s")
        await pilot.pause()
        assert tail.display is False
        assert tail._new_line_count == 0


@pytest.mark.asyncio
async def test_scroll_to_bottom_dismisses_tool_tail():
    """OutputPanel.watch_scroll_y dismisses ToolTail when user returns to live edge.

    max_scroll_y is 0 in headless tests (no overflow content), so we patch it
    to a non-zero value to exercise the guard branch.
    """
    from unittest.mock import PropertyMock, patch
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)

        app.open_streaming_tool_block("t1", "bash")
        await pilot.pause()

        block = output.query_one(StreamingToolBlock)
        tail = block.query_one(ToolTail)

        # Arm the scroll flag and tail
        output._user_scrolled_up = True
        tail.update_count(3)
        await pilot.pause()
        assert tail.display is True

        # Patch max_scroll_y so the guard passes, then trigger the watcher
        with patch.object(type(output), "max_scroll_y", new_callable=PropertyMock, return_value=10):
            output._user_scrolled_up = True
            output.watch_scroll_y(0.0, 10)
        await pilot.pause()
        assert output._user_scrolled_up is False


# ---------------------------------------------------------------------------
# refresh_skin() on StreamingToolBlock
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_skin_does_not_clear_body():
    """refresh_skin() on a completed StreamingToolBlock must not wipe content."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()

        app.open_streaming_tool_block("id-rs", "ls -la")
        await pilot.pause()
        for i in range(5):
            app.append_streaming_line("id-rs", f"line {i}")
        await asyncio.sleep(0.12)
        await pilot.pause()
        app.close_streaming_tool_block("id-rs", "0.5s")
        await pilot.pause()

        block = app.query_one(StreamingToolBlock)
        log = block.query_one(CopyableRichLog)
        lines_before = len(log.lines)
        assert lines_before > 0

        # refresh_skin should NOT clear the body
        block.refresh_skin()
        await pilot.pause()
        assert len(log.lines) == lines_before


@pytest.mark.asyncio
async def test_refresh_skin_is_subclass_safe():
    """self.query(ToolBlock) finds StreamingToolBlock — refresh_skin must not crash."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()

        app.open_streaming_tool_block("id-q", "test")
        await pilot.pause()
        app.append_streaming_line("id-q", "output line")
        await asyncio.sleep(0.12)
        await pilot.pause()
        app.close_streaming_tool_block("id-q", "0.1s")
        await pilot.pause()

        # query(ToolBlock) should find the StreamingToolBlock
        blocks = list(app.query(ToolBlock))
        assert len(blocks) == 1
        assert isinstance(blocks[0], StreamingToolBlock)

        # refresh_skin on each should not raise
        for b in blocks:
            b.refresh_skin()
        await pilot.pause()
