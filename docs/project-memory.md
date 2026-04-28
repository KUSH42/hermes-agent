# Memory Index

## Feedback
- [TUI test scope — targeted only](feedback_tui_test_scope.md) — Never run full tests/tui/ (timeouts); run only targeted new test files
- [Full TUI suite timeout](feedback_full_suite_timeout.md) — Full tests/tui/ takes 16+ min; use timeout=1200000 if truly needed; prefer targeted files
- [Worktree workflow](feedback_worktree_workflow.md) — Prefer worktrees for parallel/isolated work; branch from main; merge back
- [New branches must be based on main](feedback_branch_base.md) — Branch from main by default; TUI work branches from feat/textual-migration
- [Specs are always .md files](feedback_spec_format.md) — Global rule: specs/design docs written to disk as Markdown, not inline-only
- [Hermes specs live in /home/xush/.hermes/](feedback_spec_location_hermes.md) — Parent of repo, alongside wdo.txt and existing spec .md files
- [asyncio deprecation warning fix](feedback_asyncio_deprecation.md) — Use get_running_loop() not get_event_loop() in sync pytest fixtures (Python 3.10+)
- [PlanPanel test — use PENDING not RUNNING](feedback_plan_panel_test_pending_state.md) — RUNNING triggers set_interval timer that blocks pilot.pause(); use PENDING instead
- [fix-tool-result-role is wontfix](feedback_wontfix_tool_result_role.md) — Local /anthropic proxy mis-detected as anthropic_messages edge case — skip it, do not re-spec
- [on_focus affordances guard](feedback_on_focus_affordances.md) — ToolPanel.on_focus only flashes when _has_affordances=True; tests must wire _block mock
- [Module split mutable globals](feedback_module_split_mutable_globals.md) — Re-exported bool globals in __init__ are value copies; tests must target source submodule directly
- [Textual Widget.parent/.app are read-only](feedback_textual_property_mock.md) — Use PropertyMock patch; Syntax._theme is object not string — capture theme= kwarg instead
- [Composer assist resolver + atomic history rewrite](feedback_composer_assist_atomic_history.md) — HermesInput assist state is centralized in AssistKind/_resolve_assist; _compute_mode reads _completion_overlay_active; history saves now dedupe + atomically rewrite the prompt_toolkit file

## Reference
- [TUI load-bearing facts](reference_tui_facts.md) — Textual 8.2.3 stable; API gotchas, typed state protocol, bounded queue
- [Textual 8.x impl gotchas](reference_textual_impl_gotchas.md) — 53+ gotchas: ReasoningFlowEngine missing fields, close_box hide-before-write order, + all prior
- [TCSS custom variable declaration gotcha](reference_tcss_variable_gotcha.md) — New $var-name refs MUST be declared in .tcss file; get_css_variables() alone insufficient at parse time
- [PathSearchProvider → HermesInput routing](reference_path_search_routing.md) — siblings can't bubble; App-level relay required; tests that set inp.value trigger real walker
- [Textual mount() anchor resolution gotcha](reference_textual_mount_order.md) — before=other resolves to other.parent not self; silently mounts into wrong container
- [OutputPanel mount order contract](reference_output_panel_mount_order.md) — all dynamic content uses before=tool_pending; trio [ToolPendingLine, ThinkingWidget, LiveLineWidget] always last; 12 tests
- [Rich v15 upgrade](reference_rich_v15.md) — upgraded from 14.2→15.0.0; ANSI newline fix, FileProxy.isatty fix; pin updated to >=15.0.0,<16
- [rtk pytest output suppression](reference_rtk_pytest.md) — rtk-ai/rtk swallows pytest output; fix: --override-ini="addopts="
- [TUI dev skill](skills/tui-development/SKILL.md) — Widget patterns, thread safety, testing, CSS theming, Textual 8.x gotchas
- [Hermes skin skill + reference](reference_hermes_skin_skill.md) — ~/.claude/skills/hermes-skin/SKILL.md; skin-reference.md is canonical; checklist for new component vars
- [TUI mixin structure + R4 services](reference_tui_mixin_structure.md) — MRO, services/ subpackage, adapter pattern, _flash_hint exception, deleted files
- [Transferable components from local codebases](transferable_components.md) — Tier 1–3 audit of ai-agent-dev-dumbeddown, ai-orchestrator, ai-orchestrator2 with port effort + gotchas

## response_flow.py Audit (2026-04-24)
- [response_flow audit + fix specs](project_response_flow_audit.md) — 22 issues, 3-spec split A/B/C: state machine, reasoning/proxy, classifier routing; 33 tests total

## Renderer Audit Specs (2026-04-24)
- [Renderer audit specs](project_render_audit.md) — 5 DRAFT specs covering rendereraudit.md (39 issues, 10 renderers + cross-cutting); grammar + diff + search + code/json/table/log + shell/selection/streaming; 137 tests
- [Render Visual Grammar spec](project_render_visual_grammar.md) — MERGED 2026-04-24; G1/G2/G3/G4; _grammar.py + SkinColors + BodyFooter + build_widget cleanup; 23 tests; commits fa273f42+3c4a15e0
- [Render code-json spec](project_render_code_json.md) — IMPLEMENTED 2026-04-24; R-C1..R-C4 CodeRenderer + R-J1..R-J3 JsonRenderer; 23 tests; commit 1cabe40f
- [Render table-log spec](project_render_table_log.md) — IMPLEMENTED 2026-04-24; R-T1..R-T3 TableRenderer + R-L1..R-L3 LogRenderer; 20 tests; commit 12858046
- [Skin Palette spec](project_skin_palette_spec.md) — DRAFT; SYN-1 fix validate_skin_payload non-hex; SYN-2 SkinColors.syntax_scheme+resolve_syntax_palette; SYN-3 4 skins syntax-scheme; 22 tests

## Audit 4 Specs (2026-04-24)
- [Audit 4 Quick Wins spec](project_audit4_quick_wins.md) — IMPLEMENTED 2026-04-24; TRIGGER-01/02/04, INTR-01/05/06, PANE-01/02, CONFIG-02/03/04, REF-02/03, BROWSE-02, SESS-01; 33 tests; commit 88c6c7b6; branch feat/audit4-quick-wins
- [Audit 4 Overlay Hardening spec](project_audit4_overlay_hardening.md) — DRAFT; INTR-02, CONFIG-01, REF-01, TRIGGER-03; 24 tests
- [Audit 4 Interrupt Renderer spec](project_audit4_interrupt_renderer.md) — DRAFT; INTR-03/04; renderer protocol + SessionFlowOverlay split; 28 tests
- [Audit 4 Chrome Density spec](project_audit4_chrome_density.md) — DRAFT; BROWSE-01 (2-cell minimap), IA-01 (legend→placeholder); 22 tests

## Active / Pending Work
- [Composer surface audit spec](project_composer_surface_audit.md) — IMPLEMENTED 2026-04-28; centralized AssistKind resolver, completion-mode mirror flag, locked state restore, rev-search/error host classes, explicit-bash detection, atomic history rewrite, completion placeholder + ghost-suggestion hardening; tests/tui/test_composer_invariants.py plus targeted composer suite
- [Audit 3 Quick Wins spec](project_audit3_quick_wins.md) — IMPLEMENTED 2026-04-24; I1/I2/I3/I7/I8/I11/I12/I13/I15/I16; 22 tests; commit fd34922b
- [Audit 3 Completion Accept spec](project_audit3_completion_accept.md) — APPROVED 2026-04-24; I4/I10; 10 tests; /home/xush/.hermes/2026-04-24-audit3-completion-accept-spec.md
- [Audit 3 Draft Unification spec](project_audit3_draft_unification.md) — APPROVED 2026-04-24; I5; 12 tests; /home/xush/.hermes/2026-04-24-audit3-draft-unification-spec.md
- [Audit 3 Input Mode Enum spec](project_audit3_input_mode_enum.md) — IMPLEMENTED 2026-04-24; I9/I17; 30 tests; commit 13f4f72e; branch feat/audit3-input-mode-enum
- [Audit 2 Quick Wins spec](project_audit2_quick_wins.md) — APPROVED 2026-04-24; B3/B4/B6/B7/B8/B10/B11; 23 tests; /home/xush/.hermes/2026-04-24-audit2-quick-wins-spec.md
- [Audit 2 Discovery & Affordances spec](project_audit2_discovery.md) — IMPLEMENTED 2026-04-24; B1/B5/B9; 37 tests; branch feat/audit2-discovery-affordances
- [Audit 2 Structural Cleanup spec](project_audit2_structural.md) — IMPLEMENTED 2026-04-24; B12–B16 (144 tests, 0c8da197) + B2 (12 tests, 8d6974c2); both specs IMPLEMENTED
- [Audit 1 Quick Wins spec](project_audit1_quick_wins.md) — IMPLEMENTED 2026-04-24; A6/A8/A10/A11/A12/A13/A14/A15; 23 tests; commit 827e6036
- [Audit 1 Error Prominence spec](project_audit1_error_prominence.md) — IMPLEMENTED 2026-04-24; A3/A7; 20 tests; commit f688ba5f; branch feat/audit1-error-prominence
- [Audit 1 Phase Legibility spec](project_audit1_phase_legibility.md) — IMPLEMENTED 2026-04-24; A1/A2/A4/A5/A9; status_phase + nameplate gating + DEEP threshold + chip semantics + STARTED label; 50 tests; branch feat/audit1-phase-legibility
- [DrawbrailleOverlay split spec](project_drawbraille_split_spec.md) — APPROVED 2026-04-23; 4 files: anim_orchestrator.py + drawbraille_renderer.py + thin overlay shell + widgets/anim_config_panel.py; 53 tests
- [New anim engines + /anim improvements spec](project_anim_engines_new.md) — APPROVED 2026-04-22; wireframe_cube/sierpinski/plasma/torus_3d/matrix_rain + speed/ambient/duration; 32 tests
- [TUI audit perf fixes spec](project_tui_audit_perf.md) — APPROVED 2026-04-21; P1–P7: async history save, mermaid wiring, Popen threading, CSS var caching; spec at /home/xush/.hermes/tui-audit-perf-fixes-spec.md
- [TUI audit UX polish spec](project_tui_audit_ux.md) — APPROVED 2026-04-21; U1–U4: history truncation, browse badge, idle-tip guard, error hint; spec at /home/xush/.hermes/tui-audit-ux-polish-spec.md
- [Open PRs on NousResearch/hermes-agent](project_open_prs.md) — 5 open PRs (PR1–PR5) stacked series for rich rendering + theming

## Architecture Docs (current state)
- [Output pane design spec](project_output_pane_spec.md) — Full reference: OutputPanel, MessagePanel, ToolBlock, StreamingToolBlock, LiveLineWidget, ThinkingWidget, ReasoningPanel, data flow, gotchas, roadmap
- [Bottom-bar design spec](project_bottom_bar_design.md) — Design + future reference for all 7 widgets below OutputPanel; key-badge typography, color shimmer, context-sensitive hints, 4-phase roadmap
- [R2 panes layout](project_r2_panes.md) — IMPLEMENTED 2026-04-22; 3-pane skeleton, PaneManager, breakpoints, focus, persistence, /layout, Ctrl+\; 202 tests; flag-gated display.layout=v2
- [R3 overlay consolidation](project_r3_overlay_consolidation.md) — A/B/C/E IMPLEMENTED 2026-04-22; 21→5 overlays; Phase D pending R7
- [R4 services refactor spec](project_r4_services.md) — IMPLEMENTED 2026-04-22; all 4 phases; 10 _app_*.py deleted; HermesApp(App) only; 248 tests
- [RX1 FeedbackService spec](project_rx1_feedback_service.md) — IMPLEMENTED 2026-04-22; unified flash service, Phases A/B/C, 18 tests
- [RX2 I/O boundary enforcement](project_rx2_io_boundary.md) — IMPLEMENTED 2026-04-22; io_boundary.py, safe_run/open_url/edit_cmd/read/write, scan_sync_io, 63 tests
- [RX3 CSS var single-source](project_rx3_css_var_sot.md) — Phases 1-3 IMPLEMENTED 2026-04-22; build_skin_vars + VarSpec shim + validator + 3-step fallback; Phase 4 deferred
- [RX4 AgentLifecycleHooks spec](project_rx4_lifecycle_hooks.md) — IMPLEMENTED 2026-04-22; 71 tests; priority-ordered cleanup registry

## Recent Specs (last 2 weeks)
- [Bar SNR P0 spec](project_bar_snr_p0.md) — IMPLEMENTED 2026-04-23; 10-cell bar, kill rotation, pin Esc-interrupt, suppress pulse+shimmer during streaming, dim bars; 42 tests
- [Bar SNR P1/P2 spec](project_bar_snr_p1p2.md) — IMPLEMENTED 2026-04-24; YOLO stripe, breadcrumb sticky, model dim, session hide, cross-bar, collapse indicator; 24 tests
- [R1 PlanPanel spec](project_plan_panel_r1.md) — IMPLEMENTED 2026-04-22; PlanPanel 4-section widget, tool_batch_callback, 78 tests
- [PlanPanel P0 fixes spec](project_plan_panel_p0.md) — IMPLEMENTED 2026-04-23; delete DoneSection, default collapse, 2Hz tick, error chip, budget hide, debounce active; 37 tests
- [PlanPanel P1 polish spec](project_plan_panel_p1.md) — IMPLEMENTED 2026-04-23; focus nav, segmented chip, [F9] badge; 86 tests
- [Tool call UX audit pass 10 spec](project_tool_ux_pass10.md) — IMPLEMENTED 2026-04-22; 19 fixes / 10 themes (A–J), 7 commits
- [R10 Header-only collapse spec](project_r10_header_only.md) — IMPLEMENTED 2026-04-23; exit code in collapsed header; 18 tests
- [Header signal hardening spec](project_header_signal_hardening.md) — IMPLEMENTED 2026-04-23; flash last, · placeholder, category icon preserved, gutter from $accent; 20 tests
- [Error recoverability spec](project_error_recoverability.md) — IMPLEMENTED 2026-04-23; --completing class, [e] stderr hint, remediation in header, sub-agent error glyphs; 22 tests
- [OmissionBar + ChildPanel polish spec](project_omissionbar_childpanel.md) — IMPLEMENTED 2026-04-23; [reset] label, pre-mount at 80%, alt+c for compact; 15 tests
- [Input mode safety spec](project_input_mode_safety.md) — IMPLEMENTED 2026-04-23; rev-search bash semantics, bash mode indicator, readline bindings; 33 tests
- [Input feedback & completion spec](project_input_feedback_completion.md) — IMPLEMENTED 2026-04-23; legend strip, Enter accepts completion, error placeholder; 36 tests
- [InterruptOverlay hardening spec](project_interrupt_overlay_hardening.md) — IMPLEMENTED 2026-04-23; 46 tests; commit 20c4c1c0
- [Startup banner polish spec](project_startup_banner_polish.md) — IMPLEMENTED 2026-04-23; pre-flight frame, wall-clock cap, hold-frame, reduced motion; 18 tests
- [Nameplate + ThinkingWidget lifecycle spec](project_nameplate_thinking.md) — IMPLEMENTED 2026-04-23; unhide during thinking, theme colors, shimmer, fade-out, layout reserve, label escalation; 29 tests
- [TUI Visual Polish spec](project_tui_polish_spec.md) — IMPLEMENTED 2026-04-22; D1–D13: gutter, binary collapse, overlay border-title, flash color; 101 tests
- [TUI visual redesign spec](project_tui_visual_redesign.md) — IMPLEMENTED 2026-04-22; V1–V8 splash/gutter/nameplate/sep/contrast/accent; 87 tests
- [ThinkingWidget v2 spec](project_thinking_widget_v2.md) — IMPLEMENTED 2026-04-22; _AnimSurface+_LabelLine, 5 modes, 4 substates, two-phase deactivate; 22 tests
- [R5 DEPRECATED stub cleanup + app forwarder removal](project_r5_deprecated_cleanup.md) — DONE; 0 DEPRECATED markers remain; all 3 passes complete; last commit 284a981e
- [TUI Dead Code Cleanup spec](project_dead_code_cleanup.md) — IMPLEMENTED 2026-04-24; D1–D7: 6 dead files + 21 zero-caller app.py forwarders; 29 tests; commit 98b8763a; branch worktree-dead-code-cleanup
- [v2 Pane PlanPanel Wiring spec](project_v2_pane_wiring.md) — IMPLEMENTED 2026-04-24; P1: PlanPanel in left pane for layout=v2, delete PlanPanelStub; 14 tests; commit c57f03c8
- [ResponseFlowEngine refactor](project_response_flow_refactor.md) — IMPLEMENTED 2026-04-24; _LineClassifier, _init_fields, 5 dispatch methods, ReasoningFlowEngine dedup; 25 tests
- [response_flow.py audit fixes spec](project_response_flow_fixes.md) — APPROVED 2026-04-24; A-1..A-6/B-1..B-3/B-5/C-1+C-2/D-2/D-5/D-6; 39 tests; B-2a adds engine walk to ThemeService
- [Audit 1 Phase Legibility](project_audit1_phase_legibility.md) — IMPLEMENTED 2026-04-24; agent_phase.py + status_phase reactive + nameplate pause + DEEP gate + chip next-tool + Connecting label; 50 tests
- [Error Logging Sweep spec](project_error_logging_sweep.md) — IMPLEMENTED 2026-04-24; EL-1..EL-7; 18 bare swallows → logger.warning/exception/debug across 7 modules; 24 tests; commit f2c01fa5
- [Session Manager Hardening spec](project_session_manager_hardening.md) — IMPLEMENTED 2026-04-24; SM-1 _NotifyListener lock+logging, SM-2 dead-code deletion, SM-3 atomic write; 16 tests; branch feat/textual-migration
- [TUI Design 01 Tool Panel Affordances spec](project_tui_design01_tool_panel.md) — IMPLEMENTED 2026-04-24; TOOL-1/2/3/4 footer routing + strip label + header trim + syntax theme; 6 tests
