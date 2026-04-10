"""Tests for input widget focus and chevron prompt rendering."""

from unittest.mock import MagicMock

import pytest
from rich.text import Text

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.input_widget import HermesInput


@pytest.mark.asyncio
async def test_input_focused_on_startup():
    """Input widget receives focus automatically when the app mounts."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert inp.has_focus, "Input should be focused on startup"


@pytest.mark.asyncio
async def test_chevron_visible_when_empty():
    """The ❯ chevron is visible even when input is empty."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert inp.content == ""
        rendered = inp.render()
        assert isinstance(rendered, Text)
        assert rendered.plain.startswith("❯ ")


@pytest.mark.asyncio
async def test_chevron_visible_with_content():
    """The ❯ chevron precedes user-typed content."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.content = "hello"
        rendered = inp.render()
        assert rendered.plain.startswith("❯ hello")


@pytest.mark.asyncio
async def test_chevron_visible_when_disabled():
    """The ❯ chevron is visible even when input is disabled with spinner."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.disabled = True
        inp.spinner_text = "thinking..."
        rendered = inp.render()
        assert rendered.plain.startswith("❯ ")
        assert "thinking..." in rendered.plain


@pytest.mark.asyncio
async def test_chevron_visible_when_masked():
    """The ❯ chevron is visible during password masking."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.content = "secret"
        inp.masked = True
        rendered = inp.render()
        assert rendered.plain.startswith("❯ ")
        assert "●" in rendered.plain
        assert "secret" not in rendered.plain


@pytest.mark.asyncio
async def test_prompt_symbol_constant():
    """PROMPT_SYMBOL matches the PT version's chevron."""
    assert HermesInput.PROMPT_SYMBOL == "❯ "


@pytest.mark.asyncio
async def test_cursor_offset_accounts_for_chevron():
    """Cursor position in render is offset by the chevron length."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.content = "abc"
        inp.cursor_pos = 1  # between 'a' and 'b'
        rendered = inp.render()
        # The chevron is "❯ " (2 chars), so cursor at content pos 1
        # means the 'b' at rendered position 3 should be reversed
        plain = rendered.plain
        assert plain.startswith("❯ abc")


@pytest.mark.asyncio
async def test_no_placeholder_when_idle():
    """No placeholder text shown when idle (matches PT behavior)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert inp.placeholder_text == ""
        # When focused and empty, just chevron + cursor
        rendered = inp.render()
        # Should be "❯ " + cursor indicator only
        assert "Send a message" not in rendered.plain


@pytest.mark.asyncio
async def test_placeholder_child_always_hidden():
    """The placeholder Static child widget is always hidden (display:none)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        placeholder = inp.query_one(".hermes-input--placeholder")
        # display should be none regardless of content state
        assert not placeholder.display
