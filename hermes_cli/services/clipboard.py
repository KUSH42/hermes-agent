"""Non-blocking clipboard service for hermes.

Provides ClipboardService with off-thread probe/extract/read_text operations
so clipboard access never blocks the UI event loop.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from hermes_cli.clipboard import save_clipboard_image, has_clipboard_image

_log = logging.getLogger(__name__)


class ClipboardService:
    """Off-thread clipboard probe/extract/read with cancellation support."""

    def __init__(self) -> None:
        self._in_flight: threading.Thread | None = None
        self._cancel_evt: threading.Event = threading.Event()

    def probe(self, on_done: Callable[[bool], None], timeout: float = 8.0) -> None:
        """Check whether clipboard has an image. Calls on_done(bool) via _dispatch."""
        self._spawn(lambda: has_clipboard_image(), on_done, timeout)

    def extract(self, dest: Path, on_done: Callable[[bool], None], timeout: float = 8.0) -> None:
        """Extract image to dest. Calls on_done(True) on success, on_done(False) otherwise."""
        self._spawn(lambda: save_clipboard_image(dest), on_done, timeout)

    def read_text(self, on_done: Callable[[str], None], timeout: float = 3.0) -> None:
        """Read plain text from the OS clipboard off-thread.

        Tries in order: xclip -o -selection clipboard, wl-paste --no-newline,
        PowerShell Get-Clipboard. Calls on_done("") on all-failure. Calls
        on_done(text) on success. Always calls on_done exactly once, on the
        calling thread's app event loop via app.call_from_thread().
        """
        self._spawn_str(_read_os_clipboard_text, on_done, timeout)

    def cancel_in_flight(self) -> None:
        """Cancel the currently in-flight worker (best-effort; subprocess may finish)."""
        self._cancel_evt.set()

    def _spawn(self, work: Callable[[], bool], on_done: Callable[[bool], None], timeout: float) -> None:
        self.cancel_in_flight()
        self._cancel_evt = threading.Event()
        evt = self._cancel_evt
        fired_once = threading.Event()

        def _maybe_dispatch(result: bool) -> None:
            if not evt.is_set() and not fired_once.is_set():
                fired_once.set()
                self._dispatch(on_done, result)

        def _run() -> None:
            try:
                result = work()
            except Exception:
                _log.exception("ClipboardService work failed")
                result = False
            _maybe_dispatch(result)

        t = threading.Thread(target=_run, daemon=True)
        self._in_flight = t
        t.start()
        threading.Timer(timeout, lambda: _maybe_dispatch(False)).start()

    def _spawn_str(self, work: Callable[[], str], on_done: Callable[[str], None], timeout: float) -> None:
        self.cancel_in_flight()
        self._cancel_evt = threading.Event()
        evt = self._cancel_evt
        fired_once = threading.Event()

        def _maybe_dispatch(result: str) -> None:
            if not evt.is_set() and not fired_once.is_set():
                fired_once.set()
                self._dispatch_str(on_done, result)

        def _run() -> None:
            try:
                result = work()
            except Exception:
                _log.exception("ClipboardService read_text failed")
                result = ""
            _maybe_dispatch(result)

        t = threading.Thread(target=_run, daemon=True)
        self._in_flight = t
        t.start()
        threading.Timer(timeout, lambda: _maybe_dispatch("")).start()

    def _dispatch(self, on_done: Callable[[bool], None], result: bool) -> None:
        # Base: calls on_done on the current (worker) thread.
        # Subclasses MUST override to marshal back to the event-loop thread.
        raise NotImplementedError("Subclasses must override _dispatch to marshal to event-loop thread")

    def _dispatch_str(self, on_done: Callable[[str], None], result: str) -> None:
        # Base: calls on_done on the current (worker) thread.
        # Subclasses MUST override to marshal back to the event-loop thread.
        raise NotImplementedError("Subclasses must override _dispatch_str to marshal to event-loop thread")


class TextualClipboardService(ClipboardService):
    """ClipboardService variant that marshals callbacks to a Textual app event loop."""

    def __init__(self, app: object) -> None:
        super().__init__()
        self._app = app

    def _dispatch(self, on_done: Callable[[bool], None], result: bool) -> None:
        self._app.call_from_thread(on_done, result)

    def _dispatch_str(self, on_done: Callable[[str], None], result: str) -> None:
        self._app.call_from_thread(on_done, result)


def _read_os_clipboard_text() -> str:
    """Read plain text from the OS clipboard synchronously.

    Tries in order: xclip (X11), wl-paste (Wayland), PowerShell Get-Clipboard.
    Returns "" on all-failure.
    """
    # X11 — xclip
    try:
        r = subprocess.run(
            ["xclip", "-o", "-selection", "clipboard"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0:
            return r.stdout
    except FileNotFoundError:
        pass  # xclip not installed
    except Exception:
        _log.debug("xclip read_text failed", exc_info=True)

    # Wayland — wl-paste
    try:
        r = subprocess.run(
            ["wl-paste", "--no-newline"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0:
            return r.stdout
    except FileNotFoundError:
        pass  # wl-paste not installed
    except Exception:
        _log.debug("wl-paste read_text failed", exc_info=True)

    # Windows / WSL — PowerShell Get-Clipboard
    if sys.platform in ("win32",) or _is_wsl():
        exe = "powershell.exe" if _is_wsl() else "powershell"
        try:
            r = subprocess.run(
                [exe, "-NoProfile", "-NonInteractive", "-Command", "Get-Clipboard"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                return r.stdout.rstrip("\n")
        except FileNotFoundError:
            pass  # powershell not found
        except Exception:
            _log.debug("PowerShell Get-Clipboard failed", exc_info=True)

    return ""


def _is_wsl() -> bool:
    try:
        from hermes_constants import is_wsl
        return is_wsl()
    except Exception:
        return False
