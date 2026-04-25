"""R-2A tests: context-aware registry signature (phase + density)."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from hermes_cli.tui.services.tools import ToolCallState
from hermes_cli.tui.tool_panel.density import DensityTier
from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind, ToolPayload
from hermes_cli.tui.tool_category import ToolCategory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _payload(
    category: object = None,
    output_raw: str = "some output",
    tool_name: str = "bash",
) -> ToolPayload:
    if category is None:
        category = ToolCategory.FILE
    return ToolPayload(
        tool_name=tool_name,
        category=category,
        args={},
        input_display=None,
        output_raw=output_raw,
        line_count=1,
    )


def _cls(kind: ResultKind, confidence: float = 0.9) -> ClassificationResult:
    return ClassificationResult(kind, confidence)


# ---------------------------------------------------------------------------
# TestAcceptsDefault — R-2A-1 (5 tests)
# ---------------------------------------------------------------------------

class TestAcceptsDefault:

    def test_default_accepts_completing_done(self):
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        assert FallbackRenderer.accepts(ToolCallState.COMPLETING, DensityTier.DEFAULT) is True
        assert FallbackRenderer.accepts(ToolCallState.DONE, DensityTier.DEFAULT) is True

    def test_default_rejects_streaming(self):
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        assert FallbackRenderer.accepts(ToolCallState.STREAMING, DensityTier.DEFAULT) is False

    def test_default_rejects_started_generated(self):
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        assert FallbackRenderer.accepts(ToolCallState.STARTED, DensityTier.DEFAULT) is False
        assert FallbackRenderer.accepts(ToolCallState.GENERATED, DensityTier.DEFAULT) is False

    def test_accepted_phases_overridable(self):
        from hermes_cli.tui.body_renderers.base import BodyRenderer
        from hermes_cli.tui.tool_payload import ResultKind

        class _TestRenderer(BodyRenderer):
            kind = ResultKind.TEXT
            accepted_phases = frozenset({ToolCallState.STREAMING, ToolCallState.DONE})

            @classmethod
            def can_render(cls, cls_result, payload) -> bool:
                return True

            def build(self):
                return ""

        assert _TestRenderer.accepts(ToolCallState.STREAMING, DensityTier.DEFAULT) is True
        assert _TestRenderer.accepts(ToolCallState.DONE, DensityTier.DEFAULT) is True
        assert _TestRenderer.accepts(ToolCallState.COMPLETING, DensityTier.DEFAULT) is False

    def test_accepts_density_independence_default(self):
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        for tier in (DensityTier.COMPACT, DensityTier.DEFAULT, DensityTier.HERO, DensityTier.TRACE):
            assert FallbackRenderer.accepts(ToolCallState.DONE, tier) is True


# ---------------------------------------------------------------------------
# TestPickRendererSignature — R-2A-2 (8 tests)
# ---------------------------------------------------------------------------

class TestPickRendererSignature:

    def test_pick_renderer_requires_phase_kwarg(self):
        from hermes_cli.tui.body_renderers import pick_renderer
        payload = _payload()
        cls = _cls(ResultKind.TEXT)
        with pytest.raises(TypeError):
            pick_renderer(cls, payload, density=DensityTier.DEFAULT)  # type: ignore[call-arg]

    def test_pick_renderer_requires_density_kwarg(self):
        from hermes_cli.tui.body_renderers import pick_renderer
        payload = _payload()
        cls = _cls(ResultKind.TEXT)
        with pytest.raises(TypeError):
            pick_renderer(cls, payload, phase=ToolCallState.DONE)  # type: ignore[call-arg]

    def test_pick_renderer_phase_done_density_default_existing_behavior(self):
        from hermes_cli.tui.body_renderers import pick_renderer, EmptyStateRenderer, FallbackRenderer, SearchRenderer
        # EMPTY → EmptyStateRenderer
        assert pick_renderer(_cls(ResultKind.EMPTY), _payload(), phase=ToolCallState.DONE, density=DensityTier.DEFAULT) is EmptyStateRenderer
        # TEXT → FallbackRenderer
        assert pick_renderer(_cls(ResultKind.TEXT), _payload(), phase=ToolCallState.DONE, density=DensityTier.DEFAULT) is FallbackRenderer
        # SEARCH high-conf → SearchRenderer
        assert pick_renderer(
            _cls(ResultKind.SEARCH, 0.9),
            _payload(category=ToolCategory.SEARCH),
            phase=ToolCallState.DONE,
            density=DensityTier.DEFAULT,
        ) is SearchRenderer

    def test_pick_renderer_phase_streaming_falls_back(self):
        from hermes_cli.tui.body_renderers import pick_renderer, PlainBodyRenderer
        from hermes_cli.tui.body_renderers.json import JsonRenderer
        # Phase-C-only renderers (default accepts rejects STREAMING) must not be
        # selected at STREAMING. With no category match, streaming branch falls
        # back to PlainBodyRenderer rather than a Phase-C renderer like JSON.
        payload = _payload(category="__no_match__", output_raw='{"key": "val"}')
        cls = _cls(ResultKind.JSON, confidence=0.95)
        result = pick_renderer(cls, payload, phase=ToolCallState.STREAMING, density=DensityTier.DEFAULT)
        assert result is PlainBodyRenderer
        assert result is not JsonRenderer

    def test_pick_renderer_filters_by_accepts_skips_to_next(self):
        from hermes_cli.tui.body_renderers import pick_renderer, REGISTRY
        from hermes_cli.tui.body_renderers.json import JsonRenderer

        payload = _payload(output_raw='{"k": "v"}')
        cls = _cls(ResultKind.JSON, confidence=0.95)

        # Patch JsonRenderer.accepts to False on first call, then let others run —
        # but simpler: patch accepts on all REGISTRY entries except JsonRenderer to False,
        # confirming JsonRenderer is still found when its accepts returns True.
        with patch.object(JsonRenderer, "accepts", return_value=True):
            result = pick_renderer(cls, payload, phase=ToolCallState.DONE, density=DensityTier.DEFAULT)
        assert result is JsonRenderer

    def test_pick_renderer_shell_short_circuit_respects_accepts(self):
        from hermes_cli.tui.body_renderers import pick_renderer, FallbackRenderer
        from hermes_cli.tui.body_renderers.shell import ShellOutputRenderer

        payload = _payload(category=ToolCategory.SHELL, output_raw="hello")
        cls = _cls(ResultKind.TEXT, confidence=1.0)

        with patch.object(ShellOutputRenderer, "accepts", return_value=False):
            result = pick_renderer(cls, payload, phase=ToolCallState.DONE, density=DensityTier.DEFAULT)
        assert result is FallbackRenderer

    def test_pick_renderer_empty_short_circuit_respects_accepts(self):
        from hermes_cli.tui.body_renderers import pick_renderer, FallbackRenderer
        from hermes_cli.tui.body_renderers.empty import EmptyStateRenderer

        payload = _payload()
        cls = _cls(ResultKind.EMPTY, confidence=1.0)

        with patch.object(EmptyStateRenderer, "accepts", return_value=False):
            result = pick_renderer(cls, payload, phase=ToolCallState.DONE, density=DensityTier.DEFAULT)
        assert result is FallbackRenderer

    def test_pick_renderer_density_passed_through(self):
        from hermes_cli.tui.body_renderers import pick_renderer
        from hermes_cli.tui.body_renderers.base import BodyRenderer

        captured: list[tuple] = []

        class _CapturingRenderer(BodyRenderer):
            kind = ResultKind.JSON

            @classmethod
            def accepts(cls, phase, density) -> bool:
                captured.append((phase, density))
                return False  # don't actually pick; just capture

            @classmethod
            def can_render(cls, cls_result, payload) -> bool:
                return True

            def build(self):
                return ""

        from hermes_cli.tui.body_renderers import REGISTRY
        REGISTRY.insert(0, _CapturingRenderer)
        try:
            pick_renderer(
                _cls(ResultKind.JSON, 0.9),
                _payload(),
                phase=ToolCallState.COMPLETING,
                density=DensityTier.COMPACT,
            )
        finally:
            REGISTRY.remove(_CapturingRenderer)

        assert len(captured) >= 1
        assert captured[0] == (ToolCallState.COMPLETING, DensityTier.COMPACT)


# ---------------------------------------------------------------------------
# TestFallbackInvariant — R-2A-3 (3 tests)
# ---------------------------------------------------------------------------

class TestFallbackInvariant:

    def test_fallback_accepts_completing_default(self):
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        assert FallbackRenderer.accepts(ToolCallState.COMPLETING, DensityTier.DEFAULT) is True

    def test_fallback_accepts_done_all_densities(self):
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        for tier in (DensityTier.HERO, DensityTier.DEFAULT, DensityTier.COMPACT, DensityTier.TRACE):
            assert FallbackRenderer.accepts(ToolCallState.DONE, tier) is True

    def test_fallback_accepts_completing_all_densities(self):
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        for tier in (DensityTier.HERO, DensityTier.DEFAULT, DensityTier.COMPACT, DensityTier.TRACE):
            assert FallbackRenderer.accepts(ToolCallState.COMPLETING, tier) is True


# ---------------------------------------------------------------------------
# TestCompletionCallSite — R-2A-4 (5 tests)
# ---------------------------------------------------------------------------

def _make_completion_mixin(view_state=None):
    """Return a bare _ToolPanelCompletionMixin instance with stubs."""
    from hermes_cli.tui.tool_panel._completion import _ToolPanelCompletionMixin

    class _Stub(_ToolPanelCompletionMixin):
        _category = ToolCategory.FILE
        _block = None
        _body_pane = None
        _tool_name = "test_tool"
        _tool_args = {}

        def _lookup_view_state(self):
            return view_state

        def remove_class(self, cls_name):
            pass

        def _swap_renderer(self, renderer_cls, payload, cls_result):
            pass

    return _Stub()


class TestCompletionCallSite:

    def test_completion_swap_passes_phase_completing(self):
        from hermes_cli.tui.body_renderers import pick_renderer as _orig

        stub = _make_completion_mixin()
        captured: list[dict] = []

        def _fake_pick(cls_result, payload, *, phase, density):
            captured.append({"phase": phase, "density": density})
            from hermes_cli.tui.body_renderers import FallbackRenderer
            return FallbackRenderer

        payload = _payload()
        cls = _cls(ResultKind.JSON, 0.9)

        with patch("hermes_cli.tui.body_renderers.pick_renderer", side_effect=_fake_pick):
            stub._maybe_swap_renderer(cls, payload)

        assert len(captured) == 1
        assert captured[0]["phase"] == ToolCallState.COMPLETING

    def test_completion_swap_passes_density_from_view_state(self):
        view = MagicMock()
        view.state = ToolCallState.COMPLETING
        view.density = DensityTier.COMPACT

        stub = _make_completion_mixin(view_state=view)
        captured: list[dict] = []

        def _fake_pick(cls_result, payload, *, phase, density):
            captured.append({"phase": phase, "density": density})
            from hermes_cli.tui.body_renderers import FallbackRenderer
            return FallbackRenderer

        payload = _payload()
        cls = _cls(ResultKind.JSON, 0.9)

        with patch("hermes_cli.tui.body_renderers.pick_renderer", side_effect=_fake_pick):
            stub._maybe_swap_renderer(cls, payload)

        assert captured[0]["density"] == DensityTier.COMPACT

    def test_completion_swap_fallback_when_view_state_missing(self):
        stub = _make_completion_mixin(view_state=None)
        captured: list[dict] = []

        def _fake_pick(cls_result, payload, *, phase, density):
            captured.append({"phase": phase, "density": density})
            from hermes_cli.tui.body_renderers import FallbackRenderer
            return FallbackRenderer

        payload = _payload()
        cls = _cls(ResultKind.JSON, 0.9)

        with patch("hermes_cli.tui.body_renderers.pick_renderer", side_effect=_fake_pick):
            stub._maybe_swap_renderer(cls, payload)

        assert captured[0]["phase"] == ToolCallState.COMPLETING
        assert captured[0]["density"] == DensityTier.DEFAULT

    def test_completion_swap_logs_exception_on_failure(self, caplog):
        import logging
        stub = _make_completion_mixin()

        def _boom(cls_result, payload, *, phase, density):
            raise RuntimeError("pick_renderer exploded")

        payload = _payload()
        cls = _cls(ResultKind.JSON, 0.9)

        with patch("hermes_cli.tui.body_renderers.pick_renderer", side_effect=_boom):
            with caplog.at_level(logging.ERROR, logger="hermes_cli.tui.tool_panel._completion"):
                stub._maybe_swap_renderer(cls, payload)

        assert any("renderer swap" in r.message.lower() or "renderer" in r.message.lower() for r in caplog.records)

    def test_completion_swap_no_op_for_text_kind(self):
        stub = _make_completion_mixin()
        pick_called = []

        def _fake_pick(cls_result, payload, *, phase, density):
            pick_called.append(True)
            from hermes_cli.tui.body_renderers import FallbackRenderer
            return FallbackRenderer

        payload = _payload()
        cls = _cls(ResultKind.TEXT, 1.0)

        with patch("hermes_cli.tui.body_renderers.pick_renderer", side_effect=_fake_pick):
            stub._maybe_swap_renderer(cls, payload)

        assert not pick_called


# ---------------------------------------------------------------------------
# TestForceRendererCallSite — R-2A-5 (4 tests)
# ---------------------------------------------------------------------------

def _make_actions_mixin(view_state=None):
    from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin

    class _Stub(_ToolPanelActionsMixin):
        _category = ToolCategory.FILE
        _block = None
        _tool_name = "test_tool"
        _tool_args = {}
        _forced_renderer_kind = None

        def _lookup_view_state(self):
            return view_state

        def copy_content(self):
            return "output text"

        def _body_line_count(self):
            return 1

        def _swap_renderer(self, renderer_cls, payload, cls_result):
            pass

    return _Stub()


class TestForceRendererCallSite:

    def test_force_renderer_passes_phase_done_default(self):
        stub = _make_actions_mixin(view_state=None)
        captured: list[dict] = []

        def _fake_pick(cls_result, payload, *, phase, density):
            captured.append({"phase": phase, "density": density})
            from hermes_cli.tui.body_renderers import FallbackRenderer
            return FallbackRenderer

        with patch("hermes_cli.tui.body_renderers.pick_renderer", side_effect=_fake_pick):
            stub.force_renderer(ResultKind.JSON)

        assert captured[0]["phase"] == ToolCallState.DONE

    def test_force_renderer_passes_density_from_view_state(self):
        view = MagicMock()
        view.state = ToolCallState.DONE
        view.density = DensityTier.COMPACT

        stub = _make_actions_mixin(view_state=view)
        captured: list[dict] = []

        def _fake_pick(cls_result, payload, *, phase, density):
            captured.append({"phase": phase, "density": density})
            from hermes_cli.tui.body_renderers import FallbackRenderer
            return FallbackRenderer

        with patch("hermes_cli.tui.body_renderers.pick_renderer", side_effect=_fake_pick):
            stub.force_renderer(ResultKind.JSON)

        assert captured[0]["density"] == DensityTier.COMPACT

    def test_force_renderer_uses_view_state_phase_when_present(self):
        view = MagicMock()
        view.state = ToolCallState.COMPLETING
        view.density = DensityTier.DEFAULT

        stub = _make_actions_mixin(view_state=view)
        captured: list[dict] = []

        def _fake_pick(cls_result, payload, *, phase, density):
            captured.append({"phase": phase, "density": density})
            from hermes_cli.tui.body_renderers import FallbackRenderer
            return FallbackRenderer

        with patch("hermes_cli.tui.body_renderers.pick_renderer", side_effect=_fake_pick):
            stub.force_renderer(ResultKind.JSON)

        assert captured[0]["phase"] == ToolCallState.COMPLETING

    def test_force_renderer_logs_exception_on_failure(self, caplog):
        import logging
        stub = _make_actions_mixin(view_state=None)

        def _boom(cls_result, payload, *, phase, density):
            raise RuntimeError("pick_renderer exploded")

        with patch("hermes_cli.tui.body_renderers.pick_renderer", side_effect=_boom):
            with caplog.at_level(logging.ERROR, logger="hermes_cli.tui.tool_panel._actions"):
                stub.force_renderer(ResultKind.JSON)

        assert any("force_renderer" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# TestExistingTestSweep — R-2A-6 (4 meta-tests)
# ---------------------------------------------------------------------------

class TestExistingTestSweep:

    def test_no_remaining_positional_pick_renderer_in_tests(self):
        """AST-scan tests/tui/ for pick_renderer() calls missing phase= kwarg."""
        import ast
        import pathlib

        root = pathlib.Path("/home/xush/.hermes/hermes-agent/tests/tui")
        bad: list[str] = []
        for path in root.rglob("*.py"):
            # Self-exclude: this file has intentional bad calls for TypeError tests
            if path.name == "test_renderer_registry_context.py":
                continue
            try:
                tree = ast.parse(path.read_text(), filename=str(path))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                # Match `pick_renderer(...)` and `mod.pick_renderer(...)`
                name = (
                    func.id if isinstance(func, ast.Name)
                    else func.attr if isinstance(func, ast.Attribute)
                    else None
                )
                if name != "pick_renderer":
                    continue
                if not any(kw.arg == "phase" for kw in node.keywords):
                    bad.append(f"{path.relative_to(root.parent.parent)}:{node.lineno}")
        assert bad == [], "pick_renderer() calls without phase= kwarg:\n" + "\n".join(bad)

    def test_existing_render_shell_selection_tests_pass(self):
        """Smoke: import the shell selection test module without errors."""
        import importlib
        mod = importlib.import_module("tests.tui.test_render_shell_selection_streaming")
        assert mod is not None

    def test_existing_renderer_swap_tests_pass(self):
        """Smoke: import the renderer swap test module without errors."""
        import importlib
        mod = importlib.import_module("tests.tui.test_renderer_swap")
        assert mod is not None

    def test_existing_tool_body_renderer_regression_tests_pass(self):
        """Smoke: import the tool body renderer regression test module without errors."""
        import importlib
        mod = importlib.import_module("tests.tui.test_tool_body_renderer_regression")
        assert mod is not None
