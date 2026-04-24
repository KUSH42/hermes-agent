"""Tests for CopyableRichLog and plain-text copy from output panels."""

from unittest.mock import MagicMock

import pytest
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.strip import Strip

from hermes_cli.tui.widgets import CopyableRichLog, _apply_span_style, _strip_ansi


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
    """get_selection extracts text from visual lines without ANSI."""
    from textual.geometry import Offset
    from textual.selection import Selection

    log = CopyableRichLog()
    # Populate visual lines directly (bypassing layout-gated write)
    log.lines = [
        Strip([Segment("hello", Style.null())]),
        Strip([Segment("world", Style.null())]),
    ]

    # Select "hello": col 0–5 on row 0
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


def test_pre_layout_fallback_subtracts_margins():
    """Pre-layout fallback must subtract scrollbar + CopyableBlock margins.

    Regression: pre-layout used app.width - 1 (scrollbar only), but
    CopyableBlock has margin: 0 2 (4 chars total). Text wrapped 4 cols
    too wide, spilling under the scrollbar.
    """
    import inspect

    from hermes_cli.tui.widgets import CopyableRichLog

    source = inspect.getsource(CopyableRichLog.write)
    assert "app.size.width - 5" in source, (
        "Pre-layout fallback must use 'app.size.width - 5' "
        "(1 scrollbar + 4 CopyableBlock margin chars)"
    )


def test_get_selection_multiline():
    """get_selection can span multiple visual lines."""
    from textual.geometry import Offset
    from textual.selection import Selection

    log = CopyableRichLog()
    log.lines = [
        Strip([Segment("line one", Style.null())]),
        Strip([Segment("line two", Style.null())]),
    ]

    # Select from col 5 of row 0 ("one") to col 4 of row 1 ("line")
    sel = Selection(start=Offset(5, 0), end=Offset(4, 1))
    result = log.get_selection(sel)
    assert result is not None
    text, _ = result
    assert "one" in text
    assert "line" in text


# ---------------------------------------------------------------------------
# _apply_span_style tests
# ---------------------------------------------------------------------------

def _make_strip(*texts: str) -> Strip:
    """Build a Strip from plain text segments (no style)."""
    segs = [Segment(t, Style.null()) for t in texts]
    return Strip(segs, sum(len(t) for t in texts))


def test_apply_span_style_full_segment():
    """Style applied to entire segment range."""
    sel = Style(bgcolor="blue")
    strip = _make_strip("hello")
    result = _apply_span_style(strip, 0, 5, sel)
    segs = list(result)
    assert len(segs) == 1
    assert segs[0].text == "hello"
    assert segs[0].style is not None
    assert segs[0].style.bgcolor is not None


def test_apply_span_style_partial_start():
    """Style applied from start of string, not covering the end."""
    sel = Style(bgcolor="red")
    strip = _make_strip("hello world")
    result = _apply_span_style(strip, 0, 5, sel)
    segs = list(result)
    texts = [s.text for s in segs]
    assert "hello" in texts
    assert " world" in texts or "world" in " ".join(texts)
    # First segment ("hello") should have the selection style
    hello_seg = next(s for s in segs if s.text == "hello")
    assert hello_seg.style is not None and hello_seg.style.bgcolor is not None


def test_apply_span_style_partial_end():
    """Style applied from mid-point to end (end_x=-1)."""
    sel = Style(bgcolor="green")
    strip = _make_strip("hello world")
    result = _apply_span_style(strip, 6, -1, sel)
    segs = list(result)
    # "world" should be highlighted, "hello " should not
    world_seg = next((s for s in segs if s.text == "world"), None)
    assert world_seg is not None
    assert world_seg.style is not None and world_seg.style.bgcolor is not None


def test_apply_span_style_multi_segment_split():
    """Span spanning multiple segments applies style to each."""
    sel = Style(bgcolor="yellow")
    strip = Strip([
        Segment("foo", Style.null()),
        Segment("bar", Style.null()),
        Segment("baz", Style.null()),
    ], 9)
    # Select "oob" (chars 2–5): spans end of "foo" and start of "bar"
    result = _apply_span_style(strip, 2, 5, sel)
    segs = list(result)
    # Check that total text is preserved
    assert "".join(s.text for s in segs) == "foobarbaz"
    # "o" (char 2 of "foo") and "ba" (chars 0-2 of "bar") should be highlighted
    highlighted = [s.text for s in segs if s.style and s.style.bgcolor is not None]
    assert any("o" in t for t in highlighted)
    assert any("ba" in t for t in highlighted)


def test_apply_span_style_no_overlap():
    """Span outside segment range leaves strip unchanged."""
    sel = Style(bgcolor="purple")
    strip = _make_strip("hello")
    result = _apply_span_style(strip, 10, 15, sel)
    segs = list(result)
    assert len(segs) == 1
    assert segs[0].text == "hello"
    # No selection style
    assert segs[0].style == Style.null() or segs[0].style is None or (
        segs[0].style.bgcolor is None
    )


def test_apply_span_style_end_minus_one_covers_all():
    """end_x=-1 highlights the entire strip."""
    sel = Style(bgcolor="cyan")
    strip = _make_strip("full line")
    result = _apply_span_style(strip, 0, -1, sel)
    segs = list(result)
    assert all(s.style is not None and s.style.bgcolor is not None for s in segs)


# ---------------------------------------------------------------------------
# render_line selection highlight (async, requires app context)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_render_line_produces_offset_metadata():
    """render_line returns strips with offset metadata for selection tracking."""
    import asyncio
    from textual.app import App, ComposeResult

    class _App(App):
        def compose(self) -> ComposeResult:
            yield CopyableRichLog(markup=False, id="log")

        async def on_mount(self):
            log = self.query_one("#log", CopyableRichLog)
            log.write(Text("hello world"))

    async with _App().run_test(size=(80, 24)) as pilot:
        await asyncio.sleep(0.2)
        log = pilot.app.query_one("#log", CopyableRichLog)
        strip = log.render_line(0)
        found = any(
            seg.style and seg.style._meta and "offset" in seg.style.meta
            for seg in strip
        )
        assert found, "render_line must embed offset metadata for selection"


@pytest.mark.asyncio
async def test_render_line_applies_selection_style():
    """render_line paints screen--selection style when a selection is active."""
    import asyncio
    from rich.color import Color
    from textual.app import App, ComposeResult
    from textual.geometry import Offset
    from textual.selection import Selection

    class _App(App):
        def compose(self) -> ComposeResult:
            yield CopyableRichLog(markup=False, id="log")

        async def on_mount(self):
            log = self.query_one("#log", CopyableRichLog)
            log.write(Text("hello world"))

    async with _App().run_test(size=(80, 24)) as pilot:
        await asyncio.sleep(0.2)
        log = pilot.app.query_one("#log", CopyableRichLog)

        # Inject a selection covering "hello" (chars 0–5, row 0)
        sel = Selection(start=Offset(0, 0), end=Offset(5, 0))
        pilot.app.screen.selections = {log: sel}
        log.refresh()
        await asyncio.sleep(0.1)

        strip = log.render_line(0)
        segs = list(strip)
        highlighted = [s for s in segs if s.style and s.style.bgcolor is not None]
        assert highlighted, "Selected region must have a background color applied"
