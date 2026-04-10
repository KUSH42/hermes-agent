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
