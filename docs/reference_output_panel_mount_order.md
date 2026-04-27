---
name: OutputPanel mount order — canonical widget ordering contract
description: The invariant layout order in OutputPanel and the correct anchor for all dynamic mounts
type: reference
originSessionId: 66c9c022-2174-4259-82c9-399028aab58c
---
**OutputPanel compose order (fixed, always at bottom):**
```
[...dynamic content...]
ToolPendingLine   (display:none by default)
ThinkingWidget    (display:none by default)
LiveLineWidget    (always present)
```

**All dynamic content mounts use `before=output.tool_pending` as anchor:**

| Widget | Call | Mount target |
|---|---|---|
| MessagePanel | `output.new_message()` | `output.mount(mp, before=output.tool_pending)` |
| UserEchoPanel | `app.echo_user_message()` | `output.mount(uep, before=output.tool_pending)` |
| ToolBlock | `app.mount_tool_block()` | `output.mount(tb, before=output.tool_pending)` |
| StreamingToolBlock | `app.open_streaming_tool_block()` | `output.mount(stb, before=output.tool_pending)` |

**Why this works across turns:** When turn N+1 starts, new content is inserted at `before=tool_pending`. Turn N's ToolBlocks/STBs (already mounted before tool_pending) stay correctly ordered *between* turn N's MessagePanel and turn N+1's UserEchoPanel. No orphaning.

**Bugs this prevents:**
- `before=output.live_line` → STBs land between ThinkingWidget and LiveLineWidget; after next turn they're stranded below the new turn's content
- `panel.mount(tb)` (no anchor) → appends ToolBlock at END of MessagePanel, after response text (wrong visual order)
- `ThinkingWidget.activate()` changing display toggles virtual height — when it was at the top of OutputPanel (before any messages), every toggle caused a layout shift and scroll position corruption

**Integration tests:** `tests/tui/test_mount_order.py` (12 tests)
