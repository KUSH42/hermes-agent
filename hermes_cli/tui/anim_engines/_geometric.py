"""Geometric/pattern animation engines: KaleidoscopeEngine, ThickHelixEngine,
LissajousWeaveEngine, MandalaBloomEngine, AuroraRibbonEngine, WaveFunctionEngine, RopeBraidEngine."""
from __future__ import annotations

import math
import random

from ._base import (
    AnimParams,
    _BaseEngine,
    _braille_density_set,
    _depth_to_density,
    _easing,
    _lut_cos,
    _lut_sin,
    _make_canvas,
    _make_trail_canvas,
    _safe_dims,
)


class ThickHelixEngine(_BaseEngine):
    """Pulsing thick helix strand."""

    def next_frame(self, params: AnimParams) -> str:
        canvas = _make_canvas()
        w, h = params.width, params.height
        t = params.t
        freq = 8.0 * math.pi / max(w, 1)   # 4 cycles across width
        thickness = 1 + int(math.sin(t * 3.0) * 2 + 2)
        for x in range(w):
            phase = x * freq + t * 4.0
            y_center = int((math.sin(phase) + 1) * 0.5 * (h - 1))
            for dy in range(-thickness, thickness + 1):
                y = y_center + dy
                if 0 <= y < h:
                    canvas.set(x, y)
        return canvas.frame()


class KaleidoscopeEngine(_BaseEngine):
    """Radial triple spiral with kaleidoscope symmetry."""

    def next_frame(self, params: AnimParams) -> str:
        canvas = _make_canvas()
        w, h = params.width, params.height
        t = params.t
        cx, cy = w // 2, h // 2
        for arm in range(3):
            arm_offset = arm * (2 * math.pi / 3)
            for i in range(80):
                r = i * min(w, h) / 180
                theta = i * 0.22 + t * 3.0 + arm_offset
                x = cx + int(r * math.cos(theta))
                y = cy + int(r * math.sin(theta) * 0.5)
                if 0 <= x < w and 0 <= y < h:
                    canvas.set(x, y)
                # Mirror
                xm = 2 * cx - x
                if 0 <= xm < w and 0 <= y < h:
                    canvas.set(xm, y)
        return canvas.frame()


class LissajousWeaveEngine(_BaseEngine):
    """Multiple Lissajous curves with drifting a/b ratios."""

    def __init__(self) -> None:
        self._phase_jump = 0.0

    def on_signal(self, signal: str, value: float = 0.0) -> None:
        if signal == "tool":
            self._phase_jump = random.random() * math.pi

    def next_frame(self, params: AnimParams) -> str:
        w, h = params.width, params.height
        t = params.t
        n_strands = max(1, params.symmetry)
        canvas = _make_canvas()
        cx, cy = w / 2, h / 2

        for strand in range(n_strands):
            a0 = 2.0 + strand * 0.7
            b0 = 3.0 + strand * 0.5
            a = a0 + 0.1 * math.sin(t * 0.3 * (1 + params.heat))
            b = b0 + 0.1 * math.cos(t * 0.2)
            delta = strand * math.pi / n_strands + self._phase_jump

            steps = max(w * 4, 200)
            for i in range(steps):
                s = i / steps * 2 * math.pi
                x = cx + (w * 0.45) * _lut_sin(a * s + delta)
                y = cy + (h * 0.45) * _lut_sin(b * s)
                if 0 <= x < w and 0 <= y < h:
                    canvas.set(int(x), int(y))

        self._phase_jump *= 0.9  # decay phase jump
        return canvas.frame()


class MandalaBloomEngine(_BaseEngine):
    """N-fold radial symmetry using rhodonea rose curve."""

    def __init__(self) -> None:
        self._k = 3.0
        self._bloom_fast = False

    def on_signal(self, signal: str, value: float = 0.0) -> None:
        if signal == "complete":
            self._bloom_fast = True

    def next_frame(self, params: AnimParams) -> str:
        w, h = params.width, params.height
        t = params.t
        n = max(1, params.symmetry)
        cx, cy = w / 2, h / 2
        scale = min(w, h) * 0.45

        canvas = _make_canvas()

        speed = 0.05 + params.heat * 0.1
        if self._bloom_fast:
            speed = 0.5
        self._k += speed * 0.01
        if self._bloom_fast and (self._k % 1.0) < 0.1:
            self._bloom_fast = False

        A = 1.0
        B = 0.3
        steps = 200

        for fold in range(n):
            fold_angle = fold * 2 * math.pi / n
            sector_angle = 2 * math.pi / n
            for i in range(steps):
                theta = i / steps * sector_angle
                k = self._k
                r = (A * _lut_cos(k * theta + t * 0.5) + B * _lut_sin(theta * 2.3 + t * 0.7))
                r = abs(r) * scale
                total_angle = theta + fold_angle
                x = cx + r * _lut_cos(total_angle)
                y = cy + r * _lut_sin(total_angle) * 0.5
                if 0 <= x < w and 0 <= y < h:
                    canvas.set(int(x), int(y))

        # Center spiral
        for i in range(50):
            r = i * scale / 100
            angle = i * 0.5 + t
            x = cx + r * _lut_cos(angle)
            y = cy + r * _lut_sin(angle) * 0.5
            if 0 <= x < w and 0 <= y < h:
                canvas.set(int(x), int(y))

        return canvas.frame()


class AuroraRibbonEngine(_BaseEngine):
    """Horizontal ribbons with multi-octave sine stack and soft edges."""

    _OCTAVES = [(1.0, 0.8, 0.5), (2.0, 1.5, 0.3), (4.0, 3.0, 0.2)]

    def __init__(self) -> None:
        self._bands: int = 6
        self._bands_width: int = 0
        # Per-octave x-ramp cache: _x_phases[i][x] = freq_i * x/w * 2π
        # Invalidated when width changes — avoids recomputing static multiplies each frame.
        self._x_phases: list[list[float]] = []

    def _rebuild_cache(self, w: int) -> None:
        two_pi_over_w = 2 * math.pi / w
        self._x_phases = [
            [freq * x * two_pi_over_w for x in range(w)]
            for freq, _spd, _A in self._OCTAVES
        ]
        self._bands = max(6, w // 20)
        self._bands_width = w

    def next_frame(self, params: AnimParams) -> str:
        w, h = _safe_dims(params)
        t = params.t
        if self._bands_width != w:
            self._rebuild_cache(w)
        n_ribbons = max(2, min(self._bands, params.symmetry))
        canvas = _make_trail_canvas(params.trail_decay) if params.trail_decay > 0 else _make_canvas()

        ribbon_ys = [h * (i + 1) / (n_ribbons + 1) for i in range(n_ribbons)]

        # Repulsion spring
        for i in range(len(ribbon_ys)):
            for j in range(i + 1, len(ribbon_ys)):
                dy = ribbon_ys[j] - ribbon_ys[i]
                if abs(dy) < h / (n_ribbons + 1) * 0.7:
                    force = 0.5 * (1 - abs(dy) / (h / (n_ribbons + 1)))
                    ribbon_ys[i] -= force
                    ribbon_ys[j] += force

        octaves = self._OCTAVES
        x_phases = self._x_phases
        thickness = 2
        scale = (h / (n_ribbons + 1)) * 0.3

        for ri, base_y in enumerate(ribbon_ys):
            phase_offset = ri * 1.3
            xp0, xp1, xp2 = x_phases[0], x_phases[1], x_phases[2]
            (_, spd0, A0), (_, spd1, A1), (_, spd2, A2) = octaves
            t0 = spd0 * t + phase_offset
            t1 = spd1 * t + phase_offset
            t2 = spd2 * t + phase_offset
            for x in range(w):
                y_off = (
                    A0 * _lut_sin(xp0[x] + t0)
                    + A1 * _lut_sin(xp1[x] + t1)
                    + A2 * _lut_sin(xp2[x] + t2)
                ) * scale

                cy = base_y + y_off
                icy = int(cy)
                for dy in range(-thickness, thickness + 1):
                    ry = icy + dy
                    if 0 <= ry < h:
                        _braille_density_set(canvas, x, ry, 1.0 - abs(dy) / (thickness + 1), w, h)

        return canvas.frame() if hasattr(canvas, "frame") else ""


class WaveFunctionEngine(_BaseEngine):
    """Quantum wave packets with interference and collapse event."""

    def __init__(self) -> None:
        self._collapse = False
        self._collapse_t = 0.0
        self._packets = [
            {"x0": 0.3, "k0": 5.0, "sigma": 0.08, "omega": 3.0, "vx": 0.01, "vy": 0.005},
            {"x0": 0.5, "k0": 7.0, "sigma": 0.06, "omega": 4.5, "vx": -0.008, "vy": 0.007},
            {"x0": 0.7, "k0": 6.0, "sigma": 0.07, "omega": 3.8, "vx": 0.006, "vy": -0.009},
        ]
        self._pkt_px: list[float] = [0.3, 0.5, 0.7]  # pixel-space positions

    def on_signal(self, signal: str, value: float = 1.0) -> None:
        if signal == "complete":
            self._collapse = True
            self._collapse_t = 0.0

    def next_frame(self, params: AnimParams) -> str:
        w, h = params.width, params.height
        t = params.t
        canvas = _make_canvas()

        if self._collapse:
            self._collapse_t += params.dt

        # Update packet positions with reflection (D5)
        for i, pkt in enumerate(self._packets):
            px = self._pkt_px[i] * w * 2
            py = h * 2  # midpoint in pixel space
            px += pkt["vx"] * w * 2
            py += pkt["vy"] * h * 4
            # Reflect at braille pixel boundaries
            if px < 0:
                px = 0
                pkt["vx"] = abs(pkt["vx"])
            if px >= w * 2:
                px = w * 2 - 1
                pkt["vx"] = -abs(pkt["vx"])
            if py < 0:
                py = 0
                pkt["vy"] = abs(pkt["vy"])
            if py >= h * 4:
                py = h * 4 - 1
                pkt["vy"] = -abs(pkt["vy"])
            self._pkt_px[i] = px / max(w * 2, 1)

        w_m1_inv = 1.0 / max(w - 1, 1)
        for xi in range(w):
            x = xi * w_m1_inv
            psi_total = 0.0
            for i, pkt in enumerate(self._packets):
                x0 = self._pkt_px[i]
                sigma = pkt["sigma"]
                k0 = pkt["k0"]
                omega = pkt["omega"]
                envelope = math.exp(-((x - x0) ** 2) / (2 * sigma ** 2))
                carrier = math.cos(k0 * x * 6.28 - omega * t)

                if self._collapse and i > 0:
                    # Other packets collapse
                    envelope *= max(0, 1 - self._collapse_t * 3)
                elif self._collapse and i == 0:
                    # First packet spikes
                    spike = min(2.0, 1.0 + self._collapse_t * 5)
                    envelope *= spike

                psi = envelope * carrier
                psi_total += psi ** 2  # probability density

            # Render filled bar from baseline
            bar_h = int(abs(psi_total) * h * 0.8)
            bar_h = min(bar_h, h - 1)
            base_y = h - 1
            for yi in range(base_y - bar_h, base_y + 1):
                if 0 <= yi < h:
                    canvas.set(xi, yi)

        if self._collapse and self._collapse_t > 0.5:
            self._collapse = False

        return canvas.frame()


class RopeBraidEngine(_BaseEngine):
    """3 strands braiding in 3D with depth sorting and occlusion."""

    def __init__(self) -> None:
        self._unwind = False

    def on_signal(self, signal: str, value: float = 0.0) -> None:
        if signal == "complete":
            self._unwind = True

    def next_frame(self, params: AnimParams) -> str:
        w, h = params.width, params.height
        t = params.t
        canvas = _make_canvas()

        twist = 1.0 + params.heat * 2.0
        if self._unwind:
            twist = max(0.0, twist - 0.2)
            if twist <= 0.1:
                self._unwind = False

        # Braid period changes slowly
        lam = 20.0 + 5.0 * math.sin(t * 0.1)
        n_strands = 3

        for si in range(n_strands):
            phase = si * 2 * math.pi / n_strands
            strand_pts = []
            for x in range(0, w, 1):
                # Bezier easing at crossing points
                cross_phase = (x % lam) / lam
                ease = _easing(cross_phase, "cubic")
                braid_angle = (x / lam) * 2 * math.pi * twist + phase
                y_center = h / 2 + math.sin(braid_angle) * h * 0.3
                z = math.cos(braid_angle)  # z in [-1, 1]
                strand_pts.append((x, y_center, z))

            # Sort by z (back to front)
            for x, y, z in sorted(strand_pts, key=lambda p: p[2]):
                if 0 <= y < h and params.depth_cues:
                    _depth_to_density(z, canvas, int(x), int(y), w, h)
                elif 0 <= y < h:
                    canvas.set(int(x), int(y))

        return canvas.frame()
