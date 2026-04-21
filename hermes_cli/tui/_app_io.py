"""_AppIOMixin — output queue, TTE effects, and flush methods for HermesApp."""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual import work
from textual.css.query import NoMatches

from hermes_cli.tui._app_utils import _CPYTHON_FAST_PATH, _run_effect_sync

if TYPE_CHECKING:
    pass

import logging as _logging
import os as _os_mod

logger = _logging.getLogger(__name__)


class _AppIOMixin:
    """Output queue consumer, write_output, TTE animation, and flush methods.

    Extracted from HermesApp to reduce file size.  Self is always a HermesApp
    instance at runtime — all attribute access on self is valid.
    """

    # --- Output consumer (bounded queue → RichLog) ---

    @work(exclusive=True)
    async def _consume_output(self) -> None:
        """Async worker consuming the output queue.

        Runs on the Textual event loop. ``@work`` with no ``thread=True``
        means this is an async coroutine worker — correct for awaiting
        the asyncio.Queue.

        The ``await asyncio.sleep(0)`` after each chunk yields back to the
        event loop so that layout/refresh callbacks (e.g. processing deferred
        RichLog renders after a new MessagePanel mount) can run between chunks
        rather than piling up until the queue is fully drained.

        ``_first_chunk_in_turn`` is a local flag reset on each None sentinel.
        The first non-None chunk per turn deactivates the ThinkingWidget shimmer.
        """
        from hermes_cli.tui.widgets import OutputPanel, ThinkingWidget
        _first_chunk_in_turn: bool = True
        while True:
            chunk = await self._output_queue.get()  # type: ignore[attr-defined]
            if chunk is None:
                # Sentinel: flush live line; reset first-chunk flag for next turn
                _first_chunk_in_turn = True
                try:
                    panel = self.query_one(OutputPanel)  # type: ignore[attr-defined]
                    panel.flush_live()
                    # flush_live() may commit a pending buffered line (setext lookahead),
                    # extending the virtual height AFTER the last chunk's scroll_end fired.
                    # Queue one more scroll_end so the final line is always visible.
                    if not panel._user_scrolled_up:
                        self.call_after_refresh(panel.scroll_end, animate=False)  # type: ignore[attr-defined]
                except NoMatches:
                    pass
                continue
            # Deactivate shimmer on first content chunk of each turn
            if _first_chunk_in_turn:
                _first_chunk_in_turn = False
                try:
                    self.query_one(ThinkingWidget).deactivate()  # type: ignore[attr-defined]
                except NoMatches:
                    pass
            try:
                panel = self.query_one(OutputPanel)  # type: ignore[attr-defined]
                panel.record_raw_output(chunk)
                panel.live_line.feed(chunk)
                try:
                    msg = panel.current_message
                    if msg is not None:
                        engine = getattr(msg, "_response_engine", None)
                        if engine is not None:
                            engine.feed(chunk)
                except Exception:
                    pass
                panel.refresh(layout=True)
                if not panel._user_scrolled_up:
                    self.call_after_refresh(panel.scroll_end, animate=False)  # type: ignore[attr-defined]
            except NoMatches:
                pass
            await asyncio.sleep(0)

    # --- Thread-safe output writing ---

    def write_output(self, text: str) -> None:
        """Thread-safe: enqueue text for the output consumer.

        Uses ``call_soon_threadsafe`` to ensure the event loop wakes
        immediately when a chunk is enqueued from the agent thread.
        """
        if self._event_loop is None:  # type: ignore[attr-defined]
            return
        try:
            if _CPYTHON_FAST_PATH:
                self._output_queue.put_nowait(text)  # type: ignore[attr-defined]
            else:
                self._event_loop.call_soon_threadsafe(  # type: ignore[attr-defined]
                    self._output_queue.put_nowait, text
                )
            # Clear the dropped flag on a successful enqueue
            if self.status_output_dropped:  # type: ignore[attr-defined]
                self.status_output_dropped = False  # type: ignore[attr-defined]
        except asyncio.QueueFull:
            # Backpressure: UI is 4096 chunks behind — drop rather than OOM.
            # Signal the user via StatusBar so they know output was truncated.
            logger.warning("Output queue full — dropped chunk (backpressure)")
            self.status_output_dropped = True  # type: ignore[attr-defined]
        except RuntimeError:
            pass  # Event loop closed

    async def _play_effects_async(
        self,
        effect_name: str,
        text: str,
        params: dict[str, object] | None = None,
    ) -> bool:
        """Suspend Textual, run TTE animation, then resume."""
        loop = asyncio.get_running_loop()
        with self.suspend():  # type: ignore[attr-defined]
            return await loop.run_in_executor(None, _run_effect_sync, effect_name, text, params)

    @work
    async def _play_effects(
        self,
        effect_name: str,
        text: str,
        params: dict[str, object] | None = None,
    ) -> None:
        """Suspend Textual, run a TTE animation, then resume.

        ``App.suspend()`` is a **synchronous** context manager — use ``with``,
        not ``async with``.  The blocking TTE call is offloaded to a thread-pool
        executor so it doesn't block the event loop even while suspended.

        Safe to call from any thread; ``@work`` handles dispatch.
        """
        await self._play_effects_async(effect_name, text, params)

    def play_effects_blocking(
        self,
        effect_name: str,
        text: str,
        params: dict[str, object] | None = None,
    ) -> bool:
        """Run a TTE animation and block caller until it completes."""
        if self._event_loop is None:  # type: ignore[attr-defined]
            return False
        future = asyncio.run_coroutine_threadsafe(
            self._play_effects_async(effect_name, text, params),
            self._event_loop,  # type: ignore[attr-defined]
        )
        try:
            return bool(future.result())
        except Exception:
            return False

    def get_working_directory(self) -> Path:
        """Return TUI workspace root used for path completion and file-drop links."""
        candidate = getattr(self.cli, "terminal_cwd", None)  # type: ignore[attr-defined]
        if not isinstance(candidate, (str, bytes, Path)) or not str(candidate).strip():
            candidate = None
        candidate = candidate or _os_mod.environ.get("TERMINAL_CWD") or _os_mod.getcwd()
        try:
            return Path(candidate).expanduser().resolve()
        except Exception:
            return Path(_os_mod.getcwd()).resolve()

    def _play_tte_main(
        self,
        effect_name: str,
        text: str,
        params: dict[str, object] | None = None,
        done_event: "threading.Event | None" = None,
    ) -> bool:
        from hermes_cli.tui.widgets import TTEWidget
        try:
            widget = self.query_one("#tte-effect", TTEWidget)  # type: ignore[attr-defined]
            widget.play(effect_name, text, params=params, done_event=done_event)
            return True
        except NoMatches:
            if done_event is not None:
                done_event.set()
            return False

    def play_tte(
        self,
        effect_name: str,
        text: str,
        params: dict[str, object] | None = None,
        done_event: "threading.Event | None" = None,
    ) -> bool:
        """Play a TTE animation inline in TUI."""
        if self._event_loop is not None and threading.current_thread() is not threading.main_thread():  # type: ignore[attr-defined]
            self.call_from_thread(self._play_tte_main, effect_name, text, params, done_event)  # type: ignore[attr-defined]
            return True
        return self._play_tte_main(effect_name, text, params, done_event)

    def play_tte_blocking(
        self,
        effect_name: str,
        text: str,
        params: dict[str, object] | None = None,
        timeout_s: float = 15.0,
    ) -> bool:
        """Play a TTE animation inline and wait for completion."""
        done_event = threading.Event()
        started = self.play_tte(effect_name, text, params=params, done_event=done_event)
        if not started:
            return False
        done_event.wait(timeout_s)
        return True

    def _stop_tte_main(self) -> None:
        from hermes_cli.tui.widgets import TTEWidget
        try:
            widget = self.query_one("#tte-effect", TTEWidget)  # type: ignore[attr-defined]
            widget.stop()
        except NoMatches:
            pass

    def stop_tte(self) -> None:
        """Stop any running inline TTE animation."""
        if self._event_loop is not None and threading.current_thread() is not threading.main_thread():  # type: ignore[attr-defined]
            self.call_from_thread(self._stop_tte_main)  # type: ignore[attr-defined]
            return
        self._stop_tte_main()

    def flush_output(self) -> None:
        """Thread-safe: send flush sentinel to commit any trailing partial line."""
        if self._event_loop is None:  # type: ignore[attr-defined]
            return
        try:
            if _CPYTHON_FAST_PATH:
                self._output_queue.put_nowait(None)  # type: ignore[attr-defined]
            else:
                self._event_loop.call_soon_threadsafe(  # type: ignore[attr-defined]
                    self._output_queue.put_nowait, None
                )
        except (asyncio.QueueFull, RuntimeError):
            pass
