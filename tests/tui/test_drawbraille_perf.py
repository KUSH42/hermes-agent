"""Tests for drawbraille animation performance optimisations.

Covers:
  A1 — divisor hoists (PerlinFlow, FluidField, WaveFunction)
  A2 — try/except → bounds check (parametrized engine smoke)
  A3 — TrailCanvas canvas reuse
  A4 — NeuralPulse edge-step cache
  A5 — _render_multi_color divisor hoist (smoke)
  B1 — _SIN_LUT / _COS_LUT accuracy + engine smokes
  B2 — _render_multi_color buffer reuse
  B3 — _layer_frames buffer cleared between calls
"""
from __future__ import annotations

import math
import types
import unittest.mock as mock

import pytest

from hermes_cli.tui.anim_engines import (
    AnimParams,
    TrailCanvas,
    NeuralPulseEngine,
    PerlinFlowEngine,
    FluidFieldEngine,
    WaveFunctionEngine,
    WaveInterferenceEngine,
    AuroraRibbonEngine,
    LissajousWeaveEngine,
    MandalaBloomEngine,
    FlockSwarmEngine,
    ConwayLifeEngine,
    HyperspaceEngine,
    RopeBraidEngine,
    _layer_frames,
    _SIN_LUT,
    _COS_LUT,
    _lut_sin,
    _lut_cos,
    _LAYER_ROW_BUF,
    _LAYER_RESULT_BUF,
    _BOID_CELL_SIZE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _small_params(**kw) -> AnimParams:
    defaults = dict(width=20, height=10, t=0.0, dt=1/15, particle_count=10, heat=0.5)
    defaults.update(kw)
    return AnimParams(**defaults)


# ── A1 — Divisor hoists ───────────────────────────────────────────────────────

def test_perlin_flow_no_per_pixel_division():
    """Smoke: PerlinFlowEngine.next_frame() runs without error and returns non-empty."""
    eng = PerlinFlowEngine()
    params = _small_params(width=10, height=6)
    results = [eng.next_frame(params) for _ in range(3)]
    assert all(isinstance(r, str) and len(r) > 0 for r in results)


def test_fluid_field_no_per_pixel_division():
    """Smoke: FluidFieldEngine.next_frame() runs without error and returns non-empty."""
    eng = FluidFieldEngine()
    params = _small_params(width=10, height=6)
    results = [eng.next_frame(params) for _ in range(3)]
    assert all(isinstance(r, str) and len(r) > 0 for r in results)


def test_wave_function_no_per_pixel_division():
    """Smoke: WaveFunctionEngine.next_frame() runs without error and returns non-empty."""
    eng = WaveFunctionEngine()
    params = _small_params(width=10, height=6)
    results = [eng.next_frame(params) for _ in range(3)]
    assert all(isinstance(r, str) and len(r) > 0 for r in results)


# ── A2 — Bounds check (no exception on small canvas) ─────────────────────────

_SMALL_ENGINES = [
    NeuralPulseEngine,
    FlockSwarmEngine,
    ConwayLifeEngine,
    HyperspaceEngine,
    PerlinFlowEngine,
    FluidFieldEngine,
    LissajousWeaveEngine,
    MandalaBloomEngine,
    RopeBraidEngine,
    WaveFunctionEngine,
    WaveInterferenceEngine,
]


@pytest.mark.parametrize("cls", _SMALL_ENGINES, ids=lambda c: c.__name__)
def test_bounds_check_no_exception_small_canvas(cls):
    """No exception when canvas is tiny (w=4, h=4 — guaranteed OOB attempts)."""
    eng = cls()
    # Very small canvas forces many OOB attempts
    params = _small_params(width=4, height=4)
    for _ in range(3):
        result = eng.next_frame(params)
        assert isinstance(result, str)


# ── A3 — TrailCanvas canvas reuse ─────────────────────────────────────────────

def test_trail_canvas_fresh_canvas_per_call():
    """TrailCanvas.to_canvas() returns a fresh BrailleCanvas each call (no pooling)."""
    from hermes_cli.tui.braille_canvas import BrailleCanvas
    tc = TrailCanvas()
    tc.set(1, 1)
    tc.set(2, 2)

    c1 = tc.to_canvas()
    c2 = tc.to_canvas()

    assert isinstance(c1, BrailleCanvas)
    assert isinstance(c2, BrailleCanvas)
    assert c1 is not c2, "to_canvas() should return a new canvas each call"


# ── A4 — NeuralPulse edge step cache ─────────────────────────────────────────

def test_neural_pulse_edge_steps_cached():
    """After _init(), _edge_steps is populated and values match math.hypot."""
    eng = NeuralPulseEngine()
    eng._init(50, 20, 10)

    assert hasattr(eng, "_edge_steps"), "_edge_steps attribute missing"
    assert len(eng._edge_steps) > 0, "_edge_steps is empty after _init"

    # Spot-check: every cached step should equal max(int(hypot(...)), 1)
    for (i, j), cached_steps in eng._edge_steps.items():
        ax, ay = eng._nodes[i]
        bx, by = eng._nodes[j]
        expected = max(int(math.hypot(bx - ax, by - ay)), 1)
        assert cached_steps == expected, (
            f"Edge ({i},{j}): cached={cached_steps}, expected={expected}"
        )


# ── A5 — _render_multi_color divisor hoist smoke ─────────────────────────────

def test_render_multi_color_divisor_hoisted():
    """_render_multi_color returns Text with non-zero spans (smoke for hoist correctness)."""
    from rich.text import Text
    from hermes_cli.tui.drawbraille_renderer import DrawbrailleRenderer as DrawbrailleOverlay
    from hermes_cli.tui.animation import _parse_rgb

    # Build a minimal stub that has just the attributes the method reads
    class _Stub:
        _resolved_multi_colors = ["#ff0000", "#00ff00", "#0000ff"]
        _resolved_multi_color_rgbs = [_parse_rgb(c) for c in _resolved_multi_colors]
        hue_shift_speed = 0.3
        _multi_color_row_buf: list = []

    stub = _Stub()
    # Call the unbound method with our stub
    frame = "abc\ndef"
    result = DrawbrailleOverlay._render_multi_color(stub, frame, 0.0, stub.hue_shift_speed)  # type: ignore[arg-type]
    assert isinstance(result, Text)
    assert len(result._spans) > 0


# ── B1 — LUT accuracy ─────────────────────────────────────────────────────────

def test_lut_sin_accuracy():
    """_lut_sin(a) ≈ math.sin(a) within 0.01 for 50 angles in [0, 2π]."""
    import random
    rng = random.Random(42)
    for _ in range(50):
        a = rng.uniform(0, 2 * math.pi)
        assert abs(_lut_sin(a) - math.sin(a)) < 0.01, (
            f"LUT sin error too large at {a}: {abs(_lut_sin(a) - math.sin(a))}"
        )


def test_lut_cos_accuracy():
    """_lut_cos(a) ≈ math.cos(a) within 0.01 for 50 angles in [0, 2π]."""
    import random
    rng = random.Random(42)
    for _ in range(50):
        a = rng.uniform(0, 2 * math.pi)
        assert abs(_lut_cos(a) - math.cos(a)) < 0.01, (
            f"LUT cos error too large at {a}: {abs(_lut_cos(a) - math.cos(a))}"
        )


def test_wave_interference_smoke_lut():
    eng = WaveInterferenceEngine()
    params = _small_params(width=20, height=10)
    for _ in range(3):
        r = eng.next_frame(params)
        assert isinstance(r, str) and len(r) > 0


def test_perlin_flow_smoke_lut():
    eng = PerlinFlowEngine()
    params = _small_params(width=20, height=10)
    for _ in range(3):
        r = eng.next_frame(params)
        assert isinstance(r, str) and len(r) > 0


def test_aurora_ribbon_smoke_lut():
    eng = AuroraRibbonEngine()
    params = _small_params(width=20, height=10)
    for _ in range(3):
        r = eng.next_frame(params)
        assert isinstance(r, str) and len(r) > 0


def test_lissajous_smoke_lut():
    eng = LissajousWeaveEngine()
    params = _small_params(width=20, height=10)
    for _ in range(3):
        r = eng.next_frame(params)
        assert isinstance(r, str) and len(r) > 0


def test_mandala_smoke_lut():
    eng = MandalaBloomEngine()
    params = _small_params(width=20, height=10)
    for _ in range(3):
        r = eng.next_frame(params)
        assert isinstance(r, str) and len(r) > 0


# ── B2 — _render_multi_color buffer reuse ────────────────────────────────────

def _make_multi_color_stub(colors, hue_shift_speed=0.3):
    """Build a minimal stub for DrawbrailleOverlay._render_multi_color."""
    from hermes_cli.tui.animation import _parse_rgb

    class _Stub:
        pass

    stub = _Stub()
    stub._resolved_multi_colors = list(colors)
    stub._resolved_multi_color_rgbs = [_parse_rgb(c) for c in colors]
    stub.hue_shift_speed = hue_shift_speed
    stub._multi_color_row_buf = []
    return stub


def test_render_multi_color_buffer_reuse():
    """Same list object should be reused on second call with same row width."""
    from hermes_cli.tui.drawbraille_renderer import DrawbrailleRenderer as DrawbrailleOverlay

    stub = _make_multi_color_stub(["#ff0000", "#0000ff"])
    frame = "abcde\nfghij"
    DrawbrailleOverlay._render_multi_color(stub, frame, 0.0, stub.hue_shift_speed)  # type: ignore[arg-type]
    buf_id = id(stub._multi_color_row_buf)

    DrawbrailleOverlay._render_multi_color(stub, frame, 0.1, stub.hue_shift_speed)  # type: ignore[arg-type]
    assert id(stub._multi_color_row_buf) == buf_id, "Buffer list was reallocated"


def test_render_multi_color_correct_output():
    """Regression: output Text has the right number of characters."""
    from rich.text import Text
    from hermes_cli.tui.drawbraille_renderer import DrawbrailleRenderer as DrawbrailleOverlay

    stub = _make_multi_color_stub(["#ff0000", "#00ff00"], hue_shift_speed=0.0)
    frame = "hello"
    result = DrawbrailleOverlay._render_multi_color(stub, frame, 0.0, stub.hue_shift_speed)  # type: ignore[arg-type]
    assert isinstance(result, Text)
    plain = result.plain
    assert "hello" in plain


# ── B3 — _layer_frames buffer cleared between calls ──────────────────────────

def _braille(c: int) -> str:
    """Return a braille char with given bit pattern."""
    return chr(0x2800 | c)


def _make_frame(rows: list[str]) -> str:
    return "\n".join(rows)


def test_layer_frames_overlay_mode():
    """overlay mode: upper layer (b) non-zero bits win."""
    # a = all bits set (0xFF), b = 0 → result keeps a's bits
    row_a = _braille(0xFF) * 3
    row_b = _braille(0x00) * 3
    fa = _make_frame([row_a])
    fb = _make_frame([row_b])
    result = _layer_frames(fa, fb, "overlay")
    # b is all-zero → a should win
    assert result == row_a


def test_layer_frames_additive_mode():
    """additive (OR) mode: bits from both frames combined."""
    row_a = _braille(0b00001111) * 2
    row_b = _braille(0b11110000) * 2
    fa = _make_frame([row_a])
    fb = _make_frame([row_b])
    result = _layer_frames(fa, fb, "additive")
    expected = _braille(0xFF) * 2
    assert result == expected


def test_layer_frames_xor_mode():
    """xor mode: bits XOR'd between frames."""
    row_a = _braille(0b11111111) * 2
    row_b = _braille(0b11110000) * 2
    fa = _make_frame([row_a])
    fb = _make_frame([row_b])
    result = _layer_frames(fa, fb, "xor")
    expected = _braille(0b00001111) * 2
    assert result == expected


def test_layer_frames_buffer_cleared_between_calls():
    """Buffer is properly cleared — second call with different frames gives different result."""
    row_a1 = _braille(0b00001111) * 3
    row_b1 = _braille(0b11110000) * 3
    fa1 = _make_frame([row_a1])
    fb1 = _make_frame([row_b1])
    result1 = _layer_frames(fa1, fb1, "additive")
    assert result1 == _braille(0xFF) * 3

    # Different frames
    row_a2 = _braille(0b00000001) * 3
    row_b2 = _braille(0b00000010) * 3
    fa2 = _make_frame([row_a2])
    fb2 = _make_frame([row_b2])
    result2 = _layer_frames(fa2, fb2, "additive")
    assert result2 == _braille(0b00000011) * 3

    # Results should differ
    assert result1 != result2


# ── H1 — FlockSwarmEngine spatial grid ───────────────────────────────────────

def test_flock_grid_built_after_next_frame():
    """_grid is non-empty after next_frame() when boids exist."""
    eng = FlockSwarmEngine()
    params = _small_params(width=100, height=56, particle_count=20)
    eng.next_frame(params)
    assert len(eng._grid) > 0, "_grid should be non-empty after next_frame()"


def test_flock_cell_size_covers_max_radius():
    """_BOID_CELL_SIZE must be >= 20 (max boid interaction radius)."""
    assert _BOID_CELL_SIZE >= 20, (
        f"_BOID_CELL_SIZE={_BOID_CELL_SIZE} is less than the max interaction radius 20"
    )


def test_flock_no_self_in_neighbors():
    """Engine runs without crash — self-skip guard prevents j==i from corrupting steering."""
    eng = FlockSwarmEngine()
    params = _small_params(width=100, height=56, particle_count=10)
    result = eng.next_frame(params)
    assert isinstance(result, str) and len(result) > 0


def test_flock_smoke_small_canvas():
    """next_frame() on 20×10 returns non-empty string."""
    eng = FlockSwarmEngine()
    params = _small_params(width=20, height=10, particle_count=10)
    result = eng.next_frame(params)
    assert isinstance(result, str) and len(result) > 0


def test_flock_smoke_medium_canvas():
    """next_frame() on 100×56 returns non-empty string."""
    eng = FlockSwarmEngine()
    params = _small_params(width=100, height=56, particle_count=30)
    result = eng.next_frame(params)
    assert isinstance(result, str) and len(result) > 0


def test_flock_smoke_large_canvas():
    """next_frame() on 160×96 returns non-empty string."""
    eng = FlockSwarmEngine()
    params = _small_params(width=160, height=96, particle_count=60)
    result = eng.next_frame(params)
    assert isinstance(result, str) and len(result) > 0


def test_flock_scatter_path_unaffected():
    """scatter=True → next_frame() still returns a non-empty string."""
    eng = FlockSwarmEngine()
    params = _small_params(width=100, height=56, particle_count=20)
    # Initialize first
    eng.next_frame(params)
    # Trigger scatter via on_signal
    eng.on_signal("complete")
    result = eng.next_frame(params)
    assert isinstance(result, str) and len(result) > 0


def test_flock_signals_still_apply():
    """Each on_signal() variant followed by next_frame() completes without error."""
    signals = ["thinking", "reasoning", "tool", "complete", "error"]
    for sig in signals:
        eng = FlockSwarmEngine()
        params = _small_params(width=100, height=56, particle_count=20)
        eng.next_frame(params)  # init
        eng.on_signal(sig)
        result = eng.next_frame(params)
        assert isinstance(result, str), f"next_frame() returned non-str after signal '{sig}'"


def test_flock_grid_neighbor_count_bounded():
    """Average grid-neighbor count per boid is less than n-1 on a medium canvas."""
    eng = FlockSwarmEngine()
    n = 30
    params = _small_params(width=100, height=56, particle_count=n)
    eng.next_frame(params)  # init + first frame

    w, h = params.width, params.height
    n_cols = max(1, (w - 1) // _BOID_CELL_SIZE + 1)
    n_rows = max(1, (h - 1) // _BOID_CELL_SIZE + 1)
    grid = eng._grid

    total_neighbors = 0
    for i, b in enumerate(eng._boids):
        bx_cell = int(b[0] / _BOID_CELL_SIZE)
        by_cell = int(b[1] / _BOID_CELL_SIZE)
        count = 0
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                nc = bx_cell + dc
                nr = by_cell + dr
                if nc < 0 or nc >= n_cols or nr < 0 or nr >= n_rows:
                    continue
                for j in grid.get((nc, nr), ()):
                    if j != i:
                        count += 1
        total_neighbors += count

    avg = total_neighbors / max(len(eng._boids), 1)
    assert avg < n - 1, (
        f"avg grid neighbors {avg:.1f} is not less than n-1={n - 1}; "
        "grid is not filtering boids"
    )


def test_flock_grid_reuses_dict():
    """id(eng._grid) is the same object across 3 consecutive next_frame() calls."""
    eng = FlockSwarmEngine()
    params = _small_params(width=100, height=56, particle_count=20)
    eng.next_frame(params)
    grid_id = id(eng._grid)
    for _ in range(2):
        eng.next_frame(params)
        assert id(eng._grid) == grid_id, (
            "eng._grid dict was replaced — should be cleared and reused, not reallocated"
        )
