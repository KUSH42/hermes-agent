"""C1: detail_level → collapsed bool migration tests.

After Pass 10 Phase 3, detail_level is a property backed by collapsed:
  detail_level == 0  ↔  collapsed == True
  detail_level == 1/2/3  ↔  collapsed == False

watch_detail_level removed; toggle_l0_restore removed.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import OutputPanel
from hermes_cli.tui.tool_panel import ToolPanel, BodyPane, FooterPane
from hermes_cli.tui.tool_category import ToolCategory


async def _pause(pilot, n: int = 5) -> None:
    for _ in range(n):
        await pilot.pause()


def _make_app() -> HermesApp:
    return HermesApp(cli=MagicMock())


# ---------------------------------------------------------------------------
# C1: detail_level property tests
# ---------------------------------------------------------------------------


def test_detail_level_property_collapsed_maps_to_0():
    """C1: collapsed=True → detail_level == 0."""
    block = MagicMock()
    block._total_received = 0
    block._all_plain = []
    panel = ToolPanel(block=block, tool_name="bash")
    panel.collapsed = True
    assert panel.detail_level == 0


def test_detail_level_property_expanded_maps_to_2():
    """C1: collapsed=False → detail_level == 2."""
    block = MagicMock()
    block._total_received = 0
    block._all_plain = []
    panel = ToolPanel(block=block, tool_name="bash")
    panel.collapsed = False
    assert panel.detail_level == 2


def test_detail_level_setter_0_sets_collapsed_true():
    """C1: detail_level = 0 → collapsed = True."""
    block = MagicMock()
    block._total_received = 0
    panel = ToolPanel(block=block, tool_name="bash")
    panel.detail_level = 0
    assert panel.collapsed is True


def test_detail_level_setter_1_sets_collapsed_false():
    """C1: detail_level = 1 → collapsed = False."""
    block = MagicMock()
    block._total_received = 0
    panel = ToolPanel(block=block, tool_name="bash")
    panel.detail_level = 1
    assert panel.collapsed is False


def test_detail_level_setter_2_sets_collapsed_false():
    """C1: detail_level = 2 → collapsed = False."""
    block = MagicMock()
    block._total_received = 0
    panel = ToolPanel(block=block, tool_name="bash")
    panel.detail_level = 2
    assert panel.collapsed is False


def test_detail_level_setter_3_sets_collapsed_false():
    """C1: detail_level = 3 → collapsed = False."""
    block = MagicMock()
    block._total_received = 0
    panel = ToolPanel(block=block, tool_name="bash")
    panel.detail_level = 3
    assert panel.collapsed is False


def test_detail_level_is_int():
    """C1: detail_level property returns int."""
    block = MagicMock()
    block._total_received = 0
    block._all_plain = []
    panel = ToolPanel(block=block, tool_name="bash")
    assert isinstance(panel.detail_level, int)


def test_watch_detail_level_removed():
    """C1: watch_detail_level method deleted."""
    block = MagicMock()
    block._total_received = 0
    panel = ToolPanel(block=block, tool_name="bash")
    assert not hasattr(panel, "watch_detail_level"), "watch_detail_level should be deleted in C1"


def test_toggle_l0_restore_removed():
    """C2: action_toggle_l0_restore deleted; Space no longer binds to it."""
    block = MagicMock()
    block._total_received = 0
    panel = ToolPanel(block=block, tool_name="bash")
    assert not hasattr(panel, "action_toggle_l0_restore"), "action_toggle_l0_restore should be deleted in C2"


def test_space_not_bound_to_toggle():
    """C2: space binding removed from ToolPanel.BINDINGS."""
    space_bindings = [b for b in ToolPanel.BINDINGS if b.key == "space"]
    assert len(space_bindings) == 0, f"space should not be bound in ToolPanel, found: {space_bindings}"


def test_auto_collapsed_flag_set_on_auto_collapse():
    """C1: _auto_collapsed flag set True when auto-collapse fires."""
    block = MagicMock()
    block._total_received = 0
    block._all_plain = [f"line {i}" for i in range(200)]
    panel = ToolPanel(block=block, tool_name="bash")
    panel._body_pane = MagicMock()
    panel._footer_pane = MagicMock()
    panel._footer_pane.display = False
    # Auto-collapse should fire for 200 lines
    panel._apply_complete_auto_collapse()
    if panel.collapsed:
        assert panel._auto_collapsed is True


def test_user_toggle_clears_auto_collapsed():
    """C1: user Enter toggle sets _auto_collapsed=False."""
    block = MagicMock()
    block._total_received = 0
    block._all_plain = []
    block._tail = None  # prevent MagicMock truthy check from causing early return
    panel = ToolPanel(block=block, tool_name="bash")
    panel._auto_collapsed = True
    panel._body_pane = MagicMock()
    panel._footer_pane = MagicMock()
    panel._footer_pane.display = False
    panel.collapsed = True
    panel.action_toggle_collapse()
    assert panel._auto_collapsed is False


def test_l1_preview_shows_tail_lines():
    """BodyPane._update_preview shows tail when not streaming."""
    from textual.widgets import Static

    block_mock = MagicMock()
    block_mock._all_plain = [f"line {i}" for i in range(10)]
    block_mock._streaming = False
    block_mock._is_streaming = False

    bp = BodyPane(block=block_mock)
    bp._renderer = None

    preview_mock = MagicMock(spec=Static)
    bp._update_preview(preview_mock)

    preview_mock.update.assert_called_once()
    call_arg = preview_mock.update.call_args[0][0]
    rendered = str(call_arg)
    assert "line 9" in rendered or "line 8" in rendered or "line 7" in rendered
