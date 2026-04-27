---
name: Skin Palette spec
description: DRAFT — SYN-1/2/3; syntax-scheme for YAML skins + SkinColors.resolve_syntax_palette(); 22 tests
type: project
originSessionId: 22afb1c4-e0fb-4a07-8330-28ad17a660e7
---
DRAFT 2026-04-24; spec at /home/xush/.hermes/2026-04-24-skin-palette-spec.md

**Why:** YAML TUI skins have `syntax-theme` (pygments) but no access to SYNTAX_SCHEMES rich token palettes. Also fixes latent SYN-1 bug: `validate_skin_payload` rejects `syntax-theme: 'catppuccin'` as non-hex on every skin load.

**How to apply:** Branch from feat/textual-migration. Implement after render-visual-grammar is merged.

Issues:
- **SYN-1** — `_NON_HEX_COMPONENT_VARS` frozenset in `theme_manager.py`; skip hex check for `syntax-theme`+`syntax-scheme` in `validate_skin_payload`. 5 tests.
- **SYN-2** — `SkinColors.syntax_scheme: str` field + `resolve_syntax_palette(overrides?) -> dict` method; `from_app` reads `syntax-scheme` with non-hex bypass. 9 tests.
- **SYN-3** — 4 bundled skins get `syntax-scheme:` in component_vars (catppuccin/tokyo-night/solarized-dark→matching name, matrix→hermes); scan test; scheme resolves to known SYNTAX_SCHEMES entry. 8 tests.

NOT in COMPONENT_VAR_DEFAULTS (non-hex). NOT in hermes.tcss (would be orphan). Lives only in skins + SkinColors.
