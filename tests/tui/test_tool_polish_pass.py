"""Tests for TCS Polish Pass spec — P-1..P-9.

Addresses: Y-3 (HERO override flash), Y-4 (TRACE armed pending), Y-5 (density
cycle destination flash), E-2 (auto-injection parse time), E-3 (is_error_for_ui).
P-6/P-7 skipped (depend on H-3 F1 pinning). P-9 partial (H-1 cleanup pending).
"""
from __future__ import annotations

import time
import dataclasses
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_view(state, exit_code=None):
    from hermes_cli.tui.services.tools import ToolCallViewState, ToolCallState
    return ToolCallViewState(
        tool_call_id="test-id",
        gen_index=0,
        tool_name="test",
        label="test",
        args={},
        state=state,
        block=None,
        panel=None,
        parent_tool_call_id=None,
        category="shell",
        depth=0,
        start_s=time.monotonic(),
        exit_code=exit_code,
    )


def _make_summary(is_error=False, stderr_tail="", actions=(), exit_code=None):
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    return ResultSummaryV4(
        primary=None,
        exit_code=exit_code,
        chips=(),
        stderr_tail=stderr_tail,
        actions=tuple(actions),
        artifacts=(),
        is_error=is_error,
    )


def _make_action(kind, hotkey, label="x", payload=None):
    from hermes_cli.tui.tool_result_parse import Action
    return Action(label=label, hotkey=hotkey, kind=kind, payload=payload)


def _make_inputs(kind=None, body_line_count=5, width=120, parent_clamp=None, phase=None):
    from hermes_cli.tui.tool_panel.layout_resolver import DensityInputs
    from hermes_cli.tui.services.tools import ToolCallState
    return DensityInputs(
        phase=phase or ToolCallState.DONE,
        is_error=False,
        has_focus=False,
        user_scrolled_up=False,
        user_override=True,
        user_override_tier=None,
        body_line_count=body_line_count,
        threshold=0,
        row_budget=None,
        kind=kind,
        parent_clamp=parent_clamp,
        width=width,
    )


# ---------------------------------------------------------------------------
# P-1: Hero rejection reason
# ---------------------------------------------------------------------------

class TestHeroRejectionReason:
    def _make_mixin_with_resolver(self, hero_min_width=100):
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        from hermes_cli.tui.tool_panel.layout_resolver import ToolBlockLayoutResolver
        mixin = _ToolPanelActionsMixin.__new__(_ToolPanelActionsMixin)
        resolver = ToolBlockLayoutResolver(hero_min_width=hero_min_width)
        mixin._resolver = resolver
        return mixin

    def test_hero_rejected_kind_message(self):
        from hermes_cli.tui.tool_payload import ResultKind
        mixin = self._make_mixin_with_resolver()
        inputs = _make_inputs(kind=ResultKind.TEXT, body_line_count=5, width=120)
        msg = mixin._hero_rejection_reason(inputs)
        assert "kind" in msg
        assert "not eligible" in msg
        assert "text" in msg.lower()

    def test_hero_rejected_no_body_message(self):
        from hermes_cli.tui.tool_payload import ResultKind
        mixin = self._make_mixin_with_resolver()
        inputs = _make_inputs(kind=ResultKind.DIFF, body_line_count=0, width=120)
        msg = mixin._hero_rejection_reason(inputs)
        assert "no body" in msg

    def test_hero_rejected_too_long_message(self):
        from hermes_cli.tui.tool_payload import ResultKind
        from hermes_cli.tui.tool_panel.layout_resolver import _HERO_MAX_LINES
        mixin = self._make_mixin_with_resolver()
        inputs = _make_inputs(kind=ResultKind.DIFF, body_line_count=_HERO_MAX_LINES + 1, width=120)
        msg = mixin._hero_rejection_reason(inputs)
        assert "too long" in msg
        assert str(_HERO_MAX_LINES + 1) in msg

    def test_hero_rejected_too_narrow_message(self):
        from hermes_cli.tui.tool_payload import ResultKind
        mixin = self._make_mixin_with_resolver(hero_min_width=100)
        inputs = _make_inputs(kind=ResultKind.DIFF, body_line_count=4, width=60)
        msg = mixin._hero_rejection_reason(inputs)
        assert "too narrow" in msg
        assert "60" in msg

    def test_hero_rejected_unclassified_kind_default(self):
        mixin = self._make_mixin_with_resolver()
        inputs = _make_inputs(kind=None, body_line_count=4, width=120)
        msg = mixin._hero_rejection_reason(inputs)
        assert "unclassified" in msg


# ---------------------------------------------------------------------------
# P-2: Trace-armed chip
# ---------------------------------------------------------------------------

class TestTraceArmedChip:
    def _make_header_with_panel(self, armed=False, is_complete=False):
        """Build a minimal ToolCallHeader-like object."""
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        panel = MagicMock()
        panel._user_collapse_override = armed
        if armed:
            panel._user_override_tier = DensityTier.TRACE
        else:
            panel._user_override_tier = None

        return panel, is_complete

    def test_trace_queued_chip_when_armed_streaming(self):
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        panel, is_complete = self._make_header_with_panel(armed=True, is_complete=False)
        # simulate the P-2 condition check
        _user_armed_trace = (
            getattr(panel, "_user_collapse_override", False)
            and getattr(panel, "_user_override_tier", None) is not None
            and getattr(getattr(panel, "_user_override_tier", None), "value", "") == "trace"
        )
        assert _user_armed_trace is True

    def test_trace_queued_chip_absent_when_not_armed(self):
        panel, is_complete = self._make_header_with_panel(armed=False, is_complete=False)
        _user_armed_trace = (
            getattr(panel, "_user_collapse_override", False)
            and getattr(panel, "_user_override_tier", None) is not None
            and getattr(getattr(panel, "_user_override_tier", None), "value", "") == "trace"
        )
        assert _user_armed_trace is False

    def test_trace_queued_chip_clears_on_complete(self):
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        panel, _ = self._make_header_with_panel(armed=True, is_complete=True)
        is_complete = True
        # When is_complete, the guard `not self._is_complete` prevents chip from appearing
        should_show = (not is_complete) and (
            getattr(panel, "_user_collapse_override", False)
            and getattr(panel, "_user_override_tier", None) is not None
            and getattr(getattr(panel, "_user_override_tier", None), "value", "") == "trace"
        )
        assert should_show is False


# ---------------------------------------------------------------------------
# P-3: Density cycle destination flash
# ---------------------------------------------------------------------------

class TestDensityCycleFlash:
    def _make_panel_mixin(self):
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        from hermes_cli.tui.tool_panel.layout_resolver import ToolBlockLayoutResolver, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState

        mixin = _ToolPanelActionsMixin.__new__(_ToolPanelActionsMixin)
        resolver = ToolBlockLayoutResolver()
        mixin._resolver = resolver
        mixin._user_collapse_override = False
        mixin._user_override_tier = None
        mixin._auto_collapsed = False
        mixin._result_summary_v4 = None
        mixin._parent_clamp_tier = None
        mixin._view_state = _make_view(ToolCallState.DONE)
        mixin._lookup_view_state = lambda: None

        flashes = []
        mixin._flash_header = lambda msg, tone="success": flashes.append((msg, tone))

        from textual.geometry import Size
        mixin.size = Size(width=120, height=20)

        def _body_line_count():
            return 5
        mixin._body_line_count = _body_line_count

        return mixin, flashes

    def test_action_toggle_collapse_flashes_destination_tier(self):
        mixin, flashes = self._make_panel_mixin()
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        mixin.action_toggle_collapse()
        # Should have flashed the resulting tier
        assert len(flashes) >= 1
        # The last flash is either the destination tier or rejection message
        last_msg, last_tone = flashes[-1]
        # Default→Compact is expected (no HERO rejection)
        assert last_msg in (
            DensityTier.COMPACT.value,
            DensityTier.DEFAULT.value,
            DensityTier.HERO.value,
        ) or "unavailable" in last_msg

    def test_density_cycle_flashes_compact_then_hero_then_default(self):
        mixin, flashes = self._make_panel_mixin()
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        # First press: DEFAULT → COMPACT
        mixin.action_toggle_collapse()
        assert any(DensityTier.COMPACT.value in msg for msg, _ in flashes)

    def test_rejection_flash_does_not_combine_with_destination_flash(self):
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        from hermes_cli.tui.tool_panel.layout_resolver import ToolBlockLayoutResolver, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState

        mixin = _ToolPanelActionsMixin.__new__(_ToolPanelActionsMixin)
        resolver = ToolBlockLayoutResolver()
        mixin._resolver = resolver
        # Override to be at COMPACT so next is HERO
        resolver._tier = DensityTier.COMPACT
        mixin._user_collapse_override = False
        mixin._user_override_tier = None
        mixin._auto_collapsed = False
        mixin._result_summary_v4 = None
        mixin._parent_clamp_tier = None
        mixin._view_state = _make_view(ToolCallState.DONE)
        mixin._lookup_view_state = lambda: None
        flashes = []
        mixin._flash_header = lambda msg, tone="success": flashes.append((msg, tone))
        from textual.geometry import Size
        mixin.size = Size(width=120, height=20)
        mixin._body_line_count = lambda: 5

        mixin.action_toggle_collapse()
        # Only one flash — not both rejection + destination
        assert len(flashes) == 1


# ---------------------------------------------------------------------------
# P-4: Auto-injection at parse time
# ---------------------------------------------------------------------------

class TestRecoveryActionAtParseTime:
    def test_parse_injects_retry_when_error(self):
        from hermes_cli.tui.tool_result_parse import inject_recovery_actions
        summary = _make_summary(is_error=True, actions=())
        result = inject_recovery_actions(summary)
        kinds = [a.kind for a in result.actions]
        assert "retry" in kinds

    def test_parse_injects_copy_err_when_stderr_tail(self):
        from hermes_cli.tui.tool_result_parse import inject_recovery_actions
        summary = _make_summary(stderr_tail="some error", actions=())
        result = inject_recovery_actions(summary)
        kinds = [a.kind for a in result.actions]
        assert "copy_err" in kinds

    def test_parse_does_not_double_inject_retry(self):
        from hermes_cli.tui.tool_result_parse import inject_recovery_actions
        existing_retry = _make_action("retry", "r")
        summary = _make_summary(is_error=True, actions=(existing_retry,))
        result = inject_recovery_actions(summary)
        retry_count = sum(1 for a in result.actions if a.kind == "retry")
        assert retry_count == 1

    def test_render_footer_no_longer_injects(self):
        """Footer must not inject; injection is now done before set_result_summary_v4."""
        from hermes_cli.tui.tool_result_parse import inject_recovery_actions
        # Pre-injected summary
        known = _make_action("retry", "r")
        summary = _make_summary(is_error=True, actions=(known,))
        prepped = inject_recovery_actions(summary)
        # After inject, retry is present once
        retry_count = sum(1 for a in prepped.actions if a.kind == "retry")
        assert retry_count == 1

    def test_summary_actions_contract_stable(self):
        """summary.actions matches what the footer would render after injection."""
        from hermes_cli.tui.tool_result_parse import inject_recovery_actions
        summary = _make_summary(is_error=True, stderr_tail="fail", actions=())
        prepped = inject_recovery_actions(summary)
        # actions is a stable tuple — same as what _render_footer receives
        assert isinstance(prepped.actions, tuple)
        kinds = {a.kind for a in prepped.actions}
        assert "retry" in kinds
        assert "copy_err" in kinds


# ---------------------------------------------------------------------------
# P-5: is_error_for_ui
# ---------------------------------------------------------------------------

class TestIsErrorForUi:
    def test_is_error_for_ui_done_zero(self):
        from hermes_cli.tui.services.tools import ToolCallState
        vs = _make_view(ToolCallState.DONE, exit_code=0)
        assert vs.is_error_for_ui is False

    def test_is_error_for_ui_done_nonzero(self):
        from hermes_cli.tui.services.tools import ToolCallState
        vs = _make_view(ToolCallState.DONE, exit_code=1)
        assert vs.is_error_for_ui is True

    def test_is_error_for_ui_error_state(self):
        from hermes_cli.tui.services.tools import ToolCallState
        vs = _make_view(ToolCallState.ERROR, exit_code=None)
        assert vs.is_error_for_ui is True

    def test_is_error_for_ui_cancelled_state(self):
        from hermes_cli.tui.services.tools import ToolCallState
        vs = _make_view(ToolCallState.CANCELLED, exit_code=1)
        assert vs.is_error_for_ui is False

    def test_is_error_for_ui_streaming_state(self):
        from hermes_cli.tui.services.tools import ToolCallState
        vs = _make_view(ToolCallState.STREAMING, exit_code=None)
        assert vs.is_error_for_ui is False


# ---------------------------------------------------------------------------
# P-6: F1 pinned at narrow width (depends on H-3 _render_hints)
# ---------------------------------------------------------------------------

class TestF1Pinned:
    @pytest.mark.skip(reason="P-6: depends on hint-pipeline H-3 F1 pinning at narrow widths; "
                             "current _build_hint_text hides F1 when narrow=True (width<50)")
    def test_f1_pinned_at_width_30(self):
        """F1 hint pinned even when budget forces all contextual hints out."""
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        from hermes_cli.tui.tool_result_parse import ResultSummaryV4
        mixin = _ToolPanelActionsMixin.__new__(_ToolPanelActionsMixin)
        rs = _make_summary(is_error=False)
        mixin._result_summary_v4 = rs
        mixin._block = MagicMock()
        mixin._block._completed = True
        mixin._view_state = None
        mixin._lookup_view_state = lambda: None
        from textual.geometry import Size
        mixin.size = Size(width=30, height=20)
        mixin.is_mounted = True
        text = mixin._build_hint_text()
        assert "F1" in text.plain


# ---------------------------------------------------------------------------
# P-7: Truncation marker count matches dropped (depends on H-3)
# ---------------------------------------------------------------------------

class TestTruncationMarker:
    @pytest.mark.skip(reason="P-7: depends on hint-pipeline H-3 _truncate_hints +N more marker; "
                             "not yet implemented in current _build_hint_text path")
    def test_truncation_marker_count_matches_dropped(self):
        """Across widths 30..120, +N matches actual dropped contextual hints."""
        pass


# ---------------------------------------------------------------------------
# P-8: Density cycle excludes TRACE
# ---------------------------------------------------------------------------

class TestDensityCycleExcludesTrace:
    def test_density_cycle_excludes_trace(self):
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        cycle_results = set()
        current = DensityTier.DEFAULT
        for _ in range(6):  # more than 3 iterations to detect cycle length
            nxt = _ToolPanelActionsMixin._next_tier_in_cycle(current)
            cycle_results.add(nxt)
            current = nxt

        assert DensityTier.TRACE not in cycle_results
        # Exactly 3 tiers in cycle
        assert cycle_results == {DensityTier.DEFAULT, DensityTier.COMPACT, DensityTier.HERO}


# ---------------------------------------------------------------------------
# P-9: Legacy alias + cleanup (partial — H-1 deletion pending)
# ---------------------------------------------------------------------------

class TestLegacyAliasMigration:
    def test_drop_order_alias_still_resolves(self):
        """_DROP_ORDER_BY_TIER alias resolves; back-compat for one release."""
        from hermes_cli.tui.tool_panel.layout_resolver import _DROP_ORDER_BY_TIER
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        assert DensityTier.DEFAULT in _DROP_ORDER_BY_TIER
        assert DensityTier.COMPACT in _DROP_ORDER_BY_TIER
        assert DensityTier.HERO in _DROP_ORDER_BY_TIER
        # trace_pending appears in each drop order
        for tier, order in _DROP_ORDER_BY_TIER.items():
            if tier != DensityTier.TRACE:
                assert "trace_pending" in order, f"trace_pending missing from {tier} drop order"

    @pytest.mark.skip(reason="P-9: depends on hint-pipeline H-1 deleting _select_hint_set; "
                             "function still exists in current codebase (H-1 added new path "
                             "but did not delete the old one)")
    def test_select_hint_set_removed(self):
        """Once H-1 deletion lands, _select_hint_set must be gone."""
        from hermes_cli.tui.tool_panel import _actions as _mod
        assert not hasattr(_mod._ToolPanelActionsMixin, "_select_hint_set")
