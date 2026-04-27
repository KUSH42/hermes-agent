---
name: Error recoverability spec
description: B-2/C-1/C-2/D-2 — completing class, stderr hint, remediation in header, sub-agent error glyphs
type: project
originSessionId: a8db54eb-b880-4c9e-a543-11d3d14e6656
---
**DONE** 2026-04-23; merged feat/textual-migration (3b9d7476); 22 tests in test_error_recoverability.py

**Why:** Tool UX audit deferred items — error state visibility and recoverability cues after tool failures.

**How to apply:** These are shipped. If extending error glyphs or remediation hints, follow the patterns established here.

## What was implemented

**B-2 — `--completing` two-tick collapse:**
- `set_result_summary` adds `--completing` class, fires `set_timer(0.25, _post_complete_tidy)`
- `_post_complete_tidy` removes `--completing`, applies final collapsed state
- `HERMES_DETERMINISTIC` guard: inline (no timer)
- CSS: `ToolPanel.--completing > ToolAccent { background: $primary 25%; }`

**C-1 — `[e]` stderr action:**
- `FooterPane._render_footer` injects synthetic `copy_err` action when `stderr_tail` present
- Expanded state only

**C-2 — `ToolHeader._remediation_hint`:**
- `self._remediation_hint: str | None = None` added to `__init__`
- Populated from first chip remediation (truncated 28 chars)
- Renders as `hint:…` dim yellow tail segment when collapsed+error
- `_DROP_ORDER`: "remediation" between "stderrwarn" and "exit"

**D-2 — SubAgentPanel child error glyphs:**
- `_child_error_kinds: list[str]` tracks per-child error kinds (ordered, deduped)
- `SubAgentHeader.update` renders up to 3 glyphs in `("error-kinds", ...)` segment
- Accessible fallback: `err-kinds:…` text
