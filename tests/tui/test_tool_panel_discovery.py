"""B9 — Action discovery: [?] focus-hint pill on first focus.

Tests for _maybe_show_discovery_hint and _DISCOVERY_GLOBAL_SHOWN flag.
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock, call, patch

import pytest

import hermes_cli.tui.tool_panel as _tp_module


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


def _make_panel(*, result=None) -> "types.SimpleNamespace":
    panel = types.SimpleNamespace()
    panel._discovery_shown = False
    panel._result_summary_v4 = result

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
    """Reset _DISCOVERY_GLOBAL_SHOWN before/after each test."""
    _tp_module._DISCOVERY_GLOBAL_SHOWN = False
    yield
    _tp_module._DISCOVERY_GLOBAL_SHOWN = False


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

    def test_hint_not_fired_after_global_suppress(self, monkeypatch):
        monkeypatch.setenv("HERMES_ACCESSIBLE", "")
        _tp_module._DISCOVERY_GLOBAL_SHOWN = True
        panel = _make_panel(result=_make_summary())
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

    def test_discovery_flag_reset_between_test_panels(self):
        # The autouse fixture resets the flag; this test confirms it starts False
        assert _tp_module._DISCOVERY_GLOBAL_SHOWN is False

    def test_global_flag_persists_across_panel_instances(self, monkeypatch):
        monkeypatch.setenv("HERMES_ACCESSIBLE", "")
        panel1 = _make_panel(result=_make_summary())
        panel1._maybe_show_discovery_hint()
        # panel1 set _discovery_shown=True, but NOT the global flag via hint alone
        # The global flag is set only via action_show_help
        # Confirm flag still False after hint (hint doesn't set global)
        assert _tp_module._DISCOVERY_GLOBAL_SHOWN is False

        # Second panel should still be able to show hint (global not yet set)
        panel2 = _make_panel(result=_make_summary())
        panel2._maybe_show_discovery_hint()
        panel2.app.feedback.flash.assert_called_once()


class TestActionShowHelpSetsGlobalFlag:
    def test_action_show_help_sets_global_flag(self, monkeypatch):
        # Build minimal panel with app mock
        panel = types.SimpleNamespace()
        panel._discovery_shown = False
        mock_app = MagicMock()
        mock_app.query_one.side_effect = Exception("no overlay in test")
        panel.app = mock_app

        from hermes_cli.tui.tool_panel import ToolPanel
        panel.action_show_help = ToolPanel.action_show_help.__get__(panel)

        _tp_module._DISCOVERY_GLOBAL_SHOWN = False
        panel.action_show_help()
        assert _tp_module._DISCOVERY_GLOBAL_SHOWN is True
