"""Native desktop notification + optional sound.

Backend priority:
  1. notify-send  (Linux)
  2. osascript    (macOS)
  3. silent no-op (unsupported platform / missing tools)

All subprocess calls happen in a daemon thread — never blocks the event loop.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading


def notify(
    title: str,
    body: str,
    *,
    sound: bool = False,
    sound_name: str = "Glass",
) -> None:
    """Fire a native desktop notification in a background daemon thread.

    Args:
        title: Notification title.
        body:  Notification body text.
        sound: Play a sound alongside the notification.
        sound_name: macOS sound name (ignored on Linux).
    """
    def _run() -> None:
        try:
            if sys.platform == "darwin":
                _notify_macos(title, body, sound=sound, sound_name=sound_name)
            else:
                _notify_linux(title, body, sound=sound)
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


def _notify_macos(title: str, body: str, *, sound: bool, sound_name: str) -> None:
    if not shutil.which("osascript"):
        return
    # json.dumps produces valid double-quoted AppleScript string literals.
    sound_clause = f" sound name {json.dumps(sound_name)}" if sound else ""
    script = (
        f"display notification {json.dumps(body)} "
        f"with title {json.dumps(title)}"
        f"{sound_clause}"
    )
    subprocess.run(["osascript", "-e", script], check=False,
                   capture_output=True, timeout=5)


def _notify_linux(title: str, body: str, *, sound: bool) -> None:
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", title, body], check=False,
                       capture_output=True, timeout=5)
    if sound:
        _play_linux_sound()


def _play_linux_sound() -> None:
    """Play freedesktop message sound. Tries canberra-gtk-play then paplay."""
    if shutil.which("canberra-gtk-play"):
        subprocess.run(
            ["canberra-gtk-play", "--id=message-new-instant"],
            check=False, capture_output=True, timeout=5,
        )
        return
    _FALLBACK = "/usr/share/sounds/freedesktop/stereo/message.oga"
    if shutil.which("paplay"):
        import os
        if os.path.exists(_FALLBACK):
            subprocess.run(["paplay", _FALLBACK], check=False,
                           capture_output=True, timeout=5)
