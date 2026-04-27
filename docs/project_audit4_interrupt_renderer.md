---
name: Audit 4 Interrupt Renderer spec
description: Extract per-kind _InterruptRenderer protocol; split NEW_SESSION/MERGE_CONFIRM into SessionFlowOverlay.
type: project
originSessionId: cfcecd26-19f5-49dc-8bf4-f8660e32392c
---
DRAFT — spec at `/home/xush/.hermes/2026-04-24-audit4-interrupt-renderer-spec.md`

Issues: INTR-03 (renderer protocol), INTR-04 (SessionFlowOverlay split)
Tests: 28 in `tests/tui/test_audit4_interrupt_renderer.py`

**Why:** InterruptOverlay is 998 lines with 7 variants + queue + countdown + guards. Renderer extraction makes per-kind tests trivial. SessionFlowOverlay split enforces "InterruptOverlay = agent-blocked" contract.

**How to apply:** INTR-03 steps 1–3 (protocol + classes + registry) before touching overlay dispatch; INTR-04 after INTR-03 dispatch is verified.
