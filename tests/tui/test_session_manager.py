"""Tests for hermes_cli/tui/session_manager.py"""
from __future__ import annotations

import json
import sys
import threading
import time
import unittest.mock as mock
from pathlib import Path

import pytest

from hermes_cli.tui.session_manager import (
    SessionRecord,
    SessionIndex,
    SessionManager,
    _NotifyListener,
    _MAX_SOCK_PATH,
    send_notification,
)


# ---------------------------------------------------------------------------
# SessionRecord
# ---------------------------------------------------------------------------

def test_session_record_to_dict_roundtrip():
    rec = SessionRecord(
        id="abc123",
        branch="feat/x",
        worktree_path="/tmp/wt",
        pid=1234,
        socket_path="/tmp/s.sock",
        agent_running=True,
        last_event="started",
    )
    d = rec.to_dict()
    rec2 = SessionRecord.from_dict(d)
    assert rec2.id == rec.id
    assert rec2.branch == rec.branch
    assert rec2.worktree_path == rec.worktree_path
    assert rec2.pid == rec.pid
    assert rec2.socket_path == rec.socket_path
    assert rec2.agent_running == rec.agent_running
    assert rec2.last_event == rec.last_event


# ---------------------------------------------------------------------------
# SessionIndex
# ---------------------------------------------------------------------------

def test_session_index_read_missing_file(tmp_path):
    idx = SessionIndex(tmp_path / "sessions.json")
    data = idx.read()
    assert data == {"active_session_id": "", "sessions": []}


@pytest.mark.skipif(sys.platform == "win32", reason="fcntl not available on Windows")
def test_session_index_write_creates_file(tmp_path):
    path = tmp_path / "sessions.json"
    idx = SessionIndex(path)
    idx.write({"active_session_id": "x", "sessions": []})
    assert path.exists()
    loaded = json.loads(path.read_text())
    assert loaded["active_session_id"] == "x"


@pytest.mark.skipif(sys.platform == "win32", reason="fcntl not available on Windows")
def test_session_index_add_session(tmp_path):
    idx = SessionIndex(tmp_path / "sessions.json")
    rec = SessionRecord("id1", "main", "/wt", 111, "/s.sock")
    idx.add_session(rec)
    sessions = idx.get_sessions()
    assert len(sessions) == 1
    assert sessions[0].id == "id1"


@pytest.mark.skipif(sys.platform == "win32", reason="fcntl not available on Windows")
def test_session_index_remove_session(tmp_path):
    idx = SessionIndex(tmp_path / "sessions.json")
    rec = SessionRecord("id1", "main", "/wt", 111, "/s.sock")
    idx.add_session(rec)
    idx.remove_session("id1")
    sessions = idx.get_sessions()
    assert sessions == []


@pytest.mark.skipif(sys.platform == "win32", reason="fcntl not available on Windows")
def test_session_index_update_active(tmp_path):
    idx = SessionIndex(tmp_path / "sessions.json")
    idx.write({"active_session_id": "", "sessions": []})
    idx.update_active("abc")
    assert idx.get_active_id() == "abc"


@pytest.mark.skipif(sys.platform == "win32", reason="fcntl not available on Windows")
def test_session_index_get_sessions(tmp_path):
    idx = SessionIndex(tmp_path / "sessions.json")
    rec1 = SessionRecord("id1", "main", "/wt1", 1, "/s1.sock")
    rec2 = SessionRecord("id2", "feat", "/wt2", 2, "/s2.sock")
    idx.add_session(rec1)
    idx.add_session(rec2)
    sessions = idx.get_sessions()
    assert len(sessions) == 2
    ids = {s.id for s in sessions}
    assert ids == {"id1", "id2"}


@pytest.mark.skipif(sys.platform == "win32", reason="fcntl not available on Windows")
def test_session_index_get_active_id(tmp_path):
    idx = SessionIndex(tmp_path / "sessions.json")
    idx.write({"active_session_id": "sess42", "sessions": []})
    assert idx.get_active_id() == "sess42"


@pytest.mark.skipif(sys.platform == "win32", reason="fcntl not available on Windows")
def test_session_index_concurrent_writes_no_corruption(tmp_path):
    """Two threads both write; result must be valid JSON."""
    path = tmp_path / "sessions.json"
    idx = SessionIndex(path)
    errors = []

    def writer(rec_id: str):
        try:
            rec = SessionRecord(rec_id, "branch", "/wt", 0, "/sock")
            idx.add_session(rec)
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=writer, args=("t1",))
    t2 = threading.Thread(target=writer, args=("t2",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert not errors
    # File must be valid JSON
    loaded = json.loads(path.read_text())
    assert "sessions" in loaded


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------

def test_session_manager_validate_socket_path_short(tmp_path):
    mgr = SessionManager(tmp_path / "s", max_sessions=8)
    sid = "abc"
    # Should not raise
    path = mgr.validate_socket_path(sid)
    assert path.endswith("notify.sock")


def test_session_manager_validate_socket_path_too_long(tmp_path):
    long_dir = tmp_path / ("x" * 90)
    mgr = SessionManager(long_dir, max_sessions=8)
    sid = "a" * 20
    with pytest.raises(ValueError, match="too long"):
        mgr.validate_socket_path(sid)


def test_session_manager_is_alive_zero_pid(tmp_path):
    mgr = SessionManager(tmp_path / "s")
    rec = SessionRecord("id1", "main", "/wt", 0, "/sock")
    assert mgr.is_alive(rec) is False


def test_session_manager_is_alive_nonexistent_pid(tmp_path):
    mgr = SessionManager(tmp_path / "s")
    rec = SessionRecord("id1", "main", "/wt", 999999999, "/sock")
    assert mgr.is_alive(rec) is False


@pytest.mark.skipif(sys.platform == "win32", reason="fcntl not available on Windows")
def test_session_manager_get_orphans(tmp_path):
    mgr = SessionManager(tmp_path / "s")
    # Add record with dead PID
    rec = SessionRecord("dead1", "main", "/wt", 999999999, "/sock")
    mgr.index.add_session(rec)
    orphans = mgr.get_orphans()
    assert any(o.id == "dead1" for o in orphans)


def test_session_manager_kill_session_sigterm_then_sigkill(tmp_path):
    mgr = SessionManager(tmp_path / "s")
    rec = SessionRecord("id1", "main", "/wt", 1234, "/sock")

    kill_calls = []

    def fake_kill(pid, sig):
        kill_calls.append((pid, sig))
        if sig == 0:
            raise ProcessLookupError("dead")

    import signal as _sig
    with mock.patch("os.kill", side_effect=fake_kill):
        # First call to kill with SIGTERM succeeds, then os.kill(pid, 0) raises
        # ProcessLookupError so we don't get to SIGKILL
        mgr.kill_session(rec, timeout=0.1)

    assert any(c[1] == _sig.SIGTERM for c in kill_calls)


@pytest.mark.skipif(sys.platform == "win32", reason="fcntl not available on Windows")
def test_session_manager_write_read_state_roundtrip(tmp_path):
    mgr = SessionManager(tmp_path / "s")
    sdir = mgr.create_session_dir("sess1")
    rec = SessionRecord("sess1", "feat", str(sdir), 999, "/sock", agent_running=True)
    mgr.write_state(sdir, rec)
    loaded = mgr.read_state("sess1")
    assert loaded is not None
    assert loaded.id == "sess1"
    assert loaded.agent_running is True


def test_session_manager_poll_state_until_pid_timeout(tmp_path):
    mgr = SessionManager(tmp_path / "s")
    result = mgr.poll_state_until_pid("nonexistent", timeout=0.2)
    assert result is None


# ---------------------------------------------------------------------------
# _NotifyListener
# ---------------------------------------------------------------------------

def test_notify_listener_starts_and_stops(tmp_path):
    sock_path = str(tmp_path / "test.sock")
    received = []
    listener = _NotifyListener(sock_path, received.append)
    listener.start()
    time.sleep(0.05)
    listener.stop()
    # No assertion — just must not error


def test_notify_listener_receives_message(tmp_path):
    sock_path = str(tmp_path / "notify.sock")
    received = []
    ready = threading.Event()
    got = threading.Event()

    def on_event(ev):
        received.append(ev)
        got.set()

    listener = _NotifyListener(sock_path, on_event)
    listener.start()
    # Wait for socket file to appear
    deadline = time.monotonic() + 3.0
    while not Path(sock_path).exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert Path(sock_path).exists(), "Listener socket did not appear in time"

    ok = send_notification(sock_path, {"type": "ping", "msg": "hello"})
    assert ok is True

    got.wait(timeout=3.0)
    listener.stop()

    assert received
    assert received[0].get("type") == "ping"


def test_send_notification_nonexistent_socket():
    result = send_notification("/tmp/hermes_nonexistent_test.sock", {"type": "x"})
    assert result is False
