"""Tests for _flush_stream and _on_tool_complete fixes.

Covers:
- _flush_stream: block/code buffers flushed even when _stream_buf is empty
  (e.g. API error hits right after a newline boundary)
- _flush_stream: _stream_code_hl.flush() output gets _RST appended
- _flush_stream: normal path (non-empty buffer) still works after restructure —
  process_line fires first, then flush runs; box border closed when opened
- _on_tool_complete: code previews gated on tool_progress_mode == "verbose",
  not just _code_highlight_enabled; edit diffs still shown in "all" mode
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

# Stub optional packages absent in the test environment.
_MISSING_STUBS = {
    mod: MagicMock()
    for mod in [
        "prompt_toolkit", "prompt_toolkit.history", "prompt_toolkit.styles",
        "prompt_toolkit.patch_stdout", "prompt_toolkit.application",
        "prompt_toolkit.layout", "prompt_toolkit.layout.processors",
        "prompt_toolkit.filters", "prompt_toolkit.layout.dimension",
        "prompt_toolkit.layout.menus", "prompt_toolkit.widgets",
        "prompt_toolkit.key_binding", "prompt_toolkit.completion",
        "prompt_toolkit.formatted_text", "prompt_toolkit.auto_suggest",
        "fire",
    ]
    if mod not in sys.modules
}
sys.modules.update(_MISSING_STUBS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RST_SENTINEL = "\033[0m"


def _make_flush_cli(stream_buf="", stream_box_opened=False, stream_text_ansi=""):
    """Minimal HermesCLI stub suitable for exercising _flush_stream."""
    from cli import HermesCLI

    cli = HermesCLI.__new__(HermesCLI)
    cli._stream_buf = stream_buf
    cli._stream_spec_stack = []
    cli._stream_vis_len = 0  # no partial line shown by default
    cli._stream_box_opened = stream_box_opened
    cli._stream_text_ansi = stream_text_ansi
    cli._reasoning_box_opened = False
    cli._reasoning_buf = ""
    cli._deferred_content = ""
    # Block buffer and code highlighter are replaced per-test with mocks.
    cli._stream_block_buf = MagicMock()
    cli._stream_code_hl = MagicMock()
    return cli


def _make_tool_cli(tool_progress_mode="verbose", code_highlight_enabled=True):
    """Minimal HermesCLI stub suitable for exercising _on_tool_complete."""
    from cli import HermesCLI

    cli = HermesCLI.__new__(HermesCLI)
    cli.tool_progress_mode = tool_progress_mode
    cli._code_highlight_enabled = code_highlight_enabled
    cli._pending_edit_snapshots = {}
    return cli


# ---------------------------------------------------------------------------
# _flush_stream: block/code buffers flushed when _stream_buf is empty
# ---------------------------------------------------------------------------

class TestFlushStreamEmptyBuffer:
    """Block and code flushes must fire even when the stream buffer is empty."""

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST_SENTINEL)
    def test_block_buf_flushed_when_stream_buf_empty(self, mock_cprint):
        """`_stream_block_buf.flush()` is called even when `_stream_buf == ""`."""
        cli = _make_flush_cli(stream_buf="")
        cli._stream_block_buf.flush.return_value = None
        cli._stream_code_hl.flush.return_value = None

        with patch.object(cli, "_close_reasoning_box"):
            cli._flush_stream()

        cli._stream_block_buf.flush.assert_called_once()

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST_SENTINEL)
    def test_code_hl_flushed_when_stream_buf_empty(self, mock_cprint):
        """`_stream_code_hl.flush()` is called even when `_stream_buf == ""`."""
        cli = _make_flush_cli(stream_buf="")
        cli._stream_block_buf.flush.return_value = None
        cli._stream_code_hl.flush.return_value = None

        with patch.object(cli, "_close_reasoning_box"):
            cli._flush_stream()

        cli._stream_code_hl.flush.assert_called_once()

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST_SENTINEL)
    def test_code_fence_content_rendered_on_empty_buf(self, mock_cprint):
        """When an API error hits after a newline (buffer empty), any code
        block content held in the code highlighter is still rendered."""
        cli = _make_flush_cli(stream_buf="")
        cli._stream_block_buf.flush.return_value = None
        cli._stream_code_hl.flush.return_value = "highlighted code"

        with patch.object(cli, "_close_reasoning_box"):
            cli._flush_stream()

        printed = [str(c.args[0]) for c in mock_cprint.call_args_list]
        assert any("highlighted code" in p for p in printed), (
            "Code fence content was silently dropped; expected it in cprint output"
        )

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST_SENTINEL)
    def test_block_buf_tail_rendered_on_empty_buf(self, mock_cprint):
        """Buffered block state (e.g. pending setext heading, partial table)
        is rendered even when `_stream_buf` is empty."""
        cli = _make_flush_cli(stream_buf="")
        cli._stream_block_buf.flush.return_value = "pending line"
        cli._stream_code_hl.flush.return_value = None

        with (
            patch.object(cli, "_close_reasoning_box"),
            patch("cli._apply_block_line", side_effect=lambda l, **_: l),
            patch("cli._apply_inline_md", side_effect=lambda l, **_: l),
        ):
            cli._flush_stream()

        printed = [str(c.args[0]) for c in mock_cprint.call_args_list]
        assert any("pending line" in p for p in printed), (
            "Buffered block content was dropped when _stream_buf was empty"
        )


# ---------------------------------------------------------------------------
# _flush_stream: normal path (non-empty buffer) — regression after restructure
# ---------------------------------------------------------------------------

class TestFlushStreamNonEmptyBuffer:
    """Normal-path regression: non-empty _stream_buf still processed correctly
    after the unconditional-flush restructure."""

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST_SENTINEL)
    def test_process_line_called_before_flush(self, mock_cprint):
        """process_line fires on the partial buffer content before flush()."""
        cli = _make_flush_cli(stream_buf="partial line")
        cli._stream_block_buf.process_line.return_value = "partial line"
        cli._stream_code_hl.process_line.return_value = "partial line"  # identity → inline md path
        cli._stream_block_buf.flush.return_value = None
        cli._stream_code_hl.flush.return_value = None

        with (
            patch.object(cli, "_close_reasoning_box"),
            patch("cli._apply_block_line", side_effect=lambda l, **_: l),
            patch("cli._apply_inline_md", side_effect=lambda l, **_: l),
        ):
            cli._flush_stream()

        cli._stream_block_buf.process_line.assert_called_once_with("partial line")
        cli._stream_code_hl.process_line.assert_called_once()

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST_SENTINEL)
    def test_flush_called_after_process_line(self, mock_cprint):
        """flush() is still called on both buffers even when _stream_buf was non-empty."""
        cli = _make_flush_cli(stream_buf="partial line")
        cli._stream_block_buf.process_line.return_value = "partial line"
        cli._stream_code_hl.process_line.return_value = "partial line"
        cli._stream_block_buf.flush.return_value = None
        cli._stream_code_hl.flush.return_value = None

        with (
            patch.object(cli, "_close_reasoning_box"),
            patch("cli._apply_block_line", side_effect=lambda l, **_: l),
            patch("cli._apply_inline_md", side_effect=lambda l, **_: l),
        ):
            cli._flush_stream()

        cli._stream_block_buf.flush.assert_called_once()
        cli._stream_code_hl.flush.assert_called_once()

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST_SENTINEL)
    def test_stream_buf_cleared_after_flush(self, mock_cprint):
        cli = _make_flush_cli(stream_buf="leftover")
        cli._stream_block_buf.process_line.return_value = None  # suppressed
        cli._stream_block_buf.flush.return_value = None
        cli._stream_code_hl.flush.return_value = None

        with patch.object(cli, "_close_reasoning_box"):
            cli._flush_stream()

        assert cli._stream_buf == ""

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST_SENTINEL)
    def test_no_box_border_printed_when_opened(self, mock_cprint):
        """No bottom border — next turn's top rule provides separation."""
        cli = _make_flush_cli(stream_buf="", stream_box_opened=True)
        cli._stream_block_buf.flush.return_value = None
        cli._stream_code_hl.flush.return_value = None

        with (
            patch.object(cli, "_close_reasoning_box"),
            patch("cli.shutil") as mock_shutil,
        ):
            mock_shutil.get_terminal_size.return_value = SimpleNamespace(columns=40)
            cli._flush_stream()

        assert not mock_cprint.called

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST_SENTINEL)
    def test_box_border_not_printed_when_not_opened(self, mock_cprint):
        cli = _make_flush_cli(stream_buf="", stream_box_opened=False)
        cli._stream_block_buf.flush.return_value = None
        cli._stream_code_hl.flush.return_value = None

        with patch.object(cli, "_close_reasoning_box"):
            cli._flush_stream()

        assert not mock_cprint.called


# ---------------------------------------------------------------------------
# _flush_stream: code-hl tail gets _RST
# ---------------------------------------------------------------------------

class TestFlushStreamCodeHlReset:
    """Output from _stream_code_hl.flush() must be followed by _RST."""

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST_SENTINEL)
    def test_code_hl_tail_ends_with_rst(self, mock_cprint):
        cli = _make_flush_cli(stream_buf="")
        cli._stream_block_buf.flush.return_value = None
        cli._stream_code_hl.flush.return_value = "\033[32msome code\033[33m"

        with patch.object(cli, "_close_reasoning_box"):
            cli._flush_stream()

        printed = [str(c.args[0]) for c in mock_cprint.call_args_list]
        code_lines = [p for p in printed if "some code" in p]
        assert code_lines, "Code hl tail was not printed at all"
        # Each code line is now printed with 2-space indent; _RST follows as a
        # separate _cprint call immediately after the loop.
        assert all(p.startswith("  ") for p in code_lines), (
            f"Expected 2-space indent on code-hl lines, got: {code_lines}"
        )
        assert _RST_SENTINEL in printed, (
            f"Expected standalone _RST after code-hl output, got: {printed}"
        )

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", True)
    @patch("cli._RST", _RST_SENTINEL)
    def test_code_hl_no_output_no_extra_rst(self, mock_cprint):
        """When flush() returns nothing, no spurious _RST is printed."""
        cli = _make_flush_cli(stream_buf="")
        cli._stream_block_buf.flush.return_value = None
        cli._stream_code_hl.flush.return_value = None

        with patch.object(cli, "_close_reasoning_box"):
            cli._flush_stream()

        printed = [str(c.args[0]) for c in mock_cprint.call_args_list]
        # Only the box-border _RST is acceptable (when box was opened).
        # Since _stream_box_opened is False, nothing should be printed at all.
        assert not printed


# ---------------------------------------------------------------------------
# _on_tool_complete: code previews gated on verbose mode
# ---------------------------------------------------------------------------

class TestOnToolCompleteVerboseGating:
    """Code previews (read_file, execute_code, terminal) require verbose mode."""

    def _run(self, cli, function_name, function_args, function_result):
        with patch("cli._cprint"):
            cli._on_tool_complete("call_1", function_name, function_args, function_result)

    @patch("cli._cprint")
    def test_read_file_preview_shown_in_verbose(self, _cprint):
        cli = _make_tool_cli(tool_progress_mode="verbose")
        with (
            patch("agent.display.render_edit_diff_with_delta"),
            patch("agent.display.render_read_file_preview") as mock_preview,
            patch("agent.display.render_execute_code_preview"),
            patch("agent.display.render_terminal_preview"),
        ):
            cli._on_tool_complete(
                "call_1", "read_file",
                {"path": "foo.py"},
                '{"content": "x = 1"}',
            )
        mock_preview.assert_called_once()

    @patch("cli._cprint")
    def test_read_file_preview_not_shown_in_all(self, _cprint):
        cli = _make_tool_cli(tool_progress_mode="all")
        with (
            patch("agent.display.render_edit_diff_with_delta"),
            patch("agent.display.render_read_file_preview") as mock_preview,
        ):
            cli._on_tool_complete(
                "call_1", "read_file",
                {"path": "foo.py"},
                '{"content": "x = 1"}',
            )
        mock_preview.assert_not_called()

    @patch("cli._cprint")
    def test_read_file_preview_not_shown_in_new(self, _cprint):
        cli = _make_tool_cli(tool_progress_mode="new")
        with (
            patch("agent.display.render_edit_diff_with_delta"),
            patch("agent.display.render_read_file_preview") as mock_preview,
        ):
            cli._on_tool_complete(
                "call_1", "read_file",
                {"path": "foo.py"},
                '{"content": "x = 1"}',
            )
        mock_preview.assert_not_called()

    @patch("cli._cprint")
    def test_no_preview_when_off(self, _cprint):
        """_on_tool_complete returns early in off mode — nothing rendered."""
        cli = _make_tool_cli(tool_progress_mode="off")
        with (
            patch("agent.display.render_edit_diff_with_delta") as mock_diff,
            patch("agent.display.render_read_file_preview") as mock_preview,
        ):
            cli._on_tool_complete(
                "call_1", "read_file",
                {"path": "foo.py"},
                '{"content": "x = 1"}',
            )
        mock_diff.assert_not_called()
        mock_preview.assert_not_called()

    @patch("cli._cprint")
    def test_code_highlight_disabled_suppresses_preview_even_in_verbose(self, _cprint):
        """`_code_highlight_enabled = False` still suppresses previews."""
        cli = _make_tool_cli(tool_progress_mode="verbose", code_highlight_enabled=False)
        with (
            patch("agent.display.render_edit_diff_with_delta"),
            patch("agent.display.render_read_file_preview") as mock_preview,
        ):
            cli._on_tool_complete(
                "call_1", "read_file",
                {"path": "foo.py"},
                '{"content": "x = 1"}',
            )
        mock_preview.assert_not_called()

    @patch("cli._cprint")
    def test_edit_diff_shown_in_all_mode(self, _cprint):
        """Edit diffs are not gated on verbose — they show in all/new modes too."""
        cli = _make_tool_cli(tool_progress_mode="all")
        with (
            patch("agent.display.render_edit_diff_with_delta") as mock_diff,
            patch("agent.display.render_read_file_preview"),
        ):
            cli._on_tool_complete(
                "call_1", "write_file",
                {"path": "foo.py", "content": "x = 2"},
                '{"success": true}',
            )
        mock_diff.assert_called_once()

    @patch("cli._cprint")
    def test_execute_code_preview_shown_in_verbose(self, _cprint):
        cli = _make_tool_cli(tool_progress_mode="verbose")
        with (
            patch("agent.display.render_edit_diff_with_delta"),
            patch("agent.display._result_succeeded", return_value=True),
            patch("agent.display.render_execute_code_preview") as mock_preview,
        ):
            cli._on_tool_complete(
                "call_1", "execute_code",
                {"code": "print('hi')"},
                '{"output": "hi"}',
            )
        mock_preview.assert_called_once()

    @patch("cli._cprint")
    def test_execute_code_preview_not_shown_in_all(self, _cprint):
        cli = _make_tool_cli(tool_progress_mode="all")
        with (
            patch("agent.display.render_edit_diff_with_delta"),
            patch("agent.display._result_succeeded", return_value=True),
            patch("agent.display.render_execute_code_preview") as mock_preview,
        ):
            cli._on_tool_complete(
                "call_1", "execute_code",
                {"code": "print('hi')"},
                '{"output": "hi"}',
            )
        mock_preview.assert_not_called()
