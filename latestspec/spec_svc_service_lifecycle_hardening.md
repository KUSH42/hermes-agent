# Service Lifecycle Hardening (SPEC-SVC)

**Status:** DRAFT
**Date:** 2026-05-02
**Branch base:** `feat/textual-migration`
**Addresses:** SVC-M1, SVC-M2, SVC-M3, APP-M1, APP-M2, APP-M3, APP-M4, APP-M5, CONST-M1, SKIN-M1, SKIN-M2, STAT-M1, HEADLESS-L1, SVC-L1, STAT-L1, APP-L1, APP-L2
**Test file:** `tests/tui/test_service_lifecycle.py`
**Estimated tests:** 24

---

## Summary

The 2026-05-02 audit found 17 lifecycle / service-plumbing issues across `app.py`, `services/sessions.py`, `services/bash_service.py`, `services/theme.py`, `widgets/status_bar.py`, `headless_session.py`, `_app_constants.py`, and `theme_manager.py`. The dominant patterns: (a) mount/unmount cleanup that swallows exceptions without logs, (b) workers/threads with no teardown hook on app `on_unmount`, (c) blocking I/O on the event loop, (d) state mutations that aren't atomic. This spec addresses each cluster with focused fixes; nothing here changes contracts, only hardens execution.

---

## SVC-1 — `_NotifyListener` thread stops on app `on_unmount` (closes SVC-M1, SVC-M2)

### Problem

`services/sessions.py:83-88`. `notify_listener.start()` runs on init; only stopped in `switch_to_session`. On normal app exit, the daemon thread is GCed but the unix socket may remain bound until process death.

`switch_to_session` (lines 191-220): `_pending_exec` is set after `listener.stop()` / `timer.stop()`. If `app.exit()` raises, the listener is dead and cannot be restarted.

### Fix

1. **Add explicit teardown hook** on `HermesApp.on_unmount` calling `self._svc_sessions.stop_listener()` which forwards to `_NotifyListener.stop()`.
2. **Stage cleanup correctly in `switch_to_session`** — defer listener.stop() into the lambda passed to `app.exit()`, so failure paths still have a live listener to restart:

```python
def switch_to_session(self, sid: str) -> None:
    self._pending_exec = sid
    timer.stop()
    def _do_exec():
        listener.stop()  # only stop right before execvp
        os.execvp(sys.argv[0], sys.argv)
    self.app.exit(callback=_do_exec)
```

If `app.exit` raises before `_do_exec` runs, the listener is still alive.

### Tests (3)

- `test_notify_listener_stopped_on_app_unmount`
- `test_switch_to_session_keeps_listener_alive_until_exec`
- `test_switch_to_session_recoverable_on_exit_failure`

---

## SVC-2 — `bash_service.kill` logs on unexpected OSError (closes SVC-M3)

### Problem

`services/bash_service.py:54-55`. `except (ProcessLookupError, PermissionError, OSError): pass`. Unexpected OSError is swallowed silently; sandbox kill failures invisible.

### Fix

```python
except ProcessLookupError:
    pass  # process already gone — expected
except PermissionError:
    _log.warning("BashService.kill: PermissionError — sandbox or capability issue", exc_info=True)
except OSError:
    _log.warning("BashService.kill: unexpected OSError", exc_info=True)
```

### Tests (1)

- `test_bash_kill_logs_on_unexpected_oserror`

---

## SVC-3 — `sessions.create_new_session` cleans up orphan headless on poll timeout (closes APP-M5)

### Problem

`services/sessions.py:268-289`. If `poll_state_until_pid` times out, the spawned headless `Popen` is left running; worktree is removed but orphan process remains.

### Fix

```python
proc = subprocess.Popen([...])
try:
    pid = self._poll_state_until_pid(...)
    if pid is None:
        _log.warning("create_new_session: poll timeout; killing orphan headless pid=%d", proc.pid)
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()
        raise SessionCreateTimeout()
    return pid
except Exception:
    if proc.poll() is None:
        proc.terminate()
    raise
```

### Tests (2)

- `test_create_new_session_kills_orphan_on_poll_timeout`
- `test_create_new_session_kills_orphan_on_other_exception`

---

## SVC-4 — App `on_mount` pane-state restore logs failures (closes APP-M1)

### Problem

`app.py:879-893`. `load_layout_blob` / `_apply_layout` / `apply_center_split` errors swallowed by bare `except Exception: pass`.

### Fix

```python
try:
    blob = load_layout_blob(...)
    self._apply_layout(blob)
except Exception:
    _log.warning("on_mount: pane layout restore failed; using default", exc_info=True)
```

### Tests (1)

- `test_on_mount_logs_pane_restore_failure_then_uses_default`

---

## SVC-5 — App `on_unmount` cleanup converts swallows to debug logs (closes APP-M2)

### Problem

`app.py:1009-1052`. Five `except Exception: pass` sites in shutdown path. Best-effort teardown, fine, but no debug log = leaks unhuntable.

### Fix

Convert each to `_log.debug(..., exc_info=True)`:

```python
try:
    self._flash_resize_timer.stop()
except Exception:
    _log.debug("on_unmount: _flash_resize_timer stop failed", exc_info=True)
# ... repeat for media-player, TGP, etc.
```

### Tests (2)

- `test_on_unmount_debug_logs_each_cleanup_failure`
- `test_on_unmount_continues_past_failures`

---

## SVC-6 — Module-level `_os_mod` import deduped (closes APP-M3, APP-L1, APP-L2)

### Problem

`app.py` does `import os as _os` inline at lines 644, 829, 857, 1080, 1103. Module-level `_os_mod` already imported. Each inline call hits sys.modules. Also: overlay imports inconsistent (some top, some on_mount inline); `event.size` accessed twice in on_resize.

### Fix

1. Delete the 5 inline `import os as _os` lines; use existing module-level import.
2. Standardize overlay imports — pick **top-level** for everything (lazy imports save trivial startup time and add inconsistency); audit `app.py:108-110` and on_mount; consolidate.
3. on_resize: `size = event.size` then read `.width` / `.height` from local.

### Tests (1)

- `test_app_py_no_inline_os_imports` — grep test.

---

## SVC-7 — Auto-compact computation extracted to single helper (closes APP-M4)

### Problem

`app.py:833-839` (on_mount) duplicates body of `_flush_resize:964-967`. Two sources of truth for "should be compact"; race at first paint.

### Fix

```python
def _recompute_auto_compact(self) -> None:
    if self.compact_manual is not None:
        self.compact = self.compact_manual
        return
    self.compact = self.size.width < self._compact_threshold
```

`on_mount` and `_flush_resize` both call it. Single source of truth.

### Tests (2)

- `test_recompute_auto_compact_called_from_on_mount`
- `test_recompute_auto_compact_called_from_flush_resize`

---

## SVC-8 — `_resolve_reduced_motion` caches the resolved value (closes SKIN-M1)

### Problem

`app.py:643-655`. Reads config (file I/O) on every call; called from `set_reduced_motion` and at startup.

### Fix

```python
@cached_property
def _reduced_motion_cached(self) -> bool:
    return self._read_reduced_motion_from_config()

def refresh_reduced_motion(self) -> None:
    """Explicit recompute — call after config edit, theme reload, or manual override."""
    if "_reduced_motion_cached" in self.__dict__:
        del self.__dict__["_reduced_motion_cached"]
    _ = self._reduced_motion_cached  # warm
```

### Tests (2)

- `test_reduced_motion_cached_after_first_read`
- `test_refresh_reduced_motion_re_reads_config`

---

## SVC-9 — `KNOWN_SKILLS` atomic refresh (closes CONST-M1)

### Problem

`_app_constants.py:46-52`. `clear()` then `update()` is not atomic. Concurrent reader between the two calls sees an empty set.

### Fix

```python
_KNOWN_SKILLS_LOCK = threading.Lock()

def refresh_known_skills(new_set: set[str]) -> None:
    new_known = frozenset(new_set)
    assert _KNOWN_SLASH_BARE.isdisjoint(new_known)
    with _KNOWN_SKILLS_LOCK:
        KNOWN_SKILLS.clear()
        KNOWN_SKILLS.update(new_known)
```

Or replace `KNOWN_SKILLS` with a module-level reactive whose value is the frozenset; readers always see a complete value. Since `KNOWN_SKILLS` is documented as a mutable set today, the lock approach is the smaller change.

### Tests (2)

- `test_known_skills_refresh_atomic_under_lock`
- `test_known_skills_disjoint_invariant_holds`

---

## SVC-10 — `HintBar.on_unmount` stops `_flash_timer` (closes STAT-M1)

### Problem

`widgets/status_bar.py:337-338`. on_unmount calls `_shimmer_stop()` only; `_flash_timer` is never stopped → if widget is unmounted mid-flash, timer fires `_clear_flash` on a detached widget.

### Fix

```python
def on_unmount(self) -> None:
    self._shimmer_stop()
    if self._flash_timer is not None:
        try:
            self._flash_timer.stop()
        except Exception:
            _log.debug("HintBar.on_unmount: _flash_timer stop failed", exc_info=True)
        self._flash_timer = None
```

### Tests (1)

- `test_hintbar_on_unmount_stops_flash_timer`

---

## SVC-11 — `OutputJSONLWriter` append-only (closes HEADLESS-L1)

### Problem

`headless_session.py:35-40`. Each `write()` rewrites the whole file (up to 2000 entries). On chatty agents (10 chunks/sec), 20K JSON serializations/sec.

### Fix

Replace ring-buffer-rewrite with append-only file + rotation when row count > max:

```python
def write(self, entry: dict) -> None:
    line = json.dumps(entry) + "\n"
    self._fp.write(line)
    self._row_count += 1
    if self._row_count > self._MAX_ROWS:
        self._rotate()

def _rotate(self) -> None:
    self._fp.close()
    self._fp = open(self._path, "w")  # truncate
    # write last N rows from in-memory ring
```

### Tests (2)

- `test_output_jsonl_appends_without_rewriting`
- `test_output_jsonl_rotates_at_max_rows`

---

## SVC-12 — Sessions polling gated on overlay visibility (closes SVC-L1)

### Problem

`services/sessions.py:89`. `poll_session_index` reads `sessions.json` every 2s regardless of overlay visibility.

### Fix

```python
def _poll_session_index_tick(self) -> None:
    overlay_visible = self._is_session_overlay_visible()
    has_others = self._has_other_active_sessions
    if not (overlay_visible or has_others):
        return  # skip polling when nothing observes it
    self._poll_session_index()
```

`_has_other_active_sessions` is set by the notify listener.

### Tests (1)

- `test_sessions_poll_skipped_when_overlay_hidden_and_no_others`

---

## SVC-13 — Skin hot-swap refresh batched via `call_after_refresh` (closes STAT-L1)

### Problem

`services/theme.py:88-117`. On skin hot-swap, every ToolBlock + StreamingCodeBlock + MessagePanel + ReasoningPanel + ThinkingWidget is iterated and refreshed sequentially on the event loop. Many tool blocks → UI stall hundreds of ms.

### Fix

```python
def _refresh_runtime_skin_consumers(self) -> None:
    self.app.call_after_refresh(self._do_refresh_runtime_skin_consumers)

def _do_refresh_runtime_skin_consumers(self) -> None:
    # batch: one DOM walk, schedule each refresh in a single layout pass
    refresh_targets = [
        *self.app.query(ToolBlock),
        *self.app.query(MessagePanel),
        # ...
    ]
    for w in refresh_targets:
        w.refresh(layout=False)
    self.app.refresh(layout=True)  # single layout pass
```

### Tests (2)

- `test_skin_refresh_calls_after_refresh_not_immediately`
- `test_skin_refresh_batches_layout_into_single_pass`

---

## SVC-14 — `ThemeManager.css_variables` flatness invariant documented (closes SKIN-M2)

### Problem

`theme_manager.py:780-787`. Property returns `{**self._css_vars, **self._component_vars}` — shallow copy. Today's COMPONENT_VAR_DEFAULTS is flat strings so safe; future nested values would be shared by reference.

### Fix

Add a docstring and a runtime assertion:

```python
@property
def css_variables(self) -> dict[str, str]:
    """Return merged CSS variables. Values must be flat strings or scalars; nested
    dicts are not safe to expose because the merge is shallow.

    If a future component var needs nested structure, wrap with MappingProxyType
    or deep-copy it here.
    """
    merged = {**self._css_vars, **self._component_vars}
    if __debug__:
        for k, v in merged.items():
            assert not isinstance(v, (dict, list, set)), \
                f"ThemeManager.css_variables: nested value for {k!r} ({type(v).__name__}); see docstring"
    return merged
```

### Tests (1)

- `test_css_variables_assertion_on_nested_value`

---

## Implementation order

1. **SVC-1** first — fixes a real teardown bug; biggest lifecycle hazard.
2. **SVC-2 + SVC-3 + SVC-4 + SVC-5** — small log-and-handle patches; parallel.
3. **SVC-6 + SVC-7** — small refactors.
4. **SVC-8 + SVC-9 + SVC-10** — caching + atomicity + timer cleanup.
5. **SVC-11 + SVC-12 + SVC-13** — perf and hot-swap.
6. **SVC-14** last — assertion adds runtime cost in debug; verify no test regressions.

---

## Test file layout

```python
# tests/tui/test_service_lifecycle.py

class TestNotifyListener: ...           # 3   SVC-1
class TestBashKillLogging: ...          # 1   SVC-2
class TestSessionCreateOrphans: ...     # 2   SVC-3
class TestPaneRestore: ...              # 1   SVC-4
class TestOnUnmountCleanup: ...         # 2   SVC-5
class TestImportHygiene: ...            # 1   SVC-6
class TestAutoCompact: ...              # 2   SVC-7
class TestReducedMotionCache: ...       # 2   SVC-8
class TestKnownSkillsAtomic: ...        # 2   SVC-9
class TestHintBarTimerCleanup: ...      # 1   SVC-10
class TestOutputJsonl: ...              # 2   SVC-11
class TestSessionPollGate: ...          # 1   SVC-12
class TestSkinRefreshBatching: ...      # 2   SVC-13
class TestCssVariablesFlatness: ...     # 1   SVC-14
# Total: 23 (header estimate 24; close enough)
```

Tests use focused fakes (`FakeNotifyListener`, `FakePopen`, `FakeApp`) — no full app mounts except SVC-13 which needs a Pilot to verify layout passes.
