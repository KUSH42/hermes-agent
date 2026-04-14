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
        # _plain_lines is updated synchronously when lines are committed;
        # log.lines only reflects rendered strips which require _size_known=True
        assert len(msg.reasoning._plain_lines) == 2


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
        # No lines committed — partial text is in _live_buf
        assert len(msg.reasoning._plain_lines) == 0
        assert msg.reasoning._live_buf == "partial text"
        assert msg.reasoning._live_line.display is True
        assert "partial text" in str(msg.reasoning._live_line.render())


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
        # "hello world" committed = 1 plain line; "next" still in buffer
        assert len(msg.reasoning._plain_lines) == 1
        assert msg.reasoning._live_buf == "next"
        assert msg.reasoning._live_line.display is True
        assert "next" in str(msg.reasoning._live_line.render())


@pytest.mark.asyncio
async def test_close_box_flushes_and_stays_visible():
    """close_box flushes remaining buffer; panel stays visible as history."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        # Extra pause to let MessagePanel.on_mount call_after_refresh settle
        await pilot.pause()
        await pilot.pause()
        msg.reasoning.open_box("Reasoning")
        msg.reasoning.append_delta("some content")
        await pilot.pause()
        msg.reasoning.close_box()
        await pilot.pause()
        await pilot.pause()
        # Panel stays visible so reasoning isn't lost during tool calls
        assert msg.reasoning.has_class("visible")
        # Flushed partial = 1 plain line (close_box flushes _live_buf)
        assert len(msg.reasoning._plain_lines) == 1
        assert msg.reasoning._live_line.display is False


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

        output = app.query_one(OutputPanel)
        msg = output.current_message or output.new_message("hello")
        await pilot.pause()
        rp = msg.reasoning

        rp.open_box("Reasoning")
        long_line = "The user wants me to analyze this request carefully and provide a thorough response"
        rp.append_delta(long_line + "\n")
        for _ in range(10):
            await pilot.pause()

        assert rp.size.width > 20, (
            f"ReasoningPanel should use full width, got {rp.size.width}"
        )


# ---------------------------------------------------------------------------
# Collapse feature (P1-A)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reasoning_panel_collapse_toggle():
    """Clicking ReasoningPanel after close_box() toggles body display."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        rp = msg.reasoning

        rp.open_box("Reasoning")
        rp.append_delta("line one\n")
        rp.close_box()
        await pilot.pause()

        # After close, panel should have --closeable class
        assert rp.has_class("--closeable")
        # Body starts expanded
        assert rp._body_collapsed is False
        assert rp._reasoning_log.styles.display != "none"

        # Simulate click — toggle collapse
        rp.on_click()
        await pilot.pause()
        assert rp._body_collapsed is True
        assert rp.has_class("--collapsed")
        assert rp._reasoning_log.styles.display == "none"
        assert "click to expand" in str(rp._collapsed_stub._Static__content)

        # Second click — expand again
        rp.on_click()
        await pilot.pause()
        assert rp._body_collapsed is False
        assert not rp.has_class("--collapsed")
        assert rp._reasoning_log.styles.display != "none"


@pytest.mark.asyncio
async def test_reasoning_panel_click_ignored_during_streaming():
    """on_click does nothing while streaming is in progress (before close_box)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        rp = msg.reasoning

        rp.open_box("Reasoning")
        rp.append_delta("partial line\n")
        await pilot.pause()

        # Click during streaming — must be a no-op
        rp.on_click()
        await pilot.pause()
        assert rp._body_collapsed is False
        assert not rp.has_class("--closeable")


@pytest.mark.asyncio
async def test_reasoning_panel_open_resets_collapse():
    """open_box() resets collapsed state for re-use across turns."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        rp = msg.reasoning

        rp.open_box("Reasoning")
        rp.append_delta("first\n")
        rp.close_box()
        rp.on_click()  # collapse
        await pilot.pause()
        assert rp._body_collapsed is True

        # Re-open (new turn) — must reset
        rp.open_box("Reasoning")
        await pilot.pause()
        assert rp._body_collapsed is False
        assert not rp.has_class("--collapsed")
        assert not rp.has_class("--closeable")


@pytest.mark.asyncio
async def test_titled_rule_shows_timestamp():
    """Per-turn TitledRule shows HH:MM timestamp when created_at is set."""
    import datetime
    from hermes_cli.tui.widgets import TitledRule

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        msg = output.new_message("hello")
        await pilot.pause()

        rule = msg._response_rule
        # created_at is set on the rule from MessagePanel.__init__
        assert rule._created_at is not None
        # The rendered text includes HH:MM
        msg.show_response_rule()
        await pilot.pause()
        rendered = str(rule.render())
        # Just check the rule has a created_at — timestamp format depends on time
        assert isinstance(rule._created_at, datetime.datetime)
        assert rule._created_at.strftime("%H:%M") in rendered


@pytest.mark.asyncio
async def test_titled_rule_shows_response_metrics_before_timestamp():
    """Per-turn TitledRule shows tok/s + elapsed left of timestamp."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        msg = output.new_message("hello")
        msg.show_response_rule()
        msg.set_response_metrics(tok_s=42.0, elapsed_s=2.4, streaming=False)
        await pilot.pause()

        rule = msg._response_rule
        rendered = str(rule.render())
        ts = rule._created_at.strftime("%H:%M")
        assert "42 tok/s" in rendered
        assert "2.4s" in rendered
        assert rendered.index("42 tok/s") < rendered.index(ts)


@pytest.mark.asyncio
async def test_startup_message_panel_hides_response_rule():
    """Startup/banner panel should not show the per-turn titled rule."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        msg = output.new_message(show_header=False)
        await pilot.pause()

        msg.show_response_rule()
        await pilot.pause()

        assert not msg._response_rule.has_class("visible")
