---
name: Audit 4 Quick Wins spec
description: 15 small P0/P1/P2 fixes from audit 4 — bindings, countdown, pane, skin preview, sessions tab, minimap color, etc.
type: project
originSessionId: cfcecd26-19f5-49dc-8bf4-f8660e32392c
---
IMPLEMENTED 2026-04-24 — spec at `/home/xush/.hermes/2026-04-24-audit4-quick-wins-spec.md`; commit 88c6c7b6; branch feat/audit4-quick-wins

Issues: TRIGGER-01/02/04, INTR-01/05/06, PANE-01/02, CONFIG-02, CONFIG-03, CONFIG-04, REF-02, REF-03, BROWSE-02, SESS-01
Tests: 33 in `tests/tui/test_audit4_quick_wins.py`

**Why:** All small/low-risk fixes identified in audit 4 (overlays, navigation, IA). Each is independently reverted.

**How to apply:** Done. Worktree at `../worktrees/audit4-quick-wins`.
