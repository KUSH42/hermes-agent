---
name: DrawbrailleOverlay split spec
description: Spec for splitting drawbraille_overlay.py (2264 lines) into 4 files with 53 tests
type: project
originSessionId: 10a30e1f-42ce-479d-a183-ba3ecb878a4f
---
DONE 2026-04-24; 5 phases + 75 tests merged into feat/textual-migration.

**Completed structure:**
- `_color_utils.py` — `_resolve_color`, `_hex_to_rgb`, `_expand_short_hex`, `_rich_to_hex`; no Textual dep
- `anim_orchestrator.py` — `AnimOrchestrator`; engine selection, carousel, SDF warmup, external trail; 26 tests
- `drawbraille_renderer.py` — `DrawbrailleRenderer`; frame→Text, multi-color gradient, fade alpha; 21 tests
- `drawbraille_overlay.py` — thin Widget shell (~1270 lines post-split); re-exports all public names
- `widgets/anim_config_panel.py` — `AnimConfigPanel`, `AnimGalleryOverlay`, `_GalleryPreview`, `ANIMATION_KEYS`; 10 tests

**Phase 5 additions (commit 93c47af1 on feat/drawbraille-split):**
- 5A: removed 4 dead cfg fields: `adaptive`, `adaptive_metric`, `ease_in`, `ease_out`
- 5B: `_RAIL_POSITIONS` frozenset + `_ambient_allowed()` — non-rail positions skip ambient idle
- 5C: `on_phase_signal` crossfade early-flight guard (progress < 0.5 → skip install, update targets)
- 17 tests in `test_drawbraille_cleanup.py` (C-01–C-14 + extras)

**Key gotchas:**
- `_tick` stays on DrawbrailleOverlay (clock subscriber)
- `_sdf_permanently_failed` cleared via direct attr write in `_do_hide`, NOT in `reset()`
- `cancel_fade_out()` resets BOTH `_fade_state` AND `_fade_alpha`
- `signal("thinking")` + ambient state: skip `on_phase_signal` (transition_to_active owns it)
- `_ambient_allowed()` uses `self.position` reactive (not `_cfg.position`) — drag to non-rail suppresses ambient correctly
