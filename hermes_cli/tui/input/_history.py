"""History and ghost-text mixin for HermesInput."""
from __future__ import annotations

from ._constants import _HISTORY_FILE, _MAX_HISTORY


class _HistoryMixin:
    """Mixin: persistent command history + Fish-style ghost-text suggestion."""

    # State initialised by HermesInput.__init__
    _history: list[str]
    _history_idx: int
    _slash_commands: list[str]

    def _load_history(self) -> None:
        """Load history from the hermes history file (same format as FileHistory).

        Loads last _MAX_HISTORY entries to avoid test-remnant bloat.
        """
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
                self._history = lines[-_MAX_HISTORY:]
        except OSError:
            self._history = []

    def _save_to_history(self, text: str) -> None:
        """Append an entry to the history file and in-memory list."""
        if not text.strip():
            return
        if self._history and self._history[-1] == text:
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

    def update_suggestion(self) -> None:
        """Set ghost text from history. Called by TextArea after every edit."""
        current = self.text  # type: ignore[attr-defined]
        if not current or "\n" in current:
            self.suggestion = ""  # type: ignore[attr-defined]
            return
        row, col = self.cursor_location  # type: ignore[attr-defined]
        if row != 0 or col != len(current):
            self.suggestion = ""  # type: ignore[attr-defined]
            return
        for entry in reversed(self._history):
            if entry.startswith(current) and entry != current:
                self.suggestion = entry[len(current):]  # type: ignore[attr-defined]
                return
        self.suggestion = ""  # type: ignore[attr-defined]
