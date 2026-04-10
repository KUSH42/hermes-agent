"""Custom input widget for Hermes TUI.

Extends Textual's built-in Input widget to get selection, clipboard, mouse
drag, shift+arrow, and all standard keybindings for free. Layers
Hermes-specific features on top:

- History: backed by ~/.hermes/.hermes_history via FileHistory format
- Autocomplete: slash-command completer with popup
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

if TYPE_CHECKING:
    pass

# History file path — same location as prompt_toolkit's FileHistory used
_HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
_HISTORY_FILE = _HERMES_HOME / ".hermes_history"


class HermesInput(Input, can_focus=True):
    """Input widget with history, autocomplete, and spinner overlay.

    Extends Textual's Input to inherit selection, clipboard, cursor, and
    all standard keybindings. Emits :class:`HermesInput.Submitted` when
    the user presses Enter with non-empty content.
    """

    DEFAULT_CSS = """
    HermesInput {
        height: 1;
        background: transparent;
        border: none;
        padding: 0;
    }
    HermesInput > .hermes-input--autocomplete {
        display: none;
        border: round $primary;
        max-height: 6;
        overflow-y: auto;
    }
    HermesInput.--autocomplete-visible > .hermes-input--autocomplete {
        display: block;
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
        super().__init__(placeholder=placeholder, id=id, classes=classes)
        self._history: list[str] = []
        self._history_idx: int = -1
        self._history_draft: str = ""
        self._autocomplete_items: list[str] = []
        self._autocomplete_idx: int = 0
        self._slash_commands: list[str] = []

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

        Textual's disabled state only blocks mouse events. Key events pass
        through unrestricted, so users can still type into a disabled Input.
        Guard against that here. Let ctrl+c and escape bubble for interrupt.
        """
        if self.disabled and event.is_printable:
            event.prevent_default()
            return
        await super()._on_key(event)

    # --- Actions ---

    def action_submit(self) -> None:
        """Save to history before posting Submitted."""
        text = self.value.strip()
        if self.disabled or not text:
            return
        self._save_to_history(text)
        self.post_message(self.Submitted(text))
        self.value = ""
        self._history_idx = -1

    def action_history_prev(self) -> None:
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

    def _update_autocomplete(self) -> None:
        """Update autocomplete popup based on current value."""
        if self.value.startswith("/") and self._slash_commands:
            prefix = self.value.split()[0] if self.value else ""
            matches = [c for c in self._slash_commands if c.startswith(prefix) and c != prefix]
            if matches and len(prefix) > 1:
                self._autocomplete_items = matches[:12]
                self._autocomplete_idx = 0
                self.add_class("--autocomplete-visible")
                try:
                    popup = self.screen.query_one(".hermes-input--autocomplete")
                    popup.update("\n".join(
                        f"[bold]→[/bold] {m}" if i == self._autocomplete_idx else f"  {m}"
                        for i, m in enumerate(self._autocomplete_items)
                    ))
                except NoMatches:
                    pass
                return
        self._autocomplete_items = []
        self.remove_class("--autocomplete-visible")

    def action_accept_autocomplete(self) -> None:
        if self._autocomplete_items:
            selected = self._autocomplete_items[self._autocomplete_idx]
            self.value = selected + " "
            self.cursor_position = len(self.value)
            self._autocomplete_items = []
            self.remove_class("--autocomplete-visible")

    def action_dismiss_autocomplete(self) -> None:
        self._autocomplete_items = []
        self.remove_class("--autocomplete-visible")

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
