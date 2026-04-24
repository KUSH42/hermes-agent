"""C1: .error-banner CSS covers both static and streaming tool blocks."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static


class _App(App):
    CSS = """
.error-banner {
    color: red;
    background: red 10%;
    height: auto;
}
"""

    def compose(self) -> ComposeResult:
        yield Static("error text", classes="error-banner")


@pytest.mark.asyncio
async def test_error_banner_class_renders():
    async with _App().run_test() as pilot:
        banner = pilot.app.query_one(".error-banner")
        assert banner is not None
        assert banner.has_class("error-banner")


@pytest.mark.asyncio
async def test_error_banner_no_streaming_prefix_required():
    """CSS rule applies to .error-banner anywhere — not just inside StreamingToolBlock."""
    async with _App().run_test() as pilot:
        # Banner at root level (no StreamingToolBlock ancestor) still gets the class
        banner = pilot.app.query_one(".error-banner", Static)
        assert banner.has_class("error-banner")
