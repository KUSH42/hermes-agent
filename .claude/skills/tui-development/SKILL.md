---
name: tui-development
description: >
  Textual 8.x TUI development for the hermes-agent project. Covers widget patterns,
  thread safety, testing with run_test/pilot, CSS theming, reactive state, and all
  known Textual 8.x gotchas. TRIGGER when: building, fixing, or auditing hermes TUI
  components; adding new widgets, overlays, animations, or bindings.
version: "2.0"
author: Hermes Agent
metadata:
  hermes:
    tags: [tui, textual, ui, widgets, css, testing, reactive]
    related_skills: [systematic-debugging, test-driven-development]
---

# TUI Development — Hermes Agent

---

## Codebase structure

### HermesApp mixin map + services layer (R4)

**R4 architecture (complete, all 4 phases merged)**: All 10 `_app_*.py` mixin files deleted. `HermesApp(App)` — no mixin bases. Logic lives in `hermes_cli/tui/services/`. Forwarder methods (`watch_X`, `on_key`, `_handle_tui_command`, etc.) are inlined directly at the bottom of `HermesApp` in `app.py` (2654 lines).

**R5 DEPRECATED stub cleanup (2026-04-23, commit 864ac9fe)**: 11 zero-external-caller DEPRECATED forwarder stubs deleted from app.py — `_cell_width`, `_input_bar_width`, `_next_spinner_frame`, `_helix_width`, `_helix_spinner_frame`, `_build_helix_frames` (spinner group); `_mount_minimap_default` (browse); `_append_attached_images`, `_insert_link_tokens`, `_drop_path_display`, `_handle_file_drop_inner` (watchers). **64 DEPRECATED markers remain** — all have live external callers in services/ or tests/; do not delete without migrating callers first.

Remaining `_app_*.py` files (NOT mixins — keep them):
- `_app_constants.py` — `KNOWN_SLASH_COMMANDS` and other module-level constants
- `_app_utils.py` — `_CPYTHON_FAST_PATH`, `_log_lag`, `_run_effect_sync`
- `_browse_types.py` — `BrowseAnchorType`, `BrowseAnchor`, `_is_in_reasoning`

**Deleted files** (all logic now in services/):
`_app_io.py`, `_app_spinner.py`, `_app_tool_rendering.py`, `_app_browse.py`, `_app_context_menu.py`, `_app_sessions.py`, `_app_theme.py`, `_app_commands.py`, `_app_watchers.py`, `_app_key_handler.py`

**Services layer** (`hermes_cli/tui/services/`) — the real logic owners:

| Service | `app._svc_X` | Key methods |
|---|---|---|
| `ThemeService` | `_svc_theme` | `flash_hint`, `apply_skin`, `copy_text_with_hint`, `set_status_error`, `get_selected_text` |
| `SpinnerService` | `_svc_spinner` | `tick_spinner`, `set_hint_phase`, `compute_hint_phase`, `set_chevron_phase` |
| `IOService` | `_svc_io` | `consume_output`, `commit_lines`, `flush_output` |
| `ToolRenderingService` | `_svc_tools` | `mount_tool_block`, `open/close_streaming_tool_block`, `set_plan_batch`, `mark_plan_running/done` |
| `BrowseService` | `_svc_browse` | `on_browse_mode`, `rebuild_browse_anchors`, `jump_anchor`, `focus_tool_panel` |
| `SessionsService` | `_svc_sessions` | `init_sessions`, `switch_to_session`, `create_new_session`, `refresh_session_bar` |
| `ContextMenuService` | `_svc_context` | `show_context_menu_at`, `build_context_items`, `copy_text`, `paste_into_input` |
| `CommandsService` | `_svc_commands` | `handle_tui_command`, `initiate_undo`, `run_rollback_sequence`, `handle_layout_command` |
| `WatchersService` | `_svc_watchers` | `on_size/compact/voice_mode`, `on_clarify/approval/sudo/secret/undo/status_error`, `handle_file_drop` |
| `KeyDispatchService` | `_svc_keys` | `dispatch_key`, `dispatch_input_submitted` |
| `BashService` | `_svc_bash` | `run(cmd)`, `kill()`, `is_running`, `_exec_sync`, `_finalize` |
| `AgentLifecycleHooks` | `hooks` | `register/unregister/fire/snapshot` — RX4 cleanup registry |

**Service init order in `__init__`** (load-bearing — watchers/keys depend on all others existing):
```python
self.hooks (RX4)  ← instantiated first, before R4 services
self._svc_theme → _svc_spinner → _svc_io → _svc_tools → _svc_browse
→ _svc_sessions → _svc_context → _svc_commands → _svc_bash
→ _svc_watchers → _svc_keys
```

**Service method naming rules:**
- Drop leading `_` from private helpers (e.g. `_flash_hint` → `flash_hint`)
- `watch_X` stays on App/mixin (Textual calls by convention); service gets `on_X(value)`
- Textual event handlers (`on_key`, `on_hermes_input_submitted`, `on_text_area_changed`) stay on mixin as forwarders; service gets `dispatch_X(event)`
- `@work` decorators stay on mixin adapters; service gets bare `async def`
- Public permanent API (e.g. `handle_file_drop`, `flush_output`) — no `# DEPRECATED` comment on mixin
- Private adapters — add `# DEPRECATED: remove in Phase 3` comment on mixin

**`_flash_hint` exception**: stays on App/mixin routing via `FeedbackService` (RX1 Phase B) — NOT `_svc_theme`. Do NOT change to `_svc_theme.flash_hint()`.

Class declaration (R4 — no mixin bases):
```python
class HermesApp(App):
```

### Module split map

| Original file | Split into |
|---|---|
| `app.py` | `hermes_cli/tui/services/` — all 10 `_app_*.py` mixin files deleted in R4; logic moved to service classes |
| `drawille_overlay.py` | `anim_engines.py` (engines) + core |
| `tool_blocks.py` | `tool_blocks/` subpackage: `_shared.py`, `_header.py`, `_block.py`, `_streaming.py` |
| `widgets/renderers.py` | `code_blocks.py`, `inline_media.py`, `prose.py` (renderers.py kept as re-export shim) |
| `input_widget.py` (908L) | `input/` subpackage: `_constants.py`, `_history.py`, `_path_completion.py`, `_autocomplete.py`, `widget.py` |
| `body_renderer.py` (deleted) | `body_renderers/streaming.py` — legacy streaming classes now live here |

`input_widget.py` kept as a 5-line backward-compat shim — all old importers unchanged.

### Body renderer architecture

Two parallel renderer systems exist — do **not** unify their APIs:

**`body_renderers/streaming.py`** — per-line streaming during live tool execution (moved from deleted `body_renderer.py`):
- Base: `StreamingBodyRenderer` (was `BodyRenderer`; renamed to avoid clash with ABC)
- Factory: `StreamingBodyRenderer.for_category(ToolCategory) → StreamingBodyRenderer`
- API: `render_stream_line()`, `finalize()`, `preview()`, `render_diff_line()`, `highlight_line()`
- Subclasses: `ShellRenderer`, `CodeRenderer`, `FileRenderer`, `SearchRenderer`, `WebRenderer`, `AgentRenderer`, `TextRenderer`, `MCPBodyRenderer`, `PlainBodyRenderer`
- Import: `from hermes_cli.tui.body_renderers.streaming import StreamingBodyRenderer`

**`body_renderers/` (ABC, Phase C)** — post-hoc rich rendering after tool completion:
- Base: `BodyRenderer` (ABC, `body_renderers/base.py`)
- Factory: `pick_renderer(cls_result, payload)` in `body_renderers/__init__.py`
- API: `can_render()`, `build()`, `build_widget()`
- Import: `from hermes_cli.tui.body_renderers import pick_renderer, FallbackRenderer`

Call sites for streaming path: `tool_panel.py`, `execute_code_block.py`, `tool_blocks/_block.py`, `write_file_block.py` — all import `StreamingBodyRenderer` from `body_renderers.streaming`.

### Parallel sessions architecture

- Each session = git worktree + branch + process. Active: `HermesApp` (full TUI). Background: `HeadlessSession` (no Textual import).
- Session data in `session_dir/sessions.json` (fcntl.flock on writes); each session has `state.json`, `notify.sock`, `output.jsonl`.
- **Session switch** via `self.exit(callback=lambda: os.execvp(...))` — never call `execvp` from the event loop. Flush to `output.jsonl` before exec.
- **Headless output hook**: module-level `_output_hook: Optional[Callable] = None` in `cli.py`; `_cprint` calls it if set; `HeadlessSession.__init__` sets it; `_on_complete` clears it.
- **Cross-process notify**: background sends newline-delimited JSON to active session's `notify.sock`; `_NotifyListener` daemon calls `app.call_from_thread(...)` on receipt.
- **Socket path limit**: ~104 chars (macOS) / ~108 chars (Linux) — validate on create. Startup-race notifications silently dropped — acceptable.
- **Dock stacking**: multiple `dock: bottom` widgets stack bottom-to-top in compose order. `_SessionNotification` uses `layer: overlay` + `dock: bottom` to float above without disturbing others.
- **Orphan detection**: `os.kill(pid, 0)` + `/proc/<pid>/cmdline` check for `--worktree-session-id <id>` guards against PID reuse.
- **Branch pre-validation**: run `git show-ref --verify --quiet refs/heads/<branch>` before `git worktree add` for cleaner error without partial state.
- **2s polling**: `SessionIndex.read()` in event loop is fine at 2s (tiny JSON, ~0.1ms). Move to worker only on slow filesystems.

---

## Subsystem reference

### io_boundary (`hermes_cli/tui/io_boundary.py`)

All TUI subprocess and hot-path file I/O must route through these helpers. `scan_sync_io` enforces this — `T-BOUND-02` hard-fails on unexempted violations.

```python
from hermes_cli.tui.io_boundary import (
    safe_run, safe_open_url, safe_edit_cmd,
    safe_read_file, safe_write_file, cancel_all, scan_sync_io,
)
```

- `safe_run(caller, cmd, *, timeout, on_success=None, on_error=None, on_timeout=None, ...)` — **must be called from event loop**. `on_error(exc, stderr)` is 2-arg; all other `on_error` callbacks are 1-arg.
- `safe_open_url(caller, url, *, on_error=None)` — validates URL (http/https/file/mailto only). **Bare file paths fail** — always convert: `path.resolve().as_uri()` → `file:///tmp/foo.txt`.
- `safe_edit_cmd(caller, cmd_argv, path, *, line=None, on_exit=None, on_error=None)` — terminal editor via `App.suspend()`. `_suspend_busy` flag prevents collision with TTE effects.
- `cancel_all(app)` — wired into `HermesApp.on_unmount`.
- `# allow-sync-io: <reason>` (≥3 chars) exempts a call-site. Scanner window: `[lineno-2, lineno+2]`.
- Worker cancellation does NOT kill the subprocess; callbacks in cancelled workers are silently dropped.
- Every callback touching `self.*` must start `if not self.is_mounted: return`.

**Test patch targets** — `_open_external_direct` shim was deleted 2026-04-24. Patch `hermes_cli.tui.tool_panel.safe_open_url`, not `subprocess.Popen`. Extract `on_error` from `mock.call_args.kwargs` and invoke manually.

### FeedbackService (`hermes_cli/tui/services/feedback.py`)

Unified flash/feedback for HintBar, ToolHeader, CodeBlockFooter. Accessed as `app.feedback`.

- `app.feedback.flash(channel_id, msg, *, duration, priority)` — event-loop-only.
- Priority: `P1 > P0` preempts; same = replaces; lower = blocked. `key=` replaces regardless of priority.
- `cancel()` calls `adapter.restore()`; preempt does NOT (prevents overwrite-race).
- `on_agent_idle()` only restores when no flash active (E3 fix).
- Channel IDs: `"hint-bar"` (lifecycle-aware), `"tool-header::<panel-id>"`, `"code-footer::<id>"`.
- `app.feedback.peek("hint-bar")` — passive check, no re-render triggered.
- `_flash_hint()` on App routes to `feedback.flash("hint-bar", ...)` — do NOT call `_svc_theme.flash_hint()`.

### ToolHeader (`tool_blocks/_header.py`)

`_DROP_ORDER` (current): `["linecount", "duration", "chip", "hero", "diff", "stderrwarn", "exit", "remediation", "chevron", "flash"]`
- Flash is last — user-action feedback survives until very end.
- `exit` segment only renders for shell-category tools with non-None `exit_code`.
- `remediation` renders when `is_collapsed and _is_complete and _tool_icon_error`.
- B-1: non-interactive tools get `·` placeholder in chevron slot (not empty).

### InterruptOverlay (`overlays/interrupt.py`)

Single widget handles 7 interrupt kinds (CLARIFY/APPROVAL/SUDO/SECRET/UNDO/NEW_SESSION/MERGE_CONFIRM) via FIFO queue. Lives on `layer: interrupt` (above `overlay`, below `tooltip`).

- `present(payload, replace=False)` — FIFO queue; `replace=True` for same-kind re-present.
- `preempt=True` — pushes current to queue front, activates new one.
- `dismiss_current("__cancel__")` — the canonical dismiss path from `KeyDispatchService`.
- `_confirm_destructive_id` must be cleared AFTER `_current_payload = None` in `_teardown_current` — order is load-bearing.
- `app.focus()` does not exist in Textual 8.x — use `app.screen.focus()`.
- Textual 8.x has no CSS `+` or `~` sibling combinators — use Python class toggles instead.
- `AnimConfigPanel.on_blur` must bail when `InterruptOverlay.has_class("--visible")` or focus trap re-steals focus every tick.

### ResponseFlowEngine (`hermes_cli/tui/response_flow.py`)

- `_init_fields()` initialises all 26 app-independent instance fields. Both `ResponseFlowEngine` and `ReasoningFlowEngine` call it first in `__init__`. **New fields go in `_init_fields()` only** — `ReasoningFlowEngine` inherits automatically.
- `_LineClassifier` — 13 pure detection methods, no mutable state. Instantiated as `self._clf`.
- `process_line()` dispatcher uses `elif` — **do not change to `if`**. IN_INDENTED_CODE/IN_SOURCE_LIKE close paths return `False` from `_dispatch_non_normal_state` to fall through to prose.

### StatusBar / HintBar (`widgets/status_bar.py`)

- `status_streaming: reactive[bool]` on HermesApp — bars dim to 55% opacity during streaming.
- `Widget.watch(app, attr, cb)` returns `None` — never store or stop handle. Textual auto-unregisters on unmount.
- Breadcrumb (S1-B) gates on `status_active_file_offscreen AND active_file AND width >= 60`. The `status_active_file_offscreen` flag is set by `OutputPanel.watch_scroll_y` — do NOT add `super().watch_scroll_y()` (ScrollableContainer doesn't define it → AttributeError).
- `import time as _time` must be at MODULE TOP in status_bar.py — never re-import inside render (fires every frame).

### PlanPanel (`widgets/plan_panel.py`)

- Key app reactives: `planned_calls`, `turn_cost_usd`, `turn_tokens_in`, `turn_tokens_out`, `plan_panel_collapsed`.
- `set_plan_batch` / `mark_plan_running(tool_call_id)` / `mark_plan_done(tool_call_id, is_error, dur_ms)` on `ToolRenderingService`.
- Never mutate `planned_calls` list in-place — always replace: `items = list(self.planned_calls); ...; self.planned_calls = items`.
- `_plan_tool_call_id` set on ToolPanels in `message_panel.py` else-branch (top-level only). NOT in `tools.py`.
- `_PlanEntry.on_click` → `BrowseService.scroll_to_tool(tool_call_id)` for jump-to-tool navigation.

### Input system (`input/widget.py` + mixins)

- `Enter-to-accept completion` must be in `_on_key` (not `action_submit`) — action_submit is called programmatically and must not be overlay-gated.
- Rev-search `_exit_rev_mode`: capture `match_idx = getattr(self, "_rev_match_idx", -1)` BEFORE setting `self._rev_match_idx = -1`. Pre-capture is load-bearing.
- `_refresh_placeholder()` is the single source of truth for input placeholder text — never set `self.placeholder` directly. Priority: locked > error > idle.
- `InputLegendBar` must be in flow layout (NOT dock:bottom) — sits above `#input-row` in compose order.

### Overlay architecture (`overlays/`)

- 5 canonical overlays: `ConfigOverlay` (7 tabs), `InterruptOverlay` (7 kinds), `HistorySearchOverlay`, `KeymapOverlay`, `ToolPanelHelpOverlay`.
- All pre-mounted, always in DOM. Show/hide via `--visible` CSS class only — never `mount()`/`remove()` at runtime.
- `ConfigOverlay.show_overlay(tab="model"|"skin"|...)` — routes `/model`, `/skin`, `/reasoning`, `/verbose`, `/yolo`.
- `_dismiss_all_info_overlays()` iterates `{ConfigOverlay, InterruptOverlay, HistorySearchOverlay, KeymapOverlay, ToolPanelHelpOverlay}`.
- Alias classes (e.g. `ModelPickerOverlay`) use `_AliasMeta` + registration in `_css_type_names` frozenset — both `query_one(Alias)` and `isinstance(obj, Alias)` work.

### Animation engines (`anim_engines.py`)

- 26 engines. New engines slot via `_ENGINE_META["category"]` — never add directly to `_PHASE_CATEGORIES` lists.
- `TrailCanvas.frame()` = `decay_all()` + render. Never call `tick()` (doesn't exist) or `decay_all()` separately.
- `_SIN_LUT`/`_COS_LUT` (1024 entries) + `_lut_sin`/`_lut_cos` — max error ~0.006, fine for visuals only.
- Bounds check (`if 0 <= x < w`) is 5–15% faster than `try/except` for out-of-bounds coords.
- `DrawbrailleOverlay` split pending (spec at `/home/xush/.hermes/2026-04-23-drawbraille-overlay-split-spec.md`): `anim_orchestrator.py` + `drawbraille_renderer.py` + thin shell + `widgets/anim_config_panel.py`.

### Skin / RX3 vars (`theme_manager.py`, `hermes.tcss`)

Adding a new component var requires **3 edits**:
1. `COMPONENT_VAR_DEFAULTS` in `theme_manager.py`
2. `$name: value;` declaration in `hermes.tcss` (required at TCSS parse time)
3. `component_vars:` entry in all 4 bundled skins (`matrix`, `catppuccin`, `solarized-dark`, `tokyo-night`)

`_defaults_as_strs()` / `_default_of(x)` — always use these instead of `dict(COMPONENT_VAR_DEFAULTS)` directly (T8 grep test enforces this).

`load_with_fallback` — 3-step chain: configured → bundled default → emergency `COMPONENT_VAR_DEFAULTS`. TUI always starts.

### R2 panes layout (`pane_manager.py`)

Flag-gated: `display.layout: "v2"`. Breakpoints: SINGLE < 120 cols, THREE 120–159, THREE_WIDE ≥ 160. `compute_layout(w, h)` is a pure function. `_apply_layout(app)` is idempotent — call from `_flush_resize` only, not `watch_size`.

`query_one(PaneContainer)` is ambiguous (3 instances) — always use `query_one("#pane-left")` etc.

---

New module `hermes_cli/tui/io_boundary.py` + 63 tests in `tests/tui/test_io_boundary.py`.

**Purpose:** All TUI subprocess calls and hot-path file I/O now route through typed helpers that dispatch off the event loop via `run_worker(thread=True, group="io_boundary")`. A pytest boundary scanner enforces no new violations.

**Public API:**
```python
from hermes_cli.tui.io_boundary import (
    safe_run, safe_open_url, safe_edit_cmd,
    safe_read_file, safe_write_file, cancel_all, scan_sync_io,
)
```

- `safe_run(caller, cmd, *, timeout, on_success=None, on_error=None, on_timeout=None, env=None, cwd=None, input_bytes=None, capture=True) -> Worker | None` — dispatches subprocess off event loop. **Must be called from the event loop** — validation-failure `on_error` fires synchronously on calling thread. Worker cancellation does NOT kill the subprocess. `on_error(exc, stderr: str)` is 2-arg; all other helpers use 1-arg `on_error(exc)`.
- `safe_open_url(caller, url, *, on_error=None)` — validates URL (allowlist: http/https/file/mailto; rejects javascript:/data:), resolves platform opener, calls `safe_run` internally. Adapts 1-arg `on_error` to 2-arg `safe_run` contract.
- `safe_edit_cmd(caller, cmd_argv, path, *, line=None, on_exit=None, on_error=None)` — terminal editor via `App.suspend()`. GUI editors fall through to `safe_open_url`. `_suspend_busy` flag prevents collision with TTE effects.
- `safe_read_file` / `safe_write_file` — 1-arg `on_error(exc)`, no stderr concept.
- `cancel_all(app)` — wired into `HermesApp.on_unmount`; cancels all `"io_boundary"` group workers.
- `scan_sync_io(paths: Iterable[Path]) -> list[tuple[Path, int, str]]` — AST scanner; returns `(file, lineno, call_name)` for unexempted violations.

**`_safe_callback(app, cb, *args)` contract:**
```python
if cb is None: return
try:
    app.call_from_thread(cb, *args)
except RuntimeError:
    raise  # called from event loop = programming bug; do not swallow
except Exception:
    pass   # broken callback logic; silently drop
```
Only call from inside a worker thread. Callbacks execute on the event loop — call widget methods directly, never wrap in another `call_from_thread`.

**Callback rules:**
1. `on_success(stdout, stderr, returncode)` / `on_error(exc, stderr)` / `on_timeout(elapsed_s)` — all fire on event loop via `_safe_callback`.
2. Every callback that touches `self.*` must start with `if not self.is_mounted: return` (worker path only — sync validation-failure paths don't need this).
3. `get_current_worker().is_cancelled` — checked before subprocess.run AND before dispatching callbacks; cancelled workers drop callbacks silently.

**`_suspend_busy` flag:** `HermesApp._suspend_busy: bool = False` added in `__init__` after `self.hooks`. `safe_edit_cmd` checks it and fires `on_error(SuspendBusyError)` if set. `IOService.play_effects_async` also guards it (check before try, set as first line inside try, reset in finally).

**Boundary enforcement:**
- `# allow-sync-io: <reason>` (≥3 char reason) exempts a call-site from the scanner. Window: `[lineno-2, lineno+2]`.
- `T-BOUND-02` (`test_no_sync_io`) hard-fails on any unexempted `subprocess`/`open()` in `hermes_cli/tui/**/*.py`. Phase C removed the `skipif` — it's always-on.
- Scanner false-negatives: aliased imports (`import subprocess as _sp`) and `path_var.open(...)` (non-inline Path) are NOT caught. Pre-step 0 covered these with explicit exemption comments.

**Migrated call sites (Phase B, 9 steps):**
- `math_renderer.py` — `render_mermaid` split into `_build_mermaid_cmd(code) → (cmd, mmd_tmp, png_tmp) | None`; `code_blocks._try_render_mermaid_async` now uses `safe_run`; bare `threading.Thread` deleted.
- `tool_panel.py` — `FooterPane.on_button_pressed`, `action_open_primary` (both branches), `action_open_url` → `safe_open_url` / `safe_edit_cmd`.
- `widgets/status_bar.py` — `SourcesBar.on_button_pressed` → `safe_open_url`.
- `services/context_menu.py` — `open_external_url` thread wrapper deleted; `open_path_action` → `safe_open_url` with optimistic `flash_success()` + `_err_fired` guard for sync-validation-failure edge case.
- `services/theme.py` — xclip fallback in `copy_text_with_hint` → `safe_run`.
- `input/widget.py` — middle-click xclip → `safe_run`; callback guards `is_mounted and out`.
- `input/_history.py` — per-submit `open()` → `safe_write_file(mode="a", mkdir_parents=True)`.
- `desktop_notify.py` — all 4 `subprocess.run` + daemon thread (`_run()` + `threading.Thread`) deleted; `notify(title, body, *, caller, sound=..., sound_name=...)` now calls helpers directly via `safe_run`; `_maybe_notify` in `app.py` passes `caller=self`.

**Permanent exemptions (pre-step 0 — `# allow-sync-io:` comments added):**
- `services/bash_service.py` — long-lived Popen in `@work(thread=True, group='bash')`
- `media_player.py` — long-lived mpv handle, managed lifecycle
- `headless_session.py` — init-time, one-shot, no event loop running
- `workspace_tracker.py` — git calls already in `run_worker` worker context
- `session_manager.py:62` — flock-locked write, atomicity required
- `session_manager.py _verify_cmdline` — dead code (`get_orphans()` has no callers)
- `_app_utils.py:33` — module-level lag logger, <100 bytes, negligible
- Various `PILImage.open()` — already in worker threads

**Gotchas:**
- `safe_run` must be called from the event loop — validation-failure `on_error` fires synchronously on the calling thread.
- `safe_open_url` optimistic success: call `flash_success()` after `safe_open_url` returns; if URL validation fails synchronously, `on_error` fires first then `flash_success()` overwrites it. Use `_err_fired` flag if the overwrite is unacceptable.
- `desktop_notify.notify()` now requires `caller` kwarg — any new call site must pass `self` or `self.app`.
- `_build_mermaid_cmd` returns `None` only when BOTH mmdc AND npx are unavailable.
- Scanner does not catch aliased subprocess imports (`import subprocess as _sp`) — verify manually with `grep -rn "import subprocess as\|_sp\."`.
- **`safe_open_url` requires a URL with a scheme** — bare file paths like `/tmp/foo.txt` fail `_validate_url` with `"missing scheme"`. Always convert: `path.resolve().as_uri()` → `file:///tmp/foo.txt`. The `is_url = "://" in target` check determines which branch to use.
- **`_open_external_direct` shim deleted (2026-04-24)** — `tool_panel.py` previously had a `getattr(subprocess, "Popen")` indirection to dodge the scan. It is gone. Tests that patched `subprocess.Popen` for tool_panel open actions must now patch `hermes_cli.tui.tool_panel.safe_open_url`. Error-flash tests must extract `on_error` from `mock.call_args.kwargs` and invoke it manually; `is_mounted` is a read-only property so use `patch.object(type(panel), "is_mounted", new_callable=PropertyMock, return_value=True)`.


## Lifecycle Hooks — cleanup outside watchers (RX4)

`AgentLifecycleHooks` (`hermes_cli/tui/services/lifecycle_hooks.py`) is a priority-ordered, error-isolated registry for cleanup that used to live inline in `watch_agent_running`. Accessed as `self.hooks` on `HermesApp`.

### Why

Every audit pass finds "forgot to reset X when Y happened". Cleanup was open-coded in whichever watcher observed the transition. 175-line `watch_agent_running` had 17+ side effects in source-line order with no enforced checklist. RX4 extracts cleanup into named callbacks registered against the transition they care about.

Division of labour:
- **Reactive watcher** → updates rendering state (CSS classes, `.display`, widget properties), then calls `hooks.fire(transition)` at the end.
- **Hook callback** → performs cleanup (clear attrs, reset timers, emit OSC, notify external subsystems). Never touches rendering.

### Transition names

| Transition | When |
|---|---|
| `on_turn_start` | `agent_running` False → True |
| `on_turn_end_any` | `agent_running` True → False (always) |
| `on_turn_end_success` | turn end, `status_error` empty |
| `on_turn_end_error` | turn end, `status_error` set |
| `on_interrupt` | turn end via ESC/resubmit — set `app._interrupt_source` before dispatching |
| `on_compact_complete` | `status_compaction_progress` → 0.0 |
| `on_error_set` | `status_error` "" → non-empty |
| `on_error_clear` | `status_error` non-empty → "" |
| `on_session_switch` | session label changes |
| `on_session_resume` | session loads on startup |
| `on_streaming_start` | first token of assistant response |
| `on_streaming_end` | last token of assistant message |

### Priority ranges

| Priority | Used for |
|---|---|
| 10 | Terminal state: OSC progress, desktop notify scheduling |
| 50 | Buffer flush: `flush_live`, `evict_old_turns` |
| 100 | Default / generic cleanups |
| 500 | Visual chrome: chevron pulses, hint phase |
| 900 | Input refocus / placeholder restore (runs last) |

### Registration pattern

Register in `on_mount`, not `__init__`, so `on_unmount` reliably deregisters:

```python
class MyService:
    def on_mount(self):
        self._handles = [
            self.app.hooks.register("on_turn_end_any", self._cleanup, owner=self, priority=100, name="my_cleanup"),
        ]

    def on_unmount(self):
        self.app.hooks.unregister_owner(self)
```

`owner=self` enables bulk cleanup via `unregister_owner(self)`. For bound methods, the registry uses `WeakMethod` — owner GC → registration silently pruned on next `fire`.

### Key gotchas

- **Do not set the reactive that owns the transition.** A callback on `on_turn_end_any` that sets `agent_running = True` re-enters immediately. Policy: callbacks must not set the reactive whose transition they're responding to.
- **Nested fires are allowed.** `fire("on_turn_end_any")` can call `fire("on_interrupt")` inside a callback. Each `fire` snapshots its registration list at entry — mid-fire register/unregister is safe.
- **`call_later` has no delay param.** For timed cleanup inside a callback (e.g. chevron 400 ms pulse), use `app.set_timer(delay, callback)` from inside the hook callback.
- **Pre-mount guard.** `fire` before `app.is_running` defers to `_deferred` queue; `drain_deferred()` is called from `on_mount`.
- **`**_` pattern.** Callbacks registered on transitions that carry `**ctx` (e.g. `on_interrupt` carries `source=`) must accept `**_` if they don't use the kwargs. Callbacks on both ctx-less and ctx-carrying transitions need `**_`.
- **`_interrupt_source` flag.** Set `app._interrupt_source = "esc"` (or `"resubmit"` / `"ctrl+shift+c"`) in `services/keys.py` (`KeyDispatchService`) before dispatching the interrupt. `watch_agent_running(False)` reads and clears it; fires `on_interrupt` if set.
- **Firing points.** `watch_agent_running` fires `on_turn_start/end_*`; `WatchersService.on_status_compaction_progress` fires `on_compact_complete`; `WatchersService.on_status_error` fires `on_error_set/clear`; `IOService.consume_output` fires `on_streaming_start/end`.

### Debug introspection

```python
snap = app.hooks.snapshot()  # dict[transition, list[name]]
# Returns {"on_turn_start": ["reset_turn_state", "osc_progress_start"], ...}
```

### Phase d — enforcement patterns

**AST snapshot test** — `TestPhaseD.test_registered_transitions_documented` in `tests/tui/services/test_lifecycle_hooks_phase_c.py` uses `ast.parse(textwrap.dedent(inspect.getsource(HermesApp._register_lifecycle_hooks)))` to extract every `h.register(...)` call and compares it against the `EXPECTED_SNAPSHOT` module-level constant (§9 table). When you add a new hook registration, you MUST:
1. Add the `h.register(...)` call in `_register_lifecycle_hooks`
2. Update `EXPECTED_SNAPSHOT` in the test file
3. Update `## 9. Registered callbacks` in the RX4 spec at `/home/xush/.hermes/2026-04-22-tui-v2-RX4-lifecycle-hooks-spec.md`

**Banned inline patterns** — `test_watch_agent_running_no_inline_reactive_cleanups` enforces that these patterns do NOT appear inline in `watch_agent_running`:
- `status_output_dropped = False`
- `spinner_label = `
- `status_active_file = `
- `_active_streaming_blocks.clear()`
- `_maybe_notify()`
- `_try_auto_title()`

**Watcher line budget** — `test_watchers_service_no_deep_inline_cleanup` enforces that `WatchersService` compaction-related methods have ≤ 3 inline cleanup statements.

---

## Framework: Textual 8.2.3

### Import paths

```python
from textual.app import App, ComposeResult
from textual.widgets import Static, Button, Input, RichLog, Label
from textual.containers import ScrollableContainer, Vertical, Horizontal
from textual import events, work
from textual.worker import get_current_worker
from textual.reactive import reactive
from textual.binding import Binding
from textual.geometry import Size
from textual.message import Message  # needed for inner Message subclasses
```

### Reactive state

```python
class MyApp(App):
    my_value: reactive[str] = reactive("")

    def watch_my_value(self, old: str, new: str) -> None:
        ...
```

Watchers run synchronously on the event loop. Never do blocking I/O in a watcher.

**`Widget.watch(obj, attr, cb)` returns `None` — never store or stop the handle.** The signature is `-> None`. Storing `self._h = self.watch(...)` then calling `self._h.stop()` in `on_unmount` raises `AttributeError: 'NoneType'.stop()` on every shutdown. Textual auto-unregisters cross-widget watchers when the observing widget unmounts. `on_unmount` should only stop timers/animations the widget owns (e.g. pulse/shimmer timers):

```python
def on_mount(self) -> None:
    self.watch(self.app, "status_streaming", self._on_change)  # no handle

def on_unmount(self) -> None:
    self._pulse_stop()  # own timer — stop it; watcher — Textual cleans it up
```

**Manually calling `watch_*` does NOT update the reactive value**: `widget.watch_has_focus(False)` invokes the callback but `widget.has_focus` stays unchanged. Track display state in a plain bool attribute the watcher writes to; read that, not the reactive, in other methods:

```python
def __init__(self):
    self._hint_visible: bool = False

def watch_has_focus(self, value: bool) -> None:
    self._hint_visible = value
    ...

def on_resize(self, event) -> None:
    if self._hint_visible:  # NOT self.has_focus
        self._set_hint(...)
```

**`int()` casts in watchers**: Tests that call `widget.watch_collapsed(False)` with a mock `_block` will trigger `len(mock._all_plain)` → MagicMock → TypeError. Wrap restore/expand blocks in `try/except` and cast explicitly:

```python
try:
    saved = int(self._saved_visible_start)
    total = int(len(self._block._all_plain))
except Exception:
    pass
```

### Worker pattern

**`call_from_thread` is only on `App`, not on `Widget`** (Textual 8.x). Inside a `@work(thread=True)` method on a widget, use `self.app.call_from_thread(fn)` — NOT `self.call_from_thread(fn)`. The latter raises `AttributeError` at runtime.

```python
@work(thread=True)   # CPU or blocking I/O
def _load_file(self) -> None:
    data = open(...).read()
    self.app.call_from_thread(self._display, data)  # NOT self.call_from_thread

@work            # async — runs in event loop
async def _do_search(self, query: str) -> None: ...

# Cancel previous before starting new:
def _search(self, query: str) -> None:
    self._search_worker = self.run_worker(self._do_search(query), exclusive=True)
```

### Thread safety

- `self.app.call_from_thread(fn, *args)` — schedule callback from worker thread. **Widget-level `self.call_from_thread` does not exist** in Textual 8.x.
- Never call `self.query_one()` or widget setters from a `@work(thread=True)` worker
- `get_current_worker().is_cancelled` — check cancellation in long loops

### MRO rules (mixins + Textual)

**Always list mixins BEFORE the Textual base class.** Textual bases (TextArea, Widget, App) define many methods — placing them first causes them to shadow your mixin's overrides:

```python
# WRONG — TextArea.update_suggestion shadows _HistoryMixin.update_suggestion
class HermesInput(TextArea, _HistoryMixin, can_focus=True): ...

# CORRECT — mixin found first in MRO
class HermesInput(_HistoryMixin, TextArea, can_focus=True): ...
```

This applies to `App` subclasses with multiple mixins too — see HermesApp declaration above.

**`PulseMixin`**: `PulseMixin.__init_subclass__` warns at class-definition time if `Widget` appears before `PulseMixin` in MRO. Use `class Foo(PulseMixin, Widget): ...`.

**Mixin self-references**: Mixins access attributes defined on the host class. Use `# type: ignore[attr-defined]` on all such accesses — at runtime `self` is always the concrete class:
```python
class _WatchersMixin:
    def watch_size(self, size: Any) -> None:
        self.query_one(HintBar)  # type: ignore[attr-defined]
        self._flash_hint("...", 2.0)  # type: ignore[attr-defined]
```

### BINDINGS

```python
BINDINGS = [
    Binding("ctrl+shift+a", "select_all", "Select all", show=False),
    Binding("f2", "show_usage", "Usage", show=True),
    Binding("escape", "dismiss", "Close", show=False),
]
```

**`ctrl+a` conflicts** with terminal select-all in many terminals — use `ctrl+shift+a`.

### compose() vs __init__ for widget attributes

Attributes assigned in `compose()` (e.g. `self._foo = Static(...)`) are only set after mounting. `hasattr(widget, "_foo")` fails on a freshly constructed (unmounted) widget. Declare in `__init__` as `self._foo: Static | None = None`; assign in `compose()`.

**Widgets dropped from `compose()` leave broken state references**: If a widget is no longer yielded in `compose()`, any `self._widget` reference becomes `None` and `self._widget.state = ...` silently fails or crashes. After a refactor, grep every `self._attr =` in `__init__`/`compose()` and confirm the widget is still yielded.

**Default placeholder must reach `TextArea.__init__`**: Assigning `self._idle_placeholder` after `super().__init__()` does NOT update the displayed placeholder:
```python
def __init__(self, *, placeholder: str = "", ...) -> None:
    _default = "Type a message  @file  /  commands"
    _effective = placeholder if placeholder else _default
    super().__init__(..., placeholder=_effective, ...)
    self._idle_placeholder: str = _effective  # keep in sync
```

### Overlay show/hide pattern

All overlays in this codebase use **pre-mount + `--visible` toggle**. Dynamically mounting/removing overlays breaks `_hide_all_overlays()` and requires `try/except NoMatches` everywhere.

```python
# In App.compose():
yield MyOverlay(id="my-overlay")  # always in DOM, display:none by default

# Show:
def show_overlay(self) -> None:
    self.add_class("--visible")
    try:
        self.query_one("#search-input", Input).value = ""  # reset stale state
    except NoMatches:
        pass
    self.call_after_refresh(self._focus_default)

# Hide:
def hide_overlay(self) -> None:
    self.remove_class("--visible")  # NOT self.remove()
```

Tests check `overlay.has_class("--visible")`, not DOM presence. `_hide_all_overlays()` iterates overlay classes and calls `remove_class("--visible")` — works because they're always in DOM.

**`query_one()` vs `query()` when the same class is pre-mounted**: If `App.compose()` mounts `ToolPanelHelpOverlay(id="tool-panel-help-overlay")` and a test mounts another instance, `query_one(ToolPanelHelpOverlay)` returns the pre-mounted one. Use `query()` whenever multiple instances can exist:

```python
# WRONG — finds pre-mounted widget, ignores test's instance
self.query_one(ToolPanelHelpOverlay).remove_class("--visible")

# CORRECT
for w in self.query(ToolPanelHelpOverlay):
    w.remove_class("--visible")
```

### CSS / TCSS

```css
/* Custom CSS variables MUST be declared in .tcss, not just get_css_variables() */
$spinner-shimmer-dim: #555555;
$spinner-shimmer-peak: #d8d8d8;

HelpOverlay > #help-content {
    scrollbar-size-vertical: 1;
    scrollbar-color: $text-muted 30%;
}
```

New `$var-name` refs must be declared in the `.tcss` file at parse time — `get_css_variables()` alone is insufficient.

**No CSS `+` or `~` sibling combinators** — Textual 8.x does not support them. Use Python class toggles on a parent instead:
```python
# WRONG — invalid in Textual TCSS
InterruptOverlay.--diff-visible + #diff-hint { display: block; }

# CORRECT — toggle class on parent
self.add_class("--diff-hint-visible")
```

**New component var requires 3 edits**: (1) `COMPONENT_VAR_DEFAULTS` in `theme_manager.py`, (2) `$name: value;` declaration in `hermes.tcss`, (3) `component_vars:` entry in all 4 bundled skins. T1/T2/T3 in `test_css_var_single_source.py` catch omissions.

**CSS class operations require `_classes`** (set by `DOMNode.__init__`): Calling `add_class`/`remove_class` on `object.__new__(SomeWidget)` raises `AttributeError`. In production methods exercised by unit tests, wrap CSS mutations:
```python
try:
    self.remove_class(f"-l{old}")
    self.add_class(f"-l{new}")
except AttributeError:
    pass
```

### HintBar / flash system

```python
# Timed flash (expires after duration seconds):
self._flash_hint("Message", 2.0)

# Respect timed flash before clearing — don't overwrite an active flash:
if _time.monotonic() >= self._flash_hint_expires:
    self.query_one(HintBar).hint = ""
```

Widget-level flash variants:
- `CodeBlockFooter.flash_copy()` — flashes "✓ Copied" for 1.5 s, CSS class `--flash-copy`
- `ToolHeader.flash_rerun()` — pulses glyph to "streaming" for 600 ms then restores `_last_state`

### CompletionOverlay

`THRESHOLD_COMP_NARROW = 80` — overlay gets `--narrow` CSS class when terminal width < 80. First-call guard: always apply narrow class when `_last_applied_w == 0`.

Add `--no-preview` class to hide `PreviewPanel` and expand `VirtualCompletionList`:
```css
CompletionOverlay.--no-preview PreviewPanel { display: none; }
CompletionOverlay.--no-preview VirtualCompletionList { width: 1fr; }
```

`watch_highlighted_candidate()` adds `--no-preview` to `CompletionOverlay` when candidate is `None`.

### AnimationClock

`AnimationClock.subscribe(divisor, cb)` clamps `divisor = max(1, int(divisor))` and logs a warning if clamped. Always pass integer divisors.

### Desktop notify gate

```python
# In __init__:
self._last_keypress_time: float = 0.0

# In on_key:
self._last_keypress_time = _time.monotonic()

# In _maybe_notify:
since_key = _time.monotonic() - self._last_keypress_time
if since_key < 5.0:
    return  # user is watching, skip notify
```

### Scroll

```python
# scroll_y setter — fine for reactive watchers, avoids double-repaint:
self.scroll_y = new_y
# Imperative scroll:
scroll_widget.scroll_to_widget(target_widget, animate=False)
```

### Local import shadowing module-level alias

```python
import time as _time  # module level

def watch_agent_running(self, value: bool) -> None:
    if value:
        import time as _time  # BUG: treats _time as local throughout the function
        self._turn_start_time = _time.monotonic()
    # Later in same function, value=False branch:
    if _time.monotonic() >= self._flash_hint_expires:  # UnboundLocalError!
```

Python sees any `import X as Y` assignment anywhere in a function scope and treats `Y` as local throughout. Never re-import inside a conditional branch.

### accessibility_mode()

```python
from hermes_cli.tui.constants import accessibility_mode
if accessibility_mode():
    # Use ASCII fallbacks instead of Unicode box-drawing chars
    ...
```

Reads `HERMES_NO_UNICODE` and `HERMES_ACCESSIBLE` env vars at call time — not cached at import.

### browse_mode watcher self-reset guard

`watch_browse_mode` immediately resets `self.browse_mode = False` if no ToolHeaders exist in DOM. Tests that set `app.browse_mode = True` directly will see it reset to False. Mount real ToolHeaders first, or test the render logic structurally via `inspect.getsource`.

---

## Testing patterns

### Running tests

**NEVER run `python -m pytest tests/tui/`** — full suite has 3700+ tests and takes ~16 minutes. Run only targeted files:

```bash
# Module-specific:
python -m pytest tests/tui/test_tool_blocks.py tests/tui/test_tool_panel.py -x -q --override-ini="addopts="

# Import check only for app.py:
python3 -c "from hermes_cli.tui.app import HermesApp; print('OK')"
```

Use `--override-ini="addopts="` to suppress rtk output suppression.

**After splits, run only files for the touched modules.** Do not run suites for unrelated modules.

### Basic async test structure

```python
@pytest.mark.asyncio
async def test_my_widget() -> None:
    from unittest.mock import MagicMock
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        widget = app.query_one(MyWidget)
        widget.some_attr = "value"
        await pilot.pause()
        assert widget.rendered_text == "expected"
```

- `await pilot.pause()` — let event loop tick (needed after reactive changes)
- `await pilot.pause(delay=0.3)` — wait for workers (file preview, etc.)
- `pilot.press("key")` may be consumed by the focused widget — call `app.on_key(mock_event)` directly to test app-level handlers
- Use `asyncio.get_running_loop()` not `asyncio.get_event_loop()` in sync pytest fixtures (Python 3.10+ deprecation)

### MagicMock gotchas

**`isinstance(MagicMock(spec=Cls), Cls)` is always False** — even with `spec=`. Use duck-typing:
```python
# WRONG — always False for MagicMock
if not isinstance(block, StreamingToolBlock):
    return

# CORRECT
if not hasattr(block, '_follow_tail'):
    return
```

**`getattr(mock, "_attr", False)` is truthy** — unset attrs on `MagicMock(spec=...)` return a `MagicMock()` object (truthy). Use identity check:
```python
# WRONG — fires for any unset attr (MagicMock() is truthy)
if getattr(block, "_completed", False):
    return

# CORRECT
if getattr(block, "_completed", False) is True:
    return
```

### `__new__`-created objects

Tests sometimes use `Cls.__new__(Cls)` to bypass Textual's Widget constructor. Every `self._attr` set in `__init__` is absent on such objects.

**In production code**, any method exercised by `__new__`-based tests MUST use `getattr(self, '_attr', default)`:
```python
# WRONG — AttributeError on __new__-constructed object
if self._detected_cwd:
    ...

# CORRECT
if getattr(self, '_detected_cwd', None):
    ...
```

**Prefer `Widget.__init__` over `__new__`**: `Widget.__init__` doesn't mount or compose — it's safe to call without a running app. `__new__` forces the test to maintain a parallel list of all instance attrs and breaks silently when `__init__` adds a new one. Only use `__new__` when `__init__` has custom logic that genuinely requires a running app.

### Patch targets after module splits

Patch at the module where the name is **defined**, not where it is used:

```python
# WRONG after split — spec_for now lives in tool_category.py
patch("hermes_cli.tui.tool_blocks.spec_for")

# CORRECT
patch("hermes_cli.tui.tool_category.spec_for")
```

After `input/` subpackage split, `input_widget.py` is a shim — it re-exports but doesn't re-import into its own namespace. Tests patching `hermes_cli.tui.input_widget.some_fn` must update to `hermes_cli.tui.input.widget.some_fn`.

**`safe_open_url` patch target** — `_open_external_direct` shim was deleted 2026-04-24. Patch `hermes_cli.tui.tool_panel.safe_open_url`, not `subprocess.Popen`. Extract `on_error` from `mock.call_args.kwargs` and invoke manually; use `patch.object(type(panel), "is_mounted", new_callable=PropertyMock, return_value=True)` for is_mounted guards.

### Overlay test fixtures

Tests using a minimal `_App` class must yield overlay widgets in `compose()`. Without them, actions that use `query_one(SomeOverlay)` silently no-op (caught `NoMatches`) and visibility assertions never fire:

```python
class _App(App):
    def compose(self):
        yield ToolPanelHelpOverlay()  # required
        yield MyWidget()

# Assert visibility state, not DOM presence:
assert not overlay.has_class("--visible")  # CORRECT
assert len(pilot.app.query(MyOverlay)) == 0  # WRONG — pre-mounted, always present
```

### Contradictory test pairs after refactors

A test written for old behavior (e.g. `assert "scroll_relative" in src`) conflicts with a new test (e.g. `assert mock.scroll_down.call_count >= 5`). When both exist and the old one passes while the new one fails, the old test codifies superseded design. Update the old test to match the new implementation.

### Unstaged modifications cause mysterious failures

Pre-session `M` files in `git status` may contain broken/reverted code that conflicts with the committed state. Run `git diff HEAD -- <file>` before assuming a test failure is in your changes.

### Ghost method calls

Always `grep -rn "def method_name"` before calling a method that was added in a recent refactor. Ghost calls (`_notify_group_header()` called but defined nowhere) silently no-op on real objects and crash on `__new__`-constructed ones.

### Animation engine performance patterns

**try/except vs bounds check:** Drawille raises on out-of-bounds coords. Replacing `try: canvas.set(x,y) except Exception: pass` with `if 0 <= x < w and 0 <= y < h: canvas.set(x,y)` is 5–15% faster per engine. Exception machinery is ~10× slower when it fires.

**Sin/cos LUT:** `_SIN_LUT`/`_COS_LUT` (1024 entries) + `_lut_sin(angle)`/`_lut_cos(angle)` live in `anim_engines.py`. Max error ~0.006 vs `math.sin` — fine for visual rendering, NOT for physics integration (RK4 etc.). Swap into hot per-pixel loops only.

**Divisor hoisting:** `max(w, 1)` / `max(h, 1)` inside inner loops should be hoisted to `w_inv = 1.0 / max(w, 1)` before the loop. Same for `max(row_len - 1, 1)` in `_render_multi_color`.

**Spatial grid for boid simulations:** `FlockSwarmEngine` uses `_BOID_CELL_SIZE = 20` (= largest steering radius). Grid built O(n) per frame with `self._grid.clear()` + rebuild. 3×3 cell search replaces O(n²) all-pairs loop. Gain: 15–55% depending on canvas size. Key: use empty tuple `()` as `.get()` default to avoid list allocation on empty cells.

**TrailCanvas canvas pooling:** Store `self._canvas = drawille.Canvas()` at `__init__`; detect `self._canvas_has_clear = hasattr(self._canvas, 'clear')` once. `to_canvas()` reuses the stored canvas instead of allocating each frame.

**`_layer_frames` buffers:** Module-level `_LAYER_ROW_BUF`/`_LAYER_RESULT_BUF` lists with `.clear()` + append replace per-call allocations. Non-reentrant — only valid from the Textual event loop (single-threaded). Add a comment noting this.

**`_render_multi_color` buffer:** `self._multi_color_row_buf: list[str]` on `DrawilleOverlay`, initialised in `on_mount()` (no `__init__` on this widget). Reuse per row; reallocate only on width change.

**`_braille_density_set` / `_depth_to_density` signatures:** Both accept `w, h` parameters (added in perf pass). Call sites: `HyperspaceEngine`, `AuroraRibbonEngine` (direct), `RopeBraidEngine` (via `_depth_to_density`).

### Rich bracket eating in Button labels

`Button("[show all]", ...)` renders as empty — Rich parses `[show all]` as a markup tag. Always wrap bracket-containing labels:
```python
from rich.text import Text
Button(Text("[show all]"), ...)  # correct
Button("[show all]", ...)        # empty label
```

### `_pending_children` internal name conflict

Textual's `Widget` base class uses `_pending_children` as an internal list attribute. Naming your own widget dict attribute `_pending_children` causes `'list' object has no attribute 'setdefault'` errors. Use `_child_buffer` or similar instead.

### Static content access

`Static` has no `.renderable` attribute in Textual 8.x. Use `.content`:

```python
# WRONG — AttributeError
str(widget.query_one("#foo", Static).renderable)

# CORRECT
str(widget.query_one("#foo", Static).content)
```

### Pure-function widget method tests (_ChartHelper pattern)

For Widget methods that only use a small set of `self.*` attrs (no `query_one`, no reactives), avoid running a full app by creating a plain helper class:

```python
class _ChartHelper:
    _BAR_WIDTH = 30
    _build_chart = UsageOverlay._build_chart
    _build_sparkline = UsageOverlay._build_sparkline

def _h() -> _ChartHelper:
    return _ChartHelper()

def test_zero_total():
    assert "no token data yet" in _h()._build_chart(0, 0, 0, 0).lower()
```

No `Widget.__new__`, no running app, no async overhead. Only works when the method's `self` access is limited to plain attributes declared on the helper.

### Patching function-local imports

If a method does `from some.module import fn` inside the function body, patch at the **source module**:

```python
# Method body: from agent.usage_pricing import estimate_usage_cost
# WRONG — name never bound in overlays namespace
patch("hermes_cli.tui.overlays.estimate_usage_cost")

# CORRECT — patches sys.modules["agent.usage_pricing"].estimate_usage_cost
patch("agent.usage_pricing.estimate_usage_cost")
```

### App-level key handler testing

Non-focused widgets can't receive key events via `pilot.press()`. Test app-level `on_key` dispatch directly:

```python
with patch.object(app, "_copy_text_with_hint") as mock_copy:
    event = MagicMock()
    event.key = "c"
    app.on_key(event)
    await pilot.pause()
    mock_copy.assert_called_once_with("expected text")
    event.prevent_default.assert_called()
```

### `__init__.py` re-exports after subpackage splits

After splitting `renderers.py` into `code_blocks.py`, `inline_media.py`, `prose.py`, the `widgets/__init__.py` re-export block still imported from `.renderers`. A single `ImportError` in `__init__.py` blocks ALL test files that import `hermes_cli.tui.app` from collecting (~100+ tests). Fix: import each class from its actual home module:

```python
# BROKEN after split
from .renderers import (CodeBlockFooter, StreamingCodeBlock, InlineImage, ...)

# CORRECT after split
from .renderers import (CopyableBlock, CopyableRichLog, LiveLineWidget, ...)
from .code_blocks import (CodeBlockFooter, StreamingCodeBlock)
from .inline_media import (InlineImage, InlineImageBar, InlineThumbnail)
from .prose import (InlineProseLog, MathBlockWidget)
```

---

## Skin system

Full reference in [`skin-reference.md`](skin-reference.md) (same skills folder).  
Standalone skill: `hermes-skin`.

Quick facts for TUI work:
- `app.apply_skin(Path | dict)` — single entry point; triggers `refresh_css()` + invalidates hint cache, StatusBar, completions, PreviewPanel, all ToolBlock/StreamingCodeBlock.
- New `$var-name` in `hermes.tcss` must also appear in `COMPONENT_VAR_DEFAULTS` (theme_manager.py) and skin_engine.py docstring — TCSS parse happens at class-definition time.
- `SkinPickerOverlay` scans `~/.hermes/skins/` for `.json/.yaml/.yml`; `"default"` always first.
- Hot reload: `_theme_manager.start_hot_reload()` — off-thread daemon, ~2 s latency. Dict-loaded skins cannot hot-reload.

---

## _Skin system full reference (inline copy — see skin-reference.md for canonical)_

### Two-layer architecture

**Layer 1 — `skin_engine.py` (legacy ANSI/banner layer)**
- `SkinEngine` dataclass with `.colors`, `.spinner`, `.branding`, `.tool_icons`, `.diff`, `.markdown`, `.syntax_scheme`, etc.
- Used for Rich-rendered banner art, prompt_toolkit ANSI mode, TTE effects, and `_skin_color()` helper in `widgets/utils.py`.
- API: `get_active_skin()` → `SkinEngine`; `set_active_skin(name)`; `list_skins()`.
- `skin.get_color(key, fallback)` — reads `.colors[key]` with fallback.
- `skin.get_branding(key, fallback)` — reads `.branding[key]` with fallback.

**Layer 2 — `theme_manager.py` + `skin_loader.py` (Textual CSS variable layer)**
- `ThemeManager` translates skin files into Textual CSS variables via `get_css_variables()`.
- `apply_skin(skin_vars: dict | Path)` on `HermesApp` — single entry point; calls `_theme_manager.load_dict()` or `load([path])` then `apply()`.
- `ThemeManager.css_variables` property: `{**_css_vars, **_component_vars}` — component vars win on conflict.

### Skin file location

User skins: `~/.hermes/skins/<name>.yaml` or `<name>.json`.  
`SkinPickerOverlay` discovers skins by scanning that directory for `.json/.yaml/.yml` extensions.  
`"default"` is always inserted at index 0 even if no default file exists.

### Skin file format (YAML)

```yaml
# ── Semantic keys (skin_loader._SEMANTIC_MAP) ──────────────────────────
fg:         "#E0E0E0"    # → foreground, text
bg:         "#0F0F23"    # → background, surface, panel
accent:     "#7C3AED"    # → primary, accent
accent-dim: "#5A2A9A"    # → primary-darken-2, primary-darken-3
success:    "#4CAF50"    # → success
warning:    "#FFA726"    # → warning
error:      "#ef5350"    # → error
muted:      "#888888"    # → text-muted
border:     "#333333"    # → panel-lighten-1
selection:  "#1E4080"    # → boost

# ── Glass keys (pass through unchanged) ────────────────────────────────
glass-tint:   "#0D0D0D"
glass-border: "#333333"
glass-edge:   "#555555"

# ── Raw Textual CSS var overrides (Pass 1 — highest precedence) ─────────
vars:
  primary: "#7C3AED"               # Wins over semantic fan-out
  preview-syntax-theme: "dracula"  # Pygments theme for code blocks (default: monokai)
                                   # Options: monokai, dracula, one-dark, nord, gruvbox, etc.

# ── Component Part variables (injected by ThemeManager) ─────────────────
component_vars:
  app-bg:                   "#1E1E1E"   # Global app bg — Screen + HermesApp + chrome
  cursor-color:             "#FFF8DC"   # Input cursor glyph/block
  cursor-selection-bg:      "#3A5A8C"   # Text selection highlight
  cursor-placeholder:       "#555555"   # Placeholder text colour
  ghost-text-color:         "#555555"   # Autocomplete ghost/suggestion text
  chevron-base:             "#FFF8DC"   # Input chevron idle state
  chevron-file:             "#FFBF00"   # Input chevron file mode
  chevron-stream:           "#6EA8D4"   # Input chevron streaming
  chevron-shell:            "#A8D46E"   # Input chevron shell mode
  chevron-done:             "#4CAF50"   # Input chevron done
  chevron-error:            "#E06C75"   # Input chevron error
  fuzzy-match-color:        "#FFD866"   # Autocomplete fuzzy match highlight
  status-running-color:     "#FFBF00"   # StatusBar running indicator
  status-error-color:       "#ef5350"   # StatusBar error
  status-warn-color:        "#FFA726"   # StatusBar warning
  status-context-color:     "#5f87d7"   # StatusBar context info
  running-indicator-hi-color:  "#FFA726"   # Running indicator bright phase
  running-indicator-dim-color: "#6e6e6e"   # Running indicator trough/shimmer base
  fps-hud-bg:               "#1a1a2e"   # FPS counter background
  user-echo-bullet-color:   "#FFBF00"   # User message bullet
  completion-empty-bg:      "#2A2A2A"   # Completion list empty state
  rule-dim-color:           "#888888"   # TitledRule/PlainRule dim text
  rule-bg-color:            "#1E1E1E"   # Rule gradient endpoint (MUST match app-bg)
  rule-accent-color:        "#FFD700"   # TitledRule title text accent
  rule-accent-dim-color:    "#B8860B"   # TitledRule accent dim variant
  primary-darken-3:         "#4a7aaa"   # TitledRule idle glyph (not a Textual built-in)
  brand-glyph-color:        "#FFD700"   # ⟁/⚕ brand glyph, separate from title text
  scrollbar:                "#5f87d7"   # Scrollbar thumb
  drawille-canvas-color:    "#00d7ff"   # Braille animation canvas default colour
  panel-border:             "#333333"   # SourcesBar and bordered panel borders
  footnote-ref-color:       "#888888"   # Footnote superscript marker
  tool-mcp-accent:          "#9b59b6"   # MCP tool accent
  tool-vision-accent:       "#00bcd4"   # Vision tool accent
  diff-add-bg:              "#1a3a1a"   # Diff addition background
  diff-del-bg:              "#3a1a1a"   # Diff deletion background
  cite-chip-bg:             "#1a2030"   # Citation chip background
  cite-chip-fg:             "#8899bb"   # Citation chip foreground
  browse-turn:              "#d4a017"   # Browse mode turn anchor pip
  browse-code:              "#4caf50"   # Browse mode code anchor pip
  browse-tool:              "#2196f3"   # Browse mode tool anchor pip
  browse-diff:              "#e040fb"   # Browse mode diff anchor pip
  browse-media:             "#00bcd4"   # Browse mode media anchor pip
  nameplate-idle-color:     "#888888"   # AssistantNameplate idle state
  nameplate-active-color:   "#7b68ee"   # AssistantNameplate active state
  nameplate-decrypt-color:  "#00ff41"   # AssistantNameplate decrypt animation
  spinner-shimmer-dim:      "#555555"   # Spinner shimmer trough (skinnable for light bg)
  spinner-shimmer-peak:     "#d8d8d8"   # Spinner shimmer peak

# ── Legacy skin_engine keys (ANSI/banner layer — skin_engine.py) ────────
colors:
  banner_title:   "#FFD700"    # Banner/TTE gradient stop 1 — skin.get_color("banner_title")
  banner_accent:  "#FFBF00"    # Banner/TTE gradient stop 2 — skin.get_color("banner_accent")
  banner_dim:     "#CD7F32"    # Banner/TTE gradient stop 3 — skin.get_color("banner_dim")
  # ... (full schema in hermes_cli/skin_engine.py docstring)

branding:
  agent_name:     "Hermes Agent"
  prompt_symbol:  "❯ "

syntax_scheme: monokai   # Named scheme; separate from vars.preview-syntax-theme
```

### Precedence rules (skin_loader)

1. **Pass 1** — `vars:` block written directly to output dict (highest precedence, overrides everything).
2. **Pass 2** — semantic keys (`fg`, `bg`, `accent`, …) fan out via `_SEMANTIC_MAP`; `setdefault` used so Pass 1 wins on conflict.
3. **Glass keys** (`glass-tint`, `glass-border`, `glass-edge`) pass through unchanged after Pass 2.
4. **`component_vars:`** extracted separately; merged on top of `COMPONENT_VAR_DEFAULTS` (ThemeManager).
5. **Textual built-in defaults** — lowest precedence (overridden by everything above).

### `apply_skin()` refresh chain

```python
app.apply_skin(Path("~/.hermes/skins/mytheme.yaml"))
# or
app.apply_skin({"accent": "#7C3AED", "component_vars": {"cursor-color": "#FFD700"}})
```

`apply_skin` invalidates (in order):
1. `_theme_manager.load_dict()` / `load([path])` + `apply()` → calls `refresh_css()`.
2. `_hint_cache.clear()` — StatusBar idle-tip rendering cache.
3. `StatusBar._idle_tips_cache = None` — forces tip re-render on next tick.
4. `VirtualCompletionList.refresh_theme()` — completion list repaints.
5. `PreviewPanel.refresh_theme()` — preview panel repaints.
6. All mounted `ToolBlock` instances: `block.refresh_skin()`.
7. All mounted `StreamingCodeBlock` instances: `block.refresh_skin(css_vars)`.

### Hot reload

```python
# Start background watcher (1 Hz poll by default)
app._theme_manager.start_hot_reload(poll_interval_s=1.0)

# Stop on exit
app._theme_manager.stop_hot_reload()

# Manual poll (used in set_interval callbacks at ~1 Hz)
changed = app._theme_manager.check_for_changes()
```

Hot reload is off-thread: `_watch_loop` does blocking `stat()` + file read in a daemon thread, then schedules `_apply_hot_reload_payload` onto the Textual event loop via `app.call_from_thread`. Skin file edits land in the TUI within ~2 s with no frame drops.

**Dict-loaded skins (`load_dict`) cannot hot-reload** — `_source_path` is set to `None`.

### `preview-syntax-theme` raw var

Controls Pygments syntax highlighting theme for code blocks and the preview panel. Set in the `vars:` block (raw override):

```yaml
vars:
  preview-syntax-theme: "dracula"
```

Consumed by:
- `ResponseFlow._pygments_theme` (updated by `refresh_skin_vars()`)
- `StreamingCodeBlock.refresh_skin()` → `_pygments_theme`
- `PreviewPanel.refresh_theme()` → reads `css.get("preview-syntax-theme", "")`
- `ExecuteCodeBlock` → `css_vars.get("preview-syntax-theme", "monokai")`

Default: `"monokai"` everywhere. Valid names: any Pygments style name (`monokai`, `dracula`, `one-dark`, `nord`, `gruvbox`, `github-dark`, `catppuccin`, `solarized-dark`, `tokyo-night`).

### TTE effects integration

`tte_runner.py` provides skin-aware terminal text effects (optional dep: `pip install "hermes-agent[fun]"`).

```python
from hermes_cli.tui.tte_runner import run_effect, iter_frames, EFFECT_MAP, EFFECT_DESCRIPTIONS

# Synchronous — caller must suspend Textual TUI first (inside App.suspend())
success = run_effect("matrix", "Hello Hermes")

# Async frame generator — for rendering into a widget
for frame in iter_frames("decrypt", "Connecting…"):
    widget.update(frame)
```

**Skin-aware gradient**: both `run_effect` and `iter_frames` pull `banner_title`, `banner_accent`, `banner_dim` from `skin_engine.get_active_skin()` and apply them to `effect.effect_config.final_gradient_stops` — the three TTE gradient color stops. This is skipped if the caller passes explicit `params={"final_gradient_stops": [...]}`.

**Effect catalogue** (`EFFECT_MAP` keys — 40+ effects):

| Category | Effects |
|---|---|
| Reveal / dramatic | `matrix`, `blackhole`, `decrypt`, `laseretch`, `binarypath`, `synthgrid` |
| Flow / ambient | `beams`, `waves`, `rain`, `overflow`, `sweep` |
| Text reveal | `print`, `slide`, `highlight` |
| Fun / misc | `wipe`, `colorshift`, `crumble`, `burn`, `fireworks`, `bouncyballs`, `bubbles`, `vhstape`, `thunderstorm`, `smoke`, `rings`, `scattered`, `spray`, `swarm`, `spotlights`, `unstable`, `slice`, `middleout`, `pour`, `orbittingvolley`, `randomsequence`, `expand`, `errorcorrect` |

**`_apply_effect_params()`** coerces raw config values to match each effect's config field type (bool/int/float/str/tuple/Color). Unknown keys are ignored with a print warning. `"parser_spec"` key is always skipped.

**`run_effect` must be called inside `App.suspend()`** — TTE writes directly to the raw terminal and conflicts with Textual's renderer.

**TUI startup TTE path:** `_play_tte_in_output_panel` (cli.py) — generates frames via `iter_frames`, splices each into the full banner layout via `_splice_startup_banner_frame`, and applies via `call_from_thread` → `query_one(StartupBannerWidget).set_frame(frame)`. `StartupBannerWidget` is pre-mounted as the first child of `OutputPanel.compose()` — no runtime mount needed.

**Do NOT** use `TTEWidget` + `dock:top` overlay for startup — it anchors to the screen top-left, not the hero's left-column position within the banner layout.

**Do NOT** try to mount `StartupBannerWidget` at runtime from a background thread — `call_from_thread(mount)` silently no-ops (unawaited `AwaitMount`), and `call_from_thread(fn)` cannot return widget references to the calling thread (result dict is read before the closure runs).

### TCSS: declaring new skin vars

Any new `$var-name` referenced in `hermes.tcss` **must** be:
1. Added to `COMPONENT_VAR_DEFAULTS` in `theme_manager.py` with a sensible default.
2. Declared in `hermes.tcss` under the Component Part variables comment block (`/* Component Part variables */`).
3. Documented in the `component_vars:` block of `skin_engine.py`'s module docstring.

`get_css_variables()` alone is insufficient — Textual parses TCSS at class-definition time; unknown `$var-name` refs raise at parse time, not at render time.

### 2026-04-23 — Input Mode Safety (rev-search, bash mode, readline bindings)

**`_exit_rev_mode` bug (now fixed):** The method previously set `self._rev_match_idx = -1` before reading it in the accept path. Fix: capture `match_idx = getattr(self, "_rev_match_idx", -1)` BEFORE the `self._rev_match_idx = -1` line. The accept path then uses the pre-captured value to sync `_history_idx`.

**Rev-search legend via `feedback.flash`:** Use `duration=9999` as a "never expires" sentinel for persistent hints. `FeedbackService` always schedules `app.set_timer(delay, cb)` — with `delay=0.0` Textual fires the expire callback on the very next tick. Use explicit `app.feedback.cancel("hint-bar")` to clear. Call in `_exit_rev_mode` (both accept and abort paths) inside `try/except`.

**Rev-search Enter semantics (bash-style):** In `action_submit`, check `getattr(self, "_rev_mode", False)` at the top and call `_exit_rev_mode(accept=True)` before reading `self.text`. The match text was already loaded by `action_rev_search` during live search; `_exit_rev_mode(accept=True)` only syncs `_history_idx` — it does NOT call `load_text`. The subsequent submit reads whatever text is in the widget.

**`_sync_bash_mode_ui(is_bash: bool)` pattern:** Centralise all bash-mode UI changes (placeholder, chevron glyph, hint) in one method called from `on_text_area_changed`. Do NOT call it from `keys.py` — let `inp.clear()` → `on_text_area_changed` → `_sync_bash_mode_ui(False)` handle exit automatically.

**Ctrl+C bash-mode routing in `keys.py`:** Insert the bash-mode block AFTER the selection-copy check and BEFORE the existing `_svc_bash.is_running` check. Query `#input-area` and check `has_class("--bash-mode")`:
- Running cmd → `_svc_bash.kill()` + hint
- No running cmd → `inp.clear()` (triggers `on_text_area_changed` which auto-removes `--bash-mode`)

**`_history_navigate_skip_cmds(direction)` pattern:** Save draft before the loop (once, on `_history_idx == -1` + backward). Use `start = _history_idx if _history_idx != -1 else len(_history)`, then `idx = start + direction`. Forward past end → reset idx to -1, restore `_history_draft`. If no matching entry found, stay put (don't change `_history_idx`).

**`suggestion` is a Textual reactive:** Cannot be set via normal attribute syntax on `object.__new__(HermesInput)` — raises `ReactiveError`. Use a plain Python fake class (`_FakeInput`) for history mixin tests that need to verify `suggestion` changes. The `_FakeInput` class declares `suggestion` as a plain instance attribute.

**`_FakeInput` testing pattern:** For `_HistoryMixin` pure-unit tests, create a plain class (not `object.__new__`) with all the attributes the mixin uses, plus a plain `suggestion: str` field. Assign the unbound mixin methods directly: `_HistoryMixin.action_rev_search(inp)`. No `PropertyMock`, no `Widget.__new__`, no async overhead.

**Bash mode CSS border:** Border on `HermesInput.--bash-mode` uses `$chevron-shell` not `$primary`. Must also add compact override: `HermesApp.density-compact HermesInput.--bash-mode:focus { border: none; }` — compact mode removes focus border to preserve content height (same rule as normal focus border).

**Alt+Up/Down conflict with browse-mode:** `alt+up`/`alt+down` are handled in `services/keys.py` browse-mode block (lines ~427–431) AND `app.py` app-level bindings. Adding `priority=True` in `HermesInput.BINDINGS` correctly intercepts before both when input is focused. No changes to `keys.py` or `app.py` needed.

### 2026-04-23 — Error recoverability + OmissionBar/ChildPanel polish (commit 3b9d7476)

**B-2 — `--completing` two-tick collapse sequence:**
- `ToolPanel.set_result_summary` adds `--completing` CSS class on the panel, then `set_timer(0.25, _post_complete_tidy)`.
- `_post_complete_tidy` calls `remove_class("--completing")` (in try/except AttributeError) then applies the final collapsed state.
- Under `HERMES_DETERMINISTIC=1`: calls `_post_complete_tidy` inline (no timer).
- CSS: `ToolPanel.--completing > ToolAccent { background: $primary 25%; }` — subtle flash during window.

**C-1 — `[e]` stderr action in expanded FooterPane:**
- `FooterPane._render_footer` injects a synthetic `copy_err` action when `stderr_tail` is present and no existing `copy_err` action exists in the chip list.
- Only appears in expanded state (collapsed header uses stderrwarn segment, not this).

**C-2 — `ToolHeader._remediation_hint`:**
- `ToolHeader.__init__`: `self._remediation_hint: str | None = None`
- `ToolPanel.set_result_summary`: extracts `chip.remediation` from the first chip, truncates to 28 chars, stores on both `self._header_remediation_hint` and `header._remediation_hint`.
- `_render_v4`: appends `("remediation", Text(f"  hint:{_rh}", style="dim yellow"))` when `is_collapsed and _is_complete and _tool_icon_error and _remediation_hint`.
- `_DROP_ORDER`: `"remediation"` inserted between `"stderrwarn"` and `"exit"`.

**D-2 — SubAgentPanel child error glyphs:**
- `SubAgentPanel.__init__`: `self._child_error_kinds: list[str] = []`
- `_notify_child_complete`: calls `_extract_error_kind(tool_call_id)`, appends to `_child_error_kinds` if new.
- `_extract_error_kind`: walks `_body.children`, matches by `_tool_call_id`, returns `error_kind` from `_result_summary_v4`.
- `SubAgentHeader.update`: accepts `error_kinds` param — renders up to 3 glyphs as `("error-kinds", ...)` segment; accessible fallback appends `err-kinds:...` text.

**D-1 — OmissionBar `[reset]` never disabled:**
- Button label changed from `[hide]` to `[reset]` (via `Text("[reset]")` — bare string would be eaten by Rich markup parser).
- `set_counts()`: removed `disabled = at_default`; toggles `--at-default` CSS class instead + sets tooltip (`"Already at default view"` / `"Scroll output window"`).
- `on_button_pressed`: no-op guard when `--ob-cap` + `--at-default`.
- CSS: `OmissionBar Button.--at-default { color: $text-muted 50%; }`.

**E-1 — Bottom OmissionBar shown at 80% cap:**
- `_OB_WARN_THRESHOLD = int(_VISIBLE_CAP * 0.8)` constant in `_shared.py` (= 160 for default 200 cap).
- `_refresh_omission_bars` in `_streaming.py`: `show_bottom = (total >= warn_threshold) or (visible_end < total) or bool(cap_msg)`.

**E-2 — ChildPanel `space` → `alt+c`:**
- `Binding("space", "toggle_compact", ...)` removed from `ChildPanel.BINDINGS`.
- `Binding("alt+c", "toggle_compact", show=False, priority=True)` added.

**Key gotchas:**
- `Button("[reset]", ...)` → empty label (Rich parses `[reset]` as markup tag). Always use `Button(Text("[reset]"), ...)`.
- `_remediation_hint` render guard requires `_tool_icon_error` (not just `_error_kind`) to avoid showing hints on non-error collapsed panels.
- `_child_error_kinds` is a `list` not `set` — order of first-seen preserved; dedup by `if ek not in self._child_error_kinds` before append.
- Under `HERMES_DETERMINISTIC`, two-tick collapse path is skipped entirely — `_post_complete_tidy` called inline. Tests that set `HERMES_DETERMINISTIC=1` see synchronous collapse without the 0.25s window.
- Under `HERMES_DETERMINISTIC`, two-tick collapse path is skipped entirely — `_post_complete_tidy` called inline. Tests that set `HERMES_DETERMINISTIC=1` see synchronous collapse without the 0.25s window.

### 2026-04-23 — Input Feedback & Completion UX (commit 51cc833b, merged feat/textual-migration)

A-2/B-1/B-2/B-3/E-1/E-2/E-3/F-3 — 36 tests in `tests/tui/test_input_feedback_completion.py`.

**A-2 — Draft stash for programmatic setters:**
- `_draft_stash: str | None = None` on `HermesInput`.
- `save_draft_stash()` — stores `self.text` only when `_history_idx == -1` (not navigating history).
- `action_history_prev` — in the `_history_idx == -1` branch, only saves `_history_draft` when `_draft_stash is None`; stash holds the real pre-overlay text.
- `action_history_next` past-end branch — restores `_draft_stash` (then clears it) before `_history_draft`.
- `on_text_area_changed` invalidation — clears stash when `_history_idx == -1 and self.text != self._draft_stash`.
- `HistorySearchOverlay._accept_result()` calls `inp.save_draft_stash()` before `inp.value = ...`.

**B-1 — Empty reason copy:**
- `_EMPTY_REASON_TEXT` in `hermes_cli/tui/completion_list.py` updated: `"too_short": "  type 2+ chars to match"`, `"no_slash_match": "  no match — /help for list"`, `"path_not_found": "  no such path — try @ alone"`.

**B-2 — Enter accepts highlighted completion:**
- Intercept in `_on_key` key == "enter" branch, AFTER file-drop check, BEFORE `action_submit()`.
- Checks `self._completion_overlay_visible()` → `screen.query_one(VirtualCompletionList).highlighted >= 0` → calls `self.action_accept_autocomplete(); return`.
- Second Enter (no overlay visible) falls through to `action_submit()` as normal.
- MUST be in `_on_key`, NOT `action_submit()` — action_submit is called programmatically and must not be overlay-gated.
- `action_accept_highlighted()` does NOT exist; `action_accept_autocomplete()` is on `_AutocompleteMixin`.
- No `self._overlay` attribute exists — always use `self.screen.query_one()`.

**B-3/F-3 — InputLegendBar:**
- New `hermes_cli/tui/widgets/input_legend_bar.py` — `InputLegendBar(Static)` with `show_legend(mode)` / `hide_legend()` and 4 legend strings: `"bash"`, `"rev_search"`, `"completion"`, `"ghost"`.
- Mounted in `app.compose()` before `#input-row` (sits above HermesInput in flow layout, NOT dock:bottom).
- Call sites: `_sync_bash_mode_ui` (bash), `action_rev_search`/`_exit_rev_mode` (rev_search), `CompletionOverlay.show/hide_overlay` (completion), `update_suggestion` (ghost).
- All calls wrapped in `try/except` — widget may not be mounted in tests.
- CSS: `HermesApp.density-compact InputLegendBar { display: none !important; }` — hidden in compact mode. `hide_legend()` still removes `--visible` so stale legend doesn't reappear on compact toggle.

**E-1 — Error-aware placeholder:**
- `error_state: reactive[str | None] = reactive(None)` on `HermesInput`.
- `_refresh_placeholder()` — single source of truth: locked (`self.disabled`) > error (`self.error_state`) > idle (`self._idle_placeholder`). Every state-changing watcher/setter calls this; never set `self.placeholder` directly.
- `watch_error_state` delegates to `_refresh_placeholder()`.
- Esc-to-clear: before overlay-close chain, `if self.error_state is not None and not self.text.strip(): self.error_state = None; return`.
- Wired in `services/watchers.py` `on_status_error`: `inp.error_state = value if value else None` (additive — existing FeedbackService flash unchanged).

**E-2 — History write failure toast:**
- `_write_fail_warned: bool = False` on `HermesInput` (init via `widget.py`).
- `_on_history_write_error(exc)` — deduped via `_write_fail_warned`; flashes hint-bar with `duration=6.0, priority=WARN`; reset to False via `on_done` callback on successful write.
- `safe_write_file` param is `data` (not `content`), `on_done` (not `on_success`); `on_done` receives `bytes_written: int`.
- `_write_fail_warned` access uses `getattr(self, "_write_fail_warned", False)` to survive `__new__`-constructed objects.

**E-3 — Locked input indicator:**
- `_set_input_locked(locked: bool)` — visual-affordance helper ONLY; calls `_refresh_placeholder()` and adds/removes `--locked` CSS class. Does NOT set `self.disabled`.
- Guard: `if not getattr(self, "is_mounted", False): return`.
- Called alongside `inp.disabled` mutations in `watchers.py` (on_undo_state and agent-running paths).
- CSS: `HermesInput.--locked { border: tall $panel-lighten-1 30%; color: $text-muted 60%; }` — uses `color: $text-muted 60%` NOT `opacity:` (opacity unsupported in Textual 8.2.3).

**Key gotchas:**
- `_refresh_placeholder()` must be the ONLY place that sets `self.placeholder` — watch for any direct `self.placeholder =` assignment that bypasses the priority chain.
- InputLegendBar must be in flow layout (not dock:bottom) — sits above `#input-row` visually because dock-bottom stack is bottom-to-top in compose order.
- `_set_input_locked()` is visual-only; `self.disabled` is managed by callers. Mixing the two would block Ctrl+C in locked state.
- Priority chain must be respected in call order: `_refresh_placeholder()` reads current state at call time, so always call it AFTER updating the state that changed.

---

### 2026-04-23 — PlanPanel P1 polish (commit f7a4ed55, merged feat/textual-migration)

P1-1/P1-2/P1-3 — 86 tests total (48 new in `test_plan_panel_p1.py` + updated `TestErrorCountInChip` in `test_plan_panel_p0.py`).

**P1-1 — Focus navigation:**
- `_PlanEntry(Static, can_focus=True)` — new widget in `plan_panel.py` before `_NowSection`. `on_click`/Enter → `_jump()`; Esc → refocus `#input-area`. `_jump()` uses `getattr(self.app, "_svc_browse", None)` guard.
- `BrowseService.scroll_to_tool(tool_call_id: str) -> bool` — new method in `services/browse.py`. Queries `OutputPanel` children via `output.query(ToolPanel)`, matches by `_plan_tool_call_id`, calls `scroll_to_widget(animate=True, center=True)` + `clear_browse_highlight()` + `add_class("--browse-focused")`.
- `ToolPanel._plan_tool_call_id: str | None = None` — added to `tool_panel.py` `__init__`.
- Wiring: `message_panel.py` `open_streaming_tool_block` **else branch only** (top-level ToolPanels): `panel._plan_tool_call_id = tool_call_id`. NOT in `tools.py` — `ToolPanel` is not created there.
- `_NowSection.show_call()` removes old `#now-line` and mounts a `_PlanEntry` with `tool_call_id`. `_update_now_line()` still queries `#now-line` as `Static` — works because `_PlanEntry(Static)`.
- `_NextSection.update_calls()` mounts `_PlanEntry` for each pending entry; overflow `+N more` stays plain `Static`.
- `from textual import events` added to `plan_panel.py` (was missing).

**P1-2 — Segmented chip header:**
- `_ChipSegment(Static, can_focus=False)` — new widget before `_PlanPanelHeader`. `action` kwarg consumed in `__init__` (not passed to super). Actions: `"jump_running"`, `"jump_first_error"`, `"usage"`.
- `_PlanPanelHeader.compose()` rewritten — yields: `#plan-header-label`, `#plan-chip-title`, `#chip-running/done/errors/cost`, `#plan-f9-badge`.
- `update_header` delegates to `_show_chip` or `_show_full`. Error segment uses `RichText.from_markup`.
- `TestErrorCountInChip` in `test_plan_panel_p0.py` updated to chip-segment assertions.

**P1-3:** `Static("[F9]", id="plan-f9-badge")` in compose; `dock: right; color: $text-muted 50%` in `_PlanPanelHeader.DEFAULT_CSS`.

**Critical gotchas:**
- `ToolPanel` wiring is in `message_panel.py` else branch — NOT `tools.py`.
- `output.query(ToolPanel)` is recursive; ChildPanels always have `_plan_tool_call_id = None` so they never match.
- Do NOT add `display: none` to `_ChipSegment.DEFAULT_CSS` — visibility managed via `.display = bool`.

---

### 2026-04-23 — PlanPanel P0 fixes (commit 878d357e, merged feat/textual-migration)

P0-1/P0-2/P0-3/P0-4/P0-5/P0-6 + B-1/B-2/B-3 — 37 tests in `tests/tui/test_plan_panel_p0.py`.

**P0-1 — `_DoneSection` deleted:** All mounting sites removed (`compose`, `_on_collapse_changed`, `_rebuild`, `_rebuild_done`). TCSS rule block deleted. Done count surfaces in chip header only.

**P0-2 — Default collapsed:** `_collapsed: reactive[bool] = reactive(True)`. `on_mount` calls `_on_collapse_changed(getattr(self.app, "plan_panel_collapsed", True))` synchronously after `_rebuild()` to eliminate first-frame flash. Do NOT change `DEFAULT_CSS` height — the existing `PlanPanel.--collapsed { height: 1; max-height: 1; }` rule is correct.

**P0-3 — 2Hz tick + `_base_text`:**
- `_NowSection._base_text: str = ""` — stores glyph + label without elapsed.
- `_update_now_line(elapsed)` helper — appends `  [Ns]` only when `elapsed >= 3`; never string-searches `"  ["`.
- `_tick()` calls `_update_now_line`; `clear()` resets `_base_text = ""`.
- `set_interval(1.0)` → `set_interval(2.0)`.

**P0-4 — Error count in chip + cost in header:**
- `_rebuild_header` splits `done` (PlanState.DONE only) and `errors` (PlanState.ERROR) separately.
- Reads `turn_cost_usd = getattr(self.app, "turn_cost_usd", 0.0)`.
- `update_header(collapsed, running, pending, done, errors=0, cost_usd=0.0)` — new signature.
- When `errors > 0`: use `rich.text.Text.from_markup(...)` — plain strings with `[bold red]` tags render literally in `Static.update()`.
- Cost appended as ` · $0.12` via `RichText.append()` if label is already `RichText`, else plain string concat.

**P0-5 — `_BudgetSection` visibility:**
- `_budget_hide_timer: Any = None` on `PlanPanel`.
- `_BudgetSection` removed from `_on_collapse_changed` iteration — budget managed exclusively by `_refresh_budget_visibility`.
- `_refresh_budget_visibility(has_active, calls)` — hides budget when active; shows for 5s post-turn via `_hide_budget_after_turn` timer.

**P0-6 — Debounce `--active` hide:**
- `_active_hide_timer: Any = None` on `PlanPanel`.
- `has_any=False` starts 3s timer to `_do_hide_active` instead of hiding immediately.
- `has_any=True` cancels any pending timer and shows immediately.
- `_do_hide_active` is a separate class method (not nested).

**B-1:** `_NextSection._expanded` reactive deleted; `update_calls` always uses `_MAX_VISIBLE`.

**B-2:** `$plan-now-fg: #ffb454` (theme_manager + hermes.tcss); `$plan-pending-fg: #888888`. Use literal hex — Textual 8.2.3 does not resolve variable-to-variable references at parse time. All skin YAMLs unchanged.

---

### 2026-04-23 — Startup Banner Polish (commits 65de2069 + 20563d73, merged feat/textual-migration)

A-1/A-2/A-3/A-5/A-6/B-1/B-3/G-1 — 18 tests in `tests/tui/test_startup_banner_polish.py`. `cli.py` at repo root (not `hermes_cli/cli.py`).

**Pre-flight frame (A-1):** After `template = self._build_startup_banner_template(plain_hero)`, queue `_preflight = self._render_startup_banner_text(print_hero=True); _queue_frame(_preflight)` so `StartupBannerWidget` is never blank during TTE warmup.

**Wall-clock cap (A-5):** `MAX_WALL_S = 6.0` alongside existing `MAX_FRAMES = 3000` at L3466. `_tte_start = time.monotonic()` after preflight queue call. Break condition: `if i >= MAX_FRAMES or (time.monotonic() - _tte_start) >= MAX_WALL_S: break`.

**Hold-frame + static via queue (B-1):** After TTE loop's try/except, if `rendered_any`: `time.sleep(0.25); _queue_frame(self._render_startup_banner_text(print_hero=True))`. `show_banner_with_startup_effect` only calls `_set_tui_startup_banner_static()` when `not played`; otherwise sets `self._postamble_pending = True`. `_set_tui_startup_banner_static` is fallback-only — its body unchanged, only docstring updated.

**Ordering guarantee:** `_drain_latest` loops on the event loop thread reading `latest_frame` until None. After `time.sleep(0.25)`, `_queue_frame(static)` either piggybacks on a still-running `_drain_latest` or schedules a new one — both serialize on the event loop, so static always arrives after all TTE frames. The sleep provides the visible hold, not ordering.

**Reduced motion (G-1):** In `_get_startup_text_effect_config` (L3262), add before existing config reads: `_cfg = getattr(self, "config", {}) or {}; if _cfg.get("tui", {}).get("reduced_motion"): return None; if os.environ.get("HERMES_REDUCED_MOTION"): return None`. Uses already-loaded config dict — no `read_raw_config()` I/O.

**Padding smear (B-3):** In `_splice_startup_banner_frame`, `hero_line.append(" " * delta, style="")` — explicit empty style breaks Rich's style carry from preceding span.

**Pane width (A-3):** Create `OutputPanel.on_mount` (OutputPanel had none): sets `self.app._startup_output_panel_width = self.size.width`. In `_render_startup_banner_text`: `panel_w = getattr(app, "_startup_output_panel_width", 0); if panel_w > 0: capture_width = panel_w`. Startup race is acknowledged/acceptable — daemon reads 0 and falls back to terminal width if `on_mount` hasn't fired yet.

**Deferred postamble (A-6):** In `hermes_cli/tui/services/keys.py`, `dispatch_input_submitted` top: one-shot guard flushes `cli._show_banner_postamble()` and resets `cli._postamble_pending = False`. Guard goes before `event.value` read and bash-passthrough block so it fires on all first submits.

**Test fixture critical patterns:**
- `import cli as cli_module` — root-level, NOT `hermes_cli.cli`
- `patch.object(cli_module, "_hermes_app", mock_app)` — module global
- `mock_app.call_from_thread = MagicMock(side_effect=lambda fn: fn())` — prevents hang on non-running event loop
- Template dict keys: `{"lines": [], "hero_row": 0, "hero_col": 0, "hero_width": 10, "hero_height": 5}`
- Monkeypatch: `"cli.time.monotonic"`, `patch("cli.iter_frames", ...)`

---

### 2026-04-23 — Nameplate + ThinkingWidget Lifecycle (commits bfff7488 + 93867798, merged feat/textual-migration)

C-1/C-2/C-3/C-4/C-5/C-6/D-1/D-2/D-3/D-4/D-5/D-6/D-7/E-2/E-3/F-2/G-1 — 29 tests in `tests/tui/test_nameplate_thinking.py`; 2 existing tests in `test_thinking_widget_v2.py` updated.

**Nameplate unhide (C-1):** Deleted `HermesApp.thinking-active AssistantNameplate { display: none; }` from `hermes.tcss:647`. Keep `density-compact` rule at L642.

**Theme colors (C-2, C-5):** In `AssistantNameplate.on_mount` (L697): `self._active_style = Style.parse(f"bold {self._accent_hex}")` and `self._idle_color_hex = _lerp_hex(self._text_hex, self._accent_hex, 0.25)`. Replace all 5 `_NP_IDLE_COLOR` usages (L784/829/849/933/944) and all 5 `_NP_ACTIVE_COLOR` usages (L849/884/889/933/944) with `self._idle_color_hex`/`self._active_style`. Module-level constants kept as unmounted fallbacks. `$nameplate-idle-color`/`$nameplate-active-color` TCSS vars are dead code — left with comment.

**Shimmer fix (C-3):** `_render_active_pulse`: `n = max(3, len(self._frame)); offset = math.pi / n` — spans π across name regardless of length. `_tick_active_idle`: `self._active_phase += 0.28` (was 0.18). **Glitch reset (C-4):** In `_tick_glitch` else branch at ~L889: `self._active_phase = 0.0` before state transition. **Resize refresh (C-6):** `on_resize` calls `self.refresh()` after canvas width update.

**ThinkingWidget config pre-warm (D-7):** Add `ThinkingWidget.on_mount` that calls `self._load_config()`.

**Label escalation (D-1):** LONG_WAIT tick: `prefix = "Thinking"/"Thinking deeply"/"Still thinking"/"Working hard"` at 0/30/60/120s. `label_text = f"{prefix}… ({n}s)"`.

**D-2 flash effect swap:** `activate()` stores `self._resolved_effect = resolved_effect`; creates `self._label_line = _LabelLine("flash", ...)`. In `_tick` STARTED→WORKING: swaps `self._label_line._effect = make_stream_effect({"stream_effect": self._resolved_effect}, lock=self._label_line._lock)`. Import: `from hermes_cli.stream_effects import make_stream_effect` (NOT `hermes_cli.tui.stream_effects`).

**Fade-out (D-3):** `deactivate()` adds `--fading` class; `_do_hide()` removes it. TCSS: `ThinkingWidget.--active { opacity: 1; }` (required for transition to animate, not snap) + `ThinkingWidget.--fading { opacity: 0.0; transition: opacity 150ms in_out_cubic; }`.

**Layout reserve (D-4):** `_do_hide()` sets `self._substate = "--reserved"` and `self.add_class("--reserved")` instead of collapsing. `clear_reserve()` method removes class and resets substate. Call site: `self.query_one(ThinkingWidget).clear_reserve()` (NOT `self.app.query_one` — `ThinkingWidget` is a direct child of `OutputPanel`). TCSS: `ThinkingWidget.--reserved { height: 1; display: block; opacity: 0; }`.

**Engine whitelist split (D-5):** `_WHITELIST_DEEP_AMBIENT` (safe engines) + `_WHITELIST_DEEP_INTENSE` (adds matrix_rain/wireframe_cube etc.); `_WHITELIST_DEEP = _WHITELIST_DEEP_AMBIENT` alias. `_cfg_allow_intense` from `tui.thinking.allow_intense` config key.

**Deterministic static state (D-6):** Replace early-return in `activate()` with static LINE-mode: adds `--active`/`--mode-line` + `thinking-active` classes, mounts `_LabelLine("breathe")`, calls `update_static("Thinking…")`. `_LabelLine.update_static(text)` calls `self.update(RichText(text))` without starting tick.

**Narrow demotion + reduced motion (F-2, G-1) — canonical `_resolve_mode` body:**
```python
if self.app.has_class("reduced-motion"): return ThinkingMode.LINE  # first
if getattr(self.app, "compact", False): return ThinkingMode.COMPACT
w = self.app.size.width
if 0 < w < 70: return ThinkingMode.LINE
if 0 < w < 100: return ThinkingMode.COMPACT
```
`_tick_active_idle` guard: `if self.app.has_class("reduced-motion"): return`. `HermesApp.on_mount` in `app.py` adds `reduced-motion` class from both `HERMES_REDUCED_MOTION` env var AND `tui.reduced_motion` config key (fresh `read_raw_config()` call in `on_mount` is acceptable — fires once at startup on the event loop, not a hot path).

**Lock safety (E-3):** `_LabelLine.__init__`: `_lock = kwargs.pop("_lock", None)` before `super().__init__("", **kwargs)`; `self._lock = _lock or threading.Lock()`. `_init_effect` uses `lock=self._lock`. `activate()` passes `_lock=threading.Lock()`.
