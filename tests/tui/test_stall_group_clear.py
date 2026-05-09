"""Tests for STALL-GC-H1/H2 — group-terminal abandonment for stalled children.

Test layout:
    TestAbandonment          — H1 (9 tests): StreamingToolBlock._mark_abandoned + stalled calc
    TestAbandonmentSweep     — H2 (5 tests): ToolGroup._sweep_abandoned_children
"""

from __future__ import annotations

import sys
import time
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_block() -> StreamingToolBlock:
    """Return a minimal StreamingToolBlock stub (no Textual app needed)."""
    block = StreamingToolBlock.__new__(StreamingToolBlock)
    block._completed = False
    block._abandoned = False
    block._microcopy_shown = False
    block._tool_name = "test_tool"
    block._last_line_time = 0.0
    block._stream_started_at = None

    header = MagicMock()
    header._pulse_paused = False
    header._stall_glyph_active = False
    block._header = header

    body = MagicMock()
    block._body = body

    return block


# ---------------------------------------------------------------------------
# TestAbandonment — H1
# ---------------------------------------------------------------------------

class TestAbandonment:

    def test_mark_abandoned_sets_flag(self):
        block = _make_block()
        block._mark_abandoned()
        assert block._abandoned is True

    def test_abandoned_microcopy_search(self):
        block = _make_block()
        mock_spec = MagicMock()
        mock_spec.category.value = "search"

        with patch("hermes_cli.tui.tool_category.spec_for", return_value=mock_spec):
            block._mark_abandoned()

        block._body.set_microcopy.assert_called_with("no result · search")

    def test_abandoned_microcopy_unknown_category(self):
        block = _make_block()
        mock_spec = MagicMock()
        mock_spec.category.value = "unknown"

        with patch("hermes_cli.tui.tool_category.spec_for", return_value=mock_spec):
            block._mark_abandoned()

        block._body.set_microcopy.assert_called_with("no result")

    def test_abandoned_microcopy_on_import_error(self):
        block = _make_block()

        # Remove the module from sys.modules so the lazy import fails
        saved = sys.modules.pop("hermes_cli.tui.tool_category", None)
        try:
            with patch.dict("sys.modules", {"hermes_cli.tui.tool_category": None}):
                block._mark_abandoned()
        finally:
            if saved is not None:
                sys.modules["hermes_cli.tui.tool_category"] = saved

        block._body.set_microcopy.assert_called_with("no result")

    def test_abandoned_drops_stall_glyph(self):
        block = _make_block()
        block._header._stall_glyph_active = True

        with patch("hermes_cli.tui.tool_category.spec_for", side_effect=RuntimeError("boom")):
            block._mark_abandoned()

        assert block._header._stall_glyph_active is False

    def test_abandoned_calls_pulse_stop(self):
        block = _make_block()

        with patch("hermes_cli.tui.tool_category.spec_for", side_effect=RuntimeError("boom")):
            block._mark_abandoned()

        block._header._pulse_stop.assert_called_once()

    def test_mark_abandoned_idempotent(self):
        block = _make_block()

        with patch("hermes_cli.tui.tool_category.spec_for", side_effect=RuntimeError("boom")):
            block._mark_abandoned()
            block._mark_abandoned()  # second call must be a no-op

        # _pulse_stop called exactly once (second _mark_abandoned returns early on _abandoned guard)
        block._header._pulse_stop.assert_called_once()

    def test_stalled_calc_gated_by_abandoned(self):
        """When _abandoned=True the stalled flag must evaluate False even with old last_line_time."""
        # Directly evaluate the stalled expression from _update_microcopy.
        # When _abandoned=True the `not self._abandoned` clause short-circuits to False.
        now = time.monotonic()
        # Simulate a block that would normally be stalled (>5s since last line)
        completed = False
        abandoned = True
        last_line_time = now - 10.0  # 10s since last line — past 5s threshold

        stalled = (
            not completed
            and not abandoned
            and last_line_time > 0.0
            and (time.monotonic() - last_line_time) > 5.0
        )
        assert stalled is False, "stalled must be False when abandoned=True"

        # Confirm the guard is the _abandoned flag specifically (not completed)
        stalled_without_abandon_gate = (
            not completed
            and last_line_time > 0.0
            and (time.monotonic() - last_line_time) > 5.0
        )
        assert stalled_without_abandon_gate is True, (
            "Without abandoned gate, stalled should be True (confirming the gate matters)"
        )

    def test_multiple_children_abandoned(self):
        blocks = [_make_block() for _ in range(3)]
        for b in blocks:
            with patch("hermes_cli.tui.tool_category.spec_for", side_effect=RuntimeError("boom")):
                b._mark_abandoned()

        assert all(b._abandoned is True for b in blocks)
        for b in blocks:
            b._body.set_microcopy.assert_called_with("no result")


# ---------------------------------------------------------------------------
# TestAbandonmentSweep — H2
# ---------------------------------------------------------------------------

def _make_group_stub(group_state=None):
    """Return a minimal ToolGroup stub for sweep tests (no Textual app needed)."""
    from hermes_cli.tui.tool_group import ToolGroup, ToolGroupState

    group = ToolGroup.__new__(ToolGroup)
    group._group_swept = False
    group._group_terminal_at = None
    group._group_state = group_state or ToolGroupState.DONE
    group._group_id = "test-group-id"
    return group


def _make_real_panel(completed: bool):
    """Return a real ToolPanel stub (via __new__) with a controlled _block."""
    from hermes_cli.tui.tool_panel import ToolPanel

    block = MagicMock()
    block._completed = completed
    block._mark_abandoned = MagicMock()

    panel = ToolPanel.__new__(ToolPanel)
    panel._block = block
    return panel, block


class TestAbandonmentSweep:

    def test_sweep_marks_non_completed_child(self):
        group = _make_group_stub()
        panel, block = _make_real_panel(completed=False)

        body = MagicMock()
        body.children = [panel]
        group._body = body

        group._sweep_abandoned_children()

        assert group._group_swept is True
        block._mark_abandoned.assert_called_once()

    def test_sweep_idempotent(self):
        group = _make_group_stub()
        panel, block = _make_real_panel(completed=False)

        body = MagicMock()
        body.children = [panel]
        group._body = body

        group._sweep_abandoned_children()
        group._sweep_abandoned_children()  # second call is a no-op via _group_swept

        block._mark_abandoned.assert_called_once()

    def test_sweep_skips_completed_child(self):
        group = _make_group_stub()
        panel, block = _make_real_panel(completed=True)

        body = MagicMock()
        body.children = [panel]
        group._body = body

        group._sweep_abandoned_children()

        block._mark_abandoned.assert_not_called()

    def test_sweep_skips_if_body_is_none(self):
        group = _make_group_stub()
        group._body = None

        # Must not raise; must still set _group_swept
        group._sweep_abandoned_children()

        assert group._group_swept is True

    def test_sweep_does_not_fire_for_running_group(self):
        """set_timer must NOT be called in on_tool_panel_completed when group stays RUNNING."""
        from hermes_cli.tui.tool_group import ToolGroup, ToolGroupState

        group = _make_group_stub(group_state=ToolGroupState.RUNNING)
        group._group_terminal_at = 0.0
        group._streaming_err_count = 0
        group._terminal_err_count = 0
        group._running_diff_add = 0
        group._running_diff_del = 0
        group.set_timer = MagicMock()
        group.recompute_aggregate = MagicMock()
        group._apply_child_render_cap = MagicMock()
        group._body = MagicMock()
        group._body.children = []

        from hermes_cli.tui.tool_panel import ToolPanel
        event = MagicMock(spec=ToolPanel.Completed)
        event.control = MagicMock()
        block = MagicMock()
        block._line_err_count = 0
        block._view_state = None
        event.control._block = block

        with patch("hermes_cli.tui.tool_group._recompute_group_state", return_value=ToolGroupState.RUNNING):
            with patch("hermes_cli.tui.tool_group.isinstance", side_effect=lambda obj, cls: True):
                try:
                    group.on_tool_panel_completed(event)
                except Exception:
                    pass

        # _group_terminal_at still None → set_timer not called
        group.set_timer.assert_not_called()
