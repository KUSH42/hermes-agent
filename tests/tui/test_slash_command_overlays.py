"""Tests for slash command TUI integration — §5 of spec.

Covers:
  1   HelpOverlay hidden by default
  2   /help shows HelpOverlay with --visible
  3   /help sets focus on #help-search Input
  4   Esc on HelpOverlay hides it
  5   Dismiss restores focus to HermesInput
  6   Filter by text shows matching commands only
  7   Clearing filter restores full list
  8   UsageOverlay hidden by default
  9   /usage with no agent → flash hint, overlay stays hidden
  10  /usage with agent shows UsageOverlay
  11  /usage dismisses on Esc, restores focus
  12  CommandsOverlay hidden by default
  13  /commands shows CommandsOverlay
  14  ModelOverlay hidden by default
  15  /model (no args) shows ModelOverlay
  16  /model <name> does NOT show ModelOverlay
  17  Only one info overlay visible at a time
  18  All info overlays dismiss when agent starts (watch_agent_running)
  19  _dismiss_all_info_overlays() hides every info overlay
  20  /title with arg → flash hint, returns False
  21  /title no arg → flash warning, returns False
  22  /stop → flash hint, returns False
  23  /new → flash hint, returns False
  24  /clear returns True (handled)
  25  _clear_animation_in_progress prevents re-entry
  26  /commands handler exists in process_command (Phase 1)
  27  show_tools() uses _cprint not print
  28  _show_recent_sessions() uses _cprint not print
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.overlays import (
    CommandsOverlay,
    HelpOverlay,
    ModelOverlay,
    UsageOverlay,
)
from textual.widgets import Input, Static


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app() -> HermesApp:
    cli = MagicMock()
    cli.agent = None  # default: no agent
    return HermesApp(cli=cli)


def _make_app_with_agent() -> HermesApp:
    cli = MagicMock()
    agent = MagicMock()
    agent.model = "claude-sonnet-4-6"
    agent.provider = "anthropic"
    agent.base_url = None
    agent.session_input_tokens = 1000
    agent.session_output_tokens = 500
    agent.session_cache_read_tokens = 200
    agent.session_cache_write_tokens = 100
    agent.session_total_tokens = 1800
    agent.session_api_calls = 3
    agent.context_compressor = MagicMock(
        last_prompt_tokens=8000,
        context_length=200000,
        compression_count=0,
    )
    agent.get_rate_limit_state.return_value = None
    cli.agent = agent
    return HermesApp(cli=cli)


async def _submit(pilot, app, cmd: str) -> None:
    """Submit a command bypassing CompletionOverlay."""
    from hermes_cli.tui.input_widget import HermesInput
    inp = app.query_one(HermesInput)
    inp.value = cmd
    inp.action_submit()
    await pilot.pause()


# ---------------------------------------------------------------------------
# 1–3  HelpOverlay: visibility, focus
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_help_overlay_hidden_by_default():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        overlay = app.query_one(HelpOverlay)
        assert not overlay.has_class("--visible")


@pytest.mark.asyncio
async def test_help_overlay_shows_on_slash_help():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        await _submit(pilot, app, "/help")
        overlay = app.query_one(HelpOverlay)
        assert overlay.has_class("--visible")


@pytest.mark.asyncio
async def test_help_overlay_focuses_search_input():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        await _submit(pilot, app, "/help")
        search = app.query_one("#help-search", Input)
        assert search.has_focus


# ---------------------------------------------------------------------------
# 4–5  HelpOverlay: dismiss
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_help_overlay_escape_hides_it():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        await _submit(pilot, app, "/help")
        assert app.query_one(HelpOverlay).has_class("--visible")
        await pilot.press("escape")
        await pilot.pause()
        assert not app.query_one(HelpOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_help_overlay_dismiss_restores_input_focus():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        from hermes_cli.tui.input_widget import HermesInput
        await pilot.pause()
        await _submit(pilot, app, "/help")
        await pilot.press("escape")
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert inp.has_focus


# ---------------------------------------------------------------------------
# 6–7  HelpOverlay: filter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_help_overlay_filter_narrows_results():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        await _submit(pilot, app, "/help")
        await pilot.pause()
        overlay = app.query_one(HelpOverlay)
        full_count = len(list(overlay.query(Static)))

        search = app.query_one("#help-search", Input)
        search.value = "zzznomatch"
        await pilot.pause()
        filtered_count = len(list(overlay.query(Static)))
        assert filtered_count < full_count


@pytest.mark.asyncio
async def test_help_overlay_filter_clear_restores_all():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        await _submit(pilot, app, "/help")
        await pilot.pause()
        overlay = app.query_one(HelpOverlay)
        full_count = len(list(overlay.query(Static)))

        search = app.query_one("#help-search", Input)
        search.value = "zzznomatch"
        await pilot.pause()
        search.value = ""
        await pilot.pause()
        restored_count = len(list(overlay.query(Static)))
        assert restored_count == full_count


# ---------------------------------------------------------------------------
# 8–11  UsageOverlay
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_usage_overlay_hidden_by_default():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        assert not app.query_one(UsageOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_usage_overlay_no_agent_flashes_hint():
    app = _make_app()  # cli.agent is None
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        with patch.object(app, "_flash_hint") as mock_flash:
            result = app._handle_tui_command("/usage")
        assert result is True
        mock_flash.assert_called_once()
        assert not app.query_one(UsageOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_usage_overlay_shows_with_agent():
    app = _make_app_with_agent()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        with patch("hermes_cli.tui.overlays.UsageOverlay.refresh_data"):
            await _submit(pilot, app, "/usage")
        assert app.query_one(UsageOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_usage_overlay_dismiss_escape():
    app = _make_app_with_agent()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        with patch("hermes_cli.tui.overlays.UsageOverlay.refresh_data"):
            await _submit(pilot, app, "/usage")
        assert app.query_one(UsageOverlay).has_class("--visible")
        await pilot.press("escape")
        await pilot.pause()
        assert not app.query_one(UsageOverlay).has_class("--visible")


# ---------------------------------------------------------------------------
# 12–13  CommandsOverlay
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_commands_overlay_hidden_by_default():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        assert not app.query_one(CommandsOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_commands_overlay_shows_on_slash_commands():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        await _submit(pilot, app, "/commands")
        assert app.query_one(CommandsOverlay).has_class("--visible")


# ---------------------------------------------------------------------------
# 14–16  ModelOverlay
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_model_overlay_hidden_by_default():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        assert not app.query_one(ModelOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_model_overlay_shows_on_slash_model_no_args():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        await _submit(pilot, app, "/model")
        assert app.query_one(ModelOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_model_overlay_not_shown_with_args():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        await _submit(pilot, app, "/model claude-sonnet-4-6")
        assert not app.query_one(ModelOverlay).has_class("--visible")


# ---------------------------------------------------------------------------
# 17  Single overlay at a time
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_only_one_info_overlay_visible():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        await _submit(pilot, app, "/help")
        assert app.query_one(HelpOverlay).has_class("--visible")

        await _submit(pilot, app, "/commands")
        assert not app.query_one(HelpOverlay).has_class("--visible")
        assert app.query_one(CommandsOverlay).has_class("--visible")


# ---------------------------------------------------------------------------
# 18  Auto-dismiss on agent start
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_overlays_dismiss_when_agent_starts():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        await _submit(pilot, app, "/help")
        assert app.query_one(HelpOverlay).has_class("--visible")

        app.agent_running = True
        await pilot.pause()
        assert not app.query_one(HelpOverlay).has_class("--visible")


# ---------------------------------------------------------------------------
# 19  _dismiss_all_info_overlays
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dismiss_all_hides_every_overlay():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        app.query_one(HelpOverlay).add_class("--visible")
        app.query_one(CommandsOverlay).add_class("--visible")
        app._dismiss_all_info_overlays()
        await pilot.pause()
        assert not app.query_one(HelpOverlay).has_class("--visible")
        assert not app.query_one(CommandsOverlay).has_class("--visible")


# ---------------------------------------------------------------------------
# 20–23  Flash hint commands
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_title_with_arg_flashes_and_forwards():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        with patch.object(app, "_flash_hint") as mock_flash:
            result = app._handle_tui_command("/title my-session")
        assert result is False
        mock_flash.assert_called_once()
        args = mock_flash.call_args[0][0]
        assert "my-session" in args


@pytest.mark.asyncio
async def test_title_no_arg_flashes_usage():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        with patch.object(app, "_flash_hint") as mock_flash:
            result = app._handle_tui_command("/title")
        assert result is False
        mock_flash.assert_called_once()
        assert "Usage" in mock_flash.call_args[0][0]


@pytest.mark.asyncio
async def test_stop_flashes_and_forwards():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        with patch.object(app, "_flash_hint") as mock_flash:
            result = app._handle_tui_command("/stop")
        assert result is False
        mock_flash.assert_called_once()


@pytest.mark.asyncio
async def test_new_flashes_and_forwards():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        with patch.object(app, "_flash_hint") as mock_flash:
            result = app._handle_tui_command("/new")
        assert result is False
        mock_flash.assert_called_once()


# ---------------------------------------------------------------------------
# 24–25  /clear
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clear_returns_true():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        with patch.object(app, "_handle_clear_tui"):
            result = app._handle_tui_command("/clear")
        assert result is True


@pytest.mark.asyncio
async def test_clear_prevents_reentry_while_in_progress():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        app._clear_animation_in_progress = True
        call_count = 0

        original = app._handle_clear_tui

        def _spy():
            nonlocal call_count
            call_count += 1
            return original()

        with patch.object(app, "_handle_clear_tui", side_effect=_spy):
            app._handle_tui_command("/clear")
        assert call_count == 0  # blocked by flag


# ---------------------------------------------------------------------------
# 26  /commands handler in process_command (Phase 1)
# ---------------------------------------------------------------------------

def test_commands_has_process_command_handler():
    from hermes_cli.commands import resolve_command
    cmd_def = resolve_command("commands")
    # Even if not in registry, process_command must handle "commands" — verified
    # by inspecting the elif chain in cli.py source.
    import cli as _cli_module
    src = inspect.getsource(_cli_module.HermesCLI.process_command)
    assert '"commands"' in src or "'commands'" in src


# ---------------------------------------------------------------------------
# 27–28  show_tools / _show_recent_sessions use _cprint not print
# ---------------------------------------------------------------------------

def test_show_tools_uses_cprint_not_print():
    import re as _re
    import cli as _cli_module
    src = inspect.getsource(_cli_module.HermesCLI.show_tools)
    # Bare `print(` (not `_cprint(` and not `.print(`) must not appear
    bare_prints = _re.findall(r'(?<![._\w])print\(', src)
    assert not bare_prints, f"Bare print() calls found: {bare_prints}"


def test_show_recent_sessions_uses_cprint_not_print():
    import cli as _cli_module
    src = inspect.getsource(_cli_module.HermesCLI._show_recent_sessions)
    assert "print(" not in src.replace("_cprint(", "")
