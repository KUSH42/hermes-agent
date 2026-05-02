# TUI Deep Audit 2026-05-02 — Spec Index

Companion to `/home/xush/.hermes/tui_deep_audit_2026-05-02.md`. Nine specs drafted to address all 97 audit findings + 12 composer-concept findings from re-audit. All `Status: DRAFT` pending review.

| Spec | File | Tests | Closes |
|---|---|---|---|
| **SPEC-WRK** Worker exception discipline | `spec_wrk_worker_exception_discipline.md` | 26 | APP-H1..H4, SVC-H1, SVC-H2, STREAM-MATH-WORKER, PACER-TICK-NO-EXC, ANIM-CLOCK-TICK-SWALLOW, ANIM-TICK-RENDER-NOLOG, CD-8 |
| **SPEC-CSS** Skin var diagnostic logging | `spec_css_skin_var_diagnostics.md` | 14 | SKIN-H1, SVC-H1, SVC-H2, STAT-M2, OVERLAY-CTOR-WATCH-SWALLOW, THEME-REFRESH-EXCEPT-TUPLE, SKIN-L1 |
| **SPEC-TBC** Tool block concept drift fix | `spec_tbc_concept_drift_fix.md` | 24 | CD-1..CD-5, IL-GAP-1, DEAD-1 |
| **SPEC-MOD** Modal arbiter | `spec_mod_modal_arbiter.md` | 22 | H3, H6, M3, M4, M12 |
| **SPEC-ASS** Composer ASSIST consolidation | `spec_ass_composer_assist_consolidation.md` | 30 | H1, H2, M6, M9, M11, CC-1..CC-12 |
| **SPEC-STR** Streaming hardening | `spec_str_streaming_hardening.md` | 28 | STREAM-FENCE-LEAK, -PARTIAL-DETACH, -FOOTNOTE-CAP, -PARTIAL-CSI-LOSS, -FENCE-FLUSH-CODE, -REASONING-RACE, STARTUP-BANNER-RACE, CONTENT-CLASSIFY-NO-TIMEOUT, PARTIAL-JSON-UNICODE-RECOVERY, STREAM-CITE-STATE, PROSE-DOUBLE-EMIT-DEBUG, CACHE-INVALIDATE-FOR-RESIZE, EXEC-CURSOR-TIMER-SWALLOW, TTE-CACHE-LOAD-SWALLOW |
| **SPEC-ANM** Animation reentrancy | `spec_anm_animation_safety.md` | 11 | ANIM-LAYER-REENTRANCY, ANIM-EXTERNAL-TRAIL-SCALES, PERF-RGB-CACHE-CAP |
| **SPEC-SVC** Service lifecycle hardening | `spec_svc_service_lifecycle_hardening.md` | 23 | SVC-M1..M3, APP-M1..M5, CONST-M1, SKIN-M1, SKIN-M2, STAT-M1, HEADLESS-L1, SVC-L1, STAT-L1, APP-L1, APP-L2 |
| **SPEC-TBM** Tool block MED cleanup | `spec_tbm_tool_block_med_cleanup.md` | 22 | CD-6..CD-11, EH-1, EH-2, PERF-1, LOW-1..LOW-5 |
| **TOTAL** | | **200** | **97 audit findings + 12 CC re-audit findings + 5 invariant gates added** |

## Cross-spec dependencies

```
SPEC-TBC → SPEC-TBM         (TBM-3 depends on TBC-6 user_override axis)
SPEC-WRK → IL-W1            (gate lands after all violators fixed)
SPEC-CSS → IL-S1            (gate lands after all violators fixed)
SPEC-MOD → IL-M1            (gate lands after all overlays migrated)
SPEC-ANM → IL-A1            (gate lands after module-level state cleaned)
SPEC-ASS → composer-concept.md drift §1, §6, §10, §11 closure
```

## New invariant gates added (5)

| Gate | Spec | Lints |
|---|---|---|
| IL-W1 | SPEC-WRK | `@work` decorations wrap body in try/except |
| IL-S1 | SPEC-CSS | `get_css_variables()` callsites log on exception |
| IL-M1 | SPEC-MOD | `--modal` class only added via `ModalOverlayMixin` |
| IL-A1 | SPEC-ANM | No module-level mutable buffers in animation files |
| (extends IL-7) | SPEC-TBC + SPEC-TBM | `user_override` axis paired with header refresh; chip render-form ≤ 18 chars |

## Convergence impact

After **SPEC-TBC + SPEC-TBM** land:
- Criterion 1 (invariant gates green): ✅ extended IL-7 still passes.
- Criterion 2 (concept doc unchanged): ✅ only changelog entries added (bug-fix-class).
- Criterion 3 (targeted tests green per PR): ✅ expected.
- Criterion 4 (≤3 MED, 0 HIGH): **flips green** if fresh re-audit confirms.

Convergence plan can close after 14 consecutive days of green CI.

## Priority

**P0 — do first (highest user-impact, time-pressured):**
- **SPEC-WRK** — silent worker death today causes "output stops forever" / "bash stuck" bugs. Real prod risk.
- **SPEC-TBC** — closes 6 HIGH concept drifts; flips convergence criterion 4. Time-pressure: concept v3.6 freeze ends 2026-05-11.

**P1 — high-impact UX bugs users hit:**
- **SPEC-ASS** — modal+ASSIST wedging means real users get stuck composers. Composer-concept.md has no freeze.
- **SPEC-STR** — silent data loss (orphan CSI, footnote cap, citations) + TTE startup race. Mostly invisible until it bites.
- **SPEC-MOD** — modal stacking H3/H6 are real focus-trap bugs.

**P2 — hardening, less visible:**
- **SPEC-CSS** — skin diagnostics; only matters when something already broke.
- **SPEC-SVC** — lifecycle/teardown; mostly affects exit and session-switch paths.
- **SPEC-ANM** — reentrancy is latent, not currently triggering for most users.

**P3 — cleanup:**
- **SPEC-TBM** — the MED tail; needed for convergence but no urgency once HIGHs are gone.

## Parallelism

**Hard dependencies (must be sequential):**
- **TBM-3 depends on TBC-6** (needs `AxisName.user_override`). TBM after TBC.
- **All `IL-*` invariant gates** must land *after* their corresponding spec's violator fixes — gate would otherwise red-flag existing code.

**Soft conflicts (can run parallel but expect merge churn):**
- **WRK + STR** — both touch `response_flow.py` (`_flush_math_block`, `CharacterPacer`). Light, but coordinate.
- **CSS + SVC** — both touch `services/theme.py`. Different functions, but same file.
- **CSS + ANM** — both touch `drawbraille_overlay.py` watchers. Pick one to land first.
- **ASS + MOD** — both touch `SkillPickerOverlay`. **Land MOD first**, then ASS rebases on `ModalOverlayMixin`.

**Cleanly parallel (no overlap):** WRK ‖ TBC ‖ ASS ‖ STR ‖ ANM ‖ SVC touch mostly disjoint files.

## Recommended PR waves

```
Wave 1 (parallel, ~3 PRs):     WRK     CSS     SVC
                                 ↓               ↓
Wave 2 (parallel, ~4 PRs):     TBC     STR     ANM     MOD
                                 ↓                       ↓
Wave 3 (sequential):           TBM ←─────────────── ASS
```

- **Wave 1** unblocks invariant gates and removes the silent-failure floor.
- **Wave 2** fans out across surfaces. TBC must precede TBM; MOD must precede ASS.
- **Wave 3** finishes convergence (TBM) and composer reactive consolidation (ASS rebased on the new mixin).

**Single-developer order:** WRK → TBC → ASS → STR → MOD → CSS → SVC → ANM → TBM. WRK + TBC first delivers highest value fastest.

**2 developers:** pair WRK+CSS on one branch, TBC+TBM on another (same owner since they share concept doc edits).

Total estimated work: ~200 tests, 9 PRs. Each PR is under the 35-test split criterion in `.claude/CLAUDE.md` (SPEC-ASS at 30 and SPEC-STR at 28 are within bounds; split before approval if either grows past 35 during review).

## Status

All 9 specs at `Status: DRAFT`. Per `.claude/CLAUDE.md` workflow: run a fresh reviewer on each, fix HIGH→MED→LOW, transition to APPROVED, then implement.
