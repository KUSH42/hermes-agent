"""Tests for CopyableRichLog and plain-text copy from output panels."""

from unittest.mock import MagicMock

import pytest
from rich.text import Text

from hermes_cli.tui.widgets import CopyableRichLog, _strip_ansi


def test_strip_ansi_removes_sgr():
    """_strip_ansi removes SGR color codes."""
    assert _strip_ansi("\x1b[31mhello\x1b[0m") == "hello"


def test_strip_ansi_removes_multiple_codes():
    """_strip_ansi handles multiple ANSI sequences."""
    text = "\x1b[1m\x1b[34mbold blue\x1b[0m normal \x1b[32mgreen\x1b[0m"
    assert _strip_ansi(text) == "bold blue normal green"


def test_strip_ansi_preserves_plain_text():
    """_strip_ansi leaves plain text unchanged."""
    assert _strip_ansi("hello world") == "hello world"


def test_strip_ansi_preserves_markdown():
    """_strip_ansi preserves markdown syntax (only strips ANSI)."""
    text = "\x1b[1m# Header\x1b[0m"
    assert _strip_ansi(text) == "# Header"


@pytest.mark.asyncio
async def test_copyable_richlog_stores_plain_lines():
    """write_with_source stores plain text alongside styled text."""
    log = CopyableRichLog()
    styled = Text("hello", style="bold")
    log.write_with_source(styled, "hello")
    assert log._plain_lines == ["hello"]


@pytest.mark.asyncio
async def test_copyable_richlog_clear():
    """clear() resets _plain_lines."""
    log = CopyableRichLog()
    log.write_with_source(Text("a"), "a")
    log.write_with_source(Text("b"), "b")
    assert len(log._plain_lines) == 2
    log.clear()
    assert log._plain_lines == []


def test_plain_lines_memory_bounded():
    """_plain_lines is cleared by clear(); no unbounded growth across turns."""
    log = CopyableRichLog()
    for i in range(100):
        log.write_with_source(Text(f"line {i}"), f"line {i}")
    assert len(log._plain_lines) == 100
    log.clear()
    assert log._plain_lines == []
    # After clear, new writes start fresh — no accumulation from prior turn
    log.write_with_source(Text("new"), "new")
    assert log._plain_lines == ["new"]


def test_get_selection_returns_plain_text():
    """get_selection extracts text from _plain_lines without ANSI.

    Offset(x, y): x=column, y=row. Selection.extract uses transpose=(y, x).
    """
    from textual.geometry import Offset
    from textual.selection import Selection

    log = CopyableRichLog()
    log.write_with_source(Text("hello"), "hello")
    log.write_with_source(Text("world"), "world")

    # Select "hello": col 0–5 on row 0 → Offset(x=0,y=0) to Offset(x=5,y=0)
    sel = Selection(start=Offset(0, 0), end=Offset(5, 0))
    result = log.get_selection(sel)
    assert result is not None
    text, sep = result
    assert text == "hello"
    assert sep == "\n"


def test_get_selection_empty_log():
    """get_selection returns None when no lines stored."""
    from textual.geometry import Offset
    from textual.selection import Selection

    log = CopyableRichLog()
    sel = Selection(start=Offset(0, 0), end=Offset(5, 0))
    assert log.get_selection(sel) is None


def test_get_selection_multiline():
    """get_selection can span multiple plain lines."""
    from textual.geometry import Offset
    from textual.selection import Selection

    log = CopyableRichLog()
    log.write_with_source(Text("line one"), "line one")
    log.write_with_source(Text("line two"), "line two")

    # Select from col 5 of row 0 ("one") to col 4 of row 1 ("line")
    # Offset(x=5, y=0) = col 5, row 0; Offset(x=4, y=1) = col 4, row 1
    sel = Selection(start=Offset(5, 0), end=Offset(4, 1))
    result = log.get_selection(sel)
    assert result is not None
    text, _ = result
    assert "one" in text
    assert "line" in text
