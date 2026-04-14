# TUI syntax and diff hot reload spec

This spec extends existing skin hot reload so every TUI surface that renders
syntax-highlighted code or skin-colored diffs updates live when the active skin
changes. Goal: no stale `monokai` blocks, no stale diff colors, and no need to
reopen panels or remount widgets to pick up new theme state.

## Current state

The TUI already hot reloads some syntax-highlighted content:

- `StreamingCodeBlock` refreshes completed blocks in place via
  `HermesApp.apply_skin()` -> `StreamingCodeBlock.refresh_skin()`.
- In-progress `StreamingCodeBlock` instances keep streaming and finalize with
  the new `preview-syntax-theme`.
- `ToolBlock` supports `rerender_fn`, and `execute_code` preview blocks already
  use it to rebuild ANSI-highlighted lines on skin change.

The remaining gaps are:

- `PreviewPanel` always renders `Syntax(..., theme="monokai")` and does not
  rebuild when the skin changes.
- TUI diff blocks mounted from `_on_tool_complete()` do not pass a rerender
  callback, so diff colors stay frozen at mount time.
- TUI `read_file` preview blocks do not pass a rerender callback, so syntax
  colors stay frozen at mount time.
- TUI `terminal` file-preview blocks do not pass a rerender callback, so syntax
  colors stay frozen at mount time.
- `HermesApp.apply_skin()` refreshes `ToolBlock` and `StreamingCodeBlock`, but
  it does not explicitly refresh `PreviewPanel`.
- `HermesApp.apply_skin()` wraps whole refresh loops in broad `try` blocks,
  which means one bad block can stop refresh for later blocks.

## Scope

This change applies only to TUI surfaces under `hermes_cli/tui/` and the TUI
mount path in `cli.py`.

In scope:

- `PreviewPanel`
- Static `ToolBlock` diff previews
- Static `ToolBlock` code previews from `read_file`
- Static `ToolBlock` code previews from `terminal` when the command is a file
  read preview
- Existing `StreamingCodeBlock` hot reload path hardening

Out of scope:

- Prompt-toolkit mode
- Recomputing already completed plain-text tool output that never used syntax or
  diff coloring
- Streaming terminal output that is plain runtime stdout rather than a syntax
  preview

## Requirements

After this change:

1. Changing skin must update every mounted syntax-highlighted or diff-colored
   TUI surface in place.
2. A completed block must preserve semantic state while recoloring:
   copied text, collapsed state, detected language, and ordering must not
   change.
3. A live preview must not reread the filesystem just to recolor. If source is
   already loaded, recolor from cached source.
4. One broken block refresh must not prevent later blocks from refreshing.
5. New blocks mounted after skin change must still use current skin on first
   render.

## Design

### `PreviewPanel`

`PreviewPanel` becomes theme-aware and rerenderable from cached source.

- Worker message changes from "already built `Syntax` object" to "raw preview
  source payload."
- `PreviewPanel` stores enough state to rebuild current view without I/O:
  absolute path, preview text head, and plain-text fallback state.
- Add `refresh_theme()`:
  - If current preview mode is syntax, rebuild `Syntax` with current
    `preview-syntax-theme` and `app-bg`.
  - If current preview mode is plain fallback or panel is empty, no-op.
- Initial render path and hot-reload path use same renderer helper so preview
  and refresh stay identical.

### Static `ToolBlock` previews

Every TUI block whose display lines depend on active skin gets a `rerender_fn`.

- Diff blocks:
  capture the unified diff once at mount time, then recolor that immutable diff
  on skin change. Do not recompute from current filesystem state.
- `read_file` code preview blocks:
  close over `path` and `result_json`, then call `render_read_file_preview()`
  again.
- `terminal` file-preview blocks:
  close over `command` and `result_json`, then call
  `render_terminal_preview()` again.
- Existing `execute_code` callback path stays as-is.

`ToolBlock.refresh_skin()` remains canonical rebuild hook. It must keep plain
copy text stable and update only styled display lines.

### `HermesApp.apply_skin()`

Skin apply becomes fan-out refresh coordinator.

- Keep existing cache invalidation.
- Refresh `PreviewPanel` explicitly.
- Refresh `VirtualCompletionList` as today.
- Refresh each `ToolBlock` individually with per-block exception isolation.
- Refresh each `StreamingCodeBlock` individually with per-block exception
  isolation.

This keeps one failing rerender callback from freezing all later blocks.

## Test plan

Add or update TUI tests for:

- `PreviewPanel` rerenders current syntax preview on skin change.
- Diff `ToolBlock` rerenders on skin change.
- `read_file` preview `ToolBlock` rerenders on skin change.
- `terminal` file-preview `ToolBlock` rerenders on skin change.
- Existing `StreamingCodeBlock` tests remain green.

## Review

Review pass against live code found these issues and this spec addresses them:

- Issue: spec must not assume every tool block is syntax-highlighted.
  Fix: scope only blocks with skin-dependent render callbacks.
- Issue: preview hot reload could accidentally reread files.
  Fix: cached-source rerender requirement made explicit.
- Issue: one rerender exception could stop later refreshes.
  Fix: per-widget isolation added to `HermesApp.apply_skin()`.

Open issues after review: 0.
