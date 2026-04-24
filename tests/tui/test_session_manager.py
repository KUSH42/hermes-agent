"""Tests for parallel session data layer.

Phase A — session_manager.py + OutputJSONLWriter ring-cap.

17 tests:
  1.  SessionRecord round-trip to_dict / from_dict
  2.  SessionRecord.from_dict tolerates missing optional fields
  3.  SessionIndex.read() on missing file returns defaults
  4.  SessionIndex.read() on corrupt JSON returns defaults
  5.  SessionIndex.write() creates parent dirs
  6.  SessionIndex.add_session() deduplicates by ID
  7.  SessionIndex.remove_session() by ID
  8.  SessionIndex.update_active() sets field
  9.  SessionIndex.get_sessions() skips malformed entries
  10. SessionIndex.get_active_id() returns empty string on missing file
  11. SessionManager.new_id() returns 12-char hex string
  12. SessionManager.validate_socket_path() passes for normal path
  13. SessionManager.validate_socket_path() raises for overly long path
  14. SessionManager.kill_session() sends SIGTERM (mocked)
  15. _NotifyListener.start() creates socket at path
  16. _NotifyListener.stop() cleans up socket file
  17. send_notification() returns True on success (mock socket)
  18. send_notification() returns False on connection refused
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.session_manager import (
    SessionRecord,
    SessionIndex,
    SessionManager,
    _NotifyListener,
    send_notification,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_session_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sessions"
    d.mkdir()
    return d


def _make_record(**kwargs) -> SessionRecord:
    defaults = dict(
        id="abc123def456",
        branch="feat/test",
        worktree_path="/tmp/hermes-sessions/abc123def456",
        pid=12345,
        socket_path="/tmp/hermes-sessions/abc123def456/notify.sock",
        agent_running=False,
        last_event="started",
    )
    defaults.update(kwargs)
    return SessionRecord(**defaults)


# ---------------------------------------------------------------------------
# 1. SessionRecord round-trip
# ---------------------------------------------------------------------------

def test_session_record_round_trip():
    rec = _make_record()
    d = rec.to_dict()
    restored = SessionRecord.from_dict(d)
    assert restored.id == rec.id
    assert restored.branch == rec.branch
    assert restored.worktree_path == rec.worktree_path
    assert restored.pid == rec.pid
    assert restored.socket_path == rec.socket_path
    assert restored.agent_running == rec.agent_running
    assert restored.last_event == rec.last_event


# ---------------------------------------------------------------------------
# 2. SessionRecord.from_dict tolerates missing optional fields
# ---------------------------------------------------------------------------

def test_session_record_from_dict_tolerates_missing_optionals():
    minimal = {"id": "x", "branch": "b", "worktree_path": "/", "pid": 0, "socket_path": ""}
    rec = SessionRecord.from_dict(minimal)
    assert rec.agent_running is False
    assert rec.last_event == ""


# ---------------------------------------------------------------------------
# 3. SessionIndex.read() on missing file
# ---------------------------------------------------------------------------

def test_session_index_read_missing_file(tmp_session_dir: Path):
    idx = SessionIndex(tmp_session_dir / "sessions.json")
    data = idx.read()
    assert data["active_session_id"] == ""
    assert data["sessions"] == []


# ---------------------------------------------------------------------------
# 4. SessionIndex.read() on corrupt JSON
# ---------------------------------------------------------------------------

def test_session_index_read_corrupt_json(tmp_session_dir: Path):
    path = tmp_session_dir / "sessions.json"
    path.write_text("{corrupt json [[[")
    idx = SessionIndex(path)
    data = idx.read()
    assert data["active_session_id"] == ""
    assert data["sessions"] == []


# ---------------------------------------------------------------------------
# 5. SessionIndex.write() creates parent dirs
# ---------------------------------------------------------------------------

def test_session_index_write_creates_parent_dirs(tmp_path: Path):
    nested = tmp_path / "a" / "b" / "sessions.json"
    idx = SessionIndex(nested)
    idx.write({"active_session_id": "", "sessions": []})
    assert nested.exists()


# ---------------------------------------------------------------------------
# 6. SessionIndex.add_session() deduplicates by ID
# ---------------------------------------------------------------------------

def test_session_index_add_session_deduplicates(tmp_session_dir: Path):
    idx = SessionIndex(tmp_session_dir / "sessions.json")
    rec = _make_record()
    idx.add_session(rec)
    # Add again (should not duplicate)
    rec2 = _make_record(branch="feat/updated")
    idx.add_session(rec2)
    sessions = idx.get_sessions()
    assert len(sessions) == 1
    assert sessions[0].branch == "feat/updated"


# ---------------------------------------------------------------------------
# 7. SessionIndex.remove_session() by ID
# ---------------------------------------------------------------------------

def test_session_index_remove_session(tmp_session_dir: Path):
    idx = SessionIndex(tmp_session_dir / "sessions.json")
    rec = _make_record()
    idx.add_session(rec)
    idx.remove_session(rec.id)
    assert idx.get_sessions() == []


# ---------------------------------------------------------------------------
# 8. SessionIndex.update_active() sets field
# ---------------------------------------------------------------------------

def test_session_index_update_active(tmp_session_dir: Path):
    idx = SessionIndex(tmp_session_dir / "sessions.json")
    idx.update_active("abc123def456")
    assert idx.get_active_id() == "abc123def456"


# ---------------------------------------------------------------------------
# 9. SessionIndex.get_sessions() skips malformed entries
# ---------------------------------------------------------------------------

def test_session_index_get_sessions_skips_malformed(tmp_session_dir: Path):
    path = tmp_session_dir / "sessions.json"
    path.write_text(json.dumps({
        "active_session_id": "",
        "sessions": [
            {"id": "valid", "branch": "b", "worktree_path": "/", "pid": 1, "socket_path": ""},
            {"broken": True},   # missing required fields
            None,               # not a dict
        ]
    }))
    idx = SessionIndex(path)
    sessions = idx.get_sessions()
    # Only the valid one should survive
    assert len(sessions) == 1
    assert sessions[0].id == "valid"


# ---------------------------------------------------------------------------
# 10. SessionIndex.get_active_id() returns empty string on missing file
# ---------------------------------------------------------------------------

def test_session_index_get_active_id_missing_file(tmp_session_dir: Path):
    idx = SessionIndex(tmp_session_dir / "nonexistent.json")
    assert idx.get_active_id() == ""


# ---------------------------------------------------------------------------
# 11. SessionManager.new_id() returns 12-char hex string
# ---------------------------------------------------------------------------

def test_session_manager_new_id(tmp_session_dir: Path):
    mgr = SessionManager(tmp_session_dir)
    id1 = mgr.new_id()
    id2 = mgr.new_id()
    assert len(id1) == 12
    assert all(c in "0123456789abcdef" for c in id1)
    assert id1 != id2


# ---------------------------------------------------------------------------
# 12. SessionManager.validate_socket_path() passes for normal path
# ---------------------------------------------------------------------------

def test_session_manager_validate_socket_path_normal(tmp_session_dir: Path):
    mgr = SessionManager(tmp_session_dir)
    # /tmp/sessions/<12-char-id>/notify.sock = well under 104/108
    path = mgr.validate_socket_path("abc123def456")
    assert path.endswith("notify.sock")


# ---------------------------------------------------------------------------
# 13. SessionManager.validate_socket_path() raises for overly long path
# ---------------------------------------------------------------------------

def test_session_manager_validate_socket_path_too_long(tmp_path: Path):
    # Create a deeply nested session_dir that will push past OS limit
    long_dir = tmp_path / ("x" * 80) / ("y" * 20)
    mgr = SessionManager(long_dir)
    with pytest.raises(ValueError, match="Socket path too long"):
        mgr.validate_socket_path("abc123def456")


# ---------------------------------------------------------------------------
# 14. SessionManager.kill_session() sends SIGTERM (mocked)
# ---------------------------------------------------------------------------

def test_session_manager_kill_session_sends_sigterm(tmp_session_dir: Path):
    mgr = SessionManager(tmp_session_dir)
    rec = _make_record(pid=12345)
    kill_calls = []

    import signal

    def fake_kill(pid, sig):
        kill_calls.append((pid, sig))
        if sig == signal.SIGTERM:
            raise ProcessLookupError  # pretend process dies immediately

    with patch("os.kill", side_effect=fake_kill):
        mgr.kill_session(rec, timeout=0.1)

    assert (12345, signal.SIGTERM) in kill_calls


# ---------------------------------------------------------------------------
# 19. _NotifyListener.start() creates socket at path
# ---------------------------------------------------------------------------

def test_notify_listener_start_creates_socket(tmp_session_dir: Path):
    sock_path = str(tmp_session_dir / "test.sock")
    events = []
    listener = _NotifyListener(sock_path, events.append)
    listener.start()
    # Give the thread a moment to bind
    time.sleep(0.1)
    assert Path(sock_path).exists()
    listener.stop()


# ---------------------------------------------------------------------------
# 20. _NotifyListener.stop() cleans up socket file
# ---------------------------------------------------------------------------

def test_notify_listener_stop_cleans_up(tmp_session_dir: Path):
    sock_path = str(tmp_session_dir / "cleanup.sock")
    listener = _NotifyListener(sock_path, lambda e: None)
    listener.start()
    time.sleep(0.1)
    listener.stop()
    # Wait for daemon thread to finish its finally-block unlink
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if not Path(sock_path).exists():
            break
        time.sleep(0.05)
    # Socket file should be gone after stop
    assert not Path(sock_path).exists()


# ---------------------------------------------------------------------------
# 21. send_notification() returns True on success
# ---------------------------------------------------------------------------

def test_send_notification_success(tmp_session_dir: Path):
    sock_path = str(tmp_session_dir / "notify.sock")
    received = []

    def on_event(e):
        received.append(e)

    listener = _NotifyListener(sock_path, on_event)
    listener.start()
    time.sleep(0.1)

    result = send_notification(sock_path, {"type": "test", "msg": "hello"})
    time.sleep(0.2)

    listener.stop()
    assert result is True
    assert len(received) == 1
    assert received[0]["type"] == "test"


# ---------------------------------------------------------------------------
# 22. send_notification() returns False on connection refused
# ---------------------------------------------------------------------------

def test_send_notification_connection_refused(tmp_session_dir: Path):
    # No listener running at this path
    sock_path = str(tmp_session_dir / "nonexistent.sock")
    result = send_notification(sock_path, {"type": "test"})
    assert result is False
