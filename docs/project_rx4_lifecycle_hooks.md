---
name: RX4 AgentLifecycleHooks spec
description: Priority-ordered lifecycle cleanup registry — all phases a+b+c+d DONE; merged feat/textual-migration (3149919e)
type: project
originSessionId: 94d90175-4fba-4775-8a8a-6c8aabee2bf5
---
**Why:** 175-line `watch_agent_running` had 17+ inline side effects in source-line order. No enforced checklist meant audit passes kept finding "forgot to reset X when Y". RX4 extracts cleanup into named callbacks registered against the transition they care about.

**Service:** `hermes_cli/tui/services/lifecycle_hooks.py` → `AgentLifecycleHooks`, accessed as `app.hooks`.

**Wiring:**
- `app.__init__`: `self.hooks = AgentLifecycleHooks(self)` (before R4 services) + `self._interrupt_source = None`
- `app.on_mount` end: `_register_lifecycle_hooks()` + `hooks.drain_deferred()`
- `app.on_unmount` start: `hooks.shutdown()`
- `watch_agent_running(True)` → `hooks.fire("on_turn_start")`
- `watch_agent_running(False)` → `hooks.fire("on_turn_end_any")`, then `on_turn_end_{success,error}`, then `on_interrupt` if `_interrupt_source` set
- `WatchersService.on_status_compaction_progress(0.0)` → `hooks.fire("on_compact_complete")`
- `WatchersService.on_status_error` → `hooks.fire("on_error_set"/"on_error_clear")`
- `IOService.consume_output` → `hooks.fire("on_streaming_start")` / `hooks.fire("on_streaming_end")`
- `SessionsService.switch_to_session()` → `hooks.fire("on_session_switch", target_id=...)` before `app.exit()`
- `app.handle_session_resume()` → `hooks.fire("on_session_resume", session_id=..., turn_count=...)`

**`_interrupt_source` flag:** Set in `services/keys.py` at 3 sites — `"esc"` (ESC path), `"ctrl+shift+c"`, `"resubmit"` — immediately before `cli.agent.interrupt()`. Read and cleared by `watch_agent_running(False)`.

**Registered callbacks** (all in `_register_lifecycle_hooks()`):
- `on_turn_start`: osc_progress_start (p10), dismiss_info_overlays (p50), reset_turn_state (p100)
- `on_turn_end_any`: osc_progress_end (p10), desktop_notify (p10), clear_output_dropped_flag (p100), clear_spinner_label (p100), clear_active_file (p100), reset_response_metrics (p100), clear_streaming_blocks (p100), drain_gen_queue (p100), restore_input_placeholder (p900)
- `on_turn_end_success`: auto_title_first_turn (p100), chevron_done_pulse (p500)
- `on_interrupt`: osc_progress_end_interrupt (p10)
- `on_compact_complete`: reset_compaction_warn_flags (p100)
- `on_error_set`: schedule_status_error_autoclear (p100)
- `on_error_clear`: cancel_status_error_timer (p100)
- `on_session_switch`: session_switch_cleanup (p100) — releases blocking queues, interrupts agent
- `on_session_resume`: session_resume_reset (p100) — cancels error timer, clears status_error

**Debug:** F12 → `action_debug_hooks_snapshot` logs `hooks.snapshot()` + flashes hint.

**Phase status:**
- Phase a ✅ 2026-04-22 — service + core callbacks + 19 tests
- Phase b ✅ 2026-04-22 — dual execution deleted, error/compact/streaming hooks wired, D2 fix; 33 tests; commit 16f7004a
- Phase c ✅ 2026-04-22 — interrupt source wired at all 3 key sites; session_switch/resume hooks + cleanup callbacks; dismiss_info_overlays hook; F12 binding; 28 tests
- Phase d ✅ 2026-04-22 — EXPECTED_SNAPSHOT constant (§9 table); AST snapshot test; test_snapshot_keys_match_expected; SKILL.md Phase d section; 29 tests
- Merged feat/textual-migration: merge commit 3149919e (71 total lifecycle tests)

**How to apply:** Any new "reset X on turn end" logic → `_lc_*` method registered via `hooks.register(...)` in `_register_lifecycle_hooks()`. Never add inline cleanup to `watch_agent_running` or watchers.
