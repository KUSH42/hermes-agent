"""B2: age microcopy formats correctly and _tick_age is lifecycle-safe."""
from __future__ import annotations

import pytest

from hermes_cli.tui.tool_panel import _format_age


def test_format_age_seconds():
    assert _format_age(10) == "completed 10s ago"
    assert _format_age(59) == "completed 59s ago"


def test_format_age_minutes():
    assert _format_age(60) == "completed 1m ago"
    assert _format_age(125) == "completed 2m ago"
    assert _format_age(3599) == "completed 59m ago"


def test_format_age_hours():
    assert _format_age(3600) == "completed 1h ago"
    assert _format_age(7200) == "completed 2h ago"


@pytest.mark.asyncio
async def test_tick_age_noop_when_unmounted():
    """_tick_age must not crash if widget is not mounted."""
    from textual.app import App, ComposeResult
    from textual.widgets import Static
    from hermes_cli.tui.tool_panel import ToolPanel

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanel(block=Static("body"), tool_name="Bash")

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        # _completed_at not set → tick should be silent no-op
        panel._tick_age()
        await pilot.pause()
        # No exception = pass
