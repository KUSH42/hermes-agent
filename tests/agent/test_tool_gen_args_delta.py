"""Tests for tool_gen_args_delta_callback wiring (§13.2 of ExecuteCodeBlock spec)."""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch


def _make_coder(**kwargs):
    from run_agent import AIAgent
    coder = AIAgent.__new__(AIAgent)
    for k, v in kwargs.items():
        setattr(coder, k, v)
    coder.tool_gen_callback = None
    coder.tool_gen_args_delta_callback = None
    return coder


def test_gen_started_signature_has_idx():
    """tool_gen_callback receives (idx, name), not (name,)."""
    received = []
    coder = _make_coder()
    coder.tool_gen_callback = lambda *args: received.append(args)
    coder._fire_tool_gen_started(0, "execute_code")
    assert received == [(0, "execute_code")]


def test_args_delta_fires_per_delta():
    """_fire_tool_gen_args_delta calls the callback with correct args."""
    received = []
    coder = _make_coder()
    coder.tool_gen_args_delta_callback = lambda *args: received.append(args)
    coder._fire_tool_gen_args_delta(0, "execute_code", '{"code":"', '{"code":"')
    assert received == [(0, "execute_code", '{"code":"', '{"code":"')]


def test_callback_exception_swallowed():
    """Raising callback doesn't propagate."""
    coder = _make_coder()
    coder.tool_gen_callback = lambda *a: 1 / 0
    coder.tool_gen_args_delta_callback = lambda *a: 1 / 0
    # Should not raise
    coder._fire_tool_gen_started(0, "test_tool")
    coder._fire_tool_gen_args_delta(0, "test_tool", "x", "x")


def test_idx_stable_for_parallel_tools():
    """_fire_tool_gen_args_delta keeps idx stable per tool call slot."""
    received = []
    coder = _make_coder()
    coder.tool_gen_args_delta_callback = lambda *args: received.append(args)
    coder._fire_tool_gen_args_delta(0, "execute_code", "a", "a")
    coder._fire_tool_gen_args_delta(1, "execute_code", "b", "b")
    assert received[0][0] == 0
    assert received[1][0] == 1


def test_anthropic_fires_per_input_json_delta():
    """Anthropic-style partial_json delta → callback receives (idx, name, delta, accumulated)."""
    received = []
    coder = _make_coder()
    coder.tool_gen_args_delta_callback = lambda *args: received.append(args)

    # Anthropic sends incremental partial_json; accumulated grows per chunk
    partial1 = '{"code":"import'
    partial2 = ' yaml\\n"}'
    accumulated1 = partial1
    accumulated2 = partial1 + partial2

    coder._fire_tool_gen_args_delta(0, "execute_code", partial1, accumulated1)
    coder._fire_tool_gen_args_delta(0, "execute_code", partial2, accumulated2)

    assert len(received) == 2
    assert received[0] == (0, "execute_code", partial1, accumulated1)
    assert received[1] == (0, "execute_code", partial2, accumulated2)
    # delta ≠ accumulated for second chunk (Anthropic pattern)
    assert received[1][2] != received[1][3]


def test_args_before_name_replayed():
    """Catch-up replay: accumulated args sent as single delta right after gen_start.

    OpenAI scenario: arg chunks arrive before name completes.  After gen_start
    fires, the bridge replays all accumulated args as one catch-up delta with
    delta == accumulated.
    """
    received_gen = []
    received_delta = []
    coder = _make_coder()
    coder.tool_gen_callback = lambda *args: received_gen.append(args)
    coder.tool_gen_args_delta_callback = lambda *args: received_delta.append(args)

    # Simulate: name completes, gen_start fires, then immediate replay
    coder._fire_tool_gen_started(0, "execute_code")
    # Replay: delta == accumulated (full args so far)
    catch_up = '{"code":"import yaml\\n"}'
    coder._fire_tool_gen_args_delta(0, "execute_code", catch_up, catch_up)

    assert received_gen == [(0, "execute_code")]
    assert len(received_delta) == 1
    # delta == accumulated in replay
    assert received_delta[0][2] == received_delta[0][3] == catch_up
