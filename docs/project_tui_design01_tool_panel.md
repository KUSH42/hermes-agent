---
name: TUI Design 01 — Tool Panel Affordances spec
description: IMPLEMENTED spec for TOOL-1/2/3/4 footer routing, strip label, header trim, syntax theme
type: project
originSessionId: bfaa96d5-8607-482c-b166-841d78544fb5
---
IMPLEMENTED 2026-04-24; TOOL-1 ACTION_KIND_TO_PANEL_METHOD + full chip dispatch + flash on error; TOOL-2 file strip `c diff`→`c copy`; TOOL-3 `_trim_tail_segments` drops `hero` not `flash`; TOOL-4 static preview reads `preview-syntax-theme`→`syntax-theme`→`monokai`; 6 tests; branch feat/textual-migration

**Why:** Design audit found silent no-ops on footer action chips, wrong key label in collapsed strip, flash dropped before hero under narrow widths, and hardcoded Monokai ignoring user syntax theme setting.

**How to apply:** Spec file at `/home/xush/.hermes/2026-04-24-tui-design-01-tool-panel-affordances-spec.md`; test file `tests/tui/test_tool_panel_affordances.py`.
