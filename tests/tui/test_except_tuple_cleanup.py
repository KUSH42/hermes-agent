"""Spec0 — exception-fallback regression guards for ToolHeader._refresh_gutter_color."""
from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock

from hermes_cli.tui.tool_blocks._header import ToolHeader
from hermes_cli.tui.tool_blocks._shared import (
    _DIFF_ADD_FALLBACK,
    _DIFF_DEL_FALLBACK,
    _RUNNING_FALLBACK,
)


def _make_header() -> ToolHeader:
    h = ToolHeader.__new__(ToolHeader)
    h._tool_name = "test_tool"
    h._focused_gutter_color = "#000000"
    h._diff_add_color = None
    h._diff_del_color = None
    h._running_icon_color = None
    return h


class TestRefreshGutterColorFallbacks:
    def test_recovers_from_no_active_app(self):
        h = _make_header()
        type(h).app = PropertyMock(side_effect=RuntimeError("no active app"))
        h._colors = MagicMock(return_value=MagicMock(tool_header_gutter="#aaa"))
        h._refresh_gutter_color()
        assert h._diff_add_color == _DIFF_ADD_FALLBACK
        assert h._diff_del_color == _DIFF_DEL_FALLBACK
        assert h._running_icon_color == _RUNNING_FALLBACK

    def test_uses_css_variable_values_when_present(self):
        h = _make_header()
        h._colors = MagicMock(return_value=MagicMock(tool_header_gutter="#aaa"))
        app_mock = MagicMock()
        app_mock.get_css_variables.return_value = {
            "addition-marker-fg": "#11ff11",
            "deletion-marker-fg": "#ff1111",
            "status-running-color": "#ffffff",
        }
        type(h).app = PropertyMock(return_value=app_mock)
        h._refresh_gutter_color()
        assert h._diff_add_color == "#11ff11"
        assert h._diff_del_color == "#ff1111"
        assert h._running_icon_color == "#ffffff"

    def test_falls_back_for_missing_css_keys(self):
        h = _make_header()
        h._colors = MagicMock(return_value=MagicMock(tool_header_gutter="#aaa"))
        app_mock = MagicMock()
        app_mock.get_css_variables.return_value = {}
        type(h).app = PropertyMock(return_value=app_mock)
        h._refresh_gutter_color()
        assert h._diff_add_color == _DIFF_ADD_FALLBACK
        assert h._diff_del_color == _DIFF_DEL_FALLBACK
        assert h._running_icon_color == _RUNNING_FALLBACK
