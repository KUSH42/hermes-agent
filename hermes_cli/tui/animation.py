"""
Shared animation utilities for the Hermes TUI.

Pure functions have no side effects and no Textual imports.
PulseMixin uses duck-typed Textual APIs (set_interval, refresh).
"""
from __future__ import annotations

import math

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
    def _parse(h: str) -> tuple[int, int, int]:
        h = h.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    r1, g1, b1 = _parse(hex1)
    r2, g2, b2 = _parse(hex2)
    r = round(lerp(r1, r2, t))
    g = round(lerp(g1, g2, t))
    b = round(lerp(b1, b2, t))
    return f"#{r:02x}{g:02x}{b:02x}"


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
        if self._pulse_timer is None:
            self._pulse_tick = 0
            # set_interval callback MUST be def (not async def) when no await used.
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

    for i in range(n):
        if i in protected:
            continue
        char_tick = tick - int(i / n * period)
        t = pulse_phase(char_tick, period=period)
        color = lerp_color(dim, peak, t)
        result.stylize(Style(color=color), start=i, end=i + 1)

    return result
