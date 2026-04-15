# Input Bar Undo/Redo

**Status:** Implemented
**Priority:** P2
**Depends on:** None
**Goal:** Add Ctrl+Z / Ctrl+Shift+Z undo/redo to the TUI input bar so users can recover from accidental edits without retyping.

---

## 1. Problem

Textual's built-in `Input` widget has **zero undo/redo support** — no bindings, no undo stack, no related methods. When a user accidentally deletes text, pastes over their input, or accepts a completion they didn't want, the only recovery is retyping from scratch.

This is especially painful because `HermesInput` has several mutation paths that can silently change the input value:
- Completion acceptance (Tab) replaces a span of text
- Ghost-text acceptance appends characters (cursor move makes ghost text real)
- `insert_text()` callers can overwrite content
- `_on_paste()` replaces content with pasted text
- Ctrl+U / Ctrl+W / Ctrl+K delete ranges
- Ctrl+C (app.py on_key handler) clears input directly via `inp.content = ""`

Without undo, any of these can force the user to retype a long prompt.

---

## 2. Goals

1. **Ctrl+Z** undoes the last text edit, restoring both value and cursor position
2. **Ctrl+Shift+Z** (and **Ctrl+Y**) redoes a previously undone edit
3. Stack captures edits from typing, completion, paste, and programmatic `value=` changes
4. Stack has bounded size (default 50 entries) — no unbounded memory growth
5. Stack is cleared on submit (Enter) — undo should not reach across submissions
6. No visual indicator needed — the input text itself is the feedback

---

## 3. Non-Goals

- Undo across message submissions (that's what `UndoConfirmOverlay` / `/undo` is for)
- Undo of history navigation (Up/Down) — that's already reversible by design; both stacks are cleared on history nav
- Per-character granularity — snapshot-based (captures after a short idle debounce)
- Undo of completion overlay interactions that don't change the input value

---

## 4. Design

### 4.1 Undo Stack

The undo model uses a "pre-edit value" approach: `_pre_undo_value` tracks the value that existed before the current edit burst. When the debounce fires (or an explicit pre-mutation hook fires), it pushes `_pre_undo_value` to the undo stack — this is the state to **restore** on undo.

```python
@dataclass(slots=True)
class _UndoEntry:
    value: str
    cursor: int
```

State:
- `_undo_stack: list[_UndoEntry]` — states to restore on undo, newest last
- `_redo_stack: list[_UndoEntry]` — states popped by undo, restored on redo
- `_undo_timer: Any | None` — debounce timer handle
- `_pre_undo_value: str` — value before the current edit burst

Max size: `_MAX_UNDO = 50`

### 4.2 Snapshot Capture Strategy

**Two paths for pushing to the undo stack:**

1. **Debounced (typing):** `watch_value` → `_schedule_undo_snapshot()` → 800ms timer → `_flush_undo()`. The timer pushes `_pre_undo_value` (the state before this burst) to the undo stack, then updates `_pre_undo_value = self.value`.

2. **Immediate (pre-mutation):** `_push_undo_snapshot()` called before completion accept, paste, or insert_text. Same logic: pushes `_pre_undo_value`, updates to current value. Cancels pending debounce to prevent double-push.

**Why this works:**
- Typing "hel" then pausing: debounce fires, pushes "" (the pre-edit value) to undo. `_pre_undo_value` becomes "hel".
- Typing "lo" (continuing from "hel"): new debounce. On fire, pushes "hel" to undo. `_pre_undo_value` becomes "hello".
- Ctrl+Z: pops "hel" from undo, pushes "hello" to redo, restores "hel".
- Ctrl+Z again: pops "" from undo, pushes "hel" to redo, restores "".
- Ctrl+Shift+Z: pops "hel" from redo, pushes "" to undo, restores "hel".

### 4.3 Hooks into Existing Methods

| Method | File | Hook | Notes |
|---|---|---|---|
| `watch_value()` | `input_widget.py` | Call `_schedule_undo_snapshot()` | Debounced — groups typing bursts |
| `action_accept_autocomplete()` | `input_widget.py` | Call `_push_undo_snapshot()` before `self.value = new_value` | Cancels debounce; captures pre-completion state |
| `insert_text()` | `input_widget.py` | Call `_push_undo_snapshot()` before `self.value = ...` | Cancels debounce; captures pre-insert state |
| `_on_paste()` | `input_widget.py` | Call `_push_undo_snapshot()` before `super()._on_paste(event)` | Cancels debounce; captures pre-paste state |
| `action_submit()` | `input_widget.py` | Cancel timer, clear both stacks + `_pre_undo_value` | No snapshot — submit clears everything |
| `action_history_prev()` | `input_widget.py` | Clear both stacks + `_pre_undo_value` | History replaces entire value |
| `action_history_next()` | `input_widget.py` | Clear both stacks + `_pre_undo_value` | Same reasoning as prev |
| Ctrl+C clear (on_key priority 3) | `app.py` | Call `inp._push_undo_snapshot()` before `inp.content = ""` | External mutation — must capture pre-clear state |

**External mutations:** Any code outside `HermesInput` that sets `.content` or `.value` directly must call `_push_undo_snapshot()` first. The Ctrl+C handler in `app.py` is the only current external mutator.

### 4.4 Actions & Bindings

```python
Binding("ctrl+z",       "undo_edit", "Undo edit", show=False),
Binding("ctrl+shift+z", "redo_edit", "Redo edit", show=False),
Binding("ctrl+y",       "redo_edit", "Redo edit", show=False),
```

`action_undo_edit()`:
1. If `self.disabled`, return
2. If `_undo_stack` non-empty:
   - Push current `(value, cursor)` to `_redo_stack`
   - Pop from `_undo_stack`, restore value + cursor (cursor defaults to end of text if 0)

`action_redo_edit()`:
1. If `self.disabled`, return
2. If `_redo_stack` non-empty:
   - Push current `(value, cursor)` to `_undo_stack`
   - Pop from `_redo_stack`, restore value + cursor

Cursor heuristic: debounce entries use cursor=0 (no cursor tracking for typing bursts). On undo, if entry cursor is 0, place cursor at `len(entry.value)` (end of restored text). Explicit entries (from redo or undo) preserve the real cursor position.

### 4.5 Implementation Details

```python
# In __init__:
self._undo_stack: list[_UndoEntry] = []
self._redo_stack: list[_UndoEntry] = []
self._undo_timer: Any | None = None
self._pre_undo_value: str = ""

def _schedule_undo_snapshot(self) -> None:
    if self._undo_timer is not None:
        self._undo_timer.stop()
    self._undo_timer = self.set_timer(_UNDO_DEBOUNCE_S, self._flush_undo)

def _flush_undo(self) -> None:
    self._undo_timer = None
    entry = _UndoEntry(self._pre_undo_value, 0)
    if not (self._undo_stack and self._undo_stack[-1] == entry):
        self._undo_stack.append(entry)
        if len(self._undo_stack) > _MAX_UNDO:
            self._undo_stack.pop(0)
    self._redo_stack.clear()
    self._pre_undo_value = self.value

def _push_undo_snapshot(self) -> None:
    if self._undo_timer is not None:
        self._undo_timer.stop()
        self._undo_timer = None
    entry = _UndoEntry(self._pre_undo_value, 0)
    if not (self._undo_stack and self._undo_stack[-1] == entry):
        self._undo_stack.append(entry)
        if len(self._undo_stack) > _MAX_UNDO:
            self._undo_stack.pop(0)
    self._redo_stack.clear()
    self._pre_undo_value = self.value
```

### 4.6 Edge Cases

- **Empty initial state:** `_pre_undo_value` starts as `""`. First edit burst pushes `""` to undo — correct (undo restores empty).
- **Sanitization loop:** `_sanitizing_value` guard prevents `watch_value` from scheduling debounce during sanitization.
- **Disabled state:** Both actions early-return when `self.disabled`.
- **Dedup:** `_flush_undo` and `_push_undo_snapshot` skip if stack top equals the entry being pushed (prevents double-push from debounce + explicit hook).
- **Completion with pending debounce:** `_push_undo_snapshot()` cancels the timer, preventing the stale debounce from also firing.
- **Ctrl+U/W/K delete actions:** Go through `watch_value` → debounce → `_flush_undo`. Groups with preceding typing.
- **Ctrl+C clear from app.py:** External mutation — `app.py` calls `inp._push_undo_snapshot()` before `inp.content = ""`.

---

## 5. Design Decisions

| Decision | Chosen | Alternative | Reason |
|---|---|---|---|
| Model | Pre-edit value with debounce | Push current state on change | Pushing current state creates wrong undo behavior (restores current, not previous) |
| Granularity | Debounced (800ms) coalesced snapshots | Per-keystroke | Per-keystroke makes undo painfully slow for long edits |
| Debounce interval | 800ms | 500ms / 1200ms | 500ms too short (pauses mid-word trigger); 1200ms too long |
| Stack size | 50 | 20 / 100 | 20 too few; 100 wastes memory |
| Clear on submit | Yes | No | Undo across submissions is confusing; `/undo` handles message-level |
| History nav | Clear both stacks | Preserve | Up/Down replaces entire value; redo after history is meaningless |
| Cursor on undo | End of text if entry cursor is 0 | Always 0 | Debounce entries don't track cursor; end-of-text is the natural position |
| External mutations | Caller responsibility | Intercept in setter | Only one external mutator (app.py Ctrl+C); simpler than setter interception |

---

## 6. Configuration

No config.yaml changes — this is a UX feature with sane defaults. Module-level constants `_UNDO_DEBOUNCE_S = 0.8`, `_MAX_UNDO = 50`.

---

## 7. Files Changed

| File | Change |
|---|---|
| `hermes_cli/tui/input_widget.py` | Added `_UndoEntry` dataclass, `_MAX_UNDO`/`_UNDO_DEBOUNCE_S` constants, undo/redo stacks + timer + `_pre_undo_value` in `__init__`, `_schedule_undo_snapshot()` + `_flush_undo()` + `_push_undo_snapshot()` methods, `action_undo_edit()` + `action_redo_edit()` methods, 3 bindings, hooks in `watch_value`/`action_accept_autocomplete`/`insert_text`/`_on_paste`/`action_submit`/`action_history_prev`/`action_history_next`, timer cleanup in `on_unmount` |
| `hermes_cli/tui/app.py` | Added `inp._push_undo_snapshot()` call before `inp.content = ""` in Ctrl+C on_key handler |
| `tests/tui/test_hermes_input.py` | Added 15 undo/redo test cases |

---

## 8. Implementation Plan (Completed)

1. ✅ Added `_UndoEntry` dataclass and constants
2. ✅ Added undo/redo stacks, timer, `_pre_undo_value` to `__init__`
3. ✅ Added `_schedule_undo_snapshot()`, `_flush_undo()`, `_push_undo_snapshot()`
4. ✅ Added `action_undo_edit()` and `action_redo_edit()` with cursor heuristic
5. ✅ Added `ctrl+z`, `ctrl+shift+z`, `ctrl+y` bindings
6. ✅ Hooked `watch_value()` → `_schedule_undo_snapshot()`
7. ✅ Hooked `action_accept_autocomplete()` → `_push_undo_snapshot()` before mutation
8. ✅ Hooked `insert_text()` → `_push_undo_snapshot()` before mutation
9. ✅ Hooked `_on_paste()` → `_push_undo_snapshot()` before `super()._on_paste()`
10. ✅ Hooked `action_submit()` — cancel timer, clear stacks + `_pre_undo_value`
11. ✅ Hooked `action_history_prev()` — clear stacks + `_pre_undo_value`
12. ✅ Hooked `action_history_next()` — clear stacks + `_pre_undo_value`
13. ✅ Added `inp._push_undo_snapshot()` in app.py Ctrl+C handler
14. ✅ Timer cleanup in `on_unmount()`
15. ✅ Written 15 tests — all passing

---

## 9. Test Results

15 tests, all passing:
- test_undo_basic, test_undo_multi_step, test_redo_roundtrip, test_redo_ctrl_y
- test_completion_undo, test_submit_clears_stacks, test_history_nav_clears_stacks
- test_stack_cap, test_undo_disabled_noop, test_undo_empty_stack_noop, test_redo_empty_stack_noop
- test_undo_empty_state, test_edit_after_undo_clears_redo
- test_debounce_cancelled_by_push, test_dedup_skips_identical_top
- test_undo_cursor_preserved, test_full_undo_redo_chain

Full TUI suite: 1000 passed, 0 regressions.

---

## 10. Backward Compatibility

Fully backward compatible — new bindings only, no existing behavior changes. Users who never press Ctrl+Z see zero difference. No `ctrl+z` or `ctrl+y` bindings exist in `HermesInput`, `HermesApp`, or Textual's `Input` base class (verified).
