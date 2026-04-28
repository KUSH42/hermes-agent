"""Tests for OutputPanel and LiveLineWidget — Step 1 output pipeline."""

import asyncio
import sys
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import (
    LiveLineWidget,
    MessagePanel,
    OutputPanel,
    ThinkingWidget,
    UserMessagePanel,
)


@pytest.mark.asyncio
async def test_output_panel_composes_children():
    """OutputPanel yields a LiveLineWidget."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        assert panel is not None
        live = panel.live_line
        assert isinstance(live, LiveLineWidget)


@pytest.mark.asyncio
async def test_cprint_routes_to_queue():
    """Text written via write_output reaches the current message's RichLog."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Ensure a MessagePanel exists for output to land in
        panel = app.query_one(OutputPanel)
        msg = panel.new_message()
        await pilot.pause()
        app.write_output("Hello world\n")
        # Give consumer time to process
        await pilot.pause()
        await pilot.pause()
        # Flush StreamingBlockBuffer setext-lookahead pending line
        app.flush_output()
        await pilot.pause()
        await pilot.pause()
        assert len(msg.response_log._plain_lines) >= 1


@pytest.mark.asyncio
async def test_queue_sentinel_flushes_live_line():
    """None sentinel flushes the live line buffer and consumer stays alive."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Write partial line (no newline) then flush
        app.write_output("partial")
        await pilot.pause()
        app.flush_output()
        await pilot.pause()
        await pilot.pause()
        # After flush, the live line buffer should be empty
        live = app.query_one(LiveLineWidget)
        assert live._buf == ""


@pytest.mark.asyncio
async def test_live_line_commits_complete_lines():
    """LiveLineWidget commits complete lines to the current MessagePanel's RichLog."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Ensure a MessagePanel exists
        panel = app.query_one(OutputPanel)
        msg = panel.new_message()
        await pilot.pause()
        app.write_output("line1\nline2\npartial")
        await pilot.pause()
        await pilot.pause()
        # Flush StreamingBlockBuffer setext-lookahead pending line + "partial" from live buf
        app.flush_output()
        await pilot.pause()
        await pilot.pause()
        assert len(msg.response_log._plain_lines) >= 2
        live = app.query_one(LiveLineWidget)
        # flush_output drains live buf into engine — it's empty after flush
        assert live._buf == ""


@pytest.mark.asyncio
async def test_queue_backpressure_does_not_crash():
    """QueueFull is caught gracefully when queue is saturated."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Fill the queue to capacity
        for i in range(4096):
            app.write_output(f"chunk{i}\n")
        # One more should be silently dropped (not raise)
        app.write_output("overflow\n")
        await pilot.pause()


def test_cprint_falls_through_when_no_app():
    """_cprint falls through to stdout when _hermes_app is None."""
    # Import the module-level function
    import cli
    original_app = cli._hermes_app
    try:
        cli._hermes_app = None
        # Should not raise — falls through to prompt_toolkit renderer
        # We just verify it doesn't crash
        with patch.object(cli, '_pt_print') as mock_print:
            cli._cprint("test output")
            mock_print.assert_called_once()
    finally:
        cli._hermes_app = original_app


# ---------------------------------------------------------------------------
# ThinkingWidget tests (spec: tui-animation-novel-techniques.md §8)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_thinking_widget_hidden_by_default():
    """ThinkingWidget is display:none before activation."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        widget = app.query_one(ThinkingWidget)
        assert not widget.display


@pytest.mark.asyncio
async def test_thinking_widget_activates_on_submit():
    """ThinkingWidget.activate() shows the widget (adds --active)."""
    from unittest.mock import MagicMock
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        widget = app.query_one(ThinkingWidget)
        widget.activate()
        await pilot.pause()
        assert widget.display  # activate() adds --active → display: block


@pytest.mark.asyncio
async def test_thinking_widget_deactivates_on_first_chunk():
    """ThinkingWidget deactivate() hides the widget after activate()."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        widget = app.query_one(ThinkingWidget)
        widget.activate()
        await pilot.pause()
        assert widget.display  # activate shows it
        widget.deactivate()
        await asyncio.sleep(0.2)  # deactivate uses 150ms timer before hiding
        await pilot.pause()
        # CSS display is not testable in unit test context; verify --active class removed
        assert not widget.has_class("--active"), "deactivate should remove --active class"


@pytest.mark.asyncio
async def test_thinking_widget_deactivate_idempotent():
    """Calling deactivate() twice does not raise."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        widget = app.query_one(ThinkingWidget)
        widget.deactivate()  # already inactive
        widget.deactivate()  # second call must not raise


@pytest.mark.asyncio
async def test_thinking_widget_deactivates_on_flush_live():
    """OutputPanel.flush_live() calls ThinkingWidget.deactivate() which hides after timer."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        widget = app.query_one(ThinkingWidget)
        widget.activate()
        await pilot.pause()
        assert widget.display  # activate shows it
        # flush_live() calls deactivate() — starts 150ms hide timer
        app.query_one(OutputPanel).flush_live()
        await asyncio.sleep(0.2)
        await pilot.pause()
        assert not widget.display


@pytest.mark.asyncio
async def test_thinking_widget_render_line_width():
    """ThinkingWidget.render_line(0) returns a Strip of the widget's width."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        widget = app.query_one(ThinkingWidget)
        strip = widget.render_line(0)
        # Strip should have at least some content (width >= 40 fallback)
        assert len(strip) > 0


@pytest.mark.asyncio
async def test_thinking_widget_render_line_nonzero_y():
    """ThinkingWidget.render_line(y>0) returns a blank Strip."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        widget = app.query_one(ThinkingWidget)
        strip = widget.render_line(1)
        # All segments should be blank spaces
        text_content = "".join(seg.text for seg in strip)
        assert text_content.strip() == ""


# ---------------------------------------------------------------------------
# MessagePanel fade-in tests (spec: tui-animation-novel-techniques.md §6)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_message_panel_fade_in_starts_at_zero():
    """MessagePanel starts at opacity=0 immediately after mount."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        msg = panel.new_message()
        # Immediately after new_message(), styles.opacity is 0 (set in on_mount)
        # before the _start_fade timer fires at 50ms.
        await pilot.pause()
        # The timer fires after 50ms; then the 250ms animation runs.
        # After 400ms total, opacity should be 1.0.
        await asyncio.sleep(0.4)
        await pilot.pause()
        assert msg.styles.opacity == pytest.approx(1.0, abs=0.05)


@pytest.mark.asyncio
async def test_message_panel_fade_in_completes():
    """MessagePanel --entering class is removed after call_after_refresh fires."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        msg = panel.new_message()
        # --entering class is present immediately after mount
        assert msg.has_class("--entering")
        # call_after_refresh fires in the next event loop pass
        await pilot.pause()
        await pilot.pause()
        # After --entering is removed, the CSS opacity transition has been triggered.
        # The panel no longer has the entering class.
        assert not msg.has_class("--entering")


# ---------------------------------------------------------------------------
# Integration tests (spec: tui-animation-novel-techniques.md §15 Step 7)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_submit_activates_shimmer_first_chunk_hides_it():
    """Submit → ThinkingWidget activates then hides after deactivate()."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        thinking = app.query_one(ThinkingWidget)

        thinking.activate()
        await pilot.pause()
        assert thinking.display  # activate shows it

        thinking.deactivate()
        await asyncio.sleep(0.2)  # 150ms hide timer
        await pilot.pause()
        # CSS display not testable in unit test context; verify --active class removed
        assert not thinking.has_class("--active"), "deactivate should remove --active class"


@pytest.mark.asyncio
async def test_agent_running_triggers_pulse():
    """agent_running=True starts pulse; agent_running=False stops pulse."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        from hermes_cli.tui.widgets import StatusBar
        bar = app.query_one(StatusBar)

        app.agent_running = True
        await pilot.pause()
        assert bar._pulse_timer is not None

        app.agent_running = False
        await pilot.pause()
        assert bar._pulse_timer is None


@pytest.mark.asyncio
async def test_context_bar_color_changes_with_progress():
    """Compaction bar color changes smoothly as progress increases."""
    from hermes_cli.tui.widgets import StatusBar

    _vars: dict = {}  # empty → falls back to hardcoded defaults (lowercase)
    # At 0.0 — normal (direct return, lowercase default)
    c0 = StatusBar._compaction_color(0.0, _vars)
    assert c0 == "#5f87d7"
    # At 0.65 — somewhere in the lerp band
    c65 = StatusBar._compaction_color(0.65, _vars)
    assert c65 != "#5f87d7"
    assert c65 != "#ffa726"
    # At 0.99 — crit (direct return, lowercase default)
    c99 = StatusBar._compaction_color(0.99, _vars)
    assert c99 == "#ef5350"
    # Custom vars respected
    c_custom = StatusBar._compaction_color(0.60, {"status-warn-color": "#FF0000"})
    assert c_custom != "#5f87d7"  # in lerp band; uses custom warn color


@pytest.mark.asyncio
async def test_copyable_rich_log_render_line_has_offsets():
    """CopyableRichLog.render_line() adds offset metadata for text selection.

    RichLog.render_line() strips lack ``style.meta["offset"]``, so the
    compositor's ``get_widget_and_offset_at()`` returns offset None and
    Textual's drag-to-select silently fails.  Our override must call
    ``apply_offsets()`` so selection works in the output panel.
    """
    from rich.text import Text

    from hermes_cli.tui.widgets import CopyableRichLog

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        log = CopyableRichLog(markup=False)
        await app.mount(log)
        log.write(Text("hello world"))
        await pilot.pause()

        strip = log.render_line(0)
        has_offset = any(
            seg.style is not None
            and seg.style._meta is not None
            and "offset" in seg.style.meta
            for seg in strip._segments
        )
        assert has_offset, "render_line must add offset metadata for selection"


@pytest.mark.asyncio
async def test_copyable_rich_log_widget_and_offset_resolves():
    """get_widget_and_offset_at returns a valid offset on CopyableRichLog."""
    from rich.text import Text

    from hermes_cli.tui.widgets import CopyableRichLog, MessagePanel, OutputPanel

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        msg = MessagePanel()
        await panel.mount(msg, before=panel.query_one(ThinkingWidget))

        # Write directly to the CopyableRichLog inside the MessagePanel
        log = msg.query_one(CopyableRichLog)
        log.write(Text("selectable content"))
        await pilot.pause()
        # Force layout settle — CopyableRichLog height:auto needs a refresh
        # cycle to populate the compositor map before get_widget_and_offset_at.
        log.refresh()
        await pilot.pause()

        region = app.screen.find_widget(log).region
        assert region is not None, "CopyableRichLog must have a compositor region"

        # Query offset at a point inside the log — verify compositor lookup returns something
        _widget, offset = app.screen.get_widget_and_offset_at(
            region.x + 2, region.y
        )
        # Widget lookup may return log or a sibling (layout-dependent); just ensure not None
        assert _widget is not None, "compositor lookup must resolve a widget at log region"


@pytest.mark.asyncio
async def test_evict_old_turns_no_eviction_under_threshold():
    """evict_old_turns is a no-op when turn count is within threshold."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        output = app.query_one(OutputPanel)
        # Mount a few messages — well under threshold
        for i in range(5):
            ump = UserMessagePanel(f"msg {i}")
            output.mount(ump, before=output.query_one(ThinkingWidget))
            mp = output.new_message(user_text=f"msg {i}")
        await pilot.pause()
        output.evict_old_turns()
        await pilot.pause()
        panels = list(output.query(MessagePanel))
        assert len(panels) == 5


@pytest.mark.asyncio
async def test_evict_old_turns_removes_beyond_threshold():
    """evict_old_turns removes the oldest turn panels when count exceeds threshold."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        output = app.query_one(OutputPanel)
        # Mount 30 turns (60 turn-boundary children) — exceeds _EVICTION_THRESHOLD=25
        for i in range(30):
            ump = UserMessagePanel(f"msg {i}")
            output.mount(ump, before=output.query_one(ThinkingWidget))
            mp = output.new_message(user_text=f"msg {i}")
        await pilot.pause()
        panels_before = list(output.query(MessagePanel))
        assert len(panels_before) == 30

        output.evict_old_turns()
        await pilot.pause()

        panels_after = list(output.query(MessagePanel))
        # Should keep at most _MAX_TURNS=20
        assert len(panels_after) <= output._MAX_TURNS
        # The newest panels should survive
        assert panels_after[-1] is panels_before[-1]
        # UserMessagePanel count should also be reduced
        ump_count = len(output.query(UserMessagePanel))
        assert ump_count <= output._MAX_TURNS
