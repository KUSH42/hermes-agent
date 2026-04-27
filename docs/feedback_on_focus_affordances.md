---
name: on_focus affordances guard
description: ToolPanel.on_focus must check _has_affordances before flashing toggle hint
type: feedback
originSessionId: 13cbf76b-1b41-4330-a37f-1e38c7290e98
---
ToolPanel.on_focus only flashes the "(Enter) toggle" hint when `block._header._has_affordances` is True. When `_block` is None (no block attached), do NOT flash by default.

**Why:** pass8_d D4 is the authoritative spec — flash is only meaningful when the panel has expandable content. pass7_c was written before this guard and needed updating to set `_block._header._has_affordances = True` in its test fixture.

**How to apply:** When writing tests for `on_focus`, always wire up a `_block` mock with the appropriate `_has_affordances` value. Don't test `on_focus` on a bare `__new__`-constructed panel without a block.
