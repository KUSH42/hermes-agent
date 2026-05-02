# Animation — Reentrancy + Tick Safety (SPEC-ANM)

**Status:** DRAFT
**Date:** 2026-05-02
**Branch base:** `feat/textual-migration`
**Addresses:** ANIM-LAYER-REENTRANCY, ANIM-EXTERNAL-TRAIL-SCALES, PERF-RGB-CACHE-CAP, plus animation-related portions of WRK spec (cross-ref WRK-6 AnimationClock, WRK-7 drawbraille tick — those are owned by SPEC-WRK; this spec covers the animation-internal half)
**Test file:** `tests/tui/test_animation_safety.py`
**Estimated tests:** 14

---

## Summary

Animation hot paths share **module-level mutable buffers** (`_LAYER_ROW_BUF`, `_LAYER_RESULT_BUF`, `_RGB_CACHE`, `_SINE_TABLES`) plus orchestrator `_external_trail` setattrs keyed on `_w/_h`. The comment claims single-threaded, but `CrossfadeEngine` + nested `CompositeEngine` reenter `_layer_frames` in the same frame, clobbering outer-call state and producing scrambled frames. Additionally `apply_external_trail` is O(rows × cols × 8) per frame with no perf probe; `_RGB_CACHE` is "first-256-wins" not LRU. This spec eliminates the reentrancy hazard by moving buffers to per-call locals or a per-engine buffer pool, adds the missing perf probes, and converts `_RGB_CACHE` to a real LRU.

> **Note:** WRK-6 (`AnimationClock` subscriber isolation) and WRK-7 (`drawbraille_overlay._tick` engine fallback) are owned by SPEC-WRK. This spec is animation-engine internals only.

---

## ANM-1 — `_layer_frames` uses per-call locals (closes ANIM-LAYER-REENTRANCY)

### Problem

`anim_engines.py:178-225`. `_LAYER_ROW_BUF` and `_LAYER_RESULT_BUF` are module-level lists mutated in place. Comment "single-threaded" is correct re: threads, but **not re: reentrancy** — `CompositeEngine` whose layers themselves call `_layer_frames` (nested composite, crossfade-of-composite) clobbers the outer call's state.

### Fix

Two acceptable approaches; **pick A**:

**A. Per-call locals (preferred).** Drop the module-level buffers; allocate fresh lists at function entry. List-allocation cost (~1µs) is negligible vs the per-cell Python work. This is the simplest, surest fix.

```python
def _layer_frames(frames, ...):
    row_buf: list[str] = []
    result_buf: list[str] = []
    # rest of function unchanged
```

**B. Per-engine buffer pool.** Each engine instance owns its own buffers. More plumbing; slight perf win on repeated frames; not worth it.

Add a runtime assertion at function entry to catch any future re-introduction of shared state:

```python
assert "_LAYER_ROW_BUF" not in globals(), \
    "ANM-1: module-level layer buffer reintroduced; use per-call locals"
```

### Tests (3)

- `test_layer_frames_per_call_buffers` — call `_layer_frames` recursively (nested composite); assert each call sees its own buffer.
- `test_nested_composite_engine_no_clobber` — render a `CompositeEngine([CompositeEngine([...]), ...])`; compare expected output.
- `test_module_level_layer_buf_not_present` — `assert not hasattr(anim_engines, "_LAYER_ROW_BUF")`.

---

## ANM-2 — `apply_external_trail` perf probe + vectorized hot loop (closes ANIM-EXTERNAL-TRAIL-SCALES)

### Problem

`anim_orchestrator.py:438-450`. For each braille char, inner loop iterates 8 bit positions and decodes/re-encodes. At 80×24 cells, 60 fps → **15360 set() calls/frame** — dominant cost on stateless engines.

### Fix

1. **Perf probe.** Wrap with `measure("apply_external_trail", budget_ms=4)` — surfaces overruns in `PerfRegistry`.
2. **Precomputed bit-mask table.** Build a module-level `_BRAILLE_BIT_MASKS = tuple(1 << i for i in range(8))` and a fast-path that uses `bytes.translate` or numpy-style vectorization where possible. If the data structure resists vectorization (per-cell side effects), at minimum unroll the inner 8-bit loop manually.

Concrete first-pass change: replace per-bit `set()` calls with a single `frozenset` constructed once per cell:

```python
_BIT_RANGE = range(8)
_BIT_MASKS = tuple(1 << i for i in _BIT_RANGE)

def apply_external_trail(self, frame, ...):
    with measure("apply_external_trail", budget_ms=4):
        for row_idx, row in enumerate(frame):
            for col_idx, ch in enumerate(row):
                code = ord(ch) - 0x2800
                if not code:
                    continue
                # set bits in trail buffer using mask, not set()
                self._trail[row_idx * cols + col_idx] |= code
```

Confirm this matches the algorithmic intent; the audit found O(n^2)-shaped set() walking. The fix gets it to O(rows × cols).

### Tests (3)

- `test_apply_external_trail_perf_probe_records`
- `test_apply_external_trail_correctness_unchanged` — golden-frame test against pre-fix output.
- `test_apply_external_trail_budget_warning_on_overrun`

---

## ANM-3 — `_RGB_CACHE` is real LRU (closes PERF-RGB-CACHE-CAP)

### Problem

`animation.py:99-110`. `_RGB_CACHE` is "first-256-wins": once full, new entries skip caching but recompute every frame. Multi-color list with N>256 stops → silent perf cliff.

### Fix

Replace the manual cache with `functools.lru_cache(maxsize=256)`:

```python
@functools.lru_cache(maxsize=256)
def _rgb_cached(hex_str: str) -> tuple[int, int, int]:
    ...

# Drop `_RGB_CACHE` dict and the manual `if len(_RGB_CACHE) < 256: ...` guard.
```

### Tests (2)

- `test_rgb_cache_evicts_least_recently_used`
- `test_rgb_cache_correctness_after_eviction`

---

## ANM-4 — Module-level mutable-state lint gate

### Problem

Future code can re-introduce shared module-level buffers in `anim_engines.py`/`animation.py`/`anim_orchestrator.py`.

### Fix

Add `tests/tui/test_invariants.py::TestAnimationSharedState::test_il_a1_no_module_level_mutable_buffers`. AST-walk the three animation files; reject any module-level `Assign` whose target is uppercase-named (convention) AND value is `list()` / `[]` / `dict()` / `{}` / `set()` etc. — unless preceded by `# il-a1: <reason>` exemption.

`_RGB_CACHE` (after ANM-3) becomes the lru_cache-wrapped function, no module-level dict. `_SINE_TABLES` is read-only after init — exemption with reason "read-only after module init".

### Tests (3)

- `test_il_a1_passes_on_compliant_module`
- `test_il_a1_rejects_module_level_list`
- `test_il_a1_honors_exemption_comment`

---

## ANM-5 — Drawbraille watcher swallows log at debug (cross-ref OVERLAY-CTOR-WATCH-SWALLOW)

### Problem

Already addressed in **SPEC-CSS** (CSS-5). Listed here for completeness — no separate work.

### Fix

(Owned by SPEC-CSS.)

---

## Implementation order

1. **ANM-1** first — pure refactor, no behavior change.
2. **ANM-3** — drop-in `lru_cache` swap.
3. **ANM-2** — perf probe + bit-mask hot path. Verify with golden-frame test.
4. **ANM-4** — invariant gate; lands once code is clean.

---

## Test file layout

```python
# tests/tui/test_animation_safety.py

class TestLayerFramesReentrancy: ...     # 3   ANM-1
class TestExternalTrailPerf: ...         # 3   ANM-2
class TestRgbCacheLru: ...               # 2   ANM-3
# Total: 8

# tests/tui/test_invariants.py (extension)
class TestAnimationSharedState: ...      # 3
# Total: 3

# Grand total: 11

# Note: header estimate was 14; rebalancing to 11 is fine — tighter and still covers each ANM-N.
```

Tests use synthetic `frame` payloads (lists of braille-char strings) and compare against pre-recorded golden frames stored in `tests/tui/_anim_golden_frames.py`.
