# Parallel Worktree Sessions Spec

**Branch:** `spec/parallel-worktree-sessions`  
**Date:** 2026-04-20  
**Status:** Draft 3

---

## Problem

Hermes runs one agent at a time in one working directory. Heavy tasks (full refactor,
spec write, test suite) block the REPL entirely. Users already manage this manually:
open a second terminal, `git worktree add`, start a second `hermes` process, switch
between them. The TUI has no awareness of any of this.

Goal: make parallel worktree sessions a first-class TUI feature — create, monitor,
switch, and merge sessions without leaving the app.

---

## Design constraints

- Each session = one `git worktree` + one branch + one process. Active (foreground)
  sessions run `HermesApp` (full TUI). Background sessions run `HeadlessSession`
  (agent pipeline only, no TUI).
- Sessions are siblings, not nested. No tree structure.
- The existing `WorkspaceOverlay` (`w` / `/workspace`) is the anchor point for
  session management — extend it, don't add a competing surface.
- Keyboard-first. Mouse optional.
- No layout split / tiling inside one Textual process. Each session is its own
  process; the TUI shows a session *switcher*, not a side-by-side view.
- Feature-gated behind `sessions.enabled` config flag (default `false`).

---

## Key concepts

| Term | Definition |
|---|---|
| **Session** | A `(session_id, worktree_path, branch, PID)` tuple tracked in `state.json`. |
| **Active session** | The session whose TUI is in the foreground terminal. |
| **Background session** | Running Hermes process, not in the foreground. |
| **Orphan worktree** | Worktree exists in `session_dir`, `state.json` entry exists, but PID is dead. |

---

## IPC model

### Chosen approach: shared state directory + UNIX socket per session

Each session writes its state to `<session_dir>/<id>/state.json`. Communication
between sessions uses a **UNIX domain socket** at `<session_dir>/<id>/notify.sock`.

```
session_dir/
  sessions.json          ← file-locked on write; format:
                           {
                             "active_session_id": "abc123",
                             "sessions": [
                               {"id": "abc123", "branch": "main",
                                "worktree_path": "...", "pid": 12345,
                                "socket_path": ".../notify.sock"},
                               ...
                             ]
                           }
  abc123/
    state.json           ← {id, branch, worktree_path, pid, agent_running, last_event}
    notify.sock          ← UNIX socket; active session listens; bg sessions send here
    output.jsonl         ← ring-buffered output written while session is in background
  def456/
    state.json
    notify.sock
    output.jsonl
```

**File locking**: all writes to `sessions.json` use `fcntl.flock(LOCK_EX)` to prevent
concurrent-write races between processes. Reads are opportunistic (no lock); stale reads
are tolerable for the 2s polling window.

**Creating a background session** (`subprocess.Popen`):
The active session spawns a new `hermes` process with `subprocess.Popen(...,
start_new_session=True)`. The child writes its PID + socket path to `state.json`
once its event loop is ready. The parent registers the child in `sessions.json`.

**Switching sessions** (`os.execvp`):
Before calling `os.execvp`, the active session:
1. Flushes its current output buffer (the TUI's `OutputPanel` plain-text lines)
   to `<session_dir>/<active_id>/output.jsonl` (ring-buffer capped at
   `output_buffer_lines`).
2. Writes `active_session_id: <target_id>` to `sessions.json` (locked) so
   background sessions immediately know where to send notifications.
3. Closes its `notify.sock` listener.
4. Calls `os.execvp(sys.argv[0], [sys.argv[0], "--session-id", target_id])`.
   Uses `sys.argv[0]` (the actual binary path, venv-safe) rather than bare
   `"hermes"` which would break in virtualenv or custom install paths.

The new Hermes process reads its `state.json` (metadata) and replays `output.jsonl`
into a read-only `HistoryPanel` (a non-interactive `RichLog` in `session_widgets.py`).
`HistoryPanel` renders **plain text only** — Rich markup, tool block formatting, code
syntax highlighting, and inline images from the background session are NOT preserved.
This is a known limitation of the headless output path. A dim header "── session
history (plain text) ──" separates history from the live panel below it. Session bar is re-rendered
from `sessions.json` on startup.

There is no persistent "session manager daemon". The session bar is rendered by
whichever Hermes process currently owns the terminal. Its data comes from reading
`sessions.json` at startup and polling it every 2s (debounced file stat; re-read
only on mtime change).

**Headless mode**: background sessions are launched without a TTY. They cannot run
Textual's terminal renderer. They run in `--headless` mode: agent pipeline active,
config loaded, tool execution enabled, but `HermesApp` is replaced by a
`HeadlessSession` driver that writes output lines to `output.jsonl` and handles
the notify socket. Textual is not imported in headless mode. Add `--headless` flag
to `cli.py`; `HeadlessSession` lives in `hermes_cli/tui/headless_session.py`.

**Background output**: every agent output line in a headless session is appended to
`output.jsonl` (`{ts, text, role}` — `text` is plain text stripped of ANSI/Rich
markup, ring-capped at `output_buffer_lines`).

**Cross-process notifications** (background → foreground):
A background session reads `active_session_id` from `sessions.json` and sends a
JSON event `{type, session_id, message}` to `<session_dir>/<active_id>/notify.sock`.
The foreground process listens on its own socket in a daemon thread; on receipt it
calls `app.call_from_thread(...)` to flash the HintBar.

**Startup race**: between `os.execvp` and the incoming process opening its socket,
notifications are silently dropped. Background sessions do not retry failed socket
sends. This is acceptable — the session bar polling (2s) will reflect the updated
`agent_running` state from `state.json` regardless.

**Who writes `active_session_id`**: only the process that is switching (calling
`os.execvp`) writes this field. The incoming process reads it to confirm it is now
active and opens its socket. Background sessions never write `active_session_id`.

---

## UX model

### Session bar (new persistent chrome)

Mounted at the very bottom of the app, always visible when `sessions.enabled`.
TCSS dock ordering (innermost = highest z-order in bottom stack):
`StatusBar` (innermost) → `HintBar` → `SessionBar` (outermost, lowest physical
position). `SessionBar` uses `dock: bottom` with explicit `height: 1` so it
doesn't crowd the existing chrome.

```
 ● main  ○ feat/auth [●]  ○ fix/crash   ┤ + ├
```

- `●` filled = active session (this process)
- `○` hollow = background session (running, not in foreground)
- `[●]` pulsing = agent running in that background session
- ` ` blank = agent idle
- `+` = open NewSessionOverlay (`Ctrl+W N`)

`Alt+1`…`Alt+9` switch to session by 1-indexed position. Clicking a session name
also switches. Note: some terminal emulators capture `Alt+N` for their own tab
switching. If an `Alt+N` press is not received by Hermes (no session switch), use
`/sessions switch <name>` or click the session bar directly as fallback.

When `max_sessions` is reached, the `+` button shows as `[dim]+[/dim]` and is
non-interactive; pressing `Ctrl+W N` flashes "Max sessions reached" in HintBar.

### WorkspaceOverlay — Sessions tab

Extend `WorkspaceOverlay` with a tab strip using Textual's built-in `ContentSwitcher`.
The tab strip is a row of `Button` widgets with `--active` CSS class on the selected
tab; clicking or left/right arrow keys cycle. (`Tab` is NOT used — it cycles focus
between overlay widgets in Textual, which would conflict.)

```
┌─ Workspace ──────────────────────────────────────────┐
│  [ Git Status ]  [ Sessions ]                        │
├──────────────────────────────────────────────────────┤
│  (ContentSwitcher swaps content below)               │
└──────────────────────────────────────────────────────┘
```

**Sessions tab** content:

```
  ● main             feat/tool-panel-v4   idle
  ○ feat/auth        feat/auth-rewrite    running  [switch] [merge] [kill]
  ○ fix/crash        fix/null-deref       idle     [switch] [merge] [kill]
  ⚠ orphan/dead      orphan-branch        orphan   [reopen] [delete]

  [ + New Session ]
```

- Active session row has no `[switch]`/`[kill]` — you can't kill your own foreground
  session from the overlay. Kill requires switching away first; a dim hint says so.
- Orphan entries: PID dead, worktree still on disk. Actions: `[reopen]` (spawn new
  process in the worktree) or `[delete]` (rm worktree + remove entry).

### Creating a session

`Ctrl+W N` (mnemonic: **W**orktree **N**ew — avoids terminal-swallowed `Ctrl+Shift+*`)
or clicking `+` in the session bar opens `NewSessionOverlay`:

```
┌─ New Session ─────────────────────────────────────────┐
│  Branch name:  [ feat/                              ] │
│  Base:         [● current branch  ○ main            ] │
│                                          [ Create ] │
└───────────────────────────────────────────────────────┘
```

The "Task hint" field is removed — it had no defined behavior. Branch name and base
are sufficient.

On confirm:
1. Validate branch name is not empty and not already a branch in this repo. If the
   branch already exists as a worktree, show inline error: "Branch already checked
   out in another worktree."
2. Run `git worktree add <session_dir>/<id>/ -b <branch> <base>` in a worker
   thread; show spinner in the Create button. If git returns non-zero, display
   its stderr inline in the overlay (e.g., "fatal: '<branch>' is already used by
   worktree at ..."). Do not proceed.
3. `subprocess.Popen([sys.argv[0], "--headless", "--session-id", new_id],
   cwd=worktree_path, start_new_session=True)` — uses `sys.argv[0]` for venv
   safety; headless flag skips Textual initialization.
4. Poll `state.json` up to 3s for PID registration. On timeout: show error
   "Session failed to start", run `git worktree remove --force <path>` cleanup.
5. On success: dismiss overlay, update `sessions.json`, session bar refreshes.

### Switching sessions

- `Alt+N` or click session name in bar, or `[switch]` in overlay.
- Active session flushes in-progress output to `output.jsonl`, writes
  `active_session_id`, closes socket, then calls
  `os.execvp("hermes", ["hermes", "--session-id", target_id])`.
- The incoming process reads state, re-renders TUI, reopens its notify socket.
- There is a brief terminal flash during exec; this is acceptable for Option A.

### Merging a session

From the Sessions tab: click `[merge]` next to a session, or `/sessions merge <name>`.

**Pre-condition**: the session being merged must be idle (agent not running). If
running, `[merge]` is disabled and shows tooltip "Stop agent first."

**Merge flow** (modal, 3 steps in a `MergeConfirmOverlay`):

1. **Pre-merge check**: show `git diff <base>...<branch> --stat` output. Warn if
   any files overlap with uncommitted changes in the target branch.
2. **Strategy select**: `Merge commit` / `Squash` / `Rebase`. Default: squash.
3. **Confirm**: runs merge in a worker thread. Shows live git output.
   - `[ Merge + close session ]` (default): on success, kill the session process
     and delete worktree. Session entry turns `$success` → removed after 3s.
   - `[ Merge only ]`: on success, leave session alive; user must kill manually.
   - On conflict: show conflict file list inline. Offer `[ Open in $EDITOR ]` and
     `[ Abort merge ]`. Session is NOT auto-killed on conflict.

### Killing a session

`[kill]` in overlay, or `/sessions kill <name>`.

**Killing a background session**: prompt:

```
Kill session "feat/auth"?
  [ Keep worktree ]  [ Delete worktree ]  [ Cancel ]
```

Sends `SIGTERM` to PID; if still alive after 2s, `SIGKILL`. Removes entry from
`sessions.json`. Updates session bar.

**Killing the active session**: not available from the `[kill]` button (disabled,
dim hint: "Switch away first to kill this session"). The user must switch to another
session and then kill the former active session from there. `/sessions kill current`
is rejected with an error message.

### Orphan detection

On startup (if `sessions.enabled`): read `sessions.json`, check each PID with
`os.kill(pid, 0)` — but also verify the process is a Hermes session by reading
`/proc/<pid>/cmdline` (Linux) or `ps -p <pid> -o args=` (macOS) and confirming
`--session-id <id>` appears. This guards against PID reuse by unrelated processes.
Dead PIDs or PID mismatch → marked as orphan. Orphans show in the Sessions tab
with `[reopen]` and `[delete]` actions.

`[reopen]` = spawn a new headless Hermes process in the existing worktree,
inheriting the session ID. `output.jsonl` is preserved so history is visible on
next switch-in.

`auto_prune_orphans: true` in config skips the prompt and deletes orphans + their
worktrees automatically on startup.

---

## Slash commands

| Command | Action |
|---|---|
| `/sessions` | Open WorkspaceOverlay → Sessions tab |
| `/sessions new [branch]` | Open NewSessionOverlay (pre-fills branch field) |
| `/sessions list` | Print session list to output panel |
| `/sessions switch <name>` | Switch to named session |
| `/sessions merge <name>` | Run merge flow for named session |
| `/sessions kill <name>` | Kill named session (rejected if active session) |

---

## Status bar integration

When a background session's agent completes or errors, the foreground process
receives a notification on `notify.sock` and flashes the HintBar:

```
  feat/auth: agent finished ✓   [switch]
```

The notification uses `_SessionNotification(Horizontal)` — a thin widget that
mounts into the same dock slot as HintBar, temporarily replacing it. It contains
a `Static` for the message and a `Button("[switch]")` for the action. On button
press: calls the session switch flow (flush → exec). On 5s timeout or Esc:
unmounts and HintBar resumes. Does NOT use `_flash_hint_expires` (a different
mechanism for simple text hints); `_SessionNotification` is its own widget with
its own timer.

If multiple background events arrive while the hint is shown, they queue in a
`deque` and show sequentially (next event shows immediately after the current one
dismisses).

---

## Config

```yaml
sessions:
  enabled: false
  session_dir: "/tmp/hermes-sessions"   # Linux/macOS only; /tmp is fine for ephemeral sessions
  max_sessions: 8
  output_buffer_lines: 2000
  auto_prune_orphans: false
  default_merge_strategy: "squash"      # "merge" | "squash" | "rebase"
```

Note: `session_dir` under `/tmp` is ephemeral — sessions survive terminal close
but not reboots. This is intentional (sessions are task-scoped, not long-lived).

UNIX socket path limit: socket paths are capped at ~104 chars (macOS) / ~108 chars
(Linux). With the default `/tmp/hermes-sessions/<36-char-uuid>/notify.sock` the
path is ~75 chars — safe. Custom `session_dir` paths deeper than ~30 chars risk
exceeding the limit. `SessionManager` validates socket path length on creation and
rejects `session_dir` values that would overflow.

---

## Files that move together

- `hermes_cli/tui/session_manager.py` (NEW) — `SessionRecord`, `SessionManager`,
  `SessionIndex` (reads/writes `sessions.json` with `fcntl.flock`), `_NotifyListener`
  daemon thread
- `hermes_cli/tui/session_widgets.py` (NEW) — `SessionBar`, `NewSessionOverlay`,
  `MergeConfirmOverlay`, `_SessionRow`, `_SessionsTab`, `_SessionNotification`,
  `HistoryPanel` (read-only `RichLog` replay of `output.jsonl`)
- `hermes_cli/tui/headless_session.py` (NEW) — `HeadlessSession` driver (agent
  pipeline, output.jsonl writer, notify socket sender; no Textual import)
- `hermes_cli/tui/overlays.py` — extend `WorkspaceOverlay` with `ContentSwitcher`
  tab strip; mount `_SessionsTab` as second content pane
- `hermes_cli/tui/app.py` — session bar mount (dock bottom), `Alt+N` bindings,
  `Ctrl+W N` binding, `/sessions` slash cmd routing, notify socket startup/teardown,
  `--session-id` CLI arg handling
- `hermes_cli/config.py` — `sessions` block in `DEFAULT_CONFIG`
- `cli.py` — parse `--session-id` and `--headless` args; route to `HeadlessSession`
  when `--headless`; pass `session_id` to `HermesApp` when `--session-id` only
- `tests/tui/test_session_manager.py` (NEW) — `SessionRecord`, `SessionManager`,
  `SessionIndex` read/write + flock, orphan detection (PID dead + cmdline mismatch),
  notify listener (mock socket), socket path length validation
- `tests/tui/test_session_widgets.py` (NEW) — `SessionBar` rendering + dock order,
  `NewSessionOverlay` validation (empty name, duplicate branch, git error surface,
  max_sessions), merge flow states (pre-check/strategy/confirm/conflict), kill active
  session disabled, orphan reopen/delete, `_SessionNotification` queue behavior
- `tests/tui/test_headless_session.py` (NEW) — `HeadlessSession` output.jsonl write,
  ring-cap enforcement, socket send on agent complete/error

---

## Out of scope (this spec)

- Side-by-side split view within one terminal window
- Session sharing / collaboration
- Remote sessions (SSH)
- Session persistence across machine reboots
- Auto-spawning sessions based on agent task type
- Windows support (`/tmp`, `os.execvp`, UNIX sockets are POSIX-only)

---

## Phasing

| Phase | Scope | Tests |
|---|---|---|
| A | `SessionRecord` + `SessionManager` + `SessionIndex` (flock) + config + `_NotifyListener` stub | ~20 |
| B | `HeadlessSession` + `--headless` CLI flag + `output.jsonl` writer + ring-cap | ~15 |
| C | `SessionBar` widget + `Alt+N` bindings + session bar TCSS + dock ordering | ~15 |
| D | `NewSessionOverlay` + create/kill flows + `/sessions` commands | ~20 |
| E | WorkspaceOverlay Sessions tab (`ContentSwitcher` + `_SessionsTab` + orphan UI) | ~15 |
| F | Merge flow (`MergeConfirmOverlay` + worker + conflict display) | ~20 |
| G | Cross-process notifications (`notify.sock` + `_SessionNotification` + HintBar) | ~15 |

~120 tests total. Each phase ships independently behind the feature flag.
Phases A–C are pure data/widget; no subprocess. Phase D adds subprocess (mocked in tests).
Phase G adds UNIX socket IPC (mock socket in tests).
