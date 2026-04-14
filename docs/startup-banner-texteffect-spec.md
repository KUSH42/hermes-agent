# Startup banner texteffect spec

## Overview

This spec adds a startup-only terminal text effect for the CLI banner. It lets
you choose one specific TerminalTextEffects effect in config, pass that
effect's individual parameters, and apply it to the startup banner logo before
the normal banner layout renders.

Today, Hermes already has TerminalTextEffects support through `/effects`, and
the startup banner already has two large art surfaces:

- `banner_logo`, printed above the main startup panel
- `_hero`, rendered inside the left side of the full-width banner panel

This spec changes startup animation to target the banner logo, not `_hero`.
The startup effect must use colors derived from the active skin instead of
hardcoded effect colors.

## Goals

This change exists to make startup banner presentation configurable without
adding one-off code paths per effect.

- Let the user enable or disable a startup text effect in config.
- Let the user select one concrete effect by name.
- Let the user pass per-effect parameters for that selected effect.
- Apply the effect to the banner logo shown at startup.
- Derive the animation palette from the active skin.
- Keep compact banner mode and non-effect startup behavior unchanged.

## Non-goals

This spec narrows scope to startup banner rendering only.

- Do not animate `_hero` inside the main banner panel.
- Do not change `/effects` command semantics in this patch.
- Do not animate every response or every turn.
- Do not add arbitrary passthrough for every TTE internal object attribute.
- Do not redesign skin file structure beyond what startup logo animation needs.

## Current behavior

Hermes already has most building blocks, but they are disconnected.

`hermes_cli/banner.py`:

- `build_welcome_banner()` prints `banner_logo` above the panel.
- `build_welcome_banner()` renders `_hero` inside the panel body.
- Both assets are currently Rich-markup strings with embedded colors.

`cli.py`:

- `show_banner()` prints the compact or full startup banner.
- `_tui_startup_display()` calls `show_banner()` after switching to
  `ChatConsole`.

`hermes_cli/tui/tte_runner.py`:

- `run_effect(effect_name, text, skin=None)` already exists.
- It already derives a fallback three-stop gradient from the active skin using
  `banner_dim`, `banner_accent`, and `banner_title`.
- It accepts only `effect_name` and `text`; it does not accept structured
  effect-specific params.

`hermes_cli/tui/app.py`:

- `HermesApp._play_effects()` suspends Textual, runs an effect in a worker,
  then resumes.
- This path is used by `/effects`, not by startup banner rendering.

## Problem statement

Current startup rendering has three gaps.

First, startup has no config-driven animation surface. Users can run `/effects`
manually, but they cannot make startup banner animation part of their theme.

Second, `_hero` is wrong target for startup animation. `_hero` lives inside the
two-column panel and competes with model, cwd, session, and tools. The visual
"brand hit" at startup is the top `banner_logo`, not the inner `_hero`.

Third, startup logo art is stored as Rich-markup strings with inline colors.
That works for static banner printing, but TTE effects need plain text content
plus a runtime color palette. If Hermes reuses baked-in markup colors, startup
animation will drift from active skin colors.

## Proposed behavior

At startup, Hermes may optionally play one text effect against the banner logo
before it prints the normal startup banner.

When enabled:

1. Resolve the active skin.
2. Resolve the startup logo text from `banner_logo`, not `_hero`.
3. Strip Rich markup from the logo source to get plain text glyphs.
4. Run the configured TTE effect with skin-derived colors and validated
   effect-specific params.
5. Print the normal startup banner after the animation completes.

When disabled, Hermes must keep today's startup behavior unchanged.

### Target surface

The animated target is the top startup `banner_logo`. `_hero` remains static in
the full banner panel unless a later spec changes that behavior.

If the terminal is in compact banner mode, Hermes must skip startup animation.
Compact mode has no printed `banner_logo`, so animating it would create a
visual mismatch between the effect and the rendered banner that follows.

### Startup timing

The startup effect runs once per CLI startup, before the normal banner is
printed.

For prompt-toolkit startup, Hermes can run the effect directly before printing
the banner.

For TUI startup, Hermes must use the existing suspend/resume pattern from
`HermesApp._play_effects()` so the raw-terminal animation does not corrupt the
Textual screen buffer.

The welcome line, resumed-session history, and tool-availability warnings must
still render after the effect because they are part of the normal post-banner
startup flow.

## Config shape

The config must use one dedicated object under `display`.

Proposed shape:

```yaml
display:
  startup_text_effect:
    enabled: false
    effect: matrix
    params: {}
```

Field rules:

- `enabled`: boolean gate. Default `false`.
- `effect`: one value from `hermes_cli.tui.tte_runner.EFFECT_MAP`.
- `params`: mapping of effect-specific overrides for the selected effect.

This config object is startup-banner-specific. It must not silently affect the
existing `/effects` command unless a later patch explicitly unifies them.

### Effect-specific params

Users asked for "specific effect with its individual params." Hermes therefore
must not treat `params` as an unvalidated free-for-all blob.

Instead, Hermes should add a small per-effect startup schema in
`hermes_cli/tui/tte_runner.py`, for example:

```python
STARTUP_EFFECT_PARAMS = {
    "matrix": {"speed": int, "rain_time": int},
    "beams": {"beam_delay": int, "beam_row_symbols": list[str]},
    "print": {"print_speed": int},
}
```

Required behavior:

- Validate only keys declared for the selected effect.
- Ignore or reject unknown keys with a clear startup warning.
- Coerce simple scalar types where safe.
- Never reflect arbitrary nested config into random TTE objects.

This keeps config predictable and prevents startup from becoming a dynamic
reflection surface over third-party internals.

### Config loader parity

Hermes has two config default surfaces for CLI behavior:

- `cli.py:load_cli_config()`
- `hermes_cli/config.py:DEFAULT_CONFIG`

This feature must be added to both, with the same default shape, so startup
behavior does not drift between interactive CLI startup, config editing, and
other config-aware entry points.

## Skin color contract

Startup animation colors must come from the active skin, not from hardcoded
markup inside the logo asset.

### Logo text source

For effect playback, Hermes must derive plain text from the active startup
logo:

- If active skin defines `banner_logo`, use that asset.
- Otherwise use built-in `HERMES_AGENT_LOGO`.
- Strip Rich markup tags before passing text to TTE.

The logo's glyph layout still comes from the skin asset. Only color control
moves to runtime.

### Palette derivation

Startup animation should derive its palette from the active skin using this
fallback chain:

1. `banner_title`
2. `banner_accent`
3. `banner_dim`

If an effect supports more than one final color stop, Hermes should pass these
three colors as the default gradient. If an effect exposes only one terminal
color or one highlight color, Hermes should use `banner_title` first, then fall
back through the same chain.

If a later skin wants tighter control, Hermes may add an optional dedicated
skin key such as `ui_ext.startup_text_effect_gradient`, but this spec does not
require it. Base behavior must work from existing banner color keys.

## Rendering rules

The startup effect must preserve normal banner output semantics.

- Run only for full banner mode.
- Run only once per startup.
- Print the normal banner after the effect finishes.
- If startup effect already rendered the full logo successfully, suppress the
  later static `banner_logo` print for that startup only.
- If the effect is disabled, skipped, or fails soft, keep the normal static
  `banner_logo` print.

This avoids immediate logo duplication while preserving today's fallback path.

## Implementation notes

This change crosses banner, config, and TUI startup code, but the runtime model
should stay simple.

### Banner code

`hermes_cli/banner.py` should expose a helper that resolves startup logo assets
from one source of truth, instead of burying selection logic inside
`build_welcome_banner()`.

One acceptable helper shape:

```python
def resolve_banner_logo_assets() -> tuple[str, str]:
    """Return (markup_logo, plain_logo)."""
```

`markup_logo` feeds normal Rich banner printing. `plain_logo` feeds TTE
playback. Both must come from the same selected skin asset.

### TTE runner

`hermes_cli/tui/tte_runner.py` should grow:

- per-effect startup param schema
- param validation and application
- helper for deriving skin gradient once

One acceptable API:

```python
def run_effect(
    effect_name: str,
    text: str,
    skin=None,
    params: dict[str, object] | None = None,
) -> None:
```

### Startup call sites

`cli.py` should decide startup effect once, near `show_banner()` / TUI startup
flow, rather than scattering effect checks in multiple banner render helpers.

One acceptable split:

- `show_banner()` stays responsible for printing normal banner
- new startup wrapper handles:
  - config read
  - compact-mode skip
  - TUI versus non-TUI execution path
  - one-shot effect playback before `show_banner()`

## Validation rules

Startup must fail soft. Bad effect config must never prevent Hermes from
starting.

Required behavior:

- Unknown effect name: print one warning, skip effect, continue startup.
- TTE missing: print one install hint, skip effect, continue startup.
- Invalid params: print one warning, skip invalid keys or skip effect,
  continue startup.
- Missing skin colors: fall back to existing banner color defaults.

Startup warnings belong in normal banner output, not in exceptions that abort
the session.

## Tests

This feature needs targeted tests because startup code spans normal CLI and
TUI.

### Unit tests

Add tests for:

- config default leaves startup effect disabled
- valid config resolves effect name and params
- invalid effect name skips playback
- invalid params are ignored or warned predictably
- logo text helper strips Rich markup but preserves glyph layout
- color derivation uses active skin keys with fallback

Likely files:

- `tests/hermes_cli/test_banner.py`
- `tests/cli/test_cli_skin_integration.py`
- new `tests/tui/test_startup_text_effect.py` if TUI-specific startup wiring
  needs direct coverage

### TUI behavior tests

For TUI startup:

- verify effect path routes through suspend/resume worker, not raw direct print
- verify `show_banner()` still runs after effect playback
- verify compact mode skips effect

### Regression tests

Protect these existing behaviors:

- static banner still uses `banner_logo` and `_hero` in normal full mode
- compact banner output is unchanged
- `/effects` command still works with no startup config

## File scope

Expected implementation touchpoints:

- `hermes_cli/config.py`
- `cli.py`
- `hermes_cli/banner.py`
- `hermes_cli/tui/tte_runner.py`
- `hermes_cli/tui/app.py`
- tests in `tests/hermes_cli/`, `tests/cli/`, and possibly `tests/tui/`
