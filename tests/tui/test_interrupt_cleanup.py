"""Tests for interrupt cleanup: streaming block dict clearing, blink timer, idempotency.

Design: on interrupt, _active_streaming_blocks dict is cleared (releases GC refs,
prevents stale entries on next turn).  DOM nodes are NOT removed — partial tool
output stays visible so users can see what was running when interrupted.
"""

from unittest.mock import MagicMock, patch
import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import LiveLineWidget, OutputPanel


def _app_with_agent():
    cli = MagicMock()
    cli.agent = MagicMock()
    cli.agent.interrupt = MagicMock()
    app = HermesApp(cli=cli)
    return app, cli


# ---------------------------------------------------------------------------
# P0-1: streaming block dict cleared on interrupt (DOM nodes stay)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_streaming_blocks_dict_empty_after_interrupt():
    """_active_streaming_blocks is cleared after watch_agent_running(False)."""
    app, cli = _app_with_agent()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = MagicMock()
        block.is_mounted = True
        app._active_streaming_blocks = {"x": block}
        app.agent_running = True
        await pilot.pause()
        app.agent_running = False
        await pilot.pause()
        assert app._active_streaming_blocks == {}


@pytest.mark.asyncio
async def test_streaming_blocks_not_removed_from_dom_on_interrupt():
    """watch_agent_running(False) does NOT call .remove() — partial output stays visible."""
    app, cli = _app_with_agent()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = MagicMock()
        block.is_mounted = True
        app._active_streaming_blocks = {"a": block}
        app.agent_running = True
        await pilot.pause()
        app.agent_running = False
        await pilot.pause()
        block.remove.assert_not_called()
        assert app._active_streaming_blocks == {}


@pytest.mark.asyncio
async def test_multiple_blocks_dict_all_cleared_on_interrupt():
    """Multiple tracked blocks: dict cleared, none removed from DOM."""
    app, cli = _app_with_agent()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block1 = MagicMock()
        block1.is_mounted = True
        block2 = MagicMock()
        block2.is_mounted = True
        app._active_streaming_blocks = {"a": block1, "b": block2}
        app.agent_running = True
        await pilot.pause()
        app.agent_running = False
        await pilot.pause()
        block1.remove.assert_not_called()
        block2.remove.assert_not_called()
        assert app._active_streaming_blocks == {}


# ---------------------------------------------------------------------------
# P1-5 regression: blink timer cleared by flush()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flush_live_stops_blink_timer():
    """(regression) LiveLineWidget.flush() sets _blink_timer to None."""
    app, cli = _app_with_agent()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        live = app.query_one(OutputPanel).live_line
        # Inject a fake timer so flush() has something to stop
        fake_timer = MagicMock()
        live._blink_timer = fake_timer
        live.flush()
        fake_timer.stop.assert_called_once()
        assert live._blink_timer is None


@pytest.mark.asyncio
async def test_blink_timer_none_after_watch_agent_running_false():
    """(regression) watch_agent_running(False) leaves blink timer cleared via flush_live."""
    app, cli = _app_with_agent()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        live = app.query_one(OutputPanel).live_line
        fake_timer = MagicMock()
        live._blink_timer = fake_timer
        app.agent_running = True
        await pilot.pause()
        app.agent_running = False
        await pilot.pause()
        assert live._blink_timer is None


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cleanup_idempotent_double_call():
    """watch_agent_running(False) called twice does not raise."""
    app, cli = _app_with_agent()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        app.agent_running = False
        await pilot.pause()
        # Simulate a second turn and another False transition
        app.agent_running = True
        await pilot.pause()
        app.agent_running = False
        await pilot.pause()
