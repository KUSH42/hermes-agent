# Tool Block Concept: Three Axes, One Pipeline

**Status:** FROZEN through 2026-05-11 (concept note, not a spec)
**Version:** 3.6
**Last updated:** 2026-04-27
**Freeze rationale:** code catch-up cycle. Concept evolved v3.0 → v3.6 in three days, faster than implementation can converge. Audits keep producing findings against doc-deltas rather than code regressions. Freeze gives the lint-gate + scaffolding-sweep work (see `/home/xush/.hermes/tool_block_convergence_plan.md`) a stable target.
**Scope:** the visual representation of a single tool call in the TUI — header, live tail, body, footer.
**Audience:** anyone touching `tool_blocks/`, `tool_panel/` (including `layout_resolver.py`), `body_renderers/`, `services/tools.py`, `services/plan_sync.py`, `services/feedback.py`, or the renderer registry.

---

## Freeze policy (active 2026-04-27 → 2026-05-11)

During the freeze window:

- **Allowed:** bug-fix edits to existing clauses (typo, broken cross-reference, factual error in a contract already documented).
- **Allowed:** changelog entries describing implementation work that closes existing clauses.
- **Rejected:** new clauses, new contract surfaces, new perception budgets, new channel rules, new axis values, new role catalogue entries, new redundant-signal rows.
- **Rejected:** version bump to v3.7 or higher.

Resume policy: after 2026-05-11, v3.7 may open *only if* the convergence plan's Step 5 criteria are green (all invariant gates passing, targeted tests passing on owner paths, audit produces ≤3 MED + 0 HIGH). If not green, extend freeze by another 14 days and continue catch-up.

Reviewers: a PR proposing a new clause during freeze is a review block, not a style nit. Direct it to the convergence plan instead.

---

## Why this document exists

The tool block surface is the central display element of the harness. Hundreds scroll past in a long session. Today the implementation is mature — state machine, classifier, renderer registry, density controls, skin grammar all exist — but the pieces don't share a name. New features re-invent local versions of axes that already exist; reviewers debate "where does this rule belong" because the frame is implicit.

This note declares the frame. It does not propose a rewrite. It names what the code already does so future work has a shared vocabulary.

### Design voice

Tool blocks read like quiet paragraphs and only escalate when something demands the user's attention. A successful call is mostly visual silence: a dim border, a category chip, a clamped body. An error or a stall *changes register* — the loudness shift is the signal, not the colour. The aesthetic target is "monitoring console at rest" rather than "dashboard with widgets": dense when consulted, recedes when not. Every channel rule, every density tier, every motion budget below serves that posture.

---

## The frame at a glance

```
                ┌────────────────────────────────────────────────┐
                │            ToolCallViewState (axis bus)         │
                │  ┌─────────┐    ┌────────┐    ┌─────────────┐   │
                │  │  PHASE  │    │  KIND  │    │   DENSITY   │   │
                │  └────┬────┘    └────┬───┘    └──────┬──────┘   │
                └───────┼──────────────┼───────────────┼──────────┘
                        │              │               │
        ┌───────────────┼──────────────┼───────────────┼──────────────┐
        │               ▼              ▼               ▼              │
        │         ┌──────────────────────────────────────────┐        │
        │         │ Channels (visual / glyph / motion / a11y)│        │
        │         │ SkinColors · _grammar · feedback.py · ARIA │      │
        │         └──────────────────────────────────────────┘        │
        │               │              │               │              │
        │               ▼              ▼               ▼              │
        │       ┌─────────────────────────────────────────────┐       │
        │       │  Header  ·  Live tail  ·  Body  ·  Footer   │       │
        │       └─────────────────────────────────────────────┘       │
        │                       (one block)                           │
        └─────────────────────────────────────────────────────────────┘
                                    │
                       ┌────────────┴────────────┐
                       ▼                         ▼
               PlanSyncBroker             ER cell rules,
               (cube → cube coupling)     hint pipeline,
                                          user overrides
```

Every tool block is the product of **three orthogonal axes**:

| Axis | Values | Question |
|------|--------|----------|
| **PHASE** | `GENERATED → STARTED → STREAMING → COMPLETING → {DONE, ERR, CANCEL}` | When in life? |
| **KIND** | `shell, code, json, diff, table, log, search, empty, binary, text` | What is the content? |
| **DENSITY** | `HERO (T0), DEFAULT (T1), COMPACT (T2), TRACE (T3)` | How much real estate? |

Each axis has a **resolver** (decides the value) and **subscribers** (react to it). All three values are published on `ToolCallViewState`, the per-block axis bus. Every render decision is a lookup into the (phase, kind, density) cube. Every part of the block (header, tail, body, footer) is a function of those three values, written in shared channels.

> **Note on terminology.** Earlier drafts called the rendering channels "vocabularies." From v3.0 onward they are **channels** (visual / glyph / motion / a11y) — independent media through which signals reach the user. The word "vocabulary" is reserved for the *axis values themselves* (the strings PHASE/KIND/DENSITY take). This separation matters: channels carry signal redundantly; vocabularies define the signal space.

### Multi-block rhythm

The cube governs one block. Across blocks, a thin rhythm contract holds:
HERO and DEFAULT blocks earn one row of vertical rest after them; COMPACT
and TRACE pack tight (zero rows) so deep history stays dense. Group
children never insert separators — the group header is the rhythm
landmark for its members. ERR phase always earns the rest gap regardless
of tier. The contract is CSS-only; no resolver decision touches it.

---

## Canonical block mocks

The frame is text-rich; the four mocks below pin down what it actually looks like. Skin colors are not represented; structure and density are.

<!-- coloured-mocks-start -->
![HERO + STREAMING + focused](concept_mocks/hero_streaming.svg)
![DEFAULT + ERR + unfocused](concept_mocks/default_err.svg)

> These mocks are regenerated from the bundled default skin palette via
> `scripts/render_concept_mocks.py`. They are illustrative — every shipped
> skin clears the contrast gate, so a skin substitution does not change
> recognition; only hue. If the gate ever changes (e.g. moving from 4.5:1 to
> 7:1 for body text), regenerate and review.
<!-- coloured-mocks-end -->

**HERO (T0) — single block per viewport.** Gets full nameplate, full body, highest-priority hints fitted to width (F1 always pinned), separator below. Tie-break order when multiple candidates qualify: focused ▸ only-in-viewport ▸ first-in-viewport ▸ most-recent. Exactly one HERO per viewport at a time.

**HERO eligibility precedence** (resolves ties between thresholds and focus):

1. **Pressure gate first.** `pressure ≥ 0.6` restricts HERO to focused candidates only; `pressure ≥ 0.85` disables HERO entirely (focused block stays at DEFAULT). Pressure wins over focus.
2. **Threshold gate second.** A focused block under low pressure must still meet `HERO_MIN_BODY_ROWS`; a 2-row body never earns HERO even with focus. Focus does not force HERO past its row threshold.
3. **Tie-break last.** Among the remaining candidates that pass (1) and (2), apply focused ▸ only ▸ first ▸ most-recent.

Focus is therefore a *qualifier*, not an override. The only override that bypasses these gates is `PHASE = ERR` (errors are loud).

```
┌─ shell · git diff HEAD~1 · 47 lines · 0.3s ─────────────── DONE ─┐
│  diff --git a/foo.py b/foo.py                                    │
│  @@ -12,7 +12,7 @@                                               │
│  +    added line                                                  │
│  -    removed line                                                │
│  …  (43 more rows)                                                │
└─ [c]opy  [t]oggle-kind  [D]ensity  [F1]help ────────────────────┘
```

**HERO body height contract.** "No clamp" means no *kind-defaulted* clamp (HERO ignores DEFAULT's ~12-row limit). It does **not** mean unbounded: HERO body is bounded by `viewport_rows − chrome_rows` (header + footer + separator + group-ancestor chrome). When body content exceeds this, HERO shows the first `viewport_rows − chrome_rows − 1` rows plus a `…+N more · ↵ to scroll` chip on the last visible row; pressing `Enter` enters in-block scroll mode (`Esc` exits). The block never silently overflows the viewport — that would violate "no surprise re-flow." Below `MIN_HERO_VIEWPORT_ROWS` (in `THRESHOLDS`, currently 16), HERO is disabled entirely and the would-be HERO stays at DEFAULT.

**DEFAULT (T1) — recently produced, in viewport, not focused.** Full header, body clamped to N rows, top-priority hints only.

```
▸ shell · git diff HEAD~1 · 47 lines · 0.3s · DONE
│ diff --git a/foo.py b/foo.py
│ +    added line
│ -    removed line                          [c]opy  [t]
│ … 44 more
```

**COMPACT (T2) — scrolled past or low-pressure context.** Header drops chips per `_DROP_ORDER`, body becomes one-line summary, footer hides.

```
▸ shell · diff · 47L · DONE
```

**TRACE (T3) — deep history.** One row total, no body, no footer.

```
· shell · DONE
```

**ERR — phase override at any tier.** Three-row contract holds even at COMPACT/TRACE: error category chip on header, stderr evidence in body, recovery hints first in footer. Border tint is the loud channel.

```
┃▸ shell · git diff HEAD~1 · ENOENT ─────────────────────────── ERR ┃
┃│ fatal: ambiguous argument 'HEAD~1': unknown revision           ┃
┃│ Use '--' to separate paths from revisions                       ┃
┃└ [r]etry  [e]dit-args  [c]opy  [t]oggle-kind                    ┃
```

**Empty (kind=empty) — tool produced no stdout.** Header retains category + outcome; body is suppressed entirely (no row); footer keeps `[c]opy` only when something *was* captured (e.g. exit code). Resolver still picks a tier on header-only metrics; HERO is rare for empty blocks.

```
▸ shell · mkdir -p build · 0.0s · DONE
```

**Binary (kind=binary) — payload not safely renderable as text.** Body is a one-line summary chip (`<bytes> · <mime?> · <sha-prefix>`), no hex dump by default. `c` copies a path/data-URI sentinel; pressing `t` does not cycle to text renderers (binary is a terminal kind unless user overrides explicitly).

```
▸ shell · cat /usr/bin/ls · 142 KB · application/x-executable · DONE
│ binary payload — body suppressed (press c to copy as data-URI)
```

**Group — coupling between cubes (not a cube).** Single header summarizes child PHASE rollup; body is the children, each its own block governed by its own (phase, kind, density). Group bodies have an overflow rule (`…+N more children` chip) — see "ToolGroup / PlanSyncBroker" below.

```
▼ plan step · "refactor auth" · 3 calls · 2/3 done · RUNNING
  │
  ├─ ▸ shell · git status · DONE                    (T1)
  ├─ ▸ code  · auth.py    · DONE                    (T1)
  └─ ▸ shell · pytest …   · STREAMING ░░░ 12 rows  (T0, currently focused)
```

---

## UX intent per axis

The axes are not arbitrary mechanics — each owns a piece of the user's experience.

### PHASE owns *liveness*
The user must always know whether work is happening, finished, or broken — within ~100ms. PHASE drives the spinner-free liveness signal: pulse during STREAMING, freeze-pulse on stall, error border on ERR, soft fade on DONE. STARTED and GENERATED are usually invisible to users (sub-second), but the frame keeps them named so a slow tool can surface "queued" without inventing new state.

**Pre-first-chunk skeleton.** STARTED is usually invisible (sub-second) but isn't always — runtime queueing, slow tool spin-up, network latency. If STARTED holds for ≥100ms without a chunk, the live-tail renderer mounts a skeleton row: kind icon (best-known guess, falls back to generic `▸`) + dim `· · ·` ellipsis + motion-channel pulse on the icon. The skeleton dismisses the instant the first chunk lands. Without this affordance, the 0–120ms first-chunk window reads as a hang on slow tools — the skeleton converts perceived freeze into perceived progress. Skeleton is widget-local state, not a view-state field; no PHASE transition. Implemented in `tool_blocks/_streaming.py::_maybe_mount_skeleton` with a 100ms `set_timer`; reduced-motion users skip the pulse (SK-1, 2026-04-27).

**Settled state.** A block enters `settled` 600ms after PHASE reaches DONE with no further events on it. Settled blocks suppress all motion-channel signal *except* focus changes and ERR transitions (errors always re-loud). This is what keeps incidental events — skin hot-reload, viewport resize, a sibling block flashing — from rippling motion across stable scrollback history. Settled is per-block widget-local; CANCEL and ERR also enter settled on the same 600ms timer. A new event on a settled block (e.g. `r` retry) clears settled before any new motion fires.

**Implemented in** `tool_blocks/_streaming.py::StreamingToolBlock._arm_settled_timer`; flash suppression in `services/feedback.py::FeedbackService.flash` via `tone="focus"` / `tone="err-enter"` exemption (FS-3, commit 64086b808).

**Stall is motion-only, not a PHASE node.** When STREAMING produces no chunks for ≥1.5s, the motion channel switches the pulse from "active" to "frozen" cadence; PHASE *stays* `STREAMING`. We deliberately did not add a `STALLED` node — stall is a UI affordance for the user, not a lifecycle fact for subscribers. Renderers, classifiers, and the broker continue to see `STREAMING` and behave identically. When the next chunk arrives, motion silently resumes the active cadence with no PHASE transition.

**Live-tail scroll behaviour.** A STREAMING block is sticky-bottom by default — newly appended chunks scroll the live tail to keep the most recent row in view. Three exits from sticky mode:

1. **User scrolls up inside the block** (`PgUp` / `Up` while focused). Sticky releases; new chunks append off-screen. A `↓ N more rows` chip appears on the bottom border as a non-modal indicator.
2. **User scrolls down to within 1 row of the tail.** Sticky reattaches silently; chip dismisses.
3. **PHASE leaves STREAMING.** Sticky releases unconditionally (final renderer takes over). Scroll position preserved across the renderer swap.

Sticky is per-block widget-local state, not a view-state field — same shape as scroll position. It resets on focus loss and on COMPLETING. The chip uses the motion channel for its first-detach outline (one frame) but otherwise renders as glyph-only; pulsing it would conflate with PHASE liveness.

### KIND owns *recognition*
The user must recognize a block's content type before reading it. KIND drives renderer choice (diff vs raw vs table) and the icon/category chip. A misclassified block is a UX failure even if visually fine — the user wastes a fixation deciding "is this a path or a hash?" The `t` user override exists because classification is heuristic and the user is the final authority.

### DENSITY owns *attention budget*
The user has a finite vertical screen and a finite scan budget. DENSITY decides which blocks earn rows and which earn a single line. HERO is for the call the user is reading right now; TRACE is for an old `ls` they no longer care about. The resolver is single-owner specifically because density is where features fight for space — every "just add a row" PR has to negotiate with the resolver, not with three independent flags.

These three intents are why the axes are orthogonal. Liveness, recognition, and attention are independent user concerns; collapsing any pair causes regressions (a "high-priority" flag conflates DENSITY with PHASE; a "compact diff renderer" conflates DENSITY with KIND).

### UX guarantees (the contract these intents create)

1. **Liveness ≤ 100ms.** Any state change visible to the user within 100ms of the underlying event.
2. **Recognition before reading.** A block's KIND must be visually obvious before the user begins reading the body — chip + glyph + color, redundantly.
3. **Most useful block is most prominent.** Resolver outputs must respect this invariant; any resolver change that breaks it is a regression.
4. **No surprise re-flow.** Density transitions never cause a focused block to leave the viewport.
5. **User authority on KIND.** When classification disagrees with the user, the user wins (`t` override survives re-mount).
6. **Errors are loud.** `PHASE = ERR` always overrides density clamp; an error is never compacted away.
7. **Redundant signal across channels** (see channel rules below).

---

## Why exactly three axes?

Two would not fit: PHASE+KIND alone leaves no room to say "this finished call should shrink to one line" without piggybacking on KIND. Four is rejected because every candidate fourth axis (focus, selection, group membership) is *derivable* from existing state plus user input — they are not properties of the call itself, they are properties of *the user's relationship to the call*. Those live on the surrounding surfaces (hint pipeline, group broker, user overrides), not inside the cube.

Growth path if a genuine fourth axis ever arises: it must (a) be a property of the call independent of viewer, (b) have a single resolver, (c) be publishable on `ToolCallViewState`. If any leg fails, it belongs on a surrounding surface instead.

---

## User-control asymmetry (by design)

| Axis | User override? | Mechanism | Reason |
|------|----------------|-----------|--------|
| PHASE | **No** | — | PHASE is ground truth from the tool runtime. A user cannot will a STREAMING call into DONE. (Cancel is an action that triggers a real CANCEL transition, not an override.) |
| KIND | **Yes** | `t` cycles through eligible kinds | Classification is heuristic; user is final authority. Recorded as `user_kind_override` on view-state (KO-1..5). |
| DENSITY | **Partial** | `D` cycles tiers; `_user_collapse_override` for collapse | Density is a negotiation between resolver and user. User overrides win for that block but do not change resolver policy. |

Anything that looks like a fourth user override (e.g. "user-pinned PHASE") is a coupling violation; route it through the resolver as input, not as a parallel override.

---

## Focus model

`focused` is a resolver input on every axis decision; predictability is non-negotiable. The harness tracks one *primary focus* per scrollback. Group children participate as *secondary focus* only inside an expanded `ToolGroup`.

| Rule | Behaviour |
|------|-----------|
| Auto-focus on entry | A new block claims focus iff no block holds focus, OR the prior focused block is in a terminal state (DONE / ERR / CANCEL). A user actively focused on a running block is *never* preempted by a new invocation. |
| Manual movement | Keyboard only — `j` / `k` (or `↓` / `↑`) cycle blocks; `g` first, `G` most recent. Mouse hover does *not* move focus (resolver inputs must be stable across cursor jitter). |
| Stickiness through transitions | The focused block's PHASE/KIND/DENSITY changes never move focus. DONE → COMPACT while focused: focus stays. |
| Stickiness across scroll | Scrolling does *not* change focus. A focused block can scroll out of view; the resolver still treats it as focused but with `is_in_view=False`. HERO eligibility requires `focused=True` **AND** `is_in_view=True` — see HERO precedence. |
| Focus loss | Focus is lost only by (a) explicit movement, (b) unmount (e.g. scrollback eviction), or (c) overlay/modal capture. |
| Group focus | When a `ToolGroup` is expanded (`Enter`), focus enters the group as *secondary focus* on its first non-terminal child; `j`/`k` cycle siblings; `Esc` returns focus to the group header. Only the group header counts as primary focus for HERO eligibility — children inside a group cannot independently claim a viewport-level HERO. |

Focus is the user's relationship to the call. It lives on the **app**, not on the view-state — moving focus does not mutate `ToolCallViewState`. Resolvers read `app.focused_block_id == self.id` as a derived input.

### Focus visibility

The focus ring is a single contract across tiers: the block's left border swaps from its tier glyph to a **brighter accent** of the same shape, and the header gains a `›` prefix glyph before the category chip. No new geometry — focus does not change row count, does not shift drop-order, does not animate.

| Tier | Unfocused | Focused | Header prefix |
|------|-----------|---------|---------------|
| HERO | `┌─...─┐` (dim) | `┌─...─┐` (accent) | `› ` before category |
| DEFAULT | `▸ │` (dim) | `▸ │` (accent) | `› ` before category |
| COMPACT | `▸` (dim) | `▸` (accent) | `› ` before category |
| TRACE | `·` (dim) | `·` (accent) | `› ` before category |

This is the visual + glyph encoding of the focus signal in the redundant-signal table. Skins recolor "accent" but cannot remove the prefix glyph — focus must survive monochrome terminals. A TRACE block looks like a TRACE block whether focused or not; only the tint and the prefix change. The geometric stability is what makes "no surprise re-flow" hold across focus movement: tab-cycling through 30 blocks shifts only colour and a single glyph per block, never row counts.

**Implemented in** `body_renderers/_grammar.py::FOCUS_PREFIX`, `body_renderers/_grammar.py::get_tier_gutter_glyphs`, and `_header.py::_render_v4` (FS-1/FS-2, commit 64086b808).

---

## The four channels

The frame uses four distinct channels. They are not interchangeable; each has its own override scope.

| Channel | Defined in | Examples | Skin reach |
|---------|-----------|----------|------------|
| **Visual** (color) | `SkinColors` | `accent`, `success`, `error`, `diff_add_bg`, `syntax_theme` | Full — skins redefine values |
| **Glyph** (typography) | `body_renderers/_grammar.py` | `▸`, `│`, `·`, `…`, gutter widths, chip helpers | Limited — skins pick from approved set, do not invent glyphs |
| **Motion** | `services/feedback.py` | flashes, pulses, warning toasts | Color only — skins recolor a flash, never decide which event flashes |
| **A11y** | ARIA-equivalent strings, contrast modes | screen-reader summaries, high-contrast tier behavior, focus announcements | Subset — skins may add long-form labels; cannot suppress them |

Naming them separately matters because their override boundaries differ: a skin can do anything to a color, can choose among a fixed glyph set, can only re-tint motion, and can only extend a11y strings. None can reach an axis resolver. None can decide *when* to flash, *what* glyph means a separator, *that* a tier exists, or *whether* a block has an alt label.

### Visual channel — semantic palette

Skins recolor freely, but the palette they fill is a *closed semantic role set*. A role is what the colour means in the cube; a value is what hue/luminance the skin assigns. Skins cannot add roles, cannot collapse two roles into one, cannot leave a role unbound. Contrast gate (a11y section) applies per-role, not per-value.

| Role | Purpose | Used by |
|------|---------|---------|
| `accent` | active-state tint (focus ring, STREAMING border, KIND-override flash) | header, gutter, focus visibility |
| `accent_dim` | recessed accent for unfocused active blocks | DEFAULT/COMPACT borders during STREAMING |
| `success` | DONE positive terminal state | DONE chip, exit=0 indicator |
| `warning` | non-error attention (stall freeze, retry chip, slow-renderer placeholder) | stall glyph tint, `retry × N` chip |
| `error` | ERR phase, contrast-gated stricter (≥4.5:1 even on borders) | ERR border, error category chip, ER body marker |
| `info` | neutral informational (size, duration, timestamp chips) | info-value chips at HERO/DEFAULT |
| `muted` | recessed text — body wrap continuation glyphs, "…+N more" chips | truncation indicators, separator dots |
| `surface` | block background (rare — most blocks are transparent over panel surface) | HERO body fill in skins that opt in |
| `surface_alt` | striped row tint for diff/table renderers | DiffRenderer +/- bg, TableRenderer alt rows |
| `border` | dim default border tint for non-active states | DEFAULT/COMPACT/TRACE gutters |

Skins must bind every role — partial palettes are rejected at load with a named violation per missing role (same gate as contrast). The role set is closed by the same logic as KIND and error categories: extending it is a concept change, not a skin change. A new role enters the catalogue only when a new signal would otherwise have to overload an existing role (and therefore break the redundant-signal table). Today's catalogue is sized to the current signal set; growth is by negotiation, not by skin authoring.

### Motion intensity

The motion channel has a global intensity dial — the only legitimate way to suppress motion. Vestibular sensitivity, screen recording, and SSH-over-jittery-network all need it. Intensity is *not* per-block and *not* skin-controlled.

| Intensity | Pulse | Flash | Fade | Stall freeze | When |
|-----------|-------|-------|------|--------------|------|
| `full` (default) | 800ms period | 240ms | 600ms ease | cadence change at 1.5s | terminal supports motion, user has not opted out |
| `reduced` | static accent tint, no animation | one-frame outline (≤16ms) | instant swap | static "stalled" glyph (`◌`) replaces pulse | `prefers-reduced-motion`, low-bandwidth flag, or explicit setting |
| `none` | no signal | no signal | instant swap | static glyph only | screen-reader primary mode, recording mode, or explicit setting |

When motion is reduced or off, the redundant-signal rule still holds — every signal motion would have carried must already exist on visual + glyph + a11y, so removing motion never removes information. The reduced/none modes are how we verify that rule isn't quietly violated.

**Honest caveat — stall is motion-primary, glyph-fallback.** Stall is the one signal where motion is the *primary* encoding under `full` intensity (cadence change with no PHASE transition behind it). Under `reduced`/`none`, stall surfaces on the glyph channel as a static `◌` plus an a11y "stalled" announce. This is a controlled bleed across channels, not pure orthogonality: the motion channel carries the signal when available, the glyph channel takes over when not. Document it as an exception rather than pretend the channels are fully independent. No other signal has this shape today; if a second one appears, name the bleed in its row of the redundant-signal table the same way.

### A11y channel rules

The a11y channel is more than ARIA strings. It has a verbosity policy and a contrast gate:

- **Live-region politeness:** `polite` by default for PHASE transitions (DONE, COMPLETING). `assertive` reserved for ERR and CANCEL only. Streaming chunks are *not* announced — only the start ("running"), stall ("stalled"), and terminal transition.
- **Announcement frequency:** one announce per state change, never per chunk. A 5-minute streaming call announces twice (start, end), not 30,000 times. The motion channel carries chunk-level liveness; a11y carries state-level liveness.
- **Contrast gate:** SkinColors validates at resolution time. Border/glyph against background ≥ 3:1. Body text ≥ 4.5:1. Error border + ERR text ≥ 4.5:1 (not 3:1 — errors must clear the stricter bar even on borders). A skin failing the gate is rejected with a named contrast violation, not silently dimmed. (See SkinColors resolution path; gate behaviour is a contract, not a debug-mode warning.)
- **Long-form labels:** skins may add long-form alternates per chip (e.g. `"shell"` → `"shell command"` for screen readers); they cannot suppress the short label.

### Redundant-signal rule

**Every signal a user must perceive is encoded across at least two channels.** This is not optional. Color-blind users, low-contrast terminals, and screen readers all break otherwise.

| Signal | Visual | Glyph | Motion | A11y |
|--------|--------|-------|--------|------|
| STREAMING liveness | accent border | — | pulse | "running" announce |
| ERR | error border tint | `┃` heavy gutter | brief flash | "error: <category>" |
| Focus | focus ring color | — | — | focus announce |
| KIND change (user override) | accent flash | new icon | flash | "kind set to <X>" |
| DONE | dim border | gutter softens | soft fade | "complete" |
| Streaming KIND hint | `~<kind>` chip in header | kind icon override | — | "running \<kind\>" announce updated |

Adding a new signal? Fill its row in this table before merging.

---

## Per-tier behavior contract

What the DENSITY resolver promises the user, per tier. This is the resolver's external contract — internal logic may add nuance, but these guarantees hold.

| Tier | Header | Body | Footer | Border | When |
|------|--------|------|--------|--------|------|
| **HERO (T0)** | full nameplate + all chips + duration | full body, no clamp | highest-priority hints fitted to width, F1 pinned | `┌─...─┐` boxed | exactly one per viewport: focused ▸ only ▸ first ▸ most-recent |
| **DEFAULT (T1)** | full nameplate, drop-order respected | clamped to ~12 rows + tail summary | top 2–3 hints | `▸ │` | recent, in viewport, not focused |
| **COMPACT (T2)** | category + name + outcome only | one-line summary | hidden | `▸` | scrolled past viewport center, or many siblings |
| **TRACE (T3)** | one row, category + outcome | hidden | hidden | `·` | far history, or under heavy viewport pressure |

Resolver inputs (`LayoutInputs`): focus, viewport pressure, body row count, parent_clamp, `_user_collapse_override`, `phase` (for ERR bypass). Output: `tier`, `collapsed`, drop-order decisions.

**Viewport pressure formula.** `pressure = rows_consumed_by_visible_blocks / available_terminal_rows`, recomputed on every block transition or terminal resize. Crossings:

| Pressure | Effect on resolver |
|----------|--------------------|
| `< 0.6` | tiers free; HERO eligible per tie-break |
| `0.6 – 0.85` | HERO restricted to focused; older blocks step down DEFAULT → COMPACT |
| `0.85 – 1.0` | only focused block stays at DEFAULT or higher; siblings forced to COMPACT |
| `> 1.0` (oversubscribed) | unfocused, off-screen blocks cascade to TRACE; ERR bypasses |

**Pressure / tier fixed-point.** Pressure depends on row consumption; row consumption depends on tier; tier depends on pressure. Resolution is a bounded two-pass per layout cycle:

1. Compute pressure using the *previous* cycle's tiers (initial cycle: all DEFAULT).
2. Run the resolver per block with that pressure value.
3. Recompute pressure with the new tiers. If the pressure band changed (e.g. crossed the 0.85 boundary), run **one** more resolver pass and stop.

Two passes are sufficient because both the tier set (4 values) and the band set (4 values) are coarse — a third pass cannot change a decision the first two could not. If the second pass would flip the band yet again, the resolver pins to the *tighter* tier (bias toward conservation under contention). The procedure is deterministic and oscillation-free; no convergence loop, no fixed-point iteration.

Quantitative thresholds (`HERO_MIN_BODY_ROWS=5`, `DEFAULT_BODY_CLAMP≈12`, `COMPACT_SIBLING_CAP=4`, etc.) live in `tool_panel/layout_resolver.py::THRESHOLDS`. Keep the constants there; this doc names *that* the thresholds exist and roughly *what* they gate, not their numeric values (those are tuned per release).

**Width pressure (the second pressure axis).** Viewport pressure decides tier; width pressure decides chip drop *within* tier. `width_pressure = max(0, content_natural_width / available_cols)`, recomputed on resize:

| Width pressure | Effect |
|----------------|--------|
| `< 0.7` | header renders all chips for current tier |
| `0.7 – 0.9` | shed bottom of info-value hierarchy first (timestamp → duration → size) |
| `0.9 – 1.0` | name/arg chip mid-elides with `…`; further chips drop in hierarchy order |
| `> 1.0` | tier step-down (DEFAULT→COMPACT, etc.); ERR bypasses |

Width and viewport pressure compose: a block can be DEFAULT-by-height + name-elided-by-width simultaneously. Step-down at `> 1.0` width is the only width-driven tier change; everything else is within-tier chip drop.

**Minimum viable width.** Below `MIN_BLOCK_COLS` (in `THRESHOLDS`, currently 40), the block renders a degenerate one-line form: `· <category> · <outcome>` with no body and no footer regardless of tier. Below `MIN_VIEWPORT_COLS` (currently 24), the harness refuses to draw the block surface and shows a "viewport too narrow" placeholder at the panel level. These are floors, not bands — they short-circuit the resolver entirely and are the only legitimate way for content to disappear without a `…+N` glyph.

Body content wraps per renderer: code/json wrap on whitespace, diff hard-wraps with a `↵` continuation glyph, table drops rightmost columns one at a time and surfaces a `…+N cols` chip on the header row. Wrapping never silently elides — every elision earns a glyph the user can recognize.

**Information-value hierarchy (drop-order rationale).** Header chips have a fixed information value, dropped tail-first as width tightens. Most→least important:

1. **Category** — the user's primary recognition signal; never dropped (would break "recognition before reading")
2. **Outcome / phase chip** — answers "is this done, running, broken?"; never dropped at any tier
3. **Name / arg summary** — what the call *is*; first chip dropped at TRACE
4. **Size / row count** — body shape, dropped before duration at COMPACT
5. **Duration** — useful but recoverable from logs; first dropped at COMPACT
6. **Timestamp** — present only at HERO; first to drop on width pressure

Drop order *within* a tier follows this hierarchy, not insertion order. The exact `_DROP_ORDER` list in code mirrors this; if they ever disagree, code is the bug, this hierarchy is the spec.

**Promotion rules (chips that earn an extra tier).** Two static promotions override the baseline ordering:

- **Long-call promotion.** A call with `duration > LONG_CALL_THRESHOLD` (in `THRESHOLDS`, currently 5s) keeps its duration chip through COMPACT and is dropped only at TRACE — long calls are interesting and the chip is the only signal saying so.
- **Large-payload promotion.** A body with `row_count > LARGE_PAYLOAD_ROWS` (in `THRESHOLDS`, currently 200) keeps its row-count chip one tier longer than baseline.

Promotions are static thresholds, not a resolver — they live alongside `_DROP_ORDER` selection logic. They are deliberately one-way (no demotion of fast calls below baseline); the goal is "interesting things stay visible," not symmetric tuning.

**ERR override.** At any tier, `PHASE = ERR` re-binds the row contract:

| Row    | Content                                                    |
|--------|------------------------------------------------------------|
| Header | exactly two chips: error category + outcome (`ERR`); every other chip dropped at every tier (HERO included). Category never truncates |
| Body   | stderr evidence (set via `set_stderr_tail`, never collapsed) |
| Footer | recovery hints, sorted first ahead of generic affordances  |

Even at TRACE, an ERR block restores enough rows to honor this contract.

### Body truncation contract

DEFAULT (T1) clamps body to `DEFAULT_BODY_CLAMP` rows. The default truncation strategy is **tail-bias**: keep the last `clamp − 1` rows, drop earlier content, surface a `… N earlier` chip on the first visible row. This favours streaming and log-shaped output where the tail is the live edge. Renderers may opt out per KIND when the head defines the recognition signal:

| KIND | Strategy | Rationale |
|------|----------|-----------|
| `diff` | hunk-aware | never split a hunk; show first hunks fully, elide whole hunks at the boundary, chip = `…+N hunks (+M lines)` |
| `table` | head-bias rows | first N rows + chip; columns drop right-to-left under width pressure |
| `log` | tail-bias (default) | most recent N entries; head dropped |
| `json` | head-bias | structural prefix is the recognition signal |
| `code` | head-bias | function/class signatures cluster at the top |
| `shell`, `text` | tail-bias (default) | streaming context |
| `search` | priority-bias | top N hits by score, no middle elision |
| `empty`, `binary` | n/a | body suppressed |

Strategy is a renderer property declared on the `BodyRenderer` subclass (`truncation_bias = "head" | "tail" | "priority" | <callable>`), not an axis. COMPACT (T2) collapses to a one-line summary derived by the renderer (`BodyRenderer.summary_line(payload)`) regardless of bias; the strategy table only governs DEFAULT clamping. HERO never truncates by clamp — only by viewport (see HERO body height contract). Every truncation point is glyph-marked; silent elision is forbidden.

---

## Perception budgets

Numbers are commitments, not aspirations. Failing one is a regression.

| Event | Budget | Channel | Notes |
|-------|--------|---------|-------|
| PHASE transition → user-visible change | ≤ 100 ms | visual + motion | `set_axis` → repaint |
| First STREAMING chunk → first painted row | ≤ 120 ms | visual | live tail must not lag perceptibly |
| Stall detection (no chunk) → freeze pulse | 1.5 s | motion | distinguishes "running slowly" from "stuck" |
| COMPLETING → final renderer swap | ≤ 250 ms | visual | classifier + render budget combined |
| Group child transition → group header reflow | ≤ 50 ms (debounced 30 ms) | visual | broker debounces to avoid chatter under heavy fan-out |
| User keypress → flash feedback | ≤ 16 ms | motion | next-frame; below this users perceive lag |
| Density tier change → reflow | ≤ 200 ms | visual | longer than transition is acceptable; longer than 200 ms feels janky. **Repaint is instant — no easing, no interpolation.** See "Density tier transition repaint" row. |
| Group expand/collapse → settled layout | ≤ 200 ms | visual + motion | growth animates downward only; focused block stays anchored (see ToolGroup expansion rule) |
| Pulse cadence | 800 ms period | motion | shared across all running blocks for visual sync |
| Flash duration | 240 ms | motion | uniform per channel (FC-1) |
| DENSITY resolver run | ≤ 1 ms / block | — | one pass through `LayoutInputs` → `tier`+drop decisions; no I/O, no allocation in steady state |
| Group aggregation tick | ≤ 5 ms / 100 children | — | broker debounces 30ms; one tick batches all transitions in window |
| KIND classifier run | ≤ 50 ms / payload | — | runs once at COMPLETING; if exceeded, classifier returns `unknown` and renderer falls to `RawTextRenderer` |
| Stall detector wakeup | 250 ms timer / streaming block | — | shared timer, not per-block; checks last-chunk timestamp |
| Header scan time (recognition) | ≤ 500 ms / ≤ 7 chips | visual + glyph | a HERO header must be scannable inside a single fixation pass; chip count above 7 forces drop-order to fire even at low width pressure (Miller's 7±2). DEFAULT cap = 5 chips, COMPACT = 3, TRACE = 2. |
| Density tier transition repaint | instant (no easing) | visual | tier changes are hard repaints, not animated; the only motion is a one-frame outline flash on geometry delta (see "Settled state" below). Animation across reflow is forbidden — terminals can't sustain 60fps interpolation and stutter is worse than a clean cut. |
| Pre-first-chunk placeholder visible | ≤ 100 ms after STARTED | visual + glyph | if STARTED holds without a chunk past 100ms, render a skeleton row (kind icon + dim ellipsis `· · ·` + pulse on motion channel). Skeleton dismisses on first chunk. Without this, slow-start tools look hung for the 0–120ms first-chunk window. |
| Settled-state quiescence | 600 ms post-DONE with no events | — | block enters `settled`; subsequent incidental events (skin reload, viewport resize, sibling reflow) suppress all motion on it except focus + ERR transitions. Prevents polish events from leaking flashes onto stable history. |

When a budget cannot be met, degrade visibly — show an explicit "(…)" or stall glyph rather than appearing frozen.

**Compound budgets.** Group fan-out: 200 children entering STREAMING in the same tick must still repaint the group header within the 50ms group-repaint budget. Resolver + aggregation + paint must compose; if any leg blows it, the broker drops the tick and coalesces with the next debounce window rather than missing the perceptual deadline.

**How budgets are measured.** Budgets in this section are not lore — they are enforced through three mechanisms:

1. **CI bench.** `tests/perf/test_axis_budgets.py` exercises each row's scenario under `pytest-benchmark` with deterministic fixtures and asserts the budget. The bench runs on CI for every PR touching `tool_blocks/`, `tool_panel/`, `body_renderers/`, `services/tools.py`, `services/plan_sync.py`, or `services/feedback.py`. A regression fails the build.
2. **Runtime trace.** When `HERMES_TUI_TRACE_BUDGETS=1`, each instrumented event is timed via a monotonic clock; an overrun logs at `warning` with event name, measured time, and budget. Off by default (zero overhead in production); on for dev sessions and the perf-regression bot.
3. **Adding a budget = adding a fixture.** New rows in this table must come with a benchmark fixture in `test_axis_budgets.py` before merging. A budget without a fixture is aspirational and does not belong here.

The point is enforcement, not measurement-for-its-own-sake: the table is a *contract* the code is held to, not a wish list.

---

## Coupling table — every legal cross-axis read

Orthogonality means resolvers do not depend on each other's *state* in the steady case. There are four legal couplings, each constrained:

| From → To | Where | What flows | Constraint |
|-----------|-------|------------|------------|
| PHASE → KIND | `ToolPanel` invokes classifier at COMPLETING | trigger only, not state read | KIND resolves once per block, gated by PHASE entering COMPLETING. A separate glyph-only signal (`streaming_kind_hint`) may update the header icon and chip during STREAMING — see note below. |
| PHASE → DENSITY | ER cell rule (`PHASE=ERR` bypasses parent clamp) | phase value as resolver input | Errors override clamp; encoded in `LayoutInputs`, not ad-hoc |
| KIND → DENSITY | renderer declares min-height needs at each tier | per-tier display contract | Renderer is a *subscriber*, not a resolver — declares needs, does not set tier |
| DENSITY → PHASE | none | — | Forbidden. A block's tier never changes its lifecycle state. |

**Note on streaming KIND hint (SLR-3).** A separate, glyph-only signal — `streaming_kind_hint` — may update the header icon and category chip during STREAMING based on a first-chunk sniff. It does not mutate `view_state.kind` and does not pick a renderer; the body keeps streaming through the raw renderer. Hint clears at COMPLETING; classifier output then drives both icon and renderer as today. The hint is a guess, the classifier is resolution. `_MIN_HINT_PREFIX_BYTES = 8` is documented inline in `services/tools.py`; full classifier window remains 256 bytes. Header-side defensive clear in `tool_blocks/_header.py::_on_axis_change` on the `"state"` axis when transitioning into the inlined terminal/resolving set `{COMPLETING, DONE, ERROR, CANCELLED}` guards against late axis-write races (SK-2, 2026-04-27).

Anything not in this table is an axis violation. Example violations seen in review:
- A renderer reading `view_state.phase` to pick a *different renderer* — that's KIND resolution leaking into a subscriber. Fix: route through `pick_renderer` with phase as a kwarg.
- A skin token like `$tier-compact-force` — that's channel reaching an axis. Fix: reject; the skin only reshapes how a tier *looks*.
- A widget reading another widget's `_collapsed` private flag — that's bypassing the axis bus. Fix: read `view_state.density.collapsed`.

---

## Cube reachability

Not all `(PHASE, KIND, DENSITY)` cells are legal. KIND resolves once at COMPLETING (per the PHASE→KIND coupling); before that, KIND is unresolved (`?`).

| PHASE | KIND reachable | DENSITY reachable | Notes |
|-------|----------------|-------------------|-------|
| GENERATED | `?` only | DEFAULT, COMPACT, TRACE | No body yet — HERO threshold gate fails. |
| STARTED | `?` only | DEFAULT, COMPACT, TRACE | Same as GENERATED. |
| STREAMING | `?` only | all four | HERO becomes eligible once live tail crosses `HERO_MIN_BODY_ROWS`. Mid-stream classification is out of scope (see "where the frame does not fit"). |
| COMPLETING | any resolved KIND | all four | Single classifier run publishes KIND. Brief — typically <250ms. |
| DONE | any resolved KIND | all four | Stable terminal. |
| ERR | any resolved KIND **or** `?` | all four (ER three-row contract overrides body clamp) | Classifier may not have run if PHASE jumped to ERR before COMPLETING; KIND can stay `?`. ER cell rule applies regardless. |
| CANCEL | `?` if cancelled before COMPLETING; resolved KIND if after | all four | Late cancel after a successful classify keeps the resolved KIND. |

Illegal cells (representative):

- `(GENERATED, diff, *)` — any resolved KIND requires PHASE ≥ COMPLETING.
- `(STARTED, code, *)` — same.
- `(STREAMING, table, *)` — same.
- `(*, *, HERO)` where `body_rows < HERO_MIN_BODY_ROWS` — fails threshold gate.
- `(*, *, HERO)` where `viewport_rows < MIN_HERO_VIEWPORT_ROWS` — HERO disabled below the minimum viewport.

Reachability is a static invariant. A resolver, classifier, or test fixture producing an illegal cell is a bug. The matrix above is the source of truth; tests under `tests/tui/test_cube_reachability.py` assert it for every transition path.

---

## Implementation map

### PHASE
- **Resolver:** `services/tools.py::ToolRenderingService` (transitions on tool lifecycle events)
- **State:** `ToolCallState` enum, stored on `ToolCallViewState`
- **Subscribers:** `ToolHeader` (icon, pulse), `StreamingToolBlock` (live tail), `ToolPanel` (when to invoke classifier + final renderer), `FooterPane` (action affordances)

### KIND
- **Resolver:** `content_classifier.py::classify_content`
- **State:** `ClassificationResult(kind, confidence, metadata)` — runs once at COMPLETING
- **Confidence threshold:** `KIND_MIN_CONFIDENCE` (in `content_classifier.THRESHOLDS`, currently 0.5). Below threshold, `pick_renderer` falls to `FallbackRenderer` regardless of declared kind. Disclosure band 0.5–0.7: renderer surfaces `⚠ low-confidence: <kind>` caption via `_low_confidence_caption()`. The thresholds are single named constants in `THRESHOLDS`; this doc names *that* they exist, not their numeric values. `KIND_MIN_CONFIDENCE = 0.5`, disclosure band 0.5–0.7.
- **Subscribers:** `body_renderers/__init__.py::pick_renderer` (selects renderer subclass)

### DENSITY
- **Resolver:** `tool_panel/layout_resolver.py::ToolBlockLayoutResolver` — single owner of `tier`, `collapsed`, `_DROP_ORDER_*`, drop-order trimming, footer visibility.
- **State:** `DensityTier` (HERO/DEFAULT/COMPACT/TRACE) + per-segment drop decisions, exposed on `ToolCallViewState` via the axis bus.
- **Subscribers:** `ToolHeader` (chip dropping), `ToolPanel` (body show/hide), `FooterPane` (action affordances), `ChildPanel` (nested clamp).
- **Parent clamp:** `LayoutInputs.parent_clamp: DensityTier | None`. ChildPanel watches the parent SubAgentPanel's density tier and feeds it into the resolver so children cannot render at a less-tight tier than the parent. Errors bypass the clamp (modal override). (See spec R3-NESTED.)

### Channels
- **Visual:** `SkinColors` — resolved at widget mount via `app.get_css_variables()`; fallback chain when unresolved.
- **Glyph:** `body_renderers/_grammar.py` — module-level constants; `chip()` helper; gutter widths.
- **Motion:** `services/feedback.py` — single owner of flashes/pulses; uniform tone per channel; queue guard.
- **A11y:** screen-reader strings derived from axis values + skin-supplied long-form labels; high-contrast contrast-ratio gate enforced on visual channel resolution.

---

## Concurrency invariants

The cube has one event loop. Every mutation crosses through it.

| Operation | Thread | Rule |
|-----------|--------|------|
| `set_axis` (PHASE/KIND/DENSITY publication) | Textual event loop only | Workers must marshal via `App.call_from_thread`. Direct `set_axis` from a worker is a contract violation. |
| Resolver run | Event loop, synchronous | Resolver is pure (`LayoutInputs → tier+drops`); ≤1ms; never schedules I/O. |
| Classifier run | Event loop or short-lived worker | If worker, result published via `call_from_thread`; classifier never writes view-state directly. |
| Renderer `render()` | Event loop | Synchronous. Slow-renderer rule (see dispatch contract) governs the >250ms case. |
| Stall detector | One shared `set_interval(0.25s)` on the app, not per-block | Reads last-chunk timestamp from each STREAMING block; emits a *motion-channel* swap, not a `set_axis` call (stall is not a PHASE transition). |
| Motion-intensity swap | Event loop | When intensity changes (`prefers-reduced-motion`, user setting), motion subscribers re-bind synchronously; no in-flight flash leaks across the boundary. |
| PlanSyncBroker tick | Event loop, debounced 30ms | Coalesces all child transitions in window; one repaint per tick. |
| Feedback queue (`services/feedback.py`) | Event loop | Single-owner queue; queue guard rejects pile-up (FC-4). |
| Skin hot-reload (DESIGN.md change) | Event loop | All in-flight pulses re-bind to new SkinColors at the next pulse-cadence boundary (≤800 ms); no mid-pulse colour swap. Cadence resets so all running blocks re-align on the new skin's pulse period. Stall-freeze cadence inherits the new period without restart. Glyph constants are static — skin reload never replaces a glyph mid-frame. |

The invariant: **no axis state mutates off the event loop, ever.** Workers compute, marshal, then mutate. View-state therefore needs no internal locking — concurrency is collapsed at the boundary, not inside the cube.

---

## The renderer dispatch contract

The PHASE axis shows through the dispatch:

- **Picker:** `pick_renderer(cls_result, payload, *, phase, density, user_kind_override=None) -> BodyRenderer` selects a renderer class from a single registry. KIND drives the selection; PHASE+DENSITY are passed as context.
- **Renderer:** `BodyRenderer.render(payload, *, phase, density) -> Widget` produces the widget. A renderer self-declares which PHASE values it accepts via `accepted_phases` and may decline by raising or returning a fallback.

Streaming-only renderers (raw, line-by-line) opt in to `{STARTED, STREAMING}`. Final-render renderers (classified, structured) default to `{COMPLETING, DONE}`. They are not competing systems — they are the **same axis** applied at different phases. `StreamingBodyRenderer` is a backward-compat alias for the unified `BodyRenderer` ABC.

A diff renderer declines while STREAMING (falls back to raw). A shell renderer accepts both phases.

### Renderer purity rules

1. **Idempotent on inputs.** `render(payload, *, phase, density)` called twice with identical args must return widgets that present identically. No hidden state across calls.
2. **No external reads.** A renderer does not read `view_state` directly, does not query the app, does not touch sibling widgets. All inputs arrive as kwargs.
3. **Re-invocable on density change.** When DENSITY changes, the panel calls `render` again with the new tier. Renderers must not assume one-shot construction.
4. **Failure declines, never crashes.** If a renderer cannot honor `(phase, density)`, it returns a fallback widget (raw renderer output). It does not raise into the dispatch.
5. **No motion.** Renderers do not call into `services/feedback.py`. Motion is owned by the panel/header in response to view-state changes.

### Failure modes

| Condition | Behavior |
|-----------|----------|
| `kind = unknown`, low confidence | `pick_renderer` returns `RawTextRenderer` |
| Renderer raises during `render()` | Caught, logged with `exc_info=True`, fallback to `RawTextRenderer`; block tagged so it does not retry every density change |
| Renderer exceeds 250ms COMPLETING budget | Soft deadline: panel mounts a placeholder widget (kind icon + "rendering…" + freeze-pulse glyph) at 250ms, schedules the slow render in a worker, swaps in result via `call_from_thread`. Hard deadline at 2s: cancel the worker, fall back to `RawTextRenderer`, log at `warning`. Block tagged so density changes re-enter the same fast/slow split. |
| Classifier throws | Treated as `kind = unknown`; logged |
| Classifier exceeds 50ms budget | Cancelled; treated as `kind = unknown`; logged at `warning` |
| Resolver throws | Last-known good tier reused; logged at `error`; block does not crash the panel |

---

## Block-level key contract

Keys bound while a tool block has focus. Block-level only — global keys (e.g. `q`, `?`) are documented elsewhere.

| Key | Action | Affects axis | Notes |
|-----|--------|--------------|-------|
| `t` | cycle KIND through eligible renderers | KIND (override) | eligibility = kinds whose registered `BodyRenderer.accepts(payload, phase=current)` returns true; binary excluded unless explicit; TEXT excluded after KO-A; survives re-mount; flashes on no-op (HF-A) |
| `T` | revert KIND override → resolver default | KIND | clears `user_kind_override` |
| `D` | cycle DENSITY tier forward | DENSITY (override) | order: `DEFAULT → COMPACT → TRACE → HERO → DEFAULT`; wraps; pressure-forbidden tiers (HERO under `pressure ≥ 0.85` or `body_rows < HERO_MIN_BODY_ROWS`) flash + skip silently to next legal tier; flashes on no-op |
| `Shift+D` | cycle DENSITY tier backward | DENSITY (override) | reverse order, same skip semantics |
| `c` | copy block content (kind-aware) | — | uses `BodyRenderer.copy_text()` |
| `r` | retry (errored blocks only) | PHASE (re-invokes runtime) | not an override; triggers a real new call. **Same id**: prior view-state collapses to CANCEL via the preemption path before the new GENERATED enters STARTED. Scrollback position preserved. The new view-state's `retry_count` increments; chip displays `retry × N` (N counts `r`-initiated retries since the original GENERATED — preemption-CANCELs do *not* increment) |
| `e` | edit-and-retry args (errored blocks) | — | opens command editor; on submit, behaves like `r` (same `retry_count` semantics) |
| `Enter` | toggle expand/collapse (binary) — `D` for full density cycle | DENSITY (override) | binary on every panel; HERO reachable only via D |
| `F1` | help overlay for current block | — | pinned; not subject to drop order (HF-C) |
| mouse-drag | terminal-native text selection (passes through to body widget) | — | does not move focus; yields raw text only — use `c` for kind-aware copy |
| mouse-click on header | move focus to that block; if header is a ToolGroup, also toggle expand | DENSITY (group only) | the only legal mouse-driven focus mutation; mouse hover never moves focus (resolver inputs must be stable across cursor jitter) |

User overrides are recorded on `ToolCallViewState`, not on the widget that received the keypress.

---

## Worked example: happy path — `git diff HEAD~1`

End-to-end trace through one tool call. Numbered events, axis values shown as `(P/K/D)`.

```
1. tool_invoked{id=t42, name="bash"}                                  (GENERATED / ?  / DEFAULT)
   - ToolRenderingService creates ToolCallViewState, set_axis(phase=GENERATED).
   - ToolPanel mounts a ToolBlock; ToolHeader shows category chip "shell".
   - DENSITY resolver runs with no body content → DEFAULT.

2. tool_started{id=t42}                                                (STARTED   / ?  / DEFAULT)
   - set_axis(phase=STARTED). Header pulse begins (motion channel).
   - No KIND yet; live tail renderer is the streaming raw renderer.

3. tool_output_chunk{id=t42, "diff --git a/foo..."}                    (STREAMING / ?  / DEFAULT)
   - set_axis(phase=STREAMING). StreamingToolBlock appends to live tail.
   - Resolver re-evaluates: live tail has 12 rows now → still DEFAULT.

4. tool_output_chunk{id=t42, "+   added line\n-   removed line\n..."}  (STREAMING / ?  / DEFAULT)
   - Live tail keeps growing. KIND still unresolved — PHASE→KIND coupling
     is gated on COMPLETING, not STREAMING.

5. tool_completing{id=t42, exit=0}                                     (COMPLETING / diff / DEFAULT)
   - set_axis(phase=COMPLETING). Classifier runs once on full payload.
   - ClassificationResult(kind=diff, confidence=0.92).
   - set_axis(kind=diff). pick_renderer(kind=diff, phase=COMPLETING, density=DEFAULT)
     → DiffRenderer.render(payload, phase=COMPLETING, density=DEFAULT).
   - ToolPanel.replace_body_widget(diff_widget). Live tail dismissed.
   - Resolver re-evaluates: 47 body rows → still DEFAULT (under HERO threshold).

6. tool_done{id=t42}                                                   (DONE / diff / DEFAULT)
   - set_axis(phase=DONE). Header pulse stops; soft fade.
   - FooterPane shows: [c]opy [t]oggle-kind [D]ensity (hint pipeline derives
     these from current cell, no static table).

7. (later) user scrolls past, focus leaves block                       (DONE / diff / COMPACT)
   - DENSITY resolver re-runs with focus=False, viewport pressure → COMPACT.
   - set_axis(density=COMPACT). DiffRenderer re-renders with density=COMPACT.
   - Header drops the path chip per _DROP_ORDER. Footer hides affordances.

8. (later) user presses `t` while focused                              (DONE / log / COMPACT)
   - KO-1..5: user_kind_override = "log" recorded on view-state.
   - pick_renderer reads user_kind_override → LogRenderer.
   - This survives re-mount; widgets are stateless windows onto view-state.
```

Every transition is a `set_axis` call. Every render is a function of the axis bus. No widget reads another widget's flags.

---

## Worked examples — unhappy paths

The most UX-critical moments are not happy.

### ERR — `git diff HEAD~999`

```
1. tool_invoked, tool_started, streaming chunks                        (... STREAMING / ? / DEFAULT)
2. tool_completing{id=t43, exit=128, stderr="fatal: ambiguous..."}     (COMPLETING / shell / DEFAULT)
   - Classifier runs; payload is empty stdout → kind = shell (low confidence).
   - exit ≠ 0 → ToolRenderingService transitions to ERR, not DONE.
3. set_axis(phase=ERR)                                                  (ERR / shell / DEFAULT)
   - ER cell rule fires: header pinned to category chip "shell · ENOENT" (no truncation).
   - set_stderr_tail(stderr) → body shows last N stderr lines, no collapse.
   - Hint pipeline emits recovery hints first: [r]etry, [e]dit-args, then generic.
   - Border tint switches to error color (visual + glyph: heavy gutter ┃).
   - Brief flash on the block (motion); a11y announces "error: ENOENT".
4. (later) viewport pressure rises → resolver wants to compact          (ERR / shell / COMPACT*)
   - LayoutInputs.phase=ERR triggers parent_clamp bypass.
   - Effective tier never drops below the ER three-row contract.
   - Header, stderr body, recovery footer all retained.
```

### CANCEL — user interrupts a running tool

```
1. STREAMING for 8s; user presses interrupt.                           (STREAMING / ? / DEFAULT)
2. interrupt → ToolRenderingService.cancel_tool(t44).
   - set_axis(phase=CANCEL). Terminal state; subsequent events for t44 are no-ops.
   - Header pulse stops; a "cancelled" chip replaces duration.
   - Live tail renderer freezes content as-is (no further appends honored).
   - Body is whatever was streamed; no classifier run (CANCEL is not COMPLETING).
   - Footer affordances change: [c]opy still available, [r]etry available.
   - Motion: brief desaturation flash. A11y: "cancelled".
```

### Preemption — a stale STREAMING block superseded

```
1. tool_invoked{id=t45} → STREAMING                                    (STREAMING / ? / DEFAULT)
2. tool_invoked{id=t45} again (same id, fresh GENERATED).
   - Preemption detected: prior block transitioned to CANCEL via _terminalize_tool_view.
   - Race-loser feedback fires before the new block enters STARTED (FC-2).
   - The new block mounts as a fresh GENERATED; old block's view-state is
     marked terminal and visually dimmed.
   - Order on screen is preserved (old above, new below); they are different
     view-states sharing an id history.
```

### Group fan-out with mixed states

```
plan_step{id=p7, "refactor auth", children=[t46, t47, t48]}

1. broker.bind_children(p7, [t46, t47, t48])
   - PlanSyncBroker creates ToolGroupState(p7, PENDING).
   - Group header mounts: "▼ refactor auth · 3 calls · 0/3 done · PENDING"

2. t46 → STARTED → STREAMING                    group: any-running → RUNNING
3. t46 → DONE                                   group: 1/3 done; still RUNNING
4. t47 → STARTED → STREAMING (concurrent with t48 starting)
5. t48 → STARTED → ERR (stderr, exit 1)         group: any-error → ERR
   - Group header re-binds to ERR cell rule: "▼ refactor auth · 3 calls · 1 error · ERR"
   - Border tint propagates to group surround.
   - DENSITY does NOT propagate up: group does not pick a tier from t48.
   - Children render at their own (phase, kind, density). t48 is ERR DEFAULT;
     t47 is STREAMING DEFAULT; t46 is DONE COMPACT (auto-collapsed after done).
6. Aggregation is incremental: each child transition triggers one broker tick,
   debounced 30ms, ≤50ms to repaint group header.
```

---

## What this concept made happen (consolidation log)

Three consolidations, all landed. Each was its own spec.

1. **Density resolver, single owner.** `tool_panel/layout_resolver.py::ToolBlockLayoutResolver` owns `tier`, `collapsed`, `_DROP_ORDER_*`, drop-order trimming, and footer visibility. Header / body / footer subscribe via `panel._resolver`. Auto-collapse rules are methods on the resolver, not side-effects of `set_result_summary`. (See specs DR-1..5, DU-1..6.)

2. **Renderer registry takes context.** `pick_renderer(cls_result, payload, *, phase, density, user_kind_override=None)` — single entry, single registry. Streaming-tier renderers participate via `accepted_phases`; `StreamingBodyRenderer` is now a backward-compat alias for the unified `BodyRenderer` ABC. (See specs R-2A-1..6, R-2B-1..6.)

3. **Per-block axis bus.** `ToolCallViewState` holds PHASE + KIND + DENSITY with a `set_axis` choke-point and `_AxisWatcher` protocol. Widgets watch the view-state instead of private flags. (See spec R3-AXIS-01..03.)

---

## Surrounding surfaces

The 3-axis cube describes a single block. Six adjacent surfaces touch the cube but live next to it. Each is named here so reviewers know where to file a change that does not fit cleanly on (phase, kind, density).

### PHASE transition model

The PHASE values listed earlier are nodes; the edges matter too. `services/tools.py::ToolRenderingService` is the single transition owner:

```
GENERATED ─► STARTED ─► STREAMING ─► COMPLETING ─┬─► DONE
                                                  ├─► ERR
                                                  └─► CANCEL   (terminal)
```

Rules: terminal states are absorbing (`_TERMINAL_STATES`); transitions are idempotent on re-entry; `set_axis` is the choke-point that publishes new state to subscribers; preemption (a STREAMING block superseded by a fresh GENERATED with the same id) collapses the prior block to CANCEL before the new one enters STARTED. (See specs SM-01..06, SM-HARDENING-01/02, R3-AXIS.)

**View-state lookup contract.** Tool-call ids are *not* unique across an entire session — preemption and user-`r` retry both reuse an id. The service maintains two indexes:

- `live_by_id: dict[str, ToolCallViewState]` — at most one entry per id; points to the *non-terminal* view-state. Cleared on entry to a terminal state.
- `history_by_id: dict[str, list[ToolCallViewState]]` — append-only; preserves prior terminal view-states for scrollback / `c` copy / a11y replay.

Routing rules:

1. **Inbound runtime events route to `live_by_id` only.** A `tool_output_chunk{id=t42}` arriving after `t42` was preempted is dropped (logged at `debug`); the new live `t42` view-state has not started yet, so the chunk does not belong to it either.
2. **Preemption sequence.** On a fresh `tool_invoked{id=X}` while `live_by_id[X]` is non-terminal: (a) call `_terminalize_tool_view(prior, CANCEL)` which fires race-loser feedback; (b) move prior into `history_by_id[X]`; (c) `del live_by_id[X]`; (d) create new view-state and insert as `live_by_id[X]`. The new block enters GENERATED only after the prior is fully off `live_by_id` — there is no overlap window.
3. **`r` retry semantics.** Same as preemption with one extra step: the new view-state inherits a `retry_of: prior_view_state_ref` link so the renderer can show "retry of <prior>" affordance. Scrollback position of prior is preserved (the prior view-state still owns its rows in scrollback; the new one mounts below).
4. **Terminal-state events are no-ops.** A late `tool_done{id=t42}` for a view-state already in CANCEL/ERR is logged and dropped — `_TERMINAL_STATES` absorbs.
5. **Widgets resolve once.** A `ToolBlock` widget binds to one specific view-state instance at mount time and never re-binds. Preemption mounts a *new* `ToolBlock`; the prior widget continues to render its now-terminal view-state until scrolled off.

### ToolGroup / PlanSyncBroker — the multi-block primitive

A plan step can spawn one or more tool calls. **`ToolGroup` is the only legal multi-block container in the harness** — there is no other way to bind blocks together, by design. Anything else (siblings, parents, "related" calls) must either be a group or be unrelated.

```
                        ┌───────────────────────┐
                        │   ToolGroupState      │
                        │   (broker aggregate)  │
                        └──────────┬────────────┘
                                   │  PHASE rollup only
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
      ┌────────────┐       ┌────────────┐       ┌────────────┐
      │  Cube t46  │       │  Cube t47  │       │  Cube t48  │
      │ (P, K, D)  │       │ (P, K, D)  │       │ (P, K, D)  │
      └────────────┘       └────────────┘       └────────────┘
        ▲ parent_clamp       ▲ parent_clamp       ▲ parent_clamp
        └────────── DENSITY propagates DOWN only ───────────┘
```

`services/plan_sync.py::PlanSyncBroker` aggregates child PHASE values into a parent group state (`ToolGroupState`: PENDING / RUNNING / DONE / ERR / CANCELLED). The group has its own header but no body — its body is the children. Aggregation is **incremental** (one child transition at a time), debounced 30ms, ≤50ms to repaint, so very long plans stay cheap.

**ToolGroupState transition graph.** Group state is derived, not authored — it is a deterministic function of the multiset of child PHASE values. The broker recomputes after each debounced tick:

```
PENDING ─► RUNNING ─┬─► DONE       (all children DONE, none ERR/CANCEL)
                    ├─► ERR        (any child ERR)
                    └─► CANCELLED  (no ERR; ≥1 CANCEL; rest DONE/CANCEL)
```

Aggregation rules — order matters because they decide latching:

1. **ERR is sticky once latched.** First child to reach ERR transitions the group to ERR. Subsequent child DONEs do *not* unlatch — group stays ERR for the rest of its life. (Otherwise a 99/100-success plan with one error silently becomes DONE on the last child's completion, hiding the failure.)
2. **CANCELLED requires zero ERR.** If both ERR and CANCEL appear, ERR wins — errors out-rank cancellations in the rollup.
3. **DONE only when all children are DONE.** A group with one PENDING child cannot be DONE even if all started children succeeded. Lingering PENDING children keep the group at RUNNING.
4. **Terminal states are absorbing.** Once a group enters DONE/ERR/CANCELLED, late child transitions are logged but do not re-enter RUNNING. (Prevents a "phantom restart" if a delayed event arrives after the broker has rolled up.)
5. **Idempotent ticks.** Computing rollup with no state change is a no-op — no flash, no repaint, no a11y announce.

`bind_children` runs once at plan registration; rebinding is rejected (ToolGroup membership is immutable post-registration). Children added later belong to a new group.

**Expansion reflow rule.** When a group expands (Enter on collapsed header), the group grows *downward only* — content below the group is pushed; content above (including any focused non-child block) is anchored. Collapse mirrors: rows shrink upward into the header. This is what makes "no surprise re-flow" hold even for a 50-child group expanding under heavy viewport pressure. If downward growth would push the harness footer off-screen, the harness scrolls the new content into view as one motion, not as a series of incremental reflows. When the focused block *is* a child of the expanding group, focus follows the child to its new position (not anchored to viewport offset) — the user is asking to see this group's contents, not to keep their offset.

**Nesting depth.** Groups do not nest. A group's children are tool-call cubes, never other groups. `bind_children(p, [other_group, ...])` is rejected at registration (broker logs at `warning`, treats as no-op). Rationale: a 2-level nest already pushes header chrome past one row of indentation, and the parent_clamp ceiling stops being meaningful when a child is itself a clamp source. If a runtime emits plan-of-plans (e.g. agent-of-agents), the outer level becomes a *session-strip* surrounding surface, not a recursive ToolGroup — a different shape with its own rules. The hard "depth = 1" rule keeps the cube↔cube coupling diagram honest: one group, N cubes, no recursion.

**Group degeneracy.** `bind_children(p, [])` is rejected (empty group is meaningless; broker logs at `warning` and treats as no-op). `bind_children(p, [single])` mounts a normal group surface — the group header is shown even with one child, because the *group* is the named plan-step; the child is the call inside it. Skipping the group surface for single-child plans would create a "where did the plan-step header go?" gap; the cost of one consistent extra row is worth the navigational uniformity.

The group surface is *not* on the cube; it is a coupling between cubes:
- **PHASE** aggregates via the broker (any-child-running → group RUNNING; all-done → group DONE; any-error → group ERR).
- **KIND** does *not* aggregate — a group of mixed-kind children has no group-level kind.
- **DENSITY** propagates *down* via parent_clamp, not up — the group does not pick a tier from its children. The clamp is a *ceiling*: a child's user override (`D`) cannot lift its tier above the parent group's tier; an attempted lift flashes feedback and reverts. Exception: ERR children always bypass clamp regardless of parent (errors out-rank user attention budget).

**Group overflow rule.** Large fan-outs need a body cap — a 50-child plan even at TRACE is 50 rows. The group body has a `child_render_cap` per tier:

| Group tier | Max visible children | Overflow chip |
|------------|----------------------|---------------|
| HERO       | unbounded            | — |
| DEFAULT    | 12                   | `…+N more children · N_err errors · N_running running` |
| COMPACT    | 4                    | same pattern, only ERR + RUNNING children visible above the chip |
| TRACE      | 0 (children hidden)  | `… N children · N_err errors` |

ERR children are always promoted past the cap (an error is never compacted away — same rule as the cube's ER cell). The overflow chip is focusable; pressing `Enter` expands the group to HERO, lifting the cap.

(See spec PG-1..PG-4, R3-NESTED.)

### Feedback contract (motion channel)

`services/feedback.py` is the single owner of flashes, pulses, and warning toasts — the motion channel. Rules: uniform tone per channel, race losers feedback before the winner appears, preemption replaces an in-flight flash, and a queue guard prevents pile-up. A skin can change the *colour* of a flash; it cannot change which event flashes. (See spec FC-1..FC-4.)

### Error recovery contract

When PHASE = ERR, the block re-binds its three rows to a fixed contract (see "Per-tier behavior contract" above). This is a `(PHASE = ERR, *, *)` cell rule, not a parallel system. The DENSITY resolver bypasses the parent clamp on errors so a clamped child can still scream. (See spec ER-1..5.)

**Error category taxonomy.** The header chip ("ENOENT", "EACCES", "EXIT 128", etc.) is derived deterministically from a small, named enum — not free-form stderr text. Resolution order:

1. **Stderr signal regex** — known patterns map to categories (`fatal: ambiguous argument` → `ENOENT`-class for git, `command not found` → `ENOENT`, `permission denied` → `EACCES`, `connection refused` → `ENETUNREACH`, etc.). The regex set is a closed module-level table.
2. **Exit code class** — non-zero exit codes fall back to coarse categories (`signal`, `usage`, `runtime`, `unknown`) when no stderr signal matches.
3. **Bare fallback** — when neither yields a category, the chip is the literal `"error"`. Never blank, never the raw stderr first line.

The taxonomy lives next to the rendering service so that recovery hints (`[r]etry`, `[e]dit-args`) can branch on category rather than parsing strings at the footer. Adding a category = appending to the regex/exit-class table + listing the recovery hints it should surface. The chip vocabulary is closed; renderers and skins read it but never invent new categories.

### Hint pipeline

The footer's affordance list is generated, not authored. `tool_panel/_actions.py::_collect_hints` reads (phase, kind, density, focus) and yields candidate hints; `_render_hints` formats them; `_truncate_hints` drops by priority when width is tight. Hints are derived from the axes — no static tables, no per-widget hint authoring. New affordances are added by appending a candidate, not by editing a string. (See spec H-1..H-4.)

**Hint priority order** (highest first; F1 always pinned, never subject to drop):

1. **Recovery hints** for ERR (`[r]etry`, `[e]dit-args`, etc.) — branch on error category.
2. **State-required hints** (`[Esc]exit-scroll` while in-block scroll mode; `[↵]expand` on group overflow chip).
3. **KIND-specific affordances** (`[c]opy` always present once payload exists; `[t]oggle-kind` when the eligibility set has >1 entry; `[T]revert` when `user_kind_override` is set).
4. **Density / view controls** (`[D]ensity`, `[Shift+D]`).
5. **Generic** (`[F1]help` — pinned).

`_truncate_hints` drops bottom-up. F1 is unconditional. Recovery hints lead and are never dropped while ERR remains. The list is data, not strings — adding a hint = appending a `(priority, condition, label, action)` tuple to the candidate set. Hidden hints surface via `F1`, so the priority list is also the help-overlay order.

**Microcopy contract** (applies to every user-visible label — hints, chips, error categories, a11y short labels):

1. **Bracket-key form.** Bound key wraps the inner glyph: `[c]opy`, `[r]etry`, `[Esc]exit-scroll`, `[↵]expand`. Single letters lowercase; named keys (Esc / ↵ / F1 / Shift+D) keep their canonical casing inside the brackets. Never `[C]opy` or `[c] copy` — no space, no shifted letter.
2. **Verb-first, lowercase, no period.** Labels are imperative-mood verbs (`copy`, `retry`, `expand`, `toggle-kind`). No leading capitals (proper nouns aside). No trailing punctuation. Hyphenate multi-word actions (`toggle-kind`, `edit-args`) — no spaces inside a label.
3. **Length cap.** Each rendered hint ≤ 14 chars including brackets and key. Longer = drop a syllable or pick a shorter verb. Width pressure should drop hints, never truncate them mid-word.
4. **No marketing voice.** "show details", not "explore your options". The harness is a console, not an onboarding flow.
5. **Status chips mirror the rule.** `DONE`, `ERR`, `CANCEL`, `STREAMING` — uppercase short forms, never sentence-case ("Done") or long forms ("completed successfully").

A label that violates the contract is a review block, not a style nit. The cumulative effect of 30 inconsistent labels per screen is what separates a console from a UI. Enforced via meta-tests in `test_microcopy_and_confidence.py::TestStatusChipCasing` and `TestLiveTailChip`.

### User overrides

User input that overrides a resolver is recorded on `ToolCallViewState`, not on the widget that received the keypress. `user_kind_override` (KO-1..5) and `_user_collapse_override` (DR-2) are both view-state fields; the resolver reads them as inputs. This invariant means a user override survives re-mount, view-state replay, and parent-clamp recomputation. Widgets are stateless windows onto the view-state.

---

## Where this frame *does not* fit cleanly

Honest limits, worth knowing before extending:

- **Long-running background tools that exit the viewport while STREAMING.** Cross-block concern — belongs to a session strip / status bar surface, not the tool block's axes.
- **KIND that legitimately changes mid-stream.** Rare but real (e.g. a tool that emits a log header and then JSON). Current frame resolves KIND once at COMPLETING; supporting mid-stream re-classification would require a per-segment KIND, which is a different shape. *Stub design for the day this matters:* a `BodySegment` list on view-state, each with its own KIND and (start, end) byte offsets; classifier emits a boundary token; `pick_renderer` runs per segment; one PHASE still governs the block. Punted because the runtime currently has no segmentation contract.
- **Calls without a clear "completion" event** (long-poll subscriptions, watchers). PHASE collapses badly — STREAMING never ends. Today these are modelled as repeating short calls; a true streaming-forever primitive does not fit.
- **Cross-block search / filter / find.** With hundreds of blocks per session, "find the diff for auth.py" has no surface. Not on the cube; needs a new surrounding surface (sketch: a `/`-triggered overlay that filters scrollback by category, kind, name, error-state, with focus-jump on Enter). Listed here so the gap is named, not silently absorbed into the cube.
- **Cross-block diffs / aggregations** (e.g. "show me what changed across these three calls"). Not on the cube; would need a new surrounding surface, likely co-resident with the find overlay.
- **Persistence and scrollback semantics.** The cube is in-session only. View-state is not durable across restarts; historical blocks remain at whatever tier they last resolved to (typically TRACE) for as long as the scrollback retains them. Cross-session persistence (replay a finished session, scrub through a long-completed plan) is out of scope — would need a serialization contract on `ToolCallViewState` and a scrub-mode that disables resolvers in favour of recorded tiers. Named so that "save my session" requests have a place to land.
- **Internationalization.** KIND values, category chips, hint strings are English-source. The frame does not currently route them through a translation layer; a11y strings would need the same. *Stub:* every visible string already routes through a small set of helpers (`chip()`, hint pipeline, a11y label builders) — making them locale-aware is a one-shot wrap rather than a deep refactor. Out of scope until a localized harness target appears.

---

## Rejected designs (anti-pattern catalogue)

Patterns proposed in review and rejected. Recorded so we don't re-litigate.

| Proposal | Why rejected | Where it actually belongs |
|----------|--------------|---------------------------|
| `priority` field on a block | Conflates DENSITY with focus/recency. "Important" is the user's relationship to the call, not a property of the call. | Resolver input (focus, recency) — already there. |
| Per-renderer density (`CompactDiffRenderer`) | Duplicates the DENSITY axis. Renderer should declare *needs at each tier*, not own its own tier. | `BodyRenderer.render(*, density)` — already there. |
| `pinned` axis | Same shape as priority. User pin is a viewer-relationship concern. | View-state user override flag, not an axis. |
| Skin token `$tier-compact-force` | Channel reaching an axis. Skin reshapes how tiers *look*, not which tier resolves. | Reject. |
| Reading `view_state.phase` inside a renderer to swap renderer | KIND resolution leaking into a subscriber. | Route through `pick_renderer(*, phase=...)`. |
| Group-level KIND (e.g. "this group is mostly diffs") | KIND does not aggregate; a mixed group has no kind. Inventing one creates ambiguity. | Reject; chips per child instead. |
| User override of PHASE | PHASE is ground truth. "Mark as done" against the runtime is meaningless. | Reject; user *cancel* triggers a real CANCEL. |
| Per-widget hint authoring (e.g. `widget.add_hint("[r]etry")`) | Bypasses the hint pipeline; static authoring rots fast. | Append candidate to `_collect_hints`. |
| Second resolver for "auto-expand on error" | Errors are an ER cell rule, not a separate resolver. | Encode in `LayoutInputs.phase=ERR` clamp bypass. |
| Multi-block container other than ToolGroup | Coupling sprawl. ToolGroup is the only legal one. | Use ToolGroup or treat as unrelated. |

---

## Regression-testing the UX guarantees

The seven UX guarantees (liveness ≤100ms, recognition before reading, most-useful-most-prominent, no-surprise-reflow, user authority on KIND, errors-are-loud, redundant-signal) are testable, not aspirational. Each has a concrete fixture pattern:

| Guarantee | Test shape |
|-----------|------------|
| Liveness ≤ 100ms | Inject PHASE transition; assert `set_axis` fires within 100ms (monotonic clock); assert at least one channel update queued before the deadline |
| Recognition before reading | Snapshot test: HERO/DEFAULT block at PHASE=DONE — assert category chip + glyph + colour all present and resolve to the same KIND |
| Most-useful-most-prominent | Resolver fixture matrix (focus × pressure × phase × body-rows) → assert ranked output; the focused or ERR block must be in the top tier; regression on this matrix == design regression |
| No surprise reflow | Density change with focused block; assert focused block's `id` remains visible (offset within viewport may change, but `is_in_view(focused) == True` before and after) |
| User authority on KIND | `t` cycle; force re-mount; assert `user_kind_override` survives and `pick_renderer` honours it |
| Errors are loud | Resolver fixture with parent_clamp=TRACE + child PHASE=ERR; assert child renders ≥ DEFAULT-equivalent three-row contract |
| Redundant signal | Per-row in the redundant-signal table, assert ≥2 of (visual, glyph, motion, a11y) produce non-empty output for the signal |

These belong in `tests/tui/` as resolver-level snapshot tests, not UI integration tests — fast, deterministic, run in seconds. A failing snapshot here is a *design* failure and should reach review, not be auto-blessed. The contrast gate (a11y channel) and motion-intensity-`none` mode are particularly worth testing because they're easy to silently regress.

**Sampling the resolver matrix.** The full focus × pressure × phase × body-rows cross-product is ~2 × 4 × 6 × 12 ≈ 576 cells; full coverage is wasteful and brittle. Sampling strategy:

1. **Every band boundary** — pressure crossings 0.6 / 0.85 / 1.0; HERO_MIN_BODY_ROWS / DEFAULT_BODY_CLAMP / LARGE_PAYLOAD_ROWS thresholds; phase enter/exit terminal states.
2. **Every row of the redundant-signal table** asserted at least once.
3. **Every illegal cell from the reachability matrix** asserted to refuse (resolver fixture must reject, not silently coerce).
4. **Random interior sampling** at PR time via a `pytest --hypothesis-seed` fixture that draws (focus, pressure, phase, rows) tuples from the legal cells.

Coverage assertion lives in `tests/tui/test_resolver_matrix_coverage.py`. The point is not to assert every cell; it is to assert every *transition between cells* the user can perceive. Boundary + signal + illegal-refuse + random gets there without combinatorial blowup.

When adding a new feature: add its row to the redundant-signal table, name which guarantee it could violate, and write the fixture before merging.

---

## How to use this document

When proposing a new tool-block feature or fixing a regression:

1. Identify which axis the change touches (PHASE / KIND / DENSITY) or whether it is a channel (visual / glyph / motion / a11y).
2. Locate the resolver for that axis. If you find yourself adding a *second* resolver, stop — consolidate first.
3. Check whether the change requires a new (phase, kind, density) cell behavior or modifies an existing one.
4. Check the coupling table. If your change reads across axes and isn't in the table, it's a violation.
5. Check the redundant-signal rule. New signals must hit at least two channels.
6. Check the perception budget table. If your change affects timing, name the budget you're holding.
7. If it requires reaching across channels (e.g. "skin should force compact tier"), reject the cross-cut. Channels cannot reach axes; resolvers do not read each other's private state — they read `ToolCallViewState`.

When reviewing:

- "Where does this state live" should have one answer per axis. Multiple answers = consolidation opportunity.
- "Why does this renderer behave differently in streaming vs final" is answered by PHASE, not by the existence of a separate hierarchy.
- New skin tokens are channel additions. New skin *behaviors* (tier overrides, classification hints) are an axis violation.
- A proposed fourth axis must satisfy: property of the call (not the viewer), single resolver, publishable on view-state. Otherwise it is a surrounding surface.
- A proposed fifth channel must satisfy: independent override scope, not derivable from existing channels. Otherwise extend an existing channel.

When this doc drifts from the code: flag it, don't silently edit. Bump the version line and add a `## Changelog` entry.

---

## Changelog

### v3.6 — 2026-04-27 — SLR-1/SLR-2/SLR-3: Streaming legibility + visual rhythm

- **SLR-1 (HG-1): Multi-block rhythm contract.** HERO and DEFAULT blocks earn one row of vertical rest (margin-bottom: 1); COMPACT and TRACE pack tight (0). Group children always 0. ERR phase always earns the gap. CSS-only; no resolver change. New "Multi-block rhythm" subsection added to "The frame at a glance."
- **SLR-2 (HG-2): Colour-rendered mocks.** `scripts/render_concept_mocks.py` generates SVG mocks from `SkinColors.default()` committed to `docs/concept_mocks/`. References inserted between sentinel comments after "## Canonical block mocks."
- **SLR-3 (HG-3): Streaming KIND hint.** `streaming_kind_hint` classmethod on `BodyRenderer`; implemented on `DiffRenderer`, `JsonRenderer`, `CodeRenderer`. Per-view sniff buffer (threshold: 8 bytes) in `append_tool_output`. Hint written via axis bus (`set_axis(view, "streaming_kind_hint", hint)`); clears at COMPLETING/ERROR/CANCELLED/DONE. `ToolHeader` registers axis watcher and swaps icon glyph + `~<kind>` chip. No motion flash. New row in redundant-signal table; note added to PHASE→KIND coupling row.

### v3.6 — 2026-04-27 — R4-1: Enter binary toggle

Enter is now a 2-state machine (COMPACT ↔ NOT-COMPACT). ChildPanel override deleted;
hint labels read "expand"/"collapse" matching action. HERO reachable only via D.

### v3.5 — 2026-04-27

Outstanding-UX audit pass: H1–H6 + M1 from the v3.4 review.

- **Header scan budget** added to perception budgets (H1): ≤500ms / ≤7 chips per HERO header (Miller's 7±2); per-tier chip caps (DEFAULT 5, COMPACT 3, TRACE 2). Drop-order fires on chip-count overflow even at low width pressure. Recognition is now a measurable contract, not implicit.
- **Density tier transition is instant** (H2): tier reflow is a hard repaint with a one-frame outline flash on geometry delta — no easing, no interpolation. New "Density tier transition repaint" budget row + cross-reference on the existing 200ms row. Animation across reflow is forbidden because terminals can't sustain 60fps interpolation cleanly; stutter is worse than a clean cut.
- **Pre-first-chunk skeleton** added to PHASE owns liveness (H3) + budget row: kind icon + dim `· · ·` + motion-pulse mounts at 100ms after STARTED if no chunk yet, dismissed on first chunk. Closes the 0–120ms perceived-hang window for slow-start tools. Skeleton is widget-local, no PHASE transition.
- **Settled state** new paragraph in PHASE owns liveness (H4) + budget row: 600ms post-DONE/CANCEL/ERR with no events → block enters `settled`; suppresses motion on incidental events (skin reload, viewport resize, sibling reflow) except focus and ERR transitions. Prevents polish events from leaking flashes onto stable history.
- **Group nesting depth = 1** added to ToolGroup section (H5): groups do not nest. `bind_children(p, [other_group])` rejected. Plan-of-plans belongs on a session-strip surrounding surface, not a recursive ToolGroup.
- **Microcopy contract** added to hint pipeline (H6): bracket-key form (`[c]opy` not `[C]opy`), verb-first lowercase no-period imperative labels, ≤14 char cap, hyphenated multi-word, status chips uppercase short forms. Five-rule contract; violations are review blocks.
- **Visual channel semantic palette** new subsection in channels (M1): closed 10-role set (`accent`, `accent_dim`, `success`, `warning`, `error`, `info`, `muted`, `surface`, `surface_alt`, `border`); skins must bind every role; partial palettes rejected at load. Role catalogue grows only when a new signal would otherwise overload an existing role.

### v3.4 — 2026-04-27

Outstanding-UX audit: H1–H5 + M1–M10 from the v3.3 review.

- **Width pressure axis** added to viewport pressure section (H1): width pressure formula, four-band table (chip drop → name elision → tier step-down), `MIN_BLOCK_COLS` / `MIN_VIEWPORT_COLS` floors, per-renderer wrap rules. Width and viewport pressure compose; tier step-down is the only width-driven tier change.
- **Body truncation contract** new subsection between per-tier table and perception budgets (H2): tail-bias default + per-KIND opt-out (head-bias for json/code, hunk-aware for diff, priority for search, etc.). Strategy is a renderer property, not an axis. Silent elision forbidden.
- **Live-tail scroll behaviour** added to PHASE owns liveness (H3): sticky-bottom default, three exit conditions, per-block widget-local state (not view-state). `↓ N more rows` chip on detach.
- **Focus visibility** new subsection in focus model (H4): brighter-accent border + `›` header prefix, geometric stability across tiers. Single contract that makes "no surprise re-flow" verifiable.
- **Density cycle** explicit in block-level key contract (H5): `D` order `DEFAULT → COMPACT → TRACE → HERO → DEFAULT`; `Shift+D` reverse; pressure-forbidden tiers flash + skip silently.
- **ERR header chip count** explicit in ER override row (M1): exactly two chips (category + outcome `ERR`), every other chip dropped at every tier including HERO.
- **Hint priority order** added to hint pipeline section (M2): five-level hierarchy (recovery > state-required > KIND-specific > density > generic), F1 always pinned. List is data, not strings.
- **Long-call / large-payload promotion** added after info-value hierarchy (M3): duration > 5s and rows > 200 promote one tier longer. Static thresholds, one-way (no demotion of fast calls).
- **Group expand/collapse budget** added to perception budgets + **expansion reflow rule** added to ToolGroup section (M4): 200ms settled layout, downward growth only, focused non-child anchored, focused child follows expansion.
- **Mouse / selection model** added to block-level key contract (M5): mouse-drag = terminal-native text selection through to body widget; mouse-click on header = focus + group toggle; hover never moves focus.
- **Retry counter** added to `r` row (M6): `retry_count` field on view-state, chip `retry × N`; preemption-CANCELs do *not* increment.
- **Group degeneracy** added to ToolGroup section (M7): empty group rejected, single-child group renders normal group surface (uniform navigation > one row saved).
- **Classifier confidence threshold** named in KIND implementation map (M8): `KIND_MIN_CONFIDENCE` in `content_classifier.THRESHOLDS`, currently 0.6.
- **Skin hot-reload** row added to concurrency invariants (M9): pulses re-bind at next cadence boundary (≤800ms), no mid-pulse colour swap, glyphs static.
- **Sampling the resolver matrix** added to regression-testing section (M10): boundary + signal + illegal-refuse + random sampling strategy; ~576-cell cross-product is not enumerated cell-by-cell.

### v3.3 — 2026-04-27

Top-priority audit fixes (H1–H4 + M9 from the v3.2 review).

- **Focus model** new section between user-control asymmetry and channels: auto-focus-on-entry rules, keyboard-only movement, stickiness through transitions and scroll, group focus semantics. Focus is now a documented resolver input rather than an undefined assumption. (H1)
- **Pressure / tier fixed-point** added to the viewport pressure section: bounded two-pass resolution with conservative tie-break to the tighter tier. Eliminates oscillation risk and divergence between implementations. (H2)
- **HERO body height contract** added to canonical mocks: HERO body bounded by `viewport_rows − chrome_rows`; overflow shows first N − 1 rows + scroll chip; below `MIN_HERO_VIEWPORT_ROWS` HERO is disabled. Closes the "no clamp + finite viewport" contradiction. (H3)
- **Cube reachability** new section between coupling table and implementation map: which `(PHASE, KIND, DENSITY)` cells are legal, which are illegal, and the test surface that asserts the matrix. KIND before COMPLETING is now formally illegal, not "unspecified." (H4)
- **How budgets are measured** added to perception budgets: CI bench (`test_axis_budgets.py`), runtime trace flag (`HERMES_TUI_TRACE_BUDGETS=1`), "no fixture, no budget" rule. Budgets are now enforced contracts, not aspirations. (M9)

### v3.2 — 2026-04-27

Audit pass closing seven gaps identified in v3.1 review (G1–G5 + M1–M2).

- **ToolGroupState transition graph** added to ToolGroup section: PENDING → RUNNING → {DONE, ERR, CANCELLED}; ERR is sticky once latched; ERR > CANCEL; DONE requires all children DONE; terminal absorbing; idempotent ticks; `bind_children` immutable post-registration. (G1)
- **Resolver and aggregation cost budgets** added to perception budgets: ≤1ms/block resolver, ≤5ms/100-children group aggregation, ≤50ms classifier, 250ms shared stall-detector tick. New "compound budgets" note covers fan-out repaint composition. (G2)
- **Concurrency invariants** new section between implementation map and dispatch contract: `set_axis` is event-loop-only, workers must marshal via `call_from_thread`, stall detector is one shared interval (not per-block) and emits motion-channel updates rather than PHASE transitions, motion-intensity swap is synchronous, broker debounce on event loop. View-state needs no locks. (G3)
- **Slow-renderer fallback contract** added to dispatch failure modes: 250ms soft deadline mounts placeholder + worker-thread render; 2s hard deadline cancels and falls to `RawTextRenderer`; classifier 50ms budget cancels to `unknown`. (G4)
- **View-state lookup contract** added to PHASE transition model: `live_by_id` (≤1 per id) + `history_by_id` (append-only); inbound events route to live only; preemption sequence specified atomically; `r` retry inherits `retry_of` link; widgets bind once and never re-bind. (G5)
- **Stall channel-bleed honesty** added to motion-intensity section: stall is motion-primary with glyph-fallback under reduced/none — a controlled exception to channel orthogonality, named rather than denied. (M1)
- **HERO eligibility precedence** added to canonical mocks: pressure gate → threshold gate → tie-break. Focus is a qualifier, not an override; only `PHASE = ERR` bypasses gates. (M2)

### v3.1 — 2026-04-27

Audit pass closing 20 policy gaps surfaced in v3.0 review.

- Added **design voice** paragraph to "Why this document exists" — names the aesthetic posture ("monitoring console at rest").
- **Motion intensity dial** added to channels: `full / reduced / none`, with `prefers-reduced-motion` and recording mode mapped. Stall freeze gets a static glyph fallback under reduced/none.
- **A11y channel rules** subsection: live-region politeness policy (polite for transitions, assertive for ERR/CANCEL only, never per-chunk), announcement frequency (one-per-state-change), WCAG contrast gate (≥3:1 borders / ≥4.5:1 text + errors), long-form label rule.
- **Stall is motion-only** — clarified PHASE liveness section: stall does *not* introduce a `STALLED` PHASE node; PHASE stays STREAMING; motion swaps cadence; subscribers see no transition.
- **HERO tie-break** pinned: focused ▸ only-in-viewport ▸ first-in-viewport ▸ most-recent. Exactly one HERO per viewport.
- **Empty (kind=empty) and Binary (kind=binary) block mocks** added to canonical mocks.
- **Viewport pressure formula** defined (`rows_consumed_visible / available_rows`) with band table.
- **Threshold reference** to `tool_panel/layout_resolver.py::THRESHOLDS` — concept names that thresholds exist; numeric values live in code.
- **Information-value hierarchy** documented as the rationale behind `_DROP_ORDER`. Code mirrors hierarchy; if they disagree, hierarchy wins.
- **HERO "all hints"** softened to "highest-priority hints fitted to width, F1 pinned" — the previous wording could not survive narrow terminals.
- **`r` retry semantics** clarified: same id, prior view-state collapses to CANCEL via preemption path before new GENERATED.
- **`t` KIND eligibility** defined: kinds whose registered `BodyRenderer.accepts(payload, phase)` returns true; binary excluded by default; TEXT excluded after KO-A.
- **Error category taxonomy** added to ER section: stderr-regex → exit-class → bare `error` fallback; closed enum, no free-form chips.
- **Group overflow rule** added: per-tier `child_render_cap` with overflow chip; ERR children always promoted past the cap.
- **Child clamp ceiling** clarified: parent_clamp is a ceiling, user `D` cannot lift child above parent; ERR bypasses.
- **Persistence and scrollback** added to "where the frame does not fit" — in-session-only scope named, cross-session persistence punted with a sketch.
- **Mid-stream KIND** got a stub design (`BodySegment` per-segment KIND).
- **Cross-block search/filter** added as a named surrounding surface gap with sketch (`/` overlay).
- **Internationalization** stub: existing chip/hint helpers as the locale wrap-point.
- New section **"Regression-testing the UX guarantees"** — fixture patterns for each of the seven guarantees; resolver-level snapshot tests, not UI integration.

### v3.0 — 2026-04-27

- Added **canonical block mocks** (HERO / DEFAULT / COMPACT / TRACE / ERR / group).
- Added **per-tier behavior contract** table (resolver's external promise).
- Added **perception budgets** table (latency, cadence, debounce numbers).
- Promoted **a11y to a first-class channel** (now four: visual / glyph / motion / a11y), with redundant-signal rule.
- Added **renderer purity rules** and **failure modes** to dispatch contract.
- Added **block-level key contract** table.
- Added **unhappy-path worked examples** (ERR, CANCEL, preemption, group fan-out).
- Added **rejected designs (anti-pattern catalogue)**.
- Added **user-control asymmetry** subsection (PHASE has no override, by design).
- Added **cube↔cube group diagram**.
- Renamed "vocabularies" (rendering channels) → **channels**; reserved "vocabulary" for axis value sets. Footnote at first use.
- Consolidated per-axis goals into a unified **UX guarantees** subsection.
- Removed accessibility from "where this frame does not fit cleanly" (now first-class).

### v2.0 — earlier 2026-04

- Initial public concept note. Three axes named, coupling table, surrounding surfaces, happy-path worked example.
