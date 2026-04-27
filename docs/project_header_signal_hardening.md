---
name: Header signal hardening spec
description: DONE 2026-04-23 — B-1/C-3/F-1/F-2/F-3 fixes to _header.py, _tool_panel.py; 20 tests
type: project
originSessionId: b762c839-2a11-4e0a-b197-b524e035bf96
---
**DONE** 2026-04-23; 5 fixes, 20 tests in `tests/tui/test_header_signal_hardening.py`

**Why:** Tool block header dropped flash (user feedback) first under width pressure; non-interactive headers had no visual slot; category icon disappeared on error; gutter color was hardcoded "bold cyan" / `rule-accent-color`.

**How to apply:** All changes landed on `feat/textual-migration`. Reference spec at `/home/xush/.hermes/2026-04-23-header-signal-hardening-spec.md`.

## Changes

**B-1 — `·` placeholder in chevron slot (`_header.py`)**
- `if self._has_affordances:` … `else:` branch appends `("chevron", Text("  ·", style="dim #444444"))`
- Chevron slot always present; non-interactive headers read as "inactive" not missing.

**C-3 — Category icon preserved on error (`_header.py`)**
- Removed the `icon_str = _ek_icon` substitution block (lines ~193–201).
- Error_kind glyph still appears in hero prefix (lines ~247–255); category icon stays in icon column.

**F-1 — Flash drops last (`_header.py`)**
- `_DROP_ORDER` moved `"flash"` from index 0 to last: `["linecount","duration","chip","hero","diff","stderrwarn","exit","chevron","flash"]`
- Narrow-clip added: on `width < 80`, flash `_msg` capped at 14 chars + "…" before `"  ✓ "` prefix.

**F-2 — Duration single append point (`_header.py`)**
- `"duration"` added to `_DROP_ORDER` at index 1 (drops before chevron/flash).
- `_pending_dur: str | None = None` set in both spinner and completed branches; single `tail_segments.append(("duration", …))` after the entire if/else block.

**F-3A — Gutter color cascade (`_header.py`)**
- `_refresh_gutter_color`: `accent-interactive` → `primary` → `_GUTTER_FALLBACK` (was `rule-accent-color` → fallback).

**F-3B — Accent chip dynamic color (`tool_panel.py`)**
- `_TONE_STYLES["accent"] = ""` (sentinel, not `"bold cyan"`).
- `FooterPane._render_footer`: when `tone_style` is empty and `chip.tone == "accent"`, resolves `accent-interactive` → `primary` → `#5f87d7` dynamically.

## Gotchas
- `Widget.app` is read-only ContextVar property — tests use `patch.object(type(h), "app", new_callable=PropertyMock, return_value=mock_app)`.
- `_DROP_ORDER` governs trim priority, not render position in `tail_segments` — duration appended after chevron in list but drops before chevron under pressure.
- Flash narrow-clip uses `self.size.width` inline (not `term_w` which is defined after the if/else block).
