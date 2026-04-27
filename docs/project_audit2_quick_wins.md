---
name: Audit 2 Quick Wins spec
description: Audit 2 quick-win fixes for tool call surface — B3/B4/B6/B7/B10/B11 (B8 dropped)
type: project
originSessionId: 893fc893-43d3-44ef-bb0a-624e6f2fb1a9
---
DONE 2026-04-24 (merged feat/textual-migration). 6 issues, 22 tests. Commits 581fb2cd–20043592.

Spec: /home/xush/.hermes/2026-04-24-audit2-quick-wins-spec.md

**Why:** Audit 2 identified these as < 1 day each; all are mechanical with no architectural risk.

**Issues:**
- B11: `flash_success` always fires on completion including errors — branch to `flash_error()` in `_streaming.py:313`
- B4: `_DropOrder` list subclass uses `inspect.stack()` to lie to tests — deleted, updated `test_tui_polish.py`
- B6: OmissionBar default button `[hide]` → `[reset]`; removed duplicate `--ob-cap-adv` button
- B7: SubAgentHeader shows no running indicator when not done — added `●` to segments BEFORE `_trim_tail_segments`
- B10: EmptyStateRenderer gives same "(no output)" for all categories — category-aware via `_get_empty_message()`
- B3: Auto-collapse snaps to top on expand — pre-seed tail position before triggering collapse
- ~~B8~~: REMOVED — `FooterPane.compact` IS live code; rule is not dead
