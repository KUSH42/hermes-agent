---
name: Audit 1 Phase Legibility spec
description: DONE 2026-04-24; A1/A2/A4/A5/A9; status_phase enum + nameplate gating + DEEP threshold + chip semantics + STARTED label; 50 tests; branch feat/audit1-phase-legibility
type: project
originSessionId: 00befacd-d165-4081-8bba-5e7a2a3862f1
---
DONE 2026-04-24. Branch: `feat/audit1-phase-legibility` (from `feat/textual-migration`). Spec at `/home/xush/.hermes/2026-04-24-audit1-phase-legibility-spec.md`. 2 commits, 50 tests in `tests/tui/test_audit1_phase_legibility.py`.

**Why:** Users can't distinguish reasoning / streaming / tool-exec phases. Three simultaneous pulse animations all signal "alive". DEEP mode activates too eagerly. PlanPanel chip duplicates StatusBar counts.

**A1 — `status_phase` reactive:**
- New `hermes_cli/tui/agent_phase.py` — `Phase` plain-string constants (IDLE/REASONING/STREAMING/TOOL_EXEC/ERROR). Import as `from hermes_cli.tui.agent_phase import Phase`.
- `HermesApp.status_phase: reactive[str] = reactive(Phase.IDLE)` — import `_Phase` at module top.
- `watch_status_phase(old, new)` toggles `--phase-{name}` CSS class on app root (TCSS gating).
- `watch_agent_running`: first line sets `status_phase = REASONING if value else IDLE`.
- `IOService.consume_output`: sets STREAMING on first token; sets REASONING (or IDLE if not running) on `on_streaming_end` hook.
- `ToolRenderingService._open_tool_count: int = 0` — increment on `open_streaming_tool_block`, decrement on both `close_streaming_tool_block` and `close_streaming_tool_block_with_diff`. Sets TOOL_EXEC on open; reverts to REASONING/IDLE when count reaches 0.
- `_lc_reset_turn_state` resets `_svc_tools._open_tool_count = 0`.
- `WatchersService._phase_before_error: str = ""` — saved on error set, restored on clear. Phase.ERROR is orthogonal (can overlay any running phase).

**A2 — Nameplate phase gating:**
- `AssistantNameplate.on_mount` wires `self.watch(self.app, "status_phase", self._on_phase_change)`.
- `_pause_pulse()` — calls `_stop_timer()` only; `--active` CSS stays (turn-in-progress color persists).
- `_on_phase_change(phase)` — REASONING: restart pulse if ACTIVE_IDLE and timer is None; STREAMING/TOOL_EXEC: `_pause_pulse()`; IDLE/ERROR: no-op (other paths handle these).

**A4 — DEEP mode threshold:**
- `ThinkingWidget._cfg_deep_after_s: float = 120.0` (config: `tui.thinking.deep_after_s`).
- `_substate_start = time.monotonic()` set when LONG_WAIT entered in `_tick`.
- `_resolve_mode`: after width checks, if resolved mode == DEEP, gates on `elapsed = now - getattr(self, "_substate_start", now)` vs `_cfg_deep_after_s`. Below threshold → COMPACT.
- `getattr(..., "_substate_start", time.monotonic())` default means elapsed=0 → COMPACT when field not yet set (correct).

**A5 — PlanPanel chip semantics:**
- `_PlanPanelHeader.update_header` gains `next_tool_name: str = ""` kwarg.
- `_show_chip`: chip-running and chip-done always hidden. Title = `"Plan ▸  next: {name}"` or `"all done"` or `"—"`. Pending count appended as `{n}⏵` when > 0. Errors and cost unchanged.
- `PlanPanel._rebuild_header` resolves first `PlanState.PENDING` entry's `tool_name`.
- `test_plan_panel_p1.py` updated: `test_chip_running_shows_when_running_gt_0` → `test_chip_running_always_hidden_in_chip`; `test_chip_running_hidden_when_running_zero` → `test_chip_done_always_hidden_in_chip`; `test_show_chip_pending_in_title_text` checks `⏵` not `▸`.

**A9 — STARTED label:**
- `ThinkingWidget._get_label_text(elapsed=None) -> str` extracted from `_tick`. Returns `"Connecting…"` for STARTED, `"Thinking…"` (base_label) for WORKING, `"{prefix}… ({n}s)"` for LONG_WAIT.
- `_tick` uses `label_text = self._get_label_text(elapsed)` instead of inline logic.

**How to apply:** Import Phase from `hermes_cli.tui.agent_phase`. Phase drives CSS gating via `--phase-{name}` classes. Never set `status_phase` in a lifecycle hook callback — set it only in the reactive path (watcher or service method called from event loop). `_open_tool_count` must stay in sync with `_active_streaming_blocks` — always increment/decrement together.
