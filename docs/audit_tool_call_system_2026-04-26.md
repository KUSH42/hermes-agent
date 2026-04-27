# Tool Call System — Design & UI/UX Audit

**Date:** 2026-04-26
**Branch:** feat/textual-migration
**Scope:** the visual & interaction surface of a tool call from invocation to terminal state — `tool_blocks/`, `tool_panel/`, `tool_group.py`, `body_renderers/`, `services/tools.py`, plus the chrome that exposes it (hint row, footer, tools_overlay, prefix legend).
**Lens:** information design, discoverability, feedback legibility, density gracefulness, vocabulary consistency. Not a code-quality audit (see `audit_tui_full_2026-04-25.md` for that pass).
**Status:** DRAFT — findings, not specs. Each issue tagged with severity and a one-line fix sketch.

---

## Executive summary

The 3-axis frame (PHASE × KIND × DENSITY) declared in `docs/concept.md` is mature in the engine and the renderer registry. **Where it is still leaking is the user surface.** Discoverability is the biggest gap: 30+ keybindings live behind a 4-chip hint strip and an F1 modal, with a rotating tip lottery filling some of the slack. Density gracefulness — explicitly called out in `concept.md` as the missing seam — has been partly addressed by the `LayoutResolver`, but the footer still degrades binarily (visible | `display: none`) and `_DROP_ORDER_COMPACT` is willing to drop the *primary summary chip*. Several concept-level "is this thing alive?" surfaces (microcopy, phase chips, spinner, pulse, tail) compete instead of compose.

The findings group into six themes:

1. **Discoverability gap** — too many bindings, too few hints, two hint pipelines.
2. **Density gracefulness** — partial: footer/hero/compact/trace tiers don't share a row budget; user-override silent failure.
3. **"Is it alive?" multiplexing** — four parallel liveness signals with no canonical owner.
4. **Vocabulary leak** — gutter glyphs, separator dots, and chip formats live outside `_grammar.py`.
5. **Error surface fragmentation** — recovery info spread across header/footer/body/microcopy with no contract for which is canonical.
6. **Mode legibility** — kind-cycle and density-cycle hide their state; user has no preview.

Severity: **HIGH** = degrades a core path; **MED** = visible polish gap; **LOW** = consistency.

---

## 1. Discoverability gap

### D-1 [HIGH] — 30 bindings, 4 hints

**Where:** `tool_panel/_core.py:118–147` declares 30+ `Binding(... show=False)` entries. `tool_panel/_actions.py:21–23` defines three static hint tuples — `DEFAULT_HINTS` (5 items), `ERROR_HINTS` (4), `COLLAPSED_HINTS` (3) — that the hint row renders.

**Problem:** Power keys for paging the body (`+/-/*`), copying invocation (`I`), copying ANSI-preserved output (`C`), copying HTML (`H`), copying paths (`p`), opening URL (`O`), edit-cmd (`E`), tail-follow toggle (`f`), all the `j/k/J/K/</>` scroll bindings, density TRACE (`alt+t`), context menu (`?`) — none ever appear in the hint row. Users can only learn them by pressing `F1`. The rotating tip (HF-G, `tool_tips.current_tip()`) shows one hint at a time when wide & complete, which reaches some users some of the time but is essentially a lottery for keys you might *never* see in a session.

**Fix sketch:** Bucket bindings by *category* (copy, navigate, kind, recovery) and rotate hint sets by *what the focused block can do*. The discovery surface is `_build_hint_text` (already context-aware) but it's currently orphan code — see D-3.

### D-2 [HIGH] — `[t]` means kind, `alt+t` means density TRACE

**Where:** `tool_panel/_core.py:132,134`. `t` is `cycle_kind` (DIFF→CODE→PLAIN), `alt+t` is `density_trace`.

**Problem:** Same letter for two different *axis* concepts (KIND and DENSITY). The hint row exposes `[t] kind` in DEFAULT_HINTS (label "kind" — opaque); `alt+t` is unbound visually and only available via F1. `t` is also overloaded with `[T]rim`-style mental models from other terminal apps.

**Fix sketch:** Pick a non-conflicting density-cycle hotkey (e.g. `D`) and surface it conditionally in the hint row. Keep `t` bound to kind. Document the axis ↔ key mapping somewhere user-discoverable (concept.md already names the axes).

### D-3 [MED] — `_build_hint_text` is dead code

**Where:** `tool_panel/_actions.py:614`. Defined but never called from any production site (only a stale comment in `app.py:1868`).

**Problem:** Two hint pipelines exist. The live one is `_format(_select_hint_set())` which renders one of three static tuples. The orphaned one (`_build_hint_text`) is more sophisticated — checks `_block_streaming`, dedups against visible footer chips, splits primary/contextual, narrow-aware. **The better pipeline is unused.**

**Fix sketch:** Either delete `_build_hint_text` (cheap), or wire it as the live builder and retire the static tuples (better — closes D-1 in one move).

### D-4 [LOW] — Hint truncation hides what was lost

**Where:** `tool_panel/_actions.py:546–559` (`_format`).

**Problem:** When width < hint length, the algorithm pops items from the back-but-keeps-tail and inserts `…`. The dropped items are invisible. User sees `[Enter] expand · … · [f1] all` and has no way to know which keys disappeared.

**Fix sketch:** Either use a stable marker (`+N keys`) or expose dropped items as a tooltip on the hint row.

### D-5 [LOW] — F1 help is the only discovery for power-users, but never advertised at narrow widths

**Where:** `_build_hint_text:680–684`, hint truncation flow.

**Problem:** `[f1] all` is the documented escape hatch — but `_format` will drop it last only because the static tuples place it last. On a narrow terminal where width fits 1 hint, even F1 falls off. The truncation never preserves F1 specifically.

**Fix sketch:** Pin `[f1]` as the always-kept item even when the truncator pops the rest.

---

## 2. Density gracefulness

### Y-1 [HIGH] — Footer is binary (visible vs `display:none`); has no row budget

**Where:** `tool_panel/_footer.py:286–297` (`_refresh_visibility`); `body_renderers/_frame.py:39` (`BodyFrame.body-frame--compact > BodyFooter { display: none }`).

**Problem:** `concept.md` flagged this directly: *"footer cannot gracefully degrade — there is no central density resolver to negotiate."* The new `ToolBlockLayoutResolver` outputs `footer_visible: bool` (a binary), not a row count or chip-priority list. Result: in COMPACT tier the footer disappears entirely — losing exit code chip, stderr tail, retry action, artifact buttons. The header tail tries to compensate by keeping `exit/stderrwarn/remediation` last in the drop-order, but that's a fragile compensation, not a design.

**Fix sketch:** Extend `LayoutDecision` with a `footer_budget: int` (number of rows the footer may consume, 0–N). FooterPane renders chip-priority list against budget the way the header tail does. Compact = 1 row (chips only), default = 2 (chips + stderr_tail truncated), trace = unbounded.

### Y-2 [HIGH] — `_DROP_ORDER_COMPACT` will drop the primary summary chip (`hero`) at position 4

**Where:** `tool_panel/layout_resolver.py:81–92`.

**Problem:** Compact ordering: `chip, linecount, flash, diff, hero, chevron, duration, stderrwarn, remediation, exit`. Position 5 (`hero`) is the *primary summary* — the only segment that says **what the tool actually did** (e.g. `"  modified app.py"`). In COMPACT-tier narrow terminals the hero will routinely fall off, leaving the user staring at a dim icon and a label with no result information.

**Fix sketch:** In COMPACT, `hero` must be one of the last-kept (along with `exit`, `stderrwarn`, `remediation`). Move `hero` from index 4 → index 8. Compensate by dropping `diff` earlier when terminal is narrow (additions/deletions are derivable from the diff body anyway).

### Y-3 [MED] — User HERO override silently degrades to DEFAULT

**Where:** `layout_resolver.py:266–277`. If user requests HERO but `kind ∉ HERO_KINDS` or `body_line_count` ineligible, the resolver returns DEFAULT and emits a 1.2s `"hero unavailable"` flash (`_actions.py:80`).

**Problem:** Flash gives no reason. User retries `Enter` and gets the same flash, retries again — same result. The block *kind* is at fault but only the developer knows that.

**Fix sketch:** Flash should explain: `"hero unavailable — kind 'shell' not eligible"` or `"hero unavailable — body too long (12 > 8)"`. Reason is already computed as `decision.reason`; surface it in the message.

### Y-4 [MED] — TRACE-armed-pending is a hidden mode

**Where:** `_actions.py:117–119`. When user presses TRACE while STREAMING, override flags persist so post-completion auto-promotes; flash says `"trace pending — block still streaming"`.

**Problem:** Once flash fades (1.2s), the user has no indicator that TRACE is queued. If they switch focus and come back, no signal. If they press TRACE again, it flashes again — but they don't know it's already armed.

**Fix sketch:** When TRACE is armed-pending, show a subtle chip in the header tail (`"trace queued"`) until the post-completion resolve fires. Drop-order should keep this chip near the top of priority during the pending window.

### Y-5 [LOW] — Density cycle skips TRACE; cycle order is opaque

**Where:** `_actions.py:32–41` (`_next_tier_in_cycle`). Cycles `DEFAULT → COMPACT → HERO → DEFAULT`.

**Problem:** TRACE is not in the cycle (intentional — it's a diagnostic), but the user can't see this. There's no preview "next tier: COMPACT". After 3 presses they're back where they started without indication of what the cycle visited.

**Fix sketch:** Flash the destination tier on each cycle (`"compact"` / `"hero"` / `"default"`). Document TRACE as alt+t-only.

---

## 3. "Is it alive?" multiplexing

### A-1 [MED] — Four concurrent liveness signals

**Where:**
- Header icon `PulseMixin` (animated color lerp, `_header.py:240–244`)
- Header tail `_spinner_char` segment (`_header.py:270–280`)
- ToolCallHeader phase chip (`"…starting"`, `"…finalizing"` — `_header.py:799–885`)
- Body microcopy line (`▸ 12 lines · 3.4 kB · 200 kB/s`, `streaming_microcopy.py`)
- (and PulseMixin's gutter focus highlight `┃` while focused)

**Problem:** All five signal "this tool is doing something." None of them is canonical. The phase chip says `…starting` for 0.8s, then disappears; the spinner runs the entire stream; the icon pulses the entire stream; the microcopy updates per line. A user trying to understand "where in the lifecycle am I?" must integrate four signals.

**Fix sketch:** Pick one canonical phase indicator per phase. Suggested allocation:
- `STARTED` only: `…starting` chip + dim icon (no pulse yet — nothing to pulse over).
- `STREAMING`: pulse + microcopy. No phase chip (redundant).
- `COMPLETING`: `…finalizing` chip; pulse settles.
- `DONE/ERROR`: settled icon, no chip, no pulse.

The current code essentially does this *except* the spinner char in the tail duplicates the pulse. Pick one.

### A-2 [LOW] — Microcopy stall indicator (`⚠ stalled?`) competes with spinner

**Where:** `streaming_microcopy.py:81–83`. Appends `⚠ stalled?` when no output for 5s+.

**Problem:** While stalled, the spinner is *still spinning* (the renderer doesn't gate on stall). User sees pulsing icon + "stalled" text — contradictory. Spinner should freeze when stalled.

**Fix sketch:** Pulse mixin should consult a `_stalled` flag (already computable from elapsed_since_last_byte) and switch to a static "paused" icon.

---

## 4. Vocabulary leak

### V-1 [MED] — Gutter glyphs live in `_header.py`, not `_grammar.py`

**Where:** `_header.py:213–227`. Five distinct gutter treatments:
- child: `"    "` (4 spaces)
- child_diff: `"  ╰─"`
- focused: `"  ┃ "`
- default: `"    "`
- group: `"  ┊ "` (in `tool_group.py:195`)

**Problem:** These are *vocabulary* (the alphabet, per concept.md). They should live in `body_renderers/_grammar.py` next to `GLYPH_META_SEP` etc. Today a skin can redefine `tool_header_gutter` *color* but not the *glyph*. A skin author who wants Unicode-clean output has no path.

**Fix sketch:** Add `GLYPH_GUTTER_FOCUSED`, `GLYPH_GUTTER_GROUP`, `GLYPH_GUTTER_CHILD_DIFF`, etc. to `_grammar.py`. ToolHeader and GroupHeader read through `glyph()` lookup.

### V-2 [LOW] — Separator dot `·` hardcoded across three sites

**Where:**
- `_header.py:410` uses `_glyph(GLYPH_META_SEP)` ✓ correct
- `_actions.py:548` uses `" · "` ✗ literal
- `_footer.py:333` uses `"  "` ✗ literal (no separator)
- `streaming_microcopy.py:78` uses `f" · "` ✗ literal

**Problem:** Hint row, microcopy, and footer can't be re-vocabularied by skin.

**Fix sketch:** Replace literals with `_grammar.GLYPH_META_SEP` lookup.

### V-3 [LOW] — Chip format split

**Where:**
- Hint row: `[y] copy` — bracket + space + label
- Footer action chip: `[y] copy` — same (good — `_footer.py:496`)
- Collapsed strip: `("y", "copy")` rendered as `y copy` (no brackets, see `_footer.py:69`)
- Body footer chips (BodyFooter from grammar): own format

**Problem:** The "press a key for X" idiom has three formats. Pick one.

**Fix sketch:** Standardize on `[key] label`. Document in `_grammar.py` as the chip vocab.

---

## 5. Error surface fragmentation

### E-1 [HIGH] — Recovery info smeared across 5 surfaces

**Where:** Single error block can simultaneously show:
- Header icon (red/error variant) + error_kind icon swap (`_header.py:230–237`)
- Header tail: `exit N` chip, `⚠ stderr (e)` chip, `hint:remediation` chip
- Body: stays expanded (modal override per concept.md)
- Footer: stderr_tail (8 lines), auto-injected `retry` action chip, auto-injected `copy err` chip
- Hint row: ERROR_HINTS variant

**Problem:** Five places to say "this errored." The user's eye must scan each. No declared canonical "first read" — the design lacks a primary recovery affordance. Every audit (audit1, audit3, audit4) has touched a piece but the *whole* never lined up.

**Fix sketch:** Declare a recovery contract: **header surfaces the *category* of error (icon + exit chip), footer surfaces the *recovery action* (retry button), body surfaces the *evidence* (stderr_tail).** Strip duplication: don't put `⚠ stderr` chip in header AND `copy err` button in footer for the *same* stderr — pick one. Drop hint:remediation chip from header (footer is the recovery surface).

### E-2 [MED] — Action auto-injection mutates the contract

**Where:** `_footer.py:384–391` (auto-inserts `retry` if missing on error); `_footer.py:393–400` (auto-inserts `copy_err` if stderr_tail).

**Problem:** Callers building `ResultSummaryV4.actions` think they own the action list. The footer silently injects two more. A test asserting `len(actions) == N` is wrong by definition. A renderer reading `summary.actions` to decide layout sees one list; the footer renders a different one.

**Fix sketch:** Move the auto-injection into `ResultSummaryV4.actions` building (single source of truth) at parse time, not render time.

### E-3 [LOW] — `is_error` definition drift

**Where:** `_actions.py:541–544` (`_is_error` checks `exit_code not in (None, 0)`); `services/tools.py` `ToolCallViewState.is_error` (separate field set by terminalize); footer uses `summary.is_error` (third path).

**Problem:** Three "is this an error?" checks with overlapping but not identical semantics. Tool-cancellation (CANCELLED phase) is treated differently by each.

**Fix sketch:** Single `is_error_for_ui()` helper on view state; everyone reads from it.

---

## 6. Mode legibility

### M-1 [MED] — Kind cycle hides current state

**Where:** `_core.py:134` (`t` → `cycle_kind`). Affordance hint says `[t] kind`.

**Problem:** User presses `t` and the renderer changes. They have no idea what *current* kind is, and no preview of the cycle. Cycling to a wrong kind (e.g. JSON view of a binary blob) gives them garbage with no "press t to undo" path beyond cycling forward through all kinds.

**Fix sketch:** Hint should show `[t] kind: code → plain`. Cycle should either preview-on-hover (not feasible in TUI) or include `[T]` (shift+T) to go *backward*. Memory's KO-A..KO-D entries already record some of this work; this is the remaining gap.

### M-2 [LOW] — Group widget is keyboard-invisible

**Where:** `tool_group.py:162` — `GroupHeader.can_focus = False`.

**Problem:** GroupHeader has a `▸/▾` toggle and shows aggregate diff stats — it's a meaningful interactive element. But you can't tab to it. `shift+enter` peek_focused works on the *child* panel, not the group. A user navigating with keyboard skips groups entirely; they can only collapse a group by clicking it.

**Fix sketch:** `can_focus = True`; bind `enter` on group to toggle; bind `shift+enter` on group to peek-collapse-siblings (current `peek_focused` behavior). Add `[Enter] toggle group` to hint when group is focused.

### M-3 [LOW] — Spinner color identity is undocumented

**Where:** `_header.py:271–280` — `_spinner_identity` provides `color_a, color_b, phase_offset` per tool, lerp animated.

**Problem:** Each tool gets a "color personality" in the spinner — cute, but undocumented (no skin override, no accessibility note, not surfaced to users as meaningful). It's effectively decoration that violates the "vocabulary, not axis" rule (a skin cannot override per-tool colors).

**Fix sketch:** Either pull `SpinnerIdentity` colors from `SkinColors.tier_accents[category]` (so skins reach it), or simplify to a single accent and delete `_spinner_identity`. Lean toward the latter — the personality buys nothing the user can name.

---

## Cross-cutting observation: the hint row is doing two jobs

The hint row at the bottom of the panel is asked to be both:
- **A discovery surface** (here are the things you can do)
- **A status surface** (here is what just happened — flashes, tip rotation)

These compete for the same row. The flash mechanism (`_flash_header`) actually targets the *header*, but the header is already crowded. The hint row briefly gets HF-G's rotating tip. There is no surface that is *only* status — `feedback_service` provides one but its render target is varied.

**Suggestion:** Make the hint row purely discovery. Move flashes/tips to a dedicated single-row strip below the body but above the footer (or fold into the existing microcopy slot, which becomes empty post-streaming anyway).

---

## What is NOT broken (so don't touch it)

Tracking these explicitly so future audits don't waste cycles re-litigating them:

- **PHASE state machine** (`services/tools.py::ToolRenderingService._set_view_state`) — single choke-point, well-tested, do not refactor.
- **Renderer registry dispatch** (`body_renderers/__init__.py::pick_renderer`) — `(phase, kind, density)` signature is the right contract; R-2A/R-2B settled it.
- **SkinColors grammar tokens** — vocabulary is well-defined for *colors*; the gap is glyphs (V-1).
- **Plan/Group sync** (PG-1..PG-4 in MEMORY.md) — broker pattern is correct; no UX-visible issue.
- **Tools overlay** (`tools_overlay.py`) — recently audited (DC-1..DC-4 discoverability work); the prefix legend, gantt, and KNOWN_PREFIXES contract are in good shape.

---

## Recommended next moves (sequencing)

In order of UX leverage per spec-effort:

1. **D-3 + D-1** (paired): wire `_build_hint_text` as the live builder, retire static tuples. Half a day. Closes the largest single discoverability gap. ~10 tests.
2. **Y-1 + Y-2**: extend `LayoutDecision.footer_budget` and fix `_DROP_ORDER_COMPACT` ordering. ~25 tests. Resolves the explicit gap in concept.md §What this frame buys.
3. **E-1**: declare the recovery contract (header=category, footer=action, body=evidence) and dedupe. ~20 tests. Touches several files but each change is small.
4. **A-1**: pick canonical liveness signal per phase. ~15 tests. Mostly deletion.
5. **V-1 + V-2**: glyph vocabulary cleanup. ~10 tests. Pure mechanical sweep — good worktree task.
6. **M-1**: kind-cycle preview hint. ~8 tests. Small, high satisfaction.
7. **M-2**: GroupHeader focus + enter binding. ~12 tests. Low risk.

The remaining issues (D-2, D-4, D-5, Y-3, Y-4, Y-5, A-2, V-3, E-2, E-3, M-3) cluster naturally as a "polish pass" worktree: ~30 tests, half-day of work.

Two specs of HIGH severity (D-1+D-3, Y-1+Y-2, E-1) plus one polish pass should close this audit's findings. None of them require touching the PHASE state machine or the renderer registry.
