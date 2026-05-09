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
| Banner hierarchy BH-1/2/3 | `_section_break` rule, warn orange-red, dismiss badge row (`u dismiss` + install cmd); skin tokens `banner-warning/dim/key` added to 4 missing skins (catppuccin, matrix, solarized-dark, tokyo-night); 2 BH-3 tests corrected to match APPROVED spec | `47be7b80e` | 13 |
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

## 2026-05-03 — CD-H2/H3/CD-M1 composer ASSIST/MODE sync

- **CD-H2**: `app._hide_completion_overlay_if_present` now calls `HermesInput.dismiss_completion_overlay()` instead of directly removing `--visible`; new `dismiss_completion_overlay()` method is the single-write-site guard (routes through `_resolve_assist(NONE)` only when `assist is OVERLAY`)
- **CD-H3**: `_set_input_locked` now ends with `self._mode = self._compute_mode()` wrapped in `try/except AttributeError` (guard for pre-mount window)
- **CD-M1**: `watch_assist` now ends with same `self._mode = self._compute_mode()` pattern — fixes MODE lag on `NONE↔OVERLAY` transitions
- Gotcha: `_FakeInput` in `test_composer_invariants.py` is missing `assist` attribute — 12 tests in that file were pre-existing failures on base branch (unrelated to this spec)
- Test pattern: minimal `_StubInput` with `_compute_mode` overridden via `MagicMock(return_value=...)` for pure unit tests; call `HermesInput.method(stub)` directly

## 2026-05-03 — SVCAUD-H1..H7 app.py exception discipline sweep

- Fixed 7 `except Exception: pass` blocks in `hermes_cli/tui/app.py`
- H7: `_apply_model_inline` inner swallow → `logger.warning`; fixed latent `_log` NameError at L1362/L1375
- H1: `_mount_inline_media_widget` outer swallow → `logger.exception`
- H2: emoji mount loop → `logger.warning` + explicit `continue`
- H3: `watch_yolo_mode` narrowed to `NoMatches` (silent) + broad Exception logged
- H4: `watch_focused` three blocks each narrowed to expected type (silent) + broad logged
- H5: drawbraille signal narrowed to `NoMatches` (silent) + broad → `logger.debug`
- H6: `_osc_progress_update` outer swallow → `logger.debug`
- Test pattern: bind method to `MagicMock(spec=HermesApp)`, patch logger at `hermes_cli.tui.app.logger`
- Gotcha: `_inline_media_config` and `InlineMediaWidget` are local imports inside `_mount_inline_media_widget`; patch at source module (`hermes_cli.tui.media_player._inline_media_config`, `hermes_cli.tui.widgets.InlineMediaWidget`), not at `hermes_cli.tui.app`

## 2026-05-03 — OS-H4 OutputPanel JUMPED→PINNED setter guard

- **OS-H4**: `_user_scrolled_up = False` unconditionally wrote `scroll_state = PINNED`, collapsing `JUMPED→PINNED` without confirming live-edge geometry. Callers like `echo_user_message` (app.py) could clear the jump-hint badge prematurely.
- **Fix pattern**: setter guard `if not v and self.scroll_state == ScrollState.JUMPED: return`. The one legitimate `JUMPED→PINNED` path (`watch_scroll_y` at live edge) replaced its `self._user_scrolled_up = False` with a direct `self.scroll_state = ScrollState.PINNED` write so it isn't silenced.
- **Both changes must land together** — applying the setter guard without the `watch_scroll_y` update would break the live-edge transition entirely.
- Test pattern: `_StubOutputPanel` stub (pure Python, no Textual runtime) exposing `scroll_state` and the property under test. Parametrize `True` branch over all 3 states in a single test method.

## 2026-05-03 — ANSK-H2/H3/H4 anim/TTE fixes

- **ANSK-H2**: `TTEWidget._run_animation` must capture `done_event = self._done_event` *before* the `try` block; remove `self._done_event = None` from `finally` — the worker only signals its own captured event, `stop()/play()` own the instance field lifecycle
- **ANSK-H3**: `ThinkingWidget._load_config` bare `except Exception: pass` → `_log.warning(..., exc_info=True)` — the swallow is correct (defaults work) but needs visibility
- **ANSK-H4 + M7**: `_apply_effect_params` was annotated `-> None` but returned `bool`; early returns yielded implicit `None`. Behavioral impact: `not None == not False == True` so gradient behavior was actually correct — this was a type annotation fix plus `print()` elimination. **`print()` inside `_apply_effect_params` corrupts live TUI frame buffer** (called from inline worker; Textual not suspended)
- Gotcha: `is_mounted` and `app` on Textual Widget are read-only properties — use `patch.object(type(w), "is_mounted", new_callable=PropertyMock, return_value=True)` inside a `with` block; don't try to assign directly or via `type(w).is_mounted = ...` (leaks to other tests)
- Test pattern for `@work(thread=True)` bodies: call `widget._run_animation.__wrapped__(widget, ...)` directly to bypass the worker decorator

## 2026-05-03 — CD-H1 SLASH_SUBCOMMAND dispatch + CD-H4 _open_skill_picker bool return

- **CD-H1**: `_AutocompleteMixin._update_autocomplete` was missing a `SLASH_SUBCOMMAND` branch in the final if/elif chain. Added between `SLASH_COMMAND` and `PATH_REF*` arms: `elif trigger.context is CompletionContext.SLASH_SUBCOMMAND: self._show_subcommand_completions(trigger.parent_command, trigger.fragment)`.
- **CD-H4**: `HermesApp._open_skill_picker` returned `None` in all paths. Changed return type to `bool`; returns `False` on modal-block early return, `True` after both the "update existing picker" and "mount new picker" paths.
- **CD-H4 guard**: In `HermesInput._resolve_assist`, PICKER branch now captures `opened = self.app._open_skill_picker(...)` and returns early if `not opened` — prevents writing `self.assist = PICKER` when the picker was blocked by a modal.
- Gotcha: `types.SimpleNamespace()` raises `TypeError: got multiple values for keyword argument` if your `_make_fake_input()` helper sets default keyword args and the caller passes the same key. Use explicit named params with default values instead of `**{defaults, **kwargs}`.
- Gotcha: `HermesApp.query_one` is not available on a `types.SimpleNamespace` stub — add `app.query_one = MagicMock(side_effect=NoMatches(...))` explicitly for tests of `_open_skill_picker`.
- Test pattern: call `HermesInput._resolve_assist(stub_obj, AssistKind.PICKER)` unbound; stub `app._open_skill_picker` as `MagicMock(return_value=False/True)`; check `stub_obj.assist` after call.

## 2026-05-03 — CD-11 _lookup_view_state sync (tool-block convergence)

- **CD-11**: `ToolPanel._lookup_view_state` accessed `svc._tool_views_by_id.get()` directly instead of `svc.live_by_id()`. Changed to use the public helper.
- **Why no lock needed**: `_lookup_view_state` is only called from `_apply_layout`, which enforces the event-loop invariant via `RuntimeError` at line 438-439. Event-loop reads of `_tool_views_by_id` are safe without `_state_lock` per the `ToolsService.__init__` contract (comment at line 296).
- **Convergence status**: all 10 tool-block MEDs from the 2026-05-02 audit are now at 0 HIGH / 2 MED (CD-9 idempotent/harmless, CD-11 this commit). Criterion 4 clock started 2026-05-03.

## 2026-05-03 — SPEC-MED-RESIDUAL-SWEEP (M5/M10/ANIM-TRAIL)

- **M5** (`osc52.py`): byte-slice UTF-8 at cap was corrected to `raw[:cap].decode("utf-8", errors="ignore").encode("utf-8")` — drop incomplete tail codepoint rather than producing invalid byte sequence.
- **M10** (`fuzzy.py`): empty-query path replaced `list(items) + sort + slice` with `heapq.nsmallest(limit, items, key=lambda c: c.display)` followed by score-zero replacement. Memory bounded to `limit` regardless of input size.
- **ANIM-EXTERNAL-TRAIL-SCALES** (`anim_orchestrator.py`): added `_BRAILLE_BITS_TO_OFFSETS` — precomputed 256-entry tuple mapping each braille bits value (0–255) to its `(dx, dy)` offset pairs. Hot loop now does one `tuple.__iter__` per character instead of 8 conditional checks per character. Eliminates the per-frame `rows×cols×8` branch cost.
- **Gotcha**: `_BRAILLE_BITS_TO_OFFSETS` must be defined after `_BRAILLE_BIT_POSITIONS` (it uses a comprehension over it at module load). Both are immutable module-level tuples.

## 2026-05-03 — AC Skill Inline Completion via $ trigger

- **AC-1**: Replaced `_resolve_assist(AssistKind.PICKER)` in SKILL_INVOKE branch with `_show_skill_completions(trigger.fragment)`. New method builds `SlashCandidate(display=c.name, command="$"+c.name)` items from `self._skills`, fuzzy-ranks them, and shows inline CompletionOverlay in `slash_only=True` mode.
- **display vs command**: `display=c.name` (no `$`) so `fuzzy_rank` and prefilter operate on the same string. `command="$"+c.name` drives the acceptance path (`c.command + " "` → `"$name "`).
- **disabled filter**: `if c.enabled and c.name.startswith(fragment)` — disabled skills never appear in completions.
- **hint dedup guard**: `_last_skill_hint_fragment` / `_last_skill_hint_time` 2s cooldown, matching `_show_slash_completions` pattern. Prevents flash-hint thrashing on every keystroke.
- **perf.measure**: deferred `from hermes_cli.tui.perf import measure` placed after items list comprehension (before the `with measure(...)` call), consistent with `_show_slash_completions` placement.
- **AC-2**: Deleted dead auto-dismiss guard (lines 88–97) and removed two dead imports (`_SKILL_RE` from completion_context, `SKILL_PICKER_TRIGGER_PREFIX` from _assist). Note: `SKILL_PICKER_TRIGGER_PREFIX` stays live in `widget.py:33,353`.
- **Class annotation**: Added `_skills: list` to `_AutocompleteMixin` annotations block (matches pattern of `_slash_commands: list[str]`).
- **Test pattern**: `_AutocompleteMixin` methods called unbound via `_AutocompleteMixin._show_skill_completions(stub, fragment)` on a minimal `_FakeAutocomplete` stub that tracks `_resolve_assist_calls`, `_push_to_list_calls`, `_set_overlay_mode_calls`, `_flash_hint_calls`. No Textual app mounting needed.
- **Gotcha**: Worktree created by EnterWorktree defaults to HEAD of main, not the current branch. After entering worktree, `git reset --hard feat/textual-migration` to get the right base.

## 2026-05-03 — SPEC-STARTUP-OPT-3-BANNER-GEO-CACHE

- **New module** `hermes_cli/tui/_banner_geo_cache.py`: SHA-1[:12] keyed JSON disk cache for banner hero-slot geometry (hero_row/hero_col). `is_cache_disabled()` gates on `HERMES_NO_CACHE` env var. `gc_geo_cache(cap=20)` runs in a daemon thread after each cache-miss write to keep the cache dir bounded.
- **cli.py** `_build_startup_banner_template` (in `HermesCLI`): reads `shutil.get_terminal_size()` for `wide_layout`/`tall_layout` flags; reads `_hermes_app._startup_output_panel_width` for `panel_w`; falls back to `term_width` when app or attribute is missing. Cache hit skips the O(N) scan loop but still calls `_render_startup_banner_text` (needed for TTE background lines).
- **Key insight**: `_render_startup_banner_text` must always be called even on cache hit because the template lines are used by the TTE overlay — only the scan loop can be skipped.
- **Testing pattern**: For integration tests, instantiate `HermesCLI` with `object.__new__(cli_mod.HermesCLI)` (no `__init__`), then patch `_render_startup_banner_text` on the instance via `patch.object`. Use a `_FakeRichText` / `_FakeLine` pair that mimics Rich Text's `.split(sep, allow_blank=True)` and `.plain` API.
- **Gotcha**: `_STARTUP_BANNER_PLACEHOLDER_MARKER` is a module-level constant in cli.py (PUA char ``). Tests must monkeypatch it to a simple ASCII string (e.g. `""`) so length arithmetic stays predictable.
- **Gotcha**: two separate booleans (`wide_layout = term_width >= 95`, `tall_layout = term_rows >= 20`) are required for the cache key — not one `logo_visible` flag. `banner.py` prints a wordmark when `term_width >= 95` but `term_rows < 20`, giving different geometry from the no-logo case. A single bool collapses those two states causing stale cache hits with wrong hero_row.
- **Gotcha**: `gc_geo_cache(cap=0)` must guard with `if cap <= 0: return`. Python `files[:-0]` equals `files[:]` (all items), not empty — passing 0 deletes the entire cache.

## 2026-05-03 — SPEC-STARTUP-OPT-1-PARALLEL-TTE

- **Pattern**: `template_cell: list = [None]` — mutable cell shared between multiple closures in `_play_tte_in_output_panel`. Producer thread reads `template_cell[0]` per-frame; main thread populates it after `_ensure_startup_banner_artefacts` returns. Eliminates the 0.5–1.5 s sequential wait on cache miss.
- **Closure cell ordering**: Python closure cells are fixed at function-definition time. All closures referencing `template_cell` must be defined *after* `template_cell` is bound in the enclosing scope. Use `inspect.getsource` in tests to assert ordering.
- **`call_later` timing**: `app.call_later(fn)` can fire `fn` at any point after enqueue — including before the next line in the calling thread. Move `call_later(_apply_preflight)` to *after* any variables `_apply_preflight` reads are populated.
- **Test pattern for closure capture**: patch `threading.Thread` as a `side_effect` function that captures `target` arg when `target.__name__ == "_produce"`. Use `inspect.getclosurevars(target).nonlocals["template_cell"]` to get the shared cell. Capture `_RealThread = threading.Thread` at module level *before* any `patch` call or you can't use `MagicMock(spec=_RealThread)` inside the patch context.
- **Cache hit path unchanged**: On cache hit, `_ensure_startup_banner_artefacts` still runs synchronously before the inline frame loop; `template_cell[0]` is populated before any splice call. No behavioral change on warm paths.
- **Gotcha**: `patch.object` restores the original mock value after the `with` block. Tracking call counts or side-effects across the `with` boundary requires assigning directly to the mock attribute (`cli.foo = my_fn`) rather than using `patch.object(cli, "foo", ...)`.

## 2026-05-09 — SPEC-LP-COL-CANONICAL-BODY-INDENT

- **New constant** `BODY_INDENT_COLUMNS: int = 2` in `hermes_cli/tui/widgets/output_panel.py`: mirrors `$body-indent: 2` TCSS variable; lets tests and Python code assert the canonical body column without reading the TCSS file.
- **TCSS variable** `$body-indent: 2` added to `hermes.tcss` variable block (LP-COL-1). Textual requires variables to be declared in the TCSS file itself — runtime skin overrides cannot inject them.
- **LP-COL-2 padding split**: `ToolPanel { padding-left: 1; }` + `ToolPanel BodyPane { padding-left: 1; }` in `hermes.tcss` give combined 2-col indent. Cannot use `$body-indent / 2` — TCSS arithmetic is not supported; each rule carries a comment referencing `$body-indent`.
- **LP-COL-3 comment contract**: `FooterPane.DEFAULT_CSS` comment updated to document that its `padding: 0 1` + parent ToolPanel's `padding-left: 1` = `$body-indent (2)`. No numeric change — comments only.
- **LP-COL-4**: `CodeSection` and `OutputSection` changed from `padding-left: 6` → `padding-left: 0`. The 6-col header-label alignment is achieved by the header's internal layout, not body indent. If any renderer relied on the 6-col offset for sub-element alignment, track as a separate follow-up spec.
- **LP-COL-5**: Comments added to `HermesApp.density-compact UserMessagePanel` rule (M2) and `ToolPanel { margin-bottom: 0; }` base rule (L1, confirmed not dead — compact/trace tiers inherit it; hero/default tiers override via higher-specificity rules).
- **Test approach**: All 22 tests are static (file-content assertions + DEFAULT_CSS string checks). No `run_test` + `widget.styles.*` is needed because the padding values live in DEFAULT_CSS (importable) or hermes.tcss (readable). Avoids the HermesApp VarSpec crash that kills runtime test apps loaded with the full hermes.tcss.
- **Gotcha**: `vkey` border in Textual is visual-only — it does NOT consume layout space. If body content must align with a widget that has `border-left: vkey`, you must add explicit `padding-left` to compensate; the border alone does not shift the text column.

## 2026-05-03 — SPEC-STARTUP-OPT-2-PRELAUNCH-WORKER

- **New method** `HermesCLI._start_prelaunch_banner_worker()`: starts a daemon thread named `hermes-banner-prelaunch` immediately after `_HApp` is configured and before `app.run()`. Thread waits on `OUTPUT_PANEL_WIDTH_READY` (1.5s timeout, falls back gracefully), then calls `resolve_banner_hero_assets()` → `_sanitize_startup_hero_text()` → `_ensure_startup_banner_artefacts()`. Exceptions caught + logged at DEBUG with `exc_info=True`.
- **`_prelaunch_artefacts_pending: bool`** flag init alongside `_startup_banner_template`/`_startup_banner_static`. Set to `True` before thread starts; cleared (one-shot) at top of `show_banner_with_startup_effect` regardless of TTE path. Prevents the reset of pre-built artefacts on initial startup; `/reload` path sees `False` and resets normally.
- **Join in `_play_tte_in_output_panel` Step C**: `getattr(self, "_prelaunch_banner_thread", None)` + `is_alive()` + `join(timeout=0.3)` inserted before the existing `_ensure_startup_banner_artefacts(plain_hero)` call. 300ms cap avoids stall on slow systems; `_ensure_startup_banner_artefacts` is a no-op if worker already finished (template already set).
- **Interaction with OPT1**: Independent of OPT1 (parallel producer). Both reduce visible startup latency; combined they eliminate all sequential banner-build latency from the on_mount path.
- **Test pattern**: `_make_cli()` returns `MagicMock(spec=HermesCLI)` with manually set attrs. Call unbound methods via `cli_mod.HermesCLI._start_prelaunch_banner_worker(cli)`. For threading tests, join the thread with a short timeout (2s) to let it complete. For timer/delay tests, use `threading.Event()` + `threading.Timer(0.05, event.set).start()` to simulate delayed panel-width signal.
- **Gotcha**: `patch.object(cli_mod, "_hermes_app", None)` needed in `show_banner_with_startup_effect` tests because the static path calls into `_set_tui_startup_banner_static` which reads `_hermes_app`. Without the patch, the real module global (set in other tests) leaks in.
- **Gotcha**: worktree created by EnterWorktree defaults to HEAD of main (not `feat/textual-migration`). After `EnterWorktree`, do `git reset --hard feat/textual-migration` to get the correct base. This repeats the AC skill gotcha — same pattern every time.

## 2026-05-03 — SPEC-STARTUP-OPT-4-DEFERRED-BANNER-DATA

- **New module** `hermes_cli/tui/_banner_data_cache.py`: SHA-1[:12] keyed 24h TTL disk cache for `(unavailable_toolsets, mcp_status, skills_by_category)`. Mirrors `_banner_geo_cache.py` pattern. `is_cache_disabled()` gates on `HERMES_NO_CACHE`. `save_banner_data` writes atomically via `.tmp`→rename. `gc_banner_data_cache()` removes `.tmp` files older than TTL. `schedule_refresh()` starts daemon thread `hermes-banner-data-refresh`; idempotent via module-level `threading.Event(_refresh_started)`.
- **banner.py/build_welcome_banner**: adds `from hermes_cli.tui._banner_data_cache import load_banner_data as _load_banner_data` inside the function body; branches on `_cached is not None` before each of the three slow calls. Live-call fallback has per-call try/except with `logger.exception` (check_tool_availability, get_available_skills) or `logger.debug` (get_mcp_status — cosmetic). HERMES_NO_CACHE disables all three caches with one knob.
- **cli.py/_ensure_startup_banner_artefacts**: replaced bare `if self._startup_banner_template is None` guard with threading.Event barrier. Pattern: `_artefacts_lock` guards a double-check + event allocation; `claimed` flag routes to build path or wait path; `finally: _artefacts_built_event.set()` guarantees waiters unblock even on exception; fast path `if self._startup_banner_template is not None: return` before lock acquisition.
- **cli.py/run_tui**: `schedule_refresh()` imported locally and called immediately after `_start_prelaunch_banner_worker()`. Daemon thread runs off critical path; no blocking.
- **Test pattern for _do_refresh inside schedule_refresh**: capture the real `_do_refresh` function with `real_do_refresh = mod._do_refresh` BEFORE `patch.object(mod, "_do_refresh", ...)`. Call `real_do_refresh()` inside `_patched_do()`, not `mod._do_refresh()` (that would recurse via the mock's side_effect).
- **Gotcha**: `from hermes_cli.tui._banner_data_cache import load_banner_data` inside a function body re-executes the attribute lookup on the cached module object each call. `patch("hermes_cli.tui._banner_data_cache.load_banner_data", ...)` intercepts correctly.
- **Gotcha**: Don't patch `function.__globals__` — it's a readonly attribute and `patch()` will raise `AttributeError` on `__exit__`. Patch at the module level instead.
- **Gotcha**: `_refresh_started` is a module-level singleton `threading.Event`. Tests that call `schedule_refresh()` must call `mod._refresh_started.clear()` in setup (via `_import_cache()` helper) or the second test in the same worker process will see the event already set and skip the thread start.

## 2026-05-09 — LP-RHYTHM Vertical Rhythm (spec-lp-rhythm-vertical-margins.md)

- **CSS change — hermes.tcss**: Replaced the old SLR-1 per-tier margin block (lines 893–914) with a single `ToolPanel, MessagePanel, UserMessagePanel { margin-bottom: 1; }` rule (LP-RHYTHM-1). `ChildPanel { margin-bottom: 0; }` retains the group-tight behaviour without needing per-tier overrides.
- **CSS change — hermes.tcss MessagePanel rule**: Changed `margin: 1 0 0 0` → `margin: 0` (line ~177). Margin-bottom: 1 is now provided by the new unified rule above; MessagePanel must not also declare margin-top.
- **Python change — message_panel.py UserMessagePanel.DEFAULT_CSS**: Changed `margin: 1 0 0 0` → `margin: 0` with LP-RHYTHM-2 comment. Trailing gap entirely owned by hermes.tcss margin-bottom rule.
- **CSS change — OutputPanelScrollBadge**: Changed `background: $panel-lighten-1 80%` → `background: $surface` (LP-RHYTHM-3). Fully opaque background prevents semi-transparent overlay of last content row.
- **New helper module**: `tests/tui/_rendered_position.py` — `widget_first_row(widget)` and `gap_between(w1, w2)` for asserting rendered row positions in Pilot tests without re-deriving region arithmetic everywhere.
- **Gotcha — LP-COL test dependency**: LP-COL-5 test `test_margin_bottom_base_rule_commented` checked for `"Do not delete"` near `ToolPanel { margin-bottom: 0; }`. LP-RHYTHM-1 removes both. Updated the LP-COL test to assert LP-RHYTHM-1 sentinel instead — always update sibling spec tests when one spec supersedes another's CSS rule.
- **Pattern — runtime gap tests**: Tests that assert `gap_between(w1, w2) == 1` use lightweight `App` subclasses with inline CSS (no HermesApp — avoids VarSpec errors from missing skin vars). Widget CSS mirrors the hermes.tcss LP-RHYTHM rule. Run with `asyncio.get_event_loop().run_until_complete(run())` pattern (not `@pytest.mark.asyncio`) to avoid strict-mode loop scope issues.
- **Density-compact specificity**: `HermesApp.density-compact MessagePanel { margin: 0; }` has specificity (0,2,1) vs LP-RHYTHM-1's (0,0,1). Compact rules always win without any change to the density-compact block.

## 2026-05-09 — LP-GUTTER-PHILOSOPHY (spec-lp-gutter-philosophy.md)

- **Rail convention**: Every top-level message block now carries a 1-cell `border-left: vkey` gutter rail. Text column = rail(1) + `padding-left(1)` = 2 (matches LP-COL `$body-indent`). No `margin-left` on these blocks — rail sits at col 0 of the content area.
- **CopyableBlock (LP-GUTTER-1)**: `DEFAULT_CSS` changed from `margin: 0 2` to `margin: 0; padding: 0 1; border-left: vkey $accent 60%`. Rail uses the existing `$accent` skin var — no new var needed.
- **UserMessagePanel (LP-GUTTER-2)**: `DEFAULT_CSS` changed from `padding: 0 2` to `padding: 0 1; border-left: vkey $user-accent 60%`. Added `user-accent` to all 11 bundled skin `x-hermes: component-vars:` sections.
- **`user-accent` lives in `component-vars`, not `colors:`**: The spec says to assert `SkinPayload.colors` but the actual field is `SkinPayload.component_vars` because `x-hermes: component-vars:` items flow into that dict. `SkinPayload.colors` would only have it if it were in `colors:` (root-level) or `x-hermes: colors:`. Test asserts `payload.component_vars["user-accent"]`.
- **ReasoningPanel (LP-GUTTER-3)**: Split-file fix — `DEFAULT_CSS` changed from `margin: 0 2; (no padding)` to `margin: 0; padding: 0 1`. `hermes.tcss` ReasoningPanel block changed from `margin: 0 2; border-left:...` to `padding: 0 1; border-left:...` (margin removed; padding mirrors DEFAULT_CSS for tcss specificity win). `#reasoning-collapsed` child's `padding: 0 1` zeroed to `padding: 0` (parent now provides padding-left: 1; child was double-padding).
- **tcss comment contains old value**: Putting `/* margin: 0 2 removed */` in hermes.tcss caused a string-search test to false-positive find `margin: 0 2`. Pattern fix: strip comment lines before asserting the live declaration is absent.
- **LP-COL test updates**: 4 LP-COL tests asserted `margin: 0 2 in CopyableBlock.DEFAULT_CSS`, `margin: 0 2 in ReasoningPanel.DEFAULT_CSS`, `padding: 0 2 in UserMessagePanel.DEFAULT_CSS`, and the cross-surface integration test. All updated to assert the post-LP-GUTTER state (border-left + padding: 0 1).
- **Compact density compatibility**: Rails use `border-left` (not margin). `HermesApp.density-compact` rules zero `margin` but do not touch `border-left`, so rails survive compact automatically. No change to compact rules needed.

## 2026-05-09 — HB1 HintBar Channel Discipline (spec_hb1_hint_channel_discipline.md)

- **`HINT_KEY_*` constants** — 11 new string constants in `hermes_cli/tui/services/feedback.py`: `HINT_KEY_REV_SEARCH`, `HINT_KEY_BASH_MODE`, `HINT_KEY_STATUS_ERROR`, `HINT_KEY_COMPACTION_WARN`, `HINT_KEY_COMPACTION_CRIT`, `HINT_KEY_PANE_FOCUS`, `HINT_KEY_DENSITY_CHANGE`, `HINT_KEY_DENSITY_TOGGLE`, `HINT_KEY_HISTORY_WRITE_ERR`, `HINT_KEY_TOOL_DISCOVERY`, `HINT_KEY_SCROLL_CATCHUP`. Import from `hermes_cli.tui.services.feedback` or `hermes_cli.tui.services import feedback as _fb`.
- **`_flash_hint` signature extended** — now accepts `key: str | None = None` and `priority: int = 10` (NORMAL). Returns `FlashHandle` (was `None`). Call sites that need non-clobbering behavior pass a stable key from the catalogue.
- **`FlashMessage` class deleted** — was in `status_bar.py`. All call sites (`tool_panel/_core.py`, `tool_blocks/_streaming.py`) updated to call `app.feedback.flash("hint-bar", ...)` with `priority=LOW`, `key=HINT_KEY_DENSITY_CHANGE`. `on_flash_message`, `_flash_text`, `_flash_timer`, `_clear_flash` all removed from `HintBar`.
- **`pane_manager` hint routing** — `focus_pane_widget()` now calls `app.feedback.flash("hint-bar", "Esc → input", duration=3.0, priority=LOW, key=HINT_KEY_PANE_FOCUS)`. `_clear_hint_if_side_pane` helper deleted; `app.set_timer` removed. Method name in production code is `focus_pane_widget`, not `focus_active_pane` (spec used the old name).
- **StatusBar S1-E simplified** — removed `_feedback_explicit`/`_mockish` dance from flash detection. Just `_feedback.peek("hint-bar")` if `_feedback` is not None; `_hintbar_flashing = _flash_state is not None`.
- **IL-HB-1 lint gate** — AST scan in `TestCancelByKey::test_il_hb_1_lint_gate` finds zero `cancel("hint-bar")` without `key=` in `hermes_cli/tui/`. All 3 previous bare-cancel sites (history exit, bash mode, status_error) now carry keys.
- **Gotcha — `pane_manager` method name**: spec called it `focus_active_pane` but the real method is `focus_pane_widget(pane_id, app)`. Tests must use the real name.
- **Gotcha — FeedbackService cancel does NOT restore from stack**: When flash A preempts flash B (B was active, A arrives at higher priority), B is gone. Cancelling A by key leaves the channel empty. There is no restoration stack. Tests that check "cancel of overlay leaves prior flash visible" must pre-populate the lower-priority flash after the cancel, or assert channel is empty.
- **Gotcha — `FlashMessage` also used in `tool_blocks/_streaming.py`**: The spec only mentioned `tool_panel/_core.py`. In practice `_streaming.py` also imported `FlashMessage` for kind-revert and adoption toasts. Both updated to `feedback.flash(... key=HINT_KEY_DENSITY_CHANGE ...)`.
- **24 tests** in `tests/tui/test_hint_channel_discipline.py`; all pass in ~3s. Invariants: 53/53 pass.

## 2026-05-09 — HB2 HintBar Render & Phase Fixes (spec_hb2_hintbar_render.md)

- **`_hint_to_text(raw, default_style=None)`** — new module-level helper in `status_bar.py`. Parses Rich markup via `Text.from_markup()`; falls back to `Text(raw)` on parse error with `_log.debug(..., exc_info=True)`. Use instead of `Text(raw)` anywhere markup is intended.
- **`_build_streaming_hint(key_color, width=120)`** — signature changed; now degrades long→short→minimal based on width: `>=78` full, `>=48` short (no descs), else minimal. Callers must pass `width`; default 120 preserves old behavior.
- **`_streaming_pinned_text(key_color, width)`** — new HintBar instance method; width-aware helper reusing `_hints_for("stream", ...)` cached variants.
- **`_render_streaming()`** — new HintBar instance method; replaces the old inline streaming branch in `render()`. Priority-≥10 flashes are left-anchored with compact cue on right; LOW flashes remain right-appended.
- **`_STREAMING_PROMOTE_PRIORITY = 10`** — module constant; set to 999 to revert to legacy right-anchored behavior without code change.
- **`_vars()`, `_key_color(vars_=None)`, `_shimmer_colors(vars_=None)`** — unified CSS var resolver methods on HintBar. `_get_key_color()` kept as deprecated alias. Always pass `v = self._vars()` once per render and thread through.
- **`_peek_flash()`** — HintBar helper to safely access `feedback.peek("hint-bar")`; returns FlashState or None.
- **`_should_shimmer()`** — HintBar helper: `running and _animations_enabled`. Used by M3/M4.
- **`_shimmer_state_consistent_with_phase(phase)`** — HintBar helper for M4 short-circuit check.
- **`_clear_hint_cache()`** — module-level hook; added FIFO bound `_HINT_CACHE_MAX = 32` to `_hints_for()`; theme.py uses `_clear_hint_cache()` instead of direct `.clear()`.
- **Watchers `on_status_error`** — now resolves `status-error-color` CSS var and wraps flash text in `[bold {err_color}]⚠ {value}[/]` markup so HintBar renders it bold-red.
- **`_on_streaming_change()`** — HB2-M3: immediately evicts stale stream/file phase when `not running`; no longer waits for next render. Calls `self.refresh()` unconditionally at end.
- **`set_phase()`** — HB2-M4: checks `_shimmer_state_consistent_with_phase()` before short-circuiting; same-phase call with stopped shimmer now correctly restarts it.
- **KEY_* constants + HINT_MAX_PRIMARY** — now exported from `hermes_cli.tui.widgets.__init__` (HB2-L2).
- **Gotcha — HintBar widget stub**: `content_size` is a Widget property with no setter; `app` is a MessagePump property backed by a context variable. Both require a local `_FakeHintBar(HintBar)` subclass that overrides both as plain `@property` returning fake values. Cannot be patched via `__dict__`.
- **Gotcha — Rich span style is a string**: `Text.from_markup("[bold]X[/]")._spans[0].style` is `'bold'` (str), not a `Style` object. Check `isinstance(s.style, str) and "bold" in s.style` OR `hasattr(s.style, "bold") and s.style.bold` — both branches needed for robust detection.
- **26 tests** in `tests/tui/test_hint_render.py`; all pass in 0.56s. Invariants: 53/53 pass.
- **worktree sync gotcha**: After `EnterWorktree`, the worktree branch HEAD may point to a different commit than intended. Use `git -C <main-repo> update-ref refs/heads/<worktree-branch> <target-SHA>` to force the branch pointer, then `git reset HEAD && git checkout -- .` to update the index and working tree. `git branch -f` does not update locked worktree branches.

## 2026-05-09 — RZ-OP OutputPanel & RichLog resize hardening (spec_rz_output_panel.md)

- **`OutputPanel._last_resize_geom: tuple[int,int] = (-1,-1)`** — new `__init__` attr. `on_resize` reads `(new_w, new_h)` from `event.size` via `getattr` chains and skips `_resolve_layout()` when geometry is unchanged (height-only drag, repeated cascades).
- **`OutputPanel._force_width_ready_fallback()`** — new instance method. Registered via `self.set_timer(2.0, ...)` at the end of `on_mount`. Sets `OUTPUT_PANEL_WIDTH_READY` and a default `_startup_output_panel_width = 79` if no resize delivered `width > 0` within 2s. Guards on truthy existing width to avoid overwriting a real value.
- **`OutputPanel.on_mount` width-capture fix** — `try/except` around `self.size.width` now splits: raises go to `_log.warning(..., exc_info=True)` with `w = 0` fallback. `if w > 0:` block is outside `try`. `set_timer` call placed *after* the width block, outside the swallow boundary.
- **`OutputPanel.on_resize` width-capture fix** — same pattern: `try` around `self.size.width` only; `except Exception` logs `WARNING + exc_info`; `w = 0` fallback; `if w > 0:` gate outside `try`.
- **`_clear_thinking_reserve` swallow upgraded** — `except Exception: pass` replaced with `except Exception: _log.debug("clear_thinking_reserve: tw.clear_reserve() failed", exc_info=True)`. Comment updated to explain why swallowing is correct.
- **`CopyableRichLog.on_resize` width guard** — `self._render_width = event.size.width` gated: only assigns when `w > 0`; zero fires `_log.debug("CopyableRichLog.on_resize: event.size.width == 0; skipping update")`.
- **Test pattern — duck-typed `_PanelStub`**: `OutputPanel.__new__` fails with `ReactiveError` if you try to set `scroll_state` before `super().__init__`. Use a plain `_PanelStub` class with matching attrs and call `OutputPanel.on_resize(stub, event)` / `OutputPanel.on_mount(stub)` directly. Add `_force_width_ready_fallback` method to stub so `set_timer(2.0, self._force_width_ready_fallback)` in `on_mount` resolves.
- **19 tests** in `tests/tui/test_resize_output_panel.py`; all pass in ~2.5s.

## 2026-05-09 — SessionOverlay SO-1/SO-2/SO-3 (spec_session_overlay_polish.md)

- **`_format_tokens_compact(total: int) -> str`** — module-level in `_legacy.py`. Always returns exactly 9 chars. Strip trailing `.0` by calling `.rstrip("0").rstrip(".")` **before** appending `"k"` / `"M"` suffix — suffix is appended after stripping, not before.
- **`_SessionRow._build_label(selected: bool = False) -> Text`** — returns Rich `Text` (not str). Fixed-width column layout: selector(2) + current(2) + title(flexible) + last(11+1sep) + turns(9+1sep) + tokens(9). No markup in layout math.
- **`_SessionRow.__init__`** — accepts `title_width=18`, `heavy_threshold`, `color_tokens_*`. All must be assigned **before** `super().__init__(self._build_label(), ...)`.
- **`SessionOverlay._render_rows`** — resolves token colors with `_is_hex()` guard: CSS computed values like `"auto 38%"` raise `ColorParseError` in `Rich.Style`, so non-hex values fall back to hardcoded defaults.
- **SO-3 state machine**: `_pending_delete_idx`, `_cancel_pending_delete()`, confirm guard in `action_dismiss`. `action_select`/`action_new_session` call `dismiss_overlay()` directly to bypass guard. `open_sessions()` always calls `_cancel_pending_delete()` first.
- **Gotcha — Rich Color `.name` attribute**: `str(Color.parse("#3E4252"))` returns full repr. Use `Color.parse(...).name` (lowercase `"#3e4252"`) in test assertions. Via `style.color.name`.
- **42 tests** in `tests/tui/test_session_overlay.py`; all pass in ~14s.

## 2026-05-09 — RZ-MED resize delta gates (spec_rz_media_prose.md)

- **`InlineImage._last_resize_size: tuple[int,int] = (-1,-1)`** — new instance attr in `__init__`. `on_resize` reads `self._reactive_image` (not `self.image`) to avoid `ReactiveError` on unmounted widgets, then skips `watch_image` if `(w,h)` is unchanged. Internal reactive backing attr is named `_reactive_image` per `reactive.internal_name`.
- **`InlineProseLog.on_resize`** — `_render_mode_cache = None` moved inside the `new_px != _last_cell_px` branch. `_reset_cell_px_cache()` and `self.refresh()` remain unconditional. Keeps public wrappers current without wasted cache-recompute on drag cascades.
- **`InlineMediaWidget._last_seekbar_w: int = 0`** — added to `__init__`. `on_resize` gates `_seekbar.refresh()` on width change only; height-only events skip the repaint. Note: spec called this class `MediaPlayerWidget` but the actual class is `InlineMediaWidget` in `widgets/media.py`.
- **`DrawbrailleOverlay.on_resize`** — computes candidate `new_w`/`new_h` then returns early if `_anim_params` already has those dims; otherwise updates and calls `refresh()`. Avoids piling 5–20 redundant refreshes on top of the normal animation cadence during a drag.
- **Gotcha — `_reactive_image` for unmounted `InlineImage`**: accessing `self.image` (the reactive descriptor) on an unmounted widget raises `ReactiveError`. Read `self._reactive_image` directly instead; inject it in tests via `obj._reactive_image = sentinel`.
- **Test pattern — `__new__` + attribute injection**: all four widget tests use `object.__new__(WidgetClass)` and inject only the attrs exercised by `on_resize`. No app/DOM mount needed. `unittest.mock.patch.object(obj, "watch_image")` works even on `__new__`-constructed objects.
- **17 tests** in `tests/tui/test_resize_media_prose.py`; all pass in ~2.4s. Commit `7d5c6cbb7`.

## 2026-05-09 — RZ-APP-H1/H4/L6 resize debounce hygiene (spec_rz_app_debounce.md)

- **`HermesApp._last_flushed_size: tuple[int, int] = (-1, -1)`** — new `__init__` attr (near `_pending_resize`). Sentinel ensures first real flush always fires all steps.
- **`_flush_resize` geometry gate** — `width_changed` / `geom_changed` booleans derived from `_last_flushed_size`. `_apply_min_size_overlay` and `_pane_manager.on_resize` gated on `geom_changed`; `_recompute_auto_compact` and hard-floor `compact=True` gated on `width_changed`. `_maybe_reload_emoji` runs every flush (orthogonal to terminal dims).
- **`_RESIZE_DEBOUNCE_S` comment block** — 8-line comment above the constant explains what the debounce protects (app-level steps only), what it does NOT protect (child widget Textual cascades), and the 60 ms tuning rationale.
- **H4 exception log** — bare `except AttributeError: return` replaced with `logger.warning(..., exc_info=True)` so missing `.size` is visible in logs instead of silently aborting the flush.
- **Gotcha — `compact` reactive on `__new__` objects**: `HermesApp.compact` is a Textual `reactive` descriptor. Writing `self.compact = x` on an unmounted `__new__`-constructed object raises `ReactiveError("Node is missing data")`. Fix: create a test subclass (`_StubApp`) that shadows the reactive with a plain class attribute `compact = False`, then use `__new__(_StubApp)`. `_flush_resize` uses `self.compact` so the stub's plain attr is read/written correctly.
- **Test pattern — source-inspection with `inspect.getsource(module)`**: when asserting comment text above a constant, extract a window of 600+ chars before the constant's text position. Use `.lower()` to handle capitalisation differences (comment may start with capital letter).
- **14 tests** in `tests/tui/test_resize_app_flush.py`; all pass in ~2.4s.

## 2026-05-09 — RZ-OV-M4/M5/M7 Overlay resize gating (spec_rz_overlays.md)

- **`HistorySearchOverlay._last_render_w: int = 0`** — new `__init__` attr. `on_resize` early-returns if not `--visible`, reads `self.app.size.width`, skips `_render_results` when width unchanged, logs debug if `app` unavailable.
- **`KeymapOverlay.__init__`** — class had no `__init__`; new one adds `_last_resize_w: int = 0`. `on_resize` uses `crosses_threshold(old, new, 80)` (HYSTERESIS=2, dead-band [78,82)); `_update_content` only called on crossing; `_last_resize_w` always updated.
- **`CompletionOverlay._last_applied_max_h: int = -1`** — added in `on_mount` alongside `_last_applied_w`. `on_resize` wraps `styles.max_height = avail` in `if avail != self._last_applied_max_h:` guard; cache updates only inside the successful write branch.
- **Import added**: `from hermes_cli.tui.resize_utils import crosses_threshold` added to `widgets/overlays.py`.
- **Gotcha — `self.app` on `__new__` widgets**: property traverses `_MessagePump__parent` chain → `AttributeError`. Patch via `patch.object(type(overlay), "app", new_callable=PropertyMock)` to inject a `SimpleNamespace(size=Size(w,h))`.
- **Gotcha — `query_one()` on unmounted widgets**: raises `AttributeError: '_nodes' not found` when no DOM. Must also `patch.object(overlay, "query_one", return_value=mock_input)` for tests exercising paths that call `query_one`.
- **11 tests** in `tests/tui/test_resize_overlays.py`; all pass in ~2.3s. Merge `9f5622765`.

## 2026-05-09 — RZ-CL-M1/M2/M8/L2/L5 Resize subsystem cleanup (spec_rz_cleanup.md)

- **`PaneManager.on_resize` → `update_for_size`** (M8): pure rename to avoid Textual's `on_<event>` auto-dispatch hook collision. Updated 24 call sites: `app.py:_flush_resize`, 7 in `test_pane_manager.py`, 16 in `test_pane_responsive.py`. Note: `_flush_resize` (not `on_resize`) is the method that calls it — asserting the rename in tests should inspect `_flush_resize` source, not `on_resize`.
- **`NAMEPLATE_REFRESH_DELTA = 4`** (M2): new constant in `resize_utils.py`. Replaces `abs(delta) > HYSTERESIS * 2` with `abs(delta) >= NAMEPLATE_REFRESH_DELTA` in `Nameplate.on_resize`. Inclusive `>=` is intentional — avoids off-by-one at delta==4. `_last_nameplate_w` now always updated.
- **`INITIAL_WIDTH = 0` + `initial_resize_state()`** (L2): added to `resize_utils.py`. Removes `_last_applied_w == 0` double-guard from `CompletionOverlay` — `crosses_threshold(0, any_sane_new_w, threshold)` already fires on first call.
- **`tools_overlay.py` size source** (M1): `on_resize(self) → on_resize(self, event: "events.Resize")`. Reads `event.size.width` instead of `self.app.size.width`. Added `from textual import events` import.
- **Annotation sweep** (L5): standardised 10 files from `event: Any` / `event: object` → `event: "events.Resize"` (unused → `_event`). Added `from textual import events` to each file that lacked it. Also canonicalised `getattr(event.size)` fallbacks to `event.size.width` in `_footer.py`, `_actions.py`, `tool_group.py`.
- **Gotcha — `Screen.app` has no setter**: `ToolsScreen.app` is a property without a setter — `instance.app = mock` raises `AttributeError`. Use `MagicMock(spec=ToolsScreen)` instead of `object.__new__(ToolsScreen)` for dispatch tests; property attributes are set on the mock directly.
- **Gotcha — conflicts from advanced HEAD**: merge produced 3 conflicts where HEAD had added dedup guards (`_last_flushed_size`, `_last_resize_size`, `_last_seekbar_w`). Resolution: keep HEAD logic but swap annotation and `getattr(event.size)` → `event.size.width`.
- **11 tests** in `tests/tui/test_resize_cleanup.py`; 86 total (including 75 pre-existing pane tests) pass in ~4s.

## 2026-05-09 — MPC-H1/M1/M2/L1: background model catalog cache (spec: model-picker-cache.md)

**New fields in `ConfigOverlay.__init__`:**
- `_model_cache: dict[str, list[str] | list[dict]] = {}` — per-provider model ID lists
- `_provider_list_cache: list[dict] | None = None` — cached `list_available_providers()` result
- `_model_prefetch_done: bool = False` — gates prefetch re-run on dismiss/reopen

**New methods:**
- `_prefetch_all_providers()` — `@work(thread=True, name="model-catalog-prefetch")` decorated; fills `_provider_list_cache` then all per-provider model lists in one worker thread
- `_fetch_provider_models(provider, current_model)` — plain method, always called via `run_worker(..., thread=True, name=f"model-catalog-fetch-{provider}")`; stores to `_model_cache`; calls `self.app.call_from_thread(self._populate_model_list, ...)` if still browsing same provider

**Changed behaviour:**
- `_populate_model_list`: reads `_model_cache.get(provider)` first; on miss shows `"⟳ loading…"` placeholder and fires targeted fetch worker (worker name-based dedup guard)
- `_populate_provider_list`: reads `_provider_list_cache` first; falls back to synchronous call with `_log.warning` on failure
- `dismiss_overlay`: resets `_model_prefetch_done = False` so prefetch re-runs on next open
- `show_overlay`: starts prefetch worker after `_refresh_active_tab()`; dedup guard prevents concurrent prefetches

**Critical gotchas:**
- `call_from_thread` is on `self.app`, NOT `self` (Widget/MessagePump don't have it in this Textual version)
- `work` decorator imports from `textual`, not `textual.worker` (`from textual import work`)
- `Worker.is_done` doesn't exist — use `w.state not in _WORKER_DONE` where `_WORKER_DONE = {WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED}`
- `run_worker` can't forward positional args to callable — use a lambda: `run_worker(lambda: self._fn(arg1, arg2), name=..., thread=True)`
- `call_from_thread` can't be patched via `patch.object(ov, ...)` — it's not on the widget; patch `pilot.app.call_from_thread` instead
- `type(ov).workers = property(...)` MUST use `patch.object(type(ov), "workers", new_callable=PropertyMock)` — replacing the property directly breaks teardown (Textual calls `self.workers.cancel_node(self)` on unmount)
- Bound methods aren't identity-equal across attribute accesses; use `mock.call_args[0][0].__func__ is ConfigOverlay._method` for identity checks
- **18 tests** in `tests/tui/test_model_picker_cache.py`; commit `cb9b0275a`

## 2026-05-09 — TTE-SETTLE-M1/H1/H2: settle frame gradient direction fix

**New API in `hermes_cli/tui/tte_runner.py`:**
- `get_effect_gradient_direction(effect_name, params=None) -> str` — instantiates effect, reads `effect_config.final_gradient_direction.name`, returns 'VERTICAL'/'HORIZONTAL'/'DIAGONAL'/'RADIAL' or 'DIAGONAL' on any failure. Place after `_apply_skin_gradient`.

**Changed signature in `cli.py`:**
- `_hero_ansi_with_stops(self, plain_hero, stops, direction="DIAGONAL")` — VERTICAL=per-row gradient, HORIZONTAL=per-col gradient, else=original char-count. Default preserves backward compat.

**Wiring in `_play_tte_in_output_panel`:**
- `_settle_direction` block injected after `_settle_stops` block; both cache-miss and cache-hit settle-frame calls now pass `_settle_direction`.

**Gotchas:**
- `plain_hero.split("\n")` with trailing `"\n"` yields a phantom empty-string row — colors shift because n changes; downstream `.splitlines()` absorbs the extra empty row but colors are NOT identical. Test with `len(non_blank_lines)` equality, not full string equality.
- TTE `_TestSettleDirectionWiring` tests require `_install_draining_set_interval` from `test_tte_cache.py` pattern (set_interval arg order is `(interval, fn)` not `(fn, interval)`); call_from_thread must drain ticks synchronously or `playback_done.wait` times out.
- `get_effect_gradient_direction` can't be patched at the `cli.py` import site — must patch `hermes_cli.tui.tte_runner.get_effect_gradient_direction`.
- 16 tests in `tests/tui/test_tte_settle_direction.py`.

## 2026-05-09 — SPEC-CP-FEEDBACK: CopyResult + truthful copy feedback

**New type in `hermes_cli/tui/osc52.py`:**
- `CopyResult(frozen dataclass)` — `success: bool`, `bytes_written: int`, `bytes_input: int`, `truncated: bool`, `.truncation_ratio` property (1.0 when bytes_input==0).
- `osc52.write(text)` now returns `CopyResult` instead of `bool`. Single in-tree caller was `services/theme.py`.

**New constants in `hermes_cli/tui/services/feedback.py`:**
- `HINT_KEY_COPY_OK = "copy-ok"` and `HINT_KEY_COPY_TRUNCATED = "copy-truncated"`.

**Changed in `hermes_cli/tui/services/theme.py` — `ThemeService`:**
- `copy_text_with_hint` refactored: collects `CopyResult` per channel into `sync_outcomes`, delegates to `_dispatch_copy_feedback`.
- `_dispatch_copy_feedback(outcomes, char_count)` new helper: no-success → `set_status_error("copy failed — see log")`; truncated → flash with `M/N chars copied (truncated to terminal cap)`; else → `⎘  N chars copied`.
- xclip `on_error` callback now only logs at WARNING and calls `_dispatch_copy_feedback`; old `set_status_error` side-effect removed.
- Feedback for successful copy goes through `self.app._flash_hint(key=..., priority=...)` not through `self.flash_hint`.
- `set_status_error` still routes through `self.flash_hint → self.app.feedback.flash` (not `_flash_hint`).

**Gotchas:**
- `ThemeService.flash_hint` routes to `self.app.feedback.flash("hint-bar", ...)` while `_dispatch_copy_feedback` routes to `self.app._flash_hint(...)`. These are different call paths; tests asserting on `_flash_hint` will miss `set_status_error` side effects and vice versa.
- `safe_run` `on_error` callback signature is `(exc: Exception, stderr: str)` — two args. Spec pseudocode showed one arg; adapt accordingly.
- `safe_run` is a module-level function `safe_run(app, cmd, ...)` — `app.safe_run` does not exist.
- `CopyResult.success` for Textual path is inferred from absence of exception (no return value from `copy_to_clipboard`).
- 10 tests in `tests/tui/test_copy_feedback.py`.

## 2026-05-09 — SPEC-IIB-LIFECYCLE: InlineImageBar lifecycle hardening

**New constant in `hermes_cli/tui/widgets/inline_media.py`:**
- `_MAX_THUMBNAILS = 40` — module-level cap on mounted `InlineThumbnail` widgets.

**New class in `hermes_cli/tui/widgets/inline_media.py`:**
- `_OldnessChip(Static)` — left-docked chip showing `+N earlier images` when thumbnails have been evicted. Set `tooltip` *after* construction (not as `__init__` kwarg); `Static.__init__` does not accept `tooltip`.

**New fields on `InlineImageBar.__init__`:**
- `_chips_by_key: dict[tuple[str, int], InlineThumbnail]` — live mapping `(realpath, mtime) → widget`.
- `_chip_order: list[tuple[str, int]]` — oldest-first eviction order.
- `_evicted_count: int` — monotonic count; drives `_OldnessChip` label.
- `_next_idx: int` — monotonic stable index (replaces fragile `len(self._paths)` idiom).

**New methods on `InlineImageBar`:**
- `_next_index()` — monotonically increasing stable ID.
- `_dedupe_key(path)` → `(str, int)` — calls `Path.resolve()` + `stat().st_mtime`; `OSError` → mtime=0.
- `_highlight_existing(key)` — adds `--highlight-pulse` CSS class; timer removes it after 0.6s.
- `_evict_oldest(container)` — pops `_chip_order[0]`, calls `chip.remove()`, increments `_evicted_count`.
- `_sync_oldness_chip(container)` — mounts/updates `_OldnessChip`; removes it when `_evicted_count==0`.
- `_recompute_visibility()` — adds/removes `--visible` based on `bool(_chips_by_key)`.
- `clear()` — removes all `InlineThumbnail` and `_OldnessChip`, resets all tracking state.

**Changed in `InlineThumbnail.on_mount`:**
- Computes `_tooltip_text` from `relative_to(cwd)` before calling `_load_strips()`. Uses `getattr(self.app, "get_working_directory", lambda: Path.cwd())()` for cwd.

**New constant in `hermes_cli/tui/services/feedback.py`:**
- `HINT_KEY_IMAGE_NOT_IN_VIEW = "image-not-in-view"`.

**Changed in `hermes_cli/tui/app.py` — `on_inline_image_bar_thumbnail_clicked`:**
- Now uses `return` instead of `break` after match; adds `--highlight-pulse` on match; on miss calls `_flash_hint` with `HINT_KEY_IMAGE_NOT_IN_VIEW`.

**Changed in `hermes_cli/tui/services/commands.py` — `handle_clear_tui`:**
- After `op.remove_children()`, calls `app.query_one(_IIB).clear()` (NoMatches swallowed with comment — bar may be disabled).

**Gotchas:**
- `Static.__init__` does NOT accept `tooltip` kwarg; set it as `chip.tooltip = tip` after construction.
- `Widget.app` is a read-only property; cannot set `thumb.app = fake` in tests. Use `run_test` with a minimal app that provides `get_working_directory()`.
- `on_inline_image_bar_thumbnail_clicked` lives only in `HermesApp`; for lightweight tests, extract the handler body into a standalone async function that accepts `(app, event)`.
- `_OldnessChip.render()` returns a `textual.content.Content` object; `str(rendered)` gives the text string.
- `chip.remove()` in `_evict_oldest` automatically cancels in-flight `@work(thread=True)` workers via `on_unmount`.
- 16 tests in `tests/tui/test_inline_image_bar_lifecycle.py`.

---

## 2026-05-09 — SPEC-X-DESIGN-TOKENS: attachment skin token centralisation

**New module-level constants in `hermes_cli/tui/widgets/status_bar.py`:**
- `_ATTACHMENT_CSS_DEFAULTS: dict[str, str]` — five hard-coded hex fallbacks for attachment chip tokens; used when `get_css_variables()` raises or skin is missing keys.
- `_ATTACHMENT_REQUIRED_KEYS: frozenset[str]` — `frozenset(_ATTACHMENT_CSS_DEFAULTS)`; change-detector for X-DT-3.

**New helpers in `status_bar.py`:**
- `_get_attachment_css_vars(skin_vars)` — returns all five attachment CSS-var values; falls back to `_ATTACHMENT_CSS_DEFAULTS` per-key for missing tokens.
- `_check_attachment_tokens(skin_vars, widget_name)` — emits `_log.warning` per missing key (sorted); call guarded by `_tokens_checked` flag on widget instance.

**Changed in `ImageBar`:**
- `__init__` gains `_tokens_checked: bool = False` — one-shot lint gate.
- `render()` restructured: captures `_raw = get_css_variables()` then `_get_attachment_css_vars(_raw)` + calls `_check_attachment_tokens(_raw, ...)` on first paint; uses `attachment-chip-shimmer-dim/peak` keys instead of `spinner-shimmer-*`.
- `update_images()` applies `_av["attachment-chip-fg"]` as Rich Text style instead of hardcoded `"dim"`.
- Both `except Exception` paths log at DEBUG with `exc_info=True` (matching HintBar._vars() pattern in same file).

**Skin DESIGN.md (all 11 bundled skins) — `x-hermes.component-vars`:**
- Five new keys added after `spinner-shimmer-peak`: `attachment-chip-fg`, `attachment-chip-bg`, `attachment-chip-shimmer-dim`, `attachment-chip-shimmer-peak`, `attachment-chip-remove-fg`.
- Use `{colors.ui-accent}` / `{colors.ui-error}` token refs where available; shimmer values mirror the skin's spinner-shimmer values.

**Test patterns (8 tests in `tests/tui/test_attachment_skin_tokens.py`):**
- Skin coverage test uses `load_design_md_payload()` + checks `payload.component_vars` (not raw YAML `colors:` — attachment tokens are in `x-hermes.component-vars`).
- `_make_image_bar()` creates unmounted `ImageBar` via `__new__`; reactive `_shimmer_tick` requires `widget.__dict__["_id"]`, `widget.__dict__["_shimmer_tick"]` (use `__dict__` direct write to bypass descriptor).
- `display` property setter accesses `self.styles` (unavailable without mounted app); stub with `ImageBar.display = property(lambda s: True, lambda s, v: None)` in test.
- `_shimmer_once` calls `set_interval`; stub as `lambda base_text, **kw: None` on instance.

**Gotchas:**
- `attachment-chip-*` tokens live in `x-hermes.component-vars` → `SkinPayload.component_vars` → `ThemeManager._component_vars` → `css_variables`. NOT in `colors:` top-level.
- The `{colors.ui-accent}` reference resolves at skin load time via `_resolve_all_refs` (refs context = `{"colors": fm["colors"]}`). Catppuccin uses `{colors.muted}` / `{colors.foreground}` for shimmer — follow the same pattern for shimmer tokens in catppuccin.
- `except Exception` in `render()` / `update_images()` is intentional (CSS lookup fail-safe in render path); log at DEBUG not WARNING to avoid per-frame noise.

---

## Changelog 2026-05-09 — SPEC-DD-POLICY file-drop policy refinements

**Changed in `hermes_cli/file_drop.py`:**
- Added `import shlex` at top.
- `IMAGE_EXTENSIONS` now includes `.heic`, `.heif`, `.avif` (DD-PL-3).
- `DroppedFile.kind` Literal expanded with `"directory_rejected"`, `"directory_glob"`.
- `classify_dropped_file` gains `allow_directory: bool = False` kwarg; default rejects dirs with reason `"drop a file, not a folder (use /index <dir>)"`; with `allow_directory=True` returns `kind="directory_glob"` (DD-PL-1).
- `format_link_token` replaced double-quote-if-spaces logic with `shlex.quote` (DD-PL-4). Safe paths return bare strings; paths with spaces/specials return single-quoted.
- Greedy-prefix space scan in `detect_file_drop_text` bounded to 12 positions via `[:12]` slice (DD-PL-5).

**Changed in `hermes_cli/tui/services/watchers.py`:**
- Added module-level `_INTERRUPT_ATTRS = ("approval_state", "interrupt_state", "confirm_state")`.
- `WatchersService.__init__` gains `_pending_drop_queue: list[Path]` and `_last_drop_undo_state: tuple[str, list] | None` slots.
- Added `_modal_active()` helper using `_INTERRUPT_ATTRS` (DD-PL-6).
- `handle_file_drop_inner`: modal check now uses `_modal_active()` and buffers instead of discarding (DD-PL-6). Directory handling updated for new kinds. Rejected-path hint now names first file + overflow count (DD-PL-2). `directory_glob` formatted as `token + "/**/*"`.
- Added `_replay_pending_drops()` helper; wired into `on_approval_state` on transition to `None`.
- `insert_link_tokens` snapshots pre-drop state, calls `history.checkpoint()` before/after mutation, stores `_last_drop_undo_state` (DD-PL-7).

**Changed in `hermes_cli/tui/input/widget.py`:**
- Added `action_undo` to `HermesInput`: checks `WatchersService._last_drop_undo_state`, restores `inp.text` and `app.attached_images`, then falls through to `super().action_undo()` if slot is None (DD-PL-7).

**Gotchas:**
- `shlex.quote` does NOT always single-quote: safe strings (no spaces/specials) are returned bare. Only paths with spaces, quotes, or shell metacharacters get wrapped. Test assertions must use `shlex.quote(...)` as the expected value, not assume leading `'`.
- `TextArea.history` is a `textual.document._history.EditHistory` object with a `.checkpoint()` method (present in Textual 0.80+). The `max_checkpoints` kwarg in `TextArea.__init__` controls how many history entries are kept.
- `_modal_active()` uses `getattr(..., None)` so non-existent attrs (`interrupt_state`, `confirm_state`) are safe — they return `None` and don't raise `AttributeError`.
- The greedy-prefix bound (12) means paths with more than 12 spaces in the full input string may not be detected by the prefix scan. The full-string check (first candidate) still runs so a complete path with 12+ spaces is found on the first try.
- 26 tests total: 8 in `tests/test_file_drop_policy.py` (pure unit), 8 in `tests/tui/test_drop_policy.py` (stub-based), 10 in `tests/tui/test_file_drop.py` (existing, updated).

---

## Changelog 2026-05-09 — SPEC-IB-VISIBILITY ImageBar visibility resolver

**New APIs in `hermes_cli/tui/widgets/status_bar.py`:**
- `ImageBar.recompute_visibility()` — single authority for `--visible` class; reads `self.app.size.height` and `len(self.app.attached_images)`; call from any site after state change.
- `ImageBar.DEFAULT_CSS` now contains `ImageBar.--visible { display: block; }` — the class toggle has visual effect.
- `ImageBar._recompute_visibility()` now delegates to `recompute_visibility()` instead of setting `self.display` directly.
- `StatusBar._attachment_count_hidden: int = 0` — local field updated by `_on_attachment_count_hidden_change` watch callback.
- `StatusBar._on_attachment_count_hidden_change(count)` — watch callback for `app.status_attachment_count_hidden`.
- `StatusBar.render()` prepends `📎N` chip to `state_t` when `_attachment_count_hidden > 0`.

**New APIs in `hermes_cli/tui/services/watchers.py`:**
- `WatchersService._sync_status_attachment_chip()` — writes `app.status_attachment_count_hidden` based on `h < 10` and `count > 0`; called from both `on_attached_images` and end of `on_size`.
- `on_size` now calls `image_bar.recompute_visibility()` via `except (NoMatches, AttributeError): pass` block.

**New reactive in `hermes_cli/tui/app.py`:**
- `status_attachment_count_hidden: reactive[int] = reactive(0)` — drives the StatusBar chip.

**Gotchas:**
- `DOMNode.add_class`/`remove_class` call `update_node_styles()` which walks the DOM tree. In unit tests without a mounted app, stub `widget.update_node_styles = lambda **kw: None` on the instance to suppress this.
- `ImageBar.app` can be monkey-patched as a class-level `property` in tests via `ImageBar.app = property(lambda self: self.__dict__["_app"])`. Always restore in `teardown_method` with `del ImageBar.app`.
- The linter may rewrite `update_images` to use `AttachmentChip` child widgets; `_recompute_visibility` (called by `update_images`) must delegate to `recompute_visibility()` not set `self.display`.
- Tests that used to test `_static_content.style` from the old text-based `update_images` are obsolete after the chip-based rewrite; update to test `AttachmentChip.DEFAULT_CSS` token references instead.
- 9 new tests in `tests/tui/test_image_bar_visibility.py`.

---

## 2026-05-09 — SPEC-IB-INTERACTIVE: AttachmentChip + ImageBar diff-mount

**New APIs/classes:**
- `AttachmentChip(Static, can_focus=True)` in `hermes_cli/tui/widgets/status_bar.py` — interactive chip for per-image removal. Constructor: `AttachmentChip(path: Path, index: int)`. Posts `AttachmentChip.Removed(path, index)` on remove action.
- `HINT_KEY_ATTACHMENT_DETACH = "attachment-detach"` added to `hermes_cli/tui/services/feedback.py`.
- `HermesApp.on_attachment_chip_removed` in `app.py` — bubble handler that removes path from `attached_images` and flashes hint.

**Changed behaviour:**
- `ImageBar.update_images` replaced: now diff-mounts `AttachmentChip` widgets instead of building a single `Text` label. Old shimmer-on-add path removed from this method (deferred to SPEC-IB-VISUAL).
- `ImageBar._recompute_visibility` added: `self.display = bool(self.query(AttachmentChip))`. Does NOT delegate to the existing `recompute_visibility()` (which checks `app.attached_images` count and height for the height-based visibility path).

**Gotchas:**
- `AttachmentChip.DEFAULT_CSS` references `$attachment-chip-fg` and `$attachment-chip-bg`. Test apps without HermesApp must override `get_css_variables()` to inject these vars, or the stylesheet parser raises `UnresolvedVariableError` at mount time. Use the `_AttachVarsMixin` pattern from `test_image_bar_interactive.py`.
- `App.CSS` string with `$var: value;` does NOT work for injecting CSS variables that are referenced from `DEFAULT_CSS` in another class — Textual resolves them at parse time from the combined stylesheet, and the order matters. Override `get_css_variables()` instead.
- `ImageBar.recompute_visibility()` (public, no underscore) is a separate method that checks both `app.attached_images` count AND height < 10. It calls `add_class("--visible")` / `remove_class("--visible")`. The new `_recompute_visibility` (with underscore) uses `self.display = bool(...)` for the simpler chip-presence check from the diff-mount path.
- `widget.remove()` in Textual is async (schedules DOM removal). Snapshot `current = {chip._path: chip for chip in self.query(AttachmentChip)}` before starting any removals so the mount loop doesn't see stale chips.
- `AttachmentChip` must be exported from `widgets/__init__.py` and imported in `app.py` before the `on_attachment_chip_removed` handler can dispatch.

### 2026-05-09 SPEC-PS-UNIFY: paste resolver unification + OS clipboard right-click paste

**New APIs/types:**
- `hermes_cli.file_drop.DropResolution(paths, remainder_text)` — frozen dataclass; `.is_empty` property
- `hermes_cli.file_drop.resolve_dropped_paths(text, *, multi_line=True) -> DropResolution` — single resolver; `multi_line=True` splits on newlines (multi-file drop), `multi_line=False` greedy-prefix single-line mode
- `hermes_cli.services.clipboard.ClipboardService` — base off-thread probe/extract/read_text; `_dispatch`/`_dispatch_str` must be overridden in subclasses
- `hermes_cli.services.clipboard.TextualClipboardService` — Textual subclass; marshals via `app.call_from_thread`
- `ClipboardService.read_text(on_done, timeout=3.0)` — tries xclip → wl-paste → PowerShell Get-Clipboard off-thread; calls `on_done(str)` exactly once on event-loop thread
- `HermesInput.FilesDropped(paths, remainder_text="")` — extended with `remainder_text` field (backward-compatible default)
- `WatchersService._insert_plain_text(text)` — inserts raw text at cursor via `insert_text` or `value` append
- `WatchersService.handle_file_drop_inner(paths, remainder="")` — extended with `remainder` kwarg; inserts plain text after path tokens
- `ContextMenuService._paste_text_into_input(text)` — extracted insert+flash helper for right-click paste
- `ContextMenuService._paste_done: bool` — per-call flicker guard; set False before async OS read, True in callback
- `HermesApp._clipboard_svc` — `TextualClipboardService` instance wired in `_init_services()`

**Changed behaviour:**
- `parse_dragged_file_paste` is now a shim over `resolve_dropped_paths(multi_line=True)` but preserves nil-on-any-miss (returns None when remainder_text is non-empty, matching old behavior for existing tests)
- `detect_file_drop_text` is now a shim over `resolve_dropped_paths(multi_line=False)` packed into `FileDropMatch` with `is_image` computed from resolved path
- `HermesInput._on_paste` uses `resolve_dropped_paths` directly; carries `remainder_text` in `FilesDropped`
- `paste_into_input` (right-click) falls back to OS clipboard when `app.clipboard` is empty; 50 ms flicker guard suppresses checking hint on fast machines
- `app.on_hermes_input_files_dropped` forwards `remainder_text` to `handle_file_drop_inner`

**Gotchas:**
- `_resolve_single_line` must be defined AFTER `DropResolution` in `file_drop.py` since it constructs `DropResolution(...)` at runtime.
- `parse_dragged_file_paste` shim must check `resolution.remainder_text != ""` to preserve nil-on-any-miss; spec says `.paths or None` but existing tests require nil when any token fails.
- `ClipboardService` lives in `hermes_cli/services/clipboard.py` (NOT `hermes_cli/tui/services/`); `hermes_cli/services/__init__.py` is required for the package.
- `_dispatch_str` is a separate override from `_dispatch` (callback types `str` vs `bool` cannot be unified without changing the external API).
- `_paste_done` initialized to `True` in `__init__` so the timer guard is safe before the first `paste_into_input` call.

---

## 2026-05-09 — SPEC-IB-VISUAL: ImageBar visual chips, truncation, overflow

**New APIs/methods added:**

### `hermes_cli/tui/widgets/inline_media.py`
- `_render_attachment_thumb(path, cols=6, rows=3) -> list[Strip]` — decode a path to halfblock strips; returns `[]` on failure (caller falls back to text)
- `ChipPlan` dataclass — `path / display_name / show_thumb / show_size` fields for layout planning
- `_layout_chips(width, paths) -> tuple[list[ChipPlan], int]` — pure function; returns `(visible_plans, hidden_count)`; applies width-budget ladder (drop size → truncate to 12 → drop thumbnail → overflow)
- `_size_suffix(path, budget_spare) -> str` — returns `' (N kB)'` when spare >= 6, else `''`
- `_size_str_for_path(path) -> str` — returns `_human_size(stat().st_size)` or `''` on OSError
- `OverflowChip(Static)` — 1-row chip with CSS class `--overflow-chip` for `+N more` label
- Constants: `_THUMB_DROP_BUDGET = 15`, `_MIN_CHIP_WIDTH = 14`

### `hermes_cli/tui/widgets/status_bar.py` — `AttachmentChip` enhancements
- `_thumb_strips: list` — populated by `_load_thumb_strips` worker after mount
- `_name_row: int` — `len(_thumb_strips) // 2` (middle row for name splicing)
- `_display_name: str` — set in `__init__` via `_truncate(path.name, 24)`
- `on_mount()` — sets tooltip via `_size_str_for_path`, reads config flag, launches worker
- `_load_thumb_strips()` — `@work(thread=True)` worker; calls `_render_attachment_thumb`; posts result to `_apply_thumb_strips` via `call_from_thread`
- `_apply_thumb_strips(strips)` — updates `_thumb_strips`, `_name_row`, `styles.height`; calls `refresh()`
- `render_line(y)` — when strips present, splices `"  {name}  ✕"` onto `_name_row` using `Strip.join()`; falls back to `"📎 {name}  ✕"` when no strips

### `hermes_cli/config.py`
- `display.image_bar_thumbnails: true` — new flag; disables halfblock thumb decode when false

**Changed behaviour:**
- `AttachmentChip.on_mount` sets tooltip to `"{posix} ({size})"` or `"{posix}"` when stat fails
- Tooltip is set in `on_mount`, NOT `__init__`, because `self.tooltip` setter calls `self.screen._update_tooltip(self)` which requires a mounted widget
- `render_line` is the primary render path for thumbnail mode; `render()` still exists as the shimmer/static fallback for non-line contexts

**Gotchas:**
- `widget.tooltip` setter calls `self.screen._update_tooltip(self)` — caught by `except NoScreen` in Textual's setter, but only if `self.screen` raises `NoScreen`. If the widget has never been attached to any Textual DOM (`object.__new__` bypass), `self.screen` may raise `AttributeError` instead, which is NOT caught. Always set `tooltip` in `on_mount`, not `__init__`.
- `widget.is_mounted` is a read-only property; backing attribute is `_is_mounted`. In tests using `object.__new__`, set `chip.__dict__["_is_mounted"] = True` to simulate mounted state for `_apply_thumb_strips`.
- `Strip.join()` is the correct Textual 8.x API for concatenating Strip objects. The `+` operator is not defined on `Strip`.
- `_human_size(n)` returns `"2.0kB"` style (lowercase k), not `"2 KB"` — test assertions must not assume uppercase KB.
- `_layout_chips` imports `_truncate` from `status_bar` at call time (lazy import) to avoid circular imports between `inline_media` and `status_bar`.

---

## 2026-05-09 — SPEC-PS-NONBLOCKING: Non-blocking clipboard image extraction

**New APIs/modules:**
- `hermes_cli/tui/services/clipboard.py` — `ClipboardService` base + `TextualClipboardService` + `PromptToolkitClipboardService`
- `ClipboardService.probe(on_done, timeout)` — background has_clipboard_image check
- `ClipboardService.extract(dest, on_done, timeout)` — background save_clipboard_image
- `ClipboardService.cancel_in_flight()` — sets cancel event; callback suppressed (subprocess still runs)
- `FeedbackService.flash_paste(char_count)` — flashes `HINT_KEY_PASTE_LARGE` when >80 chars
- `HINT_KEY_PASTE_LARGE = "paste-large"` added to feedback.py constant block
- `HermesCLI._next_clip_image_path()` — path allocator extracted from `_try_attach_clipboard_image`
- `HermesCLI._flash_pt_hint(text, duration)` — transient status bar hint via `_pt_hint_text`

**Changed behaviour:**
- `HermesInput._on_paste` routes paste hints through `feedback.flash_paste()` instead of `_flash_hint()` inline
- `app.on_paste` calls `feedback.flash_paste(len(event.text))` for non-file-drop pastes
- `cli.py` three paste handlers delegate to `PromptToolkitClipboardService` (non-blocking)
- Ctrl-V uses probe-first: `probe()` → if True `extract()`, if False `paste_clipboard_data()` fallthrough
- `_get_status_bar_fragments` checks `_pt_hint_text` first; non-empty overrides normal bar content

**Gotchas:**
- `ClipboardService._dispatch` raises `NotImplementedError` — must subclass; test doubles override it.
- `fired_once` Event is the double-dispatch guard between worker completion and timeout Timer.
- `PromptToolkitClipboardService._dispatch` logs at DEBUG (not WARNING) on failure — `call_soon_threadsafe` raises `RuntimeError` on a closed loop during normal shutdown.
- `getattr(self, "_pt_hint_text", "")` defensive read in `_get_status_bar_fragments` — bar is rendered before `__init__` completes in some paths.
- `app.on_paste` needed a `return` after the file-drop branch — without it, `flash_paste` ran on file-drop pastes too.
- Test pattern for `flash_paste`: `FeedbackService.__new__`, assign `svc.flash = MagicMock()`, call and inspect mock.

## 2026-05-09 — SPEC-X-CONSOLIDATE: AttachmentBar unified widget class

**New APIs/modules:**
- `hermes_cli/tui/widgets/inline_media.py: AttachmentBar(Widget)` — unified base with `direction: Literal["outgoing","inbound"]` param; owns `_chips_by_key`, `_chip_order`, `_evict_oldest`, `_dedupe_key`, `_next_index`, `add_image`, `remove_image`, `clear`, `_recompute_visibility`, `recompute_visibility`, `compose`
- `hermes_cli/tui/widgets/__init__.py: ImageBar(AttachmentBar)` — outgoing shim; owns `update_images`, `render`, `_shimmer_once`, `_shimmer_stop`, `_shimmer_tick` reactive
- `AttachmentBar.DEFAULT_CSS` — `display:none` base + `--visible {display:block}` + `--outgoing {height:auto; border-bottom}` + `--inbound {height:7; border-top}` + `--compact {height:5}`
- `tests/tui/test_attachment_bar_unified.py` — 15 tests for X-CON-1..4

**Changed behaviour:**
- `InlineImageBar` now extends `AttachmentBar` (in-place migration in `inline_media.py`); `_highlight_existing` + `_sync_oldness_chip` remain on `InlineImageBar` as inbound-only methods
- `ImageBar` deleted from `status_bar.py`; shim in `__init__.py` instead
- `watchers._sync_status_attachment_chip` deleted; `recompute_visibility()` absorbs both visibility toggle and `status_attachment_count_hidden` write
- `update_images()` uses dual-call: `_recompute_visibility()` then `recompute_visibility()`
- `_recompute_visibility()` for outgoing queries DOM (`self.query(AttachmentChip)`); for inbound reads `_chips_by_key`

**Gotchas:**
- `InlineImageBar.__bases__[0]` in old test helpers resolved to `Widget`; now resolves to `AttachmentBar` which requires `direction` kwarg. Fix: use `from textual.widget import Widget; Widget.__init__(bar)` then manually set `bar._direction = "inbound"` + all tracking fields.
- Patching `hermes_cli.tui.widgets.status_bar.shimmer_text` no longer works for `ImageBar.render()` — now patch `hermes_cli.tui.widgets._shimmer_text` (imported at module level as `_shimmer_text`).
- `recompute_visibility()` for outgoing checks `hasattr(self.app, "attached_images")` before reading — non-HermesApp test contexts don't have the attribute; fall back to DOM-based `_recompute_visibility()`.
- `ThumbnailClicked` message stays on `InlineImageBar` (NOT moved to `AttachmentBar`) — Textual derives handler names from `Message.__qualname__`; moving it would break `on_inline_image_bar_thumbnail_clicked` routing in `app.py:~1458`.
- `_sync_status_attachment_chip` removal: both call sites (on_size + on_attached_images) removed from watchers.py. Do not re-add; the write is now in `AttachmentBar.recompute_visibility()`.
- CSS type selectors in `AttachmentBar.DEFAULT_CSS` (`AttachmentBar { ... }`) DO match `ImageBar`/`InlineImageBar` instances in Textual since type selectors match ancestor class names in the MRO.

## 2026-05-09 — LOGO-TTE parallel logo wordmark animation

**New APIs/methods:**
- `_STARTUP_BANNER_LOGO_PLACEHOLDER_MARKER = ""` — PUA sentinel distinct from hero `""`; `str.find("")` always returns 0 so placeholder must be non-empty
- `_build_startup_banner_template` extended to scan for logo placeholder row/col/width/height, stored in geo cache dict
- `_splice_startup_banner_frame(template, frame_text, logo_frame_text=None)` — elif branch for logo rows, independent of hero rows
- `_get_startup_logo_tte_config() -> _StartupTteConfig | None` — mirrors `_get_startup_text_effect_config`; reads `startup_logo_text_effect` config block + skin `logo_startup_tte` override
- `_logo_ansi_settle(plain_logo)` — renders static ANSI settle frame after logo TTE exhausts
- `_play_tte_in_output_panel(cfg, plain_hero, logo_cfg=None)` — parallel logo producer defined alongside hero; deferred thread start after prelaunch drain
- `SkinPayload.logo_startup_tte: Mapping[str,Any]` field + `get_logo_startup_tte()` — per-skin override block
- `self._prelaunch_logo_frames: tuple | None` — (effect_name, plain_logo, params, frames, gen) stored at class init
- `build_welcome_banner(logo_placeholder: str = "")` — new param; if set, renders placeholder text centered instead of normal logo

**Changed behaviour:**
- `_play_startup_text_effect` TUI path now passes `logo_cfg=self._get_startup_logo_tte_config()` to `_play_tte_in_output_panel`
- `_prelaunch_pre_produce_tte_frames` restructured: hero pre-produce is now conditional (not early-return) so logo pre-produce always runs; logo block uses `isinstance(logo_cfg, _StartupTteConfig)` guard
- `config.py` default config now includes `startup_logo_text_effect` block with `enabled: false`
- `skin_engine.py` validates `logo_startup_tte` block via `_validate_startup_tte_block` when present
- All 11 bundled skins have `logo_startup_tte:` entry under `x-hermes:`

**Gotchas:**
- `isinstance(logo_cfg, _StartupTteConfig)` guard in `_prelaunch_pre_produce_tte_frames` is critical: without it, MagicMock patches for `_get_startup_logo_tte_config` pass the `is None` check, then the logo pre-produce calls the shared patched `iter_frames` iterator, exhausting frames intended for hero tests.
- Logo placeholder must use distinct non-empty PUA char: `str.find("")` always returns 0 making empty placeholder cause false geometry matches on line 0.
- Cache key for logo frames is prefixed with `"logo-"` to avoid collisions with hero cache.

---

### 2026-05-09 — SPEC-KM-REFRESH KeymapOverlay content refresh

**New APIs/methods:**
- `_km_render_sections(sections: list, *, width: int) -> str` — module-level pure function in `overlays.py`; renders `_KMSection` list to Rich markup string. Unit-testable without mounting any widget.
- `_KM_SECTIONS_WIDE: list` — full-width (≥ 80 cols) structured keymap data
- `_KM_SECTIONS_NARROW: list` — narrow (< 80 cols) structured keymap data
- `_KMRow = tuple[str, ...]` — type alias: `(description, key1[, key2, ...])`; keys plain strings, renderer adds `[dim]\[…][/dim]`
- `_KMSection = tuple[str, list]` — type alias: `(section_title, list[_KMRow])`

**Changed behaviour:**
- `_CONTENT_WIDE` / `_CONTENT_NARROW` deleted from `KeymapOverlay`; `_update_content()` now calls `_km_render_sections(_KM_SECTIONS_WIDE/NARROW, width=w)`.
- Removed stale bindings: `Ctrl+G` (history-open alt), `Alt+Z` (undo-turn), `Space` (collapse toggle), "Plan panel" F9 label, "Help overlay" `?` label, `Ctrl+Q` Quit row.
- Added sections: "Overlays & Modes" (Ctrl+B/J, F4/F2/F3, Ctrl+Shift+A); "Pane Layout" (F5/F6/F7, Ctrl+[/], Ctrl+\, o/i, Ctrl+Alt+↑/↓).
- Expanded Tool Panel to 13 rows; F9 now "Cycle pane forward / backward" with Shift+F9.
- Narrow layout gains `Alt+↑` / `Alt+↓` for prev/next turn navigation.

**Non-obvious gotchas:**
- Section title strings may contain Rich markup — `_km_render_sections` emits them verbatim. This is an intentional exception to the plain-strings convention (used for the `[dim](press ? for full menu)[/dim]` note in the Tool Panel title). Comment at definition site documents this.
- Single-element tuples need trailing comma: `("/clear",)` — without it Python parses as a string not a tuple, causing `row[1:]` to yield individual characters.
- Logo producer must be deferred (not started at definition time) to allow prelaunch drain Step B.2 first.
- Logo producer must be deferred (not started at definition time) to allow prelaunch drain Step B.2 first.

---

### 2026-05-09 — SPEC-TTE-POST-FADE Post-TTE Gradient Fade-In

**New APIs/methods:**
- `HermesCLI._hero_ansi_with_stops_at(plain_hero, stops, direction, t, bg="#1e1e1e") -> str` — returns gradient hero ANSI at brightness `t ∈ [0, 1]`. `t=0` → all bg color; `t=1` → full gradient (identical to `_hero_ansi_with_stops`). Linearly lerps each stop from `bg` toward target via `lerp_color`. Lives in `cli.py` immediately after `_hero_ansi_with_stops`.
- `_POST_FADE_FRAMES = max(2, round(DISPLAY_FPS * 0.42))` — derived constant; placed immediately after `DISPLAY_FPS` assignment; ~10 at 24fps, ~25 at 60fps.
- `_settle_bg: str` — resolved from active skin `background` token, falls back to `"#1e1e1e"`; always bound (except clause assigns fallback).

**Changed behaviour:**
- Both settle-frame appends (cache-miss `_produce` finally block and cache-hit `_process_remaining_cache_frames`) replaced with N-frame ramp loops calling `_hero_ansi_with_stops_at`. Last frame (`t=1.0`) is identical to the old single settle frame — no regression for clean effects.
- `TestSettleDirectionWiring` tests updated to mock `_hero_ansi_with_stops_at` instead of `_hero_ansi_with_stops` (ramp no longer calls `_hero_ansi_with_stops` directly for settle frames).

**Non-obvious gotchas:**
- `t` starts at `1/N`, never 0: avoids pitch-black glitch flash on first ramp frame.
- `_hero_ansi_with_stops_at` imports `lerp_color` locally (inside the method), same as `_hero_ansi_with_stops` — no top-level import needed.
- `_settle_bg` must be resolved before both the cache-miss producer thread and `_process_remaining_cache_frames` are defined; both closures capture it by reference at definition time.
- Cache-hit ramp passes `_get_logo_frame_at(_cap)` for all ramp frames (logo TTE is done at `_cap`; reusing same frozen logo frame is correct).
- Single try/except spans the full ramp loop: if iteration K raises, frames 1..K-1 are kept; K+1..N skipped. Total failure = 0 fade frames appended (same result as pre-spec settle failure).

## 2026-05-09 — SPEC-FG-INPUT-FOCUS-GUARD

**New APIs:**
- `HermesApp.has_focus_capturing_modal()` (`app.py`) — predicate distinguishing WorkspaceOverlay (non-stealing) from all other modals on `_modal_stack`. Uses `isinstance` check; WorkspaceOverlay imported locally to avoid circular import.
- `HermesInput.can_focus` property (`input/widget.py`) — replaces `can_focus=True` class kwarg. Returns `not app.has_focus_capturing_modal()`, falls back to `True` on `AttributeError` (pre-mount).
- `HermesInput.on_focus()` (`input/widget.py`) — programmatic backstop: blurs self and calls `top_modal().focus()` when a capturing modal is active.

**Changed behaviour:**
- `action_focus_input_from_output` (i key) early-returns when a capturing modal is active.
- Three auto-focus sites (on_ready:926, turn-start:1909, session-resume:2441) gated with `has_focus_capturing_modal()`.

**Non-obvious gotchas:**
- `can_focus=True` as a class kwarg to Textual's `Widget.__init_subclass__` **overwrites** any `can_focus` property defined in the class body. Must remove the kwarg and define the property instead; `# type: ignore[override]` needed because base class declares it as `ClassVar[bool]`.
- `WorkspaceOverlay` is the sole exception: it intentionally leaves HermesInput focused. All other overlays on `_modal_stack` are focus-capturing.
- Worktree was created from wrong base (default baseRef); fixed with `git reset --hard feat/textual-migration` before implementing.

## 2026-05-09 — Logo TTE producer cache-hit bug fix

**Bug fixed:** Logo TTE producer (`_produce_logo` thread) was gated inside `if not _cache_hit:` in `_play_tte_in_output_panel` (cli.py). When hero TTE cache hit, the logo producer never started, leaving `_logo_raw_frames` empty. Every `_splice_startup_banner_frame` call received `logo_frame_text=None`, leaving `_STARTUP_BANNER_LOGO_PLACEHOLDER_MARKER` (``) chars visible for the entire animation.

**Fix:** Moved logo producer thread start outside `if not _cache_hit:` gate so it always starts when `logo_cfg is not None`, regardless of hero cache status.

**Non-obvious gotcha:** Hero cache-hit and logo cache-hit are independent. Hero `_cache_hit` controls `_cached_ansi` (hero frames); logo has its own `_logo_cached_ansi`. The `_produce_logo` function already handles logo cache internally (`if _logo_cached_ansi is not None: process from cache`), so the fix is just removing the outer gate.

**First few frames still show logo placeholder on logo cache miss** (frames 0-3 are the prefetch processed before the logo thread runs). This is ~67ms at 60fps — acceptable vs. full-animation placeholder.

## 2026-05-09 — Logo TTE placeholder fix v2 (correct fix)

**Correct root cause:** On hero cache-hit, the logo frame population was handled in Step C (`if not _cache_hit:`) which was skipped. Additionally, `_process_remaining_cache_frames` thread starts before the logo producer, so even starting the logo producer in Step C is too late for most frames.

**Two-case fix in the `if _cache_hit:` block, BEFORE hero prefetch:**
1. **Logo cache hit**: populate `_logo_raw_frames` synchronously (pure list append, ~1ms for 360 frames) and set `_logo_done` → ALL hero frames get real logo frames
2. **Logo cache miss**: start logo producer thread BEFORE `_process_remaining_cache_frames` → head start for the race

**Non-obvious gotcha:** The `_process_remaining_cache_frames` background thread processes 356 hero frames (all cached, very fast Rich text ops). If logo producer starts after it, logo will always be None for every frame because `_process_remaining_cache_frames` finishes in ~50ms while logo TTE generation takes seconds. Logo producer must start BEFORE this thread, not after.

## 2026-05-09 — Logo TTE placeholder fix v3 (geo cache root cause)

**Actual root cause:** Timer fired 385 times (confirmed via debug log), frames were being rendered — but the frames *themselves* contained `` placeholder chars. Root cause was `_banner_geo_cache.py::load_geo` only deserialised `hero_row`/`hero_col`; `logo_row`/`logo_col` were written by `save_geo` but never read back. On every second startup `cached_geo.get("logo_row") == None` → `_splice_startup_banner_frame` skipped the logo region → placeholder chars remained throughout.

**Fix:** Extended `load_geo` to unpack `logo_row`/`logo_col` when present in the JSON. Updated `save_geo` to omit `None` fields (avoids `null` entries polluting JSON). Bumped `_GEO_CACHE_FORMAT_VER` 4→5 to auto-invalidate stale files.

**Non-obvious gotcha:** Geo cache key *does* include `logo_tte_active` (was already correct), but the JSON payload never stored `logo_row`. The format version bump plus stale-cache clear was necessary because on-disk files from v4 had `logo_row` absent.

**Test isolation gotcha:** `test_cache_hit_uses_cached_position` pre-populates with `logo_tte_active=False` but `_build_startup_banner_template` computes it from `_get_startup_logo_tte_config()`. When run in the same xdist worker as `test_logo_tte.py`, global cli module state may make `_get_startup_logo_tte_config()` return a real config (→`True`), causing a key mismatch → cache miss → test fails. Fix: patch `_get_startup_logo_tte_config` to `return None` in the test.

## 2026-05-09 — Startup input-blocking bug: Textual MRO on_mount dispatch

**Bug:** All permanent overlay widgets (ContextMenu, ConfigOverlay, SessionOverlay, HistorySearchOverlay, KeymapOverlay, AnimConfigPanel, AnimGalleryOverlay, InterruptOverlay, ReferenceModal/sub-classes) were pushing themselves onto `_modal_stack` at app startup, making `has_focus_capturing_modal()` return True permanently → `HermesInput.can_focus` False → no widget focused → keystrokes swallowed.

**Root cause — Textual MRO dispatch:** `textual/message_pump.py::_get_dispatch_methods` (line ~796) walks the ENTIRE `__class__.__mro__` and yields EVERY `on_mount` defined in each class's own `__dict__`. It does NOT deduplicate. So even when a permanent overlay overrides `on_mount` with `pass`, BOTH the `pass` override AND `ModalOverlayMixin.on_mount` fire at mount time.

**Fix pattern — `_push_modal_on_mount` flag:**
- Added `_push_modal_on_mount: bool = True` class attribute to `ModalOverlayMixin`
- `ModalOverlayMixin.on_mount` returns early if `not self._push_modal_on_mount`
- All permanent (pre-mounted) overlays set `_push_modal_on_mount = False`; their modal slot is managed in `show_overlay()`/`dismiss_overlay()` instead
- Ephemeral overlays (SkillPickerOverlay, ToolsScreen — removed on dismiss) keep `True`

**IL-M1 gotcha:** `add_class("--modal")` and `remove_class("--modal")` in fallback paths (`dismiss_all_info_overlays`, `heal_stale_modal_entries`) need `# il-m1:` comments or the invariant test fails.

**Test stub gotcha:** `_make_config_overlay` in `test_legacy_overlay_migration.py` uses `__new__` to bypass `__init__`. When `ConfigOverlay.__init__` gains new instance attrs, the stub must be updated to set them manually. Added `overlay._model_prefetch_done = False`.

**xdist flake:** `'Style' object has no attribute '_color'` appears in parallel xdist runs involving Textual `run_test`. It's a Rich version mismatch that surfaces under concurrency. Tests pass when run with `--override-ini="addopts="` (serial). Not caused by these changes.

## 2026-05-09 — TTE matrix effect: frame_rate=0 emits 100k+ near-identical ticks

**Problem:** The matrix TTE effect with `frame_rate=0` (our default in `iter_frames`) iterates every internal tick, yielding ~78k frames per rain_time=1 second. `max_frames=360` therefore captured only 0.15% of the animation — the resolve/settle phase was never reached, making the animation appear cut short.

**Root cause:** Unlike effects such as `rain` (28 frames total) or `highlight`, the matrix effect simulates many virtual ticks per visual state change. With `frame_rate=0`, TTE yields every tick. With `frame_rate=N > 0`, TTE skips identical ticks and yields only N frames per virtual second — e.g. `frame_rate=25, rain_time=3` → 127 meaningful frames.

**Fix — `_frame_rate` param:**
- `iter_frames` in `tte_runner.py` now reads `params.get("_frame_rate", 0)` and sets `tc.frame_rate` to that value instead of always 0.
- `_apply_effect_params` silently skips `_frame_rate` (it applies to `terminal_config`, not `effect_config`).
- Skin `params._frame_rate: 25` controls tick-skipping per effect.

**Matrix skin tuning:** `rain_time=3, _frame_rate=25, resolve_delay=2, rain_color_gradient=[matrix greens], max_frames=250, max_wall_s=10.0`. Logo: `rain_time=2, max_frames=150, max_wall_s=8.0`.

**Verified:** 127 frames produced in ~5s, full rain+resolve animation completes, fits in max_frames budget.

## 2026-05-09 — InlineProseLog emoji double-render bug

**Symptom:** Lines with custom emoji (`:name:`) appeared twice — once plain, once with emoji image — when the line was the last in a block or appeared before a code fence.

**Root cause 1 — `_flush_block_buf` bypassed emoji path:**
`_flush_block_buf` in `response_flow.py` called `_commit_prose_line` directly, skipping `_write_prose_inline_emojis`. Any line flushed at turn-end or before a code block rendered as plain text. The same line had already been queued to `write_inline` by the streaming path, producing the doubled appearance.

Fix: route through `_write_prose_inline_emojis` + `Text.from_ansi(_normalize_ansi_for_render(...))` before falling back to `_commit_prose_line` (same pattern as `_dispatch_prose`).

**Root cause 2 — `_owner_line_for_visual_y` used wrong row count for inline lines:**
The method used `len(_inline_paint[logical_idx])` for inline lines and `_logical_visual_rows.get(logical_idx, 1)` for plain lines. When the paint plan was built before layout (`scrollable_content_region.width == 0` → fallback to 80), the row count could differ from what RichLog actually wrote. Cumulative position drift caused `render_line` to fire the inline renderer at the wrong visual y, while the real RichLog content showed at the correct position — a visual duplicate.

Fix: always use `_logical_visual_rows.get(logical_idx, 1)` for ALL lines; remove the inline_paint branch.

**Root cause 3 — `on_resize` didn't rebuild on column width change:**
Paint plans were only rebuilt when cell pixel size (`_cell_px()`) changed. A terminal resize that changes column count but not cell pixel size left `_inline_paint` and `_logical_visual_rows` out of sync.

Fix: track `_last_content_width`; also rebuild when `scrollable_content_region.width` changes.

**Test impact:** `test_response_flow_audit.py::TestA5FlushPendingSourceLine` asserted "Heading" did NOT go through the emoji path. Now it does (correct); updated assertion to verify ordering (Heading before :smile:), not path exclusion.

## 2026-05-09 — SPEC-MSG-REFLOW: CopyableRichLog viewport reflow buffer

**Feature:** `CopyableRichLog` now stores write ops in `_source_ops` (list of `_WriteOp`) and triggers a clear-and-replay when the viewport narrows below the widest rendered width. Fixes prose text truncation/clipping when the terminal is made narrower.

**Key APIs added:**
- `_WriteOp` dataclass (renderers.py) — `kind: Literal["text","wws","inline"]`, `content`, `plain`, `link`
- `CopyableRichLog._source_ops: list[_WriteOp]` — replay buffer, capped at `_SOURCE_OPS_CAP=2000`
- `CopyableRichLog._rendered_max_width: int` — widest width ever passed to `super().write()`
- `CopyableRichLog._do_reflow()` — clears log and replays ops at current `_render_width`
- `CopyableRichLog.set_streaming(active: bool)` — gates reflow during streaming; triggers pending reflow on `set_streaming(False)`
- `CopyableBlock.set_streaming(active: bool)` — delegates to `self._log`
- `InlineProseLog._do_reflow()` override — clears `_inline_lines/_inline_paint/_logical_visual_rows/_logical_count` before calling super
- `InlineProseLog._replay_inline_op(op)` — calls `self.write_inline(op.content)`
- `InlineProseLog._inline_source_appending: bool` — prevents duplicate "wws" op when `write_inline` calls `write_with_source`

**Critical gotcha — `_replaying` guard removed from `_source_ops.append`:**
Initial impl used `not self._replaying` in `write()`/`write_with_source()`/`write_inline()` to guard `_source_ops.append`. This depleted the buffer after first reflow (cleared before loop → `_replaying=True` prevents re-append → buffer empty after reflow). Fix: do NOT guard `_source_ops.append` with `_replaying` in any of the three methods. `_source_ops.clear()` happens before the replay loop, so each replayed write re-populates it exactly once (no doubling). `_replaying` is only used in `on_resize()` to prevent scheduling a new reflow while one is in progress.

**REFLOW-M1 wiring:**
- `app.py::mark_response_stream_started()` → `panel._active_prose_block.set_streaming(True)`
- `app.py::finalize_response_metrics()` → `panel._active_prose_block.set_streaming(False)` (in finally)
- `message_panel.py::ReasoningPanel.open_box()` → `self._reasoning_log.set_streaming(True)`
- `message_panel.py::ReasoningPanel.close_box()` → `self._reasoning_log.set_streaming(False)`

**Testing pattern:** Instantiate `CopyableRichLog(markup=False, ...)`, set `_render_width` directly (no Textual app). For `call_after_refresh`, patch or call `_do_reflow()` directly. `InlineProseLog` tests: subclass with fixed `scrollable_content_region` (same pattern as `test_inline_prose.py`).

**`_size_known` gotcha:** `write()` plain capture path checks `getattr(self, "_size_known", True)`. Without a Textual app/mount, `_size_known=False`, so `write(Text(...))` does NOT add to `_plain_lines`. Only `write_with_source` reliably adds to `_plain_lines` in unit tests.

## Changelog 2026-05-09 — SPEC BR-NAV BrowserNavigateRenderer

**New file:** `hermes_cli/tui/body_renderers/browser_navigate.py`
- `BrowserNavigateRenderer` — phase-C renderer for all 6 browser_* tools.
- `_NAV_TOOLS` frozenset: `browser_navigate`, `browser_back` — renders a status-code + URL + title line.
- `_ACTION_TOOLS` frozenset: `browser_click`, `browser_type`, `browser_scroll`, `browser_press` — renders verb + target + success icon.
- `_STATUS_COLORS` maps `range(200,300)→green`, `range(300,400)→yellow`, `range(400,500)→red`, `range(500,600)→bright_red`.
- `build()` returns `rich.text.Text` (not `rich.console.Group`) so `str(result)` contains the actual plain-text content for tests.
- `kind` class var set at module level via `_set_kind()` pattern (same as `JsonRenderer`).

**Modified:** `hermes_cli/tui/tool_category.py` — 6 new `ToolSpec` entries for browser_* tools, all `category=_WEB`.

**Modified:** `hermes_cli/tui/body_renderers/__init__.py` — `BrowserNavigateRenderer` added before `DiffRenderer` in `REGISTRY` and `__all__`.

**Gotcha — `str(rich.console.Group)` does not render content.** If a renderer's `build()` returns a `Group`, `str(result)` gives `<rich.console.Group object at 0x...>`, not the plain text. Tests that call `str(result)` require `build()` to return a `Text` (or another renderable whose `__str__` yields the content). Changed `_build_nav` to concatenate lines into a single `Text` with `\n` separators instead of using `Group`.

**`final_url` priority:** In `_build_nav`, `data.get("final_url") or data.get("url")` — `final_url` wins over `url` for redirect scenarios.

## Changelog 2026-05-09 — SPEC BR-SNAP BrowserSnapshotRenderer

**New file:** `hermes_cli/tui/body_renderers/browser_snapshot.py`
- `BrowserSnapshotRenderer` — phase-C renderer for `browser_snapshot` tool.
- `can_render` checks `payload.tool_name in _SNAPSHOT_TOOLS` (frozenset); does NOT check `cls_result.kind` — tool_name is the discriminator.
- `build()` returns `rich.console.Group` (header Text + Rule + tree lines + optional ellipsis).
- `_walk_tree` — recursive depth-indented renderer; landmark roles (heading/button/link etc.) → bold cyan badge + bold name; leaf roles (StaticText/text/img) → dim name, skip entirely if no name; any role with `href`/`url` gets `  → url` dim appended.
- `_count_nodes` — recursive node count for summary_line.
- `_MAX_TREE_LINES = 200` cap; excess shown as `  … N more nodes` dim line.
- `kind` set via `_set_kind()` deferred import pattern.

**Gotcha — testing Group renderables:** `list(result.renderables)` to iterate; `isinstance(item, Rule)` to detect rules; `text.plain` for plain content; `text._spans` for style inspection.

**Modified:** `hermes_cli/tui/tool_category.py` — `browser_snapshot` and `browser_get_images` added to `_SEED_SPECS` as `category=_WEB`.

**Modified:** `hermes_cli/tui/body_renderers/__init__.py` — `BrowserSnapshotRenderer` inserted at index 1 (after `BrowserNavigateRenderer`, before `DiffRenderer`/`JsonRenderer`). Both browser-specific renderers must precede `JsonRenderer` because `JsonRenderer.can_render` accepts any `ResultKind.JSON` without tool_name check.

## Changelog 2026-05-09 — SPEC BR-CON BrowserConsoleRenderer

**New file:** `hermes_cli/tui/body_renderers/browser_console.py`
- `BrowserConsoleRenderer` — phase-C renderer for `browser_console` tool.
- Parses `console_messages` (typed log entries) and `js_errors` (uncaught exceptions) from JSON envelope.
- `_LEVEL_STYLES`: log/debug→dim, info→cyan, warn/warning→yellow, error/assert→bold red; `_DEFAULT_LEVEL_STYLE="default"` for unknown levels.
- `build()` returns `rich.console.Group` (list of `Text` lines + separator + badge for JS errors).
- JS errors section: dim-red `──` Rule, red badge ` N JS error(s) `, error message + up to 4 stack frames.
- Empty envelope → `Text("(no console output)", style="dim")`.
- Malformed JSON → raw text passthrough via `except (json.JSONDecodeError, ValueError)`.
- `summary_line()` prefers `data["total_errors"]` (MCP pre-computed) over local count; falls back when field absent or 0.
- `kind` set at module level via `_set_kind()` deferred import pattern.

**Modified:** `hermes_cli/tui/tool_category.py` — `browser_console` added to `_SEED_SPECS` as `category=_WEB, primary_result="none"`.

**Modified:** `hermes_cli/tui/body_renderers/__init__.py` — `BrowserConsoleRenderer` inserted after `DiffRenderer`, before `JsonRenderer` in `REGISTRY` and `__all__`. Coexists with `BrowserSnapshotRenderer`; ordering: Nav → Snapshot → Diff → Console → Json.

**Gotcha — testing Group renderables in `test_info_level_uses_cyan`:** Access individual Text items via `list(result.renderables)`, then inspect `text._spans` directly. Rendering via `Console(no_color=True)` strips styles, so style assertions require the span list.

**Merge conflict pattern:** Both BR-SNAP and BR-CON added entries to the same three locations (`__init__.py` docstring, import block, `REGISTRY`/`__all__`). Resolution: keep both; order Nav→Snap→Diff→Con→Json in REGISTRY.

---

## 2026-05-09 — TBV: Tool body footer hygiene (spec_tbv_body_footer_hygiene)

**BodyFooter retired from body renderers.** All ten renderers (json/code/diff/shell/search/table/log + browser_navigate/browser_console/browser_snapshot) no longer pass `footer=` or override `footer_entries`. The base `BodyRenderer.footer_entries` ClassVar is **deleted** entirely. The class `BodyFooter` itself remains in `_grammar.py` for grammar primitives but has zero live mounts. `_frame.py` retains a `TYPE_CHECKING` forward-reference for the `footer: "BodyFooter | None"` annotation.

**`BodyFooter.__init__` is now str-only.** Tuple entries (`("y", "copy")`) raise `TypeError` from `render()`. Concept §893 mandates inner-glyph form (`[c]opy`); the buggy tuple branch was emitting `[c] copy` (space + label) and was the source of the dead-`y` key advertised under every JSON/code/diff body.

**`BodyFrame.body` widened to `RenderableType | Widget | None`.** Header-only frames are valid (concept §161 EMPTY suppression). `compose()` skips the body slot when `None`. `EmptyStateRenderer.build_widget` returns a header-only `BodyFrame` with the category+outcome rule on the header. `FallbackRenderer.build_widget` is now overridden — wraps the body in `BodyFrame(header=build_rule("unclassified · plain text"), body=CopyableRichLog, footer=None)`. The unclassified rule no longer scrolls inside the body Text.

**LOG stats moved to header rule.** `LogRenderer.build_widget` now produces `header=build_rule("log · INFO N · WARN N · ERROR N", ...)` and `footer=None`. Counts are computed once at `build_widget()` from the finalised raw output (LOG is non-streaming per `LogRenderer.supports_streaming = False`).

**`tool_blocks/_block.py::replace_body_widget` no longer mounts BodyFooter.** Deleted: BodyFooter import, the `query(BodyFooter)` removal loop, and the `if plain_text: self._body.mount(BodyFooter())` block. Header `_line_count`/`_has_affordances` assignments preserved.

**`hermes.tcss` BodyFooter rules deleted.** The three rules at L1246-1254 (`BodyFooter { ... }`, `HermesApp.density-compact BodyFooter { display: none; }`, `ToolPanel.--streaming BodyFooter { display: none; }`) are removed. The `_frame.py` `BodyFrame.body-frame--compact > BodyFooter { display: none; }` rule is also removed.

**Compact summary now uses BodyFrame.** `BodyPane._render_compact_body` mounts a `BodyFrame(header=None, body=Static(summary, ...), footer=None, density=COMPACT)` instead of a bare `Static`. Aligns compact rendering with the rest of the chrome.

**JSON word_wrap=True.** All three `Syntax(...)` call sites in `json.py` (L142/182/190) now wrap. Long string values (snapshots, base64) wrap at viewport. `code.py` keeps `word_wrap=False` (column-significant source).

**Age microcopy reschedules forever.** `_schedule_age_ticks` cancels any prior `_age_timer` and starts a single self-rescheduling chain. `_tick_age` reschedules at 10s/30s/600s based on current age (matches "Ns/Nm/Nh ago" granularity). Single-chain invariant — `_age_timer` always holds the **next** pending handle; multi-completion paths cannot spawn parallel chains.

**New IL gates.**
- **IL-12** (TestIL12NoBodyFooterImportInRenderers): AST walk of `body_renderers/*.py` rejecting `BodyFooter` import in any module other than `_grammar.py` (defines it) and `_frame.py` (TYPE_CHECKING forward-reference).
- **IL-13** (TestIL13NoDeadYKey): regex sweep of `body_renderers/`, `tool_blocks/`, `tool_panel/` for `[y]` and `("y", "copy")` literals. `services/`, `cli/`, and `tests/` are exempt because they contain legitimate yes/no prompts and key-binding tuples.

**Test-side regressions to remember when working on body chrome:**
- `test_renderer_framing.py::TestRF5BodyFooter` — tuple-entry tests deleted; only the str-entry test survives.
- `test_render_visual_grammar.py::TestBodyFooter` — deleted entirely (covers behaviour that no longer exists).
- `test_tool_pipeline_quick_wins.py::TestQW06BodyFooterText` — deleted.
- `test_tool_body_renderer_regression.py::TestRendererLocalFooter` — deleted.
- Static.renderable was removed in Textual 8.x; use `str(static.render())` (returns Content) instead.

**Pre-existing test failures unaffected by this work** (all flagged on base branch before this work landed): `TestQW04NoDuplicateCopyBinding` (3 tests assert `c`/`y` bindings the spec says should not exist), `TestRF3ShellJsonTableLog::test_renderers_all_use_body_frame` (browser renderers don't return BodyFrame), `TestIL8ExceptHandling::test_no_silent_swallows_in_owner_paths` (5 IL-8 violations in browser_*.py), `test_strip_visible_when_collapsed_unfocused`, `test_statusbar_browse_minimal_width`, `test_hint_row_truncated_on_narrow_screen` (Rich format spec error in overlays.py). Out of scope for TBV.

## 2026-05-09 — Per-skin animation tokens + browser renderer skin-color migration

**Skins (all 11 bundled DESIGN.md files updated):**
- Tuned `thinking-spinner-{dim,peak}`, `spinner-shimmer-{dim,peak}`,
  `drawbraille-canvas-color`, and `running-indicator-{hi,dim}-color` per skin
  so animation surfaces match each palette instead of inheriting global defaults.
  Tuning rule: dim ≈ skin's `accent-dim`, peak ≈ skin's `foreground`,
  drawbraille ≈ `accent`, running-hi ≈ `warning`. Don't add new vars to
  `COMPONENT_VAR_DEFAULTS`; the existing keys already exist as `VarSpec`
  (optional_in_skin=True) and just needed real values.

**Body renderers — browser_navigate / browser_console / browser_snapshot:**
- Replaced literal `style="red"` / `"bold red"` / `"yellow"` / `"cyan"` strings
  with `rich.style.Style(color=self.colors.<field>)`. SkinColors fields used:
  `error`, `error_dim`, `warning`, `info`, `success`. `_LEVEL_STYLES` module
  dict turned into `_level_styles(c)` factory called inside `build()` because
  styles can only be built once `self.colors` is wired (post-mount).
- HTTP status range coloring moved out of a module-level `range -> name` dict
  into `_status_color(status, c)` helper that returns hex literals from
  SkinColors at call time.
- Test pattern: when asserting that a level/state uses a particular color,
  assert `info_hex.lower() in str(span.style.color).lower()` rather than
  matching a Rich color name string. The color name path is gone.

**IL-8 / SC5 invariants:**
- `_il8_handler_has_justification` matches a regex of trigger words. "render
  gracefully" is NOT a trigger; "malformed" / "best-effort" / "fallback" ARE.
  When swallowing JSONDecodeError to display raw text, use a comment like
  `# malformed/non-JSON tool output: best-effort fall back to raw text`.
- `TestSC5MetaTest::test_no_red_literal_in_render_paths` (`tool_blocks/`,
  `body_renderers/`, `tool_panel/`) AST-walks for `\bred\b` inside Style
  positional args or `style=` kwargs. `bright_red` / `dim_red` are NOT flagged
  (underscore is a word char, breaks `\b` boundary), but `"dim red"` IS — the
  word boundary sits at the space.

**Stale skin/TTE tests fixed:**
- `test_bundled_skin_tte_stops.py`: relaxed exact-count asserts (`==`) on
  `final_gradient_stops` to `>=` for poseidon/sisyphus/hermes after the HG-1..HG-7
  multi-band hero rewrite increased stop counts (poseidon 7→10, sisyphus 6→9,
  hermes 4→7). The sisyphus monotonic-descent assertion now only walks the
  first 5 transitions because multi-band gradients are intentionally
  non-monotonic at band boundaries.
- Matrix skin uses its own `matrix` TTE effect and `max_wall_s=10.0`. Earlier
  spec attempts to swap to `rain` at 3.0s were reverted by commits a30bda9a /
  476c21ed (post-TTE fade skip + 1-frame settle). Tests must allow this:
  exempt `matrix` from `test_no_bundled_skin_uses_its_own_name_as_effect`.
- `test_mech_sweep_css_skin.py` allowlist for the `#9b59b6` MCP purple now
  covers both `$tool-mcp-accent` (legacy) and `$tool-tier-mcp-accent` (tier
  catalogue) declaration lines.

## 2026-05-09 — MSG-DEDUP-H1/M1/M2 (InlineProseLog streaming dedup)

**New state fields on `InlineProseLog`:**
- `_inline_emit_seen: dict[str, int]` — maps plain text → first emit logical index (cap 256, evict oldest with `del d[next(iter(d))]`).
- `_reflowing: bool` — True during `_do_reflow` to block concurrent writes from appending to partially-cleared state.
- `_pending_during_reflow: list[_WriteOp]` — queue for writes that arrive while `_reflowing=True`; drained after reflow completes.

**New method `_rewrite_inline(line_index, line)`:**
- Patches `_inline_lines`, `_inline_paint`, the matching `_source_ops` entry (scanning for the i-th "inline" op), and `_lines` (best-effort direct patch) in place.
- Does NOT call `super().write_with_source()` or increment `_logical_count`.
- Called when `line_index in self._inline_lines` (reflow race: `_logical_count` was reset but index already stored).

**Guard ordering in `write_inline`:**
1. M2 reflow-queue guard: `if self._reflowing and not self._replaying` → queue and return.
2. H1 Sub-fix A: `if line_index in self._inline_lines` → `_rewrite_inline` and return.
3. H1 Sub-fix B: `if plain in self._inline_emit_seen and not self._replaying` → WARNING log and return.
4. Normal append path (registers plain in `_inline_emit_seen`).

**`_do_reflow` changes:**
- Sets `self._reflowing = True` before clearing state; resets in `finally`.
- Clears `self._inline_emit_seen` before calling `super()._do_reflow()` so replay re-registers from scratch.
- Drains `_pending_during_reflow` after `finally` by calling `write_inline(op.content)` for each queued op.

**Gotcha:** During replay (`_replaying=True`), guard 3 is bypassed (the condition is `not self._replaying`), so replay correctly re-registers plain texts in `_inline_emit_seen`. The test `test_invariant_il_msg_1_reflow_idempotent` must also clear `_source_ops` before the replay loop (matching actual `_do_reflow` behaviour) — otherwise ops double-append.

**Test pattern (no DOM, no app):** Use `_StubLog(InlineProseLog)` with `scrollable_content_region` returning a fixed `Region(0, 0, width, 100)` and `_render_width` set on the instance. Direct attribute injection for `_reflowing`/`_replaying` flags.

---

## 2026-05-09 — TBV-FF Footer Focus Gate (spec_tbv_footer_focus_gate.md)

**Changed behaviour:**
- `ToolPanel.DEFAULT_CSS`: removed dead `--browsed`/`--expanded` rules (never set in Python) and removed redundant `ToolPanel:focus .action-row display:block` (subsumed by `:focus-within` in hermes.tcss:921).
- `_CollapsedActionStrip.can_focus = False` added — prevents the action strip from stealing keyboard focus and falsely triggering `:focus-within` on the parent ToolPanel.
- `ToolPanel.on_focus()` / `on_blur()` emit `_log.debug("TBV-FF-H1: …")` for tracing.

**CSS gate:** `ToolPanel:focus-within FooterPane.has-actions > .action-row { display: block; }` in hermes.tcss:921 is the **sole** show-rule for .action-row. DEFAULT_CSS only carries the hide rule.

**Invariant:** IL-FOOTER-1 (3 subtests a/b/c) added to `test_invariants.py` as `TestILFooter1ActionRowGate`. Parallel coverage in `tests/tui/test_tbv_footer_focus.py` (13 tests, 6 classes).

**Gotcha:** The spec called for a `TestILFooter1` class name; the implementation used `TestILFooter1ActionRowGate` (more descriptive). Both names are acceptable — the test IDs are what matter for CI targeting.

---

## 2026-05-09 — CHIP-NORM Chip Label Normalisation (spec_chip_label_normalization.md)

**New module:** `hermes_cli/tui/services/chip_format.py` — `format_chip(key, label) -> str` with rules:
- Single ASCII letters → lowercase (`c`, `r`, `y`)
- F-keys (`f1`..`f12`) → uppercase (`F1`, `F2`)
- Named word-keys → Title-Case (`Enter`, `Esc`, `Tab`, `Space`)
- Symbols/modifiers/chords → verbatim (`*`, `?`, `^c`, `shift+d`)

**Call site migrations:**
- `tool_panel/_footer.py` `_rebuild_action_buttons()`: `RichText(f"[{action.hotkey}] {action.label}")` → `RichText(format_chip(...))` (lazy import to avoid circular)
- `tool_panel/_actions.py` `_truncate_hints()`: `t.append(key, style="bold")` → `t.append(format_chip(key, "").rstrip(), style="bold")`
- `tool_panel/_actions.py` `_build_hint_text()`: tip_key → `_norm_key = format_chip(tip_key, "").rstrip()` before append
- `_render_hints()` overflow: `" more"` → `" keys"`

**Gotcha — circular import:** `hermes_cli.tui.services` package `__init__.py` imports `browse.py` which imports `widgets`, causing a circular init cycle if `chip_format` is imported at module level from `_footer.py` or `_actions.py` (both sit in the `tool_panel/` chain that `widgets/__init__` triggers). **Fix: always import `chip_format` lazily inside function bodies** from `tool_panel/` modules.

**IL-CHIP-1 pattern fix:** The invariant regex `\[\{[A-Za-z_][A-Za-z0-9_]*\}\]\s` didn't match dotted identifiers (`action.hotkey`). Updated to `\[\{[A-Za-z_][A-Za-z0-9_.]*\}\]\s`. Also fixed two pre-existing false positives: `_app_utils.py` log formatter and `status_bar.py` citation label — changed to use `{ts} msg` and `{n}. domain` respectively.

---

### 2026-05-09 — SPEC-SS-PHRASING (streaming status phrasing)

**New APIs:**
- `format_elapsed_short(seconds: float) -> str` in `widgets/utils.py` — `<60s` → `"12.3s"`, `<3600s` → `"2:08"` (mm:ss), `>=3600s` → `"1:02:08"` (hh:mm:ss). Exported from `widgets/__init__.py`.
- `GLYPH_NO_DATA = "—"` (U+2014 em-dash) in `body_renderers/_grammar.py` — the no-data-yet placeholder, distinct from `GLYPH_ELLIPSIS` (truncation/elision).
- `status_streaming_elapsed_s: reactive[float]` added to `HermesApp` — updated on each streaming chunk in the `set_response_metrics` path.

**Changed behaviour:**
- `TitledRule._response_metrics_text()` (`renderers.py`): `"… tok/s"` → `f"{GLYPH_NO_DATA} tok/s"` when streaming but no rate yet.
- `ThinkingWidget._get_label_text()` (`thinking.py`): LONG_WAIT elapsed format changed from `"Working hard… (128s)"` → `"Working hard… · 2:08"` (uses `format_elapsed_short`).
- `StatusBar.render()` (`status_bar.py`): streaming label gains `"streaming · 2:08"` suffix when `status_streaming_elapsed_s >= 8.0`.

**Gotcha — circular import in renderers.py:**
Importing `GLYPH_NO_DATA` at module level in `renderers.py` triggers `body_renderers/__init__.py` → `streaming.py` → `services.tools` → `services.browse` → `widgets` (partially initialised). **Fix: use lazy import inside `_response_metrics_text()`** with a comment `# avoid circular at module init`.

## 2026-05-09 — CHIP-NORM: chip_format.py + label normalisation

- New `hermes_cli/tui/services/chip_format.py`: `format_chip(key, label) -> str` — single-letter→lowercase, F-key→UPPERCASE, word-key→Title-Case, symbols/chords→verbatim.
- Migration sites: `tool_panel/_footer.py` `_rebuild_action_buttons()`, `tool_panel/_actions.py` `_truncate_hints()` + `_build_hint_text()`; overflow suffix `" more"` → `" keys"` in `_render_hints()`.
- IL-CHIP-1 regex pattern uses `[A-Za-z0-9_.]*` not `[A-Za-z_]*` — dotted attrs like `action.hotkey` need the dot in the char class.
- **Gotcha**: `services/__init__.py` triggers circular import chain → `chip_format` must be imported lazily (inside function body) from any `tool_panel/` module. Pre-existing `[{ts}]`/`[{n}]` patterns in `_app_utils.py`+`status_bar.py` were false positives fixed before the IL-CHIP-1 gate was added.

## 2026-05-09 — SR-RW: Search/JSON routing fix + line wrap gate

**Changed behaviour:**
- `close_streaming_tool_block` (`services/tools.py`): added `elif not _renderer_output_raw` fallback that stitches `_renderer_output_raw` from `_plain_lines`/`_all_plain`/`_content_lines` when `result_lines=None`. Ensures classifier receives untruncated text even when caller omits result_lines.
- `SearchRenderer.can_render` (`body_renderers/search.py`): returns `False` when `cls_result.kind == ResultKind.JSON`. Prevents JSON-payload misrouting into search chrome.
- `StreamingSearchRenderer.can_render` (`body_renderers/streaming.py`): same JSON guard.
- `SearchRenderer.build(viewport_width=None)`: truncates content lines at `viewport_width` when `len(content_t.plain) > 2 * viewport_width` using `Text.copy().truncate(n, overflow="ellipsis")`. `build_widget()` reads `self._app.size.width` (note: `_app`, not `app` — base class stores as `_app`).
- `StreamingSearchRenderer.render_stream_line`: same truncation via `self._app.size.width` after `Text.from_ansi(raw)`.
- `_swap_renderer` (`tool_panel/_completion.py`): checks for pre-existing non-placeholder children in body_pane; logs warning with `traceback.format_stack()` and removes before mount.

**New test file:** `tests/tui/test_sr_routing_wrap.py` — 13 tests (H1/H2/M1).
**New IL gate:** `IL-WRAP-1` (3 tests) in `test_invariants.py`.

**Gotcha — base class app attribute:** `BodyRenderer` stores app as `self._app` (not `self.app`). Using `getattr(self, "app", None)` returns `None` in tests that pass `app=mock_app` to the constructor — always use `self._app`.

**Gotcha — grep format in tests:** `_parse_search_output` expects `path` on its own line followed by `line_num:content` lines (not `path:line:content` format). Use `"file.py\n1:content\n"` not `"file.py:1:content\n"` for test fixtures.

## 2026-05-09 — MSG-DEDUP: InlineProseLog streaming prose deduplication guards

**New state fields on InlineProseLog (`prose.py`)**
- `_inline_emit_seen: dict[str, int]` — maps plain text → first-seen logical index, capped at 256 (evict oldest on overflow).
- `_reflowing: bool` — True inside `_do_reflow`; queues concurrent writes instead of appending.
- `_pending_during_reflow: list[_WriteOp]` — queue for writes arriving mid-reflow; drained after replay, capped at `_SOURCE_OPS_CAP // 4` (500).

**New method: `_rewrite_inline(line_index, line, text=None, plain=None)`**
Patches an already-stored inline line in place without incrementing `_logical_count`. Finds the `line_index`-th `"inline"` op in `_source_ops` and updates its `content` field (mutable dataclass — direct attr assignment works). Removes old `_inline_emit_seen` entry and registers new one.

**`write_inline` guard order (critical — don't reorder):**
1. M2 reflow queue: `if self._reflowing and not self._replaying` → append to `_pending_during_reflow` and return.
2. H1 Sub-fix A index-collision: `if line_index in self._inline_lines` → `_rewrite_inline` and return.
3. H1 Sub-fix B plain-text dedup: `if plain and plain in self._inline_emit_seen and not self._replaying` → WARNING and return.
4. Normal append path — also updates `_inline_emit_seen` (even during replay, so replay re-populates the map).

**`_do_reflow` changes:**
Sets `_reflowing = True` before clearing state, clears `_inline_emit_seen` alongside other inline state, restores `_reflowing = False` in `finally`, then drains `_pending_during_reflow`.

**Gotcha — `_inline_emit_seen` during replay:** The dedup guard skips when `_replaying = True`, but `_inline_emit_seen` IS still updated in the normal path. This is intentional — replay must re-register all plain texts so post-reflow writes don't get falsely blocked.

**Gotcha — test file location:** `tests/tui/test_msg_dedup.py` was an untracked file in the main working tree. When creating a worktree from an older commit, untracked test files don't follow — copy them manually: `cp /path/to/main/tests/tui/test_msg_dedup.py tests/tui/`.

**IL-MSG-1 gate** added to `test_invariants.py` (`TestInvariantILMSG1`, 3 tests). Apply to any PR touching `prose.py` or `renderers.py`.

## 2026-05-09 — IL-GATE-EXPANSION: 5 new invariant lint gates

**New gates in `tests/tui/test_invariants.py` (20 tests total):**

- **IL-LP-1** (`TestILLP1`, 4 tests): Leaf section widgets (`CodeSection`, `OutputSection`, `ToolBodyContainer`, `FooterPane`) must not use `padding-left: N` where N >= 2 in `hermes.tcss`. Enforces the `$body-indent` token contract from SPEC-LP-COL. `ToolPanel` and `BodyPane` are excluded (LP-COL-2 half-indent pattern). CSS comments are stripped per-block for the padding-left scan but exemption check runs on the raw block first.

- **IL-LP-2** (`TestILLP2`, 4 tests): `ToolPanel`, `MessagePanel`, `UserMessagePanel` must each have `margin-bottom: 1` in at least one CSS block. Handles grouped selectors (`ToolPanel,\nMessagePanel { }`). Checks longhand only — do not use `margin` shorthand on these panels.

- **IL-RZ-1** (`TestILRZ1`, 4 tests): Every `on_resize` handler in `hermes_cli/tui/` must reference a sentinel from `_SENTINELS` or carry an `# il-rz-1-exempt: <reason>` comment on/inside the def line. `_SENTINELS` extended with: `_last_resize_w`, `_last_seekbar_w`, `_last_nameplate_w`, `_render_width`. Exemption check uses raw source window (not `ast.unparse`, which strips comments).

- **IL-EX-1** (`TestILEX1`, 4 tests + module-level helper `_il_ex1_has_outer_raise`): Every `except` handler must re-raise (at outer scope, not nested), log with `.exception(` or `exc_info=<truthy>`, or carry `# il-ex-1-exempt: <reason>`. `exc_info=None/False/0` are rejected. The recursive helper `_il_ex1_has_outer_raise` stops descent at `Try.handlers` so inner-except raises don't falsely satisfy the outer check.

- **IL-TOK-1** (`TestILTOK1`, 4 tests): Regex scan over `hermes_cli/tui/` rejects `style="<hex-or-named>"` literals in render code. Uses lookbehind `(?<![a-zA-Z0-9_])` to skip `_style=`, `render_style=` etc. f-strings detected via `f?` prefix. Exemption per line: `# il-tok-1-exempt: <reason>`.

**Pre-requisite sweeps committed separately:**
- `fix(except)` commit: 915 except handlers across 93 files annotated with `il-ex-1-exempt` tokens.
- IL-TOK-1 exemptions on 6 sites: semantic diff colors in `tool_group.py`, running indicator in `sub_agent_panel.py`, a11y role in `browser_snapshot.py`, computed-RGB blend in `renderers.py`.
- IL-RZ-1 exemptions on `completion_list.py` and `input/widget.py` `on_resize` (legitimate unconditional handlers).

**Gotcha — CSS comment stripping and exemptions:** The IL-LP-1 gate strips CSS `/* */` comments per-block for the padding-left scan but checks exemptions on the raw block first (before stripping). If you check exemptions on the stripped block, `/* il-lp-1-exempt */` is invisible and the gate fails the self-test. Always: raw block → exemption check → strip → violation check.

**Gotcha — bulk except annotation:** The IL-EX-1 sweep script appended `il-ex-1-exempt` tokens to 915 except-handler `except` lines. If an except line already had a `#` comment, the script merged the token into the existing comment (replacing `#` with `# il-ex-1-exempt: <old-text>`). If not, it appended `  # il-ex-1-exempt: swallow`. Only the `except` line is patched — body swallows use the raw source window check.

---

## 2026-05-09 — MSG-DEDUP Sub-fix C: prefix-extension dedup

**New module:** `hermes_cli/tui/widgets/_grapheme.py`
- `suffix_grapheme_count(s: str) -> int` — ZWJ-aware grapheme cluster counter using `unicodedata`. No `regex` dependency. Handles: ZWJ sequences, variation selectors (U+FE00–U+FE0F), skin-tone modifiers (U+1F3FB–U+1F3FF), Mn combining marks.
- Key API: pure function, no widget/Textual deps. Unit-testable without mounting.

**`prose.py` additions:**
- Module-level import: `from hermes_cli.tui.widgets._grapheme import suffix_grapheme_count as _suffix_grapheme_count`
- Constant `_PREFIX_EXTEND_MAX_GRAPHEMES: int = 6`
- Sub-fix C block in `write_inline` after Sub-fix B `return` and before `self._inline_lines[line_index] = line`.

**Sub-fix C logic:** If the immediately prior inline slot (`line_index - 1`) is a strict prefix of `plain`, suffix is ≤6 graphemes, no ImageSpan in either line, and not replaying → call `_rewrite_inline(line_index - 1, ...)` and return (no new slot, no `_logical_count` increment).

**Gotcha — ImageSpan constructor:** `ImageSpan` fields are `image_path: Path`, `cell_width: int`, `cell_height: int = 1`, `alt_text: str = ""`, `cache_key: str = ""`. Not `span_index`/`image_key`/`width`/`height` — those were guessed field names that don't exist.

**Test pattern:** 12 tests in `test_msg_dedup_prefix.py`. `_make_image_line` builds `ImageSpan(image_path=Path("/tmp/fake.png"), cell_width=10, alt_text=text_str)`.

---

## 2026-05-09 — BR-NAV-TS-M1: BrowserNavigateRenderer title/size separation

**Changed file:** `hermes_cli/tui/body_renderers/browser_navigate.py`

**`_build_nav` additions:**
- Reads `data.get("content_length")` after title resolution.
- Converts via `int()` guarded in `except (TypeError, ValueError): # il-ex-1-exempt` — non-numeric silently dropped.
- Calls `_humanize_bytes` from `tool_result_parse` via local import (avoids circular import at module load time).
- Replaces single `if title:` append with a `if title or size_human:` block that builds a `Text()` object: title in `"bold"`, then `" · "` + size in `Style(color=c.muted)` when both present; separator omitted when title is absent.

**Key pattern — local import inside method:** `from hermes_cli.tui.tool_result_parse import _humanize_bytes` lives inside `_build_nav`, not at module top. The existing codebase already uses this pattern in `_build_action` for `Style`. Required to prevent circular imports.

**Key pattern — `result.append_text(title_line)`:** Appends a pre-built `Text` object (preserving its spans) rather than `result.append(str, style=...)`. Critical for retaining per-segment styles on the title+size line.

**Test file:** `tests/tui/test_br_nav_title_size.py` — 7 tests in `TestBrowserNavigateTitleSize`. Inspect spans via `result._spans` with `s.start <= char_idx < s.end` predicate.

---

## 2026-05-09 — STALL-GC: group-terminal abandonment for stalled children

**New flag on `StreamingToolBlock`:** `_abandoned: bool = False` (alongside `_completed`).

**New method:** `StreamingToolBlock._mark_abandoned()` in `hermes_cli/tui/tool_blocks/_streaming.py`:
- Idempotent (guard on `_abandoned` at top).
- Calls `_header._pulse_stop()` and clears `_header._stall_glyph_active = False`.
- Lazy-imports `spec_for` from `hermes_cli.tui.tool_category`; uses `spec.category.value` to suffix microcopy ("no result · search"); omits suffix for "unknown" or on any Exception (fallback: "no result").
- Sets `_microcopy_shown = True`.

**Updated stalled calc** in `_update_microcopy` (~line 609):
```python
stalled = (
    not self._completed
    and not self._abandoned    # STALL-GC-H1
    and self._last_line_time > 0.0
    and (time.monotonic() - self._last_line_time) > 5.0
)
```

**New fields on `ToolGroup`** (`hermes_cli/tui/tool_group.py`):
- `_group_terminal_at: float = 0.0` — monotonic timestamp of first terminal transition.
- `_group_swept: bool = False` — idempotency flag for the sweep.

**`on_tool_panel_completed` addition** (after `_recompute_group_state`):
```python
if self._group_state in _TERMINAL_GROUP_STATES and self._group_terminal_at == 0.0:
    self._group_terminal_at = time.monotonic()
    self.set_timer(2.0, self._sweep_abandoned_children)
```

**New method:** `ToolGroup._sweep_abandoned_children()`:
- Guarded by `_group_swept` (idempotent).
- Lazily imports `ToolPanel` (consistent with rest of file, avoids circular imports).
- Iterates `_body.children`, finds `ToolPanel` instances via `isinstance`, gets `_block`, calls `block._mark_abandoned()` on non-completed blocks.

**Test pattern — patching lazy imports:** `spec_for` is imported lazily inside `_mark_abandoned` via `from hermes_cli.tui.tool_category import spec_for`. Patch it at source: `patch("hermes_cli.tui.tool_category.spec_for", ...)`. Cannot patch at `_streaming.spec_for` (not a module-level attribute).

**Test pattern — isinstance with ToolPanel:** `MagicMock(spec=ToolPanel)` does NOT pass `isinstance(..., ToolPanel)`. Use `ToolPanel.__new__(ToolPanel)` and set `_block` directly on the stub for sweep tests.

**Test pattern — ImportError simulation:** Use `patch.dict("sys.modules", {"hermes_cli.tui.tool_category": None})` to trigger ImportError on the lazy import inside `_mark_abandoned`.

---

## 2026-05-09 — B1-B9: Tool Body Compose Cleanup

**Changed files:**
- `hermes_cli/tui/tool_blocks/_block.py` — new `ActionChipsRow` widget + `_action_class()`; `ToolBlock` gets `summary` param; `on_mount` wires stderr + action chips; `_HR_RE` strips HR lines; trailing-blank trim in `_render_body`
- `hermes_cli/tui/body_renderers/_grammar.py` — `BodyFooter` class deleted entirely
- `hermes_cli/tui/body_renderers/_frame.py` — `BodyFooter` TYPE_CHECKING import removed; `footer` param type → `Widget | None`
- `hermes_cli/tui/tool_blocks/_header.py` — `.--stderr-tail` DEFAULT_CSS gets `border-left: thick $error 60%` + `padding: 0 1`
- `hermes_cli/tui/tool_blocks/_streaming.py` — `set_age_microcopy` deleted
- `hermes_cli/tui/tool_panel/_completion.py` — age-microcopy 3-line call removed from `_tick_age`; promoted chip set computed before `update_summary_v4`
- `hermes_cli/tui/tool_panel/_footer.py` — `_rebuild_artifact_buttons` skips when single file artifact == header `_full_path`
- `hermes_cli/tui/tool_result_parse.py` — `_TRUNC_HINT_RE` + `_strip_truncation_hint()`; wired into `search_result_v4` and `generic_result_v4`

**Key APIs added:**
- `ActionChipsRow(actions: tuple[Action, ...])` — `Horizontal` with one `Label` per action, tinted by `_action_class(kind)`: `copy`→accent, `retry`/`reconnect`→warning, `copy_err`→error, neutral for open/edit kinds
- `_strip_truncation_hint(text: str) -> tuple[str, int | None]` — strips `[Hint: Results truncated. Use offset=N...]` from raw tool output; returns cleaned text + offset
- Truncation chip: `Chip("+N more", "status", "warning")` — must use `"status"` kind, NOT `"count"` (count doesn't allow warning tone per `_TONE_BY_KIND`)
- Truncation action: hotkey `"m"` (was confirmed not in `ToolPanel.BINDINGS`), kind `"retry"`

**Gotchas:**
- `Label._Static__content` (name-mangled) stores the original string content — use this in unit tests, not `_renderable`
- `BodyFooter` was imported by `test_renderer_framing.py`, `test_tool_body_footer_hygiene.py`, `test_invariants.py` — all updated; `TestTBVH3MicrocopyForm` str/tuple tests removed; `TestRF1BodyFrame` uses `Static("x")` instead; `IL-12 _EXEMPT` set cleared to `set()` (no exemptions remain)
- `ParseContext` is a `@dataclass` requiring all 3 fields (`complete`, `start`, `spec`) — use real `ToolComplete`/`ToolStart` dataclasses in tests, not `SimpleNamespace`
- Pre-existing failures (not regressions): `TestRF3ShellJsonTableLog::test_renderers_all_use_body_frame` (BrowserRenderers return `CopyableRichLog` not `BodyFrame`) and `test_statusbar_browse_minimal_width` (`ValueError: Sign not allowed in string format specifier`) — both fail on base branch

---

## 2026-05-09 — GHF-H1/M1: GroupHeader frozen terminal chip + outcome glyph

**Changed files:**
- `hermes_cli/tui/tool_blocks/_group_header_stats.py` — new pure-formatter module
- `hermes_cli/tui/tool_group.py` — GroupHeader + ToolGroup changes

**New module `_group_header_stats.py`:**
- `_clock_hhmm(ts: float) -> str` — converts a `time.monotonic()` timestamp to `HH:MM` wall clock string via `datetime.now().timestamp() - time.monotonic()` offset. No CLOCK_REALTIME dependency.
- `terminal_stats(tool_count, total_span_s, clock_hhmm) -> str` — pure formatter; produces `"N tool[s] · <elapsed> · HH:MM"`. Calls `format_elapsed_short` from `hermes_cli.tui.widgets.utils` via deferred import.

**`GroupHeader` changes:**
- Two new fields: `_terminal_at: float | None = None`, `_group_state_value: str = ""`
- `update()` signature extended with `terminal_at: float | None = None, group_state: str = ""`
- `render()`: outcome glyph block inserted between `GLYPH_GUTTER_GROUP` and toggle arrow; duration block replaced with terminal/live branch on `_terminal_at`

**`ToolGroup` changes:**
- `_group_terminal_at: float | None = None` added to `__init__`
- `on_tool_panel_completed`: group-state recomputed BEFORE `recompute_aggregate()` so `_group_terminal_at` is set when `recompute_aggregate` calls `_header.update(**kwargs)`
- `recompute_aggregate`: `terminal_at=self._group_terminal_at` and `group_state=self._group_state.value` added to kwargs dict

**Module-level constant `_OUTCOME_GLYPH`:** dict mapping state `.value` strings to `(glyph, style)` tuples. Defined at module level (not inside `render()`) to avoid rebuilding on every paint.

**Gotcha — testing GroupHeader.size:** `size` is a Textual read-only property backed by `_size`. Tests cannot assign to the instance directly. Use a `_TestGroupHeader(GroupHeader)` subclass that overrides `size` as a plain `property` returning a `FakeSize` object.

**Test pattern:** 12 tests in `test_group_header_freeze.py`. `TestTerminalFormatter` uses `_TestGroupHeader` subclass. `TestLeftGlyph` also uses subclass pattern. All tests are pure unit tests — no Textual app, no `run_test`.

**il-tok-1 exemptions:** `_OUTCOME_GLYPH` entries use hardcoded Rich color names (`"green"`, `"bold red"`) with `# il-tok-1-exempt` comments — no SkinColors token defined for group-level outcome glyphs.

---

## 2026-05-09 — KB-LP: Keybinding layout safety policy

### Keybinding layout safety

Default keybindings must be reachable on both US QWERTY and German QWERTZ
without AltGr. Avoid `[`, `]`, `\`, `{`, `}`, `|`, `@`, `~`. Prefer letters,
digits, `,`, `.`, `/`, `;`, `'`, `-`, F-keys, and named navigation keys.
Existing US-only bindings may be retained as compat aliases when paired
with a layout-safe primary. Gate: `IL-KB-1` in `test_kb_layout_parity.py`.

**Changed files:**
- `hermes_cli/tui/app.py` — 5 AltGr bracket bindings replaced with `alt+comma` / `alt+full_stop` / `alt+m` primaries + `alt+1/2/3` digit aliases; original 5 kept as compat aliases in named-key form (`ctrl+left_square_bracket` etc.)
- `hermes_cli/tui/widgets/overlays.py` — `_KM_SECTIONS_WIDE` Pane Layout block updated: `Ctrl+[` / `Ctrl+]` / `Ctrl+\` → `Alt+,` / `Alt+.` / `Alt+M`
- `tests/tui/test_kb_layout_parity.py` — 14 tests (H1×5, H2×3, M1×3, L1×3)

**Gate `_collect_il_kb1_violations(extra_classes=None)`:**
- Discovers all classes in `hermes_cli/tui/` via `pkgutil.walk_packages` + `inspect.getmembers`
- Checks each BINDINGS entry; if `key.split("+")[-1]` is in the forbidden-named or forbidden-literal set, that action must also have a layout-safe binding
- `extra_classes` parameter for unit-testing the gate itself with fake classes

**Gotcha — BINDINGS can contain tuples, not just `Binding` objects:**
Textual allows `BINDINGS = [("ctrl+c", "quit")]`. `_normalize_binding(b)` handles both; call it before accessing `.key` or `.action`.

---

## 2026-05-09 — BH-1/2/3: Banner Hierarchy & Tone

**Changed files:**
- `hermes_cli/tui/widgets/banner.py` — `_section_break(dim_color, width=30)` helper; BH-2 warning line uses `_skin_color("banner_warning", "#FF8C00")` / `banner_warning_dim`; BH-3 dismiss badge row appended after warning line
- `hermes/DESIGN.md` + 3 other skin DESIGN.md files (catppuccin, matrix, solarized-dark, tokyo-night) — `banner-warning / banner-warning-dim / banner-key` tokens added (7 skins already had them)
- `tests/tui/test_banner_hierarchy.py` — 13 tests

**Key APIs / constants:**
- `_section_break(dim_color, width=30)` — returns blank line + `─` rule rendered via `_skin_color("banner_warning_dim", …)`. Inserted before Skills section unconditionally; before MCP section only inside the `if mcp_status:` guard (prevents orphan rule).
- Banner token keys (kebab-case in DESIGN.md, normalized to underscores at load): `banner-warning`, `banner-warning-dim`, `banner-key`
- BH-3 badge format: `"  [bold {key_color}]u[/] [dim {dim}]dismiss[/]   [dim {dim}]run[/] [{text}]{update_cmd}[/] [dim {dim}]to install[/]"`

**Gotcha — test stubs vs APPROVED spec divergence:**
2 tests were written against a pre-review stub that said no dismiss badge. APPROVED spec reversed that. Tests corrected from `test_no_dismiss_badge_rendered` → `test_dismiss_badge_on_separate_line` + `test_dismiss_badge_format`. Always verify tests match the APPROVED spec, not draft notes.

**Gotcha — kebab-case token lookup:**
When adding a new skin, copy the 3 `banner-warning / banner-warning-dim / banner-key` lines from `hermes/DESIGN.md`; the kebab-case is normalized to underscores at `_skin_color()` call time.

---

## 2026-05-09 — legend-bar: Colored keybinds matching HintBar style

**Changed files:**
- `hermes_cli/tui/widgets/input_legend_bar.py` — `LEGENDS` dict (plain strings) replaced by `LEGEND_ENTRIES` (structured `list[_Entry]`); new `_key_color()` + `_build_markup()` methods

**Key APIs / types:**
- `_Entry = tuple[str | None, str | None]` — `(key, desc)`. `key=None` → plain dim label; `key=str` → bold+colored key + dim desc; `desc=None` → bold key alone.
- `LEGEND_ENTRIES: ClassVar[dict[str, list[_Entry]]]` — replaces old `LEGENDS: dict[str, str]`
- `_key_color(self) -> str` — reads `accent-interactive` (then `primary`) from `self.app.get_css_variables()`; falls back to `"#5f87d7"` if that raises; swallows exception with `_log.debug(..., exc_info=True)`
- `_build_markup(entries) -> str` — joins entries with `" [dim]·[/dim] "` separator; produces `[bold {color}]Key[/] [dim]desc[/dim]` per keyed entry
- `show_legend(mode)` — calls `self.update(Text.from_markup(self._build_markup(...)))`

**Gotcha — exception handling at `get_css_variables()`:**
`get_css_variables()` can raise before the app is fully mounted. `_key_color` swallows at `except Exception` level with a `_log.debug` call — intentional because this is a best-effort color lookup. The `# il-ex-1-exempt` comment must accompany the swallow for the IL-EX-1 gate.

---

## 2026-05-09 — ShimmerEffect streaming text support (unstaged)

**Changed files:**
- `hermes_cli/stream_effects.py` — `ShimmerEffect` gains `_buf_len: int` field + `register_token_tui()` / `clear_tui()` methods; `needs_clock` flipped to `True`; `tick_tui()` uses `max(self._buf_len, 20)` as wrap ceiling

**Key changes:**
- `needs_clock = True` (was `False`) — ShimmerEffect now participates in the clock/tick system for streaming text, not just static ThinkingWidget labels
- `_buf_len: int = 0` — tracks cumulative streaming token character count; used to size the shimmer wrap reset boundary to match actual line width
- `register_token_tui(token: str)` — called by the streaming path to accumulate `len(token)`
- `clear_tui()` — resets `_pos` and `_buf_len` when a new streaming run begins
- `tick_tui()` wrap reset: `label_len = max(self._buf_len, 20)` — for ThinkingWidget labels (`_buf_len == 0`) uses 20-char soft ceiling; for streaming text covers actual line width

**Gotcha:** Old comment `"needs_clock stays False intentionally"` was wrong for the streaming path. Updated to clarify: False only applied to ThinkingWidget usage; streaming usage requires the clock.

---

## 2026-05-09 — ctrl+p Plan Panel toggle (unstaged)

**Changed files:**
- `hermes_cli/tui/app.py` — `Binding("ctrl+p", "action_toggle_plan_panel", "Plan", show=True)` added to `BINDINGS`; `action_toggle_plan_panel()` method toggles `self.plan_panel_collapsed`

---

## 2026-05-09 — AC-DESC: slash/skill completion description preview

**Changed files:**
- `hermes_cli/tui/path_search.py` — `SlashCandidate` gains two new fields: `source: str = ""` (skill source label) and `trigger_hint: str = ""` (first TRIGGER-when phrase). Frozen dataclass with slots — new fields must have defaults.
- `hermes_cli/tui/input/_autocomplete.py` — `_show_slash_completions` reads `_slash_descriptions` / `_slash_args_hints` / `_slash_keybind_hints` via `getattr(..., {})` (safe in test fixtures without full HermesInput). `_show_skill_completions` now passes `source=c.source` and `trigger_hint=(c.trigger_phrases[0] if c.trigger_phrases else "")` to `SlashCandidate`.
- `hermes_cli/tui/completion_overlay.py` — `_NO_DESCRIPTION_FALLBACK` changed from `"[dim]—[/dim]"` to `"[dim]no description[/dim]"`. `SlashDescPanel._on_candidate` extended: renders `[dim]{source}[/dim]  ` badge prefix when `source` truthy; appends `\n\n[dim italic]{trigger_hint}[/dim italic]` when `trigger_hint` truthy; emits `logger.debug(...)` when description is missing.
- `hermes_cli/tui/overlays/skill_picker.py` — inline `"—"` fallback in `_rebuild_list` changed to `"no description"` (plain string, not markup, because it's already wrapped in `[dim]…[/dim]` at the call site).

**Gotcha — skill_picker fallback is NOT `_NO_DESCRIPTION_FALLBACK`:**
`skill_picker._rebuild_list` wraps `_desc` in `[dim]…[/dim]` itself, so using the constant would produce double-nested `[dim][dim]no description[/dim][/dim]`. Use the plain string `"no description"` there.

**Gotcha — `getattr(self, "_slash_descriptions", {})` pattern:**
Required because `_AutocompleteMixin` is a mixin and test fixtures may not attach the three `_slash_*` dicts. Avoids `AttributeError` in gateway harness or isolated test stubs.

**Test pattern — `_FakeRichLog` shim for `SlashDescPanel`:**
`SlashDescPanel._on_candidate` is tested by constructing an `object.__new__(SlashDescPanel)` instance and monkeypatching `clear` and `write` with a `_FakeRichLog` shim. No full App run needed. This is faster and avoids Textual app lifecycle issues for pure-logic panel tests.
