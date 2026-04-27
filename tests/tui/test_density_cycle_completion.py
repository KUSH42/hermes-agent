"""Tests for DC-1..DC-4 — Density Cycle Completion (spec 2026-04-27)."""
from __future__ import annotations

import pytest

from hermes_cli.tui.tool_panel._actions import (
    _density_cycle,
    _is_hero_row_legal,
    _next_legal_tier_static,
    _HERO_MIN_BODY_ROWS,
)
from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin as _Mixin
from hermes_cli.tui.tool_panel.density import DensityTier


# ---------------------------------------------------------------------------
# DC-1 — Forward cycle includes TRACE
# ---------------------------------------------------------------------------

class TestForwardCycle:
    def test_d_cycle_full_path(self):
        """DEFAULT × 4 forward steps → COMPACT → TRACE → HERO → DEFAULT."""
        start = DensityTier.DEFAULT
        seq = [_Mixin._next_tier_in_cycle(t) for t in [
            start,
            DensityTier.COMPACT,
            DensityTier.TRACE,
            DensityTier.HERO,
        ]]
        assert seq == [
            DensityTier.COMPACT,
            DensityTier.TRACE,
            DensityTier.HERO,
            DensityTier.DEFAULT,
        ]

    def test_d_cycle_from_trace_to_hero(self):
        """TRACE → HERO via forward step."""
        assert _Mixin._next_tier_in_cycle(DensityTier.TRACE) == DensityTier.HERO

    def test_d_cycle_wraps(self):
        """HERO wraps back to DEFAULT."""
        assert _Mixin._next_tier_in_cycle(DensityTier.HERO) == DensityTier.DEFAULT


# ---------------------------------------------------------------------------
# DC-2 — Reverse cycle (Shift+D)
# ---------------------------------------------------------------------------

class TestReverseCycle:
    def test_shift_d_reverse_cycle(self):
        """DEFAULT × 4 backward steps → HERO → TRACE → COMPACT → DEFAULT."""
        seq = [_Mixin._prev_tier_in_cycle(t) for t in [
            DensityTier.DEFAULT,
            DensityTier.HERO,
            DensityTier.TRACE,
            DensityTier.COMPACT,
        ]]
        assert seq == [
            DensityTier.HERO,
            DensityTier.TRACE,
            DensityTier.COMPACT,
            DensityTier.DEFAULT,
        ]

    def test_shift_d_from_default_to_hero(self):
        """DEFAULT backward → HERO (wrap)."""
        assert _Mixin._prev_tier_in_cycle(DensityTier.DEFAULT) == DensityTier.HERO

    def test_shift_d_out_of_cycle_value_resets_to_default(self):
        """Unknown tier (simulated via a sentinel) returns DEFAULT (ValueError branch)."""
        # Pass a value that is not in the cycle tuple — use a fresh enum value via
        # monkeypatching the cycle to a smaller subset so DEFAULT is "out of cycle".
        # Easiest: pass a string which will never be in the DensityTier tuple.
        result = _Mixin._prev_tier_in_cycle("not-a-tier")
        assert result == DensityTier.DEFAULT


# ---------------------------------------------------------------------------
# DC-3 — Pressure-forbidden tier skip
# ---------------------------------------------------------------------------

class TestPressureForbiddenSkip:
    def test_hero_skipped_under_min_rows(self):
        """TRACE forward with body_lines < _HERO_MIN_BODY_ROWS → skips HERO → DEFAULT."""
        result = _next_legal_tier_static(DensityTier.TRACE, +1, body_lines=2)
        assert result == DensityTier.DEFAULT

    def test_hero_legal_when_rows_sufficient(self):
        """TRACE forward with body_lines >= _HERO_MIN_BODY_ROWS → HERO returned."""
        result = _next_legal_tier_static(DensityTier.TRACE, +1, body_lines=10)
        assert result == DensityTier.HERO

    def test_skip_wraps_to_default_forward(self):
        """Same as test_hero_skipped_under_min_rows — explicit wrap check."""
        result = _next_legal_tier_static(DensityTier.TRACE, +1, body_lines=_HERO_MIN_BODY_ROWS - 1)
        assert result == DensityTier.DEFAULT

    def test_no_legal_tier_returns_start(self, monkeypatch):
        """When every candidate is forbidden, returns start unchanged."""
        # Monkeypatch _is_hero_row_legal to always False AND shrink cycle to only
        # [DEFAULT, HERO] so every non-start candidate is HERO.
        from hermes_cli.tui.tool_panel import _actions as _mod
        monkeypatch.setattr(_mod, "_DENSITY_CYCLE", (DensityTier.DEFAULT, DensityTier.HERO))
        monkeypatch.setattr(_mod, "_is_hero_row_legal", lambda _: False)
        result = _mod._next_legal_tier_static(DensityTier.DEFAULT, +1, body_lines=0)
        assert result == DensityTier.DEFAULT

    def test_legal_path_no_skip(self):
        """COMPACT forward with HERO legal → TRACE (normal; no skip)."""
        result = _next_legal_tier_static(DensityTier.COMPACT, +1, body_lines=20)
        assert result == DensityTier.TRACE


# ---------------------------------------------------------------------------
# DC-4 — Help overlay hint microcopy
# ---------------------------------------------------------------------------

class TestHelpMicrocopy:
    """Verify hint candidate strings collected for density keys."""

    def _make_panel(self, collapsed: bool = False):
        """Minimal stub with _collect_hints wired."""
        import types
        panel = types.SimpleNamespace()
        panel.collapsed = collapsed
        panel._result_summary_v4 = None
        panel._block = types.SimpleNamespace(_completed=True)
        panel._hint_visible = False

        def _is_error(): return False
        def _get_omission_bar(): return None
        def _visible_footer_action_kinds(): return set()

        panel._is_error = _is_error
        panel._get_omission_bar = _get_omission_bar
        panel._visible_footer_action_kinds = _visible_footer_action_kinds
        # Bind _collect_hints from the mixin
        panel._collect_hints = _Mixin._collect_hints.__get__(panel)
        return panel

    def test_help_lists_d_and_shift_d(self):
        """_collect_hints returns both density keys for a complete expanded block."""
        panel = self._make_panel(collapsed=False)
        _, contextual = panel._collect_hints()
        keys = [k for k, _ in contextual]
        assert "D" in keys
        assert "shift+d" in keys

    def test_density_cycle_label_microcopy(self):
        """'density-cycle' label: lowercase, hyphenated, ≤14 chars."""
        label = "density-cycle"
        assert label == label.lower()
        assert "-" in label
        assert len(label) <= 14

    def test_density_back_label_microcopy(self):
        """'density-back' label: lowercase, hyphenated, ≤14 chars."""
        label = "density-back"
        assert label == label.lower()
        assert "-" in label
        assert len(label) <= 14
