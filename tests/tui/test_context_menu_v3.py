"""Phase D tests: force_renderer for each ResultKind (context menu re-render).

8 tests.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from hermes_cli.tui.tool_panel import ToolPanel
from hermes_cli.tui.tool_payload import ResultKind


def _make_panel(tool_name: str = "bash") -> ToolPanel:
    block_mock = MagicMock()
    block_mock._total_received = 0
    block_mock._all_plain = ["output line 1", "output line 2"]
    panel = ToolPanel(block=block_mock, tool_name=tool_name)
    panel._header_bar = None
    panel._body_pane = None
    panel._tool_args = {}
    return panel


def test_force_renderer_code_kind():
    p = _make_panel()
    p.force_renderer(ResultKind.CODE)
    assert p._forced_renderer_kind == ResultKind.CODE


def test_force_renderer_diff_kind():
    p = _make_panel()
    p.force_renderer(ResultKind.DIFF)
    assert p._forced_renderer_kind == ResultKind.DIFF


def test_force_renderer_search_kind():
    p = _make_panel()
    p.force_renderer(ResultKind.SEARCH)
    assert p._forced_renderer_kind == ResultKind.SEARCH


def test_force_renderer_json_kind():
    p = _make_panel()
    p.force_renderer(ResultKind.JSON)
    assert p._forced_renderer_kind == ResultKind.JSON


def test_force_renderer_log_kind():
    p = _make_panel()
    p.force_renderer(ResultKind.LOG)
    assert p._forced_renderer_kind == ResultKind.LOG


def test_force_renderer_table_kind():
    p = _make_panel()
    p.force_renderer(ResultKind.TABLE)
    assert p._forced_renderer_kind == ResultKind.TABLE


def test_force_renderer_stores_forced_kind():
    """Verify _forced_renderer_kind is always set regardless of swap success."""
    p = _make_panel("grep")
    p.force_renderer(ResultKind.LOG)
    assert p._forced_renderer_kind == ResultKind.LOG


def test_force_renderer_unknown_kind_no_crash():
    """TEXT kind should not crash force_renderer."""
    p = _make_panel()
    p.force_renderer(ResultKind.TEXT)
    assert p._forced_renderer_kind == ResultKind.TEXT
