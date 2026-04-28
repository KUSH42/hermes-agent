"""Real-PTY driver for live audits. Complement to Pilot; not for tests/tui/.

Requires tmux >= 3.0 on PATH. The `resize-window -x/-y` flag syntax changed in
tmux 3.0 — earlier versions will fail loudly at `_spawn` time.

Do NOT set HERMES_CI=1 in the env passed here — that suppresses the keystroke
recorder and audit JSONL will be empty.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from typing import Callable


class TmuxDriver:
    """Context manager that drives hermes (or any command) through a real PTY.

    Usage::

        with TmuxDriver("hermes", env={"HERMES_KEYSTROKE_LOG": "1"}) as drv:
            drv.wait_for(lambda s: "hermes>" in s, timeout=5)
            drv.send_keys("hello", literal=True)
            drv.send_keys("Enter")
            print(drv.capture())
    """

    def __init__(
        self,
        command: str,
        *,
        cols: int = 200,
        rows: int = 60,
        env: dict[str, str] | None = None,
    ) -> None:
        self.session = f"hermes-audit-{uuid.uuid4().hex[:8]}"
        self.command = command
        self._env = {**os.environ, **(env or {})}
        self._spawn(cols, rows)

    def _spawn(self, cols: int, rows: int) -> None:
        if not shutil.which("tmux"):
            raise RuntimeError("tmux not found on PATH; install tmux >= 3.0")
        # -d detached; -x/-y initial size; -s session name; bash -lc to inherit shell init.
        subprocess.run(
            [
                "tmux", "new-session", "-d",
                "-s", self.session,
                "-x", str(cols),
                "-y", str(rows),
                "bash", "-lc", self.command,
            ],
            check=True,
            env=self._env,
        )

    def send_keys(self, keys: str, *, literal: bool = False) -> None:
        """Send keys to the session.

        Pass ``literal=True`` for typed text (uses ``tmux send-keys -l``).
        Leave default for named keys such as ``Enter``, ``C-c``, ``Up``.
        """
        args = ["tmux", "send-keys", "-t", self.session]
        if literal:
            args.append("-l")
        args.append(keys)
        subprocess.run(args, check=True)

    def capture(self) -> str:
        """Return the full visible pane content as a string.

        Captured size equals the session size set at spawn or last ``resize()``
        call. No trailing-whitespace stripping is applied — keep raw output for
        cell-position assertions.
        """
        out = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", self.session],
            check=True,
            capture_output=True,
            text=True,
        )
        return out.stdout

    def resize(self, cols: int, rows: int) -> None:
        """Resize the session window, triggering a real SIGWINCH."""
        subprocess.run(
            [
                "tmux", "resize-window",
                "-t", self.session,
                "-x", str(cols),
                "-y", str(rows),
            ],
            check=True,
        )

    def wait_for(
        self,
        predicate: Callable[[str], bool],
        timeout: float = 5.0,
        interval: float = 0.1,
    ) -> bool:
        """Poll ``capture()`` until ``predicate`` returns True or timeout expires.

        Returns ``True`` if predicate was satisfied, ``False`` on timeout.
        Does not raise on timeout — caller decides how to handle it.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate(self.capture()):
                return True
            time.sleep(interval)
        return False

    def __enter__(self) -> "TmuxDriver":
        return self

    def __exit__(self, *_) -> None:
        # check=False — already-killed sessions are fine; let caller exceptions propagate.
        subprocess.run(
            ["tmux", "kill-session", "-t", self.session],
            check=False,
        )
