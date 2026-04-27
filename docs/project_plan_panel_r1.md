---
name: R1 PlanPanel spec
description: PlanPanel widget — plan/action queue surface; 5 phases, 78 tests, merged feat/textual-migration 2026-04-22
type: project
originSessionId: 705c5fed-0f73-4cd7-a3ad-deb781a54d43
---
**DONE** 2026-04-22; merged feat/textual-migration (6 commits including merge commit)

**Why:** Fixes S1 (no plan/step visibility) and L9 (cost not visible inline) from the v2 TUI audit. R1 ships standalone; when R2 (pane layout) lands, PlanPanel relocates into the left pane with no internal changes.

**How to apply:** PlanPanel is bottom-docked; F9 collapses. All planned_calls mutations must assign a new list — never mutate in-place. New callbacks (tool_batch_callback, usage_callback) in run_agent.py expose batch + cost data that was previously hidden from the TUI.

**Key facts:**
- `plan_types.py`: `PlanState(StrEnum)` + `PlannedCall(frozen dataclass)` with `as_running()` / `as_done()` helpers
- `plan_panel.py`: `PlanPanel(Vertical)` with 4 subsections — `_NowSection` (elapsed timer), `_NextSection` (PENDING, max 5), `_DoneSection` (DONE/ERROR, max 5), `_BudgetSection` (cost/tokens → UsageOverlay)
- 5 new class-level reactives on `HermesApp`: `planned_calls`, `turn_cost_usd`, `turn_tokens_in`, `turn_tokens_out`, `plan_panel_collapsed` (all `repaint=False`)
- `_ToolRenderingMixin`: `set_plan_batch()`, `mark_plan_running()`, `mark_plan_done()` — event-loop-only; cli.py callers use `call_from_thread`
- `run_agent.py` Shape A: `tool_batch_callback` fires once per assistant message (before first `tool_start_callback`); `usage_callback` fires after token counter update
- `cli.py`: `_on_tool_batch`, `_on_usage`, `_reset_turn_state` (called on input submit)
- TCSS vars `plan-now-fg` + `plan-pending-fg` in hermes.tcss + COMPONENT_VAR_DEFAULTS + all 4 skin files
- `watch_planned_calls` adds/removes `plan-active` app class → forces ThinkingWidget to 1-row height
- F9 keybinding + help overlay entry
- 78 tests in `tests/tui/test_plan_*.py` + `tests/agent/test_tool_batch_callback.py`

**Non-goals:** no cancel UI (R6), no drag-to-reorder, no per-session aggregation (R7), no new overlay (R3 territory)
