"""OSC 52 clipboard capability detection for Hermes TUI."""
from __future__ import annotations

import os


def check_clipboard_env() -> bool:
    """Return clipboard-enabled flag based on HERMES_CLIPBOARD env var.

    HERMES_CLIPBOARD=1 → True (force enable)
    HERMES_CLIPBOARD=0 → False (force disable)
    unset / other     → False (safe default; no OSC 52 auto-probe)
    """
    val = os.environ.get("HERMES_CLIPBOARD", "").strip()
    if val == "1":
        return True
    if val == "0":
        return False
    return False
