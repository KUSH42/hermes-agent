---
name: Audit 2 Structural Cleanup spec
description: Audit 2 structural cleanup — two phases; Phase 1 safe, Phase 2 (completion unification) risky
type: project
originSessionId: 893fc893-43d3-44ef-bb0a-624e6f2fb1a9
---
FULLY IMPLEMENTED 2026-04-24. Phase 1 commit 0c8da197 (144 tests). Phase 2 (B2) commit 8d6974c2 (12 tests). Both specs flipped to IMPLEMENTED.

Spec: /home/xush/.hermes/2026-04-24-audit2-structural-spec.md

**Why:** Legacy shims (_safe_collapsed triple-fallback, FooterPane non-remount, ChildPanel overrides user preference), diff renderer 1:1 limitation, and tool_panel.py at 1745 lines. B2 (completion path) is a bigger architectural bet.

**Phase 1 (B12–B16) — safe:**
- B15: Simplify `_safe_collapsed` — 3-level fallback → `bool(panel.collapsed if panel is not None else False)`
- B13: Add `FooterPane.on_mount` guard: raises if mounted twice (surfaces latent bug)
- B14: Add `_user_touched_compact: bool` to ChildPanel; auto-uncompact on error only when `not _user_touched_compact`
- B12: Extend diff renderer to N:M word-diff using `difflib.SequenceMatcher` on accumulated chunks
- B16: Split `tool_panel.py` (1745L) into `tool_panel/` subpackage: `_core`, `_completion`, `_actions`, `_footer`, `_child`; keep shim at old path

**Phase 2 (B2) — risky, gate on Phase 1 green:**
- B2: Always use `StreamingToolBlock` + `ToolPanel` for display (delete static `ToolBlock` path). `ToolBlock` becomes a deprecated subclass of `StreamingToolBlock`.

**How to apply:** Phase 1 commit order: B15, B13, B14, B12, B16. Do not start B2 until Phase 1 has merged and CI is green.
