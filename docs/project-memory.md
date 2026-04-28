# Memory Index

Memory index links use canonical absolute targets under `~/.hermes` when available; `project_*.md`, `feedback_*.md`, and `reference_*.md` are stable alias names there.

## services/feedback Audit FB-H1..FB-L2 (2026-04-28)
- [services/feedback Audit](/home/xush/.hermes/project_feedback_service_audit.md) — IMPLEMENTED 2026-04-28; equal-priority PREEMPTED, apply-failure restore + ERROR log, SUPPRESSED reason, SettledAware Protocol, CodeFooterAdapter ancestor walk, register_channel warn+cancel+reentry guard, _STATE_CHANGE_TONES; 20 new tests; 9-pass review

## Composer Concept G — APPROVED 2026-04-28
- [Composer concept G](/home/xush/.hermes/project_composer_concept.md) — APPROVED v1.0; MODE×KIND×ASSIST frame for HermesInput; 16 drift items; 7 review passes (passes 6–7 met "0 HIGH + ≤2 MED" gate); basis for upcoming UX Audit G

## Focus/Nav Spec H — IMPLEMENTED 2026-04-28
- [Focus/Nav Spec H](/home/xush/.hermes/project_focus_nav_concept.md) — IMPLEMENTED; W-1..W-17; ScrollState tri-state, --modal overlays, scroll_end_if_pinned, AT-* lint tests (13 tests)

## UX Audit D — Motion/Feedback (2026-04-28)
- [UX Audit D motion feedback](/home/xush/.hermes/project_ux_audit_d_motion_feedback.md) — IMPLEMENTED 2026-04-28; D3 universal searching label + D5 fence-open border-top cue + D6 OutputPanel Esc/Space bindings; D1/D2/D4 cut after review (no real bug; _partial_display dead code); 8 tests; commit 823895d04

## UX Audit E — Error/Edge States (2026-04-28)
- [UX Audit E error edge states](/home/xush/.hermes/project_ux_audit_e_error_edge.md) — IMPLEMENTED 2026-04-28; E1 result-empty class+italic+○-prefix + E2 minified-error height-auto override + E3 error minimal adds ⌃C + E4 KEY_* constants sweep (3 sites); 11 tests; commit cc428df73

## UX Audit F — Overlays/Polish (2026-04-28)
- [UX Audit F overlays polish](/home/xush/.hermes/project_ux_audit_f_overlays_polish.md) — IMPLEMENTED 2026-04-28; F2 countdown hint + F3 disabled badge + F4 empty-state guard + F5 border token + F6 opacity 70% + F7 focus-ring unified + F8 max-height%; 14 tests; commit 917194b2f

## Config Panel Fix CO-H1/H2/M1/L1 (2026-04-28)
- [Config Panel Fix](/home/xush/.hermes/project_config_panel_fix.md) — IMPLEMENTED 2026-04-28; focus on open + tab refresh on switch + 3 swallow logs + /syntax routing; 19 tests; commit 7630237b3

## UX Audit B — Density/Truncation (2026-04-28)
- [UX Audit B density truncation](/home/xush/.hermes/project_ux_audit_b_density_truncation.md) — IMPLEMENTED 2026-04-28; B1 _DROP_ORDER_COMPACT reorder + B2 streaming error footer + B3 skeleton env-var + B4 OmissionBar narrow label + B5 truncated linecount badge; 14 tests; commit af966de5a

## UX Audit A — Skin/Visual Hierarchy (2026-04-28)
- [UX Audit A skin hierarchy](/home/xush/.hermes/project_ux_audit_a_skin_hierarchy.md) — IMPLEMENTED 2026-04-28; A1–A6; nameplate dead anim + chevron opacity + $reasoning-accent + category tier table + $error banner + DEFAULT vocab; 12 tests; commit d72ff0c07

## R5-T-M1 ThinkingWidget default-repr leak (2026-04-28)
- [R5-T-M1 ThinkingWidget repr leak](/home/xush/.hermes/project_r5_tm1_thinking_repr_leak.md) — IMPLEMENTED 2026-04-28; render() override returning empty Text; 4 tests; commit e3382c33b

## R4-T-H1 TTE banner race — threading.Event gate (2026-04-28)
- [R4-T-H1 TTE banner race](/home/xush/.hermes/project_r4_th1_tte_banner_race.md) — IMPLEMENTED 2026-04-28; STARTUP_BANNER_READY event + wait(2s) gate + NoMatches/CancelledError narrow; 5 tests; commit 151530770

## R3-H1/M1/L1 panel.id timing + feedback channel + kitty latch (2026-04-28)
- [R3 panel.id + feedback + ks-context](/home/xush/.hermes/project_r3_fix_panel_id_feedback.md) — IMPLEMENTED 2026-04-28; panel_id kwarg fix + _move_panel_channel + on_mount guard + _ks_context fallback + kitty probe latch; 14 tests; merge f0fdf63ff

## tmux Audit Driver TM-1/TM-2 (2026-04-28)
- [tmux audit driver](/home/xush/.hermes/project_tmux_audit_driver.md) — IMPLEMENTED 2026-04-28; TmuxDriver ctx-mgr in tools/tui_audit/; real-PTY complement to Pilot; commit 10f8d3b51

## Round-2 Audit Fix R2-H1 ThinkingWidget hex-color leak (2026-04-28)
- [R2-H1 color fix](/home/xush/.hermes/project_r2h1_thinking_color_fix.md) — IMPLEMENTED 2026-04-28; _normalize_hex validator + _DEFAULT_*_HEX constants; get_css_variables() exception → WARNING + defaults reset; 6 tests; commit ad2506dd2

## Audit Followup M-1/M-2/L-1 (2026-04-28)
- [M-1/M-2/L-1 log hygiene + mount gate](/home/xush/.hermes/project_audit_followup_m1_m2_l1.md) — IMPLEMENTED 2026-04-28; on_approval_state WARNING→DEBUG + seen-guard; kitty_graphics TTY latch; mount 500ms gate; 9 tests; commit 2b5bb388c

## Live Audit Fixes H-1 + H-2 (2026-04-28)
- [H-1 + H-2 fixes](/home/xush/.hermes/project_h1_h2_audit_fixes.md) — IMPLEMENTED 2026-04-28; _spinner_timer leak + LiveLineWidget WARNING→DEBUG; 6 new tests + 3 updated; commit 7ed7c0c44

## Exception Handling Compliance Sweep EH-A..EH-E (2026-04-28)
- [EH-A..EH-E sweep](/home/xush/.hermes/project_eh_compliance_sweep.md) — IMPLEMENTED 2026-04-28; ~377 bare swallows; 59 files; 82 tests; commit 00954d743

## Perf Gaps PM-04..PM-12 (2026-04-28)
- [PM-04..PM-12](/home/xush/.hermes/project_perf_gaps_pm04_pm12.md) — IMPLEMENTED 2026-04-28; measure() auto-records to PerfRegistry; 9 probe sites across io/app/tools/widgets/streaming/drawbraille; 27 tests; commit f645f4e73

## Stream Flush Cadence Visibility (2026-04-28)
- [SF-1..SF-4](/home/xush/.hermes/project_stream_flush_cadence.md) — IMPLEMENTED 2026-04-28; [STREAM-BUF]/[STREAM-CODE]/[STREAM-FENCE]/[STREAM-SEQ] debug logs; _fence_opened_at timer; 14 tests; commit a1f97aed3

## Nameplate Sporadic Idle Beat Animation (2026-04-28)
- [NA-1..NA-3](/home/xush/.hermes/project_nameplate_idle_animation.md) — IMPLEMENTED 2026-04-28; two-phase idle timer; PULSE/SHIMMER/DECRYPT beats; auto mode; breathe→pulse alias; 20 tests; commit 6fa62cd58

## CWD Display in StatusBar (2026-04-28)
- [CWD-1..CWD-4](/home/xush/.hermes/project_cwd_statusbar.md) — IMPLEMENTED 2026-04-28; status_cwd reactive + BashService sh -c wrapping + sentinel CWD extraction + StatusBar flash; 17 tests; commit 7b365bc97

## Skill Picker Empty Description Fallback (2026-04-28)
- [Skill Picker SP-1/SP-2](/home/xush/.hermes/project_skill_picker_descriptions.md) — IMPLEMENTED 2026-04-28; [dim]—[/dim] fallback in list row + (no description) in detail pane; 6 tests; commit 2b0877709

## Chip Legend in ToolPanel Help Overlay (2026-04-28)
- [Chip Legend CL-1](/home/xush/.hermes/project_chip_legend_cl1.md) — IMPLEMENTED 2026-04-28; "Header chips" section + overflow-y scroll in ToolPanelHelpOverlay; 6 tests; commit f6d22913b

## Keystroke Log Recorder (2026-04-28)
- [Keystroke Log KL-1..KL-7](/home/xush/.hermes/project_keystroke_log_step6a.md) — IMPLEMENTED 2026-04-28; opt-in JSONL recorder; _keystroke_log.py + _ks_context() + on_key/mouse hooks + KL-7 component hooks; analyze_keystroke_log.py; 15 tests; commit db31b6c29

## Bottom Chrome Consolidation (2026-04-28)
- [Bottom Chrome Consolidation BD-1/BD-2](/home/xush/.hermes/project_bottom_chrome_consolidation.md) — IMPLEMENTED 2026-04-28; Horizontal nameplate+hintbar row, SessionBar hidden, S key, [n/m] indicator in StatusBar; 12 tests; commit 79fe2b45b

## Tools Lifecycle Hygiene (2026-04-28)
- [Tools Lifecycle Hygiene H6..L13](/home/xush/.hermes/project_tools_lifecycle_hygiene.md) — IMPLEMENTED 2026-04-28; LIFO pop, gen_index clear, snapshot lock, kind-before-state, single state read, atomic DOM-id, gen depth, reset hook; 29 tests; commit fd294f52c

## Feedback
- [Tool block subsystem done definition](/home/xush/.hermes/feedback_tool_block_done_definition.md) — 4-criterion stop-auditing gate pinned to project CLAUDE.md; supersedes "0 issues / 10/10" for this subsystem
- [TUI test scope — targeted only](/home/xush/.hermes/feedback_tui_test_scope.md) — Never run full tests/tui/ (timeouts); run only targeted new test files
- [Full TUI suite timeout](/home/xush/.hermes/feedback_full_suite_timeout.md) — Full tests/tui/ takes 16+ min; use timeout=1200000 if truly needed; prefer targeted files
- [Worktree workflow](/home/xush/.hermes/feedback_worktree_workflow.md) — Prefer worktrees for parallel/isolated work; branch from main; merge back
- [New branches must be based on main](/home/xush/.hermes/feedback_branch_base.md) — Branch from main by default; TUI work branches from feat/textual-migration
- [Specs are always .md files](/home/xush/.hermes/feedback_spec_format.md) — Global rule: specs/design docs written to disk as Markdown, not inline-only
- [Hermes specs live in /home/xush/.hermes/](/home/xush/.hermes/feedback_spec_location_hermes.md) — Parent of repo, alongside wdo.txt and existing spec .md files
- [asyncio deprecation warning fix](/home/xush/.hermes/feedback_asyncio_deprecation.md) — Use get_running_loop() not get_event_loop() in sync pytest fixtures (Python 3.10+)
- [PlanPanel test — use PENDING not RUNNING](/home/xush/.hermes/feedback_plan_panel_test_pending_state.md) — RUNNING triggers set_interval timer that blocks pilot.pause(); use PENDING instead
- [fix-tool-result-role is wontfix](/home/xush/.hermes/feedback_wontfix_tool_result_role.md) — Local /anthropic proxy mis-detected as anthropic_messages edge case — skip it, do not re-spec
- [on_focus affordances guard](/home/xush/.hermes/feedback_on_focus_affordances.md) — ToolPanel.on_focus only flashes when _has_affordances=True; tests must wire _block mock
- [Module split mutable globals](/home/xush/.hermes/feedback_module_split_mutable_globals.md) — Re-exported bool globals in __init__ are value copies; tests must target source submodule directly
- [Textual Widget.parent/.app are read-only](/home/xush/.hermes/feedback_textual_property_mock.md) — Use PropertyMock patch; Syntax._theme is object not string — capture theme= kwarg instead
- [AST sweep over grep for kwarg compliance](/home/xush/.hermes/feedback_ast_sweep_kwarg_tests.md) — Meta-tests enforcing kwarg conventions must AST-walk; line grep flags multi-line calls + method names
- [MagicMock _resolver attribute leak](/home/xush/.hermes/feedback_magicmock_resolver_leak.md) — hasattr(mock,"_resolver") always True; use getattr(...) is not None + set panel._resolver=None in tests
- [Mixin MRO conflict in widget hierarchy](/home/xush/.hermes/feedback_mixin_mro_conflict.md) — Never add a mixin to both parent and subclass; Python C3 rejects; add only at highest ancestor
- [HermesApp CSS VarSpec crash](/home/xush/.hermes/feedback_hermesapp_css_varspec_crash.md) — HermesApp.run_test() crashes with VarSpec error; use minimal App(App) for widget tests
- [staticmethod class attr binding](/home/xush/.hermes/feedback_staticmethod_class_attr.md) — @staticmethod assigned as class attr becomes instance method; wrap with staticmethod() to preserve static semantics
- [Textual Widget property test leakage](/home/xush/.hermes/feedback_widget_property_leakage.md) — PropertyMock on type(widget) leaks across pytest session; use cached _IsolatedSubclass + __class__ swap
- [xdist workers stdin fileno() raises before tcgetattr](/home/xush/.hermes/feedback_xdist_stdin_patch.md) — patch module's sys.stdin.fileno() to return 0 when testing termios paths

## Quick Wins A — Visual Polish (2026-04-27)
- [Quick Wins A — VP-1..VP-10](/home/xush/.hermes/project_quick_wins_a_visual.md) — IMPLEMENTED 2026-04-27; WRAP_CONTINUATION; …+N chip; body-frame--default; low-conf caption hint; chevron shape-stable; truncation_footer action=None; summary_line density; 19 tests; commit 517071e0d

## Quick Wins B — Footer & Header (2026-04-27)
- [Quick Wins B — FH-1..FH-8](/home/xush/.hermes/project_quick_wins_b_footer_header.md) — IMPLEMENTED 2026-04-27; hint dedup, skeleton dismiss coalesce, footer streaming gate, COMPACT accepts() for diff/table/search, OmissionBar settled gate; 19 tests; commit c9d64f58a

## Axis Bus Sweep (2026-04-27)
- [Axis Bus Sweep AB-1..AB-3](/home/xush/.hermes/project_axis_bus_sweep.md) — IMPLEMENTED 2026-04-27; kind axis clears hint; delete post-state view.is_error; watcher coverage sweep; 9 tests; commit 9786046ad

## Invariant Lint Gates (2026-04-27)
- [IL-1..IL-8 mechanical invariants](/home/xush/.hermes/project_invariant_lint_gates.md) — IMPLEMENTED 2026-04-27; tests/tui/test_invariants.py (25 tests, <2s); ToolBlock.has_partial_visible_lines() to retire IL-1 H1 site; 142 bare-except sites annotated; 9 modules got _log; per-tier drop-order tests; status-chip + microcopy + set_axis ordering gates

## ERR Cell Rule (2026-04-27)
- [ERR Cell Rule ER-1..ER-5](/home/xush/.hermes/project_err_cell_rule.md) — IMPLEMENTED 2026-04-27; ErrorCategory enum + classify_error + split_stderr_tail; 2-chip header pin; StderrTailWidget clamp-bypass; _sort_actions_for_render; _RECOVERY_BY_CATEGORY gates retry/edit_args; 31 tests; commit e8c437ee7

## Truncation Bias + Slow Renderer Fallback (2026-04-27)
- [TB-1..TB-5 truncation bias + slow renderer](/home/xush/.hermes/project_truncation_bias_slow_renderer.md) — IMPLEMENTED 2026-04-27; ClassVars + summary_line + _apply_clamp + BodyPane.apply_density + clamp_rows; 37 tests; commit 86421ff2b

## Microcopy + Confidence Surface (2026-04-27)
- [Microcopy + Confidence MC-1..MC-7](/home/xush/.hermes/project_microcopy_and_confidence.md) — IMPLEMENTED 2026-04-27; chip constants, more-rows, flash lowercase, LayoutDecision subscriber, THRESHOLDS dict, low-conf caption; 18 tests; commit b65a47ba6

## Focus Visibility + Settled State (2026-04-27)
- [Focus Visibility + Settled State FS-1..FS-3](/home/xush/.hermes/project_focus_and_settled.md) — IMPLEMENTED 2026-04-27; › prefix + tier gutter glyphs + 600ms settled suppression; 15 tests; commit 64086b808

## Streaming Skeleton + KIND Hint Defensive Clear (2026-04-27)
- [Streaming Skeleton SK-1/SK-2](/home/xush/.hermes/project_streaming_skeleton_sk1_sk2.md) — IMPLEMENTED 2026-04-27; 100ms skeleton row + header-side hint clear on terminal state; 13 tests; branch worktree-streaming-skeleton

## Reference
- [TUI load-bearing facts](/home/xush/.hermes/reference_tui_facts.md) — Textual 8.2.3 stable; API gotchas, typed state protocol, bounded queue
- [Textual 8.x impl gotchas](/home/xush/.hermes/reference_textual_impl_gotchas.md) — 55+ gotchas: ReasoningFlowEngine missing fields, SimpleNamespace property limitation, + all prior
- [TCSS custom variable declaration gotcha](/home/xush/.hermes/reference_tcss_variable_gotcha.md) — New $var-name refs MUST be declared in .tcss file; get_css_variables() alone insufficient at parse time
- [PathSearchProvider → HermesInput routing](/home/xush/.hermes/reference_path_search_routing.md) — siblings can't bubble; App-level relay required; tests that set inp.value trigger real walker
- [Textual mount() anchor resolution gotcha](/home/xush/.hermes/reference_textual_mount_order.md) — before=other resolves to other.parent not self; silently mounts into wrong container
- [OutputPanel mount order contract](/home/xush/.hermes/reference_output_panel_mount_order.md) — all dynamic content uses before=tool_pending; trio [ToolPendingLine, ThinkingWidget, LiveLineWidget] always last; 12 tests
- [Rich v15 upgrade](/home/xush/.hermes/reference_rich_v15.md) — upgraded from 14.2→15.0.0; ANSI newline fix, FileProxy.isatty fix; pin updated to >=15.0.0,<16
- [rtk pytest output suppression](/home/xush/.hermes/reference_rtk_pytest.md) — rtk-ai/rtk swallows pytest output; fix: --override-ini="addopts="
- [TUI dev skill](/home/xush/.hermes/hermes-agent/skills/tui-development/SKILL.md) — Widget patterns, thread safety, testing, CSS theming, Textual 8.x gotchas
- [Hermes skin skill + reference](/home/xush/.hermes/reference_hermes_skin_skill.md) — ~/.claude/skills/hermes-skin/SKILL.md; skin-reference.md is canonical; checklist for new component vars
- [TUI mixin structure + R4 services](/home/xush/.hermes/reference_tui_mixin_structure.md) — MRO, services/ subpackage, adapter pattern, _flash_hint exception, deleted files
- [Transferable components from local codebases](/home/xush/.hermes/transferable_components.md) — Tier 1–3 audit of ai-agent-dev-dumbeddown, ai-orchestrator, ai-orchestrator2 with port effort + gotchas
- [Tool block 3-axis concept](/home/xush/.hermes/reference_tool_block_concept.md) — PHASE×KIND×DENSITY + SkinColors vocab; docs/concept.md; 3 consolidation specs implied

## Lifecycle Legibility (2026-04-26)
- [Lifecycle Legibility LL-1..LL-6](/home/xush/.hermes/project_lifecycle_legibility.md) — IMPLEMENTED 2026-04-26; density flash + completing chip + error-expanded class + RendererKind cycle + adoption flash + ToolCallHeader phase chips; 38 tests; commit 48b55cf23

## Tool Call Discoverability (2026-04-26)
- [Tool Call Discoverability DC-1..DC-4](/home/xush/.hermes/project_discoverability.md) — IMPLEMENTED 2026-04-26; hint row + prefix legend + KNOWN_PREFIXES; 22 tests; commit 025df994b

## Density Unification (2026-04-26)
- [Density Unification DU-1..DU-6](/home/xush/.hermes/project_density_unification.md) — IMPLEMENTED 2026-04-26; single LayoutResolver; atomic axis-bus-first write; shims; decision kwarg; 35 tests

## Density Tier Realization (2026-04-25)
- [Density Tier Realization](/home/xush/.hermes/project_density_tier_realization.md) — IMPLEMENTED 2026-04-25; DT-1..DT-4; HERO auto-clause, TRACE action, renderer COMPACT opt-out, 3-tier toggle cycle; 29 tests; commit 045d834e5

## Response Flow Deep Audit (2026-04-25)
- [Response Flow Deep Audit](/home/xush/.hermes/project_response_flow_deep_audit.md) — IMPLEMENTED 2026-04-25; HIGH-1..LOW-3 (9 issues); _flush_code_fence_buffer before block opens (7 sites); init/app guards; module-level ANSI regexes; orphan flush state reset; 16 tests; branch feat/response-flow-deep-audit

## Streaming Exception Sweep (2026-04-25)
- [Streaming Exception Sweep (Spec A)](/home/xush/.hermes/project_streaming_exception_sweep.md) — IMPLEMENTED 2026-04-25; H1 io.consume warning + exc_info; H3 _write_prose / _write_prose_inline_emojis logger.exception; H4 LiveLineWidget direct-write+buffer+drain on engine attach + _PRE_ENGINE_CAP=2000 + one-shot warn; 11 new + 2 retargeted tests; branch feat/streaming-exception-sweep

## Response Flow Exception Hardening (2026-04-25)
- [Response Flow Exception Hardening](/home/xush/.hermes/project_response_flow_exception_hardening.md) — IMPLEMENTED 2026-04-25; H-1..H-3 swallows→logs; M-1/M-2 unknown-state; M-3..M-5 comments; M-6 flush detached guard; L-1 _app_b1 reuse; L-2 fence fallback log; 19 tests; commit 0978ad370

## Mount Order + Axis Race (2026-04-26)
- [Spec B — Mount Order + Axis Race](/home/xush/.hermes/project_spec_b_mount_order_axis_race.md) — IMPLEMENTED 2026-04-26; H2/M6/H5/H6/M2/M5; _TERMINAL_STATES + _live_block_for_streaming + _live_anchor + H6 retry+broken + list() snapshots + inline child drain; 22 tests; commit 2d549f40e

## Tool Block Axis Audit (2026-04-25)
- [spec0 — except tuple cleanup](/home/xush/.hermes/project_spec0_except_tuple_cleanup.md) — IMPLEMENTED 2026-04-25; _resolve_max_header_gap 4-tuple→Exception + _log.debug + module logger; 3 tests; commit bf2ac7eaa; branch feat/spec0-except-tuple-cleanup

## Mechanical Sweep (2026-04-25)
- [Mech Sweep A — Exception Logging Compliance](/home/xush/.hermes/project_mech_sweep_a_exceptions.md) — IMPLEMENTED 2026-04-25; EXC-1..EXC-3; 21 modules get _log; 58 silent swallows rewritten; 3 workers get log calls; 20 tests; commit fd47f51a8; branch feat/textual-migration
- [Mech Sweep B — Dead Code Removal](/home/xush/.hermes/project_mech_sweep_b_dead_code.md) — IMPLEMENTED 2026-04-25; DC-1 measure_perf() / DC-2 _ARTIFACT_CAP / DC-3 THRESHOLD_BAR_HIDE / DC-4 module-map.md cleanup; 5 tests; branch feat/textual-migration
- [Mech Sweep D — CSS/Skin Hardening](/home/xush/.hermes/project_mech_sweep_d_css_skin.md) — IMPLEMENTED 2026-04-25; CSS-1..CSS-8: $tool-mcp-accent TCSS decl, text-muted path suffix, overlay-selection-bg var, skin refill, stale-audit regression, HTML export key fix, builtin vars doc comment, SkinColors.default() diff-bg alignment; 14 tests; commit feb51eeca
- [Mech Sweep C — Performance Micro-Fixes](/home/xush/.hermes/project_mech_sweep_c_perf.md) — IMPLEMENTED 2026-04-25; PERF-1 Style cache in completion_list / PERF-2 _stale_timer null in tools_overlay / PERF-3 on_compact dedup guard / PERF-4 streaming-block flush-slow timer unmount guard; 7 tests; commit 0744d6c56; branch feat/textual-migration
- [Mech Sweep E — Threading & Async Hardening](/home/xush/.hermes/project_mech_sweep_e_threading.md) — IMPLEMENTED 2026-04-25; THR-1 ensure_future→create_task (tools_overlay 3 sites) / THR-2 MpvPoller call_from_thread marshalling + _poll_once / THR-3 _NotifyListener docstring contract / THR-4 io.py call_soon_threadsafe comment; 9 tests; commit 1b75abf98; branch feat/textual-migration

## Stream Reveal Unification (2026-04-25)
- [Stream Reveal Unification spec](/home/xush/.hermes/project_stream_reveal_unification.md) — IMPLEMENTED 2026-04-25; SR-1..SR-8 unify three typewriter sites behind display.stream_reveal.*; defaults flipped on at 120cps gated by first-run telegraph; 36 tests; branch feat/stream-reveal-unification

## Tool Pipeline Audit Specs (2026-04-24)
- [Tool Pipeline Spec A — Header Tail](/home/xush/.hermes/project_tool_pipeline_spec_a.md) — IMPLEMENTED 2026-04-24; A-1..A-8: drop-order, double-$, ·-sep, hero style, exit visibility, 4-tier, icon tint, emoji; 27 tests; commit 07109f100
- [Tool Pipeline Quick Wins](/home/xush/.hermes/project_tool_pipeline_quick_wins.md) — IMPLEMENTED 2026-04-24; QW-01..QW-12: drop-order, shell-$, exit chip, strip focus, c binding, separator, footer text, hide-dur, emoji, ascii, tail dismiss, per-cat discovery; 38 tests; commits bea2d165d+4428dc274

## DESIGN.md Skin Rework (2026-04-25)
- [DESIGN.md Skin Rework](/home/xush/.hermes/project_design_md_skin_rework.md) — IMPLEMENTED 2026-04-25; all 4 specs (parent + DM-F/J/K); SkinPayload + DESIGN.md loader, 4 bundled skins ported, x-hermes namespace, hot-reload watches DESIGN.md only, _yaml_removal_unblocked gate; 79+ tests; branch feat/design-md-skin-rework

## Renderer Registry Move 2a (2026-04-25)
- [Renderer Registry Move 2a spec](/home/xush/.hermes/project_renderer_registry_2a.md) — IMPLEMENTED 2026-04-25; R-2A-1..R-2A-6: accepts() ABC, pick_renderer phase+density kwargs, call-site migration + sweep; 29 tests; branch feat/textual-migration

## Renderer Registry Move 2b (2026-04-25)
- [Renderer Registry Move 2b spec](/home/xush/.hermes/project_renderer_registry_2b.md) — IMPLEMENTED 2026-04-25; R-2B-1..R-2B-6: fold streaming renderers into BodyRenderer; unified REGISTRY; StreamingBodyRenderer=BodyRenderer alias; 44 tests; commit ede7ba966

## Density Resolver / Move 1 (2026-04-25)
- [Density Resolver spec](/home/xush/.hermes/project_density_resolver.md) — IMPLEMENTED 2026-04-25; DR-1/2/3/4/5: DensityInputs+Resolver, ToolPanel wiring, FooterPane.set_density, trim_tail_for_tier, view-state mirror; 40 tests; commit aee5a465a

## Tool Block Visual Noise (2026-04-25)
- [Tool Block Visual Noise](/home/xush/.hermes/project_tool_block_visual_noise.md) — IMPLEMENTED 2026-04-25; VN-1 action-row :focus-within gate (sentinel ToolPanel:focus-within rule required) + VN-2 header gap cap with tool-header-max-gap skin var; 12 tests; branch worktree-tool-block-visual-noise

## Tool Panel Accent Cleanup (2026-04-25)
- [Tool Panel Accent Cleanup spec](/home/xush/.hermes/project_tool_panel_accent_cleanup.md) — IMPLEMENTED 2026-04-25; AC-HIGH-01/AC-MED-01/AC-LOW-01: retired ToolAccent widget; tool-panel--accent + category-* + tool-panel--error border-left is sole accent contract; 8 tests + 2 stale-test rewrites in test_child_panel.py

## Tool Call State Machine (2026-04-24)
- [Tool Call State Machine spec](/home/xush/.hermes/project_tool_call_state_machine.md) — IMPLEMENTED 2026-04-24; SM-01..SM-06; ToolCallState+ToolCallViewState, service lifecycle methods, CLI thin adapters, as_completed, PENDING→DONE, write fallbacks; 29 tests; commit 835b6e239; branch worktree-tool-call-state-machine
- [Tool Call SM Hardening spec](/home/xush/.hermes/project_tool_call_sm_hardening.md) — IMPLEMENTED 2026-04-25; SM-HIGH-01/02 + SM-MED-01; delta buffering, panel wiring, single complete_tool_call terminal path; 12 tests; commit a911d09e3; branch worktree-tool-call-sm-hardening
- [TCS Audit Round 2 spec](/home/xush/.hermes/project_tcs_audit_round2.md) — IMPLEMENTED 2026-04-25; R2-HIGH-01 _terminalize_tool_view + mark_plan_cancelled + race guard / R2-HIGH-02 adoption id backfill / R2-MED-01 nameplate _MORPH_TICKS + _stop_timer fix; 14 tests; branch feat/tcs-audit-round2
- [TCS Audit Round 3 — Axis Bus](/home/xush/.hermes/project_tcs_audit_round3_axis.md) — IMPLEMENTED 2026-04-25; R3-AXIS-01 append_tool_output STARTED→STREAMING via set_axis / R3-AXIS-02 _cancel_first_pending_gen routes through helper / R3-AXIS-03 helper owns view.is_error mirror + redundant complete_tool_call write deleted; 9 new tests + 4 retargeted; branch feat/r3-axis-bus
- [R3-AFFORDANCE Kind Override](/home/xush/.hermes/project_r3_affordance_kind_override.md) — IMPLEMENTED 2026-04-25; KO-1..KO-5; user_kind_override view-state field + t keybind cycle + pick_renderer override kwarg + force_renderer migration + concept.md update; 17 new + 11 migrated tests; branch feat/textual-migration
- [Kind Override UX KO-A..KO-D](/home/xush/.hermes/project_kind_override_ux.md) — IMPLEMENTED 2026-04-26; flash on no-op paths; drop TEXT from cycle (7 stops); _user_forced caption via base.py helper; 150ms debounce; 14 tests; commit 820e2d486
- [R3-VOCAB spec](/home/xush/.hermes/project_r3_vocab.md) — IMPLEMENTED 2026-04-25; VOCAB-1 SkinColors.icon_dim/separator_dim + ToolHeader._colors() helper; VOCAB-2 14 except blocks normalized in services/tools.py; 21 tests; branch worktree-r3-vocab
- [Perf Instrumentation Gaps spec](/home/xush/.hermes/project_perf_instrumentation_gaps.md) — IMPLEMENTED 2026-04-25; PM-01/02/03; 31 tests; commit c3aa848e9; branch feat/perf-instrumentation-gaps
- [Tool Body Renderer Regression spec](/home/xush/.hermes/project_tool_body_renderer_regression.md) — IMPLEMENTED 2026-04-25; TBR-HIGH-01/02+MED-01/02+LOW-01; replace_body_widget, web/news JSON classifier, SearchRenderer.copy_text; 19 tests; commit c83bf1f5b
- [Tool Call Lifecycle Regression spec](/home/xush/.hermes/project_tool_call_lifecycle_regression.md) — IMPLEMENTED 2026-04-25; TCL-HIGH-01/02 + TCL-MED-01/02; live output via append_tool_output, debug-level renderer swap log, _panel_for_block helper; 15 tests
- [Render Diff Overhaul spec](/home/xush/.hermes/project_render_diff_overhaul.md) — IMPLEMENTED 2026-04-25; DiffRenderer overhaul; 26 tests; gotcha: don't hardcode worktree paths in tests

## Buffer Caps + Perf (2026-04-26)
- [Spec E — Buffer Caps + Perf](/home/xush/.hermes/project_spec_e_buffer_caps_perf.md) — IMPLEMENTED 2026-04-26; M1/M4/M9/M10; buffer caps + ReasoningPanel reflow + CopyableRichLog width cache + search path reset; 12 tests; commit 7f8b5f7ed

## response_flow.py Audit (2026-04-24)
- [response_flow audit + fix specs](/home/xush/.hermes/project_response_flow_audit.md) — 22 issues, 3-spec split A/B/C: state machine, reasoning/proxy, classifier routing; 33 tests total

## Renderer Audit Specs (2026-04-24)
- [Renderer audit specs](/home/xush/.hermes/project_render_audit.md) — 5 DRAFT specs covering rendereraudit.md (39 issues, 10 renderers + cross-cutting); grammar + diff + search + code/json/table/log + shell/selection/streaming; 137 tests
- [Render Visual Grammar spec](/home/xush/.hermes/project_render_visual_grammar.md) — MERGED 2026-04-24; G1/G2/G3/G4; _grammar.py + SkinColors + BodyFooter + build_widget cleanup; 23 tests; commits fa273f42+3c4a15e0
- [Render code-json spec](/home/xush/.hermes/project_render_code_json.md) — IMPLEMENTED 2026-04-24; R-C1..R-C4 CodeRenderer + R-J1..R-J3 JsonRenderer; 23 tests; commit 1cabe40f
- [Render table-log spec](/home/xush/.hermes/project_render_table_log.md) — IMPLEMENTED 2026-04-24; R-T1..R-T3 TableRenderer + R-L1..R-L3 LogRenderer; 20 tests; commit 12858046
- [Skin Palette spec](/home/xush/.hermes/project_skin_palette_spec.md) — SUPERSEDED; folded into DESIGN.md skin rework

## Tool Render HIGH Issues (2026-04-24)
- [Tool Render HIGH spec](/home/xush/.hermes/project_tool_render_high.md) — IMPLEMENTED 2026-04-24; H1 chip tone, H2 shell pipeline, H3 read+write group, H4 collapsed append, H5 _reset_label; 34 tests
- [Tool Render MEDIUM spec](/home/xush/.hermes/project_tool_render_medium.md) — IMPLEMENTED 2026-04-24; M1-M9 emoji/icon/diff/ops/registry/hotkey/path/flash/overlay; 37 tests

## Audit 4 Specs (2026-04-24)
- [Audit 4 Quick Wins spec](/home/xush/.hermes/project_audit4_quick_wins.md) — IMPLEMENTED 2026-04-24; TRIGGER-01/02/04, INTR-01/05/06, PANE-01/02, CONFIG-02/03/04, REF-02/03, BROWSE-02, SESS-01; 33 tests; commit 88c6c7b6; branch feat/audit4-quick-wins
- [Audit 4 Overlay Hardening spec](/home/xush/.hermes/project_audit4_overlay_hardening.md) — IMPLEMENTED 2026-04-25; INTR-02, CONFIG-01, REF-01, TRIGGER-03; 24 tests
- [Audit 4 Interrupt Renderer spec](/home/xush/.hermes/project_audit4_interrupt_renderer.md) — IMPLEMENTED 2026-04-25; INTR-03/04; renderer protocol + SessionFlowOverlay split; 28 tests
- [Audit 4 Chrome Density spec](/home/xush/.hermes/project_audit4_chrome_density.md) — IMPLEMENTED 2026-04-25; BROWSE-01 (2-cell minimap), IA-01 (legend→placeholder); 22 tests

## Services Logging Sweep (2026-04-25)
- [Services Logging Sweep LOG-1/LOG-2](/home/xush/.hermes/project_logging_sweep_services.md) — IMPLEMENTED 2026-04-25; sessions.py logger + 12 swallows; watchers.py 7 swallows; 28 tests; commit 9e616389d; branch feat/logging-sweep-services

## Streaming Pipeline Audit Specs (2026-04-25)
- [Streaming Pipeline Audit](/home/xush/.hermes/project_streaming_pipeline_audit.md) — A+B+C IMPLEMENTED; A: buf-safety (14t); B: io-hardening (18t, 8694595c5); C: engine-safety (18t); response_flow L2/L3/L4

## Renderer Framing (2026-04-26)
- [Renderer Framing RF-1..RF-6](/home/xush/.hermes/project_renderer_framing.md) — IMPLEMENTED 2026-04-26; BodyFrame container; BodyFooter multi-entry; all Phase C renderers migrated; LogRenderer [LEVEL] chips; tier-aware density classes; 30 tests

## Skin Contract Audit (2026-04-26)
- [Skin Contract Audit SC-1..SC-5](/home/xush/.hermes/project_skin_contract_audit.md) — IMPLEMENTED 2026-04-26; SC-1 SkinColors dim variants + accessible markers; SC-2 tier_accents MappingProxyType + 9 CSS vars; SC-3 JsonRenderer muted hint; SC-4 gutter via tool_header_gutter; SC-5 diff/completion/footer use SkinColors; 23 tests; commit 2901d4874; branch feat/textual-migration

## Plan/Group Sync (2026-04-26)
- [Plan/Group Sync PG-1..PG-4](/home/xush/.hermes/project_plan_group_sync.md) — IMPLEMENTED 2026-04-26; PlanSyncBroker; _set_view_state choke-point; incremental ToolGroup aggregate; ToolGroupState; 23 tests; commit 01c2944a0

## Hint Row & Feedback Polish (2026-04-26)
- [Hint Row & Feedback Polish HF-A..HF-G](/home/xush/.hermes/project_hint_row_feedback_polish.md) — IMPLEMENTED 2026-04-26; hint dedup, toggle reshow, F1 label, open flash, clipboard cache, discovery gate, rotating tip; 22 tests

## Header & Affordance Widths (2026-04-26)
- [Header Affordance Widths HW-1..HW-6](/home/xush/.hermes/project_header_affordance_widths.md) — IMPLEMENTED 2026-04-26; drop-order re-prio + gap clamp rm + actions cache rm + compact footer swap + separator fix; 20 tests; commit 3dc0396e7

## Streaming Pipeline Polish (2026-04-26)
- [Spec F — Streaming Pipeline Polish](/home/xush/.hermes/project_spec_f_streaming_polish.md) — IMPLEMENTED 2026-04-26; L1/L2/L3/L5/L6/L7/L11; diff regex single-source, blink reset, CSI log, syntax fallback log, threading docstring, _log rename/move, queue overflow test; 8 tests

## Timer/Pacer Lifecycle (2026-04-26)
- [Timer/Pacer Lifecycle H8..L10](/home/xush/.hermes/project_timer_pacer_lifecycle.md) — IMPLEMENTED 2026-04-26; deadline pacer + ManagedTimerMixin + init race + lock sharing + L9/L10; 27 tests; commit aff893f49

## Skill Namespace Phase 1 (2026-04-26)
- [SNS1 — $skill invocation namespace](/home/xush/.hermes/project_skill_namespace_phase1.md) — IMPLEMENTED 2026-04-26; $name prefix, SkillPickerOverlay, SkillCandidate, KNOWN_SKILLS, CompletionContext.SKILL_INVOKE=7; 62 tests; commit a7815ee35

## Skill Namespace Phase 2 (2026-04-26)
- [SNS2 — /skill deprecation warning](/home/xush/.hermes/project_skill_namespace_phase2.md) — IMPLEMENTED 2026-04-26; phase flag (default 2), _deprecated_slash_warned set, help text split, extra param removal; 13 tests; commit bd91c4228

## Skill Namespace Phase 3 (2026-04-26)
- [SNS3 — hard cutover: /skill-name rejected](/home/xush/.hermes/project_skill_namespace_phase3.md) — IMPLEMENTED 2026-04-26; slash-skill branch deleted, unconditional rejection, _deprecated_slash_warned removed, _KNOWN_SLASH_BARE guardrail, README sweep; 13 tests; commit 55bbef23c

## R3-LOW Deferred Fixes (2026-04-26)
- [R3-LOW deferred low-severity fixes](/home/xush/.hermes/project_r3_low_deferred.md) — IMPLEMENTED 2026-04-26; §5A dup collapsed writer; §2A drop-order; §2B comment; 9 tests; merge 679993a7f

## R3-NESTED Density Propagation (2026-04-26)
- [R3-NESTED parent→child density cascade](/home/xush/.hermes/project_r3_nested_density.md) — IMPLEMENTED 2026-04-26; ToolGroup.on_density_changed; Cat.4A+4B; 13 tests; merge 7c6d7e745

## Feedback Contract (2026-04-26)
- [FC-1..FC-4 feedback contract](/home/xush/.hermes/project_feedback_contract.md) — IMPLEMENTED 2026-04-26; uniform flash, race loser feedback, preemption, queue guard; ~22 tests; merge f3f27fa0d

## Quick Wins B — Footer & Header (2026-04-27)
- [Quick Wins B FH-1..FH-8](/home/xush/.hermes/project_quick_wins_b_footer_header.md) — IMPLEMENTED 2026-04-27; footer streaming gate, skeleton dismiss coalesce, COMPACT footer, hint dedup, OmissionBar settled, accepts(COMPACT), label re-read, bias fix; 19 tests; commit c9d64f58a

## Glyph Vocabulary Cleanup (2026-04-26)
- [TCS Glyph Vocabulary GV-1..GV-4](/home/xush/.hermes/project_tcs_glyph_vocab.md) — IMPLEMENTED 2026-04-26; grammar constants + chip() helper; gutter + sep migrations; 12 tests; commit c075f599e

## Quick Wins C — Services & Contract Polish (2026-04-27)
- [SC-1..SC-9 services contract polish](/home/xush/.hermes/project_quick_wins_c_services.md) — IMPLEMENTED 2026-04-27; renderer purity diff_lines; stall ◌ glyph; 50ms classifier timeout; IL-9 invariant; ENOTDIR/EINVAL taxonomy; 23 tests; commit 4d6565e38

## TCS Canonical Liveness (2026-04-26)
- [TCS Canonical Liveness CL-1..CL-6](/home/xush/.hermes/project_tcs_canonical_liveness.md) — IMPLEMENTED 2026-04-26; spinner deleted, _streaming_phase flag, stall-freeze, skin-driven pulse; 16 tests; commit e94b94b4c

## TCS Audit Followup (2026-04-26)
- [TCS Audit Followup](/home/xush/.hermes/project_tcs_audit_followup.md) — IMPLEMENTED 2026-04-26; TCS-HIGH-01..TCS-LOW-01; unknown-id fallback mark_plan_done; 22 tests; commit 86183850f

## Tool Error Recovery Contract (2026-04-26)
- [Tool Error Recovery Contract ER-1..ER-5](/home/xush/.hermes/project_error_recovery_contract.md) — IMPLEMENTED 2026-04-26; header=category only, body=stderr evidence (set_stderr_tail), footer=recovery sorted first; drop orders 10→8; 20 tests; commit d41bb0009

## Hint Pipeline Unification (2026-04-26)
- [Hint Pipeline H-1..H-4](/home/xush/.hermes/project_hint_pipeline.md) — IMPLEMENTED 2026-04-26; static tuples retired; _collect_hints+_render_hints+_truncate_hints; F1 pinned; D density key; 15 tests

## TCS Mode Legibility (2026-04-26)
- [TCS Mode Legibility ML-1..ML-5](/home/xush/.hermes/project_tcs_mode_legibility.md) — IMPLEMENTED 2026-04-26; kind caption on header; T revert binding; next-kind hint preview; ToolGroup enter toggle; collapsed focus guard; 18 tests; commit 345f0e983

## TCS Polish Pass (2026-04-26)
- [TCS Polish Pass P-1..P-9](/home/xush/.hermes/project_tcs_polish_pass.md) — IMPLEMENTED 2026-04-26; P-1..P-9 complete; _collect_hints/_render_hints/_truncate_hints; action_density_cycle D key; F1 pinned; 60 tests; commits 77b58787a+7a7d45011

## Enter Binary Toggle (2026-04-27)
- [R4-1 Enter Binary Toggle](/home/xush/.hermes/project_r4_1_enter_binary_toggle.md) — IMPLEMENTED 2026-04-27; action_toggle_collapse=COMPACT↔NOT-COMPACT; ChildPanel override deleted; hint labels fixed; 10 tests; commit f8b6f9ebb

## Density Cycle Completion (2026-04-27)
- [DC-1..DC-4 density cycle completion](/home/xush/.hermes/project_density_cycle_completion.md) — IMPLEMENTED 2026-04-27; 4-tier cycle+Shift+D+pressure skip; _DENSITY_CYCLE+_next_legal_tier_static; alt+t retired; 14 tests; commit 717c5c39c

## Microcopy Rich Text Consistency (2026-04-27)
- [MCC-1 microcopy_line() Rich Text](/home/xush/.hermes/project_mcc1_microcopy_richtext.md) — IMPLEMENTED 2026-04-27; _microcopy_text builder; all 8 branches→Text; 13 new + 15 migrated tests; commit 2ef35da28

## Tool Call Cleanup (2026-04-27)
- [CU-1/CU-2 spinner removal + a11y glyphs](/home/xush/.hermes/project_tool_call_cleanup.md) — IMPLEMENTED 2026-04-27; dead _spinner_char/_spinner_identity deleted from _header; SpinnerIdentity/make_spinner_identity removed from animation.py; _ASCII_GLYPHS extended with GV-1 gutter glyphs; 7 tests; commit 2f7e805c0

## TCS Skin Contract Tightening (2026-04-27)
- [SCT-1/SCT-2 skin contract tightening](/home/xush/.hermes/project_tcs_skin_contract_tightening.md) — IMPLEMENTED 2026-04-27; GLYPH_WARNING + microcopy_line colors kwarg + error_glyph helper; sub_agent_panel canonical glyphs; 9 tests; branch worktree-tcs-skin-contract-tightening

## Streaming Legibility Rhythm (2026-04-27)
- [SLR-1/2/3 streaming legibility rhythm](/home/xush/.hermes/project_streaming_legibility_rhythm.md) — IMPLEMENTED 2026-04-27; tier CSS class toggle + ChildPanel specificity override + SVG mock script + streaming_kind_hint sniff axis; 26 tests; commit a849a2d17

## Active / Pending Work
- [Audit 3 Quick Wins spec](/home/xush/.hermes/project_audit3_quick_wins.md) — IMPLEMENTED 2026-04-24; I1/I2/I3/I7/I8/I11/I12/I13/I15/I16; 22 tests; commit fd34922b
- [Audit 3 Completion Accept spec](/home/xush/.hermes/project_audit3_completion_accept.md) — IMPLEMENTED 2026-04-24; I4/I10; 10 tests
- [Audit 3 Draft Unification spec](/home/xush/.hermes/project_audit3_draft_unification.md) — IMPLEMENTED 2026-04-24; I5; 12 tests
- [Audit 3 Input Mode Enum spec](/home/xush/.hermes/project_audit3_input_mode_enum.md) — IMPLEMENTED 2026-04-24; I9/I17; 30 tests; commit 13f4f72e; branch feat/audit3-input-mode-enum
- [Audit 2 Quick Wins spec](/home/xush/.hermes/project_audit2_quick_wins.md) — IMPLEMENTED 2026-04-24; B3/B4/B6/B7/B8/B10/B11; 23 tests
- [Audit 2 Discovery & Affordances spec](/home/xush/.hermes/project_audit2_discovery.md) — IMPLEMENTED 2026-04-24; B1/B5/B9; 37 tests; branch feat/audit2-discovery-affordances
- [Audit 2 Structural Cleanup spec](/home/xush/.hermes/project_audit2_structural.md) — IMPLEMENTED 2026-04-24; B12–B16 (144 tests, 0c8da197) + B2 (12 tests, 8d6974c2); both specs IMPLEMENTED
- [Audit 1 Quick Wins spec](/home/xush/.hermes/project_audit1_quick_wins.md) — IMPLEMENTED 2026-04-24; A6/A8/A10/A11/A12/A13/A14/A15; 23 tests; commit 827e6036
- [Audit 1 Error Prominence spec](/home/xush/.hermes/project_audit1_error_prominence.md) — IMPLEMENTED 2026-04-24; A3/A7; 20 tests; commit f688ba5f; branch feat/audit1-error-prominence
- [Audit 1 Phase Legibility spec](/home/xush/.hermes/project_audit1_phase_legibility.md) — IMPLEMENTED 2026-04-24; A1/A2/A4/A5/A9; status_phase + nameplate gating + DEEP threshold + chip semantics + STARTED label; 50 tests; branch feat/audit1-phase-legibility
- [DrawbrailleOverlay split spec](/home/xush/.hermes/project_drawbraille_split_spec.md) — IMPLEMENTED 2026-04-23; anim_orchestrator.py + drawbraille_renderer.py + thin overlay shell + widgets/anim_config_panel.py; 53 tests
- [New anim engines + /anim improvements spec](/home/xush/.hermes/project_anim_engines_new.md) — IMPLEMENTED 2026-04-22; wireframe_cube/sierpinski/plasma/torus_3d/matrix_rain + speed/ambient/duration; 32 tests
- [TUI audit perf fixes spec](/home/xush/.hermes/project_tui_audit_perf.md) — IMPLEMENTED 2026-04-21; P1–P7: async history save, mermaid wiring, Popen threading, CSS var caching
- [TUI audit UX polish spec](/home/xush/.hermes/project_tui_audit_ux.md) — IMPLEMENTED 2026-04-21; U1–U4: history truncation, browse badge, idle-tip guard, error hint
- [Open PRs on NousResearch/hermes-agent](/home/xush/.hermes/project_open_prs.md) — 5 open PRs (PR1–PR5) stacked series for rich rendering + theming

## Architecture Docs (current state)
- [Output pane design spec](/home/xush/.hermes/project_output_pane_spec.md) — Full reference: OutputPanel, MessagePanel, ToolBlock, StreamingToolBlock, LiveLineWidget, ThinkingWidget, ReasoningPanel, data flow, gotchas, roadmap
- [Bottom-bar design spec](/home/xush/.hermes/project_bottom_bar_design.md) — Design + future reference for all 7 widgets below OutputPanel; key-badge typography, color shimmer, context-sensitive hints, 4-phase roadmap
- [R2 panes layout](/home/xush/.hermes/project_r2_panes.md) — IMPLEMENTED 2026-04-22; 3-pane skeleton, PaneManager, breakpoints, focus, persistence, /layout, Ctrl+\; 202 tests; flag-gated display.layout=v2
- [R3 overlay consolidation](/home/xush/.hermes/project_r3_overlay_consolidation.md) — A/B/C/E IMPLEMENTED 2026-04-22; 21→5 overlays; Phase D pending R7
- [R4 services refactor spec](/home/xush/.hermes/project_r4_services.md) — IMPLEMENTED 2026-04-22; all 4 phases; 10 _app_*.py deleted; HermesApp(App) only; 248 tests
- [RX1 FeedbackService spec](/home/xush/.hermes/project_rx1_feedback_service.md) — IMPLEMENTED 2026-04-22; unified flash service, Phases A/B/C, 18 tests
- [RX2 I/O boundary enforcement](/home/xush/.hermes/project_rx2_io_boundary.md) — IMPLEMENTED 2026-04-22; io_boundary.py, safe_run/open_url/edit_cmd/read/write, scan_sync_io, 63 tests
- [RX3 CSS var single-source](/home/xush/.hermes/project_rx3_css_var_sot.md) — Phases 1-3 IMPLEMENTED 2026-04-22; build_skin_vars + VarSpec shim + validator + 3-step fallback; Phase 4 deferred
- [RX4 AgentLifecycleHooks spec](/home/xush/.hermes/project_rx4_lifecycle_hooks.md) — IMPLEMENTED 2026-04-22; 71 tests; priority-ordered cleanup registry

## Recent Specs (last 2 weeks)
- [Bar SNR P0 spec](/home/xush/.hermes/project_bar_snr_p0.md) — IMPLEMENTED 2026-04-23; 10-cell bar, kill rotation, pin Esc-interrupt, suppress pulse+shimmer during streaming, dim bars; 42 tests
- [Bar SNR P1/P2 spec](/home/xush/.hermes/project_bar_snr_p1p2.md) — IMPLEMENTED 2026-04-24; YOLO stripe, breadcrumb sticky, model dim, session hide, cross-bar, collapse indicator; 24 tests
- [R1 PlanPanel spec](/home/xush/.hermes/project_plan_panel_r1.md) — IMPLEMENTED 2026-04-22; PlanPanel 4-section widget, tool_batch_callback, 78 tests
- [PlanPanel P0 fixes spec](/home/xush/.hermes/project_plan_panel_p0.md) — IMPLEMENTED 2026-04-23; delete DoneSection, default collapse, 2Hz tick, error chip, budget hide, debounce active; 37 tests
- [PlanPanel P1 polish spec](/home/xush/.hermes/project_plan_panel_p1.md) — IMPLEMENTED 2026-04-23; focus nav, segmented chip, [F9] badge; 86 tests
- [Tool call UX audit pass 10 spec](/home/xush/.hermes/project_tool_ux_pass10.md) — IMPLEMENTED 2026-04-22; 19 fixes / 10 themes (A–J), 7 commits
- [R10 Header-only collapse spec](/home/xush/.hermes/project_r10_header_only.md) — IMPLEMENTED 2026-04-23; exit code in collapsed header; 18 tests
- [Header signal hardening spec](/home/xush/.hermes/project_header_signal_hardening.md) — IMPLEMENTED 2026-04-23; flash last, · placeholder, category icon preserved, gutter from $accent; 20 tests
- [Error recoverability spec](/home/xush/.hermes/project_error_recoverability.md) — IMPLEMENTED 2026-04-23; --completing class, [e] stderr hint, remediation in header, sub-agent error glyphs; 22 tests
- [OmissionBar + ChildPanel polish spec](/home/xush/.hermes/project_omissionbar_childpanel.md) — IMPLEMENTED 2026-04-23; [reset] label, pre-mount at 80%, alt+c for compact; 15 tests
- [Input mode safety spec](/home/xush/.hermes/project_input_mode_safety.md) — IMPLEMENTED 2026-04-23; rev-search bash semantics, bash mode indicator, readline bindings; 33 tests
- [Input feedback & completion spec](/home/xush/.hermes/project_input_feedback_completion.md) — IMPLEMENTED 2026-04-23; legend strip, Enter accepts completion, error placeholder; 36 tests
- [InterruptOverlay hardening spec](/home/xush/.hermes/project_interrupt_overlay_hardening.md) — IMPLEMENTED 2026-04-23; 46 tests; commit 20c4c1c0
- [Startup banner polish spec](/home/xush/.hermes/project_startup_banner_polish.md) — IMPLEMENTED 2026-04-23; pre-flight frame, wall-clock cap, hold-frame, reduced motion; 18 tests
- [Nameplate + ThinkingWidget lifecycle spec](/home/xush/.hermes/project_nameplate_thinking.md) — IMPLEMENTED 2026-04-23; unhide during thinking, theme colors, shimmer, fade-out, layout reserve, label escalation; 29 tests
- [TUI Visual Polish spec](/home/xush/.hermes/project_tui_polish_spec.md) — IMPLEMENTED 2026-04-22; D1–D13: gutter, binary collapse, overlay border-title, flash color; 101 tests
- [TUI visual redesign spec](/home/xush/.hermes/project_tui_visual_redesign.md) — IMPLEMENTED 2026-04-22; V1–V8 splash/gutter/nameplate/sep/contrast/accent; 87 tests
- [ThinkingWidget v2 spec](/home/xush/.hermes/project_thinking_widget_v2.md) — IMPLEMENTED 2026-04-22; _AnimSurface+_LabelLine, 5 modes, 4 substates, two-phase deactivate; 22 tests
- [R5 DEPRECATED stub cleanup + app forwarder removal](/home/xush/.hermes/project_r5_deprecated_cleanup.md) — DONE; 0 DEPRECATED markers remain; all 3 passes complete; last commit 284a981e
- [TUI Dead Code Cleanup spec](/home/xush/.hermes/project_dead_code_cleanup.md) — IMPLEMENTED 2026-04-24; D1–D7: 6 dead files + 21 zero-caller app.py forwarders; 29 tests; commit 98b8763a; branch worktree-dead-code-cleanup
- [v2 Pane PlanPanel Wiring spec](/home/xush/.hermes/project_v2_pane_wiring.md) — IMPLEMENTED 2026-04-24; P1: PlanPanel in left pane for layout=v2, delete PlanPanelStub; 14 tests; commit c57f03c8
- [ResponseFlowEngine refactor](/home/xush/.hermes/project_response_flow_refactor.md) — IMPLEMENTED 2026-04-24; _LineClassifier, _init_fields, 5 dispatch methods, ReasoningFlowEngine dedup; 25 tests
- [response_flow.py audit fixes spec](/home/xush/.hermes/project_response_flow_fixes.md) — APPROVED 2026-04-24; A-1..A-6/B-1..B-3/B-5/C-1+C-2/D-2/D-5/D-6; 39 tests; B-2a adds engine walk to ThemeService
- [Audit 1 Phase Legibility](/home/xush/.hermes/project_audit1_phase_legibility.md) — IMPLEMENTED 2026-04-24; agent_phase.py + status_phase reactive + nameplate pause + DEEP gate + chip next-tool + Connecting label; 50 tests
- [Error Logging Sweep spec](/home/xush/.hermes/project_error_logging_sweep.md) — IMPLEMENTED 2026-04-24; EL-1..EL-7; 18 bare swallows → logger.warning/exception/debug across 7 modules; 24 tests; commit f2c01fa5
- [Session Manager Hardening spec](/home/xush/.hermes/project_session_manager_hardening.md) — IMPLEMENTED 2026-04-24; SM-1 _NotifyListener lock+logging, SM-2 dead-code deletion, SM-3 atomic write; 16 tests; branch feat/textual-migration
- [TUI Design 01 Tool Panel Affordances spec](/home/xush/.hermes/project_tui_design01_tool_panel.md) — IMPLEMENTED 2026-04-24; TOOL-1/2/3/4 footer routing + strip label + header trim + syntax theme; 6 tests
- [TUI Design 02 Overlay Interaction Fixes spec](/home/xush/.hermes/project_tui_design02_overlay_fixes.md) — IMPLEMENTED 2026-04-24; OVERLAY-1/2/3: remove Options tab, focus branch input, Alt+P hint; 7 tests; commit 3ff79bfc
- [TUI Design 03 Input/Status/Plan UX spec](/home/xush/.hermes/project_tui_design03_input_status_plan.md) — IMPLEMENTED 2026-04-24; INPUT-1/2 height+compact legends, STATUS-1/2 streaming dim+phase labels, PLAN-1 budget predicate; 18 tests; commit 5ab4093cc
- [Axis Bus on ToolCallViewState](/home/xush/.hermes/project_axis_bus_view_state.md) — IMPLEMENTED 2026-04-25; AXIS-1/2/3/4/5: DensityTier + kind/density fields + set_axis observer + COMPLETING stamp + collapse mirror; 14 tests; commit 8171e79ca; branch worktree-axis-bus-view-state
