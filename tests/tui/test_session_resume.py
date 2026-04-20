"""Tests for /resume session banner and state reset (spec §A1).

5 tests covering handle_session_resume:
  1. Clears OutputPanel and leaves exactly one _SessionResumedBanner child
  2. Banner text contains the session title when provided
  3. Banner shows last-8-chars of session_id when title is empty
  4. Banner text contains the turn count
  5. app.session_label is updated to the title (or short id)
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.overlays import _SessionResumedBanner
from hermes_cli.tui.widgets import MessagePanel, OutputPanel, ThinkingWidget


def _make_app() -> HermesApp:
    cli = MagicMock()
    cli.config = {}
    return HermesApp(cli=cli)


async def _mount_panels(app: HermesApp, n: int) -> None:
    """Mount n MessagePanels into OutputPanel (before ThinkingWidget)."""
    output = app.query_one(OutputPanel)
    thinking = output.query_one(ThinkingWidget)
    for _ in range(n):
        await output.mount(MessagePanel(), before=thinking)


# ---------------------------------------------------------------------------
# 1. handle_session_resume clears OutputPanel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_clears_output_panel():
    """After handle_session_resume, OutputPanel has exactly one _SessionResumedBanner."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await _mount_panels(app, 3)
        await pilot.pause()

        app.handle_session_resume("sess-abc12345", "my session", 5)
        await pilot.pause()

        output = app.query_one(OutputPanel)
        children = list(output.children)
        banners = [c for c in children if isinstance(c, _SessionResumedBanner)]
        assert len(banners) == 1
        # No MessagePanels should remain
        panels = [c for c in children if isinstance(c, MessagePanel)]
        assert len(panels) == 0


# ---------------------------------------------------------------------------
# 2. Banner text contains the session title
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_banner_shows_title():
    """Banner render output contains the provided session title."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.handle_session_resume("sess-abc12345", "fix login bug", 3)
        await pilot.pause()

        output = app.query_one(OutputPanel)
        banner = next(c for c in output.children if isinstance(c, _SessionResumedBanner))
        text = banner.render()
        assert "fix login bug" in text


# ---------------------------------------------------------------------------
# 3. Banner shows short session_id when title is empty
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_banner_shows_short_id_when_no_title():
    """When title is empty, banner shows last 8 chars of session_id."""
    session_id = "abcdef1234567890"
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.handle_session_resume(session_id, "", 2)
        await pilot.pause()

        output = app.query_one(OutputPanel)
        banner = next(c for c in output.children if isinstance(c, _SessionResumedBanner))
        text = banner.render()
        # short_id = last 8 chars
        assert session_id[-8:] in text


# ---------------------------------------------------------------------------
# 4. Banner shows the turn count
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_banner_shows_turn_count():
    """Banner text contains the numeric turn count."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.handle_session_resume("sess-xyz", "some session", 17)
        await pilot.pause()

        output = app.query_one(OutputPanel)
        banner = next(c for c in output.children if isinstance(c, _SessionResumedBanner))
        text = banner.render()
        assert "17" in text


# ---------------------------------------------------------------------------
# 5. session_label reactive is updated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_sets_session_label():
    """handle_session_resume updates app.session_label."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.handle_session_resume("sess-xyz", "fix history UX", 4)
        await pilot.pause()

        assert app.session_label == "fix history UX"


@pytest.mark.asyncio
async def test_resume_sets_session_label_short_id_when_no_title():
    """When title is empty, session_label is set to last-8 chars of session_id."""
    session_id = "xxxxxxxxxxABCDEFGH"
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.handle_session_resume(session_id, "", 1)
        await pilot.pause()

        assert app.session_label == session_id[-8:]
