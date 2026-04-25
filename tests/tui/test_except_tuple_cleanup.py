"""Spec0 — except tuple cleanup regression guards for _resolve_max_header_gap."""
from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock

from hermes_cli.tui.tool_blocks._header import (
    MAX_HEADER_GAP_CELLS_FALLBACK,
    _resolve_max_header_gap,
)


class TestResolveMaxHeaderGap:
    def test_resolve_max_header_gap_recovers_from_no_active_app(self):
        widget = MagicMock()
        type(widget).app = PropertyMock(side_effect=RuntimeError("no active app"))
        assert _resolve_max_header_gap(widget) == MAX_HEADER_GAP_CELLS_FALLBACK

    def test_resolve_max_header_gap_recovers_from_garbage_value(self):
        widget = MagicMock()
        widget.app.get_css_variables.return_value = {"tool-header-max-gap": "garbage"}
        assert _resolve_max_header_gap(widget) == MAX_HEADER_GAP_CELLS_FALLBACK

    def test_resolve_max_header_gap_returns_int_value(self):
        widget = MagicMock()
        widget.app.get_css_variables.return_value = {"tool-header-max-gap": "12"}
        assert _resolve_max_header_gap(widget) == 12
