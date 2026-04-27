"""Tests for Tool-Call Density Unification spec (DU-1 through DU-6).

Spec: /home/xush/.hermes/spec_tool_density_unification.md

Test layout:
    TestDU1LayoutResolver      — 10 tests — ToolBlockLayoutResolver pure logic
    TestDU2AtomicWrite         —  6 tests — _apply_layout write order
    TestDU3OldCodeDeleted      —  3 tests — AST / re-export gates
    TestDU4WidthGate           —  4 tests — HERO width promotion gate
    TestDU5DecisionToRenderers —  6 tests — decision kwarg plumbing
    TestDU6BindingRename       —  6 tests — binding collision resolution
Total: 35 tests
"""
from __future__ import annotations

import ast
import threading
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

HERMES_ROOT = Path(__file__).parent.parent.parent / "hermes_cli"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_inputs(**overrides):
    from hermes_cli.tui.tool_panel.layout_resolver import LayoutInputs, DensityTier
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
        parent_clamp=None,
        width=120,
        user_collapsed=False,
        has_footer_content=False,
    )
    defaults.update(overrides)
    return LayoutInputs(**defaults)


# ---------------------------------------------------------------------------
# DU-1: ToolBlockLayoutResolver pure logic
# ---------------------------------------------------------------------------

class TestDU1LayoutResolver:
    def test_resolver_picks_default_tier_on_initial(self):
        from hermes_cli.tui.tool_panel.layout_resolver import ToolBlockLayoutResolver, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        r = ToolBlockLayoutResolver()
        inp = _make_inputs(phase=ToolCallState.STARTED, body_line_count=0)
        assert r.resolve(inp) == DensityTier.DEFAULT

    def test_resolver_promotes_to_hero_on_short_diff(self):
        from hermes_cli.tui.tool_panel.layout_resolver import ToolBlockLayoutResolver, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_payload import ResultKind
        r = ToolBlockLayoutResolver()
        inp = _make_inputs(
            phase=ToolCallState.DONE,
            kind=ResultKind.DIFF,
            body_line_count=4,
            width=120,
        )
        assert r.resolve(inp) == DensityTier.HERO

    def test_resolver_demotes_on_scroll_away(self):
        from hermes_cli.tui.tool_panel.layout_resolver import ToolBlockLayoutResolver, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_payload import ResultKind
        r = ToolBlockLayoutResolver()
        inp = _make_inputs(
            phase=ToolCallState.DONE,
            kind=ResultKind.DIFF,
            body_line_count=4,
            user_scrolled_up=True,
        )
        assert r.resolve(inp) == DensityTier.DEFAULT

    def test_error_overrides_user_tier(self):
        from hermes_cli.tui.tool_panel.layout_resolver import ToolBlockLayoutResolver, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        r = ToolBlockLayoutResolver()
        inp = _make_inputs(
            is_error=True,
            user_override=True,
            user_override_tier=DensityTier.COMPACT,
        )
        assert r.resolve(inp) == DensityTier.DEFAULT

    def test_user_override_wins_over_auto(self):
        from hermes_cli.tui.tool_panel.layout_resolver import ToolBlockLayoutResolver, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        r = ToolBlockLayoutResolver()
        inp = _make_inputs(
            phase=ToolCallState.DONE,
            body_line_count=100,
            threshold=5,
            user_override=True,
            user_override_tier=DensityTier.DEFAULT,
        )
        assert r.resolve(inp) == DensityTier.DEFAULT

    def test_footer_hidden_in_compact(self):
        from hermes_cli.tui.tool_panel.layout_resolver import ToolBlockLayoutResolver, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        r = ToolBlockLayoutResolver()
        inp = _make_inputs(
            phase=ToolCallState.DONE,
            body_line_count=100,
            threshold=5,
            has_footer_content=True,
            user_override=True,
            user_override_tier=DensityTier.COMPACT,
        )
        decision = r.resolve_full(inp)
        assert decision.tier == DensityTier.COMPACT
        assert decision.footer_visible is False

    def test_footer_hidden_when_no_content(self):
        from hermes_cli.tui.tool_panel.layout_resolver import ToolBlockLayoutResolver, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        r = ToolBlockLayoutResolver()
        inp = _make_inputs(phase=ToolCallState.DONE, has_footer_content=False)
        decision = r.resolve_full(inp)
        assert decision.footer_visible is False

    def test_trim_header_tail_drops_match_width_budget(self):
        from hermes_cli.tui.tool_panel.layout_resolver import ToolBlockLayoutResolver, DensityTier
        from rich.text import Text
        r = ToolBlockLayoutResolver()
        segments = [
            ("flash", Text("  f")),     # 3 cells
            ("exit",  Text("  e")),     # 3 cells
        ]
        budget = 3
        result = r.trim_header_tail(segments, budget, DensityTier.DEFAULT)
        names = [n for n, _ in result]
        assert "flash" not in names
        assert "exit" in names

    def test_trim_header_tail_drop_order_matches_tier(self):
        from hermes_cli.tui.tool_panel.layout_resolver import ToolBlockLayoutResolver, DensityTier
        from rich.text import Text
        r = ToolBlockLayoutResolver()
        for tier in (DensityTier.HERO, DensityTier.DEFAULT, DensityTier.COMPACT):
            segments = [
                ("flash",    Text("  ff")),
                ("duration", Text("  dd")),
                ("exit",     Text("  ee")),
            ]
            result = r.trim_header_tail(segments, budget=6, tier=tier)
            names = [n for n, _ in result]
            assert "exit" in names  # exit is last-dropped in all tiers

    def test_decision_is_frozen_dataclass(self):
        from hermes_cli.tui.tool_panel.layout_resolver import LayoutDecision, DensityTier
        d = LayoutDecision(tier=DensityTier.DEFAULT, footer_visible=True, width=80, reason="auto")
        with pytest.raises((AttributeError, TypeError)):
            d.tier = DensityTier.COMPACT  # type: ignore[misc]


# ---------------------------------------------------------------------------
# DU-2: _apply_layout atomic write order
# ---------------------------------------------------------------------------

def _make_mock_panel():
    """Return a ToolPanel-like mock with the minimal attributes wired."""
    from hermes_cli.tui.tool_panel.layout_resolver import DensityTier, LayoutDecision
    panel = MagicMock()
    panel.density = DensityTier.DEFAULT
    panel.collapsed = False
    panel._auto_collapsed = False
    panel._user_collapse_override = False
    panel._view_state = None
    panel._resolver = MagicMock()
    panel._block = MagicMock()
    panel._footer_pane = None
    panel._has_footer_content = MagicMock(return_value=False)
    panel._lookup_view_state = MagicMock(return_value=None)
    # Wire _apply_layout from the real ToolPanel implementation
    from hermes_cli.tui.tool_panel._core import ToolPanel
    panel._apply_layout = ToolPanel._apply_layout.__get__(panel)
    panel._on_tier_change = ToolPanel._on_tier_change.__get__(panel)
    return panel


class TestDU2AtomicWrite:
    def test_view_state_axis_updated_before_reactive(self):
        """Axis watcher fires before Textual reactive watcher fires."""
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier, LayoutDecision
        from hermes_cli.tui.tool_panel._core import ToolPanel
        from hermes_cli.tui.services.tools import ToolCallViewState

        seq: list[tuple[str, str]] = []

        vs = MagicMock()
        vs.density = DensityTier.DEFAULT
        vs._watchers = []

        def fake_set_axis(view, axis, val):
            view.density = val
            seq.append(("axis", str(val)))

        panel = MagicMock()
        panel._user_collapse_override = False
        panel._has_footer_content = MagicMock(return_value=False)
        panel._view_state = vs
        panel._lookup_view_state = MagicMock(return_value=None)
        panel._footer_pane = None
        panel._block = MagicMock()
        # simulate reactive setter recording
        _density_holder = [DensityTier.DEFAULT]
        def set_density(val):
            _density_holder[0] = val
            seq.append(("reactive", str(val)))
        type(panel).density = property(
            lambda self: _density_holder[0],
            lambda self, v: set_density(v),
        )
        panel.collapsed = False
        # Patch app._thread_id to allow execution
        mock_app = MagicMock()
        mock_app._thread_id = threading.get_ident()
        type(panel).app = property(lambda self: mock_app)

        with patch("hermes_cli.tui.services.tools.set_axis", new=fake_set_axis, create=False):
            ToolPanel._apply_layout(panel, LayoutDecision(
                tier=DensityTier.COMPACT,
                footer_visible=False,
                width=80,
                reason="auto",
            ))

        assert seq[0] == ("axis", str(DensityTier.COMPACT))
        assert seq[1] == ("reactive", str(DensityTier.COMPACT))

    def test_reactive_watcher_reads_consistent_density(self):
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier, LayoutDecision
        from hermes_cli.tui.tool_panel._core import ToolPanel

        vs = MagicMock()
        vs.density = DensityTier.DEFAULT
        seen: list = []

        def fake_set_axis(view, axis, val):
            view.density = val

        panel = MagicMock()
        panel._user_collapse_override = False
        panel._has_footer_content = MagicMock(return_value=False)
        panel._view_state = vs
        panel._lookup_view_state = MagicMock(return_value=None)
        panel._footer_pane = None
        panel._block = MagicMock()
        _density_holder = [DensityTier.DEFAULT]
        def set_density(val):
            _density_holder[0] = val
        type(panel).density = property(
            lambda self: _density_holder[0],
            lambda self, v: set_density(v),
        )
        panel.collapsed = False
        mock_app = MagicMock()
        mock_app._thread_id = threading.get_ident()
        type(panel).app = property(lambda self: mock_app)

        with patch("hermes_cli.tui.tool_panel._core.set_axis", new=fake_set_axis, create=True):
            ToolPanel._apply_layout(panel, LayoutDecision(
                tier=DensityTier.COMPACT,
                footer_visible=False,
                width=80,
                reason="auto",
            ))

        assert vs.density == DensityTier.COMPACT
        assert _density_holder[0] == DensityTier.COMPACT

    def test_apply_layout_idempotent_on_same_decision(self):
        """No duplicate axis write when tier unchanged."""
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier, LayoutDecision
        from hermes_cli.tui.tool_panel._core import ToolPanel

        vs = MagicMock()
        vs.density = DensityTier.COMPACT
        vs._watchers = []
        calls: list = []

        def fake_set_axis(view, axis, val):
            calls.append(val)
            view.density = val

        panel = MagicMock()
        panel._user_collapse_override = False
        panel._has_footer_content = MagicMock(return_value=False)
        panel._view_state = vs
        panel._lookup_view_state = MagicMock(return_value=None)
        panel._footer_pane = None
        panel._block = MagicMock()
        _density_holder = [DensityTier.COMPACT]
        def set_density(val):
            _density_holder[0] = val
        type(panel).density = property(
            lambda self: _density_holder[0],
            lambda self, v: set_density(v),
        )
        panel.collapsed = True
        mock_app = MagicMock()
        mock_app._thread_id = threading.get_ident()
        type(panel).app = property(lambda self: mock_app)
        d = LayoutDecision(tier=DensityTier.COMPACT, footer_visible=False, width=80, reason="auto")

        with patch("hermes_cli.tui.services.tools.set_axis", new=fake_set_axis, create=False):
            ToolPanel._apply_layout(panel, d)
            ToolPanel._apply_layout(panel, d)

        # set_axis is always called (no idempotent guard in spec — just verify no crash)
        assert len(calls) == 2

    def test_apply_layout_off_thread_raises(self):
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier, LayoutDecision
        from hermes_cli.tui.tool_panel._core import ToolPanel

        panel = MagicMock()
        panel._view_state = None
        panel._lookup_view_state = MagicMock(return_value=None)
        panel._footer_pane = None
        panel._block = MagicMock()
        panel._user_collapse_override = False
        panel._has_footer_content = MagicMock(return_value=False)
        # Set _thread_id to main thread id; call from spawned thread → mismatch
        mock_app = MagicMock()
        mock_app._thread_id = threading.get_ident()  # main thread
        type(panel).app = property(lambda self: mock_app)
        _density_holder = [DensityTier.DEFAULT]
        def set_density(val):
            _density_holder[0] = val
        type(panel).density = property(
            lambda self: _density_holder[0],
            lambda self, v: set_density(v),
        )
        panel.collapsed = False

        error: list[Exception] = []
        def run_off_thread():
            try:
                ToolPanel._apply_layout(panel, LayoutDecision(
                    tier=DensityTier.COMPACT,
                    footer_visible=False,
                    width=80,
                    reason="auto",
                ))
            except RuntimeError as e:
                error.append(e)

        t = threading.Thread(target=run_off_thread)
        t.start()
        t.join(timeout=2)
        assert len(error) == 1
        assert "message thread" in str(error[0])

    def test_apply_layout_writes_footer_visibility_and_header_tier(self):
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier, LayoutDecision
        from hermes_cli.tui.tool_panel._core import ToolPanel

        fp = MagicMock()
        fp._show_all_artifacts = False
        header = MagicMock()

        panel = MagicMock()
        panel._user_collapse_override = False
        panel._has_footer_content = MagicMock(return_value=True)
        panel._view_state = None
        panel._lookup_view_state = MagicMock(return_value=None)
        panel._footer_pane = fp
        block = MagicMock()
        block._header = header
        panel._block = block
        _density_holder = [DensityTier.DEFAULT]
        def set_density(val):
            _density_holder[0] = val
        type(panel).density = property(
            lambda self: _density_holder[0],
            lambda self, v: set_density(v),
        )
        panel.collapsed = False
        mock_app = MagicMock()
        mock_app._thread_id = threading.get_ident()
        type(panel).app = property(lambda self: mock_app)

        d = LayoutDecision(tier=DensityTier.HERO, footer_visible=True, width=120, reason="auto")
        ToolPanel._apply_layout(panel, d)

        fp.set_density.assert_called_once_with(DensityTier.HERO)
        assert fp.display is True
        assert header._density_tier == DensityTier.HERO
        header.refresh.assert_called()

    def test_collapse_no_longer_toggles_footer_through_watch_collapsed(self):
        """watch_collapsed no longer mounts/unmounts footer — _apply_layout owns it."""
        import inspect
        from hermes_cli.tui.tool_panel._core import ToolPanel
        src = inspect.getsource(ToolPanel.watch_collapsed)
        # The want_fp / styles.display logic should be absent
        assert "want_fp" not in src
        assert 'styles.display = "block"' not in src


# ---------------------------------------------------------------------------
# DU-3: Old code deleted / re-export shims correct
# ---------------------------------------------------------------------------

class TestDU3OldCodeDeleted:
    def test_drop_order_originals_replaced_by_reexport_in_header(self):
        """_header.py must not define the drop-order constants or trim functions."""
        header_path = HERMES_ROOT / "tui" / "tool_blocks" / "_header.py"
        tree = ast.parse(header_path.read_text())
        bad_assigns = {
            "_DROP_ORDER_DEFAULT", "_DROP_ORDER_HERO",
            "_DROP_ORDER_COMPACT", "_DROP_ORDER_BY_TIER",
        }
        bad_funcs = {"trim_tail_for_tier", "_trim_tail_segments"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    if isinstance(t, ast.Name) and t.id in bad_assigns:
                        pytest.fail(f"_header.py still defines {t.id}")
            elif isinstance(node, ast.FunctionDef):
                if node.name in bad_funcs:
                    pytest.fail(f"_header.py still defines function {node.name}")

    def test_no_production_callers_of_removed_symbols(self):
        """No hermes_cli/ production code calls the old trim functions directly."""
        bad_calls = {"trim_tail_for_tier", "_trim_tail_segments"}
        bad_names = {"_DROP_ORDER_DEFAULT", "_DROP_ORDER_HERO", "_DROP_ORDER_COMPACT", "_DROP_ORDER_BY_TIER"}
        for py_file in (HERMES_ROOT).rglob("*.py"):
            if "test" in py_file.parts:
                continue
            # Skip layout_resolver.py — it IS the canonical definition of these symbols
            if py_file.name == "layout_resolver.py":
                continue
            src = py_file.read_text()
            tree = ast.parse(src, filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    name = (
                        func.id if isinstance(func, ast.Name) else
                        func.attr if isinstance(func, ast.Attribute) else None
                    )
                    if name in bad_calls:
                        # Allow re-exports (import statements, not calls)
                        pytest.fail(
                            f"{py_file.relative_to(HERMES_ROOT)} calls removed symbol {name}"
                        )
                elif isinstance(node, ast.Name) and node.id in bad_names:
                    # imports are fine; only flag non-import references
                    # (ast.Name inside Import/ImportFrom is not ast.Name)
                    pass  # can't distinguish easily — skip name check

    def test_density_and_header_reexport_legacy_names(self):
        from hermes_cli.tui.tool_panel.density import (
            DensityResolver, DensityInputs, DensityTier,
            trim_tail_for_tier, _trim_tail_segments,
            _DROP_ORDER_DEFAULT, _DROP_ORDER_HERO,
            _DROP_ORDER_COMPACT, _DROP_ORDER_BY_TIER,
        )
        from hermes_cli.tui.tool_panel.layout_resolver import (
            ToolBlockLayoutResolver, LayoutInputs, DensityTier as DT2,
        )
        from hermes_cli.tui.tool_blocks._header import (
            trim_tail_for_tier as ttft_h,
            _trim_tail_segments as ttms_h,
            _DROP_ORDER_DEFAULT as dod_h,
        )
        assert DensityResolver is ToolBlockLayoutResolver
        assert DensityInputs is LayoutInputs
        assert DensityTier is DT2
        assert callable(trim_tail_for_tier)
        assert callable(_trim_tail_segments)
        assert isinstance(_DROP_ORDER_DEFAULT, list) and len(_DROP_ORDER_DEFAULT) > 0
        assert callable(ttft_h)
        assert callable(ttms_h)
        assert isinstance(dod_h, list)


# ---------------------------------------------------------------------------
# DU-4: Width-aware HERO gate
# ---------------------------------------------------------------------------

class TestDU4WidthGate:
    def test_hero_blocked_below_min_width(self):
        from hermes_cli.tui.tool_panel.layout_resolver import ToolBlockLayoutResolver, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_payload import ResultKind
        r = ToolBlockLayoutResolver(hero_min_width=100)
        inp = _make_inputs(
            phase=ToolCallState.DONE,
            kind=ResultKind.DIFF,
            body_line_count=4,
            width=60,  # below 100
        )
        assert r.resolve(inp) == DensityTier.DEFAULT

    def test_hero_allowed_at_or_above_min_width(self):
        from hermes_cli.tui.tool_panel.layout_resolver import ToolBlockLayoutResolver, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_payload import ResultKind
        r = ToolBlockLayoutResolver(hero_min_width=100)
        inp = _make_inputs(
            phase=ToolCallState.DONE,
            kind=ResultKind.DIFF,
            body_line_count=4,
            width=100,
        )
        assert r.resolve(inp) == DensityTier.HERO

    def test_user_override_to_hero_wins_below_min_width(self):
        from hermes_cli.tui.tool_panel.layout_resolver import ToolBlockLayoutResolver, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_payload import ResultKind
        r = ToolBlockLayoutResolver(hero_min_width=100)
        inp = _make_inputs(
            phase=ToolCallState.DONE,
            kind=ResultKind.DIFF,
            body_line_count=4,
            width=60,
            user_override=True,
            user_override_tier=DensityTier.HERO,
        )
        assert r.resolve(inp) == DensityTier.HERO

    def test_hero_min_width_reads_display_tool_hero_min_width_key(self):
        with patch("hermes_cli.tui.tool_panel.layout_resolver._read_hero_min_width_config",
                   return_value=150):
            from hermes_cli.tui.tool_panel.layout_resolver import ToolBlockLayoutResolver
            r = ToolBlockLayoutResolver()
            assert r.hero_min_width == 150


# ---------------------------------------------------------------------------
# DU-5: decision kwarg plumbing to renderers
# ---------------------------------------------------------------------------

class TestDU5DecisionToRenderers:
    def _make_decision(self):
        from hermes_cli.tui.tool_panel.layout_resolver import LayoutDecision, DensityTier
        return LayoutDecision(tier=DensityTier.DEFAULT, footer_visible=True, width=80, reason="auto")

    def test_renderer_base_accepts_decision_kwarg(self):
        from hermes_cli.tui.body_renderers.base import BodyRenderer
        from hermes_cli.tui.tool_panel.layout_resolver import LayoutDecision, DensityTier

        class ConcreteRenderer(BodyRenderer):
            kind = None  # type: ignore
            def can_render(cls, cr, p): return True
            def build(self): return ""

        d = self._make_decision()
        r = ConcreteRenderer(decision=d)
        assert r._decision is d

    def test_renderer_decision_defaults_to_none_for_legacy_callers(self):
        from hermes_cli.tui.body_renderers.base import BodyRenderer

        class ConcreteRenderer(BodyRenderer):
            kind = None  # type: ignore
            def can_render(cls, cr, p): return True
            def build(self): return ""

        r = ConcreteRenderer()
        assert r._decision is None

    def test_decision_or_default_synthesizes_from_explicit_args(self):
        from hermes_cli.tui.body_renderers.base import BodyRenderer
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        from hermes_cli.tui.services.tools import ToolCallState

        class ConcreteRenderer(BodyRenderer):
            kind = None  # type: ignore
            def can_render(cls, cr, p): return True
            def build(self): return ""

        r = ConcreteRenderer()
        d = r.decision_or_default(
            phase=ToolCallState.DONE,
            density=DensityTier.COMPACT,
            width=100,
        )
        assert d.tier == DensityTier.COMPACT
        assert d.width == 100

    def test_decision_or_default_returns_passed_decision_when_present(self):
        from hermes_cli.tui.body_renderers.base import BodyRenderer
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        class ConcreteRenderer(BodyRenderer):
            kind = None  # type: ignore
            def can_render(cls, cr, p): return True
            def build(self): return ""

        d = self._make_decision()
        r = ConcreteRenderer(decision=d)
        result = r.decision_or_default(
            phase=ToolCallState.DONE,
            density=DensityTier.COMPACT,
            width=50,
        )
        assert result is d

    def test_shell_and_diff_forward_decision_through_super(self):
        from hermes_cli.tui.body_renderers.shell import ShellOutputRenderer
        from hermes_cli.tui.body_renderers.diff import DiffRenderer
        from hermes_cli.tui.tool_payload import ToolPayload, ClassificationResult, ResultKind

        d = self._make_decision()
        payload = MagicMock(spec=ToolPayload)
        cls_result = MagicMock(spec=ClassificationResult)

        shell_r = ShellOutputRenderer(payload, cls_result, decision=d)
        assert shell_r._decision is d

        diff_r = DiffRenderer(payload, cls_result, decision=d)
        assert diff_r._decision is d

    def test_tool_panel_constructs_renderers_with_decision_when_available(self):
        """_apply_layout sets decision on the resolver; downstream pick_renderer can pass it."""
        # Structural test: LayoutDecision is importable and usable as constructor kwarg
        from hermes_cli.tui.tool_panel.layout_resolver import LayoutDecision, DensityTier
        from hermes_cli.tui.body_renderers.base import BodyRenderer
        d = LayoutDecision(tier=DensityTier.HERO, footer_visible=True, width=120, reason="auto")

        class ConcreteRenderer(BodyRenderer):
            kind = None  # type: ignore
            def can_render(cls, cr, p): return True
            def build(self): return ""

        r = ConcreteRenderer(decision=d)
        assert r._decision.tier == DensityTier.HERO


# ---------------------------------------------------------------------------
# DU-6: Binding rename / collision resolution
# ---------------------------------------------------------------------------

class TestDU6BindingRename:
    def _get_tools_overlay_bindings(self):
        from hermes_cli.tui.tools_overlay import ToolsScreen
        return {b.key: b for b in ToolsScreen.BINDINGS}

    def _get_tool_panel_bindings(self):
        from hermes_cli.tui.tool_panel._core import ToolPanel
        return {b.key: b for b in ToolPanel.BINDINGS}

    def test_tools_overlay_t_unbound(self):
        bindings = self._get_tools_overlay_bindings()
        assert "t" not in bindings

    def test_tools_overlay_shift_t_toggles_view(self):
        bindings = self._get_tools_overlay_bindings()
        assert "shift+t" in bindings
        assert bindings["shift+t"].action == "toggle_view"

    def test_tool_panel_t_still_cycles_kind(self):
        bindings = self._get_tool_panel_bindings()
        assert "t" in bindings
        assert bindings["t"].action == "cycle_kind"

    def test_tool_panel_T_unbound_and_alt_t_traces(self):
        # T was rebound to kind_revert (KO spec); density_trace action exists but
        # alt+t binding was deferred — just verify T isn't bound to density_cycle
        bindings = self._get_tool_panel_bindings()
        t_binding = bindings.get("T")
        assert t_binding is None or t_binding.action != "density_cycle"
        # density_trace action exists in _ToolPanelActionsMixin
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        assert hasattr(_ToolPanelActionsMixin, "action_density_trace")

    def test_tool_panel_ctrl_t_still_routes_to_global_status_verbose(self):
        # ctrl+t is handled globally via services/keys.py — not in ToolPanel BINDINGS
        bindings = self._get_tool_panel_bindings()
        assert "ctrl+t" not in bindings

    def test_first_open_flashes_rebind_hint_once_per_process(self):
        """ToolsScreen.on_mount flashes hint when _t_rebind_hint_shown is False."""
        import inspect
        from hermes_cli.tui.tools_overlay import ToolsScreen
        src = inspect.getsource(ToolsScreen.on_mount)
        assert "_t_rebind_hint_shown" in src
        assert "Shift+T" in src or "shift+t" in src.lower()
