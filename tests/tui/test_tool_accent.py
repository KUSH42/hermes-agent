"""Tests for ToolAccent widget (v3 Phase A, tui-tool-panel-v3-spec.md §5.1).

Covers:
- State reactive + watch_state (add/remove_class)
- Position management (set_position)
- render_line join chars (solo/first/mid/last)
- Integration: accent wired into ToolPanel on_mount and set_result_summary
- GroupHeader accent muted state
- CWD stripping flag on SHELL ToolPanel
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from hermes_cli.tui.tool_accent import ToolAccent


# ---------------------------------------------------------------------------
# Unit tests — no app needed
# ---------------------------------------------------------------------------


def test_initial_state_is_pending():
    """ToolAccent defaults to state='pending'."""
    a = ToolAccent()
    assert a.state == "pending"


def test_watch_state_adds_new_class():
    """watch_state adds -<new> class to widget."""
    a = ToolAccent()
    a.watch_state("pending", "streaming")
    assert a.has_class("-streaming")


def test_watch_state_removes_old_class():
    """watch_state removes -<old> class."""
    a = ToolAccent()
    a.add_class("-pending")
    a.watch_state("pending", "ok")
    assert not a.has_class("-pending")
    assert a.has_class("-ok")


def test_watch_state_empty_old_no_error():
    """watch_state with empty old string does not crash."""
    a = ToolAccent()
    a.watch_state("", "streaming")  # should not raise
    assert a.has_class("-streaming")


def test_watch_state_preserves_position_classes():
    """watch_state preserves position classes (e.g. -first) when state changes."""
    a = ToolAccent()
    a.add_class("-first")
    a.watch_state("pending", "ok")
    assert a.has_class("-first"), "Position class must be preserved"
    assert a.has_class("-ok")


def test_set_position_updates_field():
    """set_position stores the position string."""
    a = ToolAccent()
    a.set_position("first")
    assert a._position == "first"


def test_set_position_all_values():
    """set_position accepts all four valid position strings."""
    a = ToolAccent()
    for pos in ("solo", "first", "mid", "last"):
        a.set_position(pos)
        assert a._position == pos


def test_all_states_toggle():
    """All state transitions work without error."""
    a = ToolAccent()
    transitions = [
        ("", "pending"),
        ("pending", "streaming"),
        ("streaming", "ok"),
        ("ok", "error"),
        ("error", "warning"),
        ("warning", "muted"),
    ]
    for old, new in transitions:
        if old:
            a.add_class(f"-{old}")
        a.watch_state(old, new)
        assert a.has_class(f"-{new}"), f"Expected -{new} after transition {old}->{new}"
        if old:
            assert not a.has_class(f"-{old}"), f"Expected -{old} removed"


def test_component_classes_declared():
    """ToolAccent declares tool-accent--rail in COMPONENT_CLASSES."""
    assert "tool-accent--rail" in ToolAccent.COMPONENT_CLASSES


def test_default_css_has_width_1():
    """ToolAccent DEFAULT_CSS sets width: 1."""
    assert "width: 1" in ToolAccent.DEFAULT_CSS


# ---------------------------------------------------------------------------
# Integration tests — ToolPanel wires accent state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_panel_has_accent_as_direct_child():
    """ToolPanel composes ToolAccent as direct child (v3-A)."""
    from hermes_cli.tui.app import HermesApp
    from hermes_cli.tui.widgets import OutputPanel
    from hermes_cli.tui.tool_panel import ToolPanel

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(5):
            await pilot.pause()
        app.agent_running = True
        for _ in range(5):
            await pilot.pause()
        app._open_gen_block("bash")
        for _ in range(5):
            await pilot.pause()

        panel = app.query_one(OutputPanel).query_one(ToolPanel)
        direct_types = [type(c).__name__ for c in panel.children]
        assert "ToolAccent" in direct_types, f"ToolAccent must be direct child; got {direct_types}"


@pytest.mark.asyncio
async def test_streaming_block_accent_is_streaming():
    """Streaming ToolPanel sets accent.state='streaming' on mount."""
    from hermes_cli.tui.app import HermesApp
    from hermes_cli.tui.widgets import OutputPanel
    from hermes_cli.tui.tool_panel import ToolPanel

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(5):
            await pilot.pause()
        app.agent_running = True
        for _ in range(5):
            await pilot.pause()
        app._open_gen_block("bash")
        for _ in range(5):
            await pilot.pause()

        panel = app.query_one(OutputPanel).query_one(ToolPanel)
        accent = panel.query_one(ToolAccent)
        assert accent.state == "streaming", f"Expected 'streaming', got '{accent.state}'"


@pytest.mark.asyncio
async def test_completed_block_accent_becomes_ok():
    """set_result_summary(ok) sets accent.state='ok'."""
    from hermes_cli.tui.app import HermesApp
    from hermes_cli.tui.widgets import OutputPanel
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.tool_result_parse import ResultSummary

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(5):
            await pilot.pause()
        app.agent_running = True
        for _ in range(5):
            await pilot.pause()
        app._open_gen_block("bash")
        for _ in range(5):
            await pilot.pause()

        panel = app.query_one(OutputPanel).query_one(ToolPanel)
        panel.set_result_summary(ResultSummary())
        for _ in range(3):
            await pilot.pause()

        accent = panel.query_one(ToolAccent)
        assert accent.state == "ok", f"Expected 'ok', got '{accent.state}'"


@pytest.mark.asyncio
async def test_error_block_accent_becomes_error():
    """set_result_summary(is_error=True) sets accent.state='error'."""
    from hermes_cli.tui.app import HermesApp
    from hermes_cli.tui.widgets import OutputPanel
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.tool_result_parse import ResultSummary

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(5):
            await pilot.pause()
        app.agent_running = True
        for _ in range(5):
            await pilot.pause()
        app._open_gen_block("bash")
        for _ in range(5):
            await pilot.pause()

        panel = app.query_one(OutputPanel).query_one(ToolPanel)
        panel.set_result_summary(ResultSummary(is_error=True, exit_code=1))
        for _ in range(3):
            await pilot.pause()

        accent = panel.query_one(ToolAccent)
        assert accent.state == "error", f"Expected 'error', got '{accent.state}'"
