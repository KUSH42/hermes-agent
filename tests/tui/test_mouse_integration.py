# Run with: pytest -o "addopts=" tests/tui/test_mouse_integration.py -v
"""Full-layout mouse and affordance integration tests.

Covers gaps left by unit-level tests:
  - CopyableBlock hover-reveal copy button (in real app layout)
  - ToolHeader ⎘/▾/▸ render text for large vs small blocks
  - StreamingCodeBlock [▼] header + collapse/expand in full layout
  - Left-click on response text does NOT scroll OutputPanel to top
  - Right-click routing from prose CopyableBlock and StreamingCodeBlock
  - Text selection: get_selection() works on can_focus=False CopyableRichLog
  - Mouse events reach can_focus=False widgets in a mounted layout
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.context_menu import ContextMenu, _ContextItem
from hermes_cli.tui.tool_blocks import ToolBlock, ToolHeader
from hermes_cli.tui.widgets import (
    CopyableBlock,
    CopyableRichLog,
    MessagePanel,
    OutputPanel,
    StreamingCodeBlock,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app() -> HermesApp:
    return HermesApp(cli=MagicMock())


async def _pause(pilot, n: int = 5) -> None:
    for _ in range(n):
        await pilot.pause()


def _right_click(widget, x: int = 5, y: int = 5) -> MagicMock:
    ev = MagicMock()
    ev.button = 3
    ev.widget = widget
    ev.screen_x = x
    ev.screen_y = y
    ev.x = x
    ev.y = y
    return ev


def _left_click(widget, x: int = 5, y: int = 5) -> MagicMock:
    ev = MagicMock()
    ev.button = 1
    ev.widget = widget
    ev.screen_x = x
    ev.screen_y = y
    ev.x = x
    ev.y = y
    return ev


# ---------------------------------------------------------------------------
# CopyableRichLog — can_focus and selection
# ---------------------------------------------------------------------------


def test_copyable_richlog_cannot_focus_to_prevent_scroll():
    """CopyableRichLog must have can_focus=False to prevent scroll-to-top on click.

    In Textual 8.x, Screen.set_focus() calls scroll_to_center → scroll_to_widget →
    container.scroll_to_region() on focus.  It does NOT call widget.scroll_visible().
    A scroll_visible() no-op is therefore ineffective.  can_focus=False is the correct
    guard: it prevents focus entirely, which prevents the scroll_to_center chain.

    Text selection still works: Textual 8.x gates selection on ALLOW_SELECT (default
    True), not on can_focus.  Mouse events are delivered by cursor position, not focus.
    """
    assert CopyableRichLog.can_focus is False, (
        "can_focus=True on CopyableRichLog triggers Screen.scroll_to_center on click, "
        "scrolling OutputPanel to y=0.  Use can_focus=False; selection works via "
        "ALLOW_SELECT=True (Textual 8.x default) without needing focus."
    )


def test_copyable_richlog_allow_select_enabled():
    """CopyableRichLog must not disable ALLOW_SELECT — selection works without focus."""
    assert CopyableRichLog.ALLOW_SELECT is True, (
        "ALLOW_SELECT=False would prevent text selection even though can_focus=False. "
        "Textual 8.x delivers selection events by cursor position, not focus."
    )


def test_copyable_richlog_get_selection_without_app():
    """get_selection() returns correct plain text without a running app.

    Verifies the selection mechanism works independently of focus state —
    Textual routes selection events by cursor position, not by focus.
    """
    from textual.geometry import Offset
    from textual.selection import Selection

    log = CopyableRichLog()
    from rich.text import Text
    log.write_with_source(Text("first line"), "first line")
    log.write_with_source(Text("second line"), "second line")

    sel = Selection(start=Offset(0, 0), end=Offset(5, 0))
    result = log.get_selection(sel)
    assert result is not None, "get_selection must return data even on can_focus=False widget"
    text, sep = result
    assert "first" in text


@pytest.mark.asyncio
async def test_copyable_richlog_mouse_down_does_not_focus():
    """Clicking a CopyableRichLog in a real layout does not give it keyboard focus.

    can_focus=False means click-to-focus never fires → OutputPanel scroll_y
    is not disturbed by Textual's scroll_visible animation.
    """
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        mp = output.new_message()
        await _pause(pilot)

        log = mp.query_one(CopyableRichLog)
        # Simulate left-click on the log via app.on_click — this is the path
        # that previously triggered scroll_visible() when can_focus was True.
        ev = _left_click(log)
        await app.on_click(ev)
        await _pause(pilot)

        # Focus must remain on the input area, not the log widget
        focused = app.focused
        assert not isinstance(focused, CopyableRichLog), (
            "CopyableRichLog must not steal focus on click (breaks scroll position)"
        )


# ---------------------------------------------------------------------------
# CopyableBlock hover-reveal copy button
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_copyable_block_hover_mounts_copy_button():
    """Mouse enter on a CopyableBlock lazily mounts the ⎘ copy button."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        mp = output.new_message()
        await _pause(pilot)

        # MessagePanel exposes _response_block (a CopyableBlock)
        block = mp._response_block
        assert isinstance(block, CopyableBlock)

        # Before hover: no copy button
        from textual.css.query import NoMatches
        with pytest.raises(NoMatches):
            block.query_one("#copy-btn")

        # Trigger hover
        block.on_mouse_enter(MagicMock())
        await _pause(pilot)

        # Copy button must exist now
        btn = block.query_one("#copy-btn")
        assert btn is not None
        # Static stores content via name-mangled _Static__content
        assert "⎘" in str(btn._Static__content)


@pytest.mark.asyncio
async def test_copyable_block_hover_idempotent():
    """Hovering a second time does not mount a second copy button."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        mp = output.new_message()
        await _pause(pilot)

        block = mp._response_block
        block.on_mouse_enter(MagicMock())
        await _pause(pilot)
        block.on_mouse_enter(MagicMock())
        await _pause(pilot)

        btns = block.query("#copy-btn")
        assert len(list(btns)) == 1, "Only one copy button must exist even after multiple hovers"


@pytest.mark.asyncio
async def test_copyable_block_copy_button_click_calls_copy():
    """Clicking the ⎘ button on a CopyableBlock fires _copy_text_with_hint."""
    from rich.text import Text
    from textual.widgets import Static

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        mp = output.new_message()
        await _pause(pilot)

        block = mp._response_block
        # Write some content so copy_content() has data
        block.log.write_with_source(Text("response text"), "response text")
        await _pause(pilot)

        # Mount the copy button via hover
        block.on_mouse_enter(MagicMock())
        await _pause(pilot)

        with patch.object(app, "_copy_text_with_hint") as mock_copy:
            btn = block.query_one("#copy-btn")
            ev = MagicMock()
            ev.widget = btn
            # CopyableBlock.on_click checks event.widget.id == "copy-btn"
            block.on_click(ev)
            await _pause(pilot)

        mock_copy.assert_called_once()
        copied_text = mock_copy.call_args[0][0]
        assert "response text" in copied_text


# ---------------------------------------------------------------------------
# ToolHeader affordance text rendering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_header_renders_copy_icon_for_large_block():
    """ToolHeader.render() includes ⎘ for blocks with more than COLLAPSE_THRESHOLD lines."""
    from hermes_cli.tui.tool_blocks import COLLAPSE_THRESHOLD

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        lines = [f"line{i}" for i in range(COLLAPSE_THRESHOLD + 1)]
        block = ToolBlock("bash", lines, lines)
        await output.mount(block)
        await _pause(pilot)

        header = block.query_one(ToolHeader)
        rendered = str(header.render())
        assert "⎘" in rendered, (
            f"ToolHeader with {COLLAPSE_THRESHOLD + 1} lines must show ⎘ copy icon"
        )


@pytest.mark.asyncio
async def test_tool_header_renders_expand_chevron_when_expanded():
    """ToolHeader shows ▾ (down) chevron when the block is expanded."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        lines = ["a", "b", "c", "d", "e"]  # 5 lines > COLLAPSE_THRESHOLD(3)
        block = ToolBlock("cat", lines, lines)
        await output.mount(block)
        await _pause(pilot)

        # Expand the block (starts collapsed by default for large blocks)
        block.toggle()
        await _pause(pilot)

        header = block.query_one(ToolHeader)
        rendered = str(header.render())
        assert "▾" in rendered, "Expanded block must show ▾ chevron"
        assert "▸" not in rendered, "Expanded block must not show ▸ chevron"


@pytest.mark.asyncio
async def test_tool_header_renders_collapse_chevron_when_collapsed():
    """ToolHeader shows ▸ (right) chevron when the block is collapsed."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        lines = ["a", "b", "c", "d", "e"]
        block = ToolBlock("cat", lines, lines)
        await output.mount(block)
        await _pause(pilot)

        # ToolBlock with >COLLAPSE_THRESHOLD lines starts collapsed by default
        header = block.query_one(ToolHeader)
        assert header.collapsed, "Large block should start collapsed"
        rendered = str(header.render())
        assert "▸" in rendered, "Collapsed block must show ▸ chevron"
        assert "▾" not in rendered, "Collapsed block must not show ▾ chevron"


@pytest.mark.asyncio
async def test_tool_header_no_affordances_for_small_block():
    """ToolHeader with ≤ COLLAPSE_THRESHOLD lines shows no ⎘ and no chevron."""
    from hermes_cli.tui.tool_blocks import COLLAPSE_THRESHOLD

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        lines = ["x"] * COLLAPSE_THRESHOLD  # exactly threshold = no affordances
        block = ToolBlock("echo", lines, lines)
        await output.mount(block)
        await _pause(pilot)

        header = block.query_one(ToolHeader)
        rendered = str(header.render())
        assert "⎘" not in rendered, (
            f"ToolHeader with ≤{COLLAPSE_THRESHOLD} lines must NOT show ⎘"
        )
        assert "▾" not in rendered
        assert "▸" not in rendered


# ---------------------------------------------------------------------------
# StreamingCodeBlock header text + collapse in full layout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_code_block_footer_visible_after_complete():
    """Integrated controls row shows copy once the fence closes."""
    app = _make_app()
    async with app.run_test(size=(80, 40)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        mp = output.new_message()
        await _pause(pilot)

        block = StreamingCodeBlock(lang="python")
        await mp.mount(block)
        await _pause(pilot)

        block.append_line("x = 1")
        block.complete({})
        await asyncio.sleep(0.05)
        await _pause(pilot)

        assert block.has_class("--complete")
        assert "copy" in block._controls_text_plain


@pytest.mark.asyncio
async def test_code_block_footer_visible_after_flush():
    """Integrated controls row is shown for FLUSHED blocks too."""
    app = _make_app()
    async with app.run_test(size=(80, 40)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        mp = output.new_message()
        await _pause(pilot)

        block = StreamingCodeBlock(lang="python")
        await mp.mount(block)
        block.append_line("x = 1")
        await _pause(pilot)

        block.flush()
        await _pause(pilot)

        assert block._state == "FLUSHED"
        assert block.has_class("--flushed")
        assert "copy" in block._controls_text_plain


@pytest.mark.asyncio
async def test_code_block_footer_copy_left_zone():
    """Copying a code block flashes the integrated controls row."""
    app = _make_app()
    async with app.run_test(size=(80, 40)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        mp = output.new_message()
        await _pause(pilot)

        block = StreamingCodeBlock(lang="python")
        await mp.mount(block)
        block.append_line("answer = 42")
        block.complete({})
        await asyncio.sleep(0.05)
        await _pause(pilot)

        with patch.object(app, "_copy_text_with_hint") as mock_copy:
            app._copy_code_block(block)
            await _pause(pilot)

        mock_copy.assert_called_once()
        assert "answer = 42" in mock_copy.call_args[0][0]
        assert "copied" in block._controls_text_plain


@pytest.mark.asyncio
async def test_code_block_footer_toggle_collapses_log():
    """toggle_collapsed() collapses/expands the code log."""
    app = _make_app()
    async with app.run_test(size=(80, 40)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        mp = output.new_message()
        await _pause(pilot)

        block = StreamingCodeBlock(lang="python")
        await mp.mount(block)
        block.append_line("x = 1")
        block.append_line("y = 2")
        block.complete({})
        await asyncio.sleep(0.05)
        await _pause(pilot)

        assert not block._collapsed

        block.toggle_collapsed()
        await _pause(pilot)
        assert block._collapsed
        assert "expand" in block._controls_text_plain

        block.toggle_collapsed()
        await _pause(pilot)
        assert not block._collapsed
        assert "collapse" in block._controls_text_plain


@pytest.mark.asyncio
async def test_code_block_footer_copy_action_click_copies():
    """Left-click on the footer copy action should copy the code block."""
    from hermes_cli.tui.widgets import CodeBlockFooter

    app = _make_app()
    async with app.run_test(size=(80, 40)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        mp = output.new_message()
        await _pause(pilot)

        block = StreamingCodeBlock(lang="python")
        await mp.mount(block)
        block.append_line("answer = 42")
        block.complete({})
        await asyncio.sleep(0.05)
        await _pause(pilot)

        copy_btn = block.query_one("#code-copy-action")
        footer = block.query_one(CodeBlockFooter)
        with patch.object(app, "_copy_text_with_hint") as mock_copy:
            footer.on_click(_left_click(copy_btn))
            await _pause(pilot)

        mock_copy.assert_called_once()
        assert "answer = 42" in mock_copy.call_args[0][0]
        assert "cop" in block._controls_text_plain.lower()


@pytest.mark.asyncio
async def test_code_block_footer_toggle_action_click_toggles():
    """Left-click on the footer toggle action should collapse and expand."""
    from hermes_cli.tui.widgets import CodeBlockFooter

    app = _make_app()
    async with app.run_test(size=(80, 40)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        mp = output.new_message()
        await _pause(pilot)

        block = StreamingCodeBlock(lang="python")
        await mp.mount(block)
        block.append_line("x = 1")
        block.append_line("y = 2")
        block.complete({})
        await asyncio.sleep(0.05)
        await _pause(pilot)

        toggle_btn = block.query_one("#code-toggle-action")
        footer = block.query_one(CodeBlockFooter)
        footer.on_click(_left_click(toggle_btn))
        await _pause(pilot)
        assert block._collapsed
        assert "expand" in block._controls_text_plain

        toggle_btn = block.query_one("#code-toggle-action")
        footer.on_click(_left_click(toggle_btn))
        await _pause(pilot)
        assert not block._collapsed
        assert "collapse" in block._controls_text_plain


# ---------------------------------------------------------------------------
# Context menu routing from prose and code block targets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_right_click_on_copyable_block_routes_to_message_panel_items():
    """Right-click on response prose (CopyableBlock) shows copy-response menu items."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        mp = output.new_message()
        await _pause(pilot)

        with patch.object(app, "_get_selected_text", return_value=None):
            await app.on_click(_right_click(mp._response_block, 20, 10))
        await _pause(pilot)

        menu = app.query_one(ContextMenu)
        assert menu.has_class("--visible"), "Right-click on response prose must open context menu"
        items = list(menu.query(_ContextItem))
        labels = [i._item.label for i in items]
        assert any("Copy full response" in lbl for lbl in labels), (
            "Menu for MessagePanel target must include 'Copy full response'"
        )


@pytest.mark.asyncio
async def test_right_click_on_streaming_code_block_shows_copy_code_item():
    """Right-click on a StreamingCodeBlock shows 'Copy code block' context menu item."""
    app = _make_app()
    async with app.run_test(size=(80, 40)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        mp = output.new_message()
        await _pause(pilot)

        block = StreamingCodeBlock(lang="python")
        await mp.mount(block)
        await _pause(pilot)

        await app.on_click(_right_click(block, 10, 5))
        await _pause(pilot)

        menu = app.query_one(ContextMenu)
        assert menu.has_class("--visible"), "Right-click on StreamingCodeBlock must open menu"
        items = list(menu.query(_ContextItem))
        labels = [i._item.label for i in items]
        assert any("Copy code block" in lbl for lbl in labels), (
            "StreamingCodeBlock right-click must show 'Copy code block' item"
        )
        # Must NOT show ToolBlock-specific items or full-response items
        assert not any("Copy tool output" in lbl for lbl in labels)
        assert not any("Copy full response" in lbl for lbl in labels)


@pytest.mark.asyncio
async def test_right_click_on_complete_code_block_shows_expand_collapse():
    """Right-click on a COMPLETE StreamingCodeBlock includes Expand/Collapse item."""
    app = _make_app()
    async with app.run_test(size=(80, 40)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        mp = output.new_message()
        await _pause(pilot)

        block = StreamingCodeBlock(lang="python")
        await mp.mount(block)
        await _pause(pilot)
        block.append_line("x = 1")
        block.append_line("y = 2")
        block.complete({})
        await asyncio.sleep(0.05)
        await _pause(pilot)

        await app.on_click(_right_click(block, 10, 5))
        await _pause(pilot)

        menu = app.query_one(ContextMenu)
        items = list(menu.query(_ContextItem))
        labels = [i._item.label for i in items]
        assert any("Expand/Collapse" in lbl for lbl in labels), (
            "COMPLETE StreamingCodeBlock right-click must include Expand/Collapse item"
        )


@pytest.mark.asyncio
async def test_right_click_on_single_line_code_block_hides_expand_collapse():
    """Single-line COMPLETE StreamingCodeBlock should not show Expand/Collapse."""
    app = _make_app()
    async with app.run_test(size=(80, 40)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        mp = output.new_message()
        await _pause(pilot)

        block = StreamingCodeBlock(lang="python")
        await mp.mount(block)
        await _pause(pilot)
        block.append_line("x = 1")
        block.complete({})
        await asyncio.sleep(0.05)
        await _pause(pilot)

        await app.on_click(_right_click(block, 10, 5))
        await _pause(pilot)

        menu = app.query_one(ContextMenu)
        items = list(menu.query(_ContextItem))
        labels = [i._item.label for i in items]
        assert not any("Expand/Collapse" in lbl for lbl in labels)


# ---------------------------------------------------------------------------
# Left-click does not steal scroll position
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_left_click_on_response_log_does_not_move_scroll():
    """Left-click on response text in a real layout does not reset OutputPanel scroll_y.

    This guards against the scroll-to-top regression caused by can_focus=True on
    CopyableRichLog: Textual called scroll_visible() → OutputPanel animated to y=0.
    """
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        mp = output.new_message()
        await _pause(pilot)

        # Left-click on the response log must just focus the input, nothing else
        log = mp.query_one(CopyableRichLog)
        ev = _left_click(log)
        initial_scroll = output.scroll_y
        await app.on_click(ev)
        await _pause(pilot)

        # scroll_y must not have changed due to the click
        assert output.scroll_y == initial_scroll, (
            "Left-click on CopyableRichLog must not alter OutputPanel scroll_y"
        )


@pytest.mark.asyncio
async def test_left_click_on_code_block_log_does_not_move_scroll():
    """Left-click on a StreamingCodeBlock's log does not reset OutputPanel scroll."""
    app = _make_app()
    async with app.run_test(size=(80, 40)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        mp = output.new_message()
        await _pause(pilot)

        block = StreamingCodeBlock(lang="python")
        await mp.mount(block)
        await _pause(pilot)

        log = block._log
        assert isinstance(log, CopyableRichLog)
        initial_scroll = output.scroll_y

        ev = _left_click(log)
        await app.on_click(ev)
        await _pause(pilot)

        assert output.scroll_y == initial_scroll, (
            "Left-click on code block's CopyableRichLog must not alter OutputPanel scroll_y"
        )


# ---------------------------------------------------------------------------
# Reasoning panel — gutter via CSS border, not text prefix
# ---------------------------------------------------------------------------


def test_reasoning_panel_gutter_line_has_no_text_prefix():
    """_gutter_line() must NOT prepend ▌ as text.

    Text-prepended ▌ only appears on the FIRST visual row of a wrapped line.
    The gutter is now provided by CSS border-left: vkey on ReasoningPanel,
    which renders on every visual row including wrap continuations.
    """
    from hermes_cli.tui.widgets import ReasoningPanel
    panel = ReasoningPanel.__new__(ReasoningPanel)
    line = panel._gutter_line("some reasoning text")
    text_str = str(line)
    assert "▌" not in text_str, (
        "_gutter_line() must not prepend ▌ as text. "
        "The gutter is now a CSS border-left: vkey on ReasoningPanel."
    )


@pytest.mark.asyncio
async def test_reasoning_panel_header_has_no_text_gutter():
    """After close_box(), the header Static must not contain ▌ text.

    CSS border-left on ReasoningPanel provides the visual gutter for ALL rows.
    Including ▌ in the header text would create a double-gutter: CSS border + text ▌.
    """
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        mp = output.new_message()
        await _pause(pilot)

        reasoning = mp.reasoning
        reasoning.open_box("Reasoning")
        reasoning.append_delta("some thought\n")
        reasoning.close_box()
        await _pause(pilot)

        header_content = str(reasoning._header._Static__content)
        assert "▌" not in header_content, (
            "ReasoningPanel header text must not include ▌ — "
            "CSS border-left provides the gutter character to avoid double-gutter."
        )
        assert "Reasoning" in header_content, "Header must still say 'Reasoning'"


def test_reasoning_panel_css_has_border_left():
    """ReasoningPanel hermes.tcss must declare border-left: vkey for the gutter."""
    import pathlib
    tcss = pathlib.Path(__file__).parents[2] / "hermes_cli" / "tui" / "hermes.tcss"
    content = tcss.read_text()
    # Find the ReasoningPanel block and verify border-left is present
    assert "border-left: vkey" in content, (
        "hermes.tcss must declare border-left: vkey on ReasoningPanel to provide "
        "a consistent left gutter on every visual row (including wrapped lines)."
    )


@pytest.mark.asyncio
async def test_reasoning_panel_gutter_present_in_mounted_app():
    """ReasoningPanel has border-left CSS applied in a mounted full app."""
    from hermes_cli.tui.widgets import ReasoningPanel as RP
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        mp = output.new_message()
        await _pause(pilot)

        reasoning = mp.reasoning
        reasoning.open_box("Reasoning")
        reasoning.append_delta("step one\n")
        reasoning.close_box()
        await _pause(pilot)

        # The gutter is a CSS border, so the content lines must NOT carry ▌ text
        lines_with_gutter_text = [
            l for l in reasoning._plain_lines if "▌" in l
        ]
        assert not lines_with_gutter_text, (
            "Reasoning content lines must not contain ▌ text prefix. "
            "Gutter is provided by CSS border-left on ReasoningPanel."
        )
