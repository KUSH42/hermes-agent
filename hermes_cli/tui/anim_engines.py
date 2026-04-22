"""Animation engine classes for the Drawbraille overlay.

Extracted from drawbraille_overlay.py to keep widget/config/gallery code separate
from the math-heavy engine implementations.

All engine classes implement the AnimEngine protocol (next_frame(params) → str).
"""
from __future__ import annotations

import math
import math as _math
from hermes_cli.tui.braille_canvas import BrailleCanvas
import random
import time
from dataclasses import dataclass, field  # noqa: F401 (field kept for potential engine use)
from typing import Protocol, runtime_checkable

# ── Sine/cosine lookup tables (B1) ───────────────────────────────────────────
_LUT_SIZE = 1024
_LUT_SIZE_F = float(_LUT_SIZE)
_TWO_PI_INV = _LUT_SIZE / (2.0 * _math.pi)

_SIN_LUT: list[float] = [_math.sin(2.0 * _math.pi * i / _LUT_SIZE) for i in range(_LUT_SIZE)]
_COS_LUT: list[float] = [_math.cos(2.0 * _math.pi * i / _LUT_SIZE) for i in range(_LUT_SIZE)]

_BOID_CELL_SIZE: int = 20  # spatial grid cell size = max boid interaction radius

# Torus tilt constants (π/6 static X-axis tilt for Torus3DEngine)
_TORUS_TILT_COS: float = math.cos(math.pi / 6)  # ≈ 0.8660
_TORUS_TILT_SIN: float = math.sin(math.pi / 6)  # ≈ 0.5000


def _lut_sin(angle: float) -> float:
    return _SIN_LUT[int(angle * _TWO_PI_INV) % _LUT_SIZE]


def _lut_cos(angle: float) -> float:
    return _COS_LUT[int(angle * _TWO_PI_INV) % _LUT_SIZE]


# ── AnimParams ────────────────────────────────────────────────────────────────

@dataclass
class AnimParams:
    width: int   # braille pixel width  = terminal_cols × 2
    height: int  # braille pixel height = terminal_rows × 4
    t: float = 0.0
    dt: float = 1 / 15
    vertical: bool = False
    # SDF morph engine config (set once from DrawbrailleOverlayCfg)
    sdf_text: str = "HERMES"
    sdf_hold_ms: float = 900
    sdf_morph_ms: float = 700
    sdf_render_mode: str = "dissolve"
    sdf_font_size: int = 96
    sdf_dissolve_spread: float = 0.15
    sdf_outline_width: float = 0.08
    # v2 fields
    heat: float = 0.0
    trail_decay: float = 0.0
    symmetry: int = 6
    particle_count: int = 60
    noise_scale: float = 1.0
    depth_cues: bool = True
    blend_mode: str = "overlay"
    attractor_type: str = "lorenz"
    life_seed: str = "gosper"


# ── Engine protocol ───────────────────────────────────────────────────────────

@runtime_checkable
class AnimEngine(Protocol):
    def next_frame(self, params: AnimParams) -> str: ...


# Optional hook (not part of Protocol — checked via hasattr):
# def on_mount(self, overlay: "DrawbrailleOverlay") -> None:
#     """Called by DrawbrailleOverlay.on_mount after engine is selected.
#     Engines that need app access (e.g. for workers) implement this."""


# ── TrailCanvas ───────────────────────────────────────────────────────────────

class TrailCanvas:
    """Braille canvas with temporal persistence via heat-map decay.

    Each pixel has a float intensity [0..1]. Each tick, all intensities are
    multiplied by `decay`. Pixels below `threshold` are cleared from the
    rendered canvas. New set() calls reinforce (add) intensity clamped to 1.0.
    """

    def __init__(self, decay: float = 0.85, threshold: float = 0.3) -> None:
        self.decay = decay
        self.threshold = threshold
        self._heat: dict[tuple[int, int], float] = {}

    def set(self, x: int, y: int, intensity: float = 1.0) -> None:  # noqa: A003
        """Set or reinforce pixel at (x, y). Out-of-bounds silently ignored."""
        if x < 0 or y < 0:
            return
        key = (int(x), int(y))
        self._heat[key] = min(1.0, self._heat.get(key, 0.0) + intensity)

    def decay_all(self) -> None:
        """Multiply all intensities by decay factor; remove sub-threshold entries."""
        to_remove = []
        for k in self._heat:
            self._heat[k] *= self.decay
            if self._heat[k] < self.threshold:
                to_remove.append(k)
        for k in to_remove:
            del self._heat[k]

    def to_canvas(self) -> BrailleCanvas:
        """Apply threshold → BrailleCanvas with pixels set above threshold."""
        c = BrailleCanvas()
        for (x, y), intensity in self._heat.items():
            if intensity >= self.threshold:
                c.set(x, y)
        return c

    def frame(self) -> str:
        """decay_all() then return rendered braille frame."""
        self.decay_all()
        return self.to_canvas().frame()


# ── Helper utilities ──────────────────────────────────────────────────────────

def _make_canvas() -> BrailleCanvas:
    return BrailleCanvas()


def _make_trail_canvas(decay: float) -> "TrailCanvas | BrailleCanvas":
    """Return TrailCanvas if decay > 0, else BrailleCanvas."""
    if decay > 0:
        return TrailCanvas(decay=decay)
    return BrailleCanvas()


def _braille_density_set(canvas: object, x: int, y: int, intensity: float, w: int, h: int) -> None:
    """Set braille pixels in a 2×2 block around (x,y) proportional to intensity.

    intensity=1.0 → all 4 pixels, 0.5 → 2 pixels, 0.25 → 1 pixel.
    Out-of-bounds silently ignored.
    """
    if x < 0 or y < 0:
        return
    # Number of pixels to set: round(intensity * 4) clamped to [0,4]
    n = max(0, min(4, round(intensity * 4)))
    offsets = [(0, 0), (1, 0), (0, 1), (1, 1)]
    for ox, oy in offsets[:n]:
        if 0 <= x + ox < w and 0 <= y + oy < h:
            canvas.set(x + ox, y + oy)


def _depth_to_density(z: float, canvas: object, x: int, y: int, w: int, h: int) -> None:
    """Set braille pixels at (x,y) proportional to z-depth.

    z in [-1, 1] where 1 = closest (full density), -1 = farthest (sparse).
    density = 0.3 + (z + 1) / 2 * 0.7  → [0.3, 1.0]
    cells_to_set = round(density * 4)   → [1, 4] dots in 2×2 block
    """
    if x < 0 or y < 0:
        return
    density = 0.3 + (z + 1) / 2 * 0.7
    _braille_density_set(canvas, x, y, density, w, h)


# Non-reentrant: mutated in-place per call. Safe because _layer_frames is only
# called from the Textual event loop (single-threaded). Do not call from workers.
_LAYER_ROW_BUF: list[str] = []
_LAYER_RESULT_BUF: list[str] = []


def _layer_frames(frame_a: str, frame_b: str, mode: str, heat: float = 0.0) -> str:
    """Merge two canvas.frame() strings pixel-by-pixel using the given blend mode.

    Braille chars U+2800–U+28FF; ord(ch)-0x2800 = bitmask.
    Modes: additive (OR), overlay (upper=b non-zero wins), xor (XOR),
           dissolve (random weighted by heat; heat=0 → equal; heat=1 → b wins).
    Non-braille chars pass through from upper layer (b).
    """
    lines_a = frame_a.split("\n")
    lines_b = frame_b.split("\n")
    n_rows = max(len(lines_a), len(lines_b))

    t_int = int(time.monotonic() * 4)
    _LAYER_RESULT_BUF.clear()
    for r in range(n_rows):
        row_a = lines_a[r] if r < len(lines_a) else ""
        row_b = lines_b[r] if r < len(lines_b) else ""
        n_cols = max(len(row_a), len(row_b))
        _LAYER_ROW_BUF.clear()
        for c in range(n_cols):
            ca = row_a[c] if c < len(row_a) else " "
            cb = row_b[c] if c < len(row_b) else " "
            ma = 0x2800 <= ord(ca) <= 0x28FF
            mb = 0x2800 <= ord(cb) <= 0x28FF
            if not ma and not mb:
                _LAYER_ROW_BUF.append(cb if cb != " " else ca)
                continue
            ba = (ord(ca) - 0x2800) if ma else 0
            bb = (ord(cb) - 0x2800) if mb else 0
            if mode == "additive":
                bits = ba | bb
            elif mode == "xor":
                bits = ba ^ bb
            elif mode == "dissolve":
                # Deterministic spatial dither — crawls slowly, no per-frame flicker (D4)
                weight_b = 0.5 + heat * 0.5
                dither = (abs((c * 2654435761 ^ r * 2246822519 ^ t_int) & 0xFFFF) / 65535.0)
                bits = bb if dither < weight_b else ba
            else:  # overlay: upper (b) wins when non-zero
                bits = bb if bb != 0 else ba
            _LAYER_ROW_BUF.append(chr(0x2800 | bits))
        _LAYER_RESULT_BUF.append("".join(_LAYER_ROW_BUF))

    return "\n".join(_LAYER_RESULT_BUF)


def _easing(t: float, kind: str) -> float:
    """t ∈ [0,1] → eased value."""
    t = max(0.0, min(1.0, t))
    if kind == "sine":
        return 0.5 - math.cos(math.pi * t) / 2
    elif kind == "cubic":
        if t < 0.5:
            return 4 * t * t * t
        else:
            return 1 - ((-2 * t + 2) ** 3) / 2
    elif kind == "elastic":
        if t == 0 or t == 1:
            return t
        return (2 ** (-10 * t)) * math.sin((t * 10 - 0.75) * 2 * math.pi / 3) + 1
    else:  # none
        return t


# ── Base engine mixin ─────────────────────────────────────────────────────────

class _BaseEngine:
    """Mixin for all animation engines. Provides no-op on_signal."""
    def on_signal(self, signal: str, value: float = 1.0) -> None:
        pass


# ── Animation engines ─────────────────────────────────────────────────────────


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
    """3D helix projected orthographically and rotated."""

    def next_frame(self, params: AnimParams) -> str:
        canvas = _make_canvas()
        w, h = params.width, params.height
        t = params.t
        cx, cy = w // 2, h // 2
        # Scale point count with width so the helix stays dense at any size.
        # Angular step shrinks proportionally so total sweep (≈21.6 rad) stays fixed.
        n_pts = max(120, w * 2)
        a_step = 21.6 / n_pts    # keeps 3.4 rotations total
        d_step = 14.4 / n_pts
        y_step =  7.2 / n_pts
        for i in range(n_pts):
            angle = i * a_step + t * 3.0
            depth = math.cos(i * d_step + t * 1.5)
            x = cx + int(math.cos(angle) * (w * 0.4) * (0.7 + 0.3 * depth))
            y = cy + int(math.sin(i * y_step) * (h * 0.45))
            if 0 <= x < w and 0 <= y < h:
                canvas.set(x, y)
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


# ── New v2 stateful engines ───────────────────────────────────────────────────

class NeuralPulseEngine(_BaseEngine):
    """Directed graph of nodes; charge propagates and fires in cascades."""

    def __init__(self) -> None:
        self._nodes: list[tuple[float, float]] = []
        self._edges: dict[int, list[int]] = {}
        self._charge: list[float] = []
        self._fire_queue: list[int] = []
        self._edge_steps: dict[tuple[int, int], int] = {}
        self._init_done = False
        self._extra_fires = 0  # set by on_signal
        self._slow_decay_ticks: int = 0  # for "complete" slow-decay

    def _init(self, w: int, h: int, n: int) -> None:
        import random as _r
        self._nodes = [(_r.random() * w, _r.random() * h) for _ in range(n)]
        # knn graph k=3
        self._edges = {}
        for i, (ax, ay) in enumerate(self._nodes):
            dists = []
            for j, (bx, by) in enumerate(self._nodes):
                if i != j:
                    dists.append((math.hypot(ax - bx, ay - by), j))
            dists.sort()
            self._edges[i] = [j for _, j in dists[:3]]
        self._charge = [0.0] * n
        # Cache edge step lengths to avoid per-frame hypot recomputation
        self._edge_steps = {}
        for i, (ax, ay) in enumerate(self._nodes):
            for j in self._edges[i]:
                bx, by = self._nodes[j]
                self._edge_steps[(i, j)] = max(int(math.hypot(bx - ax, by - ay)), 1)
        self._init_done = True

    def on_signal(self, signal: str, value: float = 1.0) -> None:
        if signal == "thinking":
            self._extra_fires = int(value * 3)
        elif signal == "reasoning":
            self._extra_fires = 1
        elif signal == "tool":
            # Boost charge in random 5 nodes immediately
            if self._nodes:
                for _ in range(min(5, len(self._nodes))):
                    idx = random.randrange(len(self._nodes))
                    self._fire_queue.append(idx)
        elif signal == "complete":
            # Halve charge decay rate for 20 ticks (slow settle)
            self._slow_decay_ticks = 20
            self._fire_queue = list(range(len(self._nodes)))
        elif signal == "error":
            # Discharge all nodes → silence
            self._charge = [0.0] * len(self._charge)
            self._fire_queue = []

    def next_frame(self, params: AnimParams) -> str:
        w, h = params.width, params.height
        n = max(5, min(50, params.particle_count // 3))
        if not self._init_done or len(self._nodes) != n:
            self._init(w, h, n)
        canvas = _make_trail_canvas(params.trail_decay) if params.trail_decay > 0 else _make_canvas()

        fire_rate = 0.05 + params.heat * 0.3
        if random.random() < fire_rate:
            self._fire_queue.append(random.randrange(len(self._nodes)))
        for _ in range(self._extra_fires):
            self._fire_queue.append(random.randrange(len(self._nodes)))
        self._extra_fires = 0

        new_queue: list[int] = []
        for node_i in set(self._fire_queue):
            nx, ny = self._nodes[node_i]
            ix, iy = int(nx), int(ny)
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    if 0 <= ix + dx < w and 0 <= iy + dy < h:
                        canvas.set(ix + dx, iy + dy)
            for nb in self._edges.get(node_i, []):
                self._charge[nb] += 0.4
        self._fire_queue = []

        decay_rate = 0.4 if self._slow_decay_ticks > 0 else 0.8
        if self._slow_decay_ticks > 0:
            self._slow_decay_ticks -= 1
        for i, c in enumerate(self._charge):
            if c > 1.0:
                new_queue.append(i)
                self._charge[i] = 0.0
            else:
                self._charge[i] *= decay_rate
        self._fire_queue = new_queue

        # Draw edges
        for i, (ax, ay) in enumerate(self._nodes):
            for j in self._edges.get(i, []):
                bx, by = self._nodes[j]
                steps = self._edge_steps.get((i, j), 1)
                for s in range(0, steps, 2):
                    fx = ax + (bx - ax) * s / steps
                    fy = ay + (by - ay) * s / steps
                    if 0 <= int(fx) < w and 0 <= int(fy) < h:
                        canvas.set(int(fx), int(fy))

        return canvas.frame() if hasattr(canvas, "frame") else ""


class FlockSwarmEngine(_BaseEngine):
    """Reynolds boids with toroidal wrap and wandering attractor."""

    def __init__(self) -> None:
        self._boids: list[list[float]] = []  # [x, y, vx, vy]
        self._attractor = [0.0, 0.0]
        self._attr_vel = [0.5, 0.3]
        self._init_done = False
        self._scatter = False
        self._w: int = 0
        self._h: int = 0
        self._speed_modifier: float = 1.0
        self._grid: dict[tuple[int, int], list[int]] = {}

    def _init(self, w: int, h: int, n: int) -> None:
        self._boids = [
            [random.random() * w, random.random() * h,
             random.uniform(-1, 1), random.uniform(-1, 1)]
            for _ in range(n)
        ]
        self._attractor = [w / 2, h / 2]
        self._w = w
        self._h = h
        self._init_done = True

    def on_signal(self, signal: str, value: float = 1.0) -> None:
        if signal == "thinking":
            # Move attractor to center, reduce speed 30%
            if self._w > 0 and self._h > 0:
                self._attractor = [self._w / 2, self._h / 2]
            self._speed_modifier = 0.7
        elif signal == "reasoning":
            # Move attractor to top-center
            if self._w > 0 and self._h > 0:
                self._attractor = [self._w / 2, self._h / 4]
        elif signal == "tool":
            # Move attractor to random corner, boost speed 50%
            if self._w > 0 and self._h > 0:
                corner = random.randint(0, 3)
                corners = [
                    [0.0, 0.0],
                    [float(self._w), 0.0],
                    [0.0, float(self._h)],
                    [float(self._w), float(self._h)],
                ]
                self._attractor = corners[corner]
            self._speed_modifier = 1.5
        elif signal == "complete":
            self._scatter = True
            self._speed_modifier = 1.0
        elif signal == "error":
            # Scatter mode; double speed for 10 ticks
            self._scatter = True
            self._speed_modifier *= 2

    def next_frame(self, params: AnimParams) -> str:
        w, h = params.width, params.height
        n = max(5, min(100, params.particle_count))
        if not self._init_done or len(self._boids) != n:
            self._init(w, h, n)

        canvas = _make_trail_canvas(0.7) if params.trail_decay <= 0 else _make_trail_canvas(params.trail_decay)

        max_speed = (1.5 + params.heat * 3.0) * self._speed_modifier
        self._w = w
        self._h = h

        # Move attractor
        self._attractor[0] += self._attr_vel[0]
        self._attractor[1] += self._attr_vel[1]
        if self._attractor[0] < 0 or self._attractor[0] > w:
            self._attr_vel[0] *= -1
        if self._attractor[1] < 0 or self._attractor[1] > h:
            self._attr_vel[1] *= -1

        # Build spatial grid O(n) — reuse dict to avoid per-frame allocation.
        # Uses distinct loop variables (gi, boid) to avoid shadowing the outer
        # steering loop variables (i, b).
        self._grid.clear()
        for gi, boid in enumerate(self._boids):
            key = (int(boid[0] / _BOID_CELL_SIZE), int(boid[1] / _BOID_CELL_SIZE))
            cell = self._grid.get(key)
            if cell is None:
                self._grid[key] = [gi]
            else:
                cell.append(gi)
        # Max cell index for a pixel in [0, w-1] is (w-1)//cell_size; +1 gives count.
        _n_cols = max(1, (w - 1) // _BOID_CELL_SIZE + 1)
        _n_rows = max(1, (h - 1) // _BOID_CELL_SIZE + 1)
        # _n_cols/_n_rows are used by the steering loop below; compute once per frame.

        for i, b in enumerate(self._boids):
            if self._scatter:
                angle = random.random() * 2 * math.pi
                b[2] += math.cos(angle) * 3
                b[3] += math.sin(angle) * 3
                continue

            sep_x = sep_y = 0.0
            ali_x = ali_y = 0.0
            coh_x = coh_y = 0.0
            sep_n = ali_n = coh_n = 0

            bx_cell = int(b[0] / _BOID_CELL_SIZE)
            by_cell = int(b[1] / _BOID_CELL_SIZE)
            for _dc in (-1, 0, 1):
                for _dr in (-1, 0, 1):
                    _nc = bx_cell + _dc
                    _nr = by_cell + _dr
                    if _nc < 0 or _nc >= _n_cols or _nr < 0 or _nr >= _n_rows:
                        continue
                    for j in self._grid.get((_nc, _nr), ()):
                        if j == i:
                            continue
                        other = self._boids[j]
                        dx = other[0] - b[0]
                        dy = other[1] - b[1]
                        dist = math.hypot(dx, dy)
                        if dist < 8:
                            sep_x -= dx / max(dist, 0.1)
                            sep_y -= dy / max(dist, 0.1)
                            sep_n += 1
                        if dist < 16:
                            ali_x += other[2]
                            ali_y += other[3]
                            ali_n += 1
                        if dist < 20:
                            coh_x += other[0]
                            coh_y += other[1]
                            coh_n += 1

            if sep_n > 0:
                b[2] += sep_x / sep_n * 0.1
                b[3] += sep_y / sep_n * 0.1
            if ali_n > 0:
                b[2] += (ali_x / ali_n - b[2]) * 0.05
                b[3] += (ali_y / ali_n - b[3]) * 0.05
            if coh_n > 0:
                b[2] += (coh_x / coh_n - b[0]) * 0.01
                b[3] += (coh_y / coh_n - b[1]) * 0.01

            # Attractor pull
            ax, ay = self._attractor
            b[2] += (ax - b[0]) * 0.001
            b[3] += (ay - b[1]) * 0.001

        self._scatter = False

        for b in self._boids:
            spd = math.hypot(b[2], b[3])
            if spd > max_speed:
                b[2] = b[2] / spd * max_speed
                b[3] = b[3] / spd * max_speed
            b[0] = (b[0] + b[2]) % w
            b[1] = (b[1] + b[3]) % h
            if 0 <= int(b[0]) < w and 0 <= int(b[1]) < h:
                canvas.set(int(b[0]), int(b[1]))

        return canvas.frame() if hasattr(canvas, "frame") else ""


class ConwayLifeEngine(_BaseEngine):
    """Conway's Game of Life in braille pixel space, set-based."""

    _GOSPER_GUN = [
        (24, 0), (22, 1), (24, 1),
        (12, 2), (13, 2), (20, 2), (21, 2), (34, 2), (35, 2),
        (11, 3), (15, 3), (20, 3), (21, 3), (34, 3), (35, 3),
        (0, 4), (1, 4), (10, 4), (16, 4), (20, 4), (21, 4),
        (0, 5), (1, 5), (10, 5), (14, 5), (16, 5), (17, 5), (22, 5), (24, 5),
        (10, 6), (16, 6), (24, 6),
        (11, 7), (15, 7),
        (12, 8), (13, 8),
    ]
    _ACORN = [(0, 2), (1, 0), (1, 2), (3, 1), (4, 2), (5, 2), (6, 2)]
    _R_PENTOMINO = [(1, 0), (2, 0), (0, 1), (1, 1), (1, 2)]

    def __init__(self) -> None:
        self._alive: set[tuple[int, int]] = set()
        self._peak = 1
        self._ticks = 0
        self._gens_per_tick = 1
        self._init_done = False
        self._w = 0
        self._h = 0

    def _seed(self, seed: str, w: int, h: int) -> None:
        cx, cy = w // 2 - 18, h // 2 - 5
        if seed == "gosper":
            self._alive = {(cx + x, cy + y) for x, y in self._GOSPER_GUN}
        elif seed == "acorn":
            cx, cy = w // 2, h // 2
            self._alive = {(cx + x, cy + y) for x, y in self._ACORN}
        elif seed == "puffer":
            # Simple puffer (block + glider combos)
            self._alive = {(cx + x, cy + y) for x, y in self._GOSPER_GUN}
            for i in range(5):
                self._alive.add((cx + 40 + i * 3, cy + 5))
        else:  # random
            self._alive = {
                (random.randrange(w), random.randrange(h))
                for _ in range(w * h // 8)
            }

    def on_signal(self, signal: str, value: float = 1.0) -> None:
        if signal == "complete":
            self._gens_per_tick = max(1, self._ticks % 3)
        elif signal == "tool":
            self._gens_per_tick = 2
        elif signal == "error":
            # Re-seed with R-pentomino
            if self._w > 0 and self._h > 0:
                cx, cy = self._w // 2, self._h // 2
                self._alive = {((cx + x) % self._w, (cy + y) % self._h) for x, y in self._R_PENTOMINO}

    def _step(self, w: int, h: int) -> None:
        neighbor_counts: dict[tuple[int, int], int] = {}
        for cx, cy in self._alive:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nb = ((cx + dx) % w, (cy + dy) % h)
                    neighbor_counts[nb] = neighbor_counts.get(nb, 0) + 1
        new_alive: set[tuple[int, int]] = set()
        for cell, cnt in neighbor_counts.items():
            if cnt == 3 or (cnt == 2 and cell in self._alive):
                new_alive.add(cell)
        self._alive = new_alive

    def next_frame(self, params: AnimParams) -> str:
        w, h = params.width, params.height
        if not self._init_done or self._w != w or self._h != h:
            self._w, self._h = w, h
            self._seed(params.life_seed, w, h)
            self._init_done = True

        for _ in range(self._gens_per_tick):
            self._step(w, h)

        # Dead board reseed (D5)
        if len(self._alive) == 0 and self._ticks % 60 == 0:
            cx, cy = w // 2, h // 2
            self._alive = {
                (cx - 1, cy),
                (cx,     cy - 1),
                (cx,     cy),
                (cx,     cy + 1),
                (cx + 1, cy + 1),
            }

        # Anti-stagnation
        alive_count = len(self._alive)
        if alive_count > self._peak:
            self._peak = alive_count
        if self._peak > 0 and alive_count < self._peak * 0.05:
            rx, ry = random.randrange(w), random.randrange(h)
            for x, y in self._R_PENTOMINO:
                self._alive.add(((rx + x) % w, (ry + y) % h))
        if alive_count > w * h * 0.8:
            self._alive = {c for c in self._alive if random.random() < 0.5}

        self._ticks += 1
        canvas = _make_canvas()
        for x, y in self._alive:
            if 0 <= x < w and 0 <= y < h:
                canvas.set(x, y)
        return canvas.frame()


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
        self._init_done = True

    def next_frame(self, params: AnimParams) -> str:
        w, h = params.width, params.height
        n = min(200, params.particle_count * 3)
        if not self._init_done:
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
                    _lut_sin(fx * fk * 6.28 + t * sk) * _lut_cos(fy * fk * 6.28 + t * sk * 0.7)
                    for fk, sk in zip(freqs, speeds)
                ) / len(freqs)
                if val > threshold:
                    canvas.set(x, y)

        return canvas.frame() if hasattr(canvas, "frame") else ""


# ── New v2 mathematical engines ───────────────────────────────────────────────

class FluidFieldEngine(_BaseEngine):
    """Particles following curl-noise velocity field with TrailCanvas."""

    def __init__(self) -> None:
        self._particles: list[list[float]] = []  # [x, y, age]
        self._max_age = 60
        self._init_done = False

    def _init(self, w: int, h: int, n: int) -> None:
        self._particles = [
            [random.random() * w, random.random() * h, random.randint(0, self._max_age)]
            for _ in range(n)
        ]
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
        w, h = params.width, params.height
        n = min(200, params.particle_count)
        if not self._init_done or len(self._particles) != n:
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
        w, h = params.width, params.height
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


# ── Compositing engines ───────────────────────────────────────────────────────

class CompositeEngine:
    """Layers multiple engines and blends their frames."""

    def __init__(self, layers: list, blend_mode: str = "overlay") -> None:
        self.layers = layers
        self.blend_mode = blend_mode

    def next_frame(self, params: AnimParams) -> str:
        if not self.layers:
            return ""
        frames = [e.next_frame(params) for e in self.layers]
        result = frames[0]
        for f in frames[1:]:
            result = _layer_frames(result, f, self.blend_mode, params.heat)
        return result


class CrossfadeEngine:
    """Smooth crossfade transition between two engines."""

    def __init__(self, engine_a: object, engine_b: object, speed: float = 0.04) -> None:
        self.engine_a = engine_a
        self.engine_b = engine_b
        self.progress = 0.0
        self.speed = speed

    def next_frame(self, params: AnimParams) -> str:
        if self.progress >= 1.0:
            return self.engine_b.next_frame(params)
        fa = self.engine_a.next_frame(params)
        fb = self.engine_b.next_frame(params)
        self.progress = min(1.0, self.progress + self.speed)
        return _layer_frames(fa, fb, "overlay")


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


# ── New Part A engines ────────────────────────────────────────────────────────

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

    # Class-level constants — defined once; never recreated per frame.
    # Triangle IFS (symmetry < 4): Sierpinski triangle pointing up.
    _TRIANGLE_TRANSFORMS: tuple = (
        lambda x, y: (x * 0.5,        y * 0.5),
        lambda x, y: (x * 0.5 + 0.5,  y * 0.5),
        lambda x, y: (x * 0.5 + 0.25, y * 0.5 + 0.5),
    )
    # Square IFS (symmetry >= 4): Sierpinski carpet (default — AnimParams.symmetry=6).
    _SQUARE_TRANSFORMS: tuple = (
        lambda x, y: (x * 0.5,        y * 0.5),
        lambda x, y: (x * 0.5 + 0.5,  y * 0.5),
        lambda x, y: (x * 0.5,        y * 0.5 + 0.5),
        lambda x, y: (x * 0.5 + 0.5,  y * 0.5 + 0.5),
    )

    def __init__(self) -> None:
        self._x: float = 0.5
        self._y: float = 0.5
        self._trail = TrailCanvas(decay=0.7, threshold=0.25)

    def on_signal(self, signal: str, value: float = 1.0) -> None:
        if signal == "complete":
            self._trail._heat.clear()
            self._x = 0.5
            self._y = 0.5

    def next_frame(self, params: AnimParams) -> str:
        w, h = params.width, params.height
        use_square = params.symmetry >= 4
        n_iters = 250 + int(params.heat * 300)
        transforms = self._SQUARE_TRANSFORMS if use_square else self._TRIANGLE_TRANSFORMS
        n_t = len(transforms)
        for _ in range(n_iters):
            t_idx = random.randint(0, n_t - 1)
            self._x, self._y = transforms[t_idx](self._x, self._y)
            px = int(self._x * (w - 1))
            py = int((1.0 - self._y) * (h - 1))   # flip Y so triangle points up
            self._trail.set(px, py)
        return self._trail.frame()  # frame() calls decay_all() then renders


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
        self._complete_countdown: int = 0
        self._error_surge_frames: int = 0

    def on_signal(self, signal: str, value: float = 1.0) -> None:
        if signal == "error":
            self._error_surge_frames = 22
        elif signal == "complete":
            self._complete_countdown = 20

    def _init_columns(self, params: AnimParams) -> None:
        w, h = params.width, params.height
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
        self._initialised = True

    def next_frame(self, params: AnimParams) -> str:
        w, h = params.width, params.height
        speed_factor = 1.0 + params.heat * 3.0

        if not self._initialised:
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


# ── Engine registry + labels (no Textual dep — safe to import standalone) ────

ENGINES: dict[str, type] = {
    "dna":               DnaHelixEngine,
    "rotating":          RotatingHelixEngine,
    "classic":           ClassicHelixEngine,
    "morph":             MorphHelixEngine,
    "vortex":            VortexEngine,
    "wave":              WaveInterferenceEngine,
    "thick":             ThickHelixEngine,
    "kaleidoscope":      KaleidoscopeEngine,
    "neural_pulse":      NeuralPulseEngine,
    "flock_swarm":       FlockSwarmEngine,
    "conway_life":       ConwayLifeEngine,
    "strange_attractor": StrangeAttractorEngine,
    "hyperspace":        HyperspaceEngine,
    "perlin_flow":       PerlinFlowEngine,
    "fluid_field":       FluidFieldEngine,
    "lissajous_weave":   LissajousWeaveEngine,
    "aurora_ribbon":     AuroraRibbonEngine,
    "mandala_bloom":     MandalaBloomEngine,
    "rope_braid":        RopeBraidEngine,
    "wave_function":     WaveFunctionEngine,
    "wireframe_cube":    WireframeCubeEngine,
    "sierpinski":        SierpinskiEngine,
    "plasma":            PlasmaEngine,
    "torus_3d":          Torus3DEngine,
    "matrix_rain":       MatrixRainEngine,
}

ANIMATION_LABELS: dict[str, str] = {
    "dna":               "DNA Double Helix",
    "rotating":          "Rotating 3D Helix",
    "classic":           "Classic Triple Wave",
    "morph":             "Morphing Helix",
    "vortex":            "Vortex Spiral",
    "wave":              "Wave Interference",
    "thick":             "Thick Pulse",
    "kaleidoscope":      "Kaleidoscope",
    "sdf_morph":         "SDF Letter Morph",
    "neural_pulse":      "Neural Pulse",
    "fluid_field":       "Fluid Field",
    "lissajous_weave":   "Lissajous Weave",
    "aurora_ribbon":     "Aurora Ribbon",
    "mandala_bloom":     "Mandala Bloom",
    "flock_swarm":       "Flock Swarm",
    "conway_life":       "Conway Life",
    "rope_braid":        "Rope Braid",
    "perlin_flow":       "Perlin Flow",
    "hyperspace":        "Hyperspace",
    "wave_function":     "Wave Function",
    "strange_attractor": "Strange Attractor",
    "wireframe_cube":    "Wireframe Cube",
    "sierpinski":        "Sierpinski Triangle",
    "plasma":            "Plasma",
    "torus_3d":          "Torus 3D",
    "matrix_rain":       "Matrix Rain",
}
