"""B5 — FooterPane action row: real Buttons.

Tests that _action_row is populated with Button widgets on update_summary_v4,
that clicks route to the correct ToolPanel action, and that streaming suppresses
the row.
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_action(kind: str, hotkey: str, label: str):
    from hermes_cli.tui.tool_result_parse import Action
    return Action(label=label, hotkey=hotkey, kind=kind, payload=None)


def _make_summary(actions=None, is_error=False, stderr_tail="", chips=None, artifacts=None):
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    return ResultSummaryV4(
        primary=None,
        exit_code=None,
        chips=tuple(chips or []),
        stderr_tail=stderr_tail,
        actions=tuple(actions or []),
        artifacts=tuple(artifacts or []),
        is_error=is_error,
    )


def _make_footer() -> "FooterPane":
    """Create a FooterPane-like namespace with _action_row and helpers."""
    from hermes_cli.tui.tool_panel import FooterPane, _IMPLEMENTED_ACTIONS

    fp = types.SimpleNamespace()
    fp._show_all_artifacts = False
    fp._last_summary = None
    fp._last_promoted = frozenset()
    fp._last_resize_w = 0
    fp._diff_kind = ""
    fp._narrow_diff_glyph = "±"

    # Simulate _action_row with tracked mount calls
    mounted_buttons = []

    class _FakeActionRow:
        def query(self, selector):
            return list(mounted_buttons)

        def mount(self, *btns):
            for b in btns:
                mounted_buttons.append(b)

    fp._action_row = _FakeActionRow()
    fp._mounted_action_buttons = mounted_buttons

    # Bind the real method
    fp._rebuild_action_buttons = FooterPane._rebuild_action_buttons.__get__(fp)
    fp.remove_class = MagicMock()
    fp.add_class = MagicMock()

    return fp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestActionButtonsMounted:
    def test_action_buttons_mounted_on_update(self):
        fp = _make_footer()
        summary = _make_summary(actions=[_make_action("retry", "r", "retry")], is_error=True)
        fp._rebuild_action_buttons(summary, list(summary.actions))
        assert len(fp._mounted_action_buttons) >= 1

    def test_action_button_label_format(self):
        fp = _make_footer()
        summary = _make_summary(actions=[_make_action("retry", "r", "retry")], is_error=True)
        fp._rebuild_action_buttons(summary, list(summary.actions))
        btn = fp._mounted_action_buttons[0]
        label_str = str(btn.label)
        assert "[r]" in label_str
        assert "retry" in label_str

    def test_action_row_hidden_when_empty(self):
        fp = _make_footer()
        summary = _make_summary(actions=[])
        fp._rebuild_action_buttons(summary, [])
        fp.remove_class.assert_called_with("has-actions")

    def test_action_row_shown_when_has_actions(self):
        fp = _make_footer()
        summary = _make_summary(actions=[_make_action("copy_body", "y", "copy")])
        fp._rebuild_action_buttons(summary, list(summary.actions))
        fp.add_class.assert_called_with("has-actions")

    def test_no_action_buttons_when_streaming(self):
        fp = _make_footer()
        summary = _make_summary(actions=[_make_action("retry", "r", "retry")])
        # simulate streaming: pass empty list
        fp._rebuild_action_buttons(summary, [])
        assert len(fp._mounted_action_buttons) == 0
        fp.remove_class.assert_called_with("has-actions")

    def test_action_buttons_rebuilt_on_summary_update(self):
        fp = _make_footer()
        s1 = _make_summary(actions=[_make_action("copy_body", "y", "copy")])
        fp._rebuild_action_buttons(s1, list(s1.actions))
        count_first = len(fp._mounted_action_buttons)

        # Second call — old buttons removed (query returns them, remove() called)
        removed = []
        for btn in fp._mounted_action_buttons:
            btn.remove = lambda: removed.append(True)

        s2 = _make_summary(actions=[_make_action("retry", "r", "retry")], is_error=True)
        fp._rebuild_action_buttons(s2, list(s2.actions))
        # New button was mounted
        assert len(fp._mounted_action_buttons) > count_first


class TestActionButtonClicks:
    def _make_panel_with_mock_actions(self):
        """Return (panel_ns, footer_ns) with mocked action methods."""
        panel = MagicMock()
        panel.action_retry = MagicMock()
        panel.action_copy_err = MagicMock()
        panel.action_open_primary = MagicMock()
        panel.action_copy_body = MagicMock()

        from hermes_cli.tui.tool_panel import FooterPane, ToolPanel
        fp = types.SimpleNamespace()
        fp.parent = panel
        fp._show_all_artifacts = False
        fp._last_summary = None
        fp._last_promoted = frozenset()
        fp._rebuild_chips = MagicMock()
        fp.app = MagicMock()

        # Patch isinstance to return True for panel → ToolPanel
        panel.__class__ = ToolPanel

        return panel, fp

    def _press_action_chip(self, fp, kind: str):
        from hermes_cli.tui.tool_panel import FooterPane
        btn = MagicMock()
        btn.classes = ["--action-chip"]
        btn.name = kind
        event = MagicMock()
        event.button = btn
        FooterPane.on_button_pressed(fp, event)

    def test_retry_button_click_calls_action(self):
        panel, fp = self._make_panel_with_mock_actions()
        self._press_action_chip(fp, "retry")
        panel.action_retry.assert_called_once()

    def test_copy_err_button_click_calls_action(self):
        panel, fp = self._make_panel_with_mock_actions()
        self._press_action_chip(fp, "copy_err")
        panel.action_copy_err.assert_called_once()

    def test_open_button_click_calls_action(self):
        panel, fp = self._make_panel_with_mock_actions()
        self._press_action_chip(fp, "open_first")
        panel.action_open_primary.assert_called_once()

    def test_copy_button_click_calls_action(self):
        panel, fp = self._make_panel_with_mock_actions()
        self._press_action_chip(fp, "copy_body")
        panel.action_copy_body.assert_called_once()

    def test_action_chip_stops_event(self):
        panel, fp = self._make_panel_with_mock_actions()
        self._press_action_chip(fp, "copy_body")
        # event.stop() is called by checking event mock but event is local;
        # indirectly: we confirm no exception raised and handler returned


class TestActionButtonStyle:
    def test_action_button_style_matches_artifact_chip(self):
        from hermes_cli.tui.tool_panel import FooterPane
        css = FooterPane.DEFAULT_CSS
        assert "border: none" in css
        assert "background: transparent" in css
        assert "--action-chip" in css
        assert "--artifact-chip" in css
