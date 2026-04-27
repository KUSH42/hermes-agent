---
name: Tool call UX audit pass 10 spec
description: Approved spec for 19 fixes across themes A-J; ToolHeaderBar deletion, detail_level retirement, mini-mode opt-in, collapsed-stub, error badge
type: project
originSessionId: ff7b09b2-143d-4516-894c-6480d74a460b
---
Spec at `/home/xush/.hermes/2026-04-22-tool-ux-audit-pass10-spec.md` — Status: **DONE** 2026-04-22.

**Why:** Consolidates redundant rendering paths surviving from v2→v4 migration: dual headers, 4 collapse fields, dual grouping systems, silent auto-hide.

**Key deletions (done):** `tool_header_bar.py`, `result_pill.py`, `tool_panel_mini.py` removed. `detail_level` reactive retired. `ToolHeaderBar` compact sync migrated to `_app_watchers.py` iterating `ToolPanel` directly.

**Merged:** `fix/tool-ux-pass6` → `feat/textual-migration` (7 commits, merge commit 39c90fd4).

**Critical gotchas (for reference):**
- Rich bracket eating: `Button("[foo]", ...)` → empty label. Use `Button(Text("[foo]"), ...)`.
- D3 OmissionBar: bar stays visible when `cap_msg` exists even if all lines shown.
- ECB `_header._header_args = {"snippet": ...}` carries first code line; `_label` stays constant.
- `/density auto-mini` is explicit opt-in; no-arg `/density` still cycles compact↔full.
