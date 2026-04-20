# Project memory

This file mirrors the stable project memory kept in
`~/.hermes/project-memory.md` so high-signal context travels with the repo.

## TUI transcript model

The TUI no longer treats reasoning as one mutable slot per assistant message.
The intended model is a per-message timeline of blocks.

- One `MessagePanel` owns one assistant turn.
- A `MessagePanel` may contain multiple thinking blocks in one turn.
- Tool blocks for a turn belong under that turn's `MessagePanel`, not directly
  under `OutputPanel`.
- Reasoning remains distinct from assistant response prose even when it occurs
  after a tool call or after earlier visible response text.

## TUI reasoning behavior

Multiple reasoning phases inside one assistant turn must be preserved.

- Opening a later reasoning phase must create a new thinking block.
- A later reasoning phase must not overwrite an earlier one.
- If reasoning begins after response streaming has already started, the UI
  should flush pending prose first, then open a new thinking block.
- If a new reasoning phase starts while a prior one is still open, the prior
  block should be auto-closed defensively before the new one starts.

## TUI prose compatibility

Some older code still assumes an always-available response log on
`MessagePanel`.

- `MessagePanel.response_log` is the legacy bootstrap prose log.
- New streaming prose should use the current prose destination rather than
  assuming every line lands in the first response block.
- `ResponseFlowEngine` owns response prose and code routing, but it does not
  own thinking content.

## Preferred TUI test coverage

When changing turn rendering, add or update tests that cover real event order,
not just widget internals.

- `reasoning -> tool -> reasoning -> response`
- `response -> reasoning -> response`
- multiple tool calls in one turn with reasoning between them
- copy and context-menu behavior on non-first thinking blocks
- ordering assertions that tool blocks are owned by the correct `MessagePanel`
- interrupt behavior with an open later thinking block

## TUI test commands

Run TUI tests serially. The project default `xdist` settings can break Textual
tests.

```bash
source venv/bin/activate
pytest -o "addopts=" tests/tui/ -q
```

Focused suites used during the multi-thinking-block refactor:

```bash
source venv/bin/activate
pytest -o "addopts=" \
  tests/tui/test_reasoning_panel.py \
  tests/tui/test_turn_lifecycle.py \
  tests/tui/test_response_flow.py \
  tests/tui/test_tool_blocks.py \
  tests/tui/test_streaming_tool_block.py \
  tests/cli/test_reasoning_tui_bridge.py -q
```

## Cross-agent hygiene

Stable constraints mirrored from the user's Claude setup:

- Never mention Claude or Claude Code in git commit messages or pull requests
  for this repo.
- Before installing any Claude Code skill from any source, scan it with Snyk
  Agent Scan first. Do not install unless the scan returns safe.
