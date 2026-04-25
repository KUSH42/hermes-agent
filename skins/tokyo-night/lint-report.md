---
skin: tokyo-night
warning_baseline: 0
---

# DESIGN.md lint report — tokyo-night

## Command

```
npx -y @google/design.md lint --format json skins/tokyo-night/DESIGN.md
```

## Findings

| Severity | Count | Notes |
|---|---|---|
| Error | 0 | No structural errors. |
| Warning | 0 | Initial baseline at conversion time. |
| Info | 0 | — |

Warnings are accepted palette debt. Any palette color change to satisfy WCAG
contrast must land in a separate PR per parent DM-G.
