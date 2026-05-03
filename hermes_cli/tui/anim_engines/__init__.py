"""Animation engine package for the Drawbraille overlay.

This package is a drop-in replacement for the former flat ``anim_engines.py`` module.
All public names are re-exported here so existing imports continue to work unchanged.
"""
from __future__ import annotations

# ── Base types and helpers ────────────────────────────────────────────────────
from ._base import (  # noqa: F401
    AnimEngine,
    AnimParams,
    TrailCanvas,
    _BaseEngine,
    _BOID_CELL_SIZE,
    _COS_LUT,
    _LUT_SIZE,
    _LUT_SIZE_F,
    _SIN_LUT,
    _TORUS_TILT_COS,
    _TORUS_TILT_SIN,
    _TWO_PI_INV,
    _braille_density_set,
    _depth_to_density,
    _easing,
    _layer_frames,
    _lut_cos,
    _lut_sin,
    _make_canvas,
    _make_trail_canvas,
    _safe_dims,
)

# ── Helix family ──────────────────────────────────────────────────────────────
from ._helix import (  # noqa: F401
    ClassicHelixEngine,
    DnaHelixEngine,
    DoubleHelixEngine,
    DoubleHelixLitEngine,
    MorphHelixEngine,
    RotatingHelixEngine,
    TripleHelixEngine,
    _rot3,
)

# ── Flow family ───────────────────────────────────────────────────────────────
from ._flow import (  # noqa: F401
    FluidFieldEngine,
    PerlinFlowEngine,
    VortexEngine,
    WaveInterferenceEngine,
)

# ── Organic family ────────────────────────────────────────────────────────────
from ._organic import (  # noqa: F401
    ConwayLifeEngine,
    FlockSwarmEngine,
    NeuralPulseEngine,
)

# ── Geometric/pattern family ──────────────────────────────────────────────────
from ._geometric import (  # noqa: F401
    AuroraRibbonEngine,
    KaleidoscopeEngine,
    LissajousWeaveEngine,
    MandalaBloomEngine,
    RopeBraidEngine,
    ThickHelixEngine,
    WaveFunctionEngine,
)

# ── Math/attractor family ─────────────────────────────────────────────────────
from ._math import (  # noqa: F401
    HyperspaceEngine,
    StrangeAttractorEngine,
)

# ── 3D/special family ─────────────────────────────────────────────────────────
from ._special import (  # noqa: F401
    MatrixRainEngine,
    PlasmaEngine,
    SierpinskiEngine,
    Torus3DEngine,
    WireframeCubeEngine,
    _bresenham_pts,
    _clip_segment,
)

# ── Composite family ──────────────────────────────────────────────────────────
from ._composite import (  # noqa: F401
    CompositeEngine,
    CrossfadeEngine,
)

# ── Engine registry + labels (no Textual dep — safe to import standalone) ────

# il-a1: engine registry dict; written once at module load, never mutated at runtime
ENGINES: dict[str, type] = {
    "dna":               DnaHelixEngine,
    "rotating":          RotatingHelixEngine,
    "double_helix":      DoubleHelixEngine,
    "double_helix_lit":  DoubleHelixLitEngine,
    "triple_helix":      TripleHelixEngine,
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

# il-a1: animation label registry; written once at module load, never mutated at runtime
ANIMATION_LABELS: dict[str, str] = {
    "dna":               "DNA Double Helix",
    "rotating":          "Rotating 3D Helix",
    "double_helix":      "Double Helix 3D",
    "double_helix_lit":  "Double Helix 3D (Lit)",
    "triple_helix":      "Triple Helix 3D",
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
