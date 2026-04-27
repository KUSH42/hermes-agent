# Streaming + Typewriter Pipeline Audit — 2026-04-25

**Status:** DRAFT
**Branch:** feat/textual-migration
**Scope:** Read-only audit. No code edits performed.
**Method:** Three parallel Explore agents covering ingress / typewriter / sinks. Findings consolidated, deduplicated, and re-ranked here.

---

## Coverage map

| Area | Modules audited |
|---|---|
| **Ingress** | `response_flow.py`, `services/io.py`, `services/tools.py` (append paths), `ReasoningFlowEngine`, axis-bus transitions |
| **Typewriter** | `widgets/renderers.py` (LiveLineWidget, CharacterPacer), `write_file_block.py`, `execute_code_block.py`, `widgets/thinking.py`, `app.py` reduced-motion wiring |
| **Sinks** | `widgets/__init__.py` (OutputPanel mount order), `widgets/message_panel.py` (MessagePanel, ReasoningPanel, child buffer), `widgets/renderers.py` (CopyableRichLog, LiveLineWidget render path), `tool_blocks/_block.py` + `_streaming.py`, `body_renderers/streaming.py`, `body_renderers/base.py` |

---

## HIGH severity

### H1 — Silent exception swallow in IOService consume loop
- **File:** `hermes_cli/tui/services/io.py:107-108`
- **Problem:** `consume_output()` wraps `engine.feed()` in `except Exception: pass` with no logger, no comment. Any engine bug becomes an invisible stream stall on a single chunk.
- **Fix:** `except Exception: logger.exception("engine.feed failed"); continue`. Project rule (`.claude/CLAUDE.md` "See log for details" contract) forbids bare swallow.
- **Test:** Inject a feed that raises on second chunk; assert log captured with `exc_info`, stream continues.

### H2 — Race: append_tool_output → append_streaming_line drops final chunk
- **File:** `hermes_cli/tui/services/tools.py:1149-1161`
- **Problem:** View state checked at line 1153 but block can be popped from `_active_streaming_blocks` between the check and the `append_streaming_line` call (line 1161). Final chunk lands on a stale handle and is silently dropped at the terminal boundary.
- **Fix:** Re-fetch block after axis transition; if `block is None or view.state in (DONE, ERROR, CANCELLED)`, drop with debug log instead of silent return.
- **Test:** Force `complete_tool_call` between the two lines via threaded race harness; assert no chunk is silently lost (either delivered to live block or logged as drop).

### H3 — Silent prose-callback swallow in `_write_prose`
- **File:** `hermes_cli/tui/response_flow.py:609-612`
- **Problem:** Callback exceptions swallowed bare. Lost prose lines or corrupt downstream state are invisible.
- **Fix:** `logger.exception("prose_callback failed")`. Same pattern repeats at `response_flow.py:1026-1030` (emoji prose render) and `:1072-1075` (emoji mount) — fix all three.
- **Test:** Wire a callback that raises on second invocation; assert log emitted, subsequent lines still attempted.

### H4 — LiveLineWidget bypasses ResponseFlowEngine when engine is None
- **File:** `hermes_cli/tui/widgets/renderers.py:389-397` (`_commit_lines`)
- **Problem:** When `msg._response_engine is None`, lines are committed directly, bypassing classifier/dispatch. If the engine initializes mid-stream, partial lines already committed are orphaned and never re-routed; mid-stream Code/Markdown blocks silently lose content.
- **Fix:** Defer commitment until engine is non-None. Either pre-allocate engine in `__init__` (no-op until first chunk) or buffer until mount completes.
- **Test:** Drive feed before engine is wired; assert lines either buffered or warned, never silently dropped.

### H5 — OutputPanel mount-order trio violation in `new_message`
- **File:** `hermes_cli/tui/widgets/__init__.py:373`
- **Problem:** `new_message()` mounts MessagePanel before querying the trio anchor. Spec contract (see `reference_output_panel_mount_order`): trio `[ToolPendingLine?, ThinkingWidget, LiveLineWidget]` must always be the last three children. Current sequence allows MessagePanel to mount between ThinkingWidget and LiveLineWidget under racy compose timing.
- **Fix:** Always mount with `before=tool_pending` (or `before=thinking_widget` when no pending). Assert invariant in test.
- **Test:** Add a property test: after any combination of `new_message` / `new_tool_pending` / `start_thinking`, the last three children are exactly the trio in expected order.

### H6 — StreamingToolBlock `_flush_pending` drops batch on NoMatches
- **File:** `hermes_cli/tui/tool_blocks/_streaming.py:474-479`
- **Problem:** If `_cached_body_log` is None and `_body.query_one(CopyableRichLog)` raises `NoMatches`, `_flush_pending()` silently returns. Pending lines are dropped — not re-queued. After NoMatches, all subsequent chunks until completion are lost.
- **Fix:** On NoMatches, log warning and re-prepend the batch into `_pending` for retry on next flush. Cap retries; if widget never appears, drop with `_log.exception` and mark block as broken.
- **Test:** Mount a StreamingToolBlock without its body widget; feed three chunks; after body mounts, assert all three chunks are visible.

### H7 — Reduced-motion ignored by LiveLineWidget cursor blink
- **File:** `hermes_cli/tui/widgets/renderers.py:415-443` (no `has_class("reduced-motion")` check)
- **Problem:** Reduced-motion is honored in `WriteFileBlock` (`write_file_block.py:92`) and `ThinkingWidget` (`thinking.py:343`) but not in LiveLineWidget. Blink timer fires unconditionally if `_cursor_blink_enabled()` returns True. Accessibility regression.
- **Fix:** Check `self.app.has_class("reduced-motion")` in `on_mount`; skip blink timer creation when set.
- **Test:** App with `reduced-motion` class → assert LiveLineWidget never schedules a blink timer.

### H8 — CharacterPacer cadence drift on burst
- **File:** `hermes_cli/tui/widgets/renderers.py:480-492` (`_drain_chars`)
- **Problem:** Burst compensation drains up to `burst*2` chars with `await asyncio.sleep(0)`. Under sustained fast streaming, the next tick re-enters before any real delay elapses; user sees visible acceleration rather than the configured 120cps.
- **Fix:** Switch to deadline-based scheduling using `time.monotonic()`. Track `next_emit_at`; sleep to deadline; never compensate by yielding zero.
- **Test:** Synthetic feed of 1000 chars in 100ms with `cps=120`; assert observed reveal duration ≥ ~8.3s ± tolerance, never compresses below.

### H9 — CharacterPacer init race in WriteFileBlock
- **File:** `hermes_cli/tui/write_file_block.py:72-101` vs `:156`
- **Problem:** Pacer constructed in `on_mount` after extractor allocation. `feed_delta` may be called from streaming thread before `on_mount` completes; on `self._pacer is None`, `feed_delta` returns early at line 156 — pending content silently dropped.
- **Fix:** Pre-allocate a no-op CharacterPacer (cps=0, queue-only) in `__init__` and replace in `on_mount`; OR guard `feed_delta` with a future that resolves after `on_mount`. Never silently drop.
- **Test:** Construct WriteFileBlock and call `feed_delta` before mounting. Then mount. Assert content is visible.

### H10 — ThinkingWidget `_LabelLine` lock not shared across redraws
- **File:** `hermes_cli/tui/widgets/thinking.py:209` vs `:419` vs `:448`
- **Problem:** `activate()` allocates `threading.Lock()` and passes it into the STARTED `_LabelLine`, but the WORKING-phase swap allocates a **new** Lock instance instead of forwarding the original. Stream-effects renderer thread races against the redraw with no real mutual exclusion.
- **Fix:** Store the lock on `self._effects_lock` in `activate()`; reuse it for every `_LabelLine` constructed during this activation cycle.
- **Test:** Concurrent `set_label` and reveal-tick drive; assert no torn frames (Rich text not partially rebuilt).

---

## MEDIUM severity

### M1 — Footnote/citation/math buffers unbounded
- **File:** `response_flow.py:568-576` (footnote, citation), `:857` (math), `:1260` (code-fence numbered buffer)
- **Problem:** No size cap on `_footnote_defs`, `_cite_entries`, `_math_lines`, `_code_fence_buffer`. Pathological agent output can balloon RAM until flush.
- **Fix:** Add per-buffer cap (suggest 500 / 500 / 10000 / 500). On overflow: `_log.warning`, drop subsequent appends (or transition state machine out of the buffering branch). Capacity values belong as module constants.
- **Test:** Drive 600 footnote lines in one turn; assert log emitted, memory bounded.

### M2 — `replace_body_widget` not atomic with finalize
- **File:** `tool_blocks/_block.py:312-326`
- **Problem:** Iterates `_body.query(BodyFooter)` and removes in place. If `finalize()` is racing on another path (rare but possible during streaming → terminal swap), query handles can be stale → double-remove exception or orphaned DOM.
- **Fix:** Single-pass atomic replace: capture children list, clear body, mount the new widget. No iteration over a live query during mutation. Add module-level lock if multi-thread entry is possible.
- **Test:** Force concurrent replace + finalize via test harness; assert no exception, body in expected terminal shape.

### M3 — `StreamingBodyRenderer.render_stream_line` has no exception contract
- **File:** `body_renderers/base.py:77-82`, dispatch site in `services/tools.py` (`append_streaming_line`)
- **Problem:** Renderer override may raise (malformed regex, OOM on Syntax init). Dispatch does not wrap → exception escapes to event loop, crashes that chunk batch.
- **Fix:** Wrap dispatch in `try/except Exception` with `_log.exception`; emit a fallback `Text(line, style="dim red")` so user sees the line even if styling failed.
- **Test:** Renderer that raises on every other line; assert visible fallback, no event-loop crash, log captured.

### M4 — `ReasoningPanel.append_delta` calls `refresh(layout=True)` per chunk
- **File:** `widgets/message_panel.py:213`
- **Problem:** Every delta forces a layout reflow. At 10 tok/s, that's 10 layout passes/sec — compositor cache thrash, O(N children) recompute. Visible perf cliff during reasoning streams with many siblings.
- **Fix:** Only `refresh(layout=True)` when `_deferred_renders` non-empty (line 205-206 already gates the conditional render). For pure text-append cases, `refresh()` (no layout) suffices. Or batch via `call_after_refresh`.
- **Test:** Perf instrumentation (PM-01 hooks): assert layout reflows / second under streaming ≤ a small constant (e.g. 5).

### M5 — MessagePanel child-buffer flush deferred and racy
- **File:** `widgets/message_panel.py:409-414` (`_mount_nonprose_block`)
- **Problem:** Child blocks arriving before parent SubAgentPanel are buffered then flushed via `call_after_refresh`. If a second child arrives before flush, both queue independently. If parent mounts mid-buffer, insertion order can be violated.
- **Fix:** Coalesce: flush synchronously when parent mounts. Or schedule a single flush task that drains the buffer in arrival order in one pass.
- **Test:** Drive parent mount + 3 children with interleaved timings; assert child order matches arrival order.

### M6 — Block pointer stale across terminal transition
- **File:** `services/tools.py:426-429` (`append_streaming_line`)
- **Problem:** Block fetched at 426; meanwhile `_terminalize_tool_view` (line 644) can pop the view. The chunk lands on the popped block.
- **Fix:** Re-check `view.state not in {DONE, ERROR, CANCELLED}` after fetching; on terminal, log debug and drop.
- **Test:** Race terminalize vs append; assert no panic, drop logged.

### M7 — Reveal/cancel timer leak on interrupt
- **File:** `tool_blocks/_streaming.py:264-276` vs WriteFileBlock + ExecuteCodeBlock pacer
- **Problem:** `on_unmount` stops `_render_timer`, `_spinner_timer`, `_duration_timer`, but WriteFileBlock/ExecuteCodeBlock each own a CharacterPacer whose internal `app.set_interval` timer is only stopped in `complete()`. Interrupt before complete → orphan timer fires until app teardown.
- **Fix:** Override `on_unmount` in WriteFileBlock + ExecuteCodeBlock to call `pacer.stop()`. Or have base `on_unmount` walk known pacer attrs.
- **Test:** Mount, feed partially, unmount mid-stream; assert no callbacks fire after unmount.

### M8 — ThinkingWidget activate-without-deactivate orphans timer
- **File:** `widgets/thinking.py:307-318`
- **Problem:** `activate()` checks `_timer is not None` but doesn't enforce mode/state consistency. Repeat `activate` calls without intervening `deactivate` orphans the previous timer.
- **Fix:** Always stop the existing timer at the top of `activate()` before re-creating.
- **Test:** Two consecutive activates; assert exactly one timer is alive at any moment.

### M9 — `CopyableRichLog.write` width fallback assumes layout
- **File:** `widgets/renderers.py:150-166`
- **Problem:** Pre-layout, `app.size.width` may be 0; fallback wraps text at ~15 chars, then reflows when layout completes. Double-render perf cliff and visible reflow flash.
- **Fix:** Cache width on first non-zero `self.size.width` in `on_mount`. Defer the first write until post-layout (`call_after_refresh`).
- **Test:** Mount and write before layout; assert no wrap at <20 chars when layout completes.

### M10 — `StreamingSearchRenderer._last_emitted_path` carries across calls
- **File:** `body_renderers/streaming.py:482`
- **Problem:** Instance attribute not reset between sequential search-tool invocations on the same renderer instance. Stale path header can render at the start of the next call.
- **Fix:** Reset in `__init__` and explicitly in `finalize()` (or wherever the lifecycle marks end-of-call).
- **Test:** Drive two search calls through one renderer instance; assert path header semantics correct on both.

### M11 — IOService swallow lacks justification comment
- **File:** `services/io.py:100-108`
- **Problem:** Even after fixing H1, the inner try/except in the per-chunk loop should carry a one-line comment ("swallow-and-continue to keep stream alive after malformed chunk").
- **Fix:** Add comment per project `.claude/CLAUDE.md` exception-handling rules.

---

## LOW severity

### L1 — `_DIFF_HEADER_RE` / `_DIFF_ARROW_RE` duplicated
- **File:** `body_renderers/streaming.py:244-248` vs `tool_blocks/_shared.py`
- **Fix:** Single source. Import from `_shared`. Risk: streaming and post-completion diff parsing drifting.

### L2 — `LiveLineWidget._blink_visible` not reset on remount
- **File:** `widgets/renderers.py:510`
- **Fix:** Reset in `on_mount`, not just in `flush`.

### L3 — Orphaned-CSI strip can shift color boundaries
- **File:** `widgets/renderers.py:361` (`_ORPHANED_CSI_RE`)
- **Fix:** Lookahead-validate ESC sequences before stripping; log dropped sequences at debug.

### L4 — `StreamingToolBlock.complete` double-stops timers
- **File:** `tool_blocks/_streaming.py:283-287`
- **Fix:** Idempotency guard via `_timers_stopped` flag, or move all timer cleanup to `on_unmount` only.

### L5 — `FileRenderer.render_stream_line` silent syntax-fail fallback
- **File:** `body_renderers/streaming.py:292-302`
- **Fix:** `_log.debug` the lexer/syntax failure with line number; show fallback marker in dim style.

### L6 — `_detached` flag not lock-protected
- **File:** `response_flow.py:635, 899`
- **Fix:** Document single-consumer guarantee in module docstring; OR add `threading.Lock`. Currently latent, not active.

### L7 — Logger declaration position
- **File:** `response_flow.py:152`
- **Fix:** Move logger to module top (after imports), per `tui-development` skill convention.

### L8 — Reduced-motion config double-read
- **File:** `app.py:779-784`
- **Fix:** Resolve env vs config once in `__init__`; `add_class("reduced-motion")` exactly once based on resolved value.

### L9 — `flush_live` deactivate vs reveal-drain race
- **File:** `widgets/__init__.py:413-444`
- **Fix:** Await `tw.deactivate` to fully settle (timer gone) before calling `live.flush`.

### L10 — `reveal_lines` runs on possibly-unmounted ExecuteCodeBlock OutputSection
- **File:** `execute_code_block.py:527-531`
- **Fix:** Guard with `self.is_mounted` check; cache log handle only when mounted, clear on unmount.

### L11 — Tests don't exercise queue-overflow path
- **File:** `tests/tui/test_typewriter.py:63-74, 213-227`
- **Fix:** Add a test pumping ≥ 5000 chars through `feed()` to exercise `_TW_CHAR_QUEUE_MAX` (4096) full-flush path. Validate no chars lost.

---

## Cross-cutting themes

1. **Exception swallowing remains the #1 risk surface.** `services/io.py:107`, `response_flow.py:609/1026/1072`, `body_renderers/base.py` dispatch — same pattern repeated. A single sweep applying the project rule (re-raise / log-with-`exc_info` / explicit comment) closes 4 HIGH and 1 MED in one pass.

2. **Mount-order contract is documented but not enforced.** H5 and the OutputPanel trio invariant are exactly the kind of property that should ship with a test asserting last-three-children. Add the property test once, prevent recurrence forever.

3. **Pacer + timer lifecycle is not centralized.** WriteFileBlock, ExecuteCodeBlock, ThinkingWidget, LiveLineWidget all manage their own timer/pacer. H8/H9/M7/M8/L4 are all variants of the same defect class. A `ManagedTimer` mixin or a single base-class `on_unmount` walking declared timer attrs would collapse the surface.

4. **Reduced-motion is per-widget rather than honored as a global gate.** H7 and L8 are both consequences. Fix: a single `app.is_reduced_motion()` query routed through a service, with widgets reading at mount time and re-checking on theme change.

5. **No reorder/double-emit found in the streaming path.** Chunk order is preserved by single-consumer queues; `_LineClassifier` state machine prevents duplicate dispatch. The risk profile is loss (drops) and corruption (silent fallback), not duplication.

---

## Suggested implementation order

If converted to specs, priority sequence:

1. **Spec A — Exception sweep** (H1, H3, H4, M3, M11): one mechanical sweep, low risk, high signal. ~10 tests.
2. **Spec B — Mount-order + axis race** (H2, H5, H6, M2, M5, M6): correctness fixes on the chunk → block path. ~20 tests.
3. **Spec C — Timer/pacer lifecycle unification** (H8, H9, H10, M7, M8, L4, L9, L10): the structural one. Likely a small base class refactor. ~25 tests.
4. **Spec D — Reduced-motion gate** (H7, L8): config-only, small. ~6 tests.
5. **Spec E — Buffer caps + perf** (M1, M4, M9, M10): defensive. ~12 tests.
6. **Spec F — Polish** (L1, L2, L3, L5, L6, L7, L11): grouped cleanup. ~8 tests.

Estimated total: ~80 tests across 6 specs. None individually exceed the project's ~35-test split threshold.

---

## Out of scope (not investigated)

- Splash / startup banner reveal — covered by `project_startup_banner_polish.md` (IMPLEMENTED 2026-04-23). Not re-audited.
- Tool render visual grammar — covered by recent grammar/code/json/table/log specs. Not re-audited.
- Renderer registry dispatch correctness — covered by R-2A / R-2B. Audit assumed registry behavior is correct.
