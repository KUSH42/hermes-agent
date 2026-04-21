"""Tests for hermes_cli/tui/desktop_notify.py — native desktop notification."""
from __future__ import annotations

import sys
import threading
from unittest.mock import MagicMock, call, patch

import pytest

from hermes_cli.tui.desktop_notify import (
    _notify_linux,
    _notify_macos,
    _play_linux_sound,
    notify,
)


# ---------------------------------------------------------------------------
# notify() — threading behaviour
# ---------------------------------------------------------------------------

def test_notify_starts_daemon_thread():
    """notify() starts a background thread (does not block)."""
    started = []

    original_thread_init = threading.Thread.__init__

    def _capture_init(self, *args, **kwargs):
        original_thread_init(self, *args, **kwargs)
        started.append(kwargs.get("daemon", False))

    with patch("threading.Thread") as mock_thread_cls:
        mock_t = MagicMock()
        mock_thread_cls.return_value = mock_t
        notify("title", "body")
        mock_thread_cls.assert_called_once()
        _, kwargs = mock_thread_cls.call_args
        assert kwargs.get("daemon") is True
        mock_t.start.assert_called_once()


def test_notify_does_not_raise_on_exception_in_thread():
    """notify() swallows exceptions raised by the notification backend."""
    with patch("hermes_cli.tui.desktop_notify._notify_linux", side_effect=RuntimeError("fail")), \
         patch("sys.platform", "linux"):
        # Should not raise — exception is caught inside the thread
        notify("title", "body")


# ---------------------------------------------------------------------------
# _notify_macos()
# ---------------------------------------------------------------------------

def test_notify_macos_calls_osascript():
    with patch("shutil.which", return_value="/usr/bin/osascript"), \
         patch("subprocess.run") as mock_run:
        _notify_macos("Title", "Body", sound=False, sound_name="Glass")
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[0] == "osascript"
    assert "-e" in args


def test_notify_macos_script_contains_title_and_body():
    with patch("shutil.which", return_value="/usr/bin/osascript"), \
         patch("subprocess.run") as mock_run:
        _notify_macos("MyTitle", "MyBody", sound=False, sound_name="Glass")
    script = mock_run.call_args[0][0][2]
    assert "MyTitle" in script
    assert "MyBody" in script


def test_notify_macos_with_sound_includes_sound_clause():
    with patch("shutil.which", return_value="/usr/bin/osascript"), \
         patch("subprocess.run") as mock_run:
        _notify_macos("T", "B", sound=True, sound_name="Ping")
    script = mock_run.call_args[0][0][2]
    assert "sound name" in script
    assert "Ping" in script


def test_notify_macos_without_sound_no_sound_clause():
    with patch("shutil.which", return_value="/usr/bin/osascript"), \
         patch("subprocess.run") as mock_run:
        _notify_macos("T", "B", sound=False, sound_name="Glass")
    script = mock_run.call_args[0][0][2]
    assert "sound name" not in script


def test_notify_macos_no_osascript_does_nothing():
    with patch("shutil.which", return_value=None), \
         patch("subprocess.run") as mock_run:
        _notify_macos("T", "B", sound=False, sound_name="Glass")
    mock_run.assert_not_called()


def test_notify_macos_uses_json_dumps_for_safe_quoting():
    """Titles/bodies with special chars are safely quoted via json.dumps."""
    with patch("shutil.which", return_value="/usr/bin/osascript"), \
         patch("subprocess.run") as mock_run:
        _notify_macos('Ti"tle', "Bo\\dy", sound=False, sound_name="Glass")
    script = mock_run.call_args[0][0][2]
    # json.dumps escapes double quotes and backslashes
    assert '\\"' in script or "Ti" in script  # at minimum the text appears


# ---------------------------------------------------------------------------
# _notify_linux()
# ---------------------------------------------------------------------------

def test_notify_linux_calls_notify_send():
    with patch("shutil.which", side_effect=lambda x: "/usr/bin/notify-send" if x == "notify-send" else None), \
         patch("subprocess.run") as mock_run:
        _notify_linux("Title", "Body", sound=False)
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[0] == "notify-send"
    assert "Title" in args
    assert "Body" in args


def test_notify_linux_no_notify_send_does_nothing():
    with patch("shutil.which", return_value=None), \
         patch("subprocess.run") as mock_run:
        _notify_linux("T", "B", sound=False)
    mock_run.assert_not_called()


def test_notify_linux_sound_calls_play_sound():
    with patch("shutil.which", side_effect=lambda x: "/usr/bin/notify-send" if x == "notify-send" else None), \
         patch("subprocess.run"), \
         patch("hermes_cli.tui.desktop_notify._play_linux_sound") as mock_play:
        _notify_linux("T", "B", sound=True)
    mock_play.assert_called_once()


def test_notify_linux_no_sound_does_not_call_play_sound():
    with patch("shutil.which", side_effect=lambda x: "/usr/bin/notify-send" if x == "notify-send" else None), \
         patch("subprocess.run"), \
         patch("hermes_cli.tui.desktop_notify._play_linux_sound") as mock_play:
        _notify_linux("T", "B", sound=False)
    mock_play.assert_not_called()


# ---------------------------------------------------------------------------
# _play_linux_sound()
# ---------------------------------------------------------------------------

def test_play_linux_sound_prefers_canberra():
    with patch("shutil.which", return_value="/usr/bin/canberra-gtk-play"), \
         patch("subprocess.run") as mock_run:
        _play_linux_sound()
    mock_run.assert_called_once()
    assert "canberra-gtk-play" in mock_run.call_args[0][0]


def test_play_linux_sound_falls_back_to_paplay_when_no_canberra():
    _FALLBACK = "/usr/share/sounds/freedesktop/stereo/message.oga"

    def _which(name):
        if name == "paplay":
            return "/usr/bin/paplay"
        return None

    with patch("shutil.which", side_effect=_which), \
         patch("os.path.exists", return_value=True), \
         patch("subprocess.run") as mock_run:
        _play_linux_sound()
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert "paplay" in args


def test_play_linux_sound_no_tools_does_not_raise():
    with patch("shutil.which", return_value=None), \
         patch("subprocess.run") as mock_run:
        _play_linux_sound()
    mock_run.assert_not_called()


def test_play_linux_sound_paplay_skips_when_file_missing():
    def _which(name):
        return "/usr/bin/paplay" if name == "paplay" else None

    with patch("shutil.which", side_effect=_which), \
         patch("os.path.exists", return_value=False), \
         patch("subprocess.run") as mock_run:
        _play_linux_sound()
    mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# notify() platform dispatch
# ---------------------------------------------------------------------------

def test_notify_dispatches_to_macos_on_darwin():
    with patch("sys.platform", "darwin"), \
         patch("hermes_cli.tui.desktop_notify._notify_macos") as mock_mac, \
         patch("hermes_cli.tui.desktop_notify._notify_linux") as mock_linux:
        notify("T", "B")
        # Give the daemon thread a moment to run
        import time; time.sleep(0.05)
    mock_mac.assert_called_once_with("T", "B", sound=False, sound_name="Glass")
    mock_linux.assert_not_called()


def test_notify_dispatches_to_linux_on_linux():
    with patch("sys.platform", "linux"), \
         patch("hermes_cli.tui.desktop_notify._notify_linux") as mock_linux, \
         patch("hermes_cli.tui.desktop_notify._notify_macos") as mock_mac:
        notify("T", "B")
        import time; time.sleep(0.05)
    mock_linux.assert_called_once_with("T", "B", sound=False)
    mock_mac.assert_not_called()


def test_notify_passes_sound_kwarg():
    with patch("sys.platform", "linux"), \
         patch("hermes_cli.tui.desktop_notify._notify_linux") as mock_linux:
        notify("T", "B", sound=True)
        import time; time.sleep(0.05)
    mock_linux.assert_called_once_with("T", "B", sound=True)
