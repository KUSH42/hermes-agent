# TUI History Search — Feature Specification

**Status:** APPROVED  
**Impact:** High  
**Key:** SPEC-B  

---

## 1. Problem Statement

Conversation turns accumulate in `OutputPanel` as stacked `MessagePanel` widgets. Scrolling back through hundreds of turns is slow and disorienting. There is no way to find a specific turn by keyword without manual scrolling. A history-search overlay gives the user instant, keyboard-driven access to any prior turn.

---

## 2. Scope

| In scope | Out of scope |
|---|---|
| Ctrl+F launches an overlay that filters past `MessagePanel` turns | Indexing tool-block content |
| Fuzzy search against the plain-text content of each turn's response log | Full-text search across filesystem |
| Keyboard navigation through results (Up/Down/Enter) | Pagination or external search engines |
| Jump-to-turn (scroll `OutputPanel` to the selected `MessagePanel`) | Editing or deleting turns from the overlay |
| Escape dismisses overlay, returns focus to input | Persistent saved searches |
| Empty query shows all turns (browse-all mode) | Match-span highlighting in result rows |

---

## 3. Trigger and Dismissal

| Event | Condition | Action |
|---|---|---|
| `ctrl+f` keypress | Any time (`agent_running` may be True) | Open `HistorySearchOverlay`, focus search input |
| `ctrl+f` (again) | Overlay already visible | Dismiss overlay, return focus to `HermesInput` |
| `Escape` | Overlay visible | Dismiss overlay, return focus to `HermesInput` |
| `Enter` on a result | — | Jump to turn, dismiss overlay |
| `ctrl+c` | Overlay visible | Dismiss overlay (does NOT copy) |

**Note:** `ctrl+f` is intercepted at `HermesApp.on_key()` *before* Textual's default focus handling so it works regardless of which widget currently holds focus.

---

## 4. UI Layout

```
┌─ History Search ────────────────────────────────────────┐
│  🔍  _______________________________________________     │
│                                                          │
│  ▶  [turn 12] write a function to parse ISO dates        │
│     [turn 11] explain the memory architecture            │
│     [turn  9] what does rollback do                      │
│     [turn  7] how is caching implemented in the agent    │
│     …                                                    │
└──────────────────────────────────────────────────────────┘
         dim status: "4 of 47 turns"
```

- Overlay is **not modal** — `OutputPanel` remains visible behind it
- Overlay is anchored: `dock: top`, offset to appear just below the `TitledRule` separator
- Width: 90% of terminal width, max 90 columns, minimum 40 columns
- Height: `auto`, capped at 18 rows (including search input + status line)
- Overlay sits on the `overlay` layer (same as `ContextMenu`)
- Background: `$panel` for visual separation from `OutputPanel`

---

## 5. Widget Structure

```
HistorySearchOverlay (Widget, layer: overlay)
  ├── SearchInput (Input, id="history-search-input", placeholder="🔍  Search turns…")
  ├── ResultList (ScrollView, id="history-result-list")
  │     └── [TurnResultItem × N]  (Static per match)
  └── StatusLine (Static, id="history-status", dim text "N of M turns")
```

### 5.1 TurnResultItem

A `Static` subclass with a `_entry: _TurnEntry` attribute. Renders as one line:

```
  [turn {N}]  {first_line_of_plain_text}…
```

- `N` = 1-based turn number (ascending; most recent = highest)
- First line truncated at `max(20, terminal_width - 14)` characters
- Selected item: CSS class `--selected` → highlighted background
- All items: `height: 1`
- Clicking a `TurnResultItem` triggers the same jump as `Enter`

### 5.2 Indexing

On `open_search()` the overlay queries `app.query_one(OutputPanel).query(MessagePanel)` and builds a **snapshot list** (copy, not live reference):

```python
@dataclass
class _TurnEntry:
    panel: MessagePanel
    index: int          # 1-based, ascending order (turn 1 = first ever)
    plain_text: str     # joined _plain_lines from panel.response_log
    display: str        # first non-empty line for display (NOT the Candidate.display)
```

The index is built once in `open_search()` and never updated while the overlay is open. New turns added after `open_search()` are not reflected — the overlay operates on a frozen snapshot. The snapshot is a plain Python list assigned to `self._index: list[_TurnEntry]`, completely independent of the DOM.

---

## 6. Search Algorithm

### 6.0 Supporting dataclasses

`_TurnEntry` holds all metadata for one indexed turn:

```python
from dataclasses import dataclass
from hermes_cli.tui.widgets import MessagePanel   # import at top of file

@dataclass
class _TurnEntry:
    panel: MessagePanel
    index: int          # 1-based (turn 1 = first ever)
    plain_text: str     # full joined _plain_lines from panel.response_log
    display: str        # first non-empty line for the result row
```

`TurnCandidate` wraps a `_TurnEntry` as a `Candidate` so `fuzzy_rank()` can process it. `Candidate` uses `@dataclass(frozen=True, slots=True)` — `TurnCandidate` must match:

```python
from hermes_cli.tui.path_search import Candidate
from dataclasses import dataclass, field

@dataclass(frozen=True, slots=True)
class TurnCandidate(Candidate):
    """Candidate subclass carrying a _TurnEntry reference for fuzzy_rank().
    
    Candidate base fields (inherited): display: str, score: int = 0,
    match_spans: tuple[tuple[int, int], ...] = ()
    
    The `entry` field has a default so it comes after the inherited default
    fields — Python's dataclass field-ordering rule is satisfied.
    """
    entry: "_TurnEntry | None" = field(default=None)
```

**Note on `frozen=True, slots=True` and inheritance:** Python 3.10+ correctly generates `__slots__` only for the new fields when subclassing a slotted frozen dataclass. `TurnCandidate.__slots__` will contain only `("entry",)`. `dataclasses.replace(c, score=..., match_spans=...)` creates a new `TurnCandidate` instance with `entry` preserved — the `fuzzy_rank` scorer works correctly with this.

Build candidates from the index:

```python
_candidates = [
    TurnCandidate(display=e.plain_text, entry=e)
    for e in self._index
]
```

Apply fuzzy rank:

```python
from hermes_cli.tui.fuzzy import fuzzy_rank

results = fuzzy_rank(query, _candidates, limit=200)
```

- Empty query → all turns in **reverse chronological order** (most recent first, i.e. highest index first). `fuzzy_rank` returns in input order when `query == ""`; build `_candidates` in reverse-index order for the empty case.
- Non-empty query → `fuzzy_rank` ranks by score descending.
- Update fires on every keystroke in `SearchInput` via `on_input_changed()`. No debounce needed — `fuzzy_rank` with 500 candidates completes in < 1 ms.

---

## 7. Keyboard Navigation

`HistorySearchOverlay.on_key()` intercepts keys with explicit handling. The `SearchInput` is an `Input` widget — Textual's `Input` captures `Up`/`Down` natively to move cursor. To intercept these before `Input` processes them, `HistorySearchOverlay` must override focus and key routing:

**Solution:** `SearchInput` is **NOT** focused directly. Instead, `HistorySearchOverlay` itself holds focus and manually forwards printable characters to `SearchInput.value`. This gives the overlay full control over `Up`/`Down`/`Enter`/`Escape` without fighting `Input`'s native key bindings.

Alternative approach: keep `SearchInput` focused and intercept `Up`/`Down` by binding them in `HistorySearchOverlay.BINDINGS` at `priority=True`. Textual `BINDINGS` with `priority=True` fire before widget-level handlers. However, the simplest and most robust pattern is the manual-forward approach below.

```python
class HistorySearchOverlay(Widget):
    BINDINGS = [
        Binding("escape", "dismiss", priority=True),
        Binding("ctrl+f", "dismiss", priority=True),
        Binding("ctrl+c", "dismiss", priority=True),
        Binding("up", "move_up", priority=True),
        Binding("down", "move_down", priority=True),
        Binding("ctrl+p", "move_up", priority=True),
        Binding("ctrl+n", "move_down", priority=True),
        Binding("enter", "jump", priority=True),
    ]
```

Bindings with `priority=True` in Textual fire before child widget handlers, including `Input`'s built-in `Up`/`Down` bindings.

| Key | Action |
|---|---|
| `Up` / `ctrl+p` | Move selection one row up (clamp at 0, no wrap) |
| `Down` / `ctrl+n` | Move selection one row down (clamp at last, no wrap) |
| `Enter` | Jump to selected turn, dismiss overlay |
| `Escape` / `ctrl+f` / `ctrl+c` | Dismiss overlay, no jump |

---

## 8. Jump-to-Turn

On `Enter` (or click on a result):

1. Retrieve the `MessagePanel` from the selected `TurnCandidate.entry.panel`
2. Dismiss overlay: `self.remove_class("--visible")`; return focus to `HermesInput`
3. Scroll to panel: `panel.scroll_visible(animate=True)` — this is the correct Textual API (called on the widget itself, not the container)
4. Add `--highlighted` CSS class to the panel immediately after scrolling

### Panel highlight animation

Show ordering (Textual CSS transition requirement: widget must be visible before animating):

```python
# Panel is already visible (not hidden). Safe to add class and trigger transition.
panel.add_class("--highlighted")
panel.set_timer(1.5, lambda: panel.remove_class("--highlighted"))
```

```css
/* hermes.tcss */
MessagePanel.--highlighted {
    background: $accent 15%;
    transition: background 1.5s in_out_cubic;
}
```

The CSS `transition` on `background` fades from `$accent 15%` back to the default background as the class is removed after 1.5 s.

---

## 9. HermesApp Integration

### 9.1 Compose

Add `HistorySearchOverlay` to `HermesApp.compose()`:

```python
yield HistorySearchOverlay(id="history-search")
```

Position: after `CompletionOverlay`, before `with Horizontal(id="input-row")`.

### 9.2 Key Interception

In `HermesApp.on_key()`, add **before** the existing priority 0 (completion overlay escape check):

```python
# ctrl+f → toggle history search overlay
if event.key == "ctrl+f":
    hs = self.query_one(HistorySearchOverlay)
    if hs.has_class("--visible"):
        hs.action_dismiss()
    else:
        hs.open_search()
    event.prevent_default()
    return
```

### 9.3 HintBar hint coordination

`HistorySearchOverlay` saves and restores the `HintBar` hint:

```python
def open_search(self) -> None:
    try:
        hint_bar = self.app.query_one(HintBar)
        self._saved_hint = hint_bar.hint   # save current hint
        hint_bar.hint = "↑↓ navigate  Enter jump  Esc close"
    except NoMatches:
        self._saved_hint = ""
    ...

def action_dismiss(self) -> None:
    self.remove_class("--visible")
    try:
        self.app.query_one(HintBar).hint = self._saved_hint
        from hermes_cli.tui.input_widget import HermesInput
        self.app.query_one(HermesInput).focus()
    except NoMatches:
        pass
```

`_saved_hint: str = ""` is initialised as a plain instance attribute in `__init__`. This gives correct save/restore even when multiple overlays might fight over the hint — each overlay saves the hint that was current at the time it opened, so the net effect is LIFO restoration.

---

## 10. HistorySearchOverlay API

**Required imports** (at top of the module that defines `HistorySearchOverlay`):

```python
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import ScrollView
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Input, Static
```

```python
class HistorySearchOverlay(Widget):
    DEFAULT_CSS = """
    HistorySearchOverlay {
        layer: overlay;
        dock: top;
        margin-top: 2;
        margin-left: 5%;
        width: 90%;
        max-width: 90;
        min-width: 40;
        height: auto;
        max-height: 18;
        display: none;
        background: $panel;
        border: tall $primary 50%;
        padding: 0 1;
    }
    HistorySearchOverlay.--visible {
        display: block;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._index: list[_TurnEntry] = []
        self._candidates: list[TurnCandidate] = []
        self._selected_idx: int = 0
        self._saved_hint: str = ""

    def open_search(self) -> None:
        """Build frozen snapshot index, show overlay, focus search input."""
        self._build_index()
        self._selected_idx = 0
        self._render_results("")
        self.add_class("--visible")
        try:
            self.query_one("#history-search-input", Input).focus()
        except NoMatches:
            pass

    def action_dismiss(self) -> None:
        """Hide overlay, restore hint, return focus to HermesInput."""
        self.remove_class("--visible")
        try:
            from hermes_cli.tui.widgets import HintBar
            self.app.query_one(HintBar).hint = self._saved_hint
        except NoMatches:
            pass
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.app.query_one(HermesInput).focus()
        except NoMatches:
            pass

    def _build_index(self) -> None:
        """Build a frozen snapshot of current turns. DOM access — call from event loop only."""
        from hermes_cli.tui.widgets import OutputPanel
        try:
            output_panel = self.app.query_one(OutputPanel)
            panels = list(output_panel.query(MessagePanel))  # snapshot copy
        except NoMatches:
            panels = []
        self._index = [
            _TurnEntry(
                panel=p,
                index=i + 1,
                plain_text="\n".join(p.response_log._plain_lines),
                display=next((l for l in p.response_log._plain_lines if l.strip()), ""),
            )
            for i, p in enumerate(panels)
        ]
        # Build candidates in reverse order so empty-query shows most recent first
        self._candidates = [
            TurnCandidate(display=e.plain_text, entry=e)
            for e in reversed(self._index)
        ]

    def compose(self) -> ComposeResult:
        yield Input(placeholder="🔍  Search turns…", id="history-search-input")
        yield ScrollView(id="history-result-list")
        yield Static("", id="history-status")

    def on_input_changed(self, event: Input.Changed) -> None:
        """Re-rank and display results on every keystroke."""
        if event.input.id == "history-search-input":
            self._render_results(event.value)

    def _render_results(self, query: str) -> None:
        """Apply fuzzy_rank and populate ResultList with TurnResultItem widgets."""
        from hermes_cli.tui.fuzzy import fuzzy_rank
        results = fuzzy_rank(query, self._candidates, limit=200)
        try:
            result_list = self.query_one("#history-result-list", ScrollView)
        except NoMatches:
            return
        # Replace all children with new TurnResultItem widgets
        items = [TurnResultItem(r.entry) for r in results]
        result_list.remove_children()
        result_list.mount(*items) if items else None
        # Update selection clamping
        self._selected_idx = max(0, min(self._selected_idx, len(items) - 1))
        self._update_selection()
        # Status line
        total = len(self._index)
        try:
            self.query_one("#history-status", Static).update(
                f"[dim]{len(results)} of {total} turn{'s' if total != 1 else ''}[/dim]"
            )
        except NoMatches:
            pass

    def _update_selection(self) -> None:
        """Apply --selected CSS class to the currently highlighted row."""
        try:
            items = list(self.query(TurnResultItem))
        except Exception:
            return
        for i, item in enumerate(items):
            item.set_class(i == self._selected_idx, "--selected")

    def action_move_up(self) -> None:
        count = len(list(self.query(TurnResultItem)))
        self._selected_idx = max(0, self._selected_idx - 1)
        self._update_selection()

    def action_move_down(self) -> None:
        count = len(list(self.query(TurnResultItem)))
        self._selected_idx = min(count - 1, self._selected_idx + 1)
        self._update_selection()

    def action_jump(self) -> None:
        """Jump to the selected turn and dismiss the overlay."""
        items = list(self.query(TurnResultItem))
        if not items:
            self.action_dismiss()
            return
        idx = max(0, min(self._selected_idx, len(items) - 1))
        entry = items[idx]._entry
        self.action_dismiss()
        panel = entry.panel
        panel.scroll_visible(animate=True)
        panel.add_class("--highlighted")
        panel.set_timer(1.5, lambda: panel.remove_class("--highlighted"))

    def on_resize(self) -> None:
        """Re-render results to update first-line truncation after terminal resize."""
        if self.has_class("--visible"):
            try:
                query = self.query_one("#history-search-input", Input).value
            except NoMatches:
                query = ""
            self._render_results(query)
```

### TurnResultItem

```python
from textual.widgets import Static

class TurnResultItem(Static):
    """Single row in the history search result list."""

    DEFAULT_CSS = """
    TurnResultItem { height: 1; padding: 0 1; }
    TurnResultItem.--selected { background: $accent 20%; }
    TurnResultItem:hover { background: $accent 10%; }
    """

    def __init__(self, entry: "_TurnEntry | None", **kwargs) -> None:
        self._entry = entry
        max_width = 76  # fallback; updated in _render_results
        label = ""
        if entry:
            first = entry.display or "(no content)"
            truncated = first[:max_width] + "…" if len(first) > max_width else first
            label = f"[dim]\\[turn {entry.index:>3}][/dim]  {truncated}"
        super().__init__(label, **kwargs)

    def on_click(self, event) -> None:
        """Clicking a result row jumps to the turn."""
        if event.button == 1:
            try:
                self.app.query_one(HistorySearchOverlay).action_jump_to(self._entry)
            except NoMatches:
                pass
```

Add `action_jump_to(entry)` to `HistorySearchOverlay`:

```python
def action_jump_to(self, entry: "_TurnEntry | None") -> None:
    """Jump directly to a specific entry (used by TurnResultItem click)."""
    self.action_dismiss()
    if entry is None:
        return
    panel = entry.panel
    panel.scroll_visible(animate=True)
    panel.add_class("--highlighted")
    panel.set_timer(1.5, lambda: panel.remove_class("--highlighted"))
```

---

## 11. CSS

**`hermes.tcss` additions:**

```css
/* History search overlay */
#history-search-input {
    border: none;
    background: $surface;
    padding: 0 1;
    margin-bottom: 1;
}

#history-result-list {
    height: auto;
    max-height: 14;
    overflow-y: auto;
    overflow-x: hidden;
}

#history-status {
    color: $text-muted;
    text-align: right;
    padding: 0 1;
}

TurnResultItem {
    height: 1;
    padding: 0 1;
}

TurnResultItem.--selected {
    background: $accent 20%;
}

TurnResultItem:hover {
    background: $accent 10%;
}

MessagePanel.--highlighted {
    background: $accent 15%;
    transition: background 1.5s in_out_cubic;
}
```

---

## 12. Tests

File: `tests/tui/test_history_search.py`

| # | Test | Assertion |
|---|---|---|
| 1 | `ctrl+f` opens overlay | `HistorySearchOverlay` has class `--visible`; `Input` has focus |
| 2 | Second `ctrl+f` closes overlay | `--visible` removed |
| 3 | `Escape` closes overlay | `--visible` removed; `HermesInput` has focus |
| 4 | Empty query shows all turns in reverse order | All `_TurnEntry` items rendered, last added = first shown |
| 5 | Non-empty query filters turns via fuzzy match | Only matching entries shown |
| 6 | `Down` moves selection | `--selected` class on correct row |
| 7 | `Up` moves selection | `--selected` class on correct row |
| 8 | `Up` at row 0 clamps (no wrap) | `--selected` stays on row 0 |
| 9 | `Down` at last row clamps (no wrap) | `--selected` stays on last row |
| 10 | `Enter` calls `panel.scroll_visible()` on correct MessagePanel | Mocked `scroll_visible` called with correct panel |
| 11 | `Enter` dismisses overlay | `--visible` removed after jump |
| 12 | `Enter` adds `--highlighted` to target panel | Class present immediately after jump |
| 13 | `--highlighted` removed after 1.5 s | Class absent after `asyncio.sleep(1.6)` + `pilot.pause()` |
| 14 | 0-turn conversation → empty result list, "0 of 0 turns" | StatusLine text correct |
| 15 | 1-turn conversation → single entry with correct first_line | `display` text matches first non-empty line |
| 16 | Click on `TurnResultItem` triggers jump | Same as Enter: `scroll_visible` called, overlay dismissed |
| 17 | HintBar shows navigation hint when overlay is open | `HintBar.hint` contains "navigate" |
| 18 | HintBar hint restored after overlay closes | `HintBar.hint` reverts to saved value |
| 19 | Overlay opens even when `agent_running=True` | No guard blocks open |
| 20 | Index snapshot is frozen: new MessagePanel mounted after open is NOT in results | `_index` length unchanged after adding a panel |
| 21 | `on_resize()` called → result items re-render | `_render_results` invoked; no crash |
| 22 | `ctrl+c` dismisses overlay | `--visible` removed |

---

## 13. Accessibility and Edge Cases

- **No turns yet:** Show "No turns yet" in result body, status "0 of 0 turns"
- **Long first line:** Truncate at `max(20, terminal_width - 14)` characters
- **Multi-line turns:** Only the first non-empty line shown in result list; full `plain_text` used for search
- **Agent running:** Overlay can open while agent streams. Index is a frozen snapshot from open time.
- **Resize:** `on_resize()` re-renders result rows with updated truncation width
- **Small terminal (< 40 cols):** Overlay uses `min-width: 40`; display may overflow. Accepted trade-off.

---

## 14. Non-Goals

- Match-span highlighting in result rows
- Searching tool-block content
- Multi-term boolean search
- Persistent saved searches
