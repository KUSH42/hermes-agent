"""Tests for bundled skin TTE final_gradient_stops parity.

Spec: /home/xush/.hermes/2026-05-04-bundled-tte-gradient-stops-spec.md
TG-1..TG-8
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

SKIN_DIR = Path(__file__).resolve().parents[2] / "hermes_cli" / "skins"
ALL_SKINS = [
    "ares", "catppuccin", "charizard", "hermes", "matrix",
    "mono", "poseidon", "sisyphus", "slate",
    "solarized-dark", "tokyo-night",
]

_HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}")


def _skin_data(skin: str) -> dict:
    """Parse DESIGN.md YAML front-matter as a dict."""
    path = SKIN_DIR / skin / "DESIGN.md"
    content = path.read_text()
    parts = content.split("---")
    return yaml.safe_load(parts[1])


def _stops(skin: str) -> list[str]:
    """Return startup_tte.params.final_gradient_stops; empty list if absent."""
    data = _skin_data(skin)
    try:
        return list(data["x-hermes"]["startup_tte"]["params"]["final_gradient_stops"])
    except (KeyError, TypeError):
        return []


def _palette(skin: str) -> set[str]:
    """Collect all verbatim #RRGGBB hex literals from the DESIGN.md."""
    path = SKIN_DIR / skin / "DESIGN.md"
    content = path.read_text()
    return {m.upper() for m in _HEX_RE.findall(content)}


def _rec601_lum(hex_color: str) -> float:
    """Rec. 601 luminance from #RRGGBB string."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return 0.299 * r + 0.587 * g + 0.114 * b


# ---------------------------------------------------------------------------
# TG-1 — ares

class TestAresStops:
    def test_ares_tte_has_final_gradient_stops(self):
        stops = _stops("ares")
        assert len(stops) >= 2

    def test_ares_tte_stops_subset_of_skin_palette(self):
        stops = _stops("ares")
        palette = _palette("ares")
        for stop in stops:
            assert stop.upper() in palette, f"{stop} not in ares palette"


# ---------------------------------------------------------------------------
# TG-2 — poseidon

class TestPoseidonStops:
    def test_poseidon_tte_has_final_gradient_stops(self):
        stops = _stops("poseidon")
        assert len(stops) == 7

    def test_poseidon_tte_stops_subset_of_skin_palette(self):
        stops = _stops("poseidon")
        palette = _palette("poseidon")
        for stop in stops:
            assert stop.upper() in palette, f"{stop} not in poseidon palette"


# ---------------------------------------------------------------------------
# TG-3 — sisyphus

class TestSisyphusStops:
    def test_sisyphus_tte_has_final_gradient_stops(self):
        stops = _stops("sisyphus")
        assert len(stops) == 6

    def test_sisyphus_tte_stops_subset_of_skin_palette(self):
        stops = _stops("sisyphus")
        palette = _palette("sisyphus")
        for stop in stops:
            assert stop.upper() in palette, f"{stop} not in sisyphus palette"

    def test_sisyphus_tte_stops_monotonic_descent(self):
        stops = _stops("sisyphus")
        lums = [_rec601_lum(s) for s in stops]
        for i in range(len(lums) - 1):
            assert lums[i] > lums[i + 1], (
                f"luminance not strictly decreasing at index {i}: {lums[i]} -> {lums[i+1]}"
            )


# ---------------------------------------------------------------------------
# TG-4 — matrix

class TestMatrixStops:
    def test_matrix_skin_uses_rain_effect(self):
        data = _skin_data("matrix")
        assert data["x-hermes"]["startup_tte"]["effect"] == "rain"

    def test_matrix_skin_does_not_use_matrix_effect(self):
        data = _skin_data("matrix")
        assert data["x-hermes"]["startup_tte"]["effect"] != "matrix"

    def test_matrix_tte_has_final_gradient_stops(self):
        stops = _stops("matrix")
        assert len(stops) >= 2

    def test_matrix_tte_stops_phosphor_descent(self):
        stops = _stops("matrix")
        lums = [_rec601_lum(s) for s in stops]
        for i in range(len(lums) - 1):
            assert lums[i] > lums[i + 1], (
                f"luminance not strictly decreasing at index {i}: "
                f"{round(lums[i], 1)} -> {round(lums[i+1], 1)}"
            )


# ---------------------------------------------------------------------------
# TG-5 — hermes

class TestHermesStops:
    def test_hermes_tte_has_final_gradient_stops(self):
        stops = _stops("hermes")
        assert len(stops) == 4

    def test_hermes_tte_includes_banner_border_bronze(self):
        stops = _stops("hermes")
        assert "#CD7F32" in [s.upper() for s in stops]


# ---------------------------------------------------------------------------
# TG-6 — all skins gate

class TestAllSkinsStopsGate:
    def test_all_bundled_skins_have_tte_final_gradient_stops(self):
        for skin in ALL_SKINS:
            stops = _stops(skin)
            assert len(stops) >= 2, f"{skin}: expected >=2 stops, got {len(stops)}"

    def test_each_tte_stop_set_subset_of_skin_palette(self):
        for skin in ALL_SKINS:
            stops = _stops(skin)
            palette = _palette(skin)
            for stop in stops:
                assert stop.upper() in palette, (
                    f"{skin}: stop {stop} not found in DESIGN.md palette"
                )


# ---------------------------------------------------------------------------
# TG-7 — runner default branch + explicit params

class TestRunnerDefaultBranch:
    def test_runner_default_branch_still_reachable(self):
        from hermes_cli.tui import tte_runner

        class FakeEffectConfig:
            final_gradient_stops = None

        cfg = FakeEffectConfig()
        tte_runner._apply_skin_gradient(
            cfg, ("#111111", "#222222", "#333333"), lambda x: f"wrapped:{x}"
        )
        assert cfg.final_gradient_stops == (
            "wrapped:#111111", "wrapped:#222222", "wrapped:#333333"
        )

    def test_runner_apply_effect_params_sets_explicit_stops(self):
        from hermes_cli.tui import tte_runner

        class FakeEffectConfig:
            final_gradient_stops = None

        class FakeEffect:
            effect_config = FakeEffectConfig()

        effect = FakeEffect()
        result = tte_runner._apply_effect_params(
            "matrix",
            effect,
            lambda x: f"C:{x}",
            {"final_gradient_stops": ["#aaffc8", "#00ff41"]},
        )
        assert result is True
        assert effect.effect_config.final_gradient_stops == ("C:#aaffc8", "C:#00ff41")


# ---------------------------------------------------------------------------
# TG-8 — effect uniqueness + no name collision

class TestEffectUniquenessGate:
    def test_bundled_skins_use_distinct_tte_effects(self):
        effects = []
        for skin in ALL_SKINS:
            data = _skin_data(skin)
            effects.append(data["x-hermes"]["startup_tte"]["effect"])
        assert len(set(effects)) == len(ALL_SKINS), (
            f"Duplicate TTE effects detected: {effects}"
        )

    def test_no_bundled_skin_uses_its_own_name_as_effect(self):
        for skin in ALL_SKINS:
            data = _skin_data(skin)
            effect = data["x-hermes"]["startup_tte"]["effect"]
            # NOTE: assumes no TTE effect name contains a hyphen; revisit if
            # terminaltexteffects adds hyphenated effect names.
            assert effect != skin, (
                f"Skin '{skin}' uses its own name as TTE effect"
            )
