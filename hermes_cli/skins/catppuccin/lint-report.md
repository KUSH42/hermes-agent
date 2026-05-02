---
skin: catppuccin
warning_baseline: 0
---

# DESIGN.md lint report — catppuccin

## Command

```
npx -y @google/design.md lint --format json skins/catppuccin/DESIGN.md
```

## Lint CLI version

Captured by CI when the export job runs. The local `requires_npx`-marked
tests in `tests/tui/test_design_md_skin.py` are skipped on machines without
`npx`.

## Findings

| Severity | Count | Notes |
|---|---|---|
| Error | 0 | No structural errors. |
| Warning | 0 | Initial baseline at conversion time. |
| Info | 0 | — |

Warnings are accepted palette debt. Any palette color change to satisfy WCAG
contrast must land in a separate PR per parent DM-G.
