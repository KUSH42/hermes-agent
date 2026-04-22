---
name: tui-development
description: >
  Textual 8.x TUI development for the hermes-agent project. Covers widget patterns,
  thread safety, testing with run_test/pilot, CSS theming, reactive state, and all
  known Textual 8.x gotchas. TRIGGER when: building, fixing, or auditing hermes TUI
  components; adding new widgets, overlays, animations, or bindings.
version: "1.2"
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

**R4 architecture (complete, all 4 phases merged)**: All 10 `_app_*.py` mixin files deleted. `HermesApp(App)` — no mixin bases. Logic lives in `hermes_cli/tui/services/`. Forwarder methods (`watch_X`, `on_key`, `_handle_tui_command`, etc.) are inlined directly at the bottom of `HermesApp` in `app.py`.

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
| `drawbraille_overlay.py` | `anim_engines.py` (engines) + core |
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

## Recent changes

### 2026-04-22 — UX fixes (search_files JSON, history idx leak, slash cmds in history, banner overflow, AnimConfigPanel focus trap)

Five targeted fixes on `feat/textual-migration`:

**1. `search_files` JSON result shown unprocessed** — `search_files` returns `{"total_count": N, "matches": [{path, line, content}, ...]}`. Previously rendered as pretty JSON with header count of 1 (raw line count).
- `tool_result_parse.py`: new `_parse_search_json()` helper; `_extract_search_artifacts` now extracts file artifacts from `matches[].path`; `search_result_v4` uses `total_count` / `len(matches)` for the header count.
- `content_classifier.py`: JSON with `matches:[{path,…}]` shape now classifies as `ResultKind.SEARCH` (conf 0.9) instead of `JSON`, so `SearchRenderer` runs. Metadata carries `{"json": True, "hit_count": …, "query": …}`.
- `body_renderers/search.py`: `_parse_search_output` detects JSON at the top and groups `matches` by `path` before falling back to the text regex path. Query highlight still works via `cls_result.metadata["query"]`.

**2. Input history arrow-up "does not always show most recent"** — `_history_idx` was only reset by `action_submit`; any other mutation (rev-search exit, `edit_cmd` action, paste, user editing a recalled entry) left it stale, and the next up-arrow stepped from that stale position.
- `input/widget.py`: new `_history_loading: bool` flag; `on_text_area_changed` resets `_history_idx = -1` when text diverges from `_history[_history_idx]` (guarded by the flag + `_handling_file_drop`).
- `input/_history.py`: `_history_load` wraps `load_text` with `_history_loading = True`; same guard on rev-search matcher loads; `_exit_rev_mode` now syncs `_history_idx` to `_rev_match_idx` on accept (so up/down continue from the match) and to `-1` on restore.

**3. Slash commands not saved to history** — `_save_to_history` had `if text.startswith("/"): return` which dropped every `/cmd` from history. Removed the guard so `/clear`, `/model …`, etc. recall via up-arrow. `test_input_completion_ux.py::test_slash_command_not_saved` flipped to `test_slash_command_saved`.

**4. Startup banner logo width** — banner was captured with `panel.scrollable_content_region.width - 1`, which wraps the caduceus hero when the center pane is narrower than the logo.
- `cli.py::_render_startup_banner_text`: always use `shutil.get_terminal_size().columns` (or app width, whichever is wider) as `capture_width`. Deleted the ~35-line `_resolve_width` thread hop.
- `widgets/__init__.py::StartupBannerWidget` CSS: `width: auto; min-width: 100%; overflow-x: visible` — widget sizes to the logo's intrinsic width and is allowed to overflow past the parent pane. OutputPanel's `overflow-x: hidden` still clips at the panel edge.

**5. WorkspaceOverlay could pop on top of AnimConfigPanel, focus got stranded** — AnimConfigPanel is non-modal (to preserve underlying overlay visuals) but captures focus. Pressing `w` (when input not focused, which is the case when AnimConfigPanel has focus) opened the workspace overlay on top, and any stray focus loss made the panel unreachable.
- `drawbraille_overlay.py::AnimConfigPanel`: new `on_blur` — while `--visible`, schedules `self.focus()` via `call_after_refresh` so focus can't escape.
- `app.py::action_toggle_workspace`: bails when `_focus_blocking_overlay_visible()` is True.
- `app.py::_focus_blocking_overlay_visible`: new helper; returns True if `AnimConfigPanel` or `AnimGalleryOverlay` has `--visible`. Central extension point for future focus-trapping overlays.

**Gotchas (new):**
- When adding a tool parser that returns JSON, the classifier routes JSON-with-`matches[{path,…}]` to `SearchRenderer`, not `JsonRenderer`. If you want JsonRenderer for a different JSON shape with a `matches` key, disambiguate via tool category or an extra field.
- Any code that sets `HermesInput.value` programmatically (paste, edit_cmd, skin injection, etc.) now correctly clears `_history_idx` via `on_text_area_changed`. Don't wrap external mutations in the `_history_loading` flag unless you genuinely want the idx preserved.
- Non-modal overlays that rely on `self.focus()` in `show()` should also implement `on_blur` → refocus-if-visible, otherwise the first descendant focus event or click outside strands them.
- `action_toggle_*` entry points for info overlays should check `_focus_blocking_overlay_visible()` before `_dismiss_all_info_overlays()` + show; the suppress-when-input-focused guard in `services/keys.py` isn't enough because focus-trapping overlays steal focus *away* from the input.

### 2026-04-22 — RX3 CSS var single-source-of-truth infra (merge 89b89a53, merged feat/textual-migration)

Phases 1+2+3 landed; Phase 4 (generator block install + VarSpec type flip + pre-commit hook) deferred to a freeze-window PR.

**Spec:** `/home/xush/.hermes/2026-04-22-tui-v2-RX3-css-var-single-source-spec.md` (approved 9.6/10 after 3 review iterations).

**New file `hermes_cli/tui/build_skin_vars.py`** — scanner + generator + CLI:
- `TEXTUAL_BUILTIN_VARS: frozenset[str]` — introspected from `App().get_css_variables()` at import with Textual 8.x version-pin `assert`. `TEXTUAL_BUILTIN_VARS_FALLBACK` enumerated snapshot for degraded environments.
- `scan_tcss_references()` / `scan_tcss_declarations()` / `scan_default_css_references(tui_dir)` / `scan_bundled_skins(skins_dir)` / `scan_docstring_keys()` — audit inputs.
- `build_matrix(defaults)` + `print_matrix(rows)` — drift report.
- `render_tcss_block(defaults)` / `render_docstring_block(defaults)` — deterministic generator output with strict alphabetical ordering, BEGIN/END markers, `hash: sha256:<hex>` line over full VarSpec tuple incl. description.
- `write_tcss()` / `write_docstring()` / `fill_skin(path, defaults)` — mutation entry points.
- CLI: `python -m hermes_cli.tui.build_skin_vars` / `--check` / `--matrix` / `--fill-skin PATH`.
- Comment-stripping in `scan_tcss_references`: `_TCSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)` applied before ref regex — stops `$var` in comments from producing false positives.

**`hermes_cli/tui/theme_manager.py` — new exports:**
- `VarSpec` (frozen dataclass) — fields: `default`, `description`, `since`, `optional_in_skin`, `category`.
- `_default_of(x: str | VarSpec) -> str` — migration shim unwrap.
- `_defaults_as_strs() -> dict[str, str]` — canonical reader; replaces all 4 prior `dict(COMPONENT_VAR_DEFAULTS)` call sites in `__init__`, `load_dict`, `_apply_hot_reload_payload`, `_load_path`.
- `SkinValidationError(ValueError)` + `validate_skin_payload(payload, *, source="<skin>", warn_missing=True)` — dataclass+regex validator; `_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")`. Missing keys → `UserWarning`; bad hex or non-mapping → `SkinValidationError`.
- `load_with_fallback(configured, *, bundled_default)` — 3-step chain: configured → bundled default → emergency `COMPONENT_VAR_DEFAULTS`-only. Each failure prints `SKIN_LOAD_FAILED` / `SKIN_DEFAULT_FAILED` / `SKIN_EMERGENCY_FALLBACK` to stderr. Emergency path always succeeds — TUI always starts.
- `_load_path` now calls `validate_skin_payload` after `load_skin_full`; invalid skins `raise` (loop in `load()` logs + continues).
- `load()` also validates merged `(skin ⊕ skin_overrides)` payload per §8.4 — a bad hex in `config.yaml` `display.skin_overrides` surfaces at load time with `source="skin_overrides"` in the error path.
- `load_dict()` intentionally unchanged — T7 regression guards that `_apply_overrides` is NOT called there (live-preview contract).
- 5 new `COMPONENT_VAR_DEFAULTS` keys: `tool-glyph-mcp`, `error-timeout`, `error-critical`, `error-auth`, `error-network` — all pre-existing in Python code (`tool_category.py`, `tool_result_parse.py`) and `hermes.tcss` but never in defaults.

**`hermes.tcss` — 14 missing declarations added**: `app-bg`, `cursor-color`, `cursor-selection-bg`, `cursor-placeholder`, `ghost-text-color`, `chevron-base/file/stream/shell/done/error`, `fps-hud-bg`, `scrollbar`, `drawbraille-canvas-color`. All were `$`-referenced in tcss rules but not declared — Textual silently resolved to empty string. Values mirror `COMPONENT_VAR_DEFAULTS`.

**Bundled skin YAML dedent bug — CRITICAL latent failure fixed**:
All 4 bundled skins (`matrix.yaml`, `catppuccin.yaml`, `solarized-dark.yaml`, `tokyo-night.yaml`) had identical dedent bugs at lines 81/83: `plan-now-fg` and `pane-border` fell out of the `component_vars:` block, making `yaml.safe_load` raise `ParserError`. Since `ThemeManager.load()` catches `Exception`, every bundled skin silently fell back to `COMPONENT_VAR_DEFAULTS` — users loading `/skin matrix` never saw the 54-key skin. Now all 4 skins parse, each carrying 59 keys.

**Tests — `tests/tui/test_css_var_single_source.py`** (19 tests + 1 xfail, all pass):
- T1: every `$name` referenced from tcss or `DEFAULT_CSS` blocks resolves (in `COMPONENT_VAR_DEFAULTS` or `TEXTUAL_BUILTIN_VARS`).
- T2: `$`-referenced defaults declared in hermes.tcss (stricter "all defaults declared" xfail'd for Phase 4).
- T3: every bundled skin covers all required keys (skips `optional_in_skin=True`).
- T4: no orphan tcss declarations.
- T5: generator deterministic.
- T6: validator rejects bad hex + non-mapping `component_vars`/`vars`; warns on missing + unknown keys.
- T6b: merged-overrides validator flags `source="skin_overrides"` in error path.
- T7: `load_dict()` does NOT call `_apply_overrides()` (live-preview regression guard).
- T8: grep test — no call site uses raw `COMPONENT_VAR_DEFAULTS[...]` outside `_default_of` (shim gate).
- Extras: `_default_of` str passthrough + VarSpec unwrap; `TEXTUAL_BUILTIN_VARS` contains core colors + ≥50 entries; hash includes description (description-only edits change hash).

**Key gotchas (new from RX3):**
- `COMPONENT_VAR_DEFAULTS` consumers MUST use `_default_of(v)` / `_defaults_as_strs()` — never `dict(COMPONENT_VAR_DEFAULTS)`. T8 grep test gates this.
- Adding a new component var still requires 3 edits until Phase 4 generator lands: (1) `COMPONENT_VAR_DEFAULTS`, (2) `$name: value;` declaration in `hermes.tcss` IF `$name` referenced from tcss/DEFAULT_CSS, (3) `component_vars:` entry in each bundled skin. T1/T2/T3 catch omissions.
- `$name` references inside TCSS `/* ... */` comments previously tripped the scanner — comment-stripping applied before regex. Any new scanner paths must do the same.
- `validate_skin_payload` emits `UserWarning` on missing required keys — existing `test_theme_manager.py` fixtures that pass partial skins now produce warnings. This is correct behavior (matches §8.3); tests still pass because warnings are not errors.
- Fallback chain uses bare `print(..., file=sys.stderr)` alongside `log.warning` so tags surface even when textual logging is disabled (e.g. in tests).
- `SkinValidationError` inherits from `ValueError` so existing `except (SkinError, OSError)` handlers needed updating to `except (SkinError, SkinValidationError, OSError)`.

**Commit trail (4 commits):**
1. `c7cceb9a` fix(skins): restore component_vars nesting in all 4 bundled skins
2. `67ee15bc` fix(tcss): declare 14 $-referenced component_vars
3. `7e64aaeb` feat(theme): VarSpec + _default_of shim + validator + 3-step fallback
4. `69b57a5b` feat(build): scanner/generator + T1-T8 tests

**Phase 4 (deferred):** replace hand-written tcss declaration block with generated BEGIN/END block, flip `COMPONENT_VAR_DEFAULTS: dict[str, str]` → `dict[str, VarSpec]` (pure value-type change — all call sites already go through shim), add `.pre-commit-config.yaml` entry for `--check`. Needs a freeze-window day with zero open PRs touching `hermes.tcss` declarations.

### 2026-04-22 — RX4 AgentLifecycleHooks — lifecycle cleanup registry (merged feat/textual-migration)

19 tests, 0.16s. Extracted cleanup logic from 175-line `watch_agent_running` into a named, priority-ordered registry.

**New file: `hermes_cli/tui/services/lifecycle_hooks.py`** — `AgentLifecycleHooks`:
- `register(transition, cb, *, owner, priority, name) → RegistrationHandle` — `WeakMethod` for bound methods; owner GC → silent prune
- `unregister(handle)` / `unregister_owner(owner)` — bulk cleanup for widget unmount
- `fire(transition, **ctx)` — snapshots registrations at entry; exceptions caught+logged; `SystemExit`/`KeyboardInterrupt` propagate
- `drain_deferred()` — called from `on_mount`; fires events queued while `app.is_running` was False
- `shutdown()` — called from `on_unmount`; sets `_shutdown` flag, clears all registrations
- `snapshot() → dict[str, list[str]]` — debug: transition → list of callback names

**`app.py` wiring:**
- `__init__`: `self.hooks = AgentLifecycleHooks(self)` (before R4 services) + `self._interrupt_source: str | None = None`
- `on_mount`: `_register_lifecycle_hooks()` + `drain_deferred()` at end
- `on_unmount`: `hooks.shutdown()` at start
- `watch_agent_running(True)`: fires `on_turn_start` at end of if-branch
- `watch_agent_running(False)`: fires `on_turn_end_any`, then `on_turn_end_{success,error}`, then `on_interrupt` if `_interrupt_source` set (and clears it)

**Registered callbacks** (priority / name) — Phases a + b:
- `on_turn_start`: `reset_turn_state` (100) ← includes response metrics reset, `osc_progress_start` (10)
- `on_turn_end_any`: `osc_progress_end` (10), `clear_output_dropped_flag` (100), `clear_spinner_label` (100), `clear_active_file` (100), `reset_response_metrics` (100), `clear_streaming_blocks` (100), `drain_gen_queue` (100), `desktop_notify` (10), `restore_input_placeholder` (900)
- `on_turn_end_success`: `chevron_done_pulse` (500), `auto_title_first_turn` (100)
- `on_interrupt`: `osc_progress_end_interrupt` (10)
- `on_compact_complete`: `reset_compaction_warn_flags` (100)
- `on_error_set`: `schedule_status_error_autoclear` (100) — schedules 10s timer via `_lc_schedule_error_autoclear`
- `on_error_clear`: `cancel_status_error_timer` (100) — cancels via `_lc_cancel_error_timer`

**Phase b additions (commit 16f7004a):**
- Dual execution removed — inline cleanup in `watch_agent_running` deleted (−88 lines); hooks are sole owners
- `_lc_schedule_error_autoclear` / `_lc_cancel_error_timer` implemented (were stubs); timer moved out of `on_status_error` inline code
- `on_compact_complete` inline flag resets removed from `on_status_compaction_progress`; `_lc_reset_compact_flags` hook is sole owner
- `IOService.consume_output` fires `on_streaming_start` (first chunk) and `on_streaming_end` (flush sentinel); D2 fix: zeros `status_compaction_progress` at stream end if still > 0
- `_lc_reset_turn_state` extended to include response-metrics reset (covers True-branch cleanup)

**`watchers.py`**: `hooks.fire("on_compact_complete")` in `on_status_compaction_progress(0.0)` (inline resets removed); `hooks.fire("on_error_set"/"on_error_clear")` in `on_status_error` (inline timer removed).

**Key gotchas:**
- `_lc_osc_progress_end` must accept `**_` — registered on both `on_turn_end_any` (no ctx) and `on_interrupt` (carries `source=`)
- Callbacks on `on_turn_end_success` must also accept `**_` since `on_turn_end_any` fires before it and callers fire all three in sequence with same ctx
- Do NOT set the reactive that owns the transition inside a hook callback (reactive deadlock)
- `_interrupt_source` is set by `services/keys.py` (`KeyDispatchService`) before dispatching each interrupt; cleared by `watch_agent_running(False)` after hooks.fire
- `on_streaming_start/end` fire per assistant-message stream (multiple per turn if multiple messages); `_first_chunk_in_turn` resets on each None sentinel

**Tests:** `tests/tui/services/test_lifecycle_hooks.py` (19), `tests/tui/services/test_lifecycle_hooks_phase_b.py` (33) — pure-unit, no Textual dep.

### 2026-04-22 — R3 overlay consolidation Phases A+B (merge de005f7a, merged feat/textual-migration)

21 pre-mounted overlays → 5 canonical + 3 standalones (C/D/E phases still pending). Alias layer preserves every existing `query_one(OldName)` / `isinstance(x, OldName)` call site.

**Phase A — ConfigOverlay (commits 3c46d2b1 + fa5ad015):**
- New `hermes_cli/tui/overlays/` package. **`overlays.py` renamed atomically to `overlays/_legacy.py`** with `overlays/__init__.py` doing `from ._legacy import *`. All existing importers work unchanged.
- New `overlays/config.py` — `ConfigOverlay(Widget)` with 7 tabs: Model, Skin, Syntax, Options, Reasoning, Verbose, YOLO. Tab keys `1`–`7` + `Tab`/`Shift+Tab` cycle. `ConfigOverlay.show_overlay(tab="model"|"skin"|...)` routes.
- Retired 5 picker overlays: `ModelPickerOverlay`, `VerbosePickerOverlay`, `ReasoningPickerOverlay`, `YoloConfirmOverlay`, `TabbedSkinOverlay` (the `SkinPickerOverlay` alias still resolves).
- Slash handlers `/model`, `/skin`, `/reasoning`, `/verbose`, `/yolo` dispatch to `ConfigOverlay.show_overlay(tab=...)` via `services/commands.py`.
- `_dismiss_all_info_overlays()` in `services/context_menu.py` updated: adds `ConfigOverlay`, retires 5 picker entries.
- Tests: **29 new** in `tests/tui/test_config_overlay.py` (tab switching, alias semantics, tab-state preservation); **~85 retired** (test_config_picker_overlays.py, test_tabbed_skin_overlay.py, test_picker_overlay_base.py).

**Phase B — InterruptOverlay (commits a5398706 + e60be059 + b6a05208 + db9dce05):**
- New `overlays/interrupt.py` — `InterruptOverlay(Widget)` with `InterruptKind` StrEnum (CLARIFY/APPROVAL/SUDO/SECRET/UNDO/NEW_SESSION/MERGE_CONFIRM), `InterruptPayload` + `InterruptChoice` + `InputSpec` dataclasses, FIFO queue, 7 variant renderers.
- Replaces 7 widgets: `ClarifyWidget`, `ApprovalWidget`, `SudoWidget`, `SecretWidget`, `UndoConfirmOverlay` (were in `widgets/overlays.py`) + `NewSessionOverlay`, `MergeConfirmOverlay` (were in `session_widgets.py`).
- New `overlays/_adapters.py` — `make_{clarify,approval,sudo,secret,undo,new_session,merge_confirm}_payload` factories convert legacy `ChoiceOverlayState`/`SecretOverlayState`/`UndoOverlayState` (unchanged agent-side wire format) into `InterruptPayload`. `_adopt_state_deadline` carries epoch deadline through.
- `compose()` in `app.py`: 7 yields collapsed to one `yield InterruptOverlay(id="interrupt-overlay")`.
- 5 state watchers (`clarify`/`approval`/`sudo`/`secret`/`undo`) in `services/watchers.py` route through adapters + `InterruptOverlay.present(payload, replace=True)`. Undo uses `preempt=True` (pushes current interrupt to queue front).
- Session flow in `services/sessions.py`: `open_new_session_overlay` / `show_merge_overlay` go through `InterruptOverlay.present(make_*_payload(...))`.
- `services/keys.py`: arrow/Enter dispatch uses `InterruptOverlay.select_choice` / `confirm_choice`; approval diff-panel scroll + Tab focus cycle preserved.
- **Escape dispatch**: InterruptOverlay is NOT added to the `_app_key_handler.py:180` tuple. Its own `BINDINGS = [Binding("escape", "dismiss", priority=True)]` handles Escape.
- Tests: **35 new** in `tests/tui/test_interrupt_overlay.py`; 7 retired in `test_session_widgets.py`.

**Alias layer (`overlays/_aliases.py`):**
- `_AliasMeta` metaclass — `__instancecheck__(cls, obj)` returns `isinstance(obj, cls._alias_target) and getattr(obj, active_tab_or_kind, None) == cls._alias_mode`.
- Two-mechanism approach: alias names registered into canonical's `_css_type_names` frozenset (makes `query_one(VerbosePickerOverlay)` resolve to `ConfigOverlay`), and `_AliasMeta.__instancecheck__` handles bare `isinstance`.
- Aliases are `Widget` subclasses (NOT canonical subclasses) — avoids making them valid mount targets.
- Tests that assumed "query_one fails when wrong picker visible" must check `has_class("--visible") and active_tab == "verbose"` instead.

**Key gotchas:**
- `query_one(Alias)` uses `Alias.__name__` as CSS type selector. Works only because alias name is in `_css_type_names` frozenset. Pure-metaclass `__instancecheck__` alone does NOT cover `query_one`.
- `call_after_refresh(self._activate, payload)` for queue advance / replace / preempt paths — `child.remove()` returns `AwaitRemove`, so same-id re-mount would race `DuplicateIds` without deferring.
- Adapters keep a `_linked_state` back-pointer to sync `ChoiceOverlayState.selected` — legacy tests that assert on `state.selected` still pass.
- `preempt=True` semantics (undo-over-approval): pushes current interrupt to queue front, activates new one; old resumes on new-one resolve. Replaces spec's pause/resume approach.

**Still pending (R3 D):**
- Phase D: SessionOverlay body → SessionStrip dropdown (R7 dependency).

**Merge notes (conflicts with R4 services refactor):** R3 was forked before R4 landed. Merge resolution kept HEAD's thin-adapter mixin shape and pushed R3's overlay wiring INTO the services (`services/commands.py`, `services/context_menu.py`, `services/keys.py`, `services/sessions.py`, `services/watchers.py`). `_get_interrupt_overlay` helper lives on `WatchersService`. Two pre-existing cross-branch failures surfaced on merge (test_turn_undo_retry 12 fails — `ThemeService.flash_hint` references removed `app._flash_hint_timer` from RX1 Phase C; test_session_widgets 7 fails — monkey-patch sites moved to `SessionsService`). NOT caused by R3.

### 2026-04-22 — R3 Overlay Consolidation Phases A/B/C (merged feat/textual-migration)

21 pre-mounted overlays → 5. Three phases, stacked and merged.

**Phase A — ConfigOverlay (2 commits):**
- `overlays.py` → `overlays/` package (atomic rename: `_legacy.py` + `__init__.py` re-export); delete stale `__pycache__` in same commit
- `overlays/config.py`: `ConfigOverlay(Widget)` — 7-tab canonical picker; tabs 1–7 map to Model/Skin/Syntax/Options/Reasoning/Verbose/YOLO
- `overlays/_aliases.py`: alias classes (`VerbosePickerOverlay`, `ModelPickerOverlay`, etc.) with `_AliasMeta.__instancecheck__` for bare `isinstance`; alias names registered into `ConfigOverlay._css_type_names` for `query_one(Alias)` CSS type resolution
- Escape dispatch: `ConfigOverlay` added to `_app_key_handler.py:180` tuple; old 5 picker entries removed from `_dismiss_all_info_overlays`
- ~30 new tests in `test_config_overlay.py`; ~85 retired from `test_config_picker_overlays.py` + `test_tabbed_skin_overlay.py`

**Phase B — InterruptOverlay (4 commits):**
- `overlays/interrupt.py`: `InterruptKind(StrEnum)` (CLARIFY/APPROVAL/SUDO/SECRET/UNDO/NEW_SESSION/MERGE_CONFIRM), `InterruptPayload` ABC + per-kind dataclasses, `InterruptOverlay(Widget)` — single widget, variant-dispatched on `state.kind`
- State adapters: `make_clarify_payload`, `make_approval_payload`, etc. adapt existing `ChoiceOverlayState`/`SecretOverlayState`/`UndoOverlayState` at overlay boundary — wire formats unchanged
- 7 old class bodies deleted; `compose()` yields one `InterruptOverlay()` instead of 7
- `InterruptOverlay.present(payload, replace=False)` — FIFO queue; `replace=True` for same-kind re-present from watchers
- 35 new tests in `test_interrupt_overlay.py`; ~58 retired across 4 files

**Phase C — ReferenceModal fallback (1 commit, §7.4 path — no PaneManager yet):**
- `overlays/reference.py`: `ReferenceModal(Widget)` base with shared `show_overlay`/`hide_overlay`/`action_dismiss`/`on_mount`; 4 thin subclasses (`HelpOverlay`, `UsageOverlay`, `CommandsOverlay`, `WorkspaceOverlay`) — all logic preserved, only inheritance changed
- 4 classes removed from `_legacy.py`; exported from `overlays/__init__.py` via `reference.py`
- 28 new tests in `test_pane_surfaces.py`; ~75 retired from 5 files
- **Spec error caught**: `F1` opens `KeymapOverlay` (not `HelpOverlay`) per `app.py:285,1557` — test replaced with pre-mount ID verification

**Key gotchas:**
- `query_one(Alias)` uses `Alias.__name__` as CSS type selector → must register alias names into canonical's `_css_type_names` frozenset; pure metaclass `__instancecheck__` alone is insufficient
- Alias classes subclass `Widget` directly (NOT the canonical) — subclassing canonical would break "one pre-mounted instance" invariant
- `overlays.py` → `overlays/` rename: delete `__pycache__/overlays.cpython-*.pyc` in same commit or old bytecode shadows new package
- `_dismiss_all_info_overlays` (not `_hide_all_overlays`) is the central helper — 13 call sites; post-R3 iterates `{ConfigOverlay, InterruptOverlay, HistorySearchOverlay, KeymapOverlay, ToolPanelHelpOverlay}`
- `InterruptOverlay` stays pre-mounted (NOT ModalScreen) — ModalScreen breaks alias instancecheck trick and every `has_class("--visible")` test
- R3 forked before R4 landed; merge resolution pushed overlay wiring INTO services (`services/commands.py` etc.)

### 2026-04-22 — RX1 FeedbackService — unified flash/feedback coordination (4 commits, merged feat/textual-migration)

18 tests (T1–T15 unit + I1–I3 integration). Replaces 7 ad-hoc per-widget flash implementations with a single service.

**New files:**
- `hermes_cli/tui/services/__init__.py` — package init
- `hermes_cli/tui/services/feedback.py` — `FeedbackService`, `FlashState`, `FlashHandle` (`.displayed: bool`), `ChannelAdapter`, `AppScheduler` (prod), `HintBarAdapter`, `ToolHeaderAdapter`, `CodeFooterAdapter`; `Scheduler`/`CancelToken` protocols; `ExpireReason(StrEnum)` (NATURAL/CANCELLED/PREEMPTED/UNMOUNTED); `LOW/NORMAL/WARN/ERROR/CRITICAL` priority constants; `ChannelUnmountedError` (internal only — not exported)
- `tests/tui/services/test_feedback_service.py` — T1–T15 unit tests; no App/run_test; `FakeScheduler`/`FakeCancelToken` fixtures; covers D3/D5/E3 regression cases
- `tests/tui/test_feedback_integration.py` — I1–I3 integration tests with real `HermesApp`

**Modified:**
- `hermes_cli/tui/app.py` — `self.feedback: FeedbackService = FeedbackService(AppScheduler(self))` in `__init__`; registers `HintBarAdapter` for `"hint-bar"` (lifecycle_aware=True); `watch_agent_running(False)` now calls `self.feedback.on_agent_idle()` (E3 fix); `_flash_hint_expires/_timer/_prior` fields removed
- `hermes_cli/tui/_app_theme.py` — `_flash_hint()` is now a 3-line forwarder to `feedback.flash("hint-bar", ...)`; shrunk from ~30 lines
- `hermes_cli/tui/tool_panel.py` — `_flash_header()` forwards to `feedback.flash(f"tool-header::{self.id}", ...)`; direct write at line 880 (`header._flash_msg = "done"`) replaced with `feedback.flash(..., duration=0.5)`; `on_mount`/`on_unmount` register/deregister `ToolHeaderAdapter`
- `hermes_cli/tui/tool_blocks/_header.py` — `flash_copy/flash_success/flash_error` forward to `tool-header::<panel-id>` channel; `_copy_flash` field and `_end_flash` stub deleted
- `hermes_cli/tui/widgets/code_blocks.py` — `CodeBlockFooter.flash_copy` forwards to `code-footer::<id>` channel; `on_mount`/`on_unmount` register/deregister `CodeFooterAdapter`; `_copy_flash_timer` field and `_restore_copy` method deleted; `StreamingCodeBlock._copy_flash` bool deleted (CSS class is authoritative)

**Key design:**
- `FlashState` uses `@dataclass` (not frozen) so `token` can be assigned after construction
- One lambda in entire service: `lambda: self._on_expire(state.id)` — captures only the primitive `state.id` string; fixes D5 ref cycle
- Priority semantics: `P1 > P0` preempts; `P1 == P0` replaces; `P1 < P0` blocked (handle `.displayed = False`)
- `key=` replaces regardless of priority (explicit caller intent)
- `cancel()` calls `adapter.restore()`; preempt does NOT (D3 fix)
- `shutdown()` fires UNMOUNTED callbacks but does NOT call `adapter.restore()` (I4)
- `on_agent_idle()` only restores when no flash active (E3 fix); `hint-bar` is the only lifecycle-aware channel
- `ChannelUnmountedError` internal to `services/feedback.py` — never import it elsewhere
- All flash call sites under `call_from_thread` continue to use `call_from_thread`; service API is event-loop-only
- Per-block adapters accumulate until `on_unmount` → `deregister_channel()` — prevents stale widget refs after ToolPanel removal

**Bugs fixed (traceability):**
- D3 overwrite race → I1+I2+I3 (preempt cancels timer; old restore never fires); regression T2/T3/I1
- D5 ref cycle (lambda captures) → service owns state; `_on_expire` drops state; no widget refs in lambdas; regression T13
- E3 `watch_agent_running` clears active flash → `on_agent_idle()` no-op during active flash; regression T11/I3

**Gotchas:**
- `FakeScheduler.advance(dt)` fires expired callbacks synchronously; mark token stopped before firing to prevent double-fire
- `ToolHeader._feedback_channel_id()` resolves `panel_id` from `self._panel.id if self._panel is not None else self.id` — header may not always have a panel reference
- `session-notify` is NOT a registered channel (Option B) — `_SessionNotification` keeps its own independent timer

### 2026-04-22 — R1 PlanPanel — plan/action queue surface (5 commits, merged feat/textual-migration)

78 tests. Surfaces the agent's work queue as first-class TUI state.

**New files:**
- `hermes_cli/tui/plan_types.py` — `PlanState(StrEnum)` (PENDING/RUNNING/DONE/ERROR/CANCELLED/SKIPPED) + `PlannedCall` (frozen dataclass with `as_running()` / `as_done()` transition helpers)
- `hermes_cli/tui/widgets/plan_panel.py` — `PlanPanel(Vertical)` with 4 subsections + module-level `_format_plan_line()` pure helper

**`app.py`** — 5 new class-level reactives (all `repaint=False`):
```python
planned_calls: reactive[list[PlannedCall]] = reactive(list, repaint=False)
turn_cost_usd: reactive[float] = reactive(0.0, repaint=False)
turn_tokens_in: reactive[int] = reactive(0, repaint=False)
turn_tokens_out: reactive[int] = reactive(0, repaint=False)
plan_panel_collapsed: reactive[bool] = reactive(False)
```

**`services/tools.py`** (`ToolRenderingService`) — three new event-loop-only methods:
- `set_plan_batch(batch: list[tuple[str, str, str, dict]])` — seeds PENDING entries, clears stale PENDING from prior batches
- `mark_plan_running(tool_call_id)` — PENDING → RUNNING, set `started_at`
- `mark_plan_done(tool_call_id, is_error, dur_ms)` — → DONE/ERROR, set `ended_at`
- All three: `items = list(self.planned_calls); ...; self.planned_calls = items` — never mutate in-place

**`run_agent.py`** (Shape A — preferred):
- `AIAgent.__init__` accepts `tool_batch_callback` + `usage_callback`
- Batch CB fires once per assistant message: concurrent path after `parsed_calls` assembled (before first `tool_start_callback`); sequential path before the `for i, tool_call in enumerate(...)` loop
- Usage CB fires after `session_*_tokens` update block; wraps `(prompt_tokens, completion_tokens, cost_usd)`
- Both wrapped in `try/except logging.debug(...)` — agent must never crash on TUI failure

**`cli.py`**:
- `_on_tool_batch(batch)` — builds 4-tuples, calls `tui.call_from_thread(tui.set_plan_batch, tuples)`; compute batch repr *before* `call_from_thread` (don't close over mutable dicts)
- `_on_usage(prompt, completion, cost_usd)` — accumulates on agent thread, then `call_from_thread(setattr, tui, 'turn_tokens_in', ...)`
- `_reset_turn_state()` — zeros all 4 reactives + clears `planned_calls`; called from `on_hermes_input_submitted` only when submission actually starts an agent turn
- `_on_tool_start` calls `tui.call_from_thread(tui.mark_plan_running, tool_call_id)`
- `_on_tool_complete` calls `tui.call_from_thread(tui.mark_plan_done, tool_call_id, is_error, dur_ms)`

**`PlanPanel` widget architecture:**
```
PlanPanel(Vertical)              # id="plan-panel"; dock: bottom; height: auto (max 12)
├── _PlanPanelHeader(Horizontal) # title + collapse chevron
├── _NowSection(Vertical)        # ● current tool  elapsed  [cancel stub]
├── _NextSection(Vertical)       # ▸ pending tools (max 5 + "… +N more" Static)
├── _DoneSection(Vertical)       # ✓/✗ done tools (max 5 + "… +N more" Static)
└── _BudgetSection(Horizontal)   # "$0.12 · 4.3k↑ 12.1k↓"; click → UsageOverlay
```
- `_NowSection` uses `set_interval(1.0, self._tick)` for elapsed; NOT `CountdownMixin` (monotonically increasing, not countdown). Timer started on first RUNNING entry, stopped when empty.
- Under `HERMES_DETERMINISTIC=1`: `_NowSection` elapsed pinned at `0s` (same contract as ThinkingWidget)
- Overflow: max 5 per section; excess → `… +N more` Static; click to expand inline (per-section `_expanded: reactive[bool]`)
- Collapsed = `--collapsed` CSS class; 1-row chip: `Plan · 2▸ · 3✓`
- At ≥ 140 cols: subsections flip to Horizontal [Now | Next | Done | Budget]
- On `compact == True`: chip form regardless of width (reuses existing `compact` reactive)
- Accessibility: `●/▸/✓/✗` → `*/>/ [ok]/[X]` when `HERMES_ACCESSIBILITY=1` (read via `_accessibility_mode()` helper — NOT `accessibility_mode()` from constants, as PlanPanel avoids that import)

**`watch_planned_calls` on `HermesApp`**: adds/removes `plan-active` app class. `hermes.tcss` uses `HermesApp.plan-active ThinkingWidget.--active { height: 1; }` — forces ThinkingWidget to LINE height while plan is active. No changes to `ThinkingWidget` class.

**`services/keys.py`**: `F9` toggles `plan_panel_collapsed`. Free across bash/zsh/fish + tmux.

**TCSS vars** — must be in `hermes.tcss` declaration block AND `COMPONENT_VAR_DEFAULTS` AND all 4 skin files:
- `plan-now-fg`: `#00bcd4` (= `$accent-interactive`)
- `plan-pending-fg`: `#777777 60%`

**Gotchas:**
- **PlanPanel must start hidden**: DEFAULT_CSS needs `display: none;` + `PlanPanel.--active { display: block; }`. Without this it renders empty header+sections at startup, eating 5-6 rows and overlapping the input area. `_on_planned_calls_changed` controls `--active`: add when `bool(calls)`, remove when empty.
- `PlannedCall` lives in `plan_types.py` (not `_app_tool_rendering.py`) — avoids circular import with `tool_category.py`
- `_NowSection._timer_handle` stopped by calling `_timer_handle.stop()` before reassigning; leaking an un-stopped timer causes double-ticks at section transitions
- `_BudgetSection` click routing: widget itself can't focus; `on_click` calls `self.app.action_show_usage()` — same pattern as other non-input widgets that open overlays
- Sub-agent nesting: `PlannedCall.depth` preserved through `as_running()` / `as_done()`; `_NextSection` / `_DoneSection` indent via `"  " * call.depth` prefix

**Test targets (never run `tests/tui/` in full):**
```
tests/tui/test_plan_types.py
tests/tui/test_plan_state_transitions.py
tests/tui/test_plan_panel.py
tests/tui/test_plan_panel_narrow.py
tests/tui/test_plan_panel_collapse.py
tests/tui/test_plan_panel_budget.py
tests/tui/test_plan_panel_usage_link.py
tests/tui/test_plan_panel_nested.py
tests/tui/test_plan_panel_perf.py
tests/tui/test_help_overlay_plan_entry.py
tests/agent/test_tool_batch_callback.py
```

### 2026-04-22 — R4 services refactor — Phase 1+2 (1 commit, merged feat/textual-migration)

40 wiring tests (`tests/tui/test_services_wiring.py`). All 4 phases merged — all 10 `_app_*.py` mixin files deleted; `HermesApp(App)` directly.

**New package**: `hermes_cli/tui/services/` — 10 `AppService` subclasses + `base.py`.

**Pattern**: logic lives in service classes. `app._svc_X.method()` is the call path.

**`_flash_hint` conflict resolved**: HEAD wins — `_ThemeMixin._flash_hint` still routes through `FeedbackService.flash("hint-bar", ...)` (RX1 design). `ThemeService.flash_hint()` exists but is NOT called by `_flash_hint`. If you see a test patching `app._svc_theme.flash_hint`, that's wrong — patch `app.feedback.flash` or `app._flash_hint` instead.

**State that moved to services** (backward-compat `@property` proxies on App for the reactive period):
- `_svc_tools._turn_tool_calls` — proxied by `app._turn_tool_calls`
- `_svc_tools._streaming_map` — proxied by `app._streaming_map`
- `_svc_browse._browse_anchors`, `_browse_cursor` — proxied
- `_svc_sessions._sessions_index` — proxied
- `_svc_spinner._helix_frame_cache` — proxied

**Gotchas:**
- Service `__init__` receives `app: HermesApp`; access dom via `self.app.query_one(...)`
- `import time as _time` at module level in `services/keys.py` — required so tests can `monkeypatch.setattr("hermes_cli.tui.services.keys._time", ...)`
- `WatchersService.drop_path_display` is a `@staticmethod` (no `self.app` needed)
- `on_hermes_input_files_dropped` on mixin calls `self._svc_watchers.handle_file_drop(event.paths)` — NOT `_svc_keys`

**Test targets:**
```
tests/tui/test_services_wiring.py   # 40 tests — instantiation + method presence + routing
```

### 2026-04-22 — R2 panes layout — three-pane skeleton (1 commit, merged feat/textual-migration)

202 tests across 6 files. Flag-gated: `display.layout: "v2"` (default `"v1"`; zero behavior change for existing users).

**New files:**
- `hermes_cli/tui/pane_manager.py` — `PaneManager` (plain class, not mixin), `PaneId(StrEnum)`, `LayoutMode(StrEnum)`, `PaneHost(Protocol)`
- `hermes_cli/tui/widgets/pane_container.py` — `PaneContainer(Widget)` — visual pane shell
- `hermes_cli/tui/widgets/plan_panel_stub.py` — placeholder for R1 (until R1 wires its `PlanPanel` in)
- `hermes_cli/tui/widgets/context_panel_stub.py` — placeholder for R6/R9
- `hermes_cli/tui/widgets/split_target_stub.py` — pre-mounted (display:none); made visible by Ctrl+\

**`PaneManager` architecture:**
- Plain class held at `self._pane_manager` on `HermesApp` — NOT a mixin
- `enabled: bool` — False in v1 mode; all public methods no-op when False
- Breakpoints: `SINGLE` < 120 cols OR h < 20 OR v1 mode; `THREE` 120–159; `THREE_WIDE` ≥ 160
- `_apply_layout(app)` — idempotent; sets `display` + `styles.width` on `#pane-left/#pane-center/#pane-right`; called from `_flush_resize` only (NOT `watch_size`)
- `dump_state() → dict` / `load_state(dict)` — persisted to `<session_dir>/layout.json` via `SessionManager.save_layout_blob` / `load_layout_blob`
- `compute_layout(w, h)` is a **pure function** — returns `(mode, left_w, center_w, right_w)`; center always ≥ 80 or falls to SINGLE
- Hysteresis: 2 cells on both SINGLE and THREE_WIDE boundaries

**`app.py` changes:**
- `__init__`: `self._output_panel = OutputPanel(id="output-panel")` constructed early (needed so v2 can re-parent it into `#pane-center` without re-instantiating); `self._pane_manager = PaneManager(cfg=_display_cfg)`
- `compose()` branches on `self._display_layout`:
  - v1: `yield self._output_panel; yield _PP(id="plan-panel")`
  - v2: `Horizontal#pane-row` → 3 `PaneContainer` widgets + `SplitTargetStub`; `_PP` yielded after pane-row in both modes
- `on_mount` (v2): adds `layout-v2` CSS class; calls `pane_center.set_content(self._output_panel)`, mounts `PlanPanelStub` + `ContextPanelStub` into side panes

**Key bindings (v2 only, all guarded by `_pane_manager.enabled`):**
- `F5/F6/F7` — focus left/center/right pane
- `F9 / Shift+F9` — cycle visible (non-collapsed) panes forward/backward
- `Ctrl+[ / Alt+[` — collapse/expand left pane
- `Ctrl+] / Alt+]` — collapse/expand right pane
- `Ctrl+\` — toggle center-pane split (shows/hides `SplitTargetStub`)
- `Esc` in side pane — returns focus to `#input-area`

**TCSS (in `hermes.tcss`, section `/* ── R2 pane layout ──`):**
```css
HermesApp.layout-v2 #pane-row      { height: 1fr; display: block; layout: horizontal; }
HermesApp.layout-v2 #input-row     { dock: bottom; }
HermesApp.layout-v2 #input-rule-bottom { dock: bottom; }
HermesApp.layout-v2 VoiceStatusBar { dock: bottom; }
HermesApp.layout-v2 StatusBar      { dock: bottom; }
/* Center split: OutputPanel 2fr, SplitTargetStub 1fr */
HermesApp.layout-v2 PaneContainer#pane-center.--split OutputPanel    { height: 2fr; }
HermesApp.layout-v2 PaneContainer#pane-center.--split SplitTargetStub { display: block; height: 1fr; }
```

**New component vars (all 4 bundled skins updated):**
- `pane-border`, `pane-border-focused`, `pane-title-fg`, `pane-divider`

**`/layout` slash command:**
- `/layout v1|v2` — persists to config; restart required
- `/layout left=N` / `/layout right=M` — live-applies pane width overrides

**Key gotchas:**
- `_apply_layout` takes `app` as arg — `PaneManager` is not a Widget and has no `self.app`
- `F9` was previously free; `Alt+[` / `Alt+]` are the always-available Ctrl aliases (some terminals send Ctrl+[ as ESC)
- Dock-bottom stacking for v2: `StatusBar` pins to bottom, `VoiceStatusBar` above it, `input-rule-bottom` above that, `#input-row` above that — matches current visual order because compose order is preserved
- `PaneContainer.DEFAULT_CSS` must use **literal hex** not `$pane-border` vars — `DEFAULT_CSS` is parsed before the app's `hermes.tcss` loads custom vars; `hermes.tcss` overrides them for the real app
- `query_one(PaneContainer)` is ambiguous — 3 instances in DOM; always use `query_one("#pane-left")` / `query_one("#pane-center")` / `query_one("#pane-right")`
- Tests that need v2 mode: set `app._display_layout = "v2"` + `app._pane_manager = PaneManager({"layout": "v2"})` before `run_test(size=(140, 40))`
- Session layout blob: `session_manager.save_layout_blob(session_id, layout)` writes `<session_dir>/<session_id>/layout.json`; `load_layout_blob` reads it; `app.on_unmount` calls save; `app.on_mount` calls load+apply

**Test targets:**
```
tests/tui/test_pane_manager.py          # 36 tests — PaneManager pure logic
tests/tui/test_pane_layout_compose.py   # 31 tests — v1/v2 compose, pane structure
tests/tui/test_pane_responsive.py       # 39 tests — breakpoints, hysteresis, focus, Esc
tests/tui/test_pane_persistence.py      # 28 tests — dump/load/roundtrip, session blob
tests/tui/test_layout_slash_commands.py # 21 tests — /layout command
tests/tui/test_pane_split.py            # 12 tests — Ctrl+\ split toggle
```

### 2026-04-22 — TUI Visual Redesign V1–V8 (7 commits, merged feat/textual-migration)

8 visual/layout fixes across banner, input, gutter, accent, contrast.

**V1 — Full-width splash**: added `expand=True` to `Panel(layout_table, ...)` in `banner.py:build_welcome_banner()`. Left column `width=_hero_width` preserved. Width bug was in Rich content, not Textual widget.

**V2 — Hide AssistantNameplate while thinking**: `thinking.py:activate()` calls `self.app.add_class("thinking-active")`; `_do_hide()` calls `self.app.remove_class("thinking-active")`. `hermes.tcss` adds `HermesApp.thinking-active AssistantNameplate { display: none; }`. App-level classes use single-hyphen convention (`thinking-active`, not `--thinking-active`). Safe to call without `call_from_thread` — `activate()` is called from `_consume_output` (async coroutine worker on event loop, see `_app_io.py:33`).

**V3 — Welcome line removed**: two `try/except + console.print` blocks deleted from `cli.py` (~line 3933–3944 TUI path, ~9322–9330 REPL path). Skin `welcome` branding field kept.

**V4 — 2-col gutter**: `UserMessagePanel` padding `0 1` → `0 2`. Input `#input-chevron` unchanged (already `width: 2`). Browse pips at col 0 — indent keeps col 0 clear.

**V5 — HintBar separator**: `_SEP = "  [dim]·[/dim]  "` → `_SEP = " [dim]·[/dim] "` in `status_bar.py:39`.

**V6 — Meta contrast**: `_render_normal()` in `renderers.py`. Add `v = {}` before try block; add `meta_color = v.get("foreground", "#aaaaaa")` after try/except; replace `style="dim"` with `style=meta_color` at the two `metrics_text` / `ts_text` append calls. `foreground` is a Textual built-in variable (no TCSS declaration needed).

**V7 — Input focus border**: `hermes.tcss` `HermesInput:focus` block gains `border: tall $primary 30%;`. Intentional reversal of prior `border: none` design.

**V8 — Second accent color**: new `accent-interactive` token (`#00bcd4` cyan, distinct from orange brand).
- `COMPONENT_VAR_DEFAULTS` in `theme_manager.py`: `"accent-interactive": "#00bcd4"` — Python fallback for all skins without the key.
- `hermes.tcss`: declare `$accent-interactive: #00bcd4;` with other variable declarations (required for TCSS parse — Textual doesn't support CSS `var()` fallback syntax).
- `HintBar._get_key_color()` in `status_bar.py`: `v.get("accent-interactive", v.get("primary", "#5f87d7"))`.
- All 4 skins (`catppuccin`, `matrix`, `solarized-dark`, `tokyo-night`): add `accent-interactive:` under `component_vars:` with skin-appropriate color.

**Tests**: 9 new — `tests/tui/test_banner.py` (new), additions to `test_status_widgets.py`, `test_thinking_widget_v2.py`, `test_theme_manager.py`.

### 2026-04-22 — ThinkingWidget v2 — composable anim engine + text effect (commit c330aada, merged feat/textual-migration c0f22ac9)

**New file: `hermes_cli/tui/widgets/thinking.py`** — replaces 120-line hand-rolled helix in `message_panel.py`.

**Architecture — three new classes:**
- `ThinkingMode(StrEnum)` — `OFF / LINE / COMPACT / DEFAULT / DEEP`
- `_AnimSurface(Widget)` — drives any `_ENGINES` entry via `engine.next_frame(params) → str`; `render_line(y)` slices stored frame strings; parent drives ticks
- `_LabelLine(Static)` — calls `effect.tick_tui()` then `effect.render_tui(label_text, accent_hex, text_hex)` → Rich `Text`; calls `self.update(rich_text)`

**`ThinkingWidget` modes and heights:**

| Mode    | Height | Anim rows |
|---------|--------|-----------|
| OFF     | 0      | 0         |
| LINE    | 1      | 0         |
| COMPACT | 2      | 1         |
| DEFAULT | 3      | 2         |
| DEEP    | 5      | 4         |

Mode resolution at `activate()`: explicit arg → `self.app.compact == True` → config `tui.thinking.mode`.

**Effect instantiation:**
```python
from hermes_cli.stream_effects import make_stream_effect
effect = make_stream_effect({"stream_effect": effect_name}, lock=None)
```
`make_stream_effect` reads `cfg["stream_effect"]`, not a bare key.

**Static-label effect whitelist** (must work without incoming tokens):

| Key | Mechanism |
|---|---|
| `breathe` (default) | `time.monotonic()` in `render_tui` |
| `glow_settle` | `tick_tui()` overridden |
| `cosmic` | `tick_tui()` overridden |
| `nier` | `tick_tui()` overridden |
| `flash` | `tick_tui()` overridden |

**`shimmer` EXCLUDED** — `_pos` advances only via `_register_terminal()` (token arrival). Called on a static label it freezes. Default is `breathe`.

**Engine whitelist keys (exact `_ENGINES` dict keys):**
- Small modes (≤2 anim rows): `dna`, `rotating`, `classic`, `morph`, `thick`, `wave`, `lissajous_weave`, `aurora_ribbon`, `rope_braid`, `perlin_flow`, `wave_function`
- DEEP (4 anim rows) adds: `vortex`, `kaleidoscope`, `neural_pulse`, `mandala_bloom`, `plasma`, `matrix_rain`, `wireframe_cube`, `torus_3d`, `sierpinski`, `flock_swarm`, `strange_attractor`, `hyperspace`, `fluid_field`, `conway_life`

Non-whitelisted engine for small mode → fall back to `dna` + debug log.

**Four substates** — updated in `_tick`:
- `STARTED` (first 500ms) — `flash` effect overrides label
- `WORKING` — configured engine + effect
- `LONG_WAIT` (after `long_wait_after_s=8s`) — label becomes `Thinking… (Ns)`
- `ABOUT_TO_STREAM` — set by `deactivate()`; 150ms fade via `set_timer(0.15, _do_hide)`

**Two-phase deactivate** (`set_timer`, not `call_later`):
```python
def deactivate(self):
    if self._substate == "ABOUT_TO_STREAM":
        return  # no-op, already fading
    self._substate = "ABOUT_TO_STREAM"
    self.set_timer(0.15, self._do_hide)

def _do_hide(self):
    if not self.is_attached:
        return
    if self._timer:
        self._timer.stop()
        self._timer = None
    self.remove_class("--active", "--mode-line", "--mode-compact", "--mode-default", "--mode-deep")
    self._substate = None
```

**`HERMES_DETERMINISTIC` guard** in `activate()` — returns immediately, keeps widget hidden in CI.

**Engine `on_mount` hook** checked with `hasattr(engine, "on_mount")` before call — existing DrawbrailleOverlay convention.

**Migration:**
- `message_panel.py` old `ThinkingWidget` class body removed; replaced with `from hermes_cli.tui.widgets.thinking import ThinkingWidget  # noqa: F401`
- `widgets/__init__.py` import redirected from `.message_panel` to `.thinking`
- All 4 existing call sites (`_app_key_handler.py:543,553`, `_app_io.py:70`, `__init__.py:310,333`) unchanged

**Tests:** 18 in `tests/tui/test_thinking_widget_v2.py` + 4 updated in `test_thinking_widget_activate.py`.

**Key gotchas:**
- `call_later(callback)` has NO delay param in Textual 8.x — for a timed callback use `set_timer(delay_s, callback)` not `call_later(0.15, cb)`
- `compose()` yields nothing — `_AnimSurface` and `_LabelLine` are mounted dynamically in `activate()` to avoid constructing them before mode and engine are known
- `shimmer` freezes on static text — always use `breathe` as default for non-streaming labels

### 2026-04-22 — ResponseFlowEngine parser hardening (commits cc3b75be + 94926cd8, merged feat/textual-migration)

**5 bugs fixed in `hermes_cli/tui/response_flow.py` and `widgets/code_blocks.py`:**

**P1 — `_code_fence_buffer` in wrong scope**: was re-initialized to `[]` at the end of `_write_prose()` body, resetting on every prose write. Moved to `ResponseFlowEngine.__init__`. `ReasoningFlowEngine` already had it correct; `ResponseFlowEngine` missed it.

**P2 — Missing imports in `flush()`**: `flush()` used `apply_block_line` / `apply_inline_markdown` without importing them. `process_line()` imports them locally (function-scoped); those bindings are NOT in scope inside `flush()`. Added `from agent.rich_output import apply_block_line, apply_inline_markdown` at top of `flush()`. Latent `NameError` when `_pending_source_line` was non-None at turn end.

**P3 — `_commit_prose_line()` dead code**: defined but never called; the prose path called `_write_prose()` directly everywhere. Wired into Phase 5 of `process_line()` (emoji-else branch flushes; normal path calls `_commit_prose_line`). Also wired into `_flush_block_buf()` (replaced direct `_prose_log.write_with_source` call). Added explicit `_flush_code_fence_buffer()` call in `flush()` before `_render_footnote_section()`. InlineCodeFence now accumulates and mounts correctly.

**P4 — Stray `_flush_code_fence_buffer()` in `_mount_math_image()`**: unrelated to math rendering, leftover from earlier refactor. Removed.

**P5 — `_looks_like_source_line()` `=`-heuristic false positives**: `"=" in raw and "==" not in raw and len <= 8` triggered on prose like "the value is x = 5". Replaced with `re.match(r'^\s*\w+\s*=\s*\S', raw) and "==" not in raw and len <= 6` — anchored to line start, so only lines beginning directly with `identifier =` fire.

**`StreamingCodeBlock` mermaid stub fixed** (P0 blocker): `_try_render_mermaid_async()` was a no-op stub. Implemented: daemon thread → `render_mermaid()` → `app.call_from_thread(_on_mermaid_rendered, path)`. `_on_mermaid_rendered(None)` now falls back to `_render_syntax(skin_vars)` instead of returning silently. `_complete_skin_vars` stored at `complete()` time so fallback has theme context.

**Key gotchas from this work:**
- `StreamingBlockBuffer` (SBB) holds one line in lookahead. Numbered lines arrive in `_commit_prose_line` one turn LATE (not when `process_line` receives them, but when the next line flushes SBB). Pre-flushing the numbered-line buffer BEFORE `_commit_prose_line` adds the current line breaks accumulation. Flush only in the emoji-else branch; let `_commit_prose_line` handle flushing for the normal path.
- `_flush_block_buf()` wrote directly to `_prose_log` — when wiring a new buffer route, ALL prose-writing paths must go through the same funnel or lines escape the accumulator.

**Tests**: 17 new in `tests/tui/test_response_flow_parser.py`; F3–F7 added to `test_math_renderer.py`.

### 2026-04-22 — 5 new anim engines + /anim improvements + overlay drag (commit 0c05c223, feat/textual-migration)

**New engines (`anim_engines.py`)** — 26 engines total (was 21):
- `WireframeCubeEngine` — orthographic rotating cube, depth-sorted edges via `_bresenham_pts`, `on_signal("complete")` → `_spin_brake` slow-stop
- `SierpinskiEngine` — IFS chaos game via `TrailCanvas`; `_SQUARE_TRANSFORMS`/`_TRIANGLE_TRANSFORMS` are **class-level tuples** (never lambdas inside `next_frame`)
- `PlasmaEngine` — summed sine plasma; `y_sine2` (entire 2nd sine term) hoisted outside xi loop — saves W LUT calls/row
- `Torus3DEngine` — N_U=20×N_V=36 wireframe torus; `_THETA_LUT`/`_PHI_LUT` class-level precomputed (720 divisions eliminated); `_TORUS_TILT_COS/SIN` module-level constants
- `MatrixRainEngine` — falling column particles via `TrailCanvas`; error surge mode; complete-reinit countdown

**`_bresenham_pts(x0, y0, x1, y1) → list[tuple[int,int]]`** — new module-level helper in `anim_engines.py`. Callers apply bounds check per point.

**Gotchas for animation engines:**
- `TrailCanvas.frame()` = `decay_all()` + render. Never call `tick()` (doesn't exist) or `decay_all()` separately.
- `_PHASE_CATEGORIES` unchanged — engines slot in via `_ENGINE_META["category"]` automatically; never add engine keys directly to `_PHASE_CATEGORIES` lists
- Class-level Python list comprehensions cannot reference earlier class attrs by name (scope rule) — use literals: `_THETA_LUT = [u * (2*math.pi/20) for u in range(20)]`

**Overlay drag + position (D1/D2, `drawbraille_overlay.py`):**
- `_POS_GRID: list[list[str]]` (3×3), `_POS_TO_RC: dict[str, tuple[int,int]]` (col, row) — module-level
- `_set_offset(ox, oy)` helper on `DrawbrailleOverlay`: sets `styles.offset` AND `_drag_base_ox/oy` together. Replace all 3 `self.styles.offset =` calls in `_apply_layout` with `_set_offset` — keeps drag base in sync regardless of which layout path fires
- `on_mouse_up` snaps via `_nearest_anchor` then calls `self.app._persist_anim_config(...)` — overlay can't call `_CommandsMixin` methods directly; must go via `self.app`
- D1 key binding: `Ctrl+Shift+Arrow` — `alt+up/alt+down` are taken by browse-mode turn navigation (lines 382–389 of `_app_key_handler.py`)
- `App.capture_mouse(self)` / `App.release_mouse()` present in Textual 8.2.3; wrap in `try/except AttributeError` for compat

**`/anim` commands (`_app_commands.py`):**
- `ov.fps = fps` (reactive assignment) — NOT `ov._fps`
- `ov._visibility_state` lives on `DrawbrailleOverlay`, not `_CommandsMixin` — check `ov._visibility_state`, not `self._visibility_state`
- Gradient hex validation: inner `_validate_hex(raw) → str | None` strips `#`, checks exactly 6 lowercase hex chars; apply to BOTH color1 and color2 args

### 2026-04-22 — Tool UX Audit Pass 10 (7 commits, merged feat/textual-migration)

19 fixes / 10 themes (A–J). Key deletions: `tool_header_bar.py`, `result_pill.py`, `tool_panel_mini.py` removed. `detail_level` reactive retired. 7 implementation phases.

**A1–A3: ToolHeaderBar/ResultPill/ToolPanelMini deleted**:
- `tool_header_bar.py` deleted — `ToolHeaderBar` was a v3 residual duplicating `ToolHeader._render_v4`. Compact-sync now lives in `services/watchers.py` (`WatchersService`) and works directly with `ToolPanel._header`.
- `result_pill.py` deleted — dead code, no call sites.
- `tool_panel_mini.py` deleted — `ToolPanelMini` / `--minified` class approach replaced by two-tick completion sequence (E1/E2).
- Tests in `test_tool_header_bar.py` and `test_tool_panel_mini.py` updated to test ToolPanel/ToolHeader interfaces directly.

**B1/B2: Hint tier model**:
- Tier 1 (always shown): primary action hints. Tier 2 (focus-shown): copy/collapse. Tier 3 (? → show): all others.
- `_build_hint_text()` builds tier list; `?` binding toggles `_hints_expanded: bool` on ToolPanel.

**C1/C2: detail_level retired**:
- `detail_level: reactive[int]` (L0–L3 stub) removed from ToolPanel. `collapsed: bool` is the sole collapse axis.
- `toggle_l0_restore` action removed. All `detail_level` references in tests migrated.

**D1/D2: ChildPanel gutter**:
- ChildPanel drops `ToolAccent` border-left — uses `_is_child: bool` class attribute instead.
- `_is_child = True` suppresses `┊` gutter connector. `SubAgentBody` padding capped at 2.

**E1/E2: Two-tick completion + opt-in mini-mode**:
- E1: ToolPanel completion uses two-tick deferred collapse: tick 1 marks `--completing`, tick 2 applies final collapsed state. Prevents flash.
- E2: `/density auto-mini` is explicit opt-in; not default. `--minified` CSS class approach retired with `tool_panel_mini.py`.

**F1: Keybind fix**: `?` → `show_help`, `f1` → `show_context_menu` (corrected from earlier pass).

**G1: OmissionBar 2-button default + [more ▸] toggle**:
- Default shows `[show all]` + `[hide]` only. Advanced buttons hidden behind `[more ▸]` toggle.
- Rich markup gotcha: `Button("[show all]", ...)` renders as empty — `[show all]` parsed as markup tag. Fix: `Button(Text("[show all]"), ...)` using `rich.text.Text`.
- `set_counts()` checks `self._narrow` to avoid overwriting label set by `_sync_narrow_layout()`.

**H1: Retire v2 grouping CSS**:
- Removed `panel.add_class(f"group-id-{group_id}")` and `panel.add_class("tool-panel--grouped")` from `tool_group.py:_do_apply_group_widget`.
- Removed corresponding v2 CSS rules from `hermes.tcss`. Only v4 `ToolGroup` widget grouping remains.

**I1/I2: ReasoningPanel**:
- I1 race fix: `append_delta` calls `self.add_class("visible")` defensively before `open_box` can race with first delta.
- I2: Removed `"click to expand"` from collapsed stub — redundant with click affordance. Stub now: `"▸ "` + `"Reasoning collapsed · NL"`.

**ReasoningPanel last-line duplication fix (fix/tool-ux-pass6)**:
- Root cause: `close_box` committed `_live_buf` to `_reasoning_log` BEFORE hiding `_live_line`, leaving a render window where both showed the same content.
- Fix: `close_box` now clears `_live_buf`, hides `_live_line`, and calls `update("")` BEFORE calling `process_line(buf)`.
- Also fixed: `ReasoningFlowEngine.__init__` was missing `_prose_callback: Callable | None = None` — caused `AttributeError` in `_write_prose` since `ReasoningFlowEngine` doesn't call `super().__init__()`.
- Gotcha: `ReasoningFlowEngine` manually re-declares all `ResponseFlowEngine` fields — any new field added to `ResponseFlowEngine.__init__` must ALSO be added to `ReasoningFlowEngine.__init__`.

**J1/J2: ExecuteCodeBlock / WriteFileBlock**:
- J1: ECB label stays constant (initial_label / tool name). First code line goes to `_header._header_args = {"snippet": ...}` truncated to 40 chars. Line count suffix appended to snippet.
- J2: WFB merged `_writing_hint` + `_progress_label` into single `_progress: Static`. Text transitions `"writing…"` → `"writing · NKB"` via `update_progress()`. Legacy aliases kept for any external callers.

**Key gotchas (new in Pass 10)**:
- Rich bracket eating: `Button("[foo]", ...)` → empty label. Always wrap bracket-containing labels with `rich.text.Text("[foo]")`.
- D3 OmissionBar: bar stays visible when `cap_msg` exists even if all lines shown — tests expecting `display is False` when `total > visible_cap` are wrong.
- `_header._header_args` dict (not `_label`) carries arg-summary content; `_render_v4` reads it for the secondary display line.

### 2026-04-22 — Nested Agent Tool Tree (commit f90cda34, merged feat/textual-migration)

**Data model** (`hermes_cli/tui/services/tools.py`):
- `_ToolCallRecord` dataclass replaces `list[dict]` for `_turn_tool_calls` (now `dict[str, _ToolCallRecord]`). Fields: `tool_call_id`, `parent_tool_call_id`, `label`, `tool_name`, `category`, `depth`, `start_s`, `dur_ms`, `is_error`, `error_kind`, `mcp_server`, `children: list[str]`.
- `_agent_stack: list[str]` on `HermesApp` — event-loop stack; push AFTER parent assignment, pop in BOTH `close_streaming_tool_block` paths (before completion hook).
- `classify_tool("Task")` → `ToolCategory.UNKNOWN`; only `"think"`, `"plan"`, `"delegate"` → `ToolCategory.AGENT`. Use `tool_name="delegate"` in tests needing AGENT stack push.
- `current_turn_tool_calls()` — serializes `_turn_tool_calls.values()` to `list[dict]` with all required keys incl. `children`, `depth`, `parent_tool_call_id`.

**SubAgentPanel** (`sub_agent_panel.py`):
- Binary `collapsed: reactive[bool]` — `CollapseState` IntEnum removed (D3). `action_toggle_collapse` is the sole collapse action.
- `SubAgentBody(Vertical)` — named subclass required for TCSS type selectors; plain `Vertical` won't match
- `SubAgentHeader` — aggregate header; `_set_gutter(is_child_last: bool)` takes only `bool` (no `None` overload)
- `watch_collapsed(v: bool)`: `if not self.is_mounted: return` guard; sets `--collapsed` class; `_body.display = (not v) and _has_children`
- `add_child_panel` — tracks `_is_child_last` gutter flag on previous child via `_tool_header._is_child_last`
- `_notify_child_complete` — NOT `on_*` prefix (would trigger Textual auto-dispatch)

**ChildPanel** (`child_panel.py`):
- `ChildPanel(ToolPanel)` with `BINDINGS = [Binding("space", "toggle_compact", show=False, priority=True)]`
- `_tool_header` property: `return self._block._header`
- `set_result_summary` uses wall-clock `_start_time` for duration — `ResultSummaryV4` has no `duration_ms`
- `watch_collapsed` is a no-op (compact driven by CSS class, not collapsed reactive)

**MessagePanel wiring** (`widgets/message_panel.py`):
- `_subagent_panels: dict[str, Any]`, `_child_buffer: dict[str, list]`, `_flush_scheduled: set[str]` — `_child_buffer` (NOT `_pending_children`; Textual Widget internals use that name as a list)
- `_mount_nonprose_block(block, parent_tool_call_id=None)` — AGENT→SubAgentPanel, child non-AGENT→ChildPanel, top-level→ToolPanel; buffers racing children
- AGENT panels registered in `_subagent_panels` BEFORE `_mount_nonprose_block` call
- `_flush_child_buffer` uses `discard()` to re-arm future scheduling on next arrival

**Browse & overlay** (`_browse_types.py`, `tools_overlay.py`):
- `BrowseAnchorType.SUBAGENT_ROOT = "subagent_root"`, glyph `"🤖"` in `_BROWSE_TYPE_GLYPH`
- `ToolsScreen._tree_view: bool = True`; `Binding("t", "toggle_view", ...)` added
- `_get_ordered_records(records)` — DFS for tree (returns `list[tuple[dict, int]]`), flat at depth 0 for timeline

**CSS gotchas**:
- `border-left: vkey $text-muted` fails at TCSS parse time — use literal hex: `border-left: vkey #666666 60%`
- `--collapsed` must appear AFTER `--has-children` in TCSS (equal specificity 0,1,1; last-declared wins)
- `ChildPanel.--compact ToolBodyContainer { display: none; }` hides body in compact mode

**Testing patterns**:
- Never use `Widget.__new__(Widget)` — bypasses `Widget.__init__`, breaks `_reactive_*` dict storage → `ReactiveError`
- `MagicMock(spec=SubAgentPanel)` has no `set_compact` (SubAgentPanel doesn't either); simplify assertions
- `_pending_children` is a Textual Widget internal list — naming conflicts cause `'list' object has no attribute 'setdefault'`
- Patch `_maybe_start_group` at `hermes_cli.tui.tool_group._maybe_start_group` (defined there, imported inside function)
- Use real `Static("x")` widget (not MagicMock) for tests that trigger `call_after_refresh` flush paths

### 2026-04-22 — TabbedSkinOverlay 3-tab /skin picker + override persistence layer (commit 2360764d, feat/textual-migration)

**Replaces `SkinPickerOverlay`** (`overlays.py`) with `TabbedSkinOverlay(Widget)`. Alias `SkinPickerOverlay = TabbedSkinOverlay` kept for backward compat — no import changes elsewhere.

**Three tabs**:
- Tab 1 (Skin): OptionList of skin files; arrow → live preview; Enter → `_confirm_skin()` persists `display.skin` and re-populates list; overlay stays open
- Tab 2 (Syntax): OptionList of 10 Pygments themes from `skin_engine.SYNTAX_SCHEMES`; arrow → `apply_skin({"preview-syntax-theme": name})`; Enter → `save_skin_override("vars.preview-syntax-theme", name)`; FIXTURE_CODE (7-line fibonacci) below list for live preview
- Tab 3 (Options): buttons for cursor colour, anim colour, bold toggle, spinner style

**Tab switching**: `1`/`2`/`3` digit keys + `Tab`/`Shift+Tab` cycle. All bindings need `priority=True` in BINDINGS to intercept before OptionList. `_show_tab_display(tab_idx)` — toggles widget `.display` without focus change. `_show_tab(tab_idx)` — calls `_show_tab_display` then focuses primary widget.

**Snapshot/revert pattern**:
- `_take_snapshot()` called on `show_overlay()` — captures `_css_vars` (minus `"component_vars"` key) + `_component_vars` separately
- `action_dismiss()` — calls `apply_skin({**_snap_css_vars, "component_vars": _snap_component_vars})` before `_dismiss_overlay_and_focus_input`
- Must strip `"component_vars"` from `_css_vars` snapshot: `load_dict()` extracts it but may leave traces; stripping prevents collision on restore
- Tab-level Enter persists that tab's setting only — overlay stays open for more changes

**Override persistence layer** (`config.py`, `theme_manager.py`):
- `display.skin_overrides: {"vars": {}, "component_vars": {}}` in `DEFAULT_CONFIG` and `config.yaml`
- `read_skin_overrides() → dict` — reads current overrides; `save_skin_override(key_path, value)` — dot-path setter (e.g. `"vars.preview-syntax-theme"`)
- `ThemeManager._apply_overrides(overrides)` — `_css_vars.update(vars)` + `_component_vars.update(component_vars)`
- `ThemeManager.load()` calls `_apply_overrides(read_skin_overrides())` after file load — overrides persist across skin switches
- `load_dict()` intentionally does NOT call `_apply_overrides()` — dict calls are live overlay previews; running overrides over them would prevent preview from showing different values

**`preview-syntax-bold`** — new Python-only CSS var (not in `COMPONENT_VAR_DEFAULTS`, not in `.tcss`). `"true"` (default) = bold/italic token modifiers retained; `"false"` = stripped via `_strip_bold(style_str)` helper in `code_blocks.py`. `StreamingCodeBlock.refresh_skin()` reads it.

**`_app_commands.py`** change: `/skin` handler changed `overlay.query_one("#spo-list").focus()` → `overlay._show_tab(0)`.

**`_app_theme.py`** addition: `_apply_override_dict(overrides)` on `_ThemeMixin` — wraps `tm._apply_overrides(overrides); tm.apply()`.

**Testing gotchas**:
- `Widget.app` is a read-only ContextVar property — `ov.app = mock_app` raises `AttributeError`. Must use `patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app)` inside a `with` block.
- `ov.compose()` requires an active Textual app (uses `with Vertical(...)` context manager). Tests that only need BINDINGS should read `TabbedSkinOverlay.BINDINGS` directly.
- `load_dict()` must NOT call `_apply_overrides()` — 2 tests verify this isolation (T-OVR-06b).
- 40 tests in `tests/tui/test_tabbed_skin_overlay.py` (T-TSO-01–15, T-OVR-01–09+06b, T-OPT-01–12)

### 2026-04-22 — Overlay specs: CommandsOverlay filter, PickerOverlay base, UsageOverlay chart

**CommandsOverlay** (`overlays.py:401`):
- Filter `Input(id="commands-search")` + `_lines_cache: list[str]` + `show_overlay()` + `_populate()` + `on_input_changed()`
- `show_overlay()` clears input value, focuses it, then calls `_populate(self._lines_cache)` — programmatic `.value = ""` does NOT fire `on_input_changed`, explicit `_populate()` call is required
- `q` binding at `priority=False` — inserts into Input when focused, dismisses when overlay itself is focused

**PickerOverlay base class** (`overlays.py:974`):
- Abstract base for `VerbosePickerOverlay`, `ModelPickerOverlay`, `SkinPickerOverlay`
- `_css_prefix: str` — set on each subclass; drives widget IDs (`#{prefix}-list`, `#{prefix}-header`)
- `refresh_data(cli)` → `_render_options()` — subclasses update `self.choices` and `self.current_value`, then call `super().refresh_data(cli)`
- `choices` is a class variable — subclasses that compute choices dynamically MUST assign to `self.choices` (instance attr), NOT mutate `cls.choices`
- `ModelPickerOverlay` and `SkinPickerOverlay` override `compose()` fully (extra `#mpo-current` / `#spo-current` Static between header and list); `PickerOverlay.compose()` is NOT called via `super()`
- `SkinPickerOverlay` overrides `action_dismiss()` to revert skin; calls `super().action_dismiss()` at end
- `YoloConfirmOverlay` and `ReasoningPickerOverlay` remain standalone `Widget` subclasses — structural mismatch (Buttons not OptionList)

**UsageOverlay** (`overlays.py:140`):
- `_build_chart(inp, cr, cw, out) -> str` — proportional bars (each bucket as fraction of total), `BAR_WIDTH=30`, `round()` for fill, skips zero buckets
- `_build_sparkline(turn_log) -> str` — 8 block chars `▁▂▃▄▅▆▇█`, caps at 40 entries, returns `""` when log empty
- `_do_copy()` reads `self._last_plain_text` (pre-built by `refresh_data`) and calls `self.app._copy_text_with_hint()`
- `c` key handler lives in `_KeyHandlerMixin.on_key` (NOT on the overlay) — overlay doesn't capture focus; HermesInput retains it; key events from HermesInput bubble to App, not to sibling overlay widget
- Guard pattern: `if _uov.has_class("--visible"): _uov._do_copy(); event.prevent_default(); return`

**Testing patterns from this work**:
- `_ChartHelper` pattern — for pure-function tests on Widget methods that don't use Textual internals (only `self._BAR_WIDTH` etc.), create a plain helper class with the relevant attrs and assign the unbound method: `class _ChartHelper: _BAR_WIDTH = 30; _build_chart = UsageOverlay._build_chart`. No `Widget.__new__` needed.
- `Static.content` not `.renderable` — `str(widget.query_one("#id", Static).content)` to get text; `.renderable` raises `AttributeError` in Textual 8.x
- Patching function-local imports: `from agent.usage_pricing import estimate_usage_cost` inside a method → patch `agent.usage_pricing.estimate_usage_cost` (source module), NOT `hermes_cli.tui.overlays.estimate_usage_cost` (never bound there)
- App-level key handler testing: call `app.on_key(MagicMock(key="c"))` directly; use `event.prevent_default.assert_called()` to verify consumption
- T1 exact string: assert `result == "  (no token data yet)"` not `"no token data yet" in result.lower()` — 2-space prefix is part of the contract

### 2026-04-22 — TUI Visual Polish pass D1–D13 (commit 79864de5, merged feat/textual-migration cc897d06)

101 tests in `tests/tui/test_tui_polish.py`.

**D2 — Gutter unification (4 cells everywhere)**:
- `_is_child` → `Text("    ", style="dim")`, gutter_w=4
- unfocused top-level → `"  ┊ "`, focused → `"  ┃ "`
- SubAgentPanel child-last → `" └─ "` (was `"  └─ "` 5), non-last → `" ├─ "` (was `"  ├─ "` 5)

**D3 — SubAgentPanel binary collapse**:
- `CollapseState` IntEnum **removed**. Binary `collapsed: reactive[bool]` is the sole model.
- `action_toggle_collapse` replaces `action_cycle_collapse`. `COMPACT` state retired.
- `on_mount`: `self.collapsed = True` for depth≥1.
- `watch_collapsed(v: bool)`: early-return if `not self.is_mounted`; sets `--collapsed` class; sets `_body.display = (not v) and _has_children`.
- `SubAgentHeader.on_click` calls `action_toggle_collapse` (not `action_cycle_collapse`).

**D4 — Overlay border-title via Textual property**:
- All 9 overlays: `border_title`/`border_subtitle` set in `on_mount()` / `show_overlay()` / `open_sessions()` etc. — no internal `Static` header widget.
- `YoloConfirmOverlay`: `border_title = "YOLO mode"` in `on_mount`; `border_subtitle = "ACTIVE"/"inactive"` in `refresh_data()`.
- `PickerOverlay.on_mount()`: `self.border_title = self.title` — all picker subclasses share this.
- `ModelPickerOverlay` and `SkinPickerOverlay` override `compose()` fully — they call their own `on_mount()` since they don't call `super().compose()`.
- `hermes_cli/tui/_hint_fmt.py`: `hint_fmt(pairs, key_color="") -> str` with `_SEP = "  ·  "` separator.

**D5 — `_nf_or_text(glyph, fallback, app=None)` in utils.py**:
- Returns `fallback` if `HERMES_ACCESSIBLE` or `HERMES_NO_UNICODE` set.
- Returns `fallback` if `app.console.color_system in (None, "standard")`.
- Otherwise returns `glyph`. Used for Nerd Font glyphs in stub rows, StatusBar active-file icon.

**D6 — StatusBar layout reorder**:
- Full-width (≥60 cols): bar+pct leads, then ctx, then model, then session.
- Narrow (<60) and minimal (<40): unchanged (model leads).
- Active-file uses `_nf_or_text("", "editing", app=app)` not raw emoji.

**D7 — Flash color simplified**:
- `_flash_style = "dim red" if h._flash_tone == "error" else f"dim {accent_color}"`
- No per-tone branches; warning/neutral/success all use accent.

**D8 — ReasoningPanel collapsed stub**:
- Gutter `"  ┊ "` (4 cells), icon `_nf_or_text("", "[R]", app=self.app)`, label "Reasoning".
- Segments: linecount + chevron, trimmed via `_trim_tail_segments`.

**D9 — SubAgentHeader badge**:
- Uses `_format_elapsed_compact` + `_trim_tail_segments`. Calls/errors/duration as named segments.
- Error style `f"bold {warn_color}"`. State classes: `--has-errors` / `--done`.

**D10 — ThinkingWidget → ReasoningPanel handoff**:
- `ThinkingWidget --active { border-left: vkey $primary 15%; }` in DEFAULT_CSS.
- `ReasoningPanel.open_box()` calls `tw.deactivate()` on any active ThinkingWidget via try/except.

**D11 — _EchoBullet color fallback**:
- Fallback key changed from `"rule-accent-color"` → `"primary"`. `"rule-accent-color"` not in COMPONENT_VAR_DEFAULTS.

**D12/D13 — Tail zone ordering**:
- `_DROP_ORDER = ["flash", "linecount", "chip", "hero", "diff", "stderrwarn", "chevron"]`
- Zone order in `_render_v4`: STATS (duration) → CONTROL (flash) → META (stderrwarn). stderrwarn style `f"bold {warn_color}"`.

**Key gotchas from this work**:
- `Widget.size`, `Widget.app`, `Widget.content_size`, `Widget.is_mounted` are **data descriptor properties with no setter**. Setting them on `object.__new__` instances fails. Use `patch.object(type(obj), 'size', new_callable=PropertyMock, return_value=Size(80,1))`.
- `border_title`/`border_subtitle` are reactives — calling `on_mount()` on a raw `object.__new__` instance raises `ReactiveError`. Use `inspect.getsource(Cls.on_mount)` to test assignment.
- Rich `Text("foo", style="dim red")` stores style on `t.style`, NOT `t._spans`. Check `str(t.style)` not `t._spans[0].style`.

### 2026-04-22 — Nameplate active-idle pulse + AnimConfigPanel expansion (commits 7030342f + adc1d016, feat/textual-migration)

**Nameplate pulsing (`widgets/__init__.py`):**
- `_NPState.ACTIVE_IDLE` previously stopped the timer — nameplate was static while agent ran.
- Now keeps timer alive at 12fps after morphing/glitching completes; calls `_tick_active_idle()` → advances `_active_phase` by 0.18 rad/frame.
- `_render_active_pulse()`: per-character `wave = (sin(_active_phase - i * 0.55) + 1.0) / 2.0` → `_lerp_hex(dim, accent, wave)`. Creates traveling sine shimmer.
- `_lerp_hex(a, b, t) -> str`: module-level helper, interpolates two hex colors by component (integer truncation — `int(r_a + t*(r_b - r_a))`).
- `_active_dim_hex`: computed once in `on_mount` as `_lerp_hex("#000000", accent, 0.30)` — 30% accent so shimmer has meaningful range.
- Both `_tick_morph` done-branch AND `_tick_glitch` done-branch resume 12fps instead of stopping.

**AnimConfigPanel expansion (`drawbraille_overlay.py`):**
- `_multi_color_row_buf: list = []` added as **class-level attr** on `DrawbrailleOverlay` — prevents `AttributeError` in tests that create the widget without mounting it.
- New fields in `_build_fields`: `enabled` toggle (first field), `hue_shift_speed` float, ambient section (`ambient_enabled`, `ambient_engine`, `ambient_heat`, `ambient_alpha`), carousel section (`carousel`, `carousel_interval_s`).
- `fps` max raised 15 → 30.
- `_push_to_overlay`, `_current_panel_cfg`, `_fields_to_dict` all updated to handle new fields (ambient/carousel as `None` in attr_map — applies via `_push_custom_field`).
- **`_persist_anim_config` merge fix** (`_app_commands.py`): was calling `_set_nested(cfg, "display.drawbraille_overlay", cfg_dict)` which replaced the whole overlay dict. Fixed to: `existing = cfg.setdefault("display", {}).setdefault("drawbraille_overlay", {}); existing.update(cfg_dict)`.

**Test fixes:**
- `test_cycle_animation_*`: use `next(f for f in panel._fields if f.name == "animation")` not `_fields[0]` (enabled is now first).
- `test_fps_inc_clamps_at_15`: changed to `int(fps_field.max_val)` dynamically (max raised to 30).

### 2026-04-22 — Bundled skin audit + 3 new skins (commit fdff67c7, merged feat/textual-migration b02ad1b5)

**Audit result**: all 5 custom skins (`~/.hermes/skins/`) were 47/47 `component_vars`. Repo's `skins/matrix.yaml` was 29/47 — missing 18 keys from dev passes 5-10.

**matrix.yaml backport** — 18 added: `browse-*` (5), `cite-chip-*` (2), `diff-add/del-bg` (2), `footnote-ref-color`, `nameplate-*` (3), `panel-border`, `spinner-shimmer-*` (2), `tool-mcp-accent`, `tool-vision-accent`.

**3 new bundled skins** (all 47/47, committed to `skins/`):
- `tokyo-night`: deep navy `#1a1b26`, blue `#7aa2f7` accent, `preview-syntax-theme: tokyo-night`
- `catppuccin`: Mocha dark `#1e1e2e`, lavender `#cba6f7` accent, `preview-syntax-theme: catppuccin`
- `solarized-dark`: warm dark `#002b36`, blue `#268bd2` + teal `#2aa198` accents, `preview-syntax-theme: solarized-dark`

**Skin completeness checklist**: after any new `COMPONENT_VAR_DEFAULTS` key, run:
```python
python3 -c "
import yaml, os
DEFAULTS = set()  # populate from theme_manager.py
for f in os.listdir('skins'):
    cvars = yaml.safe_load(open(f'skins/{f}')).get('component_vars', {})
    missing = DEFAULTS - set(cvars)
    print(f'{f}: {\"OK\" if not missing else sorted(missing)}')
"
```
- T3 fill count: use `row.count("█") == N` not `"█" * N in row` — substring match passes for rows with more filled chars
- T8 hidden-guard: assert BOTH `mock_copy.assert_not_called()` AND `event.prevent_default.assert_not_called()` — spec requires neither fires when overlay is hidden
- T10 bar exclusion: assert `"█" not in plain` — without this, bar rows leaking into plain-text copy go undetected
- T14 absent attribute: delete the attribute from MagicMock (`del agent.session_turn_token_log`) and call `refresh_data` — tests the `getattr(..., [])` guard path, not just `_build_sparkline([])`

**UsageOverlay UI polish (commit ea838836)**:
- Cost row alignment: `f"Cost:        {prefix}${value:>10.4f}"` — `$` and optional `~` sit **outside** the `>N` format spec, so the label column must absorb their width. `"Cost:        "` (13 chars) + `"$"` = 14 chars total label column, matching all other rows.
- Label case: `_build_stats` and `_build_plain_text` must use identical label strings (`"Cache Read:"`, `"Cache Write:"` — title case). Any copy-paste between the two methods risks divergence.
- Section separation: always put a blank `""` string between chart and stats sections in the `parts` list; joining with `"\n"` alone makes bar rows run directly into the model line with no gap.
- Copy error handling: `_do_copy` must NOT use bare `except Exception: pass` — call `self.app.set_status_error(f"copy failed: {exc}")` so unexpected failures surface. Clipboard-unavailability is handled inside `_copy_text_with_hint` itself, so the outer except is only for structural errors.

### 2026-04-22 — Bash passthrough mode (commit 621303d0, merged feat/textual-migration)

`!cmd` in the input bar runs a shell command and streams output into a `BashOutputBlock` in `OutputPanel` — no agent involvement.

**New files:**
- `hermes_cli/tui/services/bash_service.py` — `BashService(_svc_bash)`: `run(cmd)`, `kill()`, `_exec_sync`, `_finalize`
- `hermes_cli/tui/widgets/bash_output_block.py` — `BashOutputBlock(Static)`: `CopyableRichLog` body, elapsed timer, `--done/--error`

**`BashService._exec_sync` key details:**
- `shlex.split` before the `Popen` `try` — `ValueError` on malformed quotes caught by an explicit `except ValueError` block and displays `"[parse error] …"`, then calls `_finalize` and returns early
- `Popen(start_new_session=True)` — process gets its own pgid; `kill()` uses `os.killpg(os.getpgid(pid), SIGINT)` for full process-group kill
- `_finalize` runs on event loop via `call_from_thread`; sets `_running = False` THEN calls `block.mark_done` — prevents TOCTOU window
- `_running = True` set before `_start_bash_worker`; reset in `try/except` if worker raises; never left stuck True

**`BashOutputBlock` key details:**
- Uses `CopyableRichLog` (NOT bare `RichLog`) — avoids pre-layout width collapse when first line arrives before layout
- `push_line(line)` calls `_body.write(Text.from_ansi(line))` — ANSI colors preserved
- `on_unmount`: stops elapsed timer; calls `self.app._svc_bash.kill()` if `--running` — no orphan processes on widget removal
- Mounts into `OutputPanel` via `output.mount(block, before=output.query_one(ThinkingWidget))` — NOT into `MessagePanel` (which may not exist)

**`app.py` additions:**
- `_svc_bash = BashService(self)` — init after `_svc_commands`, before `_svc_watchers`
- `@work(thread=True, exclusive=True, group="bash") def _start_bash_worker(cmd, block)` — `exclusive=True` is Textual Worker dedup only, NOT OS process kill
- `_mount_bash_block(cmd)` — mounts before `ThinkingWidget` in `_output_panel`
- `on_unmount` calls `self._svc_bash.kill()` before hooks shutdown

**`services/keys.py` changes:**
- `dispatch_input_submitted`: `!` fork added BEFORE `_handle_tui_command` check; guards: `agent_running`, `is_running`, empty cmd
- `ctrl+c` block: bash kill inserted AFTER selection-copy check, BEFORE overlay-cancel; selection takes priority

**`input/widget.py`:** `on_text_area_changed` appends `--bash-mode` CSS class toggle + `_flash_hint(30.0)` / `feedback.cancel("hint-bar")` at end (after `_update_autocomplete`)

**CSS:** `HermesInput.--bash-mode #input-chevron { color: $chevron-shell; }` in `hermes.tcss`

**History:** `!cmd` is intentionally saved to history (`_save_to_history` fires before routing fork)

**34 tests** in `tests/tui/test_bash_passthrough.py` (T01–T31)

**Key gotchas:**
- `Widget.app` is a read-only ContextVar property. Tests for `BashOutputBlock.on_unmount` (which calls `self.app._svc_bash.kill()`) must use `patch.object(type(block), "app", new_callable=PropertyMock, return_value=mock_app)` inside a `with` block
- `_FakeInput` / plain namespace: input widget toggle tests should NOT use `object.__new__(HermesInput)` since `app` is unsettable — build a simple fake class instead
- `MessagePanel` is nested under `OutputPanel`, not a direct query target at app level. Use `self._output_panel.query_one(ThinkingWidget)` as mount anchor, not `query_one(MessagePanel)`

### 2026-04-22 — InterruptOverlay focus priority fix (116 tests pass, feat/textual-migration)

Permission prompts (approval, sudo, clarify, secret, undo, session, merge) now always paint on top of every other overlay and capture focus regardless of what was open.

**Three-file change:**

- `hermes.tcss` — Screen layers: `base overlay interrupt tooltip`. New `interrupt` layer sits between `overlay` and `tooltip`.
- `overlays/interrupt.py::InterruptOverlay` — `layer: interrupt` (was `overlay`). `_activate` now calls `self.call_after_refresh(self.focus)` after `_render_current()` so the overlay captures keyboard immediately.
- `drawbraille_overlay.py::AnimConfigPanel.on_blur` — focus trap now yields when `InterruptOverlay` has `--visible`. Without this, the trap re-stole focus back every blur event, stranding the interrupt prompt.

**Why this order matters:** the focus trap fires on every blur, so even if InterruptOverlay grabbed focus correctly, the next event loop tick would call `call_after_refresh(self.focus)` on AnimConfigPanel and steal it back. The `--visible` guard breaks the loop.

**Key gotcha:**
- Non-modal focus-trapping overlays on `layer: overlay` are painted BELOW `InterruptOverlay` (on `layer: interrupt`). Any widget that uses `on_blur` → refocus must also check `InterruptOverlay.has_class("--visible")` and bail — otherwise the focus trap fights the interrupt overlay every tick.

### 2026-04-21 — Module splits (drawbraille / tool_blocks / renderers / input)

**Track B — drawbraille**: `anim_engines.py` holds `AnimParams`, `AnimEngine`, `TrailCanvas`, `_BaseEngine`, 20 engine subclasses, `CompositeEngine`, `CrossfadeEngine`. Deleted duplicate `_GalleryPreview(Widget)` + `AnimGalleryOverlay(Widget)` that were shadowing `ModalScreen` versions (pre-existing test failure fixed).

**Track C — tool_blocks subpackage**: `OmissionBar` placed in `_shared.py` not `_streaming.py` to break circular import: `_block.py` needs `OmissionBar`; `_streaming.py` needs `ToolBlock` from `_block.py`. After splitting, `renderers.py` re-exports all public symbols so existing importers compile unchanged.

**Track D — renderers split**: Fixed `rich.strip.Strip` → `textual.strip.Strip` (Rich has no `strip` module).

**input/ subpackage**: `HermesInput` MRO must be `(_HistoryMixin, _AutocompleteMixin, _PathCompletionMixin, TextArea, ...)` — TextArea defines `update_suggestion`, which shadows the mixin's version if TextArea comes first.

**After any module split — two required steps**:
1. Add re-export lines to the original file (or `__init__.py`) so old importers still work.
2. Check for module-level names (e.g. `random`, `re`) that the old file imported but the new module does not.

### 2026-04-21 — M3 Write approval with inline diff (commit b8343f6f)

`ChoiceOverlayState` (state.py) gained `diff_text: str | None = None`. When set, `ApprovalWidget` shows a scrollable `CopyableRichLog#approval-diff` panel rendered via `DiffRenderer`.

**Approval choices:** `["once", "session", "always", "deny"]` — mirrors shell command approval. "session" adds path to `cli._write_session_allowlist: set[str]`; "always" appends to `CLI_CONFIG["write_allowlist"]` via `save_config`.

**Callback pattern:** plain module global in `tools/file_tools.py` (NOT ContextVar — ContextVar is for per-context streaming callbacks only):
```python
_write_approval_callback = None
def set_write_approval_callback(cb): global _write_approval_callback; _write_approval_callback = cb
def _request_write_approval(path, new_content): cb = _write_approval_callback; return cb(path, new_content) if cb else "allow"
```

**YOLO:** `os.getenv("HERMES_YOLO_MODE")` skips the approval prompt. Diff still appears in tool block body via `_on_tool_complete` / `_pending_edit_snapshots` — YOLO never suppresses that.

**DiffRenderer instantiation** from `ApprovalWidget.update()` requires all 5 `ToolPayload` fields + `ClassificationResult(kind=ResultKind.DIFF, confidence=1.0)`:
```python
payload = ToolPayload(tool_name="diff", category=None, args={}, input_display=None, output_raw=diff_text)
cls_result = ClassificationResult(kind=ResultKind.DIFF, confidence=1.0)
DiffRenderer(payload, cls_result).build()
```

**CSS:** `ApprovalWidget > CopyableRichLog#approval-diff` needs `overflow-y: auto` (unlike normal `CopyableRichLog` which uses `overflow-y: hidden`). Safe here because parent is not an `OutputPanel`.

**Key handler (§7):** diff scroll (Up/Down when diff has focus) and Tab cycling use `query_one("CopyableRichLog#approval-diff", CopyableRichLog)` wrapped in `try/except NoMatches`. `approval_widget.focus()` returns focus to the choices row.

**`create_file` tool absent:** `tools/file_tools.py` has no separate `create_file_tool` — only `write_file_tool` and `patch_tool` were hooked.

### 2026-04-21 — M2 Compact/responsive layout

- `compact: reactive[bool]` + `_compact_manual: bool | None = None` on `HermesApp`.
- `watch_compact` lives in `services/watchers.py` (`WatchersService`). All DOM ops wrapped in `try/except Exception` (watcher fires at reactive init before DOM exists — Textual fires `_check_watchers` during `_initialize_reactive`). CSS class mutation uses `if hasattr(self, "_classes")` guard.
- Auto-trigger: `_flush_resize` (NOT `watch_size`). `watch_size` fires on every event without debouncing; `_flush_resize` is the debounced callback (60 ms, `_RESIZE_DEBOUNCE_S`). Threshold: `w <= 120 or h <= 30`.
- Hard floor: `w < 30` forces compact even when `_compact_manual` is set.
- Tests that directly set `app.compact = True` must also set `app._compact_manual = True` — otherwise `_flush_resize` fires and resets to False based on terminal dimensions.
- StatusBar text abbreviations (model prefix strip, session truncation) gated on `compact AND width < 70` to avoid breaking tests/usage at standard 80-col terminals.
- `HERMES_DENSITY=compact` env var: set `_compact_manual = True; self.compact = True` in `on_mount` — do NOT call `add_class("density-compact")` directly.
- Compact sync (`watch_compact` in `services/watchers.py`) iterates mounted ToolPanels directly — `ToolHeaderBar` deleted in Pass 10.
- `services/sessions.py` (`SessionsService`) mutation sites for `_session_records_cache`: call `_sync_compact_visibility()` after both `init_sessions` and `_poll_session_index` mutations.
- **`/density` (NOT `/compact`) toggles layout density.** `/compact` is reserved for context compaction (forwarded to agent). The hint in `services/watchers.py:on_status_compaction_progress` already uses `/compact` for that purpose. Density slash command lives in `services/commands.py` and `_app_constants.py` as `"/density"`.
- **`action_toggle_density` else-branch uses `self.size`**: on unmounted app `size=(0,0)` so `w <= 120` is always True — restoring auto resets to compact. Tests must mock `type(app).size` as a `PropertyMock(return_value=Size(160,50))` or use `run_test(size=(140,40))`.
- **`density-compact` + `border: tall` on focused input = zero content area**: `HermesApp.density-compact HermesInput { max-height: 2; }` + `HermesInput:focus { border: tall ...; }` (2 border rows) leaves content_size.height=0. Cursor invisible, input appears broken. Fix: `HermesApp.density-compact HermesInput:focus { border: none; }`. Check `inp.content_size.height` in tests — zero means this broke again.

### 2026-04-21 — app.py 4-phase mixin extraction

Unique gotchas from this work (patterns are in Framework sections below):

- **Shared types in `_browse_types.py`**: `BrowseAnchorType`/`BrowseAnchor` live in `_browse_types.py`; both `app.py` and `services/browse.py` import from there.
- **Slash commands in `_app_constants.py`**: `KNOWN_SLASH_COMMANDS` is in `hermes_cli/tui/_app_constants.py`. Add new slash commands there only. `/density` (layout toggle) lives here; `/compact` forwards to the agent for context compaction.
- **`body_renderer.py` deleted**: all legacy streaming renderer classes moved to `body_renderers/streaming.py`; base class renamed `StreamingBodyRenderer`. Import from `body_renderers.streaming`, not the old path.
- **All `_app_*.py` mixin files deleted (R4)**: logic now lives in `services/` subpackage. Do not recreate mixin files.
- **Duplicate method bug (pre-existing)**: `app.py` had a second session block (appended during branch merges) that re-defined cached methods with inferior disk-reading versions. Always `grep -n "def method_name"` across a file before assuming a method definition is unique.

### 2026-04-21 — UX audits (Pass 9 + Full UX Audit, ~45 fixes)

Key behavioral specs implemented (structural patterns are in Framework):

- `CodeBlockFooter.flash_copy()`: flashes "✓ Copied" for 1.5 s via `_copy_flash_timer`; `--flash-copy { color: $success; }` in DEFAULT_CSS.
- `ToolPanel.action_rerun()`: calls `self._header_bar.flash_rerun()` → pulses glyph to "streaming" for 600 ms then restores `_last_state`.
- StatusBar browse badge format: `BROWSE ▸N/M`; `browse_detail_level` reactive retired with `detail_level` in Pass 10; `_apply_browse_focus()` uses `collapsed` state instead.
- `VirtualCompletionList.empty_reason: reactive[str]`; `_EMPTY_REASON_TEXT` dict; `watch_items` resets to `""` when items arrive.
- `FooterPane._narrow_diff_glyph` (Static "±") shown in compact mode when diff present.
- `CompletionOverlay.on_resize` caps `max_height = max(4, h-8)`; DEFAULT_CSS `min-height: 4`.
- `HelpOverlay.show_overlay()` clears search input and repopulates full command list on every open.
- `SessionOverlay._update_selection()` calls `scroll_to_widget` to keep selected row visible.
- `WorkspaceOverlay.show_overlay()` focuses `#ws-tab-git` button on open.
- Error-aware placeholder: when agent stops with `status_error` set, `HermesInput.placeholder` shows `Error: <snippet>… (Esc to clear)`.
- `Chip.remediation` strings from all chips joined with ` · ` into `FooterPane._remediation_row`. Not inline in chip row.
- `generic_result_v4` single-line threshold: `primary = f"✓ {n} lines" if n > 1 else "✓"` — single-line gives bare `"✓"`.
- `set_result_summary_v4` merged into `set_result_summary` — single method handles accent state, mini-mode, hero chip, promoted chips, error banner, age timer, auto-collapse, footer render. `ResultSummary` (old dataclass) still exists for v2 parsers but is no longer accepted. App callers always pass `ResultSummaryV4`.

### 2026-04-21 — API renames to track

| Old (removed) | New |
|---|---|
| `action_prev_turn` | `action_jump_turn_prev` |
| `action_next_turn` | `action_jump_turn_next` |
| scroll-based turn nav (`scroll_visible()`) | `app._jump_anchor(direction, anchor_type)` on `_browse_anchors` |
| `set_result_summary_v4` | `set_result_summary` (merged) |

### 2026-04-21 — Rendering fixes (commits 40eba1e0, c1683598)

**`render_halfblock` white-box bug** (`kitty_graphics.py:515`): PIL's `.convert("RGB")` composites transparent pixels against **white** by default. Any PNG with transparent background (e.g. matplotlib math renders) appears as a solid white rectangle. Fix: composite RGBA against `#0d0d0d` before conversion:
```python
if "A" in image.mode:
    rgba = image.convert("RGBA")
    bg = PILImage.new("RGB", rgba.size, (13, 13, 13))
    bg.paste(rgba, mask=rgba.split()[3])
    img = bg
else:
    img = image.convert("RGB")
```

**`_split_row` pipe artifacts** (`agent/rich_output.py`): naive `s.split("|")` splits on pipes inside backtick spans (`` `a | b` ``) and `\|` escape sequences, producing phantom extra columns. Fix: scan the row tracking backtick fence depth and treating `\|` as literal `|`.

**Single-line `\[...\]` block math** (`response_flow.py`): `_BLOCK_MATH_OPEN_RE` only matched standalone `\[` on its own line. `\[expr\]` on one line passed through as prose (partially mangled by inline markdown). Fix: add `_BLOCK_MATH_ONELINE_BRACKET_RE = re.compile(r'^\\\[(.+)\\\]\s*$')` and check it alongside `_BLOCK_MATH_ONELINE_RE`.

**`EnterWorktree` branch base gotcha**: `EnterWorktree` creates the new branch from the repo's current HEAD — which may not match your active feature branch if you're in a detached state or the tool resolves HEAD differently. Workaround: `git worktree add .claude/worktrees/NAME -b BRANCH BASE_BRANCH` manually, then `EnterWorktree path=.claude/worktrees/NAME`.

### 2026-04-21 — Full TUI audit sweep fixes

**`CopyableBlock` and prose log migration**: `CopyableBlock.__init__` now creates `InlineProseLog` (a subclass of `CopyableRichLog`) instead of `CopyableRichLog` directly. Same for `ReasoningPanel._reasoning_log`. Tests checking `isinstance(panel.response_log, InlineProseLog)` need this. The change is backward-compatible since `InlineProseLog` extends `CopyableRichLog`.

**`_HistoryMixin` rev-search API** (`hermes_cli/tui/input/_history.py`):
- `_rev_search_find(query=None, direction=-1)` — both params optional; `query` defaults to `self._rev_query`; `direction=-1` searches backward, `+1` forward; updates `self._rev_match_idx` and loads match into widget via `load_text()`
- `_rev_match_idx: int` — tracks current position in history list for cycling
- `_rev_saved_value: str` — saved on `action_rev_search()` entry, restored on `_exit_rev_mode(accept=False)`
- `_exit_rev_mode(accept: bool = True)` — new method; `_exit_rev_search()` now delegates here with `accept=True`

**`_save_to_history` global dedup**: old guard `if self._history[-1] == text: return` is replaced with `try: self._history.remove(text)` before appending. This promotes repeated entries to end. Slash commands (`text.startswith("/")`) are still NOT saved — this guard is tested and must stay.

**`HistorySearchOverlay` additions** (`hermes_cli/tui/widgets/overlays.py`):
- `action_prev_query()` — sets input to `_query_history[-1]` (most recent)
- `action_find_next()` — advances `_selected_idx` by 1 mod count (Ctrl+G in overlay)
- `action_toggle_mode()` — toggles `_mode` between `"current"` / `"all"`; updates `_ModeBar`
- `_handle_cross_session_jump(result)` — sets `HintBar.hint` for non-current-session jumps
- `action_dismiss()` now saves non-empty query to `_query_history` (deduped: remove+append)
- `open_search()` reads `app.cli._cfg["display"]["history_search_max_results"]` → sets `self._max_results`
- `_render_results()` uses `self._max_results` (not hardcoded 20)

**`HermesApp.BINDINGS`**: removed `ctrl+g` app-level binding — Ctrl+G now only handled inside `HistorySearchOverlay.BINDINGS` (spec B5). `ctrl+f` remains at app level.

**Flaky test pattern — history file dependency**: `test_hermes_input.py::test_enter_submits_as_typed_with_overlay_visible` was asserting `inp._history[-1] == "/he"` which only passed when developer's `~/.hermes_history` file happened to contain "/he". Slash commands aren't saved (guard). Fixed by removing that assertion — test still verifies `inp.value == ""` (form cleared after submit).

**`tools_overlay.py` rebuild flooding**: `_update_staleness_pip` timer fires every second; each tick was calling `asyncio.ensure_future(_rebuild())`, flooding the message queue and causing `pilot.pause()` to hang forever. Fixed with `_rebuild_in_flight: bool` flag — only one rebuild in flight at a time.

**`_update_pills` DuplicateIds**: `call_after_refresh` mount lambda deduplicates by checking existing child IDs before mounting.

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

**try/except vs bounds check:** Drawbraille raises on out-of-bounds coords. Replacing `try: canvas.set(x,y) except Exception: pass` with `if 0 <= x < w and 0 <= y < h: canvas.set(x,y)` is 5–15% faster per engine. Exception machinery is ~10× slower when it fires.

**Sin/cos LUT:** `_SIN_LUT`/`_COS_LUT` (1024 entries) + `_lut_sin(angle)`/`_lut_cos(angle)` live in `anim_engines.py`. Max error ~0.006 vs `math.sin` — fine for visual rendering, NOT for physics integration (RK4 etc.). Swap into hot per-pixel loops only.

**Divisor hoisting:** `max(w, 1)` / `max(h, 1)` inside inner loops should be hoisted to `w_inv = 1.0 / max(w, 1)` before the loop. Same for `max(row_len - 1, 1)` in `_render_multi_color`.

**Spatial grid for boid simulations:** `FlockSwarmEngine` uses `_BOID_CELL_SIZE = 20` (= largest steering radius). Grid built O(n) per frame with `self._grid.clear()` + rebuild. 3×3 cell search replaces O(n²) all-pairs loop. Gain: 15–55% depending on canvas size. Key: use empty tuple `()` as `.get()` default to avoid list allocation on empty cells.

**TrailCanvas canvas pooling:** Store `self._canvas = drawbraille.Canvas()` at `__init__`; detect `self._canvas_has_clear = hasattr(self._canvas, 'clear')` once. `to_canvas()` reuses the stored canvas instead of allocating each frame.

**`_layer_frames` buffers:** Module-level `_LAYER_ROW_BUF`/`_LAYER_RESULT_BUF` lists with `.clear()` + append replace per-call allocations. Non-reentrant — only valid from the Textual event loop (single-threaded). Add a comment noting this.

**`_render_multi_color` buffer:** `self._multi_color_row_buf: list[str]` on `DrawbrailleOverlay`, initialised in `on_mount()` (no `__init__` on this widget). Reuse per row; reallocate only on width change.

**`_braille_density_set` / `_depth_to_density` signatures:** Both accept `w, h` parameters (added in perf pass). Call sites: `HyperspaceEngine`, `AuroraRibbonEngine` (direct), `RopeBraidEngine` (via `_depth_to_density`).

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
  drawbraille-canvas-color:    "#00d7ff"   # Braille animation canvas default colour
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

### TCSS: declaring new skin vars

Any new `$var-name` referenced in `hermes.tcss` **must** be:
1. Added to `COMPONENT_VAR_DEFAULTS` in `theme_manager.py` with a sensible default.
2. Declared in `hermes.tcss` under the Component Part variables comment block (`/* Component Part variables */`).
3. Documented in the `component_vars:` block of `skin_engine.py`'s module docstring.

`get_css_variables()` alone is insufficient — Textual parses TCSS at class-definition time; unknown `$var-name` refs raise at parse time, not at render time.
