---
name: TUI test scope — targeted only
description: NEVER run tests/tui/ full suite — always times out. Targeted files only. No exceptions.
type: feedback
originSessionId: 38818f44-0269-4956-905d-f7b3646bd880
---

**RULE: Never run `python -m pytest tests/tui/` (full suite). Ever. No exceptions.**

**Why:** 2900+ tests, always hits timeout. User has been burned by this repeatedly and is furious each time it happens. Running more tests than the set that just timed out does not help.

**How to apply:**
- After implementing a change, run only the test files directly related to the changed module:
  - Changed `drawille_overlay.py` → run `test_anim_overlay.py`, `test_drawille_v2.py`
  - Changed `tool_blocks/` → run `test_tool_blocks.py`, `test_tool_panel.py`
  - Changed `app.py` → run `test_app.py` if it exists, NOT the whole suite
- Never expand scope to `tests/tui/` even for "broader regression checking"
- If the specific test file doesn't exist yet, import-check only: `python -c "from hermes_cli.tui.xxx import Foo; print('OK')"`
- Single test runs to verify individual fixes: `pytest path/to/test.py::TestClass::test_name`
