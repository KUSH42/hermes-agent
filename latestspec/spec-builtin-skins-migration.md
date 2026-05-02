---
title: Builtin Skins Migration — _BUILTIN_SKINS → DESIGN.md Files
status: DRAFT
author: claude-sonnet-4-6
date: 2026-05-03
---

# Builtin Skins Migration

**Status:** DRAFT

## Problem

The 7 builtin skins (`default`, `ares`, `mono`, `slate`, `poseidon`, `sisyphus`, `charizard`) are hard-coded Python dicts in `hermes_cli/skin_engine.py` (`_BUILTIN_SKINS`). They only define `colors`, `spinner`, `branding`, and a few misc keys.

When loaded, `_builtin_skin_to_css()` derives ~29 of the 82 required `component_vars` from those color keys. The remaining ~53 vars (all `tool-tier-*-accent`, `browse-*`, `cite-chip-*`, `reasoning-accent`, etc.) fall back to `COMPONENT_VAR_DEFAULTS`, which are the gold/hermes defaults — visually wrong on ares, mono, slate, etc.

The 4 file-based skins (`catppuccin`, `matrix`, `solarized-dark`, `tokyo-night`) already use `skins/<name>/DESIGN.md` and have all 82 required vars defined. This spec migrates the 7 builtins to the same format.

## Goals

1. All 11 skins define all 82 required `component-vars` explicitly.
2. No Python-dict skin data remains in `skin_engine.py`.
3. Bundled skins ship with the package (importable at runtime without `HERMES_HOME`).
4. User skins in `HERMES_HOME/skins/` still override bundled skins by name.
5. Emergency fallback (bare `COMPONENT_VAR_DEFAULTS`) still works.

## Non-goals

- Changing the DESIGN.md format or schema.
- Migrating legacy `.yaml` user skins.
- Touching the 4 existing `skins/*/DESIGN.md` files (already correct).

---

## Architecture

### Skin resolution order (unchanged semantics, new step 0)

```
0. HERMES_HOME/skins/<name>/DESIGN.md     ← user override (wins)
1. HERMES_HOME/skins/<name>.yaml          ← legacy user override
2. hermes_cli/skins/<name>/DESIGN.md      ← bundled (NEW — replaces _BUILTIN_SKINS)
3. Emergency fallback (COMPONENT_VAR_DEFAULTS)
```

Step 2 is the only new thing. Everything else is unchanged.

### New bundled skins dir

`hermes_cli/skins/` — lives inside the Python package, so it ships with `pip install`.

Move the existing 4 skins from `skins/` (project root) → `hermes_cli/skins/`:

```
hermes_cli/skins/
  catppuccin/DESIGN.md        (move from skins/catppuccin/DESIGN.md)
  matrix/DESIGN.md            (move from skins/matrix/DESIGN.md)
  solarized-dark/DESIGN.md    (move from skins/solarized-dark/DESIGN.md)
  tokyo-night/DESIGN.md       (move from skins/tokyo-night/DESIGN.md)
  default/DESIGN.md           (NEW — was _BUILTIN_SKINS["default"])
  ares/DESIGN.md              (NEW — was _BUILTIN_SKINS["ares"])
  mono/DESIGN.md              (NEW — was _BUILTIN_SKINS["mono"])
  slate/DESIGN.md             (NEW — was _BUILTIN_SKINS["slate"])
  poseidon/DESIGN.md          (NEW — was _BUILTIN_SKINS["poseidon"])
  sisyphus/DESIGN.md          (NEW — was _BUILTIN_SKINS["sisyphus"])
  charizard/DESIGN.md         (NEW — was _BUILTIN_SKINS["charizard"])
```

Multi-line `banner_logo` / `banner_hero` values use YAML literal block scalars (`|`).

---

## Code changes

### `pyproject.toml`

Add to `[tool.setuptools.package-data]`:
```toml
hermes_cli = ["web_dist/**/*", "skins/**/*"]
```

### `skin_engine.py` — additions

**New helper `_bundled_skins_dir() → Path`:**
```python
def _bundled_skins_dir() -> Path:
    """Path to the skins/ dir bundled inside the hermes_cli package."""
    return Path(__file__).parent / "skins"
```

**Update `_resolve_user_skin_path()` → rename to `_resolve_skin_path()`:**
Extend resolution to also check the bundled dir:
```python
def _resolve_skin_path(name: str) -> Optional[Path]:
    """User skin (HERMES_HOME/skins/) > bundled skin (hermes_cli/skins/)."""
    # 1. User DESIGN.md
    user_dm = _skins_dir() / name / "DESIGN.md"
    if _design_md_discovery_enabled() and user_dm.is_file():
        return user_dm
    # 2. User legacy YAML
    user_yaml = _skins_dir() / f"{name}.yaml"
    if user_yaml.is_file():
        return user_yaml
    # 3. Bundled DESIGN.md
    bundled_dm = _bundled_skins_dir() / name / "DESIGN.md"
    if bundled_dm.is_file():
        return bundled_dm
    return None
```

**Update `list_skins()`:**
Scan `_bundled_skins_dir()` for DESIGN.md skins (source: `"builtin"`), then user skins (source: `"user"`). User skins with the same name as bundled skins are de-duped (user wins).

**Update `load_skin()`:**
Replace `_BUILTIN_SKINS` lookup with `_resolve_skin_path(name)` call. If nothing found, use bundled `default/DESIGN.md` as fallback.

### `skin_engine.py` — removals

Remove after migration is complete and tests pass:
- `_BUILTIN_SKINS` dict (~450 lines)
- `_build_skin_config()` (~75 lines)
- `_builtin_skin_to_css()` (~90 lines, only needed by `ThemeManager.load_skin()`)

**`theme_manager.py` — update `load_skin()`:**
Remove the `else:` branch that calls `_builtin_skin_to_css()`. Since all named skins now load via `_resolve_skin_path()`, the DESIGN.md path always applies. The `_builtin_skin_to_css()` usage in `ThemeManager.load_skin()` (line 645) can be deleted.

---

## New DESIGN.md files — component-vars values

Each new file must define all 82 required vars. Values derived from the existing `colors` dict in `_BUILTIN_SKINS`. Below are the key mappings per skin.

### Shared tone variants (same for all skins)
```yaml
error-dim: "#8B2020"
success-dim: "#1E5C1E"
warning-dim: "#5C4A00"
text-muted-dim: "#3A3A3A"
error-auth: "#eab308"
error-network: "#f97316"
error-timeout: "#f59e0b"
```

### Per-skin `tool-tier-*-accent` strategy

| Skin | read/search/browse/thinking/tooling/query/file | write/exec/shell | mcp/agent |
|---|---|---|---|
| default | `#FFBF00` (gold accent) | `#4caf50` | `#9b59b6` / `#FFBF00` |
| ares | `#C7A96B` (bronze) | `#4caf50` | `#9b59b6` / `#C7A96B` |
| mono | `#aaaaaa` | `#cccccc` | `#888888` / `#e6edf3` |
| slate | `#7eb8f6` | `#63D0A6` | `#9b59b6` / `#8EA8FF` |
| poseidon | `#5DB8F5` | `#4caf50` | `#9b59b6` / `#A9DFFF` |
| sisyphus | `#D3D3D3` | `#919191` | `#B7B7B7` / `#F5F5F5` |
| charizard | `#F29C38` | `#4caf50` | `#9b59b6` / `#FFD39A` |

---

## Files changed

| File | Change |
|---|---|
| `pyproject.toml` | Add `skins/**/*` to package-data |
| `hermes_cli/skins/` | New dir with 11 DESIGN.md files |
| `skins/catppuccin/` → `hermes_cli/skins/catppuccin/` | Move |
| `skins/matrix/` → `hermes_cli/skins/matrix/` | Move |
| `skins/solarized-dark/` → `hermes_cli/skins/solarized-dark/` | Move |
| `skins/tokyo-night/` → `hermes_cli/skins/tokyo-night/` | Move |
| `hermes_cli/skin_engine.py` | Add `_bundled_skins_dir()`, update resolution, remove `_BUILTIN_SKINS`+helpers |
| `hermes_cli/tui/theme_manager.py` | Remove `_builtin_skin_to_css()` call path |

## Tests

Target test files:
- `tests/tui/test_eh_c_overlays.py` (config overlay skin picker)
- `tests/tui/test_bar_snr_p0.py` (skin switching coverage)
- New: `tests/test_skin_coverage.py` — parametrized over all 11 bundled skins; asserts all 82 required vars are present and valid hex after `load_skin(name)`.

No full suite run needed. Targeted files only.

## Estimated scope

- ~550 lines deleted from `skin_engine.py`
- ~11 DESIGN.md files created (~120 lines each = ~1320 lines)
- ~20 lines changed in `skin_engine.py` (new helpers + updated load/list)
- ~5 lines changed in `theme_manager.py`
- ~1 line in `pyproject.toml`
- ~40 test assertions (new parametrized test)

Split criterion: single PR — changes are tightly coupled (can't move files without updating loading code).
