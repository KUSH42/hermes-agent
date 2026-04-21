"""OSC 52 clipboard capability probe.

Must be called BEFORE App.run() — uses a separate event loop to avoid
racing with Textual's terminal ownership.
"""

from __future__ import annotations

import asyncio
import os
import sys

_OSC52_PROBE = "\033]52;c;?\a"   # BEL terminator
_PROBE_TIMEOUT = 0.5             # seconds to wait for terminal response


async def probe_osc52() -> bool:
    """Return True if the terminal responds to an OSC 52 read-back probe.

    False is returned (not raised) for ALL failure conditions:
    - Not a TTY
    - Not Linux/macOS (Windows: termios unavailable)
    - Timeout (terminal supports set-only or no OSC 52)
    - Exception in terminal raw-mode handling

    Callers should treat False conservatively (clipboard unavailable).
    The HERMES_CLIPBOARD env var overrides this result entirely.
    """
    # Platform guard: termios is POSIX-only
    if sys.platform == "win32":
        return False

    import termios  # import inside function: avoids ImportError on Windows
    import tty
    import select

    fd = sys.stdin.fileno()
    if not os.isatty(fd):
        return False

    old_settings = None  # initialize before try so finally block can safely check
    try:
        old_settings = termios.tcgetattr(fd)
        tty.setraw(fd)

        # Send the probe
        os.write(sys.stdout.fileno(), _OSC52_PROBE.encode())

        # Wait for initial response data
        loop = asyncio.get_event_loop()
        ready = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: select.select([fd], [], [], _PROBE_TIMEOUT)),
            timeout=_PROBE_TIMEOUT + 0.1,  # outer timeout slightly longer than inner
        )
        if not ready[0]:
            return False  # timeout — not supported

        # Drain all available response bytes (50 ms timeout per read)
        response = b""
        while True:
            r, _, _ = select.select([fd], [], [], 0.05)
            if not r:
                break
            chunk = os.read(fd, 256)
            if not chunk:
                break
            response += chunk

        # Validate: response must contain OSC 52 header, NOT be the echoed probe itself
        # A terminal that doesn't support OSC 52 may echo the probe bytes literally.
        # Valid responses contain ESC]52 followed by a semicolon-separated payload.
        if b"\033]52;c;" in response or b"\x9d52;c;" in response:
            # Ensure it's a genuine response, not the echoed probe
            # The echoed probe would match exactly _OSC52_PROBE bytes
            if response.strip() != _OSC52_PROBE.encode().strip():
                return True

        return False

    except Exception:
        return False

    finally:
        # `termios` was imported earlier in this function (after the win32 guard).
        # On any code path that reaches `finally` with `old_settings is not None`,
        # the `import termios` line above has already executed successfully — so
        # `termios` is available in this scope without re-importing.
        if old_settings is not None:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except Exception:
                pass  # best-effort restore


def check_clipboard_env() -> bool | None:
    """Return True/False if HERMES_CLIPBOARD env var is set, else None (run probe)."""
    val = os.environ.get("HERMES_CLIPBOARD", "").strip()
    if val == "1":
        return True
    if val == "0":
        return False
    return None


def find_xclip_cmd() -> list[str] | None:
    """Return a subprocess argv for piping text to the system clipboard, or None.

    Prefers clipboard tools that match the active session type when possible:
    Wayland sessions prefer wl-copy; X11 sessions prefer xclip/xsel.
    Falls back to any available tool if the preferred class is absent.
    Returns None if none are found on PATH.
    """
    import shutil

    session_type = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
    has_wayland = bool(os.environ.get("WAYLAND_DISPLAY")) or session_type == "wayland"
    has_x11 = bool(os.environ.get("DISPLAY")) or session_type == "x11"

    wl_copy = ["wl-copy"] if shutil.which("wl-copy") else None
    xclip = ["xclip", "-selection", "clipboard"] if shutil.which("xclip") else None
    xsel = ["xsel", "--clipboard", "--input"] if shutil.which("xsel") else None

    if has_wayland:
        return wl_copy or xclip or xsel
    if has_x11:
        return xclip or xsel or wl_copy

    return wl_copy or xclip or xsel
