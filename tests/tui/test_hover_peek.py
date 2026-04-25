"""Phase D tests: messages module, PathClicked, ToolRerunRequested, force_renderer.

8 tests.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


def test_messages_module_importable():
    import hermes_cli.tui.messages as m
    assert hasattr(m, "ToolRerunRequested")
    assert hasattr(m, "PathClicked")


def test_path_clicked_message_has_path():
    from hermes_cli.tui.messages import PathClicked
    msg = PathClicked(path="/tmp/foo.txt")
    assert msg.path == "/tmp/foo.txt"


def test_path_clicked_message_has_absolute_flag():
    from hermes_cli.tui.messages import PathClicked
    msg = PathClicked(path="/tmp/foo.txt", absolute=True)
    assert msg.absolute is True


def test_path_clicked_message_default_absolute_false():
    from hermes_cli.tui.messages import PathClicked
    msg = PathClicked(path="relative/path.txt")
    assert msg.absolute is False


def test_tool_rerun_requested_has_panel():
    from hermes_cli.tui.messages import ToolRerunRequested
    panel_mock = MagicMock()
    msg = ToolRerunRequested(panel=panel_mock)
    assert msg.panel is panel_mock


def test_force_renderer_stores_forced_kind():
    """force_renderer stores the kind even when body swap fails."""
    from types import SimpleNamespace
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.tool_payload import ResultKind
    from hermes_cli.tui.tool_panel.density import DensityTier
    from hermes_cli.tui.services.tools import ToolCallState

    block_mock = MagicMock()
    block_mock._total_received = 0

    panel = ToolPanel(block=block_mock, tool_name="bash")
    panel._view_state = SimpleNamespace(
        state=ToolCallState.DONE,
        kind=None,
        density=DensityTier.DEFAULT,
        user_kind_override=None,
    )
    # _header_bar may be None pre-compose; force_renderer should not crash
    panel._header_bar = None
    panel._body_pane = None
    panel._tool_args = {}
    panel._block = block_mock

    panel.force_renderer(ResultKind.CODE)
    assert panel._view_state.user_kind_override == ResultKind.CODE


def test_force_renderer_unknown_kind_no_crash():
    """force_renderer with any ResultKind never raises."""
    from types import SimpleNamespace
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.tool_payload import ResultKind
    from hermes_cli.tui.tool_panel.density import DensityTier
    from hermes_cli.tui.services.tools import ToolCallState

    block_mock = MagicMock()
    block_mock._total_received = 0

    panel = ToolPanel(block=block_mock, tool_name="bash")
    panel._view_state = SimpleNamespace(
        state=ToolCallState.DONE,
        kind=None,
        density=DensityTier.DEFAULT,
        user_kind_override=None,
    )
    panel._header_bar = None
    panel._body_pane = None
    panel._tool_args = {}

    for kind in ResultKind:
        panel.force_renderer(kind)  # must not raise


def test_force_renderer_fallback_on_error():
    """force_renderer swallows all exceptions gracefully."""
    from types import SimpleNamespace
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.tool_payload import ResultKind
    from hermes_cli.tui.tool_panel.density import DensityTier
    from hermes_cli.tui.services.tools import ToolCallState

    block_mock = MagicMock()
    block_mock._total_received = 0

    panel = ToolPanel(block=block_mock, tool_name="bash")
    panel._view_state = SimpleNamespace(
        state=ToolCallState.DONE,
        kind=None,
        density=DensityTier.DEFAULT,
        user_kind_override=None,
    )
    panel._header_bar = MagicMock()
    panel._body_pane = None  # will cause AttributeError in _swap_renderer
    panel._tool_args = {}
    panel._block = MagicMock()
    panel._block._all_plain = ["line1"]

    # Should not raise
    panel.force_renderer(ResultKind.DIFF)
    assert panel._view_state.user_kind_override == ResultKind.DIFF
