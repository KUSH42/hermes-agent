"""Tests for HeadlessSession and OutputJSONLWriter.

Phase B — headless_session.py.

16 tests:
  1.  OutputJSONLWriter.write() strips ANSI escape codes
  2.  OutputJSONLWriter.write() strips Rich markup [bold]
  3.  OutputJSONLWriter.write() strips Rich markup [bold red]
  4.  OutputJSONLWriter.write() strips Rich markup [link=http://x]
  5.  OutputJSONLWriter.write() persists to jsonl file
  6.  OutputJSONLWriter.load_lines() returns list of dicts
  7.  OutputJSONLWriter.load_lines() returns empty list for missing file
  8.  OutputJSONLWriter.load_lines() skips malformed lines
  9.  OutputJSONLWriter.write() ring-caps at max_lines (write 2001 → 2000 kept)
  10. HeadlessSession.__init__() creates session dir
  11. HeadlessSession._register_pid() writes state.json with correct fields
  12. HeadlessSession._get_branch() uses session_dir as cwd
  13. HeadlessSession.write_output() calls writer.write
  14. HeadlessSession.load_history() returns writer.load_lines()
  15. HeadlessSession._on_complete() sends notification to active session (mocked)
  16. HeadlessSession._on_complete() skips notify if no active_id
  17. HeadlessSession.run() calls cli.run() and then _on_complete()
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from hermes_cli.tui.headless_session import HeadlessSession, OutputJSONLWriter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def writer(tmp_dir: Path) -> OutputJSONLWriter:
    return OutputJSONLWriter(tmp_dir / "output.jsonl", max_lines=10)


# ---------------------------------------------------------------------------
# 1. ANSI stripping
# ---------------------------------------------------------------------------

def test_output_writer_strips_ansi(writer: OutputJSONLWriter):
    writer.write("\x1b[31mred text\x1b[0m")
    lines = writer.load_lines()
    assert len(lines) == 1
    assert lines[0]["text"] == "red text"


# ---------------------------------------------------------------------------
# 2. Rich markup [bold]
# ---------------------------------------------------------------------------

def test_output_writer_strips_rich_bold(writer: OutputJSONLWriter):
    writer.write("[bold]hello[/bold]")
    lines = writer.load_lines()
    assert "bold" not in lines[0]["text"]
    assert "hello" in lines[0]["text"]


# ---------------------------------------------------------------------------
# 3. Rich markup [bold red]
# ---------------------------------------------------------------------------

def test_output_writer_strips_rich_bold_red(writer: OutputJSONLWriter):
    writer.write("[bold red]important[/bold red]")
    lines = writer.load_lines()
    assert "bold red" not in lines[0]["text"]
    assert "important" in lines[0]["text"]


# ---------------------------------------------------------------------------
# 4. Rich markup [link=http://...]
# ---------------------------------------------------------------------------

def test_output_writer_strips_rich_link(writer: OutputJSONLWriter):
    writer.write("[link=http://example.com]click here[/link]")
    lines = writer.load_lines()
    assert "link=" not in lines[0]["text"]
    assert "click here" in lines[0]["text"]


# ---------------------------------------------------------------------------
# 5. Persists to jsonl file
# ---------------------------------------------------------------------------

def test_output_writer_persists_to_file(writer: OutputJSONLWriter, tmp_dir: Path):
    writer.write("hello world")
    path = tmp_dir / "output.jsonl"
    assert path.exists()
    raw = path.read_text().strip()
    entry = json.loads(raw)
    assert entry["text"] == "hello world"
    assert entry["role"] == "assistant"
    assert "ts" in entry


# ---------------------------------------------------------------------------
# 6. load_lines returns list of dicts
# ---------------------------------------------------------------------------

def test_output_writer_load_lines(writer: OutputJSONLWriter):
    writer.write("line 1")
    writer.write("line 2", role="user")
    lines = writer.load_lines()
    assert len(lines) == 2
    assert lines[0]["text"] == "line 1"
    assert lines[1]["role"] == "user"


# ---------------------------------------------------------------------------
# 7. load_lines returns empty list for missing file
# ---------------------------------------------------------------------------

def test_output_writer_load_lines_missing_file(tmp_dir: Path):
    w = OutputJSONLWriter(tmp_dir / "nonexistent.jsonl")
    assert w.load_lines() == []


# ---------------------------------------------------------------------------
# 8. load_lines skips malformed lines
# ---------------------------------------------------------------------------

def test_output_writer_load_lines_skips_malformed(tmp_dir: Path):
    path = tmp_dir / "output.jsonl"
    path.write_text('{"ts": 1.0, "text": "ok", "role": "a"}\nnot json\n{"ts": 2.0, "text": "ok2", "role": "a"}\n')
    w = OutputJSONLWriter(path)
    lines = w.load_lines()
    assert len(lines) == 2
    assert lines[0]["text"] == "ok"
    assert lines[1]["text"] == "ok2"


# ---------------------------------------------------------------------------
# 9. Ring cap enforces max_lines
# ---------------------------------------------------------------------------

def test_output_writer_ring_cap(tmp_dir: Path):
    w = OutputJSONLWriter(tmp_dir / "output.jsonl", max_lines=5)
    for i in range(7):
        w.write(f"line {i}")
    lines = w.load_lines()
    assert len(lines) == 5
    # Oldest lines (0, 1) should be gone; kept 2-6
    texts = [l["text"] for l in lines]
    assert "line 0" not in texts
    assert "line 6" in texts


# ---------------------------------------------------------------------------
# 10. HeadlessSession creates session dir
# ---------------------------------------------------------------------------

def test_headless_session_creates_dir(tmp_dir: Path):
    cli = MagicMock()
    hs = HeadlessSession(cli, "abc123def456", tmp_dir)
    expected = tmp_dir / "abc123def456"
    assert expected.is_dir()


# ---------------------------------------------------------------------------
# 11. _register_pid writes state.json
# ---------------------------------------------------------------------------

def test_headless_session_register_pid(tmp_dir: Path):
    cli = MagicMock()
    hs = HeadlessSession(cli, "abc123def456", tmp_dir)
    with patch("hermes_cli.tui.headless_session.HeadlessSession._get_branch", return_value="main"):
        hs._register_pid()
    state_path = tmp_dir / "abc123def456" / "state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text())
    assert state["id"] == "abc123def456"
    assert state["pid"] == os.getpid()
    assert state["agent_running"] is False
    assert state["last_event"] == "started"
    assert "socket_path" in state


# ---------------------------------------------------------------------------
# 12. _get_branch() uses session_dir as cwd
# ---------------------------------------------------------------------------

def test_headless_session_get_branch_uses_cwd(tmp_dir: Path):
    cli = MagicMock()
    hs = HeadlessSession(cli, "abc123def456", tmp_dir)
    session_dir = tmp_dir / "abc123def456"

    called_cwd = []

    import subprocess

    original_run = subprocess.run

    def patched_run(args, **kwargs):
        called_cwd.append(kwargs.get("cwd"))
        # Return fake result
        result = MagicMock()
        result.stdout = "feat/test\n"
        result.returncode = 0
        return result

    with patch("subprocess.run", side_effect=patched_run):
        branch = hs._get_branch()

    assert branch == "feat/test"
    assert called_cwd[0] == str(session_dir)


# ---------------------------------------------------------------------------
# 13. write_output() calls writer.write
# ---------------------------------------------------------------------------

def test_headless_session_write_output(tmp_dir: Path):
    cli = MagicMock()
    hs = HeadlessSession(cli, "abc123def456", tmp_dir)
    hs.write_output("test output")
    lines = hs.load_history()
    assert len(lines) == 1
    assert lines[0]["text"] == "test output"


# ---------------------------------------------------------------------------
# 14. load_history() returns writer.load_lines()
# ---------------------------------------------------------------------------

def test_headless_session_load_history(tmp_dir: Path):
    cli = MagicMock()
    hs = HeadlessSession(cli, "abc123def456", tmp_dir)
    hs.write_output("a")
    hs.write_output("b")
    history = hs.load_history()
    assert len(history) == 2


# ---------------------------------------------------------------------------
# 15. _on_complete() sends notification to active session (mocked)
# ---------------------------------------------------------------------------

def test_headless_session_on_complete_sends_notify(tmp_dir: Path):
    cli = MagicMock()
    hs = HeadlessSession(cli, "abc123def456", tmp_dir)

    with patch("hermes_cli.tui.session_manager.SessionIndex.get_active_id", return_value="other000000"):
        with patch("hermes_cli.tui.session_manager.send_notification", return_value=True) as mock_send:
            hs._on_complete()

    assert mock_send.called
    args = mock_send.call_args[0]
    assert args[1]["type"] == "agent_complete"
    assert args[1]["session_id"] == "abc123def456"


# ---------------------------------------------------------------------------
# 16. _on_complete() skips notify if no active_id
# ---------------------------------------------------------------------------

def test_headless_session_on_complete_skips_if_no_active(tmp_dir: Path):
    cli = MagicMock()
    hs = HeadlessSession(cli, "abc123def456", tmp_dir)

    with patch("hermes_cli.tui.session_manager.SessionIndex.get_active_id", return_value=""):
        with patch("hermes_cli.tui.session_manager.send_notification") as mock_send:
            hs._on_complete()

    assert not mock_send.called


# ---------------------------------------------------------------------------
# 17. run() calls cli.run() then _on_complete()
# ---------------------------------------------------------------------------

def test_headless_session_run_calls_cli_then_complete(tmp_dir: Path):
    cli = MagicMock()
    cli.run = MagicMock()
    hs = HeadlessSession(cli, "abc123def456", tmp_dir)

    on_complete_calls = []
    original_on_complete = hs._on_complete
    hs._on_complete = lambda: on_complete_calls.append(True)

    with patch("hermes_cli.tui.headless_session.HeadlessSession._get_branch", return_value=""):
        hs.run()

    cli.run.assert_called_once()
    assert len(on_complete_calls) == 1
