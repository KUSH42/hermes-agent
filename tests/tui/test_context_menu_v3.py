"""Phase D tests: force_renderer for each ResultKind (context menu re-render).

8 tests. Migrated for KO-4: assertions now read view.user_kind_override.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from hermes_cli.tui.tool_panel import ToolPanel
from hermes_cli.tui.tool_payload import ResultKind
from hermes_cli.tui.tool_panel.density import DensityTier
from hermes_cli.tui.services.tools import ToolCallState


def _attach_view_stub(panel: ToolPanel, *, state: ToolCallState = ToolCallState.DONE) -> ToolPanel:
    panel._view_state = SimpleNamespace(
        state=state,
        kind=None,
        density=DensityTier.DEFAULT,
        user_kind_override=None,
    )
    return panel


def _make_panel(tool_name: str = "bash") -> ToolPanel:
    block_mock = MagicMock()
    block_mock._total_received = 0
    block_mock._all_plain = ["output line 1", "output line 2"]
    panel = ToolPanel(block=block_mock, tool_name=tool_name)
    panel._header_bar = None
    panel._body_pane = None
    panel._tool_args = {}
    return _attach_view_stub(panel)


def test_force_renderer_code_kind():
    p = _make_panel()
    p.force_renderer(ResultKind.CODE)
    assert p._view_state.user_kind_override == ResultKind.CODE


def test_force_renderer_diff_kind():
    p = _make_panel()
    p.force_renderer(ResultKind.DIFF)
    assert p._view_state.user_kind_override == ResultKind.DIFF


def test_force_renderer_search_kind():
    p = _make_panel()
    p.force_renderer(ResultKind.SEARCH)
    assert p._view_state.user_kind_override == ResultKind.SEARCH


def test_force_renderer_json_kind():
    p = _make_panel()
    p.force_renderer(ResultKind.JSON)
    assert p._view_state.user_kind_override == ResultKind.JSON


def test_force_renderer_log_kind():
    p = _make_panel()
    p.force_renderer(ResultKind.LOG)
    assert p._view_state.user_kind_override == ResultKind.LOG


def test_force_renderer_table_kind():
    p = _make_panel()
    p.force_renderer(ResultKind.TABLE)
    assert p._view_state.user_kind_override == ResultKind.TABLE


def test_force_renderer_stores_forced_kind():
    """Verify view.user_kind_override is always set regardless of swap success."""
    p = _make_panel("grep")
    p.force_renderer(ResultKind.LOG)
    assert p._view_state.user_kind_override == ResultKind.LOG


def test_force_renderer_unknown_kind_no_crash():
    """TEXT kind should not crash force_renderer."""
    p = _make_panel()
    p.force_renderer(ResultKind.TEXT)
    assert p._view_state.user_kind_override == ResultKind.TEXT
