"""Custom input widget for Hermes TUI.

Extends Textual's built-in Input widget to get selection, clipboard, mouse
drag, shift+arrow, and all standard keybindings for free.  Layers
Hermes-specific features on top:

- History: backed by ~/.hermes/.hermes_history via FileHistory format
- Autocomplete: multi-context dispatcher (slash commands, path refs)
- Ghost text: native Input.suggester + HistorySuggester (Fish-style)
- Spinner overlay: sibling widget toggled when disabled
- Property bridge: content/cursor_pos aliases for callers still using old API
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Input, Static

from .completion_context import CompletionContext, CompletionTrigger, detect_context
from .completion_list import VirtualCompletionList
from .completion_overlay import CompletionOverlay
from .fuzzy import fuzzy_rank
from .history_suggester import HistorySuggester
from .path_search import Candidate, PathCandidate, PathSearchProvider, SlashCandidate

if TYPE_CHECKING:
    pass

# History file path — same location as prompt_toolkit's FileHistory used
_HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
_HISTORY_FILE = _HERMES_HOME / ".hermes_history"


class HermesInput(Input, can_focus=True):
    """Input widget with history, multi-context autocomplete, and ghost text.

    Extends Textual's Input to inherit selection, clipboard, cursor, and
    all standard keybindings.  Emits :class:`HermesInput.Submitted` when
    the user presses Enter with non-empty content.
    """

    DEFAULT_CSS = """
    HermesInput {
        height: 1;
        background: transparent;
        border: none;
        padding: 0;
    }
    """

    BINDINGS = [
        Binding("up", "history_prev", "Previous history", show=False),
        Binding("down", "history_next", "Next history", show=False),
        Binding("escape", "dismiss_autocomplete", "Dismiss", show=False),
        Binding("tab", "accept_autocomplete", "Accept completion", show=False),
        Binding("ctrl+a", "select_all", "Select all", show=False),
    ]

    # Spinner text shown when disabled (set by app's _tick_spinner)
    spinner_text: reactive[str] = reactive("", repaint=True)

    # --- Messages ---
    class Submitted(Message):
        """Emitted when the user submits input."""

        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def __init__(
        self,
        *,
        placeholder: str = "",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(
            placeholder=placeholder,
            id=id,
            classes=classes,
            suggester=HistorySuggester(self),  # ghost text via native Suggester API
        )
        self._history: list[str] = []
        self._history_idx: int = -1
        self._history_draft: str = ""
        self._slash_commands: list[str] = []

        # Autocomplete dispatcher state
        self._current_trigger: CompletionTrigger = CompletionTrigger(
            CompletionContext.NONE, "", 0,
        )
        self._raw_candidates: list[PathCandidate] = []

    def on_mount(self) -> None:
        self._load_history()

    # --- Property bridges (old API → Input API) ---

    @property
    def content(self) -> str:
        return self.value

    @content.setter
    def content(self, val: str) -> None:
        self.value = val

    @property
    def cursor_pos(self) -> int:
        return self.cursor_position

    @cursor_pos.setter
    def cursor_pos(self, val: int) -> None:
        self.cursor_position = val

    # --- History ---

    def _load_history(self) -> None:
        """Load history from the hermes history file (same format as FileHistory)."""
        try:
            if _HISTORY_FILE.exists():
                lines: list[str] = []
                current_entry: list[str] = []
                for raw_line in _HISTORY_FILE.read_text(errors="replace").splitlines():
                    if raw_line.startswith("+"):
                        current_entry.append(raw_line[1:])
                    elif current_entry:
                        lines.append("\n".join(current_entry))
                        current_entry = []
                if current_entry:
                    lines.append("\n".join(current_entry))
                self._history = lines
        except OSError:
            self._history = []

    def _save_to_history(self, text: str) -> None:
        """Append an entry to the history file and in-memory list."""
        if not text.strip():
            return
        self._history.append(text)
        try:
            _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(_HISTORY_FILE, "a", encoding="utf-8") as f:
                for line in text.split("\n"):
                    f.write(f"+{line}\n")
                f.write("\n")
        except OSError:
            pass

    def set_slash_commands(self, commands: list[str]) -> None:
        """Set the available slash commands for autocomplete."""
        self._slash_commands = sorted(commands)

    # --- Disabled key guard ---

    async def _on_key(self, event: events.Key) -> None:
        """Block printable input when disabled.

        Textual's disabled state only blocks mouse events.  Key events pass
        through unrestricted, so users can still type into a disabled Input.
        Guard against that here.  Let ctrl+c and escape bubble for interrupt.
        """
        if self.disabled and event.is_printable:
            event.prevent_default()
            return
        await super()._on_key(event)

    # --- Actions ---

    def action_submit(self) -> None:
        """Save to history before posting Submitted.

        Enter always submits as typed — never auto-accepts the highlighted
        candidate.  Tab is the only accept key.  See spec §5.8.8.
        """
        text = self.value.strip()
        if self.disabled or not text:
            return
        self._save_to_history(text)
        self._hide_completion_overlay()
        self.post_message(self.Submitted(text))
        self.value = ""
        self._history_idx = -1

    def action_history_prev(self) -> None:
        # Delegate to completion list when overlay is visible
        if self._completion_overlay_visible():
            self._move_highlight(-1)
            return
        if self.disabled or not self._history:
            return
        if self._history_idx == -1:
            self._history_draft = self.value
            self._history_idx = len(self._history) - 1
        elif self._history_idx > 0:
            self._history_idx -= 1
        else:
            return
        self.value = self._history[self._history_idx]
        self.cursor_position = len(self.value)

    def action_history_next(self) -> None:
        # Delegate to completion list when overlay is visible
        if self._completion_overlay_visible():
            self._move_highlight(+1)
            return
        if self.disabled or self._history_idx == -1:
            return
        if self._history_idx < len(self._history) - 1:
            self._history_idx += 1
            self.value = self._history[self._history_idx]
        else:
            self._history_idx = -1
            self.value = self._history_draft
        self.cursor_position = len(self.value)

    # --- Autocomplete ---

    def watch_value(self, value: str) -> None:
        self._update_autocomplete()
        # Suggester (ghost text) is driven natively by Input — no manual hook.

    def _update_autocomplete(self) -> None:
        """Dispatch to the correct completion provider based on context."""
        # Choice overlay wins: completion is suppressed while an approval
        # prompt is up.
        if getattr(self.app, "choice_overlay_active", False):
            self._hide_completion_overlay()
            return

        trigger = detect_context(self.value, self.cursor_position)
        self._current_trigger = trigger

        # Context change: clear stale walker output.  The new trigger.fragment
        # becomes the implicit stale-batch key in on_path_search_provider_batch.
        self._raw_candidates = []

        if trigger.context is CompletionContext.SLASH_COMMAND:
            self._show_slash_completions(trigger.fragment)
        elif trigger.context is CompletionContext.PATH_REF:
            self._show_path_completions(trigger.fragment)
        else:
            self._hide_completion_overlay()

    def _show_slash_completions(self, fragment: str) -> None:
        if not self._slash_commands:
            self._hide_completion_overlay()
            return
        items = [
            SlashCandidate(display=c, command=c)
            for c in self._slash_commands
            if c.startswith("/" + fragment)
        ]
        ranked = fuzzy_rank(fragment, items, limit=50)
        if not ranked:
            self._hide_completion_overlay()
            return
        self._set_overlay_mode(slash_only=True)
        self._push_to_list(ranked)
        self._show_completion_overlay()

    def _show_path_completions(self, fragment: str) -> None:
        try:
            provider = self.screen.query_one(PathSearchProvider)
        except NoMatches:
            # Provider not yet mounted (e.g. during test fixture bootstrap).
            # Fail closed — hide, don't crash.
            self._hide_completion_overlay()
            return
        self._set_overlay_mode(slash_only=False)
        self._push_to_list([])  # clear while walker spins up — no blank flash
        provider.search(fragment, Path.cwd())
        self._show_completion_overlay()

    def _set_overlay_mode(self, *, slash_only: bool) -> None:
        try:
            overlay = self.screen.query_one(CompletionOverlay)
        except NoMatches:
            return
        overlay.set_class(slash_only, "--slash-only")

    def _show_completion_overlay(self) -> None:
        try:
            overlay = self.screen.query_one(CompletionOverlay)
        except NoMatches:
            return
        overlay.add_class("--visible")

    def _hide_completion_overlay(self) -> None:
        try:
            overlay = self.screen.query_one(CompletionOverlay)
        except NoMatches:
            return
        overlay.remove_class("--visible")
        overlay.remove_class("--slash-only")

    def _completion_overlay_visible(self) -> bool:
        try:
            return self.screen.query_one(CompletionOverlay).has_class("--visible")
        except NoMatches:
            return False

    def _move_highlight(self, delta: int) -> None:
        try:
            clist = self.screen.query_one(VirtualCompletionList)
        except NoMatches:
            return
        if not clist.items:
            return
        clist.highlighted = (clist.highlighted + delta) % len(clist.items)

    # --- Batch handler ---

    def on_path_search_provider_batch(
        self, message: PathSearchProvider.Batch,
    ) -> None:
        """Accumulate walker batches and re-rank candidates."""
        # Belt + suspenders: exclusive=True already cancels in-flight walkers,
        # but a batch can be in the message queue when cancellation lands.
        if self._current_trigger.context is not CompletionContext.PATH_REF:
            return
        if message.query != self._current_trigger.fragment:
            return

        self._raw_candidates.extend(message.batch)
        ranked = fuzzy_rank(
            self._current_trigger.fragment, self._raw_candidates, limit=200,
        )
        self._push_to_list(ranked)

    def _push_to_list(self, candidates: list[Candidate]) -> None:
        try:
            clist = self.screen.query_one(VirtualCompletionList)
        except NoMatches:
            return
        clist.items = tuple(candidates)

    # --- Accept / dismiss ---

    def action_accept_autocomplete(self) -> None:
        """Tab: accept the highlighted candidate into the input."""
        try:
            clist = self.screen.query_one(VirtualCompletionList)
        except NoMatches:
            return
        if not clist.items or clist.highlighted < 0:
            return
        c = clist.items[clist.highlighted]
        trig = self._current_trigger

        if isinstance(c, SlashCandidate):
            new_value = c.command + " "
            new_cursor = len(new_value)
        elif isinstance(c, PathCandidate):
            # Replace only the @fragment span; preserve surrounding text.
            # trig.start is the index of the first char of the fragment
            # (char immediately after @); so trig.start - 1 is the @.
            before = self.value[: trig.start - 1]
            after = self.value[trig.start + len(trig.fragment):]
            # Trailing space only when at EOL so inline inserts don't double-space.
            tail = " " if not after else ""
            new_value = f"{before}@{c.display}{tail}{after}"
            # Cursor lands immediately after the inserted path (+ tail),
            # NOT at EOL, so mid-string inserts don't jump the user away.
            new_cursor = len(before) + 1 + len(c.display) + len(tail)
        else:
            return

        self.value = new_value
        self.cursor_position = new_cursor
        self._hide_completion_overlay()

    def action_dismiss_autocomplete(self) -> None:
        """Escape: dismiss completion overlay only; preserve agent-interrupt semantics."""
        if self._completion_overlay_visible():
            self._hide_completion_overlay()
            # Consume the key so the app-level escape handler doesn't also fire
            return
        # No overlay — let escape bubble to HermesApp.on_key for interrupt/browse

    # --- Convenience ---

    def insert_text(self, text: str) -> None:
        """Insert text at cursor position (for paste support / external callers)."""
        pos = self.cursor_position
        self.value = self.value[:pos] + text + self.value[pos:]
        self.cursor_position = pos + len(text)

    def clear(self) -> None:
        """Clear the input content."""
        self.value = ""
        self.cursor_position = 0
