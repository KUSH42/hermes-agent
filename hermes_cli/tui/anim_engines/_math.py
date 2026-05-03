"""Math/attractor animation engines: StrangeAttractorEngine, HyperspaceEngine."""
from __future__ import annotations

import math
import random

from ._base import (
    AnimParams,
    TrailCanvas,
    _BaseEngine,
    _braille_density_set,
    _make_canvas,
    _make_trail_canvas,
    _safe_dims,
)


class StrangeAttractorEngine(_BaseEngine):
    """Lorenz/Rössler/Thomas attractor traced with RK4, TrailCanvas decay=0.97."""

    def __init__(self) -> None:
        self._x = 0.1
        self._y = 0.0
        self._z = 0.0
        self._bounds: dict[str, float] = {}
        self._init_ticks = 0
        self._xs: list[float] = []
        self._ys: list[float] = []
        self._heat_sigma = 0.0
        self._slow_dt_ticks: int = 0  # for "complete" slow settle
        self._dt_boost_ticks: int = 0  # for "reasoning" speed-boost
        self._dt_default: float = 0.01

    def on_signal(self, signal: str, value: float = 1.0) -> None:
        if signal == "complete":
            # Halve dt for 40 ticks, creating slow settle
            self._slow_dt_ticks = 40
        elif signal == "reasoning":
            # Boost dt by 30% for 30 ticks
            self._dt_boost_ticks = 30
        else:
            self._heat_sigma = value * 2.0

    def _lorenz(self, x: float, y: float, z: float, sigma: float) -> tuple[float, float, float]:
        rho = 28.0
        beta = 8 / 3
        dx = sigma * (y - x)
        dy = x * (rho - z) - y
        dz = x * y - beta * z
        return dx, dy, dz

    def _rossler(self, x: float, y: float, z: float) -> tuple[float, float, float]:
        a, b, c = 0.2, 0.2, 5.7
        return -y - z, x + a * y, b + z * (x - c)

    def _thomas(self, x: float, y: float, z: float) -> tuple[float, float, float]:
        b = 0.208186
        return math.sin(y) - b * x, math.sin(z) - b * y, math.sin(x) - b * z

    def _deriv(self, x: float, y: float, z: float, atype: str, sigma: float) -> tuple[float, float, float]:
        if atype == "rossler":
            return self._rossler(x, y, z)
        elif atype == "thomas":
            return self._thomas(x, y, z)
        else:
            return self._lorenz(x, y, z, sigma)

    def _rk4_step(self, x: float, y: float, z: float, dt: float, atype: str, sigma: float) -> tuple[float, float, float]:
        k1 = self._deriv(x, y, z, atype, sigma)
        k2 = self._deriv(x + dt/2*k1[0], y + dt/2*k1[1], z + dt/2*k1[2], atype, sigma)
        k3 = self._deriv(x + dt/2*k2[0], y + dt/2*k2[1], z + dt/2*k2[2], atype, sigma)
        k4 = self._deriv(x + dt*k3[0], y + dt*k3[1], z + dt*k3[2], atype, sigma)
        nx = x + dt/6*(k1[0]+2*k2[0]+2*k3[0]+k4[0])
        ny = y + dt/6*(k1[1]+2*k2[1]+2*k3[1]+k4[1])
        nz = z + dt/6*(k1[2]+2*k2[2]+2*k3[2]+k4[2])
        return nx, ny, nz

    def next_frame(self, params: AnimParams) -> str:
        atype = params.attractor_type
        sigma = 10.0 + self._heat_sigma

        # Run 200 init ticks to compute bounds
        if self._init_ticks < 200:
            for _ in range(5):
                self._x, self._y, self._z = self._rk4_step(
                    self._x, self._y, self._z, 0.01, atype, sigma)
                self._xs.append(self._x)
                self._ys.append(self._y)
                self._init_ticks += 1
            if self._init_ticks >= 200:
                self._bounds["xmin"] = min(self._xs)
                self._bounds["xmax"] = max(self._xs)
                self._bounds["ymin"] = min(self._ys)
                self._bounds["ymax"] = max(self._ys)

        canvas = _make_trail_canvas(0.97)
        w, h = params.width, params.height

        dt = self._dt_default
        if self._slow_dt_ticks > 0:
            dt = self._dt_default * 0.5
            self._slow_dt_ticks -= 1
        elif self._dt_boost_ticks > 0:
            dt = self._dt_default * 1.3
            self._dt_boost_ticks -= 1

        for _ in range(5):
            self._x, self._y, self._z = self._rk4_step(
                self._x, self._y, self._z, dt, atype, sigma)
            if self._bounds:
                xmin = self._bounds.get("xmin", -25)
                xmax = self._bounds.get("xmax", 25)
                ymin = self._bounds.get("ymin", -30)
                ymax = self._bounds.get("ymax", 30)
                xr = max(xmax - xmin, 1e-6)
                yr = max(ymax - ymin, 1e-6)
                px = int((self._x - xmin) / xr * (w - 1))
                py = int((self._y - ymin) / yr * (h - 1))
            else:
                px = int((self._x + 25) / 50 * (w - 1))
                py = int((self._y + 30) / 60 * (h - 1))
            px = max(0, min(w - 1, px))
            py = max(0, min(h - 1, py))
            canvas.set(px, py)

        return canvas.frame()


class HyperspaceEngine(_BaseEngine):
    """Star field perspective projection with Z-depth and streak trails."""

    def __init__(self) -> None:
        self._stars: list[list[float]] = []  # [x, y, z, px, py]
        self._init_done = False
        self._w = 0
        self._h = 0
        self._n = 0
        self._warp = False
        self._speed_boost_ticks: int = 0

    def on_signal(self, signal: str, value: float = 1.0) -> None:
        if signal == "complete":
            self._warp = True
        elif signal == "tool":
            # Triple Z-speed for 30 ticks
            self._speed_boost_ticks = 30

    def _init(self, w: int, h: int, n: int) -> None:
        self._stars = [
            [random.uniform(-1, 1), random.uniform(-1, 1), random.uniform(0.7, 1.0), 0.0, 0.0]
            for _ in range(n)
        ]
        self._w = w
        self._h = h
        self._n = n
        self._init_done = True

    def next_frame(self, params: AnimParams) -> str:
        w, h = _safe_dims(params)
        n = min(200, params.particle_count * 3)
        if not self._init_done or self._w != w or self._h != h or self._n != n:
            self._init(w, h, n)

        trail_decay = max(params.trail_decay, 0.7 if params.heat > 0.3 else 0.0)
        canvas = _make_trail_canvas(trail_decay) if trail_decay > 0 else _make_canvas()

        cx, cy = w / 2, h / 2
        scale = min(w, h) * 0.4
        speed = 0.01 + params.heat * 0.04
        if self._warp:
            speed = 0.1
            self._warp = False
        if self._speed_boost_ticks > 0:
            speed *= 3.0
            self._speed_boost_ticks -= 1

        for star in self._stars:
            sx, sy, sz = star[0], star[1], star[2]
            prev_px, prev_py = star[3], star[4]

            sz -= speed
            if sz < 0.01:
                star[0] = random.uniform(-1, 1)
                star[1] = random.uniform(-1, 1)
                star[2] = random.uniform(0.7, 1.0)  # spawn at distance (D5)
                star[3] = cx
                star[4] = cy
                continue

            star[2] = sz
            screen_x = cx + (sx / sz) * scale
            screen_y = cy + (sy / sz) * scale * 0.5

            if 0 <= screen_x < w and 0 <= screen_y < h:
                ix, iy = int(screen_x), int(screen_y)
                # Near stars = dense
                if sz < 0.2:
                    _braille_density_set(canvas, ix, iy, 1.0 - sz, w, h)
                else:
                    canvas.set(ix, iy)
                # Streak trails at high heat
                trail_len = int(params.heat * 12)
                if trail_len > 0 and isinstance(canvas, TrailCanvas):
                    for step in range(trail_len):
                        alpha = step / trail_len
                        tx = int(prev_px + (screen_x - prev_px) * alpha)
                        ty = int(prev_py + (screen_y - prev_py) * alpha)
                        canvas.set(tx, ty, (1.0 - alpha) * 0.6)
            star[3] = screen_x
            star[4] = screen_y

        return canvas.frame() if hasattr(canvas, "frame") else ""
