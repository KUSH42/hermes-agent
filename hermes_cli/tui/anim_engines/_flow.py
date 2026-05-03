"""Flow-family animation engines: VortexEngine, WaveInterferenceEngine, PerlinFlowEngine, FluidFieldEngine."""
from __future__ import annotations

import math
import random

from ._base import (
    AnimParams,
    _BaseEngine,
    _lut_sin,
    _make_canvas,
    _make_trail_canvas,
    _safe_dims,
)


class VortexEngine(_BaseEngine):
    """Zooming inward spiral vortex."""

    def next_frame(self, params: AnimParams) -> str:
        canvas = _make_canvas()
        w, h = params.width, params.height
        t = params.t
        cx, cy = w // 2, h // 2
        for i in range(200):
            r = (i / 200) * min(w, h) * 0.5
            theta = i * 0.3 + t * 5.0
            x = cx + int(r * math.cos(theta))
            y = cy + int(r * math.sin(theta) * 0.5)
            if 0 <= x < w and 0 <= y < h:
                canvas.set(x, y)
        return canvas.frame()


class WaveInterferenceEngine(_BaseEngine):
    """Two-source sine interference / Moiré pattern."""

    def next_frame(self, params: AnimParams) -> str:
        canvas = _make_canvas()
        w, h = params.width, params.height
        t = params.t
        src_ax, src_ay = w * 0.25, h * 0.5
        src_bx, src_by = w * 0.75, h * 0.5
        # Normalize wave frequency so ring density stays constant at any canvas size.
        # Calibrated at min(w,h)=40 → k=0.4; scales down for larger canvases.
        k = 16.0 / max(min(w, h), 1)
        threshold = 0.7
        for y in range(0, h, 2):
            for x in range(0, w, 1):
                da = math.sqrt((x - src_ax) ** 2 + (y - src_ay) ** 2)
                db = math.sqrt((x - src_bx) ** 2 + (y - src_by) ** 2)
                val = _lut_sin(da * k - t * 5) + _lut_sin(db * k - t * 5)
                if val > threshold:
                    canvas.set(x, y)
        return canvas.frame()


class PerlinFlowEngine(_BaseEngine):
    """Dense flow field using layered-sine curl noise with TrailCanvas."""

    def __init__(self) -> None:
        self._noise_scale_boost: float = 0.0
        self._noise_restore_ticks: int = 0
        self._noise_default: float = 1.0

    def on_signal(self, signal: str, value: float = 1.0) -> None:
        if signal == "tool":
            # Multiply noise_scale by 2.0 for 60 ticks
            self._noise_scale_boost = 2.0
            self._noise_restore_ticks = 60
        elif signal == "complete":
            # Smoothly restore noise_scale to default
            self._noise_restore_ticks = max(0, self._noise_restore_ticks - 30)
            if self._noise_restore_ticks == 0:
                self._noise_scale_boost = 0.0

    def next_frame(self, params: AnimParams) -> str:
        w, h = params.width, params.height
        t = params.t
        ns = params.noise_scale
        # Apply boost multiplier if active
        if self._noise_restore_ticks > 0:
            ns = ns * self._noise_scale_boost
            self._noise_restore_ticks -= 1
            if self._noise_restore_ticks == 0:
                self._noise_scale_boost = 0.0
        threshold = 0.4 + 0.3 * math.sin(t * (0.5 + params.heat * 2.0))

        canvas = _make_trail_canvas(0.9) if params.trail_decay <= 0 else _make_trail_canvas(params.trail_decay)

        freqs = [1.0 * ns, 2.0 * ns, 4.0 * ns]
        speeds = [0.5, 0.7, 1.1]

        w_inv = 1.0 / max(w, 1)
        h_inv = 1.0 / max(h, 1)
        for y in range(0, h, 2):
            fy = y * h_inv
            for x in range(0, w, 1):
                fx = x * w_inv
                val = sum(
                    _lut_sin(fx * fk * 6.28 + t * sk) * math.cos(fy * fk * 6.28 + t * sk * 0.7)
                    for fk, sk in zip(freqs, speeds)
                ) / len(freqs)
                if val > threshold:
                    canvas.set(x, y)

        return canvas.frame() if hasattr(canvas, "frame") else ""


class FluidFieldEngine(_BaseEngine):
    """Particles following curl-noise velocity field with TrailCanvas."""

    def __init__(self) -> None:
        self._particles: list[list[float]] = []  # [x, y, age]
        self._max_age = 60
        self._init_done = False
        self._w = 0
        self._h = 0

    def _init(self, w: int, h: int, n: int) -> None:
        self._particles = [
            [random.random() * w, random.random() * h, random.randint(0, self._max_age)]
            for _ in range(n)
        ]
        self._w = w
        self._h = h
        self._init_done = True

    def _curl(self, x: float, y: float, t: float, ns: float) -> tuple[float, float]:
        eps = 0.01
        freqs = [1.0 * ns, 2.0 * ns]
        speeds = [0.5, 0.9]

        def noise(nx: float, ny: float) -> float:
            return sum(
                math.sin(nx * fk * 6.28 + t * sk) * math.cos(ny * fk * 6.28 + t * sk * 0.7)
                for fk, sk in zip(freqs, speeds)
            ) / len(freqs)

        dndy = (noise(x, y + eps) - noise(x, y - eps)) / (2 * eps)
        dndx = (noise(x + eps, y) - noise(x - eps, y)) / (2 * eps)
        return dndy, -dndx

    def next_frame(self, params: AnimParams) -> str:
        w, h = _safe_dims(params)
        n = min(200, params.particle_count)
        if not self._init_done or len(self._particles) != n or self._w != w or self._h != h:
            self._init(w, h, n)

        canvas = _make_trail_canvas(params.trail_decay) if params.trail_decay > 0 else _make_canvas()
        vel_mult = 1.0 + params.heat * 3.0
        w_inv = 1.0 / max(w, 1)
        h_inv = 1.0 / max(h, 1)

        for p in self._particles:
            px, py, age = p
            cx, cy = self._curl(px * w_inv, py * h_inv, params.t, params.noise_scale)
            p[0] = (px + cx * vel_mult) % w
            p[1] = (py + cy * vel_mult) % h
            p[2] = age + 1
            if p[2] > self._max_age:
                p[0] = random.random() * w
                p[1] = random.random() * h
                p[2] = 0
            if 0 <= int(p[0]) < w and 0 <= int(p[1]) < h:
                canvas.set(int(p[0]), int(p[1]))

        return canvas.frame() if hasattr(canvas, "frame") else ""
