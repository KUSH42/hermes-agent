---
name: Audit 3 Input Mode Enum spec
description: Audit 3 — I9+I17 InputMode enum (NORMAL/BASH/REV_SEARCH/COMPLETION/LOCKED), routes chevron glyph+color and InputLegendBar from watch__mode
type: project
originSessionId: 512f7281-1426-4bd8-a34e-a52d1ac56534
---
IMPLEMENTED 2026-04-24; 30 tests; commit 13f4f72e; branch feat/audit3-input-mode-enum

**Why:** Locked state invisible with text present (I9); chevron only swaps glyph for bash (I17). Each mode should have consistent indicator set. Current: bag of booleans. Target: _mode reactive derived from booleans, watch__mode routes all affordances.

**How to apply:** ~2-3 days. New _mode.py enum file; _mode reactive + _compute_mode + watch__mode on HermesInput; 3 new CSS vars; "locked" legend key; strip redundant affordances from _sync_bash_mode_ui / action_rev_search / _exit_rev_mode.
