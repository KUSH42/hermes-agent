---
name: R4 services refactor
description: Status of R4 — extracting 10 HermesApp behavioral mixins into services/ subpackage
type: project
originSessionId: be7a341b-8e14-4d76-b938-c12b25920470
---
10 `AppService` subclasses in `hermes_cli/tui/services/`. All `_app_*.py` mixins are 1-line adapter shells.

**Why:** app.py grew to 2900+ LOC; mixins still large and tightly coupled. Services = plain Python objects, independently testable.

**Phase status:**
- Phase 1+2 ✅ merged — shells + adapters; 40 wiring tests
- Phase 3 ✅ merged — flash_hint routing fixed (all services call `app._flash_hint`); 1 test patched
- Phase 4 ✅ merged — all 10 `_app_*.py` files deleted; `HermesApp(App)` only; 248 tests passing

**Merged to:** `feat/textual-migration` (commit `98de6f8e`)

**`_flash_hint` note:** In `app.py` on `feat/textual-migration`, `_flash_hint` routes through FeedbackService (RX1). In any R4-derived worktree that predates RX1, it routes through `_svc_theme.flash_hint` — HEAD wins on merge.
