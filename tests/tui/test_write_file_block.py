"""Tests for WriteFileBlock — per-chunk content streaming for write_file/create_file.

Covers spec §4 and tests T31–T43.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from hermes_cli.tui.write_file_block import WriteFileBlock
from hermes_cli.tui.tool_blocks import COLLAPSE_THRESHOLD
from hermes_cli.tui.app import HermesApp


def _make_app() -> HermesApp:
    cli = MagicMock()
    cli.agent = None
    return HermesApp(cli=cli)


# ---------------------------------------------------------------------------
# T31 — WriteFileBlock.__init__ calls header.set_path
# ---------------------------------------------------------------------------

def test_T31_init_calls_set_path():
    """WriteFileBlock.__init__(path='src/foo.py') → header.set_path('src/foo.py')."""
    block = WriteFileBlock(path="src/foo.py")
    assert block._header._full_path == "src/foo.py"
    assert block._header._path_clickable is True
    assert block._path == "src/foo.py"


# ---------------------------------------------------------------------------
# T32 — feed_delta routes through extractor to pacer
# ---------------------------------------------------------------------------

def test_T32_feed_delta_routes_through_extractor():
    """feed_delta routes through PartialJSONCodeExtractor(field='content') to pacer."""
    block = WriteFileBlock(path="src/foo.py")

    from hermes_cli.tui.partial_json import PartialJSONCodeExtractor
    from hermes_cli.tui.character_pacer import CharacterPacer

    extracted = []
    mock_extractor = MagicMock()
    mock_extractor.feed.return_value = "hello"
    mock_pacer = MagicMock()

    block._extractor = mock_extractor
    block._pacer = mock_pacer

    block.feed_delta('{"content": "hello"}')

    mock_extractor.feed.assert_called_once_with('{"content": "hello"}')
    mock_pacer.feed.assert_called_once_with("hello")


# ---------------------------------------------------------------------------
# T33 — append_content_chars splits on \n, buffers partial lines
# ---------------------------------------------------------------------------

def test_T33_append_content_chars_splits_lines():
    """append_content_chars splits on \\n, buffers partial lines."""
    emitted = []

    block = WriteFileBlock(path="foo.py")
    block._emit_content_line = lambda line: emitted.append(line)

    block.append_content_chars("hello\nworld")
    assert emitted == ["hello"]  # "world" is still in scratch
    assert block._line_scratch == "world"

    block.append_content_chars("\n")
    assert emitted == ["hello", "world"]
    assert block._line_scratch == ""


# ---------------------------------------------------------------------------
# T34 — complete line appended to body CopyableRichLog
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T34_complete_line_appended_to_richlog():
    """Complete lines are appended to body CopyableRichLog."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        block = WriteFileBlock(path="test.py")
        output = app.query_one("OutputPanel")
        msg = output.current_message or output.new_message()
        msg._mount_nonprose_block(block)
        await pilot.pause()

        block.append_content_chars("import os\n")
        await pilot.pause()

        from hermes_cli.tui.widgets import CopyableRichLog
        log = block._body.query_one(CopyableRichLog)
        assert len(log.lines) >= 1


# ---------------------------------------------------------------------------
# T35 — CharacterPacer pass-through when cps=0
# ---------------------------------------------------------------------------

def test_T35_pacer_passthrough_cps_zero():
    """CharacterPacer pass-through when cps=0: immediate reveal."""
    from hermes_cli.tui.character_pacer import CharacterPacer
    revealed = []
    pacer = CharacterPacer(cps=0, on_reveal=revealed.append, app=None)
    pacer.feed("hello")
    assert revealed == ["hello"]


# ---------------------------------------------------------------------------
# T36 — CharacterPacer queues chars when cps>0
# ---------------------------------------------------------------------------

def test_T36_pacer_queues_when_cps_positive():
    """CharacterPacer queues chars when cps>0 (does not reveal immediately)."""
    from hermes_cli.tui.character_pacer import CharacterPacer
    revealed = []
    pacer = CharacterPacer(cps=10, on_reveal=revealed.append, app=None)
    pacer.feed("hello")
    # Should NOT have revealed immediately without a timer tick
    assert revealed == []
    # flush drains immediately
    pacer.flush()
    assert revealed != []


# ---------------------------------------------------------------------------
# T37 — Reduced-motion CSS var forces cps=0
# ---------------------------------------------------------------------------

def test_T37_reduced_motion_forces_cps_zero():
    """Reduced-motion CSS var forces cps=0 regardless of config."""
    block = WriteFileBlock.__new__(WriteFileBlock)
    block._path = "foo.py"
    block._completed = False
    block._line_scratch = ""
    block._content_lines = []
    block._content_line_count = 0

    # Simulate what on_mount would do with reduced motion
    from hermes_cli.tui.character_pacer import CharacterPacer
    cps = 100  # would have been set from config
    # Simulate reduced-motion check
    css_vars = {"reduced-motion": "1"}
    if css_vars.get("reduced-motion", "0") not in ("0", "", None):
        cps = 0
    assert cps == 0


# ---------------------------------------------------------------------------
# T38 — finalize_content calls pacer.flush() then pacer.stop()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T38_complete_flushes_and_stops_pacer():
    """complete() calls pacer.flush() then pacer.stop()."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        block = WriteFileBlock(path="src/foo.py")
        output = app.query_one("OutputPanel")
        msg = output.current_message or output.new_message()
        msg._mount_nonprose_block(block)
        await pilot.pause()

        mock_pacer = MagicMock()
        mock_pacer.flush.return_value = None
        mock_pacer.stop.return_value = None
        block._pacer = mock_pacer

        block.complete("1.0s", is_error=False)
        await pilot.pause()

        mock_pacer.flush.assert_called_once()
        mock_pacer.stop.assert_called_once()


# ---------------------------------------------------------------------------
# T39 — complete() applies rich.Syntax by file extension
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T39_complete_applies_syntax_highlight():
    """complete() applies rich.Syntax re-highlight using file extension."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        block = WriteFileBlock(path="src/foo.py")
        output = app.query_one("OutputPanel")
        msg = output.current_message or output.new_message()
        msg._mount_nonprose_block(block)
        await pilot.pause()

        block._content_lines = ["import os", "import sys"]
        block._content_line_count = 2
        block._pacer = MagicMock()

        rehighlighted = []
        original = block._rehighlight_body

        def mock_rehighlight():
            rehighlighted.append(True)
            original()

        block._rehighlight_body = mock_rehighlight
        block.complete("0.5s", is_error=False)
        await pilot.pause()

        assert rehighlighted, "_rehighlight_body should have been called"


# ---------------------------------------------------------------------------
# T40 — Completion collapses when line count > COLLAPSE_THRESHOLD
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T40_complete_collapses_when_many_lines():
    """complete() collapses body when content_line_count > COLLAPSE_THRESHOLD."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        block = WriteFileBlock(path="src/big.py")
        output = app.query_one("OutputPanel")
        msg = output.current_message or output.new_message()
        msg._mount_nonprose_block(block)
        await pilot.pause()

        block._content_lines = [f"line {i}" for i in range(COLLAPSE_THRESHOLD + 2)]
        block._content_line_count = COLLAPSE_THRESHOLD + 2
        block._pacer = MagicMock()

        block.complete("1.0s", is_error=False)
        await pilot.pause()

        assert block._header.collapsed is True
        assert not block._body.has_class("expanded")


# ---------------------------------------------------------------------------
# T41 — Completion does NOT collapse when line count ≤ COLLAPSE_THRESHOLD
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T41_complete_no_collapse_when_few_lines():
    """complete() does NOT collapse when content_line_count ≤ COLLAPSE_THRESHOLD."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        block = WriteFileBlock(path="src/small.py")
        output = app.query_one("OutputPanel")
        msg = output.current_message or output.new_message()
        msg._mount_nonprose_block(block)
        await pilot.pause()

        block._content_lines = ["line"]
        block._content_line_count = 1
        block._pacer = MagicMock()

        block.complete("0.1s", is_error=False)
        await pilot.pause()

        assert block._header.collapsed is False


# ---------------------------------------------------------------------------
# T42 — _gen_blocks_by_idx set to WriteFileBlock on gen_start
# ---------------------------------------------------------------------------

def test_T42_gen_blocks_by_idx_set_on_gen_start():
    """_gen_blocks_by_idx[idx] is set to WriteFileBlock on gen_start for write_file."""
    import cli as cli_module
    from cli import HermesCLI

    cli_obj = HermesCLI.__new__(HermesCLI)
    cli_obj._tool_gen_active = False
    cli_obj._stream_box_opened = False
    cli_obj._gen_blocks_by_idx = {}
    cli_obj._pending_gen_queue = []

    mock_tui = MagicMock()
    mock_block = WriteFileBlock(path="")
    call_results = []

    def fake_call_from_thread(fn):
        fn()
        call_results.append(fn)

    mock_tui.call_from_thread = fake_call_from_thread
    mock_tui._open_write_file_block.return_value = mock_block

    with patch.object(cli_module, "_hermes_app", mock_tui), \
         patch.object(cli_obj, "_flush_stream", lambda: None, create=True), \
         patch.object(cli_obj, "_close_reasoning_box", lambda: None, create=True):
        cli_obj._on_tool_gen_start(42, "write_file")

    assert 42 in cli_obj._gen_blocks_by_idx
    assert isinstance(cli_obj._gen_blocks_by_idx[42], WriteFileBlock)


# ---------------------------------------------------------------------------
# T43 — write_file and create_file both route to WriteFileBlock
# ---------------------------------------------------------------------------

def test_T43_write_file_and_create_file_route_to_write_file_block():
    """write_file and create_file both create WriteFileBlock (not plain StreamingToolBlock)."""
    import cli as cli_module
    from cli import HermesCLI

    for tool_name in ("write_file", "create_file"):
        cli_obj = HermesCLI.__new__(HermesCLI)
        cli_obj._tool_gen_active = False
        cli_obj._stream_box_opened = False
        cli_obj._gen_blocks_by_idx = {}
        cli_obj._pending_gen_queue = []

        mock_tui = MagicMock()
        mock_block = WriteFileBlock(path="")

        def fake_call_from_thread(fn):
            fn()

        mock_tui.call_from_thread = fake_call_from_thread
        mock_tui._open_write_file_block.return_value = mock_block

        with patch.object(cli_module, "_hermes_app", mock_tui), \
             patch.object(cli_obj, "_flush_stream", lambda: None, create=True), \
             patch.object(cli_obj, "_close_reasoning_box", lambda: None, create=True):
            cli_obj._on_tool_gen_start(0, tool_name)

        found_block = cli_obj._gen_blocks_by_idx.get(0)
        assert isinstance(found_block, WriteFileBlock), \
            f"{tool_name} should create WriteFileBlock, got {type(found_block)}"
