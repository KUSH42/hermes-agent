"""3D/special animation engines: WireframeCubeEngine, SierpinskiEngine, PlasmaEngine,
Torus3DEngine, MatrixRainEngine — plus Bresenham/Liang-Barsky helpers."""
from __future__ import annotations

import math
import random

from ._base import (
    AnimParams,
    TrailCanvas,
    _TORUS_TILT_COS,
    _TORUS_TILT_SIN,
    _BaseEngine,
    _depth_to_density,
    _lut_cos,
    _lut_sin,
    _make_canvas,
    _safe_dims,
)


# ── Bresenham + Liang-Barsky helpers ─────────────────────────────────────────

def _clip_segment(
    x0: int, y0: int, x1: int, y1: int, w: int, h: int
) -> tuple[int, int, int, int] | None:
    """Liang-Barsky clip segment to [0,w)×[0,h). Returns clipped endpoints or None."""
    dx, dy = x1 - x0, y1 - y0
    p = (-dx, dx, -dy, dy)
    q = (x0, (w - 1) - x0, y0, (h - 1) - y0)
    t0, t1 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0:
            if qi < 0:
                return None
        elif pi < 0:
            r = qi / pi
            if r > t1:
                return None
            if r > t0:
                t0 = r
        else:
            r = qi / pi
            if r < t0:
                return None
            if r < t1:
                t1 = r
    if t0 > t1:
        return None
    return (
        round(x0 + t0 * dx), round(y0 + t0 * dy),
        round(x0 + t1 * dx), round(y0 + t1 * dy),
    )


def _bresenham_pts(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    """Return integer pixel coords along segment (x0,y0)→(x1,y1) using Bresenham."""
    pts: list[tuple[int, int]] = []
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    x, y = x0, y0
    while True:
        pts.append((x, y))
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy
    return pts


# ── 3D/special engines ────────────────────────────────────────────────────────

class WireframeCubeEngine(_BaseEngine):
    """Rotating 3D wireframe cube with depth-sorted edge rendering."""

    _VERTS: list[tuple[float, float, float]] = [
        (-1, -1, -1), ( 1, -1, -1), ( 1,  1, -1), (-1,  1, -1),  # back face
        (-1, -1,  1), ( 1, -1,  1), ( 1,  1,  1), (-1,  1,  1),  # front face
    ]
    _EDGES: list[tuple[int, int]] = [
        (0, 1), (1, 2), (2, 3), (3, 0),   # back face
        (4, 5), (5, 6), (6, 7), (7, 4),   # front face
        (0, 4), (1, 5), (2, 6), (3, 7),   # connecting edges
    ]
    _BRAKE_DECAY: float = 0.92   # per-frame factor while braking
    _BRAKE_FLOOR: float = 0.05   # reset when factor falls below this

    def __init__(self) -> None:
        self._spin_brake: bool = False
        self._brake_factor: float = 1.0
        self._t_internal: float = 0.0

    def on_signal(self, signal: str, value: float = 1.0) -> None:
        if signal == "complete":
            self._spin_brake = True

    def next_frame(self, params: AnimParams) -> str:
        w, h = params.width, params.height
        cx, cy = w // 2, h // 2

        speed = (1.0 + params.heat * 2.0) * self._brake_factor
        self._t_internal += params.dt * speed
        t = self._t_internal
        ry = t * 1.5
        rx = t * 0.9

        if self._spin_brake:
            self._brake_factor *= self._BRAKE_DECAY
            if self._brake_factor < self._BRAKE_FLOOR:
                self._spin_brake = False
                self._brake_factor = 1.0

        cos_ry = math.cos(ry)
        sin_ry = math.sin(ry)
        cos_rx = math.cos(rx)
        sin_rx = math.sin(rx)

        scale = min(w, h) * 0.35

        proj: list[tuple[int, int]] = []
        rotated_z: list[float] = []
        for vx, vy, vz in self._VERTS:
            # Rotate around Y
            x2 = vx * cos_ry + vz * sin_ry
            z2 = -vx * sin_ry + vz * cos_ry
            # Rotate around X
            y3 = vy * cos_rx - z2 * sin_rx
            z3 = vy * sin_rx + z2 * cos_rx
            sx = cx + int(x2 * scale)
            sy = cy + int(y3 * scale * 0.5)
            proj.append((sx, sy))
            rotated_z.append(z3)

        # Build projected coords and mean_z per edge
        edge_data = []
        for i, j in self._EDGES:
            mean_z = (rotated_z[i] + rotated_z[j]) / 2
            edge_data.append((mean_z, i, j))
        edge_data.sort(key=lambda e: e[0])   # back-to-front

        canvas = _make_canvas()
        for mz, i, j in edge_data:
            seg = _clip_segment(proj[i][0], proj[i][1], proj[j][0], proj[j][1], w, h)
            if seg is None:
                continue
            cx0, cy0, cx1, cy1 = seg
            for px, py in _bresenham_pts(cx0, cy0, cx1, cy1):
                if params.depth_cues:
                    _depth_to_density(mz, canvas, px, py, w, h)
                else:
                    canvas.set(px, py)
        return canvas.frame()


class SierpinskiEngine(_BaseEngine):
    """Sierpinski triangle via iterated function system chaos game."""

    # Three affine maps each scale 0.5 toward one vertex of the unit triangle.
    _TRANSFORMS: tuple = (
        lambda x, y: (x * 0.5,        y * 0.5),
        lambda x, y: (x * 0.5 + 0.5,  y * 0.5),
        lambda x, y: (x * 0.5 + 0.25, y * 0.5 + 0.5),
    )
    _BURN_IN: int = 20  # discard first N iterations to escape off-attractor transients

    def __init__(self) -> None:
        self._x: float = 0.5
        self._y: float = 0.5
        self._trail = TrailCanvas(decay=0.7, threshold=0.25)
        self._w: int = 0
        self._h: int = 0

    def on_signal(self, signal: str, value: float = 1.0) -> None:
        if signal == "complete":
            self._trail._heat.clear()
            self._x = 0.5
            self._y = 0.5

    def next_frame(self, params: AnimParams) -> str:
        w, h = params.width, params.height
        if self._w != w or self._h != h:
            # Size changed — stale pixel coords pollute the canvas; reset trail.
            self._trail._heat.clear()
            self._w, self._h = w, h
        n_iters = 300 + int(params.heat * 400)
        x, y = self._x, self._y
        transforms = self._TRANSFORMS
        # burn-in: converge onto attractor before plotting
        for _ in range(self._BURN_IN):
            x, y = transforms[random.randint(0, 2)](x, y)
        for _ in range(n_iters):
            x, y = transforms[random.randint(0, 2)](x, y)
            px = int(x * (w - 1))
            py = int((1.0 - y) * (h - 1))  # flip Y so triangle points up
            self._trail.set(px, py)
        self._x, self._y = x, y
        return self._trail.frame()


class PlasmaEngine(_BaseEngine):
    """Classic demoscene plasma using summed sine fields."""

    def __init__(self) -> None:
        self._t_offset: float = 0.0

    def on_signal(self, signal: str, value: float = 1.0) -> None:
        if signal == "thinking":
            self._t_offset += 0.5
        elif signal == "complete":
            self._t_offset += 2.0

    def next_frame(self, params: AnimParams) -> str:
        canvas = _make_canvas()
        w, h = params.width, params.height
        t = params.t + self._t_offset
        ns = params.noise_scale
        w_inv = 1.0 / max(w - 1, 1)
        h_inv = 1.0 / max(h - 1, 1)
        threshold = params.trail_decay * 0.5

        # Frame-constant hoists
        t_13    = t * 1.3
        t_08    = t * 0.8
        t_15    = t * 1.5
        six_ns  = 6.0 * ns
        four_ns = 4.0 * ns
        eight_ns = 8.0 * ns
        five_ns = 5.0 * ns

        for yi in range(h):
            yf = yi * h_inv
            # Row-constant hoists
            y_sine2 = _lut_sin(yf * five_ns + t)
            yf_4ns  = yf * four_ns
            dy_sq   = (yf - 0.5) ** 2
            for xi in range(w):
                xf = xi * w_inv
                v  = _lut_sin(xf * six_ns + t_13)
                v += y_sine2
                v += _lut_sin(xf * four_ns + yf_4ns + t_08)
                r = math.sqrt(max((xf - 0.5) ** 2 + dy_sq, 0))
                v += _lut_sin(r * eight_ns + t_15)
                if v > threshold:
                    canvas.set(xi, yi)
        return canvas.frame()


class Torus3DEngine(_BaseEngine):
    """Rotating wireframe torus with depth-sorted ring rendering."""

    N_U: int = 20    # latitude rings
    N_V: int = 36    # points per ring
    R: float = 0.6   # major radius
    r: float = 0.25  # minor radius (tube)

    # Precomputed angle LUTs — class-level, computed once at import time.
    # Use literals (not N_U/N_V names) due to Python class scope rule.
    _THETA_LUT: list = [u * (2.0 * math.pi / 20) for u in range(20)]  # N_U=20
    _PHI_LUT:   list = [v * (2.0 * math.pi / 36) for v in range(36)]  # N_V=36

    def __init__(self) -> None:
        assert len(self._THETA_LUT) == self.N_U, (
            f"Torus3DEngine._THETA_LUT length {len(self._THETA_LUT)} != N_U={self.N_U}; "
            "update the LUT list comprehension to match"
        )
        assert len(self._PHI_LUT) == self.N_V, (
            f"Torus3DEngine._PHI_LUT length {len(self._PHI_LUT)} != N_V={self.N_V}; "
            "update the LUT list comprehension to match"
        )
        self._rot_dir: float = 1.0
        self._reverse_frames: int = 0

    def on_signal(self, signal: str, value: float = 1.0) -> None:
        if signal == "complete":
            self._rot_dir = -1.0
            self._reverse_frames = 10

    def next_frame(self, params: AnimParams) -> str:
        w, h = params.width, params.height
        canvas = _make_canvas()
        scale = min(w, h) * 0.4
        cx, cy = w // 2, h // 2
        speed = 1.0 + params.heat * 1.5

        rot_y = params.t * 1.2 * self._rot_dir * speed
        cos_ry = _lut_cos(rot_y)
        sin_ry = _lut_sin(rot_y)

        if self._reverse_frames > 0:
            self._reverse_frames -= 1
            if self._reverse_frames == 0:
                self._rot_dir = 1.0

        rings: list[tuple[list, float]] = []
        for u in range(self.N_U):
            theta = self._THETA_LUT[u]
            cos_th = _lut_cos(theta)
            sin_th = _lut_sin(theta)
            ring_pts = []
            ring_z_sum = 0.0
            for v in range(self.N_V):
                phi = self._PHI_LUT[v]
                r_cos_phi = self.r * _lut_cos(phi)
                x0 = (self.R + r_cos_phi) * cos_th
                y0 = (self.R + r_cos_phi) * sin_th
                z0 =  self.r * _lut_sin(phi)
                x1 =  x0 * cos_ry + z0 * sin_ry
                z1 = -x0 * sin_ry + z0 * cos_ry
                y2 = y0 * _TORUS_TILT_COS - z1 * _TORUS_TILT_SIN
                z2 = y0 * _TORUS_TILT_SIN + z1 * _TORUS_TILT_COS
                sx = cx + int(x1 * scale)
                sy = cy + int(y2 * scale * 0.5)
                ring_pts.append((sx, sy))
                ring_z_sum += z2
            rings.append((ring_pts, ring_z_sum / self.N_V))

        rings.sort(key=lambda r: r[1])
        for ring_pts, mean_z in rings:
            n = len(ring_pts)
            for k in range(n):
                x0, y0 = ring_pts[k]
                x1, y1 = ring_pts[(k + 1) % n]
                seg = _clip_segment(x0, y0, x1, y1, w, h)
                if seg is None:
                    continue
                cx0, cy0, cx1, cy1 = seg
                for px, py in _bresenham_pts(cx0, cy0, cx1, cy1):
                    if params.depth_cues:
                        _depth_to_density(mean_z, canvas, px, py, w, h)
                    else:
                        canvas.set(px, py)
        return canvas.frame()


class MatrixRainEngine(_BaseEngine):
    """Digital rain — falling columns of particles with heat-map trail decay."""

    def __init__(self) -> None:
        self._columns: list[dict] = []
        self._trail = TrailCanvas(decay=0.82, threshold=0.2)
        self._initialised: bool = False
        self._w = 0
        self._h = 0
        self._n_cols = 0
        self._complete_countdown: int = 0
        self._error_surge_frames: int = 0

    def on_signal(self, signal: str, value: float = 1.0) -> None:
        if signal == "error":
            self._error_surge_frames = 22
        elif signal == "complete":
            self._complete_countdown = 20

    def _init_columns(self, params: AnimParams) -> None:
        w, h = _safe_dims(params)
        # Size may have changed — clear stale trail pixels out of the old bounds.
        self._trail._heat.clear()
        speed_factor = 1.0 + params.heat * 3.0
        n_cols = max(4, w // 6)
        if params.particle_count > 60:
            n_cols = max(n_cols, params.particle_count // 6)
        self._columns = [
            {
                "x": random.randint(0, max(w - 1, 0)),
                "y": random.uniform(-h, 0),
                "speed": random.uniform(1.5, 4.0) * speed_factor,
                "intensity": random.uniform(0.6, 1.0),
            }
            for _ in range(n_cols)
        ]
        self._w = w
        self._h = h
        self._n_cols = n_cols
        self._initialised = True

    def next_frame(self, params: AnimParams) -> str:
        w, h = _safe_dims(params)
        speed_factor = 1.0 + params.heat * 3.0
        n_cols = max(4, w // 6)
        if params.particle_count > 60:
            n_cols = max(n_cols, params.particle_count // 6)

        if not self._initialised or self._w != w or self._h != h or self._n_cols != n_cols:
            self._init_columns(params)

        if self._error_surge_frames > 0:
            self._error_surge_frames -= 1

        for col in self._columns:
            effective_speed = 6.0 if self._error_surge_frames > 0 else col["speed"]
            col["y"] += effective_speed * params.dt * h
            yi = int(col["y"])
            x = col["x"]
            if 0 <= yi < h:
                self._trail.set(x, yi, col["intensity"])
            for offset in (1, 2):
                if 0 <= yi + offset < h:
                    self._trail.set(x, yi + offset, col["intensity"] * 0.4)
            if col["y"] > h + 5:
                col["y"] = random.uniform(-h * 0.3, 0)
                col["x"] = random.randint(0, max(w - 1, 0))
                col["speed"] = random.uniform(1.5, 4.0) * speed_factor
                col["intensity"] = random.uniform(0.6, 1.0)

        if self._complete_countdown > 0:
            self._complete_countdown -= 1
            if self._complete_countdown == 0:
                self._trail._heat.clear()
                self._initialised = False

        return self._trail.frame()
