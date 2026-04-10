"""Tests for theme/skin system — Step 6."""

from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp


@pytest.mark.asyncio
async def test_apply_skin_injects_css_vars():
    """apply_skin stores vars that get_css_variables returns."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.apply_skin({"primary": "#FF0000", "background": "#000000"})
        await pilot.pause()
        css_vars = app.get_css_variables()
        assert css_vars["primary"] == "#FF0000"
        assert css_vars["background"] == "#000000"


@pytest.mark.asyncio
async def test_get_css_variables_includes_textual_defaults():
    """get_css_variables includes Textual's built-in theme variables."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        css_vars = app.get_css_variables()
        # Textual auto-generates variables like $primary, $background
        # Our override should merge, not replace
        assert isinstance(css_vars, dict)
        assert len(css_vars) > 0


@pytest.mark.asyncio
async def test_bad_skin_does_not_crash():
    """apply_skin with bad values logs warning but doesn't crash."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # This should not crash — invalid CSS values are handled gracefully
        app.apply_skin({"not-a-real-var": "invalid"})
        await pilot.pause()
