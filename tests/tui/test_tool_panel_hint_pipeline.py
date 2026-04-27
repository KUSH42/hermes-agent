"""Hint pipeline unification — H-1..H-4.

Tests:
  TestStaticPipelineRetired     (H-1, 3 tests) — static tuples + old methods deleted
  TestDynamicHintCollection     (H-2, 5 tests) — _collect_hints / _build_hint_text logic
  TestHintTruncator             (H-3, 3 tests) — _truncate_hints + F1 pinning
  TestDensityCycleBinding       (H-4, 4 tests) — D binding + action_density_cycle
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rs(
    *,
    is_error: bool = False,
    stderr_tail: str = "",
    exit_code: int | None = 0,
    actions=(),
    artifacts=(),
):
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    return ResultSummaryV4(
        primary=None,
        exit_code=exit_code,
        chips=(),
        actions=list(actions),
        artifacts=list(artifacts),
        is_error=is_error,
        stderr_tail=stderr_tail,
    )


def _make_block(*, completed: bool = True):
    block = MagicMock()
    block._completed = completed
    return block


def _make_panel(
    *,
    rs=None,
    block=None,
    collapsed: bool = False,
    has_omission_bar: bool = False,
    visible_footer: set | None = None,
    result_paths=(),
) -> types.SimpleNamespace:
    """Minimal panel-like object with all attrs that _collect_hints / _render_hints use."""
    from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin

    panel = types.SimpleNamespace()
    panel._result_summary_v4 = rs
    panel._block = block if block is not None else _make_block(completed=True)
    panel.collapsed = collapsed
    panel.is_mounted = True
    panel.size = types.SimpleNamespace(width=120)

    # Patch helpers that inspect DOM / state
    panel._is_error = lambda: rs is not None and bool(rs.is_error)
    panel._visible_footer_action_kinds = lambda: visible_footer if visible_footer is not None else set()
    panel._get_omission_bar = lambda: MagicMock() if has_omission_bar else None
    panel._result_paths_for_action = lambda: list(result_paths)

    # Bind mixin methods
    for name in ("_collect_hints", "_render_hints", "_truncate_hints", "_build_hint_text",
                 "_refresh_hint_row"):
        method = getattr(_ToolPanelActionsMixin, name)
        setattr(panel, name, method.__get__(panel))

    # Static method — assign directly (no self binding)
    panel._next_kind_label = _ToolPanelActionsMixin._next_kind_label

    return panel


# ---------------------------------------------------------------------------
# H-1 — Static pipeline retired
# ---------------------------------------------------------------------------

class TestStaticPipelineRetired:
    def test_static_constants_importerror(self):
        """DEFAULT_HINTS / ERROR_HINTS / COLLAPSED_HINTS removed from module."""
        import importlib
        import sys
        import pytest

        for name in ("DEFAULT_HINTS", "ERROR_HINTS", "COLLAPSED_HINTS"):
            sys.modules.pop("hermes_cli.tui.tool_panel._actions", None)
            with pytest.raises(ImportError):
                exec(
                    f"from hermes_cli.tui.tool_panel._actions import {name}",
                    {},
                )

    def test_format_and_select_hint_set_deleted(self):
        """_format and _select_hint_set are no longer methods on the mixin."""
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        assert not hasattr(_ToolPanelActionsMixin, "_format"), "_format should be removed"
        assert not hasattr(_ToolPanelActionsMixin, "_select_hint_set"), "_select_hint_set should be removed"

    def test_refresh_hint_row_calls_dynamic_builder(self):
        """_refresh_hint_row delegates to _build_hint_text, not the static pipeline."""
        from rich.text import Text
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin

        panel = types.SimpleNamespace()
        panel.has_focus = True
        panel._hint_row = MagicMock()

        sentinel = Text("X")

        def fake_build():
            return sentinel

        panel._build_hint_text = fake_build
        panel.has_class = lambda _cls: False

        _ToolPanelActionsMixin._refresh_hint_row(panel)

        panel._hint_row.update.assert_called_once_with(sentinel)
        panel._hint_row.add_class.assert_called_once_with("--has-hint")


# ---------------------------------------------------------------------------
# H-2 — Dynamic hint collection
# ---------------------------------------------------------------------------

class TestDynamicHintCollection:
    def test_streaming_primary_is_enter_follow_and_f_tail(self):
        """While block is streaming, primary == [('Enter','follow'), ('f','tail')]."""
        panel = _make_panel(
            rs=None,
            block=_make_block(completed=False),
        )
        primary, _ = panel._collect_hints()
        assert primary == [("Enter", "follow"), ("f", "tail")]

    def test_collapsed_primary_is_enter_expand_and_y_copy(self):
        """collapsed=True → primary == [('Enter','expand'), ('y','copy')]."""
        panel = _make_panel(
            rs=_make_rs(),
            collapsed=True,
        )
        primary, _ = panel._collect_hints()
        assert primary == [("Enter", "expand"), ("y", "copy")]

    def test_error_primary_is_enter_collapse_and_r_retry(self):
        """is_error=True terminal (expanded) → primary == [('Enter','collapse'), ('r','retry')];
        ('r','retry') NOT duplicated in contextual."""
        panel = _make_panel(rs=_make_rs(is_error=True, exit_code=1))
        primary, contextual = panel._collect_hints()
        assert primary == [("Enter", "collapse"), ("r", "retry")]
        assert ("r", "retry") not in contextual, "r retry must not appear twice"

    def test_contextual_includes_density_cycle_hints_when_complete_expanded(self):
        """Complete expanded block → D density-cycle and shift+d density-back in contextual."""
        panel = _make_panel(
            rs=_make_rs(),
            block=_make_block(completed=True),
            collapsed=False,
        )
        _, contextual = panel._collect_hints()
        assert ("D", "density-cycle") in contextual
        assert ("shift+d", "density-back") in contextual
        assert ("alt+t", "trace") not in contextual

    def test_contextual_dedups_against_footer_chips(self):
        """If footer already shows copy_err chip, ('e','stderr') absent from contextual."""
        panel = _make_panel(
            rs=_make_rs(stderr_tail="err output"),
            visible_footer={"copy_err"},
        )
        _, contextual = panel._collect_hints()
        assert ("e", "stderr") not in contextual


# ---------------------------------------------------------------------------
# H-3 — Truncator
# ---------------------------------------------------------------------------

class TestHintTruncator:
    def _make_truncator(self):
        """Return a minimal panel with _truncate_hints bound."""
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        panel = types.SimpleNamespace()
        panel._truncate_hints = _ToolPanelActionsMixin._truncate_hints.__get__(panel)
        return panel

    def test_truncate_hints_full_fit(self):
        """Large budget → all chips rendered; dropped == 0."""
        panel = self._make_truncator()
        chips = [("y", "copy"), ("r", "retry"), ("e", "stderr"), ("o", "open")]
        out, dropped = panel._truncate_hints(chips, budget=200)
        assert dropped == 0
        # All keys present in rendered text
        text_str = out.plain
        for k, _ in chips:
            assert k in text_str

    def test_truncate_hints_partial_drop_emits_count(self):
        """Tight budget → some chips dropped; dropped count is correct."""
        panel = self._make_truncator()
        # 6 chips each ~6 cells wide; budget forces partial fit
        chips = [("+", "more"), ("*", "all"), ("e", "stderr"), ("o", "open"), ("u", "urls"), ("t", "render as")]
        out, dropped = panel._truncate_hints(chips, budget=20)
        fitted_count = len(chips) - dropped
        assert 1 <= fitted_count <= 4, f"expected 1-4 fitted, got {fitted_count}"
        assert dropped >= 2
        assert out.cell_len <= 20

    def test_f1_pinned_at_min_width(self):
        """_render_hints always includes F1 help regardless of contextual size."""
        panel = _make_panel(rs=None)
        panel.size = types.SimpleNamespace(width=25)

        # Many contextual chips — all should be dropped but F1 must survive
        primary = [("Enter", "toggle"), ("y", "copy")]
        contextual = [("a", "b"), ("c", "d"), ("e", "f"), ("g", "h"), ("i", "j"), ("k", "l")]
        result = panel._render_hints(primary, contextual, 25)
        assert "F1" in result.plain
        assert "help" in result.plain


# ---------------------------------------------------------------------------
# H-4 — Density cycle binding
# ---------------------------------------------------------------------------

class TestDensityCycleBinding:
    def test_d_binding_present(self):
        """ToolPanel BINDINGS contains a 'D' key bound to 'density_cycle'."""
        from hermes_cli.tui.tool_panel import ToolPanel
        keys = {b.key: b.action for b in ToolPanel.BINDINGS}
        assert "D" in keys, "No 'D' binding on ToolPanel"
        assert keys["D"] == "density_cycle", f"Expected density_cycle, got {keys['D']}"

    def test_action_density_cycle_advances_tier(self):
        """DEFAULT → COMPACT → TRACE → HERO → DEFAULT (4-tier; resolver accepts every tier)."""
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        from hermes_cli.tui.tool_panel.density import DensityTier

        panel = types.SimpleNamespace()

        # Resolver that always accepts the requested tier
        resolver = MagicMock()
        resolver.tier = DensityTier.DEFAULT

        def accepting_resolve(inputs):
            resolver.tier = inputs.user_override_tier

        resolver.resolve.side_effect = accepting_resolve

        panel._resolver = resolver
        panel._user_collapse_override = False
        panel._user_override_tier = None
        panel._auto_collapsed = False
        panel._view_state = None
        panel._lookup_view_state = lambda: None
        panel._is_error = lambda: False
        panel._body_line_count = lambda: 10
        panel._parent_clamp_tier = None
        panel._flash_header = MagicMock()

        panel.action_density_cycle = _ToolPanelActionsMixin.action_density_cycle.__get__(panel)

        panel.action_density_cycle()
        assert resolver.tier == DensityTier.COMPACT

        panel.action_density_cycle()
        assert resolver.tier == DensityTier.TRACE

        panel.action_density_cycle()
        assert resolver.tier == DensityTier.HERO

        panel.action_density_cycle()
        assert resolver.tier == DensityTier.DEFAULT

    def test_action_density_cycle_hero_ineligible(self):
        """When resolver rejects HERO (pressure gate), _flash_header called with tone='warning'.

        Row-budget check passes (body_lines=10) so _next_legal_tier_static returns HERO;
        resolver then rejects it (simulates pressure gate), triggering the warning flash.
        """
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        from hermes_cli.tui.tool_panel.density import DensityTier

        panel = types.SimpleNamespace()

        resolver = MagicMock()
        resolver.tier = DensityTier.TRACE  # start at TRACE so next (row-legal) is HERO

        def rejecting_hero_resolve(inputs):
            if inputs.user_override_tier == DensityTier.HERO:
                resolver.tier = DensityTier.DEFAULT  # resolver rejects HERO (pressure)
            else:
                resolver.tier = inputs.user_override_tier

        resolver.resolve.side_effect = rejecting_hero_resolve

        panel._resolver = resolver
        panel._user_collapse_override = False
        panel._user_override_tier = None
        panel._auto_collapsed = False
        panel._view_state = None
        panel._lookup_view_state = lambda: None
        panel._is_error = lambda: False
        panel._body_line_count = lambda: 10  # row-legal; HERO pre-skip does NOT fire
        panel._parent_clamp_tier = None
        flash_mock = MagicMock()
        panel._flash_header = flash_mock

        panel.action_density_cycle = _ToolPanelActionsMixin.action_density_cycle.__get__(panel)

        panel.action_density_cycle()  # TRACE → HERO (row-legal, but resolver rejects)
        call_kwargs = flash_mock.call_args
        assert call_kwargs is not None
        assert call_kwargs[1].get("tone") == "warning" or (
            len(call_kwargs[0]) > 1 and call_kwargs[0][1] == "warning"
        ), f"Expected tone=warning, got {call_kwargs}"
        msg = call_kwargs[0][0]
        assert "hero" in msg.lower(), f"Expected 'hero' in message, got {msg!r}"

    def test_density_cycle_flashes_destination(self):
        """Happy path: flash called once with tier name and no warning tone."""
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        from hermes_cli.tui.tool_panel.density import DensityTier

        panel = types.SimpleNamespace()
        panel._next_tier_in_cycle = _ToolPanelActionsMixin._next_tier_in_cycle

        resolver = MagicMock()
        resolver.tier = DensityTier.DEFAULT

        def accepting_resolve(inputs):
            resolver.tier = inputs.user_override_tier

        resolver.resolve.side_effect = accepting_resolve

        panel._resolver = resolver
        panel._user_collapse_override = False
        panel._user_override_tier = None
        panel._auto_collapsed = False
        panel._view_state = None
        panel._lookup_view_state = lambda: None
        panel._is_error = lambda: False
        panel._body_line_count = lambda: 20
        panel._parent_clamp_tier = None
        flash_mock = MagicMock()
        panel._flash_header = flash_mock

        panel.action_density_cycle = _ToolPanelActionsMixin.action_density_cycle.__get__(panel)

        panel.action_density_cycle()
        flash_mock.assert_called_once()
        call_kwargs = flash_mock.call_args
        # Should NOT have tone="warning"
        tone = call_kwargs[1].get("tone", "success")
        assert tone != "warning", f"Unexpected warning tone on happy path: {call_kwargs}"
        # Should mention density or the tier name
        msg = call_kwargs[0][0]
        assert "compact" in msg.lower() or "density" in msg.lower(), f"Unexpected message: {msg!r}"
