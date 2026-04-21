"""Tests for /schedule and /fast slash command handling.

T01  /fast not in KNOWN_SLASH_COMMANDS
T02  on_hermes_input_submitted drops /fast (unknown command gate)
T03  bare /schedule flashes usage hint, returns True (not forwarded)
T04  /schedule <text> flashes confirmation, returns False (forwarded)
T05  /schedule still in KNOWN_SLASH_COMMANDS
T06  resolve_command("schedule") returns a CommandDef
T07  /schedule <text> does NOT flash "Unknown command"
T08  on_hermes_input_submitted does not put bare /schedule on _pending_input
T09  extra whitespace /schedule still forwards (returns False)
T10  resolve_command("fast") returns None
T11  schedule CommandDef has cli_only=False
T12  schedule CommandDef has non-empty args_hint
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest

from hermes_cli.tui import _app_constants
from hermes_cli.tui.app import HermesApp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app() -> HermesApp:
    cli = MagicMock()
    cli.agent = None
    return HermesApp(cli=cli)


# ---------------------------------------------------------------------------
# T01  /fast removed from KNOWN_SLASH_COMMANDS
# ---------------------------------------------------------------------------

def test_fast_not_in_known_slash_commands():
    assert "/fast" not in _app_constants.KNOWN_SLASH_COMMANDS


# ---------------------------------------------------------------------------
# T02  on_hermes_input_submitted drops /fast — unknown command gate fires
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fast_blocked_by_gate():
    """Submitting /fast must flash 'Unknown command' and NOT put on _pending_input."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        flash_calls: list[tuple] = []
        app.cli._pending_input = MagicMock()

        with patch.object(app, "_flash_hint", side_effect=lambda msg, dur: flash_calls.append((msg, dur))):
            from hermes_cli.tui.input_widget import HermesInput
            inp = app.query_one(HermesInput)
            inp.value = "/fast"
            inp.action_submit()
            await pilot.pause()

        # Unknown command flash must have fired
        assert any("Unknown command" in msg for msg, _ in flash_calls), \
            f"Expected 'Unknown command' flash; got: {flash_calls}"
        # Message must NOT have been forwarded to agent via _pending_input.put
        app.cli._pending_input.put.assert_not_called()


# ---------------------------------------------------------------------------
# T03  bare /schedule — flash usage hint, return True (not forwarded)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bare_schedule_flashes_usage_and_returns_true():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        with patch.object(app, "_flash_hint") as mock_flash:
            result = app._handle_tui_command("/schedule")
        assert result is True
        mock_flash.assert_called_once()
        hint_msg = mock_flash.call_args[0][0]
        assert "Tell the agent what to schedule" in hint_msg


# ---------------------------------------------------------------------------
# T04  /schedule <text> — flash confirmation, return False (forward)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_schedule_with_text_flashes_and_forwards():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        with patch.object(app, "_flash_hint") as mock_flash:
            result = app._handle_tui_command("/schedule check logs every hour")
        assert result is False
        mock_flash.assert_called_once()
        hint_msg = mock_flash.call_args[0][0]
        assert "📅" in hint_msg


# ---------------------------------------------------------------------------
# T05  /schedule still in KNOWN_SLASH_COMMANDS
# ---------------------------------------------------------------------------

def test_schedule_in_known_slash_commands():
    assert "/schedule" in _app_constants.KNOWN_SLASH_COMMANDS


# ---------------------------------------------------------------------------
# T06  resolve_command("schedule") returns a CommandDef
# ---------------------------------------------------------------------------

def test_schedule_resolvable_from_registry():
    from hermes_cli.commands import resolve_command
    assert resolve_command("schedule") is not None


# ---------------------------------------------------------------------------
# T07  /schedule <text> does NOT flash "Unknown command"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_schedule_with_text_no_unknown_command_flash():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        flash_calls: list[tuple] = []
        with patch.object(app, "_flash_hint", side_effect=lambda msg, dur: flash_calls.append((msg, dur))):
            result = app._handle_tui_command("/schedule do something useful")
        # Must return False (forward to agent)
        assert result is False
        # No "Unknown command" flash
        assert not any("Unknown command" in msg for msg, _ in flash_calls), \
            f"Unexpected 'Unknown command' flash: {flash_calls}"
        # Exactly one call with the calendar emoji
        calendar_calls = [msg for msg, _ in flash_calls if "📅" in msg]
        assert len(calendar_calls) == 1


# ---------------------------------------------------------------------------
# T08  on_hermes_input_submitted does not put bare /schedule on _pending_input
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bare_schedule_not_forwarded_to_agent():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        app.cli._pending_input = MagicMock()

        with patch.object(app, "_flash_hint"):
            from hermes_cli.tui.input_widget import HermesInput
            inp = app.query_one(HermesInput)
            inp.value = "/schedule"
            inp.action_submit()
            await pilot.pause()

        app.cli._pending_input.put.assert_not_called()


# ---------------------------------------------------------------------------
# T09  extra whitespace /schedule still forwards
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_schedule_with_extra_whitespace_forwards():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        with patch.object(app, "_flash_hint") as mock_flash:
            result = app._handle_tui_command("/schedule   run nightly  backup  ")
        assert result is False
        mock_flash.assert_called_once()
        hint_msg = mock_flash.call_args[0][0]
        assert "📅" in hint_msg


# ---------------------------------------------------------------------------
# T10  resolve_command("fast") returns None
# ---------------------------------------------------------------------------

def test_fast_not_in_registry():
    from hermes_cli.commands import resolve_command
    assert resolve_command("fast") is None


# ---------------------------------------------------------------------------
# T11  schedule CommandDef has cli_only=False
# ---------------------------------------------------------------------------

def test_schedule_commanddef_not_cli_only():
    from hermes_cli.commands import resolve_command
    cmd = resolve_command("schedule")
    assert cmd is not None
    assert cmd.cli_only is False


# ---------------------------------------------------------------------------
# T12  schedule CommandDef has non-empty args_hint
# ---------------------------------------------------------------------------

def test_schedule_commanddef_has_args_hint():
    from hermes_cli.commands import resolve_command
    cmd = resolve_command("schedule")
    assert cmd is not None
    assert cmd.args_hint != ""
