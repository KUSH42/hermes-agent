# Hermes Skin System — Reference

Full reference for the hermes-agent skin system. Consumed by `tui-development` skill and the standalone `hermes-skin` skill.

---

## Two-layer architecture

**Layer 1 — `skin_engine.py` (legacy ANSI/banner layer)**
- `SkinEngine` dataclass with `.colors`, `.spinner`, `.branding`, `.tool_icons`, `.diff`, `.markdown`, `.syntax_scheme`, etc.
- Used for Rich-rendered banner art, prompt_toolkit ANSI mode, TTE effects, and `_skin_color()` helper in `widgets/utils.py`.
- API: `get_active_skin()` → `SkinEngine`; `set_active_skin(name)`; `list_skins()`.
- `skin.get_color(key, fallback)` — reads `.colors[key]` with fallback.
- `skin.get_branding(key, fallback)` — reads `.branding[key]` with fallback.

**Layer 2 — `theme_manager.py` + `skin_loader.py` (Textual CSS variable layer)**
- `ThemeManager` translates skin files into Textual CSS variables via `get_css_variables()`.
- `apply_skin(skin_vars: dict | Path)` on `HermesApp` — single entry point; calls `_theme_manager.load_dict()` or `load([path])` then `apply()`.
- `ThemeManager.css_variables` property: `{**_css_vars, **_component_vars}` — component vars win on conflict.

---

## Skin file location

User skins: `~/.hermes/skins/<name>.yaml` or `<name>.json`.  
`TabbedSkinOverlay` (alias `SkinPickerOverlay`) discovers skins by scanning that directory for `.json/.yaml/.yml` extensions.  
`"default"` is always inserted at index 0 even if no default file exists.  
Activate via `/skin <name>` in TUI (direct apply, bypasses overlay) or `display.skin: <name>` in `config.yaml`.  
`/skin` bare opens `TabbedSkinOverlay` — 3-tab picker: **Skin | Syntax | Options**.

---

## Full skin file format (YAML)

```yaml
# ── Semantic keys (skin_loader._SEMANTIC_MAP) ──────────────────────────
# Fan out to multiple Textual CSS vars. setdefault used — vars: block wins.
fg:         "#E0E0E0"    # → foreground, text
bg:         "#0F0F23"    # → background, surface, panel
accent:     "#7C3AED"    # → primary, accent
accent-dim: "#5A2A9A"    # → primary-darken-2, primary-darken-3
success:    "#4CAF50"    # → success
warning:    "#FFA726"    # → warning
error:      "#ef5350"    # → error
muted:      "#888888"    # → text-muted
border:     "#333333"    # → panel-lighten-1
selection:  "#1E4080"    # → boost

# ── Glass keys (pass through to CSS unchanged) ──────────────────────────
glass-tint:   "#0D0D0D"
glass-border: "#333333"
glass-edge:   "#555555"

# ── Raw Textual CSS var overrides (Pass 1 — highest precedence) ─────────
vars:
  primary: "#7C3AED"               # Wins over semantic fan-out
  preview-syntax-theme: "dracula"  # Pygments theme for code blocks (default: monokai)
                                   # Options: monokai, dracula, one-dark, nord, gruvbox,
                                   #          github-dark, catppuccin, solarized-dark, tokyo-night, hermes
  preview-syntax-bold: "true"      # "true" (default) keeps bold/italic token modifiers; "false" strips them

# ── Component Part variables (injected by ThemeManager) ─────────────────
# All keys fall back to COMPONENT_VAR_DEFAULTS in theme_manager.py if omitted.
#
# In the canonical DESIGN.md form (skins/<name>/DESIGN.md), these live under
# `x-hermes.component-vars` instead of a top-level `component_vars` block:
#
#     x-hermes:
#       component-vars:
#         app-bg: "{colors.background}"   # token refs allowed
#         cursor-color: "#f5c2e7"
#
# Both forms produce the same runtime ThemeManager state.
component_vars:
  app-bg:                   "#1E1E1E"   # Global app bg — Screen + HermesApp + chrome
                                        # rule-bg-color MUST match this value
  cursor-color:             "#FFF8DC"   # HermesInput cursor glyph/block
  cursor-selection-bg:      "#3A5A8C"   # Text selection highlight
  cursor-placeholder:       "#555555"   # Placeholder text colour
  ghost-text-color:         "#555555"   # Autocomplete ghost/suggestion text
  chevron-base:             "#FFF8DC"   # Input chevron idle state
  chevron-file:             "#FFBF00"   # Input chevron file mode
  chevron-stream:           "#6EA8D4"   # Input chevron streaming
  chevron-shell:            "#A8D46E"   # Input chevron shell mode
  chevron-done:             "#4CAF50"   # Input chevron done
  chevron-error:            "#E06C75"   # Input chevron error
  fuzzy-match-color:        "#FFD866"   # Autocomplete fuzzy match highlight
  status-running-color:     "#FFBF00"   # StatusBar running indicator
  status-error-color:       "#ef5350"   # StatusBar error indicator
  status-warn-color:        "#FFA726"   # StatusBar warning indicator
  status-context-color:     "#5f87d7"   # StatusBar context info
  running-indicator-hi-color:  "#FFA726"   # Running indicator bright phase (shimmer peak)
  running-indicator-dim-color: "#6e6e6e"   # Running indicator trough (shimmer base)
  fps-hud-bg:               "#1a1a2e"   # FPS counter background
  user-echo-bullet-color:   "#FFBF00"   # User message bullet glyph
  completion-empty-bg:      "#2A2A2A"   # Completion list empty state background
  rule-dim-color:           "#888888"   # TitledRule/PlainRule separator dim text
  rule-bg-color:            "#1E1E1E"   # Rule gradient endpoint — MUST match app-bg
  rule-accent-color:        "#FFD700"   # TitledRule title text accent
  rule-accent-dim-color:    "#B8860B"   # TitledRule accent dim variant
  primary-darken-3:         "#4a7aaa"   # TitledRule idle glyph (not a Textual built-in var)
  brand-glyph-color:        "#FFD700"   # ⟁/⚕ brand glyph — separate from title text
  scrollbar:                "#5f87d7"   # Scrollbar thumb colour
  drawille-canvas-color:    "#00d7ff"   # Braille animation canvas default colour
  icon-dim:                 "#6e6e6e"   # SkinColors.icon_dim — spinner low-end / dimmed tool icon
  separator-dim:            "#444444"   # SkinColors.separator_dim — header chevron-slot + meta separator
  # SC-1 dim variants (2026-04-26)
  error-dim:                "#8B2020"   # SkinColors.error_dim — exit-code ok chip, remediation hints
  success-dim:              "#1E5C1E"   # SkinColors.success_dim — exit-code ok chip
  warning-dim:              "#5C4A00"   # SkinColors.warning_dim — remediation hint text
  text-muted-dim:           "#3A3A3A"   # SkinColors.text_muted_dim — chevron placeholder, parse-fail contexts
  # SC-4 gutter (2026-04-26)
  tool-header-gutter-color: "#00bcd4"   # SkinColors.tool_header_gutter — focused ToolPanel gutter (cascade: $accent-interactive)
  # SC-2 per-tier tool header accents (2026-04-26)
  tool-tier-read-accent:    "#0178D4"   # Tier accent for read-category tool icons
  tool-tier-write-accent:   "#0178D4"   # Tier accent for write-category tool icons
  tool-tier-exec-accent:    "#81C784"   # Tier accent for exec-category tool icons (green)
  tool-tier-search-accent:  "#0178D4"   # Tier accent for search-category tool icons
  tool-tier-shell-accent:   "#81C784"   # Tier accent for shell-category tool icons (green)
  tool-tier-browse-accent:  "#0178D4"   # Tier accent for browse-category tool icons
  tool-tier-mcp-accent:     "#9b59b6"   # Tier accent for MCP tool icons (purple)
  tool-tier-thinking-accent: "#0178D4"  # Tier accent for reasoning/thinking blocks
  tool-tier-tooling-accent:  "#0178D4"  # Tier accent for meta/sub-agent call blocks
  panel-border:             "#333333"   # SourcesBar + bordered panel borders
  footnote-ref-color:       "#888888"   # Footnote superscript marker colour
  tool-mcp-accent:          "#9b59b6"   # MCP tool accent (purple)
  tool-vision-accent:       "#00bcd4"   # Vision tool accent (teal)
  diff-add-bg:              "#1a3a1a"   # Diff addition background
  diff-del-bg:              "#3a1a1a"   # Diff deletion background
  cite-chip-bg:             "#1a2030"   # Citation chip background
  cite-chip-fg:             "#8899bb"   # Citation chip foreground
  browse-turn:              "#d4a017"   # Browse mode turn anchor pip colour
  browse-code:              "#4caf50"   # Browse mode code anchor pip colour
  browse-tool:              "#2196f3"   # Browse mode tool anchor pip colour
  browse-diff:              "#e040fb"   # Browse mode diff anchor pip colour
  browse-media:             "#00bcd4"   # Browse mode media anchor pip colour
  nameplate-idle-color:     "#888888"   # AssistantNameplate idle state
  nameplate-active-color:   "#7b68ee"   # AssistantNameplate active/streaming state
  nameplate-decrypt-color:  "#00ff41"   # AssistantNameplate decrypt animation
  spinner-shimmer-dim:      "#555555"   # Spinner shimmer trough (keep readable on light bg)
  spinner-shimmer-peak:     "#d8d8d8"   # Spinner shimmer peak
  plan-now-fg:              "#00bcd4"   # PlanPanel now-section foreground (R1)
  plan-pending-fg:          "#777777"   # PlanPanel pending-section foreground (R1)
  pane-border:              "#333333"   # PaneContainer border color (R2 v2 layout)
  pane-border-focused:      "#5f87d7"   # PaneContainer focused border (R2 v2 layout)
  pane-title-fg:            "#888888"   # Pane title text color (R2 v2 layout)
  pane-divider:             "#2a2a2a"   # Inter-pane divider (R2 v2 layout)

# ── Legacy skin_engine keys (Layer 1 — ANSI/banner/TTE) ─────────────────
colors:
  banner_title:   "#FFD700"    # TTE gradient stop 1; banner title text
  banner_accent:  "#FFBF00"    # TTE gradient stop 2; section headers
  banner_dim:     "#CD7F32"    # TTE gradient stop 3; dim/muted separators
  banner_border:  "#CD7F32"    # Panel border colour
  banner_text:    "#FFF8DC"    # Body text (tool names, skill names)
  ui_accent:      "#FFBF00"    # General UI accent
  ui_label:       "#4dd0e1"    # UI labels
  ui_ok:          "#4caf50"    # Success indicators
  ui_error:       "#ef5350"    # Error indicators
  ui_warn:        "#ffa726"    # Warning indicators
  prompt:         "#FFF8DC"    # Prompt text colour
  input_rule:     "#CD7F32"    # Input area horizontal rule
  response_border: "#FFD700"   # Response box border (ANSI mode)
  # (full schema in hermes_cli/skin_engine.py module docstring)

branding:
  agent_name:     "Hermes Agent"
  welcome:        "Welcome message"
  goodbye:        "Goodbye! ⚕"
  response_label: " ⚕ Hermes "
  prompt_symbol:  "❯ "
  help_header:    "(^_^)? Commands"

spinner:
  style: dots                   # dots|bounce|grow|arrows|star|moon|pulse|clock|none
  waiting_faces: ["(⚔)", "(⛨)"]
  thinking_faces: ["(⌁)", "(<>)"]
  thinking_verbs: ["forging", "plotting"]
  wings:
    - ["⟪⚔", "⚔⟫"]

syntax_scheme: monokai           # Named scheme (separate from vars.preview-syntax-theme)
                                 # Options: hermes, monokai, dracula, one-dark, github-dark,
                                 #          nord, catppuccin, tokyo-night, gruvbox, solarized-dark

diff:
  deletion_bg:  "#781414"
  addition_bg:  "#145a14"
  # ... (full schema in skin_engine.py)
```

---

## Precedence rules (skin_loader + override layer)

1. **`display.skin_overrides` in config.yaml** — merged by `ThemeManager._apply_overrides()` after every `load()` call. Highest effective precedence.
2. **`vars:` block in skin file** — written directly to output dict (highest in-file precedence).
3. **Semantic keys** (`fg`, `bg`, `accent`, …) — fan out via `_SEMANTIC_MAP`; `setdefault` used so `vars:` wins on conflict.
4. **Glass keys** (`glass-tint`, `glass-border`, `glass-edge`) — pass through unchanged.
5. **`component_vars:`** — extracted separately; merged on top of `COMPONENT_VAR_DEFAULTS`.
6. **Textual built-in defaults** — lowest precedence.

`_apply_overrides()` is called in `ThemeManager.load()` only — **not** in `load_dict()`. Dict-based `apply_skin()` calls (live overlay previews) intentionally skip the override merge so in-session previews aren't immediately overwritten.

---

## Override persistence layer (`display.skin_overrides`)

New in 2026-04-22. Per-user tweaks that survive skin switches, stored in `config.yaml`:

```yaml
display:
  skin: matrix
  skin_overrides:
    vars:
      preview-syntax-theme: dracula
      preview-syntax-bold: "false"
    component_vars:
      cursor-color: "#ff2d95"
      drawille-canvas-color: "#ff2d95"
```

### Config helpers (added to `config.py`)

```python
from hermes_cli.config import read_skin_overrides, save_skin_override

read_skin_overrides()                               # → dict from config
save_skin_override("vars.preview-syntax-theme", "nord")    # nested dot-path write
save_skin_override("component_vars.cursor-color", "#ff2d95")
```

### ThemeManager integration

`ThemeManager._apply_overrides(overrides: dict)` — merges `overrides["vars"]` into `_css_vars` and `overrides["component_vars"]` into `_component_vars`. Called at the end of `load()` ONLY, not `load_dict()`.

`HermesApp._apply_override_dict(overrides: dict)` — calls `_apply_overrides()` + `apply()` live. Use when re-merging overrides without a full disk reload (e.g. after Tab 3 option changes).

### Critical: `load_dict()` must NOT call `_apply_overrides()`

Dict-based `apply_skin()` calls are used for live overlay preview (e.g. `apply_skin({"preview-syntax-theme": "dracula"})`). If `_apply_overrides()` ran inside `load_dict()`, a persisted override would immediately overwrite the preview value — making interactive preview non-functional. Dict loads are transient; override merging happens only on full skin file loads.

---

## TabbedSkinOverlay (`/skin` command)

`TabbedSkinOverlay` in `overlays.py` replaces `SkinPickerOverlay`. Alias `SkinPickerOverlay = TabbedSkinOverlay` keeps all importers unchanged.

```
[Skin ●]  [Syntax]  [Options]          Esc=close
```

### Tab 1 — Skin

Arrow nav → `app.apply_skin(skin_path)` (live preview via `ThemeManager.load()`).  
Enter → persists `display.skin` to config; overlay stays open.  
No additional apply needed — `load()` already called `_apply_overrides()`.

### Tab 2 — Syntax

Arrow nav → `app.apply_skin({"preview-syntax-theme": name})` — **flat dict**, not `{"vars": {...}}`.  
Enter → `save_skin_override("vars.preview-syntax-theme", name)`; overlay stays open.  
Shows a 7-line Python `FIXTURE_CODE` snippet re-rendered with the selected Pygments theme.

### Tab 3 — Options

| Option | Live apply | Persist |
|---|---|---|
| Bold keywords | `apply_skin({"preview-syntax-bold": "false"})` | `save_skin_override("vars.preview-syntax-bold", value)` |
| Cursor colour | `apply_skin({"component_vars": {"cursor-color": color}})` | `save_skin_override("component_vars.cursor-color", color)` |
| Anim colour | `apply_skin({"component_vars": {"drawille-canvas-color": color}})` | `save_skin_override("component_vars.drawille-canvas-color", color)` |
| Spinner style | — | `_cfg_set_nested(cfg, "display.spinner_style", style)` (NOT under skin_overrides) |

### Escape / snapshot revert

Snapshot at `refresh_data()` call:
- `_snap_css_vars`: `{k: v for k, v in tm._css_vars.items() if k != "component_vars"}` — strip `"component_vars"` key to prevent merge collision.
- `_snap_component_vars`: copy of `tm._component_vars`.

Revert: `app.apply_skin({**_snap_css_vars, "component_vars": _snap_component_vars})`.

Tab-local Enter persists only that tab's setting; overlay stays open. Escape reverts ALL previewed changes across all tabs.

### Keyboard

`Tab`/`Shift+Tab` cycle tabs (priority=True). `1`/`2`/`3` jump directly. Both override OptionList focus cycling because `priority=True`.

### Testing pattern — Widget.app property mock

`ov.app = mock` fails — `app` is a read-only property. Use:

```python
from unittest.mock import PropertyMock, patch

with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
    ov._confirm_skin("nord")
```

---

## `apply_skin()` refresh chain

```python
app.apply_skin(Path("~/.hermes/skins/mytheme.yaml"))
# or
app.apply_skin({"accent": "#7C3AED", "component_vars": {"cursor-color": "#FFD700"}})
```

Invalidates in order:
1. `_theme_manager.load_dict()` / `load([path])` + `apply()` → `refresh_css()`.
2. `_hint_cache.clear()` — StatusBar idle-tip rendering cache.
3. `StatusBar._idle_tips_cache = None` — forces tip re-render on next tick.
4. `VirtualCompletionList.refresh_theme()` — completion list repaints.
5. `PreviewPanel.refresh_theme()` — preview panel repaints.
6. All mounted `ToolBlock`: `block.refresh_skin()`.
7. All mounted `StreamingCodeBlock`: `block.refresh_skin(css_vars)`.

---

## Hot reload

```python
app._theme_manager.start_hot_reload(poll_interval_s=1.0)  # start background watcher
app._theme_manager.stop_hot_reload()                       # stop on exit
changed = app._theme_manager.check_for_changes()           # manual poll (set_interval ~1 Hz)
```

Off-thread: `_watch_loop` daemon does blocking `stat()` + file read, then schedules `_apply_hot_reload_payload` via `app.call_from_thread`. Changes land within ~2 s, no frame drops.

**Dict-loaded skins (`load_dict`) cannot hot-reload** — `_source_path` is `None`.

---

## `preview-syntax-theme` raw var

Set in `vars:` block. Controls Pygments theme for all code blocks and preview panel.

```yaml
vars:
  preview-syntax-theme: "dracula"
```

Consumers: `ResponseFlow._pygments_theme`, `StreamingCodeBlock.refresh_skin()`, `PreviewPanel.refresh_theme()`, `ExecuteCodeBlock`. Default everywhere: `"monokai"`.

---

## TTE effects integration

`hermes_cli/tui/tte_runner.py` — optional dep: `pip install "hermes-agent[fun]"`.

```python
from hermes_cli.tui.tte_runner import run_effect, iter_frames, EFFECT_MAP

# Synchronous — must be inside App.suspend() (TTE writes raw terminal)
run_effect("matrix", "Hello Hermes")

# Frame generator — for widget rendering
for frame in iter_frames("decrypt", "Connecting…"):
    widget.update(frame)
```

**Skin-aware gradient**: both functions pull `banner_title`, `banner_accent`, `banner_dim` from `skin_engine.get_active_skin()` and apply them to `effect.effect_config.final_gradient_stops`. Skipped when caller passes `params={"final_gradient_stops": [...]}`.

**Effect catalogue** (40+ effects):

| Category | Keys |
|---|---|
| Reveal / dramatic | `matrix`, `blackhole`, `decrypt`, `laseretch`, `binarypath`, `synthgrid` |
| Flow / ambient | `beams`, `waves`, `rain`, `overflow`, `sweep` |
| Text reveal | `print`, `slide`, `highlight` |
| Fun / misc | `wipe`, `colorshift`, `crumble`, `burn`, `fireworks`, `bouncyballs`, `bubbles`, `vhstape`, `thunderstorm`, `smoke`, `rings`, `scattered`, `spray`, `swarm`, `spotlights`, `unstable`, `slice`, `middleout`, `pour`, `orbittingvolley`, `randomsequence`, `expand`, `errorcorrect` |

`_apply_effect_params()` coerces raw config to field types (bool/int/float/str/tuple/Color). Unknown keys ignored with print warning. `"parser_spec"` always skipped.

---

## Adding a new CSS component var (developer checklist)

**Current contract (RX3 Phases 1–3 landed; Phase 4 generator deferred).** A new `$var-name` needs:

1. `COMPONENT_VAR_DEFAULTS` in `theme_manager.py` — sensible hex default.
2. `hermes.tcss` under the `/* Component Part variables */` comment block — `$var-name: <default>;` (required IF the var is `$`-referenced from `hermes.tcss` or any `DEFAULT_CSS` block; Textual needs it at parse time).
3. `skin_engine.py` module docstring `component_vars:` block — description line.
4. Each bundled skin YAML (`skins/{matrix,catppuccin,solarized-dark,tokyo-night}.yaml`) — key under `component_vars:`. Use `python -m hermes_cli.tui.build_skin_vars --fill-skin skins/<name>.yaml` to auto-scaffold with defaults, then hand-tune per skin.

`tests/tui/test_css_var_single_source.py` gates CI: T1 (refs resolve), T2 ($-referenced defaults declared), T3 (bundled skins cover all keys), T4 (no orphan decls), T8 (no raw `COMPONENT_VAR_DEFAULTS[...]` access).

**RX3 validator** (`theme_manager.validate_skin_payload`) runs on every skin load. Bad hex → `SkinValidationError` → the 3-step fallback chain (`load_with_fallback`) falls through to bundled default, then to `COMPONENT_VAR_DEFAULTS`-only emergency path. Stderr tags: `SKIN_LOAD_FAILED` / `SKIN_DEFAULT_FAILED` / `SKIN_EMERGENCY_FALLBACK`.

**Consumers must use `_default_of()`** — never `COMPONENT_VAR_DEFAULTS[...]` directly. T8 grep test enforces this. The shim exists so the Phase 4 `str → VarSpec` flip is a pure value-type change.

**Textual 8.x gotcha (unchanged):** `get_css_variables()` at runtime is insufficient — `DEFAULT_CSS` is parsed at class-definition time, so any `$var-name` referenced there must be declared in `hermes.tcss` literally.

**Scanner / generator tool — `hermes_cli/tui/build_skin_vars.py`:**

- `python -m hermes_cli.tui.build_skin_vars --matrix` — drift report (referenced / py-default / tcss-decl / docstring / per-skin coverage per var).
- `python -m hermes_cli.tui.build_skin_vars --check` — CI drift gate against generated block (no-op until Phase 4 installs the block).
- `python -m hermes_cli.tui.build_skin_vars --fill-skin PATH` — add missing `component_vars` keys to a skin YAML with defaults.
- `python -m hermes_cli.tui.build_skin_vars` — regenerate TCSS + docstring blocks (Phase 4 target).

**Phase 4 (deferred):** flips `COMPONENT_VAR_DEFAULTS` values from `str` → `VarSpec` (frozen dataclass with `default`, `description`, `since`, `optional_in_skin`, `category`) and replaces the hand-written TCSS declaration block with a generated `BEGIN/END`-marker block with a `hash: sha256:<hex>` line over the full VarSpec tuple. Pre-commit `--check` hook blocks drift. Needs a freeze-window PR (no concurrent `hermes.tcss` declaration edits). Strict alphabetical ordering from the first run — expect a one-time reorder diff.
