# Tool Block — MED Cleanup (SPEC-TBM)

**Status:** DRAFT
**Date:** 2026-05-02
**Branch base:** `feat/textual-migration`
**Addresses:** CD-6, CD-7, CD-8 (cross-ref WRK-8), CD-9, CD-10, CD-11, EH-1, EH-2, PERF-1, LOW-1..LOW-5
**Test file:** `tests/tui/test_tool_block_med_cleanup.py`
**Estimated tests:** 22
**Concept doc:** `docs/concept.md` v3.6 (FROZEN through 2026-05-11). All edits remain bug-fix-class.

---

## Summary

The 11 MED + 5 LOW findings against the tool block subsystem are individually small but together account for the second half of convergence criterion 4 (≤3 MED, 0 HIGH). After SPEC-TBC closes the 6 HIGHs, this spec gets the MED count down to the threshold by addressing them in one consolidated PR. None require new contract surface; most are precision tightening.

---

## TBM-1 — Hint priority puts KIND-toggle ahead of contextual extras (closes CD-6)

### Problem

`tool_panel/_actions.py:919-958`. `_collect_hints` orders contextual chips as `[e, o, u, E, r, t, T, D, shift+d]`. Concept §H-2 mandates KIND-specific affordances (`[t]`/`[T]`) come before density / view controls, but **also** before the `e/o/u/E` extras within the contextual bucket — because `t` is the user's primary KIND-authority hand. Today four chips push `t` off-screen on narrow widths.

### Fix

Reorder contextual list so `("t", as <next>)` and `("T", auto)` lead the contextual KIND-specific bucket; `e/o/u/E` follow:

```python
contextual_hints = [
    ("t", f"as {next_kind}"),
    ("T", "auto"),
    ("e", "stderr"),
    ("o", "open"),
    ("u", "urls"),
    ("E", "edit"),
    ("r", "retry"),
]
```

`r` (retry) stays first when present (recovery > KIND > density at bucket level — verify retry handling already special-cases insertion).

### Tests (2)

- `test_hint_order_t_before_e_o_u`
- `test_hint_order_retry_first_when_present`

---

## TBM-2 — Streaming sniff buffer capped at 512 bytes (closes CD-7)

### Problem

`services/tools.py:1517-1525`. `view._sniff_buffer += chunk` accumulates every streaming chunk before lstrip threshold check. Tool with megabytes of leading whitespace → buffer grows unbounded; lstrip on 5MB string is O(n).

### Fix

```python
_SNIFF_BUFFER_CAP = 512

def _accumulate_sniff(view, chunk: str) -> None:
    if len(view._sniff_buffer) >= _SNIFF_BUFFER_CAP:
        return  # already at cap; classifier window covered
    view._sniff_buffer += chunk
    if len(view._sniff_buffer) > _SNIFF_BUFFER_CAP:
        view._sniff_buffer = view._sniff_buffer[:_SNIFF_BUFFER_CAP]
    if len(view._sniff_buffer.lstrip()) >= _SNIFF_LSTRIP_THRESHOLD:
        _classify_and_emit_hint(view)
```

If lstrip threshold never reached within the cap, fire `streaming_kind_hint = None` once and discard buffer.

### Tests (3)

- `test_sniff_buffer_caps_at_512_bytes`
- `test_sniff_buffer_emits_none_hint_when_threshold_not_reached`
- `test_sniff_buffer_lstrip_correctness_below_cap`

---

## TBM-3 — `T` revert lifts streaming hint clear into helper (closes CD-9)

### Problem

`tool_panel/_actions.py:1311-1316`. `action_kind_revert` clears `streaming_kind_hint` via set_axis, then writes `view.user_kind_override = None` directly, then calls `force_renderer(None)` which does another check + clear. Idempotent today but invites future refactor breakage of SK-2 contract ("hint clear before state write").

### Fix

```python
def _clear_streaming_kind_hint(self, view) -> None:
    """Single tear-down site for streaming_kind_hint axis. SK-2 contract.

    Always uses set_axis to ensure watchers fire and the hint clear is observable.
    """
    if getattr(view, "streaming_kind_hint", None) is not None:
        set_axis(view, AxisName.streaming_kind_hint, None)
```

`action_kind_revert` and `force_renderer` both call `self._clear_streaming_kind_hint(view)`. The duplicate clear in `force_renderer` is removed (single source).

After SPEC-TBC TBC-6 lands, `view.user_kind_override = None` becomes `set_axis(view, AxisName.user_override, None)`. This spec depends on TBC-6 for that part.

### Tests (2)

- `test_clear_streaming_kind_hint_helper_is_single_callsite`
- `test_action_kind_revert_clears_hint_exactly_once`

---

## TBM-4 — `_set_view_state` recursion guard (closes CD-10)

### Problem

`services/tools.py:284-300`. The RLock allows recursive entry; if a watcher refresh accidentally invokes `_set_view_state` recursively, the same hint-clear fires twice. Plan broker is idempotent today, but the RLock mask makes this a latent footgun.

### Fix

```python
import threading
_set_view_state_local = threading.local()

def _set_view_state(view, new_state, ...):
    depth = getattr(_set_view_state_local, "depth", 0)
    if depth >= 1:
        _log.warning("_set_view_state: recursive entry detected; rejecting nested write to %s",
                     new_state)
        return
    _set_view_state_local.depth = depth + 1
    try:
        # existing body
        ...
    finally:
        _set_view_state_local.depth = depth
```

Document on the function: "Watchers must not call `_set_view_state` re-entrantly. Recursion is rejected with a WARNING log."

### Tests (2)

- `test_set_view_state_rejects_recursive_entry`
- `test_set_view_state_recursive_entry_logs_warning`

---

## TBM-5 — `apply_layout` queues replay when `_view_state` is None (closes CD-11)

### Problem

`tool_panel/_core.py:398-407`. `vs = self._view_state or self._lookup_view_state()`. Both None during early mount → `set_axis` skipped silently; tier committed to widget reactive but never published on the axis bus. Watchers (header chip refresh, hint pipeline) miss the transition.

### Fix

Add a `_pending_layout_decisions: list[LayoutDecision] = []` queue on the panel. When `vs` is None at apply_layout time, append the decision; on next `attach_view_state(vs)`, replay the queue:

```python
def apply_layout(self, decision: LayoutDecision) -> None:
    vs = self._view_state or self._lookup_view_state()
    if vs is None:
        self._pending_layout_decisions.append(decision)
        return
    self._publish_layout(vs, decision)

def attach_view_state(self, vs) -> None:
    self._view_state = vs
    while self._pending_layout_decisions:
        decision = self._pending_layout_decisions.pop(0)
        self._publish_layout(vs, decision)
```

### Tests (3)

- `test_apply_layout_queues_when_view_state_missing`
- `test_attach_view_state_replays_queued_decisions`
- `test_axis_bus_eventually_consistent_after_late_attach`

---

## TBM-6 — `pick_renderer` streaming branch O(1) lookup (closes PERF-1)

### Problem

`body_renderers/__init__.py:149-156`. Streaming branch loops through `REGISTRY` (17 entries) calling `accepts()` + `can_render()` for every chunk. Streaming dispatch is keyed on `payload.category` (one-class-per-category) → O(n) walk is unnecessary.

### Fix

Build a category → renderer map at module import:

```python
_STREAMING_RENDERER_BY_CATEGORY: dict[ToolCategory, type[BodyRenderer]] = {}

def _build_streaming_lookup() -> None:
    for cls in REGISTRY:
        if cls.is_streaming and cls.streaming_category is not None:
            assert cls.streaming_category not in _STREAMING_RENDERER_BY_CATEGORY, \
                f"duplicate streaming renderer for {cls.streaming_category}"
            _STREAMING_RENDERER_BY_CATEGORY[cls.streaming_category] = cls

_build_streaming_lookup()

def pick_renderer(payload, *, density, phase, cls_result):
    if phase == Phase.STREAMING:
        cls = _STREAMING_RENDERER_BY_CATEGORY.get(payload.category)
        if cls is not None and cls.accepts(payload, density=density, phase=phase, cls_result=cls_result):
            return cls(payload, cls_result)
        # fall through to linear walk for streaming-but-unmapped categories
    # existing linear walk for terminal phase
    ...
```

Linear walk preserved as fallback (handles unmapped categories without breaking).

### Tests (2)

- `test_streaming_renderer_lookup_is_o1_for_known_categories`
- `test_streaming_renderer_falls_back_to_linear_walk_for_unknown_categories`

---

## TBM-7 — `action_edit_cmd` logs on exception (closes EH-1)

### Problem

`tool_panel/_actions.py:490-491`. `except Exception: # noqa: bare-except` flashes "edit unavailable" with no log.

### Fix

```python
except Exception:
    _log.exception("action_edit_cmd failed")
    self._flash_header("edit unavailable")
```

### Tests (1)

- `test_action_edit_cmd_logs_on_exception`

---

## TBM-8 — `action_copy_ansi/_html` outdated comment removed (closes EH-2)

### Problem

`tool_panel/_actions.py:580-585, 608-614`. Comment "falls back to action_copy_body" is misleading; current code structure makes this implicit via the next `if`.

### Fix

Trim the misleading comment; rely on code structure speaking for itself.

### Tests (0)

(Cosmetic — no test added.)

---

## TBM-9 — LOW cleanups (LOW-1..LOW-5)

### LOW-1 — `_SKELETON_PULSE_S` documentation

`tool_blocks/_streaming.py:54-64`. Add docstring tying constant to motion-channel cadence row in concept §perception-budgets table.

### LOW-2 — `BodyRenderer.summary_line` kwargs

`body_renderers/base.py:103-111`. Default ignores `density`/`cls_result` kwargs. Add a TODO comment clarifying subclasses use them; base is intentionally generic.

### LOW-3 — `_ks_context()` density.value guarded

`tool_panel/_core.py:472-482`. Use `getattr(self.density, "value", "default")` to short-circuit when reactive is unset during early mount.

### LOW-4 — `_register_header_hint_watcher` warns on missing attr

`services/tools.py:1506-1513`. Bump from debug to warning when `attach_stream_axis_watcher` is missing on header (real type-mismatch should scream); keep debug for the actual exception.

### LOW-5 — Hint render-form 14-char cap test

Add invariant test asserting every rendered chip from `_collect_hints()` has cell width ≤ `14 + len("[X] ")` per concept §microcopy contract clause 3.

### Tests (5)

- `test_skeleton_pulse_constant_documented`
- `test_summary_line_base_implementation_carries_todo`
- `test_ks_context_handles_unset_density_reactive`
- `test_register_header_hint_watcher_warns_on_missing_attr`
- `test_il_chip_render_form_under_18_chars` (added to test_invariants.py)

---

## TBM-10 — Concept doc 2026-05-02 changelog amendment

Append to the v3.6 changelog block (already added in SPEC-TBC):

```
- 2026-05-02 (bug-fix): hint priority order corrected so [t]/[T] precede e/o/u/E
  contextual extras within the KIND-specific bucket. (TBM-1)
- 2026-05-02 (bug-fix): streaming kind hint clear consolidated into single
  _clear_streaming_kind_hint helper; SK-2 contract reaffirmed. (TBM-3)
- 2026-05-02 (note): _set_view_state now rejects recursive entry with WARNING.
  Watchers must not re-enter the choke-point. (TBM-4)
```

### Tests (1)

- `test_concept_doc_changelog_amendments_present`

---

## Implementation order

1. **TBM-7 + TBM-8 + TBM-9** first — small, parallel, no dependencies.
2. **TBM-1** — hint reorder; visible UX win.
3. **TBM-2 + TBM-6** — perf fixes; verify with regression tests.
4. **TBM-3** — depends on SPEC-TBC TBC-6 (axis name `user_override`); land after TBC.
5. **TBM-4 + TBM-5** — concurrency tightening.
6. **TBM-10** last.

---

## Test file layout

```python
# tests/tui/test_tool_block_med_cleanup.py

class TestHintOrder: ...               # 2   TBM-1
class TestSniffBufferCap: ...          # 3   TBM-2
class TestClearStreamingHint: ...      # 2   TBM-3
class TestSetViewStateRecursion: ...   # 2   TBM-4
class TestApplyLayoutQueue: ...        # 3   TBM-5
class TestStreamingRendererLookup: ... # 2   TBM-6
class TestActionEditLogging: ...       # 1   TBM-7
class TestLowCleanups: ...             # 4   TBM-9 (4 of 5; the 5th lives in invariants)
class TestConceptDocAmendments: ...    # 1   TBM-10
# Total: 20

# tests/tui/test_invariants.py (extension)
class TestChipRenderForm: ...          # 1
class TestUserOverrideAxis: ...        # 1   (part of IL-7 extension; co-owned with TBC-6)
# Total: 2

# Grand total: 22
```

Tests use `_FakeViewState` / `_FakeToolPanel` for axis-bus paths; rendering tests mount minimal Pilot.

---

## Convergence impact

Combined with SPEC-TBC, after this spec lands the MED count drops from 11 to ≤2 (the cosmetic ones intentionally not gated). Criterion 4 of the convergence definition flips green; after 14 consecutive days of green CI, the convergence plan can be closed per `.claude/CLAUDE.md`.
