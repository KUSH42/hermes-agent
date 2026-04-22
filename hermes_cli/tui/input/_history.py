"""History and ghost-text mixin for HermesInput."""
from __future__ import annotations

from hermes_cli.tui.io_boundary import safe_write_file
from ._constants import _HISTORY_FILE, _MAX_HISTORY


class _HistoryMixin:
    """Mixin: persistent command history + Fish-style ghost-text suggestion."""

    # State initialised by HermesInput.__init__
    _history: list[str]
    _history_idx: int
    _slash_commands: list[str]

    def _load_history(self) -> None:
        """Load history from the hermes history file (same format as FileHistory).

        Deduplicates entries — last occurrence wins, ordered by last occurrence position.
        Loads last _MAX_HISTORY unique entries.
        """
        try:
            if _HISTORY_FILE.exists():
                all_entries: list[str] = []
                current_entry: list[str] = []
                for raw_line in _HISTORY_FILE.read_text(errors="replace").splitlines():
                    if raw_line.startswith("+"):
                        current_entry.append(raw_line[1:])
                    elif current_entry:
                        all_entries.append("\n".join(current_entry))
                        current_entry = []
                if current_entry:
                    all_entries.append("\n".join(current_entry))
                # Dedup: last occurrence wins, preserve relative order of last occurrences
                seen: dict[str, int] = {}
                for i, e in enumerate(all_entries):
                    seen[e] = i  # last index wins
                deduped = [e for i, e in enumerate(all_entries) if seen[e] == i]
                self._history = deduped[-_MAX_HISTORY:]
        except OSError:
            self._history = []

    def _save_to_history(self, text: str) -> None:
        """Append an entry to the history file and in-memory list.

        Deduplicates globally — removes any prior identical entry then promotes to end.
        """
        if not text.strip():
            return
        try:
            self._history.remove(text)
        except ValueError:
            pass
        self._history.append(text)
        entry_text = "\n" + "".join(f"+{line}\n" for line in text.split("\n"))
        safe_write_file(
            self,  # type: ignore[arg-type]
            _HISTORY_FILE,
            entry_text,
            mode="a",
            mkdir_parents=True,
        )

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
            self._rev_match_idx: int = -1
            self._rev_saved_value: str = ""
        current = getattr(self, "text", "")  # type: ignore[attr-defined]
        if not self._rev_mode:
            self._rev_mode = True
            self._rev_saved_value = current
            self._rev_query = current
            self._rev_idx = len(self._history)
            self._rev_match_idx = len(self._history)
            # Update placeholder to signal rev-search mode
            query_display = self._rev_query or ""
            try:
                self.placeholder = f"reverse-i-search: {query_display}_"  # type: ignore[attr-defined]
            except Exception:
                pass
        query = self._rev_query or current
        idx = self._rev_idx - 1
        while idx >= 0:
            if self._history[idx].startswith(query):
                self._rev_idx = idx
                self._history_loading = True  # type: ignore[attr-defined]
                try:
                    self.load_text(self._history[idx])  # type: ignore[attr-defined]
                    self.move_cursor((0, len(self._history[idx])))  # type: ignore[attr-defined]
                except Exception:
                    pass
                finally:
                    self._history_loading = False  # type: ignore[attr-defined]
                return
            idx -= 1

    def _exit_rev_search(self) -> None:
        self._exit_rev_mode(accept=True)

    def _exit_rev_mode(self, accept: bool = True) -> None:
        """Exit reverse-search mode. If accept=False, restore the pre-search value."""
        saved = getattr(self, "_rev_saved_value", "")
        self._rev_mode = False
        self._rev_query = ""
        self._rev_idx = -1
        self._rev_match_idx = -1
        if not accept:
            self._history_loading = True  # type: ignore[attr-defined]
            try:
                self.load_text(saved)  # type: ignore[attr-defined]
                self.move_cursor((0, len(saved)))  # type: ignore[attr-defined]
            except Exception:
                pass
            finally:
                self._history_loading = False  # type: ignore[attr-defined]
            self._history_idx = -1  # type: ignore[attr-defined]
        else:
            # Accepted a rev-search match: sync _history_idx so subsequent up/down
            # continues relative to the matched entry instead of drifting to a
            # stale pre-rev-search position.
            match_idx = getattr(self, "_rev_match_idx", -1)
            hist = getattr(self, "_history", [])
            if 0 <= match_idx < len(hist):
                self._history_idx = match_idx  # type: ignore[attr-defined]
            else:
                self._history_idx = -1  # type: ignore[attr-defined]
        # Restore idle placeholder
        try:
            self.placeholder = self._idle_placeholder  # type: ignore[attr-defined]
        except Exception:
            pass

    def _rev_search_find(self, query: str | None = None, direction: int = -1) -> str | None:
        """Find history entry matching query, updating _rev_match_idx and widget value.

        direction=-1 searches backward (older), direction=1 searches forward (newer).
        query defaults to self._rev_query if omitted.
        """
        if query is None:
            query = getattr(self, "_rev_query", "")
        if not hasattr(self, "_rev_match_idx"):
            self._rev_match_idx: int = len(self._history)
        idx = self._rev_match_idx + direction
        if direction < 0:
            while idx >= 0:
                if query in self._history[idx]:
                    self._rev_match_idx = idx
                    try:
                        self.load_text(self._history[idx])  # type: ignore[attr-defined]
                        self.move_cursor((0, len(self._history[idx])))  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    return self._history[idx]
                idx -= 1
        else:
            while idx < len(self._history):
                if query in self._history[idx]:
                    self._rev_match_idx = idx
                    try:
                        self.load_text(self._history[idx])  # type: ignore[attr-defined]
                        self.move_cursor((0, len(self._history[idx])))  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    return self._history[idx]
                idx += 1
        return None

    def _history_load(self, text: str) -> None:
        """Load a history entry into the input field and position cursor at end."""
        self._history_loading = True  # type: ignore[attr-defined]
        try:
            self.load_text(text)  # type: ignore[attr-defined]
            self.move_cursor((0, len(text)))  # type: ignore[attr-defined]
        finally:
            self._history_loading = False  # type: ignore[attr-defined]

    def _show_subcommand_completions(self, command: str, fragment: str) -> None:
        """Show subcommand completion overlay for a slash command."""
        from hermes_cli.tui.path_search import SlashCandidate
        subcommands = getattr(self, "_slash_subcommands", {})
        key = f"/{command}"
        options = subcommands.get(key, [])
        if not options:
            self._hide_completion_overlay()  # type: ignore[attr-defined]
            return
        if fragment:
            options = [o for o in options if o.lower().startswith(fragment.lower())]
        candidates = [
            SlashCandidate(display=o, command=f"/{command} {o}")
            for o in options
        ]
        if not candidates:
            self._hide_completion_overlay()  # type: ignore[attr-defined]
            return
        self._set_overlay_mode(slash_only=True)  # type: ignore[attr-defined]
        self._push_to_list(candidates)  # type: ignore[attr-defined]
        self._show_completion_overlay()  # type: ignore[attr-defined]

    def update_suggestion(self) -> None:
        """Set ghost text from history. Called by TextArea after every edit."""
        current = self.text  # type: ignore[attr-defined]
        row, col = self.cursor_location  # type: ignore[attr-defined]

        if "\n" in current:
            lines = current.split("\n")
            last_row = len(lines) - 1
            last_line = lines[-1]
            if not last_line or row != last_row or col != len(last_line):
                self.suggestion = ""  # type: ignore[attr-defined]
                return
            for entry in reversed(self._history):
                entry_last = entry.split("\n")[-1] if "\n" in entry else entry
                if entry_last.startswith(last_line) and entry_last != last_line:
                    self.suggestion = entry_last[len(last_line):]  # type: ignore[attr-defined]
                    return
            self.suggestion = ""  # type: ignore[attr-defined]
            return

        if not current:
            self.suggestion = ""  # type: ignore[attr-defined]
            return
        if row != 0 or col != len(current):
            self.suggestion = ""  # type: ignore[attr-defined]
            return
        for entry in reversed(self._history):
            if entry.startswith(current) and entry != current:
                self.suggestion = entry[len(current):]  # type: ignore[attr-defined]
                return
        self.suggestion = ""  # type: ignore[attr-defined]
