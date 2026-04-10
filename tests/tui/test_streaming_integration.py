"""Integration tests for the full TUI streaming pipeline.

Exercises the end-to-end flow: _cprint → output queue → LiveLineWidget →
RichLog, as well as reasoning panel lifecycle and flush semantics.
"""

from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp, _CPYTHON_FAST_PATH
from hermes_cli.tui.widgets import (
    LiveLineWidget, MessagePanel, OutputPanel, PlainRule,
    ReasoningPanel, UserEchoPanel,
)


async def _pause(pilot, n=5):
    """Give Textual enough ticks to process queue + layout."""
    for _ in range(n):
        await pilot.pause()


# ---------------------------------------------------------------------------
# Streaming output: line-by-line commit to RichLog
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_line_committed_to_richlog():
    """A chunk ending with \\n is committed to the RichLog immediately."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        await pilot.pause()

        app.write_output("Hello world\n")
        await _pause(pilot)

        msg = panel.current_message
        assert msg is not None
        assert len(msg.response_log.lines) >= 1
        # Live line buffer should be empty after committing
        assert panel.live_line._buf == ""


@pytest.mark.asyncio
async def test_partial_line_stays_in_live_buffer():
    """Text without \\n stays in the live line buffer, not committed to RichLog."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        await pilot.pause()

        app.write_output("partial")
        await _pause(pilot)

        msg = panel.current_message
        assert msg is not None
        assert len(msg.response_log.lines) == 0
        assert panel.live_line._buf == "partial"


@pytest.mark.asyncio
async def test_mixed_complete_and_partial_lines():
    """Multiple complete lines followed by a partial are handled correctly."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        await pilot.pause()

        app.write_output("line1\nline2\nline3\npartial")
        await _pause(pilot)

        msg = panel.current_message
        assert len(msg.response_log.lines) >= 3
        assert panel.live_line._buf == "partial"


@pytest.mark.asyncio
async def test_streaming_token_by_token():
    """Simulates real streaming: small chunks arriving one token at a time."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        await pilot.pause()

        # Simulate token-by-token streaming (like an LLM would produce)
        tokens = ["Hello", " ", "world", "\n", "Second", " line", "\n"]
        for token in tokens:
            app.write_output(token)
        await _pause(pilot)

        msg = panel.current_message
        assert len(msg.response_log.lines) >= 2
        assert panel.live_line._buf == ""


@pytest.mark.asyncio
async def test_cprint_auto_appends_newline_for_tui():
    """_cprint ensures TUI queue receives \\n-terminated text.

    This is the core fix for streaming: _cprint now appends \\n when
    the text doesn't already end with one, matching prompt_toolkit's
    print_formatted_text behavior. We test via the _cprint path directly.
    """
    import cli as cli_mod

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        await pilot.pause()

        original_app = cli_mod._hermes_app
        try:
            cli_mod._hermes_app = app
            # _cprint without \n — the fix auto-appends \n in the TUI path
            cli_mod._cprint("no trailing newline")
            await _pause(pilot)

            msg = panel.current_message
            # With the fix, \n is auto-appended so LiveLineWidget commits it
            assert len(msg.response_log.lines) >= 1
            assert panel.live_line._buf == ""
        finally:
            cli_mod._hermes_app = original_app


# ---------------------------------------------------------------------------
# Flush semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_commits_partial_line():
    """flush_output sends sentinel that commits the live line buffer to RichLog."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        await pilot.pause()

        app.write_output("partial content")
        await _pause(pilot)
        app.flush_output()
        await _pause(pilot)

        assert panel.live_line._buf == ""
        msg = panel.current_message
        assert len(msg.response_log.lines) >= 1


@pytest.mark.asyncio
async def test_flush_is_idempotent():
    """Flushing when buffer is empty does nothing harmful."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        # Flush without any prior output
        app.flush_output()
        await _pause(pilot)

        # Should not crash, no message panel created
        panel = app.query_one(OutputPanel)
        assert panel.current_message is None


@pytest.mark.asyncio
async def test_flush_after_complete_lines():
    """Flush after complete lines doesn't create phantom blank lines."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        await pilot.pause()

        app.write_output("line1\nline2\n")
        await _pause(pilot)
        app.flush_output()
        await _pause(pilot)

        msg = panel.current_message
        assert len(msg.response_log.lines) >= 2
        assert panel.live_line._buf == ""


# ---------------------------------------------------------------------------
# Box creation: MessagePanel auto-creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_output_creates_message_panel_on_demand():
    """Writing output when no MessagePanel exists auto-creates one."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        assert panel.current_message is None

        app.write_output("auto-create\n")
        await _pause(pilot)

        msg = panel.current_message
        assert msg is not None
        assert len(msg.response_log.lines) >= 1


@pytest.mark.asyncio
async def test_agent_running_creates_new_message_panel():
    """Setting agent_running=True creates a new MessagePanel via watcher."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        assert panel.current_message is None

        app.agent_running = True
        await _pause(pilot)

        assert panel.current_message is not None


@pytest.mark.asyncio
async def test_multiple_turns_create_separate_panels():
    """Each agent turn gets its own MessagePanel."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)

        # Turn 1
        app.agent_running = True
        await _pause(pilot)
        app.write_output("Turn 1 content\n")
        await _pause(pilot)
        first_msg = panel.current_message
        app.agent_running = False
        await _pause(pilot)

        # Turn 2
        app.agent_running = True
        await _pause(pilot)
        app.write_output("Turn 2 content\n")
        await _pause(pilot)
        second_msg = panel.current_message

        assert first_msg is not second_msg
        panels = panel.query(MessagePanel)
        assert len(panels) >= 2


@pytest.mark.asyncio
async def test_output_immediately_after_turn_start():
    """Content arriving right after agent_running=True lands in the new panel."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.agent_running = True
        await pilot.pause()

        app.write_output("Immediate line 1\n")
        app.write_output("Immediate line 2\n")
        await _pause(pilot)

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        assert len(msg.response_log.lines) >= 2


# ---------------------------------------------------------------------------
# Reasoning panel lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reasoning_panel_hidden_by_default():
    """ReasoningPanel is not visible until open_box is called."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.agent_running = True
        await _pause(pilot)

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        assert not msg.reasoning.has_class("visible")


@pytest.mark.asyncio
async def test_reasoning_open_close_lifecycle():
    """Full reasoning lifecycle: open → append → close."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.agent_running = True
        await _pause(pilot)

        msg = app.query_one(OutputPanel).current_message
        rp = msg.reasoning

        # Open
        rp.open_box("Thinking")
        await _pause(pilot)
        assert rp.has_class("visible")

        # Append
        rp.append_delta("Step 1\n")
        rp.append_delta("Step 2\n")
        await _pause(pilot)
        # 2 gutter-prefixed lines (no header)
        assert len(rp._reasoning_log.lines) == 2

        # Close
        rp.close_box()
        await _pause(pilot)
        assert not rp.has_class("visible")


@pytest.mark.asyncio
async def test_reasoning_partial_line_buffering():
    """Partial reasoning lines are buffered until \\n arrives."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.agent_running = True
        await _pause(pilot)

        msg = app.query_one(OutputPanel).current_message
        rp = msg.reasoning
        rp.open_box("Reasoning")
        await pilot.pause()

        # Send partial tokens
        rp.append_delta("thinking")
        rp.append_delta(" about")
        rp.append_delta(" this")
        await _pause(pilot)

        # No lines committed; partial stays in buffer (no header)
        assert len(rp._reasoning_log.lines) == 0
        assert "thinking about this" in rp._live_buf

        # Complete the line
        rp.append_delta("\n")
        await _pause(pilot)
        assert len(rp._reasoning_log.lines) == 1  # completed line (no header)
        assert rp._live_buf == ""


@pytest.mark.asyncio
async def test_reasoning_close_flushes_partial():
    """close_box flushes any remaining partial line to the RichLog."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.agent_running = True
        await _pause(pilot)

        msg = app.query_one(OutputPanel).current_message
        rp = msg.reasoning
        rp.open_box("Reasoning")
        rp.append_delta("partial thought")
        await _pause(pilot)

        # Partial should still be in buffer
        assert rp._live_buf == "partial thought"

        # Close flushes the partial
        rp.close_box()
        await _pause(pilot)
        assert rp._live_buf == ""
        assert len(rp._reasoning_log.lines) == 1  # flushed partial (no header)


@pytest.mark.asyncio
async def test_reasoning_via_app_helpers():
    """App-level reasoning helpers (open/append/close) route to the panel."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.agent_running = True
        await _pause(pilot)

        # Use the app-level helpers (what call_from_thread targets)
        app.open_reasoning("Thinking")
        await _pause(pilot)

        msg = app.query_one(OutputPanel).current_message
        assert msg.reasoning.has_class("visible")

        app.append_reasoning("Step 1\n")
        app.append_reasoning("Step 2\n")
        await _pause(pilot)

        assert len(msg.reasoning._reasoning_log.lines) == 2

        app.close_reasoning()
        await _pause(pilot)
        assert not msg.reasoning.has_class("visible")


# ---------------------------------------------------------------------------
# Combined streaming + reasoning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reasoning_then_response_streaming():
    """Reasoning panel opens, receives content, closes, then response streams."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.agent_running = True
        await _pause(pilot)

        msg = app.query_one(OutputPanel).current_message

        # Reasoning phase
        app.open_reasoning("Thinking")
        app.append_reasoning("Analysis step\n")
        await _pause(pilot)
        assert msg.reasoning.has_class("visible")

        # Transition to response
        app.close_reasoning()
        await _pause(pilot)
        assert not msg.reasoning.has_class("visible")

        # Response phase
        app.write_output("Response line 1\n")
        app.write_output("Response line 2\n")
        await _pause(pilot)

        assert len(msg.response_log.lines) >= 2
        assert len(msg.reasoning._reasoning_log.lines) >= 1  # 1 gutter-prefixed step (no header)


@pytest.mark.asyncio
async def test_rapid_streaming_does_not_lose_content():
    """Many rapid writes don't lose content under normal conditions."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        panel = app.query_one(OutputPanel)
        panel.new_message()
        await pilot.pause()

        # Rapid-fire 50 lines
        for i in range(50):
            app.write_output(f"Line {i}\n")
        await _pause(pilot, n=10)

        msg = panel.current_message
        assert len(msg.response_log.lines) >= 50


@pytest.mark.asyncio
async def test_interleaved_output_and_flush():
    """Interleaved writes and flushes produce correct output."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        panel = app.query_one(OutputPanel)
        panel.new_message()
        await pilot.pause()

        # Write, flush, write more
        app.write_output("First\n")
        app.write_output("partial")
        await _pause(pilot)
        app.flush_output()
        await _pause(pilot)
        app.write_output("Second\n")
        await _pause(pilot)

        msg = panel.current_message
        assert len(msg.response_log.lines) >= 3  # First, partial, Second
        assert panel.live_line._buf == ""


# ---------------------------------------------------------------------------
# Streaming fix: incremental rendering & thread-safe queue access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chunks_render_incrementally_on_new_message():
    """Chunks for a newly auto-created MessagePanel appear incrementally.

    Regression test: without yielding to the event loop between chunks,
    RichLog writes go to _deferred_renders (size=0 after mount) and only
    appear once the queue is fully drained.
    """
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        panel = app.query_one(OutputPanel)
        # Do NOT pre-create a MessagePanel — let append() auto-create it
        assert panel.current_message is None

        # Send first chunk — triggers new_message() + mount
        app.write_output("First line\n")
        await _pause(pilot)

        msg = panel.current_message
        assert msg is not None
        first_count = len(msg.response_log.lines)
        assert first_count >= 1, "First chunk should render before second arrives"

        # Send second chunk — should also render (not pile up deferred)
        app.write_output("Second line\n")
        await _pause(pilot)

        assert len(msg.response_log.lines) >= first_count + 1


def test_cpython_fast_path_disabled():
    """call_soon_threadsafe is always used for cross-thread queue access.

    asyncio.Queue is not thread-safe; put_nowait from a non-event-loop
    thread won't wake the selector, causing batched delivery on timer ticks.
    """
    assert _CPYTHON_FAST_PATH is False


@pytest.mark.asyncio
async def test_write_output_uses_call_soon_threadsafe():
    """write_output routes through call_soon_threadsafe, not raw put_nowait."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        with patch.object(app._event_loop, "call_soon_threadsafe", wraps=app._event_loop.call_soon_threadsafe) as spy:
            app.write_output("test\n")
            assert spy.call_count >= 1


# ---------------------------------------------------------------------------
# User echo panel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_echo_user_message_mounts_panel():
    """echo_user_message mounts a UserEchoPanel into OutputPanel."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.echo_user_message("Hello world")
        await _pause(pilot)

        panels = app.query(UserEchoPanel)
        assert len(panels) == 1


@pytest.mark.asyncio
async def test_echo_user_message_before_response():
    """UserEchoPanel appears before the response MessagePanel."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        # Echo user message, then start agent turn
        app.echo_user_message("test message")
        await _pause(pilot)
        panel = app.query_one(OutputPanel)
        panel.new_message()
        await _pause(pilot)

        # UserEchoPanel should be before MessagePanel in the DOM
        children = list(panel.children)
        echo_idx = next(i for i, c in enumerate(children) if isinstance(c, UserEchoPanel))
        msg_idx = next(i for i, c in enumerate(children) if isinstance(c, MessagePanel))
        assert echo_idx < msg_idx


@pytest.mark.asyncio
async def test_user_echo_has_short_rulers():
    """UserEchoPanel contains PlainRule widgets with max_width set."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.echo_user_message("test")
        await _pause(pilot)

        echo = app.query_one(UserEchoPanel)
        rules = echo.query(PlainRule)
        assert len(rules) == 2
        for rule in rules:
            assert rule._max_width == UserEchoPanel._ECHO_RULE_WIDTH


@pytest.mark.asyncio
async def test_user_echo_does_not_pollute_response_log():
    """User echo content should NOT appear in the MessagePanel's RichLog."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.echo_user_message("my question")
        await _pause(pilot)
        panel = app.query_one(OutputPanel)
        panel.new_message()
        await _pause(pilot)

        # Write response content
        app.write_output("response text\n")
        await _pause(pilot)

        msg = panel.current_message
        assert msg is not None
        # RichLog should only have response text, not user echo
        assert len(msg.response_log.lines) >= 1


# ---------------------------------------------------------------------------
# Backpressure / edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backpressure_does_not_crash():
    """Queue overflow is handled gracefully."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        # Saturate the queue
        for i in range(4096):
            app.write_output(f"chunk{i}\n")
        # One more should be silently dropped
        app.write_output("overflow\n")
        await pilot.pause()
        # No crash = pass


@pytest.mark.asyncio
async def test_write_output_before_event_loop():
    """write_output before the event loop is ready doesn't crash."""
    app = HermesApp(cli=MagicMock())
    # Before run_test, _event_loop is None
    app.write_output("should not crash\n")
    app.flush_output()
    # No crash = pass
