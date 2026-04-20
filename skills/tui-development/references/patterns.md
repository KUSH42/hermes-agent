# TUI patterns

Use these patterns when changing widgets, output flow, overlays, theming, or tests.

## Widget rules

- Pick one rendering model per widget:
  `compose()` for composite widgets or `render()` for leaf widgets.
- `Widget.render()` should return `Text`, another renderable, or `RenderResult`
  content. Plain `str` is literal text, not Rich markup.
- Structural properties belong in `DEFAULT_CSS`. Visual styling belongs in
  `hermes.tcss`.
- `query_one(...)` is normal access pattern. Guard teardown paths with
  `NoMatches` handling or `_safe_widget_call`.
- Avoid caching direct widget refs on `HermesApp` when a query is cheap and
  clearer.

## COMPONENT_CLASSES and component parts

Every new widget that ships visual chrome must declare `COMPONENT_CLASSES` so
skins can target sub-elements without inheriting implementation details.

```python
class ToolBlock(Widget):
    COMPONENT_CLASSES = {
        "tool-block--header",
        "tool-block--body",
        "tool-block--status-icon",
    }
```

Rules:

- Name component classes `{widget-kebab}--{part}` (double dash, all lowercase).
- Add matching selectors to `hermes.tcss` with `$surface` / `$panel` vars, not
  raw hex.
- `DEFAULT_CSS` handles structure (height, layout). `hermes.tcss` handles color.
- Skin overrides target these classes directly — no `!important` ever needed.
- If a component class changes name or is removed, grep `hermes.tcss` and any
  skin `.tcss` files for uses before deleting.

## Reactive patterns

Prefer `@on` / `@watch` over manual state-polling loops.

**`@watch`** — fires when a reactive changes value:

```python
status: reactive[str] = reactive("")

def watch_status(self, value: str) -> None:
    self.query_one("#status-label", Label).update(value)
```

- Keep watch handlers cheap: update a label or toggle CSS class only.
- Never do I/O, subprocess, or CSS reload inside a watcher.
- If the watch handler must do async work, post a message instead and handle in
  `@on`.

**`@on`** — event handler registered via decorator (preferred over `on_*`
methods for widgets that handle the same event from multiple sources):

```python
@on(Button.Pressed, "#confirm-btn")
def _confirm(self, event: Button.Pressed) -> None:
    self.post_message(ConfirmAction())
```

- Use the CSS-selector second argument to avoid `if event.button.id == ...`
  branches.
- `@on` handlers run on the app thread; keep them non-blocking.
- For high-rate events (key, scroll, tick), throttle with a debounce counter or
  delegate heavy work via `run_worker`.

## Worker patterns

Use `self.run_worker(coro, exclusive=True)` for I/O, parsing, or subprocess
work that must stay off the event loop.

```python
@work(exclusive=True, thread=False)
async def _load_preview(self, path: str) -> None:
    content = await anyio.Path(path).read_text()
    self.post_message(PreviewReady(content))
```

- `thread=False` (default): async worker, runs on event-loop executor but does
  not block it when awaiting.
- `thread=True`: sync-blocking work that must run on a thread pool (e.g.,
  `subprocess.run`, blocking file reads).
- `exclusive=True`: cancels any in-flight worker of the same name before
  launching. Use for preview/debounce patterns.
- Deliver results via `self.post_message(...)` — never mutate DOM directly
  inside a worker.
- Do not call `app.call_from_thread` from an async `@work` worker; it is
  already on the event loop. Reserve it for true background threads.
- **`ResponseFlowEngine` is NOT a Widget** — `@work` is unavailable on it.
  Use `self._panel.app.run_worker(fn, thread=True)` + `call_from_thread` for
  async off-loop work (e.g., `_flush_math_block`).

## Layout rules

- Use fractional widths (`1fr`) for columns that should share available space.
  Never hardcode pixel widths for primary content panes.
- Use `min-width` and `min-height` guards on any panel that can shrink to zero
  (e.g., completion list, overlay). Prevents zero-height render artifacts.
- Overlay layers: set `layer: overlay` in TCSS and `offset` in `DEFAULT_CSS`.
  Use `dock: bottom` / `dock: top` for persistent chrome (status bar, bottom
  bar).
- Terminal resize resilience: test at 80×24, 120×40, and 200×50 minimum.
  Fractional units handle this; hard pixel widths do not.
- Inner panels must never own horizontal scroll. Only the top-level container
  or `OutputPanel` owns scroll axes.
- `height: 1fr` on a child of a `height: auto` parent creates a circular
  dependency. Textual resolves it to 0 or extreme values — omit `height` or use
  a fixed value for accent/sidebar columns in `height: auto` containers.

## Keyboard binding conventions

Every user-visible feature must have a keybinding. Declare in `BINDINGS`:

```python
BINDINGS = [
    Binding("ctrl+f", "search", "Search history", priority=True),
    Binding("escape", "dismiss", "Close", show=False),
]
```

Rules:

- `priority=True` only for bindings that must fire even when focus is inside
  an input (e.g., overlay dismiss, global search).
- `show=False` for secondary or obvious bindings (escape, arrows).
- Group bindings: navigation (arrows/tab), actions (enter/ctrl+*), dismiss
  (escape/ctrl+c). Document in footer or tooltip, not in code comments.
- New bindings must not collide with Textual defaults or existing app bindings.
  Check `HermesApp.BINDINGS` and `HermesInput.BINDINGS` before adding.
- Vim-style single-letter bindings are only acceptable in non-input focus
  contexts (e.g., browse overlay with `can_focus=True`).

## Validation and instrumentation

For any change to a hot path (output streaming, scroll, timer tick, completion
render), include a latency check:

```python
import time
t0 = time.perf_counter()
# ... operation ...
elapsed = time.perf_counter() - t0
assert elapsed < 0.016, f"frame budget exceeded: {elapsed*1000:.1f}ms"
```

Devtools checks to run after hot-path changes:

- `textual console` — watch for repeated `Refresh` or `Layout` events on
  widgets that should be static.
- `TEXTUAL_LOG=1` — captures mount/unmount churn; look for widgets toggling
  more than once per event.
- `show_layout=True` in `run_test()` — confirms no unexpected reflow on
  scroll or streaming.

Stress-test scenarios:

- Stream 500 lines at 10ms intervals while resizing terminal.
- Open completion overlay with 200 candidates and scroll rapidly.
- Trigger 50 tool blocks in sequence and confirm scroll stays at bottom.
- Toggle history search overlay 20× rapidly without leaking focus.

## Thread and queue rules

- Agent/background threads:
  use `app.call_from_thread(...)`, `app.write_output(...)`, or
  `post_message(...)`.
- Event-loop callbacks:
  mutate directly; `call_from_thread` from app thread is wrong.
- High-rate output:
  prefer queue or purpose-built app methods over repeated DOM mutation.
- Worker results:
  prefer `post_message(...)` from `@work` workers when delivery belongs to the
  widget itself.

Concrete patterns:

- scalar reactive update:
  `app.call_from_thread(setattr, app, "status_model", value)`
- DOM/widget method from worker thread:
  `app.call_from_thread(_safe_widget_call, app, WidgetType, "method", *args)`
- preview/path-search worker result:
  `self.post_message(...)`

## Output stack rules

- New visible output mounts before `output.query_one(ThinkingWidget)`.
- Do not place content between `ThinkingWidget` and `LiveLineWidget`.
- Inner content widgets should use hidden overflow. OutputPanel owns vertical
  scrolling.
- `watch_agent_running(False)` is the canonical turn teardown path. Do not use
  `flush_output()` as a replacement for turn cleanup.
- Use the streaming/output APIs that match the change you are making:
  `app.write_output(...)`,
  `open_streaming_tool_block(...)`, `append_streaming_line(...)`,
  `close_streaming_tool_block(id, duration, is_error=False, summary=None)`.

Important nuance:

- `flush_output()` still exists and is exercised in tests for queue/sentinel
  behavior.
- Real turn-end cleanup in production is still driven by
  `watch_agent_running(False)`.

## Response flow rules

- `ResponseFlowEngine` owns `StreamingCodeBlock` lifecycle, not `MessagePanel`
  directly. One engine exists per `MessagePanel`.
- Read `response_flow.py` before changing markdown heuristics, source-like
  detection, fenced-code behavior, or prose/code ordering.
- If you touch line routing, run `tests/tui/test_response_flow.py` and at least
  one streaming integration path.

**Chunk streaming API:**
- `feed(chunk)` accumulates `_partial` and routes to `StreamingCodeBlock.feed_partial()`
  for in-code states. **Never** calls `process_line()` (single-clock invariant: only
  `_commit_lines()` drives `process_line`).
- `flush()` drains `_partial` via `pending = self._partial; _clear_partial_preview();
  process_line(pending)`.
- `flush_live()` sets `engine._partial = live._buf` then calls `engine.flush()` —
  NOT `engine.process_line(live._buf)` (double-processing bug).

**Block math (`$$`) checked BEFORE fence detection** in `process_line()` NORMAL block —
`$$` would otherwise collide with triple-backtick fence regex.

**`_apply_inline_math(raw)` guards:** only substitutes when line contains `\`, `^`, or `_`
— prevents false positives on `$100` or `$HOME`.

**InlineCodeFence detection:** `_code_fence_buffer` accumulates lines matching
`^\s*\d{1,3}\s*\|\s+\S`. Flushes as `InlineCodeFence` widget only when ≥ 2 consecutive
numbered lines match. Single-line match → normal prose. Buffer flushed on paragraph break.

**ANSI literal replacement:** targets literal string `\x1b[...]` (backslash-x-1-b in text),
NOT actual ESC bytes (0x1B). Regex: `r"\\x1b\[[0-9;?]*[a-zA-Z]"`. Check for `"\\x1b"`
substring before applying (fast gate). Applied in `_commit_prose_line` only.

## Overlay protocol

All timed overlays use typed state from `state.py`, not raw dict payloads.

- Choice overlays:
  `ChoiceOverlayState`
- Secret-input overlays:
  `SecretOverlayState`
- Destructive undo/rollback path:
  `UndoOverlayState`

`CountdownMixin` expects:

- `_state_attr`
- `_timeout_response`
- `_countdown_prefix`
- a countdown widget with matching `#{prefix}-countdown`

When opening one overlay above another, preserve existing stacking rules in
`app.py` instead of inventing new local dismiss logic.

Overlay expectations:

- active overlays generally disable the input so printable keys reach app-level
  handlers
- stacking and dismissal policy lives in `HermesApp.watch_*_state(...)`
- countdown behavior belongs in `CountdownMixin`, not duplicated per overlay

**Info overlay wire-up pattern** for new slash commands:
1. Add handler in `_handle_tui_command` (returns `True` if handled)
2. Call `_dismiss_all_info_overlays()` before opening
3. Add the overlay class to `_dismiss_all_info_overlays()`
4. Handle escape in `on_key` Priority -2 block

## Theme and CSS rules

- Use theme variables first; do not scatter raw hex values unless the value is
  a tightly-scoped fallback.
- New runtime-overridable vars must be declared in `hermes.tcss` before use.
- If a value must be skin-overridable at runtime, wire it through
  `theme_manager.py` and `skin_loader.py` instead of only hardcoding TCSS.
- Respect `$app-bg` for base chrome. Elevated overlays/panels may intentionally
  use `$panel`, `$surface`, or `$surface-lighten-1`.
- If you change theme application or hot reload, verify both the live app path
  and tests covering `ThemeManager`.
- **`$text-muted 20%` opacity syntax fails in TCSS.** Only Textual native
  design tokens (`$primary`, `$accent`, `$success`, `$error`, `$warning`) support
  the `$VAR N%` opacity modifier. Use `$primary 15%` for dim neutral, or a raw
  hex color. `$text-muted 20%` silently prevents compose from completing.

### Keeping skin files in sync

When you add a new `component_var` key to `COMPONENT_VAR_DEFAULTS` in
`theme_manager.py`, update **all three** of these in the same patch:

1. `theme_manager.py` — `COMPONENT_VAR_DEFAULTS` dict (the canonical default)
2. `hermes.tcss` — declaration so the var is resolved at CSS parse time
3. `skins/matrix.yaml` — `component_vars` section with a matrix-appropriate value
4. `docs/skins/example-skin.yaml` — add a commented-out entry with description

Failing to update the skin files means the new var silently falls back to the
`COMPONENT_VAR_DEFAULTS` value regardless of which skin is active.

Theme specifics worth remembering:

- `get_css_variables()` is guarded because Textual may call it during
  `super().__init__()`.
- `rule-bg-color` falls back through `app-bg` in rule rendering code.
- `Screen` and `HermesApp` both need `background: $app-bg` for consistent
  transparent-widget inheritance.
- `VirtualCompletionList` intentionally uses elevated surface styling, not flat
  app background.

## Perf triage

Check lag in this order:

1. Periodic work on app thread: timers, watchers, `render()`, `render_line()`.
2. Blocking work on app thread: file I/O, parsing, subprocess waits,
   `refresh_css()`.
3. DOM churn: repeated mount/remove/query cycles.
4. Scroll path: nested scroll owners, focus churn, missing `scroll_end`.
5. Existing perf probes and targeted tests before broader refactors.

Keep these paths cheap:

- `_tick_spinner()`
- `_tick_duration()`
- output queue consumption
- scroll watchers
- completion list viewport rendering
- theme hot-reload path

### AnimationClock spike diagnosis

When `anim_clock.tick` log shows spikes (145–514ms), add per-subscriber
timing inside `AnimationClock.tick()`:

```python
for sub_id, (divisor, callback) in list(self._subscribers.items()):
    if self._tick % divisor == 0:
        _s0 = time.perf_counter()
        callback()
        _s_ms = (time.perf_counter() - _s0) * 1000
        # track slowest
```

Log `(slowest sub#N: Xms)` when total exceeds budget. Map sub IDs by
searching `clock.subscribe(...)` calls across the codebase.

### Per-character coloring optimization pattern

When a hot-path function iterates per-character and creates individual
`Style`/`Segment` objects:

1. Pre-compute the color for each position into a flat list.
2. Scan for consecutive same-color runs.
3. Emit one `Style`/`Segment` per run, not per character.

This reduces Rich Text span count from N to ~N/colors, cutting the
overhead that `Text.stylize()` and `Content.from_rich_text()` incur.

Apply to: `shimmer_text`, `_render_multi_color`, `_render_shimmer_row`.

Specific hot-path guidance:

- no filesystem polling or YAML/JSON parse work inside timer/watcher paths
- avoid repeated DOM remove/mount churn in debounce or per-chunk logic
- treat `refresh_css()` as expensive enough to keep off steady-state hot paths

## Testing workflow

- Use `async def` tests with `app.run_test(...)`.
- Prefer focused module tests first, then cross-widget tests for lifecycle
  changes.
- If a change touches output flow, also consider scroll and turn-lifecycle
  tests.
- If a change touches overlays, run overlay, interrupt, and turn-lifecycle
  coverage.
- If a change touches theme logic, run theme-manager and CSS-related tests.

Testing specifics:

- TUI tests are normally headless and often need `await pilot.pause()` after
  posting messages or changing reactives.
- `pilot.resize_terminal(...)` is async and must be awaited.
- `len(log.lines)` is the reliable RichLog line-count check.
- Some headless scroll tests patch `max_scroll_y` with `PropertyMock`; do not
  assume natural overflow exists in tests.
- If cwd-sensitive logic is involved, remember `TERMINAL_CWD` can override
  `os.getcwd()`.
- **Browse `a`/`A` key tests require ToolPanels**, not bare ToolBlocks. Use
  `mount_tool_block()` (creates ToolPanel + ToolBlock). Bare `_mount_block()` is
  unaffected by the ToolPanel-querying `a`/`A` handler.
- Tests asserting a specific duration string (e.g., `"2.3s"`) will fail because
  `_on_stream_complete` computes actual elapsed from `_stream_started_at`. Assert
  `isinstance(block._header._duration, str)` instead.

Useful commands:

```bash
source venv/bin/activate
python -m pytest tests/tui/test_response_flow.py -q
python -m pytest tests/tui/test_tool_blocks.py tests/tui/test_streaming_tool_block.py -q
python -m pytest tests/tui/test_scroll_integration.py tests/tui/test_turn_lifecycle.py -q
python -m pytest tests/tui/test_overlays.py tests/tui/test_overlay_design.py -q
python -m pytest tests/tui/test_status_widgets.py tests/tui/test_history_search.py -q
python -m pytest tests/cli/test_reasoning_tui_bridge.py -q
```

For broader TUI runs, clear the repo's xdist addopts:

```bash
source venv/bin/activate
python -m pytest -o addopts='' tests/tui/ -q
```

## HermesInput (TextArea base)

`HermesInput` extends `TextArea` (not `Input`). Constructor uses
`compact=True`, `tab_behavior="focus"`, `show_line_numbers=False`,
`highlight_cursor_line=False`, `max_checkpoints=50`.

**Key patterns:**

- `_on_key` (async) intercepts keys TextArea would consume. Call
  `event.prevent_default()` to block default and `event.stop()` to stop
  propagation. Always `await super()._on_key(event)` at the end.
- `on_text_area_changed` replaces `watch_value`/`watch_cursor_position`.
  Fires asynchronously — cursor is already correct when it fires. Set
  `_sanitizing = True` during sanitize-then-`load_text` to prevent re-entry.
- Ghost text: set `self.suggestion = text` (TextArea reactive). Clear with
  `self.suggestion = ""`. Only set when cursor is at end of last row.
- `placeholder` is now `Content | str` — tests must use
  `ph.plain if hasattr(ph, 'plain') else str(ph)` for substring checks.
- `_push_undo_snapshot()` is removed — TextArea manages undo via
  `max_checkpoints`. Use `load_text("")` in `clear()` to reset history.
- File-drop bridge: `_location_to_flat(loc)` converts `(row, col)` to
  flat int; `replace_flat(start, end, text)` replaces a flat-int range.
- Paste handler is `async def _on_paste` — call `await super()._on_paste(event)`.
- Escape priority: check `HistorySearchOverlay.--visible` before intercepting
  escape for CompletionOverlay — HistorySearch BINDINGS have `priority=True`.
- TCSS component classes: `.text-area--cursor`, `.text-area--selection`,
  `.text-area--placeholder`, `.text-area--suggestion`.

## ToolPanel — binary collapse

**Architecture invariant:** `watch_collapsed` hides `block._body`
(ToolBodyContainer), NOT BodyPane. BodyPane always stays visible so ToolHeader
(inside BodyPane → ToolBlock) remains clickable for expand. Hiding BodyPane
would hide ToolHeader — second click to expand becomes impossible.

```python
def watch_collapsed(self, old: bool, new: bool) -> None:
    body_container = getattr(self._block, "_body", None)
    if body_container is not None:
        body_container.styles.display = "none" if new else "block"
    fp = self._footer_pane
    if fp is None:
        return
    want_fp = (not new) and self._has_footer_content()
    if fp.display != want_fp:
        fp.styles.display = "block" if want_fp else "none"
```

CSS `ToolPanel ToolBodyContainer { display: block; }` in `hermes.tcss` ensures
ToolBodyContainer starts visible (overrides DEFAULT_CSS `display: none`). Python
`styles.display` inline overrides the CSS rule when collapsing.

**Toggle delegation:** When `header._panel` is set (block inside ToolPanel),
`ToolBlock.toggle()` delegates to `panel.action_toggle_collapse()` and returns.
`_body.has_class("expanded")` is no longer set on in-panel blocks.

**Error promotion:** `_apply_complete_auto_collapse()` forces `collapsed = False`
when `rs.is_error`. Errors always expand regardless of line count threshold.

**Auto-collapse threshold:** `CategoryDefaults.default_collapsed_lines`. When
`spec.primary_result == "diff"`, threshold is 20 lines. Never auto-collapses at
mount — only fires in `set_result_summary_v4()`.

**Test patterns:**
```python
# Use panel.collapsed, not block._body.has_class("expanded")
assert panel.collapsed is True
assert block._body.styles.display == "none"
assert panel.query_one(BodyPane).styles.display != "none"  # BodyPane always visible
```

## ToolPanel — ToolSpec and ToolCategory

`tool_category.py` owns all tool classification, icon resolution, and MCP
server metadata. **Always call `spec_for()` — never duplicate classification logic.**

Key exports: `ToolSpec` (frozen dataclass), `ToolCategory` enum
(`FILE/SHELL/CODE/SEARCH/WEB/AGENT/MCP/UNKNOWN`), `CategoryDefaults`,
`MCPServerInfo`, `spec_for(name, args, schema)`, `resolve_icon_final(spec, nerd_font)`,
`register_tool(spec, overwrite)`, `register_mcp_server(server, ...)`.

**ToolSpec lookup chain:**
```
spec_for(name, args, schema)
    1. TOOL_REGISTRY.get(name)       ← explicit entry always wins (allows overrides)
    2. _parse_mcp_name(name)          ← recurse on inner + _derive_mcp_spec (ephemeral)
    3. _classify_args(args)           ← live arg keys from invocation
    4. _classify_by_schema(schema)    ← JSON schema properties
    5. ToolSpec(name=name, UNKNOWN)   ← fallback
```

**Classification arg key sets (exact key names only):**
- SHELL: `{"command", "cmd"}`
- CODE: `{"code"}`
- SEARCH: `{"query", "pattern"}`
- WEB: `{"url"}`
- AGENT: `{"thought", "description", "task"}`
- FILE: `{"path", "file", "filename"}`

Extra keys like `"search_query"`, `"file_path"`, `"shell"` are NOT in these sets.

**`_derive_mcp_spec` result must NOT be written to TOOL_REGISTRY.** MCP-derived
specs are ephemeral — computed on demand. Writing them would shadow explicit
overrides registered later.

**Thread-safe registry access:** `register_tool()` and `register_mcp_server()`
acquire `_REGISTRY_LOCK`. Plain `TOOL_REGISTRY.get()` reads are safe without lock
(CPython GIL, atomic dict read).

**Config flag guard pattern** (safe in `render()` hot paths):
```python
def _tool_panel_v4_enabled() -> bool:
    try:
        from hermes_cli.config import read_raw_config
        return bool(read_raw_config().get("display", {}).get("tool_panel_v4", False))
    except Exception:
        return False
```

## ToolPanel — ResultSummaryV4 pipeline

`ResultSummaryV4` frozen dataclass (`slots=True`): `primary`, `exit_code`, `chips`,
`stderr_tail`, `actions`, `artifacts`, `is_error`, `error_kind`. Collection fields
are `tuple[...]` — **never use lists.**

**`parse(ctx)` dispatch is category-keyed:**
```python
_V4_PARSERS = {"file": file_result_v4, "shell": shell_result_v4, ...}
cat = ctx.spec.category.value  # "file" not "FILE" (ToolCategory.value is lowercase)
```
Fallback: `generic_result_v4` for unknown categories.

**`ParseContext` input struct:**
```python
ParseContext(complete: ToolComplete, start: ToolStart, spec: ToolSpec)
```
`ToolComplete.raw_result` is `object` (str | dict). Always call `_raw_str(raw)` before
string operations. Never assume it's a str.

**`ToolPanel.set_result_summary_v4(summary)` wiring:**
```
→ block._header._primary_hero = summary.primary
→ _footer_pane.update_summary_v4(summary)
→ _apply_complete_auto_collapse()  [error → force expand; else → check threshold]
→ footer visibility: show when chips/stderr/actions/artifacts present AND not collapsed
```
Access header via `getattr(self._block, "_header", None)` — `_block` may be any Widget.

**`"text"` is NOT a valid `primary_result`.** Valid set:
`['bytes', 'diff', 'done', 'lines', 'matches', 'none', 'results', 'status']`.
FILE read → `"lines"` or `"bytes"`. FILE write → `"done"`. MCP → `"results"`.

**Payload cap:** `Action.payload` → `_truncate_payload(text)` → `_PAYLOAD_CAP = 65536`.
Set `payload_truncated=True` if truncated.

## ToolPanel — streaming microcopy

`streaming_microcopy.py` — per-category progress text shown in `.--microcopy`
Static inside `ToolBodyContainer`.

**Always compose, never dynamically mount.** The `.--microcopy` Static is in the DOM
from `compose()` with `display: none`. Shown by adding `--active` class when
`elapsed_s >= 0.5`. Dynamic mounting mid-stream risks the `before=` anchor resolution
gotcha (sibling mounts via `self.mount(after=self)` land in wrong container).

**STB caches the ref on mount:**
```python
self._microcopy_widget = self._body.query_one(".--microcopy")
```

**MCP provenance line persists after `complete()`.** `_clear_microcopy_on_complete()`
checks `spec.category == ToolCategory.MCP` and skips. All other categories: remove
`--active` class, clear text.

**Adaptive flush timer — stop + restart, not modify.** Textual timer intervals are
immutable:
```python
self._render_timer.stop()
self._render_timer = self.set_interval(1/hz, self._flush_pending)
```
Track `_flush_slow: bool` to avoid stop/restart on every tick. Reset to 60Hz on any
`append_line()` call; drop to 10Hz after 2s idle.

**Per-category microcopy summary:**
- SHELL / CODE: `▸ N lines · NkB`
- FILE read: `▸ N lines` or `▸ NkB`
- FILE write: `▸ writing…`
- WEB: `▸ fetching…`
- MCP: `▸ mcp · {server} server` (persists after complete)
- AGENT: `▸ thinking…` (static, no counters)
- UNKNOWN: `▸ N lines`

## ToolGroup widget

**DOM structure:**
```
ToolGroup
├── GroupHeader     (1 line; render() → Text; not focusable)
└── GroupBody       (height auto; padding-left 2; vertical layout)
    ├── ToolPanel   (child 1)
    └── ToolPanel   (child 2+)
```

**Widget grouping is always active** (feature flag `display.tool_group_widget`
deleted after v4 graduation). CSS-only grouping path removed.

**`_group_reparent_worker` guards (in order):**
1. `_find_rule_match` returns None → skip
2. `existing_panel` is streaming (`_is_streaming`) → skip
3. Either panel not attached → skip
4. `_get_tool_group(existing)` is not None → `_do_append_to_group` (3b path)
5. Else → `_do_apply_group_widget` (3c path: create new group)

Exceptions swallowed silently (CSS classes already applied as fallback).

**`recompute_aggregate` N>20 guard:** skips recompute when `len(children) > 20`
to avoid O(N²) walk. Aggregate may be stale for large groups.

**Browse mode integration:** `_rebuild_browse_anchors` adds 1 TOOL_BLOCK anchor
per ToolGroup with label `"Group▾/▸ · {summary} (N)"`. ToolHeaders inside a
collapsed group are skipped; inside an expanded group they're added individually.

**`ToolGroup.on_tool_panel_completed`:** stops the event (no bubble past group)
and calls `recompute_aggregate()`. Fires when any child ToolPanel posts
`ToolPanel.Completed`.

## ToolsOverlay (/tools timeline)

`ToolsScreen(Screen)` in `tools_overlay.py` — pushed via `push_screen`. This is
the **first use of push_screen / pop_screen** in this repo.

**Key design:** snapshot is frozen at construction — no live reactives inside the
Screen. Snapshot taken at activation: `app.current_turn_tool_calls()`.

**Activation paths:**
- `/tools` command in `_handle_tui_command`
- `T` key in browse mode `on_key` (before printable catch-all)

**Screen vs Widget overlay differences:**
- Owns focus stack completely — no `inp.disabled=True` hack needed.
- `_dismiss_all_info_overlays()` does NOT affect it (no `--visible` CSS class).
- Dismissed only via `self.app.pop_screen()` in `action_dismiss_overlay`.
- Escape is `priority=True` in BINDINGS; `action_dismiss_overlay` is `async def`.

**`_apply_filter` / `_rebuild` must be `async def`** — they call
`await listview.clear()` / `await listview.append(...)`. A bare call without
`await` silently discards the coroutine; ListView never repopulates.

**Double-escape to dismiss:** First Escape closes filter input (if visible);
second Escape dismisses the overlay via BINDINGS.

**Timer cancellation in `on_unmount`:**
```python
def on_unmount(self):
    if self._stale_timer is not None:
        self._stale_timer.stop()
```
Without this, `_update_staleness_pip` fires after Screen unmount → NoMatches.

**Duplicate panel ID guard:** if a panel with `id="tool-{tool_call_id}"` already
exists, `panel_id=None` prevents Textual `DuplicateIds`. Jump-to-panel from the
overlay may not resolve for duplicate IDs — acceptable.

## header_label_v4 and duration format

`header_label_v4(spec, args, full_label, full_path, available, accent_color)` in
`tool_blocks.py` — returns `rich.text.Text`.

- `primary_arg="path"` → path rendering with optional `:{start}-{end}` line range from `args`
- `primary_arg="command"` → italic; `$` prefix only when `category == SHELL` AND `accent_color` non-empty (both gates required)
- `primary_arg="query"` → `bold italic` in `"quotes"`
- `primary_arg="url"` → dim scheme + bold host + dim path
- `primary_arg` in `{"thought", "description", "task"}` → italic dim, max 40 cells
- `primary_arg=None` → plain fallback

**`_format_duration_v4(elapsed_ms: float) -> str`:**
```
< 50 ms  →  ""          (omit entirely)
50–5000  →  "NNNms"     (integer ms)
> 5000   →  "N.Ns"      (one decimal second)
```

`ToolHeader.render()` always calls `_render_v4()` — v2 code path removed after
graduation. `_format_duration_v4` is always active.

**`ToolHeader._is_complete: bool`** — set True in `_on_stream_complete` when
`_spinner_char = None`. Render check: `elif self._is_complete or self._duration:` →
green icon. Ensures icon settles to green/red even when duration rounds to `""`.

**Hero chip:** `_primary_hero: str | None` set by `set_result_summary_v4()`. Displayed
in `_render_v4()` tail. Style: `"bold red"` on error, `"dim green"` on success.

**Header chips:** `_header_chips: list[tuple[str, str]]` — up to 2 non-redundant chips
promoted from `summary.chips`. MCP source chip (`mcp:server`) is the primary beneficiary.

## Browse mode patterns

**Browse anchors:** `BrowseAnchorType` enum (`TURN_START / CODE_BLOCK / TOOL_BLOCK`) +
`BrowseAnchor` dataclass in `app.py`. `_rebuild_browse_anchors()` walks
`OutputPanel.walk_children`.

**Key bindings (all active within browse mode):**
- `[` / `]` — any anchor (any type)
- `{` / `}` — CODE_BLOCK only
- `alt+up` / `alt+down` — TURN_START only
- `a` — expand all ToolPanels
- `A` — collapse all ToolPanels
- `T` — open ToolsOverlay (`ToolsScreen`)
- `m` / `M` — MEDIA anchors (prev/next)

**`a`/`A` handler queries ToolPanel, not ToolBlock:**
```python
elif key == "a":
    from hermes_cli.tui.tool_panel import ToolPanel as _TP
    for panel in self.query(_TP):
        if panel.collapsed:
            panel.action_toggle_collapse()
elif key == "A":
    from hermes_cli.tui.tool_panel import ToolPanel as _TP
    for panel in self.query(_TP):
        if not panel.collapsed:
            panel.action_toggle_collapse()
```

Bare ToolBlock mounts (no ToolPanel wrapper) are NOT affected by these handlers.

**`_browse_cursor` vs `browse_index` are SEPARATE state.** Tab path updates only
`browse_index`; `[`/`]` path updates only `_browse_cursor`. `_rebuild_browse_anchors`
always clamps (never resets) cursor — callers that want reset set `_browse_cursor=0`
first.

**Focus retry:** On unmounted widget, `_focus_anchor` rebuilds once and retries on
first same-type anchor (lowest index). `_retry=False` prevents recursion.

**`_browse_hint` reactive in StatusBar:** when non-empty, replaces default Tab hint
after position indicator.

**`StreamingCodeBlock` excluded while `_state == "STREAMING"`** from anchor list.

## Drawille overlay coloring

`DrawilleOverlay._tick()` has three coloring branches (highest priority first):

1. **`multi_color`** — N-stop per-character gradient across columns with
   sinusoidal hue-shift drift. Resolves colors in `watch_multi_color` /
   `on_mount`. Implemented in `_render_multi_color(frame_str, t)`.
2. **`gradient`** — row-based two-color lerp (`color` → `color_b`).
3. **solid** — single `_resolved_color` with optional fade-in lerp.

Multi-color config (YAML):
```yaml
multi_color: ["#00ff66", "#004422", "#0066ff"]
hue_shift_speed: 0.5   # 0 = static, ~2 = fast cycling
```

`hue_shift_speed` feeds `sin(t × speed) × 0.25` → gradient drifts ±25%
of canvas width. Colors mirror-fold at edges (no hard wrap jump).

`_resolved_multi_colors` is a pre-resolved `list[str]` of hex strings kept
in sync with `multi_color` reactive via `watch_multi_color`.

**`_ENGINES` is a `dict[str, type]` of class refs (not instances).** `_get_engine()`
caches the instance in `_current_engine_instance`; rebuilds on key change. Iterate
as `engine_cls()` in tests — not `engine_instance` directly.

**SDF crossfade warmup:** `_get_engine()` sdf_morph branch shows a braille warmup
engine (`sdf_warmup_engine`, default `"neural_pulse"`) until `baker.ready.is_set()`.
On ready edge, installs `CrossfadeEngine(warmup→SDF)`. After crossfade completes
(`progress >= 1.0`), returns pure `SDFMorphEngine`. PIL-broken degradation: warmup
runs forever.

## Startup text effect (TTE) params

`display.startup_text_effect` in `config.yaml`:

```yaml
display:
  startup_text_effect:
    enabled: true
    effect: matrix          # any key from tte_runner.EFFECT_MAP
    params:
      rain_time: 1          # effect-specific override (snake_case field name)
```

`params` keys map 1-to-1 to the effect's `effect_config` dataclass fields
(snake_case). `tte_runner._apply_effect_params` coerces and sets them via
`setattr(cfg, key, value)`. Unknown keys are printed and skipped; no crash.

Matrix effect duration key: `rain_time` (int, seconds, default 15).
Set `rain_time: 1` for a ~1 s startup splash.

`final_gradient_stops` is reserved — skip it in params; skin palette applies
automatically via `run_effect()` unless explicitly overridden.

This is a `config.yaml` key, **not** a skin YAML key.

## ExecuteCodeBlock patterns

`ExecuteCodeBlock(StreamingToolBlock)` in `execute_code_block.py` — two-section
body (CodeSection + OutputSection) with per-chunk code streaming.

**Lifecycle:**
```
GEN_START → feed_delta() → append_code_chars() → _emit_code_line()
TOOL_START → finalize_code(canonical_code)  # replaces per-line with rich.Syntax
EXEC_STREAMING → append_line() → OutputSection RichLog
COMPLETED → complete(duration, is_error)
```

**Key wiring in cli.py:**
- `_gen_blocks_by_idx: dict[int, ExecuteCodeBlock]` — populated at gen_start
- `_active_execute_blocks_by_idx: dict[int, ExecuteCodeBlock]` — kept alive during exec for late deltas
- Both cleared at tool_complete
- `tool_gen_args_delta_callback` fires `_on_tool_gen_args_delta(idx, name, delta, acc)`

**Per-chunk decode pipeline:**
`tc_delta.function.arguments` → `PartialJSONCodeExtractor.feed()` →
decoded Python chars → `CharacterPacer.feed()` → `append_code_chars()`

**finalize_code():** stops pacer, clears CodeSection RichLog, writes
`rich.Syntax(lines[1:], lexer="python")` via `log.write(syntax)` (not `mount()`).
Line 0 is shown in the header, so body starts at line 1.

**Header label:** line 0 of code (plain + syntax-highlighted `_label_rich: Text`).
Set via `_emit_code_line` and refreshed in `finalize_code` from canonical args.
`_compact_tail = True` on mount: natural flow (no right-align padding), duration
in normal color (not dim), duration after toggle affordance.

**Collapse threshold:** `len(_code_lines) + _total_received > 3` → collapsed.
`_header._line_count = 0` always (suppress "NL" display). User toggle during
streaming persists via `_user_toggled` flag.

**Duplicate-block guard:** `_on_tool_start` checks `tool_call_id in
tui._active_streaming_blocks` before creating a block. Fallback creates
`ExecuteCodeBlock` (not `StreamingToolBlock`) if `_gen_blocks_by_idx` is empty.

**ToolHeader._label_rich:** `Text | None` — when set, used in render instead of
plain `_label` string. Supports syntax-highlighted labels.

**ToolHeader._compact_tail:** `bool = False` — skips right-align padding, sets
`dur_style = ""` (normal). Duration appended after toggle affordance.

**Config:** `display.execute_code_typewriter_cps: 0` (0 = pass-through).

**Auto-collapse on error:** `complete(is_error=True)` always collapses the block
when `_user_toggled` is False. Never depends on line count.

**Chart display:** `complete(is_error=False)` calls `_try_mount_media()` to render
`MEDIA: /path` lines as inline kitty images (e.g., matplotlib charts).

**Duplicate output prevention:** `cli.py._on_tool_complete` captures
`_had_output_stream_cb = tool_call_id in self._stream_callback_tokens` BEFORE
popping the token. When True, only `_error` is fed (not `_output`) to avoid
re-feeding lines that the streaming callback already delivered live.

## Adjacent-mount pattern

When block B must appear directly after block A regardless of prose/reasoning
widgets appearing between them, use the adjacent-mount anchor pattern.

**`MessagePanel._adj_anchors: dict[str, Widget]`** — keyed by an anchor key.
Use `panel_id` (= `f"tool-{tool_call_id}"`) for tools that can be concurrent
so each invocation gets its own slot. Use a stable string key (e.g. `"web_search"`)
for tools that are always sequential.

Adding a new case requires only:
1. Register anchor: `self._adj_anchors[key] = panel` when opening A
2. Look up anchor: `anchor = self._adj_anchors.get(key)` when mounting B
3. Mount adjacent + advance: `self._adj_anchors[key] = panel`
4. Pass `parent_id` from caller (cli.py) so the right key is used for lookup

**Pattern:**
```python
# In open_streaming_tool_block / mount_tool_block:
anchor = self._adj_anchors.get("parent_tool_name")
if anchor is not None and anchor.parent is self:
    children = list(self.children)
    idx = children.index(anchor) + 1
    if idx < len(children):
        self.mount(panel, before=children[idx])
    else:
        self.mount(panel)
    self._adj_anchors["parent_tool_name"] = panel  # advance for next sibling
    self._schedule_group_widget(panel)
    _mounted_adj = True
```

**Registered keys:**
- `"web_search"` — stable key; set when `tool_name == "web_search"`; consumed by
  SEARCH-category tools (e.g. `search`). Sequential → stable key is safe.
- `f"tool-{tool_call_id}"` — per-invocation key for `execute_code`; set in
  `open_streaming_tool_block` using `panel_id`; consumed by `mount_tool_block` via
  `parent_id=f"tool-{tool_call_id}"` passed from `cli.py`. Concurrent-safe.

**Pitfall:** always call `_schedule_group_widget(panel)` after adjacent mount so
ToolGroup grouping sees the panel. Without it, the panel is silently skipped.
