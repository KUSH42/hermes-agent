"""DrawilleOverlay — braille-canvas animation overlay + AnimConfigPanel.

Config-gated (display.drawille_overlay.enabled = false by default).
Plugs into AnimationClock; zero overhead when disabled.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
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
    )


# ── Color resolution ──────────────────────────────────────────────────────────

def _resolve_color(value: str, app: object) -> str:
    """Resolve TCSS var ref, named color, or hex → '#rrggbb' string."""
    if value.startswith("$"):
        var_name = value[1:]
        try:
            css_vars: dict[str, str] = app.get_css_variables()  # type: ignore[attr-defined]
            raw = css_vars.get(var_name, "")
            if raw and raw.startswith("#") and len(raw) in (4, 7):
                return raw if len(raw) == 7 else _expand_short_hex(raw)
            # Try to parse whatever the var holds
            if raw:
                return _rich_to_hex(raw)
        except Exception:
            pass
        return "#00d7ff"
    return _rich_to_hex(value)


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


# ── Engine protocol ───────────────────────────────────────────────────────────

@runtime_checkable
class AnimEngine(Protocol):
    def next_frame(self, params: AnimParams) -> str: ...


# ── Animation engines ─────────────────────────────────────────────────────────

def _make_canvas() -> object:
    import drawille
    return drawille.Canvas()


class DnaHelixEngine:
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


class RotatingHelixEngine:
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


class ClassicHelixEngine:
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


class MorphHelixEngine:
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


class VortexEngine:
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


class WaveInterferenceEngine:
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


class ThickHelixEngine:
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


class KaleidoscopeEngine:
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


_ENGINES: dict[str, AnimEngine] = {
    "dna":        DnaHelixEngine(),
    "rotating":   RotatingHelixEngine(),
    "classic":    ClassicHelixEngine(),
    "morph":      MorphHelixEngine(),
    "vortex":     VortexEngine(),
    "wave":       WaveInterferenceEngine(),
    "thick":      ThickHelixEngine(),
    "kaleidoscope": KaleidoscopeEngine(),
}

ANIMATION_KEYS: list[str] = list(_ENGINES.keys())
ANIMATION_LABELS: dict[str, str] = {
    "dna":          "DNA Double Helix",
    "rotating":     "Rotating 3D Helix",
    "classic":      "Classic Triple Wave",
    "morph":        "Morphing Helix",
    "vortex":       "Vortex Spiral",
    "wave":         "Wave Interference",
    "thick":        "Thick Pulse",
    "kaleidoscope": "Kaleidoscope",
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

    _anim_handle: "_ClockSubscription | Timer | None" = None
    _anim_params: "AnimParams | None" = None
    _resolved_color: str = "#00d7ff"
    _resolved_color_b: str = "#8800ff"
    _resolved_multi_colors: list = []   # pre-resolved hex strings; set by watch_multi_color
    _resolved_multi_color_rgbs: list | None = None  # pre-parsed RGB tuples — avoids per-frame _parse_rgb lookups
    _fade_step: int = 0
    _auto_hide_handle: "Timer | None" = None

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
        self._anim_params = AnimParams(width=w * 2, height=h * 4, dt=1 / 15)

    def on_unmount(self) -> None:
        self._stop_anim()
        if self._auto_hide_handle is not None:
            self._auto_hide_handle.stop()
            self._auto_hide_handle = None

    def on_resize(self, event: Resize) -> None:
        if self._anim_params is not None:
            self._anim_params.width = event.size.width * 2
            self._anim_params.height = event.size.height * 4

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

    # ── show / hide ────────────────────────────────────────────────────────

    def show(self, cfg: DrawilleOverlayCfg) -> None:
        """Make overlay visible and start animation.  Idempotent."""
        if not cfg.enabled:
            return
        # Sync reactives from config — triggers watchers for live updates.
        self.size_name = cfg.size
        self.vertical = cfg.vertical
        self.position = cfg.position
        self.show_border = cfg.show_border
        self.multi_color = list(cfg.multi_color)
        self.hue_shift_speed = cfg.hue_shift_speed
        self._apply_layout()
        self._fade_step = cfg.fade_in_frames
        if self._anim_params is not None:
            self._anim_params.vertical = cfg.vertical
        self.add_class("-visible")
        self._start_anim()
        if cfg.auto_hide_delay > 0:
            if self._auto_hide_handle is not None:
                self._auto_hide_handle.stop()
            self._auto_hide_handle = self.set_timer(
                cfg.auto_hide_delay, self._auto_hide
            )

    def hide(self, cfg: DrawilleOverlayCfg) -> None:
        """Hide overlay and stop animation."""
        if self._auto_hide_handle is not None:
            self._auto_hide_handle.stop()
            self._auto_hide_handle = None
        self.remove_class("-visible")
        self._stop_anim()

    def _auto_hide(self) -> None:
        self._auto_hide_handle = None
        self.hide(_overlay_config())

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
            self._anim_handle = clock.subscribe(1, self._tick)
        else:
            try:
                self._anim_handle = self.set_interval(1 / 15, self._tick)
            except Exception:
                pass

    def _stop_anim(self) -> None:
        if self._anim_handle is not None:
            self._anim_handle.stop()
            self._anim_handle = None

    # ── rendering ──────────────────────────────────────────────────────────

    def _tick(self) -> None:
        if not self.has_class("-visible"):
            return
        params = self._anim_params
        if params is None:
            return
        engine = _ENGINES.get(self.animation, _ENGINES["dna"])
        with measure("drawille_frame"):
            frame_str = engine.next_frame(params)
        params.t += params.dt

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
            if self._fade_step > 0:
                cfg = _overlay_config()
                alpha = 1.0 - self._fade_step / max(cfg.fade_in_frames, 1)
                hex_c = lerp_color("#000000", self._resolved_color, alpha)
                style = Style(color=hex_c)
                self._fade_step -= 1
            else:
                style = Style(color=self._resolved_color)
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
    kind: str               # "cycle" | "int" | "toggle" | "color"
    value: object           # current value
    choices: list | None = None   # for cycle fields
    min_val: int = 1
    max_val: int = 15


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
            bracket_l = "[" if not focused else "["
            bracket_r = "]"
            cell = f"  {f.label} {bracket_l}{val_str}{bracket_r}"
            if focused:
                row.append(f"\x1b[7m{cell}\x1b[0m")
            else:
                row.append(cell)
            if len(row) == 2:
                lines.append("  ".join(row))
                row = []
        if row:
            lines.append(row[0])
        lines.append("")
        lines.append("  [P] Preview  [S] Save  [R] Reset  Esc close")
        return Text("\n".join(lines))

    def _format_field_value(self, f: _PanelField) -> str:
        if f.kind == "cycle":
            label = ANIMATION_LABELS.get(str(f.value), str(f.value)) if f.name == "animation" else str(f.value)
            return label[:16]
        elif f.kind == "int":
            return str(f.value)
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
            f.value = min(f.max_val, int(f.value) + 1)  # type: ignore[assignment]
            self._push_to_overlay(f)
            self.refresh()

    def action_dec_value(self) -> None:
        f = self._fields[self._focus_idx]
        if f.kind == "int":
            f.value = max(f.min_val, int(f.value) - 1)  # type: ignore[assignment]
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
            "animation": "animation",
            "fps":       "fps",
            "size_name": "size_name",
            "position":  "position",
            "color":     "color",
            "gradient":  "gradient",
            "color_b":   "color_b",
            "trigger":   None,    # not a reactive on overlay
            "show_border": "show_border",
            "dim_bg":    "dim_bg",
            "vertical":  "vertical",
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
        try:
            from hermes_cli.config import read_raw_config, save_config, _set_nested
            cfg = read_raw_config()
            vals = _fields_to_dict(self._fields)
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
    }
