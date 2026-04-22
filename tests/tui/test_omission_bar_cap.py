"""H1: OmissionBar.set_counts respects visible_cap override for at_default check."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button

from hermes_cli.tui.tool_blocks._shared import OmissionBar, _VISIBLE_CAP


class _FakeBlock:
    def rerender_window(self, *a, **k):
        pass


class _App(App):
    def compose(self) -> ComposeResult:
        yield OmissionBar(_FakeBlock(), position="bottom")


@pytest.mark.asyncio
async def test_default_cap_buttons_disabled_at_default_window():
    """With default visible_cap, buttons are disabled when window is at default."""
    async with _App().run_test(size=(120, 10)) as pilot:
        bar = pilot.app.query_one(OmissionBar)
        bar.set_counts(
            visible_start=0,
            visible_end=_VISIBLE_CAP,
            total=_VISIBLE_CAP,
            visible_cap=_VISIBLE_CAP,
        )
        await pilot.pause()
        cap_btn = bar.query_one(".--ob-cap", Button)
        up_btn = bar.query_one(".--ob-up", Button)
        assert cap_btn.disabled
        assert up_btn.disabled


@pytest.mark.asyncio
async def test_custom_cap_not_at_default_when_window_exceeds_custom_cap():
    """When custom cap is lower, showing more than cap enables reset/up buttons."""
    async with _App().run_test(size=(120, 10)) as pilot:
        bar = pilot.app.query_one(OmissionBar)
        custom_cap = 50
        bar.set_counts(
            visible_start=0,
            visible_end=100,  # visible window > custom cap
            total=150,
            visible_cap=custom_cap,
        )
        await pilot.pause()
        cap_btn = bar.query_one(".--ob-cap", Button)
        up_btn = bar.query_one(".--ob-up", Button)
        # at_default = (visible_start==0 and (visible_end - visible_start) <= custom_cap)
        # = (0==0 and 100 <= 50) = False → buttons enabled
        assert not cap_btn.disabled
        assert not up_btn.disabled


@pytest.mark.asyncio
async def test_custom_cap_buttons_disabled_when_within_cap():
    """Custom cap: buttons disabled when window is within cap."""
    async with _App().run_test(size=(120, 10)) as pilot:
        bar = pilot.app.query_one(OmissionBar)
        custom_cap = 100
        bar.set_counts(
            visible_start=0,
            visible_end=80,  # within custom cap
            total=80,
            visible_cap=custom_cap,
        )
        await pilot.pause()
        cap_btn = bar.query_one(".--ob-cap", Button)
        up_btn = bar.query_one(".--ob-up", Button)
        assert cap_btn.disabled
        assert up_btn.disabled
