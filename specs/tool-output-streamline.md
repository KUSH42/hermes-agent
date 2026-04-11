# Tool Output Streamline

**Status:** Approved
**Priority:** P1
**Depends on:** None (builds on existing TUI infrastructure)
**Goal:** Redesign tool output rendering in the TUI to respect indentation, reduce noise, add collapsible blocks with copy affordances, and stream long-running tool output incrementally.

---

## Problem statement

Tool output in the current TUI has three issues:

1. **No structural indentation.** Tool result lines (cute messages, diffs, code previews) are printed as flat ANSI text via `_cprint()` → `LiveLineWidget.append()`. Multiline output loses its visual hierarchy — every line starts at column 0 regardless of nesting depth. A 40-line diff looks identical to a 40-line prose response.

2. **Noise lines that add no information.** The `preparing {tool_name}…` line (`cli.py:6290`) fires when the model *begins generating* tool-call arguments — before the tool runs. For fast tools (<200 ms) the user sees "preparing read_file…" immediately replaced by the cute completion line. For concurrent tool batches, N preparing lines stack up, then N completion lines stack up, doubling the visual footprint with zero information gain. Other low-value lines: empty-result tool completions, redundant `tool.started` spinner updates that echo the preparing line.

3. **Flat visual weight.** All tool lines use the same `┊` gutter prefix, same indentation level, same dim styling. There is no distinction between a trivial read (0.1 s) and a multi-second terminal command with rich output. Inline diffs and code previews blend into the surrounding cute message stream. The user must *read* every line to find the one that matters.

---

## Design principles

- **Indented tool blocks.** Tool output belongs to a visually nested context — the agent is *doing work*, not *speaking*. Indent tool lines under the response, using the gutter prefix as the visual anchor.
- **One line per tool, always.** Merge the preparing→completion lifecycle into a single line that updates in-place. No stacking.
- **Hierarchy through weight.** Use color, boldness, and detail level to signal importance: write/patch/terminal get full treatment; read/search get a minimal one-liner; internal tools (todo, memory, session_search) collapse entirely unless they fail.
- **Respect multiline output.** Inline diffs, code previews, and terminal output must carry the gutter prefix on every line, preserving the indented block feel.

---

## Current architecture (reference)

### Output pipeline

```
Agent thread → _vprint() / _cprint()
  → app._output_queue (bounded asyncio.Queue, 4096 chunks)
    → _consume_output() async worker
      → LiveLineWidget.append(chunk)
        → split on \n → RichLog.write(Text.from_ansi(line))
```

### Tool lifecycle events (in order)

| Event | Source | Current display |
|---|---|---|
| `tool_gen_started` | Model begins streaming tool-call JSON | `_on_tool_gen_start()` prints `┊ {emoji} preparing {tool_name}…` |
| `tool.started` | Tool execution begins | `_on_tool_progress()` updates spinner label only |
| Tool result ready | `_invoke_tool()` returns | `_vprint(cute_msg)` prints completion one-liner |
| `tool_complete` | After result collected | `_on_tool_complete()` renders inline diff / code preview |

### Key files

| File | Role |
|---|---|
| `cli.py:6276–6383` | `_on_tool_gen_start`, `_on_tool_progress`, `_on_tool_start`, `_on_tool_complete` |
| `agent/display.py:1104–1260` | `get_cute_tool_message()` — 40+ tool-specific formatters |
| `run_agent.py:6442–6610` | `_execute_tool_calls_sequential()` — `_vprint(cute_msg)` calls |
| `hermes_cli/tui/widgets.py:100–141` | `LiveLineWidget` — line buffer + RichLog commit |
| `hermes_cli/tui/app.py:182–210` | `_consume_output()` — async queue consumer |

---

## Design

### 1. Unified tool activity line (replace preparing + completion)

**Current:** Two separate prints per tool call:
```
  ┊ ⚡ preparing read_file…
  ┊ 📖 read      /src/main.py  0.3s
```

**New:** A single activity line that updates in-place:
```
  ┊ 📖 read      /src/main.py                          0.3s
```

The line appears when `tool_gen_started` fires (showing tool name + spinner dots) and is **replaced** with the final cute message when the tool completes. "Replaced" means: the last line written to the RichLog is overwritten, not appended below.

**Mechanism:**
- Add a `ToolPendingLine` widget (extends `Static`) to the `MessagePanel`, positioned above the `LiveLineWidget` (Phase 3). After Phase 5 replaces `LiveLineWidget` with `ResponseFlow`, `ToolPendingLine` is repositioned above the `ResponseFlow` container — its API (`set_line`, `remove_line`) is unchanged. This widget renders the in-progress tool line and can be freely updated without touching the RichLog.
- `_on_tool_gen_start()` writes the "in-progress" line to the pending slot via `app.call_from_thread(_safe_widget_call, app, ToolPendingLine, "set_line", tool_id, in_progress_text)`.
- `_vprint(cute_msg)` in `_execute_tool_calls_sequential()` commits the final line to the RichLog and clears the pending slot.
- **Concurrent tool batches:** `ToolPendingLine` manages a `dict[str, Text]` of pending lines keyed by tool call ID. All pending lines are rendered vertically (one per tool, in batch-start order). As each tool completes, its entry is removed from the dict and the final cute message is committed to the RichLog. When the dict is empty, the widget auto-hides.

```python
class ToolPendingLine(Widget):
    DEFAULT_CSS = "ToolPendingLine { height: auto; display: none; }"

    def __init__(self) -> None:
        super().__init__()
        self._lines: dict[str, Text] = {}  # tool_call_id → styled text
        self._order: list[str] = []        # insertion order

    def set_line(self, tool_id: str, styled: Text) -> None:
        if tool_id not in self._lines:
            self._order.append(tool_id)
        self._lines[tool_id] = styled
        self.display = True
        self.refresh()

    def remove_line(self, tool_id: str) -> None:
        self._lines.pop(tool_id, None)
        if tool_id in self._order:
            self._order.remove(tool_id)
        if not self._lines:
            self.display = False
        self.refresh()

    def render(self) -> RenderResult:
        combined = Text()
        for i, tid in enumerate(self._order):
            if i > 0:
                combined.append("\n")
            combined.append_text(self._lines[tid])
        return combined
```

**Fallback:** If the pending line mechanism proves fragile across Textual versions, accept a simpler approach: suppress the preparing line entirely and only print the completion line. The spinner label already shows tool activity during execution, so zero preparing lines is better UX than two stacked lines.

### 2. Indented multiline tool output blocks

**Current:** Inline diffs and code previews are printed as flat lines:
```
  ┊ ✍️  write     /src/main.py  1.2s
--- a/src/main.py
+++ b/src/main.py
@@ -10,3 +10,5 @@
   def hello():
-      print("hello")
+      print("hello world")
+      return True
```

**New:** Every line within a tool output block carries the gutter prefix:
```
  ┊ ✍️  write     /src/main.py                          1.2s
  ┊   --- a/src/main.py
  ┊   +++ b/src/main.py
  ┊   @@ -10,3 +10,5 @@
  ┊     def hello():
  ┊  -      print("hello")
  ┊  +      print("hello world")
  ┊  +      return True
```

**Mechanism:**
- Modify `render_edit_diff_with_delta()` and friends to accept a `prefix: str` kwarg and prepend it to every line they emit. This moves indentation to the source instead of the consumer.
- In `_on_tool_complete()` (cli.py:6342), pass `prefix="  ┊ "` to all preview renderers.
- This is simpler and more robust than sentinel markers. Sentinels that use ANSI-escape-like encoding (`\x1b[...]`) would be consumed or corrupted by `Text.from_ansi()` in `LiveLineWidget.append()` (widgets.py:130) — the Rich parser treats any `\x1b[` as a CSI sequence. The prefix approach avoids the output pipeline entirely.

**Gutter styling in blocks:**
- Gutter prefix: `  ┊ ` (2 spaces + `┊` + 1 space) — dim, matching the cute message line's left edge.
- Content within the block keeps its own syntax coloring (diff +/- colors, syntax highlights).
- No wrapping of the gutter — if the terminal is narrow, the content wraps but the gutter stays on the first visual line only.

### 3. Tool output tier system

Not all tool outputs deserve equal screen real estate. Classify tools into three tiers:

| Tier | Tools | Display |
|---|---|---|
| **Verbose** | `write_file`, `patch`, `terminal`, `execute_code`, `browser_*` | Full cute message + inline diff / code preview / terminal output (indented block) |
| **Compact** | `read_file`, `search_files`, `web_search`, `web_extract` | Cute message one-liner only. No inline preview unless `tool_progress_mode == "verbose"`. |
| **Silent** | `todo`, `memory`, `session_search`, `clarify`, `skills_list`, `skill_view` | No output line at all. Spinner label shows activity. Exception: if the tool *fails*, promote to Compact tier and show a failure one-liner. |

**Current state:** All tools print a cute message. `todo`, `session_search`, `memory` always print via `_vprint()` in `_execute_tool_calls_sequential()` (run_agent.py:6538–6576).

**Change:**
- Add a `_tool_display_tier(tool_name: str) -> str` function in `agent/display.py` returning `"verbose"`, `"compact"`, or `"silent"`.
- The function uses a hardcoded mapping for known tools (the table above) with a **default tier of `"compact"`** for any unrecognized tool name. This covers dynamically registered tools (MCP tools, skill-provided tools, user-installed tools) — they get a cute message one-liner by default. Tools can be reclassified via a `tool_display_tiers` config dictionary in the profile YAML (see §Configuration).
- In `_execute_tool_calls_sequential()` and `_execute_tool_calls_concurrent()`, check the tier before calling `_vprint(cute_msg)`:
  - `"silent"`: skip `_vprint` unless `is_failure` is True.
  - `"compact"`: call `_vprint(cute_msg)` but skip inline previews.
  - `"verbose"`: existing behavior (cute message + preview blocks).
- The tier system respects `tool_progress_mode`: when mode is `"verbose"`, promote Compact→Verbose. When mode is `"off"`, demote everything to Silent.

### 4. Concurrent batch rendering

When multiple tools execute concurrently, current output interleaves preparing + completion lines in arrival order. This is chaotic.

**New behavior:**
- At batch start, reserve N placeholder lines (one per tool in the batch).
- As each tool completes, replace its placeholder with the final cute message.
- After all tools complete, render verbose-tier output blocks sequentially below.

**Visual example (3 concurrent tools):**
```
  ┊ 📖 read      /src/auth.py                          0.2s
  ┊ 📖 read      /src/db.py                            0.3s
  ┊ 🔎 grep      "session_id"                          0.4s
```

All three lines appear in their original order regardless of which completes first. During execution, incomplete tools show an animated ellipsis or spinner char that is replaced on completion.

**Implementation note:** This requires the "replaceable line" mechanism from §1. If that proves too complex for Textual's RichLog, fall back to: suppress all output during concurrent execution, then print all cute messages in batch order after completion.

### 5. Consistent gutter alignment

All tool-related output must align to a shared left margin:

```
Column:  0123456
         ··┊·...content...
```

- Columns 0–1: two spaces (indent from response text).
- Column 2: `┊` gutter char (skin-configurable).
- Column 3: space separator.
- Column 4+: content (emoji, verb, detail, duration).

This alignment is already present in `get_cute_tool_message()` but breaks in:
- `_on_tool_gen_start()` — uses `f"  ┊ {emoji} preparing {tool_name}…"` (correct prefix but ad-hoc).
- `render_edit_diff_with_delta()` — prints with no prefix.
- `render_read_file_preview()` / `render_terminal_preview()` — prints with no prefix.

**Fix:** All tool output functions must accept and use a `prefix: str = "  ┊ "` parameter. The prefix is applied to every emitted line.

### 6. Duration alignment

**Current:** Duration is appended with variable spacing:
```
  ┊ 📖 read      /src/main.py  0.3s
  ┊ 🔎 grep      "pattern"  0.1s
  ┊ 💻 $         npm install  12.4s
```

**New:** Right-align duration to a fixed column (e.g., terminal width - 2, or a fixed column like 60):
```
  ┊ 📖 read      /src/main.py                          0.3s
  ┊ 🔎 grep      "pattern"                             0.1s
  ┊ 💻 $         npm install                          12.4s
```

**Mechanism:** In `get_cute_tool_message()`, calculate padding between the detail string and the duration string to reach a target column. Use a `_tool_line_width` that defaults to 64 chars. In TUI mode, `get_cute_tool_message()` accepts an optional `width: int` parameter; the TUI passes the current widget width (available via `self.size.width` after mount). Do **not** use `shutil.get_terminal_size()` inside Textual — it returns the outer terminal size, not the widget's content area width. In non-TUI (PT) mode, `shutil.get_terminal_size()` is appropriate. Pad with spaces. If the detail overflows, fall back to 2-space separation (current behavior).

**Display width:** Emoji characters (📖, ✍️, 🔎, 💻) occupy 2 terminal cells each. Use `wcswidth()` from the `wcwidth` package (or `unicodedata.east_asian_width()`) when calculating padding, not `len()`. The existing `_trunc()` and `_path()` helpers in `get_cute_tool_message()` (display.py:1118-1128) already use `len()` — these must be updated to use display width.

### 7. Collapsible tool output blocks

Tool output blocks (diffs, code previews, terminal output) should be **collapsed by default** and expandable on demand. The collapsed state shows a single summary line; the expanded state reveals the full indented block. This is the single most impactful UX improvement for long agent sessions — it converts an 80-line scroll buffer of diffs into a scannable 8-line summary where each tool is one line, and the user drills into exactly the one they care about.

#### 7.1 Interaction model

**Collapsed state (default for completed tools):**
```
  ┊ ✍️  write     /src/auth.py                          1.2s  ▸ 7 lines
```

The `▸ 7 lines` suffix is a disclosure indicator — it communicates that content exists behind this line. The `▸` chevron points right (collapsed). The line count tells the user whether it's worth expanding.

**Expanded state (user pressed Enter/click on the line):**
```
  ┊ ✍️  write     /src/auth.py                          1.2s  ▾
  ┊   --- a/src/auth.py
  ┊   +++ b/src/auth.py
  ┊   @@ -10,3 +10,5 @@
  ┊     def authenticate(token):
  ┊  -      return db.lookup(token)
  ┊  +      session = db.lookup(token)
  ┊  +      if session and session.is_valid():
  ┊  +          return session
```

The `▾` chevron points down (expanded). Content appears below with gutter indentation per §2.

**Toggle:** Pressing Enter or clicking on any collapsed tool line toggles it. Pressing Enter again collapses it back. The toggle is instantaneous — no animation. Focus stays on the toggled line so the user can rapid-fire through multiple blocks.

**Keyboard navigation:**
- `Escape` from input area enters **browse mode** — focus moves to the output panel. The StatusBar reflects this (see §7.6).
- `Tab` / `Shift+Tab` — cycle focus between all focusable blocks (tool blocks, code blocks, omission markers) within the output panel.
- `Enter` — toggle the focused block (expand/collapse).
- `c` — **c**opy the focused block's content to clipboard (plain text, no ANSI, no gutter chars). See §10.
- `a` — expand **a**ll collapsible blocks in the current turn. `A` (shift) — collapse all.
- `Escape` again (or any printable key) — returns focus to the input area.
- These bindings are only active in browse mode. They do not conflict with the input area.

**Mouse:** Click anywhere on the collapsed line to toggle. Click the copy affordance `⎘` (see §10) to copy. No hover highlight — the gutter `┊` already provides the visual anchor.

#### 7.2 Collapse semantics by tier

| Tier | Collapse behavior |
|---|---|
| **Verbose** (write, patch, terminal, execute_code, browser_*) | Collapsed by default when output > 3 lines. Auto-expanded while streaming (see §8). Collapses when next tool starts or response text resumes. |
| **Compact** (read, search, web_*) | No output block — one-liner only. Nothing to collapse. |
| **Silent** (todo, memory, session_search) | No output at all. Nothing to collapse. |

A tool that produces ≤ 3 lines of output is **not collapsible** — the overhead of a toggle interaction exceeds the space saved. The output renders inline, directly below the cute message, with no chevron.

#### 7.3 Widget architecture: `ToolBlock`

A new composite widget that replaces the current "cute message line + flat preview lines" pattern:

```
ToolBlock (Widget)
  ├── ToolHeader (Static, can_focus=True) ← cute message + chevron + line count
  └── ToolBodyContainer (Vertical)        ← hidden/shown by collapse state
        ├── ToolBodySegment (CopyableRichLog)  ← diff/preview lines (gutter-prefixed)
        ├── OmissionBlock (Widget, optional)   ← expandable omission marker
        └── ToolBodySegment (CopyableRichLog)  ← lines after omission (optional)
```

For tool blocks without omissions (the common case), `ToolBodyContainer` holds a single `ToolBodySegment`.

**`ToolBlock` extends `Widget`:**
- `collapsed: reactive[bool] = reactive(True)` — drives CSS class `.-collapsed` which sets `ToolBodyContainer { display: none; }`.
- `line_count: int` — total lines across all segments, shown in the header suffix.
- `toggle()` — flips `collapsed`, posts `ToolBlock.Toggled` message.
- `on_click` / `on_key(Enter)` on ToolHeader — calls `toggle()`.

**`ToolHeader` extends `Static` with `can_focus = True`:**
- Renders the cute message text + collapse indicator via `render()` → `Text` object (not plain string — see widget development rules).
- Render logic builds a `Text` with gutter char styled based on focus state (dim `┊` normally, accent `┃` when focused — see §7.6), followed by cute message, chevron, and line count.
- Focus ring: the gutter char change from `┊` to `┃` is the focus indicator. No underline or border needed.

**`ToolBodySegment` extends `CopyableRichLog`:**
- `markup=False, highlight=False, wrap=True` — same config as response log.
- Receives gutter-prefixed lines from the preview renderer.
- `height: auto` — grows with content, no scrollbar within the segment (the outer `OutputPanel` scrolls).

**`ToolBodyContainer` extends `Vertical`:**
- `height: auto` — grows with children.
- Hidden via `display: none` when parent `ToolBlock` has `.-collapsed` class.

**Why not Textual's built-in `Collapsible`?**
Textual's `Collapsible` widget uses borders, padding, background colors, and a `CollapsibleTitle` with `▶`/`▼` symbols. It's designed for settings panels and form groups — not for inline tool output in a streaming conversation. Its default chrome (border, padding, surface background) conflicts with the gutter design language. Building `ToolBlock` from primitives (`Widget` + `Static` + `CopyableRichLog`) gives us:
- Zero chrome — just the gutter prefix and a chevron character.
- Streaming support — `ToolBodySegment` is a RichLog that accepts `write()` during execution.
- Focus model — only the header is focusable, not the entire block.
- No nesting ambiguity — `Collapsible` inside `ScrollableContainer` has known height-calculation edge cases in Textual ≤ 1.x.

#### 7.4 Mounting into the output pipeline

**Current flow:**
```
_cprint(cute_msg)     → LiveLineWidget → RichLog.write()
_cprint(diff_line_1)  → LiveLineWidget → RichLog.write()
_cprint(diff_line_2)  → LiveLineWidget → RichLog.write()
```

**New flow:** Use a direct method call instead of inline sentinels. Sentinels encoded as `\x1b[...]` would be consumed or corrupted by `Text.from_ansi()` in `LiveLineWidget.append()` (widgets.py:130). Instead:

```python
# In _on_tool_complete() (cli.py:6342), from the agent thread:
app.call_from_thread(app.mount_tool_block, cute_msg, gutter_prefixed_lines)
```

`HermesApp.mount_tool_block(cute_msg: str, lines: list[str])` runs on the event loop:
1. Commit any buffered live line in `LiveLineWidget` to the current RichLog.
2. Mount a new `ToolBlock` widget into the current `MessagePanel`, positioned before the `LiveLineWidget`.
3. Write the cute message to `ToolBlock.header`.
4. Write all `lines` to `ToolBlock`'s `ToolBodySegment` (the nested CopyableRichLog inside `ToolBodyContainer`).
5. Finalize `ToolBlock.line_count`.
6. If `line_count > 3`, set `collapsed = True` (default). If ≤ 3, set `collapsed = False` (permanently expanded, no chevron).
7. Resume routing subsequent `_cprint()` output to the main response RichLog.

**Thread safety:** `mount_tool_block()` is called via `call_from_thread()`, which schedules it on the event loop. Widget mounting happens on the event loop thread. No new thread-safety concerns.

**Trade-off:** Tool output cannot stream into the block incrementally — it must wait for completion. This is acceptable for diffs and code previews, which are generated post-execution. For tools that need incremental streaming (terminal, execute_code), see §8 `StreamingToolBlock`, which uses a different mounting path.

#### 7.5 Visual states reference

```
┌─────────────────────────────────────────────────────────────────┐
│ State: COLLAPSED (default after completion, >3 lines)           │
│                                                                 │
│   ┊ ✍️  write     /src/auth.py                     1.2s  ▸ 7L  │
│                                                                 │
│ Interaction: Enter/click → expand                               │
├─────────────────────────────────────────────────────────────────┤
│ State: EXPANDED (user toggled, or ≤3 lines permanently)         │
│                                                                 │
│   ┊ ✍️  write     /src/auth.py                     1.2s  ▾     │
│   ┊   --- a/src/auth.py                                        │
│   ┊   +++ b/src/auth.py                                        │
│   ┊   @@ -10,3 +10,5 @@                                       │
│   ┊     def authenticate(token):                                │
│   ┊  -      return db.lookup(token)                             │
│   ┊  +      session = db.lookup(token)                          │
│   ┊  +      if session and session.is_valid():                  │
│   ┊  +          return session                                  │
│                                                                 │
│ Interaction: Enter/click → collapse                             │
├─────────────────────────────────────────────────────────────────┤
│ State: INLINE (≤3 lines, no toggle)                             │
│                                                                 │
│   ┊ ✍️  write     /src/auth.py                     1.2s        │
│   ┊  +      return True                                        │
│                                                                 │
│ No chevron, no focus ring, not interactive.                     │
├─────────────────────────────────────────────────────────────────┤
│ State: STREAMING (tool executing, see §8)                       │
│                                                                 │
│   ┊ 💻 $         npm test                          ◐           │
│   ┊   PASS src/auth.test.ts                                    │
│   ┊   PASS src/db.test.ts                                      │
│   ┊   ░░░░░░░░░░░░░░░░░░░░░░ (streaming)                      │
│                                                                 │
│ Auto-scrolls. Auto-collapses when tool completes.               │
└─────────────────────────────────────────────────────────────────┘
```

#### 7.6 Browse mode and the StatusBar

The user needs to know when they're in browse mode (navigating focusable blocks) versus input mode (typing a message). The StatusBar is the right place for this — it's always visible, already shows contextual state, and doesn't steal vertical space.

**StatusBar layout update:**

Current:
```
claude-3.5-sonnet  ▰▰▰▰▰▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱ 45%  156 tok/s  12480 tok  2m34s
```

With browse mode active:
```
BROWSE ▸3/8  Tab cycle · Enter toggle · c copy · Esc exit     12480 tok  2m34s
```

**Design rationale:**
- The left side of the bar **completely replaces** the model/compaction info with browse context. The user doesn't need model name or context pressure while browsing — they need navigation state.
- `▸3/8` — the focused block index out of total focusable blocks. Tells the user where they are in the sequence and how many blocks exist. Updates on every Tab press.
- The hint string (`Tab cycle · Enter toggle · c copy · Esc exit`) is a **first-visit affordance**. After the user has used browse mode 3+ times in a session, shrink it to just the index and keybindings as single chars: `▸3/8  ⇥ ↵ c ⎋`. This avoids tooltip fatigue for power users while remaining discoverable for new users. The usage count is tracked as `_browse_uses: int = 0` on `HermesApp` — in-memory only, resets on restart. No file persistence is needed; the hint is a discoverability aid, not a user preference.
- The right side keeps `tokens tok  duration` — these are always relevant.
- Transition: entering browse mode triggers a `StatusBar` refresh with the new layout. Exiting restores the normal layout. No animation — instant swap.

**Implementation:**
- Add a reactive `browse_mode: reactive[bool] = reactive(False)` to `HermesApp`.
- Add a reactive `browse_index: reactive[tuple[int, int]] = reactive((0, 0))` — `(current, total)`.
- `StatusBar.render()` checks `browse_mode` and switches layout:
  ```python
  if app.browse_mode:
      idx, total = app.browse_index
      t.append("BROWSE", style="bold")
      t.append(f" ▸{idx}/{total}", style="bold {accent}")
      t.append("  Tab cycle · Enter toggle · c copy · Esc exit", style="dim")
  else:
      # existing model + compaction + tok/s layout
  ```
- `StatusBar` watches `browse_mode` and `browse_index` in addition to existing reactives.

**Focus ring styling:**

When a block (tool header, code block header, omission line) is focused in browse mode, it gets a subtle left-edge highlight — the gutter char changes from dim `┊` to accent-colored `┃` (a thicker vertical bar):

```
  ┃ ✍️  write     /src/auth.py                     1.1s  ▸ 7L    ← focused
  ┊ 💻 $         npm test                         30.0s  ▸ 47L
```

Why `┃` instead of an underline, border, or background highlight:
- Underline conflicts with link-style affordances.
- Border adds chrome that violates the no-box-drawing rule.
- Background highlight on a single line in a RichLog-based layout is fragile.
- `┃` is a single-character change in the gutter — zero layout impact, unmistakable signal.

**Implementation:** `ToolHeader` is a `Static` — it renders a single `Text` object, not child DOM elements. CSS child selectors (`.gutter`) don't apply. Instead, the gutter style is applied programmatically in `ToolHeader.render()`:

```python
def render(self) -> RenderResult:
    t = Text()
    gutter_style = "bold " + self._accent if self.has_focus else "dim"
    t.append("  ┃ " if self.has_focus else "  ┊ ", style=gutter_style)
    t.append(self._cute_msg)
    # ... chevron, line count
    return t
```

### 8. Streaming tool output

Terminal commands and code execution can take seconds to minutes. The current architecture waits for full completion before displaying anything — the user stares at a spinner. This is the single biggest perception-of-speed problem. A command that takes 30 seconds but shows output at second 2 *feels* faster than the same command with a spinner that resolves at second 30.

#### 8.1 Problem: the latency gap

**Current terminal tool flow:**
```
t=0s    ┊ ⚡ preparing terminal…     (preparing line)
t=0s    spinner: 💻 npm test          (spinner label updates)
t=0-30s ...spinner animates...        (user sees NOTHING from the command)
t=30s   ┊ 💻 $         npm test  30.0s (cute message appears)
        [full terminal output dumped below, or hidden entirely]
```

The user gets zero feedback from t=0 to t=30. They don't know if the command is stuck, producing errors, or almost done. This is unacceptable for any interactive tool.

**Desired flow:**
```
t=0s    ┊ 💻 $         npm test                           ◐
t=2s    ┊   PASS src/auth.test.ts
t=4s    ┊   PASS src/db.test.ts
t=6s    ┊   FAIL src/session.test.ts
        ┊     ● validate() rejects expired tokens
        ┊       Expected: true, Received: false
t=30s   ┊ 💻 $         npm test                        30.0s  ▸ 47L
        (auto-collapses on completion)
```

The user sees test results at second 2, spots the failure at second 6, and can mentally prepare (or interrupt) 24 seconds before the command finishes.

#### 8.2 Streaming tiers

Not every tool benefits from streaming. The cost is real: streaming requires a PTY or pipe reader thread, incremental rendering, and careful backpressure handling. Apply streaming only where the perception-of-speed gain justifies the complexity:

| Tool | Stream? | Rationale |
|---|---|---|
| `terminal` (foreground) | **Yes** | Primary use case. Commands take 1–300s. Output is the feedback signal. |
| `execute_code` | **Yes** | Python scripts can be long-running. Partial output (prints, progress bars) is essential. |
| `process` (poll/wait/log) | **Yes** | Already has incremental output via `process_registry`. Wire it to the TUI. |
| `write_file` / `patch` | No | Output is a diff generated post-execution. No streaming source. |
| `read_file` / `search_files` | No | Fast (<1s typically). Result is post-processed. |
| `browser_*` | Partial | `browser_navigate` could show page load progress. `browser_snapshot` result is post-processed. Defer to Phase 5. |
| `delegate_task` | **Yes** | Sub-agent can run for minutes. Stream its tool activity lines (nested cute messages). See §8.6. |

#### 8.3 Architecture: `StreamingToolBlock`

Extend the `ToolBlock` widget (§7.3) with a streaming mode:

```
StreamingToolBlock extends ToolBlock
  ├── ToolHeader (Static, focusable)     ← cute msg + spinner (not duration yet)
  ├── ToolBodyContainer (Vertical)        ← live output lines, gutter-prefixed
  └── ToolTail (Static, display: none)   ← scroll-lock badge: "↓ 12 new lines"
```

**`ToolTail`** is a 1-line Static that appears only when auto-scroll is disengaged (see §8.4). It displays `↓ N new lines` right-aligned and dim. Clicking it or pressing `End` re-engages auto-scroll. When auto-scroll is active (default), `ToolTail` is hidden via `display: none`. On stream completion, `ToolTail` is permanently hidden.

**Lifecycle states:**

```
IDLE → STREAMING → DRAINING → COMPLETED
```

- **IDLE:** Widget mounted, header shows tool name + spinner char. Body empty. `collapsed = False` (expanded during streaming — the user wants to see output).
- **STREAMING:** Lines arriving. Body grows. Auto-scroll is on (see §8.4). Spinner animates in header. The block is always expanded.
- **DRAINING:** Tool finished but output buffer still flushing. Brief (< 100ms in practice). Transition is invisible to user.
- **COMPLETED:** Final state. Header updates: spinner → duration string, chevron appears. If `line_count > 3`, auto-collapse. Body freezes (no more writes).

#### 8.4 Auto-scroll contract

When the `StreamingToolBlock` is visible (not scrolled past), new lines auto-scroll the `OutputPanel` to keep the latest line visible. This matches terminal behavior — tail -f semantics.

**Scroll lock:** If the user manually scrolls up (away from the bottom of `OutputPanel`), auto-scroll disengages for this block. A subtle indicator appears at the bottom of the block:

```
  ┊   PASS src/db.test.ts
  ┊   FAIL src/session.test.ts
  ┊                                          ↓ 12 new lines
```

The `↓ 12 new lines` badge is a dim, right-aligned static that updates as lines accumulate below the scroll viewport. Clicking it (or pressing `End`) re-engages auto-scroll and jumps to the latest output.

**Implementation:** `OutputPanel` already calls `scroll_end(animate=False)` after each chunk. Add a `_user_scrolled_up: bool` flag that is set when `OutputPanel` receives a scroll-up event and cleared when the user scrolls to the bottom or the tool completes. When `_user_scrolled_up` is True, suppress the `scroll_end()` call for streaming blocks.

#### 8.5 Backpressure and line budget

A runaway command (e.g., `find / -name "*"`) can produce thousands of lines per second. The TUI cannot render all of them without jank. Streaming tool output needs three throttles:

**Throttle 1: Render budget.** The `StreamingToolBlock`'s `ToolBodySegment` RichLog accepts at most **one line per 16ms** (60 fps). Excess lines are buffered in a ring buffer (last 200 lines). When the render budget is available, the most recent buffered line is rendered, plus a `… (N lines skipped)` indicator if lines were dropped. This means the user always sees the *latest* output, not a backlog from 5 seconds ago.

**Throttle 2: Line cap.** The body RichLog stores at most **200 visible lines**. When new lines arrive beyond this cap, the oldest lines are evicted from the RichLog (but preserved in `CopyableRichLog._plain_lines` for clipboard). The user sees a `… (showing last 200 of 1,247 lines)` header inside the body. Full output remains accessible via copy or the `process log` command.

**Throttle 3: Byte cap.** If a single line exceeds 2,000 characters (common with minified JSON, webpack output), truncate to first 200 chars + `… (+1,800 chars)`. Full line preserved in plain text buffer.

#### 8.6 Nested streaming: `delegate_task`

When the agent delegates to sub-agents, each sub-agent's tool activity should stream into a nested `StreamingToolBlock`:

```
  ┊ 🔀 delegate  2 parallel tasks                        ◐
  ┊   ┊ Task 1: "Fix auth module"
  ┊   ┊ 📖 read      /src/auth.py                     0.2s
  ┊   ┊ ✍️  write     /src/auth.py                        ◐
  ┊   ┊   +      if session and session.is_valid():
  ┊   ┊
  ┊   ┊ Task 2: "Update tests"
  ┊   ┊ 📖 read      /tests/auth.test.ts              0.1s
  ┊   ┊ ✍️  write     /tests/auth.test.ts                 ◐
```

The nested gutter doubles (`┊   ┊`) to indicate depth. Each sub-task's tool lines use the same tier/collapse rules. On completion, the entire delegate block collapses to:

```
  ┊ 🔀 delegate  2 parallel tasks                     4.7s  ▸ 12L
```

**Implementation:** The `delegate_task` tool already fires tool callbacks for sub-agents. Route these callbacks through a `_nested_stream_prefix` context that prepends `  ┊ ` to each line, compounding with the outer prefix. This is additive — the existing callback architecture handles the routing; only the prefix logic changes.

#### 8.7 Terminal output source: PTY bridge

**Current:** `terminal_tool.py` calls `env.execute(command, timeout=...)` which blocks until completion. The output is collected into a string and returned. No streaming path exists for foreground commands.

**New:** For foreground terminal commands, use the new `execute_streaming()` method on `ExecutionEnvironment` (see §8.2 compatibility table). The terminal tool calls it with a line callback:

```python
# In terminal_tool.py, for foreground commands:
def _execute_foreground_streaming(
    env: ExecutionEnvironment,
    command: str,
    timeout: int,
    on_line: Callable[[str], None],
) -> dict:
    """Execute with incremental output via the environment's streaming API."""
    return env.execute_streaming(command, timeout=timeout, on_line=on_line)
```

**Integration:** The `line_callback` is wired to `_cprint()` with the gutter prefix, flowing through the existing `_output_queue` → `StreamingToolBlock`'s `ToolBodySegment` path. The existing `tool_progress_callback` mechanism fires the mount, and the line callback populates the body during execution.

**Sandbox compatibility:** The `ExecutionEnvironment` base class (`tools/environments/base.py:492`) currently defines only `execute()` (blocking). A new `execute_streaming()` method is needed:

```python
# In ExecutionEnvironment (base.py):
def execute_streaming(
    self, command: str, timeout: int, on_line: Callable[[str], None]
) -> dict:
    """Execute with incremental output. Default: falls back to blocking execute()."""
    result = self.execute(command, timeout=timeout)
    # Emit all lines at once (no true streaming)
    for line in result.get("output", "").splitlines():
        on_line(line)
    return result
```

Environment-specific overrides:

| Environment | Streaming support | Mechanism |
|---|---|---|
| Local (`LocalEnv`) | **Yes** | `subprocess.Popen` with `stdout=PIPE`, line-buffered reader thread |
| Docker (`DockerEnv`) | **Yes** | `docker exec -t` with pipe, `recv()` loop |
| SSH (`SSHEnv`) | **Yes** | Existing channel `recv()` in a loop |
| Daytona (`DaytonaEnv`) | **Partial** | API-dependent; fall back to blocking if no stream endpoint |
| Modal (`ModalEnv`) | **No** | Uses blocking `execute()` fallback |

**Fallback:** The base class default (`execute_streaming` → `execute`) ensures every environment works without modification. The `StreamingToolBlock` shows just the spinner until completion for non-streaming environments, then renders the full output. No worse than today.

#### 8.8 Stream lifecycle — complete visual walkthrough

**Long-running `npm test` command (30 seconds):**

```
t=0.0s  Agent generates tool call:

  ┊ 💻 $         npm test                                 ◐

        (ToolBlock mounted, expanded, spinner animating in header)
        (ToolBodyContainer empty — no output yet from npm)

t=1.2s  First output lines arrive:

  ┊ 💻 $         npm test                                 ◐
  ┊
  ┊   > hermes-agent@1.0.0 test
  ┊   > jest --verbose
  ┊

t=3.5s  Test suites begin reporting:

  ┊ 💻 $         npm test                                 ◐
  ┊
  ┊   > hermes-agent@1.0.0 test
  ┊   > jest --verbose
  ┊
  ┊   PASS src/auth.test.ts (1.2s)
  ┊     ✓ validates tokens (45ms)
  ┊     ✓ rejects expired tokens (12ms)
  ┊   PASS src/db.test.ts (0.8s)
  ┊     ✓ connects to database (120ms)

t=8.0s  A failure appears — user notices immediately:

  ┊ 💻 $         npm test                                 ◐
  ┊   ...
  ┊   FAIL src/session.test.ts (2.1s)
  ┊     ✕ validate() rejects expired tokens (8ms)
  ┊
  ┊       Expected: true
  ┊       Received: false
  ┊
  ┊       at Object.<anonymous> (src/session.test.ts:42:5)

        (user can Ctrl+C here to interrupt if they've seen enough)

t=30.0s  Command completes. Block transitions to COMPLETED:

  ┊ 💻 $         npm test                            30.0s  ▸ 47L

        (header: spinner replaced with duration, chevron appears)
        (body: auto-collapsed because 47 > 3 lines)
        (user can expand to review full output)

        Response text resumes below:

The test suite has 1 failure in src/session.test.ts…
```

**Fast command (`cat README.md`, 0.1s):**

```
  ┊ 💻 $         cat README.md                        0.1s

        (No streaming visible — command completes before first render tick)
        (ToolBodyContainer empty or ≤3 lines → inline, no collapse)
```

**Command with massive output (`find / -type f`, interrupted):**

```
  ┊ 💻 $         find / -type f                          ◐
  ┊   … (showing last 200 of 14,392 lines)
  ┊   /usr/share/doc/libx11/changelog.gz
  ┊   /usr/share/doc/libx11/README
  ┊   /usr/share/doc/libxcb/changelog.gz

        (user presses Ctrl+C)

  ┊ 💻 $         find / -type f                       2.4s  ▸ 200L
        (collapsed, shows 200L — the visible cap, not 14,392)
        (copy-paste gets all 14,392 lines from the plain buffer)
```

### 9. Expandable omission markers

Three places in the current codebase truncate output and insert an omission notice:

| Source | Current marker | Location |
|---|---|---|
| Terminal tool | `... [OUTPUT TRUNCATED - N chars omitted out of M total] ...` | `terminal_tool.py:1488–1498` |
| Inline diff preview | `… omitted 42 diff line(s) across 3 additional file(s)/section(s)` | `display.py:617–620` |
| Code/terminal preview | `╌╌ 12 more lines omitted ╌╌` | `display.py:654–673` |

These are currently flat text — the user sees the omission notice but cannot do anything about it. The omitted content is gone (terminal tool truncated it from the string, diff preview never rendered it, preview cap dropped the tail). This is a lossy pipeline. The user's only recourse is re-running the command or opening the file manually.

#### 9.1 Design: omission markers become collapsible blocks

Every omission notice becomes a focusable, expandable line — visually consistent with tool blocks (§7) and code blocks (§10). The collapsed state is the omission summary. The expanded state reveals the hidden content.

**Collapsed (default):**
```
  ┊   PASS src/auth.test.ts
  ┊   PASS src/db.test.ts
  ┊   ╌╌ 847 lines omitted ╌╌                                ▸
  ┊   FAIL src/session.test.ts
```

**Expanded:**
```
  ┊   PASS src/auth.test.ts
  ┊   PASS src/db.test.ts
  ┊   ╌╌ 847 lines ╌╌                                        ▾
  ┊   PASS src/utils.test.ts
  ┊   PASS src/config.test.ts
  ┊   … (845 more lines)
  ┊   PASS src/middleware.test.ts
  ┊   FAIL src/session.test.ts
```

Wait — expanding 847 lines into a RichLog would be catastrophic for layout performance and usability. Nobody reads 847 lines. The expanded state needs progressive disclosure:

**Expanded state (smart preview):**
```
  ┊   ╌╌ 847 lines ╌╌                                        ▾
  ┊    ··· first 5 ···
  ┊   PASS src/utils.test.ts
  ┊   PASS src/config.test.ts
  ┊   PASS src/router.test.ts
  ┊   PASS src/logger.test.ts
  ┊   PASS src/cache.test.ts
  ┊    ··· last 5 ···
  ┊   PASS src/events.test.ts
  ┊   PASS src/hooks.test.ts
  ┊   PASS src/queue.test.ts
  ┊   PASS src/jobs.test.ts
  ┊   PASS src/middleware.test.ts
  ┊                                                       ⎘ copy all
```

Rules:
- Show first 5 + last 5 lines of the omitted region.
- If ≤ 12 lines omitted, show all of them (no head/tail split needed).
- `⎘ copy all` affordance at the bottom copies the *complete* omitted content to clipboard (see §10 for the copy mechanism).
- The omission block participates in Tab focus cycling and responds to `c` (copy) and `Enter` (toggle).

#### 9.2 Prerequisite: lossless omission pipeline

The current truncation is **destructive** — content is dropped from the string before it reaches the display layer. To make omissions expandable, the full content must survive to the widget:

**Terminal tool (50,000 char cap):**
- Change: Instead of slicing the output string in `terminal_tool.py`, return the full string and attach metadata: `{"output": full_output, "truncated_at": 50000, "total_chars": len(full_output)}`.
- The display layer applies the 40/60 head/tail split for *rendering* but stores the full text in the `OmissionBlock` widget's backing buffer.
- Memory concern: terminal output is already capped at 200KB by the process registry's rolling buffer. The 50K display cap is a *rendering* optimization, not a memory guard. Storing the full 200KB string in a plain text buffer (not rendered to RichLog) costs ~200KB — negligible.

**Diff preview (80 lines / 6 files):**
- Change: `_summarize_rendered_diff_sections()` currently stops rendering after the budget. Instead, render all sections to ANSI strings, but only *display* the first N. Store the remainder in the `OmissionBlock` widget.
- For diffs that exceed the budget significantly (>500 lines), only store the first 500 total. Beyond that, the user should use `git diff` directly.

**Code/terminal preview (40 lines):**
- Change: Same pattern. Render all lines, display first 40, store the rest.

#### 9.3 Widget: `OmissionBlock`

```
OmissionBlock extends Widget
  ├── OmissionHeader (Static, can_focus=True) ← "╌╌ N lines omitted ╌╌  ▸  ⎘"
  └── OmissionBody (RichLog, height: auto)    ← head/tail preview
```

The `⎘` copy affordance is rendered inline in `OmissionHeader.render()` (right-aligned), consistent with `ToolHeader` and `CodeHeader`. No separate `CopyAffordance` widget needed.

- Shares the same collapse/expand/focus/copy semantics as `ToolBlock` (§7) and `CodeBlock` (§10).
- `collapsed: reactive[bool] = reactive(True)`.
- `_full_content: str` — the complete omitted text (plain, for clipboard).
- `_head_lines: list[str]` / `_tail_lines: list[str]` — the 5+5 preview lines, pre-rendered with ANSI.
- The body is populated on first expand (lazy render — don't pay the cost for blocks the user never opens).

#### 9.4 Visual integration

Omission markers use the same gutter alignment as tool output (§5) and the same chevron/line-count language as tool blocks (§7). The `╌╌` dashed line is the distinguishing mark — it means "content was here but is hidden," distinct from `┊` which means "tool activity."

```
  ┊ 💻 $         npm test                         30.0s  ▾
  ┊   > jest --verbose
  ┊   PASS src/auth.test.ts (1.2s)
  ┊   PASS src/db.test.ts (0.8s)
  ┊   ╌╌ 847 lines ╌╌                                    ▸    ← omission
  ┊   FAIL src/session.test.ts (2.1s)
  ┊
  ┊   Tests: 1 failed, 212 passed, 213 total
```

The omission sits inside the tool block's `ToolBodyContainer` (see §7.3). The container holds a sequence of `ToolBodySegment` (CopyableRichLog) and `OmissionBlock` widgets interleaved — lines before the omission in one segment, the `OmissionBlock`, then lines after in another segment. When the tool block collapses, the entire `ToolBodyContainer` is hidden via `display: none`, so the omission collapses with it.

### 10. Code blocks and the copy affordance

Response text contains fenced code blocks (```python … ```) rendered with syntax highlighting via `rich_output.py`. These are currently rendered as flat ANSI lines in the response RichLog — the user cannot interact with them, focus them, or copy their content without manually selecting text with the mouse. For an agent that writes code, this is a fundamental interaction gap.

#### 10.1 The copy problem

When the user sees a code block in the response, the most common next action is one of:
- Copy the code to paste into a file or terminal.
- Copy a command to run it.
- Read it, and move on.

Mouse selection in a terminal TUI is fragile — it grabs line numbers, gutter chars, and ANSI artifacts. Triple-click selects a single visual line but not a logical code block. Shift+click range selection breaks across wrapped lines. The user ends up with broken code on their clipboard.

The solution: make every code block a **focusable, copyable unit** with a one-action copy affordance.

#### 10.2 Interaction model

**Default state (not focused):**
```
I've fixed the authentication logic:

  1 │ def authenticate(token):
  2 │     session = db.lookup(token)
  3 │     if session and session.is_valid():
  4 │         return session
  5 │     return None

You can test it with…
```

Code blocks already have line numbers (`N │`) from `rich_output.py:_number_code_lines()`. No change to the rendered appearance.

**Focused state (Tab navigated or clicked):**
```
I've fixed the authentication logic:

  1 │ def authenticate(token):                                    ⎘
  2 │     session = db.lookup(token)
  3 │     if session and session.is_valid():
  4 │         return session
  5 │     return None

You can test it with…
```

A single `⎘` glyph (U+2398, HELM SYMBOL — or `📋` if Unicode support is uncertain) appears in the top-right corner of the code block. This is the copy affordance. It's dim until the block is focused, then accent-colored.

- **`c` key** or **click on `⎘`** — copies the code block content to clipboard. The content is **raw source code**: no line numbers, no gutter, no ANSI escape sequences, no Rich markup. Just the text the user would paste into a file.
- **`Enter` key** — for code blocks ≤12 lines (always visible), Enter copies. For code blocks >12 lines (collapsible per §10.7), Enter toggles collapse/expand (consistent with tool blocks).
- After copy: a brief flash confirmation. The `⎘` glyph changes to `✓` for 1.5 seconds (skin-accent colored), then reverts. No toast, no modal, no status bar message. The confirmation is co-located with the action.

**Mouse only (no keyboard):** Click anywhere inside the code block area to focus it. The `⎘` appears. Click `⎘` to copy. This is a two-click flow (focus + copy). Single-click-to-copy would conflict with text selection — the user might be trying to select a portion, not copy the whole block.

#### 10.3 What gets copied

The copy content is **not** what's displayed. It's the source text before rendering:

| Display | Clipboard |
|---|---|
| `  1 │ def authenticate(token):` | `def authenticate(token):` |
| Syntax-highlighted ANSI | Plain UTF-8 text |
| Gutter prefix `  ┊ ` (if inside tool block) | No prefix |
| Fenced block markers (`` ``` ``) | No markers |

The plain source text is captured during the rendering pipeline. In `StreamingCodeBlockHighlighter._flush_block()` (`rich_output.py`), the raw lines between the opening and closing fences are available before syntax highlighting is applied. Store them alongside the rendered output.

#### 10.4 Widget: `CodeBlock`

```
CodeBlock extends Widget
  ├── CodeHeader (Static, can_focus=True)  ← invisible when unfocused; shows ⎘ when focused
  └── CodeBody (CopyableRichLog, height: auto) ← syntax-highlighted code lines
```

Code blocks are currently rendered as sequential lines in the response RichLog, interleaved with prose. Extracting them into separate widgets means the response is no longer a single RichLog but a sequence of `[prose RichLog, CodeBlock, prose RichLog, CodeBlock, ...]`.

**Approach: Segmented response container (recommended).**
Replace the single response `CopyableRichLog` with a `ResponseFlow` container that mounts alternating `ProseSegment` (RichLog) and `CodeBlock` (Widget) children:

```
ResponseFlow (Vertical, height: auto)
  ├── ProseSegment (CopyableRichLog)     ← "I've fixed the auth logic:"
  ├── CodeBlock (Widget)                 ← collapsible, focusable, copyable
  │     ├── CodeHeader (Static, can_focus=True)
  │     └── CodeBody (CopyableRichLog, height: auto)
  └── ProseSegment (CopyableRichLog)     ← "You can test it with…"
```

**Why not inline RichLog with overlay?** An inline approach (keeping code blocks as RichLog lines with a floating overlay) was considered. It preserves the single-RichLog streaming pipeline. However, it's incompatible with §10.7's collapsible code blocks — RichLog cannot hide individual lines. Collapsibility requires the code block to be a discrete widget with `display: none` on its body. The segmented approach is the only path that supports both copy affordances and collapse.

**Stream-splitting concern:** `LiveLineWidget.append()` splits on `\n` and commits lines to the current active segment. When `StreamingCodeBlockHighlighter._flush_block()` returns a highlighted block, `_consume_output()` detects the block boundary (via a sideband signal from the highlighter — see §10.5), mounts a new `CodeBlock` widget, writes the highlighted lines to `CodeBlock.body`, then resumes prose flow into a new `ProseSegment`. The `LiveLineWidget` itself doesn't split — the consumer (`_consume_output`) manages routing.

**Partial ANSI sequences:** The code block highlighter buffers all lines between fences and returns the complete highlighted block at once (see `_flush_block()` at rich_output.py:2133). No partial ANSI sequences cross the prose/code boundary — the boundary is always at a complete block boundary.

#### 10.5 Code block metadata and the copy source

With the `ResponseFlow` approach, each `CodeBlock` widget stores its own metadata directly:

```python
class CodeBlock(Widget):
    _plain_source: str    # Raw code, no line numbers, no ANSI
    _language: str        # Language hint (e.g., "python", "")
    _line_count: int      # Total lines in the code block
```

No separate `CodeBlockMeta` dataclass is needed — the metadata lives on the widget instance, set at mount time.

**Population:** The agent-side `StreamingCodeBlockHighlighter` (rich_output.py:2059) already knows when a fenced block opens and closes. Extend `_flush_block()` (rich_output.py:2133) to return both the highlighted string and the raw source:

```python
# In StreamingCodeBlockHighlighter._flush_block() (rich_output.py:2133):
def _flush_block(self) -> tuple[str, str]:
    """Returns (highlighted_numbered_str, raw_source_code)."""
    code = "\n".join(self._buf)
    lang = self._lang or self._det.detect_from_content(code)
    highlighted = self._hl.to_ansi(code, language=lang).rstrip("\n")
    self._in_block = False
    raw = code  # preserve before clearing
    self._lang = None
    self._buf = []
    return _number_code_lines(highlighted), raw
```

**Return type change:** `process_line()` return type changes from `Optional[str]` to `Optional[str | tuple[str, str]]`. Prose lines still return the original `str` object (identity preserved for the `out is line` check in cli.py's streaming path — see test_rich_output.py:293). Code blocks return a `tuple[str, str]`. The cli.py streaming loop (line 668) checks `isinstance(out, tuple)`: if tuple, mount a `CodeBlock` widget with `out[0]` (highlighted) as body content and `out[1]` (raw) as `_plain_source`. If str, route to the current `ProseSegment` as before.

**Test impact:** `TestStreamingCodeBlockHighlighter` (test_rich_output.py:276+) assertions on `process_line()` return values need updating — code block completion now returns `tuple` instead of `str`.

**Copy affordance:** With the segmented `ResponseFlow` approach (§10.4), code blocks are discrete `CodeBlock` widgets. The `⎘` glyph is rendered inline in `CodeHeader.render()`, not as a separate widget:

```
CodeBlock (Widget)
  ├── CodeHeader (Static, can_focus=True)   ← shows ⎘ when focused
  └── CodeBody (CopyableRichLog, height: auto)
```

The `⎘` glyph is rendered in `CodeHeader.render()`, right-aligned. No absolute positioning needed — the header is a structural part of the widget.

The `⎘` → `✓` flash (1.5s) is handled via `set_timer()` in the `CodeHeader` widget, toggling a CSS class:

```css
/* hermes.tcss */
CodeHeader { color: $text-muted; }
CodeHeader:focus { color: $text; }
CodeHeader.-copied { color: $success; }
```

#### 10.6 Copy affordance on all block types

The `⎘` / `c`-to-copy pattern is universal across all focusable blocks, not just code blocks:

| Block type | What `c` copies |
|---|---|
| **Code block** (§10) | Raw source code — no line numbers, no ANSI, no fences |
| **Tool block** (§7) | Tool output body — diff lines, terminal output, code preview. No gutter prefix, no cute message header. |
| **Omission block** (§9) | Full omitted content (all N lines, not just the 5+5 preview). |
| **Streaming block** (§8) | Snapshot of current output at time of copy. If still streaming, copies what's available so far. |

The copy always produces **clean plain text** suitable for pasting into a file, terminal, or editor. No ANSI, no Rich markup, no line numbers, no gutter `┊`, no chevrons.

**Copy confirmation** is consistent across all block types: `⎘` → `✓` for 1.5 seconds, accent-colored.

#### 10.7 Long code blocks: collapse threshold

Code blocks in agent responses can be long — a 200-line generated file, a full test suite. These should follow the same collapse rules as tool output blocks:

- **≤ 12 lines**: fully visible, no collapse. `⎘` affordance appears on focus.
- **> 12 lines**: collapsed by default. Header shows the language tag and line count:
  ```
  python ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌  87L  ▸  ⎘
  ```
  Expanding reveals the full code block. The header uses a fading rule (matching the `PlainRule` aesthetic from §widgets.py) with the language name left-aligned — echoing how fenced blocks start with `` ```python `` in source.

Why 12 and not 3 (the tool block threshold)? Code blocks are *content the user asked for*. Tool output is *byproduct the user may not care about*. A higher threshold for code respects that the user likely wants to read the code they requested.

**Collapsed code block visual:**
```
I've rewritten the entire auth module:

python ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌  87 lines  ▸  ⎘

Let me know if you'd like me to add tests.
```

**Expanded:**
```
I've rewritten the entire auth module:

python ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌  87 lines  ▾  ⎘
  1 │ """Authentication module for Hermes Agent."""
  2 │
  3 │ import hashlib
  4 │ import hmac
    …
 87 │     return None

Let me know if you'd like me to add tests.
```

---

## Implementation plan

### Phase 1: Noise reduction (low risk, high impact)

1. **Remove the `preparing` line.** Delete the `_cprint(f"  ┊ {emoji} preparing {tool_name}…")` call in `_on_tool_gen_start()` (`cli.py:6290`). The spinner label already provides this feedback.
2. **Add tool tier system.** Implement `_tool_display_tier()` in `agent/display.py`. Gate `_vprint(cute_msg)` calls in `run_agent.py` on tier + failure status.
3. **Add prefix kwarg to preview renderers.** Update `render_edit_diff_with_delta()`, `render_read_file_preview()`, `render_terminal_preview()`, `render_execute_code_preview()` in `agent/display.py` to accept `prefix: str = ""` and prepend it to every emitted line. Pass `"  ┊ "` from `_on_tool_complete()`.

### Phase 2: Alignment polish

4. **Right-align durations.** Update `get_cute_tool_message()` to pad detail→duration with `wcswidth()` for display-width-aware padding. Accept optional `width: int` parameter (TUI passes widget width; PT mode uses `shutil.get_terminal_size()`).
5. **Standardize gutter prefix.** Audit all tool output paths and ensure the `  ┊ ` prefix is applied consistently. Remove ad-hoc prefix construction in `_on_tool_gen_start()`.

### Phase 3: In-place line updates

6. **`ToolPendingLine` widget.** Add `ToolPendingLine` (per §1) to `MessagePanel` (above the RichLog, below the reasoning panel). Tool-in-progress lines render here via `set_line(tool_id, styled)` and are replaced freely. On completion, `remove_line(tool_id)` clears the entry and the final cute message is committed to the RichLog.
7. **Concurrent batch ordering.** `ToolPendingLine` renders N lines keyed by tool call ID in insertion order. Each completes independently. Widget auto-hides when all pending lines are removed.

### Phase 4: Collapsible blocks + browse mode

8. **Browse mode infrastructure.** Add `browse_mode: reactive[bool]` and `browse_index: reactive[tuple[int, int]]` to `HermesApp`. Implement `Escape` from input to enter browse mode, `Escape` / printable key to exit. Wire StatusBar to display the browse-mode layout per §7.6.
9. **`ToolBlock` widget.** Implement `ToolBlock`, `ToolHeader`, `ToolBodyContainer`, `ToolBodySegment` in `hermes_cli/tui/tool_blocks.py` per §7.3. Unit test: mount, write lines, toggle collapsed, verify display/none, verify line count in header.
10. **`mount_tool_block()` method.** Add `HermesApp.mount_tool_block(cute_msg, lines)` per §7.4. Integration test: call via `call_from_thread`, verify `ToolBlock` mounted with correct header and body content.
11. **Wire `_on_tool_complete()`.** Call `mount_tool_block()` from `_on_tool_complete()` with gutter-prefixed lines from the preview renderers. Verify that diffs appear inside collapsible blocks.
12. **Keyboard + mouse interaction.** Add `on_click` / `on_key` handlers to `ToolHeader`. Add `Tab` focus cycling across all focusable block headers. Add `a`/`A` expand-all/collapse-all binding. Focus ring: `┊` → `┃` accent-colored.
13. **Copy affordance.** Implement `⎘` → `✓` flash behavior in all focusable block headers (`ToolHeader`, `CodeHeader`, `OmissionHeader`) via `set_timer()` + CSS class toggle per §10.5. Wire `c` key to copy. Verify clean plain text on clipboard (no ANSI, no gutter, no line numbers).

### Phase 5: Code blocks + copy

> **Risk note:** Phase 5 replaces the entire response rendering pipeline (`LiveLineWidget` → `ResponseFlow`). This is the highest-risk phase — it touches the streaming hot path and adds significant widget complexity. Gate it behind a feature flag (`display.response_flow: true` in the profile YAML, default `false`) and land it after Phase 7 is stable. The logical ordering in this document reflects dependencies, not recommended merge order. Recommended merge order: 1 → 2 → 3 → 4 → 6 → 7 → 5.

14. **`_flush_block()` tuple return + `ResponseFlow`.** Update `StreamingCodeBlockHighlighter._flush_block()` to return `tuple[str, str]` (highlighted, raw source). Implement `ResponseFlow` container in `hermes_cli/tui/code_blocks.py`. Update `_consume_output()` to detect code block boundaries and route lines to alternating `ProseSegment` / `CodeBlock` children per §10.4.
15. **Code block focus + copy.** In browse mode, Tab-cycling includes `CodeHeader` widgets. Focused code block shows `⎘` in header via `CodeHeader.render()`. `c` key copies raw source from `CodeBlock._plain_source`.
16. **Long code block collapse.** Implement the >12 line collapse threshold per §10.7. Header: `python ╌╌╌╌╌╌ 87 lines ▸ ⎘`. Toggle expand/collapse via Enter.
17. **Copy on all block types.** Unify `c`-to-copy across ToolBlock, CodeBlock, OmissionBlock. Each returns its type-appropriate plain content per §10.6.

### Phase 6: Expandable omissions

18. **Lossless omission pipeline.** Refactor `terminal_tool.py` truncation (lines 1488–1498) to preserve full output and attach metadata. Refactor `_summarize_rendered_diff_sections()` to store omitted content. Refactor preview cap to store tail lines.
19. **`OmissionBlock` widget.** Implement per §9.3. Collapsed: `╌╌ N lines ╌╌ ▸`. Expanded: 5+5 head/tail preview with `⎘ copy all`. Lazy render on first expand.
20. **Wire omission blocks into tool output.** Omission markers inside `ToolBodyContainer` are mounted as `OmissionBlock` widgets between `ToolBodySegment` RichLogs. Tab-focusable in browse mode.

### Phase 7: Streaming tool output

21. **`execute_streaming()` method.** Add `execute_streaming(command, timeout, on_line)` to `ExecutionEnvironment` base class with blocking fallback (per §8.7). Override in `LocalEnv` with `subprocess.Popen` + reader thread. Wire `terminal_tool.py` to use it for foreground commands. Unit test: run `echo hello && sleep 1 && echo world`, verify callback fires at t≈0 and t≈1.
22. **`StreamingToolBlock` widget.** Extend `ToolBlock` with streaming lifecycle (IDLE→STREAMING→COMPLETED) per §8.3. Unit test: mount, stream 10 lines, complete, verify auto-collapse and duration.
23. **Backpressure.** Implement 60fps render throttle and 200-line cap per §8.5. Stress test: pipe 10,000 lines/sec, verify no jank, verify ring buffer eviction, verify copy gets full output.
24. **Auto-scroll + scroll lock.** Implement `_user_scrolled_up` flag in `OutputPanel` per §8.4. Manual test: stream output, scroll up, verify auto-scroll stops, scroll to bottom, verify auto-scroll resumes.
25. **Wire to `execute_code`.** Apply same streaming bridge to Python code execution. Verify `print()` statements appear incrementally.
26. **Nested delegation.** Implement `_nested_stream_prefix` for `delegate_task` sub-agent callbacks per §8.6. Integration test: delegate 2 tasks, verify nested gutter and per-task collapse.

---

## UX comparison: before and after (final)

### Before
```
⚕ Hermes ──────────────────────────────────────────────────────
▌ Let me check the authentication module…

  ┊ ⚡ preparing read_file…
  ┊ 📖 read      /src/auth.py  0.2s
  ┊ ⚡ preparing read_file…
  ┊ 📖 read      /src/db.py  0.3s
  ┊ ⚡ preparing search_files…
  ┊ 🔎 grep      "session_id"  0.4s
  ┊ ⚡ preparing write_file…
  ┊ ✍️  write     /src/auth.py  1.1s
--- a/src/auth.py
+++ b/src/auth.py
@@ -10,3 +10,5 @@
   def authenticate(token):
-      return db.lookup(token)
+      session = db.lookup(token)
+      if session and session.is_valid():
+          return session

  ┊ ⚡ preparing terminal…
  ┊ 💻 $         npm test  30.0s
  ┊ 📋 plan      3 task(s)  0.1s

I've updated the authentication to validate sessions.

Here's the new implementation:

  1 │ def authenticate(token):
  2 │     session = db.lookup(token)
  3 │     if session and session.is_valid():
  4 │         return session
  5 │     return None

And the test command: `npm test`
```

```
claude-3.5-sonnet  ▰▰▰▰▰▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱ 45%  156 tok/s  12480 tok  2m34s
```

**31 lines of output. No copy affordance. No collapse. No streaming. Status bar shows model info that's irrelevant while reading output.**

### After (input mode)
```
⚕ Hermes ──────────────────────────────────────────────────────
▌ Let me check the authentication module…

  ┊ 📖 read      /src/auth.py                          0.2s
  ┊ 📖 read      /src/db.py                            0.3s
  ┊ 🔎 grep      "session_id"                          0.4s
  ┊ ✍️  write     /src/auth.py                     1.1s  ▸ 7L
  ┊ 💻 $         npm test                         30.0s  ▸ 47L

I've updated the authentication to validate sessions.

Here's the new implementation:

  1 │ def authenticate(token):
  2 │     session = db.lookup(token)
  3 │     if session and session.is_valid():
  4 │         return session
  5 │     return None
```

5 lines ≤ 12 → fully visible, no collapse (per §10.7).

```
claude-3.5-sonnet  ▰▰▰▰▰▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱ 45%  156 tok/s  12480 tok  2m34s
```

### After (browse mode — user pressed Escape, tabbed to the write diff)
```
⚕ Hermes ──────────────────────────────────────────────────────
▌ Let me check the authentication module…

  ┊ 📖 read      /src/auth.py                          0.2s
  ┊ 📖 read      /src/db.py                            0.3s
  ┊ 🔎 grep      "session_id"                          0.4s
  ┃ ✍️  write     /src/auth.py                     1.1s  ▾  ⎘
  ┊   --- a/src/auth.py
  ┊   +++ b/src/auth.py
  ┊   @@ -10,3 +10,5 @@
  ┊     def authenticate(token):
  ┊  -      return db.lookup(token)
  ┊  +      session = db.lookup(token)
  ┊  +      if session and session.is_valid():
  ┊  +          return session
  ┊ 💻 $         npm test                         30.0s  ▸ 47L

I've updated the authentication to validate sessions.

Here's the new implementation:

  1 │ def authenticate(token):                                    ⎘
  2 │     session = db.lookup(token)
  3 │     if session and session.is_valid():
  4 │         return session
  5 │     return None
```

5 lines ≤ 12 → fully visible, `⎘` affordance shown because code block is focused.

```
BROWSE ▸4/6  Tab cycle · Enter toggle · c copy · Esc exit     12480 tok  2m34s
```

**Delta:** 31 lines → 18 (input mode — preparing lines removed, diffs collapsed, code block visible at 5 lines). Browse mode reveals exactly the block the user cares about. `c` copies the diff — clean, no gutter, no ANSI. Status bar shows navigation context instead of model info. The write diff block, the npm test output, and the code block are each one Tab press apart. Every omission in the terminal output (47L of test results) is expandable in-place with head/tail preview.

---

## Risks and mitigations (final)

| Risk | Impact | Mitigation |
|---|---|---|
| Textual RichLog has no `replace_last` | Phase 3 blocked | Phase 3 uses `ToolPendingLine` widget (dict-based, keyed by tool ID) instead of RichLog mutation — avoids the API gap entirely |
| Silent-tier tool hides a failure | User misses error | Silent tier promotes to Compact on failure — always show failures |
| Gutter prefix breaks copy-paste | Pasted code has `┊` chars | All copy paths (`c` key, `⎘` click) extract from plain text buffers — no gutter, no ANSI, no line numbers |
| Terminal width detection fails in TUI | Duration padding wrong | Fall back to 2-space separation (current behavior) if width unavailable |
| Concurrent batch placeholder jank | Visual flicker during rapid updates | `ToolPendingLine` renders all pending lines as a single `Text` object — one refresh per update, no per-line mount/unmount. Fall back to "print all after completion" if issues arise. |
| `ToolBlock` mount during streaming causes layout thrash | Scroll jank, dropped frames | Mount once at tool start, write lines incrementally. `call_after_refresh` batches layout. 60fps render budget caps the worst case. |
| Streaming unavailable in some sandboxes | No streaming for Modal/gateway envs | Graceful fallback: `execute_streaming()` base class falls back to blocking `execute()`. No worse than today. |
| Massive output overwhelms RichLog memory | OOM on `find /` | 200-line visible cap + ring buffer eviction. Full output in plain text buffer only (not rendered). Copy extracts from plain buffer. |
| Nested delegation depth > 2 | Gutter prefix consumes too much horizontal space | Cap nesting display at 2 levels. Deeper sub-agents flatten to level-2 gutter. |
| Browse mode focus conflicts with input | User can't type while browsing | Any printable key exits browse mode and inserts into input. Escape toggles. Clear, single-key exit. |
| `ResponseFlow` segmented container adds layout complexity | More widgets = more layout passes | Each segment is `height: auto` — Textual's layout handles this natively. No manual height calculation. Only mount new segments on code block boundaries (not per-line). |
| Lossless omission stores large strings | Memory for 200KB terminal outputs | Omission buffers are plain strings (not rendered Rich objects). 200KB is the process registry's existing cap. No new memory ceiling. |
| Code block raw source lost | Copy returns empty or wrong content | Raw source is stored on the `CodeBlock` widget instance (`_plain_source: str`), not as line indices. Immutable once set. No drift risk. |
| `⎘` → `✓` flash timer leaks | Timer not cancelled on widget removal | Use Textual's `set_timer()` which auto-cancels on dismount. |

---

## Files changed

### New files

| File | Purpose |
|---|---|
| `hermes_cli/tui/tool_blocks.py` | `ToolBlock`, `ToolHeader`, `ToolBodyContainer`, `ToolBodySegment`, `StreamingToolBlock`, `ToolTail`, `ToolPendingLine` widgets |
| `hermes_cli/tui/code_blocks.py` | `CodeBlock`, `CodeHeader`, `CodeBody`, `ResponseFlow` widgets |
| `hermes_cli/tui/omission_blocks.py` | `OmissionBlock`, `OmissionHeader`, `OmissionBody` widgets |

**Note:** `CopyableRichLog` already exists in `hermes_cli/tui/widgets.py` (line 67). It is not a new file — it is referenced by `ToolBodySegment`, `CodeBody`, and `OmissionBody` but does not need to be created.

### Modified files

| File | Changes |
|---|---|
| `hermes_cli/tui/widgets.py` | Update `MessagePanel.compose()` to yield `ToolPendingLine` + `ResponseFlow` (replaces single `CopyableRichLog`); update `LiveLineWidget.append()` to route lines to active `ResponseFlow` segment or `ToolBlock` body; update `MessagePanel.response_log` property |
| `hermes_cli/tui/app.py` | Add `browse_mode`, `browse_index` reactives; add `mount_tool_block()`, `enter_browse_mode()`, `exit_browse_mode()` methods; update `on_key()` for browse bindings; update `StatusBar.render()` for browse layout; add `_consume_output()` routing for `ResponseFlow` segments |
| `hermes_cli/tui/hermes.tcss` | CSS for `ToolHeader`, `ToolBodyContainer`, `ToolBodySegment`, `CodeHeader`, `CodeBody`, `OmissionHeader`, `ToolTail`, browse-mode focus styles |
| `cli.py` | Remove `_cprint(f"  ┊ {emoji} preparing {tool_name}…")` from `_on_tool_gen_start()` (line 6290); update `_on_tool_complete()` to call `mount_tool_block()` with prefixed lines; update streaming loop (line 668) to handle `_flush_block()` tuple return and mount `CodeBlock` widgets |
| `agent/display.py` | Add `_tool_display_tier()` function; add `prefix: str` kwarg to `render_edit_diff_with_delta()`, `render_read_file_preview()`, `render_terminal_preview()`, `render_execute_code_preview()`, `_emit_highlighted_lines()`, `_highlight_block()`; update `get_cute_tool_message()` for right-aligned duration + `width` param + `wcswidth()` padding |
| `agent/rich_output.py` | Update `StreamingCodeBlockHighlighter._flush_block()` to return `tuple[str, str]` (highlighted, raw source); update `process_line()` and `flush()` return types |
| `run_agent.py` | Gate `_vprint(cute_msg)` calls in `_execute_tool_calls_sequential()` (line 6537+) and `_execute_tool_calls_concurrent()` on `_tool_display_tier()` |
| `tools/terminal_tool.py` | Preserve full output string; attach `truncated_at` / `total_chars` metadata instead of slicing (line 1488); add `execute_streaming()` method |
| `tools/environments/base.py` | Add `execute_streaming()` default method to `ExecutionEnvironment` |
| `tests/test_rich_output.py` | Update `TestStreamingCodeBlockHighlighter` assertions for `process_line()` tuple return |
| `tests/tui/test_tool_blocks.py` | New: tests for `ToolBlock`, `ToolPendingLine`, `StreamingToolBlock`, browse mode, copy |
| `tests/tui/test_code_blocks.py` | New: tests for `CodeBlock`, `ResponseFlow`, collapse threshold, copy |
| `tests/tui/test_omission_blocks.py` | New: tests for `OmissionBlock`, head/tail preview, lossless pipeline |

---

## Configuration

```yaml
# In profile YAML (e.g., profiles/default.yaml):
tool_display:
  # Override tier for specific tools. Valid values: verbose, compact, silent.
  # Unknown tools default to "compact".
  tiers:
    # write_file: verbose   # (default — listed for reference)
    # todo: silent           # (default — listed for reference)
    my_custom_mcp_tool: verbose  # promote a custom tool to verbose tier
```

No new YAML files. The `tool_display` key is added to the existing profile configuration.

---

## Backward compatibility

- **When disabled (`tool_progress_mode: "off"`):** All tool output is suppressed (Silent tier for everything). Existing behavior is preserved.
- **Default behavior change:** The `preparing` line is removed unconditionally. Users who relied on it for visual feedback will see the spinner label instead (which already existed). No configuration to restore the old `preparing` line.
- **Migration:** None required. The feature is additive — existing profiles work without changes. New `tool_display.tiers` config is optional.
- **PT (non-TUI) mode:** The prefix kwarg, duration alignment, and tier gating apply to PT mode as well. Browse mode, collapsible blocks, and copy affordances are TUI-only and have no effect in PT mode.

---

## Test plan

| Phase | Step | Tests | Focus |
|---|---|---|---|
| 1 | Remove preparing line | 2 | Verify no `preparing` line emitted; spinner label still updates |
| 1 | Tool tier system | 6 | `_tool_display_tier()` returns correct tier for known tools; default `compact` for unknown; `tool_progress_mode` promotion/demotion; failure promotion for silent tools |
| 1 | Prefix kwarg on renderers | 4 | `render_edit_diff_with_delta()`, `render_read_file_preview()`, `render_terminal_preview()`, `render_execute_code_preview()` each prepend prefix to every line |
| 2 | Duration alignment | 3 | Right-aligned at target column; overflow fallback; emoji display-width correctness (`wcswidth`) |
| 2 | Gutter consistency | 2 | All tool output paths produce lines starting with `  ┊ ` |
| 3 | ToolPendingLine | 4 | Single tool: show→replace→commit; concurrent batch: N lines in order, individual replacement, auto-hide on empty |
| 4 | Browse mode | 5 | Escape enters browse; Escape/printable exits; Tab cycles focusable blocks; StatusBar layout switches; browse counter increments |
| 4 | ToolBlock widget | 6 | Mount, write lines, toggle collapsed, verify `display: none`, line count in header, focus ring (`┊`→`┃`) |
| 4 | mount_tool_block() | 3 | Direct mounting via `call_from_thread`; correct body content; collapse threshold (>3 lines) |
| 4 | Copy affordance | 4 | `c` key copies clean plain text; no ANSI/gutter/line-numbers; `⎘`→`✓` flash timer (1.5s); `set_timer` auto-cancel on dismount |
| 5 | CodeBlock + ResponseFlow | 5 | Segmented response: prose→code→prose; code block collapse (>12 lines); expand/toggle; copy extracts raw source; `_flush_block()` returns tuple |
| 6 | OmissionBlock | 4 | Collapsed default; expand shows 5+5 head/tail; ≤12 lines shows all; copy gives full omitted content |
| 6 | Lossless pipeline | 3 | terminal_tool full output preserved; diff sections stored; preview tail stored |
| 7 | StreamingToolBlock | 4 | Mount, stream 10 lines, complete→auto-collapse, duration in header |
| 7 | Backpressure | 3 | 60fps render throttle; 200-line cap with eviction; byte-cap truncation |
| 7 | Auto-scroll + scroll lock | 2 | Scroll up disengages auto-scroll; scroll-to-bottom re-engages; ToolTail shows new-line count |
| 7 | execute_streaming() | 3 | Local env: incremental lines; blocking fallback for unsupported envs; timeout handling |
| 7 | Nested delegation | 2 | Double gutter `┊   ┊` for sub-agents; per-task collapse |
| **Total** | | **65** | |

---

## Out of scope

- Tool output search/filter (e.g., fuzzy-find within a collapsed block). Good idea, separate feature.
- Syntax-aware collapsing (collapse by function, by test suite). Requires semantic parsing of output — too specialized.
- Inline code execution from code blocks (click to run). Security implications, separate spec.
- Image/binary preview in tool output. Requires Textual's image protocol support, separate feature.
