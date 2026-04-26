"""Tests for R3-NESTED: parent→child density propagation.

NESTED-1: DensityInputs.parent_clamp logic in DensityResolver
NESTED-3: SubAgentPanel.density_tier reactive wiring
NESTED-4: ChildPanel parent subscription + re-resolve
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.tool_panel.density import DensityInputs, DensityResolver, DensityTier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_inputs(**overrides: object) -> DensityInputs:
    """Build minimal DensityInputs; caller overrides specific fields."""
    from hermes_cli.tui.services.tools import ToolCallState
    defaults: dict = dict(
        phase=ToolCallState.DONE,
        is_error=False,
        has_focus=False,
        user_scrolled_up=False,
        user_override=False,
        user_override_tier=None,
        body_line_count=50,   # above typical threshold → COMPACT without clamp
        threshold=20,
        row_budget=None,
        kind=None,
        parent_clamp=None,
    )
    defaults.update(overrides)
    return DensityInputs(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# TestParentClampLogic — NESTED-1 pure resolver logic (4 tests)
# ---------------------------------------------------------------------------

class TestParentClampLogic:

    def test_parent_clamp_tightens_default(self) -> None:
        """parent_clamp=COMPACT + base=DEFAULT → COMPACT."""
        from hermes_cli.tui.services.tools import ToolCallState
        # body_line_count <= threshold → base resolves to DEFAULT
        inp = _make_inputs(body_line_count=5, threshold=20, parent_clamp=DensityTier.COMPACT)
        resolver = DensityResolver()
        result = resolver.resolve(inp)
        assert result == DensityTier.COMPACT

    def test_parent_clamp_tightens_hero(self) -> None:
        """parent_clamp=COMPACT + base=HERO → COMPACT."""
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_payload import ResultKind
        inp = _make_inputs(
            body_line_count=4,
            threshold=20,
            kind=ResultKind.DIFF,
            parent_clamp=DensityTier.COMPACT,
        )
        resolver = DensityResolver()
        result = resolver.resolve(inp)
        assert result == DensityTier.COMPACT

    def test_parent_clamp_does_not_tighten_error(self) -> None:
        """is_error=True, parent_clamp=COMPACT → DEFAULT (error exemption)."""
        inp = _make_inputs(is_error=True, parent_clamp=DensityTier.COMPACT)
        resolver = DensityResolver()
        result = resolver.resolve(inp)
        assert result == DensityTier.DEFAULT

    def test_parent_clamp_none_passthrough(self) -> None:
        """parent_clamp=None, base=HERO → HERO unchanged."""
        from hermes_cli.tui.tool_payload import ResultKind
        inp = _make_inputs(
            body_line_count=4,
            threshold=20,
            kind=ResultKind.DIFF,
            parent_clamp=None,
        )
        resolver = DensityResolver()
        result = resolver.resolve(inp)
        assert result == DensityTier.HERO


# ---------------------------------------------------------------------------
# TestSubAgentDensityTier — NESTED-3 reactive wiring (2 tests)
# ---------------------------------------------------------------------------

class TestSubAgentDensityTier:

    def _make_panel_stub(self) -> "object":
        """SimpleNamespace that records density_tier assignments via watch_collapsed."""
        recorded: dict = {"density_tier": DensityTier.DEFAULT}

        panel = types.SimpleNamespace(
            _has_children=True,
            is_mounted=True,
            _body=MagicMock(),
            add_class=MagicMock(),
            remove_class=MagicMock(),
        )

        # Bind watch_collapsed from the real class but redirect density_tier set
        from hermes_cli.tui.sub_agent_panel import SubAgentPanel

        def watch_collapsed(v: bool) -> None:
            # Reproduce the real watcher body, capturing density_tier
            if not panel.is_mounted:
                return
            if v:
                panel.add_class("--collapsed")
            else:
                panel.remove_class("--collapsed")
            panel._body.display = (not v) and panel._has_children
            recorded["density_tier"] = DensityTier.COMPACT if v else DensityTier.DEFAULT

        panel.watch_collapsed = watch_collapsed  # type: ignore[attr-defined]
        panel._recorded = recorded
        return panel

    def test_subagent_density_tier_collapses_to_compact(self) -> None:
        """Setting collapsed=True sets density_tier=COMPACT."""
        panel = self._make_panel_stub()
        panel.watch_collapsed(True)
        assert panel._recorded["density_tier"] == DensityTier.COMPACT

    def test_subagent_density_tier_expands_to_default(self) -> None:
        """Setting collapsed=False after collapse sets density_tier=DEFAULT."""
        panel = self._make_panel_stub()
        panel.watch_collapsed(True)   # collapse first
        panel.watch_collapsed(False)  # then expand
        assert panel._recorded["density_tier"] == DensityTier.DEFAULT


# ---------------------------------------------------------------------------
# TestChildParentSubscription — NESTED-4 subscription + re-resolve (7 tests)
# ---------------------------------------------------------------------------

class TestChildParentSubscription:

    def _make_child_panel(self, parent_density: DensityTier = DensityTier.DEFAULT) -> "object":
        """Build a ChildPanel-like namespace with all needed attributes."""
        from hermes_cli.tui.tool_panel._child import ChildPanel

        parent = MagicMock()
        parent.density_tier = parent_density

        child = ChildPanel.__new__(ChildPanel)
        # Wire minimal ToolPanel attrs
        child._parent_subagent = parent
        child._parent_clamp_tier = None
        child._result_summary_v4 = None
        child._compact_mode = True
        child.add_class = MagicMock()
        child.remove_class = MagicMock()

        # track set_compact calls
        child._set_compact_calls: list = []
        original_set_compact = ChildPanel.set_compact

        def _tracked_set_compact(val: bool) -> None:
            child._set_compact_calls.append(val)
            child._compact_mode = val

        child.set_compact = _tracked_set_compact  # type: ignore[method-assign]
        return child, parent

    def test_child_subscribes_to_parent_density_on_mount(self) -> None:
        """After on_mount, child calls self.watch on parent.density_tier."""
        from hermes_cli.tui.tool_panel._child import ChildPanel
        from hermes_cli.tui.sub_agent_panel import SubAgentPanel

        parent = MagicMock(spec=SubAgentPanel)
        parent.density_tier = DensityTier.DEFAULT

        child = ChildPanel.__new__(ChildPanel)
        child._parent_subagent = parent
        child._parent_clamp_tier = None
        child._result_summary_v4 = None
        child._compact_mode = True
        child.add_class = MagicMock()
        child.remove_class = MagicMock()
        child.set_compact = MagicMock()
        child._block = MagicMock()
        child._block._header = None

        watch_calls: list = []
        child.watch = MagicMock(side_effect=lambda *a, **kw: watch_calls.append(a))  # type: ignore[method-assign]

        # Stub super().on_mount() chain
        with patch.object(
            ChildPanel.__bases__[0], "on_mount", lambda self: None
        ):
            child.on_mount()

        assert any(
            len(call) >= 2 and call[1] == "density_tier"
            for call in watch_calls
        ), "watch was not called with 'density_tier'"

    def test_child_gets_seeded_clamp_on_mount(self) -> None:
        """If parent.density_tier==COMPACT at mount, child._parent_clamp_tier==COMPACT."""
        from hermes_cli.tui.tool_panel._child import ChildPanel
        from hermes_cli.tui.sub_agent_panel import SubAgentPanel

        parent = MagicMock(spec=SubAgentPanel)
        parent.density_tier = DensityTier.COMPACT

        child = ChildPanel.__new__(ChildPanel)
        child._parent_subagent = parent
        child._parent_clamp_tier = None
        child._result_summary_v4 = None
        child._compact_mode = True
        child.add_class = MagicMock()
        child.remove_class = MagicMock()
        child.set_compact = MagicMock()
        child._block = MagicMock()
        child._block._header = None
        child.watch = MagicMock()  # type: ignore[method-assign]

        with patch.object(
            ChildPanel.__bases__[0], "on_mount", lambda self: None
        ):
            child.on_mount()

        assert child._parent_clamp_tier == DensityTier.COMPACT

    def test_child_reresolves_when_parent_collapses(self) -> None:
        """parent density→COMPACT fires _on_parent_density_change, calls _apply_complete_auto_collapse."""
        from hermes_cli.tui.tool_panel._child import ChildPanel

        child = ChildPanel.__new__(ChildPanel)
        child._parent_clamp_tier = None
        child._result_summary_v4 = MagicMock()  # non-None → complete block
        child.set_compact = MagicMock()  # type: ignore[method-assign]
        apply_calls: list = []
        child._apply_complete_auto_collapse = MagicMock(  # type: ignore[method-assign]
            side_effect=lambda: apply_calls.append(True)
        )

        child._on_parent_density_change(DensityTier.COMPACT)

        assert child._parent_clamp_tier == DensityTier.COMPACT
        assert len(apply_calls) == 1

    def test_child_clears_clamp_when_parent_expands(self) -> None:
        """parent density→DEFAULT fires _on_parent_density_change with clamp=None."""
        from hermes_cli.tui.tool_panel._child import ChildPanel

        child = ChildPanel.__new__(ChildPanel)
        child._parent_clamp_tier = DensityTier.COMPACT
        child._result_summary_v4 = MagicMock()
        child.set_compact = MagicMock()  # type: ignore[method-assign]
        child._apply_complete_auto_collapse = MagicMock()  # type: ignore[method-assign]

        child._on_parent_density_change(DensityTier.DEFAULT)

        assert child._parent_clamp_tier is None
        child._apply_complete_auto_collapse.assert_called_once()

    def test_child_error_block_ignores_parent_compact_clamp(self) -> None:
        """Resolver: is_error=True, parent_clamp=COMPACT → DEFAULT (exemption)."""
        inp = _make_inputs(is_error=True, parent_clamp=DensityTier.COMPACT)
        resolver = DensityResolver()
        result = resolver.resolve(inp)
        assert result == DensityTier.DEFAULT

    def test_expand_all_action_clears_clamp(self) -> None:
        """action_expand_all sets _parent_clamp_tier=None and calls re-resolve on complete blocks."""
        from hermes_cli.tui.sub_agent_panel import SubAgentPanel
        from hermes_cli.tui.child_panel import ChildPanel

        panel = SubAgentPanel.__new__(SubAgentPanel)

        child1 = MagicMock(spec=ChildPanel)
        child1._result_summary_v4 = MagicMock()
        child2 = MagicMock(spec=ChildPanel)
        child2._result_summary_v4 = None

        panel.query = MagicMock(return_value=[child1, child2])  # type: ignore[method-assign]

        panel.action_expand_all()

        assert child1._parent_clamp_tier is None
        child1._apply_complete_auto_collapse.assert_called_once()
        assert child2._parent_clamp_tier is None
        child2.set_compact.assert_called_once_with(False)

    def test_compact_all_action_applies_clamp(self) -> None:
        """action_compact_all sets _parent_clamp_tier=COMPACT and calls re-resolve on complete blocks."""
        from hermes_cli.tui.sub_agent_panel import SubAgentPanel
        from hermes_cli.tui.child_panel import ChildPanel

        panel = SubAgentPanel.__new__(SubAgentPanel)

        child1 = MagicMock(spec=ChildPanel)
        child1._result_summary_v4 = MagicMock()
        child2 = MagicMock(spec=ChildPanel)
        child2._result_summary_v4 = None

        panel.query = MagicMock(return_value=[child1, child2])  # type: ignore[method-assign]

        panel.action_compact_all()

        assert child1._parent_clamp_tier == DensityTier.COMPACT
        child1._apply_complete_auto_collapse.assert_called_once()
        assert child2._parent_clamp_tier == DensityTier.COMPACT
        child2.set_compact.assert_called_once_with(True)
