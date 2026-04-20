# TUI gotchas

High-value pitfalls worth checking before editing tricky TUI code.

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
- **`_ENGINES` in drawille_overlay is class refs, not instances**. After v2, `_ENGINES` is `dict[str, type]`. `_get_engine()` caches instance in `_current_engine_instance`. Tests must call `engine_cls()` to get an instance — do NOT iterate `_ENGINES` as instances.

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

- If an overlay needs printable key handling, disable the input while it is
  active so input does not consume those keys first.
- Hidden focused widgets can still swallow scroll or key events. Dismiss paths
  may need explicit focus handoff.
- Overlay stacking is centralized in `app.py`. Avoid one-off dismiss logic in
  widgets unless the app-level policy changes too.
- Debounced overlay callbacks must be cancelled in dismiss/teardown paths.
- Hidden `display: none` parents can suppress worker delivery in tests. Check
  visibility lifecycle before debugging a "worker never returned" failure.

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
- Fix: time each subscriber callback individually. When total > 16ms, log slowest sub ID + ms. Example: `(slowest sub#0: 510ms)` → points at drawille overlay at sub_id=0.

**`_refresh_live_response_metrics` called from both `_tick_spinner` (10Hz) and `_tick_duration` (1Hz):**
- Has early return when `_response_metrics_active` is False — safe during idle. But during streaming, 10Hz of `query_one(OutputPanel)` + `msg.set_response_metrics()` is redundant. Acceptable for now since total path is ~1ms.

## Small but expensive traps

- `len(log.lines)`, not `log.line_count`
- `await pilot.pause()` after message posts or reactive churn
- Input placeholder owns spinner text; sibling spinner widgets cause layout churn
- ResponseFlow changes often need both unit tests and streaming integration checks
- `ToolsScreen._apply_filter` is async — always `await` it

## CSS and layer system traps

**Gotcha: `layer: overlay` in DEFAULT_CSS silently kills HermesApp.on_mount**
If any widget class is defined (imported) with `layer: overlay` in its `DEFAULT_CSS` BEFORE `app.py` completes its import chain, Textual's CSS compilation is corrupted and `on_mount` never fires. The symptom is `AttributeError: 'HermesApp' object has no attribute '_anim_clock_h'` in `on_unmount`.

Fix: **never put `layer: overlay` in `DEFAULT_CSS`**. Instead, declare it in `hermes.tcss` only. Structural CSS that references Textual's layer system belongs in `hermes.tcss`, not in widget `DEFAULT_CSS`. Same rule applies to `position: absolute` — put it in `hermes.tcss` alongside `layer: overlay`.

Also applies to CSS variables (`$accent`, `$surface-darken-2` etc) — do NOT use `$var` references in `DEFAULT_CSS` either; they also cause silent CSS parse failures at class-definition time.

**Gotcha: overlay widget needs `position: absolute` in hermes.tcss for offset to be screen-absolute**
Without `position: absolute`, a widget's `offset` CSS is relative to its normal layout-flow position, not the screen origin. Symptom: `self.styles.offset = (tw-w-2, 1)` in `_apply_size_position` appears to have no effect — widget stays at its flow position offset by those amounts. Fix: add `position: absolute` to the widget's rule in `hermes.tcss` (next to `layer: overlay`). Both must be in `hermes.tcss` — not `DEFAULT_CSS`.

**Gotcha: `query_one(WidgetType)` in app methods is fragile — prefer `query_one("#id", Type)`**
`query_one(DrawilleOverlay)` can raise `NoMatches` even when the widget is mounted if the class object differs (import aliasing, hot-reload edge cases). Use `query_one("#drawille-overlay", DrawilleOverlay)` for reliability. When the query is the first line of a toggle/hide handler and is wrapped in `except Exception: pass`, a silent miss means the handler does nothing. Always separate the query guard (`except Exception: return`) from the operation body so operation errors surface.

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
Functions like `shimmer_text`, `DrawilleOverlay._render_multi_color`, and
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
`lerp_color_rgb(c1_rgb, c2_rgb, t)` for pre-parsed tuples (used in drawille
overlay and completion shimmer). Cache is bounded at 256 entries.

**Imports inside hot-path callbacks.**
`from hermes_cli.tui.animation import shimmer_text` and
`from textual.content import Content` inside `_tick_spinner` ran on every
100ms tick. Python's import cache makes this ~0.01ms but still wasteful —
hoist to module level.

**`AnimationClock.tick` per-subscriber timing for spike diagnosis.**
When `anim_clock.tick` exceeds 16ms, log which subscriber was slowest:
`(slowest sub#N: Xms)`. Subscriber IDs are assigned at `subscribe()` time.
Drawille overlay = typically sub#0 (divisor=1, 15Hz). PulseMixin = sub#0
if subscribed before drawille. To find mapping: search for
`clock.subscribe(DIVISOR, ...)` across `widgets.py`, `drawille_overlay.py`,
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

## When to expand this file

Add an entry only if it is:

- easy to regress,
- expensive to rediscover,
- specific to Textual or hermes-agent TUI behavior,
- and short enough to scan during active work.
