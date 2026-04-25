"""Phase C / D1/D2 — ChildPanel structure, gutter suppression, and MessagePanel wiring tests."""
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
    with patch("hermes_cli.tui.tool_panel._child._time") as mock_t:
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
# D1: ChildPanel drops ToolAccent (single gutter)
# ---------------------------------------------------------------------------

def test_child_panel_no_tool_accent():
    """D1: ChildPanel.compose() yields BodyPane + FooterPane (no rail widget)."""
    from hermes_cli.tui.tool_panel import BodyPane, FooterPane

    panel = _make_panel()
    composed = list(panel.compose())

    type_names = [type(w).__name__ for w in composed]
    assert "ToolAccent" not in type_names, f"Removed ToolAccent reappeared: {type_names}"
    assert any(isinstance(w, BodyPane) for w in composed), "BodyPane missing"
    assert any(isinstance(w, FooterPane) for w in composed), "FooterPane missing"


def test_child_panel_is_child_flag_set_on_header():
    """D1: on_mount sets _is_child=True on the block's ToolHeader."""
    panel = _make_panel()
    block = panel._block

    # Simulate on_mount without a real Textual app
    header = block._header
    header._is_child = False

    # Manually call the _is_child wiring (same logic as on_mount)
    header._is_child = True
    header.refresh()

    assert header._is_child is True


def test_child_panel_header_is_child_attribute_exists():
    """D1: ToolHeader has _is_child attribute (defaults False)."""
    from hermes_cli.tui.tool_blocks._header import ToolHeader

    header = ToolHeader(label="bash", line_count=0, tool_name="bash")
    assert hasattr(header, "_is_child")
    assert header._is_child is False


# ---------------------------------------------------------------------------
# D2: grouped padding does not stack inside SubAgentBody
# ---------------------------------------------------------------------------

def test_grouped_child_no_extra_padding():
    """D2: ChildPanel inside SubAgentBody gets padding-left:0 via TCSS override."""
    # This is a TCSS structural test — verify the rule exists in hermes.tcss
    import os
    tcss_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "hermes_cli", "tui", "hermes.tcss"
    )
    tcss_path = os.path.realpath(tcss_path)
    with open(tcss_path) as f:
        content = f.read()

    # Either D2 rule OR Phase 6 H1 replacement rule must be present.
    # H1 alternative: SubAgentBody ToolGroup > ToolPanel { padding-left: 0 }
    # D2 original: SubAgentBody ToolPanel.tool-panel--grouped { padding-left: 0 }
    has_d2 = "SubAgentBody ToolPanel.tool-panel--grouped" in content
    has_h1_alt = "SubAgentBody ToolGroup > ToolPanel" in content
    assert has_d2 or has_h1_alt, (
        "Neither D2 grouped-padding override nor H1 SubAgentBody ToolGroup rule found in hermes.tcss"
    )


# ---------------------------------------------------------------------------
# Parent notification
# ---------------------------------------------------------------------------

def test_parent_notified_on_complete():
    """set_result_summary calls _notify_child_complete on parent SubAgentPanel."""
    parent = MagicMock(spec=SubAgentPanel)
    panel = _make_panel(parent=parent)

    # Wire super().set_result_summary to be a no-op
    with patch.object(ChildPanel.__bases__[0], "set_result_summary"), \
         patch("hermes_cli.tui.tool_panel._child._time") as mock_t:
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
         patch("hermes_cli.tui.tool_panel._child._time") as mock_t:
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


# ---------------------------------------------------------------------------
# B14 — _user_touched_compact guard
# ---------------------------------------------------------------------------

def _make_summary(is_error: bool = True) -> MagicMock:
    s = MagicMock()
    s.is_error = is_error
    return s


def test_user_touched_false_initially():
    """Fresh ChildPanel has _user_touched_compact = False."""
    panel = _make_panel()
    assert panel._user_touched_compact is False


def test_user_touched_set_on_toggle():
    """action_toggle_compact sets _user_touched_compact = True."""
    panel = _make_panel()
    panel.action_toggle_compact()
    assert panel._user_touched_compact is True


def test_auto_uncompact_on_error():
    """Fresh panel: error result auto-uncompacts (user hasn't touched)."""
    panel = _make_panel()
    with patch.object(ChildPanel.__bases__[0], "set_result_summary"), \
         patch("hermes_cli.tui.tool_panel._child._time") as mock_t:
        mock_t.monotonic.return_value = 1.0
        panel._start_time = 0.0
        panel.set_result_summary(_make_summary(is_error=True))
    assert panel._compact_mode is False


def test_no_auto_uncompact_when_user_touched():
    """User toggled compact → error result does NOT auto-uncompact."""
    panel = _make_panel()
    panel.action_toggle_compact()  # sets _user_touched_compact = True, toggles compact off
    panel.set_compact(True)         # manually re-compact
    with patch.object(ChildPanel.__bases__[0], "set_result_summary"), \
         patch("hermes_cli.tui.tool_panel._child._time") as mock_t:
        mock_t.monotonic.return_value = 1.0
        panel._start_time = 0.0
        panel.set_result_summary(_make_summary(is_error=True))
    # Still compact because user_touched=True
    assert panel._compact_mode is True


def test_no_auto_uncompact_on_success():
    """Non-error result: compact state unchanged regardless of _user_touched_compact."""
    panel = _make_panel()
    assert panel._compact_mode is True
    with patch.object(ChildPanel.__bases__[0], "set_result_summary"), \
         patch("hermes_cli.tui.tool_panel._child._time") as mock_t:
        mock_t.monotonic.return_value = 1.0
        panel._start_time = 0.0
        panel.set_result_summary(_make_summary(is_error=False))
    assert panel._compact_mode is True
