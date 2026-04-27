---
name: New Animation Engines + /anim Command Improvements spec
description: 5 new engines + /anim speed/ambient/preview-duration + Part D move/resize/color; 51 tests; Implemented 2026-04-22
type: project
originSessionId: d42aaadf-2412-4683-8f6b-06be35c05fb7
---
Spec at `/home/xush/.hermes/2026-04-22-anim-engines-new-spec.md` — **Implemented** 2026-04-22, commit `0c05c223` on `feat/textual-migration`. 51/51 tests passing.

**Why:** Fill visual variety gaps in engine gallery (no 3D wireframe, no fractal, no demoscene, no particle-rain); unblock CLI power-users from needing config panel for FPS/ambient tweaks; add live overlay positioning and color CLI commands.

**How to apply:** Implement in order: `_bresenham_pts` helper → 5 engine classes → registry entries in drawille_overlay.py → B1/B2/B3 in _app_commands.py → Part D (D1–D5) → 51 tests.

Key gotchas baked into spec:
- `TrailCanvas.frame()` already decays — no separate `tick()` call (doesn't exist)
- `ov.fps = fps` (reactive), not `ov._fps`
- `ov._visibility_state` in B3, not `self._visibility_state`
- `_TORUS_TILT_COS/_SIN` are module-level constants (cos/sin of π/6); `rot_y` and `theta` LUTs hoisted outside inner loops
- `_PHASE_CATEGORIES` unchanged — new engines slot in via category membership automatically
- D1 uses `Ctrl+Shift+Arrow` (not Alt+Arrow — those are taken by browse-mode turn nav)
- D2 `_set_offset(ox, oy)` helper keeps `_drag_base_ox/oy` in sync with all 3 `_apply_layout` offset paths
- D3 gradient handler validates both color1 and color2 through `_validate_hex` inner fn; invalid hex returns early
- D3 `self.app._persist_anim_config(...)` in `DrawilleOverlay.on_mouse_up` (overlay can't call app mixin methods directly)
