"""KO-1..KO-4: User KIND override on tool blocks.

17 tests across:
- TestViewStateField (KO-1, 1 test)
- TestPickRendererOverride (KO-2, 4 tests)
- TestSwapRendererOverride (KO-3, 5 tests)
- TestActionCycleKind (KO-4, 7 tests)
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.tool_payload import (
    ClassificationResult,
    ResultKind,
    ToolPayload,
)
from hermes_cli.tui.tool_category import ToolCategory
from hermes_cli.tui.tool_panel.density import DensityTier
from hermes_cli.tui.services.tools import ToolCallState, ToolCallViewState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _payload(category: object = None, output_raw: str = "out") -> ToolPayload:
    if category is None:
        category = ToolCategory.FILE
    return ToolPayload(
        tool_name="bash",
        category=category,
        args={},
        input_display=None,
        output_raw=output_raw,
        line_count=1,
    )


def _cls(kind: ResultKind, confidence: float = 0.9) -> ClassificationResult:
    return ClassificationResult(kind, confidence)


def _attach_view_stub(panel, *, state: ToolCallState = ToolCallState.DONE,
                      override: "ResultKind | None" = None,
                      stamped_kind: "ClassificationResult | None" = None) -> None:
    panel._view_state = SimpleNamespace(
        state=state,
        kind=stamped_kind,
        density=DensityTier.DEFAULT,
        user_kind_override=override,
    )


def _make_panel(tool_name: str = "bash"):
    from hermes_cli.tui.tool_panel import ToolPanel
    block_mock = MagicMock()
    block_mock._total_received = 0
    block_mock._all_plain = ["line"]
    panel = ToolPanel(block=block_mock, tool_name=tool_name)
    panel._header_bar = None
    panel._body_pane = None
    panel._tool_args = {}
    return panel


# ---------------------------------------------------------------------------
# KO-1: TestViewStateField
# ---------------------------------------------------------------------------

class TestViewStateField:

    def test_view_state_user_kind_override_defaults_none(self):
        view = ToolCallViewState(
            tool_call_id="tc1",
            gen_index=0,
            tool_name="bash",
            label="bash",
            args={},
            state=ToolCallState.GENERATED,
            block=None,
            panel=None,
            parent_tool_call_id=None,
            category="shell",
            depth=0,
            start_s=0.0,
        )
        assert view.user_kind_override is None


# ---------------------------------------------------------------------------
# KO-2: TestPickRendererOverride
# ---------------------------------------------------------------------------

class TestPickRendererOverride:

    def test_pick_renderer_override_replaces_kind(self):
        from hermes_cli.tui.body_renderers import pick_renderer, CodeRenderer

        result = pick_renderer(
            _cls(ResultKind.TEXT, 1.0), _payload(),
            phase=ToolCallState.DONE, density=DensityTier.DEFAULT,
            user_kind_override=ResultKind.CODE,
        )
        assert result is CodeRenderer

    def test_pick_renderer_override_text_returns_fallback(self):
        from hermes_cli.tui.body_renderers import pick_renderer, FallbackRenderer

        result = pick_renderer(
            _cls(ResultKind.JSON, 0.9), _payload(),
            phase=ToolCallState.DONE, density=DensityTier.DEFAULT,
            user_kind_override=ResultKind.TEXT,
        )
        assert result is FallbackRenderer

    def test_pick_renderer_override_beats_shell_rule(self):
        from hermes_cli.tui.body_renderers import pick_renderer, CodeRenderer

        result = pick_renderer(
            _cls(ResultKind.TEXT, 1.0),
            _payload(category=ToolCategory.SHELL, output_raw="echo hi"),
            phase=ToolCallState.DONE, density=DensityTier.DEFAULT,
            user_kind_override=ResultKind.CODE,
        )
        assert result is CodeRenderer

    def test_pick_renderer_override_ignored_in_streaming(self):
        from hermes_cli.tui.body_renderers import pick_renderer, CodeRenderer

        result = pick_renderer(
            _cls(ResultKind.TEXT, 0.0), _payload(),
            phase=ToolCallState.STREAMING, density=DensityTier.DEFAULT,
            user_kind_override=ResultKind.CODE,
        )
        assert result is not CodeRenderer


# ---------------------------------------------------------------------------
# KO-3: TestSwapRendererOverride
# ---------------------------------------------------------------------------

def _make_completion_stub(*, view_state=None, category=ToolCategory.FILE):
    from hermes_cli.tui.tool_panel._completion import _ToolPanelCompletionMixin

    class _Stub(_ToolPanelCompletionMixin):
        _block = None
        _body_pane = None
        _tool_name = "test_tool"
        _tool_args = {}
        _view_state = None

        def __init__(self):
            self._view_state = view_state
            self._category = category
            self._swapped: list = []

        def _lookup_view_state(self):
            return None

        def remove_class(self, _cls_name):
            pass

        def _swap_renderer(self, renderer_cls, payload, cls_result):
            self._swapped.append(renderer_cls)

    return _Stub()


class TestSwapRendererOverride:

    def test_maybe_swap_renderer_threads_override(self):
        from hermes_cli.tui.body_renderers import CodeRenderer

        view = SimpleNamespace(
            state=ToolCallState.DONE,
            kind=None,
            density=DensityTier.DEFAULT,
            user_kind_override=ResultKind.CODE,
        )
        stub = _make_completion_stub(view_state=view)
        stub._maybe_swap_renderer(_cls(ResultKind.TEXT, 1.0), _payload())
        assert stub._swapped == [CodeRenderer]

    def test_maybe_swap_renderer_override_on_shell_swaps(self):
        from hermes_cli.tui.body_renderers import CodeRenderer

        view = SimpleNamespace(
            state=ToolCallState.DONE,
            kind=None,
            density=DensityTier.DEFAULT,
            user_kind_override=ResultKind.CODE,
        )
        stub = _make_completion_stub(view_state=view, category=ToolCategory.SHELL)
        stub._maybe_swap_renderer(
            _cls(ResultKind.TEXT, 1.0),
            _payload(category=ToolCategory.SHELL),
        )
        assert stub._swapped == [CodeRenderer]

    def test_maybe_swap_renderer_override_text_swaps_to_fallback(self):
        from hermes_cli.tui.body_renderers import FallbackRenderer

        view = SimpleNamespace(
            state=ToolCallState.DONE,
            kind=None,
            density=DensityTier.DEFAULT,
            user_kind_override=ResultKind.TEXT,
        )
        stub = _make_completion_stub(view_state=view)
        stub._maybe_swap_renderer(_cls(ResultKind.JSON, 0.9), _payload())
        assert stub._swapped == [FallbackRenderer]

    def test_maybe_swap_renderer_view_none_falls_through(self):
        # No view_state, no override → existing TEXT/EMPTY/SHELL early-returns fire.
        stub = _make_completion_stub(view_state=None)
        stub._maybe_swap_renderer(_cls(ResultKind.TEXT, 1.0), _payload())
        assert stub._swapped == []  # early-returned on TEXT, no swap

    def test_maybe_swap_renderer_override_persists_across_reswaps(self):
        from hermes_cli.tui.body_renderers import CodeRenderer

        view = SimpleNamespace(
            state=ToolCallState.DONE,
            kind=None,
            density=DensityTier.DEFAULT,
            user_kind_override=ResultKind.CODE,
        )
        stub = _make_completion_stub(view_state=view)
        stub._maybe_swap_renderer(_cls(ResultKind.TEXT, 1.0), _payload())
        stub._maybe_swap_renderer(_cls(ResultKind.TEXT, 1.0), _payload())
        assert stub._swapped == [CodeRenderer, CodeRenderer]


# ---------------------------------------------------------------------------
# KO-4: TestActionCycleKind
# ---------------------------------------------------------------------------

class TestActionCycleKind:

    def test_action_cycle_kind_advances_override(self):
        panel = _make_panel()
        _attach_view_stub(panel)

        with patch.object(panel, "_swap_renderer"):
            panel.action_cycle_kind()
        assert panel._view_state.user_kind_override == ResultKind.CODE

        # Cycle 6 more times to wrap to None (7-stop cycle: None+6 kinds).
        # Reset debounce timestamp before each call to bypass 150ms window.
        with patch.object(panel, "_swap_renderer"):
            for _ in range(6):
                panel._cycle_kind_last_fired = 0.0
                panel.action_cycle_kind()
        assert panel._view_state.user_kind_override is None

    @pytest.mark.parametrize("state", [
        ToolCallState.GENERATED,
        ToolCallState.STARTED,
        ToolCallState.STREAMING,
        ToolCallState.REMOVED,
    ])
    def test_action_cycle_kind_streaming_noop(self, state):
        panel = _make_panel()
        _attach_view_stub(panel, state=state)

        with patch.object(panel, "_swap_renderer") as swap:
            panel.action_cycle_kind()
        assert panel._view_state.user_kind_override is None
        swap.assert_not_called()

    def test_action_cycle_kind_generated_noop(self):
        panel = _make_panel()
        _attach_view_stub(panel, state=ToolCallState.GENERATED)
        with patch.object(panel, "_swap_renderer") as swap:
            panel.action_cycle_kind()
        swap.assert_not_called()
        assert panel._view_state.user_kind_override is None

    def test_action_cycle_kind_triggers_swap(self):
        from hermes_cli.tui.body_renderers import CodeRenderer

        panel = _make_panel()
        _attach_view_stub(panel)
        with patch.object(panel, "_swap_renderer") as swap:
            panel.action_cycle_kind()
        assert swap.called
        # First positional arg = renderer class.
        renderer_cls = swap.call_args[0][0]
        assert renderer_cls is CodeRenderer

    def test_force_renderer_writes_view_state(self):
        from hermes_cli.tui.body_renderers import JsonRenderer

        panel = _make_panel()
        _attach_view_stub(panel)
        with patch.object(panel, "_swap_renderer") as swap:
            panel.force_renderer(ResultKind.JSON)
        assert panel._view_state.user_kind_override == ResultKind.JSON
        renderer_cls = swap.call_args[0][0]
        assert renderer_cls is JsonRenderer

    def test_force_renderer_none_clears_override(self):
        panel = _make_panel()
        _attach_view_stub(panel, override=ResultKind.CODE)
        with patch.object(panel, "_swap_renderer") as swap:
            panel.force_renderer(None)
        assert panel._view_state.user_kind_override is None
        assert swap.called  # active entry-point: replays swap unconditionally

    def test_action_cycle_kind_snaps_to_none_for_off_cycle_value(self):
        panel = _make_panel()
        _attach_view_stub(panel, override=ResultKind.EMPTY)
        with patch.object(panel, "_swap_renderer"):
            panel.action_cycle_kind()
        # idx=-1 + 1 → 0 → cycle[0] is None
        assert panel._view_state.user_kind_override is None
