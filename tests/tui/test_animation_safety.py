"""Tests for SPEC-ANM: animation reentrancy + LRU cache + perf probe.

ANM-1: _layer_frames per-call locals (TestLayerFramesReentrancy)
ANM-3: _RGB_CACHE → _rgb_cached LRU (TestRgbCacheLru)
ANM-2: apply_external_trail perf probe (TestExternalTrailPerf)
"""
from __future__ import annotations

import sys
import pathlib
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is in sys.path
_REPO_ROOT = pathlib.Path(__file__).parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hermes_cli.tui import anim_engines
from hermes_cli.tui.anim_engines import _layer_frames, AnimParams, CompositeEngine
from hermes_cli.tui.animation import _rgb_cached
from hermes_cli.tui.braille_canvas import BrailleCanvas


# ---------------------------------------------------------------------------
# ANM-1: _layer_frames reentrancy
# ---------------------------------------------------------------------------

class TestLayerFramesReentrancy:
    """ANM-1: _layer_frames must use per-call locals, not module-level buffers."""

    def test_module_level_layer_buf_not_present(self) -> None:
        """Module must not expose _LAYER_ROW_BUF or _LAYER_RESULT_BUF."""
        assert not hasattr(anim_engines, "_LAYER_ROW_BUF"), (
            "_LAYER_ROW_BUF should have been deleted (ANM-1 per-call locals)"
        )
        assert not hasattr(anim_engines, "_LAYER_RESULT_BUF"), (
            "_LAYER_RESULT_BUF should have been deleted (ANM-1 per-call locals)"
        )

    def test_layer_frames_direct_call_is_reentrant(self) -> None:
        """Calling _layer_frames while a conceptual second call is in progress
        must return independent correct results.

        We simulate reentrancy by running two independent calls sequentially and
        verifying neither poisons the other's output. (True concurrent reentrancy
        would require threads; this covers the nested-CompositeEngine path.)
        """
        # Build two 1-column, 1-row frames with different bits
        # Frame A: bit 0 only → chr(0x2800 | 0x01) = '⠁'
        # Frame B: bit 1 only → chr(0x2800 | 0x02) = '⠂'
        fa = chr(0x2801)  # braille single dot top-left
        fb = chr(0x2802)  # braille single dot second position

        result_ab = _layer_frames(fa, fb, "additive")
        result_ba = _layer_frames(fb, fa, "additive")

        # additive = OR of bits; both should be bit0|bit1 = 0x03 = '⠃'
        expected = chr(0x2803)
        assert result_ab == expected, f"Expected {repr(expected)}, got {repr(result_ab)}"
        assert result_ba == expected, f"Expected {repr(expected)}, got {repr(result_ba)}"

        # Also verify xor: a XOR b = 0x01 ^ 0x02 = 0x03 (same bits, still '⠃')
        result_xor = _layer_frames(fa, fb, "xor")
        assert result_xor == expected

        # overlay: b wins when non-zero → should be fb
        result_ov = _layer_frames(fa, fb, "overlay")
        assert result_ov == fb

    def test_nested_composite_engine_no_clobber(self) -> None:
        """Nested CompositeEngine([CompositeEngine([a, b]), c]) must not clobber buffers.

        With per-call locals, each _layer_frames invocation is independent.
        We verify that the final frame is the additive OR of all three single-dot frames.
        """
        # Three engines returning single-dot frames with different bit positions
        class _FixedEngine:
            def __init__(self, bits: int) -> None:
                self._ch = chr(0x2800 | bits)
            def next_frame(self, params: AnimParams) -> str:
                return self._ch

        params = AnimParams(width=2, height=4)

        engine_a = _FixedEngine(0x01)  # bit 0
        engine_b = _FixedEngine(0x02)  # bit 1
        engine_c = _FixedEngine(0x04)  # bit 2

        inner = CompositeEngine([engine_a, engine_b], blend_mode="additive")
        outer = CompositeEngine([inner, engine_c], blend_mode="additive")

        result = outer.next_frame(params)

        # Expected: 0x01 | 0x02 | 0x04 = 0x07 = '⠇'
        expected = chr(0x2807)
        assert result == expected, (
            f"Nested CompositeEngine returned {repr(result)}, expected {repr(expected)}"
        )


# ---------------------------------------------------------------------------
# ANM-3: _rgb_cached LRU
# ---------------------------------------------------------------------------

class TestRgbCacheLru:
    """ANM-3: _rgb_cached must use functools.lru_cache with maxsize=256."""

    def setup_method(self) -> None:
        """Clear lru_cache before each test for isolation."""
        _rgb_cached.cache_clear()

    def test_rgb_cache_evicts_least_recently_used(self) -> None:
        """Fill to maxsize, re-access an early entry, add one more.

        The LRU eviction should not drop the recently re-accessed entry.
        currsize must remain 256 (at capacity).
        """
        # Fill cache with 256 distinct hex strings
        for i in range(256):
            hex_str = f"#{i:02x}{i:02x}{i:02x}"
            _rgb_cached(hex_str)

        # Re-access the very first entry to make it "recently used"
        _rgb_cached("#000000")

        # Add one more (257th unique entry) — should evict LRU (entry #1 = #010101)
        _rgb_cached("#ffffff")

        info = _rgb_cached.cache_info()
        assert info.currsize == 256, (
            f"Expected currsize=256 after add-one-past-limit, got {info.currsize}"
        )

    def test_rgb_cache_correctness_after_eviction(self) -> None:
        """Evict a previously cached entry, re-call it, assert correct RGB tuple."""
        # Fill to capacity with entries that will push #000000 out
        _rgb_cached("#000000")  # cache it first
        for i in range(1, 257):
            _rgb_cached(f"#{i:02x}{i:02x}{i:02x}")

        # Now re-call the potentially evicted entry
        result = _rgb_cached("#000000")
        assert result == (0, 0, 0), f"Expected (0, 0, 0), got {result}"

        # Also test a known color
        result_ff = _rgb_cached("#ff8040")
        assert result_ff == (0xFF, 0x80, 0x40), f"Expected (255,128,64), got {result_ff}"


# ---------------------------------------------------------------------------
# ANM-2: apply_external_trail perf probe
# ---------------------------------------------------------------------------

class TestExternalTrailPerf:
    """ANM-2: apply_external_trail must record to PerfRegistry via measure()."""

    def _make_orchestrator(self) -> object:
        """Return a minimal AnimOrchestrator with a mock overlay."""
        from hermes_cli.tui.anim_orchestrator import AnimOrchestrator
        mock_overlay = MagicMock()
        return AnimOrchestrator(mock_overlay)

    def _make_params(self) -> AnimParams:
        return AnimParams(width=2, height=4)

    def _make_cfg(self, trail_decay: float = 0.85) -> MagicMock:
        cfg = MagicMock()
        cfg.trail_decay = trail_decay
        return cfg

    def _simple_frame(self) -> str:
        """A 1-cell braille frame with one dot set."""
        c = BrailleCanvas()
        c.set(0, 0)
        return c.frame()

    def test_apply_external_trail_perf_probe_records(self) -> None:
        """Calling apply_external_trail must record 'apply_external_trail' in PerfRegistry."""
        import hermes_cli.tui.perf as perf_mod
        # Clear existing samples
        perf_mod._registry.clear("apply_external_trail")

        orch = self._make_orchestrator()
        orch._current_engine_instance = None
        frame = self._simple_frame()

        orch.apply_external_trail(frame, self._make_params(), self._make_cfg())

        samples = perf_mod._registry.samples("apply_external_trail")
        assert len(samples) >= 1, (
            "PerfRegistry should have at least one 'apply_external_trail' sample after the call"
        )

    def test_apply_external_trail_correctness_unchanged(self) -> None:
        """Golden-frame test: single-dot input → same single-dot output after one pass."""
        from tests.tui._anim_golden_frames import APPLY_EXTERNAL_TRAIL_SINGLE_DOT_FRAME_1

        orch = self._make_orchestrator()
        orch._current_engine_instance = None
        frame = self._simple_frame()  # '⠁'

        result = orch.apply_external_trail(frame, self._make_params(), self._make_cfg())

        assert result == APPLY_EXTERNAL_TRAIL_SINGLE_DOT_FRAME_1, (
            f"Golden frame mismatch: expected {repr(APPLY_EXTERNAL_TRAIL_SINGLE_DOT_FRAME_1)}, "
            f"got {repr(result)}"
        )

    def test_apply_external_trail_budget_warning_on_overrun(self) -> None:
        """When budget_ms=0, measure() should always log an OVER-budget warning."""
        import hermes_cli.tui.perf as perf_mod

        # Patch the module-level logger in perf to capture warning calls
        with patch.object(perf_mod, "log") as mock_log:
            # Patch measure to use budget_ms=0 by wrapping it
            original_measure = perf_mod.measure

            import contextlib

            @contextlib.contextmanager
            def measure_zero_budget(label: str, budget_ms: float = 16.67, *, silent: bool = False):
                with original_measure(label, budget_ms=0.0, silent=silent) as r:
                    yield r

            from hermes_cli.tui import anim_orchestrator
            with patch.object(anim_orchestrator, "measure", measure_zero_budget):
                orch = self._make_orchestrator()
                orch._current_engine_instance = None
                frame = self._simple_frame()
                orch.apply_external_trail(frame, self._make_params(), self._make_cfg())

        # The perf logger is a Textual log() callable; check that warning was emitted
        # via mock_log.warning (log.warning is the OVER-budget path in perf.measure)
        warning_calls = mock_log.warning.call_args_list
        assert any("OVER" in str(call) for call in warning_calls), (
            f"Expected a warning containing 'OVER' for zero-budget measure, "
            f"got calls: {warning_calls}"
        )
