# Streaming Pipeline Hardening (SPEC-STR)

**Status:** DRAFT
**Date:** 2026-05-02
**Branch base:** `feat/textual-migration`
**Addresses:** STREAM-FENCE-LEAK, STREAM-PARTIAL-DETACH, STREAM-FOOTNOTE-CAP, STREAM-PARTIAL-CSI-LOSS, STREAM-FENCE-FLUSH-CODE, STREAM-REASONING-RACE, STARTUP-BANNER-RACE, CONTENT-CLASSIFY-NO-TIMEOUT, PARTIAL-JSON-UNICODE-RECOVERY, STREAM-CITE-STATE, PROSE-DOUBLE-EMIT-DEBUG, CACHE-INVALIDATE-FOR-RESIZE, EXEC-CURSOR-TIMER-SWALLOW, TTE-CACHE-LOAD-SWALLOW
**Test file:** `tests/tui/test_streaming_hardening.py`
**Estimated tests:** 28

---

## Summary

The streaming pipeline (`response_flow.py`, `partial_json.py`, `content_classifier.py`, `inline_prose.py`, plus the TTE startup gate) has accumulated lifecycle bugs across 14 distinct sites. The dominant root cause: **fence/partial/timer state spans 4 owners** for one open code fence — `ResponseFlowEngine._fence_opened_at`, `StreamingCodeBlock`, `CharacterPacer._timer`, header `ManagedTimerMixin` trackers — each path resets only what it knows. This spec consolidates fence-timer ownership into one place, fixes the silent-data-loss spots (orphaned CSI, footnote cap, citation overflow, bad `\uXXXX`), and tightens the TTE startup race.

---

## STR-1 — `_fence_opened_at` unconditional reset on state-change paths (closes STREAM-FENCE-LEAK, STREAM-FENCE-FLUSH-CODE)

### Problem

`response_flow.py:911-913` (`_handle_unknown_state`) and `response_flow.py:1254-1258` (`flush()` non-`IN_CODE` branches) conditionally clear `_fence_opened_at`. If reached while `IN_CODE`, the timer leaks; next `[STREAM-FENCE]` log computes negative/stale `elapsed_ms`.

### Fix

Encapsulate fence state behind a small helper:

```python
def _reset_fence_state(self) -> None:
    """Drop fence-timer + per-fence buffers. Idempotent. Safe from any state."""
    self._fence_opened_at = None
    self._fence_lang = None
    # any other per-fence tracking
```

Call this unconditionally at:
- Top of `_handle_unknown_state`.
- `flush()` non-`IN_CODE` branches.
- End of `_close_fence` path (already does it; verify).
- `feed()` `_detached` early-return (also clears any partial state).

### Tests (4)

- `test_fence_state_reset_in_unknown_state`
- `test_fence_state_reset_in_flush_indented_code_branch`
- `test_fence_elapsed_log_never_negative`
- `test_reset_fence_state_idempotent`

---

## STR-2 — `feed()` partial dispatch checks `is_mounted` (closes STREAM-PARTIAL-DETACH)

### Problem

`response_flow.py:701-711`. `feed()` returns early on `_detached`, but `_route_partial(active_block.feed_partial)` can race if panel unmounts between entry and dispatch. Crash: `feed_partial` on unmounted `StreamingCodeBlock`.

### Fix

```python
def _route_partial(self, fn) -> None:
    block = self._active_block
    if block is None or not getattr(block, "is_mounted", True):
        return
    try:
        fn(self._partial)
    except Exception:
        _log.exception("_route_partial: %r raised on unmounted/detached block", fn)
        self._reset_fence_state()
        self._active_block = None
```

### Tests (2)

- `test_route_partial_skips_unmounted_block`
- `test_route_partial_logs_and_clears_on_exception`

---

## STR-3 — Footnote cap doesn't poison continuations (closes STREAM-FOOTNOTE-CAP)

### Problem

`response_flow.py:744-746`. When `len(_footnote_defs) >= _MAX_FOOTNOTES`, the new-entry branch early-returns without updating `_footnote_def_open`. The next continuation line (line 745) appends to `self._footnote_defs[self._footnote_def_open]` — possibly the wrong (stale) label.

### Fix

```python
if len(self._footnote_defs) >= self._MAX_FOOTNOTES:
    _log.warning("footnote cap %d hit; dropping new ref %r", self._MAX_FOOTNOTES, label)
    self._footnote_def_open = None  # critical: continuations no longer routed
    return
```

### Tests (2)

- `test_footnote_cap_clears_open_label`
- `test_continuation_after_cap_does_not_misroute`

---

## STR-4 — Orphaned-CSI suppression logs at debug (closes STREAM-PARTIAL-CSI-LOSS)

### Problem

`response_flow.py:709-711`. `_ORPHANED_CSI_RE.sub("", self._partial)` removes CSI tokens silently. If `clean` becomes empty when `_partial` is non-empty, user sees nothing flow until the line completes — no log.

### Fix

```python
clean = _ORPHANED_CSI_RE.sub("", self._partial)
if clean != self._partial:
    _log.debug("[STREAM-BUF] orphan-CSI suppressed: len=%d → %d", len(self._partial), len(clean))
self._partial = clean
```

### Tests (1)

- `test_orphan_csi_suppression_logs_when_size_changes`

---

## STR-5 — `ReasoningFlowEngine._init_fields` wraps `get_css_variables` (closes STREAM-REASONING-RACE)

### Problem

`response_flow.py:1591-1617`. `_app_b1.get_css_variables()` invoked before `hasattr` check on real path; theme corruption raises and engine init fails uncaught.

### Fix

```python
try:
    css_vars = app_b1.get_css_variables() or {}
except Exception:
    _log.exception("ReasoningFlowEngine: get_css_variables failed; defaulting to empty")
    css_vars = {}
```

### Tests (1)

- `test_reasoning_engine_init_logs_on_css_var_failure_and_defaults_empty`

---

## STR-6 — TTE startup race: producer re-checks ready inside `call_from_thread` (closes STARTUP-BANNER-RACE)

### Problem

`STARTUP_BANNER_READY` (set in StartupBannerWidget.on_mount, cleared in on_unmount) is racy: if widget unmounts between `wait(2.0)` returning True and the producer reaching `query_one(StartupBannerWidget)`, query fails.

### Fix

Producer worker:

```python
def _set_frame_safely(self, frame):
    if not STARTUP_BANNER_READY.is_set():
        _log.debug("TTE producer: banner ready flag cleared mid-frame")
        return
    try:
        widget = self.app.query_one(StartupBannerWidget)
    except NoMatches:
        _log.debug("TTE producer: StartupBannerWidget gone")
        return
    widget.set_frame(frame)
```

Producer dispatches via `call_from_thread(self._set_frame_safely, frame)`.

Also extract `StartupBannerWidget` from `widgets/__init__.py:812-870` into its own file `widgets/startup_banner.py` to enable targeted import without dragging the whole module. (Done as part of this fix because the module is becoming a kitchen sink.)

### Tests (3)

- `test_set_frame_skips_when_ready_cleared`
- `test_set_frame_handles_nomatches`
- `test_startup_banner_widget_imports_from_dedicated_module`

---

## STR-7 — `classify_content` 50ms enforcement + length cap (closes CONTENT-CLASSIFY-NO-TIMEOUT)

### Problem

`content_classifier.py:39-140`. No 50ms timeout enforcement (memory entry SC-9 mentions one but it's not present). `json.loads` on full text (could be MB); regex `re.findall(r"^\s*\d+[:\-]\s")` no length cap. `lru_cache(maxsize=32)` may pin large strings.

### Fix

1. **Length cap** — at function entry, `text = text[:_CLASSIFY_MAX_BYTES]` where `_CLASSIFY_MAX_BYTES = 65536`.
2. **Timeout** — wrap the heavy paths (json.loads, regex.findall) in a deadline check using `time.monotonic()`. If the cumulative elapsed exceeds 50ms, return `ClassificationResult(kind=TEXT, confidence=0.0, reason="timeout")` and `_log.warning("classify_content: 50ms budget exceeded for %d-byte payload", len(text))`.
3. **Cache pinning** — replace `lru_cache(maxsize=32)` with a manual dict keyed on `hash(text[:1024])` rather than full text; size-bound to 32 entries.

### Tests (4)

- `test_classify_content_truncates_at_64k`
- `test_classify_content_returns_text_on_timeout`
- `test_classify_content_logs_when_budget_exceeded`
- `test_classify_cache_does_not_pin_large_strings`

---

## STR-8 — `partial_json` bad `\uXXXX` logs warning (closes PARTIAL-JSON-UNICODE-RECOVERY)

### Problem

`partial_json.py:130-133`. On `int(self._unicode_buf, 16)` ValueError, four hex chars are appended verbatim — looks like real text but is wrong. No log.

### Fix

```python
try:
    code = int(self._unicode_buf, 16)
    out.append(chr(code))
except ValueError:
    _log.warning("partial_json: bad \\u escape %r — emitting literal", self._unicode_buf)
    out.append("\\u" + self._unicode_buf)  # explicitly literal, not garbled
```

### Tests (2)

- `test_partial_json_bad_unicode_escape_logs_warning`
- `test_partial_json_bad_unicode_emits_literal_not_garbled`

---

## STR-9 — Citation overflow surfaces user-visible OmissionBar (closes STREAM-CITE-STATE)

### Problem

`response_flow.py:755-760`. Citations dropped past `_MAX_CITATIONS`; logs warning, but user-visible result is silently missing footnote refs.

### Fix

In `_mount_sources_bar`, render an OmissionBar-style "+N more sources truncated" line when `_dropped_citation_count > 0`:

```python
if self._dropped_citation_count > 0:
    sources_bar.append_omission(f"+{self._dropped_citation_count} more sources truncated")
```

`_dropped_citation_count` is incremented on each cap-hit drop.

### Tests (2)

- `test_citation_overflow_increments_drop_counter`
- `test_sources_bar_renders_omission_when_drops_present`

---

## STR-10 — Prose DOUBLE-EMIT debug skips blank lines (closes PROSE-DOUBLE-EMIT-DEBUG)

### Problem

`response_flow.py:667-672`. `_last_prose_plain` lives on engine forever; legitimate repeats (blank-line spacers) all log as DOUBLE-EMIT, polluting debug logs.

### Fix

```python
if plain.strip() == "":
    return  # blank repeats are legit; don't log
if plain == self._last_prose_plain:
    _log.debug("[STREAM-PROSE] DOUBLE-EMIT %r", plain[:80])
self._last_prose_plain = plain
```

Also reset `self._last_prose_plain = None` at top of `flush()` so cross-turn boundaries don't false-positive.

### Tests (2)

- `test_double_emit_skips_blank_lines`
- `test_double_emit_resets_on_flush`

---

## STR-11 — `InlineImageCache.invalidate_for_resize` snapshots keys + wraps cell_px (closes CACHE-INVALIDATE-FOR-RESIZE)

### Problem

`inline_prose.py:171-180`. Loops over `self._entries` while computing `_cell_px()`. If `_cell_px()` raises during teardown, partial mutation leaves dangling Kitty image IDs.

### Fix

```python
def invalidate_for_resize(self) -> None:
    keys = list(self._entries.keys())  # snapshot
    try:
        cell = self._cell_px()
    except Exception:
        _log.exception("invalidate_for_resize: _cell_px failed; skipping resize invalidation")
        return
    for k in keys:
        if self._entries[k].cell_px != cell:
            self._evict(k)
```

### Tests (2)

- `test_invalidate_for_resize_snapshots_before_iteration`
- `test_invalidate_for_resize_logs_on_cell_px_exception`

---

## STR-12 — `execute_code_block.finalize_code` wraps pacer flush+stop (closes EXEC-CURSOR-TIMER-SWALLOW)

### Problem

`execute_code_block.py:329-339`. Cursor stop is wrapped in try/except logging at debug. But pacer.flush() + stop() right below (lines 337-339) has no try/except. If `flush()` raises (on_reveal callback bug), finalization is half-done; OutputSection never reveals.

### Fix

```python
try:
    self._pacer.flush()
    self._pacer.stop()
except Exception:
    _log.exception("finalize_code: pacer flush/stop failed; forcing reveal")
    self._force_reveal()  # bypass pacer; render full output
```

### Tests (2)

- `test_finalize_code_logs_on_pacer_failure`
- `test_finalize_code_force_reveals_when_pacer_fails`

---

## STR-13 — TTE cache load OSError logged + cache disabled per run (closes TTE-CACHE-LOAD-SWALLOW)

### Problem

`_tte_cache.py:106-114`. `except OSError: pass` after `path.unlink(missing_ok=True)`. Permission error means cache keeps trying to load corrupt file forever; never gets unlinked.

### Fix

```python
except FileNotFoundError:
    pass  # raced with another process — fine
except OSError:
    _log.warning("tte_cache: cannot load/unlink %s; disabling cache for this run", path, exc_info=True)
    _CACHE_DISABLED_FOR_RUN.set()
    return None
```

`load_tte_frames` and `save_tte_frames` short-circuit if `_CACHE_DISABLED_FOR_RUN` is set.

### Tests (1)

- `test_tte_cache_disables_for_run_on_oserror`

---

## Implementation order

1. **STR-1** first — fence-state helper unblocks STR-2.
2. **STR-2** — partial-detach guard.
3. **STR-3 + STR-4** — silent-data-loss fixes; small.
4. **STR-5** — single try/except.
5. **STR-7 + STR-8 + STR-9 + STR-10** — independent fixes; parallel.
6. **STR-11 + STR-12 + STR-13** — independent fixes; parallel.
7. **STR-6** last — touches startup path; biggest blast radius if it regresses.

---

## Test file layout

```python
# tests/tui/test_streaming_hardening.py

class TestFenceStateReset: ...           # 4   STR-1
class TestRoutePartialDetach: ...        # 2   STR-2
class TestFootnoteCap: ...               # 2   STR-3
class TestOrphanCsiLog: ...              # 1   STR-4
class TestReasoningEngineInit: ...       # 1   STR-5
class TestTteProducerSafety: ...         # 3   STR-6
class TestClassifyContentLimits: ...     # 4   STR-7
class TestPartialJsonUnicode: ...        # 2   STR-8
class TestCitationOverflow: ...          # 2   STR-9
class TestProseDoubleEmit: ...           # 2   STR-10
class TestInlineImageCacheResize: ...    # 2   STR-11
class TestExecCodeFinalize: ...          # 2   STR-12
class TestTteCacheDisable: ...           # 1   STR-13
# Total: 28
```

Tests use `_FakeApp`/`_FakeStreamingBlock` for engine-only paths; `Pilot` for inline-prose and exec-code paths.
