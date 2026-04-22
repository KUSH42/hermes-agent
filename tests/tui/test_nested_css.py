"""Phase E — TCSS rules for SubAgentPanel / ChildPanel."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from hermes_cli.tui.sub_agent_panel import SubAgentPanel, SubAgentBody


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_panel(depth=0):
    """Properly-initialized SubAgentPanel for CSS class tests."""
    panel = SubAgentPanel(depth=depth)
    panel._header = MagicMock()
    body = MagicMock()
    body.children = []
    panel._body = body
    return panel


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_depth_padding_classes():
    """Depth 1/2/3 panels have correct --depth-N classes; depth 0 has none."""
    p0 = _make_panel(depth=0)
    p1 = _make_panel(depth=1)
    p2 = _make_panel(depth=2)
    p3 = _make_panel(depth=3)

    assert not p0.has_class("--depth-0")
    assert not p0.has_class("--depth-1")
    assert p1.has_class("--depth-1")
    assert not p1.has_class("--depth-2")
    assert p2.has_class("--depth-2")
    assert p3.has_class("--depth-3")


def test_no_children_body_hidden():
    """Without --has-children class, SubAgentPanel does not have it at init."""
    panel = _make_panel()
    assert not panel.has_class("--has-children")


def test_has_children_reveals_body():
    """--has-children class is added after first child."""
    panel = _make_panel()
    panel._body.mount = MagicMock()
    from hermes_cli.tui.child_panel import ChildPanel
    mock_child = MagicMock(spec=ChildPanel)
    mock_child._tool_header = MagicMock()
    panel.add_child_panel(mock_child)
    assert panel.has_class("--has-children")


def test_collapsed_overrides_has_children():
    """Both --collapsed and --has-children: collapsed added by watcher."""
    panel = _make_panel()
    panel._has_children = True
    panel.add_class("--has-children")

    with patch.object(type(panel), "is_mounted", new_callable=lambda: property(lambda _: True)):
        panel.watch_collapsed(True)

    assert panel.has_class("--has-children")
    assert panel.has_class("--collapsed")
    # body.display should be False (collapsed + has_children → still hidden by watcher)
    assert panel._body.display is False


def test_child_compact_body_hidden():
    """ChildPanel with --compact class applied on construction."""
    from hermes_cli.tui.child_panel import ChildPanel
    block = MagicMock()
    block._header = MagicMock()

    panel = ChildPanel(block, tool_name="Grep", depth=1)
    assert panel.has_class("--compact")
    assert panel._compact_mode is True


def test_accessible_border_replaced():
    """SubAgentBody can have -accessible class added."""
    body = SubAgentBody()
    body.add_class("-accessible")
    assert body.has_class("-accessible")
    # CSS: SubAgentBody.-accessible { border-left: none; padding-left: 2; }
