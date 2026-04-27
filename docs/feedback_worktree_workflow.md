---
name: Worktree workflow — prefer worktrees for parallel/isolated work
description: Use git worktrees for parallel tasks; merge into main
type: feedback
originSessionId: fabddc2c-d47d-48d7-b471-ed71bcd6cb43
---
Prefer git worktrees for any non-trivial feature or fix to enable parallelism and isolation.

**Why:** User runs multiple Claude instances and wants parallel progress without file conflicts. Worktrees keep branches isolated; main session stays clean for coordination.

**How to apply:**

**Starting a task:**
- Suggest a worktree if the task is self-contained and touches a bounded set of files
- Branch off `main` (not the current feature branch) unless told otherwise
- Typical setup: `git worktree add ../hermes-next -b feat/TASK-NAME main`

**During work in a worktree:**
- Keep commits atomic and well-described
- Update skill files as part of the work (same session, same branch)

**Finishing a task:**
- Run tests, commit everything, report done with branch name

**Detecting if currently in a worktree:**
`git rev-parse --git-dir` → `.git` = main repo; absolute path containing `worktrees/` = linked worktree.
