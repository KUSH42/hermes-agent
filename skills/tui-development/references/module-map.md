# TUI module map

Use this file to find ownership quickly. Read the real module after you find
the owner.

## Architecture overview

```text
HermesApp
├── OutputPanel
│   ├── MessagePanel
│   │   ├── TitledRule
│   │   ├── ReasoningPanel
│   │   ├── GroupHeader               (virtual group header; has ToolAccent)
│   │   ├── ToolPanel                 (v3-A layout: horizontal)
│   │   │   ├── ToolAccent            (width:1 gutter rail; state→color)
│   │   │   └── _PanelContent         (layout: vertical; width:1fr)
│   │   │       ├── ArgsPane          (L3 only)
│   │   │       ├── BodyPane          → ToolBlock/StreamingToolBlock/ExecuteCodeBlock
│   │   │       └── FooterPane        → DiffAffordance (hidden until set_diff())
│   │   ├── prose blocks / CopyableRichLog
│   │   └── StreamingCodeBlock widgets via ResponseFlowEngine
│   ├── ThinkingWidget
│   └── LiveLineWidget
├── CompletionOverlay
│   ├── VirtualCompletionList
│   └── PreviewPanel
├── PathSearchProvider
├── overlay widgets and search/help overlays
├── input/rules/bars
└── StatusBar / VoiceStatusBar / FPSCounter / startup banner
```

High-signal flow:

- agent/background thread:
  `call_from_thread(...)` for scalar state, queue/app helpers for streamed text
- `HermesApp._output_queue`:
  bounded async queue for high-throughput output
- `OutputPanel`:
  owns live streaming area and scroll suppression
- `MessagePanel`:
  owns per-turn render state
- `ResponseFlowEngine`:
  turns committed lines into prose/code widgets

## Core modules

- `hermes_cli/tui/app.py`
  HermesApp composition, reactives, queue consumer, watchers, overlay
  orchestration, theme application, startup TTE hooks, browse mode, hint-phase
  control. Also: `_open_execute_code_block()` factory for ExecuteCodeBlock.
- `hermes_cli/tui/widgets.py`
  Shared widgets, output panel, rules, bars, overlays, countdown mixin,
  startup banner widget, FPS HUD, and many TUI-specific rendering rules.
- `hermes_cli/tui/tool_accent.py`
  `ToolAccent` — 1-cell vertical gutter rail; `state` reactive (pending/streaming/ok/error/warning/muted);
  `set_position(solo|first|mid|last)` for join chars; `render_line` overrides box-drawing chars (┃/├/╰/┬).
  Tests: `tests/tui/test_tool_accent.py`.
- `hermes_cli/tui/diff_affordance.py`
  `DiffAffordance` — ╰→ connector row in FooterPane; hidden until `set_diff(added, removed)` called;
  `clear_diff()` resets. Tests: `tests/tui/test_diff_affordance.py`.
- `hermes_cli/tui/cwd_strip.py`
  `strip_cwd(text)` — extracts and removes `__HERMES_CWD_*__...__HERMES_CWD_*__` tokens; returns
  `(cleaned_text, cwd_or_None)`. `has_cwd_token(text)`. Regex tolerates 8–32 hex chars.
- `hermes_cli/tui/tool_payload.py`
  `ResultKind` enum (TEXT/CODE/DIFF/SEARCH/LOG/JSON/TABLE/BINARY/EMPTY), `ClassificationResult`, `ToolPayload`.
  Phase B stub — full streaming/ANSI pipeline in Phase C.
- `hermes_cli/tui/result_pill.py`
  `ResultPill` (Static) — kind chip in ToolHeaderBar; hidden for TEXT; `set_kind(kind)` transitions
  via add/remove class; `PILL_LABELS` maps ResultKind → display string.
  Tests: `tests/tui/test_result_pill.py`.
- `hermes_cli/tui/tool_header_bar.py`
  `ToolHeaderBar` — horizontal header row; StatusGlyph (PulseMixin, glyphs ▸●✓✗⟳◔),
  LineCountChip (5 chars, `—L` placeholder), DurationChip (live 0.5s timer, freezes at `set_finished`),
  ArgSummary (1fr, Python-truncates via cell_len), ResultPill (hidden for TEXT). Narrow terminal
  adaptation in `on_resize` (< 80 / < 60 / < 40). Fires `ToolHeaderBar.Clicked` on click.
  Tests: `tests/tui/test_tool_header_bar.py`.
- `hermes_cli/tui/content_classifier.py`
  `classify_content(payload)` — full Phase C heuristics: binary/diff/search/json/table/log/code/text.
  LRU cache (32 entries) keyed by (output_raw, tool_name, arg_query). Cache cleared via `classify_content.cache_clear()`.
  Tests: `tests/tui/test_content_classifier.py` (24 tests).
- `hermes_cli/tui/body_renderers/` package (Phase C)
  `base.py`: `BodyRenderer` ABC — `kind`, `supports_streaming`, `build()`, `build_widget()`, `refresh_incremental()`.
  `__init__.py`: `REGISTRY` list (Search→Diff→Json→Table→Code→Log→Shell→Empty→Fallback) + `pick_renderer(cls_result, payload)`.
  Rule: SHELL category → always ShellOutputRenderer (unless EMPTY). Confidence > 0.7 → specialized. Else FallbackRenderer.
  `shell.py`: `ShellOutputRenderer` — supports_streaming=True; strip_cwd after finalize; `refresh_incremental` appends.
  `search.py`: `SearchRenderer` + `VirtualSearchList` (Widget with render_line for >100 hits).
  `diff.py`: `DiffRenderer` — word-diff via SequenceMatcher; auto-collapse >40 lines or >3 hunks.
  `code.py`: `CodeRenderer` — rich.Syntax, lang from extension or fence annotation.
  `log.py`: `LogRenderer` — level coloring, timestamp dim.
  `json.py`: `JsonRenderer` — rich.pretty.Pretty; fallback to text on parse failure.
  `table.py`: `TableRenderer` — pipe/tab delimiter; header detection; numeric right-align.
  `empty.py`: `EmptyStateRenderer` — Static widget with "(no output)" dim text.
  `fallback.py`: `FallbackRenderer` — always-True can_render terminator; CopyableRichLog passthrough.
  Tests: `tests/tui/test_body_renderers_v3.py` (72), `tests/tui/test_renderer_swap.py` (8), `tests/tui/test_virtual_search_list.py` (8).
- `hermes_cli/tui/messages.py`
  `ToolRerunRequested(panel)`, `PathClicked(path, absolute)`. TYPE_CHECKING guards for ToolPanel. Phase D only.
- `hermes_cli/tui/input_section.py`
  `InputSection` — category-gated input summary widget. Shown at L2+. Dispatch table: SHELL→command, FILE→path, SEARCH→query+root, WEB→method+url, CODE→empty. `should_show(category)` classmethod. `refresh_content(args)` updates on arg changes. Tests: `tests/tui/test_input_section.py`.
- `hermes_cli/tui/section_divider.py`
  `SectionDivider` — `╭─ title ─── meta ──╮` / `╰──╯` single-row widget. `render_line` builds fill with title priority (meta truncated first). `set_title()` / `set_meta()` update in-place. Tests: `tests/tui/test_section_divider.py`.
- `hermes_cli/tui/turn_phase.py`
  `AgentThought` (dim border-left), `ToolSequence` (no rail), `AgentFinalResponse` (conditional `.-multiline` rail). Phase D infrastructure; activation gated by `display.tool_panel_v3_turn_phases` (default False). Tests: `tests/tui/test_turn_phase.py`.
- `hermes_cli/tui/tool_panel_mini.py`
  `ToolPanelMini` — 1-row compact SHELL widget; `meets_mini_criteria(cat, exit, lines, stderr)` helper;
  `_expand()` restores originating ToolPanel and removes self; toast shown once via `app._mini_toast_shown`.
  Tests: `tests/tui/test_tool_panel_mini.py`.
- `hermes_cli/tui/tool_blocks.py`
  `ToolBlock`, `StreamingToolBlock`, `ToolHeader` (right-aligned tail, flash_success/flash_error),
  `ToolTail`, `_safe_cell_width`, collapse and browse-mode behavior.
  STB: `_should_strip_cwd` flag (set by ToolPanel for SHELL); `_detected_cwd` stores path;
  `append_line` runs `strip_cwd` when flag set; `complete()` appends dim `cwd: /path` line.
  **v3-B: `ToolHeader` is hidden by `hermes.tcss` rule `ToolPanel ToolHeader { display: none; }`.
  Tests that click `block._header` must now click `panel.query_one(ToolHeaderBar)` instead.**
- `hermes_cli/tui/execute_code_block.py`
  `ExecuteCodeBlock` — execute_code tool UX redesign. Two-section body
  (CodeSection + OutputSection), per-chunk JSON arg streaming via
  PartialJSONCodeExtractor + CharacterPacer, rich.Syntax finalization,
  blinking cursor, success/error flash, always-on click-to-toggle.
  Tests: `tests/tui/test_execute_code_block.py`.
- `hermes_cli/tui/partial_json.py`
  `PartialJSONCodeExtractor` — incremental JSON string field extractor for
  `tool_gen_args_delta` streaming. State machine: seek → after_colon →
  before_open_quote → in_string → unicode_escape → done.
  Tests: `tests/test_partial_json_extractor.py`.
- `hermes_cli/tui/character_pacer.py`
  `CharacterPacer` — optional typewriter pacing at configured cps. cps=0 is
  pass-through. Timer self-stops on empty buffer. flush() drains synchronously.
- `hermes_cli/tui/response_flow.py`
  `ResponseFlowEngine`, prose buffering, inline markdown, code-block routing,
  and `StreamingCodeBlock` lifecycle.
  Also: `_DimRichLogProxy` (wraps CopyableRichLog for dim italic proxy writes)
  and `ReasoningFlowEngine` (ResponseFlowEngine subclass for ReasoningPanel —
  dim italic prose, code blocks inside ReasoningPanel, no _sync_prose_log).

## Input and completion

- `hermes_cli/tui/input_widget.py`
  `HermesInput`, history, submission, masking, trigger dispatch.
- `hermes_cli/tui/completion_context.py`
  Trigger detection for slash, `@`, and path contexts.
- `hermes_cli/tui/path_search.py`
  Threaded path walker and candidate production.
- `hermes_cli/tui/completion_list.py`
  `VirtualCompletionList`, viewport rendering, highlight logic.
- `hermes_cli/tui/completion_overlay.py`
  Overlay container, preview/list layout, visibility lifecycle.
- `hermes_cli/tui/preview_panel.py`
  File preview worker path, syntax highlighting, binary guards.
- `hermes_cli/tui/history_suggester.py`
  Inline ghost-text suggestion path.
- `hermes_cli/tui/fuzzy.py`
  Matching and ranking helpers.

## Theme and animation

- `hermes_cli/tui/hermes.tcss`
  Structural and visual TUI CSS, declared variables, widget selectors.
- `hermes_cli/tui/theme_manager.py`
  Component vars, runtime theme application, hot-reload plumbing.
- `hermes_cli/tui/skin_loader.py`
  Semantic color fan-out from skin files into CSS vars.
- `hermes_cli/tui/animation.py`
  `PulseMixin`, `lerp_color`, `shimmer_text`.
- `hermes_cli/tui/perf.py`
  Perf probes, measurement helpers, FPS data source.
  Phase E: `PerfRegistry` — in-memory named latency store (`record/p50/p95/max/stats/clear`);
  `TOOL_PANEL_V3_COUNTERS` — canonical list of 14 v3 counter names;
  `measure_v3(label, budget_ms, silent)` — like `measure()` but also records into `_registry`.
  Module-level singleton `_registry` used by all v3 call sites (content_classifier, tool_panel).
  Tests: `tests/tui/test_perf_budgets.py` (14 unit + 2 wiring).
- `hermes_cli/tui/tte_runner.py`
  TerminalTextEffects frame generation helpers.
- `hermes_cli/tui/drawille_overlay.py`
  `DrawilleOverlay` (braille-canvas animation, 8 engines, multi-color strand
  rendering), `AnimConfigPanel` (`/anim` slash command inline config UI),
  `DrawilleOverlayCfg`, `AnimParams`, engine protocol + all engine classes.
  Config-gated via `display.drawille_overlay.enabled`. Tests in
  `tests/tui/test_drawille_overlay.py`.

## State and overlays

- `hermes_cli/tui/state.py`
  Typed overlay state dataclasses.
- `hermes_cli/tui/context_menu.py`
  Right-click context menu.
- `hermes_cli/tui/osc52_probe.py`
  Clipboard capability probe before Textual startup.

## CLI bridge points

- `cli.py`
  `_hermes_app`, `_cprint`, reasoning bridge, startup TTE integration, TUI
  setup and teardown.

## Test map

- `tests/tui/test_execute_code_block.py`
  ExecuteCodeBlock lifecycle, streaming, finalization, collapse rules, copy.
- `tests/test_partial_json_extractor.py`
  PartialJSONCodeExtractor: seek/extract, chunked body, escapes, unicode.
- `tests/agent/test_tool_gen_args_delta.py`
  tool_gen_callback idx signature, _fire_tool_gen_args_delta wiring.
- `tests/tui/test_output_panel.py`
  Queue routing, live line, turn eviction.
- `tests/tui/test_tool_blocks.py`
  Static tool blocks, browse mode, integration edges.
- `tests/tui/test_tool_panel.py`
  ToolPanel composition (v3-B: ToolAccent + _PanelContent[ToolHeaderBar, ...]), detail level watcher,
  Args/Footer panes, category classification, D/0-3/Enter keybindings, set_result_summary, copy contract.
- `tests/tui/test_tool_accent.py`
  ToolAccent state reactive, watch_state add/remove_class, position management, integration with ToolPanel.
- `tests/tui/test_diff_affordance.py`
  DiffAffordance hidden/shown state, set_diff/clear_diff, integration in FooterPane.
- `tests/tui/test_result_pill.py`
  ResultPill kind transitions, display hide/show, label updates, TEXT keeps display=False.
- `tests/tui/test_tool_header_bar.py`
  ToolHeaderBar compose children, StatusGlyph states, LineCountChip placeholder/overflow, DurationChip,
  ArgSummary truncation, chevron level sync, click→detail cycle, ToolPanel integration.
- `tests/tui/test_group_semantic_label.py`
  group_semantic_label dedup/count/join/overflow, group_path_hint single/multiple/no-paths.
- `tests/tui/test_tool_panel_mini.py`
  meets_mini_criteria criteria matrix, ToolPanelMini height/focus, auto-mount on qualifying SHELL complete.
- `tests/tui/test_streaming_tool_block.py`
  Streaming block lifecycle, caps, tail badge.
- `tests/tui/test_scroll_integration.py`
  Scroll suppression, live edge, tail dismissal.
- `tests/tui/test_response_flow.py`
  ResponseFlow engine and code-block routing.
- `tests/tui/test_overlays.py`
  Base overlay behavior.
- `tests/tui/test_overlay_design.py`
  Overlay stacking, layout, countdown behavior.
- `tests/tui/test_turn_lifecycle.py`
  Cross-widget turn invariants and cleanup.
- `tests/tui/test_history_search.py`
  History search interaction.
- `tests/tui/test_completion_overlay.py`
  Completion overlay behavior.
- `tests/tui/test_status_widgets.py`
  Hint/status/input placeholder behavior.
- `tests/tui/test_perf_instrumentation.py`
  Perf helpers and FPS HUD.
- `tests/cli/test_reasoning_tui_bridge.py`
  `cli.py` to TUI reasoning bridge.

## Usual read order by task

- output/render bug:
  `app.py` → `widgets.py` → `tool_blocks.py` or `response_flow.py` → focused
  tests
- overlay/input bug:
  `app.py` → `widgets.py` → `state.py` → overlay tests
- completion/preview bug:
  `input_widget.py` → `completion_context.py` → `path_search.py` →
  `completion_overlay.py` / `completion_list.py` / `preview_panel.py`
- theme bug:
  `hermes.tcss` → `theme_manager.py` → `skin_loader.py` → theme tests
