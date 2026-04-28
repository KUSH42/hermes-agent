"""BashOutputBlock — widget that displays streaming output from a bash command."""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

_log = logging.getLogger(__name__)

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from hermes_cli.tui.widgets.renderers import CopyableRichLog

if TYPE_CHECKING:
    from textual.timer import Timer


class BashOutputBlock(Static):
    """Displays a shell command header + streaming output body.

    Uses CopyableRichLog (not bare RichLog) to avoid the pre-layout width
    collapse bug when the first output line arrives before layout completes.
    """

    DEFAULT_CSS = """
    BashOutputBlock {
        border-left: vkey $chevron-shell 60%;
        margin-bottom: 1;
        height: auto;
    }
    BashOutputBlock > #bash-header {
        height: 1;
    }
    BashOutputBlock > #bash-header > #bash-cmd {
        width: 1fr;
    }
    BashOutputBlock > #bash-header > #bash-status {
        width: auto;
        color: $text-muted;
    }
    BashOutputBlock > #bash-body {
        height: auto;
        max-height: 30;
    }
    BashOutputBlock.--error > #bash-header {
        color: $error;
    }
    BashOutputBlock.--done > #bash-header > #bash-status {
        color: $text-muted;
    }
    """

    def __init__(self, cmd: str) -> None:
        super().__init__()
        self._cmd = cmd
        self._start_time: float = 0.0
        self._elapsed_timer: Timer | None = None
        self._body: CopyableRichLog | None = None
        self._status: Static | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="bash-header"):
            yield Static(self._cmd_label(), id="bash-cmd")
            yield Static("running…", id="bash-status")
        yield CopyableRichLog(id="bash-body", wrap=True, markup=False)

    def on_mount(self) -> None:
        self._body = self.query_one("#bash-body", CopyableRichLog)
        self._status = self.query_one("#bash-status", Static)
        self._start_time = time.monotonic()
        self.add_class("--running")
        self._elapsed_timer = self.set_interval(0.5, self._tick_elapsed)

    def on_unmount(self) -> None:
        """Stop elapsed timer and kill any running process on widget removal."""
        if self._elapsed_timer is not None:
            self._elapsed_timer.stop()
            self._elapsed_timer = None
        if self.has_class("--running"):
            try:
                self.app._svc_bash.kill()
            except Exception:
                # best-effort process teardown; ignore if already dead
                pass

    def push_line(self, line: str) -> None:
        """Append one output line. Call via app.call_from_thread."""
        if self._body is not None:
            try:
                from rich.text import Text
                self._body.write(Text.from_ansi(line))
            except Exception:
                _log.debug("push_line: line append failed", exc_info=True)

    def mark_done(self, exit_code: int, elapsed_s: float) -> None:
        """Transition to completed state. Called on event loop via call_from_thread."""
        if self._elapsed_timer is not None:
            self._elapsed_timer.stop()
            self._elapsed_timer = None
        self.remove_class("--running")
        self.add_class("--done")
        if exit_code != 0:
            self.add_class("--error")
        if self._status is not None:
            icon = "✓" if exit_code == 0 else f"✗ exit {exit_code}"
            self._status.update(f"{elapsed_s:.2f}s  {icon}")

    def _tick_elapsed(self) -> None:
        elapsed = time.monotonic() - self._start_time
        if self._status is not None:
            self._status.update(f"{elapsed:.1f}s")

    def _cmd_label(self) -> str:
        label = f"$ {self._cmd}"
        return label if len(label) <= 63 else label[:60] + "…"
