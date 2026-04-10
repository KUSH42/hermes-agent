"""Custom input widget for Hermes TUI.

Replaces prompt_toolkit's TextArea with a Textual-native widget that owns:
- History: backed by ~/.hermes/.hermes_history via prompt_toolkit.history.FileHistory
- Autocomplete: slash-command completer with ListView popup
- Placeholder: conditional overlay shown when content is empty
- Password masking: reactive masked bool replacing display chars with bullet

This is Step 5 of the migration plan. Steps 1–4 use Textual's built-in
TextArea as an interim shim.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from rich.text import Text
from textual import events
from textual.app import ComposeResult, RenderResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

if TYPE_CHECKING:
    pass

# History file path — same location as prompt_toolkit's FileHistory used
_HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
_HISTORY_FILE = _HERMES_HOME / ".hermes_history"


class HermesInput(Widget, can_focus=True):
    """Custom input widget with history, autocomplete, and password masking.

    Emits :class:`HermesInput.Submitted` when the user presses Enter with
    non-empty content.
    """

    DEFAULT_CSS = """
    HermesInput {
        height: auto;
        min-height: 1;
        max-height: 8;
    }
    HermesInput > .hermes-input--placeholder {
        color: $text-muted;
        display: none;
    }
    HermesInput.--empty > .hermes-input--placeholder {
        display: block;
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
        Binding("enter", "submit", "Submit", show=False),
        Binding("up", "history_prev", "Previous history", show=False),
        Binding("down", "history_next", "Next history", show=False),
        Binding("escape", "dismiss_autocomplete", "Dismiss", show=False),
        Binding("tab", "accept_autocomplete", "Accept completion", show=False),
    ]

    # --- Reactives ---
    content: reactive[str] = reactive("", repaint=True)
    cursor_pos: reactive[int] = reactive(0)
    masked: reactive[bool] = reactive(False)
    placeholder_text: reactive[str] = reactive("Send a message...")
    disabled: reactive[bool] = reactive(False)

    # --- Messages ---
    class Submitted(Message):
        """Emitted when the user submits input."""

        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def __init__(
        self,
        *,
        placeholder: str = "Send a message...",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.placeholder_text = placeholder
        self._history: list[str] = []
        self._history_idx: int = -1
        self._history_draft: str = ""  # save current input when navigating history
        self._autocomplete_items: list[str] = []
        self._autocomplete_idx: int = 0
        self._slash_commands: list[str] = []

    def compose(self) -> ComposeResult:
        yield Static(self.placeholder_text, classes="hermes-input--placeholder")
        yield Static("", classes="hermes-input--autocomplete")

    def on_mount(self) -> None:
        self._load_history()
        self._update_empty_class()

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
                # Most recent last
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

    def _update_empty_class(self) -> None:
        self.set_class(not self.content, "--empty")

    def watch_content(self, value: str) -> None:
        self._update_empty_class()
        self._update_autocomplete()

    def watch_disabled(self, value: bool) -> None:
        if value:
            self.add_class("--disabled")
        else:
            self.remove_class("--disabled")

    def render(self) -> RenderResult:
        if self.masked:
            display = "●" * len(self.content)
        else:
            display = self.content

        t = Text(display)
        # Cursor indicator — append a block char at cursor position
        if self.has_focus and not self.disabled:
            pos = min(self.cursor_pos, len(display))
            if pos < len(display):
                t.stylize("reverse", pos, pos + 1)
            else:
                t.append("▏", style="blink")
        return t

    # --- Key handling ---

    def on_key(self, event: events.Key) -> None:
        if self.disabled:
            event.prevent_default()
            return

        key = event.key
        char = event.character

        # Regular character input
        if char and len(char) == 1 and key not in (
            "enter", "up", "down", "escape", "tab",
            "backspace", "delete", "left", "right",
            "home", "end",
        ) and not event.is_printable is False:
            event.prevent_default()
            self._insert_char(char)
            return

        if key == "backspace":
            event.prevent_default()
            self._backspace()
        elif key == "delete":
            event.prevent_default()
            self._delete()
        elif key == "left":
            event.prevent_default()
            if self.cursor_pos > 0:
                self.cursor_pos -= 1
        elif key == "right":
            event.prevent_default()
            if self.cursor_pos < len(self.content):
                self.cursor_pos += 1
        elif key == "home":
            event.prevent_default()
            self.cursor_pos = 0
        elif key == "end":
            event.prevent_default()
            self.cursor_pos = len(self.content)
        elif key == "ctrl+a":
            event.prevent_default()
            self.cursor_pos = 0
        elif key == "ctrl+e":
            event.prevent_default()
            self.cursor_pos = len(self.content)
        elif key == "ctrl+k":
            event.prevent_default()
            self.content = self.content[: self.cursor_pos]
        elif key == "ctrl+u":
            event.prevent_default()
            self.content = self.content[self.cursor_pos :]
            self.cursor_pos = 0
        elif key == "ctrl+w":
            event.prevent_default()
            self._delete_word_back()

    def _insert_char(self, char: str) -> None:
        pos = self.cursor_pos
        self.content = self.content[:pos] + char + self.content[pos:]
        self.cursor_pos = pos + len(char)

    def _backspace(self) -> None:
        if self.cursor_pos > 0:
            pos = self.cursor_pos
            self.content = self.content[: pos - 1] + self.content[pos:]
            self.cursor_pos = pos - 1

    def _delete(self) -> None:
        pos = self.cursor_pos
        if pos < len(self.content):
            self.content = self.content[:pos] + self.content[pos + 1 :]

    def _delete_word_back(self) -> None:
        pos = self.cursor_pos
        if pos == 0:
            return
        # Skip trailing spaces
        i = pos - 1
        while i > 0 and self.content[i] == " ":
            i -= 1
        # Skip word chars
        while i > 0 and self.content[i - 1] != " ":
            i -= 1
        self.content = self.content[:i] + self.content[pos:]
        self.cursor_pos = i

    def insert_text(self, text: str) -> None:
        """Insert text at cursor position (for paste support)."""
        pos = self.cursor_pos
        self.content = self.content[:pos] + text + self.content[pos:]
        self.cursor_pos = pos + len(text)

    def on_paste(self, event: events.Paste) -> None:
        """Handle paste events."""
        if self.disabled:
            return
        self.insert_text(event.text)
        event.prevent_default()

    # --- Actions ---

    def action_submit(self) -> None:
        if self.disabled:
            return
        text = self.content.strip()
        if text:
            self._save_to_history(text)
            self.post_message(self.Submitted(text))
            self.content = ""
            self.cursor_pos = 0
            self._history_idx = -1

    def action_history_prev(self) -> None:
        if self.disabled or not self._history:
            return

        # If we haven't started navigating history, save current content
        if self._history_idx == -1:
            self._history_draft = self.content
            self._history_idx = len(self._history) - 1
        elif self._history_idx > 0:
            self._history_idx -= 1
        else:
            return

        self.content = self._history[self._history_idx]
        self.cursor_pos = len(self.content)

    def action_history_next(self) -> None:
        if self.disabled or self._history_idx == -1:
            return

        if self._history_idx < len(self._history) - 1:
            self._history_idx += 1
            self.content = self._history[self._history_idx]
        else:
            # Back to the draft
            self._history_idx = -1
            self.content = self._history_draft

        self.cursor_pos = len(self.content)

    # --- Autocomplete ---

    def _update_autocomplete(self) -> None:
        """Update autocomplete popup based on current content."""
        if self.content.startswith("/") and self._slash_commands:
            prefix = self.content.split()[0] if self.content else ""
            matches = [c for c in self._slash_commands if c.startswith(prefix) and c != prefix]
            if matches and len(prefix) > 1:
                self._autocomplete_items = matches[:12]
                self._autocomplete_idx = 0
                self.add_class("--autocomplete-visible")
                try:
                    popup = self.query_one(".hermes-input--autocomplete", Static)
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
            self.content = selected + " "
            self.cursor_pos = len(self.content)
            self._autocomplete_items = []
            self.remove_class("--autocomplete-visible")

    def action_dismiss_autocomplete(self) -> None:
        self._autocomplete_items = []
        self.remove_class("--autocomplete-visible")

    def clear(self) -> None:
        """Clear the input content."""
        self.content = ""
        self.cursor_pos = 0
