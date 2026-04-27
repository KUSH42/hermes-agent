---
name: R10 Header-only collapse spec
description: collapsed=True adds explicit exit code to ToolHeader; binary stays; 17 tests
type: project
originSessionId: 529a9810-0b7c-40f5-bf75-8fad89a7f402
---
**DONE** 2026-04-23. Spec: `/home/xush/.hermes/2026-04-23-tui-v2-R10-header-only-collapse-spec.md`

**Why:** Pass 10 binary collapse hides footer, so exit code is inaccessible without expanding. Icon colour alone (red/green) isn't enough for scanning N collapsed panels.

**Changes:**
- `ToolHeader.__init__`: add `self._exit_code: int | None = None`
- `_render_v4`: after stderrwarn try-except block (before line ~314), append `exit` segment when `is_collapsed and _is_complete`
- `tool_panel.set_result_summary`: `header._exit_code = getattr(summary, "exit_code", None)`
- `_DROP_ORDER`: add `"exit"` between `"stderrwarn"` and `"chevron"`
- No TCSS changes, no new state axis

**Precedence:** hero+exit_code==0 → hero only; hero+exit_code!=0 → both; no hero+0 → `ok`; no hero+non-zero → `exit N`

**Tests:** `tests/tui/test_r10_header_only.py` T01–T17

**How to apply:** exit_code is int|None from ResultSummaryV4; only shell-category tools populate it; None = no segment rendered (by design).
