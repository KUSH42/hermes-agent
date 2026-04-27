---
name: asyncio event loop deprecation warning fix
description: How to fix DeprecationWarning from get_event_loop() in pytest conftest fixtures on Python 3.10+
type: feedback
originSessionId: 22f7500c-aa1f-4565-9d60-ad0e9a906336
---
Use `asyncio.get_running_loop()` instead of `asyncio.get_event_loop_policy().get_event_loop()` in sync pytest fixtures.

**Why:** Python 3.10+ emits `DeprecationWarning: There is no current event loop` when `get_event_loop()` is called with no loop set. `get_running_loop()` raises `RuntimeError` cleanly instead — no warning. In a sync fixture there's never a running loop, so the `except RuntimeError` branch always fires, which is the correct behavior.

**How to apply:** Any time a conftest fixture calls `get_event_loop()` or `get_event_loop_policy().get_event_loop()` to check/create a loop for sync tests, replace with:

```python
try:
    loop = asyncio.get_running_loop()
    created = loop.is_closed()
except RuntimeError:
    loop = None
    created = True

if created:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
```
