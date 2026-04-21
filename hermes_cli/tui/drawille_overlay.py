"""DrawilleOverlay — braille-canvas animation overlay + AnimConfigPanel.

Config-gated (display.drawille_overlay.enabled = false by default).
Plugs into AnimationClock; zero overhead when disabled.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.events import Resize
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Input, Static

from hermes_cli.tui.animation import AnimationClock, _ClockSubscription, lerp_color, _parse_rgb, lerp_color_rgb
from hermes_cli.tui.perf import measure
from hermes_cli.tui.anim_engines import (
    AnimParams,
    AnimEngine,
    TrailCanvas,
    _BaseEngine,
    DnaHelixEngine,
    RotatingHelixEngine,
    ClassicHelixEngine,
    MorphHelixEngine,
    VortexEngine,
    WaveInterferenceEngine,
    ThickHelixEngine,
    KaleidoscopeEngine,
    NeuralPulseEngine,
    FlockSwarmEngine,
    ConwayLifeEngine,
    StrangeAttractorEngine,
    HyperspaceEngine,
    PerlinFlowEngine,
    FluidFieldEngine,
    LissajousWeaveEngine,
    AuroraRibbonEngine,
    MandalaBloomEngine,
    RopeBraidEngine,
    WaveFunctionEngine,
    CompositeEngine,
    CrossfadeEngine,
)

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
    # Phase A — signal enrichment
    error_hold_frames: int = 8
    # Phase B — phase-aware carousel
    phase_aware_carousel: bool = True
    phase_crossfade_speed: float = 0.08
    # Phase C — completion ceremony
    completion_burst_frames: int = 4
    # Phase D — ambient idle
    ambient_enabled: bool = False
    ambient_heat: float = 0.12
    ambient_alpha: float = 0.35
    ambient_engine: str = "perlin_flow"
    # Phase E — positioning
    position_margin: int = 2
    rail_width: int = 12
    rail_output_margin: bool = False

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
        # Phase A
        error_hold_frames=int(d.get("error_hold_frames", 8)),
        # Phase B
        phase_aware_carousel=bool(d.get("phase_aware_carousel", True)),
        phase_crossfade_speed=float(d.get("phase_crossfade_speed", 0.08)),
        # Phase C
        completion_burst_frames=int(d.get("completion_burst_frames", 4)),
        # Phase D
        ambient_enabled=bool(d.get("ambient_enabled", False)),
        ambient_heat=float(d.get("ambient_heat", 0.12)),
        ambient_alpha=float(d.get("ambient_alpha", 0.35)),
        ambient_engine=str(d.get("ambient_engine", "perlin_flow")),
        # Phase E
        position_margin=int(d.get("position_margin", 2)),
        rail_width=int(d.get("rail_width", 12)),
        rail_output_margin=bool(d.get("rail_output_margin", False)),
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


# ── Phase B: phase-aware carousel ────────────────────────────────────────────

_PHASE_UPDATE_SIGNALS: frozenset = frozenset({
    "thinking", "reasoning", "tool", "complete", "error", "waiting"
})

_PHASE_CATEGORIES: dict[str, list[str]] = {
    "thinking":  ["Organic"],
    "reasoning": ["Organic", "Mathematical"],
    "tool":      ["Mathematical"],
    "waiting":   ["Organic"],
    "error":     ["Classic"],
    "complete":  [],   # don't switch engine during fade-out
}


# ── Phase F: named presets ────────────────────────────────────────────────────

_PRESETS: dict[str, dict] = {
    "minimal": {
        "animation": "perlin_flow",
        "carousel": False,
        "phase_aware_carousel": False,
        "size": "small",
        "color": "$primary",
        "ambient_enabled": False,
        "completion_burst_frames": 0,
        "fade_out_frames": 4,
        "fps": 12,
        "dim_background": False,
    },
    "balanced": {
        "animation": "neural_pulse",
        "carousel": False,
        "phase_aware_carousel": False,
        "size": "small",
        "color": "auto",
        "completion_burst_frames": 4,
        "fade_out_frames": 8,
        "fps": 20,
        "ambient_enabled": False,
    },
    "immersive": {
        "position": "rail-right",
        "rail_width": 14,
        "rail_output_margin": True,
        "size": "medium",
        "color": "auto",
        "carousel": True,
        "carousel_interval_s": 6.0,
        "phase_aware_carousel": True,
        "dim_background": True,
        "ambient_enabled": True,
        "ambient_alpha": 0.25,
        "completion_burst_frames": 6,
        "fade_out_frames": 12,
        "fps": 24,
    },
    "hacker": {
        "color": "#00ff41",
        "animation": "dna",
        "carousel": True,
        "carousel_interval_s": 4.0,
        "phase_aware_carousel": False,
        "size": "small",
        "position": "top-right",
        "dim_background": False,
        "fps": 24,
    },
    "zen": {
        "animation": "aurora_ribbon",
        "carousel": True,
        "carousel_interval_s": 12.0,
        "phase_aware_carousel": True,
        "phase_crossfade_speed": 0.03,
        "color": "$primary",
        "size": "medium",
        "position": "mid-right",
        "ambient_enabled": True,
        "ambient_heat": 0.08,
        "ambient_alpha": 0.2,
        "ambient_engine": "aurora_ribbon",
        "completion_burst_frames": 2,
        "fade_out_frames": 16,
        "fps": 15,
    },
    "sdf": {
        "animation": "sdf_morph",
        "carousel": False,
        "phase_aware_carousel": False,
        "size": "medium",
        "position": "top-center",
        "color": "auto",
        "completion_burst_frames": 4,
        "fade_out_frames": 10,
        "fps": 20,
        "sdf_hold_ms": 700,
        "sdf_morph_ms": 350,
    },
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
    # Phase A — signal enrichment
    _error_hold_frames: int = 0
    _waiting: bool = False
    # Phase B — phase-aware carousel
    _current_phase: str = "thinking"
    _carousel_key: str = ""   # tracks carousel engine key (NOT _current_engine_key)
    # Phase C — multi-tool burst + completion ceremony
    _burst_counter: int = 0
    _burst_decay_ticks: int = 0
    _completion_burst_frames: int = 0
    # Phase D — ambient idle
    _visibility_state: str = "hidden"   # "hidden" | "active" | "ambient"

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
            # Initialize _carousel_key to first engine
            if self._carousel_engines:
                self._carousel_key = self._carousel_engines[0]
        else:
            self._carousel_engines = []
            self._carousel_crossfade = None
        # Phase D: set visibility state
        self._visibility_state = "active"
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
        # Phase D: reset visibility state
        self._visibility_state = "hidden"

    def _auto_hide(self) -> None:
        self._auto_hide_handle = None
        self.hide(_overlay_config())

    def signal(self, event: str, value: float = 1.0) -> None:
        """Signal a heat event to the overlay and active engine.

        Vocabulary: "thinking", "token", "tool", "complete",
                    "reasoning", "error", "waiting".
        """
        cfg = self._cfg
        # Phase A: reset error_hold on any non-error signal
        if event != "error":
            self._error_hold_frames = 0

        if event == "thinking":
            self._heat_target = 0.5
            self._waiting = False   # Phase A3: clear waiting flag
        elif event == "reasoning":
            self._heat_target = 0.65
        elif event == "token":
            self._heat_target = min(1.0, self._heat_target + 0.25)
        elif event == "tool":
            # Phase C: burst accumulator
            self._burst_counter = min(self._burst_counter + 1, 5)
            self._burst_decay_ticks = 0
            self._heat_target = min(1.0 + self._burst_counter * 0.1, 1.5)
        elif event == "complete":
            self._heat_target = 0.0
            self._waiting = False   # Phase A3: clear waiting flag
            # Phase C2: completion burst — direct heat assignment
            if cfg is not None and cfg.completion_burst_frames > 0:
                self._heat = min(self._heat + 0.2, 1.2)
                self._completion_burst_frames = cfg.completion_burst_frames
        elif event == "error":
            self._heat_target = 1.0
            error_hold = cfg.error_hold_frames if cfg is not None else 8
            self._error_hold_frames = error_hold
            self._waiting = False
        elif event == "waiting":
            self._heat_target = 0.2
            self._waiting = True

        # Phase B: update current phase and trigger crossfade
        if event in _PHASE_UPDATE_SIGNALS:
            old_phase = self._current_phase
            self._current_phase = event
            if cfg is not None and cfg.carousel and self._carousel_engines and event != "token":
                next_key = self._pick_carousel_candidate(event)
                if next_key and next_key != self._carousel_key:
                    eng_a = (self._current_engine_instance
                             or (_ENGINES.get(self._carousel_key) or _ENGINES["dna"])())
                    eng_b = _ENGINES[next_key]()
                    self._carousel_crossfade = CrossfadeEngine(
                        eng_a, eng_b, speed=cfg.phase_crossfade_speed
                    )
                    self._carousel_key = next_key
                    self._carousel_last_switch = time.monotonic()

        # Phase D: ambient → active transition on "thinking"
        if event == "thinking" and self._visibility_state == "ambient":
            self._transition_to_active()

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

    # ── Phase B helpers ────────────────────────────────────────────────────

    def _pick_carousel_candidate(self, phase: str) -> str | None:
        """Return a random engine key filtered by phase category, excluding current."""
        cfg = self._cfg
        if cfg is None or not self._carousel_engines:
            return None
        if cfg.phase_aware_carousel:
            allowed = _PHASE_CATEGORIES.get(phase, [])
            if allowed:
                candidates = [
                    k for k in self._carousel_engines
                    if _ENGINE_META.get(k, {}).get("category") in allowed
                    and k != self._carousel_key
                ]
            else:
                candidates = []
        else:
            candidates = [k for k in self._carousel_engines if k != self._carousel_key]
        if not candidates:
            # Fallback: any engine including current
            candidates = self._carousel_engines
        return random.choice(candidates) if candidates else None

    # ── Phase D helpers ────────────────────────────────────────────────────

    def _transition_to_active(self) -> None:
        """Ambient → active light transition (no full show())."""
        cfg = self._cfg
        if cfg is None:
            return
        self._visibility_state = "active"
        self._heat_target = 0.5
        next_key = self._pick_carousel_candidate("thinking")
        if next_key:
            eng_a = self._current_engine_instance or (
                _ENGINES.get(self._carousel_key) or _ENGINES["dna"]
            )()
            eng_b = _ENGINES[next_key]()
            self._carousel_crossfade = CrossfadeEngine(
                eng_a, eng_b, speed=cfg.phase_crossfade_speed
            )
            self._carousel_key = next_key

    def _transition_to_ambient(self) -> None:
        """Active → ambient transition after completion burst."""
        cfg = self._cfg
        if cfg is None:
            return
        self._visibility_state = "ambient"
        self._heat_target = 0.0
        ambient_key = cfg.ambient_engine
        if ambient_key in _ENGINES:
            self._current_engine_instance = _ENGINES[ambient_key]()
            self._carousel_key = ambient_key

    # ── Phase E helpers ────────────────────────────────────────────────────

    def _has_nameplate(self) -> bool:
        """Return True if AssistantNameplate is present in the DOM."""
        try:
            return len(self.app.query("AssistantNameplate")) > 0
        except Exception:
            return False

    # ── carousel ───────────────────────────────────────────────────────────

    def _get_carousel_engine(self) -> object:
        """Return the engine for the current carousel position, handling crossfade."""
        # Phase D: ambient guard — freeze carousel during ambient state
        if self._visibility_state == "ambient":
            if self._current_engine_instance is None:
                cfg = self._cfg
                ambient_key = (cfg.ambient_engine if cfg else "perlin_flow") or "perlin_flow"
                if ambient_key not in _ENGINES:
                    ambient_key = "perlin_flow"
                self._current_engine_instance = _ENGINES[ambient_key]()
                self._carousel_key = ambient_key
            return self._current_engine_instance

        # If crossfade active and not done, return it
        if self._carousel_crossfade is not None:
            if self._carousel_crossfade.progress < 1.0:
                return self._carousel_crossfade
            else:
                # Crossfade done — commit new engine key
                if self._carousel_engines:
                    self._carousel_idx %= len(self._carousel_engines)
                    self._current_engine_key = self._carousel_engines[self._carousel_idx]
                    self._carousel_key = self._current_engine_key
                self._carousel_crossfade = None

        # Check if time to advance
        now = time.monotonic()
        cfg = self._cfg
        interval = cfg.carousel_interval_s if cfg else 12.0
        if (now - self._carousel_last_switch) > interval:
            # Phase B: build filtered candidate list
            if cfg is not None and cfg.phase_aware_carousel:
                allowed = _PHASE_CATEGORIES.get(self._current_phase, [])
                if allowed:
                    candidates = [
                        k for k in self._carousel_engines
                        if _ENGINE_META.get(k, {}).get("category") in allowed
                    ]
                else:
                    candidates = []
            else:
                candidates = self._carousel_engines

            if not candidates:
                candidates = self._carousel_engines  # fallback — never freeze

            if len(candidates) < 1:
                # No candidates at all — just return current
                pass
            else:
                # Pick next from filtered pool, excluding current
                others = [k for k in candidates if k != self._carousel_key] or candidates
                next_key = random.choice(others)
                self._carousel_key = next_key
                # Advance global idx to match (find in global list or just append)
                if next_key in self._carousel_engines:
                    self._carousel_idx = self._carousel_engines.index(next_key)
                # Build crossfade
                engine_a = self._current_engine_instance
                if engine_a is None:
                    cur = self._carousel_key or (self._carousel_engines[0] if self._carousel_engines else "dna")
                    engine_a = _ENGINES.get(cur, _ENGINES["dna"])()
                engine_b = _ENGINES.get(next_key, _ENGINES["dna"])()
                speed = cfg.crossfade_speed if cfg else 0.04
                self._carousel_crossfade = CrossfadeEngine(engine_a, engine_b, speed=speed)
                self._carousel_last_switch = now
                return self._carousel_crossfade

        # Normal: return current cached engine
        if self._carousel_engines:
            self._carousel_idx %= len(self._carousel_engines)
        if self._current_engine_instance is None or self._current_engine_key != self._carousel_engines[self._carousel_idx]:
            key = self._carousel_engines[self._carousel_idx]
            self._current_engine_key = key
            self._carousel_key = key
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
        cfg = self._cfg

        # Phase A: error hold countdown
        if self._error_hold_frames > 0:
            self._error_hold_frames -= 1
            if self._error_hold_frames == 0:
                self._heat_target = 0.5

        # Phase C: burst counter decay
        if self._burst_counter > 0:
            self._burst_decay_ticks += 1
            if self._burst_decay_ticks >= 30:
                self._burst_counter = max(0, self._burst_counter - 1)
                self._burst_decay_ticks = 0

        # Phase C2: completion burst — gate heat interpolation
        if self._completion_burst_frames > 0:
            self._completion_burst_frames -= 1
            if self._completion_burst_frames == 0:
                # Burst just ended — set target and trigger fade/ambient
                self._heat_target = 0.0
                if cfg is not None and cfg.ambient_enabled:
                    self._transition_to_ambient()
                elif cfg is not None and cfg.fade_out_frames > 0:
                    self._fade_state = "out"
                    self._fade_step = cfg.fade_out_frames
                else:
                    self._do_hide()
                    return
            # No heat interpolation during burst — fall through to render
        elif self._visibility_state == "ambient":
            # Phase D: ambient branch — override heat
            params.heat = cfg.ambient_heat if cfg is not None else 0.12
        elif not self._waiting or self._heat_target > 0:
            # Normal heat interpolation (skip only when _waiting and heat would go to 0)
            self._heat += (self._heat_target - self._heat) * 0.15
        else:
            self._heat += (self._heat_target - self._heat) * 0.15

        # Phase C: authoritative heat clamp [0, 1.5]
        if self._visibility_state != "ambient":
            params.heat = max(0.0, min(1.5, self._heat))

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
        # Phase A3: skip fade-out while _waiting is True
        if self._waiting and self._fade_state == "out":
            self._fade_state = "stable"

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
        elif self._visibility_state == "ambient" and cfg is not None:
            # Phase D: ambient color-channel dimming
            self._fade_state = "stable"
            render_color = _resolve_color(cfg.color, self.app, dim=cfg.ambient_alpha)
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
        cfg = self._cfg
        margin = cfg.position_margin if cfg is not None else 2

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
        try:
            tw = self.app.size.width
            th = self.app.size.height
        except Exception:
            tw, th = 80, 24

        top_safe = 1 if self._has_nameplate() else 0
        bottom_safe = 2

        pos = self.position

        # Phase E: rail modes (offset-based, not dock)
        if pos in ("rail-right", "rail-left"):
            rail_width = cfg.rail_width if cfg is not None else 12
            self.styles.width = rail_width
            self.styles.height = th - top_safe - bottom_safe
            if pos == "rail-right":
                ox, oy = tw - rail_width, top_safe
            else:
                ox, oy = 0, top_safe
            self.styles.offset = (max(0, ox), max(0, oy))
            # Optional: adjust OutputPanel padding
            if cfg is not None and cfg.rail_output_margin:
                try:
                    from hermes_cli.tui.widgets import OutputPanel
                    panel = self.app.query_one(OutputPanel)
                    if pos == "rail-right":
                        panel.styles.padding_right = rail_width
                    else:
                        panel.styles.padding_left = rail_width
                except Exception:
                    pass
            return

        self.styles.width = w
        self.styles.height = h

        # Phase E: 9 named anchors
        positions = {
            "center":        ((tw - w) // 2,        (th - h) // 2),
            "top-right":     (tw - w - margin,       top_safe + margin),
            "bottom-right":  (tw - w - margin,       th - h - bottom_safe),
            "bottom-left":   (margin,                th - h - bottom_safe),
            "top-left":      (margin,                top_safe + margin),
            "top-center":    ((tw - w) // 2,         top_safe + margin),
            "bottom-center": ((tw - w) // 2,         th - h - bottom_safe),
            "mid-right":     (tw - w - margin,       (th - h) // 2),
            "mid-left":      (margin,                (th - h) // 2),
        }
        ox, oy = positions.get(pos, positions["center"])

        # Safe area clamping
        ox = max(margin, min(ox, tw - w - margin))
        oy = max(top_safe, min(oy, th - h - bottom_safe))
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


class AnimConfigPanel(ModalScreen):
    """Modal config screen for the drawille animation.

    Opened by ``/anim config`` slash command or ``ctrl+shift+a``.
    Dismissed by ``Escape``.
    """

    COMPONENT_CLASSES = {
        "anim-config-panel--field",
        "anim-config-panel--focused",
        "anim-config-panel--button",
    }

    DEFAULT_CSS = """
    AnimConfigPanel {
        align: center middle;
    }
    AnimConfigPanel > * {
        background: $surface;
        border: round $accent;
        padding: 1 2;
        width: 70;
        height: auto;
        max-height: 15;
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
                        choices=["center", "top-right", "bottom-right", "bottom-left", "top-left",
                                 "top-center", "bottom-center", "mid-right", "mid-left",
                                 "rail-right", "rail-left"]),
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

    def compose(self) -> ComposeResult:
        yield Static(self._build_text(), id="anim-config-body")

    def on_mount(self) -> None:
        self.focus()

    def _get_overlay(self) -> "DrawilleOverlay | None":
        try:
            return self.app.query_one(DrawilleOverlay)
        except (NoMatches, Exception):
            return None

    # ── rendering ──────────────────────────────────────────────────────────

    def _build_text(self) -> Text:
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

    def _refresh_body(self) -> None:
        """Update the Static child with current field state."""
        try:
            self.query_one("#anim-config-body", Static).update(self._build_text())
        except (NoMatches, Exception):
            pass

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
        self.dismiss()

    def action_next_field(self) -> None:
        self._focus_idx = (self._focus_idx + 1) % len(self._fields)
        self._refresh_body()

    def action_prev_field(self) -> None:
        self._focus_idx = (self._focus_idx - 1) % len(self._fields)
        self._refresh_body()

    def action_cycle_right(self) -> None:
        self._cycle(+1)

    def action_cycle_left(self) -> None:
        self._cycle(-1)

    def action_inc_value(self) -> None:
        f = self._fields[self._focus_idx]
        if f.kind == "int":
            f.value = min(int(f.max_val), int(f.value) + 1)  # type: ignore[assignment]
            self._push_to_overlay(f)
            self._refresh_body()
        elif f.kind == "float":
            f.value = round(max(float(f.min_val), min(float(f.max_val), float(f.value) + f.step)), 6)  # type: ignore[assignment]
            self._push_to_overlay(f)
            self._refresh_body()

    def action_dec_value(self) -> None:
        f = self._fields[self._focus_idx]
        if f.kind == "int":
            f.value = max(int(f.min_val), int(f.value) - 1)  # type: ignore[assignment]
            self._push_to_overlay(f)
            self._refresh_body()
        elif f.kind == "float":
            f.value = round(max(float(f.min_val), min(float(f.max_val), float(f.value) - f.step)), 6)  # type: ignore[assignment]
            self._push_to_overlay(f)
            self._refresh_body()

    def action_toggle_value(self) -> None:
        f = self._fields[self._focus_idx]
        if f.kind == "toggle":
            f.value = not f.value
            self._push_to_overlay(f)
            self._refresh_body()

    def action_activate(self) -> None:
        f = self._fields[self._focus_idx]
        if f.kind == "toggle":
            f.value = not f.value
            self._push_to_overlay(f)
            self._refresh_body()
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
            self._refresh_body()
            return
        if f.kind != "cycle" or not f.choices:
            return
        idx = (f.choices.index(str(f.value)) + direction) % len(f.choices)
        f.value = f.choices[idx]
        self._push_to_overlay(f)
        self._refresh_body()

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
        self._refresh_body()


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

class AnimGalleryOverlay(ModalScreen):
    """Gallery modal screen for browsing and selecting animation engines (B2)."""

    DEFAULT_CSS = """
    AnimGalleryOverlay {
        align: center middle;
    }
    AnimGalleryOverlay > Vertical {
        width: 70;
        height: 20;
        border: round $accent;
        background: $surface;
        padding: 0 1;
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
        with Vertical():
            yield Static("", id="gallery-list")
            yield _GalleryPreview(id="gallery-preview")

    def on_mount(self) -> None:
        self.focus()
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
        self.dismiss()

    def action_close(self) -> None:
        self.dismiss()

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
        self.app.push_screen(AnimConfigPanel())


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
