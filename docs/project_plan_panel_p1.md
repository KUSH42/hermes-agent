---
name: PlanPanel P1 polish spec
description: Focus nav (Now/Next → ToolPanel scroll), segmented chip, [F9] badge — implement after P0 merges
type: project
originSessionId: f760d69e-b6e5-4653-8fa4-8224669d15f8
---
Spec at `/home/xush/.hermes/2026-04-23-plan-panel-p1-polish-spec.md` — **DONE 2026-04-23**; commit f7a4ed55; merged feat/textual-migration.

P1-1: `_PlanEntry(Static, can_focus=True)` — clickable/focusable row in Now and Next sections; click/Enter calls `BrowseService.scroll_to_tool(tool_call_id)`; Esc refocuses `#input-area`. New `BrowseService.scroll_to_tool(id)` queries ToolPanels by `_plan_tool_call_id` attr, calls `scroll_to_widget` + `--browse-focused`.
P1-2: `_ChipSegment` clickable chip segments in `_PlanPanelHeader`; `1▶` → jump running, `2✗` → jump first error, `$0.12` → UsageOverlay. Chip and expanded views toggle via `.display`.
P1-3: `[F9]` micro-badge docked right in `_PlanPanelHeader`; always visible; color `$text-muted 50%`.

**Key gotchas:**
- `_plan_tool_call_id` added to `ToolPanel.__init__`; wired in `ToolRenderingService.open_streaming_tool_block`.
- `scroll_to_tool` queries only `OutputPanel` children — avoids SubAgentPanel nesting.
- `Text.from_markup(...)` required for error count colored chip; bare string with Rich tags renders literally.
- Chip `.display` toggle (not `add_class`) for show/hide of segments.

**Why:** Bridges PlanPanel/scroll-area split — the biggest orientation win available.
**How to apply:** After P0 merges; new `_PlanEntry` widget, `BrowseService` addition, header rewrite; `tests/tui/test_plan_panel_p1.py`.
