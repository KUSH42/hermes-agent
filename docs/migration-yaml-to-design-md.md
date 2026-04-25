# Migration: YAML skins → DESIGN.md

This document describes the transition from legacy `skins/<name>.yaml` files
to the canonical DESIGN.md per-skin directory layout.

## Layout

| Skin source | Canonical location | Legacy location |
|---|---|---|
| Bundled | `skins/<name>/DESIGN.md` | `skins/<name>.yaml` |
| User    | `<HERMES_HOME>/skins/<name>/DESIGN.md` | `<HERMES_HOME>/skins/<name>.yaml` |

## Schema

DESIGN.md skin files contain YAML front matter with these top-level keys:

- `name`, `description`, `version`
- `colors.*` — standard palette tokens. Hyphenated keys (e.g. `banner-title`)
  normalize to underscored entries in `SkinPayload.colors` (`banner_title`).
- `components.*` — DESIGN.md standard component tokens (informational; not
  consumed by Hermes runtime).
- `x-hermes.*` — Hermes-specific namespace:
  - `semantic` — overrides for `colors.*` semantic fan-out
  - `component-vars` — TUI CSS component variables (Textual `$name` overrides)
  - `syntax.scheme` + `syntax.overrides` — `SYNTAX_SCHEMES` selection + per-token
    overrides
  - `diff` — diff renderer hex/string fields
  - `markdown` — Rich markdown style fields
  - `spinner` — spinner faces, verbs, wings, style
  - `branding` — agent name, welcome/goodbye, prompt symbol, etc.
  - `tool_prefix`, `tool_icons`
  - `banner_logo`, `banner_hero`
  - `vars` — raw Textual CSS variable passthrough (parity with legacy `vars:`
    block; e.g. `preview-syntax-theme`)

## Token references

String values may reference other tokens via `{dotted.path}` syntax. Refs are
resolved against `colors.*`. Cycles and unresolved refs raise `SkinError`.

## Hot reload

`ThemeManager` watches `<skin-dir>/DESIGN.md` only. Edits to `lint-report.md`,
`tokens.dtcg.json`, or any adjacent legacy YAML do not retrigger reloads.

## Deprecation timeline

- Phase 0–3: legacy YAML loaded silently.
- Phase 4: user YAML-only loads emit `DeprecationWarning` (the deprecation
  release marker is `_YAML_DEPRECATED_SINCE` in `hermes_cli/skin_engine.py`).
- Phase 5 (DM-K3): legacy YAML paths removed once
  `_yaml_removal_unblocked(current_version)` returns `(True, [])`.

## DM-J export artifacts

CI runs `npx -y @google/design.md lint` and `... export --format dtcg` for
every bundled skin. Lint findings live in `skins/<name>/lint-report.md` with
a `warning_baseline` integer in the front matter (regression gate).
DTCG output lands at `skins/<name>/tokens.dtcg.json` and is **never** read
by the Hermes runtime.
