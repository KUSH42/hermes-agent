"""Tests for session_label reactive and StatusBar chip (spec §B3).

4 tests:
  1. Fresh app has session_label == ""
  2. StatusBar render contains session_label text when set
  3. Label longer than 28 chars is truncated with '…'
  4. Empty label: ' · ' prefix absent from render
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import StatusBar


def _make_app() -> HermesApp:
    cli = MagicMock()
    cli.config = {}
    cli._cfg = {}
    return HermesApp(cli=cli)


# ---------------------------------------------------------------------------
# 1. Default session_label is empty string
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_label_reactive_default_empty():
    """Fresh HermesApp has session_label == ''."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.session_label == ""


# ---------------------------------------------------------------------------
# 2. StatusBar render contains session_label text
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_bar_shows_session_label():
    """Setting app.session_label causes StatusBar to include that text in render."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.session_label = "my session"
        await pilot.pause()

        bar = app.query_one(StatusBar)
        rendered = bar.render()
        # Rich Text → str
        text_str = str(rendered)
        assert "my session" in text_str


# ---------------------------------------------------------------------------
# 3. Label longer than 28 chars is truncated with '…'
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_label_truncated_long():
    """A label exceeding 28 characters is truncated and ends with '…'."""
    long_label = "a" * 40
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.session_label = long_label
        await pilot.pause()

        bar = app.query_one(StatusBar)
        rendered = str(bar.render())
        # Should contain truncated version (28 chars + '…')
        assert "…" in rendered
        assert long_label not in rendered  # full string must not appear


# ---------------------------------------------------------------------------
# 4. Empty label: no ' · ' prefix
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_label_empty_no_prefix():
    """When session_label is empty, the session chip prefix is absent."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.session_label = ""
        await pilot.pause()

        bar = app.query_one(StatusBar)
        rendered = str(bar.render())
        # The ' · ' separator that immediately follows the session label should
        # not appear as the very first non-space character cluster when no label is set.
        # Verify by checking that the render does not start with a label+dot pattern.
        # Simplest invariant: render does not begin with ' · '
        assert not rendered.startswith(" · ")
