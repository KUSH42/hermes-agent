"""Tests for HermesInput widget (Input-based)."""

from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.input_widget import HermesInput


@pytest.mark.asyncio
async def test_input_widget_exists():
    """HermesInput is present in the composed layout."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one("#input-area")
        assert isinstance(inp, HermesInput)


@pytest.mark.asyncio
async def test_input_starts_empty():
    """Input value is empty on mount."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert inp.value == ""
        assert inp.content == ""  # bridge property


@pytest.mark.asyncio
async def test_content_property_bridge():
    """content property reads/writes value; cursor_pos bridges cursor_position."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.content = "hello"
        assert inp.value == "hello"
        assert inp.content == "hello"
        inp.cursor_pos = 3
        assert inp.cursor_position == 3
        assert inp.cursor_pos == 3


@pytest.mark.asyncio
async def test_input_disabled_when_agent_running():
    """Input is disabled when agent_running is True."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert not inp.disabled
        app.agent_running = True
        await pilot.pause()
        assert inp.disabled


@pytest.mark.asyncio
async def test_input_clear():
    """clear() resets content and cursor position."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "hello"
        inp.cursor_position = 3
        inp.clear()
        assert inp.value == ""
        assert inp.cursor_position == 0


@pytest.mark.asyncio
async def test_input_insert_text():
    """insert_text inserts at cursor position."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "helo"
        inp.cursor_position = 3
        inp.insert_text("l")
        assert inp.value == "hello"
        assert inp.cursor_position == 4


@pytest.mark.asyncio
async def test_slash_command_autocomplete():
    """Typing '/' triggers autocomplete when slash commands are set."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.set_slash_commands(["/help", "/history", "/quit"])
        inp.value = "/he"
        inp.cursor_position = 3
        await pilot.pause()
        assert inp.has_class("--autocomplete-visible")
        assert "/help" in inp._autocomplete_items


@pytest.mark.asyncio
async def test_history_navigation():
    """Up/Down keys cycle through history."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = ["first", "second", "third"]
        inp.value = "current"

        inp.action_history_prev()
        assert inp.value == "third"
        inp.action_history_prev()
        assert inp.value == "second"
        inp.action_history_next()
        assert inp.value == "third"
        inp.action_history_next()
        assert inp.value == "current"


@pytest.mark.asyncio
async def test_history_navigation_empty_history():
    """Up/down with no history entries is a no-op."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = []  # ensure empty
        inp.value = "current"
        inp.action_history_prev()
        assert inp.value == "current"
        inp.action_history_next()
        assert inp.value == "current"


@pytest.mark.asyncio
async def test_history_save_on_submit():
    """action_submit() saves to history before posting Submitted."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = []
        inp.value = "test command"
        inp.action_submit()
        assert "test command" in inp._history
        assert inp.value == ""


@pytest.mark.asyncio
async def test_disabled_input_rejects_keystrokes():
    """Typing into disabled HermesInput has no effect."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.focus()
        app.agent_running = True
        await pilot.pause()
        assert inp.disabled
        # Try typing — value should remain empty
        await pilot.press("a", "b", "c")
        await pilot.pause()
        assert inp.value == ""


@pytest.mark.asyncio
async def test_input_changed_triggers_autocomplete():
    """watch_value updates autocomplete popup."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.set_slash_commands(["/help", "/history"])
        # Setting value should trigger watch_value → _update_autocomplete
        inp.value = "/he"
        await pilot.pause()
        assert inp._autocomplete_items == ["/help"]


@pytest.mark.asyncio
async def test_ctrl_a_selects_all():
    """ctrl+a selects entire input value."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "hello world"
        inp.focus()
        await pilot.pause()
        inp.action_select_all()
        await pilot.pause()
        assert inp.selection.start != inp.selection.end


@pytest.mark.asyncio
async def test_shift_arrow_selection():
    """Shift+right selects text; selection range is non-empty."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "hello"
        inp.cursor_position = 0
        inp.focus()
        await pilot.pause()
        await pilot.press("shift+right")
        await pilot.pause()
        assert inp.selection.start != inp.selection.end


@pytest.mark.asyncio
async def test_ctrl_x_cuts_selected_input():
    """ctrl+x removes selected text."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.value = "hello"
        inp.focus()
        await pilot.pause()
        inp.action_select_all()
        await pilot.pause()
        await pilot.press("ctrl+x")
        await pilot.pause()
        assert inp.value == ""


@pytest.mark.asyncio
async def test_ctrl_v_pastes():
    """ctrl+v inserts clipboard content at cursor."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.focus()
        await pilot.pause()
        app.copy_to_clipboard("pasted")
        await pilot.pause()
        await pilot.press("ctrl+v")
        await pilot.pause()
        assert "pasted" in inp.value


@pytest.mark.asyncio
async def test_history_preserves_selection():
    """Up/down history navigation moves cursor to end, clearing selection."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = ["older", "newer"]
        inp.value = "current"
        inp.focus()
        await pilot.pause()
        # Select all then navigate history — selection should be gone
        inp.action_select_all()
        await pilot.pause()
        inp.action_history_prev()
        await pilot.pause()
        # After history nav, cursor should be at end of new value
        assert inp.cursor_position == len(inp.value)


@pytest.mark.asyncio
async def test_spinner_overlay_when_disabled():
    """Spinner overlay shows when agent_running; input hides."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        import asyncio
        app.agent_running = True
        await pilot.pause()
        await asyncio.sleep(0.15)
        await pilot.pause()
        from textual.widgets import Static
        overlay = app.query_one("#spinner-overlay", Static)
        inp = app.query_one("#input-area")
        assert overlay.display
        assert not inp.display


@pytest.mark.asyncio
async def test_paste_long_text():
    """Pasting text longer than terminal width is stored correctly."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        long_text = "a" * 200
        inp.focus()
        await pilot.pause()
        app.copy_to_clipboard(long_text)
        await pilot.pause()
        await pilot.press("ctrl+v")
        await pilot.pause()
        assert inp.value == long_text


@pytest.mark.asyncio
async def test_copy_from_output_is_plain():
    """CopyableRichLog.get_selection returns text without ANSI codes."""
    from textual.geometry import Offset
    from textual.selection import Selection
    from hermes_cli.tui.widgets import CopyableRichLog, _strip_ansi
    from rich.text import Text

    log = CopyableRichLog()
    ansi_line = "\x1b[1mBold text\x1b[0m"
    plain_line = _strip_ansi(ansi_line)
    log.write_with_source(Text.from_ansi(ansi_line), plain_line)

    # Select all: col 0–len on row 0. Offset(x, y): x=col, y=row.
    sel = Selection(
        start=Offset(0, 0),
        end=Offset(len(plain_line), 0),
    )
    result = log.get_selection(sel)
    assert result is not None
    text, sep = result
    assert "\x1b" not in text
    assert "Bold text" in text


@pytest.mark.asyncio
async def test_copy_from_reasoning_is_plain():
    """ReasoningPanel _plain_lines stores text without gutter prefix or ANSI."""
    from hermes_cli.tui.widgets import ReasoningPanel

    panel = ReasoningPanel()
    panel._live_buf = ""
    panel._plain_lines = []
    panel.append_delta("some reasoning\nmore text\n")
    assert "▌" not in "\n".join(panel._plain_lines)
    assert "some reasoning" in panel._plain_lines
    assert "more text" in panel._plain_lines
