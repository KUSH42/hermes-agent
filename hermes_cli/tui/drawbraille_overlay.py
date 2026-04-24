"""DrawbrailleOverlay — braille-canvas animation overlay + AnimConfigPanel.

Config-gated (display.drawbraille_overlay.enabled = false by default).
Plugs into AnimationClock; zero overhead when disabled.
"""
from __future__ import annotations

import random
import time
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.events import Resize
from textual.reactive import reactive
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Input, Static

from hermes_cli.tui.animation import AnimationClock, _ClockSubscription
from hermes_cli.tui.perf import measure
from hermes_cli.tui.anim_engines import (
    AnimParams,
    AnimEngine,
    TrailCanvas,
    _BaseEngine,
    _layer_frames,
    _braille_density_set,
    _depth_to_density,
    _easing,
    _make_canvas,
    _make_trail_canvas,
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
    WireframeCubeEngine,
    SierpinskiEngine,
    PlasmaEngine,
    Torus3DEngine,
    MatrixRainEngine,
)

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp



# ── Config dataclass ──────────────────────────────────────────────────────────

@dataclass
class DrawbrailleOverlayCfg:
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
    # v2 particle engines
    particle_count: int = 60
    # v2 symmetry / structure
    symmetry: int = 6
    noise_scale: float = 1.0
    depth_cues: bool = True
    attractor_type: str = "lorenz"
    life_seed: str = "gosper"
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
    custom_offset_x: int = -1
    custom_offset_y: int = -1

    def __post_init__(self) -> None:
        if self.multi_color is None:
            self.multi_color = []


def _cfg_from_mapping(d: dict) -> DrawbrailleOverlayCfg:
    raw_mc = d.get("multi_color", [])
    multi_color = [str(c) for c in raw_mc] if isinstance(raw_mc, list) else []
    return DrawbrailleOverlayCfg(
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
        particle_count=int(d.get("particle_count", 60)),
        symmetry=int(d.get("symmetry", 6)),
        noise_scale=float(d.get("noise_scale", 1.0)),
        depth_cues=bool(d.get("depth_cues", True)),
        attractor_type=str(d.get("attractor_type", "lorenz")),
        life_seed=str(d.get("life_seed", "gosper")),
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
        custom_offset_x=int(d.get("custom_offset_x", -1)),
        custom_offset_y=int(d.get("custom_offset_y", -1)),
    )


def _overlay_config() -> DrawbrailleOverlayCfg:
    """Read current overlay config from disk. Not cached — reads each call.

    Uses read_raw_config() to avoid ensure_hermes_home() side effect during tests.
    Falls back to empty dict if config file missing.
    """
    try:
        from hermes_cli.config import read_raw_config
        d = read_raw_config().get("display", {}).get("drawbraille_overlay", {})
    except Exception:
        d = {}
    return _cfg_from_mapping(d)


# ── Color resolution ──────────────────────────────────────────────────────────
# Helpers live in _color_utils.py (no Textual dep).  Re-exported here for
# backward compat so existing call sites (services/, app.py, etc.) continue.

from hermes_cli.tui._color_utils import (  # noqa: E402
    _hex_to_rgb,
    _resolve_color,
    _expand_short_hex,
    _rich_to_hex,
)


# ── Engine registry (re-exported from anim_engines — no Textual dep there) ───

from hermes_cli.tui.anim_engines import ENGINES as _ENGINES  # noqa: E402

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


from hermes_cli.tui.anim_engines import ANIMATION_LABELS  # noqa: E402

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
    # Part A new engines
    "wireframe_cube":    {"category": "Classic",      "desc": "Rotating 3D wireframe cube with depth-sorted edges"},
    "sierpinski":        {"category": "Mathematical", "desc": "IFS chaos game fractal — Sierpinski triangle with trail decay"},
    "plasma":            {"category": "Mathematical", "desc": "Demoscene plasma — sum of sine fields thresholded into braille"},
    "torus_3d":          {"category": "Classic",      "desc": "Rotating wireframe torus with depth-sorted latitude rings"},
    "matrix_rain":       {"category": "Organic",      "desc": "Falling particle columns with TrailCanvas decay"},
    # Part B new engines
    "double_helix":      {"category": "Classic",      "desc": "3D double-strand DNA helix with compound rotation and rungs"},
    "double_helix_lit":  {"category": "Classic",      "desc": "3D double helix with depth-based braille density cues"},
    "triple_helix":      {"category": "Classic",      "desc": "3D triple-strand helix with compound rotation"},
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


# ── Position grid helpers (D1/D2) ────────────────────────────────────────────

# Positions where ambient idle is permitted (braille chars opaque — non-rail positions cover output)
_RAIL_POSITIONS: frozenset[str] = frozenset({"rail-right", "rail-left"})

_POS_GRID: list[list[str]] = [
    ["top-left",    "top-center",    "top-right"],
    ["mid-left",    "center",        "mid-right"],
    ["bottom-left", "bottom-center", "bottom-right"],
]
_POS_TO_RC: dict[str, tuple[int, int]] = {
    name: (col, row)
    for row, rowlist in enumerate(_POS_GRID)
    for col, name in enumerate(rowlist)
}


def _nearest_anchor(ox: int, oy: int, w: int, h: int, tw: int, th: int) -> str:
    """Return the named position whose ideal offset is closest to (ox, oy)."""
    margin = 2
    top_safe = 1
    bottom_safe = 2
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
    best = "center"
    best_d = float("inf")
    for name, (ix, iy) in positions.items():
        d = (ox - ix) ** 2 + (oy - iy) ** 2
        if d < best_d:
            best_d = d
            best = name
    return best


# ── DrawbrailleOverlay ───────────────────────────────────────────────────────────

class DrawbrailleOverlay(Static):
    """Braille-canvas animation overlay shown during agent activity.

    Shown/hidden by ``show()`` / ``hide()`` called from
    ``HermesApp.watch_agent_running()``.  Plugs into the shared
    ``AnimationClock`` (no extra timers).
    """

    COMPONENT_CLASSES = {
        "drawbraille-overlay--canvas",
        "drawbraille-overlay--border",
    }

    DEFAULT_CSS = """
    DrawbrailleOverlay {
        display: none;
        width: 12;
        height: 22;
        offset: 0 0;
        min-width: 8;
        min-height: 4;
        padding: 0;
    }
    DrawbrailleOverlay.-visible {
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
    particle_count:  reactive[int]   = reactive(60)
    symmetry:        reactive[int]   = reactive(6)
    blend_mode:      reactive[str]   = reactive("overlay")
    layer_b:         reactive[str]   = reactive("")
    attractor_type:  reactive[str]   = reactive("lorenz")
    life_seed:       reactive[str]   = reactive("gosper")
    depth_cues:      reactive[bool]  = reactive(True)

    _anim_handle: "_ClockSubscription | Timer | None" = None
    _anim_params: "AnimParams | None" = None
    _auto_hide_handle: "Timer | None" = None
    _cfg: "DrawbrailleOverlayCfg | None" = None  # last cfg passed to show()
    # v2 heat / adaptive
    _heat: float = 0.0
    _heat_target: float = 0.0
    _token_count_last: int = 0
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
    # D2 — mouse drag fields
    _dragging: bool = False
    _drag_base_ox: int = 0
    _drag_base_oy: int = 0
    _drag_start_sx: int = 0
    _drag_start_sy: int = 0

    # ── lifecycle ──────────────────────────────────────────────────────────

    def _ensure_orchestrator(self) -> None:
        """Create orchestrator lazily if on_mount was not called (e.g. in tests)."""
        if "_orchestrator" not in self.__dict__:
            from hermes_cli.tui.anim_orchestrator import AnimOrchestrator
            self.__dict__["_orchestrator"] = AnimOrchestrator(self)

    def _ensure_renderer(self) -> None:
        """Create renderer lazily if on_mount was not called (e.g. in tests)."""
        if "_renderer" not in self.__dict__:
            from hermes_cli.tui.drawbraille_renderer import DrawbrailleRenderer
            self.__dict__["_renderer"] = DrawbrailleRenderer()

    def __getattr__(self, name: str) -> object:
        """Auto-create _renderer and _orchestrator on first access (test-compat)."""
        if name == "_renderer":
            self._ensure_renderer()
            return self.__dict__["_renderer"]
        if name == "_orchestrator":
            self._ensure_orchestrator()
            return self.__dict__["_orchestrator"]
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def on_mount(self) -> None:
        from hermes_cli.tui.anim_orchestrator import AnimOrchestrator
        from hermes_cli.tui.drawbraille_renderer import DrawbrailleRenderer
        self._orchestrator = AnimOrchestrator(self)
        self._renderer = DrawbrailleRenderer()
        try:
            self._renderer.resolve_colors(self.color, self.color_b, self.multi_color, self.app)
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
            self._ensure_renderer()
            self._renderer.resolve_colors(value, self.color_b, self.multi_color, self.app)
        except Exception:
            pass

    def watch_color_b(self, value: str) -> None:
        try:
            self._ensure_renderer()
            self._renderer.resolve_colors(self.color, value, self.multi_color, self.app)
        except Exception:
            pass

    def watch_multi_color(self, value: list) -> None:
        try:
            self._ensure_renderer()
            self._renderer.resolve_colors(self.color, self.color_b, value, self.app)
        except Exception:
            pass

    def watch_position(self, _value: str) -> None:
        self._apply_layout()

    def watch_size_name(self, _value: str) -> None:
        self._apply_layout()

    def watch_vertical(self, value: bool) -> None:
        self._apply_layout()
        if self._anim_params is not None:
            self._anim_params.vertical = value

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

    def show(self, cfg: DrawbrailleOverlayCfg) -> None:
        """Make overlay visible and start animation.  Idempotent."""
        self._ensure_orchestrator()
        self._ensure_renderer()
        if not cfg.enabled:
            return
        self._cfg = cfg
        # If a fade-out is in progress, cancel it — start fade-in instead
        if self._renderer._fade_state == "out":
            self._renderer.start_fade_in(cfg)
            return  # already visible, just interrupt fade-out
        # Sync reactives from config — triggers watchers for live updates.
        self.animation = cfg.animation
        self.color = cfg.color
        self.gradient = cfg.gradient
        self.color_b = cfg.color_secondary
        self.dim_bg = cfg.dim_background
        self.size_name = cfg.size
        self.vertical = cfg.vertical
        self.position = cfg.position
        self.show_border = cfg.show_border
        self.multi_color = list(cfg.multi_color)
        self.hue_shift_speed = cfg.hue_shift_speed
        self.fps = cfg.fps
        self._apply_layout()
        self._renderer.start_fade_in(cfg)
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
            self._orchestrator._sdf_engine = None
        # Carousel setup (delegated to orchestrator)
        self._orchestrator.init_carousel(cfg)
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

    def hide(self, cfg: DrawbrailleOverlayCfg) -> None:
        """Hide overlay, optionally with fade-out."""
        self._ensure_orchestrator()
        self._ensure_renderer()
        if not self.has_class("-visible"):
            return  # already hidden — no-op
        if self._auto_hide_handle is not None:
            self._auto_hide_handle.stop()
            self._auto_hide_handle = None
        fade_frames = cfg.fade_out_frames if cfg is not None else 0
        if fade_frames > 0:
            self._renderer.start_fade_out(cfg)
            self._cfg = cfg
            # Don't stop anim yet — _tick() will handle fade and final hide
            return
        # Immediate hide (no fade)
        self._do_hide()

    def _do_hide(self) -> None:
        """Internal: immediately hide overlay and reset state."""
        self._ensure_orchestrator()
        self._ensure_renderer()
        self.remove_class("-visible")
        self._stop_anim()
        self._renderer.cancel_fade_out()
        # Clear orchestrator engine/carousel/SDF cache
        self._orchestrator.reset()
        # _sdf_permanently_failed cleared explicitly here (NOT in reset())
        self._orchestrator._sdf_permanently_failed = False
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
        self._ensure_orchestrator()
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

        # Phase B: update current phase and trigger crossfade (via orchestrator)
        if event in _PHASE_UPDATE_SIGNALS:
            self._current_phase = event
            if cfg is not None:
                # Guard: when event="thinking" and in ambient state,
                # _transition_to_active() (called below) installs the carousel
                # CrossfadeEngine via transition_to_active(). Calling on_phase_signal()
                # first would install a CrossfadeEngine that transition_to_active()
                # immediately overwrites. Skip on_phase_signal here.
                if not (event == "thinking" and self._visibility_state == "ambient"):
                    self._orchestrator.on_phase_signal(self._current_phase, cfg)

        # Phase D: ambient → active transition on "thinking"
        if event == "thinking" and self._visibility_state == "ambient":
            self._transition_to_active()

        # Forward to engine if it supports on_signal
        engine = self._orchestrator._current_engine_instance
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

    # ── Phase B helpers (delegated to orchestrator) ─────────────────────

    def _pick_carousel_candidate(self, phase: str) -> str | None:
        """Thin delegator to AnimOrchestrator.pick_carousel_candidate."""
        cfg = self._cfg
        if cfg is None:
            return None
        return self._orchestrator.pick_carousel_candidate(phase, cfg)

    # ── Phase D helpers ────────────────────────────────────────────────────────────────────

    def _transition_to_active(self) -> None:
        """Ambient → active light transition (no full show())."""
        cfg = self._cfg
        if cfg is None:
            return
        self._visibility_state = "active"
        self._heat_target = 0.5
        self._orchestrator.transition_to_active(cfg)
        # NOTE: does NOT call add_class("-visible") — overlay is already visible

    def _transition_to_ambient(self) -> None:
        """Active → ambient transition after completion burst."""
        cfg = self._cfg
        if cfg is None:
            return
        self._visibility_state = "ambient"
        self._heat_target = 0.0
        if cfg.ambient_engine in _ENGINES:
            self._orchestrator.set_ambient_engine(cfg.ambient_engine)
        # NOTE: does NOT call add_class("-visible") — overlay is already visible

    def _has_nameplate(self) -> bool:
        """Return True if AssistantNameplate is present in the DOM."""
        try:
            return len(self.app.query("AssistantNameplate")) > 0
        except Exception:
            return False

    # ── clock subscription ──────────────────────────────────────────────────────

    def _start_anim(self) -> None:
        if self._anim_handle is not None:
            return
        clock = None
        try:
            clock = getattr(self.app, "_anim_clock", None)
        except Exception:
            pass
        if clock is not None:
            from hermes_cli.tui.animation import AnimationClock
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

    # ── Phase D helpers ────────────────────────────────────────────────────────────────────

    # ── Engine delegators (Phase 2: thin backward-compat shims) ──────────────

    def _get_engine(self) -> object:
        """Thin delegator — Phase 2 backward compat for existing tests."""
        self._ensure_orchestrator()
        self._ensure_renderer()
        try:
            gradient = self.gradient
        except Exception:
            gradient = self.__dict__.get("gradient", False)
        return self._orchestrator.get_engine(
            self._anim_params,
            self._cfg,
            resolved_color=self._renderer._resolved_color,
            resolved_color_b=self._renderer._resolved_color_b if gradient else None,
        )

    def _get_carousel_engine(self) -> object:
        """Thin delegator — Phase 2 backward compat for existing tests."""
        self._ensure_orchestrator()
        cfg = self._cfg
        if cfg is None:
            return self._orchestrator._current_engine_instance or self._orchestrator.set_ambient_engine("dna") or self._orchestrator._current_engine_instance
        return self._orchestrator.get_carousel_engine(cfg)

    def _get_sdf_engine(self, params: AnimParams) -> object:
        """Thin delegator — Phase 2 backward compat for existing tests."""
        self._ensure_orchestrator()
        self._ensure_renderer()
        try:
            gradient = self.gradient
        except Exception:
            gradient = self.__dict__.get("gradient", False)
        return self._orchestrator.get_sdf_engine(
            params,
            self._cfg,
            resolved_color=self._renderer._resolved_color,
            resolved_color_b=self._renderer._resolved_color_b if gradient else None,
        )

    def _ambient_allowed(self) -> bool:
        """Ambient idle only makes sense at rail positions — non-rail positions cover output."""
        cfg = self._cfg
        return cfg is not None and cfg.ambient_enabled and self.position in _RAIL_POSITIONS

    # ── rendering ──────────────────────────────────────────────────────────

    def _update_heat_and_burst(self, params: AnimParams, cfg: "DrawbrailleOverlayCfg | None") -> bool:
        """Update heat, burst counters, and completion state.

        Returns True if caller should stop (e.g. _do_hide was called internally).
        Side effects: modifies params.heat, self._heat, self._heat_target, self._burst_*.
        """
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
                if self._ambient_allowed():
                    self._transition_to_ambient()
                elif cfg is not None and cfg.fade_out_frames > 0:
                    self._renderer.start_fade_out(cfg)
                else:
                    self._do_hide()
                    return True
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

        return False

    def _tick(self) -> None:
        self._ensure_orchestrator()
        self._ensure_renderer()
        if not self.has_class("-visible"):
            # Still running during fade-out — only skip if fully hidden (not fading)
            if self._renderer._fade_state != "out":
                return
        params = self._anim_params
        if params is None:
            return
        cfg = self._cfg

        if self._update_heat_and_burst(params, cfg):
            return

        # Get engine via orchestrator (Phase 3: colors owned by renderer)
        engine = self._orchestrator.get_engine(
            params, cfg,
            resolved_color=self._renderer._resolved_color,
            resolved_color_b=self._renderer._resolved_color_b if self.gradient else None,
        )

        with measure("drawbraille_frame"):
            frame_str = engine.next_frame(params)
        params.t += params.dt

        # External trail for stateless engines (delegated to orchestrator)
        frame_str = self._orchestrator.apply_external_trail(frame_str, params, cfg)

        # Phase A3: cancel fade-out while _waiting is True
        if self._waiting and self._renderer._fade_state == "out":
            self._renderer.cancel_fade_out()

        rich_text = self._renderer.render_frame(
            frame_str, params.t, cfg,
            visibility_state=self._visibility_state,
            gradient=self.gradient,
            hue_shift_speed=self.hue_shift_speed,
        )
        if rich_text is None:
            # render_frame signals: fade-out complete — hide now
            self._do_hide()
            return
        self.update(rich_text)

    # ── size / position ────────────────────────────────────────────────────

    def _set_offset(self, ox: int, oy: int) -> None:
        """Set styles.offset and keep drag-base in sync."""
        self.styles.offset = (ox, oy)
        self._drag_base_ox = ox
        self._drag_base_oy = oy

    def _clamp_offset(self, ox: int, oy: int, w: int, h: int, tw: int, th: int) -> tuple[int, int]:
        cfg = self._cfg
        margin = cfg.position_margin if cfg is not None else 2
        top_safe = 1 if self._has_nameplate() else 0
        bottom_safe = 2
        max_x = max(margin, tw - w - margin)
        max_y = max(top_safe, th - h - bottom_safe)
        return (
            max(0, max(margin, min(ox, max_x))),
            max(0, max(top_safe, min(oy, max_y))),
        )

    def _set_anim_param_cells(self, w: int, h: int) -> None:
        if self._anim_params is not None:
            self._anim_params.width = max(1, int(w)) * 2
            self._anim_params.height = max(1, int(h)) * 4

    def _apply_layout(self) -> None:
        """Apply size + position from current reactives.  Safe to call any time."""
        cfg = self._cfg
        margin = cfg.position_margin if cfg is not None else 2
        try:
            tw = self.app.size.width
            th = self.app.size.height
        except Exception:
            tw, th = 80, 24

        if self.size_name == "fill":
            self.styles.width = "1fr"
            self.styles.height = "1fr"
            self._set_anim_param_cells(tw, th)
            self._set_offset(0, 0)
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

        top_safe = 1 if self._has_nameplate() else 0
        bottom_safe = 2

        pos = self.position

        # Phase E: rail modes (offset-based, not dock)
        if pos in ("rail-right", "rail-left"):
            rail_width = cfg.rail_width if cfg is not None else 12
            self.styles.width = rail_width
            self.styles.height = th - top_safe - bottom_safe
            self._set_anim_param_cells(rail_width, th - top_safe - bottom_safe)
            if pos == "rail-right":
                ox, oy = tw - rail_width, top_safe
            else:
                ox, oy = 0, top_safe
            self._set_offset(max(0, ox), max(0, oy))
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
        self._set_anim_param_cells(w, h)

        if pos == "custom":
            ox = cfg.custom_offset_x if cfg is not None else self._drag_base_ox
            oy = cfg.custom_offset_y if cfg is not None else self._drag_base_oy
            if ox < 0 or oy < 0:
                ox, oy = self._drag_base_ox, self._drag_base_oy
            ox, oy = self._clamp_offset(int(ox), int(oy), w, h, tw, th)
            self._set_offset(ox, oy)
            return

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
        ox, oy = self._clamp_offset(ox, oy, w, h, tw, th)
        self._set_offset(ox, oy)

    # ── D2 mouse drag handlers ─────────────────────────────────────────────

    def on_mouse_down(self, event: object) -> None:
        from textual import events
        if not isinstance(event, events.MouseDown):
            return
        if event.button != 1:
            return
        self._dragging = True
        self._drag_start_sx = event.screen_x
        self._drag_start_sy = event.screen_y
        try:
            self.app.capture_mouse(self)
        except AttributeError:
            pass
        event.stop()

    def on_mouse_move(self, event: object) -> None:
        from textual import events
        if not isinstance(event, events.MouseMove):
            return
        if not self._dragging:
            return
        dx = event.screen_x - self._drag_start_sx
        dy = event.screen_y - self._drag_start_sy
        try:
            tw = self.app.size.width
            th = self.app.size.height
            w = self.size.width
            h = self.size.height
            ox, oy = self._clamp_offset(
                self._drag_base_ox + dx,
                self._drag_base_oy + dy,
                w, h, tw, th,
            )
            self.styles.offset = (ox, oy)
        except Exception:
            pass
        event.stop()

    def on_mouse_up(self, event: object) -> None:
        from textual import events
        if not isinstance(event, events.MouseUp):
            return
        if not self._dragging:
            return
        self._dragging = False
        try:
            self.app.release_mouse()
        except AttributeError:
            pass
        try:
            tw, th = self.app.size.width, self.app.size.height
            w, h = self.size.width, self.size.height
            ox = self._drag_base_ox + (event.screen_x - self._drag_start_sx)
            oy = self._drag_base_oy + (event.screen_y - self._drag_start_sy)
            ox, oy = self._clamp_offset(ox, oy, w, h, tw, th)
            cfg = self._cfg or _overlay_config()
            self._cfg = replace(cfg, position="custom", custom_offset_x=ox, custom_offset_y=oy)
            self._set_offset(ox, oy)
            self.position = "custom"
            self.app._svc_commands.persist_anim_config({
                "position": "custom",
                "custom_offset_x": ox,
                "custom_offset_y": oy,
            })
        except Exception:
            pass
        event.stop()




# ── Re-exports (Phase 1 split) ────────────────────────────────────────────────
# Load-bearing order: must be at bottom of file, after DrawbrailleOverlay,
# DrawbrailleOverlayCfg, and all module-level constants are fully defined.
# anim_config_panel.py imports from this module at load time; placing these
# re-exports here ensures all names are present before the circular trigger fires.

from hermes_cli.tui.widgets.anim_config_panel import (  # noqa: E402
    AnimConfigPanel,
    AnimGalleryOverlay,
    _GalleryPreview,
    _PanelField,
    ANIMATION_KEYS,
    _PANEL_CONFIG_KEYS,
    _panel_updates,
    _current_panel_cfg,
    _fields_to_dict,
)
