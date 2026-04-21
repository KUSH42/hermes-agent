"""Tests for ReasoningPanel widget — Step 2."""

from unittest.mock import MagicMock

import pytest
from rich.console import Console

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import OutputPanel, ReasoningPanel, StreamingCodeBlock, _safe_widget_call
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
async def test_close_box_reasserts_visible_class():
    """close_box keeps finalized reasoning mounted even if visibility was lost."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        await pilot.pause()
        rp = msg.reasoning

        rp.open_box("Reasoning")
        rp.append_delta("some content")
        await pilot.pause()

        # Simulate external class churn during finalize path.
        rp.remove_class("visible")
        rp.close_box()
        await pilot.pause()

        assert rp.has_class("visible")
        assert len(rp._plain_lines) == 1


@pytest.mark.asyncio
async def test_close_box_flushes_deferred_render_after_immediate_finalize():
    """Immediate close after a partial delta must flush deferred RichLog renders."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        rp = msg.reasoning

        # No pause between open, append, and close: this reproduces the
        # finalize path where live text disappears before deferred log lines mount.
        rp.open_box("Reasoning")
        rp.append_delta("partial without newline")
        rp.close_box()
        await pilot.pause()

        # The content must be preserved in plain_lines (the actual bug was
        # losing content when close_box hid the live line before deferred
        # renders flushed).  In headless tests, deferred renders may not
        # flush (RichLog._size_known is False), so we verify the content
        # survived rather than checking the render queue.
        assert len(rp._plain_lines) == 1
        assert rp._plain_lines[0] == "partial without newline"


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
async def test_titled_rule_uses_brand_glyph_color_with_leading_space_label():
    """Leading-space labels should still color the first non-space glyph."""
    from hermes_cli.tui.widgets import TitledRule

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.apply_skin(
            {
                "component_vars": {
                    "brand-glyph-color": "#00ff9f",
                    "rule-accent-color": "#00ff41",
                }
            }
        )
        await pilot.pause()

        rule = TitledRule(title=" ⟁ Matrix")
        await app.mount(rule)
        await pilot.pause()

        rendered = rule.render()
        console = Console(force_terminal=True, color_system="truecolor", width=80)
        glyph_style = rendered.get_style_at_offset(console, 1)
        text_style = rendered.get_style_at_offset(console, 3)

        assert glyph_style.color is not None
        assert text_style.color is not None
        assert glyph_style.color.triplet.hex == "#00ff9f"
        assert text_style.color.triplet.hex == "#00ff41"


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


# ---------------------------------------------------------------------------
# ReasoningFlowEngine — 15 new tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reasoning_engine_created_on_mount():
    """ReasoningFlowEngine is created in on_mount when HERMES_MARKDOWN=1."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        rp = msg.reasoning  # trigger lazy mount
        await pilot.pause()  # let on_mount fire
        assert rp._reasoning_engine is not None


@pytest.mark.asyncio
async def test_reasoning_engine_absent_when_disabled(monkeypatch):
    """No engine created when HERMES_MARKDOWN is disabled."""
    monkeypatch.setattr("hermes_cli.tui.response_flow.MARKDOWN_ENABLED", False)
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        rp = msg.reasoning  # trigger lazy mount
        await pilot.pause()  # let on_mount fire
        assert rp._reasoning_engine is None


@pytest.mark.asyncio
async def test_inline_bold_in_reasoning():
    """Bold markdown processed — raw ** not in plain_lines."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        rp = msg.reasoning  # trigger lazy mount
        await pilot.pause()  # let on_mount fire
        rp.open_box("Reasoning")
        rp.append_delta("**bold text**\n")
        await pilot.pause()
        assert len(rp._plain_lines) >= 1
        assert "**" not in rp._plain_lines[0]


@pytest.mark.asyncio
async def test_inline_code_in_reasoning():
    """Inline code backticks stripped from plain_lines."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        rp = msg.reasoning  # trigger lazy mount
        await pilot.pause()  # let on_mount fire
        rp.open_box("Reasoning")
        rp.append_delta("`mycode`\n")
        await pilot.pause()
        assert len(rp._plain_lines) >= 1
        assert "`" not in rp._plain_lines[0]


@pytest.mark.asyncio
async def test_heading_in_reasoning():
    """Heading ## stripped from plain_lines by markdown processing."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        rp = msg.reasoning  # trigger lazy mount
        await pilot.pause()  # let on_mount fire
        rp.open_box("Reasoning")
        rp.append_delta("## My Heading\n")
        await pilot.pause()
        assert len(rp._plain_lines) >= 1
        assert not rp._plain_lines[0].startswith("##")


@pytest.mark.asyncio
async def test_list_item_in_reasoning():
    """List item processed — plain_lines has content (not raw '- item')."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        rp = msg.reasoning  # trigger lazy mount
        await pilot.pause()  # let on_mount fire
        rp.open_box("Reasoning")
        rp.append_delta("- my item\n")
        await pilot.pause()
        assert len(rp._plain_lines) >= 1
        # Engine renders "- " as a bullet symbol
        assert rp._plain_lines[0] != "- my item"


@pytest.mark.asyncio
async def test_fenced_code_block_in_reasoning():
    """Fenced code block mounts a StreamingCodeBlock inside ReasoningPanel."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        rp = msg.reasoning  # trigger lazy mount
        await pilot.pause()  # let on_mount fire
        rp.open_box("Reasoning")
        rp.append_delta("```python\n")
        rp.append_delta("x = 1\n")
        rp.append_delta("```\n")
        await pilot.pause()  # let StreamingCodeBlock mount
        blocks = list(rp.query(StreamingCodeBlock))
        assert len(blocks) >= 1


@pytest.mark.asyncio
async def test_reasoning_code_block_has_dim_class():
    """Code block mounted by ReasoningFlowEngine gets reasoning-code-block class."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        rp = msg.reasoning  # trigger lazy mount
        await pilot.pause()  # let on_mount fire
        rp.open_box("Reasoning")
        rp.append_delta("```python\n")
        rp.append_delta("y = 2\n")
        rp.append_delta("```\n")
        await pilot.pause()  # let StreamingCodeBlock mount
        blocks = list(rp.query(StreamingCodeBlock))
        assert len(blocks) >= 1
        assert blocks[0].has_class("reasoning-code-block")


@pytest.mark.asyncio
async def test_unclosed_fence_flushed_on_close_box():
    """Unclosed fence is flushed (FLUSHED state) when close_box() is called."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        rp = msg.reasoning  # trigger lazy mount
        await pilot.pause()  # let on_mount fire
        rp.open_box("Reasoning")
        rp.append_delta("```python\n")
        rp.append_delta("z = 3\n")
        await pilot.pause()  # let StreamingCodeBlock mount
        # No closing fence — close_box flushes
        rp.close_box()
        await pilot.pause()
        blocks = list(rp.query(StreamingCodeBlock))
        assert len(blocks) >= 1
        assert blocks[0]._state == "FLUSHED"
        assert rp._reasoning_engine._active_block is None


@pytest.mark.asyncio
async def test_code_block_content_correct():
    """Code lines inside fence appear in block._code_lines, not _plain_lines."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        rp = msg.reasoning  # trigger lazy mount
        await pilot.pause()  # let on_mount fire
        rp.open_box("Reasoning")
        rp.append_delta("```python\n")
        rp.append_delta("a = 42\n")
        rp.append_delta("```\n")
        await pilot.pause()  # let StreamingCodeBlock mount
        blocks = list(rp.query(StreamingCodeBlock))
        assert len(blocks) >= 1
        assert "a = 42" in blocks[0]._code_lines
        assert not any("a = 42" in ln for ln in rp._plain_lines)


@pytest.mark.asyncio
async def test_fallback_raw_line_written(monkeypatch):
    """When engine absent (HERMES_MARKDOWN=0), raw line written to log."""
    monkeypatch.setattr("hermes_cli.tui.response_flow.MARKDOWN_ENABLED", False)
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        await pilot.pause()
        rp = msg.reasoning
        assert rp._reasoning_engine is None
        rp.open_box("Reasoning")
        rp.append_delta("raw line\n")
        await pilot.pause()
        assert "raw line" in rp._plain_lines


@pytest.mark.asyncio
async def test_open_box_after_delta_preserves_content():
    """open_box after deltas does NOT call _reasoning_log.clear()."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        await pilot.pause()
        rp = msg.reasoning

        rp.open_box("First")
        rp.append_delta("first line\n")
        await pilot.pause()

        # Intercept clear() to detect if it fires
        cleared = []
        orig_clear = rp._reasoning_log.clear
        rp._reasoning_log.clear = lambda: cleared.append(True) or orig_clear()

        rp.open_box("Second")
        await pilot.pause()

        assert len(cleared) == 0, "_reasoning_log.clear() called despite prior content"


@pytest.mark.asyncio
async def test_open_box_before_delta_clears_log():
    """open_box on fresh panel (no prior content) calls _reasoning_log.clear()."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        await pilot.pause()
        rp = msg.reasoning

        # No deltas before open_box — _plain_lines is empty
        cleared = []
        orig_clear = rp._reasoning_log.clear
        rp._reasoning_log.clear = lambda: cleared.append(True) or orig_clear()

        rp.open_box("Reasoning")
        await pilot.pause()

        assert len(cleared) == 1, "_reasoning_log.clear() not called on fresh panel"


@pytest.mark.asyncio
async def test_close_box_flushes_engine():
    """close_box flushes partial line + open fence via engine."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        rp = msg.reasoning  # trigger lazy mount
        await pilot.pause()  # let on_mount fire
        rp.open_box("Reasoning")
        rp.append_delta("```python\n")
        await pilot.pause()  # let StreamingCodeBlock mount
        rp.append_delta("partial_code")  # partial line, no newline
        await pilot.pause()
        rp.close_box()
        await pilot.pause()
        assert rp._live_buf == ""
        assert rp._reasoning_engine._active_block is None
        blocks = list(rp.query(StreamingCodeBlock))
        assert len(blocks) >= 1
        assert blocks[0]._state == "FLUSHED"


@pytest.mark.asyncio
async def test_close_box_with_no_engine_fallback(monkeypatch):
    """When engine absent, close_box flushes partial line via raw path."""
    monkeypatch.setattr("hermes_cli.tui.response_flow.MARKDOWN_ENABLED", False)
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        msg = _ensure_message(app)
        await pilot.pause()
        rp = msg.reasoning
        assert rp._reasoning_engine is None
        rp.open_box("Reasoning")
        rp.append_delta("partial no newline")
        await pilot.pause()
        rp.close_box()
        await pilot.pause()
        assert rp._live_buf == ""
        assert "partial no newline" in rp._plain_lines
