"""Tests for hermes_cli/tui/headless_session.py"""
from __future__ import annotations

import json
import os
import sys
import time
import unittest.mock as mock
from pathlib import Path

import pytest

from hermes_cli.tui.headless_session import HeadlessSession, OutputJSONLWriter


# ---------------------------------------------------------------------------
# OutputJSONLWriter
# ---------------------------------------------------------------------------

def test_output_jsonl_writer_creates_file(tmp_path):
    writer = OutputJSONLWriter(tmp_path / "output.jsonl")
    writer.write("hello")
    assert (tmp_path / "output.jsonl").exists()


def test_output_jsonl_writer_strips_ansi(tmp_path):
    writer = OutputJSONLWriter(tmp_path / "output.jsonl")
    writer.write("\x1b[32mgreen text\x1b[0m")
    lines = writer.load_lines()
    assert lines
    assert "\x1b" not in lines[0]["text"]
    assert "green text" in lines[0]["text"]


def test_output_jsonl_writer_strips_rich_markup(tmp_path):
    writer = OutputJSONLWriter(tmp_path / "output.jsonl")
    writer.write("[bold]bold text[/bold]")
    lines = writer.load_lines()
    assert lines
    assert "[bold]" not in lines[0]["text"]
    assert "bold text" in lines[0]["text"]


def test_output_jsonl_writer_ring_cap(tmp_path):
    max_lines = 10
    writer = OutputJSONLWriter(tmp_path / "output.jsonl", max_lines=max_lines)
    for i in range(max_lines + 5):
        writer.write(f"line {i}")
    lines = writer.load_lines()
    assert len(lines) == max_lines


def test_output_jsonl_writer_load_lines_missing_file(tmp_path):
    writer = OutputJSONLWriter(tmp_path / "missing.jsonl")
    assert writer.load_lines() == []


def test_output_jsonl_writer_load_lines_parses_written(tmp_path):
    writer = OutputJSONLWriter(tmp_path / "output.jsonl")
    writer.write("first")
    writer.write("second")
    lines = writer.load_lines()
    texts = [l["text"] for l in lines]
    assert "first" in texts
    assert "second" in texts


def test_output_jsonl_writer_ring_cap_at_boundary(tmp_path):
    max_lines = 5
    writer = OutputJSONLWriter(tmp_path / "output.jsonl", max_lines=max_lines)
    for i in range(max_lines):
        writer.write(f"line {i}")
    lines = writer.load_lines()
    assert len(lines) == max_lines


def test_output_jsonl_writer_multiple_writes_accumulate(tmp_path):
    writer = OutputJSONLWriter(tmp_path / "output.jsonl", max_lines=100)
    for i in range(5):
        writer.write(f"msg {i}")
    lines = writer.load_lines()
    assert len(lines) == 5


def test_output_jsonl_writer_role_preserved(tmp_path):
    writer = OutputJSONLWriter(tmp_path / "output.jsonl")
    writer.write("user says hi", role="user")
    lines = writer.load_lines()
    assert lines
    assert lines[0]["role"] == "user"


# ---------------------------------------------------------------------------
# HeadlessSession
# ---------------------------------------------------------------------------

def test_headless_session_init_creates_dir(tmp_path):
    hs = HeadlessSession(object(), "sess1", tmp_path)
    assert (tmp_path / "sess1").is_dir()


def test_headless_session_register_pid_writes_state(tmp_path):
    hs = HeadlessSession(object(), "sess1", tmp_path)
    hs._register_pid()
    state_path = tmp_path / "sess1" / "state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text())
    assert state["pid"] == os.getpid()
    assert state["id"] == "sess1"


def test_headless_session_write_output_delegates(tmp_path):
    hs = HeadlessSession(object(), "sess1", tmp_path)
    hs.write_output("hello world")
    lines = hs.load_history()
    assert lines
    assert "hello world" in lines[0]["text"]


def test_headless_session_load_history_returns_lines(tmp_path):
    hs = HeadlessSession(object(), "sess1", tmp_path)
    hs.write_output("a")
    hs.write_output("b")
    history = hs.load_history()
    texts = [e["text"] for e in history]
    assert "a" in texts
    assert "b" in texts


def test_headless_session_on_complete_sends_notification(tmp_path):
    """_on_complete should call send_notification if there's a different active session."""
    hs = HeadlessSession(object(), "sess1", tmp_path)

    import hermes_cli.tui.session_manager as _sm

    mock_idx = mock.MagicMock()
    mock_idx.get_active_id.return_value = "sess2"
    MockIndexCls = mock.MagicMock(return_value=mock_idx)
    mock_notify = mock.MagicMock(return_value=True)

    with mock.patch.object(_sm, "SessionIndex", MockIndexCls), \
         mock.patch.object(_sm, "send_notification", mock_notify):
        hs._on_complete()

    assert mock_notify.called


def test_headless_session_get_branch_subprocess_mock(tmp_path):
    hs = HeadlessSession(object(), "sess1", tmp_path)
    with mock.patch("subprocess.run") as mock_run:
        mock_run.return_value = mock.Mock(stdout="feat/test\n")
        branch = hs._get_branch()
    assert branch == "feat/test"
