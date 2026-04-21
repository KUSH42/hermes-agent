"""CharacterPacer — optional typewriter pacing for code streaming reveal."""
from __future__ import annotations

import collections
from typing import Callable


class CharacterPacer:
    """Paces character reveal at a configured chars-per-second rate.

    cps=0: pass-through — every feed() returns the full input immediately.
    cps>0: buffer chars, drain on a 60fps timer at `cps` chars/sec. If
    stream outpaces drain, buffer grows. If stream is slower than drain,
    pacer naturally waits on the stream.
    """

    def __init__(
        self,
        cps: int,
        on_reveal: Callable[[str], None],
        app: object | None = None,
    ) -> None:
        if isinstance(cps, (int, float)):
            self._cps = max(0, int(cps))
        else:
            self._cps = 0
        self._on_reveal = on_reveal
        self._app = app
        self._buf: collections.deque[str] = collections.deque()
        self._timer = None
        self._chars_per_tick = max(1, round(self._cps / 60)) if self._cps > 0 else 0

    def feed(self, chars: str) -> None:
        """Accept new characters to reveal. Pass-through if cps=0."""
        if not chars:
            return
        if self._cps == 0:
            self._on_reveal(chars)
            return
        for ch in chars:
            self._buf.append(ch)
        if self._timer is None and self._buf:
            self._start_timer()

    def flush(self) -> None:
        """Drain remaining buffer immediately and stop timer."""
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:
                pass
            self._timer = None
        if self._buf:
            data = "".join(self._buf)
            self._buf.clear()
            self._on_reveal(data)

    def stop(self) -> None:
        """Stop timer without draining (called on_unmount)."""
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:
                pass
            self._timer = None

    def _start_timer(self) -> None:
        app = self._app
        if app is not None:
            self._timer = app.set_interval(1 / 60, self._tick)
        else:
            self._timer = None

    def _tick(self) -> None:
        if not self._buf:
            if self._timer is not None:
                try:
                    self._timer.stop()
                except Exception:
                    pass
                self._timer = None
            return
        batch: list[str] = []
        for _ in range(self._chars_per_tick):
            if self._buf:
                batch.append(self._buf.popleft())
            else:
                break
        if batch:
            self._on_reveal("".join(batch))
        if not self._buf:
            if self._timer is not None:
                try:
                    self._timer.stop()
                except Exception:
                    pass
                self._timer = None
