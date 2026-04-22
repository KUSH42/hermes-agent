"""BashService — executes shell commands in a background thread and streams
output to a BashOutputBlock widget."""
from __future__ import annotations

import os
import shlex
import signal
import subprocess
import time as _time
from typing import TYPE_CHECKING

from .base import AppService

if TYPE_CHECKING:
    from hermes_cli.tui.widgets.bash_output_block import BashOutputBlock


class BashService(AppService):
    """Manages one-at-a-time shell command execution for bash-passthrough mode."""

    def __init__(self, app: "HermesApp") -> None:  # type: ignore[name-defined]
        super().__init__(app)
        self._proc: subprocess.Popen | None = None
        self._running: bool = False

    @property
    def is_running(self) -> bool:
        return self._running

    def run(self, cmd: str) -> None:
        """Entry point called from the event loop (dispatch_input_submitted)."""
        block = self.app._mount_bash_block(cmd)
        self._running = True
        try:
            self.app._start_bash_worker(cmd, block)
        except Exception:
            self._running = False
            raise

    def kill(self) -> None:
        """Send SIGINT to the entire process group of the running command."""
        proc = self._proc
        if proc is not None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGINT)
            except (ProcessLookupError, PermissionError, OSError):
                pass

    def _exec_sync(self, cmd: str, block: "BashOutputBlock") -> None:
        """Blocking execution — runs inside @work(thread=True, group='bash')."""
        start = _time.monotonic()
        exit_code = 1

        # Split before the Popen try so shlex ValueError (malformed quote) is
        # caught by the explicit except ValueError block here, not buried in the
        # Popen block. cmd0 captured here for FileNotFoundError display.
        try:
            args = shlex.split(cmd)
        except ValueError as exc:
            self.app.call_from_thread(block.push_line, f"[parse error] {exc}")
            self.app.call_from_thread(
                self._finalize, block, 1, _time.monotonic() - start
            )
            return
        cmd0 = args[0] if args else cmd

        try:
            self._proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,  # own process group → killpg works
            )
            for line in self._proc.stdout:
                self.app.call_from_thread(block.push_line, line.rstrip("\n"))
            self._proc.wait()
            exit_code = self._proc.returncode
        except FileNotFoundError:
            # cmd0 captured before try — no second shlex.split call
            self.app.call_from_thread(
                block.push_line, f"bash: {cmd0}: command not found"
            )
        except Exception as exc:
            self.app.call_from_thread(block.push_line, f"[error] {exc}")
        finally:
            self._proc = None

        elapsed = _time.monotonic() - start
        # Clear _running only after mark_done is dispatched to avoid TOCTOU:
        # a new !cmd submitted after _running=False but before mark_done would
        # mount a new block before the old one finishes its --done transition.
        self.app.call_from_thread(self._finalize, block, exit_code, elapsed)

    def _finalize(
        self, block: "BashOutputBlock", exit_code: int, elapsed: float
    ) -> None:
        """Called on event loop via call_from_thread. Clears state + marks block done."""
        self._running = False
        block.mark_done(exit_code, elapsed)
