---
name: R5 DEPRECATED stub cleanup + app forwarder removal
description: All DEPRECATED forwarder stubs removed from app.py — 11 in R5, 21 in dead-code cleanup, 43 in forwarder removal; 0 remain
type: project
originSessionId: a8d3ea9e-f293-4a79-96d7-6a4e0034aba0
---
**DONE** in three passes; 0 DEPRECATED markers remain in app.py.

**R5** (2026-04-23, commit 864ac9fe): 11 zero-caller stubs deleted — spinner group, browse, watchers.
**D1-D7** (2026-04-24, commit 98b8763a): 21 more zero-caller app.py forwarders deleted as part of dead-code cleanup.
**App forwarder removal** (2026-04-24, commit 284a981e): Remaining 43 DEPRECATED forwarders deleted after migrating all callers to service layer directly. Branch: worktree-worktree-app-forwarder-removal.

**Why:** R4 moved logic to services/ but left 75 DEPRECATED forwarder stubs inline. All are now gone.

**How to apply:** No DEPRECATED markers remain. All production code calls service layer directly (e.g. `app._svc_spinner.set_hint_phase(...)` not `app._set_hint_phase(...)`). The 43-test absence suite in `tests/tui/test_app_forwarder_removal.py` guards against regression.
