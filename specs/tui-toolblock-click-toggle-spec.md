# TUI ToolBlock Click-to-Toggle — Feature Specification

**Status:** APPROVED  
**Impact:** Low-Medium  
**Key:** SPEC-D  

---

## 1. Problem Statement

`ToolBlock` headers currently support only two interaction modes:

1. **Browse mode** (keyboard-driven): `Tab`/`Enter` to navigate and toggle
2. **Right-click context menu**: "Expand/Collapse" action

Left-click on a `ToolHeader` does nothing. This is a discoverability gap — users naturally try to click the header to expand/collapse tool output, as they would in any collapsible-section UI.

---

## 2. Scope

| In scope | Out of scope |
|---|---|
| Left single-click on `ToolHeader` → toggle collapsed state | Double-click |
| Visual hover feedback (CSS background shift) | Drag to resize |
| Click during streaming silently ignored | Click on `ToolBodyContainer` content |
| Click on no-affordance header silently ignored | Animating the expand/collapse height transition |

---

## 3. Behaviour Specification

### 3.1 Click target

Any left-click (`event.button == 1`) on a `ToolHeader` triggers a toggle. The full header row is the hit target — not just the chevron area.

### 3.2 Toggle logic

Calls `parent_block.toggle()` — the existing `ToolBlock.toggle()` method. Identical to the browse-mode `Enter` key path.

### 3.3 Streaming guard

If `ToolHeader._spinner_char is not None` (block is in STREAMING state), the click is silently ignored. No visual feedback for this case — it would create noise during active tool execution.

### 3.4 `COLLAPSE_THRESHOLD` guard

If `ToolHeader._has_affordances is False` (block has ≤ 3 lines, always expanded), the click is silently ignored.

---

## 4. Implementation

### 4.1 Add `on_click` to `ToolHeader`

In `hermes_cli/tui/tool_blocks.py`, add to `ToolHeader`:

```python
from textual.events import Click  # add to imports at top of file

def on_click(self, event: Click) -> None:
    """Left-click toggles the parent ToolBlock.
    
    Right-clicks (button=3) are not intercepted here — they bubble up to
    HermesApp.on_click() which builds the context menu.
    """
    if event.button != 1:
        return                          # right/middle click: let bubble to HermesApp
    if self._spinner_char is not None:
        return                          # streaming: ignore click
    if not self._has_affordances:
        return                          # always-expanded block: nothing to toggle
    event.prevent_default()
    parent = self.parent
    if parent is not None:
        parent.toggle()
```

`Click` is imported from `textual.events`. The existing `from typing import Any` import does not need to change.

### 4.2 CSS hover feedback

Add to `hermes.tcss`:

```css
/* ToolHeader — hover affordance */
ToolHeader:hover {
    background: $accent 8%;
}
```

**Note:** `cursor: pointer` is a web CSS property not supported by Textual's CSS engine and must NOT be added. The hover background change is sufficient to communicate clickability.

---

## 5. Interaction with Existing Click Handler

`HermesApp.on_click()` guards with `if event.button != 3: return` — it does nothing for left-clicks. The new `ToolHeader.on_click()` therefore has no conflict regardless of whether `event.prevent_default()` is called or not.

**Clarification on `prevent_default()`:** In Textual's event model, `prevent_default()` prevents the widget's *default action* (e.g. focus steal on click) but does NOT stop event bubbling to ancestor handlers. The event still reaches `HermesApp.on_click()`, but since that handler immediately returns on `button != 3`, the behaviour is correct. The `prevent_default()` call is still correct — it suppresses any default Textual click behaviour on the widget (e.g. unintended focus changes).

---

## 6. StreamingToolBlock Considerations

`StreamingToolBlock` subclasses `ToolBlock`. The streaming guard (`self._spinner_char is not None`) covers the STREAMING state. On `COMPLETED`, `_spinner_char` is set to `None`, so click-to-toggle works on completed streaming blocks.

---

## 7. Tests

Add to `tests/tui/test_tool_blocks.py` or create `tests/tui/test_tool_block_click.py`:

| # | Test | Assertion |
|---|---|---|
| 1 | Left-click on `ToolHeader` with affordances → block toggles | `collapsed` changes from True to False |
| 2 | Second left-click → block toggles back | `collapsed` changes from False to True |
| 3 | Left-click while streaming (`_spinner_char != None`) → no toggle | `collapsed` unchanged |
| 4 | Left-click on no-affordance header (`_has_affordances=False`) → no toggle | `collapsed` unchanged |
| 5 | Right-click on `ToolHeader` → `on_click` returns without toggling | `collapsed` unchanged; right-click bubbles to HermesApp |
| 6 | Click on `ToolHeader` calls `parent.toggle()` | Mock `toggle()` called exactly once |
| 7 | `ToolHeader:hover` CSS rule present in stylesheet | `app.get_css_variables()` or stylesheet content check |

---

## 8. Non-Goals

- Height tween animation on expand/collapse
- Double-click to expand all
- Keyboard shortcut remapping
