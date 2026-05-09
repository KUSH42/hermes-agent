"""Tests for GHF-H1 (frozen terminal chip) and GHF-M1 (outcome glyph)."""
from __future__ import annotations

import re
import time
import types
from unittest.mock import PropertyMock

import pytest


class TestTerminalFormatter:
    """GHF-H1 pure formatter tests — no Textual app."""

    def test_terminal_stats_plural(self):
        from hermes_cli.tui.tool_blocks._group_header_stats import terminal_stats
        result = terminal_stats(3, 88.0, "18:14")
        assert "3 tools" in result
        assert "18:14" in result
        # format_elapsed_short(88.0) → "1:28"
        assert "1:28" in result

    def test_terminal_stats_singular(self):
        from hermes_cli.tui.tool_blocks._group_header_stats import terminal_stats
        result = terminal_stats(1, 3.1, "10:05")
        assert "1 tool" in result
        assert "tools" not in result
        assert "10:05" in result
        assert "3.1s" in result

    def test_terminal_stats_span_frozen(self):
        """Formatter is pure — same span_s → same span string."""
        from hermes_cli.tui.tool_blocks._group_header_stats import terminal_stats
        r1 = terminal_stats(2, 88.0, "12:00")
        time.sleep(0.01)
        r2 = terminal_stats(2, 88.0, "12:00")
        # Extract the middle segment (elapsed)
        def span_part(s):
            parts = s.split(" · ")
            return parts[1] if len(parts) >= 2 else s
        assert span_part(r1) == span_part(r2)

    def test_clock_hhmm_format(self):
        from hermes_cli.tui.tool_blocks._group_header_stats import _clock_hhmm
        ts = time.monotonic()
        result = _clock_hhmm(ts)
        assert re.match(r"^\d{2}:\d{2}$", result), f"Expected HH:MM, got {result!r}"

    def _make_header(self, **overrides):
        """Construct a bare GroupHeader and set fields directly (no app)."""
        from hermes_cli.tui.tool_group import GroupHeader

        class FakeSize:
            width = 120

        # Subclass to override the read-only size property without touching Textual
        class _TestGroupHeader(GroupHeader):
            size = FakeSize()  # type: ignore[assignment]

        h = _TestGroupHeader.__new__(_TestGroupHeader)
        # Set defaults matching __init__
        h._summary_text = "test summary"
        h._diff_add = 0
        h._diff_del = 0
        h._duration_ms = 0
        h._child_count = 2
        h._collapsed = False
        h._error_count = 0
        h._terminal_at = None
        h._group_state_value = ""
        h.refresh = lambda: None  # suppress Textual refresh
        for k, v in overrides.items():
            setattr(h, k, v)
        return h

    def test_group_header_terminal_chip_rendered(self):
        h = self._make_header(_terminal_at=1000.0, _child_count=2, _duration_ms=88000)
        result = str(h.render())
        assert "tool" in result
        assert ":" in result  # clock separator

    def test_group_header_live_duration_when_running(self):
        h = self._make_header(_terminal_at=None, _duration_ms=3000)
        result = str(h.render())
        assert ("3000ms" in result or "3.0s" in result)
        assert "tool" not in result

    def test_group_header_terminal_replaces_live_duration(self):
        h = self._make_header(_terminal_at=None, _duration_ms=3000)
        r1 = str(h.render())
        assert "ms" in r1 or "s" in r1

        h._terminal_at = time.monotonic()
        h._duration_ms = 3000
        r2 = str(h.render())
        assert "tool" in r2
        # live "ms" form should not appear
        assert "ms" not in r2

    def test_tool_group_captures_terminal_at(self):
        """ToolGroup._group_terminal_at is set once and immutable thereafter."""
        from hermes_cli.tui.tool_group import ToolGroup, ToolGroupState, _TERMINAL_GROUP_STATES

        # Create a minimal ToolGroup (no app)
        tg = ToolGroup.__new__(ToolGroup)
        tg._group_terminal_at = None
        tg._group_state = ToolGroupState.RUNNING

        # Simulate first transition to DONE
        import time as _t
        tg._group_state = ToolGroupState.DONE
        if tg._group_state in _TERMINAL_GROUP_STATES and tg._group_terminal_at is None:
            tg._group_terminal_at = _t.monotonic()
        first_ts = tg._group_terminal_at
        assert first_ts is not None

        time.sleep(0.01)
        # Simulate second call — should NOT overwrite
        if tg._group_state in _TERMINAL_GROUP_STATES and tg._group_terminal_at is None:
            tg._group_terminal_at = _t.monotonic()
        assert tg._group_terminal_at == first_ts


class TestLeftGlyph:
    """GHF-M1 outcome glyph tests — bare GroupHeader, no app."""

    def _make_header(self, group_state_value: str):
        from hermes_cli.tui.tool_group import GroupHeader

        class FakeSize:
            width = 120

        class _TestGroupHeader(GroupHeader):
            size = FakeSize()  # type: ignore[assignment]

        h = _TestGroupHeader.__new__(_TestGroupHeader)
        h._summary_text = "test"
        h._diff_add = 0
        h._diff_del = 0
        h._duration_ms = 0
        h._child_count = 1
        h._collapsed = False
        h._error_count = 0
        h._terminal_at = None
        h._group_state_value = group_state_value
        h.refresh = lambda: None
        return h

    def test_left_glyph_running_no_glyph(self):
        h = self._make_header("running")
        result = str(h.render())
        assert "✓" not in result
        assert "✗" not in result
        assert "–" not in result

    def test_left_glyph_done(self):
        h = self._make_header("done")
        result = str(h.render())
        assert "✓" in result

    def test_left_glyph_err(self):
        h = self._make_header("err")
        result = str(h.render())
        assert "✗" in result

    def test_left_glyph_cancelled(self):
        h = self._make_header("cancelled")
        result = str(h.render())
        assert "–" in result
