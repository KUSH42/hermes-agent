# Hermes TUI — Deep Audit Report

**Date:** 2026-05-02
**Branch:** `feat/textual-migration`
**Working dir:** `/home/xush/.hermes/hermes-agent`
**Method:** Four parallel Opus audit agents, each scoped to a TUI surface. Aggregated and ranked.

## Concept docs in scope

The TUI has **multiple concept docs**, not just `docs/concept.md`. Audits referenced:

| Doc | Surface | Status |
|---|---|---|
| `docs/concept.md` | Tool block subsystem (PHASE × KIND × DENSITY) | **FROZEN at v3.6 through 2026-05-11.** Bug-fix edits + changelog entries only. New clauses rejected. |
| `docs/composer-concept.md` | Composer (MODE × KIND × ASSIST) | Active, no freeze. The composer audit below referenced its frame but did not deep-read this file — re-audit recommended. |
| `docs/project_output_pane_spec.md` | Output pane | Out of this audit's scope. |
| `docs/spec_thinking_chroma_gradient.md` | ThinkingWidget | Out of this audit's scope. |
| `docs/project_skin_palette_spec.md` | Skin/theme | Touched indirectly via app-shell audit. |

**Audit scope coverage:**
- Tool block subsystem (vs. `concept.md` v3.6)
- Composer / input / overlays / completion (vs. `composer-concept.md` Spec G + Focus/Nav Spec H — *partial; composer-concept.md not deep-read*)
- Streaming pipeline + animation/rendering (no single concept doc; uses memory entries SR-1..SR-8, SF-1..SF-4, SK-1/SK-2)
- App shell + services + skin/theme (vs. DESIGN.md SkinPayload + project-wide exception rules)

---

## Convergence verdict (tool block subsystem only)

Against the four-criterion definition of done in `.claude/CLAUDE.md`:

1. **Invariant gates green.** ✅ PASSING. `tests/tui/test_invariants.py` IL-1..IL-9 pass (26 tests, ~2.78s).
2. **Concept doc unchanged.** ✅ Holding (freeze in force; no version bump pending).
3. **Targeted tests green per PR.** Cannot verify from a single audit; presumed green.
4. **Audit produces ≤3 MED, 0 HIGH.** ❌ **FAILING.** This audit produced 6 HIGH + 11 MED + 5 LOW against the frozen v3.6 contract.

**Net:** subsystem **not converged**. Primary blockers: renderer-dispatch failure-mode contract (CD-2/CD-3), dead axis-bus violator (CD-1/DEAD-1), broken `_auto_renderer_kind` (CD-4). All fixable as bug-fix-class edits under the freeze.

---

## Cross-cutting architectural smells (all 4 audits)

These are root-cause patterns where >1 finding traces to the same defect class. Fix these and ~30% of the punch list collapses.

1. **`@work` workers without top-level try/except.** Project rule: thread/async workers must wrap their body in try/except + `_log.exception(...)`. Multiple violators across surfaces:
   - `services/io.py::consume_output` (HIGH)
   - `app.py::_start_bash_worker` (HIGH)
   - `app.py::_run_git_poll` (HIGH)
   - `response_flow.py::_render_worker` (math, MED)
   - `character_pacer.py::_tick` (MED)
   - `drawbraille_overlay.py::_tick` (MED)
   - `services/tools.py::_classify_with_timeout` worker pool (MED, leaks threads)

   **Recommendation:** add an IL-style invariant test that scans `@work(thread=True)` decorated bodies for the wrapper.

2. **`get_css_variables()` failures swallowed silently.** Skin hot-swap stuck on stale colors with no diagnostic — exactly the failure class IL-1..IL-8 was designed to prevent for tools, but the skin contract surface has no equivalent gate. Sites:
   - `widgets/__init__.py::AssistantNameplate` × 4 (HIGH)
   - `widgets/status_bar.py::HintBar._get_key_color` (MED)
   - `services/theme.py` × 2 (HIGH/MED)
   - `services/theme.py::populate_slash_commands` (HIGH — different call but same swallow pattern)

   **Recommendation:** lint gate that requires every `get_css_variables()` call site to log on exception.

3. **No central modal/focus arbiter.** Every overlay individually adds/removes `--modal`, owns its own Esc binding with `priority=True`, and writes its own focus restore. Implemented inconsistently:
   - `HelpOverlay`/`UsageOverlay` drop only `--visible`, not `--modal` (MED)
   - `SkillPickerOverlay` can stack against `InterruptOverlay` simultaneously (HIGH H3)
   - `ToolsScreen` narrow-resize exit path skips `--modal` cleanup (HIGH H6)
   - `ContextMenu.show` empty-items path leaks stale `--modal` (MED M12)

   **Recommendation:** `_modal_stack` on `HermesApp` plus a `ModalOverlayBase` mixin centralizing class toggles, Esc binding, focus return.

4. **ASSIST state spread across three independent reactives.** Composer concept G mandates `_resolve_assist` as the single write site, but readers consult three sources: the Python flag `_completion_overlay_active`, the `--visible` CSS class on `CompletionOverlay`, and an implicit DOM probe for `SkillPickerOverlay`. AutoDismiss flips one but not the others. Symptoms: H1, H2, M9, M11.

   **Recommendation:** a reactive `assist: AssistKind` on `HermesInput` with watchers driving every consumer (mode, chevron, placeholder, `--visible`).

5. **Module-level mutable state in animation hot paths.** `_LAYER_ROW_BUF`, `_LAYER_RESULT_BUF`, `_RGB_CACHE`, `_SINE_TABLES` plus orchestrator `_external_trail` setattrs. Comment claims single-threaded; nested `CompositeEngine` reentrancy violates it (HIGH `ANIM-LAYER-REENTRANCY`). Future async or test-parallelism breaks invisibly.

6. **`app.py` is doing service plumbing AND mixin-forwarding.** 2815 lines, thin pass-through methods routing to `self._svc_*`. Seven `@work` decorators living on `app.py` because `@work` needs an App `self`. New service = edit two files.

7. **Inconsistent `except` discipline despite project rule.** EH-A..EH-E sweep annotated ~377 sites in memory, but new code keeps adding bare `except Exception: pass` (drawbraille_overlay.py:901, services/theme.py:204). The rule is not enforced by a gate.

   **Recommendation:** invariant test that rejects new `except Exception:\n    pass` without an inline `# allow-` exemption marker.

---

## Findings — Tool block subsystem (vs. concept.md v3.6)

### HIGH

```
[HIGH] CD-1 — ToolCallHeader bypasses set_axis on PHASE write
  Where: hermes_cli/tui/tool_blocks/_header.py:1065
  Concept: §Concurrency invariants ("set_axis is the choke-point that publishes new state to subscribers"); §PHASE transition model
  Problem: ToolCallHeader.set_state writes self._view.state = new_state directly, bypassing set_axis, _set_view_state, AND PlanSyncBroker. Watchers and the broker would not fire.
  Fix: Delete ToolCallHeader (it is dead — never imported/instantiated/exported from tool_blocks/__init__.py) OR route through set_axis(view, "state", new_state). Recommend deletion.
```

```
[HIGH] CD-2 — _swap_renderer keeps original body on render failure (no FallbackRenderer)
  Where: hermes_cli/tui/tool_panel/_completion.py:244-248
  Concept: §Renderer dispatch / Failure modes ("Renderer raises during render() → fallback to RawTextRenderer")
  Problem: When build_widget() raises, exception is logged but swap is abandoned. Concept requires fallback to FallbackRenderer/RawTextRenderer; user sees stale streaming body for a classified failure.
  Fix: On Exception, mount FallbackRenderer(payload, ClassificationResult(kind=TEXT, confidence=0.0)).build_widget() and tag block so future density changes use the same fallback.
```

```
[HIGH] CD-3 — Slow-renderer 250ms soft-deadline contract not enforced
  Where: hermes_cli/tui/tool_panel/_footer.py:267-293 (_mount_body_with_deadline)
  Concept: §dispatch failure-modes (placeholder + worker + swap path)
  Problem: Renderer runs synchronously on event loop; only post-hoc warning when elapsed > _SLOW_DEADLINE_S. The placeholder + worker + swap path (_start_slow_render / _render_in_worker) exists but is never invoked. A 600ms renderer freezes the event loop on first paint — exactly what the contract is meant to prevent.
  Fix: Probe wall-clock before first build. If renderer is tagged "slow" from prior session OR first build crosses 250ms with yield-point, route to _start_slow_render. Persist the slow tag on renderer instance/class.
```

```
[HIGH] CD-4 — _auto_renderer_kind reads non-existent attribute, always returns PLAIN
  Where: hermes_cli/tui/tool_blocks/_streaming.py:907-927
  Concept: §user authority on KIND, §kind-revert semantics
  Problem: getattr(self, "_view", None) reads "_view" on StreamingToolBlock — but no such attribute exists. Canonical view-state lives on the panel as _view_state. Wrapping try/except logs at debug only; function silently returns PLAIN for every call. Effect: action_kind_revert always flashes "kind: auto (plain)" regardless of classifier verdict — lying to the user.
  Fix: Resolve via getattr(self, "_tool_panel", None) then panel._view_state, OR thread view-state through ToolPanel and read view.kind. Also: line 917 passes view.args (a dict) where ToolPayload is expected.
```

```
[HIGH] CD-5 — Block-level `c` copy key contract diverges from concept
  Where: hermes_cli/tui/tool_panel/_core.py:171 + _actions.py:916,1140 (hint label "y copy")
  Concept: §Block-level key contract ("c | copy block content (kind-aware)")
  Problem: Concept binds `c`; implementation binds `y`. Microcopy says [y]copy but canonical mocks/perception-budgets/key-contract table all use [c]opy.
  Fix: Bug-fix edit allowed under freeze. Recommend rebinding to `c` in _core.py since canonical mocks and key-contract table consistently use c; piecemeal microcopy edits will create more drift.
```

```
[HIGH] IL-GAP-1 — view.user_kind_override write without axis-bus equivalent uncovered by IL-7/8
  Where: hermes_cli/tui/tool_panel/_actions.py:1172,1315
  Concept: §user overrides
  Problem: user_kind_override is a direct field write (not on AxisName). IL-7 only checks set_axis ordering for streaming_kind_hint vs state — does not check that user_kind_override changes pair with a header refresh. A direct write here doesn't fire watchers, so the "as <kind>" caption can lag.
  Fix: Promote user_kind_override into AxisName so set_axis fires watchers, OR keep direct write but require force_renderer to refresh header explicitly.
```

### MED

```
[MED] DEAD-1 — ToolCallHeader is unused (102 LOC at _header.py:1013-1114)
[MED] EH-1 — action_edit_cmd swallows Exception with user-visible flash, no log (_actions.py:490)
[MED] EH-2 — action_copy_ansi/_html misleading "falls back to action_copy_body" comment (_actions.py:580-585, 608-614)
[MED] CD-6 — Hint-priority order: e/o/u/E come before t (toggle-kind), reversing canonical KIND-bucket order (_actions.py:919-958)
[MED] CD-7 — Streaming hint sniff buffer never bounded; lstrip on multi-MB whitespace is O(n) (services/tools.py:1517-1525)
[MED] CD-8 — _classify_with_timeout leaks worker threads on TimeoutError (services/tools.py:35-48)
[MED] CD-9 — `T` revert duplicates streaming_kind_hint clear (idempotent, but invites SK-2 break) (_actions.py:1311-1316)
[MED] CD-10 — _set_view_state recursion under RLock not guarded (services/tools.py:284-300)
[MED] CD-11 — _view_state lookup races with ToolPanel mount in apply_layout (_core.py:398-407)
[MED] PERF-1 — pick_renderer streaming branch O(n) over REGISTRY per chunk; cache category→renderer map (body_renderers/__init__.py:149-156)
```

### LOW

```
[LOW] LOW-1 — _SKELETON_PULSE_S env var swallows ValueError without doc tying to motion-cadence (_streaming.py:54-64)
[LOW] LOW-2 — BodyRenderer.summary_line() ignores cls_result kwarg (body_renderers/base.py:103-111)
[LOW] LOW-3 — _ks_context() reads vs.density.value unguarded; AttributeError on early mount (_core.py:472-482)
[LOW] LOW-4 — _register_header_hint_watcher swallows missing attach_stream_axis_watcher at debug-only (services/tools.py:1506-1513)
[LOW] LOW-5 — truncate_hints does not honor the 14-char microcopy cap on rendered chips (_actions.py:965-990)
```

---

## Findings — Composer / input / overlays / completion

> Caveat: this audit referenced Spec G + H by frame but did not deep-read `docs/composer-concept.md`. Re-audit recommended once that doc is in scope.

### HIGH

```
[HIGH] H1 — _resolve_assist OVERLAY→PICKER doesn't tear down path-debounce timer
  Where: hermes_cli/tui/input/widget.py:282-333
  Spec: G (ASSIST single-write-site)
  Problem: PICKER branch hides completion overlay but does not stop _path_debounce_timer (only _hide_completion_overlay does). Stale path-search timer can post-mount items into a now-stale overlay after PICKER opened.
  Fix: PICKER branch must call self._hide_completion_overlay().
```

```
[HIGH] H2 — _completion_overlay_active flag desyncs vs CompletionOverlay --visible class
  Where: completion_overlay.py:180 (AutoDismiss handler) + input/_path_completion.py:74
  Spec: G (single source of truth for ASSIST)
  Problem: VirtualCompletionList AutoDismiss removes --visible on overlay but doesn't clear HermesInput._completion_overlay_active. _compute_mode keeps returning COMPLETION → composer wedged.
  Fix: AutoDismiss must post a message that triggers _hide_completion_overlay (or clear flag directly).
```

```
[HIGH] H3 — SkillPicker doesn't queue against InterruptOverlay; both can be --modal
  Where: overlays/skill_picker.py:142 + interrupt.py:345
  Spec: H (W-* modal focus discipline)
  Problem: Two overlays simultaneously hold --modal; both bind Esc priority=True; key dispatch order undefined. No global modal-stack arbiter.
  Fix: Centralize _modal_stack on app; defer/refuse open if another --modal is up.
```

```
[HIGH] H4 — VirtualCompletionList absorbs Input.Submitted via skill_picker overlap
  Where: overlays/skill_picker.py:298 (on_key)
  Spec: G/H
  Problem: Picker hosts an Input ("picker-filter"); SkillPickerOverlay.on_key handles Enter via event.stop() + _dispatch_selected before Input emits Submitted. Enter inside filter input dispatches highlighted skill — surprising.
  Fix: Skip Enter when self.app.focused has id "picker-filter"; or wire on_input_submitted.
```

```
[HIGH] H5 — middle-click paste bypasses disabled gate and skips sanitize
  Where: input/widget.py:198-217 (on_click)
  Spec: H
  Problem: safe_run callback only checks is_mounted; if input was disabled (running…) while paste subprocess was running, output is inserted anyway. Also no _sanitize_input_text on pasted text.
  Fix: Gate on `not self.disabled`; route through self.insert_text() (sanitizes) instead of self.insert().
```

```
[HIGH] H6 — ToolsScreen leaves --modal class set on narrow-resize pop_screen
  Where: tools_overlay.py:440 (on_resize narrow path) + AT-* invariants
  Spec: H
  Problem: --modal added in on_mount, removed only on cooperative dismiss paths. on_resize narrow-terminal calls pop_screen without removing --modal, breaking AT-* invariants on screen reuse.
  Fix: Override on_pause/on_screen_suspend to remove --modal, OR remove --modal in narrow on_resize before pop_screen.
```

### MED

```
[MED] M1 — tools_overlay action_jump_to_panel: bare Exception swallow no log (tools_overlay.py:741)
[MED] M2 — UsageOverlay _do_copy fallback: bare swallow no comment (overlays/reference.py:412)
[MED] M3 — HelpOverlay/UsageOverlay action_dismiss removes only --visible, leaving --modal stale (overlays/reference.py:196,480)
[MED] M4 — InterruptOverlay action_drain_queue doesn't restore focus to HermesInput (overlays/interrupt.py:907-916)
[MED] M5 — OSC52 _MAX_RAW_BYTES truncation can split UTF-8 mid-codepoint (osc52.py:39)
[MED] M6 — _show_path_completions: searching=True set after _push_to_list([]); 1-frame "no results" race (input/_path_completion.py:188-199)
[MED] M7 — SkillPickerOverlay._dispatch_selected mutates inp.value without save_draft_stash; lost draft + silent no-op when disabled (skill_picker.py:320-334)
[MED] M8 — InterruptOverlay countdown danger-class not removed on hide_if_kind path (interrupt.py:464-466)
[MED] M9 — completion_list watch_items: --slash-only class persists when items collapse to 0 (completion_list.py:335-359)
[MED] M10 — fuzzy_rank empty-query allocates full list before slice (fuzzy.py:39-44)
[MED] M11 — _compute_mode has no PICKER branch; chevron/legend lie about state during SkillPicker (input/widget.py:776-786)
[MED] M12 — ContextMenu.show empty-items doesn't clear stale --modal (context_menu.py:213-214)
```

### LOW

```
[LOW] L1 — InterruptOverlay child.remove swallow comments uneven (interrupt.py:418-419, 538-539)
[LOW] L2 — drawbraille_overlay.py:901 has bare Exception:pass without comment
[LOW] L3 — VirtualCompletionList virtual_size uses len() not cell_len() — emoji/CJK undersize (completion_list.py:343)
[LOW] L5 — fuzzy.py contiguous-only matcher rejects camelCase initials (fuzzy.py:50-53)
[LOW] L6 — _push_to_list short-circuit equality misses score-only changes (_path_completion.py:240-241)
[LOW] L7 — SkillPickerOverlay shows "no skills installed" briefly before lazy populate (skill_picker.py:164-177)
```

---

## Findings — Streaming pipeline + animation/rendering

### HIGH

```
[HIGH] STREAM-FENCE-LEAK — Fence timer not reset in _handle_unknown_state
  Where: response_flow.py:911-913
  Problem: Resets _state/_active_block but only conditionally clears _fence_opened_at. Reached while IN_CODE → next [STREAM-FENCE] log can compute stale elapsed_ms.
  Fix: Unconditional self._fence_opened_at = None at top of _handle_unknown_state.
```

```
[HIGH] STREAM-PARTIAL-DETACH — feed() bypasses _detached check on _route_partial corner
  Where: response_flow.py:701-711
  Problem: _route_partial(active_block.feed_partial) can race if panel unmounts between feed() entry and dispatch. Crash risk: feed_partial on unmounted StreamingCodeBlock during teardown.
  Fix: In _route_partial, check is_mounted on _active_block, or wrap in try/log.
```

```
[HIGH] ANIM-LAYER-REENTRANCY — Module-level _LAYER_ROW_BUF/_RESULT_BUF non-reentrant
  Where: anim_engines.py:178-225
  Problem: Module-level lists mutated in place; comment says single-threaded, but CrossfadeEngine + nested CompositeEngine paths layer twice in same frame. Nested _layer_frames calls clobber outer state → scrambled frames.
  Fix: Per-call locals, OR assert non-reentrancy and document.
```

```
[HIGH] PACER-TIMER-LIFECYCLE — Bare except: pass on timer.stop in CharacterPacer
  Where: character_pacer.py:73-77
  Problem: except Exception: pass swallows stop failures; only inline comment differentiates safe Textual case from real bugs (AttributeError on None handle).
  Fix: Narrow to (RuntimeError, AttributeError) with _log.debug(exc_info=True).
```

```
[HIGH] OVERLAY-CTOR-WATCH-SWALLOW — watch_color/color_b/multi_color silently swallow
  Where: drawbraille_overlay.py:612-631
  Problem: Three reactive watchers try/except Exception: pass with comment only. _resolve_color failure on real bad input → stale color forever, no log.
  Fix: Replace pass with _log.debug("watch_color resolve failed for %r", value, exc_info=True).
```

```
[HIGH] OVERLAY-NAMEPLATE-SWALLOW — _has_nameplate hides app errors (drawbraille_overlay.py:899-902)
[HIGH] TTE-CACHE-LOAD-SWALLOW — load_tte_frames swallows OSError silently (_tte_cache.py:106-114)
```

### MED

```
[MED] STREAM-FOOTNOTE-CAP — _footnote_def_open not updated past cap; continuations misrouted (response_flow.py:744-746)
[MED] STREAM-PARTIAL-CSI-LOSS — Orphaned CSI removal silently drops content; no log (response_flow.py:709-711)
[MED] STREAM-MATH-WORKER — _flush_math_block run_worker has no try/except; renderer crash invisible (response_flow.py:1379-1391)
[MED] STREAM-FENCE-FLUSH-CODE — flush() can leave _fence_opened_at set via IN_INDENTED_CODE branch (response_flow.py:1254-1258)
[MED] STREAM-REASONING-RACE — ReasoningFlowEngine._init_fields: get_css_variables() not wrapped (response_flow.py:1591-1617)
[MED] ANIM-CLOCK-TICK-SWALLOW — AnimationClock subscriber callback unbounded; one buggy subscriber kills 15Hz bus (animation.py:213-218)
[MED] ANIM-EXTERNAL-TRAIL-SCALES — apply_external_trail O(rows×cols×8); 80×24×8 set() calls/frame (anim_orchestrator.py:438-450)
[MED] ANIM-TICK-RENDER-NOLOG — _tick wraps engine.next_frame in measure() but no try/except; bad state crashes recurring tick (drawbraille_overlay.py:1048-1050)
[MED] CONTENT-CLASSIFY-NO-TIMEOUT — classify_content has no 50ms enforcement; lru_cache pins large strings (content_classifier.py:39-140)
[MED] PARTIAL-JSON-UNICODE-RECOVERY — Bad \uXXXX silently emits literal hex; no log (partial_json.py:130-133)
[MED] PACER-TICK-NO-EXC — _tick on_reveal exception propagates to set_interval; timer dies silently (character_pacer.py:84-122)
[MED] STARTUP-BANNER-RACE — STARTUP_BANNER_READY single set/clear racy across worker boundary (widgets/__init__.py:854-860 + cli.py:4787)
[MED] THEME-REFRESH-EXCEPT-TUPLE — except (NoMatches, Exception): pass; redundant + silent (services/theme.py:204-205)
```

### LOW

```
[LOW] PERF-RGB-CACHE-CAP — _RGB_CACHE first-256-wins, not LRU; silent perf cliff (animation.py:99-110)
[LOW] STREAM-CITE-STATE — Citations dropped past _MAX_CITATIONS; no UI signal (response_flow.py:755-760)
[LOW] PROSE-DOUBLE-EMIT-DEBUG — DOUBLE-EMIT debug spam on legit blank-line repeats (response_flow.py:667-672)
[LOW] CACHE-INVALIDATE-FOR-RESIZE — invalidate_for_resize partial-mutation if _cell_px raises (inline_prose.py:171-180)
[LOW] EXEC-CURSOR-TIMER-SWALLOW — finalize_code: pacer.flush() unwrapped; OutputSection may not reveal (execute_code_block.py:329-339)
```

### Test-coverage gaps

- `tests/tui/test_anim_overlay.py` — orchestrator `_layer_frames` reentrancy, `_tick` exception fallback, `apply_external_trail` perf budget.
- `tests/tui/test_response_flow*.py` — `_handle_unknown_state` recovery, fence-timer non-IN_CODE leak, footnote-cap-with-continuation.
- `tests/tui/test_partial_json.py` — bad `\uXXXX` recovery branch.
- `tests/tui/test_character_pacer.py` — burst-guard, on_reveal-raises.
- `tests/tui/test_tte_cache.py` — load OSError, corrupt-pickle, format-version mismatch.

---

## Findings — App shell + services + skin/theme

### HIGH

```
[HIGH] APP-H1 — _consume_output worker has no top-level try/except
  Where: services/io.py:50 (consume_output, async @work loop)
  Problem: while True: body has no outer try/except. Any uncaught exception kills the streaming worker silently — output stops forever, no log.
  Fix: Wrap loop body in try/except (SystemExit/KeyboardInterrupt re-raise; Exception → logger.exception + continue).

[HIGH] APP-H2 — Silent swallow in flush sentinel branch hides UI desync (services/io.py:75-80)
[HIGH] APP-H3 — _start_bash_worker has no try/except; BashService._running can stick at True forever (app.py:1056-1061)
[HIGH] APP-H4 — _run_git_poll worker leaks _git_poll_in_flight=True on exception (app.py:1129-1138)
[HIGH] SVC-H1 — populate_slash_commands swallows all errors silently (services/theme.py:259-260)
[HIGH] SVC-H2 — io.play_effects_blocking returns False without log (services/io.py:240-243)
[HIGH] SKIN-H1 — Nameplate get_css_variables() bare swallows (×4 sites in widgets/__init__.py:1029-1077)
```

### MED

```
[MED] APP-M1 — on_mount pane-state restore swallows without log (app.py:879-893)
[MED] APP-M2 — on_unmount cleanup swallows × 5 sites (app.py:1009-1052)
[MED] APP-M3 — _resolve_reduced_motion: function-local `import os` × 5 sites (app.py:644 et al)
[MED] APP-M4 — Auto-compact watcher duplicates resize logic; race at first paint (app.py:833-839 + 964-967)
[MED] SVC-M1 — _NotifyListener thread not stopped on app on_unmount (services/sessions.py:83-88)
[MED] SVC-M2 — sessions.switch_to_session: cleanup-order leaks listener if execvp fails (sessions.py:191-220)
[MED] SVC-M3 — bash_service.kill swallows OSError without log (bash_service.py:54-55)
[MED] SKIN-M1 — _resolve_reduced_motion does file I/O on event loop per call (app.py:643-655)
[MED] SKIN-M2 — ThemeManager.css_variables shallow-copy contract fragile against future nested values (theme_manager.py:780-787)
[MED] STAT-M1 — HintBar.on_unmount doesn't stop _flash_timer; can fire on detached widget (status_bar.py:337-338)
[MED] STAT-M2 — HintBar._get_key_color get_css_variables swallow no log (status_bar.py:283-288)
[MED] CONST-M1 — refresh_known_skills: clear() then update() not atomic; concurrent reader sees empty (_app_constants.py:46-52)
[MED] APP-M5 — sessions create_new_session leaks orphan headless Popen on poll timeout (sessions.py:268-289)
```

### LOW

```
[LOW] APP-L1 — Mixed top-level vs in-function overlay imports (app.py:108-110, on_mount)
[LOW] APP-L2 — on_resize: event.size attribute access duplicated (app.py:957-961)
[LOW] SKIN-L1 — _builtin_skin_to_css silently drops keys when _hex returns None (theme_manager.py:391-470)
[LOW] HEADLESS-L1 — OutputJSONLWriter rewrites whole file on every write() — O(N) per chunk (headless_session.py:35-40)
[LOW] SVC-L1 — sessions polling fires every 2s regardless of overlay visibility (sessions.py:89)
[LOW] STAT-L1 — _refresh_runtime_skin_consumers iterates all ToolBlocks/MessagePanels on event loop; can stall on hot-swap (services/theme.py:88-117)
```

---

## Recommended remediation order

Fix in roughly this sequence — earlier items unlock later ones or close finding clusters:

1. **`@work` exception wrapper sweep** (APP-H1..H4, HIGH-tier streaming/anim worker bugs). One pattern, ~7 sites, closes a smell category.
2. **`get_css_variables()` log-on-fail sweep** (SKIN-H1, M2 + others). Add a lint gate.
3. **Tool block CD-1..CD-5** (delete dead `ToolCallHeader`, fix `_auto_renderer_kind` non-attribute read, wire `FallbackRenderer` + slow-renderer worker dispatch, reconcile `c` vs `y` copy binding). All bug-fix-class under freeze. Closes convergence criterion (4).
4. **`STREAM-FENCE-LEAK` + `STREAM-PARTIAL-DETACH`** — small targeted fixes, eliminate two real crash/desync paths.
5. **Modal arbiter introduction** (`_modal_stack` + `ModalOverlayBase`). Closes H3, H6, M3, M4, M12 in one refactor.
6. **`ASSIST` reactive consolidation** on `HermesInput`. Closes H1, H2, M9, M11.
7. **Animation reentrancy fix** (`ANIM-LAYER-REENTRANCY`) — per-call locals or assert.
8. **Tool-block MEDs** (DEAD-1, EH-1, CD-6..CD-11, PERF-1).
9. **Long-tail LOWs and test-coverage gaps.**

---

## Counts

| Surface | HIGH | MED | LOW | Total |
|---|---|---|---|---|
| Tool blocks | 6 | 11 | 5 | 22 |
| Composer/input/overlays | 6 | 12 | 6 | 24 |
| Streaming/animation | 7 | 13 | 5 | 25 |
| App/services/skin | 7 | 13 | 6 | 26 |
| **TOTAL** | **26** | **49** | **22** | **97** |

---

## Open questions / re-audit candidates

- **`docs/composer-concept.md`** was not deep-read by the composer audit agent. A targeted second pass against that doc may surface MODE×KIND×ASSIST drift not visible from frame inference alone.
- **`docs/project_output_pane_spec.md`** and **`docs/spec_thinking_chroma_gradient.md`** were out of scope. Worth a focused audit if those surfaces have changed.
- **DESIGN.md SkinPayload contract** — ThemeManager.css_variables (SKIN-M2) hints the contract surface deserves its own audit.
- The **StartupBannerWidget** living inside `widgets/__init__.py` (rather than its own module) was a surprise during the streaming audit — worth extracting and adding standalone tests around the `STARTUP_BANNER_READY` race (MED).
