"""Tests for context menu, copy/paste flash feedback.

Step 1 (3): _flash_hint sets + restores hint; paste flashes hint
Step 2 (7): ContextMenu show/hide/items; position clamp; blur/escape/item-click dismiss
Step 3 (8): context item dispatch per widget type; button guard; None-widget guard
Step 4 (2): copy action writes to clipboard; copy-all collects logs
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.context_menu import ContextMenu, MenuItem, _ContextItem, _ContextSep
from hermes_cli.tui.widgets import HintBar, MessagePanel, OutputPanel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app() -> HermesApp:
    return HermesApp(cli=MagicMock())


# ---------------------------------------------------------------------------
# Step 1 — Copy/paste flash feedback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flash_hint_sets_hint():
    """_flash_hint sets HintBar.hint immediately."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app._flash_hint("⎘  42 chars copied", 10.0)
        await pilot.pause()
        bar = app.query_one(HintBar)
        assert bar.hint == "⎘  42 chars copied"


@pytest.mark.asyncio
async def test_flash_hint_restores_after_duration():
    """_flash_hint restores the prior hint value after the timer fires."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Set a non-empty prior hint
        bar = app.query_one(HintBar)
        bar.hint = "prior"
        app._flash_hint("flash text", 0.05)  # very short duration
        await pilot.pause()
        assert bar.hint == "flash text"
        await asyncio.sleep(0.15)
        await pilot.pause()
        assert bar.hint == "prior"


@pytest.mark.asyncio
async def test_paste_flashes_hint():
    """Pasting into HermesInput flashes '📋 N chars' in HintBar."""
    from textual.events import Paste

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one("#input-area")
        # Post a Paste event directly to the input widget
        paste_event = Paste("hello world")
        inp.post_message(paste_event)
        await pilot.pause()
        bar = app.query_one(HintBar)
        assert "11" in bar.hint  # len("hello world") == 11
        assert "📋" in bar.hint


# ---------------------------------------------------------------------------
# Step 2 — ContextMenu widget behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_menu_starts_hidden():
    """ContextMenu is not visible on initial mount."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        menu = app.query_one(ContextMenu)
        assert not menu.has_class("--visible")


@pytest.mark.asyncio
async def test_context_menu_show_adds_visible_class():
    """show() adds --visible class."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        menu = app.query_one(ContextMenu)
        items = [MenuItem("Copy", "", lambda: None)]
        menu.show(items, 5, 5)
        await pilot.pause()
        assert menu.has_class("--visible")


@pytest.mark.asyncio
async def test_context_menu_dismiss_removes_visible_class():
    """dismiss() removes --visible class."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        menu = app.query_one(ContextMenu)
        items = [MenuItem("Copy", "", lambda: None)]
        menu.show(items, 5, 5)
        await pilot.pause()
        menu.dismiss()
        await pilot.pause()
        assert not menu.has_class("--visible")


@pytest.mark.asyncio
async def test_context_menu_show_mounts_items():
    """show() mounts the correct number of _ContextItem widgets."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        menu = app.query_one(ContextMenu)
        items = [
            MenuItem("Copy", "", lambda: None),
            MenuItem("Paste", "", lambda: None),
            MenuItem("Clear", "", lambda: None, separator_above=True),
        ]
        menu.show(items, 5, 5)
        await pilot.pause()
        assert len(menu.query(_ContextItem)) == 3
        assert len(menu.query(_ContextSep)) == 1  # separator_above on 3rd item


@pytest.mark.asyncio
async def test_context_menu_position_clamp_right():
    """show() clamps x so the menu doesn't clip off the right edge."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        menu = app.query_one(ContextMenu)
        items = [MenuItem("Copy all output", "", lambda: None)]
        # Request x near the right edge (way too far right)
        menu.show(items, 999, 5)
        await pilot.pause()
        # offset x must be < app width
        offset_x = menu.styles.offset.x.value
        assert offset_x < 80


@pytest.mark.asyncio
async def test_context_menu_position_clamp_bottom():
    """show() clamps y so the menu doesn't clip off the bottom edge."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        menu = app.query_one(ContextMenu)
        items = [MenuItem("Copy", "", lambda: None)]
        # Request y near the bottom edge
        menu.show(items, 5, 999)
        await pilot.pause()
        offset_y = menu.styles.offset.y.value
        assert offset_y < 24


@pytest.mark.asyncio
async def test_context_menu_escape_dismiss():
    """Pressing Escape while ContextMenu is focused dismisses it."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        menu = app.query_one(ContextMenu)
        items = [MenuItem("Copy", "", lambda: None)]
        menu.show(items, 5, 5)
        await pilot.pause()
        assert menu.has_class("--visible")
        # Focus the menu so Escape fires on_key
        menu.focus()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not menu.has_class("--visible")


# ---------------------------------------------------------------------------
# Step 3 — Context dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_right_click_button_1_ignored():
    """A button=1 click never opens the context menu."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        menu = app.query_one(ContextMenu)
        # Simulate left-click (button=1): menu should stay hidden
        mock_event = MagicMock()
        mock_event.button = 1
        app.on_click(mock_event)
        await pilot.pause()
        assert not menu.has_class("--visible")


@pytest.mark.asyncio
async def test_right_click_widget_none_no_menu():
    """event.widget=None produces no menu items and does not show the menu."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        mock_event = MagicMock()
        mock_event.widget = None
        items = app._build_context_items(mock_event)
        assert items == []


@pytest.mark.asyncio
async def test_build_context_items_tool_block():
    """Right-click on a ToolBlock → 3 items: Copy tool, Expand/Collapse, Copy all."""
    from hermes_cli.tui.tool_blocks import ToolBlock

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Mount a ToolBlock with >3 lines so it has affordances
        block = ToolBlock(
            "test_tool",
            ["l1", "l2", "l3", "l4"],
            ["p1", "p2", "p3", "p4"],
        )
        output = app.query_one(OutputPanel)
        await output.mount(block)
        await pilot.pause()

        mock_event = MagicMock()
        mock_event.widget = block

        items = app._build_context_items(mock_event)
        assert len(items) == 3
        assert "Copy tool output" in items[0].label
        assert "Expand" in items[1].label or "Collapse" in items[1].label
        assert "Copy all output" in items[2].label
        assert items[2].separator_above is True


@pytest.mark.asyncio
async def test_build_context_items_tool_header():
    """Right-click on a ToolHeader → same items as ToolBlock (routes via parent)."""
    from hermes_cli.tui.tool_blocks import ToolBlock, ToolHeader

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = ToolBlock(
            "test_tool",
            ["l1", "l2", "l3", "l4"],
            ["p1", "p2", "p3", "p4"],
        )
        output = app.query_one(OutputPanel)
        await output.mount(block)
        await pilot.pause()

        header = block.query_one(ToolHeader)
        mock_event = MagicMock()
        mock_event.widget = header

        items = app._build_context_items(mock_event)
        assert len(items) == 3
        assert "Copy tool output" in items[0].label


@pytest.mark.asyncio
async def test_build_context_items_message_panel():
    """Right-click on a MessagePanel → Copy full response (and optionally Copy selected)."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Trigger new_message to create a MessagePanel
        output = app.query_one(OutputPanel)
        output.new_message()
        await pilot.pause()

        panel = output.current_message
        assert panel is not None

        mock_event = MagicMock()
        mock_event.widget = panel

        # Patch _get_selected_text to return None (no selection)
        with patch.object(app, "_get_selected_text", return_value=None):
            items = app._build_context_items(mock_event)

        assert len(items) == 1
        assert "Copy full response" in items[0].label


@pytest.mark.asyncio
async def test_build_context_items_message_panel_with_selection():
    """MessagePanel + active selection → 2 items (Copy selected + Copy full response)."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        output.new_message()
        await pilot.pause()

        panel = output.current_message
        mock_event = MagicMock()
        mock_event.widget = panel

        with patch.object(app, "_get_selected_text", return_value="some selected text"):
            items = app._build_context_items(mock_event)

        assert len(items) == 2
        assert "Copy selected" in items[0].label
        assert "Copy full response" in items[1].label


@pytest.mark.asyncio
async def test_build_context_items_hermes_input():
    """Right-click on HermesInput → Paste + Clear input."""
    from hermes_cli.tui.input_widget import HermesInput

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)

        mock_event = MagicMock()
        mock_event.widget = inp

        items = app._build_context_items(mock_event)
        assert len(items) == 2
        assert "Paste" in items[0].label
        assert "Clear" in items[1].label


@pytest.mark.asyncio
async def test_build_context_items_fallback_no_selection():
    """Unrecognised widget + no selection → empty list (no menu)."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Use a Status bar widget which isn't in any special path
        from hermes_cli.tui.widgets import StatusBar
        bar = app.query_one(StatusBar)
        mock_event = MagicMock()
        mock_event.widget = bar

        with patch.object(app, "_get_selected_text", return_value=None):
            items = app._build_context_items(mock_event)

        assert items == []


@pytest.mark.asyncio
async def test_build_context_items_separator_above_flag():
    """ToolBlock menu: the third item (Copy all output) has separator_above=True."""
    from hermes_cli.tui.tool_blocks import ToolBlock

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = ToolBlock("t", ["a", "b", "c", "d"], ["a", "b", "c", "d"])
        output = app.query_one(OutputPanel)
        await output.mount(block)
        await pilot.pause()

        mock_event = MagicMock()
        mock_event.widget = block
        items = app._build_context_items(mock_event)

        # First two have no separator; third (Copy all) does
        assert items[0].separator_above is False
        assert items[1].separator_above is False
        assert items[2].separator_above is True


# ---------------------------------------------------------------------------
# Step 4 — Action implementations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_copy_tool_output_writes_clipboard():
    """_copy_tool_output calls app.copy_to_clipboard with block content."""
    from hermes_cli.tui.tool_blocks import ToolBlock

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = ToolBlock("t", ["line1", "line2"], ["plain1", "plain2"])
        output = app.query_one(OutputPanel)
        await output.mount(block)
        await pilot.pause()

        copied: list[str] = []
        with patch.object(app, "copy_to_clipboard", side_effect=copied.append):
            app._copy_tool_output(block)

        assert len(copied) == 1
        assert "plain1" in copied[0]
        assert "plain2" in copied[0]


@pytest.mark.asyncio
async def test_copy_all_output_joins_logs():
    """_copy_all_output aggregates content from all CopyableRichLog instances."""
    from rich.text import Text
    from hermes_cli.tui.widgets import CopyableRichLog

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Create two MessagePanels so we get two response logs
        output = app.query_one(OutputPanel)
        p1 = output.new_message()
        p1.response_log.write_with_source(Text("response1"), "response1")
        p2 = output.new_message()
        p2.response_log.write_with_source(Text("response2"), "response2")
        await pilot.pause()

        copied: list[str] = []
        with patch.object(app, "copy_to_clipboard", side_effect=copied.append):
            app._copy_all_output()

        assert len(copied) == 1
        assert "response1" in copied[0]
        assert "response2" in copied[0]
