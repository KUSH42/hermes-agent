"""Native desktop notification + optional sound.

Backend priority:
  1. notify-send  (Linux)
  2. osascript    (macOS)
  3. silent no-op (unsupported platform / missing tools)

All subprocess calls are dispatched via safe_run (io_boundary) — off the event loop.
"""
from __future__ import annotations

import json
import shutil
import sys
from typing import TYPE_CHECKING

from hermes_cli.tui.io_boundary import safe_run

if TYPE_CHECKING:
    from textual.app import App
    from textual.widget import Widget


def notify(
    title: str,
    body: str,
    *,
    caller: "App | Widget",
    sound: bool = False,
    sound_name: str = "Glass",
) -> None:
    """Fire a native desktop notification via safe_run.

    Args:
        title:      Notification title.
        body:       Notification body text.
        caller:     App or Widget — passed to safe_run for worker dispatch.
        sound:      Play a sound alongside the notification.
        sound_name: macOS sound name (ignored on Linux).
    """
    if sys.platform == "darwin":
        _notify_macos(title, body, caller=caller, sound=sound, sound_name=sound_name)
    else:
        _notify_linux(title, body, caller=caller, sound=sound)


def _notify_macos(
    title: str,
    body: str,
    *,
    caller: "App | Widget",
    sound: bool,
    sound_name: str,
) -> None:
    if not shutil.which("osascript"):
        return
    # json.dumps produces valid double-quoted AppleScript string literals.
    sound_clause = f" sound name {json.dumps(sound_name)}" if sound else ""
    script = (
        f"display notification {json.dumps(body)} "
        f"with title {json.dumps(title)}"
        f"{sound_clause}"
    )
    safe_run(caller, ["osascript", "-e", script], timeout=5, on_error=None)


def _notify_linux(
    title: str,
    body: str,
    *,
    caller: "App | Widget",
    sound: bool,
) -> None:
    if shutil.which("notify-send"):
        safe_run(caller, ["notify-send", title, body], timeout=5, on_error=None)
    if sound:
        _play_linux_sound(caller=caller)


def _play_linux_sound(*, caller: "App | Widget", sound_name: str = "Glass") -> None:
    """Play freedesktop message sound. Tries canberra-gtk-play then paplay."""
    if shutil.which("canberra-gtk-play"):
        safe_run(
            caller,
            ["canberra-gtk-play", "--id=message-new-instant"],
            timeout=5,
            on_error=None,
        )
        return
    _FALLBACK = "/usr/share/sounds/freedesktop/stereo/message.oga"
    if shutil.which("paplay"):
        import os
        if os.path.exists(_FALLBACK):
            safe_run(caller, ["paplay", _FALLBACK], timeout=5, on_error=None)
