---
name: OmissionBar + ChildPanel polish spec
description: D-1/E-1/E-2 — [reset] label, pre-mount at 80%, alt+c for compact
type: project
originSessionId: a8db54eb-b880-4c9e-a543-11d3d14e6656
---
**DONE** 2026-04-23; merged feat/textual-migration (3b9d7476); 15 tests in test_omissionbar_childpanel.py

**Why:** Tool UX audit polish — OmissionBar UX roughness and ChildPanel binding conflict with space key.

**How to apply:** These are shipped. OmissionBar `[reset]` is now the canonical label; `--at-default` is the disabled-state pattern for other buttons that should never truly disable.

## What was implemented

**D-1 — OmissionBar `[reset]` never disabled:**
- Label: `Button(Text("[reset]"), ...)` — `Text()` wrapper required (bare `"[reset]"` eaten by Rich)
- Never `disabled` — `--at-default` CSS class dims + tooltip instead
- `set_counts()` toggles class; `on_button_pressed` no-ops when `--ob-cap + --at-default`
- CSS: `OmissionBar Button.--at-default { color: $text-muted 50%; }`

**E-1 — Bottom OmissionBar at 80% cap:**
- `_OB_WARN_THRESHOLD = int(_VISIBLE_CAP * 0.8)` = 160 for default 200 cap
- `_refresh_omission_bars`: `show_bottom = (total >= warn_threshold) or ...`

**E-2 — ChildPanel bindings:**
- `Binding("space", "toggle_compact")` removed
- `Binding("alt+c", "toggle_compact", show=False, priority=True)` added
