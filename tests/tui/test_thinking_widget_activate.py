"""E1: ThinkingWidget activate/deactivate lifecycle."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from hermes_cli.tui.widgets.message_panel import ThinkingWidget


class _App(App):
    def compose(self) -> ComposeResult:
        yield ThinkingWidget()


@pytest.mark.asyncio
async def test_activate_shows_widget_and_starts_timer():
    async with _App().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        assert w._shimmer_timer is None
        w.activate()
        await pilot.pause()
        assert w.has_class("--active")
        assert w._shimmer_timer is not None


@pytest.mark.asyncio
async def test_activate_is_idempotent():
    async with _App().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w.activate()
        timer_first = w._shimmer_timer
        w.activate()
        assert w._shimmer_timer is timer_first  # same timer, not re-created


@pytest.mark.asyncio
async def test_deactivate_stops_timer_and_collapses():
    async with _App().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w.activate()
        await pilot.pause()
        w.deactivate()
        await pilot.pause()
        assert w._shimmer_timer is None
        assert not w.has_class("--active")


@pytest.mark.asyncio
async def test_tick_shimmer_advances_phase():
    async with _App().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w.activate()
        phase_before = w._dot_phase
        w._tick_shimmer()
        assert w._dot_phase == (phase_before + 1) % 3
