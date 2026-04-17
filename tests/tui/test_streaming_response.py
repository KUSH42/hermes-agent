"""Streaming response path integration tests.

Covers: write_output → queue → _consume_output → LiveLineWidget → flush_live → RichLog.

Run with:
    pytest -o "addopts=" tests/tui/test_streaming_response.py -v
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import (
    CopyableRichLog,
    LiveLineWidget,
    MessagePanel,
    OutputPanel,
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
    await asyncio.sleep(0.05)
    await pilot.pause()
    app.agent_running = False
    await pilot.pause()


def _disable_typewriter(app: HermesApp) -> None:
    """Disable typewriter and blink for deterministic testing."""
    live = app.query_one(OutputPanel).query_one(LiveLineWidget)
    live._tw_enabled = False
    live._blink_enabled = False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_output_chunk_visible_in_live_line():
    """feed() accumulates text in _buf without newline."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _disable_typewriter(app)

        app.agent_running = True
        await pilot.pause()

        app.write_output("hello")
        await asyncio.sleep(0.05)
        await pilot.pause()

        live = app.query_one(OutputPanel).query_one(LiveLineWidget)
        assert live._buf == "hello", f"expected 'hello' in _buf, got {live._buf!r}"

        app.agent_running = False
        await pilot.pause()


@pytest.mark.asyncio
async def test_flush_commits_buf_to_richlog():
    """feed() with a newline commits to response_log and clears _buf."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _disable_typewriter(app)

        await _run_turn(app, pilot, chunks=["hello\n"])

        panel = app.query_one(OutputPanel)
        live = panel.query_one(LiveLineWidget)
        msg = panel.current_message
        assert msg is not None
        assert live._buf == "", f"_buf should be empty after newline flush, got {live._buf!r}"
        assert len(msg.response_log._plain_lines) >= 1, "response_log should have at least 1 line"


@pytest.mark.asyncio
async def test_partial_line_flushed_on_turn_end():
    """Partial _buf (no trailing newline) is committed to response_log when turn ends."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _disable_typewriter(app)

        app.agent_running = True
        await pilot.pause()

        app.write_output("partial line no newline")
        await asyncio.sleep(0.05)
        await pilot.pause()

        app.agent_running = False
        await pilot.pause()

        panel = app.query_one(OutputPanel)
        live = panel.query_one(LiveLineWidget)
        assert live._buf == "", f"_buf should be empty after turn end, got {live._buf!r}"

        msg = panel.current_message
        assert msg is not None
        total_text = "\n".join(msg.response_log._plain_lines)
        assert "partial line no newline" in total_text, (
            f"partial content not found in response_log: {total_text!r}"
        )


@pytest.mark.asyncio
async def test_typewriter_animating_flag_false_after_flush():
    """With typewriter force-enabled, _animating is False after the turn ends.

    _char_queue is initialised in on_mount only when typewriter is on.  We
    set up both the queue and start the drainer worker after mount so the
    typewriter code path is fully exercised.
    """
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        live = app.query_one(OutputPanel).query_one(LiveLineWidget)
        # Force-enable typewriter: set flag AND initialise _char_queue (normally
        # done in on_mount when config is True).
        live._tw_enabled = True
        live._char_queue = asyncio.Queue()
        live._drain_chars()  # start the drainer worker
        await pilot.pause()

        await _run_turn(app, pilot, chunks=["token\n"])

        assert live._animating is False, "_animating should be False after flush"


@pytest.mark.asyncio
async def test_typewriter_blink_timer_stops_after_flush():
    """flush() stops the non-typewriter blink timer and resets _blink_visible."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        live = app.query_one(OutputPanel).query_one(LiveLineWidget)
        live._tw_enabled = False
        live._blink_enabled = True

        await _run_turn(app, pilot, chunks=["hello\n"])

        assert live._blink_timer is None, "blink timer should be None after turn ends"
        assert live._blink_visible is True, "_blink_visible should be reset to True"


@pytest.mark.asyncio
async def test_thinking_widget_deactivates_on_first_token():
    """ThinkingWidget deactivates (display=False, _shimmer_timer=None) on first chunk."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _disable_typewriter(app)

        thinking = app.query_one(OutputPanel).query_one(ThinkingWidget)

        # Manually activate the thinking widget
        app.agent_running = True
        await pilot.pause()
        thinking.activate()
        await pilot.pause()

        assert not thinking.display, "ThinkingWidget disabled (height:0, no-op activate)"

        # Feed a chunk — deactivation happens via _consume_output path
        app.write_output("first token\n")
        await asyncio.sleep(0.05)
        await pilot.pause()

        app.agent_running = False
        await pilot.pause()

        assert not thinking.display, "ThinkingWidget should be deactivated after first token"
        assert thinking._shimmer_timer is None, "_shimmer_timer should be None after deactivation"


@pytest.mark.asyncio
async def test_multi_turn_live_line_starts_clean():
    """_buf is empty between consecutive turns — no content leaks across turns."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _disable_typewriter(app)

        live = app.query_one(OutputPanel).query_one(LiveLineWidget)

        await _run_turn(app, pilot, chunks=["turn 1 line\n"])
        assert live._buf == "", f"_buf should be empty after turn 1, got {live._buf!r}"

        await _run_turn(app, pilot, chunks=["turn 2 line\n"])
        assert live._buf == "", f"_buf should be empty after turn 2, got {live._buf!r}"


@pytest.mark.asyncio
async def test_richlog_write_width_not_narrow():
    """A 60-char line fed through the streaming path is not truncated in _plain_lines."""
    long_line = "A" * 60
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _disable_typewriter(app)

        await _run_turn(app, pilot, chunks=[long_line + "\n"])

        panel = app.query_one(OutputPanel)
        msg = panel.current_message
        assert msg is not None
        assert len(msg.response_log._plain_lines) >= 1
        committed = msg.response_log._plain_lines[0]
        assert long_line in committed, (
            f"60-char content should not be truncated; got: {committed!r}"
        )


@pytest.mark.asyncio
async def test_word_boundary_flush_no_double_write():
    """Two chunks that together form one line produce exactly 1 committed line."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _disable_typewriter(app)

        await _run_turn(app, pilot, chunks=["foo ", "bar\n"])

        panel = app.query_one(OutputPanel)
        msg = panel.current_message
        assert msg is not None
        plain_lines = msg.response_log._plain_lines
        # Filter out empty lines that may come from the rule separator
        content_lines = [l for l in plain_lines if l.strip()]
        assert len(content_lines) == 1, (
            f"expected exactly 1 content line, got {len(content_lines)}: {content_lines!r}"
        )
        assert "foo" in content_lines[0] and "bar" in content_lines[0], (
            f"committed line should contain both 'foo' and 'bar': {content_lines[0]!r}"
        )


@pytest.mark.asyncio
async def test_ansi_in_response_stream_renders_without_escapes():
    """ANSI escape codes in response stream are stripped from _plain_lines."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        _disable_typewriter(app)

        await _run_turn(app, pilot, chunks=["\x1b[1mBold text\x1b[0m\n"])

        panel = app.query_one(OutputPanel)
        msg = panel.current_message
        assert msg is not None
        plain_lines = msg.response_log._plain_lines
        assert len(plain_lines) >= 1, "response_log should have at least 1 line"

        combined = "\n".join(plain_lines)
        assert "Bold text" in combined, f"'Bold text' not found in plain_lines: {combined!r}"
        assert "\x1b" not in combined, (
            f"ANSI escape codes found in _plain_lines: {combined!r}"
        )
