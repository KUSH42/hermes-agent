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
