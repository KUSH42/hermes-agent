"""Scroll integration tests — live OutputPanel scroll behaviour.

Tests cover the complete interaction chain as it runs in the real app:
  - auto-scroll on streaming output, user echo, block open/close
  - auto-scroll suppression when the user has scrolled away
  - scroll flag lifecycle (set / clear / threshold guard)
  - ToolTail badge accumulation and dismissal
  - turn navigation (alt+up / alt+down) with real MessagePanels
  - mouse and keyboard scroll event handling

Implementation bugs caught by this suite:
  - open_streaming_tool_block() was missing the scroll_end call present in
    every other OutputPanel mutation (fixed in app.py)
  - StreamingToolBlock._tail_new_count was not reset when watch_scroll_y
    dismissed the tail externally; second scroll session accumulated on top
    of the stale count (fixed in tool_blocks.py by removing the duplicate
    counter and using tail._new_line_count as the single source of truth)

Run with:
    pytest -o "addopts=" tests/tui/test_scroll_integration.py -v
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.tool_blocks import StreamingToolBlock, ToolTail
from hermes_cli.tui.widgets import (
    MessagePanel,
    OutputPanel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app() -> HermesApp:
    cli = MagicMock()
    cli.agent = None
    return HermesApp(cli=cli)


async def _setup(pilot) -> OutputPanel:
    await pilot.pause()
    return pilot.app.query_one(OutputPanel)


async def _open_block(app: HermesApp, pilot, tid: str = "t1", label: str = "cmd") -> StreamingToolBlock:
    output = app.query_one(OutputPanel)
    if output.current_message is None:
        output.new_message()
    await pilot.pause()
    app.open_streaming_tool_block(tid, label)
    await pilot.pause()
    return app._active_streaming_blocks[tid]


def _make_scroll_event(cls, widget=None, button=0):
    """Construct a Textual MouseScroll* event with the required positional args."""
    return cls(
        widget=widget,
        x=0, y=0,
        delta_x=0, delta_y=1,
        button=button,
        shift=False, meta=False, ctrl=False,
    )


# ===========================================================================
# 1. Auto-scroll on streaming output
# ===========================================================================

@pytest.mark.asyncio
async def test_auto_scroll_fires_on_streaming_chunk():
    """scroll_end is called on the OutputPanel for each streamed chunk when the
    user has not scrolled away."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        assert output._user_scrolled_up is False

        with patch.object(output, "scroll_end") as mock_se:
            app.write_output("hello\n")
            await asyncio.sleep(0.05)
            await pilot.pause()
            assert mock_se.called, "scroll_end must be called when not scrolled up"


@pytest.mark.asyncio
async def test_auto_scroll_suppressed_when_scrolled_up():
    """scroll_end is NOT called while _user_scrolled_up is True."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        output._user_scrolled_up = True

        with patch.object(output, "scroll_end") as mock_se:
            app.write_output("hello\n")
            await asyncio.sleep(0.05)
            await pilot.pause()
            assert not mock_se.called, "scroll_end must be suppressed when _user_scrolled_up"


@pytest.mark.asyncio
async def test_auto_scroll_suppressed_across_many_chunks():
    """Suppression persists for the entire burst, not just the first chunk."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        output._user_scrolled_up = True

        with patch.object(output, "scroll_end") as mock_se:
            for i in range(10):
                app.write_output(f"line {i}\n")
            await asyncio.sleep(0.1)
            await pilot.pause()
            assert not mock_se.called, "scroll_end must not fire across a 10-chunk burst when scrolled up"


# ===========================================================================
# 2. Auto-scroll on user echo and message panel creation
# ===========================================================================

@pytest.mark.asyncio
async def test_user_echo_triggers_scroll():
    """echo_user_message schedules scroll_end when the user is at the live edge."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        assert output._user_scrolled_up is False

        with patch.object(output, "scroll_end") as mock_se:
            app.echo_user_message("hello world")
            await pilot.pause()
            assert mock_se.called, "scroll_end must be called after echo_user_message"


@pytest.mark.asyncio
async def test_user_echo_suppressed_when_scrolled_up():
    """echo_user_message respects the scroll-suppression flag."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        output._user_scrolled_up = True

        with patch.object(output, "scroll_end") as mock_se:
            app.echo_user_message("hello world")
            await pilot.pause()
            assert not mock_se.called


@pytest.mark.asyncio
async def test_user_echo_mounts_panel_before_tool_pending():
    """UserEchoPanel appears in the DOM before ToolPendingLine."""
    from hermes_cli.tui.widgets import ToolPendingLine
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _setup(pilot)
        app.echo_user_message("buy milk")
        await pilot.pause()
        output = app.query_one(OutputPanel)
        children = list(output.children)
        types = [type(c).__name__ for c in children]
        assert "UserEchoPanel" in types
        assert "ToolPendingLine" in types
        echo_idx = next(i for i, t in enumerate(types) if t == "UserEchoPanel")
        tp_idx = types.index("ToolPendingLine")
        assert echo_idx < tp_idx, "UserEchoPanel must sit before ToolPendingLine"


# ===========================================================================
# 3. Auto-scroll from streaming block API
# ===========================================================================

@pytest.mark.asyncio
async def test_open_streaming_block_triggers_scroll():
    """open_streaming_tool_block schedules scroll_end at the live edge.

    Bug: this call was missing before — every other OutputPanel mutation
    (echo, append line, close block) called scroll_end except open.
    """
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        output.new_message()
        await pilot.pause()

        with patch.object(output, "scroll_end") as mock_se:
            app.open_streaming_tool_block("t1", "ls")
            await pilot.pause()
            assert mock_se.called, "scroll_end must fire when a new streaming block is mounted"


@pytest.mark.asyncio
async def test_open_streaming_block_suppressed_when_scrolled_up():
    """open_streaming_tool_block respects the scroll-suppression flag."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        output.new_message()
        await pilot.pause()
        output._user_scrolled_up = True

        with patch.object(output, "scroll_end") as mock_se:
            app.open_streaming_tool_block("t1", "ls")
            await pilot.pause()
            assert not mock_se.called


@pytest.mark.asyncio
async def test_append_streaming_line_triggers_scroll():
    """append_streaming_line schedules scroll_end when not scrolled away."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        await _open_block(app, pilot)
        assert output._user_scrolled_up is False

        with patch.object(output, "scroll_end") as mock_se:
            app.append_streaming_line("t1", "output line")
            await pilot.pause()
            assert mock_se.called


@pytest.mark.asyncio
async def test_append_streaming_line_suppressed_when_scrolled_up():
    """append_streaming_line does not scroll when _user_scrolled_up."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        await _open_block(app, pilot)
        output._user_scrolled_up = True

        with patch.object(output, "scroll_end") as mock_se:
            app.append_streaming_line("t1", "output line")
            await pilot.pause()
            assert not mock_se.called


@pytest.mark.asyncio
async def test_close_streaming_block_triggers_scroll():
    """close_streaming_tool_block schedules scroll_end to reveal the collapsed header."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        await _open_block(app, pilot)
        app.append_streaming_line("t1", "done")
        await asyncio.sleep(0.05)
        await pilot.pause()

        with patch.object(output, "scroll_end") as mock_se:
            app.close_streaming_tool_block("t1", "0.1s")
            await pilot.pause()
            assert mock_se.called


@pytest.mark.asyncio
async def test_close_streaming_block_suppressed_when_scrolled_up():
    """close_streaming_tool_block respects scroll suppression."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        await _open_block(app, pilot)
        output._user_scrolled_up = True

        with patch.object(output, "scroll_end") as mock_se:
            app.close_streaming_tool_block("t1", "0.1s")
            await pilot.pause()
            assert not mock_se.called


# ===========================================================================
# 4. Scroll flag lifecycle
# ===========================================================================

@pytest.mark.asyncio
async def test_on_scroll_up_event_sets_flag():
    """ScrollUp keyboard event sets _user_scrolled_up."""
    from textual.scrollbar import ScrollUp as _ScrollUp
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        assert output._user_scrolled_up is False
        output.on_scroll_up(_ScrollUp())
        assert output._user_scrolled_up is True


@pytest.mark.asyncio
async def test_on_mouse_scroll_up_sets_flag():
    """Mouse wheel up sets _user_scrolled_up."""
    from textual.events import MouseScrollUp as _MSU
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        assert output._user_scrolled_up is False
        output.on_mouse_scroll_up(_make_scroll_event(_MSU))
        assert output._user_scrolled_up is True


@pytest.mark.asyncio
async def test_on_mouse_scroll_down_does_not_set_flag():
    """Mouse wheel down alone does NOT set _user_scrolled_up.

    Re-engagement at the bottom is handled by watch_scroll_y, not by the
    scroll-down handler.
    """
    from textual.events import MouseScrollDown as _MSD
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        assert output._user_scrolled_up is False
        output.on_mouse_scroll_down(_make_scroll_event(_MSD))
        assert output._user_scrolled_up is False, "scroll-down must not set the scroll-up flag"


@pytest.mark.asyncio
async def test_watch_scroll_y_clears_flag_at_bottom():
    """watch_scroll_y clears _user_scrolled_up when scroll reaches max_scroll_y."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        output._user_scrolled_up = True

        with patch.object(type(output), "max_scroll_y", new_callable=PropertyMock, return_value=20):
            output.watch_scroll_y(20)

        assert output._user_scrolled_up is False


@pytest.mark.asyncio
async def test_watch_scroll_y_clears_flag_within_one_line_of_bottom():
    """The threshold is >= max_scroll_y - 1 — one line above bottom also clears."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        output._user_scrolled_up = True

        with patch.object(type(output), "max_scroll_y", new_callable=PropertyMock, return_value=20):
            output.watch_scroll_y(19)

        assert output._user_scrolled_up is False


@pytest.mark.asyncio
async def test_watch_scroll_y_preserves_flag_mid_scroll():
    """watch_scroll_y does NOT clear the flag when not near the bottom."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        output._user_scrolled_up = True

        with patch.object(type(output), "max_scroll_y", new_callable=PropertyMock, return_value=100):
            output.watch_scroll_y(50)

        assert output._user_scrolled_up is True


@pytest.mark.asyncio
async def test_watch_scroll_y_noop_when_max_scroll_is_zero():
    """watch_scroll_y guards against max_scroll_y == 0 (headless / no overflow).
    The flag must not be mutated in that case."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        output._user_scrolled_up = True

        with patch.object(type(output), "max_scroll_y", new_callable=PropertyMock, return_value=0):
            output.watch_scroll_y(0)

        assert output._user_scrolled_up is True, "flag must not be cleared when max_scroll_y is 0"


@pytest.mark.asyncio
async def test_flag_clears_after_streaming_then_scroll_return():
    """Full sequence: stream → scroll up (flag set) → chunks ignored → scroll to bottom → flag clears."""
    from textual.scrollbar import ScrollUp as _ScrollUp
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)

        app.write_output("first chunk\n")
        await asyncio.sleep(0.05)
        await pilot.pause()

        # User scrolls up
        output.on_scroll_up(_ScrollUp())
        assert output._user_scrolled_up is True

        # More streaming — scroll_end suppressed
        with patch.object(output, "scroll_end") as mock_se:
            app.write_output("second chunk\n")
            await asyncio.sleep(0.05)
            await pilot.pause()
            assert not mock_se.called

        # User scrolls back to the live edge
        with patch.object(type(output), "max_scroll_y", new_callable=PropertyMock, return_value=30):
            output.watch_scroll_y(30)
        assert output._user_scrolled_up is False

        # Now streaming should scroll again
        with patch.object(output, "scroll_end") as mock_se2:
            app.write_output("third chunk\n")
            await asyncio.sleep(0.05)
            await pilot.pause()
            assert mock_se2.called


# ===========================================================================
# 5. ToolTail accumulation and dismissal
# ===========================================================================

@pytest.mark.asyncio
async def test_tool_tail_accumulates_while_scrolled_up():
    """Lines arriving while _user_scrolled_up increment the ToolTail badge count."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        block = await _open_block(app, pilot)
        tail = block.query_one(ToolTail)

        output._user_scrolled_up = True

        for i in range(5):
            block.append_line(f"line {i}")
        await asyncio.sleep(0.1)
        await pilot.pause()

        assert tail.display is True, "ToolTail should be visible when lines arrive while scrolled up"
        assert tail._new_line_count == 5, f"Expected 5, got {tail._new_line_count}"


@pytest.mark.asyncio
async def test_tool_tail_hidden_when_not_scrolled_up():
    """Lines arriving when _user_scrolled_up is False must not show the ToolTail."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        block = await _open_block(app, pilot)
        tail = block.query_one(ToolTail)

        assert output._user_scrolled_up is False
        for i in range(5):
            block.append_line(f"line {i}")
        await asyncio.sleep(0.1)
        await pilot.pause()

        assert tail.display is False, "ToolTail must stay hidden when user is at the live edge"
        assert tail._new_line_count == 0


@pytest.mark.asyncio
async def test_tool_tail_text_format():
    """ToolTail badge text includes the count and 'new lines'."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        block = await _open_block(app, pilot)
        tail = block.query_one(ToolTail)

        tail.update_count(7)
        rendered = str(tail.render())
        assert "7" in rendered
        assert "new lines" in rendered


@pytest.mark.asyncio
async def test_tool_tail_dismissed_when_scroll_returns():
    """watch_scroll_y dismisses all ToolTails in the panel when user returns to bottom."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        block = await _open_block(app, pilot)
        tail = block.query_one(ToolTail)

        output._user_scrolled_up = True
        tail.update_count(8)
        await pilot.pause()
        assert tail.display is True

        with patch.object(type(output), "max_scroll_y", new_callable=PropertyMock, return_value=50):
            output.watch_scroll_y(50)
        await pilot.pause()

        assert tail.display is False, "ToolTail must be dismissed when user returns to the live edge"


@pytest.mark.asyncio
async def test_multiple_blocks_tail_tracked_independently():
    """Each StreamingToolBlock has its own ToolTail; both accumulate while scrolled up."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        output.new_message()
        await pilot.pause()

        app.open_streaming_tool_block("t1", "cmd1")
        app.open_streaming_tool_block("t2", "cmd2")
        await pilot.pause()

        b1 = app._active_streaming_blocks["t1"]
        b2 = app._active_streaming_blocks["t2"]

        output._user_scrolled_up = True

        for i in range(3):
            b1.append_line(f"b1 line {i}")
        for i in range(7):
            b2.append_line(f"b2 line {i}")

        await asyncio.sleep(0.1)
        await pilot.pause()

        assert b1.query_one(ToolTail)._new_line_count == 3
        assert b2.query_one(ToolTail)._new_line_count == 7


@pytest.mark.asyncio
async def test_tool_tail_resets_between_scroll_sessions():
    """Returning to the bottom clears the count; a second scroll-away session starts fresh.

    Bug: _tail_new_count (now removed) was not reset when watch_scroll_y called
    tail.dismiss() externally. The second session accumulated on top of the stale
    value. Fixed by removing the duplicate counter and using tail._new_line_count
    as the single source of truth — which IS reset by dismiss().
    """
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        block = await _open_block(app, pilot)
        tail = block.query_one(ToolTail)

        # First scroll-away session
        output._user_scrolled_up = True
        for i in range(4):
            block.append_line(f"line {i}")
        await asyncio.sleep(0.1)
        await pilot.pause()
        assert tail._new_line_count == 4

        # Return to bottom — dismisses tail (resets _new_line_count to 0)
        with patch.object(type(output), "max_scroll_y", new_callable=PropertyMock, return_value=40):
            output.watch_scroll_y(40)
        await pilot.pause()
        assert tail.display is False
        assert tail._new_line_count == 0

        # Second scroll-away session must start from 0
        output._user_scrolled_up = True
        block.append_line("new line after return")
        await asyncio.sleep(0.1)
        await pilot.pause()
        assert tail._new_line_count == 1, (
            f"Second session should start at 1, got {tail._new_line_count}. "
            "Stale _tail_new_count bug — tail._new_line_count must be the single source of truth."
        )


# ===========================================================================
# 6. Turn navigation
# ===========================================================================

@pytest.mark.asyncio
async def test_turn_nav_prev_noop_with_no_panels():
    """action_prev_turn does not crash when no MessagePanels exist."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _setup(pilot)
        app.action_prev_turn()
        await pilot.pause()


@pytest.mark.asyncio
async def test_turn_nav_next_noop_with_no_panels():
    """action_next_turn does not crash when no MessagePanels exist."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _setup(pilot)
        app.action_next_turn()
        await pilot.pause()


@pytest.mark.asyncio
async def test_turn_nav_prev_calls_scroll_visible_on_panel():
    """action_prev_turn calls scroll_visible on a panel when panels exist.

    In headless layout all panels have virtual_region.y == 0. With scroll_y
    mocked to 20 (well above any panel), the reversed walk finds the last
    panel immediately (0 < 19) and calls scroll_visible on it.
    """
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        p1 = output.new_message()
        p2 = output.new_message()
        p3 = output.new_message()
        await pilot.pause()

        with (
            patch.object(type(output), "scroll_y", new_callable=PropertyMock, return_value=20.0),
            patch.object(p1, "scroll_visible") as sv1,
            patch.object(p2, "scroll_visible") as sv2,
            patch.object(p3, "scroll_visible") as sv3,
        ):
            app.action_prev_turn()
            await pilot.pause()

        # With all panels at y=0, reversed walk hits p3 first (0 < 19) — the
        # most recently created panel is visually the one "just above" current pos.
        called = [sv1.called, sv2.called, sv3.called]
        assert any(called), "action_prev_turn must call scroll_visible on some panel"
        assert sum(called) == 1, "exactly one panel should be scrolled to"
        assert sv3.called, "the last (most recent) panel must be chosen in headless layout"


@pytest.mark.asyncio
async def test_turn_nav_prev_wraps_to_first_panel_when_at_top():
    """When scroll_y <= 0, no panel satisfies the 'above current' condition.
    action_prev_turn wraps and scrolls to panels[0].
    """
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        p1 = output.new_message()
        p2 = output.new_message()
        await pilot.pause()

        # scroll_y=0 → threshold is -1; no panel with y < -1 → wraps to panels[0]
        with (
            patch.object(type(output), "scroll_y", new_callable=PropertyMock, return_value=0.0),
            patch.object(p1, "scroll_visible") as sv1,
            patch.object(p2, "scroll_visible") as sv2,
        ):
            app.action_prev_turn()
            await pilot.pause()
        sv1.assert_called_once_with(animate=True)
        sv2.assert_not_called()


@pytest.mark.asyncio
async def test_turn_nav_next_calls_scroll_visible_on_panel():
    """action_next_turn calls scroll_visible on a panel below the current position.

    With scroll_y mocked to -10, all panels at y=0 satisfy 0 > -9, so the
    first panel in forward order gets the scroll_visible call.
    """
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        p1 = output.new_message()
        p2 = output.new_message()
        await pilot.pause()

        with (
            patch.object(type(output), "scroll_y", new_callable=PropertyMock, return_value=-10.0),
            patch.object(p1, "scroll_visible") as sv1,
            patch.object(p2, "scroll_visible") as sv2,
        ):
            app.action_next_turn()
            await pilot.pause()
        sv1.assert_called_once_with(animate=True)
        sv2.assert_not_called()


@pytest.mark.asyncio
async def test_turn_nav_next_noop_when_scroll_past_all_panels():
    """action_next_turn is a no-op when scroll_y is past every panel's top.

    Mock scroll_y to 10 000 — far beyond any panel position — so no panel
    satisfies `panel_top > scroll_y + 1`.
    """
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        p1 = output.new_message()
        p2 = output.new_message()
        await pilot.pause()

        with (
            patch.object(type(output), "scroll_y", new_callable=PropertyMock, return_value=10_000.0),
            patch.object(p1, "scroll_visible") as sv1,
            patch.object(p2, "scroll_visible") as sv2,
        ):
            app.action_next_turn()
            await pilot.pause()
        sv1.assert_not_called()
        sv2.assert_not_called()


@pytest.mark.asyncio
async def test_alt_up_keybinding_reaches_action_prev_turn():
    """alt+up key event dispatches action_prev_turn on the app."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _setup(pilot)
        with patch.object(app, "action_prev_turn") as mock_action:
            await pilot.press("alt+up")
            await pilot.pause()
            assert mock_action.called, "alt+up must dispatch action_prev_turn"


@pytest.mark.asyncio
async def test_alt_down_keybinding_reaches_action_next_turn():
    """alt+down key event dispatches action_next_turn on the app."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _setup(pilot)
        with patch.object(app, "action_next_turn") as mock_action:
            await pilot.press("alt+down")
            await pilot.pause()
            assert mock_action.called, "alt+down must dispatch action_next_turn"


# ===========================================================================
# 7. Mouse scroll step size
# ===========================================================================

@pytest.mark.asyncio
async def test_mouse_scroll_up_moves_three_lines():
    """on_mouse_scroll_up scrolls relative by exactly -3 lines (_SCROLL_LINES)."""
    from textual.events import MouseScrollUp as _MSU
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        with patch.object(output, "scroll_relative") as mock_sr:
            output.on_mouse_scroll_up(_make_scroll_event(_MSU))
            mock_sr.assert_called_once_with(y=-3, animate=False)


@pytest.mark.asyncio
async def test_mouse_scroll_down_moves_three_lines():
    """on_mouse_scroll_down scrolls relative by exactly +3 lines (_SCROLL_LINES)."""
    from textual.events import MouseScrollDown as _MSD
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)
        with patch.object(output, "scroll_relative") as mock_sr:
            output.on_mouse_scroll_down(_make_scroll_event(_MSD))
            mock_sr.assert_called_once_with(y=3, animate=False)


@pytest.mark.asyncio
async def test_mouse_scroll_events_prevent_default():
    """Mouse scroll events call prevent_default() to suppress Textual's built-in scroll handling."""
    from textual.events import MouseScrollUp as _MSU, MouseScrollDown as _MSD
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = await _setup(pilot)

        up_event = _make_scroll_event(_MSU)
        up_event.prevent_default = MagicMock()
        output.on_mouse_scroll_up(up_event)
        up_event.prevent_default.assert_called_once()

        down_event = _make_scroll_event(_MSD)
        down_event.prevent_default = MagicMock()
        output.on_mouse_scroll_down(down_event)
        down_event.prevent_default.assert_called_once()
