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
  version: "3.7"
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
- `hermes_cli/tui/write_file_block.py` with `tests/tui/test_write_file_block.py`
- `hermes_cli/tui/math_renderer.py` with `tests/tui/test_math_renderer.py`; also touches `response_flow.py`, `widgets.py`, `config.py`, `cli.py`
- `hermes_cli/tui/response_flow.py` with `tests/tui/test_response_flow.py`, `tests/tui/test_math_renderer.py`
- `hermes_cli/tui/drawille_overlay.py` with `tests/tui/test_drawille_overlay.py`,
  `tests/tui/test_drawille_toggle.py`, `tests/tui/test_drawille_v2.py`
- `cli.py` TUI bridge code with `tests/cli/test_reasoning_tui_bridge.py` or
  other bridge tests

## Validation

Last revalidated: **2026-04-19. 1669 total TUI tests passing** (9 bake-dependent SDF morph tests skip cleanly via `@requires_pil_bake` — PIL/Python 3.13 FreeType incompatibility).

Recent changes (details → reference files):
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
    `patterns.md §Info overlay pattern`, `gotchas.md §Info overlay escape binding trap`
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
- **ToolPanel v3 A–E + post-E regression fixes** (2026-04-18): Full ToolPanel v3 system —
  ToolAccent, ToolHeaderBar, body_renderers/, content_classifier, InputSection, TurnPhase, ToolPanelMini,
  PerfRegistry, high-contrast, reduced-motion. 4 regression bugs fixed (set_result_summary wire, _panel_managed
  flag, default_collapsed_lines thresholds, _swap_renderer line count stale).
  → `module-map.md §Core modules`, `patterns.md §ToolPanel v3-*`, `gotchas.md §ToolPanel v3-*`
