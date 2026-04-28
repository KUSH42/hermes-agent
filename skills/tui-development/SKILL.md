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

> Quick module ownership lookup: [references/module-map.md](references/module-map.md)

### HermesApp mixin map + services layer (R4)

**R4 architecture (complete, all 4 phases merged)**: All 10 `_app_*.py` mixin files deleted. `HermesApp(App)` — no mixin bases. Logic lives in `hermes_cli/tui/services/`. Forwarder methods (`watch_X`, `on_key`, `_handle_tui_command`, etc.) are inlined directly at the bottom of `HermesApp` in `app.py` (2654 lines).

**R5 DEPRECATED stub cleanup (2026-04-23, commit 864ac9fe)**: 11 zero-external-caller DEPRECATED forwarder stubs deleted from app.py — `_cell_width`, `_input_bar_width`, `_next_spinner_frame`, `_helix_width`, `_helix_spinner_frame`, `_build_helix_frames` (spinner group); `_mount_minimap_default` (browse); `_append_attached_images`, `_insert_link_tokens`, `_drop_path_display`, `_handle_file_drop_inner` (watchers). **0 DEPRECATED markers remain** — all forwarders deleted across three passes (R5 + D1-D7 dead-code cleanup + app forwarder removal spec, commit 284a981e). All production code now calls service layer directly.

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
- Base: `BodyRenderer` (ABC, `body_renderers/base.py`) — `__init__(payload, cls_result, *, app=None)`; lazy `colors` property → `SkinColors`
- Factory: `pick_renderer(cls_result, payload)` in `body_renderers/__init__.py`
- API: `can_render()`, `build()`, `build_widget(density=None)`; `footer_entries: ClassVar[tuple] = (("y","copy"),)` — declare empty tuple to suppress footer
- Import: `from hermes_cli.tui.body_renderers import pick_renderer, FallbackRenderer`

**`body_renderers/_frame.py`** — canonical body container (RF-1, 2026-04-26):
- `BodyFrame(Widget)` — header slot + body slot + footer slot; `compose()` yields `Static(header)` / body Widget or `Static(body)` / `BodyFooter`
- `BodyFrame(header, body, footer, *, density=None, classes="")` — `density` maps to CSS class: COMPACT→`body-frame--compact`, HERO→`body-frame--hero`, TRACE→`body-frame--trace`
- `BodyFrame.body-frame--compact > BodyFooter { display: none; }` — CSS hides footer in compact tier
- All Phase C renderers (Code/Diff/Search/Shell/Json/Table/Log) must return `BodyFrame` from `build_widget()`. Only `FallbackRenderer` and `EmptyStateRenderer` are exempt.

**`body_renderers/_grammar.py`** — shared visual grammar for renderer bodies (G1–G4, merged 2026-04-24):
- `glyph(char) → str` — returns ASCII fallback when `HERMES_NO_UNICODE=1`; patch target is `hermes_cli.tui.constants.accessibility_mode` (not the grammar module itself)
- `SkinColors` — frozen dataclass; `from_app(app)`, `default()`; hex-validates all fields; special-cases `syntax-theme`/`syntax-scheme` as non-hex string fields
- `build_path_header(path, *, right_meta, colors)` → Rich `Text`
- `build_gutter_line_num(n)` → Rich `Text`
- `build_rule(label?)` → Rich `Text`
- `build_parse_failure(text, err, *, colors)` → Rich `Text` — dim raw text + `"Parse error: {err}"` in error color; use instead of hardcoded `dim` strings in parse-fail paths
- `BodyFooter(*entries, **kwargs)` — each entry is `str` or `(key, label)` tuple; entries separated by `' · '`; `[key]` chip is bold muted, label is plain muted, plain strings get no brackets. `dock: bottom; height: 1`. Colors resolved on `on_mount` from `SkinColors.from_app(self.app)`.

**`build_widget` override policy:** All Phase C renderers now override `build_widget(density=None) → BodyFrame`. FallbackRenderer and EmptyStateRenderer are exempt (bespoke layout). `build_widget` signature must include `density=None` kwarg for tier propagation; existing callsite at `tool_panel/_completion.py` passes zero args and remains backward-compatible.

**`--streaming` CSS class lifecycle:** Added by `ToolRenderingService.open_streaming_tool_block` on panel open; removed as the FIRST line of `_maybe_swap_renderer` before any other logic. `BodyFooter { display: none }` while class is present.

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

- `safe_run(caller, cmd, *, timeout, on_success=None, on_error=None, on_timeout=None, env=None, cwd=None, input_bytes=None, capture=True) -> Worker | None` — **must be called from event loop**. Dispatches off event loop via `run_worker(thread=True, group="io_boundary")`. Validation-failure `on_error` fires synchronously on the calling thread. Worker cancellation does NOT kill the subprocess. `on_error(exc, stderr: str)` is 2-arg; all other helpers use 1-arg `on_error(exc)`.
- `safe_open_url(caller, url, *, on_error=None)` — validates URL (allowlist: http/https/file/mailto; rejects javascript:/data:). **Bare file paths fail** `_validate_url` with `"missing scheme"` — always convert: `path.resolve().as_uri()` → `file:///tmp/foo.txt`.
- `safe_edit_cmd(caller, cmd_argv, path, *, line=None, on_exit=None, on_error=None)` — terminal editor via `App.suspend()`. GUI editors fall through to `safe_open_url`. `_suspend_busy` flag prevents collision with TTE effects (also guarded by `IOService.play_effects_async`).
- `safe_read_file` / `safe_write_file` — 1-arg `on_error(exc)`, no stderr concept.
- `cancel_all(app)` — wired into `HermesApp.on_unmount`; cancels all `"io_boundary"` group workers.
- `scan_sync_io(paths)` → `list[(file, lineno, call_name)]` — AST scanner.
- `# allow-sync-io: <reason>` (≥3 char reason) exempts a call-site. Scanner window: `[lineno-2, lineno+2]`. Aliased imports (`import subprocess as _sp`) and `path_var.open(...)` are NOT caught — verify manually.
- Worker cancellation does NOT kill the subprocess; callbacks in cancelled workers are silently dropped.
- Every callback touching `self.*` must start `if not self.is_mounted: return` (worker path only — sync validation-failure paths don't need this).
- `get_current_worker().is_cancelled` checked before subprocess.run AND before dispatching callbacks.

**`_safe_callback(app, cb, *args)` contract** (worker-thread-only; never wrap callbacks in another `call_from_thread`):
```python
if cb is None: return
try:
    app.call_from_thread(cb, *args)
except RuntimeError:
    raise  # called from event loop = programming bug; do not swallow
except Exception:
    pass   # broken callback logic; silently drop
```

**Optimistic success gotcha:** `safe_open_url` sync-validation-failure fires `on_error` before the optimistic `flash_success()` — use an `_err_fired` flag if overwrite is unacceptable.

**`desktop_notify.notify()`** requires `caller` kwarg — any new call site must pass `self` or `self.app`.

**Test patch targets** — `_open_external_direct` shim was deleted 2026-04-24. Patch `hermes_cli.tui.tool_panel.safe_open_url`, not `subprocess.Popen`. Extract `on_error` from `mock.call_args.kwargs` and invoke manually; `is_mounted` is a read-only property — use `patch.object(type(panel), "is_mounted", new_callable=PropertyMock, return_value=True)`.

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
- `_LineClassifier` — pure detection methods, no mutable state. Instantiated as `self._clf`. **All regex calls in dispatchers must go through `self._clf`** — the classifier is the single source of truth; inline regex calls in dispatch methods will silently diverge.
- `process_line()` uses `if self._state != "NORMAL": dispatch_non_normal(); if self._state == "NORMAL": ...` — both checks are `if`, not `elif`. When a non-NORMAL handler returns `False` (block close), state resets to NORMAL and the closing line re-enters the NORMAL classifiers. Do NOT convert to `elif`.
- `_dispatch_non_normal_state`: `_active_block is None` guard in each state resets to NORMAL and returns `False` (recovery path, no assert). Safe under `python -O`.
- `_emit_rule()` uses `self._prose_log.write_with_source(rule, "---")` — never append to `_prose_log._plain_lines` directly. The proxy handles dim wrap and plain tracking.
- `_DimRichLogProxy` overrides `write_with_source` (dim italic wrap + plain append), `write` (forward only, no plain update), and `write_inline` (dim italic per TextSpan, plain accumulate). Use `write_with_source` for any call that needs copy-buffer tracking.

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
- Composer assist ownership is centralized in `AssistKind` + `HermesInput._resolve_assist(...)`. Use it for overlay / skill-picker / none transitions instead of ad hoc picker teardown or direct overlay flags.
- `_completion_overlay_active` is the source of truth for completion-mode detection inside `_compute_mode()`. Do not query overlay DOM state from the mode resolver.
- `_refresh_placeholder()` is the single source of truth for input placeholder text — never set `self.placeholder` directly. Current priority: locked > rev-search > completion > bash > error > idle.
- `_set_input_locked()` now owns the real disabled-state transition as well as visuals. It tracks `_locked` and `_pre_lock_disabled`, restores the prior disabled state on unlock, and is intentionally idempotent.
- `watch_error_state` and rev-search enter/exit paths own the `--error` / `--rev-search` host classes. Add/remove classes incrementally; do not replace the full class set.
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
- `DrawbrailleOverlay` split **complete** (2026-04-24): `anim_orchestrator.py` + `drawbraille_renderer.py` + thin shell + `widgets/anim_config_panel.py`. See changelog entry below.

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

> Dense pitfall list: [references/gotchas.md](references/gotchas.md) — check before editing tricky TUI code.

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

**Custom CSS variable values must be literal hex — never variable references.** `$my-var: $warning;` silently drops `my-var` from `get_css_variables()` entirely (confirmed in Textual 8.2.3). This applies to ALL rhs references — both built-in theme vars (`$warning`, `$primary`, `$text-muted`) and other custom vars. Always use hex: `$my-var: #FEA62B;`. Built-in theme var hex equivalents: `$warning=#FEA62B`, `$primary=#0178D4`.

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

> Widget, overlay, theming, and output flow patterns: [references/patterns.md](references/patterns.md)
> Deep live e2e audit (Pilot harness + DEBUG logs + keystroke JSONL → replay seed): [references/live-audit.md](references/live-audit.md)
> Real-PTY tmux audit pass (complement to Pilot — catches kitty/sixel/SIGWINCH/OSC bugs Pilot can't see): [references/tmux-audit.md](references/tmux-audit.md)

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

### Rich `Syntax.__repr__` does not include the theme name

The spec comment "Rich's `Syntax.__repr__` includes the theme name" is **wrong** for Rich ≥15. `repr(Syntax(..., theme="dracula"))` returns `<rich.syntax.Syntax object at 0x...>` — no theme name. `Syntax._theme` is a `PygmentsSyntaxTheme` object, not a string. Two ways to assert the theme:

**Preferred — patch `rich.syntax.Syntax` and capture the kwarg:**
```python
import rich.syntax as _rich_syntax
_real = _rich_syntax.Syntax
themes = []
with patch.object(_rich_syntax, "Syntax", side_effect=lambda *a, **kw: (themes.append(kw.get("theme")), _real(*a, **kw))[1]):
    widget._render_body()
assert themes[0] == "nord"
```

**Alternative — read the resolved style class name:**
```python
theme_name = syntax._theme._pygments_style_class.__name__.lower()
assert "dracula" in theme_name  # "DraculaStyle" → "draculastyle"
```

### MagicMock `app.config` makes collapse-threshold read return 1

When an app is `MagicMock()`, `app.config` auto-returns a MagicMock. Dict-chain lookups on MagicMock (`cfg.get("tui")` etc.) stay truthy and chain further MagicMocks. `int(MagicMock())` calls `__int__` which MagicMock implements — returns **1** by default. If a renderer reads a threshold via `app.config`, tests with a bare MagicMock app will trigger that threshold unexpectedly. Always set `app.config = {}` when the test doesn't care about config:

```python
app = MagicMock()
app.get_css_variables.return_value = {"syntax-theme": "dracula"}
app.config = {}  # prevents threshold = 1 via MagicMock.__int__
```

### `_JsonCollapseWidget` child widgets in `__init__` for pure-unit toggle tests

When a widget has a `_toggle_expand()` or similar method that flips `child.display`, and tests call it without `run_test`, child widgets **must** be assigned in `__init__` (not `compose()`). `compose()` only runs after mounting; calling `_toggle_expand()` on an unmounted widget would raise `AttributeError` on missing children.

```python
class _JsonCollapseWidget(Widget):
    def __init__(self, summary_text, syntax, full_json):
        from textual.widgets import Static
        super().__init__()
        self._summary = Static(summary_text)       # in __init__
        self._syntax_view = Static(syntax)         # in __init__
        self._syntax_view.display = False
        self._full_json = full_json

    def compose(self):
        yield self._summary        # yielded in compose too for mounting
        yield self._syntax_view

    def _toggle_expand(self):
        self._syntax_view.display = not self._syntax_view.display
```

Test: `widget._toggle_expand(); assert widget._syntax_view.display is True` — no `run_test` needed.

### Rich `Color.__str__` returns full repr, not hex; comparison is case-sensitive

`str(span.style.color)` returns `"Color('#ff3333', ColorType.TRUECOLOR, ...)"` — NOT bare hex. Rich normalises hex to **lowercase** internally (e.g. `"#E06C75"` → stored as `"#e06c75"`). Test assertions must use `in` AND lower-case:

```python
# WRONG — fails (wrong form) or flaky (case mismatch)
assert str(span.style.color) == "#E06C75"
assert "#E06C75" in str(span.style.color)

# CORRECT
assert "#e06c75" in str(span.style.color).lower()
# or case-insensitive:
assert SkinColors.default().error.lower() in str(span.style.color).lower()
```

This affects any test that checks span colours from Rich `Text._spans`.

### `rich.console.Group` doesn't stringify to content — use `._renderables`

`str(Group(...))` returns the Python object repr, not rendered text. To extract content from a `Group` in tests:

```python
from rich.console import Group
from rich.text import Text

def _group_text(g):
    if isinstance(g, Group):
        return " ".join(
            r.plain if isinstance(r, Text) else str(r)
            for r in g._renderables
        )
    return g.plain if isinstance(g, Text) else str(g)
```

### `Rich.Text.append()` has no `end=` kwarg

`text.append("x", style=s, end="")` raises `TypeError: Text.append() got an unexpected keyword argument 'end'`. `end` is not an arg. Just omit it; append always concatenates without separator.

### Float field truthiness: `0.0` is falsy — use `is not None`

```python
# WRONG — skips elapsed when started_at == 0.0
if finished_at and started_at:
    elapsed = finished_at - started_at

# CORRECT
if finished_at is not None and started_at is not None:
    elapsed = finished_at - started_at
```

Any numeric field that can legitimately be `0` or `0.0` (timestamps, counts, thresholds) must be checked with `is not None`, not truthiness.

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

## Changelog

Compact index — each entry keeps only gotchas/patterns not obvious from the commit diff. For code-change detail see `git show <commit>`.

### 2026-04-28 — UX Audit D — Motion/Feedback D3+D5+D6 — 8 tests, commit `823895d04`, branch `feat/textual-migration`

**Spec:** `~/.hermes/2026-04-28-ux-audit-D-motion-feedback-spec.md`. 4 production edits + 177-line test file. D1/D2/D4 cut after multi-pass review (no real bug; `_partial_display` is dead code in code_blocks.py).

**Gotchas:**
- Textual 8.x cannot animate borders. CSS `transition: border-top 80ms` is silently ignored. For D5's fence-open cue, hard `set_timer(0.08, remove_class)` flip instead of CSS transition.
- `StreamingCodeBlock`'s body uses Pygments-styled child Text — a `color:` rule on the widget root is overridden by child Style cascades. Use `border-top:` (paints widget root only) for cues that must survive child styling.
- `_render_shimmer_row` order: y == 0 label branch must precede `self._no_color` branch, else color-mode users see only shimmer (no semantic label) — fails WCAG.
- `widgets/__init__.py:OutputPanel` already defines `on_mount` at :347 (caches startup-banner width). Adding a new `on_mount` shadows that cache — never redefine.
- Priority Esc bindings on container widgets swallow overlay-dismiss when overlays are open above. OutputPanel's Esc is non-priority; relies on focus-bubble routing (overlay grabs focus → its Esc wins).
- `app.cli` not on minimal `App(App)` test harness — wire via `app.cli = SimpleNamespace(agent=SimpleNamespace(interrupt=Mock()))`. Same for `app.status_streaming` (set as plain attr; reactive only on HermesApp).
- `ResponseFlowEngine.__init__` calls `panel.app.get_css_variables()` via StreamingBlockBuffer; tests using `__new__` must wire `panel.app.get_css_variables=Mock(return_value={})` before construction.
- `VirtualCompletionList.size`/`_shimmer_phase` are read-only Textual props/reactives; can't be set via `__new__` shim. For source-only assertions, use `inspect.getsource(...)` and assert text/order.
- D6 hint-text changes deferred to E4 (UX-audit freeze owns hint-composer key literals); D6 ships behavior, E4 sweeps wording.

### 2026-04-28 — UX Audit E: error/edge states (E1–E4) — commit cc428df73

- **E1 `result-empty` class**: `ToolHeader._render_v4()` calls `self.add_class("result-empty")` in the empty-result branch (~line 379). This triggers `update_node_styles()` which needs a mounted app; in unit tests patch `Widget.update_node_styles` to avoid the "no `_MessagePump__parent`" crash.
- **E1 label prefix**: Insert `if self.has_class("result-empty"): label_text = Text(f"○ {label_text.plain}", style="italic")` AFTER the `if self._label_rich / else header_label_v4(...)` block, BEFORE `t.append_text(label_text)` — one insertion point covers both label-building paths.
- **E2 CSS specificity**: `ToolPanel.--minified.tool-panel--error { height: auto; }` must come AFTER the `ToolPanel.--minified { height: 1; }` rule — TCSS last-wins for same-specificity; compound selector is more specific so position doesn't strictly matter but is cleaner after the rule it overrides.
- **E2 `.--focus-hint` not `.hint-row`**: The focus-hint DOM element uses class `--focus-hint` (`_core.py`). The legacy `.hint-row` selector in the existing minified rule is dead — it never matched. The E2 second rule MUST use `.--focus-hint`.
- **E3/E4 `_hint_cache`**: `_build_hints` caches via `_hint_cache` dict. Tests MUST call `_hint_cache.clear()` in `setup_method` before testing hint content — stale cache from a prior test will give wrong results.
- **E4 three sweep sites**: Key constants must be applied in THREE places in `status_bar.py`: `_build_hints` (all 8 phases), `_build_streaming_hint` (the `badge("^C", ...)` call at ~line 173), and `HintBar.render()` inline f-string fallback (~line 384). Missing any site leaves caret notation in the live UI.
- **`spec_for` patch target for ToolHeader tests**: `spec_for` is imported LOCALLY inside `_render_v4` (`from hermes_cli.tui.tool_category import spec_for`), NOT at module level. Patch `hermes_cli.tui.tool_category.spec_for`, NOT `hermes_cli.tui.tool_blocks._header.spec_for` (the latter raises AttributeError).

### 2026-04-28 — UX Audit F — Overlays/Polish F2–F8 — 14 tests, commit `917194b2f`, branch `feat/textual-migration`

**Spec:** `~/.hermes/2026-04-28-ux-audit-F-overlays-polish-spec.md`. 4 production files + 380-line test file.

**Gotchas:**
- `SkillCandidate` has NO `is_header` attribute — section headers are Textual `Option` objects added separately in `_rebuild_list`; filter via `c.enabled` only.
- `ScrollableContainer` has no `.update()` — use `remove_children(); mount(Static(...))`.
- `Static` stores content as `_Static__content` (name-mangled, Textual 8.x) — no `.renderable`.
- TCSS has no `@extend`/`@mixin` — focus-ring unification uses rule duplication with a sync comment.
- Textual `size`, `scroll_offset`, `app` are read-only properties — shadow at class body level in tests, not in `__init__`.
- CompletionList `searching` is a Textual reactive (no underscore prefix) — `self.searching`, not `self._searching`.
- `MagicMock.mount.side_effect` replacement kills `.call_args_list` — use `side_effect=` kwarg, not attribute replacement.
- F1 key-symbol consistency moved to Spec E as E4 (same `status_bar.py`/`hint_bar.py` as E3).

### 2026-04-28 — UX Audit B — Density/Truncation B1–B5 — 14 tests, commit `af966de5a`, branch `feat/textual-migration`

**Spec:** `~/.hermes/2026-04-28-ux-audit-B-density-truncation-spec.md`. 5 production edits + 310-line test file.

**Gotchas:**
- `_DROP_ORDER_COMPACT` position = drop priority (earlier = first to go). "preserve hero over duration" means put `duration` BEFORE `hero` in the list, not after.
- `OmissionBar` already has `self._narrow: bool = False` in `__init__` and sets `self._narrow = now_narrow` in `on_resize`. The `on_resize` previously set `self._label.display = False` (hid label); B4 replaces that with abbreviated `↓NL↑` text and `toggle_class("--narrow", now_narrow)`.
- `ToolCallHeader._truncated_line_count` is NOT a constructor param — add as `self._truncated_line_count: int = 0` in `__init__`, sync from `StreamingToolBlock.complete()` alongside `self._header._line_count = self._total_received`.
- Warning-tone inline Text style: use `self._colors().warning_dim` (NOT `$warning` TCSS variable — that only works in TCSS files, not Python Text() style strings).
- Env-var for `_SKELETON_DELAY_S`: `_streaming.py` already has module-level `logger = logging.getLogger(__name__)` and `import logging`. Pattern: try/except ValueError with `logger.warning(...)` fallback.
- B3 skip-timer guard: the existing mount pattern is `self._skeleton_timer = self._register_timer(self.set_timer(...))` — the double-wrap is correct (matches source).

### 2026-04-28 — R5-T-M1 ThinkingWidget default-repr leak — 4 tests, commit `e3382c33b`, branch `wt-r5-tm1`

**Spec:** `~/.hermes/2026-04-28-r5-tm1-thinking-repr-leak-spec.md`. 1 production edit + 4 tests.

**Textual default `Widget.render()` repr leak under real PTY** (`widgets/thinking.py`):
- Widgets with an empty `compose()` (children mounted dynamically via `activate()`) can emit their class+id string as visible text during transient CSS-class-transition frames under a real PTY. The default `Widget.render()` fallback fires before cascaded `display: none` resolves.
- Safe pattern: always override `render()` to return `RichText("")` for any widget whose `compose()` yields nothing and whose children are the sole renderers. The override is a no-op for Pilot (which never invokes the fallback) but suppresses the artifact under tmux/real-PTY.
- This bug is **invisible to Pilot** — only real-PTY harness (tmux) catches it. Second consecutive round where tmux pass surfaces a real bug Pilot misses (validates dual-harness procedure).

### 2026-04-28 — R3-H1/M1/L1 panel.id timing + feedback channel + ks-context fallback — merge `f0fdf63ff`, branch `feat/textual-migration`

**Spec:** `~/.hermes/2026-04-28-r3-fix-spec.md`. 7 production edits + 14 new tests.

**ToolPanel id kwarg contract** (`_core.py`, `message_panel.py`):
- `ToolPanel.__init__` passes `**kwargs` to `Widget.__init__` — the `id=` kwarg reaches Textual's base class unmodified. Always pass `id=panel_id` at construction if you want the channel registered at on_mount; never set `panel.id` after the fact for the non-collision path.
- `DOMNode.id` is a `@property` (not `Reactive`). The setter raises `ValueError` when `_id is not None` (one-write semantics). A Textual `watch_id` watcher is dead code — never auto-invoked.

**FeedbackService channel key contract** (`_core.py`, `services/tools.py`):
- `on_mount` registers `"tool-header::{self.id}"` only when `header is not None and self.id is not None`. The guard prevents `"tool-header::None"` pollution for panels without a computed id (execute_code / write_file gen-time / history-load).
- `_move_panel_channel(panel, old_id, new_id)` in `ToolRenderingService` — must be called as the SECOND line inside the adoption rename `try:` (after `view.panel.id = new_id`). If the rename raises (M19 collision), `_move_panel_channel` is skipped — channel stays under `current_id`. Use two separate try/excepts inside: deregister first, register second; split so a deregister failure doesn't prevent registration.
- `deregister_channel` is safe on missing keys (`pop(name, None)`) — safe to call with `old_id=None`.

**Test gotchas** (`test_tool_panel_feedback_channel.py`):
- `ToolPanel.compose()` yields `_block._header` (must be a real Widget instance), and `BodyPane.compose()` yields `_block` (also must be a real Widget). Use `Static` subclasses (`_FakeHeader`, `_FakeBlock`), never `MagicMock`, for the block/header.
- `FeedbackService` requires `scheduler: Scheduler` — use `_FakeScheduler` with `after(delay, cb) → _FakeCancelToken`.
- Wire `app.feedback = FeedbackService(...)` before `compose()` by setting it in `App.__init__`, not after `run_test()`.
- `_microcopy_shown = False` on block is required for the completion "done" flash gate to pass — the gate uses `getattr(block, "_microcopy_shown", True)` defaulting to `True` (skip flash).
- `FeedbackService.flash` suppresses non-exempt tones when `_settled=True` on the widget — check `getattr(panel, "_settled", False)` is False before asserting flashes.

**kitty_graphics probe latch** (`kitty_graphics.py`):
- The `global _tty_unavailable` declaration must be at the TOP of the function, before any use of `_tty_unavailable`. A `global` declaration after a read of the same name in the same function raises `SyntaxError: name '_tty_unavailable' is used prior to global declaration`.
- R3-L1 tests go in `test_kitty_graphics_latch.py` (new file), NOT `test_kitty_graphics.py` — the existing file has a module-level `pytestmark = pytest.mark.skipif(not _PIL_AVAILABLE, ...)` that silently skips all tests when PIL is absent.

**_ks_context fallback** (`_core.py`):
- The fallback `if block_id == "unknown": panel_id = self.id or ""; if panel_id.startswith("tool-"): block_id = panel_id[5:]` must be placed AFTER the existing `else:` block that sets `block_id = "unknown"`, before the final `return`. Preserves precedence: _view_state > _lookup_view_state > panel.id fallback.
- Test with `panel._view_state = None; panel._plan_tool_call_id = None` to exercise the fallback path. The `_lookup_view_state` call also falls through to "unknown" when `_plan_tool_call_id is None`.

### 2026-04-28 — tmux audit driver TM-1/TM-2 — commit `10f8d3b51`, branch `feat/textual-migration`

**Spec:** `~/.hermes/2026-04-28-tmux-audit-driver-spec.md`. New `tools/tui_audit/` package — investigative tool only, never CI.

**`TmuxDriver` context manager** (`tools/tui_audit/tmux_driver.py`):
- Always use in a `with` block — `__exit__` kills session with `check=False` (already-killed sessions are fine; caller exceptions propagate normally since `__exit__` returns `None`).
- `shutil.which("tmux")` guard in `_spawn` raises `RuntimeError` with actionable message if tmux absent. Must be first line of `_spawn` before the subprocess call.
- `send_keys(keys, literal=False)` — `literal=True` appends `-l` flag to `tmux send-keys`, required for typed text. Named keys (`Enter`, `C-c`, `Up`) do NOT use literal.
- `capture()` returns raw pane content including trailing whitespace — do not strip for cell-position assertions.
- `wait_for(pred, timeout, interval)` returns `False` on timeout (no exception) — caller decides how to handle.
- Session name: `f"hermes-audit-{uuid.uuid4().hex[:8]}"` — grep for `hermes-audit-` in `tmux ls` to find leaks.
- **Do NOT set `HERMES_CI=1`** in the env — it suppresses the keystroke recorder and audit JSONL will be empty.

**`tmux-audit.md` reference** (`~/.claude/skills/tui-development/references/tmux-audit.md`): already existed with comprehensive content (7 sections). No overwrite needed.

**Smoke test** (`tools/tui_audit/test_tmux_smoke.py`): run with `python3 tools/tui_audit/test_tmux_smoke.py` before each audit cycle. Checks spawn/capture/kill. Not under `tests/tui/` — not in CI.

### 2026-04-28 — EH-A..EH-E Exception Handling Compliance Sweep — 82 tests, commit `00954d743`, branch `feat/textual-migration`

**Specs:** `/home/xush/.hermes/spec_eh_a_services.md` through `spec_eh_e_toplevel.md`. 59 source files, ~377 bare swallows resolved.

**Three-category classification pattern** (reusable for future sweeps):
- `LOG` — unexpected failure in action/callback/worker path; add `_log.debug(..., exc_info=True)`. Use `warning` when user-visible state is left inconsistent.
- `COMMENT` — best-effort/teardown/pre-mount/CSS-lookup swallow where silence is correct; add one-line business-reason comment on the `except` line.
- `exc_info` upgrade — existing log call missing `exc_info=True`; add it mechanically.

**Modules that needed `_log` added** (check before assuming a module has one):
services/: `commands.py`, `keys.py`, `browse.py`, `bash_service.py`, `context_menu.py`, `spinner.py`
overlays/: `_adapters.py`, `config.py`, `interrupt.py`, `reference.py`
widgets/: `__init__.py`, `anim_config_panel.py`, `bash_output_block.py`, `inline_media.py`, `media.py`, `message_panel.py`, `overlays.py`, `prose.py`, `thinking.py`
top-level: `theme_manager.py`

**`interrupt.py` inline import anti-pattern**: Had `try: import logging; logging.getLogger(__name__).warning(...)` at line ~282. Replaced with module-level `_log = logging.getLogger(__name__)` + bare `_log.warning(...)`.

**Test patching targets**: Use `patch("hermes_cli.tui.services.commands._log")` form — patch the module attribute directly. For `io.py` the logger is `logger` not `_log`. For `_streaming.py` it is also `logger`. Check the module source before writing the patch path.

**Comment placement**: Business-reason comment goes on the `except Exception:` line itself as an inline comment — `except Exception:  # reason here`. Not on the `pass` line. `# noqa: bare-except` is NOT a valid substitute — replace it entirely.

### 2026-04-28 — Nameplate Sporadic Idle Beat Animation NA-1..NA-3 — 20 tests, commit `6fa62cd58`, branch `worktree-worktree-nameplate-idle-animation`

**Spec:** `/home/xush/.hermes/nameplate_idle_animation_spec.md`.

**Pattern — two-phase idle timer contract**: IDLE state uses no 30fps interval between beats. Instead: `_enter_idle_timer()` stops interval + calls `_schedule_next_beat()` which fires `set_timer(delay, _start_idle_beat)`. When one-shot fires, `_start_idle_beat()` calls `_set_timer_rate(30)` to restart interval. Beat completes → `_stop_timer()` + `_schedule_next_beat()`. `_stop_all_idle_timers()` handles both on unmount.

**New enum `_NPIdleBeat`** alongside `_NPState`: NONE/PULSE/SHIMMER/DECRYPT.

**Beat catalogue class constants**: `_BEAT_PULSE_TICKS=30`, `_BEAT_SHIMMER_TICKS=30`, `_BEAT_DECRYPT_TICKS=30` (symmetry only), `_BEAT_CATALOGUE=[PULSE,SHIMMER,DECRYPT]`.

**Decrypt beat gotcha**: completion gate is `all_locked`, NOT `tick >= _BEAT_DECRYPT_TICKS` — `_BEAT_DECRYPT_TICKS` is defined but unused as completion gate.

**Testing gotcha**: `_make_np_effects()` must stub `set_timer` as well as `set_interval`. Any test that transitions into IDLE (via `_tick_startup`, `_tick_morph`, or `_enter_idle_timer`) will crash with "no running event loop" if `set_timer` is not stubbed.

**Compat change**: `idle_effect` default changed `"breathe"` → `"auto"`. `"breathe"` aliased to `"pulse"` in `__init__`. `stream_effects.VALID_EFFECTS` no longer used by nameplate.

### 2026-04-28 — Chip Legend in ToolPanel Help Overlay CL-1 — 6 tests, commit `f6d22913b`, branch `worktree-chip-legend-cl1`

**Spec:** `/home/xush/.hermes/spec-chip-legend-f1.md`. Two string constant edits only: append "Header chips" section to `_BINDINGS_TABLE` + `overflow-y: auto; scrollbar-gutter: stable` in `DEFAULT_CSS`. No DOM changes, no new widgets. Tests assert directly on class attributes — no mount/pilot needed. Gotcha: `EnterWorktree` creates branch from `origin/main` by default — use `git worktree add` + `EnterWorktree path=` to base on a feature branch.

### 2026-04-28 — Keystroke Log Recorder KL-1..KL-7 — 15 tests, commit `db31b6c29`, branch `feat/textual-migration`

**Spec:** `/home/xush/.hermes/keystroke_log_step6a.md`. Opt-in JSONL keypress/mouse/component recorder for convergence-plan Step 6a.

**New module:** `tool_panel/_keystroke_log.py`
- `ENABLED: bool` evaluated once at module import — zero per-keypress overhead when disabled.
- Activation: `HERMES_KEYSTROKE_LOG=1` env var OR `~/.hermes/config.toml [debug] keystroke_log = true`. CI guard: `HERMES_CI=1` wins unconditionally.
- Three record functions: `record()` (key), `record_mouse()` (click/scroll), `record_component()` (action hooks).
- Key allowlist redaction: non-allowlist keys become `"<other>"` in the log.
- 5 MB rotation to `.jsonl.1` (one backup); `_rotate_if_needed()` catches `FileNotFoundError` silently.
- Widget coordinate: logged as raw `(x, y)` from event — no relative transform needed (Textual events already carry widget-relative coords).

**`_core.py` changes (KL-2/KL-6):**
- `_ks_context() -> tuple[str, str, str | None]`: shared helper returning `(block_id, phase, kind_val)`. Derives `block_id` from `vs.tool_call_id` → `f"gen-{vs.gen_index}"` → `"unknown"`.
- `on_key`, `on_click`, `on_mouse_scroll_up`, `on_mouse_scroll_down` all local-import `ENABLED` first, early-return on `not ENABLED`.
- Mouse button mapping: `event.button` int 1/2/3 → `"left"/"middle"/"right"`.

**`_actions.py` changes (KL-7):**
- `action_density_cycle` / `action_density_cycle_reverse`: capture `_old_tier` before mutation; record `"density_toggle"` after flash with `extra={"from":…,"to":…}`.
- `action_toggle_collapse`: record `"expand_toggle"` with `extra={"expanded": bool}`.
- `action_cycle_kind`: record `"kind_override"` with `extra={"from": old_kind, "to": new_kind}`.

**`tools/analyze_keystroke_log.py` (KL-5):** standalone report script, no hermes imports. 6 sections: per-key totals, zero-press bound keys, `t`-rate classifier proxy, density at first keypress per block, mouse heatmap, component interaction matrix.

**Gotcha — `SimpleNamespace.__class__` reassignment fails in tests:**
- `types.SimpleNamespace().__class__ = SomeClass` raises `TypeError: __class__ assignment only supported for mutable types or ModuleType subclasses`.
- Fix: define named stub classes inline (`class ToolCallHeader: pass`) and pass as `widget=ToolCallHeader()`.

### 2026-04-28 — Bottom Chrome Consolidation BD-1/BD-2 — 12 tests, commit `79fe2b45b`, branch `worktree-bottom-chrome-consolidation`

**Spec:** `/home/xush/.hermes/spec-bottom-chrome-consolidation.md`. Recovers 1–2 always-visible chrome rows.

**BD-1 — `#nameplate-hint-row` Horizontal container:**
- `app.compose()` wraps `AssistantNameplate` + `HintBar` in `with Horizontal(id="nameplate-hint-row"):`.
- CSS: `#nameplate-hint-row { height: 1; width: 1fr; }`. `AssistantNameplate` pins at `width: 24; min-width: 12`. `HintBar` takes `width: 1fr`.
- `HintBar.render()` uses `self.content_size.width` (unaffected — already reading fractional width).
- Compact density rule: added `HermesApp.density-compact #nameplate-hint-row AssistantNameplate { display: none; }` for higher specificity than `HermesApp.density-compact AssistantNameplate` since `#id` selector wins over class.

**BD-2 — SessionBar hidden; session indicator in StatusBar:**
- CSS: `SessionBar { display: none !important; }` — unconditional; `--sessions-enabled` cannot override it.
- `SessionsService._update_session_label()` — new helper that writes `app.session_label = "[n/m]"` when `session_count > 1`, else `""`. Called from `init_sessions()`, `refresh_session_bar()`, `poll_session_index()`.
- `StatusBar.render()` already reads `app.session_label` and appends ` · [n/m]` — no StatusBar changes needed.
- `Binding("S", "open_sessions", ...)` added to `HermesApp.BINDINGS` for session panel access.

**Test gotchas:**
- `SessionsService._sessions_enabled` is a property whose setter reads `self.app`. Set `svc.app = app` BEFORE any property assignment; bypass `__init__` by using `object.__new__` + `app._sessions_enabled_override = True`.
- `StatusBar.render()` calls `self.size.width` (goes through Textual layout). Use `patch.object(type(bar), "size", new_callable=PropertyMock, return_value=SimpleNamespace(width=80, height=1))` AND `patch.object(type(bar), "content_size", ...)`. Without `status_model` set on the stub app, StatusBar renders `"connecting…"` before reaching the session_label path.
- Indent threshold for "bare yield" in compose: direct compose children are at 8-space indent; inside a `with` block they're at 12-space indent. Test for `indent <= 8` to detect bare yields.
- CSS comment text can contain class/widget names — scanning for `"SessionBar"` in raw tcss hits the comment; scan line-by-line for lines that start with `SessionBar` and contain `{`.

### 2026-04-28 — Stream Flush Cadence Visibility SF-1..SF-4 — 14 tests, commit `a1f97aed3`, branch `feat/textual-migration`

**Spec:** `/home/xush/.hermes/stream_flush_cadence.md`. Pure additive debug logging — no behaviour changes.

**SF-1 — `_code_fence_buffer` lifecycle logs (`response_flow.py`):**
- `[STREAM-BUF] InlineCodeFence buffering started` fires once on the first numbered line entering the buffer.
- `[STREAM-BUF] InlineCodeFence flushing N lines → widget|prose` fires at flush, before the buffer is cleared.
- Guard: `if not self._code_fence_buffer:` — ensures the start log fires exactly once per sequence, not per line.

**SF-2 — `StreamingCodeBlock` lifecycle logs (`widgets/code_blocks.py`):**
- Added `import logging; _log = logging.getLogger(__name__)` at module level.
- `[STREAM-CODE] fence closed lang=... N lines STREAMING→COMPLETE` in `complete()` after `_state = "COMPLETE"`.
- `[STREAM-CODE] finalize_syntax lang=... N lines (batch re-render)` in `_finalize_syntax()` before `_render_syntax()`.
- `[STREAM-CODE] fence flushed (turn ended) lang=... N lines STREAMING→FLUSHED` in `flush()` after `_state = "FLUSHED"`.
- **Gotcha:** `self._log` is the `CopyableRichLog` widget — NOT the module logger. Always use bare `_log` (module-level), never `self._log.debug()`.

**SF-3 — Fence state timer (`response_flow.py`):**
- Added `import time as _time` at module level and `self._fence_opened_at: float | None = None` in `_init_fields`.
- `[STREAM-FENCE] opened lang=...` + `_fence_opened_at = _time.monotonic()` set when `_state → IN_CODE`.
- `[STREAM-FENCE] closed lang=... elapsed_ms=N.N` computed on fence close before clearing `_fence_opened_at`.
- Reset `_fence_opened_at = None` in all three `IN_CODE` exit paths: normal fence close, `flush()`, and `_handle_unknown_state()`.

**SF-4 — Chunk sequence counter (`services/io.py`):**
- `_seq = getattr(app, "_perf_chunk_seq", 0) + 1; app._perf_chunk_seq = _seq` — per-session counter, no `__init__` change needed.
- `[STREAM-SEQ] seq=N size=N` logged before `panel.record_raw_output(chunk)`.
- Uses `logger` (the module-level `_logging.getLogger(__name__)` already declared at line 19).

**Test patterns:**
- SF-2 uses dynamic `_Isolated = type("_Isolated", (StreamingCodeBlock,), {"app": None, "is_mounted": False})` to shadow read-only Textual properties; avoids `PropertyMock` session leakage.
- SF-3 uses `_dispatch_normal_state(raw, False)` — the second positional arg `intro_candidate` is required.
- SF-3 classifier mock must set `clf.is_block_math_oneline.return_value = None` and `clf.is_block_math_open.return_value = False` — otherwise MagicMock returns a truthy object and execution never reaches the fence detection block.

### 2026-04-28 — Tools Lifecycle Hygiene H6/H7/H8/H9/M17/M19/M21/L13 — 29 tests, commit `fd294f52c`, branch `feat/textual-migration`

**Spec:** `/home/xush/.hermes/tools_lifecycle_hygiene.md`. 8 scaffolding fixes to services/tools.py + tool_blocks/_block.py + write_file_block.py.

**H6 — LIFO pop order in `_pop_pending_gen_for`:**
- Both passes now use `sorted(..., reverse=True)`. Provider emits gen-start before start_tool_call; the newest GENERATED is the one whose args just completed.
- `_cancel_first_pending_gen` stays FIFO (oldest-first) for background-terminal cleanup. Cross-reference comment added. Do NOT flip that method.
- Test pattern: seed `_tool_views_by_gen_index = {0: v0, 1: v1}` and assert the returned view is `v1`.

**H7 — `view.gen_index = None` on adoption:**
- After `self._tool_views_by_id[tool_call_id] = view`, immediately set `view.gen_index = None`.
- Invariant: `gen_index is set ↔ view ∈ _tool_views_by_gen_index`. Violated before this fix: adopted views retained their old `gen_index`, allowing `_terminalize_tool_view` Step 11 to evict a freshly opened gen with the same index.
- Meta-test: walk all `_tool_views_by_id.values()` and assert `gen_index is None`.

**H8 — `_snapshot_turn_tool_calls()` helper:**
- New method: `with self._state_lock: return list(self._turn_tool_calls.values())`. Safe to call from `@work(thread=True)` workers (e.g. /tools overlay reload path).
- `current_turn_tool_calls()` now delegates iteration to `_snapshot_turn_tool_calls()`.
- `_state_lock` comment updated with full threading contract (workers must acquire; event-loop reads are safe without it).
- Test pattern for concurrency: `threading.Thread` writer loops 200 `_turn_tool_calls` mutations; reader loops 200 `_snapshot_turn_tool_calls()` calls; assert no `RuntimeError`.
- `_state_lock` must be `threading.RLock()` not `Lock()` — `_set_view_state` callbacks on the event-loop side can re-enter the lock.

**H9 — Stamp kind before COMPLETING transition:**
- Swap `_stamp_kind_on_completing` / `_set_view_state(COMPLETING)` order. Watchers now see `view.kind is not None` on first COMPLETING notification (concept §KIND R5).
- Test: install state-axis watcher; capture `view.kind` inside watcher when `new == COMPLETING`; assert non-None.

**M17 — Single state read:**
- `state = view.state` once before branching in `append_tool_output`. Closes re-entry risk if a future watcher mutates `view.state` mid-dispatch.
- Test: patch `_set_view_state` to immediately mutate `view.state = DONE` after the STREAMING transition; assert `append_streaming_line` was still called (because STARTED was captured before mutation).

**M19 — Atomic DOM-id adoption:**
- Removed pre-query (`self.app.query(f"#{new_id}")`) and conditional set. Replaced with direct `view.panel.id = new_id` inside `try/except Exception`. Exception logs at DEBUG with `exc_info=True`.
- Rationale: the query→set gap was non-atomic; a watcher could mount a widget with the same id between the two.
- Test: `_PanelWithReadOnlyId` class whose `id` setter raises `RuntimeError`; assert panel.id unchanged and no exception propagated.

**M21 — Depth from agent stack at gen-open time:**
- `open_tool_generation` now computes `gen_parent_id` and `gen_depth` from `_agent_stack[-1]` (stack-only; no `_explicit_parent_map` pop — that's keyed by tool_call_id which is unknown at gen time).
- Inline the stack lookup instead of calling `_compute_parent_depth` (which has side effects on `_explicit_parent_map`).
- Adoption in `start_tool_call` re-runs `_compute_parent_depth` with the real `tool_call_id` and overwrites `view.depth` — adoption remains authoritative; M21 just removes the depth=0 flicker.

**L13 — `reset_partial_state()` hook:**
- `ToolBlock.reset_partial_state()` — no-op base method. Docstring explains contract.
- `WriteFileBlock.reset_partial_state()` — clears `_bytes_written`, `_bytes_total`, `_line_scratch`, `_content_lines`, `_pre_mount_chunks`; calls `_extractor.reset()` if available.
- Adoption path in `start_tool_call` calls hook (guarded by `hasattr`) before `_wire_args`. Failure caught and logged at DEBUG — `_wire_args` always runs.
- Test pattern for `WriteFileBlock`: `WriteFileBlock.__new__(WriteFileBlock)` + manual attr init; no Widget runtime needed.

**General test patterns used in this spec:**
- `_make_service()` creates `ToolRenderingService.__new__` + manual attrs. Does NOT call `__init__` (which needs a full app + Textual runtime).
- `_make_view(...)` creates `ToolCallViewState` with `_watchers=[]` for axis-watcher tests.
- Concurrency test uses `threading.Thread` (not asyncio) since the target code is plain Python dict iteration.
- `complete_tool_call` signature: `(tool_call_id, tool_name, args, raw_result, *, is_error, summary, ...)` — all positional args required.

### 2026-04-27 — Invariant Lint Gates IL-1..IL-8 — 25 tests, branch `feat/textual-migration`

**Spec:** `/home/xush/.hermes/invariant_lint_gates.md`. 8 mechanical gates encoding `docs/concept.md` v3.6 invariants.

**File:** `tests/tui/test_invariants.py`. AST walks + regex sweeps over six owner paths (`tool_blocks/`, `tool_panel/`, `body_renderers/`, `services/{tools,plan_sync,feedback}.py`). Runtime <2s.

**IL-1 sibling-private cross-reads:** AST gate flags `self.<outer>.<inner>.…` chains where `outer` is `_panel`/`_block`/`_header` and `inner` startswith `_`. Composer ownership is an explicit per-module table — AST inference (looking for `self._x = X(...)`) doesn't work because of `super().__init__` delegation and parameter-receipt assignment. Allowlist: `_block.py`/`_streaming.py` may read `self._header._*`; `_core.py`/`_actions.py`/`_child.py` may read `self._block._*`. **Also flags `hasattr(self._panel._block, ...)` and `getattr(...)` calls** with forbidden chains as the first arg — masking-by-hasattr is a real anti-pattern observed at the canonical H1 site.

**Production fix for the canonical IL-1 violation:** `_header.py` was reading `self._panel._block._visible_count < len(self._panel._block._all_plain)`. Replaced with `block.has_partial_visible_lines()` — a public method added to `ToolBlock` (returns `False` by default) and overridden in `StreamingToolBlock` (returns `_visible_count < len(_all_plain)`). Pattern to reuse: when a sibling needs to know about another widget's internal state, expose a public boolean predicate, not the raw fields.

**IL-2 raw hex outside SkinColors:** regex sweep `#[0-9A-Fa-f]{6}`. Allowlist: `SkinColors.default()` body, dataclass field defaults inside `SkinColors` class body, module-level `_*_FALLBACK` constants matching `^_[A-Z][A-Z0-9_]*_FALLBACK$`, lines with `# noqa: hex`, hex appearing inside a `#` comment (split each line at first `#` and only sweep code portion). New module constants added during cleanup: `_ERROR_FG_FALLBACK` (`_grammar.py`, `shell.py`), `_DIFF_ADD_BG_FALLBACK`/`_DIFF_DEL_BG_FALLBACK` (`_block.py`), `_ACCENT_FALLBACK` (`_footer.py`), `_APP_BG_FALLBACK` (`_actions.py`).

**IL-3 microcopy form:** `_collect_hints` returns `list[tuple[str, str]]` — bracket form `[c]opy` is render-time decoration via `_render_hints`, never stored. Gate the tuple components separately. Key regex `[a-zA-Z]|Esc|↵|Enter|F[0-9]+|[Ss]hift\+[A-Za-z]|\*` (note both `S` and `s` for shift — actual emitted keys include `"shift+d"` and `"D"`/`"E"`/`"T"`). Label regex `[a-z][a-z0-9\-]*|as [a-z][a-z0-9\-]*` — single sanctioned multi-word form is `"as <kind>"` (json/code/diff). **Test fixture for `_collect_hints`:** `MagicMock(spec=_ToolPanelActionsMixin)` — `_lookup_view_state` lives on `_core.py:ToolPanel` not on the mixin, so assign explicitly: `obj._lookup_view_state = MagicMock(return_value=None)`. Stub all called methods (`_is_error`, `_visible_footer_action_kinds`, `_get_omission_bar`, `_result_paths_for_action`); set `_next_kind_label = None` (the code uses `getattr(...)` with that default).

**IL-4 chip drop-order:** `trim_tail_for_tier(tail_segments=, tail_budget=, tier=)` — the resolver itself doesn't see chips; trimming is per-tier `_DROP_ORDER_*` lists. Gate test: pass all entries of the tier's drop_order with `cell_len=1`, set `tail_budget=N`, expect last N to survive. TRACE excluded — `trim_tail_for_tier` returns the input unmodified for TRACE; count cap is enforced upstream.

**IL-5 status chip casing:** introspect `dir(_header)` for `_CHIP_*` names. Regex `…?[A-Z0-9+]+` — all-uppercase with optional leading ellipsis. **Migration:** delete `TestStatusChipCasing` from `test_microcopy_and_confidence.py`; IL-5 is now authoritative.

**IL-6 renderer purity:** AST walk; only `BodyRenderer` subclasses (not `BodyFooter`, `_HunkHeader` etc.); render-family methods (`render`/`build`/`build_widget`). Forbidden: `view_state.*` Name root, `self.app.*` (Textual property), `self._panel.*`, `self._block.*`. **Allowed:** `self._app.*` (renderer's stored app ref from constructor — established pattern for `_get_collapse_threshold` etc.); `self.colors`, `self._payload`, kwargs.

**IL-7 set_axis ordering:** structural test. In `services/tools.py:_set_view_state`, `set_axis(view, "streaming_kind_hint", None)` line < `set_axis(view, "state", new)` line. Hint-clear-first ensures subscribers see one consistent edge (hint=None paired with state=new). State-first would briefly expose new state with stale hint.

**IL-8 except-handler ban:** AST + raw-source comment correlation. Accepts: re-raise, `<logger>.<level>(...)` call (where logger is `_log`/`logger`/`log`/`_logger` and level is `exception`/`debug`/`info`/`critical` always-OK or `error`/`warning` with `exc_info=`), justification comment matching `# .*\b(expected|safe|noqa: bare-except)\b` on preceding-line OR within handler body span (covers inline `pass  # already gone — safe`), narrow-allowlisted exception type (`NoMatches`, `ChannelUnmountedError`) with bare pass. **Comment detection MUST be lineno-correlated** — never file-wide; `node.lineno` and `node.end_lineno` define the span. **Module-level requirement:** any module containing an `except` clause must have `import logging` and a module-level logger assignment named `_log`/`logger`/`log`/`_logger`.

**Prerequisite-cleanup pattern for IL-8:** the gate had ~178 first-run violations across 17 owner-path files. Strategy: land the gate as a failing test; produce the canonical offender list; bulk-annotate each except line with `  # noqa: bare-except` (trailing inline) for all bare-pass cases; add `import logging; _log = logging.getLogger(__name__)` to 9 modules that lacked it (`tool_blocks/_shared.py`, `tool_panel/_core.py`, `tool_panel/_child.py`, `body_renderers/{log,table,search,code,diff,json}.py`); re-run gate green. The bulk-annotate sweep was a 50-line Python helper script — for any future similar cleanup, reuse the pattern (regex offenders out, sed/edit, re-run).

**Concept.md tie-in:** `IL-1` retires concept §coupling table; `IL-2` retires §visual channel rule; `IL-3` retires §hint pipeline microcopy contract; `IL-4` retires §perception budgets H1; `IL-5` retires §microcopy rule 5; `IL-6` retires §renderer purity rule 2; `IL-7` retires §SLR-3 ordering note; `IL-8` retires project CLAUDE.md exception-handling rule.

### 2026-04-27 — Microcopy + Confidence Surface MC-1..MC-7 — 18 tests, commit `b65a47ba6`, branch `feat/textual-migration`

**MC-1 status chip constants in `_header.py`:**
- Chip constants (`_CHIP_STARTING`, `_CHIP_FINALIZING`, etc.) placed at module level; meta-test uses `re.search` on source text with a pattern that excludes the constant definition line — use a negative-lookbehind on `=` or look for the pattern only in assignment/update expressions, not after `=`.
- Docstring at `_phase_chip` must be updated in sync — the meta-test searches for lowercase forms in string literals excluding constant lines; a stale docstring will cause a false pass but is still a microcopy violation.

**MC-2 `_MORE_ROWS_CHIP` in `_streaming.py`:**
- Padding spaces (`"  ↓ N new lines  "`) removed — CSS provides padding. Tests assert no leading/trailing whitespace in `_MORE_ROWS_CHIP.format(n=5)`.

**MC-3 flash_label sweep:**
- Two files: `tool_blocks/_header.py:492` and `widgets/code_blocks.py:~104`. Both default `"✓ Copied"` → `"✓ copied"`.
- Meta-test pattern: `flash_label\s*[=:]\s*"✓\s+[A-Z]"` — matches parameter defaults; does NOT match `HintBar.hint` assignments.

**MC-4 `LayoutDecision` subscriber protocol:**
- `ToolBlockLayoutResolver._listeners` type changed from `Callable[[DensityTier], None]` to `Callable[["LayoutDecision"], None]`. Any subscriber that expected a bare `DensityTier` arg will break silently if not updated — search for all `subscribe()` call sites when touching layout_resolver.
- `_core.py._on_tier_change` now receives a `LayoutDecision` and calls `_apply_layout(decision)` directly. This deletes the local re-synthesis of `LayoutInputs` — do not re-add it.

**MC-5 `THRESHOLDS` dict in `content_classifier.py`:**
- Boundary semantics: `KIND_DISCLOSURE_BAND_LOW = 0.5` is an *exclusive* lower bound (`> 0.5`). Do NOT change `>` to `>=` when substituting the named constant — that silently widens the disclosure band.

**MC-6 `_low_confidence_caption()` in `base.py`:**
- Uses `self.colors.muted` (property, not `_colors()` helper). Returns `rich.text.Text` — not a string.
- Caption injected after `_user_forced_caption_renderable()`, before `self.build()`. When `_low_confidence_disclosed` is not set, `getattr(..., False)` short-circuits cleanly.

### 2026-04-27 — Focus Visibility + Settled State FS-1/FS-2/FS-3 — 15 tests, commit `64086b808`, branch `feat/textual-migration`

**FS-1 `FOCUS_PREFIX = "›"` in `_grammar.py`:**
- `FOCUS_PREFIX` is a module-level constant — never call `glyph(FOCUS_PREFIX)` since `›` has no `_ASCII_GLYPHS` entry (it's a semantic glyph, not a box-drawing char); add it separately if accessibility fallback is needed.
- `focus_cells = 2 if focused else 0` widens `FIXED_PREFIX_W` so `tail_budget` shrinks correctly; the prefix is appended AFTER `label_text` is fully constructed but BEFORE `t.append_text(label_text)`.
- `_fp_color` must use `getattr(self, "_focused_gutter_color", None) or self._colors().accent` — NOT `accent_color` (local var only set when a flash is active; referencing it elsewhere is `UnboundLocalError`).

**FS-2 `get_tier_gutter_glyphs()` in `_grammar.py`:**
- Import is deferred inside `_build_tier_gutter_glyphs()` — `DensityTier` import at grammar module level creates a circular import. Use a lazy-cache pattern (`_TIER_GUTTER_GLYPHS_CACHE`) so the cost is one dict construction, not per-render.
- `SkinColors` has no `.border` field — use `.separator_dim` for unfocused gutter tint. `.tool_header_gutter` is used for `_focused_gutter_color` init but `.separator_dim` is the right unfocused tone.
- `GLYPH_GUTTER_FOCUSED = "┃"` was the only glyph constant removed by FS-2 — it becomes dead code. Tests referencing it need to be updated (import the module; assert `not hasattr(mod, "GLYPH_GUTTER_FOCUSED")`).
- ERR override to `"┃"` uses existing `self._tool_icon_error` bool (consistent with all other error branches in `_render_v4`).

**FS-3 settled state:**
- `_settled_timer` must NOT be registered via `ManagedTimerMixin._register_timer` — `complete()` calls `_stop_all_managed()` which would cancel settled before it fires. Stop it manually in `on_unmount` instead.
- `_arm_settled_timer` clears `_settled = False` before arming — this ensures retry paths on already-settled blocks reset the flag (behavior table row "DONE→ERR was settled → fires; settled cleared").
- `ChannelAdapter.widget` property defaults to `None`. Only `ToolHeaderAdapter` overrides it. `HintBarAdapter` and `CodeFooterAdapter` intentionally keep `None` — settled suppression is block-level only.
- Settled guard in `flash()` reads `_record.adapter.widget` via `_record = self._channels[channel]` — note the variable is `_record` (prefixed with `_`) to visually distinguish it from the `record` variable reused below the guard.
- Test pattern for `test_incidental_flash_suppressed_when_settled`: construct `FeedbackService.__new__()` + manually wire `_channels`, `_active`, `_counter`. The `flash()` settled guard fires before any preemption or timer logic, so no scheduler mock needed for the suppressed-path test.

### 2026-04-27 — Streaming Legibility Rhythm SLR-1/2/3 — 26 tests, commit `a849a2d17`, branch `worktree-streaming-legibility-rhythm`
- **SLR-1 `_TIER_CLASS_NAMES` dict** (module-level in `tool_panel/_core.py`): `{DensityTier.HERO: "tool-panel--tier-hero", ...}`. Toggled in `_apply_layout` before `self.density = ...`. All 4 tier classes are removed, then one is added — mutual exclusion enforced.
- **`ChildPanel` subclass specificity bleed**: CSS type selectors match subclasses. `ChildPanel { margin-bottom: 0; }` (specificity 0,0,1) loses to `ToolPanel.tool-panel--tier-default { margin-bottom: 1; }` (0,1,1). Fix: explicit `ChildPanel.tool-panel--tier-* { margin-bottom: 0; }` rules placed after the ToolPanel tier rules.
- **SLR-3 sniff buffer**: `view._sniff_buffer: str | None = ""`. Accumulates chunks. Fires once when `len(buf.lstrip()) >= _MIN_HINT_PREFIX_BYTES (8)`. After firing, set to `None` to skip future calls. Pass `buf.lstrip()[:256]` to renderers — renderers use `startswith` so leading whitespace breaks detection.
- **Axis watcher registration point**: registered exactly once per tool call in `append_tool_output` at STARTED→STREAMING transition via `_register_header_hint_watcher`. Header stores `_streaming_kind_hint` and calls `self.refresh()` on axis change.
- **`streaming_kind_hint` classmethod**: added to `BodyRenderer` base as `return None`; overridden in `DiffRenderer`, `JsonRenderer`, `CodeRenderer`. Import `ResultKind` inside method to avoid circular imports.
- **Class body scoping**: Python class bodies cannot access enclosing function-scope locals. Module-level constants required for test `CSS = _SLR1_CSS`.

### 2026-04-27 — R4-1 Enter Binary Toggle — 10 tests, commit `f8b6f9ebb`, branch `feat/textual-migration`
- **`action_toggle_collapse` is now a 2-state machine**: COMPACT→DEFAULT ("expanded"), any other tier→COMPACT ("collapsed"). `_next_tier_in_cycle` is NOT called from this action; it stays alive for `action_density_cycle` (D key) only.
- **HERO reachable only via D**: Enter never targets HERO. The `_hero_rejection_reason` / HERO post-resolve check was removed from `action_toggle_collapse` (still present in `action_density_cycle`).
- **`ChildPanel.action_toggle_collapse` deleted**: The old `self.collapsed = not self.collapsed` override bypassed the resolver and the flash. After R4-1C, ChildPanel inherits the parent binary toggle — resolver path + flash on every press.
- **Hint label pattern**: `_collect_hints` Enter branches collapsed to one: `"expand"` when `collapsed=True`, `"collapse"` otherwise. Streaming branch (`"follow"`) is untouched. The `"toggle"` label is gone entirely.
- **Test pattern — action tests with SimpleNamespace**: bind `_ToolPanelActionsMixin.action_toggle_collapse.__get__(panel)` on a SimpleNamespace; stub `_resolver = MagicMock()` with `_resolver.tier = DensityTier.X`; assert `_user_override_tier`, `_user_collapse_override`, `_auto_collapsed`, `_resolver.resolve.assert_called_once()`, `_flash_header.assert_called_once_with(label, tone="info")`.
- **Stale test deletion**: `test_child_panel_enter.py::test_toggle_collapse_flips_collapsed` tested the old direct-toggle; deleted when R4-1C landed.

### 2026-04-27 — Density Cycle Completion DC-1..DC-4 — 14 tests, commit `717c5c39c`, branch `feat/textual-migration`
- **`_DENSITY_CYCLE` module-level constant** in `tool_panel/_actions.py` (lazy-initialized to avoid circular imports): `(DEFAULT, COMPACT, TRACE, HERO)`. TRACE now in cycle (Option A); `alt+t` binding retired from `_core.py`.
- **`_next_legal_tier_static(start, direction, body_lines)`** — pure module-level function, direction=+1/−1, skips HERO when `body_lines < _HERO_MIN_BODY_ROWS` (=5). Returns `start` if all candidates exhausted. **Callers** still own the post-resolve pressure flash check (`requested_tier == HERO and resolver.tier != HERO`). The pre-skip (row budget) does NOT emit a flash — it silently routes to next legal tier.
- **`action_density_cycle_reverse`** added to `_ToolPanelActionsMixin`; mirrors `action_density_cycle` exactly. `Binding("shift+d", "density_cycle_reverse", ...)` added in `_core.py`.
- **`_prev_tier_in_cycle` staticmethod** on `_ToolPanelActionsMixin` — `(idx - 1) % len(cycle)` wrap. Unknown tier → DEFAULT (ValueError branch).
- **Hint candidates** (`_collect_hints`): removed `("alt+t", "trace")`, added `("D", "density-cycle")` and `("shift+d", "density-back")` for complete, expanded blocks.
- **Test pattern for `_collect_hints` in isolation**: use `types.SimpleNamespace` + bind the mixin method via `_Mixin._collect_hints.__get__(panel)`. Wire `_result_summary_v4=None`, `_block=SimpleNamespace(_completed=True)`, stub `_is_error()`, `_get_omission_bar()`, `_visible_footer_action_kinds()`.
- **`test_tool_panel_hint_pipeline.py` fix**: `test_error_primary_is_enter_toggle_and_r_retry` → renamed to `test_error_primary_is_enter_collapse_and_r_retry` (R4-1 changed label from "toggle" to "collapse/expand"). Also density cycle test updated for 4-tier.

### 2026-04-27 — TCS Skin Contract Tightening SCT-1/SCT-2 — 9 tests, branch `worktree-tcs-skin-contract-tightening`
- **`GLYPH_WARNING = "⚠"`** added to `body_renderers/_grammar.py`; `_ASCII_GLYPHS["⚠"] = "!"` for accessibility fallback. Route stall/warning markers through `_glyph(GLYPH_WARNING)` everywhere.
- **`microcopy_line` signature gained `colors: SkinColors | None`** kwarg. Returns `Union[str, Text]`: str fast-path preserved when **both** `stalled=False` **and** `colors is None` — covers existing equality assertions in `test_streaming_microcopy.py`/`test_ux_phase2_3.py`/`test_tool_ux_pass7_a.py`. Stall span uses `f"bold {colors.warning}"` when colors provided, else literal `"bold yellow"`.
- **AGENT branch always returns `Text`** (shimmer + static thinking… both Text-typed). Don't return str for AGENT regardless of stalled/colors.
- **`tool_result_parse.error_glyph(kind, icon_mode=None)`** is the canonical icon-only accessor for `_ERROR_DISPLAY`. `icon_mode=None` resolves via `agent.display.get_tool_icon_mode()`. Unknown kind → `"network"` fallback (matches `_error_kind_display`).
- **Don't put error glyph data in `_grammar.py`**: `_ERROR_DISPLAY` already encodes 3 modes + css_var and lives where parsers populate `error_kind`. Moving it would force `_grammar.py` to import `agent.display` (icon-mode policy belongs in tool_result_parse, not the grammar layer).
- **Test pattern — patch accessibility_mode**: patch `hermes_cli.tui.constants.accessibility_mode`, NOT `_grammar.accessibility_mode`. The `_grammar.glyph()` helper does a local `from hermes_cli.tui.constants import accessibility_mode` — patching the grammar module attribute fails (`AttributeError: module ... does not have the attribute 'accessibility_mode'`).
- **Test pattern — capture `Static.update` renderable**: monkeypatch `header._badges.update` with a wrapper that stashes the arg. Use `App(App)` minimal harness (not HermesApp.run_test — VarSpec crash) for SubAgentHeader tests.
- **Visible glyph diff in sub_agent_panel emoji mode**: legacy `🌐/💀/🔒/⏱/✗` → canonical `📡/⚡/🔑/⏳/💢`. No overlap keys; canonical wins.

### 2026-04-26 — Glyph Vocabulary Cleanup GV-1..GV-4 — 12 tests, commit `c075f599e`, branch `feat/textual-migration`
- **New gutter/chip constants in `_grammar.py`**: `GLYPH_GUTTER_FOCUSED` (`┃`), `GLYPH_GUTTER_GROUP` (`┊`), `GLYPH_GUTTER_CHILD_DIFF` (`╰─`), `GLYPH_GUTTER_CHILD_PLAIN` (4-space pad), `GLYPH_CHIP_OPEN` (`[`), `GLYPH_CHIP_CLOSE` (`]`). Not routed through `glyph()` / `_ASCII_GLYPHS` — gutter glyphs have never had ASCII fallbacks; chip brackets are ASCII already.
- **`chip(key, label, *, bracketed=True) -> Text` helper** added to `_grammar.py`. Bracket pair uses `GLYPH_CHIP_OPEN/CLOSE` with `"dim"` style; key is `"bold"`; label is `"dim"`. All three chip surfaces (hint row `_actions.py`, footer buttons `_footer.py`, collapsed strip `_completion.py`) now call `chip()` instead of inline f-strings or local helpers.
- **Hint row local `_chip(t, key, label)` deleted** from `_actions.py`. Old form mutated `t` in-place (3 args). New `chip()` returns a `Text` (2 args); call site is `t.append_text(chip(k, l, bracketed=False))`. Same pattern applies in `_truncate_hints`.
- **`_footer.py` Button label migration**: `RichText(f"[{k}] {l}", no_wrap=True)` → `_chip(k, l, bracketed=True)` + `label._no_wrap = True`. `Text._no_wrap` is the internal field — don't use `label.no_wrap = True` (that just adds an unrecognized instance attribute).
- **Collapsed strip separator changed**: old code padded with trailing `"  "` between chips. New code uses `_glyph(GLYPH_META_SEP)` separator (` · `), consistent with hint row.
- **`streaming_microcopy.py` separator migration**: import `GLYPH_META_SEP, glyph as _glyph` at module level; compute `_SEP = _glyph(GLYPH_META_SEP)` inside `microcopy_line()` (deferred so accessibility runtime state is respected). All 8 literal ` · ` f-string sites replaced. `_completion.py` had one extra `  ·  ` (double-spaced) in remediation text — migrated too.
- **Meta-test pattern for glyph migration**: `subprocess.run(["grep", "-n", "┃", ...])` then filter out docstring/comment lines (lines where stripped content starts with `#` or contains `"""`). A docstring like `"""header: '  ┊ …'"""` would otherwise trip the assertion.
- **Meta-test scope for separator**: Check only the _migrated_ files (`_actions.py`, `_completion.py`, `_footer.py`, `streaming_microcopy.py`) — not all of `tool_blocks/` and `tool_panel/`. Other files (`_streaming.py`, `_shared.py`) still have legitimate ` · ` uses outside the chip contract.

### 2026-04-26 — Kind Override UX KO-A..KO-D — 14 tests, commit `820e2d486`, branch `feat/textual-migration`
- **Debounce pattern for action handlers**: `import time` at module top in `_actions.py`; use `getattr(self, "_cycle_kind_last_fired", 0.0)` default; tests must reset `panel._cycle_kind_last_fired = 0.0` before each call in loops to bypass the 150ms window.
- **`_user_forced` annotation**: `object.__setattr__(cls_result, "_user_forced", True)` bypasses `frozen=True`. Not a declared field — ephemeral render-time annotation. Read with `getattr(obj, "_user_forced", False)`. `_grammar.user_forced_caption(kind)` produces the dim italic disclosure caption.
- **`BodyRenderer._user_forced_caption_renderable()`**: base-class helper returns `Text | None`. Default `build_widget()` injects it before the main build output. BodyFrame-returning renderers (code/json/diff etc.) do NOT yet inject the caption — that requires per-renderer Group wrapping (out of scope for this spec).
- **Cycle is 7 stops** (None + CODE + JSON + DIFF + TABLE + LOG + SEARCH). TEXT dropped. A full cycle from None is exactly 7 presses. Legacy test updated.

### 2026-04-26 — Lifecycle Legibility LL-1..LL-6 — 38 tests, commit `48b55cf23`, branch `feat/textual-migration`
- **`density_flash_text(last, new_tier, reason)` is a pure function** in `tool_panel/_core.py`. Test it directly — no Textual machinery needed. The 4 suppression rules: `last is None` (initial), same tier, non-"auto" reason → all suppress.
- **`DensityResult` dataclass** in `tool_panel/layout_resolver.py` carries `(tier, reason)` — lightweight snapshot for flash comparison. Re-exported from `tool_panel/density.py`.
- **`RendererKind` enum** in `body_renderers/__init__.py`. `str` mixin for JSON/logging serialisation. Cycle order: `DIFF → CODE → PLAIN → DIFF`.
- **`FlashMessage` / `KindOverrideChanged` / `KindOverrideChip`** in `widgets/status_bar.py`, re-exported from `widgets/__init__.py`. `KindOverrideChip` is a `Static` (not a Widget subclass) — `can_focus=False`.
- **`ToolCallViewState` gained 2 fields**: `completing_started_at: float | None = None`, `density_reason: Literal["auto","user","error_override","initial"] | None = None`. Both are read by header/chip logic; write via `set_axis` or direct assignment from `_apply_layout`.
- **`ToolCallState.PENDING`** added as the first enum value. Existing tests that enumerate all states must add `PENDING` or they fail the coverage check.
- **`ToolCallHeader`** in `_header.py`: two `Static` children (`.phase-chip`, `.finalizing-chip`); `set_state()` drives text + timer; `on_unmount()` must stop both timers.
- **`_apply_layout` patches for stub tests**: `density` and `collapsed` are Textual reactives — on `__new__` stubs they raise `ReactiveError`. Patch via `patch.object(type(panel), "density", new_callable=PropertyMock)` AND `patch.object(type(panel), "collapsed", new_callable=PropertyMock)`. `is_attached` and `app` also need PropertyMock.

### 2026-04-26 — Hint Row & Feedback Polish HF-A..HF-G — 22 tests, branch `feat/textual-migration`
- **`_visible_footer_action_kinds()`**: best-effort DOM query returning chip `.name` attrs from `_footer_pane._action_row.query(".--action-chip")`; returns `set()` if footer hidden or DOM partial. Called by `_build_hint_text` to suppress duplicate hint/chip entries for `retry` and `copy_err`.
  - **2026-04-27 (HRP-3) supersedes this approach**: `FooterPane._visible_action_keys: frozenset[str]` is now set by `_rebuild_action_buttons` (covers both early-return paths) and cleared in `_refresh_visibility`'s hidden branch. `_build_hint_text` reads it via a 3-gate guard: `is_mounted` AND `panel.has_pseudo_class("focus-within")` AND `fp.styles.display != "none"`. The focus-within gate is critical — action chips are mounted-but-invisible when the panel isn't focus-within (CSS at `_footer.py:238`), so deduping there would silently strip affordances.
- **`_toggle_hint_shown_at: float`**: replaces the boolean `_toggle_hint_shown`. Initialized to `0.0` in `__init__`. `on_focus` re-shows the "(Enter) toggle" hint only when `monotonic() - _toggle_hint_shown_at >= 300`. Import `time as _time` locally inside `on_focus` — don't try to patch `hermes_cli.tui.tool_panel._actions.time`; set `_toggle_hint_shown_at` directly in tests.
- **`clipboard_cache.py`** (`hermes_cli/tui/clipboard_cache.py`): `write_html(html) → Path` writes to `~/.cache/hermes/clipboard/copy_{ts}.html`. `prune_expired(now=None) → int` deletes entries older than 24h; returns count. Called from `app.on_mount` (swallowed on failure). `action_copy_html` uses `write_html` instead of `/tmp` inline write.
- **`services/tool_tips.py`**: module-level mutable `_idx: int`. `current_tip() → (key, label)` reads without advancing; `advance()` increments; `reset()` zeroes (test-only). Tests must call `tool_tips.reset()` in `autouse` fixture to prevent cross-test order dependency.
- **`_build_hint_text` F1 label**: appends `"  F1 "` (bold dim) + `"help"` (dim) only when `not narrow` (width >= 50). Old bare `"  F1"` is gone.
- **`action_show_help` discovery gate**: marks all ToolCategory discovered only when `is_opening` (overlay was hidden). Closing the overlay no longer adds to `_DISCOVERY_SHOWN_CATEGORIES`.
- **`action_open_primary` flash order**: `_flash_header("opening…")` now fires BEFORE the `_open_path_action` call in the header-path branch. Failure branch flashes `"open failed"` with `tone="error"`.

### 2026-04-26 — Plan/Group Sync PG-1..PG-4 — 23 tests, commit `01c2944a0`, branch `feat/textual-migration`
- **`PlanSyncBroker` is the single source of plan row mutations** (`services/plan_sync.py`). `mark_plan_running/done/cancelled` are called ONLY from the broker's `on_view_state`. Any explicit call site in `tools.py` outside those three method defs fails the AST test `test_no_explicit_mark_plan_calls_in_tools_service`.
- **`_set_view_state(view, new)` is the choke-point** for all view state changes. Uses `RLock` for thread safety; fires `set_axis` + broker atomically. Old `set_axis(view, "state", ...)` direct calls in tools.py are all migrated. The exception: fresh-start constructor (`ToolCallViewState(..., state=STARTED, ...)`) cannot use `_set_view_state` pre-construction — fire broker manually after assignment.
- **`view.dur_ms` must be stamped BEFORE `_set_view_state`** for terminal states. The broker reads `view.dur_ms or 0` when dispatching `mark_plan_done`. In `_terminalize_tool_view` Step 9, set `view.dur_ms = dur_ms` before calling `_set_view_state`.
- **`_make_group()` in tests**: ToolGroup reactive `collapsed` stores in `g.__dict__["_reactive_collapsed"]`; Textual reactive `__get__` also requires `hasattr(obj, "id")` — satisfied by setting `g.__dict__["_id"] = None`. Cannot use `object.__setattr__(g, "collapsed", False)` — reactive descriptor intercepts it.
- **`ToolGroup._last_header_kwargs`**: initialized to `{}` in `__init__`. `_refresh_header_counts()` is a no-op when empty — safe to call before first `recompute_aggregate()` runs.
- **`StreamingLineAppended` circular import**: `_streaming.py` imports `ToolGroup` locally inside `append_line` to avoid circular import (`tool_group.py` imports `ToolCallState` from `services/tools.py`, `_streaming.py` is imported from `tool_blocks/__init__.py` which `tool_group.py` may pull in transitively). Use `from hermes_cli.tui.tool_group import ToolGroup as _TG` inside the method body.
- **`on_tool_group_streaming_line_appended` accesses `event.control`** for the block ref; `event.stop()` first. `_line_err_count` is incremented on the block directly (not the panel).

### 2026-04-26 — Skin Contract Audit SC-1..SC-5 — 23 tests, commit `2901d4874`, branch `feat/textual-migration`
- **`SkinColors` now has 5 new defaulted fields**: `error_dim`, `success_dim`, `warning_dim`, `text_muted_dim`, `tool_header_gutter`. Frozen dataclass — new fields with defaults must come AFTER all non-defaulted fields. `MappingProxyType` as a frozen-dataclass field default requires `field(default_factory=lambda: _EMPTY_MAP, ...)` — cannot use `field(default=_EMPTY_MAP)` even though MappingProxyType is immutable (Python 3.11 still raises ValueError for mutable-default guard).
- **`SkinColors.tier_accents` is a `MappingProxyType[str, str]`** covering `TIER_KEYS` (canonical spec keys) PLUS legacy display-tier keys `file/exec/query/agent` returned by `display_tier_for()`. Build it from `TIER_KEYS | frozenset({"file","exec","query","agent"})` or `.get(key, fallback)` will miss legacy tiers.
- **`_refresh_gutter_color()` now uses `self._colors().tool_header_gutter`** (SC-4). The old fallback chain `css.get("accent-interactive") or css.get("primary") or _GUTTER_FALLBACK` is removed. Tests that patched the old chain must be updated to expect `SkinColors.default().tool_header_gutter` (`"#00bcd4"`).
- **`_colors()` lazy-caches on `_skin_colors_cache`** — not set in `__init__`. First call resolves from `self.app`; subsequent calls return cached. Tests using `ToolHeader.__new__()` start with no cache; mock the app via `PropertyMock` on `type(h)`.
- **`hasattr(panel, "_resolver")` is always True for MagicMock** — use `getattr(panel, "_resolver", None) is not None` instead. Tests that mock a panel without setting `_resolver` must explicitly set `panel._resolver = None` to avoid the mock being used as a real resolver.
- **`_DROP_ORDER` alias added to `_header.py`** — re-exports `_DROP_ORDER_DEFAULT` for pre-DU callers. Flash is now at index 0 (drops first), not last — Spec A overrode the header-signal-hardening spec. Tests asserting `_DROP_ORDER[-1] == "flash"` must be updated.
- **AST scanner for style= kwarg compliance (`test_skin_contract_audit.py::TestSC5MetaTest`)**: uses `ast.walk` with a parent-mapping to identify `style=` kwargs and `Style()` positional args only. Avoids false positives from dict values (`_TONE_STYLES = {"error": "bold red"}`), docstrings, and fallback strings. Allowlist via `# noqa-skin:` inline comment.

### 2026-04-26 — Renderer Framing RF-1..RF-6 — 30 tests, branch `feat/textual-migration`
- **`BodyFrame` is the canonical Phase C container.** All Phase C `build_widget()` overrides must return `BodyFrame(header, body, footer, density=density)`. FallbackRenderer and EmptyStateRenderer are the only exceptions (bespoke layout; explicitly excluded from the meta-test).
- **`BodyFooter(*entries)` multi-entry API.** Old `BodyFooter()` (zero-arg) rendered hardcoded `[y] copy`. New form accepts `*entries: str | (key, label)`. Empty call `BodyFooter()` renders nothing. Renderers that previously had no footer now pass explicit entries (e.g., `BodyFooter(("y","copy"),("c","csv"))` for TableRenderer).
- **`build_parse_failure(text, err, *, colors)` replaces inline dim+hint patterns.** JsonRenderer parse-fail path now uses it; result is a `Rich.Text` suitable as `body=` arg to `BodyFrame`. Assert "Parse error" in `body_child.content` (Textual `Static.content` property, not `.renderable`).
- **`TableRenderer.build()` now sets `self._row_count` / `self._col_count`** before returning — `build_widget()` reads them via `getattr(self, "_row_count", 0)`. Must call `build()` first or row/col counts are 0.
- **`LogRenderer._build_body_with_counts(raw)` replaces `build()` body.** Returns `(Text, (n_info, n_warn, n_err))`. Each level-matched line is prefixed with `[INFO]`/`[WARN]`/`[ERROR]`/`[DEBUG]` chip in level color, unless `_EXISTING_CHIP_RE` (`r"^\[(INFO|WARN|WARNING|ERROR|DEBUG)\]"`) matches the rest-string — prevents `[INFO] [INFO]` doubling.
- **`ShellOutputRenderer._build_body(cleaned)` splits body from CWD logic.** `build()` calls `_build_body(cleaned)` after prepending the CWD rule; `build_widget()` puts CWD in the `header=` slot instead. The `strip_cwd` import is inside the method — patch at `hermes_cli.tui.cwd_strip.strip_cwd`, not `hermes_cli.tui.body_renderers.shell.strip_cwd` (module has no module-level attribute for it).
- **`DiffRenderer` got `_count_changed_files(lines)` private helper** — counts `---`/`+++` file pairs; `build_widget()` uses it for the summary header label `"N file(s) changed"`. Existing `_build_diff_container(lines, auto_collapse)` extracted from the old `build_widget()`.
- **`DensityTier` value attribute:** `DensityTier.COMPACT.value == "compact"` (str enum). `BodyFrame.__init__` uses `density.value` to look up the tier class. Tests constructing `BodyFrame` with a real `DensityTier` require the enum to be importable — no circular import risk since `_frame.py` defers the import inside `__init__`.
- **`Static.content` not `.renderable`.** Textual `Static` stores its content in the `.content` property (not `.renderable`). Assertions on body-slot text must use `child.content`, not `child.renderable`.
- **Patch target for `accessibility_mode` in grammar glyph tests:** `hermes_cli.tui.constants.accessibility_mode`. The grammar module imports it with `from hermes_cli.tui.constants import accessibility_mode` — patching `hermes_cli.tui.body_renderers._grammar.accessibility_mode` raises `AttributeError` because the name isn't in the grammar module's namespace.
- **Meta-test exclusion list for `test_renderers_all_use_body_frame`:** excludes `FallbackRenderer`, `EmptyStateRenderer`, and all streaming-tier renderers (`ShellRenderer`, `StreamingCodeRenderer`, `FileRenderer`, `StreamingSearchRenderer`, `WebRenderer`, `AgentRenderer`, `TextRenderer`, `MCPBodyRenderer`). Streaming renderers have different lifecycle; don't add them to the Phase C contract.

### 2026-04-25 — spec0 except-tuple cleanup — 3 tests, commit `bf2ac7eaa`
- **`except (LookupError, ValueError, TypeError, Exception):` is redundant** — Python catches by isinstance against any tuple member, so `Exception` (the supertype) dominates the narrower names. Drop the tuple form to `except Exception:` and let the comment carry the narrowing intent. No runtime behavior change.
- **Replacing a lone `pass` swallow with `_log.debug(..., exc_info=True)`** is the project-rule-compliant minimum when the swallow is genuinely correct (fallback constant covers the failure). Debug level keeps it silent at default WARNING but visible to anyone tracing the issue.
- **Targeted `_resolve_max_header_gap` test pattern** — `MagicMock` does not raise on attribute access by default, so use `type(widget).app = PropertyMock(side_effect=RuntimeError(...))` to exercise the NoActiveAppError path. For coercion failures wire a real dict via `widget.app.get_css_variables.return_value = {...}` (mock-of-dict makes `.get` return a child-mock, breaking `int(...)` differently than expected).

### 2026-04-25 — Streaming Exception Sweep (Spec A) H1+H3+H4 — 11 new + 2 retargeted tests, branch `feat/streaming-exception-sweep`
- **`LiveLineWidget._commit_lines` engine-None path now buffers AND direct-writes.** Previously the engine-None branch wrote directly to RichLog and forgot the line. Now: direct write (preserves visibility) + append to `_pre_engine_lines` (capped at `_PRE_ENGINE_CAP: ClassVar[int] = 2000`) + once-per-instance `logger.warning("engine missing ...")` latched via `_pre_engine_warned`. On engine attach, drain runs through `engine.process_line` in arrival order before the fresh line. Acceptable cost: prose lines get duplicated in the prose log (already-direct-written + replayed), but Code/Markdown blocks recover their structural mounts.
- **`on_mount` is the init point for `LiveLineWidget`** — the class has no `__init__`. Add new per-instance fields to the **top** of `on_mount` (before the `if self._tw_enabled:` branch) so they exist for both typewriter-on and typewriter-off paths.
- **Defensive `getattr(self, "_pre_engine_lines", None)` inside `_commit_lines`** — _commit_lines is reachable via `feed`/`append`, both of which require mount, but explicit > implicit. The `or assign` form (`buf = self._pre_engine_lines = []`) keeps the field initialised on rare pre-mount entry.
- **`MagicMock(spec=CopyableRichLog)` works for `isinstance` branch in `_commit_lines`.** Pair with `rl._deferred_renders = []` so the `if rl._deferred_renders:` post-loop branch doesn't try to call `self.call_after_refresh`.
- **Test pattern when `app.run_test` is broken:** instantiate `LiveLineWidget()` directly, manually set `_tw_*`, `_blink_*`, `_animating`, plus the new `_pre_engine_lines = []` and `_pre_engine_warned = False`, then `type(live).app = property(lambda s: mock_app)` to satisfy `self.app.query_one(OutputPanel)`. The `app.run_test` path on `feat/textual-migration` currently raises `StylesheetError: 'VarSpec' object has no attribute 'splitlines'` — direct construction sidesteps it.
- **`engine.feed.side_effect` lists must include enough entries** — a third call against a 2-entry list raises `StopIteration`, which the surrounding except-block then logs as another warning, blowing up `call_count` assertions. Use `[None, RuntimeError(...), None]` for "fail middle, succeed before/after" scenarios.
- **`ResponseFlowEngine` attribute names for state-snapshot tests:** `_state`, `_partial`, `_pending_code_intro`. There is **no** `_in_code_block` attribute — confusion likely with another engine. Run `dir(engine)` once before composing the snapshot.
- **`logger.exception("...")` already includes the traceback** — don't add `exc_info=True` to it. Reserve `logger.warning(..., exc_info=True)` for cases where the level should not be `EXCEPTION` but full TB is still wanted.
- **Spec A retargeted prior `test_response_flow_exception_hardening.py::TestH1ProseCallbackSwallow` tests** from `mock_log.debug.assert_called_once()` to `mock_log.exception.assert_called_once()` because the swallow shape changed; substring assertion `"_write_prose"` / `"_write_prose_inline_emojis"` pins the site label so a future swap of the two messages would still fail the test.

### 2026-04-25 — Mech Sweep A — Exception Logging Compliance EXC-1..EXC-3 — 20 tests, commit `fd47f51a8`, branch `feat/textual-migration`
- **21 modules now have `_log = logging.getLogger(__name__)`** — the 20 logger-less modules in scope plus `pane_manager.py` (already had one). Logger name is always `_log` in new modules; `pane_manager.py` keeps `_log`, `app.py` keeps `logger`.
- **All broad-Exception pass handlers replaced with `_log.debug/warning/exception`** — zero `except Exception: pass` survivors remain in the 21 in-scope modules without a marker comment. `test_no_silent_except_pass` is the AST gate; `test_no_remaining_exception_survivors` is the EXC-3 equivalence check.
- **AST lint is intentionally scoped to 21 modules** — the whole TUI tree has ~458 `except Exception: pass` sites. Running a global lint would be permanently red (Mech Sweep B will widen it). Scope the `_IN_SCOPE_MODULES` list explicitly in the test.
- **Widget.app is a read-only Textual property** — `minimap.app = mock_app` raises `AttributeError`. Spot tests that need Widget.app must either use `PropertyMock` patching or avoid direct Widget instantiation entirely. The cleanest fix is to directly exercise the except-branch body (import the `_log` name, call it inside a try/except, assert it was called) — no Widget construction needed.
- **Textual reactive raises on `__new__` instances** — `SessionBar.__new__(SessionBar); bar._sessions_data = []` raises `ReactiveError`. Same workaround: test the except-branch body directly, not through the Widget method.
- **PaneManager constructor takes `cfg: dict`, not keyword flags** — `PaneManager(enabled=True)` is `TypeError`. Use `PaneManager(cfg={"layout": "v2"})` to get `pm.enabled == True`.
- **`@work(thread=True)` worker AST check** — verify `keyword(arg="thread", value=Constant(True))` in the decorator's keywords. Function bodies inside the worker can have any structure; the test only checks that every `ExceptHandler` directly inside the function body has a log call or `raise`.
- **EXC-2 worker log levels matter** — `emoji_registry.on_mount` uses `_log.exception` (unexpected GIF decode failure), `overlays/_legacy._load_sessions` uses `_log.warning(..., exc_info=True)` (user-visible empty overlay), `app._init_workspace_tracker` uses `logger.debug(...)` (non-git is normal). Never promote non-git to WARNING/ERROR — that would spam every non-git invocation.

### 2026-04-25 — Mech Sweep B — Dead Code Removal DC-1..DC-4 — 5 tests, branch `feat/textual-migration`
- **Deleted `perf.measure_perf()`** (`hermes_cli/tui/perf.py`) — duplicated `measure()` with extra `_registry.record()` write. Zero callers in `hermes_cli/`, `tests/`, or `agent/`; only worktree mirrors had refs. Use `measure(label, silent=True)` if you need a no-log path; registry writes belong on the explicit `PerfRegistry.record()` API.
- **Deleted `tool_result_parse._ARTIFACT_CAP`** — flagged `# legacy alias`; `_ARTIFACT_DISPLAY_CAP` is the active cap.
- **Deleted `resize_utils.THRESHOLD_BAR_HIDE`** — flagged `# legacy — watch_size uses 8/9/10`. Bottom-bar visibility lives entirely in `watch_size` callbacks now.
- **`module-map.md` doc must track public-symbol deletions.** The two stale refs (one for perf, one for resize_utils) were caught only because the spec's DC-4 test reads the file and grepped for both names. Cheap insurance for any future deletion sweep — one assert line per symbol.
- **Pure attribute / string-content tests are sufficient for "is this dead?" sweeps.** No DOM, no Pilot, no app harness. `assert not hasattr(module, "X")` + a one-line happy-path call on the survivor (e.g., `with measure("smoke", silent=True): pass`) are enough; faster than any integration test and just as definitive.
- **Worktree mirrors are decoy hits in `grep`.** The audit had to filter `.claude/worktrees/*` to confirm zero callers; always `grep -v worktrees` (or scope to `hermes_cli/`, `tests/`, `agent/`) when verifying call-counts before deletion.

### 2026-04-25 — R3-VOCAB (VOCAB-1 + VOCAB-2) — 21 tests, branch `worktree-r3-vocab`
- **`SkinColors` gained two fields** — `icon_dim` (spinner low-end / dimmed tool icon) and `separator_dim` (header chevron-slot + meta separator). Defaults `#6e6e6e` / `#444444`. CSS vars `icon-dim` / `separator-dim` flow through existing `x-hermes.vars` passthrough — no skin-loader allowlist change needed (the `_X_HERMES_ALLOWED_KEYS` gate is for top-level keys under `x-hermes`, not individual var names — common error to assume otherwise).
- **`SkinColors(...)` direct constructor calls in tests must be updated** when fields are added — fixed two stale fixtures in `test_skin_palette.py` and one in `test_render_shell_selection_streaming.py`. Prefer `SkinColors.default()._replace(...)` style for forward-compatibility, but the codebase doesn't use `_replace`; current pattern is full kwargs.
- **`ToolHeader._colors()` lazy-cached SkinColors helper.** App context isn't available in `__init__` (header is built before mount), so resolution happens at first call. Cache on `_skin_colors_cache`. Recovery wraps base `Exception` because `NoActiveAppError` lives at private `textual._context.NoActiveAppError` — same trade-off as `_resolve_max_header_gap`.
- **Hex-literal fallback audit pattern.** Search `_header.py` (and similar render modules) for `"#[0-9a-fA-F]{6}"` literals — every match is either (a) a SkinColors miss (replace) or (b) a Rich named color path that's already skinnable via a different CSS var (leave). The literal `"red"` at `_header.py:380` is named-color, not hex, and reaches through `dict.get("status-error-color", "red")` which is already overridable — so it's out of scope for vocab fixes.
- **Falsy-coalesce widening for `_focused_gutter_color`.** Original used `getattr(..., "#5f87d7")` so empty string `""` would render the literal. Fix uses `getattr(..., None) or self._colors().accent` so any falsy value (None or "") falls back to skin accent. Pre-flight grep confirmed no test relied on the empty-string-shows-literal behavior — empty assignments in `test_header_tail_spec_a.py:172,184` are for unrelated label-suppression in non-flash codepaths.
- **`classify_tool` is total** under documented inputs (`tool_category.spec_for` always returns a sentinel). Five `try/except Exception` wrappers in `services/tools.py` were dead code (`except` branches never executed). Direct call is safe; `or ""` guard only needed at the one call site where `tool_name: str | None`.
- **Outer try/except Exception wrappers are NOT inherently wrong** — `_create_write_fallback` legitimately wraps its body in a logging try/except for failure isolation. But the AST sweep test `TestExceptionSweepClassifyToolDead` (deliberately strict — encodes the post-fix invariant) flags ANY enclosing try-Exception around `classify_tool/_ct`. **Hoist the call out of the outer try** (it's total, so safe outside) — adds a one-line comment explaining why.
- **AST meta-tests beat grep for "no try wraps X" invariants.** `inspect.getsource(module) → ast.parse → ast.walk` for `Try` nodes whose `handlers[i].type` is `Name(id="Exception")`, then walk each body for the target Call. Catches multi-line wrappers that line-grep misses; exposes both `func=Name(id="_ct")` and aliased `func=Attribute(attr="classify_tool")` patterns.
- **Pattern A bare-swallow → `logger.debug(msg, exc_info=True)`.** Per-site message must be specific (e.g., `"DrawbrailleOverlay.signal('reasoning') failed"`) not generic — the contract test `TestExceptionSweepLoggerContract` asserts both presence of the exact message AND `exc_info=True`. Generic messages defeat triage.
- **Pattern B narrow-then-justify.** Single-line `# vocab-2: <reason>` comment beside the narrowed `except` documents intent. `query_one` semantics are inverted (NoMatches IS the success path for ID-collision check) — narrowing must preserve the inversion or the next dev will swap branches.
- **Multi-line `_apply_gen_arg_delta` JSON parsing was overly broad** — single try/except Exception wrapped both `json.loads` (expects partial chunks) and `int()` (expects non-numeric values). Splitting into two narrow try/excepts isolates causes; otherwise the outer logger fires "update_progress failed" for what's actually a partial-stream chunk, misattributing the cause.
- **Service test pattern without app:** `ToolRenderingService.__new__(ToolRenderingService)` + manual attribute population (`svc.app = MagicMock(); svc._streaming_map = {}; ...`) bypasses `__init__` and the AppService base. Easier than building a real HermesApp mock for tests that only exercise a single method.

### 2026-04-25 — Stream Reveal Unification SR-1..SR-8 — 36 tests, branch `feat/stream-reveal-unification`
- **New module `hermes_cli/tui/stream_reveal_config.py`** — single-source-of-truth accessors (`reveal_enabled`, `reveal_cps(site=...)`, `burst_threshold`, `cursor_enabled`, `respect_reduced_motion`, `first_run_state`). `_DEFAULTS` is `MappingProxyType` to forbid mutation; `_legacy_warned: set[str]` for per-key once-per-process deprecation logging.
- **Schema:** `display.stream_reveal.{enabled,cps,respect_reduced_motion,burst_threshold,cursor}`. Master switch + per-site `reveal_cps(site=…)` keyed by `"prose" | "execute_code" | "write_file"`. Defaults: `enabled=True, cps=120` — visible-but-unobtrusive.
- **Legacy fallback:** `terminal.typewriter.*`, `display.{execute_code,write_file}_typewriter_cps` still read; one warning per key per process. Unified block always wins; legacy ignored when block present.
- **`HERMES_TYPEWRITER` env var only forces enabled axis; cps still flows from config.** Spec explicitly chose this so `HERMES_TYPEWRITER=1` with `cps: 80` runs at 80, not default 120.
- **LiveLineWidget RM gate:** prose was the only reveal site without reduced-motion compliance. Now folded into `on_mount` with same `app.get_css_variables()["reduced-motion"]` probe as the two pacer sites. NEW: `respect_reduced_motion=False` is an opt-out (default True).
- **`NoActiveAppError` is a `RuntimeError` subclass in Textual, NOT a `LookupError`** — verified at `textual/_context.py:13`. RM probe catches `(AttributeError, RuntimeError)` with `_log.debug(..., exc_info=True)`.
- **Compat shims preserved:** `widgets/utils.py` still exports `_typewriter_enabled`, `_typewriter_delay_s`, `_typewriter_burst_threshold`, `_typewriter_cursor_enabled` as thin delegates to the new accessors. `tests/tui/test_typewriter.py` still works without modification.
- **`/typewriter` slash command** in `services/commands.py:handle_typewriter_command`. Persists to YAML via `save_config(cfg)`. `_persist_stream_reveal` returns False on `is_managed()` or write failure and flashes its own hint, so callers omit success flash on False.
- **First-run telegraph (SR-8):** marker key `display.stream_reveal._first_run_telegraphed: true` (underscore-prefixed = bookkeeping, ignored by accessors). Persisted on first observation; `first_run_state()` returns `"first_run"` only when marker absent AND no legacy keys present. `HermesApp._stream_reveal_telegraphed` instance flag handles within-process race; on-disk marker handles across-process race.
- **YAML round-trip caveat (precedent matches `/anim`, `/title`):** `save_config` reformats and drops user comments. Documented in spec behavior table.
- **Mock pattern for `_persist_stream_reveal` tests:** use a `state["cfg"]` dict and patch `read_raw_config` to return `copy.deepcopy(state["cfg"])`, `save_config` to deep-copy assigned. Direct dict aliasing breaks because the helper does `cfg.setdefault("display", {}).setdefault("stream_reveal", {})` and `save_config(cfg)` would write back the same object — test assertions need a snapshot.
- **Test gotcha — `test_cps_zero_hint_cleared_on_complete` (`tests/tui/test_write_file_block.py`):** pre-spec relied on default cps=0 setting `block._progress` in on_mount; new default cps=120 skips that branch. Fix is in the test: also assign `block._progress = hint` so `complete()`'s `if self._progress is not None:` cleanup branch fires. Production behavior unchanged.
- **Existing pre-existing failures** (T42/T43 in `test_write_file_block.py`) are unrelated — `fake_call_from_thread` signature mismatch in `cli.py`, predates this spec.

### 2026-04-25 — Tool Call System Audit Round 3 — Axis-Bus Holes (Spec A) — 9 new + 4 retargeted tests
- **Axis-bus contract:** every `ToolCallViewState` mutation must flow through `set_axis(view, axis, value)` (or `_terminalize_tool_view` which calls it internally). Direct attribute writes silently bypass watchers (collapse mirror, density tier, plan-row sync, future skin observers). Three sites previously bypassed; all now routed.
- **`append_tool_output` STARTED→STREAMING is the most common transition in the system** — fires once per real tool call. `set_axis` short-circuits when `old == value`, so re-entering the method after the first line is a watcher no-op (safe).
- **`_cancel_first_pending_gen` should not call `mark_plan_done/cancelled`.** A `GENERATED` view never produced an active Plan row; pass `mark_plan=False` when delegating to `_terminalize_tool_view`. Also covers a previously-bare `except: pass` on `block.remove()` — helper Step 10 logs failures at debug.
- **`_terminalize_tool_view` Step 9 now also writes `view.is_error` BEFORE `set_axis(state)`.** Watchers reading `view.is_error` during the state-change callback see the terminal value. The redundant 4-line block in `complete_tool_call` (state + is_error + index pop) is gone — the helper invoked via `close_streaming_tool_block` owns those writes.
- **Test isolation gotcha (4 existing tests retargeted):** `complete_tool_call`'s view-removal contract has shifted from inline-write to helper-invoked-via-close. Tests that previously patched `close_streaming_tool_block` to isolate `complete_tool_call` and asserted `_tool_views_by_id` removal must now run real close with `_get_output_panel` patched to `None` (no scroll) and `mark_plan_done` patched. Real close calls helper, helper pops the index. No production behavior changed; only test isolation level shifted.
- **Pattern for asserting axis-call counts:** wrap `set_axis` with a recorder that appends to a list before calling the real fn (`patch.object(tools_mod, "set_axis", side_effect=recording_set_axis)`). Filter by `axis == 'state'` to ignore kind/density writes. NOTE: the wrapper records every call regardless of the same-value short-circuit, because the short-circuit happens *inside* the real `set_axis` after the wrapper's append. Test count = total calls including no-ops.
- **`_stamp_kind_on_completing` short-circuit:** pre-stamping `view.kind = sentinel` before `complete_tool_call` skips the classifier entirely (the `if view.kind is not None: return` guard at the top). Useful when a test wants to count state-axis writes without the classifier's kind-axis call adding noise.
- Branch: `feat/r3-axis-bus`. Spec dependency: requires R2's `_terminalize_tool_view` helper, so based off `feat/tcs-audit-round2` rather than the spec's stated `feat/textual-migration`.

### 2026-04-25 — Tool Call System Audit Round 2 R2-HIGH-01/02 + R2-MED-01 — 14 tests
- **Single terminal-cleanup helper.** `ToolRenderingService._terminalize_tool_view(tool_call_id, *, terminal_state, is_error, mark_plan, remove_visual, delete_view, dur_ms, view, gen_index)` is now the single owner of `_open_tool_count` / `_active_tool_name` / `_agent_stack` / `status_phase` / `_tool_views_by_id` / `_tool_views_by_gen_index` mutations on terminal transitions. `remove_streaming_tool_block`, `cancel_tool_call`, and the body of `close_streaming_tool_block(_with_diff)` all route through it. Direct attribute writes in those methods are GONE — do not reintroduce them.
- **`prev_state` capture before mutation is load-bearing.** Helper reads `view.state` once at entry, then operates on the snapshot. Callers must NOT pre-write the terminal state (e.g. `view.state = CANCELLED` before the helper) — that would defeat the in-flight gate at step 3 and `_open_tool_count` would never decrement. `cancel_tool_call` therefore uses `.get()` not `.pop()` for view lookup.
- **`COMPLETING` is in the in-flight set for counter decrement.** `complete_tool_call` calls `set_axis(view, "state", COMPLETING)` before the close — by the time the helper sees the view, `prev_state == COMPLETING`. Decrement set is `{STARTED, STREAMING, COMPLETING}`. GENERATED is excluded (never incremented).
- **`_active_tool_name` clear keys on `view.tool_name` (raw), not `view.label`.** Tool A whose `tool_name="execute_code"` closes; Tool B (`tool_name="read_file"`, label `"Read"`) is still active with `_active_tool_name="read_file"`. Helper compares against `view.tool_name` so it leaves Tool B's name intact.
- **`mark_plan_done` now early-returns on already-DONE/CANCELLED rows.** Defends the cross-path race where `complete_tool_call` arrives for an id whose view was already cancelled and popped (the existing line-1030 view-state guard cannot fire when `view is None`).
- **`PlannedCall.as_cancelled` mirrors `as_done`.** Explicit constructor (no `dataclasses.replace`) — house style is field-by-field. Without it `mark_plan_cancelled` raises AttributeError.
- **Adoption-time identity backfill.** `start_tool_call` adopted-path now sets `view.block._tool_call_id = tool_call_id`, updates `view.panel.id` to `tool-{id}` (collision-checked via `app.query`), and calls `panel.refresh()` after `_wire_args`. Real readers of `block._tool_call_id`: `widgets/sub_agent_panel.py:230`, `widgets/tool_panel/_child.py:81`. Without the DOM id update, PlanPanel jump-to-tool (`app.query("#tool-…")`) does not find adopted generated panels.
- **Nameplate `_pulse_stop` was a missing-method bug.** `_on_error_set` called `self._pulse_stop()`; the actual API is `self._stop_timer()`. The `except Exception: pass` swallowed the AttributeError so the error class never applied. Fix: call `_stop_timer` and replace bare-except with `_LOG.debug(..., exc_info=True)`.
- **Nameplate morph timing split.** `_DECRYPT_TICKS = 150` (5s @ 30fps) is for the cold-start splash only. `_MORPH_TICKS = 8` (~267ms) drives active/idle transitions. Confirmed call site: `_init_morph` line 1023 had a literal `150` (NOT a `_DECRYPT_TICKS` reference) that grep for the constant misses — must grep `\b150\b` separately when auditing.
- **Test pattern for service-level helper tests.** `_make_service` builds a `ToolRenderingService.__new__` with a `MagicMock` app and empty index dicts; views are constructed with `ToolCallViewState(...)` directly. Mock `_panel_for_block` with `patch.object` to skip DOM walks. Use `_seed_plan` to put `PlannedCall` rows on `app.planned_calls` for plan-transition tests.
- **`_parse_duration_ms` extracted as module-level fn.** Replaces the duplicated inline parser in `close_streaming_tool_block` / `_with_diff`. Returns `int` ms, `0` on empty/None/parse-failure. Handles `"µs"`/`"us"`/`"ms"`/`"s"` suffixes plus bare numerics.

### 2026-04-25 — Tool Block Visual Noise Cleanup VN-1/VN-2 — 12 tests
- **`:focus-within` on an ancestor with descendant target needs a self-rule.** Textual's screen `_update_focus_styles` walks `focused.ancestors_with_self` looking for the first node with `_has_focus_within=True`; only that node's subtree is re-evaluated. `_has_focus_within` is set per-node from rules whose rightmost selector matches the node's `_selector_names`. So a rule like `ToolPanel:focus-within FooterPane > .action-row` keys under `.action-row` — it sets `_has_focus_within` on the row but NOT on the panel. When `panel.focus()` fires, the screen walks panel's ancestors (panel itself), finds `_has_focus_within=False`, never refreshes the row. Symptom: button-focus path works (because button is itself the focused widget and ancestors are walked), but panel-focus path silently fails. **Fix:** add a sentinel self-rule like `ToolPanel:focus-within { offset: 0 0; }` (visually no-op since `offset: 0 0` is already the panel default) so `focus-within` ends up in ToolPanel's pseudo set and the subtree refresh fires.
- **Existing `ToolPanel:focus` rules must NOT be promoted to `:focus-within`** if their visual effect (background, border) shouldn't persist while a Button child has focus — every panel along a tab path would otherwise stay highlighted. Only convert rules that gate descendant content (FooterPane/action-row visibility).
- **`density-compact` companion edit:** when adding `:focus-within` for action-row visibility, also convert `HermesApp.density-compact ToolPanel:focus FooterPane { display: block; }` → `:focus-within`; otherwise compact mode hides the FooterPane (and therefore the action-row) the moment focus moves to a Button child of the row.
- **Streaming gate hides actions even when complete:** `FooterPane._render_footer` zeros out `actions_to_render` when `panel._block._completed is False`. Tests that `panel.set_result_summary(...)` directly must set `panel._block._completed = True` first or the streaming guard removes the `has-actions` class.
- **PropertyMock pattern for `Widget.app` + `Widget.size`:** Both are read-only Textual properties. Use `@patch.object(ToolHeader, "app", new_callable=PropertyMock)` + `@patch.object(ToolHeader, "size", new_callable=PropertyMock)` in stacked decorators. `app` mock returns a `SimpleNamespace(get_css_variables=lambda: {...}, console=SimpleNamespace(color_system="truecolor"))`. `size` mock returns a `SimpleNamespace(width=N)`. This avoids mounting the widget but still drives `_render_v4()` end-to-end.
- **Skin var validator allowlist:** non-hex skin vars (e.g. an integer cell-count like `tool-header-max-gap`) must be added to `_NON_HEX_COMPONENT_VARS` in `theme_manager.py` AND have a string default in `COMPONENT_VAR_DEFAULTS` — otherwise the hex validator rejects the value at skin-load time.

### 2026-04-25 — Renderer Registry Move 2a R-2A-1..R-2A-6 — 29 tests
- **`BodyRenderer.accepts(phase, density)`**: non-abstract classmethod; default policy is `{COMPLETING, DONE}` at any density. `accepted_phases = frozenset()` means "use default" — empty set resolves to the two post-streaming phases, NOT "reject all".
- **`pick_renderer` patch target**: the function is imported via `from hermes_cli.tui.body_renderers import pick_renderer` inside each call-site method (not at module level). Patching `hermes_cli.tui.tool_panel._completion.pick_renderer` fails with AttributeError. Correct target is `hermes_cli.tui.body_renderers.pick_renderer`.
- **`_actions.py` had no logger**: `force_renderer` swallowed all exceptions with bare `pass`. Added `import logging; _log = logging.getLogger(__name__)` at module top; `_log.exception(...)` now replaces the swallow.
- **R-2A-6 sweep grep exclusion**: the compliance grep test (`test_no_remaining_positional_pick_renderer_in_tests`) must exclude `test_renderer_registry_context.py` itself, which has intentional bad calls to test `TypeError`.

### 2026-04-25 — Tool Panel Accent Cleanup AC-HIGH-01/AC-MED-01/AC-LOW-01 — 8 tests
- **Visual accent contract:** `ToolPanel` border-left is the *only* accent system. Class triplet: `tool-panel--accent` (always after on_mount) × `category-{value}` (file/shell/code/search/web/agent/mcp/vision) × `tool-panel--error` (set/cleared via `set_result_summary`). Do not introduce a separate rail/gutter widget — the contract comment block at `hermes.tcss` L743 is load-bearing for future maintainers.
- **`ToolPanel.compose()` final shape:** yields exactly `_CollapsedActionStrip`, `BodyPane`, `FooterPane`, `Static` (focus-hint). No accent widget.
- **`ToolPanel.on_mount()` is the single class-add site:** `add_class(f"category-{self._category.value}")` + `add_class("tool-panel--accent")`. Don't duplicate elsewhere.
- **`ResultSummaryV4` test fixture:** `_make_summary` needs full kwargs — `primary, exit_code, chips=(), stderr_tail="", actions=(), artifacts=(), is_error`. Missing tuple kwargs raise `TypeError`.
- **Stale-test gotcha:** When deleting a widget module, grep tests/ for imports — `test_child_panel.py` had a `from hermes_cli.tui.tool_accent import ToolAccent` that the production `grep -r ... hermes_cli/` sweep didn't catch (different walk root). Always sweep both `hermes_cli/` and `tests/` after a widget deletion.
- **Memory hygiene caveat surfaced:** `tool-pipeline-quick-wins-spec.md` and `render-visual-grammar-spec.md` headers still say `APPROVED` though MEMORY.md lists them IMPLEMENTED — header drift. Project rule: update spec header to IMPLEMENTED at merge-time, not at memory-write time.

### 2026-04-26 — Density Unification DU-1..DU-6 — fc0239574, 35 tests
- **Single resolver:** `tool_panel/layout_resolver.py` — `ToolBlockLayoutResolver` owns all three density decisions (tier, footer visibility, header tail drop). `LayoutInputs` is the union of old `DensityInputs` + width + user_collapsed + has_footer_content. `LayoutDecision` is a frozen dataclass (tier, footer_visible, width, reason).
- **`density.py` is now a thin re-export shim** — `DensityResolver = ToolBlockLayoutResolver`, `DensityInputs = LayoutInputs`. Every existing import `from tool_panel.density import ...` continues to work without change. Do NOT write new production code importing from `density.py`; import from `layout_resolver.py` directly.
- **`_header.py` drop-order constants deleted** — `_DROP_ORDER_DEFAULT|HERO|COMPACT`, `_DROP_ORDER_BY_TIER`, `trim_tail_for_tier`, `_trim_tail_segments` are now re-exported from `_header.py` for backward compat, but originate in `layout_resolver.py`. Header call site uses `self._panel._resolver.trim_header_tail(...)` when a panel is available; `default_resolver().trim_header_tail(...)` as fallback.
- **`_apply_layout` write order contract:** axis-bus `set_axis` fires **first** (synchronous watchers see the new tier), then `self.density = tier` (Reactive scheduled on next tick). By the time `watch_density` fires, `vs.density` is already updated. Axis watchers MUST NOT read `self.density` — read their `view` argument instead.
- **`_apply_layout` is message-thread-only.** Raises `RuntimeError` when `threading.get_ident() != app._thread_id` (and `_thread_id` is not None). Off-thread callers must use `call_from_thread`.
- **Footer visibility is owned exclusively by `_apply_layout`.** `watch_collapsed` no longer mounts/unmounts footer. Only `_apply_layout` calls `self._footer_pane.display = bool`. Do not reintroduce `fp.styles.display = "block"|"none"` in `watch_collapsed`.
- **`BodyRenderer` gains `decision` kwarg** — `__init__(self, ..., *, decision: LayoutDecision | None = None)`. Stored as `self._decision`. `decision_or_default(*, phase, density, width)` returns the stored decision or synthesises a `LayoutDecision` from explicit args (no `view` reference needed). `ShellOutputRenderer` already forwards `**kwargs` so no migration needed. `DiffRenderer` was updated to accept `decision=None` explicitly.
- **`default_resolver()` process-wide singleton** — lazy-constructed, no lock needed (message-thread callers only). Used by `sub_agent_panel.py` and `message_panel.py` for standalone trim calls.
- **DU-6 binding table:** ToolPanel `T` → `Alt+T` (density_trace); ToolsOverlay `t` → `Shift+T` (toggle_view); ToolPanel `t` (cycle_kind) unchanged. `Shift+T` on ToolPanel is now free for LL-4. One-shot per-session hint fires on first ToolsOverlay open; suppressed by `app._t_rebind_hint_shown`.
- **Patch target for set_axis:** `_apply_layout` uses `from hermes_cli.tui.services.tools import set_axis` inside the method body. Patch `hermes_cli.tui.services.tools.set_axis` (the source), NOT `hermes_cli.tui.tool_panel._core.set_axis` (that name never exists in the module dict).
- **`vs._watchers = []` required in tests.** When constructing a bare `MagicMock()` for view-state (not `MagicMock(spec=ToolCallViewState)`), the real `set_axis` reads `view._watchers`. Always add `vs._watchers = []` to avoid `AttributeError`.

### 2026-04-25 — DensityResolver Move 1 DR-1/2/3/4/5 — aee5a465a, 40 tests
- **DensityResolver** is a pure-Python class (no Textual deps) in `tool_panel/density.py`. `DensityInputs` is a frozen dataclass. `ToolCallState` import in `_compute()` is deferred to avoid circular import with `services/tools.py` which imports `DensityTier`.
- **has_focus in run_test()**: Textual auto-focuses the first `can_focus=True` widget in a bare `_App`. Tests calling `_apply_complete_auto_collapse()` without explicitly blurring the panel get `has_focus=True` and the function returns early. Fix: `patch.object(type(panel), "has_focus", new_callable=PropertyMock, return_value=False)` inside the async context.
- **SimpleNamespace view-state**: When using `types.SimpleNamespace(state=ToolCallState.DONE)` as a fake view-state, add `density=DensityTier.DEFAULT, _watchers=[]` so `set_axis()` can read `old = getattr(view, "density")` without AttributeError.
- **STARTED/STREAMING block toggle**: After Move 1, `action_toggle_collapse()` goes through the resolver. STARTED/STREAMING phases return DEFAULT regardless of `user_override`. Old AXIS-5 test `test_collapse_toggle_mirrors_density` updated to use `state=DONE`.
- **Local import target for set_axis**: `_on_tier_change` does `from hermes_cli.tui.services.tools import set_axis` inline. Cannot patch via `hermes_cli.tui.tool_panel._core.set_axis` — that name doesn't exist in the module dict. Test behavior by observing `vs.density` changes instead.

### 2026-04-25 — Streaming IO Hardening L1/M2/M3 — 8694595c5, 18 tests
- **L1 (drop warning):** In `IOService.write_output()` `except asyncio.QueueFull:`, added `if not app.status_output_dropped: logger.warning(...)` gate — warns once per drop-run, resets when `status_output_dropped` clears on success.
- **M2 (flush sentinel retry):** Replaced `flush_output()` CPython-fast-path / `call_soon_threadsafe` branching with single `asyncio.run_coroutine_threadsafe(_send_flush(), loop)`. `_send_flush` tries `put_nowait(None)`; on `QueueFull` yields `await asyncio.sleep(0)` (consumer gets one tick) then retries; logs warning if second try also fails.
- **M3 (pressure metric):** Added `status_output_pressure: reactive[bool] = reactive(False)` to `HermesApp` near `status_output_dropped`. In `write_output` success path: set when `qsize >= maxsize * 3 // 4`, clear when `qsize < maxsize // 2`.
- **Gotcha (test: `_CPYTHON_FAST_PATH=False` default):** `_CPYTHON_FAST_PATH` is `False` — `write_output` uses `call_soon_threadsafe` which schedules without raising. Unit tests that need `QueueFull` to fire must patch `_CPYTHON_FAST_PATH` to `True`.
- **Gotcha (test: `run_coroutine_threadsafe` scheduling):** `flush_output()` uses `run_coroutine_threadsafe` which schedules via `call_soon_threadsafe`. To run the coroutine in tests: call `loop.run_until_complete(async_fn())` where `async_fn` does `await asyncio.sleep(0); await asyncio.sleep(0)` — two yields needed to let `ensure_future` and the task body both run.
- **Gotcha (test: gather order for retry test):** To test the sentinel-retry path, schedule `drain_one()` BEFORE `_send_flush()` in `asyncio.gather(drain_one(), _send_flush())` — their `sleep(0)` callbacks fire in registration order, so drain_one drains first, making room for _send_flush's retry.
- **Gotcha (test: coroutine leak in RuntimeError mock):** When mocking `run_coroutine_threadsafe` with `side_effect=RuntimeError`, close the coroutine arg (`coro.close()`) in the side_effect to avoid `RuntimeWarning: coroutine never awaited`.

### 2026-04-25 — Streaming Buffer Safety H1+M1 — 0f81b42ce, 14 tests
- **H1 (`_stream_buf` cap):** Added `_STREAM_BUF_MAX_CHARS = 65_536` near `_PARTIAL_FLUSH_CHARS` in `cli.py`. In `_emit_stream_text()`, after `self._stream_buf += text`, check `len > cap` and force-flush the full buffer (TUI: `write_output(chunk)`; CLI: `_cprint(...)`). Cap prevents unbounded growth on no-newline responses (base64 blobs, very long code lines).
- **M1 (`_char_queue` cap):** Added `_TW_CHAR_QUEUE_MAX = 4096` to `widgets/utils.py`. Import it in `renderers.py`; changed `asyncio.Queue()` → `asyncio.Queue(maxsize=_TW_CHAR_QUEUE_MAX)` in `on_mount`. Added `_enqueue_char(item)` helper: `put_nowait` or, on `QueueFull`, call `flush()` to drain queued chars in order then `self._buf += item` (commit line if `\n`). `feed()` now calls `_enqueue_char` instead of `put_nowait` directly.
- **Gotcha (test):** `LiveLineWidget.__new__` breaks reactive `_buf` — always use `LiveLineWidget()` (proper constructor). Then set instance attrs directly after construction; do NOT set `_buf` via reactive (it reads config in `on_mount` — set `_tw_enabled`, `_tw_delay`, etc. manually instead).
- **Gotcha (test):** `HermesCLI._emit_stream_text` needs `_ORPHAN_CLOSE_TAGS = []`, `show_reasoning = False`, `_close_reasoning_box = lambda: None`, `_message_stream_output_tokens = 0`, `_stream_box_opened = True` (to skip header), `_stream_buf = ""`, `_stream_spec_stack = []` on the stub object. Use `HermesCLI.__new__(HermesCLI)` then set attrs.

### 2026-04-25 — Axis Bus on ToolCallViewState AXIS-1/2/3/4/5 — 8171e79ca, 14 tests
- **AXIS-1:** New `hermes_cli/tui/tool_panel/density.py` — `DensityTier(str, Enum)` with `.rank` property. HERO=0, DEFAULT=1, COMPACT=2, TRACE=3.
- **AXIS-2:** `ToolCallViewState` gains `kind: ClassificationResult | None = None`, `density: DensityTier = DensityTier.DEFAULT`, `_watchers: list = field(...)`. `DensityTier` imported at module level in `services/tools.py`; `ClassificationResult` under `TYPE_CHECKING`.
- **AXIS-3:** `set_axis(view, axis, value)` — only writes when `old != value`; fires `_watchers`; logs watcher exceptions with `logger.exception` and continues. `add_axis_watcher` / `remove_axis_watcher` are module-level in `services/tools.py`.
- **AXIS-4:** `ToolRenderingService._stamp_kind_on_completing(view, result_lines)` — imported lazily inside method; idempotent (skips if `view.kind is not None`). Called from `complete_tool_call` after `set_axis(view, "state", COMPLETING)`.
- **AXIS-5:** `ToolPanel._lookup_view_state()` uses `self.app._svc_tools._tool_views_by_id.get(tool_call_id)` (NOT `tool_rendering_service` — that property doesn't exist). `_mirror_density_to_view_state()` called from both `action_toggle_collapse` and `_apply_complete_auto_collapse`.
- **Gotcha (worktree base):** `EnterWorktree` may create the worktree branch from a remote tracking ref rather than the local branch HEAD. Check `git log` after entering worktree; if commits diverge use `git reset --hard <local-branch-sha>` before starting work.
- **Gotcha (AXIS-5 test focus):** The panel must have `.focus()` called before `await pilot.press("enter")` to fire the Enter→action_toggle_collapse binding.

### 2026-04-25 — Perf Instrumentation Gaps PM-01/02/03 — c3aa848e9, 31 tests
- `perf.py` gains three new probe singletons: `_tool_probe` (`ToolCallProbe`), `_queue_probe` (`QueueDepthProbe`), `_stream_probe` (`StreamJitterProbe`).
- **PM-01 (ToolCallProbe):** `ToolCallViewState` gains `started_at: float = field(default_factory=_time.monotonic)`. Adopted path in `start_tool_call()` resets it (`view.started_at = _time.monotonic()`) to capture actual tool-start, not gen-block creation time. `complete_tool_call()` computes `dur_ms_float` from `view.started_at`; fallback to `block._stream_started_at` when `view is None`. Calls `_tool_probe.record(tool_name, tool_call_id, dur_ms_float, is_error=)`. Removed dead `import time as _t` and string-parsing `dur_ms` extraction.
- **PM-02 (QueueDepthProbe):** `services/io.py` `write_output()` `QueueFull` handler replaced with `_queue_probe.record_drop()`. `spinner.py` `tick_duration()` calls `_queue_probe.tick(app._output_queue)` after `_worker_watcher.tick()`. Tags: `[QUEUE-DROP]`/`[QUEUE-WARN]`/`[QUEUE-ALARM]` at WARNING; `[QUEUE]` heartbeat at INFO every 30 ticks.
- **PM-03 (StreamJitterProbe):** `app.py` adds `_last_stream_chunk_ts: float | None`. Reset to `None` in `mark_response_stream_started()`; gap computed and `_stream_probe.record_chunk(gap_ms, est_tokens)` called in `mark_response_stream_delta()` (reuses `now` for token window append). `finalize_response_metrics()` calls `_stream_probe.summarize()` and clears `_last_stream_chunk_ts`. Tags: `[STREAM]`/`[STREAM-STALL]`/`[STREAM-BURST]`/`[STREAM-SUMMARY]`.
- **Gotcha (test):** `IOService.__new__` leaves `app` unset — set `svc.app = mock_app` (not `svc._app`); `AppService.__init__` assigns `self.app`, not `self._app`.
- **Gotcha (PerfRegistry):** `_registry` is module-level — tests that record into it must call `_registry.clear("label")` in `setup_method` to avoid cross-test accumulation.

### 2026-04-25 — Services logging sweep LOG-1/LOG-2 — 9e616389d, 28 tests
- `sessions.py` had no logger at all. Added `import logging; _log = logging.getLogger(__name__)` at module top. 12 bare `except Exception: pass` blocks now call `_log.warning/error/exception/debug` depending on severity.
- `watchers.py` logger added similarly. 7 fixes: `handle_file_drop` now calls `_log.exception` before the flash; `on_status_compaction_progress` warns on both flash failures; `on_compact` chevron narrows to `NoMatches` and the `query(ToolPanel)` loop wrapper is **removed entirely** (query() returns empty DOMQuery, never raises NoMatches — the try/except was wrong); `on_status_error` split into two try blocks, first narrowed to NoMatches; `on_approval_state` DrawbrailleOverlay query narrowed to NoMatches; `_post_interrupt_focus` narrowed + debug on unexpected; `on_undo_state` two lock/unlock sites add debug.
- **Gotcha**: `query()` (multi-result) never raises `NoMatches` — wrapping it in `except Exception/NoMatches` silently swallows real errors from the loop body. `NoMatches` is raised only by `query_one()`.
- **Test pattern**: service methods with `import subprocess as _sp` locally — patch `subprocess.run`/`subprocess.Popen` at the stdlib level, not `sessions._sp` (module has no `_sp` attr). For `@work(thread=True)` methods, call `method.__wrapped__(svc, ...)` to bypass the thread decorator.
- **Test pattern**: `switch_to_session` guards on `_sessions_enabled`. Set `app._sessions_enabled_override = True` in tests, otherwise returns early before the code under test runs.

### 2026-04-25 — Streaming Engine Safety L2/L3/L4 — 52460c314, 18 tests
- **Logger added to `response_flow.py`**: `import logging` + `logger = logging.getLogger(__name__)` at module level (was missing). Required by all three guards.
- **L2 (`_ORPHANED_CSI_RE`)**: `re.compile(r"(?<!\x1b)\[[0-9;]+[A-Za-z]")` at module level strips CSI bodies not preceded by ESC. Applied in `feed()` as `clean = _ORPHANED_CSI_RE.sub("", self._partial)` before routing. `_partial` itself keeps raw bytes (so a subsequent chunk can complete the sequence); only the routed copy is cleaned.
- **L3 (`_detached` field)**: Added to `_init_fields()`. Both `ResponseFlowEngine._mount_code_block` and `ReasoningFlowEngine._mount_code_block` check `getattr(self._panel, "is_mounted", False)` — on `False`, log debug + set `_detached = True` + return. `process_line()` and `feed()` both guard with `if self._detached: return` at the top.
- **L4 (`_MAX_EMOJI_MOUNTS`)**: Class constant `= 50`. `_emoji_mounts: int = 0` in `_init_fields()`. Cap check + increment at the top of `_do_mount()` (inside `_mount_emoji()`). Counter reset to 0 in `flush()` after `_emitted_media_urls.clear()`. Annotated existing bare `except Exception: pass` with rationale comment.
- **Gotcha (L4 test)**: `_do_mount` takes `call_from_thread` path when `panel.app._thread_id != threading.get_ident()`. Tests must set `panel.app._thread_id = threading.get_ident()` (not `None`) to force synchronous execution and make counter increments visible.

### 2026-04-25 — Tool Call SM Hardening SM-HIGH-01/02 + SM-MED-01 — a911d09e3, 12 tests
- `complete_tool_call()` now accepts an optional `duration: str | None` kwarg. When supplied (e.g. from CLI's `_stream_start_times` timer), it overrides the block-inferred duration. Existing callers with no `duration` arg are unaffected.
- `_pending_gen_arg_deltas: dict[int, list[tuple[str, str]]]` — keyed by gen_index. `append_generation_args_delta(gen_index, tool_name, delta, accumulated)` buffers if view absent, applies immediately if view+block exist. Drained in `open_tool_generation()` at the end; dropped (not applied) in `start_tool_call()` on adopt after wiring.
- `_apply_gen_arg_delta(block, tool_name, delta, accumulated)` — calls `block.feed_delta(delta)` then `block.update_progress(written, total)` for write_file/create_file/str_replace_editor.
- SM-MED-01: panel back-reference captured in all 3 start paths: (1) `open_tool_generation()` after `view.block = block`; (2) adopted path in `start_tool_call()` after `_wire_args` if view.panel was None; (3) direct-start path: `panel = getattr(block, "_tool_panel", None)` replaces `panel = None`. Adopted path also sets `panel._plan_tool_call_id = tool_call_id`.
- SM-HIGH-01 in cli.py: `_on_tool_gen_args_delta` now calls `tui.call_from_thread(tui.append_generation_args_delta, ...)` — no more `svc._tool_views_by_gen_index` peek. `_on_tool_complete` off-mode replaces separate close+plan calls with single `complete_tool_call`. Main TUI path: pre-init `display_lines/header_stats/_result_lines` before diff try-block, snapshot `_diff_display_lines` after try-block (before verbose preview section can overwrite `display_lines`), single `complete_tool_call` at end.
- Gotcha: `block._stream_started_at` in mock tests must be set to `None`; MagicMock arithmetic raises TypeError in the duration fallback path.
- Tests: `_make_service()` helper updated to init `_pending_gen_arg_deltas = {}` — existing tests will fail if helper is copied without it.

### 2026-04-24 — Tool Call State Machine SM-01..SM-06 — 835b6e239, 29 tests
- `ToolCallState` (str, Enum) and `ToolCallViewState` (dataclass) live in `services/tools.py`. The service now owns `_tool_views_by_id` and `_tool_views_by_gen_index` in addition to the backward-compat `_turn_tool_calls` dict.
- `open_tool_generation(gen_index, tool_name)` replaces the CLI's gen-queue pattern. Routes to `open_execute_code_block`, `open_write_file_block`, or `open_gen_block` internally; skill tools get a GENERATED record with no block.
- `start_tool_call(tool_call_id, tool_name, args)` adopts the GENERATED record (if any) or creates a STARTED record directly. Calls `mark_plan_running()` internally — do NOT call it separately from cli.py.
- `_pop_pending_gen_for(tool_name)` does two passes: first match by tool_name, then FIFO fallback. Dict insertion order (Python 3.7+) gives FIFO within the same tool type.
- Adopted records retain their `gen_index` and stay in `_tool_views_by_gen_index`; they are ALSO inserted into `_tool_views_by_id` once adopted.
- Background terminal: `start_tool_call()` internally checks `args.get("background")` and calls `_cancel_first_pending_gen("terminal")`. No CLI-side handling needed.
- `mark_plan_done()` now accepts PENDING→DONE in addition to RUNNING→DONE (SM-05). This is idempotent for cases where start was skipped.
- `complete_tool_call()` always calls `mark_plan_done()` before returning, regardless of `tool_progress` mode. The SM-05 fix is in the service, and the off-mode early return in cli.py also calls `mark_plan_done()`.
- For write-tool fallbacks (SM-06): `_create_write_fallback()` sets `panel._plan_tool_call_id = tool_call_id` so PlanPanel/browse jumps work. Must happen inside the service, not in cli.py.
- `_lc_reset_turn_state()` in app.py now also resets `_tool_views_by_id` and `_tool_views_by_gen_index`.
- SM-04: `run_agent.py` concurrent executor now uses `as_completed()` with a `future_meta` dict. `_emit_completion()` helper fires progress+complete callbacks per-future; post-loop only prints and appends `messages[]` in original order. Do NOT call complete callbacks twice.
- Tests: all 29 in `tests/tui/test_tool_call_state_machine.py` use `_make_service()` lightweight helper — no HermesApp.run_test() needed. Patch `open_gen_block`, `open_execute_code_block`, `mark_plan_running` on the service instance.
- Stale test in `test_tools_overlay.py::test_current_turn_tool_calls_returns_copy` accessed `app._turn_tool_calls`; updated to `app._svc_tools._turn_tool_calls`.

### 2026-04-24 — Tool Pipeline Spec A: Header Tail Consolidation — 07109f100, 27 tests
- `Text(plain, style="dim")` stores style as base attr, NOT a span. `append_text(seg)` creates `Span(start, end, seg.style)` from the base style — but only when the Text object itself is the arg. When stripping leading whitespace (A-3), `Text(seg.plain.lstrip(), spans=_remap_spans(seg))` LOSES the base style. Fix: `Text(stripped, style=seg.style); stripped._spans.extend(_remap_spans(seg))`.
- `_remap_spans(seg, strip_n)` must use `seg._spans` (explicit spans, always a list), not `seg.style` (base style). The two are independent. Pre-existing segments with only base style → `_spans = []` → `_remap_spans` returns `[]` → style lost unless base-style is also carried.
- `Widget.__new__(ToolHeader)` bypasses `__init__`, missing `_classes = frozenset()`. `has_class("focused")` calls `self._classes.issuperset(...)` and raises `AttributeError`. Fix: add `_classes=frozenset()` to defaults in `_bare_header()` test helper.
- `accessibility_mode()` in `_grammar.glyph()` reads `hermes_cli.tui.constants.accessibility_mode`, not the widget's `_accessible_mode()`. Patching `h._accessible_mode` does NOT affect the separator glyph — must `patch("hermes_cli.tui.constants.accessibility_mode", return_value=True)`.
- `display_tier_for(cat)` added to `tool_category.py` and `__all__`. 4 tiers: `file`, `exec` (SHELL+CODE), `query` (SEARCH+WEB+MCP), `agent` (AGENT+VISION+UNKNOWN).
- New TCSS vars `$tool-tier-{file,exec,query,agent}-accent` in `hermes.tcss` must be declared there (parse-time substitution) even if also in `COMPONENT_VAR_DEFAULTS`.

### 2026-04-24 — Tool Render MEDIUM Issues (M1–M9) — feat/textual-migration, 37 tests
- `GroupHeader.size` is a read-only Textual property — use `patch.object(GroupHeader, "size", new_callable=PropertyMock, return_value=size_mock)` in tests.
- `_get_header_label(panel)` queries the panel for `ToolHeader` via `panel.query(ToolHeader)` and reads `._label`. Mocks must wire `panel.query = MagicMock(return_value=iter([header_mock]))` where `header_mock._label = path`.
- `_find_diff_targets` (new) returns list of all write panels sharing same path within the attach window. `_find_diff_target` (singular) wraps it, returns most-recent.
- Pre-existing hotkey collision in parsers: `copy_err` used `"e"`, `edit_cmd` also used `"e"`. Fixed by changing `edit_cmd` to `"E"` (uppercase) in all parsers — matches what existing tests expected.
- `_ToolsScreenState` class attrs (not instance) serve as module-level mutable state for filter persistence — `_tools_state = _ToolsScreenState()` instance, mutated in-place.
- `action_dismiss_overlay` saves state via `getattr(self, attr, default)` — existing tests use `SimpleNamespace` mocks without all fields; must be defensive.
- M5 `_REMEDIATIONS` dict import at top level in `tool_result_parse.py` — `ToolCategory` can be imported directly (no circular dep since `tool_category.py` doesn't import from `tool_result_parse.py`).

### 2026-04-24 — TUI Design 03 (input height / status phases / plan budget) — 5ab4093cc, 18 tests
- TCSS rule `.density-compact X` (bare class) matches both `_App(App)` and `HermesApp`; `HermesApp.density-compact X` only matches the concrete type.
- `HintBar.hint` / `_shimmer_tick` are Textual reactives — tests on unmounted widgets need `hb.__dict__["hint"] = ...` + `patch.object(type(hb), "hint", new_callable=PropertyMock)`. `__dict__` write bypasses `__set__` but `__get__` still checks `hasattr(obj, "id")`.
- `opacity:` unsupported in Textual 8.2.3 — dim at render path (`Text(.., style="dim")` / `color: $text-muted 55%`) instead of `.--streaming { opacity: 0.55 }`.
- Avoid `self.app` inside hot helpers on pre-mount paths; pass values as kwargs (see `PlanPanel._show_chip(tokens_in, tokens_out, ...)`).

### 2026-04-24 — OVERLAY-1/2/3 interaction fixes — 3ff79bfc, 7 tests
- `call_after_refresh` callbacks are FIFO within one sync turn; to run AFTER another queued callback: nest — `call_after_refresh(lambda: call_after_refresh(target))`.
- `Static.content` (str) is the reader — not `.renderable`.
- `ConfigOverlay` reasoning OptionList is populated lazily via `_update_reasoning_highlights()`; empty right after `show_overlay()` alone.

### 2026-04-24 — SearchRenderer + VirtualSearchList overhaul — c1454a88, 32 tests
- `_safe_refresh()` is required for pure-unit tests using `Widget.__new__()` — `self.refresh()` raises `AttributeError: _is_mounted` on unmounted objects.
- `build_rule()` applies muted colour on `Text.style` (base), not as a span — assert via `str(rule.style)` not `rule._spans`.
- Sticky group header should only render when `≥2` groups exist (single-file results have no boundary).
- `VirtualSearchList` kwarg renamed `lines_text=` → `lines=`.

### 2026-04-24 — TableRenderer + LogRenderer polish — 12858046, 20 tests
- `str(rich.Color)` returns full repr — test with `"#hex" in str(span.style.color)`, not `==`.
- `_looks_like_table`: modal-column-count rule (mode ≥2, ≥70% coverage). Bare `table.add_column()` (no label) when no header — don't fake `Col{j+1}`.

### 2026-04-24 — Audit 4 Quick Wins — 88c6c7b6, 33 tests
- `app` / `screen` / `parent` on Textual Widgets are read-only properties — always `patch.object(WidgetClass, "app", new_callable=PropertyMock, ...)`; direct assignment raises `AttributeError: property 'X' of 'Y' object has no setter`.
- `browse_mode` is a reactive — use `types.SimpleNamespace(browse_mode=False)`, not `HermesApp.__new__`.
- InterruptOverlay countdown allowlist: `_COUNTDOWN_ALLOWED = frozenset({InterruptKind.CLARIFY})`. APPROVAL/SUDO/SECRET never auto-dismiss.
- `_flash_replace_border` must early-return when `app.has_class("reduced-motion")`.

### 2026-04-24 — Audit 3 Input Mode Enum — 13f4f72e, 30 tests
- New `input/_mode.py` with `InputMode` enum + `_compute_mode()` priority `LOCKED > REV_SEARCH > BASH > COMPLETION > NORMAL`.
- `_mode: reactive[InputMode]` on `HermesInput`; `watch__mode` routes chevron + legend via module-level `_CHEVRON_GLYPHS` / `_CHEVRON_VAR` / `_LEGEND_KEY` dicts.
- Chevron color lookup uses var name WITHOUT `$` (e.g. `"chevron-rev-search"` not `"$chevron-rev-search"`).
- `_sync_legend_to_mode`: NORMAL mode with active `suggestion` must NOT hide legend (ghost preservation).

### 2026-04-24 — Audit 3 Completion Accept — c9c2fd71, 10 tests
- Enter-vs-highlighted: compute `is_exact_slash` AND `highlighted_is_typed` separately (`item.command.strip() == raw.strip()`). Accept runs when `highlighted >= 0 and not highlighted_is_typed` — covers user-moved-highlight case.
- Bounds-check `clist.highlighted` before `clist.items[...]`.
- Mid-string Tab guard: flash `"Tab: move cursor to end to accept"` (2.0s) then close overlay — direct accept would corrupt text.

### 2026-04-24 — Audit 3 Input Quick Wins — fd34922b, 22 tests
- Rev-search ↑↓: route to `_rev_search_find(direction)` BEFORE generic history nav. After `action_rev_search` match, set `self._rev_match_idx = idx` so cycling starts at correct position.
- Rev-search is substring (`query in self._history[idx]`), not `startswith`.
- Esc clears `error_state` unconditionally (no `and not self.text.strip()` guard).
- Ghost text suppressed for `len(current) < 2`. Paste flash gated on `len > 80`.

### 2026-04-24 — Audit 2 Quick Wins — 581fb2cd..20043592, 22 tests
- `StreamingToolBlock.complete()` must branch `flash_error` vs `flash_success` on `is_error` — previously always success.
- Auto-collapse tail restore bug: `_apply_complete_auto_collapse` must pre-seed `_saved_visible_start = max(0, total - visible_cap)` so expand doesn't bail on saved==0.
- `Button(Text("[reset]"), ...)` — bare `"[reset]"` is eaten by Rich markup parser.
- Don't use `inspect.stack()` to return different values in test vs prod (deleted `_DropOrder` shim).

### 2026-04-23 — Input Mode Safety — 33 tests
- `_exit_rev_mode`: capture `match_idx = getattr(self, "_rev_match_idx", -1)` BEFORE setting `self._rev_match_idx = -1`. Pre-capture is load-bearing.
- Rev-search persistent hint: `feedback.flash(..., duration=9999)` as never-expires sentinel; `app.feedback.cancel("hint-bar")` to clear explicitly.
- Bash-mode CSS border uses `$chevron-shell` not `$primary`; compact override needed: `HermesApp.density-compact HermesInput.--bash-mode:focus { border: none; }`.
- `suggestion` reactive cannot be set on `object.__new__(HermesInput)` — use plain `_FakeInput` class with `suggestion: str` attribute for `_HistoryMixin` pure-unit tests.
- `alt+up/alt+down` priority: add `priority=True` in `HermesInput.BINDINGS` to beat both `services/keys.py` browse-mode block and app-level bindings when input is focused.

### 2026-04-23 — Error recoverability + OmissionBar/ChildPanel polish — 3b9d7476, 22 tests
- Two-tick `--completing` collapse: `set_timer(0.25, _post_complete_tidy)` then `remove_class`. Under `HERMES_DETERMINISTIC=1` call inline (no timer) — tests see synchronous collapse.
- `_child_error_kinds` is a `list` (order-of-first-seen), not `set` — dedup via `if ek not in ...` before append.
- `_remediation_hint` render guard needs `_tool_icon_error` (not just `_error_kind`).
- ChildPanel `space` binding conflicts with TextArea — use `alt+c` with `priority=True`.

### 2026-04-23 — Input Feedback & Completion UX — 51cc833b, 36 tests
- `_refresh_placeholder()` MUST be the only writer of `self.placeholder`. Priority: locked > rev-search > completion > bash > error > idle. Always call AFTER updating the state that changed.
- Enter-accepts-completion intercept MUST be in `_on_key` (not `action_submit`) — `action_submit` is called programmatically and must not be overlay-gated. No `self._overlay` attribute exists — use `self.screen.query_one()`.
- `InputLegendBar` in flow layout, NOT `dock: bottom` — sits above `#input-row` because dock-bottom stack is bottom-to-top in compose order.
- `_set_input_locked()` now owns disabled-state transitions too; preserve `_pre_lock_disabled` so unlock restores the prior state instead of forcing enabled.
- `safe_write_file` kwargs: `data=` / `on_done=` (not `content=` / `on_success=`); `on_done` receives `bytes_written: int`.
- Explicit bash mode only activates on a literal leading `!` (`self.text.startswith("!")`), not `lstrip()`.
- Use `_resolve_assist(AssistKind.OVERLAY|SKILL_PICKER|NONE)` instead of direct assist-surface teardown. `_update_autocomplete()` must not clear the ghost suggestion unless an overlay/picker assist was actually active.

### 2026-04-23 — PlanPanel P1 polish — f7a4ed55, 86 tests
- `ToolPanel._plan_tool_call_id` wiring lives in `message_panel.py` **else branch** (top-level ToolPanels only) — NOT in `tools.py`. `output.query(ToolPanel)` is recursive; ChildPanels keep `_plan_tool_call_id = None` so they never match.
- Don't add `display: none` to `_ChipSegment.DEFAULT_CSS` — visibility is `self.display = bool`.
- `_ChipSegment.__init__`: consume custom `action=` kwarg before `super().__init__()` — Static does not accept it.

### 2026-04-23 — PlanPanel P0 fixes — 878d357e, 37 tests
- Test reactives at PENDING, not RUNNING — RUNNING triggers `set_interval` timer that blocks `pilot.pause()`.
- `_DoneSection` deleted; done count lives in chip header only.
- Multi-text-style in `Static.update()` requires `rich.text.Text.from_markup(...)` — plain strings with `[bold red]` render literally.
- Theme vars must be literal hex in Textual 8.2.3: `$plan-now-fg: #ffb454`, not `$plan-now-fg: $warning` (silently drops from `get_css_variables()`).

### 2026-04-23 — Startup Banner Polish — 65de2069 + 20563d73, 18 tests
- `cli.py` is at **repo root**, not `hermes_cli/cli.py`. Tests: `import cli as cli_module`.
- Wall-clock cap `MAX_WALL_S = 6.0` alongside `MAX_FRAMES = 3000`. `_tte_start = time.monotonic()` AFTER preflight queue call.
- Reduced-motion gate in `_get_startup_text_effect_config`: checks `config["tui"]["reduced_motion"]` + `HERMES_REDUCED_MOTION`; returns `None` to skip TTE.
- Static frame enqueued via `_queue_frame` (not inline) to serialize after TTE frames on the event loop; 0.25s hold is visible pause, not ordering.
- Mock `call_from_thread = MagicMock(side_effect=lambda fn: fn())` — prevents hang when no event loop is running in tests.

### 2026-04-24 — Audit 1 Phase Legibility — b76e0f6b + 1d00d678, 50 tests
- New `agent_phase.Phase` as plain-string constants (not `Enum`) — avoids import cycles and reactive-serialization friction.
- `HermesApp.status_phase` reactive; `watch_status_phase` toggles `--phase-{name}` CSS class on app root.
- `_open_tool_count` on `ToolRenderingService` — decrement in BOTH `close_streaming_tool_block` AND `close_streaming_tool_block_with_diff`. Reset to 0 in `_lc_reset_turn_state`.
- `AssistantNameplate._pause_pulse()` calls `_stop_timer()` only — deliberately does NOT remove `--active` (turn-in-progress color persists across STREAMING/TOOL_EXEC). The stop method is `_stop_timer`, not `_pulse_stop`.
- `ThinkingWidget._resolve_mode` DEEP gate reads `elapsed = time.monotonic() - getattr(self, "_substate_start", time.monotonic())`; falls back to COMPACT when `elapsed < _cfg_deep_after_s`. `_substate_start` is runtime-set only (absent → elapsed=0 → COMPACT — correct).
- `os.environ.setdefault("HERMES_DETERMINISTIC", "1")` at module top pollutes other test files in the same process — pre-existing hazard.

### 2026-04-24 — DrawbrailleOverlay split + Phase 5 cleanup — 02efe64a..93c47af1, 75 tests
- Circular-import break: `_color_utils.py` has NO deps on either `drawbraille_overlay` or `drawbraille_renderer`; both import from it. `anim_orchestrator` / `drawbraille_renderer` use `TYPE_CHECKING`-only import for `DrawbrailleOverlayCfg`.
- `_sdf_permanently_failed` cleared via direct attr write in `_do_hide`, NOT in `reset()` — prevents mid-session `_stop_anim` from re-triggering SDF retry.
- `cancel_fade_out()` must reset BOTH `_fade_state = "stable"` AND `_fade_alpha = 1.0`.
- Crossfade early-flight guard: `progress < 0.5` skip CrossfadeEngine install; still update `_carousel_idx` + `_carousel_key` so the in-flight crossfade lands on the right engine.
- All re-exports from `drawbraille_overlay` must stay (list in commit) — backward-compat contract.

### 2026-04-23 — Nameplate + ThinkingWidget lifecycle — bfff7488 + 93867798, 29 tests
- `ThinkingWidget.--fading { opacity: 0.0; transition: opacity 150ms in_out_cubic; }` requires `ThinkingWidget.--active { opacity: 1; }` or it snaps instead of animating.
- `_do_hide()` sets `self._substate = "--reserved"` + `add_class("--reserved")` (not collapse); `clear_reserve()` removes both. TCSS: `ThinkingWidget.--reserved { height: 1; display: block; opacity: 0; }`.
- `clear_reserve()` call site: `self.query_one(ThinkingWidget)` — ThinkingWidget is a direct child of `OutputPanel`, NOT `self.app.query_one`.
- `make_stream_effect` lives in `hermes_cli.stream_effects` — NOT `hermes_cli.tui.stream_effects`.
- `_LabelLine.__init__` pops `_lock` before `super().__init__("", **kwargs)` to allow shared lock passing.
- Shimmer fix: `n = max(3, len(self._frame)); offset = math.pi / n` spans π across name regardless of length.

### 2026-04-24 — Audit 1 Quick Wins — 827e6036, 23 tests
- `StatusBar` unit test pattern: subclass + `PropertyMock` for read-only `size`/`app`. Example in `test_audit1_quick_wins.py::_BarHelper`.
- `types.SimpleNamespace` + bound method pattern for widget methods without DOM/reactive deps: `panel._method = WidgetClass._method.__get__(panel)`. Do NOT use `__new__` when the attr is a class-level reactive (`PlanPanel._collapsed` raises `ReactiveError`).
- Deleted `StatusBar.__getattr__` — silent-swallow was hiding bugs.
- Ghost legend one-per-session: `_ghost_legend_shown: bool` gate on `HermesInput`; `_show_ghost_legend/_hide_ghost_legend` are module-level helpers in `_history.py`.
- Budget visibility is synchronous (`not has_active and not _collapsed and (cost_usd > 0 or tokens_in > 0)`) — no `_budget_hide_timer`.
- `ThinkingWidget._reserve_fallback_timer` — 2s timer in `_do_hide()`; `clear_reserve()` must `.stop()` it. `_clear_reserve_fallback` checks `has_class("--reserved")` before clearing (idempotent).

### 2026-04-24 — Audit 2 Discovery & Affordances — 75f2ae00..cfb00c59, 37 tests
- `FooterPane._action_row` is created in `compose()`, not `__init__` — guard via `getattr(self, "_action_row", None)` for pre-compose objects.
- `ToolPanel.action_copy_result` does NOT exist — the real method is `action_copy_body`. Map `"copy_body"` → `panel.action_copy_body` in `ACTION_KIND_TO_PANEL_METHOD`.

### 2026-04-24 — TUI Design 01 Tool Panel Affordances — 8942caeb, 6 tests
- `ACTION_KIND_TO_PANEL_METHOD` at module level in `_footer.py`. `open_first` maps to `"action_open_primary"` (NOT `"action_open_first"`).
- `FooterPane.on_button_pressed`: flash `"Action failed"` then **re-raise** when handler raises — don't silently swallow.
- `FeedbackService.LOW` is NOT a class attribute — it's a module-level constant (`LOW: int = 0` in `feedback.py`). `FeedbackService.LOW` raises `AttributeError` (silently swallowed by `except Exception: pass`). Import: `from hermes_cli.tui.services import feedback as _fb_mod; priority=_fb_mod.LOW`.
- `_trim_tail_segments` when only `{"hero", "flash"}` compete for budget: drop `hero`, keep `flash` (user-action feedback must survive longest per `_DROP_ORDER`).
- Static file preview syntax theme lookup order: `css.get("preview-syntax-theme") or css.get("syntax-theme") or "monokai"`.
- `_COLLAPSED_ACTIONS` map is lazy-init (deferred import of `ToolCategory` to break cycle).

### 2026-04-24 — Tool Render HIGH Issues (H1-H5) — test_tool_render_high.py, 34 tests
- `_get_header_label(panel)` queries Textual DOM (`panel.query(ToolHeader)`) — returns `""` for MagicMock. Patch `hermes_cli.tui.tool_group._get_header_label` with `side_effect=lambda p: p._label` in any test calling `_find_rule_match` or `_build_summary_text` that depends on label text.
- `_get_effective_tp_siblings` also must be patched to control which siblings are returned, otherwise the real impl walks `message_panel.children` which is a MagicMock.
- `read_raw_config` in `_find_rule_match` is imported **inside the function** via `from hermes_cli.config import read_raw_config` — patch at `hermes_cli.config.read_raw_config`, NOT `hermes_cli.tui.tool_group.read_raw_config`.
- `_do_append_to_group` calls `await group._body.mount(new_panel)` — use `AsyncMock()` for `_body.mount`, else `TypeError: object MagicMock can't be used in 'await' expression`.
- `_TONE_BY_KIND` is module-level (not inside `__post_init__`) to avoid dict re-creation on every `ResultSummaryV4` instantiation. `__post_init__` reads it as a constant.
- `RULE_FILE_EDIT = 4` evaluated **before** `RULE_DIFF_ATTACH = 1` in `_find_rule_match` — a `patch` tool is both a write tool and a diff tool; Rule 4 wins when prev was a read on the same path.
- H4 flash CSS: `GroupHeader.--group-appended { background: $accent 20%; transition: background 300ms in_out_cubic; }` in `hermes.tcss`. Class is added on collapsed→append, removed by `set_timer(0.6, ...)` callback.

### 2026-04-24 — Tool Pipeline Quick Wins QW-01..QW-12 — commits bea2d165d+4428dc274, 38+3 tests

**Changed APIs / constants:**
- `_DROP_ORDER` in `_header.py`: new ordering `[flash, remediation, stderrwarn, chip, linecount, duration, hero, diff, chevron, exit]` — exit survives last.
- `_DISCOVERY_GLOBAL_SHOWN: bool` in `_completion.py` **replaced** by `_DISCOVERY_SHOWN_CATEGORIES: set` — per-category hint gating. Re-exports in `__init__.py` updated to match. Tests that reset the old bool must now call `_comp_mod._DISCOVERY_SHOWN_CATEGORIES.clear()`.
- `_EMOJI_ICONS[ToolCategory.CODE]` changed from `"🐍"` to `"💻"`.
- `_CATEGORY_DEFAULTS[SEARCH].ascii_fallback` → `">"` (was `"?"`); `_CATEGORY_DEFAULTS[UNKNOWN].ascii_fallback` → `"·"` (was `"?"`).
- `_CollapsedActionStrip` TCSS rules added to `hermes.tcss`: `color: $text-muted 50%` unfocused, `85%` when `ToolPanel:focus`.
- `ToolTail` now adds/removes `--visible` CSS class in `update_count()` and `dismiss()` alongside the existing `display` property — needed for the Enter-dismiss intercept in `action_toggle_collapse`.

**Behaviour changes:**
- QW-01: shell-prompt `$` glyph deleted from `_render_v4`; `shell_prompt_w` stays 0.
- QW-02: exit chip renders whenever `_is_complete` (not only when collapsed).
- QW-03: `_refresh_collapsed_strip` no longer requires `has_focus`; `on_blur` calls `_refresh_collapsed_strip()` instead of removing `--visible`.
- QW-04: `c` binding removed from `ToolPanel.BINDINGS`; FILE collapsed strip: `("c","copy")` entry deleted.
- QW-06: `BodyFooter.render()` outputs `[y] copy` only — `[c]` and `open in $EDITOR` gone.
- QW-07: `_block.py` no longer sets `_header._hide_duration = True` for `read_file`/`search_files`.
- QW-10: `action_toggle_collapse` intercepts Enter when `tail.has_class("--visible")`, calls `tail.dismiss()`, returns early.
- QW-11: `separator_overhead = max(0, 2*(len(tail_segments)-1))` deducted from `tail_budget` before `_trim_tail_segments`; assembly loop inserts `" ·"` (style `"dim #666666"`) between segments.
- QW-12: `action_show_help` now adds all `ToolCategory` values to `_DISCOVERY_SHOWN_CATEGORIES` (was `_DISCOVERY_GLOBAL_SHOWN = True`).

**Test patterns:**
- `ToolTail.dismiss()` test: use `MagicMock(spec=[])` not `ToolTail.__new__()` — the latter lacks `styles` and fails on `self.display = False`.
- Discovery set reset fixture: `_comp_mod._DISCOVERY_SHOWN_CATEGORIES.clear()` in `autouse` fixture.
- StatusBar idle render: as of S1-E/A8, idle state is `Text("  ", style="dim")` — no `F1 help` in StatusBar; tests checking for it must assert the negative or check model name instead.

### 2026-04-25 — Tool Body Renderer Regression TBR-HIGH-01/02+MED-01/02+LOW-01 — commit c83bf1f5b, 19 tests

**Changed APIs / constants:**
- `ToolBlock.replace_body_widget(widget, *, plain_text="")` — new method. Removes `CopyableRichLog` + any `BodyFooter` from `self._body`, mounts new widget, mounts `BodyFooter` if `plain_text` is non-empty, stores `_rendered_plain_text`. Deferred import: `from hermes_cli.tui.body_renderers._grammar import BodyFooter` inside the method to avoid circular imports (body_renderers imports from tool_blocks).
- `ToolBlock._rendered_plain_text: str = ""` — new field. `ToolBlock.copy_content()` returns it when non-empty; falls back to `_plain_lines`.
- `StreamingToolBlock.replace_body_widget()` — override stops timers if `not self._completed` before calling `super()`. Regression guard only; `complete()` already stops them in normal flow. `copy_content()` also checks `_rendered_plain_text` first.
- `_completion.py._swap_renderer()` — no longer removes old_block from DOM. Calls `old_block.replace_body_widget(new_widget, plain_text=...)` when old_block has the method; falls back to direct mount + update refs if not. `plain_text = renderer.copy_text() if hasattr(renderer, "copy_text") else payload.output_raw`. Logger `_log` added at module level.
- `content_classifier._cached_classify()` — extended JSON detection: `data.web`, `data.news` → SEARCH with `source="web"/"news"`; `results[]` with url/title/content → SEARCH with `source="extract"`.
- `search._parse_search_json()` — restructured: `matches` path runs when `isinstance(matches, list)`; new `data_inner.web/news` path; new `results[]` path. Helpers `_parse_web_hit()` and `_parse_extract_hit()` extracted.
- `SearchRenderer.copy_text()` — returns normalized hits as `"\n".join(content)`, one per hit.

**Behaviour changes:**
- `_swap_renderer` old test (`test_swap_renderer_removes_old_block`) expected old block to be removed — replaced with `test_swap_renderer_keeps_original_block`. `test_pick_renderer_shell_always_shell` deleted (wrong contract); replaced by three `TestShellSelectionPolicy` tests in new file.
- `BodyFooter` no longer mounts as direct child of `BodyPane`; lives inside `ToolBlock._body`.

**Gotchas:**
- `BodyFooter` is in `body_renderers._grammar`; `ToolBlock` is in `tool_blocks._block`. Importing at module level creates a circular import. Always import deferred inside `replace_body_widget()`.
- `_parse_search_json` variable named `data` (outer dict) has inner key also named `"data"` (web/news). Use `data_inner = data.get("data")` to avoid confusion.
- `BrokenRenderer` in `test_swap_renderer_on_failure_keeps_old` must fail on `build_widget()`, not `__init__` — the new `_swap_renderer` doesn't catch instantiation errors (only `build_widget` and `replace_body_widget` are protected).
- `_maybe_swap_renderer` still has a blanket try/except that catches instantiation failures from the outer call path; `_swap_renderer` itself only protects the two explicitly documented failure points.

### 2026-04-25 — Mech Sweep E — Threading & Async Hardening (THR-1..THR-4) — 1b75abf98, 9 tests

**New APIs / changed behaviour:**
- `ToolsScreen._rebuild_task: asyncio.Task | None` and `ToolsScreen._filter_task: asyncio.Task | None` — stored handles for in-flight tasks; cancelled in `on_unmount`.
- `asyncio.ensure_future` is now GONE from `tools_overlay.py`. Three call sites replaced with `asyncio.create_task(..., name=...)`. Module-level `import asyncio` replaces three function-local imports.
- `MpvPoller.__init__` gains a required second positional arg `app: App`. All callbacks are dispatched via `app.call_from_thread` in the new `_poll_once()` method. Callers must NOT wrap callbacks in `call_from_thread` themselves (double-wrap would schedule `call_from_thread` from the loop thread, raising RuntimeError).
- `MpvPoller._poll_once() -> bool` extracted: one poll iteration, returns False to stop the loop. Makes the poller unit-testable without spinning a thread.

**Gotchas:**
- `asyncio.ensure_future` has weaker GC semantics than `create_task` — if nothing holds a reference to the returned Future, the task can be collected mid-flight when the overlay is dismissed. Always store the handle and cancel in `on_unmount`.
- `on_unmount` is sync in Textual 8.x — do NOT `await` the cancelled task there. Fire-and-forget; the loop reaps it.
- `App.call_from_thread` raises `RuntimeError` if the app is not running (shutdown race) OR if called from the event-loop thread itself. The `_poll_once` `except RuntimeError` block must log at DEBUG (expected shutdown path) and return False (stop loop). Never re-raise in this branch.
- The `widgets/media.py` caller was previously double-wrapping: `on_tick=lambda pos, dur: app.call_from_thread(self._on_tick, pos, dur)`. After THR-2, passing bare `self._on_tick`/`self._on_end` is required. Double-wrap causes `call_from_thread(call_from_thread(fn))` → the inner `call_from_thread` runs on the loop thread and raises `RuntimeError`.
- Existing `test_inline_media.py` thread-based tests used `time.sleep` + side-effects via callback. After migration, use `app.call_from_thread = MagicMock(side_effect=lambda fn, *a: fn(*a))` — identity dispatch keeps the sleep pattern working without further changes.

### 2026-04-25 — R3-AFFORDANCE Kind Override (KO-1..KO-5) — branch feat/textual-migration, 17 new tests + 11 migrated

**New APIs:**
- `ToolCallViewState.user_kind_override: ResultKind | None = None` — single source of truth for the user KIND override (replaces the panel-local `_forced_renderer_kind` slot that has been deleted from `ToolPanel.__init__`).
- `pick_renderer(..., user_kind_override: ResultKind | None = None)` — new kwarg. When set and phase is post-streaming, synthesizes a high-confidence `ClassificationResult` and bypasses Rules 1–2 (SHELL / EMPTY short-circuits). TEXT/EMPTY override short-circuits to `FallbackRenderer`. Walk skips both `FallbackRenderer` and `ShellOutputRenderer` (their `can_render` is unconditionally True; without filtering they'd silently catch the override).
- `ToolPanel.action_cycle_kind` — new keyboard action bound to `t`. Cycles `view.user_kind_override` through `(None, CODE, JSON, DIFF, TABLE, LOG, SEARCH, TEXT)`. No-op when `view.state` not in `{COMPLETING, DONE, ERROR, CANCELLED}`. Delegates to `force_renderer` for the swap.
- `ToolPanel.force_renderer(kind: ResultKind | None)` — kind is now `Optional`; passing None clears the override. Reads `view.kind` (stamped classifier verdict) for the cls_result fallback when kind is None. Active entry-point: replays the swap unconditionally (no Fallback short-circuit, unlike `_maybe_swap_renderer`).
- `_maybe_swap_renderer` — restructured. Reads `self._view_state or self._lookup_view_state()` first, derives `override = view.user_kind_override if view else None`, gates the TEXT/EMPTY/SHELL early-returns on `override is None`. Passes `user_kind_override=override` to `pick_renderer`. Fallback short-circuit `if override is None and renderer_cls is FallbackRenderer: return` only fires for the no-override path (so override→Fallback/TEXT swaps are observable).

**Gotchas:**
- `_forced_renderer_kind` panel slot is GONE. Tests asserting on `panel._forced_renderer_kind == X` must migrate to `panel._view_state.user_kind_override == X` AND attach a stub view-state (helper `_attach_view_stub` returning a `SimpleNamespace(state=…, kind=None, density=DEFAULT, user_kind_override=None)`) before calling `force_renderer`.
- Stub mixins for completion/actions tests now require `_view_state = None` class attr — `_maybe_swap_renderer` and `force_renderer` both read `self._view_state or self._lookup_view_state()`, AttributeError without the slot.
- `_fake_pick` patch lambdas in tests must accept the `user_kind_override=None` kwarg or pick_renderer side-effect raises TypeError; widening was applied to all 7 `_fake_pick` + 2 `_boom` lambdas in `tests/tui/test_renderer_registry_context.py`.
- `pick_renderer`'s override walk skips `ShellOutputRenderer` AND `FallbackRenderer`. Both `can_render` always return True (`ShellOutputRenderer` for SHELL category, `FallbackRenderer` unconditionally) — without filtering, an override of CODE on a SHELL block would still resolve to `ShellOutputRenderer`.
- The cycle excludes `EMPTY` and `BINARY`. EMPTY would render an empty-state placeholder over real output; BINARY currently has no specialized renderer. The defensive `idx = ValueError` branch snaps to None when the override was set out-of-cycle via direct API.
- `action_cycle_kind` gate is `_RENDERABLE = {COMPLETING, DONE, ERROR, CANCELLED}`, NOT `not in _STREAMING_PHASES`. GENERATED has no body to swap; REMOVED is mid-recycle. Both are silent no-ops.
- Hint strip `_build_hint_text` adds `("t", "render as")` at front of `contextual` (insert(0, …)) when `not _block_streaming and not rs.is_error`. Survives the `contextual[:2]` truncation, but on narrow panels (<50 cols) the contextual slice is empty so the hint is hidden.

### 2026-04-25 — Mech Sweep C — Performance Micro-Fixes (PERF-1..PERF-4) — 0744d6c56, 7 tests

**Changed behaviour:**
- `VirtualCompletionList.__init__`: 4 new cached Style fields: `_style_text_normal`, `_style_text_selected`, `_style_path_suffix`, `_style_empty`. `_refresh_fuzzy_color()` now also refreshes `_style_empty` (from `completion-empty-bg`) and `_style_path_suffix` (from `path-suffix-color`). Call sites in `render_line` and `_styled_candidate` use cached objects instead of constructing `Style()` per-render.
- `ToolsScreen.on_unmount`: `_stale_timer = None` after `.stop()` — symmetric with `_refresh_timer`.
- `WatchersService.__init__`: new `_last_compact_value: bool | None = None` field. `on_compact` guards with `if self._last_compact_value == value: return` before updating cache — deduplicates repeated same-value calls.
- `StreamingToolBlock.__init__`: new `_is_unmounted: bool = False` and `_render_timer: Timer | None = None` fields. `on_unmount` sets `_is_unmounted = True` first. Both flush-slow timer reassignment sites (in `append_line` and `_flush_pending`) now null the timer before reassigning and skip `set_interval` when `_is_unmounted`.

**Gotchas:**
- `Candidate` dataclass has only `display` + `match_spans` fields. `PathCandidate` adds `insert_text` + `abs_path`. The `path` kwarg does not exist — test constructors must use `abs_path`.
- `ToolsScreen.on_unmount` calls `_render_timer.stop()` (existing try block) AND the PERF-4 guard in `_flush_pending` also calls it. When testing the flush-slow path after `on_unmount`, reset the mock call count with `.reset_mock()` before calling `_flush_pending` to isolate each call site.
- `WatchersService.on_compact` wraps `query_one` in `except NoMatches` — tests must raise the real `textual.css.query.NoMatches`, not a plain `Exception("NoMatches")`, or the except clause won't catch it and the test will propagate the error.
- Spec D "merges first" branch applies: `_style_path_suffix` initialized to `Style(dim=True)` (no color literal); `_refresh_fuzzy_color` resolves `path-suffix-color` css var to populate it.

### 2026-04-25 — Mech Sweep D — CSS/Skin Hardening (CSS-1..CSS-8) — branch feat/textual-migration, 14 tests

**Changed behaviour:**
- `COMPONENT_VAR_DEFAULTS["overlay-selection-bg"]` added (value `"#333399"`). `tools_overlay.render_tool_row` gains optional `app=None` kwarg — reads this var from `get_css_variables()` for cursor row selection background.
- `COMPONENT_VAR_DEFAULTS["tool-header-max-gap"]` changed from plain `"8"` string to `VarSpec(default="8", optional_in_skin=True, ...)`. Consumers of `_default_of(...)` are unaffected; consumers iterating over raw COMPONENT_VAR_DEFAULTS must route through `_default_of`.
- `hermes.tcss`: added `$tool-mcp-accent: #9b59b6` declaration; ToolPanel.category-mcp rule now references `$tool-mcp-accent` instead of hardcoded hex. Added Textual built-in vars doc comment block (sentinel: "Textual built-in CSS variables used"). TCSS `$diff-add-bg`/`$diff-del-bg` corrected to `#1a3a1a`/`#3a1a1a` (were `#0e2a16`/`#2a0e0e`).
- `SkinColors.default()` `diff_add_bg`/`diff_del_bg` aligned to match `COMPONENT_VAR_DEFAULTS` (`#1a3a1a`/`#3a1a1a`).
- `completion_list._styled_candidate`: path suffix reads `text-muted` via `self.app.get_css_variables()` (silent fallback to `#888888`).
- `tool_panel/_actions.py` HTML export: `get("base", ...)` → `css.get("app-bg") or css.get("background") or "#1e1e2e"`.
- All 4 bundled DESIGN.md skins (`catppuccin`, `matrix`, `solarized-dark`, `tokyo-night`) gained `overlay-selection-bg` in their `x-hermes.component-vars` block.

**Gotchas:**
- DESIGN.md skin YAML frontmatter: `component-vars` is nested under `x-hermes`, not at top level. `fm.get("component-vars")` returns None; correct path is `fm["x-hermes"]["component-vars"]`.
- `VirtualCompletionList.app` is a Textual `@property` that walks the DOM tree — cannot be patched via `instance.__dict__["app"] = mock`. Use `patch.object(type(widget), "app", new_callable=PropertyMock, return_value=mock_app)`.
- `VarSpec.optional_in_skin=True` suppresses the missing-key `UserWarning` from `validate_skin_dict`. The `required` set in that function filters out VarSpec instances where `optional_in_skin` is True, so skins need not declare non-colour layout knobs.
- `tools_overlay.render_tool_row` is a module-level function, not a method. Testing the `app` kwarg requires passing a mock directly — no Textual pilot needed.

### 2026-04-26 — Tool Call Discoverability DC-1/DC-3/DC-4 — commit 025df994b, 22 tests

**DC-4: `KNOWN_PREFIXES` single source**
- `KNOWN_PREFIXES: tuple[str, ...] = ("file:", "shell:", "error:")` exported from `tools_overlay.py` at module level. The `_apply_filter` `for prefix in ...` loop now reads `KNOWN_PREFIXES`; placeholder text is `f"filter… (prefix: {' '.join(KNOWN_PREFIXES)})"`. Any test that monkey-patches `KNOWN_PREFIXES` must patch `hermes_cli.tui.tools_overlay.KNOWN_PREFIXES`.

**DC-3: Filter prefix legend strip**
- `ToolsScreen` composes a `#prefix-legend` Static below `#filter-row`. Auto-hide logic lives in `_update_legend_visibility(filter_value: str)` called from `on_input_changed`. Key state: `self._prefix_used: bool` (per-open-instance; resets on clear) + `self._disc_state: DiscoverabilityState` (loaded from disk on `__init__`). Deferred write: `action_dismiss_overlay` calls `save_discoverability_state` only when `_prefix_used and not tools_filter_first_use`. "Successful filter" definition: KNOWN_PREFIXES prefix present + non-whitespace remainder + `self._filtered` non-empty.
- `DiscoverabilityState` lives in `hermes_cli/tui/services/session_state.py`. Load/save helpers use `~/.hermes/.tui_session_state.json` (HERMES_HOME env-respected). Missing/corrupt file returns `DiscoverabilityState()` defaults silently.
- CSS class `--hidden` on `#prefix-legend` uses `display: none` rule in `ToolsScreen.DEFAULT_CSS`.

**DC-1: ToolPanel hint row — three static hint sets**
- `DEFAULT_HINTS`, `ERROR_HINTS`, `COLLAPSED_HINTS` module-level tuples in `_actions.py`. `[f1] all` is always the last item and is never dropped by `_format`.
- `_format(hints)` joins with `" · "`, then truncates by popping from `body = list(hints[:-1])` right-to-left until `" · ".join(body + ["…", tail])` fits; falls back to `tail[:w]`.
- `_available_width()` reads `self.content_region.width` (Textual content area, excludes border/padding).
- `_is_error()`: `rs = self._result_summary_v4; return rs is not None and rs.exit_code not in (None, 0)`.
- `_select_hint_set()`: collapsed → `COLLAPSED_HINTS`; error → `ERROR_HINTS`; else → `DEFAULT_HINTS`.
- `_refresh_hint_row()`: single method called by both `watch_has_focus` and can be called externally. Shows hint when `self.has_focus or self.has_class("--has-affordances")`.
- `--has-affordances` CSS class on ToolPanel makes hint always-visible (accessibility/keyboard-only mode); set externally, orthogonal to focus state.

**Testing mixin methods without DOM/pilot — `_FakePanel` class pattern**
- `SimpleNamespace` cannot hold `@property` descriptors (raises `TypeError: cannot set attribute of immutable type`). Use a real class instead: `class _FakePanel: content_region = property(lambda self: ...); _available_width = _ToolPanelActionsMixin._available_width; ...`. Bind all needed mixin methods as class-level attributes directly — Python's descriptor protocol handles `__get__` for unbound methods automatically when accessed on instances.
- `_FakePanel._available_width = _ToolPanelActionsMixin._available_width` (no `__get__` call needed at class body level) means `fake_panel._available_width()` invokes the real mixin method with `fake_panel` as `self`.

### 2026-04-26 — Header/Affordance Widths HW-1..HW-6 — commit 3dc0396e7, 20 tests

**HW-1: Drop order re-prioritised in `layout_resolver.py`**
- All three tier lists updated: `_DROP_ORDER_DEFAULT`, `_DROP_ORDER_HERO`, `_DROP_ORDER_COMPACT`. Recovery affordances (`stderrwarn`, `remediation`) now drop last (before exit only); cosmetics (`chip`, `linecount`, `duration`) drop first.
- `_header.py` re-exports `_DROP_ORDER = _DROP_ORDER_DEFAULT` as legacy alias — do not edit drop orders in `_header.py`; edit `layout_resolver.py`.
- Hero demotion invariant (`names <= {"hero", "flash"}` → drop hero first) runs BEFORE the drop-order loop; tests for `{hero, flash}` edge case must account for this.

**HW-2: Gap clamp removed — `_resolve_max_header_gap` deleted**
- `_header.py:~458`: `pad = max(0, available - label_used)` replaces clamped variant.
- `MAX_HEADER_GAP_CELLS_FALLBACK` and `_resolve_max_header_gap` deleted. `tool-header-max-gap` skin var is now a no-op.

**HW-3: `_get_collapsed_actions` cache removed**
- `_COLLAPSED_ACTIONS` global gone; `_get_collapsed_actions` builds per-call via `_build_collapsed_actions_map()` inside a try/except that logs. `_log` added to `_footer.py`.
- Tests that verify no-caching must patch `_build_collapsed_actions_map` to return different dicts on successive calls (there is no external registration surface to test).

**HW-4: Compact footer swaps row visibility**
- Old: `FooterPane.compact > .footer-stderr { display: none; }` — now removed.
- New: `FooterPane.compact > .artifact-row { display: none; }` + `max-height: 1; overflow: hidden` on `.footer-stderr`.
- `_render_stderr` adds `" (e for full)"` suffix and clamps to last line when `self.has_class("compact")`. Empty-tail guard: `if not lines: return result` before the compact branch.

**HW-5: Separator dim-modifier removed**
- Both call sites in `_header.py` (lines ~337 and ~410): `style=f"dim {self._colors().separator_dim}"` → `style=self._colors().separator_dim`.
- Default raised `#444444` → `#555555` in `SkinColors.default()`.
- `dim` SGR + explicit dark hex = near-invisible on dark terminals; drop `dim`, use a lighter base instead.

**Testing gotcha — `getattr(widget, "app", None)` does not work**
- Textual `.app` is a property that raises `NoActiveAppError` (not `AttributeError`) when no active app. `getattr(widget, "app", None)` propagates the exception.
- Correct pattern: `patch.object(type(widget), "app", new_callable=PropertyMock, return_value=None)` → `from_app(None)` → `SkinColors.default()`.

### 2026-04-26 — Timer/Pacer Lifecycle H8..L10 — commit aff893f49, 27 tests

**H8: CharacterPacer — deadline-based emission**
- Removed `_chars_per_tick` (fixed batch size). Added `_next_emit_at: float` deadline.
- `feed()` sets `_next_emit_at = clock()` when starting timer so first char emits immediately.
- `_tick()`: `if now < _next_emit_at: return` (too early). Burst guard: if `now - _next_emit_at > 2*interval`, reset `_next_emit_at = now` to avoid thundering herd. Emit `chars_due = max(1, int(elapsed/interval)+1)` chars.
- Injectable `clock=` kwarg (default `time.monotonic`) for deterministic tests.

**H9: Pre-mount chunk buffering in WriteFileBlock + ExecuteCodeBlock**
- `_pre_mount_chunks: list[str] = []` added to `__init__`.
- `feed_delta`: if `_extractor is None or _pacer is None`, buffer raw delta in `_pre_mount_chunks` instead of silently dropping.
- `on_mount`: after creating pacer, drains `_pre_mount_chunks` through extractor → pacer then clears.

**H10: ThinkingWidget — shared lock across _LabelLine redraws**
- `_effects_lock: threading.Lock | None = None` class attribute.
- `activate()`: allocates lock once (`if self._effects_lock is None`), passes same instance to all `_LabelLine` creations (STARTED flash + deterministic path).
- STARTED→WORKING swap in `_tick()` already reused `self._label_line._lock` — now that IS `_effects_lock`.

**M7: ManagedTimerMixin — new file `hermes_cli/tui/managed_timer_mixin.py`**
- `_register_timer(timer)` → appends `{"timer": t, "stopped": False}` entry, returns timer.
- `_register_pacer(pacer)` → same for pacers.
- `_stop_all_managed()` → stops all unstopped entries, marks `stopped=True`, clears both lists.
- `on_unmount()` → calls `_stop_all_managed()` then chains to `super().on_unmount()` safely.
- Adopted by: `StreamingToolBlock` (MRO leader — WriteFileBlock/ExecuteCodeBlock inherit through it), `ThinkingWidget`, `LiveLineWidget`.
- **MRO gotcha**: don't add `ManagedTimerMixin` to BOTH `StreamingToolBlock` AND its subclasses — Python C3 MRO rejects the inconsistency with `TypeError: Cannot create consistent MRO`.

**M8: ThinkingWidget.activate — stop prior timer before registering new one**
- Old guard: `if self._timer is not None: return`. New: `self._stop_all_managed(); self._timer = None`.
- Double-activate no longer orphans the prior timer.
- Timer registered via `_register_timer(self.set_interval(...))` so mixin tracks it.

**L4: StreamingToolBlock.complete + replace_body_widget — no double-stop**
- `complete()` calls `self._stop_all_managed()` instead of `try: render_timer.stop(); spinner_timer.stop(); ...`.
- `replace_body_widget()` same.
- Mixin marks entries `stopped=True` → subsequent `on_unmount → _stop_all_managed()` skips them.
- Rate-switching code paths that call `_render_timer.stop()` then re-create via `set_interval` must also use `_register_timer(...)` for the new handle.

**L9: ThinkingWidget.deactivate — synchronous timer stop before fade**
- `deactivate()` now calls `self._stop_all_managed()` as first line, stopping animation timer immediately.
- Visual 150ms CSS fade still scheduled via `set_timer(0.15, _do_hide)` as before.
- flush_live can call `tw.deactivate()` (sync) and immediately proceed to `live.flush()` with no animation-tick race.

**L10: ExecuteCodeBlock.reveal_lines — is_mounted guard**
- First line: `if not self.is_mounted: _log.debug("reveal_lines on unmounted block; dropping %d lines", end - start); return`.
- Test uses `patch.object(type(block), "is_mounted", new_callable=PropertyMock)` — `.app` property gotcha applies here too.

### 2026-04-26 — Spec E Buffer Caps + Perf (M1/M4/M9/M10) — commit 7f8b5f7ed, 12 tests

**M1: Buffer caps in response_flow.py**
- Four module-level constants: `_MAX_FOOTNOTES=500`, `_MAX_CITATIONS=500`, `_MAX_MATH_LINES=10_000`, `_MAX_CODE_FENCE_BUFFER=500`.
- Footnote guard: only on the `label not in self._footnote_defs` branch (line 668 area) — continuation lines that extend an existing entry are still allowed.
- Citation guard: only on new entries (`_n not in self._cite_entries`).
- Math overflow: set `self._state = "NORMAL"`, `self._math_lines.clear()`, return — called from `_dispatch_non_normal_state` (NOT `_dispatch_state_machine` which doesn't exist).
- Code fence: guard in `_commit_prose_line` before `.append()`; regex is `r"^\s*\d{1,3}\s*\|\s+\S"` — test lines must use pipe format like `"  1 | code"`.

**M4: ReasoningPanel.append_delta reflow**
- Changed `self.refresh(layout=True)` (line 213) to conditional: only when `self._reasoning_log._deferred_renders` is non-empty; otherwise `self.refresh()`.
- `add_class("visible")` at line 196 requires `_classes` Textual attr → must mock `panel.add_class = MagicMock()` in tests; `ReasoningPanel.__new__` alone is insufficient.

**M9: CopyableRichLog._render_width caching**
- New field `_render_width: int | None = None` in `__init__`.
- `on_resize(event: events.Resize)` is authoritative: `self._render_width = event.size.width`. Requires `from textual import events` import.
- `on_mount` + `_capture_width` for best-effort pre-warm only.
- `write()` adds `*, _deferred: bool = False` kwarg. Pre-layout path (all widths 0 + no `_render_width`): defers once via `call_after_refresh(lambda c=content: self.write(c, _deferred=True))`, returns `self`.
- `scrollable_content_region` and `size` are Textual read-only properties → must use `PropertyMock` in tests: `patch.object(type(log), "scrollable_content_region", new_callable=PropertyMock, return_value=Region(0,0,0,0))`.
- `events.Resize.__init__` takes `(size, virtual_size, container_size=None, pixel_size=None)` — all `Size` objects.

**M10: StreamingSearchRenderer.finalize**
- One line added: `self._last_emitted_path = None` at start of `finalize`. Signature: `finalize(self, all_plain: list[str], **kwargs)`.

---

## Changelog 2026-04-26 — Spec F streaming polish (L1/L2/L3/L5/L6/L7/L11)

**L1: Diff regex single-source**
- `_DIFF_HEADER_RE` and `_DIFF_ARROW_RE` now live only in `tool_blocks/_shared.py`
- `body_renderers/streaming.py` imports them: `from hermes_cli.tui.tool_blocks._shared import _DIFF_ARROW_RE, _DIFF_HEADER_RE`
- No circular import risk (checked: `_shared` → `widgets` → no `body_renderers.streaming`)

**L2: LiveLineWidget._blink_visible reset**
- `self._blink_visible = True` moved to the very first line of `on_mount` (before typewriter setup)
- Prevents stale False value on remount when flush() never fired (response completed before first chunk)

**L3: Orphaned CSI strip with debug log**
- `render()` now uses `_ORPHANED_CSI_RE.subn(...)` + `_log.debug("stripped %d orphaned CSI sequences...")` when n > 0
- `logger` renamed to `_log` in `renderers.py` (matches project convention)

**L5: FileRenderer.render_stream_line fallback**
- `except Exception` now calls `_log.debug("syntax render failed for lang=%s line=%r", ..., exc_info=True)` and returns `Text(plain, style="dim")` instead of bare `Text(plain)`
- `body_renderers/streaming.py` now has `import logging; _log = logging.getLogger(__name__)` at top

**L6: ResponseFlowEngine threading docstring**
- Single-consumer contract documented in class docstring

**L7: response_flow.py logger**
- `logger` renamed to `_log` throughout (16 call sites)
- `_log = logging.getLogger(__name__)` moved to immediately after TYPE_CHECKING block (before first FunctionDef at ~line 128)

**Testing gotcha: HermesApp CSS VarSpec crash**
- `HermesApp` fails `run_test()` with `'VarSpec' object has no attribute 'splitlines'` — pre-existing bug in hermes.tcss stylesheet parsing
- Workaround: use minimal `class _LiveApp(App)` that composes only the widget under test
- The `_tw_patch()` helper (from `test_typewriter.py`) works with minimal apps too

---

## Changelog 2026-04-26 — SNS1 $skill invocation namespace (Phase 1)

**New files / packages:**
- `hermes_cli/tui/types/__init__.py` + `types/skill_candidate.py` — `SkillCandidate` frozen dataclass; `from_skill_info()` classmethod; `_classify_source()` maps skill path to "hermes"/"claude"/"plugin"/"user"; `_parse_trigger_phrases()` / `_parse_negative_phrases()` extract body-prose list items
- `hermes_cli/tui/overlays/skill_picker.py` — `SkillPickerOverlay` two-pane modal (left: filterable OptionList, right: detail); triggered via `_open_skill_picker(seed_filter, trigger_source)`

**New APIs:**
- `agent/skill_commands.py::normalize_skill_invocation(typed)` — strips leading `$` or `/`, returns `/name` key for lookup; `None` for empty/invalid input
- `hermes_cli/tui/_app_constants.py::KNOWN_SKILLS: set[str]` — runtime-populated bare names (no `$`/`/`); `refresh_known_skills(names)` clears+replaces
- `hermes_cli/tui/completion_context.py::CompletionContext.SKILL_INVOKE = 7` — prevents inline completion overlay for `$fragment` input
- `hermes_cli/tui/completion_context.py::_SKILL_RE` — `re.compile(r"^\$([\w-]*)$")`; exported for auto-dismiss logic in `_autocomplete.py`
- `hermes_cli/tui/services/theme.py::ThemeService.populate_skills()` — scans skill_commands, builds `SkillCandidate` list, calls `refresh_known_skills()`, pushes to `HermesInput._skills`
- `hermes_cli/tui/app.py::_open_skill_picker(seed_filter, trigger_source)` — idempotent: queries existing `SkillPickerOverlay` and calls `set_filter()`, or mounts a new one
- `hermes_cli/tui/app.py::_populate_skills()` — thin forwarder to `_svc_theme.populate_skills()`

**Behavior changes:**
- `$name` in CLI input routes through `$`-branch in `cli.py` → `normalize_skill_invocation` → `/name` skill lookup (non-rekey: internal dict stays `/`-keyed)
- `$fragment` typed in TUI input → `CompletionContext.SKILL_INVOKE` → `_open_skill_picker` (picker is the completion surface; inline overlay suppressed)
- `Alt+$` chord in TUI → `_open_skill_picker(seed_filter="", trigger_source="chord")`; suppressed in `InputMode.BASH`
- Prefix-triggered picker (`trigger_source="prefix"`) auto-dismisses when `_SKILL_RE` no longer matches the input value
- Unknown `$name` submission in TUI → flash hint "Unknown skill: $name  (Alt+$ for picker)" and return without dispatch
- `/skills` listing legend is phase-gated: phase<2 → "Invoke with $name (or /name in CLI/gateway mode)"; phase>=2 → "$name to invoke (Alt+$ for picker)"
- **SNS2 (2026-04-26)**: `display.skill_namespace_phase` config key (default 2); `_deprecated_slash_warned: set[str]` in `cli.py` throttles /skill-name warning to once per session; `show_help()` splits "Slash commands"/"Skills" sections at phase>=2; `extra` param removed from `ThemeService.refresh_slash_commands`; phase=3 stub rejects /skill-name (replaced by SNS3)
- **SNS3 (2026-04-26)**: hard cutover — `_deprecated_slash_warned` state removed from `cli.py`; slash-skill dispatch branch replaced with unconditional rejection `"/{name} no longer invokes skills — use ${name} (Alt+$ for picker)"`; `_sns_phase` flag reads removed from `show_help()` (unconditionally renders `$name to invoke (Alt+$ for picker)`); `_app_constants._KNOWN_SLASH_BARE` frozenset added + disjointness assertion in `refresh_known_skills`; README.md Browse-skills row updated to `$<skill-name>`; Phase-2 forward-compat stub deleted from `test_skill_namespace_phase2.py`

**Gotchas:**
- `Alt+$` key encoding is terminal-dependent: may arrive as `alt+4`, `alt+dollar_sign`, or `alt+$`. Use `event.character == "$" and key.startswith("alt+")` for reliable detection.
- `SkillPickerOverlay._trigger` ("prefix"/"chord") controls auto-dismiss: prefix-triggered calls `dismiss()` when `_SKILL_RE` misses on input change; chord-triggered requires explicit Esc/Enter/Tab.
- `ThemeService.populate_skills()` guards `NoMatches` on `HermesInput` query with `_log.debug(...)` — intentional swallow for headless/gateway mode where no HermesInput mounts.
- `SkillCandidate` is a **frozen** dataclass — do not attempt `candidate.name = ...` in tests; construct via `SkillCandidate(name=..., ...)` directly or via `from_skill_info()`.
- `_classify_source()` checks path fragments: "claude-code" → "claude", "plugins/" or ".claude/plugins" → "plugin", ".claude/skills" → "user", else → "hermes". Order matters; check for "claude-code" before ".claude".
- Fuzzy `$`-typo suggestions in `cli.py` use `typed[1:][:3]` prefix (3 chars) — not 4. Using 4 caused `"reve"` to miss `"review"` (starts with `"revi"`).

**Test patterns:**
- `SkillCandidate` tests: construct directly, no app needed; 7 unit tests cover `from_skill_info`, `_classify_source`, trigger phrase parsing.
- Picker tests: use minimal `class _TestApp(App)` with `compose` yielding only `SkillPickerOverlay`; inject `_skills` list into the overlay's `_candidates` directly after mount (bypass `_load_candidates` which queries `HermesInput`).
- `KNOWN_SKILLS` tests: test `_app_constants` submodule directly (not via `__init__` re-export) to avoid mutable-global copy issue.
- `CompletionContext.SKILL_INVOKE` tests: call `detect_context()` with `bash_mode=False` for the `$` branch; `bash_mode=True` must suppress it.

## Changelog 2026-04-26 — Hint Pipeline Unification H-1..H-4 — 15 tests

**Spec:** `/home/xush/.hermes/2026-04-26-tcs-hint-pipeline-spec.md`
**Files changed:** `hermes_cli/tui/tool_panel/_actions.py`, `hermes_cli/tui/tool_panel/_core.py`
**Test file:** `tests/tui/test_tool_panel_hint_pipeline.py`

**New APIs/methods:**
- `_ToolPanelActionsMixin._collect_hints()` → `tuple[list[tuple[str,str]], list[tuple[str,str]]]` — computes (primary, contextual) hint pairs from panel state; 4 primary variants (streaming/collapsed/error/ok); contextual is capability-gated (+/*/e/o/u/E/t/I/alt+t/D)
- `_ToolPanelActionsMixin._render_hints(primary, contextual, width)` → `Text` — renders four-bucket hint row: primary · contextual · +N more · F1 help [rotating tip]; F1 always pinned via budget reservation
- `_ToolPanelActionsMixin._truncate_hints(chips, budget)` → `tuple[Text, int, list[str]]` — greedy left-to-right fit; returns (rendered, dropped_count, dropped_keys_in_order); uses `rich.cells.cell_len`. **HRP-1 (2026-04-27)** changed signature from 2-tuple to 3-tuple; the dropped-key list is consumed by `_append_overflow_marker`.
- `_ToolPanelActionsMixin._append_overflow_marker(t, n_dropped, dropped_keys, width, f1_reserve)` — renders `+y/r/e` when keys form fits, falls back to `+N more`, suppresses if neither fits. Caps shown keys at 4 with trailing `/…`.
- `_ToolPanelActionsMixin._build_hint_text()` — **2026-04-27**: budget-driven inline (no `_collect_hints`/`_render_hints` orchestrator on `feat/textual-migration`); the `narrow < 50` cliff is gone. Cap remains `primary[:2] + contextual[:2]` but cell budget drives final visibility. F1 is always appended when `_power_keys_exist` and reserves 4 cells in the budget.
- `_ToolPanelActionsMixin.action_density_cycle()` — cycles DEFAULT→COMPACT→HERO→DEFAULT; rejects HERO with `tone="warning"` flash
- `ToolPanel` BINDINGS: added `Binding("D", "density_cycle", ...)`

**Deleted:**
- `DEFAULT_HINTS`, `ERROR_HINTS`, `COLLAPSED_HINTS` module-level constants
- `_format(hints)`, `_select_hint_set()`, `_available_width()` — all now dead

**Behavior changes:**
- Error primary: was `("x","dismiss")`; now `("r","retry")` — retry is the primary recovery action
- Streaming primary: now `[("Enter","follow"),("f","tail")]`; previously `("Enter","follow")` only
- Hint row always shows `F1 help` at end, even on narrow widths; old code could drop it
- `+N more` count replaces silent `…` for dropped contextual hints

**Gotchas:**
- `_next_tier_in_cycle` is a `@staticmethod` — bind it explicitly in tests: `panel._next_tier_in_cycle = _ToolPanelActionsMixin._next_tier_in_cycle`
- `_collect_hints` dedup guard for `("r","retry")` checks `not in primary` (not footer); prevents double-render in error state where primary already has retry
- Budget formula: `width - primary_t.cell_len - f1_t.cell_len - 2 * sep_w - _HINT_ROW_MARGIN(4)` — F1 is reserved before contextual gets any budget; on very narrow widths budget=0 and all contextual is dropped/counted
- `_truncate_hints` is a greedy break (stops on first chip that exceeds budget), NOT a knapsack — it does NOT skip a wide chip and try a narrower one

**Test patterns:**
- Use `types.SimpleNamespace` + `_ToolPanelActionsMixin.method.__get__(panel)` to bind methods without full ToolPanel
- `_collect_hints` needs: `_result_summary_v4`, `_block` (with `._completed`), `collapsed`, `_is_error()`, `_visible_footer_action_kinds()`, `_get_omission_bar()`, `_result_paths_for_action()`
- `_render_hints` / `_build_hint_text` additionally needs: `is_mounted`, `size.width`
- H-4 action tests: need `_resolver.tier`, `_resolver.resolve(inputs)`, `_user_collapse_override`, `_user_override_tier`, `_auto_collapsed`, `_view_state`, `_lookup_view_state()`, `_is_error()`, `_body_line_count()`, `_parent_clamp_tier`, `_flash_header()`

---

## Changelog — 2026-04-26 — Tool Error Recovery Contract (ER-1..ER-5)

**New APIs/methods:**
- `ToolBodyContainer.set_stderr_tail(tail: str | None) -> None` — shows/hides `.--stderr-tail` Static widget; renders last 8 lines of tail with `SkinColors.error` style; hidden when `tail` is None or empty
- `FooterPane._RECOVERY_KINDS: tuple[str, ...]` — `("retry", "copy_err")` module-level constant for sort priority
- `FooterPane._RECOVERY_ORDER: dict[str, int]` — index-map for sort key in `_rebuild_action_buttons`

**Deleted:**
- `ToolHeader` stderrwarn tail segment (was: `("stderrwarn", Text("  ⚠ stderr (e)", ...)`)
- `ToolHeader` remediation tail segment (was: `("remediation", Text(f"  hint:{_rh}", ...)`)
- `FooterPane._render_stderr()` method entirely
- `FooterPane._stderr_row`, `_remediation_row` Static widgets from compose
- `_ToolPanelCompletionMixin` remediation hint storage block (was writing `_hdr._remediation_hint`)
- `_DROP_ORDER_DEFAULT/HERO/COMPACT`: removed `"stderrwarn"` and `"remediation"` entries (10 → 8 entries each)

**Behavior changes:**
- Header only shows category-level info (chip, linecount, duration, flash, diff, chevron, hero, exit)
- Stderr evidence shown in body via `ToolBodyContainer.set_stderr_tail()` wired from `_ToolPanelCompletionMixin`
- Recovery actions (retry, copy_err) sorted first in footer action row via `_RECOVERY_ORDER`
- Recovery action chips get CSS class `--recovery-action` → accent color + bold

**Gotchas:**
- `set_stderr_tail` catches `NoActiveAppError` (not `AttributeError`) when widget has no active app: use `try/except Exception: _app = None`; `getattr(self, "app", None)` does NOT work for Textual app descriptors
- `SkinColors.from_app` must be patched at source `hermes_cli.tui.body_renderers._grammar.SkinColors.from_app` not at import site; the method is called via local import inside `set_stderr_tail`
- `_RECOVERY_KINDS`/`_RECOVERY_ORDER` must be defined BEFORE `class FooterPane` in `_footer.py` — module-level constants used in method body; putting them after class causes `NameError` at call time
- Meta-tests (ER-5) use `subprocess.run(["grep", ...])` to verify no `stderrwarn` in `hermes_cli/`; any comment containing the word will trip these tests

**Test patterns:**
- `TestStderrInBody`: instantiate `ToolBodyContainer.__new__`, set `_classes=set()`, mount `.--stderr-tail` Static manually, call `set_stderr_tail()`; no Textual runtime needed for pure attribute tests
- Header absence tests: use `inspect.getsource(ToolCallHeader._render_v4)` and assert string not in source; avoids needing to mock Textual `app` property descriptor
- Drop-order meta-tests: assert `"stderrwarn" not in _DROP_ORDER` and `"remediation" not in _DROP_ORDER`; length is now 8 not 10

### 2026-04-26 — TCS Mode Legibility ML-1..ML-5 — 18 tests, commit `345f0e983`, branch `feat/textual-migration`

**ML-1: `kind` segment in header tail**
- `tail_segments.append(("kind", Text(f"  as {kind_label}", style=f"dim italic {colors.accent}")))` added in `_header.py` after duration append, before the tail-budget trim.
- Reads `view.user_kind_override` from `panel._view_state`; absent/None → segment not appended.
- `"kind"` added to `_DROP_ORDER_DEFAULT/HERO/COMPACT` in `layout_resolver.py`. Position: after `"duration"`, before `"flash"` in DEFAULT/HERO; after `"flash"`, before `"diff"` in COMPACT.

**ML-2: `T → kind_revert` on ToolPanel**
- `Binding("T", "kind_revert", "Revert kind", show=False)` added to `_core.py` BINDINGS after `"t"`.
- `action_kind_revert()` in `_actions.py`: sets `view.user_kind_override = None`, calls `force_renderer(None)`, flashes `"render as: auto"`. No-op flash: `"render as: no override"`. No-view flash: `"no block focused"`.

**ML-3: `_next_kind_label` static method**
- `_ToolPanelActionsMixin._next_kind_label(current: ResultKind | None) -> str` — pure function; cycle mirrors `action_cycle_kind`'s 7-stop tuple (None, CODE, JSON, DIFF, TABLE, LOG, SEARCH). Returns lowercase `.value` or `"auto"` for None.
- `_build_hint_text` (or `_collect_hints` if H-1..H-4 committed): replaces `("t", "render as")` with `("t", f"as {_next_label}")` and inserts `("T", "auto")` at position 1 when `_current_kind is not None`.
- `_next_kind_label` is a `@staticmethod` — bind in FakePanel tests with `_next_kind_label = staticmethod(_ToolPanelActionsMixin._next_kind_label)`.

**ML-4: `enter → toggle_collapse` on ToolGroup**
- `Binding("enter", "toggle_collapse", "Toggle group", show=False)` added before `shift+enter`.
- `action_toggle_collapse(self)`: `self._user_collapsed = not self.collapsed; self.collapsed = self._user_collapsed`. Same path as `on_click`.

**ML-5: `on_descendant_focus` guard for collapsed groups**
- `on_descendant_focus(event)`: when `self.collapsed and event.widget is not self`, calls `self.focus()` and `event.stop()`. Prevents tab order from entering hidden GroupBody children.

### 2026-04-26 — TCS Polish Pass P-1..P-8 (Y-3/Y-4/Y-5/E-2/E-3) — 23 tests, commit `77b58787a`, branch `feat/textual-migration`

**P-1: `_hero_rejection_reason` + width in DensityInputs**
- New `_hero_rejection_reason(self, inp) -> str` on `_ToolPanelActionsMixin` — checks `_HERO_KINDS`, body_line_count, then `inp.width < resolver.hero_min_width`. Returns reason string for user-facing flash.
- `width=self.size.width` added to both `DensityInputs(...)` calls in `action_toggle_collapse` and `action_density_trace`. Without this, the narrow-terminal branch never fires.
- Flash path: `"hero unavailable — {msg}"` on rejection; `tier.value` info flash on success (P-3).

**P-2: `trace_pending` chip in `_header.py._render_v4`**
- Chip appended when `self._panel is not None and not self._is_complete` and `_user_collapse_override=True and _user_override_tier.value == "trace"`.
- Uses `self._colors().warning_dim` for style. Name `"trace_pending"` added to `_DROP_ORDER_DEFAULT/HERO/COMPACT` in `layout_resolver.py` at position before `"exit"`.
- Tests use direct condition logic (panel mock), not full header render, to avoid Textual runtime.

**P-3: destination tier flash in `action_toggle_collapse`**
- `self._flash_header(self._resolver.tier.value, tone="info")` appended in the `else` branch (rejection-free path). Exactly one flash emitted per action call.

**P-4: `inject_recovery_actions()` helper in `tool_result_parse.py`**
- Module-level `inject_recovery_actions(summary) -> ResultSummaryV4` — idempotent; uses `dataclasses.replace()` to return a new frozen instance. `import dataclasses` added at top.
- Called at both `set_result_summary_v4` sites in `services/tools.py`; render-time injection blocks deleted from `_footer._render_footer` (~15 lines removed).
- `ResultSummaryV4` uses `slots=True` and `frozen=True` — `dataclasses.replace()` is the correct mutation path.

**P-5: `exit_code` field + `is_error_for_ui` property on `ToolCallViewState`**
- New field `exit_code: int | None = None` added after `density_reason`.
- `is_error_for_ui` property: ERROR state → True; CANCELLED → False; otherwise `exit_code not in (None, 0)`.
- `_terminalize_tool_view` (Step 9) populates `view.exit_code` by reading `panel._result_summary_v4.exit_code` via `_panel_for_block`. May be None if RS not yet set.
- `_actions._is_error` replaced: delegates to `vs.is_error_for_ui` via `_view_state or _lookup_view_state()`.

**P-8: `_next_tier_in_cycle` docstring**
- Explains why TRACE is excluded from the user cycle; points to `action_density_trace`.

**P-6/P-7/P-9 (complete): all 60 tests pass**

Completed in second pass (worktree `polish-pass-skips`, commit `7a7d45011`):

**P-9: static constants + dead methods deleted**
- `DEFAULT_HINTS`, `ERROR_HINTS`, `COLLAPSED_HINTS` module-level constants removed.
- `_format()` and `_select_hint_set()` deleted entirely.

**H-2: `_collect_hints()` method**
- Returns `(primary, contextual)` tuple of `(key, label)` pairs.
- Streaming: primary = `[("Enter", "follow"), ("f", "tail")]` — tail moved from contextual to primary.
- Error: primary = `[("Enter", "toggle"), ("r", "retry")]` — retry promoted to primary, NOT duplicated in contextual.
- Non-error, complete, expanded: contextual always gets `("alt+t", "trace")` appended.
- `_next_kind_label` accessed via `getattr(self, "_next_kind_label", None)` to handle minimal test stubs.

**H-3: `_truncate_hints(chips, budget)` + `_render_hints(primary, contextual, width)`**
- `_truncate_hints` → `(Text, dropped_count)`: budget-aware chip fitting (len() for ASCII, cell width approx).
- `_render_hints` → calls `_truncate_hints`, appends `+N more`, then F1 always (P-6).
- F1 is appended unconditionally in `_render_hints` — no `narrow` guard, no `_power_keys_exist` gate.

**H-4: `action_density_cycle` method added**
- Uses `self._is_error()` (not inline `_result_summary_v4.is_error`).
- Uses `getattr(self, "size", None)` for width (tests don't set `size` on SimpleNamespace panels).
- Hero rejection: `"hero mode unavailable"` — no `_hero_rejection_reason` call (test stubs don't bind it).
- `D` binding was already present in `_core.py`.

**Test stub gotchas for the split pipeline:**
- `_FakePanel` (class-based) must use `staticmethod(_ToolPanelActionsMixin._next_kind_label)` — raw function assigned as class attr becomes instance method; `staticmethod()` wrapper prevents this.
- `_make_panel` (SimpleNamespace) can use `panel._next_kind_label = _ToolPanelActionsMixin._next_kind_label` directly — instance attrs don't go through the descriptor protocol.
- `_collect_hints` and `_render_hints` must be in the bound-methods list in all test helpers.

**Worktree merge gotcha — committed vs uncommitted state divergence**
- If the main working tree has uncommitted H-1..H-4 changes (e.g. `_collect_hints` in `_actions.py`) but the committed state has the old `_build_hint_text`, the worktree created by `git worktree add` gets the COMMITTED state. Tests written in the worktree that call `_collect_hints` will fail after merge-resolution since the merged file may still use `_build_hint_text`. Always verify with `git show HEAD:path/to/file | grep method_name` before writing tests.

## Changelog — 2026-04-27 — MCC-1 microcopy_line() Rich Text conversion

**MCC-1 — all microcopy_line() branches now return Rich Text:**
- Introduced `_microcopy_text(segments, elapsed_s, stall)` builder — builds Text incrementally with explicit styles per component (`_GUTTER_STYLE="dim"`, `_VALUE_STYLE=""`, `_SEP_STYLE="dim"`, `_ELAPSED_STYLE="dim"`).
- Introduced `_stall_text(stalled, colors=None)` — returns `Text | None`; uses `colors.warning` when SkinColors provided (SCT-1 compat), falls back to `"bold yellow"`. Called once at top of `microcopy_line()` and passed through to AGENT branch too.
- All 6 str-building branches converted to segment-list builds. `_elapsed_suffix()` and `_stall_suffix()` nested functions deleted.
- Return type narrowed `Union[str, Text]` → `Text`; `Union` import removed; catch-all `return ""` → `return Text()`.
- SCT-1's `colors: "SkinColors | None" = None` parameter preserved — stall style uses `colors.warning` when set.
- **Old-test migration pattern**: tests that did `assert microcopy_line(spec, s) == "▸ ... str"` must become `assert microcopy_line(spec, s).plain == "..."`. `"substring" in result` (Text.__contains__) continues to work without change — Rich Text supports string `in` natively. `result.lower()` is `str`-only — use `result.plain.lower()`.
- **Worktree caveat**: TUI source files are all untracked — git worktrees are empty shells; work directly in main repo on `feat/textual-migration`.

**Pre-existing caller issue (do not fix in this spec):**
`_streaming.py` calls `microcopy_line(..., colors=colors)`. The `colors=` kwarg was wired by SCT-1 before MCC-1; MCC-1 preserves the param in signature.

## Changelog — 2026-04-27 — CU-1/CU-2 Spinner Dead Code + A11y Glyph Cleanup

**CU-1 — dead spinner plumbing deleted:**
- `ToolHeader._spinner_char` (instance attr) and `_spinner_identity` (class attr) removed — both were always `None` since CL-1; the render branches they guarded were unreachable.
- `SpinnerIdentity` dataclass and `make_spinner_identity()` function deleted from `animation.py`; `_SPINNER_FRAME_SETS` and `_SPINNER_COLOR_PAIRS` constants deleted with them. `dataclass` import also removed (now unused).
- `lerp_color` and `pulse_phase_offset` removed from `_header.py` imports (only used in dead spinner render); `PulseMixin` import kept.
- `_streaming.py` init: `self._spinner_identity` and `self._spinner_frame` attrs deleted; `make_spinner_identity/SpinnerIdentity` import removed; attach-spec assignment `self._header._spinner_identity = ...` deleted.
- `write_file_block.py:267` and `execute_code_block.py:477` `_spinner_char = None` assignments deleted.

**Indentation gotcha after else-block collapse:**
When removing `if self._spinner_char is not None: ... else:` and making the else-body unconditional, ALL inner blocks lost one level of indentation. The flash/exit-code blocks at the end of `_render_v4` were still inside the former `else:` scope — needed a second Edit pass to dedent them from 16→12 and 12→8 spaces respectively. Pattern: when deleting a top-level `if/else` and keeping only the `else` body, scan all the way to the end of the else scope before declaring done.

**CU-2 — accessibility glyph map extended:**
- `_grammar.py` `_ASCII_GLYPHS` extended with GV-1 gutter glyphs: `┃→|`, `┊→:`, `╰─→\-`
- `glyph()` pure function — test with `monkeypatch.setattr("hermes_cli.tui.constants.accessibility_mode", lambda: True)`, no widget mount needed.

**Pre-existing test failures in target files (do not fix):**
- `test_tool_ux_pass5_a.py::TestA1`, `TestA7` — `_density_tier` missing from `_make_stb()` mock
- `test_tool_ux_pass5_c.py::TestC3::test_partial_label_when_windowed` — same issue
- `test_ux_phase2_3.py::TestOmissionBarResetLabel::test_emoji/nerdfont` — `OmissionBar._reset_label()` icon-mode patch mismatch
These were failing on baseline before CU-1/CU-2; not introduced by this work.
- **Merge conflict resolution pattern**: when both branches modify the same "render as" line differently, keep the HEAD's outer structure (`_build_hint_text`/`_collect_hints` scaffold), apply the new behavior (next-kind label + revert hint) inside the existing conditional.

## Changelog — 2026-04-27 — SK-1/SK-2 Streaming Skeleton + KIND Hint Defensive Clear

**SK-1 — pre-first-chunk skeleton row** (`tool_blocks/_streaming.py`):
- New constants: `_SKELETON_DELAY_S = 0.1`, `_SKELETON_GLYPH = "· · ·"`, `_SKELETON_PULSE_S = 0.4`.
- New attrs in `__init__`: `_skeleton_widget`, `_skeleton_timer`, `_skeleton_pulse_timer`, `_skeleton_dim`. Init in `__init__` (not `on_mount`) so `_dismiss_skeleton()` is safe on `__new__`-built test instances.
- `on_mount` arms 100ms `set_timer(_maybe_mount_skeleton)` registered with `ManagedTimerMixin._register_timer`.
- `_maybe_mount_skeleton` race-guards `_total_received > 0 or _completed or _is_unmounted or not is_attached`, mounts a `Static(Text)` with classes `tool-skeleton tool-skeleton--dim` `before=self._tail`. Pulse via `set_interval(0.4s)` toggling `--dim` class, skipped under `app._reduced_motion`.
- `_best_kind_icon`: streaming_kind_hint → ToolHeader._KIND_HINT_ICON glyph → header `_tool_icon` → `▸` fallback.
- `append_line` first-chunk dismisses skeleton (covers both <100ms and ≥100ms paths). `complete()` calls `_dismiss_skeleton()` BEFORE `_stop_all_managed()` (mixin stops timers but does NOT unmount the widget).
- `_dismiss_skeleton` uses `getattr(self, "_skeleton_*", None)` so partially-initialized test instances (`StreamingToolBlock.__new__(...)`) don't crash.
- New CSS in `hermes.tcss`: `.tool-skeleton { color: $text-muted; height: 1; padding: 0 1; }` + `.tool-skeleton--dim { opacity: 0.5; }`. Both classes new — verified absent before.

**SK-2 — KIND hint defensive clear** (`tool_blocks/_header.py:_on_axis_change`):
- New `state` axis branch: when transitioning into `{COMPLETING, DONE, ERROR, CANCELLED}` and `_streaming_kind_hint is not None`, clear and refresh.
- Lazy import `ToolCallState` inside the branch (matches existing `_header.py` lazy-import convention).
- Axis name is `"state"` not `"phase"` (per `services/tools.py:111` `AxisName = Literal["state","kind","density","streaming_kind_hint"]`).

**Test-fixture gotcha — read-only Widget property leakage across tests:**
Setting `type(widget).is_attached = PropertyMock(...)` on a Textual Widget subclass mutates the SHARED CLASS, leaking to every other test in the same pytest session. Fix: define a one-off `_IsolatedBlock(StreamingToolBlock)` / `_IsolatedHeader(ToolHeader)` subclass in the test module and override the property as a plain class attribute or descriptor on the SUBCLASS. Cache the subclass at module scope and swap via `instance.__class__ = _IsolatedSubclass`. `size` property has the same trap.

**`Static` widget renderable accessor:**
The renderable passed to `Static(content)` is stored at `_Static__content` (Python name-mangling for `__content`) — `widget.renderable` does not exist on Textual 8.x Static. Tests that need to read back a Static's rendered Text without a running App must use `widget._Static__content`.

**`Static.remove()` requires App context:**
Calling `Widget.remove()` on a unit-test mock raises `NoActiveAppError`. For tests that exercise unmount paths, replace `widget.remove = MagicMock()` after mount.

**Tests:** `tests/tui/test_streaming_skeleton.py` — 13 tests (5 SK-2 hint clear + 8 SK-1 skeleton). All bare-instance unit tests; no `run_test`/`HermesApp` used (avoids VarSpec crash + slow setup).

**Concept.md updated:** §PHASE owns liveness "Pre-first-chunk skeleton" subsection appended with implementation pointer; §SLR-3 note appended with header-side defensive clear note.

---

## 2026-04-27 — TB-1..TB-5: Truncation Bias + Slow Renderer Fallback

**New ClassVars on BodyRenderer ABC** (`body_renderers/base.py`):
- `truncation_bias: ClassVar[Literal["head","tail","priority","hunk-aware"]] = "tail"` — per-kind clamping strategy
- `kind_icon: ClassVar[str] = "⬜"` — used by `_make_slow_placeholder` in TB-4
- All 17 REGISTRY renderers (9 Phase-C + 8 streaming) must re-declare both in `__dict__` or meta-test `test_each_renderer_declares_bias` fails. The ABC itself is exempt from the meta-test.

**`summary_line()` on BodyRenderer** (`body_renderers/base.py`):
- `payload_row_count() → int` — `len((self.payload.output_raw or "").splitlines())`
- `summary_line() → str` — base returns `"(N rows)"` / `"(no output)"`; per-kind overrides:
  - `DiffRenderer`: `_diff_stats() → (files, plus, minus)` → `"N file(s) · +A −D"` (calls module-level `_parse_file_stats`)
  - `JsonRenderer`: `_json_top_keys() → str` (top 4 dict keys joined) → `"{ k1, k2 }"`
  - `TableRenderer`: `row_count()/col_count()` wrap `_row_count/_col_count` → `"N rows × M cols"` (must call `build()` first to populate)
  - `SearchRenderer`: `hit_count()` wraps `_hit_count` → `"N hit(s)"` / `"(no matches)"`
  - `LogRenderer`: `last_log_line(maxlen=60)` → `"… last line"` / `"(no output)"`

**`_apply_clamp()` dispatch** (`body_renderers/base.py`):
- `build_widget(density=None, clamp_rows=None)` — base now accepts `clamp_rows`; if set, calls `_apply_clamp(rows, clamp_rows)` on `self.payload.output_raw.splitlines()` and writes result via `Text("\n".join(clamped))`; `markup=True` on CopyableRichLog for chip rendering
- All Phase-C renderer `build_widget` overrides must also accept `clamp_rows=None` kwarg (they ignore it; clamping happens in base for non-BodyFrame renderers)
- `_apply_clamp(rows, clamp)` dispatches on `self.truncation_bias`:
  - `"tail"`: keep last `clamp-1` rows, prepend `"…N earlier"` chip
  - `"head"`: keep first `clamp-1` rows, append `"…+N more"` chip
  - `"hunk-aware"`: walk `@@` boundaries from end; preserve complete hunks; chip = `"…+N hunks (+M lines)"`
  - `"priority"`: sort by `self._hit_scores` (parallel list), keep top `clamp-1`, append `"…+N hits"` chip
- `_tail_clamp()` is a pure helper for `_hunk_aware_clamp` fallback (avoids recursion through `_apply_clamp`)

**`LayoutDecision.clamp_rows`** (`tool_panel/layout_resolver.py`):
- `_DEFAULT_BODY_CLAMP: int = 12` module constant
- `clamp_rows: int | None = None` field on `LayoutDecision` (frozen dataclass, default keeps existing constructors working)
- `_clamp_for_tier(tier) → int | None` module-level function: HERO→None, DEFAULT→12, COMPACT→None, TRACE→0
- `resolve_full()` now sets `clamp_rows=_clamp_for_tier(tier)` in returned LayoutDecision
- `_on_tier_change()` in `_core.py` also sets `clamp_rows=_clamp_for_tier(tier)`

**`BodyPane.apply_density()`** (`tool_panel/_footer.py`):
- Class-level constants: `_SLOW_DEADLINE_S = 0.25`, `_HARD_DEADLINE_S = 2.0`
- New init attrs: `_slow_worker_active: bool`, `_hard_timer: Timer | None`, `_last_tier: DensityTier | None`
- `apply_density(tier)` — public entry; routes: TRACE→remove all, COMPACT→`_render_compact_body()`, DEFAULT/HERO→`_mount_body_with_deadline(tier)`
- `_render_compact_body()` — mounts `Static(renderer.summary_line(), classes="compact-summary")`
- `_mount_body_with_deadline(tier)` — builds widget synchronously; if elapsed > 250ms logs warning (first-build path never uses worker; only re-renders triggered by density changes would use `_start_slow_render`)
- `_make_slow_placeholder(icon)` → `Static` with class `"slow-placeholder"`; the icon string is embedded in the renderable
- `_slow_kill()` — cancels `app.workers.cancel_group(self, "slow-render")`, mounts FallbackRenderer widget
- `@work(thread=True, exclusive=True, group="slow-render") _render_in_worker(tier)` — builds widget in bg thread; calls `self.app.call_from_thread(self._swap_in_real_widget, widget)` on completion
- `_swap_in_real_widget(widget)` — guard: if `_slow_worker_active` is False (kill already ran), discard and return
- `_apply_layout` in `_core.py` now calls `self._body_pane.apply_density(decision.tier)` as step 5

**Test patterns:**
- BodyPane unit tests use `object.__new__(BodyPane)` + manual attr init (no DOM)
- `query("*").remove()` calls are mocked via `bp.query = lambda _: FakeQuery()` pattern
- `_make_slow_placeholder` returns `Static` — access renderable via `widget._Static__content` not `widget.renderable` (Python name-mangling)
- `FallbackRenderer` called from `_footer.py` needs a `cls_result` arg to avoid crash in `_should_show_footer()`; supply dummy `ClassificationResult(kind=ResultKind.TEXT, confidence=0.0)`

---

## Changelog — 2026-04-27 ERR Cell Rule (ER-1..ER-5)

**New module:** `hermes_cli/tui/services/error_taxonomy.py`
- `ErrorCategory(str, Enum)` — 8 values: ENOENT/EACCES/ENETUNREACH/SIGNAL/USAGE/RUNTIME/TIMEOUT/UNKNOWN
- `STDERR_TAIL_ROWS = 12`
- `classify_error(stderr, exit_code) -> ErrorCategory` — regex → exit-code class → UNKNOWN
- `split_stderr_tail(stderr, *, rows=12) -> list[str]` — last N non-empty lines

**ToolCallViewState** (`services/tools.py`) — 3 new fields:
- `error_category: Any | None = None` — populated before ERROR state write in `_terminalize_tool_view`
- `stderr_tail: tuple[str, ...] = ()` — last N stderr lines
- `payload: str = ""` — stdout fallback for ERR body

**ToolHeader** (`tool_blocks/_header.py`):
- `_error_category_text() -> str` — reads `panel._view_state.error_category`; UNKNOWN fallback
- `_render_v4()` — when `_tool_icon_error`, skip `trim_header_tail` entirely; emit exactly
  `[("error-category", Text), ("outcome", Text("ERR"))]`; no elision at any tier

**BodyPane** (`tool_panel/_footer.py`):
- New attr: `_err_body_locked: bool = False`
- `mount_static(widget)` — remove all children, mount widget, set `_err_body_locked = True`
- `apply_density()` — returns immediately when `_err_body_locked`

**_core.py** — new ERR body widgets + guard:
- `StderrTailWidget`, `PayloadTailWidget`, `EmptyOutputWidget` — thin `Static` subclasses
- `pick_err_body_widget(view) -> Widget` — selects ERR body widget based on view fields
- `_apply_layout()` step 5 — if `vs.state == ERROR` and not locked, calls `mount_static(pick_err_body_widget(vs))` instead of `apply_density`

**_footer.py** (ER-4):
- `_RECOVERY_KINDS` extended: `("retry", "edit_args", "copy_err")`
- `_sort_actions_for_render(actions) -> list` — recovery cluster first, F1 last
- `_rebuild_action_buttons` uses `_sort_actions_for_render` instead of inline sort
- `_IMPLEMENTED_ACTIONS` + `ACTION_KIND_TO_PANEL_METHOD` extended with `edit_args`

**tool_result_parse.py** (ER-5):
- `ActionKind` Literal extended with `"edit_args"`
- `_make_edit_args()` → `Action(label="edit args", hotkey="a", kind="edit_args")`
- `_RECOVERY_BY_CATEGORY` dict + `_allowed_recovery(cat)` — category gates retry/edit_args
- `inject_recovery_actions()` — auto-classifies, gates retry/edit_args via `_allowed_recovery`;
  `copy_err` always injected if stderr exists regardless of category

**_actions.py** (ER-5):
- `EditToolArgsRequested(tool_call_id)` — standalone `Message` subclass
- `action_edit_args()` — posts `EditToolArgsRequested`; `"a"` binding in `ToolPanel.BINDINGS`

**Gotchas:**
- `Static` widget content is stored as `_Static__content` (name-mangled); access via `widget.content` property (not `.renderable`)
- `_error_category_text()` reads `panel._view_state.error_category`, not `self._view` (which doesn't exist on ToolHeader)
- `_allowed_recovery` lazy-builds `_RECOVERY_BY_CATEGORY` on first call to avoid import-time cycle with `error_taxonomy`
- Hotkey "a" for `edit_args` chosen because "e" is owned by `copy_err` and "r" by `retry`

---

## Changelog — 2026-04-27 Invariant Lint Gates (IL-1..IL-8)

**New test file:** `tests/tui/test_invariants.py` (25 tests, <1s, runs on every PR touching the six owner paths: `tool_blocks/`, `tool_panel/`, `body_renderers/`, `services/tools.py`, `services/plan_sync.py`, `services/feedback.py`).

**Concept doc:** frozen v3.6 through 2026-05-11 (commit a7ec8e51d) so gates measure against a stable target. See `/home/xush/.hermes/tool_block_convergence_plan.md` for the convergence strategy this spec implements (Step 2 of 6).

**Eight gates:**
- **IL-1** sibling-private cross-read AST ban with explicit composer allowlist table (NOT AST inference — ownership rule is "the module that composes the inner widget", and `super().__init__` delegation hides composition sites). Owner table: `_block.py` + `_streaming.py` may read `self._header._*`; `_core.py` + `_actions.py` + `_child.py` may read `self._block._*`. Also flags `hasattr/getattr` on forbidden chains.
- **IL-2** raw hex `#[0-9A-Fa-f]{6}` outside allowlist. Allowlist: `SkinColors.default()` body, dataclass field defaults inside `SkinColors`, `_*_FALLBACK` module-level constants, `# noqa: hex` annotation, hex inside Python comments, test files.
- **IL-3** microcopy form on hint labels — bracket-key form, lowercase letter, no space after bracket, ≤14 chars.
- **IL-4** per-tier chip count caps (HERO ≤7, DEFAULT ≤5, COMPACT ≤3, TRACE ≤2) via new `LayoutDecision.visible_chip_count` accessor; calls `trim_tail_for_tier` directly.
- **IL-5** status chip casing — uppercase `_CHIP_*` constants in `_header.py`. Existing `TestStatusChipCasing` in `test_microcopy_and_confidence.py` deleted as part of this migration.
- **IL-6** renderer purity AST gate — no `view_state.*`, `self._app.*`, `self._panel.*`, `self._block.*` reads inside any `BodyRenderer.render/build/build_widget` method.
- **IL-7** `set_axis` ordering — pattern-asserts hint-clear-line < state-write-line within `_set_view_state`.
- **IL-8** tightened empty-except ban — every except must re-raise, log with `_log.<level>` (any severity, with or without `exc_info`), match a narrow allowlisted exception type, or carry `# noqa: bare-except` justification comment. Module-level `_log = logging.getLogger(__name__)` required if module has any except clause.

**Production-code touches as part of landing the gates:**

- `tool_blocks/_block.py` — added `has_partial_visible_lines() -> bool` default-False; `_DIFF_ADD_BG_FALLBACK` and `_DIFF_DEL_BG_FALLBACK` module constants for diff bg dict `.get()` defaults.
- `tool_blocks/_streaming.py` — `has_partial_visible_lines()` override returns `_visible_count < len(_all_plain)`. **This is the IL-1 escape pattern: when a sibling needs derived data, expose a public method on the owner instead of letting callers reach in.**
- `tool_blocks/_header.py` — IL-1 fix: replaced `self._panel._block._visible_count` chain with `_block.has_partial_visible_lines()`.
- `body_renderers/_grammar.py`, `body_renderers/shell.py` — `_ERROR_FG_FALLBACK = "#E06C75"` module constant (IL-2 pattern).
- `tool_panel/_footer.py` — `_ACCENT_FALLBACK = "#5f87d7"`.
- `tool_panel/_actions.py` — `_APP_BG_FALLBACK = "#1e1e2e"`.
- 142 bare-except sites: appended `# noqa: bare-except` annotation with justification.
- 9 modules without logger now have `import logging; _log = logging.getLogger(__name__)`: `tool_blocks/_shared.py`, `tool_panel/_core.py`, `tool_panel/_child.py`, `body_renderers/{log,table,search,code,diff,json}.py`.

**New API:**
- `LayoutDecision.visible_chip_count: int` — exposed for IL-4 testing; counts header chips after `trim_tail_for_tier` runs.
- `ToolBlock.has_partial_visible_lines() -> bool` (and override on `StreamingToolBlock`) — sibling-safe accessor for streaming truncation state.

**Non-obvious test patterns:**
- IL-1 uses an explicit per-module composer allowlist dict at the top of the test class. Adding a new widget that legitimately composes another requires a new row here, NOT a code-side annotation.
- IL-3 drives `_collect_hints` via `MagicMock(spec=_ToolPanelActionsMixin)` to avoid mounting the panel; the hint registry is data-only.
- IL-4 calls `trim_tail_for_tier` directly with synthetic `_Segment` lists rather than mounting `ToolHeader` (no DOM, no width-measure).
- IL-5 introspects `dir(_header)` filtering for names matching `^_CHIP_[A-Z]+$` so future status chips auto-enroll.
- IL-7 reads `services/tools.py` source as text and asserts line ordering inside the `_set_view_state` function body — does NOT execute the function.
- IL-8 walks AST `ExceptHandler` nodes; comment annotations are matched on the source line via `linecache`, not via AST (comments are not AST nodes).

**Gotchas:**
- IL-2 must allow hex inside Python comments (`accent: str  # hex, e.g. "#0178D4"` in `_grammar.py:111`); split each line at the first `#` before scanning.
- IL-2 dataclass field defaults inside `SkinColors` body (e.g. `error_dim: str = "#8B2020"`) are part of the canonical palette and exempt — the `default()` classmethod is not the only canonical site.
- `# noqa: hex` and `# noqa: bare-except` are project-local conventions; `flake8` does not consume them. Annotation is purely for the IL-2/IL-8 sweepers.
- Adding a new owner-path widget that composes another: append a row to IL-1's `_OWNER_TABLE` dict in the test, not just in the spec. The test is authoritative.

**Acceptance:** `pytest tests/tui/test_invariants.py -q --override-ini="addopts="` → `25 passed in 0.52s`. Spec at `/home/xush/.hermes/invariant_lint_gates.md` (Status: IMPLEMENTED 2026-04-27).

## Changelog — 2026-04-27 Axis Bus Sweep (AB-1..AB-3)

**New test file:** `tests/tui/test_axis_bus_sweep.py` (9 tests, <2s).

**Spec:** `/home/xush/.hermes/axis_bus_sweep.md` (Status: IMPLEMENTED 2026-04-27). Merge commit `13a8d8d51`, branch `feat/textual-migration`.

**AB-1 — streaming KIND hint clears on kind-axis change:**
- Added `axis == "kind"` branch to `ToolHeader._on_axis_change` (between `streaming_kind_hint` and `state` branches). Clears `_streaming_kind_hint` + refreshes when hint is non-None; no-op when hint already None.
- Added `# AB-3: density not relevant: <reason>` annotation to `_on_axis_change` docstring area so the AB-3 sweep test's opt-out mechanism fires correctly.
- Updated both writer sites in `tool_panel/_actions.py`: `force_renderer` and `action_kind_revert` now call `set_axis(view, "streaming_kind_hint", None)` BEFORE direct `view.user_kind_override = ...` assignment. This ensures the existing `streaming_kind_hint` watcher branch fires first and refreshes the header before body-replace proceeds.

**AB-2 — delete post-state view.is_error write:**
- Deleted `view.is_error = is_error  # double-write kept from original for safety` (services/tools.py, formerly line 825, after `_set_view_state`).
- Updated comment block at Step 9 to add `# NOTE: no post-state mutations on view.` as a forward-looking invariant note.

**AB-3 — watcher coverage sweep test:**
- Test walks `hermes_cli/tui/` source for `add_axis_watcher(...)` calls, resolves watcher callable source, and asserts it has an `axis == "<name>"` branch for every name in `AxisName`. Opt-out annotation: `# AB-3: <axis> not relevant: <reason>` anywhere in the watcher function body.
- Guards against vacuous pass: asserts ≥1 watcher site was found.

**New conventions / patterns:**
- **AB-3 opt-out pattern:** `# AB-3: density not relevant: header display does not change with density tier; ToolPanel owns layout`. Use this format on the watcher function for any axis the watcher intentionally ignores.
- **Writer-side hint clear pattern:** when mutating `user_kind_override` by direct assignment (not via `set_axis`), the writer must explicitly call `set_axis(view, "streaming_kind_hint", None)` before the assignment to notify watchers.

**Gotchas:**
- `ToolHeader` (line 75) ≠ `ToolCallHeader` (line 916) — both in `_header.py`. `_on_axis_change` and `_streaming_kind_hint` live on `ToolHeader`. Tests must use `object.__new__(ToolHeader)`.
- `ToolRenderingService` (not `ToolsService`) is the class in `services/tools.py`.
- `_terminalize_tool_view` test needs `MagicMock(spec=ToolRenderingService)` svc with `_tool_views_by_id`, `_tool_views_by_gen_index`, `_open_tool_count`, `_agent_stack`, `_turn_tool_calls`, `svc.app.*` all set; pass `view=` kwarg to skip internal lookup.
- `_make_view()` SimpleNamespace fakes must include `_watchers=[]` (fresh list per call) because `set_axis` iterates `view._watchers`.
- AB-3 `_find_watcher_names` must match both `ast.Name` calls (`add_axis_watcher(...)` direct) and `ast.Attribute` calls (`mod.add_axis_watcher(...)`) — the production site uses the direct form after a local `from ... import add_axis_watcher`.
- `view.gen_index` required on view fakes passed to `_terminalize_tool_view` (Step 11 of the function body).


---

## Changelog — 2026-04-27 Axis Bus Sweep (AB-1..AB-3)

**New test file:** `tests/tui/test_axis_bus_sweep.py` (9 tests, ~0.6s). Spec at `/home/xush/.hermes/axis_bus_sweep.md` (Status: IMPLEMENTED, merge 13a8d8d51).

**AB-1 — KIND axis change clears streaming hint:**
- `tool_blocks/_header.py::ToolHeader._on_axis_change` — added `axis == "kind"` branch (between the existing `streaming_kind_hint` and `state` branches). Clears `_streaming_kind_hint` and refreshes; honors concept §user-authority-on-KIND.
- `tool_panel/_actions.py::force_renderer` (sites :1064 set + :1188 revert) — calls `set_axis(view, "streaming_kind_hint", None)` *before* the direct `view.user_kind_override = ...` assignment. The existing watcher branch picks up the clear and refreshes.

**AB-2 — Delete post-state `is_error` write:**
- `services/tools.py::_terminalize_tool_view` — removed line 825 (`view.is_error = is_error  # double-write kept from original for safety`). Pre-state write at :802 is now the only write. R3-AXIS-03 invariant: subscribers see final values on first watcher notification.

**AB-3 — Watcher-axis coverage sweep test:**
- New structural test asserting every `add_axis_watcher` registration's body has a branch (or explicit opt-out) for every published axis. Forward-looking — catches regressions if a future axis is added or a future watcher is registered without full coverage.
- **Opt-out convention:** `# AB-3: <axis-name> not relevant: <reason>` comment on a line within the watcher body. The sweep test reads source text to recognize this; it is *not* an AST-level annotation.

**Important — `user_kind_override` is NOT in `AxisName`:**
The `AxisName` enum (`services/tools.py:116`) has only `state | kind | density | streaming_kind_hint`. `user_kind_override` is mutated by direct assignment (`view.user_kind_override = ...`), never via `set_axis()`. This is intentional and stays that way during the v3.6 freeze. Implications:
- Any code that sets `user_kind_override` must explicitly clear `streaming_kind_hint` via `set_axis(view, "streaming_kind_hint", None)` *before* the direct assignment, so the existing axis watcher picks up the clear and refreshes the header before the override-driven re-render.
- AB-1 test `test_force_renderer_clears_hint_before_override_write` asserts this ordering with a call-order spy.
- Adding `user_kind_override` to `AxisName` is a v3.7-class concept change (new published axis, new watcher contract). Out of scope until concept doc unfreezes.

**Non-obvious test patterns:**
- AB-1 force_renderer tests construct a panel via `MagicMock(spec=ToolPanel)` and patch `set_axis` to record call order; assert hint-clear timestamp < override-write timestamp.
- AB-2 uses `ast.walk` on `_terminalize_tool_view` source body, finding `Assign`/`AugAssign` nodes whose target is `view.<attr>`, collecting their line numbers, and asserting all line numbers are *less than* the `_set_view_state(...)` call's line number. The "inverse sanity" meta-test feeds a synthetic source with a deliberate post-state write and asserts the walker flags it.
- AB-3 walks `If` chains inside watcher function bodies, collects axis-name string literals from the comparison RHS, and compares against `set(AxisName.__members__.values())`. Opt-out comments are matched via `linecache` on the line *immediately preceding* the `def _on_axis_change` start of the watcher.

**Gotchas:**
- `force_renderer` is invoked from the `t` keystroke handler, not from a `set_axis` writer. Easy to miss because the surrounding code uses `set_axis` for everything else; direct-assignment was a v3.5-era choice that survives.
- The AB-3 sweep test's opt-out comment regex looks for `# AB-3:` exactly. A typo (`# ab3:`, `# AB3:`) silently disables the opt-out.
- When adding a new `add_axis_watcher` site, run `pytest tests/tui/test_axis_bus_sweep.py::TestAB3WatcherCoversAllAxes` first — it surfaces missing branches before any behavioral test runs.

**Acceptance:** `pytest tests/tui/test_axis_bus_sweep.py tests/tui/test_invariants.py -q --override-ini="addopts="` → `34 passed in 0.59s` (9 AB + 25 IL).

## Changelog — 2026-04-27 Quick Wins C — Services & Contract Polish (SC-1..SC-9)

**Files changed:** `body_renderers/diff.py`, `tool_panel/_completion.py`, `tool_panel/layout_resolver.py`, `tool_blocks/_header.py`, `tool_blocks/_streaming.py`, `services/tools.py`, `services/feedback.py`, `services/error_taxonomy.py`, `tool_result_parse.py`

### SC-1: DiffRenderer renderer purity (concept §renderer-purity rule 5)

`DiffRenderer.build()` used to post `DiffStatUpdate` messages per `+`/`-` line (PG-3). This violates renderer purity — renderers must be pure data producers.

**Fix pattern:**
- Add `self._diff_lines: list[str] = list(lines)` inside `build()` to capture parsed lines as instance state.
- Add `diff_lines` property returning `list(self._diff_lines)`.
- Delete the `for line in lines: app.post_message(...)` block from `build()`.
- Add `_ToolPanelCompletionMixin._emit_diff_stat_for_renderer(renderer)` which iterates `renderer.diff_lines` and posts `DiffStatUpdate` via `self.app.post_message`.
- Wire from `_swap_renderer()` after `renderer.build_widget()`: `if hasattr(renderer, "diff_lines"): self._emit_diff_stat_for_renderer(renderer)`.

**Test gotcha:** Setting `app=MagicMock()` at construction time causes `SkinColors.from_app(MagicMock)` to crash (MagicMock isn't a string for `_hex_re.match`). Instead: create renderer without `app=`, then set `renderer._app = fake_app` after init. Lazy `colors` property re-evaluates on first access. Provide `fake_app = SimpleNamespace(get_css_variables=lambda: {}, post_message=...)` so fallback colors work.

### SC-2: Stall reduced-motion fallback glyph (concept §motion-intensity)

`_streaming.py` stall detection already paused the pulse animation. Under `reduced_motion=True`, a paused pulse is invisible — the stall is undetectable without animation.

**Fix:** Add `ToolHeader._stall_glyph_active: bool = False`. In `_render_v4`, after the `_tool_icon_error` ERR override, add `elif self._stall_glyph_active: raw_glyph = "◌"`. In `_streaming.py` stall toggle:
```python
if stalled and not self._header._pulse_paused:
    self._header._pulse_paused = True
    if reduced_motion:
        self._header._stall_glyph_active = True
elif not stalled and self._header._pulse_paused:
    self._header._pulse_paused = False
    self._header._stall_glyph_active = False
```

**Test gotcha:** `StreamingToolBlock.app` is a Textual read-only property — cannot set it with `block.app = ...`. Use `SimpleNamespace` namespace as the header proxy and test the toggle logic directly.

### SC-4: Classifier 50ms timeout (concept §perception-budgets)

`_stamp_kind_on_completing` in `services/tools.py` called `classify_content()` synchronously with no timeout.

**Fix:** Module-level singleton `_CLASSIFIER_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="hermes-classifier")`. Helper `_classify_with_timeout(payload)` submits to executor and calls `fut.result(timeout=0.050)`. On `TimeoutError`: log at `WARNING` with `exc_info=True` (required for IL-8), return `ClassificationResult(kind=ResultKind.TEXT, confidence=0.0)`. Replace direct `classify_content(payload)` call with `_classify_with_timeout(payload)`.

**IL-8 compliance:** `except concurrent.futures.TimeoutError:` with `logger.warning(..., exc_info=True)` — IL-8 requires `exc_info=True` for `.warning()`; `.exception()` or `.debug()` work without it.

**Worker thread note:** `concurrent.futures` worker thread outlives the timeout; result is discarded. Acceptable — classifier holds no locks, payload is read-only.

### SC-9: ErrorCategory ENOTDIR + EINVAL

Added to `ErrorCategory(str, Enum)` and `_STDERR_RULES` in `error_taxonomy.py`:
- `ENOTDIR = "ENOTDIR"` — matched by `r"not a directory"`
- `EINVAL = "EINVAL"` — matched by `r"invalid argument"` and `r"unrecognized option"`

Added to `_RECOVERY_BY_CATEGORY` in `tool_result_parse.py`:
- Both get `frozenset({"edit_args", "retry"})` — user-fixable path/arg errors.

**Note:** Keep value-form aligned with sibling uppercase errnos (`ENOENT`, `EACCES`). Don't re-spell existing lowercase values (`signal`, `runtime`, etc.) — CSS class names and chip labels are keyed by `.value`.

### IL-9: View-mirror ordering invariant

New invariant gate `TestIL9ViewMirrorOrdering` in `tests/tui/test_invariants.py`. AST-walks `services/tools.py` and asserts no `view.dur_ms = ...` or `view.is_error = ...` write appears **after** a terminal `_set_view_state(view, ToolCallState.{DONE|ERROR|CANCELLED|REMOVED})` call in the same function. Locks in R3-AXIS-03 ordering contract. Target runtime: <1s.

### SC-6: _trim_tail_segments ERR pin docstring

Added docstring noting PHASE=ERR is intentionally absent — the ERR cell rule (concept §ER-1..ER-5) is enforced at `ToolHeader._render_v4` level via fixed 2-chip pinned tail. Prevents future readers from "fixing" the missing ERR branch.

### SC-7: flash() event-loop-only docstring convention

Added convention note to `FeedbackService.flash()` docstring: "Convention: called from the event loop only — workers should marshal via App.call_from_thread." No runtime assertion (blocked by concept v3.6 freeze); enforced as AST meta-test `test_no_worker_calls_to_flash`.

## Changelog — 2026-04-27 Quick Wins A — Visual & Glyph Polish (VP-1..VP-10)

### New constants / API changes

- `WRAP_CONTINUATION = "↵"` added to `body_renderers/_grammar.py` next to `FOCUS_PREFIX`. No consumers yet — locks the glyph choice for forward compat. ASCII fallback entry deferred (no emission site to validate choice against).
- `truncation_footer()` in `_grammar.py` gains `action: str | None` (was `str = "expand"`). Passing `action=None` omits the action suffix. Backward-compat: existing callers with default `action="expand"` are unchanged.
- `BodyRenderer.summary_line()` in `base.py` now has two keyword-only params: `density: DensityTier | None = None` and `cls_result: ClassificationResult | None = None`. All five overrides updated. `LogRenderer`, `DiffRenderer`, `SearchRenderer` have COMPACT-tier branches; `TableRenderer` and `JsonRenderer` are signature-only.
- `_render_web_search_results()` in `streaming.py` gains `colors: SkinColors | None = None`. Call site at `StreamingSearchRenderer.finalize` passes `colors=self.colors`.
- `BodyFrame._TIER_CLASS` now has `"default"` key → `"body-frame--default"`. `DEFAULT_CSS` adds `BodyFrame.body-frame--default { margin-bottom: 1; }`.
- `_low_confidence_caption()` in `base.py` now returns `"⚠ low-confidence: {kind} (press t to cycle)"` — affordance hint matches user-forced caption.
- Chevron glyph in `_header.py::_render_v4`: glyph selection (★/▸/▾) extracted from the affordance branch; both branches share it. Style is `"dim"` when `_has_affordances=True`, `colors.separator_dim` otherwise.

### Gotchas

- `ToolHeader._render_v4` relies on `self.styles.height`, `self.has_class()`, and `self.screen` via the Textual widget hierarchy. Tests using `__new__` to stub it will hit `RuntimeError: Widget is missing attributes` when any Textual layout property is accessed. Workaround: test the chevron logic directly (extract the glyph/style selection formula) rather than running `_render_v4` on an uninitialized stub.
- `DensityTier.DEFAULT.value == "default"` — `_TIER_CLASS.get(str(density.value), "")` matches correctly.

## Changelog — 2026-04-27 Quick Wins B — Footer & Header (FH-1..FH-8), commit `c9d64f58a`

### New fields / API changes

- `LayoutInputs.is_streaming: bool = False` — new field on the frozen `LayoutInputs` dataclass (`layout_resolver.py`). Wired at all 5 `DensityInputs(...)` construction sites in `_actions.py` (3 sites) and `_completion.py` (1 site). Value: `phase in (ToolCallState.STARTED, ToolCallState.STREAMING)`.
- `BodyRenderer.decision_or_default()` gains `has_footer_content: bool = False` kwarg. Now returns `footer_visible=has_footer_content` (mirrors resolver semantics). Old callers unaffected (keyword default is False).

### Behaviour changes

- **Footer streaming gate (FH-3)**: `ToolBlockLayoutResolver.resolve_full()` returns `footer_visible=False` when `inputs.is_streaming=True`. `FooterPane._refresh_visibility()` adds parallel guard: `if _block._completed is False → display = "none"`. Guards `set_density()` from overwriting resolver's just-written none during a mid-stream tier change.
- **COMPACT footer (FH-5)**: `resolve_full` drops `tier != DensityTier.COMPACT` exclusion. `has_footer_content` is now the sole content gate. At COMPACT with no content → hidden (unchanged). At COMPACT with content → visible (new).
- **accepts(COMPACT) for diff/table/search (FH-6)**: `DiffRenderer`, `TableRenderer`, `SearchRenderer` no longer block COMPACT phase — `accepts()` delegates to `super()`. Their existing `summary_line()` provides the one-line surface.
- **Skeleton dismiss coalesced (FH-2)**: `StreamingToolBlock.append_line()` no longer calls `_dismiss_skeleton()`. Moved to `_flush_pending()` after the batch write loop, gated on `lines_written > 0`. Content row and skeleton removal both commit in the same flush tick → same paint cycle.
- **OmissionBar settled gate (FH-8)**: `_refresh_omission_bars()` clears `cap_msg = None` when `self._settled is True`. `_on_settled_timer()` re-fires `_refresh_omission_bars()` when either omission bar is mounted, so the cap warning drops exactly at the 600 ms quiesce boundary.
- **`StreamingCodeRenderer.truncation_bias` = `"tail"` (FH-4)**: was `"head"`. Defensive against future clamp paths during streaming (latent today — `_apply_clamp` not reached during streaming).
- **Header label width (FH-7)**: `_render_v4` re-reads `tail.cell_len` as `final_tail_w` immediately before label truncation (regression-prevention — no current bug).
- **Hint dedup (FH-1)**: `_collect_hints` adds a final-pass dedup: `contextual = [t for t in contextual if t not in set(primary)]`. Operates on contextual only; primary is single-emission by construction.

### Gotchas

- `FooterPane.parent` is a read-only `Widget` property. Tests must use an isolated subclass with `parent` overridden as a class attribute (`class _IsolatedFP(FooterPane): parent = stub`) — cannot assign directly to `fp.parent`.
- `FIXED_PREFIX_W` in `_header.py::_render_v4` is a local variable (not module-level). Tests for FH-7 cannot import it; use a stand-in constant and test the arithmetic shape directly.
- `_HintsMixin` / `_HintsActionsMixin` do not exist — the actions class is `_ToolPanelActionsMixin`. FH-1 dedup logic is pure Python (set subtract); test it inline without importing the mixin.

## Changelog — 2026-04-28 — Skill Picker Empty Description Fallback SP-1/SP-2 — 6 tests, commit `2b0877709`, branch `worktree-skill-picker-descriptions`

**Spec:** `/home/xush/.hermes/spec-skill-picker-descriptions.md`. Two isolated fixes to `hermes_cli/tui/overlays/skill_picker.py`.

**SP-1 (list row):** `_rebuild_list()` line 178-184. Replaced `candidate.description[:40]` bare embed with:
```python
_desc = candidate.description[:40] if candidate.description else "—"
Option(f"${candidate.name}{disabled_badge}  [dim]{_desc}[/dim]", id=candidate.name)
```
Empty description now shows `[dim]—[/dim]`; non-empty description is wrapped in `[dim]...[/dim]` for visual consistency.

**SP-2 (detail pane):** `_refresh_detail()` line 198-199. Replaced conditional `if selected.description: widgets.append(Static(selected.description))` with unconditional:
```python
desc_text = selected.description or "[dim](no description)[/dim]"
widgets.append(Static(desc_text, markup=True))
```

**Test pattern:** `_PickerApp(App)` minimal host (not HermesApp — VarSpec crash). Set `picker._candidates` and `picker._selected_candidate = lambda: candidate` INSIDE the `async with run_test()` block (on_mount wipes state). Call `_rebuild_list()` / `_refresh_detail()` + `await pilot.pause()`. Read `Static.content` (not `.renderable`). Use `picker.query("#picker-right Static").results(Static)` to iterate detail pane widgets.

**Gotcha — `option_list.get_option("id").prompt`:** returns the Rich markup string, not rendered text. `"[dim]—[/dim]" in str(...)` works for assertion. Index 0 is the source-group header (disabled Option); use `get_option(id=name)` to skip it.

## Changelog — 2026-04-28 — CWD Display in StatusBar CWD-1..CWD-4 — 17 tests, commit `7b365bc97`, branch `feat/textual-migration`

**Spec:** `/home/xush/.hermes/spec-cwd-statusbar.md`. Three files touched: `app.py`, `services/bash_service.py`, `widgets/status_bar.py`.

**CWD-1:** `status_cwd: reactive[str] = reactive("")` added after `status_model` in HermesApp class body. `_set_workspace_tracker` sets it via `import os as _os; self.status_cwd = _os.getcwd()` (local import pattern — `os` is not at module level in app.py).

**CWD-2:** BashService gains `_bash_cwd: str = os.getcwd()` in `__init__`. `_exec_sync` replaces `shlex.split` + bare `Popen(args)` with `Popen(["sh", "-c", wrapped], cwd=self._bash_cwd)` where `wrapped` appends `printf '%s%s\n' _CWD_SENTINEL "$(pwd)"` after the command. Reader loop strips sentinel lines (skips push_line); extracts the CWD path and passes it as `new_cwd` to `_finalize`. `_finalize` gains `new_cwd: str | None = None` kwarg — updates `_bash_cwd` and `self.app.status_cwd`. `import shlex` removed (no longer used).

**CWD-3:** `import os` added to `status_bar.py` (was absent). `render()` computes `cwd_basename = os.path.basename(_raw_cwd) or _raw_cwd` (fallback for root `/`). In `width < 40 or (compact and width < 70)` branch: CWD omitted. In `width < 60` and `else` branches: `cwd_basename` prepended before model with `" · "` separator.

**CWD-4:** `StatusBar.on_mount()` gets `self._cwd_changed_at: float = 0.0` and `self.watch(app, "status_cwd", self._on_cwd_change)` after the model watcher. `_on_cwd_change` mirrors `_on_model_change`: records timestamp, calls `self.refresh()`, sets 2.1s timer to re-dim.

**Test gotchas:**
- `_tok_s_displayed` is a Textual reactive on StatusBar — set via `bar.__dict__["_tok_s_displayed"] = 0.0` to bypass descriptor (not direct attr assignment).
- Bound method identity check `fn is svc._finalize` fails (creates new bound-method object each access) — use `fn.__name__ == "_finalize"` instead.
- `_render()` helper assigns read-only Textual `app`/`size`/`content_size` properties using `bar.__class__.prop = property(lambda s: val)` on the isolated subclass — must do this INSIDE the render call, not in `_make_bar`.
- StatusBar `render()` reads many app attrs via `getattr(app, "attr", default)` so the app stub only needs to provide the attrs actually tested; missing attrs fall through to their defaults.

---

## Changelog — 2026-04-28 — Perf Instrumentation Gaps PM-04..PM-12 — f645f4e73, 27 tests

### measure() now auto-records to PerfRegistry
`perf.py`: `measure()` context manager now calls `_registry.record(label, elapsed_ms)` in its `finally` block. Every `with measure("label", ...)` call is automatically recorded under the label key in the module-level `_registry`. No need for explicit `_registry.record()` calls alongside `measure()` blocks. Note: `_registry` is defined later in the same module — safe because the `finally` body only runs at call time, not at import.

### PM-04: io.consume_output per-chunk timing
`services/io.py`: Hot path wrapped with `measure("io.consume_chunk", budget_ms=8.0, silent=True)`. Inner `measure("io.engine_feed", budget_ms=4.0, silent=True)` around `engine.feed(chunk)` (only entered when engine is not None). Also preserves existing `_seq` debug counter. All three measures use `silent=True` — no per-chunk log noise; `_registry` still records every sample.

### PM-05: Startup wall-clock logging
`app.py`: `HermesApp.__init__` gains `_mount_start_monotonic: float = 0.0`. `on_mount` sets `self._mount_start_monotonic = _time.monotonic()` on first line; logs `[STARTUP] mount_ms=...` at the very end (before `_RESIZE_DEBOUNCE_S`).
`widgets/message_panel.py`: `import time as _time` added. `on_mount` reads `getattr(self.app, "_mount_start_monotonic", 0.0)` before calling `ev.set()`; if non-zero, logs `[STARTUP] panels_ready_ms=...` via `_log.debug`.

**Gotcha:** The guard `if _t0 > 0.0` skips the log in test contexts where `HermesApp.on_mount` hasn't fired (so `_mount_start_monotonic` stays 0.0).

### PM-06: Panel refresh isolation
`services/io.py`: `panel.refresh(layout=True)` now wrapped with `measure("io.panel_refresh", budget_ms=6.0, silent=True)` inside the outer `measure("io.consume_chunk")` block. Budget intentionally tighter than outer (6ms vs 8ms) — when both fire simultaneously, it means the refresh alone exceeded the total budget, which is the signal we want.

### PM-07: Tool adoption gap (GENERATED→STARTED latency)
`services/tools.py`: `ToolCallViewState` gains `gen_created_at: "float | None" = None`. `open_tool_generation` passes `started_at=now, gen_created_at=now` explicitly (reusing the already-captured `now = _time.monotonic()` at line 1074 — no second call). `start_tool_call` adopted path replaces `view.started_at = _time.monotonic()` with `view.started_at = now` (reuses the existing `now` captured at line 1206), then logs `[TOOL-ADOPT] <name> gap_ms=...` at DEBUG and `[TOOL-ADOPT-WARN]` at WARNING when gap > 500ms.

**Gotcha:** Do NOT introduce a second `_time.monotonic()` call — both `gen_created_at` and `started_at` must share the same sample to avoid two-sample race.

### PM-08: OutputPanel mount cost
`widgets/__init__.py`: `from hermes_cli.tui.perf import measure` added at module level. `new_message()` wraps the existing `try/except NoMatches` mount block with `measure("output_panel.mount_message", budget_ms=16.0)`. No `silent=True` — fires at most once per turn, acceptable noise.

### PM-09: Path-completion fuzzy rerank
`input/_path_completion.py`: `from hermes_cli.tui.perf import measure` added. `fuzzy_rank(...)` call in `on_path_search_provider_batch` wrapped with `measure("path_completion.fuzzy_rerank", budget_ms=4.0, silent=True)`.

### PM-10: CSS variable lookup
`app.py`: `measure` added to the `from hermes_cli.tui.perf import (...)` block. `get_css_variables()` body wrapped with `measure("css_variables", budget_ms=5.0, silent=True)` — return is inside the `with` block so the measure covers the full method.

### PM-11: Syntax highlighter live measure
`body_renderers/streaming.py`: `from hermes_cli.tui.perf import measure` added at module level. `_highlight_python` body wrapped with `measure("renderer.highlight_line", budget_ms=2.0, silent=True)`. `finalize_code` body (after early-return guards) wrapped with `measure("renderer.finalize_code", budget_ms=20.0)` (non-silent — one-shot at tool completion, acceptable).

### PM-12: Animation render_frame cost
`drawbraille_overlay.py`: Separate `with measure("drawbraille_render", budget_ms=4.0, silent=True)` block added around `self._renderer.render_frame(...)` call. The existing `measure("drawbraille_frame")` for `engine.next_frame()` is left unchanged — two separate blocks, distinguishing math cost from render cost.

### Test patterns (test_perf_instrumentation_gaps2.py)
- **Registry-based "was measure entered" tests**: After `with measure("label", ...)`, check `_registry.stats("label")["count"] == N`. Cleaner than patching `measure` with a side_effect spy.
- **Budget-fire tests**: Patch `hermes_cli.tui.perf.log` and `hermes_cli.tui.perf.time`; set `mock_time.perf_counter.side_effect = [0.0, elapsed_s]`; assert `[PERF]` in warning.
- **silent=True tests**: Patch `perf.log` — assert no `"label"` in captured log messages even after `with measure(label, silent=True)`.
- **Logger capture pattern for PM-05/PM-07**: Add `CapHandler(logging.Handler)` to the module's logger, run the code path, then remove the handler. Avoids patching and works with any logging level.

## Changelog — 2026-04-28 — Deferred renderer swap pre-mount race fix

**Bug**: First web_search tool call in a response rendered raw JSON instead of SearchRenderer output.

**Root cause**: `_swap_renderer()` in `_completion.py` silently returned when `self._body_pane is None`. `_body_pane` is set in `compose()`, but `set_result_summary_v4` → `_update_kind_from_classifier` → `_swap_renderer` can fire before compose has run on the first call.

**Fix**:
- `ToolPanel.__init__`: Added `self._pending_renderer_swap: tuple[type, Any, Any] | None = None`
- `_swap_renderer`: When `_body_pane is None`, store `(renderer_cls, payload, cls_result)` in `_pending_renderer_swap` instead of `return`ing
- `ToolPanel.on_mount`: After existing mount logic, consume `_pending_renderer_swap` and call `_swap_renderer` with stored args

**Gotcha**: The "1st call" pattern is the giveaway — every first fast-completing tool in a response hits this race because `open_streaming_tool_block` → mount → compose is batched async, and `complete_tool_call` can arrive in the same event batch.

**Tests added** (`test_tool_panel.py`):
- `test_swap_renderer_deferred_when_body_pane_none` — unit: pre-compose call stores pending swap
- `test_swap_renderer_deferred_applied_on_mount` — integration: pending cleared after on_mount

## Changelog — 2026-04-28 — Audit Followup M-1/M-2/L-1 — log hygiene + mount budget gate

**Spec:** `/home/xush/.hermes/2026-04-28-audit-followup-spec.md` (Status: IMPLEMENTED). Commit `2b5bb388c`, branch `worktree-audit-followup-m1-m2-l1` → merged to `feat/textual-migration`.

**M-1 (`watchers.py`)**: `on_approval_state` ENTER trace (WARNING) downgraded to DEBUG with `_approval_state_seen` guard: initial reactive fire-through (`value=None`, first call) returns early and logs at DEBUG only. Post-present diagnostic block at lines 416–424 also downgraded WARNING→DEBUG. `_approval_state_seen: bool = False` declared in `WatchersService.__init__`.

**M-2 (`kitty_graphics.py`)**: Added `import errno` + module-level `_tty_unavailable: bool = False` latch. All three probe sites (`_cell_px`, `_apc_probe`, `_sixel_probe`) now check errno on failure: ENOTTY/EBADF/EINVAL/25 sets the latch + logs INFO once; real errors (EIO etc.) still log debug+traceback. Subsequent calls short-circuit silently. Cache note: `_cell_px_cache` must be reset alongside `_tty_unavailable` in test teardown — the latch causes `_cell_px()` to return (10, 20) which gets cached; resetting only the latch leaves a stale cache.

**L-1 (`app.py`)**: Added 500ms soft gate on `_mount_elapsed_ms`. Fast mounts (≤500ms) stay at DEBUG; slow mounts produce WARNING in errors.log. Threshold matches PM-07 adoption gate for consistency.

**Testing patterns**:
- M-1: `WatchersService` instantiated via `object.__new__`; patch `hermes_cli.tui.services.watchers._log`. Wire `_get_interrupt_overlay` to return a proper mock overlay for the "no WARNING" test — returning `None` correctly triggers the "InterruptOverlay not mounted" WARNING for non-None state (that WARNING intentionally stays).
- M-2: Patch `fcntl.ioctl` / `termios.tcgetattr` to raise `OSError(errno.ENOTTY, ...)`. In xdist workers, `sys.stdin.fileno()` raises before `tcgetattr` in `_apc_probe` — patch `hermes_cli.tui.kitty_graphics.sys.stdin.fileno` to return 0. Teardown must reset **both** `kg._tty_unavailable = False` AND `kg._cell_px_cache = None`.
- L-1: Conditional logic tested directly with `patch.object(app_mod, "logger")` + `patch.object(app_mod, "_time")` — HermesApp cannot be run in Pilot (VarSpec crash). Regression gate uses minimal `App(CSS="")` subclass.

## Changelog — 2026-04-28 — H-1 timer cleanup + H-2 stream warning downgrade

**Spec:** `/home/xush/.hermes/2026-04-28-h1-h2-fix-spec.md` (Status: IMPLEMENTED). Commit `7ed7c0c44`, branch `fix/h1-h2-audit-fixes` → merged to `feat/textual-migration`.

**H-1**: `ExecuteCodeBlock.complete()` and `WriteFileBlock.complete()` referenced `_spinner_timer` (deleted in CU-1 sweep). Bare `except Exception` swallowed the `AttributeError`, preventing `_duration_timer.stop()` from running on every `complete_tool_call`. Fix: replace the manual 3-call try/except block with `self._stop_all_managed()` in both files — matching `StreamingToolBlock.complete()`. `_render_timer` and `_duration_timer` are registered via `_register_timer` in `StreamingToolBlock.on_mount` (inherited), so `_stop_all_managed` covers them idempotently.

**H-2**: `LiveLineWidget._commit_lines` logged the engine-missing race at `WARNING` on every cold-start, polluting `errors.log`. The path is documented/recovered (Streaming Exception Sweep H4). Downgraded to `DEBUG`; message now includes `"engine missing on first chunk"` and spec reference.

**Testing patterns**:
- H-1 unit tests: directly instantiate `ExecuteCodeBlock`/`WriteFileBlock`, pre-set `_code_state = _STATE_FINALIZED` to skip `finalize_code()`, patch `_stop_all_managed` to assert called once. **query_one mock must raise `NoMatches`, not bare `Exception`** — `complete()` only catches `NoMatches` for the cursor lookup.
- H-2 tests: reuse `_make_live_widget_with_panel()` helper from `test_streaming_exception_sweep.py`; set `_buf = "line\ntail"` (needs `\n` for `_commit_lines` to process complete lines).
- Three pre-existing tests in `test_streaming_exception_sweep.py` needed updates: `test_commit_lines_buffers_and_writes_directly_when_engine_missing` (warning→debug), `test_commit_lines_caps_buffer_but_keeps_direct_writes` (same), and `TestMetaSweepSitesHaveLogging.test_streaming_exception_sweep_sites_have_logging` (assert `_log.debug(` + `"engine missing on first chunk"`).

## Changelog — 2026-04-28 — R2-H1 ThinkingWidget hex-color validation — 6 tests, commit `ad2506dd2`, branch `feat/textual-migration`

**Spec:** `/home/xush/.hermes/2026-04-28-r2h1-thinking-color-fix-spec.md` (Status: IMPLEMENTED).

**Root cause:** `ThinkingWidget._refresh_colors` read `text` CSS variable via `app.get_css_variables()`. Textual's default theme resolves `text` to `"auto 87%"` (not a hex color). The old code stored `"#auto 87%"` in `_text_hex`, which crashed `_parse_rgb("auto 87%")` at `int(s[0:2], 16)` 6 times per turn. The exception was swallowed at DEBUG by `tick_label`'s outer try/except — widget appeared unstyled but no crash. Same class of defect as H-1 (input-boundary validation failure invisible to tests).

**Fix:** Module-level `_normalize_hex(value, default)` with `_HEX_COLOR_RE = re.compile(r"^#?(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")`. Returns lowercased 6-char hex or default. Replaces bare `except Exception: pass` with `logger.warning(..., exc_info=True)` + reset to defaults. Updated class-level defaults to reference module constants (`_DEFAULT_ACCENT_HEX`/`_DEFAULT_TEXT_HEX`).

**New API:** `_HEX_COLOR_RE`, `_DEFAULT_ACCENT_HEX`, `_DEFAULT_TEXT_HEX`, `_normalize_hex` — all module-level in `thinking.py` near `_DEFAULT_EFFECT` (line ~70 area). `import re` added to imports.

**Logger name in `thinking.py`:** `logger` (8 call sites), NOT `_log` — there's an alias `_log = logger` at line 32 but `logger` is the primary name.

**`app` property mock pattern for `ThinkingWidget` tests:**
```python
class _ThinkingWithMockApp(ThinkingWidget):
    _mock_app: object = None
    @property
    def app(self):
        return self._mock_app

widget = _ThinkingWithMockApp.__new__(_ThinkingWithMockApp)
widget._mock_app = MagicMock()
widget._mock_app.get_css_variables.return_value = {...}
```
Direct `widget.app = mock` raises `AttributeError: property 'app' of 'ThinkingWidget' object has no setter`. DO NOT use `PropertyMock` on `type(widget)` — leaks across pytest session. Use isolated subclass cached at module scope.

**`caplog` logger name for `thinking.py`:** `"hermes_cli.tui.widgets.thinking"`. Use `caplog.set_level(logging.WARNING, logger=...)` + check `caplog.records` for warnings. `caplog.at_context(...)` is not a reliable alias — prefer `set_level`.

**`_normalize_hex` 3-char shorthand expansion:** `"#abc"` → `"#aabbcc"` (each char doubled). Expansion happens AFTER regex validation; the regex passes both 3-char and 6-char. Downstream `_parse_rgb` only handles 6-char — expansion is required.

**Behavior on `get_css_variables()` raising:** WARNING logged (not DEBUG — failure during normal app operation could mask real Textual regression); both fields reset to `_DEFAULT_ACCENT_HEX`/`_DEFAULT_TEXT_HEX`. Prior behavior left stale values; new is always-deterministic on failure.

## Changelog — 2026-04-28 — R4-T-H1 TTE banner race — threading.Event gate — 5 tests, commit `151530770`, branch `worktree-r4-th1-tte-banner-race`

**Spec:** `/home/xush/.hermes/2026-04-28-r4-th1-tte-banner-race-spec.md` (Status: IMPLEMENTED).

**Root cause:** `HermesCLI._play_tte_in_output_panel` (daemon startup thread) called `app.call_from_thread(_drain_latest)` which immediately tried `app.query_one(StartupBannerWidget)`. On cold mount the daemon thread raced `OutputPanel.compose()` by ~3 ms, emitting 2× WARNING + 1× CancelledError WARNING = 108 log lines per boot into `errors.log`. Only caught by the tmux real-PTY harness; Pilot bypasses the CLI banner-worker entry path.

**Fix pattern:** Module-level `threading.Event` (`STARTUP_BANNER_READY`) set in `StartupBannerWidget.on_mount`, cleared in `on_unmount`. Producer calls `STARTUP_BANNER_READY.wait(timeout=2.0)` before first `_queue_frame`. `_drain_latest`'s `except Exception` narrowed to `except NoMatches` at DEBUG. Frame-loop's `except Exception` split: `concurrent.futures.CancelledError` → DEBUG; rest → WARNING.

**New API:** `STARTUP_BANNER_READY: threading.Event` — module-level in `hermes_cli/tui/widgets/__init__.py` (before `StartupBannerWidget` class). `import threading as _threading` added to top-level imports. `import concurrent.futures` added to `cli.py` after `import threading`.

**Test gotchas:**
- `threading.Event` is module-level state → `autouse` fixture must call `STARTUP_BANNER_READY.clear()` before AND after each test.
- `app.call_from_thread` receives the async **function**, not a coroutine — capture as `captured_fns[0]` then call `asyncio.run(captured_fns[0]())`.
- Run `asyncio.run(coro())` INSIDE the `with patch("cli.logger"):` block — closure resolves `logger` via module globals at call time, not at closure-creation time.

## Changelog — 2026-04-28 — UX Audit A — Skin/visual hierarchy consistency (A1–A6) — 12 tests, commit `d72ff0c07`

**Spec:** `/home/xush/.hermes/2026-04-28-ux-audit-A-skin-hierarchy-consistency-spec.md` (Status: IMPLEMENTED).

**Changes:**
- `app.py`: dropped dead `effects_enabled`, `idle_effect`, `glitch_enabled` kwargs from `AssistantNameplate` construction (they were `getattr`-with-defaults never overridden anywhere).
- `widgets/__init__.py` `AssistantNameplate.on_mount`: replaced `if not self._effects_enabled: return` guard with `if self.styles.display == "none": return`. CSS var setup block (lines 821–839) must still run for hidden widgets — guard goes AFTER that block.
- `hermes.tcss` chevron: added `opacity` to `#input-chevron` base (0.55) and all 5 phase rules (`--phase-done` 0.55, `--phase-stream`/`--phase-file`/`--phase-shell` 0.85, `--phase-error` 1.0). Transition now includes `opacity`.
- `theme_manager.py` + `hermes.tcss`: new `$reasoning-accent` (#0178D4) skin token; 3-edit rule applied (COMPONENT_VAR_DEFAULTS + tcss declaration + all 4 skins). `ReasoningPanel` gutter updated to `vkey $reasoning-accent 60%`.
- `hermes.tcss` category accents: tiered opacity rule (Critical file/shell/vision→80%, Primary web/mcp/code→60%, Utility search/agent→40%); added documentation comment block. code/web/mcp moved from 80%→60%.
- `hermes.tcss` `.error-banner`: replaced hardcoded `#cc3333` with `$error` token.

**Key gotcha — `_idle_beat_timer` vs `_timer`:** `_idle_beat_timer` is only set when the state machine cycles to IDLE (`_enter_idle_timer()` at lines 1000/1042). For tests that check whether animation started, assert `_timer is not None` (set directly in `on_mount` at line 843). Asserting `_idle_beat_timer` for the visible case always fails trivially; for the hidden case, always passes trivially — neither test would validate the guard.

**Skin YAML structure for component-vars:** In all 4 bundled skins, keys live under `x-hermes.component-vars` in the YAML front-matter. Test must load the front-matter via regex `^---\n(.*?)\n---` (re.DOTALL), then navigate `data["x-hermes"]["component-vars"]`.

## Changelog — 2026-04-28 — UX Audit B — Density/Truncation fixes (B1–B5) — 14 tests, commit `af966de5a`

**Spec:** `/home/xush/.hermes/2026-04-28-ux-audit-B-density-truncation-spec.md` (Status: IMPLEMENTED).

**Changes:**
- `layout_resolver.py` `_DROP_ORDER_COMPACT`: moved `duration` before `hero` so human summary outlives digit decoration in tight COMPACT rows.
- `layout_resolver.py` `resolve_full()`: footer now visible during streaming when `is_error AND has_footer_content` — allows mid-stream error messages through. Non-error streaming still hides footer.
- `_streaming.py`: added `import os`; `_SKELETON_DELAY_S` now read from `HERMES_TOOL_SKELETON_DELAY_MS` env var (default 100ms, ValueError fallback warning). `on_mount` wraps skeleton timer in `if _SKELETON_DELAY_S > 0.0:` guard.
- `_shared.py` `OmissionBar.on_resize`: narrow viewports now show `↓NL↑` abbreviated label instead of hiding; `toggle_class("--narrow", now_narrow)` added. `set_counts`: narrow branch shows abbreviated label via `self._narrow`.
- `hermes.tcss`: added `OmissionBar.--narrow .--ob-label { width: auto; }` so abbreviated label doesn't get eaten by 1fr constraint.
- `_header.py` `ToolHeader.__init__`: `_truncated_line_count: int = 0` added. `_render_v4` linecount branch: when `_truncated_line_count > 0`, appends `[trunc:N]` badge in `dim {warning_dim}` style.
- `_streaming.py` `complete()`: syncs `self._header._truncated_line_count = self._truncated_line_count` after `_line_count` sync.

**Test gotchas:**
- `OmissionBar.__new__` + manual attrs works for label-update tests, but `set_counts` calls `query_one` which needs `_nodes`. Mock `query_one` to raise `NoMatches` — all button branches inside `try/except NoMatches: pass` short-circuit cleanly.
- `Widget.size` is a read-only Textual property. To mock it: create an `_IsolatedSubclass(OmissionBar)`, set `ob.__class__ = _IsolatedSubclass`, then `type(ob).size = PropertyMock(...)`. Clean up with `del type(ob).size` in finally block to prevent session leakage.
- `Rich Text.style` is a plain `str` (e.g. `'dim #5C4A00'`), not a Style object — use `str(text.style)` for substring assertions.
- B3 env-var tests: must `del sys.modules[mod_name]` before re-importing to force module-level code to re-execute with the patched env.
- `_render_v4` calls `self.has_class()`, `self.styles.height`, `self.size.width`, etc. — too tightly coupled to Widget context for pure unit tests. Use source inspection (`inspect.getsource`) as structural guard + replicate the segment-building logic directly in tests.

## Changelog — 2026-04-28 — Config Panel Fix CO-H1/H2/M1/L1 — 19 new tests + 1 updated, commit `7630237b3`, branch `feat/textual-migration`

**New APIs / changed behaviour:**
- `ConfigOverlay._focus_active_tab()` — focus map for tab → widget id; called after `add_class("--visible")` in `show_overlay()` so `call_later` fires AFTER layout completes. `except NoMatches: pass` is valid here (before compose).
- `ConfigOverlay._refresh_active_tab()` — dispatches to per-tab refresh helpers; `if not self._snap_css_vars` guard prevents overwriting open-time CSS snapshot with previewed state on re-entry.
- `ConfigOverlay._last_cli: object = None` — stores last cli object for deferred tab-switch refresh.
- `ConfigOverlay.watch_active_tab()` — now guards `_refresh_active_tab()` + `_focus_active_tab()` behind `self.has_class("--visible")` to avoid stale-populate when tab changes while hidden.
- `CommandsService._TAB_FOR_CMD` — added `"/syntax": "syntax"` entry.

**Gotchas:**
- `Widget.focus()` uses `call_later` — deferred to next event tick. Focus assertions MUST `await pilot.pause()` first.
- `Widget.visible` checks CSS `visibility` rule, NOT `display`. `display:none` does NOT set `visible=False`.
- `patch.object(widget, "app")` FAILS — `app` is a Textual read-only property. Patch `widget.query_one` instead.
- `except Exception: pass` with an explicit comment IS compliant. AST sweeps that flag all bare-pass swallows will false-positive on best-effort flash-hint sites.
- Test `test_tab_state_preserved_across_switch` updated: CO-H2 intentionally refreshes the list on tab switch (old "preserve manual highlight" expectation was the pre-fix buggy behavior).

### 2026-04-28 — UX Audit F — Overlays/Polish F2–F8 — 14 tests, commit `917194b2f`, branch `feat/ux-audit-f-overlays-polish`

**Spec:** `/home/xush/.hermes/2026-04-28-ux-audit-F-overlays-polish-spec.md`. 3 production files + 14 tests.

**Gotchas:**
- `VirtualCompletionList` unit-testing without app: `size`, `scroll_offset`, and `app` are all read-only Textual `property` instances on Widget/ScrollView. Shadow them at the subclass's **class body** level (as plain class attributes), NOT in `__init__`. Assigning to them in `__init__` after `super().__init__()` is skipped still raises `AttributeError: property has no setter`.
- Textual reactive descriptors require `_id` on the object (set by `super().__init__()`). To bypass: shadow each reactive as a plain class attribute in the subclass before instantiation — `class _Stub(VCL): items = tuple()`. This makes Python find the plain value before the descriptor.
- `Static` stores its content as `_Static__content` (Python name-mangling of `self.__content`). There is no `.renderable` property in Textual 8.x. Use `getattr(widget, '_Static__content', '')` to inspect Static content in tests.
- TCSS block extractor pitfall: `"ToolPanel:focus"` appears in a comment `/* ... keep in sync with ToolPanel:focus below */` and in `"ToolPanel:focus _CollapsedActionStrip { ... }"`. A naïve line-scan matcher hits both before the real standalone block. Fix: skip lines that start with `/*`/`*` during selector search, AND require the selector fragment is not followed by whitespace+element (descendant combinator pattern).
- `MagicMock.mount.side_effect = lambda *w, **kw: list.extend(w)` — use `side_effect` not attribute replacement; replacing `mount` with a plain function loses `.call_args_list` tracking.

### 2026-04-28 — services/feedback Audit FB-H1..FB-L2 — 20 tests, commit pending, branch `worktree-feedback-service-audit`

**Spec:** `/home/xush/.hermes/2026-04-28-feedback-service-audit-spec.md`. 2 production files + 1 test file.

**New APIs / changed behaviour:**
- `ExpireReason.SUPPRESSED` — new value; fired when settled-suppression blocks a flash without ever displaying it. Callers' `on_expire` now distinguishes "blocked by priority" (no callback) from "blocked by settled" (SUPPRESSED).
- `SettledAware` Protocol (runtime_checkable) in `services/feedback.py` — `is_settled() -> bool`. Replaces the prior `getattr(_widget, "_settled", False)` literal in `flash()`. Widgets opt in by structural conformance (not by inheriting the protocol — would force a circular import from `tool_blocks` → `services`).
- `_widget_is_settled(widget)` — module-level helper; sole reader of the SettledAware contract.
- `_STATE_CHANGE_TONES: frozenset[str] = {"focus", "err-enter"}` — module constant; tones in this set bypass settled-suppression. Add a tone here only when its semantics encode a state change rather than incidental motion.
- `StreamingToolBlock.is_settled()` added (sole production widget that owns `_settled`).
- `CodeFooterAdapter.widget` now resolves to the footer's closest `SettledAware` ancestor (today only `StreamingToolBlock`); cached on first hit. `None` results NOT cached so post-mount walks succeed. `clear_cache()` provided defensively.
- `HintBarAdapter._get_bar` narrowed from `except Exception` (which silently re-wrapped everything as `ChannelUnmountedError`) to `except NoMatches` only — render errors / AttributeError now propagate to the new generic-Exception branch in `flash()` and get ERROR-logged with traceback.
- `flash()` preemption: equal-priority now PREEMPTs (was a silent `_stop_flash_internal` that suppressed `on_expire`). Three-branch `>`/`==`/`<` collapsed to `>=`/`<` plus key-match short-circuit. `_stop_flash_internal` removed (dead code).
- `flash()` apply path: `ChannelUnmountedError` now also calls `adapter.restore()` defensively. New `except Exception` branch logs at ERROR with traceback, calls `restore()`, fires `on_expire(UNMOUNTED)`.
- `register_channel` warns at WARNING on overwrite (with previous/new adapter type names), cancels any active flash on the OLD adapter, and uses a `_registering` set to block re-entrant `flash()` calls during the swap window.

**Gotchas:**
- `@runtime_checkable` Protocol with a single method matches structurally — a `MagicMock` with arbitrary attrs will pass `isinstance(mock, SettledAware)` because MagicMock auto-creates `is_settled`. Tests that need "widget does NOT conform" must use a hand-rolled class without `is_settled()`.
- `CodeFooterAdapter.widget` walks `ancestors_with_self` (Textual DOMNode property — returns `[]` pre-mount, never raises). Tests that fake the footer must provide that attribute.
- Tests for the cache-survives-clear_settled scenario must use a CodeFooterAdapter subclass that no-ops `apply`/`restore` — the real apply requires footer attributes the fake doesn't have, so flash() would fall into the new generic-Exception branch and return displayed=False.
- `_STATE_CHANGE_TONES` exemption is checked via `tone in _STATE_CHANGE_TONES`; promoting tones from inline literal to a frozenset constant is a contract surface — any new tone added must be evaluated for the "state change vs motion" distinction.
- `caplog.at_level(...)` captures specific logger only when given the logger name kwarg — use `caplog.at_level(logging.WARNING, logger="hermes_cli.tui.services.feedback")`.

## Changelog 2026-04-28 — Spec H Focus/Nav (W-1..W-17)

**New APIs / constants:**
- `ScrollState(StrEnum)` — PINNED / ANCHORED / JUMPED — in `widgets/__init__.py`; exported via `from hermes_cli.tui.widgets import ScrollState`
- `OutputPanel.scroll_state: reactive[ScrollState]` — replaces `_user_scrolled_up: bool`
- `OutputPanel.scroll_end_if_pinned()` — centralised scroll-to-bottom gate; all `scroll_end` calls in `services/io.py` and `services/tools.py` replaced with this
- `OutputPanelScrollBadge(Static)` — dock:bottom badge showing "↓ N new" or "↑ jump · End to latest"
- `HINT_MAX_PRIMARY = 3` — in `widgets/status_bar.py`; slices primary hint list
- `EXTENDED_HINT: dict[str,str]` — in `app.py`; zone first-entry hint strings keyed by zone name
- `_zones_first_entry_seen: set[str]` — tracks first zone visits per turn; cleared by `_lc_reset_turn_state`
- `Binding("end", "action_scroll_to_latest", ...)` — added to HermesApp.BINDINGS
- `.--modal` TCSS class — applied to all trapped overlays via add_class("--modal")

**Changed behaviour:**
- `OutputPanel._user_scrolled_up` is now a read-only property backed by `scroll_state`; setter also accepted for backward compat
- `on_scroll_up` sets `scroll_state = ANCHORED`; `on_scroll_down` reverts to PINNED when state was ANCHORED
- Browse scroll paths (`browse.py:scroll_to_tool`, `focus_anchor`) set `scroll_state = JUMPED` before `scroll_to_widget`; F-2 contract means they don't call `.focus()`
- `query_one("#input-area").focus()` replaced with `query_one(HermesInput).focus()` (W-12) at ~5 call sites
- `/clear` and new-turn paths focus `HermesInput` (AT-Z3 contract)

**Test patterns (W-16 invariant tests):**
- AT-B1 scope: only check `app.py` top-level `on_key`/`_on_key` for raw `event.key` reads — widget-local handlers are excluded (they receive already-routed events)
- AT-S1 scope: skip `.scroll_end()` calls where receiver `ast.Name.id` contains `log` (catches CopyableRichLog.scroll_end in `tool_panel/_actions.py`)
- AST receiver extraction: `isinstance(callee.value, ast.Name)` to get the receiver variable name in attribute-call patterns
- Both invariant tests are structural/lint (no pilot/App required) — run in ~2s total
