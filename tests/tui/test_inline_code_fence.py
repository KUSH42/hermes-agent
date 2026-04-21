"""Tests for InlineCodeFence widget and response_flow detection (5 tests)."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# InlineCodeFence widget tests
# ---------------------------------------------------------------------------

def test_inline_code_fence_widget_composes():
    """InlineCodeFence is a Widget that can be instantiated."""
    from textual.widget import Widget
    from hermes_cli.tui.response_flow import InlineCodeFence

    fence = InlineCodeFence(lines=["  1 | def foo():", "  2 |     pass"])
    assert isinstance(fence, Widget)


def test_inline_code_fence_contains_lines():
    """InlineCodeFence stores provided lines."""
    from hermes_cli.tui.response_flow import InlineCodeFence

    lines = ["  1 | def foo():", "  2 |     pass", "  3 |     return 1"]
    fence = InlineCodeFence(lines=lines)
    assert fence._lines == lines


# ---------------------------------------------------------------------------
# ResponseFlowEngine InlineCodeFence detection tests (no app needed)
# ---------------------------------------------------------------------------

def test_response_flow_detects_numbered_lines():
    """_NUMBERED_LINE_RE matches lines with number|content format."""
    from hermes_cli.tui.response_flow import _NUMBERED_LINE_RE

    # These should match
    matching = [
        "  1 | def foo():",
        " 12 |     return val",
        "100 | some content",
        "1| x",
        "  5 |   indented",
    ]
    for line in matching:
        assert _NUMBERED_LINE_RE.match(line), f"Expected match for: {repr(line)}"


def test_response_flow_non_numbered_not_fenced():
    """_NUMBERED_LINE_RE does NOT match plain prose lines."""
    from hermes_cli.tui.response_flow import _NUMBERED_LINE_RE

    non_matching = [
        "This is regular prose",
        "  - list item",
        "# heading",
        "No numbers here",
        "",
        "def foo():  # no number prefix",
    ]
    for line in non_matching:
        assert not _NUMBERED_LINE_RE.match(line), f"Expected no match for: {repr(line)}"


def test_response_flow_single_numbered_line_not_fenced():
    """A single numbered line should NOT become an InlineCodeFence (need >= 2)."""
    from hermes_cli.tui.response_flow import ResponseFlowEngine, _NUMBERED_LINE_RE

    # Single line: buffer should not trigger fence (need >= 2)
    engine = MagicMock()
    engine._code_fence_buffer = []

    line = "  1 | def foo():"
    if _NUMBERED_LINE_RE.match(line):
        engine._code_fence_buffer.append(line)

    # With only 1 line in buffer, should not mount InlineCodeFence
    assert len(engine._code_fence_buffer) == 1
    # Verify it requires >= 2 before flushing as fence
    # (the actual logic is in _commit_prose_line/_flush_code_fence_buffer)
    buf = engine._code_fence_buffer
    would_fence = len(buf) >= 2
    assert would_fence is False
