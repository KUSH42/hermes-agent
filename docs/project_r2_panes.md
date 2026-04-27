---
name: R2 panes layout implementation
description: Three-pane layout skeleton for Hermes TUI — branch, status, key files, test count
type: project
originSessionId: be7a341b-8e14-4d76-b938-c12b25920470
---
**Status:** DONE 2026-04-22; 202 tests; single commit 73d7d963 on branch `feat/tui-v2-r2-panes`

**Why:** Parent spec `/home/xush/.hermes/2026-04-22-tui-v2-R2-panes-spec.md` §3 R2 — three-pane skeleton for agents.

**How to apply:** Flag-gated `display.layout: "v2"` (default `"v1"`, no behavior change). Side panes start with stubs (PlanPanelStub / ContextPanelStub) for R1/R6/R9 to fill.

## Key new files
- `hermes_cli/tui/pane_manager.py` — PaneManager (plain class), PaneId, LayoutMode, PaneHost protocol
- `hermes_cli/tui/widgets/pane_container.py` — PaneContainer widget
- `hermes_cli/tui/widgets/plan_panel_stub.py` / `context_panel_stub.py` / `split_target_stub.py`

## Architecture decisions
- PaneManager is a plain class (not mixin), held at `app._pane_manager`
- Breakpoints: SINGLE <120 cols, THREE 120–159, THREE_WIDE ≥160; height guard MIN_HEIGHT=20
- `_apply_layout(app)` is idempotent; called from `_flush_resize` (debounced, not `watch_size`)
- `OutputPanel` constructed in `__init__`, mounted into `#pane-center` via `pane_center.set_content()`
- Dock-bottom TCSS rules gated on `HermesApp.layout-v2` CSS class
- Center split: `SplitTargetStub` pre-mounted (display:none), toggled by Ctrl+\
- Session persistence: `session_manager.save_layout_blob` / `load_layout_blob` → `<session_dir>/layout.json`
- `/layout v1|v2` slash command — requires restart; `/layout left=N right=M` applies live

## New component vars (all 4 bundled skins updated)
- `pane-border`, `pane-border-focused`, `pane-title-fg`, `pane-divider`

## Key bindings added (v2 only)
- F5/F6/F7 — focus left/center/right pane
- F9 / Shift+F9 — cycle visible panes
- Ctrl+[ / Alt+[ — collapse/expand left pane
- Ctrl+] / Alt+] — collapse/expand right pane
- Ctrl+\ — toggle center split
