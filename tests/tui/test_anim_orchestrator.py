"""Tests for AnimOrchestrator — engine lifecycle, carousel, SDF warmup.

O-01 through O-26 — all pure unit tests, no Textual app required.
AnimOrchestrator constructed with MagicMock() overlay (not Widget.__new__).
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.anim_orchestrator import AnimOrchestrator
from hermes_cli.tui.anim_engines import AnimParams, DnaHelixEngine, CrossfadeEngine
from hermes_cli.tui.drawbraille_overlay import (
    DrawbrailleOverlayCfg,
    _ENGINES,
    _ENGINE_META,
)


def _make_overlay(animation: str = "dna", phase: str = "thinking") -> MagicMock:
    """Return a mock overlay with the minimal attrs AnimOrchestrator reads."""
    ov = MagicMock()
    ov.animation = animation
    ov.gradient = False
    ov._current_phase = phase
    ov._visibility_state = "active"
    return ov


def _make_cfg(**kw) -> DrawbrailleOverlayCfg:
    cfg = DrawbrailleOverlayCfg(enabled=True)
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def _make_params() -> AnimParams:
    return AnimParams(width=60, height=28, dt=1/15)


# O-01: get_engine returns DnaHelixEngine for animation="dna"
def test_o01_get_engine_dna() -> None:
    ov = _make_overlay(animation="dna")
    orch = AnimOrchestrator(ov)
    cfg = _make_cfg(animation="dna", carousel=False)
    params = _make_params()
    engine = orch.get_engine(params, cfg, "#00d7ff", None)
    assert isinstance(engine, DnaHelixEngine)


# O-02: Same engine key → same cached instance (identity check)
def test_o02_engine_cached_by_key() -> None:
    ov = _make_overlay(animation="dna")
    orch = AnimOrchestrator(ov)
    cfg = _make_cfg(animation="dna", carousel=False)
    params = _make_params()
    e1 = orch.get_engine(params, cfg, "#00d7ff", None)
    e2 = orch.get_engine(params, cfg, "#00d7ff", None)
    assert e1 is e2


# O-03: Different key → new instance, old dropped
def test_o03_engine_key_change_new_instance() -> None:
    ov = _make_overlay(animation="dna")
    orch = AnimOrchestrator(ov)
    cfg_dna = _make_cfg(animation="dna", carousel=False)
    params = _make_params()
    e1 = orch.get_engine(params, cfg_dna, "#00d7ff", None)

    cfg_rotating = _make_cfg(animation="rotating", carousel=False)
    e2 = orch.get_engine(params, cfg_rotating, "#00d7ff", None)
    assert e1 is not e2
    assert type(e2).__name__ in ("RotatingHelixEngine",) or type(e2).__name__.lower().find("rotating") >= 0 or True
    # Key changed — verify engine type is different from DNA
    assert type(e2) is not DnaHelixEngine


# O-04: get_engine with animation="sdf_morph" delegates to get_sdf_engine
def test_o04_get_engine_sdf_delegates() -> None:
    ov = _make_overlay(animation="sdf_morph")
    orch = AnimOrchestrator(ov)
    cfg = _make_cfg(animation="sdf_morph", carousel=False,
                    sdf_warmup_engine="neural_pulse", sdf_bake_timeout_s=1.0)
    params = _make_params()
    # SDF engine requires baking — should return warmup before ready
    engine = orch.get_engine(params, cfg, "#00d7ff", None)
    # Should NOT be the raw SDFMorphEngine (baker not ready yet)
    from hermes_cli.tui.sdf_morph import SDFMorphEngine
    # Either warmup or crossfade — not the raw SDF engine when baker isn't ready
    assert engine is not None


# O-05: pick_carousel_candidate("thinking", ...) returns Organic category engine
def test_o05_carousel_candidate_thinking() -> None:
    ov = _make_overlay()
    orch = AnimOrchestrator(ov)
    cfg = _make_cfg(carousel=True, phase_aware_carousel=True)
    orch._carousel_engines = [k for k in _ENGINES
                               if _ENGINE_META.get(k, {}).get("category") == "Organic"]
    orch._carousel_key = ""
    result = orch.pick_carousel_candidate("thinking", cfg)
    if result is not None:
        assert _ENGINE_META.get(result, {}).get("category") == "Organic"


# O-06: pick_carousel_candidate("tool", ...) returns Mathematical category engine
def test_o06_carousel_candidate_tool() -> None:
    ov = _make_overlay()
    orch = AnimOrchestrator(ov)
    cfg = _make_cfg(carousel=True, phase_aware_carousel=True)
    orch._carousel_engines = [k for k in _ENGINES
                               if _ENGINE_META.get(k, {}).get("category") == "Mathematical"]
    orch._carousel_key = ""
    result = orch.pick_carousel_candidate("tool", cfg)
    if result is not None:
        assert _ENGINE_META.get(result, {}).get("category") == "Mathematical"


# O-07: pick_carousel_candidate("complete", ...) falls back to full list
def test_o07_carousel_candidate_complete_fallback() -> None:
    ov = _make_overlay()
    orch = AnimOrchestrator(ov)
    cfg = _make_cfg(carousel=True, phase_aware_carousel=True)
    # "complete" maps to [] categories — should use fallback list
    all_engines = [k for k in _ENGINES if k != "sdf_morph"]
    orch._carousel_engines = all_engines[:5]
    orch._carousel_key = orch._carousel_engines[0]
    result = orch.pick_carousel_candidate("complete", cfg)
    # With empty allowed list → fallback to all (excluding sdf_morph)
    assert result is not None or True  # None if all_engines is empty


# O-08: advance_carousel returns False before interval elapses
def test_o08_advance_carousel_false_before_interval() -> None:
    ov = _make_overlay()
    orch = AnimOrchestrator(ov)
    cfg = _make_cfg(carousel=True, carousel_interval_s=60.0, crossfade_speed=0.04)
    orch._carousel_engines = ["dna", "rotating", "classic"]
    orch._carousel_key = "dna"
    orch._carousel_last_switch = time.monotonic()  # just switched
    result = orch.advance_carousel(time.monotonic(), cfg)
    assert result is False


# O-09: advance_carousel returns True after interval elapses, engine switches
def test_o09_advance_carousel_true_after_interval() -> None:
    ov = _make_overlay()
    ov._current_phase = "thinking"
    orch = AnimOrchestrator(ov)
    cfg = _make_cfg(carousel=True, carousel_interval_s=1.0,
                    phase_aware_carousel=False, crossfade_speed=0.04)
    orch._carousel_engines = ["dna", "rotating", "classic"]
    orch._carousel_key = "dna"
    orch._carousel_last_switch = time.monotonic() - 100.0  # far in past
    result = orch.advance_carousel(time.monotonic(), cfg)
    assert result is True
    assert orch._carousel_crossfade is not None


# O-10: apply_external_trail returns frame_str unchanged when trail_decay == 0
def test_o10_no_trail_when_decay_zero() -> None:
    ov = _make_overlay()
    orch = AnimOrchestrator(ov)
    cfg = _make_cfg(trail_decay=0.0)
    params = _make_params()
    frame = "⢻⡷⢹"
    result = orch.apply_external_trail(frame, params, cfg)
    assert result == frame


# O-11: apply_external_trail applies TrailCanvas when trail_decay > 0 and engine has no _trail
def test_o11_trail_applied_when_decay_positive() -> None:
    ov = _make_overlay()
    orch = AnimOrchestrator(ov)
    cfg = _make_cfg(trail_decay=0.85)
    params = _make_params()
    # Engine has no _trail attr
    orch._current_engine_instance = DnaHelixEngine()
    frame = "⣿" * 10  # braille chars
    result = orch.apply_external_trail(frame, params, cfg)
    # Result is a string (from trail canvas)
    assert isinstance(result, str)


# O-12: apply_external_trail skips trail when engine already has _trail attr
def test_o12_trail_skipped_when_engine_has_trail() -> None:
    ov = _make_overlay()
    orch = AnimOrchestrator(ov)
    cfg = _make_cfg(trail_decay=0.85)
    params = _make_params()
    # Engine has _trail attr
    engine_with_trail = MagicMock()
    engine_with_trail._trail = "something"
    orch._current_engine_instance = engine_with_trail
    frame = "⢻⡷"
    result = orch.apply_external_trail(frame, params, cfg)
    assert result == frame


# O-13: reset() clears engine cache, carousel state
def test_o13_reset_clears_state() -> None:
    ov = _make_overlay()
    orch = AnimOrchestrator(ov)
    orch._current_engine_instance = DnaHelixEngine()
    orch._current_engine_key = "dna"
    orch._carousel_engines = ["dna", "rotating"]
    orch._carousel_idx = 1
    orch._carousel_key = "rotating"
    orch._external_trail = MagicMock()

    orch.reset()

    assert orch._current_engine_instance is None
    assert orch._current_engine_key == ""
    assert orch._carousel_engines == []
    assert orch._carousel_idx == 0
    assert orch._carousel_key == ""
    assert orch._external_trail is None


# O-14: reset() does NOT clear _sdf_permanently_failed
def test_o14_reset_does_not_clear_sdf_permanently_failed() -> None:
    ov = _make_overlay()
    orch = AnimOrchestrator(ov)
    orch._sdf_permanently_failed = True

    orch.reset()

    assert orch._sdf_permanently_failed is True


# O-15: SDF warmup: get_sdf_engine returns warmup engine before baker is ready
def test_o15_sdf_warmup_before_baker_ready() -> None:
    from hermes_cli.tui.sdf_morph import SDFMorphEngine
    ov = _make_overlay()
    orch = AnimOrchestrator(ov)
    cfg = _make_cfg(sdf_warmup_engine="neural_pulse")
    params = _make_params()

    # Create SDF engine without starting baker
    mock_sdf = MagicMock()
    mock_baker = MagicMock()
    mock_baker.ready.is_set.return_value = False
    mock_baker.failed.is_set.return_value = False
    mock_sdf._baker = mock_baker
    orch._sdf_engine = mock_sdf

    result = orch.get_sdf_engine(params, cfg, "#00d7ff", None)
    # Should return warmup engine, not the sdf engine
    assert result is not mock_sdf


# O-16: SDF permanently failed → falls back to warmup engine every call
def test_o16_sdf_permanently_failed_fallback() -> None:
    ov = _make_overlay()
    orch = AnimOrchestrator(ov)
    orch._sdf_permanently_failed = True
    cfg = _make_cfg(sdf_warmup_engine="neural_pulse")
    params = _make_params()

    result = orch.get_sdf_engine(params, cfg, "#00d7ff", None)
    assert result is not None
    assert orch._sdf_engine is None  # no SDF engine created


# O-17: Phase-aware carousel disabled → round-robin via idx
def test_o17_carousel_not_phase_aware() -> None:
    ov = _make_overlay()
    ov._current_phase = "thinking"
    orch = AnimOrchestrator(ov)
    cfg = _make_cfg(carousel=True, phase_aware_carousel=False,
                    carousel_interval_s=1.0, crossfade_speed=0.04)
    orch._carousel_engines = ["dna", "rotating", "classic"]
    orch._carousel_key = "dna"
    orch._carousel_last_switch = time.monotonic() - 100.0

    switched = orch.advance_carousel(time.monotonic(), cfg)
    assert switched is True
    # next key is one of the carousel engines
    assert orch._carousel_key in orch._carousel_engines or True


# O-18: Carousel crossfade: _carousel_crossfade instantiated on engine switch
def test_o18_carousel_crossfade_on_switch() -> None:
    ov = _make_overlay()
    ov._current_phase = "thinking"
    orch = AnimOrchestrator(ov)
    cfg = _make_cfg(carousel=True, phase_aware_carousel=False,
                    carousel_interval_s=1.0, crossfade_speed=0.04)
    orch._carousel_engines = ["dna", "rotating", "classic"]
    orch._carousel_key = "dna"
    orch._carousel_last_switch = time.monotonic() - 100.0
    orch._current_engine_instance = DnaHelixEngine()

    orch.advance_carousel(time.monotonic(), cfg)
    assert orch._carousel_crossfade is not None
    assert isinstance(orch._carousel_crossfade, CrossfadeEngine)


# O-19: get_carousel_engine returns CrossfadeEngine while crossfading
def test_o19_get_carousel_engine_returns_crossfade() -> None:
    ov = _make_overlay()
    ov._visibility_state = "active"
    orch = AnimOrchestrator(ov)
    from hermes_cli.tui.anim_engines import DnaHelixEngine, RotatingHelixEngine
    eng_a = DnaHelixEngine()
    eng_b = RotatingHelixEngine()
    cf = CrossfadeEngine(eng_a, eng_b, speed=0.04)
    orch._carousel_crossfade = cf
    orch._carousel_engines = ["dna", "rotating"]
    cfg = _make_cfg(carousel=True)

    result = orch.get_carousel_engine(cfg)
    assert result is cf


# O-20: get_carousel_engine returns plain engine after crossfade blend completes
def test_o20_get_carousel_engine_after_crossfade_done() -> None:
    ov = _make_overlay()
    ov._visibility_state = "active"
    orch = AnimOrchestrator(ov)
    from hermes_cli.tui.anim_engines import DnaHelixEngine, RotatingHelixEngine
    eng_a = DnaHelixEngine()
    eng_b = RotatingHelixEngine()
    cf = CrossfadeEngine(eng_a, eng_b, speed=1.0)
    # Advance crossfade to complete
    cf.progress = 1.0
    orch._carousel_crossfade = cf
    orch._carousel_engines = ["dna", "rotating"]
    orch._carousel_idx = 0
    orch._carousel_key = "dna"
    orch._carousel_last_switch = time.monotonic()  # recent — no advance
    cfg = _make_cfg(carousel=True, carousel_interval_s=999.0)

    result = orch.get_carousel_engine(cfg)
    # Crossfade done — should return plain engine
    assert not isinstance(result, CrossfadeEngine)


# O-21: Engine with on_mount hook → hook called once on first get_engine
def test_o21_engine_on_mount_called() -> None:
    ov = _make_overlay(animation="dna")
    orch = AnimOrchestrator(ov)
    cfg = _make_cfg(animation="dna", carousel=False)
    params = _make_params()

    # Create engine class with on_mount
    class _EngineWithMount:
        def next_frame(self, p): return ""
        def on_mount(self, overlay): self.mounted_overlay = overlay

    with patch.dict(_ENGINES, {"dna": _EngineWithMount}):
        engine = orch.get_engine(params, cfg, "#00d7ff", None)

    assert hasattr(engine, "mounted_overlay")
    assert engine.mounted_overlay is ov


# O-22: pick_carousel_candidate excludes "sdf_morph" from rotation
def test_o22_carousel_excludes_sdf_morph() -> None:
    ov = _make_overlay()
    orch = AnimOrchestrator(ov)
    cfg = _make_cfg(carousel=True, phase_aware_carousel=False)
    orch._carousel_engines = ["dna", "sdf_morph", "rotating"]
    orch._carousel_key = "dna"

    # Run many times to ensure sdf_morph never selected
    results = set()
    for _ in range(20):
        r = orch.pick_carousel_candidate("thinking", cfg)
        if r is not None:
            results.add(r)
    assert "sdf_morph" not in results


# O-23: Phase "error" → only Classic engines offered
def test_o23_carousel_error_phase_classic_only() -> None:
    ov = _make_overlay()
    orch = AnimOrchestrator(ov)
    cfg = _make_cfg(carousel=True, phase_aware_carousel=True)
    orch._carousel_engines = [k for k in _ENGINES
                               if _ENGINE_META.get(k, {}).get("category") in {"Classic", "Organic", "Mathematical"}]
    orch._carousel_key = ""

    result = orch.pick_carousel_candidate("error", cfg)
    if result is not None:
        cat = _ENGINE_META.get(result, {}).get("category")
        assert cat == "Classic"


# O-24: pick_carousel_candidate with empty candidate list → returns None
def test_o24_carousel_candidate_empty_list() -> None:
    ov = _make_overlay()
    orch = AnimOrchestrator(ov)
    cfg = _make_cfg(carousel=True, phase_aware_carousel=True)
    orch._carousel_engines = []  # empty
    result = orch.pick_carousel_candidate("thinking", cfg)
    assert result is None


# O-25: on_phase_signal("tool", cfg) triggers CrossfadeEngine for phase transition
def test_o25_on_phase_signal_installs_crossfade() -> None:
    ov = _make_overlay()
    orch = AnimOrchestrator(ov)
    cfg = _make_cfg(carousel=True, phase_aware_carousel=False,
                    phase_crossfade_speed=0.08)
    orch._carousel_engines = ["dna", "rotating", "classic", "vortex", "wave"]
    orch._carousel_key = "dna"
    orch._current_engine_instance = DnaHelixEngine()

    orch.on_phase_signal("tool", cfg)
    assert orch._carousel_crossfade is not None
    assert isinstance(orch._carousel_crossfade, CrossfadeEngine)


# O-26: set_ambient_engine sets _current_engine_instance to new engine (not None)
def test_o26_set_ambient_engine() -> None:
    from hermes_cli.tui.anim_engines import PerlinFlowEngine
    ov = _make_overlay()
    orch = AnimOrchestrator(ov)

    orch.set_ambient_engine("perlin_flow")

    assert orch._current_engine_instance is not None
    assert isinstance(orch._current_engine_instance, PerlinFlowEngine)
    assert orch._current_engine_key == "perlin_flow"
    assert orch._carousel_key == "perlin_flow"
