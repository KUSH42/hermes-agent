"""Custom input widget for Hermes TUI.

Extends Textual's built-in Input widget to get selection, clipboard, mouse
drag, shift+arrow, and all standard keybindings for free.  Layers
Hermes-specific features on top:

- History: backed by ~/.hermes/.hermes_history via FileHistory format
- Autocomplete: multi-context dispatcher (slash commands, path refs)
- Ghost text: native Input.suggester + HistorySuggester (Fish-style)
- Spinner text: rendered via the Input placeholder while disabled
- Property bridge: content/cursor_pos aliases for callers still using old API
"""

from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hermes_cli.file_drop import parse_dragged_file_paste
from hermes_cli.tui.perf import measure

from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Input, Static

from hermes_cli.tui.constants import ICON_COPY
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


def _sanitize_input_text(text: str) -> str:
    """Normalize input text for the single-line prompt.

    Strips Unicode control / format characters that should not survive into
    prompts or slash commands. Newlines and tabs are normalized to spaces so
    pasted multi-line content doesn't inject hidden structure into the input.
    """
    sanitized: list[str] = []
    for ch in text:
        if ch in ("\n", "\r", "\t"):
            sanitized.append(" ")
            continue
        if unicodedata.category(ch).startswith("C"):
            continue
        sanitized.append(ch)
    return "".join(sanitized)


@dataclass(frozen=True, slots=True)
class _PathSearchRequest:
    batch_key: str
    match_query: str
    root: Path
    insert_prefix: str


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
        Binding("up",       "history_prev",           "Previous history",     show=False),
        Binding("down",     "history_next",            "Next history",         show=False),
        Binding("pageup",   "completion_page_up",      "Page up completion",   show=False),
        Binding("pagedown", "completion_page_down",    "Page down completion", show=False),
        Binding("escape",   "dismiss_autocomplete",    "Dismiss",              show=False),
        Binding("tab",      "accept_autocomplete",     "Accept completion",    show=False),
        Binding("ctrl+a",   "select_all",              "Select all",           show=False),
    ]

    # Spinner text shown when disabled (set by app's _tick_spinner)
    spinner_text: reactive[str] = reactive("", repaint=True)

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
        self._path_debounce_timer: "Any | None" = None
        self._sanitizing_value = False

    def on_mount(self) -> None:
        self._load_history()

    def on_unmount(self) -> None:
        if self._path_debounce_timer is not None:
            self._path_debounce_timer.stop()
            self._path_debounce_timer = None

    # --- Property bridges (old API → Input API) ---

    @property
    def content(self) -> str:
        return self.value

    @content.setter
    def content(self, val: str) -> None:
        self.value = _sanitize_input_text(val)

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

    def _on_paste(self, event: events.Paste) -> None:
        """Intercept terminal drag-and-drop before Input inserts raw path text."""
        dropped_paths = parse_dragged_file_paste(event.text)
        if dropped_paths:
            self.post_message(self.FilesDropped(dropped_paths))
            event.stop()
            return
        # Flash paste hint before letting Input handle the paste
        try:
            from hermes_cli.tui.constants import ICON_COPY
            self.app._flash_hint(f"{ICON_COPY}  {len(event.text)} chars pasted", 1.2)
        except Exception:
            pass
        super()._on_paste(event)

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

    def watch_value(self, value: str) -> None:
        if self._sanitizing_value:
            return
        sanitized = _sanitize_input_text(value)
        if sanitized != value:
            self._sanitizing_value = True
            try:
                cursor_prefix = _sanitize_input_text(value[: self.cursor_position])
                self.value = sanitized
                self.cursor_position = min(len(sanitized), len(cursor_prefix))
            finally:
                self._sanitizing_value = False
            return
        self._update_autocomplete()
        # Suggester (ghost text) is driven natively by Input — no manual hook.

    def watch_cursor_position(self, _cursor_position: int) -> None:
        """Re-run completion after cursor updates.

        Input value and cursor reactives do not settle in lockstep. During
        typing, ``watch_value`` can observe the new text with the previous
        cursor position, which makes completion lag one character behind.
        The cursor watcher applies the same update once the final cursor
        location is known.
        """
        if self._sanitizing_value:
            return
        self._update_autocomplete()

    def _update_autocomplete(self) -> None:
        """Dispatch to the correct completion provider based on context.

        Perf target: <4 ms total (60 FPS budget = 16.67 ms; autocomplete is
        ~25 % of that budget).  Measured via TEXTUAL_LOG=1 + [PERF] filter.
        Torture test: 100 chars/s input while a 50 k-file tree is being walked.
        """
        with measure("input._update_autocomplete", budget_ms=4.0):
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
        self._set_searching(True)   # show "searching…" while debounce + walk run
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
        if self._current_trigger.context not in (
            CompletionContext.PATH_REF,
            CompletionContext.PLAIN_PATH_REF,
            CompletionContext.ABSOLUTE_PATH_REF,
        ):
            return
        if message.query != self._current_trigger.fragment:
            return

        if len(self._raw_candidates) < 4096:
            self._raw_candidates.extend(message.batch)
        request = self._resolve_path_search_request()
        ranked = fuzzy_rank(
            request.match_query or self._current_trigger.fragment,
            self._raw_candidates,
            limit=200,
        )
        self._push_to_list(ranked)
        # Clear searching state once the final batch arrives
        if message.final:
            self._set_searching(False)

    def _push_to_list(self, candidates: list[Candidate]) -> None:
        try:
            clist = self.screen.query_one(VirtualCompletionList)
        except NoMatches:
            return
        # Propagate current query so empty-state label shows "no results for X"
        request = self._resolve_path_search_request()
        clist.current_query = request.match_query or self._current_trigger.fragment
        clist.items = tuple(candidates)

    # --- Accept / dismiss ---

    def action_accept_autocomplete(self) -> None:
        """Tab: accept highlighted completion or ghost-text suggestion.

        When the completion overlay is not visible the overlay's item list may
        still contain stale candidates from a prior interaction (highlighted=0).
        In that case Tab must NOT accept those stale candidates — instead it
        delegates to the native Input cursor-right which accepts ghost text.
        """
        if not self._completion_overlay_visible():
            # No active overlay: let Tab accept the ghost-text suggestion.
            self.action_cursor_right()
            return
        try:
            clist = self.screen.query_one(VirtualCompletionList)
        except NoMatches:
            return
        if not clist.items or clist.highlighted < 0:
            return

        # P0-G: mid-cursor guard — if the cursor is not at the end of the
        # typed fragment, the user has repositioned it.  Accept would corrupt
        # multi-token inputs, so dismiss only without splicing.
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
        """Escape: dismiss completion overlay only; preserve agent-interrupt semantics."""
        if self._completion_overlay_visible():
            self._hide_completion_overlay()
            # Consume the key so the app-level escape handler doesn't also fire
            return
        # No overlay — let escape bubble to HermesApp.on_key for interrupt/browse

    # --- Convenience ---



    def insert_text(self, text: str) -> None:
        """Insert text at cursor position (for paste support / external callers)."""
        text = _sanitize_input_text(text)
        if not text:
            return
        pos = self.cursor_position
        self.value = self.value[:pos] + text + self.value[pos:]
        self.cursor_position = pos + len(text)

    def clear(self) -> None:
        """Clear the input content."""
        self.value = ""
        self.cursor_position = 0
