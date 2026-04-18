# TUI gotchas

These are high-value pitfalls worth checking before you edit tricky TUI code.

## Threading and timers

- `set_interval(...)` callbacks should be plain `def` callbacks.
- Do not call `call_from_thread(...)` from the app thread.
- Keep polling, file reads, parsing, and hot-reload detection off the event
  loop.
- `@work(thread=True)` workers that block forever on `queue.get()` cause
  teardown pain. Prefer instance state plus async/event-loop dispatch.
- `post_message(...)` is usually safer than `call_from_thread(...)` for worker
  results that belong to the same widget.

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

## Textual behavior traps

- `compose()` and `render()` are mutually exclusive in practice for one widget.
- `Widget.mount(child, before=anchor)` uses `anchor.parent`; choose anchors from
  the intended parent.
- `remove_children()` plus immediate `mount()` can race; explicit per-child
  `remove()` is safer in sensitive paths.
- `pilot.resize_terminal(...)` is async and must be awaited.
- `scroll_offset` is read-only; use scroll APIs instead.
- `query_one(...)` raises `NoMatches`; teardown-safe code should guard it.
- plain `str` from `render()` is literal text, not Rich markup.

## Completion and preview

- `VirtualCompletionList` should stay O(viewport), not O(total items).
- Preview workers need cancellation checks around blocking file-read paths.
- Blank overlay states usually mean list/preview lifecycle or worker-cancel
  logic regressed, not just rendering.
- `TERMINAL_CWD` can silently change path-root behavior in tests and live runs.

## Small but expensive traps

- `len(log.lines)`, not `log.line_count`
- `await pilot.pause()` after message posts or reactive churn
- browse mode self-resets when no `ToolHeader` widgets exist
- input placeholder owns spinner text; sibling spinner widgets cause layout
  churn
- ResponseFlow changes often need both unit tests and streaming integration
  checks

## When to expand this file

Add an entry only if it is:

- easy to regress,
- expensive to rediscover,
- specific to Textual or hermes-agent TUI behavior,
- and short enough to scan during active work.
