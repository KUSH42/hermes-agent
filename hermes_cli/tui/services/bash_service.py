"""BashService — executes shell commands in a background thread and streams
output to a BashOutputBlock widget."""
from __future__ import annotations

import os
import signal
import subprocess
import time as _time
from typing import TYPE_CHECKING

from .base import AppService

if TYPE_CHECKING:
    from hermes_cli.tui.widgets.bash_output_block import BashOutputBlock

# CWD-2b: sentinel printed by the shell wrapper after every command to report
# the final working directory. Chosen to be long/unique — collision negligible.
_CWD_SENTINEL = "HERMES_CWD_8f7e2a1b="


class BashService(AppService):
    """Manages one-at-a-time shell command execution for bash-passthrough mode."""

    def __init__(self, app: "HermesApp") -> None:  # type: ignore[name-defined]
        super().__init__(app)
        self._proc: subprocess.Popen | None = None
        self._running: bool = False
        # CWD-2a: persistent CWD across consecutive bash commands
        self._bash_cwd: str = os.getcwd()

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

        # CWD-2c: wrap command in sh -c so that:
        #   1. Shell features (pipes, redirects, &&) work correctly
        #   2. We append a pwd probe to capture the final CWD after any cd
        wrapped = (
            f"{{ {cmd}; }}; "
            f"__ex=$?; "
            f"printf '%s%s\\n' '{_CWD_SENTINEL}' \"$(pwd)\"; "
            f"exit \"$__ex\""
        )

        _extracted_cwd: str | None = None
        try:
            self._proc = subprocess.Popen(  # allow-sync-io: long-lived Popen in @work(thread=True, group='bash'), off event loop
                ["sh", "-c", wrapped],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,  # own process group → killpg works
                cwd=self._bash_cwd,      # CWD-2c: persistent CWD
            )
            # CWD-2d: strip the sentinel line from display; capture the CWD it carries
            for line in self._proc.stdout:
                raw = line.rstrip("\n")
                if raw.startswith(_CWD_SENTINEL):
                    _extracted_cwd = raw[len(_CWD_SENTINEL):]
                    continue  # do NOT push sentinel to display
                self.app.call_from_thread(block.push_line, raw)
            self._proc.wait()
            exit_code = self._proc.returncode
        except FileNotFoundError:
            self.app.call_from_thread(block.push_line, "[error] sh not found")
        except Exception as exc:
            self.app.call_from_thread(block.push_line, f"[error] {exc}")
        finally:
            self._proc = None

        elapsed = _time.monotonic() - start
        # CWD-2e: pass extracted CWD to _finalize so it can update status_cwd
        self.app.call_from_thread(
            self._finalize, block, exit_code, elapsed, _extracted_cwd
        )

    def _finalize(
        self,
        block: "BashOutputBlock",
        exit_code: int,
        elapsed: float,
        new_cwd: str | None = None,
    ) -> None:
        """Called on event loop via call_from_thread. Clears state + marks block done."""
        self._running = False
        if new_cwd:
            self._bash_cwd = new_cwd
            self.app.status_cwd = new_cwd  # reactive → triggers StatusBar refresh
        block.mark_done(exit_code, elapsed)
