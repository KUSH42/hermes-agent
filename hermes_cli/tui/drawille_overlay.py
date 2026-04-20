"""DrawilleOverlay — braille-canvas animation overlay + AnimConfigPanel.

Config-gated (display.drawille_overlay.enabled = false by default).
Plugs into AnimationClock; zero overhead when disabled.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.events import Resize
from textual.reactive import reactive
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Input, Static

from hermes_cli.tui.animation import AnimationClock, _ClockSubscription, lerp_color, _parse_rgb, lerp_color_rgb
from hermes_cli.tui.perf import measure

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp


# ── Config dataclass ──────────────────────────────────────────────────────────

@dataclass
class DrawilleOverlayCfg:
    enabled: bool = False
    animation: str = "dna"
    trigger: str = "agent_running"
    fps: int = 15
    position: str = "center"
    size: str = "medium"
    vertical: bool = False
    color: str = "$accent"
    gradient: bool = False
    color_secondary: str = "$primary"
    dim_background: bool = True
    show_border: bool = False
    border_style: str = "round"
    border_color: str = "$accent"
    auto_hide_delay: float = 0.0
    fade_in_frames: int = 3
    fade_out_frames: int = 0
    # Multi-color per-character strand coloring (N ≥ 1 stops).
    # When non-empty, overrides gradient/color/color_secondary.
    multi_color: list = None  # type: ignore[assignment]
    # Speed of hue-shift oscillation (rad/sec at 15 Hz).
    # 0.0 = static gradient; higher = faster drift.
    hue_shift_speed: float = 0.3
    # SDF morph engine settings
    sdf_text: str = "HERMES"
    sdf_hold_ms: float = 900
    sdf_morph_ms: float = 700
    sdf_render_mode: str = "dissolve"
    sdf_outline_width: float = 0.08
    sdf_dissolve_spread: float = 0.15
    sdf_font_size: int = 96
    # v2 compositing
    blend_mode: str = "overlay"
    layer_b: str = ""
    crossfade_speed: float = 0.04
    # v2 temporal trail
    trail_decay: float = 0.0
    # v2 adaptive
    adaptive: bool = False
    adaptive_metric: str = "token_rate"
    # v2 particle engines
    particle_count: int = 60
    # v2 symmetry / structure
    symmetry: int = 6
    noise_scale: float = 1.0
    depth_cues: bool = True
    attractor_type: str = "lorenz"
    life_seed: str = "gosper"
    # v2 easing
    ease_in: str = "sine"
    ease_out: str = "sine"
    # v2 carousel
    carousel: bool = False
    carousel_interval_s: float = 8.0
    # sdf crossfade warmup
    sdf_warmup_engine: str = "neural_pulse"
    sdf_crossfade_speed: float = 0.03
    # sdf baker timeout
    sdf_bake_timeout_s: float = 5.0

    def __post_init__(self) -> None:
        if self.multi_color is None:
            self.multi_color = []


def _overlay_config() -> DrawilleOverlayCfg:
    """Read current overlay config from disk. Not cached — reads each call.

    Uses read_raw_config() to avoid ensure_hermes_home() side effect during tests.
    Falls back to empty dict if config file missing.
    """
    try:
        from hermes_cli.config import read_raw_config
        d = read_raw_config().get("display", {}).get("drawille_overlay", {})
    except Exception:
        d = {}
    raw_mc = d.get("multi_color", [])
    multi_color = [str(c) for c in raw_mc] if isinstance(raw_mc, list) else []
    return DrawilleOverlayCfg(
        enabled=bool(d.get("enabled", False)),
        animation=str(d.get("animation", "dna")),
        trigger=str(d.get("trigger", "agent_running")),
        fps=int(d.get("fps", 15)),
        position=str(d.get("position", "top-right")),
        size=str(d.get("size", "medium")),
        vertical=bool(d.get("vertical", True)),
        color=str(d.get("color", "$accent")),
        gradient=bool(d.get("gradient", False)),
        color_secondary=str(d.get("color_secondary", "$primary")),
        dim_background=bool(d.get("dim_background", True)),
        show_border=bool(d.get("show_border", False)),
        border_style=str(d.get("border_style", "round")),
        border_color=str(d.get("border_color", "$accent")),
        auto_hide_delay=float(d.get("auto_hide_delay", 0)),
        fade_in_frames=int(d.get("fade_in_frames", 3)),
        fade_out_frames=int(d.get("fade_out_frames", 0)),
        multi_color=multi_color,
        hue_shift_speed=float(d.get("hue_shift_speed", 0.3)),
        sdf_text=str(d.get("sdf_text", "HERMES")),
        sdf_hold_ms=float(d.get("sdf_hold_ms", 900)),
        sdf_morph_ms=float(d.get("sdf_morph_ms", 700)),
        sdf_render_mode=str(d.get("sdf_render_mode", "dissolve")),
        sdf_outline_width=float(d.get("sdf_outline_width", 0.08)),
        sdf_dissolve_spread=float(d.get("sdf_dissolve_spread", 0.15)),
        sdf_font_size=int(d.get("sdf_font_size", 96)),
        blend_mode=str(d.get("blend_mode", "overlay")),
        layer_b=str(d.get("layer_b", "")),
        crossfade_speed=float(d.get("crossfade_speed", 0.04)),
        trail_decay=float(d.get("trail_decay", 0.0)),
        adaptive=bool(d.get("adaptive", False)),
        adaptive_metric=str(d.get("adaptive_metric", "token_rate")),
        particle_count=int(d.get("particle_count", 60)),
        symmetry=int(d.get("symmetry", 6)),
        noise_scale=float(d.get("noise_scale", 1.0)),
        depth_cues=bool(d.get("depth_cues", True)),
        attractor_type=str(d.get("attractor_type", "lorenz")),
        life_seed=str(d.get("life_seed", "gosper")),
        ease_in=str(d.get("ease_in", "sine")),
        ease_out=str(d.get("ease_out", "sine")),
        carousel=bool(d.get("carousel", False)),
        carousel_interval_s=float(d.get("carousel_interval_s", 8.0)),
        sdf_warmup_engine=str(d.get("sdf_warmup_engine", "neural_pulse")),
        sdf_crossfade_speed=float(d.get("sdf_crossfade_speed", 0.03)),
        sdf_bake_timeout_s=float(d.get("sdf_bake_timeout_s", 5.0)),
    )


# ── Color resolution ──────────────────────────────────────────────────────────

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    """'#rrggbb' → (r, g, b) integers."""
    h = h.lstrip("#")
    if len(h) == 3:
        h = h[0]*2 + h[1]*2 + h[2]*2
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return r, g, b


def _resolve_color(value: str, app: object, dim: float = 1.0) -> str:
    """Resolve TCSS var ref, named color, or hex → '#rrggbb' string.

    'auto' maps to '$accent' (resolved via CSS vars).
    dim ∈ [0,1] multiplies each RGB channel — used for fade-out.
    """
    if value == "auto":
        value = "$accent"
    if value.startswith("$"):
        var_name = value[1:]
        try:
            css_vars: dict[str, str] = app.get_css_variables()  # type: ignore[attr-defined]
            raw = css_vars.get(var_name, "")
            if raw and raw.startswith("#") and len(raw) in (4, 7):
                resolved_hex = raw if len(raw) == 7 else _expand_short_hex(raw)
            elif raw:
                resolved_hex = _rich_to_hex(raw)
            else:
                resolved_hex = "#00d7ff"
        except Exception:
            resolved_hex = "#00d7ff"
    else:
        resolved_hex = _rich_to_hex(value)

    if dim < 1.0:
        r, g, b = _hex_to_rgb(resolved_hex)
        r, g, b = int(r * dim), int(g * dim), int(b * dim)
        return f"#{r:02x}{g:02x}{b:02x}"
    return resolved_hex


def _expand_short_hex(h: str) -> str:
    """#abc → #aabbcc."""
    h = h.lstrip("#")
    return f"#{h[0]*2}{h[1]*2}{h[2]*2}"


def _rich_to_hex(value: str) -> str:
    try:
        from rich.color import Color as RichColor
        triplet = RichColor.parse(value).get_truecolor()
        return f"#{triplet.red:02x}{triplet.green:02x}{triplet.blue:02x}"
    except Exception:
        return "#00d7ff"


# ── AnimParams ────────────────────────────────────────────────────────────────

@dataclass
class AnimParams:
    width: int   # braille pixel width  = terminal_cols × 2
    height: int  # braille pixel height = terminal_rows × 4
    t: float = 0.0
    dt: float = 1 / 15
    vertical: bool = False
    # SDF morph engine config (set once from DrawilleOverlayCfg)
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
# def on_mount(self, overlay: "DrawilleOverlay") -> None:
#     """Called by DrawilleOverlay.on_mount after engine is selected.
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

    def to_canvas(self) -> object:
        """Apply threshold → drawille Canvas with pixels set above threshold."""
        import drawille
        c = drawille.Canvas()
        for (x, y), intensity in self._heat.items():
            if intensity >= self.threshold:
                try:
                    c.set(x, y)
                except Exception:
                    pass
        return c

    def frame(self) -> str:
        """decay_all() then return to_canvas().frame()."""
        self.decay_all()
        return self.to_canvas().frame()


# ── Helper utilities ──────────────────────────────────────────────────────────

def _make_canvas() -> object:
    import drawille
    return drawille.Canvas()


def _make_trail_canvas(decay: float) -> object:
    """Return TrailCanvas if decay > 0, else standard drawille.Canvas."""
    if decay > 0:
        return TrailCanvas(decay=decay)
    return _make_canvas()


def _braille_density_set(canvas: object, x: int, y: int, intensity: float) -> None:
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
        try:
            canvas.set(x + ox, y + oy)
        except Exception:
            pass


def _depth_to_density(z: float, canvas: object, x: int, y: int) -> None:
    """Set braille pixels at (x,y) proportional to z-depth.

    z in [-1, 1] where 1 = closest (full density), -1 = farthest (sparse).
    density = 0.3 + (z + 1) / 2 * 0.7  → [0.3, 1.0]
    cells_to_set = round(density * 4)   → [1, 4] dots in 2×2 block
    """
    if x < 0 or y < 0:
        return
    density = 0.3 + (z + 1) / 2 * 0.7
    _braille_density_set(canvas, x, y, density)


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
    result_rows: list[str] = []

    t_int = int(time.monotonic() * 4)
    for r in range(n_rows):
        row_a = lines_a[r] if r < len(lines_a) else ""
        row_b = lines_b[r] if r < len(lines_b) else ""
        n_cols = max(len(row_a), len(row_b))
        merged = []
        for c in range(n_cols):
            ca = row_a[c] if c < len(row_a) else " "
            cb = row_b[c] if c < len(row_b) else " "
            ma = 0x2800 <= ord(ca) <= 0x28FF
            mb = 0x2800 <= ord(cb) <= 0x28FF
            if not ma and not mb:
                merged.append(cb if cb != " " else ca)
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
            merged.append(chr(0x2800 | bits))
        result_rows.append("".join(merged))

    return "\n".join(result_rows)


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
            for y in range(h):
                phase = y * 0.25 + t * 4.0
                x_a = int((math.sin(phase) + 1) * 0.5 * (w - 1))
                x_b = int((math.sin(phase + math.pi) + 1) * 0.5 * (w - 1))
                canvas.set(x_a, y)
                canvas.set(x_b, y)
                if y % 8 == 0:
                    x_lo, x_hi = min(x_a, x_b), max(x_a, x_b)
                    for x in range(x_lo, x_hi + 1, 2):
                        canvas.set(x, y)
        else:
            for x in range(w):
                phase = x * 0.25 + t * 4.0
                y_a = int((math.sin(phase) + 1) * 0.5 * (h - 1))
                y_b = int((math.sin(phase + math.pi) + 1) * 0.5 * (h - 1))
                canvas.set(x, y_a)
                canvas.set(x, y_b)
                if x % 8 == 0:
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
        for i in range(120):
            angle = i * 0.18 + t * 3.0
            depth = math.cos(i * 0.12 + t * 1.5)
            x = cx + int(math.cos(angle) * (w * 0.4) * (0.7 + 0.3 * depth))
            y = cy + int(math.sin(i * 0.06) * (h * 0.45))
            if 0 <= x < w and 0 <= y < h:
                canvas.set(x, y)
        return canvas.frame()


class ClassicHelixEngine(_BaseEngine):
    """Three sine waves scrolling horizontally."""

    def next_frame(self, params: AnimParams) -> str:
        canvas = _make_canvas()
        w, h = params.width, params.height
        t = params.t
        for x in range(w):
            for phase_offset in (0.0, 2.1, 4.2):
                y = int((math.sin(x * 0.2 + t * 5.0 + phase_offset) + 1) * 0.5 * (h - 1))
                canvas.set(x, y)
        return canvas.frame()


class MorphHelixEngine(_BaseEngine):
    """Helix with breathing amplitude modulation."""

    def next_frame(self, params: AnimParams) -> str:
        canvas = _make_canvas()
        w, h = params.width, params.height
        t = params.t
        amp = 0.35 + 0.15 * math.sin(t * 2.0)
        for x in range(w):
            phase = x * 0.25 + t * 4.0
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
        threshold = 0.7
        for y in range(0, h, 2):
            for x in range(0, w, 1):
                da = math.sqrt((x - src_ax) ** 2 + (y - src_ay) ** 2)
                db = math.sqrt((x - src_bx) ** 2 + (y - src_by) ** 2)
                val = math.sin(da * 0.4 - t * 5) + math.sin(db * 0.4 - t * 5)
                if val > threshold:
                    canvas.set(x, y)
        return canvas.frame()


class ThickHelixEngine(_BaseEngine):
    """Pulsing thick helix strand."""

    def next_frame(self, params: AnimParams) -> str:
        canvas = _make_canvas()
        w, h = params.width, params.height
        t = params.t
        thickness = 1 + int(math.sin(t * 3.0) * 2 + 2)
        for x in range(w):
            phase = x * 0.25 + t * 4.0
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
        self._init_done = True

    def on_signal(self, signal: str, value: float = 1.0) -> None:
        if signal == "thinking":
            self._extra_fires = int(value * 3)
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
                    try:
                        canvas.set(ix + dx, iy + dy)
                    except Exception:
                        pass
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
                steps = max(int(math.hypot(bx - ax, by - ay)), 1)
                for s in range(0, steps, 2):
                    fx = ax + (bx - ax) * s / steps
                    fy = ay + (by - ay) * s / steps
                    try:
                        canvas.set(int(fx), int(fy))
                    except Exception:
                        pass

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

            for j, other in enumerate(self._boids):
                if i == j:
                    continue
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
            try:
                canvas.set(int(b[0]), int(b[1]))
            except Exception:
                pass

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
            try:
                canvas.set(x, y)
            except Exception:
                pass
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
        self._dt_default: float = 0.01

    def on_signal(self, signal: str, value: float = 1.0) -> None:
        if signal == "complete":
            # Halve dt for 40 ticks, creating slow settle
            self._slow_dt_ticks = 40
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
                    _braille_density_set(canvas, ix, iy, 1.0 - sz)
                else:
                    try:
                        canvas.set(ix, iy)
                    except Exception:
                        pass
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

        for y in range(0, h, 2):
            for x in range(0, w, 1):
                fx = x / max(w, 1)
                fy = y / max(h, 1)
                val = sum(
                    math.sin(fx * fk * 6.28 + t * sk) * math.cos(fy * fk * 6.28 + t * sk * 0.7)
                    for fk, sk in zip(freqs, speeds)
                ) / len(freqs)
                if val > threshold:
                    try:
                        canvas.set(x, y)
                    except Exception:
                        pass

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

        for p in self._particles:
            px, py, age = p
            cx, cy = self._curl(px / max(w, 1), py / max(h, 1), params.t, params.noise_scale)
            p[0] = (px + cx * vel_mult) % w
            p[1] = (py + cy * vel_mult) % h
            p[2] = age + 1
            if p[2] > self._max_age:
                p[0] = random.random() * w
                p[1] = random.random() * h
                p[2] = 0
            try:
                canvas.set(int(p[0]), int(p[1]))
            except Exception:
                pass

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
                x = cx + (w * 0.45) * math.sin(a * s + delta)
                y = cy + (h * 0.45) * math.sin(b * s)
                if 0 <= x < w and 0 <= y < h:
                    try:
                        canvas.set(int(x), int(y))
                    except Exception:
                        pass

        self._phase_jump *= 0.9  # decay phase jump
        return canvas.frame()


class AuroraRibbonEngine(_BaseEngine):
    """Horizontal ribbons with multi-octave sine stack and soft edges."""

    def __init__(self) -> None:
        self._bands: int = 6
        self._bands_width: int = 0

    def next_frame(self, params: AnimParams) -> str:
        w, h = params.width, params.height
        t = params.t
        # D5: dynamic bands based on terminal width
        if not self._bands_width or self._bands_width != w:
            self._bands = max(6, w // 20)
            self._bands_width = w
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

        octaves = [(1.0, 0.8, 0.5), (2.0, 1.5, 0.3), (4.0, 3.0, 0.2)]
        thickness = 2

        for ri, base_y in enumerate(ribbon_ys):
            phase_offset = ri * 1.3
            for x in range(w):
                y_off = sum(
                    A * math.sin(freq * x / w * 2 * math.pi + spd * t + phase_offset)
                    for freq, spd, A in octaves
                ) * (h / (n_ribbons + 1)) * 0.3

                cy = base_y + y_off
                # Soft edge with density
                for dy in range(-thickness, thickness + 1):
                    ry = int(cy) + dy
                    intensity = 1.0 - abs(dy) / (thickness + 1)
                    if 0 <= ry < h:
                        _braille_density_set(canvas, x, ry, intensity)

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
                r = (A * math.cos(k * theta + t * 0.5) + B * math.sin(theta * 2.3 + t * 0.7))
                r = abs(r) * scale
                total_angle = theta + fold_angle
                x = cx + r * math.cos(total_angle)
                y = cy + r * math.sin(total_angle) * 0.5
                if 0 <= x < w and 0 <= y < h:
                    try:
                        canvas.set(int(x), int(y))
                    except Exception:
                        pass

        # Center spiral
        for i in range(50):
            r = i * scale / 100
            angle = i * 0.5 + t
            x = cx + r * math.cos(angle)
            y = cy + r * math.sin(angle) * 0.5
            if 0 <= x < w and 0 <= y < h:
                try:
                    canvas.set(int(x), int(y))
                except Exception:
                    pass

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
                    _depth_to_density(z, canvas, int(x), int(y))
                elif 0 <= y < h:
                    try:
                        canvas.set(int(x), int(y))
                    except Exception:
                        pass

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

        for xi in range(w):
            x = xi / max(w - 1, 1)
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
                    try:
                        canvas.set(xi, yi)
                    except Exception:
                        pass

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


# ── Engine registry (class refs — instantiated per DrawilleOverlay session) ────

_ENGINES: dict[str, type] = {
    "dna":               DnaHelixEngine,
    "rotating":          RotatingHelixEngine,
    "classic":           ClassicHelixEngine,
    "morph":             MorphHelixEngine,
    "vortex":            VortexEngine,
    "wave":              WaveInterferenceEngine,
    "thick":             ThickHelixEngine,
    "kaleidoscope":      KaleidoscopeEngine,
    # v2 stateful engines
    "neural_pulse":      NeuralPulseEngine,
    "flock_swarm":       FlockSwarmEngine,
    "conway_life":       ConwayLifeEngine,
    "strange_attractor": StrangeAttractorEngine,
    "hyperspace":        HyperspaceEngine,
    "perlin_flow":       PerlinFlowEngine,
    # v2 mathematical engines
    "fluid_field":       FluidFieldEngine,
    "lissajous_weave":   LissajousWeaveEngine,
    "aurora_ribbon":     AuroraRibbonEngine,
    "mandala_bloom":     MandalaBloomEngine,
    "rope_braid":        RopeBraidEngine,
    "wave_function":     WaveFunctionEngine,
}

# ── Contextual SDF tool label map (C1) ────────────────────────────────────────

_TOOL_SDF_LABELS: dict[str, str] = {
    "Read":          "reading",
    "Write":         "writing",
    "Edit":          "editing",
    "Bash":          "running",
    "Glob":          "scanning",
    "Grep":          "scanning",
    "WebSearch":     "searching",
    "WebFetch":      "fetching",
    "Agent":         "delegating",
    # snake_case variants (API may use either)
    "read_file":     "reading",
    "write_file":    "writing",
    "edit_file":     "editing",
    "bash":          "running",
    "glob":          "scanning",
    "grep":          "scanning",
    "web_search":    "searching",
    "web_fetch":     "fetching",
    "":              "thinking",
}


ANIMATION_KEYS: list[str] = list(_ENGINES.keys()) + ["sdf_morph"]
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
    # v2
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
}

# ── Engine metadata (B2 / E1) ─────────────────────────────────────────────────

_ENGINE_META: dict[str, dict] = {
    # Classic
    "dna":               {"category": "Classic",      "desc": "DNA double helix with phosphate rungs"},
    "rotating":          {"category": "Classic",      "desc": "3D helix projection, continuously rotating"},
    "classic":           {"category": "Classic",      "desc": "Three sine waves scrolling horizontally"},
    "morph":             {"category": "Classic",      "desc": "Helix with breathing amplitude modulation"},
    "vortex":            {"category": "Classic",      "desc": "Zooming inward spiral vortex"},
    "wave":              {"category": "Classic",      "desc": "Two-source sine interference pattern"},
    "thick":             {"category": "Classic",      "desc": "Pulsing thick helix strand"},
    "kaleidoscope":      {"category": "Classic",      "desc": "Radial triple spiral, kaleidoscope symmetry"},
    # Organic
    "neural_pulse":      {"category": "Organic",      "desc": "Directed graph with charge cascades"},
    "flock_swarm":       {"category": "Organic",      "desc": "Reynolds boids with wandering attractor"},
    "conway_life":       {"category": "Organic",      "desc": "Conway's Game of Life in braille space"},
    "strange_attractor": {"category": "Organic",      "desc": "Lorenz/Rössler attractor with RK4 integration"},
    "hyperspace":        {"category": "Organic",      "desc": "Star field perspective projection"},
    "perlin_flow":       {"category": "Organic",      "desc": "Particles following curl-noise velocity field"},
    # Mathematical
    "fluid_field":       {"category": "Mathematical", "desc": "Particles in curl-noise velocity field"},
    "lissajous_weave":   {"category": "Mathematical", "desc": "Multiple Lissajous curves with drifting ratios"},
    "aurora_ribbon":     {"category": "Mathematical", "desc": "Horizontal ribbons with multi-octave sine"},
    "mandala_bloom":     {"category": "Mathematical", "desc": "N-fold radial rhodonea rose symmetry"},
    "rope_braid":        {"category": "Mathematical", "desc": "Three strands braiding in 3D with depth sort"},
    "wave_function":     {"category": "Mathematical", "desc": "Quantum wave packets with interference"},
    # Premium (sdf_morph handled via _get_sdf_engine)
    "sdf_morph":         {"category": "Premium",      "desc": "Typographic SDF letter morphing \u2726"},
}


# ── DrawilleOverlay ───────────────────────────────────────────────────────────

class DrawilleOverlay(Static):
    """Braille-canvas animation overlay shown during agent activity.

    Shown/hidden by ``show()`` / ``hide()`` called from
    ``HermesApp.watch_agent_running()``.  Plugs into the shared
    ``AnimationClock`` (no extra timers).
    """

    COMPONENT_CLASSES = {
        "drawille-overlay--canvas",
        "drawille-overlay--border",
    }

    DEFAULT_CSS = """
    DrawilleOverlay {
        display: none;
        width: 12;
        height: 22;
        offset: 0 0;
        min-width: 8;
        min-height: 4;
        padding: 0;
    }
    DrawilleOverlay.-visible {
        display: block;
    }
    """

    animation:       reactive[str]  = reactive("dna")
    color:           reactive[str]  = reactive("$accent")
    fps:             reactive[int]  = reactive(15)
    position:        reactive[str]  = reactive("center")
    size_name:       reactive[str]  = reactive("medium")
    gradient:        reactive[bool] = reactive(False)
    color_b:         reactive[str]  = reactive("$primary")
    dim_bg:          reactive[bool] = reactive(True)
    show_border:     reactive[bool] = reactive(False)
    vertical:        reactive[bool] = reactive(False)
    # Multi-color strand coloring — list of hex strings.
    # reactive(list) uses factory form to avoid shared mutable default.
    multi_color:     reactive[list] = reactive(list)
    hue_shift_speed: reactive[float] = reactive(0.3)
    # v2 reactive attrs
    trail_decay:     reactive[float] = reactive(0.0)
    adaptive:        reactive[bool]  = reactive(False)
    particle_count:  reactive[int]   = reactive(60)
    symmetry:        reactive[int]   = reactive(6)
    blend_mode:      reactive[str]   = reactive("overlay")
    layer_b:         reactive[str]   = reactive("")
    attractor_type:  reactive[str]   = reactive("lorenz")
    life_seed:       reactive[str]   = reactive("gosper")
    depth_cues:      reactive[bool]  = reactive(True)

    _anim_handle: "_ClockSubscription | Timer | None" = None
    _anim_params: "AnimParams | None" = None
    _resolved_color: str = "#00d7ff"
    _resolved_color_b: str = "#8800ff"
    _resolved_multi_colors: list = []   # pre-resolved hex strings; set by watch_multi_color
    _resolved_multi_color_rgbs: list | None = None  # pre-parsed RGB tuples — avoids per-frame _parse_rgb lookups
    _fade_step: int = 0
    _fade_state: str = "stable"   # "in" | "out" | "stable"
    _fade_alpha: float = 1.0      # current fade-out alpha [0..1]
    _auto_hide_handle: "Timer | None" = None
    _sdf_engine: object | None = None  # lazily created SDF morph engine
    # sdf crossfade warmup state
    _sdf_warmup_instance: object | None = None
    _sdf_crossfade: object | None = None   # CrossfadeEngine during warmup→SDF transition
    _sdf_baker_was_ready: bool = False
    _sdf_permanently_failed: bool = False
    _cfg: "DrawilleOverlayCfg | None" = None  # last cfg passed to show()
    # v2 engine instance cache
    _current_engine_instance: object | None = None
    _current_engine_key: str = ""
    # v2 heat / adaptive
    _heat: float = 0.0
    _heat_target: float = 0.0
    _token_count_last: int = 0
    # v2 carousel
    _carousel_elapsed: float = 0.0
    _carousel_engine_idx: int = 0
    _carousel_engines: list = []
    _carousel_idx: int = 0
    _carousel_last_switch: float = 0.0
    _carousel_crossfade: "CrossfadeEngine | None" = None
    # external trail for stateless engines
    _external_trail: "TrailCanvas | None" = None

    # ── lifecycle ──────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        try:
            self._resolved_color = _resolve_color(self.color, self.app)
            self._resolved_color_b = _resolve_color(self.color_b, self.app)
            self._resolved_multi_colors = [
                _resolve_color(c, self.app) for c in self.multi_color
            ]
            self._resolved_multi_color_rgbs = [
                _parse_rgb(c) for c in self._resolved_multi_colors
            ]
        except Exception:
            pass
        w = self.size.width or 50
        h = self.size.height or 14
        cfg = _overlay_config()
        self._anim_params = AnimParams(
            width=w * 2, height=h * 4, dt=1 / 15,
            sdf_text=cfg.sdf_text,
            sdf_hold_ms=cfg.sdf_hold_ms,
            sdf_morph_ms=cfg.sdf_morph_ms,
            sdf_render_mode=cfg.sdf_render_mode,
            sdf_font_size=cfg.sdf_font_size,
            sdf_dissolve_spread=cfg.sdf_dissolve_spread,
            sdf_outline_width=cfg.sdf_outline_width,
            trail_decay=cfg.trail_decay,
            symmetry=cfg.symmetry,
            particle_count=cfg.particle_count,
            noise_scale=cfg.noise_scale,
            depth_cues=cfg.depth_cues,
            blend_mode=cfg.blend_mode,
            attractor_type=cfg.attractor_type,
            life_seed=cfg.life_seed,
        )

    def on_unmount(self) -> None:
        self._stop_anim()
        if self._auto_hide_handle is not None:
            self._auto_hide_handle.stop()
            self._auto_hide_handle = None

    def on_resize(self, event: Resize) -> None:
        if self._anim_params is not None:
            self._anim_params.width = event.size.width * 2
            self._anim_params.height = event.size.height * 4
            self.refresh()

    # ── watchers ───────────────────────────────────────────────────────────

    def watch_color(self, value: str) -> None:
        try:
            self._resolved_color = _resolve_color(value, self.app)
        except Exception:
            pass

    def watch_color_b(self, value: str) -> None:
        try:
            self._resolved_color_b = _resolve_color(value, self.app)
        except Exception:
            pass

    def watch_multi_color(self, value: list) -> None:
        try:
            self._resolved_multi_colors = [_resolve_color(c, self.app) for c in value]
            self._resolved_multi_color_rgbs = [_parse_rgb(c) for c in self._resolved_multi_colors]
        except Exception:
            pass

    def watch_position(self, _value: str) -> None:
        self._apply_layout()

    def watch_size_name(self, _value: str) -> None:
        self._apply_layout()
        if self._anim_params is not None:
            self._anim_params.width = self.size.width * 2
            self._anim_params.height = self.size.height * 4

    def watch_vertical(self, value: bool) -> None:
        self._apply_layout()
        if self._anim_params is not None:
            self._anim_params.vertical = value
            self._anim_params.width = self.size.width * 2
            self._anim_params.height = self.size.height * 4

    def watch_show_border(self, value: bool) -> None:
        if value:
            self.add_class("-show-border")
        else:
            self.remove_class("-show-border")

    # v2 watchers — update _anim_params when reactive changes

    def watch_trail_decay(self, value: float) -> None:
        if self._anim_params is not None:
            self._anim_params.trail_decay = value

    def watch_particle_count(self, value: int) -> None:
        if self._anim_params is not None:
            self._anim_params.particle_count = value

    def watch_symmetry(self, value: int) -> None:
        if self._anim_params is not None:
            self._anim_params.symmetry = value

    def watch_blend_mode(self, value: str) -> None:
        if self._anim_params is not None:
            self._anim_params.blend_mode = value

    def watch_attractor_type(self, value: str) -> None:
        if self._anim_params is not None:
            self._anim_params.attractor_type = value

    def watch_life_seed(self, value: str) -> None:
        if self._anim_params is not None:
            self._anim_params.life_seed = value

    def watch_depth_cues(self, value: bool) -> None:
        if self._anim_params is not None:
            self._anim_params.depth_cues = value

    def watch_fps(self, _value: int) -> None:
        self._stop_anim()
        self._start_anim()

    # ── show / hide ────────────────────────────────────────────────────────

    def show(self, cfg: DrawilleOverlayCfg) -> None:
        """Make overlay visible and start animation.  Idempotent."""
        if not cfg.enabled:
            return
        self._cfg = cfg
        # If a fade-out is in progress, cancel it
        if self._fade_state == "out":
            self._fade_state = "in"
            self._fade_step = cfg.fade_in_frames
            return  # already visible, just interrupt fade-out
        # Sync reactives from config — triggers watchers for live updates.
        self.size_name = cfg.size
        self.vertical = cfg.vertical
        self.position = cfg.position
        self.show_border = cfg.show_border
        self.multi_color = list(cfg.multi_color)
        self.hue_shift_speed = cfg.hue_shift_speed
        self.fps = cfg.fps
        self._apply_layout()
        self._fade_state = "in"
        self._fade_step = cfg.fade_in_frames
        self._fade_alpha = 1.0
        if self._anim_params is not None:
            self._anim_params.vertical = cfg.vertical
            # Update SDF params from config
            self._anim_params.sdf_text = cfg.sdf_text
            self._anim_params.sdf_hold_ms = cfg.sdf_hold_ms
            self._anim_params.sdf_morph_ms = cfg.sdf_morph_ms
            self._anim_params.sdf_render_mode = cfg.sdf_render_mode
            self._anim_params.sdf_font_size = cfg.sdf_font_size
            self._anim_params.sdf_dissolve_spread = cfg.sdf_dissolve_spread
            self._anim_params.sdf_outline_width = cfg.sdf_outline_width
            # Update v2 params from config
            self._anim_params.trail_decay = cfg.trail_decay
            self._anim_params.symmetry = cfg.symmetry
            self._anim_params.particle_count = cfg.particle_count
            self._anim_params.noise_scale = cfg.noise_scale
            self._anim_params.depth_cues = cfg.depth_cues
            self._anim_params.blend_mode = cfg.blend_mode
            self._anim_params.attractor_type = cfg.attractor_type
            self._anim_params.life_seed = cfg.life_seed
        # Clear SDF engine so it gets recreated with new params
        if cfg.animation != "sdf_morph":
            self._sdf_engine = None
        # Carousel setup
        if cfg.carousel:
            self._carousel_engines = [
                k for k in _ENGINES
                if _ENGINE_META.get(k, {}).get("category") not in {"Premium", "System"}
            ]
            if len(self._carousel_engines) < 2:
                self._carousel_engines = []
            self._carousel_idx = 0
            self._carousel_last_switch = time.monotonic()
            self._carousel_crossfade = None
        else:
            self._carousel_engines = []
            self._carousel_crossfade = None
        self.add_class("-visible")
        self._start_anim()
        if cfg.auto_hide_delay > 0:
            if self._auto_hide_handle is not None:
                self._auto_hide_handle.stop()
            self._auto_hide_handle = self.set_timer(
                cfg.auto_hide_delay, self._auto_hide
            )

    def hide(self, cfg: DrawilleOverlayCfg) -> None:
        """Hide overlay, optionally with fade-out."""
        if not self.has_class("-visible"):
            return  # already hidden — no-op
        if self._auto_hide_handle is not None:
            self._auto_hide_handle.stop()
            self._auto_hide_handle = None
        fade_frames = cfg.fade_out_frames if cfg is not None else 0
        if fade_frames > 0:
            self._fade_state = "out"
            self._fade_step = fade_frames
            self._cfg = cfg
            # Don't stop anim yet — _tick() will handle fade and final hide
            return
        # Immediate hide (no fade)
        self._do_hide()

    def _do_hide(self) -> None:
        """Internal: immediately hide overlay and reset state."""
        self.remove_class("-visible")
        self._stop_anim()
        self._fade_state = "stable"
        self._fade_alpha = 1.0
        self._sdf_engine = None
        self._sdf_warmup_instance = None
        self._sdf_crossfade = None
        self._sdf_baker_was_ready = False
        self._sdf_permanently_failed = False
        self._current_engine_instance = None
        self._current_engine_key = ""
        self._external_trail = None
        self._carousel_crossfade = None

    def _auto_hide(self) -> None:
        self._auto_hide_handle = None
        self.hide(_overlay_config())

    def signal(self, event: str, value: float = 1.0) -> None:
        """Signal a heat event to the overlay and active engine.

        Vocabulary: "thinking", "token", "tool", "complete".
        """
        if event == "thinking":
            self._heat_target = 0.5
        elif event == "token":
            self._heat_target = min(1.0, self._heat_target + 0.25)
        elif event == "tool":
            self._heat_target = 1.0
        elif event == "complete":
            self._heat_target = 0.0
        # Forward to engine if it supports on_signal
        engine = self._current_engine_instance
        if engine is not None and hasattr(engine, "on_signal"):
            try:
                engine.on_signal(event, value)
            except Exception:
                pass

    # ── contextual SDF text (C1) ───────────────────────────────────────────

    @property
    def contextual_text(self) -> str:
        """Return SDF display text: explicit cfg override or tool-derived label."""
        if self._cfg and self._cfg.sdf_text:
            return self._cfg.sdf_text
        try:
            tool = self.app._active_tool_name  # type: ignore[attr-defined]
        except AttributeError:
            return "thinking"
        return _TOOL_SDF_LABELS.get(tool, "thinking")

    # ── carousel (D2) ─────────────────────────────────────────────────────

    def _get_carousel_engine(self) -> object:
        """Return the engine for the current carousel position, handling crossfade."""
        # If crossfade active and not done, return it
        if self._carousel_crossfade is not None:
            if self._carousel_crossfade.progress < 1.0:
                return self._carousel_crossfade
            else:
                # Crossfade done — commit new engine key
                self._current_engine_key = self._carousel_engines[self._carousel_idx]
                self._carousel_crossfade = None

        # Check if time to advance
        now = time.monotonic()
        cfg = self._cfg
        interval = cfg.carousel_interval_s if cfg else 12.0
        if (now - self._carousel_last_switch) > interval:
            current_key = self._carousel_engines[self._carousel_idx]
            self._carousel_idx = (self._carousel_idx + 1) % len(self._carousel_engines)
            next_key = self._carousel_engines[self._carousel_idx]
            # Build fresh engine instances for crossfade
            engine_a = self._current_engine_instance
            if engine_a is None:
                engine_a = _ENGINES.get(current_key, _ENGINES["dna"])()
            engine_b = _ENGINES.get(next_key, _ENGINES["dna"])()
            speed = cfg.crossfade_speed if cfg else 0.04
            self._carousel_crossfade = CrossfadeEngine(engine_a, engine_b, speed=speed)
            self._carousel_last_switch = now
            # Current instance will be replaced when crossfade completes
            return self._carousel_crossfade

        # Normal: return current cached engine
        if self._current_engine_instance is None or self._current_engine_key != self._carousel_engines[self._carousel_idx]:
            key = self._carousel_engines[self._carousel_idx]
            self._current_engine_key = key
            self._current_engine_instance = _ENGINES.get(key, _ENGINES["dna"])()
        return self._current_engine_instance

    # ── clock subscription ─────────────────────────────────────────────────

    def _start_anim(self) -> None:
        if self._anim_handle is not None:
            return
        clock: AnimationClock | None = None
        try:
            clock = getattr(self.app, "_anim_clock", None)
        except Exception:
            pass
        if clock is not None:
            # Divisor: how many 15-fps clock ticks to skip per overlay tick.
            divisor = max(1, round(15 / max(1, self.fps)))
            self._anim_handle = clock.subscribe(divisor, self._tick)
        else:
            try:
                self._anim_handle = self.set_interval(1 / max(1, self.fps), self._tick)
            except Exception:
                pass

    def _stop_anim(self) -> None:
        if self._anim_handle is not None:
            self._anim_handle.stop()
            self._anim_handle = None

    def _get_engine(self) -> object:
        """Return cached engine instance, rebuilding if key changed."""
        # Carousel path checked first (D2)
        if self._cfg and self._cfg.carousel and len(self._carousel_engines) >= 2:
            return self._get_carousel_engine()

        key = self.animation

        # Reset warmup state when switching away from sdf_morph
        if self._current_engine_key == "sdf_morph" and key != "sdf_morph":
            self._sdf_warmup_instance = None
            self._sdf_crossfade = None
            self._sdf_baker_was_ready = False
            # Also reset external trail when engine changes
            self._external_trail = None

        if key != self._current_engine_key and self._external_trail is not None:
            self._external_trail = None

        if key != "sdf_morph":
            if self._current_engine_instance is None or self._current_engine_key != key:
                cls = _ENGINES.get(key, _ENGINES["dna"])
                self._current_engine_instance = cls()
                self._current_engine_key = key
                if hasattr(self._current_engine_instance, "on_mount"):
                    self._current_engine_instance.on_mount(self)
            return self._current_engine_instance

        # ── sdf_morph path ────────────────────────────────────────────────────
        self._current_engine_key = "sdf_morph"
        sdf = self._get_sdf_engine(self._anim_params)
        now_ready = sdf._baker.ready.is_set()

        # Edge: baker just became ready → install CrossfadeEngine(warmup → SDF)
        if now_ready and not self._sdf_baker_was_ready:
            self._sdf_baker_was_ready = True
            warmup = self._sdf_warmup_instance
            if warmup is not None:
                cfg = _overlay_config()
                self._sdf_crossfade = CrossfadeEngine(
                    engine_a=warmup,
                    engine_b=sdf,
                    speed=cfg.sdf_crossfade_speed,
                )
                self._sdf_warmup_instance = None  # handed off to crossfade
            # If warmup is None (bake finished before first tick): go straight to SDF

        # Crossfade in progress
        if self._sdf_crossfade is not None:
            if self._sdf_crossfade.progress >= 1.0:
                self._sdf_crossfade = None  # done; fall through to pure SDF
            else:
                return self._sdf_crossfade

        # Baker not ready yet → return warmup engine
        if not now_ready:
            if self._sdf_warmup_instance is None:
                cfg = _overlay_config()
                wkey = cfg.sdf_warmup_engine if cfg.sdf_warmup_engine in _ENGINES else "dna"
                self._sdf_warmup_instance = _ENGINES[wkey]()
            return self._sdf_warmup_instance

        # Baker ready, crossfade done → pure SDF
        return sdf

    def _get_sdf_engine(self, params: AnimParams) -> object:
        """Lazily create SDF morph engine. Calls on_mount on first creation.

        C2: check baker.failed BEFORE baker.ready (fail-fast).
        """
        import logging as _logging
        _LOG = _logging.getLogger(__name__)

        # Check if permanently failed (C2)
        if self._sdf_permanently_failed:
            fallback = (self._cfg.sdf_warmup_engine if self._cfg else None) or "neural_pulse"
            if fallback not in _ENGINES:
                fallback = "neural_pulse"
            return _ENGINES[fallback]()

        if self._sdf_engine is not None:
            # Check baker.failed BEFORE baker.ready (C2)
            baker = getattr(self._sdf_engine, "_baker", None)
            if baker is not None and hasattr(baker, "failed") and baker.failed.is_set():
                if not self._sdf_permanently_failed:
                    _LOG.warning("SDF baker failed — falling back to warmup engine")
                    self._sdf_permanently_failed = True
                self._sdf_engine = None
                self._sdf_warmup_instance = None
                self._sdf_baker_was_ready = False
                fallback = (self._cfg.sdf_warmup_engine if self._cfg else None) or "neural_pulse"
                if fallback not in _ENGINES:
                    fallback = "neural_pulse"
                return _ENGINES[fallback]()

        if self._sdf_engine is None:
            from hermes_cli.tui.sdf_morph import SDFMorphEngine
            self._sdf_engine = SDFMorphEngine(
                text=params.sdf_text,
                hold_ms=params.sdf_hold_ms,
                morph_ms=params.sdf_morph_ms,
                mode=params.sdf_render_mode,
                outline_w=params.sdf_outline_width,
                dissolve_spread=params.sdf_dissolve_spread,
                font_size=params.sdf_font_size,
                color=self._resolved_color,
                color_b=self._resolved_color_b if self.gradient else None,
            )
            # Start bake worker
            if hasattr(self._sdf_engine, "on_mount"):
                self._sdf_engine.on_mount(self)
        return self._sdf_engine

    # ── rendering ──────────────────────────────────────────────────────────

    def _tick(self) -> None:
        if not self.has_class("-visible"):
            # Still running during fade-out — only skip if fully hidden (not fading)
            if self._fade_state != "out":
                return
        params = self._anim_params
        if params is None:
            return

        # Smooth heat toward target (exponential approach)
        self._heat += (self._heat_target - self._heat) * 0.15
        params.heat = self._heat

        # Get engine (cached instance)
        engine = self._get_engine()

        with measure("drawille_frame"):
            frame_str = engine.next_frame(params)
        params.t += params.dt

        # External trail for stateless engines (D3)
        if (self._cfg is not None and self._cfg.trail_decay > 0
                and not hasattr(engine, "_trail")):
            w = params.width
            h = params.height
            if (self._external_trail is None
                    or getattr(self._external_trail, "_w", None) != w
                    or getattr(self._external_trail, "_h", None) != h):
                self._external_trail = TrailCanvas(decay=self._cfg.trail_decay)
                self._external_trail._w = w  # type: ignore[attr-defined]
                self._external_trail._h = h  # type: ignore[attr-defined]
            et = self._external_trail
            # Map braille characters to pixel coords
            for row_idx, row in enumerate(frame_str.split("\n")):
                for col_idx, ch in enumerate(row):
                    if 0x2800 <= ord(ch) <= 0x28FF:
                        bits = ord(ch) - 0x2800
                        for dy in range(4):
                            for dx in range(2):
                                bit_idx = dy * 2 + dx
                                if bits & (1 << bit_idx):
                                    px = col_idx * 2 + dx
                                    py = row_idx * 4 + dy
                                    et.set(px, py, 1.0)
            et.decay_all()
            frame_str = et.to_canvas().frame()

        # Determine render color (may be dimmed during fade-out)
        cfg = self._cfg
        if self._fade_state == "out" and cfg is not None:
            self._fade_step -= 1
            if self._fade_step <= 0:
                self._do_hide()
                return
            self._fade_alpha = self._fade_step / max(cfg.fade_out_frames, 1)
            render_color = _resolve_color(cfg.color, self.app, dim=self._fade_alpha)
        elif self._fade_state == "in" and self._fade_step > 0:
            fade_in_frames = cfg.fade_in_frames if cfg is not None else 3
            alpha = 1.0 - self._fade_step / max(fade_in_frames, 1)
            render_color = lerp_color("#000000", self._resolved_color, alpha)
            self._fade_step -= 1
            if self._fade_step <= 0:
                self._fade_state = "stable"
        else:
            self._fade_state = "stable"
            render_color = self._resolved_color

        if self._resolved_multi_colors:
            self.update(self._render_multi_color(frame_str, params.t))
        elif self.gradient:
            rows = frame_str.split("\n")
            n = max(len(rows), 1)
            pieces: list[tuple[str, Style]] = []
            for i, row in enumerate(rows):
                hex_c = lerp_color(self._resolved_color, self._resolved_color_b, i / n)
                pieces.append((row + "\n", Style(color=hex_c)))
            self.update(Text.assemble(*pieces))
        else:
            style = Style(color=render_color)
            self.update(Text(frame_str, style=style))

    def _render_multi_color(self, frame_str: str, t: float) -> Text:
        """Per-character N-stop gradient with time-based hue-shift drift.

        Each character's column position maps to a position on the gradient.
        A sinusoidal drift (hue_shift_speed) oscillates the gradient left/right
        over time, creating the shifting-hue effect.
        """
        colors = self._resolved_multi_colors
        n_stops = len(colors)
        drift = math.sin(t * self.hue_shift_speed) * 0.25

        # Use pre-parsed RGB tuples (cached at resolve time, not per-frame).
        # Fallback to per-frame parse if cache wasn't populated (e.g. test setup).
        stop_rgbs = self._resolved_multi_color_rgbs
        if stop_rgbs is None:
            stop_rgbs = [_parse_rgb(c) for c in colors]

        rows = frame_str.split("\n")
        pieces: list[tuple[str, Style]] = []
        for row in rows:
            row_len = len(row)
            if row_len == 0:
                pieces.append(("\n", Style()))
                continue

            # Pre-compute color per position
            row_colors: list[str] = []
            for char_idx in range(row_len):
                pos = char_idx / max(row_len - 1, 1) + drift
                pos = abs(pos % 2.0)
                if pos > 1.0:
                    pos = 2.0 - pos

                if n_stops == 1:
                    hex_c = colors[0]
                else:
                    segment = pos * (n_stops - 1)
                    seg_idx = min(int(segment), n_stops - 2)
                    seg_t = segment - seg_idx
                    hex_c = lerp_color_rgb(stop_rgbs[seg_idx], stop_rgbs[seg_idx + 1], seg_t)
                row_colors.append(hex_c)

            # Batch consecutive same-color runs
            run_start = 0
            run_color = row_colors[0]
            for i in range(1, row_len + 1):
                c = row_colors[i] if i < row_len else None
                if c != run_color:
                    span = row[run_start:i]
                    pieces.append((span, Style(color=run_color)))
                    run_start = i
                    run_color = c

            pieces.append(("\n", Style()))
        return Text.assemble(*pieces)

    # ── size / position ────────────────────────────────────────────────────

    def _apply_layout(self) -> None:
        """Apply size + position from current reactives.  Safe to call any time."""
        if self.size_name == "fill":
            self.styles.width = "1fr"
            self.styles.height = "1fr"
            self.styles.offset = (0, 0)
            return
        if self.vertical:
            sizes = {
                "small":  (10, 16),
                "medium": (12, 22),
                "large":  (16, 30),
            }
        else:
            sizes = {
                "small":  (30, 8),
                "medium": (50, 14),
                "large":  (70, 20),
            }
        w, h = sizes.get(self.size_name, sizes["medium"])
        self.styles.width = w
        self.styles.height = h
        try:
            tw = self.app.size.width
            th = self.app.size.height
        except Exception:
            tw, th = 80, 24
        positions = {
            "center":       ((tw - w) // 2,  (th - h) // 2),
            "top-right":    (tw - w - 2,     1),
            "bottom-right": (tw - w - 2,     th - h - 2),
            "bottom-left":  (2,              th - h - 2),
            "top-left":     (2,              1),
        }
        ox, oy = positions.get(self.position, positions["center"])
        self.styles.offset = (max(0, ox), max(0, oy))


# ── AnimConfigPanel ───────────────────────────────────────────────────────────

@dataclass
class _PanelField:
    name: str
    label: str
    kind: str               # "cycle" | "int" | "float" | "toggle" | "color"
    value: object           # current value
    choices: list | None = None   # for cycle fields
    min_val: float = 1
    max_val: float = 15
    step: float = 0.05      # used by "float" kind; ignored for other kinds


class AnimConfigPanel(Widget):
    """Inline config overlay for the drawille animation.

    Opened by ``/anim`` slash command or ``ctrl+shift+a``.
    Does not disable input — users can still type while it's open.
    Dismissed by ``Escape`` or next message send.
    """

    COMPONENT_CLASSES = {
        "anim-config-panel--field",
        "anim-config-panel--focused",
        "anim-config-panel--button",
    }

    DEFAULT_CSS = """
    AnimConfigPanel {
        height: auto;
        max-height: 10;
        width: auto;
        min-width: 60;
        padding: 0 1;
        display: none;
    }
    AnimConfigPanel.-open {
        display: block;
    }
    """

    BINDINGS = [
        Binding("escape",     "close",        "Close",         show=False),
        Binding("tab",        "next_field",    "Next field",    show=False),
        Binding("shift+tab",  "prev_field",    "Prev field",    show=False),
        Binding("left",       "cycle_left",    "Prev value",    show=False),
        Binding("right",      "cycle_right",   "Next value",    show=False),
        Binding("up",         "inc_value",     "Increase",      show=False),
        Binding("down",       "dec_value",     "Decrease",      show=False),
        Binding("space",      "toggle_value",  "Toggle",        show=False),
        Binding("enter",      "activate",      "Activate",      show=False),
    ]

    can_focus = True

    _focus_idx: int = 0
    _preview_timer: "Timer | None" = None
    _color_editing: bool = False

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._fields: list[_PanelField] = []
        self._overlay: DrawilleOverlay | None = None
        self._build_fields()

    def _build_fields(self) -> None:
        cfg = _overlay_config()
        layer_b_choices = [""] + [k for k in ANIMATION_KEYS if k != "sdf_morph"]
        self._fields = [
            _PanelField("animation",  "Animation", "cycle",  cfg.animation,
                        choices=ANIMATION_KEYS),
            _PanelField("fps",        "FPS",       "int",    cfg.fps,
                        min_val=1, max_val=15),
            _PanelField("size_name",  "Size",      "cycle",  cfg.size,
                        choices=["small", "medium", "large", "fill"]),
            _PanelField("position",   "Position",  "cycle",  cfg.position,
                        choices=["center", "top-right", "bottom-right", "bottom-left", "top-left"]),
            _PanelField("color",      "Color",     "color",  cfg.color),
            _PanelField("gradient",   "Gradient",  "toggle", cfg.gradient),
            _PanelField("color_b",    "Color B",   "color",  cfg.color_secondary),
            _PanelField("trigger",    "Trigger",   "cycle",  cfg.trigger,
                        choices=["agent_running", "command_running", "always"]),
            _PanelField("show_border","Border",    "toggle", cfg.show_border),
            _PanelField("dim_bg",     "Dim BG",    "toggle", cfg.dim_background),
            _PanelField("vertical",   "Vertical",  "toggle", cfg.vertical),
            # v2 fields
            _PanelField("blend_mode",     "Blend",       "cycle",  cfg.blend_mode,
                        choices=["overlay", "additive", "xor", "dissolve"]),
            _PanelField("layer_b",        "Layer B",     "cycle",  cfg.layer_b,
                        choices=layer_b_choices),
            _PanelField("trail_decay",    "Trail",       "float",  cfg.trail_decay,
                        min_val=0.0, max_val=0.98, step=0.05),
            _PanelField("adaptive",       "Adaptive",    "toggle", cfg.adaptive),
            _PanelField("particle_count", "Particles",   "int",    cfg.particle_count,
                        min_val=10, max_val=200),
            _PanelField("symmetry",       "Symmetry",    "int",    cfg.symmetry,
                        min_val=1, max_val=12),
            _PanelField("attractor_type", "Attractor",   "cycle",  cfg.attractor_type,
                        choices=["lorenz", "rossler", "thomas"]),
            _PanelField("life_seed",      "Life seed",   "cycle",  cfg.life_seed,
                        choices=["gosper", "acorn", "puffer", "random"]),
            _PanelField("depth_cues",     "Depth cues",  "toggle", cfg.depth_cues),
        ]
        self._focus_idx = 0

    def open(self) -> None:
        """Show the panel and focus it."""
        self._build_fields()
        self.add_class("-open")
        self.focus()

    def close(self) -> None:
        """Hide the panel without reverting runtime changes."""
        self.remove_class("-open")
        try:
            self.app.query_one("#input-area").focus()
        except (NoMatches, Exception):
            pass

    def _get_overlay(self) -> "DrawilleOverlay | None":
        if self._overlay is not None:
            return self._overlay
        try:
            self._overlay = self.app.query_one(DrawilleOverlay)
        except (NoMatches, Exception):
            pass
        return self._overlay

    # ── rendering ──────────────────────────────────────────────────────────

    def render(self) -> Text:
        lines: list[str] = []
        lines.append("─ Animation Config ─")
        row: list[str] = []
        for i, f in enumerate(self._fields):
            focused = i == self._focus_idx
            val_str = self._format_field_value(f)
            bracket_l = "["
            bracket_r = "]"
            cell = f"  {f.label} {bracket_l}{val_str}{bracket_r}"
            if focused:
                row.append(f"\x1b[7m{cell}\x1b[0m")
            else:
                row.append(cell)
            if len(row) == 2:
                lines.append("  ".join(row))
                row = []
            # E1: show engine description below animation field
            if f.name == "animation" and focused:
                desc = _ENGINE_META.get(str(f.value), {}).get("desc", "")
                if desc:
                    lines.append("")  # flush the current row first
                    row = []
                    lines.append(f"     \x1b[2m{desc}\x1b[0m")
        if row:
            lines.append(row[0])
        lines.append("")
        lines.append("  [P] Preview  [S] Save  [R] Reset  Esc close")
        return Text("\n".join(lines))

    def _format_field_value(self, f: _PanelField) -> str:
        if f.kind == "cycle":
            if f.name == "animation":
                key = str(f.value)
                cat = _ENGINE_META.get(key, {}).get("category", "")
                badge = f"[{cat[:3].upper()}] " if cat else ""
                return (badge + key)[:18]
            return str(f.value)[:16]
        elif f.kind == "int":
            return str(f.value)
        elif f.kind == "float":
            return f"{float(f.value):.2f}"
        elif f.kind == "toggle":
            return "on" if f.value else "off"
        else:  # color
            return str(f.value)[:12]

    # ── key actions ────────────────────────────────────────────────────────

    def action_close(self) -> None:
        self.close()

    def action_next_field(self) -> None:
        self._focus_idx = (self._focus_idx + 1) % len(self._fields)
        self.refresh()

    def action_prev_field(self) -> None:
        self._focus_idx = (self._focus_idx - 1) % len(self._fields)
        self.refresh()

    def action_cycle_right(self) -> None:
        self._cycle(+1)

    def action_cycle_left(self) -> None:
        self._cycle(-1)

    def action_inc_value(self) -> None:
        f = self._fields[self._focus_idx]
        if f.kind == "int":
            f.value = min(int(f.max_val), int(f.value) + 1)  # type: ignore[assignment]
            self._push_to_overlay(f)
            self.refresh()
        elif f.kind == "float":
            f.value = round(max(float(f.min_val), min(float(f.max_val), float(f.value) + f.step)), 6)  # type: ignore[assignment]
            self._push_to_overlay(f)
            self.refresh()

    def action_dec_value(self) -> None:
        f = self._fields[self._focus_idx]
        if f.kind == "int":
            f.value = max(int(f.min_val), int(f.value) - 1)  # type: ignore[assignment]
            self._push_to_overlay(f)
            self.refresh()
        elif f.kind == "float":
            f.value = round(max(float(f.min_val), min(float(f.max_val), float(f.value) - f.step)), 6)  # type: ignore[assignment]
            self._push_to_overlay(f)
            self.refresh()

    def action_toggle_value(self) -> None:
        f = self._fields[self._focus_idx]
        if f.kind == "toggle":
            f.value = not f.value
            self._push_to_overlay(f)
            self.refresh()

    def action_activate(self) -> None:
        f = self._fields[self._focus_idx]
        if f.kind == "toggle":
            f.value = not f.value
            self._push_to_overlay(f)
            self.refresh()
        elif f.kind == "cycle":
            self._cycle(+1)

    def on_key(self, event: object) -> None:
        """Handle P/S/R shortcuts."""
        key = getattr(event, "key", "")
        if key == "p":
            self._do_preview()
        elif key == "s":
            self._do_save()
        elif key == "r":
            self._do_reset()

    def _cycle(self, direction: int) -> None:
        f = self._fields[self._focus_idx]
        if f.kind == "float":
            # Left/right also adjust float fields
            delta = f.step * direction
            f.value = round(max(float(f.min_val), min(float(f.max_val), float(f.value) + delta)), 6)  # type: ignore[assignment]
            self._push_to_overlay(f)
            self.refresh()
            return
        if f.kind != "cycle" or not f.choices:
            return
        idx = (f.choices.index(str(f.value)) + direction) % len(f.choices)
        f.value = f.choices[idx]
        self._push_to_overlay(f)
        self.refresh()

    def _push_to_overlay(self, f: _PanelField) -> None:
        """Apply field change to DrawilleOverlay reactive immediately."""
        ov = self._get_overlay()
        if ov is None:
            return
        attr_map = {
            "animation":     "animation",
            "fps":           "fps",
            "size_name":     "size_name",
            "position":      "position",
            "color":         "color",
            "gradient":      "gradient",
            "color_b":       "color_b",
            "trigger":       None,    # not a reactive on overlay
            "show_border":   "show_border",
            "dim_bg":        "dim_bg",
            "vertical":      "vertical",
            # v2 attrs
            "blend_mode":    "blend_mode",
            "layer_b":       "layer_b",
            "trail_decay":   "trail_decay",
            "adaptive":      "adaptive",
            "particle_count": "particle_count",
            "symmetry":      "symmetry",
            "attractor_type": "attractor_type",
            "life_seed":     "life_seed",
            "depth_cues":    "depth_cues",
        }
        attr = attr_map.get(f.name)
        if attr is not None:
            setattr(ov, attr, f.value)

    # ── preview / save / reset ─────────────────────────────────────────────

    def _do_preview(self) -> None:
        ov = self._get_overlay()
        if ov is None:
            return
        cfg = _current_panel_cfg(self._fields)
        ov.show(cfg)
        if self._preview_timer is not None:
            self._preview_timer.stop()
        self._preview_timer = self.set_timer(3.0, self._end_preview)

    def _end_preview(self) -> None:
        self._preview_timer = None
        try:
            if not self.app.agent_running:   # type: ignore[attr-defined]
                ov = self._get_overlay()
                if ov is not None:
                    ov.hide(_overlay_config())
        except Exception:
            pass

    def _do_save(self) -> None:
        self._push_to_overlay_all()
        try:
            vals = _fields_to_dict(self._fields)
            try:
                self.app._persist_anim_config(vals)  # type: ignore[attr-defined]
            except Exception:
                # Fallback: direct write
                from hermes_cli.config import read_raw_config, save_config, _set_nested
                cfg = read_raw_config()
                _set_nested(cfg, "display.drawille_overlay", vals)
                save_config(cfg)
            try:
                from hermes_cli.tui.widgets import HintBar
                self.app.query_one(HintBar).hint = "✓ Saved to config"  # type: ignore[attr-defined]
                self.app.set_timer(2.0, lambda: None)  # type: ignore[attr-defined]
            except Exception:
                pass
        except Exception as exc:
            try:
                self.app.set_status_error(f"save failed: {exc}", auto_clear_s=5.0)  # type: ignore[attr-defined]
            except Exception:
                pass

    def _push_to_overlay_all(self) -> None:
        """Apply all field changes to DrawilleOverlay."""
        for f in self._fields:
            self._push_to_overlay(f)

    def _do_reset(self) -> None:
        from hermes_cli.config import DEFAULT_CONFIG
        d = DEFAULT_CONFIG["display"]["drawille_overlay"]  # type: ignore[index]
        self._fields = []
        self._build_fields()
        ov = self._get_overlay()
        if ov is not None:
            ov.animation = d.get("animation", "dna")
            ov.color = d.get("color", "$accent")
        self.refresh()


# ── _GalleryPreview ───────────────────────────────────────────────────────────

class _GalleryPreview(Widget):
    """Live engine preview widget for AnimGalleryOverlay and AnimConfigPanel."""

    DEFAULT_CSS = """
    _GalleryPreview {
        width: 20;
        height: 6;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._engine_key: str = ""
        self._engine: object | None = None
        self._preview_timer: "Timer | None" = None

    def set_engine(self, key: str) -> None:
        """Switch to a new engine. Creates a fresh instance."""
        self._engine_key = key
        if key == "sdf_morph":
            # SDF requires baking — use neural_pulse as stand-in
            self._engine = _ENGINES["neural_pulse"]()
        elif key in _ENGINES:
            self._engine = _ENGINES[key]()
            if hasattr(self._engine, "on_mount"):
                try:
                    self._engine.on_mount(self)  # type: ignore[arg-type]
                except Exception:
                    pass
        else:
            self._engine = None
        self.refresh()

    def _preview_tick(self) -> None:
        if self._engine is None:
            return
        try:
            params = AnimParams(width=40, height=24, heat=0.5)
            frame = self._engine.next_frame(params)
            params.t += params.dt
            self.update(frame)
        except Exception:
            pass

    def on_mount(self) -> None:
        self._engine = None
        self._preview_timer = self.set_interval(0.5, self._preview_tick)


# ── AnimGalleryOverlay ────────────────────────────────────────────────────────

class AnimGalleryOverlay(Widget):
    """Gallery overlay for browsing and selecting animation engines (B2)."""

    DEFAULT_CSS = """
    AnimGalleryOverlay {
        display: none;
        width: 70;
        height: 20;
        border: round $accent;
        background: $surface;
        padding: 0 1;
        offset: 5 2;
    }
    AnimGalleryOverlay.--visible {
        display: block;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close", show=False),
        Binding("enter",  "select", "Select", show=False),
        Binding("space",  "select", "Select", show=False),
        Binding("up",     "prev_item", "Prev", show=False),
        Binding("down",   "next_item", "Next", show=False),
        Binding("p",      "preview", "Preview", show=False),
        Binding("s",      "open_config", "Config", show=False),
    ]

    can_focus = True

    _focus_idx: int = 0

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._engine_list: list[str] = list(_ENGINES.keys()) + ["sdf_morph"]
        self._focus_idx = 0

    def compose(self) -> "ComposeResult":
        yield Static("", id="gallery-list")
        yield _GalleryPreview(id="gallery-preview")

    def on_mount(self) -> None:
        self._refresh_list()
        self._update_preview()

    def _refresh_list(self) -> None:
        lines: list[str] = []
        lines.append("─ Animation Gallery ─")
        for i, key in enumerate(self._engine_list):
            meta = _ENGINE_META.get(key, {})
            cat = meta.get("category", "")
            badge = f"[{cat[:3].upper()}]" if cat else "   "
            marker = ">" if i == self._focus_idx else " "
            lines.append(f"  {marker} {key:<22} {badge}")
        lines.append("")
        lines.append("  ↑↓ navigate · Enter select · P preview · Esc close")
        try:
            self.query_one("#gallery-list", Static).update("\n".join(lines))
        except (NoMatches, Exception):
            pass

    def _update_preview(self) -> None:
        try:
            key = self._engine_list[self._focus_idx]
            self.query_one(_GalleryPreview).set_engine(key)
        except (NoMatches, IndexError, Exception):
            pass

    def action_prev_item(self) -> None:
        self._focus_idx = (self._focus_idx - 1) % len(self._engine_list)
        self._refresh_list()
        self._update_preview()

    def action_next_item(self) -> None:
        self._focus_idx = (self._focus_idx + 1) % len(self._engine_list)
        self._refresh_list()
        self._update_preview()

    def action_select(self) -> None:
        try:
            key = self._engine_list[self._focus_idx]
            try:
                ov = self.app.query_one(DrawilleOverlay)
                ov.animation = key
            except (NoMatches, Exception):
                pass
            # Update app animation key
            try:
                cfg = _overlay_config()
                cfg.animation = key
            except Exception:
                pass
        except IndexError:
            pass
        self.remove_class("--visible")
        try:
            self.app.query_one("#input-area").focus()
        except (NoMatches, Exception):
            pass

    def action_close(self) -> None:
        self.remove_class("--visible")
        try:
            self.app.query_one("#input-area").focus()
        except (NoMatches, Exception):
            pass

    def action_preview(self) -> None:
        """Force-show overlay with selected engine for 5s."""
        try:
            key = self._engine_list[self._focus_idx]
            ov = self.app.query_one(DrawilleOverlay)
            cfg = _overlay_config()
            cfg.enabled = True
            cfg.animation = key
            ov.animation = key
            ov.show(cfg)
            self.app.set_timer(5.0, lambda: None)  # type: ignore[attr-defined]
        except (NoMatches, Exception):
            pass

    def action_open_config(self) -> None:
        self.remove_class("--visible")
        try:
            panel = self.app.query_one(AnimConfigPanel)
            panel.open()
        except (NoMatches, Exception):
            pass


def _current_panel_cfg(fields: list[_PanelField]) -> DrawilleOverlayCfg:
    """Build a DrawilleOverlayCfg from current panel field values."""
    fmap = {f.name: f.value for f in fields}
    return DrawilleOverlayCfg(
        enabled=True,
        animation=str(fmap.get("animation", "dna")),
        trigger=str(fmap.get("trigger", "agent_running")),
        fps=int(fmap.get("fps", 15)),
        position=str(fmap.get("position", "center")),
        size=str(fmap.get("size_name", "medium")),
        color=str(fmap.get("color", "$accent")),
        gradient=bool(fmap.get("gradient", False)),
        color_secondary=str(fmap.get("color_b", "$primary")),
        dim_background=bool(fmap.get("dim_bg", True)),
        show_border=bool(fmap.get("show_border", False)),
        vertical=bool(fmap.get("vertical", False)),
        border_style="round",
        border_color="$accent",
        auto_hide_delay=0.0,
        fade_in_frames=3,
        fade_out_frames=0,
        multi_color=[],
        hue_shift_speed=0.3,
        # v2
        blend_mode=str(fmap.get("blend_mode", "overlay")),
        layer_b=str(fmap.get("layer_b", "")),
        trail_decay=float(fmap.get("trail_decay", 0.0)),
        adaptive=bool(fmap.get("adaptive", False)),
        particle_count=int(fmap.get("particle_count", 60)),
        symmetry=int(fmap.get("symmetry", 6)),
        attractor_type=str(fmap.get("attractor_type", "lorenz")),
        life_seed=str(fmap.get("life_seed", "gosper")),
        depth_cues=bool(fmap.get("depth_cues", True)),
        sdf_warmup_engine=str(fmap.get("sdf_warmup_engine", "neural_pulse")),
        sdf_crossfade_speed=float(fmap.get("sdf_crossfade_speed", 0.03)),
    )


def _fields_to_dict(fields: list[_PanelField]) -> dict:
    """Convert panel fields to a dict suitable for saving to config."""
    fmap = {f.name: f.value for f in fields}
    return {
        "enabled": True,
        "animation": str(fmap.get("animation", "dna")),
        "trigger": str(fmap.get("trigger", "agent_running")),
        "fps": int(fmap.get("fps", 15)),
        "position": str(fmap.get("position", "center")),
        "size": str(fmap.get("size_name", "medium")),
        "color": str(fmap.get("color", "$accent")),
        "gradient": bool(fmap.get("gradient", False)),
        "color_secondary": str(fmap.get("color_b", "$primary")),
        "dim_background": bool(fmap.get("dim_bg", True)),
        "show_border": bool(fmap.get("show_border", False)),
        "vertical": bool(fmap.get("vertical", False)),
        "border_style": "round",
        "border_color": "$accent",
        "auto_hide_delay": 0,
        "fade_in_frames": 3,
        "fade_out_frames": 0,
        "multi_color": [],
        "hue_shift_speed": 0.3,
        # v2
        "blend_mode": str(fmap.get("blend_mode", "overlay")),
        "layer_b": str(fmap.get("layer_b", "")),
        "trail_decay": float(fmap.get("trail_decay", 0.0)),
        "adaptive": bool(fmap.get("adaptive", False)),
        "particle_count": int(fmap.get("particle_count", 60)),
        "symmetry": int(fmap.get("symmetry", 6)),
        "attractor_type": str(fmap.get("attractor_type", "lorenz")),
        "life_seed": str(fmap.get("life_seed", "gosper")),
        "depth_cues": bool(fmap.get("depth_cues", True)),
        "sdf_warmup_engine": str(fmap.get("sdf_warmup_engine", "neural_pulse")),
        "sdf_crossfade_speed": float(fmap.get("sdf_crossfade_speed", 0.03)),
    }
