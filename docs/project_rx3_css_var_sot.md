---
name: RX3 CSS var single-source-of-truth
description: Phases 1-3 merged (89b89a53); build_skin_vars + VarSpec shim + validator + 3-step fallback; Phase 4 (generator block install) deferred
type: project
originSessionId: 134412db-262b-4173-8095-f58ad695ec26
---
**Spec:** `/home/xush/.hermes/2026-04-22-tui-v2-RX3-css-var-single-source-spec.md` (approved 9.6/10 after 3 review iterations).

**Merged:** 89b89a53 onto feat/textual-migration, 4 commits on branch `feat/tui-v2-rx3-css-var-single-source`:
- `c7cceb9a` fix(skins): dedent bug in all 4 bundled skins (plan-now-fg/pane-border were dropping out of component_vars: block → yaml.safe_load raised → ThemeManager.load caught Exception → skin silently ignored; users loading /skin matrix only saw COMPONENT_VAR_DEFAULTS)
- `67ee15bc` fix(tcss): 14 $-referenced defaults declared in hermes.tcss (app-bg, cursor-*, chevron-*, fps-hud-bg, scrollbar, drawille-canvas-color, ghost-text-color)
- `7e64aaeb` feat(theme): VarSpec + _default_of + _defaults_as_strs shim; SkinValidationError + validate_skin_payload; load_with_fallback 3-step chain (configured → default.yaml → emergency COMPONENT_VAR_DEFAULTS-only, each logged SKIN_LOAD_FAILED/SKIN_DEFAULT_FAILED/SKIN_EMERGENCY_FALLBACK)
- `69b57a5b` feat(build): hermes_cli/tui/build_skin_vars.py scanner+generator+CLI; tests/tui/test_css_var_single_source.py — T1-T8 + T6b, 19 tests + 1 xfail (Phase 4 gate)

**Call-site contract (T8-enforced):** every read of `COMPONENT_VAR_DEFAULTS` must go through `_default_of(v)` or `_defaults_as_strs()`. Grep test blocks raw `COMPONENT_VAR_DEFAULTS[...]` access outside `theme_manager.py` and `build_skin_vars.py`.

**Added 5 new COMPONENT_VAR_DEFAULTS keys:** `tool-glyph-mcp`, `error-timeout`, `error-critical`, `error-auth`, `error-network` — pre-existing $ refs in tool_category.py and tool_result_parse.py but never in defaults.

**CLI:**
- `python -m hermes_cli.tui.build_skin_vars --matrix` — drift report (reference / tcss-decl / py-default / docstring / per-skin coverage).
- `--check` — CI drift gate (no-op until Phase 4 block install).
- `--fill-skin PATH` — scaffold missing keys into a skin YAML with defaults.
- default (no flag) — regenerate TCSS + docstring blocks (Phase 4 target).

**TEXTUAL_BUILTIN_VARS** introspected from `App().get_css_variables()` at import. Pinned to Textual 8.x with `assert textual.__version__.startswith("8.")`. Enumerated `TEXTUAL_BUILTIN_VARS_FALLBACK` kicks in on degraded-env import paths.

**Phase 4 deferred** — freeze-window PR requirement (no concurrent hermes.tcss declaration edits from open R-branches). Flips `COMPONENT_VAR_DEFAULTS: dict[str, str]` → `dict[str, VarSpec]` (pure value-type change — all call sites already use shim), replaces hand-written tcss decl block with generated BEGIN/END-marker block (strict alphabetical from run #1 → one-time reorder diff in the install commit), adds `.pre-commit-config.yaml` `--check` entry.

**Why:** recurring gotcha — every new component var needed 3 coordinated edits (defaults / tcss / docstring); misses were silent render bugs. Before RX3 shipped, I found 4 bundled skins that had been completely broken (dedent bug) since commit fdff67c7 never caught it.

**How to apply:** when adding a new component var, still edit 3 places today (defaults + tcss + docstring) PLUS each bundled skin's component_vars (use `--fill-skin`). T1/T2/T3/T8 catch omissions in CI. After Phase 4 lands, edit only COMPONENT_VAR_DEFAULTS + run generator.
