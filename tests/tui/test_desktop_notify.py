"""Tests for hermes_cli/tui/desktop_notify.py — native desktop notification."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.desktop_notify import (
    _notify_linux,
    _notify_macos,
    _play_linux_sound,
    notify,
)

_SAFE_RUN = "hermes_cli.tui.desktop_notify.safe_run"


# ---------------------------------------------------------------------------
# notify() — dispatch behaviour (RX2: safe_run replaces threading.Thread)
# ---------------------------------------------------------------------------

def test_notify_dispatches_via_safe_run():
    """notify() dispatches via safe_run (non-blocking, off-event-loop)."""
    mock_caller = MagicMock()
    with patch(_SAFE_RUN) as mock_safe_run:
        with patch("shutil.which", return_value="/usr/bin/notify-send"):
            notify("title", "body", caller=mock_caller)
    mock_safe_run.assert_called_once()


def test_notify_does_not_raise():
    """notify() does not raise when no notification tools are available."""
    mock_caller = MagicMock()
    with patch(_SAFE_RUN), \
         patch("shutil.which", return_value=None), \
         patch("sys.platform", "linux"):
        notify("title", "body", caller=mock_caller)  # must not raise


# ---------------------------------------------------------------------------
# _notify_macos()
# ---------------------------------------------------------------------------

def test_notify_macos_calls_osascript():
    mock_caller = MagicMock()
    with patch("shutil.which", return_value="/usr/bin/osascript"), \
         patch(_SAFE_RUN) as mock_safe_run:
        _notify_macos("Title", "Body", caller=mock_caller, sound=False, sound_name="Glass")
    mock_safe_run.assert_called_once()
    cmd = mock_safe_run.call_args[0][1]
    assert cmd[0] == "osascript"
    assert "-e" in cmd


def test_notify_macos_script_contains_title_and_body():
    mock_caller = MagicMock()
    with patch("shutil.which", return_value="/usr/bin/osascript"), \
         patch(_SAFE_RUN) as mock_safe_run:
        _notify_macos("MyTitle", "MyBody", caller=mock_caller, sound=False, sound_name="Glass")
    script = mock_safe_run.call_args[0][1][2]
    assert "MyTitle" in script
    assert "MyBody" in script


def test_notify_macos_with_sound_includes_sound_clause():
    mock_caller = MagicMock()
    with patch("shutil.which", return_value="/usr/bin/osascript"), \
         patch(_SAFE_RUN) as mock_safe_run:
        _notify_macos("T", "B", caller=mock_caller, sound=True, sound_name="Ping")
    script = mock_safe_run.call_args[0][1][2]
    assert "sound name" in script
    assert "Ping" in script


def test_notify_macos_without_sound_no_sound_clause():
    mock_caller = MagicMock()
    with patch("shutil.which", return_value="/usr/bin/osascript"), \
         patch(_SAFE_RUN) as mock_safe_run:
        _notify_macos("T", "B", caller=mock_caller, sound=False, sound_name="Glass")
    script = mock_safe_run.call_args[0][1][2]
    assert "sound name" not in script


def test_notify_macos_no_osascript_does_nothing():
    mock_caller = MagicMock()
    with patch("shutil.which", return_value=None), \
         patch(_SAFE_RUN) as mock_safe_run:
        _notify_macos("T", "B", caller=mock_caller, sound=False, sound_name="Glass")
    mock_safe_run.assert_not_called()


def test_notify_macos_uses_json_dumps_for_safe_quoting():
    """Titles/bodies with special chars are safely quoted via json.dumps."""
    mock_caller = MagicMock()
    with patch("shutil.which", return_value="/usr/bin/osascript"), \
         patch(_SAFE_RUN) as mock_safe_run:
        _notify_macos('Ti"tle', "Bo\\dy", caller=mock_caller, sound=False, sound_name="Glass")
    script = mock_safe_run.call_args[0][1][2]
    assert '\\"' in script or "Ti" in script


# ---------------------------------------------------------------------------
# _notify_linux()
# ---------------------------------------------------------------------------

def test_notify_linux_calls_notify_send():
    mock_caller = MagicMock()
    with patch("shutil.which", side_effect=lambda x: "/usr/bin/notify-send" if x == "notify-send" else None), \
         patch(_SAFE_RUN) as mock_safe_run:
        _notify_linux("Title", "Body", caller=mock_caller, sound=False)
    mock_safe_run.assert_called_once()
    cmd = mock_safe_run.call_args[0][1]
    assert cmd[0] == "notify-send"
    assert "Title" in cmd
    assert "Body" in cmd


def test_notify_linux_no_notify_send_does_nothing():
    mock_caller = MagicMock()
    with patch("shutil.which", return_value=None), \
         patch(_SAFE_RUN) as mock_safe_run:
        _notify_linux("T", "B", caller=mock_caller, sound=False)
    mock_safe_run.assert_not_called()


def test_notify_linux_sound_calls_play_sound():
    mock_caller = MagicMock()
    with patch("shutil.which", side_effect=lambda x: "/usr/bin/notify-send" if x == "notify-send" else None), \
         patch(_SAFE_RUN), \
         patch("hermes_cli.tui.desktop_notify._play_linux_sound") as mock_play:
        _notify_linux("T", "B", caller=mock_caller, sound=True)
    mock_play.assert_called_once_with(caller=mock_caller)


def test_notify_linux_no_sound_does_not_call_play_sound():
    mock_caller = MagicMock()
    with patch("shutil.which", side_effect=lambda x: "/usr/bin/notify-send" if x == "notify-send" else None), \
         patch(_SAFE_RUN), \
         patch("hermes_cli.tui.desktop_notify._play_linux_sound") as mock_play:
        _notify_linux("T", "B", caller=mock_caller, sound=False)
    mock_play.assert_not_called()


# ---------------------------------------------------------------------------
# _play_linux_sound()
# ---------------------------------------------------------------------------

def test_play_linux_sound_prefers_canberra():
    mock_caller = MagicMock()
    with patch("shutil.which", return_value="/usr/bin/canberra-gtk-play"), \
         patch(_SAFE_RUN) as mock_safe_run:
        _play_linux_sound(caller=mock_caller)
    mock_safe_run.assert_called_once()
    cmd = mock_safe_run.call_args[0][1]
    assert "canberra-gtk-play" in cmd


def test_play_linux_sound_falls_back_to_paplay_when_no_canberra():
    def _which(name):
        return "/usr/bin/paplay" if name == "paplay" else None

    mock_caller = MagicMock()
    with patch("shutil.which", side_effect=_which), \
         patch("os.path.exists", return_value=True), \
         patch(_SAFE_RUN) as mock_safe_run:
        _play_linux_sound(caller=mock_caller)
    mock_safe_run.assert_called_once()
    cmd = mock_safe_run.call_args[0][1]
    assert "paplay" in cmd


def test_play_linux_sound_no_tools_does_not_raise():
    mock_caller = MagicMock()
    with patch("shutil.which", return_value=None), \
         patch(_SAFE_RUN) as mock_safe_run:
        _play_linux_sound(caller=mock_caller)
    mock_safe_run.assert_not_called()


def test_play_linux_sound_paplay_skips_when_file_missing():
    def _which(name):
        return "/usr/bin/paplay" if name == "paplay" else None

    mock_caller = MagicMock()
    with patch("shutil.which", side_effect=_which), \
         patch("os.path.exists", return_value=False), \
         patch(_SAFE_RUN) as mock_safe_run:
        _play_linux_sound(caller=mock_caller)
    mock_safe_run.assert_not_called()


# ---------------------------------------------------------------------------
# notify() platform dispatch
# ---------------------------------------------------------------------------

def test_notify_dispatches_to_macos_on_darwin():
    mock_caller = MagicMock()
    with patch("sys.platform", "darwin"), \
         patch("hermes_cli.tui.desktop_notify._notify_macos") as mock_mac, \
         patch("hermes_cli.tui.desktop_notify._notify_linux") as mock_linux:
        notify("T", "B", caller=mock_caller)
    mock_mac.assert_called_once_with("T", "B", caller=mock_caller, sound=False, sound_name="Glass")
    mock_linux.assert_not_called()


def test_notify_dispatches_to_linux_on_linux():
    mock_caller = MagicMock()
    with patch("sys.platform", "linux"), \
         patch("hermes_cli.tui.desktop_notify._notify_linux") as mock_linux, \
         patch("hermes_cli.tui.desktop_notify._notify_macos") as mock_mac:
        notify("T", "B", caller=mock_caller)
    mock_linux.assert_called_once_with("T", "B", caller=mock_caller, sound=False)
    mock_mac.assert_not_called()


def test_notify_passes_sound_kwarg():
    mock_caller = MagicMock()
    with patch("sys.platform", "linux"), \
         patch("hermes_cli.tui.desktop_notify._notify_linux") as mock_linux:
        notify("T", "B", caller=mock_caller, sound=True)
    mock_linux.assert_called_once_with("T", "B", caller=mock_caller, sound=True)
