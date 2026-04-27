---
name: Textual TCSS custom variable declaration requirement
description: Custom $var-name references in TCSS must be declared in the TCSS file itself; get_css_variables() alone is insufficient at parse time
type: reference
originSessionId: 8cc1a1e5-1004-4a92-a9c9-187a3c336432
---
## The gotcha

Adding a new CSS variable reference like `color: $cursor-color;` in `hermes.tcss` will throw:

```
textual.css.errors.UnresolvedVariableError: reference to undefined variable '$cursor-color'
```

if `cursor-color` is not declared in the TCSS file AND `get_css_variables()` has not been called with that key before CSS is first parsed.

## Root cause

Textual validates `$name` references during TCSS parsing. On first render, `refresh_css()` (which calls `get_css_variables()`) may not have fired yet. Textual's built-in variables (`$primary`, `$background`, etc.) are declared in Textual's own `DEFAULT_CSS`, so they're always available at parse time.

**Custom application variables are NOT automatically registered.** `get_css_variables()` only provides override *values* for variables that already exist in the parse-time variable set.

## Fix

Declare default values at the top of `hermes.tcss` **before** any rule that references them:

```tcss
/* hermes.tcss — top of file */
$cursor-color: #FFF8DC;
$cursor-selection-bg: #3A5A8C;
$cursor-placeholder: #555555;
```

These TCSS-declared defaults are then overridable at runtime by `get_css_variables()` returning a dict that includes `cursor-color`, etc.

## Where defaults live

`theme_manager.COMPONENT_VAR_DEFAULTS` mirrors the TCSS defaults:
```python
COMPONENT_VAR_DEFAULTS = {
    "cursor-color":        "#FFF8DC",
    "cursor-selection-bg": "#3A5A8C",
    "cursor-placeholder":  "#555555",
}
```

Both must be kept in sync. If you add a new component var, add it to BOTH.

## Source

Discovered during implementation of ThemeManager (2026-04-11). The `UnresolvedVariableError` was thrown by `stylesheet.py:390` → `parse.py:447` during `app.run_test()`.

## Critical extension: variable-to-variable declarations always fail silently

`$my-var: $warning;` in hermes.tcss does NOT set `my-var` to the warning color — it silently drops `my-var` from `get_css_variables()` entirely. Confirmed with a live test (2026-04-24):

```python
CSS = "$test-var-warning: $warning;"
# get_css_variables().get("test-var-warning") → None (key missing, not "#FEA62B")
```

This applies to ALL rhs variable references — both Textual built-in theme vars (`$warning`, `$primary`, `$text-muted`) and other custom vars. Always use literal hex on the rhs of TCSS variable declarations.

Built-in theme var hex equivalents (Textual dark theme defaults):
- `$warning` = `#FEA62B`
- `$primary` = `#0178D4`

## Critical extension: border-left fails SILENTLY with component vars

`color: $text-muted` in external TCSS works fine (falls back gracefully). But `border-left: vkey $text-muted` causes **silent app startup failure** (no logged error, OutputPanel not mounted, `_anim_clock_h` AttributeError on unmount). Diagnosed during Tool Panel v2 Phase 1 (2026-04-17).

**Rule:** For `border-left` (and likely other border properties) in hermes.tcss, use ONLY Textual built-in design tokens: `$primary`, `$accent`, `$warning`, `$error`, `$success`. Component vars like `$text-muted`, `$app-bg`, `$rule-accent-color` must NOT be used in `border-left` declarations. Alpha percentages (`$primary 40%`) are fine.
