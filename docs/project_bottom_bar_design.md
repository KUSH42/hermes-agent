---
name: Bottom-bar design spec
description: Design + future reference doc for all 7 widgets below OutputPanel; key-badge typography, color shimmer, context hints, TTE transitions
type: project
originSessionId: 24b57129-b95a-426e-9279-745919a7fe66
---
Spec at /home/xush/.hermes/bottom-bar-design-spec.md — v4.0. **All 4 phases implemented 2026-04-12. 769 tests passing.**

Covers: HintBar, ImageBar, TitledRule, Input Row, PlainRule, VoiceStatusBar, StatusBar.

**Implemented:**
- `shimmer_text()` added to `animation.py` — traveling sine wave, `skip_ranges` protect key badge names
- `HintBar` converted from `Static` to `Widget`; `set_phase(phase)` drives 8-phase hint system; width-responsive (118/78/48/minimal breakpoints); shimmer on stream/file phases
- `_hint_cache: dict[tuple[str,str], dict[str,str]]` — keyed by `(phase, key_color.lower())`; cleared on skin change
- `_build_streaming_hint()` builds `(Text, skip_ranges)` for shimmer with protected key names
- `TitledRule` now has `PulseMixin`; `⚕` lerps `#2d4a6e → #5f87d7` during streaming; `set_error()` hard-sets `#EF5350`
- StatusBar `"running"` word shimmer reuses `_pulse_tick` (no second timer); idle tips in key-badge format; "connecting…" startup state
- **Bar SNR P0 (2026-04-23, 58ee2650):** `_BAR_WIDTH` 20→10; `pct_int%` removed from all branches; 3-zone color ramp; idle tip rotation deleted (static `F1·/commands`); `status_streaming` reactive suppresses pulse+shimmer during streaming; `--streaming` CSS class dims both bars to opacity 0.55; `^T` toggles verbose ctx_label; `HintBar.render` pins `^C/Esc` during streaming
- **Bar SNR P1/P2 (2026-04-24, 15cff87e):** YOLO → fixed left-edge color stripe (bold-black-on-warn-color at position 0); breadcrumb gated on `status_active_file_offscreen` (OutputPanel.watch_scroll_y → `_update_active_file_offscreen`); model name bold-flash 2s on change (`_model_changed_at`, `import time as _time` module-top, `_on_model_change`); session label suppressed when `session_count<=1` (synced in `poll_session_index`+`init_sessions`); idle affordance suppressed when `feedback.peek("hint-bar")` is not None; `…` collapse indicator in minimal branch (width<40) when spare≥3
- ImageBar `_shimmer_once()` — 1-pass reveal on attach
- `HermesApp._animations_enabled` cached at init from `NO_ANIMATIONS`/`REDUCE_MOTION` env vars
- Phase wiring: `_compute_hint_phase()` + `_set_hint_phase()` called from all relevant watchers
- `watch_size()` hides PlainRule → ImageBar → HintBar when terminal height < 12
- Note: TitledRule pulse integrated in `render()` (not `render_line()`) — current impl uses `render()` path, spec's `render_line()` mention was aspirational

**Key design decisions:**
- `NO_COLOR` does NOT disable animations — motion flag only
- TTE transitions: all default OFF
- `HintBar.hint` reactive still used for flash overrides (`_flash_hint`) and overlay countdowns (`_tick_spinner`)

**Why:** Distinguish Hermes from React/Ink competitors; add unique personality; improve key hint scanability.
**How to apply:** Reference spec for bottom-bar widget changes. Implementation is the source of truth.
