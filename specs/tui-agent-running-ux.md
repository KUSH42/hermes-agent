# Agent-Running UX & Active-File Breadcrumb — Feature Specification

**Status:** Implemented 2026-04-11  
**Priority:** P0  
**Branch target:** `feat/textual-migration`  
**Depends on:** textual-migration (implemented), tui-animation-novel-techniques (implemented)  
**Goal:** Keep the input bar spatially anchored during agent runs and show a real-time active-file breadcrumb in the StatusBar, exploiting Textual's reactive engine to deliver a premium UX Ink/React cannot match.

---

## 1. Problem Statement

### 1.1 Input visibility gap

`_tick_spinner` in `app.py` currently hides the input widget when the agent is running:

```python
# app.py:388 — current broken behaviour
overlay.display = True
inp.display = False     # ← user loses their staging area every turn
```

This means:
- The input bar **disappears** for the entire duration of every agent turn.
- The user cannot paste, review, or stage their next message while waiting.
- The **spatial anchor** (the `❯` prompt line) jumps on every turn start/end — visually jarring and perceived as "cheap" compared to Ink apps that keep the prompt fixed.
- The `#spinner-overlay` Static that replaces it uses a width of `1fr` but `display: none` by default; the show/hide cycle creates a layout reflow on every tick.

**Evidence:** `app.py:381–394` (`_tick_spinner`) unconditionally sets `inp.display = False` when `spinner_display` is truthy. The `watch_agent_running` watcher (lines 482–495) restores `widget.display = True` only on turn-end — confirming the hiding is not a guard but the primary flow.

**Quick-wins already shipped** (do not re-implement):
- GAP-17: `call_after_refresh(widget.focus)` on turn-end (app.py:495)
- Chevron dim: `set_class(value, "--busy")` + `#input-chevron.--busy { color: $text-muted 40%; }` (app.py:471, hermes.tcss:84)

### 1.2 Active-file breadcrumb gap

`StatusBar.render()` displays `model | compaction bar | tok/s | tokens | duration | state`. When the agent calls `read_file("src/auth.py")` the spinner label in `_build_hint_text()` strips verbose prefixes and shows just the tool name + args — but this text appears only in the `#spinner-overlay` (which is hidden behind the input) and is never surfaced in the persistent StatusBar.

The user sees `● running` but has no idea which file is being touched, making the agent feel like a black box.

---

## 2. Goals

1. Input bar is visible and spatially stable at **all times** — no `display: none` during agent runs.
2. Spinner text is delivered as `HermesInput.placeholder` — zero layout reflow; the `#spinner-overlay` becomes a dead widget with `display: none` always (to be removed in a future cleanup pass).
3. `status_active_file: reactive[str]` is set on `HermesApp` whenever `spinner_label` names a file-touching tool and contains a path.
4. `StatusBar.render()` inserts a `📄 <path>` breadcrumb between the left stats and the right state label when `status_active_file` is non-empty.
5. All existing spinner, hint, and status-bar tests continue to pass.
6. New tests cover: placeholder spinner, focus restore, file extraction (hit/miss/no-path), breadcrumb render (present/absent/narrow terminal).

---

## 3. Non-Goals

| Exclusion | Reason |
|---|---|
| Removing the `#spinner-overlay` Static from `compose()` | Deferred cleanup — safe to leave as always-hidden for now |
| Parsing tool arguments beyond a path regex | Over-engineering; the regex is sufficient for all current tools |
| File-path breadcrumb in browse mode | Browse mode renders its own left text; breadcrumb would conflict |
| Showing breadcrumb in the HintBar | HintBar is reserved for timed flash messages |
| pyperclip / clipboard integration | Separate spec (SPEC-E) |
| Breadcrumb for non-file tools (bash, search) | Separate future spec |

---

## 4. Design

### 4.1 Input visibility — placeholder spinner

**Core change:** `_tick_spinner` will no longer touch `inp.display`. Instead:

```
_tick_spinner (0.1 s tick)
  ↓ builds spinner_display string
  ↓ updates #spinner-overlay (still present, always hidden — legacy guard)
  ↓ sets inp.placeholder = spinner_display   ← NEW
```

`HermesInput` inherits Textual's `Input`, which renders `.input--placeholder` when `value == ""` and the widget is disabled (or always when value is empty). The placeholder disappears automatically when the user types — zero manual cleanup required.

**Clearing on turn-end:** `watch_agent_running(False)` already calls `widget.display = True` (safety guard). We add `widget.placeholder = ""` in that same branch to clear the spinner text.

**CSS:** `HermesInput > .input--placeholder` already styles `color: #555555; text-style: italic` (hermes.tcss:112). No new CSS needed.

**Structural change:** The `#spinner-overlay` Static stays in `compose()` and the DOM but is never shown. The `inp.display = False / True` pair inside `_tick_spinner` is removed entirely.

### 4.2 Active-file breadcrumb

#### 4.2.1 HermesApp additions

```python
# Module-level constants (app.py, below imports)
_FILE_TOOLS: frozenset[str] = frozenset({
    "read_file", "write_file", "edit_file", "create_file",
    "view", "str_replace_editor", "patch",
})

_PATH_EXTRACT_RE = re.compile(
    r'["\']?(/[\w./\-]+|[\w./\-]+\.[\w]{1,6})["\']?'
)

# New reactive on HermesApp (below spinner_label declaration, line ~146)
status_active_file: reactive[str] = reactive("")
```

#### 4.2.2 Updated `watch_spinner_label`

```python
def watch_spinner_label(self, value: str) -> None:
    """Reset per-tool elapsed timer and extract active file path."""
    self._tool_start_time = _time.monotonic() if value else 0.0
    if value and isinstance(value, str):
        tool_name = value.split("(")[0].split(" · ")[0].strip()
        if tool_name in _FILE_TOOLS:
            m = _PATH_EXTRACT_RE.search(value)
            self.status_active_file = m.group(1) if m else ""
        else:
            self.status_active_file = ""
    else:
        self.status_active_file = ""
```

**Why `split("(")[0].split(" · ")[0].strip()`:** `spinner_label` labels are already prefix-stripped by `_build_hint_text()` (which removes `"Calling tool: "` etc.). The resulting format is either `"read_file(path='src/auth.py')"` (with args) or `"read_file · 1.2s"` (with elapsed time appended by `_tick_spinner`). The double-split isolates just the bare tool name in both formats.

#### 4.2.3 StatusBar changes

**`on_mount` addition** — add `status_active_file` to the existing watch loop:

```python
for attr in (
    "status_tokens", "status_model", "status_duration",
    "status_compaction_progress", "status_compaction_enabled",
    "command_running",
    "browse_mode", "browse_index", "_browse_total",
    "status_output_dropped",
    "status_active_file",          # ← NEW
):
    self.watch(app, attr, self._on_status_change)
```

**`render()` update** — insert breadcrumb between left stats and the right state label. Only injected in the non-browse path (browse mode has its own left-side text). Width gate: only shown when `width >= 60`.

```python
# After building `t` (left stats) and before the right-side state label:
active_file = str(getattr(app, "status_active_file", ""))
if active_file and width >= 60:
    t.append("  📄 ", style="dim")
    # Truncate long paths to avoid crowding; keep filename visible
    max_path = max(10, width // 4)
    display_path = active_file if len(active_file) <= max_path else "…" + active_file[-(max_path - 1):]
    t.append(display_path, style="dim")
```

The breadcrumb segment is injected BEFORE the padding calculation so the right-anchored state label still right-aligns correctly.

---

## 5. Design Decisions

| Decision | Alternative considered | Reason chosen |
|---|---|---|
| Placeholder for spinner text | Keep `#spinner-overlay` overlay | Zero layout reflow; Input API handles dim/show automatically when disabled |
| `HermesInput.placeholder` attribute | Custom `spinner_text` attribute | Textual's native `Input.placeholder` renders via `.input--placeholder` CSS — no custom render path |
| `status_active_file` reactive on HermesApp | Derive in `StatusBar.render()` from `spinner_label` | Reactive keeps StatusBar read-only; file extraction logic stays with agent state |
| Path regex `[\w./\-]+\.[\w]{1,6}` | Full POSIX path parser | Sufficient for all tool call formats; avoids false positives on pure directory args |
| Width gate `>= 60` for breadcrumb | Always show | Narrow terminals would overlap the state label |
| Path truncation `width // 4` | Fixed 20-char limit | Scales with terminal width; keeps filename always visible |
| Leave `#spinner-overlay` in DOM | Remove it | Removal requires updating tests; safe to defer as it stays `display: none` permanently |

---

## 6. Configuration

No new YAML configuration is introduced. The breadcrumb and placeholder behaviour are always-on; they derive from existing `spinner_label` and `agent_running` reactives.

---

## 7. Files Changed

### Modified

| File | Changes |
|---|---|
| `hermes_cli/tui/app.py` | Add `_FILE_TOOLS`, `_PATH_EXTRACT_RE` constants; add `status_active_file` reactive; update `watch_spinner_label`; update `_tick_spinner` (remove `inp.display` toggle, add `inp.placeholder`); update `watch_agent_running` (add `widget.placeholder = ""` on turn-end) |
| `hermes_cli/tui/widgets.py` | `StatusBar.on_mount`: add `status_active_file` to watch loop; `StatusBar.render`: inject breadcrumb segment |

### New

| File | Contents |
|---|---|
| `tests/tui/test_agent_running_ux.py` | 18 new tests covering placeholder spinner, focus restore, file extraction, breadcrumb render, narrow terminal |

---

## 8. Implementation Plan

**Step 1 — Remove `inp.display` toggle from `_tick_spinner`**

In `app.py:381–394`, delete the `inp.display = False` and `inp.display = True` lines. Keep the `overlay.display = True/False` lines for now (legacy no-op). Add `inp.placeholder = spinner_display` when `spinner_display` is truthy; clear it otherwise.

```python
# _tick_spinner (revised)
try:
    inp = self.query_one("#input-area")
    overlay = self.query_one("#spinner-overlay", Static)
    # Keep overlay hidden always; use placeholder for spinner text
    overlay.display = False
    if hasattr(inp, "placeholder"):
        inp.placeholder = spinner_display if spinner_display else ""
    if hasattr(inp, "spinner_text"):
        inp.spinner_text = spinner_display
except NoMatches:
    pass
```

**Step 2 — Clear placeholder on turn-end in `watch_agent_running`**

In `app.py:482–495`, add `widget.placeholder = ""` after the existing `widget.display = True`:

```python
if not value:
    if hasattr(widget, "spinner_text"):
        widget.spinner_text = ""
    widget.display = True
    if hasattr(widget, "placeholder"):
        widget.placeholder = ""      # ← NEW
    try:
        self.query_one("#spinner-overlay", Static).display = False
    except NoMatches:
        pass
    self.call_after_refresh(widget.focus)
```

**Step 3 — Add `status_active_file` reactive to HermesApp**

In `app.py`, after `spinner_label: reactive[str] = reactive("")` (~line 146), add:

```python
status_active_file: reactive[str] = reactive("")
```

**Step 4 — Add module-level constants**

In `app.py`, after the existing `import re` block (top of file), add:

```python
_FILE_TOOLS: frozenset[str] = frozenset({
    "read_file", "write_file", "edit_file", "create_file",
    "view", "str_replace_editor", "patch",
})

_PATH_EXTRACT_RE = re.compile(
    r'["\']?(/[\w./\-]+|[\w./\-]+\.[\w]{1,6})["\']?'
)
```

**Step 5 — Update `watch_spinner_label`**

Replace `app.py:513–515`:

```python
def watch_spinner_label(self, value: str) -> None:
    """Reset per-tool elapsed timer and extract active file path."""
    self._tool_start_time = _time.monotonic() if value else 0.0
    if value and isinstance(value, str):
        tool_name = value.split("(")[0].split(" · ")[0].strip()
        if tool_name in _FILE_TOOLS:
            m = _PATH_EXTRACT_RE.search(value)
            self.status_active_file = m.group(1) if m else ""
        else:
            self.status_active_file = ""
    else:
        self.status_active_file = ""
```

**Step 6 — Update `StatusBar.on_mount`**

In `widgets.py:994–1001`, add `"status_active_file"` to the attribute list in the watch loop.

**Step 7 — Update `StatusBar.render`**

In `widgets.py:1076–1128` (the non-browse branch), insert the breadcrumb segment after building the left stats `t` and before the padding + state-label suffix. Insert between the duration append and the right-anchored state label:

```python
active_file = str(getattr(app, "status_active_file", ""))
if active_file and width >= 60:
    t.append("  📄 ", style="dim")
    max_path = max(10, width // 4)
    display_path = (
        active_file if len(active_file) <= max_path
        else "…" + active_file[-(max_path - 1):]
    )
    t.append(display_path, style="dim")
```

**Step 8 — Write tests**

Create `tests/tui/test_agent_running_ux.py` with 18 tests (see §11 Test Plan).

---

## 9. State Changes

| Reactive | Added/Modified | Owner | Read by |
|---|---|---|---|
| `status_active_file: reactive[str]` | **Added** | `HermesApp` | `StatusBar.render()` |
| `spinner_label` (existing) | **Modified watcher** | `HermesApp` | `_build_hint_text()`, `watch_spinner_label()` |
| `agent_running` (existing) | **Modified watcher** | `HermesApp` | `StatusBar`, `UndoConfirmOverlay`, `_tick_spinner` |

---

## 10. Capabilities Required

None. This spec makes no changes to tool definitions, profile gating, or agent capabilities.

---

## 11. Test Plan

| Step | Tests | Focus |
|---|---|---|
| Step 1 (placeholder spinner) | 4 | `_tick_spinner` sets `inp.placeholder` to spinner text; overlay stays hidden; no display toggle on inp |
| Step 2 (focus restore) | 2 | `watch_agent_running(False)` clears placeholder; input focused after turn ends |
| Steps 3–5 (file extraction) | 6 | `watch_spinner_label` sets `status_active_file` for `read_file`, `write_file`; clears for unknown tools; handles missing path; handles `view` tool; clears on empty label |
| Steps 6–7 (StatusBar breadcrumb) | 6 | StatusBar renders breadcrumb when `status_active_file` non-empty; omits separator when empty; truncates long paths; skips breadcrumb at `width < 60`; clears when `status_active_file` reset; browse mode unaffected |

**Total new tests: 18**

### Integration scenarios

1. Full turn lifecycle: agent starts → spinner label set → breadcrumb appears → agent ends → breadcrumb clears → focus restored.
2. Tool switch: `spinner_label` changes from `read_file(...)` to `bash(...)` mid-turn → breadcrumb clears immediately.
3. Narrow terminal (width=40): StatusBar renders without breadcrumb, no errors.

---

## 12. Cost Impact

None. No LLM API calls added or modified.

---

## 13. Error Conditions

| Scenario | Handling |
|---|---|
| `#input-area` not found (TextArea fallback path) | `try/except NoMatches` in `_tick_spinner` and `watch_agent_running`; `hasattr(inp, "placeholder")` guard |
| `status_active_file` not on app (edge case during init) | `getattr(app, "status_active_file", "")` with default in `StatusBar.render()` |
| `_PATH_EXTRACT_RE` no match on file-tool label | `status_active_file = ""` (no breadcrumb shown) |
| Path longer than terminal width | Truncated to `"…" + tail` via width-scaled `max_path` formula |
| `spinner_label` set to non-string value | `str.split("(")[0]` will raise — guard with `if value and isinstance(value, str)` |

---

## 14. Determinism Impact

None. This spec makes no changes to agent or tool execution logic.

---

## 15. Backward Compatibility

| Scenario | Behaviour |
|---|---|
| Old `#spinner-overlay` widget still in DOM | Always `display: none`; no visual change |
| `TextArea` fallback input path (non-HermesInput) | `hasattr(inp, "placeholder")` guard skips placeholder update safely |
| Terminals width < 60 | Breadcrumb silently omitted; no layout change |
| Existing `_tick_spinner` tests expecting overlay show/hide | Tests will need updating: overlay always hidden now; placeholder checked instead |

---

## 16. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `HermesInput.placeholder` not rendered correctly when disabled | Low | Medium | Textual Input natively renders placeholder when `value == ""`; confirmed in TextualDocs |
| `_PATH_EXTRACT_RE` false-positive on non-path args | Low | Low | Regex requires either leading `/` or a `.<ext>` suffix; unit-tested |
| StatusBar render perf hit from extra `getattr` | Very low | Very low | One additional `getattr` per repaint; StatusBar already reads 10+ attributes |
| Width-gate threshold (60) too conservative | Low | Very low | Configurable in future; 60 is a safe minimum for most real terminals |
| `watch_spinner_label` fires before `status_active_file` reactive is registered | Low | Low | Reactive declared at class body scope; registered before `on_mount` fires |

---

## 17. Interaction with Other Specs

| Spec | Relationship |
|---|---|
| `tui-animation-novel-techniques` | Depends on (PulseMixin already in StatusBar) |
| `tui-osc52-capability-detection-spec` | Independent; StatusBar already hosts the clipboard-warning widget |
| `tui-streaming-typewriter` | Independent; LiveLineWidget and `_consume_output` unaffected |
| `tui-turn-undo-retry-spec` | Uses `watch_agent_running` — undo-cancel guard in that watcher unchanged |
| `tui-history-search-spec` | Independent |
