"""Tests for SPEC-E: OSC 52 clipboard capability detection.

Covers:
  1-6:  probe_osc52() behaviour under various terminal conditions
  7-10: HermesApp._copy_text_with_hint() clipboard guard
  11-13: check_clipboard_env() env var parsing
  14:   browse-mode 'c' key with clipboard unavailable
  15:   context menu "Copy tool output" with clipboard unavailable
  16-20: find_xclip_cmd() and xclip fallback in _copy_text_with_hint()
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.osc52_probe import check_clipboard_env, find_xclip_cmd, probe_osc52
from hermes_cli.tui.widgets import HintBar


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(clipboard_available: bool = True) -> HermesApp:
    return HermesApp(cli=MagicMock(), clipboard_available=clipboard_available)


# ---------------------------------------------------------------------------
# Tests 1-6: probe_osc52()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_osc52_returns_true_on_valid_response():
    """probe_osc52() returns True when terminal responds with valid OSC 52 data."""
    import types

    valid_response = b"\033]52;c;dGVzdA==\a"

    fake_termios = types.ModuleType("termios")
    fake_termios.tcgetattr = MagicMock(return_value=[0] * 19)
    fake_termios.tcsetattr = MagicMock()
    fake_termios.TCSADRAIN = 1

    fake_tty = types.ModuleType("tty")
    fake_tty.setraw = MagicMock()

    # Call sequence:
    # 1: run_in_executor initial wait → fd ready
    # 2: drain loop first read → fd has data
    # 3: drain loop second read → no more data
    call_count = [0]

    def _fake_select(rlist, wlist, xlist, timeout=None):
        call_count[0] += 1
        if call_count[0] <= 2:
            return ([0], [], [])  # fd ready / has data
        return ([], [], [])  # drain complete

    fake_select = types.ModuleType("select")
    fake_select.select = _fake_select

    with (
        patch.dict("sys.modules", {"termios": fake_termios, "tty": fake_tty, "select": fake_select}),
        patch("sys.platform", "linux"),
        patch("os.isatty", return_value=True),
        patch("sys.stdin") as mock_stdin,
        patch("sys.stdout") as mock_stdout,
        patch("os.write"),
        patch("os.read", return_value=valid_response),
    ):
        mock_stdin.fileno.return_value = 0
        mock_stdout.fileno.return_value = 1
        result = await probe_osc52()

    assert result is True


@pytest.mark.asyncio
async def test_probe_osc52_returns_true_valid_response_via_mocking():
    """probe_osc52() returns True for valid OSC 52 response (duplicate confirmation)."""
    import types

    valid_response = b"\033]52;c;dGVzdA==\a"

    fake_termios = types.ModuleType("termios")
    fake_termios.tcgetattr = MagicMock(return_value=[0] * 19)
    fake_termios.tcsetattr = MagicMock()
    fake_termios.TCSADRAIN = 1

    fake_tty = types.ModuleType("tty")
    fake_tty.setraw = MagicMock()

    call_count = [0]

    def _fake_select(rlist, wlist, xlist, timeout=None):
        call_count[0] += 1
        if call_count[0] <= 2:
            return ([0], [], [])  # fd ready on first, data available on second
        return ([], [], [])  # no more data

    fake_select = types.ModuleType("select")
    fake_select.select = _fake_select

    with (
        patch.dict("sys.modules", {"termios": fake_termios, "tty": fake_tty, "select": fake_select}),
        patch("sys.platform", "linux"),
        patch("os.isatty", return_value=True),
        patch("sys.stdin") as mock_stdin,
        patch("sys.stdout") as mock_stdout,
        patch("os.write"),
        patch("os.read", return_value=valid_response),
    ):
        mock_stdin.fileno.return_value = 0
        mock_stdout.fileno.return_value = 1
        result = await probe_osc52()

    assert result is True


@pytest.mark.asyncio
async def test_probe_osc52_returns_false_on_timeout():
    """probe_osc52() returns False when select times out (no OSC 52 support)."""
    import types

    fake_termios = types.ModuleType("termios")
    fake_termios.tcgetattr = MagicMock(return_value=[0] * 19)
    fake_termios.tcsetattr = MagicMock()
    fake_termios.TCSADRAIN = 1

    fake_tty = types.ModuleType("tty")
    fake_tty.setraw = MagicMock()

    fake_select = types.ModuleType("select")
    fake_select.select = MagicMock(return_value=([], [], []))  # always timeout

    with (
        patch.dict("sys.modules", {"termios": fake_termios, "tty": fake_tty, "select": fake_select}),
        patch("sys.platform", "linux"),
        patch("os.isatty", return_value=True),
        patch("sys.stdin") as mock_stdin,
        patch("sys.stdout") as mock_stdout,
        patch("os.write"),
    ):
        mock_stdin.fileno.return_value = 0
        mock_stdout.fileno.return_value = 1
        result = await probe_osc52()

    assert result is False


@pytest.mark.asyncio
async def test_probe_osc52_returns_false_when_not_a_tty():
    """probe_osc52() returns False immediately when stdin is not a TTY."""
    import types

    fake_termios = types.ModuleType("termios")
    fake_termios.tcgetattr = MagicMock(return_value=[0] * 19)
    fake_termios.tcsetattr = MagicMock()
    fake_termios.TCSADRAIN = 1

    fake_tty = types.ModuleType("tty")
    fake_tty.setraw = MagicMock()

    fake_select = types.ModuleType("select")
    fake_select.select = MagicMock(return_value=([], [], []))

    with (
        patch.dict("sys.modules", {"termios": fake_termios, "tty": fake_tty, "select": fake_select}),
        patch("sys.platform", "linux"),
        patch("os.isatty", return_value=False),
        patch("sys.stdin") as mock_stdin,
    ):
        mock_stdin.fileno.return_value = 0
        result = await probe_osc52()

    assert result is False


@pytest.mark.asyncio
async def test_probe_osc52_returns_false_on_windows():
    """probe_osc52() returns False immediately on Windows without importing termios."""
    with patch("sys.platform", "win32"):
        result = await probe_osc52()

    assert result is False


@pytest.mark.asyncio
async def test_probe_osc52_returns_false_when_tcgetattr_raises():
    """probe_osc52() returns False and does not raise when tcgetattr raises OSError."""
    import types

    fake_termios = types.ModuleType("termios")
    fake_termios.tcgetattr = MagicMock(side_effect=OSError("not a terminal"))
    fake_termios.tcsetattr = MagicMock()
    fake_termios.TCSADRAIN = 1

    fake_tty = types.ModuleType("tty")
    fake_tty.setraw = MagicMock()

    fake_select = types.ModuleType("select")
    fake_select.select = MagicMock(return_value=([], [], []))

    with (
        patch.dict("sys.modules", {"termios": fake_termios, "tty": fake_tty, "select": fake_select}),
        patch("sys.platform", "linux"),
        patch("os.isatty", return_value=True),
        patch("sys.stdin") as mock_stdin,
        patch("sys.stdout") as mock_stdout,
    ):
        mock_stdin.fileno.return_value = 0
        mock_stdout.fileno.return_value = 1
        result = await probe_osc52()

    assert result is False
    # Verify tcsetattr was NOT called (old_settings is None when tcgetattr raises)
    fake_termios.tcsetattr.assert_not_called()


@pytest.mark.asyncio
async def test_probe_osc52_returns_false_for_echoed_probe():
    """probe_osc52() returns False when terminal echoes the probe bytes back."""
    import types
    from hermes_cli.tui.osc52_probe import _OSC52_PROBE

    # The echoed response is the exact probe bytes
    echoed_response = _OSC52_PROBE.encode()

    fake_termios = types.ModuleType("termios")
    fake_termios.tcgetattr = MagicMock(return_value=[0] * 19)
    fake_termios.tcsetattr = MagicMock()
    fake_termios.TCSADRAIN = 1

    fake_tty = types.ModuleType("tty")
    fake_tty.setraw = MagicMock()

    call_count = [0]

    def _fake_select(rlist, wlist, xlist, timeout=None):
        call_count[0] += 1
        if call_count[0] == 1:
            return ([0], [], [])
        return ([], [], [])

    fake_select = types.ModuleType("select")
    fake_select.select = _fake_select

    with (
        patch.dict("sys.modules", {"termios": fake_termios, "tty": fake_tty, "select": fake_select}),
        patch("sys.platform", "linux"),
        patch("os.isatty", return_value=True),
        patch("sys.stdin") as mock_stdin,
        patch("sys.stdout") as mock_stdout,
        patch("os.write"),
        patch("os.read", return_value=echoed_response),
    ):
        mock_stdin.fileno.return_value = 0
        mock_stdout.fileno.return_value = 1
        result = await probe_osc52()

    assert result is False


# ---------------------------------------------------------------------------
# Tests 7-10: HermesApp._copy_text_with_hint()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_copy_text_with_hint_clipboard_unavailable_shows_warning():
    """When clipboard unavailable, _copy_text_with_hint flashes a warning."""
    app = _make_app(clipboard_available=False)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app._copy_text_with_hint("x")
        await pilot.pause()
        bar = app.query_one(HintBar)
        assert "Clipboard unavailable" in bar.hint or "clipboard" in bar.hint.lower()


@pytest.mark.asyncio
async def test_copy_text_with_hint_clipboard_unavailable_does_not_call_copy():
    """When clipboard unavailable, copy_to_clipboard is NOT called."""
    app = _make_app(clipboard_available=False)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        with patch.object(app, "copy_to_clipboard") as mock_copy:
            app._copy_text_with_hint("hello")
            await pilot.pause()
        mock_copy.assert_not_called()


@pytest.mark.asyncio
async def test_copy_text_with_hint_clipboard_available_shows_chars_copied():
    """When clipboard available, _copy_text_with_hint flashes N chars copied."""
    app = _make_app(clipboard_available=True)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        with patch.object(app, "copy_to_clipboard"):
            app._copy_text_with_hint("hello")
            await pilot.pause()
        bar = app.query_one(HintBar)
        assert "5" in bar.hint  # len("hello") == 5


@pytest.mark.asyncio
async def test_copy_text_with_hint_clipboard_available_calls_copy():
    """When clipboard available, copy_to_clipboard is called exactly once."""
    app = _make_app(clipboard_available=True)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        with patch.object(app, "copy_to_clipboard") as mock_copy:
            app._copy_text_with_hint("hello")
            await pilot.pause()
        mock_copy.assert_called_once_with("hello")


# ---------------------------------------------------------------------------
# Tests 11-13: check_clipboard_env()
# ---------------------------------------------------------------------------


def test_check_clipboard_env_returns_true_when_set_to_1():
    """HERMES_CLIPBOARD=1 → check_clipboard_env() returns True."""
    with patch.dict(os.environ, {"HERMES_CLIPBOARD": "1"}):
        result = check_clipboard_env()
    assert result is True


def test_check_clipboard_env_returns_false_when_set_to_0():
    """HERMES_CLIPBOARD=0 → check_clipboard_env() returns False."""
    with patch.dict(os.environ, {"HERMES_CLIPBOARD": "0"}):
        result = check_clipboard_env()
    assert result is False


def test_check_clipboard_env_returns_none_when_unset():
    """HERMES_CLIPBOARD unset → check_clipboard_env() returns None."""
    env = {k: v for k, v in os.environ.items() if k != "HERMES_CLIPBOARD"}
    with patch.dict(os.environ, env, clear=True):
        result = check_clipboard_env()
    assert result is None


# ---------------------------------------------------------------------------
# Test 14: browse-mode 'c' key with clipboard unavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_browse_mode_c_key_clipboard_unavailable_shows_warning():
    """Browse-mode 'c' with clipboard unavailable shows warning hint."""
    from hermes_cli.tui.widgets import OutputPanel
    from hermes_cli.tui.tool_blocks import ToolBlock

    app = _make_app(clipboard_available=False)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Mount a ToolBlock so browse mode has something to navigate
        lines = [f"line {i}" for i in range(5)]
        plain = [f"plain {i}" for i in range(5)]
        output = app.query_one(OutputPanel)
        block = ToolBlock("test_tool", lines, plain)
        await output.mount(block)
        await pilot.pause()

        # Enter browse mode
        app.browse_mode = True
        app.browse_index = 0
        await pilot.pause()

        # Press 'c' in browse mode
        with patch.object(app, "copy_to_clipboard") as mock_copy:
            await pilot.press("c")
            await pilot.pause()
        mock_copy.assert_not_called()

        bar = app.query_one(HintBar)
        assert "clipboard" in bar.hint.lower() or "unavailable" in bar.hint.lower()


# ---------------------------------------------------------------------------
# Test 15: Context menu "Copy tool output" with clipboard unavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_menu_copy_tool_output_clipboard_unavailable():
    """Context menu 'Copy tool output' with clipboard unavailable shows warning hint."""
    from hermes_cli.tui.widgets import OutputPanel
    from hermes_cli.tui.tool_blocks import ToolBlock

    app = _make_app(clipboard_available=False)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        lines = [f"line {i}" for i in range(5)]
        plain = [f"plain {i}" for i in range(5)]
        output = app.query_one(OutputPanel)
        block = ToolBlock("test_tool", lines, plain)
        await output.mount(block)
        await pilot.pause()

        # Invoke _copy_tool_output directly (mimics context menu action)
        with patch.object(app, "copy_to_clipboard") as mock_copy:
            app._copy_tool_output(block)
            await pilot.pause()
        mock_copy.assert_not_called()

        bar = app.query_one(HintBar)
        assert "clipboard" in bar.hint.lower() or "unavailable" in bar.hint.lower()


# ---------------------------------------------------------------------------
# Tests 16-24: find_xclip_cmd() and xclip fallback
# ---------------------------------------------------------------------------


def test_find_xclip_cmd_prefers_wl_copy_on_wayland():
    """Wayland sessions prefer wl-copy when both clipboard tool classes exist."""
    def _which(name):
        return f"/usr/bin/{name}" if name in {"wl-copy", "xclip", "xsel"} else None

    with patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-0"}, clear=True), \
         patch("shutil.which", side_effect=_which):
        result = find_xclip_cmd()
    assert result == ["wl-copy"]


def test_find_xclip_cmd_prefers_xclip_on_x11_even_if_wl_copy_exists():
    """X11 sessions prefer xclip over wl-copy when both are installed."""
    def _which(name):
        return f"/usr/bin/{name}" if name in {"wl-copy", "xclip"} else None

    with patch.dict("os.environ", {"DISPLAY": ":0"}, clear=True), \
         patch("shutil.which", side_effect=_which):
        result = find_xclip_cmd()
    assert result == ["xclip", "-selection", "clipboard"]


def test_find_xclip_cmd_prefers_xsel_on_x11_when_xclip_absent():
    """X11 sessions fall back to xsel before wl-copy."""
    def _which(name):
        return f"/usr/bin/{name}" if name in {"wl-copy", "xsel"} else None

    with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}, clear=True), \
         patch("shutil.which", side_effect=_which):
        result = find_xclip_cmd()
    assert result == ["xsel", "--clipboard", "--input"]


def test_find_xclip_cmd_falls_back_to_wl_copy_without_session_hint():
    """Without session hints, the first available backend is still acceptable."""
    with patch.dict("os.environ", {}, clear=True), \
         patch("shutil.which", side_effect=lambda x: "/usr/bin/wl-copy" if x == "wl-copy" else None):
        result = find_xclip_cmd()
    assert result == ["wl-copy"]


def test_find_xclip_cmd_returns_none_when_nothing_found():
    """find_xclip_cmd() returns None when no clipboard tool is on PATH."""
    with patch("shutil.which", return_value=None):
        result = find_xclip_cmd()
    assert result is None


@pytest.mark.asyncio
async def test_copy_text_with_hint_uses_xclip_when_osc52_unavailable():
    """When OSC 52 unavailable but xclip present, _copy_text_with_hint uses subprocess."""
    app = HermesApp(cli=MagicMock(), clipboard_available=False, xclip_cmd=["xclip", "-selection", "clipboard"])
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            app._copy_text_with_hint("hello")
            await pilot.pause()
        mock_run.assert_called_once_with(
            ["xclip", "-selection", "clipboard"],
            input=b"hello",
            check=True,
            timeout=2,
            stdout=ANY,
            stderr=ANY,
        )
        bar = app.query_one(HintBar)
        assert "5" in bar.hint  # len("hello") == 5


@pytest.mark.asyncio
async def test_copy_text_with_hint_xclip_subprocess_failure_shows_error():
    """When xclip subprocess raises, _copy_text_with_hint shows an error hint."""
    app = HermesApp(cli=MagicMock(), clipboard_available=False, xclip_cmd=["xclip", "-selection", "clipboard"])
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        with patch("subprocess.run", side_effect=OSError("xclip not found")):
            app._copy_text_with_hint("hello")
            await pilot.pause()
        bar = app.query_one(HintBar)
        assert "fail" in bar.hint.lower() or "error" in bar.hint.lower()


@pytest.mark.asyncio
async def test_clipboard_warning_hidden_when_xclip_available():
    """Status bar clipboard warning is NOT shown when xclip is available as fallback."""
    app = HermesApp(cli=MagicMock(), clipboard_available=False, xclip_cmd=["xclip", "-selection", "clipboard"])
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        warning = app.query_one("#status-clipboard-warning")
        assert "--active" not in warning.classes


@pytest.mark.asyncio
async def test_clipboard_warning_shown_when_both_unavailable():
    """Status bar clipboard warning IS shown when both OSC 52 and xclip are unavailable."""
    app = HermesApp(cli=MagicMock(), clipboard_available=False, xclip_cmd=None)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        warning = app.query_one("#status-clipboard-warning")
        assert "--active" in warning.classes
