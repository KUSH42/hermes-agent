"""finalize_queue — module-level queue for deferred BodyRenderer.finalize calls.

Architecture: tui-tool-panel-v2-spec.md §5.1, §14.1.

Problem: rich.Syntax finalization for long outputs can take 10–80 ms.
Calling finalize() synchronously on the event loop causes a visible hitch
at tool_complete. The finalize queue defers these calls to a once-per-frame
drain so the UI stays responsive.

Usage
-----
    from hermes_cli.tui.finalize_queue import enqueue_finalize

    # At tool_complete, instead of calling finalize directly:
    enqueue_finalize(lambda: body_pane._apply_finalize(renderer.finalize(all_plain)))

    # The HermesApp 60fps render timer drains one entry per tick:
    drain_one()  # called from app._on_render_tick (Phase 3 wiring)

Backpressure
------------
When queue depth exceeds MAX_DEPTH, enqueue_finalize runs the closure
inline rather than deferring (prevents unbounded queue growth during
burst of 20+ parallel tool completions, per stress test S2).

Phase 2 note: the drain timer is NOT wired into the app yet — Phase 3
adds the render-tick hook. In Phase 2, drain_one() is called explicitly
by ExecuteCodeBlock.finalize_code and WriteFileBlock.complete via
_drain_finalize_immediately(), which runs all pending closures
synchronously on the event loop (acceptable because Phase 2 doesn't
change the timing model vs Phase 1).
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Callable

_log = logging.getLogger(__name__)

_queue: deque[Callable[[], None]] = deque()

MAX_DEPTH = 64


def enqueue_finalize(fn: Callable[[], None]) -> None:
    """Add *fn* to the finalize queue, or run inline if queue is too deep."""
    if len(_queue) >= MAX_DEPTH:
        try:
            fn()
        except Exception as exc:
            _log.warning("finalize inline (queue full) raised: %s", exc, exc_info=True)
        return
    _queue.append(fn)


def drain_one() -> bool:
    """Drain the oldest pending finalize closure. Return True if one was run."""
    if not _queue:
        return False
    fn = _queue.popleft()
    try:
        fn()
    except Exception as exc:
        _log.warning("finalize drain_one raised: %s", exc, exc_info=True)
    return True


def drain_all() -> int:
    """Drain all pending finalize closures. Returns count drained."""
    count = 0
    while _queue:
        fn = _queue.popleft()
        try:
            fn()
        except Exception as exc:
            _log.warning("finalize drain_all raised: %s", exc, exc_info=True)
        count += 1
    return count


def queue_depth() -> int:
    """Return current number of pending finalize closures."""
    return len(_queue)
