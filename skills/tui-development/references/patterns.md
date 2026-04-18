# TUI patterns

Use these patterns when changing widgets, output flow, overlays, theming, or
tests.

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
  `close_streaming_tool_block(...)`.

Important nuance:

- `flush_output()` still exists and is exercised in tests for queue/sentinel
  behavior.
- Real turn-end cleanup in production is still driven by
  `watch_agent_running(False)`.

## Response flow rules

- `ResponseFlowEngine` owns `StreamingCodeBlock` lifecycle, not `MessagePanel`
  directly.
- One engine exists per `MessagePanel`.
- Read `response_flow.py` before changing markdown heuristics, source-like
  detection, fenced-code behavior, or prose/code ordering.
- If you touch line routing, run `tests/tui/test_response_flow.py` and at least
  one streaming integration path.

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

### Keeping skin files in sync

When you add a new `component_var` key to `COMPONENT_VAR_DEFAULTS` in
`theme_manager.py`, update **all three** of these in the same patch:

1. `theme_manager.py` — `COMPONENT_VAR_DEFAULTS` dict (the canonical default)
2. `hermes.tcss` — declaration so the var is resolved at CSS parse time
3. `skins/matrix.yaml` — `component_vars` section with a matrix-appropriate value
4. `docs/skins/example-skin.yaml` — add a commented-out entry with description

Failing to update the skin files means the new var silently falls back to the
`COMPONENT_VAR_DEFAULTS` value regardless of which skin is active, breaking
skin authors' ability to override it. The example skin doubles as the canonical
reference for skin authors — keep it complete.

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

**ToolHeader tail order:** `NL  ▾  duration` (toggle before duration).

**Config:** `display.execute_code_typewriter_cps: 0` (0 = pass-through).

## ToolPanel v3-A patterns

**ToolPanel compose structure** — `layout: horizontal` with inner vertical container:

```python
def compose(self) -> ComposeResult:
    self._accent = ToolAccent()
    self._args_pane = ArgsPane()
    self._body_pane = BodyPane(self._block, category=self._category)
    self._footer_pane = FooterPane()
    yield self._accent
    with _PanelContent():          # layout: vertical; width: 1fr
        yield self._args_pane
        yield self._body_pane
        yield self._footer_pane
```

Never index `panel.children` by position — use `panel.query_one(ArgsPane)` etc.

**ToolAccent state lifecycle:**

```python
# on_mount: streaming block → "streaming", static block → "ok"
if total_lines > 0:
    self._accent.state = "ok"
else:
    self._accent.state = "streaming"

# set_result_summary: completion outcome
self._accent.state = "error" if summary.is_error else "ok"
```

**ToolAccent state watch — add/remove_class (not set_classes):**

```python
def watch_state(self, old: str, new: str) -> None:
    if old:
        self.remove_class(f"-{old}")  # set_classes() would wipe position classes
    self.add_class(f"-{new}")
```

**CWD strip wiring** — flag set in `__init__` before any lines arrive:

```python
# ToolPanel.__init__:
from hermes_cli.tui.tool_category import ToolCategory
if self._category == ToolCategory.SHELL and hasattr(block, "_should_strip_cwd"):
    block._should_strip_cwd = True
```

`StreamingToolBlock.append_line` strips and discards empty CWD-only lines.
`complete()` appends dim `cwd: /path` line if `_detected_cwd` is set.

## ToolPanel v3-B patterns

**ToolPanel compose structure with ToolHeaderBar** — v3-B adds header row first in _PanelContent:

```python
def compose(self) -> ComposeResult:
    self._accent = ToolAccent()
    self._header_bar = ToolHeaderBar(label=self._tool_name)
    self._args_pane = ArgsPane()
    self._body_pane = BodyPane(self._block, category=self._category)
    self._footer_pane = FooterPane()
    yield self._accent
    with _PanelContent():
        yield self._header_bar   # ← NEW first child
        yield self._args_pane
        yield self._body_pane
        yield self._footer_pane
```

`_PanelContent.children[0]` is now `ToolHeaderBar`.

**ToolHeaderBar state sync** — mirror ToolAccent state changes:

```python
# on_mount + set_result_summary must both update header_bar and accent:
state = "streaming"  # or "ok" / "error"
if self._accent is not None:
    self._accent.state = state
if self._header_bar is not None:
    self._header_bar.set_state(state)
    self._header_bar.set_finished(self._completed_at)     # freezes timer
    self._header_bar.set_line_count(self._body_line_count())
```

**Chevron sync in watch_detail_level:**

```python
if self._header_bar is not None:
    self._header_bar.set_chevron(new)  # ▸ for L0/L1, ▾ for L2/L3
```

**ResultPill update via content classifier stub (Phase B: TEXT/EMPTY only):**

```python
from hermes_cli.tui.content_classifier import classify_content
result = classify_content(payload)  # returns ClassificationResult
self._header_bar.set_kind(result.kind)
# TEXT → pill hidden; all others → pill visible with correct class/label
```

**ToolPanelMini auto-select** — evaluated at `set_result_summary`, not mount:

```python
from hermes_cli.tui.tool_panel_mini import meets_mini_criteria, ToolPanelMini
if meets_mini_criteria(category, exit_code, line_count, stderr):
    mini = ToolPanelMini(source_panel=self, command=cmd, duration_s=dur)
    self.parent.mount(mini, after=self)
    self.display = False   # hide self, mini is the visible replacement
```

Expansion: `ToolPanelMini._expand()` calls `source_panel.display = True` then `self.remove()`.

**Semantic GroupHeader label** — `refresh_stats()` now calls semantic helpers:

```python
from hermes_cli.tui.tool_group import group_semantic_label, group_path_hint
label = group_semantic_label(members)      # e.g. "patch × 2" or "patch+diff"
hint  = group_path_hint(members)           # e.g. "widgets.py" or None
full  = f"{label} · {hint}" if hint else label
```

`group_semantic_label` deduplicates tool names; `count = len(members)` (all members).
`group_path_hint` returns common basename if all members share the same filename.

## ToolPanel v3-C patterns

**Selecting a renderer** — `pick_renderer()` from `body_renderers/__init__.py`:

```python
from hermes_cli.tui.body_renderers import pick_renderer
from hermes_cli.tui.tool_payload import ToolPayload, ResultKind

# SHELL always gets ShellOutputRenderer (unless EMPTY)
# confidence > 0.7 → specialized renderer
# else → FallbackRenderer
renderer_cls = pick_renderer(cls_result, payload)
renderer = renderer_cls(payload, cls_result)
widget = renderer.build_widget()   # returns Widget (CopyableRichLog or custom)
```

**Full classify_content()** — Phase C heuristic order (first match wins):
1. Empty/whitespace → EMPTY
2. Binary (>5% ASCII control chars) → BINARY
3. `---`/`+++`/`@@` at line start → DIFF
4. ≥ 3 lines with `\d+[:-]` prefix → SEARCH (+ query from args)
5. Starts with `{` or `[` and parseable → JSON
6. ≥ 3 lines, 85% consistent column count → TABLE
7. ≥ 2 log lines (timestamp or level token) → LOG
8. Starts with ` ``` ` or path arg ends in code extension → CODE
9. Default → TEXT

Cache key: `(output_raw, tool_name, arg_query)`. Clear in tests via `classify_content.cache_clear()`.

**Renderer swap in ToolPanel** — after classify, call `_maybe_swap_renderer`:

```python
# Non-TEXT, non-SHELL kinds trigger swap:
self._maybe_swap_renderer(cls_result, payload)

def _swap_renderer(self, renderer_cls, payload, cls_result):
    # imports inside method to avoid circular: tool_panel ← body_renderers ← tool_payload
    renderer = renderer_cls(payload, cls_result)
    new_widget = renderer.build_widget()
    self._body_pane.mount(new_widget)
    if old_block is not None and old_block.is_attached:
        old_block.remove()
    self._block = new_widget
    self._body_pane._block = new_widget
```

**InlineCodeFence detection in response_flow** — buffer lines matching `^\s*\d{1,3}\s*\|\s+\S`:

```python
# _code_fence_buffer accumulates consecutive numbered lines.
# When ≥ 2 accumulated and next line doesn't match: flush as InlineCodeFence widget.
# On paragraph break: flush buffer (< 2 → normal prose, ≥ 2 → InlineCodeFence).
```

**ANSI literal replacement** — replaces literal `\x1b[...]` strings (not actual ESC bytes):

```python
_LITERAL_ANSI_RE = re.compile(r"\\x1b\[[0-9;?]*[a-zA-Z]")
# Applies in _commit_prose_line ONLY if "\\x1b" substring present (fast gate).
# Result: \x1b[?1000h → [?1000h] rendered dim.
```

**VirtualSearchList** — Widget with `render_line(y) -> Strip` for large search results:

```python
# y is viewport-relative; use y + _scroll_offset for dataset index.
# _lines: list[Strip] built from full dataset; only viewport range accessed.
# Mounted by SearchRenderer.build_widget() when hit_count > 100.
```

## ToolPanel v3-D patterns

**InputSection visibility in watch_detail_level:**
```python
# Shown at L2+ for all categories except CODE (execute_code)
want_is = new >= 2 and InputSection.should_show(self._category)
if self._input_section is not None and self._input_section.display != want_is:
    self._input_section.styles.display = "block" if want_is else "none"
```

**Detail level CSS class tracking:**
```python
# In watch_detail_level — swap only the changed classes:
self.remove_class(f"-l{old}")
self.add_class(f"-l{new}")
# TCSS: ToolPanel.-l3 { background: $accent 8%; }
```

**space: collapse/restore toggle:**
```python
def action_toggle_l0_restore(self) -> None:
    self._mark_user_override()
    if self.detail_level == 0:
        self.detail_level = self._pre_collapse_level  # init to 2 in __init__
    else:
        self._pre_collapse_level = self.detail_level
        self.detail_level = 0
```

**force_renderer — Re-render as override:**
```python
def force_renderer(self, kind: ResultKind) -> None:
    self._forced_renderer_kind = kind  # stored before swap attempt (persists on failure)
    # imports inside method to avoid circular
    from hermes_cli.tui.body_renderers import pick_renderer
    from hermes_cli.tui.tool_payload import ToolPayload, ClassificationResult
    payload = ToolPayload(tool_name=..., category=..., args=..., input_display=None,
                          output_raw=self.copy_content(), line_count=self._body_line_count())
    cls_result = ClassificationResult(kind=kind, confidence=1.0)
    renderer_cls = pick_renderer(cls_result, payload)
    self._swap_renderer(renderer_cls, payload, cls_result)
    self._header_bar.set_kind(kind)
```

**App-level o/i bindings:**
```python
# In HermesApp.BINDINGS:
Binding("o", "focus_output", show=False)
Binding("i", "focus_input_from_output", show=False)

def action_focus_output(self):
    self.query_one(OutputPanel).focus()

def action_focus_input_from_output(self):
    self.query_one(HermesInput).focus()
```

**TurnPhase containers** — implemented but inactive. `display.tool_panel_v3_turn_phases` defaults False. When True, MessagePanel wraps contiguous spans. `AgentFinalResponse.set_multiline(bool)` adds/removes `.-multiline` (border-left rail). Phase E activates.
