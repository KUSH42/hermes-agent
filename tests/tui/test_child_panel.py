"""Phase C — ChildPanel and MessagePanel wiring tests."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, call

from hermes_cli.tui.child_panel import ChildPanel
from hermes_cli.tui.sub_agent_panel import SubAgentPanel
from hermes_cli.tui.tool_result_parse import ResultSummaryV4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_block():
    block = MagicMock()
    block._header = MagicMock()
    block._header._is_child_last = None
    return block


def _make_panel(depth=1, parent=None):
    block = _make_block()
    with patch("hermes_cli.tui.child_panel._time") as mock_t:
        mock_t.monotonic.return_value = 0.0
        panel = ChildPanel(block, tool_name="Grep", depth=depth, parent_subagent=parent)
    return panel


async def _pause(pilot, n=3):
    for _ in range(n):
        await pilot.pause()


# ---------------------------------------------------------------------------
# Compact mode
# ---------------------------------------------------------------------------

def test_child_panel_starts_compact():
    """ChildPanel initializes with _compact_mode=True and --compact class."""
    panel = _make_panel()
    assert panel._compact_mode is True
    assert panel.has_class("--compact")


def test_toggle_compact_expands():
    """action_toggle_compact flips compact off, removes --compact."""
    panel = _make_panel()
    panel.action_toggle_compact()
    assert panel._compact_mode is False
    assert not panel.has_class("--compact")


def test_toggle_compact_twice_restores():
    """Double toggle returns to compact."""
    panel = _make_panel()
    panel.action_toggle_compact()
    panel.action_toggle_compact()
    assert panel._compact_mode is True
    assert panel.has_class("--compact")


def test_set_compact_noop_if_same():
    """set_compact(True) when already True does not modify state."""
    panel = _make_panel()
    assert panel._compact_mode is True
    # Call with same value — should be a no-op
    panel.set_compact(True)
    assert panel._compact_mode is True  # unchanged


def test_watch_collapsed_noop():
    """Setting collapsed reactive doesn't affect body visibility — no-op watcher."""
    panel = _make_panel()
    # Should not raise; no side effects
    panel.watch_collapsed(False, True)
    panel.watch_collapsed(True, False)


# ---------------------------------------------------------------------------
# Parent notification
# ---------------------------------------------------------------------------

def test_parent_notified_on_complete():
    """set_result_summary calls _notify_child_complete on parent SubAgentPanel."""
    parent = MagicMock(spec=SubAgentPanel)
    panel = _make_panel(parent=parent)

    # Wire super().set_result_summary to be a no-op
    with patch.object(ChildPanel.__bases__[0], "set_result_summary"), \
         patch("hermes_cli.tui.child_panel._time") as mock_t:
        mock_t.monotonic.return_value = 1.0
        panel._start_time = 0.0

        summary = MagicMock()
        summary.is_error = False
        panel.set_result_summary(summary)

    parent._notify_child_complete.assert_called_once()
    args = parent._notify_child_complete.call_args[0]
    assert args[1] is False  # is_error


def test_error_auto_expands_child():
    """Error result auto-expands compact child."""
    parent = MagicMock(spec=SubAgentPanel)
    panel = _make_panel(parent=parent)

    with patch.object(ChildPanel.__bases__[0], "set_result_summary"), \
         patch("hermes_cli.tui.child_panel._time") as mock_t:
        mock_t.monotonic.return_value = 1.0
        panel._start_time = 0.0
        summary = MagicMock()
        summary.is_error = True
        panel.set_result_summary(summary)

    assert panel._compact_mode is False
    assert not panel.has_class("--compact")


# ---------------------------------------------------------------------------
# MessagePanel wiring
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_orphan_child_mounts_flat():
    """Child with unknown parent_tool_call_id is buffered without crash."""
    from hermes_cli.tui.app import HermesApp
    from hermes_cli.tui.widgets.message_panel import MessagePanel
    from textual.widgets import Static
    app = HermesApp(cli=MagicMock())
    async with app.run_test() as pilot:
        msg = MessagePanel()
        await app.mount(msg)
        await _pause(pilot)

        block = Static("x")
        block._content_type = "tool"  # type: ignore[attr-defined]
        msg._mount_nonprose_block(block, parent_tool_call_id="nonexistent")

        # Block synchronously buffered — check before flush runs
        assert block in msg._child_buffer.get("nonexistent", [])
        await _pause(pilot)


@pytest.mark.asyncio
async def test_flush_deduplication():
    """Two children buffered for same parent → single call_after_refresh."""
    from hermes_cli.tui.widgets.message_panel import MessagePanel
    from hermes_cli.tui.app import HermesApp
    app = HermesApp(cli=MagicMock())
    async with app.run_test() as pilot:
        msg = MessagePanel()
        await app.mount(msg)
        await _pause(pilot)

        c1 = MagicMock()
        c1._content_type = "tool"
        c2 = MagicMock()
        c2._content_type = "tool"

        with patch.object(msg, "call_after_refresh") as mock_caf:
            msg._mount_nonprose_block(c1, parent_tool_call_id="p-x")
            msg._mount_nonprose_block(c2, parent_tool_call_id="p-x")

        # Only one call_after_refresh for "p-x"
        flush_calls = [c for c in mock_caf.call_args_list
                       if c[0] and c[0][0] == msg._flush_child_buffer]
        assert len(flush_calls) == 1


@pytest.mark.asyncio
async def test_maybe_start_group_skipped():
    """Child with parent_tool_call_id does NOT trigger _maybe_start_group."""
    from hermes_cli.tui.widgets.message_panel import MessagePanel
    from hermes_cli.tui.app import HermesApp
    app = HermesApp(cli=MagicMock())
    async with app.run_test() as pilot:
        msg = MessagePanel()
        await app.mount(msg)
        await _pause(pilot)

        parent_panel = MagicMock(spec=SubAgentPanel)
        parent_panel.add_child_panel = MagicMock()
        msg._subagent_panels["p-y"] = parent_panel

        child = MagicMock()
        child._content_type = "tool"

        # _maybe_start_group is imported inside the function; patch it at source
        with patch("hermes_cli.tui.tool_group._maybe_start_group") as mock_msg:
            msg._mount_nonprose_block(child, parent_tool_call_id="p-y")

        mock_msg.assert_not_called()
        parent_panel.add_child_panel.assert_called_once_with(child)


@pytest.mark.asyncio
async def test_subagent_panels_registration():
    """SubAgentPanel registered in _subagent_panels before mount — verified by patching."""
    from hermes_cli.tui.app import HermesApp
    from hermes_cli.tui.widgets import OutputPanel
    from hermes_cli.tui.sub_agent_panel import SubAgentPanel as SAP
    app = HermesApp(cli=MagicMock())
    async with app.run_test() as pilot:
        app.agent_running = True
        await _pause(pilot)

        try:
            panel = app.query_one(OutputPanel)
        except Exception:
            return  # No output panel, skip

        msg = panel.current_message or panel.new_message()
        registered_before_mount: list[bool] = []
        original = msg._mount_nonprose_block

        def side_effect(widget, parent_tool_call_id=None):
            if isinstance(widget, SAP):
                registered_before_mount.append(
                    any(v is widget for v in msg._subagent_panels.values())
                )
            return original(widget, parent_tool_call_id)

        msg._mount_nonprose_block = side_effect
        app.open_streaming_tool_block("sap-reg-1", "delegate task", tool_name="delegate")
        await _pause(pilot)

        assert registered_before_mount, "open_streaming_tool_block created no SubAgentPanel"
        assert all(registered_before_mount), "Panel not registered before mount"
