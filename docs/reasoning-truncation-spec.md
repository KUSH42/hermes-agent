# Reasoning truncation spec

This spec defines how the TUI should truncate reasoning output without making
the reasoning panel feel broken. The current code preserves every reasoning
line for the life of the turn, which is simple but unbounded.

## Goals

You must keep the interaction predictable while preventing a long reasoning
stream from dominating the scrollback or consuming unbounded memory.

- Keep streaming smooth while the model is actively emitting reasoning.
- Preserve the user's ability to expand and inspect recent reasoning.
- Make truncation visible in the panel itself, not only in the status bar.
- Keep copy behavior honest. If the panel is truncated, copied text must
  reflect that fact.

## Non-goals

This spec does not define model-side truncation. It only covers local TUI
storage and rendering.

## Proposed behavior

Apply truncation only after a reasoning block closes. Do not trim mid-stream.
Mid-stream trimming causes the scroll position to jump and makes the panel feel
unstable while the model is still thinking.

When `close_box()` runs:

1. Keep the newest reasoning lines up to a fixed line cap.
2. Keep the newest reasoning bytes up to a fixed byte cap.
3. If either cap is exceeded, replace the dropped prefix with a single summary
   line at the top of the block.

Use these initial caps:

- `REASONING_MAX_LINES = 200`
- `REASONING_MAX_BYTES = 32 * 1024`

The summary line must be plain and explicit:

`… earlier reasoning truncated: 143 lines, 18,420 chars hidden`

Render that summary line inside the reasoning panel using the same gutter as
normal reasoning content, but with a dim warning style instead of italic body
text.

## Data model

Track these fields on `ReasoningPanel`:

- `self._plain_lines`: the retained visible lines, including the truncation
  summary when present.
- `self._truncated_line_count`: number of dropped original lines.
- `self._truncated_char_count`: number of dropped original characters.
- `self._was_truncated`: boolean shortcut for rendering and copy behavior.

Do not store dropped lines after truncation. The point of the cap is bounded
memory, not lazy hiding.

## Copy behavior

Copying reasoning from a truncated panel must copy exactly what is visible in
the panel, including the truncation summary line. Do not imply full fidelity if
the original prefix was dropped.

## Collapse behavior

When a truncated reasoning block is collapsed, the collapsed stub must still
show the retained line count, not the original total. If truncation metadata is
present, append a short marker:

`Reasoning collapsed  200L  truncated`

This keeps the collapsed state compact while still signalling loss.

## Implementation order

Implement this in three steps:

1. Add reasoning-panel truncation metadata and close-time trimming logic.
2. Add tests for line-cap trimming, byte-cap trimming, and copy semantics.
3. Add a small visual treatment for the truncation summary line.

## Test cases

Cover these cases:

- A short reasoning block is unchanged.
- A long block trims only after `close_box()`.
- The newest lines are preserved after truncation.
- The summary line reports hidden lines and characters accurately.
- Collapsed reasoning still shows a clickable stub after truncation.
- Copying truncated reasoning includes the summary line.
