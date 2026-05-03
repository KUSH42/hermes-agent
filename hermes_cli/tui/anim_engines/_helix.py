"""Helix-family animation engines."""
from __future__ import annotations

import math

from ._base import (
    AnimParams,
    _BaseEngine,
    _braille_density_set,
    _depth_to_density,
    _make_canvas,
)


class DnaHelixEngine(_BaseEngine):
    """DNA double helix with connecting rungs (default)."""

    def next_frame(self, params: AnimParams) -> str:
        canvas = _make_canvas()
        w, h = params.width, params.height
        t = params.t
        if params.vertical:
            freq = 8.0 * math.pi / max(h, 1)   # 4 cycles across height
            rung_step = max(8, h // 15)
            for y in range(h):
                phase = y * freq + t * 4.0
                x_a = int((math.sin(phase) + 1) * 0.5 * (w - 1))
                x_b = int((math.sin(phase + math.pi) + 1) * 0.5 * (w - 1))
                canvas.set(x_a, y)
                canvas.set(x_b, y)
                if y % rung_step == 0:
                    x_lo, x_hi = min(x_a, x_b), max(x_a, x_b)
                    for x in range(x_lo, x_hi + 1, 2):
                        canvas.set(x, y)
        else:
            freq = 8.0 * math.pi / max(w, 1)   # 4 cycles across width
            rung_step = max(8, w // 15)
            for x in range(w):
                phase = x * freq + t * 4.0
                y_a = int((math.sin(phase) + 1) * 0.5 * (h - 1))
                y_b = int((math.sin(phase + math.pi) + 1) * 0.5 * (h - 1))
                canvas.set(x, y_a)
                canvas.set(x, y_b)
                if x % rung_step == 0:
                    y_lo, y_hi = min(y_a, y_b), max(y_a, y_b)
                    for y in range(y_lo, y_hi + 1, 2):
                        canvas.set(x, y)
        return canvas.frame()


class RotatingHelixEngine(_BaseEngine):
    """3D helix rotating about its long axis, projected orthographically."""

    _N_TURNS = 4

    def next_frame(self, params: AnimParams) -> str:
        canvas = _make_canvas()
        w, h = params.width, params.height
        t = params.t
        cx, cy = w // 2, h // 2
        n_pts = max(160, w * 2)
        rot_y = t * 1.5
        cos_ry, sin_ry = math.cos(rot_y), math.sin(rot_y)
        radius = w * 0.38
        for i in range(n_pts):
            theta = i / n_pts * (2 * math.pi * self._N_TURNS)
            hx = math.cos(theta)
            hz = math.sin(theta)
            rx = hx * cos_ry + hz * sin_ry
            rz = -hx * sin_ry + hz * cos_ry
            hy = (i / n_pts - 0.5) * h * 0.9
            sx = cx + int(rx * radius)
            sy = cy + int(hy)
            if 0 <= sx < w and 0 <= sy < h:
                if params.depth_cues:
                    _depth_to_density(rz, canvas, sx, sy, w, h)
                else:
                    canvas.set(sx, sy)
        return canvas.frame()


def _rot3(x: float, y: float, z: float,
          crx: float, srx: float,
          cry: float, sry: float,
          crz: float, srz: float) -> tuple[float, float, float]:
    """Apply Ry → Rx → Rz compound rotation."""
    x1 = x * cry + z * sry;  z1 = -x * sry + z * cry
    y2 = y * crx - z1 * srx; z2 =  y * srx + z1 * crx
    x3 = x1 * crz - y2 * srz; y3 = x1 * srz + y2 * crz
    return x3, y3, z2


class DoubleHelixEngine(_BaseEngine):
    """3D double-strand helix with compound rotation (Y-spin + X-tumble + Z-roll) and rungs."""

    _N_TURNS = 1.5
    _RUNG_EVERY = 12

    def __init__(self) -> None:
        self._rx: float = 0.0
        self._ry: float = 0.0
        self._rz: float = 0.0

    def next_frame(self, params: AnimParams) -> str:
        self._ry += params.dt * 1.8
        self._rx += params.dt * 0.45
        self._rz += params.dt * 0.3
        canvas = _make_canvas()
        w, h = params.width, params.height
        cx, cy = w // 2, h // 2
        n_pts = max(160, h * 4)
        sx_scale = min(w * 0.18, h * 0.28)
        sy_scale = h * 0.45
        cam_d = 3.5
        crx, srx = math.cos(self._rx), math.sin(self._rx)
        cry, sry = math.cos(self._ry), math.sin(self._ry)
        crz, srz = math.cos(self._rz), math.sin(self._rz)

        def proj(rx: float, ry: float, rz: float) -> tuple[int, int]:
            p = cam_d / (cam_d + rz * 0.6)
            return cx + int(rx * sx_scale * p), cy + int(ry * sy_scale * p)

        def plot(sx: int, sy: int, rz: float) -> None:
            if 0 <= sx < w and 0 <= sy < h:
                if params.depth_cues:
                    _depth_to_density(rz, canvas, sx, sy, w, h)
                else:
                    canvas.set(sx, sy)

        for i in range(n_pts):
            t = i / n_pts
            theta = t * 2 * math.pi * self._N_TURNS
            # strand A
            ax, ay, az = _rot3(math.cos(theta), (t - 0.5) * 2, math.sin(theta),
                                crx, srx, cry, sry, crz, srz)
            plot(*proj(ax, ay, az), az)
            # strand B (π offset)
            bx, by, bz = _rot3(math.cos(theta + math.pi), (t - 0.5) * 2, math.sin(theta + math.pi),
                                crx, srx, cry, sry, crz, srz)
            plot(*proj(bx, by, bz), bz)
            # rungs — interpolate in 3D, always solid
            if i % self._RUNG_EVERY == 0:
                asx, asy = proj(ax, ay, az)
                bsx, bsy = proj(bx, by, bz)
                steps = max(abs(bsx - asx), abs(bsy - asy), 1)
                for s in range(steps + 1):
                    f = s / steps
                    rix, riy, riz = ax+(bx-ax)*f, ay+(by-ay)*f, az+(bz-az)*f
                    rsx, rsy = proj(rix, riy, riz)
                    if 0 <= rsx < w and 0 <= rsy < h:
                        canvas.set(rsx, rsy)
        return canvas.frame()


class DoubleHelixLitEngine(_BaseEngine):
    """Double-strand helix with compound rotation — back strand always visible (no depth fade)."""

    _N_TURNS = 1.5
    _RUNG_EVERY = 12

    def __init__(self) -> None:
        self._rx: float = 0.0
        self._ry: float = 0.0
        self._rz: float = 0.0

    def next_frame(self, params: AnimParams) -> str:
        self._ry += params.dt * 1.8
        self._rx += params.dt * 0.45
        self._rz += params.dt * 0.3
        canvas = _make_canvas()
        w, h = params.width, params.height
        cx, cy = w // 2, h // 2
        n_pts = max(160, h * 4)
        sx_scale = min(w * 0.18, h * 0.28)
        sy_scale = h * 0.45
        cam_d = 3.5
        crx, srx = math.cos(self._rx), math.sin(self._rx)
        cry, sry = math.cos(self._ry), math.sin(self._ry)
        crz, srz = math.cos(self._rz), math.sin(self._rz)

        def proj(rx: float, ry: float, rz: float) -> tuple[int, int]:
            p = cam_d / (cam_d + rz * 0.6)
            return cx + int(rx * sx_scale * p), cy + int(ry * sy_scale * p)

        def plot(sx: int, sy: int, rz: float) -> None:
            if 0 <= sx < w and 0 <= sy < h:
                density = 0.45 + (rz + 1) / 2 * 0.55
                _braille_density_set(canvas, sx, sy, density, w, h)

        for i in range(n_pts):
            t = i / n_pts
            theta = t * 2 * math.pi * self._N_TURNS
            ax, ay, az = _rot3(math.cos(theta), (t - 0.5) * 2, math.sin(theta),
                                crx, srx, cry, sry, crz, srz)
            plot(*proj(ax, ay, az), az)
            bx, by, bz = _rot3(math.cos(theta + math.pi), (t - 0.5) * 2, math.sin(theta + math.pi),
                                crx, srx, cry, sry, crz, srz)
            plot(*proj(bx, by, bz), bz)
            if i % self._RUNG_EVERY == 0:
                asx, asy = proj(ax, ay, az)
                bsx, bsy = proj(bx, by, bz)
                steps = max(abs(bsx - asx), abs(bsy - asy), 1)
                for s in range(steps + 1):
                    f = s / steps
                    rix, riy, riz = ax+(bx-ax)*f, ay+(by-ay)*f, az+(bz-az)*f
                    rsx, rsy = proj(rix, riy, riz)
                    if 0 <= rsx < w and 0 <= rsy < h:
                        canvas.set(rsx, rsy)
        return canvas.frame()


class TripleHelixEngine(_BaseEngine):
    """3D triple-strand helix with compound rotation and perspective (wjz.html style)."""

    _N_TURNS = 3
    _N_STRANDS = 3

    def __init__(self) -> None:
        self._rx: float = 0.0
        self._ry: float = 0.0
        self._rz: float = 0.0

    def next_frame(self, params: AnimParams) -> str:
        self._ry += params.dt * 1.8
        self._rx += params.dt * 0.45
        self._rz += params.dt * 0.3
        canvas = _make_canvas()
        w, h = params.width, params.height
        cx, cy = w // 2, h // 2
        n_pts = max(120, h * 3)
        sx_scale = min(w * 0.18, h * 0.28)
        sy_scale = h * 0.45
        cam_d = 3.5
        crx, srx = math.cos(self._rx), math.sin(self._rx)
        cry, sry = math.cos(self._ry), math.sin(self._ry)
        crz, srz = math.cos(self._rz), math.sin(self._rz)

        for strand in range(self._N_STRANDS):
            phase = strand * 2 * math.pi / self._N_STRANDS
            for i in range(n_pts):
                t = i / n_pts
                theta = t * 2 * math.pi * self._N_TURNS + phase
                rx, ry, rz = _rot3(math.cos(theta), (t - 0.5) * 2, math.sin(theta),
                                    crx, srx, cry, sry, crz, srz)
                p = cam_d / (cam_d + rz * 0.6)
                sx = cx + int(rx * sx_scale * p)
                sy = cy + int(ry * sy_scale * p)
                if 0 <= sx < w and 0 <= sy < h:
                    if params.depth_cues:
                        _depth_to_density(rz, canvas, sx, sy, w, h)
                    else:
                        canvas.set(sx, sy)
        return canvas.frame()


class ClassicHelixEngine(_BaseEngine):
    """Three sine waves scrolling horizontally."""

    def next_frame(self, params: AnimParams) -> str:
        canvas = _make_canvas()
        w, h = params.width, params.height
        t = params.t
        freq = 6.0 * math.pi / max(w, 1)   # 3 cycles across width
        for x in range(w):
            for phase_offset in (0.0, 2.1, 4.2):
                y = int((math.sin(x * freq + t * 5.0 + phase_offset) + 1) * 0.5 * (h - 1))
                canvas.set(x, y)
        return canvas.frame()


class MorphHelixEngine(_BaseEngine):
    """Helix with breathing amplitude modulation."""

    def next_frame(self, params: AnimParams) -> str:
        canvas = _make_canvas()
        w, h = params.width, params.height
        t = params.t
        freq = 8.0 * math.pi / max(w, 1)   # 4 cycles across width
        amp = 0.35 + 0.15 * math.sin(t * 2.0)
        for x in range(w):
            phase = x * freq + t * 4.0
            y_a = int((math.sin(phase) * amp + 0.5) * (h - 1))
            y_b = int((math.sin(phase + math.pi) * amp + 0.5) * (h - 1))
            y_a = max(0, min(h - 1, y_a))
            y_b = max(0, min(h - 1, y_b))
            canvas.set(x, y_a)
            canvas.set(x, y_b)
        return canvas.frame()
