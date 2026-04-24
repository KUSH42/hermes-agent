"""B9 / QW-12 — Action discovery: per-category hint gating.

Tests for _maybe_show_discovery_hint and _DISCOVERY_SHOWN_CATEGORIES set.
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest

import hermes_cli.tui.tool_panel._completion as _comp_module
from hermes_cli.tui.tool_category import ToolCategory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_summary():
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    return ResultSummaryV4(
        primary=None, exit_code=None,
        chips=(), actions=(), artifacts=(),
        is_error=False, stderr_tail="",
    )


def _make_panel(*, result=None, category=ToolCategory.SHELL) -> "types.SimpleNamespace":
    panel = types.SimpleNamespace()
    panel._discovery_shown = False
    panel._result_summary_v4 = result
    panel._category = category

    mock_feedback = MagicMock()
    mock_feedback.LOW = 0
    mock_app = MagicMock()
    mock_app.feedback = mock_feedback
    panel.app = mock_app

    from hermes_cli.tui.tool_panel import ToolPanel
    panel._maybe_show_discovery_hint = ToolPanel._maybe_show_discovery_hint.__get__(panel)

    return panel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_global_flag():
    """Reset _DISCOVERY_SHOWN_CATEGORIES before/after each test."""
    _comp_module._DISCOVERY_SHOWN_CATEGORIES.clear()
    yield
    _comp_module._DISCOVERY_SHOWN_CATEGORIES.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDiscoveryHint:
    def test_hint_fires_on_first_focus_with_result(self, monkeypatch):
        monkeypatch.setenv("HERMES_ACCESSIBLE", "")
        monkeypatch.setenv("HERMES_NO_UNICODE", "")
        panel = _make_panel(result=_make_summary())
        panel._maybe_show_discovery_hint()
        panel.app.feedback.flash.assert_called_once()

    def test_hint_not_fired_during_streaming(self, monkeypatch):
        monkeypatch.setenv("HERMES_ACCESSIBLE", "")
        panel = _make_panel(result=None)
        panel._maybe_show_discovery_hint()
        panel.app.feedback.flash.assert_not_called()

    def test_hint_not_fired_twice(self, monkeypatch):
        monkeypatch.setenv("HERMES_ACCESSIBLE", "")
        panel = _make_panel(result=_make_summary())
        panel._maybe_show_discovery_hint()
        panel._maybe_show_discovery_hint()
        assert panel.app.feedback.flash.call_count == 1

    def test_hint_not_fired_after_category_in_set(self, monkeypatch):
        monkeypatch.setenv("HERMES_ACCESSIBLE", "")
        _comp_module._DISCOVERY_SHOWN_CATEGORIES.add(ToolCategory.SHELL)
        panel = _make_panel(result=_make_summary(), category=ToolCategory.SHELL)
        panel._maybe_show_discovery_hint()
        panel.app.feedback.flash.assert_not_called()

    def test_hint_not_fired_in_accessibility_mode(self, monkeypatch):
        monkeypatch.setenv("HERMES_ACCESSIBLE", "1")
        panel = _make_panel(result=_make_summary())
        panel._maybe_show_discovery_hint()
        panel.app.feedback.flash.assert_not_called()

    def test_hint_priority_is_zero(self, monkeypatch):
        monkeypatch.setenv("HERMES_ACCESSIBLE", "")
        panel = _make_panel(result=_make_summary())
        panel._maybe_show_discovery_hint()
        _, kwargs = panel.app.feedback.flash.call_args
        assert kwargs.get("priority") == 0

    def test_hint_duration_is_3s(self, monkeypatch):
        monkeypatch.setenv("HERMES_ACCESSIBLE", "")
        panel = _make_panel(result=_make_summary())
        panel._maybe_show_discovery_hint()
        _, kwargs = panel.app.feedback.flash.call_args
        assert kwargs.get("duration") == 3.0

    def test_hint_key_is_tool_discovery(self, monkeypatch):
        monkeypatch.setenv("HERMES_ACCESSIBLE", "")
        panel = _make_panel(result=_make_summary())
        panel._maybe_show_discovery_hint()
        _, kwargs = panel.app.feedback.flash.call_args
        assert kwargs.get("key") == "tool-discovery"

    def test_hint_text_references_question_mark(self, monkeypatch):
        monkeypatch.setenv("HERMES_ACCESSIBLE", "")
        panel = _make_panel(result=_make_summary())
        panel._maybe_show_discovery_hint()
        args, _ = panel.app.feedback.flash.call_args
        msg = args[1]
        assert "?" in msg
        assert "F1" in msg

    def test_discovery_set_empty_at_start(self):
        assert len(_comp_module._DISCOVERY_SHOWN_CATEGORIES) == 0

    def test_category_added_to_set_after_hint(self, monkeypatch):
        monkeypatch.setenv("HERMES_ACCESSIBLE", "")
        panel = _make_panel(result=_make_summary(), category=ToolCategory.FILE)
        panel._maybe_show_discovery_hint()
        assert ToolCategory.FILE in _comp_module._DISCOVERY_SHOWN_CATEGORIES

    def test_different_category_still_fires_after_first(self, monkeypatch):
        monkeypatch.setenv("HERMES_ACCESSIBLE", "")
        panel1 = _make_panel(result=_make_summary(), category=ToolCategory.SHELL)
        panel1._maybe_show_discovery_hint()
        # FILE not yet shown — a different panel should fire
        panel2 = _make_panel(result=_make_summary(), category=ToolCategory.FILE)
        panel2._maybe_show_discovery_hint()
        panel2.app.feedback.flash.assert_called_once()

    def test_same_category_second_panel_skips(self, monkeypatch):
        monkeypatch.setenv("HERMES_ACCESSIBLE", "")
        panel1 = _make_panel(result=_make_summary(), category=ToolCategory.SHELL)
        panel1._maybe_show_discovery_hint()
        panel2 = _make_panel(result=_make_summary(), category=ToolCategory.SHELL)
        panel2._maybe_show_discovery_hint()
        panel2.app.feedback.flash.assert_not_called()


class TestActionShowHelpSetsGlobalFlag:
    def test_action_show_help_marks_all_categories(self, monkeypatch):
        panel = types.SimpleNamespace()
        panel._discovery_shown = False
        mock_app = MagicMock()
        mock_app.query_one.side_effect = Exception("no overlay in test")
        panel.app = mock_app

        from hermes_cli.tui.tool_panel import ToolPanel
        panel.action_show_help = ToolPanel.action_show_help.__get__(panel)

        assert len(_comp_module._DISCOVERY_SHOWN_CATEGORIES) == 0
        panel.action_show_help()
        for cat in ToolCategory:
            assert cat in _comp_module._DISCOVERY_SHOWN_CATEGORIES
