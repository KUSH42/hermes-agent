# Composer — ASSIST Consolidation + composer-concept doc closure (SPEC-ASS)

**Status:** DRAFT
**Date:** 2026-05-02
**Branch base:** `feat/textual-migration`
**Addresses:** H1, H2, M6, M9, M11, CC-1, CC-2, CC-3, CC-4, CC-5, CC-6, CC-7, CC-8, CC-9, CC-10, CC-11, CC-12
**Test file:** `tests/tui/test_composer_assist_consolidation.py`
**Estimated tests:** 30
**Concept doc:** `docs/composer-concept.md` — active, no freeze. Edits permitted; this spec also closes a long-running drift catalogue inside the doc.

---

## Summary

`composer-concept.md` mandates `_resolve_assist()` as the single write site for the ASSIST axis. In practice ASSIST state is spread across **three independent reactives/flags**: `_completion_overlay_active` (Python bool on `HermesInput`), the `--visible` CSS class on `CompletionOverlay`, and an implicit DOM probe for `SkillPickerOverlay`. AutoDismiss flips one of those three but not the others, leaving MODE wedged at COMPLETION indefinitely (CC-1, H2). Placeholder priority order inverts the BASH > COMPLETION contract (CC-2). Legend literals are not byte-exact with `LEGENDS` (CC-3). The doc itself has six stale drift catalogue entries (CC-5/6/9/10/11) that lag the code.

This spec introduces a single reactive `assist: AssistKind` on `HermesInput` (typed enum, single source of truth), migrates every consumer (mode, chevron, placeholder, `--visible`, watchers) to read it, fixes priority/literal/lock-gate bugs, removes scope-creep findings (CC-12), and closes the drift catalogue with documented "CLOSED" annotations.

---

## ASS-1 — Introduce `AssistKind` reactive on `HermesInput`

### Problem

Multiple readers consult inconsistent sources for ASSIST state. `_completion_overlay_active` is a plain `bool` (CC-9 partial). No central read gate.

### Fix

In `hermes_cli/tui/input/widget.py`:

```python
class AssistKind(Enum):
    NONE = "none"
    GHOST = "ghost"          # ghost suggestion visible
    OVERLAY = "overlay"      # completion overlay (slash, path, @file)
    PICKER = "picker"        # skill picker open
```

```python
class HermesInput(Input):
    assist: reactive[AssistKind] = reactive(AssistKind.NONE)
```

Replace `_completion_overlay_active: bool` with reads of `self.assist == AssistKind.OVERLAY`. Replace probes for SkillPickerOverlay with `self.assist == AssistKind.PICKER`.

`_resolve_assist(target: AssistKind)` is the **only** function that writes `self.assist`. All transitions go through it (per existing concept G contract).

### Tests (3)

- `test_assist_reactive_default_is_none`
- `test_resolve_assist_is_only_write_site` (AST-walk asserting no `self.assist =` outside `_resolve_assist`)
- `test_assist_enum_values_match_concept_doc`

---

## ASS-2 — `_compute_mode` adds PICKER branch (closes M11, partial CC-4)

### Problem

`_compute_mode` (`widget.py:776-786`) has no PICKER branch. Chevron/legend lie about state during SkillPicker. CC-4 (docstring `InputMode.AGENT`) is a doc-side symptom of the missing enum value.

### Fix

Decision: do **not** add `InputMode.PICKER`. The picker is an ASSIST-level state, not a MODE-level state — MODE remains the underlying user mode (NORMAL/BASH/etc.) while ASSIST overlays the picker chrome. Concept doc agrees with this.

Instead:
- `_compute_mode` reads `self.assist`; when `assist == PICKER`, force `_compose_chevron_text("picker")` and `placeholder = "(skill)"` from the chevron writer.
- The legend bar gains a tier `if self.assist == PICKER: return LEGENDS["picker"]` ahead of the mode tier.
- Add `LEGENDS["picker"]` entry to the canonical table.
- Update SkillPickerOverlay docstring (`overlays/skill_picker.py:3-6, 43, 143`) replacing all `InputMode.AGENT` → `InputMode.NORMAL` (CC-4).

### Tests (4)

- `test_chevron_reads_picker_when_assist_is_picker`
- `test_legend_picker_tier_takes_priority_over_mode`
- `test_skill_picker_docstring_uses_input_mode_normal` (grep test)
- `test_legends_table_has_picker_entry`

---

## ASS-3 — `_refresh_placeholder` priority order matches concept (CC-2)

### Problem

`widget.py:239-244` puts the COMPLETION placeholder branch **before** BASH. Concept doc drift §1 mandates BASH > COMPLETION (the function docstring at line 229 even documents the intended order).

### Fix

Reorder branches:

```python
def _refresh_placeholder(self) -> None:
    if self._rev_mode:                                  # REV_SEARCH wins
        self.placeholder = self._rev_search_placeholder()
        return
    if self.has_class("--bash-mode"):                   # BASH next
        self.placeholder = "$ bash command…"
        return
    if self.assist == AssistKind.OVERLAY:               # COMPLETION third
        self.placeholder = ""  # see ASS-4
        return
    if self._error_state:                               # ERROR after
        ...
    self.placeholder = self._normal_placeholder()       # NORMAL last
```

### Tests (2)

- `test_placeholder_bash_wins_over_overlay`
- `test_placeholder_overlay_wins_over_error_normal`

---

## ASS-4 — COMPLETION placeholder behavior matches concept mock (CC-8)

### Problem

Concept mock for COMPLETION mode says "(unchanged from underlying mode)" — overlay floats over the unchanged underlying placeholder. Code at `widget.py:241` overwrites with `"↑↓ select  ·  Tab accept  ·  Esc close"`.

### Fix

Two acceptable resolutions; **pick the doc-mandated one**:

**Resolution A (preferred):** code follows doc. The overlay rendering itself shows nav legend; placeholder underneath is unchanged. The assist branch in `_refresh_placeholder` becomes a no-op (the function returns early without reassigning `placeholder`), preserving whatever the underlying mode set.

```python
if self.assist == AssistKind.OVERLAY:
    return  # leave placeholder from underlying mode
```

CompletionOverlay's `border_subtitle` already carries "↑↓ select · Tab accept · Esc close" — verify and surface there if missing.

**Resolution B (rejected):** overwrite placeholder. This pollutes BASH placeholder and contradicts doc.

### Tests (3)

- `test_overlay_assist_does_not_overwrite_placeholder`
- `test_underlying_bash_placeholder_visible_when_overlay_active`
- `test_completion_overlay_subtitle_carries_nav_hint`

---

## ASS-5 — `LEGENDS["completion"]` byte-exact with concept doc (CC-3)

### Problem

`widgets/input_legend_bar.py:31` reads `"@file  ·  Tab=insert  ·  Enter=run  ·  Esc=cancel"`. Concept doc table says `"@file  ·  Tab=accept  ·  Enter=accept  ·  Esc=cancel"`.

### Fix

Update `LEGENDS["completion"]` to match doc verbatim. If the verbs `insert/run` were intentional, escalate to a doc edit instead — but the concept doc takes precedence by default.

Add `LEGENDS["picker"]` (new): `"↑↓ navigate  ·  Enter=run  ·  Esc=cancel"` (or whatever the picker actually does — verify against `SkillPickerOverlay.on_key`).

### Tests (2)

- `test_legends_completion_byte_exact_with_doc` — string equality test reading both files.
- `test_legends_picker_present_and_consistent`

---

## ASS-6 — `AutoDismiss` triggers `_hide_completion_overlay` properly (closes H2, CC-1)

### Problem

`completion_overlay.py:180-186` (`on_virtual_completion_list_auto_dismiss`) removes `--visible` and `--slash-only` CSS but does **not** call `_hide_completion_overlay` on `HermesInput`. Old `_completion_overlay_active` stays True; with the ASS-1 refactor, `self.assist` would stay `OVERLAY`. MODE/legend/placeholder all wedge.

### Fix

```python
def on_virtual_completion_list_auto_dismiss(self, ev) -> None:
    self.post_message(_AutoDismissBubble())  # bubbles up
```

`HermesInput` handles the message:

```python
def on__auto_dismiss_bubble(self, ev) -> None:
    self._hide_completion_overlay()  # single tear-down site
    ev.stop()
```

`_hide_completion_overlay` already calls `_resolve_assist(AssistKind.NONE)`, stops `_path_debounce_timer`, and clears the overlay. AutoDismiss now goes through it.

### Tests (3)

- `test_auto_dismiss_triggers_hide_completion_overlay`
- `test_auto_dismiss_resets_assist_to_none`
- `test_auto_dismiss_clears_path_debounce_timer`

---

## ASS-7 — `_resolve_assist(PICKER)` properly tears down OVERLAY (closes H1)

### Problem

`widget.py:282-333` PICKER branch hides completion overlay inline but doesn't stop `_path_debounce_timer`. Stale path-search timer can post-mount items into a now-stale overlay after PICKER opened.

### Fix

PICKER branch calls `self._hide_completion_overlay()` (the single tear-down site, which also stops the timer) before adding the picker. Inline hide logic deleted.

```python
def _resolve_assist(self, target: AssistKind) -> None:
    current = self.assist
    if current == target:
        return
    # Tear down current ASSIST first.
    if current == AssistKind.OVERLAY:
        self._hide_completion_overlay()
    elif current == AssistKind.PICKER:
        self._hide_skill_picker()
    elif current == AssistKind.GHOST:
        self._clear_ghost_suggestion()
    # Build target.
    if target == AssistKind.OVERLAY:
        ...
    elif target == AssistKind.PICKER:
        ...
    self.assist = target  # single write site
```

### Tests (3)

- `test_overlay_to_picker_stops_path_debounce_timer`
- `test_overlay_to_picker_hides_completion_overlay_widget`
- `test_resolve_assist_idempotent_on_same_target`

---

## ASS-8 — Middle-click paste respects `disabled` (CC-7, partial H5)

### Problem

`widget.py:198-217` `on_click` handles button==2 and inserts pasted text via `safe_run` callback. Callback only checks `is_mounted`; **does not check `self.disabled`**, so paste succeeds while composer is in LOCKED mode (agent streaming). H5 also flagged missing `_sanitize_input_text` call.

### Fix

```python
def on_click(self, event) -> None:
    if event.button != 2:
        return
    if self.disabled:
        return  # composer locked; ignore paste
    cmd = self._primary_selection_cmd()
    safe_run(cmd, on_success=self._handle_paste_result)

def _handle_paste_result(self, out: str) -> None:
    if not self.is_mounted or self.disabled:
        return
    sanitized = self._sanitize_input_text(out)
    self.insert_text(sanitized)
```

### Tests (3)

- `test_middle_click_paste_no_op_when_disabled`
- `test_middle_click_paste_sanitizes_input`
- `test_middle_click_paste_uses_insert_text_not_insert`

---

## ASS-9 — `_show_path_completions` searching=True ordering (closes M6)

### Problem

`input/_path_completion.py:188-199`: order is `_push_to_list([])` → `_set_searching(True)` → `_resolve_assist(OVERLAY)`. Empty-list reactive may dispatch before searching=True is set; user sees one frame of "no results" before shimmer.

### Fix

Reorder:

```python
self._set_searching(True)         # shimmer first
self._push_to_list([])             # clear list under shimmer
self._resolve_assist(AssistKind.OVERLAY)  # show overlay
```

### Tests (1)

- `test_path_search_no_results_flash_before_shimmer`

---

## ASS-10 — `--slash-only` class clears on empty items (closes M9)

### Problem

`completion_list.py:335-359`. When slash-only overlay receives empty items, `--slash-only` class persists; SlashDescPanel still renders for nothing.

### Fix

In `watch_items`:

```python
if not new_items and self.has_class("--slash-only"):
    self.remove_class("--slash-only")
```

### Tests (1)

- `test_slash_only_class_removes_on_empty_items`

---

## ASS-11 — `SkillPickerOverlay` handles Enter inside picker-filter properly (closes H4)

### Problem

`overlays/skill_picker.py:298` `on_key` handles Enter via `event.stop()` + `_dispatch_selected` before Input emits Submitted. Enter inside the filter Input dispatches the highlighted skill — surprising UX.

### Fix

```python
def on_key(self, event) -> None:
    if event.key == "enter":
        focused = self.app.focused
        if getattr(focused, "id", None) == "picker-filter":
            return  # let Input.Submitted handler take it
        ...
```

Wire `on_input_submitted` to also call `_dispatch_selected`. (User can press Enter in filter to confirm typing OR after navigating; both reach the same handler.)

### Tests (2)

- `test_picker_enter_in_filter_does_not_dispatch_skill`
- `test_picker_input_submitted_dispatches_highlighted_skill`

---

## ASS-12 — `_dispatch_selected` saves draft stash (closes M7)

### Problem

`overlays/skill_picker.py:320-334` mutates `inp.value` without `save_draft_stash`. Lost draft when value=`$name` overwrites it. Also silent no-op when `inp.disabled` (action_submit gated).

### Fix

```python
def _dispatch_selected(self, skill: SkillCandidate) -> None:
    inp = self.app.query_one(HermesInput)
    if inp.disabled:
        inp._flash_hint("composer locked — skill not run")
        return
    inp.save_draft_stash()         # preserve current draft per concept locked stash/restore
    inp.value = f"${skill.name}"
    inp.action_submit()
    self.dismiss_overlay()
```

### Tests (3)

- `test_dispatch_selected_saves_draft_stash`
- `test_dispatch_selected_flashes_when_locked`
- `test_dispatch_selected_does_not_call_action_submit_when_disabled`

---

## ASS-13 — Remove duplicated `_rev_query` declaration (closes CC-11)

### Problem

`widget.py:159` declares `self._rev_query: str = ""` in `__init__`; `widget.py:187` declares `_rev_query: reactive[str] = reactive("")` at class level. The `__init__` assignment shadows the reactive; `watch__rev_query` may not fire on changes from `_rev_search_find()`.

### Fix

Delete `self._rev_query = ""` at line 159. Reactive at line 187 provides correct initialization.

### Tests (1)

- `test_rev_query_changes_trigger_watcher`

---

## ASS-14 — Composer-concept doc drift catalogue closure (closes CC-5, CC-6, CC-9, CC-10)

### Problem

The drift catalogue inside `composer-concept.md` lists open items that have been (partially) closed by code:

- **drift §1** — `_completion_overlay_active` reactive mirror: code uses bool flag (closed differently than doc described).
- **drift §6** — `--rev-search` host class: code added it (`_history.py:179, 222`); doc still says "no class today."
- **drift §9** — (not in audit; verify) and **drift §11** — `suggestion` field declared at class level now (`widget.py:89`).
- **drift §10** — `Alt+$` chord trigger: docstring promises it but no binding implements it (CC-10).

### Fix

In `composer-concept.md`, mark each item `CLOSED YYYY-MM-DD` with a one-line note:

```
drift §1: CLOSED 2026-05-02 — superseded by ASSIST reactive (SPEC-ASS).
drift §6: CLOSED 2026-05-02 — --rev-search class added in input/_history.py.
drift §10: REMOVED 2026-05-02 — Alt+$ chord trigger spec dropped; use $ prefix only.
           SkillPickerOverlay docstring updated to remove chord references.
drift §11: CLOSED 2026-05-02 — suggestion field declared at class level in widget.py:89.
```

For drift §10, also remove the `Alt+$` references from `SkillPickerOverlay` docstring + `border_title`.

For CC-12 (out-of-scope `context_menu.py`), add a one-line note to the "Audience/Scope" section of `composer-concept.md`: "ContextMenu is not part of the composer subsystem; do not include in composer audits."

### Tests (2)

- `test_composer_concept_doc_drift_items_closed`  — grep test confirming "CLOSED" annotations on §1, §6, §11; "REMOVED" on §10.
- `test_skill_picker_docstring_no_alt_dollar_chord`

---

## Implementation order

1. **ASS-1** first — introduces `AssistKind` reactive; everything else depends on it.
2. **ASS-2** — chevron/legend/placeholder readers wired to new reactive.
3. **ASS-3 + ASS-4 + ASS-5** — placeholder/legend correctness (BASH-mode regression risk).
4. **ASS-6 + ASS-7** — write-site discipline; closes H1, H2, CC-1.
5. **ASS-8 + ASS-9 + ASS-10 + ASS-11 + ASS-12** — per-overlay fixes, parallel.
6. **ASS-13** — single-line deletion.
7. **ASS-14** — doc closure last; lands with the final code patch.

---

## Test file layout

```python
# tests/tui/test_composer_assist_consolidation.py

class TestAssistReactive: ...           # 3   ASS-1
class TestComputeMode: ...              # 4   ASS-2
class TestPlaceholderPriority: ...      # 2   ASS-3
class TestPlaceholderOverlayBehavior: ...# 3  ASS-4
class TestLegendsLiterals: ...          # 2   ASS-5
class TestAutoDismiss: ...              # 3   ASS-6
class TestResolveAssist: ...            # 3   ASS-7
class TestMiddleClickPaste: ...         # 3   ASS-8
class TestPathSearchOrdering: ...       # 1   ASS-9
class TestSlashOnlyClass: ...           # 1   ASS-10
class TestPickerKeyDispatch: ...        # 2   ASS-11
class TestDispatchSelected: ...         # 3   ASS-12
class TestRevQueryReactive: ...         # 1   ASS-13
class TestDocDriftClosure: ...          # 2   ASS-14
# Total: 33 (estimate 30 in header; this is fine — split into 30 once issues consolidate)
```

Tests use `Pilot`-mounted `HermesInput` (or a `_TestApp(App)` with HermesInput in compose) plus `caplog` for log assertions.

---

## Note on scope creep

CC-12 (context_menu.py is outside composer scope) is intentionally a **doc-only** fix in ASS-14 — no code change. Future composer audits will skip it per the updated scope statement.
