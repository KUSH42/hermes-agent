# Anim Overlay — Persist Settings + Default Position/Size

**Status:** DRAFT
**Date:** 2026-05-02
**Branch base:** `feat/textual-migration`
**Addresses:** Auto-persist `/anim` settings; bottom-right default; compact size default
**Test file:** `tests/tui/test_anim_persist_defaults.py`
**Estimated tests:** 22

---

## Summary

Three related changes to the drawbraille animation overlay:

1. **AP-1 — Auto-persist on close/hide**: When the AnimConfigPanel is dismissed via `action_dismiss()` (Escape key), save the current in-memory config to disk automatically. Currently, the user must press `S` manually or the settings are lost.

2. **AP-2 — Auto-persist on drag-release**: Already partially done (`on_mouse_up` calls `persist_anim_config`), but the `_cfg` is updated in-memory only and the position field written is `"custom"`. This is correct; this spec confirms the contract and adds test coverage for the full round-trip.

3. **AP-3 — Default size: medium (small in compact mode)**: Change `DrawbrailleOverlayCfg.size` default from `"medium"` (already `"medium"` in the dataclass) — **actual gap**: `_cfg_from_mapping` hard-codes `"medium"` too, so this is consistent. The spec adds compact-mode awareness: when `app.compact` is `True` at `show()` time and no user-persisted size exists, use `"small"`.

4. **AP-4 — Default position: bottom-right with 2-cell right margin**: Two changes: `DrawbrailleOverlayCfg.position` default `"center"` → `"bottom-right"`; `_cfg_from_mapping` position fallback `"top-right"` → `"bottom-right"`. The `_apply_layout` `"bottom-right"` formula uses `margin = cfg.position_margin = 2` (2-cell right clearance) and `bottom_safe = 2` (2-cell bottom clearance above the input bar). Both are already correct — no formula changes required.

---

## AP-1 — Auto-persist on AnimConfigPanel close

**Out of scope**: `AnimGalleryOverlay.action_dismiss()` (line ~822 in `drawbraille_overlay.py`) is a separate dismiss path and is intentionally excluded. The gallery `action_select()` mutates `ov.animation` explicitly — users who press Enter/Space intend to save; users who press Escape to exit browsing should not have a half-selected preset auto-persisted. Escape-dismiss of the gallery must remain a no-op save.

### Problem

`AnimConfigPanel.action_dismiss()` (defined in `hermes_cli/tui/widgets/anim_config_panel.py`, line ~357; the class is re-exported from `drawbraille_overlay.py`) only removes the `--visible` class and returns focus. Any in-flight field changes (via `_push_to_overlay`) that have not been explicitly saved with `S` are lost on next startup.

Users expect TUI settings to "just stick" — especially animation/color/size/fps — without a separate save step.

**Why `_do_save()` cannot be called directly**: `_do_save()` (lines ~571–615 of `anim_config_panel.py`) calls `ov.show(cfg)` when `cfg.enabled and cfg.trigger == "always"`, and `ov.hide(cfg)` when `not cfg.enabled`. Calling it from `action_dismiss()` would immediately re-show the `DrawbrailleOverlay` whenever those conditions hold — undoing the user's dismiss.

### Fix

Add a `_save_fields_only()` method that persists the current fields to disk without triggering any overlay visibility changes. Call it from `action_dismiss()`.

**New method** (add to `AnimConfigPanel`, before `_do_save()`):
```python
def _save_fields_only(self) -> None:
    """Persist current fields to disk without touching overlay visibility."""
    payload = _fields_to_dict(self._fields)  # module-level helper, same as _do_save()
    try:
        self.app._svc_commands.persist_anim_config(payload)
    except Exception:
        _log.debug("_save_fields_only: persist failed", exc_info=True)
        return  # don't flash success hint if persist failed
    try:
        from hermes_cli.tui.widgets import HintBar
        bar = self.app.query_one(HintBar)
        bar.hint = "✓ Saved to config"
        def _clear_hint() -> None:
            try:
                self.app.query_one(HintBar).hint = ""
            except NoMatches:
                pass  # HintBar removed before timer fired — harmless
        self.app.set_timer(2.0, _clear_hint)
    except Exception:
        _log.debug("_save_fields_only: hint flash failed", exc_info=True)
```

**Updated `action_dismiss()`** (file: `hermes_cli/tui/widgets/anim_config_panel.py`, line ~357):
```python
def action_dismiss(self) -> None:
    self._save_fields_only()     # persist without re-showing overlay
    self.remove_class("--visible")
    try:
        from hermes_cli.tui.input_widget import HermesInput
        self.app.query_one(HermesInput).focus()
    except (NoMatches, ImportError):
        pass  # NoMatches: widget absent; ImportError: module not yet loaded — focus restoration is best-effort
```

`_save_fields_only()` is unconditional — every dismiss persists the current state. This is simpler and correct: if the user opened and changed nothing, the same values are written (idempotent). A `✓ Saved to config` hint flash (shown only after a successful persist, cleared after 2s via a named `_clear_hint()` inner function matching the `_do_save` pattern) confirms the save to the user. If the user pressed S first, the dismiss hint replaces any existing hint and a new 2s clear timer starts.

**`_push_to_overlay_all()` intentionally omitted**: `_do_save()` calls `_push_to_overlay_all()` before building the payload to sync reactive overlay state back into `_fields`. `_save_fields_only()` skips this — `_fields` is the canonical source of user-edited values in the config panel, and reactive state on the overlay (e.g. the compact `size_name` override from AP-3) is session-local and must not be persisted. `_push_to_overlay_all` must NOT be called from `_save_fields_only()` under any code path.

**`_do_save()` fallback path intentionally dropped**: `_do_save()` falls back to a direct `read_raw_config`/`save_config` write when `persist_anim_config` raises. `_save_fields_only()` does NOT fall back — it logs debug and returns. If `_svc_commands` is not ready at dismiss time, the fields are silently dropped (debug log only). This is intentional: the fallback write path imports the config layer and risks import cycles on dismiss. Accept the rare data loss in exchange for simplicity.

**Deferred import of `HintBar`**: The `from hermes_cli.tui.widgets import HintBar` import inside the try block is intentional. `HintBar` lives in a module that may not be imported when `anim_config_panel.py` is first loaded (to avoid circular imports at module load time). The import is fast (cached after first load) and occurs only in the hint-flash code path, which is already inside a broad `except Exception` guard. The import and the `query_one` call are kept together in a single try/except because an `ImportError` is handled identically to a `NoMatches` error — either way, the hint flash is skipped and logged at DEBUG. Separating them would add code without changing behaviour.

**`_clear_hint` scope clarification**: `_clear_hint` is a nested function (not a coroutine) passed to `self.app.set_timer(2.0, _clear_hint)`. It is invoked by the timer framework after `_save_fields_only()` returns — it executes entirely outside the outer `try/except Exception` block. Therefore the `except NoMatches: pass` inside `_clear_hint` is its sole exception handler; no outer guard catches it. The comment "HintBar removed before timer fired — harmless" is the policy-compliant justification for the narrow-type swallow.

**Edge case**: if `_svc_commands` is not ready, `persist_anim_config` raises — `_log.debug` logs it, the method returns early, and the hint is NOT shown (avoids a false-success flash on failure).

### Behavior table

| Action | Before fix | After fix |
|--------|-----------|-----------|
| Press Escape in config panel | Fields lost | Fields persisted to disk |
| Press S then Escape | Persisted once (S), then again on dismiss | Both saves are idempotent (same values) |
| Open panel, change nothing, Escape | Nothing saved | Save no-op (same values written) |
| Escape while `enabled=True, trigger="always"` | Fields lost | Fields saved; `DrawbrailleOverlay` NOT re-shown |

### Tests

**Common setup for all AP-1 tests**: `AnimConfigPanel.app` is a property inherited from `MessagePump`. In unit tests without a running Textual app, accessing `panel.app` raises `RuntimeError`. Use `mocker.patch.object(type(panel), "app", new_callable=PropertyMock, return_value=mock_app)` (with `mock_app = MagicMock(...)` configured per-test) before calling any panel method. Restore with a matching `mocker` teardown (pytest-mock handles this automatically). This pattern matches `test_anim_overlay.py` line 821.

- `test_ap1_dismiss_calls_save_fields_only`: `spy_save = mocker.patch.object(panel, "_save_fields_only")`; `spy_do_save = mocker.patch.object(panel, "_do_save")`; call `action_dismiss()`; assert `spy_save.call_count == 1`; assert `panel.remove_class.call_args == call("--visible")` (mock `remove_class` via `mocker.patch.object(panel, "remove_class")`); `spy_do_save.assert_not_called()` (self-asserting — do NOT wrap in `assert`) (regression guard — ensures `action_dismiss` never inadvertently calls `_do_save`, which would re-show the overlay under `enabled=True, trigger="always"`). Ordering against `_save_fields_only` is guaranteed by reading the implementation; cross-mock ordering via `call_args_list` cannot span two separate mocked objects without a parent mock.
- `test_ap1_save_fields_only_does_not_call_push_to_overlay_all`: `mocker.patch("hermes_cli.tui.drawbraille_overlay._overlay_config", return_value=DrawbrailleOverlayCfg())`; mock `_push_to_overlay_all` and `app._svc_commands.persist_anim_config`; call `_save_fields_only()` directly; assert `_push_to_overlay_all` was NOT called (verifies the intentional omission — reactive state on the overlay must not bleed into the persisted payload). The `_overlay_config` patch pins a known baseline and prevents `_fields_to_dict` from making disk reads via `read_raw_config()`.
- `test_ap1_dismiss_no_crash_svc_not_ready`: `mocker.patch("hermes_cli.tui.drawbraille_overlay._overlay_config", return_value=DrawbrailleOverlayCfg())`; configure `mock_app._svc_commands.persist_anim_config.side_effect = RuntimeError`; `mock_log = mocker.patch("hermes_cli.tui.widgets.anim_config_panel._log")`; call `action_dismiss()` — no exception propagates; assert `mock_log.debug.call_args[1]["exc_info"] is True`; `mock_app.query_one.assert_not_called()` (self-asserting — do NOT wrap in `assert`) (hint path never entered — `_save_fields_only` returns early after the persist failure, before `query_one(HintBar)` is reached). Do NOT assert `.hint == ""` against a MagicMock; auto-created MagicMock attributes are not `""` and the assertion always fails.
- `test_ap1_overlay_stays_hidden_after_dismiss`: `mocker.patch("hermes_cli.tui.drawbraille_overlay._overlay_config", return_value=DrawbrailleOverlayCfg())` (prevents disk read via `_fields_to_dict` → `_overlay_config()` when `_save_fields_only` runs); mock `app._svc_commands.persist_anim_config` to succeed (returns without raising); initialize panel fields via `panel._build_fields(DrawbrailleOverlayCfg(enabled=True, trigger="always"))` (verify exact method name against source — if `_build_fields` is not the builder, use whatever method populates `panel._fields` from a cfg); `mocker.patch.object(overlay, "show")` (spy); call `action_dismiss()`; assert `overlay.show` NOT called. Without mocking `persist_anim_config`, `_save_fields_only` raises, catches, returns early — the overlay still isn't re-shown, but the assertion passes vacuously rather than actually testing the `enabled=True, trigger="always"` guard.
- `test_ap1_dismiss_hint_shown`: `mocker.patch("hermes_cli.tui.drawbraille_overlay._overlay_config", return_value=DrawbrailleOverlayCfg())`; configure `mock_app.set_timer = MagicMock()`; call `action_dismiss()`; assert `mock_app.query_one(HintBar).hint == "✓ Saved to config"` (MagicMock same-args consistency returns the same mock object for repeated `query_one(HintBar)` calls — no stub mounting needed; the `.hint = ...` assignment and read-back work via MagicMock); assert `mock_app.set_timer.assert_called_once_with(2.0, mocker.ANY)` (self-asserting — do NOT wrap in `assert`)

---

## AP-2 — Drag-release persist (contract + coverage)

### Problem

`DrawbrailleOverlay.on_mouse_up` (file: `hermes_cli/tui/drawbraille_overlay.py`, line ~1227) already calls `persist_anim_config({"position": "custom", "custom_offset_x": ox, "custom_offset_y": oy})` via `self.app._svc_commands`. This is correct.

Gap: the `except Exception` at line ~1253 has a comment (`# app service not ready — drag position not persisted, non-critical`) which satisfies the project exception policy minimum. This spec upgrades it to include a debug log so that failures are visible in debug output without changing runtime behaviour.

### Fix

Add `_log.debug(..., exc_info=True)` to the existing swallow (remove the bare `pass`; the existing comment becomes redundant and can be dropped since the log message conveys the same information):

```python
except Exception:
    _log.debug(
        "on_mouse_up: drag position not persisted",
        exc_info=True,
    )
```

No behavioral change — still non-critical, but now visible in debug logs.

### Tests

- `test_ap2_drag_release_persists_position`: instantiate `DrawbrailleOverlay()` directly (no running app). Build `mock_app = MagicMock(size=MagicMock(width=120, height=30)); mock_app._svc_commands.persist_anim_config = MagicMock()`. Wrap the full test body in `with patch.object(type(overlay), "app", new_callable=PropertyMock, return_value=mock_app): with patch.object(type(overlay), "size", new_callable=PropertyMock, return_value=Size(50, 14)):` — do NOT access `overlay.app` before the patch is active (`overlay.app` before the patch raises `RuntimeError`). Inside the context: set `overlay._dragging=True, overlay._drag_start_sx=10, overlay._drag_start_sy=5, overlay._drag_base_ox=0, overlay._drag_base_oy=0`; `overlay._cfg = DrawbrailleOverlayCfg(position_margin=2)`; `mocker.patch.object(overlay, "_has_nameplate", return_value=False)`; `spy = mocker.patch.object(overlay, "_clamp_offset", wraps=overlay._clamp_offset)` (before event call); construct `event = MouseUp(widget=None, x=15, y=8, delta_x=0, delta_y=0, button=1, shift=False, meta=False, ctrl=False, screen_x=15, screen_y=8)` — all positional args required; `event.stop = MagicMock()` since `on_mouse_up` calls `event.stop()` unconditionally; call `overlay.on_mouse_up(event)`. Note: `from textual.geometry import Size` and `from textual.events import MouseUp` must be imported at the top of the test file. Assert: `mock_app._svc_commands.persist_anim_config.assert_called_once_with({"position": "custom", "custom_offset_x": 5, "custom_offset_y": 3})`; `spy.assert_called_once_with(5, 3, 50, 14, 120, 30)` (raw_ox, raw_oy, overlay_w, overlay_h, screen_w, screen_h — verify arg order against `_clamp_offset` signature; `assert_called_once_with` is self-asserting — do NOT wrap in `assert`). **Arithmetic**: `raw_ox = 0+(15-10)=5`, `raw_oy = 0+(8-5)=3`; clamped values equal raw (within bounds).
- `test_ap2_drag_release_exception_logged`: same mock setup as above; `mock_log = mocker.patch("hermes_cli.tui.drawbraille_overlay._log")`; configure `mock_app._svc_commands.persist_anim_config.side_effect = RuntimeError`; call `overlay.on_mouse_up(event)`; assert `mock_log.debug.call_args[1]["exc_info"] is True`; assert `mock_log.warning.call_count == 0`
- `test_ap2_no_drag_no_persist`: set up overlay with `_dragging=False`; mock `persist_anim_config`; call `on_mouse_up(...)` → assert `persist_anim_config` NOT called

---

## AP-3 — Default size: compact-aware

### Problem

The current default size is `"medium"` in both `DrawbrailleOverlayCfg` (line ~82) and `_cfg_from_mapping` fallback (line ~163). When the overlay is shown in compact mode (terminal < 120 cols or < 30 rows, or `HERMES_DENSITY=compact`), `"medium"` (50×14 cells) occupies a disproportionate amount of screen space.

### Fix

In `DrawbrailleOverlay.show()` (file: `hermes_cli/tui/drawbraille_overlay.py`, line ~687), after loading `cfg` from `_overlay_config()` (which already has `cfg.size`), check if `app.compact` is `True` **and** the persisted size is the factory default (i.e. the user has never explicitly set a size). If so, override `cfg.size = "small"` before applying layout.

"Never explicitly set" detection: if `cfg.size == "medium"` and the raw config dict has no `"size"` key under `display.drawbraille_overlay`, treat it as the default. The simplest approach: expose a sentinel from `_overlay_config()` or check `_cfg_from_mapping` directly. Simplest: call `read_raw_config()` and check if `"size"` key is absent.

**Simpler alternative** (preferred): skip the sentinel complexity. Extract the compact-size logic into a small `_effective_size` helper, then call it from `show()`. The helper is the testable unit:

```python
def _effective_size(self, cfg: DrawbrailleOverlayCfg) -> str:
    """Return the size name to use for this session, applying compact override if appropriate."""
    try:
        if self.app.compact and cfg.size == "medium":
            return cfg.compact_size  # "small" by default
    except (RuntimeError, AttributeError):
        # RuntimeError: NoActiveAppError when no active app context (test harness) — compact check skipped
        # AttributeError: app not a HermesApp / compact attr absent on test stub — skip override
        pass
    return cfg.size
```

In `show()`, replace the existing `self.size_name = cfg.size` line with:

```python
self.size_name = self._effective_size(cfg)
```

Note: `self.app.compact` is a `reactive[bool]` on `HermesApp` and will not raise under normal operation. `RuntimeError` (`NoActiveAppError`) covers the no-app-context case; `AttributeError` covers test stubs that lack the `compact` attribute. These are the only two plausible failure modes.

**Insertion point**: the existing `self.size_name = cfg.size` assignment (current line 704) is replaced by `self.size_name = self._effective_size(cfg)`. No other changes to `show()` are required.

This respects explicit user overrides (if user set `size = "small"` or `size = "large"`, `cfg.size != "medium"` condition prevents the override from kicking in incorrectly). If user explicitly sets `size = "medium"`, compact override still fires — acceptable tradeoff given that `medium` in compact mode is too large. No config schema documentation is required; this tradeoff is a consequence of the `cfg.size == "medium"` heuristic and is intentional.

**Size/reactive divergence note**: `show()` sets `self.size_name` (the reactive) to `effective_size`, but stores `self._cfg = cfg` where `cfg.size` may still be `"medium"`. This is intentional — `_apply_layout` reads `self.size_name`, not `cfg.size`. `AnimConfigPanel._do_reset` reads from `DEFAULT_CONFIG` (not `self._cfg`), so the divergence is harmless.

**Compact override is session-local**: The compact override sets `DrawbrailleOverlay.size_name` (a reactive on the overlay widget). `AnimConfigPanel._fields` is rebuilt from `_overlay_config()` which reads disk config, not the reactive. Therefore `_save_fields_only()` always writes the persisted `cfg.size` (e.g. `"medium"`) to disk, never the session-local compact override. This is correct — the override fires again on every `show()` call, so there is nothing to persist.

**Dataclass change** (`DrawbrailleOverlayCfg`, line ~82, after `custom_offset_y`):
```python
compact_size: str = "small"
```

**`_cfg_from_mapping` change** (after `custom_offset_y=...` kwarg, before the closing paren — must ship atomically with the dataclass change to avoid `TypeError`):
```python
compact_size=str(d.get("compact_size", "small")),
```

**`DEFAULT_CONFIG`**: Before shipping, grep `DEFAULT_CONFIG` for `"compact_size"`. If absent (expected), `_cfg_from_mapping`'s fallback to `"small"` covers `_do_reset()` and no update is needed. If present with a value other than `"small"`, update `DEFAULT_CONFIG["display"]["drawbraille_overlay"]["compact_size"] = "small"` to stay consistent.

**Pre-existing divergence (out of scope)**: `DrawbrailleOverlayCfg.vertical` defaults to `False`, but `_cfg_from_mapping` defaults `vertical=True` (i.e. `bool(d.get("vertical", True))`). This inconsistency predates this spec and is not addressed here. **Do NOT fix the `vertical` default inconsistency as part of this PR** — it has downstream test expectations and requires a separate spec.

### Behavior table

Note: the compact override only fires when `cfg.enabled == True` and `show()` runs past its early-return guard. When `enabled=False`, `show()` returns before reaching the size branch — no-op.

Note: do not add a "user explicitly chose medium" sentinel to compensate for the `cfg.size == "medium"` heuristic. This spec intentionally accepts the tradeoff to avoid config complexity. `test_ap3_explicit_medium_in_compact_still_overridden` documents and locks the accepted behavior.

| Terminal mode | `cfg.size` | `cfg.enabled` | Result |
|---------------|-----------|---------------|--------|
| normal        | `"medium"` (default) | `True` | `"medium"` used |
| compact       | `"medium"` (default) | `True` | `"small"` used |
| compact       | `"medium"` (user-set explicitly) | `True` | `"small"` used (known tradeoff; intentional — do not add a "user explicitly chose medium" sentinel) |
| compact       | `"large"` (user set) | `True` | `"large"` used (no override; `!= "medium"`) |
| normal        | `"small"` (user set) | `True` | `"small"` used |
| compact       | any | `False` | `show()` returns early — compact override and `size_name` assignment are never reached; overlay state unchanged |

### Tests

- `test_ap3_compact_mode_uses_small`: `app.compact = True`, `cfg.size = "medium"` → `overlay.size_name == "small"` after `show()`
- `test_ap3_normal_mode_uses_medium`: `app.compact = False` → `overlay.size_name == "medium"`
- `test_ap3_explicit_size_not_overridden`: `app.compact = True`, `cfg.size = "large"` → `overlay.size_name == "large"`
- `test_ap3_compact_size_field_roundtrip`: `_cfg_from_mapping({"compact_size": "medium"})` → `cfg.compact_size == "medium"`
- `test_ap3_compact_size_field_default`: `DrawbrailleOverlayCfg()` → `cfg.compact_size == "small"` (new field has correct default)
- `test_ap3_explicit_medium_in_compact_still_overridden`: simulate a user-persisted `"medium"` by round-tripping through `_cfg_from_mapping({"size": "medium"})` to get `cfg` (distinct code path from the dataclass default); `app.compact = True`; call `overlay._effective_size(cfg)`; assert return value is `"small"`. Documents the known tradeoff: the heuristic cannot distinguish default-`"medium"` from user-set-`"medium"` — both get overridden in compact mode. The round-trip through `_cfg_from_mapping` makes this test genuinely distinct from `test_ap3_compact_mode_uses_small`.
- `test_ap3_enabled_false_compact_override_skipped`: `cfg = DrawbrailleOverlayCfg(enabled=False, size="medium")`; mock `type(overlay).app` with `compact=True`; set `overlay.__dict__["size_name"] = "medium"` as the baseline BEFORE calling `show()` (because the existing test helper initialises `size_name="small"`, which would cause a false-positive `!= "small"` assertion); call `overlay.show(cfg)` (no mocking of `_apply_layout` needed — `show()` returns before reaching any side-effects when `enabled=False`, at line ~691); assert `overlay.size_name == "medium"` (exact equality — confirms compact override was never applied). Covers the behavior table row "compact, any, False → overlay state unchanged".
- `test_ap3_show_compact_sets_size_name_small`: wiring test — verifies `show()` actually calls `self._effective_size(cfg)` on the `enabled=True` path. Mock `type(overlay).app` with `compact=True`; mock `_apply_layout` to no-op; mock `_start_anim` to no-op (or pre-set `_renderer`/`_orchestrator` as done in `_overlay_with_mock_app` helper); call `overlay.show(DrawbrailleOverlayCfg(enabled=True, size="medium"))`; assert `overlay.size_name == "small"`. A refactoring error that keeps `self.size_name = cfg.size` instead of `self.size_name = self._effective_size(cfg)` would fail this test while all isolated `_effective_size` tests still pass.
- `test_ap3_no_active_app_falls_back_to_cfg_size`: test the extracted `_effective_size(cfg: DrawbrailleOverlayCfg) -> str` helper directly (see Fix section — this helper must be extracted to make the test feasible). No app context is needed. Call `overlay._effective_size(DrawbrailleOverlayCfg(size="medium"))` with `mocker.patch.object(type(overlay), "app", new_callable=PropertyMock, side_effect=RuntimeError("no app"))`. Assert return value is `"medium"` (override skipped, no exception propagated). This avoids the combinatorial mock surface of all `self.app` access points inside `show()`.

---

## AP-4 — Default position: bottom-right with 1-cell padding

### Problem

Default position is `"center"` in `DrawbrailleOverlayCfg` (line ~81) and in `_cfg_from_mapping` (line ~163). Center blocks the output pane content. Bottom-right, above the input bar, is less intrusive.

Current `"bottom-right"` math in `_apply_layout` (line ~1174):
```python
"bottom-right": (tw - w - margin, th - h - bottom_safe),
```
where `margin = cfg.position_margin = 2` (default) and `bottom_safe = 2`. This already places the overlay 2 cells above the bottom edge, clearing the input bar. The 1-cell right padding is provided by `margin = 2` (1-cell padding = `margin >= 1`; `margin = 2` satisfies this).

**The fix is minimal**: change `"center"` → `"bottom-right"` in `DrawbrailleOverlayCfg.position`, and change `"top-right"` → `"bottom-right"` in `_cfg_from_mapping`'s position fallback (the two sites use different "before" values).

### Fix

**`DrawbrailleOverlayCfg` dataclass** (`hermes_cli/tui/drawbraille_overlay.py`, line ~82):
```python
# Before
position: str = "center"
# After
position: str = "bottom-right"
```

**`_cfg_from_mapping` fallback** (line ~163):
```python
# Before
position=str(d.get("position", "top-right")),
# After
position=str(d.get("position", "bottom-right")),
```

Note: `_cfg_from_mapping` currently falls back to `"top-right"` (not `"center"`), which is inconsistent with the dataclass default. Both should be `"bottom-right"`.

**Preset updates**: The `"hacker"` preset already uses `"top-right"` explicitly — no change needed. The `"minimal"` and `"balanced"` presets omit `position` — they will inherit the new default. That is acceptable (both are small-sized overlays).

**`DEFAULT_CONFIG` and `_do_reset()` behaviour**: `DEFAULT_CONFIG["display"]["drawbraille_overlay"]["position"]` is currently `"top-right"` (not `"center"` and not `"bottom-right"`). This value is intentionally left unchanged by this PR — changing it would alter the user-facing reset target in a separate UX decision. After AP-4, `_do_reset()` still yields `position = "top-right"` (read from `DEFAULT_CONFIG`), not `"bottom-right"` (the new dataclass/mapping default). This is acceptable: `_do_reset()` restores to the explicit-config baseline, while AP-4 changes only what happens on a fresh install with no config file.

**Class-level reactive**: `DrawbrailleOverlay` has a class-level `position: reactive[str] = reactive("center")` (line ~495). Leave it as `reactive("center")` — do not change it. The reactive is only relevant before the first `show()` call (when the overlay is hidden), and `_apply_layout` is never called before `show()` sets `self.position = cfg.position`. Changing the reactive default would not change observable behavior but would add an unnecessary diff.

### Behavior table

| Scenario | Before | After |
|----------|--------|-------|
| Fresh install, no config (runtime: `_cfg_from_mapping({})`) | `"top-right"` (`_cfg_from_mapping` fallback) | `"bottom-right"` |
| `DrawbrailleOverlayCfg()` instantiated directly (tests/tooling) | `"center"` (dataclass default) | `"bottom-right"` (dataclass default updated) |
| User set `position = "center"` in config | `"center"` | `"center"` (config wins) |
| User has `position = "top-right"` persisted (pre-fix installs) | `"top-right"` | `"top-right"` (config wins; no migration needed) |
| `_do_reset()` called | `"top-right"` (from `DEFAULT_CONFIG`) | `"top-right"` (unchanged — `DEFAULT_CONFIG` not updated in this PR) |

### Tests

- `test_ap4_default_position_is_bottom_right`: `DrawbrailleOverlayCfg()` → `cfg.position == "bottom-right"`
- `test_ap4_cfg_from_mapping_empty_defaults`: `_cfg_from_mapping({})` → `cfg.position == "bottom-right"`
- `test_ap4_cfg_from_mapping_explicit_center`: `_cfg_from_mapping({"position": "center"})` → `cfg.position == "center"`
- `test_ap4_dataclass_and_mapping_consistent`: assert `DrawbrailleOverlayCfg().position == _cfg_from_mapping({}).position == "bottom-right"` (both sites agree)
- `test_ap4_bottom_right_offset_within_bounds`: instantiate `DrawbrailleOverlay()` directly (no running app required — `_apply_layout` is synchronous and does not access `self.app`). Mock app size via `mocker.patch.object(type(overlay), "app", new_callable=PropertyMock, return_value=MagicMock(size=Size(width=120, height=30)))`. Note: `_apply_layout` reads `w, h` from `sizes[self.size_name]` (e.g. `sizes["medium"] = (50, 14)`) — it does NOT read `self.size` (the Widget data descriptor), so no `type(overlay).size` PropertyMock is needed. `overlay._cfg = DrawbrailleOverlayCfg(position_margin=2)`; `overlay.size_name = "medium"`; `mocker.patch.object(overlay, "_has_nameplate", return_value=False)`; `mocker.patch.object(overlay, "_set_offset")`; `overlay.position = "bottom-right"`; call `overlay._apply_layout()` → assert `overlay._set_offset.call_args == call(68, 14)` (= `tw-w-margin=120-50-2=68`, `th-h-bottom_safe=30-14-2=14`)

---

## Implementation order

1. AP-4 (default position) — pure constant changes, zero risk
2. AP-3 (compact size) — add dataclass field + `show()` branch
3. AP-2 (drag-release log) — one-line exception hygiene fix
4. AP-1 (auto-persist on close) — `action_dismiss()` change + tests

No dependency between AP-4 and AP-3. AP-2 and AP-1 are independent of AP-3/AP-4.

**Consistency note**: AP-3's `compact_size` field addition to `DrawbrailleOverlayCfg` and the corresponding `_cfg_from_mapping` kwarg update should ship in the same commit for round-trip consistency — so that `_cfg_from_mapping` immediately populates the new field from persisted config. Shipping the dataclass field alone is not a runtime error (the field has a default, so `DrawbrailleOverlayCfg(...)` calls that omit `compact_size=` are valid Python), but it leaves the mapping stale until the second commit.

---

## Files touched

| File | Change |
|------|--------|
| `hermes_cli/tui/drawbraille_overlay.py` | AP-4: `"center"` → `"bottom-right"` (×2); AP-3: add `compact_size` field; AP-2: swallow → debug log |
| `hermes_cli/tui/widgets/anim_config_panel.py` | AP-1: add `_save_fields_only()`; `action_dismiss()` calls `_save_fields_only()` instead of `_do_save()` |
| `tests/tui/test_anim_persist_defaults.py` | New test file, 22 tests |
