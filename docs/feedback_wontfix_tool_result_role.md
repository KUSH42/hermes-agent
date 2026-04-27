---
name: fix-tool-result-role is wontfix
description: The tool-result role conversion edge case (local /anthropic proxy mis-detected as anthropic_messages) is explicitly wontfix — do not re-spec or re-implement it
type: feedback
originSessionId: 3facddc8-0739-405f-a98a-9786dc59424f
---
Do not spec, implement, or revisit `/home/xush/.hermes/fix-tool-result-role-spec.md`.

The bug it describes — a local reverse proxy with a `/anthropic` suffix URL getting auto-detected as `api_mode="anthropic_messages"`, causing `role:"tool"` messages to be wrongly converted to `role:"user"+tool_result blocks — is considered a weird edge case and is wontfix.

**Why:** The scenario (local OpenAI-wire endpoint proxied under a path called `/anthropic`) is too unusual to merit a config escape hatch or auto-detection heuristic change. The spec was abandoned 2026-04-22.

**How to apply:** If this file or bug description surfaces in future sessions, skip it immediately and move to the next item.
