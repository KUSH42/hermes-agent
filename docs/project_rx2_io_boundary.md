---
name: RX2 I/O boundary enforcement
description: DONE 2026-04-22; io_boundary.py centralizes all TUI blocking I/O; 5 public helpers, scan_sync_io, 63 tests, 9 call sites migrated, merged feat/textual-migration
type: project
originSessionId: aeb28b9a-95b3-4ebe-ba26-95398b098059
---
All TUI subprocess/blocking I/O centralized in `hermes_cli/tui/io_boundary.py`.

**Why:** Scattered blocking calls (subprocess.run, open(), xclip, xdg-open) were leaking onto the event loop, causing TUI freezes and hard-to-trace hangs.

**How to apply:** All new subprocess/file I/O in the TUI must use the io_boundary helpers. Use `# allow-sync-io: <reason>` (≥3-char reason) to exempt a line from the boundary scanner.

## Public API

```python
safe_run(caller, cmd, *, timeout, input_bytes=None, on_success=None, on_error=None, on_timeout=None)
safe_open_url(caller, url, *, on_error=None)
safe_edit_cmd(caller, path, *, on_error=None)
safe_read_file(caller, path, *, on_success, on_error=None)
safe_write_file(caller, path, content, *, mode="w", mkdir_parents=False, on_error=None)
cancel_all(caller)
scan_sync_io(paths) -> list[tuple[str, int, str]]
```

## Key contracts

- `_safe_callback`: `except RuntimeError: raise` BEFORE `except Exception: pass` — RuntimeError = called from event-loop thread (bug); must not be swallowed
- `safe_run.on_error(exc, stderr: str)` is **2-arg**; all other `on_error` are **1-arg**
- `safe_open_url` adapts internally: `lambda exc, _: on_error(exc)` when wrapping safe_run
- `_suspend_busy` flag on HermesApp: `safe_edit_cmd` + `IOService.play_effects_async` both guard it (check before try, set as first line inside try, reset in finally)
- `_validate_path` checks forbidden chars (`{';', '|', '&', '`', '\n', '\r', '\x00'}`) BEFORE `Path.resolve()` — null bytes crash resolve

## Migrated call sites (Phase B)

1. `input/_history.py:_save_to_history` — `safe_write_file` (replaces open() append)
2. `input/widget.py:middle-click` — `safe_run(xclip -selection primary -o)`
3. `services/context_menu.py:open_external_url` — `safe_open_url` (thread wrapper deleted)
4. `services/context_menu.py:open_path_action` — `safe_open_url` + `_err_fired` flag for sync-validation edge case
5. `services/theme.py:copy_text_with_hint` — `safe_run(xclip -selection clipboard -i)`
6. `desktop_notify.py:notify` — `safe_run` for all 4 subprocess.run calls; `_run()` + `threading.Thread` deleted; now takes `caller: App | Widget`
7. `math_renderer.py:_build_mermaid_cmd` — returns None when BOTH mmdc AND npx unavailable
8. `widgets/code_blocks.py:_try_render_mermaid_async` — `safe_run` (threading.Thread deleted)
9. `services/io.py:play_effects_async` — `_suspend_busy` guard added

## Permanent exemptions (# allow-sync-io)

- `session_manager.py` flock-locked writes — OS-level lock already off-loop
- `desktop_notify.py` `_verify_cmdline` — dead code path; `get_orphans()` has zero external callers
- `_CPYTHON_FAST_PATH` guard — module-level probe, runs once at import

## Boundary scanner

`scan_sync_io(paths)` — AST-based; `# allow-sync-io: <reason>` exempts in [lineno-2, lineno+2] window. T-BOUND-02 is hard-fail (no skipif) — boundary test always-on in CI.

## Test file

`tests/tui/test_io_boundary.py` — 63 tests, all spec IDs (T-RUN-*, T-URL-*, T-EDIT-*, T-READ-*, T-WRITE-*, T-BOUND-*, T-NOTIFY-*, T-CANCEL-*)
