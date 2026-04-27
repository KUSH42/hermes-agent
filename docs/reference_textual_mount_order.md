---
name: Textual mount() anchor resolution — _find_mount_point gotcha
description: before= in Widget.mount() resolves to the anchor's actual parent, not self — silently mounts into wrong container
type: reference
originSessionId: 66c9c022-2174-4259-82c9-399028aab58c
---
**Critical:** `widget.mount(child, before=other_widget)` resolves the insertion parent from `other_widget.parent`, NOT from `widget` (self).

```python
# panel is MessagePanel, output.live_line is in OutputPanel
panel.mount(block, before=output.live_line)
# → actually mounts block into OutputPanel, just before live_line
# → NOT into panel (MessagePanel) as the code implies
```

This is by design in Textual's `_find_mount_point()`:
```python
return cast("Widget", spot.parent), spot.parent._nodes.index(spot)
```

**How to apply:** Always ensure the `before=` anchor is a **direct child of the intended parent**. If you want to mount into `panel`, use `before=panel.some_child`, not `before=some_sibling_of_panel`.

**Hermes fix (2026-04-12):** `open_streaming_tool_block` and `mount_tool_block` previously used `panel.mount(block, before=output.live_line)` — silently mounting into OutputPanel before LiveLineWidget instead of into MessagePanel. After fixing (now using `output.mount(block, before=output.tool_pending)`), completed StreamingToolBlocks stay correctly ordered between their turn's content and the next turn.
