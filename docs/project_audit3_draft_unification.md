---
name: Audit 3 Draft Unification spec
description: Audit 3 — I5 delete _history_draft, keep only _draft_stash as single draft field with TextArea.Changed invalidation
type: project
originSessionId: 512f7281-1426-4bd8-a34e-a52d1ac56534
---
IMPLEMENTED 2026-04-24; 15 tests in test_audit3_draft_unification.py; 143 tests passing across 4 related files; commit pending

**Why:** Two draft fields (_history_draft + _draft_stash) with divergent invalidation watchers cause stale draft restores after edit-then-navigate cycles.

**How to apply:** ~1 day. Delete _history_draft in widget.py and _history.py; fold prev-action draft-save into save_draft_stash() with _draft_stash is None guard (critical: preserves overlay-saved stash); restore-to-empty when _draft_stash is None on forward-past-end. Grep must cover tests/tui/ too (test_hermes_input.py:841 has known hit).
