---
name: Open PRs on NousResearch/hermes-agent
description: The 6 open PRs from KUSH42 on the upstream NousResearch/hermes-agent repo — PR1–PR5 rich rendering stack + PR6 reasoning rendering
type: project
originSessionId: fda841a2-40d0-41ee-9d19-3a2d2d390090
---
As of 2026-04-09, KUSH42 has 6 open PRs on NousResearch/hermes-agent:

| PR # | Title | Branch |
|------|-------|--------|
| 6736 | feat(display): rich rendering pipeline for reasoning/thinking blocks (PR6) | `feat/reasoning-rich-rendering` |
| 4582 | feat(theme): full theme integration — wire all colors/styles to SkinConfig (PR5) | `feat/theme-ui-chrome` |
| 4513 | feat(rich_output): stateful block markdown rendering (PR4) | `feat/markdown-stateful-blocks` |
| 4504 | feat(rich_output): block-level markdown rendering for LLM responses (PR3) | `feat/markdown-block-rendering` |
| 4471 | feat: syntax highlighting for tool outputs and LLM responses (PR2) | `feat/tool-output-highlighting` |
| 4470 | feat: Rich-based rendering engine with intra-line diff highlighting (PR1) | `feat/rich-diff-renderer` |

**Tracking issue:** NousResearch/hermes-agent#4518

**Why:** PR1–PR5 are a stacked series implementing a rich terminal rendering pipeline and theming system. PR6 extends that pipeline to reasoning/thinking blocks (`display.rich_reasoning`, default true).
**How to apply:** When discussing PRs, branches, or review status, refer to these by their PR number and label (PR1–PR6). All branches live on the KUSH42 fork and target NousResearch/hermes-agent main.
