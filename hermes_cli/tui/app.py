"""HermesApp — Textual App subclass for the Hermes TUI.

Replaces the prompt_toolkit Application with a reactive, CSS-themed Textual
app. Thread → App communication uses two mechanisms:

A. ``call_from_thread(fn, *args)`` for scalar reactive mutations.
B. Bounded ``asyncio.Queue`` for high-throughput streaming output.

Module-level ``_hermes_app`` reference is set in ``cli.py:run()`` and cleared
in its ``finally`` block — replaces all ``hasattr(self, "_app")`` guards.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import math
import platform
import queue
import re
import threading

# File-touching tool names — used by watch_spinner_label to extract active file
_FILE_TOOLS: frozenset[str] = frozenset({
    "read_file", "write_file", "edit_file", "create_file",
    "view", "str_replace_editor", "patch",
})

_SHELL_TOOLS: frozenset[str] = frozenset({
    "bash", "run_command", "execute_command", "shell", "run_bash",
})

_PATH_EXTRACT_RE = re.compile(
    r'["\']?(/[\w./\-]+|[\w./\-]+\.[\w]{1,6})["\']?'
)


def _looks_like_slash_command(text: str) -> bool:
    """Return True if text looks like a slash command, not a file path."""
    if not text or not text.startswith("/"):
        return False
    first_word = text.split()[0]
    return "/" not in first_word[1:]


import time as _time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import Static, TextArea
from textual import work

from hermes_cli.file_drop import classify_dropped_file, format_link_token
from hermes_cli.tui.state import (
    ChoiceOverlayState,
    OverlayState,
    SecretOverlayState,
    UndoOverlayState,
)
from hermes_cli.tui.widgets import (
    ApprovalWidget,
    ClarifyWidget,
    CopyableRichLog,
    FPSCounter,
    HistorySearchOverlay,
    HintBar,
    KeymapOverlay,
    ImageBar,
    LiveLineWidget,
    MessagePanel,
    OutputPanel,
    PlainRule,
    ReasoningPanel,
    SecretWidget,
    StartupBannerWidget,
    StatusBar,
    StreamingCodeBlock,
    SudoWidget,
    TTEWidget,
    ThinkingWidget,
    TitledRule,
    UndoConfirmOverlay,
    UserMessagePanel,
    VoiceStatusBar,
    _fps_hud_enabled,
    _safe_widget_call,
)

from hermes_cli.tui.constants import ICON_COPY
from hermes_cli.tui.animation import AnimationClock
from hermes_cli.tui.perf import EventLoopLatencyProbe, FrameRateProbe, WorkerWatcher
from hermes_cli.tui.theme_manager import ThemeManager
from wcwidth import wcswidth

try:
    import drawille as _drawille
except ImportError:
    _drawille = None

if TYPE_CHECKING:
    from hermes_cli.tui.input_widget import HermesInput
    from hermes_cli.tui.path_search import Candidate, PathCandidate
    from hermes_cli.tui.tool_blocks import ToolHeader

logger = logging.getLogger(__name__)

import os as _os_mod


def _animations_enabled_check() -> bool:
    """Return False if the user has opted out of animations via env vars."""
    for key in ("NO_ANIMATIONS", "REDUCE_MOTION"):
        val = _os_mod.environ.get(key, "").strip().lower()
        if val in ("1", "true", "yes"):
            return False
    return True


def _run_effect_sync(effect_name: str, text: str, params: dict[str, object] | None = None) -> bool:
    """Run a TTE animation synchronously.

    Must be called after the Textual TUI has been suspended (i.e. inside
    ``App.suspend()``).  Runs in a thread-pool executor so it does not
    block the event loop.
    """
    from hermes_cli.tui.tte_runner import run_effect
    print()
    rendered = run_effect(effect_name, text, params=params)
    print()
    return rendered


# Always use call_soon_threadsafe for cross-thread queue access.
# asyncio.Queue is not thread-safe: put_nowait from a non-event-loop thread
# won't wake the selector, so the consumer only discovers items on the next
# timer tick rather than immediately.
_CPYTHON_FAST_PATH = False

# CSS file path — relative to this module
_CSS_PATH = Path(__file__).parent / "hermes.tcss"
_HELIX_DELAY_S = 3.0
_HELIX_FRAME_COUNT = 24
_HELIX_MIN_CELLS = 6


class HermesApp(App):
    """Main Textual application for the Hermes Agent TUI.

    Holds all reactive state that drives widget updates. The agent thread
    (and other background threads) mutate these reactives via
    ``call_from_thread``, and Textual's watch system handles re-rendering.
    """

    CSS_PATH = "hermes.tcss"

    # Layer declaration — required before any widget uses ``layer: overlay``
    # in CSS.  Draw order: default → overlay.
    LAYERS = ("default", "overlay")

    BINDINGS = [
        Binding("ctrl+f", "open_history_search", "History search", show=False, priority=True),
        Binding("ctrl+g", "open_history_search", "History search", show=False, priority=True),
        Binding("f1", "show_help", "Keyboard shortcuts", show=False),
        Binding("f8", "toggle_fps_hud", "FPS HUD", show=False),
        Binding("alt+up", "prev_turn", "Previous turn", show=False),
        Binding("alt+down", "next_turn", "Next turn", show=False),
        Binding("ctrl+shift+a", "open_anim_config", "Animation config", show=False, priority=True),
    ]

    _CHEVRON_PHASE_CLASSES: frozenset[str] = frozenset({
        "--phase-file", "--phase-stream", "--phase-shell",
        "--phase-done", "--phase-error",
    })

    # --- Reactive state (replaces flag + _invalidate() pattern) ---
    agent_running: reactive[bool] = reactive(False)
    command_running: reactive[bool] = reactive(False)
    voice_mode: reactive[bool] = reactive(False)
    voice_recording: reactive[bool] = reactive(False)

    # Overlay states — typed dataclasses, not raw dicts
    clarify_state: reactive[ChoiceOverlayState | None] = reactive(None)
    approval_state: reactive[ChoiceOverlayState | None] = reactive(None)
    sudo_state: reactive[SecretOverlayState | None] = reactive(None)
    secret_state: reactive[SecretOverlayState | None] = reactive(None)
    undo_state: reactive[UndoOverlayState | None] = reactive(None)

    # Status bar data
    status_model: reactive[str] = reactive("")
    status_context_tokens: reactive[int] = reactive(0)
    status_context_max: reactive[int] = reactive(0)

    # Compaction state
    status_compaction_progress: reactive[float] = reactive(0.0)  # 0.0–1.0
    status_compaction_enabled: reactive[bool] = reactive(True)

    # Tok/s throughput (last turn)
    status_tok_s: reactive[float] = reactive(0.0)

    # Browse mode — keyboard-driven navigation through ToolBlock widgets
    browse_mode: reactive[bool] = reactive(False)
    browse_index: reactive[int] = reactive(0)
    # Memoized count of mounted ToolHeaders — avoids O(n) DOM query in StatusBar.render()
    _browse_total: reactive[int] = reactive(0)

    # Output dropped flag — set when queue is full; shown in StatusBar until next successful write
    status_output_dropped: reactive[bool] = reactive(False)

    # Image attachments — reactive(list) uses factory form to avoid shared mutable default
    attached_images: reactive[list] = reactive(list)

    # Spinner label — text shown beside the spinner frame (e.g. "Calling tool…")
    spinner_label: reactive[str] = reactive("")

    # Active file path extracted from spinner_label when a file-touching tool runs.
    # Drives the 📄 breadcrumb in StatusBar. Empty string when no file is active.
    status_active_file: reactive[str] = reactive("")

    # Persistent error message shown in StatusBar until cleared.
    # repaint=False: StatusBar registers its own watch() in on_mount.
    status_error: reactive[str] = reactive("", repaint=False)

    # Highlighted completion candidate — drives PreviewPanel via watch_highlighted_candidate.
    # Uses reactive(None) (no type param) to avoid import cycle at class-definition time.
    highlighted_candidate: reactive = reactive(None)

    # FPS HUD visibility — toggled via Ctrl+\ or display.fps_hud config
    fps_hud_visible: reactive[bool] = reactive(False)

    # hint_text is NOT on HermesApp — HintBar.hint is the single source of truth.

    def __init__(
        self,
        cli: Any,
        startup_fn=None,
        clipboard_available: bool = True,
        xclip_cmd: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.cli = cli
        self._startup_fn = startup_fn
        self._clipboard_available: bool = clipboard_available
        self._xclip_cmd: list[str] | None = xclip_cmd

        # Bounded queue: prevents unbounded memory growth when agent produces
        # faster than UI renders. 4096 chunks ≈ ~1MB of text at ~256 bytes/chunk.
        self._output_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=4096)
        self._spinner_idx = 0
        self._shimmer_tick = 0  # monotonic; never wraps — decoupled from spinner frame count
        self._event_loop: asyncio.AbstractEventLoop | None = None

        # ThemeManager handles skin loading, component vars, and hot reload.
        # Must be constructed after super().__init__() so App internals exist.
        self._theme_manager = ThemeManager(self)
        # Diagnostic probes — initialised in on_mount once the event loop runs.
        self._worker_watcher: WorkerWatcher | None = None
        self._event_loop_probe: EventLoopLatencyProbe | None = None
        self._frame_probe: FrameRateProbe | None = None
        self._fps_hud_update_every: int = 1  # refined in on_mount once MAX_FPS is known

        # Spinner frames — read from module-level _COMMAND_SPINNER_FRAMES in cli.py
        self._spinner_frames: tuple[str, ...] = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
        self._helix_frame_cache: dict[int, tuple[str, ...]] = {}

        # Elapsed time for the current tool call — reset whenever spinner_label changes
        self._tool_start_time: float = 0.0

        # Whether to use HermesInput (step 5) or interim TextArea
        self._use_hermes_input = True

        # Browse-mode visit counter — first 3 visits show full hint, then compact
        self._browse_uses: int = 0

        # Active StreamingToolBlocks keyed by tool_call_id
        self._active_streaming_blocks: dict[str, Any] = {}
        self._response_metrics_active: bool = False
        self._response_wall_start_time: float | None = None
        self._response_segment_start_time: float | None = None
        self._response_token_window: collections.deque[tuple[float, int]] = collections.deque()

        # Undo/retry state
        self._undo_in_progress: bool = False
        self._last_user_input: str = ""
        # Panel/args to act on when undo/rollback overlay is confirmed
        self._pending_undo_panel: "MessagePanel | None" = None
        self._pending_rollback_n: int = 0
        # Animation feature flag — checked by all shimmer/pulse paths
        self._animations_enabled: bool = _animations_enabled_check()
        # Current hint phase — tracks what the user is doing
        self._hint_phase: str = "idle"
        # Timestamp until which _flash_hint has the hint bar reserved.
        # _tick_spinner must not overwrite before this expires.
        self._flash_hint_expires: float = 0.0
        # Compaction warning state — reset when progress returns to 0
        self._compaction_warned: bool = False

    # --- Compose ---

    def compose(self) -> ComposeResult:
        yield OutputPanel(id="output-panel")
        # TTEWidget uses layer: overlay + dock: top in its DEFAULT_CSS so it
        # floats over the banner area when active.  Banner content is already
        # in OutputPanel underneath; when effect ends the overlay hides and
        # the static caduceus is visible in-place.
        yield TTEWidget(id="tte-effect")
        with Vertical(id="overlay-layer"):
            yield ClarifyWidget(id="clarify")
            yield ApprovalWidget(id="approval")
            yield SudoWidget(id="sudo")
            yield SecretWidget(id="secret")
            yield UndoConfirmOverlay(id="undo-confirm")
        yield HintBar(id="hint-bar")
        yield ImageBar(id="image-bar")
        yield TitledRule(id="input-rule", show_state=True)

        if self._use_hermes_input:
            from hermes_cli.tui.input_widget import HermesInput as _HI
            from hermes_cli.tui.completion_overlay import CompletionOverlay as _CO
            from hermes_cli.tui.path_search import PathSearchProvider as _PSP
            # CompletionOverlay must be composed BEFORE HermesInput so it sits
            # directly above the input in the natural layout flow (no dock/offset).
            yield _CO(id="completion-overlay")
            yield HistorySearchOverlay(id="history-search")
            yield KeymapOverlay(id="keymap-help")
            with Horizontal(id="input-row"):
                yield Static("❯ ", id="input-chevron")
                yield _HI(id="input-area")
                yield Static("", id="spinner-overlay")
            # PathSearchProvider is invisible — position is irrelevant.
            yield _PSP(id="path-search-provider")
        else:
            yield TextArea(id="input-area")

        yield PlainRule(id="input-rule-bottom")
        yield VoiceStatusBar(id="voice-status")
        yield StatusBar(id="status-bar")
        # Drawille animation overlay — before FPSCounter so FPS HUD stays above.
        from hermes_cli.tui.drawille_overlay import DrawilleOverlay as _DO, AnimConfigPanel as _ACP
        yield _DO(id="drawille-overlay")
        yield _ACP(id="anim-config-panel")
        # FPS HUD — overlay layer, docked top; display:none by default.
        # Must be before ContextMenu so ContextMenu stays topmost in overlay layer.
        yield FPSCounter(id="fps-counter")
        # ContextMenu must be last so it renders above all other widgets
        # within the overlay layer (DOM order = paint order within a layer).
        from hermes_cli.tui.context_menu import ContextMenu as _CM
        yield _CM(id="context-menu")

    # --- Lifecycle ---

    def on_mount(self) -> None:
        self._event_loop = asyncio.get_running_loop()
        self._worker_watcher = WorkerWatcher(self)
        self._event_loop_probe = EventLoopLatencyProbe()
        self._theme_manager.start_hot_reload()
        from textual import constants as _tc
        _frame_interval = 1.0 / _tc.MAX_FPS  # matches Screen._update_timer cadence
        # window=MAX_FPS → 1 s of rolling history; log every MAX_FPS ticks → 1 log/s
        self._frame_probe = FrameRateProbe(window=_tc.MAX_FPS, log_every=_tc.MAX_FPS)
        self._fps_hud_update_every = max(1, _tc.MAX_FPS // 4)  # update display at ~4 Hz
        self._consume_output()  # starts the @work consumer
        self._anim_clock = AnimationClock()
        self._anim_clock_h = self.set_interval(1 / 15, self._anim_clock.tick)
        self._spinner_h = self.set_interval(0.1, self._tick_spinner)
        self._fps_h = self.set_interval(_frame_interval, self._tick_fps)
        self._duration_h = self.set_interval(1.0, self._tick_duration)
        # Restore FPS HUD state from config (runtime toggle overrides this)
        if _fps_hud_enabled():
            self.fps_hud_visible = True
        # Focus the input bar so the user can type immediately
        try:
            self.query_one("#input-area").focus()
        except NoMatches:
            pass
        if not self._clipboard_available and not self._xclip_cmd:
            try:
                self.query_one("#status-clipboard-warning").add_class("--active")
            except NoMatches:
                pass
        if self._startup_fn is not None:
            threading.Thread(target=self._startup_fn, daemon=True).start()
        import os as _os
        if _os.environ.get("HERMES_DENSITY", "").lower() == "compact":
            self.add_class("density-compact")
        if _os.environ.get("HERMES_REDUCED_MOTION", "").lower() in ("1", "true", "yes"):
            self.add_class("reduced-motion")
        # Wire slash commands from COMMAND_REGISTRY into the autocomplete engine
        if self._use_hermes_input:
            self._populate_slash_commands()
        # Initialize hint bar to idle phase — shows key-badge hints immediately
        self._set_hint_phase("idle")

    def on_unmount(self) -> None:
        """Stop background helpers tied to app lifetime."""
        self._theme_manager.stop_hot_reload()
        for _h in (self._anim_clock_h, self._spinner_h, self._fps_h, self._duration_h):
            _h.stop()

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
        _first_chunk_in_turn: bool = True
        while True:
            chunk = await self._output_queue.get()
            if chunk is None:
                # Sentinel: flush live line; reset first-chunk flag for next turn
                _first_chunk_in_turn = True
                try:
                    panel = self.query_one(OutputPanel)
                    panel.flush_live()
                    # flush_live() may commit a pending buffered line (setext lookahead),
                    # extending the virtual height AFTER the last chunk's scroll_end fired.
                    # Queue one more scroll_end so the final line is always visible.
                    if not panel._user_scrolled_up:
                        self.call_after_refresh(panel.scroll_end, animate=False)
                except NoMatches:
                    pass
                continue
            # Deactivate shimmer on first content chunk of each turn
            if _first_chunk_in_turn:
                _first_chunk_in_turn = False
                try:
                    self.query_one(ThinkingWidget).deactivate()
                except NoMatches:
                    pass
            try:
                panel = self.query_one(OutputPanel)
                panel.live_line.feed(chunk)
                panel.refresh(layout=True)
                if not panel._user_scrolled_up:
                    self.call_after_refresh(panel.scroll_end, animate=False)
            except NoMatches:
                pass
            await asyncio.sleep(0)

    # --- Thread-safe output writing ---

    def write_output(self, text: str) -> None:
        """Thread-safe: enqueue text for the output consumer.

        Uses ``call_soon_threadsafe`` to ensure the event loop wakes
        immediately when a chunk is enqueued from the agent thread.
        """
        if self._event_loop is None:
            return
        try:
            if _CPYTHON_FAST_PATH:
                self._output_queue.put_nowait(text)
            else:
                self._event_loop.call_soon_threadsafe(
                    self._output_queue.put_nowait, text
                )
            # Clear the dropped flag on a successful enqueue
            if self.status_output_dropped:
                self.status_output_dropped = False
        except asyncio.QueueFull:
            # Backpressure: UI is 4096 chunks behind — drop rather than OOM.
            # Signal the user via StatusBar so they know output was truncated.
            logger.warning("Output queue full — dropped chunk (backpressure)")
            self.status_output_dropped = True
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
        with self.suspend():
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
        if self._event_loop is None:
            return False
        future = asyncio.run_coroutine_threadsafe(
            self._play_effects_async(effect_name, text, params),
            self._event_loop,
        )
        try:
            return bool(future.result())
        except Exception:
            return False

    def get_working_directory(self) -> Path:
        """Return TUI workspace root used for path completion and file-drop links."""
        candidate = getattr(self.cli, "terminal_cwd", None)
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
        try:
            widget = self.query_one("#tte-effect", TTEWidget)
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
        if self._event_loop is not None and threading.current_thread() is not threading.main_thread():
            self.call_from_thread(self._play_tte_main, effect_name, text, params, done_event)
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
        try:
            widget = self.query_one("#tte-effect", TTEWidget)
            widget.stop()
        except NoMatches:
            pass

    def stop_tte(self) -> None:
        """Stop any running inline TTE animation."""
        if self._event_loop is not None and threading.current_thread() is not threading.main_thread():
            self.call_from_thread(self._stop_tte_main)
            return
        self._stop_tte_main()

    def flush_output(self) -> None:
        """Thread-safe: send flush sentinel to commit any trailing partial line."""
        if self._event_loop is None:
            return
        try:
            if _CPYTHON_FAST_PATH:
                self._output_queue.put_nowait(None)
            else:
                self._event_loop.call_soon_threadsafe(
                    self._output_queue.put_nowait, None
                )
        except (asyncio.QueueFull, RuntimeError):
            pass

    # --- Spinner + hint bar ---

    def _tick_spinner(self) -> None:
        """set_interval callback — runs ON the event loop (def, not async def).

        Reads overlay deadlines and agent state to assemble hint text.
        Updates the input widget's spinner_text so the spinner renders
        inside the input field when the agent is running.
        """
        if not (self.agent_running or self.command_running):
            return
        self._shimmer_tick += 1

        hint_suffix = self._build_hint_text()

        # Append per-tool elapsed time when a tool call is in progress
        elapsed = 0.0
        if self._tool_start_time > 0:
            elapsed = max(0.0, _time.monotonic() - self._tool_start_time)
            hint_suffix = f"{hint_suffix} · {elapsed:.1f}s" if hint_suffix else f"{elapsed:.1f}s"

        # Deliver spinner text to input bar (placeholder + spinner_text).
        # HintBar shows phase-based hints (e.g. "^C interrupt · Esc dismiss")
        # — spinner/elapsed are already visible in the input bar, no duplication.
        try:
            inp = self.query_one("#input-area")
            overlay = self.query_one("#spinner-overlay", Static)
            overlay.display = False  # always hidden; placeholder replaces overlay
            frame = self._next_spinner_frame(
                text_after_frame=hint_suffix,
                elapsed=elapsed,
                input_width=self._input_bar_width(inp),
            )
            spinner_display = f"{frame} {hint_suffix}" if frame and hint_suffix else (frame or hint_suffix)
            # Leading space so cursor doesn't obscure first char when input is focused
            padded = f" {spinner_display}" if spinner_display else ""
            if hasattr(inp, "placeholder"):
                if padded and getattr(self, "_animations_enabled", True):
                    try:
                        from hermes_cli.tui.animation import shimmer_text
                        from textual.content import Content
                        shimmer = shimmer_text(
                            padded,
                            tick=self._shimmer_tick,
                            dim="#555555",
                            peak="#d8d8d8",
                            period=60,
                        )
                        inp.placeholder = Content.from_rich_text(shimmer)
                    except Exception:
                        inp.placeholder = padded
                else:
                    inp.placeholder = padded
        except NoMatches:
            pass

        self._refresh_live_response_metrics()

    @staticmethod
    def _cell_width(text: str) -> int:
        """Return visible cell width for terminal layout math."""
        width = wcswidth(text)
        return max(0, width)

    def _input_bar_width(self, inp: Any) -> int:
        """Best-effort live width of the input widget in terminal cells."""
        region_width = getattr(getattr(inp, "content_size", None), "width", 0) or 0
        widget_width = getattr(getattr(inp, "size", None), "width", 0) or 0
        app_width = max(0, getattr(getattr(self, "size", None), "width", 0) - 4)
        return max(region_width, widget_width, app_width)

    def _next_spinner_frame(self, text_after_frame: str, elapsed: float, input_width: int) -> str:
        """Return the next spinner frame. Drawille helix moved to ThinkingWidget."""
        frames = self._spinner_frames
        if frames:
            self._spinner_idx = (self._spinner_idx + 1) % len(frames)
            return frames[self._spinner_idx]
        return ""

    def _helix_width(self, text_after_frame: str, input_width: int) -> int:
        """Compute how many cells remain for the animated helix."""
        suffix_width = self._cell_width(text_after_frame)
        spacer = 1 if text_after_frame else 0
        # Reserve the leading padding cell added before placeholder text.
        available = max(0, input_width - suffix_width - spacer - 1)
        return available

    def _helix_spinner_frame(self, elapsed: float, text_after_frame: str, input_width: int) -> str | None:
        """Return a cached drawille helix frame when the timer has run long enough."""
        if _drawille is None or elapsed < _HELIX_DELAY_S:
            return None
        width_cells = self._helix_width(text_after_frame, input_width)
        if width_cells < _HELIX_MIN_CELLS:
            return None
        frames = self._helix_frame_cache.get(width_cells)
        if frames is None:
            frames = self._build_helix_frames(width_cells)
            self._helix_frame_cache[width_cells] = frames
        if not frames:
            return None
        return frames[self._spinner_idx % len(frames)]

    def _build_helix_frames(self, width_cells: int) -> tuple[str, ...]:
        """Precompute one-line drawille frames for a 3-strand helix."""
        if _drawille is None or width_cells < _HELIX_MIN_CELLS:
            return ()

        width_points = max(2, width_cells * 2)
        amplitude = 1.35
        midpoint = 1.5
        frames: list[str] = []

        for frame_idx in range(_HELIX_FRAME_COUNT):
            canvas = _drawille.Canvas()
            phase = (frame_idx / _HELIX_FRAME_COUNT) * (2 * math.pi)
            for strand_idx in range(3):
                strand_phase = phase + (strand_idx * 2 * math.pi / 3)
                for x in range(width_points):
                    theta = strand_phase + (x * 0.42)
                    y = midpoint + (math.sin(theta) * amplitude)
                    canvas.set(x, int(round(max(0.0, min(3.0, y)))))
            rendered = canvas.frame()
            frame = rendered.splitlines()[0] if rendered else ""
            frames.append(frame.ljust(width_cells)[:width_cells])

        return tuple(frames)

    def _build_hint_text(self) -> str:
        """Build the hint suffix shown beside the spinner.

        Reads overlay deadlines and agent state to assemble context hints
        (e.g. " — waiting for approval (12s)"). Extracts the logic from
        the get_hint_text() closure (cli.py:8258).
        """
        parts: list[str] = []
        label_text = getattr(self, "spinner_label", "")
        if label_text:
            # Strip verbose prefixes — the tool name is the signal, not the verb
            for prefix in ("Calling tool: ", "Running tool: ", "Tool: "):
                if label_text.startswith(prefix):
                    label_text = label_text[len(prefix):]
                    break
            parts.append(label_text)
        for label, state_attr in [
            ("approval", "approval_state"),
            ("clarify", "clarify_state"),
            ("sudo", "sudo_state"),
            ("secret", "secret_state"),
        ]:
            state = getattr(self, state_attr)
            if state is not None:
                parts.append(f" — waiting for {label} ({state.remaining}s)")
        return " ".join(parts) if parts else ""

    # --- Session / response timers ---

    def _tick_duration(self) -> None:
        """Run 1-Hz diagnostics and refresh live response metrics."""
        # --- Diagnostic probes (run unconditionally at 1 Hz) ---
        if self._event_loop_probe is not None:
            self._event_loop_probe.tick()
        if self._worker_watcher is not None:
            self._worker_watcher.tick()
        self._refresh_live_response_metrics()

    # --- FPS HUD ticker ---

    def _tick_fps(self) -> None:
        """Frame-rate probe ticker — runs at 1/MAX_FPS (matches Screen._update_timer).

        Probes at the render cadence so the HUD reflects actual event-loop frame
        delivery rate rather than an arbitrary coarse interval.  DOM is only
        touched every ~4 Hz (fps_hud_update_every ticks) to keep the HUD readable
        and avoid adding repaint pressure from the HUD itself.
        """
        if self._frame_probe is None:
            return
        fps, avg_ms = self._frame_probe.tick()
        if self.fps_hud_visible:
            every = getattr(self, "_fps_hud_update_every", 1)
            if self._frame_probe._ticks % every == 0:
                try:
                    counter = self.query_one(FPSCounter)
                    counter.fps = fps
                    counter.avg_ms = avg_ms
                except NoMatches:
                    pass

    def watch_fps_hud_visible(self, value: bool) -> None:
        """Show or hide the FPS HUD overlay."""
        try:
            counter = self.query_one(FPSCounter)
            if value:
                counter.add_class("--visible")
            else:
                counter.remove_class("--visible")
        except NoMatches:
            pass

    def action_toggle_fps_hud(self) -> None:
        """Toggle the FPS / avg-ms HUD (Ctrl+\\)."""
        self.fps_hud_visible = not self.fps_hud_visible

    # --- User message echo ---

    def echo_user_message(self, text: str, images: int = 0) -> None:
        """Mount a UserMessagePanel showing the user's submitted message.

        Called from the agent thread via ``call_from_thread`` before
        ``agent_running`` is set to True (which creates the new MessagePanel).
        """
        try:
            panel = self.query_one(OutputPanel)
            panel.mount(UserMessagePanel(text, images=images), before=panel.query_one(ThinkingWidget))
            # Always scroll to show the user's own message regardless of scroll
            # position — the user just submitted, they expect to see the exchange.
            # Re-engage auto-scroll for the upcoming assistant response.
            panel._user_scrolled_up = False
            self.call_after_refresh(panel.scroll_end, animate=False)
        except NoMatches:
            pass

    # --- Reactive watchers ---

    def _compute_hint_phase(self) -> str:
        """Compute hint phase from current app state, in priority order."""
        if getattr(self, "voice_mode", False):
            return "voice"
        # Any overlay open?
        if any(
            getattr(self, attr) is not None
            for attr in ("approval_state", "clarify_state", "sudo_state", "secret_state")
        ):
            return "overlay"
        if getattr(self, "browse_mode", False):
            return "browse"
        if getattr(self, "agent_running", False) or getattr(self, "command_running", False):
            return "stream"
        if bool(getattr(self, "status_error", "")):
            return "error"
        # Typing phase: check if input has content
        try:
            inp = self.query_one("#input-area")
            if hasattr(inp, "value") and inp.value:
                return "typing"
        except NoMatches:
            pass
        return "idle"

    def _set_hint_phase(self, phase: str) -> None:
        """Apply hint phase to HintBar safely."""
        self._hint_phase = phase
        try:
            self.query_one(HintBar).set_phase(phase)
        except NoMatches:
            pass

    def _set_chevron_phase(self, phase: str) -> None:
        """Set exactly one phase class on #input-chevron, clearing all others."""
        try:
            chevron = self.query_one("#input-chevron", Static)
            for cls in self._CHEVRON_PHASE_CLASSES:
                chevron.remove_class(cls)
            if phase:
                chevron.add_class(phase)
        except NoMatches:
            pass

    def _drawille_show_hide(self, running: bool) -> None:
        """Show or hide the drawille overlay based on agent state."""
        try:
            from hermes_cli.tui.drawille_overlay import DrawilleOverlay as _DO, _overlay_config
            overlay = self.query_one(_DO)
            cfg = _overlay_config()
            if running and cfg.trigger in ("agent_running", "always"):
                overlay.show(cfg)
                if cfg.dim_background:
                    try:
                        self.query_one(OutputPanel).add_class("-dim-bg")
                    except NoMatches:
                        pass
            else:
                overlay.hide(cfg)
                try:
                    self.query_one(OutputPanel).remove_class("-dim-bg")
                except NoMatches:
                    pass
        except NoMatches:
            pass
        except Exception:
            pass

    def watch_agent_running(self, value: bool) -> None:
        self._drawille_show_hide(value)
        if value:
            self._response_metrics_active = False
            self._response_wall_start_time = None
            self._response_segment_start_time = None
            self._response_token_window.clear()
            self._set_chevron_phase("--phase-stream")
            self._set_hint_phase("stream")
        else:
            try:
                chevron = self.query_one("#input-chevron", Static)
                if not chevron.has_class("--phase-error"):
                    self._set_chevron_phase("--phase-done")
                    self.set_timer(0.4, lambda: self._set_chevron_phase(""))
            except NoMatches:
                pass
            # Safety net: flush live buffer + stop all per-turn timers.
            # flush_output() is never called from cli.py so the None sentinel
            # that drives flush_live() via _consume_output never arrives.
            # flush_live() handles: (1) ThinkingWidget.deactivate(),
            # (2) LiveLineWidget.flush() → stops blink timer + resets
            #     _blink_visible, (3) commits any partial _buf to MessagePanel.
            try:
                output = self.query_one(OutputPanel)
                output.flush_live()
                # Evict old turns at idle to prevent compositor cache thrash
                # (Textual LRU maxsize=16 can't cope with 300+ children).
                output.evict_old_turns()
            except NoMatches:
                pass
            # Clear stale spinner/file breadcrumb — cli.py resets _spinner_text
            # locally but never pushes spinner_label="" to the app, so the last
            # tool label persists into turn 2 and StatusBar shows a stale file path.
            self.spinner_label = ""
            self.status_active_file = ""
            self._response_metrics_active = False
            self._response_wall_start_time = None
            self._response_segment_start_time = None
            self._response_token_window.clear()
            # Clear any blocks left open from an interrupted turn (agent stopped
            # without calling close_streaming_tool_block).  Leaked refs prevent GC
            # of the widget objects and cause stale entries on the next turn.
            self._active_streaming_blocks.clear()
            # Clear any gen blocks left open from interrupted turns
            pending = getattr(self.cli, "_pending_gen_queue", None)
            if pending:
                for block in pending:
                    try:
                        block.remove()
                    except Exception:
                        pass
                pending.clear()

        # --- undo safety guard ---
        if value and self.undo_state is not None:
            # Agent started while undo overlay was open — auto-cancel for safety
            self.undo_state = None
            self._pending_undo_panel = None
            self._flash_hint("⚠  Agent started, undo cancelled", 2.0)

        try:
            widget = self.query_one("#input-area")
            # Input stays enabled when agent is running — user can submit
            # to interrupt + send new message.  Only overlays disable input.
            if not value:
                if hasattr(widget, "spinner_text"):
                    widget.spinner_text = ""
                # Restore input visibility (safety guard) and clear spinner placeholder
                widget.display = True
                if hasattr(widget, "placeholder"):
                    widget.placeholder = ""
                try:
                    self.query_one("#spinner-overlay", Static).display = False
                except NoMatches:
                    pass
                # Clear the HintBar spinner when the agent stops
                try:
                    self.query_one(HintBar).hint = ""
                except NoMatches:
                    pass
                # GAP-17: restore focus so the user can type immediately without clicking
                self.call_after_refresh(widget.focus)
        except NoMatches:
            pass
        # New turn starting — create a new MessagePanel with the last user input
        if value:
            try:
                self.query_one(OutputPanel).new_message(
                    user_text=self._last_user_input
                )
            except NoMatches:
                pass
        # Recompute hint phase when agent stops
        if not value:
            self._set_hint_phase(self._compute_hint_phase())

    def _refresh_live_response_metrics(self) -> None:
        """Refresh current message header while a streamed response is active."""
        if not self._response_metrics_active:
            return
        try:
            output = self.query_one(OutputPanel)
        except NoMatches:
            return
        msg = output.current_message
        if msg is None:
            return
        wall_start = self._response_wall_start_time
        if wall_start is None:
            return
        now = _time.monotonic()
        elapsed = max(0.0, now - wall_start)
        window_s = 0.75
        while self._response_token_window and now - self._response_token_window[0][0] > window_s:
            self._response_token_window.popleft()
        live_tok_s = 0.0
        if self._response_token_window:
            token_sum = sum(tokens for _, tokens in self._response_token_window)
            span = max(now - self._response_token_window[0][0], 0.05)
            live_tok_s = token_sum / span
        msg.set_response_metrics(tok_s=live_tok_s, elapsed_s=elapsed, streaming=True)

    def mark_response_stream_started(self) -> None:
        """Start live response timing for current assistant turn."""
        if not self._response_metrics_active:
            self._response_metrics_active = True
            self._response_wall_start_time = _time.monotonic()
            self._response_token_window.clear()
        if self._response_segment_start_time is None:
            self._response_segment_start_time = _time.monotonic()
        self._refresh_live_response_metrics()

    def mark_response_stream_delta(self, text: str) -> None:
        """Record streamed response text for rolling live tok/s."""
        if self._response_segment_start_time is None or not text:
            return
        from agent.model_metadata import estimate_tokens_rough
        est_tokens = estimate_tokens_rough(text)
        if est_tokens <= 0:
            return
        self._response_token_window.append((_time.monotonic(), est_tokens))
        self._refresh_live_response_metrics()

    def pause_response_stream(self) -> None:
        """Pause live message timing while agent waits on tool execution."""
        self._response_segment_start_time = None
        self._response_token_window.clear()

    def finalize_response_metrics(self, tok_s: float, elapsed_s: float) -> None:
        """Freeze tok/s + elapsed on current assistant message header."""
        self.pause_response_stream()
        self._response_metrics_active = False
        self._response_wall_start_time = None
        self._response_token_window.clear()
        try:
            output = self.query_one(OutputPanel)
        except NoMatches:
            return
        msg = output.current_message
        if msg is None:
            return
        msg.set_response_metrics(tok_s=tok_s, elapsed_s=elapsed_s, streaming=False)

    def watch_spinner_label(self, value: str) -> None:
        """Reset per-tool elapsed timer and extract active file path."""
        self._tool_start_time = _time.monotonic() if value else 0.0
        if value and isinstance(value, str):
            # Labels are already prefix-stripped by _build_hint_text.
            # Split on "(" (args form) and " · " (elapsed-time form) to isolate tool name.
            tool_name = value.split("(")[0].split(" · ")[0].strip()
            if tool_name in _FILE_TOOLS:
                m = _PATH_EXTRACT_RE.search(value)
                self.status_active_file = m.group(1) if m else ""
                self._set_chevron_phase("--phase-file")
                self._set_hint_phase("file")
            elif tool_name in _SHELL_TOOLS:
                self.status_active_file = ""
                self._set_chevron_phase("--phase-shell")
                self._set_hint_phase("stream")
            else:
                self.status_active_file = ""
                self._set_chevron_phase("--phase-stream")
                self._set_hint_phase("stream")
        else:
            self.status_active_file = ""
            if self.agent_running:
                self._set_chevron_phase("--phase-stream")

    @property
    def choice_overlay_active(self) -> bool:
        """True when an interactive choice overlay (clarify/approval) is up.

        Used by HermesInput._update_autocomplete to suppress completion while
        the user is answering an approval prompt.
        """
        return self.clarify_state is not None or self.approval_state is not None

    def _hide_completion_overlay_if_present(self) -> None:
        """Hide the completion overlay when a choice overlay activates."""
        try:
            from hermes_cli.tui.completion_overlay import CompletionOverlay as _CO
            self.query_one(_CO).remove_class("--visible")
        except NoMatches:
            pass

    def action_open_history_search(self) -> None:
        """Open (or close) the history search overlay."""
        from hermes_cli.tui.completion_overlay import CompletionOverlay as _CO
        try:
            if self.query_one(_CO).has_class("--visible"):
                return
        except NoMatches:
            pass
        try:
            hs = self.query_one(HistorySearchOverlay)
            if hs.has_class("--visible"):
                hs.action_dismiss()
            else:
                hs.open_search()
        except NoMatches:
            pass

    def action_show_help(self) -> None:
        """Toggle the keyboard-shortcut reference overlay."""
        try:
            overlay = self.query_one(KeymapOverlay)
            if overlay.has_class("--visible"):
                overlay.remove_class("--visible")
            else:
                overlay.add_class("--visible")
        except NoMatches:
            pass

    def action_prev_turn(self) -> None:
        """Scroll to the previous assistant MessagePanel."""
        try:
            output = self.query_one(OutputPanel)
            panels = list(self.query(MessagePanel))
            if not panels:
                return
            scroll_y = output.scroll_y
            # Walk in reverse — find first panel whose virtual top is above current scroll
            for panel in reversed(panels):
                panel_top = panel.virtual_region.y
                if panel_top < scroll_y - 1:
                    panel.scroll_visible(animate=True)
                    return
            panels[0].scroll_visible(animate=True)
        except NoMatches:
            pass

    def action_next_turn(self) -> None:
        """Scroll to the next assistant MessagePanel."""
        try:
            output = self.query_one(OutputPanel)
            panels = list(self.query(MessagePanel))
            if not panels:
                return
            scroll_y = output.scroll_y
            for panel in panels:
                panel_top = panel.virtual_region.y
                if panel_top > scroll_y + 1:
                    panel.scroll_visible(animate=True)
                    return
        except NoMatches:
            pass

    def action_toggle_density(self) -> None:
        """Toggle compact / normal density mode."""
        if self.has_class("density-compact"):
            self.remove_class("density-compact")
            self._flash_hint("Density: normal", 1.0)
        else:
            self.add_class("density-compact")
            self._flash_hint("Density: compact", 1.0)

    def _dismiss_floating_panels(self) -> None:
        """Dismiss HistorySearchOverlay and KeymapOverlay (P0-B stacking).

        Called whenever an agent-triggered overlay becomes active so that the
        reference/navigation panels do not compete for screen space.
        """
        try:
            hs = self.query_one(HistorySearchOverlay)
            if hs.has_class("--visible"):
                hs.action_dismiss()
        except NoMatches:
            pass
        try:
            ko = self.query_one(KeymapOverlay)
            if ko.has_class("--visible"):
                ko.remove_class("--visible")
        except NoMatches:
            pass

    def watch_clarify_state(self, value: ChoiceOverlayState | None) -> None:
        try:
            w = self.query_one(ClarifyWidget)
            w.display = value is not None
            if value is not None:
                w.update(value)
                self._hide_completion_overlay_if_present()
                self._dismiss_floating_panels()
                self.call_after_refresh(w.focus)
            else:
                if not self.agent_running and not self.command_running:
                    try:
                        self.call_after_refresh(self.query_one("#input-area").focus)
                    except NoMatches:
                        pass
        except NoMatches:
            pass
        self._set_hint_phase(self._compute_hint_phase())

    def watch_approval_state(self, value: ChoiceOverlayState | None) -> None:
        try:
            w = self.query_one(ApprovalWidget)
            w.display = value is not None
            if value is not None:
                w.update(value)
                self._hide_completion_overlay_if_present()
                self._dismiss_floating_panels()
                self.call_after_refresh(w.focus)
            else:
                if not self.agent_running and not self.command_running:
                    try:
                        self.call_after_refresh(self.query_one("#input-area").focus)
                    except NoMatches:
                        pass
        except NoMatches:
            pass
        self._set_hint_phase(self._compute_hint_phase())

    def watch_highlighted_candidate(self, c: Any) -> None:
        """Route highlighted candidate to PreviewPanel (PathCandidate only)."""
        try:
            from hermes_cli.tui.preview_panel import PreviewPanel as _PP
            from hermes_cli.tui.path_search import PathCandidate as _PC
            panel = self.query_one(_PP)
            panel.candidate = c if isinstance(c, _PC) else None
        except NoMatches:
            pass

    def watch_sudo_state(self, value: SecretOverlayState | None) -> None:
        try:
            w = self.query_one(SudoWidget)
            w.display = value is not None
            if value is not None:
                w.update(value)
                self._dismiss_floating_panels()
        except NoMatches:
            pass
        self._set_hint_phase(self._compute_hint_phase())

    def watch_secret_state(self, value: SecretOverlayState | None) -> None:
        try:
            w = self.query_one(SecretWidget)
            w.display = value is not None
            if value is not None:
                w.update(value)
                self._dismiss_floating_panels()
        except NoMatches:
            pass
        self._set_hint_phase(self._compute_hint_phase())

    def watch_status_error(self, value: str) -> None:
        """Update TitledRule error state and hint phase when error changes."""
        try:
            self.query_one("#input-rule", TitledRule).set_error(bool(value))
        except NoMatches:
            pass
        self._set_hint_phase(self._compute_hint_phase())

    def watch_undo_state(self, value: UndoOverlayState | None) -> None:
        try:
            w = self.query_one(UndoConfirmOverlay)
            w.display = value is not None
            if value is not None:
                w.update(value)
                self._dismiss_floating_panels()
                # P0-B: pause any active agent overlay countdown while undo confirm is open
                for widget_type in (ApprovalWidget, ClarifyWidget, SudoWidget, SecretWidget):
                    try:
                        aw = self.query_one(widget_type)
                        if aw.display:
                            aw.pause_countdown()
                    except NoMatches:
                        pass
            else:
                # P0-B: resume paused agent overlay countdowns when undo confirm dismisses
                for widget_type in (ApprovalWidget, ClarifyWidget, SudoWidget, SecretWidget):
                    try:
                        aw = self.query_one(widget_type)
                        if aw.display and getattr(aw, "_was_paused", False):
                            aw.resume_countdown()
                    except NoMatches:
                        pass
        except NoMatches:
            pass
        # Disable input while overlay is open so printable keys (y/n) bubble
        # up to the app-level on_key handler instead of being typed into the field.
        try:
            inp = self.query_one("#input-area")
            if value is not None:
                inp.disabled = True
            elif not self.agent_running and not self.command_running:
                inp.disabled = False
        except NoMatches:
            pass
        # Clear pending panel ref when overlay is dismissed (including auto-cancel)
        if value is None:
            self._pending_undo_panel = None

    def on_text_area_changed(self, event: Any) -> None:
        """Update hint phase when HermesInput (TextArea-based) content changes."""
        if getattr(event, "text_area", None) is not None:
            inp = event.text_area
            if getattr(inp, "id", None) == "input-area":
                if (
                    not getattr(self, "agent_running", False)
                    and not getattr(self, "command_running", False)
                    and not getattr(self, "browse_mode", False)
                    and not bool(getattr(self, "status_error", ""))
                    and not any(
                        getattr(self, attr) is not None
                        for attr in ("approval_state", "clarify_state", "sudo_state", "secret_state")
                    )
                ):
                    has_content = bool(getattr(inp, "value", ""))
                    self._set_hint_phase("typing" if has_content else "idle")

    def on_input_changed(self, event: Any) -> None:
        """Update hint phase on input content change (typing phase detection)."""
        # Only react to the main input area, not overlay inputs
        if getattr(event, "input", None) is not None:
            inp = event.input
            if getattr(inp, "id", None) == "input-area":
                # Don't override if agent is running or overlays are active
                if (
                    not getattr(self, "agent_running", False)
                    and not getattr(self, "command_running", False)
                    and not getattr(self, "browse_mode", False)
                    and not bool(getattr(self, "status_error", ""))
                    and not any(
                        getattr(self, attr) is not None
                        for attr in ("approval_state", "clarify_state", "sudo_state", "secret_state")
                    )
                ):
                    has_content = bool(getattr(inp, "value", ""))
                    self._set_hint_phase("typing" if has_content else "idle")

    def watch_size(self, size: Any) -> None:
        """Hide bottom-bar widgets when terminal is too short (height < 12)."""
        try:
            h = size.height
        except AttributeError:
            return
        try:
            plain_rule = self.query_one("#input-rule-bottom")
            plain_rule.display = h >= 8
        except NoMatches:
            pass
        try:
            image_bar = self.query_one(ImageBar)
            # Only hide if it was visible (has images)
            if h < 10:
                image_bar.styles.display = "none"
            elif image_bar._static_content:
                image_bar.styles.display = "block"
        except (NoMatches, AttributeError):
            pass
        try:
            hint_bar = self.query_one(HintBar)
            hint_bar.display = h >= 9
        except NoMatches:
            pass

    def watch_status_compaction_progress(self, value: float) -> None:
        if value == 0.0:
            self._compaction_warned = False
        try:
            self.query_one("#input-rule", TitledRule).progress = value
        except NoMatches:
            pass
        if value >= 0.9 and not self._compaction_warned:
            self._compaction_warned = True
            self._flash_hint("⚠  Context window 90% full — compaction imminent", 3.0)

    def watch_voice_mode(self, value: bool) -> None:
        try:
            self.query_one(VoiceStatusBar).set_class(value, "active")
        except NoMatches:
            pass
        self._set_hint_phase("voice" if value else self._compute_hint_phase())

    def watch_voice_recording(self, value: bool) -> None:
        try:
            bar = self.query_one(VoiceStatusBar)
            if value:
                bar.update_status("● REC")
            elif self.voice_mode:
                bar.update_status("🎤 Voice mode")
        except NoMatches:
            pass

    def watch_attached_images(self, value: list) -> None:
        try:
            self.query_one(ImageBar).update_images(value)
        except NoMatches:
            pass

    def _append_attached_images(self, images: list[Path]) -> None:
        """Keep TUI image state and CLI submit payload in sync."""
        if not images:
            return
        current = list(self.attached_images)
        current.extend(images)
        self.attached_images = current
        cli = getattr(self, "cli", None)
        if cli is not None and hasattr(cli, "_attached_images"):
            cli._attached_images.extend(images)

    def _clear_attached_images(self) -> None:
        self.attached_images = []
        cli = getattr(self, "cli", None)
        if cli is not None and hasattr(cli, "_attached_images"):
            cli._attached_images.clear()

    def _insert_link_tokens(self, tokens: list[str]) -> None:
        if not tokens:
            return
        try:
            inp = self.query_one("#input-area")
        except NoMatches:
            return
        selection = getattr(inp, "selection", None)
        if hasattr(inp, "_location_to_flat") and selection is not None:
            # TextArea: convert (row,col) to flat ints for string slicing
            start = end = inp.cursor_pos
            if not selection.is_empty:
                start = inp._location_to_flat(selection.start)
                end   = inp._location_to_flat(selection.end)
        else:
            start = end = getattr(inp, "cursor_position", 0)
            if selection is not None and not selection.is_empty:
                start, end = selection.start, selection.end

        before = inp.value[:start]
        after  = inp.value[end:]
        prefix = "" if not before or before[-1].isspace() else " "
        suffix = "" if not after  or after[0].isspace()  else " "
        payload = prefix + " ".join(tokens) + suffix
        if selection is not None and not selection.is_empty:
            if hasattr(inp, "replace_flat"):
                inp.replace_flat(payload, start, end)
            elif hasattr(inp, "replace"):
                inp.replace(payload, start, end)
        else:
            inp.insert_text(payload)

    @staticmethod
    def _drop_path_display(path: Path, cwd: Path) -> str:
        """Format a dropped file path: relative if in cwd/child/parent, else absolute."""
        try:
            return path.relative_to(cwd).as_posix()
        except ValueError:
            pass
        # Check parent level with os.path.relpath
        try:
            rel = _os_mod.path.relpath(path, cwd)
        except ValueError:
            return path.as_posix()
        # Count leading ../ segments — allow single level (parent/sibling)
        depth = 0
        r = rel
        while r.startswith(".."):
            depth += 1
            r = r[3:] if len(r) > 2 else ""
        if depth <= 1:
            return rel.replace(_os_mod.sep, "/")
        return path.as_posix()

    def handle_file_drop(self, paths: list[Path]) -> None:
        """Route terminal drag-and-drop pasted paths into input bar."""
        if any(getattr(self, attr) is not None for attr in ("approval_state", "clarify_state", "sudo_state", "secret_state")):
            self._flash_hint("file drop unavailable while prompt is open", 1.5)
            return

        cwd = self.get_working_directory()
        link_tokens: list[str] = []
        image_paths: list[Path] = []
        rejected: list[str] = []

        for path in paths:
            dropped = classify_dropped_file(path, cwd)
            if dropped.kind == "image":
                image_paths.append(path)
            elif dropped.kind in ("linkable_text", "unsupported_binary"):
                try:
                    link_tokens.append(format_link_token(path, cwd))
                except ValueError as exc:
                    rejected.append(str(exc))
            else:
                rejected.append(dropped.reason or dropped.kind)

        if image_paths:
            self._append_attached_images(image_paths)
        if link_tokens:
            self._insert_link_tokens(link_tokens)

        hint_parts: list[str] = []
        if link_tokens:
            noun = "file" if len(link_tokens) == 1 else "files"
            hint_parts.append(f"linked {len(link_tokens)} {noun}")
        if image_paths:
            noun = "image" if len(image_paths) == 1 else "images"
            hint_parts.append(f"attached {len(image_paths)} {noun}")
        if rejected:
            noun = "item" if len(rejected) == 1 else "items"
            hint_parts.append(f"dropped {len(rejected)} unsupported {noun}")

        if hint_parts:
            self._flash_hint(" · ".join(hint_parts), 1.2)

    # --- Reasoning panel helpers (called via call_from_thread) ---

    def _current_message_panel(self) -> MessagePanel | None:
        """Return the current MessagePanel, or None."""
        try:
            return self.query_one(OutputPanel).current_message
        except NoMatches:
            return None

    def open_reasoning(self, title: str = "Reasoning") -> None:
        """Open the reasoning panel. Safe to call from any thread via call_from_thread."""
        msg = self._current_message_panel()
        if msg is not None:
            msg.open_thinking_block(title)

    def append_reasoning(self, delta: str) -> None:
        """Append reasoning delta. Safe to call from any thread via call_from_thread."""
        msg = self._current_message_panel()
        if msg is not None:
            msg.append_thinking(delta)

    def close_reasoning(self) -> None:
        """Close the reasoning panel. Safe to call from any thread via call_from_thread."""
        msg = self._current_message_panel()
        if msg is not None:
            msg.close_thinking_block()

    # --- ToolBlock mounting ---

    def mount_tool_block(
        self,
        label: str,
        lines: list[str],
        plain_lines: list[str],
        rerender_fn=None,
        header_stats=None,
        tool_name: str | None = None,
    ) -> None:
        """Mount a ToolBlock into OutputPanel before the live-output duo.

        Tool blocks are direct children of MessagePanel so they stay correctly
        ordered across turns.  Mounting before ThinkingWidget/LiveLineWidget
        ensures completed blocks remain visually associated with their turn's
        content even after subsequent turns are appended.
        """
        if not lines:
            return
        try:
            output = self.query_one(OutputPanel)
            # Ensure a MessagePanel exists for this turn (holds response text).
            msg = output.current_message or output.new_message()
            msg.mount_tool_block(
                label,
                lines,
                plain_lines,
                tool_name=tool_name,
                rerender_fn=rerender_fn,
                header_stats=header_stats,
            )
            msg.refresh(layout=True)
            # Increment memoized header count to avoid O(n) query in StatusBar
            self._browse_total += 1
            if not output._user_scrolled_up:
                self.call_after_refresh(output.scroll_end, animate=False)
        except NoMatches:
            pass

    # --- StreamingToolBlock lifecycle ---

    def _open_gen_block(self, tool_name: str) -> "Any | None":
        """Open a StreamingToolBlock at gen_start time. Event-loop only.

        Called via call_from_thread from the agent thread during streaming
        argument generation. Returns the block reference for queue correlation,
        or None if the mount failed.
        """
        try:
            output = self.query_one(OutputPanel)
            msg = output.current_message or output.new_message()
            block = msg.open_streaming_tool_block(label=tool_name, tool_name=tool_name)
            self._browse_total += 1
            if not output._user_scrolled_up:
                self.call_after_refresh(output.scroll_end, animate=False)
            return block
        except NoMatches:
            return None

    def open_streaming_tool_block(self, tool_call_id: str, label: str, tool_name: str | None = None) -> None:
        """Mount a StreamingToolBlock into OutputPanel before the live-output duo.

        Tool blocks are direct children of MessagePanel so they stay correctly
        ordered across turns.  Mounting before ThinkingWidget/LiveLineWidget
        means completed STBs remain visually adjacent to their turn's content
        after subsequent turns are appended.

        Called via ``call_from_thread`` from the agent thread before the tool
        starts executing.  Subsequent output lines are routed here via
        ``append_streaming_line()``.
        """
        try:
            output = self.query_one(OutputPanel)
            # Ensure a MessagePanel exists for this turn (holds response text).
            msg = output.current_message or output.new_message()
            block = msg.open_streaming_tool_block(label=label, tool_name=tool_name)
            self._active_streaming_blocks[tool_call_id] = block
            msg.refresh(layout=True)
            self._browse_total += 1
            if not output._user_scrolled_up:
                self.call_after_refresh(output.scroll_end, animate=False)
        except NoMatches:
            pass

    def append_streaming_line(self, tool_call_id: str, line: str) -> None:
        """Append a line to the named streaming block. Event-loop only.

        Called via ``call_from_thread`` from the agent thread (via the
        ``on_line`` callback registered in ``cli.py._on_tool_start``).
        """
        block = self._active_streaming_blocks.get(tool_call_id)
        if block is None:
            return
        block.append_line(line)
        # Auto-scroll when user hasn't manually scrolled away
        try:
            panel = self.query_one(OutputPanel)
            if not panel._user_scrolled_up:
                self.call_after_refresh(panel.scroll_end, animate=False)
        except NoMatches:
            pass

    def close_streaming_tool_block(self, tool_call_id: str, duration: str, is_error: bool = False) -> None:
        """Transition streaming block to COMPLETED state. Event-loop only.

        Called via ``call_from_thread`` from the agent thread after the tool
        finishes executing.
        """
        block = self._active_streaming_blocks.pop(tool_call_id, None)
        if block is None:
            return
        block.complete(duration, is_error=is_error)
        # Scroll to show the completed (now collapsed) block
        try:
            panel = self.query_one(OutputPanel)
            if not panel._user_scrolled_up:
                self.call_after_refresh(panel.scroll_end, animate=False)
        except NoMatches:
            pass

    def remove_streaming_tool_block(self, tool_call_id: str) -> None:
        """Remove a streaming block from the DOM entirely. Event-loop only.

        Used when a static preview block (diff, code) replaces the streaming
        block — avoids showing both for the same tool call.
        """
        block = self._active_streaming_blocks.pop(tool_call_id, None)
        if block is None:
            return
        try:
            block.remove()
        except Exception:
            pass

    # --- Browse mode ---

    def _apply_browse_focus(self) -> None:
        """Update .focused CSS class on all ToolHeaders based on browse state."""
        from hermes_cli.tui.tool_blocks import ToolHeader as _TH
        headers = list(self.query(_TH))
        for i, h in enumerate(headers):
            if self.browse_mode and i == self.browse_index:
                h.add_class("focused")
            else:
                h.remove_class("focused")

    def watch_browse_mode(self, value: bool) -> None:
        from hermes_cli.tui.tool_blocks import ToolHeader as _TH
        if value:
            # If no ToolHeaders exist, do not enter browse mode
            if not list(self.query(_TH)):
                self.browse_mode = False
                return
            self._browse_uses += 1
        # Disable/re-enable input so printable keys bubble to on_key in browse mode
        try:
            inp = self.query_one("#input-area")
            inp.disabled = value
            if not value:
                inp.display = True
                inp.focus()
        except NoMatches:
            pass
        self._apply_browse_focus()
        self._set_hint_phase("browse" if value else self._compute_hint_phase())

    def watch_browse_index(self, _value: int) -> None:
        self._apply_browse_focus()

    # --- Theme / skin system ---

    def get_css_variables(self) -> dict[str, str]:
        """Merge ThemeManager overrides into Textual's CSS variable resolution.

        Confirmed stable: ``App.get_css_variables() -> dict[str, str]`` is
        unchanged from Textual 1.0 through 8.x.

        Variable precedence (highest → lowest):
            component_vars  >  skin vars  >  Textual defaults

        The component_vars layer enables full Component Parts theming without
        private-API hacks: ``hermes.tcss`` references ``$cursor-color`` etc.
        which ThemeManager injects here.
        """
        base = super().get_css_variables()
        # _theme_manager may not exist yet if called during super().__init__().
        # Fall back to COMPONENT_VAR_DEFAULTS so CSS vars resolve on first parse.
        tm = getattr(self, "_theme_manager", None)
        if tm is not None:
            overrides = tm.css_variables
        else:
            from hermes_cli.tui.theme_manager import COMPONENT_VAR_DEFAULTS
            overrides = COMPONENT_VAR_DEFAULTS
        return {**base, **overrides}

    def apply_skin(self, skin_vars: "dict[str, str] | Path") -> None:
        """Apply a skin as CSS variable overrides.

        Accepts either a pre-built ``dict[str, str]`` of Textual CSS variable
        names, or a ``Path`` to a JSON/YAML skin file (processed via
        ``ThemeManager``).

        Skin files may include a ``component_vars`` section to theme cursor
        colour, selection colour, and other Component Part variables.

        Safe to call via ``call_from_thread``.
        """
        if isinstance(skin_vars, dict):
            self._theme_manager.load_dict(skin_vars)
        else:
            self._theme_manager.load([skin_vars])
        self._theme_manager.apply()
        # Invalidate hint cache on skin change so key-badge colors are rebuilt
        from hermes_cli.tui.widgets import _hint_cache
        _hint_cache.clear()
        # Invalidate StatusBar idle tips cache
        try:
            sb = self.query_one(StatusBar)
            sb._idle_tips_cache = None
        except NoMatches:
            pass
        try:
            from .completion_list import VirtualCompletionList
            self.query_one(VirtualCompletionList).refresh_theme()
        except NoMatches:
            pass
        except Exception:
            logger.debug("Completion list theme refresh failed", exc_info=True)
        try:
            from .preview_panel import PreviewPanel
            self.query_one(PreviewPanel).refresh_theme()
        except NoMatches:
            pass
        except Exception:
            logger.debug("Preview panel theme refresh failed", exc_info=True)
        from hermes_cli.tui.tool_blocks import ToolBlock
        for block in self.query(ToolBlock):
            try:
                block.refresh_skin()
            except Exception:
                logger.debug("ToolBlock theme refresh failed", exc_info=True)
        for block in self.query(StreamingCodeBlock):
            try:
                block.refresh_skin(self.get_css_variables())
            except Exception:
                logger.debug("StreamingCodeBlock theme refresh failed", exc_info=True)

    def refresh_slash_commands(self, extra: list[str] | None = None) -> None:
        """Update the slash command list after plugins are loaded.

        Call via ``call_from_thread`` if not on the event loop.

        Parameters
        ----------
        extra:
            Additional command names to append (e.g. plugin-registered commands
            that COMMAND_REGISTRY doesn't know about yet).
        """
        self._populate_slash_commands()
        if extra:
            try:
                from hermes_cli.tui.input_widget import HermesInput as _HI
                inp = self.query_one(_HI)
                combined = sorted(set(inp._slash_commands) | {
                    n if n.startswith("/") else f"/{n}" for n in extra
                })
                inp.set_slash_commands(combined)
            except (NoMatches, Exception):
                pass

    # --- Clipboard / selection helpers ---

    def _get_selected_text(self) -> str | None:
        """Return selected text from the screen, or None."""
        try:
            result = self.screen.get_selected_text()
            return result if result else None
        except Exception:
            return None

    # --- Slash command wiring ---

    def _populate_slash_commands(self) -> None:
        """Feed the canonical command list from COMMAND_REGISTRY into HermesInput.

        Called once on mount.  Safe to call again after plugin commands are added.
        Includes built-in commands, their aliases, and any registered skill commands.
        """
        try:
            from hermes_cli.tui.input_widget import HermesInput as _HI
            from hermes_cli.commands import COMMAND_REGISTRY
            # Build full slash-name list: /name + /alias for each command
            names: list[str] = []
            for cmd in COMMAND_REGISTRY:
                names.append(f"/{cmd.name}")
                for alias in getattr(cmd, "aliases", []):
                    names.append(f"/{alias}")
            try:
                inp = self.query_one(_HI)
                inp.set_slash_commands(names)
            except NoMatches:
                pass
        except Exception:
            pass  # Don't crash on import errors during init

    # --- Copy/paste feedback ---

    def _flash_hint(self, text: str, duration: float = 1.5) -> None:
        """Flash *text* in the HintBar for *duration* seconds, then restore.

        Reuses the existing ``HintBar.hint`` reactive — no new widgets.
        Safe to call from the event loop (e.g. from action lambdas).
        """
        try:
            bar = self.query_one(HintBar)
            prior = bar.hint
            bar.hint = text
            # Reserve the hint bar for the flash duration so _tick_spinner
            # does not overwrite the message before it expires.
            self._flash_hint_expires = _time.monotonic() + duration
            self.set_timer(duration, lambda: setattr(bar, "hint", prior))
        except NoMatches:
            pass

    def set_status_error(self, msg: str, auto_clear_s: float = 0.0) -> None:
        """Persistent StatusBar error. Also fires a flash hint for immediate visibility.

        Thread-safety: must be called from the event loop.
        auto_clear_s=0 → sticky until next set_status_error("") call.
        auto_clear_s>0 → auto-clears after that many seconds.
        """
        self.status_error = msg
        flash_duration = auto_clear_s if 0 < auto_clear_s <= 2.5 else 2.5
        self._flash_hint(f"⚠ {msg}", flash_duration)
        if auto_clear_s > 0:
            self.set_timer(auto_clear_s, lambda: setattr(self, "status_error", ""))

    def _copy_text_with_hint(self, text: str) -> None:
        """Copy text to clipboard with capability guard and hint flash."""
        # Keep Textual's local clipboard in sync even when we have to fall back
        # to external clipboard tools, so app-level paste actions still work.
        self._clipboard = text
        if not self._clipboard_available:
            if self._xclip_cmd:
                try:
                    import subprocess
                    subprocess.run(
                        self._xclip_cmd,
                        input=text.encode(),
                        check=True,
                        timeout=2,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    self._flash_hint(f"⎘  {len(text)} chars copied", 1.5)
                except Exception:
                    self.set_status_error("copy failed", auto_clear_s=10.0)
            else:
                self.set_status_error("no clipboard — install xclip or xsel", auto_clear_s=0)
            return
        self.copy_to_clipboard(text)
        self._flash_hint(f"⎘  {len(text)} chars copied", 1.5)

    # --- Right-click context menu ---

    async def on_click(self, event: Any) -> None:
        """Left-click focuses input; right-click (button=3) shows context menu."""
        if event.button == 1:
            # Don't steal focus when clicking inside panels that manage their own focus.
            from hermes_cli.tui.widgets import OutputPanel as _OP, HistorySearchOverlay as _HSO
            node = getattr(event, "widget", None)
            while node is not None:
                if isinstance(node, (_OP, _HSO)):
                    return
                node = getattr(node, "parent", None)
            try:
                self.query_one("#input-area").focus()
            except NoMatches:
                pass
            return
        if event.button != 3:
            return
        items = self._build_context_items(event)
        if not items:
            return
        event.prevent_default()
        # Resolve screen coords — show() receives ints, not int|None
        sx = event.screen_x if event.screen_x is not None else event.x
        sy = event.screen_y if event.screen_y is not None else event.y
        try:
            from hermes_cli.tui.context_menu import ContextMenu as _CM
            await self.query_one(_CM).show(items, sx, sy)
        except NoMatches:
            pass

    def on_path_search_provider_batch(self, message: Any) -> None:
        """Relay PathSearchProvider.Batch to HermesInput.

        PathSearchProvider and HermesInput are siblings (both children of the
        Screen).  Textual only bubbles messages upward through the parent chain,
        so PathSearchProvider.post_message(Batch) reaches the App but never
        reaches HermesInput.  This relay bridges the gap by calling the handler
        directly on the input widget.
        """
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.query_one(HermesInput).on_path_search_provider_batch(message)
        except (NoMatches, ImportError):
            pass

    def _build_context_items(self, event: Any) -> list:
        """Walk the clicked widget's parent chain and return context menu items.

        Priority (first match wins):
        1. ToolBlock / ToolHeader → tool copy + expand/collapse + copy-all
        2. MessagePanel          → copy selected (if any) + copy full response
        3. HermesInput / #input-row → paste hint + clear input
        4. Fallback              → copy selected only (if selection is active)
        """
        from hermes_cli.tui.context_menu import MenuItem

        widget = getattr(event, "widget", None)
        if widget is None:
            return []

        # Walk up the parent chain
        node = widget
        while node is not None:
            # --- ToolBlock ---
            try:
                from hermes_cli.tui.tool_blocks import ToolBlock as _TB
                if isinstance(node, _TB):
                    block = node
                    return [
                        MenuItem("⎘  Copy tool output", "", lambda b=block: self._copy_tool_output(b)),
                        MenuItem("▸/▾  Expand/Collapse", "", lambda b=block: b.toggle()),
                        MenuItem("⎘  Copy all output", "", lambda: self._copy_all_output(), separator_above=True),
                    ]
            except ImportError:
                pass

            # --- ToolHeader (parent is the ToolBlock) ---
            try:
                from hermes_cli.tui.tool_blocks import ToolHeader as _TH, ToolBlock as _TB
                if isinstance(node, _TH):
                    parent = node.parent
                    if isinstance(parent, _TB):
                        block = parent
                        return [
                            MenuItem("⎘  Copy tool output", "", lambda b=block: self._copy_tool_output(b)),
                            MenuItem("▸/▾  Expand/Collapse", "", lambda b=block: b.toggle()),
                            MenuItem("⎘  Copy all output", "", lambda: self._copy_all_output(), separator_above=True),
                        ]
            except ImportError:
                pass

            # --- StreamingCodeBlock ---
            try:
                from hermes_cli.tui.widgets import StreamingCodeBlock as _SCB
                if isinstance(node, _SCB):
                    cb = node
                    items = [
                        MenuItem("⎘  Copy code block", "", lambda b=cb: self._copy_code_block(b)),
                    ]
                    if cb.can_toggle():
                        items.append(MenuItem("▸/▾  Expand/Collapse", "", lambda b=cb: b.toggle_collapsed()))
                    return items
            except ImportError:
                pass

            # --- MessagePanel ---
            try:
                from hermes_cli.tui.widgets import MessagePanel as _MP
                if isinstance(node, _MP):
                    panel = node
                    items = []
                    selected = self._get_selected_text()
                    if selected:
                        sel_text = selected
                        items.append(MenuItem("⎘  Copy selected", "", lambda t=sel_text: self._copy_text(t)))
                    items.append(MenuItem("⎘  Copy full response", "", lambda p=panel: self._copy_panel(p)))
                    return items
            except ImportError:
                pass

            # --- HermesInput ---
            try:
                from hermes_cli.tui.input_widget import HermesInput as _HI
                if isinstance(node, _HI):
                    items = []
                    sel = getattr(node, "selection", None)
                    if sel is not None and not sel.is_empty:
                        try:
                            sel_text = node.get_text_range(sel.start, sel.end)
                        except Exception:
                            sel_text = getattr(node, "selected_text", "")
                        if sel_text:
                            items.append(MenuItem("⎘  Copy selected", "ctrl+c", lambda t=sel_text: self._copy_text(t)))
                    items += [
                        MenuItem(f"{ICON_COPY}  Paste", "ctrl+v", lambda: self._paste_into_input()),
                        MenuItem("✕  Clear input", "", lambda: self._clear_input()),
                    ]
                    return items
            except ImportError:
                pass

            # --- #input-row container ---
            if getattr(node, "id", None) == "input-row":
                return [
                    MenuItem(f"{ICON_COPY}  Paste", "ctrl+v", lambda: self._paste_into_input()),
                    MenuItem("✕  Clear input", "", lambda: self._clear_input()),
                ]

            node = getattr(node, "parent", None)

        # Fallback: always provide Paste; add Copy selected when text is highlighted.
        items = []
        selected = self._get_selected_text()
        if selected:
            sel_text = selected
            items.append(MenuItem("⎘  Copy selected", "", lambda t=sel_text: self._copy_text(t)))
        items.append(MenuItem(f"{ICON_COPY}  Paste", "ctrl+v", lambda: self._paste_into_input()))
        return items

    # --- Context menu action helpers ---

    def _copy_code_block(self, block: Any) -> None:
        """Copy a StreamingCodeBlock's plain-text content to clipboard and flash footer."""
        try:
            content = block.copy_content()
            self._copy_text_with_hint(content)
            if hasattr(block, "flash_copy"):
                block.flash_copy()
        except Exception:
            self._flash_hint("⚠ copy failed", 1.5)

    def _copy_tool_output(self, block: Any) -> None:
        """Copy a ToolBlock's plain-text content to clipboard and flash hint."""
        try:
            content = block.copy_content()
            self._copy_text_with_hint(content)
        except Exception:
            self._flash_hint("⚠ copy failed", 1.5)

    def _copy_all_output(self) -> None:
        """Copy plain text from every CopyableRichLog in the output panel."""
        try:
            from hermes_cli.tui.widgets import CopyableRichLog as _CRL
            parts = [log.copy_content() for log in self.query(_CRL)]
            content = "\n".join(p for p in parts if p)
            self._copy_text_with_hint(content)
        except Exception:
            self._flash_hint("⚠ copy failed", 1.5)

    def _copy_panel(self, panel: Any) -> None:
        """Copy a MessagePanel's response log content to clipboard."""
        try:
            from hermes_cli.tui.widgets import MessagePanel as _MP, CopyableRichLog as _CRL
            if isinstance(panel, _MP):
                content = panel.all_prose_text()
            elif isinstance(panel, _CRL):
                content = panel.copy_content()
            else:
                return
            self._copy_text_with_hint(content)
        except Exception:
            self._flash_hint("⚠ copy failed", 1.5)

    def _copy_text(self, text: str) -> None:
        """Copy arbitrary text to clipboard and flash hint."""
        self._copy_text_with_hint(text)

    def _paste_into_input(self) -> None:
        """Paste app clipboard content into the input and flash a paste hint."""
        try:
            inp = self.query_one("#input-area")
            text = self.clipboard
            if not text:
                inp.focus()
                self._flash_hint("clipboard empty", 1.5)
                return
            if hasattr(inp, "insert_text"):
                inp.insert_text(text)
            elif hasattr(inp, "value"):
                inp.value = f"{getattr(inp, 'value', '')}{text}"
            inp.focus()
            self._flash_hint(f"⎘  {len(text)} chars pasted", 1.2)
        except NoMatches:
            pass

    def _clear_input(self) -> None:
        """Clear the input content."""
        try:
            inp = self.query_one("#input-area")
            if hasattr(inp, "clear"):
                inp.clear()
            elif hasattr(inp, "value"):
                inp.value = ""
        except NoMatches:
            pass

    # --- Undo / Retry / Rollback (SPEC-C) ---

    def _handle_tui_command(self, text: str) -> bool:
        """Intercept TUI-specific slash commands before agent sees them.

        Returns True if the command was handled here (do not forward to agent).
        Returns False if not a TUI command (forward to agent as normal).
        """
        stripped = text.strip()
        if stripped == "/undo":
            self._initiate_undo()
            return True
        if stripped == "/retry":
            self._initiate_retry()
            return True
        if re.match(r"^/rollback(?:\s+\d+)?$", stripped):
            self._initiate_rollback(stripped)
            return True
        if stripped == "/compact":
            self.action_toggle_density()
            return True
        if stripped == "/anim":
            self._open_anim_config()
            return True
        return False

    def _has_rollback_checkpoint(self) -> bool:
        """Return True if the agent has a filesystem checkpoint available."""
        try:
            return bool(getattr(self.cli.agent, "has_checkpoint", lambda: False)())
        except Exception:
            return False

    def _open_anim_config(self) -> None:
        """Toggle the AnimConfigPanel overlay."""
        try:
            from hermes_cli.tui.drawille_overlay import AnimConfigPanel as _ACP
            panel = self.query_one(_ACP)
            if panel.has_class("-open"):
                panel.close()
            else:
                panel.open()
        except NoMatches:
            pass

    def action_open_anim_config(self) -> None:
        self._open_anim_config()

    def _initiate_undo(self) -> None:
        if self._undo_in_progress:
            self._flash_hint("⚠  Undo in progress", 1.5)
            return
        if self.agent_running:
            self._flash_hint("⚠  Cannot undo while agent is running", 2.0)
            return
        panels = list(self.query(MessagePanel))
        if not panels:
            self._flash_hint("⚠  Nothing to undo", 1.5)
            return
        last_panel = panels[-1]
        user_text = getattr(last_panel, "_user_text", "")
        state = UndoOverlayState(
            deadline=_time.monotonic() + 10,
            response_queue=queue.Queue(),
            user_text=user_text[:80] + "…" if len(user_text) > 80 else user_text,
            has_checkpoint=self._has_rollback_checkpoint(),
        )
        self._pending_undo_panel = last_panel
        self._pending_rollback_n = 0
        self.undo_state = state

    @work(thread=False)
    async def _run_undo_sequence(self, panel: MessagePanel) -> None:
        try:
            self._undo_in_progress = True

            # Step 1: Opacity fade to signal impending removal
            panel.styles.opacity = 0.3
            await asyncio.sleep(0.4)  # wait for CSS transition (0.3s + margin)

            # Step 2: Call agent undo in a thread so event loop stays responsive
            try:
                await asyncio.to_thread(self.cli.agent.undo)
            except (AttributeError, NotImplementedError):
                self._flash_hint("⚠  Undo not supported by agent", 2.0)
                panel.styles.opacity = 1.0
                return

            # Step 3: Remove the MessagePanel from DOM (synchronous in Textual)
            panel.remove()

            # Step 4: Restore user message to HermesInput (if stored)
            user_text = getattr(panel, "_user_text", "")
            if user_text:
                try:
                    from hermes_cli.tui.input_widget import HermesInput
                    hi = self.query_one(HermesInput)
                    hi.value = user_text
                    hi.cursor_position = len(user_text)
                except NoMatches:
                    pass

            # Step 5: Feedback
            self._flash_hint("↩  Undo done", 2.0)
        finally:
            self._undo_in_progress = False

    def _initiate_retry(self) -> None:
        if self.agent_running:
            self._flash_hint("⚠  Cannot retry while agent is running", 2.0)
            return
        panels = list(self.query(MessagePanel))
        if not panels:
            self._flash_hint("⚠  Nothing to retry", 1.5)
            return
        last_user_text = getattr(panels[-1], "_user_text", "")
        if not last_user_text:
            self._flash_hint("⚠  No user message to retry", 1.5)
            return
        try:
            from hermes_cli.tui.input_widget import HermesInput
            hi = self.query_one(HermesInput)
            hi.value = last_user_text
            hi.cursor_position = len(last_user_text)
            hi.action_submit()
        except NoMatches:
            pass

    def _initiate_rollback(self, text: str) -> None:
        m = re.match(r"^/rollback(?:\s+(\d+))?$", text.strip())
        if not m:
            self._flash_hint("⚠  Usage: /rollback [N]", 2.0)
            return
        n = int(m.group(1)) if m.group(1) else 0
        # Build a simple rollback state reusing UndoOverlayState
        state = UndoOverlayState(
            deadline=_time.monotonic() + 15,
            response_queue=queue.Queue(),
            user_text=f"Filesystem rollback (checkpoint {n})",
            has_checkpoint=True,
        )
        self._pending_undo_panel = None
        self._pending_rollback_n = n
        self.undo_state = state

    @work(thread=False)
    async def _run_rollback_sequence(self, n: int) -> None:
        try:
            await asyncio.to_thread(self.cli.agent.rollback, n)
            self._flash_hint("↩  Rollback done", 2.0)
        except (AttributeError, NotImplementedError):
            self._flash_hint("⚠  Rollback not supported by agent", 2.0)

    # --- Key bindings for overlays, copy, and interrupt ---

    def on_key(self, event: Any) -> None:
        """Global key handler for overlay navigation, copy, and interrupt.

        Keybinding split:
        - ctrl+c: copy selected text → cancel overlay → clear input → exit
        - ctrl+shift+c: dedicated agent interrupt (double-press = force exit)
        - escape: cancel overlay → interrupt agent
        """
        key = event.key

        # --- ctrl+p → path/file picker (@-completion) ---
        if key == "ctrl+p":
            try:
                from hermes_cli.tui.input_widget import HermesInput as _HI
                inp = self.query_one(_HI)
                inp.focus()
                inp.insert_text("@")
            except (NoMatches, Exception):
                pass
            event.prevent_default()
            return

        # --- undo overlay key dispatch ---
        if self.undo_state is not None:
            if event.key in ("y", "enter"):
                pending_panel = self._pending_undo_panel
                pending_n = self._pending_rollback_n
                self.undo_state = None
                self._pending_undo_panel = None
                if pending_panel is not None:
                    # Undo: run undo sequence directly (no thread/queue needed)
                    self._run_undo_sequence(pending_panel)
                else:
                    # Rollback
                    self._run_rollback_sequence(pending_n)
                event.prevent_default()
                return
            if event.key in ("n", "escape"):
                self.undo_state = None
                self._pending_undo_panel = None
                event.prevent_default()
                return

        # --- ctrl+c: copy / cancel overlay / clear / exit ---
        if key == "ctrl+c":
            # Priority 1: copy selected text from output panels
            # (Input handles its own selection copy internally)
            selected = self._get_selected_text()
            if selected:
                self._copy_text_with_hint(selected)
                event.prevent_default()
                return

            # Priority 2: cancel active overlays (deny)
            for state_attr in ("approval_state", "clarify_state"):
                state: ChoiceOverlayState | None = getattr(self, state_attr)
                if state is not None:
                    state.response_queue.put("deny")
                    setattr(self, state_attr, None)
                    event.prevent_default()
                    return
            for state_attr in ("sudo_state", "secret_state"):
                state = getattr(self, state_attr)
                if state is not None:
                    state.response_queue.put("")
                    setattr(self, state_attr, None)
                    event.prevent_default()
                    return

            # Priority 3: clear input or exit (NO interrupt)
            if not self.agent_running:
                try:
                    inp = self.query_one("#input-area")
                    if hasattr(inp, "content") and inp.content:
                        inp.clear()
                    else:
                        self.exit()
                except NoMatches:
                    self.exit()
            event.prevent_default()
            return

        # --- ctrl+shift+c: dedicated agent interrupt ---
        if key == "ctrl+shift+c":
            if self.agent_running and hasattr(self.cli, "agent") and self.cli.agent:
                now = _time.monotonic()
                last = getattr(self, "_last_interrupt_time", 0.0)
                if now - last < 2.0:
                    # Double ctrl+shift+c within 2s → force exit
                    self.exit()
                    event.prevent_default()
                    return
                self._last_interrupt_time = now
                self.cli.agent.interrupt()
                # Show feedback
                try:
                    panel = self.query_one(OutputPanel)
                    msg = panel.current_message
                    if msg is not None:
                        rl = msg.response_log
                        rl.write(
                            Text.from_markup("[bold red]⚡ Interrupting...[/bold red]")
                        )
                        if rl._deferred_renders:
                            self.call_after_refresh(msg.refresh, layout=True)
                except NoMatches:
                    pass
                event.prevent_default()
                return

        # --- escape: cancel overlay, interrupt agent, browse mode, or enter browse ---
        if key == "escape":
            # Priority -1: dismiss history search overlay (highest priority — fires
            # before completion overlay so Escape always closes the search first).
            try:
                hs = self.query_one(HistorySearchOverlay)
                if hs.has_class("--visible"):
                    hs.action_dismiss()
                    event.prevent_default()
                    return
            except NoMatches:
                pass

            # Priority 0: dismiss completion overlay (before everything else so it
            # doesn't fire agent-interrupt or browse-mode on the same keystroke).
            try:
                from hermes_cli.tui.completion_overlay import CompletionOverlay as _CO
                _co = self.query_one(_CO)
                if _co.has_class("--visible"):
                    _co.remove_class("--visible")
                    _co.remove_class("--slash-only")
                    event.prevent_default()
                    return
            except NoMatches:
                pass

            # Priority 1: exit browse mode
            if self.browse_mode:
                self.browse_mode = False
                event.prevent_default()
                return

            # Priority 2: cancel active overlays (None response)
            for state_attr in ("approval_state", "clarify_state"):
                state = getattr(self, state_attr)
                if state is not None:
                    state.response_queue.put(None)
                    setattr(self, state_attr, None)
                    event.prevent_default()
                    return
            for state_attr in ("sudo_state", "secret_state"):
                state = getattr(self, state_attr)
                if state is not None:
                    state.response_queue.put("")
                    setattr(self, state_attr, None)
                    event.prevent_default()
                    return

            # Priority 3: interrupt running agent
            if self.agent_running and hasattr(self.cli, "agent") and self.cli.agent:
                self.cli.agent.interrupt()
                try:
                    panel = self.query_one(OutputPanel)
                    msg = panel.current_message
                    if msg is not None:
                        rl = msg.response_log
                        rl.write(
                            Text.from_markup("[bold red]⚡ Interrupting...[/bold red]")
                        )
                        if rl._deferred_renders:
                            self.call_after_refresh(msg.refresh, layout=True)
                except NoMatches:
                    pass
                event.prevent_default()
                return

            # Priority 4: enter browse mode when idle (no overlay, agent not running)
            no_overlay = all(
                getattr(self, a) is None
                for a in ("approval_state", "clarify_state", "sudo_state", "secret_state")
            )
            if no_overlay and not self.agent_running:
                self.browse_mode = True
                event.prevent_default()
                return

        # --- Browse mode key handling ---
        if self.browse_mode:
            from hermes_cli.tui.tool_blocks import ToolHeader as _TH
            headers = list(self.query(_TH))
            total = max(1, len(headers))

            if key == "tab":
                self.browse_index = (self.browse_index + 1) % total
                event.prevent_default()
                return
            elif key == "shift+tab":
                self.browse_index = (self.browse_index - 1) % total
                event.prevent_default()
                return
            elif key == "enter":
                if headers:
                    idx = self.browse_index % len(headers)
                    parent = headers[idx].parent
                    if hasattr(parent, "toggle"):
                        parent.toggle()
                event.prevent_default()
                return
            elif key == "c":
                if headers:
                    idx = self.browse_index % len(headers)
                    h = headers[idx]
                    parent = h.parent
                    if hasattr(parent, "copy_content"):
                        self._copy_text_with_hint(parent.copy_content())
                    h.flash_copy()
                event.prevent_default()
                return
            elif key == "a":
                # Expand all blocks (only those with affordances)
                from hermes_cli.tui.tool_blocks import ToolBlock as _TB
                for block in self.query(_TB):
                    if not block._body.has_class("expanded"):
                        block.toggle()
                event.prevent_default()
                return
            elif key == "A":
                # Collapse all blocks (only those with affordances)
                from hermes_cli.tui.tool_blocks import ToolBlock as _TB
                for block in self.query(_TB):
                    if block._body.has_class("expanded"):
                        block.toggle()
                event.prevent_default()
                return
            elif key == "escape":
                self.browse_mode = False
                event.prevent_default()
                return
            elif event.character is not None:
                # Printable key: exit browse mode and insert the character
                self.browse_mode = False
                try:
                    inp = self.query_one("#input-area")
                    if hasattr(inp, "insert_text"):
                        inp.insert_text(event.character)
                except NoMatches:
                    pass
                event.prevent_default()
                return

        # Overlay key handling — check each overlay in priority order
        for state_attr, widget_type in [
            ("approval_state", ApprovalWidget),
            ("clarify_state", ClarifyWidget),
        ]:
            state = getattr(self, state_attr)
            if state is not None:
                if key == "up" and state.selected > 0:
                    state.selected -= 1
                    try:
                        self.query_one(widget_type).update(state)
                    except NoMatches:
                        pass
                    event.prevent_default()
                    return
                elif key == "down" and state.selected < len(state.choices) - 1:
                    state.selected += 1
                    try:
                        self.query_one(widget_type).update(state)
                    except NoMatches:
                        pass
                    event.prevent_default()
                    return
                elif key == "enter":
                    if state.choices:
                        chosen = state.choices[state.selected]
                        state.response_queue.put(chosen)
                        setattr(self, state_attr, None)
                    event.prevent_default()
                    return

    # --- Input submission handler ---

    def on_hermes_input_submitted(self, event: Any) -> None:
        """Handle input submission from HermesInput.

        When agent is running: interrupt first, then send new message
        (except /queue and /btw which queue without interrupting).
        """
        text = event.value
        images = list(self.attached_images)
        if images:
            self._clear_attached_images()
            payload = (text, images)
        else:
            payload = text

        # If agent is running, decide: interrupt or queue
        if self.agent_running and text:
            _cmd = text.lstrip("/").split()[0].lower() if text.startswith("/") else ""
            if _cmd in ("queue", "btw"):
                # /queue and /btw queue without interrupting
                if hasattr(self.cli, "_pending_input"):
                    self.cli._pending_input.put(payload)
                return
            # Everything else: interrupt agent, then send as new message
            # Activate thinking shimmer for the upcoming new turn
            try:
                self.query_one(ThinkingWidget).activate()
            except NoMatches:
                pass
            if hasattr(self.cli, "agent") and self.cli.agent:
                self.cli.agent.interrupt()
            if hasattr(self.cli, "_pending_input"):
                self.cli._pending_input.put(payload)
            return

        # Normal submission (agent idle)
        # Activate thinking shimmer — deactivated when first chunk arrives
        try:
            self.query_one(ThinkingWidget).activate()
        except NoMatches:
            pass
        if hasattr(self, "cli") and self.cli is not None:
            if hasattr(self.cli, "_pending_input"):
                self.cli._pending_input.put(payload)

    def on_hermes_input_files_dropped(self, event: Any) -> None:
        """Handle terminal drag-and-drop pasted paths from HermesInput."""
        self.handle_file_drop(event.paths)
