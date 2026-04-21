"""Phase D tests: SectionDivider render logic.

5 tests covering top/bottom edge rendering, set_title, set_meta, truncation.
"""
from __future__ import annotations

import pytest
from rich.segment import Segment

from hermes_cli.tui.section_divider import SectionDivider


def _render_top(width: int, title: str = "", meta: str = "") -> str:
    """Render top edge at given width and return plain text."""
    from unittest.mock import PropertyMock, patch
    from textual.geometry import Size
    sd = SectionDivider(title=title, meta=meta, edge="top")
    with patch.object(type(sd), "size", new_callable=PropertyMock, return_value=Size(width, 1)):
        strip = sd.render_line(0)
    return "".join(seg.text for seg in strip)


def _render_bottom(width: int) -> str:
    from unittest.mock import PropertyMock, patch
    from textual.geometry import Size
    sd = SectionDivider(edge="bottom")
    with patch.object(type(sd), "size", new_callable=PropertyMock, return_value=Size(width, 1)):
        strip = sd.render_line(0)
    return "".join(seg.text for seg in strip)


def test_section_divider_top_edge():
    text = _render_top(40, title="output")
    assert text.startswith("╭")
    assert "╮" in text
    assert "output" in text


def test_section_divider_bottom_edge():
    text = _render_bottom(30)
    assert text.startswith("╰")
    assert text.endswith("╯")
    assert "─" in text


def test_section_divider_set_title():
    sd = SectionDivider(title="before")
    refreshed = []
    sd.refresh = lambda: refreshed.append(True)  # type: ignore
    sd.set_title("after")
    assert sd._title == "after"
    assert refreshed


def test_section_divider_set_meta():
    sd = SectionDivider(meta="old")
    refreshed = []
    sd.refresh = lambda: refreshed.append(True)  # type: ignore
    sd.set_meta("new")
    assert sd._meta == "new"
    assert refreshed


def test_section_divider_truncates_meta_when_tight():
    """When width is very tight, meta gets truncated or dropped."""
    # Use a very narrow width that can't fit both title and meta
    text = _render_top(12, title="output", meta="very long meta string")
    # Should not crash and should fit within width
    assert len(text) <= 12
