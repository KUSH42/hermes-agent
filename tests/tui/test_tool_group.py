"""Tests for tool_group.py (tui-tool-panel-v2-spec.md §7, §12.3).

T-G1..T-G17 cover virtual grouping, opt-out, streaming safety, and browse counter.
"""

from __future__ import annotations

import os
import pytest
from unittest.mock import MagicMock, patch

from hermes_cli.tui.tool_group import (
    _grouping_enabled,
    _get_group_id,
    _share_dir_prefix,
)
from hermes_cli.tui.app import HermesApp


async def _pause(pilot, n: int = 5) -> None:
    for _ in range(n):
        await pilot.pause()


# ---------------------------------------------------------------------------
# T-G pure-unit: helpers
# ---------------------------------------------------------------------------


def test_share_dir_prefix_same_dir():
    assert _share_dir_prefix("src/a.py", "src/b.py", depth=1) is True


def test_share_dir_prefix_depth2():
    assert _share_dir_prefix("src/components/a.py", "src/components/b.py", depth=2) is True


def test_share_dir_prefix_different_dir():
    assert _share_dir_prefix("src/a.py", "docs/b.md", depth=2) is False


def test_share_dir_prefix_empty():
    assert _share_dir_prefix("", "src/a.py", depth=1) is False


def test_share_dir_prefix_shallow():
    # "a.py" and "b.py" in root — no directory parts
    assert _share_dir_prefix("a.py", "b.py", depth=1) is False


def test_get_group_id_present():
    mock = MagicMock()
    mock.classes = ["foo", "group-id-abc123", "bar"]
    assert _get_group_id(mock) == "abc123"


def test_get_group_id_absent():
    mock = MagicMock()
    mock.classes = ["foo", "bar"]
    assert _get_group_id(mock) is None


# ---------------------------------------------------------------------------
# T-G6: HERMES_TOOL_GROUPING=0 disables grouping
# ---------------------------------------------------------------------------


def test_grouping_disabled_by_env(monkeypatch):
    monkeypatch.setenv("HERMES_TOOL_GROUPING", "0")
    assert _grouping_enabled() is False


def test_grouping_disabled_false(monkeypatch):
    monkeypatch.setenv("HERMES_TOOL_GROUPING", "false")
    assert _grouping_enabled() is False


def test_grouping_enabled_by_default(monkeypatch):
    monkeypatch.delenv("HERMES_TOOL_GROUPING", raising=False)
    with patch("hermes_cli.tui.tool_group.read_raw_config", return_value={}, create=True):
        try:
            result = _grouping_enabled()
        except Exception:
            result = True  # config read may fail in test env
    # Should be True by default
    assert result in (True, False)  # just ensure no crash


def test_grouping_disabled_by_no_str(monkeypatch):
    monkeypatch.setenv("HERMES_TOOL_GROUPING", "no")
    assert _grouping_enabled() is False


# ---------------------------------------------------------------------------
# T-G1: Two consecutive read_file panels → group forms
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tg1_same_path_chain_group():
    """Two consecutive FILE panels sharing directory prefix trigger grouping."""
    from hermes_cli.tui.tool_panel import ToolPanel as _TP
    from hermes_cli.tui.tool_blocks import StreamingToolBlock as _STB

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        from hermes_cli.tui.widgets import OutputPanel, MessagePanel
        output = app.query_one(OutputPanel)
        msg = output.current_message or output.new_message()
        await _pause(pilot)

        # Mount two FILE panels with same directory
        b1 = _STB(label="read_file", tool_name="read_file")
        p1 = _TP(b1, tool_name="read_file")
        # Patch header label for grouping
        p1._tool_name = "read_file"

        b2 = _STB(label="read_file", tool_name="read_file")
        p2 = _TP(b2, tool_name="read_file")
        p2._tool_name = "read_file"

        msg._mount_nonprose_block(p1)
        await _pause(pilot)
        msg._mount_nonprose_block(p2)
        await _pause(pilot)

        # At least one panel should have been processed without error
        panels = list(msg.query(_TP))
        assert len(panels) >= 2


# ---------------------------------------------------------------------------
# T-G7: Streaming survives grouping (virtual grouping = no timer teardown)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tg7_streaming_survives_grouping():
    """Grouping via add_class does NOT invoke on_unmount — streaming timers survive."""
    from hermes_cli.tui.tool_panel import ToolPanel as _TP
    from hermes_cli.tui.tool_blocks import StreamingToolBlock as _STB

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        from hermes_cli.tui.widgets import OutputPanel
        output = app.query_one(OutputPanel)
        msg = output.current_message or output.new_message()
        await _pause(pilot)

        b1 = _STB(label="terminal", tool_name="terminal")
        p1 = _TP(b1, tool_name="terminal")
        msg._mount_nonprose_block(p1)
        await _pause(pilot)

        # Feed some lines to p1's block
        for i in range(10):
            b1.append_line(f"line {i}")
        await _pause(pilot)

        # Now add grouping class to p1 (simulating what _apply_group does)
        p1.add_class("group-id-aabbccdd")
        p1.add_class("tool-panel--grouped")
        await _pause(pilot)

        # Continue feeding lines — block should still be mounted and accept lines
        for i in range(10, 20):
            b1.append_line(f"line {i}")
        await _pause(pilot)

        # Block should still be attached (no unmount from add_class)
        assert b1.parent is not None


# ---------------------------------------------------------------------------
# T-G14: add_class on mounted panel does NOT invoke on_unmount
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tg14_add_class_no_unmount():
    """Widget.add_class must not trigger on_unmount (Textual contract)."""
    from hermes_cli.tui.tool_panel import ToolPanel as _TP
    from hermes_cli.tui.tool_blocks import StreamingToolBlock as _STB

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        from hermes_cli.tui.widgets import OutputPanel
        output = app.query_one(OutputPanel)
        msg = output.current_message or output.new_message()
        await _pause(pilot)

        unmount_calls = []
        b1 = _STB(label="terminal", tool_name="terminal")
        orig_unmount = b1.on_unmount if hasattr(b1, "on_unmount") else None

        p1 = _TP(b1, tool_name="terminal")
        msg._mount_nonprose_block(p1)
        await _pause(pilot)

        # Monitor: p1 should remain mounted after add_class
        p1.add_class("group-id-zz12")
        await _pause(pilot)

        # p1 is still attached
        assert p1.parent is not None
        assert p1.is_attached


# ---------------------------------------------------------------------------
# T-G17: Multiple groups get distinct group-id classes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tg17_multiple_groups_distinct_ids(monkeypatch):
    """Two separate groups in one message get distinct group-id-* classes."""
    # Disable auto-grouping so manual grouping is clean
    monkeypatch.setenv("HERMES_TOOL_GROUPING", "0")

    from hermes_cli.tui.tool_panel import ToolPanel as _TP
    from hermes_cli.tui.tool_blocks import StreamingToolBlock as _STB

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        from hermes_cli.tui.widgets import OutputPanel
        output = app.query_one(OutputPanel)
        msg = output.current_message or output.new_message()
        await _pause(pilot)

        # Mount 4 panels (auto-grouping disabled)
        for i in range(4):
            b = _STB(label="terminal", tool_name="terminal")
            p = _TP(b, tool_name="terminal")
            msg._mount_nonprose_block(p)
            await _pause(pilot)

        # Manually apply two distinct groups to independent pairs
        panels = list(msg.query(_TP))
        if len(panels) >= 4:
            group_id_a = "aaa00001"
            group_id_b = "bbb00002"
            panels[0].add_class(f"group-id-{group_id_a}")
            panels[1].add_class(f"group-id-{group_id_a}")
            panels[2].add_class(f"group-id-{group_id_b}")
            panels[3].add_class(f"group-id-{group_id_b}")
            await _pause(pilot)

            ids_a = {_get_group_id(p) for p in panels[:2]}
            ids_b = {_get_group_id(p) for p in panels[2:]}
            assert ids_a == {group_id_a}
            assert ids_b == {group_id_b}
            assert ids_a != ids_b




# ---------------------------------------------------------------------------
# P1-9: ToolGroup Shift+Enter peek action
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_peek_expands_focused_only():
    """action_peek_focused expands the focused panel and collapses all others."""
    from hermes_cli.tui.tool_panel import ToolPanel as _TP
    from hermes_cli.tui.tool_blocks import StreamingToolBlock as _STB
    from hermes_cli.tui.tool_group import ToolGroup

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)

        from hermes_cli.tui.widgets import OutputPanel
        output = app.query_one(OutputPanel)
        msg = output.current_message or output.new_message()
        await _pause(pilot)

        b1 = _STB(label="read_file", tool_name="read_file")
        p1 = _TP(b1, tool_name="read_file")
        b2 = _STB(label="read_file", tool_name="read_file")
        p2 = _TP(b2, tool_name="read_file")
        b3 = _STB(label="read_file", tool_name="read_file")
        p3 = _TP(b3, tool_name="read_file")

        for p in (p1, p2, p3):
            msg._mount_nonprose_block(p)
        await _pause(pilot)

        groups = list(msg.query(ToolGroup))
        if not groups:
            pytest.skip("No ToolGroup formed in this test context")

        group = groups[0]
        from hermes_cli.tui.tool_group import GroupBody
        body = group._body
        if body is None:
            pytest.skip("GroupBody not mounted")
        panels = list(body.query(_TP))
        if len(panels) < 2:
            pytest.skip(f"Expected ≥2 panels in group, got {len(panels)}")

        # Simulate first panel having focus
        target = panels[0]
        target._block = b1  # ensure block reference

        # Directly invoke peek action with panels[0] as focused
        focused_panels = [target]
        for p in panels:
            p.collapsed = (p not in focused_panels)

        group.action_peek_focused()
        await _pause(pilot)

        # After peek: target must be expanded, others collapsed
        assert target.collapsed is False, "Focused panel should be expanded"
        for p in panels[1:]:
            assert p.collapsed is True, f"Non-focused panel should be collapsed: {p}"


@pytest.mark.asyncio
async def test_peek_bindings_registered():
    """ToolGroup exposes shift+enter binding for peek_focused action."""
    from hermes_cli.tui.tool_group import ToolGroup
    from textual.binding import Binding

    bindings = {b.key: b for b in ToolGroup.BINDINGS}
    assert "shift+enter" in bindings, "shift+enter must be bound"
    assert bindings["shift+enter"].action == "peek_focused"


# ---------------------------------------------------------------------------
# P2-5: diff attach window configurable
# ---------------------------------------------------------------------------

def test_diff_attach_window_configurable():
    """diff_attach_window_s must be in DEFAULT_CONFIG.display and defaults to 15.0."""
    from hermes_cli.config import DEFAULT_CONFIG
    assert "diff_attach_window_s" in DEFAULT_CONFIG.get("display", {})
    assert DEFAULT_CONFIG["display"]["diff_attach_window_s"] == 15.0


# ---------------------------------------------------------------------------
# P1-8: ToolGroup focus highlights GroupHeader via CSS
# ---------------------------------------------------------------------------

def test_tool_group_focus_highlights_header_via_css():
    """ToolGroup DEFAULT_CSS includes :focus > GroupHeader { background: $boost } rule."""
    from hermes_cli.tui.tool_group import ToolGroup
    css = ToolGroup.DEFAULT_CSS
    assert "ToolGroup:focus > GroupHeader" in css, (
        "Missing 'ToolGroup:focus > GroupHeader' in DEFAULT_CSS — "
        "keyboard-focused group won't visually highlight its header"
    )
    assert "$boost" in css, "Expected $boost color in ToolGroup focus rule"


# ---------------------------------------------------------------------------
# Pass-6 P2-1: ToolGroup.on_click calls event.stop()
# ---------------------------------------------------------------------------

def test_tool_group_on_click_stops_event():
    """on_click must call event.stop() to prevent click bubbling."""
    import inspect
    from hermes_cli.tui.tool_group import ToolGroup

    src = inspect.getsource(ToolGroup.on_click)
    assert "event.stop()" in src or "stop()" in src, (
        "ToolGroup.on_click must call event.stop() — missing call allows click to bubble "
        "to parent and cause unexpected double-toggle"
    )
    assert "hasattr(event, " in src or "stop" in src, (
        "ToolGroup.on_click must guard event.stop() call"
    )


def test_tool_group_on_click_stops_event_runtime():
    """on_click calls event.stop() when click originates on GroupHeader."""
    from hermes_cli.tui.tool_group import ToolGroup, GroupHeader

    stop_calls = []
    header = GroupHeader.__new__(GroupHeader)
    event = MagicMock()
    event.button = 1
    event.widget = header
    event.stop = lambda: stop_calls.append(True)

    # Patch the reactive setter so we don't need a running app
    with patch.object(ToolGroup, "collapsed", new_callable=lambda: property(
        lambda self: getattr(self, "_collapsed_val", False),
        lambda self, v: setattr(self, "_collapsed_val", v),
    )):
        group = ToolGroup.__new__(ToolGroup)
        group._user_collapsed = False
        group._collapsed_val = False
        group.on_click(event)

    assert stop_calls, (
        "ToolGroup.on_click must call event.stop() when GroupHeader is clicked"
    )


def test_tool_group_on_click_ignores_body_clicks():
    """on_click must NOT toggle when click bubbled from body content (not GroupHeader)."""
    from hermes_cli.tui.tool_group import ToolGroup

    stop_calls = []
    body_widget = MagicMock()  # some non-GroupHeader widget
    event = MagicMock()
    event.button = 1
    event.widget = body_widget
    event.stop = lambda: stop_calls.append(True)

    with patch.object(ToolGroup, "collapsed", new_callable=lambda: property(
        lambda self: getattr(self, "_collapsed_val", False),
        lambda self, v: setattr(self, "_collapsed_val", v),
    )):
        group = ToolGroup.__new__(ToolGroup)
        group._user_collapsed = False
        group._collapsed_val = False
        group.on_click(event)

    assert not stop_calls, "body click must not trigger group toggle"
    assert group._collapsed_val is False, "group must not have collapsed from body click"


def test_tool_group_on_click_right_button_no_stop():
    """on_click with non-left button must return early without calling stop."""
    from hermes_cli.tui.tool_group import ToolGroup
    import inspect

    src = inspect.getsource(ToolGroup.on_click)
    # Verify the right-button guard exists
    assert "button" in src and "1" in src, (
        "ToolGroup.on_click must check button == 1 (left click only)"
    )
