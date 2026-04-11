# Hermes TUI — Capabilities, Status & Roadmap

**Branch:** `feat/textual-migration`  
**Last updated:** 2026-04-11  
**Test suite:** 390 tests, 0 failures

---

## What exists today

### Core architecture

| Component | File | Delivered in |
|---|---|---|
| `HermesApp(App)` — reactive state, queue consumer, theme | `hermes_cli/tui/app.py` | ✅ Complete |
| `OutputPanel` — scrollable, holds all `MessagePanel`s | `hermes_cli/tui/widgets.py` | ✅ Complete |
| `MessagePanel` — per-turn grouping: rule + reasoning + log | `hermes_cli/tui/widgets.py` | ✅ Complete |
| `LiveLineWidget` — streaming in-progress line | `hermes_cli/tui/widgets.py` | ✅ Complete |
| `LiveLineWidget` typewriter animation — `feed()`/`_drain_chars()`/`flush()`; burst compensation; ANSI-atomic split | `hermes_cli/tui/widgets.py` | ✅ `tui-streaming-typewriter.md` |
| `ToolPendingLine` — in-progress tool activity (single, replaceable) | `hermes_cli/tui/widgets.py` | ✅ Phase 3 |
| `ToolBlock` + `ToolHeader` + `ToolBodyContainer` — collapsible tool output | `hermes_cli/tui/tool_blocks.py` | ✅ Phase 7 |
| `StreamingToolBlock` — IDLE→STREAMING→COMPLETED; 60fps flush, 200-line cap, 2kB/line cap | `hermes_cli/tui/tool_blocks.py` | ✅ Phase 7 §8 |
| `ToolTail` — scroll-lock badge `↓ N new lines` | `hermes_cli/tui/tool_blocks.py` | ✅ Phase 7 §8 |
| `OutputPanel._user_scrolled_up` — auto-scroll suppression during streaming | `hermes_cli/tui/widgets.py` | ✅ Phase 7 §8 |
| `HermesInput` — history (file-backed), autocomplete, masking | `hermes_cli/tui/input_widget.py` | ✅ Complete |
| `StatusBar` — model, context bar, tok/s, duration, browse mode | `hermes_cli/tui/widgets.py` | ✅ Complete |
| `ReasoningPanel` — collapsible reasoning with `▌` gutter | `hermes_cli/tui/widgets.py` | ✅ Complete |
| `CopyableRichLog` — RichLog with plain-text clipboard backing | `hermes_cli/tui/widgets.py` | ✅ Complete |
| Skin/theme engine — CSS variable injection via `get_css_variables()` | `hermes_cli/skin_engine.py` + `app.py` | ✅ Complete |
| `skin_loader.py` — JSON/YAML → Textual CSS variable dict (semantic fan-out) | `hermes_cli/tui/skin_loader.py` | ✅ `../../tui-autocomplete-engine-spec.md` |
| Overlay system — clarify, approval, sudo, secret (all with countdown) | `hermes_cli/tui/widgets.py` | ✅ Complete |
| `VoiceStatusBar` — voice recording indicator | `hermes_cli/tui/widgets.py` | ✅ Complete |
| `ImageBar` — attached image list | `hermes_cli/tui/widgets.py` | ✅ Complete |
| `ContextMenu` — right-click overlay (layer:overlay); `MenuItem` dataclass; `_build_context_items` dispatch; `_flash_hint` feedback | `hermes_cli/tui/context_menu.py` | ✅ `tui-context-menu.md` |
| `TteRunner` — `/effects` command; `run_effect()`; TTE suspend via `App.suspend()`; skin gradient | `hermes_cli/tui/tte_runner.py` | ✅ `tui-text-effects.md` |
| `PathSearchProvider` — threaded filesystem walker, batched candidates | `hermes_cli/tui/path_search.py` | ✅ `../../tui-autocomplete-engine-spec.md` |
| `fuzzy_rank` — subsequence ranker with match-span highlighting | `hermes_cli/tui/fuzzy.py` | ✅ `../../tui-autocomplete-engine-spec.md` |
| `VirtualCompletionList` — O(viewport) virtualized list, 10k+ items at 60fps | `hermes_cli/tui/completion_list.py` | ✅ `../../tui-autocomplete-engine-spec.md` |
| `detect_context` — regex trigger dispatcher (/, @, NATURAL) | `hermes_cli/tui/completion_context.py` | ✅ `../../tui-autocomplete-engine-spec.md` |
| `CompletionOverlay` — container: list + preview, glassmorphism | `hermes_cli/tui/completion_overlay.py` | ✅ `../../tui-autocomplete-engine-spec.md` |
| `HistorySuggester` — Fish-style ghost text via native Textual Suggester API | `hermes_cli/tui/history_suggester.py` | ✅ `../../tui-autocomplete-engine-spec.md` |
| `PreviewPanel` — syntax-highlighted file preview, binary sniff, 128KB cap | `hermes_cli/tui/preview_panel.py` | ✅ `../../tui-autocomplete-engine-spec.md` |

### Markdown + rich output rendering

The response text pipeline is fully implemented. `agent/rich_output.py` (2360 lines) provides:

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
| `a` | Expand all `ToolBlock`s in the session |
| `A` (shift+a) | Collapse all `ToolBlock`s in the session |
| `Escape` | Exit browse mode |
| Any other printable key | Exit browse mode + insert character into input |

`StatusBar` switches to `BROWSE ▸N/T  hint` layout at three width tiers (≥60 / 40–59 / <40). Full hint (`Tab · Enter · c copy · a expand-all · Esc exit`) shown for first 3 browse visits (`_browse_uses` counter); compact (`Tab · c · a/A · Esc`) after that.

### Key bindings (always-on)

| Key | Action |
|---|---|
| `ctrl+c` | Copy selected text → cancel overlay (deny) → clear input → exit |
| `ctrl+shift+c` | Interrupt agent (double-press within 2s = force exit) |
| `Escape` | (Priority 0) dismiss completion overlay → exit browse mode → cancel overlay (None) → interrupt agent → enter browse mode |
| `Up` / `Down` | Move highlight in completion list (when open) → history navigation (in input) / overlay choice selection |
| `Tab` | Accept highlighted completion candidate (slash: replace value; @path: splice into text) / browse mode cycling |
| `Shift+Tab` | Dismiss completion overlay / browse mode reverse cycling |

### Autocomplete key bindings

| Key | Context | Action |
|---|---|---|
| `/` at start of input | Any | Opens slash-command completion overlay |
| `@` (preceded by space or start) | Any | Opens path completion overlay with threaded filesystem walker |
| `Up` / `Down` | Completion overlay open | Move highlight; `Up` scrolls history when overlay not open |
| `Tab` | Completion overlay open | Accept highlighted candidate |
| `Escape` | Completion overlay open | Dismiss overlay (Priority 0 — fires before any other escape handler) |
| Ghost text (right-side) | History match | Press `→` or `End` to accept Fish-style suggestion |
| `Enter` | Any | Submit input as typed — NEVER auto-accepts highlighted candidate |

### Thread → App communication

| Pattern | Used for |
|---|---|
| `app.call_from_thread(setattr, app, attr, value)` | Scalar reactive updates from agent thread |
| `app.write_output(text)` / `app.flush_output()` | Streaming text (via bounded `asyncio.Queue`, 4096 cap) |
| `app.call_from_thread(app.mount_tool_block, label, lines, plain)` | Mount completed tool output block |
| `app.call_from_thread(app.open_reasoning, title)` etc. | Reasoning panel open/append/close |
| `app.call_from_thread(app.open_streaming_tool_block, tool_call_id, label)` | Begin a `StreamingToolBlock` (IDLE→STREAMING) |
| `app.call_from_thread(app.append_streaming_line, tool_call_id, line)` | Append a line to an active `StreamingToolBlock` |
| `app.call_from_thread(app.close_streaming_tool_block, tool_call_id, duration_str)` | Finalize a `StreamingToolBlock` (STREAMING→COMPLETED) |
| `app.call_from_thread(_safe_widget_call, app, ToolPendingLine, method, ...)` | Tool progress line updates |

### Backpressure handling

Queue full → `logger.warning` + `app.status_output_dropped = True` → StatusBar shows `⚠ output truncated` in red. Clears automatically on next successful enqueue.

---

## Known limitations

### Missing: nested delegation streaming (step 26)

`delegate_task` sub-agent tool activity does not yet stream into a nested `StreamingToolBlock` with a doubled gutter (`┊   ┊`). The outer agent's streaming works; sub-agent output accumulates and collapses as before.

**See spec:** `specs/tool-output-streamline.md` §8.6. Deferred — additive, lower priority.

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
| `StreamingToolBlock._flush_pending` 60fps `set_interval` timer | One timer per active streaming block | Low risk; Textual auto-cancels on unmount; typically ≤3 concurrent |

---

## Specs written, not yet implemented

_All specs have been implemented. See "Completed spec work" below._

---

## Future specs — not yet written

These are ordered by user impact. Each warrants a standalone spec before implementation.

### ~~SPEC-A: Streaming tool output (`StreamingToolBlock`)~~ ✅ IMPLEMENTED 2026-04-11
**Impact:** High — eliminates the worst perceived-latency experience (30s command = 30s spinner).  
**Status:** Done. Steps 21–25 of `specs/tool-output-streamline.md` §8. Step 26 (nested delegation) deferred.  
**What was built:** `execute_streaming()` on `BaseEnvironment` + `LocalEnvironment`; `StreamingToolBlock` widget (IDLE→STREAMING→COMPLETED); 60fps flush timer; 200-line visible cap; 2 kB/line byte cap; `_user_scrolled_up` scroll lock on `OutputPanel`; ContextVar streaming callback in `terminal_tool.py`; `open_streaming_tool_block` / `append_streaming_line` / `close_streaming_tool_block` on `HermesApp`; wired from `cli.py` `_on_tool_start` / `_on_tool_complete`. 22 new tests.

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

---

## Completed spec work

| Spec | Implemented | Tests |
|---|---|---|
| `tool-output-streamline.md` Phases 1–3 (ToolPendingLine, indented blocks, tier system) | ✅ | ~20 tests |
| `tool-output-streamline.md` Phase 4 (ToolBlock, browse mode, StatusBar) | ✅ `tool-block-browse-mode.md` | 28 tests |
| `tool-output-streamline.md` Phase 7 §8 steps 21–25 (StreamingToolBlock, execute_streaming, backpressure, scroll lock, terminal wiring) | ✅ 2026-04-11 | 11 tests (`test_streaming_tool_block.py`) |
| Textual migration (app, widgets, overlays, input, theme) | ✅ `../../textual-migration.md` | 183 tests |
| Markdown/rich output rendering (inline, block, streaming, code highlight) | ✅ (on this branch, `agent/rich_output.py`) | 300+ tests |
| Speculative inline markdown (zero-stall partial flush) | ✅ | 8 tests |
| Clipboard/selection in CopyableRichLog | ✅ | 10 tests |
| `tui-context-menu.md` — right-click overlay, `_build_context_items` dispatch, copy/paste feedback, `_flash_hint` | ✅ 2026-04-11 | 21 tests |
| `tui-text-effects.md` — `/effects` command, `TteRunner`, `run_effect()`, skin gradient, `App.suspend()` integration | ✅ 2026-04-11 | 12 tests |
| `tui-streaming-typewriter.md` — `LiveLineWidget.feed()` typewriter animation, `_drain_chars()`, burst compensation, ANSI-atomic split, `flush()` | ✅ 2026-04-11 | 17 tests |
| `tui-animation-novel-techniques.md` — `animation.py` (`lerp`, `ease_*`, `pulse_phase`, `lerp_color`, `PulseMixin`); `ThinkingWidget` skeleton shimmer; `MessagePanel` fade-in; non-typewriter blink cursor; `StatusBar` pulse + animated tok/s counter + compaction lerp; `AnimatedCounter` widget | ✅ 2026-04-11 | 49 new tests (390 total) |

---

## Quick-win tasks (no spec required)

These can be picked up immediately:

1. ~~**Expand-all / collapse-all** (`a`/`A` in browse mode)~~ ✅ Implemented — `a` expands all, `A` collapses all in browse mode.

2. ~~**Browse-mode `_browse_uses` counter**~~ ✅ Implemented — `_browse_uses: int` on `HermesApp`, incremented in `watch_browse_mode` on entry. `StatusBar` shows full hint for first 3 visits, compact after.

3. **Narrow the bare `except Exception` in `on_mount` guards** — several widgets use `except Exception: pass` where `except NoMatches: pass` is the correct intent. Low risk, small cleanup.

4. ~~**`toggle()` no-op test**~~ ✅ Added — `test_toggle_is_noop_on_small_block`.
