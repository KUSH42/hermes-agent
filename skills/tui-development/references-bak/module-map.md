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
│   │   ├── ToolBlock / StreamingToolBlock
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
  control.
- `hermes_cli/tui/widgets.py`
  Shared widgets, output panel, rules, bars, overlays, countdown mixin,
  startup banner widget, FPS HUD, and many TUI-specific rendering rules.
- `hermes_cli/tui/tool_blocks.py`
  `ToolBlock`, `StreamingToolBlock`, `ToolHeader`, `ToolTail`, collapse and
  browse-mode behavior.
- `hermes_cli/tui/response_flow.py`
  `ResponseFlowEngine`, prose buffering, inline markdown, code-block routing,
  and `StreamingCodeBlock` lifecycle.

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
- `hermes_cli/tui/tte_runner.py`
  TerminalTextEffects frame generation helpers.

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

- `tests/tui/test_output_panel.py`
  Queue routing, live line, turn eviction.
- `tests/tui/test_tool_blocks.py`
  Static tool blocks, browse mode, integration edges.
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
