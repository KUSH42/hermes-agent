# Live Audit Guide — Deep TUI E2E + Log Triage

How to drive the real `HermesApp` end-to-end via Textual's `Pilot`, capture debug logs and keystroke JSONL, triage for inconsistencies, and seed replayable e2e tests. This is the procedure used for the 2026-04-28 live audit.

> When to use: open-ended UX/correctness audit, regression hunt across many surfaces at once, or "is the lifecycle actually consistent in the wild?" sweeps. For a single-widget regression, prefer unit tests + targeted Pilot run from `references/patterns.md`.

---

## 1. Goals

A live audit produces two artifacts:

1. **Findings report** — tiered HIGH/MED/LOW issues with file:line, observed vs expected, log evidence. Lives in `~/.hermes/<date>-live-audit-findings.md`.
2. **e2e seed** — `~/.hermes/keystroke.jsonl` from the run, plus a replay plan describing how to turn the JSONL into a Pilot-driven regression suite.

Don't write spec-level fix designs in the findings — one-line sketches only. Specs come later.

### Why live audits earn their cost

The 2026-04-28 round-1 audit caught real bugs that the targeted regression suite missed — most notably H-1, an `AttributeError` swallowed by a bare `except Exception:` in `ExecuteCodeBlock.complete()` that leaked the duration timer on every successful tool close. Targeted unit tests didn't see it because the catch was silent and the code path didn't crash. The audit found it via DEBUG-log triage: the swallowed traceback was visible in `agent.log` even though no test ever flagged it.

Pattern: **silent swallows of real bugs are invisible to unit tests by definition**. Live + DEBUG-log triage is the cheapest way to surface them.

### Cost reference

Round-1 data point for planning: ~6 minutes wall, ~200K tokens, 44 tool calls, 9 flows × 16 checkpoints, 10 findings (4 HIGH / 4 MED / 2 LOW). Use this as a sanity bound — significantly more than 10× either dimension means the audit is doing too much (spec work, code-fix attempts) or the harness is fighting the agent.

---

## 2. Pre-flight blockers (read first)

### 2.1 `HermesApp.run_test()` VarSpec crash — sometimes

Historical reports say `HermesApp.run_test()` raises `StylesheetError: 'VarSpec' object has no attribute 'splitlines'` on `feat/textual-migration` (pre-existing TCSS parsing bug). **Empirically the 2026-04-28 round-1 live audit booted `HermesApp.run_test()` cleanly with no VarSpec crash** — the issue is intermittent or already mitigated for the cold-mount path.

**Procedure**: try the raw `HermesApp().run_test()` path first with a bare `MagicMock` CLI. If it boots, proceed. If it crashes, fall back to a workaround:

- **(A) Bypass-stylesheet harness**: subclass `HermesApp` and override `CSS` / `CSS_PATH` to a minimal stylesheet for the audit run. Lose theming fidelity, keep behavior. Best for behavior audits.
- **(B) Component-level Pilot**: use a minimal `App(App)` host with the specific widget(s) under test mounted. Loses cross-widget integration. Best for surface-bounded audits.
- **(C) Patch the VarSpec call site**: temporarily monkey-patch `textual.css.parse` to swallow the failing spec, run the audit, then restore. Fragile but preserves real CSS. Document the patch in the findings.

If the raw path crashes today, **fixing the VarSpec bug is a HIGH finding in itself** — file it and proceed with workaround (A).

### 2.2 Keystroke recorder gates — and a known coverage gap

`hermes_cli/tui/tool_panel/_keystroke_log.py` is opt-in:

- Enable: `HERMES_KEYSTROKE_LOG=1` **or** `~/.hermes/config.toml [debug] keystroke_log = true`
- **Suppressed by `HERMES_CI=1`** — never set CI mode for an audit run.
- Output: `~/.hermes/keystroke.jsonl` (5 MB rotation).
- Records: keypress (allowlisted set, see `_ALLOWLIST` in source), mouse click, mouse scroll, component interaction (density change, collapse, kind cycle).

Truncate the JSONL before the run so the seed is clean:
```bash
rm -f ~/.hermes/keystroke.jsonl
```

**Known gap (round-1 finding H-4)**: hooks live on `ToolPanel` only. App-level keystrokes (slash entry, F1 overlay, Ctrl-R history, Escape, density toggles when no block exists) are **not recorded** if no `ToolPanel` is mounted/focused at press time. If the audit's flows don't open at least one tool block, `keystroke.jsonl` will be empty even with the env var set — and the e2e seed for cold-start/overlay flows is then unrecoverable from this run. Plan flows accordingly: open one tool block early so app-level keys before/after still get captured under that block's context, **or** call this out as a "no app-level seed" caveat in the e2e plan. The proper fix (a hook at `KeyDispatchService.dispatch_key`) was filed as H-4; until it lands, treat the JSONL as intra-block-only.

### 2.3 Provider stub — `MagicMock` CLI is enough

Real LLM calls during an audit burn tokens and add nondeterminism. **Empirically a `MagicMock()` passed as the `cli` arg to `HermesApp` was sufficient for the round-1 audit** — no FakeLLM-class fixture needed. The mock absorbs every method call the app makes during cold start and during driver-orchestrated tool-call simulation. The audit drove tool calls directly via the `_svc_tools` API rather than going through the LLM path, so the mock never had to return realistic content.

If a flow you want to exercise actually requires LLM-shaped responses (reasoning panel, slow-LLM stalls, chunk-boundary edge cases), search for existing fixtures:
```bash
grep -rn "FakeLLM\|stub_llm\|StubProvider\|mock_provider" tests/tui/ tests/conftest.py
```
Otherwise note paths that "require live provider" in findings rather than skipping silently.

### 2.4 Full TUI suite is forbidden

Per project CLAUDE.md: **never** run `python -m pytest tests/tui/` (16+ min timeout). Run only the audit harness + targeted regression files.

---

## 3. Setup

### 3.1 Logging

Initialize file logging at DEBUG **before** importing/instantiating `HermesApp`:

```python
from hermes_logging import setup_logging

log_dir = setup_logging(mode="cli", log_level="DEBUG", force=True)
# log_dir resolves to ~/.hermes/logs/{agent.log,errors.log}
```

`setup_logging` is keyword-only; the kwarg is `log_level` (string, e.g. `"DEBUG"`/`"INFO"`), not `level` and not a `logging.*` int. `force=True` is required because the function short-circuits on second call. Truncate first:
```python
for f in (log_dir / "agent.log", log_dir / "errors.log"):
    if f.exists(): f.write_text("")
```

### 3.2 Artifact dir

```python
from pathlib import Path
ART = Path.home() / ".hermes" / f"audit-{date}-live"
ART.mkdir(exist_ok=True)
```
Save screenshots, log slices, and screen-tree snapshots here per flow.

### 3.3 Reuse the prior driver

Each audit's `driver.py` lives in its artifact dir. Round-1's at `/home/xush/.hermes/audit-2026-04-28-live/driver.py` is the canonical working baseline. **Read and reuse it on subsequent audits** — don't rebuild from scratch. Adapt by:

1. Copying to a new artifact dir (`audit-<date>-live-N/`).
2. Updating log/JSONL paths in setup.
3. Adding new flows for whatever shipped since the last audit's commit baseline (`git log --oneline <prev-base>..HEAD`).

This keeps the harness stable and makes round-N findings comparable to round-1.

### 3.4 Harness skeleton

```python
import asyncio, os
os.environ["HERMES_KEYSTROKE_LOG"] = "1"
os.environ.pop("HERMES_CI", None)

async def run_audit():
    setup_logging_at_debug()
    app = make_audit_app()  # workaround (A) — see 2.1
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await flow_cold_start(pilot)
        await flow_prompt_submit(pilot)
        await flow_tool_calls(pilot)
        await flow_density_kind_toggle(pilot)
        await flow_error_path(pilot)
        await flow_overlays(pilot)
        await flow_streaming_edge_cases(pilot)
        await flow_resize_focus_scroll(pilot)
        await flow_session_interrupt(pilot)

asyncio.run(run_audit())
```

Per-flow contract: enter from a known state, exercise, snapshot, return to known state. Use `await pilot.pause(0.05)` between actions to flush message queue.

---

## 4. Coverage matrix

A "deep" audit means breadth. Minimum surfaces:

| Surface | Flow | Snapshot |
|---|---|---|
| Cold start | App boot → input ready | initial layout, focus, status bar |
| Prompt submit | Type → submit → stream | reasoning panel, code-fence handling, stream reveal cadence |
| Tool calls (each renderer) | shell, read/write group, search, code, json, table, log, diff | PHASE×KIND×DENSITY transitions per axis bus |
| Density | `<` / `>` / `*` cycle, hero auto-clause | flash, completing chip, settled state |
| Kind override | `t` cycle (TEXT excluded), 150 ms debounce | `_user_forced` caption, no-op flash |
| Error path | failing tool → ERR cell | recovery actions, stderr tail, 2-chip header |
| Overlays | tool panel help, skill picker, completion list, plan panel, session bar, nameplate | open/close, focus restoration |
| Streaming | long prose, fast bursts, slow drips, fence open/close | orphan flush state, `[STREAM-*]` log cadence |
| Resize | shrink/grow horizontal + vertical | layout reflow, no event-loop stalls |
| Focus/scroll | Tab, Shift-Tab, j/k, page up/down | focus visibility, ›-prefix, gutter glyphs |
| Session interrupt | Ctrl-C / cancel mid-tool | cleanup, terminal-state writes |
| Skin reload | DESIGN.md hot-reload (if reachable) | TCSS revar, no double-mount |

Plus anything fresh in recent memory entries — check `~/.claude/projects/-home-xush--hermes-hermes-agent/memory/MEMORY.md` for `IMPLEMENTED <recent date>` entries; those are the surfaces most likely to leak.

---

## 5. Log triage

**Philosophy**: `errors.log` is the operator triage feed. Anything that lands there should be something an operator should react to. WARNING for known-handled races, dev-traces, or recovered conditions is **noise** that drowns real signal — downgrade to DEBUG. WARNING is the right level for: unhandled state, broken contracts, missing-but-required mounts, real failures with degraded behavior. The first three round-1 fixes (H-2, M-1, the post-present diagnostic in M-1) were all WARNING→DEBUG downgrades for this reason.

After the run, slice `~/.hermes/logs/agent.log` and check:

| Pattern | Look for | Significance |
|---|---|---|
| `[STREAM-BUF]` `[STREAM-CODE]` `[STREAM-FENCE]` `[STREAM-SEQ]` | sequence violations, fence reopened, buffer drained twice | orphan flush, broken state machine |
| Tracebacks in `agent.log` | any `Traceback` outside of expected error-path tests | exception slipping through `@work(thread=True)` |
| `errors.log` | any content | by definition worth surfacing |
| `[PERF]` warnings | budget exceeded labels | regression vs perf-instrumentation memory entries |
| `[AXIS]` ordering | `set_axis` after `complete_tool_call`, double-writes | violates axis-bus-first contract |
| Mount-order | `H6 retry`, `mount before compose` | mount-order race resurfacing |
| Bare swallow markers | `# NoMatches expected`, `# best-effort` | confirm the comment matches reality (project CLAUDE.md exception rules) |
| Nameplate idle | PULSE/SHIMMER/DECRYPT beat scheduling | two-phase timer correctness |

Cross-check against frozen invariants in `tests/tui/test_invariants.py` IL-1..IL-8 and `docs/concept.md` v3.6 (the doc is **frozen** — don't propose new clauses, only fix existing-clause violations).

---

## 6. Findings report shape

`~/.hermes/<date>-live-audit-findings.md`:

```markdown
**Status:** DRAFT
**Date:** 2026-04-28
**Branch:** feat/textual-migration
**Commit:** <sha>
**Scope:** live HermesApp Pilot audit + agent.log DEBUG triage

## Summary
| Tier | Count |
|---|---|
| HIGH | N |
| MED  | N |
| LOW  | N |

## HIGH-1: <title>
**File:** `path/to/file.py:line`
**Observed:** ...
**Expected:** ...
**Evidence:** `<log line pasted verbatim>`
**Fix sketch:** <one line>
```

One-line fix sketches only. No spec body. No tests proposed. The follow-up specs are separate work.

---

## 7. e2e seed — JSONL → replay

After the audit:

1. Copy the recorder output: `cp ~/.hermes/keystroke.jsonl <artifact-dir>/keystroke.jsonl`.
2. Inspect with `tools/analyze_keystroke_log.py` to see what was captured.
3. Write a replay plan (`~/.hermes/<date>-e2e-seed-plan.md`) covering:
   - **Schema gaps**: current JSONL has key/density/kind/mouse but lacks: precise timing deltas? focus snapshot? screen content hash? component mount state? List what needs adding.
   - **Replay tool sketch**: `tools/replay_keystroke_log.py` consumes JSONL and drives Pilot — `await pilot.press(row.key)` / `await pilot.click(selector_from(row.component))` / `await pilot.pause(row.dt_ms / 1000)`.
   - **Assertions**: at each step, what to verify (axis-bus state, density, focus, screen tree hash). The recorder doesn't capture these today — list as schema additions.
   - **Determinism**: provider stubbing, clock control, animation timer mocking.

Don't implement the replay tool in the audit task. Plan only. Implementation is its own spec.

---

## 8. Reporting back

Audit summary to caller: artifact paths, finding counts by tier, blockers hit. Keep the chat-back under 300 words. The detail lives in the markdown files.

---

## 9. Re-audit / verification rounds

When prior fixes have landed and you're running again, do **both**: regression-verify the prior issues AND a fresh full audit. Don't just check the fixed items — code that lands fixes also lands new surface.

The findings file should open with a **verification table** mapping each prior R(N-1) finding to one of:

- **FIXED** — re-exercised, evidence in current logs shows the fix in place
- **NOT FIXED** — fix didn't land or didn't take; prior finding still reproduces
- **NOT EXERCISED** — flow that would surface this isn't in the current run; status unknown

Then the body covers new findings only. This keeps round-N reports comparable and lets a reader trace any individual issue across rounds.

Cite commits when claiming FIXED: "FIXED in `7ed7c0c44`" — concrete and grep-able.

---

## 10. Anti-patterns

- **Don't run targeted regression tests as part of the audit.** Audit observes the live app; tests verify fixes. Mixing them muddies signal.
- **Don't fix HIGH findings inline.** Audit run is read-only on code (writes only to `~/.hermes/audit-*` and the JSONL). Fixes go through normal spec → review → implement loop.
- **Don't commit, push, or touch git state.** This branch is active.
- **Don't propose new `docs/concept.md` clauses.** Doc is frozen until 2026-05-11 — see project CLAUDE.md.
- **Don't trust a single flow's silence.** Some inconsistencies only surface under burst/race; exercise streaming and rapid keypresses explicitly.
