---
name: response_flow.py audit fixes spec
description: Spec A IMPLEMENTED; index spec split into A/B/C; A-1..A-6 + R-18 done; 148 tests total
type: project
originSessionId: c2b987c9-8a10-44f9-8ad4-ee343a0f5125
---
Spec index at /home/xush/.hermes/2026-04-24-response-flow-fixes-spec.md (Status: SPLIT into A/B/C).

Spec A at /home/xush/.hermes/2026-04-24-response-flow-fixes-a-spec.md (Status: IMPLEMENTED 2026-04-24).
- A-1..A-6 + R-18 flush() leading _flush_block_buf() drain; 19 tests in test_response_flow_audit.py
- 148 tests pass across all response_flow test files; 0 regressions

Spec B at /home/xush/.hermes/2026-04-24-response-flow-fixes-b-spec.md — IMPLEMENTED 2026-04-24.
- B-1..B-3, B-5, D-2, D-5, D-6; 10 tests in test_response_flow_audit.py
- All fixes landed in pre-spec commit 003688ec alongside A and C; no follow-up commit needed.

Spec C at /home/xush/.hermes/2026-04-24-response-flow-fixes-c-spec.md — also in 003688ec; verify status.

**Why:** State-machine correctness issues in ResponseFlowEngine; ReasoningFlowEngine parity; _LineClassifier routing; ThemeService engine walk.

**How to apply:** All three specs IMPLEMENTED. No further action needed on feat/textual-migration for this audit.
