"""Tests for B2 — static ToolBlock completion path parity with streaming path.

Verifies that mount_tool_block wires up _is_complete, _tool_icon_error,
set_result_summary_v4, and flash exactly as the streamed path does.

Run with:
    pytest -o "addopts=" tests/tui/test_completion_parity.py -v
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.tool_blocks import ToolBlock
from hermes_cli.tui.tool_result_parse import ResultSummaryV4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app():
    return HermesApp(cli=MagicMock())


# ---------------------------------------------------------------------------
# Static path — header state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_static_header_is_complete():
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = app.mount_tool_block("output", ["line"], ["line"])
        await pilot.pause()
        assert block._header._is_complete is True


@pytest.mark.asyncio
async def test_static_flash_success_sets_no_error():
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = app.mount_tool_block("output", ["line"], ["line"])
        await pilot.pause()
        assert block._header._tool_icon_error is False


@pytest.mark.asyncio
async def test_static_flash_error_sets_tool_icon_error():
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = app.mount_tool_block("output", ["line"], ["line"], is_error=True)
        await pilot.pause()
        assert block._header._tool_icon_error is True


# ---------------------------------------------------------------------------
# Static path — ResultSummaryV4 on panel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_static_result_summary_v4_set():
    from hermes_cli.tui.tool_panel import ToolPanel
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.mount_tool_block("output", ["line"], ["line"])
        await pilot.pause()
        panel = app.query_one(ToolPanel)
        assert panel._result_summary_v4 is not None


@pytest.mark.asyncio
async def test_static_result_summary_not_error():
    from hermes_cli.tui.tool_panel import ToolPanel
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.mount_tool_block("output", ["line"], ["line"])
        await pilot.pause()
        panel = app.query_one(ToolPanel)
        assert panel._result_summary_v4.is_error is False


@pytest.mark.asyncio
async def test_static_result_summary_is_error():
    from hermes_cli.tui.tool_panel import ToolPanel
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.mount_tool_block("output", ["line"], ["line"], is_error=True)
        await pilot.pause()
        panel = app.query_one(ToolPanel)
        assert panel._result_summary_v4.is_error is True


# ---------------------------------------------------------------------------
# Static path — copy content
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_static_copy_body_returns_content():
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = app.mount_tool_block("output", ["line"], ["line"])
        assert block.copy_content() == "line"


# ---------------------------------------------------------------------------
# Unit test — _complete_static flash path (no app required)
# ---------------------------------------------------------------------------

def test_complete_static_flash_fires_without_app():
    """_complete_static reaches flash_success via _header without a mounted DOM.

    Uses ToolBlock.__new__ to skip __init__ (no widget tree needed); sets only
    _header since _complete_static accesses nothing else. The mock verifies the
    call path reaches flash_success regardless of the try/except guard in the
    real implementation.
    """
    block = ToolBlock.__new__(ToolBlock)
    block._header = MagicMock()
    block._header.flash_success = MagicMock()
    block._complete_static()
    block._header.flash_success.assert_called_once()


def test_complete_static_flash_error_path():
    block = ToolBlock.__new__(ToolBlock)
    block._header = MagicMock()
    block._header.flash_error = MagicMock()
    block._complete_static(is_error=True)
    block._header.flash_error.assert_called_once()


# ---------------------------------------------------------------------------
# Signature compatibility
# ---------------------------------------------------------------------------

def test_existing_callers_unchanged():
    """is_error param exists with default False; old positional form still works."""
    sig = inspect.signature(HermesApp.mount_tool_block)
    assert "is_error" in sig.parameters
    assert sig.parameters["is_error"].default is False


@pytest.mark.asyncio
async def test_existing_callers_no_raise():
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # old positional form (no is_error)
        block = app.mount_tool_block("output", ["x"], ["x"])
        assert block is not None


# ---------------------------------------------------------------------------
# Regression — streaming path unchanged
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_streaming_path_unchanged():
    from hermes_cli.tui.tool_panel import ToolPanel
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.open_streaming_tool_block(
            tool_call_id="tc-1", label="output", tool_name=None
        )
        await pilot.pause()
        summary = ResultSummaryV4(
            primary=None,
            exit_code=None,
            chips=(),
            stderr_tail="",
            actions=(),
            artifacts=(),
            is_error=False,
        )
        app.close_streaming_tool_block(
            tool_call_id="tc-1", duration="1.0s", summary=summary
        )
        await pilot.pause()
        panel = app.query_one(ToolPanel)
        assert panel._result_summary_v4 is not None
