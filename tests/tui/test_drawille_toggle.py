"""Tests for ctrl+shift+a drawille overlay toggle."""

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.drawille_overlay import DrawilleOverlay


@pytest.mark.asyncio
async def test_ctrl_shift_a_toggles_drawille_overlay():
    """ctrl+shift+a toggles DrawilleOverlay -visible class."""
    from unittest.mock import MagicMock
    cli = MagicMock()
    app = HermesApp(cli=cli)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        do = app.query_one(DrawilleOverlay)
        # Simulate overlay being shown (cfg.enabled=False in test env)
        do.add_class("-visible")
        await pilot.pause()
        assert do.has_class("-visible")

        await pilot.press("ctrl+shift+a")
        await pilot.pause()
        assert not do.has_class("-visible"), "Overlay should hide after ctrl+shift+a"

        await pilot.press("ctrl+shift+a")
        await pilot.pause()
        assert do.has_class("-visible"), "Overlay should show again after second ctrl+shift+a"


@pytest.mark.asyncio
async def test_ctrl_shift_a_works_with_disabled_input():
    """ctrl+shift+a toggles overlay even when input is disabled."""
    from unittest.mock import MagicMock
    from hermes_cli.tui.input_widget import HermesInput
    cli = MagicMock()
    app = HermesApp(cli=cli)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.focus()
        inp.disabled = True
        app.agent_running = True

        do = app.query_one(DrawilleOverlay)
        do.add_class("-visible")
        await pilot.pause()

        await pilot.press("ctrl+shift+a")
        await pilot.pause()
        assert not do.has_class("-visible")
