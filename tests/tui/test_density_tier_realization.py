"""Tests for Density Tier Realization spec (DT-1..DT-4).

Spec: /home/xush/.hermes/2026-04-25-tool-block-axis-audit/spec1-density-tier-realization.md

Test layout:
    TestHeroResolution          — 9 tests  (DT-1)
    TestTraceResolution         — 7 tests  (DT-2)
    TestRendererCompactOptOut   — 4 tests  (DT-3)
    TestToggleCycle             — 4 tests  (DT-4)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_inputs(**overrides):
    from hermes_cli.tui.tool_panel.density import DensityInputs
    from hermes_cli.tui.services.tools import ToolCallState
    defaults = dict(
        phase=ToolCallState.DONE,
        is_error=False,
        has_focus=False,
        user_scrolled_up=False,
        user_override=False,
        user_override_tier=None,
        body_line_count=5,
        threshold=20,
        row_budget=None,
        kind=None,
    )
    defaults.update(overrides)
    return DensityInputs(**defaults)


def _compute(**overrides):
    from hermes_cli.tui.tool_panel.density import DensityResolver
    return DensityResolver._compute(_make_inputs(**overrides))


# ---------------------------------------------------------------------------
# DT-1: HERO tier resolution
# ---------------------------------------------------------------------------

class TestHeroResolution:

    def test_hero_diff_under_8_lines(self):
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.tool_payload import ResultKind
        from hermes_cli.tui.services.tools import ToolCallState
        tier = _compute(body_line_count=5, kind=ResultKind.DIFF,
                        phase=ToolCallState.DONE, threshold=20)
        assert tier == DensityTier.HERO

    def test_hero_json_at_8_lines_inclusive(self):
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.tool_payload import ResultKind
        from hermes_cli.tui.services.tools import ToolCallState
        tier = _compute(body_line_count=8, kind=ResultKind.JSON,
                        phase=ToolCallState.DONE, threshold=20)
        assert tier == DensityTier.HERO

    def test_hero_completing_phase_qualifies(self):
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.tool_payload import ResultKind
        from hermes_cli.tui.services.tools import ToolCallState
        tier = _compute(body_line_count=4, kind=ResultKind.DIFF,
                        phase=ToolCallState.COMPLETING, threshold=20)
        assert tier == DensityTier.HERO

    def test_hero_text_does_not_qualify(self):
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.tool_payload import ResultKind
        from hermes_cli.tui.services.tools import ToolCallState
        tier = _compute(body_line_count=4, kind=ResultKind.TEXT,
                        phase=ToolCallState.DONE, threshold=20)
        assert tier == DensityTier.DEFAULT

    def test_hero_long_payload_under_threshold_default(self):
        """9 lines, DIFF, threshold=20 → over HERO cap but under threshold → DEFAULT."""
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.tool_payload import ResultKind
        from hermes_cli.tui.services.tools import ToolCallState
        tier = _compute(body_line_count=9, kind=ResultKind.DIFF,
                        phase=ToolCallState.DONE, threshold=20)
        assert tier == DensityTier.DEFAULT

    def test_hero_long_payload_over_threshold_compact(self):
        """9 lines, DIFF, threshold=8 → over HERO cap, over threshold → COMPACT."""
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.tool_payload import ResultKind
        from hermes_cli.tui.services.tools import ToolCallState
        tier = _compute(body_line_count=9, kind=ResultKind.DIFF,
                        phase=ToolCallState.DONE, threshold=8)
        assert tier == DensityTier.COMPACT

    def test_hero_error_blocks_hero(self):
        """is_error=True blocks HERO — modal guard wins first."""
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.tool_payload import ResultKind
        from hermes_cli.tui.services.tools import ToolCallState
        tier = _compute(body_line_count=4, kind=ResultKind.DIFF,
                        is_error=True, phase=ToolCallState.DONE, threshold=20)
        assert tier == DensityTier.DEFAULT

    def test_hero_streaming_blocks_hero(self):
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.tool_payload import ResultKind
        from hermes_cli.tui.services.tools import ToolCallState
        tier = _compute(body_line_count=4, kind=ResultKind.DIFF,
                        phase=ToolCallState.STREAMING, threshold=20)
        assert tier == DensityTier.DEFAULT

    def test_hero_scrolled_up_user_blocked(self):
        """user_scrolled_up prevents HERO auto-promotion."""
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.tool_payload import ResultKind
        from hermes_cli.tui.services.tools import ToolCallState
        tier = _compute(body_line_count=4, kind=ResultKind.DIFF,
                        phase=ToolCallState.DONE, threshold=20,
                        user_scrolled_up=True)
        assert tier == DensityTier.DEFAULT


# ---------------------------------------------------------------------------
# DT-2: TRACE tier resolution
# ---------------------------------------------------------------------------

class TestTraceResolution:

    def test_trace_via_user_override(self):
        from hermes_cli.tui.tool_panel.density import DensityTier, DensityResolver
        from hermes_cli.tui.services.tools import ToolCallState
        inp = _make_inputs(
            phase=ToolCallState.DONE,
            user_override=True,
            user_override_tier=DensityTier.TRACE,
            body_line_count=100,
            threshold=20,
        )
        resolver = DensityResolver()
        tier = resolver.resolve(inp)
        assert tier == DensityTier.TRACE

    def test_trace_header_skips_drop_order(self):
        """TRACE → trim_tail_for_tier returns all segments unchanged."""
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.tool_blocks._header import trim_tail_for_tier
        from rich.text import Text
        segs = [("flash", Text("a")), ("chip", Text("b")), ("linecount", Text("c"))]
        result = trim_tail_for_tier(segs, tail_budget=5, tier=DensityTier.TRACE)
        assert result == segs

    def test_trace_unset_returns_to_default(self):
        """Clearing the override resolves back to DEFAULT."""
        from hermes_cli.tui.tool_panel.density import DensityTier, DensityResolver
        from hermes_cli.tui.services.tools import ToolCallState
        resolver = DensityResolver()
        # First set TRACE
        inp_trace = _make_inputs(
            phase=ToolCallState.DONE,
            user_override=True,
            user_override_tier=DensityTier.TRACE,
            body_line_count=5,
            threshold=20,
        )
        resolver.resolve(inp_trace)
        assert resolver.tier == DensityTier.TRACE
        # Now clear override
        inp_default = _make_inputs(
            phase=ToolCallState.DONE,
            user_override=False,
            user_override_tier=None,
            body_line_count=5,
            threshold=20,
        )
        resolver.resolve(inp_default)
        assert resolver.tier == DensityTier.DEFAULT

    def test_density_trace_action_binding(self):
        """action_density_trace exists and sets TRACE tier on the resolver."""
        from hermes_cli.tui.tool_panel.density import DensityTier, DensityResolver
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        from hermes_cli.tui.services.tools import ToolCallState

        mixin = _ToolPanelActionsMixin.__new__(_ToolPanelActionsMixin)
        mixin._resolver = DensityResolver()
        mixin._user_collapse_override = False
        mixin._user_override_tier = None
        mixin._auto_collapsed = False
        mixin._parent_clamp_tier = None
        mixin.size = MagicMock(width=80)
        mixin._view_state = None
        mixin._result_summary_v4 = None
        mixin._body_line_count = lambda: 50

        def _lookup():
            return None
        mixin._lookup_view_state = _lookup

        flashed: list = []

        def _flash(msg, tone="success"):
            flashed.append((msg, tone))
        mixin._flash_header = _flash

        mixin.action_density_trace()
        assert mixin._resolver.tier == DensityTier.TRACE

    def test_trace_during_streaming_flashes_pending(self):
        from hermes_cli.tui.tool_panel.density import DensityTier, DensityResolver
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        from hermes_cli.tui.services.tools import ToolCallState

        mixin = _ToolPanelActionsMixin.__new__(_ToolPanelActionsMixin)
        mixin._resolver = DensityResolver()
        mixin._user_collapse_override = False
        mixin._user_override_tier = None
        mixin._auto_collapsed = False
        mixin._parent_clamp_tier = None
        mixin.size = MagicMock(width=80)
        mixin._result_summary_v4 = None
        mixin._body_line_count = lambda: 10

        vs = MagicMock()
        vs.state = ToolCallState.STREAMING
        vs.kind = None
        mixin._view_state = vs
        mixin._lookup_view_state = lambda: None

        flashed: list = []
        mixin._flash_header = lambda msg, tone="success": flashed.append((msg, tone))

        mixin.action_density_trace()
        assert mixin._resolver.tier != DensityTier.TRACE
        assert any("pending" in f[0] for f in flashed)
        # Override flags stay set (deferred to post-completion resolve)
        assert mixin._user_collapse_override is True
        assert mixin._user_override_tier == DensityTier.TRACE

    def test_trace_on_errored_block_flashes_unavailable(self):
        from hermes_cli.tui.tool_panel.density import DensityTier, DensityResolver
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        from hermes_cli.tui.services.tools import ToolCallState

        mixin = _ToolPanelActionsMixin.__new__(_ToolPanelActionsMixin)
        mixin._resolver = DensityResolver()
        mixin._user_collapse_override = False
        mixin._user_override_tier = None
        mixin._auto_collapsed = False
        mixin._parent_clamp_tier = None
        mixin.size = MagicMock(width=80)
        mixin._body_line_count = lambda: 5

        summary = MagicMock()
        summary.is_error = True
        mixin._result_summary_v4 = summary

        vs = MagicMock()
        vs.state = ToolCallState.DONE
        vs.kind = None
        mixin._view_state = vs
        mixin._lookup_view_state = lambda: None

        flashed: list = []
        mixin._flash_header = lambda msg, tone="success": flashed.append((msg, tone))

        mixin.action_density_trace()
        # Modal guard returns DEFAULT; flags cleared
        assert mixin._resolver.tier == DensityTier.DEFAULT
        assert any("errored" in f[0] for f in flashed)
        assert mixin._user_collapse_override is False
        assert mixin._user_override_tier is None

    def test_trace_footer_shows_all_artifacts(self):
        """FooterPane at TRACE density: _show_all_artifacts=True and _rebuild_chips called."""
        from hermes_cli.tui.tool_panel._footer import FooterPane
        from hermes_cli.tui.tool_panel.density import DensityTier

        pane = FooterPane.__new__(FooterPane)
        pane._density = DensityTier.DEFAULT
        pane._show_all_artifacts = False
        pane._last_summary = None

        rebuild_calls: list = []
        pane._rebuild_chips = lambda: rebuild_calls.append(1)
        pane._has_footer_content = lambda: True

        # Simulate styles.display assignment
        _display: list = []
        styles_mock = MagicMock()
        type(styles_mock).__setattr__ = MagicMock()
        pane.styles = MagicMock()

        pane._density = DensityTier.TRACE
        pane._refresh_visibility()

        assert pane._show_all_artifacts is True
        assert len(rebuild_calls) == 1


# ---------------------------------------------------------------------------
# DT-3: Renderer opt-out at COMPACT
# ---------------------------------------------------------------------------

class TestRendererCompactOptOut:

    @pytest.mark.parametrize("renderer_cls", [
        "DiffRenderer",
        "TableRenderer",
        "SearchRenderer",
    ])
    def test_diff_table_search_decline_compact(self, renderer_cls):
        """FH-6: Diff/Table/Search now accept COMPACT (summary_line provides one-line surface)."""
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        import hermes_cli.tui.body_renderers as br
        cls = getattr(br, renderer_cls)
        # FH-6 changed contract: COMPACT is now accepted by all three renderers
        assert cls.accepts(ToolCallState.DONE, DensityTier.COMPACT) is True

    @pytest.mark.parametrize("renderer_cls", [
        "DiffRenderer",
        "TableRenderer",
        "SearchRenderer",
    ])
    def test_diff_table_search_accept_default(self, renderer_cls):
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        import hermes_cli.tui.body_renderers as br
        cls = getattr(br, renderer_cls)
        assert cls.accepts(ToolCallState.DONE, DensityTier.DEFAULT) is True

    def test_pick_renderer_falls_through_for_compact_diff(self):
        """DIFF kind + COMPACT density → DiffRenderer accepts (FH-6: COMPACT supported).

        DiffRenderer.accepts() now returns True for COMPACT so it handles the
        DIFF kind at compact density with its summary_line surface.
        """
        from hermes_cli.tui.body_renderers import pick_renderer, DiffRenderer
        from hermes_cli.tui.tool_payload import ToolPayload, ClassificationResult, ResultKind
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_category import ToolCategory

        cls_result = ClassificationResult(kind=ResultKind.DIFF, confidence=0.9)
        payload = ToolPayload(
            tool_name="write_file",
            category=ToolCategory.FILE,
            args={},
            input_display=None,
            output_raw="- old\n+ new\n",
            line_count=2,
        )
        renderer = pick_renderer(
            cls_result, payload,
            phase=ToolCallState.DONE,
            density=DensityTier.COMPACT,
        )
        assert renderer is DiffRenderer

    def test_pick_renderer_diff_at_default(self):
        """DIFF kind + DEFAULT density → DiffRenderer selected."""
        from hermes_cli.tui.body_renderers import pick_renderer, DiffRenderer
        from hermes_cli.tui.tool_payload import ToolPayload, ClassificationResult, ResultKind
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_category import ToolCategory

        cls_result = ClassificationResult(kind=ResultKind.DIFF, confidence=0.9)
        payload = ToolPayload(
            tool_name="write_file",
            category=ToolCategory.FILE,
            args={},
            input_display=None,
            output_raw="- old\n+ new\n",
            line_count=2,
        )
        renderer = pick_renderer(
            cls_result, payload,
            phase=ToolCallState.DONE,
            density=DensityTier.DEFAULT,
        )
        assert renderer is DiffRenderer


# ---------------------------------------------------------------------------
# DT-4: Toggle action cycles three tiers
# ---------------------------------------------------------------------------

class TestToggleCycle:

    def test_toggle_default_to_compact(self):
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        result = _ToolPanelActionsMixin._next_tier_in_cycle(DensityTier.DEFAULT)
        assert result == DensityTier.COMPACT

    def test_toggle_compact_to_trace(self):
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        result = _ToolPanelActionsMixin._next_tier_in_cycle(DensityTier.COMPACT)
        assert result == DensityTier.TRACE

    def test_toggle_trace_to_hero(self):
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        result = _ToolPanelActionsMixin._next_tier_in_cycle(DensityTier.TRACE)
        assert result == DensityTier.HERO

    def test_toggle_hero_to_default(self):
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        result = _ToolPanelActionsMixin._next_tier_in_cycle(DensityTier.HERO)
        assert result == DensityTier.DEFAULT

    def test_toggle_hero_unavailable_flashes(self):
        """Toggle to HERO when kind=TEXT → HERO eligibility gate blocks it, flash warning."""
        from hermes_cli.tui.tool_panel.density import DensityTier, DensityResolver
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_payload import ResultKind

        mixin = _ToolPanelActionsMixin.__new__(_ToolPanelActionsMixin)
        mixin._resolver = DensityResolver()
        mixin._user_collapse_override = False
        mixin._user_override_tier = None
        mixin._auto_collapsed = False
        mixin._parent_clamp_tier = None
        mixin.size = MagicMock(width=80)
        mixin._result_summary_v4 = None
        mixin._body_line_count = lambda: 4

        vs = MagicMock()
        vs.state = ToolCallState.DONE
        vs.is_error_for_ui = False
        # TEXT kind — not in _HERO_KINDS
        cls_result = MagicMock()
        cls_result.kind = ResultKind.TEXT
        vs.kind = cls_result
        mixin._view_state = vs
        mixin._lookup_view_state = lambda: None

        flashed: list = []
        mixin._flash_header = lambda msg, tone="success": flashed.append((msg, tone))

        # Stub _block and tail to None so action skips the tail-dismiss path
        mixin._block = None

        # First toggle: DEFAULT → COMPACT (binary toggle)
        mixin.action_toggle_collapse()
        assert mixin._resolver.tier == DensityTier.COMPACT

        # Second toggle: COMPACT → DEFAULT (binary toggle back)
        flashed.clear()
        mixin.action_toggle_collapse()
        assert mixin._resolver.tier == DensityTier.DEFAULT
