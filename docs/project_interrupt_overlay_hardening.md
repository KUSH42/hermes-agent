---
name: InterruptOverlay hardening spec
description: Spec addressing all P0/P1 findings from the 2026-04-23 interrupt/approval UX audit — dismiss path unification, stale deadline fix, UNDO keybindings, silent replace guard, plus A-1/A-2/B-1/C-2/C-3/D-1/D-2
type: project
originSessionId: f1f58b53-0a8b-4540-935b-8297cf362ece
---
Spec at `/home/xush/.hermes/2026-04-23-interrupt-overlay-hardening-spec.md`

**Why:** Audit found 4 P0 bugs converging to make APPROVAL flow unreliable: stale deadline → silent auto-deny after undo preempt; 4 dismiss paths disagree on resolution value; UNDO advertises [y]/[n] but only Arrow+Enter works; replace=True silently swaps diff.

**Status:** IMPLEMENTED 2026-04-23 — commit 20c4c1c0, merged feat/textual-migration

**8 phases, 4 files, 46 tests:**

- Phase A: Delete bypass blocks from keys.py; all dismiss → `ov.dismiss_current("__cancel__")` (F-1/F-3)
- Phase B: Preempt stamps `prior.deadline=0` + `_remaining_on_preempt=remaining`; `_activate` rebases from snapshot (C-1)
- Phase C: `on_key` accelerators — `y`/`n` for UNDO, `o`/`s`/`a`/`d` for APPROVAL/CLARIFY (F-2)
- Phase D: Same-kind replace flashes `--flash-replace` border 300ms, resets `selected=0`, blocks Enter 250ms (G-1)
- Phase E: Queue cap `_MAX_QUEUE_DEPTH=8`; `Ctrl+Shift+Esc` drains all; depth shown in `border_subtitle` (C-2/C-3)
- Phase F: `_refresh_base_row()` + `_refresh_strategy_row()` on button clicks (A-1)
- Phase G: Diff focus ring CSS, `--scrollable` class, SECRET urgency=warn, double-Enter guard for "always"/"session", border escalates to --urgency-danger at ≤3s (B-1/D-1/A-2/E-1)
- Phase H: `_post_interrupt_focus()` helper in WatchersService, called from ALL `on_*_state(None)` branches (D-2)

**Key decisions:**
- User-authoritative deadline rebase (not agent-authoritative) — preempted prompt restarts clock from remaining
- Escape + Ctrl+C both → `"__cancel__"` → `cancel_value` (adapter-defined); APPROVAL cancel = `None`, timeout = `"deny"`
- `_confirm_destructive_id` sentinel cleared by `_teardown_current` — no bleed across interrupts
