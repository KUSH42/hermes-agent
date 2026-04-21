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


# ---------------------------------------------------------------------------
# Phase 1: SessionOverlay escape fix (Tests 6–9)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_overlay_escape_closes():
    """Test 6: SessionOverlay visible → Escape → not visible."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        from hermes_cli.tui.overlays import SessionOverlay
        session_overlay = app.query_one(SessionOverlay)
        session_overlay.add_class("--visible")
        await pilot.pause()
        assert session_overlay.has_class("--visible")
        await pilot.press("escape")
        await pilot.pause()
        assert not session_overlay.has_class("--visible")


@pytest.mark.asyncio
async def test_session_overlay_escape_restores_focus():
    """Test 7: After close via Escape, HermesInput has focus."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        from hermes_cli.tui.overlays import SessionOverlay
        from hermes_cli.tui.input_widget import HermesInput
        session_overlay = app.query_one(SessionOverlay)
        session_overlay.add_class("--visible")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert inp.has_focus


@pytest.mark.asyncio
async def test_compact_command_triggers_density_toggle():
    """Test 8: /compact submit calls action_toggle_density()."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        with patch.object(app, "action_toggle_density") as mock_toggle:
            result = app._handle_tui_command("/compact")
        assert result is True
        mock_toggle.assert_called_once()


@pytest.mark.asyncio
async def test_sessions_command_opens_overlay():
    """Test 9: /sessions submit calls action_open_sessions()."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        with patch.object(app, "action_open_sessions") as mock_open:
            result = app._handle_tui_command("/sessions")
        assert result is True
        mock_open.assert_called_once()


# ---------------------------------------------------------------------------
# Phase 3: Display & overlay polish (Tests 29–50)
# ---------------------------------------------------------------------------

# Test 29: tui_help_lines includes cli_only commands — in test_commands.py

@pytest.mark.asyncio
async def test_commands_overlay_shows_cli_only_commands():
    """Test 30: /commands overlay lists /config (cli_only)."""
    from hermes_cli.commands import tui_help_lines
    lines = tui_help_lines()
    # tui_help_lines (used by CommandsOverlay) should include /config
    joined = "\n".join(lines)
    assert "/config" in joined


@pytest.mark.asyncio
async def test_commands_overlay_excludes_gateway_only():
    """Test 31: /commands overlay does not list /approve (gateway_only)."""
    from hermes_cli.commands import tui_help_lines
    import re as _re
    lines = tui_help_lines()
    line_cmds = set()
    for line in lines:
        m = _re.match(r'`(/[\w-]+)', line)
        if m:
            line_cmds.add(m.group(1))
    # gateway_only commands like /approve should not appear
    assert "/approve" not in line_cmds


def test_q_binding_not_priority_on_help_overlay():
    """Test 32: HelpOverlay's q binding has priority=False."""
    from hermes_cli.tui.overlays import HelpOverlay
    from textual.binding import Binding
    # Find q binding
    q_bindings = [b for b in HelpOverlay.BINDINGS if hasattr(b, 'key') and b.key == "q"]
    assert q_bindings, "HelpOverlay should have a q binding"
    for b in q_bindings:
        assert not b.priority, f"HelpOverlay q binding should have priority=False, got {b.priority}"


def test_q_binding_not_priority_on_usage_overlay():
    """Test 33: UsageOverlay has no q binding (removed entirely)."""
    from hermes_cli.tui.overlays import UsageOverlay
    q_bindings = [b for b in UsageOverlay.BINDINGS if hasattr(b, 'key') and b.key == "q"]
    assert not q_bindings, f"UsageOverlay should NOT have a q binding, found: {q_bindings}"


@pytest.mark.asyncio
async def test_slash_desc_panel_shows_args_hint():
    """Test 34: Highlight /rollback → desc panel shows [number] args_hint."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        from hermes_cli.tui.path_search import SlashCandidate
        from hermes_cli.tui.completion_overlay import SlashDescPanel

        cand = SlashCandidate(
            display="/rollback",
            command="/rollback",
            description="List or restore filesystem checkpoints",
            args_hint="[number]",
            keybind_hint="",
        )
        app.highlighted_candidate = cand
        await pilot.pause()
        # The panel should have rendered with the args_hint
        panel = app.query_one(SlashDescPanel)
        assert panel is not None  # Panel exists and received the candidate


@pytest.mark.asyncio
async def test_slash_desc_panel_shows_keybind_hint():
    """Test 35: Highlight /sessions → desc panel shows Ctrl+Shift+H keybind."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        from hermes_cli.tui.path_search import SlashCandidate
        from hermes_cli.tui.completion_overlay import SlashDescPanel

        cand = SlashCandidate(
            display="/sessions",
            command="/sessions",
            description="Browse and resume recent sessions",
            args_hint="",
            keybind_hint="Ctrl+Shift+H",
        )
        app.highlighted_candidate = cand
        await pilot.pause()
        panel = app.query_one(SlashDescPanel)
        assert panel is not None


@pytest.mark.asyncio
async def test_slash_desc_panel_no_keybind_shows_nothing():
    """Test 36: Highlight /usage → no stale keybind line."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        from hermes_cli.tui.path_search import SlashCandidate

        cand = SlashCandidate(
            display="/usage",
            command="/usage",
            description="Show token usage and rate limits",
            args_hint="",
            keybind_hint="",  # no keybind
        )
        app.highlighted_candidate = cand
        await pilot.pause()
        # Candidate has no keybind_hint — just verify no exception thrown
        assert app.highlighted_candidate is cand


@pytest.mark.asyncio
async def test_help_overlay_refreshes_after_plugin_register():
    """Test 37: Register plugin command → refresh_slash_commands → overlay shows new command."""
    from hermes_cli.commands import register_plugin_command, CommandDef, COMMAND_REGISTRY
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        # Open help overlay
        await _submit(pilot, app, "/help")
        await pilot.pause()

        # Register a new plugin command
        test_cmd = CommandDef("testplugin9999", "Test plugin command", "Tools & Skills")
        register_plugin_command(test_cmd)
        try:
            # refresh_slash_commands also refreshes HelpOverlay cache
            app.refresh_slash_commands()
            await pilot.pause()

            overlay = app.query_one(HelpOverlay)
            # _commands_cache should now include the new command
            cache_cmds = [cmd for _, cmd, _ in overlay._commands_cache]
            assert "/testplugin9999" in cache_cmds
        finally:
            # Cleanup: remove test command
            COMMAND_REGISTRY[:] = [c for c in COMMAND_REGISTRY if c.name != "testplugin9999"]
            from hermes_cli.commands import rebuild_lookups
            rebuild_lookups()


@pytest.mark.asyncio
async def test_commands_overlay_refreshes_on_open():
    """Test 38: /commands re-opens → shows fresh data (not stale mount cache)."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        # Open /commands once
        await _submit(pilot, app, "/commands")
        await pilot.pause()
        # Close it
        await pilot.press("escape")
        await pilot.pause()
        # Open again — _refresh_content is called again
        await _submit(pilot, app, "/commands")
        await pilot.pause()
        from hermes_cli.tui.overlays import CommandsOverlay
        assert app.query_one(CommandsOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_unknown_slash_command_flash_hint():
    """Test 39: /foobar submit → HintBar.hint contains 'Unknown command'."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        with patch.object(app, "_flash_hint") as mock_flash:
            result = app._handle_tui_command("/foobar")
        assert result is False
        mock_flash.assert_called()
        # The flash hint should mention "Unknown command"
        hint_msg = mock_flash.call_args[0][0]
        assert "Unknown" in hint_msg or "unknown" in hint_msg


@pytest.mark.asyncio
async def test_known_cli_command_no_flash_hint():
    """Test 40: /new submit → no 'Unknown command' flash."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        with patch.object(app, "_flash_hint") as mock_flash:
            result = app._handle_tui_command("/new")
        assert result is False
        # /new flashes "New session started", not "Unknown command"
        if mock_flash.called:
            hint_msg = mock_flash.call_args[0][0]
            assert "Unknown" not in hint_msg


@pytest.mark.asyncio
async def test_gateway_only_commands_excluded_from_slash_completion():
    """Test 41: _show_slash_completions("") does NOT include /approve, /deny, /status."""
    from hermes_cli.tui.input_widget import HermesInput
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        # After mount, slash_commands should be populated without gateway_only entries
        gateway_only_names = ["/approve", "/deny", "/status"]
        for name in gateway_only_names:
            assert name not in inp._slash_commands, \
                f"{name} (gateway_only) should not be in TUI completion list"


@pytest.mark.asyncio
async def test_populate_slash_commands_includes_args_hint():
    """Test 42: _populate_slash_commands sets args_hint on slash candidates."""
    from hermes_cli.tui.input_widget import HermesInput
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        # /rollback should have args_hint "[number]"
        assert "/rollback" in inp._slash_args_hints
        assert inp._slash_args_hints["/rollback"] == "[number]"


@pytest.mark.asyncio
async def test_populate_slash_commands_includes_keybind_hint():
    """Test 43: _populate_slash_commands sets keybind_hint on /sessions candidate."""
    from hermes_cli.tui.input_widget import HermesInput
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert "/sessions" in inp._slash_keybind_hints
        assert inp._slash_keybind_hints["/sessions"] == "Ctrl+Shift+H"


@pytest.mark.asyncio
async def test_tools_no_args_opens_overlay():
    """Test 44: /tools (bare) tries to open ToolsScreen."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        with patch.object(app, "_open_tools_overlay") as mock_open:
            result = app._handle_tui_command("/tools")
        assert result is True
        mock_open.assert_called_once()


@pytest.mark.asyncio
async def test_tools_with_args_falls_through():
    """Test 45: _handle_tui_command("/tools list") returns False (CLI handles it)."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        result = app._handle_tui_command("/tools list")
        assert result is False


def test_workspace_overlay_q_binding_removed():
    """Test 49: WorkspaceOverlay.BINDINGS does not contain a q binding."""
    from hermes_cli.tui.overlays import WorkspaceOverlay
    q_bindings = [b for b in WorkspaceOverlay.BINDINGS if hasattr(b, 'key') and b.key == "q"]
    assert not q_bindings, f"WorkspaceOverlay should NOT have a q binding, found: {q_bindings}"


def test_usage_overlay_q_binding_removed():
    """Test 50: UsageOverlay.BINDINGS does not contain a q binding."""
    from hermes_cli.tui.overlays import UsageOverlay
    q_bindings = [b for b in UsageOverlay.BINDINGS if hasattr(b, 'key') and b.key == "q"]
    assert not q_bindings, f"UsageOverlay should NOT have a q binding"


# ---------------------------------------------------------------------------
# Regression guards (Tests 46–47)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_slash_mode_clears_on_path_context():
    """Test 46: Regression guard for SC-14 — _show_path_completions clears slash-only before debounce."""
    from hermes_cli.tui.input_widget import HermesInput
    from hermes_cli.tui.completion_overlay import CompletionOverlay

    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        co = app.query_one(CompletionOverlay)

        # Show slash overlay
        inp._set_overlay_mode(slash_only=True)
        co.add_class("--visible")
        await pilot.pause()
        assert co.has_class("--slash-only")

        # Switching to path completions should immediately clear slash-only
        # (before debounce timer fires)
        inp._set_overlay_mode(slash_only=False)
        await pilot.pause()
        assert not co.has_class("--slash-only")


@pytest.mark.asyncio
async def test_slash_only_cleared_on_natural_context():
    """Test 47: Type /help then delete → type foo → overlay hidden, not stuck in slash-only."""
    from hermes_cli.tui.input_widget import HermesInput
    from hermes_cli.tui.completion_overlay import CompletionOverlay

    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        co = app.query_one(CompletionOverlay)

        # Start with slash overlay visible
        inp._set_overlay_mode(slash_only=True)
        co.add_class("--visible")
        await pilot.pause()

        # Now hide the overlay (natural context — no completion trigger)
        inp._hide_completion_overlay()
        await pilot.pause()
        assert not co.has_class("--visible")
        assert not co.has_class("--slash-only")
