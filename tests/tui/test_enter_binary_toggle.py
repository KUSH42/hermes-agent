"""R4-1: Enter binary toggle — action, hints, ChildPanel parity.

TestEnterAction       (R4-1A, 4 tests) — action_toggle_collapse is COMPACT↔NOT-COMPACT.
TestEnterHintLabel    (R4-1B, 3 tests) — hint label flips with tier.
TestChildPanelParity  (R4-1C, 3 tests) — ChildPanel inherits parent semantics.
"""
from __future__ import annotations

import inspect
import types
from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_resolver(tier):
    r = MagicMock()
    r.tier = tier
    return r


def _make_action_panel(tier):
    """Minimal namespace that supports action_toggle_collapse."""
    from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
    from hermes_cli.tui.services.tools import ToolCallState

    panel = types.SimpleNamespace()
    panel._resolver = _make_resolver(tier)
    panel._flash_header = MagicMock()
    panel._view_state = None
    panel._lookup_view_state = lambda: None
    panel._is_error = lambda: False
    panel._body_line_count = lambda: 0
    panel._parent_clamp_tier = None
    panel.size = types.SimpleNamespace(width=120)
    panel._block = types.SimpleNamespace()  # no _tail

    # Bind the mixin method
    panel.action_toggle_collapse = _ToolPanelActionsMixin.action_toggle_collapse.__get__(panel)
    return panel


def _make_hint_panel(*, collapsed: bool):
    """Minimal namespace for _collect_hints tests."""
    from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin

    panel = types.SimpleNamespace()
    panel._result_summary_v4 = None
    panel._block = types.SimpleNamespace(_completed=True)
    panel.collapsed = collapsed
    panel._is_error = lambda: False
    panel._visible_footer_action_kinds = lambda: set()
    panel._get_omission_bar = lambda: None
    panel._result_paths_for_action = lambda: []

    # Bind mixin methods needed by _collect_hints
    for name in ("_collect_hints", "_truncate_hints", "_build_hint_text",
                 "_render_hints", "_refresh_hint_row"):
        m = getattr(_ToolPanelActionsMixin, name, None)
        if m is not None:
            setattr(panel, name, m.__get__(panel))

    panel._next_kind_label = None
    panel._view_state = None
    panel._lookup_view_state = lambda: None
    return panel


# ---------------------------------------------------------------------------
# TestEnterAction  (R4-1A)
# ---------------------------------------------------------------------------

class TestEnterAction:
    """action_toggle_collapse is a binary toggle: COMPACT→DEFAULT, else→COMPACT."""

    def test_enter_from_default_collapses_to_compact(self):
        from hermes_cli.tui.tool_panel.density import DensityTier

        panel = _make_action_panel(DensityTier.DEFAULT)
        panel.action_toggle_collapse()

        assert panel._user_override_tier == DensityTier.COMPACT
        assert panel._user_collapse_override is True
        assert panel._auto_collapsed is False
        panel._resolver.resolve.assert_called_once()
        panel._flash_header.assert_called_once_with("collapsed", tone="info")

    def test_enter_from_compact_expands_to_default(self):
        from hermes_cli.tui.tool_panel.density import DensityTier

        panel = _make_action_panel(DensityTier.COMPACT)
        panel.action_toggle_collapse()

        assert panel._user_override_tier == DensityTier.DEFAULT
        assert panel._user_collapse_override is True
        assert panel._auto_collapsed is False
        panel._resolver.resolve.assert_called_once()
        panel._flash_header.assert_called_once_with("expanded", tone="info")

    def test_enter_from_hero_collapses_to_compact(self):
        from hermes_cli.tui.tool_panel.density import DensityTier

        panel = _make_action_panel(DensityTier.HERO)
        panel.action_toggle_collapse()

        assert panel._user_override_tier == DensityTier.COMPACT
        assert panel._user_collapse_override is True
        assert panel._auto_collapsed is False
        panel._resolver.resolve.assert_called_once()
        panel._flash_header.assert_called_once_with("collapsed", tone="info")

    def test_enter_from_trace_collapses_to_compact(self):
        from hermes_cli.tui.tool_panel.density import DensityTier

        panel = _make_action_panel(DensityTier.TRACE)
        panel.action_toggle_collapse()

        assert panel._user_override_tier == DensityTier.COMPACT
        assert panel._user_collapse_override is True
        assert panel._auto_collapsed is False
        panel._resolver.resolve.assert_called_once()
        panel._flash_header.assert_called_once_with("collapsed", tone="info")


# ---------------------------------------------------------------------------
# TestEnterHintLabel  (R4-1B)
# ---------------------------------------------------------------------------

class TestEnterHintLabel:
    """Hint pipeline labels Enter with the actual next state (expand or collapse)."""

    def test_hint_label_collapse_when_default(self):
        """DEFAULT tier (collapsed=False) → hint says 'collapse'; no 'toggle'."""
        panel = _make_hint_panel(collapsed=False)
        primary, _ = panel._collect_hints()

        assert ("Enter", "collapse") in primary
        assert ("Enter", "toggle") not in primary
        assert ("Enter", "expand") not in primary

    def test_hint_label_expand_when_compact(self):
        """COMPACT tier (collapsed=True) → hint says 'expand'; no 'toggle'."""
        panel = _make_hint_panel(collapsed=True)
        primary, _ = panel._collect_hints()

        assert ("Enter", "expand") in primary
        assert ("Enter", "toggle") not in primary
        assert ("Enter", "collapse") not in primary

    @pytest.mark.parametrize("collapsed", [False, False], ids=["hero", "trace"])
    def test_hint_label_collapse_when_hero_or_trace(self, collapsed: bool):
        """HERO and TRACE (both collapsed=False) → hint says 'collapse'."""
        panel = _make_hint_panel(collapsed=collapsed)
        primary, _ = panel._collect_hints()

        assert ("Enter", "collapse") in primary
        assert ("Enter", "toggle") not in primary


# ---------------------------------------------------------------------------
# TestChildPanelParity  (R4-1C)
# ---------------------------------------------------------------------------

class TestChildPanelNoPanelOverride:
    """ChildPanel.action_toggle_collapse is inherited from ToolPanel, not overridden."""

    def test_childpanel_no_local_action_override(self):
        """MRO: action_toggle_collapse resolves on ToolPanel mixin, not ChildPanel."""
        from hermes_cli.tui.child_panel import ChildPanel
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin

        # action_toggle_collapse must NOT be defined directly on ChildPanel
        assert "action_toggle_collapse" not in ChildPanel.__dict__, (
            "ChildPanel still overrides action_toggle_collapse — R4-1C not applied"
        )
        # It must still be resolvable via MRO (from the mixin)
        assert callable(getattr(ChildPanel, "action_toggle_collapse", None))


class _MinimalApp(App):
    """Minimal host for ChildPanel mount tests."""

    def compose(self) -> ComposeResult:
        from hermes_cli.tui.child_panel import ChildPanel
        block = Static("body")
        yield ChildPanel(block=block, tool_name="Bash", depth=1)


class TestChildPanelParity:
    """ChildPanel inherits ToolPanel binary-toggle semantics end-to-end."""

    @pytest.mark.asyncio
    async def test_childpanel_enter_uses_resolver_path(self):
        """After R4-1C: Enter on ChildPanel sets _user_collapse_override and calls _flash_header."""
        from hermes_cli.tui.child_panel import ChildPanel
        from hermes_cli.tui.tool_panel.density import DensityTier

        async with _MinimalApp().run_test() as pilot:
            panel = pilot.app.query_one(ChildPanel)

            # Stub resolver and flash so we don't need real block state
            panel._resolver = _make_resolver(DensityTier.DEFAULT)
            panel._flash_header = MagicMock()
            panel._is_error = lambda: False
            panel._body_line_count = lambda: 0

            panel.action_toggle_collapse()

            assert panel._user_collapse_override is True
            assert panel._user_override_tier is not None
            panel._flash_header.assert_called_once()

    @pytest.mark.asyncio
    async def test_childpanel_enter_matches_toolpanel_semantics(self):
        """ChildPanel Enter transitions match the R4-1A behavior table."""
        from hermes_cli.tui.child_panel import ChildPanel
        from hermes_cli.tui.tool_panel.density import DensityTier

        async with _MinimalApp().run_test() as pilot:
            panel = pilot.app.query_one(ChildPanel)
            panel._is_error = lambda: False
            panel._body_line_count = lambda: 0

            # DEFAULT → COMPACT
            panel._resolver = _make_resolver(DensityTier.DEFAULT)
            panel._flash_header = MagicMock()
            panel.action_toggle_collapse()
            assert panel._user_override_tier == DensityTier.COMPACT
            panel._flash_header.assert_called_once_with("collapsed", tone="info")

            # COMPACT → DEFAULT
            panel._resolver = _make_resolver(DensityTier.COMPACT)
            panel._flash_header = MagicMock()
            panel.action_toggle_collapse()
            assert panel._user_override_tier == DensityTier.DEFAULT
            panel._flash_header.assert_called_once_with("expanded", tone="info")

            # HERO → COMPACT
            panel._resolver = _make_resolver(DensityTier.HERO)
            panel._flash_header = MagicMock()
            panel.action_toggle_collapse()
            assert panel._user_override_tier == DensityTier.COMPACT
            panel._flash_header.assert_called_once_with("collapsed", tone="info")
