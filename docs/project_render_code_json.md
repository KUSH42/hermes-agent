---
name: Render code-json spec
description: IMPLEMENTED CodeRenderer + JsonRenderer polish (R-C1..R-C4, R-J1..R-J3); 23 tests; commit 1cabe40f
type: project
originSessionId: 753cc8e6-1dac-4729-858c-64a39e591a97
---
R-C1..R-C4 CodeRenderer and R-J1..R-J3 JsonRenderer polish.

**Why:** rendereraudit.md spec 4a — skin-driven Syntax theme, conditional line numbers, regex fence, lang+origin header, valid-JSON output, parse-fail hint, large-object collapse.

**How to apply:** All 23 tests in `tests/tui/test_render_code_json.py`. Cherry-picked as commit 1cabe40f onto feat/textual-migration from worktree branch worktree-render-code-json.

Key implementation decisions:
- `body_renderers/code.py`: `_FENCE_RE` anchored regex with `(?!```)` negative-lookahead; `build()` returns `Group(header, Syntax)`; line numbers conditional on >=6 lines or `start_line` in args; `self.colors.syntax_theme` for theme.
- `body_renderers/json.py`: `_JsonCollapseWidget` child widgets in `__init__` (not `compose`) for pure-unit toggle tests; collapse threshold via `tui.json.collapse_threshold` config; `_build_summary_text` uses `RichText.append("[expand]")` not string concat (avoids Rich markup parsing).
- `body_renderers/streaming.py`: All `"monokai"` literals replaced with `"ansi_dark"` (SkinColors.default().syntax_theme) since streaming renderers are stateless singletons with no app access.
