"""Tests for ToolPendingLine widget — Phase 3 of tool-output-streamline."""

from unittest.mock import MagicMock

import pytest
from rich.text import Text

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import OutputPanel, ToolPendingLine


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_app() -> HermesApp:
    return HermesApp(cli=MagicMock())


# ---------------------------------------------------------------------------
# Test 1: single tool — show → update → commit (remove)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_single_tool_show_then_remove():
    """set_line shows the widget; remove_line hides it."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        widget = app.query_one(ToolPendingLine)
        # Initially hidden
        assert not widget.display

        # Show in-progress line
        widget.set_line("read_file", Text("  ┊ 📖 read_file  …"))
        await pilot.pause()
        assert widget.display

        # Remove once complete
        widget.remove_line("read_file")
        await pilot.pause()
        assert not widget.display


# ---------------------------------------------------------------------------
# Test 2: concurrent batch — N lines in insertion order, independent removal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_batch_order_and_independent_removal():
    """Multiple tools show in insertion order; each can be removed independently."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        widget = app.query_one(ToolPendingLine)

        widget.set_line("read_file", Text("  ┊ 📖 read_file  …"))
        widget.set_line("web_search", Text("  ┊ 🔍 web_search  …"))
        widget.set_line("terminal", Text("  ┊ 💻 terminal  …"))
        await pilot.pause()

        assert widget.display
        assert widget._order == ["read_file", "web_search", "terminal"]
        assert len(widget._lines) == 3

        # Remove middle one — others remain
        widget.remove_line("web_search")
        await pilot.pause()
        assert widget.display
        assert "web_search" not in widget._lines
        assert widget._order == ["read_file", "terminal"]

        # Remove remaining
        widget.remove_line("read_file")
        widget.remove_line("terminal")
        await pilot.pause()
        assert not widget.display


# ---------------------------------------------------------------------------
# Test 3: auto-hide when empty
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_hides_when_all_removed():
    """Widget hides as soon as the last pending line is removed."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        widget = app.query_one(ToolPendingLine)
        widget.set_line("terminal", Text("  ┊ 💻 terminal  …"))
        await pilot.pause()
        assert widget.display

        widget.remove_line("terminal")
        await pilot.pause()
        assert not widget.display
        assert not widget._lines


# ---------------------------------------------------------------------------
# Test 4: set_line on existing key updates without duplicating order
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_existing_line_no_duplicate_order():
    """set_line on an existing key updates the text without adding a duplicate."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        widget = app.query_one(ToolPendingLine)
        widget.set_line("terminal", Text("  ┊ 💻 terminal  …"))
        widget.set_line("terminal", Text("  ┊ 💻 terminal  ⠙"))
        await pilot.pause()

        assert widget._order == ["terminal"]
        assert len(widget._lines) == 1
        assert "⠙" in widget._lines["terminal"].plain


# ---------------------------------------------------------------------------
# Test 5: widget is mounted inside OutputPanel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_pending_mounted_in_output_panel():
    """ToolPendingLine is a child of OutputPanel."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        panel = app.query_one(OutputPanel)
        pending = panel.tool_pending
        assert isinstance(pending, ToolPendingLine)
