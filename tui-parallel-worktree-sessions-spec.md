# Parallel Worktree Sessions Spec

**Branch:** `spec/parallel-worktree-sessions`  
**Date:** 2026-04-20  
**Status:** Draft 1

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

- Each session = one `git worktree` + one `HermesApp` process + one branch.
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
| **Session** | A `(worktree_path, branch, HermesApp PID)` triple. |
| **Active session** | The session whose TUI is in the foreground. |
| **Background session** | Running process, not currently visible. |
| **Orphan worktree** | A worktree that exists on disk but has no running Hermes process. |

---

## UX model

### Session bar (new persistent chrome)

A slim bar below the StatusBar (or above the HintBar — TBD). Always visible when
`sessions.enabled`. Shows:

```
 ● main  ○ feat/auth [●]  ○ fix/crash ━━  ┤ + New ├
```

- `●` filled = active session
- `○` hollow = background session
- `[●]` = agent running in that background session (pulsing dot animation)
- `━━` = agent idle
- `+ New` = create session shortcut

Clicking a session name switches to it. `Alt+1`…`Alt+9` switch by index.

### WorkspaceOverlay — Sessions tab

Extend the existing `WorkspaceOverlay` with a tab strip at the top:

```
┌─ Workspace ──────────────────────────────────────────┐
│  [ Git Status ]  [ Sessions ]                        │
├──────────────────────────────────────────────────────┤
│  (existing git status content / new sessions panel)  │
└──────────────────────────────────────────────────────┘
```

The **Sessions tab** shows a vertical list of all sessions with inline controls:

```
  ● main             feat/tool-panel-v4   idle     [switch]
  ○ feat/auth        feat/auth-rewrite    running  [switch] [merge] [kill]
  ○ fix/crash        fix/null-deref       idle     [switch] [merge] [kill]

  [ + New Session ]
```

This is the primary session management surface. The session bar gives ambient
awareness; the WorkspaceOverlay Sessions tab gives full control.

### Creating a session

`Ctrl+Shift+N` or clicking `+ New` in the session bar / overlay opens a
`NewSessionOverlay`:

```
┌─ New Session ─────────────────────────────────────────┐
│  Branch name:  [ feat/                              ] │
│  Base:         [● current branch  ○ main            ] │
│  Task hint:    [                                    ] │
│                                          [ Create ] │
└───────────────────────────────────────────────────────┘
```

On confirm:
1. `git worktree add <path> -b <branch> <base>`
2. Spawn a new `hermes` process in that worktree path.
3. Show the new session in the bar; keep active session in foreground.

Path convention: `/tmp/hermes-sessions/<branch-slug>/`.

### Switching sessions

- Session bar click or `Alt+N` (N = 1-indexed position).
- **Does not kill the current session** — it stays running in background.
- The TUI shell-evals an `exec hermes --attach <session-id>` or equivalent.
  Implementation detail: simplest is `subprocess.Popen` + terminal attach via
  `os.execvp`; alternative is a shared IPC socket bus.
- Background sessions continue running. Agent output accumulates in their
  output buffer. When user switches back, they see the full history.

### Merging a session

From the Sessions tab: click `[merge]` next to a session (or `/merge` slash cmd).

**Merge flow** (modal, 3 steps):

1. **Pre-merge check**: show `git diff <base>...<branch> --stat`. Warn if
   conflicts likely (overlapping files with main).
2. **Strategy select**: `Fast-forward` / `Squash` / `Rebase`. Default: squash.
3. **Confirm**: runs merge, shows result inline. On success: session entry
   turns green → auto-closes after 3s or on Esc.

Option: `merge and keep session` vs `merge and delete session`.

### Killing a session

`[kill]` in overlay, or `/sessions kill <name>`. Prompts:

```
Kill session "feat/auth"?
  [ Keep worktree ]  [ Delete worktree ]  [ Cancel ]
```

Removes entry from bar. Sends `SIGTERM` to session process.

### Orphan detection

On startup (if `sessions.enabled`): scan for `hermes`-managed worktrees in
`/tmp/hermes-sessions/` that have no running process. Show them as `[orphan]`
in the Sessions tab with option to re-attach or delete.

---

## Slash commands

| Command | Action |
|---|---|
| `/sessions` | Open WorkspaceOverlay → Sessions tab |
| `/sessions new [branch]` | Create session (pre-fills branch field) |
| `/sessions list` | Print session list to output panel |
| `/sessions switch <name>` | Switch to named session |
| `/sessions merge <name>` | Run merge flow for named session |
| `/sessions kill <name>` | Kill named session |

---

## Status bar integration

When a background session's agent completes or errors, flash a notification in
the HintBar:

```
  feat/auth: agent finished ✓   [switch]
```

Auto-dismisses after 5s. Uses existing hint mechanism.

---

## IPC model (implementation path)

Two options — choose one:

### Option A: Process-per-session (simpler)

Each session = separate `hermes` OS process. The session bar is a thin
"session manager" process that monitors PIDs and forwards input. Switch =
`os.execvp` into the target session process. State persistence via session
files at `/tmp/hermes-sessions/<id>/state.json`.

**Pro**: full isolation, existing Hermes code unchanged internally.  
**Con**: session switch = exec (slight flash), no shared memory.

### Option B: Thread-per-session (complex)

All sessions run as asyncio tasks in one process. Each session has its own
`HermesApp` instance running on a separate `Screen`. Switch = `app.push_screen()`.

**Pro**: instant switching, shared config + theme.  
**Con**: requires Textual multi-screen architecture; agent threads share process
memory (GIL contention, harder isolation).

**Recommendation: Option A first.** Simpler, ships faster, can be upgraded later.

---

## Config

```yaml
sessions:
  enabled: false
  session_dir: "/tmp/hermes-sessions"
  max_sessions: 8
  bar_position: "bottom"        # "bottom" | "top" | "status-bar"
  auto_prune_orphans: false
```

---

## Files that move together

- `hermes_cli/tui/session_manager.py` (NEW) — `SessionRecord`, `SessionManager`,
  `SessionBar` widget, `NewSessionOverlay`, merge flow
- `hermes_cli/tui/overlays.py` — extend `WorkspaceOverlay` with tab strip +
  `_SessionsTab` panel
- `hermes_cli/tui/app.py` — session bar mount, `/sessions` slash cmd, `Alt+N`
  bindings, hint bar notification
- `hermes_cli/config.py` — `sessions` block in `DEFAULT_CONFIG`
- `tests/tui/test_session_manager.py` (NEW) — SessionRecord, SessionBar, create/kill/merge flows

---

## Out of scope (this spec)

- Side-by-side split view within one terminal window
- Session sharing / collaboration
- Remote sessions (SSH)
- Session persistence across machine reboots
- Auto-spawning sessions based on agent task type

---

## Open questions

1. **Attach mechanism**: `os.execvp` vs socket IPC vs `subprocess` + pty?
   Needs prototype to pick.
2. **Session bar position**: below StatusBar crowds bottom chrome further. Above
   HintBar might be better. Or integrate into StatusBar as scrolling segment?
3. **Background agent output**: does output accumulate in a ring buffer (capped),
   or full history? Memory implications if sessions run for hours.
4. **Merge strategy defaults**: squash is safest (clean history) but loses
   commit granularity. Make per-session default configurable?
5. **WorkspaceOverlay tab mechanism**: current overlay has no tab strip — needs
   a `_TabBar` widget. Reuse completion list styling or new component?

---

## Phasing

| Phase | Scope | Tests |
|---|---|---|
| A | `SessionManager` + `SessionRecord` + `SessionBar` widget + config | ~20 |
| B | `NewSessionOverlay` + create/kill flows + `/sessions` commands | ~20 |
| C | WorkspaceOverlay Sessions tab | ~15 |
| D | Merge flow + merge UI | ~20 |
| E | Background status notifications + hint bar | ~10 |

~85 tests total. Each phase ships independently behind the feature flag.
