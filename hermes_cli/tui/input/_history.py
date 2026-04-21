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

    def set_slash_descriptions(self, descriptions: dict[str, str]) -> None:
        self._slash_descriptions: dict[str, str] = descriptions

    def set_slash_args_hints(self, hints: dict[str, str]) -> None:
        self._slash_args_hints: dict[str, str] = hints

    def set_slash_keybind_hints(self, hints: dict[str, str]) -> None:
        self._slash_keybind_hints: dict[str, str] = hints

    def set_slash_subcommands(self, subcommands: dict[str, list[str]]) -> None:
        self._slash_subcommands: dict[str, list[str]] = subcommands

    def action_rev_search(self) -> None:
        """Reverse-search history (Ctrl+R)."""
        if not hasattr(self, "_rev_mode"):
            self._rev_mode: bool = False
            self._rev_query: str = ""
            self._rev_idx: int = -1
        current = getattr(self, "text", "")  # type: ignore[attr-defined]
        if not self._rev_mode:
            self._rev_mode = True
            self._rev_query = current
            self._rev_idx = len(self._history)
        query = self._rev_query or current
        idx = self._rev_idx - 1
        while idx >= 0:
            if self._history[idx].startswith(query):
                self._rev_idx = idx
                try:
                    self.clear()  # type: ignore[attr-defined]
                    self.insert(self._history[idx])  # type: ignore[attr-defined]
                except Exception:
                    pass
                return
            idx -= 1

    def _exit_rev_search(self) -> None:
        self._rev_mode = False
        self._rev_query = ""
        self._rev_idx = -1

    def _rev_search_find(self, query: str) -> str | None:
        """Find the most recent history entry matching query."""
        for entry in reversed(self._history):
            if query in entry:
                return entry
        return None

    def _history_load(self) -> None:
        """Reload history from disk."""
        self._load_history()

    def _show_subcommand_completions(self, command: str, fragment: str) -> None:
        """Show subcommand completion overlay for a slash command."""
        subcommands = getattr(self, "_slash_subcommands", {})
        key = f"/{command}"
        options = subcommands.get(key, [])
        if fragment:
            options = [o for o in options if fragment.lower() in o.lower()]
        try:
            from hermes_cli.tui.autocomplete_overlay import AutocompleteOverlay
            app = self.app  # type: ignore[attr-defined]
            overlay = app.query_one(AutocompleteOverlay)
            if not options:
                overlay.styles.display = "none"
                return
            overlay.set_items(options)
            overlay.styles.display = "block"
        except Exception:
            pass

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
