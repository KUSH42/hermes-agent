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
| `references/gotchas.md` | All Textual/hermes gotchas — non-obvious traps, test workarounds, API quirks, Textual 8.2.3 API reference |
| `references/patterns.md` | Widget rules, reactive patterns, worker patterns, keyboard conventions, lifecycle hooks, testing patterns |
| `references/changelog.md` | Implementation history — dated changelog entries for every spec/fix |
| `references/live-audit.md` | Live audit notes and open questions |
| `skin-reference.md` | Skin YAML schema, palette keys, CSS var mapping |
| `references/tmux-audit.md` | TmuxDriver usage patterns and PTY audit harness |

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


## Skin system

Full reference in [`skin-reference.md`](skin-reference.md) (same skills folder).  
Standalone skill: `hermes-skin`.

Quick facts for TUI work:
- `app.apply_skin(Path | dict)` — single entry point; triggers `refresh_css()` + invalidates hint cache, StatusBar, completions, PreviewPanel, all ToolBlock/StreamingCodeBlock.
- New `$var-name` in `hermes.tcss` must also appear in `COMPONENT_VAR_DEFAULTS` (theme_manager.py) and skin_engine.py docstring — TCSS parse happens at class-definition time.
- `SkinPickerOverlay` scans `~/.hermes/skins/` for `.json/.yaml/.yml`; `"default"` always first.
- Hot reload: `_theme_manager.start_hot_reload()` — off-thread daemon, ~2 s latency. Dict-loaded skins cannot hot-reload.

---

