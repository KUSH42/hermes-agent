# TUI Full Audit — 2026-04-25

**Scope:** `hermes_cli/tui/`
**Branch:** `feat/textual-migration`
**Method:** 7 parallel Explore subagents, one per axis (architecture, exception handling, dead code, performance, test coverage, theming, threading/async).

---

## Executive Summary

| Axis | HIGH | MED | LOW | Top hit |
|---|---|---|---|---|
| Architecture | 3 | 4 | 2 | `app.py` god object (2,545 LOC, 172 methods) |
| Exception handling | 6+ files | 23 files | — | Bare `except Exception: pass` across 23 modules without `_log` |
| Dead code | 3 | 2 | — | `perf.py:749 measure_perf()` zero callers |
| Performance | 0 | 2 | 3 | `Style()` recreated per row in `completion_list.py` |
| Test coverage | 5 files | 38 tests | 4 | `app.py`, `anim_engines.py`, `services/tools.py` no dedicated tests |
| Theming/CSS | 4 | 3 | 2 | Hardcoded `#9b59b6` in `hermes.tcss` for MCP accent |
| Threading/async | 2 | 2 | — | `asyncio.ensure_future` w/o ref + `MpvPoller` callbacks unmarshalled |

Total HIGH-priority items: **23**. Most are mechanical fixes; the architectural HIGHs (god-object, watchers antipattern, tool/session coupling) need design work.

---

## 1. Architecture

### HIGH

**A1. `app.py` god object** — `hermes_cli/tui/app.py:245–2545`
2,545 lines, 172 methods, 45 reactive fields. Mixes UI state, service orchestration, message routing, action handlers (29×), watchers (20×), event handlers (15×).
**Fix:** extract domain state objects (`BrowseState`, `StatusBar`, `CompactionState`, `SessionState`); move 29 `action_*` to `KeyDispatchService`; introduce `ReactiveCoordinatorService` for watchers. Target ~600 lines for `app.py`.

**A2. `services/watchers.py` is reactive dispatcher disguised as a service** — `services/watchers.py:21–552`
20+ stateless `on_*` handlers. Pattern violates separation between reactive binding and behaviour logic. Lines 472–511 (`on_status_error` + auto-clear timer) belong to `ThemeService`/`FeedbackService`.
**Fix:** inline `watch_*` back into `app.py` (Textual idiom) or create lightweight `ReactiveWatchBinder`. Move overlay handlers to `OverlayService`.

**A3. `ToolRenderingService` × `SessionsService` × `app._turn_tool_calls` triadic coupling** — `services/tools.py:145–1348`, `services/sessions.py:18–481`, `app.py:1539–1543`
`SessionsService.do_kill_session` does **not** call `_svc_tools.remove_streaming_tool_block`. `ToolRenderingService._turn_tool_calls` accessed via `self.app._svc_tools._turn_tool_calls` (private dict, breaks encapsulation).
**Fix:** `ToolStateService` owns `current_calls`, `stack`, `open_count`. `SessionsService.do_kill_session` calls `tool_state.clear_for_session(sid)` explicitly.

### MED

- **A4.** `tool_panel/__init__.py:1–43` re-exports 13 underscored privates (`_format_age`, `_TONE_STYLES`, `_ArtifactButton`, `_build_collapsed_actions_map`). Likely zero external callers — drop from `__all__`.
- **A5.** Bidirectional import: `tool_blocks/_block.py:14` imports `tool_panel.density.DensityTier`; `tool_panel/_actions.py:174` imports `tool_blocks.OmissionBar`. Move `DensityTier` into a `tool_common/` module or merge the two packages.
- **A6.** `body_renderers/__init__.py:94–196` `pick_renderer()` is 100+ lines of nested branching (streaming / KO-2 override / Phase C × 4 rules). Extract `RendererDispatcher` policy.
- **A7.** `tool_panel/_actions.py` (732 LOC) + `_completion.py` (493 LOC) mixin creep. Define `_ToolPanelProtocol(Protocol)` documenting the attributes both mixins poke at.

### LOW

- **A8.** `services/feedback.py` (554 LOC) mixes public protocols + impl — split into `feedback_protocol.py` / `feedback_types.py` / `feedback_service.py` if more channel adapters land.
- **A9.** `services/commands.py` (784 LOC) bundles slash-command dispatch + hint updates + action routing. Defer until next command feature.

---

## 2. Exception handling — CLAUDE.md compliance

Project rule: every `except` must re-raise, log with `exc_info=True`, or carry an explanatory comment. `except Exception: pass` is always wrong.

### CRITICAL: 23 modules with `except Exception: pass` and **no module logger**

`tool_category.py:368`, `emoji_registry.py` (9 sites: 122/134/157/174/187/213/215/232/303), `sub_agent_panel.py:60,72`, `animation.py:245,279`, `session_widgets.py` (15 sites: 71/109/114/125/196/215/222/229/236/243/250/309/315/333/360), `browse_minimap.py:52,64,74`, `completion_list.py:140,208`, `tooltip.py:81`, `write_file_block.py:88,94,135,201,227,242,303`, `pane_manager.py:296,340,348,407`, `overlays/_legacy.py:141,181,216,223,332`, `body_renderers/_grammar.py:61,218`, plus `min_size_overlay.py`, `execute_code_block.py`, `tte_runner.py`, `workspace_tracker.py`, `preview_panel.py`, `io_boundary.py`, `kitty_graphics.py`, `math_renderer.py`, `tool_result_parse.py`.

**Fix per file:** add `import logging; _log = logging.getLogger(__name__)` at top, replace `pass` with `_log.debug("op_name failed: <reason>", exc_info=True)` (or `warning`/`exception` per severity).

### HIGH: `@work(thread=True)` bodies that swallow silently

- `emoji_registry.py:290–304` — `on_mount()` worker, line 303 `except Exception: pass`. Wrap entire body in try/except → `_log.exception("EmojiWidget on_mount failed")`.
- `overlays/_legacy.py:132–142` — `_load_sessions()` worker, line 141 swallow. → `_log.exception("_load_sessions failed")`.
- `app.py:994–1009` — `_init_workspace_tracker()` line 1006 falls through silently. → `_log.exception("_init_workspace_tracker failed")`.

### Already-compliant (verified)

`completion_overlay.py:155,167,174`, `media_player.py:55,79`, `drawbraille_renderer.py:63`, `services/theme.py:67+` — all log with `exc_info=True`.

---

## 3. Dead code

### HIGH

- **D1.** `perf.py:749` `measure_perf()` — zero callers; duplicates `measure()` (line 112) with extra registry recording. Delete.
- **D2.** `tool_result_parse.py:178` `_ARTIFACT_CAP` — comment says `# legacy alias`, zero callers. Delete.
- **D3.** `resize_utils.py:13` `THRESHOLD_BAR_HIDE` — comment says `# legacy — watch_size uses 8/9/10`, zero callers. Delete.

### MED

- **D4.** `overlays/_legacy.py` (343 LOC, `SessionOverlay`, `ToolPanelHelpOverlay`, `_SessionResumedBanner`, `_SessionRow`, `_dismiss_overlay_and_focus_input`) — module docstring marks as Phase A–C legacy but symbols are still used and tested. Plan deprecation timeline or rename to `overlays/sessions_legacy.py`.
- **D5.** `overlays/_aliases.py` — runtime alias shims (`NewSessionOverlay`, `ModelPickerOverlay`, `TabbedSkinOverlay`). Active, but post-consolidation likely simplifiable.

(No orphan test files or scratch files in `tui/`.)

---

## 4. Performance

No event-loop blockers found. P1–P7 audit work holds. Remaining items are micro-optimisations.

### MED

- **P1.** `tools_overlay.py:372` — `on_unmount()` checks `_stale_timer is not None` then calls `.stop()` but does **not** null it. `_refresh_timer` (line 376) does. Fix asymmetry.
- **P2.** `completion_list.py:355,381,398` — `Style()` and `Style(dim=True, color="#888888")` recreated per row per render at 60 fps. Cache as `self._base_style_normal` / `self._base_style_selected` / `self._empty_style`, refresh on theme reload only.

### LOW

- **P3.** `services/watchers.py:118` `on_compact()` fires on every reactive change without a no-op guard. Add `if self.app.compact == value: return`.
- **P4.** `tool_blocks/_streaming.py:254` — flush-slow timer restart without null guard before reassign. Guard with `if self._render_timer: self._render_timer.stop()`.

### Verified-good

App-level timer cleanup (`app.on_unmount` 923–930), streaming block 3-timer cleanup, history cap at 10k lines, completion list shimmer cleanup, `HERMES_DETERMINISTIC` skip in `tool_panel/_completion.py:71`.

---

## 5. Test coverage

130 production files, 294 test files (2.26:1).

### HIGH: untested production files >100 LOC

1. `app.py` (2,545 LOC) — `HermesApp` lifecycle, slash-command routing, `call_from_thread` plumbing, reactive propagation. Integration-tested only.
2. `anim_engines.py` (2,091 LOC) — 20+ engines (Dna, RotatingHelix, etc.), `TrailCanvas`, LUT helpers. Only orchestrator covered.
3. `services/tools.py` (1,348 LOC) — `ToolRenderingService`, `ToolCallViewState`, axis watcher API. No `test_services_tools.py`.
4. `overlays/interrupt.py` (1,018 LOC) — interrupt payload, countdown, variant dispatch.
5. `widgets/status_bar.py` (967 LOC) — `StatusBar`, `HintBar`, `AnimatedCounter`, `VoiceStatusBar`, `ImageBar`, `SourcesBar`. Tests scattered across `test_bar_snr_p0.py` / `test_status_widgets.py`, no consolidated file.

### MED: skipped / xfail / skipif

- `test_session_widgets.py` — 7 `@pytest.mark.skip` ("folded into InterruptOverlay"). Migrate or delete.
- `test_css_var_single_source.py::test_t2_all_defaults_declared_post_phase4` — `xfail`, blocks RX3 Phase 4 close-out.
- `test_sixel.py` (9), `test_emoji_registry.py` (4) — `skipif` PIL missing. Mark optional in CI config so CI failure surfaces dep loss.
- `test_mouse_ux.py` (2) — `skipif` Linux/X11.

### LOW

`assert True` lint-only sanity checks in `test_services_wiring.py`, `test_io_boundary.py`, `test_session_manager_hardening.py`, `test_response_flow.py`. Acceptable.

---

## 6. CSS / Skin / Theming

### HIGH

- **T1.** `hermes.tcss:755` — `ToolPanel.category-mcp.tool-panel--accent { border-left: vkey #9b59b6 80%; }`. Hardcoded hex. Replace with `$tool-mcp-accent` (already in `COMPONENT_VAR_DEFAULTS`).
- **T2.** `completion_list.py:398` — `Style(dim=True, color="#888888")` for path-suffix hint. Bypasses skin layer. Use `text-muted` via `get_css_variables()` lookup or `SkinColors` pattern from `_grammar.py`.
- **T3.** `tools_overlay.py:216` — `row.stylize("bold on #333399", 0, len(row))`. Add `overlay-selection-bg` to `COMPONENT_VAR_DEFAULTS`.
- **T4.** Bundled skins (`catppuccin.yaml`, `matrix.yaml`, `solarized-dark.yaml`, `tokyo-night.yaml`) all missing `tool-header-max-gap` (added with VN-2 spec 2026-04-25). Run `python -m hermes_cli.tui.build_skin_vars --fill-skin <path>`.

### MED

- **T5.** `streaming_microcopy.py:46–47` — `ACCENT = "#00ff99"`, `DIM = "#446644"` hardcoded for thinking shimmer. Either pull from CSS vars or add explicit `thinking-shimmer-accent` / `thinking-shimmer-dim`.
- **T6.** `body_renderers/_grammar.py:94–104` — `SkinColors.default()` fallback hexes don't match `COMPONENT_VAR_DEFAULTS` exactly (`accent="#0178D4"` vs `"primary"`, `success="#4CAF50"` vs Textual `$success`). Audit all 9 fallbacks.
- **T7.** 21 component vars declared in `COMPONENT_VAR_DEFAULTS` but never read by any renderer (`chevron-completion`, `chevron-locked`, `chevron-rev-search`, `cite-chip-bg`, `cite-chip-fg`, `error-auth/critical/network/timeout`, `footnote-ref-color`, `info`, `nameplate-decrypt-color`, `pane-border`, `pane-border-focused`, `pane-divider`, `pane-title-fg`, `rule-accent-dim-color`, `running-indicator-hi-color`, `status-context-color`, `tool-glyph-mcp`, `tool-mcp-accent`). Either wire up or drop.

### LOW

- **T8.** `tool_panel/_actions.py:304–306` — `bg_hex = self.app.get_css_variables().get("base", "#1e1e2e")`. Key `"base"` does not exist in palette; should be `"app-bg"` or `"background"`. Always uses fallback.
- **T9.** `hermes.tcss` references 16 Textual built-ins (`$primary`, `$accent`, `$error`, `$success`, `$warning`, `$text`, `$text-muted`, …). Add a comment block at the top so maintainers don't think they need to declare them.

---

## 7. Threading / async

### HIGH

- **X1.** `tools_overlay.py:417,521,531` — `asyncio.ensure_future(self._rebuild())` / `asyncio.ensure_future(self._apply_filter())` from event-loop callbacks (`_refresh`, `on_button_pressed`). No reference held → task can be GC'd mid-run.
  **Fix:** `asyncio.create_task(...)` (Textual 8.x retains ref) or store on `self._pending_task`.
- **X2.** `media_player.py:226,231` — `MpvPoller._run()` daemon thread directly invokes `self._on_tick(pos, dur)` and `self._on_end()` without `call_from_thread`. Callbacks likely mutate `InlineImageBar` widget state.
  **Fix:** wrap callbacks at registration: `self._on_tick = lambda p, d: app.call_from_thread(user_cb, p, d)`.

### MED

- **X3.** `session_manager.py:274–299` — `_NotifyListener._handle()` (worker thread) calls `self._on_event(json.loads(line))` without marshalling. Currently safe because the registered `_on_session_notify_event` (`services/sessions.py:202`) does its own `call_from_thread`, but the contract is implicit. Add type hint and docstring.
- **X4.** `services/io.py:127,173` — `app._event_loop.call_soon_threadsafe(app._output_queue.put_nowait, text)`. Correct because `put_nowait` is sync, but a future async refactor would silently break. Add comment + use `run_coroutine_threadsafe` if it ever becomes async.

### Verified-good

- `session_manager.py:226,241,254,267` — `with self._lock:` socket guarding ✓
- `services/sessions.py:216–450` — all 9 `@work(thread=True)` use `call_from_thread` ✓
- `widgets/inline_media.py:127–135` — TGP encode off-thread, `call_from_thread` apply ✓
- `theme_manager.py:540–573` — filesystem poll → `call_from_thread(_apply_hot_reload_payload)` ✓
- `kitty_graphics.py` — `_id_lock` serialises ID allocation ✓

---

## Recommended order

1. **Mechanical sweep (1–2 days)** — exception handling §2, dead code §3 (D1–D3), perf §4 (P1–P4), CSS §6 (T1–T4), threading §7 (X1–X2). All low-risk, high-volume fixes.
2. **Architectural Phase 1 (1 week)** — A1 god-object split: extract `BrowseState`/`StatusBar`/`CompactionState`/`SessionState`; cap `app.py` <800 LOC.
3. **Architectural Phase 2 (3–5 days)** — A2 watchers antipattern (inline `watch_*` or `ReactiveWatchBinder`).
4. **Architectural Phase 3 (3–5 days)** — A3 `ToolStateService` + explicit session→tool cleanup contract.
5. **Test backfill (parallel)** — `test_services_tools.py`, consolidated `test_status_bar.py`, anim engine unit tests.
6. **Polish** — A4–A9, T5–T9, P3–P4, RX3 Phase 4 close-out (`xfail` test).

---

## Out-of-scope / not audited

- Documentation accuracy
- Accessibility (screen reader, contrast ratios beyond skin defaults)
- I18N
- Binary dependencies (mpv, sixel, kitty graphics) runtime behavior
- `HERMES_DETERMINISTIC` correctness in CI (only spot-checked)
