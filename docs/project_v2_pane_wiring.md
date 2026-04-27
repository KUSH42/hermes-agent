---
name: v2 Pane PlanPanel Wiring spec
description: IMPLEMENTED spec for wiring real PlanPanel into v2 left pane and deleting plan_panel_stub.py
type: project
originSessionId: 0d2a2266-d841-4113-a4d5-feac3e5cc1a1
---
IMPLEMENTED 2026-04-24; P1: PlanPanel in left pane for layout=v2, delete PlanPanelStub; 14 tests; commit c57f03c8; branch feat/textual-migration

**Why:** R2 pane layout was mounting a stub; real PlanPanel is ready. Also fixes bare `except Exception: pass` → `logger.exception` and adds `dock: none` CSS override in hermes.tcss.

**How to apply:** DONE. Use PENDING (not RUNNING) state in planned_calls reactive tests to avoid _NowSection._ensure_timer starting a set_interval that blocks pilot.pause().
