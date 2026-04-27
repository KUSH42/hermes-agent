---
name: Output pane design spec
description: Full design reference for the TUI output pane — widget inventory, data flow, visual design, performance contracts, gotchas, and future roadmap
type: project
originSessionId: ff5affc3-d9b0-4965-bb30-ea33976479dc
---
Spec written 2026-04-12 at /home/xush/.hermes/output-pane-design-spec.md

**Why:** Mirrors the bottom-bar-design-spec.md format. Created as a living reference document for anyone working on the output zone of the TUI.

**How to apply:** When working on OutputPanel, MessagePanel, ToolBlock, streaming tool output, reasoning display, or the output queue — consult this spec first.

Key facts captured:
- Mount order invariant: always `before=output.tool_pending`; trio [ToolPendingLine, ThinkingWidget, LiveLineWidget] must be last
- `CopyableRichLog.write()` width resolution fix (max of region_w vs app.size.width)
- `overflow-y: hidden` required on all inner RichLogs to avoid swallowing scroll events
- CSS type selector matching uses `_css_type_name` not base class name
- Sentinel (None) path from flush_output() is dead code; all teardown via `watch_agent_running(False)`
- ToolTail scroll-lock wiring **fully implemented** (2026-04-12): `StreamingToolBlock.compose()` yields `self._tail`; `_flush_pending()` increments `tail._new_line_count` when `_user_scrolled_up`; `watch_scroll_y` on `OutputPanel` dismisses tails on return to live edge. `tail._new_line_count` is the **single source of truth** — the duplicate `_tail_new_count` field on `StreamingToolBlock` was removed (bug: it wasn't reset when `tail.dismiss()` was called externally, causing stale accumulation on second scroll session).
- `open_streaming_tool_block()` calls `scroll_end` after mounting (bug fix 2026-04-12 — was missing; every other mutation called it).
