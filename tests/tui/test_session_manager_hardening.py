"""Tests for session_manager.py hardening (SM-1, SM-2, SM-3).

16 tests:
  SM-1 (7): _NotifyListener threading.Lock correctness + dispatch logging
  SM-2 (3): dead-code methods absent from SessionManager
  SM-3 (6): SessionIndex.write() atomic temp-file + rename
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.session_manager import (
    SessionIndex,
    SessionManager,
    _NotifyListener,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sessions"
    d.mkdir()
    return d


def _make_listener(tmp_dir: Path, on_event=None) -> tuple[_NotifyListener, str]:
    sock_path = str(tmp_dir / "test.sock")
    listener = _NotifyListener(sock_path, on_event or (lambda e: None))
    return listener, sock_path


# ---------------------------------------------------------------------------
# SM-1: _NotifyListener threading.Lock
# ---------------------------------------------------------------------------

class TestNotifyListenerLock:

    def test_lock_created_on_init(self, tmp_dir: Path):
        listener, _ = _make_listener(tmp_dir)
        assert hasattr(listener, "_lock")
        assert isinstance(listener._lock, type(threading.Lock()))

    def test_stop_acquires_lock_before_closing_sock(self, tmp_dir: Path):
        listener, _ = _make_listener(tmp_dir)
        lock_held_during_close = []
        mock_sock = MagicMock()

        original_close = mock_sock.close

        def close_spy():
            lock_held_during_close.append(not listener._lock.acquire(blocking=False))
            if not lock_held_during_close[-1]:
                listener._lock.release()

        mock_sock.close.side_effect = close_spy
        listener._sock = mock_sock

        listener.stop()

        assert lock_held_during_close == [True], "lock must be held when _sock.close() is called"

    def test_run_sets_sock_under_lock(self, tmp_dir: Path):
        listener, sock_path = _make_listener(tmp_dir)
        sock_was_none_at_lock_entry = []

        original_enter = listener._lock.__class__.__enter__

        class _TracingLock:
            def __init__(self):
                self._real = threading.Lock()

            def acquire(self, *a, **kw):
                return self._real.acquire(*a, **kw)

            def release(self):
                return self._real.release()

            def __enter__(self):
                self._real.acquire()
                sock_was_none_at_lock_entry.append(listener._sock is None)
                return self

            def __exit__(self, *a):
                self._real.release()

        listener._lock = _TracingLock()
        listener.start()
        time.sleep(0.15)
        listener.stop()

        # At least one lock entry should have seen _sock as None (the assignment entry)
        assert True in sock_was_none_at_lock_entry

    def test_stop_before_sock_set_does_not_crash(self, tmp_dir: Path):
        listener, _ = _make_listener(tmp_dir)
        # _sock is None; stop() should not raise
        listener.stop()

    def test_sock_is_none_after_run_exits(self, tmp_dir: Path):
        listener, sock_path = _make_listener(tmp_dir)
        listener.start()
        time.sleep(0.1)
        listener.stop()
        # Wait for thread to finish finally block
        if listener._thread:
            listener._thread.join(timeout=2.0)
        assert listener._sock is None

    def test_handle_logs_on_event_dispatch_error(self, tmp_dir: Path):
        sock_path = str(tmp_dir / "err.sock")

        def bad_on_event(e):
            raise RuntimeError("boom")

        listener = _NotifyListener(sock_path, bad_on_event)
        listener.start()
        time.sleep(0.1)

        with patch("hermes_cli.tui.session_manager.logger") as mock_log:
            # Send a valid JSON line
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(1.0)
                s.connect(sock_path)
                s.sendall(b'{"type": "test"}\n')
                s.close()
            except OSError:
                pass
            time.sleep(0.2)

            mock_log.warning.assert_called()
            call_kwargs = mock_log.warning.call_args
            assert call_kwargs[1].get("exc_info") is True

        listener.stop()

    def test_handle_silently_skips_json_decode_error(self, tmp_dir: Path):
        sock_path = str(tmp_dir / "bad.sock")
        called = []
        listener = _NotifyListener(sock_path, lambda e: called.append(e))
        listener.start()
        time.sleep(0.1)

        with patch("hermes_cli.tui.session_manager.logger") as mock_log:
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(1.0)
                s.connect(sock_path)
                s.sendall(b"not valid json\n")
                s.close()
            except OSError:
                pass
            time.sleep(0.15)
            mock_log.warning.assert_not_called()

        assert called == []
        listener.stop()


# ---------------------------------------------------------------------------
# SM-2: dead-code methods absent
# ---------------------------------------------------------------------------

class TestDeadCodeDeleted:

    def test_is_alive_absent(self):
        assert not hasattr(SessionManager, "is_alive")

    def test_verify_cmdline_absent(self):
        assert not hasattr(SessionManager, "_verify_cmdline")

    def test_get_orphans_absent(self):
        assert not hasattr(SessionManager, "get_orphans")


# ---------------------------------------------------------------------------
# SM-3: SessionIndex.write() atomic temp-file + rename
# ---------------------------------------------------------------------------

class TestSessionIndexAtomicWrite:

    def test_write_produces_valid_json(self, tmp_dir: Path):
        idx = SessionIndex(tmp_dir / "sessions.json")
        data = {"active_session_id": "abc", "sessions": [{"id": "abc"}]}
        idx.write(data)
        result = json.loads((tmp_dir / "sessions.json").read_text())
        assert result == data

    def test_write_is_atomic_on_serialization_error(self, tmp_dir: Path):
        idx = SessionIndex(tmp_dir / "sessions.json")
        original = {"active_session_id": "original", "sessions": []}
        idx.write(original)

        with patch("json.dump", side_effect=TypeError("bad")):
            with pytest.raises(TypeError):
                idx.write({"active_session_id": "corrupted", "sessions": []})

        result = json.loads((tmp_dir / "sessions.json").read_text())
        assert result["active_session_id"] == "original"

    def test_write_cleans_up_tmp_on_exception(self, tmp_dir: Path):
        idx = SessionIndex(tmp_dir / "sessions.json")

        with patch("os.replace", side_effect=OSError("fail")):
            with pytest.raises(OSError):
                idx.write({"sessions": []})

        tmp_files = list(tmp_dir.glob("*.tmp"))
        assert tmp_files == [], f"tmp file not cleaned up: {tmp_files}"

    def test_write_replaces_existing_content(self, tmp_dir: Path):
        idx = SessionIndex(tmp_dir / "sessions.json")
        idx.write({"active_session_id": "A", "sessions": []})
        idx.write({"active_session_id": "B", "sessions": []})
        result = json.loads((tmp_dir / "sessions.json").read_text())
        assert result["active_session_id"] == "B"

    def test_write_creates_parent_dirs(self, tmp_path: Path):
        nested = tmp_path / "a" / "b" / "c" / "sessions.json"
        idx = SessionIndex(nested)
        idx.write({"active_session_id": "", "sessions": []})
        assert nested.exists()

    def test_write_concurrent_serialization(self, tmp_dir: Path):
        idx = SessionIndex(tmp_dir / "sessions.json")
        # Pre-create the file so all writers can open it with "a+"
        idx.write({"writer": -1})

        barrier = threading.Barrier(4)
        errors = []

        def writer(i: int):
            try:
                barrier.wait(timeout=5)
                for _ in range(10):
                    idx.write({"writer": i})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == [], f"Writer errors: {errors}"
        result = json.loads((tmp_dir / "sessions.json").read_text())
        assert "writer" in result
        assert result["writer"] in range(4)
