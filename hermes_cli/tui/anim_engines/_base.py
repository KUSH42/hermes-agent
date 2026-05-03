"""Shared base types for animation engines: AnimParams, AnimEngine, TrailCanvas, _BaseEngine,
and all module-level helpers (LUTs, canvas utilities, easing, layer blending).
"""
from __future__ import annotations

import math
import math as _math
import random
import time
from dataclasses import dataclass, field  # noqa: F401 (field kept for potential engine use)
from typing import Protocol, runtime_checkable

from hermes_cli.tui.braille_canvas import BrailleCanvas

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


def _safe_dims(params: AnimParams) -> tuple[int, int]:
    """Return positive integer braille-pixel dimensions for engine math."""
    return max(1, int(params.width)), max(1, int(params.height))


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


def _layer_frames(frame_a: str, frame_b: str, mode: str, heat: float = 0.0) -> str:
    """Merge two canvas.frame() strings pixel-by-pixel using the given blend mode.

    Braille chars U+2800–U+28FF; ord(ch)-0x2800 = bitmask.
    Modes: additive (OR), overlay (upper=b non-zero wins), xor (XOR),
           dissolve (random weighted by heat; heat=0 → equal; heat=1 → b wins).
    Non-braille chars pass through from upper layer (b).
    """
    row_buf: list[str] = []
    result_buf: list[str] = []

    lines_a = frame_a.split("\n")
    lines_b = frame_b.split("\n")
    n_rows = max(len(lines_a), len(lines_b))

    t_int = int(time.monotonic() * 4)
    for r in range(n_rows):
        row_a = lines_a[r] if r < len(lines_a) else ""
        row_b = lines_b[r] if r < len(lines_b) else ""
        n_cols = max(len(row_a), len(row_b))
        row_buf.clear()
        for c in range(n_cols):
            ca = row_a[c] if c < len(row_a) else " "
            cb = row_b[c] if c < len(row_b) else " "
            ma = 0x2800 <= ord(ca) <= 0x28FF
            mb = 0x2800 <= ord(cb) <= 0x28FF
            if not ma and not mb:
                row_buf.append(cb if cb != " " else ca)
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
            row_buf.append(chr(0x2800 | bits))
        result_buf.append("".join(row_buf))

    return "\n".join(result_buf)


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
