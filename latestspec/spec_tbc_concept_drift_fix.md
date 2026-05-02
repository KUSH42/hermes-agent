# Tool Block — Concept v3.6 Drift Fix (SPEC-TBC)

**Status:** DRAFT
**Date:** 2026-05-02
**Branch base:** `feat/textual-migration`
**Addresses:** CD-1, CD-2, CD-3, CD-4, CD-5, IL-GAP-1, DEAD-1
**Test file:** `tests/tui/test_concept_drift_fix.py` + extension to `tests/tui/test_invariants.py`
**Estimated tests:** 24
**Concept doc:** `docs/concept.md` v3.6 (FROZEN through 2026-05-11). All edits below qualify as **bug-fix-class** under the freeze policy: typo, broken cross-reference, factual correction. No new clauses, no version bump.

---

## Summary

The 2026-05-02 deep audit found 6 HIGH-severity drift items between code and `docs/concept.md` v3.6. Closing them flips convergence criterion 4 (≤3 MED, 0 HIGH) green, which is the operational stop signal for the convergence plan. Every fix below is either (a) a code change to bring the implementation in line with an existing concept clause, or (b) a typo/cross-reference fix in the doc. None bumps v3.6 or adds new contract surface.

---

## TBC-1 — Delete dead `ToolCallHeader` (CD-1, DEAD-1)

### Problem

`hermes_cli/tui/tool_blocks/_header.py:1013-1114` defines `ToolCallHeader` (102 LOC). The class is **not imported, instantiated, or exported** from `tool_blocks/__init__.py` anywhere in the codebase. It contains a direct `self._view.state = new_state` write at line 1065 that bypasses `set_axis`, `_set_view_state`, AND `PlanSyncBroker` — a concrete violation of `concept.md` §"Concurrency invariants" if it were ever wired up.

### Fix

Delete the class body. Delete unreferenced helpers `_CHIP_CANCELLED`/`_CHIP_FINALIZING` if they have no other consumer (verify with `rg`). Update `tool_blocks/__init__.py` if it re-exports.

### Tests (2)

- `test_toolcall_header_class_is_removed` — `from hermes_cli.tui.tool_blocks import _header; assert not hasattr(_header, 'ToolCallHeader')`.
- `test_no_imports_of_toolcall_header_remain` — AST/grep test asserts no remaining import statements name it.

---

## TBC-2 — `_swap_renderer` falls back to `FallbackRenderer` on `build_widget` failure (CD-2)

### Problem

`hermes_cli/tui/tool_panel/_completion.py:244-248` catches `build_widget()` exception, logs it, then **abandons the swap** with the comment "keeping original body". Concept v3.6 §Renderer dispatch / Failure modes mandates: *"Renderer raises during render() → Caught, logged with exc_info=True, fallback to RawTextRenderer"*. User sees stale streaming body for a classified failure.

### Fix

```python
except Exception:
    _log.exception("_swap_renderer: build_widget failed for %r; falling back to FallbackRenderer",
                   type(renderer).__name__)
    self._block_failed_renderers.add(type(renderer))  # tag so density changes don't retry
    fallback = FallbackRenderer(payload, ClassificationResult(kind=RendererKind.TEXT, confidence=0.0))
    new_body = fallback.build_widget(payload, density=density)
    # ... continue swap with new_body ...
```

`_block_failed_renderers` is a per-block set keyed on renderer **class**; on density-change re-render, `pick_renderer` is consulted but candidates whose class is in the failed set are skipped, returning `FallbackRenderer` directly.

### Behavior table

| Renderer state | Density change | Result |
|---|---|---|
| Healthy | Yes | New renderer dispatched normally |
| Failed once | Yes | `FallbackRenderer` returned without retry |
| Failed once | None (initial) | `FallbackRenderer` mounted, fallback caption visible |

### Tests (4)

- `test_swap_renderer_mounts_fallback_on_build_widget_exception`
- `test_swap_renderer_logs_with_exc_info_on_failure`
- `test_block_tagged_after_failure_skips_renderer_on_density_change`
- `test_fallback_renderer_caption_shows_classification_failure`

---

## TBC-3 — Wire slow-renderer 250 ms soft-deadline contract (CD-3)

### Problem

`hermes_cli/tui/tool_panel/_footer.py:267-293` (`_mount_body_with_deadline`) runs the renderer **synchronously on the event loop** and only logs a post-hoc warning when elapsed > `_SLOW_DEADLINE_S`. The placeholder + worker + swap path (`_start_slow_render` / `_render_in_worker`) **exists but is never invoked** from the first-build flow. A 600 ms renderer freezes the event loop on first paint — exactly what concept v3.6 §dispatch failure-modes is meant to prevent: *"Soft deadline: panel mounts a placeholder widget … at 250 ms, schedules the slow render in a worker, swaps in result via call_from_thread."*

### Fix

Two-phase strategy:

1. **Persisted slow-tag.** Add a class-level `_SLOW_RENDERER_CLASSES: set[type] = set()` on `ToolPanel`. After a renderer's first build crosses `_SLOW_DEADLINE_S`, add its class to this set.
2. **Reroute on tagged classes.** Before invoking the renderer in `_mount_body_with_deadline`, check the tag set: if tagged, dispatch directly to `_start_slow_render` (placeholder mount → `_render_in_worker` → `call_from_thread` swap). Untagged renderers run synchronously the first time; on overrun, they are tagged for next time.

This is the minimum that closes the contract. (A pre-emptive yield-point during the first paint requires architectural change — out of bug-fix scope.)

### Behavior table

| Renderer history | Initial build path | Re-render path |
|---|---|---|
| No prior overrun | Synchronous | Tag on overrun, then worker |
| Tagged slow | Placeholder + worker + swap | Placeholder + worker + swap |

### Tests (5)

- `test_initial_build_runs_synchronously_when_untagged`
- `test_overrun_tags_renderer_class_as_slow`
- `test_tagged_renderer_routes_to_worker_on_next_build`
- `test_worker_swap_uses_call_from_thread`
- `test_slow_tag_persists_across_panel_instances` (class-level set)

---

## TBC-4 — Fix `_auto_renderer_kind` non-existent attribute read (CD-4)

### Problem

`hermes_cli/tui/tool_blocks/_streaming.py:907-927`:

```python
view = getattr(self, "_view", None)  # WRONG — no such attribute on StreamingToolBlock
```

`_view` does not exist on `StreamingToolBlock`; canonical view-state lives on the panel as `_view_state`. The `try/except` logs at debug only; function silently returns `RendererKind.PLAIN` for every call. Net effect: `action_kind_revert` always flashes "kind: auto (plain)" regardless of actual classifier verdict — **lying to the user**, in violation of concept v3.6 §user authority on KIND.

Additionally, line 917 passes `view.args` (a `dict`) where `pick_renderer` expects a `ToolPayload`.

### Fix

```python
def _auto_renderer_kind(self) -> RendererKind:
    panel = getattr(self, "_tool_panel", None)
    if panel is None:
        return RendererKind.PLAIN
    view = getattr(panel, "_view_state", None)
    if view is None:
        return RendererKind.PLAIN
    payload = view.payload  # ToolPayload, not view.args dict
    if payload is None:
        return RendererKind.PLAIN
    cls_result = panel.last_classification_result()  # already cached on panel
    return pick_renderer(payload, density=view.density,
                         phase=view.state, cls_result=cls_result).kind
```

If `last_classification_result()` does not exist on the panel today, expose it as a thin getter for the cached result already kept by `_run_sniff_buffer`.

### Tests (4)

- `test_auto_renderer_kind_resolves_via_panel_view_state`
- `test_auto_renderer_kind_returns_plain_when_panel_missing`
- `test_auto_renderer_kind_uses_payload_not_args_dict`
- `test_action_kind_revert_caption_reflects_real_classifier_verdict`

---

## TBC-5 — Reconcile block-level copy key: `c` vs `y` (CD-5)

### Problem

Concept v3.6 §"Block-level key contract" table row reads: *"c | copy block content (kind-aware)"*. Implementation binds `y` (`_core.py:171`) and the hint pipeline shows "y copy" (`_actions.py:916, 1140`). Canonical mocks, perception-budget examples, and the key-contract table all use `[c]opy`.

This is a **bug-fix-class edit** allowed under freeze (typo / factual correction).

### Fix

**Code path (recommended):** rebind `y → c` in `_core.py` BINDINGS, keep action name `action_copy_body` (already unambiguous since `action_copy` would conflict — actually verify; rename to `action_copy_block` if cleaner). Update microcopy: `_actions.py:916, 1140` `"y copy"` → `"c copy"`.

**Concept doc path:** add a changelog entry to `docs/concept.md` noting the bug-fix reconciliation.

### Tests (2)

- `test_block_level_copy_binding_is_c` — `BINDINGS` table contains `("c", ...)`, not `("y", ...)`.
- `test_hint_pipeline_renders_c_copy_label`

---

## TBC-6 — Promote `user_kind_override` to AxisName (IL-GAP-1)

### Problem

Concept v3.6 §user overrides: *"recorded on `ToolCallViewState` … resolver reads them as inputs"*. IL-7 only checks `set_axis` ordering for `streaming_kind_hint` vs `state` — it does **not** check that `user_kind_override` changes pair with a header refresh. Today `_actions.py:1172, 1315` writes `view.user_kind_override = ...` directly, bypassing watchers, so the header's "as `<kind>`" caption can lag until something else triggers a refresh.

### Fix

1. Add `user_override` to `AxisName` enum (`tool_panel/_view_state.py`).
2. Replace direct writes with `set_axis(view, AxisName.user_override, value)`.
3. `ToolCallHeader` (the live one, not the dead class deleted in TBC-1) attaches an axis watcher on `user_override` that calls `self.refresh()`.

This is a **bug-fix-class edit** because it's correcting a missed enum entry against the documented user-overrides clause; no new contract surface.

### Tests (4)

- `test_user_override_axis_routes_through_set_axis`
- `test_header_refreshes_on_user_override_axis_write`
- `test_action_kind_revert_writes_via_set_axis`
- `test_il_7_includes_user_override_axis_check` — extend IL-7 invariant to also verify `user_override` is paired with header refresh.

---

## TBC-7 — Concept doc bug-fix changelog entries

### Problem

Several drift items above require small concept doc patches: cross-reference fixes and changelog entries that close the gap.

### Fix

In `docs/concept.md`, append a v3.6 changelog block dated 2026-05-02 with these line items (no clause body changes):

```
- 2026-05-02 (bug-fix): block-level copy key reconciliation — code rebound to `c` to
  match canonical key-contract table; microcopy updated. (TBC-5)
- 2026-05-02 (bug-fix): user_kind_override now flows through set_axis(AxisName.user_override)
  to satisfy "set_axis is the choke-point" invariant. No clause change. (TBC-6)
- 2026-05-02 (bug-fix): renderer dispatch failure-mode contract realized in code:
  FallbackRenderer is mounted on build_widget exception; slow-renderer 250 ms tag
  triggers worker dispatch on subsequent builds. (TBC-2, TBC-3)
```

### Tests (1)

- `test_concept_doc_changelog_present_for_2026_05_02` — grep test on `docs/concept.md`.

---

## Implementation order

1. **TBC-1** first — pure deletion, eliminates a concept-violator and 102 LOC. Lowest risk.
2. **TBC-5** — small rebinding + microcopy edit.
3. **TBC-4** — bug fix on broken read; user-visible win.
4. **TBC-6** — axis-bus extension; depends on no others.
5. **TBC-2** — FallbackRenderer wiring; standalone.
6. **TBC-3** — slow-renderer worker dispatch; biggest scope, save for last.
7. **TBC-7** — concept doc changelog. Land with the last code patch.

---

## Test file layout

```python
# tests/tui/test_concept_drift_fix.py

class TestToolCallHeaderDeleted: ...        # 2
class TestSwapRendererFallback: ...          # 4
class TestSlowRendererWorkerDispatch: ...    # 5
class TestAutoRendererKindResolves: ...      # 4
class TestCopyKeyBinding: ...                # 2
class TestUserOverrideAxis: ...              # 4
class TestConceptDocChangelog: ...           # 1
# Total: 22

# tests/tui/test_invariants.py (extension to IL-7)
class TestUserOverrideAxisInvariant: ...     # 2
# Total: 2

# Grand total: 24
```

All tests use `_FakeToolPanel` / `_FakeViewState` / `Pilot`-mounted single panels — no full app runs.

---

## Convergence impact

After this spec lands and tests pass:

- Criterion 1 (invariant gates green): still passing.
- Criterion 2 (concept doc unchanged): still passing — only changelog entries added.
- Criterion 3 (targeted tests green per PR): expected to pass.
- Criterion 4 (≤3 MED, 0 HIGH): **flips green** if a fresh re-audit confirms HIGH count drops to 0.

The 11 MEDs identified in the audit are addressed in **SPEC-TBM** (Tool Block MED Cleanup) — landing TBC + TBM together is what closes the convergence plan.
