---
name: tui-development
description: >
  Architecture, patterns, and API gotchas for the hermes-agent Textual TUI
  (`hermes_cli/tui/`). Covers widget development, thread→app communication,
  overlay state protocol, testing with Pilot, CSS theming, and high-frequency
  Textual pitfalls.
  TRIGGER when: writing or modifying TUI widgets, adding new overlays or
  status bars, debugging Textual rendering, writing tests in `tests/tui/`,
  touching `_cprint` or `_hermes_app`, or working with `hermes_cli/tui/*`.
  DO NOT TRIGGER when: modifying agent logic, tools, config, or non-TUI CLI
  commands (`hermes_cli/commands.py`, `hermes_cli/config.py`, etc.).
compatibility: "Python 3.11+, Textual >=1.0,<9 (pinned), Rich >=15"
metadata:
  author: xush
  version: "4.0"
  target: code_agent
---

## Use this skill for TUI work

This skill is for `hermes_cli/tui/`, TUI-facing bridges in `cli.py`, and
`tests/tui/`. Treat it as an execution guide, not as a replacement for reading
live code.

## First read

Read these files before you edit anything:

1. `hermes_cli/tui/app.py`
2. `hermes_cli/tui/widgets.py`
3. The specific module you will touch under `hermes_cli/tui/`
4. The matching tests under `tests/tui/`

Then load only the focused reference you need:

- `references/module-map.md` for ownership and routing
- `references/patterns.md` for implementation rules and test workflow
- `references/gotchas.md` for known Textual and hermes-specific traps

## High-signal invariants

- Keep blocking I/O, file polling, YAML parsing, and subprocess waits off the
  Textual event loop.
- Only mutate DOM/reactives on the app thread. From worker or agent threads,
  use `app.call_from_thread(...)`, queue handoff, or `post_message(...)`.
- Workspace overlay is Git-scoped, not Hermes-session-scoped. Inside a repo,
  build the full snapshot off-thread, then swap tracker state on the app
  thread in one shot.
- Workspace polling is owned by one helper in `HermesApp`: desired when either
  the overlay is visible or `agent_running` is true, with one in-flight poll
  and coalesced retrigger.
- Keep exactly one vertical scroll owner in the output path. Inner
  `RichLog`/`ScrollView` widgets must not keep independent scrolling.
- In the output stack, dynamic content mounts before
  `output.query_one(ThinkingWidget)`. `[ThinkingWidget, LiveLineWidget]`
  remain last.
- `watch_agent_running(False)` owns end-of-turn cleanup. Do not build new logic
  around dead sentinel or fallback cleanup paths.
- Perf alarms should use the existing `hermes_cli.tui.perf` primitives. Prefer
  low-noise suspicion/escalation over logging on every single slight breach.
- When skill text and live code disagree, trust live code and update the skill.

## Fast workflow

1. Find the owning module and tests from `references/module-map.md`.
2. Read the narrow pattern section you need in `references/patterns.md`.
3. Check `references/gotchas.md` before changing timers, overlays, scrolling,
   threading, theming, or completion UI.
4. Implement the change in code and tests together.
5. Run targeted tests first, then broader `tests/tui/` coverage if the change
   crosses module boundaries.
6. If behavior changed materially, update this skill or one reference doc in
   the same patch.

## Common task routing

- New widget or status chrome:
  `module-map.md` widget ownership, then `patterns.md` widget section.
- Streaming/output bug:
  `module-map.md` output stack, then `patterns.md` output API, then relevant
  entries in `gotchas.md`.
- Overlay/input bug:
  `patterns.md` overlay protocol and testing sections, then `gotchas.md`
  overlay/input entries.
- Slash command intercept (new TUI command):
  `patterns.md` §Info overlay pattern, then `gotchas.md` §Info overlay escape
  binding trap. Wire into `_handle_tui_command`; add `_dismiss_all_info_overlays`
  call; handle escape in `on_key` Priority -2 block.
- Theme or skin bug:
  `patterns.md` CSS theming section + COMPONENT_CLASSES section, then
  `gotchas.md` theme entries.
- Perf hitch or repaint bug:
  `patterns.md` perf triage section, then `gotchas.md` timer/threading entries.
- Workspace overlay / repo-status bug:
  `module-map.md` app + tracker ownership, then `patterns.md` worker/polling
  rules, then `gotchas.md` overlay/threading entries.

## Files that usually move together

- `hermes_cli/tui/app.py` with `tests/tui/test_integration.py`,
  `tests/tui/test_turn_lifecycle.py`, or a focused module test
- `hermes_cli/tui/overlays.py` with `tests/tui/test_slash_command_overlays.py`
- `hermes_cli/tui/widgets.py` with overlay/status/output tests; InlineThumbnail/InlineImageBar with `tests/tui/test_image_bar.py`
- `hermes_cli/tui/kitty_graphics.py` with `tests/tui/test_kitty_graphics.py`, `tests/tui/test_halfblock_renderer.py`, `tests/tui/test_inline_image.py`, `tests/tui/test_sixel.py`
- `tools/vision_tools.py` with `tests/tools/test_vision_inline.py`
- `hermes_cli/tui/tool_blocks.py` with `tests/tui/test_tool_blocks.py`,
  `tests/tui/test_streaming_tool_block.py`, `tests/tui/test_omission_bar.py`,
  `tests/tui/test_path_context_menu.py`, `tests/tui/test_browse_nav_markers.py`, and scroll tests
- `hermes_cli/tui/execute_code_block.py` with `tests/tui/test_execute_code_block.py`;
  also touches `hermes_cli/tui/partial_json.py`, `hermes_cli/tui/character_pacer.py`,
  `hermes_cli/tui/body_renderer.py`, `cli.py §_on_tool_gen_start/_on_tool_start`,
  `tests/agent/test_tool_gen_args_delta.py`, `tests/test_partial_json_extractor.py`
- `hermes_cli/tui/write_file_block.py` with `tests/tui/test_write_file_block.py`
- `hermes_cli/tui/math_renderer.py` with `tests/tui/test_math_renderer.py`; also touches `response_flow.py`, `widgets.py`, `config.py`, `cli.py`
- `hermes_cli/tui/response_flow.py` with `tests/tui/test_response_flow.py`, `tests/tui/test_math_renderer.py`
- `hermes_cli/tui/drawille_overlay.py` with `tests/tui/test_drawille_overlay.py`,
  `tests/tui/test_drawille_toggle.py`, `tests/tui/test_drawille_v2.py`
- `hermes_cli/tui/tooltip.py` with any widget gaining `TooltipMixin`; touches `hermes.tcss §Screen layers`
- `hermes_cli/tui/input_widget.py` + `completion_overlay.py` + `completion_list.py` + `preview_panel.py` + `path_search.py`
  with `tests/tui/test_input_completion_ux.py` and `tests/tui/test_completion_p0.py`
- `hermes_cli/commands.py` with `tests/hermes_cli/test_commands.py`; slash-cmd changes also touch
  `hermes_cli/tui/completion_context.py`, `hermes_cli/tui/input_widget.py`, `hermes_cli/tui/overlays.py`,
  `hermes_cli/tui/completion_overlay.py`, `hermes_cli/tui/app.py`, and `tests/tui/test_slash_command_overlays.py`
- `hermes_cli/tui/workspace_tracker.py` with `tests/tui/test_workspace_tracker.py`
  and `tests/tui/test_workspace_overlay.py`
- `hermes_cli/tui/widgets.py §AssistantNameplate` with `tests/tui/test_nameplate.py`;
  also touches `app.py`, `hermes.tcss`, `theme_manager.py`, `config.py`, `cli.py`
- `cli.py` TUI bridge code with `tests/cli/test_reasoning_tui_bridge.py` or
  other bridge tests

## Validation

Last revalidated: **2026-04-21. ~2865+ total TUI tests passing** (9 bake-dependent SDF morph tests skip cleanly via `@requires_pil_bake` — PIL/Python 3.13 FreeType incompatibility).

Recent changes (details → reference files):
- **Tool call UX audit pass 4** (2026-04-21): 25 issues (5 P0, 10 P1, 10 P2); spec at `/home/xush/.hermes/tui-tool-call-ux-audit-spec.md`. ~30 new tests across 3 phases.
  **P0 fixes:** diff path regex narrowed (`--- a/` / `+++ b/` prefix required — stops bare `---` YAML separators matching); rate deque expanded to 60 samples; shimmer phase is tick-incremented `+= 0.05` constant delta (not wall-clock) so busy-loop doesn't skip animation; omission bar `set_counts()` always called regardless of `display` state; secondary-args `update_secondary_args()` uses `--args-row` Static slot (separate from `--microcopy`) so secondary args persist across microcopy updates.
  **P1 fixes:** `action_edit_cmd()` saves existing input to history before overwriting; `ToolPanel.PathFocused(Message)` inner class posted when path-tool gains focus; `on_tool_panel_path_focused` in app flashes one-shot hint (guarded by `_path_open_hint_shown`); `osc8.is_supported` alias exported; `ToolGroup.BINDINGS` adds `shift+enter → action_peek_focused` (expand focused panel, collapse others); `ToolsScreen._refresh_timer` auto-starts when in-progress tools present; MCP label in Gantt uses `server::method()` format; `action_export_json` uses `mkdir(parents=True, exist_ok=True)`; `WriteFileBlock` shows `Static("writing…")` hint when `cps=0`, cleared on complete; `ExecuteCodeBlock` cursor hidden on complete (not on code finalize).
  **P2 fixes:** copy flash unified to 1.2s (`_copy_text_with_hint`); `BodyPane` gets `--body-degraded` CSS class + left warning border when renderer init raises; `$tool-vision-accent` declared in `hermes.tcss` + `COMPONENT_VAR_DEFAULTS`; `view_image`/`analyze_image` seed specs added; `shell_pipeline_ms` and `diff_attach_window_s` moved to `DEFAULT_CONFIG.display` (read at call time — not module level); `_build_hint_text()` limits to 3 hints when width < 50; `[+N more]` overflow chip gets `_overflow_remediation` with URL/path hint; `resolve_icon_final()` degrades to `ascii_fallback` in emoji mode (1-cell header constraint); `payload_truncated` chip shown inline in footer when any `Action.payload_truncated` is True.
  Key invariants: `payload_truncated` lives on `Action` (NOT `ResultSummaryV4`); `osc8.is_supported` is a public alias for `_osc8_supported`; `BodyPane._renderer_degraded` flag set in `__init__`, class applied in `on_mount`; `_ARTIFACT_DISPLAY_CAP` lives in `tool_result_parse.py` not `tool_panel.py`; `_build_hint_text` uses Rich Text spans for bold keys (not plain chars); shimmer phase `+= 0.05` per microcopy tick (never wall-clock delta).
  → `hermes_cli/tui/tool_blocks.py`, `hermes_cli/tui/tool_panel.py`, `hermes_cli/tui/tools_overlay.py`, `hermes_cli/tui/tool_group.py`, `hermes_cli/tui/tool_category.py`, `hermes_cli/tui/streaming_microcopy.py`, `hermes_cli/tui/write_file_block.py`, `hermes_cli/tui/execute_code_block.py`, `hermes_cli/tui/app.py §on_tool_panel_path_focused/_path_open_hint_shown`, `hermes_cli/tui/osc8.py §is_supported`, `hermes_cli/tui/hermes.tcss §BodyPane/tool-vision-accent`, `hermes_cli/tui/theme_manager.py §COMPONENT_VAR_DEFAULTS`, `hermes_cli/config.py §display.shell_pipeline_ms/diff_attach_window_s`, `tests/tui/test_tool_blocks.py`, `tests/tui/test_tool_panel.py`, `tests/tui/test_tools_overlay.py`, `tests/tui/test_tool_group.py`, `tests/tui/test_tool_spec.py`, `tests/tui/test_write_file_block.py`, `tests/tui/test_execute_code_block.py`, `tests/tui/test_streaming_microcopy.py`, `tests/tui/test_omission_bar.py`
- **Input history pollution — 3 bugs fixed** (2026-04-21): Slash commands, file-level dedup failure, and CLI/TUI entry merge all caused
  "unrelated trash" at the top of up-arrow history.
  **Bug 1 — Slash commands in history**: `_save_to_history` had no filter; `/clear`, `/anim`, `/model`, etc. were saved as prompts.
  Fix: early return when `text.lstrip().startswith("/")`.
  **Bug 2 — File-level dedup failure**: in-memory `list.remove` deduped the session, but never rewrote the file. Repeated slash cmds
  accumulated as duplicates; all copies reloaded on next TUI start. Fix: `_load_history` deduplicates the loaded slice after `lines[-_MAX_HISTORY:]`
  (reversed pass, last-occurrence wins, order preserved) — repairs existing polluted history files automatically.
  **Bug 3 — CLI/TUI entry merge**: `prompt_toolkit`'s `FileHistory` writes `\n# timestamp\n+cmd\n` with no trailing blank after the last
  entry. The TUI's old append (`+cmd\n\n`) ran straight into it, causing the parser to merge two commands into one multiline entry
  (`"cli_cmd\ntui_cmd"`). Fix: `_save_to_history` now writes a leading `\n` before the `+` lines (`\n+line\n…\n`).
  6 new tests in `TestHistoryTrash` in `tests/tui/test_input_completion_ux.py`.
  Key invariants: `_save_to_history` skips slash commands entirely; always writes `\n+…\n` (leading + trailing blank);
  `_load_history` deduplicates so file-level dupes don't survive a restart.
  → `hermes_cli/tui/input_widget.py §_load_history/_save_to_history`, `tests/tui/test_input_completion_ux.py §TestHistoryTrash`
- **_push_tui_status thread-safety** (2026-04-21): `_push_tui_status` used `call_from_thread` unconditionally.
  `_handle_clear_tui` is `thread=False` (event-loop worker), so calling `call_from_thread` from it raised `RuntimeError`.
  Fix: check `threading.get_ident() == tui._thread_id`; direct reactive assignment on app thread, `call_from_thread` from bg threads.
  → `cli.py §_push_tui_status`, `gotchas.md §call_from_thread`
- **Header tok/s fix** (2026-04-21): `_pause_stream_state` was reading `agent._last_turn_output_tokens` — total API
  output tokens including tool_use blocks, not just text. Also race-prone at tool-call boundaries (field may not yet
  reflect current segment). Fix: `_emit_stream_text` in `cli.py` now accumulates `estimate_tokens_rough(text)` into
  `_message_stream_output_tokens` directly — same estimator as the live rolling window, text-only, race-free.
  `_pause_stream_state` no longer touches `_message_stream_output_tokens`.
  Key invariant: live tok/s (rolling window in `app.py`) and final tok/s (accumulated in `cli.py`) now use the same
  `estimate_tokens_rough` estimator — consistent across streaming and finalized display.
  7 new tests in `tests/cli/test_tok_s_metrics.py`.
  → `cli.py §_emit_stream_text/_pause_stream_state`, `tests/cli/test_tok_s_metrics.py` (new)
- **Config picker overlays** (2026-04-21): 5 new interactive overlays for `/model`, `/reasoning`, `/skin`, `/yolo`, `/verbose`.
  All in `hermes_cli/tui/overlays.py`. Wired into `app.py §_handle_tui_command` (bare `/cmd` opens overlay; `/cmd <arg>` falls through to CLI), `compose()`, and `_dismiss_all_info_overlays()`.
  Module-level config helpers `_cfg_read_raw_config`, `_cfg_save_config`, `_cfg_set_nested`, `_cfg_get_hermes_home` imported at top of `overlays.py` (not lazily) so tests can patch them without `AttributeError`.
  **`VerbosePickerOverlay`**: `OptionList` of 4 modes; `Enter` writes `display.tool_progress` to config.
  **`YoloConfirmOverlay`**: Enable/Disable/Cancel buttons; Enable sets `approvals.mode="off"` + `os.environ["HERMES_YOLO_MODE"]="1"` + `app.yolo_mode=True`; Disable restores `_previous_mode`; escape/cancel is no-op.
  **`ReasoningPickerOverlay`**: 6 level buttons (none/low/minimal/medium/high/xhigh) + 2 checkboxes (show panel/rich mode). Level click injects `/reasoning <level>` back through `HermesInput.action_submit()`. Checkboxes write `display.show_reasoning`/`display.rich_reasoning` to config immediately.
  **`ModelPickerOverlay`**: `OptionList` sourced from `cfg.get("models", {}).keys()` + current model from `cli.agent.model`. Selection injects `/model <name>` via `action_submit()`. Replaces bare `/model` handler (was `ModelOverlay`).
  **`SkinPickerOverlay`**: Scans `get_hermes_home()/"skins"` for `.yaml/.json` files + `"default"`. Arrow navigation triggers `apply_skin(Path)` live preview. Escape reverts by snapshotting `_theme_manager._css_vars/_component_vars` on open. Enter persists `display.skin` to config.
  Pre-existing `_sessions_enabled` property/instance-attr conflict in `app.__init__` fixed (removed the instance assignment — the `@property` already handles it).
  36 tests in `tests/tui/test_config_picker_overlays.py`.
  → `hermes_cli/tui/overlays.py`, `hermes_cli/tui/app.py §_handle_tui_command/compose/_dismiss_all_info_overlays`, `tests/tui/test_config_picker_overlays.py` (new)
- **AnimGalleryOverlay z-order fix** (2026-04-21): `AnimGalleryOverlay` lacked `layer: overlay` and `position: absolute`
  in both `DEFAULT_CSS` and `hermes.tcss`. When the animation gallery was opened (`/anim gallery` or keybinding),
  the widget rendered in normal base-layer layout flow as a direct Screen child after `StatusBar` — appearing below
  the input bar and disrupting the vertical layout. Fix: added `AnimGalleryOverlay { layer: overlay; position: absolute; }`
  to `hermes.tcss`, matching the pattern already used for `DrawilleOverlay` and `AnimConfigPanel`.
  Key invariant: ALL overlay-type widgets that float above the UI (not in flow) need BOTH rules in `hermes.tcss`
  (NOT `DEFAULT_CSS` — see gotcha: `layer: overlay` in `DEFAULT_CSS` corrupts CSS compilation).
  3 new tests in `tests/tui/test_drawille_overlay.py §test_anim_gallery_overlay_not_in_default_css/
  test_hermes_tcss_has_layer_overlay_for_anim_gallery`.
  → `hermes_cli/tui/hermes.tcss §AnimGalleryOverlay`, `tests/tui/test_drawille_overlay.py`
- **Parallel worktree sessions** (2026-04-21): Full feature behind `sessions.enabled` config (default `false`). 7 new files/modules:
  `session_manager.py` (stdlib-only data layer: `SessionRecord`, `SessionIndex` with `fcntl.flock` exclusive writes,
  `SessionManager` lifecycle, `_NotifyListener` daemon UNIX socket thread, `send_notification()` helper).
  `headless_session.py` (background agent driver — NO Textual import; `OutputJSONLWriter` ring-buffered JSONL, ANSI+Rich
  stripped; `HeadlessSession.run()` registers PID in `state.json`, fires completion notification via `send_notification`).
  `session_widgets.py`: `SessionBar` (1-line dock strip; `●`/`○`/`[●]` markers; `Alt+N` switch, `+` button → `NewSessionOverlay`),
  `_SessionsTab` + `_WorktreeSessionRow` (Sessions tab in WorkspaceOverlay; orphan ⚠/[reopen]/[delete]; idle/running/kill/merge),
  `NewSessionOverlay` (branch name + base selector + git error surface), `MergeConfirmOverlay` (merge/squash/rebase + close-on-success),
  `_SessionNotification` (5s toast with [switch] button; queued for multiple events; independent of `_flash_hint_expires`),
  `HistoryPanel` (read-only `RichLog` replay of `output.jsonl`, plain text).
  `config.py` sessions block: `session_dir=/tmp/hermes-sessions`, `max_sessions=8`, `output_buffer_lines=2000`,
  `auto_prune_orphans`, `default_merge_strategy=squash`.
  `cli.py`: `--headless` + `--worktree-session-id` args; routes to `HeadlessSession` when both set.
  `overlays.py` `WorkspaceOverlay` extended with `ContentSwitcher` tab strip (Git Status | Sessions).
  `app.py`: `SessionBar` + `_SessionNotification` in `compose()`; `Ctrl+W N` binding; `Alt+1–9` session switch;
  session action methods (`_switch_to_session` → `os.execvp`, `_create_new_session` → worker + Popen, `_kill_session_prompt`,
  `_open_merge_overlay`, `_run_merge`, etc.).
  Key design: `SessionBar` hidden by default (`display: none`); enabled by `--sessions-enabled` CSS class.
  Orphan detection: `os.kill(pid, 0)` + cmdline check (`/proc/<pid>/cmdline` Linux, `ps -p` macOS) guards PID reuse.
  Socket path validation rejects paths > 104 (macOS) / 108 (Linux) chars.
  `_SessionNotification` does NOT use `_flash_hint_expires` — it has its own `set_timer(5.0)`.
  `HistoryPanel` only renders plain text — Rich/ANSI/tool formatting not preserved in headless path (known limitation).
  90 new tests: `tests/tui/test_session_manager.py` (23), `tests/tui/test_headless_session.py` (17), `tests/tui/test_session_widgets.py` (50).
  Key bugs found and fixed in WIP code: `_verify_cmdline` checked `--session-id` not `--worktree-session-id`;
  `OutputJSONLWriter` Rich regex only stripped simple `[tag]` not `[bold red]`/`[link=x]`; `_get_branch()` used
  process cwd not worktree cwd; `MergeConfirmOverlay` strategy parse `btn_id[3:]` yielded `"erge"` not `"merge"`;
  `SessionBar._rebuild()` DuplicateIds: `remove_children()` async → IDs still present at `mount()` time
  (fix: per-child `.remove()` + `call_after_refresh(lambda: inner.mount(*w))`);
  `_SessionNotification` needed `layer: overlay` to avoid bottom-dock-stack conflict with `HintBar`/`SessionBar`.
  → `hermes_cli/tui/session_manager.py` (new), `hermes_cli/tui/headless_session.py` (new),
    `hermes_cli/tui/session_widgets.py` (new), `hermes_cli/tui/overlays.py §WorkspaceOverlay`,
    `hermes_cli/tui/app.py §compose/on_key/session_methods`, `hermes_cli/config.py §sessions`,
    `cli.py §main/--headless/--worktree-session-id`, `tests/tui/test_session_manager.py`,
    `tests/tui/test_headless_session.py`, `tests/tui/test_session_widgets.py`
- **Slash command dispatch fix** (2026-04-21): `/slash-commands` shown in completion overlay were flashing
  "Unknown command" when entered, because `_handle_tui_command` had a hardcoded whitelist (~16 commands)
  and fired the flash for any `/word` not in the list. Fix: the guard now calls `resolve_command()` against
  `COMMAND_REGISTRY` before flashing — only commands absent from the registry get the "Unknown command"
  flash; registry commands not handled by TUI-specific logic fall through to the CLI agent silently.
  Key invariant: `_handle_tui_command` returns `False` to forward to agent; `True` to consume.
  8 new tests in `tests/tui/test_slash_command_dispatch.py`.
  → `hermes_cli/tui/app.py §_handle_tui_command`, `tests/tui/test_slash_command_dispatch.py` (new)
- **Input bar '/' flicker loop** (2026-04-21): Typing '/' caused the input to clear and re-insert itself
  in a loop. Root cause: fallback DnD detector in `on_text_area_changed` called `detect_file_drop_text("/")`
  which matched `Path("/").exists() == True` (root dir), cleared input, posted FilesDropped, re-inserted "/".
  Fix: added `len(stripped) > 1` guard before calling `detect_file_drop_text` in the DnD path.
  1 regression test in `tests/tui/test_slash_completion_regression.py`.
  → `hermes_cli/tui/input_widget.py §on_text_area_changed`
- **Autocomplete re-entry guard** (2026-04-21): `_update_autocomplete` lacked equality check — same trigger
  re-pushed items to `VirtualCompletionList` every call, firing `watch_items → refresh → layout → watch_value`
  feedback cycle. Fix: compute trigger first, compare with `self._current_trigger`, return early if equal.
  Also added same-content guard in `_push_to_list` (skip assignment when items+query unchanged).
  2 regression tests in `tests/tui/test_slash_completion_regression.py`.
  → `hermes_cli/tui/input_widget.py §_update_autocomplete/_push_to_list`
- **Interrupt/cancel keybinding split + history search fixes** (2026-04-20):
  Keybinding model: ctrl+c = copy selected → cancel overlay (deny) → clear input (NEVER interrupts);
  ctrl+shift+c = dedicated interrupt (double within 2s = force exit); escape = cancel overlay (None) → interrupt.
  **P0-2**: `flush_live()` called immediately after `agent.interrupt()` at both dispatch sites — stops blink cursor at
  point of interrupt, not at next turn boundary.
  **P0-3**: `except NoMatches` at feedback blocks now `self.log.warning(...)` instead of bare `pass`.
  **P0-1**: `_active_streaming_blocks.clear()` on `watch_agent_running(False)` — releases GC refs + prevents stale
  dict entries on next turn. DOM nodes NOT removed — partial tool output stays visible.
  Key design invariant: `test_interrupt_mid_stream_block_stays_in_dom` confirms blocks must remain in DOM after
  interrupt. Only the tracking dict is cleared, not the widgets themselves.
  **_substring_search**: tokens must all match within user OR assistant section independently — cross-boundary
  matches (token in user text, co-token in assistant text) rejected. Check `all(t in user_hay)` OR
  `all(t in asst_hay)` before collecting spans.
  **history search test infra**: `_make_app()` must use `cli._cfg = {}` (not bare `MagicMock()`) — `int(MagicMock())=1`
  collapses `_max_results` to 1. Cap tests must set `cli._cfg = {"display": {"history_search_max_results": N}}`
  before `open_search()` (which reads and overrides `_max_results`).
  19 new tests: `tests/tui/test_interrupt.py` (+13), `tests/tui/test_interrupt_cleanup.py` (new, 6 tests).
  → `hermes_cli/tui/app.py §watch_agent_running/_active_streaming_blocks/on_key(interrupt sites)`,
    `hermes_cli/tui/widgets.py §_substring_search`,
    `tests/tui/test_interrupt.py`, `tests/tui/test_interrupt_cleanup.py` (new)
- **Custom emoji missing after code/tool blocks** (2026-04-20): `ensure_prose_block()` in `MessagePanel`
  created new `CopyableBlock` without `_log_class=InlineProseLog`. After any code or tool block in a
  response, subsequent prose segments used plain `CopyableRichLog` (no `write_inline`) →
  `_write_prose_inline_emojis` returned False → `:name:` rendered as literal text. First prose block
  (before any split) always used InlineProseLog correctly; only post-split blocks were broken.
  Fix: pass `_log_class=InlineProseLog` to `CopyableBlock` constructor in `ensure_prose_block`.
  Regression test: `test_ensure_prose_block_new_block_uses_inline_prose_log` in `test_inline_prose.py`.
  Key gotcha: ALL prose blocks in `MessagePanel` must use `InlineProseLog`, not just `_response_block`.
  → `hermes_cli/tui/widgets.py §MessagePanel.ensure_prose_block`, `tests/tui/test_inline_prose.py`
- **Anim overlay — premium spinner & /anim redesign** (2026-04-20): 5 phases, 57 new tests in `tests/tui/test_anim_overlay.py`.
  **Phase A:** `DEFAULT_CONFIG["display"]["drawille_overlay"]` promoted to defaults: `enabled=True`, `position="top-right"`, `size="small"`, `color="auto"`, `fps=20`, `dim_background=False`, `animation="neural_pulse"`, `fade_out_frames=8`, `sdf_text=""`, `sdf_morph_ms=400`, `sdf_crossfade_speed=0.045`. NEW `sdf_bake_timeout_s=5.0` field in `DrawilleOverlayCfg` + DEFAULT_CONFIG + `_overlay_config()`. `_resolve_color` gains `dim: float = 1.0` param + `"auto"` → `"$accent"` branch. `DrawilleOverlay` gains `_fade_state: str`, `_fade_step: int` — fade-out lifecycle in `_tick()`. `DrawilleOverlay.signal(event, value=1.0)` centralizes all heat mutations from app.py.
  **Phase B:** `_ENGINE_META` dict (all `_ENGINES` keys + `"sdf_morph"`, keyed with actual short keys like `"dna"` not `"dna_helix"`). `AnimGalleryOverlay` + `_GalleryPreview` widgets in `drawille_overlay.py`. `/anim` command vocabulary expanded: `on`/`off`/`toggle`/`config`/`list`/`<engine_fuzzy>`/`sdf [text]`. `_anim_force: str | None` on `HermesApp`. Gallery wired in compose(), `_dismiss_all_info_overlays()`, escape Priority -2 block.
  **Phase C:** `_TOOL_SDF_LABELS` dict + `contextual_text` property on `DrawilleOverlay`. `_active_tool_name` on `HermesApp` set/cleared by `_on_tool_start`/`_on_tool_complete`. `SDFBaker` gains `failed` event + `_start_time` + 5s `sdf_bake_timeout_s` timeout. `_sdf_permanently_failed` flag prevents baker re-creation loop. `_anim_hint: reactive[str]` on `HermesApp`; `_update_anim_hint()` called from agent lifecycle hooks; `StatusBar` reads it.
  **Phase D:** `_BaseEngine` mixin with no-op `on_signal`. Signal vocab unified to `"thinking"/"token"/"tool"/"complete"` across 6 engines. Carousel implemented via `_get_carousel_engine()` + `_carousel_engines` (filtered by `_ENGINE_META` category). External trail accumulator for stateless classic engines. Crossfade dissolve uses deterministic hash dither (not `random.random()`). ConwayLife R-pentomino re-seed, WaveFunction boundary reflect, Hyperspace depth spawn, AuroraRibbon dynamic bands.
  **Phase E:** `AnimConfigPanel` gains engine desc line (E1), `[CAT]` prefix in animation label (E2), `_GalleryPreview` in panel header (E3). `_do_save()` calls `app._persist_anim_config()` primary + direct YAML fallback. `HermesApp._persist_anim_config()` writes `config["display"]["drawille_overlay"]` to YAML. Test isolation fix: `type(panel).app` class mutations in tests now save/restore the property in `finally` to prevent cross-test contamination.
  Key gotchas: `_ENGINE_META` uses actual short `_ENGINES` keys (`"dna"` not `"dna_helix"`); `_resolve_color` stays module-level (NOT instance method); `type(X).app = property(...)` in tests MUST be restored in `finally` — leaks permanently into subsequent tests in same process.
  → `hermes_cli/tui/drawille_overlay.py §_BaseEngine/_ENGINE_META/_GalleryPreview/AnimGalleryOverlay/DrawilleOverlay.signal/fade-out/contextual_text/carousel`, `hermes_cli/tui/app.py §signal-calls/_anim_force/_active_tool_name/_anim_hint/_persist_anim_config/on_key-escape`, `hermes_cli/config.py §display.drawille_overlay defaults`, `tests/tui/test_anim_overlay.py` (new, 57 tests)
- **TGP stdout redirect fix — custom emojis blank in Kitty** (2026-04-21): Root cause: Textual's `App._process_messages()` wraps the event loop with `redirect_stdout(_PrintCapture)`, replacing `sys.stdout` with an object that routes `write()` to `app._print()`. `InlineImageCache._render()` called `sys.stdout.write(seq)` to upload TGP image data → sequence went to internal capture buffer, never Kitty. Kitty rendered placeholder chars as blank (unknown image ID). Fix: use `out = sys.__stdout__ if sys.__stdout__ is not None else sys.stdout` — `sys.__stdout__` bypasses the redirect. 2 sites: `inline_prose.py §InlineImageCache._render()` + `widgets.py §InlineImage._emit_raw()`. 2 new tests in Group 12 (`test_inline_prose.py`). See `gotchas.md §TGP / Kitty Graphics stdout redirect`.
  → `hermes_cli/tui/inline_prose.py §_render`, `hermes_cli/tui/widgets.py §InlineImage._emit_raw`, `tests/tui/test_inline_prose.py §Group 12`
- **Emoji render-safety fix** (2026-04-20): `InlineImageCache._render()` was being called from `InlineProseLog.render_line()` on cache miss, causing: (1) TGP path writing raw kitty escape sequences to `sys.stdout` INSIDE Textual's render phase → screen corruption; (2) PIL resize blocking event loop. Fix: `render_line` now calls `get_strips_or_alt()` (never calls `_render`; returns alt_text on miss). `write_inline()` triggers `_prerender_line_images()` which emits TGP on event loop synchronously and offloads halfblock PIL to `@work(thread=True) _prerender_halfblock()`. Also: `_current_render_mode()` now caches `_RenderMode` (prevents ioctl per render_line); `on_resize()` invalidates cache + calls `_reset_cell_px_cache()`. 6 new tests in `tests/tui/test_inline_prose.py`.
  Key gotcha: `_prerender_halfblock` needs app context; guard with `try/except` (unit tests have no app → skip worker silently). See `gotchas.md §InlineProseLog / emoji render-safety`.
  → `hermes_cli/tui/inline_prose.py §get_strips_or_alt`, `hermes_cli/tui/widgets.py §InlineProseLog._prerender_line_images/_prerender_halfblock/_current_render_mode/on_resize/write_inline/_render_inline_line`, `hermes_cli/tui/kitty_graphics.py §_reset_cell_px_cache`, `tests/tui/test_inline_prose.py §Group 11`
- **Slash command TUI overhaul — Phases 1–3** (2026-04-20): Full rework of slash command registry, completion, and overlay system. 52 new tests.
  **Phase 1 — Registry & escape fix:** `CommandDef` gains `tui_only: bool = False` + `keybind_hint: str = ""` fields. `/compact` + `/sessions` registered as `tui_only=True`. `/anim` + `/workspace` marked `tui_only=True`. `_is_gateway_available()` excludes `tui_only` commands from all gateway surfaces. `tui_help_lines()` helper returns all non-gateway-only commands (incl. `tui_only` + `cli_only`). Escape handler in `on_key` now includes `SessionOverlay` in dismiss loop. Unknown-command flash: `_handle_tui_command` shows "Unknown command — try /help" for unrecognised bare `/word`.
  **Phase 2 — Subcommand completion:** `SLASH_SUBCOMMAND = 6` added to `CompletionContext` enum. `CompletionTrigger` gains `parent_command: str = ""`. `_SLASH_SUBCMD_RE` checked before `_SLASH_RE` in `detect_context`. `SlashCandidate` gains `args_hint`, `category`, `keybind_hint` fields. `HermesInput` gains `_slash_subcommands`, `_slash_args_hints`, `_slash_keybind_hints` dicts + setters. `_show_subcommand_completions(parent_cmd, fragment)` added. `action_accept_autocomplete` splices only the fragment (preserves parent prefix). `_populate_slash_commands` excludes `gateway_only` commands.
  **Phase 3 — Display & overlay polish:** `CommandsOverlay._refresh_content` calls `tui_help_lines()` (not `gateway_help_lines()`); refresh called on every open. `q` binding: `HelpOverlay` demoted to `priority=False`; `UsageOverlay`/`CommandsOverlay`/`ModelOverlay`/`WorkspaceOverlay` remove `q` entirely (Escape via `on_key` Priority -2 handles dismiss). `SlashDescPanel._on_candidate` renders `/command [args_hint]` + description + dim `keybind_hint`. `HelpOverlay._refresh_commands_cache()` called after plugin registration via `HermesApp.refresh_slash_commands`.
  Key gotchas: `CompletionTrigger` is `frozen=True, slots=True` — new fields need defaults. `_SLASH_SUBCMD_RE` must be checked BEFORE `_SLASH_RE` (longer match wins). `tui_only` and `gateway_only` are mutually exclusive — a command is either TUI-only or gateway-only, never both.
  → `hermes_cli/commands.py §CommandDef/tui_help_lines`, `hermes_cli/tui/completion_context.py §SLASH_SUBCOMMAND`,
    `hermes_cli/tui/input_widget.py §_show_subcommand_completions/action_accept_autocomplete`,
    `hermes_cli/tui/path_search.py §SlashCandidate`, `hermes_cli/tui/overlays.py §HelpOverlay/CommandsOverlay`,
    `hermes_cli/tui/completion_overlay.py §SlashDescPanel`, `hermes_cli/tui/app.py §_handle_tui_command/on_key`,
    `tests/tui/test_slash_subcommand_completion.py` (new), `tests/tui/test_slash_command_overlays.py`,
    `tests/hermes_cli/test_commands.py`
- **AssistantNameplate** (2026-04-20): `AssistantNameplate(Widget)` + `_NPChar` dataclass + `_NPState` enum appended to `widgets.py`.
  State machine: `STARTUP→IDLE→MORPH_TO_ACTIVE→ACTIVE_IDLE→GLITCH→MORPH_TO_IDLE→ERROR_FLASH`.
  Decrypt reveal: per-char `lock_at = 2 + i*2 + randint(-1,1)` ticks at 20fps (~0.6s for "Hermes").
  Idle: delegates to `StreamEffectRenderer.render_tui(name, accent_hex, text_hex)` via
  `make_stream_effect({"stream_effect": name})` — key is `"stream_effect"` NOT `"name"`.
  Morph: `_init_morph(src, dst)` cross-dissolves via `_morph_dissolve` countdown list; `done` flag
  set only after decrement (NOT before — common bug: `done=False` before decrement misses locks).
  ACTIVE_IDLE stops timer (`_stop_timer()`); glitch/morph restart it.
  Error flash: 2 frames in `_NPState.ERROR_FLASH`; transitions via direct state assign (not
  `transition_to_idle()` — avoids re-entrant error check and spurious `_set_timer_rate` call).
  Timer: 20fps for STARTUP/MORPH/GLITCH/ERROR_FLASH; 6fps for IDLE; stopped during ACTIVE_IDLE.
  App wiring: `compose()` yields `AssistantNameplate` between OutputPanel and HintBar using
  `getattr(self, "_nameplate_*", default)` pattern; `watch_agent_running` and existing
  `watch_spinner_label` (line ~1852) extended with `try/except NoMatches`. Config wired via
  `app._nameplate_*` plain attrs set in `cli.py` before `compose()` (same pattern as `_math_enabled`).
  TCSS: `$nameplate-idle-color`, `$nameplate-active-color`, `$nameplate-decrypt-color` declared as
  literal colours (NOT `$var: $other_var` — Textual TCSS does not support variable-in-variable).
  `COMPONENT_VAR_DEFAULTS` in `theme_manager.py` updated. 39 tests in `tests/tui/test_nameplate.py`.
  → `hermes_cli/tui/widgets.py §AssistantNameplate/_NPChar/_NPState`,
    `hermes_cli/tui/app.py §compose/watch_agent_running/watch_spinner_label`,
    `hermes_cli/tui/hermes.tcss §$nameplate-*/AssistantNameplate`,
    `hermes_cli/tui/theme_manager.py §COMPONENT_VAR_DEFAULTS`,
    `hermes_cli/config.py §display.nameplate_*`,
    `cli.py §_nameplate_*/app._nameplate_*`,
    `tests/tui/test_nameplate.py` (new, 39 tests)
- **Input/Completion UX** (2026-04-20): 16 issues (A1–D4) fully implemented. Key invariants:
  - A1: `HermesInput._idle_placeholder` stores default text; `app.py` restores via `getattr(w, "_idle_placeholder", "")` not `""`.
  - A2: ghost text works in multiline mode — matches last line of input via `rsplit("\n",1)[-1]`.
  - A3: `HermesApp._completion_hint: reactive[str]` watched by StatusBar; `_show_completion_overlay` sets it, `_hide_completion_overlay` clears it; ghost text cleared on show and restored on hide.
  - A4: `ctrl+shift+up/down` changes `_input_height_override` (3–10); resets on submit.
  - A5: `_history_load(text)` uses `self.replace()` not `load_text()` to preserve undo ring.
  - B1: `SlashDescPanel(RichLog)` in `completion_overlay.py` watches `app.highlighted_candidate`; `SlashCandidate.description` field; `set_slash_descriptions(dict)` on HermesInput.
  - B2: `_last_slash_hint_fragment` debounces flash — only resets on `action_submit()`, NOT on `_hide_completion_overlay()`.
  - C2: `_maybe_schedule_auto_close()` has no length guard (removed `len >= 4` threshold).
  - C3: `_move_highlight` uses `max(0, min(n-1, h+delta))` clamp, not `%` wrap.
  - C4: `HermesApp._path_search_ignore: frozenset|None = None`. `_walk` uses `ignore if ignore is not None else {defaults}` — do NOT use `ignore or {defaults}` (empty frozenset is falsy). Config key: `terminal.path_search_ignore`.
  - C5: `_styled_candidate` appends `→ insert_text` dim suffix when `insert_text != display` and `not selected`.
  - D1: `_load_preview` checks `path.is_dir()` first; shows sorted listing (dirs-first) with `d `/`  ` ASCII prefix, 40-entry cap, `PlainReady` message.
  - D3: `_hex_luminance(hex)` helper in `preview_panel.py` — do NOT import from `animation.py`.
  - D4: `_update_overflow_badge` uses `self.size.height` (with `or 13` fallback); `on_resize` calls it.
  → `hermes_cli/tui/input_widget.py`, `hermes_cli/tui/completion_list.py`,
    `hermes_cli/tui/completion_overlay.py`, `hermes_cli/tui/preview_panel.py`,
    `hermes_cli/tui/path_search.py`, `hermes_cli/tui/app.py`, `hermes_cli/tui/widgets.py`,
    `hermes_cli/config.py`, `cli.py`, `tests/tui/test_completion_p0.py`,
    `tests/tui/test_input_completion_ux.py` (69 tests)
- **TGP unicode placeholder detection fix** (2026-04-20): `_supports_unicode_placeholders()` was too
  strict — only accepted `TERM=xterm-kitty`, missing the `TERM_PROGRAM=kitty` path used by many Kitty
  installs. Result: `get_caps()` → `TGP` (via `TERM_PROGRAM=kitty`) but placeholder check → `False`
  → silent halfblock fallback in `InlineImage.watch_image`. Fix: also accept `TERM_PROGRAM=kitty` as
  proof of Kitty identity. Added `_LOG.warning(...)` on TGP→halfblock fallback path so misdetection
  is visible in logs. 3 new tests in `tests/tui/test_kitty_graphics.py §Unicode placeholder detection`.
  Key invariant: `_supports_unicode_placeholders()` result is cached per session — call
  `_reset_unicode_placeholders_cache()` in tests that monkeypatch `TERM`/`TERM_PROGRAM`/`KITTY_WINDOW_ID`.
  → `hermes_cli/tui/kitty_graphics.py §_supports_unicode_placeholders`,
    `hermes_cli/tui/widgets.py §InlineImage.watch_image`, `tests/tui/test_kitty_graphics.py`
- **First-response-line race fix — extended** (2026-04-20): "W" missing from first reply in Kitty.
  Two separate buffers can hold pre-panel-switch content:
  1. `_block_buf._pending` (setext lookahead — a full line held for context)
  2. `engine._partial` (partial chunk with no `\n` yet — Kitty delivers smaller chunks)
  Previous fix only stole `_block_buf._pending`; `_partial` was silently dropped.
  Fix: `watch_agent_running(True)` steals BOTH. `_partial` stored as `new_msg._carry_partial`;
  `MessagePanel.on_mount` re-feeds it via `engine.feed(carry_partial)` after `process_line(carry_pending)`.
  `MessagePanel.__init__` gains `_carry_partial: str | None = None`.
  Key invariant: **engine doesn't exist until `on_mount` fires** — route deferred calls through
  `_carry_pending` (for complete lines) and `_carry_partial` (for partial chunks). Never call
  `engine.process_line()` or `engine.feed()` on a freshly created MessagePanel from `watch_agent_running`.
  3 regression tests in `tests/tui/test_turn_lifecycle.py` (2 existing + `test_partial_chunk_migrated_to_new_panel`).
  → `hermes_cli/tui/app.py §watch_agent_running`, `hermes_cli/tui/widgets.py §MessagePanel.__init__/on_mount`,
    `tests/tui/test_turn_lifecycle.py §test_partial_chunk_migrated_to_new_panel`
- **Panel-ready gate — streaming start gated behind engine mount** (2026-04-21): multi-line first
  chunks (e.g. `"Line 1\nLine 2\n"`) processed entirely in one `_commit_lines()` call before
  `await asyncio.sleep(0)` yields to the event loop. `_block_buf` processes both lines: Line 1 is
  returned (written to OLD panel's log, lost), Line 2 stays in `_pending` (stolen). The steal-only
  fix missed any lines that were EMITTED by `_block_buf` before the panel switch.
  Worst case: event loop busy with queued TTE frame callbacks → `agent_running=True` delayed further.
  Fix: cli.py injects `_panel_ready_event: threading.Event` onto the app BEFORE calling
  `call_from_thread(agent_running=True)`. `MessagePanel.on_mount` signals it after engine init and
  carry-pending/partial replay, then clears `app._panel_ready_event = None`. cli.py waits
  `_panel_ready_event.wait(timeout=1.0)` before calling `chat()`. Streaming can now only start after
  the new panel's engine is fully ready — race window eliminated entirely.
  `HermesApp.__init__` gains `_panel_ready_event: threading.Event | None = None`.
  4th regression test: `test_panel_ready_event_set_on_mount`.
  → `hermes_cli/tui/app.py §__init__`, `hermes_cli/tui/widgets.py §MessagePanel.on_mount`,
    `cli.py §process_loop (agent_running=True block)`,
    `tests/tui/test_turn_lifecycle.py §test_panel_ready_event_set_on_mount`
- **Mouse UX — tooltip system, ctrl+click, scroll config, double-click, shift-select** (2026-04-20):
  `tooltip.py` (NEW) — `Tooltip(Widget)` + `TooltipMixin`; mounted on `screen.tooltip` layer;
  positioned via `styles.offset`; 500ms delay timer; dismissed on `on_mouse_leave`.
  Applied to: `ToolHeader`, `StreamingCodeBlock`, `ReasoningPanel`, `InlineThumbnail`, `SeekBar`,
  `OmissionBar`, `_CopyBtn` (copy button in `CopyableBlock`).
  `hermes.tcss`: `Screen { layers: base overlay tooltip; }` added; `OutputPanel scrollbar-size-vertical: 1` removed
  (dead scrollbar — CopyableRichLog owns scroll state, not OutputPanel track).
  `ToolGroup.on_click`: `if event.button != 1: return` — right-click no longer accidentally collapses group.
  `HermesInput.on_click`: button 2 (middle-click) on Linux reads X11 primary selection via
  `xclip -selection primary` → `xsel --primary` fallback chain; inserts at cursor; `event.stop()`.
  `CopyableRichLog.on_click` / `LinkClicked`: plain left-click now copies URL to clipboard;
  Ctrl+left-click opens. `LinkClicked` gained `ctrl: bool` field.
  `app.on_copyable_rich_log_link_clicked`: branches on `event.ctrl` — copy vs open.
  `config.py` `terminal.scroll_lines: 3`; `HermesApp._scroll_lines: int = 3`; wired from `cli.py`;
  `OutputPanel.on_mouse_scroll_*` uses `getattr(self.app, '_scroll_lines', _SCROLL_LINES)`.
  Double-click via `event.chain == 2` (Textual native — no manual timer):
  `StreamingCodeBlock.on_click`: chain==2 + state!=STREAMING → copy all code;
  `ReasoningPanel.on_click`: chain==2 → force-expand (body_collapsed=False);
  `ToolHeader.on_click`: chain==2 + no path → copy result summary from parent._result_summary.
  `HistorySearchOverlay`: `_last_click_idx: int | None`, `_shift_selected: set[int]`;
  `TurnResultItem.on_click`: shift+left-click → range-select [last, current] inclusive, apply
  `--selected` CSS class, no jump; plain click → single select + jump; reset on dismiss.
  `action_jump()` updated: if `_shift_selected` non-empty, jumps to first (min index) entry via `action_jump_to`.
  Key: `open_search()` clears stale `--selected` CSS via `for item in self.query(TurnResultItem): item.set_class(False, "--selected")`
  BEFORE `_render_results()` runs — `update_from()` updates labels only, never CSS classes, so stale selection
  highlights persist across overlay open/close without this explicit clear.
  `app._show_context_menu_at(items, x, y)` extracted helper; `_show_context_menu_for_focused()`
  computes position from `focused.content_region` center for keyboard-triggered context menu.
  40 new tests in `tests/tui/test_mouse_ux.py`.
  Key: `Click.chain` int is native Textual — no manual `_last_click_time` needed.
  Key: `_CopyBtn` subclass pattern: `class _CopyBtn(TooltipMixin, Static)` — `Static` is concrete,
  `TooltipMixin` must come first in MRO. `_CopyBtn` replaces `Static("⎘", id="copy-btn")` in
  `CopyableBlock.on_mouse_enter`.
  → `hermes_cli/tui/tooltip.py` (new), `widgets.py`, `tool_blocks.py`, `tool_group.py`,
    `input_widget.py`, `app.py`, `hermes.tcss`, `config.py`, `cli.py`,
    `tests/tui/test_mouse_ux.py` (new, 40 tests)
- **Workspace overlay = full Git working tree + low-noise perf alarms** (2026-04-20):
  Workspace view now matches Git working-tree state instead of only Hermes-touched files.
  `workspace_tracker.py` was rebuilt around parsed `GitSnapshotEntry` rows plus Hermes-only
  annotations (`session_added/session_removed`, touched badge, complexity warning). `GitPoller`
  parses `git status --porcelain=v1 -z --untracked-files=all`, preserving XY status, untracked,
  conflict, and rename metadata. `WorkspaceOverlay` renders branch + dirty count from snapshot,
  row tags (`staged`, `untracked`, `Hermes`, `conflict`), rename microcopy, and a non-Git
  empty-state message. Polling is now controlled by `HermesApp._sync_workspace_polling_state()`:
  active when overlay visible OR `agent_running`, one timer only, one in-flight worker only,
  coalesced retrigger when a poll request lands mid-flight.
  Perf instrumentation gained `SuspicionDetector` in `perf.py` — logs `[PERF-ALARM]` only on
  repeated over-budget samples or severe spikes. Wired into `EventLoopLatencyProbe`, spinner and
  duration ticks, and workspace git-poll/apply paths.
  → `hermes_cli/tui/workspace_tracker.py`, `hermes_cli/tui/overlays.py`,
    `hermes_cli/tui/app.py`, `hermes_cli/tui/perf.py`,
    `tests/tui/test_workspace_tracker.py`, `tests/tui/test_workspace_overlay.py`,
    `tests/tui/test_perf_instrumentation.py`
- **Crush easy-wins features A/B/C/D** (2026-04-20): 50 tests in `tests/tui/test_crush_easy_wins.py`.
  **A — context_pct meter**: `HermesApp.context_pct: reactive[float]` + `context_pct` added to
  `StatusBar.on_mount` watch list. `StatusBar.render()` appends ` ▕ XX%` segment (dim, color by threshold:
  <70% = context-color, 70-90% = warn, >90% = error) when `context_pct > 0`, `width >= 50`, and
  `display.context_pct = true` in config. `_push_tui_status()` in `cli.py` computes token pct from
  `agent.session_prompt_tokens + session_completion_tokens` / `model_context_window(model)`;
  `model_context_window(model) -> int` added to `config.py` (maps claude-* family to 200k, others 0).
  **B — OSC 9;4 progress bar**: `hermes_cli/tui/osc_progress.py` (NEW) — `is_supported()` detects
  Ghostty (`$TERM_PROGRAM=ghostty`), iTerm2 (`TERM_PROGRAM=iTerm.app`), WezTerm, Rio, Windows Terminal
  (`$WT_SESSION`), plus `$HERMES_OSC_PROGRESS` override. `update(running)` writes `\x1b]9;4;3;\x07`
  (indeterminate) or `\x1b]9;4;0;\x07` (clear) via `os.write(sys.stdout.fileno(), ...)` (raw bytes).
  `HermesApp._osc_progress_update(running)` called from `watch_agent_running(True/False)`.
  **C — desktop notification + sound**: `hermes_cli/tui/desktop_notify.py` (NEW) — `can_notify()`,
  `notify(title, body, sound=False, sound_name="Glass")`. Linux: `notify-send`; macOS: `osascript`
  with `json.dumps()` for safe string injection. Sound: macOS `afplay`, Linux `paplay`/`aplay`/`ogg123`.
  `HermesApp._maybe_notify()` checks `notify_min_seconds` threshold, uses `_last_assistant_text` for
  body; fires in `watch_agent_running(False)`. Config: `display.desktop_notify/notify_min_seconds/
  notify_sound/notify_sound_name` + yolo `display.osc_progress/context_pct`.
  **D — yolo mode indicator**: `HermesApp.yolo_mode: reactive[bool]` initialized from
  `HERMES_YOLO_MODE` env at `on_mount`. `watch_yolo_mode()` adds/removes `--yolo-active` on
  `#input-chevron`. `StatusBar.render()` prepends `⚡ YOLO  ` badge (bold warning color) when
  `yolo_mode=True`. `_toggle_yolo()` in `cli.py` syncs reactive via `tui.call_from_thread(setattr,
  tui, "yolo_mode", new_value)`. `ResponseFlowEngine._prose_callback` wired in `MessagePanel.on_mount`
  to update `app._last_assistant_text` on each committed prose line.
  Key gotchas: `_make_bar()` pattern in tests must use a local subclass (`class _BarStub(StatusBar)`)
  NOT `type(bar).app = property(...)` — the latter mutates the live `StatusBar` class and breaks
  subsequent pilot tests. `_tok_s_displayed` reactive must NOT be set via `object.__setattr__` — it
  still triggers Textual's `__set__` (data descriptor). Skip it; render() doesn't read it.
  → `hermes_cli/tui/osc_progress.py` (new), `hermes_cli/tui/desktop_notify.py` (new),
    `hermes_cli/tui/app.py §context_pct/yolo_mode/watch_yolo_mode/_osc_progress_update/_maybe_notify`,
    `hermes_cli/tui/widgets.py §StatusBar.on_mount/render/_EchoBullet.get_text`,
    `hermes_cli/tui/response_flow.py §_prose_callback/_write_prose/__init__`,
    `hermes_cli/config.py §model_context_window/_MODEL_CONTEXT_WINDOW`,
    `cli.py §_push_tui_status/_toggle_yolo`,
    `tests/tui/test_crush_easy_wins.py` (new, 50 tests)
- **Execute-code output display + UX fixes** (2026-04-20):
  `cli.py._on_tool_complete`: added `execute_code` branch after SEARCH/WEB `_result_lines` block —
  parses JSON result (`{"output","error","stderr"}`), splits into `_result_lines`, fed into `ECB.append_line()`
  before `complete()`. Both stdout and stderr now visible in the OutputSection.
  `hermes_cli/tool_icons.py.DISPLAY_NAMES["execute_code"]`: changed from `"exec"` → `"python"` (removes
  the stale `[🐍] exec` display name).
  `widgets.py._EchoBullet`: refactored from `render()`+`height:1` (overflows) to `compose()+Static`+`height:auto`
  (word-wraps at terminal width). Pulse animation: `_pulse_step()` and `_pulse_stop()` overridden to call
  `_push()` → updates inner `Static` directly (no longer relies on `self.refresh()` triggering `render()`).
  `_build_text()` extracts the Rich Text builder; `Text(overflow="fold")` ensures long messages fold at
  container boundary rather than overflow the terminal.
  → `cli.py §_on_tool_complete`, `hermes_cli/tool_icons.py §DISPLAY_NAMES`,
    `hermes_cli/tui/widgets.py §_EchoBullet`
- **Tool Block Click + Path/URL Linkification** (2026-04-20): 3 sub-features. 35 new tests in
  `tests/tui/test_tool_block_click_links.py`. Spec at `/home/xush/.hermes/tui-tool-block-click-links-spec.md`.
  **Feature 1 (always-clickable toggle)**: `ToolHeader.on_click` now delegates to `panel.action_toggle_collapse()`
  BEFORE the `_has_affordances` guard — all completed blocks toggle on click regardless of line count.
  **Feature 2 (args row)**: `ToolBodyContainer` gains `--args-row` Static (composed before CopyableRichLog);
  `set_args_row(text)` shows/hides it. `_build_args_row_text(spec, tool_input)` module helper formats
  non-primary args. `STB.complete()` calls `set_args_row` via spec lookup.
  **Feature 3 (linkification)**: `_linkify_text(plain, rich_text)` + `_first_link(plain)` helpers in
  `tool_blocks.py`. Apply underline + `meta={"_link_url": url}` to URLs and file paths.
  `STB.append_line()` changed: `_pending` now stores `(Text, str)` (pre-linkified Rich Text) instead
  of `(str, str)`. `_flush_pending`/`rerender_window`/`reveal_lines`/`collapse_to` all pass
  `link=_first_link(plain)` to `write_with_source`. `CopyableRichLog.write_with_source(link=None)` stores
  link in `_line_links`; `on_click` hits Rich meta first, falls back to `_line_links[content_y]`;
  posts `CopyableRichLog.LinkClicked(url)`. `HermesApp.on_copyable_rich_log_link_clicked` + 
  `_open_external_url(url)` (scheme whitelist: http/https/file). `osc8.py` extended with `_URL_RE`/`_URL_TRAIL_RE`
  + URL branch in `inject_osc8`; URL sub applied BEFORE path sub to prevent double-match.
  `_LINK_PATH_RE` / `_PATH_RE` both use `(?<![=:\w/])` negative lookbehind to skip paths inside URLs.
  `execute_code_block.py._flush_pending` updated to handle `Text` in batch (isinstance check).
  **Fixes**: `test_click_calls_toggle_exactly_once` updated to patch `panel.action_toggle_collapse`
  (ToolBlock is now always wrapped in ToolPanel via `mount_tool_block`). Category header font: bold,
  non-italic, unquoted (was `"query"` italic). MCP microcopy `" server"` suffix added.
  Web search/extract result body: `close_streaming_tool_block` gains `result_lines` param; split in
  `cli.py` for SEARCH/WEB tools; fed into STB before `complete()`.
  → `hermes_cli/tui/tool_blocks.py §on_click/ToolBodyContainer/set_args_row/_build_args_row_text/
    _linkify_text/_first_link/_LINK_PATH_RE/append_line/_flush_pending/rerender_window/reveal_lines/collapse_to`,
    `hermes_cli/tui/widgets.py §CopyableRichLog.write_with_source/on_click/clear/_line_links/LinkClicked`,
    `hermes_cli/tui/osc8.py §_URL_RE/_URL_TRAIL_RE/inject_osc8`,
    `hermes_cli/tui/app.py §on_copyable_rich_log_link_clicked/_open_external_url`,
    `hermes_cli/tui/execute_code_block.py §_flush_pending`,
    `tests/tui/test_tool_block_click_links.py` (new, 35 tests),
    `tests/tui/test_tool_blocks.py §test_click_calls_toggle_exactly_once` (updated),
    `tests/tui/test_tool_header_v4.py §test_query_bold_not_quoted` (updated)
- **Custom Emoji** (2026-04-20): `hermes_cli/tui/emoji_registry.py` (NEW) — `EmojiEntry` dataclass
  (`name, path, description, pil_image, cell_width=2, cell_height=1, n_frames=1`), `normalize_emoji()`
  (cell_height always 1; LANCZOS resize into cell budget), `_cell_px()` helper delegating to
  `kitty_graphics._cell_px()`, `EmojiRegistry` (load/get/all_entries/is_empty/system_prompt_block +
  disk cache at `emojis/.cache/` + orphan cleanup + `reload_normalized` for cell_px changes).
  `AnimatedEmojiWidget` via deferred factory `_build_animated_emoji_widget()` + cached
  `get_animated_emoji_widget_class()` — `@work(thread=True)` on_mount extracts GIF frames;
  `set_timer` (one-shot, recursive) honors per-frame `duration`; falls back to static for
  `HALFBLOCK`/`NONE` caps. Config: `display.custom_emojis: "auto"` + `emoji: {max_cell_width,
  disk_cache, reasoning}`. System prompt block injected in `main()` from `_registry.system_prompt_block()`.
  `_EMOJI_RE = re.compile(r":([a-zA-Z0-9_-]+):")` in `response_flow.py`. `_extract_emoji_refs()`
  + `_mount_emoji()` in `ResponseFlowEngine`; wired in Phase 6 after prose write. `ReasoningFlowEngine`
  gets `_emoji_registry`/`_emoji_images_enabled` gated on `_emoji_reasoning` config. `HermesApp.
  _resolve_user_emoji()` resolves `:name:` in user messages (on event-loop thread);
  wired in `echo_user_message`. `on_resize()` triggers `reload_normalized` via `run_worker(thread=True)`
  when cell_px changes. Image fallback: HALFBLOCK/NONE caps → write `:name:` as prose.
  50 tests in `tests/tui/test_emoji_registry.py`.
  → `hermes_cli/tui/emoji_registry.py` (new), `hermes_cli/tui/response_flow.py §_EMOJI_RE/
    _extract_emoji_refs/_mount_emoji/_has_image_support/ResponseFlowEngine.__init__/
    ReasoningFlowEngine.__init__`, `hermes_cli/tui/app.py §_resolve_user_emoji/echo_user_message/
    on_resize`, `hermes_cli/config.py §custom_emojis/emoji`, `cli.py §_custom_emojis_enabled/
    _emoji_registry/main emoji injection`, `tests/tui/test_emoji_registry.py`
- **GeneratorEffect stream effect** (2026-04-20): `GeneratorEffect` (`generator`) added to
  `hermes_cli/stream_effects.py`. Mirrors the glitched-writer neo preset: each char cycles
  `_` (steps>5) → `/` (steps>2) → `-` (steps>0) → real char, with per-char random steps (3–8)
  and left-to-right index stagger (char at index `i` blocked until `global_tick >= i * stagger`).
  Config keys: `stream_effect_gen_min_steps` (3), `stream_effect_gen_max_steps` (8),
  `stream_effect_gen_stagger` (1). Spaces get steps=0 (instant reveal). 6 new tests in Group H
  of `tests/tui/test_stream_effects.py`. `VALID_EFFECTS` now has 13 entries.
  → `hermes_cli/stream_effects.py §GeneratorEffect/_EFFECT_MAP/VALID_EFFECTS`,
    `tests/tui/test_stream_effects.py §Group H`
- **Stream Effects v2 + skin override** (2026-04-20): 5 new `StreamEffectRenderer` subclasses in
  `hermes_cli/stream_effects.py` — `GlitchMorphEffect` (`glitch_morph`), `CascadeRevealEffect`
  (`cascade`), `NierEffect` (`nier`), `ZalgoEffect` (`zalgo`), `CosmicFadeEffect` (`cosmic`).
  All `needs_clock=True`, TUI-mode only (terminal falls back to base). 59 tests total in
  `tests/tui/test_stream_effects.py` (+31 new: 25 effect + 4 skin override).
  `_stream_effect_cfg()` extended: reads active skin raw YAML for top-level `stream_effect` key;
  string shorthand or dict with `enabled` + per-effect tuning keys. Skin value overrides
  `config.yaml`. `skins/matrix.yaml` activates `cascade` (`cascade_ticks: 3`).
  `docs/skins/example-skin.yaml` documents all 12 effects with full config schema.
  → `hermes_cli/stream_effects.py §GlitchMorphEffect/CascadeRevealEffect/NierEffect/ZalgoEffect/
    CosmicFadeEffect/_NEO_SYMBOLS/_NIER_CHARS/_ZALGO_MARKS/_COSMIC_GHOSTS`,
    `hermes_cli/tui/widgets.py §_stream_effect_cfg (skin override path)`,
    `skins/matrix.yaml §stream_effect`, `docs/skins/example-skin.yaml §stream_effect`,
    `tests/tui/test_stream_effects.py §H/I/J/K/L/G3/G4`
- **Browse Mode Visual Markers** (2026-04-20): 31 tests across `tests/tui/test_browse_markers.py` + `tests/tui/test_browse_minimap.py`. New file: `hermes_cli/tui/browse_minimap.py`. Spec at `/home/xush/.hermes/tui-browse-mode-markers-spec.md` (v2, reviewed).
  Key arch invariants:
  - **`M` / `m` are taken** — MEDIA anchor nav in browse `on_key` Priority -2 block (app.py). Minimap toggle uses `\` (backslash).
  - **`_clear_browse_pips` removes ALL pip classes** — query `.--has-pip`, then `remove_class("--has-pip", "--anchor-pip-turn", "--anchor-pip-code", "--anchor-pip-tool", "--anchor-pip-diff", "--anchor-pip-media")`. CSS border-left is on type-specific class, not shared class — removing only `--has-pip` leaves border visible.
  - **`_apply_browse_pips` calls `_clear_browse_pips` first** — always reset before reapplying (prevents class accumulation across rebuilds).
  - **`StreamingCodeBlock` has no default border** — `StreamingCodeBlock.--anchor-pip-code` must add `border-top: tall $browse-code 25%` alongside `border-left` so `border_title` (badge) renders in top strip. Without it, `border_title` is invisible.
  - **`watch__browse_badge`** — double underscore is the correct Textual watcher name for reactive `_browse_badge` (`_attr` → `watch__attr`).
  - **Reasoning markers**: `walk_children` is recursive — reasoning code blocks ARE naturally included as `CODE_BLOCK` anchors. `_apply_browse_pips` checks `_is_in_reasoning(widget)` and skips pip/badge when `_browse_reasoning_markers=False`. Config: `display.browse_markers.reasoning=True` (default on).
  - **All 4 boundary TCSS rules** in §4.2: base `UserMessagePanel`, `--browse-active` promotion, `--no-turn-boundary` override (×2 — with and without `--browse-active`).
  - **MEDIA glyph**: use `▶` (U+25B6, single-width) not `🖼` (2-cell emoji). Fallback `[M]` when `HERMES_NO_UNICODE`.
  - **`BrowseMinimap(Widget)` `dock: right`** inside `OutputPanel` — pins to viewport right edge (not scrolled with content), correct for minimap. Width: 1 cell.
  - **`_browse_badge_widgets: list[Widget]`** on `HermesApp` — tracks which widgets received badges for cleanup. Capped at 200 for perf.
  → `hermes_cli/tui/app.py §_apply_browse_pips/_clear_browse_pips/watch_browse_mode/action_toggle_minimap/on_key`,
    `hermes_cli/tui/browse_minimap.py` (NEW),
    `hermes_cli/tui/widgets.py §StreamingCodeBlock._browse_badge/watch__browse_badge/complete flash`,
    `hermes_cli/tui/tool_blocks.py §ToolHeader._browse_badge/render`,
    `hermes_cli/tui/hermes.tcss §browse-* vars/pip classes/boundary rules`,
    `hermes_cli/tui/theme_manager.py §browse-* component vars`,
    `hermes_cli/config.py §display.browse_markers`,
    `cli.py §_browse_markers_enabled/_browse_reasoning_markers/etc`,
    `tests/tui/test_browse_markers.py` (new), `tests/tui/test_browse_minimap.py` (new)
- **Citations & SourcesBar** (2026-04-20): 25 tests in `tests/tui/test_citations.py`. `[CITE:N Title \u2014 URL]` tags suppressed from prose, collected, `SourcesBar` mounted at `flush()`.
  - `_CITE_RE = re.compile(r'^\[CITE:(\d{1,4})\s+(.+?)\s+\u2014\s+(https?://\S+)\]$')` at module level in `response_flow.py`.
  - `ResponseFlowEngine`: `_cite_entries: dict[int, tuple[str,str]]`, `_cite_order: list[int]`, `_citations_enabled: bool`. Cite detection in `process_line()` NORMAL state after footnote check. `_mount_sources_bar()` uses `panel.call_after_refresh` (NOT `call_from_thread` — flush is on event loop).
  - `ReasoningFlowEngine`: mirrors all three attrs; `_citations_enabled` gated by `_citations_enabled and _reasoning_rich_prose`. `_render_footnote_section()` override respects `_reasoning_rich_prose` — delegates to `super()` when `True`, no-op when `False`. Use `self._panel.app` not bare `panel.app`.
  - `SourcesBar(Widget)` in `widgets.py` — `_urls` dict built in `__init__` (not `compose()`). Chips open URLs via `subprocess.Popen([opener, url])`. `_extract_domain()` + `_truncate()` helpers at module level.
  - Config: `display.citations=True`, `display.reasoning_rich_prose=True`. Both default `True` — active for prose and reasoning by default.
  - CSS vars `$cite-chip-bg`/`$cite-chip-fg` in `hermes.tcss`; `COMPONENT_VAR_DEFAULTS` in `theme_manager.py`.
  - System prompt hint injected when `_citations_enabled` and TUI mode active.
  → `hermes_cli/tui/response_flow.py §_CITE_RE/cite attrs/process_line/flush/_mount_sources_bar/ReasoningFlowEngine`,
    `hermes_cli/tui/widgets.py §SourcesBar/_extract_domain/_truncate`,
    `hermes_cli/config.py §display.citations/reasoning_rich_prose`,
    `cli.py §_citations_enabled/_reasoning_rich_prose/system prompt hint`,
    `hermes_cli/tui/hermes.tcss §cite vars`, `hermes_cli/tui/theme_manager.py §cite vars`,
    `tests/tui/test_citations.py` (new, 25 tests)
- **Tool Call UX Pass 4 — Phase 3** (2026-04-20): 19 tests in `tests/tui/test_ux_phase4_p3.py`. Covers B4/C2/C3/D3/D4/F1/G1/G2/G3.
  - **B4**: Flash timer aligned to `_flash_expires` TTL — both 1.2s (was 1.3s timer).
  - **C2**: `StreamingToolBlock._follow_tail: bool = False`; `append_line()` calls `rerender_window()` every 5 lines when set; `complete()` resets. `ToolPanel` gains `Binding("f", "toggle_tail_follow")` + `action_toggle_tail_follow()`.
  - **C3**: `ShellRenderer.finalize()` detects JSON (`{`/`[`) or YAML (`---`) and returns `rich.Syntax`; plain text returns None.
  - **D3**: All chip remediation hints joined with `"  ·  "` separator (was first-only).
  - **D4**: `_build_hint_text()` now shows `C/H color/html`, `I invocation`, `u urls` (when URL artifacts present).
  - **F1**: `set_result_summary_v4()` schedules `set_timer(10.0, _show_age)` → `block.set_age_microcopy(f"completed {elapsed}s ago")`. `set_age_microcopy()` no-ops when `_completed=False`.
  - **G1**: `ToolPanel > .--focus-hint` gets `border-top: solid $boost` in `hermes.tcss`.
  - **G2**: `ToolBodyContainer.clear_microcopy()` no longer restores `_secondary_text` post-completion.
  - **G3**: `_TONE_STYLES: dict[str, str]` module constant extracted; both inline `tone_style = {...}` dicts replaced.
  → `hermes_cli/tui/tool_panel.py §_TONE_STYLES/toggle_tail_follow/D3 hints/D4 hint text/F1 timer`,
    `hermes_cli/tui/tool_blocks.py §_follow_tail/set_age_microcopy/clear_microcopy`,
    `hermes_cli/tui/body_renderer.py §ShellRenderer.finalize`,
    `hermes_cli/tui/hermes.tcss §--focus-hint`,
    `tests/tui/test_ux_phase4_p3.py` (new, 19 tests)
- **Tool Call UX Pass 4 — Phase 2** (2026-04-20): 22 tests in `tests/tui/test_ux_phase4_p2.py`. Covers B1/B2/B3/C1/D2/E1/H1.
  - **B1 — Error-kind icon override**: `tool_blocks.py` `_render_v4()` — after `icon_str = self._tool_icon or ""`, if `_tool_icon_error and _error_kind`, override icon with `_ERROR_ICON[_error_kind]` map.
  - **B2 — Suppress `{N}L` when hero set**: `elif self._line_count and not self._primary_hero:` — line count chip only shown when no hero chip set.
  - **B3 — MCP streaming microcopy fallback**: `streaming_microcopy.py` MCP branch — `server = prov[4:] if prov.startswith("mcp:") else ""`, then `__`-split fallback (last segment), then bare name. Removed `" server"` suffix.
  - **C1 — J/K page scroll + `<`/`>` top/bottom**: `tool_panel.py` BINDINGS — `Binding("J", "scroll_body_page_down")`, `Binding("K", "scroll_body_page_up")`, `Binding("less_than_sign", "scroll_body_top")`, `Binding("greater_than_sign", "scroll_body_bottom")`. Actions implemented on `ToolPanel`.
  - **D2 — Artifact chips as Buttons**: `tool_panel.py` `FooterPane` — `_artifact_row: Horizontal` in compose; `_rebuild_artifact_buttons()` mounts `Button(label, id=f"artifact-{i}")` per artifact. `on_button_pressed` dispatches to `action_open_primary` or `action_open_url`.
  - **E1 — `ToolPanelHelpOverlay`**: `overlays.py` — static binding table, `show_overlay()` / `hide_overlay()` / `on_key()` dismiss. `tool_panel.py` `action_show_help()` calls `self.app.mount(ToolPanelHelpOverlay())`. `Binding("question_mark", "show_help")` added.
  - **H1 — MCP remediation hints**: `tool_result_parse.py` `_MCP_REMEDIATIONS = {"timeout": ..., "parse": ..., "signal": ...}`. `mcp_result_v4()` error branch sets `remediation = _MCP_REMEDIATIONS.get(error_kind or "", None)` on the `Chip`.
  → `hermes_cli/tui/tool_blocks.py §_render_v4 error icon / line count guard`,
    `hermes_cli/tui/streaming_microcopy.py §MCP server fragment fallback`,
    `hermes_cli/tui/tool_panel.py §C1 page bindings/D2 artifact buttons/E1 show_help`,
    `hermes_cli/tui/overlays.py §ToolPanelHelpOverlay`,
    `hermes_cli/tui/tool_result_parse.py §_MCP_REMEDIATIONS/mcp_result_v4`,
    `tests/tui/test_ux_phase4_p2.py` (new, 22 tests)
- **Tool Call UX Pass 4 — Phase 1** (2026-04-20): 12 tests in `tests/tui/test_ux_phase4_p1.py`. Covers A1/A2/D1/E2.
  - **A1 — `edit_cmd` action**: `"edit_cmd"` added to `_IMPLEMENTED_ACTIONS`. `action_edit_cmd()` finds `edit_cmd` action in `_result_summary_v4.actions`, calls `app.query_one(HermesInput)`, sets `.value` + `.focus()`. `Binding("E", "edit_cmd")`. `HermesInput` imported from `hermes_cli.tui.input_widget` (NOT `widgets`).
  - **A2 — `open_url` action**: `"open_url"` added to `_IMPLEMENTED_ACTIONS`. `action_open_url()` finds first `kind="url"` artifact, calls `subprocess.Popen([opener, url])`. `Binding("O", "open_url")`.
  - **D1 — Error always expands**: `set_result_summary_v4()` — `if summary.is_error: self.collapsed = False` runs unconditionally (no longer guarded by `not _user_collapse_override`). Dead error-expand code in `_apply_complete_auto_collapse()` removed.
  - **E2 — `action_open_first` removed**: deleted as standalone method; `action_open_primary` covers both file + url artifacts.
  - **`action_open_primary` URL fallback**: when `header._path_clickable` is False, falls back to first `kind="url"` artifact via `subprocess.Popen`.
  → `hermes_cli/tui/tool_panel.py §_IMPLEMENTED_ACTIONS/action_edit_cmd/action_open_url/action_open_primary/D1 collapse fix`,
    `tests/tui/test_ux_phase4_p1.py` (new, 12 tests)
- **Tool Call UX Phase 2+3** (2026-04-20): 66 tests in `tests/tui/test_ux_phase2_3.py`. Covers A2/B2/B3/B4/C3/C4/C5/D1/D2/D3/E1/E2/E3/F2/G1/G2 from the UX review spec.
  - **A2 — Chip remediation hints**: `Chip.remediation: str | None = None` field in `tool_result_parse.py`. MCP `disconnected` chip → `"restart or check server logs"`; `auth` chip → `"re-authenticate with /mcp auth"`. `FooterPane._remediation_row()` renders dim italic hint row below chips when any chip has remediation.
  - **B2 — Streaming rate display**: `StreamingState.rate_bps: float | None = None` field. `StreamingToolBlock.__init__` gains `_rate_samples: deque[tuple[float, int], maxlen=20]`. `append_line()` appends `(time.time(), len(line))`. `_bytes_per_second() -> float | None`: filters last 2s, None if <2 samples. `_update_microcopy()` passes `rate_bps=self._bytes_per_second()`. `microcopy_line()` shows `· 12.3 kB/s` suffix when rate known.
  - **B3 — Artifact overflow cap**: `ResultSummaryV4.artifacts_truncated: bool = False`. `_ARTIFACT_DISPLAY_CAP = 5`. All artifact extractors store ALL artifacts (no parse-time cap); `FooterPane` caps display to 5 + shows `"[+N more]"` overflow chip. `FooterPane._show_all_artifacts: bool = False`; `_rebuild_chips()` rebuilds chip list on toggle. `TOOL_REGISTRY` unchanged.
  - **B4 — Config-driven caps**: `DEFAULT_CONFIG["display"]` gains `tool_visible_cap: 200`, `tool_line_byte_cap: 2000`, `tool_page_size: 50`, `tool_collapse_thresholds: {"verbose": 15, "normal": 10, "compact": 6}`. `StreamingToolBlock.on_mount()` reads these into `_visible_cap`, `_line_byte_cap`, `_page_size`.
  - **C3 — HTTP status last line**: `StreamingToolBlock._last_http_status: str | None = None`. `append_line()` checks line against `_HTTP_STATUS_RE = re.compile(r"HTTP/\d+(?:\.\d+)?\s+(\d{3})")` — captures status code. `microcopy_line()` appends `· HTTP 200` when `last_status` set.
  - **C4 — `_human_size()` helper**: in `streaming_microcopy.py` — `B`/`kB`/`MB` tiers. Replaces `_kb()` (kept as alias). Used in FILE microcopy branch.
  - **C5 — ANSI/HTML copy**: `CopyableRichLog._all_rich: list[Text] = []` populated in `write_with_source()` alongside `_plain_lines`. `action_copy_ansi()`: `Console(force_terminal=True, width=...)` + `Text.assemble(*_all_rich)`. `action_copy_html()`: `Console(record=True)` + post-inject `background-color` into `<body>`. `Binding("A", "copy_ansi")`, `Binding("H", "copy_html")`.
  - **D1 — Rate samples deque**: `deque(maxlen=20)` — see B2 above.
  - **D2 — WEB tool HTTP line detection**: see C3 above.
  - **D3 — Elapsed suffix**: `microcopy_line()` appends `· N.Ns` when `elapsed_s > 2.0`. AGENT branch with `reduced_motion=True` → static `Text("▸ thinking…")`. `_elapsed_suffix(elapsed_s)` helper.
  - **E1 — Error kind in result summary**: `ResultSummaryV4.error_kind: str | None = None`. `_parse_error_kind(text)` in `tool_result_parse.py` — maps keywords (`timed out` → `timeout`, `exit code` → `exit`, `killed`/`signal` → `signal`, `auth`/`permission` → `auth`, `refused`/`unreachable`/`network` → `network`). Called in `build_result_summary_v4()` when `is_error=True`. 7 tests.
  - **E2 — Collapse tier rationalization**: `_CATEGORY_DEFAULTS` in `tool_category.py` — AGENT+FILE=15 (verbose), SHELL+SEARCH+WEB+MCP=10 (normal), CODE+UNKNOWN=6 (compact).
  - **E3 — Header identity**: `header_label_v4()` in `tool_blocks.py` — MCP: `"server::method()"` from `tool_input.get("server","mcp") + "::" + name + "()"`. AGENT: first 60 chars of `tool_input.get("task") or tool_input.get("thought","")`. UNKNOWN: raw `tool_name`.
  - **F2 — Reduced motion env**: `HermesApp.__init__`: `self._reduced_motion = bool(os.environ.get("HERMES_REDUCED_MOTION"))`. Passed through to `_update_microcopy()` → `microcopy_line(reduced_motion=...)`.
  - **G1 — Copy invocation**: `"copy_invocation"` in `_IMPLEMENTED_ACTIONS`. `FooterPane.action_copy_invocation()` formats `tool_name(key=val, ...)` from stored `_tool_input`. `Binding("I", "copy_invocation")`.
  - **G2 — Copy URLs**: `"copy_urls"` in `_IMPLEMENTED_ACTIONS`. `FooterPane.action_copy_urls()` extracts URLs from `_all_rich` via regex; newline-joins; copies. `Binding("u", "copy_urls")`.
  → `hermes_cli/tui/streaming_microcopy.py §_human_size/_elapsed_suffix/microcopy_line rate_bps/elapsed_s/reduced_motion/last_status`,
    `hermes_cli/tui/tool_result_parse.py §Chip.remediation/ResultSummaryV4.artifacts_truncated/_ARTIFACT_DISPLAY_CAP/_parse_error_kind`,
    `hermes_cli/tui/tool_blocks.py §StreamingToolBlock._rate_samples/_bytes_per_second/_last_http_status/header_label_v4`,
    `hermes_cli/tui/tool_panel.py §FooterPane._show_all_artifacts/_rebuild_chips/_remediation_row/action_copy_invocation/action_copy_urls`,
    `hermes_cli/tui/tool_category.py §_CATEGORY_DEFAULTS E2 tiers`,
    `hermes_cli/tui/widgets.py §CopyableRichLog._all_rich/action_copy_ansi/action_copy_html`,
    `hermes_cli/tui/app.py §HermesApp._reduced_motion`,
    `hermes_cli/config.py §DEFAULT_CONFIG.display tool caps`,
    `tests/tui/test_ux_phase2_3.py` (new, 66 tests)
- **Tool Call UX Phase 1** (2026-04-20): 26 tests in `tests/tui/test_ux_phase1.py`. Covers A1+A3+B1+C1+C2+F1 from the UX review spec (`/home/xush/.hermes/tui-tool-call-ux-review-2026-04-20.md`).
  - **A1 — `_error_kind_display(kind, detail, icon_mode)` helper** in `tool_result_parse.py`: `_ERROR_DISPLAY` dict (6 kinds: timeout/exit/signal/auth/network/parse), `_MODE_IDX`, function returns `(icon, label, css_var_name)`. Error CSS vars declared in `hermes.tcss`: `$error-timeout` (amber), `$error-critical` (red), `$error-auth` (yellow), `$error-network` (orange). `ToolHeader.__init__` gains `_error_kind: str | None = None`. `ToolPanel.set_result_summary_v4()` wires `header._error_kind = summary.error_kind`. `_render_v4()` uses `_error_kind` + `_tool_icon_error` to color hero chip. `app.get_css_variables()` returns keys **without `$` prefix**.
  - **A3 — Silent failure fallbacks**: `_render_v4()` None → ASCII header `"[tool] {label}"` + `--header-degraded` class. `BodyPane.__init__` renderer exception → `PlainBodyRenderer()` fallback + `logging.getLogger(__name__).debug(...)` (NOT `None`). `_refresh_tool_icon()` exception → `_CATEGORY_DEFAULTS[spec.category].ascii_fallback or "?"`. Diff path None → `_diff_file_path` stays `None`, header renders without crash.
  - **B1 — Secondary args in microcopy slot**: `_secondary_args_text(category, tool_input) -> str` helper in `tool_blocks.py` (FILE write/read, SHELL env/cwd, SEARCH glob, AGENT task, MCP first 2 args). `ToolBodyContainer` gains `_secondary_text`, `_microcopy_active`, `update_secondary_args()`, `set_microcopy()`, `clear_microcopy()`. **CSS class exclusivity**: `set_microcopy()` removes `--secondary-args` before adding `--active`; `clear_microcopy()` removes `--active`, adds `--secondary-args` back if `_secondary_text` non-empty — they NEVER coexist. TCSS: `ToolBodyContainer .--microcopy.--secondary-args { display: block; color: $text-muted; opacity: 0.6; }`. `StreamingToolBlock.__init__` gains `tool_input: dict | None = None`.
  - **C1 — `action_open_primary()`** on `ToolPanel`: opens `header._full_path` (actual attr — NOT `_label_path`) via `app._open_path_action(header, header._full_path, opener, False)` when `header._path_clickable` (actual attr — NOT `_is_path_clickable`); else falls back to `action_open_first()`. `"open_first"` stays in `_IMPLEMENTED_ACTIONS` (footer chip guard — orthogonal to key binding).
  - **C2 — j/k scroll**: `Binding("j"/"k", "scroll_body_down/up")` on `ToolPanel`. Guard: `not self.collapsed` (reactive, no underscore).
  - **F1 — Accessible mode**: `_accessible_mode() -> bool` on `ToolHeader`: `True` when `HERMES_ACCESSIBLE=1` or `app.console.color_system in (None, "standard")`. Prepends `[>]`/`[+]`/`[!]` to header. State from private attrs: `_spinner_char is not None` → `[>]`; `_tool_icon_error` → `[!]`; `_is_complete` → `[+]`. **Do NOT use CSS classes `--completed`/`--error` — they don't exist on `ToolHeader`.**
  → `hermes_cli/tui/tool_result_parse.py §_ERROR_DISPLAY/_error_kind_display`,
    `hermes_cli/tui/tool_blocks.py §ToolBodyContainer/ToolHeader._accessible_mode/_error_kind/_render_v4/StreamingToolBlock._secondary_args_text/tool_input`,
    `hermes_cli/tui/tool_panel.py §BodyPane.__init__/action_open_primary/action_scroll_body_down/up`,
    `hermes_cli/tui/body_renderer.py §PlainBodyRenderer`,
    `hermes_cli/tui/hermes.tcss §error-* CSS vars/--secondary-args rule`,
    `tests/tui/test_ux_phase1.py` (new, 26 tests)
- **Tool UX Pass 3** (2026-04-20): 11 fixes across P0/P1/P2 categories + ~27 new tests.
  - **§1 MCPBodyRenderer**: New class in `body_renderer.py`; registered for `ToolCategory.MCP`.
    `render_stream_line` = ANSI passthrough. `finalize` extracts `content[].text` from JSON.
    Tests: `tests/tui/test_body_renderer.py` (6 tests, new file).
  - **§2 Footer retry**: `"retry"` added to `_IMPLEMENTED_ACTIONS`. `action_retry()` calls
    `app._initiate_retry()` when `rs.is_error`. `Binding("r","retry")` added. `_build_hint_text()`
    shows "r retry" hint on error results. `_artifact_icon(kind)` helper extracted from inline code
    in `FooterPane` — testable, used by FooterPane too.
  - **§3 `_label_rich` in ToolHeader**: `_render_v4()` now reads `_label_rich` (set by ECB with
    syntax-highlighted label) before falling back to `header_label_v4()`. Truncated via
    `label_text.divide([available])[0]` + `"…"` append.
  - **§4 ANSI preservation**: `StreamingToolBlock` gains `_all_rich: list[Text]`.
    `append_line()` populates both `_all_plain` and `_all_rich`. `rerender_window()`,
    `reveal_lines()`, `collapse_to()` all zip `_all_rich` with `_all_plain` — color preserved on scroll.
  - **§5 ECB top OmissionBar**: `_apply_execute_mount_overrides()` now mounts both bars eagerly
    on `OutputSection` (top bar `before=rl`). Removed lazy bottom-bar mount from `_flush_pending()`.
  - **§6 FILE microcopy denominators**: Removed `total_str`/`total_kb` from FILE template.
    Now `▸ N lines · XkB` (no `?`).
  - **§7 MCP microcopy clear**: Removed `if spec.category == ToolCategory.MCP: return` guard
    from `_clear_microcopy_on_complete()`. All tools clear microcopy on complete.
  - **§8 `[reset]` button**: OmissionBar bottom `"[↑cap]"` → `"\\[reset]"` (backslash-escaped
    to prevent Rich markup `[reset]` tag swallowing the text — renders as `[reset]`).
  - **§9 Dead CSS**: `--flash-complete` rule removed from `hermes.tcss`.
  - **§10 Artifact icons**: `_artifact_icon(kind)` helper in `tool_panel.py` respects
    `get_tool_icon_mode()`: nerdfont/auto → `\uf15b`/`\uf0c1`/`\uf03e`; emoji → 📎/🔗/🖼; ascii → [F]/[L]/[I].
  - **§11 Collapse no-op flash**: `action_collapse_lines()` guards with no-op check + `_flash_header("at minimum")`.
  Key gotcha: **Rich markup in Button labels** — `"[reset]"` is a Rich markup reset tag → renders empty.
  Must escape as `"\\[reset]"`. Same issue would affect any `[word]` label — always escape or use `Text.from_markup`.
  → `hermes_cli/tui/body_renderer.py §MCPBodyRenderer`,
    `hermes_cli/tui/tool_panel.py §_IMPLEMENTED_ACTIONS/_artifact_icon/action_retry/_build_hint_text/action_collapse_lines`,
    `hermes_cli/tui/tool_blocks.py §StreamingToolBlock._all_rich/append_line/rerender_window/reveal_lines/collapse_to/OmissionBar.compose`,
    `hermes_cli/tui/execute_code_block.py §_apply_execute_mount_overrides/_flush_pending`,
    `hermes_cli/tui/streaming_microcopy.py §microcopy_line FILE branch`,
    `hermes_cli/tui/hermes.tcss §--flash-complete removed`,
    `tests/tui/test_body_renderer.py` (new, 6 tests),
    `tests/tui/test_tool_panel.py` (8 new tests),
    `tests/tui/test_tool_blocks.py` (12 new tests),
    `tests/tui/test_omission_bar.py` (1 new test)
- **ExecuteCodeBlock spec review complete** (2026-04-20): 4-pass review loop; spec accuracy 4/10 → 10/10.
  Key implementation facts surfaced and now documented in spec:
  - **`call_from_thread` race**: `_open_execute_code_block` is async; `_gen_blocks_by_idx` is never
    actually populated on the gen_start path (`result[0]` still None when checked). All ECBs are
    created via the tool_start fallback path in practice.
  - **Fallback ECBs lack ToolPanel**: the `_create_ecb_fallback` closure mounts the bare
    `ExecuteCodeBlock` without a `ToolPanel` wrapper — these blocks have no J/K navigation or
    browse anchor registration.
  - **Highlight/finalize path**: ECB does NOT call `StreamingCodeBlock._highlight_line` or
    `_finalize_syntax` — it uses `BodyRenderer.for_category(ToolCategory.CODE).highlight_line()`
    and `BodyRenderer.finalize_code(code, theme, bg)`. `finalize_code` internally slices to
    `lines[1:]` and returns `None` for single-line code (body stays empty for short scripts).
  - **Flash CSS vars**: `$success 35%` and `$error 35%` (not `$addition-marker-fg`/`$deletion-marker-fg`).
  - **`CharacterPacer.__init__`** takes three params: `(cps, on_reveal, app=None)` — `app` required for `set_interval`.
  - **`PartialJSONCodeExtractor`** has 6 states: `seek | after_colon | before_open_quote | in_string | unicode_escape | done`.
    Seek uses `buf.find(needle)` (simple substring, not string-literal-aware).
  - **`ExecuteCodeBody` composes**: `CodeSection + OutputSeparator + OutputSection` (OutputSeparator
    shows dim "─── output" separator; display toggled with OutputSection at tool_start).
  - **`on_mount` deferred override**: ECB uses `call_after_refresh(_apply_execute_mount_overrides)`
    because parent `on_mount` runs after child in Textual MRO, overwriting `_has_affordances = True`.
  - **`#code-live-cursor` Static**: cursor mount wrapped in `try/except` — silently skipped on failure.
  - **`flush()` stops timer**: `CharacterPacer.flush()` already stops drain timer internally; subsequent
    `stop()` call in `finalize_code` is a belt-and-suspenders no-op.
  → `execute-code-block-spec.md` (spec now accurate)
- **ExecuteCodeBlock bug fixes** (2026-04-20): Three cli.py races fixed:
  1. `_on_tool_gen_start` race: closures for `_open_execute` and `_open_write` now
     set `gen_blocks[idx] = b` directly from the event-loop callback (not via a
     `result[0]` closure that's always None when checked on the agent thread).
  2. Fallback ECBs now wrapped in `ToolPanel` (bare mount broke J/K nav + anchors).
  3. Fallback `finalize_code` race: moved inside `_create_ecb_fallback` closure,
     scheduled via `call_after_refresh` so mount completes first.
  Also added test_T48 (other tools label normal color) + test_T49 (right-align
  preserves affordances) to `tests/tui/test_tool_blocks.py`. 42 ECB-related tests pass.
  → `cli.py §_on_tool_gen_start/_create_ecb_fallback`, `tests/tui/test_tool_blocks.py`
- **Tool UX Pass 2 — Phases A–E** (2026-04-20): 5-phase UX upgrade to tool call display.
  **Phase A (footer actions)**: Real `action_copy_body`, `action_open_first`, `action_copy_err`,
  `action_copy_paths` in `FooterPane` with c/o/e/p bindings. `_IMPLEMENTED_ACTIONS` frozenset gates
  render. `_flash_header()` posts flash via `ToolHeader._flash_msg`/`_flash_expires`. `_render_stderr(tail)`
  method (multi-line, height auto; max 4). `_result_paths_for_action()` extracts paths for open/copy.
  Clipboard via `_copy_text_with_hint()` (OSC52 + xclip). `promoted_chip_texts` param in `update_summary_v4`.
  **Phase B (chevron + auto-collapse thresholds)**: Chevron always rendered in `_render_v4()` when
  `_has_affordances`, uses `self._panel.collapsed if self._panel is not None`. Thresholds updated:
  FILE→10, SHELL→8, CODE→5, AGENT→15, UNKNOWN→6.
  **Phase C (microcopy + stderr + chips)**: `_thinking_shimmer(elapsed_s)` returns `Text` (not `str`)
  for AGENT — animated lerp_color wave on `"Thinking…"`. `_last_n_chars_v4(text, n=300)` replaces
  `_last_line_v4` for stderr_tail — preserves newlines, 300 char cap. `_make_copy_err` hotkey "c"→"e".
  `promoted_chip_texts: frozenset[str]` for chip dedup in `set_result_summary_v4`.
  **Phase D (OmissionBar dual-bar redesign)**: Both bars always in DOM from `on_mount()` (guarded by
  `self._body.is_mounted` so `ExecuteCodeBlock` subclass doesn't crash). Display toggled by
  `_refresh_omission_bars()`. Top bar (`--omission-bar-top`): `[↑all](.--ob-up-all)` + `[↑+50](.--ob-up-page)`.
  Bottom bar (`--omission-bar-bottom`): `[↑cap](.--ob-cap)` + `[↑](.--ob-up)` + `[↓](.--ob-down)` +
  `[↓all](.--ob-down-all)`. All button actions route through `block.rerender_window(start, end)` — the
  canonical scroll primitive. `rerender_window` clears log, writes `_all_plain[start:end]`, updates
  `_visible_start`/`_visible_count`, calls `_refresh_omission_bars()`. `set_counts(visible_start,
  visible_end, total)` updates label + disabled states; only called when bar is visible.
  `ToolPanel.action_expand/collapse/expand_all_lines` updated to call `rerender_window` (old `_do_*` gone).
  API: `_omission_bar_bottom`, `_omission_bar_top`, `_omission_bar_bottom_mounted`, `_omission_bar_top_mounted`.
  **Phase E (MCP accent, diff CSS, narrow fix, Gantt scale)**: `ToolPanel.category-mcp` border in
  hermes.tcss. `_diff_bg_colors(self)` widget method reads `app._theme_manager._component_vars`.
  `COMPONENT_VAR_DEFAULTS`: added `tool-mcp-accent`, `diff-add-bg`, `diff-del-bg`. Narrow GroupBody
  `display:none` → `padding-left:0`. `_gantt_scale_text(turn_total_s, gantt_w, label_w)` + `#gantt-scale`
  Static in ToolsOverlay. Tests: `test_omission_bar.py` fully rewritten (25 tests, new API);
  `test_streaming_microcopy.py` AGENT tests check `isinstance(result, Text)`.
  → `hermes_cli/tui/tool_blocks.py`, `hermes_cli/tui/tool_panel.py`, `hermes_cli/tui/tool_category.py`,
    `hermes_cli/tui/tool_result_parse.py`, `hermes_cli/tui/streaming_microcopy.py`,
    `hermes_cli/tui/tools_overlay.py`, `hermes_cli/tui/theme_manager.py`, `hermes_cli/tui/hermes.tcss`,
    `tests/tui/test_omission_bar.py` (rewritten), `tests/tui/test_tool_panel.py`, `tests/tui/test_streaming_microcopy.py`
- **Binary collapse** (2026-04-19): `detail_level: reactive[int]` (L0–L3) **replaced** with
  `collapsed: reactive[bool]` on `ToolPanel`. `ArgsPane` class deleted. `tool_args_format.py` deleted.
  `CategoryDefaults`: removed `args_formatter` + `default_detail` fields. `ToolPanel.BINDINGS`: removed
  `d/D/0/1/2/3`; kept `enter/+/-/*`. `_apply_complete_auto_level` → `_apply_complete_auto_collapse`.
  Architecture invariant: `watch_collapsed` hides `block._body` (ToolBodyContainer), NOT BodyPane —
  BodyPane stays visible so ToolHeader remains clickable. Browse `a`/`A` handler queries `ToolPanel`
  (not ToolBlock) and checks `panel.collapsed`. CSS `ToolPanel ToolBodyContainer { display: block; }`
  in hermes.tcss ensures initial visibility. 1958 tests passing.
  → `hermes_cli/tui/tool_panel.py`, `hermes_cli/tui/app.py §on_key a/A`,
    `tests/tui/test_tool_panel.py`, `tests/tui/test_tool_blocks.py`, `tests/tui/test_p2_gaps.py`,
    `patterns.md §ToolPanel binary collapse`, `gotchas.md §ToolPanel binary collapse gotchas`
- **v4 graduation / P8** (2026-04-19): All v4 feature guards deleted, v2 dead paths removed.
  `_tool_panel_v4_enabled()`, `_tool_panel_v2_enabled()`, `_group_widget_enabled()`,
  `_tool_gutter_enabled()` — all guard functions gone. Config keys `display.tool_panel_v4`,
  `display.tool_panel_v2`, `display.tool_group_widget`, `display.result_hero` stripped.
  `ToolHeader.render()` always calls `_render_v4()`; v2 path gone. Widget grouping always runs.
  Post-graduation UX quick wins: AGENT default_detail 0→1; icon always colored after complete();
  FILE diff collapse threshold 20 lines; uniform microcopy for CODE/AGENT/UNKNOWN;
  FooterPane stderr split row; header-tail chips promotion.
  → `hermes_cli/tui/tool_blocks.py`, `hermes_cli/tui/tool_panel.py`, `hermes_cli/tui/tool_category.py`,
    `hermes_cli/tui/streaming_microcopy.py`, `hermes_cli/tui/tool_result_parse.py`
- **ToolsOverlay /tools timeline** (2026-04-19): `hermes_cli/tui/tools_overlay.py` (NEW) —
  `ToolsScreen(Screen)` first push_screen in this repo. Frozen snapshot at construction.
  `render_tool_row()` pure function. Gantt bar, export JSON, filter input, staleness pip.
  `T` key in browse mode + `/tools` slash command. Turn tracking: `_turn_tool_calls`,
  `_turn_start_monotonic` in HermesApp. `open_streaming_tool_block` assigns `id="tool-{tcid}"`.
  → `hermes_cli/tui/tools_overlay.py` (new), `hermes_cli/tui/app.py §open/close_streaming_tool_block`,
    `patterns.md §ToolsOverlay`, `gotchas.md §ToolsScreen async gotchas`
- **ToolGroup widget** (2026-04-19): `ToolGroup(Widget)` + `GroupHeader` + `GroupBody`.
  `_schedule_group_widget` always runs (CSS-only path deleted). `_group_reparent_worker` with 5-guard
  chain. `recompute_aggregate` N>20 bound. Browse integration: 1 anchor per group.
  → `hermes_cli/tui/tool_group.py`, `hermes_cli/tui/app.py §_schedule_group_widget`,
    `patterns.md §ToolGroup widget`
- **v4 P1–P7** (2026-04-19): ToolSpec/ToolCategory expanded (~70→~520 lines): `spec_for()`,
  `ToolSpec` frozen dataclass, `CategoryDefaults`, `MCPServerInfo`, 20 seed specs, 10 MCP servers.
  `header_label_v4()` + `_format_duration_v4()` in `tool_blocks.py`. `ResultSummaryV4` pipeline
  (`tool_result_parse.py` + category parsers). Streaming microcopy (`streaming_microcopy.py` NEW).
  OmissionBar keyboard bindings in `ToolPanel.BINDINGS` (`+/-/*`). Focused-panel hint row.
  → `hermes_cli/tui/tool_category.py`, `hermes_cli/tui/tool_blocks.py`,
    `hermes_cli/tui/tool_result_parse.py`, `hermes_cli/tui/streaming_microcopy.py` (new),
    `tests/tui/test_tool_spec.py`, `tests/tui/test_tool_header_v4.py`
- **Math formula & chart inline display** (2026-04-19): `hermes_cli/tui/math_renderer.py` (NEW) —
  `MathRenderer.render_unicode()` with 50-entry `_SYMBOL_TABLE` + superscript/subscript/frac/mathbf/mathit
  transforms. `render_block()` via `matplotlib.mathtext` → temp PNG (`transparent=True`; wraps in `$...$`
  if not already). `render_mermaid()` via `mmdc` or `npx @mermaid-js/mermaid-cli` subprocess (15s timeout).
  `ResponseFlowEngine` gains `IN_MATH` state + 7 new fields (`_math_lines`, `_math_env`, `_math_enabled`,
  `_math_renderer_mode`, `_math_dpi`, `_math_max_rows`, `_mermaid_enabled`) read from `panel.app.*` at init.
  Block math regexes (`_BLOCK_MATH_OPEN_RE`, `_BLOCK_MATH_CLOSE_RE`, `_BLOCK_MATH_ONELINE_RE`) checked
  **before** `_FENCE_OPEN_RE` in `process_line()` NORMAL block — `$$` would otherwise collide with fence.
  `_apply_inline_math()`: runs on `raw` line before `apply_block_line`; only substitutes when content
  contains `\`, `^`, or `_` (guards against `$100`, `$HOME`). `_flush_math_block()`: sync unicode path or
  async via `self._panel.app.run_worker(fn, thread=True)` + `call_from_thread`. `flush()` drains open
  `IN_MATH` state as unicode. `MathBlockWidget` in `widgets.py`: label + `InlineImage` child.
  `StreamingCodeBlock._finalize_syntax()` triggers `_try_render_mermaid_async()` for `lang == "mermaid"`;
  `_on_mermaid_rendered()` calls `self.parent.mount(InlineImage(...), after=self)` for sibling mount
  (NOT `self.mount(..., after=self)` — that uses the Textual anchor-resolution gotcha).
  `ReasoningFlowEngine.__init__` gets all 7 math fields with math/mermaid disabled (Non-Goal).
  Config: `display.math/math_renderer/mermaid/math_dpi/math_max_rows` in `config.py`; wired through
  `cli.py` to `HermesApp` plain attrs. 30 new tests in `tests/tui/test_math_renderer.py`.
  Key gotchas: `ResponseFlowEngine` is NOT a Widget — use `self._panel.app.run_worker()` not `@work`.
  `MathRenderer` uses lazy singleton `_get_math_renderer()` (avoids matplotlib import at module load).
  `render_block()` calls `matplotlib.use("Agg")` inside the method — must be before `pyplot` import.
  → `hermes_cli/tui/math_renderer.py` (new), `hermes_cli/tui/response_flow.py §IN_MATH/math fields/
    _apply_inline_math/_flush_math_block/_mount_math_widget/_mount_math_unicode`,
    `hermes_cli/tui/widgets.py §MathBlockWidget/StreamingCodeBlock._finalize_syntax/
    _try_render_mermaid_async/_on_mermaid_rendered`,
    `hermes_cli/tui/hermes.tcss §MathBlockWidget`, `hermes_cli/config.py §display.math*`,
    `cli.py §_math_enabled/_math_renderer/_mermaid_enabled/_math_dpi/_math_max_rows/
    system_prompt math hint (appended in main() after worktree injection, guarded by _math_enabled|_mermaid_enabled)`,
    `tests/tui/test_math_renderer.py` (new, 30 tests)
- **SDF crossfade warmup** (2026-04-19): No more blank overlay while SDF baker runs. `_get_engine()` sdf_morph
  branch now shows a braille warmup engine (`sdf_warmup_engine`, default `"neural_pulse"`) until
  `baker.ready.is_set()`. On ready edge, installs `CrossfadeEngine(warmup→SDF)`. After crossfade completes
  (`progress >= 1.0`), returns pure `SDFMorphEngine`. `hide()` resets all three warmup attrs. PIL-broken
  degradation: warmup runs forever (overlay stays alive). New config fields: `sdf_warmup_engine: str` +
  `sdf_crossfade_speed: float = 0.03` — round-tripped through `_current_panel_cfg` / `_fields_to_dict`.
  Key: `_sdf_crossfade`, `_sdf_warmup_instance`, `_sdf_baker_was_ready` are plain class attrs (not
  reactive). 8 new tests in `TestSDFCrossfadeWarmup` in `tests/tui/test_drawille_v2.py`.
  → `hermes_cli/tui/drawille_overlay.py §_get_engine/_get_sdf_engine/hide/DrawilleOverlayCfg/_overlay_config`,
    `tests/tui/test_drawille_v2.py §TestSDFCrossfadeWarmup`
- **Drawille fps reactive** (2026-04-19): `DrawilleOverlay.fps` reactive now controls actual tick rate.
  `_start_anim()` uses `self.fps` for both paths: `AnimationClock` gets `divisor = max(1, round(15/fps))`;
  `set_interval` fallback uses `1/fps`. `watch_fps()` restarts timer on change. `show()` syncs `self.fps =
  cfg.fps` so YAML/panel changes take immediate effect. `fps: 30` in YAML or AnimConfigPanel now works.
  → `hermes_cli/tui/drawille_overlay.py §_start_anim/watch_fps/show`
- **Browse mode unified anchor navigation** (2026-04-19): `BrowseAnchorType` enum + `BrowseAnchor` dataclass
  added at module level in `app.py`. `HermesApp` gains `_browse_anchors: list[BrowseAnchor]`,
  `_browse_cursor: int`, `_browse_hint: reactive[str]`. New methods: `_rebuild_browse_anchors()` (walks
  `OutputPanel.walk_children`, builds ordered list of TURN_START/CODE_BLOCK/TOOL_BLOCK anchors),
  `_jump_anchor(direction, filter_type)`, `_focus_anchor(idx, anchor, *, _retry=True)`,
  `_clear_browse_highlight()`, `_update_browse_status(anchor)`. New browse keys (before printable
  catch-all): `[`/`]` any anchor, `{`/`}` CODE_BLOCK only, `alt+up`/`alt+down` TURN_START only.
  Browse entry guard relaxed — no longer requires ToolHeaders to exist (enables text-only turn nav).
  `watch_browse_mode(True)`: resets `_browse_cursor=0` then rebuilds. `watch_browse_mode(False)`:
  clears `_browse_hint` + `_clear_browse_highlight()`. `watch_agent_running(False)`: calls
  `_rebuild_browse_anchors()` when `browse_mode` is active.
  `inject_diff()` in `tool_blocks.py`: adds `self._header.add_class("--diff-header")` so diff
  ToolHeaders get "Diff · " label prefix in anchor list.
  `StatusBar.render()`: reads `_browse_hint` reactive; when non-empty, appended after position
  indicator instead of default Tab hint. `_browse_hint` added to StatusBar watch list.
  CSS: `.--browse-focused` (accent), `StreamingCodeBlock.--browse-focused` (success),
  `UserMessagePanel.--browse-focused` (warning) in `hermes.tcss`.
  Key invariants: `StreamingCodeBlock` excluded while `_state == "STREAMING"`. `ToolHeader._label`
  (not `_title`) is the display label. `_browse_cursor` and `browse_index` are SEPARATE — Tab path
  updates only `browse_index`; `[`/`]` path updates only `_browse_cursor`. `_rebuild_browse_anchors`
  always clamps (never resets) cursor — callers that want reset set `_browse_cursor=0` first.
  `_focus_anchor` retry: on unmounted widget, rebuilds once and retries on first same-type anchor
  (lowest index); `_retry=False` prevents recursion. 24 new tests + 1 updated.
  → `hermes_cli/tui/app.py §BrowseAnchorType/BrowseAnchor/_rebuild_browse_anchors/_jump_anchor/
    _focus_anchor/watch_browse_mode/watch_agent_running/on_key`,
    `hermes_cli/tui/tool_blocks.py §inject_diff`,
    `hermes_cli/tui/widgets.py §StatusBar.render`,
    `hermes_cli/tui/hermes.tcss §--browse-focused`,
    `tests/tui/test_browse_nav_markers.py` (new), `tests/tui/test_tool_blocks.py` (guard test updated)
- **Drawille Animations v2** (2026-04-19): 12 new cinematic engines + core systems in `drawille_overlay.py`
  (now 2315 lines). **New engines:** `NeuralPulseEngine`, `FluidFieldEngine`, `LissajousWeaveEngine`,
  `AuroraRibbonEngine`, `MandalaBloomEngine`, `FlockSwarmEngine`, `ConwayLifeEngine`, `RopeBraidEngine`,
  `PerlinFlowEngine`, `HyperspaceEngine`, `WaveFunctionEngine`, `StrangeAttractorEngine`.
  **New systems:** `TrailCanvas` (temporal heat decay), `CompositeEngine` (additive/overlay/xor/dissolve
  blending), `CrossfadeEngine` (smooth engine transitions), adaptive `on_signal` protocol (detected via
  `hasattr` — no Protocol class). **`_ENGINES`** migrated from singleton instances to `dict[str, type]`
  class refs; `DrawilleOverlay._get_engine()` caches instance in `_current_engine_instance`, rebuilds on
  key change. **`AnimParams`** gained 9 new fields (heat, trail_decay, symmetry, particle_count,
  noise_scale, depth_cues, blend_mode, attractor_type, life_seed). **`DrawilleOverlayCfg`** gained 16
  v2 fields + full `_overlay_config()` parsing. **`AnimConfigPanel`** v2: 9 new panel fields, new
  `kind="float"` with step/clamp, `_PanelField.step: float`, `min_val`/`max_val` widened to float.
  **DrawilleOverlay** got 9 new reactive attrs + watchers + `_heat`/`_heat_target` adaptive heat.
  **`app.py`** heat injection: `watch_agent_running(False)` fires `on_signal("complete")`, token
  streaming bumps `_heat_target`, `_on_tool_complete` spikes heat to 1.0. **28 new tests** in
  `tests/tui/test_drawille_v2.py`. Key gotchas: `layer_b` excludes `sdf_morph`; all math via stdlib
  `math` (no numpy/Perlin library); ConwayLife uses set-based alive cells (not 2D array); StrangeAttractor
  computes scale bounds from 200 init ticks.
  → `hermes_cli/tui/drawille_overlay.py`, `hermes_cli/tui/app.py §watch_agent_running/_on_tool_complete`,
    `tests/tui/test_drawille_v2.py`
- **Stream Effects** (2026-04-18): `hermes_cli/stream_effects.py` (NEW) — `StreamEffectRenderer` base +
  `NoneEffect`, `FlashEffect`, `GradientTailEffect`, `GlowSettleEffect`, `DecryptEffect`, `ShimmerEffect`,
  `BreatheEffect`. `make_stream_effect(cfg, lock=None)`, `VALID_EFFECTS`, `_lerp_color` (re-export),
  `_get_accent_hex()` (uses `load_skin(Path)`, NOT `load_skin_vars`). Key: `on_token` does NOT acquire
  `self._lock` — demo caller holds lock before calling. `FlashEffect` + `GlowSettleEffect` both track
  `_buf_len: int = 0` running counter. `DecryptEffect` renders `_words + _current_partial` in `render_tui`;
  ignores `buf` param. GradientTailEffect `frac = (i+1)/max(len(tail),1)` — accent at tail end (newest).
  `LiveLineWidget`: `_stream_effect_name()` + `_stream_effect_cfg()` in `widgets.py`; `_stream_fx` loaded in
  `on_mount`; `_tick_stream_fx` with try/except; `render()` branches on `_stream_fx` with try/except fallback;
  `append()` + `_drain_chars()` call `register_token_tui`; `_commit_lines()` calls `clear_tui()`;
  `flush()` calls `on_turn_end()`. Config at `DEFAULT_CONFIG["terminal"]["stream_effect"]`. 28 new tests.
  → `hermes_cli/stream_effects.py` (new), `hermes_cli/tui/widgets.py §LiveLineWidget`,
    `hermes_cli/config.py §DEFAULT_CONFIG`, `tests/tui/test_stream_effects.py`
- **ResponseFlow chunk streaming** (2026-04-18): `feed(chunk)` added to `ResponseFlowEngine` — accumulates
  `_partial`, routes to `StreamingCodeBlock.feed_partial()` for in-code states (`IN_CODE`, `IN_INDENTED_CODE`,
  `IN_SOURCE_LIKE`). `feed()` NEVER calls `process_line()` (single-clock invariant: only `_commit_lines()` drives
  it). `flush()` drains `_partial` via `pending = self._partial; _clear_partial_preview(); process_line(pending)`.
  `StreamingCodeBlock`: `_partial_display = Static("", classes="--code-partial")` yielded in `compose()`;
  `feed_partial()` highlights fragment + appends `"▌"` cursor; `clear_partial()` hides display; guards at top
  of `append_line()`/`complete()`/`flush()`. `flush_live()` fixed: `engine._partial = live._buf` (NOT
  `engine.process_line(live._buf)`) to prevent double-processing; `engine.flush()` then processes it.
  `app._consume_output()`: inner try/except calls `engine.feed(chunk)` per chunk after `live_line.feed(chunk)`.
  `ReasoningFlowEngine.__init__` also gets `_partial: str = ""` field. 21 new tests.
  → `hermes_cli/tui/response_flow.py §feed/_route_partial/_clear_partial_preview/flush`,
    `hermes_cli/tui/widgets.py §StreamingCodeBlock`, `hermes_cli/tui/app.py §_consume_output`,
    `tests/tui/test_response_flow_chunk.py`
- **WorkspaceOverlay** (2026-04-18): `hermes_cli/tui/workspace_tracker.py` (NEW) —
  `WorkspaceTracker`, `GitPoller`, `GitSnapshot`, `FileEntry`, `analyze_complexity`,
  `WorkspaceUpdated`. `WorkspaceOverlay` added to `overlays.py` with `DEFAULT_CSS`.
  App integration: `_init_workspace_tracker` @work (subprocess off event loop →
  `_set_workspace_tracker` via `call_from_thread`); `_trigger_git_poll` / `_run_git_poll`
  @work; `_analyze_complexity` @work; `_refresh_workspace_overlay` helper;
  `on_workspace_updated` message handler; `action_toggle_workspace`; `w` key guard in
  `on_key` (skips when HermesInput has focus); `/workspace` in `_handle_tui_command`;
  `WorkspaceOverlay` added to `_dismiss_all_info_overlays` + escape Priority -2 block;
  5s background poll via `set_interval` in `watch_agent_running`. `cli.py §_on_tool_complete`:
  `record_write` + `_trigger_git_poll` + `_analyze_complexity` for file-mutating tools.
  Key threading rules: all tracker mutations (record_write, apply_git_status, set_complexity)
  on event loop thread; DOM queries from workers use `call_from_thread` + helper method;
  attributes set from workers use `call_from_thread`. 35 new tests
  (18 tracker unit + 17 overlay pilot). `ComplexityResult` message NOT used — results
  applied via `call_from_thread` directly.
  → `workspace_tracker.py` (new), `overlays.py §WorkspaceOverlay`, `app.py §workspace`,
    `cli.py §_on_tool_complete`, `tests/tui/test_workspace_tracker.py`,
    `tests/tui/test_workspace_overlay.py`
- **Media Extensions E/F/G** (2026-04-18):
  **Phase E (Vision inline):** `tools/vision_tools.py` — `_format_vision_result(result, source_path)` appends
  `\nMEDIA: /path\n` to vision tool success returns when `source_path` is a valid local file. Success path only.
  `source_path = str(local_path) if local_path.is_file() else None`. 8 tests in `tests/tools/test_vision_inline.py`.
  **Phase F (InlineImageBar):** `hermes_cli/tui/widgets.py` — `InlineThumbnail(Widget)` + `InlineImageBar(Widget)`.
  `InlineThumbnail` loads halfblock strips in a `@work(thread=True)` worker; results applied via
  `app.call_from_thread(_apply_strips, strips)`. `InlineImageBar.add_image` no-op when `_enabled=False`.
  `ImageMounted(Message)` defined in `tool_blocks.py`; posted from `StreamingToolBlock._try_mount_media()` after
  mount. `HermesApp.on_image_mounted` → `InlineImageBar.add_image`. `on_inline_image_bar_thumbnail_clicked` →
  `scroll_to_widget`. `display.image_bar: True` in DEFAULT_CONFIG; wired through `cli.py`→`app._inline_image_bar_enabled`.
  NOTE: existing `ImageBar` (id="image-bar") is for user-attached files — `InlineImageBar` (id="inline-image-bar")
  is the new thumbnail strip for model inline images. 13 tests in `tests/tui/test_image_bar.py`.
  **Phase G (Sixel):** `hermes_cli/tui/kitty_graphics.py` — `_sixel_probe()` (DA1 query), `_to_sixel()` (PIL→DCS),
  `_sixel_rle()`. Step 6.5 in `_detect_caps` (after APC, before COLORTERM). `widgets.py InlineImage`: `_sixel_seq`
  attr, `_prepare_sixel`, `_render_sixel_line`, `render_line` SIXEL branch, `watch_image` SIXEL routing.
  `_prepare_sixel` guards `_fit_image` with `if seq and cw > 0 and ch > 0`. 18 tests in `tests/tui/test_sixel.py`.
  Key: `Message` import needed in `widgets.py` for `InlineImageBar.ThumbnailClicked`. `@work(thread=True)` calls
  `_load_strips()` directly in `on_mount` — NOT `self.run_worker(...)`. Sixel thread safety is a follow-up (sync only in Phase G).
  → `tools/vision_tools.py`, `hermes_cli/tui/widgets.py`, `hermes_cli/tui/kitty_graphics.py`,
    `hermes_cli/tui/tool_blocks.py`, `hermes_cli/tui/app.py`, `hermes_cli/config.py`, `cli.py`
- **Footnotes Phase A** (2026-04-18): `[^N]` inline refs → Unicode superscripts; `[^N]: def` lines
  suppressed and collected; end-of-turn footnote section via `_render_footnote_section()`.
  `_FOOTNOTE_REF_RE` + `_SUP_TABLE` + `_to_superscript` in `agent/rich_output.py`; sub runs BEFORE
  `if "\x1b" in line:` guard so heading-embedded refs are also converted. `_FOOTNOTE_DEF_RE` at
  module level in `response_flow.py`; detection as first check inside `if self._state == "NORMAL":`.
  `ReasoningFlowEngine.__init__` mirrors the three attrs; `_render_footnote_section` overridden to
  no-op. `"footnote-ref-color": "#888888"` in `COMPONENT_VAR_DEFAULTS`; `$footnote-ref-color` in
  `hermes.tcss`. `write_with_source` (not bare `write`) for both separator and footnote lines.
  22 new tests in `tests/tui/test_footnotes.py`.
  → `agent/rich_output.py`, `hermes_cli/tui/response_flow.py`, `theme_manager.py`, `hermes.tcss`
- **Kitty TGP inline images — Phase D** (2026-04-18): `display.inline_images: auto|on|off` config — `off` forces
  placeholder regardless of terminal cap. `display.halfblock_dark_threshold` (float, default 0.1) — configurable
  WCAG luminance threshold for halfblock dark-cell detection. Threading for large images: `_prepare_tgp` dispatches
  to `@work(thread=True) _prepare_tgp_async` when `img.width * img.height * 4 > LARGE_IMAGE_BYTES (2_000_000)`;
  result applied via `app.call_from_thread(self._apply_tgp_result, ...)`. `KittyRenderer._alloc_id` protected
  by `threading.Lock`. `_apply_tgp_result` guards `is_mounted` before mutating state. 18 new tests.
  New exports from kitty_graphics: `set_inline_images_mode/get_inline_images_mode`, `set_dark_threshold/get_dark_threshold`,
  `LARGE_IMAGE_BYTES`, `_reset_phase_d`. Wired from cli.py `CliAgent.__init__` alongside other display config.
  → `hermes_cli/tui/kitty_graphics.py §Phase D`, `widgets.py §InlineImage._prepare_tgp/_prepare_tgp_async/_apply_tgp_result`,
    `cli.py §CliAgent.__init__`, `hermes_cli/config.py §DEFAULT_CONFIG.display`, `tests/tui/test_phase_d.py`
- **Kitty TGP inline images — Phases A–C** (2026-04-18): `hermes_cli/tui/kitty_graphics.py` (NEW) —
  `GraphicsCap` enum, `get_caps()/_detect_caps()/_reset_caps()` detection chain, `_cell_px()` ioctl,
  `_chunk_b64()/_build_tgp_sequence()/_fit_image()`, `KittyRenderer/_get_renderer()`, `render_halfblock()`,
  `_load_image()`. `InlineImage` widget added to `widgets.py` (deferred import pattern avoids circular).
  `HermesApp.on_unmount` emits `delete_all_sequence()` as safety net. `StreamingToolBlock._try_mount_media()`
  in `tool_blocks.py` (+ `_extract_image_path` + `_MEDIA_LINE_RE` at module level). Matplotlib auto-capture
  via `_MATPLOTLIB_CAPTURE_SNIPPET` appended to sandboxed script in `code_execution_tool.py`. `pillow` +
  `matplotlib` added to base deps in `pyproject.toml`. 45 new tests across 3 files.
  Key: `InlineImage` uses deferred imports (`from hermes_cli.tui.kitty_graphics import ...` inside methods)
  to avoid circular import at module load. `reactive` attrs require `Widget.__init__` — can't use
  `object.__new__` in tests; use `InlineImage()` directly. `size` property has no setter — use `or 80`
  fallback in render methods. HERMES_GRAPHICS env var overrides detection for CI/testing.
  `body_renderers/` package is EMPTY in live code (v3 spec diverged from implementation) — `ImageRenderer`
  skipped; MEDIA: detection works directly in STB.complete() instead.
  → `hermes_cli/tui/kitty_graphics.py`, `widgets.py §InlineImage`, `tool_blocks.py §_try_mount_media`,
    `app.py §on_unmount`, `tools/code_execution_tool.py §_MATPLOTLIB_CAPTURE_SNIPPET`,
    `tests/tui/test_kitty_graphics.py`, `tests/tui/test_halfblock_renderer.py`, `tests/tui/test_inline_image.py`
- **Slash command TUI integration — Phase 1-3** (2026-04-18): `hermes_cli/tui/overlays.py` (NEW) —
  `HelpOverlay`, `UsageOverlay`, `CommandsOverlay`, `ModelOverlay`. Imported at top of `app.py`.
  `_handle_tui_command` extended for `/help`, `/usage`, `/commands`, `/model`, `/clear`, `/new`,
  `/title`, `/stop`. `_dismiss_all_info_overlays()` method; called before any info overlay open and
  from `watch_agent_running(True)`. Escape at Priority -2 in `on_key`.
  `cli.py`: `/commands` handler; `show_tools()` + `_show_recent_sessions()` → `_cprint`. 28 new tests.
  → `hermes_cli/tui/overlays.py`, `app.py §_handle_tui_command`, `app.py §on_key`,
    `patterns.md §Overlay protocol`, `gotchas.md §Overlay and input behavior`
- **Drawille Animations v2** (2026-04-19): `drawille_overlay.py` extended with 12 new engines + compositing.
  `TrailCanvas` class (heat-map decay, threshold, set/decay_all/to_canvas/frame); `_make_trail_canvas(decay)` factory.
  Helpers: `_braille_density_set(canvas,x,y,intensity)`, `_depth_to_density(z,canvas,x,y)`, `_layer_frames(a,b,mode,heat)`,
  `_easing(t,kind)`. `AnimParams` gains 9 new fields: `heat`, `trail_decay`, `symmetry`, `particle_count`,
  `noise_scale`, `depth_cues`, `blend_mode`, `attractor_type`, `life_seed`. `DrawilleOverlayCfg` gains 16 v2 fields.
  `_ENGINES` is now `dict[str, type]` (class refs) — `_get_engine()` caches instance in `_current_engine_instance`;
  clears on `hide()` and key change; calls `on_mount` hook if present.
  Phase B engines: `NeuralPulseEngine`, `FlockSwarmEngine`, `ConwayLifeEngine`, `StrangeAttractorEngine`,
  `HyperspaceEngine`, `PerlinFlowEngine`. Phase C engines: `FluidFieldEngine`, `LissajousWeaveEngine`,
  `AuroraRibbonEngine`, `MandalaBloomEngine`, `RopeBraidEngine`, `WaveFunctionEngine`.
  Phase D: `CompositeEngine(layers, blend_mode)`, `CrossfadeEngine(engine_a, engine_b, speed)`.
  Adaptive signal protocol: engines optionally declare `on_signal(signal, value)` — detected via `hasattr`.
  `DrawilleOverlay` gains `_heat`, `_heat_target`, `_token_count_last`; heat smoothed in `_tick` at 0.15 rate.
  `_PanelField` gains `step: float`, `min_val`/`max_val` widened to float; new `kind="float"` supported in
  `action_inc_value`, `action_dec_value`, `_cycle`; `_format_field_value` formats float as `f"{v:.2f}"`.
  `AnimConfigPanel._build_fields()` adds 9 v2 fields; `layer_b` excludes `sdf_morph`.
  `_push_to_overlay`, `_current_panel_cfg`, `_fields_to_dict` all extended for v2. HermesApp heat injection
  at `watch_agent_running(False)`, `close_streaming_tool_block`, `mark_response_stream_delta`.
  Gotcha: `_ENGINES` is now class-refs, not instances — iterate as `engine_cls()` in tests.
  28 new tests in `tests/tui/test_drawille_v2.py`. Existing `test_drawille_overlay.py` updated to instantiate engines.
  → `hermes_cli/tui/drawille_overlay.py`, `hermes_cli/tui/app.py §close_streaming_tool_block/mark_response_stream_delta/watch_agent_running`,
    `tests/tui/test_drawille_v2.py`, `tests/tui/test_drawille_overlay.py`
- **Diff merged into patch STB header** (2026-04-18): `inject_diff(diff_lines, header_stats)` on STB;
  `close_streaming_tool_block_with_diff` on app; cli.py `_on_tool_complete` restructured.
  → `tool_blocks.py`, `app.py`, `cli.py §_on_tool_complete`
