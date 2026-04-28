"""History and ghost-text mixin for HermesInput."""
from __future__ import annotations

import logging
import os
import tempfile

from ._assist import AssistKind
from ._constants import _HISTORY_FILE, _MAX_HISTORY

_log = logging.getLogger(__name__)


def _serialize_history_entries(entries: list[str]) -> str:
    """Serialize history entries in prompt_toolkit FileHistory wire format."""
    blocks: list[str] = []
    for entry in entries:
        blocks.append("".join(f"+{line}\n" for line in entry.split("\n")))
    return "\n".join(blocks)


def _show_ghost_legend(widget: object) -> None:
    """A12: show ghost legend on first suggestion; one-per-session."""
    if getattr(widget, "_ghost_legend_shown", False):
        return
    try:
        from hermes_cli.tui.widgets.input_legend_bar import InputLegendBar
        widget._ghost_legend_shown = True  # type: ignore[attr-defined]
        widget.screen.query_one(InputLegendBar).show_legend("ghost")  # type: ignore[attr-defined]
    except Exception:  # InputLegendBar absent — ghost legend not shown
        pass


def _hide_ghost_legend(widget: object) -> None:
    """A12: hide ghost legend when suggestion cleared."""
    try:
        from hermes_cli.tui.widgets.input_legend_bar import InputLegendBar
        widget.screen.query_one(InputLegendBar).hide_legend()  # type: ignore[attr-defined]
    except Exception:  # InputLegendBar absent — ghost legend not hidden
        pass


def _apply_assist(widget: object, kind: AssistKind, suggestion: str = "") -> None:
    """Compat shim for unit fakes that don't bind HermesInput._resolve_assist."""
    resolver = getattr(widget, "_resolve_assist", None)
    if callable(resolver):
        resolver(kind, suggestion)
        return
    if kind is AssistKind.GHOST:
        widget.suggestion = suggestion  # type: ignore[attr-defined]
        return
    widget.suggestion = ""  # type: ignore[attr-defined]


class _HistoryMixin:
    """Mixin: persistent command history + Fish-style ghost-text suggestion."""

    # State initialised by HermesInput.__init__
    _history: list[str]
    _history_idx: int
    _slash_commands: list[str]
    _rev_mode: bool = False

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
                if not deduped:
                    self._ghost_legend_shown = False  # type: ignore[attr-defined]
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
        payload = _serialize_history_entries(self._history)
        _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=_HISTORY_FILE.parent,
                delete=False,
            ) as fh:
                tmp_path = fh.name
                fh.write(payload)
            os.replace(tmp_path, _HISTORY_FILE)
            self._write_fail_warned = False  # type: ignore[attr-defined]
        except OSError as exc:
            _log.debug("history write failed: %s", exc, exc_info=True)
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            self._on_history_write_error(exc)

    def _on_history_write_error(self, exc: Exception) -> None:
        """Called when history file write fails. Shows a toast (once per session)."""
        if getattr(self, "_write_fail_warned", False):
            return
        self._write_fail_warned = True
        import logging
        logging.getLogger(__name__).error("history write failed", exc_info=True)
        try:
            from hermes_cli.tui.services.feedback import WARN
            self.app.feedback.flash(  # type: ignore[attr-defined]
                "hint-bar",
                "history write failed — recent entries won't persist",
                duration=6.0,
                priority=WARN,
            )
        except Exception:  # feedback service absent — warning shown only in log
            pass

    def set_slash_commands(self, commands: list[str]) -> None:
        """Set the available slash commands for autocomplete."""
        self._slash_commands = sorted(commands)

    def set_skills(self, candidates: "list") -> None:
        """Set the available skill candidates (for picker + KNOWN_SKILLS).

        Separated from _slash_commands so built-in list stays pure.
        """
        self._skills: list = list(candidates)

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
        current = getattr(self, "text", "")  # type: ignore[attr-defined]
        if not self._rev_mode:
            self._rev_mode = True
            self._rev_saved_value = current
            self._rev_query = current
            self._rev_idx = len(self._history)
            self._rev_match_idx = len(self._history)
            # Clear any ghost text and show persistent rev-search hint
            self.add_class("--rev-search")  # type: ignore[attr-defined]
            _apply_assist(self, AssistKind.NONE)
            self._refresh_placeholder()  # type: ignore[attr-defined]
            try:
                self.app.feedback.flash(  # type: ignore[attr-defined]
                    "hint-bar",
                    "Ctrl+G abort · Esc accept · ↑↓ cycle",
                    duration=9999,
                )
            except Exception:
                pass
            # Recompute mode so watch__mode handles legend/chevron
            try:
                self._mode = self._compute_mode()  # type: ignore[attr-defined]
            except AttributeError as exc:
                # AttributeError: partial mount/test harness without mode sources initialised.
                _log.debug("rev-search mode sync skipped: %s", exc, exc_info=True)
        query = self._rev_query or current
        idx = self._rev_idx - 1
        while idx >= 0:
            if query in self._history[idx]:
                self._rev_idx = idx
                self._rev_match_idx = idx  # I1: sync so ↑↓ continues from here
                self._history_loading = True  # type: ignore[attr-defined]
                try:
                    self.load_text(self._history[idx])  # type: ignore[attr-defined]
                    self.move_cursor((0, len(self._history[idx])))  # type: ignore[attr-defined]
                except Exception:  # TextArea API unavailable — rev-search match not displayed
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
        # Capture match_idx before clearing state (used in accept path below)
        match_idx = getattr(self, "_rev_match_idx", -1)
        self._rev_mode = False
        self.remove_class("--rev-search")  # type: ignore[attr-defined]
        self._rev_query = ""
        self._rev_idx = -1
        self._rev_match_idx = -1
        self._draft_stash = None  # type: ignore[attr-defined]
        if not accept:
            self._history_loading = True  # type: ignore[attr-defined]
            try:
                self.load_text(saved)  # type: ignore[attr-defined]
                self.move_cursor((0, len(saved)))  # type: ignore[attr-defined]
            except Exception:  # TextArea API unavailable — rev-search match not displayed
                pass
            finally:
                self._history_loading = False  # type: ignore[attr-defined]
            self._history_idx = -1  # type: ignore[attr-defined]
        else:
            # Accepted a rev-search match: sync _history_idx so subsequent up/down
            # continues relative to the matched entry instead of drifting to a
            # stale pre-rev-search position.
            hist = getattr(self, "_history", [])
            if 0 <= match_idx < len(hist):
                self._history_idx = match_idx  # type: ignore[attr-defined]
            else:
                self._history_idx = -1  # type: ignore[attr-defined]
        # Cancel the persistent rev-search hint
        try:
            self.app.feedback.cancel("hint-bar")  # type: ignore[attr-defined]
        except Exception:
            pass
        # Restore idle placeholder
        try:
            self._refresh_placeholder()  # type: ignore[attr-defined]
        except Exception:
            try:
                self.placeholder = self._idle_placeholder  # type: ignore[attr-defined]
            except Exception:
                pass
        # Recompute mode so watch__mode handles legend/chevron
        try:
            self._mode = self._compute_mode()  # type: ignore[attr-defined]
        except AttributeError as exc:
            # AttributeError: partial mount/test harness without mode sources initialised.
            _log.debug("rev-search exit mode sync skipped: %s", exc, exc_info=True)

    def _rev_search_find(self, query: str | None = None, direction: int = -1) -> str | None:
        """Find history entry matching query, updating _rev_match_idx and widget value.

        direction=-1 searches backward (older), direction=1 searches forward (newer).
        query defaults to self._rev_query if omitted.
        """
        if query is None:
            query = self._rev_query
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
                    except Exception:  # TextArea API unavailable — rev-search match not displayed
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
                    except Exception:  # TextArea API unavailable — rev-search match not displayed
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

    def _history_navigate_skip_cmds(self, direction: int) -> None:
        """Navigate history skipping slash and bang commands."""
        if not self._history:
            return
        if self._history_idx == -1 and direction == +1:
            return
        if self._history_idx == -1 and direction == -1:
            if getattr(self, "_draft_stash", None) is None:
                self.save_draft_stash()  # type: ignore[attr-defined]
        start = self._history_idx if self._history_idx != -1 else len(self._history)
        idx = start + direction
        if direction == +1 and idx >= len(self._history):
            self._history_idx = -1  # type: ignore[attr-defined]
            stash = getattr(self, "_draft_stash", None)
            self._history_load(stash if stash is not None else "")  # type: ignore[attr-defined]
            if stash is not None:
                self._draft_stash = None  # type: ignore[attr-defined]
            return
        while 0 <= idx < len(self._history):
            entry = self._history[idx]
            if not entry.startswith("/") and not entry.startswith("!"):
                self._history_idx = idx  # type: ignore[attr-defined]
                self._history_load(entry)  # type: ignore[attr-defined]
                return
            idx += direction

    def _show_subcommand_completions(self, command: str, fragment: str) -> None:
        """Show subcommand completion overlay for a slash command."""
        from hermes_cli.tui.path_search import SlashCandidate
        subcommands = getattr(self, "_slash_subcommands", {})
        key = f"/{command}"
        options = subcommands.get(key, [])
        if not options:
            _apply_assist(self, AssistKind.NONE)
            return
        if fragment:
            options = [o for o in options if o.lower().startswith(fragment.lower())]
        candidates = [
            SlashCandidate(display=o, command=f"/{command} {o}")
            for o in options
        ]
        if not candidates:
            _apply_assist(self, AssistKind.NONE)
            return
        self._set_overlay_mode(slash_only=True)  # type: ignore[attr-defined]
        self._push_to_list(candidates)  # type: ignore[attr-defined]
        _apply_assist(self, AssistKind.OVERLAY)

    def update_suggestion(self) -> None:
        """Set ghost text from history. Called by TextArea after every edit."""
        if self._rev_mode:
            return
        current = self.text  # type: ignore[attr-defined]
        row, col = self.cursor_location  # type: ignore[attr-defined]

        if len(current) < 2:
            _apply_assist(self, AssistKind.NONE)
            _hide_ghost_legend(self)
            return

        if "\n" in current:
            lines = current.split("\n")
            last_row = len(lines) - 1
            last_line = lines[-1]
            if not last_line or row != last_row or col != len(last_line):
                _apply_assist(self, AssistKind.NONE)
                _hide_ghost_legend(self)
                return
            for entry in reversed(self._history):
                entry_last = entry.split("\n")[-1] if "\n" in entry else entry
                if entry_last.startswith(last_line) and entry_last != last_line:
                    _apply_assist(self, AssistKind.GHOST, entry_last[len(last_line):])
                    _show_ghost_legend(self)
                    return
            _apply_assist(self, AssistKind.NONE)
            _hide_ghost_legend(self)
            return

        if not current:
            _apply_assist(self, AssistKind.NONE)
            _hide_ghost_legend(self)
            return
        if row != 0 or col != len(current):
            _apply_assist(self, AssistKind.NONE)
            _hide_ghost_legend(self)
            return
        for entry in reversed(self._history):
            if entry.startswith(current) and entry != current:
                _apply_assist(self, AssistKind.GHOST, entry[len(current):])
                _show_ghost_legend(self)
                return
        _apply_assist(self, AssistKind.NONE)
        _hide_ghost_legend(self)
