"""Overlay/dialog classes for the Hermes TUI.

Contains: CountdownMixin, ClarifyWidget, ApprovalWidget, SudoWidget,
SecretWidget, UndoConfirmOverlay, history-search types and helpers,
TurnResultItem, KeymapOverlay, HistorySearchOverlay.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Static

from hermes_cli.tui.animation import lerp_color
from .renderers import CopyableRichLog
from hermes_cli.tui.state import (
    ChoiceOverlayState,
    OverlayState,
    SecretOverlayState,
    UndoOverlayState,
)

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp


# ---------------------------------------------------------------------------
# CountdownMixin
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
    # Stored handle so we can stop/restart the timer for pause/resume.
    _countdown_timer: "object | None" = None
    # Pause/resume tracking (P0-B: multi-overlay stacking).
    _was_paused: bool = False
    _pause_start: float = 0.0
    # Initial total seconds — set from state.remaining in each widget's update().
    # Used to compute the ▓▒░ fill ratio.
    _countdown_total: int = 30
    # Wall-clock start time for smooth lerp color (set when countdown begins).
    _countdown_start_time: float = 0.0

    def _start_countdown(self) -> None:
        """Call from on_mount(). Starts the 1-second tick timer."""
        if self._countdown_timer is not None:
            return  # already running
        import time as _time
        self._countdown_start_time = _time.monotonic()
        self._countdown_timer = self.set_interval(1.0, self._tick_countdown)

    def on_unmount(self) -> None:
        """Safety net: cancel countdown timer on removal."""
        if self._countdown_timer is not None:
            self._countdown_timer.stop()
            self._countdown_timer = None

    def pause_countdown(self) -> None:
        """Pause the countdown timer (P0-B: multi-overlay stacking).

        Stops the tick without auto-resolving; call ``resume_countdown()`` to
        restart and compensate the deadline for time spent paused.
        """
        if self._countdown_timer is not None:
            self._countdown_timer.stop()
            self._countdown_timer = None
        self._was_paused = True
        self._pause_start = time.monotonic()

    def resume_countdown(self) -> None:
        """Resume a previously paused countdown.

        Extends the deadline by the time spent paused so the user is not
        penalised for an interruption they did not initiate.
        """
        if not self._was_paused:
            return
        state: "OverlayState | None" = getattr(
            getattr(self, "app", None), self._state_attr, None
        )
        if state is not None:
            elapsed_paused = time.monotonic() - self._pause_start
            state.deadline += elapsed_paused
        self._was_paused = False
        self._start_countdown()

    def _build_countdown_strip(self, remaining: int, total: int, width: int) -> "Text":
        """Build a ▓▒░ progress strip for the countdown display.

        Spec §2.3: ▓ = remaining time (left, colored); ░ = elapsed (right, dim).
        Color phases: >5s → $primary; 1-5s → lerp($primary→$warning); ≤1s → $error.
        """
        # Bar color phase
        if remaining > 5:
            bar_color = "#5f87d7"  # $primary calm
        elif remaining > 1:
            t = (5.0 - remaining) / 4.0
            bar_color = lerp_color("#5f87d7", "#FFA726", t)
        else:
            bar_color = "#ef5350"  # $error critical

        import os as _os
        no_unicode = _os.environ.get("HERMES_NO_UNICODE", "")
        from rich.style import Style
        label = f"{remaining:>2}s"
        label_width = len(label) + 1   # leading space + label
        bar_width = max(8, width - label_width)

        result = Text()
        # Urgency glyph prefix (skipped when unicode disabled)
        if not no_unicode:
            if remaining <= 1:
                result.append("⚠⚠ ", Style(color="#ef5350", bold=True))
            elif remaining <= 3:
                result.append("⚠ ", Style(color="#FFA726", bold=True))

        ratio = min(1.0, remaining / max(1, total))
        filled_cells = int(bar_width * ratio)

        meniscus = min(3, filled_cells)
        heavy = max(0, filled_cells - meniscus)
        empty = max(0, bar_width - filled_cells)

        if heavy > 0:
            result.append("▓" * heavy, Style(color=bar_color))
        if meniscus > 0:
            result.append("▒" * meniscus, Style(color=bar_color))
        if empty > 0:
            result.append("░" * empty, Style(color="#6e6e6e"))
        result.append(f" {label}", Style(color="#6e6e6e"))
        return result

    def _tick_countdown(self) -> None:
        """Tick handler — update countdown display and auto-resolve on expiry.

        Runs ON the event loop (set_interval callback), so direct mutation is
        correct; call_from_thread would be wrong here.
        """
        state: "OverlayState | None" = getattr(self.app, self._state_attr)
        if state is None:
            return
        remaining = state.remaining
        countdown_id = f"#{self._countdown_prefix}-countdown"
        try:
            countdown_w = self.query_one(countdown_id, Static)
            # content_size.width may be 0 if not yet laid out; use 40 as fallback.
            bar_width = max(10, self.content_size.width)
            strip = self._build_countdown_strip(remaining, self._countdown_total, bar_width)
            countdown_w.update(strip)
        except (NoMatches, AttributeError):
            pass
        if state.expired:
            self._resolve_timeout(state)

    def _resolve_timeout(self, state: "OverlayState") -> None:
        """Put timeout response on queue and clear state. Runs on event loop."""
        state.response_queue.put(self._timeout_response)
        setattr(self.app, self._state_attr, None)


# ---------------------------------------------------------------------------
# ClarifyWidget
# ---------------------------------------------------------------------------

class ClarifyWidget(CountdownMixin, Widget, can_focus=True):
    """Choice overlay with countdown for clarification questions."""

    _state_attr = "clarify_state"
    _timeout_response = None
    _countdown_prefix = "clarify"

    DEFAULT_CSS = """
    ClarifyWidget {
        display: none;
        height: auto;
        border-top: hkey $primary 25%;
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
        self._countdown_total = max(1, state.remaining)
        try:
            self.query_one("#clarify-question", Static).update(
                f"[dim]?[/dim]  {state.question}"
            )
            choices_markup = "  ".join(
                f"[bold #FFD700]\\[ {c} ←\\][/bold #FFD700]" if i == state.selected
                else f"[dim]\\[ {c} \\][/dim]"
                for i, c in enumerate(state.choices)
            )
            self.query_one("#clarify-choices", Static).update("     " + choices_markup)
        except NoMatches:
            pass

    def hide(self) -> None:
        self.display = False


# ---------------------------------------------------------------------------
# ApprovalWidget
# ---------------------------------------------------------------------------

class ApprovalWidget(CountdownMixin, Widget, can_focus=True):
    """Choice overlay for dangerous-command approval with 'deny' timeout."""

    _state_attr = "approval_state"
    _timeout_response = "deny"
    _countdown_prefix = "approval"

    DEFAULT_CSS = """
    ApprovalWidget {
        display: none;
        height: auto;
        border-top: hkey $warning 35%;
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
        self._countdown_total = max(1, state.remaining)
        try:
            self.query_one("#approval-question", Static).update(
                f"[dim]![/dim]  {state.question}"
            )
            choices_markup = "  ".join(
                f"[bold #FFD700]\\[ {c} ←\\][/bold #FFD700]" if i == state.selected
                else f"[dim]\\[ {c} \\][/dim]"
                for i, c in enumerate(state.choices)
            )
            self.query_one("#approval-choices", Static).update("     " + choices_markup)
        except NoMatches:
            pass

    def hide(self) -> None:
        self.display = False


# ---------------------------------------------------------------------------
# SudoWidget
# ---------------------------------------------------------------------------

class SudoWidget(CountdownMixin, Widget):
    """Password input overlay for sudo commands with countdown.

    Alt+P toggles masked/unmasked peek (P1-A). The `--unmasked` CSS class is
    applied when peek is active; re-masked on next keypress, click, or blur.
    """

    _state_attr = "sudo_state"
    _timeout_response = None
    _countdown_prefix = "sudo"

    DEFAULT_CSS = """
    SudoWidget {
        display: none;
        height: auto;
        border-top: hkey $warning 35%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="sudo-prompt")
        yield Input(password=True, placeholder="enter passphrase…", id="sudo-input")
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

    def on_key(self, event: Any) -> None:
        """Alt+P toggles peek (unmask) for the password input (P1-A)."""
        if event.key == "alt+p":
            try:
                inp = self.query_one("#sudo-input", Input)
                if self.has_class("--unmasked"):
                    inp.password = True
                    self.remove_class("--unmasked")
                else:
                    inp.password = False
                    self.add_class("--unmasked")
            except NoMatches:
                pass
            event.prevent_default()

    def on_blur(self, event: Any) -> None:  # type: ignore[override]
        """Re-mask on focus loss."""
        try:
            self.query_one("#sudo-input", Input).password = True
        except NoMatches:
            pass
        self.remove_class("--unmasked")

    def update(self, state: SecretOverlayState) -> None:
        """Populate and show the sudo prompt."""
        self.display = True
        self._countdown_total = max(1, state.remaining)
        try:
            self.query_one("#sudo-prompt", Static).update(
                f"[dim]#[/dim]  {state.prompt}"
            )
            inp = self.query_one("#sudo-input", Input)
            inp.password = True
            self.remove_class("--unmasked")
            inp.clear()
            inp.focus()
        except NoMatches:
            pass

    def hide(self) -> None:
        self.display = False


# ---------------------------------------------------------------------------
# SecretWidget
# ---------------------------------------------------------------------------

class SecretWidget(CountdownMixin, Widget):
    """Captures a secret value (API key, token, etc.) with masked input.

    Alt+P toggles masked/unmasked peek (P1-A). Re-masked on blur.
    """

    _state_attr = "secret_state"
    _timeout_response = None
    _countdown_prefix = "secret"

    DEFAULT_CSS = """
    SecretWidget {
        display: none;
        height: auto;
        border-top: hkey $primary 25%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="secret-prompt")
        yield Input(password=True, placeholder="enter secret value…", id="secret-input")
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

    def on_key(self, event: Any) -> None:
        """Alt+P toggles peek (unmask) for the secret input (P1-A)."""
        if event.key == "alt+p":
            try:
                inp = self.query_one("#secret-input", Input)
                if self.has_class("--unmasked"):
                    inp.password = True
                    self.remove_class("--unmasked")
                else:
                    inp.password = False
                    self.add_class("--unmasked")
            except NoMatches:
                pass
            event.prevent_default()

    def on_blur(self, event: Any) -> None:  # type: ignore[override]
        """Re-mask on focus loss."""
        try:
            self.query_one("#secret-input", Input).password = True
        except NoMatches:
            pass
        self.remove_class("--unmasked")

    def update(self, state: SecretOverlayState) -> None:
        """Populate and show the secret prompt."""
        self.display = True
        self._countdown_total = max(1, state.remaining)
        try:
            self.query_one("#secret-prompt", Static).update(
                f"[dim]*[/dim]  {state.prompt}"
            )
            inp = self.query_one("#secret-input", Input)
            inp.password = True
            self.remove_class("--unmasked")
            inp.clear()
            inp.focus()
        except NoMatches:
            pass

    def hide(self) -> None:
        self.display = False


# ---------------------------------------------------------------------------
# UndoConfirmOverlay
# ---------------------------------------------------------------------------

class UndoConfirmOverlay(CountdownMixin, Widget):
    """Undo confirmation overlay with 10-second auto-cancel.

    Shows the user text that will be removed and waits for Y/Enter (confirm)
    or N/Escape (cancel).  CountdownMixin drives the timer tick.

    Border: all-sides ``$warning 35%`` — destructive action demands stronger
    containment signal than top-only tray modals (spec §2.4).
    """

    _state_attr = "undo_state"
    _timeout_response = "cancel"
    _countdown_prefix = "undo"

    DEFAULT_CSS = """
    UndoConfirmOverlay {
        display: none;
        height: auto;
        border: tall $warning 35%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="undo-header")
        yield Static("", id="undo-user-text")
        yield Static("", id="undo-has-checkpoint")
        yield Static("", id="undo-choices")
        yield Static("", id="undo-countdown")

    def on_mount(self) -> None:
        self._start_countdown()

    def update(self, state: UndoOverlayState) -> None:
        """Populate content from typed state and make visible."""
        self.display = True
        self._countdown_total = max(1, state.remaining)
        try:
            self.query_one("#undo-header", Static).update(
                "[dim]<[/dim]  Undo last turn?"
            )
            echo_raw = state.user_text
            echo_text = echo_raw[:80] + "…" if len(echo_raw) > 80 else echo_raw
            self.query_one("#undo-user-text", Static).update(
                "     This will remove the assistant's last response and re-queue:\n"
                f'     [dim italic]"{echo_text}"[/dim italic]'
            )
            checkpoint_text = (
                "     [dim]+ filesystem checkpoint revert[/dim]"
                if state.has_checkpoint else ""
            )
            self.query_one("#undo-has-checkpoint", Static).update(checkpoint_text)
            self.query_one("#undo-choices", Static).update(
                "     [bold]\\[y][/bold] Undo and retry    "
                "[bold]\\[n][/bold] Cancel"
            )
        except NoMatches:
            pass

    def hide(self) -> None:
        self.display = False


# ---------------------------------------------------------------------------
# History Search types + helpers
# ---------------------------------------------------------------------------

@dataclass
class _TurnEntry:
    """Metadata for one indexed turn (frozen snapshot; never mutated)."""
    panel: "Any"  # MessagePanel — avoid circular import
    index: int          # 1-based (turn 1 = first ever)
    user_text: str      # paired text from preceding UserMessagePanel
    assistant_text: str # full plain assistant prose from the panel
    search_text: str    # combined contiguous-search haystack
    display: str        # user-facing row label


@dataclass(frozen=True, slots=True)
class TurnCandidate:
    """Candidate for fuzzy_rank() carrying a _TurnEntry reference.

    Re-implements Candidate fields inline (rather than subclassing) to avoid
    the Python slots-inheritance restriction when both base and child are
    frozen+slotted dataclasses across different module scopes.
    fuzzy_rank() only reads .display and calls dataclasses.replace(), which
    works fine on this standalone frozen dataclass.
    """
    display: str
    score: int = 0
    match_spans: tuple[tuple[int, int], ...] = ()
    entry: "_TurnEntry | None" = field(default=None)


@dataclass(frozen=True)
class _SearchResult:
    """Result from _substring_search — carries match metadata for rendering."""
    entry: _TurnEntry
    match_spans: tuple[tuple[int, int], ...]  # relative to search_text
    first_match_offset: int


def _substring_search(
    query: str,
    entries: list[_TurnEntry],
    limit: int = 20,
) -> list[_SearchResult]:
    """Casefolded contiguous substring search with span tracking.

    Searches combined user+assistant text.  Returns results sorted by:
    1. Match count × 10 + word-boundary bonus (5) + char-0 bonus (2)
    2. Recency (newer wins on tie)
    """
    needle = query.casefold()
    results: list[tuple[_TurnEntry, list[tuple[int, int]], int]] = []
    for entry in entries:
        haystack = entry.search_text.casefold()
        spans: list[tuple[int, int]] = []
        offset = 0
        while True:
            pos = haystack.find(needle, offset)
            if pos == -1:
                break
            spans.append((pos, pos + len(needle)))
            offset = pos + len(needle)  # no overlap
        if spans:
            score = len(spans) * 10
            first = spans[0][0]
            if first == 0 or entry.search_text[first - 1] in " \n\t/._-":
                score += 5
            results.append((entry, spans, score))
    results.sort(key=lambda r: (-r[2], -r[0].index))
    return [
        _SearchResult(entry=e, match_spans=tuple(s), first_match_offset=s[0][0])
        for e, s, _ in results[:limit]
    ]


def _highlight_spans(text: str, spans: tuple[tuple[int, int], ...]) -> str:
    """Wrap matched character spans in Rich markup for accent highlighting."""
    if not spans:
        return _escape_markup(text)
    parts: list[str] = []
    prev = 0
    for start, end in sorted(spans):
        if start > prev:
            parts.append(_escape_markup(text[prev:start]))
        parts.append(f"[bold $accent]{_escape_markup(text[start:end:])}[/]")
        prev = end
    if prev < len(text):
        parts.append(_escape_markup(text[prev:]))
    return "".join(parts)


def _escape_markup(text: str) -> str:
    """Escape Rich markup brackets so raw user text renders literally."""
    return text.replace("[", r"\[").replace("]", r"\]")


def _extract_snippet(
    search_text: str,
    match_spans: tuple[tuple[int, int], ...],
    context_chars: int = 40,
) -> str:
    """Extract a context window around the first match with accent highlighting."""
    if not match_spans:
        raw = search_text[:80]
        suffix = "…" if len(search_text) > 80 else ""
        return _escape_markup(raw) + suffix
    first_start = match_spans[0][0]
    last_end = match_spans[-1][1]
    window_start = max(0, first_start - context_chars)
    window_end = min(len(search_text), last_end + context_chars)
    # Collapse to single line — strip internal newlines for compact display
    snippet_raw = search_text[window_start:window_end].replace("\n", " ")
    # Offset spans into local snippet coordinates
    local_spans = tuple(
        (s - window_start, e - window_start)
        for s, e in match_spans
        if s >= window_start and e <= window_end
    )
    prefix = "…" if window_start > 0 else ""
    suffix = "…" if window_end < len(search_text) else ""
    return prefix + _highlight_spans(snippet_raw, local_spans) + suffix


def _turn_result_label(entry: "_TurnEntry | None") -> str:
    """Build the Rich-markup label for a TurnResultItem row."""
    if not entry:
        return ""
    max_width = 76
    first = entry.display or "(no content)"
    truncated = first[:max_width] + "…" if len(first) > max_width else first
    return f"[dim]\\[turn {entry.index:>3}][/dim]  {truncated}"


def _build_result_label(result: "_SearchResult | None") -> str:
    """Build multi-line Rich-markup label for TurnResultItem with match context."""
    if result is None:
        return ""
    entry = result.entry
    # Row 1: turn header + first line of user text (escaped)
    user_first = entry.user_text.split("\n", 1)[0]
    if len(user_first) > 72:
        user_first = user_first[:72] + "…"
    header = f"[dim]\\[turn {entry.index:>3}][/dim]  {_escape_markup(user_first)}"
    # Row 2: context snippet with match highlighting
    snippet = _extract_snippet(entry.search_text, result.match_spans)
    return f"{header}\n  {snippet}"


# ---------------------------------------------------------------------------
# TurnResultItem
# ---------------------------------------------------------------------------

class TurnResultItem(Static):
    """Single row in the history search result list — multi-line with match context."""

    DEFAULT_CSS = """
    TurnResultItem { height: auto; min-height: 2; max-height: 4; padding: 0 1; }
    TurnResultItem.--selected { background: $accent 20%; }
    TurnResultItem:hover { background: $accent 10%; }
    """

    def __init__(self, result: "_SearchResult | None", **kwargs: Any) -> None:
        self._result = result
        self._entry = result.entry if result else None
        super().__init__(_build_result_label(result), **kwargs)

    def update_from(self, result: "_SearchResult | None") -> None:
        """Update in-place without DOM add/remove."""
        self._result = result
        self._entry = result.entry if result else None
        self.update(_build_result_label(result))

    def on_click(self, event: Any) -> None:
        """Clicking a result row jumps to the turn; shift+click range-selects."""
        if event.button != 1:
            return
        try:
            overlay = self.app.query_one(HistorySearchOverlay)
        except NoMatches:
            return
        idx = self._entry.index if self._entry is not None else None
        if idx is None:
            return
        if getattr(event, "shift", False) and getattr(overlay, "_last_click_idx", None) is not None:
            # Range select from last click to here
            start = overlay._last_click_idx
            lo, hi = sorted([start, idx])
            shift_sel = set(range(lo, hi + 1))
            overlay._shift_selected = shift_sel
            for item in overlay.query(TurnResultItem):
                item_idx = item._entry.index if item._entry is not None else -1
                item.set_class(item_idx in shift_sel, "--selected")
        else:
            overlay._last_click_idx = idx
            overlay._shift_selected = set()
            for item in overlay.query(TurnResultItem):
                item.set_class(False, "--selected")
            overlay.action_jump_to(self._entry, self._result)


# ---------------------------------------------------------------------------
# KeymapOverlay
# ---------------------------------------------------------------------------

class KeymapOverlay(Widget):
    """Keyboard-shortcut reference card.  Toggle with F1; dismiss with Escape, F1, or q."""

    DEFAULT_CSS = """
    KeymapOverlay {
        layer: overlay;
        display: none;
        dock: top;
        height: auto;
        max-height: 24;
        width: 1fr;
        margin: 0 1;
        padding: 1 2;
        background: $surface;
        border: tall $primary 15%;
    }
    KeymapOverlay.--visible { display: block; }
    KeymapOverlay > Static { height: auto; }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=False, priority=True),
        Binding("f1", "dismiss", "Close", show=False, priority=True),
        Binding("q", "dismiss", "Close", show=False, priority=True),
    ]

    # Full-width layout (≥80 cols).  Width-breakpoint rendering is handled in
    # render() on the inner Static; this constant is the ≥80 version.
    _CONTENT_WIDE = (
        "[bold]Hermes  Keyboard Reference[/bold]"
        "                          [dim]\\[F1][/dim] close\n"
        "─────────────────────────────────────────────────────────────\n"
        "\n"
        "[bold $text]Navigation[/bold $text]\n"
        "  Previous / next turn            [dim]\\[Alt+↑][/dim]   [dim]\\[Alt+↓][/dim]\n"
        "  Scroll to live edge             [dim]\\[End][/dim]\n"
        "  Open history search             [dim]\\[Ctrl+F][/dim]  [dim]\\[Ctrl+G][/dim]\n"
        "\n"
        "[bold $text]Input[/bold $text]\n"
        "  Submit message                  [dim]\\[Enter][/dim]\n"
        "  Accept autocomplete             [dim]\\[Tab][/dim]\n"
        "  Insert newline                  [dim]\\[Shift+Enter][/dim]\n"
        "  Previous / next history         [dim]\\[↑][/dim]  [dim]\\[↓][/dim]\n"
        "  Path/file reference             [dim]\\[@file][/dim]  [dim]\\[Ctrl+P][/dim]\n"
        "\n"
        "[bold $text]Tools[/bold $text]\n"
        "  Expand / collapse tool block    [dim]\\[click header][/dim]\n"
        "  Expand all / collapse all       [dim]\\[a][/dim]  [dim]\\[A][/dim]  (browse mode)\n"
        "  Interrupt agent                 [dim]\\[Ctrl+C][/dim]  [dim]\\[Escape][/dim]\n"
        "\n"
        "[bold $text]Slash Commands[/bold $text]\n"
        "  /help                           List all commands\n"
        "  /model  /reasoning  /skin       Picker overlays\n"
        "  /yolo   /verbose                Toggle modes\n"
        "  /clear  /undo  /retry           Session control\n"
        "\n"
        "[bold $text]Panels[/bold $text]\n"
        "  Click reasoning                 Collapse / expand\n"
        "  Undo last turn                  [dim]\\[Alt+Z][/dim]\n"
        "  Toggle FPS HUD                  [dim]\\[F8][/dim]\n"
        "\n"
        "[bold $text]Tool Panel[/bold $text]\n"
        "  Toggle collapse                 [dim]\\[Enter][/dim]  [dim]\\[Space][/dim]\n"
        "  Scroll body                     [dim]\\[j][/dim]  [dim]\\[k][/dim]  [dim]\\[J][/dim]  [dim]\\[K][/dim]\n"
        "  Rerun tool                      [dim]\\[r][/dim]\n"
        "  Copy output                     [dim]\\[c][/dim]  [dim]\\[C][/dim]  [dim]\\[H][/dim]\n"
        "  Help overlay                    [dim]\\[?][/dim]\n"
        "\n"
        "[bold $text]Mouse & Right-click[/bold $text]\n"
        "  Right-click tool header         Context menu\n"
        "  Ctrl+click                      Open file/URL\n"
        "  Middle-click                    Paste primary selection\n"
        "  Scroll wheel                    Scroll output\n"
        "\n"
        "[bold $text]System[/bold $text]\n"
        "  This help                       [dim]\\[F1][/dim]\n"
        "  Quit                            [dim]\\[Ctrl+Q][/dim]\n"
    )

    _CONTENT_NARROW = (
        "[bold]Keyboard Reference[/bold]  [dim]\\[F1][/dim] close\n"
        "\n"
        "[bold $text]Navigation[/bold $text]\n"
        "  Prev/next turn\n    [dim]\\[Alt+↑][/dim]  [dim]\\[Alt+↓][/dim]\n"
        "  History search\n    [dim]\\[Ctrl+F][/dim]\n"
        "\n"
        "[bold $text]Input[/bold $text]\n"
        "  Submit\n    [dim]\\[Enter][/dim]\n"
        "  Autocomplete\n    [dim]\\[Tab][/dim]\n"
        "\n"
        "[bold $text]Tools[/bold $text]\n"
        "  Expand/collapse\n    [dim]\\[click header][/dim]\n"
        "  Interrupt\n    [dim]\\[Ctrl+C][/dim]\n"
        "\n"
        "[bold $text]Commands[/bold $text]\n"
        "  /model /skin /yolo /clear\n"
        "\n"
        "[bold $text]System[/bold $text]\n"
        "  Help  [dim]\\[F1][/dim]    Quit  [dim]\\[Ctrl+Q][/dim]\n"
    )

    def compose(self) -> ComposeResult:
        yield Static("", id="keymap-content", markup=True)

    def on_mount(self) -> None:
        self._update_content()

    def on_resize(self) -> None:
        self._update_content()

    def _update_content(self) -> None:
        """Choose wide/narrow layout based on terminal width (P1-D)."""
        try:
            w = self.app.size.width
        except Exception:
            w = 80
        content = self._CONTENT_WIDE if w >= 80 else self._CONTENT_NARROW
        try:
            self.query_one("#keymap-content", Static).update(content)
        except NoMatches:
            pass

    def action_dismiss(self) -> None:
        self.remove_class("--visible")
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.app.query_one(HermesInput).focus()
        except (NoMatches, ImportError):
            pass


# ---------------------------------------------------------------------------
# HistorySearchOverlay
# ---------------------------------------------------------------------------

class HistorySearchOverlay(Widget):
    """Ctrl+F history search overlay.

    Shows a fuzzy-searchable list of past conversation turns. Ctrl+F opens
    it; Escape/Ctrl+F/Enter dismiss it (Enter also jumps to the selected turn).
    """

    DEFAULT_CSS = """
    HistorySearchOverlay {
        layer: overlay;
        dock: top;
        margin-top: 2;
        margin-left: 4;
        width: 90%;
        max-width: 90;
        min-width: 40;
        height: auto;
        max-height: 50%;
        min-height: 8;
        display: none;
        background: $surface;
        border: tall $primary 15%;
        padding: 0 1;
    }
    HistorySearchOverlay.--visible {
        display: block;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", priority=True),
        Binding("ctrl+f", "dismiss", priority=True),
        Binding("ctrl+g", "dismiss", priority=True),
        Binding("ctrl+c", "dismiss", priority=True),
        Binding("up", "move_up", priority=True),
        Binding("down", "move_down", priority=True),
        Binding("ctrl+p", "move_up", priority=True),
        Binding("ctrl+n", "move_down", priority=True),
        Binding("enter", "jump", priority=True),
    ]

    class TurnCompleted(Message):
        """Posted when the agent finishes a turn — triggers index rebuild."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._index: list[_TurnEntry] = []
        self._current_results: list[_SearchResult] = []
        self._selected_idx: int = 0
        self._saved_hint: str = ""
        self._debounce_handle: Any = None  # Timer | None; cancelled on each new keystroke
        self._cross_session_loading: bool = False  # B4: worker in-flight flag
        self._max_results: int = 50
        self._last_click_idx: int | None = None
        self._shift_selected: set[int] = set()
        self._mode: str = "current"
        self._query_history: list[str] = []

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Search history  ↑↓ navigate · Enter jump · Esc close", id="history-search-input")
        yield VerticalScroll(id="history-result-list")
        yield Static("", id="history-status")

    def open_search(self) -> None:
        """Build frozen snapshot index, show overlay, focus search input."""
        self._build_index()
        self._selected_idx = 0
        # Save and update HintBar hint
        try:
            from .status_bar import HintBar
            hint_bar = self.app.query_one(HintBar)
            self._saved_hint = hint_bar.hint
            hint_bar.hint = "↑↓ navigate  Enter jump  Esc close"
        except NoMatches:
            self._saved_hint = ""
        # A1: clear previous search query so the list always opens unfiltered
        try:
            inp = self.query_one("#history-search-input", Input)
            inp.value = ""
        except NoMatches:
            pass
        self._render_results("")
        self.add_class("--visible")
        try:
            self.query_one("#history-search-input", Input).focus()
        except NoMatches:
            pass

    def action_dismiss(self) -> None:
        """Hide overlay, restore hint, return focus to HermesInput."""
        # Cancel any pending debounce so _render_results() doesn't run
        # against a hidden overlay, removing and re-mounting DOM children.
        if self._debounce_handle is not None:
            self._debounce_handle.stop()
            self._debounce_handle = None
        # A2: clear highlighted_candidate so ghost text is not left stale
        try:
            self.app.highlighted_candidate = None
        except Exception:
            pass
        self.remove_class("--visible")
        try:
            from .status_bar import HintBar
            self.app.query_one(HintBar).hint = self._saved_hint
        except NoMatches:
            pass
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.app.query_one(HermesInput).focus()
        except (NoMatches, ImportError):
            pass

    def _build_index(self) -> None:
        """Build a frozen snapshot of current turns. DOM access — event loop only."""
        try:
            from hermes_cli.tui.widgets import OutputPanel, MessagePanel
            output_panel = self.app.query_one(OutputPanel)
            panels = [
                child for child in output_panel.children if isinstance(child, MessagePanel)
            ]
        except NoMatches:
            self._index = []
            return

        # panels[0] is the startup/banner turn (oldest in DOM, not indexed).
        # Real turns are panels[1:]; iterate newest-first.
        # Index is 1-based across all panels: startup = 1, first real = 2, etc.
        real_panels = panels[1:]
        total = len(panels)
        entries: list[_TurnEntry] = []
        for i, panel in enumerate(reversed(real_panels)):
            message_count = total - i
            user_text = panel._user_text or "(no user message)"
            assistant_text = panel.all_prose_text()
            entries.append(
                _TurnEntry(
                    panel=panel,
                    index=message_count,
                    user_text=user_text,
                    assistant_text=assistant_text,
                    search_text=f"{user_text}\n\n{assistant_text}",
                    display=user_text,
                )
            )
        self._index = entries

    def on_input_changed(self, event: Input.Changed) -> None:
        """Debounce keystrokes (150ms) before re-ranking results."""
        if event.input.id != "history-search-input":
            return
        if self._debounce_handle is not None:
            self._debounce_handle.stop()
            self._debounce_handle = None
        query = event.value
        if getattr(self, "_mode", "current") == "all":
            # B4: in all-sessions mode, re-run cross-session search on new query
            def _run_cross() -> None:
                self._cross_session_loading = True
                self._show_cross_session_loading()
                if hasattr(self, "_search_cross_session"):
                    self._search_cross_session(query)
            self._debounce_handle = self.set_timer(0.25, _run_cross)
        else:
            self._debounce_handle = self.set_timer(0.15, lambda: self._render_results(query))

    def _show_cross_session_loading(self) -> None:
        """B4: display a 'Searching…' indicator in the status bar while the worker runs."""
        try:
            self.query_one("#history-status", Static).update("[dim]Searching all sessions…[/dim]")
        except NoMatches:
            pass

    def _render_results(self, query: str) -> None:
        """Search with match highlighting and update the result list.

        Reuses existing TurnResultItem widgets when the result count is
        unchanged (update-in-place via update_from()).  Only adds or removes
        widgets when the count changes, cutting DOM churn on stable queries.
        """
        self._debounce_handle = None
        # Scored search with span tracking; cap at 20 results.
        if query:
            search_results = _substring_search(query, self._index, limit=20)
        else:
            # No query: show all entries newest-first, no match spans
            search_results = [
                _SearchResult(entry=e, match_spans=(), first_match_offset=0)
                for e in self._index[:20]
            ]
        self._current_results = search_results
        try:
            result_list = self.query_one("#history-result-list", VerticalScroll)
        except NoMatches:
            return

        existing = list(result_list.query(TurnResultItem))
        new_count = len(search_results)
        old_count = len(existing)

        if new_count == old_count:
            for widget, result in zip(existing, search_results):
                widget.update_from(result)
        elif new_count < old_count:
            for widget, result in zip(existing[:new_count], search_results):
                widget.update_from(result)
            for widget in existing[new_count:]:
                widget.remove()
        else:
            for widget, result in zip(existing, search_results[:old_count]):
                widget.update_from(result)
            new_items = [TurnResultItem(r) for r in search_results[old_count:]]
            result_list.mount_all(new_items)

        self._selected_idx = max(0, min(self._selected_idx, new_count - 1))
        self.call_after_refresh(self._update_selection)

        # Status line
        total = len(self._index)
        try:
            if search_results or total == 0:
                shown = len(search_results)
                sel = min(self._selected_idx + 1, shown) if shown else 0
                status_text = (
                    f"[dim]{sel}/{shown} shown · "
                    f"{total} turn{'s' if total != 1 else ''} indexed[/dim]"
                )
            else:
                status_text = (
                    "[dim]no matches — try fewer words or a partial phrase[/dim]"
                )
            self.query_one("#history-status", Static).update(status_text)
        except NoMatches:
            pass

    def _update_selection(self) -> None:
        """Apply --selected CSS class to the currently highlighted row."""
        try:
            items = list(self.query(TurnResultItem))
        except Exception:
            return
        for i, item in enumerate(items):
            item.set_class(i == self._selected_idx, "--selected")

    def action_move_up(self) -> None:
        self._selected_idx = max(0, self._selected_idx - 1)
        self._update_selection()

    def action_move_down(self) -> None:
        count = len(list(self.query(TurnResultItem)))
        self._selected_idx = min(max(count - 1, 0), self._selected_idx + 1)
        self._update_selection()

    def action_jump(self) -> None:
        """Jump to the selected turn and dismiss the overlay."""
        items = list(self.query(TurnResultItem))
        if not items:
            self.action_dismiss()
            return
        shift_sel = getattr(self, "_shift_selected", set())
        if shift_sel:
            target_idx = min(shift_sel)
            for item in items:
                if item._entry is not None and getattr(item._entry, "index", -1) == target_idx:
                    entry, result = item._entry, item._result
                    self.action_dismiss()
                    if entry is not None:
                        self._scroll_to_match(entry, result)
                    return
        idx = max(0, min(self._selected_idx, len(items) - 1))
        result = items[idx]._result
        entry = items[idx]._entry
        self.action_dismiss()
        if entry is None:
            return
        self._scroll_to_match(entry, result)

    def action_jump_to(
        self,
        entry: "_TurnEntry | None",
        result: "_SearchResult | None" = None,
    ) -> None:
        """Jump directly to a specific entry (used by TurnResultItem click)."""
        self.action_dismiss()
        if entry is None:
            return
        self._scroll_to_match(entry, result)

    def _scroll_to_match(
        self,
        entry: _TurnEntry,
        result: "_SearchResult | None",
    ) -> None:
        """Scroll to panel, flash highlight, deep-scroll into matched region."""
        panel = entry.panel
        panel.scroll_visible(animate=True)
        panel.add_class("--highlighted")
        panel.set_timer(0.5, lambda: panel.remove_class("--highlighted"))
        # Deep scroll: if match is deep in assistant text, scroll into it
        if result and result.first_match_offset > 0:
            try:
                log = panel.query_one(CopyableRichLog)
                lines_before = entry.search_text[:result.first_match_offset].count("\n")
                if lines_before > 5:
                    log.scroll_to(0, lines_before - 2, animate=True)
            except NoMatches:
                pass

    def on_resize(self) -> None:
        """Re-render results to update truncation width after terminal resize."""
        if self.has_class("--visible"):
            try:
                query = self.query_one("#history-search-input", Input).value
            except NoMatches:
                query = ""
            self._render_results(query)


# ---------------------------------------------------------------------------
# _CrossSessionResult — cross-session FTS5 search result
# ---------------------------------------------------------------------------

@dataclass
class _CrossSessionResult:
    """Result from cross-session FTS5 search."""
    session_id: str
    session_title: str       # empty string if NULL
    role: str
    content_preview: str     # first 80 chars, newlines collapsed
    timestamp: float
    is_current_session: bool # True when session_id == current session_id


def _build_cross_session_label(result: "_CrossSessionResult") -> str:
    """Build row label for a cross-session search result."""
    title = result.session_title or result.session_id[-8:]
    preview = result.content_preview
    return f"[dim]\\[{_escape_markup(title)}][/dim]  {_escape_markup(preview)}"


# ---------------------------------------------------------------------------
# _ModeBar — current/all session toggle display
# ---------------------------------------------------------------------------

class _ModeBar(Static):
    """Renders [Current] All or Current [All] based on overlay mode."""

    DEFAULT_CSS = """
    _ModeBar { height: 1; padding: 0 1; }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self._mode = "current"

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        if mode == "current":
            self.update("[bold]\\[Current][/bold] All")
        else:
            self.update("Current [bold]\\[All][/bold]")
