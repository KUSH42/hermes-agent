---
name: Audit 4 Overlay Hardening spec
description: P1 overlay fixes — approval diff Enter-ambiguity, config tab grouping, usage sparkline → table, HelpOverlay 2-tab.
type: project
originSessionId: cfcecd26-19f5-49dc-8bf4-f8660e32392c
---
DRAFT — spec at `/home/xush/.hermes/2026-04-24-audit4-overlay-hardening-spec.md`

Issues: INTR-02, CONFIG-01, REF-01, TRIGGER-03
Tests: 24 in `tests/tui/test_audit4_overlay_hardening.py`

**Why:** Non-trivial overlay changes from audit 4. TRIGGER-03 (HelpOverlay 2-tab + KeymapOverlay retirement) is the largest item.

**How to apply:** INTR-02 first (standalone), then CONFIG-01 (cosmetic), REF-01 (replace sparkline), TRIGGER-03 last.
