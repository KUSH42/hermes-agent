"""B1 — Collapsed+focused action strip.

Tests for _CollapsedActionStrip visibility logic in ToolPanel.
"""
from __future__ import annotations

import os
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_summary(is_error=False, stderr_tail=""):
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    return ResultSummaryV4(
        primary=None, exit_code=None,
        chips=(), actions=(), artifacts=(),
        is_error=is_error, stderr_tail=stderr_tail,
    )


def _make_panel(
    *,
    has_focus: bool = False,
    collapsed: bool = True,
    result: object = None,
    category_name: str = "SHELL",
    deterministic: bool = False,
) -> "types.SimpleNamespace":
    """Build a SimpleNamespace that mimics the parts of ToolPanel used by _refresh_collapsed_strip."""
    from hermes_cli.tui.tool_panel import _CollapsedActionStrip, _get_collapsed_actions

    strip = types.SimpleNamespace()
    strip._visible = False

    def strip_add_class(cls):
        if cls == "--visible":
            strip._visible = True

    def strip_remove_class(cls):
        if cls == "--visible":
            strip._visible = False

    strip.add_class = strip_add_class
    strip.remove_class = strip_remove_class
    strip.update = MagicMock()

    from hermes_cli.tui.tool_category import ToolCategory
    category_map = {
        "SHELL": ToolCategory.SHELL,
        "FILE": ToolCategory.FILE,
        "SEARCH": ToolCategory.SEARCH,
        "WEB": ToolCategory.WEB,
        "CODE": ToolCategory.CODE,
        "AGENT": ToolCategory.AGENT,
        "MCP": ToolCategory.MCP,
    }

    panel = types.SimpleNamespace()
    panel._collapsed_strip = strip
    panel.has_focus = has_focus
    panel.collapsed = collapsed
    panel._result_summary_v4 = result
    panel._category = category_map.get(category_name, ToolCategory.SHELL)
    panel._deterministic = deterministic

    from hermes_cli.tui.tool_panel import ToolPanel
    panel._refresh_collapsed_strip = ToolPanel._refresh_collapsed_strip.__get__(panel)

    return panel


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCollapsedActionStrip:
    def test_strip_visible_when_unfocused_collapsed(self, monkeypatch):
        # QW-03: strip shows whenever collapsed, focus only affects color via CSS
        monkeypatch.delenv("HERMES_DETERMINISTIC", raising=False)
        panel = _make_panel(has_focus=False, collapsed=True, result=_make_summary())
        panel._refresh_collapsed_strip()
        assert panel._collapsed_strip._visible

    def test_strip_visible_when_focused_collapsed(self, monkeypatch):
        monkeypatch.delenv("HERMES_DETERMINISTIC", raising=False)
        panel = _make_panel(has_focus=True, collapsed=True, result=_make_summary())
        panel._refresh_collapsed_strip()
        assert panel._collapsed_strip._visible

    def test_strip_hidden_when_focused_expanded(self, monkeypatch):
        monkeypatch.delenv("HERMES_DETERMINISTIC", raising=False)
        panel = _make_panel(has_focus=True, collapsed=False, result=_make_summary())
        panel._refresh_collapsed_strip()
        assert not panel._collapsed_strip._visible

    def test_strip_hidden_during_streaming(self, monkeypatch):
        monkeypatch.delenv("HERMES_DETERMINISTIC", raising=False)
        panel = _make_panel(has_focus=True, collapsed=True, result=None)
        panel._refresh_collapsed_strip()
        assert not panel._collapsed_strip._visible

    def test_strip_retry_only_on_error(self, monkeypatch):
        monkeypatch.delenv("HERMES_DETERMINISTIC", raising=False)
        panel = _make_panel(
            has_focus=True, collapsed=True,
            result=_make_summary(is_error=False), category_name="SHELL"
        )
        panel._refresh_collapsed_strip()
        call = panel._collapsed_strip.update.call_args
        if call:
            text_obj = call[0][0]
            assert "[r]" not in str(text_obj)

    def test_strip_retry_shown_on_error(self, monkeypatch):
        monkeypatch.delenv("HERMES_DETERMINISTIC", raising=False)
        panel = _make_panel(
            has_focus=True, collapsed=True,
            result=_make_summary(is_error=True), category_name="SHELL"
        )
        panel._refresh_collapsed_strip()
        assert panel._collapsed_strip._visible
        call = panel._collapsed_strip.update.call_args
        assert call is not None
        text_obj = call[0][0]
        assert "[r]" in str(text_obj)

    def test_strip_err_only_with_stderr(self, monkeypatch):
        monkeypatch.delenv("HERMES_DETERMINISTIC", raising=False)
        panel = _make_panel(
            has_focus=True, collapsed=True,
            result=_make_summary(stderr_tail=""), category_name="SHELL"
        )
        panel._refresh_collapsed_strip()
        call = panel._collapsed_strip.update.call_args
        if call:
            text_obj = call[0][0]
            assert "[e]" not in str(text_obj)

    def test_strip_err_shown_with_stderr(self, monkeypatch):
        monkeypatch.delenv("HERMES_DETERMINISTIC", raising=False)
        panel = _make_panel(
            has_focus=True, collapsed=True,
            result=_make_summary(stderr_tail="error output"), category_name="SHELL"
        )
        panel._refresh_collapsed_strip()
        assert panel._collapsed_strip._visible
        call = panel._collapsed_strip.update.call_args
        assert call is not None
        text_obj = call[0][0]
        assert "[e]" in str(text_obj)

    def test_strip_keys_always_present(self, monkeypatch):
        monkeypatch.delenv("HERMES_DETERMINISTIC", raising=False)
        panel = _make_panel(
            has_focus=True, collapsed=True,
            result=_make_summary(), category_name="SHELL"
        )
        panel._refresh_collapsed_strip()
        assert panel._collapsed_strip._visible
        call = panel._collapsed_strip.update.call_args
        assert call is not None
        text_obj = call[0][0]
        assert "[?]" in str(text_obj)

    def test_strip_stays_on_blur(self, monkeypatch):
        # QW-03: blur no longer hides the strip; CSS dims it via color rules
        monkeypatch.delenv("HERMES_DETERMINISTIC", raising=False)
        panel = _make_panel(has_focus=True, collapsed=True, result=_make_summary())
        panel._refresh_collapsed_strip()
        assert panel._collapsed_strip._visible

        # Simulate blur: _refresh_collapsed_strip is called with has_focus=False
        panel.has_focus = False
        panel._refresh_collapsed_strip()
        assert panel._collapsed_strip._visible

    def test_strip_updates_on_collapse(self, monkeypatch):
        monkeypatch.delenv("HERMES_DETERMINISTIC", raising=False)
        # Start expanded+focused — no strip
        panel = _make_panel(has_focus=True, collapsed=False, result=_make_summary())
        panel._refresh_collapsed_strip()
        assert not panel._collapsed_strip._visible

        # Now collapse while focused — strip should appear
        panel.collapsed = True
        panel._refresh_collapsed_strip()
        assert panel._collapsed_strip._visible

    def test_strip_suppressed_under_deterministic(self, monkeypatch):
        monkeypatch.setenv("HERMES_DETERMINISTIC", "1")
        panel = _make_panel(has_focus=True, collapsed=True, result=_make_summary())
        panel._refresh_collapsed_strip()
        assert not panel._collapsed_strip._visible

    def test_strip_no_duplicate_in_footer_pane(self, monkeypatch):
        monkeypatch.delenv("HERMES_DETERMINISTIC", raising=False)
        # When collapsed, FooterPane should be hidden (watch_collapsed logic),
        # so B1 strip and B5 footer don't overlap.
        # Verify: _CollapsedActionStrip.DEFAULT_CSS sets display:none by default.
        from hermes_cli.tui.tool_panel import _CollapsedActionStrip
        assert "display: none" in _CollapsedActionStrip.DEFAULT_CSS
        assert "--visible" in _CollapsedActionStrip.DEFAULT_CSS
