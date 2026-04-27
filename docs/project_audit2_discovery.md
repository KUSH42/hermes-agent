---
name: Audit 2 Discovery & Affordances spec
description: Audit 2 action discoverability — collapsed action strip, real buttons, focus hint
type: project
originSessionId: 893fc893-43d3-44ef-bb0a-624e6f2fb1a9
---
DONE 2026-04-24. B1/B5/B9; 37 tests; branch feat/audit2-discovery-affordances (commit cfb00c59).

Spec: /home/xush/.hermes/2026-04-24-audit2-discovery-affordances-spec.md

**Why:** Tool actions (retry, copy, open) exist but are invisible in collapsed state and have no mouse affordance. 30+ bindings have no discovery surface.

**Issues:**
- B1: When ToolPanel is collapsed+focused, show a `_CollapsedActionStrip` with 3–5 filtered actions (retry only on error, err only with stderr). Strip hides on blur/expand/streaming. New widget in `tool_panel.py`.
- B5: FooterPane action row is plain Rich Text that looks like buttons but isn't. Convert to real `Button` widgets in `_action_row: Horizontal`. Add `on_button_pressed` to `FooterPane` that calls the corresponding `ToolPanel.action_*()` method.
- B9: On first focus of a completed ToolPanel, flash hint-bar "  [?] or F1 → tool keys" at priority=0 for 3s. Track `_discovery_shown` per panel and `_DISCOVERY_GLOBAL_SHOWN` module-level (cleared when user presses `?` or F1).

**How to apply:** Implement B5 first (contained), then B1 (new widget), then B9 (FeedbackService dependency). B1 strip and B5 action row are complementary — different panel states (collapsed vs expanded).
