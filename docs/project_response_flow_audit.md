---
name: response_flow.py audit + fix specs
description: Audit and 3-spec split of response_flow.py issues — A state machine, B reasoning/proxy, C classifier routing
type: project
originSessionId: 94ad0676-e22d-41a2-ba85-ffa18de9abb5
---
Audit at `/home/xush/.hermes/2026-04-24-response-flow-audit.md` — 22 issues
across 5 categories on `hermes_cli/tui/response_flow.py` (1332 lines). 6/10
score. Findings: A-1 silently mis-renders fences after indented-code close,
A-3 asserts crash under `python -O`, B-1 ReasoningFlowEngine never themes
correctly, C-1 `_LineClassifier` is dead-code parallel impl.

**Why:** Pre-existing bugs surfaced by full read; classifier rot risk grows.

**How to apply:** Three sibling specs to land in order A → B → C. Each gets
its own DRAFT → review-loop → APPROVED → IMPLEMENTED cycle. Index at
`/home/xush/.hermes/2026-04-24-response-flow-fixes-spec.md` (status: SPLIT).

- Spec A — `2026-04-24-response-flow-fixes-a-spec.md` — DRAFT, 16 tests,
  state machine: A-1..A-6. Land first.
- Spec B — `2026-04-24-response-flow-fixes-b-spec.md` — DRAFT, 12 tests,
  reasoning/proxy: B-1..B-5 + D-2/D-5/D-6. Touches `services/theme.py` for
  B-2. Land second.
- Spec C — `2026-04-24-response-flow-fixes-c-spec.md` — DRAFT, 5 tests,
  classifier routing: C-1/C-2. Land third (touches every site A and B
  touch — last to avoid rebase churn).

Test files: `tests/tui/test_response_flow_audit_{a,b,c}.py`.
Branch base: `feat/textual-migration` for all three.

Deferred: D-1 dispatcher split, A-7 cosmetic flicker, _LineClassifier deletion
option (b).
