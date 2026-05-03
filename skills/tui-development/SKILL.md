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

## Reference files

| File | Contents |
|---|---|
| `references/module-map.md` | Module ownership, class names, key APIs, test-to-module map, owner-path groups |
| `references/gotchas.md` | All Textual/hermes gotchas — non-obvious traps, test workarounds, API quirks |
| `references/patterns.md` | Widget rules, reactive patterns, worker patterns, keyboard conventions |
| `references/live-audit.md` | Live audit notes and open questions |
| `references/tmux-audit.md` | TmuxDriver usage patterns and PTY audit harness |
| `skin-reference.md` | Skin YAML schema, palette keys, CSS var mapping |

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

### Startup banner styling

- `StartupBannerWidget` must paint `background: $app-bg` in its own `DEFAULT_CSS`. Do not rely on inherited/default terminal background for the startup banner host; otherwise the left hero/logo cell can fall back to terminal black even when the app chrome uses a themed `app-bg`.
- Keep a mounted-style regression for this contract. `tests/tui/test_visual_properties.py::test_startup_banner_background_equals_app_background` checks the widget background against `HermesApp.styles.background`.
- `ThinkingWidget`, `_AnimSurface`, and `_LabelLine` must all paint the app background, but do it via runtime `styles.background` assignment from the resolved theme/app background, not via `$app-bg` in widget-local `DEFAULT_CSS`. Standalone widget tests instantiate these classes outside the full Hermes CSS variable map; `$app-bg` inside local widget CSS will raise `UnresolvedVariableError`.
- Keep the same mounted-style contract for the thinking stack. `tests/tui/test_visual_properties.py::test_thinking_widget_spinner_background_equals_app_background` checks the host and both mounted children against `HermesApp.styles.background`.
- First-turn assistant rendering is startup-sensitive: markdown / LaTeX only become available after `MessagePanel.on_mount()` installs `ResponseFlowEngine`. `cli.py` therefore gates `agent_running=True` with `_panel_ready_event.wait(...)`; keep that wait generous enough that early stream chunks do not fall back to raw `Text.from_ansi(...)`.
- Session overlay discoverability gotcha (2026-05-02): `ctrl+shift+h` appears dead in some terminals. Use `ctrl+j` as the advertised `open_sessions` binding and keep `ctrl+shift+h` only as a secondary alias. HintBar and `/sessions` `keybind_hint` should advertise `Ctrl+J`.

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

### SkillPickerOverlay (`overlays/skill_picker.py`)

- Mounted with `app.mount(SkillPickerOverlay(...))` as a plain `Widget`, not `push_screen()`. It must own a widget-level `dismiss()` helper; do not call screen-style dismissal APIs on it.
- Canonical close path: remove `--modal`, `remove()` the widget when mounted, then restore `HermesInput` focus. Route `Esc`, auto-dismiss, and input-side teardown through that helper.

### ConfigOverlay (`overlays/config.py`)

- Skin preview and skin confirm must route through `HermesApp.apply_named_skin()` / `ThemeService.apply_named_skin()`, not raw `ThemeManager.load_skin()`. `load_skin()` only refreshes CSS; the service path also refreshes cached live skin consumers such as completion UI, tool blocks, streaming code blocks, and message/reasoning panels.

### Widget overlay close API

- For pre-mounted Textual `Widget` overlays, expose a public `dismiss()` helper even when bindings route through `action_dismiss()`.
- Standard contract: `dismiss()` is a thin wrapper that delegates to `action_dismiss()`. This gives external callers a stable close API without changing Textual action bindings.
- Use the wrapper for generic overlay-teardown code when the concrete widget type may vary. Reserve screen-style dismissal APIs for actual `Screen`/`ModalScreen` classes only.

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
- **`/anim ambient <engine>`**: always call `ov._orchestrator.set_ambient_engine(key)` — NOT `ov._current_engine_instance = _ENGINES[key]()`. Direct mutation leaves `_current_engine_key` and `_carousel_key` stale. (ANIM-API-1, commit 520a48b7c)
- **`Torus3DEngine` LUTs**: `_THETA_LUT`/`_PHI_LUT` are precomputed with magic literals (class-scope rule). `__init__` asserts `len(_THETA_LUT)==N_U` and `len(_PHI_LUT)==N_V`. Changing `N_U`/`N_V` without updating the list comprehension raises `AssertionError` at construction. (ANIM-API-2)
- **`AnimConfigPanel._cycle`**: guards `f.choices.index(str(f.value))` with `try/except ValueError` — unknown value defaults to index 0. Missing guard crashes the key handler. (ANIM-API-3)

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

**New component var always requires 2 edits**: (1) `COMPONENT_VAR_DEFAULTS` in `theme_manager.py`, (2) `$name: value;` declaration in `hermes.tcss` when the var is `$`-referenced at parse time. Bundled skin YAML updates are required only when the key is *not* marked `optional_in_skin=True` via `VarSpec`. T1/T2/T3 in `test_css_var_single_source.py` catch omissions.

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

Compact index. Novel gotchas extracted to `references/gotchas.md`. For full diff see `git show <commit>`.

### 2026-05-03

| Spec | What shipped | Commit | Tests |
|---|---|---|---|
| TB-MED-5/1/2 convergence | swallow comments + chip promotion (`duration_s`/`_promote_drop_order`) + `GroupOverflowChip`/tier cap | `342f08499` | 20 |
| TW-CHROMA | `ThinkingWidget` per-row lerp gradient + hue-shift; `_lerp_hex` in `_color_utils`; 3 new CSS vars | `d2b80af40` | 24 |
| TB-H3+H4 | `THRESHOLDS` dict, `LayoutInputs` pressure/viewport_rows/is_offscreen, `_pressure_band` pure fn, OutputPanel two-pass `_resolve_layout`; IL-11 | — | 17 |
| TB-H2 | `_tool_views_history_by_id` cap=10; `live_by_id`/`history_by_id` helpers; append-then-pop in `_terminalize_tool_view`; preemption routing in `start_tool_call` | `4c5caa2db` | 9 |
| TB-H1 | `ToolGroupState.ERROR→ERR`, `PARTIAL` removed; ERR-sticky + terminal-absorbing in `_recompute_group_state`; IL-10 | `a005da564` | 13 |
| SPEC-MMP-VIEWPORT | `BrowseMinimap` dock:right viewport-pinned; viewport rect bg tint config-gated; scroll observer `self.watch`; MMP-H3/H4/L1 | — | 13+3 skip |
| SPEC-WSO-AUTO | `_workspace_auto_suppressed` flag; `watch_agent_running(False)` auto-shows; `action_dismiss` sets suppression; WSO-AUTO-1/2/3 | `0c60967c3` | 9 |
| SPEC-MMP-LIFECYCLE | `_browse_anchors`/`_browse_cursor` shims on `HermesApp`→`BrowseService`; `_mount_minimap` unified helper; toggle serialized on flag; MMP-M4..M7 | — | 14 |
| SPEC-MMP-RENDER | `_NARROW` glyph map, cursor-wins-collision, last-row tail, accent cache, `_refresh_minimap` 4 sites; MMP-H1..L7 | `064a0e098` | 35 |
| WSO-STAT-1/2/3 | `GitSnapshot.numstat` + `GitPoller` numstat call + `FileEntry` git_added/git_removed + render priority rule | `41c64ea41` | 9 |
| SPEC-MOD-LEG | `ConfigOverlay`+`SessionOverlay`+`HistorySearchOverlay`→`ModalOverlayMixin`; `dismiss_all_info_overlays` fixed; `_dismiss_overlay_and_focus_input` deleted | `e9525f4d1` | 32 |
| SPEC-TTE per-skin | `x-hermes.startup_tte` (effect/wall/frames/fps/params); lazy `EFFECT_MAP` validator; cli resolver precedence; 11 skins authored; default→hermes rename; `_normalize_skin_name` alias | — | 30 |
| widgets/ split | `widgets/` package: `output_panel`, `fps_counter`, `tte_widget`, `startup_banner`, `nameplate`, `_events`; `__init__.py` pure re-export shim | `a18d4676e` | — |
| anim_engines/ split | `anim_engines/` package: `_base`/`_helix`/`_flow`/`_organic`/`_geometric`/`_math`/`_special`/`_composite`; IL-A1 gate updated | `d62cdf076` | — |
| SPEC-SVC | `stop_listener` worker, bash kill logs, orphan cleanup, pane restore log, reduced-motion cache, atomic `KNOWN_SKILLS`, `HintBar` flash timer, `OutputJSONLWriter` append+rotate, deferred skin refresh, CSS flatness guard | — | 26 |
| SPEC-ASS | `assist` reactive, single-write-site `_resolve_assist`, PICKER chrome, AutoDismiss bubble, legend/placeholder fixes | `3faa810a5` | 33 |
| SPEC-CSS | Diagnostic logging at `get_css_variables()` swallow sites; IL-S1 | `f2ab0fe46` | 14 |
| SPEC-STR | `_reset_fence_state` helper, partial-detach guard, footnote cap fix, CSI debug log, reasoning CSS race, TTE tick guard, classifier 50ms+64KB, unicode escape log, citation overflow display, double-emit reset, resize cache guard, pacer finalize wrap, TTE cache disable-for-run | `074f6d293` | 27 |
| SPEC-TBM | sniff cap, `_set_view_state` recursion guard, `_clear_streaming_kind_hint` helper, queue/replay layout, O(1) renderer lookup | — | 21 |
| SPEC-MOD | `ModalOverlayMixin` + `_modal_stack`; 5 overlay migrations; IL-M1 gate; `super.on_unmount`, browse-target lazy capture, dismiss order, dup escape bindings, `super.on_mount` fixes | `e4b48e7b9` | 32 |
| SPEC-ANM | per-call locals in `_layer_frames`, `lru_cache`, perf probe, IL-A1 gate | — | 12 |
| SPEC-TBC | `ToolCallHeader` deleted, `_swap_renderer` fallback, slow-renderer deadline, parent-walk fix, copy key c, `set_user_kind_override` helper | `509188324` | 29 |
| SPEC-WRK | `@work(thread=True)` bodies try/except; `_subscriber_failures`; `_failsafe_disable`; `_reveal_failure_count`; `_pool_starvation_count`; IL-W1 lint gate | `3fa0befce` | 29 |
| Builtin skins | `_BUILTIN_SKINS` deleted; 11 `DESIGN.md` files in `hermes_cli/skins/`; `_bundled_skins_dir()`/`_bundled_default_payload()`; `_resolve_skin_path`; voice-status keys | `b7be249c0` | — |
| Output pane P0-B/P1-B/P1-E | `CopyableRichLog._wws_active` flag; direct `write()` plain capture before deferred branch; `_EchoBullet` expand/collapse | — | 24 |

**Key new APIs (2026-05-03):** `_lerp_hex(hex_a, hex_b, t)` in `_color_utils`; `set_user_kind_override(id, kind)` in `services/tools.py`; `LayoutInputs.pressure/viewport_rows/is_offscreen`; `THRESHOLDS: dict[str, int]` in `density.py`; `_tool_views_history_by_id` (cap=10); `ToolGroupState.ERR` (renamed from `PARTIAL`); `ENGINES: dict[str, type]` (replaces `_ENGINES`) in `anim_engines/__init__.py`; `DrawbrailleOverlayCfg` only in `drawbraille_overlay.py` (engines in `anim_engines/`).

### 2026-05-02

| Spec | What shipped | Commit | Tests |
|---|---|---|---|
| WAR cascade | dedup signal, hoist `_output`, defer evict/browse/TurnCompleted, rm dup `_sync_workspace`, `signal_on_show` param | `71535171a` | 12 |
| Clipboard | OSC 52 primary path + `osc52.py` + `_primary_selection_cmd()` Wayland-aware paste + unified copy service | `a5806f2bb` | 22 |
| Config model/provider picker | provider `OptionList` in model tab, `provider_model_ids()`, `/model --provider` flag | — | — |
| TTE frame disk cache | `_tte_cache.py` + cache-hit fast path; SHA-1[:14] key; gzip+pickle; write-back thread | — | 52 |
| TTE streaming producer | streaming producer thread eliminates 10-20s blank screen; `_PREFETCH_FRAMES=15` | — | 14 |
| OutputPanel live-output suffix | `[LiveLineWidget, ThinkingWidget]` order — ThinkingWidget at bottom | — | — |
| ThinkingWidget gradient randomization | per-render randomized gradient | — | 16 |

### 2026-05-01

| Spec | What shipped | Commit | Tests |
|---|---|---|---|
| Startup banner polish | `_first_input_seen` collapses 250ms post-TTE hold; `_use_compact_banner()` prefers OutputPanel width; hero gradient line-granular; hero width cached per skin via `register_skin_callback()`; `width: 100%` on `StartupBannerWidget` | — | 57 |
| Startup TTE config/diagnostics | `startup_text_effect` adds `max_wall_s`/`max_frames`/`fps`; `_StartupTteConfig`; loop-teardown `RuntimeError`→DEBUG; missing TTE logs INFO once | — | 66 |
| HintBar startup HS-1/HS-2 | `render()` stale-shimmer guard + `set_phase`/`on_streaming_change` creation guards | `6b448e60b` | 11 |
| Banner truncation BT-1..BT-3 | `…+N more` everywhere, `_format_session_id` tail-cap, `_format_cwd` tilde+elision | `83ed4ae02` | 14 |
| Banner hierarchy BH-1/2/3 | `_section_break` rule, warn orange-red, dismiss badge row | `a94eca185` | 13 |
| Composer/status CS-1/CS-2 | placeholder sep, idle bar hide (`pct_int>=1` gate) | — | 8 |
| Banner layout BL-1..BL-4 | logo row-gate + wordmark fallback, sigil padding, summary stat hoisted, hero 3-tone gradient | — | 16 |
| ANIM-API-1..3 | ambient→orchestrator, Torus3D LUT assert, `_cycle` ValueError guard | `520a48b7c` | 19 |
| ANIM-TIMER-1..4 | `on_unmount` leaks, `AnimParams` t=0 freeze, `watch_fps` hidden restart, lambda no-op timers | `4101da15b` | 13 |
| Screenshot audit SS-1..SS-10 | em-dash fallback, stall glyph, `ThinkingWidget height:auto`, banner ack, legend verbs, ctx suffix+uppercase, skill list chip, nameplate tier accent, session copy, `/model` inline | `ca40c63c2` | 34 |
| ANIM-EH-1..5 | `drawbraille _log` + `on_signal` log + `on_blur` comments + `_do_save` secondary log + `_layer_frames` threading guards | — | 9 |

### 2026-04-28

| Spec | What shipped | Commit | Tests |
|---|---|---|---|
| feedback FB-H1..FB-L2 | equal-priority PREEMPTED, apply-failure restore, `SettledAware` Protocol, `CodeFooterAdapter`, register_channel guard, `_STATE_CHANGE_TONES` | — | 20 |
| Composer concept G | `MODE×KIND×ASSIST` frame; `_resolve_assist()`; `_completion_overlay_active`; locked stash/restore; exception sweep; invariants | `1eabbdfab` | 33 |
| Focus/Nav spec H | `ScrollState` tri-state, `--modal` overlays, `scroll_end_if_pinned`, AT-* lint tests | — | 13 |
| UX Audit A | nameplate anim + chevron + `$reasoning-accent` + tier table + `$error` banner | `d72ff0c07` | 12 |
| UX Audit B | `DROP_ORDER`, streaming error footer, skeleton env-var, `OmissionBar`, linecount badge | `af966de5a` | 14 |
| UX Audit C | collapsed remediation hints, compact `Tab suggest`, `SessionBar` `S` hint, dynamic header tooltip, `SkillPicker` action copy | `351361ec1` | 17 |
| UX Audit D | searching label + fence-open cue + `OutputPanel` bindings | `823895d04` | 8 |
| UX Audit E | `result-empty` class, height:auto error, ^C hint, KEY_* sweep | `cc428df73` | 11 |
| UX Audit F | countdown, badge, empty-state, border, opacity, focus-ring, max-height% | `917194b2f` | 14 |
| Config panel CO-H1/H2/M1/L1 | focus on open + tab refresh + 3 swallow logs + /syntax routing | `7630237b3` | 19 |
| R5-T-M1 ThinkingWidget repr leak | `render()` override returning empty `RichText("")` | `e3382c33b` | 4 |
| R4-T-H1 TTE banner race | `STARTUP_BANNER_READY` event + `wait(2s)` gate | `151530770` | 5 |
| R3 panel.id + feedback + ks-context | `panel_id` kwarg + `_move_panel_channel` + kitty latch | `f0fdf63ff` | 14 |
| tmux audit driver TM-1/TM-2 | `TmuxDriver` ctx-mgr in `tools/tui_audit/`; real-PTY complement to Pilot | `10f8d3b51` | — |
| R2-H1 ThinkingWidget color fix | `_normalize_hex` + `_DEFAULT_*_HEX`; `get_css_variables()` exception→WARNING | `ad2506dd2` | 6 |
| EH-A..EH-E exception sweep | ~377 bare swallows; 59 files | `00954d743` | 82 |
| PM-04..PM-12 perf gaps | `measure()` auto-records to `PerfRegistry`; 9 probe sites | `f645f4e73` | 27 |
| SF-1..SF-4 stream flush | `[STREAM-BUF/CODE/FENCE/SEQ]` debug logs; `_fence_opened_at` timer | `a1f97aed3` | 14 |
| NA-1..NA-3 nameplate idle | two-phase idle timer; PULSE/SHIMMER/DECRYPT beats | `6fa62cd58` | 20 |
| CWD-1..CWD-4 status bar | `status_cwd` reactive + `BashService` sentinel + `StatusBar` flash | `7b365bc97` | 17 |
| SP-1/SP-2 skill picker | `[dim]—[/dim]` fallback + `(no description)` in detail pane | `2b0877709` | 6 |
| CL-1 chip legend | "Header chips" section + overflow-y scroll in `ToolPanelHelpOverlay` | `f6d22913b` | 6 |
| KL-1..KL-7 keystroke log | opt-in JSONL recorder; `_keystroke_log.py` + `_ks_context()` + KL-7 hooks | `db31b6c29` | 15 |
| BD-1/BD-2 bottom chrome | nameplate+hintbar row, S key, [n/m] indicator | `79fe2b45b` | 12 |
| H6..L13 tools lifecycle | LIFO pop, gen_index clear, snapshot lock, atomic DOM-id, gen depth, reset hook | `fd294f52c` | 29 |
| Audit followup M-1/M-2/L-1 | log hygiene + kitty TTY latch + mount 500ms gate | `2b5bb388c` | 9 |
| H-1/H-2 audit | `_spinner_timer` leak + `LiveLineWidget` WARNING→DEBUG | `7ed7c0c44` | 6 |
| Deferred renderer swap | pre-mount race fix | — | — |

### 2026-04-27

| Spec | What shipped | Commit | Tests |
|---|---|---|---|
| VP-1..VP-10 quick wins A | `WRAP_CONTINUATION`, `...+N` chip, `body-frame--default`, chevron stable, `summary_line` density | `517071e0d` | 19 |
| FH-1..FH-8 quick wins B | hint dedup, skeleton coalesce, footer streaming gate, COMPACT `accepts()`, `OmissionBar` settled | `c9d64f58a` | 19 |
| SC-1..SC-9 quick wins C | renderer purity `diff_lines`, stall glyph, 50ms classifier timeout, IL-9 invariant | `4d6565e38` | 23 |
| AB-1..AB-3 axis bus sweep | kind axis clears hint; delete post-state `view.is_error`; watcher coverage | `9786046ad` | 9 |
| IL-1..IL-8 invariant lint gates | `tests/tui/test_invariants.py` (25 tests, <2s); 142 bare-except sites annotated; drop-order + chip ordering gates | — | 25 |
| ER-1..ER-5 ERR cell rule | `ErrorCategory` enum + `classify_error` + `split_stderr_tail`; `StderrTailWidget`; `_RECOVERY_BY_CATEGORY` | `e8c437ee7` | 31 |
| TB-1..TB-5 truncation bias | `ClassVars` + `summary_line` + `_apply_clamp` + `clamp_rows` | `86421ff2b` | 37 |
| MC-1..MC-7 microcopy + confidence | chip constants, `THRESHOLDS` dict, low-conf caption, `LayoutDecision` subscriber | `b65a47ba6` | 18 |
| FS-1..FS-3 focus/settled | prefix + tier gutter glyphs + 600ms settled suppression | `64086b808` | 15 |
| SK-1/SK-2 streaming skeleton | 100ms skeleton row + header-side hint clear on terminal state | — | 13 |
| R4-1 enter binary toggle | `action_toggle_collapse=COMPACT↔NOT-COMPACT`; `ChildPanel` override deleted | `f8b6f9ebb` | 10 |
| DC-1..DC-4 density cycle | 4-tier cycle + Shift+D + pressure skip; alt+t retired | `717c5c39c` | 14 |
| MCC-1 microcopy Rich Text | `_microcopy_text` builder; all 8 branches→Text | `2ef35da28` | 13+15 |
| CU-1/CU-2 spinner/a11y glyphs | dead `_spinner_char` deleted; `SpinnerIdentity` removed; `_ASCII_GLYPHS` extended | `2f7e805c0` | 7 |
| SCT-1/SCT-2 skin contract | `GLYPH_WARNING` + `microcopy_line` colors kwarg + `error_glyph` helper | — | 9 |
| SLR-1/2/3 streaming legibility | tier CSS class toggle + `ChildPanel` specificity + SVG mock + `streaming_kind_hint` axis | `a849a2d17` | 26 |

### 2026-04-26

| Spec | What shipped | Commit | Tests |
|---|---|---|---|
| LL-1..LL-6 lifecycle legibility | density flash + completing chip + `RendererKind` cycle + adoption flash + phase chips | `48b55cf23` | 38 |
| DC-1..DC-4 discoverability | hint row + prefix legend + `KNOWN_PREFIXES` | `025df994b` | 22 |
| DU-1..DU-6 density unification | single `LayoutResolver`; atomic axis-bus-first write; shims; decision kwarg | `fc0239574` | 35 |
| Spec B mount order/axis race | `_TERMINAL_STATES` + `_live_block_for_streaming` + `_live_anchor` + H6 retry | `2d549f40e` | 22 |
| RF-1..RF-6 renderer framing | `BodyFrame` container; `BodyFooter` multi-entry; Phase C renderers migrated; `LogRenderer` chips | — | 30 |
| SC-1..SC-5 skin contract | dim variants + `tier_accents` `MappingProxyType` + gutter via `tool_header_gutter` | `2901d4874` | 23 |
| PG-1..PG-4 plan/group sync | `PlanSyncBroker`; `_set_view_state` choke-point; `ToolGroupState` | `01c2944a0` | 23 |
| HF-A..HF-G hint row | hint dedup, toggle reshow, F1 label, open flash, rotating tip | — | 22 |
| HW-1..HW-6 header widths | drop-order re-prio + gap clamp rm + compact footer swap + separator fix | `3dc0396e7` | 20 |
| Spec F streaming polish | L1/L2/L3/L5-L7/L11; diff regex, blink reset, CSI log, syntax fallback | — | 8 |
| Timer/pacer lifecycle H8..L10 | deadline pacer + `ManagedTimerMixin` + init race + lock sharing | `aff893f49` | 27 |
| SNS1-3 skill namespace | `$name` prefix, `SkillPickerOverlay`, `CompletionContext.SKILL_INVOKE=7`; `/skill` deprecation→hard cutover | `a7815ee35` | 62+13+13 |
| Hint pipeline H-1..H-4 | `_collect_hints`+`_render_hints`+`_truncate_hints`; F1 pinned; D density key | — | 15 |
| TCS mode legibility ML-1..ML-5 | kind caption, T revert binding, next-kind hint preview | `345f0e983` | 18 |
| TCS polish P-1..P-8 | `_collect_hints`/`_render_hints`; D key; F1 pinned | `77b58787a` | 23 |
| KO-A..KO-D kind override UX | flash no-op, drop TEXT from cycle, `_user_forced` caption, 150ms debounce | `820e2d486` | 14 |
| Spec E buffer caps/perf | M1/M4/M9/M10; buffer caps + `ReasoningPanel` reflow + `CopyableRichLog` cache | `7f8b5f7ed` | 12 |
| ER-1..ER-5 tool error recovery | header=category, body=stderr, footer=recovery sorted first | `d41bb0009` | 20 |
| GV-1..GV-4 glyph vocabulary | grammar constants + `chip()` helper; gutter + sep migrations | `c075f599e` | 12 |
| TCS canonical liveness CL-1..6 | spinner deleted, `_streaming_phase` flag, stall-freeze, skin-driven pulse | `e94b94b4c` | 16 |
| TCS audit followup | unknown-id fallback `mark_plan_done` | `86183850f` | 22 |
| R3-LOW deferred | §5A dup collapsed writer, §2A drop-order, §2B comment | `679993a7f` | 9 |
| R3-NESTED density propagation | `ToolGroup.on_density_changed`; Cat.4A+4B | `7c6d7e745` | 13 |
| Feedback contract FC-1..FC-4 | uniform flash, race loser feedback, preemption, queue guard | `f3f27fa0d` | 22 |

### 2026-04-25

| Spec | What shipped | Commit | Tests |
|---|---|---|---|
| DT-1..DT-4 density tiers | HERO auto-clause, TRACE action, renderer COMPACT opt-out, 3-tier toggle cycle | `045d834e5` | 29 |
| Response flow deep audit | HIGH-1..LOW-3 (9 issues); `_flush_code_fence_buffer` (7 sites) | — | 16 |
| Streaming exception sweep A | H1 `io.consume` + H3 `_write_prose` + H4 `LiveLineWidget` drain | — | 11 |
| Streaming IO hardening | L1/M2/M3 | `8694595c5` | 18 |
| Streaming buffer safety | H1+M1 | `0f81b42ce` | 14 |
| Axis bus AXIS-1..5 | `ToolCallViewState` axis-bus writes | `8171e79ca` | 14 |
| Perf instrumentation PM-01..03 | — | `c3aa848e9` | 31 |
| Services logging LOG-1/2 | — | `9e616389d` | 28 |
| Streaming engine safety L2/L3/L4 | — | `52460c314` | 18 |
| SM hardening SM-HIGH-01/02+MED-01 | — | `a911d09e3` | 12 |
| R3-VOCAB VOCAB-1/2 | — | — | 21 |
| Stream reveal unification SR-1..8 | — | — | 36 |
| Axis-bus holes spec A | — | — | 9+4 |
| R2-HIGH-01/02+MED-01 | — | — | 14 |
| Visual noise VN-1/2 | — | — | 12 |
| Renderer registry R-2A-1..6 | — | — | 29 |
| Panel accent AC-HIGH/MED/LOW | — | — | 8 |
| DensityResolver move DR-1..5 | — | `aee5a465a` | 40 |
| Mech sweep A EXC-1..3 | — | `fd47f51a8` | 20 |
| Mech sweep C PERF-1..4 | — | `0744d6c56` | 7 |
| Mech sweep D CSS-1..8 | — | — | 14 |
| Mech sweep E THR-1..4 | — | `1b75abf98` | 9 |

### 2026-04-24

| Spec | What shipped | Commit | Tests |
|---|---|---|---|
| SM-01..SM-06 tool call state machine | — | `835b6e239` | 29 |
| Header tail consolidation | — | `07109f100` | 27 |
| Tool render MEDIUM M1-M9 | — | — | 37 |
| TUI Design 03 | input height / status phases / plan budget | `5ab4093cc` | 18 |
| OVERLAY-1/2/3 | interaction fixes | `3ff79bfc` | 7 |
| SearchRenderer + VirtualSearchList | overhaul | `c1454a88` | 32 |
| TableRenderer + LogRenderer | polish | `12858046` | 20 |
| Audit 4 quick wins | — | `88c6c7b6` | 33 |
| Audit 3 input mode enum | — | `13f4f72e` | 30 |
| Audit 3 completion accept | — | `c9c2fd71` | 10 |
| Audit 3 input quick wins | — | `fd34922b` | 22 |
| Audit 2 quick wins | — | `581fb2cd` | 22 |
| Tool pipeline QW-01..QW-12 | — | `bea2d165d` | 38+3 |
| Tool render HIGH H1-H5 | — | — | 34 |
| TBR body renderer regression | HIGH-01/02+MED-01/02+LOW-01 | `c83bf1f5b` | 19 |
| Audit 1 phase legibility | — | `b76e0f6b` | 50 |
| DrawbrailleOverlay split | Phase 5 cleanup; anim_engines extracted | `02efe64a` | 75 |
| Audit 1 quick wins | — | `827e6036` | 23 |
| Audit 2 discovery/affordances | — | `75f2ae00` | 37 |
| TUI Design 01 tool panel affordances | — | `8942caeb` | 6 |

### 2026-04-23

| Spec | What shipped | Commit | Tests |
|---|---|---|---|
| Input mode safety | — | — | 33 |
| Error recoverability + OmissionBar/ChildPanel | — | `3b9d7476` | 22 |
| Input feedback & completion UX | — | `51cc833b` | 36 |
| PlanPanel P1 polish | — | `f7a4ed55` | 86 |
| PlanPanel P0 fixes | — | `878d357e` | 37 |
| Startup banner polish | — | `65de2069` | 18 |
| Nameplate + ThinkingWidget lifecycle | — | `bfff7488` | 29 |
