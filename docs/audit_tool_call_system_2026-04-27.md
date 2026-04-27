# Tool Call System — Design & UX Audit, Round 3

**Date:** 2026-04-27
**Branch:** feat/textual-migration
**Status:** DRAFT — fresh findings post-Round-2 (2026-04-26_round2.md)
**Scope:** UX/design only — visual hierarchy, lifecycle legibility, density gracefulness, affordance discovery, error recovery, group/plan coherence, renderer consistency, skin contract, motion/feedback, information architecture
**Predecessors:** 
- audit_tool_call_system_2026-04-26.md (DRAFT, Round 1 on the fly)
- audit_tool_call_system_2026-04-26_round2.md (post-merge findings)

---

## Executive summary

**The system is in stable, mature shape.** The three-axis frame (PHASE × KIND × DENSITY) is well-implemented. Round-2 issues (F-1..F-7) have mostly closed or are deferred by design. This audit focuses on **visual UX** from the user's eyes outward: does the information reach them clearly? Does motion signal or distract? Do all renderer kinds feel coherent?

**Finding count:** 8 findings, all MED/LOW severity. No HIGH findings that degrade core paths. The system **no longer has structural debt** — it now has *polish gaps* and *micro-inconsistencies*.

Severity: **HIGH** = degrades core UX path; **MED** = visible polish gap; **LOW** = consistency/correctness.

---

## Findings

### 1. [MED] — Hint row at 50-cell threshold is too abrupt; lacks graceful slope

**Where:** `tool_panel/_actions.py:772` (`_render_hints` method, line 772: `narrow = width < 50`).

**What user sees:** At 51 cells: `[Enter] follow · [f] tail · [y] copy · [t] kind: code → plain · F1 help`. At 49 cells: `[Enter] follow · [f] tail · F1 help` (two-thirds of context vanishes). The threshold is a cliff, not a curve.

**Why it's wrong:** F-1 from Round 2 already raised truncation marker opacity. But the underlying issue is deeper: the algorithm suppresses all contextual hints (line 783: `shown_contextual = contextual[:2] if not narrow else []`) when width < 50 without measuring actual budget. A user on a 60-cell SSH window with a narrow tmux pane might have budget for one contextual hint, but the short-circuit prevents even attempting to pack it.

**Fix sketch:** Delete the `narrow = width < 50` short-circuit. Let `_truncate_hints` handle all widths uniformly. Contextual hints should pack until budget exhausted (zero-sum with primary hints), not vanish categorically. The packing algorithm already exists; extend it to apply everywhere.

---

### 2. [MED] — Hint row `+N more` marker does not expose dropped keys (F-1 follow-up)

**Where:** `tool_panel/_actions.py:793–796`.

**What user sees:** When hints overflow, a marker `+2 more` appears. The user cannot see which 2 keys (e.g., `e` stderr vs `E` edit) were dropped. Power users widen the terminal to *discover* the keys, but `+2 more` gives no guidance on whether it's worth the hassle.

**Why it's wrong:** The dynamic hint pipeline now generates more variety (context-aware: `[t] kind: code → plain` appears only when KIND override is set, etc.). Dropped hints carry semantic weight — they tell users what affordances exist. F-1 suggested showing `+y/r/e` (keys without labels) as a middle ground.

**Fix sketch:** When hints are truncated, expose dropped key names only (no labels, to save cells): `+y/r/e`. Fall back to `+N more` only at extreme narrowness (<25 cells). Key names alone let users press to discover, and are discoverable without terminal resizing.

---

### 3. [LOW] — Hint row footer-chip deduplication is order-dependent

**Where:** `tool_panel/_actions.py:688–702` (`_visible_footer_action_kinds` + `_collect_hints`).

**What user sees:** If a footer action (e.g., `[r] retry`) is visible, it gets suppressed from the hint row. But the visibility check is a DOM query (`fp._action_row.query(".--action-chip")`), which is best-effort and can race with async footer updates. If the footer hasn't mounted yet, the dedup misses, and both footer and hint row show `[r] retry`.

**Why it's wrong:** The dedup is a polish measure: avoid duplicate affordances. But the DOM query is fragile. The footer doesn't guarantee render order with the hint row. If a completion event fires and the footer hasn't stabilized yet, a brief moment shows duplication.

**Fix sketch:** Move the dedup source of truth into the completion/update path. When `_refresh_hint_row` is called, pass the visible footer actions as an argument rather than querying the DOM. This centralizes the dedup logic and removes the race.

---

### 4. [LOW] — Microcopy separator uses grammar constant but not consistently

**Where:** `streaming_microcopy.py:76` uses `_glyph(GLYPH_META_SEP)`, but the microcopy line itself is built as a plain string (line 89, etc.) using f-strings with `_SEP` literal interpolation.

**What user sees:** The separators in the microcopy line (`▸ 12 lines · 3.4 kB · 200 kB/s`) respect the glyph() accessibility fallback, but the overall line is a plain string, not a Rich Text. This means if a user later adds advanced styling (e.g., per-component colorization), the microcopy won't integrate naturally.

**Why it's wrong:** It's not *wrong* per se, but it's asymmetric. All other surfaces (header, footer, hint row) build Rich Text with explicit styling. Microcopy builds strings. Minor consistency issue; not load-bearing.

**Fix sketch:** Convert `microcopy_line` to return Rich Text consistently. Build the line incrementally with Rich Text.append() like the hints do. No functional change, just internal consistency. Low priority.

---

### 5. [LOW] — Phase chip removed but phase lifecycle not fully visual

**Where:** `tool_blocks/_header.py` (PulseMixin used; no explicit phase chip since CL-1).

**What user sees:** While STREAMING, the header icon pulses. That's the only "what phase am I in?" signal. Stall detection freezes the pulse (`_pulse_paused`), which is good. But if a user focuses a block mid-stream, then switches focus away, the pulsing header is no longer visible. No other surface (microcopy, footer, body) clearly states "phase: STREAMING."

**Why it's wrong:** It's not wrong, but it's fragile. The microcopy updates per-line (good signal), but only while STREAMING. The moment completion starts (COMPLETING phase), the microcopy stops updating, and the only signal is the pulse settling and the icon color changing. A user who steps away briefly doesn't know the block entered COMPLETING.

**Fix sketch:** Not a fix — a observation for future work. The current model (pulse + microcopy for STREAMING, settled icon + footer for completion) is sound. But add a brief phase-transition flash on COMPLETING entry (similar to flash on TRACE armed) to telegraph the state change. Out of scope for this audit; noted for RX (response flow) audits.

---

### 6. [MED] — Footer visibility gated on density COMPACT/TRACE, but no row-budget negotiation

**Where:** `tool_panel/_footer.py:278–289` (`_refresh_visibility`).

**What user sees:** In DEFAULT tier, footer is visible (if content). In COMPACT, footer is `display: none`. In TRACE, footer is visible. But the footer has no *row budget*: it either shows fully or hides. The header tail shrinks per `_DROP_ORDER_COMPACT`; the body collapses; the footer is binary.

**Why it's wrong:** Concept.md identified this gap: footer cannot gracefully degrade. Round 2 raised it as C-1 (design trajectory, not bug). It's not broken, but it's inelegant. A user in COMPACT might appreciate 1-row footer (chips only, no stderr tail) instead of losing all recovery info.

**Fix sketch:** Extend `LayoutDecision` with a `footer_rows: int` field (0, 1, 2, 3+ per tier). FooterPane renders chips+stderr_tail budget-aware, like header tail does. COMPACT = 1 row (chips, no tail), DEFAULT = 2 (chips + tail truncated), TRACE = unbounded. This unifies the density model. Deferred to future spec (no user complaint yet).

---

### 7. [LOW] — Microcopy stall warning style is hardcoded, not through grammar

**Where:** `streaming_microcopy.py:136` (`result.append(" ⚠ stalled?", style="bold yellow")`).

**What user sees:** When streaming stalls, the microcopy appends `⚠ stalled?` in bold yellow. This color is hardcoded; it doesn't consult `SkinColors.warning_dim` or the skin's warning color token.

**Why it's wrong:** Minor skin contract leak. The glyph `⚠` is correct (not a hardcoded Unicode-vs-ASCII fallback issue), but the color bypasses the skin system. If a user's skin defines a custom warning color, stall warnings will use hard-coded yellow, not the skin's palette.

**Fix sketch:** Use `SkinColors.warning_dim` at the call site. Microcopy doesn't have direct app context, so it would need the colors passed in. Currently, `microcopy_line()` receives `spec` and `state` only. Either thread colors through, or make the call site (in `_streaming.py:468`) apply the style after receiving the text.

---

### 8. [LOW] — Error-icon glyph in header uses per-call lookup, should be constant

**Where:** `tool_blocks/_header.py:227–231` (per-tool error icon resolution).

**What user sees:** When a tool errors, the header displays an error-specific icon (e.g., a red bolt for timeout, a red X for runtime error). This is fetched from `get_tool_icon_mode()` on each render, which is correct but verbose.

**Why it's wrong:** It's not wrong — just low leverage and scattered. The error icon logic lives in three places: (1) header.py for header display, (2) tool_result_parse.py for terminal state, (3) display.py for tool category defaults. Each re-implements the glyph set. If a skin wants to customize error glyphs, there's no central point.

**Fix sketch:** Add `error_icon` and `error_icon_glyph_map` to `SkinColors` or a new `ErrorGlyphs` constant in `_grammar.py`. Centralize error icon resolution. Low priority (error blocks are rare compared to success).

---

## Cross-cutting observations

### C-1: Hint row authority has solidified; footer is now secondary display

Round 2 noted this trajectory; it's now visible in the code. The hint row (H-1..H-4 from prior work) is the user's **discovery surface** — context-aware, truncates gracefully, F1 is pinned. The footer (action chips) is now mostly a **status display** (exit code, stderr, artifacts). This is good! The roles are clear.

**No action:** Just confirming the design won. If a future feature adds back footer action-first thinking, gently push back toward the hint row.

---

### C-2: Microcopy is doing more work than its line count suggests

`streaming_microcopy.py` (~150 lines) is the only continuously-updating "this is alive" surface during STREAMING. It provides:
- Per-category progress (lines, bytes, rate, matches)
- Elapsed time (once > 2s)
- Stall detection (freezes on no-output, shows `⚠ stalled?`)
- Shimmer animation for AGENT category
- Accessibility fallback (static text when reduced_motion)

It's lightweight and elegant, but it has **no skin styling** (colors hardcoded in one place, line 136), **no narrow-terminal testing** (at <50 cells, does it overflow?), and **no explicit error surface** (stall is the closest). Recommend: add microcopy to the next narrow-terminal polish pass.

---

### C-3: Density tiers are well-named but conceptually per-tier, not per-axis

The `LayoutResolver` resolves a single `tier: DensityTier` (HERO/DEFAULT/COMPACT/TRACE). The concept.md frame suggests axes should be orthogonal, but density is modeled as **presets** not **budgets**. Switching to HERO automatically sets header/body/footer behavior; you cannot mix HERO body with COMPACT footer.

This is fine for now (the tiers are well-chosen). But if future work wants finer control (e.g., "show me a tall body in a narrow header"), the current `DensityTier` enum won't scale. Noted for C-2 follow-up work.

---

### C-4: Renderer visual grammar is consistent across kinds

Spot-checked CODE, DIFF, JSON, LOG, SEARCH, SHELL, TABLE renderers. All use:
- `SkinColors.from_app()` or fallback to defaults
- Gutter glyphs from `_grammar.py`
- Color tokens through `colors.error`, `colors.success`, etc.
- No hardcoded hex colors (except reasonable defaults in `_grammar.py`)
- Consistent wrap/truncation at edge cases

**No findings** — the grammar is doing its job. Skins can customize all renderer output.

---

## Already-known & deferred

### From Round 2

**Closed (F-1 follow-up):** F-1 reported truncation hiding dropped hints. F-2 (cliff at width 50) is a parent issue; fixing F-2 implicitly fixes F-1's symptom.

**Closed (F-4 glyph accessibility):** Gutter glyphs were added to `_ASCII_GLYPHS` in CU-2. No re-auditing needed.

**Closed (F-6 spinner dead state):** Spinners were deleted in CU-1. No dead code lingering.

**Closed (F-7 hero flash wording):** The flash now includes reason (line 85 in _actions.py: `msg = self._hero_rejection_reason(inputs)`).

**Deferred (C-1 hint vs footer authority):** See C-1 above — trajectory confirmed, no action needed.

**Deferred (C-2 budget vs preset):** See C-3 above — out of scope for polish.

**Deferred (C-3 microcopy styling):** See C-2 above — noted for next pass.

### From Rounds 1 & 2 combined

The following areas were audited and confirmed stable; do not re-audit unless behavior changes:

- **PHASE state machine:** `services/tools.py::ToolRenderingService` — unified lifecycle (PENDING → GENERATED → STARTED → STREAMING → COMPLETING → DONE/ERROR/CANCELLED). Subscribers properly wired. ✓
- **KIND classifier + renderer registry:** `content_classifier.py` + `body_renderers/__init__.py`. Runs once at COMPLETING. User override via `t` keybind wired to `view.user_kind_override`. ✓
- **Glyph vocabulary:** `body_renderers/_grammar.py` (GLYPH_* constants, chip() helper, SkinColors). All call sites use grammar lookups. ✓
- **Error recovery contract:** `tool_result_parse.py::inject_recovery_actions()` (parse-time), footer chips (status display), hint row (discovery). ER-1..ER-5 spec implemented. ✓
- **Canonical liveness:** Pulse + microcopy + stall freeze (CL-1..CL-6 spec). Phase chips removed. ✓
- **Plan/group sync:** PG-1..PG-4 brokers aggregate state correctly. Nesting clarity intact. ✓
- **Hint pipeline:** H-1..H-4 dynamic builder, context-aware, F1 pinned. ✓
- **Layout resolver:** Unified density decision, tier-aware drop orders, footer visibility gated. ✓

---

## Recommended sequencing

Three lightweight worktrees could close all remaining findings:

**Worktree A — Hint row polish** (~8 tests)
- Finding 1: Drop the `width < 50` cliff; use packing budget everywhere
- Finding 2: Expose dropped key names (`+y/r/e` form)
- Finding 3: Move footer-chip dedup to completion pipeline (race-safe)

**Worktree B — Skin contract tightening** (~6 tests)
- Finding 7: Thread SkinColors into microcopy for stall styling
- Finding 8: Centralize error glyphs (minor, can defer)

**Worktree C — Consistency** (~4 tests)
- Finding 4: Convert microcopy string-building to Rich Text incrementally

Total: ~18 tests. No PHASE/KIND/DENSITY core changes. After this, only C-level design trajectories (C-2 budget model, C-3 density axes) remain, which are out-of-scope for single-audit fixes.

---

## What does not need touching (confirmed stable)

Reaffirming from prior audits:

- PHASE state machine
- Renderer registry dispatch
- Plan/Group sync broker
- Tools overlay (earlier audits covered)
- SkinColors grammar (post-GV)
- Hint pipeline dynamic builder
- Error recovery contract surfaces (header/body/footer allocation)
- Canonical liveness allocation (pulse + microcopy + stall freeze)
- Body collapse and DENSITY tier thresholds
- Header tail trimming algorithm (`_DROP_ORDER_BY_TIER`)
- Footer artifact/action button rendering

---

## Conclusion

The tool call system is **production-ready**. The 3-axis design (PHASE × KIND × DENSITY) is fully realized. The visible gaps are **polish only**: hint row width handling, a microcopy stall color, a footer dedup race. All are MED/LOW severity and can ship as-is.

The system's biggest strength is **consistency**: every renderer speaks the same vocabulary, every action flows through the hint row or footer, every density tier has clear semantics. Future audits should focus on expanding this consistency outward (e.g., session-level status bars, keyboard map discovery) rather than fixing internal incoherence.

**No blockers. Ready for merge.**
