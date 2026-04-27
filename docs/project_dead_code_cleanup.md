---
name: TUI Dead Code Cleanup spec
description: IMPLEMENTED spec for D1–D7 dead-file and dead-forwarder cleanup; 29 tests; commit 98b8763a; branch worktree-dead-code-cleanup
type: project
originSessionId: a1edfb71-9483-45f9-bf6b-3b17a9c9f010
---
IMPLEMENTED 2026-04-24; D1–D7: 5 dead source files + finalize_queue + osc52_probe + 21 zero-caller app.py forwarders; 29 new tests; 4 existing test files updated; 3 test files deleted; commit 98b8763a; branch worktree-dead-code-cleanup

**Why:** Post-R4/R5/Audit-1-4 call-site migration left orphaned stubs and dead modules that accumulate confusion.

**How to apply:** Implement only after spec is APPROVED (done). Branch from feat/textual-migration. Follow D5→D3→D1→D6→D4→D2→D7 order; migrate D7 test call sites BEFORE deleting methods.
