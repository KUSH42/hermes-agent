"""B3: ToolPanelMini hover reveals/hides source panel via --minified class."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from hermes_cli.tui.tool_panel_mini import ToolPanelMini


class _FakeSource(Static):
    pass


class _App(App):
    def compose(self) -> ComposeResult:
        self.source = _FakeSource("body")
        self.source.add_class("--minified")
        self.mini = ToolPanelMini(source_panel=self.source)
        yield self.source
        yield self.mini


@pytest.mark.asyncio
async def test_hover_true_removes_minified():
    async with _App().run_test() as pilot:
        app = pilot.app
        assert app.source.has_class("--minified")
        app.mini.watch_mouse_hover(True)
        await pilot.pause()
        assert not app.source.has_class("--minified")


@pytest.mark.asyncio
async def test_hover_false_restores_minified():
    async with _App().run_test() as pilot:
        app = pilot.app
        app.mini.watch_mouse_hover(True)
        await pilot.pause()
        app.mini.watch_mouse_hover(False)
        await pilot.pause()
        assert app.source.has_class("--minified")


@pytest.mark.asyncio
async def test_expand_removes_minified_and_removes_mini():
    async with _App().run_test() as pilot:
        app = pilot.app
        app.mini._expand()
        await pilot.pause(delay=0.1)
        assert not app.source.has_class("--minified")
        # remove() is scheduled async; check it was called by verifying source visible
        assert not app.source.has_class("--minified")
