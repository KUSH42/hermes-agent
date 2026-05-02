# Composer Concept: Three Axes, One Input Surface

**Status:** APPROVED
**Version:** 1.0
**Last updated:** 2026-04-28
**Scope:** the prompt-entry surface at the bottom of the OutputPane — chevron, text area, ghost suggestion, legend bar, completion overlay, and the relays that feed it.
**Audience:** anyone touching `hermes_cli/tui/input/`, `widgets/input_legend_bar.py`, `completion_overlay.py`, `completion_list.py`, `completion_context.py`, `path_search.py`, or app-level routing for those (`HermesApp.on_path_search_provider_batch`, `_open_skill_picker`, `_svc_keys.dispatch_input_submitted`).

---

## Why this document exists

The composer is the single channel through which every user intention reaches the harness. Its surfaces have grown organically: an InputMode enum here, a CompletionTrigger dataclass there, a PathSearchProvider relay routed through the app, a ghost-text mixin layered onto a vendored TextArea. The pieces work, but there is no shared frame that names *which axis a feature touches*. Reviewers debate "where does this rule belong?" because the territory is not mapped.

This note declares the frame. It does not propose a rewrite. It names what the code already does so future audits, specs, and reviews share vocabulary.

### Design voice

The composer is a quiet line that tells the user three things at once: **what regime they are in** (typing freely, recalling, locked, shelling), **what they are typing** (a prompt, a command, a path, a skill), and **what the harness will offer back** (a ghost, an overlay, a picker, a flash). Idle, it is one row of dim chrome. Active, it gains a chevron color shift, a single legend row, and at most one floating overlay. The aesthetic target is "search field at rest" not "IDE with palettes": rich when consulted, recedes otherwise. Every channel rule below serves that posture.

---

## The frame at a glance

```
            ┌─────────────────────────────────────────────────────┐
            │           HermesInput axis bus (single instance)     │
            │   ┌────────┐    ┌────────┐    ┌──────────────┐       │
            │   │  MODE  │    │  KIND  │    │    ASSIST    │       │
            │   └───┬────┘    └────┬───┘    └──────┬───────┘       │
            └──────┼──────────────┼────────────────┼───────────────┘
                   │              │                │
    ┌──────────────┼──────────────┼────────────────┼──────────────┐
    │              ▼              ▼                ▼              │
    │      ┌────────────────────────────────────────────────┐     │
    │      │  Channels (visual / glyph / motion / a11y)     │     │
    │      │  chevron · legend · overlay · ghost · placeholder│   │
    │      └────────────────────────────────────────────────┘     │
    │              │              │                │              │
    │              ▼              ▼                ▼              │
    │      ┌──────────────────────────────────────────────┐       │
    │      │  Chevron · TextArea · GhostText · LegendBar  │       │
    │      │            · CompletionOverlay               │       │
    │      └──────────────────────────────────────────────┘       │
    │                       (one composer)                        │
    └─────────────────────────────────────────────────────────────┘
                                │
                   ┌────────────┴────────────┐
                   ▼                         ▼
           PathSearchProvider           Skill picker,
           (app-level relay)            feedback service,
                                        history file I/O
```

Every observable state of the composer is the product of **three orthogonal axes**:

| Axis | Values | Question |
|------|--------|----------|
| **MODE** | `NORMAL, BASH, REV_SEARCH, COMPLETION, LOCKED` (resolver: `_compute_mode()`) | What regime is the composer in? |
| **KIND** | `NONE, NATURAL, SLASH_COMMAND, SLASH_SUBCOMMAND, PATH_REF, PLAIN_PATH_REF, ABSOLUTE_PATH_REF, SKILL_INVOKE` (resolver: `detect_context()`) | What is the user typing? |
| **ASSIST** | `NONE, GHOST, OVERLAY, PICKER, HINT_FLASH, ERROR_FLASH` (no central resolver — see drift §4) | What is the composer offering back? |

Each axis has a **resolver** (decides the value) and **subscribers** (react to it). MODE is published on `HermesInput._mode` (reactive); KIND lives on `_current_trigger.context` (`CompletionTrigger`, never `None` — initialized to a `NONE`-context trigger); ASSIST is implicit — it is the union of `suggestion`, `CompletionOverlay --visible`, app skill-picker visibility, and active feedback flashes. Every render decision is a lookup into the (mode, kind, assist) cube. Every part of the composer (chevron, placeholder, legend, ghost, overlay) is a function of those three values, written in shared channels.

> **Note on terminology.** "Mode" already exists in code as `InputMode`; the axis is named to match. "Kind" generalises the existing `CompletionTrigger.context` field — the doc uses **KIND** as the axis name and prints the actual enum values verbatim to keep the indirection thin. "Assist" is a new umbrella for the four ways the composer offers feedback; it has no single source field today and that absence is part of the drift this doc names.

### UX intent per axis

Each axis owns one user-visible question; that ownership is what makes the axes orthogonal.

- **MODE owns regime legibility.** "Am I typing a prompt, recalling history, shelling, or waiting?" The user must know this within one glance, regardless of what they are typing or whether help is offered. Chevron + placeholder carry it.
- **KIND owns intent classification.** "Is this a prompt, a slash command, a path, a skill?" KIND is invisible until the user types a sigil; before that, it sits at `NONE`. The sigils themselves are the primary glyph signal; the overlay is the secondary visual signal.
- **ASSIST owns offered help.** "Is the composer suggesting, listing, picking, flashing, or quiet?" ASSIST is the only axis the *user* does not control directly — the composer decides whether to offer help based on (MODE, KIND, content, history, focus, lock). When MODE and KIND are unambiguous and uncontroversial, ASSIST falls to `NONE` and the composer goes silent.

Axis collisions (e.g. should ERROR_FLASH win over BASH placeholder?) are decided by the channel rules, not by axis precedence — see §Channels.

---

## Canonical composer mocks

The frame is structural; the mocks below pin down what the surface looks like for the most common cube cells. Skin colors are not represented; structure and glyphs are. The leading glyph in each box (`❯ $ ⟲ ⊞ ⊘`) is a *schematic* depiction of the sibling `#input-chevron` Label — in the live UI the chevron lives in its own widget adjacent to the TextArea, not inside the box.

```
NORMAL · NATURAL · NONE                   (idle, no history match)
┌─────────────────────────────────────────────────────────────┐
│ ❯ Type a message @file /cmd !shell                          │
└─────────────────────────────────────────────────────────────┘
   (no legend bar)

NORMAL · NATURAL · GHOST                  (history suggestion offered)
┌─────────────────────────────────────────────────────────────┐
│ ❯ git stat·us --short                                       │
└─────────────────────────────────────────────────────────────┘
  suggestion  ·  Tab=accept  ·  →=accept                        ← legend (one-shot)

NORMAL · SLASH · OVERLAY                  (slash-command picker open)
   ┌───────────────────────┐ ┌───────────────────┐
   │ /commit               │ │ git commit helper │  ← SlashDescPanel
   │ /clear   ▮            │ │ Clear screen      │
   │ /diff                 │ └───────────────────┘
   └───────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│ ⊞ /cl_                                                      │
└─────────────────────────────────────────────────────────────┘
  @file  ·  Tab=accept  ·  Enter=accept  ·  Esc=cancel           ← legend

BASH · NATURAL · NONE                     (shell passthrough)
┌─────────────────────────────────────────────────────────────┐
│ $ !ls -la                                                   │
└─────────────────────────────────────────────────────────────┘
  shell mode · Tab=path · Enter=run · Ctrl+C=clear              ← legend

REV_SEARCH · NATURAL · NONE               (Ctrl+R recall)
┌─────────────────────────────────────────────────────────────┐
│ ⟲ reverse-i-search: dif_                                    │
└─────────────────────────────────────────────────────────────┘
  Ctrl+G abort · Esc accept · ↑↓ cycle                          ← legend

LOCKED · — · NONE                         (agent streaming)
┌─────────────────────────────────────────────────────────────┐
│ ⊘ running…  ·  Ctrl+C to interrupt                            │
└─────────────────────────────────────────────────────────────┘
  running…  ·  Ctrl+C to interrupt                                ← legend
```

These mocks are not skinned; every shipped skin substitutes hue, never structure or glyph.

---

## MODE axis — regimes the composer is behind

`InputMode` is defined in `hermes_cli/tui/input/_mode.py`. Resolver: `HermesInput._compute_mode()` in `widget.py`. It is the *single* place precedence is decided, and the precedence is **load-bearing**:

```
LOCKED  >  REV_SEARCH  >  BASH  >  COMPLETION  >  NORMAL
```

Reordering breaks the chevron/legend/placeholder display, because each subscriber reads `_mode` and assumes the higher-precedence regime has already been resolved out.

The "Cause" column names what *makes the gate true*; the "Resolver gate" column names the boolean predicate `_compute_mode()` actually reads. Confusing the two is the §2 drift in nutshell. Legend and placeholder string literals in this table are byte-exact with code (`InputLegendBar.LEGENDS` and `_refresh_placeholder()` respectively).

| MODE | Cause (user/service action) | Resolver gate (`_compute_mode()`) | Chevron | Legend (canonical from `LEGENDS`) | Placeholder source | Notes |
|------|-----------------------------|-----------------------------------|---------|-----------------------------------|--------------------|-------|
| `NORMAL` | default | (no other gate true) | `❯` (accent) | (hidden, except A12 ghost legend) | `_idle_placeholder` | KIND axis still active; ghost may show |
| `BASH` | text after `lstrip()` begins with `!` (toggles `--bash-mode` class via `on_text_area_changed`) | `self.has_class("--bash-mode")` | `$` | `shell mode  ·  Tab=path  ·  Enter=run  ·  Ctrl+C=clear` | `! shell mode  ·  Enter runs  ·  Ctrl+C clear` | KIND restricted: SKILL_INVOKE suppressed at `detect_context` level; SLASH_COMMAND not explicitly suppressed but structurally unreachable (drift §8 names this fragility) |
| `REV_SEARCH` | `Ctrl+R` action sets `_rev_mode = True` | `getattr(self, "_rev_mode", False)` | `⟲` | `rev-search  ·  ↑↓=cycle  ·  Esc=accept  ·  Ctrl+G=abort` | `reverse-i-search: <query>_` | Ghost cleared; overlay disabled; saves draft to `_rev_saved_value` |
| `COMPLETION` | `_show_completion_overlay()` mounts overlay with `--visible` | `self._completion_overlay_visible()` is true | `⊞` | `@file  ·  Tab=accept  ·  Enter=accept  ·  Esc=cancel` | (unchanged from underlying mode) | Asymmetric: this is the only mode where the placeholder does **not** change — see drift §1 |
| `LOCKED` | service-side caller sets `self.disabled = True` (typically around streaming) | `self.disabled` | `⊘` | `running…  ·  Ctrl+C to interrupt` | `running…  ·  Ctrl+C to interrupt` | `_set_input_locked(True)` does **not** flip `disabled` — only adds `--locked` CSS + locked placeholder. The setter and the MODE resolver are decoupled (see drift §2). |

**Subscribers to MODE:**
- `_sync_chevron_to_mode()` — reads `_CHEVRON_GLYPHS[mode]` and `_CHEVRON_VAR[mode]`, updates `#input-chevron` Label.
- `_sync_legend_to_mode()` — looks up `key = _LEGEND_KEY[mode]` (host-side) and calls `InputLegendBar.show_legend(key)`. Legend literals are owned by `InputLegendBar.LEGENDS`, not by any host-side string table.
- `_refresh_placeholder()` — placeholder priority chain: LOCKED > BASH > ERROR (orthogonal, see §ASSIST) > IDLE.
- CSS classes — `--bash-mode`, `--locked` toggle on/off the host widget.

**Mode is reactive but not history-tracked.** There is no transition log; debugging mode oscillation requires logging in `watch__mode()`.

---

## KIND axis — what the user is typing

`KIND` is the completion context: a structural classification of the current text + cursor position. It is computed by `detect_context()` (module-level in `completion_context.py`) and stored on `HermesInput._current_trigger: CompletionTrigger` (always populated; the initial value is a `CompletionTrigger(NONE, "", 0)` placeholder).

| KIND (enum value) | Pattern | Dispatch | Overlay class |
|---|---|---|---|
| `NONE` | pre-detect sentinel; first keystroke replaces it | (none) | — |
| `NATURAL` | none of the sigil patterns below | no overlay; ghost text may apply | — |
| `SLASH_COMMAND` | `^/[\w-]*$` (entire value; fragment = `value[1:]` — no capture group, sliced by hand) at pos 0 (early branch in `_update_autocomplete`, single-line only — `'\n' not in value` guard). The branch does not read `_bash_mode`; suppression in BASH is coincidental to value-shape (drift §8). REV_SEARCH and LOCKED suppress detection upstream by gating `_update_autocomplete` itself. | `_show_slash_completions(fragment)` — fuzzy rank against `_slash_commands` | `--slash-only` (hides preview, shows `SlashDescPanel`) |
| `SLASH_SUBCOMMAND` | `^/([\w-]+)\s+([\w-]*)$` | `_show_subcommand_completions()` — per-command subcommand list | `--slash-only` |
| `PATH_REF` | `@<fragment>` at token boundary | `_show_path_completions(fragment)` — `PathSearchProvider.search()` (debounced 120ms, threaded). Fragment's leading sigil is recovered from `_current_trigger.start`. | (no class) |
| `PLAIN_PATH_REF` | `./`, `../`, `~/` at token start | same path provider | same |
| `ABSOLUTE_PATH_REF` | `/abs/path` after whitespace (not slash-cmd) | same | same |
| `SKILL_INVOKE` | `$<fragment>` (suppressed in BASH mode at `detect_context` level) | `app._open_skill_picker(seed_filter=fragment, trigger_source='prefix')` — app-level picker, **not** inline overlay | n/a (different surface) |

**Re-entry guard.** `_AutocompleteMixin._update_autocomplete()` returns early if `new_trigger == self._current_trigger`. The comment in code calls it out explicitly: *"prevents `watch_items` → refresh → `watch_value` re-entry loop"*. This is **not** a debounce (the debounce is the separate 120ms timer on the path branch); it only suppresses redundant dispatch when the same trigger is re-derived from the same text+cursor. Each typed/deleted character produces a different fragment, so deletion-and-retype walks through a sequence of distinct triggers and refires dispatch normally.

**KIND is partially gated by MODE.**
- In `BASH`: `SKILL_INVOKE` is suppressed at the `detect_context(bash_mode=True)` level. `SLASH_COMMAND` is **not** suppressed — the early-branch matcher in `_update_autocomplete` runs unconditionally, so a leading `/cmd` typed after `!` will still mount the slash overlay. PATH kinds remain eligible. (See drift §8 — this is half-deliberate, half-historical.)
- In `REV_SEARCH` and `LOCKED`: `_update_autocomplete` early-returns; no detection happens.
- In `NORMAL` and `COMPLETION`: all kinds are eligible.

---

## ASSIST axis — what the composer offers back

ASSIST is the umbrella for the four feedback channels. It is the only axis with no single source field today; it is the *union* of:

| ASSIST | Surface | Source state | Mutually exclusive with |
|--------|---------|--------------|-------------------------|
| `NONE` | nothing | (default) | — |
| `GHOST` | trailing dim suffix in TextArea | `self.suggestion` non-empty (ad-hoc str attribute set on the `HermesInput` instance by `_HistoryMixin`; not a Textual `TextArea` field — see drift §11) | OVERLAY, PICKER (cleared when those open) |
| `OVERLAY` | floating `CompletionOverlay` above input | `_completion_overlay_visible()` predicate (reads `--visible` CSS class on `CompletionOverlay`) | GHOST, PICKER |
| `PICKER` | full-screen skill picker | `SkillPickerOverlay` mounted in app | GHOST, OVERLAY |
| `HINT_FLASH` | transient row via `app.feedback.flash()` | no observable predicate — fire-and-forget through the feedback service queue (composer cannot answer "is HINT_FLASH active?"); see drift §4 | (overlays others) |
| `ERROR_FLASH` | placeholder takeover (with leading `⚠` glyph) | `error_state: str \| None` reactive | overridden by BASH placeholder; LOCKED overrides both (priority chain in `_refresh_placeholder()` is `disabled > --bash-mode > error_state > idle`) |

**Mutual exclusion is enforced at write-time, not by a resolver.** Opening the overlay clears `suggestion`; entering REV_SEARCH clears `suggestion`. The `SKILL_INVOKE` branch opens the picker but does **not** explicitly call `_hide_completion_overlay`, relying on the prior `_show_path_completions` / `_show_slash_completions` not having run for a `$`-prefixed fragment — coexistence is structurally improbable rather than guarded (see drift §1b). There is no central `assist_resolver()` that picks one and suppresses the rest. This is the largest gap the frame exposes — see drift §4.

**GHOST eligibility rules** (`_HistoryMixin.update_suggestion()`):

1. Text is ≥ 2 chars.
2. Cursor is at end of last line.
3. A history entry starts with current text (single-line) or its last-line suffix matches a history entry's last line (multi-line).
4. The candidate is not equal to current text (single-line) or to the current last line (multi-line) — prevents zero-length ghost.

For multi-line input, only the last line's suffix is suggested; suggestion clears if cursor moves off the last line.

**A12 one-shot legend gate.** `_ghost_legend_shown` is set the first time GHOST is offered in a session and never re-flips. Intent: keep the legend bar quiet after the user has learned the affordance. Side effect: clearing all history does not re-arm the legend — see drift §5.

---

## Channels — how the cube reaches the user

Same four channels as the tool-block frame. Every signal must be carried in **at least two** channels (the redundancy contract):

### Visual channel
- Chevron color (CSS var per MODE).
- Host CSS classes currently in use: `--bash-mode`, `--locked`. (REV_SEARCH has no class today — drift §6.)
- `CompletionOverlay --visible`, `--slash-only`, `--narrow`.
- `VirtualCompletionList` shimmer rows during PathSearchProvider walk.
- Border/background remain skin-driven; no per-mode overrides.

### Glyph channel
- Chevron glyph (`❯ $ ⟲ ⊞ ⊘`) — primary MODE indicator.
- Sigil prefixes the user types (`/`, `@`, `./`, `~/`, `$`, `!`) — primary KIND indicator.
- Ghost text rendered as TextArea suffix in muted style — primary GHOST indicator.

### Motion channel
- Input height resize (Ctrl+Shift+Up/Down, 1–6 rows) flashes "Input height: N" via `app._flash_hint()`.
- Hint flashes (paste size, unknown slash, completion accept nudge) appear as transient rows above input.
- `VirtualCompletionList` shimmer animation while PathSearchProvider is searching.
- No animation on submit, clear, or mode change. (Deliberate — see Design voice.)

### A11y channel
- Placeholder text is the dominant a11y surface; it carries MODE and ERROR_FLASH state in plain words.
- Legend bar text is read by screen readers when shown.
- ARIA roles on overlay/list/picker are inherited from Textual primitives; no custom labels today (drift §16).

**Redundancy table** (signal → channels):

Each row encodes one signal; cells in *italics* indicate a downstream signal carried by another axis (e.g. SLASH triggers OVERLAY, OVERLAY flips MODE → COMPLETION, which flips the chevron — the chevron in that row is downstream, not native to KIND).

| Signal | Visual | Glyph | Motion | A11y |
|--------|:------:|:-----:|:------:|:----:|
| MODE = LOCKED | --locked CSS | ⊘ chevron | — | placeholder text |
| MODE = BASH | --bash-mode CSS | $ chevron | — | placeholder text |
| MODE = REV_SEARCH | chevron color only (no host class — drift §6) | ⟲ chevron | — | placeholder text |
| KIND = SLASH_COMMAND | overlay --visible | `/` sigil | — | legend bar (*via MODE = COMPLETION*) |
| KIND = PATH_* | overlay --visible | `@` / `./` / `~/` sigil | shimmer rows | legend bar (*via MODE = COMPLETION*) |
| ASSIST = GHOST | dim suffix | ghost text glyphs | — | A12 legend (one-shot) |
| ASSIST = OVERLAY | overlay `--visible` | (overlay frame) | mount/unmount | legend bar (*via MODE = COMPLETION*) |
| ASSIST = PICKER | full-screen mount | (picker frame + sigil `$`) | mount/unmount | (Textual default ARIA — drift §16) |
| ASSIST = HINT_FLASH | (transient row visual) | flash glyph | flash mount/unmount | (text content) |
| ASSIST = ERROR_FLASH | (none) | leading `⚠` in placeholder | — | placeholder text |

ERROR_FLASH and REV_SEARCH each currently carry on **only one** channel (a11y placeholder, glyph chevron). Both are redundancy-contract violations — see drift §6, §7.

---

## Cross-surface couplings

The composer is not self-contained; it routes through the app for several capabilities. These couplings are the boundary of this concept — touching them means revising this doc *and* whatever else owns them.

| Coupling | Direction | Mechanism |
|----------|-----------|-----------|
| `PathSearchProvider` walk results | provider → app → input | `Batch` message, sibling-to-sibling via `HermesApp.on_path_search_provider_batch` (see `reference_path_search_routing.md`) |
| Skill picker open/close | input → app | `app._open_skill_picker(seed_filter, trigger_source)` |
| Submission dispatch | input → app → services | `HermesInput.Submitted` → `_svc_keys.dispatch_input_submitted()` |
| Feedback flashes | input → app | `app.feedback.flash()` / `app._flash_hint()` |
| History file I/O | input → disk | `~/.hermes/.hermes_history`, append via `safe_write_file()`, deduped on save |
| Lock from streaming | services → app → input | `app` calls `input._set_input_locked(True/False)` around streaming. Note the gap: this sets CSS only; if MODE = LOCKED is required, the caller must also flip `input.disabled` (drift §2). |
| Drag-drop file paths | terminal → input | `parse_dragged_file_paste()` → `FilesDropped` message |

**TextArea inheritance.** `HermesInput` extends Textual's `TextArea`. This gives undo/redo (50 checkpoints), multi-line, paste handling, and the `suggestion` field for ghost text. Most TextArea API is used as-is; the composer overrides `_on_paste`, `action_cursor_right`, and key bindings.

---

## Contracts that touch other concepts

The composer is one of several surfaces with cross-cutting rules. Where this doc and another concept overlap, the **other** concept owns the rule and this doc cites it.

- **Lock/streaming contract.** When the agent is streaming, `MODE = LOCKED`. This is owned by the *services* layer (`services/tools.py` and friends), not by the composer. The composer only renders the lock; it does not decide it. See `docs/concept.md` §"PHASE — when in life" for the upstream lifecycle.
- **Hint flash queue.** `app.feedback.flash()` is the same service the tool-block subsystem uses. Composer hints share the queue; double-flashes are deduplicated by the feedback service, not by `HermesInput`.
- **Focus ring on overlay.** `CompletionOverlay` and any future input-adjacent overlays MUST follow the F7 focus-ring pattern (`.--focus-highlight`) once UX Audit F is implemented. Today the overlay does not have a focus ring distinct from the list-row highlight.
- **Skin tokens.** Chevron colors, ghost-text dim, legend muted color all resolve through the active skin (`SkinColors` / `DESIGN.md`). New tokens specific to the composer must follow the A4 opacity tier rule (UX Audit A).

---

## Known drift / gotchas

These are not bugs — they are the gaps the frame exposes. Each is a candidate for a future spec. Owner tags identify which subsystem must own the fix.

1. **COMPLETION mode does not change the placeholder.** Every other mode rewrites the placeholder; COMPLETION leaves the underlying mode's placeholder visible while the overlay floats above. Structural cause: `_refresh_placeholder()` does not consult `_completion_overlay_visible()`. Closing the gap requires (a) inserting a new tier into the priority chain (between BASH and ERROR, or between ERROR and IDLE — design choice) **and** (b) a way to read overlay state from the placeholder path. The hot-render path should not call `query_one(CompletionOverlay)`; the proper fix is a `_completion_overlay_active` reactive mirror on `HermesInput` that the predicate already maintains. Not just a literal-string change.  *Owner: composer.*

   **1b.** Related: opening the skill picker (`PICKER` ASSIST) on a `$`-fragment does not explicitly dismiss an inline overlay if one is somehow still mounted. Coexistence is structurally improbable but not guarded.  *Owner: composer.*

2. **`--locked` CSS class is decoupled from `disabled` (and from MODE).** `_set_input_locked()` adds the `--locked` class and re-runs `_refresh_placeholder()`, but the locked-text branch only fires when `disabled=True` — and `_set_input_locked` does **not** flip `self.disabled`. Net effect: the placeholder resolves to whichever lower-priority tier (BASH/error/idle) was already active. `_compute_mode()` resolves `LOCKED` solely from `self.disabled`. Therefore: a caller using `_set_input_locked(True)` *without* also setting `disabled` produces a "visually locked, mode-wise NORMAL" composite. The intent of the split (allow CSS-only lock without trapping focus?) is undocumented.  *Owner: composer + services (caller contract).*

3. *(Removed in v0.2 — was misdescribed; the equality guard does not block delete-and-retype because intermediate keystrokes change the trigger.)*

4. **ASSIST has no central resolver.** `GHOST`, `OVERLAY`, `PICKER`, `HINT_FLASH`, `ERROR_FLASH` are mutually exclusive (mostly) but the exclusion is enforced at each write site. A central `_resolve_assist()` would replace several inline guards and make 1b structurally impossible.  *Owner: composer.*

5. **A12 ghost-legend gate is one-shot per session.** Once shown, never shown again. Clearing history does not re-arm. Consider tying the gate to "first ghost in *this* session has been seen" with explicit reset.  *Owner: composer.*

6. **REV_SEARCH host-widget visual is empty; chevron color is the only visual signal beyond glyph.** No `--rev-search` CSS class on the host, no border change, no motion. The chevron *glyph* is `⟲` (glyph channel) and the chevron *color* is `$chevron-rev-search` (visual channel, but isolated to the chevron Label). The host TextArea looks identical to NORMAL. Redundancy is thin; failure mode = high in low-vision configurations. Adding a `--rev-search` host class with a border-side or background tint would close the gap.  *Owner: composer + skin (token).*

7. **ERROR_FLASH carries on a11y placeholder + a single inline `⚠` glyph; no border, no motion, and it is suppressed under BASH or LOCKED.** The leading `⚠` is one glyph signal but it does not survive when BASH or LOCKED takes over the placeholder, so the redundancy gap is mode-conditional. A misclick on Esc clears it silently regardless.  *Owner: composer + feedback service.*

8. **BASH suppression of SLASH is coincidental, not explicit.** The early SLASH branch in `_update_autocomplete` checks `self.value.startswith("/")` (no lstrip). BASH is gated on `self.text.lstrip().startswith("!")`. The two predicates cannot both hold on the same value: SLASH requires the literal first byte to be `/`, while BASH allows leading whitespace before `!` and the `!` itself survives `lstrip()`. So in practice the slash overlay does not open in BASH today, and the comment above the early SLASH branch in `_autocomplete.py` is effectively correct. The fragility is that suppression depends on *value shape*, not on a *bash-mode predicate*: any future change loosening either gate (whitespace tolerance on SLASH, paste handling that prepends, alternate sigils) would reopen the gap silently. Fix is structural: add an explicit `if self._mode is InputMode.BASH: return` at the top of the early branch so suppression is in code, not in coincidence.  *Owner: composer.*

9. **Bash mode triggers on any leading `!`.** Pasting "!important note" silently flips to BASH mode. No confirmation, no escape hatch beyond Ctrl+C.  *Owner: composer.*

10. **History dedup is in-memory only; the on-disk file accumulates duplicates.** `_save_to_history()` in `_history.py` removes prior identical entries from the in-memory `self._history` list via `==` equality and **appends** the new line to `~/.hermes/.hermes_history` (no rewrite). Duplicates are collapsed only at next `_load_history()`. Comparison is content-exact, so trailing whitespace, case, or punctuation differences create distinct slots (e.g. `/help` and `/help ` both persist on disk).  *Owner: composer (`_history.py`).*

11. **`suggestion` field is an ad-hoc dynamic attribute.** Set with `# type: ignore[attr-defined]` at every write site; not declared on `HermesInput` or any base class. Works, but fragile under typing tools and inheritance changes.  *Owner: composer.*

12. **Rev-search placeholder is set once, not on every keystroke.** Subsequent ↑/↓ during rev-search update `_rev_query` but the placeholder is not re-rendered until exit.  *Owner: composer.*

13. **Mid-word completion accept blocked.** `action_accept_autocomplete()` requires cursor at end-of-value; otherwise it flashes "move cursor to end to accept" and dismisses. No structural reason for the restriction.  *Owner: composer.*

14. **Paste handler does not maintain focus explicitly.** Large pastes that trigger flash hints can drift focus to the hint surface in some terminals.  *Owner: composer + feedback service.*

15. **Draft stash leaks across rapid mode toggles.** `_draft_stash` is cleared on `action_submit()` and `_exit_rev_mode()` only; entering and exiting rev-search without typing leaves the stash populated.  *Owner: composer.*

16. **No custom ARIA on overlay/list/picker.** Inherited Textual primitives may be sufficient for screen readers, but the doc cannot make that claim without an audit. Either confirm sufficiency and downgrade to "intentional", or write a labels pass.  *Owner: composer.*

---

## Glossary

- **Composer** — canonical name for the surface this doc describes. Implementation class: `HermesInput` (extends Textual `TextArea`). Doc uses "composer" throughout; "input" / "input surface" / "prompt-entry" are not synonyms but informal references.
- **Chevron** — the leading single-glyph marker (`#input-chevron` Label) that primarily encodes MODE.
- **Ghost text** — fish-shell-style trailing suffix offered by `_HistoryMixin.update_suggestion()`, accepted with Tab or `→`. Stored on the ad-hoc `self.suggestion` attribute.
- **Legend bar** — single-row affordance strip below the input (`InputLegendBar`), driven by MODE. Canonical strings live in `InputLegendBar.LEGENDS`.
- **CompletionTrigger** — frozen dataclass in `completion_context.py`. Fields: `context: CompletionContext`, `fragment: str`, `start: int`, `parent_command: str`. The initial `NONE`-context placeholder is constructed in `HermesInput.__init__`; subsequent values come from `detect_context()` (module-level function), which itself never returns `NONE`.
- **CompletionContext** — enum in `completion_context.py`. Values listed in this doc in **semantic-group order**: `NONE, NATURAL, SLASH_COMMAND, SLASH_SUBCOMMAND, PATH_REF, PLAIN_PATH_REF, ABSOLUTE_PATH_REF, SKILL_INVOKE`. The source file declares them in numeric-enum order (`NONE, SLASH_COMMAND, PATH_REF, NATURAL, PLAIN_PATH_REF, ABSOLUTE_PATH_REF, SLASH_SUBCOMMAND, SKILL_INVOKE`); both orders are valid, but the doc uses semantic order throughout for readability.
- **Slash-only mode** — `CompletionOverlay` CSS class that hides the preview pane and shows the `SlashDescPanel` instead.
- **A12 gate** — the one-shot ghost-legend show flag (`_ghost_legend_shown`).
- **Lock** — composer state currently CSS-only, set by `_set_input_locked()` (toggles `--locked` class + locked placeholder). Decoupled from `self.disabled` and therefore from MODE = LOCKED — this decoupling is treated as drift, not contract (see drift §2).
- **`error_state`** — reactive `str | None` on `HermesInput`. Drives ERROR_FLASH placeholder takeover. Cleared by Esc.
- **`_rev_mode`** — boolean instance flag set by `Ctrl+R` and cleared on accept/abort. Read by `_compute_mode()` to resolve `MODE = REV_SEARCH`.

---

## Changelog

Each version-bump entry must list: axis additions/changes, drift items added or closed, code references touched, and any inter-concept boundary changes.

- **v1.0 (2026-04-28)** — review pass 7 (second consecutive gate-met pass: 0 HIGH / 0 MED / 2 LOW). Applied both LOWs (line-number reference replaced with anchor citation; SLASH_COMMAND regex pattern shape clarified — no capture group, fragment sliced via `value[1:]`). Status flipped DRAFT → APPROVED.
- **v0.7 (2026-04-28)** — review pass 6 fixes (gate met). BASH cause now correctly says "after `lstrip()`"; BASH placeholder string made byte-exact with code (double-spaces around `·`); table preamble pins both legend AND placeholder strings as byte-exact. Drift §8 reformulated to avoid the misleading "after lstrip" framing — now names the asymmetry explicitly. Drift §2 description corrected to reflect that `_set_input_locked` calls `_refresh_placeholder()` but the locked-text branch is gated on `disabled` (which the setter does not flip).
- **v0.6 (2026-04-28)** — review pass 5 fixes. Drift §8 rewritten: BASH/SLASH suppression is coincidental (value-shape predicates are mutually exclusive), not "implementation contradicts comment". Names the fragility (predicate independence) and proposes the explicit-gate fix. KIND SLASH row + BASH MODE row updated to match. ASSIST table HINT_FLASH source state explicitly named as "no observable predicate".
- **v0.5 (2026-04-28)** — review pass 4 fixes. Replaced phantom `_LEGEND_TEXT[mode]` with actual `_LEGEND_KEY[mode] → InputLegendBar.show_legend(key)` flow. Drift §1 expanded to require a `_completion_overlay_active` reactive mirror (avoids hot-path query). Drift §6 + redundancy table credit chevron color as visual signal; gap is "no host-widget visual" not "no visual". KIND SLASH row narrowed: "regardless of `_bash_mode`" not "regardless of MODE" — REV_SEARCH/LOCKED suppress upstream. COMPLETION mock legend made byte-exact with `LEGENDS["completion"]`.
- **v0.4 (2026-04-28)** — review pass 3 fixes. Mock GHOST legend made byte-exact (`suggestion · Tab=accept · →=accept`). Added preamble note that mock chevrons are schematic (live UI uses sibling Label widget). Drift §10 corrected to acknowledge in-memory-only dedup with file-level accumulation. ASSIST = ERROR_FLASH placeholder priority inverted (BASH wins, LOCKED wins over both); redundancy table + drift §7 updated to credit the leading `⚠` glyph and note mode-conditional suppression. Drift §8 now cites the contradicting `_autocomplete.py` docstring. Drift §1 names structural fix (priority-chain insertion). KIND table: SLASH single-line guard noted; handler renamed to `on_text_area_changed` (no underscore). OVERLAY source-state cites `_completion_overlay_visible()` predicate. Glossary: `CompletionTrigger` clarified — `detect_context()` never returns NONE.
- **v0.3 (2026-04-28)** — review pass 2 fixes. Split MODE table "Trigger" into "Cause / Resolver gate" columns to disentangle user action from `_compute_mode` predicate. Made all legend literals byte-exact with `InputLegendBar.LEGENDS` (double-spaces around `·`). Removed phantom `--rev-search` CSS class from channel listing (lives only as drift §6). Fixed GHOST eligibility rule 4 wording for multi-line case. Added rows for ASSIST = OVERLAY / PICKER / HINT_FLASH to redundancy table; clarified KIND chevron-via-MODE downstream signal. Added drift §16 (no custom ARIA). Cited `_save_to_history()` in drift §10. Pinned semantic-group enum ordering and noted it in glossary. Corrected lock-from-streaming coupling direction (`services → app → input`).
- **v0.2 (2026-04-28)** — review pass 1 fixes. Corrected MODE = LOCKED resolver gate (`self.disabled`, not `_set_input_locked`). Replaced abstract KIND names with literal `CompletionContext` enum values (added `NONE`). Replaced legend literals with canonical strings from `InputLegendBar.LEGENDS`. Fixed `CompletionTrigger.context` field name and `detect_context()` function name throughout. Dropped phantom `prefix='@'` kwarg from `_show_path_completions` reference. Removed misdescribed drift §3; added §1b (PICKER/OVERLAY coexistence), §8 (BASH does not suppress SLASH), §11 (suggestion field is ad-hoc). Added "UX intent per axis" section. Added owner tags to all drift items. Added `error_state`, `_rev_mode`, `Composer` to glossary. Tightened ASSIST ↔ TextArea language.
- **v0.1 (2026-04-28)** — initial draft. Frame named: MODE × KIND × ASSIST. 13 drift items catalogued. Status: DRAFT, awaiting first review pass.
