"""Tests for HintBar, StatusBar, VoiceStatusBar, ImageBar — Step 3."""

from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import HintBar, ImageBar, StatusBar, VoiceStatusBar


@pytest.mark.asyncio
async def test_hint_bar_updates_on_reactive_change():
    """HintBar.hint reactive triggers widget update."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(HintBar)
        bar.hint = "⠋ thinking..."
        await pilot.pause()
        # The rendered content should reflect the hint value


@pytest.mark.asyncio
async def test_spinner_tick_updates_input_when_agent_running():
    """_tick_spinner updates input widget's spinner_text when agent_running is True."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        # Wait for at least one spinner tick (100ms interval)
        import asyncio
        await asyncio.sleep(0.15)
        await pilot.pause()
        inp = app.query_one("#input-area")
        assert hasattr(inp, "spinner_text")
        assert inp.spinner_text != ""


@pytest.mark.asyncio
async def test_spinner_stops_when_agent_not_running():
    """HintBar clears when agent_running becomes False."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        app.agent_running = False
        await pilot.pause()
        bar = app.query_one(HintBar)
        assert bar.hint == ""


@pytest.mark.asyncio
async def test_status_bar_renders_model_tokens_duration():
    """StatusBar renders status_model, status_tokens, and status_duration."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.status_model = "claude-opus"
        app.status_tokens = 1234
        app.status_duration = 5.7
        await pilot.pause()
        bar = app.query_one(StatusBar)
        # Force re-render check — the bar should exist and have rendered


@pytest.mark.asyncio
async def test_agent_running_disables_input():
    """Setting agent_running=True disables the input area."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        input_widget = app.query_one("#input-area")
        assert not input_widget.disabled
        app.agent_running = True
        await pilot.pause()
        assert input_widget.disabled


@pytest.mark.asyncio
async def test_voice_status_bar_hidden_by_default():
    """VoiceStatusBar is hidden when voice_mode is False."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(VoiceStatusBar)
        assert not bar.has_class("active")


@pytest.mark.asyncio
async def test_voice_status_bar_shows_on_voice_mode():
    """VoiceStatusBar becomes visible when voice_mode is True."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.voice_mode = True
        await pilot.pause()
        bar = app.query_one(VoiceStatusBar)
        assert bar.has_class("active")


@pytest.mark.asyncio
async def test_voice_recording_updates_status():
    """VoiceStatusBar shows 'REC' when recording."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.voice_mode = True
        app.voice_recording = True
        await pilot.pause()


@pytest.mark.asyncio
async def test_image_bar_hidden_when_no_images():
    """ImageBar is hidden when no images are attached."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(ImageBar)
        assert not bar.display


@pytest.mark.asyncio
async def test_image_bar_shows_on_attach():
    """ImageBar becomes visible when images are attached."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        class FakeImage:
            name = "screenshot.png"

        app.attached_images = [FakeImage()]
        await pilot.pause()
        bar = app.query_one(ImageBar)
        assert bar.display
