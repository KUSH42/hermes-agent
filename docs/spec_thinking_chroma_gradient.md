# DRAFT — ThinkingWidget Spinner Hue-Shift Chroma Gradient

**Spec ID:** TW-CHROMA  
**Status:** DRAFT  
**Scope:** `hermes_cli/tui/widgets/thinking.py`, `hermes_cli/tui/_color_utils.py`, `hermes_cli/tui/theme_manager.py`, `hermes_cli/tui/hermes.tcss`

---

## Problem

`_AnimSurface.render_line()` paints every braille row with the same flat
`dim {accent_hex}` style.  The spinner is monochrome regardless of skin.
There is no skin-level knob to set distinct thinking-animation colors or to
enable a temporal hue drift.  `_refresh_colors()` reads generic `$accent` /
`$text` — not thinking-specific vars — so skin authors have no independent
control point.

---

## Goal

Add a two-stop chroma gradient that sweeps vertically across the braille
surface, plus an optional temporal hue-shift so the gradient slowly rotates
through hue space over time.  Both colors and speed are skin-CSS-derived and
therefore skinnable without touching Python.

---

## Issues

### HIGH

**TW-CHROMA-1 — Per-row gradient in `_AnimSurface.render_line()`**

Current (line 214):
```python
text = Text(raw, style=f"dim {self._accent_hex}", no_wrap=True, ...)
```
Every row receives the same color.

Fix: interpolate between `_chroma_a_hex` and `_chroma_b_hex` by normalised
row position `y / max(1, total_rows - 1)`, using `_lerp_hex()` (see
TW-CHROMA-5).  Total rows = `self.size.height`.  Row 0 = chroma-a, last row
= chroma-b.

The `dim` prefix is intentional (braille is detail, not headline) — keep it.

**TW-CHROMA-2 — New component CSS vars for gradient endpoints**

Add three entries to `COMPONENT_VAR_DEFAULTS` in `theme_manager.py`:

| var name | default | notes |
|---|---|---|
| `thinking-chroma-a` | `"#7b68ee"` | top-of-surface color (same hue as `nameplate-active-color`) |
| `thinking-chroma-b` | `"#00bcd4"` | bottom-of-surface color (same as `accent-interactive`) |
| `thinking-hue-shift-speed` | `VarSpec(default="0.15", optional_in_skin=True, description="Hue rotation turns/second; 0 = static")` | non-hex knob, needs `optional_in_skin=True` |

`hermes.tcss` must declare these three vars (inside the auto-generated block
or the manual preamble, whichever `build_skin_vars.py` enforces).

**TW-CHROMA-3 — `_refresh_colors()` reads the new vars**

Extend `ThinkingWidget._refresh_colors()` to also pull:

```python
self._chroma_a_hex = _normalize_hex(css_vars.get("thinking-chroma-a"), "#7b68ee")
self._chroma_b_hex = _normalize_hex(css_vars.get("thinking-chroma-b"), "#00bcd4")
raw_speed = css_vars.get("thinking-hue-shift-speed", "0.15")
try:
    self._chroma_hue_speed = float(raw_speed)
except (ValueError, TypeError):
    self._chroma_hue_speed = 0.15
```

Add instance-level class-var defaults:
```python
_chroma_a_hex: str = "#7b68ee"
_chroma_b_hex: str = "#00bcd4"
_chroma_hue_speed: float = 0.15
```

### MEDIUM

**TW-CHROMA-4 — Temporal hue drift applied in `tick_anim()`**

On each timer tick (`_tick()` → `tick_anim()`), the parent passes the current
`elapsed` time into `_AnimSurface` so it can rotate both gradient stops by the
same delta:

```python
# in ThinkingWidget._tick()
elapsed = time.monotonic() - (self._activate_time or time.monotonic())
hue_delta = (elapsed * self._chroma_hue_speed) % 1.0
chroma_a = _hue_rotate(self._chroma_a_hex, hue_delta)
chroma_b = _hue_rotate(self._chroma_b_hex, hue_delta)
self._anim_surface.tick_anim(dt, chroma_a=chroma_a, chroma_b=chroma_b)
```

`_AnimSurface.tick_anim()` signature changes:
```python
def tick_anim(
    self,
    dt: float,
    accent_hex: str = "#888888",   # kept for backward compat; used as chroma_a fallback
    chroma_a: str | None = None,
    chroma_b: str | None = None,
) -> None:
```

When `chroma_b is None`, fall back to `chroma_a` (flat single color —
preserves old behavior for callers that don't pass the new args).

**TW-CHROMA-5 — `_lerp_hex()` helper in `_color_utils.py`**

`_lerp_hex` already lives in `widgets/__init__.py` (AssistantNameplate, line ~881)
but is private to that module.  Extract it to `_color_utils.py` so
`_AnimSurface.render_line()` can import it without creating a widget-to-widget
dependency:

```python
def _lerp_hex(a: str, b: str, t: float) -> str:
    """Linear interpolate two '#rrggbb' colors. t=0→a, t=1→b."""
    ar, ag, ab = _hex_to_rgb(a)
    br, bg, bb = _hex_to_rgb(b)
    r = int(ar + (br - ar) * t)
    g = int(ag + (bg - ag) * t)
    b_ = int(ab + (bb - ab) * t)
    return f"#{r:02x}{g:02x}{b_:02x}"
```

`_lerp_hex` in `widgets/__init__.py` can be converted to a thin import shim
(or left as-is to avoid churn — the two are small enough that a duplicate is
acceptable if the reviewer prefers).

### LOW

**TW-CHROMA-6 — Guard: hue-shift speed clamped to `[0.0, 2.0]`**

`thinking-hue-shift-speed` is a raw CSS var that a skin author could set to
an arbitrary float.  After parsing, clamp:
```python
self._chroma_hue_speed = max(0.0, min(2.0, self._chroma_hue_speed))
```
This matches the range already used by `DrawbrailleOverlay.hue_shift_speed`
(AnimConfigPanel, 0.0–2.0).

**TW-CHROMA-7 — Reduced-motion / LINE mode: gradient disabled**

When `ThinkingMode.LINE` is active (reduced motion or narrow terminal), only
the `_LabelLine` is visible — no `_AnimSurface`.  No change needed.  But
confirm that hue-shift code paths are guarded by `_anim_surface is not None`
before touching the surface, which they already are via the `tick_anim` guard.

---

## Non-goals

- No new config YAML knob (`tui.thinking.*`) — the skin CSS vars are the sole
  configuration surface, consistent with how `nameplate-*` vars work.
- No change to `_LabelLine` — the text label uses `_text_hex` / `_accent_hex`
  separately; the chroma gradient applies only to the braille surface.
- No alpha/opacity gradient (vertical fade) — that is a separate concern.

---

## Implementation order

1. TW-CHROMA-5 (`_lerp_hex` in `_color_utils.py`) — no behavior change, safe first
2. TW-CHROMA-2 (new component vars) — schema-only, no runtime effect yet
3. TW-CHROMA-3 (`_refresh_colors` extension) — reads new vars, stores on self
4. TW-CHROMA-4 (hue-drift in `_tick()` + `tick_anim` sig change)
5. TW-CHROMA-1 (per-row gradient in `render_line`) — visual payoff
6. TW-CHROMA-6 (clamp guard)

---

## Test surface (expected ~12–16 tests)

- `_lerp_hex` round-trips at t=0 and t=1; midpoint is correct
- `_refresh_colors` with mocked `get_css_variables` → correct hex stored
- `_refresh_colors` with invalid speed string → falls back to 0.15
- `_refresh_colors` clamps speed outside [0,2]
- `render_line(y=0)` uses chroma-a color; `render_line(y=rows-1)` uses chroma-b
- `tick_anim` with `chroma_b=None` falls back to flat color (old behavior)
- Hue drift: after elapsed=1.0 with speed=0.5, gradient colors differ from
  speed=0.0 colors by the expected hue offset
- `build_skin_vars` validation passes (no drift between COMPONENT_VAR_DEFAULTS,
  hermes.tcss declarations, and skin docstrings)
