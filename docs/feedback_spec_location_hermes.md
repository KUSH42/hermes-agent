---
name: Hermes spec files go to /home/xush/.hermes/ (parent of hermes-agent repo)
description: For the hermes-agent project, spec .md files are written to /home/xush/.hermes/ (the repo's parent dir, where wdo.txt lives), NOT inside the repo's specs/ subdir
type: feedback
originSessionId: 23565d9d-70b1-4872-bf70-0f7783cd869b
---
For the hermes-agent project, specs are saved to **`/home/xush/.hermes/`** — the parent directory of the `hermes-agent/` repo. This is where design briefs like `wdo.txt` live, alongside existing specs such as `textual-migration.md`, `tui-clipboard-selection-spec.md`, `typewriter_streaming.md`, `v4a_patch_hardening.md`, and the dated `2026-04-05-terminal-output-interceptor-*.md` series.

**Why:** User explicitly said "save them to .." (parent of cwd `/home/xush/.hermes/hermes-agent`) on 2026-04-11 when establishing the rule. There *is* a `hermes-agent/specs/` subdir inside the repo (with `tui-capabilities-roadmap.md`, `tool-block-browse-mode.md`, `tool-output-streamline.md`), but those are roadmap/status docs, not the working-directory for new spec drafts. The parent dir is where the user stages design inputs (wdo.txt) and outputs together.

**How to apply:**
- For any new hermes-agent spec/design doc, create it at `/home/xush/.hermes/<name>.md`.
- Follow the existing naming pattern — either a slug (`tui-clipboard-selection-spec.md`) or a dated prefix for time-stamped work (`2026-MM-DD-<slug>.md`). Slug-only is fine for most cases.
- Do NOT put new specs inside `hermes-agent/specs/` — reserve that for committed/reviewed specs that belong in the repo.
- Pairs with `feedback_spec_format.md` which mandates the `.md` extension.
- If the user ever clarifies that a particular spec should go *into* the repo's `specs/` dir instead, honor that for the specific spec but don't overwrite this default.
