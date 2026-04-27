---
name: New branches must be based on main
description: Always branch from main unless the user explicitly says otherwise
type: feedback
originSessionId: ab716edc-a720-42ce-9f8f-fa34e998042a
---
Always create new branches from `main`, not from the current working branch.

**Why:** User has had to correct this multiple times — branching off a feature branch pulls in unrelated commits and pollutes the new branch's history.

**How to apply:** When creating any new branch (git checkout -b, git switch -c), use `main` as the base by default. Only branch off a non-main branch if the user explicitly specifies a different base.

**Exception (hermes-agent TUI work):** New TUI feature branches should be based on `feat/textual-migration`, NOT `main`. The textual migration branch is the active development trunk for all TUI work. Confirmed 2026-04-21 when user corrected a `main`-based worktree for parallel sessions.
