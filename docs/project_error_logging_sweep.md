---
name: Error Logging Sweep spec
description: IMPLEMENTED 2026-04-24; EL-1..EL-7; 18 bare swallows across 7 modules now log; 24 tests; commit f2c01fa5
type: project
originSessionId: 46826cd4-d5f3-4e7d-9d37-a637197957ed
---
Error logging sweep across 7 TUI modules — H-1/H-4/H-5/H-6/H-7/H-8/M-5 from tui-audit-2026-04-24.md.

**Why:** 18 `except Exception: pass` blocks silently dropped failures (context menu actions, yt-dlp, SDF baking, headless IPC, inline images). No control-flow changes — pure observability.

**How to apply:** Spec is at `/home/xush/.hermes/2026-04-24-error-logging-sweep-spec.md` (IMPLEMENTED). All 7 files now have `import logging; logger = logging.getLogger(__name__)`. Test file: `tests/tui/test_error_logging_sweep.py` (24 tests).

- EL-1 `_browse_types._is_in_reasoning` → `logger.debug`
- EL-2 `completion_overlay` on_mount/on_resize/_clear_candidate → `logger.debug`
- EL-3 `headless_session` write/on_complete → `logger.warning`; read/get_branch → `logger.debug`
- EL-4 `inline_prose` TGP/halfblock render + kitty delete → `logger.debug`
- EL-5 `context_menu` action failures → `logger.exception` + `app.notify`; focus-restore → `logger.debug`
- EL-6 `media_player` yt-dlp → `logger.warning`; config read → `logger.debug`
- EL-7 `sdf_morph` SDFBaker.bake → `logger.warning` before `failed.set()`
