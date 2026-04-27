---
name: ThinkingWidget v2 spec
description: Composable ThinkingWidget — AnimSurface + LabelLine, 5 modes, 4 substates, two-phase deactivate. DONE 2026-04-22.
type: project
originSessionId: cca92689-af3d-47d2-aa54-25079b120e0d
---
ThinkingWidget v2 implemented and merged onto feat/textual-migration (commit c0f22ac9).

**Why:** old widget had a hand-rolled helix duplicating anim_engines logic, no text effect, fixed 3-row height, abrupt disappear on deactivate.

**New file:** `hermes_cli/tui/widgets/thinking.py`

**How to apply:** When touching ThinkingWidget, import from `.thinking`, not `.message_panel`. `message_panel.py` now only has a re-export shim.
