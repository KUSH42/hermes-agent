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
