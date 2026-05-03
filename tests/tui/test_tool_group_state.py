"""Tests for ToolGroupState ERR-sticky aggregation (TB-H1).

TestERRSticky: 10 unit tests covering enum shape, aggregation logic,
ERR-sticky rule, terminal absorbing, and caller-side set_class path.
All tests use types.SimpleNamespace to stub child widgets — no mounted DOM required.
"""

from __future__ import annotations

import types


def _make_child(state: object) -> object:
    """Return a SimpleNamespace stub with _view_state.state set."""
    return types.SimpleNamespace(
        _view_state=types.SimpleNamespace(state=state)
    )


class TestERRSticky:
    def test_enum_has_no_partial_member(self) -> None:
        from hermes_cli.tui.tool_group import ToolGroupState
        assert "PARTIAL" not in {s.name for s in ToolGroupState}

    def test_enum_uses_err_not_error(self) -> None:
        from hermes_cli.tui.tool_group import ToolGroupState
        assert ToolGroupState.ERR.value == "err"
        assert not hasattr(ToolGroupState, "ERROR")

    def test_empty_children_returns_pending(self) -> None:
        from hermes_cli.tui.tool_group import _recompute_group_state, ToolGroupState
        result = _recompute_group_state([])
        assert result is ToolGroupState.PENDING

    def test_all_done_returns_done(self) -> None:
        from hermes_cli.tui.tool_group import _recompute_group_state, ToolGroupState
        from hermes_cli.tui.services.tools import ToolCallState
        children = [_make_child(ToolCallState.DONE) for _ in range(3)]
        result = _recompute_group_state(children)
        assert result is ToolGroupState.DONE

    def test_one_err_among_dones_returns_err(self) -> None:
        """Regression fence for TB-H1: was wrongly returning PARTIAL."""
        from hermes_cli.tui.tool_group import _recompute_group_state, ToolGroupState
        from hermes_cli.tui.services.tools import ToolCallState
        children = [_make_child(ToolCallState.DONE)] * 99 + [_make_child(ToolCallState.ERROR)]
        result = _recompute_group_state(children)
        assert result is ToolGroupState.ERR

    def test_one_err_with_streaming_returns_err(self) -> None:
        """ERR-sticky fires even when non-terminal siblings are still running."""
        from hermes_cli.tui.tool_group import _recompute_group_state, ToolGroupState
        from hermes_cli.tui.services.tools import ToolCallState
        children = [
            _make_child(ToolCallState.ERROR),
            _make_child(ToolCallState.STREAMING),
        ]
        result = _recompute_group_state(children, current_state=ToolGroupState.RUNNING)
        assert result is ToolGroupState.ERR

    def test_done_plus_cancelled_returns_cancelled(self) -> None:
        from hermes_cli.tui.tool_group import _recompute_group_state, ToolGroupState
        from hermes_cli.tui.services.tools import ToolCallState
        children = [
            _make_child(ToolCallState.DONE),
            _make_child(ToolCallState.DONE),
            _make_child(ToolCallState.CANCELLED),
        ]
        result = _recompute_group_state(children, current_state=ToolGroupState.RUNNING)
        assert result is ToolGroupState.CANCELLED

    def test_terminal_absorbing_done_then_late_streaming(self) -> None:
        from hermes_cli.tui.tool_group import _recompute_group_state, ToolGroupState
        from hermes_cli.tui.services.tools import ToolCallState
        children = [_make_child(ToolCallState.STREAMING)]
        result = _recompute_group_state(children, current_state=ToolGroupState.DONE)
        assert result is ToolGroupState.DONE

    def test_terminal_absorbing_err_then_late_done(self) -> None:
        from hermes_cli.tui.tool_group import _recompute_group_state, ToolGroupState
        from hermes_cli.tui.services.tools import ToolCallState
        children = [_make_child(ToolCallState.DONE) for _ in range(5)]
        result = _recompute_group_state(children, current_state=ToolGroupState.ERR)
        assert result is ToolGroupState.ERR

    def test_caller_set_class_uses_only_err_branch(self) -> None:
        """_recompute_group_state with ERROR child and current_state=None returns ERR;
        ToolGroupState has no PARTIAL member (enum shape guard)."""
        from hermes_cli.tui.tool_group import _recompute_group_state, ToolGroupState
        from hermes_cli.tui.services.tools import ToolCallState
        children = [_make_child(ToolCallState.ERROR)]
        result = _recompute_group_state(children, current_state=None)
        assert result is ToolGroupState.ERR
        assert "PARTIAL" not in {s.name for s in ToolGroupState}
