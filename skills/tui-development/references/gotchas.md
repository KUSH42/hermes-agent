# TUI gotchas

High-value pitfalls worth checking before editing tricky TUI code.

## TGP / Kitty Graphics stdout redirect

- **`sys.stdout` is `_PrintCapture` inside Textual's event loop.** `App._process_messages()` wraps execution in `redirect_stdout(_PrintCapture)`, which routes `write()` to `app._print()` (internal log) and returns `-1` from `fileno()`. Any code that writes APC/TGP Kitty sequences to `sys.stdout` inside the event loop silently swallows them — Kitty never receives the image data, and placeholder chars render as blank.
- **Fix: use `sys.__stdout__`** for TGP sequence output. `sys.__stdout__` is the original fd-backed stream, unaffected by `redirect_stdout`. Guard with `out = sys.__stdout__ if sys.__stdout__ is not None else sys.stdout` for frozen-interpreter safety.
- **Affected sites**: `inline_prose.py §InlineImageCache._render()` (TGP upload), `widgets.py §InlineImage._emit_raw()` (TGP upload + delete-on-unmount). Both fixed 2026-04-21.
- **`get_strips_or_alt()` is the safe render-path variant** — never calls `_render()`, returns alt strips on cache miss. `get_strips()` may call `_render()` and must only be called from pre-render steps (off the render phase).
- **Symptom**: custom emojis (`:name:`) show as ASCII alt-text or blank in Kitty even though TGP is detected and placeholder strips are returned by the cache. The image was never uploaded.

## Input history pollution — three bugs in `_load_history` / `_save_to_history`

Three separate bugs cause "unrelated trash" at the top of up-arrow history (fixed 2026-04-21):

1. **Slash commands saved to history**: `/clear`, `/anim`, `/model`, etc. are UI control commands, not prompts. `_save_to_history` now early-returns when `text.lstrip().startswith("/")`.
2. **No file-level dedup**: In-memory dedup (`list.remove`) never touched the file, so typing the same slash command 4× results in 4 entries in the file. On the next TUI start all 4 reload. Fix: `_load_history` deduplicates the loaded slice (last occurrence wins, order preserved).
3. **CLI/TUI entry merge**: `prompt_toolkit`'s `FileHistory` writes `\n# timestamp\n+cmd\n` — no trailing blank after the last entry. When the TUI appended `+tui_cmd\n\n` directly after, the parser merged them into one multiline entry (`"cli_cmd\ntui_cmd"`). Fix: `_save_to_history` writes a leading `\n` before the `+` lines.

Key invariant: `_save_to_history` writes `\n+line\n…\n` (leading blank + trailing blank). The TUI never writes `# timestamp` lines — `prompt_toolkit` comments in the file are parsed but ignored.

## `_normalize_ansi_for_render` — multi-param CSI orphan stripping

- **`(?<!\x1b)` is insufficient** as the orphan-fragment lookbehind in `_normalize_ansi_for_render`. A multi-param CSI sequence like `\x1b[1;37m` has `;37m` preceded by `1` (not `\x1b`), so the old pattern incorrectly stripped it, leaving `\x1b[1`. Rich's ANSI parser then reads `\x1b[1M` as CSI "scroll up" and silently consumes the content character `M`. Every level-1/2 heading (style = bold+white `\x1b[1;37m` or bold+bright-white `\x1b[1;97m`) lost its first letter.
- **Fix**: use `(?<![\x1b0-9;])` — skip stripping if the `;` or `[` is preceded by ESC, a digit, or a semicolon; those are all valid inside a CSI parameter list.
- **Does NOT affect `_strip_ansi`**: `_strip_ansi` first strips all complete `\x1b[..letter]` sequences with `_ANSI_RE`, so the `_ORPHAN_RE` only runs on plain text where digits would never precede a `;`. The fix is only needed in `_normalize_ansi_for_render` which preserves the full ANSI.
- **Symptom**: heading lines lose their first letter in TUI output. `## Markdown Features Showcase` renders as `arkdown Features Showcase`. The bug is invisible without emoji (path goes through `write_with_source`, which re-parses the malformed ANSI) but present in every heading turn.
- **Affected site**: `hermes_cli/tui/response_flow.py §_normalize_ansi_for_render` (fixed 2026-04-21).

## `call_from_thread` must not be called from the app thread

- **`call_from_thread` raises `RuntimeError` when called from the app's own event-loop thread.** Textual checks `self._thread_id == threading.get_ident()` and raises `"The call_from_thread method must run in a different thread from the app"`.
- **Trigger**: any async worker with `thread=False` (the default) that calls a helper that uses `call_from_thread`. `_handle_clear_tui` triggered this via `cli._push_tui_status()`.
- **Fix pattern**: detect the thread context and use direct reactive assignment when already on the app thread:
  ```python
  import threading as _threading
  def _apply() -> None:
      tui.some_reactive = value
  if _threading.get_ident() == tui._thread_id:
      _apply()
  else:
      tui.call_from_thread(_apply)
  ```
- **Applies to**: any method in `cli.py` that calls `tui.call_from_thread(...)` and may be invoked from both background threads AND async workers. `_push_tui_status()` is the canonical example (fixed 2026-04-21).

## Tool header / ToolHeader render

- **`mount_tool_block` arg order**: signature is `(label, lines, plain_lines, tool_name=None, rerender_fn=None, header_stats=None)`. All `call_from_thread(tui.mount_tool_block, ...)` in cli.py pass `function_name` as arg 4 (tool_name), `_rerender_*` as arg 5 (rerender_fn), `header_stats` as arg 6. Tests check `args[5]` for callable, not `args[4]`.
- **`_compact_tail` for file-tool STBs**: Set `block._header._compact_tail = True` when `set_path()` is called in `_update_block_label`. Makes duration render inline after path label, not right-aligned. Diff blocks always get compact_tail via `mount_tool_block`.
- **Shell prompt prefix**: `ToolHeader._shell_prompt = True` causes `render()` to prepend `" $"` in accent color (`_focused_gutter_color`) right after the icon. The 2-cell width is tracked via `shell_prompt_w` and added to `FIXED_PREFIX_W` for correct tail right-alignment. Set for terminal/bash tools in `_update_block_label`.
- **Consecutive patch deduplication**: `HermesCLI._pending_patch_paths: dict[str, str]` maps path → active tool_call_id. When a second patch to the same path arrives while first is active, `remove_streaming_tool_block` is called immediately. The diff from the suppressed patch still mounts and attaches to the first patch via Rule 1 (diff attachment, 10s window). Entry is cleaned up in `_on_tool_complete`.
- **Virtual grouping is CSS-only** (`group-id-<hex>` + `tool-panel--grouped` classes) with DOM reparenting into `ToolGroup`. There is no longer a CSS-only path for grouping after graduation; `_schedule_group_widget` always runs.
- **Context menu focus restore**: `ContextMenu._prev_focus` is saved in `show()` and restored in `_ContextItem.on_click()`. Prevents input area from stealing focus when a context menu item is clicked.
- **`_label_rich` for grep patterns**: Set `block._header._label_rich` to a Rich `Text` with per-character regex coloring in `_update_block_label` for `search_files` and `grep`. `_label_rich` takes precedence over `_label` string in render when `_path_clickable` is False.
- **`RenderResult` is a type alias, not a callable**: `render()` must return `Text(...)` directly — do NOT write `return RenderResult(Text())`. That throws `TypeError: 'str' object is not callable` in Textual 8.x where `RenderResult` is a string type alias.
- **Duration string assertions break**: `_on_stream_complete` computes actual elapsed from `_stream_started_at` (set in `on_mount`), not the `duration` string argument. Tests asserting `block._header._duration == "2.3s"` will fail. Assert `isinstance(block._header._duration, str)` instead.

## ToolPanel binary collapse gotchas

- **`watch_collapsed` must hide `block._body`, NOT BodyPane**. Hiding BodyPane also hides ToolHeader (it's inside BodyPane → ToolBlock), making the second click to expand impossible. Always hide `block._body` (ToolBodyContainer).
- **ToolBodyContainer needs CSS override**: DEFAULT_CSS sets `ToolBodyContainer { display: none }`. Add `ToolPanel ToolBodyContainer { display: block; }` in `hermes.tcss` to ensure initial visibility. Python `styles.display` inline then overrides when collapsing.
- **Browse `a`/`A` queries ToolPanel, not ToolBlock**: After binary collapse, `block._body.has_class("expanded")` is no longer the collapse signal. The browse handler calls `self.query(ToolPanel)` and checks `panel.collapsed`. Bare ToolBlock mounts (no ToolPanel wrapper) are NOT affected by these keys.
- **BodyPane is always `display: block`** after binary collapse. Tests checking `panel.query_one(BodyPane).styles.display` should assert it is NOT `"none"`, never `"none"`.
- **ToolBlock.toggle() delegates to panel when inside ToolPanel**. `_body.has_class("expanded")` is never set on in-panel blocks. Check `panel.collapsed` in tests.

## ToolSpec and tool_category gotchas

- **`spec_for("")` must not raise**. Empty tool name → `ToolSpec(name="")` → `ValueError("non-empty")`. Guard at top of `spec_for`: return UNKNOWN sentinel when `name` is falsy. `_tool_name or ""` pattern exists across codebase — callers frequently pass `None`/`""`.
- **`_category_glyph` must NOT call `ThemeManager.instance()`**. `ThemeManager` has no `.instance()` classmethod — silently returns `""` on `AttributeError`. Read from `_CATEGORY_DEFAULTS[cat].icon_nf` directly.
- **MCP server names must NOT contain `__`**. `register_mcp_server` rejects names with `__` because MCP canonical names are `mcp__{server}__{tool}` — double-underscore is the delimiter. Use hyphen-delimited names in tests: `"test-svc"`, `"svr-icon"`.
- **`_derive_mcp_spec` result must NOT be in TOOL_REGISTRY**. Derived MCP specs are ephemeral. Writing them would shadow explicit overrides. `test_mcp_derived_not_in_tool_registry` verifies this invariant.
- **ToolSpec validation raises at construction time**. `name=""` → ValueError, bad `provenance` → ValueError, invalid `primary_result` → ValueError. Validation in `__post_init__` (frozen dataclass). No lazy validation.
- **WEB/MCP `emit_heartbeat` default**: `ToolSpec.emit_heartbeat` defaults `False`. For MCP-derived WEB/MCP specs, always set `emit_heartbeat=True` — the `_derive_mcp_spec` condition `elif category in (WEB, MCP) and not inner_spec.streaming` was never True because `inner_spec.streaming` defaults `True`. Fix: `elif category in (WEB, MCP)`.
- **`_ENGINES` in drawbraille_overlay is class refs, not instances**. After v2, `_ENGINES` is `dict[str, type]`. `_get_engine()` caches instance in `_current_engine_instance`. Tests must call `engine_cls()` to get an instance — do NOT iterate `_ENGINES` as instances.

## ToolsScreen async gotchas

- **`_apply_filter` / `_rebuild` must be `async def`**. Both call `await listview.clear()` / `await listview.append(...)`. A bare `self._apply_filter()` without `await` silently discards the coroutine — ListView never repopulates. All call sites must `await`.
- **Timer cancellation required in `on_unmount`**. Without `self._stale_timer.stop()` in `on_unmount`, `_update_staleness_pip` fires after Screen unmount → `NoMatches` on DOM queries.
- **`_dismiss_all_info_overlays()` does NOT affect `ToolsScreen`**. It's a real Screen pushed via `push_screen`, not a Widget overlay with `--visible` class. Dismissed only via `app.pop_screen()`.
- **Duplicate panel ID guard**: if `id="tool-{tool_call_id}"` already exists in DOM, `panel_id=None` to avoid Textual `DuplicateIds`. Jump-to-panel from the overlay may silently fail.

## ReasoningFlowEngine — StreamingBlockBuffer and the `process_line` override

`ReasoningFlowEngine` overrides `process_line(raw)` to call
`super().process_line(raw)` then immediately `_flush_block_buf()`. This
eliminates the one-line `StreamingBlockBuffer` lookahead lag so every prose and
list line appears immediately (no typewriter flash).

Tradeoff: setext headings render as prose-line + HR, tables as plain pipe rows.
Both are rare in reasoning output; ATX headings (`## Foo`) still work correctly.

In tests that access `msg.reasoning._reasoning_engine` or require engine-path
processing: call `rp = msg.reasoning` (triggers lazy mount), then
`await pilot.pause()` before using the engine — `on_mount` needs one loop cycle.

## Threading and timers

- **`Timer.stop()` not `.cancel()`** — Textual 8.x timer handles expose `.stop()`. There is no `.cancel()` method. Calling `.cancel()` raises `AttributeError`. Debounce pattern: `self._timer.stop(); self._timer = self.set_timer(delay, callback)`.
- `set_interval(...)` callbacks should be plain `def` callbacks.
- **`call_from_thread` crashes when called from the event-loop thread** with
  `RuntimeError: The call_from_thread method must run in a different thread`.
  `_consume_output` is an `@work` async coroutine — it runs ON the event loop,
  not in a thread. Any helper called from `process_line` / `_commit_lines`
  must guard: `if threading.get_ident() == getattr(app, "_thread_id", None): fn() else: app.call_from_thread(fn)`.
- Do not call `call_from_thread(...)` from the app thread.
- Keep polling, file reads, parsing, and hot-reload detection off the event
  loop.
- `@work(thread=True)` workers that block forever on `queue.get()` cause
  teardown pain. Prefer instance state plus async/event-loop dispatch.
- `post_message(...)` is usually safer than `call_from_thread(...)` for worker
  results that belong to the same widget.
- **Workspace polling must not have two timer owners.** Use one app-level
  helper (`_sync_workspace_polling_state()`) and let it decide based on overlay
  visibility / `agent_running`. Scattered `set_interval` start-stop logic drifts.
- **Workspace overlay rows come from Git snapshot, not Hermes writes.**
  `record_write()` only annotates rows; inclusion comes from the latest
  `GitSnapshot`. If you expect a file to show up without Git reporting it,
  you are debugging the wrong layer.
- **Single-sample perf warnings are usually noise.** Use `SuspicionDetector`
  for "hunch" logging so one scheduler blip does not spam the Textual log.
- **`ResponseFlowEngine` is NOT a Widget.** `@work` is unavailable on it. For
  async off-loop work (e.g., `_flush_math_block`), use
  `self._panel.app.run_worker(fn, thread=True)` + `call_from_thread`.

## Shared animation clock (`AnimationClock`)

`HermesApp` creates one `AnimationClock` at mount and exposes it as
`self._anim_clock`. All animation widgets subscribe to it instead of creating
their own `set_interval` calls. This keeps timer object count near-constant
regardless of how many widgets are animating.

**Divisor cheat-sheet** (clock runs at 15 Hz):

| Divisor | Rate   | Used by                          |
|---------|--------|----------------------------------|
| 1       | 15 Hz  | PulseMixin, ImageBar shimmer     |
| 2       | 7.5 Hz | HintBar shimmer, completion list |
| 4       | 3.75 Hz| ThinkingWidget dots/helix        |
| 8       | 1.9 Hz | LiveLineWidget cursor blink      |
| 75      | 0.2 Hz | StatusBar hint rotation (5 s)    |

**Pattern for new animated widgets:**

```python
def _anim_start(self) -> None:
    if self._anim_handle is not None:
        return
    clock: AnimationClock | None = getattr(
        getattr(self, "app", None), "_anim_clock", None
    )
    if clock is not None:
        self._anim_handle = clock.subscribe(DIVISOR, self._tick)
    else:
        self._anim_handle = self.set_interval(1 / RATE_HZ, self._tick)

def _anim_stop(self) -> None:
    if self._anim_handle is not None:
        self._anim_handle.stop()
        self._anim_handle = None

def on_unmount(self) -> None:
    self._anim_stop()
```

The `_ClockSubscription` returned by `clock.subscribe()` exposes `.stop()` — same
interface as Textual timer handles. Unit tests that use fake stubs without `app`
fall through to the `set_interval` branch automatically.

**Do not** use the shared clock for `StreamingToolBlock`'s 60 Hz render timer
(too fast) or for non-animation work timers (debounce, countdown precision).

## Output and scrolling

- `_cprint(...)` appends a newline. Partial streaming updates in TUI mode
  should use `app.write_output(...)`, not `_cprint(...)`.
- Inner `RichLog` scrolling causes corruption and stale repaint behavior when
  nested inside `OutputPanel`.
- `open_streaming_tool_block(...)` and other new output mounts should preserve
  live-edge scroll behavior.
- `watch_agent_running(False)` clears interrupted streaming-block state. Do not
  rely on leaked `_active_streaming_blocks`.
- `flush_output()` exists for queue/sentinel behavior and tests, but it is not
  the main production turn-teardown path.
- `watch_scroll_y()` has headless/test guards around `max_scroll_y == 0`; keep
  them if you touch live-edge logic.
- `ToolTail` state is per streaming block. Regressions usually show up in
  `tests/tui/test_scroll_integration.py`.

## Overlay and input behavior

- **Slash-menu overlays MUST be modal — focus must never return to the input bar while an overlay is visible.** If `HermesInput` (or any `Input` widget) regains focus while a slash overlay is open, printable keystrokes go to the input field rather than the overlay, breaking keyboard navigation entirely. Enforce this by: (1) calling `overlay.focus()` immediately after mount; (2) overriding `on_focus` on the input widget to re-delegate focus to any active overlay; (3) NOT calling `input.focus()` in dismiss paths — use `app.set_focus(None)` or let the overlay's `on_dismiss` restore focus explicitly.
- If an overlay needs printable key handling, disable the input while it is
  active so input does not consume those keys first.
- **Composer assist state has one owner now: `HermesInput._resolve_assist(...)`.** Completion overlay, skill picker, and plain mode must converge through `AssistKind` (`NONE`, `OVERLAY`, `SKILL_PICKER`). Do not clear one assist surface directly from another subsystem.
- Hidden focused widgets can still swallow scroll or key events. Dismiss paths
  may need explicit focus handoff.
- Overlay stacking is centralized in `app.py`. Avoid one-off dismiss logic in
  widgets unless the app-level policy changes too.
- Debounced overlay callbacks must be cancelled in dismiss/teardown paths.
- Hidden `display: none` parents can suppress worker delivery in tests. Check
  visibility lifecycle before debugging a "worker never returned" failure.
- **Workspace overlay has a real non-Git state now.** Outside a Git repo it
  should stay mountable but render the empty-state copy, with no polling.
- **Opening / dismissing workspace overlay affects polling state.** If a test
  flips `--visible` directly, it may also need to call the app sync helper or
  go through the action path.

## Theme and CSS

- `get_css_variables()` is called during `super().__init__()`. Guard instance
  attrs with `getattr(...)`.
- New `$vars` must be declared in `hermes.tcss` before use or startup fails.
- `RichLog` subclasses inherit background defaults you may need to override.
- Transparent widgets inherit from `Screen`, not just `HermesApp`.
- In this theme, `$surface` can equal `$app-bg`; elevation sometimes requires
  `$surface-lighten-1` or `$panel`.
- New runtime-overridable vars need both TCSS declaration and ThemeManager
  wiring when they must be skin-controlled.
- **`border-left` + component vars = silent startup crash.** `color: $text-muted`
  works fine in external TCSS, but `border-left: vkey $text-muted` silently
  prevents the app from mounting (`OutputPanel` not found, `_anim_clock_h`
  AttributeError on unmount). For `border-left` use ONLY Textual built-in
  design tokens: `$primary`, `$accent`, `$warning`, `$error`, `$success`.
  (Diagnosed during Tool Panel v2 Phase 1, 2026-04-17.)
- **`$text-muted 20%` is a TCSS parse error.** The opacity-modifier syntax `$VAR N%`
  only works for Textual native design tokens (`$primary`, `$accent`, etc.). Use
  `$primary 15%` for dim neutral, or a raw hex color.

## Textual behavior traps

- `compose()` and `render()` are mutually exclusive in practice for one widget.
- `Widget.mount(child, before=anchor)` uses `anchor.parent` for the mount container.
  Choose anchors from the intended parent. Use `parent.mount(child, after=self)`
  (sibling mount) not `self.mount(child, after=self)` — the latter silently mounts
  into the wrong container.
- `remove_children()` plus immediate `mount()` can race; explicit per-child
  `remove()` is safer in sensitive paths.
- `pilot.resize_terminal(...)` is async and must be awaited.
- `scroll_offset` is read-only; use scroll APIs instead.
- `query_one(...)` raises `NoMatches`; teardown-safe code should guard it.
- **`@work` decorator is `from textual import work`** in Textual 8.x — NOT
  `from textual.worker import work` (raises `ImportError`). Applies to any
  deferred class construction that imports `work` inside a factory function
  (e.g., `_build_animated_emoji_widget()`).
- Plain `str` from `render()` is literal text, not Rich markup.
- **`Static.renderable` does not exist in Textual.** Tests that check a Static's
  content must use `str(widget.render())` (the `render()` method), not
  `widget.renderable`. Applies to all Static-based widgets.
- **`watch_state` must use `add_class`/`remove_class`, not `set_classes`.** 
  `set_classes(f"-{new}")` replaces ALL classes, wiping position classes like
  `-first`, `-last`. Correct pattern:
  ```python
  def watch_state(self, old: str, new: str) -> None:
      if old:
          self.remove_class(f"-{old}")
      self.add_class(f"-{new}")
  ```

## Completion and preview

- `VirtualCompletionList` should stay O(viewport), not O(total items).
- Preview workers need cancellation checks around blocking file-read paths.
- Blank overlay states usually mean list/preview lifecycle or worker-cancel
  logic regressed, not just rendering.
- `TERMINAL_CWD` can silently change path-root behavior in tests and live runs.
- **`_compute_mode()` must read `_completion_overlay_active`, not DOM/query state.** Mode resolution runs in tests and teardown paths where the overlay object may not exist or may be stale.
- **Ghost suggestions and overlays are separate assist surfaces.** `_update_autocomplete()` may update inline ghost text without any overlay being active. Clearing assist unconditionally in the no-overlay branch regresses multiline ghost suggestions.
- **History persistence is full-file rewrite, not append.** `_save_to_history()` now deduplicates and atomically rewrites the prompt_toolkit history file with `NamedTemporaryFile` + `os.replace`. The expected wire format starts at `+entry` with no synthetic leading blank line.
- **Textual CSS `border-left` is stricter than `color`.** In this composer work, token/grey variants failed parse or mount, while plain `white` / `red` worked for `HermesInput.--rev-search` and `HermesInput.--error`.

## Text selection in RichLog / CopyableRichLog

- `RichLog.render_line()` adds **no** `style.meta["offset"]` → compositor
  `get_widget_and_offset_at()` returns `offset=None` → `_select_start` is never
  set → drag-to-select silently does nothing.  Fix: override `render_line` and
  call `strip.apply_offsets(scroll_x, content_y)`.
- `RichLog._render_line()` also does **not** paint `screen--selection` (unlike
  `Log._render_line_strip`).  The selection state is tracked internally but
  nothing is highlighted.  Fix: call `selection.get_span(content_y)` in
  `render_line` and apply the background via `_apply_span_style` **before**
  `apply_offsets`.
- `get_selection()` must build its source text from `self.lines` (visual strips,
  one per visual row) not from a logical buffer like `_plain_lines`.  When
  `wrap=True`, a single `write()` call creates multiple entries in `self.lines`
  but only one in `_plain_lines`, so selection y-indices misalign and clipboard
  extraction silently returns wrong text.
- `ALLOW_SELECT` (default `True`) and `can_focus=False` are orthogonal.
  Selection is routed by cursor position in `Screen._forward_event`, not by
  focus.  `can_focus=False` does not break selection; missing offset metadata
  does.

## Perf fixes applied 2026-04-17 (lag.log diagnosis)

**`_tick_spinner` shimmer cost (10Hz hot path):**
- `shimmer_text()` + `Content.from_rich_text()` ran every tick = every 100ms.
- WRONG approach: throttling to 5Hz (skip every other tick). Kills smoothness, masks the real problem.
- CORRECT fix: batch same-color runs in `shimmer_text()`. Pre-compute colors for all N chars, then merge consecutive same-color positions into a single `Style` span. Reduces spans from N → ~20. Result: 0.1ms per call, full 10Hz works fine. Total shimmer+Content path = 0.2ms.
- Also: hoist `shimmer_text` and `Content` imports to module level. Import inside hot path adds overhead even with Python's module cache.
- Also: remove redundant `import time as _t` inside tick — use existing module-level `_time`.
- **General rule: optimize the work, don't skip the frame.** If an animation callback is too slow, make the computation faster (batch, cache, pre-compute), don't reduce the frame rate.

**`AnimationClock.tick` per-subscriber timing:**
- Original log only showed total tick time (`anim_clock.tick took 514ms (5 subs)`) — no way to tell which subscriber blocked.
- Fix: time each subscriber callback individually. When total > 16ms, log slowest sub ID + ms. Example: `(slowest sub#0: 510ms)` → points at drawbraille overlay at sub_id=0.

**`_refresh_live_response_metrics` called from both `_tick_spinner` (10Hz) and `_tick_duration` (1Hz):**
- Has early return when `_response_metrics_active` is False — safe during idle. But during streaming, 10Hz of `query_one(OutputPanel)` + `msg.set_response_metrics()` is redundant. Acceptable for now since total path is ~1ms.

## InlineProseLog / emoji render-safety (fixed 2026-04-20)

**NEVER call `_render()` or `get_strips()` from inside `render_line`.** `InlineImageCache._render()` does PIL image resizing and (for TGP) emits raw Kitty Graphics Protocol escape sequences via `sys.stdout.write`. Calling either from `render_line` causes:
- TGP path: raw escape bytes interleaved with Textual's output buffer → screen corruption/glitch on kitty.
- Halfblock path: PIL `img.resize()` blocks the event loop inside the render phase → freeze.

**Correct pattern:** Use `get_strips_or_alt()` in `render_line` — returns alt_text strips on cache miss, never calls `_render()`. Pre-populate the cache from `write_inline()` via `_prerender_line_images()`:
- TGP spans: emit `sys.stdout.write(tgp_seq)` synchronously in `_prerender_line_images()` (event loop, but NOT inside render_line's call stack).
- Halfblock spans: offload PIL work to `@work(thread=True) _prerender_halfblock()`; call `self.refresh()` from worker thread when done.

**`_current_render_mode()` ioctl trap:** Calling `_cell_px()` (raw `fcntl.ioctl`) on every `render_line` invocation adds a syscall per frame per visible inline-image line. Fix: use `cell_width_px()` / `cell_height_px()` (both cached) instead. Cache the full `_RenderMode` object on the widget; invalidate in `on_resize()` which must also call `_reset_cell_px_cache()` to pick up the new terminal dimensions.

**`_prerender_halfblock` needs app context** — the `@work(thread=True)` decorator raises `LookupError` when called outside a mounted widget (e.g., unit tests). Guard with `try/except` in `_prerender_line_images`; render_line shows alt_text until the worker finishes.

**`text_selection` property needs screen** — in unit tests for `render_line` overrides, patch with `patch.object(type(widget), "text_selection", new_callable=lambda: property(lambda self: None))`.

## Small but expensive traps

- `len(log.lines)`, not `log.line_count`
- `await pilot.pause()` after message posts or reactive churn
- Input placeholder owns spinner text; sibling spinner widgets cause layout churn
- ResponseFlow changes often need both unit tests and streaming integration checks
- `ToolsScreen._apply_filter` is async — always `await` it

## CSS and layer system traps

**Gotcha: MinSizeBackdrop must be queried via `self.screen.query()`, not `self.query()`**
`MinSizeBackdrop` mounts on the Screen (via `self.screen.mount(...)`), not on the App. `self.query("MinSizeBackdrop")` searches the App's DOM subtree and returns empty. Use `self.screen.query("MinSizeBackdrop")` in `_apply_min_size_overlay`.

**Gotcha: `layer: overlay` in DEFAULT_CSS silently kills HermesApp.on_mount**
If any widget class is defined (imported) with `layer: overlay` in its `DEFAULT_CSS` BEFORE `app.py` completes its import chain, Textual's CSS compilation is corrupted and `on_mount` never fires. The symptom is `AttributeError: 'HermesApp' object has no attribute '_anim_clock_h'` in `on_unmount`.

Fix: **never put `layer: overlay` in `DEFAULT_CSS`**. Instead, declare it in `hermes.tcss` only. Structural CSS that references Textual's layer system belongs in `hermes.tcss`, not in widget `DEFAULT_CSS`. Same rule applies to `position: absolute` — put it in `hermes.tcss` alongside `layer: overlay`.

Also applies to CSS variables (`$accent`, `$surface-darken-2` etc) — do NOT use `$var` references in `DEFAULT_CSS` either; they also cause silent CSS parse failures at class-definition time.

**Gotcha: overlay widget needs `position: absolute` in hermes.tcss for offset to be screen-absolute**
Without `position: absolute`, a widget's `offset` CSS is relative to its normal layout-flow position, not the screen origin. Symptom: `self.styles.offset = (tw-w-2, 1)` in `_apply_size_position` appears to have no effect — widget stays at its flow position offset by those amounts. Fix: add `position: absolute` to the widget's rule in `hermes.tcss` (next to `layer: overlay`). Both must be in `hermes.tcss` — not `DEFAULT_CSS`.

**Gotcha: `query_one(WidgetType)` in app methods is fragile — prefer `query_one("#id", Type)`**
`query_one(DrawbrailleOverlay)` can raise `NoMatches` even when the widget is mounted if the class object differs (import aliasing, hot-reload edge cases). Use `query_one("#drawbraille-overlay", DrawbrailleOverlay)` for reliability. When the query is the first line of a toggle/hide handler and is wrapped in `except Exception: pass`, a silent miss means the handler does nothing. Always separate the query guard (`except Exception: return`) from the operation body so operation errors surface.

**Gotcha: `_handle_tui_command` must be wired into `on_hermes_input_submitted`**
Slash commands like `/anim`, `/undo`, `/compact` are intercepted in `_handle_tui_command`. This method returns `True` if handled. It must be called at the TOP of `on_hermes_input_submitted`, BEFORE the agent-running branch, so commands work whether the agent is idle or running. Individual handlers check `agent_running` themselves. Forgetting the wire-up causes all TUI commands to be forwarded to the agent as user messages.

**Gotcha: ExecuteCodeBlock duplicate block on gen/tool race**
`_on_tool_start` for `execute_code` pops the first entry from `_gen_blocks_by_idx`.
If `_open_execute_code_block` failed silently (exception caught, returns None),
`_gen_blocks_by_idx` is empty and the fallback fires — creating a second block.
Guard: check `tool_call_id in tui._active_streaming_blocks` before any block
creation, and fallback must create `ExecuteCodeBlock` not `StreamingToolBlock`.

**Gotcha: `load_config()` side effect in tests**
`load_config()` calls `ensure_hermes_home()` which creates the hermes home directory. If a test sets `HERMES_HOME` to point to `tmp_path`, this creates subdirs (`cron/`, `sessions/`, `SOUL.md` etc.) inside `tmp_path`. The path_search walker then finds these as extra files.

Fix: use `read_raw_config()` instead of `load_config()` for lightweight config reads where you just need a single value. `read_raw_config()` does not call `ensure_hermes_home()`.

**Gotcha: new `$var` refs must be declared in `hermes.tcss`**
Any new `$my-var` used in `.tcss` files must be declared at file scope in `hermes.tcss`. `get_css_variables()` injection alone is insufficient — Textual's CSS parser rejects undeclared `$var` refs at parse time with no error (silently missing). Example: `$tool-glyph-mcp: "󰡨";` added for ToolCategory MCP icon.

## Animation perf patterns

**Per-character `lerp_color()` → batch same-color runs.**
Functions like `shimmer_text`, `DrawbrailleOverlay._render_multi_color`, and
`VirtualCompletionList._render_shimmer_row` all iterate per-character and
create individual `Style(color=...)` objects. This creates N Rich Text spans
for N characters. Instead:
1. Pre-compute color per position into a `list[str]`.
2. Batch consecutive same-color runs into single spans.
Result: ~20 spans instead of ~60+. Dramatically reduces Rich/Textual overhead.

**`lerp_color()` hex parse on every call → `_parse_rgb()` cache.**
`lerp_color` internally parses hex→RGB every call. When called with the same
color pair across many characters/ticks, this is wasted work. Fix: module-level
`_RGB_CACHE: dict[str, tuple[int, int, int]]` in `animation.py`. Also expose
`lerp_color_rgb(c1_rgb, c2_rgb, t)` for pre-parsed tuples (used in drawbraille
overlay and completion shimmer). Cache is bounded at 256 entries.

**Imports inside hot-path callbacks.**
`from hermes_cli.tui.animation import shimmer_text` and
`from textual.content import Content` inside `_tick_spinner` ran on every
100ms tick. Python's import cache makes this ~0.01ms but still wasteful —
hoist to module level.

**`AnimationClock.tick` per-subscriber timing for spike diagnosis.**
When `anim_clock.tick` exceeds 16ms, log which subscriber was slowest:
`(slowest sub#N: Xms)`. Subscriber IDs are assigned at `subscribe()` time.
Drawbraille overlay = typically sub#0 (divisor=1, 15Hz). PulseMixin = sub#0
if subscribed before drawbraille. To find mapping: search for
`clock.subscribe(DIVISOR, ...)` across `widgets.py`, `drawbraille_overlay.py`,
`completion_list.py`.

## File drop gotchas

**Quoted paths from terminals.**
Some terminals quote drag-and-drop paths (`"/path/file.py"` or
`'/path/file.py'`). `_decode_path_text` must strip surrounding matching
quotes before URL-decoding. Without this, `parse_dragged_file_paste`
returns `None` for quoted paths — the drop silently fails.

**Space-separated multi-file drops.**
Terminals may send multiple files as space-separated paths on one line:
`/a.py /b.txt`. `parse_dragged_file_paste` historically only split on
newlines. Fix: `_split_quoted_paths()` — quote-aware tokenizer that
handles `"/path with spaces/file.py" /no-spaces.py` correctly.

**Paths with spaces in filenames.**
`classify_dropped_file` previously rejected text files containing spaces
in the path with "spaces not supported in @path yet". This prevented
dropping common files (e.g., "my notes.py"). Fix: accept them. Use
quoted format in `format_link_token` (`"my notes.py"`) to handle
spaces in the agent-side path resolution.

**`format_link_token` no @ prefix.**
Tokens are plain paths now, not `@path`. Relative if in cwd, absolute
otherwise. Paths with spaces get double-quoted: `"path with spaces/file.py"`.
Agent-side file content reading handles plain paths natively.

**GNOME Terminal DnD: `_on_paste` never fires; Enter submits raw path.**
When Textual's mouse mode `?1003h` is active, VTE sends dropped file paths
as raw chars — NOT bracketed paste. `_on_paste` is never called. Characters
land in the TextArea synchronously (via TextArea's `_on_key`), but
`TextArea.Changed` notifications are queued async. The trailing `\n` from
the file URI arrives as an Enter key event that fires `action_submit()`
BEFORE the async queue drains — so the raw path gets submitted as a message.

Fix (in `HermesInput._on_key`): before calling `action_submit()` on Enter,
run `detect_file_drop_text(self.text.strip())`. If it matches, clear the
input and post `FilesDropped` instead.

`event._no_default_action = True` IS the correct API to stop the MRO walk in
Textual 8.x — confirmed in `_get_dispatch_methods` source (breaks loop when
the flag is set). `event.prevent_default()` sets `_prevent_default`, which
is a different flag used for different purposes.

## Rich markup in Button (and Static) labels

`Button("[reset]")` renders an **empty** label — `[reset]` is a Rich markup
style-reset tag. The same happens with any `[word]` that is a valid Rich tag.

**Fix:** Escape with a backslash: `Button("\\[reset]")` (Python string `"\\[reset]"` →
string literal `\[reset]` → Rich renders as `[reset]`).

Applies to `Button`, `Static`, `Label`, any widget whose constructor accepts
markup strings. Always escape brackets in labels unless you intend markup.

To verify: `str(button.label)` returns empty string if the tag was consumed.

## Pytest under rtk-ai/rtk

`rtk-ai/rtk` intercepts all pytest CLI output and replaces it with compressed summaries. Symptoms:
- `--collect-only` shows "No tests collected" even when tests exist
- Normal runs show "Pytest: N passed" instead of full output
- Failure details are in `~/.local/share/rtk/tee/<timestamp>_pytest.log`

**Fix:** always run with `--override-ini="addopts="`:
```
python -m pytest <path> -q --override-ini="addopts="
```
For full failure detail: read the log path printed by rtk on failure.

**In pilot tests:** `call_from_thread(...)` raises `RuntimeError` when called from the event-loop thread (which is what pilot tests run in). Use direct method calls instead: `app.open_streaming_tool_block(...)` not `app.call_from_thread(app.open_streaming_tool_block, ...)`.

## web_search adjacent-mount (`_web_search_adj_anchor`)

`MessagePanel` tracks `_web_search_adj_anchor: Widget | None` to ensure `search` sub-tool blocks appear directly after `web_search`, not after subsequent reasoning text.

- Set to the `web_search` ToolPanel immediately before `_mount_nonprose_block` is called
- Subsequent SEARCH-category tools (tool_name != "web_search") check this anchor; if set and still in `self.children`, they mount directly after it (before any reasoning text that arrived between)
- After each adjacent mount, the anchor advances to the newly mounted panel (stacking multiple search sub-calls in order)
- Anchor is implicitly reset per MessagePanel (fresh instance each turn)

## First-response-line disappears ("W" missing from "Wake up Neo")

Race between agent streaming and `watch_agent_running(True)` firing on the
event loop can cause the first response line to be buffered in the OLD
(startup/previous-turn) panel's `_block_buf._pending` and never flushed.

Root cause chain:
1. Banner postamble (or previous response trailing blank) leaves `_pending = ""`
   on the current panel via `process_line("")`.
2. Agent starts streaming before `watch_agent_running(True)` fires; first
   response line arrives in `_commit_lines()` which uses `current_message`
   (still the old panel) → `process_line("Wake up Neo")` on old panel →
   `_handle_line` returns `""` (old empty pending), holds "Wake up Neo".
3. `watch_agent_running(True)` fires → `new_message()` → old panel never
   flushed again → "Wake up Neo" lost.

Fix (2026-04-20):
- `watch_agent_running(True)` steals `_block_buf._pending` from old engine,
  clears it, stores as `new_msg._carry_pending`.
- `MessagePanel.on_mount` processes `_carry_pending` through the new engine
  once it's ready (`_response_engine` is None in `__init__`, set in `on_mount`).
- Clears empty-string sentinel too — prevents poisoning the next turn.

**Do NOT call `engine.process_line()` on a freshly created MessagePanel from
`watch_agent_running()` directly** — the engine isn't mounted yet. Always
route deferred engine calls through `_carry_pending` / `on_mount`.

## Completion system gotchas

**`frozenset()` default is falsy — use `None` as sentinel for "unset".**
`HermesApp._path_search_ignore` defaults to `None`, not `frozenset()`.
`_walk()` checks `ignore if ignore is not None else {defaults}`.
Do NOT use `ignore or {defaults}` — an empty `frozenset()` (meaning "ignore nothing")
is falsy and would silently fall through to the hardcoded default set.
General rule: when `None` means "unset" and `frozenset()` is a valid user value, always
use explicit `is not None` checks, never truthiness.

**`_last_slash_hint_fragment` debounce: reset on submit only, NOT on hide.**
`_show_slash_completions` calls `_hide_completion_overlay` on the no-match path.
If `_hide_completion_overlay` reset the fragment, the debounce would clear itself
immediately each time — making the guard useless. Only `action_submit()` resets it.

**`SlashDescPanel` import: no cycle exists between `completion_overlay.py` and `path_search.py`.**
`from .path_search import SlashCandidate` at module level is safe.
No need for deferred inside-method import.

## SkinColors / skin contract gotchas (SC-1..SC-5, 2026-04-26)

**`MappingProxyType` field in a frozen dataclass requires `field(default_factory=...)`.**
Even though `MappingProxyType` is immutable, Python 3.11 raises `ValueError: mutable default`
for any non-primitive as a frozen-dataclass default. Use:
```python
tier_accents: MappingProxyType = field(
    default_factory=lambda: _EMPTY_MAP, hash=False, compare=False, repr=False
)
```
Not `field(default=_EMPTY_MAP, ...)`.

**`SkinColors.tier_accents` must include legacy display-tier keys.**
`display_tier_for()` in `tool_category.py` returns `"file"`, `"exec"`, `"query"`, `"agent"` —
NOT the `TIER_KEYS` frozenset. Build `tier_accents` from `TIER_KEYS | frozenset({"file","exec","query","agent"})`.
Without the legacy keys, `.get("file", fallback)` always falls back.

**`hasattr(mock, "_resolver")` is always `True` for MagicMock — use `getattr(...) is not None`.**
`MagicMock` auto-creates attributes on first access. `hasattr(panel, "_resolver")` returns True
for any bare `MagicMock()`. Tests that mock a panel must set `panel._resolver = None` explicitly,
and production code must guard with `getattr(self._panel, "_resolver", None) is not None`.

**`ToolHeader._colors()` lazy-caches on `_skin_colors_cache` — not in `__init__`.**
Tests using `ToolHeader.__new__()` start with no cache. First call resolves from `self.app`
(mock via `PropertyMock` on `type(h)`). The cache persists for the object's life — if a test
calls `_render_v4()` twice with different apps, only the first resolution is used.

**`_DROP_ORDER` alias exists in `_header.py` as `_DROP_ORDER_DEFAULT`.**
After DU (density unification), the single `_DROP_ORDER` was split into tier-specific lists.
`_header.py` re-exports `_DROP_ORDER = _DROP_ORDER_DEFAULT` for backward compat. Flash is now
at index 0 (drops first); Spec A overrode the header-signal-hardening spec's "flash drops last".
Tests asserting `_DROP_ORDER[-1] == "flash"` must be updated to `_DROP_ORDER[0] == "flash"`.

**AST parent-mapping required for targeted `style=` kwarg scanning.**
`ast.walk` does not give parent info. To find only `style=` kwargs and `Style()` positional args
(not dict values or docstrings), build a parent map first:
```python
parent = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
```
Then check `isinstance(parent.get(node), ast.keyword) and parent[node].arg == "style"`.
Skipping this yields false positives on `_TONE_STYLES = {"error": "bold red"}` dict literals.

## Alt+$ key encoding is terminal-dependent (2026-04-26)

`event.key` for `Alt+$` varies by terminal: can arrive as `"alt+4"`, `"alt+dollar_sign"`, or `"alt+$"` depending on whether the terminal sends alt-code or alt-meta sequences. Never match on `event.key == "alt+$"` alone.

**Reliable pattern**: `getattr(event, "character", None) == "$" and event.key.startswith("alt+")`. This works because `event.character` is set to the base character (`$`) regardless of how the modifier is encoded.

Affected site: `hermes_cli/tui/services/keys.py §dispatch_key` (SNS1 Phase 1, 2026-04-26).

## SkillPickerOverlay trigger_source auto-dismiss contract (2026-04-26)

`SkillPickerOverlay` has two trigger modes controlled by `_trigger: str`:
- `"prefix"` — opened because user typed `$fragment`; **auto-dismisses** when `_SKILL_RE` no longer matches the input value (e.g. user deleted the `$`). The autocomplete handler in `_autocomplete.py` checks on every `Input.Changed` event.
- `"chord"` — opened via `Alt+$`; **stays** until explicit Esc/Enter/Tab.

If you forget this distinction and the picker disappears unexpectedly on input change, check `trigger_source` was passed correctly from `_open_skill_picker`.

## Ghost suggestion state and cached HintBar affordances (2026-04-28)

- `HermesInput` intentionally shadows `TextArea.suggestion` with a plain string
  class attribute. Do NOT "fix" it by making it a reactive on HermesInput:
  TextArea itself writes `self.suggestion = ""` while the user types, and a
  new reactive descriptor there will flicker ghost-dependent UI state off on
  normal keystrokes.
- Publish ghost visibility from `_resolve_assist(...)`, not from arbitrary
  `suggestion = ...` writes. The production contract is branch-local:
  GHOST publishes `True`, NONE/OVERLAY publish `False` after clearing
  suggestion, and PICKER publishes `False` explicitly because it never writes
  `self.suggestion`.
- `_build_hints()` in `status_bar.py` is cached by `(phase, key_color)` only.
  Any suffix that depends on viewport bucket, density tier, or live ghost
  state must be appended in `HintBar.render()` after the cached lookup.
- `HintBar.render()` can run before `on_mount()`, so attrs read there must be
  seeded in `__init__`. Watchers that mirror app reactives (`status_density_tier`,
  `status_ghost_suggestion`) still belong in `on_mount()`.
- Reactive watchers only fire on value changes. If a collapsed-only affordance
  must update when ERROR arrives to an already-collapsed panel, add a second
  refresh path from the state transition itself; `watch_collapsed()` alone is
  insufficient.

## When to expand this file

Add an entry only if it is:

- easy to regress,
- expensive to rediscover,
- specific to Textual or hermes-agent TUI behavior,
- and short enough to scan during active work.

## NoActiveAppError vs AttributeError (2026-04-26)

Textual's `self.app` property raises `NoActiveAppError` (subclass of `Exception`, NOT `AttributeError`) when widget has no active app. `getattr(self, "app", None)` only catches `AttributeError` — it does NOT suppress `NoActiveAppError`. Always use `try/except Exception: _app = None` when guarding app access outside a mounted widget.

## SkinColors.from_app patch path (2026-04-26)

When `SkinColors.from_app` is called inside a method via local import (e.g., `from hermes_cli.tui.body_renderers._grammar import SkinColors`), patching the import site does not work. Patch the source: `patch("hermes_cli.tui.body_renderers._grammar.SkinColors.from_app", ...)`.

## Meta-test comment grep trap (2026-04-26)

ER-5 meta-tests use `grep -rn "stderrwarn" hermes_cli/` to verify removal. Any code comment containing the literal word `stderrwarn` will trip this test. Reword comments to describe the pattern in abstract terms (e.g., "header owns category only, not evidence").

## Module-level constants before class definition (2026-04-26)

Constants used inside class methods (`_RECOVERY_KINDS`, `_RECOVERY_ORDER`) must be defined BEFORE the class body in the module. Defining them after the class causes `NameError` at call time even though the module loads. Python resolves names at call time for regular methods, not at class-definition time — but if the name is looked up in module scope and isn't there yet at the point of definition, it still fails on first call if Python didn't define it yet.

## Read-only Widget property leakage (2026-04-27)

`type(widget).is_attached = PropertyMock(...)` mutates the SHARED Widget subclass — leaks to every test in the pytest session that touches that class. Same trap for `size`, `app`, and any other Textual property. Fix: define a one-off `_IsolatedSubclass(StreamingToolBlock)` (cached at module scope) overriding the property as a class attribute or `@property`, then swap `instance.__class__ = _IsolatedSubclass`. This isolates the override to instances of the test subclass without touching the parent.

## Static widget renderable accessor (2026-04-27)

`Static(content)` stores its content at `_Static__content` (Python `__content` name-mangling), NOT `widget.renderable`. Tests that need to read back the rendered Text without a running App must use `widget._Static__content`. `widget.render()` and `widget.visual` both raise `NoActiveAppError` outside `run_test`.

## Static.remove() requires App context (2026-04-27)

`Widget.remove()` walks up to the App via the message pump — raises `NoActiveAppError` on bare-instance test mocks. For tests that exercise unmount paths, mock `widget.remove = MagicMock()` after constructing the widget.

## Threading.Event for daemon-thread / widget-mount synchronization (2026-04-28)

When a daemon thread needs to call `app.query_one(SomeWidget)` shortly after app startup, it will race `OutputPanel.compose()`. The fix: add a module-level `threading.Event` set in the widget's `on_mount` and cleared in `on_unmount`. The daemon thread calls `event.wait(timeout=N)` before any `query_one`. This is the canonical pattern for this class of pre-mount race in hermes (same defect class as R1-H-2 LiveLineWidget race).

- `import threading as _threading` must be in the **top-level imports** of the widget module, not inline near the class definition (linters flag out-of-order imports).
- The module-level constant (`STARTUP_BANNER_READY = _threading.Event()`) should live immediately before the class definition.
- Tests must include an `autouse` fixture that calls `event.clear()` before and after each test to prevent module-level state from leaking between tests.

## Textual default `Widget.render()` repr leak under real PTY (2026-04-28)

Widgets with an empty `compose()` (children mounted dynamically in an `activate()` method) can emit their class-id-CSS-classes string as visible text during a transient CSS-class-transition frame under a real PTY. Textual's default `Widget.render()` fallback fires before cascaded `display: none` resolves for the new class set.

- Captured in round-5 tmux audit (`tmux_B_80x24.txt` line 3) as `ThinkingWidget#thinking.--reserved.--fading`.
- **Safe pattern**: always override `render()` to return `RichText("")` for any widget whose `compose()` yields nothing and all visuals come from dynamically-mounted children.
- Bug is **invisible to Pilot** — only tmux/real-PTY harness surfaces it. Validates dual-harness audit procedure.
- Fix: `hermes_cli/tui/widgets/thinking.py` — `render()` always returns `RichText("")`.

## call_from_thread receives async function, not coroutine (2026-04-28)

`app.call_from_thread(_drain_latest)` passes the **async function object**, not a coroutine. When capturing it in tests via `mock_app.call_from_thread.side_effect = _capture`, `captured_fns[0]` is the function. To run it in tests: `asyncio.run(captured_fns[0]())` — the extra `()` call creates the coroutine.

## patch("cli.logger") scope: run asyncio coroutines inside the with-block (2026-04-28)

`_drain_latest` resolves `logger` via `cli` module globals at call time. If `asyncio.run(coro())` is called **after** the `with patch("cli.logger"):` block closes, the logger has been restored and the mock captures nothing. Always run test coroutines inside the `with patch(...)` block.
