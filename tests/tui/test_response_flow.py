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
        # _finalize_syntax: single write replaces per-line content
        assert len(block._log._plain_lines) == 1
        assert "line1" in block._log._plain_lines[0]
        assert "line2" in block._log._plain_lines[0]


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
        # content preserved (no clear, no Syntax)
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
    """Post-code prose renders in a new CopyableBlock section below the code block."""
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
        # 2 prose blocks: initial (empty) + post-code
        assert len(msg._prose_blocks) == 2
        post = msg._prose_blocks[1]
        assert any("post-code prose" in ln for ln in post.log._plain_lines)
        # pre-code prose block is empty (no text before fence in this test)
        assert msg._prose_blocks[0].log._plain_lines == []


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
    """Consecutive fences (no prose between) produce empty intermediate section."""
    from hermes_cli.tui.widgets import StreamingCodeBlock

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
        # 3 sections: initial (empty) + between-fences (empty) + after last fence (empty)
        assert len(msg._prose_blocks) == 3
        # all sections empty
        for block in msg._prose_blocks:
            assert block.log._plain_lines == []
        # all_prose_text with no content returns ""
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
async def test_code_block_collapse_click():
    """Click on CodeBlockHeader collapses a COMPLETE StreamingCodeBlock."""
    from hermes_cli.tui.widgets import CodeBlockHeader, StreamingCodeBlock

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await _run_turn(app, pilot, chunks=["```python\nfoo\n```\n"])
        await pilot.pause()  # let _finalize_syntax fire
        await pilot.pause()  # CSS engine settle

        msg = app.query_one(OutputPanel).current_message
        assert msg is not None
        block = msg.query_one(StreamingCodeBlock)
        assert block._state == "COMPLETE"

        header = block.query_one(CodeBlockHeader)
        await pilot.click(header)
        await pilot.pause()  # on_click fires toggle_class
        await pilot.pause()  # CSS engine computes display:none

        assert block.has_class("--collapsed")
        assert not block._log.display
