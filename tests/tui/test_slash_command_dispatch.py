"""Tests for SC-12: slash command "Unknown command" false-positive fix.

Verifies that:
  1  Registry commands that aren't TUI-handled do NOT trigger the flash.
  2  Completely unknown commands (/foobar123) DO trigger the flash.
  3  TUI-handled commands (/clear, /help) dispatch correctly, no flash.
  4  Registry aliases are also recognised (no false flash).
  5  Commands with args pass through without flash when in registry.
  6  Commands with args that are NOT in registry still flash.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app() -> "HermesApp":
    from hermes_cli.tui.app import HermesApp
    cli = MagicMock()
    cli.agent = None
    return HermesApp(cli=cli)


def _call_handle(app, text: str):
    """Call _handle_tui_command without running the full Textual app loop.

    Patches out _flash_hint so we can assert on it, and stubs out any DOM
    queries the handler makes for non-matching branches (the code under test
    for the flash guard doesn't reach DOM).
    """
    flash_calls: list[str] = []

    def _capture_flash(msg: str, *args, **kwargs):
        flash_calls.append(msg)

    app._flash_hint = _capture_flash  # type: ignore[method-assign]
    # Many TUI-handled branches query the DOM.  Patch query_one and query to avoid
    # NoMatches / NotReady errors since we're not running the event loop.
    from unittest.mock import MagicMock
    from textual.css.query import NoMatches
    app.query_one = MagicMock(side_effect=NoMatches("no dom"))  # type: ignore[method-assign]
    app.query = MagicMock(return_value=[])  # type: ignore[method-assign]

    result = app._svc_commands.handle_tui_command(text)
    return result, flash_calls


# ---------------------------------------------------------------------------
# Test 1 — registry command (non-TUI-handled) does NOT flash
# ---------------------------------------------------------------------------

def test_registry_command_no_unknown_flash():
    """Commands in COMMAND_REGISTRY that aren't TUI-handled must not flash."""
    app = _make_app()
    # /profile, /skin, /config, /voice, /effects, /reload-mcp, /browser, /plugins,
    # /paste, /insights, /update, /quit are in the registry but have no special
    # branch in _handle_tui_command — they fall through to CLI.
    # (/verbose, /yolo, /skin, /reasoning are TUI-handled and return True; excluded here)
    for cmd in ("/voice", "/profile", "/config",
                "/effects", "/reload-mcp", "/browser", "/plugins", "/paste",
                "/insights", "/update", "/quit"):
        result, flashes = _call_handle(app, cmd)
        assert result is False, f"{cmd} should return False (forward to agent)"
        assert not any("Unknown command" in f for f in flashes), (
            f"{cmd} should NOT flash Unknown command, but got: {flashes}"
        )


# ---------------------------------------------------------------------------
# Test 2 — made-up command DOES flash
# ---------------------------------------------------------------------------

def test_unknown_command_flashes():
    """Commands not in COMMAND_REGISTRY must trigger the flash."""
    app = _make_app()
    for cmd in ("/foobar123", "/notreal", "/xyzzy"):
        result, flashes = _call_handle(app, cmd)
        assert result is False, f"{cmd} should return False"
        assert any("Unknown command" in f for f in flashes), (
            f"{cmd} should flash Unknown command, but got: {flashes}"
        )


# ---------------------------------------------------------------------------
# Test 3 — TUI-handled commands dispatch correctly, no flash
# ---------------------------------------------------------------------------

def test_tui_handled_clear_dispatches():
    """/clear is TUI-handled; returns True, no Unknown command flash."""
    app = _make_app()
    with patch.object(app._svc_commands, "handle_clear_tui", return_value=None), \
         patch.object(app, "run_worker"):
        result, flashes = _call_handle(app, "/clear")
    assert result is True
    assert not any("Unknown command" in f for f in flashes)


def test_tui_handled_undo_dispatches():
    """/undo returns True, no flash."""
    app = _make_app()
    with patch.object(app._svc_commands, "initiate_undo"):
        result, flashes = _call_handle(app, "/undo")
    assert result is True
    assert not any("Unknown command" in f for f in flashes)


def test_tui_handled_retry_dispatches():
    """/retry returns True, no flash."""
    app = _make_app()
    with patch.object(app._svc_commands, "initiate_retry"):
        result, flashes = _call_handle(app, "/retry")
    assert result is True
    assert not any("Unknown command" in f for f in flashes)


# ---------------------------------------------------------------------------
# Test 4 — aliases are recognised (no false flash)
# ---------------------------------------------------------------------------

def test_registry_aliases_no_unknown_flash():
    """Aliases defined in COMMAND_REGISTRY must also be recognised."""
    app = _make_app()
    # /reset is alias for /new; /exit is alias for /quit; /bg is alias for /background
    for cmd in ("/reset", "/exit", "/bg", "/fork", "/sb",
                "/gateway", "/reload_mcp", "/set-home", "/easteregg"):
        result, flashes = _call_handle(app, cmd)
        assert result is False, f"alias {cmd} should return False"
        assert not any("Unknown command" in f for f in flashes), (
            f"alias {cmd} should NOT flash Unknown command, but got: {flashes}"
        )


# ---------------------------------------------------------------------------
# Test 5 — registry command WITH args passes through silently
# ---------------------------------------------------------------------------

def test_registry_command_with_args_no_flash():
    """/model <name> and /title <text> are in registry with args — no flash."""
    app = _make_app()
    for cmd in ("/model gpt-4o", "/reasoning high", "/skin nord", "/voice on",
                "/verbose off", "/yolo on"):
        result, flashes = _call_handle(app, cmd)
        assert result is False, f"{cmd} should return False"
        assert not any("Unknown command" in f for f in flashes), (
            f"{cmd} should NOT flash Unknown command, but got: {flashes}"
        )


# ---------------------------------------------------------------------------
# Test 6 — unknown command WITH args still flashes
# ---------------------------------------------------------------------------

def test_unknown_command_with_args_flashes():
    """A completely unrecognised command with args must still flash."""
    app = _make_app()
    for cmd in ("/foobar123 some arg", "/notreal thing"):
        result, flashes = _call_handle(app, cmd)
        assert result is False
        assert any("Unknown command" in f for f in flashes), (
            f"{cmd} should flash Unknown command, but got: {flashes}"
        )
