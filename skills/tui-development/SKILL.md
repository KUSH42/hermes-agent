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
compatibility: "Python 3.11+, Textual >=1.0,<9 (pinned), Rich >=15"
metadata:
  author: xush
  version: "4.0"
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
- Slash command intercept (new TUI command):
  `patterns.md` §Info overlay pattern, then `gotchas.md` §Info overlay escape
  binding trap. Wire into `_handle_tui_command`; add `_dismiss_all_info_overlays`
  call; handle escape in `on_key` Priority -2 block.
- Theme or skin bug:
  `patterns.md` CSS theming section + COMPONENT_CLASSES section, then
  `gotchas.md` theme entries.
- Perf hitch or repaint bug:
  `patterns.md` perf triage section, then `gotchas.md` timer/threading entries.

## Files that usually move together

- `hermes_cli/tui/app.py` with `tests/tui/test_integration.py`,
  `tests/tui/test_turn_lifecycle.py`, or a focused module test
- `hermes_cli/tui/overlays.py` with `tests/tui/test_slash_command_overlays.py`
- `hermes_cli/tui/widgets.py` with overlay/status/output tests; InlineThumbnail/InlineImageBar with `tests/tui/test_image_bar.py`
- `hermes_cli/tui/kitty_graphics.py` with `tests/tui/test_kitty_graphics.py`, `tests/tui/test_halfblock_renderer.py`, `tests/tui/test_inline_image.py`, `tests/tui/test_sixel.py`
- `tools/vision_tools.py` with `tests/tools/test_vision_inline.py`
- `hermes_cli/tui/tool_blocks.py` with `tests/tui/test_tool_blocks.py`,
  `tests/tui/test_streaming_tool_block.py`, `tests/tui/test_omission_bar.py`,
  `tests/tui/test_path_context_menu.py`, `tests/tui/test_browse_nav_markers.py`, and scroll tests
- `hermes_cli/tui/execute_code_block.py` with `tests/tui/test_execute_code_block.py`;
  also touches `hermes_cli/tui/partial_json.py`, `hermes_cli/tui/character_pacer.py`,
  `hermes_cli/tui/body_renderer.py`, `cli.py §_on_tool_gen_start/_on_tool_start`,
  `tests/agent/test_tool_gen_args_delta.py`, `tests/test_partial_json_extractor.py`
- `hermes_cli/tui/write_file_block.py` with `tests/tui/test_write_file_block.py`
- `hermes_cli/tui/math_renderer.py` with `tests/tui/test_math_renderer.py`; also touches `response_flow.py`, `widgets.py`, `config.py`, `cli.py`
- `hermes_cli/tui/response_flow.py` with `tests/tui/test_response_flow.py`, `tests/tui/test_math_renderer.py`
- `hermes_cli/tui/drawille_overlay.py` with `tests/tui/test_drawille_overlay.py`,
  `tests/tui/test_drawille_toggle.py`, `tests/tui/test_drawille_v2.py`
- `cli.py` TUI bridge code with `tests/cli/test_reasoning_tui_bridge.py` or
  other bridge tests

## Validation

Last revalidated: **2026-04-20. 2024 total TUI tests passing** (9 bake-dependent SDF morph tests skip cleanly via `@requires_pil_bake` — PIL/Python 3.13 FreeType incompatibility; 1 flaky perf jitter test in `test_streaming_perf.py` occasionally fails under load — pre-existing, not related to recent changes).

Recent changes (details → reference files):
- **Tool Call UX Phase 1** (2026-04-20): 26 tests in `tests/tui/test_ux_phase1.py`. Covers A1+A3+B1+C1+C2+F1 from the UX review spec (`/home/xush/.hermes/tui-tool-call-ux-review-2026-04-20.md`).
  - **A1 — `_error_kind_display(kind, detail, icon_mode)` helper** in `tool_result_parse.py`: `_ERROR_DISPLAY` dict (6 kinds: timeout/exit/signal/auth/network/parse), `_MODE_IDX`, function returns `(icon, label, css_var_name)`. Error CSS vars declared in `hermes.tcss`: `$error-timeout` (amber), `$error-critical` (red), `$error-auth` (yellow), `$error-network` (orange). `ToolHeader.__init__` gains `_error_kind: str | None = None`. `ToolPanel.set_result_summary_v4()` wires `header._error_kind = summary.error_kind`. `_render_v4()` uses `_error_kind` + `_tool_icon_error` to color hero chip. `app.get_css_variables()` returns keys **without `$` prefix**.
  - **A3 — Silent failure fallbacks**: `_render_v4()` None → ASCII header `"[tool] {label}"` + `--header-degraded` class. `BodyPane.__init__` renderer exception → `PlainBodyRenderer()` fallback + `logging.getLogger(__name__).debug(...)` (NOT `None`). `_refresh_tool_icon()` exception → `_CATEGORY_DEFAULTS[spec.category].ascii_fallback or "?"`. Diff path None → `_diff_file_path` stays `None`, header renders without crash.
  - **B1 — Secondary args in microcopy slot**: `_secondary_args_text(category, tool_input) -> str` helper in `tool_blocks.py` (FILE write/read, SHELL env/cwd, SEARCH glob, AGENT task, MCP first 2 args). `ToolBodyContainer` gains `_secondary_text`, `_microcopy_active`, `update_secondary_args()`, `set_microcopy()`, `clear_microcopy()`. **CSS class exclusivity**: `set_microcopy()` removes `--secondary-args` before adding `--active`; `clear_microcopy()` removes `--active`, adds `--secondary-args` back if `_secondary_text` non-empty — they NEVER coexist. TCSS: `ToolBodyContainer .--microcopy.--secondary-args { display: block; color: $text-muted; opacity: 0.6; }`. `StreamingToolBlock.__init__` gains `tool_input: dict | None = None`.
  - **C1 — `action_open_primary()`** on `ToolPanel`: opens `header._full_path` (actual attr — NOT `_label_path`) via `app._open_path_action(header, header._full_path, opener, False)` when `header._path_clickable` (actual attr — NOT `_is_path_clickable`); else falls back to `action_open_first()`. `"open_first"` stays in `_IMPLEMENTED_ACTIONS` (footer chip guard — orthogonal to key binding).
  - **C2 — j/k scroll**: `Binding("j"/"k", "scroll_body_down/up")` on `ToolPanel`. Guard: `not self.collapsed` (reactive, no underscore).
  - **F1 — Accessible mode**: `_accessible_mode() -> bool` on `ToolHeader`: `True` when `HERMES_ACCESSIBLE=1` or `app.console.color_system in (None, "standard")`. Prepends `[>]`/`[+]`/`[!]` to header. State from private attrs: `_spinner_char is not None` → `[>]`; `_tool_icon_error` → `[!]`; `_is_complete` → `[+]`. **Do NOT use CSS classes `--completed`/`--error` — they don't exist on `ToolHeader`.**
  → `hermes_cli/tui/tool_result_parse.py §_ERROR_DISPLAY/_error_kind_display`,
    `hermes_cli/tui/tool_blocks.py §ToolBodyContainer/ToolHeader._accessible_mode/_error_kind/_render_v4/StreamingToolBlock._secondary_args_text/tool_input`,
    `hermes_cli/tui/tool_panel.py §BodyPane.__init__/action_open_primary/action_scroll_body_down/up`,
    `hermes_cli/tui/body_renderer.py §PlainBodyRenderer`,
    `hermes_cli/tui/hermes.tcss §error-* CSS vars/--secondary-args rule`,
    `tests/tui/test_ux_phase1.py` (new, 26 tests)
- **Tool UX Pass 3** (2026-04-20): 11 fixes across P0/P1/P2 categories + ~27 new tests.
  - **§1 MCPBodyRenderer**: New class in `body_renderer.py`; registered for `ToolCategory.MCP`.
    `render_stream_line` = ANSI passthrough. `finalize` extracts `content[].text` from JSON.
    Tests: `tests/tui/test_body_renderer.py` (6 tests, new file).
  - **§2 Footer retry**: `"retry"` added to `_IMPLEMENTED_ACTIONS`. `action_retry()` calls
    `app._initiate_retry()` when `rs.is_error`. `Binding("r","retry")` added. `_build_hint_text()`
    shows "r retry" hint on error results. `_artifact_icon(kind)` helper extracted from inline code
    in `FooterPane` — testable, used by FooterPane too.
  - **§3 `_label_rich` in ToolHeader**: `_render_v4()` now reads `_label_rich` (set by ECB with
    syntax-highlighted label) before falling back to `header_label_v4()`. Truncated via
    `label_text.divide([available])[0]` + `"…"` append.
  - **§4 ANSI preservation**: `StreamingToolBlock` gains `_all_rich: list[Text]`.
    `append_line()` populates both `_all_plain` and `_all_rich`. `rerender_window()`,
    `reveal_lines()`, `collapse_to()` all zip `_all_rich` with `_all_plain` — color preserved on scroll.
  - **§5 ECB top OmissionBar**: `_apply_execute_mount_overrides()` now mounts both bars eagerly
    on `OutputSection` (top bar `before=rl`). Removed lazy bottom-bar mount from `_flush_pending()`.
  - **§6 FILE microcopy denominators**: Removed `total_str`/`total_kb` from FILE template.
    Now `▸ N lines · XkB` (no `?`).
  - **§7 MCP microcopy clear**: Removed `if spec.category == ToolCategory.MCP: return` guard
    from `_clear_microcopy_on_complete()`. All tools clear microcopy on complete.
  - **§8 `[reset]` button**: OmissionBar bottom `"[↑cap]"` → `"\\[reset]"` (backslash-escaped
    to prevent Rich markup `[reset]` tag swallowing the text — renders as `[reset]`).
  - **§9 Dead CSS**: `--flash-complete` rule removed from `hermes.tcss`.
  - **§10 Artifact icons**: `_artifact_icon(kind)` helper in `tool_panel.py` respects
    `get_tool_icon_mode()`: nerdfont/auto → `\uf15b`/`\uf0c1`/`\uf03e`; emoji → 📎/🔗/🖼; ascii → [F]/[L]/[I].
  - **§11 Collapse no-op flash**: `action_collapse_lines()` guards with no-op check + `_flash_header("at minimum")`.
  Key gotcha: **Rich markup in Button labels** — `"[reset]"` is a Rich markup reset tag → renders empty.
  Must escape as `"\\[reset]"`. Same issue would affect any `[word]` label — always escape or use `Text.from_markup`.
  → `hermes_cli/tui/body_renderer.py §MCPBodyRenderer`,
    `hermes_cli/tui/tool_panel.py §_IMPLEMENTED_ACTIONS/_artifact_icon/action_retry/_build_hint_text/action_collapse_lines`,
    `hermes_cli/tui/tool_blocks.py §StreamingToolBlock._all_rich/append_line/rerender_window/reveal_lines/collapse_to/OmissionBar.compose`,
    `hermes_cli/tui/execute_code_block.py §_apply_execute_mount_overrides/_flush_pending`,
    `hermes_cli/tui/streaming_microcopy.py §microcopy_line FILE branch`,
    `hermes_cli/tui/hermes.tcss §--flash-complete removed`,
    `tests/tui/test_body_renderer.py` (new, 6 tests),
    `tests/tui/test_tool_panel.py` (8 new tests),
    `tests/tui/test_tool_blocks.py` (12 new tests),
    `tests/tui/test_omission_bar.py` (1 new test)
- **ExecuteCodeBlock spec review complete** (2026-04-20): 4-pass review loop; spec accuracy 4/10 → 10/10.
  Key implementation facts surfaced and now documented in spec:
  - **`call_from_thread` race**: `_open_execute_code_block` is async; `_gen_blocks_by_idx` is never
    actually populated on the gen_start path (`result[0]` still None when checked). All ECBs are
    created via the tool_start fallback path in practice.
  - **Fallback ECBs lack ToolPanel**: the `_create_ecb_fallback` closure mounts the bare
    `ExecuteCodeBlock` without a `ToolPanel` wrapper — these blocks have no J/K navigation or
    browse anchor registration.
  - **Highlight/finalize path**: ECB does NOT call `StreamingCodeBlock._highlight_line` or
    `_finalize_syntax` — it uses `BodyRenderer.for_category(ToolCategory.CODE).highlight_line()`
    and `BodyRenderer.finalize_code(code, theme, bg)`. `finalize_code` internally slices to
    `lines[1:]` and returns `None` for single-line code (body stays empty for short scripts).
  - **Flash CSS vars**: `$success 35%` and `$error 35%` (not `$addition-marker-fg`/`$deletion-marker-fg`).
  - **`CharacterPacer.__init__`** takes three params: `(cps, on_reveal, app=None)` — `app` required for `set_interval`.
  - **`PartialJSONCodeExtractor`** has 6 states: `seek | after_colon | before_open_quote | in_string | unicode_escape | done`.
    Seek uses `buf.find(needle)` (simple substring, not string-literal-aware).
  - **`ExecuteCodeBody` composes**: `CodeSection + OutputSeparator + OutputSection` (OutputSeparator
    shows dim "─── output" separator; display toggled with OutputSection at tool_start).
  - **`on_mount` deferred override**: ECB uses `call_after_refresh(_apply_execute_mount_overrides)`
    because parent `on_mount` runs after child in Textual MRO, overwriting `_has_affordances = True`.
  - **`#code-live-cursor` Static**: cursor mount wrapped in `try/except` — silently skipped on failure.
  - **`flush()` stops timer**: `CharacterPacer.flush()` already stops drain timer internally; subsequent
    `stop()` call in `finalize_code` is a belt-and-suspenders no-op.
  → `execute-code-block-spec.md` (spec now accurate)
- **ExecuteCodeBlock bug fixes** (2026-04-20): Three cli.py races fixed:
  1. `_on_tool_gen_start` race: closures for `_open_execute` and `_open_write` now
     set `gen_blocks[idx] = b` directly from the event-loop callback (not via a
     `result[0]` closure that's always None when checked on the agent thread).
  2. Fallback ECBs now wrapped in `ToolPanel` (bare mount broke J/K nav + anchors).
  3. Fallback `finalize_code` race: moved inside `_create_ecb_fallback` closure,
     scheduled via `call_after_refresh` so mount completes first.
  Also added test_T48 (other tools label normal color) + test_T49 (right-align
  preserves affordances) to `tests/tui/test_tool_blocks.py`. 42 ECB-related tests pass.
  → `cli.py §_on_tool_gen_start/_create_ecb_fallback`, `tests/tui/test_tool_blocks.py`
- **Tool UX Pass 2 — Phases A–E** (2026-04-20): 5-phase UX upgrade to tool call display.
  **Phase A (footer actions)**: Real `action_copy_body`, `action_open_first`, `action_copy_err`,
  `action_copy_paths` in `FooterPane` with c/o/e/p bindings. `_IMPLEMENTED_ACTIONS` frozenset gates
  render. `_flash_header()` posts flash via `ToolHeader._flash_msg`/`_flash_expires`. `_render_stderr(tail)`
  method (multi-line, height auto; max 4). `_result_paths_for_action()` extracts paths for open/copy.
  Clipboard via `_copy_text_with_hint()` (OSC52 + xclip). `promoted_chip_texts` param in `update_summary_v4`.
  **Phase B (chevron + auto-collapse thresholds)**: Chevron always rendered in `_render_v4()` when
  `_has_affordances`, uses `self._panel.collapsed if self._panel is not None`. Thresholds updated:
  FILE→10, SHELL→8, CODE→5, AGENT→15, UNKNOWN→6.
  **Phase C (microcopy + stderr + chips)**: `_thinking_shimmer(elapsed_s)` returns `Text` (not `str`)
  for AGENT — animated lerp_color wave on `"Thinking…"`. `_last_n_chars_v4(text, n=300)` replaces
  `_last_line_v4` for stderr_tail — preserves newlines, 300 char cap. `_make_copy_err` hotkey "c"→"e".
  `promoted_chip_texts: frozenset[str]` for chip dedup in `set_result_summary_v4`.
  **Phase D (OmissionBar dual-bar redesign)**: Both bars always in DOM from `on_mount()` (guarded by
  `self._body.is_mounted` so `ExecuteCodeBlock` subclass doesn't crash). Display toggled by
  `_refresh_omission_bars()`. Top bar (`--omission-bar-top`): `[↑all](.--ob-up-all)` + `[↑+50](.--ob-up-page)`.
  Bottom bar (`--omission-bar-bottom`): `[↑cap](.--ob-cap)` + `[↑](.--ob-up)` + `[↓](.--ob-down)` +
  `[↓all](.--ob-down-all)`. All button actions route through `block.rerender_window(start, end)` — the
  canonical scroll primitive. `rerender_window` clears log, writes `_all_plain[start:end]`, updates
  `_visible_start`/`_visible_count`, calls `_refresh_omission_bars()`. `set_counts(visible_start,
  visible_end, total)` updates label + disabled states; only called when bar is visible.
  `ToolPanel.action_expand/collapse/expand_all_lines` updated to call `rerender_window` (old `_do_*` gone).
  API: `_omission_bar_bottom`, `_omission_bar_top`, `_omission_bar_bottom_mounted`, `_omission_bar_top_mounted`.
  **Phase E (MCP accent, diff CSS, narrow fix, Gantt scale)**: `ToolPanel.category-mcp` border in
  hermes.tcss. `_diff_bg_colors(self)` widget method reads `app._theme_manager._component_vars`.
  `COMPONENT_VAR_DEFAULTS`: added `tool-mcp-accent`, `diff-add-bg`, `diff-del-bg`. Narrow GroupBody
  `display:none` → `padding-left:0`. `_gantt_scale_text(turn_total_s, gantt_w, label_w)` + `#gantt-scale`
  Static in ToolsOverlay. Tests: `test_omission_bar.py` fully rewritten (25 tests, new API);
  `test_streaming_microcopy.py` AGENT tests check `isinstance(result, Text)`.
  → `hermes_cli/tui/tool_blocks.py`, `hermes_cli/tui/tool_panel.py`, `hermes_cli/tui/tool_category.py`,
    `hermes_cli/tui/tool_result_parse.py`, `hermes_cli/tui/streaming_microcopy.py`,
    `hermes_cli/tui/tools_overlay.py`, `hermes_cli/tui/theme_manager.py`, `hermes_cli/tui/hermes.tcss`,
    `tests/tui/test_omission_bar.py` (rewritten), `tests/tui/test_tool_panel.py`, `tests/tui/test_streaming_microcopy.py`
- **Binary collapse** (2026-04-19): `detail_level: reactive[int]` (L0–L3) **replaced** with
  `collapsed: reactive[bool]` on `ToolPanel`. `ArgsPane` class deleted. `tool_args_format.py` deleted.
  `CategoryDefaults`: removed `args_formatter` + `default_detail` fields. `ToolPanel.BINDINGS`: removed
  `d/D/0/1/2/3`; kept `enter/+/-/*`. `_apply_complete_auto_level` → `_apply_complete_auto_collapse`.
  Architecture invariant: `watch_collapsed` hides `block._body` (ToolBodyContainer), NOT BodyPane —
  BodyPane stays visible so ToolHeader remains clickable. Browse `a`/`A` handler queries `ToolPanel`
  (not ToolBlock) and checks `panel.collapsed`. CSS `ToolPanel ToolBodyContainer { display: block; }`
  in hermes.tcss ensures initial visibility. 1958 tests passing.
  → `hermes_cli/tui/tool_panel.py`, `hermes_cli/tui/app.py §on_key a/A`,
    `tests/tui/test_tool_panel.py`, `tests/tui/test_tool_blocks.py`, `tests/tui/test_p2_gaps.py`,
    `patterns.md §ToolPanel binary collapse`, `gotchas.md §ToolPanel binary collapse gotchas`
- **v4 graduation / P8** (2026-04-19): All v4 feature guards deleted, v2 dead paths removed.
  `_tool_panel_v4_enabled()`, `_tool_panel_v2_enabled()`, `_group_widget_enabled()`,
  `_tool_gutter_enabled()` — all guard functions gone. Config keys `display.tool_panel_v4`,
  `display.tool_panel_v2`, `display.tool_group_widget`, `display.result_hero` stripped.
  `ToolHeader.render()` always calls `_render_v4()`; v2 path gone. Widget grouping always runs.
  Post-graduation UX quick wins: AGENT default_detail 0→1; icon always colored after complete();
  FILE diff collapse threshold 20 lines; uniform microcopy for CODE/AGENT/UNKNOWN;
  FooterPane stderr split row; header-tail chips promotion.
  → `hermes_cli/tui/tool_blocks.py`, `hermes_cli/tui/tool_panel.py`, `hermes_cli/tui/tool_category.py`,
    `hermes_cli/tui/streaming_microcopy.py`, `hermes_cli/tui/tool_result_parse.py`
- **ToolsOverlay /tools timeline** (2026-04-19): `hermes_cli/tui/tools_overlay.py` (NEW) —
  `ToolsScreen(Screen)` first push_screen in this repo. Frozen snapshot at construction.
  `render_tool_row()` pure function. Gantt bar, export JSON, filter input, staleness pip.
  `T` key in browse mode + `/tools` slash command. Turn tracking: `_turn_tool_calls`,
  `_turn_start_monotonic` in HermesApp. `open_streaming_tool_block` assigns `id="tool-{tcid}"`.
  → `hermes_cli/tui/tools_overlay.py` (new), `hermes_cli/tui/app.py §open/close_streaming_tool_block`,
    `patterns.md §ToolsOverlay`, `gotchas.md §ToolsScreen async gotchas`
- **ToolGroup widget** (2026-04-19): `ToolGroup(Widget)` + `GroupHeader` + `GroupBody`.
  `_schedule_group_widget` always runs (CSS-only path deleted). `_group_reparent_worker` with 5-guard
  chain. `recompute_aggregate` N>20 bound. Browse integration: 1 anchor per group.
  → `hermes_cli/tui/tool_group.py`, `hermes_cli/tui/app.py §_schedule_group_widget`,
    `patterns.md §ToolGroup widget`
- **v4 P1–P7** (2026-04-19): ToolSpec/ToolCategory expanded (~70→~520 lines): `spec_for()`,
  `ToolSpec` frozen dataclass, `CategoryDefaults`, `MCPServerInfo`, 20 seed specs, 10 MCP servers.
  `header_label_v4()` + `_format_duration_v4()` in `tool_blocks.py`. `ResultSummaryV4` pipeline
  (`tool_result_parse.py` + category parsers). Streaming microcopy (`streaming_microcopy.py` NEW).
  OmissionBar keyboard bindings in `ToolPanel.BINDINGS` (`+/-/*`). Focused-panel hint row.
  → `hermes_cli/tui/tool_category.py`, `hermes_cli/tui/tool_blocks.py`,
    `hermes_cli/tui/tool_result_parse.py`, `hermes_cli/tui/streaming_microcopy.py` (new),
    `tests/tui/test_tool_spec.py`, `tests/tui/test_tool_header_v4.py`
- **Math formula & chart inline display** (2026-04-19): `hermes_cli/tui/math_renderer.py` (NEW) —
  `MathRenderer.render_unicode()` with 50-entry `_SYMBOL_TABLE` + superscript/subscript/frac/mathbf/mathit
  transforms. `render_block()` via `matplotlib.mathtext` → temp PNG (`transparent=True`; wraps in `$...$`
  if not already). `render_mermaid()` via `mmdc` or `npx @mermaid-js/mermaid-cli` subprocess (15s timeout).
  `ResponseFlowEngine` gains `IN_MATH` state + 7 new fields (`_math_lines`, `_math_env`, `_math_enabled`,
  `_math_renderer_mode`, `_math_dpi`, `_math_max_rows`, `_mermaid_enabled`) read from `panel.app.*` at init.
  Block math regexes (`_BLOCK_MATH_OPEN_RE`, `_BLOCK_MATH_CLOSE_RE`, `_BLOCK_MATH_ONELINE_RE`) checked
  **before** `_FENCE_OPEN_RE` in `process_line()` NORMAL block — `$$` would otherwise collide with fence.
  `_apply_inline_math()`: runs on `raw` line before `apply_block_line`; only substitutes when content
  contains `\`, `^`, or `_` (guards against `$100`, `$HOME`). `_flush_math_block()`: sync unicode path or
  async via `self._panel.app.run_worker(fn, thread=True)` + `call_from_thread`. `flush()` drains open
  `IN_MATH` state as unicode. `MathBlockWidget` in `widgets.py`: label + `InlineImage` child.
  `StreamingCodeBlock._finalize_syntax()` triggers `_try_render_mermaid_async()` for `lang == "mermaid"`;
  `_on_mermaid_rendered()` calls `self.parent.mount(InlineImage(...), after=self)` for sibling mount
  (NOT `self.mount(..., after=self)` — that uses the Textual anchor-resolution gotcha).
  `ReasoningFlowEngine.__init__` gets all 7 math fields with math/mermaid disabled (Non-Goal).
  Config: `display.math/math_renderer/mermaid/math_dpi/math_max_rows` in `config.py`; wired through
  `cli.py` to `HermesApp` plain attrs. 30 new tests in `tests/tui/test_math_renderer.py`.
  Key gotchas: `ResponseFlowEngine` is NOT a Widget — use `self._panel.app.run_worker()` not `@work`.
  `MathRenderer` uses lazy singleton `_get_math_renderer()` (avoids matplotlib import at module load).
  `render_block()` calls `matplotlib.use("Agg")` inside the method — must be before `pyplot` import.
  → `hermes_cli/tui/math_renderer.py` (new), `hermes_cli/tui/response_flow.py §IN_MATH/math fields/
    _apply_inline_math/_flush_math_block/_mount_math_widget/_mount_math_unicode`,
    `hermes_cli/tui/widgets.py §MathBlockWidget/StreamingCodeBlock._finalize_syntax/
    _try_render_mermaid_async/_on_mermaid_rendered`,
    `hermes_cli/tui/hermes.tcss §MathBlockWidget`, `hermes_cli/config.py §display.math*`,
    `cli.py §_math_enabled/_math_renderer/_mermaid_enabled/_math_dpi/_math_max_rows/
    system_prompt math hint (appended in main() after worktree injection, guarded by _math_enabled|_mermaid_enabled)`,
    `tests/tui/test_math_renderer.py` (new, 30 tests)
- **SDF crossfade warmup** (2026-04-19): No more blank overlay while SDF baker runs. `_get_engine()` sdf_morph
  branch now shows a braille warmup engine (`sdf_warmup_engine`, default `"neural_pulse"`) until
  `baker.ready.is_set()`. On ready edge, installs `CrossfadeEngine(warmup→SDF)`. After crossfade completes
  (`progress >= 1.0`), returns pure `SDFMorphEngine`. `hide()` resets all three warmup attrs. PIL-broken
  degradation: warmup runs forever (overlay stays alive). New config fields: `sdf_warmup_engine: str` +
  `sdf_crossfade_speed: float = 0.03` — round-tripped through `_current_panel_cfg` / `_fields_to_dict`.
  Key: `_sdf_crossfade`, `_sdf_warmup_instance`, `_sdf_baker_was_ready` are plain class attrs (not
  reactive). 8 new tests in `TestSDFCrossfadeWarmup` in `tests/tui/test_drawille_v2.py`.
  → `hermes_cli/tui/drawille_overlay.py §_get_engine/_get_sdf_engine/hide/DrawilleOverlayCfg/_overlay_config`,
    `tests/tui/test_drawille_v2.py §TestSDFCrossfadeWarmup`
- **Drawille fps reactive** (2026-04-19): `DrawilleOverlay.fps` reactive now controls actual tick rate.
  `_start_anim()` uses `self.fps` for both paths: `AnimationClock` gets `divisor = max(1, round(15/fps))`;
  `set_interval` fallback uses `1/fps`. `watch_fps()` restarts timer on change. `show()` syncs `self.fps =
  cfg.fps` so YAML/panel changes take immediate effect. `fps: 30` in YAML or AnimConfigPanel now works.
  → `hermes_cli/tui/drawille_overlay.py §_start_anim/watch_fps/show`
- **Browse mode unified anchor navigation** (2026-04-19): `BrowseAnchorType` enum + `BrowseAnchor` dataclass
  added at module level in `app.py`. `HermesApp` gains `_browse_anchors: list[BrowseAnchor]`,
  `_browse_cursor: int`, `_browse_hint: reactive[str]`. New methods: `_rebuild_browse_anchors()` (walks
  `OutputPanel.walk_children`, builds ordered list of TURN_START/CODE_BLOCK/TOOL_BLOCK anchors),
  `_jump_anchor(direction, filter_type)`, `_focus_anchor(idx, anchor, *, _retry=True)`,
  `_clear_browse_highlight()`, `_update_browse_status(anchor)`. New browse keys (before printable
  catch-all): `[`/`]` any anchor, `{`/`}` CODE_BLOCK only, `alt+up`/`alt+down` TURN_START only.
  Browse entry guard relaxed — no longer requires ToolHeaders to exist (enables text-only turn nav).
  `watch_browse_mode(True)`: resets `_browse_cursor=0` then rebuilds. `watch_browse_mode(False)`:
  clears `_browse_hint` + `_clear_browse_highlight()`. `watch_agent_running(False)`: calls
  `_rebuild_browse_anchors()` when `browse_mode` is active.
  `inject_diff()` in `tool_blocks.py`: adds `self._header.add_class("--diff-header")` so diff
  ToolHeaders get "Diff · " label prefix in anchor list.
  `StatusBar.render()`: reads `_browse_hint` reactive; when non-empty, appended after position
  indicator instead of default Tab hint. `_browse_hint` added to StatusBar watch list.
  CSS: `.--browse-focused` (accent), `StreamingCodeBlock.--browse-focused` (success),
  `UserMessagePanel.--browse-focused` (warning) in `hermes.tcss`.
  Key invariants: `StreamingCodeBlock` excluded while `_state == "STREAMING"`. `ToolHeader._label`
  (not `_title`) is the display label. `_browse_cursor` and `browse_index` are SEPARATE — Tab path
  updates only `browse_index`; `[`/`]` path updates only `_browse_cursor`. `_rebuild_browse_anchors`
  always clamps (never resets) cursor — callers that want reset set `_browse_cursor=0` first.
  `_focus_anchor` retry: on unmounted widget, rebuilds once and retries on first same-type anchor
  (lowest index); `_retry=False` prevents recursion. 24 new tests + 1 updated.
  → `hermes_cli/tui/app.py §BrowseAnchorType/BrowseAnchor/_rebuild_browse_anchors/_jump_anchor/
    _focus_anchor/watch_browse_mode/watch_agent_running/on_key`,
    `hermes_cli/tui/tool_blocks.py §inject_diff`,
    `hermes_cli/tui/widgets.py §StatusBar.render`,
    `hermes_cli/tui/hermes.tcss §--browse-focused`,
    `tests/tui/test_browse_nav_markers.py` (new), `tests/tui/test_tool_blocks.py` (guard test updated)
- **Drawille Animations v2** (2026-04-19): 12 new cinematic engines + core systems in `drawille_overlay.py`
  (now 2315 lines). **New engines:** `NeuralPulseEngine`, `FluidFieldEngine`, `LissajousWeaveEngine`,
  `AuroraRibbonEngine`, `MandalaBloomEngine`, `FlockSwarmEngine`, `ConwayLifeEngine`, `RopeBraidEngine`,
  `PerlinFlowEngine`, `HyperspaceEngine`, `WaveFunctionEngine`, `StrangeAttractorEngine`.
  **New systems:** `TrailCanvas` (temporal heat decay), `CompositeEngine` (additive/overlay/xor/dissolve
  blending), `CrossfadeEngine` (smooth engine transitions), adaptive `on_signal` protocol (detected via
  `hasattr` — no Protocol class). **`_ENGINES`** migrated from singleton instances to `dict[str, type]`
  class refs; `DrawilleOverlay._get_engine()` caches instance in `_current_engine_instance`, rebuilds on
  key change. **`AnimParams`** gained 9 new fields (heat, trail_decay, symmetry, particle_count,
  noise_scale, depth_cues, blend_mode, attractor_type, life_seed). **`DrawilleOverlayCfg`** gained 16
  v2 fields + full `_overlay_config()` parsing. **`AnimConfigPanel`** v2: 9 new panel fields, new
  `kind="float"` with step/clamp, `_PanelField.step: float`, `min_val`/`max_val` widened to float.
  **DrawilleOverlay** got 9 new reactive attrs + watchers + `_heat`/`_heat_target` adaptive heat.
  **`app.py`** heat injection: `watch_agent_running(False)` fires `on_signal("complete")`, token
  streaming bumps `_heat_target`, `_on_tool_complete` spikes heat to 1.0. **28 new tests** in
  `tests/tui/test_drawille_v2.py`. Key gotchas: `layer_b` excludes `sdf_morph`; all math via stdlib
  `math` (no numpy/Perlin library); ConwayLife uses set-based alive cells (not 2D array); StrangeAttractor
  computes scale bounds from 200 init ticks.
  → `hermes_cli/tui/drawille_overlay.py`, `hermes_cli/tui/app.py §watch_agent_running/_on_tool_complete`,
    `tests/tui/test_drawille_v2.py`
- **Stream Effects** (2026-04-18): `hermes_cli/stream_effects.py` (NEW) — `StreamEffectRenderer` base +
  `NoneEffect`, `FlashEffect`, `GradientTailEffect`, `GlowSettleEffect`, `DecryptEffect`, `ShimmerEffect`,
  `BreatheEffect`. `make_stream_effect(cfg, lock=None)`, `VALID_EFFECTS`, `_lerp_color` (re-export),
  `_get_accent_hex()` (uses `load_skin(Path)`, NOT `load_skin_vars`). Key: `on_token` does NOT acquire
  `self._lock` — demo caller holds lock before calling. `FlashEffect` + `GlowSettleEffect` both track
  `_buf_len: int = 0` running counter. `DecryptEffect` renders `_words + _current_partial` in `render_tui`;
  ignores `buf` param. GradientTailEffect `frac = (i+1)/max(len(tail),1)` — accent at tail end (newest).
  `LiveLineWidget`: `_stream_effect_name()` + `_stream_effect_cfg()` in `widgets.py`; `_stream_fx` loaded in
  `on_mount`; `_tick_stream_fx` with try/except; `render()` branches on `_stream_fx` with try/except fallback;
  `append()` + `_drain_chars()` call `register_token_tui`; `_commit_lines()` calls `clear_tui()`;
  `flush()` calls `on_turn_end()`. Config at `DEFAULT_CONFIG["terminal"]["stream_effect"]`. 28 new tests.
  → `hermes_cli/stream_effects.py` (new), `hermes_cli/tui/widgets.py §LiveLineWidget`,
    `hermes_cli/config.py §DEFAULT_CONFIG`, `tests/tui/test_stream_effects.py`
- **ResponseFlow chunk streaming** (2026-04-18): `feed(chunk)` added to `ResponseFlowEngine` — accumulates
  `_partial`, routes to `StreamingCodeBlock.feed_partial()` for in-code states (`IN_CODE`, `IN_INDENTED_CODE`,
  `IN_SOURCE_LIKE`). `feed()` NEVER calls `process_line()` (single-clock invariant: only `_commit_lines()` drives
  it). `flush()` drains `_partial` via `pending = self._partial; _clear_partial_preview(); process_line(pending)`.
  `StreamingCodeBlock`: `_partial_display = Static("", classes="--code-partial")` yielded in `compose()`;
  `feed_partial()` highlights fragment + appends `"▌"` cursor; `clear_partial()` hides display; guards at top
  of `append_line()`/`complete()`/`flush()`. `flush_live()` fixed: `engine._partial = live._buf` (NOT
  `engine.process_line(live._buf)`) to prevent double-processing; `engine.flush()` then processes it.
  `app._consume_output()`: inner try/except calls `engine.feed(chunk)` per chunk after `live_line.feed(chunk)`.
  `ReasoningFlowEngine.__init__` also gets `_partial: str = ""` field. 21 new tests.
  → `hermes_cli/tui/response_flow.py §feed/_route_partial/_clear_partial_preview/flush`,
    `hermes_cli/tui/widgets.py §StreamingCodeBlock`, `hermes_cli/tui/app.py §_consume_output`,
    `tests/tui/test_response_flow_chunk.py`
- **WorkspaceOverlay** (2026-04-18): `hermes_cli/tui/workspace_tracker.py` (NEW) —
  `WorkspaceTracker`, `GitPoller`, `GitSnapshot`, `FileEntry`, `analyze_complexity`,
  `WorkspaceUpdated`. `WorkspaceOverlay` added to `overlays.py` with `DEFAULT_CSS`.
  App integration: `_init_workspace_tracker` @work (subprocess off event loop →
  `_set_workspace_tracker` via `call_from_thread`); `_trigger_git_poll` / `_run_git_poll`
  @work; `_analyze_complexity` @work; `_refresh_workspace_overlay` helper;
  `on_workspace_updated` message handler; `action_toggle_workspace`; `w` key guard in
  `on_key` (skips when HermesInput has focus); `/workspace` in `_handle_tui_command`;
  `WorkspaceOverlay` added to `_dismiss_all_info_overlays` + escape Priority -2 block;
  5s background poll via `set_interval` in `watch_agent_running`. `cli.py §_on_tool_complete`:
  `record_write` + `_trigger_git_poll` + `_analyze_complexity` for file-mutating tools.
  Key threading rules: all tracker mutations (record_write, apply_git_status, set_complexity)
  on event loop thread; DOM queries from workers use `call_from_thread` + helper method;
  attributes set from workers use `call_from_thread`. 35 new tests
  (18 tracker unit + 17 overlay pilot). `ComplexityResult` message NOT used — results
  applied via `call_from_thread` directly.
  → `workspace_tracker.py` (new), `overlays.py §WorkspaceOverlay`, `app.py §workspace`,
    `cli.py §_on_tool_complete`, `tests/tui/test_workspace_tracker.py`,
    `tests/tui/test_workspace_overlay.py`
- **Media Extensions E/F/G** (2026-04-18):
  **Phase E (Vision inline):** `tools/vision_tools.py` — `_format_vision_result(result, source_path)` appends
  `\nMEDIA: /path\n` to vision tool success returns when `source_path` is a valid local file. Success path only.
  `source_path = str(local_path) if local_path.is_file() else None`. 8 tests in `tests/tools/test_vision_inline.py`.
  **Phase F (InlineImageBar):** `hermes_cli/tui/widgets.py` — `InlineThumbnail(Widget)` + `InlineImageBar(Widget)`.
  `InlineThumbnail` loads halfblock strips in a `@work(thread=True)` worker; results applied via
  `app.call_from_thread(_apply_strips, strips)`. `InlineImageBar.add_image` no-op when `_enabled=False`.
  `ImageMounted(Message)` defined in `tool_blocks.py`; posted from `StreamingToolBlock._try_mount_media()` after
  mount. `HermesApp.on_image_mounted` → `InlineImageBar.add_image`. `on_inline_image_bar_thumbnail_clicked` →
  `scroll_to_widget`. `display.image_bar: True` in DEFAULT_CONFIG; wired through `cli.py`→`app._inline_image_bar_enabled`.
  NOTE: existing `ImageBar` (id="image-bar") is for user-attached files — `InlineImageBar` (id="inline-image-bar")
  is the new thumbnail strip for model inline images. 13 tests in `tests/tui/test_image_bar.py`.
  **Phase G (Sixel):** `hermes_cli/tui/kitty_graphics.py` — `_sixel_probe()` (DA1 query), `_to_sixel()` (PIL→DCS),
  `_sixel_rle()`. Step 6.5 in `_detect_caps` (after APC, before COLORTERM). `widgets.py InlineImage`: `_sixel_seq`
  attr, `_prepare_sixel`, `_render_sixel_line`, `render_line` SIXEL branch, `watch_image` SIXEL routing.
  `_prepare_sixel` guards `_fit_image` with `if seq and cw > 0 and ch > 0`. 18 tests in `tests/tui/test_sixel.py`.
  Key: `Message` import needed in `widgets.py` for `InlineImageBar.ThumbnailClicked`. `@work(thread=True)` calls
  `_load_strips()` directly in `on_mount` — NOT `self.run_worker(...)`. Sixel thread safety is a follow-up (sync only in Phase G).
  → `tools/vision_tools.py`, `hermes_cli/tui/widgets.py`, `hermes_cli/tui/kitty_graphics.py`,
    `hermes_cli/tui/tool_blocks.py`, `hermes_cli/tui/app.py`, `hermes_cli/config.py`, `cli.py`
- **Footnotes Phase A** (2026-04-18): `[^N]` inline refs → Unicode superscripts; `[^N]: def` lines
  suppressed and collected; end-of-turn footnote section via `_render_footnote_section()`.
  `_FOOTNOTE_REF_RE` + `_SUP_TABLE` + `_to_superscript` in `agent/rich_output.py`; sub runs BEFORE
  `if "\x1b" in line:` guard so heading-embedded refs are also converted. `_FOOTNOTE_DEF_RE` at
  module level in `response_flow.py`; detection as first check inside `if self._state == "NORMAL":`.
  `ReasoningFlowEngine.__init__` mirrors the three attrs; `_render_footnote_section` overridden to
  no-op. `"footnote-ref-color": "#888888"` in `COMPONENT_VAR_DEFAULTS`; `$footnote-ref-color` in
  `hermes.tcss`. `write_with_source` (not bare `write`) for both separator and footnote lines.
  22 new tests in `tests/tui/test_footnotes.py`.
  → `agent/rich_output.py`, `hermes_cli/tui/response_flow.py`, `theme_manager.py`, `hermes.tcss`
- **Kitty TGP inline images — Phase D** (2026-04-18): `display.inline_images: auto|on|off` config — `off` forces
  placeholder regardless of terminal cap. `display.halfblock_dark_threshold` (float, default 0.1) — configurable
  WCAG luminance threshold for halfblock dark-cell detection. Threading for large images: `_prepare_tgp` dispatches
  to `@work(thread=True) _prepare_tgp_async` when `img.width * img.height * 4 > LARGE_IMAGE_BYTES (2_000_000)`;
  result applied via `app.call_from_thread(self._apply_tgp_result, ...)`. `KittyRenderer._alloc_id` protected
  by `threading.Lock`. `_apply_tgp_result` guards `is_mounted` before mutating state. 18 new tests.
  New exports from kitty_graphics: `set_inline_images_mode/get_inline_images_mode`, `set_dark_threshold/get_dark_threshold`,
  `LARGE_IMAGE_BYTES`, `_reset_phase_d`. Wired from cli.py `CliAgent.__init__` alongside other display config.
  → `hermes_cli/tui/kitty_graphics.py §Phase D`, `widgets.py §InlineImage._prepare_tgp/_prepare_tgp_async/_apply_tgp_result`,
    `cli.py §CliAgent.__init__`, `hermes_cli/config.py §DEFAULT_CONFIG.display`, `tests/tui/test_phase_d.py`
- **Kitty TGP inline images — Phases A–C** (2026-04-18): `hermes_cli/tui/kitty_graphics.py` (NEW) —
  `GraphicsCap` enum, `get_caps()/_detect_caps()/_reset_caps()` detection chain, `_cell_px()` ioctl,
  `_chunk_b64()/_build_tgp_sequence()/_fit_image()`, `KittyRenderer/_get_renderer()`, `render_halfblock()`,
  `_load_image()`. `InlineImage` widget added to `widgets.py` (deferred import pattern avoids circular).
  `HermesApp.on_unmount` emits `delete_all_sequence()` as safety net. `StreamingToolBlock._try_mount_media()`
  in `tool_blocks.py` (+ `_extract_image_path` + `_MEDIA_LINE_RE` at module level). Matplotlib auto-capture
  via `_MATPLOTLIB_CAPTURE_SNIPPET` appended to sandboxed script in `code_execution_tool.py`. `pillow` +
  `matplotlib` added to base deps in `pyproject.toml`. 45 new tests across 3 files.
  Key: `InlineImage` uses deferred imports (`from hermes_cli.tui.kitty_graphics import ...` inside methods)
  to avoid circular import at module load. `reactive` attrs require `Widget.__init__` — can't use
  `object.__new__` in tests; use `InlineImage()` directly. `size` property has no setter — use `or 80`
  fallback in render methods. HERMES_GRAPHICS env var overrides detection for CI/testing.
  `body_renderers/` package is EMPTY in live code (v3 spec diverged from implementation) — `ImageRenderer`
  skipped; MEDIA: detection works directly in STB.complete() instead.
  → `hermes_cli/tui/kitty_graphics.py`, `widgets.py §InlineImage`, `tool_blocks.py §_try_mount_media`,
    `app.py §on_unmount`, `tools/code_execution_tool.py §_MATPLOTLIB_CAPTURE_SNIPPET`,
    `tests/tui/test_kitty_graphics.py`, `tests/tui/test_halfblock_renderer.py`, `tests/tui/test_inline_image.py`
- **Slash command TUI integration — Phase 1-3** (2026-04-18): `hermes_cli/tui/overlays.py` (NEW) —
  `HelpOverlay`, `UsageOverlay`, `CommandsOverlay`, `ModelOverlay`. Imported at top of `app.py`.
  `_handle_tui_command` extended for `/help`, `/usage`, `/commands`, `/model`, `/clear`, `/new`,
  `/title`, `/stop`. `_dismiss_all_info_overlays()` method; called before any info overlay open and
  from `watch_agent_running(True)`. Escape at Priority -2 in `on_key`.
  `cli.py`: `/commands` handler; `show_tools()` + `_show_recent_sessions()` → `_cprint`. 28 new tests.
  → `hermes_cli/tui/overlays.py`, `app.py §_handle_tui_command`, `app.py §on_key`,
    `patterns.md §Overlay protocol`, `gotchas.md §Overlay and input behavior`
- **Drawille Animations v2** (2026-04-19): `drawille_overlay.py` extended with 12 new engines + compositing.
  `TrailCanvas` class (heat-map decay, threshold, set/decay_all/to_canvas/frame); `_make_trail_canvas(decay)` factory.
  Helpers: `_braille_density_set(canvas,x,y,intensity)`, `_depth_to_density(z,canvas,x,y)`, `_layer_frames(a,b,mode,heat)`,
  `_easing(t,kind)`. `AnimParams` gains 9 new fields: `heat`, `trail_decay`, `symmetry`, `particle_count`,
  `noise_scale`, `depth_cues`, `blend_mode`, `attractor_type`, `life_seed`. `DrawilleOverlayCfg` gains 16 v2 fields.
  `_ENGINES` is now `dict[str, type]` (class refs) — `_get_engine()` caches instance in `_current_engine_instance`;
  clears on `hide()` and key change; calls `on_mount` hook if present.
  Phase B engines: `NeuralPulseEngine`, `FlockSwarmEngine`, `ConwayLifeEngine`, `StrangeAttractorEngine`,
  `HyperspaceEngine`, `PerlinFlowEngine`. Phase C engines: `FluidFieldEngine`, `LissajousWeaveEngine`,
  `AuroraRibbonEngine`, `MandalaBloomEngine`, `RopeBraidEngine`, `WaveFunctionEngine`.
  Phase D: `CompositeEngine(layers, blend_mode)`, `CrossfadeEngine(engine_a, engine_b, speed)`.
  Adaptive signal protocol: engines optionally declare `on_signal(signal, value)` — detected via `hasattr`.
  `DrawilleOverlay` gains `_heat`, `_heat_target`, `_token_count_last`; heat smoothed in `_tick` at 0.15 rate.
  `_PanelField` gains `step: float`, `min_val`/`max_val` widened to float; new `kind="float"` supported in
  `action_inc_value`, `action_dec_value`, `_cycle`; `_format_field_value` formats float as `f"{v:.2f}"`.
  `AnimConfigPanel._build_fields()` adds 9 v2 fields; `layer_b` excludes `sdf_morph`.
  `_push_to_overlay`, `_current_panel_cfg`, `_fields_to_dict` all extended for v2. HermesApp heat injection
  at `watch_agent_running(False)`, `close_streaming_tool_block`, `mark_response_stream_delta`.
  Gotcha: `_ENGINES` is now class-refs, not instances — iterate as `engine_cls()` in tests.
  28 new tests in `tests/tui/test_drawille_v2.py`. Existing `test_drawille_overlay.py` updated to instantiate engines.
  → `hermes_cli/tui/drawille_overlay.py`, `hermes_cli/tui/app.py §close_streaming_tool_block/mark_response_stream_delta/watch_agent_running`,
    `tests/tui/test_drawille_v2.py`, `tests/tui/test_drawille_overlay.py`
- **Diff merged into patch STB header** (2026-04-18): `inject_diff(diff_lines, header_stats)` on STB;
  `close_streaming_tool_block_with_diff` on app; cli.py `_on_tool_complete` restructured.
  → `tool_blocks.py`, `app.py`, `cli.py §_on_tool_complete`
