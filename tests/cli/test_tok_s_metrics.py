"""Tests for tok/s metric accumulation in the streaming path.

Verifies that _message_stream_output_tokens is driven by estimate_tokens_rough
applied to each visible text chunk in _emit_stream_text, NOT by reading the
stale _last_turn_output_tokens field from the agent object.

Run with:
    pytest -o "addopts=" tests/cli/test_tok_s_metrics.py -v
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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

def _make_emit_cli(stream_output_tokens: int = 0) -> "HermesCLI":  # type: ignore[name-defined]
    """Minimal HermesCLI stub with the fields touched by _emit_stream_text."""
    from cli import HermesCLI

    cli = HermesCLI.__new__(HermesCLI)
    cli._stream_buf = ""
    cli._stream_spec_stack = []
    cli._stream_text_ansi = ""
    cli._stream_box_opened = True   # skip box-open branch (needs skin_engine)
    cli._stream_started = True
    cli.show_reasoning = False
    cli._reasoning_box_opened = False
    cli._deferred_content = ""
    cli._stream_block_buf = MagicMock()
    cli._stream_code_hl = MagicMock()
    cli._message_stream_output_tokens = stream_output_tokens
    return cli


def _estimate(text: str) -> int:
    from agent.model_metadata import estimate_tokens_rough
    return estimate_tokens_rough(text)


# ---------------------------------------------------------------------------
# Tests: tok/s metric accumulation
# ---------------------------------------------------------------------------

class TestTokSUsesTextTokensNotApiUsage:
    """_message_stream_output_tokens must match sum of estimate_tokens_rough per chunk."""

    @patch("cli._cprint")
    @patch("cli._hermes_app", None)
    @patch("cli._RICH_RESPONSE", False)
    def test_single_chunk_accumulates_correctly(self, mock_cprint):
        """One text chunk → counter equals estimate_tokens_rough(chunk)."""
        cli = _make_emit_cli()
        text = "Hello, this is a response.\n"
        cli._emit_stream_text(text)
        expected = _estimate(text)
        assert cli._message_stream_output_tokens == expected

    @patch("cli._cprint")
    @patch("cli._hermes_app", None)
    @patch("cli._RICH_RESPONSE", False)
    def test_multiple_chunks_sum_correctly(self, mock_cprint):
        """Multiple chunks → counter is the sum of per-chunk estimates."""
        cli = _make_emit_cli()
        chunks = ["First chunk of text.\n", "Second chunk.\n", "Third.\n"]
        for chunk in chunks:
            cli._emit_stream_text(chunk)
        expected = sum(_estimate(c) for c in chunks)
        assert cli._message_stream_output_tokens == expected

    @patch("cli._cprint")
    @patch("cli._hermes_app", None)
    @patch("cli._RICH_RESPONSE", False)
    def test_counter_independent_of_agent_last_turn_tokens(self, mock_cprint):
        """Counter must NOT read agent._last_turn_output_tokens.

        Even when that field holds a large value, the counter must match
        only the text actually streamed through _emit_stream_text.
        """
        cli = _make_emit_cli()
        # Attach a fake agent object with a large _last_turn_output_tokens value
        fake_agent = SimpleNamespace(_last_turn_output_tokens=9999)
        cli.agent = fake_agent

        text = "Short reply.\n"
        cli._emit_stream_text(text)

        expected = _estimate(text)
        # Must equal text-based estimate, not 9999
        assert cli._message_stream_output_tokens == expected
        assert cli._message_stream_output_tokens != 9999

    @patch("cli._cprint")
    @patch("cli._hermes_app", None)
    @patch("cli._RICH_RESPONSE", False)
    def test_pause_stream_state_does_not_add_api_tokens(self, mock_cprint):
        """_pause_stream_state must not re-add _last_turn_output_tokens to the counter."""
        import time
        from cli import HermesCLI

        cli = _make_emit_cli()
        cli._stream_started = True
        cli._stream_start_time = time.monotonic() - 0.5  # simulate 0.5 s of streaming
        cli._message_stream_active_s = 0.0
        fake_agent = SimpleNamespace(_last_turn_output_tokens=5000)
        cli.agent = fake_agent

        text = "Some response text.\n"
        cli._emit_stream_text(text)
        tokens_after_stream = cli._message_stream_output_tokens

        # Now call _pause_stream_state — must not change _message_stream_output_tokens
        with patch("cli._hermes_app", None):
            cli._pause_stream_state(intermediate=True)

        assert cli._message_stream_output_tokens == tokens_after_stream
        # Specifically must not have added the api field
        assert cli._message_stream_output_tokens < 5000

    @patch("cli._cprint")
    @patch("cli._hermes_app", None)
    @patch("cli._RICH_RESPONSE", False)
    def test_empty_text_does_not_increment(self, mock_cprint):
        """Empty string must not change the counter (estimate returns 0)."""
        cli = _make_emit_cli()
        cli._emit_stream_text("")
        assert cli._message_stream_output_tokens == 0


class TestTokSResetsPerTurn:
    """_message_stream_output_tokens resets to 0 at the start of each user turn."""

    @patch("cli._cprint")
    @patch("cli._hermes_app", None)
    @patch("cli._RICH_RESPONSE", False)
    def test_counter_starts_at_zero_each_turn(self, mock_cprint):
        """Simulates two consecutive turns; counter must reset between them."""
        cli = _make_emit_cli()

        # Turn 1 — accumulate some tokens
        cli._emit_stream_text("First turn response.\n")
        assert cli._message_stream_output_tokens > 0

        # Simulate turn-start reset (mirrors lines 8524-8525 in cli.py)
        cli._message_stream_output_tokens = 0

        # Turn 2 — fresh accumulation
        text2 = "Second turn response.\n"
        cli._emit_stream_text(text2)
        assert cli._message_stream_output_tokens == _estimate(text2)

    @patch("cli._cprint")
    @patch("cli._hermes_app", None)
    @patch("cli._RICH_RESPONSE", False)
    def test_multi_segment_turn_accumulates_across_segments(self, mock_cprint):
        """Multiple tool-call segments in one turn must sum into the counter.

        The reset happens per user turn, not per segment, so all text across
        segments within a single user turn contributes to tok/s.
        """
        cli = _make_emit_cli()

        seg1 = "Pre-tool text.\n"
        cli._emit_stream_text(seg1)
        after_seg1 = cli._message_stream_output_tokens

        # Simulate segment boundary (no reset of _message_stream_output_tokens)
        seg2 = "Post-tool text.\n"
        cli._emit_stream_text(seg2)

        expected = _estimate(seg1) + _estimate(seg2)
        assert cli._message_stream_output_tokens == expected
        assert cli._message_stream_output_tokens > after_seg1
