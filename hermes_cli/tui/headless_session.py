"""HeadlessSession — background agent pipeline without Textual TUI."""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections import deque
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class OutputJSONLWriter:
    """Append-only output.jsonl writer with ring-buffer rotation. Plain text only (ANSI stripped)."""

    _MAX_ROWS: int = 2000

    def __init__(self, path: Path, max_lines: int = 2000) -> None:
        self._path = path
        self._MAX_ROWS = max_lines  # allow override per-instance
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = open(self._path, "a")  # append-only; creates if absent  # allow-sync-io: long-lived writer, headless only
        self._row_count = 0
        self._ring: deque[str] = deque(maxlen=self._MAX_ROWS)

    def write(self, text: str, role: str = "assistant") -> None:
        import re as _re
        # Strip ANSI escape sequences
        plain = _re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', text)
        # Strip Rich markup tags (handles [bold], [bold red], [link=x], [#ff0000], etc.)
        plain = _re.sub(r'\[[^\[\]\n]*\]', '', plain)
        entry = {"ts": time.time(), "text": plain, "role": role}
        line = json.dumps(entry) + "\n"
        self._ring.append(line)
        try:
            self._fp.write(line)
            self._row_count += 1
            if self._row_count > self._MAX_ROWS:
                self._rotate()
        except OSError:
            logger.warning("HeadlessSession: failed to write output.jsonl", exc_info=True)

    def _rotate(self) -> None:
        """Truncate file and re-write the last _MAX_ROWS lines from the ring."""
        try:
            self._fp.close()
            with open(self._path, "w") as f:  # allow-sync-io: rotation is infrequent, headless only
                f.writelines(self._ring)
            self._fp = open(self._path, "a")  # allow-sync-io: reopen after rotation
            self._row_count = len(self._ring)
        except OSError:
            logger.warning("HeadlessSession: failed to rotate output.jsonl", exc_info=True)

    def close(self) -> None:
        try:
            self._fp.flush()
            self._fp.close()
        except OSError:
            logger.debug("HeadlessSession: failed to close output.jsonl", exc_info=True)

    def load_lines(self) -> list[dict]:
        if not self._path.exists():
            return []
        lines = []
        try:
            for line in self._path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    lines.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        except OSError:
            logger.debug("HeadlessSession: failed to read output.jsonl", exc_info=True)
        return lines


class HeadlessSession:
    """Runs agent pipeline with no TUI. Writes output to output.jsonl; handles IPC."""

    def __init__(
        self,
        cli: object,
        session_id: str,
        session_dir: Path,
        output_buffer_lines: int = 2000,
    ) -> None:
        self._cli = cli
        self._session_id = session_id
        self._session_dir = Path(session_dir) / session_id
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._writer = OutputJSONLWriter(
            self._session_dir / "output.jsonl",
            max_lines=output_buffer_lines,
        )
        self._socket_path = str(self._session_dir / "notify.sock")

    def run(self) -> None:
        """Register PID in state.json, then run the CLI agent loop."""
        self._register_pid()
        try:
            self._cli.run()
        finally:
            self._on_complete()

    def _register_pid(self) -> None:
        state = {
            "id": self._session_id,
            "branch": self._get_branch(),
            "worktree_path": str(self._session_dir),
            "pid": os.getpid(),
            "socket_path": self._socket_path,
            "agent_running": False,
            "last_event": "started",
        }
        state_path = self._session_dir / "state.json"
        state_path.write_text(json.dumps(state, indent=2))

    def _get_branch(self) -> str:
        import subprocess
        try:
            result = subprocess.run(  # allow-sync-io: init-time, one-shot, no event loop running
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=3,
                cwd=str(self._session_dir),
            )
            return result.stdout.strip()
        except Exception:
            logger.debug("HeadlessSession._get_branch: subprocess failed", exc_info=True)
            return ""

    def _on_complete(self) -> None:
        from hermes_cli.tui.session_manager import SessionIndex
        try:
            idx = SessionIndex(self._session_dir.parent / "sessions.json")
            active_id = idx.get_active_id()
            if active_id and active_id != self._session_id:
                from hermes_cli.tui.session_manager import send_notification
                send_notification(
                    str(self._session_dir.parent / active_id / "notify.sock"),
                    {"type": "agent_complete", "session_id": self._session_id, "message": "agent finished"},
                )
        except Exception:
            logger.warning("HeadlessSession._on_complete: notification send failed", exc_info=True)

    def write_output(self, text: str, role: str = "assistant") -> None:
        self._writer.write(text, role)

    def load_history(self) -> list[dict]:
        return self._writer.load_lines()
