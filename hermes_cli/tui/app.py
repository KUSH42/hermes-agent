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
import time as _time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import Static, TextArea
from textual import work

from hermes_cli.tui.state import (
    ChoiceOverlayState,
    OverlayState,
    SecretOverlayState,
)
from hermes_cli.tui.widgets import (
    ApprovalWidget,
    ClarifyWidget,
    CopyableRichLog,
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
    UserEchoPanel,
    VoiceStatusBar,
    _safe_widget_call,
)

if TYPE_CHECKING:
    from hermes_cli.tui.input_widget import HermesInput
    from hermes_cli.tui.path_search import Candidate, PathCandidate
    from hermes_cli.tui.tool_blocks import ToolHeader

logger = logging.getLogger(__name__)

# Always use call_soon_threadsafe for cross-thread queue access.
# asyncio.Queue is not thread-safe: put_nowait from a non-event-loop thread
# won't wake the selector, so the consumer only discovers items on the next
# timer tick rather than immediately.
_CPYTHON_FAST_PATH = False

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
    status_duration: reactive[str] = reactive("0s")

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

    # Highlighted completion candidate — drives PreviewPanel via watch_highlighted_candidate.
    # Uses reactive(None) (no type param) to avoid import cycle at class-definition time.
    highlighted_candidate: reactive = reactive(None)

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

        # Elapsed time for the current tool call — reset whenever spinner_label changes
        self._tool_start_time: float = 0.0

        # Whether to use HermesInput (step 5) or interim TextArea
        self._use_hermes_input = True

        # Browse-mode visit counter — first 3 visits show full hint, then compact
        self._browse_uses: int = 0

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
        yield TitledRule(id="input-rule", show_state=True)

        if self._use_hermes_input:
            from hermes_cli.tui.input_widget import HermesInput as _HI
            from hermes_cli.tui.completion_overlay import CompletionOverlay as _CO
            from hermes_cli.tui.path_search import PathSearchProvider as _PSP
            # CompletionOverlay must be composed BEFORE HermesInput so it sits
            # directly above the input in the natural layout flow (no dock/offset).
            yield _CO(id="completion-overlay")
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

    # --- Lifecycle ---

    def on_mount(self) -> None:
        self._event_loop = asyncio.get_running_loop()
        self._consume_output()  # starts the @work consumer
        self.set_interval(0.1, self._tick_spinner)
        self.set_interval(1.0, self._tick_duration)
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

        The ``await asyncio.sleep(0)`` after each chunk yields back to the
        event loop so that layout/refresh callbacks (e.g. processing deferred
        RichLog renders after a new MessagePanel mount) can run between chunks
        rather than piling up until the queue is fully drained.
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

        # Append per-tool elapsed time when a tool call is in progress
        if self._tool_start_time > 0:
            elapsed = _time.monotonic() - self._tool_start_time
            spinner_display = f"{spinner_display} · {elapsed:.1f}s"

        # Show spinner in overlay, hide input
        try:
            inp = self.query_one("#input-area")
            overlay = self.query_one("#spinner-overlay", Static)
            if spinner_display:
                overlay.update(Text(spinner_display, style="dim italic"))
                overlay.display = True
                inp.display = False
            else:
                overlay.display = False
                inp.display = True
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

    # --- Session duration timer ---

    def _tick_duration(self) -> None:
        """Update session duration every second."""
        cli = getattr(self, "cli", None)
        if cli is None:
            return
        session_start = getattr(cli, "session_start", None)
        if session_start is None:
            return
        try:
            from agent.usage_pricing import format_duration_compact
            elapsed = max(0.0, (datetime.now() - session_start).total_seconds())
            self.status_duration = format_duration_compact(elapsed)
        except Exception:
            pass

    # --- User message echo ---

    def echo_user_message(self, text: str, images: int = 0) -> None:
        """Mount a UserEchoPanel showing the user's submitted message.

        Called from the agent thread via ``call_from_thread`` before
        ``agent_running`` is set to True (which creates the new MessagePanel).
        """
        try:
            panel = self.query_one(OutputPanel)
            panel.mount(UserEchoPanel(text, images=images), before=panel.live_line)
            self.call_after_refresh(panel.scroll_end, animate=False)
        except NoMatches:
            pass

    # --- Reactive watchers ---

    def watch_agent_running(self, value: bool) -> None:
        try:
            widget = self.query_one("#input-area")
            widget.disabled = value
            if not value:
                if hasattr(widget, "spinner_text"):
                    widget.spinner_text = ""
                # Restore input visibility, hide spinner overlay
                widget.display = True
                try:
                    self.query_one("#spinner-overlay", Static).display = False
                except NoMatches:
                    pass
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

    def watch_spinner_label(self, value: str) -> None:
        """Reset per-tool elapsed timer whenever the spinner label changes."""
        self._tool_start_time = _time.monotonic() if value else 0.0

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

    def watch_clarify_state(self, value: ChoiceOverlayState | None) -> None:
        try:
            w = self.query_one(ClarifyWidget)
            w.display = value is not None
            if value is not None:
                w.update(value)
                self._hide_completion_overlay_if_present()
        except NoMatches:
            pass

    def watch_approval_state(self, value: ChoiceOverlayState | None) -> None:
        try:
            w = self.query_one(ApprovalWidget)
            w.display = value is not None
            if value is not None:
                w.update(value)
                self._hide_completion_overlay_if_present()
        except NoMatches:
            pass

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

    # --- ToolBlock mounting ---

    def mount_tool_block(
        self,
        label: str,
        lines: list[str],
        plain_lines: list[str],
    ) -> None:
        """Mount a ToolBlock into the current MessagePanel. Event-loop only."""
        if not lines:
            return
        from hermes_cli.tui.tool_blocks import ToolBlock as _ToolBlock
        try:
            output = self.query_one(OutputPanel)
            panel = output.current_message
            if panel is None:
                panel = output.new_message()
            panel.mount(_ToolBlock(label, lines, plain_lines))
            # Increment memoized header count to avoid O(n) query in StatusBar
            self._browse_total += 1
        except NoMatches:
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

    def watch_browse_index(self, _value: int) -> None:
        self._apply_browse_focus()

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

    def apply_skin(self, skin_vars: "dict[str, str] | Path") -> None:
        """Apply a skin as CSS variable overrides.

        Accepts either a pre-built ``dict[str, str]`` of Textual CSS variable
        names, or a ``Path`` to a JSON/YAML skin file (processed via
        ``skin_loader.load_skin``).

        Safe to call via ``call_from_thread``.
        """
        if isinstance(skin_vars, Path):
            from hermes_cli.tui.skin_loader import load_skin
            skin_vars = load_skin(skin_vars)
        self._skin_vars = skin_vars
        try:
            self.refresh_css()
        except Exception:
            logger.warning("Failed to apply skin CSS variables", exc_info=True)

    # --- Clipboard / selection helpers ---

    def _get_selected_text(self) -> str | None:
        """Return selected text from the screen, or None."""
        try:
            result = self.screen.get_selected_text()
            return result if result else None
        except Exception:
            return None

    # --- Key bindings for overlays, copy, and interrupt ---

    def on_key(self, event: Any) -> None:
        """Global key handler for overlay navigation, copy, and interrupt.

        Keybinding split:
        - ctrl+c: copy selected text → cancel overlay → clear input → exit
        - ctrl+shift+c: dedicated agent interrupt (double-press = force exit)
        - escape: cancel overlay → interrupt agent
        """
        key = event.key

        # --- ctrl+c: copy / cancel overlay / clear / exit ---
        if key == "ctrl+c":
            # Priority 1: copy selected text from output panels
            # (Input handles its own selection copy internally)
            selected = self._get_selected_text()
            if selected:
                self.copy_to_clipboard(selected)
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
                        inp.content = ""
                        inp.cursor_pos = 0
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
                        self.copy_to_clipboard(parent.copy_content())
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
        """Handle input submission from HermesInput."""
        if hasattr(self, "cli") and self.cli is not None:
            text = event.value
            if hasattr(self.cli, "_pending_input"):
                self.cli._pending_input.put(text)
