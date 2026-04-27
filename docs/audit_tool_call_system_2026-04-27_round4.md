# Tool Call System — Design & UX Audit, Round 4

**Date:** 2026-04-27
**Branch:** feat/textual-migration
**Status:** DRAFT
**Predecessors:**
- audit_tool_call_system_2026-04-26.md (Round 1)
- audit_tool_call_system_2026-04-26_round2.md (Round 2)
- audit_tool_call_system_2026-04-27.md (Round 3, 8 findings MED/LOW)

**Scope:** UX/design only — visual hierarchy, lifecycle legibility, density gracefulness,
affordance discovery, error recovery, group/plan coherence, renderer consistency, skin
contract, motion/feedback, information architecture. Excludes anything raised in
Rounds 1–3 unless regressed.

---

## Executive summary

Round 4 reads a system that has converged. Three rounds plus the post-merge polish
specs (HW, P-, ER-, CL-, ML-, GV-, H-, MCC) have closed the structural gaps and most
of the polish gaps. The eight findings below are real but small: one is a HIGH because
two bindings perform the same multi-step density action with hints that lie about the
behaviour; the rest are MED/LOW skin-contract leaks and renderer-family inconsistencies
that slipped past Round 3's spot-check.

**Finding count:** 1 HIGH, 3 MED, 4 LOW. Compared to Round 3 (0 HIGH, 5 MED, 3 LOW),
this is consistent — discovery rate continues to fall as the system stabilises. Each
finding is precise enough to spec without re-investigation.

Severity legend unchanged: HIGH = degrades a core path; MED = visible polish gap;
LOW = consistency / correctness.

---

## Findings

### R4-1 [HIGH] — `Enter` performs a 3-way density cycle but advertises itself as a binary toggle

**Where:** `tool_panel/_actions.py:46–88` (`action_toggle_collapse`) bound to `Enter` in
`tool_panel/_core.py:119`. Hint pipeline labels it `"Enter toggle"` /
`"Enter expand"` (`_actions.py:678–686`).

**What user sees today:**

- Block in DEFAULT, body visible. User presses Enter. Tier becomes COMPACT — body
  collapses. Microcopy / flash reads `"compact"`.
- User presses Enter again expecting to expand. Tier becomes HERO. Body sometimes
  re-expands (eligible kind, ≤8 lines, terminal ≥100 cols), sometimes the user gets
  the warning flash `"hero unavailable — kind shell not eligible"`.
- A third Enter brings them back to DEFAULT. The "toggle" hint is wrong on the
  second press and on every press for ineligible blocks, where Enter cycles to a
  state that immediately rejects.

**Why it's wrong:**

Round 3 confirmed the canonical D key for density cycle (`Binding("D", "density_cycle", …)`)
was added in H-4 / P-9. But `action_toggle_collapse` was never narrowed back to a
binary expand/collapse. Both Enter and D now run essentially identical bodies — they
both call `_next_tier_in_cycle(self._resolver.tier)`, set override flags, resolve, and
flash. This duplicates the action and conflicts with the hint copy ("toggle" implies
boolean, "cycle" is what actually happens).

Worse, ChildPanel (`tool_panel/_child.py:70–71`) overrides `action_toggle_collapse`
to a true boolean toggle (`self.collapsed = not self.collapsed`). So **Enter behaves
differently** for parent ToolPanel (cycle) vs ChildPanel (toggle). Users navigating a
nested call sequence get inconsistent affordances on the same key.

**What user should see:**

Enter is a binary expand/collapse toggle. `D` is the explicit cycle. The hint reads
`"Enter expand"` / `"Enter collapse"` (verbatim) and, when in COMPACT, `"Enter expand"`
takes the user back to DEFAULT — never up to HERO. HERO is reachable only via the
explicit `D` cycle. ChildPanel and ToolPanel match.

**Concrete fix sketch:**

1. Rewrite `action_toggle_collapse` (`_actions.py:46–88`) to:
   - If current tier is COMPACT: set override to DEFAULT, resolve, flash `"expanded"`.
   - Else (DEFAULT or HERO): set override to COMPACT, resolve, flash `"collapsed"`.
   - Drop the `_next_tier_in_cycle` call.
2. Update hint labels in `_collect_hints` (`_actions.py:677–686`) to read `"expand"` /
   `"collapse"` based on current tier. Already partly there for COLLAPSED; needs the
   inverse branch.
3. Delete the override of `action_toggle_collapse` in `_child.py:70–71` — it now matches
   parent semantics by default.
4. Keep `action_density_cycle` on D unchanged — the explicit power-user path.

Tests: rotate Enter from DEFAULT, COMPACT, HERO and assert tier sequence. Verify the
hint label flips with current tier. Verify ChildPanel agrees.

---

### R4-2 [MED] — Footer chip tones bypass `SkinColors`; skins cannot retheme footer

**Where:** `tool_panel/_footer.py:32–38`:

```
_TONE_STYLES: dict[str, str] = {
    "success": "bold green",
    "warning": "bold yellow",
    "error": "bold red",
    "accent": "",
    "neutral": "dim",
}
```

**What user sees today:** Footer chips render with terminal ANSI named colors. A skin
defining custom hex tokens for `$success`, `$warning`, `$error` (the documented
SkinColors contract) sees those values applied **everywhere except** the footer chip
tones, which keep terminal-default hues.

**Why it's wrong:** Round 3 finding 7 fixed this for the streaming microcopy stall
warning (`SkinColors.warning`), and Round 3 cross-cutting C-4 explicitly stated *"all
renderers use SkinColors"*. The check was over the renderer set; it skipped the
footer. The footer is in the design vocabulary's reach (`_grammar.py` even ships a
`BodyFooter` that does honour SkinColors). The panel's `FooterPane` is asymmetric.

**Concrete fix sketch:**

Move tone resolution to render time. In `FooterPane._render_footer`
(`_footer.py:320`), resolve `SkinColors.from_app(self.app)` once and replace the
`_TONE_STYLES` lookup with a function that returns
`f"bold {colors.success}"` / `f"bold {colors.warning}"` / `f"bold {colors.error}"`
keyed off `chip.tone`. Keep `accent` and `neutral` as today. Delete the
`_TONE_STYLES` map.

Tests: assert footer chip tone style for a custom-skin'd app uses the skin's hex,
not "green"/"yellow"/"red".

---

### R4-3 [MED] — `EmptyStateRenderer` and `FallbackRenderer` skip `BodyFrame`

**Where:** `body_renderers/empty.py:62–66` returns a bare `Static(msg, classes="empty-state")`.
`body_renderers/fallback.py:27–43` builds a Rich Text and relies on the default
`build_widget` (which wraps in `CopyableRichLog`, no frame). Compare with the eight
Phase C renderers that all return `BodyFrame(...)` (code, diff, json, log, search,
shell, table — see `_frame.py` and grep results in audit research).

**What user sees today:** A code block, table, or diff result is wrapped in a
`BodyFrame` with `body-frame--header` / `body-frame--body` / `body-frame--footer`
slots and tier-aware density classes (`.body-frame--compact`, `.body-frame--hero`,
`.body-frame--trace`). An empty result or low-confidence text fallback does **not** —
it renders as a flat Static or RichLog. Visual outcomes:

1. The compact / hero / trace tier classes do not apply to empty / fallback bodies.
   They render at full body size regardless of density.
2. The `BodyFooter` affordance row (`y copy` etc.) is missing for empty / fallback.
3. The body slot does not carry the `body-frame--body` class, so any skin selector
   targeting that class misses these two renderers.

**Why it's wrong:** Round 3 C-4 claimed the renderer family is consistent. Spot
check missed empty + fallback because they're rare. They are still part of the
family — empty fires whenever `kind == EMPTY`, fallback fires for low-confidence or
TEXT — and they break the contract every other renderer upholds.

**Concrete fix sketch:**

1. `EmptyStateRenderer.build_widget`: wrap the Static in `BodyFrame(header=None,
   body=Static(msg), footer=None, density=density)`. Pass density from caller (already
   threaded via `build_widget(density=...)` for other renderers). Footer is None
   because empty state has no copy affordance, but the frame's tier classes still apply.
2. `FallbackRenderer`: override `build_widget` to wrap the Rich Text in
   `BodyFrame(header=None, body=CopyableRichLog(...), footer=BodyFooter(("y", "copy")),
   density=density)`. Keep the `unclassified · plain text` rule inside the body.

Tests: assert each of the 10 renderers returns a `BodyFrame` (or a widget mounted
inside one) when `build_widget` is invoked. Property test on the registry, not
per-renderer.

---

### R4-4 [MED] — Header flash error tone uses ANSI `"red"` literal as fallback when CSS lookup fails

**Where:** `tool_blocks/_header.py:319–326`:

```
if self._flash_tone == "error":
    try:
        _err_color = self.app.get_css_variables().get("status-error-color", "red")
    except Exception:
        _err_color = "red"
    _flash_style = f"dim {_err_color}"
```

**What user sees today:** When the app has not finished mounting, or when a worker
calls `_flash_header(..., tone="error")` from outside the main loop, the CSS lookup
fails and the flash falls back to bare ANSI `red`. The rest of the codebase has
moved to `SkinColors.error` for hex consistency; this one site holds the ANSI token.

**Why it's wrong:** Skin contract leak, parallel to R4-2 but for header rather than
footer. The header has access to `SkinColors` already (`self._colors().error` is
called for the icon color logic just below). The flash branch should use it too.

**Concrete fix sketch:**

Replace lines 322–326 with `_err_color = self._colors().error`. Drop the
`get_css_variables` call entirely — `SkinColors.from_app` already handles the
fallback chain at construction time.

Tests: assert flash style for tone="error" uses `colors.error` hex, not `"red"`.

---

### R4-5 [LOW] — Hardcoded HERO chevron glyph `★` is not in `_grammar.py`

**Where:** `tool_blocks/_header.py:303–313`. The chevron column glyph for HERO tier
is `"  ★"` inline. Collapsed and expanded glyphs (`▸`, `▾`) are also inline. None of
these go through `_grammar.glyph()` and none have an ASCII fallback in
`_ASCII_GLYPHS`.

**What user sees today:** When `accessibility_mode()` is on, `▸` and `▾` get ASCII
fallbacks via `glyph()` *elsewhere in the codebase* (e.g. microcopy gutter). In the
header chevron slot, they don't, and `★` has no fallback at all. A screen-reader user
running in accessibility mode hears `"star"` for HERO and the raw box glyphs for
collapse/expand.

**Why it's wrong:** GV-1..GV-4 centralised gutter glyphs; this is a residue. Round 2
F-4 fixed three gutter glyphs in `_ASCII_GLYPHS` but missed the chevron column. The
chevron is decorative — but consistency demands it pass through grammar.

**Concrete fix sketch:**

Add three new constants to `_grammar.py`:

```
GLYPH_CHEVRON_HERO     = "★"
GLYPH_CHEVRON_COLLAPSED = "▸"
GLYPH_CHEVRON_EXPANDED  = "▾"
```

Add fallbacks to `_ASCII_GLYPHS`: `"★": "*"`, `"▾": "v"` (`▸` already mapped).
Replace inline literals in `_header.py:305–309` with `_glyph(GLYPH_CHEVRON_*)`.

Tests: assert accessibility-mode header renders `*` / `>` / `v` for HERO / collapsed
/ expanded chevron states.

---

### R4-6 [LOW] — Microcopy `_GUTTER` `"▸ "` is inline; not in `_grammar.py`

**Where:** `streaming_microcopy.py:65` — `_GUTTER = "▸ "` module-private constant.

**What user sees today:** The microcopy gutter renders identical to the path-header
gutter (`build_path_header` uses `glyph("▸")` from `_grammar.py`). They look the same
because they happen to be the same glyph. They aren't connected — if grammar
introduces a new gutter shape, microcopy keeps the old one until manually updated.

**Why it's wrong:** Coordination drift. The two surfaces — header gutter and
streaming microcopy gutter — are visual peers (both anchor the leading column of a
"this is a tool" line). Round 2 GV-1 routed gutter glyphs through grammar but missed
this one because microcopy is not a renderer.

**Concrete fix sketch:**

Replace `_GUTTER = "▸ "` with `from hermes_cli.tui.body_renderers._grammar import
GLYPH_HEADER, glyph as _glyph`. Use `f"{_glyph(GLYPH_HEADER)} "` at the call site
(line 90 in `_microcopy_text`). Note the existing import `from
hermes_cli.tui.body_renderers._grammar import GLYPH_META_SEP, glyph as _glyph,
GLYPH_WARNING` is already present in this file.

Tests: existing microcopy tests already exercise this; just retarget the constant.

---

### R4-7 [LOW] — `feedback.py` has 13 `except Exception: pass` swallows in user callbacks

**Where:** `services/feedback.py`. Lines 93, 237, 311, 393, 419, 446, 451, 478, 484,
523, 549, 573 — most wrap `state.on_expire(reason)` callbacks or
`adapter.restore()` calls. Per `.claude/CLAUDE.md`:

> `except Exception: pass` is **always wrong**.

**What user sees today:** A buggy `on_expire` callback raises an exception. The
exception is silently swallowed; the flash service keeps running. The bug is
invisible to the developer and to anyone reading the log. The user experience is a
flash that vanished early or a widget that didn't restore but no clue why.

**Why it's wrong:** Project rule violation, but the UX impact is real: feedback is
the system's main "did this affordance work?" signal. Silent swallows turn buggy
adapters into unexplained UI inconsistencies. Round 3 didn't audit feedback.py for
exception hygiene because the focus was UX surfaces, not service plumbing — but the
plumbing fails in ways that look like UX bugs.

**Concrete fix sketch:**

Replace `except Exception: pass` with `except Exception: _log.exception("flash %s
callback failed", channel_or_state_id)` for every site. The 13 instances cluster into
three patterns:

1. `state.on_expire(reason)` callbacks — log with the channel name + reason.
2. `adapter.restore()` calls — log with the channel name; restore can't undo the
   state mutation, so loud is correct.
3. `Timer.stop()` (`_TimerCancelToken.stop`, line 93) — the only legitimate swallow
   on this list (a stopped timer raising is harmless), but it should still be
   `_log.debug("timer.stop raised after expiry", exc_info=True)` not `pass`.

Tests: monkey-patch a flash callback to raise; assert the log captures it with
`exc_info`.

---

### R4-8 [LOW] — `_collect_hints` builds streaming branch without consulting the resolver's view

**Where:** `tool_panel/_actions.py:666–732`. The streaming-vs-complete branch keys on
`block._completed`, the kind override branch keys on `view.user_kind_override`, the
error branch keys on `self._is_error()`. The collapsed branch keys on `self.collapsed`.
None of them consult `self._resolver.tier` — yet the contextual hints `("alt+t",
"trace")` and `("D", … via implicit cycle)` are tier-relevant.

**What user sees today:** When the panel is in TRACE tier (already maximised), the
hint `[alt+t] trace` is still offered. Pressing alt+t in TRACE re-runs the resolver,
finds the panel already at TRACE, and silently does nothing — no flash, no movement.
Discoverability says "press this for trace" but trace is already on.

Similarly when in HERO, the hint `[Enter] toggle` advertises a state move that just
returns to DEFAULT, but doesn't explain that direction.

**Why it's wrong:** The hint pipeline has access to the resolver via `self._resolver.tier`
but doesn't use it. ML-1..ML-5 added kind-cycle preview ("as code → plain"); the same
preview pattern would clean up tier hints. Low severity because TRACE is rare and
HERO has visible tier flash, but it's a polish gap.

**Concrete fix sketch:**

In `_collect_hints` (line 728–730), guard the alt+t hint:

```
from hermes_cli.tui.tool_panel.density import DensityTier
if not _block_streaming and not getattr(self, "collapsed", False):
    if getattr(self._resolver, "tier", DensityTier.DEFAULT) != DensityTier.TRACE:
        contextual.append(("alt+t", "trace"))
```

Optionally, when resolver.tier is HERO or COMPACT, replace `("D", "density")`-style
hints (currently absent — would need to be added) with previews like `("D", f"to
{next_tier.value}")` mirroring the kind preview pattern.

Tests: panel in TRACE → assert alt+t hint absent. Panel in DEFAULT → assert present.

---

## Cross-cutting observations

### CC-1: The "Enter" key is overloaded across the system, and the overload now reaches inside

Enter is the chord-key for: (a) submit input in HermesInput, (b) follow path in path
focus mode, (c) expand a collapsed completion list, (d) cycle density on a focused
ToolPanel, (e) toggle collapse on a focused ChildPanel, (f) follow tail link on a
streaming block. The first three are the system-wide chord; the last three live on
tool panels.

R4-1 above fixes the cycle-vs-toggle inconsistency, but the underlying problem —
Enter doing five different things depending on focus context — is structural. The
hint row partly papers over this (it adapts the label to context) but a user who
loses focus and wants to re-anchor has no map.

Out of scope for this audit; flagging as a future "keyboard map discovery" surface
question.

### CC-2: `BodyFrame` is the canonical container, but only 8/10 renderers know

Renderer family consistency is a stronger contract than Round 3 implied. The frame
controls the tier-aware density classes, the footer slot for action chips, and the
body slot's class for skin selectors. Two opt-outs (R4-3) erode that contract.
After fixing, consider asserting the contract in tests: every concrete renderer
returns `BodyFrame` from `build_widget`. A registry sweep test would catch new
renderers that forget.

### CC-3: SkinColors leak audit needs a sweep, not a spot-check

Round 3 C-4 claimed all renderers use SkinColors. R4-2 (footer ANSI tones), R4-4
(header flash ANSI fallback), R4-5 (HERO glyph not in grammar), R4-6 (microcopy
gutter not in grammar) collectively show the spot-check missed four sites. A grep
for `"red"|"yellow"|"green"|"blue"|"cyan"|"magenta"` and `bold (red|yellow|green)`
across the tool block + tool panel modules would catch these in CI. The sites
aren't many; the sweep is cheap.

### CC-4: ChildPanel divergence is a nesting tax

ChildPanel inherits from ToolPanel and overrides `action_toggle_collapse` and the
compose method. Each override is locally sensible (a compact-mode child needs
different behaviour) but the cumulative effect is that nested blocks behave
differently from their parents on Enter, on density changes, and on collapse
recovery. R4-1 closes the Enter divergence; the others remain. Worth a future audit
of the ChildPanel-vs-ToolPanel surface specifically.

---

## What does not need touching (carried forward from Rounds 1–3)

Reaffirming:

- PHASE state machine (`services/tools.py::ToolRenderingService`, `ToolCallState`
  enum, `_set_view_state` choke-point) — stable
- Renderer registry dispatch (`pick_renderer` with phase + density + override) —
  stable
- Plan/Group sync broker (PG-1..PG-4) — stable
- DensityResolver / LayoutResolver consolidation (DR-1..5, DU-1..6) — stable; one
  owner per block; subscribers all read from `_resolver`
- Hint pipeline H-1..H-4 — minor polish in R4-1 / R4-8 above; the structure is
  sound
- Glyph vocabulary `_grammar.py` (post-GV) — needs three additions per R4-5 / R4-6,
  not a redesign
- Error recovery contract (ER-1..5) — stable; sort order, recovery-first,
  stderr_tail surface all working
- Microcopy stall styling — fixed in MCC-1 + Round 3 follow-through; R4-6 is a
  separate gutter consistency point

---

## Recommended sequencing

Three lightweight worktrees close all eight findings:

**Worktree A — Enter binding semantics (R4-1)** (~15 tests)
- Rewrite `action_toggle_collapse` to binary toggle
- Update hint labels
- Delete ChildPanel override
- Verify ChildPanel matches parent

**Worktree B — Skin contract sweep (R4-2 + R4-4 + R4-5 + R4-6)** (~12 tests)
- Footer chip tones via SkinColors
- Header flash error tone via SkinColors
- HERO / chevron glyphs in `_grammar.py`
- Microcopy gutter via grammar
- Optional CI grep against ANSI literal colors

**Worktree C — Renderer family + plumbing (R4-3 + R4-7 + R4-8)** (~14 tests)
- Empty + Fallback renderers via BodyFrame
- feedback.py exception logging sweep
- Hint pipeline reads resolver.tier for trace dedup

Total: ~41 tests. None touches the PHASE / KIND / DENSITY axes. After this, the
system is ready for the next audit cycle, which should be triggered by feature work,
not polish hunts.

---

## Conclusion

The tool call system has reached a polish-only phase. R4-1 is the last meaningful
core-path UX issue (binding semantics). The rest are skin-contract leaks and
renderer-family edge cases. The 3-axis frame (PHASE × KIND × DENSITY) is fully
realised in code; the remaining work is sweeping consistency across the surfaces
that should already be speaking the same vocabulary.

No blockers. Ready to merge after R4-1.

---

## Appendix: `concept.md` drift report

`docs/concept.md` describes "three consolidations" as future work (lines 127–133)
and "where the frame does not fit cleanly" (lines 137–145). All four items are now
implemented per the project memory index and verified by file inspection. Suggested
edits below — **do not apply blindly**; the document is a living concept note and
the user may prefer alternate phrasing.

### Drift item 1 — "What changes if this concept is adopted" → past tense

**Lines 125–133** read:

```
## What changes if this concept is adopted

Three consolidations, no rewrites. Each is its own future spec.

1. **Density resolver, single owner.** Pull `_DROP_ORDER`, `collapsed`, `_auto_collapsed`,
   `_user_collapse_override`, and the implicit "which tier" decision into one
   `DensityResolver` per block. Header / body / footer subscribe. Auto-collapse rules
   become a method on that resolver, not a side-effect of `set_result_summary`. Highest
   leverage; smallest blast radius.

2. **Renderer registry takes context.** `pick_renderer(classification, phase, density)`.
   Streaming and final-render call the same entry point with different context. The
   "two hierarchies" merge under one registry — `StreamingBodyRenderer` subclasses
   become renderers that opt-in to the STREAMING phase.

3. **Per-block axis bus.** `ToolCallViewState` already holds PHASE. Add resolved KIND
   and resolved DENSITY there. Widgets watch the view-state instead of their own
   private flags. Mostly bookkeeping — the values exist, they are not co-located.
```

**Verification:**

1. Density resolver: `tool_panel/layout_resolver.py::ToolBlockLayoutResolver` is the
   single owner. `_DROP_ORDER_*` constants moved into it. `density.py` is a re-export
   shim. Subscribers read `panel._resolver.tier`. ✓ (DR-1..5 + DU-1..6)
2. Renderer registry: `body_renderers/__init__.py::pick_renderer` signature is
   `(cls_result, payload, *, phase, density, user_kind_override=None)`. Single registry,
   `StreamingBodyRenderer` subclasses participate via `accepted_phases`. ✓ (R-2A + R-2B)
3. Per-block axis bus: `ToolCallViewState` holds `state` (PHASE), `kind`
   (ClassificationResult), `density` (DensityTier), with `set_axis` choke-point and
   watcher protocol (`_AxisWatcher`). ✓ (R3-AXIS)

**Suggested edit** — rename the section and rewrite as past tense, e.g.:

```
## What this concept made happen (consolidation log)

Three consolidations, all landed. Each was its own spec.

1. **Density resolver, single owner.** `tool_panel/layout_resolver.py::ToolBlockLayoutResolver`
   owns `_DROP_ORDER_*`, `tier`, `collapsed`, drop-order trimming, and footer visibility.
   Header / body / footer subscribe via `panel._resolver`. (See specs DR-1..5, DU-1..6.)

2. **Renderer registry takes context.** `pick_renderer(cls_result, payload, *, phase,
   density, user_kind_override=None)` — single entry, single REGISTRY. Streaming-tier
   renderers participate via `accepted_phases`. (See specs R-2A-1..6, R-2B-1..6.)

3. **Per-block axis bus.** `ToolCallViewState` holds PHASE + KIND + DENSITY with
   `set_axis` and watcher hooks. (See spec R3-AXIS-01..03.)
```

### Drift item 2 — "Where this frame does not fit cleanly" → first-class for nesting

**Lines 137–141** read:

```
## Where this frame *does not* fit cleanly

Honest limits, worth knowing before extending:

- **Nested / sub-agent tool blocks.** A nested call has its own `(phase, kind, density)`,
  but the parent's density affects whether children render at all. The parent-child
  density coupling is not first-class in the frame. Modelable as "child density
  resolver inherits a clamp from parent," but the cube alone does not capture it.
```

**Verification:** R3-NESTED implemented `parent_clamp: DensityTier | None` on
`LayoutInputs` (`layout_resolver.py:163`) and `_compute_tier` honours it (`layout_resolver.py:301–306`).
ChildPanel sets `_parent_clamp_tier` via watcher on the parent SubAgentPanel
(`tool_panel/_child.py:73–83`). The cube *does* capture nesting now. ✓ (R3-NESTED)

**Suggested edit** — promote nested coupling out of the "doesn't fit cleanly" list and
into the implementation map:

Delete the "Nested / sub-agent tool blocks" bullet from lines 139–141. Add a new
entry under "Implementation map → DENSITY" (line 113):

```
- **Parent clamp:** `LayoutInputs.parent_clamp: DensityTier | None`. ChildPanel
  watches the parent SubAgentPanel's `density_tier` and feeds it into the resolver
  so children cannot render at a less-tight tier than the parent. Errors bypass the
  clamp (modal override). (See spec R3-NESTED.)
```

The remaining two "doesn't fit cleanly" items (interrupt/cancellation, long-running
background tools) are still genuine open questions — keep them.

### Drift item 3 — `StreamingBodyRenderer` reference is now an alias

**Lines 59–61** read:

```
### 1. The dual renderer hierarchy is the PHASE axis showing through

`StreamingBodyRenderer` (raw, line-by-line) runs in PHASE ∈ {STARTED, STREAMING}.
`BodyRenderer` ABC (classified, structured) runs in PHASE ∈ {COMPLETING, DONE}.
```

**Verification:** Per memory index R-2B, `StreamingBodyRenderer = BodyRenderer`
alias. The dual hierarchy was unified — there is one ABC.

**Suggested edit** — soften the wording to acknowledge the unification:

```
### 1. The unified renderer dispatch is the PHASE axis showing through

`pick_renderer` selects from a single registry, but renderers self-declare which
PHASE values they accept via `accepted_phases`. Streaming-only renderers
(`ShellRenderer`, `StreamingCodeRenderer`, `FileRenderer`, etc.) opt in to
`{STARTED, STREAMING}`. Final-render renderers (`DiffRenderer`, `JsonRenderer`,
etc.) default to `{COMPLETING, DONE}`. `StreamingBodyRenderer` is now a backward-
compat alias for the unified `BodyRenderer` ABC.
```

### Summary of suggested drift edits

| Lines | Change | Rationale |
|---|---|---|
| 125–133 | Past-tense rewrite of "What changes if this concept is adopted" | All three consolidations landed |
| 137–141 (Nested bullet) | Delete; add new entry under Implementation map → DENSITY | R3-NESTED makes parent clamp first-class |
| 59–61 | Unification language for `StreamingBodyRenderer` | R-2B aliased the two hierarchies |

Three small edits. The rest of `concept.md` (frame definition, vocabulary section,
mental model, "how to use this document") remains accurate.
