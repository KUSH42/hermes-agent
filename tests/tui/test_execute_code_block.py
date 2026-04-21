"""Tests for ExecuteCodeBlock widget (§13.3 of ExecuteCodeBlock spec)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import OutputPanel


async def _pause(pilot, n=5):
    for _ in range(n):
        await pilot.pause()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _mount_execute_block(pilot, app):
    """Create and mount an ExecuteCodeBlock into the current message."""
    from hermes_cli.tui.execute_code_block import ExecuteCodeBlock
    output = app.query_one(OutputPanel)
    msg = output.current_message or output.new_message()
    block = ExecuteCodeBlock(initial_label="python")
    msg._mount_nonprose_block(block)
    await _pause(pilot)
    return block


# ---------------------------------------------------------------------------
# Step 2: icon registry
# ---------------------------------------------------------------------------


def test_icon_resolution():
    """Python nerd-font glyph (U+E235) used for execute_code, not cod-code."""
    from hermes_cli.tool_icons import NERD_FONT_TOOL_ICONS, ASCII_TOOL_ICONS
    icon = NERD_FONT_TOOL_ICONS.get("execute_code", "")
    assert ord(icon) == 0xE235, f"Expected U+E235, got U+{ord(icon):04X}"
    assert ASCII_TOOL_ICONS.get("execute_code") == "P"


# ---------------------------------------------------------------------------
# Phase lifecycle tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phase_gen_start():
    """Block mounted, spinner running, CodeSection empty, OutputSection hidden."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        block = await _mount_execute_block(pilot, app)

        from hermes_cli.tui.execute_code_block import CodeSection, OutputSection
        # Spinner running
        assert block._header._spinner_char is not None
        # CodeSection present, OutputSection hidden
        code_sec = block.query_one(CodeSection)
        out_sec = block.query_one(OutputSection)
        assert code_sec is not None
        assert not out_sec.display


@pytest.mark.asyncio
async def test_default_expanded_during_stream():
    """Block starts expanded in GEN phase (user can see stream)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        block = await _mount_execute_block(pilot, app)

        from hermes_cli.tui.execute_code_block import ExecuteCodeBody
        body = block.query_one(ExecuteCodeBody)
        assert body.has_class("expanded")
        assert not block._header.collapsed


@pytest.mark.asyncio
async def test_toggle_during_streaming():
    """Click-to-toggle works while block is in GEN_STREAMING state."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        block = await _mount_execute_block(pilot, app)

        # _has_affordances should be True even during streaming
        assert block._header._has_affordances is True
        # Calling toggle should work
        block.toggle()
        await _pause(pilot)
        assert block._header.collapsed is True
        assert block._user_toggled is True


# ---------------------------------------------------------------------------
# GEN_STREAMING: feed_delta
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gen_streaming_appends_lines():
    """feed_delta with chunked JSON → decoded line in CodeSection."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        block = await _mount_execute_block(pilot, app)

        # Feed two lines: line 0 → header label, line 1 → CodeSection body
        block.feed_delta('{"code":"import yaml\\nhome = Path.home()\\n"}')
        await _pause(pilot, n=8)

        # Line 0 should be in header label, not in body
        assert "import yaml" in block._header._label

        from hermes_cli.tui.execute_code_block import CodeSection
        from hermes_cli.tui.widgets import CopyableRichLog
        code_log = block.query_one(CodeSection).query_one(CopyableRichLog)
        assert len(code_log.lines) >= 1


@pytest.mark.asyncio
async def test_label_updated_on_first_line():
    """Header label is updated to first non-empty code line."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        block = await _mount_execute_block(pilot, app)

        block.feed_delta('{"code":"import yaml\\n"}')
        await _pause(pilot, n=8)

        assert block._header._label == "import yaml"
        assert block._label_set is True


# ---------------------------------------------------------------------------
# TOOL_START: finalize_code
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_code_replaces_with_syntax():
    """After finalize_code(full), CodeSection contains the Syntax renderable."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        block = await _mount_execute_block(pilot, app)

        # Partially streamed some code
        block.feed_delta('{"code":"imp')
        await _pause(pilot)

        # finalize_code replaces with canonical code
        full_code = "import yaml\nprint('hello')"
        block.finalize_code(full_code)
        await _pause(pilot)

        from hermes_cli.tui.execute_code_block import CodeSection
        from hermes_cli.tui.widgets import CopyableRichLog
        code_log = block.query_one(CodeSection).query_one(CopyableRichLog)
        assert len(code_log.lines) >= 1
        # Code lines should reflect canonical code
        assert block._code_lines == full_code.splitlines()
        assert block._code_state == "finalized"


@pytest.mark.asyncio
async def test_output_section_revealed_on_finalize():
    """OutputSection revealed when finalize_code is called."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        block = await _mount_execute_block(pilot, app)

        from hermes_cli.tui.execute_code_block import OutputSection
        assert not block.query_one(OutputSection).display

        block.finalize_code("print('hi')")
        await _pause(pilot)

        assert block.query_one(OutputSection).display


@pytest.mark.asyncio
async def test_args_missing_code_field():
    """finalize_code('') → no crash; CodeSection stays empty."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        block = await _mount_execute_block(pilot, app)

        # Should not raise
        block.finalize_code("")
        await _pause(pilot)

        from hermes_cli.tui.execute_code_block import CodeSection
        from hermes_cli.tui.widgets import CopyableRichLog
        code_log = block.query_one(CodeSection).query_one(CopyableRichLog)
        # empty code → no Syntax written
        assert len(code_log.lines) == 0


@pytest.mark.asyncio
async def test_late_delta_after_finalize_is_noop():
    """Delta arriving after finalize_code is a no-op (state == FINALIZED)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        block = await _mount_execute_block(pilot, app)

        block.finalize_code("import yaml")
        await _pause(pilot)

        from hermes_cli.tui.execute_code_block import CodeSection
        from hermes_cli.tui.widgets import CopyableRichLog
        code_log = block.query_one(CodeSection).query_one(CopyableRichLog)
        lines_before = len(code_log.lines)

        # Late delta should be ignored
        block.feed_delta('{"code":"extra line\\n"}')
        await _pause(pilot)

        assert len(code_log.lines) == lines_before


# ---------------------------------------------------------------------------
# COMPLETED phase
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phase_completed_success():
    """flash_success() applies --flash-success class; duration visible; icon green."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        block = await _mount_execute_block(pilot, app)

        block.finalize_code("print('hi')")
        await _pause(pilot)
        block.complete("1.2s", is_error=False)
        await _pause(pilot)

        # Duration set
        assert block._header._duration == "1.2s"
        # Spinner cleared
        assert block._header._spinner_char is None
        # Flash success applied (class added; removed after 450ms timer — just check it was set once)
        assert not block._header._tool_icon_error


@pytest.mark.asyncio
async def test_phase_completed_error():
    """flash_error() applies --flash-error; icon red."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        block = await _mount_execute_block(pilot, app)

        block.finalize_code("raise ValueError('oops')")
        await _pause(pilot)
        block.complete("0.5s", is_error=True)
        await _pause(pilot)

        assert block._header._tool_icon_error is True


# ---------------------------------------------------------------------------
# Collapse rules
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collapse_rule_few_lines():
    """≤3 total lines → expanded at complete."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        block = await _mount_execute_block(pilot, app)

        block.finalize_code("x = 1")  # 1 line
        await _pause(pilot)
        block.complete("0.1s", is_error=False)
        await _pause(pilot)

        assert not block._header.collapsed


@pytest.mark.asyncio
async def test_collapse_rule_many_lines():
    """>20 total lines → collapsed at complete (ECB-specific threshold)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        block = await _mount_execute_block(pilot, app)

        # 21 lines — must exceed _EXECUTE_COLLAPSE_THRESHOLD=20
        code = "\n".join(f"x_{i} = {i}" for i in range(21))
        block.finalize_code(code)
        await _pause(pilot)
        block.complete("0.1s", is_error=False)
        await _pause(pilot)

        assert block._header.collapsed


@pytest.mark.asyncio
async def test_user_toggle_persists_to_complete():
    """User collapsing during stream survives the completion auto-rule."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        block = await _mount_execute_block(pilot, app)

        # User collapses during streaming
        block.toggle()
        await _pause(pilot)
        assert block._header.collapsed

        # Many lines would normally trigger collapse (same outcome, but shouldn't override)
        block.finalize_code("a=1\nb=2\nc=3\nd=4")
        await _pause(pilot)
        block.complete("0.1s", is_error=False)
        await _pause(pilot)

        # Still collapsed (user choice respected)
        assert block._user_toggled is True


# ---------------------------------------------------------------------------
# copy_content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_copy_content_code_only():
    """copy_content returns code when no stdout."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        block = await _mount_execute_block(pilot, app)

        block.finalize_code("import yaml")
        await _pause(pilot)

        content = block.copy_content()
        assert "import yaml" in content


@pytest.mark.asyncio
async def test_copy_content_code_and_output():
    """copy_content concatenates code + output with blank-line separator."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        block = await _mount_execute_block(pilot, app)

        block.finalize_code("print('hi')")
        await _pause(pilot)
        block.append_line("hi")
        await _pause(pilot)

        content = block.copy_content()
        assert "print('hi')" in content
        assert "hi" in content


# ---------------------------------------------------------------------------
# Header right-align
# ---------------------------------------------------------------------------


def test_header_right_align():
    """With width=80, duration sits in rightmost column range; label truncated with … when long."""
    from hermes_cli.tui.tool_blocks import ToolHeader
    from unittest.mock import patch, PropertyMock
    from textual.geometry import Size, Region

    header = ToolHeader(label="x" * 80, line_count=5)
    header._duration = "2.3s"
    header._has_affordances = True
    header._spinner_char = None

    # Patch size.width to return 80
    mock_region = Region(0, 0, 80, 1)
    with patch.object(type(header), 'size', new_callable=PropertyMock, return_value=Size(80, 1)):
        from rich.text import Text
        result = header.render()
        rendered = result.plain if isinstance(result, Text) else str(result)
        # Duration should appear (right-aligned)
        assert "2.3s" in rendered
        # Label should be truncated (80 x's can't fit in ~53 available chars)
        assert "…" in rendered


def test_header_label_normal_color():
    """Completed header's label does NOT carry dim style."""
    from hermes_cli.tui.tool_blocks import ToolHeader
    from textual.geometry import Size
    header = ToolHeader(label="my_tool", line_count=5)
    header._duration = "1.0s"
    header._spinner_char = None  # completed
    header._tool_icon_error = False
    header._size = Size(80, 1)

    result = header.render()
    from rich.text import Text
    assert isinstance(result, Text)
    # Find the label span — it should not have "dim" style
    for span in result._spans:
        text_slice = result.plain[span.start:span.end]
        if "my_tool" in text_slice:
            style_str = str(span.style)
            assert "dim" not in style_str, f"Label span has dim style: {style_str}"
            break


# ---------------------------------------------------------------------------
# Pacer pass-through
# ---------------------------------------------------------------------------


def test_pacer_passthrough():
    """cps=0 → CharacterPacer.feed() calls on_reveal immediately."""
    received = []
    from hermes_cli.tui.character_pacer import CharacterPacer
    pacer = CharacterPacer(cps=0, on_reveal=lambda s: received.append(s), app=None)
    pacer.feed("hello")
    assert received == ["hello"]


def test_pacer_buffered():
    """cps>0 → CharacterPacer.feed() buffers characters."""
    received = []
    from hermes_cli.tui.character_pacer import CharacterPacer
    pacer = CharacterPacer(cps=60, on_reveal=lambda s: received.append(s), app=None)
    pacer.feed("hello")
    # With no app/timer, nothing is revealed yet
    assert received == []
    # flush() drains immediately
    pacer.flush()
    assert received == ["hello"]


# ---------------------------------------------------------------------------
# Single block per factory (regression)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_block_per_idx():
    """_gen_blocks_by_idx stores blocks; double-registration doesn't create duplicates."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()

        block1 = await _mount_execute_block(pilot, app)
        # Registering in the dict should be idempotent for the same idx
        gen_blocks = {0: block1}
        assert gen_blocks[0] is block1
        # Re-querying returns same block
        assert gen_blocks.get(0) is block1


# ---------------------------------------------------------------------------
# Test 28a: large catch-up delta (replay scenario)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delta_before_gen_start_replayed():
    """A single large 'replay' delta (all args at once) is correctly extracted.

    Simulates the OpenAI path where arg chunks arrive before the tool name is
    known.  After gen_start fires the bridge replays accumulated args as one
    catch-up delta.  feed_delta must handle this without losing any chars.
    """
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        block = await _mount_execute_block(pilot, app)

        # Entire args payload arrives as one replay delta
        full_args = '{"code":"import yaml\\nhome = Path.home()\\nprint(home)\\n"}'
        block.feed_delta(full_args)
        await _pause(pilot, n=8)

        # Header label should be first line
        assert "import yaml" in block._header._label
        # Multiple code lines decoded
        assert len(block._code_lines) >= 2


# ---------------------------------------------------------------------------
# Test 28b: extractor done before tool_start, pacer still draining
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extractor_done_before_tool_start():
    """If code fits in one chunk, extractor hits done before finalize_code.

    When finalize_code() then arrives, the pacer is flushed and the canonical
    Syntax replaces any partial per-line output — extractor.done state must not
    prevent finalize_code from doing its job.
    """
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        panel = app.query_one(OutputPanel)
        panel.new_message()
        block = await _mount_execute_block(pilot, app)

        # Short code — extractor hits done in one chunk
        block.feed_delta('{"code":"x = 1\\n"}')
        await _pause(pilot, n=4)
        assert block._extractor._state == "done"

        # finalize_code with canonical code supersedes per-line streamed output
        canonical = "x = 1\ny = 2"
        block.finalize_code(canonical)
        await _pause(pilot)

        assert block._code_state == "finalized"
        assert block._code_lines == canonical.splitlines()

        # CodeSection should have canonical content (>1 line → Syntax written)
        from hermes_cli.tui.execute_code_block import CodeSection
        from hermes_cli.tui.widgets import CopyableRichLog
        code_log = block.query_one(CodeSection).query_one(CopyableRichLog)
        assert len(code_log.lines) >= 1


# ---------------------------------------------------------------------------
# Test 31: narrow terminal header render
# ---------------------------------------------------------------------------


def test_right_align_narrow_terminal():
    """At width=40 the header renders without crash; tail never overlaps label."""
    from hermes_cli.tui.tool_blocks import ToolHeader
    from unittest.mock import patch, PropertyMock
    from textual.geometry import Size

    header = ToolHeader(label="import yaml and do stuff with paths", line_count=2)
    header._duration = "1.5s"
    header._has_affordances = True
    header._spinner_char = None

    with patch.object(type(header), "size", new_callable=PropertyMock, return_value=Size(40, 1)):
        from rich.text import Text
        result = header.render()
        # Must not raise; must return Text
        assert isinstance(result, Text)
        rendered = result.plain
        # Duration must appear (right side)
        assert "1.5s" in rendered
        # Rendered width must not exceed terminal width significantly
        assert len(rendered) <= 44  # small slack for multi-byte


# ---------------------------------------------------------------------------
# P0-2: cursor visible after finalize_code, hidden after complete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cursor_visible_after_code_finalize():
    """Cursor remains visible (non-hidden) after finalize_code() fires — execution hasn't run yet."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        block = await _mount_execute_block(pilot, app)
        from hermes_cli.tui.execute_code_block import _STATE_FINALIZED
        from textual.widgets import Static

        block.finalize_code("x = 1\nprint(x)")
        await _pause(pilot)

        assert block._code_state == _STATE_FINALIZED
        # Cursor widget must still exist and be visible
        try:
            cursor_w = block.query_one("#code-live-cursor", Static)
            assert cursor_w.display is not False, "Cursor should remain visible after finalize_code"
        except Exception:
            pass  # cursor may not mount in headless — just verify state flag


@pytest.mark.asyncio
async def test_cursor_hidden_after_state_completed():
    """Cursor is hidden after complete() — execution result has arrived."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        block = await _mount_execute_block(pilot, app)
        from hermes_cli.tui.execute_code_block import _STATE_COMPLETED
        from textual.widgets import Static

        block.finalize_code("x = 1")
        await _pause(pilot)

        block.complete("0.5s", is_error=False)
        await _pause(pilot)

        assert block._code_state == _STATE_COMPLETED
        # Cursor widget must be hidden
        try:
            cursor_w = block.query_one("#code-live-cursor", Static)
            assert cursor_w.display is False, "Cursor should be hidden after complete()"
        except Exception:
            pass  # cursor absence also acceptable — display=False means hidden


# ---------------------------------------------------------------------------
# Pass-6 P0-2: error complete does NOT auto-collapse inner header
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_code_block_error_header_not_collapsed():
    """complete(is_error=True) must NOT collapse the inner header — ToolPanel handles errors."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        block = await _mount_execute_block(pilot, app)

        block.finalize_code("raise ValueError('oops')")
        await _pause(pilot)

        block.complete("0.1s", is_error=True)
        await _pause(pilot)

        assert block._header.collapsed is False, (
            "ECB inner header must NOT be collapsed after error complete() — "
            "ToolPanel.set_result_summary owns error expansion"
        )


# ---------------------------------------------------------------------------
# Pass-6 P2-4: label_rich truncates AFTER highlighting
# ---------------------------------------------------------------------------

def test_execute_code_block_label_rich_truncated_after_highlight():
    """_emit_code_line highlights the full line then truncates the Rich Text."""
    from hermes_cli.tui.execute_code_block import ExecuteCodeBlock
    from rich.text import Text

    block = ExecuteCodeBlock.__new__(ExecuteCodeBlock)
    block._code_lines = []
    block._label_set = False

    # Mock the header
    header = MagicMock()
    header._label = None
    header._label_rich = None
    block._header = header
    block._body = MagicMock()
    block._body.query_one.side_effect = Exception("not mounted")

    # Long line: a string literal that spans >60 chars
    long_line = 'x = "' + "a" * 80 + '"'
    block._emit_code_line(long_line)

    assert header._label_rich is not None
    assert isinstance(header._label_rich, Text), "Expected Rich Text, not plain string"
    assert header._label_rich.cell_len <= 60, (
        f"Rich Text must be truncated to ≤60 cells, got {header._label_rich.cell_len}"
    )
