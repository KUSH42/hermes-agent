---
name: Session Manager Hardening spec
description: SM-1/SM-2/SM-3 hardening of session_manager.py — lock, dead-code removal, atomic write
type: project
originSessionId: 2d8a8c3d-8a92-45e3-8ac3-de770799d340
---
IMPLEMENTED 2026-04-24 on branch feat/textual-migration.

**Why:** H-2/H-3/M-8/M-9/M-14/L-20 from tui-audit-2026-04-24.md — thread-safety race in _NotifyListener, crash-safety gap in SessionIndex.write(), dead orphan-detection cluster.

Changes:
- SM-1: `_NotifyListener._lock = threading.Lock()` guards `_sock` reads/writes in `stop()`/`_run()`/finally; `_handle` logs dispatcher errors via `logger.warning(exc_info=True)` instead of bare pass
- SM-2: deleted `is_alive`, `_verify_cmdline`, `get_orphans` from `SessionManager`; deleted 5 corresponding tests from `test_session_manager.py`
- SM-3: `SessionIndex.write()` replaced truncate-in-place with `tempfile.mkstemp` + `os.replace` under flock — crash-safe atomic update
- Added `import logging`, `import tempfile` to `session_manager.py`
- New test file: `tests/tui/test_session_manager_hardening.py` (16 tests)

**How to apply:** `is_alive`/`get_orphans` are gone — do not reference them. `write()` is now crash-safe; the lock file (`a+`) is separate from the temp file being written.
