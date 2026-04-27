---
name: Audit 3 Completion Accept Overhaul spec
description: Audit 3 — I4 mid-string Tab flash hint, I10 Enter honors highlighted slash candidate
type: project
originSessionId: 512f7281-1426-4bd8-a34e-a52d1ac56534
---
IMPLEMENTED 2026-04-24; I4/I10; 10 tests; commit c9c2fd71; branch feat/textual-migration

**Why:** Two silent failure modes in completion accept — mid-string Tab dismisses without feedback; Enter submits typed text even when user moved highlight to different slash command.

**How to apply:** Implement after quick wins. I10 in widget.py Enter branch; I4 in _autocomplete.py action_accept_autocomplete.
