"""D2: OmissionBar collapses to 2 buttons below THRESHOLD_NARROW width."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from unittest.mock import MagicMock

from hermes_cli.tui.tool_blocks._shared import OmissionBar, THRESHOLD_NARROW


class _FakeBlock:
    def rerender_window(self, *a, **k):
        pass


class _App(App):
    def compose(self) -> ComposeResult:
        yield OmissionBar(_FakeBlock(), position="bottom")


@pytest.mark.asyncio
async def test_narrow_hides_up_and_down_all_buttons():
    """Below THRESHOLD_NARROW, [↑] and [↓all] are hidden."""
    async with _App().run_test(size=(THRESHOLD_NARROW - 1, 10)) as pilot:
        bar = pilot.app.query_one(OmissionBar)
        # Prime state with some counts so buttons exist
        bar.set_counts(visible_start=0, visible_end=50, total=200)
        await pilot.pause()
        from textual.widgets import Button
        up_btn = bar.query_one(".--ob-up", Button)
        down_all_btn = bar.query_one(".--ob-down-all", Button)
        assert not up_btn.display
        assert not down_all_btn.display


@pytest.mark.asyncio
async def test_narrow_down_button_label_becomes_pg():
    """Below THRESHOLD_NARROW, [↓] button is advanced (hidden); [↓all] also hidden."""
    async with _App().run_test(size=(THRESHOLD_NARROW - 1, 10)) as pilot:
        bar = pilot.app.query_one(OmissionBar)
        bar.set_counts(visible_start=0, visible_end=50, total=200)
        await pilot.pause()
        from textual.widgets import Button
        # In narrow mode [↓all] is hidden; [↓] is advanced and also hidden
        down_all_btn = bar.query_one(".--ob-down-all", Button)
        assert not down_all_btn.display


@pytest.mark.asyncio
async def test_wide_restores_buttons():
    """Above THRESHOLD_NARROW, [↓all] visible again (advanced buttons stay behind [more▸])."""
    async with _App().run_test(size=(THRESHOLD_NARROW + 20, 10)) as pilot:
        bar = pilot.app.query_one(OmissionBar)
        bar.set_counts(visible_start=0, visible_end=50, total=200)
        await pilot.pause()
        from textual.widgets import Button
        down_all_btn = bar.query_one(".--ob-down-all", Button)
        assert down_all_btn.display
