"""Tests for R3-H1 panel.id timing + FeedbackService channel registration, and R3-M1 ks-context fallback.

R3-H1: MessagePanel.open_streaming_tool_block previously dropped the panel_id
argument so panel.id was None at on_mount → FeedbackService channel registered
under "tool-header::None" → all header flashes raised KeyError (swallowed).

R3-M1: _ks_context had no fallback to derive block_id from panel.id, so rows
logged "block_id=unknown" whenever _view_state and _plan_tool_call_id were absent.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from hermes_cli.tui.tool_panel import ToolPanel
from hermes_cli.tui.services.feedback import FeedbackService


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

class _FakeCancelToken:
    def stop(self) -> None:
        pass


class _FakeScheduler:
    def after(self, delay: float, cb: Any) -> _FakeCancelToken:
        return _FakeCancelToken()


def _make_feedback() -> FeedbackService:
    return FeedbackService(_FakeScheduler())


class _FakeHeader(Static):
    """Minimal Widget acting as a tool header for channel registration tests."""
    DEFAULT_CSS = "_FakeHeader { height: auto; }"
    _flash_msg: str | None = None
    _flash_tone: str | None = None
    _flash_expires: float | None = None


class _FakeBlock(Static):
    """Minimal Widget acting as a tool block.

    ToolPanel.compose() yields _block._header (if set) and BodyPane yields _block.
    Both must be real Widget instances.
    """
    DEFAULT_CSS = "_FakeBlock { height: auto; }"

    def __init__(self, *, with_header: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._header: _FakeHeader | None = _FakeHeader() if with_header else None
        self._microcopy_shown: bool = False


def _make_summary(*, is_error: bool = False) -> Any:
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    return ResultSummaryV4(
        primary="done",
        exit_code=0,
        chips=(),
        stderr_tail="",
        actions=(),
        artifacts=(),
        is_error=is_error,
        error_kind=None,
    )


class _PanelApp(App):
    """Minimal host for single-panel tests. Wires FeedbackService before compose."""

    def __init__(
        self,
        block: "_FakeBlock",
        panel_id: "str | None",
        feedback: FeedbackService,
    ) -> None:
        super().__init__()
        self.feedback = feedback
        self._block = block
        self._panel_id = panel_id

    def compose(self) -> ComposeResult:
        yield ToolPanel(self._block, tool_name="terminal", id=self._panel_id)


# ---------------------------------------------------------------------------
# R3-H1 tests
# ---------------------------------------------------------------------------


def test_panel_id_set_at_construction():
    """ToolPanel constructed with id= has .id set immediately (no app needed)."""
    block = _FakeBlock()
    panel = ToolPanel(block, tool_name="terminal", id="tool-tc1")
    assert panel.id == "tool-tc1"


def test_panel_id_none_when_not_passed():
    """Regression guard: ToolPanel without id= has .id == None at construction."""
    block = _FakeBlock()
    panel = ToolPanel(block, tool_name="terminal")
    assert panel.id is None


@pytest.mark.asyncio
async def test_channel_registered_under_correct_key_at_mount():
    """Panel mounted with id='tool-tc1' registers 'tool-header::tool-tc1', not 'tool-header::None'."""
    feedback = _make_feedback()
    block = _FakeBlock()
    app = _PanelApp(block, "tool-tc1", feedback)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "tool-header::tool-tc1" in feedback._channels
        assert "tool-header::None" not in feedback._channels


@pytest.mark.asyncio
async def test_on_mount_guard_skips_registration_when_id_none():
    """Panel mounted without id= skips channel registration (no 'tool-header::None' pollution)."""
    feedback = _make_feedback()
    block = _FakeBlock()
    app = _PanelApp(block, None, feedback)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "tool-header::None" not in feedback._channels


@pytest.mark.asyncio
async def test_two_panels_register_distinct_channels():
    """Two panels with distinct ids each get their own channel; no collision."""
    feedback = _make_feedback()

    class _TwoPanelApp(App):
        def __init__(self) -> None:
            super().__init__()
            self.feedback = feedback

        def compose(self) -> ComposeResult:
            yield ToolPanel(_FakeBlock(), tool_name="terminal", id="tool-tc1")
            yield ToolPanel(_FakeBlock(), tool_name="bash", id="tool-tc2")

    app = _TwoPanelApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "tool-header::tool-tc1" in feedback._channels
        assert "tool-header::tool-tc2" in feedback._channels


@pytest.mark.asyncio
async def test_adoption_re_registers_channel_on_collision_path():
    """_move_panel_channel: deregisters old_id, registers new_id."""
    from hermes_cli.tui.services.tools import ToolRenderingService

    feedback = _make_feedback()
    block = _FakeBlock()

    # Panel mounted with no id — on_mount guard skips registration
    app = _PanelApp(block, None, feedback)
    async with app.run_test() as pilot:
        await pilot.pause()
        panel = app.query_one(ToolPanel)

        # Confirm no registration happened
        assert "tool-header::None" not in feedback._channels
        assert "tool-header::tool-tc1" not in feedback._channels

        # Simulate adoption: _move_panel_channel called by ToolRenderingService
        mock_app = MagicMock()
        mock_app.feedback = feedback
        svc = ToolRenderingService(mock_app)
        svc._move_panel_channel(panel, None, "tool-tc1")

        assert "tool-header::None" not in feedback._channels
        assert "tool-header::tool-tc1" in feedback._channels


@pytest.mark.asyncio
async def test_move_panel_channel_no_header_logs_warning():
    """_move_panel_channel logs WARNING when _block has no _header."""
    from hermes_cli.tui.services.tools import ToolRenderingService

    feedback = _make_feedback()
    block = _FakeBlock(with_header=False)
    app = _PanelApp(block, None, feedback)
    async with app.run_test() as pilot:
        await pilot.pause()
        panel = app.query_one(ToolPanel)

        mock_app = MagicMock()
        mock_app.feedback = feedback
        svc = ToolRenderingService(mock_app)

        with patch("hermes_cli.tui.services.tools.logger") as mock_logger:
            svc._move_panel_channel(panel, None, "tool-tc1")
            assert mock_logger.warning.called
            warning_msg = str(mock_logger.warning.call_args)
            assert "_header" in warning_msg


@pytest.mark.asyncio
async def test_completion_done_flash_logs_keyerror_when_channel_missing():
    """set_result_summary logs DEBUG KeyError when feedback channel absent, no exception."""
    feedback = _make_feedback()
    block = _FakeBlock()
    block._microcopy_shown = False

    app = _PanelApp(block, "tool-tc1", feedback)
    async with app.run_test() as pilot:
        await pilot.pause()
        panel = app.query_one(ToolPanel)

        # Deregister the channel so the flash call raises KeyError
        feedback.deregister_channel("tool-header::tool-tc1")

        with patch("hermes_cli.tui.tool_panel._completion._log") as mock_log:
            panel.set_result_summary(_make_summary(is_error=False))
            await pilot.pause()

        debug_calls = [str(c) for c in mock_log.debug.call_args_list]
        assert any("tool-header channel missing" in c for c in debug_calls), (
            f"Expected 'tool-header channel missing' in debug log; got: {debug_calls}"
        )
        assert not mock_log.exception.called, "No exception-level log expected for KeyError path"


@pytest.mark.asyncio
async def test_completion_done_flash_dispatched_when_channel_present():
    """set_result_summary dispatches 'done' flash when channel is registered."""
    feedback = _make_feedback()
    block = _FakeBlock()
    block._microcopy_shown = False

    app = _PanelApp(block, "tool-tc1", feedback)
    async with app.run_test() as pilot:
        await pilot.pause()
        panel = app.query_one(ToolPanel)

        # Ensure panel is not settled (flash would be suppressed otherwise)
        assert not getattr(panel, "_settled", False)

        flash_calls: list[tuple[str, str]] = []
        original_flash = feedback.flash

        def _spy_flash(channel: str, message: str, **kwargs: Any) -> Any:
            flash_calls.append((channel, message))
            return original_flash(channel, message, **kwargs)

        feedback.flash = _spy_flash  # type: ignore[method-assign]
        panel.set_result_summary(_make_summary(is_error=False))
        await pilot.pause()

        assert any(
            ch == "tool-header::tool-tc1" and msg == "done"
            for ch, msg in flash_calls
        ), f"Expected 'done' flash on tool-header::tool-tc1; got: {flash_calls}"


# ---------------------------------------------------------------------------
# R3-M1 tests
# ---------------------------------------------------------------------------


def test_ks_context_falls_back_to_panel_id():
    """_ks_context derives block_id from panel.id when _view_state is absent."""
    block = _FakeBlock()
    panel = ToolPanel(block, tool_name="terminal", id="tool-tc1")
    panel._view_state = None
    panel._plan_tool_call_id = None

    block_id, phase, kind_val = panel._ks_context()
    assert block_id == "tc1", f"Expected 'tc1' (peeled 'tool-'), got {block_id!r}"


def test_ks_context_returns_unknown_when_no_id_and_no_view_state():
    """_ks_context returns 'unknown' when both _view_state and panel.id are absent."""
    block = _FakeBlock()
    panel = ToolPanel(block, tool_name="terminal")  # no id kwarg
    panel._view_state = None
    panel._plan_tool_call_id = None

    block_id, phase, kind_val = panel._ks_context()
    assert block_id == "unknown"
