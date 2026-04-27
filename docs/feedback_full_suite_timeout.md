---
name: Full TUI suite timeout
description: Never run the full tests/tui/ suite with default 2-minute timeout — it takes 16+ minutes
type: feedback
originSessionId: 13cbf76b-1b41-4330-a37f-1e38c7290e98
---
Never run `python -m pytest tests/tui/` with a 120s timeout. The full suite takes 16+ minutes (confirmed: 989s / ~16.5 min).

**Why:** User explicitly called this out as stupid — causes repeated wasted waits.

**How to apply:**
- If running the full suite is truly needed, use `timeout=1200000` (20 min) minimum
- Prefer running only targeted files after making changes — run only the files relevant to the changes made
- Background runs with `run_in_background=true` are fine but still need realistic timeout on the `until` poll loop
