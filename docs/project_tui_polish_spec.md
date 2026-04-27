---
name: TUI Visual Polish spec
description: DONE 2026-04-22; 12 steps / D1–D13; gutter unification, binary collapse, overlay border-title, flash color, stub, StatusBar reorder; 101 tests; merged feat/textual-migration (cc897d06)
type: project
originSessionId: 1f92377e-9067-4a8e-a591-5b4e6517925a
---
Visual polish consolidation pass for the Hermes TUI. 101 tests in `tests/tui/test_tui_polish.py`.

**Why:** Design consistency across tool call presentation, overlays, and status/hint bars — all gutter widths, flash colors, and header patterns were divergent.

**Key changes (D1–D13):**
- D2: All gutter variants unified to 4 cells (`"    "` child, `"  ┊ "` unfocused, `"  ┃ "` focused, `" └─ "` / `" ├─ "` subagent)
- D3: `CollapseState` IntEnum removed from `sub_agent_panel.py`; binary `collapsed: bool` reactive is the sole collapse axis. `action_cycle_collapse` → `action_toggle_collapse`. `COMPACT` state retired.
- D4: All 9 overlays use `border_title`/`border_subtitle` Textual properties instead of internal `Static` header widgets. `_hint_fmt.py` new shared module with `hint_fmt()` helper.
- D5: `_nf_or_text(glyph, fallback, app=None)` added to `widgets/utils.py`; respects `HERMES_ACCESSIBLE`, `HERMES_NO_UNICODE`, and `app.console.color_system`.
- D6: StatusBar full-width layout: bar+pct+ctx leads; model+session trails. `_nf_or_text` replaces raw file emoji.
- D7: Flash color: `"dim red"` if error, else `f"dim {accent_color}"` — no per-tone branches.
- D8: `ReasoningPanel._update_collapsed_stub()` uses 4-cell gutter `"  ┊ "` + `_nf_or_text("", "[R]")` icon.
- D9: `SubAgentHeader.update()` uses `_format_elapsed_compact` + `_trim_tail_segments`.
- D10: `ThinkingWidget --active` CSS adds `border-left: vkey $primary 15%`. `ReasoningPanel.open_box()` calls `tw.deactivate()` on active ThinkingWidget before proceeding.
- D11: `_EchoBullet.on_mount()` fallback uses `"primary"` instead of `"rule-accent-color"`.
- D12/D13: `_DROP_ORDER = ["flash", "linecount", "chip", "hero", "diff", "stderrwarn", "chevron"]`. Tail zone: duration→flash→stderrwarn. stderrwarn style `f"bold {warn_color}"` (was `"dim red"`).

**How to apply:** Reference when auditing gutter widths, flash colors, overlay header patterns, or tail zone ordering in tool headers.
