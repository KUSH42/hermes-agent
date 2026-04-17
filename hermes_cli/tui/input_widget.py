"""Custom input widget for Hermes TUI.

Extends Textual's TextArea for multiline (1–3 row) support.  Layers
Hermes-specific features on top:

- History: backed by ~/.hermes/.hermes_history via FileHistory format
- Autocomplete: multi-context dispatcher (slash commands, path refs)
- Ghost text: TextArea.suggestion reactive, Fish-style (update_suggestion override)
- Spinner text: rendered via TextArea.placeholder while agent runs
- Property bridge: value/content/cursor_pos/cursor_position for callers still using
  the old single-line API
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hermes_cli.file_drop import parse_dragged_file_paste
from hermes_cli.tui.perf import measure

from textual import events
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import TextArea, Static

from hermes_cli.tui.constants import ICON_COPY
from .completion_context import CompletionContext, CompletionTrigger, detect_context
from .completion_list import VirtualCompletionList
from .completion_overlay import CompletionOverlay
from .fuzzy import fuzzy_rank
from .path_search import Candidate, PathCandidate, PathSearchProvider, SlashCandidate

if TYPE_CHECKING:
    pass

# History file path — same location as prompt_toolkit's FileHistory used
_HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
_HISTORY_FILE = _HERMES_HOME / ".hermes_history"

# Slash-command value regex — matches entire input "/cmd" with word+hyphen chars.
_SLASH_FULL_RE = re.compile(r"^/([\w-]*)$")


def _sanitize_input_text(text: str) -> str:
    """Normalize input text for the multiline prompt.

    Keeps newlines (multiline support), strips bare CR, converts tabs to space,
    and strips other Unicode control/format characters.
    """
    sanitized: list[str] = []
    for ch in text:
        if ch == "\r":
            continue
        if ch == "\t":
            sanitized.append(" ")
            continue
        if unicodedata.category(ch).startswith("C") and ch != "\n":
            continue
        sanitized.append(ch)
    return "".join(sanitized)


@dataclass(frozen=True, slots=True)
class _PathSearchRequest:
    batch_key: str
    match_query: str
    root: Path
    insert_prefix: str


class HermesInput(TextArea, can_focus=True):
    """Multiline input bar (1–3 rows) with history, autocomplete, and ghost text.

    Extends TextArea for multiline support.  Shift+Enter inserts a newline;
    Enter submits.  Emits :class:`HermesInput.Submitted` on non-empty submit.
    """

    DEFAULT_CSS = """
    HermesInput {
        height: auto;
        max-height: 3;
        background: transparent;
        border: none;
        padding: 0;
        width: 1fr;
    }
    """

    BINDINGS = [
        Binding("ctrl+a",       "select_all",  "Select all",  show=False),
        Binding("ctrl+shift+z", "redo",        "Redo",        show=False),
    ]

    # --- Messages ---
    class Submitted(Message):
        """Emitted when the user submits input."""

        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    class FilesDropped(Message):
        """Emitted when terminal drag-and-drop pastes one or more local paths."""

        def __init__(self, paths: list[Path]) -> None:
            super().__init__()
            self.paths = paths

    def __init__(
        self,
        *,
        placeholder: str = "",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(
            text="",
            soft_wrap=True,
            compact=True,
            tab_behavior="focus",
            show_line_numbers=False,
            highlight_cursor_line=False,
            max_checkpoints=50,
            id=id,
            classes=classes,
        )
        self._history: list[str] = []
        self._history_idx: int = -1
        self._history_draft: str = ""
        self._slash_commands: list[str] = []
        self._suppress_autocomplete_once: bool = False
        self._sanitizing: bool = False

        # Autocomplete dispatcher state
        self._current_trigger: CompletionTrigger = CompletionTrigger(
            CompletionContext.NONE, "", 0,
        )
        self._raw_candidates: list[PathCandidate] = []
        self._path_debounce_timer: "Any | None" = None

    def on_mount(self) -> None:
        self._load_history()

    def on_unmount(self) -> None:
        if self._path_debounce_timer is not None:
            self._path_debounce_timer.stop()
            self._path_debounce_timer = None

    # --- Property bridges (old API → TextArea API) ---

    @property
    def value(self) -> str:
        return self.text

    @value.setter
    def value(self, v: str) -> None:
        # load_text resets undo history and fires Changed asynchronously.
        # Cursor goes to (0,0) after load_text; callers that need a specific
        # position should set cursor_position after.
        self.load_text(v)

    @property
    def content(self) -> str:
        return self.text

    @content.setter
    def content(self, v: str) -> None:
        self.load_text(_sanitize_input_text(v))

    @property
    def cursor_pos(self) -> int:
        """Flat cursor offset compatible with old single-line API."""
        row, col = self.cursor_location
        lines = self.text.split("\n")
        return sum(len(lines[i]) + 1 for i in range(row)) + col

    @cursor_pos.setter
    def cursor_pos(self, pos: int) -> None:
        lines = self.text.split("\n")
        row = 0
        for line in lines:
            if pos <= len(line):
                self.move_cursor((row, pos))
                return
            pos -= len(line) + 1
            row += 1
        self.move_cursor((len(lines) - 1, len(lines[-1])))

    @property
    def cursor_position(self) -> int:
        """Alias for cursor_pos (app.py uses both names)."""
        return self.cursor_pos

    @cursor_position.setter
    def cursor_position(self, pos: int) -> None:
        self.cursor_pos = pos

    def _location_to_flat(self, loc: tuple[int, int]) -> int:
        """Convert (row, col) TextArea location to flat string offset."""
        row, col = loc
        lines = self.text.split("\n")
        return sum(len(lines[i]) + 1 for i in range(row)) + col

    def replace_flat(self, text: str, start: int, end: int) -> None:
        """Replace flat-offset range with text. Bridge for app.py file-drop code."""
        lines = self.text.split("\n")
        s_row, s_col = 0, start
        for i, line in enumerate(lines):
            if s_col <= len(line):
                s_row = i
                break
            s_col -= len(line) + 1
        else:
            s_row = len(lines) - 1
            s_col = len(lines[-1]) if lines else 0
        e_row, e_col = 0, end
        for i, line in enumerate(lines):
            if e_col <= len(line):
                e_row = i
                break
            e_col -= len(line) + 1
        else:
            e_row = len(lines) - 1
            e_col = len(lines[-1]) if lines else 0
        self.replace(text, (s_row, s_col), (e_row, e_col))

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

    # --- Key handling ---

    async def _on_key(self, event: events.Key) -> None:
        """Override to handle special keys before TextArea's default handling.

        TextArea intercepts enter, tab, and navigation keys in its own _on_key,
        so all special keys must be handled here (not via BINDINGS).
        """
        if self.disabled and event.is_printable:
            event.prevent_default()
            return

        key = event.key

        # Submit
        if key == "enter":
            event.prevent_default()
            self.action_submit()
            return

        # Newline
        if key == "shift+enter":
            event.prevent_default()
            self.insert("\n")
            return

        # Tab: accept completion or ghost text
        if key == "tab":
            event.prevent_default()
            self.action_accept_autocomplete()
            return

        # Escape: dismiss overlay; else bubble to app interrupt/browse handler.
        # HistorySearchOverlay BINDINGS have priority=True — yield to it when visible.
        if key == "escape":
            if self._completion_overlay_visible():
                try:
                    from hermes_cli.tui.widgets import HistorySearchOverlay
                    hs = self.app.query_one(HistorySearchOverlay)
                    if hs.has_class("--visible"):
                        # HistorySearch handles this escape via priority BINDING
                        pass
                    else:
                        event.prevent_default()
                        self._hide_completion_overlay()
                        return
                except Exception:
                    event.prevent_default()
                    self._hide_completion_overlay()
                    return

        # PageUp/Down: route to completion overlay when visible
        if key == "pageup":
            if self._completion_overlay_visible():
                event.prevent_default()
                self.action_completion_page_up()
                return

        if key == "pagedown":
            if self._completion_overlay_visible():
                event.prevent_default()
                self.action_completion_page_down()
                return

        # Up: history prev if at top row; else overlay navigation or cursor up
        if key == "up":
            if self._completion_overlay_slash_only():
                event.prevent_default()
                self._hide_completion_overlay()
                self._suppress_autocomplete_once = True
                self.action_history_prev()
                return
            elif self._completion_overlay_visible():
                event.prevent_default()
                self._move_highlight(-1)
                return
            elif self.cursor_location[0] == 0:
                event.prevent_default()
                self.action_history_prev()
                return
            # else: let TextArea move cursor up

        # Down: history next if at bottom row; else overlay navigation or cursor down
        if key == "down":
            if self._completion_overlay_slash_only():
                event.prevent_default()
                self._hide_completion_overlay()
                self._suppress_autocomplete_once = True
                self.action_history_next()
                return
            elif self._completion_overlay_visible():
                event.prevent_default()
                self._move_highlight(+1)
                return
            else:
                last_row = self.text.count("\n")
                if self.cursor_location[0] >= last_row:
                    event.prevent_default()
                    self.action_history_next()
                    return
            # else: let TextArea move cursor down

        await super()._on_key(event)

    async def _on_paste(self, event: events.Paste) -> None:
        """Intercept terminal drag-and-drop before TextArea inserts raw path text."""
        dropped_paths = parse_dragged_file_paste(event.text)
        if dropped_paths:
            self.post_message(self.FilesDropped(dropped_paths))
            event._no_default_action = True
            event.stop()
            return
        try:
            self.app._flash_hint(f"{ICON_COPY}  {len(event.text)} chars pasted", 1.2)
        except Exception:
            pass
        await super()._on_paste(event)

    # --- TextArea change handler (replaces watch_value + watch_cursor_position) ---

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Sanitize text and update autocomplete on every content change.

        TextArea.Changed fires asynchronously, so by the time this runs,
        cursor_position has already been set by any synchronous code that
        followed the triggering edit (e.g. value.setter + cursor_position.setter).
        This eliminates the cursor-lag race that existed with Input.
        """
        if self._sanitizing:
            return
        raw = self.text
        sanitized = _sanitize_input_text(raw)
        if sanitized != raw:
            self._sanitizing = True
            try:
                cursor = self.cursor_location
                self.load_text(sanitized)
                self.move_cursor(cursor, select=False)
            finally:
                self._sanitizing = False
            return
        self._update_autocomplete()

    # --- Ghost text (Fish-style, via TextArea.suggestion) ---

    def update_suggestion(self) -> None:
        """Set ghost text from history. Called by TextArea after every edit."""
        current = self.text
        # Ghost text only for single-line non-empty text with cursor at end.
        # Mid-text cursor guard: suggestion must never appear when cursor is
        # mid-text, or action_cursor_right would corrupt the text on accept.
        if not current or "\n" in current:
            self.suggestion = ""
            return
        row, col = self.cursor_location
        if row != 0 or col != len(current):
            self.suggestion = ""
            return
        for entry in reversed(self._history):
            if entry.startswith(current) and entry != current:
                self.suggestion = entry[len(current):]
                return
        self.suggestion = ""

    # --- Actions ---

    def action_submit(self) -> None:
        """Save to history, post Submitted, then clear the input."""
        text = self.text.strip()
        if self.disabled or not text:
            return
        self._save_to_history(text)
        self._hide_completion_overlay()
        self.post_message(self.Submitted(text))
        # load_text("") resets undo history — correct post-submit state.
        self.load_text("")
        self._history_idx = -1
        self._suppress_autocomplete_once = False

    def action_history_prev(self) -> None:
        if self._completion_overlay_slash_only():
            self._hide_completion_overlay()
            self._suppress_autocomplete_once = True
        elif self._completion_overlay_visible():
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
        if self._completion_overlay_slash_only():
            self._hide_completion_overlay()
            self._suppress_autocomplete_once = True
        elif self._completion_overlay_visible():
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

    def action_completion_page_up(self) -> None:
        """PageUp: jump one page up in the completion list."""
        if not self._completion_overlay_visible():
            return
        try:
            clist = self.screen.query_one(VirtualCompletionList)
            if not clist.items:
                return
            page = max(1, clist.size.height - 1)
            clist.highlighted = max(0, clist.highlighted - page)
        except NoMatches:
            pass

    def action_completion_page_down(self) -> None:
        """PageDown: jump one page down in the completion list."""
        if not self._completion_overlay_visible():
            return
        try:
            clist = self.screen.query_one(VirtualCompletionList)
            if not clist.items:
                return
            page = max(1, clist.size.height - 1)
            clist.highlighted = min(len(clist.items) - 1, clist.highlighted + page)
        except NoMatches:
            pass

    # --- Autocomplete ---

    def _update_autocomplete(self) -> None:
        """Dispatch to the correct completion provider based on context."""
        with measure("input._update_autocomplete", budget_ms=4.0):
            if self._suppress_autocomplete_once:
                self._suppress_autocomplete_once = False
                return
            if getattr(self.app, "choice_overlay_active", False):
                self._hide_completion_overlay()
                return

            # Slash commands: use full value (not cursor position).
            # Multiline input starting with '/' is not a slash command.
            if (
                "\n" not in self.value
                and self.value.startswith("/")
                and _SLASH_FULL_RE.match(self.value)
            ):
                fragment = self.value[1:]
                self._current_trigger = CompletionTrigger(
                    CompletionContext.SLASH_COMMAND, fragment, 1,
                )
                self._raw_candidates = []
                self._show_slash_completions(fragment)
                return

            trigger = detect_context(self.value, self.cursor_position)
            self._current_trigger = trigger
            self._raw_candidates = []

            if trigger.context is CompletionContext.SLASH_COMMAND:
                self._show_slash_completions(trigger.fragment)
            elif trigger.context in (
                CompletionContext.PATH_REF,
                CompletionContext.PLAIN_PATH_REF,
                CompletionContext.ABSOLUTE_PATH_REF,
            ):
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
        with measure("slash_completions.fuzzy_rank", budget_ms=2.0, silent=True):
            ranked = fuzzy_rank(fragment, items, limit=50)
        if not ranked:
            hint = ""
            duration = 1.5
            if fragment and len(fragment) >= 2:
                all_slash = [SlashCandidate(display=c, command=c) for c in self._slash_commands]
                suggestions = fuzzy_rank(fragment, all_slash, limit=1)
                if suggestions:
                    hint = f"Did you mean: {suggestions[0].command}?"
                    duration = 2.0
                else:
                    hint = f"Unknown command: /{fragment}"
                    duration = 1.5
            elif fragment:
                hint = f"Unknown command: /{fragment}"
                duration = 1.5
            if hint:
                try:
                    self.app._flash_hint(hint, duration)
                except Exception:
                    pass
            self._hide_completion_overlay()
            return
        self._set_overlay_mode(slash_only=True)
        self._push_to_list(ranked)
        self._show_completion_overlay()

    def _show_path_completions(self, fragment: str) -> None:
        if self._path_debounce_timer is not None:
            self._path_debounce_timer.stop()
            self._path_debounce_timer = None
        self._set_overlay_mode(slash_only=False)
        self._push_to_list([])
        self._set_searching(True)
        self._show_completion_overlay()
        self._path_debounce_timer = self.set_timer(
            0.12, lambda: self._fire_path_search(fragment)
        )

    def _fire_path_search(self, fragment: str) -> None:
        self._path_debounce_timer = None
        if self._current_trigger.context not in (
            CompletionContext.PATH_REF,
            CompletionContext.PLAIN_PATH_REF,
            CompletionContext.ABSOLUTE_PATH_REF,
        ):
            return
        if self._current_trigger.fragment != fragment:
            return
        try:
            provider = self.screen.query_one(PathSearchProvider)
        except NoMatches:
            return
        request = self._resolve_path_search_request()
        provider.search(
            request.batch_key,
            request.root,
            match_query=request.match_query,
            insert_prefix=request.insert_prefix,
        )

    def _working_directory(self) -> Path:
        app = getattr(self, "app", None)
        getter = getattr(app, "get_working_directory", None)
        if callable(getter):
            return getter()
        return Path.cwd()

    def _resolve_path_search_request(self) -> _PathSearchRequest:
        trig = self._current_trigger
        cwd = self._working_directory()
        if trig.context is CompletionContext.PATH_REF:
            raw = trig.fragment
        else:
            raw = self.value[trig.start:self.cursor_position]

        if not raw:
            return _PathSearchRequest("", "", cwd, "")

        if raw.startswith("~/"):
            anchor = Path.home()
            remainder = raw[2:]
        elif raw.startswith("/"):
            anchor = Path("/")
            remainder = raw[1:]
        else:
            anchor = cwd
            remainder = raw

        if raw.endswith("/"):
            dir_part = remainder.rstrip("/")
            leaf = ""
        else:
            dir_part, _, leaf = remainder.rpartition("/")

        intended_base = (anchor / dir_part).resolve(strict=False) if dir_part else anchor
        base = intended_base
        missing_parts: list[str] = []
        while not (base.exists() and base.is_dir()):
            part = base.name
            parent = base.parent
            if part:
                missing_parts.append(part)
            if parent == base:
                break
            base = parent
        if not (base.exists() and base.is_dir()):
            base = anchor
        query_parts = list(reversed(missing_parts))
        if leaf:
            query_parts.append(leaf)
        match_query = "/".join(part for part in query_parts if part)
        insert_prefix = raw[:-len(match_query)] if match_query else raw
        return _PathSearchRequest(raw, match_query, base, insert_prefix)

    def _set_searching(self, value: bool) -> None:
        try:
            clist = self.screen.query_one(VirtualCompletionList)
            clist.searching = value
        except Exception:
            pass

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
        if self._path_debounce_timer is not None:
            self._path_debounce_timer.stop()
            self._path_debounce_timer = None
        self._set_searching(False)
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

    def _completion_overlay_slash_only(self) -> bool:
        try:
            overlay = self.screen.query_one(CompletionOverlay)
            return overlay.has_class("--visible") and overlay.has_class("--slash-only")
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
        if self._current_trigger.context not in (
            CompletionContext.PATH_REF,
            CompletionContext.PLAIN_PATH_REF,
            CompletionContext.ABSOLUTE_PATH_REF,
        ):
            return
        request = self._resolve_path_search_request()
        if message.query != request.batch_key:
            return

        if len(self._raw_candidates) < 4096:
            self._raw_candidates.extend(message.batch)
        ranked = fuzzy_rank(
            request.match_query or self._current_trigger.fragment,
            self._raw_candidates,
            limit=200,
        )
        self._push_to_list(ranked)
        if message.final:
            self._set_searching(False)

    def _push_to_list(self, candidates: list[Candidate]) -> None:
        try:
            clist = self.screen.query_one(VirtualCompletionList)
        except NoMatches:
            return
        request = self._resolve_path_search_request()
        clist.current_query = request.match_query or self._current_trigger.fragment
        clist.items = tuple(candidates)

    # --- Accept / dismiss ---

    def action_accept_autocomplete(self) -> None:
        """Tab: accept highlighted completion or ghost-text suggestion.

        When the completion overlay is not visible, Tab delegates to
        action_cursor_right() which accepts the ghost-text suggestion (if any).
        """
        if not self._completion_overlay_visible():
            self.action_cursor_right()
            return
        try:
            clist = self.screen.query_one(VirtualCompletionList)
        except NoMatches:
            return
        if not clist.items or clist.highlighted < 0:
            return

        # P0-G: mid-cursor guard — cursor not at end means user repositioned it.
        if self.cursor_position < len(self.value):
            self._hide_completion_overlay()
            return

        c = clist.items[clist.highlighted]
        trig = self._current_trigger

        if isinstance(c, SlashCandidate):
            new_value = c.command + " "
            new_cursor = len(new_value)
        elif isinstance(c, PathCandidate):
            insert_text = c.insert_text or c.display
            if trig.context in (
                CompletionContext.PLAIN_PATH_REF,
                CompletionContext.ABSOLUTE_PATH_REF,
            ):
                if trig.context is CompletionContext.PLAIN_PATH_REF and not c.insert_text:
                    prefix_end = self.value.index("/", trig.start) + 1
                    path_prefix = self.value[trig.start:prefix_end]
                    insert_text = f"{path_prefix}{c.display}"
                before = self.value[:trig.start]
                after = self.value[self.cursor_position:]
                tail = " " if not after else ""
                new_value = f"{before}{insert_text}{tail}{after}"
                new_cursor = len(before) + len(insert_text) + len(tail)
            else:
                # PATH_REF: replace @fragment span; trig.start - 1 is the @.
                before = self.value[: trig.start - 1]
                after = self.value[self.cursor_position:]
                tail = " " if not after else ""
                new_value = f"{before}@{insert_text}{tail}{after}"
                new_cursor = len(before) + 1 + len(insert_text) + len(tail)
        else:
            return

        self.value = new_value
        self.cursor_position = new_cursor
        self._hide_completion_overlay()

    def action_dismiss_autocomplete(self) -> None:
        """Dismiss completion overlay without affecting agent-interrupt semantics."""
        if self._completion_overlay_visible():
            self._hide_completion_overlay()

    # --- Convenience ---

    def insert_text(self, text: str) -> None:
        """Insert text at cursor position (for paste support / external callers)."""
        text = _sanitize_input_text(text)
        if not text:
            return
        self.insert(text)

    def clear(self) -> None:
        """Clear the input content and reset undo history."""
        self.load_text("")
