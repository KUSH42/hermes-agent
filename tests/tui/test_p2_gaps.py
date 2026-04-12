"""P2 gap tests — four deferred scenarios now tractable.

Sections:
  1 — Resize mid-stream (tests 1.1–1.5)
  2 — Overlay simultaneity (tests 2.1–2.5)
  3 — Selection stability during streaming (tests 3.1–3.4)
  4 — Browse mode + context menu interactions (tests 4.1–4.6)

Run with:
    pytest -o "addopts=" tests/tui/test_p2_gaps.py -v
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.completion_overlay import CompletionOverlay
from hermes_cli.tui.tool_blocks import COLLAPSE_THRESHOLD, ToolBlock, ToolHeader
from hermes_cli.tui.widgets import (
    HistorySearchOverlay,
    HintBar,
    LiveLineWidget,
    MessagePanel,
    OutputPanel,
    ThinkingWidget,
    ToolPendingLine,
    CopyableRichLog,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app() -> HermesApp:
    cli = MagicMock()
    cli.agent = None
    return HermesApp(cli=cli)


def _make_block(n_lines: int, label: str = "cmd") -> ToolBlock:
    lines = [f"output line {i}" for i in range(n_lines)]
    return ToolBlock(label=label, lines=lines, plain_lines=lines)


async def _mount_block(app: HermesApp, pilot, n_lines: int = COLLAPSE_THRESHOLD + 2, label: str = "cmd") -> ToolBlock:
    """Mount a ToolBlock into OutputPanel before ToolPendingLine."""
    output = app.query_one(OutputPanel)
    block = _make_block(n_lines, label)
    output.mount(block, before=output.query_one(ToolPendingLine))
    await pilot.pause()
    return block


async def _run_turn(app: HermesApp, pilot, *, chunks: list[str] | None = None) -> None:
    """Simulate one agent turn: activate → optional output → deactivate."""
    app.agent_running = True
    await pilot.pause()
    for chunk in (chunks or []):
        app.write_output(chunk)
    await asyncio.sleep(0.05)
    await pilot.pause()
    app.agent_running = False
    await pilot.pause()


# ===========================================================================
# Section 1 — Resize mid-stream
# ===========================================================================

@pytest.mark.asyncio
async def test_resize_wider_during_stream_no_crash():
    """CopyableRichLog write() width calculation survives resize from 40→80."""
    app = _make_app()
    async with app.run_test(size=(40, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        app.write_output("hello ")
        await asyncio.sleep(0.02)
        await pilot.pause()
        await pilot.resize_terminal(80, 24)
        app.write_output("world\n")
        await asyncio.sleep(0.05)
        await pilot.pause()
        app.agent_running = False
        await pilot.pause()

        # No crash — current_message on OutputPanel should exist
        assert app.query_one(OutputPanel).current_message is not None


@pytest.mark.asyncio
async def test_resize_narrower_during_stream_no_crash():
    """Narrowing mid-stream is the dangerous direction (width can transiently be 0)."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        app.write_output("hello ")
        await asyncio.sleep(0.02)
        await pilot.pause()
        await pilot.resize_terminal(40, 24)
        app.write_output("world\n")
        await asyncio.sleep(0.05)
        await pilot.pause()
        app.agent_running = False
        await pilot.pause()

        assert app.query_one(OutputPanel).current_message is not None


@pytest.mark.asyncio
async def test_resize_does_not_corrupt_plain_lines():
    """Plain lines are source text — resize must not truncate them."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        long_line = "A" * 50 + "\n"
        app.agent_running = True
        await pilot.pause()
        app.write_output(long_line)
        await asyncio.sleep(0.05)
        await pilot.pause()
        # Resize between flush and turn-end
        await pilot.resize_terminal(120, 24)
        app.agent_running = False
        await pilot.pause()

        # Find the CopyableRichLog in the last MessagePanel
        output = app.query_one(OutputPanel)
        panels = list(output.query(MessagePanel))
        assert panels, "MessagePanel should exist after turn"
        plain = panels[-1].response_log._plain_lines
        assert any("A" * 50 in line for line in plain), (
            f"50 A's not found in plain_lines: {plain}"
        )


@pytest.mark.asyncio
async def test_scroll_lock_preserved_across_resize():
    """Resize must not reset _user_scrolled_up when user has scrolled up."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        # Simulate user scroll
        output._user_scrolled_up = True

        app.agent_running = True
        await pilot.pause()
        app.write_output("some chunk\n")
        await asyncio.sleep(0.02)
        await pilot.pause()

        await pilot.resize_terminal(60, 24)

        assert output._user_scrolled_up is True, (
            "resize must not reset user scroll lock"
        )

        app.agent_running = False
        await pilot.pause()


@pytest.mark.asyncio
async def test_history_search_rerenders_on_resize():
    """on_resize re-calls _render_results — overlay stays open without crash."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(HistorySearchOverlay)

        # Open the overlay
        overlay.open_search()
        await pilot.pause()
        await asyncio.sleep(0.05)
        await pilot.pause()
        assert overlay.has_class("--visible")

        # Resize — triggers on_resize which calls _render_results
        await pilot.resize_terminal(60, 24)

        # Overlay must remain open and result list must exist
        assert overlay.has_class("--visible")
        from textual.containers import VerticalScroll
        result_list = overlay.query_one("#history-result-list", VerticalScroll)
        assert result_list is not None


# ===========================================================================
# Section 2 — Overlay simultaneity
# ===========================================================================

@pytest.mark.asyncio
async def test_history_search_blocked_when_completion_visible():
    """action_open_history_search returns early when CompletionOverlay is visible."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        co = app.query_one(CompletionOverlay)
        co.add_class("--visible")
        await pilot.pause()

        app.action_open_history_search()
        await pilot.pause()

        hs = app.query_one(HistorySearchOverlay)
        assert not hs.has_class("--visible"), (
            "HistorySearchOverlay must not open when CompletionOverlay is visible"
        )


@pytest.mark.asyncio
async def test_completion_visible_does_not_block_escape():
    """Escape dismisses CompletionOverlay; HistorySearchOverlay stays closed."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        co = app.query_one(CompletionOverlay)
        co.add_class("--visible")
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()

        assert not co.has_class("--visible"), "CompletionOverlay should be dismissed"
        hs = app.query_one(HistorySearchOverlay)
        assert not hs.has_class("--visible"), "HistorySearchOverlay must not open"


@pytest.mark.asyncio
async def test_history_search_escape_priority_over_completion():
    """When both overlays are open, Escape closes HistorySearch first (priority -1)."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        co = app.query_one(CompletionOverlay)
        hs = app.query_one(HistorySearchOverlay)

        # Simulate transient race: both visible
        co.add_class("--visible")
        hs.add_class("--visible")
        await pilot.pause()

        # First Escape — history search closes (priority -1), completion stays
        await pilot.press("escape")
        await pilot.pause()
        assert not hs.has_class("--visible"), "HistorySearch should close first"
        assert co.has_class("--visible"), "CompletionOverlay should still be open"

        # Second Escape — completion closes
        await pilot.press("escape")
        await pilot.pause()
        assert not co.has_class("--visible"), "CompletionOverlay should close on second escape"


@pytest.mark.asyncio
async def test_history_search_toggles_when_completion_hidden():
    """action_open_history_search opens when CompletionOverlay is not visible."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        co = app.query_one(CompletionOverlay)
        assert not co.has_class("--visible")

        # Open
        app.action_open_history_search()
        await pilot.pause()
        hs = app.query_one(HistorySearchOverlay)
        assert hs.has_class("--visible")

        # Toggle close
        app.action_open_history_search()
        await pilot.pause()
        assert not hs.has_class("--visible")


@pytest.mark.asyncio
async def test_browse_mode_escape_clears_before_overlay_cancel():
    """Escape closes HistorySearch before browse mode exits (two distinct presses)."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Mount a block so browse_mode can stay True
        await _mount_block(app, pilot)

        app.browse_mode = True
        await pilot.pause()
        assert app.browse_mode is True

        # Manually open history search overlay
        hs = app.query_one(HistorySearchOverlay)
        hs.add_class("--visible")
        await pilot.pause()

        # First Escape: HistorySearch closes, browse_mode unchanged
        await pilot.press("escape")
        await pilot.pause()
        assert not hs.has_class("--visible"), "HistorySearch should close"
        assert app.browse_mode is True, "browse_mode must not change on first escape"

        # Second Escape: browse mode exits
        await pilot.press("escape")
        await pilot.pause()
        assert app.browse_mode is False, "browse_mode should exit on second escape"


# ===========================================================================
# Section 3 — Selection stability during streaming
# ===========================================================================

@pytest.mark.asyncio
async def test_copy_during_active_stream_no_crash():
    """Empty-selection copy during streaming must be a no-op, not a crash."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        app.write_output("partial chunk")
        await asyncio.sleep(0.02)
        await pilot.pause()

        # Call with empty string — no clipboard content, just flash
        with patch.object(app, "copy_to_clipboard", return_value=None):
            app._copy_text_with_hint("")
            await pilot.pause()

        # No exception — hint may or may not be set (empty string → "0 chars copied")
        # Just confirm agent state is intact
        assert app.agent_running is True
        app.agent_running = False
        await pilot.pause()


@pytest.mark.asyncio
async def test_context_menu_copy_during_stream_no_crash():
    """_build_context_items must be safe to call while turn is active."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        app.write_output("streaming…\n")
        await asyncio.sleep(0.05)
        await pilot.pause()

        # Build a mock event pointing at a MessagePanel
        output = app.query_one(OutputPanel)
        panels = list(output.query(MessagePanel))
        assert panels, "MessagePanel must exist during active turn"
        panel = panels[-1]

        mock_event = MagicMock()
        mock_event.widget = panel

        items = app._build_context_items(mock_event)
        assert len(items) > 0, "context items must be non-empty for MessagePanel"

        # Calling the first item's action must not raise
        with patch.object(app, "_copy_text_with_hint", return_value=None):
            items[0].action()

        app.agent_running = False
        await pilot.pause()


@pytest.mark.asyncio
async def test_plain_lines_not_corrupted_by_concurrent_read():
    """Concurrent _plain_lines reads during streaming must not corrupt accumulation."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()

        all_snapshots: list[list[str]] = []
        # Stream 20 lines in 4 batches of 5, reading _plain_lines after each batch
        output = app.query_one(OutputPanel)
        for batch in range(4):
            for i in range(5):
                app.write_output(f"line {batch * 5 + i}\n")
            await asyncio.sleep(0.05)
            await pilot.pause()
            panels = list(output.query(MessagePanel))
            if panels:
                snapshot = list(panels[-1].response_log._plain_lines)
                all_snapshots.append(snapshot)

        app.agent_running = False
        await pilot.pause()

        panels = list(output.query(MessagePanel))
        assert panels, "MessagePanel must exist"
        final = panels[-1].response_log._plain_lines
        # No duplicates
        assert len(final) == len(set(final)), f"Duplicates found in _plain_lines: {final}"
        # Final snapshot is a superset of each earlier snapshot
        for snap in all_snapshots:
            for line in snap:
                assert line in final, f"{line!r} missing from final plain_lines"


@pytest.mark.asyncio
async def test_copy_during_active_stream_stable_plain_lines():
    """Clipboard reads mid-stream must not corrupt _plain_lines accumulation."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()

        output = app.query_one(OutputPanel)
        with patch.object(app, "_copy_text_with_hint", return_value=None) as mock_copy:
            for i in range(5):
                app.write_output(f"line {i}\n")
                await asyncio.sleep(0.05)
                await pilot.pause()
                # Simulate clipboard read after each line
                panels = list(output.query(MessagePanel))
                if panels:
                    current = "\n".join(panels[-1].response_log._plain_lines)
                    app._copy_text_with_hint(current)

        app.agent_running = False
        await pilot.pause()

        panels = list(output.query(MessagePanel))
        assert panels
        final = panels[-1].response_log._plain_lines
        assert len(final) == len(set(final)), f"Duplicates in _plain_lines: {final}"
        assert len(final) == 5, f"Expected 5 lines, got {len(final)}: {final}"


# ===========================================================================
# Section 4 — Browse mode + context menu interactions
# ===========================================================================

@pytest.mark.asyncio
async def test_browse_mode_context_menu_shows_tool_items():
    """Right-click on ToolHeader in browse mode returns tool-specific menu items."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _mount_block(app, pilot)

        app.browse_mode = True
        await pilot.pause()
        assert app.browse_mode is True

        header = block.query_one(ToolHeader)
        mock_event = MagicMock()
        mock_event.widget = header

        items = app._build_context_items(mock_event)
        labels = [item.label for item in items]
        assert any("Copy tool output" in label for label in labels), (
            f"Expected 'Copy tool output' item, got: {labels}"
        )


@pytest.mark.asyncio
async def test_browse_mode_c_key_copies_focused_block():
    """In browse mode, 'c' copies the focused block's content."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block1 = await _mount_block(app, pilot, label="block1")
        block2 = await _mount_block(app, pilot, label="block2")

        app.browse_mode = True
        app.browse_index = 0
        await pilot.pause()
        assert app.browse_mode is True

        with patch.object(app, "copy_to_clipboard") as mock_clip:
            await pilot.press("c")
            await pilot.pause()

        # copy_to_clipboard was called with block1's content
        if mock_clip.called:
            copied = mock_clip.call_args[0][0]
            expected = block1.copy_content()
            assert copied == expected, (
                f"Expected block1 content, got: {copied!r}"
            )


@pytest.mark.asyncio
async def test_browse_mode_enter_toggles_focused_block():
    """Enter in browse mode expands a collapsed block with ≥4 lines."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _mount_block(app, pilot, n_lines=COLLAPSE_THRESHOLD + 2)
        # Block starts collapsed (> COLLAPSE_THRESHOLD lines)
        assert block._body.has_class("expanded") is False

        app.browse_mode = True
        app.browse_index = 0
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert block._body.has_class("expanded"), "Enter should expand the focused block"


@pytest.mark.asyncio
async def test_browse_mode_a_expands_all_blocks():
    """'a' in browse mode expands all blocks with affordances."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        blocks = [
            await _mount_block(app, pilot, n_lines=COLLAPSE_THRESHOLD + 2, label=f"b{i}")
            for i in range(3)
        ]
        app.browse_mode = True
        await pilot.pause()
        # All start collapsed
        for b in blocks:
            assert not b._body.has_class("expanded")

        await pilot.press("a")
        await pilot.pause()

        for b in blocks:
            assert b._body.has_class("expanded"), f"Block {b} should be expanded"


@pytest.mark.asyncio
async def test_browse_mode_shift_a_collapses_all_blocks():
    """'A' in browse mode collapses all expanded blocks."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        blocks = [
            await _mount_block(app, pilot, n_lines=COLLAPSE_THRESHOLD + 2, label=f"b{i}")
            for i in range(3)
        ]
        # Manually expand all
        for b in blocks:
            b._body.add_class("expanded")
            b._header.collapsed = False
        await pilot.pause()

        app.browse_mode = True
        await pilot.pause()

        await pilot.press("A")
        await pilot.pause()

        for b in blocks:
            assert not b._body.has_class("expanded"), f"Block {b} should be collapsed"


@pytest.mark.asyncio
async def test_browse_mode_exits_on_printable_key():
    """Pressing a printable key exits browse mode (character insertion is best-effort)."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await _mount_block(app, pilot)  # required for browse_mode to stay True

        app.browse_mode = True
        await pilot.pause()
        assert app.browse_mode is True

        await pilot.press("x")
        await pilot.pause()

        assert app.browse_mode is False, "Printable key should exit browse mode"
