"""I1: ReasoningPanel collapsed stub has bold glyph + primary-colored 'click to expand'."""
from __future__ import annotations

import pytest
from rich.text import Text
from textual.app import App, ComposeResult

from hermes_cli.tui.widgets.message_panel import ReasoningPanel


class _App(App):
    def compose(self) -> ComposeResult:
        panel = ReasoningPanel()
        panel.add_class("visible")
        yield panel


@pytest.mark.asyncio
async def test_collapsed_stub_contains_glyph():
    """Collapsed stub starts with ▸ glyph."""
    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ReasoningPanel)
        panel._plain_lines = ["line1", "line2", "line3"]
        panel._update_collapsed_stub()
        await pilot.pause()
        stub_text = panel._collapsed_stub._Static__content
        assert "▸" in stub_text.plain


@pytest.mark.asyncio
async def test_collapsed_stub_shows_line_count():
    """Collapsed stub shows correct line count."""
    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ReasoningPanel)
        panel._plain_lines = ["a", "b", "c", "d", "e"]
        panel._update_collapsed_stub()
        await pilot.pause()
        stub_text = panel._collapsed_stub._Static__content
        assert "5L" in stub_text.plain


@pytest.mark.asyncio
async def test_collapsed_stub_shows_reasoning_collapsed():
    """I2: collapsed stub shows 'Reasoning collapsed' but NOT 'click to expand'."""
    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ReasoningPanel)
        panel._plain_lines = ["x"]
        panel._update_collapsed_stub()
        await pilot.pause()
        stub_text = panel._collapsed_stub._Static__content
        assert "Reasoning collapsed" in stub_text.plain
        assert "click to expand" not in stub_text.plain


@pytest.mark.asyncio
async def test_collapsed_stub_uses_rich_text():
    """_update_collapsed_stub produces a rich Text object (not markup string)."""
    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ReasoningPanel)
        panel._plain_lines = ["line"]
        panel._update_collapsed_stub()
        await pilot.pause()
        content = panel._collapsed_stub._Static__content
        assert isinstance(content, Text)
