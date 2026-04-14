"""ResponseFlowEngine tests.

23 tests total:
  7 unit      — ResponseFlowEngine with mock panel (no Pilot)
  10 widget   — require app.run_test() (mount, call_after_refresh)
  6 integration — full Pilot, write_output() → DOM visible

Run with:
    pytest -o "addopts=" tests/tui/test_response_flow.py -v
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import (
    CopyableBlock,
    CopyableRichLog,
    MessagePanel,
    OutputPanel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_engine():
    """Create a ResponseFlowEngine with mocked DOM dependencies.

    Returns (engine, prose_log, panel_mock).
    The prose_log is a real CopyableRichLog — needed for _plain_lines inspection.
    panel.mount is a MagicMock — code block mounts won't actually happen,
    but _open_code_block() won't crash.
    """
    from hermes_cli.tui.response_flow import ResponseFlowEngine

    log = CopyableRichLog(markup=False)
    panel = MagicMock()
    panel._msg_id = 1
    panel._prose_blocks = []
    panel.response_log = log
    panel.app.get_css_variables.return_value = {
        "preview-syntax-theme": "monokai",
        "app-bg": "#1e1e1e",
    }
    engine = ResponseFlowEngine(panel=panel)
    engine._prose_log = log  # wire the real log
    return engine, log, panel


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


# ---------------------------------------------------------------------------
# Unit tests — no Pilot
# ---------------------------------------------------------------------------

def test_prose_passthrough():
    """Plain line passes through and lands in _plain_lines.

    StreamingBlockBuffer buffers every plain line for setext lookahead — emits
    on next line or flush().  Call engine.flush() to simulate turn end.
    """
    engine, log, _ = make_engine()
    engine.process_line("hello world")
    engine.flush()  # drain StreamingBlockBuffer setext lookahead
    assert log._plain_lines, "no plain lines written"
    assert "hello world" in log._plain_lines[0]


def test_bold_inline():
    """**bold** markers consumed — plain text stored without ** markers."""
    engine, log, _ = make_engine()
    engine.process_line("**bold** text")
    engine.flush()
    assert log._plain_lines, "no plain lines written"
    assert "**" not in log._plain_lines[0]
    assert "bold" in log._plain_lines[0]


def test_h1_heading():
    """# heading marker consumed — plain text has no # prefix."""
    engine, log, _ = make_engine()
    engine.process_line("# Section Header")
    engine.flush()
    assert log._plain_lines, "no plain lines written"
    assert "#" not in log._plain_lines[0]
    assert "Section Header" in log._plain_lines[0]


def test_bullet_list():
    """Bullet item gets written — plain text has content."""
    engine, log, _ = make_engine()
    engine.process_line("- item one")
    engine.flush()
    assert log._plain_lines, "no plain lines written"
    assert "item one" in log._plain_lines[0]


def test_blockquote():
    """> blockquote gets written — plain text has content."""
    engine, log, _ = make_engine()
    engine.process_line("> quoted text")
    engine.flush()
    assert log._plain_lines, "no plain lines written"
    assert "quoted text" in log._plain_lines[0]


def test_setext_heading_lookahead():
    """Setext heading resolved by StreamingBlockBuffer — one plain line emitted."""
    engine, log, _ = make_engine()
    engine.process_line("Section")
    assert len(log._plain_lines) == 0, "expected lookahead buffering"
    engine.process_line("=======")
    assert len(log._plain_lines) == 1
    assert "Section" in log._plain_lines[0]


def test_markdown_disabled(monkeypatch):
    """MARKDOWN_ENABLED=False → engine not created → raw text written."""
    monkeypatch.setattr("hermes_cli.tui.response_flow.MARKDOWN_ENABLED", False)

    async def _inner():
        app = HermesApp(cli=MagicMock())
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.write_output("**bold**\n")
            await asyncio.sleep(0.05)
            await pilot.pause()
            panel = app.query_one(OutputPanel).current_message
            assert panel is not None
            # engine was not created — raw text stored
            assert panel._response_engine is None
            assert "**bold**" in panel.response_log._plain_lines[0]

    import asyncio as _asyncio
    _asyncio.get_event_loop().run_until_complete(_inner())


# ---------------------------------------------------------------------------
# Widget tests — require app.run_test() (DOM operations: mount, call_after_refresh)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_horizontal_rule_emits_rich_rule():
    """process_line('---') emits a Rich Rule renderable to the prose log.

    StreamingBlockBuffer buffers '---' as a potential setext-H2 underline.
    The pending line is flushed when the turn ends (flush_live → engine.flush).
    """
    from rich.rule import Rule as RichRule

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # start a turn so MessagePanel exists
        app.agent_running = True
        await pilot.pause()
        app.write_output("---\n")
        await asyncio.sleep(0.05)
        await pilot.pause()
        # End turn — triggers flush_live() → engine.flush() → _flush_block_buf()
        app.agent_running = False
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        # _plain_lines gets "---" from _emit_rule
        assert "---" in msg.response_log._plain_lines


@pytest.mark.asyncio
async def test_code_block_opens_streaming_block():
    """Opening a code fence mounts a StreamingCodeBlock in MessagePanel."""
    from hermes_cli.tui.widgets import StreamingCodeBlock

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        app.write_output("```python\n")
        await asyncio.sleep(0.05)
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        blocks = msg.query(StreamingCodeBlock)
        assert len(blocks) == 1
        assert blocks.first()._lang == "python"


@pytest.mark.asyncio
async def test_code_block_streams_lines():
    """Lines inside a code fence go to StreamingCodeBlock._code_lines."""
    from hermes_cli.tui.widgets import StreamingCodeBlock

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        app.write_output("```python\n")
        app.write_output("x = 1\n")
        app.write_output("y = 2\n")
        app.write_output("z = 3\n")
        await asyncio.sleep(0.05)
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        block = msg.query_one(StreamingCodeBlock)
        assert len(block._code_lines) == 3
        assert len(block._log.lines) == 3


@pytest.mark.asyncio
async def test_code_block_complete_on_close():
    """Closing fence transitions StreamingCodeBlock to COMPLETE state."""
    from hermes_cli.tui.widgets import StreamingCodeBlock

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        app.write_output("```python\n")
        app.write_output("line1\n")
        app.write_output("line2\n")
        app.write_output("```\n")
        await asyncio.sleep(0.05)
        await pilot.pause()
        await pilot.pause()  # let call_after_refresh fire

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        block = msg.query_one(StreamingCodeBlock)
        assert block._state == "COMPLETE"
        assert block.has_class("--complete")
        # Final syntax body remains in the log; controls render in the footer widget.
        assert len(block._log._plain_lines) == 1
        assert "line1" in block._log._plain_lines[0]
        assert "line2" in block._log._plain_lines[0]
        assert "copy" in block._controls_text_plain


@pytest.mark.asyncio
async def test_code_block_flush_incomplete():
    """engine.flush() on mid-fence transition marks StreamingCodeBlock FLUSHED."""
    from hermes_cli.tui.widgets import StreamingCodeBlock

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        app.write_output("```python\n")
        app.write_output("x = 1\n")
        app.write_output("y = 2\n")
        await asyncio.sleep(0.05)
        await pilot.pause()
        # end the turn without closing the fence
        app.agent_running = False
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        block = msg.query_one(StreamingCodeBlock)
        assert block._state == "FLUSHED"
        assert block.has_class("--flushed")
        assert not block.has_class("--complete")
        # preserved content remains in the log; controls render in the footer widget.
        assert len(block._log.lines) == 2


@pytest.mark.asyncio
async def test_multiple_code_blocks_in_one_turn():
    """Two code fences produce two StreamingCodeBlocks, both COMPLETE."""
    from hermes_cli.tui.widgets import StreamingCodeBlock

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        app.write_output("```python\nfoo\n```\n")
        app.write_output("between\n")
        app.write_output("```bash\necho hi\n```\n")
        await asyncio.sleep(0.05)
        await pilot.pause()
        await pilot.pause()  # let call_after_refresh fire

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        blocks = list(msg.query(StreamingCodeBlock))
        assert len(blocks) == 2
        assert all(b._state == "COMPLETE" for b in blocks)


@pytest.mark.asyncio
async def test_code_fence_after_pending_prose():
    """Setext lookahead line is flushed to prose before code block opens."""
    from hermes_cli.tui.widgets import StreamingCodeBlock

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        # "potential heading" followed immediately by fence — StreamingBlockBuffer must flush
        app.write_output("potential heading\n")
        app.write_output("```python\n")
        app.write_output("x = 1\n")
        app.write_output("```\n")
        await asyncio.sleep(0.05)
        await pilot.pause()
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        # "potential heading" landed in prose log (flushed before fence opened)
        assert any("potential heading" in ln for ln in msg.response_log._plain_lines)
        # code block was mounted
        assert len(list(msg.query(StreamingCodeBlock))) == 1


@pytest.mark.asyncio
async def test_prose_after_code_block_in_new_section():
    """Post-code prose renders below the code block in timeline order."""
    from hermes_cli.tui.widgets import StreamingCodeBlock

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        app.write_output("```python\n")
        app.write_output("x = 1\n")
        app.write_output("```\n")
        app.write_output("post-code prose\n")
        await asyncio.sleep(0.05)
        await pilot.pause()
        await pilot.pause()
        # End turn — flushes the buffered "post-code prose" line
        app.agent_running = False
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        assert len(msg._prose_blocks) >= 1
        post = msg._prose_blocks[-1]
        assert any("post-code prose" in ln for ln in post.log._plain_lines)


@pytest.mark.asyncio
async def test_multiple_fences_correct_prose_sections():
    """prose1 → fence1 → prose2 → fence2 → prose3 lands in 3 separate sections."""
    from hermes_cli.tui.widgets import StreamingCodeBlock

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        app.write_output("prose1\n")
        app.write_output("```python\ncode1\n```\n")
        app.write_output("prose2\n")
        app.write_output("```bash\ncode2\n```\n")
        app.write_output("prose3\n")
        await asyncio.sleep(0.05)
        await pilot.pause()
        await pilot.pause()
        # End turn — flushes buffered prose lines (setext lookahead)
        app.agent_running = False
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        assert len(msg._prose_blocks) == 3
        assert any("prose1" in ln for ln in msg._prose_blocks[0].log._plain_lines)
        assert any("prose2" in ln for ln in msg._prose_blocks[1].log._plain_lines)
        assert any("prose3" in ln for ln in msg._prose_blocks[2].log._plain_lines)
        full = msg.all_prose_text()
        assert "prose1" in full
        assert "prose2" in full
        assert "prose3" in full
        # correct DOM order: CopyableBlock SCB CopyableBlock SCB CopyableBlock
        children = list(msg.children)
        cb_idxs = [i for i, c in enumerate(children) if isinstance(c, CopyableBlock)]
        scb_idxs = [i for i, c in enumerate(children) if isinstance(c, StreamingCodeBlock)]
        assert len(cb_idxs) == 3
        assert len(scb_idxs) == 2


@pytest.mark.asyncio
async def test_all_prose_text_empty_sections():
    """Consecutive fences with no prose keep prose storage empty."""

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        # fence immediately followed by fence — no prose between them
        app.write_output("```python\nfoo\n```\n")
        app.write_output("```bash\nbar\n```\n")
        await asyncio.sleep(0.05)
        await pilot.pause()
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        for block in msg._prose_blocks:
            assert block.log._plain_lines == []
        assert msg.all_prose_text() == ""


# ---------------------------------------------------------------------------
# Integration tests — full Pilot, write_output() → DOM visible
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_streaming_bold_visible_in_log():
    """**bold** text has no ** markers in the stored plain line."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await _run_turn(app, pilot, chunks=["**bold** text\n"])

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        assert "**" not in msg.response_log._plain_lines[0]
        assert "bold" in msg.response_log._plain_lines[0]


@pytest.mark.asyncio
async def test_code_block_streams_live():
    """Lines inside a code fence appear in StreamingCodeBlock before fence closes."""
    from hermes_cli.tui.widgets import StreamingCodeBlock

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        app.write_output("```python\n")
        app.write_output("print('hello')\n")
        await asyncio.sleep(0.05)
        await pilot.pause()
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        block = msg.query_one(StreamingCodeBlock)
        assert block._state == "STREAMING"
        assert len(block._log.lines) == 1


@pytest.mark.asyncio
async def test_code_block_finalizes_on_close():
    """Complete code block: COMPLETE state; plain lines hold raw source code."""
    from hermes_cli.tui.widgets import StreamingCodeBlock

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await _run_turn(app, pilot, chunks=["```python\n", "x = 1\n", "```\n"])
        await pilot.pause()  # let call_after_refresh fire

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        block = msg.query_one(StreamingCodeBlock)
        assert block._state == "COMPLETE"
        assert "x = 1" in block._log._plain_lines[0]
        # no ANSI escape codes in the plain source
        assert "\x1b" not in block._log._plain_lines[0]
        assert "copy" in block._controls_text_plain


@pytest.mark.asyncio
async def test_code_block_flush_on_agent_stop():
    """Agent stops mid-fence → FLUSHED, content preserved."""
    from hermes_cli.tui.widgets import StreamingCodeBlock

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        app.write_output("```python\n")
        app.write_output("x = 1\n")
        await asyncio.sleep(0.05)
        await pilot.pause()
        app.agent_running = False  # triggers flush_live → engine.flush()
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        block = msg.query_one(StreamingCodeBlock)
        assert block._state == "FLUSHED"
        assert len(block._log.lines) == 1  # content not lost
        assert "copy" in block._controls_text_plain


@pytest.mark.asyncio
async def test_copy_prose_plain_text():
    """Plain text stored in _plain_lines has no ** markers and no ANSI codes."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await _run_turn(app, pilot, chunks=["**bold** text\n"])

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        plain = msg.response_log._plain_lines[0]
        assert "**" not in plain
        assert "\x1b" not in plain


@pytest.mark.asyncio
async def test_complete_code_block_has_footer():
    """Integrated controls row is visible when the code block completes."""
    from hermes_cli.tui.widgets import StreamingCodeBlock, CodeBlockFooter

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await _run_turn(app, pilot, chunks=["```python\nfoo\n```\n"])
        await pilot.pause()

        block = app.query_one(OutputPanel).current_message.query_one(StreamingCodeBlock)
        assert block._state == "COMPLETE"
        assert block.has_class("--complete")
        assert "copy" in block._controls_text_plain
        assert "collapse" not in block._controls_text_plain
        footer = block.query_one(CodeBlockFooter)
        assert footer.styles.display == "block"


@pytest.mark.asyncio
async def test_footer_absent_during_streaming():
    """No controls row is rendered while still streaming."""
    from hermes_cli.tui.widgets import StreamingCodeBlock

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        app.write_output("```python\n")
        app.write_output("x = 1\n")
        await asyncio.sleep(0.05)
        await pilot.pause()

        block = app.query_one(OutputPanel).current_message.query_one(StreamingCodeBlock)
        assert block._state == "STREAMING"
        assert not block.has_class("--complete")
        assert not block.has_class("--complete"), "block must still be STREAMING"
        assert block._controls_text_plain == ""


@pytest.mark.asyncio
async def test_footer_copy_copies_code():
    """block.flash_copy() updates the integrated controls row."""
    from unittest.mock import patch
    from hermes_cli.tui.widgets import StreamingCodeBlock

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await _run_turn(app, pilot, chunks=["```python\nfoo = 42\n```\n"])
        await pilot.pause()

        block = app.query_one(OutputPanel).current_message.query_one(StreamingCodeBlock)
        assert block._state == "COMPLETE"

        with patch.object(app, "_copy_text_with_hint") as mock_copy:
            app._copy_code_block(block)
            await pilot.pause()

        mock_copy.assert_called_once()
        assert "foo = 42" in mock_copy.call_args[0][0]
        assert "copied" in block._controls_text_plain


@pytest.mark.asyncio
async def test_footer_toggle_collapses_code_log():
    """toggle_collapsed() collapses then re-expands the code log."""
    from hermes_cli.tui.widgets import StreamingCodeBlock

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await _run_turn(app, pilot, chunks=["```python\nfoo\nbar\n```\n"])
        await pilot.pause()

        block = app.query_one(OutputPanel).current_message.query_one(StreamingCodeBlock)
        assert not block._collapsed

        block.toggle_collapsed()
        await pilot.pause()
        assert block._collapsed
        assert "expand" in block._controls_text_plain

        block.toggle_collapsed()
        await pilot.pause()
        assert not block._collapsed
        assert "collapse" in block._controls_text_plain


@pytest.mark.asyncio
async def test_block_toggle_collapsed_updates_footer_and_log():
    """StreamingCodeBlock.toggle_collapsed() drives integrated controls + body."""
    from hermes_cli.tui.widgets import StreamingCodeBlock

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await _run_turn(app, pilot, chunks=["```python\nfoo\nbar\n```\n"])
        await pilot.pause()

        block = app.query_one(OutputPanel).current_message.query_one(StreamingCodeBlock)
        assert not block._collapsed

        block.toggle_collapsed()
        await pilot.pause()
        assert block._collapsed
        assert "expand" in block._controls_text_plain

        block.toggle_collapsed()
        await pilot.pause()
        assert not block._collapsed
        assert "collapse" in block._controls_text_plain


@pytest.mark.asyncio
async def test_single_line_code_block_footer_is_copy_only():
    """Single-line code block shows copy affordance but no collapse affordance."""
    from hermes_cli.tui.widgets import StreamingCodeBlock

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await _run_turn(app, pilot, chunks=["```python\nfoo\n```\n"])
        await pilot.pause()

        block = app.query_one(OutputPanel).current_message.query_one(StreamingCodeBlock)
        assert block._controls_text_plain.strip() == "⎘ copy"
        assert not block.can_toggle()


@pytest.mark.asyncio
async def test_code_block_followed_by_prose_keeps_footer_visible():
    """Controls row stays visible when prose continues after a completed code block."""
    from hermes_cli.tui.widgets import StreamingCodeBlock, CopyableBlock

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(100, 40)) as pilot:
        await _run_turn(
            app,
            pilot,
            chunks=[
                "```java\npublic class HelloWorld {\n  public static void main(String[] args) {\n    System.out.println(\"Hello\");\n  }\n}\n```\n",
                "Explanation:\nfoo\nbar\n",
            ],
        )
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        block = msg.query_one(StreamingCodeBlock)
        prose_blocks = list(msg.query(CopyableBlock))

        assert block._controls_text_plain.strip() != ""
        assert len(prose_blocks) >= 1
        assert prose_blocks[-1].log.copy_content() == "Explanation:\nfoo\nbar"


@pytest.mark.asyncio
async def test_indented_code_block_mounts_widget_and_keeps_footer():
    """Markdown-style indented code blocks should render as StreamingCodeBlock widgets."""
    from hermes_cli.tui.widgets import StreamingCodeBlock, CopyableBlock, CodeBlockFooter

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(100, 40)) as pilot:
        await _run_turn(
            app,
            pilot,
            chunks=[
                "Here's a classic Java Hello World:\n",
                "\n",
                "    public class HelloWorld {\n",
                "        public static void main(String[] args) {\n",
                "            System.out.println(\"Hello, World!\");\n",
                "        }\n",
                "    }\n",
                "\n",
                "Run it:\n",
            ],
        )
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        block = msg.query_one(StreamingCodeBlock)
        footer = block.query_one(CodeBlockFooter)
        prose_blocks = list(msg.query(CopyableBlock))

        assert block._state == "COMPLETE"
        assert "public class HelloWorld" in block.copy_content()
        assert "copy" in block._controls_text_plain
        assert footer.styles.display == "block"
        assert len(prose_blocks) >= 2
        assert prose_blocks[-1].log.copy_content() == "Run it:"


@pytest.mark.asyncio
async def test_source_like_prose_mounts_code_widgets_and_footer():
    """Unfenced source-looking prose lines should mount StreamingCodeBlock widgets."""
    from hermes_cli.tui.widgets import StreamingCodeBlock, CopyableBlock, CodeBlockFooter

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(100, 40)) as pilot:
        await _run_turn(
            app,
            pilot,
            chunks=[
                "Sure, here's a classic Java Hello World:\n",
                "public class HelloWorld {\n",
                "    public static void main(String[] args) {\n",
                "        System.out.println(\"Hello, World!\");\n",
                "    }\n",
                "}\n",
                "\n",
                "To run it:\n",
                "javac HelloWorld.java\n",
                "java HelloWorld\n",
                "\n",
                "Output:\n",
                "Hello, World!\n",
            ],
        )
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        blocks = list(msg.query(StreamingCodeBlock))
        prose_blocks = list(msg.query(CopyableBlock))

        assert len(blocks) >= 2
        assert "public class HelloWorld" in blocks[0].copy_content()
        assert "javac HelloWorld.java" in blocks[1].copy_content()
        assert "copy" in blocks[0]._controls_text_plain
        assert blocks[0].query_one(CodeBlockFooter).styles.display == "block"
        assert len(prose_blocks) >= 2
        prose = msg.all_prose_text()
        assert "To run it:" in prose
        assert "Output:" in prose


@pytest.mark.asyncio
async def test_source_like_heuristic_does_not_swallow_explanation_bullets_or_following_prose():
    """Explanation bullets and trailing prose must stay in prose, not synthetic code blocks."""
    from hermes_cli.tui.widgets import StreamingCodeBlock

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(100, 50)) as pilot:
        await _run_turn(
            app,
            pilot,
            chunks=[
                "Sure, here's a simple Java Hello World example:\n",
                "public class HelloWorld {\n",
                "    public static void main(String[] args) {\n",
                "        System.out.println(\"Hello, World!\");\n",
                "    }\n",
                "}\n",
                "\n",
                "How it works:\n",
                "• public class HelloWorld - defines a public class named HelloWorld\n",
                "• public static void main(String[] args) - the entry point Java looks for\n",
                "• System.out.println(\"Hello, World!\"); - prints to the console\n",
                "\n",
                "Want to see something more interesting next?\n",
            ],
        )
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        blocks = list(msg.query(StreamingCodeBlock))

        assert len(blocks) == 1
        prose = msg.all_prose_text()
        assert "How it works:" in prose
        assert "defines a public class named HelloWorld" in prose
        assert "the entry point Java looks for" in prose
        assert "Want to see something more interesting next?" in prose


@pytest.mark.asyncio
async def test_output_label_promotes_single_plain_line_to_code_block():
    """`Output:` followed by a single plain line should still get a code block footer."""
    from hermes_cli.tui.widgets import StreamingCodeBlock, CodeBlockFooter

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(100, 40)) as pilot:
        await _run_turn(
            app,
            pilot,
            chunks=[
                "Output:\n",
                "Hello, World!\n",
                "\n",
                "Next line of prose.\n",
            ],
        )
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        block = msg.query_one(StreamingCodeBlock)
        assert block.copy_content() == "Hello, World!"
        assert block.query_one(CodeBlockFooter).styles.display == "block"
        assert "Next line of prose." in msg.all_prose_text()


@pytest.mark.asyncio
async def test_inline_output_label_value_promotes_single_line_code_block():
    """`Output: value` on one line should still render a one-line code block with controls."""
    from hermes_cli.tui.widgets import StreamingCodeBlock, CodeBlockFooter

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(100, 40)) as pilot:
        await _run_turn(
            app,
            pilot,
            chunks=[
                "Output: Hello, World!\n",
                "Next line of prose.\n",
            ],
        )
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        block = msg.query_one(StreamingCodeBlock)
        assert block.copy_content() == "Hello, World!"
        assert block.query_one(CodeBlockFooter).styles.display == "block"
        assert "Output:" in msg.all_prose_text()
        assert "Next line of prose." in msg.all_prose_text()


@pytest.mark.asyncio
async def test_prenumbered_source_lines_strip_duplicate_gutter_in_code_block():
    """Pre-numbered model output should not render a second line-number column."""
    from hermes_cli.tui.widgets import StreamingCodeBlock

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(100, 40)) as pilot:
        await _run_turn(
            app,
            pilot,
            chunks=[
                "1 │ public class HelloWorld {\n",
                "2 │     public static void main(String[] args) {\n",
                "3 │         System.out.println(\"Hello\");\n",
                "4 │     }\n",
                "5 │ }\n",
            ],
        )
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        block = msg.query_one(StreamingCodeBlock)
        copied = block.copy_content().splitlines()
        assert copied[0] == "public class HelloWorld {"
        assert copied[1].startswith("    public static void main")
        assert all("│" not in line[:6] for line in copied)


@pytest.mark.asyncio
async def test_space_separated_prenumbered_lines_strip_duplicate_gutter():
    """Pre-numbered lines without a visible bar should still lose the model-added number column."""
    from hermes_cli.tui.widgets import StreamingCodeBlock

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(100, 40)) as pilot:
        await _run_turn(
            app,
            pilot,
            chunks=[
                "1  public class HelloWorld {\n",
                "2      public static void main(String[] args) {\n",
                "3          System.out.println(\"Hello\");\n",
                "4      }\n",
                "5  }\n",
            ],
        )
        await pilot.pause()

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        block = msg.query_one(StreamingCodeBlock)
        copied = block.copy_content().splitlines()
        assert copied[0] == "public class HelloWorld {"
        assert copied[-1] == "}"


@pytest.mark.asyncio
async def test_code_block_copy_content_strips_ansi_sequences():
    """Code-block clipboard content must use plain source text, not terminal escapes."""
    from hermes_cli.tui.widgets import StreamingCodeBlock

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        msg = app.query_one(OutputPanel).new_message()
        block = StreamingCodeBlock(lang="python")
        await msg.mount(block)
        await pilot.pause()

        block.append_line("\x1b[97mprint('hello')\x1b[39m")
        block.append_line("\x1b[31mvalue = 42\x1b[0m")
        block.complete(app.get_css_variables())
        await asyncio.sleep(0.05)
        await pilot.pause()

        assert block.copy_content() == "print('hello')\nvalue = 42"


def test_detect_lang_prefers_java_for_short_hello_world_snippet():
    """Short Java snippets should not fall back to plain text."""
    from hermes_cli.tui.response_flow import _detect_lang

    code = (
        "public class HelloWorld {\n"
        "    public static void main(String[] args) {\n"
        "        System.out.println(\"Hello, World!\");\n"
        "    }\n"
        "}"
    )
    assert _detect_lang(code) == "java"


def test_detect_lang_prefers_bash_for_command_blocks():
    """Command-only blocks should finalize with shell highlighting."""
    from hermes_cli.tui.response_flow import _detect_lang

    code = "javac HelloWorld.java\njava HelloWorld"
    assert _detect_lang(code) == "bash"
