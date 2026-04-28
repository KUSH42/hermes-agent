"""CharacterPacer — deadline-based typewriter pacing for code streaming reveal."""
from __future__ import annotations

import collections
import time
from typing import Callable


class CharacterPacer:
    """Paces character reveal at a configured chars-per-second rate.

    cps=0: pass-through — every feed() returns the full input immediately.
    cps>0: buffer chars, drain on a 60fps timer using deadline-based emission.
           Guarantees steady cadence regardless of feed burst rate.
           Bounded catch-up after stalls: if the emission schedule falls more than
           2 intervals behind the clock, the deadline is reset to now, preventing a
           thundering-herd burst through the entire backlog.

    clock: injectable monotonic clock (default: time.monotonic) for deterministic tests.
    """

    def __init__(
        self,
        cps: int,
        on_reveal: Callable[[str], None],
        app: object | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if isinstance(cps, (int, float)):
            self._cps = max(0, int(cps))
        else:
            self._cps = 0
        self._on_reveal = on_reveal
        self._app = app
        self._clock = clock if clock is not None else time.monotonic
        self._buf: collections.deque[str] = collections.deque()
        self._timer = None
        self._next_emit_at: float = 0.0

    def feed(self, chars: str) -> None:
        """Accept new characters. Pass-through if cps=0."""
        if not chars:
            return
        if self._cps == 0:
            self._on_reveal(chars)
            return
        was_empty = not self._buf
        for ch in chars:
            self._buf.append(ch)
        if was_empty and self._timer is None:
            # Anchor deadline to now so first char emits on the very next tick.
            self._next_emit_at = self._clock()
            self._start_timer()

    def flush(self) -> None:
        """Drain remaining buffer immediately and stop timer."""
        self._stop_timer()
        if self._buf:
            data = "".join(self._buf)
            self._buf.clear()
            self._on_reveal(data)

    def stop(self) -> None:
        """Stop timer without draining (used on widget unmount)."""
        self._stop_timer()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _stop_timer(self) -> None:
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:  # timer already stopped or collected — safe to ignore
                pass
            self._timer = None

    def _start_timer(self) -> None:
        app = self._app
        if app is not None:
            self._timer = app.set_interval(1 / 60, self._tick)

    def _tick(self) -> None:
        """Timer callback — emit chars due at the configured cps rate."""
        if not self._buf:
            self._stop_timer()
            return

        if self._cps <= 0:
            self._stop_timer()
            return

        now = self._clock()
        interval = 1.0 / self._cps

        # Not yet time to emit.
        if now < self._next_emit_at:
            return

        # Burst guard: if we are more than 2 intervals behind schedule (e.g. after a
        # stall), reset the deadline to now to avoid a thundering-herd catch-up burst.
        if now - self._next_emit_at > 2 * interval:
            self._next_emit_at = now

        # Emit as many chars as have become due since the last scheduled deadline.
        elapsed_since_deadline = now - self._next_emit_at
        chars_due = max(1, int(elapsed_since_deadline / interval) + 1)

        batch: list[str] = []
        for _ in range(chars_due):
            if self._buf:
                batch.append(self._buf.popleft())
            else:
                break

        if batch:
            self._on_reveal("".join(batch))
            self._next_emit_at += len(batch) * interval

        if not self._buf:
            self._stop_timer()
