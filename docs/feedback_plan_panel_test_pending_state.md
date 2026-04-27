---
name: PlanPanel reactive tests — use PENDING not RUNNING state
description: Using PlanState.RUNNING in planned_calls tests starts a set_interval timer that blocks pilot.pause() indefinitely
type: feedback
originSessionId: 34bc9a2d-936c-41ad-b49f-b3dbcb113752
---
Use `PlanState.PENDING` (not `RUNNING`) when setting `app.planned_calls` in async `run_test` tests for PlanPanel.

**Why:** `PlanState.RUNNING` triggers `_NowSection.show_call()` → `_ensure_timer()` → `self.set_interval(2.0, self._tick)`. The `set_interval` keeps the Textual message counter non-zero. `pilot.pause()` waits for the counter to reach zero, so it never returns → `WaitForScreenTimeout` → SIGALRM conftest kills the test after 30 s.

**How to apply:** In any test that checks `--active` class or reactive propagation, set `mock_call.state = PlanState.PENDING` and also set `mock_call.depth = 0`, `mock_call.label = "..."`, `mock_call.tool_call_id = "..."` to avoid MagicMock attribute issues in `_NextSection.update_calls`. `PENDING` still satisfies `has_any=True` → `--active` is added.
