"""Overlay/dialog classes for the Hermes TUI.

R3 Phase B deleted the 5 interrupt widget bodies (ClarifyWidget,
ApprovalWidget, SudoWidget, SecretWidget, UndoConfirmOverlay) — they are
now variant modes of ``InterruptOverlay`` in ``overlays/interrupt.py``.
The original class names are re-exported as alias proxies from
``overlays._aliases`` for backward compatibility.

Remaining: history-search types and helpers, TurnResultItem, KeymapOverlay,
HistorySearchOverlay.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

_log = logging.getLogger(__name__)

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Static

from .renderers import CopyableRichLog
from hermes_cli.tui.overlays._modal_mixin import ModalOverlayMixin
from hermes_cli.tui.resize_utils import crosses_threshold

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp


# ---------------------------------------------------------------------------
# R3 Phase B: Legacy interrupt widget aliases
# ---------------------------------------------------------------------------
# ClarifyWidget / ApprovalWidget / SudoWidget / SecretWidget /
# UndoConfirmOverlay class bodies were deleted in R3 Phase B. The names
# re-export as alias proxies from overlays._aliases — they resolve to the
# canonical InterruptOverlay instance via CSS-type registration +
# _AliasMeta.__instancecheck__.
from hermes_cli.tui.overlays._aliases import (  # noqa: F401,E402
    ApprovalWidget,
    ClarifyWidget,
    SecretWidget,
    SudoWidget,
    UndoConfirmOverlay,
)


# ---------------------------------------------------------------------------
# History Search types + helpers
# ---------------------------------------------------------------------------

@dataclass
class _TurnEntry:
    """Metadata for one indexed turn (frozen snapshot; never mutated)."""
    panel: "Any"  # MessagePanel — avoid circular import
    index: int          # 1-based (turn 1 = first ever)
    user_text: str      # paired text from preceding UserMessagePanel
    assistant_text: str # full plain assistant prose from the panel
    search_text: str    # combined contiguous-search haystack
    display: str        # user-facing row label


@dataclass(frozen=True, slots=True)
class TurnCandidate:
    """Candidate for fuzzy_rank() carrying a _TurnEntry reference.

    Re-implements Candidate fields inline (rather than subclassing) to avoid
    the Python slots-inheritance restriction when both base and child are
    frozen+slotted dataclasses across different module scopes.
    fuzzy_rank() only reads .display and calls dataclasses.replace(), which
    works fine on this standalone frozen dataclass.
    """
    display: str
    score: int = 0
    match_spans: tuple[tuple[int, int], ...] = ()
    entry: "_TurnEntry | None" = field(default=None)


@dataclass(frozen=True)
class _SearchResult:
    """Result from _substring_search — carries match metadata for rendering."""
    entry: _TurnEntry
    match_spans: tuple[tuple[int, int], ...]  # relative to search_text
    first_match_offset: int


def _substring_search(
    query: str,
    entries: list[_TurnEntry],
    limit: int = 20,
) -> list[_SearchResult]:
    """Casefolded contiguous substring search with span tracking.

    Searches combined user+assistant text.  Returns results sorted by:
    1. Match count × 10 + word-boundary bonus (5) + char-0 bonus (2)
    2. Recency (newer wins on tie)
    """
    needle = query.casefold()
    results: list[tuple[_TurnEntry, list[tuple[int, int]], int]] = []
    for entry in entries:
        haystack = entry.search_text.casefold()
        spans: list[tuple[int, int]] = []
        offset = 0
        while True:
            pos = haystack.find(needle, offset)
            if pos == -1:
                break
            spans.append((pos, pos + len(needle)))
            offset = pos + len(needle)  # no overlap
        if spans:
            score = len(spans) * 10
            first = spans[0][0]
            if first == 0 or entry.search_text[first - 1] in " \n\t/._-":
                score += 5
            results.append((entry, spans, score))
    results.sort(key=lambda r: (-r[2], -r[0].index))
    return [
        _SearchResult(entry=e, match_spans=tuple(s), first_match_offset=s[0][0])
        for e, s, _ in results[:limit]
    ]


def _highlight_spans(text: str, spans: tuple[tuple[int, int], ...]) -> str:
    """Wrap matched character spans in Rich markup for accent highlighting."""
    if not spans:
        return _escape_markup(text)
    parts: list[str] = []
    prev = 0
    for start, end in sorted(spans):
        if start > prev:
            parts.append(_escape_markup(text[prev:start]))
        parts.append(f"[bold $accent]{_escape_markup(text[start:end:])}[/]")
        prev = end
    if prev < len(text):
        parts.append(_escape_markup(text[prev:]))
    return "".join(parts)


def _escape_markup(text: str) -> str:
    """Escape Rich markup brackets so raw user text renders literally."""
    return text.replace("[", r"\[").replace("]", r"\]")


def _extract_snippet(
    search_text: str,
    match_spans: tuple[tuple[int, int], ...],
    context_chars: int = 40,
) -> str:
    """Extract a context window around the first match with accent highlighting."""
    if not match_spans:
        raw = search_text[:80]
        suffix = "…" if len(search_text) > 80 else ""
        return _escape_markup(raw) + suffix
    first_start = match_spans[0][0]
    last_end = match_spans[-1][1]
    window_start = max(0, first_start - context_chars)
    window_end = min(len(search_text), last_end + context_chars)
    # Collapse to single line — strip internal newlines for compact display
    snippet_raw = search_text[window_start:window_end].replace("\n", " ")
    # Offset spans into local snippet coordinates
    local_spans = tuple(
        (s - window_start, e - window_start)
        for s, e in match_spans
        if s >= window_start and e <= window_end
    )
    prefix = "…" if window_start > 0 else ""
    suffix = "…" if window_end < len(search_text) else ""
    return prefix + _highlight_spans(snippet_raw, local_spans) + suffix


def _turn_result_label(entry: "_TurnEntry | None") -> str:
    """Build the Rich-markup label for a TurnResultItem row."""
    if not entry:
        return ""
    max_width = 76
    first = entry.display or "(no content)"
    truncated = first[:max_width] + "…" if len(first) > max_width else first
    return f"[dim]\\[turn {entry.index:>3}][/dim]  {truncated}"


def _build_result_label(result: "_SearchResult | None") -> str:
    """Build multi-line Rich-markup label for TurnResultItem with match context."""
    if result is None:
        return ""
    entry = result.entry
    # Row 1: turn header + first line of user text (escaped)
    user_first = entry.user_text.split("\n", 1)[0]
    if len(user_first) > 72:
        user_first = user_first[:72] + "…"
    header = f"[dim]\\[turn {entry.index:>3}][/dim]  {_escape_markup(user_first)}"
    # Row 2: context snippet with match highlighting
    snippet = _extract_snippet(entry.search_text, result.match_spans)
    return f"{header}\n  {snippet}"


# ---------------------------------------------------------------------------
# TurnResultItem
# ---------------------------------------------------------------------------

class TurnResultItem(Static):
    """Single row in the history search result list — multi-line with match context."""

    DEFAULT_CSS = """
    TurnResultItem { height: auto; min-height: 2; max-height: 4; padding: 0 1; }
    TurnResultItem.--selected { background: $accent 20%; }
    TurnResultItem:hover { background: $accent 10%; }
    """

    def __init__(self, result: "_SearchResult | None", **kwargs: Any) -> None:
        self._result = result
        self._entry = result.entry if result else None
        super().__init__(_build_result_label(result), **kwargs)

    def update_from(self, result: "_SearchResult | None") -> None:
        """Update in-place without DOM add/remove."""
        self._result = result
        self._entry = result.entry if result else None
        self.update(_build_result_label(result))

    def on_click(self, event: Any) -> None:
        """Clicking a result row jumps to the turn; shift+click range-selects."""
        if event.button != 1:
            return
        try:
            overlay = self.app.query_one(HistorySearchOverlay)
        except NoMatches:
            return
        idx = self._entry.index if self._entry is not None else None
        if idx is None:
            return
        if getattr(event, "shift", False) and getattr(overlay, "_last_click_idx", None) is not None:
            # Range select from last click to here
            start = overlay._last_click_idx
            lo, hi = sorted([start, idx])
            shift_sel = set(range(lo, hi + 1))
            overlay._shift_selected = shift_sel
            for item in overlay.query(TurnResultItem):
                item_idx = item._entry.index if item._entry is not None else -1
                item.set_class(item_idx in shift_sel, "--selected")
        else:
            overlay._last_click_idx = idx
            overlay._shift_selected = set()
            for item in overlay.query(TurnResultItem):
                item.set_class(False, "--selected")
            overlay.action_jump_to(self._entry, self._result)


# ---------------------------------------------------------------------------
# KeymapOverlay — structured data + renderer
# ---------------------------------------------------------------------------

# Type aliases for the structured keymap data source.
# Keys are plain strings — renderer wraps them in [dim]\[…][/dim] markup.
_KMRow = tuple[str, ...]            # (description, key1[, key2, ...])
_KMSection = tuple[str, list]       # (section_title, list[_KMRow])


def _km_render_sections(
    sections: list,
    *,
    width: int,
) -> str:
    """Render section list to Rich markup string.

    Pure module-level function — unit-testable without mounting any widget.
    Section titles may contain Rich markup (exception to plain-strings
    convention) — used for the '(press ? for full menu)' dim note in the
    Tool Panel title.
    """
    lines: list[str] = [
        f"[bold]Hermes  Keyboard Reference[/bold]"
        f"{'':>{width - 43}}[dim]\\[F1][/dim] close",
        "─" * min(width - 4, 61),
        "",
    ]
    for title, rows in sections:
        lines.append(f"[bold $text]{title}[/bold $text]")
        for row in rows:
            desc = row[0]
            keys = "  ".join(f"[dim]\\[{k}][/dim]" for k in row[1:]) if len(row) > 1 else ""
            lines.append(f"  {desc:<36}{keys}")
        lines.append("")
    return "\n".join(lines)


# Full-width layout (≥ 80 cols).
# Title may contain Rich markup (exception to plain-strings convention).
_KM_SECTIONS_WIDE: list = [
    ("Input", [
        ("Send message",                "Enter"),
        ("Newline",                     "Shift+Enter"),
        ("Interrupt agent",             "Ctrl+C"),
        ("Clear input",                 "Ctrl+U"),
        ("Paste",                       "Ctrl+V"),
        ("Attach file / image",         "Ctrl+T"),
        ("Undo / Redo",                 "Ctrl+Z", "Ctrl+Y"),
    ]),
    ("Navigation", [
        ("Prev / next turn",            "Alt+↑", "Alt+↓"),
        ("Scroll output",               "↑", "↓", "PgUp", "PgDn"),
        ("Open history search",         "Ctrl+F"),
        ("Next / prev search hit",      "n", "N"),
        ("Cycle pane forward / backward", "F9", "Shift+F9"),
    ]),
    ("Overlays & Modes", [
        ("Browse mode",                 "Ctrl+B"),
        ("Sessions",                    "Ctrl+J"),
        ("Workspace",                   "F4"),
        ("Usage stats",                 "F2"),
        ("Commands list",               "F3"),
        ("Animation config",            "Ctrl+Shift+A"),
    ]),
    ("Pane Layout", [
        ("Focus left / center / right", "F5", "F6", "F7"),
        ("Collapse left / right pane",  "Ctrl+[", "Ctrl+]"),
        ("Toggle center split",         "Ctrl+\\"),
        ("Focus output / input",        "o", "i"),
        ("Prev / next subagent",        "Ctrl+Alt+↑", "Ctrl+Alt+↓"),
    ]),
    # Title contains Rich markup — (press ? for full menu) dim note.
    ("Tool Panel  [dim](press ? for full menu)[/dim]", [
        ("Toggle collapse",             "Enter"),
        ("Scroll body  ·  top / end",   "j", "k", "J", "K", "<", ">"),
        ("Rerun tool",                  "r"),
        ("Copy: plain / +color / HTML", "c", "C", "H"),
        ("Copy: input / invocation",    "Y", "I"),
        ("Copy: stderr / paths / URLs", "e", "p", "u"),
        ("Copy: full path",             "P"),
        ("Density cycle ↓ / ↑",        "D", "Shift+D"),
        ("Render kind / revert",        "t", "T"),
        ("Edit cmd / args",             "E", "a"),
        ("Tail follow",                 "f"),
        ("Dismiss error banner",        "x"),
        ("Context menu  ·  Help",       "?", "F1"),
    ]),
    ("Slash Commands  (type / in composer)", [
        ("/clear",                      ),
        ("/model  /provider",           ),
        ("/skin  /anim",                ),
        ("/compact  /help",             ),
    ]),
]

# Narrow layout (< 80 cols).
_KM_SECTIONS_NARROW: list = [
    ("Input", [
        ("Send",            "Enter"),
        ("Newline",         "Shift+Enter"),
        ("Interrupt",       "Ctrl+C"),
        ("Attach",          "Ctrl+T"),
    ]),
    ("Navigation", [
        ("Prev / next turn",  "Alt+↑", "Alt+↓"),
        ("History search",    "Ctrl+F"),
        ("Cycle pane",        "F9"),
    ]),
    ("Overlays & Modes", [
        ("Browse mode",       "Ctrl+B"),
        ("Sessions",          "Ctrl+J"),
        ("Workspace",         "F4"),
    ]),
    ("Tool Panel", [
        ("Toggle collapse",   "Enter"),
        ("Copy / Rerun",      "c", "r"),
        ("Context menu",      "?"),
        ("Help",              "F1"),
    ]),
]


class KeymapOverlay(ModalOverlayMixin, Widget):
    """Keyboard-shortcut reference card.  Toggle with F1; dismiss with Escape, F1, or q."""

    can_focus = True

    DEFAULT_CSS = """
    KeymapOverlay {
        layer: overlay;
        display: none;
        dock: top;
        height: auto;
        max-height: 24;
        width: 1fr;
        margin: 0 1;
        padding: 1 2;
        background: $surface;
        border: tall $primary 15%;
    }
    KeymapOverlay.--visible { display: block; }
    KeymapOverlay > Static { height: auto; }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=False, priority=True),
        Binding("f1", "dismiss", "Close", show=False, priority=True),
        Binding("q", "dismiss", "Close", show=False, priority=True),
    ]

    def compose(self) -> ComposeResult:
        yield Static("", id="keymap-content", markup=True)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._last_resize_w: int = 0

    def on_mount(self) -> None:
        # Permanent widget: do NOT call ModalOverlayMixin.on_mount().
        # push_modal / --modal are managed per show() / action_dismiss() cycle.
        self._update_content()

    def on_unmount(self) -> None:
        # Permanent widget: do NOT call ModalOverlayMixin.on_unmount().
        pass

    def on_resize(self) -> None:
        try:
            w = self.app.size.width
        except Exception:
            _log.debug("KeymapOverlay.on_resize: app size unavailable", exc_info=True)
            return
        if crosses_threshold(self._last_resize_w, w, 80):
            self._update_content()
        self._last_resize_w = w

    def _update_content(self) -> None:
        """Choose wide/narrow layout based on terminal width (P1-D)."""
        try:
            w = self.app.size.width
        except Exception:
            w = 80
        sections = _KM_SECTIONS_WIDE if w >= 80 else _KM_SECTIONS_NARROW
        content = _km_render_sections(sections, width=w)
        try:
            self.query_one("#keymap-content", Static).update(content)
        except NoMatches:
            pass

    def show(self) -> None:
        """Open the keymap reference; F1 / Esc / q dismiss."""
        if self.has_class("--visible"):
            return
        self._capture_focus_caller()
        try:
            self.app.push_modal(self)  # il-m1: register in arbiter stack
        except AttributeError:  # push_modal absent in tests or pre-patch HermesApp — graceful degrade
            _log.debug("KeymapOverlay.show: app has no push_modal")
        self.add_class("--modal", "--visible")  # il-m1: owned by show (permanent widget override)
        self._update_content()

    def dismiss(self) -> None:
        """Public close helper for widget overlays."""
        self.action_dismiss()

    def action_dismiss(self) -> None:
        self.dismiss_overlay()

    def dismiss_overlay(self) -> None:
        """Permanent-widget dismiss: hide without removing from DOM."""
        target = self._restore_focus_to()
        self.remove_class("--visible", "--modal")  # il-m1: owned by dismiss_overlay (permanent override)
        try:
            self.app.pop_modal(self)  # il-m1: deregister from arbiter stack
        except AttributeError:  # pop_modal absent in tests or pre-patch HermesApp — graceful degrade
            _log.debug("KeymapOverlay.dismiss_overlay: app has no pop_modal")
        if target is not None:
            try:
                if target.is_mounted:
                    target.focus()
            except Exception:
                _log.debug("KeymapOverlay.dismiss_overlay: focus restore failed", exc_info=True)


# ---------------------------------------------------------------------------
# HistorySearchOverlay
# ---------------------------------------------------------------------------

class HistorySearchOverlay(ModalOverlayMixin, Widget):
    """Ctrl+F history search overlay.

    Shows a fuzzy-searchable list of past conversation turns. Ctrl+F opens
    it; Escape/Ctrl+F/Enter dismiss it (Enter also jumps to the selected turn).
    """

    DEFAULT_CSS = """
    HistorySearchOverlay {
        layer: overlay;
        dock: top;
        margin-top: 2;
        margin-left: 4;
        width: 90%;
        max-width: 90;
        min-width: 40;
        height: auto;
        max-height: 50%;
        min-height: 8;
        display: none;
        background: $surface;
        border: tall $primary 15%;
        padding: 0 1;
    }
    HistorySearchOverlay.--visible {
        display: block;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", priority=True),
        Binding("ctrl+f", "dismiss", priority=True),
        Binding("ctrl+g", "dismiss", priority=True),
        Binding("ctrl+c", "dismiss", priority=True),
        Binding("up", "move_up", priority=True),
        Binding("down", "move_down", priority=True),
        Binding("ctrl+p", "move_up", priority=True),
        Binding("ctrl+n", "move_down", priority=True),
        Binding("enter", "jump", priority=True),
    ]

    class TurnCompleted(Message):
        """Posted when the agent finishes a turn — triggers index rebuild."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._index: list[_TurnEntry] = []
        self._current_results: list[_SearchResult] = []
        self._selected_idx: int = 0
        self._saved_hint: str = ""
        self._debounce_handle: Any = None  # Timer | None; cancelled on each new keystroke
        self._cross_session_loading: bool = False  # B4: worker in-flight flag
        self._max_results: int = 50
        self._last_click_idx: int | None = None
        self._shift_selected: set[int] = set()
        self._mode: str = "current"
        self._query_history: list[str] = []
        self._last_render_w: int = 0

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Search history  ↑↓ navigate · Enter jump · Esc close", id="history-search-input")
        yield VerticalScroll(id="history-result-list")
        yield Static("", id="history-status")

    def on_mount(self) -> None:
        # Permanent widget: do NOT call ModalOverlayMixin.on_mount().
        # push_modal / --modal are managed per open_search() / dismiss_overlay() cycle.
        pass

    def on_unmount(self) -> None:
        # Permanent widget: never removed from DOM. ModalOverlayMixin.on_unmount must NOT
        # be called here — stack/focus cleanup is owned by dismiss_overlay(), not lifecycle hooks.
        pass

    def open_search(self) -> None:
        """Build frozen snapshot index, show overlay, focus search input."""
        if self.has_class("--visible"):
            return  # already open — don't double-push the modal stack
        # Read max_results from config if available
        try:
            cfg = self.app.cli._cfg or {}
            max_r = cfg.get("display", {}).get("history_search_max_results", 50)
            self._max_results = int(max_r)
        except Exception:
            pass  # config parse failed; use default max_results limit
        self._build_index()
        self._selected_idx = 0
        # Save and update HintBar hint
        try:
            from .status_bar import HintBar
            hint_bar = self.app.query_one(HintBar)
            self._saved_hint = hint_bar.hint
            hint_bar.hint = "↑↓ navigate  Enter jump  Esc close"
        except NoMatches:
            self._saved_hint = ""
        # A1: clear previous search query so the list always opens unfiltered
        try:
            inp = self.query_one("#history-search-input", Input)
            inp.value = ""
        except NoMatches:
            pass
        self._render_results("")
        self._capture_focus_caller()
        try:
            self.app.push_modal(self)  # il-m1: register in arbiter stack
        except AttributeError:  # push_modal absent in tests or pre-patch HermesApp — graceful degrade
            _log.debug("HistorySearchOverlay.open_search: app has no push_modal")
        self.add_class("--modal", "--visible")  # il-m1: owned by open_search (permanent widget override)
        try:
            self.query_one("#history-search-input", Input).focus()
        except NoMatches:
            pass

    def dismiss(self) -> None:
        """Public close helper — delegates to action_dismiss."""
        self.action_dismiss()

    def action_dismiss(self) -> None:
        """Hide overlay, restore hint, return focus to HermesInput."""
        self.dismiss_overlay()

    def dismiss_overlay(self) -> None:
        """Permanent-widget dismiss: hide without removing from DOM."""
        # Capture focus target FIRST — before any reactive/state mutation that could shift focus
        target = self._restore_focus_to()
        # Save current query to _query_history (non-empty, deduped)
        try:
            query = self.query_one("#history-search-input", Input).value.strip()
            if query:
                if query in self._query_history:
                    self._query_history.remove(query)
                self._query_history.append(query)
        except Exception:
            _log.debug("HistorySearchOverlay.dismiss_overlay: query-history save failed", exc_info=True)
        # Cancel any pending debounce so _render_results() doesn't run
        # against a hidden overlay, removing and re-mounting DOM children.
        if self._debounce_handle is not None:
            self._debounce_handle.stop()
            self._debounce_handle = None
        # A2: clear highlighted_candidate so ghost text is not left stale
        try:
            self.app.highlighted_candidate = None
        except Exception:
            _log.debug("HistorySearchOverlay.dismiss_overlay: highlighted_candidate clear failed", exc_info=True)
        self.remove_class("--visible", "--modal")  # il-m1: owned by dismiss_overlay (permanent override)
        try:
            from .status_bar import HintBar
            self.app.query_one(HintBar).hint = self._saved_hint
        except NoMatches:
            pass
        try:
            self.app.pop_modal(self)  # il-m1: deregister from arbiter stack
        except AttributeError:  # pop_modal absent in tests or pre-patch HermesApp — graceful degrade
            _log.debug("HistorySearchOverlay.dismiss_overlay: app has no pop_modal")
        if target is not None:
            try:
                if target.is_mounted:
                    target.focus()
            except Exception:
                _log.debug("HistorySearchOverlay.dismiss_overlay: focus restore failed", exc_info=True)

    def _build_index(self) -> None:
        """Build a frozen snapshot of current turns. DOM access — event loop only."""
        try:
            from hermes_cli.tui.widgets import OutputPanel, MessagePanel
            output_panel = self.app.query_one(OutputPanel)
            panels = [
                child for child in output_panel.children if isinstance(child, MessagePanel)
            ]
        except NoMatches:
            self._index = []
            return

        # panels[0] is the startup/banner turn (oldest in DOM, not indexed).
        # Real turns are panels[1:]; iterate newest-first.
        # Index is 1-based across all panels: startup = 1, first real = 2, etc.
        real_panels = panels[1:]
        total = len(panels)
        entries: list[_TurnEntry] = []
        for i, panel in enumerate(reversed(real_panels)):
            message_count = total - i
            user_text = panel._user_text or "(no user message)"
            assistant_text = panel.all_prose_text()
            entries.append(
                _TurnEntry(
                    panel=panel,
                    index=message_count,
                    user_text=user_text,
                    assistant_text=assistant_text,
                    search_text=f"{user_text}\n\n{assistant_text}",
                    display=user_text,
                )
            )
        self._index = entries

    def on_input_changed(self, event: Input.Changed) -> None:
        """Debounce keystrokes (150ms) before re-ranking results."""
        if event.input.id != "history-search-input":
            return
        if self._debounce_handle is not None:
            self._debounce_handle.stop()
            self._debounce_handle = None
        query = event.value
        if getattr(self, "_mode", "current") == "all":
            # B4: in all-sessions mode, re-run cross-session search on new query
            def _run_cross() -> None:
                self._cross_session_loading = True
                self._show_cross_session_loading()
                if hasattr(self, "_search_cross_session"):
                    self._search_cross_session(query)
            self._debounce_handle = self.set_timer(0.25, _run_cross)
        else:
            self._debounce_handle = self.set_timer(0.15, lambda: self._render_results(query))

    def _show_cross_session_loading(self) -> None:
        """B4: display a 'Searching…' indicator in the status bar while the worker runs."""
        try:
            self.query_one("#history-status", Static).update("[dim]Searching all sessions…[/dim]")
        except NoMatches:
            pass

    def _render_results(self, query: str) -> None:
        """Search with match highlighting and update the result list.

        Reuses existing TurnResultItem widgets when the result count is
        unchanged (update-in-place via update_from()).  Only adds or removes
        widgets when the count changes, cutting DOM churn on stable queries.
        """
        self._debounce_handle = None
        # Scored search with span tracking; cap at _max_results.
        cap = self._max_results
        if query:
            search_results = _substring_search(query, self._index, limit=cap)
        else:
            # No query: show all entries newest-first, no match spans
            search_results = [
                _SearchResult(entry=e, match_spans=(), first_match_offset=0)
                for e in self._index[:cap]
            ]
        self._current_results = search_results
        try:
            result_list = self.query_one("#history-result-list", VerticalScroll)
        except NoMatches:
            return

        existing = list(result_list.query(TurnResultItem))
        new_count = len(search_results)
        old_count = len(existing)

        if new_count == old_count:
            for widget, result in zip(existing, search_results):
                widget.update_from(result)
        elif new_count < old_count:
            for widget, result in zip(existing[:new_count], search_results):
                widget.update_from(result)
            for widget in existing[new_count:]:
                widget.remove()
        else:
            for widget, result in zip(existing, search_results[:old_count]):
                widget.update_from(result)
            new_items = [TurnResultItem(r) for r in search_results[old_count:]]
            result_list.mount_all(new_items)

        self._selected_idx = max(0, min(self._selected_idx, new_count - 1))
        self.call_after_refresh(self._update_selection)

        # Status line
        total = len(self._index)
        try:
            if search_results or total == 0:
                shown = len(search_results)
                sel = min(self._selected_idx + 1, shown) if shown else 0
                status_text = (
                    f"[dim]{sel}/{shown} shown · "
                    f"{total} turn{'s' if total != 1 else ''} indexed[/dim]"
                )
            else:
                status_text = (
                    "[dim]no matches — try fewer words or a partial phrase[/dim]"
                )
            self.query_one("#history-status", Static).update(status_text)
        except NoMatches:
            pass

    def _update_selection(self) -> None:
        """Apply --selected CSS class to the currently highlighted row."""
        try:
            items = list(self.query(TurnResultItem))
        except Exception:
            # widget absent during dismiss; return early is correct
            return
        for i, item in enumerate(items):
            item.set_class(i == self._selected_idx, "--selected")

    def action_move_up(self) -> None:
        self._selected_idx = max(0, self._selected_idx - 1)
        self._update_selection()

    def action_move_down(self) -> None:
        count = len(list(self.query(TurnResultItem)))
        self._selected_idx = min(max(count - 1, 0), self._selected_idx + 1)
        self._update_selection()

    def action_prev_query(self) -> None:
        """Ctrl+Up: restore most recent previous search query."""
        if not self._query_history:
            return
        query = self._query_history[-1]
        try:
            inp = self.query_one("#history-search-input", Input)
            inp.value = query
        except Exception:
            # search query widget absent; filter not applied
            pass

    def action_find_next(self) -> None:
        """Ctrl+G inside overlay: advance selection to next result, wrapping."""
        count = len(list(self.query(TurnResultItem)))
        if count == 0:
            return
        self._selected_idx = (self._selected_idx + 1) % count
        self._update_selection()

    def action_toggle_mode(self) -> None:
        """Tab: toggle between 'current' and 'all' session search modes."""
        self._mode = "all" if self._mode == "current" else "current"
        try:
            mode_bar = self.query_one(_ModeBar)
            mode_bar.set_mode(self._mode)
        except Exception:
            pass  # mode bar widget absent; visual indicator not updated
        try:
            query = self.query_one("#history-search-input", Input).value
        except Exception:
            # search input absent; query defaults to empty string
            query = ""
        if self._mode == "all" and hasattr(self, "_search_cross_session"):
            self._cross_session_loading = True
            self._show_cross_session_loading()
            self._search_cross_session(query)
        else:
            self._render_results(query)

    def _handle_cross_session_jump(self, result: "_CrossSessionResult") -> None:
        """Handle a jump to a cross-session result (may be other session)."""
        if result.is_current_session:
            return
        try:
            from .status_bar import HintBar
            hint_bar = self.app.query_one(HintBar)
            title = result.session_title or result.session_id
            hint_bar.hint = f"Switch to session: {title}"
        except Exception:
            # widget absent during reset; skip gracefully
            pass

    def action_jump(self) -> None:
        """Jump to the selected turn and dismiss the overlay."""
        items = list(self.query(TurnResultItem))
        if not items:
            self.action_dismiss()
            return
        shift_sel = getattr(self, "_shift_selected", set())
        if shift_sel:
            target_idx = min(shift_sel)
            if 0 <= target_idx < len(items):
                item = items[target_idx]
                entry, result = item._entry, item._result
                self.action_dismiss()
                if entry is not None:
                    self._scroll_to_match(entry, result)
                return
        idx = max(0, min(self._selected_idx, len(items) - 1))
        result = items[idx]._result
        entry = items[idx]._entry
        self.action_dismiss()
        if entry is None:
            return
        self._scroll_to_match(entry, result)

    def action_jump_to(
        self,
        entry: "_TurnEntry | None",
        result: "_SearchResult | None" = None,
    ) -> None:
        """Jump directly to a specific entry (used by TurnResultItem click)."""
        self.action_dismiss()
        if entry is None:
            return
        self._scroll_to_match(entry, result)

    def _scroll_to_match(
        self,
        entry: _TurnEntry,
        result: "_SearchResult | None",
    ) -> None:
        """Scroll to panel, flash highlight, deep-scroll into matched region."""
        panel = entry.panel
        panel.scroll_visible(animate=True)
        panel.add_class("--highlighted")
        panel.set_timer(0.5, lambda: panel.remove_class("--highlighted"))
        # Deep scroll: if match is deep in assistant text, scroll into it
        if result and result.first_match_offset > 0:
            try:
                log = panel.query_one(CopyableRichLog)
                lines_before = entry.search_text[:result.first_match_offset].count("\n")
                if lines_before > 5:
                    log.scroll_to(0, lines_before - 2, animate=True)
            except NoMatches:
                pass

    def on_resize(self) -> None:
        if not self.has_class("--visible"):
            return
        try:
            new_w = self.app.size.width
        except Exception:
            _log.debug("HistorySearchOverlay.on_resize: app size unavailable", exc_info=True)
            return
        if new_w == self._last_render_w:
            return
        self._last_render_w = new_w
        try:
            query = self.query_one("#history-search-input", Input).value
        except NoMatches:
            query = ""
        self._render_results(query)


# ---------------------------------------------------------------------------
# _CrossSessionResult — cross-session FTS5 search result
# ---------------------------------------------------------------------------

@dataclass
class _CrossSessionResult:
    """Result from cross-session FTS5 search."""
    session_id: str
    session_title: str       # empty string if NULL
    role: str
    content_preview: str     # first 80 chars, newlines collapsed
    timestamp: float
    is_current_session: bool # True when session_id == current session_id


def _build_cross_session_label(result: "_CrossSessionResult") -> str:
    """Build row label for a cross-session search result."""
    title = result.session_title or result.session_id[-8:]
    preview = result.content_preview
    return f"[dim]\\[{_escape_markup(title)}][/dim]  {_escape_markup(preview)}"


# ---------------------------------------------------------------------------
# _ModeBar — current/all session toggle display
# ---------------------------------------------------------------------------

class _ModeBar(Static):
    """Renders [Current] All or Current [All] based on overlay mode."""

    DEFAULT_CSS = """
    _ModeBar { height: 1; padding: 0 1; }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self._mode = "current"

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        if mode == "current":
            self.update("[bold]\\[Current][/bold] All")
        else:
            self.update("Current [bold]\\[All][/bold]")
