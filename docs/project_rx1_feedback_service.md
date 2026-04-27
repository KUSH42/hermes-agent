---
name: RX1 FeedbackService spec
description: FeedbackService — unified flash/timer service replacing 7 ad-hoc flash impls; Phases A/B/C, 18 tests, merged feat/textual-migration 2026-04-22
type: project
originSessionId: 705c5fed-0f73-4cd7-a3ad-deb781a54d43
---
**DONE** 2026-04-22; merged feat/textual-migration (4 commits incl. cleanup commit)

**Why:** D3 overwrite race, D5 lambda ref cycle, E3 `watch_agent_running` clobbering active flash. Every audit rediscovered flash bugs; RX1 is the strategic fix.

**How to apply:** All flash call sites continue to call existing method signatures (`_flash_hint`, `_flash_header`, `flash_copy`, etc.) — Phase B made them forwarders. The service is accessed as `self.feedback` on `HermesApp` and `self.app.feedback` inside widgets.

**Key facts:**
- `services/feedback.py`: `FeedbackService`, `FlashState` (mutable dataclass — `token` assigned post-construction), `FlashHandle` (`.displayed: bool`), `ChannelAdapter`, `AppScheduler`, `HintBarAdapter`, `ToolHeaderAdapter`, `CodeFooterAdapter`
- `ExpireReason`: NATURAL / CANCELLED / PREEMPTED / UNMOUNTED
- Priority: LOW=0, NORMAL=10, WARN=20, ERROR=30, CRITICAL=40; `P1 > P0` preempts; `P1 == P0` replaces; `P1 < P0` blocked
- `key=` replaces regardless of priority
- `ChannelUnmountedError` — internal to `services/feedback.py`; never imported elsewhere
- Only lambda: `lambda: self._on_expire(state.id)` — captures primitive string only (D5 fix)
- `on_agent_idle()` no-ops when flash active (E3 fix); `hint-bar` is only lifecycle-aware channel
- Per-block adapters deregistered in `on_unmount` → prevents stale widget refs
- `session-notify` is NOT a channel (Option B) — `_SessionNotification` keeps own timer
- 15 unit tests (no App/Textual) + 3 integration tests; `FakeScheduler`/`FakeCancelToken`
- Phase C deleted: `_copy_flash_timer`, `_restore_copy`, `_end_flash`, `_copy_flash` bool, `_flash_hint_timer/expires/prior`

**Non-goals:** no copy/tone/visual redesign, no HintBar/StatusBar merge, no queueing, no new flash surfaces
