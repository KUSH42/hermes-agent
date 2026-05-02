# Modal/Focus Arbiter + ModalOverlayBase (SPEC-MOD)

**Status:** DRAFT
**Date:** 2026-05-02
**Branch base:** `feat/textual-migration`
**Addresses:** H3, H6, M3, M4, M12, plus generalizes audit cluster #3
**Test file:** `tests/tui/test_modal_arbiter.py` + extension to `tests/tui/test_invariants.py`
**Estimated tests:** 22

---

## Summary

Every overlay in the TUI today individually adds/removes the `--modal` CSS class, owns its own `Esc` binding with `priority=True`, and writes its own focus-restore-to-`HermesInput` epilogue. This duplication is implemented inconsistently — `HelpOverlay`/`UsageOverlay` drop only `--visible` (leaving `--modal` stale); `SkillPickerOverlay` can stack against `InterruptOverlay` simultaneously; `ToolsScreen`'s narrow-resize exit path skips `--modal` cleanup; `ContextMenu.show` empty-items leaks stale `--modal`. The Focus/Nav Spec H assumes a central arbiter exists; the implementation only has the CSS class. This spec introduces a single `_modal_stack` list on `HermesApp` and a `ModalOverlayMixin` (used at composition time) that owns the Esc binding, class toggling, and focus restore. All four overlay types migrate to the mixin in lockstep.

---

## MOD-1 — Introduce `_modal_stack` on `HermesApp`

### Problem

No central arbiter for "which overlay currently owns the modal layer."

### Fix

In `hermes_cli/tui/app.py`:

```python
class HermesApp(App):
    _modal_stack: list[Widget] = []  # bottom = oldest active modal; top = currently focused
```

Methods:
- `push_modal(self, overlay: Widget) -> None` — appends; if non-empty before push, the previous top has `--modal-suppressed` added.
- `pop_modal(self, overlay: Widget) -> None` — removes; if it was the top, restores focus per the rules in MOD-3; if predecessor exists, removes its `--modal-suppressed`.
- `top_modal(self) -> Widget | None`.
- `is_modal_active(self) -> bool` — `bool(self._modal_stack)`.

`HermesInput.action_*` and other input-side handlers consult `app.is_modal_active()` instead of probing individual overlay classes.

### Tests (4)

- `test_push_modal_marks_top_overlay_only`
- `test_push_modal_suppresses_predecessor`
- `test_pop_modal_restores_predecessor_modal_class`
- `test_is_modal_active_reflects_stack`

---

## MOD-2 — `ModalOverlayMixin` consolidates Esc + class toggling

### Problem

Each overlay implements its own `--modal` add/remove, Esc binding (`priority=True`), and dismiss action. Drift is inevitable.

### Fix

New file `hermes_cli/tui/overlays/_modal_mixin.py`:

```python
class ModalOverlayMixin:
    """Mixed into Widget/Screen subclasses that own the modal layer.

    Owns:
      - --modal class toggle on mount/unmount
      - escape binding (priority=True)
      - app._modal_stack push/pop
      - focus return to caller (overridable via _restore_focus_to())
    """
    BINDINGS = [Binding("escape", "dismiss_modal", "close", priority=True)]

    def on_mount(self) -> None:
        self.add_class("--modal")
        self.app.push_modal(self)
        self._capture_focus_caller()

    def on_unmount(self) -> None:
        self.remove_class("--modal")
        self.app.pop_modal(self)

    def action_dismiss_modal(self) -> None:
        # Subclasses override action_dismiss_modal_payload() if they have queued items.
        self.dismiss_overlay()

    def dismiss_overlay(self) -> None:
        # Concrete pop logic; pop_screen vs remove() handled per host type.
        ...

    def _restore_focus_to(self) -> Widget | None:
        # Default: HermesInput. Subclasses override.
        try:
            return self.app.query_one(HermesInput)
        except NoMatches:
            return None
```

The mixin is **not a base class** — it's mixed in via class definition (e.g. `class SkillPickerOverlay(ModalOverlayMixin, Vertical):`). Pythonic MRO handles `on_mount`/`on_unmount` chaining; subclasses call `super().on_mount()` first.

### Tests (3)

- `test_mixin_adds_modal_class_on_mount`
- `test_mixin_removes_modal_class_on_unmount`
- `test_mixin_pushes_and_pops_app_stack`

---

## MOD-3 — Focus restoration discipline

### Problem

`InterruptOverlay.action_drain_queue` (M4) does not restore focus to `HermesInput`. `ToolsScreen` narrow-resize path (H6) does not run any restore. Each overlay reinvents the rule.

### Fix

`ModalOverlayMixin._restore_focus_to()` returns a `Widget | None`. On pop:

```python
def on_unmount(self) -> None:
    target = self._restore_focus_to()
    self.remove_class("--modal")
    self.app.pop_modal(self)
    if target is not None and target.is_mounted:
        target.focus()
```

Subclasses that need different return targets (e.g. ToolsScreen returns to last-focused tool block) override `_restore_focus_to()`. The mixin guarantees **some** focus target is set, which is what AT-* invariants check.

### Tests (3)

- `test_focus_restores_to_hermes_input_by_default`
- `test_subclass_override_restore_focus`
- `test_no_crash_when_target_widget_unmounted`

---

## MOD-4 — Migrate `SkillPickerOverlay` (closes H3, partial M7)

### Problem

`SkillPickerOverlay` stacks against `InterruptOverlay`; both bind Esc `priority=True`; dispatch order undefined.

### Fix

`SkillPickerOverlay` mixes in `ModalOverlayMixin`. Existing on_mount class-add and Esc binding deleted. `_open_skill_picker` checks `if app.is_modal_active() and not isinstance(app.top_modal(), SkillPickerOverlay): return` — defers/refuses if another modal is up.

### Tests (3)

- `test_skill_picker_refuses_when_interrupt_modal_active`
- `test_skill_picker_replaces_existing_skill_picker`
- `test_skill_picker_pop_restores_input_focus`

---

## MOD-5 — Migrate `InterruptOverlay` (closes M4, partial M8)

### Problem

`action_drain_queue` doesn't restore focus. Countdown danger-class can persist on `hide_if_kind` path (M8).

### Fix

`InterruptOverlay` mixes in `ModalOverlayMixin`. `_teardown_current` no longer manages `--modal` itself. `hide_if_kind` mirrors the urgency-class clear loop already in `_teardown_current` (the M8 fix).

### Tests (3)

- `test_drain_queue_restores_focus_to_input`
- `test_hide_if_kind_clears_urgency_danger_class`
- `test_interrupt_pops_from_modal_stack_on_hide`

---

## MOD-6 — Migrate `HelpOverlay` and `UsageOverlay` (closes M3)

### Problem

Both override `action_dismiss` to remove only `--visible`, leaving `--modal` stale.

### Fix

Both mix in `ModalOverlayMixin`. Override `action_dismiss` removed (mixin's `action_dismiss_modal` replaces it). `--modal` add/remove migrates to mixin lifecycle.

### Tests (2)

- `test_help_overlay_dismiss_removes_modal`
- `test_usage_overlay_dismiss_removes_modal`

---

## MOD-7 — Migrate `ToolsScreen` (closes H6)

### Problem

`on_resize` narrow-terminal path calls `pop_screen` without removing `--modal`.

### Fix

`ToolsScreen` mixes in `ModalOverlayMixin`. `on_pause`/`on_screen_suspend` are intercepted by mixin (or `on_unmount` runs at pop). Narrow-resize path simply calls `self.dismiss_overlay()` from the mixin instead of raw `pop_screen`.

### Tests (2)

- `test_tools_screen_narrow_resize_pops_modal_class`
- `test_tools_screen_jump_to_panel_pops_modal_class`

---

## MOD-8 — Fix `ContextMenu.show` empty-items leak (M12)

### Problem

Empty-items early return at `context_menu.py:213-214` doesn't clear an existing `--modal`/`--visible` from a prior open.

### Fix

`ContextMenu` mixes in `ModalOverlayMixin`. Empty-items branch calls `self.dismiss_overlay()` before returning.

### Tests (1)

- `test_context_menu_empty_items_clears_stale_modal_class`

---

## IL-M1 — Invariant gate: every overlay claiming `--modal` uses `ModalOverlayMixin`

### Problem

Future overlays may add `--modal` raw and re-introduce the inconsistency.

### Fix

Add `tests/tui/test_invariants.py::TestModalDiscipline::test_il_m1_modal_class_only_added_via_mixin`. AST-walk `hermes_cli/tui/` for `Call` nodes whose `func` is `add_class` / `remove_class` with `"--modal"` as a string arg. Assert each enclosing class either inherits from `ModalOverlayMixin` OR carries an `# il-m1: <reason>` exemption.

### Tests (1)

- `test_il_m1_rejects_raw_modal_class_add`

---

## Behavior table — modal stacking

| Sequence | Top of stack after | Predecessor `--modal-suppressed`? |
|---|---|---|
| (empty) | None | n/a |
| Open Skill | Skill | n/a |
| Open Skill, then Interrupt arrives | Interrupt | Skill: yes |
| Skill refused while Interrupt up | Interrupt | n/a |
| Pop Interrupt while Skill suppressed | Skill | Skill: removed |

---

## Implementation order

1. **MOD-1 + MOD-2 + MOD-3** — land arbiter + mixin together; no overlay migrated yet.
2. **MOD-4** — Skill picker first; smallest blast radius and highest visibility (H3).
3. **MOD-5** — Interrupt overlay; trickiest because it has queue semantics.
4. **MOD-6** — Reference modals; trivial.
5. **MOD-7** — ToolsScreen; verify on_resize path.
6. **MOD-8** — ContextMenu; trivial.
7. **IL-M1** last — gate has no false positives once all overlays migrated.

---

## Test file layout

```python
# tests/tui/test_modal_arbiter.py

class TestModalStack: ...                  # 4   (MOD-1)
class TestModalMixinLifecycle: ...         # 3   (MOD-2)
class TestFocusRestoration: ...            # 3   (MOD-3)
class TestSkillPickerMigration: ...        # 3   (MOD-4)
class TestInterruptMigration: ...          # 3   (MOD-5)
class TestReferenceMigration: ...          # 2   (MOD-6)
class TestToolsScreenMigration: ...        # 2   (MOD-7)
class TestContextMenuMigration: ...        # 1   (MOD-8)
# Total: 21

# tests/tui/test_invariants.py (extension)
class TestModalDiscipline: ...             # 1
# Total: 1

# Grand total: 22
```

Tests use `Pilot`-mounted overlay-only screens; some use a tiny `_TestApp(HermesApp)` with `compose()` returning just the overlay-under-test.
