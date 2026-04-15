"""Turn lifecycle integration tests.

Covers end-to-end state invariants across one or more agent turns:
  - ThinkingWidget deactivates after each turn (the _first_chunk_in_turn
    sentinel-reset bug meant it ran forever from turn 2 onward)
  - Tool body content is not individually scrollable (overflow-y: hidden)
  - OutputPanel is the sole scroll container (WhatsApp model)

Run with:
    pytest -o "addopts=" tests/tui/test_turn_lifecycle.py -v
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from rich.text import Text

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.tool_blocks import ToolBlock, ToolBodyContainer
from hermes_cli.tui.widgets import (
    CopyableRichLog,
    HistorySearchOverlay,
    LiveLineWidget,
    MessagePanel,
    OutputPanel,
    ReasoningPanel,
    ThinkingWidget,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _run_turn(app: HermesApp, pilot, *, chunks: list[str] | None = None) -> None:
    """Simulate one agent turn: activate → optional output → deactivate."""
    app.agent_running = True
    await pilot.pause()
    for chunk in (chunks or []):
        app.write_output(chunk)
    # Drain the async output queue
    await asyncio.sleep(0.05)
    await pilot.pause()
    app.agent_running = False
    await pilot.pause()


# ---------------------------------------------------------------------------
# ThinkingWidget lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_thinking_widget_deactivates_after_turn_1():
    """ThinkingWidget is hidden and timer stopped after the first turn ends."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        thinking = app.query_one(OutputPanel).query_one(ThinkingWidget)

        await _run_turn(app, pilot, chunks=["Hello\n", "world\n"])

        assert not thinking.display, "ThinkingWidget should be hidden after turn ends"
        assert thinking._shimmer_timer is None, "shimmer timer should be stopped"


@pytest.mark.asyncio
async def test_thinking_widget_activates_on_submit():
    """ThinkingWidget is visible while agent_running=True."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        thinking = app.query_one(OutputPanel).query_one(ThinkingWidget)

        app.agent_running = True
        await pilot.pause()

        # Fire on_hermes_input_submitted to trigger activate()
        from hermes_cli.tui.input_widget import HermesInput
        inp = app.query_one(HermesInput)
        inp.post_message(HermesInput.Submitted(value="hi"))
        await pilot.pause()

        assert thinking.display, "ThinkingWidget should be visible while agent is running"

        app.agent_running = False
        await pilot.pause()


@pytest.mark.asyncio
async def test_thinking_widget_deactivates_on_turn_2():
    """Regression: _first_chunk_in_turn was never reset (no flush_output sentinel),
    so from turn 2 onward ThinkingWidget.deactivate() was never called via the
    queue path.  watch_agent_running(False) is the safety net that fixes this."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        thinking = app.query_one(OutputPanel).query_one(ThinkingWidget)

        # Turn 1 — deactivation via first-chunk path
        await _run_turn(app, pilot, chunks=["turn 1 response\n"])
        assert not thinking.display, "ThinkingWidget should be hidden after turn 1"

        # Turn 2 — deactivation must NOT rely on _first_chunk_in_turn (it's False,
        # never reset because flush_output is never called from cli.py)
        await _run_turn(app, pilot, chunks=["turn 2 response\n"])
        assert not thinking.display, "ThinkingWidget should be hidden after turn 2"
        assert thinking._shimmer_timer is None


@pytest.mark.asyncio
async def test_thinking_widget_deactivates_on_turn_3():
    """Three consecutive turns all clean up correctly."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        thinking = app.query_one(OutputPanel).query_one(ThinkingWidget)

        for n in range(3):
            await _run_turn(app, pilot, chunks=[f"turn {n}\n"])
            assert not thinking.display, f"ThinkingWidget still active after turn {n}"
            assert thinking._shimmer_timer is None


@pytest.mark.asyncio
async def test_thinking_widget_deactivates_tool_only_turn():
    """Turn with no text output (tool-only) still deactivates ThinkingWidget.

    No write_output() calls → _first_chunk_in_turn path never fires →
    watch_agent_running(False) must handle cleanup.
    """
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        thinking = app.query_one(OutputPanel).query_one(ThinkingWidget)

        await _run_turn(app, pilot, chunks=[])  # no text output

        assert not thinking.display, "ThinkingWidget should be hidden after tool-only turn"
        assert thinking._shimmer_timer is None


@pytest.mark.asyncio
async def test_thinking_widget_deactivates_on_error_turn():
    """If agent_running goes False without any chunks (error path), shimmer stops."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        thinking = app.query_one(OutputPanel).query_one(ThinkingWidget)

        app.agent_running = True
        await pilot.pause()
        # Simulate: agent errors immediately, no output sent
        app.agent_running = False
        await pilot.pause()

        assert not thinking.display
        assert thinking._shimmer_timer is None


# ---------------------------------------------------------------------------
# LiveLineWidget flush + blink timer (GAP-D1)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_live_line_blink_timer_stops_after_turn():
    """Regression: flush_live() was never called from cli.py, so the non-typewriter
    blink timer on LiveLineWidget ran indefinitely across turns.
    watch_agent_running(False) now calls flush_live() which stops the timer."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        live = app.query_one(OutputPanel).query_one(LiveLineWidget)

        # Disable typewriter to activate the simple blink-timer path in feed()
        live._tw_enabled = False
        live._blink_enabled = True

        await _run_turn(app, pilot, chunks=["hello\n"])

        assert live._blink_timer is None, "blink timer should be stopped after turn ends"
        assert live._blink_visible is True, "_blink_visible should be reset to True for next turn"


@pytest.mark.asyncio
async def test_live_line_partial_buf_flushed_on_turn_end():
    """Partial _buf content (no trailing newline) is committed to the current
    MessagePanel when the turn ends, not leaked into the next turn."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.agent_running = True
        await pilot.pause()

        # Write a chunk with no trailing newline — stays in _buf
        app.write_output("partial line without newline")
        await asyncio.sleep(0.05)
        await pilot.pause()

        # End turn — flush_live() should commit _buf to MessagePanel
        app.agent_running = False
        await pilot.pause()

        panel = app.query_one(OutputPanel)
        live = panel.query_one(LiveLineWidget)
        assert live._buf == "", "_buf should be cleared after flush_live()"

        # The partial content should now be in the MessagePanel's response_log
        msg = panel.current_message
        assert msg is not None
        total_text = "\n".join(msg.response_log._plain_lines)
        assert "partial line without newline" in total_text


# ---------------------------------------------------------------------------
# HistorySearchOverlay debounce timer cleanup (GAP-A1)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_search_dismiss_cancels_debounce():
    """Regression: action_dismiss() didn't cancel _debounce_handle — the timer
    fired 150ms later and ran _render_results() against a hidden overlay,
    causing DOM remove/mount churn on a widget the user already closed."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()

        # Simulate a keypress that arms the debounce timer
        from textual.widgets import Input
        inp = overlay.query_one("#history-search-input", Input)
        inp.value = "q"
        await pilot.pause()
        assert overlay._debounce_handle is not None, "debounce timer should be armed"

        # Dismiss before the 150ms fires
        overlay.action_dismiss()
        await pilot.pause()

        assert overlay._debounce_handle is None, "debounce timer should be cancelled on dismiss"
        # Verify _render_results does NOT run after dismiss (no --visible class)
        assert not overlay.has_class("--visible")


@pytest.mark.asyncio
async def test_history_search_debounce_does_not_mutate_dismissed_overlay():
    """After dismiss, waiting 200ms should not cause any DOM changes to the
    hidden overlay (the cancelled timer must not fire _render_results)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        overlay = app.query_one(HistorySearchOverlay)
        overlay.open_search()
        await pilot.pause()

        from textual.widgets import Input
        inp = overlay.query_one("#history-search-input", Input)
        inp.value = "q"
        await pilot.pause()

        overlay.action_dismiss()
        await pilot.pause()

        # Wait longer than the 150ms debounce to confirm timer was cancelled
        await asyncio.sleep(0.25)
        await pilot.pause()

        # Overlay remains hidden — no DOM mutations from a ghost _render_results call
        assert not overlay.has_class("--visible"), "overlay should stay dismissed"


# ---------------------------------------------------------------------------
# Scroll isolation (WhatsApp model)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_output_panel_is_sole_scroll_container():
    """OutputPanel has overflow-y: auto; all child content widgets are hidden."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        # OutputPanel itself must allow vertical scroll
        assert panel.styles.overflow_y == "auto"
        # CopyableRichLog children of OutputPanel must NOT scroll individually
        for log in panel.query(CopyableRichLog):
            assert log.styles.overflow_y != "auto", (
                f"{log!r} has overflow-y:auto — creates nested scroll, causes dirty-rect corruption"
            )


@pytest.mark.asyncio
async def test_tool_body_copyable_richlog_has_no_individual_scroll():
    """ToolBodyContainer CopyableRichLog must have overflow-y: hidden.

    Nested scroll on tool bodies caused dirty-rect corruption: the internal
    scroll offset became stale after OutputPanel scrolled, and mouse movement
    triggered a repaint from the wrong offset.
    """
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        # Mount a tool block with enough lines to have previously triggered max-height scroll
        lines = [f"output line {i}" for i in range(80)]
        block = ToolBlock(label="test tool", lines=lines, plain_lines=lines)
        panel = app.query_one(OutputPanel)
        await panel.mount(block, before=panel.query_one(ThinkingWidget))
        block.toggle()  # expand it
        await pilot.pause()

        log = block.query_one(ToolBodyContainer).query_one(CopyableRichLog)
        assert log.styles.overflow_y != "auto", "tool body must not have individual scroll"
        assert log.styles.overflow_x != "auto", "tool body must not have individual scroll"


# ---------------------------------------------------------------------------
# Stale spinner / file breadcrumb across turns (GAP-3)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_spinner_label_cleared_after_turn():
    """Regression: cli.py resets _spinner_text locally but never pushes
    spinner_label='' to the app, so the last tool name persists into turn 2.
    watch_agent_running(False) now resets both spinner_label and status_active_file."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        # Simulate turn 1 with a file tool
        app.agent_running = True
        app.spinner_label = "read_file('src/main.py')"
        await pilot.pause()
        assert app.status_active_file == "src/main.py"

        # Turn 1 ends — spinner_label and status_active_file must be cleared
        app.agent_running = False
        await pilot.pause()

        assert app.spinner_label == "", "spinner_label should be cleared on turn end"
        assert app.status_active_file == "", "stale file breadcrumb should be cleared on turn end"


@pytest.mark.asyncio
async def test_file_breadcrumb_does_not_leak_into_turn_2():
    """StatusBar must not show turn-1's file path during turn 2 if no file tool ran."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        # Turn 1: file tool
        app.agent_running = True
        app.spinner_label = "write_file('config.py')"
        await pilot.pause()
        assert app.status_active_file == "config.py"
        app.agent_running = False
        await pilot.pause()

        # Turn 2: no file tool (spinner_label never set)
        app.agent_running = True
        await pilot.pause()
        assert app.status_active_file == "", "turn-2 must not inherit turn-1 file breadcrumb"
        app.agent_running = False
        await pilot.pause()


# ---------------------------------------------------------------------------
# Reasoning panel multi-block lifecycle (GAP-10)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reasoning_panel_preserves_multiple_blocks_in_same_turn():
    """A second thinking phase mounts a new block instead of overwriting the first."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        # Start a turn so there's a MessagePanel to hold reasoning
        app.agent_running = True
        await pilot.pause()

        panel = app.query_one(OutputPanel)
        msg = panel.current_message
        assert msg is not None

        # First reasoning block
        rp1 = msg.open_thinking_block("Reasoning")
        rp1.append_delta("thought one\n")
        rp1.close_box()
        assert "thought one" in rp1._plain_lines

        # Second reasoning block in the same turn (e.g. after a tool call)
        rp2 = msg.open_thinking_block("Reasoning")
        rp2.append_delta("thought two\n")
        rp2.close_box()

        blocks = list(msg.query(ReasoningPanel))
        assert len(blocks) == 2
        assert "thought one" in rp1._plain_lines
        assert "thought two" in rp2._plain_lines


@pytest.mark.asyncio
async def test_reasoning_panel_live_buf_cleared_on_open():
    """If close_box() was skipped (e.g. on interrupt), open_box() must still
    clear _live_buf so stale partial content doesn't prefix the next block."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.agent_running = True
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        rp = msg.open_thinking_block("Reasoning")

        # Start reasoning, append partial line, do NOT call close_box()
        rp.append_delta("partial without newline")
        assert rp._live_buf == "partial without newline"

        # Second open_box() without close — must clear buf
        rp2 = msg.open_thinking_block("Reasoning 2")
        assert rp2._live_buf == "", "new block must start with a clean live buffer"
        assert rp._live_buf == "", "previous open block should be auto-closed before a new one starts"

        app.agent_running = False
        await pilot.pause()


@pytest.mark.asyncio
async def test_reasoning_panel_reuse_after_close_with_no_content():
    """Empty closed panel should be reused instead of creating a new one."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.agent_running = True
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None

        # Open and immediately close with NO content (simulates interrupted reasoning)
        rp1 = msg.open_thinking_block("Reasoning")
        rp1.close_box()
        assert rp1.has_class("visible")
        assert not rp1._plain_lines
        assert not rp1._live_buf

        # Second open should REUSE the empty panel (not create a new one)
        rp2 = msg.open_thinking_block("Reasoning 2")
        assert rp2 is rp1, "empty closed panel should be reused, not replaced"
        assert rp2.has_class("visible")
        assert not rp2._is_closed

        # Verify the reused panel works correctly
        rp2.append_delta("actual content\n")
        assert "actual content" in rp2._plain_lines

        # Only one panel should exist in the DOM
        blocks = list(msg.query(ReasoningPanel))
        assert len(blocks) == 1

        app.agent_running = False
        await pilot.pause()


@pytest.mark.asyncio
async def test_reasoning_panel_no_content_leak_on_reuse():
    """Reused panel must not show stale content from a previous session."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.agent_running = True
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None

        # Open, add content, close
        rp1 = msg.open_thinking_block("R1")
        rp1.append_delta("old content\n")
        rp1.close_box()
        assert "old content" in rp1._plain_lines

        # Second open should NOT reuse (panel has content)
        rp2 = msg.open_thinking_block("R2")
        assert rp2 is not rp1, "panel with content should not be reused"

        # Third open on empty panel should reuse
        rp2.close_box()
        rp3 = msg.open_thinking_block("R3")
        assert rp3 is rp2, "empty closed panel should be reused"
        rp3.append_delta("new content\n")
        assert "new content" in rp3._plain_lines
        assert "old content" not in rp3._plain_lines

        app.agent_running = False
        await pilot.pause()


@pytest.mark.asyncio
async def test_large_single_turn_resize_does_not_crash():
    """Long single-turn transcripts must survive reflow without Textual cache KeyErrors."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(132, 45)) as pilot:
        await pilot.pause()

        app.agent_running = True
        await pilot.pause()

        output = app.query_one(OutputPanel)
        msg = output.current_message
        assert msg is not None

        # One turn with many reasoning/tool/prose transitions used to thrash
        # Textual's tiny default layout caches during resize/reflow.
        for i in range(40):
            rp = msg.open_thinking_block("Reasoning")
            rp.append_delta(f"thought {i}\n")
            rp.close_box()

            tool_lines = [f"tool {i} line {j}" for j in range(4)]
            msg.mount_tool_block(
                label=f"tool-{i}",
                lines=tool_lines,
                plain_lines=tool_lines,
                tool_name="terminal",
            )

            prose = msg.ensure_prose_block()
            prose.log.write_with_source(Text(f"after tool {i}"), f"after tool {i}")

            if i % 10 == 9:
                await pilot.pause()

        await pilot.pause()
        assert len(msg.children) > 100, "test needs a large single-turn DOM"

        app.agent_running = False
        await pilot.pause()

        await pilot.resize_terminal(133, 46)
        await pilot.pause()
        await pilot.resize_terminal(120, 40)
        await pilot.pause()

        assert output.current_message is msg


# ---------------------------------------------------------------------------
# MessagePanel ID uniqueness across many turns (GAP-1)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_message_panel_ids_unique_across_turns():
    """Each MessagePanel gets a unique _msg_id. IDs must not collide across
    many turns — CSS selector substring matching would produce silent bugs."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)

        ids = set()
        for _ in range(20):
            msg = panel.new_message()
            await pilot.pause()
            ids.add(msg._msg_id)

        assert len(ids) == 20, f"expected 20 unique _msg_ids, got {len(ids)}: {ids}"


# ---------------------------------------------------------------------------
# Empty _last_user_input safety (GAP-2)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_new_message_with_empty_user_text_is_safe():
    """watch_agent_running(True) calls new_message(user_text=_last_user_input).
    If the user never typed (e.g. programmatic agent start), user_text="" must
    not crash or produce broken MessagePanel layout."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app._last_user_input = ""
        app.agent_running = True
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None, "MessagePanel should be created even with empty user text"

        # Should not raise and the panel should be renderable
        app.write_output("response\n")
        await asyncio.sleep(0.05)
        await pilot.pause()
        app.agent_running = False
        await pilot.pause()


# ---------------------------------------------------------------------------
# _active_streaming_blocks cleanup on interrupt (GAP-5)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_streaming_blocks_dict_cleared_on_close():
    """close_streaming_tool_block() pops from _active_streaming_blocks.
    After a complete round-trip the dict must be empty — no orphaned refs."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.agent_running = True
        await pilot.pause()

        app.open_streaming_tool_block("tool-1", "bash")
        await pilot.pause()
        assert "tool-1" in app._active_streaming_blocks

        app.append_streaming_line("tool-1", "output line\n")
        await pilot.pause()

        app.close_streaming_tool_block("tool-1", "0.3s")
        await pilot.pause()

        assert "tool-1" not in app._active_streaming_blocks, (
            "_active_streaming_blocks should be empty after close — leaked refs prevent GC"
        )
        app.agent_running = False
        await pilot.pause()


@pytest.mark.asyncio
async def test_streaming_blocks_dict_cleared_on_interrupt():
    """watch_agent_running(False) clears _active_streaming_blocks for interrupted blocks.

    This prevents GC leaks when the agent is interrupted mid-stream without
    calling close_streaming_tool_block().  Turn 2 with the same tool id must
    create a fresh block, not reuse any stale reference."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.agent_running = True
        await pilot.pause()

        app.open_streaming_tool_block("tool-reused", "bash")
        await pilot.pause()
        first_block = app._active_streaming_blocks.get("tool-reused")
        assert first_block is not None

        # Interrupt: agent stops without calling close
        app.agent_running = False
        await pilot.pause()
        # Dict must be cleared — no leaked refs
        assert "tool-reused" not in app._active_streaming_blocks, (
            "_active_streaming_blocks must be cleared by watch_agent_running(False)"
        )

        # Turn 2: same tool id — creates a fresh block
        app.agent_running = True
        await pilot.pause()
        app.open_streaming_tool_block("tool-reused", "bash")
        await pilot.pause()

        second_block = app._active_streaming_blocks.get("tool-reused")
        assert second_block is not first_block, "second turn should create a new block, not reuse stale one"

        app.close_streaming_tool_block("tool-reused", "0.1s")
        app.agent_running = False
        await pilot.pause()
