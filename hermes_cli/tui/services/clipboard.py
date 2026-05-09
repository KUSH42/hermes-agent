"""Non-blocking clipboard service for image probe/extract operations.

PS-NB-1: ClipboardService skeleton with probe(), extract(), cancel_in_flight().

Two thin subclasses marshal callbacks back to the correct event-loop thread:
  - TextualClipboardService   → app.call_from_thread(on_done, result)
  - PromptToolkitClipboardService → loop.call_soon_threadsafe(on_done, result)
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

_log = logging.getLogger(__name__)


class ClipboardService:
    """Background-thread clipboard probe/extract with single-fire callback guarantee.

    Worker threads run as daemons so they never block process exit.
    The ``fired_once`` guard ensures exactly one ``on_done`` call regardless
    of races between the worker completing and the timeout timer firing.
    Cancellation (via ``cancel_in_flight``) sets the cancel event so that
    a pending callback is silently dropped; the underlying subprocess still
    runs to completion (we cannot kill it), but the callback is suppressed.
    """

    def __init__(self) -> None:
        self._in_flight: threading.Thread | None = None
        self._cancel_evt: threading.Event = threading.Event()

    def probe(self, on_done: Callable[[bool], None], timeout: float = 8.0) -> None:
        """Check whether clipboard has an image. Dispatches on_done via _dispatch."""
        from hermes_cli.clipboard import has_clipboard_image
        self._spawn(lambda: has_clipboard_image(), on_done, timeout)

    def extract(self, dest: Path, on_done: Callable[[bool], None], timeout: float = 8.0) -> None:
        """Extract image to dest. Dispatches on_done with True on success, False otherwise."""
        from hermes_cli.clipboard import save_clipboard_image
        self._spawn(lambda: save_clipboard_image(dest), on_done, timeout)

    def cancel_in_flight(self) -> None:
        """Drop any pending callback from the current in-flight operation.

        The underlying subprocess is not killed — it runs to completion in
        the background — but the callback is never dispatched.
        """
        self._cancel_evt.set()

    def _spawn(self, work: Callable[[], bool], on_done: Callable[[bool], None], timeout: float) -> None:
        self.cancel_in_flight()
        self._cancel_evt = threading.Event()
        evt = self._cancel_evt
        # fired_once ensures exactly one on_done call regardless of race between
        # the worker completing and the timeout timer firing.
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

    def _dispatch(self, on_done: Callable[[bool], None], result: bool) -> None:
        # Base implementation calls on_done on the current (worker) thread.
        # Subclasses MUST override to marshal back to the event-loop thread:
        #   TextualClipboardService  → self._app.call_from_thread(on_done, result)
        #   PromptToolkitClipboardService → self._loop.call_soon_threadsafe(on_done, result)
        raise NotImplementedError("Subclasses must override _dispatch to marshal to event-loop thread")


class TextualClipboardService(ClipboardService):
    """ClipboardService that marshals callbacks back to a Textual app's event loop."""

    def __init__(self, app: "Any") -> None:
        super().__init__()
        self._app = app

    def _dispatch(self, on_done: Callable[[bool], None], result: bool) -> None:
        try:
            self._app.call_from_thread(on_done, result)
        except Exception:
            _log.warning("TextualClipboardService: call_from_thread failed", exc_info=True)


class PromptToolkitClipboardService(ClipboardService):
    """ClipboardService that marshals callbacks back to a prompt_toolkit asyncio loop."""

    def __init__(self, loop: "asyncio.AbstractEventLoop") -> None:
        super().__init__()
        self._loop = loop

    def _dispatch(self, on_done: Callable[[bool], None], result: bool) -> None:
        try:
            self._loop.call_soon_threadsafe(on_done, result)
        except Exception:
            # loop may be closed on shutdown — acceptable to drop the callback
            _log.debug("PromptToolkitClipboardService: call_soon_threadsafe failed (loop closed?)", exc_info=True)
