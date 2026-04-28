"""Output consumer, TTE runner, effects service extracted from _app_io.py."""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from textual.css.query import NoMatches

from hermes_cli.tui._app_utils import _CPYTHON_FAST_PATH, _run_effect_sync
from hermes_cli.tui.perf import measure

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp

import logging as _logging
import os as _os_mod

logger = _logging.getLogger(__name__)

from .base import AppService


class IOService(AppService):
    """
    Output consumer, TTE runner, effects.
    Migrated from _AppIOMixin in _app_io.py.

    Methods:
      consume_output        — async body of the @work _consume_output worker
      write_output          — thread-safe enqueue text
      flush_output          — thread-safe flush sentinel
      play_effects_async    — suspend Textual and run TTE animation (async)
      play_effects_blocking — run TTE and block caller
      play_tte_main         — inner helper: find TTEWidget and call play()
      play_tte              — thread-safe TTE dispatch
      play_tte_blocking     — play TTE and wait for completion
      stop_tte_main         — inner helper: stop TTEWidget
      stop_tte              — thread-safe TTE stop
      get_working_directory — workspace root for path completion
    """

    def __init__(self, app: "HermesApp") -> None:
        super().__init__(app)

    # --- Output consumer body (called by @work wrapper on App mixin) ---

    async def consume_output(self) -> None:
        """Async body for the output queue consumer worker.

        Imported from _AppIOMixin._consume_output.  The @work decorator lives on
        the App mixin adapter; this method contains the pure logic.
        """
        from hermes_cli.tui.widgets import OutputPanel, ThinkingWidget
        app = self.app
        _first_chunk_in_turn: bool = True
        while True:
            chunk = await app._output_queue.get()
            if chunk is None:
                was_streaming = not _first_chunk_in_turn
                _first_chunk_in_turn = True
                if was_streaming:
                    # D2: if compaction progress is stuck > 0 when stream ends, signal done
                    if getattr(app, "status_compaction_progress", 0.0) > 0.0:
                        app.status_compaction_progress = 0.0
                    app.hooks.fire("on_streaming_end")
                    # A1: revert to REASONING (or IDLE if turn already ended)
                    from hermes_cli.tui.agent_phase import Phase as _Phase
                    if getattr(app, "agent_running", False):
                        app.status_phase = _Phase.REASONING
                    else:
                        app.status_phase = _Phase.IDLE
                try:
                    panel = app.query_one(OutputPanel)
                    panel.flush_live()
                    if not panel._user_scrolled_up:
                        app.call_after_refresh(panel.scroll_end, animate=False)
                except NoMatches:
                    pass
                continue
            if _first_chunk_in_turn:
                _first_chunk_in_turn = False
                # A1: mark STREAMING phase on first token
                from hermes_cli.tui.agent_phase import Phase as _Phase
                app.status_phase = _Phase.STREAMING
                app.hooks.fire("on_streaming_start")
                try:
                    app.query_one(ThinkingWidget).deactivate()
                except NoMatches:
                    pass
                # D-4: clear layout-reserve row on first stream chunk
                try:
                    app.query_one(ThinkingWidget).clear_reserve()
                except NoMatches:
                    pass
            _seq = getattr(app, "_perf_chunk_seq", 0) + 1
            app._perf_chunk_seq = _seq
            logger.debug("[STREAM-SEQ] seq=%d size=%d", _seq, len(chunk))
            with measure("io.consume_chunk", budget_ms=8.0, silent=True):
                try:
                    panel = app.query_one(OutputPanel)
                    panel.record_raw_output(chunk)
                    panel.live_line.feed(chunk)
                    try:
                        msg = panel.current_message
                        if msg is not None:
                            msg.record_raw(chunk)
                            engine = getattr(msg, "_response_engine", None)
                            if engine is not None:
                                with measure("io.engine_feed", budget_ms=4.0, silent=True):
                                    engine.feed(chunk)
                    except Exception:
                        # Suppress per-chunk record_raw / engine.feed failures so the stream stays alive;
                        # log full traceback so the failure is recoverable from the log.
                        logger.warning(
                            "io.consume: per-chunk msg.record_raw / engine.feed failed: chunk_len=%d head=%r",
                            len(chunk), chunk[:80], exc_info=True,
                        )
                    with measure("io.panel_refresh", budget_ms=6.0, silent=True):
                        panel.refresh(layout=True)
                    if not panel._user_scrolled_up:
                        app.call_after_refresh(panel.scroll_end, animate=False)
                except NoMatches:
                    pass
            await asyncio.sleep(0)

    # --- Thread-safe output writing ---

    def write_output(self, text: str) -> None:
        """Thread-safe: enqueue text for the output consumer."""
        app = self.app
        if app._event_loop is None:
            return
        try:
            if _CPYTHON_FAST_PATH:
                app._output_queue.put_nowait(text)
            else:
                # `put_nowait` is sync; `call_soon_threadsafe` is correct for thread →
                # loop scheduling here. If `_output_queue` ever becomes an async-producer
                # (e.g. `await put(...)`), switch to
                # `asyncio.run_coroutine_threadsafe(...)` instead.
                app._event_loop.call_soon_threadsafe(
                    app._output_queue.put_nowait, text
                )
            if app.status_output_dropped:
                app.status_output_dropped = False
            qsize = app._output_queue.qsize()
            maxsize = app._output_queue.maxsize
            if not app.status_output_pressure and qsize >= maxsize * 3 // 4:
                app.status_output_pressure = True
            elif app.status_output_pressure and qsize < maxsize // 2:
                app.status_output_pressure = False
        except asyncio.QueueFull:
            from hermes_cli.tui.perf import _queue_probe
            _queue_probe.record_drop()
            if not app.status_output_dropped:
                logger.warning(
                    "IOService.write_output: output queue full (maxsize=%d); "
                    "chunks will be dropped until consumer catches up",
                    app._output_queue.maxsize,
                )
            app.status_output_dropped = True
        except RuntimeError:
            pass

    def flush_output(self) -> None:
        """Thread-safe: send flush sentinel; retries once if queue is transiently full."""
        app = self.app
        if app._event_loop is None:
            return

        async def _send_flush() -> None:
            try:
                app._output_queue.put_nowait(None)
            except asyncio.QueueFull:
                # Consumer is behind — yield one tick, then retry.
                await asyncio.sleep(0)
                try:
                    app._output_queue.put_nowait(None)
                except asyncio.QueueFull:
                    logger.warning(
                        "IOService.flush_output: sentinel dropped after retry "
                        "(queue maxsize=%d); turn flush will be skipped",
                        app._output_queue.maxsize,
                    )

        try:
            asyncio.run_coroutine_threadsafe(_send_flush(), app._event_loop)
        except RuntimeError:
            pass

    # --- TTE effects (suspend-based, not TTEWidget) ---

    async def play_effects_async(
        self,
        effect_name: str,
        text: str,
        params: "dict[str, object] | None" = None,
    ) -> bool:
        """Suspend Textual, run TTE animation, then resume.

        Returns True if the effect played successfully, False if busy or failed.
        """
        if self.app._suspend_busy:
            return False
        try:
            self.app._suspend_busy = True  # first line inside try — consistent with safe_edit_cmd
            loop = asyncio.get_running_loop()
            with self.app.suspend():
                await loop.run_in_executor(None, _run_effect_sync, effect_name, text, params)
            return True
        except Exception:
            return False
        finally:
            self.app._suspend_busy = False

    def play_effects_blocking(
        self,
        effect_name: str,
        text: str,
        params: "dict[str, object] | None" = None,
    ) -> bool:
        """Run a TTE animation and block caller until it completes."""
        app = self.app
        if app._event_loop is None:
            return False
        future = asyncio.run_coroutine_threadsafe(
            self.play_effects_async(effect_name, text, params),
            app._event_loop,
        )
        try:
            return bool(future.result())
        except Exception:
            return False

    # --- Inline TTEWidget helpers ---

    def play_tte_main(
        self,
        effect_name: str,
        text: str,
        params: "dict[str, object] | None" = None,
        done_event: "threading.Event | None" = None,
    ) -> bool:
        from hermes_cli.tui.widgets import TTEWidget
        try:
            widget = self.app.query_one("#tte-effect", TTEWidget)
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
        params: "dict[str, object] | None" = None,
        done_event: "threading.Event | None" = None,
    ) -> bool:
        """Play a TTE animation inline in TUI."""
        app = self.app
        if app._event_loop is not None and threading.current_thread() is not threading.main_thread():
            app.call_from_thread(self.play_tte_main, effect_name, text, params, done_event)
            return True
        return self.play_tte_main(effect_name, text, params, done_event)

    def play_tte_blocking(
        self,
        effect_name: str,
        text: str,
        params: "dict[str, object] | None" = None,
        timeout_s: float = 15.0,
    ) -> bool:
        """Play a TTE animation inline and wait for completion."""
        done_event = threading.Event()
        started = self.play_tte(effect_name, text, params=params, done_event=done_event)
        if not started:
            return False
        done_event.wait(timeout_s)
        return True

    def stop_tte_main(self) -> None:
        from hermes_cli.tui.widgets import TTEWidget
        try:
            widget = self.app.query_one("#tte-effect", TTEWidget)
            widget.stop()
        except NoMatches:
            pass

    def stop_tte(self) -> None:
        """Stop any running inline TTE animation."""
        app = self.app
        if app._event_loop is not None and threading.current_thread() is not threading.main_thread():
            app.call_from_thread(self.stop_tte_main)
            return
        self.stop_tte_main()

    def get_working_directory(self) -> Path:
        """Return TUI workspace root used for path completion and file-drop links."""
        app = self.app
        candidate = getattr(app.cli, "terminal_cwd", None)
        if not isinstance(candidate, (str, bytes, Path)) or not str(candidate).strip():
            candidate = None
        candidate = candidate or _os_mod.environ.get("TERMINAL_CWD") or _os_mod.getcwd()
        try:
            return Path(candidate).expanduser().resolve()
        except Exception:
            return Path(_os_mod.getcwd()).resolve()
