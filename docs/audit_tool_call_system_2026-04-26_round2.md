# Tool Call System — Deep UX/Design Audit, Round 2

**Date:** 2026-04-26 (post-merge sweep)
**Branch:** feat/textual-migration
**Predecessor:** `audit_tool_call_system_2026-04-26.md` (DRAFT, same day)
**Scope:** UX/design only — discoverability, feedback legibility, density gracefulness, vocabulary, error/lifecycle UX, keyboard navigation, narrow-terminal behavior. Not code quality.
**Status:** DRAFT — fresh findings only. Closure verification of round-1 items at the bottom.

---

## Why a round 2

Six specs landed today against round-1 findings (Hint Pipeline H-1..H-4, Mode Legibility ML-1..ML-5, Glyph Vocabulary GV-1..GV-4, Error Recovery ER-1..ER-5, Canonical Liveness CL-1..CL-6, Polish Pass P-1..P-9) plus Header/Affordance Widths HW-1..HW-6. Round 1 was written *concurrently* with several of those landings, so its severity grades and "next moves" don't reflect the current tree. Round 2 reads the merged result and asks: **what did we miss, what did we leave half-finished, and what did the implementations themselves expose?**

Verdict up front: **the system is in good shape.** No HIGH-severity finding survives. The remaining gaps are MED-severity polish around discoverability at narrow widths and one deferred keyboard-affordance item (M-2). The bigger insight is *where the design intent is now leaking through implementation choices* — see the cross-cutting section.

Severity legend unchanged: HIGH = degrades core path; MED = visible polish gap; LOW = consistency.

---

## Fresh findings

### F-1 [MED] — Truncation marker `+N more` is opaque

**Where:** `tool_panel/_actions.py` `_truncate_hints` path (~line 780).

**Problem:** When the hint row overflows, dropped contextual hints collapse to a literal `+N more` string. The user sees `[Enter] expand · +2 more · [F1] all` and cannot guess whether the dropped 2 are `[y] copy` and `[r] retry` or `[I] copy invocation` and `[*] all kinds`. F1 is the documented escape hatch, but power users widen the terminal to *learn* the keys, not to recover them — and `+N more` gives them no nudge in either direction.

D-4 in round 1 raised this as LOW. Post-implementation it's MED, because the dynamic builder now *generates more variety* than the static tuples ever did, so more hints get truncated more often. A fix that was cosmetic before is functional now.

**Fix sketch:** Render the dropped keys without their labels: `+y/r/*`. ~3 keys still fits where the labels would not, and the user can press to discover the verb. If even the `+y/r/*` form overflows, fall back to `+N more` only at extreme narrowness.

### F-2 [MED] — Width threshold for contextual hints is a cliff, not a slope

**Where:** `_actions.py` (~line 782 — `width < 50` branch suppresses all contextual hints).

**Problem:** At 50 cells the user gets `[Enter] expand · [y] copy · [t] kind: code → plain · [F1] all`; at 49 they get `[Enter] expand · [F1] all`. One column drop, two-thirds of the affordances disappear. The threshold is hardcoded and doesn't measure actual content. Users on 80-col SSH terminals don't notice; users on tiled WMs and split panes do.

**Fix sketch:** Use the existing `_truncate_hints` packing budget for contextual hints too. Pack until budget exhausted, then `+N more`. Drop the `width < 50` short-circuit entirely — let the packer decide.

### F-3 [CLOSED] — GroupHeader vs ToolGroup focus confusion

**Where:** `tool_group.py:312` (`ToolGroup.can_focus = True`); bindings `enter`→`action_toggle_collapse`, `shift+enter`→`action_peek_focused` at 316–319.

**Status:** False positive. `can_focus=False` at line 162 is on the inner `GroupHeader` display widget — focus actually lands on the outer `ToolGroup`, which has bindings and a `:focus > GroupHeader { background: $boost }` style that highlights the header. Keyboard story works in the opt-in `tool_group_widget` pathway. CSS-virtual-grouping has no widget to focus by design.

### F-4 [LOW] — Accessibility-mode glyph map missing gutter additions

**Where:** `body_renderers/_grammar.py:34–40`. `_ASCII_GLYPHS` covers `▸ │ · ── …` but not the gutter glyphs added in GV-1 (`┃ ╰─ ┊`).

**Problem:** GV-1 centralized gutter glyphs but did not extend the accessibility fallback. Users running with `accessibility_mode()` on still see Unicode box-drawing in the gutter column — the *one* place an a11y user is most likely to want ASCII for screen-reader friendliness. Severity LOW because gutters are decorative-structural, not semantic, but this is a one-line fix and it closes the loop on GV-1.

**Fix sketch:** Add `"┃": "|"`, `"╰─": "\\-"`, `"┊": ":"` to `_ASCII_GLYPHS`.

### F-5 [CLOSED] — Footer auto-injection at parse time

**Where:** `tool_result_parse.py:262` (`inject_recovery_actions`); `_footer.py:357` (render reads `summary.actions` unmutated).

**Status:** Already closed via P-4. `inject_recovery_actions(summary)` is idempotent and runs at parse time; footer render uses `summary.actions` directly. Round-2 finding was based on stale read — leaving entry here so future audits don't re-litigate.

### F-6 [LOW] — `_spinner_identity` lingers as dead state

**Where:** `tool_panel/_header.py` (per Explore report — `SpinnerIdentity` struct is built per block but its tail segment was removed in CL-1).

**Problem:** CL-1 deleted the spinner tail glyph, but `SpinnerIdentity` instantiation and per-tool color lerp computation still run for every STREAMING block. Output goes nowhere. Negligible perf cost; nontrivial code-comprehension cost — a future reader will assume it's load-bearing.

**Fix sketch:** Delete the `_spinner_identity` field and the lerp call. Pulse mixin is the canonical liveness signal per CL-1.

### F-7 [LOW] — Hero `min_width` of 100 cells is undiscoverable

**Where:** `tool_panel/layout_resolver.py` — `DEFAULT_HERO_MIN_WIDTH = 100`.

**Problem:** Y-3 surfaced rejection reason in the flash, which is good. But the *threshold* itself is invisible. A user on an 80-col terminal will press `Enter` for HERO, see `"hero unavailable — terminal too narrow (80 < 100)"`, and reasonably ask: "is this a per-tool limit or a global one? Will resizing fix it?" The flash answers the first question and not the second.

LOW because most users don't care about the mechanism. But the message is one word away from being self-explanatory: `"hero needs 100 cols (got 80) — widen the terminal"`.

**Fix sketch:** Reword the flash. No code-shape change.

---

## Cross-cutting observations

### C-1: The hint row has won — the body footer should retreat

The dynamic hint pipeline (H-series) is now the strongest discovery surface in the system. It dedups against footer chips, branches on streaming/error/focus, and pins F1. **The footer is duplicating its job.** Action chips like `[y] copy` show up in both places when the hint row decides not to suppress them.

Round 1 said "make the hint row purely discovery, move flashes elsewhere." Post-merge, the *opposite* problem is more pressing: the hint row has become more authoritative than the footer for "what can I do here?" Yet the footer still injects its own action chips and renders them as primary.

Suggestion: reverse the dedup direction. Hint row becomes canonical for keyboard affordances; footer chips render only as *status indicators* (exit code, stderr_tail, copy result toast). Action verbs migrate fully to the hint row. This would simplify the footer significantly and remove the auto-injection contract drift in F-5.

Not a finding (no bug) — a design trajectory the next audit should weigh.

### C-2: Density tier transitions are still per-axis, not per-budget

`LayoutDecision` exposes `tier`, `footer_visible`, `body_height`, etc. as parallel scalars. The COMPACT/DEFAULT/HERO tiers feel like **named presets** rather than **budget shapes**. When users override one axis (HERO), other axes don't negotiate around it — they obey the preset.

The 3-axis frame in `concept.md` implies this should be per-axis. The implementation is per-tier. This is fine for now (the tiers are well-chosen), but a future audit should ask whether `LayoutDecision` should be replaced by a `LayoutBudget` (rows for header/body/footer/hint, plus density-class flag) and renderers consume that. Out of scope for round 2 fixes.

### C-3: Microcopy is the quiet workhorse

`streaming_microcopy.py` updates on every line, freezes on stall, and provides the only continuously-updating "this is alive and progressing" text. It's also the only surface that exposes throughput (kB/s). It is doing more design work than its line count suggests — and getting no skin styling, no truncation testing, no narrow-terminal fallback. At <50 cells it currently overflows the body region (untested).

Recommend: add microcopy to the next narrow-terminal pass. Not a finding because no bug observed; a known unknown.

---

## Round-1 closure verification

Recapping what closed and what didn't, against round-1 IDs:

| Round-1 ID | Status | Notes |
|---|---|---|
| D-1 (30 bindings, 4 hints) | CLOSED via H | dynamic builder + context-aware |
| D-2 (`[t]` overload) | CLOSED via H/ML | `D` for density, `t` for kind |
| D-3 (`_build_hint_text` orphan) | CLOSED via H | now canonical |
| D-4 (truncation hides loss) | **OPEN, promoted to MED** | see F-1 |
| D-5 (F1 advertising) | CLOSED via H | F1 pinned |
| Y-1 (footer binary) | CLOSED (acceptable) | no row budget but `display:none` is OK at COMPACT |
| Y-2 (hero drop position) | CLOSED via HW | hero now position 6 in compact order |
| Y-3 (hero override flash reason) | CLOSED | flash includes reason; F-7 nits the wording |
| Y-4 (TRACE-armed-pending hidden) | CLOSED | `trace_pending` chip in tail |
| Y-5 (cycle order opaque) | CLOSED via P | tier flash on cycle |
| A-1 (4 liveness signals) | CLOSED via CL | spinner deleted, phase chips deleted; F-6 leftover |
| A-2 (stall vs spinner) | CLOSED via CL | `_pulse_paused` on stall |
| V-1 (gutter glyphs in `_header.py`) | CLOSED via GV | grammar constants |
| V-2 (separator dot literal) | CLOSED via GV | `GLYPH_META_SEP` lookup |
| V-3 (chip format split) | CLOSED via GV | `chip()` helper unified |
| E-1 (5-surface error smear) | CLOSED via ER | header=category, body=evidence, footer=action |
| E-2 (action auto-injection) | CLOSED via P-4 | `inject_recovery_actions` at parse time; footer reads unmutated |
| E-3 (`is_error` drift) | CLOSED via ER | unified helper |
| M-1 (kind cycle hides state) | CLOSED via ML | caption + revert binding + preview |
| M-2 (GroupHeader focus) | CLOSED | `ToolGroup.can_focus=True` + bindings; round-1 misread inner `GroupHeader` |
| M-3 (spinner color identity) | CLOSED via CL | spinner deleted, identity dead-state per F-6 |

Open round-1 items: 1 (D-4 → F-1). Plus 4 fresh round-2 findings (F-2, F-4, F-6, F-7).

---

## Recommended sequencing

Two small worktrees should close round 2:

**Worktree A — narrow-terminal hint hardening** (~10 tests)
- F-1 (truncation marker shows keys)
- F-2 (drop the width<50 cliff)
- F-7 (hero flash wording)

**Worktree B — cleanup** (~6 tests)
- F-4 (accessibility glyph extension)
- F-6 (delete dead spinner code path: `_spinner_char` branch + `_spinner_identity`)

Total: ~16 tests. None touch the PHASE state machine, renderer registry, or skin contract. After these, the only carryover is C-1 (hint vs footer authority) which is design-trajectory work, not bug-fix work — defer to a future audit.

---

## What still does not need touching

Tracking this so round 3 doesn't re-litigate:

- PHASE state machine (`services/tools.py`)
- Renderer registry dispatch (`body_renderers/__init__.py`)
- Plan/Group sync broker (PG-1..PG-4)
- Tools overlay (DC-1..DC-4 holds up)
- SkinColors grammar (post-GV)
- Hint pipeline H-1..H-4 (current canonical builder)
- ER recovery contract surfaces (header/body/footer allocation)
- CL liveness allocation (pulse + microcopy + stall freeze)
