"""HermesInput — multiline input bar with history, autocomplete, and ghost text.

Extends Textual's TextArea for multiline (1–3 row) support.  Layers
Hermes-specific features on top via mixins:

- _HistoryMixin: persistent history + Fish-style ghost text
- _PathCompletionMixin: path resolver, overlay visibility, batch results
- _AutocompleteMixin: dispatch logic, accept/dismiss actions
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hermes_cli.file_drop import detect_file_drop_text, parse_dragged_file_paste

from rich.cells import cell_len
from textual import events
from textual.binding import Binding
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import TextArea

from hermes_cli.tui.constants import ICON_COPY
from hermes_cli.tui.io_boundary import safe_run

from ._autocomplete import _AutocompleteMixin
from ._constants import _sanitize_input_text
from ._history import _HistoryMixin
from ._path_completion import _PathCompletionMixin

if TYPE_CHECKING:
    pass


class HermesInput(_HistoryMixin, _AutocompleteMixin, _PathCompletionMixin, TextArea, can_focus=True):
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
        Binding("ctrl+shift+a", "select_all",      "Select all",  show=False),
        Binding("ctrl+shift+z", "redo",             "Redo",        show=False),
        Binding("ctrl+r",       "rev_search",       "History",     show=False),
        Binding("ctrl+g",       "abort_rev_search", "",            show=False, priority=True),
        Binding("ctrl+u",       "kill_line_start",  "",            show=False, priority=True),
        Binding("ctrl+k",       "kill_line_end",    "",            show=False, priority=True),
        Binding("alt+up",       "history_prev_prompt", "",         show=False, priority=True),
        Binding("alt+down",     "history_next_prompt", "",         show=False, priority=True),
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
        _default_placeholder = "Type a message  @file  /  commands"
        _effective_placeholder = placeholder if placeholder else _default_placeholder
        super().__init__(
            text="",
            soft_wrap=True,
            compact=True,
            tab_behavior="indent",
            show_line_numbers=False,
            highlight_cursor_line=False,
            max_checkpoints=50,
            placeholder=_effective_placeholder,
            id=id,
            classes=classes,
        )
        self._history: list[str] = []
        self._history_idx: int = -1
        self._history_draft: str = ""
        self._history_loading: bool = False
        self._slash_commands: list[str] = []
        self._slash_descriptions: dict[str, str] = {}
        self._slash_args_hints: dict[str, str] = {}
        self._slash_keybind_hints: dict[str, str] = {}
        self._slash_subcommands: dict[str, list[str]] = {}
        self._idle_placeholder: str = _effective_placeholder
        self._chevron_label: str = "❯ "
        self._rev_mode: bool = False
        self._rev_query: str = ""
        self._rev_idx: int = -1
        self._input_height_override: int = 3
        self._suppress_autocomplete_once: bool = False
        self._sanitizing: bool = False
        self._handling_file_drop: bool = False
        self._last_slash_hint_fragment: str = ""

        from hermes_cli.tui.completion_context import CompletionContext, CompletionTrigger
        self._current_trigger: CompletionTrigger = CompletionTrigger(
            CompletionContext.NONE, "", 0,
        )
        from hermes_cli.tui.path_search import PathCandidate
        self._raw_candidates: list[PathCandidate] = []
        self._path_debounce_timer: "object | None" = None
        self._draft_stash: str | None = None
        self._write_fail_warned: bool = False

    # --- Error state reactive ---
    error_state: reactive[str | None] = reactive(None)

    def on_mount(self) -> None:
        self._load_history()
        self._sync_height_to_content()

    def on_resize(self, event: events.Resize) -> None:
        self._sync_height_to_content()

    def on_click(self, event: Any) -> None:
        """Middle-click (button=2) pastes primary selection on Linux/X11."""
        import sys
        if getattr(event, "button", 1) != 2:
            return
        event.stop()
        if sys.platform != "linux":
            return
        try:
            self.app
            has_app = True
        except Exception:
            has_app = False
        if not has_app:
            try:
                from hermes_cli.tui import input_widget as compat
                proc = compat.subprocess.run(
                    ["xclip", "-selection", "primary", "-o"],
                    capture_output=True,
                    text=True,
                    timeout=1,
                )
                if getattr(proc, "returncode", 1) == 0 and getattr(proc, "stdout", ""):
                    self.insert(proc.stdout)
            except Exception:
                pass
            return
        safe_run(
            self,
            ["xclip", "-selection", "primary", "-o"],
            timeout=1,
            on_success=lambda out, err, rc: (
                self.insert(out) if (self.is_mounted and out) else None
            ),
        )

    def on_unmount(self) -> None:
        if self._path_debounce_timer is not None:
            self._path_debounce_timer.stop()
            self._path_debounce_timer = None

    # --- Placeholder management ---

    def _refresh_placeholder(self) -> None:
        """Single source of truth for placeholder text.

        Priority (highest→lowest): locked/disabled > error_state > idle.
        """
        if self.disabled:
            self.placeholder = "running…  Ctrl+C to cancel"
        elif self.error_state:
            snippet = self.error_state[:40] + ("…" if len(self.error_state) > 40 else "")
            self.placeholder = f"⚠ {snippet}  ·  Esc to clear"
        else:
            self.placeholder = self._idle_placeholder

    def watch_error_state(self, value: str | None) -> None:
        self._refresh_placeholder()

    def _set_input_locked(self, locked: bool) -> None:
        """Sync visual locked state (class + placeholder). Does NOT set self.disabled."""
        if not getattr(self, "is_mounted", False):
            return
        self._refresh_placeholder()
        if locked:
            self.add_class("--locked")
        else:
            self.remove_class("--locked")

    # --- Draft stash ---

    def save_draft_stash(self) -> None:
        """Save current text as draft stash when at history_idx == -1 (live draft)."""
        if self._history_idx == -1:
            self._draft_stash = self.text

    def _sync_height_to_content(self) -> None:
        """Keep the input 1-3 rows tall based only on visible text rows."""
        try:
            width = int(getattr(getattr(self, "content_size", None), "width", 0) or 0)
        except Exception:
            width = 0
        width = max(1, width)
        rows = 0
        for line in (self.text or "").split("\n"):
            line_width = max(1, cell_len(line))
            rows += max(1, (line_width + width - 1) // width)
        self.styles.max_height = 3
        self.styles.height = max(1, min(3, rows or 1))

    # --- Property bridges (old API → TextArea API) ---

    @property
    def value(self) -> str:
        return self.text

    @value.setter
    def value(self, v: str) -> None:
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

    # --- Key handling ---

    async def _on_key(self, event: events.Key) -> None:
        """Override to handle special keys before TextArea's default handling."""
        if self.disabled and event.is_printable:
            event.prevent_default()
            return

        key = event.key

        if key == "enter":
            event.prevent_default()
            raw = self.text.strip()
            if raw:
                try:
                    drop_match = detect_file_drop_text(raw)
                    if drop_match is not None:
                        self.load_text("")
                        self.post_message(self.FilesDropped([drop_match.path]))
                        return
                except Exception:
                    pass
            # B-2: Enter accepts highlighted completion when overlay is visible
            if self._completion_overlay_visible():
                try:
                    from hermes_cli.tui.completion_list import VirtualCompletionList
                    clist = self.screen.query_one(VirtualCompletionList)
                    exact_slash = raw.startswith("/") and raw in getattr(self, "_slash_commands", [])
                    if clist.highlighted >= 0 and not exact_slash:
                        self.action_accept_autocomplete()
                        return
                except Exception:
                    pass
            self.action_submit()
            return

        if key == "shift+enter":
            event.prevent_default()
            self.insert("\n")
            return

        if key == "tab":
            event.prevent_default()
            self.action_accept_autocomplete()
            return

        if key == "escape":
            event.stop()
            event.prevent_default()
            if self.error_state is not None and not self.text.strip():
                self.error_state = None
                return
            if getattr(self, "_rev_mode", False):
                self._exit_rev_search()
                return
            try:
                from hermes_cli.tui.widgets import HistorySearchOverlay
                hs = self.app.query_one(HistorySearchOverlay)
                if hs.has_class("--visible"):
                    hs.action_dismiss()
                    return
            except Exception:
                pass
            if self._completion_overlay_visible():
                self._hide_completion_overlay()
                return
            try:
                self.app.on_key(event)
            except Exception:
                pass
            return

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

        if key == "ctrl+shift+up":
            event.prevent_default()
            self._input_height_override = 3
            self.styles.max_height = self._input_height_override
            self._sync_height_to_content()
            try:
                self.app._flash_hint(f"Input height: {self._input_height_override}", 1.5)  # type: ignore[attr-defined]
            except Exception:
                pass
            return

        if key == "ctrl+shift+down":
            event.prevent_default()
            self._input_height_override = 3
            self.styles.max_height = self._input_height_override
            self._sync_height_to_content()
            try:
                self.app._flash_hint(f"Input height: {self._input_height_override}", 1.5)  # type: ignore[attr-defined]
            except Exception:
                pass
            return

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

        # Forward "c" to app.on_key when UsageOverlay is visible, so the
        # app-level copy handler can intercept it before TextArea inserts the char.
        # Call event.stop() to prevent the natural DOM bubble (which would call
        # app.on_key a second time via Textual's event propagation).
        if key == "c":
            try:
                from hermes_cli.tui.overlays import UsageOverlay as _UO
                _uov = self.app.query_one(_UO)
                if _uov.has_class("--visible"):
                    self.app.on_key(event)
                    event.stop()
                    event.prevent_default()
                    return
            except Exception:
                pass

        await super()._on_key(event)

    async def _on_paste(self, event: events.Paste) -> None:
        """Intercept terminal drag-and-drop before TextArea inserts raw path text."""
        try:
            dropped_paths = parse_dragged_file_paste(event.text)
        except Exception:
            dropped_paths = None
        if dropped_paths:
            self.post_message(self.FilesDropped(dropped_paths))
            event._no_default_action = True
            event.stop()
            return
        event._no_default_action = True
        try:
            self.app._flash_hint(f"{ICON_COPY}  {len(event.text)} chars pasted", 1.2)
        except Exception:
            pass
        await super()._on_paste(event)

    # --- TextArea change handler ---

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Sanitize text and update autocomplete on every content change."""
        self._sync_height_to_content()
        if self._sanitizing:
            return
        # If the user (or any external mutation) edited the text while we were
        # browsing history, drop the cached history index so the next arrow-up
        # starts at the most-recent entry again.
        if (
            not self._history_loading
            and self._history_idx != -1
            and not self._handling_file_drop
        ):
            hist = self._history
            idx = self._history_idx
            if not (0 <= idx < len(hist) and self.text == hist[idx]):
                self._history_idx = -1
        # Invalidate draft stash if user typed something different from it
        draft_stash = getattr(self, "_draft_stash", None)
        if draft_stash is not None and self._history_idx == -1:
            if self.text != draft_stash:
                self._draft_stash = None
        if not self._handling_file_drop:
            raw_text = self.text.strip()
            if raw_text and "\n" not in raw_text:
                stripped = raw_text
                if stripped and stripped[0] in ('"', "'") and len(stripped) >= 3:
                    stripped = stripped[1:-1]
                if len(stripped) > 1 and stripped.startswith(("/", "~", "file://")):
                    match = detect_file_drop_text(raw_text)
                    if match is not None:
                        self._handling_file_drop = True
                        try:
                            self.post_message(self.FilesDropped([match.path]))
                            self.load_text("")
                        finally:
                            self._handling_file_drop = False
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
        # Toggle bash-passthrough mode indicator
        _is_bash = self.text.lstrip().startswith("!")
        if _is_bash != self.has_class("--bash-mode"):
            self.set_class(_is_bash, "--bash-mode")
            self._sync_bash_mode_ui(_is_bash)

    # --- Actions ---

    def action_submit(self) -> None:
        """Save to history, post Submitted, then clear the input."""
        if getattr(self, "_rev_mode", False):
            self._exit_rev_mode(accept=True)
        text = self.text.strip()
        if self.disabled or not text:
            return
        self._save_to_history(text)
        self._hide_completion_overlay()
        self.post_message(self.Submitted(text))
        self.load_text("")
        sync_height = getattr(self, "_sync_height_to_content", None)
        if callable(sync_height):
            sync_height()
        self._history_idx = -1
        self._suppress_autocomplete_once = False
        if self._input_height_override != 3:
            self._input_height_override = 3
            self.styles.max_height = 3
        self._last_slash_hint_fragment = ""

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
            if self._draft_stash is None:
                self._history_draft = self.value
            self._history_idx = len(self._history) - 1
        elif self._history_idx > 0:
            self._history_idx -= 1
        else:
            return
        self._history_load(self._history[self._history_idx])

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
            self._history_load(self._history[self._history_idx])
        else:
            self._history_idx = -1
            if self._draft_stash is not None:
                self._history_load(self._draft_stash)
                self._draft_stash = None
            else:
                self._history_load(self._history_draft)

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

    # --- Bash mode UI sync ---

    def _sync_bash_mode_ui(self, is_bash: bool) -> None:
        """Sync placeholder, chevron glyph, hint, and legend to bash-mode state."""
        if is_bash:
            # Override idle placeholder temporarily for bash mode
            self.placeholder = "! shell mode  ·  Enter runs  ·  Ctrl+C clear"
        else:
            refresh = getattr(self, "_refresh_placeholder", None)
            if callable(refresh):
                refresh()
            else:
                self.placeholder = getattr(self, "_idle_placeholder", "")
        try:
            from textual.widgets import Label
            self.query_one("#input-chevron", Label).update("$ " if is_bash else self._chevron_label)
        except Exception:
            pass
        try:
            if is_bash:
                self.app._flash_hint("bash  ·  Enter: run  ·  Ctrl+C clear", 30.0)
            else:
                self.app.feedback.cancel("hint-bar")
        except Exception:
            pass
        try:
            from hermes_cli.tui.widgets.input_legend_bar import InputLegendBar
            legend = self.app.query_one("#input-legend-bar", InputLegendBar)
            if is_bash:
                legend.show_legend("bash")
            else:
                legend.hide_legend()
        except Exception:
            pass

    # --- Rev-search abort ---

    def action_abort_rev_search(self) -> None:
        """Ctrl+G: abort rev-search, restoring pre-search value."""
        if not getattr(self, "_rev_mode", False):
            return
        self._exit_rev_mode(accept=False)

    # --- Readline kill bindings ---

    def action_kill_line_start(self) -> None:
        """Ctrl+U: delete from cursor to start of current line."""
        cursor_row, cursor_col = self.cursor_location
        if cursor_col == 0:
            return
        self.delete(start=(cursor_row, 0), end=(cursor_row, cursor_col))

    def action_kill_line_end(self) -> None:
        """Ctrl+K: delete from cursor to end of current line."""
        row, col = self.cursor_location
        line = self.get_line(row)
        end_col = len(line.plain)
        if col >= end_col:
            return
        self.delete(start=(row, col), end=(row, end_col))

    # --- History skip-command navigation ---

    def action_history_prev_prompt(self) -> None:
        """Alt+Up: jump to the previous turn."""
        self.app.action_jump_turn_prev()

    def action_history_next_prompt(self) -> None:
        """Alt+Down: jump to the next turn."""
        self.app.action_jump_turn_next()
