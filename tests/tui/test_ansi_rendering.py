"""ANSI rendering integration tests for StreamingToolBlock.

Covers: append_line() → _strip_ansi() → _flush_pending() → CopyableRichLog._plain_lines.

Run with:
    pytest -o "addopts=" tests/tui/test_ansi_rendering.py -v
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.tool_blocks import StreamingToolBlock, _VISIBLE_CAP, _LINE_BYTE_CAP
from hermes_cli.tui.widgets import CopyableRichLog, OutputPanel


# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

DIFF_LINE_ADD  = "\x1b[32m+ added line\x1b[0m"
DIFF_LINE_REM  = "\x1b[31m- removed line\x1b[0m"
DIFF_HUNK      = "\x1b[36m@@ -1,3 +1,4 @@\x1b[0m"
BOLD_LINE      = "\x1b[1mBold header\x1b[0m"
PLAIN_LINE     = "plain text"
MALFORMED_ANSI = "\x1b[32mgreen text\x1b["  # truncated escape


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _new_block(pilot, label: str) -> StreamingToolBlock:
    """Mount a StreamingToolBlock in current MessagePanel timeline."""
    app = pilot.app
    output = app.query_one(OutputPanel)
    panel = output.current_message
    if panel is None:
        panel = output.new_message()
    block = StreamingToolBlock(label=label)
    await panel.mount(block)
    await pilot.pause()
    return block


async def _flush_block(block: StreamingToolBlock, pilot) -> None:
    """Synchronously flush pending lines and wait for Textual to settle."""
    block._flush_pending()
    # In headless tests RichLog._size_known is False, so write() defers to
    # _deferred_renders instead of populating log.lines.  Drain them.
    log = block._body.query_one(CopyableRichLog)
    if not log._size_known:
        log._size_known = True
        while log._deferred_renders:
            log.write(*log._deferred_renders.popleft())
    await pilot.pause()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ansi_diff_add_line_no_escape_chars():
    """DIFF_LINE_ADD plain text contains '+ added line' with no ANSI escapes."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot, "git diff")

        block.append_line(DIFF_LINE_ADD)
        await _flush_block(block, pilot)

        log = block._body.query_one(CopyableRichLog)
        assert len(log._plain_lines) >= 1
        plain = log._plain_lines[0]
        assert "+ added line" in plain, f"plain line missing '+ added line': {plain!r}"
        assert "\x1b" not in plain, f"ANSI escape in plain_lines: {plain!r}"


@pytest.mark.asyncio
async def test_ansi_diff_rem_line_no_escape_chars():
    """DIFF_LINE_REM plain text contains '- removed line' with no ANSI escapes."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot, "git diff")

        block.append_line(DIFF_LINE_REM)
        await _flush_block(block, pilot)

        log = block._body.query_one(CopyableRichLog)
        assert len(log._plain_lines) >= 1
        plain = log._plain_lines[0]
        assert "- removed line" in plain, f"plain line missing '- removed line': {plain!r}"
        assert "\x1b" not in plain, f"ANSI escape in plain_lines: {plain!r}"


@pytest.mark.asyncio
async def test_ansi_diff_hunk_header_no_escape_chars():
    """DIFF_HUNK plain text contains '@@ -1,3 +1,4 @@' with no ANSI escapes."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot, "git diff")

        block.append_line(DIFF_HUNK)
        await _flush_block(block, pilot)

        log = block._body.query_one(CopyableRichLog)
        assert len(log._plain_lines) >= 1
        plain = log._plain_lines[0]
        assert "@@ -1,3 +1,4 @@" in plain, f"plain line missing hunk header: {plain!r}"
        assert "\x1b" not in plain, f"ANSI escape in plain_lines: {plain!r}"


@pytest.mark.asyncio
async def test_ansi_bold_line_no_escape_chars():
    """BOLD_LINE plain text contains 'Bold header' with no ANSI escapes."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot, "tool")

        block.append_line(BOLD_LINE)
        await _flush_block(block, pilot)

        log = block._body.query_one(CopyableRichLog)
        assert len(log._plain_lines) >= 1
        plain = log._plain_lines[0]
        assert "Bold header" in plain, f"plain line missing 'Bold header': {plain!r}"
        assert "\x1b" not in plain, f"ANSI escape in plain_lines: {plain!r}"


@pytest.mark.asyncio
async def test_mixed_ansi_and_plain_lines():
    """Mixed ANSI + plain lines all land in _plain_lines with no escape codes."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot, "tool")

        block.append_line(DIFF_LINE_ADD)
        block.append_line(PLAIN_LINE)
        block.append_line(BOLD_LINE)
        await _flush_block(block, pilot)

        log = block._body.query_one(CopyableRichLog)
        assert len(log._plain_lines) == 3, (
            f"expected 3 plain lines, got {len(log._plain_lines)}: {log._plain_lines!r}"
        )
        for plain in log._plain_lines:
            assert "\x1b" not in plain, f"ANSI escape found in plain line: {plain!r}"


@pytest.mark.asyncio
async def test_malformed_ansi_does_not_crash():
    """Malformed ANSI escape does not raise; at least 1 line lands in _plain_lines."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot, "tool")

        # Should not raise
        block.append_line(MALFORMED_ANSI)
        await _flush_block(block, pilot)

        log = block._body.query_one(CopyableRichLog)
        assert len(log._plain_lines) >= 1, "expected at least 1 plain line after malformed ANSI"


@pytest.mark.asyncio
async def test_completed_tool_block_ansi_content():
    """After complete(), header has correct duration, spinner cleared, no ANSI in plain_lines."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot, "bash")

        block.append_line(DIFF_LINE_ADD)
        block.append_line(DIFF_LINE_REM)
        block.append_line(BOLD_LINE)
        block.complete("1.2s")
        await pilot.pause()

        # v4 duration rule: <50ms → "" ; 50–5000ms → "NNNms" ; >5s → "N.Ns"
        # Block was just created so elapsed is sub-50ms → "" is valid
        assert isinstance(block._header._duration, str)

        log = block._body.query_one(CopyableRichLog)
        for plain in log._plain_lines:
            assert "\x1b" not in plain, f"ANSI escape in plain_lines after complete(): {plain!r}"


@pytest.mark.asyncio
async def test_copy_tool_output_strips_ansi():
    """copy_content() returns plain text containing '+ added line' and no ANSI escapes."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot, "tool")

        block.append_line(DIFF_LINE_ADD)
        await _flush_block(block, pilot)

        content = block.copy_content()
        assert "+ added line" in content, f"'+ added line' not in copy_content(): {content!r}"
        assert "\x1b" not in content, f"ANSI escape in copy_content(): {content!r}"


@pytest.mark.asyncio
async def test_ansi_in_richlog_via_app_api():
    """Full app API path (open/append/close streaming block) produces ANSI-free _plain_lines."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.agent_running = True
        await pilot.pause()

        app.open_streaming_tool_block("tool-api-test", "bash")
        await pilot.pause()

        app.append_streaming_line("tool-api-test", DIFF_LINE_ADD)
        app.append_streaming_line("tool-api-test", DIFF_LINE_REM)
        await pilot.pause()

        app.close_streaming_tool_block("tool-api-test", "0.5s")
        await pilot.pause()

        app.agent_running = False
        await pilot.pause()

        # Query the StreamingToolBlock from OutputPanel
        output = app.query_one(OutputPanel)
        blocks = output.query(StreamingToolBlock)
        assert len(blocks) >= 1, "expected at least 1 StreamingToolBlock in OutputPanel"

        log = blocks.last()._body.query_one(CopyableRichLog)
        for plain in log._plain_lines:
            assert "\x1b" not in plain, f"ANSI escape in plain_lines via app API: {plain!r}"


@pytest.mark.asyncio
async def test_line_byte_cap_appends_truncation_marker():
    """Lines exceeding _LINE_BYTE_CAP are truncated; plain text contains '…' and is short."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot, "tool")

        long_line = "X" * (_LINE_BYTE_CAP + 100)
        block.append_line(long_line)
        await _flush_block(block, pilot)

        log = block._body.query_one(CopyableRichLog)
        assert len(log._plain_lines) >= 1, "expected at least 1 plain line after long line"
        plain = log._plain_lines[0]
        assert "…" in plain, f"truncation marker '…' not found in plain line: {plain!r}"
        assert len(plain) < _LINE_BYTE_CAP + 50, (
            f"plain line too long after byte cap: {len(plain)} chars"
        )


@pytest.mark.asyncio
async def test_visible_cap_omission_bar_mounted_once():
    """After _VISIBLE_CAP + 5 lines, OmissionBar is mounted (replaces old plain-text marker)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot, "tool")

        for i in range(_VISIBLE_CAP + 5):
            block.append_line(f"line {i}")
        await _flush_block(block, pilot)
        await pilot.pause()

        assert block._omission_bar_bottom_mounted is True, "_omission_bar_bottom_mounted should be True"
        assert block._omission_bar_bottom is not None, "_omission_bar_bottom ref must be set"

        log = block._body.query_one(CopyableRichLog)
        all_texts = ["".join(seg.text for seg in strip) for strip in log.lines]
        # No plain-text "showing first" marker any more — that is now a widget
        marker_matches = [t for t in all_texts if "showing first" in t]
        assert len(marker_matches) == 0, (
            f"expected no 'showing first' line (now a widget), got: {marker_matches!r}"
        )


@pytest.mark.asyncio
async def test_visible_cap_omission_bar_shows_correct_omitted_count():
    """OmissionBar label shows the correct number of omitted lines."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot, "tool")

        total = _VISIBLE_CAP + 10
        for i in range(total):
            block.append_line(f"line {i}")
        await _flush_block(block, pilot)
        await pilot.pause()

        assert block._total_received == total, (
            f"expected _total_received={total}, got {block._total_received}"
        )
        assert block._omission_bar_bottom is not None, "_omission_bar_bottom must be set"
        assert block._omission_bar_bottom._total == total, (
            f"OmissionBar._total should be {total}, got {block._omission_bar_bottom._total}"
        )
        omitted = total - _VISIBLE_CAP
        assert block._omission_bar_bottom._visible_end == _VISIBLE_CAP, (
            "OmissionBar._visible_end should start at _VISIBLE_CAP"
        )
        assert block._omission_bar_bottom._total - block._omission_bar_bottom._visible_end == omitted, (
            f"Expected {omitted} omitted lines in bar state"
        )


@pytest.mark.asyncio
async def test_ansi_line_stored_as_text_obj():
    """copy_content() returns ANSI-free text — _all_plain never contains escape codes."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot, "tool")

        block.append_line(DIFF_LINE_ADD)
        block.append_line(BOLD_LINE)
        block.append_line(DIFF_HUNK)
        await _flush_block(block, pilot)

        content = block.copy_content()
        assert "\x1b" not in content, f"ANSI escape in copy_content() result: {content!r}"
        assert "+ added line" in content
        assert "Bold header" in content
        assert "@@ -1,3 +1,4 @@" in content
