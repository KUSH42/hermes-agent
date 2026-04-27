---
name: Specs are always written as .md files
description: When authoring a spec/design doc, save it as a Markdown (.md) file — never as a plain chat reply, .txt, .rst, or inline code block dump
type: feedback
originSessionId: 23565d9d-70b1-4872-bf70-0f7783cd869b
---
Specs are always written as `.md` files. If the user asks for a spec, design doc, architecture proposal, or RFC, produce a Markdown file on disk — do not answer inline only.

**Why:** User wants specs to be reviewable, versionable, and linkable. Inline-only responses can't be diffed, commented on, or picked up by `spec-workflow` review. Marked as a *global* preference by the user on 2026-04-11.

**How to apply:**
- Triggered by words like "spec", "design doc", "RFC", "proposal", "architecture", "write up".
- File extension must be `.md`.
- Save location is project-dependent — for hermes-agent see the companion memory `feedback_spec_location_hermes.md` (parent of repo: `/home/xush/.hermes/`).
- Still OK to give a short inline summary pointing at the file, but the file is the deliverable.
- Since auto-memory is project-scoped, this rule only propagates to other projects if the user adds it to `~/.claude/CLAUDE.md`. Flag that option if the user expects cross-project enforcement.
