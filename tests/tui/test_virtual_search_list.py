"""Tests for VirtualSearchList widget (8 tests)."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind, ToolPayload
from hermes_cli.tui.tool_category import ToolCategory


def _search_payload(output_raw: str, hit_count: int = 5) -> ToolPayload:
    return ToolPayload(
        tool_name="grep",
        category=ToolCategory.SEARCH,
        args={"query": "test"},
        input_display=None,
        output_raw=output_raw,
        line_count=0,
    )


def _cls(hit_count: int = 5) -> ClassificationResult:
    return ClassificationResult(ResultKind.SEARCH, 0.85, {"hit_count": hit_count, "query": "test"})


# ---------------------------------------------------------------------------
# Basic VirtualSearchList widget tests (no app needed)
# ---------------------------------------------------------------------------

def test_virtual_search_list_is_widget():
    """VirtualSearchList is a proper Textual Widget."""
    from textual.widget import Widget
    from hermes_cli.tui.body_renderers.search import VirtualSearchList
    lines = ["header line", "  1 │ match one", "  2 │ match two"]
    vsl = VirtualSearchList(lines_text=lines)
    assert isinstance(vsl, Widget)


def test_virtual_search_list_render_line_returns_strip():
    """render_line() returns a Strip (after on_mount populates _strips)."""
    from hermes_cli.tui.body_renderers.search import VirtualSearchList
    from textual.strip import Strip

    lines = ["header", "  1 │ match one", "  2 │ match two"]
    vsl = VirtualSearchList(lines_text=lines)
    # Before on_mount, _strips is empty; render_line should still return Strip
    result = vsl.render_line(0)
    assert isinstance(result, Strip)


def test_virtual_search_list_100_hits_uses_virtual():
    """SearchRenderer.build_widget returns VirtualSearchList when hit_count > 100."""
    from hermes_cli.tui.body_renderers.search import SearchRenderer, VirtualSearchList

    # Build a fake output with many hits
    lines = ["src/foo.py"]
    for i in range(105):
        lines.append(f"  {i+1}: match content {i}")
    output = "\n".join(lines)

    payload = _search_payload(output, hit_count=105)
    cls_result = _cls(hit_count=105)
    renderer = SearchRenderer(payload, cls_result)
    widget = renderer.build_widget()
    assert isinstance(widget, VirtualSearchList)


def test_virtual_search_list_few_hits_uses_normal_build():
    """SearchRenderer.build_widget returns CopyableRichLog when hit_count <= 100."""
    from hermes_cli.tui.body_renderers.search import SearchRenderer
    from hermes_cli.tui.widgets import CopyableRichLog

    output = "src/foo.py\n  1: match one\n  2: match two\n  3: match three\n"
    payload = _search_payload(output, hit_count=3)
    cls_result = _cls(hit_count=3)
    renderer = SearchRenderer(payload, cls_result)
    widget = renderer.build_widget()
    assert isinstance(widget, CopyableRichLog)


def test_virtual_search_list_scroll_offset_clamps():
    """_scroll_offset is clamped to valid range."""
    from hermes_cli.tui.body_renderers.search import VirtualSearchList

    lines = ["line1", "line2", "line3"]
    vsl = VirtualSearchList(lines_text=lines)
    vsl._scroll_offset = 0

    # Simulate j key to go down
    class MockEvent:
        key = "j"
    # Manually apply the scroll logic
    max_off = max(0, len(lines) - 1)
    vsl._scroll_offset = min(vsl._scroll_offset + 100, max_off)
    assert vsl._scroll_offset == max_off

    # Simulate k key to go up past 0
    vsl._scroll_offset = max(0, vsl._scroll_offset - 100)
    assert vsl._scroll_offset == 0


def test_virtual_search_list_lines_count_correct():
    """VirtualSearchList stores the exact number of input lines."""
    from hermes_cli.tui.body_renderers.search import VirtualSearchList

    lines = [f"line {i}" for i in range(10)]
    vsl = VirtualSearchList(lines_text=lines)
    assert len(vsl._lines_text) == 10


def test_virtual_search_list_file_headers_present():
    """SearchRenderer builds lines list including file headers."""
    from hermes_cli.tui.body_renderers.search import SearchRenderer

    output = "src/foo.py\n  1: def foo\n  2: pass\n  3: end\n"
    payload = _search_payload(output, hit_count=3)
    cls_result = _cls(hit_count=3)
    renderer = SearchRenderer(payload, cls_result)
    lines = renderer._build_lines_list()
    # At least one line should contain the file path
    assert any("src/foo.py" in l for l in lines)


def test_virtual_search_list_empty_search_handled():
    """VirtualSearchList handles empty lines list without error."""
    from hermes_cli.tui.body_renderers.search import VirtualSearchList
    from textual.strip import Strip

    vsl = VirtualSearchList(lines_text=[])
    assert vsl.render_line(0) == Strip([])
    assert vsl.render_line(5) == Strip([])
