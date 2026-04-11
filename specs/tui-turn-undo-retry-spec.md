# TUI Turn Undo / Retry — Feature Specification

**Status:** APPROVED  
**Impact:** Medium-High  
**Key:** SPEC-C  

---

## 1. Problem Statement

`/undo` and `/retry` already exist as CLI commands registered in `COMMAND_REGISTRY` but have no TUI-layer integration:

- No visual feedback when undo/retry is in progress
- The last `MessagePanel` turn remains visible in the DOM after undo — DOM is not updated
- File edits made during a turn are not reverted (no checkpoint integration)
- `/rollback` (filesystem checkpoint restore) has no TUI confirmation overlay

This spec defines the TUI-layer plumbing for undo, retry, and rollback: DOM cleanup, confirmation overlay, agent-layer coordination, and file-revert feedback.

---

## 2. Scope

| In scope | Out of scope |
|---|---|
| `/undo` removes last user+assistant turn from the TUI DOM | Multi-level undo (more than one exchange) |
| `/undo` triggers file-edit revert via existing rollback checkpoint | Implementing the checkpoint system itself |
| `/retry` resends the last user message; does not remove any turns | Branching / forking sessions |
| Undo confirmation overlay (shows what will be removed) | Undo of tool-block output without removing the turn |
| Visual feedback: opacity fade before removal | Persistent undo history across sessions |
| `/rollback [N]` TUI confirmation before filesystem restore | |
| HintBar status during revert: "↩ Reverting…" | |

---

## 3. Command Flow Overview

```
User types /undo  ─►  HermesApp._handle_tui_command("/undo")
                           │
                           ├─►  Show UndoConfirmOverlay
                           │         │
                           │    User presses Y / Enter
                           │         │
                           ├─►  _run_undo_sequence()  [async, @work(thread=False)]
                           │         │
                           │    1. Flash last MessagePanel (dim opacity fade)
                           │    2. asyncio.to_thread(self.cli.agent.undo)
                           │    3. panel.remove()  (sync DOM removal)
                           │    4. Restore last user message to HermesInput
                           │    5. Show "↩  Undo done" in HintBar (2 s)
```

---

## 4. TUI State Addition

Add one new reactive to `HermesApp`:

```python
undo_state: reactive[UndoOverlayState | None] = reactive(None)
```

`UndoOverlayState` is a new dataclass in `hermes_cli/tui/state.py`:

```python
import queue as _queue
from dataclasses import dataclass, field

@dataclass
class UndoOverlayState(OverlayState):
    """State for the undo confirmation overlay.
    
    Inherits `deadline: float` and `response_queue: queue.Queue` from OverlayState.
    """
    user_text: str = ""         # the user message that will be removed
    has_checkpoint: bool = False  # True if a filesystem checkpoint exists
    # NOTE: response_queue is inherited from OverlayState — do NOT redefine it here
```

`UndoConfirmOverlay` inherits `CountdownMixin` with a 10-second auto-cancel (safety default: undo is destructive).

---

## 5. UndoConfirmOverlay Widget

```
┌─ Undo last exchange? ─────────────────────────────────┐
│                                                        │
│  Removes:  "write a function to parse ISO dates…"      │
│  + agent's response                                    │
│  + filesystem checkpoint revert (if available)         │
│                                                        │
│  [Y] Confirm    [N] Cancel            auto-cancel 10s  │
└────────────────────────────────────────────────────────┘
```

### 5.1 Behaviour

- Inherits `CountdownMixin` (`_state_attr = "undo_state"`, `_timeout_response = "cancel"`, `_countdown_prefix = "undo"`)
- `_timeout_response = "cancel"` — safety default; undo is destructive
- `Y` / `Enter` → puts `"confirm"` on `response_queue`; sets `self.app.undo_state = None`
- `N` / `Escape` → puts `"cancel"` on `response_queue`; sets `self.app.undo_state = None`

### 5.2 DOM integration

Add to `HermesApp.compose()` inside the `with Vertical(id="overlay-layer"):` block:

```python
yield UndoConfirmOverlay(id="undo-confirm")
```

Add to `HermesApp.on_key()` overlay key-dispatch loop (same pattern as approval/clarify):

```python
if self.undo_state is not None:
    if event.key in ("y", "enter"):
        self.undo_state.response_queue.put("confirm")
        self.undo_state = None
        event.prevent_default()
        return
    if event.key in ("n", "escape"):
        self.undo_state.response_queue.put("cancel")
        self.undo_state = None
        event.prevent_default()
        return
```

### 5.3 Agent-start-mid-overlay guard

`watch_agent_running` already exists in `HermesApp` (app.py:443). The undo guard must be **prepended as the very first block** inside the existing watcher:

```python
def watch_agent_running(self, value: bool) -> None:
    # --- NEW: undo safety guard ---
    if value and self.undo_state is not None:
        # Agent started while undo overlay was open — auto-cancel for safety
        self.undo_state.response_queue.put("cancel")
        self.undo_state = None
        self._flash_hint("⚠  Agent started, undo cancelled", 2.0)
    # --- END NEW ---

    # ... existing watch_agent_running body follows unchanged ...
```

The existing watcher body (input enable/disable, `OutputPanel.new_message()`, HintBar clear) is preserved below the new guard block.

---

## 6. Undo Sequence (TUI side)

`_run_undo_sequence()` is decorated with `@work(thread=False)` (async coroutine on the event loop — NOT a thread worker):

```python
@work(thread=False)
async def _run_undo_sequence(self, panel: MessagePanel) -> None:
    try:
        self._undo_in_progress = True

        # Step 1: Opacity fade to signal impending removal
        # Panel must be visible before the transition fires.
        panel.styles.opacity = 0.3
        await asyncio.sleep(0.4)  # wait for CSS transition (0.3s + safety margin)

        # Step 2: Call agent undo in a thread so the event loop stays responsive
        try:
            await asyncio.to_thread(self.cli.agent.undo)
        except (AttributeError, NotImplementedError):
            self._flash_hint("⚠  Undo not supported by agent", 2.0)
            panel.styles.opacity = 1.0  # restore opacity
            return

        # Step 3: Remove the MessagePanel from DOM (synchronous in Textual)
        panel.remove()

        # Step 4: Restore user message to HermesInput (if stored)
        user_text = getattr(panel, "_user_text", "")
        if user_text:
            try:
                from hermes_cli.tui.input_widget import HermesInput
                hi = self.query_one(HermesInput)
                hi.value = user_text
                hi.cursor_position = len(user_text)
            except NoMatches:
                pass

        # Step 5: Feedback
        self._flash_hint("↩  Undo done", 2.0)
    finally:
        self._undo_in_progress = False
```

**CSS for the opacity transition** (add to `hermes.tcss`):

```css
MessagePanel {
    transition: opacity 0.3s in_out_cubic;
}
```

This is defined on `MessagePanel` globally (not a class). When `panel.styles.opacity = 0.3` is set, the transition fires automatically because `MessagePanel` is always visible (never `display: none`) when undo is initiated.

**`_undo_in_progress` flag:**

Add to `HermesApp.__init__()`:

```python
self._undo_in_progress: bool = False
```

The `/undo` command handler checks this flag before initiating:

```python
def _initiate_undo(self) -> None:
    if self._undo_in_progress:
        self._flash_hint("⚠  Undo in progress", 1.5)
        return
    if self.agent_running:
        self._flash_hint("⚠  Cannot undo while agent is running", 2.0)
        return
    panels = list(self.query(MessagePanel))
    if not panels:
        self._flash_hint("⚠  Nothing to undo", 1.5)
        return
    last_panel = panels[-1]
    user_text = getattr(last_panel, "_user_text", "")
    state = UndoOverlayState(
        deadline=time.monotonic() + 10,
        response_queue=queue.Queue(),
        user_text=user_text[:80] + "…" if len(user_text) > 80 else user_text,
        has_checkpoint=self._has_rollback_checkpoint(),
    )
    self.undo_state = state
    # Wait for response in a thread (blocking queue.get)
    self._await_undo_response(state, last_panel)

def _has_rollback_checkpoint(self) -> bool:
    """Return True if the agent has a filesystem checkpoint available to revert.
    
    Asks the agent without blocking — uses getattr to avoid AttributeError
    if the method doesn't exist yet.
    """
    try:
        return bool(getattr(self.cli.agent, "has_checkpoint", lambda: False)())
    except Exception:
        return False

@work(thread=True)
def _await_undo_response(self, state: UndoOverlayState, panel: MessagePanel) -> None:
    answer = state.response_queue.get()   # blocks agent thread
    if answer == "confirm":
        self.call_from_thread(self._run_undo_sequence, panel)
```

---

## 7. Storing User Text in MessagePanel

`MessagePanel` needs to store the user message that initiated the turn.

**Change to `MessagePanel.__init__`:**

```python
def __init__(self, user_text: str = "", **kwargs: Any) -> None:
    ...  # existing init unchanged
    self._user_text: str = user_text
```

**Change to `OutputPanel.new_message()`** (adds `user_text` keyword parameter):

```python
def new_message(self, user_text: str = "") -> MessagePanel:
    panel = MessagePanel(user_text=user_text)
    self.mount(panel, before=self.query_one(LiveLineWidget))
    self.current_message = panel
    return panel
```

**Caller in `cli.py`** passes the raw user string. The existing `watch_agent_running` watcher at app.py:459 also calls `new_message()` (without `user_text`). To avoid creating a second MessagePanel, that call must be **replaced** by the explicit call from `cli.py`:

1. Remove `new_message()` call from `watch_agent_running` (it will now be called from `cli.py`)
2. In `cli.py`, before setting `agent_running = True`, call:

```python
app.call_from_thread(app.query_one(OutputPanel).new_message, user_text=raw_input)
```

This ensures one MessagePanel is created per turn with the correct `_user_text`, while the `watch_agent_running` body retains input-disable and HintBar-clear logic.

Alternatively, store `raw_input` on `HermesApp` before setting `agent_running`:

```python
# In cli.py, before agent.run():
app.call_from_thread(setattr, app, "_last_user_input", raw_input)
app.call_from_thread(setattr, app, "agent_running", True)
```

Then in `watch_agent_running`:
```python
if value:
    self.query_one(OutputPanel).new_message(user_text=self._last_user_input)
```

Either approach works. The second (store-then-watch) is less disruptive to existing code structure.

---

## 8. /retry Command

`/retry` resends the last user message as a new agent call (non-destructive):

```python
def _initiate_retry(self) -> None:
    if self.agent_running:
        self._flash_hint("⚠  Cannot retry while agent is running", 2.0)
        return
    panels = list(self.query(MessagePanel))
    if not panels:
        self._flash_hint("⚠  Nothing to retry", 1.5)
        return
    last_user_text = getattr(panels[-1], "_user_text", "")
    if not last_user_text:
        self._flash_hint("⚠  No user message to retry", 1.5)
        return
    # Populate HermesInput and submit programmatically
    try:
        from hermes_cli.tui.input_widget import HermesInput
        hi = self.query_one(HermesInput)
        hi.value = last_user_text
        hi.cursor_position = len(last_user_text)
        hi.action_submit()   # Textual Input built-in: fires Input.Submitted message
    except NoMatches:
        pass
```

`action_submit()` is the public Textual `Input` API that fires the `Input.Submitted` message — the same path as pressing Enter. No private methods are called.

---

## 9. /rollback Command Integration

`/rollback [N]` shows a confirmation overlay before restoring a filesystem checkpoint.

```
┌─ Rollback filesystem? ──────────────────────────────────┐
│                                                          │
│  Checkpoint: 2026-04-11 14:32:07  (2 files changed)     │
│  Changes: hermes_cli/tui/app.py, hermes_cli/tui/widgets.py │
│                                                          │
│  This cannot be undone.                                  │
│                                                          │
│  [Y] Restore    [N] Cancel            auto-cancel 15s    │
└──────────────────────────────────────────────────────────┘
```

- Separate overlay widget: `RollbackConfirmOverlay` (same `CountdownMixin` pattern)
- `_timeout_response = "cancel"` — 15 second timeout (more destructive than undo)
- After confirmation: `await asyncio.to_thread(self.cli.agent.rollback, n)` in `_run_rollback_sequence()`
- Does NOT remove `MessagePanel` turns — conversation history stays; only files revert
- Feedback: `"↩  Rollback done"` on completion

**`/rollback [N]` parameter extraction:**

```python
import re

def _initiate_rollback(self, text: str) -> None:
    m = re.match(r"^/rollback(?:\s+(\d+))?$", text.strip())
    if not m:
        self._flash_hint("⚠  Usage: /rollback [N]", 2.0)
        return
    n = int(m.group(1)) if m.group(1) else 0
    # ... build RollbackOverlayState with checkpoint info from agent ...
```

---

## 10. HermesApp Command Handler Integration

`_handle_tui_command()` is called from `HermesInput`'s submit handler **before** the text is forwarded to the agent. It returns `True` if the command was consumed by the TUI layer:

```python
def _handle_tui_command(self, text: str) -> bool:
    """Intercept TUI-specific slash commands before agent sees them.
    
    Returns True if the command was handled here (do not forward to agent).
    Returns False if not a TUI command (forward to agent as normal).
    """
    stripped = text.strip()
    if stripped == "/undo":
        self._initiate_undo()
        return True
    if stripped == "/retry":
        self._initiate_retry()
        return True
    if re.match(r"^/rollback(?:\s+\d+)?$", stripped):
        self._initiate_rollback(stripped)
        return True
    return False
```

This is called from the existing input submission handler in `cli.py` (or from `HermesInput.on_input_submitted`):

```python
# In the submit handler, before forwarding to agent:
if app._handle_tui_command(text):
    return   # consumed by TUI; do not send to agent
# ... proceed with normal agent forwarding ...
```

---

## 11. Agent-Layer Contracts

This spec does **not** implement the agent-side undo/retry logic. It assumes:

| Method | Pre-condition | Effect |
|---|---|---|
| `agent.undo()` | `agent_running == False` | Pops last user+assistant exchange from conversation; may revert last filesystem checkpoint |
| `agent.rollback(n: int)` | `agent_running == False` | Restores filesystem to checkpoint N; does NOT touch conversation history |

If these raise `AttributeError` / `NotImplementedError`, the undo sequence catches them and flashes `"⚠  Undo not supported by agent"` (see §6).

---

## 12. Tests

File: `tests/tui/test_turn_undo_retry.py`

| # | Test | Assertion |
|---|---|---|
| 1 | `/undo` opens `UndoConfirmOverlay` | `undo_state` not None; overlay visible |
| 2 | `N` key on overlay → `undo_state = None` | Overlay hides |
| 3 | `Escape` key on overlay → cancels | Overlay hides |
| 4 | `Y` → `_run_undo_sequence` triggered | `panel.remove()` observed |
| 5 | Undo sequence sets `panel.styles.opacity = 0.3` | Opacity set before remove |
| 6 | Undo sequence calls `agent.undo()` | Mock `.undo()` called once |
| 7 | After undo, last `MessagePanel` removed from DOM | `len(app.query(MessagePanel))` decremented by 1 |
| 8 | After undo, `HermesInput.value` == last user text | Input value restored |
| 9 | `/undo` while `agent_running=True` → flash warning | `HintBar.hint` contains "Cannot undo" |
| 10 | `/undo` with no turns → "Nothing to undo" | `HintBar.hint` text |
| 11 | `UndoConfirmOverlay` auto-cancels after timeout | `undo_state = None` after countdown |
| 12 | `/retry` with no prior turn → "Nothing to retry" | `HintBar.hint` text |
| 13 | `/retry` calls `HermesInput.action_submit()` with correct text | Input value set + `action_submit` called |
| 14 | `/retry` does NOT open confirmation overlay | `undo_state` stays None |
| 15 | `MessagePanel._user_text` stored on creation | Attribute correct after `new_message(user_text="hello")` |
| 16 | `/rollback` opens `RollbackConfirmOverlay` | Overlay visible |
| 17 | Rollback confirm calls `agent.rollback(n)` | Mock called with correct N |
| 18 | Rollback cancel leaves DOM unchanged | No panels removed |
| 19 | `agent.undo()` raises `NotImplementedError` → flash warning | HintBar shows "⚠  Undo not supported" |
| 20 | `_handle_tui_command("/undo")` returns True | CLI does not forward to agent |
| 21 | `_handle_tui_command("/help")` returns False | CLI forwards to agent |
| 22 | `_undo_in_progress=True` → second `/undo` flashes "Undo in progress" | `HintBar.hint` text |
| 23 | `agent_running` changes to True while overlay open → auto-cancel | `undo_state = None`; HintBar shows cancel message |

---

## 13. Edge Cases

- **Multiple rapid `/undo` presses:** Guarded by `_undo_in_progress` flag.
- **Undo after streaming starts:** Handled by `watch_agent_running` watcher (§5.3).
- **Empty `_user_text`:** "Restore to input" step skipped silently.
- **DOM panel for live turn:** `LiveLineWidget` is not a `MessagePanel`; `query(MessagePanel)` excludes it. Last completed panel is the correct undo target.
- **`/rollback` typos:** `_handle_tui_command` regex match must be precise: `/rollback` or `/rollback N` only. Typos like `/rollback_foo` return `False` and forward to agent.
