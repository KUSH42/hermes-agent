---
name: PlanPanel P0 fixes spec
description: Six P0 fixes + 3 bugs from 2026-04-23 audit — delete DoneSection, default collapse, 2Hz tick, error chip, budget hide, debounce active
type: project
originSessionId: f760d69e-b6e5-4653-8fa4-8224669d15f8
---
Spec at `/home/xush/.hermes/2026-04-23-plan-panel-p0-fixes-spec.md` — **DONE 2026-04-23**; commit 878d357e; merged feat/textual-migration.

P0-1: Delete `_DoneSection` class + all mounting (pure scroll-area duplication).
P0-2: Init `_collapsed=True` + sync on_mount to match `plan_panel_collapsed=True` default; eliminates mount flash.
P0-3: `_NowSection._tick` → 2Hz, elapsed shown only when `>= 3`s; store `_base_text` instead of `text.rfind("  [")` reverse-parse; remove `if False:` dead branch.
P0-4: Split done vs errors in `_rebuild_header`; `update_header` accepts `errors=0` kwarg; chip shows `2✗` in bold red via `Text.from_markup`.
P0-5: Hide `_BudgetSection` while RUNNING/PENDING; show for 5s post-turn via `set_timer`; cost-only `·$0.12` appended to chip label during active turn.
P0-6: Debounce `--active` removal by 3s (`_do_hide_active` timer); prevents scroll-jump when strip hides between tool batches.
B-1: Delete `_NextSection._expanded` reactive (dead code — nothing ever sets it True).
B-2: `$plan-now-fg` → `#ffb454` (warm amber); no longer collides with `$accent-interactive`. Update `theme_manager.py`, `hermes.tcss`, default skins.
B-3: `if False:` dead branch in `_refresh_display` removed by P0-3 rewrite.

**Why:** Audit found chip form is net-positive, expanded form is net-negative; Done section is pure duplication; 1Hz tick wastes frame budget.
**How to apply:** All changes in `plan_panel.py` / `hermes.tcss` / `theme_manager.py`; ~8 test groups in `tests/tui/test_plan_panel_p0.py`.
