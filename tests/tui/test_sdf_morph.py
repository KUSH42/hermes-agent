"""Tests for SDF Morph Engine — 24 tests covering baker, fallback SDF,
morph state, noise, render modes, and engine integration.
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# PIL baking requires FreeType font rendering. Pillow 9.x + Python 3.13 has a
# known incompatibility (render() arg 9 type mismatch). Skip bake-dependent
# tests when PIL can't render text with a FreeType font.
def _pil_bake_works() -> bool:
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("L", (64, 64), 0)
        draw = ImageDraw.Draw(img)
        for path in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
            "/System/Library/Fonts/Menlo.ttc",
        ]:
            try:
                font = ImageFont.truetype(path, 32)
                draw.text((10, 10), "A", fill=255, font=font)
                return True
            except Exception:
                continue
        return False
    except Exception:
        return False

_PIL_BAKE_OK = _pil_bake_works()
requires_pil_bake = pytest.mark.skipif(
    not _PIL_BAKE_OK,
    reason="PIL FreeType text rendering broken on this system (Pillow/Python version mismatch)",
)

from hermes_cli.tui.sdf_morph import (
    SDFBaker,
    SDFMorphEngine,
    MorphState,
    _sdf_from_mask,
    _dead_reckon_sdf,
    _noise_grid,
    _apply_render_mode,
    _resize_sdf,
    _mask_to_canvas,
    _apply_ansi_color,
    _resolve_color,
)


# ═══════════════════════════════════════════════════════════════════════════════
# SDFBaker unit tests (no app needed)  — tests 1–9
# ═══════════════════════════════════════════════════════════════════════════════

@requires_pil_bake
class TestSDFBaker:

    def test_bake_populates_cache_for_all_unique_chars(self):
        """bake() populates cache for all unique chars in string."""
        baker = SDFBaker(resolution=64, font_size=48)
        baker.bake("ABC")
        for ch in "ABC":
            assert ch in baker._cache

    def test_bake_duplicate_chars_single_cache_entry(self):
        """bake() with duplicate chars — only one cache entry created."""
        baker = SDFBaker(resolution=64, font_size=48)
        baker.bake("AAA")
        assert len(baker._cache) == 1
        assert "A" in baker._cache

    def test_get_returns_correct_shape_dtype(self):
        """get() returns ndarray shape (res, res) dtype float32."""
        res = 64
        baker = SDFBaker(resolution=res, font_size=48)
        baker.bake("X")
        arr = baker.get("X")
        assert arr.shape == (res, res)
        assert arr.dtype == np.float32

    def test_sdf_values_normalized_range(self):
        """SDF values are all in [-1.0, 1.0] range after normalization."""
        baker = SDFBaker(resolution=64, font_size=48)
        baker.bake("H")
        arr = baker.get("H")
        assert arr.min() >= -1.0
        assert arr.max() <= 1.0

    def test_sdf_center_value_negative_for_filled_letter(self):
        """SDF min value negative for a filled letter (inside the shape)."""
        baker = SDFBaker(resolution=128, font_size=96)
        baker.bake("O")
        arr = baker.get("O")
        assert arr.min() < 0, f"Min SDF value {arr.min()} should be negative (inside glyph)"

    def test_sdf_corner_value_positive(self):
        """SDF corner value positive (far outside any glyph)."""
        baker = SDFBaker(resolution=128, font_size=96)
        baker.bake("A")
        arr = baker.get("A")
        corner_val = arr[0, 0]
        assert corner_val > 0, f"Corner value {corner_val} should be positive (outside glyph)"

    def test_sdf_near_zero_at_boundary(self):
        """SDF near zero at the glyph boundary (within ±0.15 tolerance)."""
        baker = SDFBaker(resolution=128, font_size=96)
        baker.bake("I")
        arr = baker.get("I")
        # Find values near zero — should exist at boundary
        near_zero = np.abs(arr) < 0.15
        assert near_zero.any(), "No near-zero values found — boundary detection failed"

    def test_space_and_digit_bake_without_error(self):
        """Space character and digit bake without error."""
        baker = SDFBaker(resolution=64, font_size=48)
        baker.bake(" 5")
        assert " " in baker._cache
        assert "5" in baker._cache

    def test_ready_event_not_set_before_bake_set_after(self):
        """baker.ready not set before bake(), set after."""
        baker = SDFBaker(resolution=64, font_size=48)
        assert not baker.ready.is_set()
        baker.bake("X")
        assert baker.ready.is_set()


# ═══════════════════════════════════════════════════════════════════════════════
# _dead_reckon_sdf fallback tests  — tests 10–12
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeadReckonSDF:

    def test_returns_same_shape_as_input(self):
        """Returns array same shape as input mask."""
        mask = np.zeros((32, 32), dtype=bool)
        mask[8:24, 8:24] = True
        sdf = _dead_reckon_sdf(mask)
        assert sdf.shape == mask.shape

    def test_inside_negative_outside_positive(self):
        """Inside pixels have negative values, outside have positive."""
        mask = np.zeros((32, 32), dtype=bool)
        mask[8:24, 8:24] = True
        sdf = _dead_reckon_sdf(mask)
        # Center of filled region should be negative
        assert sdf[16, 16] < 0
        # Corner should be positive
        assert sdf[0, 0] > 0

    def test_simple_rectangle_mask(self):
        """Test with a simple 32×32 filled rectangle mask."""
        mask = np.zeros((32, 32), dtype=bool)
        mask[10:22, 10:22] = True
        sdf = _dead_reckon_sdf(mask)
        # Inside should be negative
        assert sdf[16, 16] < 0
        # Boundary should be near zero
        # Edge pixels of the rectangle should have small absolute values
        edge_val = sdf[10, 16]  # top edge of rectangle
        assert abs(edge_val) < 2.0


# ═══════════════════════════════════════════════════════════════════════════════
# MorphState / _advance_state tests  — tests 13–16
# ═══════════════════════════════════════════════════════════════════════════════

class TestMorphState:

    def test_hold_phase_transitions_to_morph(self):
        """Hold phase transitions to morph after hold_ms elapsed."""
        engine = SDFMorphEngine(text="AB", hold_ms=100, morph_ms=50)
        # Initially in hold phase
        assert engine._state.phase == "hold"
        engine._advance_state(101)
        assert engine._state.phase == "morph"

    def test_t_increases_proportionally_during_morph(self):
        """t increases proportionally to dt_ms / morph_ms during morph."""
        engine = SDFMorphEngine(text="AB", hold_ms=0, morph_ms=1000)
        engine._state.phase = "morph"
        engine._state.phase_elapsed = 0
        engine._advance_state(500)
        assert abs(engine._state.t - 0.5) < 0.01

    def test_t_clamps_and_advances_seq_idx(self):
        """t clamps at 1.0 and transitions back to hold, advancing seq_idx."""
        engine = SDFMorphEngine(text="AB", hold_ms=0, morph_ms=100)
        engine._state.phase = "morph"
        engine._state.phase_elapsed = 90
        engine._advance_state(20)  # total 110ms > 100ms
        assert engine._state.phase == "hold"
        assert engine._state.seq_idx == 1

    def test_seq_idx_wraps_around(self):
        """seq_idx wraps around at end of text string."""
        engine = SDFMorphEngine(text="AB", hold_ms=0, morph_ms=100)
        engine._state.phase = "morph"
        engine._state.phase_elapsed = 90
        engine._state.seq_idx = 1  # at B
        engine._advance_state(20)  # morph done
        assert engine._state.seq_idx == 0  # wraps to 0


# ═══════════════════════════════════════════════════════════════════════════════
# _noise_grid tests  — tests 17–20
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoiseGrid:

    def test_shape_and_range(self):
        """Returns array shape (h, w) with values in [-1, 1]."""
        noise = _noise_grid(50, 30, 0.5)
        assert noise.shape == (30, 50)
        assert noise.min() >= -1.0
        assert noise.max() <= 1.0

    def test_spatially_coherent(self):
        """At least 90% of horizontally adjacent pairs have diff < 0.5."""
        noise = _noise_grid(100, 50, 0.0)
        diffs = np.abs(noise[:, 1:] - noise[:, :-1])
        coherent_frac = (diffs < 0.5).mean()
        assert coherent_frac >= 0.9, f"Only {coherent_frac:.1%} coherent — expected >= 90%"

    def test_different_t_produces_different_grids(self):
        """Different t values produce different grids (animation progresses)."""
        n1 = _noise_grid(40, 20, 0.0)
        n2 = _noise_grid(40, 20, 0.5)
        assert not np.array_equal(n1, n2)

    def test_cache_hit_identical_array(self):
        """Cache hit returns identical array for same (w, h, t_quantized)."""
        _noise_cache_clear()
        # 0.0 and 0.01 both quantize to 0.0 (round(0.5) = 0 in Python)
        n1 = _noise_grid(40, 20, 0.0)
        n2 = _noise_grid(40, 20, 0.01)  # quantizes to 0.0
        np.testing.assert_array_equal(n1, n2)


def _noise_cache_clear():
    from hermes_cli.tui.sdf_morph import _noise_cache
    _noise_cache.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# Frame rendering tests  — tests 21–22
# ═══════════════════════════════════════════════════════════════════════════════

class TestRenderModes:

    def test_filled_more_dots_than_outline(self):
        """Filled mode: sdf < 0 produces more set dots than outline mode."""
        sdf = np.random.randn(40, 80).astype(np.float32) * 0.3
        filled = _apply_render_mode(sdf, "filled", 0.0, 0.08, 0.15)
        outline = _apply_render_mode(sdf, "outline", 0.0, 0.08, 0.15)
        assert filled.sum() > outline.sum(), "Filled should cover more area than outline"

    def test_dissolve_boundary_shift(self):
        """Dissolve mode — mask is neither all-True nor all-False."""
        sdf = np.zeros((40, 80), dtype=np.float32)
        sdf[:, :40] = -0.5  # half inside
        sdf[:, 40:] = 0.5   # half outside
        mask = _apply_render_mode(sdf, "dissolve", 0.5, 0.08, 1.0)
        assert mask.any(), "Dissolve should have some True dots"
        assert not mask.all(), "Dissolve should have some False dots"


# ═══════════════════════════════════════════════════════════════════════════════
# Engine integration tests  — tests 23–24
# ═══════════════════════════════════════════════════════════════════════════════

class TestEngineIntegration:

    def test_sdf_morph_in_animation_keys(self):
        """SDFMorphEngine present in ANIMATION_KEYS."""
        from hermes_cli.tui.drawille_overlay import ANIMATION_KEYS
        assert "sdf_morph" in ANIMATION_KEYS

    def test_sdf_morph_engine_creation(self):
        """SDFMorphEngine can be created without error."""
        engine = SDFMorphEngine(text="AB", hold_ms=100, morph_ms=100)
        assert engine.name == "sdf_morph"
        assert engine._text == "AB"

    def test_tick_returns_none_before_bake(self):
        """tick() returns None before bake completes."""
        engine = SDFMorphEngine(text="AB")
        result = engine.tick(16.0)
        assert result is None

    def test_next_frame_returns_empty_before_bake(self):
        """next_frame() returns empty string before bake completes."""
        engine = SDFMorphEngine(text="AB")
        params = MagicMock()
        params.dt = 1 / 15
        params.width = 50
        params.height = 14
        result = engine.next_frame(params)
        assert result == ""

    def test_text_minimum_length(self):
        """Text shorter than 2 chars gets padded."""
        engine = SDFMorphEngine(text="A")
        assert len(engine._text) >= 2
