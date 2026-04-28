"""Tests for UX Audit D — Motion / Feedback.

Spec: /home/xush/.hermes/2026-04-28-ux-audit-D-motion-feedback-spec.md
Changes:
- D3: CompletionList "searching" label is universal (always at row 0).
- D5: Code-fence open entrance cue (first fence per turn only).
- D6: Esc cancels in-flight stream; Space toggles _user_scrolled_up.

Hint-text update for D6 is deferred to Spec E (E4) per the UX-audit
freeze table; this file does not assert hint wording.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from textual.app import App


# ---------------------------------------------------------------------------
# D3 — CompletionList searching row universally rendered
# ---------------------------------------------------------------------------


class TestD3SearchingFallback:
    """Source-level assertion: row 0 path must call render with a Text
    containing 'searching' regardless of color mode. We assert on the
    source (AST/text scan) since VirtualCompletionList.size is a
    read-only Textual property and full-mount tests are heavyweight.
    """

    def test_render_shimmer_row_emits_searching_label_unconditionally(self):
        import inspect
        from hermes_cli.tui.completion_list import VirtualCompletionList
        src = inspect.getsource(VirtualCompletionList._render_shimmer_row)
        # Both branches the spec was concerned about must be covered:
        # the y==0 branch fires regardless of self._no_color.
        assert "searching" in src
        # The y == 0 check must come before the no_color check —
        # otherwise color-mode users get blank rows.
        idx_y_zero = src.find("y == 0")
        idx_no_color = src.find("self._no_color")
        assert idx_y_zero > 0 and idx_no_color > 0
        assert idx_y_zero < idx_no_color, (
            "D3: y == 0 branch must precede _no_color branch so the "
            "label fires in color mode too."
        )

    def test_render_shimmer_row_uses_glyph_or_label_text(self):
        import inspect
        from hermes_cli.tui.completion_list import VirtualCompletionList
        src = inspect.getsource(VirtualCompletionList._render_shimmer_row)
        # Either the hourglass glyph or the literal 'searching' word
        # must appear in the y == 0 emit path.
        assert "searching" in src


# ---------------------------------------------------------------------------
# D5 — fence-open entrance cue
# ---------------------------------------------------------------------------


def _make_engine():
    """Construct a ResponseFlowEngine with a Mock panel.

    The engine's __init__ calls panel.app.get_css_variables() in the
    StreamingBlockBuffer construction path — provide a Mock that
    returns an empty dict.
    """
    from hermes_cli.tui.response_flow import ResponseFlowEngine

    panel = MagicMock()
    panel.app = MagicMock()
    panel.app.get_css_variables = MagicMock(return_value={})
    panel.set_timer = MagicMock()
    return ResponseFlowEngine(panel=panel), panel


class TestD5FenceOpenCue:
    def test_first_fence_open_adds_class(self):
        engine, panel = _make_engine()
        # Simulate fence-open: install an _active_block stub before the
        # call site adds the class. We bypass process_line and directly
        # exercise the post-fence-open block by mocking _open_code_block.
        host = MagicMock()
        host.is_mounted = True
        engine._open_code_block = MagicMock(return_value=host)
        # Drive process_line with a fence-open line
        assert engine._first_fence_in_turn is True
        engine.process_line("```python")
        host.add_class.assert_called_with("streaming-fence-just-opened")
        assert engine._first_fence_in_turn is False

    def test_subsequent_fence_does_not_add_class(self):
        engine, panel = _make_engine()
        host = MagicMock()
        host.is_mounted = True
        engine._open_code_block = MagicMock(return_value=host)
        engine._first_fence_in_turn = False
        engine.process_line("```python")
        host.add_class.assert_not_called()

    def test_reset_first_fence_for_turn_re_enables_cue(self):
        engine, panel = _make_engine()
        engine._first_fence_in_turn = False
        engine.reset_first_fence_for_turn()
        assert engine._first_fence_in_turn is True
        host = MagicMock()
        host.is_mounted = True
        engine._open_code_block = MagicMock(return_value=host)
        engine.process_line("```python")
        host.add_class.assert_called_with("streaming-fence-just-opened")
        assert engine._first_fence_in_turn is False


# ---------------------------------------------------------------------------
# D6 — Streaming Esc/Space semantics
# ---------------------------------------------------------------------------


class _AppWithOutputPanel(App):
    """Minimal harness — App(App) wrapping OutputPanel."""

    def compose(self):
        from hermes_cli.tui.widgets import OutputPanel
        yield OutputPanel(id="output-panel")


@pytest.mark.asyncio
class TestD6StreamingEscSpace:
    async def test_esc_during_streaming_calls_agent_interrupt(self):
        app = _AppWithOutputPanel()
        async with app.run_test() as pilot:
            # Wire mock chain — minimal App has no `cli` attribute by default.
            interrupt_mock = MagicMock()
            app.cli = SimpleNamespace(agent=SimpleNamespace(interrupt=interrupt_mock))
            app.status_streaming = True
            from hermes_cli.tui.widgets import OutputPanel
            panel = app.query_one(OutputPanel)
            panel.focus()
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert interrupt_mock.call_count == 1

    async def test_space_toggles_user_scrolled_up_during_streaming(self):
        app = _AppWithOutputPanel()
        async with app.run_test() as pilot:
            app.status_streaming = True
            from hermes_cli.tui.widgets import OutputPanel
            panel = app.query_one(OutputPanel)
            panel.focus()
            await pilot.pause()
            assert panel._user_scrolled_up is False
            await pilot.press("space")
            await pilot.pause()
            assert panel._user_scrolled_up is True
            await pilot.press("space")
            await pilot.pause()
            assert panel._user_scrolled_up is False

    async def test_user_scrolled_up_preserved_after_streaming_end(self):
        app = _AppWithOutputPanel()
        async with app.run_test() as pilot:
            app.status_streaming = True
            from hermes_cli.tui.widgets import OutputPanel
            panel = app.query_one(OutputPanel)
            panel.focus()
            await pilot.pause()
            await pilot.press("space")
            await pilot.pause()
            assert panel._user_scrolled_up is True
            # Streaming ends — flag must NOT auto-reset (D6 contract).
            app.status_streaming = False
            await pilot.pause()
            assert panel._user_scrolled_up is True
