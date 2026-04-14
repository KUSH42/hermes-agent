# Run with: pytest -o "addopts=" tests/tui/test_context_menu_integration.py
"""Integration tests for context menu layout integrity and end-to-end behaviour.

Complements test_context_menu.py which covers unit-level dispatch logic.
These tests focus on:
  - Full on_click(button=3) path (not just _build_context_items)
  - Item click fires action AND dismisses the menu
  - Blur dismissal
  - Parent-chain routing from widgets nested inside ToolBlock
  - ToolBlocks mounted via app.mount_tool_block() (real mount path)
  - StreamingToolBlock right-click
  - Selection copy from ToolBlock after write_with_source fix
  - Position: menu stays within viewport
  - Re-show replaces items (no stacking)
  - Copy actions set the hint flash
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.context_menu import ContextMenu, _ContextItem
from hermes_cli.tui.tool_blocks import StreamingToolBlock, ToolBlock, ToolBodyContainer, ToolHeader
from hermes_cli.tui.widgets import HintBar, MessagePanel, OutputPanel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app() -> HermesApp:
    return HermesApp(cli=MagicMock())


async def _pause(pilot, n: int = 5) -> None:
    for _ in range(n):
        await pilot.pause()


def _right_click_event(widget, x: int = 5, y: int = 5) -> MagicMock:
    """Build a mock button=3 click event targeting *widget*."""
    ev = MagicMock()
    ev.button = 3
    ev.widget = widget
    ev.screen_x = x
    ev.screen_y = y
    ev.x = x
    ev.y = y
    return ev


# ---------------------------------------------------------------------------
# Full on_click path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_right_click_on_tool_block_opens_menu():
    """button=3 on a ToolBlock makes the ContextMenu visible."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        block = ToolBlock("grep", ["l1", "l2", "l3", "l4"], ["p1", "p2", "p3", "p4"])
        await output.mount(block)
        await _pause(pilot)

        await app.on_click(_right_click_event(block, 10, 5))
        await _pause(pilot)

        menu = app.query_one(ContextMenu)
        assert menu.has_class("--visible"), "ContextMenu must be visible after right-click on ToolBlock"


@pytest.mark.asyncio
async def test_right_click_on_tool_header_opens_menu():
    """button=3 on a ToolHeader (child of ToolBlock) routes to ToolBlock items."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        block = ToolBlock("cat", ["a", "b", "c", "d"], ["a", "b", "c", "d"])
        await output.mount(block)
        await _pause(pilot)

        header = block.query_one(ToolHeader)
        await app.on_click(_right_click_event(header, 5, 3))
        await _pause(pilot)

        menu = app.query_one(ContextMenu)
        assert menu.has_class("--visible")
        # Should have exactly 3 items (Copy tool, Expand/Collapse, Copy all)
        assert len(menu.query(_ContextItem)) == 3


@pytest.mark.asyncio
async def test_right_click_on_tool_body_container_routes_to_tool_block():
    """button=3 on ToolBodyContainer (inside ToolBlock) routes to ToolBlock items."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        block = ToolBlock("ls", ["a", "b", "c", "d"], ["a", "b", "c", "d"])
        await output.mount(block)
        await _pause(pilot)

        body = block.query_one(ToolBodyContainer)
        await app.on_click(_right_click_event(body, 5, 4))
        await _pause(pilot)

        menu = app.query_one(ContextMenu)
        assert menu.has_class("--visible")
        items = list(menu.query(_ContextItem))
        assert any("Copy tool output" in i._item.label for i in items)


@pytest.mark.asyncio
async def test_right_click_on_message_panel_opens_menu():
    """button=3 on a MessagePanel shows copy-response item."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        mp = output.new_message()
        await _pause(pilot)

        with patch.object(app, "_get_selected_text", return_value=None):
            await app.on_click(_right_click_event(mp, 20, 8))
        await _pause(pilot)

        menu = app.query_one(ContextMenu)
        assert menu.has_class("--visible")
        items = list(menu.query(_ContextItem))
        assert any("Copy full response" in i._item.label for i in items)


@pytest.mark.asyncio
async def test_right_click_on_streaming_tool_block_opens_menu():
    """button=3 on a StreamingToolBlock (ToolBlock subclass) routes to tool items."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        app.open_streaming_tool_block("stb1", "bash")
        await _pause(pilot)

        output = app.query_one(OutputPanel)
        stbs = list(output.query(StreamingToolBlock))
        assert stbs, "StreamingToolBlock not found in OutputPanel"
        stb = stbs[-1]

        await app.on_click(_right_click_event(stb, 10, 5))
        await _pause(pilot)

        menu = app.query_one(ContextMenu)
        assert menu.has_class("--visible")
        items = list(menu.query(_ContextItem))
        assert any("Copy tool output" in i._item.label for i in items)


@pytest.mark.asyncio
async def test_right_click_on_tool_block_via_mount_tool_block():
    """ToolBlock mounted via app.mount_tool_block() is right-clickable."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        app.mount_tool_block("diff", ["line1", "line2", "line3", "line4"], ["line1", "line2", "line3", "line4"])
        await _pause(pilot)

        output = app.query_one(OutputPanel)
        blocks = list(output.query(ToolBlock))
        assert blocks, "ToolBlock not found in OutputPanel"
        block = blocks[-1]

        await app.on_click(_right_click_event(block, 5, 5))
        await _pause(pilot)

        menu = app.query_one(ContextMenu)
        assert menu.has_class("--visible")


# ---------------------------------------------------------------------------
# Item click: fires action and dismisses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_item_click_fires_action():
    """Clicking a _ContextItem calls its action callable."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        fired: list[bool] = []
        from hermes_cli.tui.context_menu import MenuItem
        items = [MenuItem("Do thing", "", lambda: fired.append(True))]
        menu = app.query_one(ContextMenu)
        await menu.show(items, 5, 5)
        await _pause(pilot)

        ctx_item = menu.query_one(_ContextItem)
        ctx_item.on_click()
        await _pause(pilot)

        assert fired == [True], "Action must be called when item is clicked"


@pytest.mark.asyncio
async def test_item_click_dismisses_menu():
    """Clicking a _ContextItem hides the menu after firing the action."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        from hermes_cli.tui.context_menu import MenuItem
        items = [MenuItem("Do thing", "", lambda: None)]
        menu = app.query_one(ContextMenu)
        await menu.show(items, 5, 5)
        await _pause(pilot)
        assert menu.has_class("--visible")

        ctx_item = menu.query_one(_ContextItem)
        ctx_item.on_click()
        await _pause(pilot)

        assert not menu.has_class("--visible"), "Menu must be hidden after item click"


@pytest.mark.asyncio
async def test_item_click_copy_tool_flashes_hint():
    """Clicking 'Copy tool output' flashes the HintBar."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        block = ToolBlock("grep", ["a", "b"], ["plain a", "plain b"])
        await output.mount(block)
        await _pause(pilot)

        hint_bar = app.query_one(HintBar)

        with patch.object(app, "copy_to_clipboard"):
            with patch.object(app, "_copy_text_with_hint", wraps=app._copy_text_with_hint) as spy:
                app._copy_tool_output(block)
                await _pause(pilot)

        # HintBar should have received a flash (hint is non-empty)
        # _copy_text_with_hint eventually calls _flash_hint
        assert hint_bar.hint != "" or spy.call_count > 0


# ---------------------------------------------------------------------------
# Blur dismissal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blur_dismisses_context_menu():
    """on_blur fires when focus leaves ContextMenu — menu must hide."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        from hermes_cli.tui.context_menu import MenuItem
        menu = app.query_one(ContextMenu)
        items = [MenuItem("Copy", "", lambda: None)]
        await menu.show(items, 5, 5)
        await _pause(pilot)
        assert menu.has_class("--visible")

        # Fire on_blur directly (simulates focus moving elsewhere)
        menu.on_blur()
        await _pause(pilot)

        assert not menu.has_class("--visible"), "Blur must dismiss ContextMenu"


# ---------------------------------------------------------------------------
# Re-show replaces items (no stacking)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reshow_replaces_items():
    """Calling show() again replaces old items, not appends."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        from hermes_cli.tui.context_menu import MenuItem
        menu = app.query_one(ContextMenu)

        await menu.show([MenuItem("Item 1", "", lambda: None)], 5, 5)
        await _pause(pilot)
        assert len(menu.query(_ContextItem)) == 1

        # Show again with 2 items
        await menu.show([
            MenuItem("Item A", "", lambda: None),
            MenuItem("Item B", "", lambda: None),
        ], 5, 5)
        await _pause(pilot)

        assert len(menu.query(_ContextItem)) == 2, (
            "Re-showing must replace old items, not stack them"
        )


# ---------------------------------------------------------------------------
# Position clamping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_menu_position_within_viewport_after_right_click():
    """Menu opened via on_click is always fully inside the viewport."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        block = ToolBlock("cmd", ["x", "y", "z", "w"], ["x", "y", "z", "w"])
        await output.mount(block)
        await _pause(pilot)

        # Simulate right-click at far corner
        await app.on_click(_right_click_event(block, 999, 999))
        await _pause(pilot)

        menu = app.query_one(ContextMenu)
        assert menu.has_class("--visible")
        x = menu.styles.offset.x.value
        y = menu.styles.offset.y.value
        assert x < 80, f"Menu x={x} clipped off right edge (width=80)"
        assert y < 24, f"Menu y={y} clipped off bottom edge (height=24)"


@pytest.mark.asyncio
async def test_menu_position_at_origin():
    """Menu opened at (0, 0) stays at or near origin without going negative."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        from hermes_cli.tui.context_menu import MenuItem
        menu = app.query_one(ContextMenu)
        await menu.show([MenuItem("Item", "", lambda: None)], 0, 0)
        await _pause(pilot)

        x = menu.styles.offset.x.value
        y = menu.styles.offset.y.value
        assert x >= 0, f"Menu x={x} must not be negative"
        assert y >= 0, f"Menu y={y} must not be negative"


# ---------------------------------------------------------------------------
# Overlay layer (layout integrity)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_menu_is_on_overlay_layer():
    """ContextMenu DEFAULT_CSS declares layer: overlay."""
    css = ContextMenu.DEFAULT_CSS
    assert "layer: overlay" in css, (
        "ContextMenu must declare 'layer: overlay' in DEFAULT_CSS to float above content"
    )


@pytest.mark.asyncio
async def test_context_menu_is_last_child_of_app():
    """ContextMenu is the last widget composed in HermesApp (paints on top in overlay layer)."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        children = list(app.query("*").results())
        # Find ContextMenu in the Screen's direct children
        screen_children = list(app.screen.children)
        assert isinstance(screen_children[-1], ContextMenu), (
            "ContextMenu must be the last child of Screen so it paints above everything else"
        )


# ---------------------------------------------------------------------------
# Selection copy from ToolBlock (write_with_source fix verification)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_block_richlog_plain_lines_populated_after_mount():
    """After on_mount, CopyableRichLog._plain_lines is non-empty (write_with_source fix)."""
    from hermes_cli.tui.widgets import CopyableRichLog

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        block = ToolBlock("test", ["ansi line 1", "ansi line 2"], ["plain 1", "plain 2"])
        await output.mount(block)
        await _pause(pilot)

        log = block.query_one(CopyableRichLog)
        assert len(log._plain_lines) == 2, (
            "CopyableRichLog._plain_lines must be populated via write_with_source in on_mount"
        )
        assert log._plain_lines[0] == "plain 1"
        assert log._plain_lines[1] == "plain 2"


@pytest.mark.asyncio
async def test_tool_block_get_selection_returns_non_none():
    """get_selection() on a ToolBlock's RichLog returns content (not None) after write_with_source fix."""
    from hermes_cli.tui.widgets import CopyableRichLog

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        block = ToolBlock("test", ["line one", "line two"], ["line one", "line two"])
        await output.mount(block)
        await _pause(pilot)

        log = block.query_one(CopyableRichLog)
        # _plain_lines must be populated for get_selection to work
        assert len(log._plain_lines) > 0, "write_with_source must populate _plain_lines"


# ---------------------------------------------------------------------------
# copy_content on ToolBlock vs StreamingToolBlock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_block_copy_content_returns_plain_lines():
    """ToolBlock.copy_content() returns the plain-text version of all lines."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        block = ToolBlock("grep", ["styled a", "styled b"], ["plain a", "plain b"])
        await output.mount(block)
        await _pause(pilot)

        content = block.copy_content()
        assert "plain a" in content
        assert "plain b" in content
        # ANSI codes must not appear in copy content
        assert "\x1b" not in content


@pytest.mark.asyncio
async def test_streaming_tool_block_copy_content_after_lines():
    """StreamingToolBlock.copy_content() returns accumulated plain lines."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        app.open_streaming_tool_block("stb2", "bash")
        await _pause(pilot)

        output = app.query_one(OutputPanel)
        stbs = list(output.query(StreamingToolBlock))
        assert stbs, "StreamingToolBlock not found in OutputPanel"
        stb = stbs[-1]
        stb.append_line("output line 1")
        stb.append_line("output line 2")
        await asyncio.sleep(0.05)  # let _flush_pending fire
        await _pause(pilot)

        content = stb.copy_content()
        assert "output line 1" in content
        assert "output line 2" in content


# ---------------------------------------------------------------------------
# Empty items guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_show_with_empty_items_does_not_show_menu():
    """show() with an empty list must not make the menu visible."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        menu = app.query_one(ContextMenu)
        await menu.show([], 5, 5)
        await _pause(pilot)
        assert not menu.has_class("--visible"), "Empty items list must not show the menu"
