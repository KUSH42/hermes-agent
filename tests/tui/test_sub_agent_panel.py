"""Phase B — SubAgentPanel, SubAgentHeader, SubAgentBody widget tests."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from hermes_cli.tui.sub_agent_panel import (
    SubAgentBody,
    SubAgentHeader,
    SubAgentPanel,
)
from hermes_cli.tui.child_panel import ChildPanel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_child_mock():
    """MagicMock(spec=ChildPanel) — isinstance checks pass."""
    mock = MagicMock(spec=ChildPanel)
    mock._tool_header = MagicMock()
    return mock


def _make_unit_panel(depth=0):
    """Properly-initialized SubAgentPanel for pure unit tests (no TUI app)."""
    panel = SubAgentPanel(depth=depth)  # calls Widget.__init__ — sets up reactives
    panel._header = MagicMock()
    body = MagicMock()
    body.children = []
    panel._body = body
    return panel


async def _pause(pilot, n: int = 3) -> None:
    for _ in range(n):
        await pilot.pause()


# ---------------------------------------------------------------------------
# Binary collapse model
# ---------------------------------------------------------------------------

def test_no_collapse_state_enum():
    """CollapseState enum was retired — binary collapsed: bool is the model."""
    import hermes_cli.tui.sub_agent_panel as m
    assert not hasattr(m, "CollapseState")


def test_collapsed_reactive_exists():
    assert hasattr(SubAgentPanel, "collapsed")


# ---------------------------------------------------------------------------
# SubAgentPanel — compose / DOM structure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subagent_panel_compose():
    """Both header and body are mounted in DOM after compose."""
    from hermes_cli.tui.app import HermesApp
    app = HermesApp(cli=MagicMock())
    async with app.run_test() as pilot:
        panel = SubAgentPanel()
        await app.mount(panel)
        await _pause(pilot)
        assert panel.query_one(SubAgentHeader) is panel._header
        assert panel.query_one(SubAgentBody) is panel._body


@pytest.mark.asyncio
async def test_toggle_collapse_flips_bool():
    """action_toggle_collapse flips collapsed bool each call."""
    from hermes_cli.tui.app import HermesApp
    app = HermesApp(cli=MagicMock())
    async with app.run_test() as pilot:
        panel = SubAgentPanel()
        await app.mount(panel)
        await _pause(pilot)

        assert panel.collapsed is False
        panel.action_toggle_collapse()
        assert panel.collapsed is True
        panel.action_toggle_collapse()
        assert panel.collapsed is False


@pytest.mark.asyncio
async def test_collapsed_hides_body():
    """`collapsed=True` → `_body.display == False`."""
    from hermes_cli.tui.app import HermesApp
    app = HermesApp(cli=MagicMock())
    async with app.run_test() as pilot:
        panel = SubAgentPanel()
        await app.mount(panel)
        await _pause(pilot)
        panel._has_children = True
        panel.add_class("--has-children")
        panel.collapsed = True
        await _pause(pilot)
        assert panel._body.display is False


@pytest.mark.asyncio
async def test_collapsed_css_class_added():
    """--collapsed CSS class added when collapsed=True, removed on expand."""
    from hermes_cli.tui.app import HermesApp
    app = HermesApp(cli=MagicMock())
    async with app.run_test() as pilot:
        panel = SubAgentPanel()
        await app.mount(panel)
        await _pause(pilot)
        panel._has_children = True
        panel.add_class("--has-children")
        panel.collapsed = True
        await _pause(pilot)
        assert panel.has_class("--collapsed")
        panel.collapsed = False
        await _pause(pilot)
        assert not panel.has_class("--collapsed")


# ---------------------------------------------------------------------------
# SubAgentPanel — child management
# ---------------------------------------------------------------------------


def test_add_child_increments_count():
    """`child_count` increments after `add_child_panel`."""
    panel = _make_unit_panel()
    mock_child = _make_child_mock()
    panel._body.mount = MagicMock()

    assert panel.child_count == 0
    panel.add_child_panel(mock_child)
    assert panel.child_count == 1


def test_has_children_class_added():
    """--has-children absent at init, present after first child."""
    panel = _make_unit_panel()
    panel._body.mount = MagicMock()

    assert not panel.has_class("--has-children")
    panel.add_child_panel(_make_child_mock())
    assert panel.has_class("--has-children")


def test_last_child_gutter_flag():
    """After 2 children: first._is_child_last=False, second._is_child_last=True."""
    panel = _make_unit_panel()
    child1 = _make_child_mock()
    child2 = _make_child_mock()

    body_children = []
    panel._body.children = body_children
    panel._body.mount = MagicMock(side_effect=body_children.append)

    panel.add_child_panel(child1)
    panel.add_child_panel(child2)

    assert child1._tool_header._is_child_last is False
    assert child2._tool_header._is_child_last is True


def test_prev_last_updated_on_new_child():
    """Adding a 3rd child updates 2nd to _is_child_last=False."""
    panel = _make_unit_panel()
    children = []
    panel._body.children = children
    panel._body.mount = MagicMock(side_effect=children.append)

    c1, c2, c3 = _make_child_mock(), _make_child_mock(), _make_child_mock()
    panel.add_child_panel(c1)
    panel.add_child_panel(c2)
    assert c2._tool_header._is_child_last is True
    panel.add_child_panel(c3)
    assert c2._tool_header._is_child_last is False
    assert c3._tool_header._is_child_last is True


# ---------------------------------------------------------------------------
# Completion tracking
# ---------------------------------------------------------------------------

def test_error_count_increments():
    """error_count increments on error child completion."""
    panel = _make_unit_panel()
    panel._completed_child_count = 0
    panel._open_time = 0.0

    with patch("hermes_cli.tui.sub_agent_panel._time") as mock_t:
        mock_t.monotonic.return_value = 1.0
        panel._notify_child_complete("tid", True, 500)

    assert panel.error_count == 1


def test_completed_child_count_tracks_completions():
    """_completed_child_count increments on each _notify_child_complete call."""
    panel = _make_unit_panel()
    panel._completed_child_count = 0
    panel._open_time = 0.0

    with patch("hermes_cli.tui.sub_agent_panel._time") as mock_t:
        mock_t.monotonic.return_value = 1.0
        panel._notify_child_complete("c1", False, 100)
        panel._notify_child_complete("c2", False, 200)

    assert panel._completed_child_count == 2


def test_subtree_done_when_all_complete():
    """subtree_done=True when _completed_child_count >= child_count."""
    panel = _make_unit_panel()
    panel._completed_child_count = 0
    panel._open_time = 0.0
    panel.child_count = 2  # reactive — widget already __init__'d

    with patch("hermes_cli.tui.sub_agent_panel._time") as mock_t:
        mock_t.monotonic.return_value = 1.0
        panel._notify_child_complete("c1", False, 100)
        assert panel.subtree_done is False
        panel._notify_child_complete("c2", False, 200)
        assert panel.subtree_done is True


def test_set_result_summary_v4_marks_done():
    """set_result_summary_v4 sets subtree_done=True."""
    panel = _make_unit_panel()

    summary = MagicMock()
    summary.is_error = False
    panel.set_result_summary_v4(summary)
    assert panel.subtree_done is True
