"""Tests for TB-H3 (viewport pressure axis) + TB-H4 (THRESHOLDS landing site).

Spec: /home/xush/.hermes/spec-tb-h3-h4-pressure-thresholds.md

Test layout:
    TestThresholds      — 4 tests for TB-H4 (constant relocation)
    TestPressureBands   — 10 tests for TB-H3 (resolver behaviour)
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_inputs(**overrides):
    """Return a LayoutInputs with safe defaults, overridable by keyword."""
    from hermes_cli.tui.tool_panel.layout_resolver import LayoutInputs
    from hermes_cli.tui.services.tools import ToolCallState
    from hermes_cli.tui.tool_payload import ResultKind

    defaults = dict(
        phase=ToolCallState.DONE,
        is_error=False,
        has_focus=False,
        user_scrolled_up=False,
        user_override=False,
        user_override_tier=None,
        body_line_count=4,
        threshold=20,
        kind=ResultKind.DIFF,  # in _HERO_KINDS
        pressure=0.0,
        viewport_rows=999,
        is_offscreen=False,
    )
    defaults.update(overrides)
    return LayoutInputs(**defaults)


def _resolve(inp):
    from hermes_cli.tui.tool_panel.layout_resolver import ToolBlockLayoutResolver
    resolver = ToolBlockLayoutResolver(hero_min_width=0)  # disable width gate
    return resolver._compute_tier(inp)[0]


# ---------------------------------------------------------------------------
# TestThresholds — TB-H4
# ---------------------------------------------------------------------------

class TestThresholds:
    def test_thresholds_dict_exists_and_is_public(self):
        from hermes_cli.tui.tool_panel.layout_resolver import THRESHOLDS
        assert isinstance(THRESHOLDS, dict)

    def test_thresholds_has_all_concept_named_keys(self):
        from hermes_cli.tui.tool_panel.layout_resolver import THRESHOLDS
        expected_keys = {
            "HERO_MIN_BODY_ROWS",
            "HERO_MAX_LINES",
            "HERO_MIN_WIDTH",
            "MIN_HERO_VIEWPORT_ROWS",
            "DEFAULT_BODY_CLAMP",
            "COMPACT_SIBLING_CAP",
            "GROUP_CAP_DEFAULT",
            "GROUP_CAP_COMPACT",
            "GROUP_CAP_TRACE",
            "LONG_CALL_THRESHOLD_S",
            "LARGE_PAYLOAD_ROWS",
            "MIN_BLOCK_COLS",
            "MIN_VIEWPORT_COLS",
        }
        assert set(THRESHOLDS.keys()) >= expected_keys

    def test_no_module_level_duplicates(self):
        import hermes_cli.tui.tool_panel.layout_resolver as mod
        assert not hasattr(mod, "_DEFAULT_BODY_CLAMP")
        assert not hasattr(mod, "_HERO_MAX_LINES")
        assert not hasattr(mod, "DEFAULT_HERO_MIN_WIDTH")

    def test_hero_min_body_rows_not_in_actions_module(self):
        import hermes_cli.tui.tool_panel._actions as actions_mod
        assert not hasattr(actions_mod, "_HERO_MIN_BODY_ROWS")


# ---------------------------------------------------------------------------
# TestPressureBands — TB-H3
# ---------------------------------------------------------------------------

class TestPressureBands:
    def test_pressure_below_060_allows_hero(self):
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        inp = _make_inputs(pressure=0.4)
        assert _resolve(inp) == DensityTier.HERO

    def test_pressure_060_blocks_unfocused_hero(self):
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        inp = _make_inputs(pressure=0.7, has_focus=False)
        assert _resolve(inp) == DensityTier.DEFAULT

    def test_pressure_060_focused_keeps_hero(self):
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        inp = _make_inputs(pressure=0.7, has_focus=True)
        assert _resolve(inp) == DensityTier.HERO

    def test_pressure_085_disables_hero_even_focused(self):
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        inp = _make_inputs(pressure=0.9, has_focus=True)
        assert _resolve(inp) == DensityTier.DEFAULT

    def test_pressure_085_forces_unfocused_to_compact(self):
        # body_line_count=3, threshold=20 → would normally be DEFAULT
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        from hermes_cli.tui.tool_payload import ResultKind
        inp = _make_inputs(
            pressure=0.9,
            has_focus=False,
            body_line_count=3,
            kind=ResultKind.TEXT,  # not in _HERO_KINDS → no HERO attempt
        )
        assert _resolve(inp) == DensityTier.COMPACT

    def test_pressure_oversubscribe_cascades_offscreen_to_trace(self):
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        inp = _make_inputs(pressure=1.2, has_focus=False, is_offscreen=True)
        assert _resolve(inp) == DensityTier.TRACE

    def test_pressure_oversubscribe_onscreen_stays_compact(self):
        # pressure > 1.0 but not offscreen → cascade doesn't fire; force_compact applies
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        from hermes_cli.tui.tool_payload import ResultKind
        inp = _make_inputs(
            pressure=1.2,
            has_focus=False,
            is_offscreen=False,
            kind=ResultKind.TEXT,
        )
        assert _resolve(inp) == DensityTier.COMPACT

    def test_err_bypasses_pressure_cascade(self):
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        inp = _make_inputs(
            pressure=1.2,
            has_focus=False,
            is_offscreen=True,
            is_error=True,
        )
        assert _resolve(inp) == DensityTier.DEFAULT

    def test_viewport_too_short_blocks_hero(self):
        # pressure=0.4 (no force_compact), viewport_rows=10 < MIN_HERO_VIEWPORT_ROWS(16)
        # → HERO blocked by viewport gate; result is DEFAULT (pressure < 0.85 so no COMPACT)
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        inp = _make_inputs(pressure=0.4, viewport_rows=10, has_focus=False)
        assert _resolve(inp) == DensityTier.DEFAULT

    def test_user_override_hero_loses_to_hard_pressure(self):
        # user_override=HERO + pressure=0.9 + not has_focus → denied in override branch,
        # then pressure_forces_compact bumps DEFAULT → COMPACT
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        inp = _make_inputs(
            user_override=True,
            user_override_tier=DensityTier.HERO,
            pressure=0.9,
            has_focus=False,
        )
        assert _resolve(inp) == DensityTier.COMPACT
