"""Tests for ctrl+shift+a / ctrl+b drawille animation config panel toggle."""

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.drawille_overlay import AnimConfigPanel


@pytest.mark.asyncio
async def test_ctrl_shift_a_toggles_drawille_overlay():
    """ctrl+shift+a shows the AnimConfigPanel overlay (--visible toggle)."""
    from unittest.mock import MagicMock
    cli = MagicMock()
    app = HermesApp(cli=cli)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        panel = app.query_one(AnimConfigPanel)
        # Panel starts hidden
        assert not panel.has_class("--visible"), "AnimConfigPanel should be hidden initially"

        await pilot.press("ctrl+shift+a")
        await pilot.pause()
        assert panel.has_class("--visible"), "AnimConfigPanel should show after ctrl+shift+a"


@pytest.mark.asyncio
async def test_ctrl_shift_a_works_with_disabled_input():
    """ctrl+shift+a shows AnimConfigPanel even when input is disabled."""
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

        panel = app.query_one(AnimConfigPanel)
        assert not panel.has_class("--visible"), "AnimConfigPanel should start hidden"

        await pilot.press("ctrl+shift+a")
        await pilot.pause()
        assert panel.has_class("--visible"), "AnimConfigPanel should show after ctrl+shift+a with disabled input"
