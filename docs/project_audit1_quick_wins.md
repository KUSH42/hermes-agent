---
name: Audit 1 Quick Wins spec
description: DONE 2026-04-24; A6/A8/A10/A11/A12/A13/A14/A15 — nameplate default, StatusBar cleanup, ghost legend, budget gate, ThinkingWidget reserve timer; 23 tests
type: project
originSessionId: cdb835df-76b2-4765-bab5-5a18f50a6673
---
Status: DONE 2026-04-24
Branch: audit1-quick-wins (merged into feat/textual-migration)
Commit: 827e6036
Spec: /home/xush/.hermes/2026-04-24-audit1-quick-wins-spec.md
Tests: 23 (tests/tui/test_audit1_quick_wins.py) + updated test_plan_panel_p0.py

**Why:** Addressed 8 P1/P2 audit issues: redundant liveness animations, dead code, layout inconsistency, incomplete wiring, race/flicker, and missing affordances.

**How to apply:** All changes are complete. No follow-up needed for these items. The A13 change (budget visibility gate) obsoleted the 5s timer tests in test_plan_panel_p0.py — those were updated in the same commit.

## Changes made

| ID | File | Change |
|----|------|--------|
| A6 | widgets/__init__.py, cli.py, app.py | Default idle_effect "shimmer" → "breathe" |
| A8 | widgets/status_bar.py | Removed "F1 help · /commands" from idle state |
| A10 | widgets/status_bar.py | Deleted `__getattr__` / `_get_idle_tips` dead block |
| A11 | widgets/status_bar.py | Moved model to first position in ≥60-col branch |
| A12 | input/_history.py, input/widget.py | Wired show_legend("ghost") from update_suggestion; one-per-session gate |
| A13 | widgets/plan_panel.py | Replaced 5s _budget_hide_timer with collapsed/running/non-zero gate |
| A14 | widgets/thinking.py | Added 2s _reserve_fallback_timer in _do_hide() |
| A15 | widgets/status_bar.py | Removed progress > 0 guard; 0% always rendered (part of A11 rewrite) |
