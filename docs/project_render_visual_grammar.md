---
name: Render Visual Grammar spec
description: MERGED into feat/textual-migration — G1/G2/G3/G4; 2 commits fa273f42+3c4a15e0
type: project
originSessionId: 22afb1c4-e0fb-4a07-8330-28ad17a660e7
---
IMPLEMENTED 2026-04-24; commits fa273f42 + 3c4a15e0; MERGED into feat/textual-migration.

**Why:** Kills hex literals and independent layout decisions in renderer bodies; provides shared glyph/color/header/gutter/rule helpers; adds `BodyFooter` sticky affordance footer.

Key files:
- `hermes_cli/tui/body_renderers/_grammar.py` — new; `SkinColors`, `BodyFooter`, glyph/builder helpers
- `hermes_cli/tui/body_renderers/base.py` — `app=` kwarg + lazy `colors` property
- `shell.py`/`fallback.py` — `build_widget` overrides deleted
- `search.py` — `<=100` hits delegates to `super().build_widget()`
- `_completion.py` — `_swap_renderer` passes `app=`, mounts `BodyFooter`; `_maybe_swap_renderer` removes `--streaming` first
- `services/tools.py` — `panel.add_class("--streaming")` on tool open
- 23 tests in `tests/tui/test_render_visual_grammar.py`

**syntax-theme note:** Not in COMPONENT_VAR_DEFAULTS (non-hex; `test_defaults_as_strs_all_hex` enforces hex-only). In skins only; `SkinColors.from_app` falls back to `"ansi_dark"`.

**latent bug (SYN-1):** `validate_skin_payload` hex-validates ALL component_vars — `syntax-theme: 'catppuccin'` raises `SkinValidationError` on `_load_path`. No test catches it. Fix is in skin-palette spec (SYN-1: `_NON_HEX_COMPONENT_VARS` allowlist).
