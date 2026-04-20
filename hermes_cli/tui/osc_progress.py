"""OSC 9;4 indeterminate terminal progress bar.

Emits escape sequences to the terminal's own fd — compatible with Ghostty,
iTerm2, Rio, WezTerm, and Windows Terminal.  All other terminals silently
ignore the sequences.

Must only be called from the Textual event loop thread (same pattern as
osc52_probe.py — os.write to stdout.fileno() is safe during TUI operation).
"""
from __future__ import annotations

import os
import sys

_OSC_PROGRESS_START = b"\x1b]9;4;3;\x07"   # indeterminate
_OSC_PROGRESS_END   = b"\x1b]9;4;0;\x07"   # clear

_SUPPORTED_TERM_PROGRAMS = frozenset({"ghostty", "iterm.app", "rio", "wezterm"})


def is_supported() -> bool:
    """Return True if the terminal is known to support OSC 9;4.

    Checks $HERMES_OSC_PROGRESS first (override: "1" force-on, "0" force-off),
    then $TERM_PROGRAM against a known-compatible set, then $WT_SESSION
    (Windows Terminal).
    """
    override = os.environ.get("HERMES_OSC_PROGRESS", "").strip()
    if override == "1":
        return True
    if override == "0":
        return False
    term_prog = os.environ.get("TERM_PROGRAM", "").strip().lower()
    if term_prog in _SUPPORTED_TERM_PROGRAMS:
        return True
    if os.environ.get("WT_SESSION"):
        return True
    return False


def osc_progress_start() -> None:
    """Emit indeterminate-start sequence. No-op if terminal not supported."""
    if not is_supported():
        return
    try:
        os.write(sys.stdout.fileno(), _OSC_PROGRESS_START)
    except Exception:
        pass


def osc_progress_end() -> None:
    """Emit clear sequence. No-op if terminal not supported."""
    if not is_supported():
        return
    try:
        os.write(sys.stdout.fileno(), _OSC_PROGRESS_END)
    except Exception:
        pass
