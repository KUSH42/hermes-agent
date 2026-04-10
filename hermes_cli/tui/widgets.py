"""Textual widgets for the Hermes TUI.

All widgets follow these conventions (from the migration spec):
- Widget.render() returns Text objects, never plain str (plain str = literal, no markup)
- RichLog.write() has no markup kwarg — set markup= at construction
- query_one() raises NoMatches — use _safe_widget_call during teardown
- self.size.width is 0 during compose() — don't use for layout math
- set_interval callbacks must be def, not async def (unless they contain await)
- Reactive mutable defaults use factory form: reactive(list) not reactive([])
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.app import ComposeResult, RenderResult
from textual.containers import ScrollableContainer
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, RichLog, Static

from hermes_cli.tui.state import (
    ChoiceOverlayState,
    OverlayState,
    SecretOverlayState,
)

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _safe_widget_call(app: HermesApp, widget_type: type, method: str, *args: Any) -> None:
    """Query a widget and call a method on it, swallowing NoMatches during teardown.

    Both the query and the method call execute on the event loop (the DOM is
    owned by the event loop thread). Callers from other threads must wrap this
    in ``app.call_from_thread(_safe_widget_call, app, ...)``.
    """
    try:
        getattr(app.query_one(widget_type), method)(*args)
    except NoMatches:
        pass  # widget removed during teardown — safe to ignore


# ---------------------------------------------------------------------------
# Output pipeline (Step 1)
# ---------------------------------------------------------------------------

class LiveLineWidget(Widget):
    """Renders the current in-progress streaming chunk before it is committed.

    Accumulates text via :meth:`append`. When a newline arrives, all complete
    lines are committed to the parent OutputPanel's RichLog and only the
    trailing partial line remains in the buffer.
    """

    DEFAULT_CSS = "LiveLineWidget { height: auto; }"

    _buf: reactive[str] = reactive("", repaint=True)

    def render(self) -> RenderResult:
        return Text.from_ansi(self._buf) if self._buf else Text("")

    def append(self, chunk: str) -> None:
        """Append *chunk*; commit complete lines to the current MessagePanel's RichLog."""
        self._buf += chunk
        if "\n" in self._buf:
            lines = self._buf.split("\n")
            try:
                panel = self.app.query_one(OutputPanel)
                msg = panel.current_message
                if msg is None:
                    msg = panel.new_message()
                rl = msg.response_log
                msg.show_response_rule()
                for committed in lines[:-1]:
                    rl.write(Text.from_ansi(committed))
                # If writes were deferred (RichLog size not yet known),
                # schedule a layout refresh so the panel expands once the
                # deferred renders are processed on the next resize.
                if rl._deferred_renders:
                    self.call_after_refresh(msg.refresh, layout=True)
            except NoMatches:
                pass
            self._buf = lines[-1]


class MessagePanel(Widget):
    """Groups a response TitledRule + ReasoningPanel + response RichLog for one assistant turn."""

    DEFAULT_CSS = """
    MessagePanel {
        height: auto;
    }
    MessagePanel RichLog {
        height: auto;
        overflow-y: hidden;
        overflow-x: hidden;
    }
    MessagePanel TitledRule {
        display: none;
    }
    MessagePanel TitledRule.visible {
        display: block;
    }
    """

    _msg_counter: int = 0

    def __init__(self, **kwargs: Any) -> None:
        MessagePanel._msg_counter += 1
        self._msg_id = MessagePanel._msg_counter
        self._response_rule = TitledRule(title="⚕ Hermes", id=f"response-rule-{self._msg_id}")
        self._reasoning_panel = ReasoningPanel(id=f"reasoning-{self._msg_id}")
        self._response_log = RichLog(
            markup=False, highlight=False, wrap=True,
            id=f"response-{self._msg_id}",
        )
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        yield self._response_rule
        yield self._reasoning_panel
        yield self._response_log

    def show_response_rule(self) -> None:
        """Show the response title rule (called when first content arrives)."""
        self._response_rule.add_class("visible")

    @property
    def reasoning(self) -> ReasoningPanel:
        return self._reasoning_panel

    @property
    def response_log(self) -> RichLog:
        return self._response_log


class OutputPanel(ScrollableContainer):
    """Scrollable output area containing MessagePanels + live in-progress line."""

    DEFAULT_CSS = """
    OutputPanel {
        height: 1fr;
        overflow-y: auto;
        overflow-x: hidden;
    }
    """

    def compose(self) -> ComposeResult:
        yield LiveLineWidget(id="live-line")

    @property
    def live_line(self) -> LiveLineWidget:
        return self.query_one(LiveLineWidget)

    @property
    def current_message(self) -> MessagePanel | None:
        """Return the most recent MessagePanel, or None."""
        panels = self.query(MessagePanel)
        return panels.last() if panels else None

    def new_message(self) -> MessagePanel:
        """Create and mount a new MessagePanel for a new turn."""
        panel = MessagePanel()
        self.mount(panel, before=self.live_line)
        return panel

    def flush_live(self) -> None:
        """Commit any in-progress buffered line to current message's RichLog."""
        live = self.live_line
        if live._buf:
            msg = self.current_message
            if msg is None:
                msg = self.new_message()
            msg.show_response_rule()
            rl = msg.response_log
            rl.write(Text.from_ansi(live._buf))
            if rl._deferred_renders:
                self.call_after_refresh(msg.refresh, layout=True)
            live._buf = ""


# ---------------------------------------------------------------------------
# Reasoning panel (Step 2)
# ---------------------------------------------------------------------------

class ReasoningPanel(Widget):
    """Collapsible reasoning display with left gutter marker.

    Hidden by default via CSS ``display: none``. Toggled visible via the
    ``visible`` CSS class when reasoning output arrives. Each committed
    line is prefixed with a ``▌`` gutter marker in dim style.
    """

    GUTTER = "▌ "

    DEFAULT_CSS = """
    ReasoningPanel {
        display: none;
        height: auto;
        margin: 0 1;
    }
    ReasoningPanel.visible {
        display: block;
    }
    ReasoningPanel RichLog {
        height: auto;
        overflow-y: hidden;
        overflow-x: hidden;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        self._reasoning_log = RichLog(markup=False, highlight=False, wrap=True, id="reasoning-log")
        super().__init__(**kwargs)
        self._live_buf = ""

    def compose(self) -> ComposeResult:
        yield self._reasoning_log

    def _gutter_line(self, content: str) -> Text:
        """Build a dim gutter-prefixed line for the reasoning log."""
        t = Text()
        t.append(self.GUTTER, style="dim")
        t.append(content, style="dim italic")
        return t

    def open_box(self, title: str) -> None:
        """Show the reasoning panel."""
        self._live_buf = ""
        self.add_class("visible")
        # Trigger layout refresh so parent recalculates height after
        # deferred renders are processed on the next resize event.
        self.call_after_refresh(self.refresh, layout=True)

    def append_delta(self, text: str) -> None:
        """Append a reasoning text delta, streaming character-by-character.

        Buffers partial lines and commits on newlines so the RichLog
        shows complete lines while still updating in real-time.
        Each committed line gets a ``▌`` gutter prefix.
        """
        self._live_buf += text
        log = self._reasoning_log
        wrote = False
        # Commit complete lines
        while "\n" in self._live_buf:
            line, self._live_buf = self._live_buf.split("\n", 1)
            log.write(self._gutter_line(line))
            wrote = True
        if wrote and log._deferred_renders:
            self.call_after_refresh(self.refresh, layout=True)

    def close_box(self) -> None:
        """Hide the reasoning panel, flush remaining buffer."""
        # Flush any partial line
        buf = self._live_buf
        if buf:
            self._reasoning_log.write(self._gutter_line(buf))
            self._live_buf = ""
        self.remove_class("visible")
        self.call_after_refresh(self.refresh, layout=True)


# ---------------------------------------------------------------------------
# Titled rule (separator with embedded title)
# ---------------------------------------------------------------------------

def _fade_rule(count: int, start_hex: str, end_hex: str) -> Text:
    """Build a run of ``─`` chars that fade from *start_hex* to *end_hex*.

    Uses Rich's ``blend_rgb`` for interpolation — no extra dependencies.
    """
    from rich.color import Color, blend_rgb

    if count <= 0:
        return Text()
    c_start = Color.parse(start_hex).get_truecolor()
    c_end = Color.parse(end_hex).get_truecolor()
    t = Text()
    for i in range(count):
        factor = i / max(count - 1, 1)
        c = blend_rgb(c_start, c_end, factor)
        t.append("─", style=f"rgb({c.red},{c.green},{c.blue})")
    return t


class TitledRule(Widget):
    """Horizontal rule with an embedded title and fading rule chars."""

    DEFAULT_CSS = """
    TitledRule {
        height: 1;
    }
    """

    title_text: reactive[str] = reactive("Hermes")

    def __init__(
        self,
        title: str = "Hermes",
        fade_start: str = "#555555",
        fade_end: str = "#2A2A2A",
        accent: str = "#FFD700",
        title_color: str = "#B8860B",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.title_text = title
        self._fade_start = fade_start
        self._fade_end = fade_end
        self._accent = accent
        self._title_color = title_color

    def render(self) -> RenderResult:
        w = self.size.width
        title = self.title_text
        # Split title into accent char (first non-space) + rest
        # e.g. "⚕ Hermes" → accent="⚕", rest=" Hermes"
        parts = title.split(" ", 1)
        accent_char = parts[0] if parts else ""
        rest = (" " + parts[1]) if len(parts) > 1 else ""

        label_len = len(f" {title} ")
        left_pad = 2
        right = max(0, w - left_pad - label_len)
        t = Text()
        # Left pad: fade in (end → start)
        t.append_text(_fade_rule(left_pad, self._fade_end, self._fade_start))
        # Title: accent char in bright accent, rest in title_color
        t.append(" ")
        t.append(accent_char, style=f"bold {self._accent}")
        t.append(f"{rest} ", style=f"{self._title_color}")
        # Right fill: fade out (start → end)
        t.append_text(_fade_rule(right, self._fade_start, self._fade_end))
        return t


class PlainRule(Widget):
    """Plain horizontal rule that fades out."""

    DEFAULT_CSS = """
    PlainRule {
        height: 1;
    }
    """

    def __init__(self, fade_start: str = "#555555", fade_end: str = "#2A2A2A", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._fade_start = fade_start
        self._fade_end = fade_end

    def render(self) -> RenderResult:
        return _fade_rule(self.size.width, self._fade_start, self._fade_end)


# ---------------------------------------------------------------------------
# Hint bar + spinner (Step 3)
# ---------------------------------------------------------------------------

class HintBar(Static):
    """Single-line hint / countdown display below the overlay layer.

    ``HermesApp`` has NO ``hint_text`` reactive. ``HintBar.hint`` is the
    single source of truth. ``_tick_spinner`` writes to
    ``app.query_one(HintBar).hint`` directly.
    """

    DEFAULT_CSS = """
    HintBar {
        height: 1;
        display: none;
    }
    HintBar.visible {
        display: block;
    }
    """

    hint: reactive[str] = reactive("")

    def watch_hint(self, value: str) -> None:
        self.update(value)
        if value:
            self.add_class("visible")
        else:
            self.remove_class("visible")


# ---------------------------------------------------------------------------
# Status bar (Step 3)
# ---------------------------------------------------------------------------

class StatusBar(Widget):
    """Bottom status bar showing model, tokens, and duration.

    Reads directly from the App's reactives — no duplicated state.
    Uses ``self.watch(self.app, attr, self.refresh)`` for all three
    reactive fields so any change triggers a re-render.

    RenderResult is imported from textual.app (not textual.widget).
    """

    DEFAULT_CSS = "StatusBar { height: 1; dock: bottom; }"

    def on_mount(self) -> None:
        self.watch(self.app, "status_tokens", self._on_status_change)
        self.watch(self.app, "status_model", self._on_status_change)
        self.watch(self.app, "status_duration", self._on_status_change)

    def _on_status_change(self, _value: object = None) -> None:
        self.refresh()

    def render(self) -> RenderResult:
        app = self.app
        t = Text()
        t.append(getattr(app, "status_model", ""), style="dim")
        tokens = getattr(app, "status_tokens", 0)
        duration = getattr(app, "status_duration", 0.0)
        t.append(f"  {tokens} tok  {duration:.1f}s")
        return t


# ---------------------------------------------------------------------------
# Voice status bar (Step 3)
# ---------------------------------------------------------------------------

class VoiceStatusBar(Widget):
    """Persistent voice recording status indicator.

    Hidden by default; toggled via the ``active`` CSS class driven by
    ``HermesApp.watch_voice_mode``.
    """

    DEFAULT_CSS = """
    VoiceStatusBar {
        display: none;
        height: 1;
        color: $error;
    }
    VoiceStatusBar.active {
        display: block;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="voice-status-text")

    def update_status(self, text: str) -> None:
        try:
            self.query_one("#voice-status-text", Static).update(text)
        except NoMatches:
            pass


# ---------------------------------------------------------------------------
# Image bar (Step 3)
# ---------------------------------------------------------------------------

class ImageBar(Static):
    """Displays attached image filenames; hidden when empty."""

    DEFAULT_CSS = """
    ImageBar {
        display: none;
        height: auto;
    }
    """

    def update_images(self, images: list) -> None:
        """Update the displayed image list and toggle visibility."""
        if images:
            self.display = True
            names = ", ".join(getattr(img, "name", str(img)) for img in images)
            self.update(f"[dim]📎 {names}[/dim]")
        else:
            self.display = False
            self.update("")


# ---------------------------------------------------------------------------
# CountdownMixin (Step 4)
# ---------------------------------------------------------------------------

class CountdownMixin:
    """Shared countdown logic for timed overlays.

    Subclasses must define:
      - ``_state_attr``: str — the HermesApp reactive attribute name
      - ``_timeout_response``: value to put on response_queue on expiry
      - ``_countdown_prefix``: str — used for countdown widget ID
      - A ``Static`` with ``id="{prefix}-countdown"`` in compose()
    """

    _state_attr: str
    _timeout_response: object = None
    _countdown_prefix: str = ""

    def _start_countdown(self) -> None:
        """Call from on_mount(). Starts the 1-second tick timer."""
        self.set_interval(1.0, self._tick_countdown)

    def _tick_countdown(self) -> None:
        """Tick handler — update countdown display and auto-resolve on expiry.

        Runs ON the event loop (set_interval callback), so direct mutation is
        correct; call_from_thread would be wrong here.
        """
        state: OverlayState | None = getattr(self.app, self._state_attr)
        if state is None:
            return
        countdown_id = f"#{self._countdown_prefix}-countdown"
        try:
            self.query_one(countdown_id, Static).update(
                f"[dim]({state.remaining}s)[/dim]"
            )
        except NoMatches:
            pass
        if state.expired:
            self._resolve_timeout(state)

    def _resolve_timeout(self, state: OverlayState) -> None:
        """Put timeout response on queue and clear state. Runs on event loop."""
        state.response_queue.put(self._timeout_response)
        setattr(self.app, self._state_attr, None)


# ---------------------------------------------------------------------------
# Clarify widget (Step 4)
# ---------------------------------------------------------------------------

class ClarifyWidget(CountdownMixin, Widget):
    """Choice overlay with countdown for clarification questions."""

    _state_attr = "clarify_state"
    _timeout_response = None
    _countdown_prefix = "clarify"

    DEFAULT_CSS = """
    ClarifyWidget {
        display: none;
        border: tall $warning;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="clarify-question")
        yield Static("", id="clarify-choices")
        yield Static("", id="clarify-countdown")

    def on_mount(self) -> None:
        self._start_countdown()

    def update(self, state: ChoiceOverlayState) -> None:
        """Populate content from typed state and make visible."""
        self.display = True
        try:
            self.query_one("#clarify-question", Static).update(state.question)
            choices_markup = "\n".join(
                f"[bold]→[/bold] {c}" if i == state.selected else f"  {c}"
                for i, c in enumerate(state.choices)
            )
            self.query_one("#clarify-choices", Static).update(choices_markup)
        except NoMatches:
            pass

    def hide(self) -> None:
        self.display = False


# ---------------------------------------------------------------------------
# Approval widget (Step 4)
# ---------------------------------------------------------------------------

class ApprovalWidget(CountdownMixin, Widget):
    """Choice overlay for dangerous-command approval with 'deny' timeout."""

    _state_attr = "approval_state"
    _timeout_response = "deny"
    _countdown_prefix = "approval"

    DEFAULT_CSS = """
    ApprovalWidget {
        display: none;
        border: tall $error;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="approval-question")
        yield Static("", id="approval-choices")
        yield Static("", id="approval-countdown")

    def on_mount(self) -> None:
        self._start_countdown()

    def update(self, state: ChoiceOverlayState) -> None:
        """Populate content from typed state."""
        self.display = True
        try:
            self.query_one("#approval-question", Static).update(state.question)
            choices_markup = "\n".join(
                f"[bold]→[/bold] {c}" if i == state.selected else f"  {c}"
                for i, c in enumerate(state.choices)
            )
            self.query_one("#approval-choices", Static).update(choices_markup)
        except NoMatches:
            pass

    def hide(self) -> None:
        self.display = False


# ---------------------------------------------------------------------------
# Sudo widget (Step 4)
# ---------------------------------------------------------------------------

class SudoWidget(CountdownMixin, Widget):
    """Password input overlay for sudo commands with countdown."""

    _state_attr = "sudo_state"
    _timeout_response = None
    _countdown_prefix = "sudo"

    DEFAULT_CSS = """
    SudoWidget {
        display: none;
        border: tall $warning;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="sudo-prompt")
        yield Input(password=True, placeholder="sudo password", id="sudo-input")
        yield Static("", id="sudo-countdown")

    def on_mount(self) -> None:
        self._start_countdown()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """User pressed Enter in the password field."""
        state = getattr(self.app, "sudo_state", None)
        if state is None:
            return
        state.response_queue.put(event.value)
        self.app.sudo_state = None

    def update(self, state: SecretOverlayState) -> None:
        """Populate and show the sudo prompt."""
        self.display = True
        try:
            self.query_one("#sudo-prompt", Static).update(state.prompt)
            inp = self.query_one("#sudo-input", Input)
            inp.clear()
            inp.focus()
        except NoMatches:
            pass

    def hide(self) -> None:
        self.display = False


# ---------------------------------------------------------------------------
# Secret widget (Step 4)
# ---------------------------------------------------------------------------

class SecretWidget(CountdownMixin, Widget):
    """Captures a secret value (API key, token, etc.) with masked input."""

    _state_attr = "secret_state"
    _timeout_response = None
    _countdown_prefix = "secret"

    DEFAULT_CSS = """
    SecretWidget {
        display: none;
        border: tall $warning;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="secret-prompt")
        yield Input(password=True, placeholder="enter secret value", id="secret-input")
        yield Static("", id="secret-countdown")

    def on_mount(self) -> None:
        self._start_countdown()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """User pressed Enter in the secret field."""
        state = getattr(self.app, "secret_state", None)
        if state is None:
            return
        state.response_queue.put(event.value)
        self.app.secret_state = None

    def update(self, state: SecretOverlayState) -> None:
        """Populate and show the secret prompt."""
        self.display = True
        try:
            self.query_one("#secret-prompt", Static).update(state.prompt)
            inp = self.query_one("#secret-input", Input)
            inp.clear()
            inp.focus()
        except NoMatches:
            pass

    def hide(self) -> None:
        self.display = False
