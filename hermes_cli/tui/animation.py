"""
Shared animation utilities for the Hermes TUI.

Pure functions have no side effects and no Textual imports.
PulseMixin uses duck-typed Textual APIs (set_interval, refresh).
"""
from __future__ import annotations

import math


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
