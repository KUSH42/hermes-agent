"""Tests for reasoning CLI → TUI bridge.

Verifies that _stream_reasoning_delta, _on_reasoning, and _close_reasoning_box
correctly call the TUI ReasoningPanel methods via _hermes_app.call_from_thread.

Covers:
- Streaming path: first token opens panel, lines append, close flushes + closes
- Non-streaming path: _on_reasoning opens panel and appends
- Word-boundary partial flush sends to TUI
- Remaining buffer flushed to TUI on close
- Non-streaming panel closed on _reset_stream_state
- No TUI calls when _hermes_app is None
- Suppression: no TUI calls when _stream_box_opened is True
- Multiple turns: each turn gets open/close lifecycle
"""

import sys
from unittest.mock import MagicMock, patch, call

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


def _make_reasoning_cli(reasoning_buf="", box_opened=True):
    """Minimal HermesCLI stub for exercising _stream_reasoning_delta."""
    from cli import HermesCLI

    cli = HermesCLI.__new__(HermesCLI)
    cli._reasoning_buf = reasoning_buf
    cli._reasoning_box_opened = box_opened
    cli._reasoning_stream_started = False
    cli._reasoning_shown_this_turn = False
    cli._stream_box_opened = False
    cli._rich_reasoning = False
    cli.show_reasoning = True
    return cli


def _make_nonstream_cli():
    """Minimal HermesCLI stub for exercising _on_reasoning."""
    from cli import HermesCLI

    cli = HermesCLI.__new__(HermesCLI)
    cli._reasoning_preview_buf = ""
    cli._on_reasoning_tui_opened = False
    cli.show_reasoning = True
    cli._rich_reasoning = False
    return cli


def _make_mock_tui():
    """Mock TUI app with call_from_thread and reasoning methods."""
    tui = MagicMock()
    tui.call_from_thread = MagicMock()
    return tui


# ---------------------------------------------------------------------------
# Streaming path: _stream_reasoning_delta → TUI
# ---------------------------------------------------------------------------

class TestStreamReasoningDeltaTuiBridge:
    """_stream_reasoning_delta sends deltas to TUI via call_from_thread."""

    @patch("cli._cprint")
    @patch("cli._hermes_app")
    def test_first_token_opens_tui_panel(self, mock_app_ref, mock_cprint):
        """First reasoning token calls tui.open_reasoning via call_from_thread."""
        tui = _make_mock_tui()
        mock_app_ref.__bool__ = lambda self: True
        with patch("cli._hermes_app", tui):
            cli = _make_reasoning_cli(box_opened=False)
            cli._stream_reasoning_delta("thinking")

        open_calls = [
            c for c in tui.call_from_thread.call_args_list
            if len(c.args) >= 2 and c.args[0] == tui.open_reasoning
        ]
        assert len(open_calls) == 1, f"Expected 1 open_reasoning call, got {open_calls}"
        assert open_calls[0].args[1] == "Reasoning"

    @patch("cli._cprint")
    def test_every_delta_sent_to_tui(self, mock_cprint):
        """Every delta is sent to TUI immediately (TUI handles its own line buffering)."""
        tui = _make_mock_tui()
        with patch("cli._hermes_app", tui):
            cli = _make_reasoning_cli()
            cli._stream_reasoning_delta("hello world\n")

        append_calls = [
            c for c in tui.call_from_thread.call_args_list
            if len(c.args) >= 2 and c.args[0] == tui.append_reasoning
        ]
        assert len(append_calls) == 1
        assert append_calls[0].args[1] == "hello world\n"

    @patch("cli._cprint")
    def test_partial_tokens_sent_immediately(self, mock_cprint):
        """Partial tokens are sent to TUI immediately (no line buffering in CLI)."""
        tui = _make_mock_tui()
        with patch("cli._hermes_app", tui):
            cli = _make_reasoning_cli()
            cli._stream_reasoning_delta("hello ")
            cli._stream_reasoning_delta("world\n")

        append_calls = [
            c for c in tui.call_from_thread.call_args_list
            if len(c.args) >= 2 and c.args[0] == tui.append_reasoning
        ]
        texts = [c.args[1] for c in append_calls]
        assert texts == ["hello ", "world\n"]

    @patch("cli._cprint")
    def test_multiple_lines_sent_as_single_delta(self, mock_cprint):
        """Multi-line delta sent as single TUI call (TUI splits internally)."""
        tui = _make_mock_tui()
        with patch("cli._hermes_app", tui):
            cli = _make_reasoning_cli()
            cli._stream_reasoning_delta("line 1\nline 2\nline 3\n")

        append_calls = [
            c for c in tui.call_from_thread.call_args_list
            if len(c.args) >= 2 and c.args[0] == tui.append_reasoning
        ]
        assert len(append_calls) == 1
        assert append_calls[0].args[1] == "line 1\nline 2\nline 3\n"

    @patch("cli._cprint")
    def test_no_tui_calls_when_app_none(self, mock_cprint):
        """When _hermes_app is None, no call_from_thread calls are made."""
        with patch("cli._hermes_app", None):
            cli = _make_reasoning_cli(box_opened=False)
            # Should not raise
            cli._stream_reasoning_delta("hello\n")

    @patch("cli._cprint")
    def test_suppressed_when_stream_box_opened(self, mock_cprint):
        """No TUI calls when _stream_box_opened is True (response already started)."""
        tui = _make_mock_tui()
        with patch("cli._hermes_app", tui):
            cli = _make_reasoning_cli()
            cli._stream_box_opened = True
            cli._stream_reasoning_delta("should be suppressed\n")

        assert not tui.call_from_thread.called

    @patch("cli._cprint")
    def test_every_delta_sent_even_without_newline(self, mock_cprint):
        """Even text without newlines is sent to TUI immediately."""
        tui = _make_mock_tui()
        with patch("cli._hermes_app", tui):
            cli = _make_reasoning_cli()
            cli._stream_reasoning_delta("partial thought")

        append_calls = [
            c for c in tui.call_from_thread.call_args_list
            if len(c.args) >= 2 and c.args[0] == tui.append_reasoning
        ]
        assert len(append_calls) == 1
        assert append_calls[0].args[1] == "partial thought"


# ---------------------------------------------------------------------------
# Close: _close_reasoning_box → TUI
# ---------------------------------------------------------------------------

class TestCloseReasoningBoxTuiBridge:
    """_close_reasoning_box flushes remaining buffer and closes TUI panel."""

    @patch("cli._cprint")
    def test_close_calls_tui_close(self, mock_cprint):
        """_close_reasoning_box calls tui.close_reasoning."""
        tui = _make_mock_tui()
        with patch("cli._hermes_app", tui):
            cli = _make_reasoning_cli()
            cli._close_reasoning_box()

        close_calls = [
            c for c in tui.call_from_thread.call_args_list
            if len(c.args) >= 1 and c.args[0] == tui.close_reasoning
        ]
        assert len(close_calls) == 1

    @patch("cli._cprint")
    def test_close_does_not_duplicate_buffer_to_tui(self, mock_cprint):
        """Close does not re-send buffer to TUI (deltas already sent in real-time)."""
        tui = _make_mock_tui()
        with patch("cli._hermes_app", tui):
            cli = _make_reasoning_cli(reasoning_buf="leftover text")
            cli._close_reasoning_box()

        # No append_reasoning from close — all deltas were already sent
        append_calls = [
            c for c in tui.call_from_thread.call_args_list
            if len(c.args) >= 2 and c.args[0] == tui.append_reasoning
        ]
        assert len(append_calls) == 0

    @patch("cli._cprint")
    def test_close_noop_when_box_not_opened(self, mock_cprint):
        """No TUI calls when reasoning box was never opened."""
        tui = _make_mock_tui()
        with patch("cli._hermes_app", tui):
            cli = _make_reasoning_cli(box_opened=False)
            cli._close_reasoning_box()

        assert not tui.call_from_thread.called

    @patch("cli._cprint")
    def test_close_no_tui_calls_when_app_none(self, mock_cprint):
        """No crash when _hermes_app is None on close."""
        with patch("cli._hermes_app", None):
            cli = _make_reasoning_cli()
            cli._close_reasoning_box()  # should not raise


# ---------------------------------------------------------------------------
# Non-streaming path: _on_reasoning → TUI
# ---------------------------------------------------------------------------

class TestOnReasoningTuiBridge:
    """_on_reasoning opens panel on first call and appends text."""

    @patch("cli._cprint")
    def test_first_call_opens_tui_panel(self, mock_cprint):
        """First _on_reasoning call opens the TUI reasoning panel."""
        tui = _make_mock_tui()
        with patch("cli._hermes_app", tui):
            cli = _make_nonstream_cli()
            cli._on_reasoning("thinking about it")

        open_calls = [
            c for c in tui.call_from_thread.call_args_list
            if len(c.args) >= 2 and c.args[0] == tui.open_reasoning
        ]
        assert len(open_calls) == 1

    @patch("cli._cprint")
    def test_appends_text_to_tui(self, mock_cprint):
        """_on_reasoning appends reasoning text to TUI."""
        tui = _make_mock_tui()
        with patch("cli._hermes_app", tui):
            cli = _make_nonstream_cli()
            cli._on_reasoning("step 1")

        append_calls = [
            c for c in tui.call_from_thread.call_args_list
            if len(c.args) >= 2 and c.args[0] == tui.append_reasoning
        ]
        assert len(append_calls) == 1
        assert append_calls[0].args[1] == "step 1"

    @patch("cli._cprint")
    def test_second_call_does_not_reopen(self, mock_cprint):
        """Second _on_reasoning call appends but does NOT reopen."""
        tui = _make_mock_tui()
        with patch("cli._hermes_app", tui):
            cli = _make_nonstream_cli()
            cli._on_reasoning("step 1")
            cli._on_reasoning("step 2")

        open_calls = [
            c for c in tui.call_from_thread.call_args_list
            if len(c.args) >= 2 and c.args[0] == tui.open_reasoning
        ]
        assert len(open_calls) == 1, "open_reasoning should only be called once"

        append_calls = [
            c for c in tui.call_from_thread.call_args_list
            if len(c.args) >= 2 and c.args[0] == tui.append_reasoning
        ]
        assert len(append_calls) == 2

    @patch("cli._cprint")
    def test_empty_text_no_tui_calls(self, mock_cprint):
        """Empty reasoning text triggers no TUI calls."""
        tui = _make_mock_tui()
        with patch("cli._hermes_app", tui):
            cli = _make_nonstream_cli()
            cli._on_reasoning("")

        assert not tui.call_from_thread.called

    @patch("cli._cprint")
    def test_no_tui_calls_when_app_none(self, mock_cprint):
        """No crash when _hermes_app is None."""
        with patch("cli._hermes_app", None):
            cli = _make_nonstream_cli()
            cli._on_reasoning("thinking")  # should not raise


# ---------------------------------------------------------------------------
# State reset: _reset_stream_state closes non-streaming TUI panel
# ---------------------------------------------------------------------------

class TestResetStreamStateTuiBridge:
    """_reset_stream_state closes TUI panel if non-streaming path opened it."""

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    def test_reset_closes_nonstream_tui_panel(self, mock_cprint):
        """Reset closes TUI panel when _on_reasoning had opened it."""
        tui = _make_mock_tui()
        with patch("cli._hermes_app", tui):
            cli = _make_nonstream_cli()
            cli._on_reasoning_tui_opened = True
            # Provide required attrs for _reset_stream_state
            cli._stream_buf = ""
            cli._stream_started = False
            cli._stream_box_opened = False
            cli._reasoning_stream_started = False
            cli._stream_text_ansi = ""
            cli._stream_prefilt = ""
            cli._in_reasoning_block = False
            cli._reasoning_box_opened = False
            cli._reasoning_buf = ""
            cli._reasoning_preview_buf = ""
            cli._deferred_content = ""
            cli._reset_stream_state()

        close_calls = [
            c for c in tui.call_from_thread.call_args_list
            if len(c.args) >= 1 and c.args[0] == tui.close_reasoning
        ]
        assert len(close_calls) == 1

    @patch("cli._cprint")
    @patch("cli._RICH_RESPONSE", False)
    def test_reset_no_close_when_not_opened(self, mock_cprint):
        """Reset does NOT close TUI panel when it was never opened."""
        tui = _make_mock_tui()
        with patch("cli._hermes_app", tui):
            cli = _make_nonstream_cli()
            cli._on_reasoning_tui_opened = False
            cli._stream_buf = ""
            cli._stream_started = False
            cli._stream_box_opened = False
            cli._reasoning_stream_started = False
            cli._stream_text_ansi = ""
            cli._stream_prefilt = ""
            cli._in_reasoning_block = False
            cli._reasoning_box_opened = False
            cli._reasoning_buf = ""
            cli._reasoning_preview_buf = ""
            cli._deferred_content = ""
            cli._reset_stream_state()

        close_calls = [
            c for c in tui.call_from_thread.call_args_list
            if len(c.args) >= 1 and c.args[0] == tui.close_reasoning
        ]
        assert len(close_calls) == 0


# ---------------------------------------------------------------------------
# Full lifecycle: open → append → close across a turn
# ---------------------------------------------------------------------------

class TestReasoningTuiLifecycle:
    """End-to-end lifecycle: streaming reasoning across a full turn."""

    @patch("cli._cprint")
    def test_full_streaming_lifecycle(self, mock_cprint):
        """open → appends for each delta → close in correct order."""
        tui = _make_mock_tui()
        with patch("cli._hermes_app", tui):
            cli = _make_reasoning_cli(box_opened=False)
            # Simulate streaming reasoning
            cli._stream_reasoning_delta("Let me think...\n")
            cli._stream_reasoning_delta("Step 1: analyze\n")
            cli._stream_reasoning_delta("Step 2: plan\n")
            cli._close_reasoning_box()

        all_fns = [c.args[0] for c in tui.call_from_thread.call_args_list]
        assert all_fns[0] == tui.open_reasoning, "First call should be open_reasoning"
        assert all_fns[-1] == tui.close_reasoning, "Last call should be close_reasoning"
        append_calls = [f for f in all_fns if f == tui.append_reasoning]
        # Each delta is sent immediately (3 deltas = 3 appends)
        assert len(append_calls) == 3

    @patch("cli._cprint")
    def test_full_nonstream_lifecycle(self, mock_cprint):
        """Non-streaming: open → appends → close on reset."""
        tui = _make_mock_tui()
        with patch("cli._hermes_app", tui):
            cli = _make_nonstream_cli()
            # Also set up attrs needed for _reset_stream_state
            cli._stream_buf = ""
            cli._stream_started = False
            cli._stream_box_opened = False
            cli._reasoning_stream_started = False
            cli._stream_text_ansi = ""
            cli._stream_prefilt = ""
            cli._in_reasoning_block = False
            cli._reasoning_box_opened = False
            cli._reasoning_buf = ""
            cli._deferred_content = ""

            cli._on_reasoning("thinking step 1")
            cli._on_reasoning("thinking step 2")

        with patch("cli._hermes_app", tui), patch("cli._RICH_RESPONSE", False):
            cli._reset_stream_state()

        all_fns = [c.args[0] for c in tui.call_from_thread.call_args_list]
        assert all_fns[0] == tui.open_reasoning
        assert all_fns[-1] == tui.close_reasoning
        append_calls = [f for f in all_fns if f == tui.append_reasoning]
        assert len(append_calls) == 2
