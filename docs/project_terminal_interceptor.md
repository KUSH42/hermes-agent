---
name: Terminal output interceptor
description: Command-aware output shaping spec (git diff, pytest, ruff summaries) — abandoned for now
type: project
originSessionId: 3c2b8958-32c1-4537-ae98-f1296fb86d50
---
Spec at /home/xush/.hermes/2026-04-05-terminal-output-interceptor-*.md (3 files). Drafted 2026-04-05.

Goal was a deterministic interception layer that summarises common command output (git diff, pytest, ruff, git status) to reduce token waste, with raw-output escape hatches.

**Why abandoned:** Predates most of the TUI migration; deprioritised in favour of TUI work. No implementation exists.
**How to apply:** Do not implement unless user explicitly revives it. If revived, start from the tier-1 spec file.
