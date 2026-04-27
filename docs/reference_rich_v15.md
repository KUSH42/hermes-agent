---
name: Rich v15 upgrade notes
description: Upgraded Rich from 14.2→15.0.0; pin updated; key fixes relevant to TUI
type: reference
originSessionId: c195eec4-500f-447e-857a-7fb5508fb020
---
Upgraded 2026-04-12. `pyproject.toml` pin changed from `"rich>=14.3.3,<15"` to `"rich>=15.0.0,<16"`.

**Key changes in v15.0.0:**
- Python 3.8 support dropped (project requires >=3.11, no impact)
- `Text.from_ansi()` now preserves newlines instead of removing them — improves streaming output rendering in `LiveLineWidget._commit_lines()` and `StreamingToolBlock._flush_pending()`
- `FileProxy.isatty()` now delegates to underlying file — Textual terminal detection more reliable
- No breaking API changes

**How to apply:** No code changes needed. The ANSI fix is a pure improvement for streaming text rendering. Tests continue to pass.
