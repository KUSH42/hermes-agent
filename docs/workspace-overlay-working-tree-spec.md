# Workspace overlay: full working-tree scope

This spec changes `WorkspaceOverlay` from a session-scoped "files Hermes
touched" view into a repo-scoped working-tree view that matches `git status`
for the current repository. It keeps Hermes session metadata as annotation,
not as the inclusion filter.

The result is a simpler user model. When you open the workspace overlay, you
see the local changes that exist in the current repo, whether they came from
Hermes, you, another terminal, or a formatter.

## Goals

This change makes the overlay behave like a workspace view instead of a session
audit view.

- Show all local changes in the active Git worktree.
- Match Git's inclusion rules instead of reimplementing filesystem watching.
- Keep Hermes session deltas visible as extra context.
- Continue updating while the overlay is visible, even when `agent_running` is
  false.
- Preserve the current low-latency, thread-safe update path.

## Non-goals

This change does not turn the overlay into a full Git UI.

- Do not show ignored files.
- Do not implement manual recursive filesystem watching inside Git repos.
- Do not show files outside the active repo root.
- Do not add staging, diff, or commit actions in this pass.
- Do not remove Hermes session metadata.

## User model

The overlay answers one question: "What local changes exist right now in this
repo?"

Inside a Git repo, the overlay content must match what `git status --short`
would show for the worktree, with optional extra metadata for Hermes-touched
files. If Git would not show a file, the overlay must not show it.

Outside a Git repo, the overlay stays available but renders a non-Git empty
state message. This spec does not define a filesystem-scanning fallback.

## Source of truth

Inside a Git repo, Git is the source of truth.

- Use `git rev-parse --show-toplevel` to resolve the repo root.
- Use `git rev-parse --abbrev-ref HEAD` to resolve the branch.
- Use `git status --porcelain=v1 -z --untracked-files=all` to resolve the
  visible file set.
- Respect `.gitignore` by relying on Git behavior, not custom ignore parsing.

Use NUL-delimited porcelain output, not line-based `--short` parsing. This
avoids ambiguity for:

- paths containing spaces
- paths containing `->`
- rename entries
- unusual but valid path characters

This means the overlay includes:

- Modified tracked files.
- Added tracked files.
- Deleted tracked files.
- Renamed files.
- Untracked files.
- Staged changes.
- Unmerged and conflicted files.

This means the overlay excludes:

- Ignored files.
- Files outside the repo.
- Files Git does not consider part of the current working-tree state.

## Overlay behavior

The overlay remains a top-docked info overlay and keeps the existing dismiss
bindings and focus behavior.

### Header

The header must show:

- `Workspace`
- Current branch name
- Dirty file count

If no Git snapshot exists yet, show a loading or fallback header instead of an
empty partial state. Dirty file count is the number of visible snapshot
entries, not only the number of modified tracked files.

### Summary row

The summary row must describe the current worktree, not just Hermes session
deltas.

Required summary values:

- Modified file count
- New file count
- Deleted file count
- Staged file count
- Untracked file count

Optional session metadata may still appear here, but it must be clearly labeled
as session-only.

### File rows

Each visible row represents one file from the current Git status snapshot.

Required row fields:

- Raw Git XY status or a normalized display derived from it
- Relative path
- Staged indicator
- Untracked indicator, if applicable

Optional row fields:

- Hermes session-added and session-removed counts
- Hermes-touched badge
- Complexity warning

If a file exists in Git status but was never touched by Hermes, it must still
appear in the overlay with zeroed or omitted Hermes session fields.

### Row ordering

Row ordering must be deterministic.

Sort rows in this order:

1. Hermes-touched files, most recent `last_write` first
2. All remaining files, alphabetically by `rel_path`

This keeps active Hermes edits easy to find without hiding unrelated local
changes elsewhere in the repo.

## Data model changes

`WorkspaceTracker` must stop using Hermes writes as the inclusion gate.

### `FileEntry`

Keep `FileEntry`, but reinterpret it as overlay row state for any file currently
present in the working tree.

Recommended fields:

- `path`
- `rel_path`
- `git_xy`
- `git_index_status`
- `git_worktree_status`
- `git_staged`
- `git_untracked`
- `session_added`
- `session_removed`
- `last_write`
- `hermes_touched`
- `complexity_warning`

### Snapshot shape

`GitSnapshot` should carry parsed row data rather than only raw short-status
lines.

Recommended additions:

- `entries: list[GitSnapshotEntry]`
- `staged_count`
- `untracked_count`
- `modified_count`
- `deleted_count`
- `renamed_count`
- `conflicted_count`

This reduces parsing duplication and makes overlay refresh deterministic.

### Git status parsing

The implementation must parse full XY status semantics instead of collapsing to
one character too early.

At minimum, preserve:

- `index_status`
- `worktree_status`
- `is_untracked`
- `is_conflicted`
- `is_renamed`

The overlay may render a normalized label, but it must keep enough structured
data to distinguish:

- staged-only changes
- worktree-only changes
- staged and worktree changes on the same file
- untracked files
- renamed files
- unmerged or conflicted files

Rename entries must not be dropped in v1. Parse porcelain rename records and
display the destination path, with optional source-path microcopy if useful.

## Polling model

Polling must be tied to overlay visibility, not only to agent execution.

### Current problem

Today, background polling starts in `watch_agent_running(True)` and stops in
`watch_agent_running(False)`. That means the overlay is not truly live while
the user edits the repo during idle time.

### New rule

Start polling when either condition is true:

- The overlay is visible.
- The agent is running.

Stop polling only when both conditions are false.

### Poll interval

Use a single timer and keep the interval conservative.

- Default interval: 5.0 seconds
- Immediate poll when opening the overlay
- Immediate poll after a file-mutating tool completes

Do not create two independent poll timers for the same feature.

The app should manage polling through one helper such as
`_sync_workspace_polling_state()`, called whenever overlay visibility or
`agent_running` changes. The helper owns timer start and stop decisions.

### Poll coalescing

The existing worker group pattern is correct and should remain.

- Keep polling work off the Textual event loop.
- Use one worker group for Git polling.
- If a poll is already in flight, coalesce additional triggers instead of
  spawning overlapping subprocess work.

### Threading model

Polling and snapshot construction must run off the event loop on a worker
thread.

- Trigger polling from the app thread only.
- Run Git subprocess calls on a worker thread.
- Parse snapshot data on that worker thread.
- Post one message back to the app thread with the completed snapshot.
- Mutate tracker state and refresh the overlay only on the app thread.

This feature must maintain at most one in-flight Git poll at a time. If a new
poll trigger arrives while a poll is already running, mark a retrigger flag and
run exactly one follow-up poll after the current one completes.

This prevents overlapping `git status` subprocesses while still ensuring the
overlay catches up after bursts of writes or repeated open/close actions.

### Executor policy

Version 1 should not introduce a custom `ThreadPoolExecutor`.

Use Textual's existing `@work(thread=True)` worker model with a dedicated
workspace polling group. That keeps worker lifecycle and shutdown aligned with
the app and avoids a second concurrency abstraction inside the TUI.

If profiling later shows real contention between Git polling, complexity
analysis, media polling, or other blocking subsystems, add a bounded shared
executor behind a small service layer. Do not instantiate ad hoc executors from
widgets or overlays.

## Update flow

The update flow must remain app-thread-safe.

1. Trigger poll from the event loop.
2. Run Git subprocess work on a worker thread.
3. Post one message carrying the new snapshot.
4. Merge snapshot into tracker state on the app thread.
5. Refresh the visible overlay on the app thread.

This preserves the current high-signal invariant: no DOM mutation and no
tracker mutation from worker threads.

## Merge rules

Git snapshot data and Hermes session data must merge by path.

- Create entries for every file in the Git snapshot.
- Overlay Hermes session metadata onto those entries when available.
- Retain Hermes-only entries only if there is an explicit product reason to
  show "touched this session, now clean." The default should be no: once a file
  is clean and absent from Git status, it should disappear from the overlay.

Complexity warnings remain Hermes-only annotation in v1.

- Do not run complexity analysis for every dirty Python file in the repo.
- Continue analyzing only files Hermes touched this session.
- Attach that warning to the matching overlay row when the file is also present
  in the current Git snapshot.
- Drop the warning when the file disappears from the overlay set.

## Non-Git fallback

Outside a Git repo, show the overlay with a non-Git empty state instead of
attempting filesystem scanning.

Required behavior:

- Render the overlay chrome normally.
- Show a short message such as `Workspace view requires a Git repository`.
- Do not start background Git polling.
- Keep dismiss and focus behavior unchanged.

If a filesystem mode is added later, define it in a separate spec.

## UI copy

The overlay copy must match the new semantics.

Examples:

- Header: `Workspace  main  ● 12 dirty`
- Summary: `Git  6 modified  ·  3 new  ·  1 deleted  ·  4 staged  ·  2 untracked`
- Session badge: `Hermes`

Avoid calling the whole overlay "session" unless referring specifically to
Hermes-added metadata.

## Migration notes

This change is a semantic migration, not only a refactor.

- Existing tests that assume session-only inclusion must be updated.
- Existing hints such as `w  workspace changes` can remain.
- Existing `record_write()` and complexity analysis logic should remain, but
  they must annotate entries instead of defining the visible row set.
- Existing tracker tests that assert unknown Git-status paths are ignored must
  be rewritten, because Git snapshot rows become the visible source of truth.

## Test plan

Add or update tests in `tests/tui/test_workspace_overlay.py` and
`tests/tui/test_workspace_tracker.py`.

Required cases:

1. Overlay includes files from Git status even if Hermes never touched them.
2. Overlay includes Hermes-touched files with session metadata when they are
   also dirty in Git.
3. Overlay excludes ignored files because Git excludes them.
4. Overlay updates while visible and idle.
5. Overlay polling stops when hidden and agent is idle.
6. Immediate poll runs when the overlay opens.
7. Immediate poll runs after file-mutating tool completion.
8. Clean files disappear after the next snapshot unless a separate "recently
   touched" mode is explicitly implemented.
9. Staged and untracked states render correctly.
10. Renamed files render correctly.
11. Conflicted files render correctly.
12. Outside a Git repo, overlay shows the non-Git empty state.
13. Complexity warnings appear only for Hermes-touched files, not all dirty
    Python files.

## Implementation outline

Use the existing structure and change the ownership of truth.

1. Update `GitPoller.poll()` to return richer parsed snapshot entries.
2. Update `WorkspaceTracker` so snapshot entries create the visible row set.
3. Keep `record_write()` as annotation only.
4. Change polling lifetime from `agent_running`-only to
   `overlay_visible or agent_running`.
5. Update `WorkspaceOverlay.refresh_data()` to render Git-wide counts.
6. Add one polling-state helper that owns timer lifecycle.
7. Update tests to reflect full working-tree semantics.

## Future modes

This spec intentionally shows untracked files by default because matching
`git status` is the least surprising behavior.

If noise becomes a problem later, add an overlay mode toggle such as:

- `all`: tracked + untracked
- `tracked`: tracked only
- `session`: Hermes-touched only

The default must remain `all` so the overlay matches the user's working-tree
state.
