---
name: rtk pytest output suppression
description: rtk-ai/rtk plugin suppresses pytest output; fix with --override-ini="addopts="
type: reference
originSessionId: c8c4e888-59a1-450c-8d72-f08052f361b3
---
rtk-ai/rtk is installed and intercepts pytest CLI output. It:
- Swallows stdout/stderr, replacing it with compressed summaries
- Shows "No tests collected" on `--collect-only` even when tests exist
- Shows "Pytest: N passed" summary lines instead of normal output
- Logs full pytest output to `~/.local/share/rtk/tee/<timestamp>_pytest.log`

**Fix:** always run pytest with `--override-ini="addopts="` to bypass rtk's injected options.

```
python -m pytest <path> --override-ini="addopts="
```

**When tests fail:** rtk shows a short failure summary. Read the full log at the path it prints: `~/.local/share/rtk/tee/<timestamp>_pytest.log`

**Why:** rtk injects addopts (likely xdist or capture flags) and intercepts all CLI output to reduce token waste in AI conversations.
