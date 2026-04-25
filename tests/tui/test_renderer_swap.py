"""Tests for renderer registry pick_renderer and ToolPanel._swap_renderer (8 tests)."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind, ToolPayload
from hermes_cli.tui.tool_category import ToolCategory


def _payload(
    output_raw: str = "some output",
    tool_name: str = "bash",
    category: object = None,
) -> ToolPayload:
    if category is None:
        category = ToolCategory.SHELL
    return ToolPayload(
        tool_name=tool_name,
        category=category,
        args={},
        input_display=None,
        output_raw=output_raw,
        line_count=0,
    )


def _cls(kind: ResultKind, confidence: float = 0.9) -> ClassificationResult:
    return ClassificationResult(kind, confidence)


def _make_app():
    from hermes_cli.tui.app import HermesApp
    return HermesApp(cli=MagicMock())


async def _pause(pilot, n: int = 3) -> None:
    for _ in range(n):
        await pilot.pause()


# ---------------------------------------------------------------------------
# pick_renderer tests (no app needed)
# ---------------------------------------------------------------------------

def test_pick_renderer_empty_always_empty_state():
    """EMPTY kind always returns EmptyStateRenderer."""
    from hermes_cli.tui.body_renderers import pick_renderer, EmptyStateRenderer
    from hermes_cli.tui.services.tools import ToolCallState
    from hermes_cli.tui.tool_panel.density import DensityTier
    payload = _payload(category=ToolCategory.FILE)
    cls_result = _cls(ResultKind.EMPTY, confidence=1.0)
    result = pick_renderer(cls_result, payload, phase=ToolCallState.DONE, density=DensityTier.DEFAULT)
    assert result is EmptyStateRenderer


def test_pick_renderer_search_high_confidence():
    """SEARCH kind with high confidence returns SearchRenderer."""
    from hermes_cli.tui.body_renderers import pick_renderer, SearchRenderer
    from hermes_cli.tui.services.tools import ToolCallState
    from hermes_cli.tui.tool_panel.density import DensityTier
    payload = _payload(category=ToolCategory.SEARCH)
    cls_result = _cls(ResultKind.SEARCH, confidence=0.85)
    result = pick_renderer(cls_result, payload, phase=ToolCallState.DONE, density=DensityTier.DEFAULT)
    assert result is SearchRenderer


def test_pick_renderer_low_confidence_fallback():
    """Low confidence (≤ 0.7) returns FallbackRenderer for non-SHELL."""
    from hermes_cli.tui.body_renderers import pick_renderer, FallbackRenderer
    from hermes_cli.tui.services.tools import ToolCallState
    from hermes_cli.tui.tool_panel.density import DensityTier
    payload = _payload(category=ToolCategory.FILE)
    cls_result = _cls(ResultKind.JSON, confidence=0.5)
    result = pick_renderer(cls_result, payload, phase=ToolCallState.DONE, density=DensityTier.DEFAULT)
    assert result is FallbackRenderer


def test_pick_renderer_text_fallback():
    """TEXT kind always falls through to FallbackRenderer."""
    from hermes_cli.tui.body_renderers import pick_renderer, FallbackRenderer
    from hermes_cli.tui.services.tools import ToolCallState
    from hermes_cli.tui.tool_panel.density import DensityTier
    payload = _payload(category=ToolCategory.UNKNOWN)
    cls_result = _cls(ResultKind.TEXT, confidence=1.0)
    result = pick_renderer(cls_result, payload, phase=ToolCallState.DONE, density=DensityTier.DEFAULT)
    assert result is FallbackRenderer


# ---------------------------------------------------------------------------
# _swap_renderer tests using the full app (via mount_tool_block pattern)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_swap_renderer_mounts_new_widget():
    """_swap_renderer mounts a new widget into BodyPane."""
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.widgets import OutputPanel

    app = _make_app()
    async with app.run_test(size=(100, 40)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        # Use the public API to mount a tool block
        app.mount_tool_block(
            "bash", ["output line"], ["output line"], tool_name="bash"
        )
        await _pause(pilot, 5)

        output = app.query_one(OutputPanel)
        panel = output.query_one(ToolPanel)

        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer

        payload = ToolPayload(
            tool_name="bash",
            category=ToolCategory.SHELL,
            args={},
            input_display=None,
            output_raw="plain text",
            line_count=1,
        )
        cls_result = ClassificationResult(ResultKind.TEXT, 1.0)
        # _swap_renderer should not raise
        panel._swap_renderer(FallbackRenderer, payload, cls_result)
        await _pause(pilot, 2)


@pytest.mark.asyncio
async def test_swap_renderer_keeps_original_block():
    """_swap_renderer keeps original ToolBlock/StreamingToolBlock mounted after swap."""
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.widgets import OutputPanel

    app = _make_app()
    async with app.run_test(size=(100, 40)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        app.mount_tool_block(
            "bash", ["output line"], ["output line"], tool_name="bash"
        )
        await _pause(pilot, 5)

        output = app.query_one(OutputPanel)
        panel = output.query_one(ToolPanel)
        old_block = panel._block

        from hermes_cli.tui.body_renderers.json import JsonRenderer

        payload = ToolPayload(
            tool_name="bash",
            category=ToolCategory.SHELL,
            args={},
            input_display=None,
            output_raw='{"key": "value"}',
            line_count=1,
        )
        cls_result = ClassificationResult(ResultKind.JSON, 0.95)
        panel._swap_renderer(JsonRenderer, payload, cls_result)
        await _pause(pilot, 3)

        # Original block should remain the panel's block and stay attached
        assert panel._block is old_block
        assert old_block.is_attached


@pytest.mark.asyncio
async def test_swap_renderer_on_failure_keeps_old():
    """_swap_renderer silently keeps old renderer on any exception."""
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.widgets import OutputPanel

    app = _make_app()
    async with app.run_test(size=(100, 40)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        app.mount_tool_block(
            "bash", ["output line"], ["output line"], tool_name="bash"
        )
        await _pause(pilot, 5)

        output = app.query_one(OutputPanel)
        panel = output.query_one(ToolPanel)
        old_block = panel._block

        # Pass a renderer that fails on build_widget() (the protected failure path)
        class BrokenRenderer:
            def __init__(self, payload, cls_result, *, app=None):
                pass
            def build_widget(self):
                raise RuntimeError("intentional failure")

        payload = ToolPayload(
            tool_name="bash",
            category=ToolCategory.SHELL,
            args={},
            input_display=None,
            output_raw="test",
            line_count=1,
        )
        cls_result = ClassificationResult(ResultKind.TEXT, 1.0)
        # Should not raise — exception is silently caught
        panel._swap_renderer(BrokenRenderer, payload, cls_result)
        await _pause(pilot, 1)

        # Old block should still be the panel's block (not swapped)
        assert panel._block is old_block
