---
name: Nameplate + ThinkingWidget lifecycle spec
description: DONE — Unhide nameplate during thinking, theme colors, shimmer fix, fade-out, layout reserve, label escalation, engine whitelist split, narrow demotion, reduced motion
type: project
originSessionId: 84f8d359-423c-4cb8-b481-dbc0f8f2347b
---
**DONE** 2026-04-23. Commits `bfff7488` + `93867798`, merged onto `feat/textual-migration`.

Findings addressed: C-1–C-6, D-1–D-7, E-2, E-3, F-2, G-1. 29 tests in `tests/tui/test_nameplate_thinking.py`; 2 tests updated in `test_thinking_widget_v2.py`.

**Why:** Critical finding C-1 — `AssistantNameplate` was hidden exactly while the active pulse shimmer was designed to play (`thinking-active` CSS rule). ThinkingWidget LONG_WAIT had no escalation, fade-out was invisible snap, `_do_hide` caused layout shift.

**Key decisions:**
- Deleted `HermesApp.thinking-active AssistantNameplate { display: none; }` from `hermes.tcss:647`; kept `density-compact` rule at L642
- `_NP_ACTIVE_COLOR`/`_NP_IDLE_COLOR` module constants kept as unmounted fallbacks; instance methods use `self._active_style`/`self._idle_color_hex` computed in `on_mount`
- `ThinkingWidget.--active { opacity: 1; }` required in TCSS for CSS transition to animate (not snap) to `opacity: 0` in `--fading`
- `clear_reserve()` called via `self.query_one(ThinkingWidget)` not `self.app.query_one` (ThinkingWidget is direct child of OutputPanel)
- `reduced-motion` class is authoritative on `HermesApp`; `app.py on_mount` reads both env var AND `tui.reduced_motion` config key
- Import path: `from hermes_cli.stream_effects import make_stream_effect` (NOT `hermes_cli.tui.stream_effects`)
- `_LabelLine.__init__` pops `_lock` from `**kwargs` before `super().__init__("", **kwargs)` to keep widget kwargs passthrough intact

**How to apply:** See tui-development skill for canonical `_resolve_mode` body with all guards merged, D-4 reserve pattern, D-3 opacity transition requirements.
