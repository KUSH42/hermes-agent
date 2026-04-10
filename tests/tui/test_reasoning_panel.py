"""Tests for ReasoningPanel widget — Step 2."""

from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import OutputPanel, ReasoningPanel, _safe_widget_call
from textual.widgets import RichLog


def _ensure_message(app):
    """Create a MessagePanel so ReasoningPanel is in the DOM."""
    panel = app.query_one(OutputPanel)
    msg = panel.current_message
    if msg is None:
        msg = panel.new_message()
    return msg


@pytest.mark.asyncio
async def test_reasoning_panel_hidden_by_default():
    """ReasoningPanel is hidden (display: none) on mount."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        await pilot.pause()
        assert not msg.reasoning.has_class("visible")


@pytest.mark.asyncio
async def test_open_box_makes_visible():
    """open_box adds the 'visible' CSS class."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        await pilot.pause()
        msg.reasoning.open_box("Reasoning")
        await pilot.pause()
        assert msg.reasoning.has_class("visible")


@pytest.mark.asyncio
async def test_append_delta_writes_complete_lines():
    """append_delta commits complete lines (with \\n) to the RichLog."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        await pilot.pause()
        msg.reasoning.open_box("Thinking")
        msg.reasoning.append_delta("step 1\n")
        msg.reasoning.append_delta("step 2\n")
        await pilot.pause()
        log = msg.reasoning.query_one("#reasoning-log")
        # 2 committed lines (no header, gutter-prefixed)
        assert len(log.lines) == 2


@pytest.mark.asyncio
async def test_append_delta_buffers_partial():
    """append_delta buffers text without newlines, doesn't write to log."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        await pilot.pause()
        msg.reasoning.open_box("Thinking")
        msg.reasoning.append_delta("partial ")
        msg.reasoning.append_delta("text")
        await pilot.pause()
        log = msg.reasoning.query_one("#reasoning-log")
        # No lines committed — partial text is in _live_buf (no header line)
        assert len(log.lines) == 0
        assert msg.reasoning._live_buf == "partial text"


@pytest.mark.asyncio
async def test_append_delta_flushes_on_newline():
    """Partial buffer is committed when a newline arrives."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        await pilot.pause()
        msg.reasoning.open_box("Thinking")
        msg.reasoning.append_delta("hello ")
        msg.reasoning.append_delta("world\nnext")
        await pilot.pause()
        log = msg.reasoning.query_one("#reasoning-log")
        # "hello world" committed = 1 line; "next" still in buffer
        assert len(log.lines) == 1
        assert msg.reasoning._live_buf == "next"


@pytest.mark.asyncio
async def test_close_box_flushes_and_stays_visible():
    """close_box flushes remaining buffer; panel stays visible as history."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        await pilot.pause()
        msg.reasoning.open_box("Reasoning")
        msg.reasoning.append_delta("some content")
        await pilot.pause()
        msg.reasoning.close_box()
        await pilot.pause()
        # Panel stays visible so reasoning isn't lost during tool calls
        assert msg.reasoning.has_class("visible")
        log = msg.reasoning.query_one("#reasoning-log")
        # Flushed partial = 1 line
        assert len(log.lines) == 1


@pytest.mark.asyncio
async def test_safe_widget_call_swallows_no_matches():
    """_safe_widget_call does not raise when widget is not found."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Call with a type that doesn't exist — should not raise
        class FakeWidget:
            pass
        _safe_widget_call(app, FakeWidget, "some_method")


@pytest.mark.asyncio
async def test_app_reasoning_helpers():
    """HermesApp convenience methods for reasoning panel work correctly."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        await pilot.pause()
        app.open_reasoning("Test")
        await pilot.pause()
        assert msg.reasoning.has_class("visible")
        app.append_reasoning("thinking...\n")
        await pilot.pause()
        app.close_reasoning()
        await pilot.pause()
        # Panel stays visible as message history after close
        assert msg.reasoning.has_class("visible")


@pytest.mark.asyncio
async def test_reasoning_richlog_has_wrap_true():
    """Reasoning RichLog is created with wrap=True so text reflows on resize.

    Without wrap=True, content rendered during deferred render (when the panel
    transitions from display:none to visible) would be stuck at a narrow width.
    """
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        await pilot.pause()
        rl = msg.reasoning._reasoning_log
        assert isinstance(rl, RichLog)
        assert rl.wrap is True


@pytest.mark.asyncio
async def test_reasoning_text_uses_full_width():
    """Reasoning text wraps to the panel's full width, not a narrow default.

    Regression test: when ReasoningPanel transitions from display:none to
    visible, the RichLog's initial size can be 0. With wrap=True, content
    reflows when the widget gets its real width.
    """
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.agent_running = True
        for _ in range(5):
            await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        rp = msg.reasoning

        rp.open_box("Reasoning")
        long_line = "The user wants me to analyze this request carefully and provide a thorough response"
        rp.append_delta(long_line + "\n")
        for _ in range(10):
            await pilot.pause()

        assert rp.size.width > 20, (
            f"ReasoningPanel should use full width, got {rp.size.width}"
        )
