"""Parallel worktree session manager — data layer, file locking, IPC stubs."""
from __future__ import annotations

import fcntl
import json
import logging
import os
import platform
import socket
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class SessionRecord:
    id: str
    branch: str
    worktree_path: str
    pid: int
    socket_path: str
    agent_running: bool = False
    last_event: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SessionRecord":
        return cls(
            id=d["id"],
            branch=d.get("branch", ""),
            worktree_path=d.get("worktree_path", ""),
            pid=d.get("pid", 0),
            socket_path=d.get("socket_path", ""),
            agent_running=d.get("agent_running", False),
            last_event=d.get("last_event", ""),
        )


class SessionIndex:
    """Read/write sessions.json with fcntl.flock exclusive locking on writes."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def read(self) -> dict:
        """Opportunistic read — no lock, stale reads acceptable."""
        if not self._path.exists():
            return {"active_session_id": "", "sessions": []}
        try:
            return json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            return {"active_session_id": "", "sessions": []}

    def write(self, data: dict) -> None:
        """Locked write — serializes concurrent session processes."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a+") as lock_f:  # allow-sync-io: flock-locked write on event loop — <0.1ms on local FS; NFS risk accepted; worker migration deferred to separate PR
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            try:
                fd, tmp_path = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
                try:
                    with os.fdopen(fd, "w") as f:
                        json.dump(data, f, indent=2)
                    os.replace(tmp_path, str(self._path))
                except Exception:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    raise
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)

    def add_session(self, record: SessionRecord) -> None:
        data = self.read()
        sessions = data.get("sessions", [])
        sessions = [s for s in sessions if s.get("id") != record.id]
        sessions.append(record.to_dict())
        data["sessions"] = sessions
        self.write(data)

    def remove_session(self, session_id: str) -> None:
        data = self.read()
        data["sessions"] = [s for s in data.get("sessions", []) if s.get("id") != session_id]
        self.write(data)

    def update_active(self, session_id: str) -> None:
        data = self.read()
        data["active_session_id"] = session_id
        self.write(data)

    def get_sessions(self) -> list[SessionRecord]:
        data = self.read()
        result = []
        for s in data.get("sessions", []):
            try:
                result.append(SessionRecord.from_dict(s))
            except (KeyError, TypeError):
                continue
        return result

    def get_active_id(self) -> str:
        return self.read().get("active_session_id", "")


_MAX_SOCK_PATH = 104 if platform.system() == "Darwin" else 108


class SessionManager:
    """High-level session lifecycle: create, kill, orphan detection, path validation."""

    def __init__(self, session_dir: Path, max_sessions: int = 8) -> None:
        self._session_dir = Path(session_dir)
        self._max_sessions = max_sessions
        self._index = SessionIndex(self._session_dir / "sessions.json")

    @property
    def index(self) -> SessionIndex:
        return self._index

    def validate_socket_path(self, session_id: str) -> str:
        """Return socket path or raise ValueError if it exceeds OS limit."""
        path = str(self._session_dir / session_id / "notify.sock")
        if len(path) > _MAX_SOCK_PATH:
            raise ValueError(
                f"Socket path too long ({len(path)} > {_MAX_SOCK_PATH}): {path}"
            )
        return path

    def new_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def create_session_dir(self, session_id: str) -> Path:
        d = self._session_dir / session_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def kill_session(self, record: SessionRecord, *, timeout: float = 2.0) -> None:
        """Send SIGTERM; escalate to SIGKILL after timeout."""
        import signal
        try:
            os.kill(record.pid, signal.SIGTERM)
            deadline = time.monotonic() + timeout
            sleep_t = 0.01
            while time.monotonic() < deadline:
                try:
                    os.kill(record.pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(sleep_t)
                sleep_t = min(sleep_t * 2, 0.1)
            else:
                try:
                    os.kill(record.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        except ProcessLookupError:
            pass

    def write_state(self, session_dir: Path, record: SessionRecord) -> None:
        state_path = session_dir / "state.json"
        state_path.write_text(json.dumps(record.to_dict(), indent=2))

    def save_layout_blob(self, session_id: str, layout: dict) -> None:
        """Persist layout blob for a session to <session_dir>/<session_id>/layout.json."""
        layout_path = self._session_dir / session_id / "layout.json"
        try:
            layout_path.parent.mkdir(parents=True, exist_ok=True)
            layout_path.write_text(json.dumps(layout, indent=2))
        except OSError:
            pass

    def load_layout_blob(self, session_id: str) -> dict:
        """Read and return layout blob for a session; returns {} if absent or corrupt."""
        layout_path = self._session_dir / session_id / "layout.json"
        if not layout_path.exists():
            return {}
        try:
            return json.loads(layout_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def read_state(self, session_id: str) -> Optional[SessionRecord]:
        state_path = self._session_dir / session_id / "state.json"
        if not state_path.exists():
            return None
        try:
            return SessionRecord.from_dict(json.loads(state_path.read_text()))
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    def poll_state_until_pid(self, session_id: str, timeout: float = 3.0) -> Optional[SessionRecord]:
        """Poll state.json until PID is set (> 0) or timeout."""
        deadline = time.monotonic() + timeout
        sleep_t = 0.01
        while time.monotonic() < deadline:
            rec = self.read_state(session_id)
            if rec and rec.pid > 0:
                return rec
            time.sleep(sleep_t)
            sleep_t = min(sleep_t * 2, 0.1)
        return None


class _NotifyListener:
    """Daemon thread that listens on a UNIX socket for cross-session notifications.

    Calls on_event(event_dict) on receipt. Socket is created fresh on start(),
    closed on stop(). Messages are newline-delimited JSON.
    """

    def __init__(self, socket_path: str, on_event: Callable[[dict], None]) -> None:
        self._socket_path = socket_path
        self._on_event = on_event
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        try:
            Path(self._socket_path).unlink(missing_ok=True)
        except OSError:
            pass
        self._thread = threading.Thread(target=self._run, daemon=True, name="notify-listener")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except OSError:
                    pass

    def _run(self) -> None:
        try:
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(self._socket_path)
            srv.listen(4)
            srv.settimeout(1.0)
            with self._lock:
                self._sock = srv
            while not self._stop_event.is_set():
                try:
                    conn, _ = srv.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                threading.Thread(target=self._handle, args=(conn,), daemon=True).start()
        except OSError:
            pass
        finally:
            with self._lock:
                self._sock = None
            try:
                Path(self._socket_path).unlink(missing_ok=True)
            except OSError:
                pass

    def _handle(self, conn: socket.socket) -> None:
        try:
            buf = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
            for line in buf.split(b"\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    self._on_event(json.loads(line))
                except json.JSONDecodeError:
                    pass
                except Exception:
                    logger.warning(
                        "_NotifyListener._handle: on_event dispatch raised",
                        exc_info=True,
                    )
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass


def send_notification(socket_path: str, event: dict) -> bool:
    """Send a JSON notification to a notify.sock. Returns True on success."""
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        sock.connect(socket_path)
        sock.sendall((json.dumps(event) + "\n").encode())
        sock.close()
        return True
    except OSError:
        return False
