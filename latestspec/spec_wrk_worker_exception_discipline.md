# Workers — Exception Discipline Sweep + Invariant Gate (SPEC-WRK)

**Status:** DRAFT
**Date:** 2026-05-02
**Branch base:** `feat/textual-migration`
**Addresses:** APP-H1, APP-H2, APP-H3, APP-H4, SVC-H1, SVC-H2, STREAM-MATH-WORKER, PACER-TICK-NO-EXC, ANIM-CLOCK-TICK-SWALLOW, ANIM-TICK-RENDER-NOLOG, CD-8 (worker pool leak)
**Test file:** `tests/tui/test_worker_exception_discipline.py` + extension to `tests/tui/test_invariants.py`
**Estimated tests:** 26

---

## Summary

Project rule: every `@work(thread=True)` body and every async `@work` loop must wrap top-level logic in try/except logging via `_log.exception(...)`. The 2026-05-02 audit found **at least 7 violators** across `services/io.py`, `app.py`, `services/tools.py`, `response_flow.py`, `character_pacer.py`, `animation.py`, `drawbraille_overlay.py`. A silent worker death today produces "output stops forever" or "BashService.\_running stuck True" with zero diagnostic. This spec fixes the seven violators and adds an `IL-W1` invariant test that lints any new `@work` decoration for the wrapper pattern, closing the policy-vs-enforcement gap.

---

## WRK-1 — `consume_output` async worker has no top-level try/except

### Problem

`hermes_cli/tui/services/io.py:50-90` runs `while True: chunk = await app._output_queue.get(); app.hooks.fire(...); ...` without an outer try/except. Uncaught exception from `app.hooks.fire(...)` or panel mutations kills the worker silently — output stream stops for the rest of the session, no log entry.

### Fix

Wrap the loop body (inside `while True:`) in:

```python
try:
    chunk = await app._output_queue.get()
    # ... existing dispatch ...
except (SystemExit, KeyboardInterrupt, asyncio.CancelledError):
    raise
except Exception:
    _log.exception("consume_output: chunk dispatch failed; continuing")
    continue
```

The bare `except Exception: pass` at lines 75-80 (flush sentinel branch, APP-H2) becomes `_log.warning("io.consume: end-of-turn flush_live failed", exc_info=True)`.

### Tests (4)

- `test_consume_output_continues_after_dispatch_exception` — inject panel that raises on append; assert next chunk still dispatched.
- `test_consume_output_logs_exception` — assert `_log.exception` called once with "consume_output" in message.
- `test_consume_output_propagates_cancelled_error` — `asyncio.CancelledError` re-raised, not swallowed.
- `test_flush_sentinel_failure_logs_warning` — flush_live raises; assert `_log.warning` with `exc_info` truthy; loop continues.

---

## WRK-2 — `_start_bash_worker` thread leaks `_running=True`

### Problem

`hermes_cli/tui/app.py:1056-1061`:

```python
@work(thread=True)
def _start_bash_worker(self, cmd, block):
    self._svc_bash._exec_sync(cmd, block)  # no try/except
```

If `_exec_sync` raises before its inner finally clears `_running`, `BashService._running` stays `True` forever — every subsequent bash command short-circuits silently.

### Fix

```python
@work(thread=True)
def _start_bash_worker(self, cmd, block):
    try:
        self._svc_bash._exec_sync(cmd, block)
    except Exception:
        _log.exception("_start_bash_worker: exec failed")
    finally:
        self._svc_bash._running = False
```

### Tests (3)

- `test_bash_worker_clears_running_on_exception` — `_exec_sync` raises; assert `BashService._running is False` after worker completes.
- `test_bash_worker_logs_on_exception` — assert `_log.exception` called.
- `test_bash_worker_clears_running_on_success` — happy path still clears.

---

## WRK-3 — `_run_git_poll` worker leaks `_git_poll_in_flight=True`

### Problem

`hermes_cli/tui/app.py:1129-1138`. `poller.poll()` raises (subprocess timeout, OSError) → worker dies → `_git_poll_in_flight` is only cleared in `on_workspace_updated`, which is never posted → all future polls become no-ops.

### Fix

```python
@work(thread=True)
def _run_git_poll(self):
    try:
        snapshot = self._git_poller.poll()
        self.post_message(WorkspaceUpdated(snapshot))
    except Exception:
        _log.exception("_run_git_poll failed")
        # Post empty snapshot so on_workspace_updated still fires and clears in-flight.
        self.post_message(WorkspaceUpdated(None))
```

`on_workspace_updated` already clears `_git_poll_in_flight = False` regardless of payload (verify; if not, add `False` clear at function head).

### Tests (3)

- `test_git_poll_clears_inflight_on_exception` — poll raises; assert `_git_poll_in_flight is False`.
- `test_git_poll_logs_on_exception` — `_log.exception` called.
- `test_git_poll_posts_empty_snapshot_on_failure` — assert `WorkspaceUpdated(None)` posted.

---

## WRK-4 — `_flush_math_block` `_render_worker` has no exception path

### Problem

`hermes_cli/tui/response_flow.py:1379-1391`. `run_worker(_render_worker, thread=True)` runs Pillow/matplotlib without try/except. Renderer crash → invisible to event loop → user sees nothing happen, no log, no fallback.

### Fix

Wrap `_render_worker` body:

```python
def _render_worker():
    try:
        result = self._get_math_renderer().render_block(...)
        self._safe_callback(_on_render_done, result)
    except Exception:
        _log.exception("math render_block failed; falling back to unicode")
        self._safe_callback(_on_render_failed, None)
```

`_on_render_failed` mounts the unicode fallback already used in error paths.

### Tests (2)

- `test_math_render_worker_logs_on_exception` — renderer raises; `_log.exception` called.
- `test_math_render_worker_falls_back_to_unicode` — failed render dispatches `_on_render_failed`.

---

## WRK-5 — `CharacterPacer._tick` propagates `on_reveal` exception, killing timer

### Problem

`hermes_cli/tui/character_pacer.py:84-122`. `self._on_reveal("".join(batch))` — if `on_reveal` raises, exception propagates to Textual's `set_interval` and may stop the timer permanently with no log.

### Fix

```python
try:
    self._on_reveal("".join(batch))
except Exception:
    self._reveal_failure_count += 1
    _log.exception("CharacterPacer._tick: on_reveal raised (failure %d)", self._reveal_failure_count)
    if self._reveal_failure_count >= 3:
        _log.error("CharacterPacer: stopping after 3 consecutive on_reveal failures")
        self.stop()
```

Also fix the bare `except Exception: pass` on `timer.stop()` at lines 73-77 (PACER-TIMER-LIFECYCLE) by narrowing to `(RuntimeError, AttributeError)` with `_log.debug(exc_info=True)`.

### Tests (4)

- `test_pacer_logs_on_reveal_exception` — on_reveal raises; tick continues; log called.
- `test_pacer_stops_after_three_failures` — three consecutive failures → `_timer.stop` called.
- `test_pacer_timer_stop_narrow_swallow` — RuntimeError on stop is logged at DEBUG, not swallowed silently.
- `test_pacer_attribute_error_on_stop_handled` — AttributeError on None handle is logged at DEBUG.

---

## WRK-6 — `AnimationClock` tick callback unbounded; bad subscriber kills 15Hz bus

### Problem

`hermes_cli/tui/animation.py:213-218`:

```python
for callback in self._subscribers:
    callback()  # no try/except
```

One buggy subscriber takes down all subscribers.

### Fix

```python
for callback, fail_count in list(self._subscribers.items()):
    try:
        callback()
    except Exception:
        self._subscribers[callback] = fail_count + 1
        _log.exception("AnimationClock: subscriber %r raised (count=%d)", callback, fail_count + 1)
        if fail_count + 1 >= 5:
            _log.error("AnimationClock: unsubscribing %r after 5 failures", callback)
            self._subscribers.pop(callback, None)
```

Convert `self._subscribers` from set to dict[callback, fail_count].

### Tests (3)

- `test_clock_isolates_subscriber_exception` — one raises; others still tick.
- `test_clock_unsubscribes_after_five_failures` — five raises → callback removed.
- `test_clock_logs_each_subscriber_failure` — `_log.exception` called per failure.

---

## WRK-7 — `drawbraille_overlay._tick` doesn't catch `engine.next_frame`

### Problem

`hermes_cli/tui/drawbraille_overlay.py:1048-1050`:

```python
with measure("drawbraille_frame"):
    frame_str = engine.next_frame(params)
```

`next_frame` raises → tick crashes → if engine has bad state, every subsequent tick crashes.

### Fix

```python
try:
    with measure("drawbraille_frame"):
        frame_str = engine.next_frame(params)
except Exception:
    self._engine_failure_count += 1
    _log.exception("drawbraille engine %r next_frame failed (count=%d)",
                   type(engine).__name__, self._engine_failure_count)
    if self._engine_failure_count >= 3:
        _log.error("Falling back to 'dna' engine")
        self._switch_engine("dna")
        self._engine_failure_count = 0
    return
```

### Tests (2)

- `test_drawbraille_tick_logs_engine_exception`
- `test_drawbraille_falls_back_after_three_engine_failures`

---

## WRK-8 — `_classify_with_timeout` leaks worker threads on TimeoutError (CD-8)

### Problem

`hermes_cli/tui/services/tools.py:35-48`. On `TimeoutError`, the executor thread keeps running until classify returns. ReDoS in `classify_content` saturates the 2-worker pool.

### Fix

- Bump `max_workers=4` (classifications are bursty during plan fan-out).
- Track in-flight futures in a class attribute; on timeout, attempt `future.cancel()` (best-effort) and increment a `_pool_starvation_count` counter.
- Surface counter via `/tools` overlay diagnostics tab.

### Tests (2)

- `test_classify_timeout_increments_starvation_counter`
- `test_classify_pool_size_is_4`

---

## IL-W1 — Invariant gate: every `@work` decoration must wrap body in try/except

### Problem

The project rule (`.claude/CLAUDE.md` "Exception handling" section) is enforced ad hoc. New code keeps adding bare `@work` workers.

### Fix

Add `tests/tui/test_invariants.py::TestWorkerExceptionDiscipline::test_il_w1_workers_wrap_in_try_except`. AST-walk every `.py` under `hermes_cli/tui/` looking for functions decorated with `@work(...)` (any args). For each such function, assert the body's top-level statement is a `Try` node (or, for async, a Try wrapping the `while`/`async for` loop).

Allowed exemption: `# il-w1: <reason>` comment on the `@work` line.

### Tests (3)

- `test_il_w1_passes_on_compliant_module` — synthetic compliant code passes.
- `test_il_w1_rejects_unwrapped_worker` — synthetic violator fails with file:line in message.
- `test_il_w1_honors_exemption_comment` — `# il-w1:` exemption respected.

---

## Implementation order

1. **WRK-1** first — biggest user-visible blast radius (silent stream death).
2. **WRK-2 + WRK-3** — App-level workers; small surface; high signal.
3. **WRK-4 + WRK-5 + WRK-7** — local rendering paths.
4. **WRK-6** — clock subscriber isolation needs subscriber→dict refactor; medium scope.
5. **WRK-8** — perf-class fix, lower urgency.
6. **IL-W1** last — once all violators land, the gate has no false positives to suppress.

---

## Test file layout

```python
# tests/tui/test_worker_exception_discipline.py

class TestConsumeOutput: ...        # 4
class TestBashWorker: ...           # 3
class TestGitPollWorker: ...        # 3
class TestMathRenderWorker: ...     # 2
class TestCharacterPacer: ...       # 4
class TestAnimationClock: ...       # 3
class TestDrawbrailleEngine: ...    # 2
class TestClassifyTimeout: ...      # 2
# Total: 23

# tests/tui/test_invariants.py (extension)
class TestWorkerExceptionDiscipline: ...  # 3
# Total: 3

# Grand total: 26
```

All worker tests use injected fakes (`FakeBashService`, `FakeGitPoller`, `_FakePacer`) — no full-app mounts.
