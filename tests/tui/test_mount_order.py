# Run with: pytest -o "addopts=" tests/tui/test_mount_order.py
"""Integration tests for DOM mount order and layout fixes in the Hermes TUI.

These tests verify that OutputPanel keeps live-output trio
(``ToolPendingLine``, ``ThinkingWidget``, ``LiveLineWidget``) at bottom, while
per-turn content mounts ahead of that trio. Tool blocks now live inside their
turn's ``MessagePanel`` timeline, not as direct ``OutputPanel`` children.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import (
    OutputPanel,
    MessagePanel,
    UserMessagePanel,
    LiveLineWidget,
    ToolPendingLine,
    ThinkingWidget,
)
from hermes_cli.tui.tool_blocks import StreamingToolBlock, ToolBlock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _pause(pilot, n: int = 5) -> None:
    for _ in range(n):
        await pilot.pause()


def _make_app() -> HermesApp:
    return HermesApp(cli=MagicMock())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_output_panel_initial_compose_order():
    """The three compose-time widgets must appear in the right order with no messages."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        panel = app.query_one(OutputPanel)
        children = list(panel.children)
        types = [type(c) for c in children]
        assert ToolPendingLine in types
        assert ThinkingWidget in types
        assert LiveLineWidget in types
        tp_idx = types.index(ToolPendingLine)
        tw_idx = types.index(ThinkingWidget)
        ll_idx = types.index(LiveLineWidget)
        assert tp_idx < tw_idx < ll_idx, (
            f"Expected ToolPendingLine < ThinkingWidget < LiveLineWidget, "
            f"got indices {tp_idx}, {tw_idx}, {ll_idx}"
        )


@pytest.mark.asyncio
async def test_new_message_goes_before_tool_pending():
    """MessagePanel mounted via new_message() must appear before ToolPendingLine."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        mp = output.new_message()
        await _pause(pilot)
        children = list(output.children)
        assert mp in children, "MessagePanel not found in OutputPanel children"
        tp = output.tool_pending
        assert children.index(mp) < children.index(tp), (
            "MessagePanel must come before ToolPendingLine"
        )


@pytest.mark.asyncio
async def test_echo_user_message_goes_before_tool_pending():
    """UserMessagePanel mounted via echo_user_message() must appear before ToolPendingLine."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        app.echo_user_message("hello")
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        children = list(output.children)
        uep = next((c for c in children if isinstance(c, UserMessagePanel)), None)
        assert uep is not None, "UserMessagePanel not found in OutputPanel children"
        tp = output.tool_pending
        assert children.index(uep) < children.index(tp), (
            "UserMessagePanel must come before ToolPendingLine"
        )


@pytest.mark.asyncio
async def test_live_trio_always_last_after_messages():
    """ToolPendingLine, ThinkingWidget, LiveLineWidget must always be the last three children."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)

        # Mount several content widgets
        output.new_message()
        await _pause(pilot)
        app.echo_user_message("turn 1")
        await _pause(pilot)
        output.new_message()
        await _pause(pilot)
        app.echo_user_message("turn 2")
        await _pause(pilot)

        children = list(output.children)
        n = len(children)
        assert n >= 3, "OutputPanel must have at least 3 children"
        assert isinstance(children[-1], LiveLineWidget), (
            f"Last child must be LiveLineWidget, got {type(children[-1])}"
        )
        assert isinstance(children[-2], ThinkingWidget), (
            f"Second-to-last child must be ThinkingWidget, got {type(children[-2])}"
        )
        assert isinstance(children[-3], ToolPendingLine), (
            f"Third-to-last child must be ToolPendingLine, got {type(children[-3])}"
        )


@pytest.mark.asyncio
async def test_tool_block_mounts_before_tool_pending():
    """ToolBlock from mount_tool_block() stays in current MessagePanel timeline."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        # agent_running watcher creates a MessagePanel
        app.agent_running = True
        await _pause(pilot)
        app.mount_tool_block("output", ["line1", "line2"], ["line1", "line2"])
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        msg = output.current_message
        assert msg is not None, "Current MessagePanel missing"
        children = list(msg.children)
        tb = next((c for c in children if isinstance(c, ToolBlock)), None)
        assert tb is not None, "ToolBlock not found in MessagePanel children"
        tp = output.tool_pending
        assert msg.parent is output
        assert list(output.children).index(msg) < list(output.children).index(tp), (
            "MessagePanel containing ToolBlock must come before ToolPendingLine"
        )


@pytest.mark.asyncio
async def test_streaming_tool_block_mounts_before_tool_pending():
    """STB from open_streaming_tool_block() stays in current MessagePanel timeline."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        app.open_streaming_tool_block("id1", "bash")
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        msg = output.current_message
        assert msg is not None, "Current MessagePanel missing"
        children = list(msg.children)
        stb = next((c for c in children if isinstance(c, StreamingToolBlock)), None)
        assert stb is not None, "StreamingToolBlock not found in MessagePanel children"
        tp = output.tool_pending
        tw = output.query_one(ThinkingWidget)
        ll = output.live_line
        output_children = list(output.children)
        assert msg.parent is output
        assert output_children.index(msg) < output_children.index(tp), (
            "MessagePanel containing StreamingToolBlock must come before ToolPendingLine"
        )
        assert output_children.index(msg) < output_children.index(tw), (
            "MessagePanel containing StreamingToolBlock must come before ThinkingWidget"
        )
        assert output_children.index(msg) < output_children.index(ll), (
            "MessagePanel containing StreamingToolBlock must come before LiveLineWidget"
        )


@pytest.mark.asyncio
async def test_streaming_tool_block_is_in_output_panel_not_message_panel():
    """STB must be nested inside current MessagePanel, not mounted at OutputPanel root."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        app.open_streaming_tool_block("id2", "bash")
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        msg = output.current_message
        assert msg is not None, "Current MessagePanel missing"
        stb = next((c for c in msg.children if isinstance(c, StreamingToolBlock)), None)
        assert stb is not None, "StreamingToolBlock must be mounted in current MessagePanel"
        assert stb.parent is msg, (
            f"STB parent is {stb.parent!r}, expected MessagePanel"
        )


@pytest.mark.asyncio
async def test_completed_stb_stays_above_next_turn():
    """Completed STB stays in turn-1 MessagePanel, which stays before turn 2."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)

        # Turn 1: MessagePanel-1, open STB, close STB
        mp1 = output.new_message()
        await _pause(pilot)
        app.open_streaming_tool_block("stb-t1", "grep")
        await _pause(pilot)
        app.close_streaming_tool_block("stb-t1", "0.1s")
        await _pause(pilot)

        # Turn 2: MessagePanel-2
        mp2 = output.new_message()
        await _pause(pilot)

        stb = next((c for c in mp1.children if isinstance(c, StreamingToolBlock)), None)
        assert stb is not None, "StreamingToolBlock not found in turn-1 MessagePanel after close"

        children = list(output.children)
        i_mp1 = children.index(mp1)
        i_mp2 = children.index(mp2)

        assert i_mp1 < i_mp2, f"MP-1 ({i_mp1}) must precede MP-2 ({i_mp2})"


@pytest.mark.asyncio
async def test_multi_turn_order():
    """Two turns: UE-1, MP-1, UE-2, MP-2, ToolPendingLine, ThinkingWidget, LiveLineWidget."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)

        # Turn 1
        app.echo_user_message("msg 1")
        await _pause(pilot)
        mp1 = output.new_message()
        await _pause(pilot)

        # Turn 2
        app.echo_user_message("msg 2")
        await _pause(pilot)
        mp2 = output.new_message()
        await _pause(pilot)

        children = list(output.children)

        # Collect user echo panels in order
        ue_panels = [c for c in children if isinstance(c, UserMessagePanel)]
        assert len(ue_panels) >= 2, "Expected at least 2 UserMessagePanels"
        ue1, ue2 = ue_panels[0], ue_panels[1]

        tp = output.tool_pending
        tw = output.query_one(ThinkingWidget)
        ll = output.live_line

        i = children.index
        # Relative ordering of content
        assert i(ue1) < i(mp1), "UE-1 must precede MP-1"
        assert i(mp1) < i(ue2), "MP-1 must precede UE-2"
        assert i(ue2) < i(mp2), "UE-2 must precede MP-2"
        # Trio must be after all content
        assert i(mp2) < i(tp), "MP-2 must precede ToolPendingLine"
        assert i(tp) < i(tw), "ToolPendingLine must precede ThinkingWidget"
        assert i(tw) < i(ll), "ThinkingWidget must precede LiveLineWidget"


@pytest.mark.asyncio
async def test_scroll_guard_on_echo_user_message():
    """When _user_scrolled_up is True, echo_user_message must not change scroll_y."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        panel = app.query_one(OutputPanel)
        panel._user_scrolled_up = True
        scroll_before = panel.scroll_y
        app.echo_user_message("hi")
        await _pause(pilot)
        # scroll_y must remain the same — auto-scroll was suppressed
        assert panel.scroll_y == scroll_before, (
            f"scroll_y changed from {scroll_before} to {panel.scroll_y} "
            "despite _user_scrolled_up=True"
        )


@pytest.mark.asyncio
async def test_scroll_guard_on_close_streaming_tool_block():
    """When _user_scrolled_up is True, closing an STB must not change scroll_y."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        # Set up: need a MessagePanel to exist so open_streaming_tool_block succeeds
        app.agent_running = True
        await _pause(pilot)
        app.open_streaming_tool_block("stb-sg", "cat")
        await _pause(pilot)
        # Now enable scroll guard before close
        panel = app.query_one(OutputPanel)
        panel._user_scrolled_up = True
        scroll_before = panel.scroll_y
        app.close_streaming_tool_block("stb-sg", "0.0s")
        await _pause(pilot)
        assert panel.scroll_y == scroll_before, (
            f"scroll_y changed from {scroll_before} to {panel.scroll_y} "
            "despite _user_scrolled_up=True"
        )


@pytest.mark.asyncio
async def test_thinking_widget_activates_without_layout_shift():
    """Activating ThinkingWidget must not change the trio's relative ordering."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)

        # Activate thinking shimmer
        tw = output.query_one(ThinkingWidget)
        tw.activate()
        await _pause(pilot)

        # ThinkingWidget must now be visible
        assert tw.styles.display == "block", "ThinkingWidget must be visible after activate()"

        # The trio must still be the last three children in the correct order
        children = list(output.children)
        n = len(children)
        assert n >= 3
        assert isinstance(children[-1], LiveLineWidget), (
            f"Last child must still be LiveLineWidget, got {type(children[-1])}"
        )
        assert isinstance(children[-2], ThinkingWidget), (
            f"Second-to-last must still be ThinkingWidget, got {type(children[-2])}"
        )
        assert isinstance(children[-3], ToolPendingLine), (
            f"Third-to-last must still be ToolPendingLine, got {type(children[-3])}"
        )
        # ThinkingWidget is in the trio, not relocated
        tp = output.tool_pending
        ll = output.live_line
        i = children.index
        assert i(tp) < i(tw) < i(ll), (
            "ThinkingWidget must remain between ToolPendingLine and LiveLineWidget"
        )
