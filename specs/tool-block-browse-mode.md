# ToolBlock + Browse Mode

**Status:** Approved
**Priority:** P1
**Depends on:** tool-output-streamline phases 1–3 (implemented)
**Goal:** Replace flat ANSI-printed tool previews with collapsible ToolBlock widgets and add a keyboard-driven browse mode for navigating, expanding, and copying output blocks.

---

## Problem

After Phases 1–3, tool output is clean and quiet — but the preview content (inline diffs, code, terminal output) is still printed as flat ANSI text into the same RichLog as response prose. This creates three friction points:

1. **No retrieval.** A diff that streamed past 20 turns ago is gone. You can scroll up and read it, but you cannot copy it cleanly — clipboard gets gutter chars and ANSI codes.
2. **No proportionality.** A 40-line diff gets the same visual weight as a 1-line read. Large tool outputs dominate the scroll history; small ones disappear.
3. **No navigation.** There is no way to move between tool outputs without scrolling manually. In a long session with many tool calls, finding the specific write that produced a bug requires reading every line.

---

## Goals

1. Tool output body content (diffs, code previews, terminal output) renders in a `ToolBlock` widget that is collapsed by default when >3 lines, always expanded when ≤3 lines.
2. A `ToolBlock` header shows: content type label, line count, expand/collapse toggle (`▸`/`▾`), and copy affordance (`⎘`). No toggle or copy affordance when ≤3 lines (content already visible).
3. Pressing `Escape` from idle input (no overlay, agent not running) enters browse mode; `Escape` or any printable key exits.
4. In browse mode, `Tab`/`Shift+Tab` cycles focus through all `ToolHeader` widgets in the session.
5. Focused `ToolHeader` renders with an accent gutter (`┃` instead of `┊`).
6. `Enter` toggles the focused block's collapsed state.
7. `c` copies the focused block's plain-text content to the system clipboard via Textual's `copy_to_clipboard()` (OSC 52).
8. `⎘` flashes to `✓` for 1.5 s after a copy is initiated, then reverts.
9. `StatusBar` switches to browse-mode layout: `BROWSE ▸{idx}/{total}  Tab · Enter · c copy · Esc exit`.
10. All existing test assertions continue to pass (no regressions).

---

## Non-Goals

- **Phase 5 `ResponseFlow`**: code blocks inside response prose are a separate widget. This spec covers tool output only.
- **Mouse click-to-toggle**: deferred — requires hit-testing in `OutputPanel`.
- **ToolBlock for all tools**: only tools that produce non-empty preview content (diff, code, terminal output) get a `ToolBlock`. Tools with no preview continue using RichLog lines only.
- **Streaming tool output**: Phase 7. This spec covers completed tool output only.
- **`▸ NL` suffix on cute_msg lines**: `_safe_print(cute_msg)` fires in `run_agent.py` before `tool_complete_callback` (confirmed: lines 6382–6397). Retroactively modifying the RichLog entry would require a non-trivial race-free replacement protocol. The ToolBlock is additive below the cute_msg line. See §Design Decisions.
- **Clipboard error feedback**: `copy_to_clipboard()` uses OSC 52 (fire-and-forget). Terminals that don't support it silently ignore it. No `✗` flash — the UX cost of false negatives outweighs the benefit.

---

## Design

### Visual language

**Gutter convention:**

| State | Gutter | Style |
|---|---|---|
| Normal tool line (RichLog) | `┊` | dim |
| ToolBlock header, idle | `┊` | dim |
| ToolBlock header, focused (browse mode) | `┃` | accent (`_skin_color("banner_title", "#FFD700")`) |

**Collapsed ToolBlock** (>3 lines, default):
```
  ┊ ✍️  write     /src/auth.py                     1.1s       ← RichLog (cute_msg, unchanged)
  ┊   ╌╌ diff  7L  ▸  ⎘                                       ← ToolBlock header
```

**Expanded ToolBlock** (focused in browse mode, after Enter):
```
  ┊ ✍️  write     /src/auth.py                     1.1s
  ┃   ╌╌ diff  7L  ▾  ⎘
  ┊   --- a/src/auth.py
  ┊   +++ b/src/auth.py
  ┊   @@ -10,3 +10,5 @@
  ┊     def authenticate(token):
  ┊  -      return db.lookup(token)
  ┊  +      session = db.lookup(token)
  ┊  +      if session and session.is_valid():
  ┊  +          return session
```

**Auto-expanded ToolBlock** (≤3 lines — always open, no toggle or copy icon):
```
  ┊ 🔧 patch     /src/conf.py                      0.3s
  ┊   ╌╌ diff  2L
  ┊  -debug = True
  ┊  +debug = False
```

**Copy flash** (`c` key, focused header):
```
  ┃   ╌╌ diff  7L  ▾  ✓                            ← ✓ for 1.5 s, then revert to ⎘
```

**Browse mode StatusBar** (full width ≥60):
```
BROWSE ▸3/6  Tab · Enter · c copy · Esc exit                            12480 tok  2m34s
```

**Browse mode StatusBar** (width 40–59, compact):
```
BROWSE ▸3/6  Tab · c · Esc                          12480 tok
```

**Browse mode StatusBar** (width <40, minimal):
```
BROWSE ▸3/6                                         2m34s
```

---

### Widget architecture

```
OutputPanel
├── MessagePanel (per turn)
│   ├── TitledRule
│   ├── ReasoningPanel
│   ├── CopyableRichLog          ← cute_msgs + response prose (unchanged)
│   └── ToolBlock (0…N per turn) ← NEW: mounted dynamically via mount_tool_block()
│       ├── ToolHeader           ← "  ╌╌ {label}  {N}L  ▸/▾  ⎘"
│       └── ToolBodyContainer    ← display:none when collapsed
│           └── CopyableRichLog  ← body lines (markup=False, wrap=False)
├── ToolPendingLine              ← Phase 3 (unchanged)
└── LiveLineWidget               ← Phase 1 (unchanged)
```

`ToolBlock` and its children live in `hermes_cli/tui/tool_blocks.py`. `CopyableRichLog` is imported from `hermes_cli.tui.widgets`.

---

### ToolBlock widget (hermes_cli/tui/tool_blocks.py)

```python
from hermes_cli.tui.widgets import CopyableRichLog, _skin_color

COLLAPSE_THRESHOLD = 3  # >N lines → collapsed by default


class ToolHeader(Widget):
    """Single-line header: '  ╌╌ {label}  {N}L  [▸/▾  ⎘]'."""

    DEFAULT_CSS = "ToolHeader { height: 1; }"

    collapsed: reactive[bool] = reactive(True)

    def __init__(self, label: str, line_count: int, **kwargs):
        super().__init__(**kwargs)
        self._label = label
        self._line_count = line_count
        # ≤ threshold: always open, no affordances shown
        self._has_affordances = line_count > COLLAPSE_THRESHOLD
        self._copy_flash = False

    def render(self) -> RenderResult:
        focused = self.has_class("focused")
        if focused:
            gutter = Text("  ┃", style=f"bold {_skin_color('banner_title', '#FFD700')}")
        else:
            gutter = Text("  ┊", style="dim")
        t = Text()
        t.append_text(gutter)
        t.append(f"   ╌╌ {self._label}  {self._line_count}L", style="dim")
        if self._has_affordances:
            toggle = "  ▾" if not self.collapsed else "  ▸"
            icon   = "  ✓" if self._copy_flash else "  ⎘"
            t.append(toggle, style="dim")
            t.append(icon,   style="dim")
        return t

    def flash_copy(self) -> None:
        """Flash ⎘ → ✓ for 1.5 s, then revert."""
        self._copy_flash = True
        self.refresh()
        self.set_timer(1.5, self._end_flash)

    def _end_flash(self) -> None:
        self._copy_flash = False
        self.refresh()


class ToolBodyContainer(Widget):
    DEFAULT_CSS = """
    ToolBodyContainer { height: auto; display: none; }
    ToolBodyContainer.expanded { display: block; }
    """

    def compose(self) -> ComposeResult:
        # No explicit ID — query by type inside ToolBodyContainer
        yield CopyableRichLog(markup=False, highlight=False, wrap=False)


class ToolBlock(Widget):
    DEFAULT_CSS = "ToolBlock { height: auto; }"

    def __init__(
        self,
        label: str,
        lines: list[str],        # ANSI display lines
        plain_lines: list[str],  # plain text for copy (no ANSI, no gutter)
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._label = label
        self._lines = lines
        self._plain_lines = plain_lines
        auto_expand = len(lines) <= COLLAPSE_THRESHOLD
        self._header = ToolHeader(label, len(lines))
        self._body   = ToolBodyContainer()
        if auto_expand:
            self._header.collapsed = False
            # _has_affordances is already False when line_count ≤ threshold

    def compose(self) -> ComposeResult:
        yield self._header
        yield self._body

    def on_mount(self) -> None:
        log = self._body.query_one(CopyableRichLog)
        for line in self._lines:
            log.write(Text.from_ansi(line))
        if not self._header.collapsed:
            self._body.add_class("expanded")

    def toggle(self) -> None:
        """Toggle collapsed ↔ expanded. No-op for ≤3-line blocks."""
        if not self._header._has_affordances:
            return
        self._header.collapsed = not self._header.collapsed
        if self._header.collapsed:
            self._body.remove_class("expanded")
        else:
            self._body.add_class("expanded")
        self._header.refresh()

    def copy_content(self) -> str:
        """Plain-text content for clipboard — no ANSI, no gutter, no line numbers."""
        return "\n".join(self._plain_lines)
```

---

### Browse mode

**State on HermesApp:**

```python
browse_mode:  reactive[bool] = reactive(False)
browse_index: reactive[int]  = reactive(0)
```

`browse_index` is a flat 0-based index into `list(self.query(ToolHeader))`, which returns all headers in DOM insertion order (session chronological order). Total block count is computed on demand in `StatusBar.render()` via `len(list(app.query(ToolHeader)))`.

**Entering/exiting:**

| Trigger | Action |
|---|---|
| `Escape` from idle input (no overlay, agent not running, `browse_mode=False`) | Enter browse mode; `browse_index` stays at its last value (or 0 on first entry) |
| `Escape` in browse mode | Exit browse mode; clear all `.focused` classes on ToolHeaders |
| Any printable key (`event.character is not None`) in browse mode | Exit browse mode; call `input.insert_text(event.character)` |

**Key handling in browse mode** (added to `HermesApp.on_key()`):

| Key | Action |
|---|---|
| `tab` | `browse_index = (browse_index + 1) % max(1, total)` |
| `shift+tab` | `browse_index = (browse_index - 1) % max(1, total)` |
| `enter` | `headers[browse_index].parent.toggle()` |
| `c` | Copy via `self.copy_to_clipboard(headers[browse_index].parent.copy_content())`; call `headers[browse_index].flash_copy()` |
| `escape` | `self.browse_mode = False` |
| Printable (`event.character is not None`) | `self.browse_mode = False`; `input.insert_text(event.character)` |

**`_apply_browse_focus()` method** — called from `watch_browse_mode` and `watch_browse_index`:

```python
def _apply_browse_focus(self) -> None:
    headers = list(self.query(ToolHeader))
    for i, h in enumerate(headers):
        if self.browse_mode and i == self.browse_index:
            h.add_class("focused")
        else:
            h.remove_class("focused")
```

**`mount_tool_block()` on HermesApp** (called via `call_from_thread`):

```python
def mount_tool_block(
    self,
    label: str,
    lines: list[str],
    plain_lines: list[str],
) -> None:
    """Mount a ToolBlock into the current MessagePanel. Event-loop only."""
    from hermes_cli.tui.tool_blocks import ToolBlock as _ToolBlock
    if not lines:
        return
    panel = self.query_one(OutputPanel).current_message
    if panel is None:
        panel = self.query_one(OutputPanel).new_message()
    panel.mount(_ToolBlock(label, lines, plain_lines))
```

---

### Call path from `_on_tool_complete` (cli.py)

`_on_tool_complete` currently calls render functions that `_cprint` each preview line. The change: collect display lines and plain lines into lists, then call `mount_tool_block` when TUI is active, or fall back to `_cprint` per line (PT mode).

**Plain line extraction:**
- Strip ANSI codes (via `_strip_ansi()` from `hermes_cli/tui/widgets.py` — already imported in `cli.py` context)
- Strip the leading `"  ┊ "` prefix (6 chars) from each display line before storing as plain text

**Label mapping:**

| function_name | label | Condition |
|---|---|---|
| `patch`, `write_file` | `"diff"` | When `render_edit_diff_with_delta` returns True |
| `execute_code` | `"code"` | When verbose mode + code highlight enabled + result succeeded |
| `read_file` | `"code"` | When verbose mode + code highlight enabled |
| `terminal` | `"output"` | When verbose mode + code highlight enabled |

**ToolBlock is only mounted when the renderer produces non-empty lines.** If the renderer returns no lines (unknown extension, empty result, non-verbose mode), no ToolBlock is mounted — the existing fallback to `_cprint` is also skipped since the renderer already returned False/no output.

**Render function refactor pattern:**

```python
# Current (PT mode path unchanged):
render_edit_diff_with_delta(..., print_fn=_cprint, prefix=_TOOL_PREFIX)

# New (TUI path — collect, then mount):
tui = _hermes_app
if tui is not None:
    from hermes_cli.tui.widgets import _strip_ansi
    display_lines: list[str] = []
    render_edit_diff_with_delta(..., print_fn=display_lines.append, prefix="  ┊ ")
    if display_lines:
        # Include all lines in body (header "┊ review diff" provides context).
        plain = [_strip_ansi(l).removeprefix("  ┊ ").removeprefix("  ┊   ") for l in display_lines]
        tui.call_from_thread(tui.mount_tool_block, "diff", display_lines, plain)
else:
    render_edit_diff_with_delta(..., print_fn=_cprint, prefix=_TOOL_PREFIX)
```

---

### StatusBar browse layout

`StatusBar` adds `browse_mode` and `browse_index` to its reactive watch list in `on_mount()`. In `render()`:

```python
browse      = getattr(app, "browse_mode", False)
browse_idx  = getattr(app, "browse_index", 0)
browse_total = len(list(app.query(ToolHeader))) if browse else 0

if browse:
    left = Text(f"BROWSE ▸{browse_idx + 1}/{browse_total}", style="bold")
    if width >= 60:
        left.append("  Tab · Enter · c copy · Esc exit", style="dim")
    elif width >= 40:
        left.append("  Tab · c · Esc", style="dim")
    # right: tokens · duration (right-anchored, same as normal layout)
    ...
    return left + padding + right
```

`app.query(ToolHeader)` is safe in `render()` — it runs on the event loop. The count auto-updates whenever `browse_index` changes (Tab), which triggers a StatusBar repaint.

---

### CSS (hermes.tcss additions)

```css
/* ToolHeader — visual only (structural height: 1 is in DEFAULT_CSS) */
ToolHeader {
    margin-left: 0;
}

/* ToolBodyContainer body lines — indent matches the ┊ gutter */
ToolBodyContainer CopyableRichLog {
    padding-left: 0;
    height: auto;
    max-height: 40;        /* cap extremely long tool outputs */
    overflow-y: auto;
    overflow-x: hidden;
}

/* No extra CSS needed for ToolHeader.focused — accent is rendered inline */
```

---

## Design Decisions

**Body-only ToolBlock (not header-replacement)**

`_safe_print(cute_msg)` fires at `run_agent.py:6382`, before `tool_complete_callback` at line 6397. Suppressing it would require either inverting the order (risky for 40+ tool paths) or an async flag mechanism between two different objects. Body-only is additive and zero-risk. The `╌╌ diff  7L` line visually connects to the cute_msg above it.

**Flat browse_index (not tuple)**

`browse_index: int` + `query(ToolHeader)` gives DOM-ordered traversal across all MessagePanels without needing a per-message registry. Textual guarantees `query()` returns nodes in document order.

**Custom focus classes (not Textual's built-in focus)**

`ToolHeader` is a leaf render widget, not an interactive control. `can_focus=True` on a static widget causes unexpected scroll-jump. A CSS class (`focused`) + custom key handling is deterministic and testable.

**`copy_to_clipboard()` (Textual built-in, not pyperclip)**

`HermesApp` inherits `copy_to_clipboard(text: str)` from Textual's `App`. It uses the OSC 52 escape sequence, supported by most modern terminals. No new dependency. OSC 52 is fire-and-forget — no error callback, no `✗` flash.

**No ID on `CopyableRichLog` inside `ToolBodyContainer`**

Multiple `ToolBlock` instances per `MessagePanel` would produce duplicate IDs. Use `self._body.query_one(CopyableRichLog)` (type query within the container) — unambiguous since there is exactly one.

**`_browse_total` computed in `StatusBar.render()`, not a reactive**

A separate `browse_total: reactive[int]` would require incrementing it in `mount_tool_block()` and decrementing on block removal — error-prone. Computing `len(list(app.query(ToolHeader)))` live in `render()` is always accurate. It re-runs whenever `browse_index` changes (Tab), which is the only time the count matters.

**`_strip_ansi` for plain line extraction**

`_strip_ansi` is already defined in `hermes_cli/tui/widgets.py` and used by `flush_live()`. Import it in `cli.py` via `from hermes_cli.tui.widgets import _strip_ansi` (guarded by `if tui is not None` so it doesn't import the TUI in PT mode).

---

## Configuration

No new configuration. ToolBlocks are always active when the TUI is running. Browse mode is always available via `Escape`. No profile YAML changes needed.

---

## Files Changed

### New files

| File | Purpose |
|---|---|
| `hermes_cli/tui/tool_blocks.py` | `ToolBlock`, `ToolHeader`, `ToolBodyContainer` widget definitions |
| `tests/tui/test_tool_blocks.py` | ToolBlock + browse mode tests |

### Modified files

| File | Changes |
|---|---|
| `hermes_cli/tui/app.py` | Add `browse_mode`, `browse_index` reactives; add `mount_tool_block()`, `_apply_browse_focus()`; update `on_key()` for browse bindings and idle-escape entry; add `watch_browse_mode()`, `watch_browse_index()`; update StatusBar watch list; update `StatusBar.render()` for browse layout |
| `hermes_cli/tui/hermes.tcss` | `ToolHeader`, `ToolBodyContainer CopyableRichLog` CSS rules |
| `cli.py` | Refactor `_on_tool_complete()`: collect display/plain lines, call `mount_tool_block()` via `call_from_thread` when TUI active; import `_strip_ansi` guarded by TUI check |

---

## Implementation Plan

**Step 1 — `tool_blocks.py`: core widgets**
Define `ToolHeader`, `ToolBodyContainer`, `ToolBlock` in `hermes_cli/tui/tool_blocks.py` per §Design. Tests: auto-expand ≤3L (no toggle affordance), collapse >3L default, `toggle()` adds/removes `expanded` class on body, `copy_content()` returns plain text.

**Step 2 — CSS in hermes.tcss**
Add `ToolBodyContainer CopyableRichLog` rule. No test — visual only; mount tests in Step 3 verify no layout crash.

**Step 3 — `mount_tool_block()` on HermesApp**
Add `mount_tool_block(label, lines, plain_lines)` to `app.py`. Guard: returns early on empty `lines`. Tests: `ToolBlock` appears in DOM with correct label; empty lines produces no mount.

**Step 4 — `_on_tool_complete` refactor in cli.py**
Wrap render calls in TUI-active branch: collect to list, then `call_from_thread(mount_tool_block, ...)`. PT-mode branch unchanged. Import `_strip_ansi` guarded. Tests: `mount_tool_block` called with correct label + line count for a patch diff; PT mode still calls `_cprint`.

**Step 5 — browse mode reactives + `_apply_browse_focus`**
Add `browse_mode`, `browse_index` to `HermesApp`. Add `watch_browse_mode()` (calls `_apply_browse_focus`; on enter: if no headers, `browse_mode` stays False) and `watch_browse_index()` (calls `_apply_browse_focus`). Add `_apply_browse_focus()`. Tests: entering browse mode sets `.focused` on index-0 header; changing `browse_index` moves `.focused`.

**Step 6 — `on_key()` browse bindings**
Add idle-escape → browse entry in the existing escape block (after overlay cancel + agent interrupt checks). Add browse-mode branch: Tab, Shift+Tab, Enter, `c`, Escape, printable key. Printable key uses `event.character`; insert via `self.query_one(HermesInput).insert_text(event.character)` guarded by `try/except NoMatches`. Tests: Tab cycles (wraps); Shift+Tab cycles back; Enter calls `toggle()`; `c` calls `copy_to_clipboard` + `flash_copy()`; Escape exits; printable key exits and inserts.

**Step 7 — StatusBar browse layout**
Add `browse_mode` and `browse_index` to `StatusBar.on_mount()` watch list (joining existing 8 attributes). Add browse-mode branch in `StatusBar.render()` per §Design. Tests: browse layout at <40 / 40–59 / ≥60; `browse_mode=False` → normal layout.

**Step 8 — Integration**
Mount 3 ToolBlocks via `mount_tool_block()`, enter browse mode, Tab through all 3, verify `browse_index` cycles, `.focused` moves, Enter expands a block, `c` triggers `flash_copy()` on focused header.

---

## State Changes

| Field | Type | Where | Read by |
|---|---|---|---|
| `browse_mode` | `reactive[bool]` | `HermesApp` | `on_key()`, `watch_browse_mode()`, `StatusBar.render()` |
| `browse_index` | `reactive[int]` | `HermesApp` | `on_key()`, `watch_browse_index()`, `StatusBar.render()` |
| StatusBar watch list | — | `StatusBar.on_mount()` | Adds `browse_mode`, `browse_index` to existing 8-item list |

---

## Capabilities Required

None. Browse mode and ToolBlocks are purely display-layer features.

---

## Cost Impact

Zero. No additional API calls. No token overhead.

---

## Error Conditions

| Scenario | Handling |
|---|---|
| `mount_tool_block()` called with empty `lines` | Early return — no `ToolBlock` mounted |
| `Escape` pressed with no `ToolHeader`s in DOM | `watch_browse_mode` detects empty header list and resets `browse_mode` to `False` immediately — browse mode is never entered; no StatusBar switch |
| Printable key exit: `query_one(HermesInput)` raises `NoMatches` | `browse_mode = False`; swallow `NoMatches`; character not inserted (rare teardown edge case) |
| `ToolBodyContainer` body log `write()` fails | Wrap `on_mount` loop in try/except; ToolBlock still mounts with empty body |
| `set_timer()` fires after widget dismounted | Auto-cancelled by Textual — no action needed |
| `_on_tool_complete` called when TUI not active (PT mode) | `_hermes_app is None` guard; falls back to existing `_cprint` path |
| `render_edit_diff_with_delta` returns no lines | `display_lines` is empty; `mount_tool_block` is not called; no output (renderer already returned False) |

---

## Determinism Impact

None. ToolBlocks are display-only and do not affect agent behavior, tool execution, or response generation.

---

## Backward Compatibility

- **PT mode**: `_on_tool_complete` falls back to `_cprint` for each preview line — identical to current behavior.
- **`tool_progress_mode: "off"`**: Early return in `_on_tool_complete` before the collect/mount logic — no change.
- No profile YAML changes. No migration steps.

---

## Test Plan

| Step | Tests | Focus |
|---|---|---|
| 1 — ToolBlock widgets | 4 | Auto-expand ≤3L (no affordances), collapse >3L, `toggle()` adds/removes `expanded` class, `copy_content()` returns plain text without gutter or ANSI |
| 2 — CSS | 0 | Visual only; mount tests in Step 3 provide smoke coverage |
| 3 — mount_tool_block | 2 | ToolBlock in DOM with correct label; empty lines → no mount |
| 4 — cli refactor | 2 | `mount_tool_block` called for diff content; PT mode calls `_cprint` |
| 5 — browse reactives | 2 | Enter browse: `.focused` on index-0; `browse_index` change moves `.focused` |
| 6 — browse keybindings | 6 | Tab wraps; Shift+Tab back; Enter calls `toggle()`; `c` calls `copy_to_clipboard` + `flash_copy()`; Escape exits; printable exits + inserts |
| 7 — StatusBar browse | 3 | <40 / 40–59 / ≥60 layouts; `browse_mode=False` → normal layout |
| 8 — Integration | 2 | 3 blocks → Tab cycles → Enter expands → `c` flashes; `browse_mode=False` clears all `.focused` |
| **Total** | **21** | |

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `ToolBlock height: auto` doesn't expand correctly | Medium | High | `ToolBodyContainer` uses `height: auto` (same as `MessagePanel RichLog`); `max-height: 40` cap in CSS; verified in Step 3 mount test |
| Browse `Escape` conflicts with overlay cancel | Low | High | Overlay cancel runs first in `on_key()` priority chain (existing behavior); idle-escape check is last in the escape block |
| Browse `Escape` conflicts with agent interrupt | Low | High | Agent interrupt check runs before browse entry; browse entry only triggers when `not agent_running` |
| `query(ToolHeader)` order unstable across mounts | Low | Medium | Textual guarantees DOM order for `query()`; integration test verifies Tab cycle order |
| `ToolHeader.render()` calls `_skin_color()` on every repaint | Low | Low | `_skin_color` is a lightweight dict lookup — already used in every `TitledRule.render()` |
| Printable key inserts wrong char | Low | Medium | `event.character` is None for non-printable keys; guard: `if event.character is not None` |
| `app.query(ToolHeader)` in `StatusBar.render()` slow on long sessions | Low | Low | Textual's query is O(n) over DOM nodes; sessions with >1000 ToolBlocks are pathological. Acceptable. |
