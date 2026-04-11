# Hermes TUI — Capabilities, Status & Roadmap

**Branch:** `feat/textual-migration`  
**Last updated:** 2026-04-11  
**Test suite:** 211 tests, 0 failures

---

## What exists today

### Core architecture

| Component | File | Status |
|---|---|---|
| `HermesApp(App)` — reactive state, queue consumer, theme | `hermes_cli/tui/app.py` | ✅ Complete |
| `OutputPanel` — scrollable, holds all `MessagePanel`s | `hermes_cli/tui/widgets.py` | ✅ Complete |
| `MessagePanel` — per-turn grouping: rule + reasoning + log | `hermes_cli/tui/widgets.py` | ✅ Complete |
| `LiveLineWidget` — streaming in-progress line | `hermes_cli/tui/widgets.py` | ✅ Complete |
| `ToolPendingLine` — in-progress tool activity (single, replaceable) | `hermes_cli/tui/widgets.py` | ✅ Phase 3 |
| `ToolBlock` + `ToolHeader` + `ToolBodyContainer` — collapsible tool output | `hermes_cli/tui/tool_blocks.py` | ✅ Phase 7 |
| `HermesInput` — history (file-backed), autocomplete, masking | `hermes_cli/tui/input_widget.py` | ✅ Complete |
| `StatusBar` — model, context bar, tok/s, duration, browse mode | `hermes_cli/tui/widgets.py` | ✅ Complete |
| `ReasoningPanel` — collapsible reasoning with `▌` gutter | `hermes_cli/tui/widgets.py` | ✅ Complete |
| `CopyableRichLog` — RichLog with plain-text clipboard backing | `hermes_cli/tui/widgets.py` | ✅ Complete |
| Skin/theme engine — CSS variable injection via `get_css_variables()` | `hermes_cli/skin_engine.py` + `app.py` | ✅ Complete |
| Overlay system — clarify, approval, sudo, secret (all with countdown) | `hermes_cli/tui/widgets.py` | ✅ Complete |
| `VoiceStatusBar` — voice recording indicator | `hermes_cli/tui/widgets.py` | ✅ Complete |
| `ImageBar` — attached image list | `hermes_cli/tui/widgets.py` | ✅ Complete |

### Markdown + rich output rendering

The response text pipeline is fully implemented. `agent/rich_output.py` (2359 lines) provides:

| Function | Purpose |
|---|---|
| `apply_inline_markdown(line)` | `**bold**`, `*italic*`, `` `code` ``, `~~strike~~`, `[link](url)` → ANSI |
| `apply_block_line(line)` | Headings (`#`/`##`/`###`), blockquotes (`>`), lists (`-`/`*`/`1.`), `---` hr |
| `render_stateful_blocks(text)` | Pass-2: setext headings, multi-line blockquotes, tables |
| `StreamingBlockBuffer` | Streaming-safe state machine: defers stateful blocks until boundary |
| `StreamingCodeBlockHighlighter` | Syntax-highlighted fenced code blocks (Pygments), streamed incrementally |
| `apply_speculative_inline_md(partial)` | Applies inline markdown to partial tokens without broken span leakage |
| `format_response(text)` | Full non-streaming render (used for `/reason` command output) |

Rendering is enabled behind `_RICH_RESPONSE = True` (import-guarded) in `cli.py:674`. Applied on every response line before `_cprint()`. Works in both PT and TUI modes because the ANSI output is parsed by `Text.from_ansi()` in `LiveLineWidget`.

### Browse mode

Keyboard-driven navigation through all `ToolBlock` widgets in session order:

| Key | Action |
|---|---|
| `Escape` (idle, no overlay, agent stopped) | Enter browse mode |
| `Tab` / `Shift+Tab` | Cycle `ToolHeader` focus (wraps) |
| `Enter` | Toggle collapse state of focused block |
| `c` | Copy plain-text content (OSC 52) + `⎘→✓` flash |
| `Escape` | Exit browse mode |
| Any printable key | Exit browse mode + insert character into input |

`StatusBar` switches to `BROWSE ▸N/T  hint` layout at three width tiers (≥60 / 40–59 / <40).

### Key bindings (always-on)

| Key | Action |
|---|---|
| `ctrl+c` | Copy selected text → cancel overlay (deny) → clear input → exit |
| `ctrl+shift+c` | Interrupt agent (double-press within 2s = force exit) |
| `Escape` | Exit browse mode → cancel overlay (None) → interrupt agent → enter browse mode |
| `Up` / `Down` | History navigation (in input) / overlay choice selection |
| `Tab` / `Shift+Tab` | Autocomplete accept / dismiss; browse mode cycling |

### Browse mode key bindings

| Key | Action |
|---|---|
| `Escape` (idle, no overlay, agent stopped) | Enter browse mode |
| `Tab` / `Shift+Tab` | Cycle `ToolHeader` focus (wraps) |
| `Enter` | Toggle collapse state of focused block |
| `c` | Copy plain-text content (OSC 52) + `⎘→✓` flash |
| `a` | Expand all `ToolBlock`s in the session |
| `A` (shift+a) | Collapse all `ToolBlock`s in the session |
| `Escape` | Exit browse mode |
| Any other printable key | Exit browse mode + insert character into input |

`StatusBar` switches to `BROWSE ▸N/T  hint` layout at three width tiers (≥60 / 40–59 / <40). Full hint (`Tab · Enter · c copy · a expand-all · Esc exit`) shown for first 3 browse visits; compact (`Tab · c · a/A · Esc`) after that.

### Thread → App communication

| Pattern | Used for |
|---|---|
| `app.call_from_thread(setattr, app, attr, value)` | Scalar reactive updates from agent thread |
| `app.write_output(text)` / `app.flush_output()` | Streaming text (via bounded `asyncio.Queue`, 4096 cap) |
| `app.call_from_thread(app.mount_tool_block, label, lines, plain)` | Mount completed tool output block |
| `app.call_from_thread(app.open_reasoning, title)` etc. | Reasoning panel open/append/close |
| `app.call_from_thread(_safe_widget_call, app, ToolPendingLine, method, ...)` | Tool progress line updates |

### Backpressure handling

Queue full → `logger.warning` + `app.status_output_dropped = True` → StatusBar shows `⚠ output truncated` in red. Clears automatically on next successful enqueue.

---

## Known limitations

### Missing: streaming tool output (spec §8, not yet started)

`terminal`, `execute_code`, and `process` tools currently wait for full completion before showing any output. Users stare at a spinner for the full tool duration (potentially minutes).

**Desired behaviour:** Output appears incrementally inside an auto-expanded `StreamingToolBlock` as the command produces it, then collapses when done.

**Why not done yet:** Requires a PTY/pipe reader on the tool-execution side, a `StreamingToolBlock` widget variant that accepts `write()` calls while mounted, and careful backpressure between the PTY reader thread and Textual's event loop. The tool execution layer (`tools/terminal_tool.py`, `tools/code_exec.py`) currently does not expose incremental output — it buffers the entire result before returning. Implementing this requires changes to both the tool execution layer and the TUI.

**See spec:** `specs/tool-output-streamline.md` §8

### Missing: history search

No search within past turns. `Ctrl+R` / `Ctrl+F` from idle input brings up nothing; users scroll manually.

**No spec yet.** See §Future specs below.

### Missing: turn undo / retry

No way to rewind the conversation to before the last turn. After a bad agent response, the user must start a new session or manually roll back any file changes.

**No spec yet.**

### Missing: mouse click-to-toggle on ToolBlocks

Browse mode requires keyboard. Click-to-toggle on a ToolHeader is deferred per the spec (requires hit-testing in the scrollable `OutputPanel`).

### Terminal compatibility caveats

- **OSC 52 clipboard:** Fire-and-forget. Fails silently in Windows Terminal <1.9, some SSH sessions, restricted containers. No capability detection at startup. A `✓` flash after `c` confirms the escape was sent, not that it was received.
- **Truecolor:** StatusBar uses hex colors (`#ffa726`). Rich downsamples gracefully to 256-color but not to 16-color (`TERM=xterm`). No explicit 16-color fallback.
- **Emoji width:** Tool emoji (`✍️`, `📖`, `🔎`) are ZWJ/presentation sequences — render as 2 cells in most terminals, 1 in some East Asian locales. Rich's cell-width calculation handles the common case but not all locale combos.

---

## Architecture risks (load/scale)

| Risk | Threshold | Status |
|---|---|---|
| `CopyableRichLog._plain_lines` unbounded growth | ~5000 turn sessions | Acceptable; no compaction policy planned |
| `_browse_total` reactive — now memoized in `mount_tool_block` | N/A | ✅ Fixed (was O(n) DOM query per keystroke) |
| `on_key` queries `list(self.query(ToolHeader))` per-keypress in browse mode | Sessions with >1000 blocks | Acceptable; Textual's query is O(n) but fast in practice |
| `asyncio.Queue(maxsize=4096)` drop-on-full | Sustained high-throughput output | ✅ Now signals user via StatusBar indicator |
| `call_after_refresh` on detached widget during interrupt | Rare teardown edge case | Low risk; Textual auto-cancels set_interval timers on unmount |

---

## Future specs — not yet written

These are ordered by user impact. Each warrants a standalone spec before implementation.

### SPEC-A: Streaming tool output (`StreamingToolBlock`)
**Impact:** High — eliminates the worst perceived-latency experience (30s command = 30s spinner).  
**Scope:** Tool execution layer (expose incremental output), `StreamingToolBlock` widget (extends `ToolBlock`, accepts `write()` while mounted), backpressure-aware PTY reader thread, auto-collapse on completion.  
**Dependencies:** `tools/terminal_tool.py`, `tools/code_exec.py` must be refactored to yield output incrementally. Consider asyncio subprocess with `communicate()` replaced by stdout line reader.  
**Risk:** Medium-high. PTY wrapping on Linux vs macOS, Windows compatibility unknown.  
**Course of action:** Spec the tool-execution interface first (how incremental output is surfaced), then spec the TUI widget separately. Implement tool side first, gated behind a config flag.

### SPEC-B: History search
**Impact:** High — long sessions with 50+ turns make retrieval painful without search.  
**Scope:** `Ctrl+F` from idle input opens a search overlay (new widget, similar to ClarifyWidget). Typed query filters `MessagePanel` turns by response text match. Navigate matches with `Up`/`Down`, jump-to on `Enter`, dismiss with `Escape`.  
**Dependencies:** Requires full-text index of `CopyableRichLog._plain_lines` per turn. Build lazily on first search.  
**Risk:** Low. Pure display-layer feature; no agent interaction.  
**Course of action:** Write spec, implement as a standalone overlay + `OutputPanel.search(query)` method.

### SPEC-C: Turn undo / retry
**Impact:** Medium-high — recovering from bad agent turns currently requires exiting.  
**Scope:** Store a conversation-state snapshot (messages, files-changed list) before each agent turn. `/undo` command or `ctrl+z` keybinding reverts to the snapshot: restores conversation history, offers to reverse file changes (using stored pre-edit snapshots from `_pending_edit_snapshots`).  
**Dependencies:** Conversation history is already in `self.agent.history`. File-edit snapshots exist via `LocalEditSnapshot`. The main work is plumbing the revert UI.  
**Risk:** Medium. Reverting git-untracked edits is irreversible; need a confirmation overlay.  
**Course of action:** Spec the snapshot model and revert UX first.

### SPEC-D: Mouse click-to-toggle on ToolBlocks
**Impact:** Low-medium — browse mode covers the same use case via keyboard. Mouse adds discoverability.  
**Scope:** `ToolHeader` receives `on_click` → calls `parent.toggle()`. Requires resolving click coordinates to the correct `ToolBlock` within `OutputPanel`.  
**Dependencies:** Textual 8.x click-event routing in `ScrollableContainer` — verify that `on_click` fires correctly on `Widget` children inside a `ScrollableContainer` with `overflow-y: auto`.  
**Risk:** Low. Purely additive.

### SPEC-E: OSC 52 capability detection
**Impact:** Low — affects users in restricted environments.  
**Scope:** At startup, probe terminal clipboard support via a capability query (e.g., `TERM_PROGRAM`, `COLORTERM`, known SSH env vars). Set `_clipboard_supported: bool` on `HermesApp`. If unsupported, the `c` key in browse mode falls back to writing the content to a temp file and showing the path, or prints to the StatusBar.  
**Risk:** Low. Detection is heuristic; no reliable universal method exists.

### SPEC-F: Expand-all / collapse-all in browse mode
**Impact:** Low — convenience for power users.  
**Scope:** `a` key in browse mode expands all `ToolBlock`s in the current turn. `A` (shift+a) collapses all. Currently not implemented; the spec calls for it (tool-output-streamline.md §7.1) but was deferred from the ToolBlock implementation.  
**Risk:** None. Two lines of code + keybinding.  
**Course of action:** No spec needed; implement directly in next browse-mode patch.

---

## Completed spec work

| Spec | Implemented | Tests |
|---|---|---|
| `tool-output-streamline.md` Phases 1–3 (ToolPendingLine, indented blocks, tier system) | ✅ | ~20 tests |
| `tool-output-streamline.md` Phase 7 (ToolBlock, browse mode, StatusBar) | ✅ `tool-block-browse-mode.md` | 28 tests |
| Textual migration (app, widgets, overlays, input, theme) | ✅ `project_textual_migration.md` | 183 tests |
| Markdown/rich output rendering (inline, block, streaming, code highlight) | ✅ (on this branch, `agent/rich_output.py`) | 300+ tests |
| Speculative inline markdown (zero-stall partial flush) | ✅ | 8 tests |
| Clipboard/selection in CopyableRichLog | ✅ | 6 tests |

---

## Quick-win tasks (no spec required)

These can be picked up immediately:

1. ~~**Expand-all / collapse-all** (`a`/`A` in browse mode)~~ ✅ Implemented — `a` expands all, `A` collapses all in browse mode.

2. ~~**Browse-mode `_browse_uses` counter**~~ ✅ Implemented — `_browse_uses: int` on `HermesApp`, incremented in `watch_browse_mode` on entry. `StatusBar` shows full hint for first 3 visits, compact after.

3. **Narrow the bare `except Exception` in `on_mount` guards** — several widgets use `except Exception: pass` where `except NoMatches: pass` is the correct intent. Low risk, small cleanup.

4. ~~**`toggle()` no-op test**~~ ✅ Added — `test_toggle_is_noop_on_small_block`.
