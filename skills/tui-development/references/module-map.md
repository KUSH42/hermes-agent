# TUI module map

Use this file to find ownership quickly. Read the real module after you find
the owner.

## Architecture overview

```text
HermesApp
├── OutputPanel
│   ├── MessagePanel (per-turn)
│   │   ├── TitledRule / PlainRule
│   │   ├── ReasoningPanel → ReasoningFlowEngine
│   │   ├── ToolPanel                    (binary collapse container)
│   │   │   ├── BodyPane                 → ToolBlock / StreamingToolBlock / WriteFileBlock / ExecuteCodeBlock
│   │   │   │   └── [block]
│   │   │   │       ├── ToolHeader       (always visible — click-to-toggle)
│   │   │   │       └── ToolBodyContainer (hidden when panel.collapsed=True)
│   │   │   ├── FooterPane               (chips/stderr/actions; shown when result has content)
│   │   │   └── Static .--focus-hint     (hint text when panel focused)
│   │   ├── ToolGroup                    (wraps grouped ToolPanels)
│   │   │   ├── GroupHeader              (aggregate label + collapse toggle)
│   │   │   └── GroupBody
│   │   │       └── ToolPanel …
│   │   ├── StreamingCodeBlock           (fenced code via ResponseFlowEngine)
│   │   ├── MathBlockWidget              (inline math/mermaid render)
│   │   ├── InlineMediaWidget            (audio/video/YouTube inline player)
│   │   ├── InlineProseLog               (prose + inline image compositor)
│   │   └── CopyableRichLog / CopyableBlock (prose blocks)
│   ├── ThinkingWidget                   (animated thinking indicator — always last-1)
│   └── LiveLineWidget                   (streaming token line — always last)
├── StatusBar / VoiceStatusBar / FPSCounter / HintBar / AnimatedCounter
├── DrawilleOverlay / AnimConfigPanel    (braille animation overlay)
├── CompletionOverlay → VirtualCompletionList + PreviewPanel
├── ImageBar                             (user-attached file thumbnails)
├── InlineImageBar                       (model inline image thumbnails)
├── HistorySearchOverlay
├── HelpOverlay / UsageOverlay / CommandsOverlay / ModelOverlay / WorkspaceOverlay
├── KeymapOverlay
├── UndoConfirmOverlay / ClarifyWidget / ApprovalWidget / SudoWidget / SecretWidget
└── StartupBannerWidget / TTEWidget
```

High-signal flow:

- Agent/background thread → `call_from_thread(...)` for scalar state, queue for streamed text
- `HermesApp._output_queue` — bounded async queue for high-throughput output
- `OutputPanel` — owns live streaming area and scroll suppression
- `MessagePanel` — owns per-turn render state + `ResponseFlowEngine`
- `ResponseFlowEngine` — turns committed lines into prose/code/math widgets
- `watch_agent_running(False)` — canonical turn teardown (clears `_active_streaming_blocks`, cleanup)

## Core modules

- **`hermes_cli/tui/app.py`**
  `HermesApp` composition, reactives, queue consumer, watchers, overlay orchestration,
  theme application, startup TTE hooks, browse mode (`BrowseAnchorType`, `_rebuild_browse_anchors`,
  `_jump_anchor`, `[`/`]`/`{`/`}`/`Alt+↑↓` keys), hint-phase control, workspace tracker wiring.
  Key APIs: `open_streaming_tool_block(tool_call_id, label, tool_name)`,
  `append_streaming_line(id, line)`,
  `close_streaming_tool_block(id, duration, is_error, summary)`,
  `close_streaming_tool_block_with_diff(id, duration, diff_lines, plain_lines, stats, is_error, summary)`,
  `mount_tool_block(label, lines, plain_lines, tool_name, rerender_fn, header_stats)`,
  `write_output(chunk)`.
  Browse mode `a`/`A` keys query **ToolPanel** (not ToolBlock) — check `panel.collapsed`.

- **`hermes_cli/tui/widgets.py`**
  All shared widgets, output panel, rules, bars, overlays, CountdownMixin, startup banner,
  FPS HUD. Key classes: `CopyableRichLog`, `InlineProseLog`, `LiveLineWidget`, `MessagePanel`,
  `StreamingCodeBlock`, `ThinkingWidget`, `OutputPanel`, `UserMessagePanel`, `ReasoningPanel`,
  `TitledRule`, `PlainRule`, `HintBar`, `StatusBar`, `AnimatedCounter`, `VoiceStatusBar`,
  `ImageBar`, `ClarifyWidget`, `ApprovalWidget`, `SudoWidget`, `SecretWidget`,
  `UndoConfirmOverlay`, `TurnCandidate`, `TurnResultItem`, `KeymapOverlay`, `HistorySearchOverlay`,
  `FPSCounter`, `TTEWidget`, `InlineImage`, `MathBlockWidget`, `InlineThumbnail`, `InlineImageBar`,
  `StartupBannerWidget`, `SeekBar`, `InlineMediaWidget`.

- **`hermes_cli/tui/tool_blocks.py`**
  `ToolHeader`, `ToolBodyContainer`, `ToolBlock`, `OmissionBar`, `ToolTail`, `StreamingToolBlock`.
  Also: `ImageMounted(Message)`, `ToolHeaderStats`, collapse constants (`COLLAPSE_THRESHOLD=3`,
  `_VISIBLE_CAP`, `_LINE_BYTE_CAP`), `header_label_v4()`, `_format_duration_v4()`.
  STB: `_try_mount_media()`, `inject_diff()`, `append_line()`, `complete()`, OmissionBar lifecycle.
  ToolHeader: `collapsed: reactive[bool] = reactive(True)` — starts collapsed by default;
  `_has_affordances`, `_spinner_char`, `_duration`, `_primary_hero`, `_header_chips`,
  `_label_rich`, `_panel` (back-ref to ToolPanel), `flash_copy()`.
  **ToolHeader is inside BodyPane inside ToolPanel — always visible even when panel.collapsed=True.**
  ToolBlock.toggle(): when `header._panel` is set, delegates to `panel.action_toggle_collapse()`.

- **`hermes_cli/tui/tool_panel.py`**
  `ToolPanel(Widget)` — binary collapse container for all tool calls.
  `BodyPane` — hosts the tool block; always visible (BodyPane never hidden).
  `FooterPane` — exit-code chip, stderr tail, action hints; shown when result has content.
  Key reactive: `collapsed: reactive[bool] = reactive(False, layout=True)`.
  `watch_collapsed`: hides `block._body` (ToolBodyContainer), NOT BodyPane.
  `set_result_summary_v4(summary)` — wires result → header chips + footer + auto-collapse.
  `_apply_complete_auto_collapse()` — collapses when body > threshold; errors force expand.
  `action_toggle_collapse()` — sets `_user_collapse_override=True`, flips collapsed.
  BINDINGS: `enter` (toggle), `+/-/*` (OmissionBar lines).
  ToolPanel.Completed posted after `set_result_summary_v4`.

- **`hermes_cli/tui/tool_category.py`**
  `ToolCategory` enum: `FILE / SHELL / CODE / SEARCH / WEB / AGENT / MCP / UNKNOWN`.
  `ToolSpec` — frozen dataclass: name, category, primary_arg, primary_result, streaming,
  emit_heartbeat, render_header, terminal_inline, icon_nf, provenance.
  `CategoryDefaults` — frozen dataclass: `accent_var, glyph_var, ascii_fallback, result_parser,
  default_collapsed_lines, icon_nf`. (No `args_formatter` or `default_detail` — deleted.)
  `spec_for(name, args, schema)` — canonical lookup: registry → MCP unwrap → arg heuristic → schema → UNKNOWN.
  `classify_tool(name)` — shim → `spec_for(name).category`.
  `MCPServerInfo`, `register_tool()`, `register_mcp_server()`, `TOOL_REGISTRY`, `MCP_SERVER_REGISTRY`.
  Valid `primary_result` values: `bytes/diff/done/lines/matches/none/results/status` (not `"text"`).

- **`hermes_cli/tui/tool_group.py`**
  `ToolGroup(Widget)` — groups related ToolPanels with `collapsed: reactive[bool]`.
  `GroupHeader` — single-line toggle + aggregate chips.
  `GroupBody` — indented container for ToolPanel children (padding-left 2).
  `ToolGroup.--collapsed GroupBody { display: none; }` in DEFAULT_CSS.
  `on_tool_panel_completed` — stops event, calls `recompute_aggregate()`.
  CSS grouping path (Rule 1-4 class-only): `_schedule_group_widget` / `_group_reparent_worker` in app.py.
  `group_semantic_label(members)`, `group_path_hint(members)` in tool_group.py.

- **`hermes_cli/tui/tool_result_parse.py`**
  `ResultSummaryV4` — frozen dataclass: primary, exit_code, chips, stderr_tail, actions, artifacts, is_error, error_kind.
  `ParseContext(complete: ToolComplete, start: ToolStart, spec: ToolSpec)` — input to `parse()`.
  `parse(ctx) -> ResultSummaryV4` — dispatches by `ctx.spec.category.value` to category parsers.
  `Chip(text, tone)`, `Action(hotkey, label, payload)`, `Artifact(kind, label, path)`.
  `_raw_str(raw)` — always use before string ops on `ToolComplete.raw_result` (may be str|dict).
  Payload cap: `_PAYLOAD_CAP = 65536`. `_truncate_payload(text) -> (text, truncated: bool)`.

- **`hermes_cli/tui/streaming_microcopy.py`**
  `StreamingState` dataclass, `microcopy_line(spec, state) -> str`.
  Category routing: SHELL→ `▸ N lines · NkB`, FILE read→ `▸ N lines · NkB`, FILE write→ `▸ writing…`,
  SEARCH→ `▸ N matches`, WEB→ `▸ fetching…`, MCP→ `▸ mcp · {server} server` (persists after complete),
  CODE→ `▸ N lines · NkB`, AGENT→ `▸ thinking…`, UNKNOWN→ `▸ N lines`.

- **`hermes_cli/tui/body_renderer.py`**
  `BodyRenderer` ABC — `kind`, `supports_streaming`, `build()`, `build_widget()`, `refresh_incremental()`.
  Subclasses: `ShellRenderer`, `CodeRenderer`, `FileRenderer`, `SearchRenderer`, `WebRenderer`,
  `AgentRenderer`, `TextRenderer`. `BodyRenderer.for_category(category)` factory.
  `FileRenderer.render_diff_line(plain)` — styled Rich Text for diff lines.
  NOTE: this is `body_renderer.py` (singular) — the `body_renderers/` package was never shipped.

- **`hermes_cli/tui/response_flow.py`**
  `ResponseFlowEngine` — prose buffering, inline markdown, code-block routing, math routing.
  States: NORMAL / IN_CODE / IN_INDENTED_CODE / IN_SOURCE_LIKE / IN_MATH.
  `feed(chunk)` — accumulates partial, routes to `StreamingCodeBlock.feed_partial()` in code states.
  `process_line(raw)` — single-clock driver; never called from `feed()`.
  `flush()` — drains `_partial` then processes it; drains open IN_MATH as unicode.
  Block math regexes checked before `_FENCE_OPEN_RE` (prevents `$$` colliding with fence).
  `_apply_inline_math(raw)` — substitutes inline math when `\`, `^`, or `_` in content.
  `_DimRichLogProxy` — wraps CopyableRichLog for dim italic proxy writes (ReasoningPanel).
  `ReasoningFlowEngine` — subclass for ReasoningPanel; overrides `process_line` to flush
  `StreamingBlockBuffer` immediately (eliminates one-line lookahead lag).
  **ResponseFlowEngine is NOT a Widget.** Use `self._panel.app.run_worker(fn, thread=True)`, not `@work`.

- **`hermes_cli/tui/execute_code_block.py`**
  `ExecuteCodeBlock(StreamingToolBlock)` — two-section body (CodeSection + OutputSection).
  Lifecycle: GEN_START → `feed_delta()` → TOOL_START → `finalize_code()` → EXEC_STREAMING → `complete()`.
  `CharacterPacer` typewriter pacing; `PartialJSONCodeExtractor` for streaming arg decode.
  `finalize_code()` replaces per-line with `rich.Syntax`; line 0 shown in header (body starts line 1).

- **`hermes_cli/tui/write_file_block.py`**
  `WriteFileBlock(StreamingToolBlock)` — specialization for file-write tools with path display.

- **`hermes_cli/tui/math_renderer.py`**
  `MathRenderer` — `render_unicode()` (50-entry symbol table + superscripts/subscripts),
  `render_block()` (matplotlib → PNG), `render_mermaid()` (mmdc subprocess, 15s timeout).
  Lazy singleton via `_get_math_renderer()` — avoids matplotlib import at module load.
  `render_block()` calls `matplotlib.use("Agg")` inside — must be before pyplot import.

- **`hermes_cli/tui/media_player.py`**
  `InlineMediaCfg`, `MpvController` (subprocess + UNIX IPC socket, retry up to 1s),
  `MpvPoller` (daemon thread at 4Hz), `_fetch_youtube_thumbnail()`, `_extract_video_thumbnail()`.
  Detection regexes: `_AUDIO_EXT_RE`, `_VIDEO_EXT_RE`, `_YOUTUBE_RE`.
  `InlineMediaWidget._prepare()` is `@work(thread=True)` — resolves URL, creates MpvController,
  fetches thumbnails, then `call_from_thread(_on_ready, ...)`.

## Input and completion

- **`hermes_cli/tui/input_widget.py`**
  `HermesInput(TextArea)` — history, submission, masking, trigger dispatch, file-drop handling.
  Key: `_on_key` (async), `on_text_area_changed` replaces watch_value/watch_cursor_position,
  ghost text via `self.suggestion`, `_push_undo_snapshot()` removed (TextArea manages undo).
- **`hermes_cli/tui/completion_context.py`** — trigger detection for slash, `@`, path contexts.
- **`hermes_cli/tui/path_search.py`** — threaded path walker and candidate production.
- **`hermes_cli/tui/completion_list.py`** — `VirtualCompletionList`, viewport rendering, highlight.
- **`hermes_cli/tui/completion_overlay.py`** — overlay container, preview/list layout, visibility lifecycle.
- **`hermes_cli/tui/preview_panel.py`** — file preview worker path, syntax highlighting, binary guards.
- **`hermes_cli/tui/history_suggester.py`** — inline ghost-text suggestion path.
- **`hermes_cli/tui/fuzzy.py`** — matching and ranking helpers.
- **`hermes_cli/tui/partial_json.py`** — `PartialJSONCodeExtractor` — incremental JSON string field extractor.
- **`hermes_cli/tui/character_pacer.py`** — `CharacterPacer` — optional typewriter pacing at configured cps.

## Inline media and images

- **`hermes_cli/tui/kitty_graphics.py`**
  `GraphicsCap` enum, `get_caps()/_detect_caps()` detection chain, `_cell_px()` ioctl,
  `_chunk_b64()/_build_tgp_sequence()/_fit_image()`, `KittyRenderer/_get_renderer()`,
  `render_halfblock()`, `_load_image()`, `_sixel_probe()`, `_to_sixel()`.
  `display.inline_images: auto|on|off` — `off` forces placeholder. Threading for large images:
  `_prepare_tgp` dispatches to `@work(thread=True)` when `w*h*4 > LARGE_IMAGE_BYTES (2_000_000)`.
- **`hermes_cli/tui/inline_prose.py`**
  `InlineImageCache`, `InlineProseLog` — prose + inline image compositor widget.

## Theme and animation

- **`hermes_cli/tui/hermes.tcss`** — structural + visual CSS, declared variables, widget selectors.
- **`hermes_cli/tui/theme_manager.py`** — component vars, runtime theme application, hot-reload.
- **`hermes_cli/tui/skin_loader.py`** — semantic color fan-out from skin files into CSS vars.
- **`hermes_cli/tui/animation.py`** — `PulseMixin`, `lerp_color`, `shimmer_text`, `AnimationClock`.
- **`hermes_cli/tui/perf.py`** — `PerfRegistry` singleton, `measure_v3()`, `TOOL_PANEL_V3_COUNTERS`,
  `WorkerWatcher`, `EventLoopProbe`.
- **`hermes_cli/tui/drawille_overlay.py`** (~2300 lines)
  `DrawilleOverlay` (braille-canvas loading animation, 20 engines), `AnimConfigPanel` (`/anim` config UI),
  `DrawilleOverlayCfg`, `AnimParams`, `TrailCanvas`, `CompositeEngine`, `CrossfadeEngine`.
  Engines: `NeuralPulseEngine`, `FluidFieldEngine`, `LissajousWeaveEngine`, `AuroraRibbonEngine`,
  `MandalaBloomEngine`, `FlockSwarmEngine`, `ConwayLifeEngine`, `RopeBraidEngine`, `PerlinFlowEngine`,
  `HyperspaceEngine`, `WaveFunctionEngine`, `StrangeAttractorEngine`, `SDFMorphEngine`, plus 8 originals.
  `_ENGINES` is `dict[str, type]` (class refs, not instances). `_get_engine()` caches in `_current_engine_instance`.
  Adaptive `on_signal` protocol — detected via `hasattr` (no Protocol class).
- **`hermes_cli/tui/tte_runner.py`** — TerminalTextEffects frame generation helpers.
- **`hermes_cli/tui/sdf_morph.py`** / **`hermes_cli/tui/sdf_splash.py`** — SDF baking and splash.
- **`hermes_cli/stream_effects.py`** — `StreamEffectRenderer` base + 7 effect classes.
  `make_stream_effect(cfg, lock=None)`, `VALID_EFFECTS`. `LiveLineWidget` wired in `widgets.py`.

## Overlays and state

- **`hermes_cli/tui/overlays.py`**
  `HelpOverlay`, `UsageOverlay`, `CommandsOverlay`, `ModelOverlay`, `WorkspaceOverlay`.
  Info overlays: dismissed by `_dismiss_all_info_overlays()` (called before opening, from `watch_agent_running(True)`).
  Escape at Priority -2 in `on_key`.
- **`hermes_cli/tui/tools_overlay.py`**
  `ToolsScreen(Screen)` — full-screen timeline. Snapshot frozen at construction.
  First `push_screen` in repo — `pop_screen()` to dismiss; `_dismiss_all_info_overlays()` does NOT affect it.
- **`hermes_cli/tui/workspace_tracker.py`**
  `WorkspaceTracker`, `GitPoller`, `GitSnapshot`, `FileEntry`, `WorkspaceUpdated(Message)`.
  All tracker mutations on event-loop thread only. Workers use `call_from_thread`.
- **`hermes_cli/tui/state.py`** — typed overlay state dataclasses: `ChoiceOverlayState`, `SecretOverlayState`, `UndoOverlayState`.
- **`hermes_cli/tui/context_menu.py`** — right-click context menu + `ContextMenu._prev_focus` focus restore.
- **`hermes_cli/tui/osc52_probe.py`** — clipboard capability probe before Textual startup.

## CLI bridge

- **`cli.py`**
  `_hermes_app`, `_cprint`, reasoning bridge, startup TTE integration.
  `_on_tool_complete`: builds `ParseContext`, calls `parse()`, passes `_summary` to `close_streaming_tool_block`.
  `close_streaming_tool_block` signature: `(tool_call_id, duration, is_error=False, summary=None)`.

## Test map

| Test file | Covers |
|-----------|--------|
| `test_tool_blocks.py` | ToolBlock, STB, ToolHeader, browse mode, OmissionBar, toggle/click |
| `test_streaming_tool_block.py` | STB lifecycle, byte cap, visible cap, complete(), ToolTail |
| `test_tool_output_integration.py` | open/append/close API, concurrent blocks, interrupt |
| `test_tool_panel.py` | ToolPanel binary collapse, auto-collapse, error promotion, result v4, hint row |
| `test_tool_blocks.py` | browse a/A/enter/c keys, click toggle, context menu |
| `test_result_summary_v2.py` | ResultSummaryV4 wiring, parse(), error promote |
| `test_tool_spec.py` | ToolSpec/CategoryDefaults, classify_tool, spec_for, MCP registry |
| `test_tool_group.py` / `test_tool_group_widget.py` | ToolGroup DOM, collapse, reparent, aggregate |
| `test_streaming_microcopy.py` | microcopy_line per category |
| `test_body_renderers.py` | BodyRenderer.for_category, render_diff_line |
| `test_tool_result_parse.py` | parse(), ResultSummaryV4, ParseContext |
| `test_tool_header_v4.py` | header_label_v4, _format_duration_v4, _render_v4 |
| `test_response_flow.py` | ResponseFlowEngine states, code routing, math |
| `test_math_renderer.py` | MathRenderer unicode/block/mermaid |
| `test_inline_media.py` | InlineMediaWidget, detection, mpv IPC |
| `test_stream_effects.py` | StreamEffectRenderer effects, LiveLineWidget wiring |
| `test_browse_nav_markers.py` | BrowseAnchorType, [/]/{ }/Alt+↑↓ keys |
| `test_execute_code_block.py` | ExecuteCodeBlock lifecycle, streaming, finalization |
| `test_write_file_block.py` | WriteFileBlock |
| `test_turn_lifecycle.py` | cross-widget turn invariants and cleanup |
| `test_integration.py` | app-level integration |
| `test_overlays.py` / `test_overlay_design.py` | overlay stacking, layout, countdown |
| `test_scroll_integration.py` | scroll suppression, live edge, ToolTail |
| `test_history_search.py` | HistorySearchOverlay |
| `test_completion_overlay.py` / `test_completion_p0.py` | completion overlay behavior |
| `test_kitty_graphics.py` / `test_halfblock_renderer.py` / `test_inline_image.py` / `test_sixel.py` | inline image pipeline |
| `test_image_bar.py` | InlineThumbnail, InlineImageBar |
| `test_drawille_overlay.py` / `test_drawille_v2.py` | DrawilleOverlay, engines, compositing |
| `test_hermes_input.py` | HermesInput TextArea, file drop, ghost text |
| `test_p2_gaps.py` | resize, overlay simultaneity, browse+context |
| `test_tools_overlay.py` | ToolsScreen timeline, render_tool_row |
| `test_workspace_tracker.py` / `test_workspace_overlay.py` | workspace tracker + overlay |
| `test_omission_bar.py` | OmissionBar expand/collapse/+/-/* keys |
| `test_footnotes.py` | footnote ref conversion, section render |
| `test_status_widgets.py` | HintBar, StatusBar, browse hint, AnimatedCounter |
| `test_theme_manager.py` / `test_theme.py` | ThemeManager, skin loading |
| `test_perf_instrumentation.py` | PerfRegistry, measure_v3 |
| `test_drawille_toggle.py` | DrawilleOverlay show/hide lifecycle |
| `test_reasoning_panel.py` | ReasoningFlowEngine, ReasoningPanel |
| `tests/cli/test_reasoning_tui_bridge.py` | cli.py → TUI reasoning bridge |

## Files that move together

- `tool_panel.py` + `tool_blocks.py` + `tool_category.py` — binary collapse, category, header
- `tool_blocks.py` + `test_tool_blocks.py` + `test_streaming_tool_block.py` + `test_omission_bar.py` + `test_path_context_menu.py` + `test_browse_nav_markers.py`
- `tool_group.py` + `test_tool_group.py` + `test_tool_group_widget.py`
- `tool_result_parse.py` + `test_tool_result_parse.py` + `test_result_summary_v2.py`
- `response_flow.py` + `test_response_flow.py` + `test_math_renderer.py` + `test_response_flow_chunk.py`
- `widgets.py` + overlay/status/output tests + `test_image_bar.py`
- `kitty_graphics.py` + `test_kitty_graphics.py` + `test_halfblock_renderer.py` + `test_inline_image.py` + `test_sixel.py`
- `media_player.py` + `widgets.py §SeekBar,InlineMediaWidget` + `test_inline_media.py`
- `drawille_overlay.py` + `test_drawille_overlay.py` + `test_drawille_v2.py` + `test_drawille_toggle.py`
- `overlays.py` + `test_slash_command_overlays.py`
- `app.py` + `test_turn_lifecycle.py` + `test_integration.py` + focused module test
- `cli.py` + `tests/cli/test_reasoning_tui_bridge.py`
- `stream_effects.py` + `widgets.py §LiveLineWidget` + `test_stream_effects.py`
- `write_file_block.py` + `test_write_file_block.py`
- `math_renderer.py` + `response_flow.py` + `widgets.py` + `config.py` + `cli.py` + `test_math_renderer.py`

## Usual read order by task

- **Output/render bug:** `app.py` → `widgets.py` → `tool_blocks.py` or `response_flow.py` → tests
- **ToolPanel/collapse bug:** `tool_panel.py` → `tool_blocks.py` → `test_tool_panel.py`
- **ToolCategory/spec bug:** `tool_category.py` → `streaming_microcopy.py` → `body_renderer.py` → `test_tool_spec.py`
- **Browse mode bug:** `app.py §browse` → `tool_blocks.py §inject_diff` → `test_browse_nav_markers.py` → `test_tool_blocks.py`
- **Overlay/input bug:** `app.py` → `widgets.py` → `state.py` → overlay tests
- **Completion/preview bug:** `input_widget.py` → `completion_context.py` → `path_search.py` → completion tests
- **Theme bug:** `hermes.tcss` → `theme_manager.py` → `skin_loader.py` → theme tests
- **Animation bug:** `drawille_overlay.py` → `animation.py` → drawille tests
- **Inline image/media bug:** `kitty_graphics.py` → `widgets.py §InlineImage` → `media_player.py` → inline tests
