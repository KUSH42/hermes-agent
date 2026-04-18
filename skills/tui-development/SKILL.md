---
name: tui-development
description: >
  Architecture, patterns, and API gotchas for the hermes-agent Textual TUI
  (`hermes_cli/tui/`). Covers widget development, thread→app communication,
  overlay state protocol, testing with Pilot, CSS theming, and high-frequency
  Textual pitfalls.
  TRIGGER when: writing or modifying TUI widgets, adding new overlays or
  status bars, debugging Textual rendering, writing tests in `tests/tui/`,
  touching `_cprint` or `_hermes_app`, or working with `hermes_cli/tui/*`.
  DO NOT TRIGGER when: modifying agent logic, tools, config, or non-TUI CLI
  commands (`hermes_cli/commands.py`, `hermes_cli/config.py`, etc.).
compatibility: "Python 3.11+, Textual >=1.0,<9 (pinned), Rich >=14"
metadata:
  author: xush
  version: "3.3"
  target: code_agent
---

## Use this skill for TUI work

This skill is for `hermes_cli/tui/`, TUI-facing bridges in `cli.py`, and
`tests/tui/`. Treat it as an execution guide, not as a replacement for reading
live code.

## First read

Read these files before you edit anything:

1. `hermes_cli/tui/app.py`
2. `hermes_cli/tui/widgets.py`
3. The specific module you will touch under `hermes_cli/tui/`
4. The matching tests under `tests/tui/`

Then load only the focused reference you need:

- `references/module-map.md` for ownership and routing
- `references/patterns.md` for implementation rules and test workflow
- `references/gotchas.md` for known Textual and hermes-specific traps

## High-signal invariants

- Keep blocking I/O, file polling, YAML parsing, and subprocess waits off the
  Textual event loop.
- Only mutate DOM/reactives on the app thread. From worker or agent threads,
  use `app.call_from_thread(...)`, queue handoff, or `post_message(...)`.
- Keep exactly one vertical scroll owner in the output path. Inner
  `RichLog`/`ScrollView` widgets must not keep independent scrolling.
- In the output stack, dynamic content mounts before
  `output.query_one(ThinkingWidget)`. `[ThinkingWidget, LiveLineWidget]`
  remain last.
- `watch_agent_running(False)` owns end-of-turn cleanup. Do not build new logic
  around dead sentinel or fallback cleanup paths.
- When skill text and live code disagree, trust live code and update the skill.

## Fast workflow

1. Find the owning module and tests from `references/module-map.md`.
2. Read the narrow pattern section you need in `references/patterns.md`.
3. Check `references/gotchas.md` before changing timers, overlays, scrolling,
   threading, theming, or completion UI.
4. Implement the change in code and tests together.
5. Run targeted tests first, then broader `tests/tui/` coverage if the change
   crosses module boundaries.
6. If behavior changed materially, update this skill or one reference doc in
   the same patch.

## Common task routing

- New widget or status chrome:
  `module-map.md` widget ownership, then `patterns.md` widget section.
- Streaming/output bug:
  `module-map.md` output stack, then `patterns.md` output API, then relevant
  entries in `gotchas.md`.
- Overlay/input bug:
  `patterns.md` overlay protocol and testing sections, then `gotchas.md`
  overlay/input entries.
- Theme or skin bug:
  `patterns.md` CSS theming section + COMPONENT_CLASSES section, then
  `gotchas.md` theme entries.
- Perf hitch or repaint bug:
  `patterns.md` perf triage section, then `gotchas.md` timer/threading entries.

## Files that usually move together

- `hermes_cli/tui/app.py` with `tests/tui/test_integration.py`,
  `tests/tui/test_turn_lifecycle.py`, or a focused module test
- `hermes_cli/tui/widgets.py` with overlay/status/output tests
- `hermes_cli/tui/tool_blocks.py` with `tests/tui/test_tool_blocks.py`,
  `tests/tui/test_streaming_tool_block.py`, `tests/tui/test_omission_bar.py`,
  `tests/tui/test_path_context_menu.py`, and scroll tests
- `hermes_cli/tui/write_file_block.py` with `tests/tui/test_write_file_block.py`
- `hermes_cli/tui/response_flow.py` with `tests/tui/test_response_flow.py`
- `cli.py` TUI bridge code with `tests/cli/test_reasoning_tui_bridge.py` or
  other bridge tests

## Validation

Last revalidated: **2026-04-18. 104 tool_blocks+streaming+completion tests passing.**

Recent changes (details → reference files):
- **skill_view header fix** (2026-04-18): skill_view/skill_manage STB now shows skill name (e.g.
  "tui-development") as label instead of "skill_view". `_build_tool_label` uses `name` arg for
  `_SKILL_NAME_TOOLS`. `_update_block_label` sets `_compact_tail=True`. Gen block suppressed at
  gen_start for skill tools (orphan prevention) — block created at tool_start where `name` is known.
  → `cli.py §_build_tool_label, _update_block_label, _on_tool_gen_start`
- **Tool header polish** (2026-04-18): shell prompt `$` in accent color for terminal/bash; BashLexer
  syntax highlighting in shell headers; grep icon → nf-fa-expand (); bash tool named + icon added;
  read_file/patch/glob paths auto-linked (clickable, context menu); grep pattern syntax-highlighted;
  GroupHeader removed — virtual grouping via CSS only; diff always `margin-left: 2`; Rule 3b (consecutive
  SEARCH tools group); context menu restores pre-menu focus; `_compact_tail=True` for file-tool STBs
  (timer inline not right-aligned); consecutive same-path patch deduplication; `mount_tool_block` arg
  order bug fixed (`tool_name` moved to pos 4, `rerender_fn` to pos 5, `header_stats` to pos 6).
  → `gotchas.md §Tool header / ToolHeader render`, `gotchas.md §mount_tool_block arg order`
- **v3 post-Phase-E regression fixes** (2026-04-18): Four root-cause bugs fixed:
  1. `close_streaming_tool_block` in app.py never called `panel.set_result_summary()` — glyph stayed `●`, line count stayed `−L`, auto-collapse never ran, renderer swap never ran. Fix: find wrapping ToolPanel via `block.parent.parent.parent`, build ResultSummary via category parser, call `set_result_summary`.
  2. STB internal collapse (`complete()` removing "expanded" class when lines > COLLAPSE_THRESHOLD=3) ran even inside ToolPanel, hiding STB body while ToolPanel stayed at L2. Fix: `_panel_managed` flag on STB; ToolPanel sets it True; `complete()` skips body collapse when flag set.
  3. `default_collapsed_lines` thresholds too small (all 3–6); any tool with >3 lines collapsed to L1 preview. Fix: FILE→200, SHELL→50, CODE→200, SEARCH→200, WEB→100, UNKNOWN→50.
  4. After renderer swap, `_body_line_count()` returned 0 (new CopyableRichLog lacks `_all_plain`/`_total_received`); `_apply_complete_auto_level` used stale 0 count. Fix: `set_result_summary` captures `line_count` before swap and passes to `_apply_complete_auto_level(pre_swap_line_count)`. Also: `_pre_swap_plain_lines` saved in `_swap_renderer` and checked in `_get_all_plain`.
  Tests: updated 3 tests relying on old threshold=3. 1630 total (8 slow excluded).
- **v3 Phase E** (2026-04-18): PerfRegistry + TOOL_PANEL_V3_COUNTERS in perf.py; measure_v3() wired in
  classify_content/tool_panel on_mount/_swap_renderer/watch_detail_level; reduced-motion v3 TCSS rules;
  high-contrast TCSS overrides; scrollbar-gutter:stable on OutputPanel; high-contrast class in app.py
  on_mount. +39 tests. Closes D6, D10 final, D19.
  → `module-map.md`, `gotchas.md §ToolPanel v3-E`
- **v3 Phase D** (2026-04-18): InputSection, SectionDivider, TurnPhase containers, messages.py (ToolRerunRequested+PathClicked),
  full keyboard bindings (space/y/Y/r/o/i), force_renderer, -l{n} CSS classes, L1 preview tail/head logic. +84 tests.
  → `module-map.md`, `patterns.md §ToolPanel v3-D`, `gotchas.md §ToolPanel v3-D`
- **v3 Phase C** (2026-04-18): body_renderers/ package (9 renderers + base + registry), full classify_content()
  heuristics (binary/diff/search/json/table/log/code), VirtualSearchList, InlineCodeFence, ANSI literal pills,
  _swap_renderer in ToolPanel. +120 tests. → `module-map.md`, `gotchas.md §ToolPanel v3-C`
- **v3 Phase B** (2026-04-18): ToolHeaderBar (StatusGlyph+chips), ResultPill, content_classifier stub,
  ToolPanelMini, group_semantic_label; ToolPanel ToolHeader hidden by CSS. +49 tests.
  → `module-map.md`, `patterns.md §ToolPanel v3-B`, `gotchas.md §ToolPanel v3-B`
- **v3 Phase A** (2026-04-18): ToolAccent, DiffAffordance, cwd_strip; ToolPanel layout:horizontal + _PanelContent.
  → `module-map.md`, `patterns.md §ToolPanel v3-A`, `gotchas.md §ToolPanel v3-A`
- **v2 Phase 1–3 + grouping** (2026-04-17): ToolPanel shell, BodyRenderer, detail_level watcher,
  GroupHeader, L0-L3 keybindings. → `module-map.md`, `patterns.md`
- **ExecuteCodeBlock, StreamingCodeBlock, OmissionBar** (2026-04-17): body alignment, output
  separator, footer removed, omission controls. → `patterns.md §ExecuteCodeBlock`
- **File drop + DnD** (2026-04-17): quoted paths, multi-file, GNOME Terminal DnD limitation.
  DnD BLOCKED by Textual terminal config — confirmed no events arrive (no Paste, no Key, no
  Changed). Plain shell DnD works fine; Textual's mouse tracking `\x1b[?1003h` + raw mode
  prevents VTE from writing DnD text to PTY. UNRESOLVED.
  → `gotchas.md §File drop`
- **Path completion fixes** (2026-04-18): CompletionOverlay height 0 bug —
  `VirtualCompletionList.virtual_size = Size(0, 0)` when searching with empty items → ScrollView
  renders nothing → `height: auto` collapses. Fix: `watch_items` sets `height = max(len(new), 1)`
  while `self.searching`. Also: `_PLAIN_PATH_RE` required `/` after `.`/`..`; bare `.` or `..`
  didn't trigger. Fix: regex `(?:\\.\\.?|~)(?:/[\\w./\\-]*)?` (slash optional), `index("/")` → `find("/")`.
  → `completion_context.py`, `completion_list.py`
- **Absolute path completion fix** (2026-04-18): `_ABS_PATH_RE` required TWO slashes
  (`/[\w.\-]+/[\w./\-]*`), so `/etc` without trailing `/` or partial name `/ho` fell through to
  NATURAL. Fix: make second component optional → `/[\w.\-]+(?:/[\w./\-]*)?`. Now `/etc`, `/ho`,
  `check /etc`, `check /ho` all trigger ABSOLUTE_PATH_REF. Detection chain ordering:
  `_SLASH_RE` runs before `_ABS_PATH_RE`, so bare `/` at start-of-input always hits SLASH_COMMAND
  (by design — can't distinguish `/help` from `/home`). `check /` also stays NATURAL because the
  first component `[\w.\-]+` requires ≥1 char after `/`. Tests in `test_completion_context.py`.
  → `completion_context.py §_ABS_PATH_RE`
- **Response flow** (2026-04-17): diff lexer detection, list hanging indent, trailing blank line.
  → `patterns.md`
- **Animation perf** (2026-04-17): shimmer batching, lerp_color cache, AnimationClock spike
  logging. → `gotchas.md §Shared animation clock`
