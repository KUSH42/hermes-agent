---
name: TUI visual redesign spec
description: V1–V8 visual/layout fixes — splash, gutter, nameplate, separator, contrast, accent
type: project
originSessionId: 3f9e1ce5-a31c-464e-87ec-c5d90847b15b
---
**DONE** 2026-04-22; 7 commits, 87 tests; merged feat/textual-migration (branch feat/tui-visual-redesign).

V1: `Panel(expand=True)` in `banner.py:build_welcome_banner()` — splash now full-width.
V2: `thinking-active` app class hides `AssistantNameplate` while ThinkingWidget active; toggled in `thinking.py:activate()` / `_do_hide()`.
V3: welcome `console.print` blocks removed from `cli.py` (two locations, ~3933 and ~9322).
V4: `UserMessagePanel` padding `0 1` → `0 2` for 2-col gutter alignment.
V5: `_SEP` in `status_bar.py:39` trimmed to single space each side.
V6: `renderers.py:_render_normal()` — `v = {}` init before try; `meta_color = v.get("foreground", "#aaaaaa")` after; replaces `style="dim"` on metrics/ts_text lines.
V7: `HermesInput:focus { border: tall $primary 30%; }` — deliberate reversal of prior `border: none`.
V8: `accent-interactive: #00bcd4` in `COMPONENT_VAR_DEFAULTS`, declared in `hermes.tcss`, added to all 4 skin YAMLs under `component_vars:`; `HintBar._get_key_color()` routes through it.

**Why:** Visual polish pass — P0 structural bugs (splash width, double nameplate, welcome orphan, gutter offset) + P1 polish (separator density, meta contrast, input affordance, palette hierarchy).

**How to apply:** App-level CSS class convention is single-hyphen (`thinking-active`, not `--thinking-active`). New TCSS token refs must be declared in `hermes.tcss` (Textual TCSS parser doesn't support `var()` fallback). Python fallback for skin vars lives in `COMPONENT_VAR_DEFAULTS`.
