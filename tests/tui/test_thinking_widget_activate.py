"""E1: ThinkingWidget activate/deactivate lifecycle — updated for v2 API."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from hermes_cli.tui.widgets.thinking import ThinkingWidget


class _App(App):
    def compose(self) -> ComposeResult:
        yield ThinkingWidget()


@pytest.mark.asyncio
async def test_activate_shows_widget_and_starts_timer():
    async with _App().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        assert w._timer is None
        w.activate()
        await pilot.pause()
        assert w.has_class("--active")
        assert w._timer is not None


@pytest.mark.asyncio
async def test_activate_is_idempotent():
    async with _App().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w.activate()
        timer_first = w._timer
        w.activate()
        assert w._timer is timer_first  # same timer, not re-created


@pytest.mark.asyncio
async def test_deactivate_stops_timer_and_collapses():
    async with _App().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w.activate()
        await pilot.pause()
        w.deactivate()
        # After the 150ms two-phase deactivate
        await pilot.pause(delay=0.3)
        assert w._timer is None
        assert not w.has_class("--active")


@pytest.mark.asyncio
async def test_tick_drives_label():
    async with _App().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w.activate()
        await pilot.pause()
        # _tick should run without error
        w._tick()
        await pilot.pause()
        assert w.has_class("--active")
