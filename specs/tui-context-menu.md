# Spec: TUI Context Menu + Copy/Paste Feedback

**Status:** Implemented (2026-04-11)  
**Priority:** P1  
**Depends on:** textual-migration (implemented), autocomplete-engine (implemented)  
**Goal:** Add a right-click context menu and visible copy/paste feedback to the Hermes TUI, closing the last major interaction gap vs Ink-based competitors.

---

## 1. Problem

Three interaction gaps make the TUI feel unfinished compared to modern terminal apps:

**No right-click affordance.** Right-clicking anywhere does nothing. There is no way to access copy/expand/collapse actions without knowing keyboard shortcuts. Ink-based competitors cannot support right-click at all (no `MouseRightClick` event in React/Ink); Textual can, and we should exploit it.

**Silent copy.** `ctrl+c` on selected text calls `App.copy_to_clipboard()` at app.py:714 but returns with zero feedback. The user has no confirmation the copy happened. Browse-mode copy (key `c`) correctly flashes `⎘→✓` on the `ToolHeader`, but this idiom is not applied to any other copy path.

**Silent paste.** Pasting into `HermesInput` — which inherits Textual's `Input` and fires an `on_paste` event — triggers no feedback whatsoever. The user sees text appear but has no signal about how much was pasted or that the app registered it.

---

## 2. Goals

1. Right-clicking on a `ToolBlock` or `ToolHeader` shows a context menu with: Copy tool output, Expand/Collapse, ─separator─, Copy all output.
2. Right-clicking on a `MessagePanel`/`CopyableRichLog` shows: Copy selected (if selection active), Copy full response.
3. Right-clicking on `HermesInput` or the input row shows: Paste, Clear input.
4. Right-clicking anywhere else (with active selection) shows: Copy selected.
5. Context menu dismisses on: item click, `Escape`, blur, or click outside the menu.
6. Menu is clamped to viewport — never clips off screen edge.
7. `ctrl+c` copy (selected text path) flashes `⎘ N chars` in `HintBar` for 1.5 s.
8. Paste into `HermesInput` flashes `📋 N chars` in `HintBar` for 1.2 s.
9. All existing copy paths (browse-mode `c`, `ctrl+c` cancel-overlay) are unaffected.

---

## 3. Non-Goals

- Mouse hover effects on ToolHeaders (requires hit-testing on scroll; deferred — see Deferred section).
- Keyboard navigation within the context menu (Up/Down to move selection). The menu is small and optimised for mouse — keyboard users have existing bindings.
- Multi-item selection copy across turns. Selection is per-widget; cross-widget selection is not supported by Textual.
- Right-click on overlays (clarify/approval/sudo/secret). These widgets are modal; standard key bindings apply.
- Clipboard read (paste via menu item). OSC 52 clipboard read is unsupported in most terminals; system paste via `ctrl+v`/`shift+ins` already works through `Input`.

---

## 4. Design

### 4.1 `ContextMenu` widget

New file: `hermes_cli/tui/context_menu.py`

```
ContextMenu(Widget)
  can_focus = True           # required: on_blur only fires on focusable widgets
  DEFAULT_CSS: display:none  # hidden until .--visible class added
                             # layer:overlay and position:absolute set in CSS (see §4.6)
  
  show(items, screen_x, screen_y)  # positions + reveals; calls self.focus() at end
  dismiss()                         # removes .--visible
  
  Children (remounted on each show() via recompose()):
    _ContextSep(Static)    # separator row
    _ContextItem(Static)   # one per MenuItem
```

**`MenuItem` dataclass:**
```python
@dataclass
class MenuItem:
    label: str                    # Rich markup OK
    shortcut: str                 # dim right-aligned hint
    action: Callable[[], None]
    separator_above: bool = False
```

**Positioning:** `self.styles.offset = (clamped_x, clamped_y)`. Requires `position: absolute` in CSS (see §4.6) so the menu floats at arbitrary screen coordinates rather than shifting from its layout position. `show(items, sx, sy)` receives resolved `int` coords — the `None`-fallback from `event.screen_x → event.x` (widget-relative) is handled in `on_click` before the call. Width estimated as `max(len(label) + len(shortcut) + 4 for item in items)`. Clamp inside `show()`: `x = min(sx, self.app.size.width - estimated_width - 2)`, `y = min(sy, self.app.size.height - len(items) - 3)`.

**Focus management:** `show()` must call `self.focus()` after setting `.--visible`. This is what enables `on_blur` to fire when the user clicks elsewhere, dismissing the menu.

**Dismiss mechanisms:**
- `on_blur`: fires when menu loses focus → `dismiss()`
- `on_key(escape)`: `dismiss()` + `event.prevent_default()`
- `_ContextItem.on_click`: calls `item.action()` then `self.app.query_one(ContextMenu).dismiss()`
- `HermesApp.on_click(button==3)`: if menu already visible, dismiss first, then re-show at new position

### 4.2 Layer declaration

`HermesApp` must declare layers or Textual raises at startup:

```python
class HermesApp(App):
    LAYERS = ("default", "overlay")
```

Draw order: `default` → `overlay`. `ContextMenu` uses CSS `layer: overlay;` (see §4.6), which places it above all default-layer widgets.

### 4.3 `HermesApp.on_click` — context dispatch

```python
def on_click(self, event: Click) -> None:
    if event.button != 3:
        return
    items = self._build_context_items(event)
    if not items:
        return
    event.prevent_default()
    # Resolve screen coords here — show() receives ints, not int|None
    sx = event.screen_x if event.screen_x is not None else event.x
    sy = event.screen_y if event.screen_y is not None else event.y
    try:
        self.query_one(ContextMenu).show(items, sx, sy)
    except NoMatches:
        pass
```

**`_build_context_items` DOM walk:**
```
If event.widget is None → return [] (no menu)
Walk up event.widget's parent chain:
  ToolBlock  → [Copy tool output | Expand/Collapse | ─ | Copy all output]
  ToolHeader → same as ToolBlock (header is part of block)
  MessagePanel / CopyableRichLog → [Copy selected? | Copy full response]
  HermesInput / #input-row → [Paste | Clear input]
Fallback (nothing matched) → [Copy selected] only if selection active
```

### 4.4 Copy/paste feedback — `_flash_hint`

New method on `HermesApp`:

```python
def _flash_hint(self, text: str, duration: float = 1.5) -> None:
    try:
        bar = self.query_one(HintBar)
        prior = bar.hint
        bar.hint = text
        self.set_timer(duration, lambda: setattr(bar, "hint", prior))
    except NoMatches:
        pass
```

This reuses the existing `HintBar.hint` reactive — no new widgets, no new CSS.

**Copy flash** (app.py `on_key`, ctrl+c selected-text branch):
```python
self.copy_to_clipboard(selected)
self._flash_hint(f"⎘  {len(selected)} chars copied", 1.5)
```

**Paste flash** (input_widget.py):
```python
def on_paste(self, event) -> None:
    n = len(event.text)
    self.app._flash_hint(f"📋  {n} chars", 1.2)
    # No prevent_default — Input handles the actual paste
```

### 4.5 `ContextMenu` in `compose()`

```python
yield ContextMenu(id="context-menu")   # after StatusBar, inside HermesApp.compose()
```

### 4.6 CSS

In `DEFAULT_CSS` on `ContextMenu`:
```css
ContextMenu {
    layer: overlay;
    position: absolute;   /* required: floats at arbitrary screen coordinates */
    display: none;
    width: auto;
    height: auto;
    background: $surface;
    border: tall $primary;
    padding: 0 1;
}
ContextMenu.--visible { display: block; }
```

In `hermes.tcss` (visual only — uses Textual type selectors, no CSS class assignment needed):
```css
ContextMenu > _ContextItem:hover { background: $primary 30%; }
ContextMenu > _ContextSep { color: $text-muted; }
```

---

## 5. Design Decisions

| Decision | Chosen | Alternative | Reason |
|---|---|---|---|
| `on_blur` dismiss | Yes | Click-outside detection via App.on_click | `on_blur` is idiomatic Textual; click-outside needs filtering to avoid dismissing on right-click re-open |
| Layer system | `LAYERS = ("default", "overlay")` | `z-index` CSS | Textual doesn't support CSS z-index; layers are the correct mechanism |
| Width estimation | String length heuristic | Fixed width | Fixed width wastes space for short menus; heuristic is sufficient |
| Hint bar for feedback | Yes | Toast widget | HintBar already exists and is at the user's focal point (just above input); zero new widgets |
| Paste event hook | `on_paste` on `HermesInput` | App-level clipboard hook | `on_paste` fires on Textual Input subclasses; app-level is not needed |
| `run_in_executor` for action callbacks | No | Yes | Menu actions are short UI mutations (copy, toggle); no executor needed |

---

## 6. Configuration

No new config keys. The context menu is always available when mouse is enabled in the terminal.

---

## 7. Files Changed

**New:**
- `hermes_cli/tui/context_menu.py` — `ContextMenu`, `_ContextItem`, `_ContextSep`, `MenuItem`
- `tests/tui/test_context_menu.py` — 20 tests

**Modified:**
- `hermes_cli/tui/app.py` — `LAYERS`, `on_click`, `_build_context_items`, `_flash_hint`, `compose()` (yield ContextMenu)
- `hermes_cli/tui/input_widget.py` — `on_paste` handler
- `hermes_cli/tui/widgets.py` — `CopyableRichLog.copy_content()` (new method; returns `"\n".join(self._plain_lines)`)
- `hermes_cli/tui/hermes.tcss` — `_ContextItem:hover`, `_ContextSep` visual rules

---

## 8. Implementation Plan

**Step 0 — Scaffolding**
- Add `LAYERS = ("default", "overlay")` to `HermesApp`
- Add `yield ContextMenu(id="context-menu")` to `compose()`
- Add stub `context_menu.py` with `ContextMenu(display:none, can_focus=True)`, `MenuItem` dataclass
- Add `copy_content()` to `CopyableRichLog` in `widgets.py`: `return "\n".join(self._plain_lines)`

**Step 1 — Copy/paste flash (independent, zero risk)**
- Add `_flash_hint` to `HermesApp`
- Add copy flash in `on_key` ctrl+c selected-text branch
- Add `on_paste` to `HermesInput`
- Tests: `test_flash_hint_*` (3 tests)

**Step 2 — ContextMenu widget**
- Implement `ContextMenu.show()`, `dismiss()` (uses `Widget.recompose()` to rebuild children)
- Implement `_ContextItem`, `_ContextSep`
- Position clamping logic; `self.focus()` called at end of `show()`
- `on_blur` + `on_key(escape)` dismiss
- Tests: visibility, position clamp, dismiss (7 tests)

**Step 3 — Context dispatch**
- Implement `HermesApp.on_click` with `button == 3` guard
- Implement `_build_context_items` DOM walk
- Wire: ToolBlock path, MessagePanel path, HermesInput path, fallback
- Tests: per-context item lists (8 tests)

**Step 4 — Action implementations**
- `_copy_tool_output(block)` — `block.copy_content()` + flash (`ToolBlock.copy_content()` exists at tool_blocks.py:157)
- `_copy_all_output()` — walk all `CopyableRichLog` instances via `self.query(CopyableRichLog)`, join via `log.copy_content()` (new method added to `CopyableRichLog` in Step 0: `"\n".join(self._plain_lines)`)
- `_copy_panel(panel)` — calls `panel.copy_content()` on the `CopyableRichLog` inside the `MessagePanel` (same new method)
- `_paste_into_input()` — OSC 52 clipboard read is not viable; this item triggers `HermesInput.focus()` + shows a hint to press `ctrl+v`
- Tests: 2 tests for copy actions

---

## 9. State Changes

| Field | Widget/App | Change |
|---|---|---|
| `LAYERS` | `HermesApp` (class) | Added — `("default", "overlay")` |
| *(none)* | `ContextMenu` | New widget; no reactive added to App |

---

## 10. Capabilities Required

None. Context menu is always available; no profile gating.

---

## 11. Cost Impact

Zero. No LLM calls. No token overhead.

---

## 12. Error Conditions

| Condition | Handling |
|---|---|
| `event.widget is None` on right-click | `_build_context_items` returns `[]`; `on_click` returns without showing menu |
| `query_one(ContextMenu)` raises `NoMatches` | `on_click` wrapped in try/except; silently skipped |
| `_build_context_items` finds no items | `on_click` returns without showing menu |
| `ToolBlock.copy_content()` raises | Caught in action lambda; `_flash_hint("⚠ copy failed", 1.5)` |
| `_flash_hint` called with `HintBar` not mounted | `NoMatches` caught; no crash |
| Menu `on_blur` fires during app teardown | `dismiss()` calls `remove_class` which is safe on unmounted widget |

---

## 13. Determinism Impact

None. Context menu is purely local UI state.

---

## 14. Backward Compatibility

- All existing keyboard copy paths unchanged.
- `ctrl+c` selected-text branch gains a hint flash but its copy behaviour is identical.
- Browse-mode `c` key copy is unchanged (`flash_copy()` on `ToolHeader`).
- No config migration needed.

---

## 15. Test Plan

| Step | Tests | Focus |
|---|---|---|
| 1 | 3 | `_flash_hint` sets hint + restores after timer; paste event fires flash |
| 2 | 7 | ContextMenu show/hide; position clamp at right/bottom edges; blur dismiss; escape dismiss; item click dismiss |
| 3 | 8 | Right-click on ToolBlock → correct items; MessagePanel → correct items; HermesInput → correct items; no-match fallback; button!=3 is ignored |
| 4 | 2 | Copy action writes to clipboard; copy-all-output collects all logs |

**Total: 20 tests**

---

## 16. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `LAYERS` declaration breaks existing CSS | Low | High | Add to HermesApp class, run full TUI test suite before merge |
| `on_blur` fires unexpectedly (e.g. focus change within menu) | Medium | Low | `on_blur` only calls `dismiss()` — harmless double-dismiss |
| Menu appears under another overlay | Low | Medium | `layer: overlay` in CSS — same layer as other overlays; ordering within a layer follows DOM order; mount `ContextMenu` last in `compose()` |
| Right-click on input area — `paste` item raises user expectation that it works | Medium | Low | Item shows focus + hint "press ctrl+v to paste"; OSC 52 clipboard read noted as deferred |

---

## 17. Interaction with Other Specs

**Depends on (in):**
- `textual-migration` — HermesApp, HintBar, CopyableRichLog, ToolBlock all implemented
- `autocomplete-engine` — HermesInput subclass used as paste event target

**Enables (out):**
- `tui-text-effects` — `_flash_hint` is reused as the copy-confirmation mechanism after an effect completes

---

## Deferred

- **Keyboard navigation within menu** — Up/Down item selection, Enter to confirm. Not prioritised; existing bindings cover all actions.
- **Mouse hover highlight on ToolHeaders** — requires `on_mouse_move` hit-testing inside scrollable `OutputPanel`. Non-trivial; deferred.
- **OSC 52 clipboard read (paste via menu)** — Most terminals reject clipboard read requests for security reasons. Deferred indefinitely.
- **Context menu on mobile/tmux/SSH** — Mouse protocol varies; OSC 52 write already fire-and-forget. No new caveats added.
- **Selection copy from RichLog content** — Textual `RichLog` doesn't expose a text selection API. The selected-text path currently uses `_get_selected_text()` which reads from `Input`-type widgets only. Full RichLog selection is a Textual upstream limitation.
