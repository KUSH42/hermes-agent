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
