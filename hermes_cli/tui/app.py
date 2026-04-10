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
import logging
import platform
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import TextArea
from textual import work

from hermes_cli.tui.state import (
    ChoiceOverlayState,
    OverlayState,
    SecretOverlayState,
)
from hermes_cli.tui.widgets import (
    ApprovalWidget,
    ClarifyWidget,
    HintBar,
    ImageBar,
    LiveLineWidget,
    MessagePanel,
    OutputPanel,
    PlainRule,
    ReasoningPanel,
    SecretWidget,
    StatusBar,
    SudoWidget,
    TitledRule,
    VoiceStatusBar,
    _safe_widget_call,
)

if TYPE_CHECKING:
    from hermes_cli.tui.input_widget import HermesInput

logger = logging.getLogger(__name__)

# CPython fast-path: asyncio.Queue.put_nowait is GIL-atomic on CPython
# because deque.append is atomic. On other runtimes, use call_soon_threadsafe.
_CPYTHON_FAST_PATH = platform.python_implementation() == "CPython"

# CSS file path — relative to this module
_CSS_PATH = Path(__file__).parent / "hermes.tcss"


class HermesApp(App):
    """Main Textual application for the Hermes Agent TUI.

    Holds all reactive state that drives widget updates. The agent thread
    (and other background threads) mutate these reactives via
    ``call_from_thread``, and Textual's watch system handles re-rendering.
    """

    CSS_PATH = "hermes.tcss"

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

    # Status bar data
    status_tokens: reactive[int] = reactive(0)
    status_model: reactive[str] = reactive("")
    status_duration: reactive[float] = reactive(0.0)

    # Image attachments — reactive(list) uses factory form to avoid shared mutable default
    attached_images: reactive[list] = reactive(list)

    # Spinner label — text shown beside the spinner frame (e.g. "Calling tool…")
    spinner_label: reactive[str] = reactive("")

    # hint_text is NOT on HermesApp — HintBar.hint is the single source of truth.

    def __init__(self, cli: Any, startup_fn=None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.cli = cli
        self._startup_fn = startup_fn

        # Bounded queue: prevents unbounded memory growth when agent produces
        # faster than UI renders. 4096 chunks ≈ ~1MB of text at ~256 bytes/chunk.
        self._output_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=4096)
        self._spinner_idx = 0
        self._event_loop: asyncio.AbstractEventLoop | None = None

        # Skin CSS variable overrides (injected via get_css_variables)
        self._skin_vars: dict[str, str] = {}

        # Spinner frames — read from module-level _COMMAND_SPINNER_FRAMES in cli.py
        self._spinner_frames: tuple[str, ...] = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

        # Whether to use HermesInput (step 5) or interim TextArea
        self._use_hermes_input = True

    # --- Compose ---

    def compose(self) -> ComposeResult:
        yield OutputPanel(id="output-panel")
        with Vertical(id="overlay-layer"):
            yield ClarifyWidget(id="clarify")
            yield ApprovalWidget(id="approval")
            yield SudoWidget(id="sudo")
            yield SecretWidget(id="secret")
        yield HintBar(id="hint-bar")
        yield ImageBar(id="image-bar")
        yield TitledRule(title="⚕ Hermes", id="input-rule")

        if self._use_hermes_input:
            from hermes_cli.tui.input_widget import HermesInput as _HI
            yield _HI(id="input-area")
        else:
            yield TextArea(id="input-area")

        yield PlainRule(id="input-rule-bottom")
        yield VoiceStatusBar(id="voice-status")
        yield StatusBar(id="status-bar")

    # --- Lifecycle ---

    def on_mount(self) -> None:
        self._event_loop = asyncio.get_running_loop()
        self._consume_output()  # starts the @work consumer
        self.set_interval(0.1, self._tick_spinner)
        # Focus the input bar so the user can type immediately
        try:
            self.query_one("#input-area").focus()
        except NoMatches:
            pass
        if self._startup_fn is not None:
            threading.Thread(target=self._startup_fn, daemon=True).start()

    # --- Output consumer (bounded queue → RichLog) ---

    @work(exclusive=True)
    async def _consume_output(self) -> None:
        """Async worker consuming the output queue.

        Runs on the Textual event loop. ``@work`` with no ``thread=True``
        means this is an async coroutine worker — correct for awaiting
        the asyncio.Queue.
        """
        while True:
            chunk = await self._output_queue.get()
            if chunk is None:
                # Sentinel: flush live line and stay alive for next turn
                try:
                    self.query_one(OutputPanel).flush_live()
                except NoMatches:
                    pass
                continue
            try:
                panel = self.query_one(OutputPanel)
                panel.live_line.append(chunk)
                self.call_after_refresh(panel.scroll_end, animate=False)
            except NoMatches:
                pass

    # --- Thread-safe output writing ---

    def write_output(self, text: str) -> None:
        """Thread-safe: enqueue text for the output consumer.

        Uses ``call_soon_threadsafe`` as the safe default. On CPython,
        ``put_nowait`` directly is also safe (GIL-atomic deque.append),
        but we use the safe path by default.
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
        except asyncio.QueueFull:
            pass  # Backpressure: UI is 4096 chunks behind — drop rather than OOM
        except RuntimeError:
            pass  # Event loop closed

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

        frames = self._spinner_frames
        if frames:
            self._spinner_idx = (self._spinner_idx + 1) % len(frames)
            frame = frames[self._spinner_idx]
        else:
            frame = ""

        hint_suffix = self._build_hint_text()
        spinner_display = f"{frame} {hint_suffix}" if frame else hint_suffix

        # Show spinner in input field
        try:
            inp = self.query_one("#input-area")
            if hasattr(inp, "spinner_text"):
                inp.spinner_text = spinner_display
        except NoMatches:
            pass

        # Also update HintBar for overlay countdowns
        try:
            self.query_one(HintBar).hint = hint_suffix if any(
                getattr(self, attr) is not None
                for attr in ("approval_state", "clarify_state", "sudo_state", "secret_state")
            ) else ""
        except NoMatches:
            pass

    def _build_hint_text(self) -> str:
        """Build the hint suffix shown beside the spinner.

        Reads overlay deadlines and agent state to assemble context hints
        (e.g. " — waiting for approval (12s)"). Extracts the logic from
        the get_hint_text() closure (cli.py:8258).
        """
        parts: list[str] = []
        label_text = getattr(self, "spinner_label", "")
        if label_text:
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

    # --- Reactive watchers ---

    def watch_agent_running(self, value: bool) -> None:
        try:
            widget = self.query_one("#input-area")
            widget.disabled = value
            if not value and hasattr(widget, "spinner_text"):
                widget.spinner_text = ""
        except NoMatches:
            pass
        # New turn starting — create a new MessagePanel
        if value:
            try:
                self.query_one(OutputPanel).new_message()
            except NoMatches:
                pass
        # Clear hint bar when agent stops
        if not value and not self.command_running:
            try:
                self.query_one(HintBar).hint = ""
            except NoMatches:
                pass

    def watch_clarify_state(self, value: ChoiceOverlayState | None) -> None:
        try:
            w = self.query_one(ClarifyWidget)
            w.display = value is not None
            if value is not None:
                w.update(value)
        except NoMatches:
            pass

    def watch_approval_state(self, value: ChoiceOverlayState | None) -> None:
        try:
            w = self.query_one(ApprovalWidget)
            w.display = value is not None
            if value is not None:
                w.update(value)
        except NoMatches:
            pass

    def watch_sudo_state(self, value: SecretOverlayState | None) -> None:
        try:
            w = self.query_one(SudoWidget)
            w.display = value is not None
            if value is not None:
                w.update(value)
        except NoMatches:
            pass

    def watch_secret_state(self, value: SecretOverlayState | None) -> None:
        try:
            w = self.query_one(SecretWidget)
            w.display = value is not None
            if value is not None:
                w.update(value)
        except NoMatches:
            pass

    def watch_voice_mode(self, value: bool) -> None:
        try:
            self.query_one(VoiceStatusBar).set_class(value, "active")
        except NoMatches:
            pass

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

    # --- Reasoning panel helpers (called via call_from_thread) ---

    def _current_reasoning(self) -> ReasoningPanel | None:
        """Return the ReasoningPanel of the current MessagePanel, or None."""
        try:
            msg = self.query_one(OutputPanel).current_message
            return msg.reasoning if msg is not None else None
        except NoMatches:
            return None

    def open_reasoning(self, title: str = "Reasoning") -> None:
        """Open the reasoning panel. Safe to call from any thread via call_from_thread."""
        rp = self._current_reasoning()
        if rp is not None:
            rp.open_box(title)

    def append_reasoning(self, delta: str) -> None:
        """Append reasoning delta. Safe to call from any thread via call_from_thread."""
        rp = self._current_reasoning()
        if rp is not None:
            rp.append_delta(delta)

    def close_reasoning(self) -> None:
        """Close the reasoning panel. Safe to call from any thread via call_from_thread."""
        rp = self._current_reasoning()
        if rp is not None:
            rp.close_box()

    # --- Theme / skin system ---

    def get_css_variables(self) -> dict[str, str]:
        """Merge runtime skin overrides into Textual's CSS variable resolution.

        Confirmed stable: ``App.get_css_variables() -> dict[str, str]`` is
        unchanged from Textual 1.0 through 8.x.
        """
        base = super().get_css_variables()
        # _skin_vars may not exist yet if called during super().__init__()
        skin = getattr(self, "_skin_vars", {})
        return {**base, **skin}

    def apply_skin(self, skin_vars: dict[str, str]) -> None:
        """Apply a skin dict as CSS variable overrides.

        Safe to call via ``call_from_thread``. Keys must be valid Textual
        CSS variable names (e.g., ``"primary"``, ``"background"``).
        """
        self._skin_vars = skin_vars
        try:
            self.refresh_css()
        except Exception:
            logger.warning("Failed to apply skin CSS variables", exc_info=True)

    # --- Key bindings for overlays and interrupt ---

    def on_key(self, event: Any) -> None:
        """Global key handler for overlay navigation and agent interrupt."""
        import time as _time

        key = event.key

        # --- Ctrl+C / Escape: interrupt agent or cancel overlays ---
        if key in ("ctrl+c", "escape"):
            # Cancel active overlays first (ctrl+c denies, escape cancels)
            for state_attr in ("approval_state", "clarify_state"):
                state: ChoiceOverlayState | None = getattr(self, state_attr)
                if state is not None:
                    state.response_queue.put("deny" if key == "ctrl+c" else None)
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

            # Interrupt running agent
            if self.agent_running and hasattr(self.cli, "agent") and self.cli.agent:
                now = _time.time()
                last = getattr(self, "_last_ctrl_c_time", 0.0)

                if key == "ctrl+c" and now - last < 2.0:
                    # Double ctrl+c within 2s → force exit
                    self.exit()
                    event.prevent_default()
                    return

                if key == "ctrl+c":
                    self._last_ctrl_c_time = now

                self.cli.agent.interrupt()
                # Show feedback
                try:
                    panel = self.query_one(OutputPanel)
                    from rich.text import Text
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

            # Idle ctrl+c: clear input or exit
            if key == "ctrl+c" and not self.agent_running:
                try:
                    inp = self.query_one("#input-area")
                    if hasattr(inp, "content") and inp.content:
                        inp.content = ""
                        inp.cursor_pos = 0
                    else:
                        self.exit()
                except NoMatches:
                    self.exit()
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
        """Handle input submission from HermesInput."""
        if hasattr(self, "cli") and self.cli is not None:
            text = event.value
            if hasattr(self.cli, "_pending_input"):
                self.cli._pending_input.put(text)
