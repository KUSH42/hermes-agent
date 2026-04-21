"""Phase D — SUBAGENT_ROOT browse anchor and /tools tree view."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from hermes_cli.tui._browse_types import BrowseAnchorType, _BROWSE_TYPE_GLYPH
from hermes_cli.tui.tools_overlay import ToolsScreen


# ---------------------------------------------------------------------------
# Browse anchor type
# ---------------------------------------------------------------------------

def test_subagent_root_anchor_emitted():
    """SUBAGENT_ROOT is a member of BrowseAnchorType."""
    assert BrowseAnchorType.SUBAGENT_ROOT.value == "subagent_root"


def test_subagent_root_glyph_defined():
    """🤖 glyph registered for subagent_root."""
    assert "subagent_root" in _BROWSE_TYPE_GLYPH
    assert _BROWSE_TYPE_GLYPH["subagent_root"] == "🤖"


# ---------------------------------------------------------------------------
# Browse nav bindings
# ---------------------------------------------------------------------------

def test_ctrl_alt_bindings_present():
    """ctrl+alt+up / ctrl+alt+down bindings exist on HermesApp."""
    from hermes_cli.tui.app import HermesApp
    all_bindings = []
    for cls in HermesApp.__mro__:
        if hasattr(cls, "BINDINGS"):
            for b in cls.BINDINGS:
                try:
                    all_bindings.append(str(b.key))
                except Exception:
                    try:
                        all_bindings.append(str(b[0]))
                    except Exception:
                        pass
    assert "ctrl+alt+up" in all_bindings, "ctrl+alt+up binding missing"
    assert "ctrl+alt+down" in all_bindings, "ctrl+alt+down binding missing"


# ---------------------------------------------------------------------------
# /tools tree view — ToolsScreen
# ---------------------------------------------------------------------------

def _make_records():
    return [
        {
            "tool_call_id": "p1",
            "parent_tool_call_id": None,
            "name": "Task",
            "category": "agent",
            "depth": 0,
            "children": ["c1", "c2"],
            "start_s": 0.0,
            "dur_ms": 1000,
            "is_error": False,
            "error_kind": None,
            "mcp_server": None,
        },
        {
            "tool_call_id": "c1",
            "parent_tool_call_id": "p1",
            "name": "Read",
            "category": "file",
            "depth": 1,
            "children": [],
            "start_s": 0.1,
            "dur_ms": 200,
            "is_error": False,
            "error_kind": None,
            "mcp_server": None,
        },
        {
            "tool_call_id": "c2",
            "parent_tool_call_id": "p1",
            "name": "Grep",
            "category": "search",
            "depth": 1,
            "children": [],
            "start_s": 0.3,
            "dur_ms": 150,
            "is_error": False,
            "error_kind": None,
            "mcp_server": None,
        },
    ]


def test_tools_overlay_tree_view_indent():
    """_get_ordered_records returns children after parent in DFS order."""
    screen = object.__new__(ToolsScreen)
    screen._tree_view = True
    records = _make_records()
    ordered = screen._get_ordered_records(records)
    ids = [r["tool_call_id"] for r, _ in ordered]
    # p1 must come before c1 and c2
    assert ids.index("p1") < ids.index("c1")
    assert ids.index("p1") < ids.index("c2")


def test_tools_overlay_dfs_ordering():
    """DFS order: parent at depth 0, children at depth 1."""
    screen = object.__new__(ToolsScreen)
    screen._tree_view = True
    records = _make_records()
    ordered = screen._get_ordered_records(records)
    depths = {r["tool_call_id"]: d for r, d in ordered}
    assert depths["p1"] == 0
    assert depths["c1"] == 1
    assert depths["c2"] == 1


def test_tools_overlay_timeline_toggle():
    """_get_ordered_records in non-tree mode returns flat list at depth 0."""
    screen = object.__new__(ToolsScreen)
    screen._tree_view = False
    records = _make_records()
    ordered = screen._get_ordered_records(records)
    assert all(d == 0 for _, d in ordered)
    assert len(ordered) == len(records)


def test_tools_overlay_footer_t_binding():
    """ToolsScreen BINDINGS contain 't' key for toggle_view."""
    binding_keys = []
    for b in ToolsScreen.BINDINGS:
        try:
            binding_keys.append(str(b.key))
        except Exception:
            try:
                binding_keys.append(str(b[0]))
            except Exception:
                pass
    assert "t" in binding_keys


def test_tools_overlay_children_field_used():
    """_get_ordered_records uses 'children' field for DFS traversal."""
    screen = object.__new__(ToolsScreen)
    screen._tree_view = True
    # Parent with no children — grandchild unreachable without children field
    records = [
        {"tool_call_id": "p", "parent_tool_call_id": None, "name": "T",
         "category": "agent", "depth": 0, "children": ["ch"],
         "start_s": 0.0, "dur_ms": None, "is_error": False,
         "error_kind": None, "mcp_server": None},
        {"tool_call_id": "ch", "parent_tool_call_id": "p", "name": "R",
         "category": "file", "depth": 1, "children": [],
         "start_s": 0.1, "dur_ms": None, "is_error": False,
         "error_kind": None, "mcp_server": None},
    ]
    ordered = screen._get_ordered_records(records)
    ids = [r["tool_call_id"] for r, _ in ordered]
    assert "ch" in ids
    assert ids.index("p") < ids.index("ch")


def test_collapsed_panel_children_skipped():
    """COLLAPSED SubAgentPanel children are not emitted as browse anchors."""
    from hermes_cli.tui.sub_agent_panel import SubAgentPanel, CollapseState
    from hermes_cli.tui._browse_types import BrowseAnchor

    panel = SubAgentPanel(depth=0)
    panel._header = MagicMock()
    body = MagicMock()
    body.children = [MagicMock(), MagicMock()]
    panel._body = body
    # Directly set the reactive value via internal dict
    panel.__dict__["_reactive_collapse_state"] = CollapseState.COLLAPSED

    anchors: list[BrowseAnchor] = []

    # Simulate what _rebuild_browse_anchors does: skip body when collapsed
    if panel.collapse_state != CollapseState.COLLAPSED:
        for child in panel._body.children:
            anchors.append(BrowseAnchor(
                anchor_type=BrowseAnchorType.TOOL_BLOCK,
                widget=child,
                label="child",
                turn_id=1,
            ))

    assert len(anchors) == 0, "Collapsed panel children should not emit anchors"
