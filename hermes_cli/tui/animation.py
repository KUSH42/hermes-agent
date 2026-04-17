"""
Shared animation utilities for the Hermes TUI.

Pure functions have no side effects and no Textual imports.
PulseMixin and AnimationClock use duck-typed Textual APIs (set_interval, refresh).
"""
from __future__ import annotations

import math
from collections.abc import Callable

from rich.style import Style
from rich.text import Text


# ---------------------------------------------------------------------------
# Pure numeric helpers
# ---------------------------------------------------------------------------

def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation between a and b at position t ∈ [0, 1]."""
    return a + (b - a) * t


def ease_out_cubic(t: float) -> float:
    """Cubic ease-out: fast start, gentle deceleration. t ∈ [0, 1]."""
    return 1.0 - (1.0 - t) ** 3


def ease_in_out_cubic(t: float) -> float:
    """Symmetric S-curve. t ∈ [0, 1]."""
    if t < 0.5:
        return 4.0 * t ** 3
    return 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0


def pulse_phase(tick: int, period: int = 30) -> float:
    """
    Sine-based oscillation: returns a value in [0, 1] that cycles smoothly
    over `period` ticks. Tick 0 → 0.0; tick period/4 → 1.0; tick period/2 → 0.0.

    At 15fps with period=30: one full breath = 2 seconds.
    """
    return (math.sin(2.0 * math.pi * tick / period) + 1.0) / 2.0


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------

_RGB_CACHE: dict[str, tuple[int, int, int]] = {}

def _parse_rgb(h: str) -> tuple[int, int, int]:
    """Parse hex color to RGB tuple, with caching."""
    cached = _RGB_CACHE.get(h)
    if cached is not None:
        return cached
    h2 = h.lstrip("#")
    result = (int(h2[0:2], 16), int(h2[2:4], 16), int(h2[4:6], 16))
    if len(_RGB_CACHE) < 256:
        _RGB_CACHE[h] = result
    return result


def lerp_color(hex1: str, hex2: str, t: float) -> str:
    """
    Linearly interpolate between two hex colors.

    Args:
        hex1: Start color, e.g. "#4caf50" or "4caf50".
        hex2: End color.
        t:    Blend factor ∈ [0, 1]. 0 → hex1, 1 → hex2.

    Returns:
        Interpolated hex color string, e.g. "#7abc60".

    Interpolation is in linear RGB. Gamma error is negligible (<1 step per
    channel) for terminal truecolor output.
    """
    r1, g1, b1 = _parse_rgb(hex1)
    r2, g2, b2 = _parse_rgb(hex2)
    r = round(r1 + (r2 - r1) * t)
    g = round(g1 + (g2 - g1) * t)
    b = round(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def lerp_color_rgb(
    c1: tuple[int, int, int], c2: tuple[int, int, int], t: float
) -> str:
    """lerp_color from pre-parsed RGB tuples — skip hex parse entirely."""
    r = round(c1[0] + (c2[0] - c1[0]) * t)
    g = round(c1[1] + (c2[1] - c1[1]) * t)
    b = round(c1[2] + (c2[2] - c1[2]) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


# ---------------------------------------------------------------------------
# Shared animation clock
# ---------------------------------------------------------------------------

class _ClockSubscription:
    """Adapter so clock subscriptions expose the same .stop() as Textual timer handles."""

    __slots__ = ("_clock", "_sub_id")

    def __init__(self, clock: "AnimationClock", sub_id: int) -> None:
        self._clock = clock
        self._sub_id = sub_id

    def stop(self) -> None:
        self._clock.unsubscribe(self._sub_id)


class AnimationClock:
    """Single 15Hz master tick bus. App creates one and exposes it as ``_anim_clock``.

    Widgets subscribe in start/activate/on_mount and unsubscribe via the returned
    handle's ``.stop()`` (same interface as Textual timer handles).

    Divisor reference at 15Hz:
      divisor=1  → 15.0 Hz   (pulse, helix shimmer)
      divisor=2  → 7.5  Hz   (hint-bar shimmer, completion shimmer)
      divisor=4  → 3.75 Hz   (thinking shimmer, was 4 Hz)
      divisor=8  → 1.875 Hz  (cursor blink, was 2 Hz)
      divisor=75 → 0.2  Hz   (status-bar hint rotation, was 5 s)
    """

    def __init__(self) -> None:
        self._tick: int = 0
        self._subscribers: dict[int, tuple[int, Callable[[], None]]] = {}
        self._next_id: int = 0

    def subscribe(self, divisor: int, callback: Callable[[], None]) -> _ClockSubscription:
        """Register *callback* to fire every *divisor* ticks. Returns a stoppable handle."""
        sub_id = self._next_id
        self._next_id += 1
        self._subscribers[sub_id] = (divisor, callback)
        return _ClockSubscription(self, sub_id)

    def unsubscribe(self, sub_id: int) -> None:
        self._subscribers.pop(sub_id, None)

    def tick(self) -> None:
        """15Hz interval callback — must be plain def, registered via set_interval(1/15, ...)."""
        import time as _t
        _t0 = _t.perf_counter()
        self._tick += 1
        n_subs = len(self._subscribers)
        slowest_ms = 0.0
        slowest_id = -1
        for sub_id, (divisor, callback) in list(self._subscribers.items()):
            if self._tick % divisor == 0:
                _s0 = _t.perf_counter()
                callback()
                _s_ms = (_t.perf_counter() - _s0) * 1000
                if _s_ms > slowest_ms:
                    slowest_ms = _s_ms
                    slowest_id = sub_id
        _dt = (_t.perf_counter() - _t0) * 1000
        if _dt > 16 or n_subs > 50:
            try:
                from hermes_cli.tui.app import _log_lag
                detail = f" (slowest sub#{slowest_id}: {slowest_ms:.1f}ms)" if slowest_ms > 8 else ""
                _log_lag(f"anim_clock.tick took {_dt:.1f}ms ({n_subs} subs){detail}")
            except Exception:
                pass


# ---------------------------------------------------------------------------
# PulseMixin
# ---------------------------------------------------------------------------

class PulseMixin:
    """
    Mixin that drives a sinusoidal pulse at 15fps using Textual's set_interval.

    Subclass must appear before Widget in the MRO:
        class MyWidget(PulseMixin, Widget): ...

    PulseMixin has no __init__ to avoid MRO conflicts. It uses duck-typing
    for Textual APIs (set_interval, refresh) — these are resolved at call
    time via self, which is always a Widget subclass in practice.

    Usage:
        def on_mount(self) -> None:
            ...

        def watch_some_reactive(self, value: bool) -> None:
            if value:
                self._pulse_start()
            else:
                self._pulse_stop()

        def render(self) -> RenderResult:
            color = lerp_color("#888888", "#ffbf00", self._pulse_t)
            return Text("●", style=f"bold {color}")
    """

    _pulse_t: float = 0.0
    _pulse_tick: int = 0
    _pulse_timer: object | None = None

    def _pulse_start(self) -> None:
        """Start the pulse. Safe to call multiple times (idempotent)."""
        if self._pulse_timer is not None:
            return
        self._pulse_tick = 0
        clock: AnimationClock | None = getattr(
            getattr(self, "app", None), "_anim_clock", None
        )
        if clock is not None:
            self._pulse_timer = clock.subscribe(1, self._pulse_step)
        else:
            # Fallback for unit tests (no app / no clock).
            self._pulse_timer = self.set_interval(  # type: ignore[attr-defined]
                1 / 15, self._pulse_step
            )

    def _pulse_stop(self) -> None:
        """Stop the pulse and reset to neutral."""
        if self._pulse_timer is not None:
            self._pulse_timer.stop()
            self._pulse_timer = None
        self._pulse_t = 0.0
        self.refresh()  # type: ignore[attr-defined]

    def on_unmount(self) -> None:
        """Safety net: stop pulse on widget removal regardless of subclass cleanup."""
        self._pulse_stop()

    def _pulse_step(self) -> None:
        """15Hz timer callback — must be plain def."""
        self._pulse_tick += 1
        self._pulse_t = pulse_phase(self._pulse_tick, period=30)
        self.refresh()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Shimmer
# ---------------------------------------------------------------------------

def shimmer_text(
    source: "str | Text",
    tick: int,
    dim: str,
    peak: str,
    period: int = 40,
    skip_ranges: "list[tuple[int, int]] | None" = None,
) -> Text:
    """
    Returns a Rich Text where each character's foreground color is driven by
    a traveling sine wave — left edge leads, right edge trails.

    The wave completes one traversal across the full text in `period` ticks:
      At 15fps / period=40 → ~2.7s traversal
      At  8fps / period=32 → ~4.0s traversal (subtler, less distracting)

    Existing bold/italic/dim span attributes are preserved. Only foreground
    color is overridden per character via Text.stylize().

    Args:
        source:       Plain str or Rich Text. Source is never mutated.
        tick:         Monotonically increasing animation tick (int).
        dim:          Hex color at wave trough (leading/trailing edge).
        peak:         Hex color at wave crest (traveling highlight).
        period:       Ticks for one full wave traversal across the text.
        skip_ranges:  List of (start, end) character index pairs where end
                      is EXCLUSIVE (matches Python slice convention). Characters
                      in these ranges keep their existing color — use this to
                      protect key badge names from the shimmer wave.

    Returns:
        New Rich Text with shimmer applied. Caller owns the result.
    """
    result = Text(source) if isinstance(source, str) else source.copy()
    n = len(result)
    if n == 0:
        return result

    protected: set[int] = set()
    if skip_ranges:
        for start, end in skip_ranges:  # end is exclusive
            protected.update(range(start, end))

    # Pre-parse dim/peak RGB once (cached)
    dr, dg, db = _parse_rgb(dim)
    pr, pg, pb = _parse_rgb(peak)

    # Pre-compute colors for all positions
    colors: list[str | None] = [None] * n
    for i in range(n):
        if i in protected:
            continue
        char_tick = tick - int(i / n * period)
        t = pulse_phase(char_tick, period=period)
        r = round(dr + (pr - dr) * t)
        g = round(dg + (pg - dg) * t)
        b = round(db + (pb - db) * t)
        colors[i] = f"#{r:02x}{g:02x}{b:02x}"

    # Batch consecutive same-color runs into single spans
    run_start = 0
    run_color = colors[0]
    for i in range(1, n + 1):
        c = colors[i] if i < n else None
        if c != run_color:
            if run_color is not None:
                result.stylize(Style(color=run_color), start=run_start, end=i)
            run_start = i
            run_color = c

    return result
