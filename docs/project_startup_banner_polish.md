---
name: Startup banner polish spec
description: DONE — TTE startup animation fixes: pre-flight frame, wall-clock cap, hold-frame beat, reduced motion, padding smear, pane-aware width, deferred postamble
type: project
originSessionId: 84f8d359-423c-4cb8-b481-dbc0f8f2347b
---
**DONE** 2026-04-23. Commits `65de2069` + `20563d73`, merged onto `feat/textual-migration`.

Findings addressed: A-1, A-3, A-5, A-6, B-1, B-3, G-1 (cli.py portion). 18 tests in `tests/tui/test_startup_banner_polish.py`.

**Why:** Audit of startup banner TTE path found blank frame at mount, no wall-clock cap, color smear, layout shift at stream start, postamble layout shift, incorrect banner width in 3-pane layout.

**Key decisions:**
- Pre-flight frame uses `_render_startup_banner_text(print_hero=True)` (not `_splice_startup_banner_frame`) — skin-colored from the start
- Static banner after TTE routed through `_queue_frame` coalescing path (not `call_from_thread` directly) — ordering guaranteed by event-loop serialization
- `_set_tui_startup_banner_static()` is now fallback-only (called when `not played`)
- Reduced motion uses already-loaded `self.config` dict — no `read_raw_config()` I/O in hot path
- `OutputPanel.on_mount` width cache has an acknowledged startup race; fallback to terminal width is acceptable

**How to apply:** See tui-development skill for test fixture patterns (`import cli as cli_module`, call_from_thread stub, template dict keys).
