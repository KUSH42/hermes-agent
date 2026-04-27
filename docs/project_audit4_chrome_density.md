---
name: Audit 4 Chrome Density spec
description: Widen BrowseMinimap to 2-cell composite glyphs; merge InputLegendBar into HermesInput placeholder.
type: project
originSessionId: cfcecd26-19f5-49dc-8bf4-f8660e32392c
---
DRAFT — spec at `/home/xush/.hermes/2026-04-24-audit4-chrome-density-spec.md`

Issues: BROWSE-01 (2-cell minimap + composite anchor density), IA-01 (InputLegendBar → placeholder slot)
Tests: 22 in `tests/tui/test_audit4_chrome_density.py`

**Why:** BROWSE-01 fixes first-match-wins band collapse (multi-anchor turns show as 1 glyph). IA-01 reduces bottom chrome stack from 4 to 3 rows by folding legend into the input placeholder.

**How to apply:** Either order; both are fully independent. BROWSE-01 is safer (CSS width + render logic). IA-01 requires deleting InputLegendBar from compose + updating all call sites.
